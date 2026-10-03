"""Forgiving input for model-written operations.

Language models reliably guess a handful of spellings that differ from the canonical schema
(``rect``, ``font_size``, ``opacity: 50``, camelCase keys, ``"50%"`` coordinates). Rejecting each
guess costs an agent a round trip, so every interface normalizes them here, the same way, and
reports what changed so the caller can learn the canonical form.
"""

import re

from .errors import require

PERCENT = re.compile(r"^(-?\d+(?:\.\d+)?)%$")

TYPE_ALIASES = {
    "image": "add",
    "add-image": "add",
    "import": "add",
    "import-image": "add",
    "add-text": "text",
    "text-add": "text",
    "set-text": "text-set",
    "edit-text": "text-set",
    "update-text": "text-set",
    "delete": "remove",
    "delete-layer": "remove",
    "translate": "move",
    "set-position": "move",
    "set-opacity": "opacity",
    "set-blend": "blend",
    "blend-mode": "blend",
    "add-layer": "add",
    "remove-layer": "remove",
    "move-layer": "move",
    "set-effect": "effect",
    "filter": "effect",
    "make-selection": "select",
    "style": "layer-style",
    "add-shape": "shape",
}
SHAPE_TYPES = {
    "rect": ("rectangle", {}),
    "rectangle": ("rectangle", {}),
    "square": ("rectangle", {}),
    "box": ("rectangle", {}),
    "rounded-rect": ("rounded-rectangle", {}),
    "rounded-rectangle": ("rounded-rectangle", {}),
    "roundrect": ("rounded-rectangle", {}),
    "rounded": ("rounded-rectangle", {}),
    "pill": ("rounded-rectangle", {}),
    "circle": ("ellipse", {}),
    "oval": ("ellipse", {}),
    "ellipse": ("ellipse", {}),
    "triangle": ("polygon", {"sides": 3}),
    "pentagon": ("polygon", {"sides": 5}),
    "hexagon": ("polygon", {"sides": 6}),
    "octagon": ("polygon", {"sides": 8}),
    "polygon": ("polygon", {}),
    "star": ("star", {}),
    "line": ("line", {}),
}
STYLE_ALIASES = {
    "shadow": "drop-shadow",
    "dropshadow": "drop-shadow",
    "drop-shadow": "drop-shadow",
    "glow": "outer-glow",
    "outer-glow": "outer-glow",
    "outline": "stroke",
    "stroke": "stroke",
    "color-overlay": "color-overlay",
    "gradient-overlay": "gradient-overlay",
}
TARGET_ALIASES = ("layer", "layer_id", "layerId", "target_id", "targetId", "layer_name")
FIELD_ALIASES = {
    "text": {
        "font_size": "size",
        "fontsize": "size",
        "content": "text",
        "fill": "color",
        "colour": "color",
        "font_color": "color",
        "text_align": "align",
        "alignment": "align",
        "font_family": "font",
        "line_spacing": "spacing",
        "outline_width": "stroke_width",
        "outline_color": "stroke_color",
    },
    "shape": {
        "color": "fill",
        "colour": "fill",
        "fill_color": "fill",
        "stroke_color": "stroke",
        "outline": "stroke",
        "outline_color": "stroke",
        "border_color": "stroke",
        "border_width": "stroke_width",
        "outline_width": "stroke_width",
        "corner_radius": "radius",
        "border_radius": "radius",
        "type_of_shape": "shape",
        "kind": "shape",
    },
    "solid": {"fill": "color", "colour": "color", "fill_color": "color"},
    "gradient": {"from": "start", "to": "end", "start_color": "start", "end_color": "end"},
    "opacity": {"opacity": "value", "amount": "value", "alpha": "value"},
    "rotate": {"angle": "value", "degrees": "value", "rotation": "value"},
    "scale": {"factor": "value", "amount": "value"},
    "blend": {"mode": "value", "blend": "value", "blend_mode": "value"},
    "rename": {"new_name": "name", "to": "name"},
    "effect": {"effect": "name", "filter": "name", "value": "amount"},
    "canvas": {"color": "background", "fill": "background"},
    "variable": {"key": "name"},
    "align": {"align": "alignment", "position": "alignment", "relativeTo": "relative_to"},
}
FIELD_ALIASES["text-set"] = FIELD_ALIASES["text"]
GEOMETRY_TYPES = {
    "solid",
    "gradient",
    "shape",
    "text",
    "add",
    "frame",
    "symbol-instance",
    "move",
    "resize",
    "select",
    "text-layout",
}
CENTER_TYPES = {"solid", "gradient", "shape", "add", "frame", "symbol-instance", "move"}


