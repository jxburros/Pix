"""Human syntax for design operations; JSON settings carry compound values."""

import json

from .commands import Parser
from .design_schema import TYPES


def compile_design(cmd, args):
    if cmd not in TYPES:
        return None
    p = Parser(prog=f"vixl {cmd}")
    if cmd == "shape":
        p.add_argument("shape")
        for key in ("fill", "stroke"):
            p.add_argument("--" + key)
        for key in ("stroke-width", "radius", "inner-radius"):
            p.add_argument("--" + key, type=float)
        p.add_argument("--sides", type=int)
    elif cmd in ("group", "pathfinder"):
        p.add_argument("name")
        p.add_argument("targets", nargs="+")
        if cmd == "pathfinder":
            p.add_argument("--mode", choices=["union", "subtract", "intersect"], required=True)
    elif cmd == "clip":
        p.add_argument("target")
        p.add_argument("base", nargs="?")
        p.add_argument("--release", action="store_true")
    elif cmd == "layer-style":
        p.add_argument("target")
        p.add_argument("name")
        p.add_argument("--settings", type=json.loads)
        p.add_argument("--remove", action="store_true")
    elif cmd == "distribute":
        p.add_argument("axis", choices=["horizontal", "vertical"])
        p.add_argument("targets", nargs="+")
        p.add_argument("--gap", type=float)
    elif cmd == "style-define":
        p.add_argument("name")
        p.add_argument("--kind", choices=["character", "paragraph"])
        p.add_argument("--settings", type=json.loads, required=True)
    elif cmd == "style-apply":
        p.add_argument("target")
        p.add_argument("name")
        p.add_argument("--kind", choices=["character", "paragraph"])
    elif cmd == "swatch":
        p.add_argument("name")
        p.add_argument("color")
    elif cmd == "artboard":
        p.add_argument("name")
        p.add_argument("--preset")
        p.add_argument("--background")
        p.add_argument("--variables", type=json.loads)
        p.add_argument("--targets", nargs="+")
        p.add_argument("--delete", action="store_true")
    elif cmd in ("frame", "replace-contents"):
        if cmd == "replace-contents":
            p.add_argument("target")
            p.add_argument("--variable")
        p.add_argument("--path")
        p.add_argument("--asset")
        p.add_argument("--fit", choices=["fill", "fit"])
    elif cmd in ("repeat", "repeat-blend"):
        p.add_argument("target")
        p.add_argument("--count", type=int, required=True)
        for key in ("dx", "dy", "dw", "dh"):
            p.add_argument("--" + key, type=float)
        if cmd == "repeat-blend":
            p.add_argument("--end", type=json.loads, required=True)
    elif cmd == "adjustment":
        p.add_argument("name")
        p.add_argument("--effects", type=json.loads, required=True)
    elif cmd == "lut":
        p.add_argument("name")
        p.add_argument("--size", type=int, required=True)
        p.add_argument("--values", type=json.loads, required=True)
    elif cmd == "lookup":
        p.add_argument("target")
        p.add_argument("name")
        p.add_argument("--amount", type=float)
    elif cmd in ("comp-save", "comp-apply"):
        p.add_argument("name")
    elif cmd == "text-layout":
        p.add_argument("target")
        p.add_argument("--fit", action="store_true")
        p.add_argument("--warp", choices=["none", "arc", "flag", "bulge"])
        p.add_argument("--amount", type=float)
        p.add_argument("--path", type=json.loads)
    elif cmd == "guide":
        p.add_argument("name")
        p.add_argument("axis", choices=["x", "y"])
        p.add_argument("position", type=float)
    elif cmd == "grid":
        p.add_argument("name")
        for key in ("columns", "rows"):
            p.add_argument("--" + key, type=int)
        for key in ("margin", "gutter"):
            p.add_argument("--" + key, type=float)
    elif cmd == "symbol":
        p.add_argument("target")
        p.add_argument("name")
    elif cmd == "symbol-instance":
        p.add_argument("symbol")
    else:
        p.add_argument("target", nargs="?")
    if cmd in ("shape", "frame", "symbol-instance"):
        p.add_argument("--name")
    if cmd in ("shape", "frame", "symbol-instance", "artboard", "text-layout"):
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)
    if cmd in ("shape", "frame", "symbol-instance"):
        p.add_argument("--x", type=float)
        p.add_argument("--y", type=float)
    return {"type": cmd, **{k: v for k, v in vars(p.parse_args(args)).items() if v is not None}}
