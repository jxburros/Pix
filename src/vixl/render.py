"""Deterministic RGBA renderer with bounded layer caching and straight-alpha compositing."""

from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .assets import decode, read_bounded
from .constants import EFFECTS as EFFECTS
from .errors import VixlError, require
from .model import finite

BLENDS = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "difference", "add", "subtract")
CANVAS_PRESETS = {
    "instagram-square": (1080, 1080),
    "instagram-post": (1080, 1080),
    "youtube-thumbnail": (1280, 720),
    "story": (1080, 1920),
    "discord": (512, 512),
}
EXPORT_PROFILES = {
    "instagram": {"size": (1080, 1080), "format": "JPEG", "quality": 90},
    "discord": {"size": (512, 512), "format": "PNG"},
    "print": {"format": "TIFF", "dpi": (300, 300)},
}


CSS_RGB = re.compile(
    r"rgba?\(\s*(\d+(?:\.\d+)?%?)[\s,]+(\d+(?:\.\d+)?%?)[\s,]+(\d+(?:\.\d+)?%?)"
    r"(?:\s*[,/]\s*(\d*(?:\.\d+)?%?))?\s*\)"
)


def _css_channel(text, alpha=False):
    if text.endswith("%"):
        return round(float(text[:-1]) * 2.55)
    value = float(text)
    return round(value * 255) if alpha and value <= 1 else round(value)


def color(value):
    if value == "transparent":
        return (0, 0, 0, 0)
    if isinstance(value, str):
        # CSS rgb()/rgba() with spaces or a 0–1 alpha, which models write constantly.
        match = CSS_RGB.fullmatch(value.strip().lower())
        if match:
            r, g, b = (min(255, _css_channel(match[i])) for i in (1, 2, 3))
            a = min(255, _css_channel(match[4], alpha=True)) if match[4] else 255
            return (r, g, b, a)
    try:
        return ImageColor.getcolor(value, "RGBA")
    except (ValueError, TypeError) as exc:
        raise VixlError(
            "invalid_color",
            f"Invalid color {value!r}; use a CSS name, #rrggbb[aa], rgb()/rgba() or hsl()",
            requested=value,
        ) from exc


def substitute(value, variables):
    if isinstance(value, str):

        def replace(match):
            require(match[1] in variables, f"Undefined variable: {match[1]}", "missing_variable")
            return str(variables[match[1]])

        return re.sub(r"\$\{([\w-]+)\}", replace, value)
    return value


def font_for(project, layer):
    size = int(layer.get("size", 48))
    require(1 <= size <= 4096, "Font size must be 1–4096")
    font = layer.get("font", "DejaVuSans.ttf")
    font = project.state.get("fonts", {}).get(font, font)
    try:
        if font in project.assets:
            return ImageFont.truetype(io.BytesIO(project.assets[font]), size)
        # Only explicitly imported fonts or Pillow's bundled/system font lookup, never project paths.
        require("/" not in font and "\\" not in font, "Import custom fonts with text --font FILE")
        return ImageFont.truetype(
            str(Path(__file__).parent / "data" / font) if font == "DejaVuSans.ttf" else font, size
        )
    except OSError as exc:
        raise VixlError(
            "missing_font", f"Font {font!r} not found; use DejaVuSans.ttf or import a font file"
        ) from exc


def text_metrics(project, layer, variables=None):
    text = substitute(layer["text"], variables or project.state["variables"])
    require(len(text) <= 100000, "Text exceeds length limit", "resource_limit")
    from .text import measure, font_data, UnsupportedText

    try:
        _, box = measure(font_data(project, layer), text, layer["size"], layer.get("spacing", 4), layer.get("align", "left"))
        stroke = layer.get("stroke_width", 0)
        box = (box[0] - stroke, box[1] - stroke, box[2] + stroke, box[3] + stroke)
        return max(1, math.ceil(box[2] - box[0])), max(1, math.ceil(box[3] - box[1])), box
    except UnsupportedText:
        pass
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font_for(project, layer),
        spacing=layer.get("spacing", 4),
        stroke_width=layer.get("stroke_width", 0),
    )
    return max(1, math.ceil(box[2] - box[0])), max(1, math.ceil(box[3] - box[1])), box


