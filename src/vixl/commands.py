"""Human command syntax compiles into canonical operation dictionaries."""

import argparse
import re
import shlex
from pathlib import Path

from .errors import VixlError, require
from .constants import EFFECTS


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise VixlError("usage_error", message)


def dimensions(value):
    match = re.fullmatch(r"(\d+)[x×](\d+)", value)
    require(match, "Size must look like 1920x1080", "usage_error")
    return tuple(map(int, match.groups()))


def pairs(values):
    result = {}
    for value in values or []:
        require("=" in value, "Expected KEY=VALUE", "usage_error")
        key, val = value.split("=", 1)
        result[key] = val
    return result


def number_or_center(value):
    return value if value == "center" else float(value)


def normalize(tokens):
    tokens = list(tokens)
    require(tokens, "Expected a command")
    if tokens[0] == "layer":
        tokens.pop(0)
    if tokens[0] == "selection":
        tokens[0] = "select"
    tokens[0] = {"rm": "remove", "mv": "move", "ls": "layers", "center": "align"}.get(tokens[0], tokens[0])
    if tokens[0] == "text":
        if len(tokens) > 1 and tokens[1] == "add":
            tokens.pop(1)
        else:
            tokens[0] = "text-set"
    return tokens


def compile_command(tokens):
    tokens = normalize(shlex.split(tokens, comments=True) if isinstance(tokens, str) else tokens)
    cmd, args = tokens[0], tokens[1:]
    from .pixel_schema import compile_pixel

    pixel = compile_pixel(cmd, args)
    if pixel is not None:
        return pixel
    from .design_cli import compile_design

    design = compile_design(cmd, args)
    if design is not None:
        return design
    p = Parser(prog=f"vixl {cmd}")
    op = {"type": cmd}
    if cmd == "add":
        p.add_argument("path")
        p.add_argument("--name")
        p.add_argument("--linked", action="store_true")
        p.add_argument("--x", type=float)
        p.add_argument("--y", type=float)
    elif cmd in ("solid", "gradient", "text"):
        if cmd == "text":
            p.add_argument("text")
            p.add_argument("--font")
            p.add_argument("--size", type=int)
            p.add_argument("--align", choices=["left", "center", "right"])
            p.add_argument("--spacing", type=int)
        elif cmd == "gradient":
            p.add_argument("--start", default="black")
            p.add_argument("--end", default="white")
            p.add_argument("--direction", choices=["vertical", "horizontal", "radial", "angled"])
            p.add_argument("--angle", type=float)
            import json

            p.add_argument("--stops", type=json.loads)
        p.add_argument("--name")
        if cmd != "text":
            p.add_argument("--width", type=int)
            p.add_argument("--height", type=int)
        p.add_argument("--color")
        p.add_argument("--x", type=number_or_center)
        p.add_argument("--y", type=number_or_center)
    elif cmd == "text-set":
        p.add_argument("target", nargs="?")
        for key in ("text", "color", "align", "stroke-color"):
            p.add_argument(f"--{key}")
        for key in ("size", "spacing", "stroke-width"):
            p.add_argument(f"--{key}", type=int)
    elif cmd in (
        "remove",
        "hide",
        "show",
        "raise",
        "lower",
        "top",
        "bottom",
        "select-layer",
        "rasterize",
        "unconstrain",
    ):
        p.add_argument("target", nargs="?")
    elif cmd in ("rename", "duplicate"):
        p.add_argument("target")
        p.add_argument("name", nargs="?" if cmd == "duplicate" else None)
    elif cmd == "move":
        p.add_argument("values", nargs="*")
        p.add_argument("--x", type=float)
        p.add_argument("--y", type=float)
        p.add_argument("--relative", action="store_true")
        data = vars(p.parse_args(args))
        values = data.pop("values")
        if values and values[0] in ("x", "y") and len(values) == 2:
            data[values[0]] = float(values[1])
            data["relative"] = True
        elif len(values) == 3:
            data.update(target=values[0], x=float(values[1]), y=float(values[2]))
        elif len(values) == 2:
            data.update(x=float(values[0]), y=float(values[1]))
        elif len(values) == 1:
            data["target"] = values[0]
        else:
            require(not values, "Use move [LAYER] X Y or move [LAYER] --x X --y Y")
        require(data["x"] is not None or data["y"] is not None, "Move requires coordinates")
        return {**op, **{k: v for k, v in data.items() if v is not None}}
    elif cmd in ("resize", "scale"):
        p.add_argument("values", nargs="*")
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)
        data = vars(p.parse_args(args))
        values = data.pop("values")
        if values and not re.fullmatch(r"\d+(?:\.\d+)?%|\d+[x×]\d+|\d+(?:\.\d+)?", values[0]):
            data["target"] = values.pop(0)
        if values:
            require(len(values) in (1, 2), "Invalid resize arguments")
            if len(values) == 2:
                data.update(width=int(values[0]), height=int(values[1]))
            elif "x" in values[0] or "×" in values[0]:
                data["width"], data["height"] = dimensions(values[0])
            else:
                data["value"] = float(values[0].rstrip("%")) / (100 if values[0].endswith("%") else 1)
                op["type"] = "scale"
        if data.get("width") is not None or data.get("height") is not None:
            op["type"] = "resize"
        return {**op, **{k: v for k, v in data.items() if v is not None}}
    elif cmd in ("rotate", "opacity", "blend", "flip", *EFFECTS):
        p.add_argument("values", nargs="*")
        p.add_argument("--seed", type=int)
        p.add_argument("--radius", type=float)
        p.add_argument("--strength", type=float)
        data = vars(p.parse_args(args))
        values = data.pop("values")
        if cmd in ("grayscale", "invert", "auto-tone", "auto-color", "auto-contrast"):
            require(len(values) <= 1, "Expected optional layer")
            if values:
                data["target"] = values[0]
        else:
            require(len(values) in (1, 2), "Expected [LAYER] VALUE")
            if len(values) == 2:
                data["target"] = values.pop(0)
            key = "direction" if cmd == "flip" else "value"
            # Opacity 1–100 is read as a percentage by the shared normalizer.
            data[key] = values[0] if cmd in ("flip", "blend") else float(values[0])
        return {**op, **{k: v for k, v in data.items() if v is not None}}
    elif cmd == "crop":
        p.add_argument("target")
        for key in ("x", "y", "width", "height"):
            p.add_argument(key, type=int)
    elif cmd == "align":
        p.add_argument("target")
        p.add_argument("alignment")
        p.add_argument("--margin", type=float)
        p.add_argument("--relative-to")
        p.add_argument("--targets", nargs="+")
    elif cmd == "reorder":
        p.add_argument("target")
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--above")
        g.add_argument("--below")
    elif cmd == "constrain":
        p.add_argument("target")
        for key in ("left", "right", "top", "bottom", "center-x", "center-y"):
            p.add_argument(f"--{key}")
        p.add_argument("--below", nargs=2, metavar=("LAYER", "GAP"))
        data = vars(p.parse_args(args))
        constraints = {
            k.replace("_", "-"): v for k, v in data.items() if k not in ("target", "below") and v is not None
        }
        for key in ("center-x", "center-y"):
            if key in constraints and "." not in constraints[key]:
                constraints[key] += "." + key
        if data.get("below"):
            constraints["top"] = f"{data['below'][0]}.bottom+{float(data['below'][1])}"
        require(constraints, "Provide at least one constraint")
        return {**op, "target": data["target"], "constraints": constraints}
    elif cmd == "canvas":
        require(args, "Use canvas resize SIZE, preset NAME, or background COLOR")
        if args[0] == "resize":
            require(len(args) == 2, "Use canvas resize SIZE")
            w, h = dimensions(args[1])
            return {**op, "width": w, "height": h}
        require(len(args) == 2 and args[0] in ("preset", "background"), "Invalid canvas command")
        return {**op, args[0]: args[1]}
    elif cmd == "select":
        p.add_argument("shape", choices=["rect", "ellipse", "all", "none", "invert", "alpha", "color"])
        p.add_argument("values", nargs="*")
        p.add_argument("--tolerance", type=float)
        p.add_argument("--feather", type=float)
        p.add_argument("--mode", choices=["replace", "add", "subtract", "intersect"])
        data = vars(p.parse_args(args))
        values = data.pop("values")
        if data["shape"] in ("rect", "ellipse"):
            require(len(values) == 4, "Selection requires X Y WIDTH HEIGHT")
            data.update(zip(("x", "y", "width", "height"), map(int, values)))
        elif data["shape"] in ("alpha", "color"):
            require(len(values) == 1, "Selection requires layer or color")
            data["target" if data["shape"] == "alpha" else "color"] = values[0]
        else:
            require(not values, "Unexpected selection arguments")
        return {**op, **{k: v for k, v in data.items() if v is not None}}
    elif cmd == "mask":
        p.add_argument(
            "action", choices=["create", "from-selection", "invert", "enable", "disable", "delete", "import"]
        )
        p.add_argument("target", nargs="?")
        p.add_argument("--path")
    elif cmd == "filter":
        p.add_argument("name")
        p.add_argument("--target")
        for key in ("amount", "radius", "strength", "black", "white"):
            p.add_argument(f"--{key}", type=float)
        p.add_argument("--seed", type=int)
        data = {k: v for k, v in vars(p.parse_args(args)).items() if v is not None}
        if data["name"] in ("blur", "gaussian-blur") and "radius" in data:
            data["amount"] = data.pop("radius")
        return {"type": "effect", **data}
    elif cmd == "effect":
        p.add_argument("action", choices=["disable", "enable", "remove", "set"])
        p.add_argument("target")
        p.add_argument("effect")
        p.add_argument("--amount", type=float)
        data = vars(p.parse_args(args))
        action = data.pop("action")
        return {"type": f"effect-{action}", **{k: v for k, v in data.items() if v is not None}}
    elif cmd == "variable":
        p.add_argument("action", choices=["set", "delete"])
        p.add_argument("name")
        p.add_argument("value", nargs="?")
        data = vars(p.parse_args(args))
        action = data.pop("action")
        if action == "delete":
            data["delete"] = True
            data.pop("value", None)
        else:
            require(data["value"] is not None, "Variable set requires a value")
        return {**op, **data}
    elif cmd == "preset":
        p.add_argument("action", choices=["save", "apply"])
        p.add_argument("name")
        p.add_argument("target", nargs="?")
        p.add_argument("--set", action="append")
        data = vars(p.parse_args(args))
        action = data.pop("action")
        overrides = pairs(data.pop("set"))
        if action == "apply":
            data["overrides"] = overrides
        else:
            require(not overrides, "Preset save does not accept overrides")
        return {"type": f"preset-{action}", **{k: v for k, v in data.items() if v is not None}}
    else:
        raise VixlError("unknown_command", f"Unknown editing command: {cmd}. Run vixl --help.")
    return {**op, **{k: v for k, v in vars(p.parse_args(args)).items() if v is not None}}


def compile_script(path):
    from .assets import read_bounded

    content = read_bounded(path, 1024 * 1024).decode("utf-8")
    ops = []
    for line_no, line in enumerate(content.splitlines(), 1):
        tokens = shlex.split(line, comments=True)
        if not tokens:
            continue
        try:
            operation = compile_command(tokens)
            for field in ("path", "font"):
                if field in operation and not (field == "path" and operation["type"] == "text-layout"):
                    candidate = Path(path).resolve().parent / operation[field]
                    if field == "path" or candidate.is_file():
                        operation[field] = str(candidate)
            ops.append(operation)
        except (VixlError, ValueError) as exc:
            raise VixlError("script_error", f"{path}:{line_no}: {exc}") from exc
    return ops
