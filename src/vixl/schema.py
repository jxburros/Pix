"""Discoverable JSON Schema for the public structured operation format."""

from copy import deepcopy
from .render import EFFECTS, BLENDS

S = {"type": "string"}
N = {"type": "number"}
POSITIVE_INT = {"type": "integer", "minimum": 1}
B = {"type": "boolean"}
TARGET = {"type": "string", "description": "Stable layer ID or unique name; omitted means active layer."}


def enum(*values):
    return {"enum": list(values)}


def operation_schema():
    variants = []

    def add(kind, properties=None, required=(), **extra):
        variants.append(
            {
                "type": "object",
                "properties": {"type": {"const": kind}, "target": TARGET, **(properties or {})},
                "required": ["type", *required],
                "additionalProperties": False,
                **extra,
            }
        )

    add(
        "add",
        {"path": S, "asset": S, "name": S, "linked": B, "x": N, "y": N, "provenance": {"type": "object"}},
        anyOf=[{"required": ["path"]}, {"required": ["asset"]}],
    )
    add("solid", {"name": S, "width": POSITIVE_INT, "height": POSITIVE_INT, "color": S, "x": N, "y": N})
    add(
        "gradient",
        {
            "name": S,
            "width": POSITIVE_INT,
            "height": POSITIVE_INT,
            "start": S,
            "end": S,
            "direction": enum("horizontal", "vertical", "radial", "angled"),
            "stops": {"type": "array", "items": {"type": "object"}},
            "angle": N,
            "x": N,
            "y": N,
        },
    )
    add("palette-apply", {"name": S, "prefix": S}, ["name"])
    add("template-apply", {"name": S, "variables": {"type": "object"}}, ["name"])
    add("guidance", {"name": S, "text": S, "style": S, "delete": B}, ["name"])
    add("font-register", {"name": S, "asset": S}, ["name", "asset"])
    text = {
        "text": S,
        "size": POSITIVE_INT,
        "color": S,
        "align": enum("left", "center", "right"),
        "spacing": {"type": "integer", "minimum": 0},
    }
    add(
        "text",
        {
            **text,
            "name": S,
            "font": S,
            "x": {"type": ["string", "number"]},
            "y": {"type": ["string", "number"]},
        },
        ["text"],
    )
    add("text-set", {**text, "stroke_width": {"type": "integer", "minimum": 0}, "stroke_color": S})
    for kind in (
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
        add(kind)
    add("rename", {"name": S}, ["name"])
    add("duplicate", {"name": S})
    add("move", {"x": N, "y": N, "relative": B}, anyOf=[{"required": ["x"]}, {"required": ["y"]}])
    add(
        "resize",
        {"width": POSITIVE_INT, "height": POSITIVE_INT},
        anyOf=[{"required": ["width"]}, {"required": ["height"]}],
    )
    add("scale", {"value": {"type": "number", "exclusiveMinimum": 0}}, ["value"])
    add("rotate", {"value": N}, ["value"])
    add("opacity", {"value": {"type": "number", "minimum": 0, "maximum": 1}}, ["value"])
    add("blend", {"value": enum(*BLENDS)}, ["value"])
    add("flip", {"direction": enum("horizontal", "vertical")}, ["direction"])
    add(
        "crop", {"x": N, "y": N, "width": POSITIVE_INT, "height": POSITIVE_INT}, ["x", "y", "width", "height"]
    )
    add(
        "reorder",
        {"above": TARGET, "below": TARGET},
        oneOf=[{"required": ["above"]}, {"required": ["below"]}],
    )
    add(
        "align",
        {
            "alignment": enum(
                "center",
                "center-x",
                "center-y",
                "top",
                "bottom",
                "left",
                "right",
                "top-left",
                "top-right",
                "bottom-left",
                "bottom-right",
            ),
            "margin": N,
            "relative_to": S,
            "targets": {"type": "array", "items": S, "minItems": 1, "uniqueItems": True},
        },
        ["alignment"],
    )
    add(
        "constrain",
        {
            "constraints": {
                "type": "object",
                "properties": {
                    key: {"type": ["string", "number"]}
                    for key in ("left", "right", "top", "bottom", "center-x", "center-y")
                },
                "additionalProperties": False,
            }
        },
        ["constraints"],
    )
    add("canvas", {"width": POSITIVE_INT, "height": POSITIVE_INT, "background": S, "preset": S})
    add(
        "select",
        {
            "shape": enum("all", "none", "invert", "rect", "ellipse", "color", "alpha", "asset"),
            "x": N,
            "y": N,
            "width": POSITIVE_INT,
            "height": POSITIVE_INT,
            "color": S,
            "tolerance": N,
            "feather": N,
            "mode": enum("replace", "add", "subtract", "intersect"),
            "asset": S,
        },
        ["shape"],
    )
    add(
        "mask",
        {
            "action": enum("create", "from-selection", "import", "invert", "enable", "disable", "delete"),
            "path": S,
        },
    )
    effect = {
        "amount": N,
        "value": N,
        "seed": {"type": "integer", "minimum": 0},
        "radius": N,
        "strength": N,
        "black": N,
        "white": N,
        "points": {
            "type": "array",
            "items": {"type": "array", "items": N, "minItems": 2, "maxItems": 2},
            "minItems": 2,
        },
    }
    add("effect", {"name": S, **effect}, ["name"])
    for kind in EFFECTS:
        add(kind, deepcopy(effect))
    for kind in ("effect-disable", "effect-enable", "effect-remove", "effect-set"):
        add(
            kind,
            {"effect": {"type": ["integer", "string"]}, **(effect if kind == "effect-set" else {})},
            ["effect"],
        )
    add("variable", {"name": S, "value": {"type": ["string", "number", "boolean"]}, "delete": B}, ["name"])
    add("preset-save", {"name": S}, ["name"])
    add(
        "preset-apply",
        {"name": S, "overrides": {"type": "object", "additionalProperties": {"type": ["string", "number"]}}},
        ["name"],
    )
    from .design_schema import schemas

    schemas(add)
    from .pixel_schema import schemas as pixel_schemas

    pixel_schemas(add)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Vixl operation batch",
        "type": "object",
        "properties": {
            "operations": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {"oneOf": variants}}
        },
        "required": ["operations"],
        "additionalProperties": False,
    }


def validate_operation(operation):
    """Validate before doing any I/O; return canonical names for legacy aliases."""
    import json
    from jsonschema import Draft202012Validator
    from .operations import ALIASES
    from .errors import VixlError, require

    require(isinstance(operation, dict), "Each operation must be an object")
    result = deepcopy(operation)
    kind = result.pop("operation", result.get("type"))
    result["type"] = ALIASES.get(kind, kind) if isinstance(kind, str) else kind
    if "layer" in result:
        result["target"] = result.pop("layer")
    require(isinstance(result["type"], str), "Operation requires a string type")
    variants = operation_schema()["properties"]["operations"]["items"]["oneOf"]
    schema = next((s for s in variants if s["properties"]["type"]["const"] == result["type"]), None)
    require(schema is not None, f"Unknown operation: {result['type']}", "unknown_operation")
    error = next(Draft202012Validator(schema).iter_errors(result), None)
    if error:
        raise VixlError("invalid_operation", error.message, field=".".join(map(str, error.path)))
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise VixlError("invalid_operation", "Operations must contain finite JSON values") from exc
    return result