def transformed_size(layer):
    w, h = layer["width"], layer["height"]
    if layer.get("repeat"):
        from .design_render import repeat_bounds

        w, h = repeat_bounds(layer)
    if layer.get("rotation", 0) % 360:
        # Pillow determines the exact expanded pixel bounds, without allocating the source raster.
        angle = math.radians(layer["rotation"] % 360)
        if layer["rotation"] % 90 == 0:
            return (h, w) if layer["rotation"] % 180 else (w, h)
        return math.ceil(abs(w * math.cos(angle)) + abs(h * math.sin(angle))) + 2, math.ceil(
            abs(w * math.sin(angle)) + abs(h * math.cos(angle))
        ) + 2
    return w, h


def resolved_layers(project, variables=None):
    from .design import resolve_color

    variables = {**project.state["variables"], **(variables or {})}
    layers = deepcopy(project.state["layers"])
    originals = {item["id"]: item for item in layers}
    for index, layer in enumerate(layers):
        if layer["type"] == "symbol":
            master = originals[project.state["symbols"][layer["symbol"]]]
            instance = deepcopy(master)
            for key in (
                "id",
                "name",
                "x",
                "y",
                "width",
                "height",
                "rotation",
                "flip_x",
                "flip_y",
                "opacity",
                "blend",
                "visible",
                "constraints",
                "parent",
                "clip",
            ):
                if key in layer:
                    instance[key] = layer[key]
                elif key in ("parent", "clip"):
                    instance.pop(key, None)
            instance["effects"] += layer["effects"]
            instance["styles"] = {**instance.get("styles", {}), **layer.get("styles", {})}
            instance["auto_size"] = False
            layer = layers[index] = instance
        for category in ("character", "paragraph"):
            if layer.get(category + "_style"):
                layer.update(deepcopy(project.state[category + "_styles"][layer[category + "_style"]]))
        for key in ("text", "asset"):
            if key in layer:
                layer[key] = substitute(layer[key], variables)
        if layer.get("asset_variable"):
            name = layer["asset_variable"]
            require(name in variables, f"Undefined image variable: {name}", "missing_variable")
            layer["asset"] = str(variables[name])
            require(
                layer["asset"] in project.assets,
                "Image variables must reference embedded assets",
                "missing_asset",
            )
        for key in ("color", "fill", "start", "end", "stroke_color", "stroke"):
            if key in layer:
                layer[key] = resolve_color(layer[key], project.state, variables)
        if layer["type"] == "text" and layer.get("auto_size", True):
            layer["width"], layer["height"], _ = text_metrics(project, layer, variables)
        project.limits.size(layer["width"], layer["height"])
    return layers


