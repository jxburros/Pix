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

from . import __version__
from .assets import read_bounded
from .commands import Parser, compile_command, compile_script, dimensions, normalize, pairs
from .errors import VixlError, require
from .model import Limits

HELP = """Vixl — headless design engine for autonomous AI agents

Usage: vixl [--project FILE] [--json] COMMAND ...
       vixl                         Interactive editing shell

Documents: new SIZE [-o FILE] [--background COLOR], open FILE, save [FILE]
Inspect:   status, inspect [LAYER], describe, layers, effects [LAYER], manifest,
           dependencies, reproduce --check, schema
Layers:    add FILE --name NAME, solid --color COLOR, gradient --start A --end B,
           text add TEXT --name NAME --size N, text NAME --text TEXT,
           remove, rename, duplicate, hide, show, raise, lower, top, bottom, reorder
Design:    shape, group, ungroup, clip, layer-style, distribute, style-define,
           style-apply, swatch, artboard, frame, replace-contents, repeat, repeat-blend,
           adjustment, lut, lookup, comp-save, comp-apply, text-layout, guide, grid,
           pathfinder, symbol, symbol-instance
Measure:   info, sample X Y, histogram [--region X Y W H], info --target TEXT,
           spacing --targets A B C --axis vertical [--expected N] [--tolerance N] [--check],
           spacing --around BODY --before HEADER --after FOOTER,
           check [--safe-area 5%] [--avoid X Y W H] [--thumbnail-width 320] [--strict]
Pixels:    pixel-art, pixel-draw, pixel-palette, pixels [LAYER],
           frame-save NAME [--duration MS], frame-apply NAME, frame-delete NAME,
           animation, animation-set --loop N --order FRAME FRAME,
           export-animation --out FILE --format gif|apng|sheet [--scale N]
Editing:   move, resize, scale, rotate, flip, crop, opacity, blend, align,
           select-layer, select, mask, filter, effect, rasterize
Effects:   brightness, contrast, saturation, hue, exposure, gamma, temperature,
           tint, shadows, highlights, blur, sharpen, grayscale, invert,
           posterize, threshold, noise, grain, vignette, auto-tone, auto-color, auto-contrast
Layout:    canvas resize SIZE, canvas preset NAME, constrain, unconstrain,
           variable set NAME VALUE
History:   undo [N], redo [N], history, checkpoint NAME, branch NAME,
           checkout REF, branches, compare REF REF --out FILE
Automate:  apply FILE|- [--dry-run], run SCRIPT, batch GLOB --run SCRIPT --output DIR,
           each layer --name PATTERN -- COMMAND, preset save|apply|show NAME,
           transaction begin|commit|rollback, assert RULE, validate [PROFILE]
Resources: commands, shapes, palette list|show|add|apply, template list|show|add|new|apply,
           guidance list|show|add|apply|import|remove, font list|import, providers, models
Output:    export FILE [--quality N] [--scale 2x] [--profile NAME],
           render [PROJECT] --out FILE [--set NAME=VALUE] [--artboard NAME] [--comp NAME],
           render --data rows.csv --out DIR, export-screens --out DIR --scales 1 2,
           convert --grayscale
AI:        ask PROMPT [--apply], generate --prompt TEXT --provider NAME,
           detect objects|faces, ocr, ai describe|info|regenerate|background-remove|upscale|extend,
           select object LABEL --provider NAME, ai remove|content-aware-fill|select-subject
Updates:   update [--check | --rollback], updates [on | off | status]
Services:  serve [--host 127.0.0.1] [--port 8765], mcp [--workspace DIR] [--schema slim] [--planner]

Options: --project/-p FILE, --json, --allow-linked, --plugins, --max-pixels N, --detail compact|full, --version
Use vixl commands --json for a complete inventory; vixl COMMAND --help works without a document. See docs/commands.md.
"""


def emit(value, machine=False):
    if value is None:
        return
    if machine or isinstance(value, (dict, list)):
        # ASCII JSON is also valid UTF-8 and survives redirected legacy Windows
        # streams. Never turn a successfully saved edit into an encoding error.
        print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))
    else:
        print(value)