def _snake(key):
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", key).lower().replace("-", "_")


def _canonical_type(kind, known):
    if not isinstance(kind, str):
        return kind
    candidates = [kind, kind.lower(), kind.lower().replace("_", "-").replace(" ", "-")]
    for candidate in candidates:
        if candidate in known:
            return candidate
    for candidate in candidates:
        if candidate in TYPE_ALIASES:
            return TYPE_ALIASES[candidate]
    return candidates[-1] if candidates[-1] in SHAPE_TYPES or candidates[-1] in STYLE_ALIASES else kind


def normalize_operation(operation, properties, known_types, effects, notes, index=None):
    """Rewrite well-known guesses into canonical form. ``properties(kind)`` returns the schema's
    property names for a canonical operation type; the result is still schema-validated."""
    require(isinstance(operation, dict), "Each operation must be an object")
    op = dict(operation)
    where = f"operations[{index}]" if index is not None else "operation"

    def note(text):
        notes.append(f"{where}: {text}")

    if "type" not in op and "operation" in op:
        op["type"] = op.pop("operation")
    original = op.get("type")
    kind = _canonical_type(original, known_types)
    if isinstance(kind, str) and kind in SHAPE_TYPES and kind not in known_types:
        shape, extra = SHAPE_TYPES[kind]
        op.setdefault("shape", shape)
        for key, value in extra.items():
            op.setdefault(key, value)
        kind = "shape"
    elif isinstance(kind, str) and kind in STYLE_ALIASES and kind not in known_types:
        settings = {k: op.pop(k) for k in list(op) if k not in ("type", "target", *TARGET_ALIASES, "remove")}
        op = {**op, "name": STYLE_ALIASES[kind]}
        if settings:
            op["settings"] = settings
        kind = "layer-style"
    if kind != original:
        op["type"] = kind
        note(f"type {original!r} → {kind!r}")
    if not isinstance(kind, str) or kind not in known_types:
        return op

    for alias in TARGET_ALIASES:
        if alias in op and "target" not in op:
            op["target"] = op.pop(alias)
            note(f"{alias!r} → 'target'")
    allowed = properties(kind)

    # Generic spelling: camelCase / kebab-case keys whose snake_case form is canonical.
    for key in list(op):
        if key not in allowed and key != "type":
            snake = _snake(key)
            if snake in allowed and snake not in op:
                op[snake] = op.pop(key)
                note(f"{key!r} → {snake!r}")
    aliases = FIELD_ALIASES.get(kind, {})
    for key in list(op):
        if key in allowed or key == "type":
            continue
        canonical = aliases.get(key) or aliases.get(_snake(key)) or aliases.get(key.lower())
        if canonical and canonical in allowed and canonical not in op:
            op[canonical] = op.pop(key)
            note(f"{key!r} → {canonical!r}")

    if kind == "shape" and isinstance(op.get("shape"), str):
        guess = op["shape"].lower().replace("_", "-").replace(" ", "-")
        if guess not in SHAPE_TYPES:
            # "hexagonal", "circular", "rectangular", "stars" → their base shape.
            guess = next((name for name in SHAPE_TYPES if len(name) > 3 and guess.startswith(name)), guess)
        if guess in SHAPE_TYPES and SHAPE_TYPES[guess][0] != op["shape"]:
            shape, extra = SHAPE_TYPES[guess]
            note(f"shape {op['shape']!r} → {shape!r}")
            op["shape"] = shape
            for key, value in extra.items():
                op.setdefault(key, value)
    if kind == "opacity" and _number(op.get("value")) and 1 < op["value"] <= 100:
        note(f"opacity {op['value']} read as percent → {op['value'] / 100:g}")
        op["value"] = op["value"] / 100
    if kind == "blend" and isinstance(op.get("value"), str) and op["value"] != op["value"].lower():
        op["value"] = op["value"].lower()
    if kind == "effect" and isinstance(op.get("name"), str):
        name = op["name"].lower().replace("_", "-").replace(" ", "-")
        if name in STYLE_ALIASES and name not in effects:
            settings = {k: op.pop(k) for k in list(op) if k not in ("type", "target", "name")}
            op = {**op, "type": "layer-style", "name": STYLE_ALIASES[name]}
            if settings:
                op["settings"] = settings
            note(f"{name!r} is a layer style → {{type: 'layer-style', name: {STYLE_ALIASES[name]!r}}}")
            return op
        if name != op["name"] and name in effects:
            op["name"] = name
    if kind == "layer-style" and isinstance(op.get("name"), str):
        name = op["name"].lower().replace("_", "-").replace(" ", "-")
        if STYLE_ALIASES.get(name, name) != op["name"] and STYLE_ALIASES.get(name):
            note(f"style {op['name']!r} → {STYLE_ALIASES[name]!r}")
            op["name"] = STYLE_ALIASES[name]
        settings = op.get("settings")
        if isinstance(settings, dict):
            fixed = {}
            for key, value in settings.items():
                canonical = {
                    "offset_x": "dx",
                    "offsetX": "dx",
                    "x": "dx",
                    "offset_y": "dy",
                    "offsetY": "dy",
                    "y": "dy",
                    "radius": "blur",
                    "size": "width" if op["name"] == "stroke" else "blur",
                    "colour": "color",
                }.get(key, key)
                if canonical != key and canonical not in settings:
                    note(f"settings.{key} → settings.{canonical}")
                    key = canonical
                if key == "opacity" and _number(value) and 1 < value <= 100:
                    note(f"settings.opacity {value} read as percent → {value / 100:g}")
                    value = value / 100
                fixed[key] = value
            op["settings"] = fixed
    if kind == "move" and "x" not in op and "y" not in op and ("dx" in op or "dy" in op):
        op["x"], op["y"] = op.pop("dx", 0), op.pop("dy", 0)
        op["relative"] = True
        note("dx/dy → x/y with relative: true")
    if kind == "gradient" and isinstance(op.get("colors"), list) and "stops" not in op:
        colors = op.pop("colors")
        if len(colors) == 2:
            op.setdefault("start", colors[0])
            op.setdefault("end", colors[1])
        elif len(colors) > 2:
            op["stops"] = [
                {"offset": round(i / (len(colors) - 1), 6), "color": c} for i, c in enumerate(colors)
            ]
        note("colors → start/end/stops")
    return op


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_relative(value):
    return isinstance(value, str) and (value == "center" or PERCENT.match(value) is not None)