def resolve_layout(project, variables=None, layers=None):
    layers = layers if layers is not None else resolved_layers(project, variables)
    canvas = project.state["canvas"]
    bounds = {"canvas": (0, 0, canvas["width"], canvas["height"])}
    index = {key: layer for layer in layers for key in (layer["id"], layer["name"])}
    visiting = set()

    def edge(expression):
        if isinstance(expression, (int, float)):
            return finite(expression)
        match = re.fullmatch(
            r"(.+)\.(left|right|top|bottom|center-x|center-y)([+-]\d+(?:\.\d+)?)?", expression
        )
        require(match, f"Invalid constraint expression: {expression}")
        ref, anchor, offset = match.groups()
        if ref.startswith("guide:"):
            guide = project.state.get("guides", {}).get(ref[6:])
            require(guide is not None, f"Unknown guide: {ref}")
            require(
                anchor
                in (("left", "right", "center-x") if guide["axis"] == "x" else ("top", "bottom", "center-y")),
                "Guide axis does not match constraint",
            )
            return guide["position"] + float(offset or 0)
        b = bounds["canvas"] if ref == "canvas" else solve(ref)
        x, y, w, h = b
        return {
            "left": x,
            "right": x + w,
            "top": y,
            "bottom": y + h,
            "center-x": x + w / 2,
            "center-y": y + h / 2,
        }[anchor] + float(offset or 0)

    def solve(ref):
        require(ref in index, f"Unknown constraint target: {ref}")
        layer = index[ref]
        ident = layer["id"]
        if ident in bounds:
            return bounds[ident]
        require(ident not in visiting, "Layout constraints contain a cycle", "constraint_cycle")
        visiting.add(ident)
        w, h = transformed_size(layer)
        project.limits.size(w, h)
        x, y = layer["x"], layer["y"]
        for anchor, expression in layer.get("constraints", {}).items():
            if isinstance(expression, str) and expression.startswith("canvas.") and layer.get("parent"):
                parent = index[layer["parent"]]
                old_canvas = bounds["canvas"]
                bounds["canvas"] = (0, 0, parent["content_width"], parent["content_height"])
                val = edge(expression)
                bounds["canvas"] = old_canvas
            else:
                val = edge(expression)
            if anchor == "left":
                x = val
            elif anchor == "right":
                x = val - w
            elif anchor == "top":
                y = val
            elif anchor == "bottom":
                y = val - h
            elif anchor == "center-x":
                x = val - w / 2
            elif anchor == "center-y":
                y = val - h / 2
            else:
                raise VixlError("invalid_constraint", f"Unknown anchor: {anchor}")
        bounds[ident] = (round(x), round(y), w, h)
        visiting.remove(ident)
        return bounds[ident]

    for layer in layers:
        solve(layer["id"])
    return {k: v for k, v in bounds.items() if k != "canvas"}


def apply_effect(image, effect):
    from .constants import ARTISTIC_DEFAULTS

    if effect["name"] in ARTISTIC_DEFAULTS:
        from .artistic import artistic_filter

        return artistic_filter(image, effect)
    name = effect["name"]
    value = effect.get("amount", 0)
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    if name in ("auto-tone", "auto-color", "auto-contrast"):
        a = np.asarray(rgb, dtype=np.float32)
        visible = np.asarray(alpha) > 0
        if visible.any():
            samples = a[visible]
            if name == "auto-contrast":
                low, high = np.percentile(samples, (0.5, 99.5))
            else:
                low, high = np.percentile(samples, (0.5, 99.5), axis=0)
            span = high - low
            a = np.where(span > 0, (a - low) * 255 / np.maximum(span, 1), a)
            if name == "auto-color":
                means = a[visible].mean(axis=0)
                a *= np.mean(means) / np.maximum(means, 1)
            rgb = Image.fromarray(np.uint8(np.clip(a, 0, 255) + 0.5))
    elif name in ("brightness", "contrast", "saturation", "sharpen"):
        enhancer = {
            "brightness": ImageEnhance.Brightness,
            "contrast": ImageEnhance.Contrast,
            "saturation": ImageEnhance.Color,
            "sharpen": ImageEnhance.Sharpness,
        }[name]
        factor = max(0, 1 + value / 100) if name != "sharpen" else value
        rgb = enhancer(rgb).enhance(factor)
    elif name in ("blur", "gaussian-blur"):
        # Blur premultiplied alpha to avoid colored fringes around transparent pixels.
        return image.convert("RGBa").filter(ImageFilter.GaussianBlur(value)).convert("RGBA")
    elif name == "grayscale":
        rgb = ImageOps.grayscale(rgb).convert("RGB")
    elif name == "invert":
        rgb = ImageOps.invert(rgb)
    elif name == "posterize":
        rgb = ImageOps.posterize(rgb, int(value))
    elif name == "threshold":
        rgb = ImageOps.grayscale(rgb).point(lambda x: 255 if x >= value else 0).convert("RGB")
    elif name == "hue":
        hsv = np.array(rgb.convert("HSV"))
        hsv[:, :, 0] = (hsv[:, :, 0].astype(float) + value * 255 / 360) % 256
        rgb = Image.fromarray(hsv, "HSV").convert("RGB")
    else:
        a = np.asarray(rgb, dtype=np.float32) / 255
        if name == "exposure":
            a *= 2**value
        elif name == "gamma":
            a = np.power(a, 1 / value)
        elif name == "temperature":
            a += np.array([value / 10000, 0, -value / 10000])
        elif name == "tint":
            a += np.array([value / 200, -value / 100, value / 200])
        elif name == "shadows":
            a += value / 100 * (1 - a) ** 2
        elif name == "highlights":
            a += value / 100 * a**2
        elif name == "levels":
            black, white = effect.get("black", 0), effect.get("white", 255)
            a = (a * 255 - black) / (white - black)
        elif name == "curves":
            points = effect["points"]
            a = np.interp(a, [p[0] / 255 for p in points], [p[1] / 255 for p in points])
        elif name in ("noise", "grain"):
            rng = np.random.default_rng(effect.get("seed", 0))
            a += rng.normal(0, value, (image.height, image.width, 1))
        elif name == "vignette":
            yy, xx = np.mgrid[-1 : 1 : complex(image.height), -1 : 1 : complex(image.width)]
            radius = effect.get("radius", 0.7)
            falloff = np.clip((np.sqrt(xx * xx + yy * yy) - radius) / max(0.01, 1.414 - radius), 0, 1)
            a *= 1 - effect.get("strength", value) * falloff[:, :, None]
        else:
            from .plugins import filter_plugin

            return filter_plugin(name)(image.copy(), deepcopy(effect))
        rgb = Image.fromarray(np.uint8(np.clip(a, 0, 1) * 255))
    rgb.putalpha(alpha)
    return rgb


