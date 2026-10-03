"""Reduced-resolution proxy rendering for previews.

Agents look at previews capped around 1024 px. Rendering a 24-megapixel document at full size
and then shrinking it wastes most of the work, so previews render a geometrically scaled copy
of the document instead (JPEG sources also decode at a reduced DCT scale). Features whose
inputs are fixed-size canvas rasters (effect selections) fall back to a full render.
"""

from copy import copy, deepcopy
import re

CONSTRAINT = re.compile(r"^(.+\.(?:left|right|top|bottom|center-x|center-y))([+-]\d+(?:\.\d+)?)?$")


def _size(value, s):
    return max(1, round(value * s))


def _scale_layer(layer, s):
    for key in ("x", "y"):
        if key in layer:
            layer[key] = layer[key] * s
    for key in ("width", "height", "content_width", "content_height"):
        if key in layer:
            layer[key] = _size(layer[key], s)
    if "size" in layer and layer.get("type") == "text":
        layer["size"] = _size(layer["size"], s)
    for key in ("spacing", "radius"):
        if key in layer and isinstance(layer[key], (int, float)):
            layer[key] = layer[key] * s
    if "spacing" in layer:
        layer["spacing"] = round(layer["spacing"])
    if "stroke_width" in layer:
        value = layer["stroke_width"] * s
        layer["stroke_width"] = round(value) if layer.get("type") == "text" else value
    layout = layer.get("text_layout")
    if layout:
        for key in ("width", "height"):
            if key in layout:
                layout[key] = _size(layout[key], s)
        if "path" in layout:
            layout["path"] = [[x * s, y * s] for x, y in layout["path"]]
    repeat = layer.get("repeat")
    if repeat:
        for key in ("dx", "dy", "dw", "dh"):
            if key in repeat:
                repeat[key] = repeat[key] * s
        for key in ("width", "height"):
            if key in repeat.get("end", {}):
                repeat["end"][key] = _size(repeat["end"][key], s)
    for name, settings in layer.get("styles", {}).items():
        for key in ("dx", "dy", "blur", "width"):
            if key in settings:
                settings[key] = settings[key] * s
    for effect in layer.get("effects", []):
        if effect.get("name") in ("blur", "gaussian-blur"):
            effect["amount"] = effect.get("amount", 0) * s
    constraints = layer.get("constraints", {})
    for anchor, expression in list(constraints.items()):
        if isinstance(expression, (int, float)):
            constraints[anchor] = expression * s
        elif isinstance(expression, str):
            match = CONSTRAINT.match(expression)
            if match and match[2]:
                constraints[anchor] = f"{match[1]}{float(match[2]) * s:+g}"
    for operand in layer.get("operands", []):
        _scale_layer(operand, s)


def supported(state):
    for layer in state["layers"]:
        if any(effect.get("selection") for effect in layer.get("effects", [])):
            return False
        if layer.get("linked"):
            return False
    return True


def scaled_project(project, s):
    """Return a render-only copy of ``project`` scaled by ``s`` (< 1), or None if unsupported."""
    if not supported(project.state):
        return None
    candidate = copy(project)
    state = deepcopy(project.state)
    canvas = state["canvas"]
    canvas["width"], canvas["height"] = _size(canvas["width"], s), _size(canvas["height"], s)
    for layer in state["layers"]:
        _scale_layer(layer, s)
    for guide in state.get("guides", {}).values():
        guide["position"] = guide["position"] * s
    for style in state.get("character_styles", {}).values():
        for key in ("size", "stroke_width"):
            if key in style:
                style[key] = _size(style[key], s) if key == "size" else round(style[key] * s)
    for style in state.get("paragraph_styles", {}).values():
        if "spacing" in style:
            style["spacing"] = round(style["spacing"] * s)
    candidate.state = state
    return candidate


def render_preview(project, max_width, max_height, *, variables=None, artboard=None, comp=None, region=None):
    """Render at roughly the preview size. ``region`` [x, y, w, h] (document pixels) zooms in;
    zoomed regions may be enlarged up to 8x so small details stay legible."""
    from PIL import Image

    from .design_render import artboard_project
    from .errors import require

    candidate = artboard_project(project, artboard, comp, variables)
    c = candidate.state["canvas"]
    if region is not None:
        x, y, w, h = region
        require(w > 0 and h > 0, "Region width and height must be positive", field="region")
        x, y = max(0, x), max(0, y)
        w, h = min(w, c["width"] - x), min(h, c["height"] - y)
        require(w > 0 and h > 0, "Region is outside the canvas", field="region")
    else:
        x, y, w, h = 0, 0, c["width"], c["height"]
    fit = min(max_width / w, max_height / h)
    scale = min(1.0, fit)
    image = None
    if scale < 0.75:
        proxy = scaled_project(candidate, scale)
        if proxy is not None:
            image = proxy.render()
            box = (round(x * scale), round(y * scale), round((x + w) * scale), round((y + h) * scale))
            image = image.crop(box)
    if image is None:
        image = candidate.render().crop((x, y, x + w, y + h))
    target = (max(1, min(max_width, round(w * fit))), max(1, min(max_height, round(h * fit))))
    if region is not None and fit > 1:
        target = (max(1, round(w * min(fit, 8))), max(1, round(h * min(fit, 8))))
        return image.resize(target, Image.Resampling.LANCZOS)
    if image.size != target and (image.width > target[0] or image.height > target[1]):
        image = image.resize(target, Image.Resampling.LANCZOS)
    return image
