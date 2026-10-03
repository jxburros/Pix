"""Headless CLI and interactive shell. Project changes autosave after every successful command."""

from copy import deepcopy
import glob
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

from filelock import FileLock

from . import Project, __version__
from .assets import read_bounded
from .commands import Parser, compile_command, compile_script, dimensions, normalize, pairs
from .errors import PixError, require
from .model import Limits
from .validation import assert_rule, dependencies, validate

HELP = """Pix — programmable image editing

Usage: pix [--project FILE] [--json] COMMAND ...
       pix                         Interactive editing shell

Documents: new SIZE [-o FILE] [--background COLOR], open FILE, save [FILE]
Inspect:   status, inspect [LAYER], describe, layers, effects [LAYER], manifest,
           dependencies, reproduce --check, schema
Layers:    add FILE --name NAME, solid --color COLOR, gradient --start A --end B,
           text add TEXT --name NAME --size N, text NAME --text TEXT,
           remove, rename, duplicate, hide, show, raise, lower, top, bottom, reorder
Editing:   move, resize, scale, rotate, flip, crop, opacity, blend, align,
           select-layer, select, mask, filter, effect, rasterize
Effects:   brightness, contrast, saturation, hue, exposure, gamma, temperature,
           tint, shadows, highlights, blur, sharpen, grayscale, invert,
           posterize, threshold, noise, grain, vignette
Layout:    canvas resize SIZE, canvas preset NAME, constrain, unconstrain,
           variable set NAME VALUE
History:   undo [N], redo [N], history, checkpoint NAME, branch NAME,
           checkout REF, branches, compare REF REF --out FILE
Automate:  apply FILE|- [--dry-run], run SCRIPT, batch GLOB --run SCRIPT --output DIR,
           each layer --name PATTERN -- COMMAND, preset save|apply|show NAME,
           transaction begin|commit|rollback, assert RULE, validate [PROFILE]
Output:    export FILE [--quality N] [--scale 2x] [--profile NAME],
           render [PROJECT] --out FILE [--set NAME=VALUE], convert --grayscale
AI:        ask PROMPT [--apply], generate --prompt TEXT --provider NAME,
           detect objects|faces, ocr, ai describe|info|regenerate|background-remove|upscale|extend,
           select object LABEL --provider NAME
Updates:   update [--check | --rollback], updates [on | off | status]
Services:  serve [--host 127.0.0.1] [--port 8765], mcp [--workspace DIR]

Options: --project/-p FILE, --json, --allow-linked, --plugins, --max-pixels N, --version
Use pix COMMAND --help for editing command arguments. See docs/commands.md.
"""


def emit(value, machine=False):
    if value is None:
        return
    if machine or isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print(value)


def session_path():
    return Path.cwd() / ".pix-session.json"


def remember(path):
    fd, temporary = tempfile.mkstemp(dir=Path.cwd())
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"project": str(Path(path).resolve())}, stream)
        os.replace(temporary, session_path())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def current_path(explicit=None):
    if explicit:
        return Path(explicit).resolve()
    try:
        return Path(json.loads(session_path().read_text())["project"])
    except (OSError, ValueError, KeyError):
        raise PixError("no_project", "No current project. Use pix new SIZE -o FILE or pix open FILE.")


def read_json(path):
    text = sys.stdin.read(1024 * 1024 + 1) if path == "-" else read_bounded(path, 1024 * 1024).decode()
    require(len(text) <= 1024 * 1024, "JSON input exceeds limit", "resource_limit")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise PixError("invalid_json", str(exc)) from exc


def output_options(args, command):
    p = Parser(prog=f"pix {command}")
    p.add_argument("path", nargs="?")
    p.add_argument("--out", "--preview", dest="out")
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--scale", default="1")
    p.add_argument("--profile")
    p.add_argument("--format", choices=["PNG", "JPEG", "WEBP", "TIFF", "AVIF"])
    p.add_argument("--background", default="white")
    p.add_argument("--set", action="append")
    return p.parse_args(args)