def resolve_geometry(project, op):
    """Resolve "N%" coordinates/sizes against the canvas (or the target's parent group) and
    remember which axes asked for "center" so creation operations can center afterwards."""
    kind = op.get("type")
    if kind not in GEOMETRY_TYPES:
        return op, {}
    c = project.state["canvas"]
    width, height = c["width"], c["height"]
    if kind in ("move", "resize", "text-layout"):
        try:
            layer = project.layer(op.get("target"))
        except Exception:
            layer = None
        if layer and layer.get("parent"):
            parent = project.layer(layer["parent"])
            width, height = parent.get("content_width", width), parent.get("content_height", height)
    centered = {}
    result = dict(op)
    for key, base in (("x", width), ("y", height), ("width", width), ("height", height)):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        if value == "center" and key in ("x", "y") and kind in CENTER_TYPES:
            centered[key] = True
            result[key] = 0
            continue
        match = PERCENT.match(value)
        if match:
            amount = float(match[1]) * base / 100
            result[key] = max(1, round(amount)) if key in ("width", "height") else amount
    return result, centered


def apply_centering(project, centered, operation):
    """Center the created (or moved) layer within its canvas or parent group."""
    if not centered:
        return
    from .render import resolve_layout

    layer = project.layer(operation.get("target") if operation.get("type") == "move" else None)
    bounds = resolve_layout(project)[layer["id"]]
    if layer.get("parent"):
        parent = project.layer(layer["parent"])
        width, height = parent["content_width"], parent["content_height"]
    else:
        width, height = project.state["canvas"]["width"], project.state["canvas"]["height"]
    if centered.get("x"):
        layer["x"] = (width - bounds[2]) / 2
    if centered.get("y"):
        layer["y"] = (height - bounds[3]) / 2
    if operation.get("type") == "move":
        layer["constraints"] = {}