def session_path():
    return Path.cwd() / ".vixl-session.json"


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
        raise VixlError("no_project", "No current project. Use vixl new SIZE -o FILE or vixl open FILE.")


def read_json(path):
    text = sys.stdin.read(1024 * 1024 + 1) if path == "-" else read_bounded(path, 1024 * 1024).decode()
    require(len(text) <= 1024 * 1024, "JSON input exceeds limit", "resource_limit")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise VixlError("invalid_json", str(exc)) from exc


def output_options(args, command):
    p = Parser(prog=f"vixl {command}")
    p.add_argument("path", nargs="?")
    p.add_argument("--out", "--preview", dest="out")
    p.add_argument("--quality", type=int, default=90)
    p.add_argument("--scale", default="1")
    p.add_argument("--profile")
    p.add_argument("--format", choices=["PNG", "JPEG", "WEBP", "TIFF", "AVIF", "SVG", "JPG"])
    p.add_argument("--background", default="white")
    p.add_argument("--set", action="append")
    p.add_argument("--artboard")
    p.add_argument("--comp")
    p.add_argument("--data")
    p.add_argument("--sampling", choices=["smooth", "nearest"], default="smooth")
    p.add_argument("--svg-policy", choices=["appearance", "strict"], default="appearance")
    return p.parse_args(args)