def dispatch(argv):
    global_parser = Parser(add_help=False)
    global_parser.add_argument("--project", "-p")
    global_parser.add_argument("--json", action="store_true")
    global_parser.add_argument("--allow-linked", action="store_true")
    global_parser.add_argument("--plugins", action="store_true")
    global_parser.add_argument("--max-pixels", type=int, default=40_000_000)
    global_parser.add_argument("--version", action="store_true")
    options, tokens = global_parser.parse_known_args(argv)
    if options.version:
        return __version__, options.json
    if not tokens:
        shell(options)
        return None, options.json
    if tokens[0] in ("--help", "-h", "help"):
        return HELP, options.json
    if options.plugins:
        from .plugins import enable_plugins

        enable_plugins()
    require(options.max_pixels > 0, "Pixel limit must be positive")
    limits = Limits(max_pixels=options.max_pixels)
    tokens = normalize(tokens) if tokens[0] != "text" else tokens
    cmd, args = tokens[0], tokens[1:]
    if cmd in ("update", "updates"):
        from . import updater

        p = Parser(prog=f"pix {cmd}")
        if cmd == "update":
            flags = p.add_mutually_exclusive_group()
            flags.add_argument("--check", action="store_true")
            flags.add_argument("--rollback", action="store_true")
        else:
            p.add_argument("action", nargs="?", choices=["on", "off", "status"], default="status")
        a = p.parse_args(args)
        try:
            root = updater.root_path()
            if cmd == "updates":
                return (
                    updater.status(root)
                    if a.action == "status"
                    else updater.preference(root, a.action == "on")
                ), options.json
            return (
                updater.rollback(root) if a.rollback else updater.update(root, check_only=a.check)
            ), options.json
        except updater.UpdateError as exc:
            raise PixError("update_error", str(exc)) from exc
    if cmd == "new":
        p = Parser(prog="pix new")
        p.add_argument("size")
        p.add_argument("--background", default="transparent")
        p.add_argument("--out", "-o", default=options.project or "untitled.pix")
        a = p.parse_args(args)
        require(not Path(a.out).exists(), "Project already exists; choose another filename")
        project = Project(*dimensions(a.size), a.background, limits=limits)
        project.save(a.out)
        remember(a.out)
        return project.inspect(), options.json
    if cmd == "open":
        require(len(args) == 1, "Use open FILE")
        project = Project.load(args[0], limits=limits, allow_linked=options.allow_linked)
        remember(args[0])
        return project.inspect(), options.json
    if cmd == "schema":
        from .schema import operation_schema

        return operation_schema(), options.json
    if cmd == "batch":
        return batch(args, limits, options.allow_linked), options.json
    if cmd == "convert":
        p = Parser(prog="pix convert")
        p.add_argument("--grayscale", action="store_true")
        p.add_argument("--format", default="PNG")
        a = p.parse_args(args)
        from .assets import add_image, decode

        project = Project(1, 1, limits=limits)
        image = decode(sys.stdin.buffer.read(limits.max_asset_bytes + 1), limits)
        asset = add_image(project, image)
        project.apply(
            [
                {"type": "canvas", "width": image.width, "height": image.height},
                {"type": "add", "asset": asset},
            ]
        )
        if a.grayscale:
            project.apply({"type": "grayscale"})
        sys.stdout.buffer.write(project.export(format=a.format))
        return None, options.json
    if cmd == "render" and args and args[0].endswith(".pix"):
        options.project = args.pop(0)
    if cmd == "validate" and args and args[0].endswith(".pix"):
        options.project = args.pop(0)
    if cmd == "mcp":
        from .interfaces import mcp_server

        p = Parser(prog="pix mcp")
        p.add_argument("--workspace", help="Directory containing documents, imports and exports")
        a = p.parse_args(args)
        # Explicit workspaces can start empty. Existing --project configurations still work.
        path = current_path(options.project) if options.project or not a.workspace else None
        mcp_server(path, limits, workspace=a.workspace).run()
        return None, options.json
    path = current_path(options.project)
    if cmd == "serve":
        from .interfaces import serve

        p = Parser(prog="pix serve")
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8765)
        p.add_argument("--token-env", default="PIX_API_TOKEN")
        a = p.parse_args(args)
        serve(path, a.host, a.port, os.environ.get(a.token_env), limits)
        return None, options.json
    with FileLock(str(path) + ".lock", timeout=10, is_singleton=True):
        project = Project.load(path, limits=limits, allow_linked=options.allow_linked)
        result, changed = project_command(project, cmd, args)
        if changed:
            project.save()
    return result, options.json


