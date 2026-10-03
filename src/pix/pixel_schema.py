"""Schemas and CLI syntax for small pixel and animation documents."""

import json

from .pixel import PIXEL_TYPES
from .animation import ANIMATION_TYPES


def schemas(add):
    from .schema import S, N, enum

    grid = {"type": "integer", "minimum": 1, "maximum": 256}
    coordinate = {"type": "integer", "minimum": 0, "maximum": 255}
    palette = {"type": "object", "additionalProperties": S, "minProperties": 1, "maxProperties": 94}
    add(
        "pixel-art",
        {
            "name": S,
            "width": grid,
            "height": grid,
            "x": N,
            "y": N,
            "palette": palette,
            "background": S,
            "rows": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 256},
                "minItems": 1,
                "maxItems": 256,
            },
        },
    )
    add(
        "pixel-draw",
        {
            "tool": enum("pixel", "line", "rect", "fill"),
            "x": coordinate,
            "y": coordinate,
            "x2": coordinate,
            "y2": coordinate,
            "width": grid,
            "height": grid,
            "color": S,
        },
        ["x", "y", "color"],
    )
    add("pixel-palette", {"colors": palette}, ["colors"])
    add(
        "frame-save",
        {"name": S, "duration": {"type": "integer", "minimum": 10, "maximum": 60000, "multipleOf": 10}},
        ["name"],
    )
    add("frame-apply", {"name": S}, ["name"])
    add("frame-delete", {"name": S}, ["name"])
    add(
        "animation-set",
        {
            "loop": {"type": "integer", "minimum": 0, "maximum": 65535},
            "order": {"type": "array", "items": S, "uniqueItems": True, "maxItems": 256},
        },
    )


def compile_pixel(cmd, args):
    from .commands import Parser

    if cmd not in PIXEL_TYPES + ANIMATION_TYPES:
        return None
    p = Parser(prog=f"pix {cmd}")
    if cmd == "pixel-art":
        p.add_argument("--name")
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)
        p.add_argument("--x", type=int)
        p.add_argument("--y", type=int)
        p.add_argument("--palette", type=json.loads)
        p.add_argument("--rows", type=json.loads)
        p.add_argument("--background")
    elif cmd == "pixel-draw":
        p.add_argument("target")
        p.add_argument("tool", choices=["pixel", "line", "rect", "fill"])
        p.add_argument("x", type=int)
        p.add_argument("y", type=int)
        p.add_argument("--color", required=True)
        for key in ("x2", "y2", "width", "height"):
            p.add_argument("--" + key, type=int)
    elif cmd == "pixel-palette":
        p.add_argument("target")
        p.add_argument("--colors", type=json.loads, required=True)
    elif cmd.startswith("frame-"):
        p.add_argument("name")
        if cmd == "frame-save":
            p.add_argument("--duration", type=int)
    else:
        p.add_argument("--loop", type=int)
        p.add_argument("--order", nargs="+")
    return {"type": cmd, **{k: v for k, v in vars(p.parse_args(args)).items() if v is not None}}
