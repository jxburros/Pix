"""Fixed-project REST and MCP services; file access stays inside the project boundary."""

import base64
from contextlib import contextmanager
import hmac
import json
from pathlib import Path

from filelock import FileLock

from .assets import add_image, decode
from .errors import PixError, require
from .model import Limits
from .project import Project
from .validation import validate


class Session:
    def __init__(self, path, limits=None):
        self.path = Path(path).resolve()
        self.limits = limits or Limits()
        Project.load(self.path, limits=self.limits)

    @contextmanager
    def project(self, write=False):
        with FileLock(str(self.path) + ".lock", timeout=10, is_singleton=True):
            project = Project.load(self.path, limits=self.limits)
            yield project
            if write:
                project.save()

    def inspect(self):
        with self.project() as p:
            return p.inspect()

    def apply(self, operations, dry_run=False):
        from .render import EFFECTS
        from .operations import OPERATION_TYPES

        if isinstance(operations, dict):
            operations = operations.get("operations", [operations])
        require(isinstance(operations, list), "Expected operation array")
        for operation in operations:
            require(isinstance(operation, dict), "Expected operation object")
            kind = operation.get("type", operation.get("operation"))
            # Service clients import images explicitly. They cannot read arbitrary server files,
            # enable plugins, or resolve linked assets or fonts supplied by a remote request.
            require(
                not any(k in operation for k in ("path", "linked", "font")),
                "Filesystem fields are unavailable through services",
                "forbidden",
            )
            require(kind in set(OPERATION_TYPES) | set(EFFECTS), "Unsupported service operation")
            if kind == "effect":
                require(operation.get("name") in EFFECTS, "Service clients cannot load plugins", "forbidden")
            if kind == "mask":
                require(
                    operation.get("action") != "import", "Import masks using embedded assets", "forbidden"
                )
        with self.project(write=not dry_run) as p:
            return p.apply(operations, dry_run=dry_run)

    def render(self, variables=None):
        with self.project() as p:
            return p.export(variables=variables, format="PNG")

    def validate(self, profile=None, rules=None):
        with self.project() as p:
            return validate(p, profile, rules)

    def history(self, action="list", ref=None, count=1):
        require(
            action
            in ("list", "undo", "redo", "branch", "checkpoint", "checkout", "begin", "commit", "rollback"),
            "Unknown history action",
        )
        with self.project(write=action != "list") as p:
            if action in ("undo", "redo"):
                getattr(p, action)(count)
            elif action in ("branch", "checkpoint", "checkout"):
                getattr(p, action)(ref)
            elif action in ("begin", "commit", "rollback"):
                getattr(p, action)()
            return {
                "head": p.head,
                "branch": p.current_branch,
                "branches": p.branches,
                "checkpoints": p.checkpoints,
                "nodes": [{k: v for k, v in node.items() if k != "state"} for node in p.nodes.values()],
            }

    def import_image(self, data, name="image"):
        with self.project(write=True) as p:
            image = decode(data, p.limits)
            asset = add_image(p, image)
            p.apply({"type": "add", "asset": asset, "name": name})
            return p.inspect(p.state["active_layer"])

    def ai(self, command, args):
        from .ai import ai_command

        require(command in ("ask", "generate", "ai", "select", "detect", "ocr"), "Unsupported AI command")
        require(isinstance(args, list) and all(isinstance(x, str) for x in args), "AI args must be strings")
        require(not any(x in ("-h", "--help") for x in args), "Help flags are not service commands")
        with self.project() as p:
            result, changed = ai_command(p, command, args)
            if changed:
                p.save()
            return result


