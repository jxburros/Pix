"""Schemas for editable design primitives shared by every operation interface."""

TYPES = (
    "shape",
    "group",
    "ungroup",
    "clip",
    "layer-style",
    "distribute",
    "style-define",
    "style-apply",
    "swatch",
    "artboard",
    "frame",
    "replace-contents",
    "repeat",
    "repeat-blend",
    "adjustment",
    "lut",
    "lookup",
    "comp-save",
    "comp-apply",
    "text-layout",
    "guide",
    "grid",
    "pathfinder",
    "symbol",
    "symbol-instance",
)
SHAPES = ("rectangle", "rounded-rectangle", "ellipse", "polygon", "star", "line")
STYLES = ("drop-shadow", "stroke", "outer-glow", "color-overlay", "gradient-overlay")


def schemas(add):
    from .schema import S, N, B, POSITIVE_INT, enum

    refs = {"type": "array", "items": S, "minItems": 1, "maxItems": 512, "uniqueItems": True}
    obj = {"type": "object"}
    geometry = {"name": S, "width": POSITIVE_INT, "height": POSITIVE_INT, "x": N, "y": N}
    add(
        "shape",
        {
            **geometry,
            "shape": enum(*SHAPES),
            "fill": S,
            "stroke": S,
            "stroke_width": N,
            "radius": N,
            "sides": POSITIVE_INT,
            "inner_radius": N,
        },
        ["shape"],
    )
    add("group", {"name": S, "targets": refs}, ["name", "targets"])
    add("ungroup")
    add("clip", {"base": S, "release": B})
    add("layer-style", {"name": enum(*STYLES), "settings": obj, "remove": B}, ["name"])
    add(
        "distribute", {"targets": refs, "axis": enum("horizontal", "vertical"), "gap": N}, ["targets", "axis"]
    )
    add(
        "style-define",
        {"name": S, "kind": enum("character", "paragraph"), "settings": obj},
        ["name", "settings"],
    )
    add("style-apply", {"name": S, "kind": enum("character", "paragraph")}, ["name"])
    add("swatch", {"name": S, "color": S}, ["name", "color"])
    add(
        "artboard",
        {**geometry, "preset": S, "background": S, "variables": obj, "targets": refs, "delete": B},
        ["name"],
    )
    add(
        "frame",
        {**geometry, "path": S, "asset": S, "fit": enum("fill", "fit")},
        anyOf=[{"required": ["path"]}, {"required": ["asset"]}],
    )
    add(
        "replace-contents",
        {"path": S, "asset": S, "variable": S, "fit": enum("fill", "fit")},
        anyOf=[{"required": ["path"]}, {"required": ["asset"]}, {"required": ["variable"]}],
    )
    repeat = {"count": POSITIVE_INT, "dx": N, "dy": N, "dw": N, "dh": N}
    add("repeat", repeat, ["count"])
    add("repeat-blend", {**repeat, "end": obj}, ["count", "end"])
    add("adjustment", {"name": S, "effects": {"type": "array", "items": obj, "maxItems": 256}}, ["effects"])
    add(
        "lut",
        {
            "name": S,
            "size": POSITIVE_INT,
            "values": {
                "type": "array",
                "items": {"type": "array", "items": N, "minItems": 3, "maxItems": 3},
                "maxItems": 35937,
            },
        },
        ["name", "size", "values"],
    )
    add("lookup", {"name": S, "amount": N}, ["name"])
    add("comp-save", {"name": S}, ["name"])
    add("comp-apply", {"name": S}, ["name"])
    add(
        "text-layout",
        {
            "width": POSITIVE_INT,
            "height": POSITIVE_INT,
            "fit": B,
            "warp": enum("none", "arc", "flag", "bulge"),
            "amount": N,
            "path": {
                "type": "array",
                "items": {"type": "array", "items": N, "minItems": 2, "maxItems": 2},
                "minItems": 2,
                "maxItems": 1024,
            },
        },
    )
    add("guide", {"name": S, "axis": enum("x", "y"), "position": N}, ["name", "axis", "position"])
    add(
        "grid", {"name": S, "columns": POSITIVE_INT, "rows": POSITIVE_INT, "margin": N, "gutter": N}, ["name"]
    )
    add(
        "pathfinder",
        {"name": S, "targets": refs, "mode": enum("union", "subtract", "intersect")},
        ["name", "targets", "mode"],
    )
    add("symbol", {"name": S}, ["name"])
    add("symbol-instance", {**geometry, "symbol": S}, ["symbol"])