def layer_image(project, layer, bounds):
    key = hashlib.sha256(json.dumps([layer, bounds], sort_keys=True).encode()).hexdigest()
    linked = layer.get("linked")
    cacheable = not linked and not layer.get("lookup") and layer["type"] not in ("group", "pathfinder")
    if cacheable and key in project._cache:
        return project._cache[key].copy()
    kind = layer["type"]
    if layer.get("repeat"):
        from .design_render import repeat_image

        image = repeat_image(project, layer)
    elif kind in ("shape", "group", "frame", "pathfinder"):
        from .design_render import special_image

        image = special_image(project, layer)
    elif kind == "pixel":
        from .pixel import pixel_image

        image = pixel_image(project, layer)
    elif kind == "raster":
        if linked:
            require(
                project.allow_linked,
                "Linked assets require --allow-linked or allow_linked=True",
                "linked_asset_disabled",
            )
            source = Path(linked)
            if not source.is_absolute():
                source = (project.path.parent if project.path else Path.cwd()) / source
            image = decode(read_bounded(source, project.limits.max_asset_bytes), project.limits)
        else:
            hint = None if layer.get("crop") else (layer["width"], layer["height"])
            image = project.image(layer["asset"], size_hint=hint)
        if layer.get("crop"):
            image = image.crop(tuple(layer["crop"]))
    elif kind == "text":
        from .design_render import text_image

        image = text_image(project, layer)
    elif kind == "solid":
        image = Image.new("RGBA", (layer["width"], layer["height"]), color(layer["fill"]))
    elif kind == "gradient":
        from .design_render import gradient_image

        image = gradient_image(project, layer, (layer["width"], layer["height"]))
    else:
        raise VixlError("invalid_layer", f"Unsupported layer type: {kind}")
    image = transform_layer_image(project, layer, bounds, image)
    # Cache is bounded in bytes as well as entry count.
    if cacheable and image.width * image.height * 4 < 32 * 1024 * 1024:
        while project._cache and (
            len(project._cache) >= 16
            or sum(i.width * i.height * 4 for i in project._cache.values()) + image.width * image.height * 4
            > 64 * 1024 * 1024
        ):
            project._cache.pop(next(iter(project._cache)))
        project._cache[key] = image.copy()
    return image


