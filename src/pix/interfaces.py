"""Cached project sessions, fixed-project REST and workspace-scoped MCP services."""

from contextlib import contextmanager
import hmac
from pathlib import Path
from threading import RLock

from filelock import FileLock

from .assets import add_image, decode
from .errors import PixError, require
from .model import Limits
from .project import Project
from .validation import validate


class Session:
    def __init__(self, path=None, limits=None, *, workspace=None):
        self.limits = limits or Limits()
        self.workspace = Path(workspace or (Path(path).resolve().parent if path else Path.cwd())).resolve()
        require(self.workspace.is_dir(), "Workspace must be an existing directory")
        self.path = None
        self._cached = None
        self._stamp = None
        self._mutex = RLock()
        if path:
            self.open(path if workspace else Path(path).resolve())

    def resolve(self, path):
        resolved = (self.workspace / path).resolve()
        require(resolved.is_relative_to(self.workspace), "Path is outside the workspace", "forbidden")
        return resolved

    @staticmethod
    def stamp(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def open(self, path):
        with self._mutex:
            resolved = self.resolve(path)
            with FileLock(str(resolved) + ".lock", timeout=10, is_singleton=True):
                stamp = self.stamp(resolved)
                project = Project.load(resolved, limits=self.limits)
                self.path, self._cached, self._stamp = resolved, project, stamp
            return self.summary(project)

    def create(self, path, width, height, background="transparent"):
        with self._mutex:
            resolved = self.resolve(path)
            require(resolved.suffix.lower() == ".pix", "Document path must end in .pix")
            require(resolved.parent.is_dir(), "Destination directory must exist")
            with FileLock(str(resolved) + ".lock", timeout=10, is_singleton=True):
                require(not resolved.exists(), "Destination already exists")
                project = Project(width, height, background, limits=self.limits)
                project.save(resolved)
                self.path, self._cached, self._stamp = resolved, project, self.stamp(resolved)
            return self.summary(project)

    def summary(self, project):
        return {
            "path": str(self.path.relative_to(self.workspace)),
            "canvas": project.state["canvas"],
            "layer_count": len(project.state["layers"]),
            "head": project.head,
        }

    @contextmanager
    def project(self, write=False):
        # Serialize threads and cooperating CLI/service writers. Revalidate only when disk changes.
        with self._mutex:
            require(self.path is not None, "Create or open a document first", "no_project")
            with FileLock(str(self.path) + ".lock", timeout=10, is_singleton=True):
                try:
                    stamp = self.stamp(self.path)
                    if self._cached is None or stamp != self._stamp:
                        self._cached = Project.load(self.path, limits=self.limits)
                        self._stamp = stamp
                    revision = self._cached._revision
                    yield self._cached
                    if write:
                        self._cached.save()
                    if self._cached._revision != revision:
                        self._stamp = self.stamp(self.path)
                except BaseException:
                    # A failed provider, operation or save must never leave unsaved cached state.
                    self._cached = None
                    self._stamp = None
                    raise

    def inspect(self):
        with self.project() as p:
            return p.inspect()

    def apply(self, operations, dry_run=False, detail="compact"):
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
                not any(k in operation for k in ("linked", "font"))
                and ("path" not in operation or kind == "text-layout"),
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
            return p.apply(operations, dry_run=dry_run, detail=detail)

    def render(self, variables=None, artboard=None, comp=None):
        with self.project() as p:
            return p.export(variables=variables, artboard=artboard, comp=comp, format="PNG")

    def measure(self, **options):
        with self.project() as p:
            return p.measure(**options)

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
    app = FastAPI(title="Pix Engine", version="0.8.0")
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
        return session.apply(
            body.get("operations"), bool(body.get("dry_run", False)), body.get("detail", "compact")
        )

    @app.get("/render")
    def render():
        return Response(session.render(), media_type="image/png")

    @app.post("/render")
    def render_variables(body: dict):
        return Response(
            session.render(body.get("variables"), body.get("artboard"), body.get("comp")),
            media_type="image/png",
        )

    @app.post("/measure")
    def measure(body: dict):
        return session.measure(**body)

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


def mcp_server(path=None, limits=None, *, workspace=None):
    try:
        from .mcp_tools import build_server
        import mcp.server.fastmcp  # noqa: F401
    except ImportError as exc:
        raise PixError("missing_dependency", "Install pix-engine[mcp]") from exc

    return build_server(Session(path, limits, workspace=workspace))