def project_command(project, cmd, args):
    if cmd in ("inspect", "status", "describe"):
        if cmd == "describe" and args == ["image"]:
            from .ai import ai_command

            return ai_command(project, "ai", ["describe"])
        require(len(args) <= 1, "Expected optional layer")
        return project.inspect(args[0] if args else None), False
    if cmd == "layers":
        return project.inspect()["layers"], False
    if cmd == "effects":
        return deepcopy(project.layer(args[0] if args else None)["effects"]), False
    if cmd == "manifest":
        return {
            "version": __version__,
            "canvas": project.state["canvas"],
            "layers": len(project.state["layers"]),
            "history_entries": len(project.nodes),
            "dependencies": dependencies(project),
        }, False
    if cmd in ("dependencies", "reproduce"):
        result = dependencies(project)
        if cmd == "reproduce":
            project.render()
            result["reproducible"] = True
            result["note"] = "Current rendering verified; remote model replay is not guaranteed."
        return result, False
    if cmd == "save":
        require(len(args) <= 1, "Use save [FILE]")
        if args:
            require(
                not Path(args[0]).exists() or Path(args[0]).resolve() == project.path,
                "Destination already exists",
            )
            project.save(args[0])
            remember(args[0])
        else:
            project.save()
        return {"saved": str(project.path)}, False
    if cmd in ("render", "export"):
        a = output_options(args, cmd)
        destination = a.out or a.path
        require(destination, "Provide output filename or --out FILE")
        require(
            destination == "-" or Path(destination).resolve() != project.path,
            "Cannot export over the project",
        )
        data = project.export(
            None if destination == "-" else destination,
            quality=a.quality,
            scale=float(a.scale.rstrip("x")),
            profile=a.profile,
            variables=pairs(a.set),
            format=a.format,
            background=a.background,
        )
        if destination == "-":
            sys.stdout.buffer.write(data)
            return None, False
        return {"output": destination, "bytes": len(data)}, False
    if cmd in ("apply", "run"):
        p = Parser(prog=f"pix {cmd}")
        p.add_argument("file")
        p.add_argument("--dry-run", action="store_true")
        a = p.parse_args(args)
        ops = read_json(a.file) if cmd == "apply" else compile_script(a.file)
        return project.apply(ops, dry_run=a.dry_run), not a.dry_run
    if cmd == "each":
        import fnmatch

        require("--" in args, "Use each layer [--name PATTERN] [--type TYPE] -- COMMAND")
        split = args.index("--")
        p = Parser(prog="pix each")
        p.add_argument("kind", choices=["layer"])
        p.add_argument("--name", default="*")
        p.add_argument("--type")
        a = p.parse_args(args[:split])
        base = compile_command(args[split + 1 :])
        ops = [
            {**deepcopy(base), "target": layer["id"]}
            for layer in project.state["layers"]
            if fnmatch.fnmatchcase(layer["name"], a.name)
            and (not a.type or layer["type"] == {"image": "raster"}.get(a.type, a.type))
        ]
        return project.apply(ops) if ops else {"operations": 0}, bool(ops)
    if cmd in ("undo", "redo"):
        require(len(args) <= 1, "Expected optional count")
        getattr(project, cmd)(int(args[0]) if args else 1)
        return project.inspect(), True
    if cmd in ("checkpoint", "branch", "checkout"):
        require(len(args) == 1, "Expected a history name")
        getattr(project, cmd)(args[0])
        return {"head": project.head, "branch": project.current_branch}, True
    if cmd == "branches":
        return {
            "branches": project.branches,
            "checkpoints": project.checkpoints,
            "current": project.current_branch,
        }, False
    if cmd == "history":
        return [{k: v for k, v in node.items() if k != "state"} for node in project.nodes.values()], False
    if cmd == "transaction":
        require(
            len(args) == 1 and args[0] in ("begin", "commit", "rollback"),
            "Use transaction begin|commit|rollback",
        )
        getattr(project, args[0])()
        return {"transaction": args[0], "success": True}, True
    if cmd == "compare":
        from PIL import Image

        p = Parser(prog="pix compare")
        p.add_argument("left")
        p.add_argument("right")
        p.add_argument("--out", required=True)
        a = p.parse_args(args)
        left, right = project.clone(), project.clone()
        left.checkout(a.left)
        right.checkout(a.right)
        li, ri = left.render(), right.render()
        project.limits.size(li.width + ri.width, max(li.height, ri.height))
        canvas = Image.new("RGBA", (li.width + ri.width, max(li.height, ri.height)))
        canvas.paste(li, (0, 0))
        canvas.paste(ri, (li.width, 0))
        require(Path(a.out).resolve() != project.path, "Cannot overwrite project")
        canvas.save(a.out)
        return {"output": a.out, "left": left.inspect(), "right": right.inspect()}, False
    if cmd == "assert":
        rule = " ".join(args)
        require(assert_rule(project, rule), f"Assertion failed: {rule}", "assertion_failed")
        return {"passed": True, "rule": rule}, False
    if cmd == "validate":
        p = Parser(prog="pix validate")
        p.add_argument("profile", nargs="?")
        p.add_argument("--rules")
        a = p.parse_args(args)
        result = validate(project, a.profile, read_json(a.rules) if a.rules else None)
        if not result["valid"]:
            raise PixError("validation_failed", "Project validation failed", **result)
        return result, False
    if cmd == "preset" and args and args[0] == "show":
        require(len(args) == 2 and args[1] in project.state["presets"], "Preset not found")
        return project.state["presets"][args[1]], False
    if cmd in ("ai", "ask", "generate", "detect", "ocr", "OCR") or (
        cmd == "select" and args and args[0] == "object"
    ):
        from .ai import ai_command

        return ai_command(project, cmd, args)
    return project.apply(compile_command([cmd, *args])), True


