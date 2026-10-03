"""Project-independent resource discovery and explicit user-library imports."""

from pathlib import Path

from .assets import read_bounded
from .commands import Parser, pairs
from .errors import require
from . import resources

CATEGORIES = {"palette": "palettes", "template": "templates", "guidance": "guidance"}


def resource_options(cmd, args):
    p = Parser(prog=f"vixl {cmd}")
    p.add_argument(
        "action",
        choices=["list", "show", "add", "apply", "new", "import", "remove"],
        nargs="?",
        default="list",
    )
    p.add_argument("name", nargs="?")
    p.add_argument("source", nargs="?")
    p.add_argument("--style", default="overall")
    p.add_argument("--prefix")
    p.add_argument("--set", action="append")
    p.add_argument("--out", "-o")
    return p.parse_args(args)


def standalone(cmd, args, limits):
    a = resource_options(cmd, args)
    kind = CATEGORIES[cmd]
    if a.action == "list":
        return {"kind": kind, "names": sorted(resources.catalog(kind))}, False
    require(a.name, "Provide a resource name")
    if a.action == "show":
        return {"name": a.name, "value": resources.get(kind, a.name)}, False
    if a.action == "add":
        require(a.source, "Provide a resource file")
        import json

        data = read_bounded(a.source, 1024 * 1024).decode("utf-8")
        return resources.register(kind, a.name, data if kind == "guidance" else json.loads(data)), False
    if cmd == "template" and a.action == "new":
        require(a.out, "Use template new NAME -o FILE")
        require(not Path(a.out).exists(), "Project already exists")
        p = resources.create_template(a.name, pairs(a.set), limits=limits)
        p.save(a.out)
        from .cli import remember

        remember(a.out)
        return {"created": a.out, "template": a.name, "layers": len(p.state["layers"])}, False
    return None, True


def project_command(project, cmd, args):
    if cmd == "font":
        p = Parser(prog="vixl font")
        p.add_argument("action", choices=["list", "import"])
        p.add_argument("source", nargs="?")
        p.add_argument("--name")
        a = p.parse_args(args)
        if a.action == "list":
            return project.state.get("fonts", {}), False
        require(a.source and a.name, "Use font import FILE_OR_HTTPS_URL --name NAME")
        from .fonts import import_font

        return import_font(project, a.source, a.name), True
    a = resource_options(cmd, args)
    require(a.name, "Provide a resource name")
    if a.action == "apply":
        if cmd == "guidance":
            op = {"type": "guidance", "name": a.name, "style": a.style}
        elif cmd == "palette":
            op = {"type": "palette-apply", "name": a.name}
            if a.prefix:
                op["prefix"] = a.prefix
        else:
            op = {"type": "template-apply", "name": a.name, "variables": pairs(a.set)}
    elif cmd == "guidance" and a.action == "import":
        require(a.source, "Provide a guidance text file")
        op = {
            "type": "guidance",
            "name": a.name,
            "text": read_bounded(a.source, 100000).decode("utf-8"),
            "style": a.style,
        }
    elif cmd == "guidance" and a.action == "remove":
        op = {"type": "guidance", "name": a.name, "style": a.style, "delete": True}
    else:
        require(False, "Unsupported resource action")
    return project.apply(op, detail="compact"), True