def dispatch(argv):
    global_parser = Parser(add_help=False)
    global_parser.add_argument("--project", "-p")
    global_parser.add_argument("--json", action="store_true")
    global_parser.add_argument("--allow-linked", action="store_true")
    global_parser.add_argument("--plugins", action="store_true")
    global_parser.add_argument("--max-pixels", type=int, default=40_000_000)
    global_parser.add_argument("--detail", choices=["compact", "full"], default="compact")
    global_parser.add_argument("--version", action="store_true")
    options, tokens = global_parser.parse_known_args(argv)
    if options.version:
        return __version__, options.json
    if not tokens:
        shell(options)
        return None, options.json
    if tokens[0] in ("--help", "-h", "help"):
        return HELP, options.json
    from . import Project

    if options.plugins:
        from .plugins import enable_plugins

        enable_plugins()
    require(options.max_pixels > 0, "Pixel limit must be positive")
    limits = Limits(max_pixels=options.max_pixels)
    tokens = normalize(tokens) if tokens[0] != "text" else tokens
    cmd, args = tokens[0], tokens[1:]
    if cmd in ("open", "schema") and any(arg in ("--help", "-h") for arg in args):
        return command_help(cmd, args), options.json
    if cmd in ("commands", "shapes"):
        from .operations import OPERATION_TYPES
        from .design_schema import SHAPES
        from .render import EFFECTS

        return (
            {"shapes": list(SHAPES)}
            if cmd == "shapes"
            else {
                "commands": sorted(
                    (
                        set(OPERATION_TYPES)
                        - {
                            "palette-apply",
                            "template-apply",
                            "font-register",
                            "effect-set",
                            "effect-disable",
                            "effect-enable",
                            "effect-remove",
                            "preset-save",
                            "preset-apply",
                        }
                    )
                    | set(EFFECTS)
                    | {"filter"}
                    | set(
                        "new open save status inspect describe layers effects manifest dependencies reproduce schema check batch convert render export export-screens export-animation spacing pixels animation info sample histogram apply run each undo redo checkpoint branch checkout branches history transaction compare assert validate preset ai ask generate detect ocr serve mcp update updates commands shapes palette template guidance font providers models".split()
                    )
                )
            }
        ), options.json
    if cmd in ("palette", "template", "guidance"):
        from .resource_cli import standalone

        result, needs_project = standalone(cmd, args, limits)
        if not needs_project:
            return result, options.json
    if cmd in ("providers", "models"):
        from .models import discovery_command

        return discovery_command(cmd, args), options.json
    if cmd in ("update", "updates"):
        from . import updater

        p = Parser(prog=f"vixl {cmd}")
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
            raise VixlError("update_error", str(exc)) from exc
    if cmd == "new":
        p = Parser(prog="vixl new")
        p.add_argument("size")
        p.add_argument("--background", default="transparent")
        p.add_argument("--out", "-o", default=options.project or "untitled.vixl")
        a = p.parse_args(args)
        require(not Path(a.out).exists(), "Project already exists; choose another filename")
        project = Project(*dimensions(a.size), a.background, limits=limits)
        project.save(a.out)
        remember(a.out)
        return (
            project.inspect()
            if options.detail == "full"
            else {
                "path": str(project.path),
                "canvas": project.state["canvas"],
                "layers": len(project.state["layers"]),
                "head": project.head,
            }
        ), options.json
    if cmd == "open":
        require(len(args) == 1, "Use open FILE")
        project = Project.load(args[0], limits=limits, allow_linked=options.allow_linked)
        remember(args[0])
        return (
            project.inspect()
            if options.detail == "full"
            else {
                "path": str(project.path),
                "canvas": project.state["canvas"],
                "layers": len(project.state["layers"]),
                "head": project.head,
            }
        ), options.json
    if cmd == "schema":
        from .schema import operation_schema

        return operation_schema(), options.json
    if cmd == "batch":
        return batch(args, limits, options.allow_linked), options.json
    if cmd == "convert":
        p = Parser(prog="vixl convert")
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
    if cmd == "render" and args and args[0].endswith(".vixl"):
        options.project = args.pop(0)
    if cmd == "validate" and args and args[0].endswith(".vixl"):
        options.project = args.pop(0)
    if cmd == "mcp":
        from .interfaces import mcp_server

        p = Parser(prog="vixl mcp")
        p.add_argument("--workspace", help="Directory containing documents, imports and exports")
        p.add_argument(
            "--schema",
            choices=["full", "slim"],
            default=os.environ.get("VIXL_MCP_SCHEMA", "full"),
            help="slim advertises operation names only; fields come from vixl_operation_schema",
        )
        p.add_argument("--planner", action="store_true", help="Expose the provider-backed vixl_ai_plan tool")
        a = p.parse_args(args)
        # Explicit workspaces can start empty. Existing --project configurations still work.
        path = current_path(options.project) if options.project or not a.workspace else None
        mcp_server(path, limits, workspace=a.workspace, schema=a.schema, planner=a.planner).run()
        return None, options.json
    if "--help" in args or "-h" in args:
        return command_help(cmd, args), options.json
    path = current_path(options.project)
    if cmd == "serve":
        from .interfaces import serve

        p = Parser(prog="vixl serve")
        p.add_argument("--host", default="127.0.0.1")
        p.add_argument("--port", type=int, default=8765)
        p.add_argument("--token-env", default="VIXL_API_TOKEN")
        a = p.parse_args(args)
        serve(path, a.host, a.port, os.environ.get(a.token_env), limits)
        return None, options.json
    with FileLock(str(path) + ".lock", timeout=10, is_singleton=True):
        project = Project.load(path, limits=limits, allow_linked=options.allow_linked)
        result, changed = project_command(project, cmd, args, detail=options.detail)
        if changed:
            project.save()
    return result, options.json


def command_help(cmd, args):
    from . import Project

    manual = {
        "open": "open FILE",
        "schema": "schema",
        "canvas": "canvas resize SIZE | preset NAME | background COLOR",
        "save": "save [FILE]",
        "inspect": "inspect [LAYER]",
        "status": "status",
        "describe": "describe [image]",
        "layers": "layers",
        "effects": "effects [LAYER]",
        "manifest": "manifest",
        "dependencies": "dependencies",
        "reproduce": "reproduce --check",
        "pixels": "pixels [LAYER]",
        "animation": "animation",
        "undo": "undo [COUNT]",
        "redo": "redo [COUNT]",
        "checkpoint": "checkpoint NAME",
        "branch": "branch NAME",
        "checkout": "checkout REF",
        "branches": "branches",
        "history": "history",
        "transaction": "transaction begin|commit|rollback",
        "assert": "assert RULE",
        "each": "each layer [--name PATTERN] [--type TYPE] -- COMMAND",
        "serve": "serve [--host HOST] [--port PORT] [--token-env ENV]",
        "preset": "preset save|apply|show NAME [--set KEY=VALUE]",
    }
    if cmd in manual:
        return "Usage: vixl " + manual[cmd]
    # Parsers handle --help before validation or execution, using a disposable document.
    return project_command(Project(1, 1), cmd, args)[0]