def create_app(path, *, token=None, limits=None):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse, Response
        from starlette.middleware.trustedhost import TrustedHostMiddleware
    except ImportError as exc:
        raise PixError("missing_dependency", "Install pix-engine[server]") from exc
    session = Session(path, limits)
    app = FastAPI(title="Pix Engine", version="0.7.0")
    if not token:
        app.add_middleware(
            TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
        )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if token and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": "cross_origin_forbidden"}, status_code=403)
        maximum = session.limits.max_asset_bytes if request.url.path == "/assets" else 1024 * 1024
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                return JSONResponse({"error": "resource_limit"}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.exception_handler(PixError)
    async def pix_error(request: Request, exc: PixError):
        return JSONResponse(exc.as_dict(), status_code=403 if exc.code == "forbidden" else 400)

    @app.get("/schema")
    def schema():
        from .schema import operation_schema

        return operation_schema()

    @app.get("/document")
    def document():
        return session.inspect()

    @app.get("/layers")
    def layers():
        return session.inspect()["layers"]

    @app.post("/operations")
    def operations(body: dict):
        return session.apply(body.get("operations"), bool(body.get("dry_run", False)))

    @app.get("/render")
    def render():
        return Response(session.render(), media_type="image/png")

    @app.post("/render")
    def render_variables(body: dict):
        return Response(session.render(body.get("variables")), media_type="image/png")

    @app.post("/validate")
    def validation(body: dict):
        return session.validate(body.get("profile"), body.get("rules"))

    @app.get("/history")
    def history():
        return session.history()

    @app.post("/history/{action}")
    def history_action(action: str, body: dict):
        return session.history(action, body.get("ref"), body.get("count", 1))

    @app.post("/assets")
    async def assets(request: Request, name: str = "image"):
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(session.import_image, await request.body(), name)

    @app.post("/ai/{command}")
    def ai(command: str, body: dict):
        return session.ai(command, body.get("args", []))

    return app


def serve(path, host="127.0.0.1", port=8765, token=None, limits=None):
    require(
        host in ("127.0.0.1", "localhost", "::1") or token,
        "Non-loopback serving requires PIX_API_TOKEN",
        "authentication_required",
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise PixError("missing_dependency", "Install pix-engine[server]") from exc
    uvicorn.run(create_app(path, token=token, limits=limits), host=host, port=port)


def mcp_server(path, limits=None):
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:
        raise PixError("missing_dependency", "Install pix-engine[mcp]") from exc
    session = Session(path, limits)
    server = FastMCP(
        "Pix",
        instructions="Inspect the document, submit canonical operations, validate, and render. All editing is atomic; use dry_run to preview changes. No arbitrary filesystem access.",
    )

    @server.tool()
    def pix_document_inspect() -> dict:
        """Inspect canvas, stable layer IDs, editable effects, bounds, selection and history."""
        return session.inspect()

    @server.tool()
    def pix_operations_apply(operations: list[dict], dry_run: bool = False) -> dict:
        """Apply an atomic operation batch. E.g. [{type: move, target: logo, x: 10, y: 20}]."""
        return session.apply(operations, dry_run)

    @server.tool()
    def pix_render_preview(variables: dict | None = None) -> Image:
        """Render the current project as a PNG image without modifying it."""
        return Image(data=session.render(variables), format="png")

    @server.tool()
    def pix_validate(profile: str | None = None, rules: list[str] | None = None) -> dict:
        """Check bounds, export profiles and assertions without changing the document."""
        return session.validate(profile, rules)

    @server.tool()
    def pix_history(action: str = "list", ref: str | None = None, count: int = 1) -> dict:
        """List history or undo, redo, branch, checkpoint, checkout, begin, commit, rollback."""
        return session.history(action, ref, count)

    @server.tool()
    def pix_import_image(image_base64: str, name: str = "image") -> dict:
        """Import image bytes as an embedded layer. Does not read host file paths."""
        require(len(image_base64) <= 90 * 1024 * 1024, "Image input exceeds limit")
        try:
            data = base64.b64decode(image_base64, validate=True)
        except ValueError as exc:
            raise PixError("invalid_image", "Invalid base64") from exc
        return session.import_image(data, name)

    @server.tool()
    def pix_ai(command: str, args: list[str]) -> dict:
        """Use a locally configured provider for ask, generate, ai, select, detect or ocr."""
        return session.ai(command, args)

    @server.resource("pix://operations")
    def operations_reference() -> str:
        from .schema import operation_schema

        return json.dumps(operation_schema())

    return server
