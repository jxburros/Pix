"""Cached project sessions, fixed-project REST and workspace-scoped MCP services."""

from contextlib import contextmanager
import hmac
from pathlib import Path
from threading import RLock

from filelock import FileLock

from .assets import add_encoded
from .errors import VixlError, require
from .model import Limits
from . import __version__
from .project import Project
from .validation import validate


def service_check(operation):
    """Restrictions for remote/agent callers, applied after normalization so aliases such as
    ``font_family`` cannot bypass them. Service clients import images explicitly; they cannot
    read arbitrary server files, enable plugins, or resolve linked assets or fonts."""
    from .render import EFFECTS
    from .operations import OPERATION_TYPES

    kind = operation.get("type")
    require(
        not any(k in operation for k in ("linked", "font"))
        and ("path" not in operation or kind in ("text-layout", "shape")),
        "Filesystem fields (path, linked, font) are unavailable through services; "
        "import images with vixl_import_image and reference the returned asset",
        "forbidden",
        field=next((k for k in ("path", "linked", "font") if k in operation), None),
    )
    require(kind in set(OPERATION_TYPES) | set(EFFECTS), "Unsupported service operation", field="type")
    if kind == "effect":
        import difflib

        name = operation.get("name")
        close = difflib.get_close_matches(str(name), EFFECTS, 2, 0.5)
        require(
            name in EFFECTS,
            f"Unknown effect {name!r}"
            + (f"; did you mean {' or '.join(map(repr, close))}?" if close else "; see allowed for built-in effects"),
            "forbidden",
            field="name",
            allowed=list(EFFECTS),
            suggestions=close,
        )
    if kind == "mask":
        require(operation.get("action") != "import", "Import masks using embedded assets", "forbidden")


class _Document:
    __slots__ = ("path", "project", "stamp")

    def __init__(self, path, project, stamp):
        self.path, self.project, self.stamp = path, project, stamp