def transform_layer_image(project, layer, bounds, image):
    """Apply the same geometry and appearance to a layer or an isolated group child."""
    kind = layer["type"]
    if not layer.get("repeat"):
        image = image.resize(
            (layer["width"], layer["height"]),
            Image.Resampling.NEAREST if kind == "pixel" else Image.Resampling.LANCZOS,
        )
    if layer.get("flip_x"):
        image = ImageOps.mirror(image)
    if layer.get("flip_y"):
        image = ImageOps.flip(image)
    if layer.get("rotation", 0) % 360:
        image = image.rotate(
            -layer["rotation"],
            Image.Resampling.NEAREST if kind == "pixel" else Image.Resampling.BICUBIC,
            expand=True,
        )
        # Match conservative layout bounds consistently.
        if image.size != tuple(bounds[2:]):
            padded = Image.new("RGBA", tuple(bounds[2:]))
            padded.alpha_composite(
                image, ((padded.width - image.width) // 2, (padded.height - image.height) // 2)
            )
            image = padded
    for effect in layer["effects"]:
        if not effect.get("enabled", True):
            continue
        changed = apply_effect(image, effect)
        if effect.get("selection"):
            x, y, w, h = bounds
            mask = project.image(effect["selection"], "L").crop((x, y, x + w, y + h))
            image = Image.composite(changed, image, mask)
        else:
            image = changed
    if layer.get("lookup"):
        from .design_render import apply_lookup

        image = apply_lookup(project, image, layer["lookup"])
    mask = layer.get("mask")
    if mask and mask.get("enabled", True):
        m = project.image(mask["asset"], "L").resize(image.size, Image.Resampling.LANCZOS)
        alpha = np.asarray(image.getchannel("A"), dtype=np.float32) * np.asarray(m, dtype=np.float32) / 255
        image.putalpha(Image.fromarray(np.uint8(alpha)))
    if layer["opacity"] != 1:
        image.putalpha(image.getchannel("A").point(lambda a: round(a * layer["opacity"])))
    return image


def composite(bottom, top, blend):
    if blend == "normal":
        return Image.alpha_composite(bottom, top)
    b, s = np.asarray(bottom, dtype=np.float32) / 255, np.asarray(top, dtype=np.float32) / 255
    cb, cs, ab, ass = b[:, :, :3], s[:, :, :3], b[:, :, 3:], s[:, :, 3:]
    if blend == "multiply":
        mixed = cb * cs
    elif blend == "screen":
        mixed = cb + cs - cb * cs
    elif blend == "overlay":
        mixed = np.where(cb <= 0.5, 2 * cb * cs, 1 - 2 * (1 - cb) * (1 - cs))
    elif blend == "darken":
        mixed = np.minimum(cb, cs)
    elif blend == "lighten":
        mixed = np.maximum(cb, cs)
    elif blend == "difference":
        mixed = np.abs(cb - cs)
    elif blend == "add":
        mixed = np.minimum(1, cb + cs)
    elif blend == "subtract":
        mixed = np.maximum(0, cb - cs)
    else:
        raise VixlError("invalid_blend", f"Unknown blend mode: {blend}")
    alpha = ass + ab * (1 - ass)
    rgb = ((1 - ass) * ab * cb + (1 - ab) * ass * cs + ab * ass * mixed) / np.maximum(alpha, 1e-8)
    return Image.fromarray(np.uint8(np.clip(np.concatenate((rgb, alpha), axis=2), 0, 1) * 255 + 0.5))


def layer_surface(project, layer, bounds, size, index, visiting=None):
    """Composite one layer and its clipping dependencies over transparent pixels."""
    from .design_render import styled_image
    from PIL import ImageChops

    visiting = set() if visiting is None else visiting
    ident = layer["id"]
    require(ident not in visiting, "Clipping contains a cycle")
    visiting.add(ident)
    tile = Image.new("RGBA", size)
    if layer["visible"]:
        b = bounds[ident]
        source = layer_image(project, {**layer, "opacity": 1}, b)
        tile.alpha_composite(source, (b[0], b[1]))
        if layer.get("styles"):
            tile = styled_image(project, tile, layer["styles"])
        if layer.get("clip"):
            mask = layer_surface(project, index[layer["clip"]], bounds, size, index, visiting)
            tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask.getchannel("A")))
        if layer["opacity"] != 1:
            tile.putalpha(tile.getchannel("A").point(lambda a: round(a * layer["opacity"])))
    visiting.remove(ident)
    return tile


