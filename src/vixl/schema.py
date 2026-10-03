"""Discoverable JSON Schema for the public structured operation format."""

from copy import deepcopy
from functools import lru_cache

from .render import EFFECTS, BLENDS

S = {"type": "string"}
N = {"type": "number"}
POSITIVE_INT = {"type": "integer", "minimum": 1}
B = {"type": "boolean"}
TARGET = {"type": "string", "description": "Stable layer ID or unique name; omitted means active layer."}
COORD = {
    "anyOf": [N, {"type": "string", "pattern": r"^(center|-?\d+(\.\d+)?%)$"}],
    "description": "Pixels, 'center', or a percentage of the canvas/parent such as '50%'.",
}
SIZE = {
    "anyOf": [POSITIVE_INT, {"type": "string", "pattern": r"^\d+(\.\d+)?%$"}],
    "description": "Pixels or a percentage of the canvas/parent such as '25%'.",
}
COORD_FIELDS = ("x", "y", "width", "height")


def enum(*values):
    return {"enum": list(values)}


def operation_schema():
    return deepcopy(_operation_schema())


@lru_cache(maxsize=1)
def _validators():
    from jsonschema import Draft202012Validator

    variants = _operation_schema()["properties"]["operations"]["items"]["oneOf"]
    return {s["properties"]["type"]["const"]: Draft202012Validator(s) for s in variants}


@lru_cache(maxsize=1)
def _operation_schema():
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
        {
            "path": S,
            "asset": S,
            "name": S,
            "linked": B,
            "x": COORD,
            "y": COORD,
            "provenance": {"type": "object"},
        },
        anyOf=[{"required": ["path"]}, {"required": ["asset"]}],
    )
    add("solid", {"name": S, "width": SIZE, "height": SIZE, "color": S, "x": COORD, "y": COORD})
    add(
        "gradient",
        {
            "name": S,
            "width": SIZE,
            "height": SIZE,
            "start": S,
            "end": S,
            "direction": enum("horizontal", "vertical", "radial", "angled"),
            "stops": {"type": "array", "items": {"type": "object"}},
            "angle": N,
            "x": COORD,
            "y": COORD,
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
            "x": COORD,
            "y": COORD,
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
    add("move", {"x": COORD, "y": COORD, "relative": B}, anyOf=[{"required": ["x"]}, {"required": ["y"]}])
    add(
        "resize",
        {"width": SIZE, "height": SIZE},
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
            "x": COORD,
            "y": COORD,
            "width": SIZE,
            "height": SIZE,
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


@lru_cache(maxsize=1)
def _properties():
    variants = _operation_schema()["properties"]["operations"]["items"]["oneOf"]
    return {v["properties"]["type"]["const"]: frozenset(v["properties"]) for v in variants}


def validate_operation(operation, notes=None, index=None):
    """Normalize common spellings, then validate before doing any I/O."""
    import json
    from .errors import VixlError, require
    from .normalize import normalize_operation
    from .operations import ALIASES

    require(isinstance(operation, dict), "Each operation must be an object")
    result = deepcopy(operation)
    kind = result.pop("operation", result.get("type"))
    result["type"] = ALIASES.get(kind, kind) if isinstance(kind, str) else kind
    properties = _properties()
    result = normalize_operation(
        result, lambda k: properties.get(k, frozenset()), properties, EFFECTS, [] if notes is None else notes, index
    )
    require(isinstance(result.get("type"), str), "Operation requires a string type", field="type")
    validator = _validators().get(result["type"])
    if validator is None:
        import difflib

        close = difflib.get_close_matches(result["type"], list(properties), 3, 0.5)
        raise VixlError(
            "unknown_operation",
            f"Unknown operation type {result['type']!r}"
            + (f"; did you mean {' or '.join(map(repr, close))}?" if close else "; see the operation schema"),
            field="type",
            suggestions=close,
        )
    from jsonschema.exceptions import best_match

    error = best_match(validator.iter_errors(result))
    if error is not None:
        raise schema_error(error, result, properties[result["type"]])
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise VixlError("invalid_operation", "Operations must contain finite JSON values") from exc
    return result


def schema_error(error, operation, allowed):
    """Turn a JSON Schema failure into a message an agent can act on in one retry."""
    import difflib
    from .errors import VixlError

    kind = operation["type"]
    path = [str(part) for part in error.absolute_path]
    field = ".".join(path) or None
    allowed = sorted(k for k in allowed if k != "type")
    details = {"field": field}
    validator = error.validator
    if validator == "additionalProperties":
        known = set(error.schema.get("properties", {}))
        extras = sorted(set(error.instance) - known)
        suggestions = {k: difflib.get_close_matches(k, sorted(known), 1, 0.5) for k in extras}
        hints = [f"{v[0]!r} instead of {k!r}" for k, v in suggestions.items() if v]
        where = f" in {field}" if field else f" for {kind!r}"
        message = f"Unknown field(s) {', '.join(map(repr, extras))}{where}. Allowed: {', '.join(sorted(known))}"
        if hints:
            message += f". Did you mean {', '.join(hints)}?"
        details.update(field=field or extras[0], allowed=sorted(known), suggestions={k: v[0] for k, v in suggestions.items() if v})
    elif validator == "enum":
        options = error.validator_value
        close = difflib.get_close_matches(str(error.instance), [str(o) for o in options], 1, 0.4)
        message = f"{field} must be one of {', '.join(map(repr, options))}; got {error.instance!r}"
        if close:
            message += f". Did you mean {close[0]!r}?"
        details.update(allowed=options, suggestions=close)
    elif validator == "required":
        missing = error.message.split("'")[1] if "'" in error.message else error.message
        message = f"{kind!r} is missing required field {missing!r}. Allowed fields: {', '.join(allowed)}"
        details.update(field=missing, allowed=allowed)
    elif validator in ("anyOf", "oneOf") and all(
        set(option) == {"required"} for option in error.validator_value
    ):
        options = [" + ".join(o["required"]) for o in error.validator_value]
        quantifier = "exactly one of" if validator == "oneOf" else "at least one of"
        message = f"{kind!r} requires {quantifier}: {', '.join(options)}"
        details.update(allowed=options)
    elif path and path[-1] in COORD_FIELDS and (
        validator == "anyOf" or (error.parent is not None and error.parent.validator == "anyOf")
    ):
        kind_of = "a positive integer" if path[-1] in ("width", "height") else "a number, 'center'"
        message = f"{field} must be {kind_of} or a percentage like '50%'; got {error.instance!r}"
    elif validator == "type":
        message = f"{field} must be {error.validator_value}; got {type(error.instance).__name__} {error.instance!r}"
    elif validator in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        message = f"{field} {error.message}"
        details["limit"] = error.validator_value
    else:
        message = f"{field + ': ' if field else ''}{error.message}"
    return VixlError("invalid_operation", message, **details)