class Session:
    """Workspace-scoped documents kept loaded between calls.

    Several documents can be open at once (bounded LRU); every method takes an optional
    ``document`` path and otherwise uses the active document."""

    MAX_OPEN = 8

    def __init__(self, path=None, limits=None, *, workspace=None):
        self.limits = limits or Limits()
        self.workspace = Path(workspace or (Path(path).resolve().parent if path else Path.cwd())).resolve()
        require(self.workspace.is_dir(), "Workspace must be an existing directory")
        self.path = None
        self.documents = {}
        self._mutex = RLock()
        if path:
            self.open(path if workspace else Path(path).resolve())

    def resolve(self, path):
        resolved = (self.workspace / path).resolve()
        require(resolved.is_relative_to(self.workspace), "Path is outside the workspace", "forbidden", field="path")
        return resolved

    def relative(self, path):
        return str(Path(path).relative_to(self.workspace))

    @staticmethod
    def stamp(path):
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _remember(self, path, project, stamp):
        self.documents.pop(path, None)
        self.documents[path] = _Document(path, project, stamp)
        while len(self.documents) > self.MAX_OPEN:
            oldest = next(iter(self.documents))
            if oldest == path:
                break
            del self.documents[oldest]  # Everything is already saved; reopening reloads it.
        self.path = path

    def open(self, path):
        with self._mutex:
            resolved = self.resolve(path)
            require(resolved.is_file(), f"Document does not exist: {path}", "not_found", field="path")
            with FileLock(str(resolved) + ".lock", timeout=10, is_singleton=True):
                stamp = self.stamp(resolved)
                project = Project.load(resolved, limits=self.limits)
                self._remember(resolved, project, stamp)
            return self.summary(project)

    def create(self, path, width, height, background="transparent"):
        with self._mutex:
            resolved = self.resolve(path)
            require(resolved.suffix.lower() == ".vixl", "Document path must end in .vixl", field="path")
            require(resolved.parent.is_dir(), "Destination directory must exist", field="path")
            with FileLock(str(resolved) + ".lock", timeout=10, is_singleton=True):
                require(not resolved.exists(), "Destination already exists; open it instead", field="path")
                project = Project(width, height, background, limits=self.limits)
                project.save(resolved)
                self._remember(resolved, project, self.stamp(resolved))
            return self.summary(project)

    def close(self, document=None):
        with self._mutex:
            path = self.resolve(document) if document else self.path
            require(path in self.documents, "Document is not open", "no_project", field="document")
            del self.documents[path]
            if self.path == path:
                self.path = next(reversed(self.documents), None)
            return self.open_documents()

    def open_documents(self):
        return {
            "active": self.relative(self.path) if self.path else None,
            "open": [self.relative(path) for path in self.documents],
        }

    def summary(self, project, path=None):
        return {
            "path": self.relative(path or self.path),
            "canvas": project.state["canvas"],
            "layer_count": len(project.state["layers"]),
            "head": project.head,
        }

    @contextmanager
    def project(self, write=False, document=None):
        # Serialize threads and cooperating CLI/service writers. Revalidate only when disk changes.
        with self._mutex:
            if document:
                path = self.resolve(document)
                require(path.suffix.lower() == ".vixl", "Document path must end in .vixl", field="document")
                if path not in self.documents:
                    require(path.is_file(), f"Document does not exist: {document}", "not_found", field="document")
            else:
                require(self.path is not None, "Create or open a document first", "no_project")
                path = self.path
            with FileLock(str(path) + ".lock", timeout=10, is_singleton=True):
                entry = self.documents.get(path)
                try:
                    stamp = self.stamp(path)
                    if entry is None or entry.project is None or stamp != entry.stamp:
                        entry = _Document(path, Project.load(path, limits=self.limits), stamp)
                    # Addressing a document explicitly keeps it open but does not change the active one.
                    self.documents.pop(path, None)
                    self.documents[path] = entry
                    while len(self.documents) > self.MAX_OPEN:
                        oldest = next(iter(self.documents))
                        if oldest in (path, self.path):
                            break
                        del self.documents[oldest]
                    project = entry.project
                    revision = project._revision
                    yield project
                    if write:
                        project.save()
                    if project._revision != revision:
                        entry.stamp = self.stamp(path)
                except BaseException:
                    # A failed provider, operation or save must never leave unsaved cached state.
                    self.documents.pop(path, None)
                    if self.path == path and not path.exists():
                        self.path = None
                    raise

    def inspect(self, target=None, document=None):
        with self.project(document=document) as p:
            return p.inspect(target)

    def apply(self, operations, dry_run=False, detail="compact", document=None):
        if isinstance(operations, dict):
            operations = operations.get("operations", [operations])
        require(isinstance(operations, list), "Expected operation array")
        with self.project(write=not dry_run, document=document) as p:
            return p.apply(operations, dry_run=dry_run, detail=detail, check=service_check)

    def render(self, variables=None, artboard=None, comp=None, document=None):
        with self.project(document=document) as p:
            return p.export(variables=variables, artboard=artboard, comp=comp, format="PNG")

    def measure_spacing(self, document=None, **options):
        with self.project(document=document) as p:
            return p.measure_spacing(**options)

    def measure(self, document=None, **options):
        with self.project(document=document) as p:
            return p.measure(**options)

    def check(self, document=None, **options):
        with self.project(document=document) as p:
            return p.check(**options)

    def validate(self, profile=None, rules=None, document=None):
        with self.project(document=document) as p:
            return validate(p, profile, rules)

    def history(self, action="list", ref=None, count=1, document=None):
        require(
            action
            in ("list", "undo", "redo", "branch", "checkpoint", "checkout", "begin", "commit", "rollback"),
            "Unknown history action",
            field="action",
        )
        with self.project(write=action != "list", document=document) as p:
            if action in ("undo", "redo"):
                getattr(p, action)(count)
            elif action in ("branch", "checkpoint", "checkout"):
                require(ref, f"History {action} requires ref", field="ref")
                getattr(p, action)(ref)
            elif action in ("begin", "commit", "rollback"):
                getattr(p, action)()
            return {
                "head": p.head,
                "branch": p.current_branch,
                "branches": p.branches,
                "checkpoints": p.checkpoints,
                "nodes": [{k: v for k, v in node.items() if k not in ("state", "delta")} for node in p.nodes.values()],
            }

    def import_image(self, data, name="image", document=None):
        with self.project(write=True, document=document) as p:
            asset, _ = add_encoded(p, data)
            p.apply({"type": "add", "asset": asset, "name": name})
            layer = p.inspect(p.state["active_layer"])
            return {
                "id": layer["id"],
                "name": layer["name"],
                "width": layer["width"],
                "height": layer["height"],
                "bounds": layer["resolved_bounds"],
                "asset": asset,
            }

    def ai(self, command, args, document=None):
        from .ai import ai_command

        require(command in ("ask", "generate", "ai", "select", "detect", "ocr"), "Unsupported AI command")
        require(isinstance(args, list) and all(isinstance(x, str) for x in args), "AI args must be strings")
        require(not any(x in ("-h", "--help") for x in args), "Help flags are not service commands")
        with self.project(document=document) as p:
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
        raise VixlError("missing_dependency", "Install vixl-engine[server]") from exc
    session = Session(path, limits)
    app = FastAPI(title="Vixl Engine", version=__version__)
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
        maximum = session.limits.max_asset_bytes if request.url.path in ("/assets", "/fonts") else 1024 * 1024
        if request.url.path == "/fonts":
            maximum = min(maximum, 16 * 1024 * 1024)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > maximum:
                return JSONResponse({"error": "resource_limit"}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.exception_handler(VixlError)
    async def vixl_error(request: Request, exc: VixlError):
        return JSONResponse(exc.as_dict(), status_code=403 if exc.code == "forbidden" else 400)

    @app.get("/schema")
    def schema():
        from .schema import operation_schema

        return operation_schema()

    @app.get("/resources/{kind}")
    def resources_list(kind: str):
        from .resources import catalog

        return {"names": sorted(catalog(kind))}

    @app.get("/resources/{kind}/{name}")
    def resource_get(kind: str, name: str):
        from .resources import get

        return {"name": name, "value": get(kind, name)}

    @app.post("/resources/{kind}/{name}")
    def resource_add(kind: str, name: str, body: dict):
        from .resources import register

        return register(kind, name, body.get("value"))

    @app.post("/export")
    def export_document(body: dict):
        allowed = {
            "format",
            "quality",
            "scale",
            "variables",
            "background",
            "artboard",
            "comp",
            "sampling",
            "profile",
            "svg_policy",
        }
        require(set(body) <= allowed, "Unknown export option")
        fmt = body.get("format", "PNG").upper()
        media = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "SVG": "image/svg+xml",
            "WEBP": "image/webp",
            "TIFF": "image/tiff",
            "AVIF": "image/avif",
        }
        require(fmt in media, "Unsupported export format")
        with session.project() as project:
            return Response(project.export(**body), media_type=media[fmt])

    @app.post("/fonts")
    async def fonts(request: Request, name: str):
        import hashlib
        from .fonts import validate_font

        data = await request.body()
        validate_font(data)
        with session.project(write=True) as project:
            asset = f"fonts/{hashlib.sha256(data).hexdigest()}.ttf"
            project.assets[asset] = data
            return project.apply({"type": "font-register", "name": name, "asset": asset}, detail="compact")

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

    def fixed(body):
        # The REST service is bound to one document; it never opens other workspace files.
        require("document" not in body, "This server serves one fixed document", "forbidden", field="document")
        return body

    @app.post("/spacing")
    def spacing(body: dict):
        return session.measure_spacing(**fixed(body))

    @app.post("/check")
    def check(body: dict):
        return session.check(**fixed(body))

    @app.post("/preview")
    def preview_image(body: dict):
        from .mcp_tools import preview

        options = fixed(body)
        allowed = {"variables", "max_width", "max_height", "max_bytes", "artboard", "comp", "region"}
        require(not set(options) - allowed, f"Preview accepts {sorted(allowed)}", field="body")
        return Response(preview(session, **options), media_type="image/png")

    @app.post("/compare")
    def compare_revisions(body: dict):
        import base64
        import io
        from .checks import compare

        options = fixed(body)
        with session.project() as p:
            image, summary = compare(
                p,
                options.get("before", "previous"),
                options.get("after", "head"),
                mode=options.get("mode", "side-by-side"),
            )
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return {**summary, "image_base64": base64.b64encode(stream.getvalue()).decode()}

    @app.get("/pixels/{target}")
    def pixels(target: str):
        with session.project() as p:
            return p.inspect_pixels(target)

    @app.get("/animation")
    def animation():
        with session.project() as p:
            return p.inspect_animation()

    @app.get("/animation/frame/{name}")
    def animation_frame(name: str, scale: int = 1):
        import io

        with session.project() as p:
            image = p.render_frame(name, scale)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return Response(stream.getvalue(), media_type="image/png")

    @app.post("/measure")
    def measure(body: dict):
        return session.measure(**fixed(body))

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
        "Non-loopback serving requires VIXL_API_TOKEN",
        "authentication_required",
    )
    try:
        import uvicorn
    except ImportError as exc:
        raise VixlError("missing_dependency", "Install vixl-engine[server]") from exc
    uvicorn.run(create_app(path, token=token, limits=limits), host=host, port=port)


def mcp_server(path=None, limits=None, *, workspace=None, schema="full", planner=False):
    try:
        from .mcp_tools import build_server
        import mcp.server.fastmcp  # noqa: F401
    except ImportError as exc:
        raise VixlError("missing_dependency", "Install vixl-engine[mcp]") from exc

    return build_server(Session(path, limits, workspace=workspace), schema=schema, planner=planner)