def layer_canvas_surface(project, layer, bounds=None, index=None):
    """Render one drawable through its ancestors onto the document canvas.

    Used for diagnostic coverage: group clipping, scaling, rotation, opacity,
    masks and styles follow the normal renderer instead of assuming local
    coordinates are canvas coordinates.
    """
    from .design_render import styled_image
    from PIL import ImageChops

    index = index or {item["id"]: item for item in resolved_layers(project)}
    bounds = bounds or resolve_layout(project, layers=list(index.values()))
    canvas = project.state["canvas"]
    canvas_size = (canvas["width"], canvas["height"])

    def container_size(item):
        parent = index.get(item.get("parent"))
        return (parent["content_width"], parent["content_height"]) if parent else canvas_size

    surface = layer_surface(project, layer, bounds, container_size(layer), index)
    parent = index.get(layer.get("parent"))
    while parent:
        size = container_size(parent)
        tile = Image.new("RGBA", size)
        if parent["visible"]:
            b = bounds[parent["id"]]
            if parent.get("repeat"):
                from .design_render import repeat_bounds, repeat_items

                repeated = Image.new("RGBA", repeat_bounds(parent))
                for item, x, y in repeat_items(parent):
                    source = transform_layer_image(project, item, (0, 0, item["width"], item["height"]), surface)
                    repeated.alpha_composite(source, (x, y))
                surface = repeated
            source = transform_layer_image(project, {**parent, "opacity": 1}, b, surface)
            tile.alpha_composite(source, b[:2])
            if parent.get("styles"):
                tile = styled_image(project, tile, parent["styles"])
            if parent.get("clip"):
                mask = layer_surface(project, index[parent["clip"]], bounds, size, index)
                tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask.getchannel("A")))
            if parent["opacity"] != 1:
                tile.putalpha(tile.getchannel("A").point(lambda a: round(a * parent["opacity"])))
        surface = tile
        parent = index.get(parent.get("parent"))
    return surface


def render_layers(project, parent=None, size=None, background="transparent"):
    from .design_render import apply_lookup

    layers = resolved_layers(project)
    bounds = resolve_layout(project, layers=layers)
    c = project.state["canvas"]
    size = size or (c["width"], c["height"])
    project.limits.size(*size)
    image = Image.new("RGBA", size, color(background))
    index = {item["id"]: item for item in layers}
    def surface(layer):
        return layer_surface(project, layer, bounds, size, index)

    def direct(layer):
        """Composite a plain layer only over its own bounds instead of a full-canvas tile."""
        b = bounds[layer["id"]]
        left, top = max(0, b[0]), max(0, b[1])
        right, bottom = min(size[0], b[0] + b[2]), min(size[1], b[1] + b[3])
        if left >= right or top >= bottom:
            return image
        source = layer_image(project, {**layer, "opacity": 1}, b)
        if (left, top, right, bottom) != (b[0], b[1], b[0] + b[2], b[1] + b[3]):
            source = source.crop((left - b[0], top - b[1], right - b[0], bottom - b[1]))
        if layer["opacity"] != 1:
            source.putalpha(source.getchannel("A").point(lambda a: round(a * layer["opacity"])))
        if layer["blend"] == "normal":
            image.alpha_composite(source, (left, top))
        else:
            box = (left, top, right, bottom)
            image.paste(composite(image.crop(box), source, layer["blend"]), box[:2])
        return image

    for layer in layers:
        if layer.get("parent") != parent or not layer["visible"]:
            continue
        if not layer.get("styles") and not layer.get("clip") and layer["type"] != "adjustment":
            image = direct(layer)
            continue
        if layer["type"] == "adjustment":
            changed = image
            for effect in layer["effects"]:
                if effect.get("enabled", True):
                    filtered = apply_effect(changed, effect)
                    changed = (
                        Image.composite(
                            filtered, changed, project.image(effect["selection"], "L").resize(size)
                        )
                        if effect.get("selection")
                        else filtered
                    )
            if layer.get("lookup"):
                changed = apply_lookup(project, changed, layer["lookup"])
            mask = Image.new("L", size, round(255 * layer["opacity"]))
            if layer.get("mask") and layer["mask"].get("enabled", True):
                from PIL import ImageChops

                mask = ImageChops.multiply(mask, project.image(layer["mask"]["asset"], "L").resize(size))
            image = Image.composite(composite(image, changed, layer["blend"]), image, mask)
        else:
            image = composite(image, surface(layer), layer["blend"])
    return image