def batch(args, limits, allow_linked):
    p = Parser(prog="pix batch")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--run", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--format", choices=["png", "jpg", "webp", "tiff"], default="png")
    a = p.parse_args(args)
    paths = sorted({str(Path(f).resolve()) for pattern in a.inputs for f in glob.glob(pattern)})
    require(paths, "No batch inputs matched")
    require(len(paths) <= 10000, "Too many batch inputs")
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    destinations = [out / (Path(f).stem + "." + a.format) for f in paths]
    require(len(set(destinations)) == len(paths), "Input names collide in output folder")
    require(not any(d.exists() for d in destinations), "Batch output already exists; choose an empty folder")
    ops = compile_script(a.run)
    results = []
    for path, dest in zip(paths, destinations):
        try:
            from .assets import decode

            image = decode(read_bounded(path, limits.max_asset_bytes), limits)
            project = Project(*image.size, limits=limits)
            project.allow_linked = allow_linked
            project.apply({"type": "add", "path": path})
            project.apply(ops)
            project.export(dest)
            results.append({"input": path, "output": str(dest), "success": True})
        except (PixError, OSError) as exc:
            results.append({"input": path, "success": False, "error": str(exc)})
    if not all(r["success"] for r in results):
        raise PixError("batch_failed", "Some batch items failed", results=results)
    return results


def shell(options):
    try:
        import readline  # noqa: F401
    except ImportError:
        pass
    print(f"Pix {__version__} · type help, exit, or a command")
    while True:
        try:
            line = input("pix > ").strip()
            if line in ("exit", "quit"):
                break
            if not line:
                continue
            if line == "help":
                print(HELP)
                continue
            prefix = ["--project", options.project] if options.project else []
            if options.allow_linked:
                prefix.append("--allow-linked")
            result, machine = dispatch([*prefix, *shlex.split(line)])
            emit(result, machine)
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
        except (PixError, OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        result, machine = dispatch(argv)
        emit(result, machine)
        return 0
    except (PixError, OSError, ValueError, TimeoutError) as exc:
        payload = (
            exc.as_dict()
            if isinstance(exc, PixError)
            else {"error": "io_error" if isinstance(exc, OSError) else "invalid_input", "message": str(exc)}
        )
        print(json.dumps(payload) if "--json" in argv else f"ERROR: {payload['message']}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