def project_command(project, cmd, args, *, detail="compact"):
    from .validation import assert_rule, dependencies, validate

    if cmd in ("palette", "template", "guidance", "font"):
        from .resource_cli import project_command as resource_command

        return resource_command(project, cmd, args)
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
        if a.data:
            require(a.svg_policy == "appearance", "Strict SVG policy requires SVG output")
            from .exports import render_data

            require(destination != "-", "Data rendering requires an output directory")
            require(a.format in (None, "PNG"), "Data rendering exports PNG files")
            return render_data(
                project,
                a.data,
                destination,
                variables=pairs(a.set),
                artboard=a.artboard,
                comp=a.comp,
                sampling=a.sampling,
                scale=float(a.scale.rstrip("x")),
                profile=a.profile,
            ), False
        data = project.export(
            None if destination == "-" else destination,
            quality=a.quality,
            scale=float(a.scale.rstrip("x")),
            profile=a.profile,
            variables=pairs(a.set),
            format=a.format,
            background=a.background,
            artboard=a.artboard,
            comp=a.comp,
            sampling=a.sampling,
            svg_policy=a.svg_policy,
        )
        if destination == "-":
            sys.stdout.buffer.write(data)
            return None, False
        return {"output": destination, "bytes": len(data)}, False
    if cmd == "spacing":
        p = Parser(prog="vixl spacing")
        p.add_argument("--targets", nargs="+")
        p.add_argument("--axis", choices=["horizontal", "vertical"], default="vertical")
        for key in ("around", "before", "after", "artboard", "comp"):
            p.add_argument("--" + key)
        p.add_argument("--expected", type=float)
        p.add_argument("--tolerance", type=float, default=1)
        p.add_argument("--check", action="store_true")
        options = vars(p.parse_args(args))
        check = options.pop("check")
        result = project.measure_spacing(**options)
        if check and not result["passed"]:
            raise VixlError("spacing_mismatch", "Requested spacing is inconsistent", measurement=result)
        return result, False
    if cmd == "check":
        p = Parser(prog="vixl check")
        p.add_argument(
            "--checks", nargs="+", choices=["bounds", "overlap", "contrast", "safe_area", "legibility"]
        )
        p.add_argument("--targets", nargs="+")
        p.add_argument("--safe-area", help="Inset from every edge: pixels or a percentage such as 5%%")
        p.add_argument(
            "--avoid", nargs=4, action="append", metavar=("X", "Y", "W", "H"), help="Reserved zone"
        )
        p.add_argument("--thumbnail-width", type=int, default=320)
        p.add_argument("--min-thumbnail-text", type=float, default=10)
        p.add_argument("--min-contrast", type=float)
        for key in ("artboard", "comp"):
            p.add_argument("--" + key)
        p.add_argument("--strict", action="store_true", help="Exit with an error when any check fails")
        options = vars(p.parse_args(args))
        strict = options.pop("strict")

        def number(value):
            return value if value.endswith("%") else float(value)

        if options["safe_area"] is not None:
            options["safe_area"] = number(options["safe_area"])
        options["avoid"] = [[number(v) for v in zone] for zone in options["avoid"] or []]
        result = project.check(**options)
        if strict and not result["passed"]:
            raise VixlError("design_check_failed", f"{result['errors']} design error(s)", report=result)
        return result, False
    if cmd == "pixels":
        require(len(args) <= 1, "Use pixels [LAYER]")
        return project.inspect_pixels(args[0] if args else None), False
    if cmd == "animation":
        require(not args, "Use animation to inspect frames")
        return project.inspect_animation(), False
    if cmd == "export-animation":
        p = Parser(prog="vixl export-animation")
        p.add_argument("--out", required=True)
        p.add_argument("--format", choices=["gif", "apng", "sheet"])
        p.add_argument("--scale", type=int, default=1)
        p.add_argument("--columns", type=int)
        a = p.parse_args(args)
        return project.export_animation(a.out, format=a.format, scale=a.scale, columns=a.columns), False
    if cmd == "export-screens":
        from .exports import export_screens

        p = Parser(prog="vixl export-screens")
        p.add_argument("--out", required=True)
        p.add_argument("--scales", nargs="+", default=["1", "2"])
        p.add_argument("--artboards", nargs="+")
        p.add_argument("--comp")
        p.add_argument("--set", action="append")
        a = p.parse_args(args)
        return export_screens(
            project,
            a.out,
            scales=[float(s.rstrip("x")) for s in a.scales],
            boards=a.artboards,
            comp=a.comp,
            variables=pairs(a.set),
        ), False
    if cmd in ("info", "sample", "histogram"):
        from .measure import measure

        p = Parser(prog=f"vixl {cmd}")
        if cmd == "sample":
            p.add_argument("point", nargs=2, type=int)
        p.add_argument("--region", nargs=4, type=int)
        p.add_argument("--foreground")
        p.add_argument("--target")
        p.add_argument("--artboard")
        p.add_argument("--comp")
        p.add_argument("--background", default="white")
        return measure(project, **vars(p.parse_args(args))), False
    if cmd in ("apply", "run"):
        p = Parser(prog=f"vixl {cmd}")
        p.add_argument("file")
        p.add_argument("--dry-run", action="store_true")
        a = p.parse_args(args)
        ops = read_json(a.file) if cmd == "apply" else compile_script(a.file)
        return project.apply(ops, dry_run=a.dry_run, detail=detail), not a.dry_run
    if cmd == "each":
        import fnmatch

        require("--" in args, "Use each layer [--name PATTERN] [--type TYPE] -- COMMAND")
        split = args.index("--")
        p = Parser(prog="vixl each")
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
        return project.apply(ops, detail=detail) if ops else {"operations": 0}, bool(ops)
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
        return [
            {k: v for k, v in node.items() if k not in ("state", "delta")} for node in project.nodes.values()
        ], False
    if cmd == "transaction":
        require(
            len(args) == 1 and args[0] in ("begin", "commit", "rollback"),
            "Use transaction begin|commit|rollback",
        )
        getattr(project, args[0])()
        return {"transaction": args[0], "success": True}, True
    if cmd == "compare":
        from PIL import Image

        p = Parser(prog="vixl compare")
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
        p = Parser(prog="vixl validate")
        p.add_argument("profile", nargs="?")
        p.add_argument("--rules")
        a = p.parse_args(args)
        result = validate(project, a.profile, read_json(a.rules) if a.rules else None)
        if not result["valid"]:
            raise VixlError("validation_failed", "Project validation failed", **result)
        return result, False
    if cmd == "preset" and args and args[0] == "show":
        require(len(args) == 2 and args[1] in project.state["presets"], "Preset not found")
        return project.state["presets"][args[1]], False
    if cmd in ("ai", "ask", "generate", "detect", "ocr", "OCR") or (
        cmd == "select" and args and args[0] == "object"
    ):
        from .ai import ai_command

        return ai_command(project, cmd, args, detail=detail)
    return project.apply(compile_command([cmd, *args]), detail=detail), True


def batch(args, limits, allow_linked):
    from . import Project

    p = Parser(prog="vixl batch")
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
        except (VixlError, OSError) as exc:
            results.append({"input": path, "success": False, "error": str(exc)})
    if not all(r["success"] for r in results):
        raise VixlError("batch_failed", "Some batch items failed", results=results)
    return results


def shell(options):
    try:
        import readline  # noqa: F401
    except ImportError:
        pass
    print(f"Vixl {__version__} · type help, exit, or a command")
    while True:
        try:
            line = input("vixl > ").strip()
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
        except (VixlError, OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)


def main(argv=None):
    # Frozen Python ignores PYTHONIOENCODING. Configure text output explicitly;
    # this does not change binary PNG/SVG/MCP writes through .buffer.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        result, machine = dispatch(argv)
        emit(result, machine)
        return 0
    except (VixlError, OSError, ValueError, TimeoutError) as exc:
        payload = (
            exc.as_dict()
            if isinstance(exc, VixlError)
            else {"error": "io_error" if isinstance(exc, OSError) else "invalid_input", "message": str(exc)}
        )
        print(json.dumps(payload) if "--json" in argv else f"ERROR: {payload['message']}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