def render(project, variables=None, artboard=None, comp=None):
    from .design_render import artboard_project

    candidate = artboard_project(project, artboard, comp, variables)
    from .design import resolve_color

    return render_layers(
        candidate, background=resolve_color(candidate.state["canvas"]["background"], candidate.state)
    )


def export(
    project,
    path=None,
    *,
    quality=90,
    scale=1,
    profile=None,
    variables=None,
    format=None,
    background="white",
    artboard=None,
    comp=None,
    sampling="smooth",
    svg_policy="appearance",
):
    require(sampling in ("smooth", "nearest"), "Sampling must be smooth or nearest")
    require(svg_policy in ("appearance", "strict"), "SVG policy must be appearance or strict")
    resample = Image.Resampling.NEAREST if sampling == "nearest" else Image.Resampling.LANCZOS
    require(path is None or Path(path).suffix.lower() != ".vixl", "Cannot export over a Vixl project")
    finite(scale, "scale", 0.01, 16)
    finite(quality, "quality", 1, 100)
    settings = {}
    if profile:
        require(profile in EXPORT_PROFILES, f"Unknown export profile: {profile}")
        settings = deepcopy(EXPORT_PROFILES[profile])
    requested_format = (
        format or settings.get("format") or ("SVG" if path and Path(path).suffix.lower() == ".svg" else "")
    ).upper()
    if requested_format == "SVG":
        require(not profile, "SVG export does not use raster export profiles")
        from .svg import export_svg

        data = export_svg(project, scale=scale, variables=variables, artboard=artboard, comp=comp, svg_policy=svg_policy)
        if path:
            Path(path).write_bytes(data)
        return data
    require(svg_policy == "appearance", "Strict SVG policy requires SVG output")
    if format:
        format = {"JPG": "JPEG", "TIF": "TIFF"}.get(format.upper(), format.upper())
    image = render(project, variables, artboard, comp)
    size = settings.pop("size", None)
    if size:
        image = ImageOps.contain(image, size, resample)
    target_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    project.limits.size(*target_size)
    if target_size != image.size:
        image = image.resize(target_size, resample)
    profile_format = settings.pop("format", None)
    fmt = (
        format
        or profile_format
        or (
            {
                ".jpg": "JPEG",
                ".jpeg": "JPEG",
                ".webp": "WEBP",
                ".tif": "TIFF",
                ".tiff": "TIFF",
                ".png": "PNG",
                ".avif": "AVIF",
            }.get(Path(path).suffix.lower())
            if path
            else "PNG"
        )
    )
    require(fmt in ("PNG", "JPEG", "WEBP", "TIFF", "AVIF"), "Specify a supported export format")
    if fmt == "JPEG":
        base = Image.new("RGBA", image.size, color(background))
        base.alpha_composite(image)
        image = base.convert("RGB")
    settings.setdefault("quality", int(quality))
    stream = io.BytesIO()
    try:
        image.save(stream, format=fmt, **settings)
    except (OSError, KeyError) as exc:
        raise VixlError("codec_error", str(exc)) from exc
    data = stream.getvalue()
    if path:
        Path(path).write_bytes(data)
    return data
