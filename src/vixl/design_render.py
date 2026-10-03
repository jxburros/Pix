"""Procedural shape, gradient, text and appearance rendering."""

from copy import copy, deepcopy
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .errors import require
from .design import resolve_color


def gradient_image(project, layer, size):
    from .render import color

    w, h = size
    stops = layer.get("stops") or [
        {"offset": 0, "color": layer.get("start", "black")},
        {"offset": 1, "color": layer.get("end", "white")},
    ]
    offsets = [s["offset"] for s in stops]
    colors = np.array([color(resolve_color(s["color"], project.state)) for s in stops], dtype=float)
    direction = layer.get("direction", "vertical")
    x = np.linspace(0, 1, w)[None, :]
    y = np.linspace(0, 1, h)[:, None]
    if direction == "radial":
        ramp = np.sqrt((2 * x - 1) ** 2 + (2 * y - 1) ** 2)
    elif direction == "angled":
        a = math.radians(layer.get("angle", 0))
        dx, dy = math.cos(a), math.sin(a)
        ramp = ((x - 0.5) * dx + (y - 0.5) * dy) / (abs(dx) + abs(dy)) + 0.5
    else:
        ramp = np.broadcast_to(x if direction == "horizontal" else y, (h, w))
    # Interpolate premultiplied alpha to avoid halos around transparent stops.
    colors[:, :3] *= colors[:, 3:] / 255
    arr = np.stack([np.interp(ramp, offsets, colors[:, i]) for i in range(4)], axis=-1)
    arr[:, :, :3] *= 255 / np.maximum(arr[:, :, 3:], 1)
    return Image.fromarray(np.uint8(np.clip(arr, 0, 255) + 0.5))


def shape_image(project, layer):
    from .render import color

    w, h = layer["width"], layer["height"]
    # Supersample within the resource budget; geometry is re-evaluated at every size.
    factor = min(
        4,
        project.limits.max_dimension // max(w, h),
        max(1, int(math.sqrt(project.limits.max_pixels / (w * h)))),
    )
    image = Image.new("RGBA", (w * factor, h * factor))
    draw = ImageDraw.Draw(image)
    fill = color(resolve_color(layer.get("fill", "white"), project.state))
    stroke = color(resolve_color(layer.get("stroke", "transparent"), project.state))
    width = round(layer.get("stroke_width", 1) * factor)
    pad = width / 2 if stroke[3] else 0
    box = (pad, pad, w * factor - 1 - pad, h * factor - 1 - pad)
    shape = layer["shape"]
    if shape in ("rectangle", "rounded-rectangle", "ellipse", "capsule"):
        fn = {
            "rectangle": draw.rectangle,
            "rounded-rectangle": draw.rounded_rectangle,
            "ellipse": draw.ellipse,
            "capsule": draw.rounded_rectangle,
        }[shape]
        extra = (
            {"radius": layer.get("radius", min(w, h) / (2 if shape == "capsule" else 5)) * factor}
            if shape in ("rounded-rectangle", "capsule")
            else {}
        )
        fn(box, fill=fill, outline=stroke if width and stroke[3] else None, width=max(1, width), **extra)
    elif shape == "line":
        draw.line(box, fill=stroke if stroke[3] else fill, width=max(1, width))
    else:
        from .geometry import shape_path, path_polygons

        path, view = shape_path(layer)
        for polygon in path_polygons(path):
            points = [
                (box[0] + x / view[0] * (box[2] - box[0]), box[1] + y / view[1] * (box[3] - box[1]))
                for x, y in polygon
            ]
            if len(points) >= 3:
                draw.polygon(points, fill=fill)
            if width and stroke[3] and len(points) >= 2:
                draw.line(points, fill=stroke, width=width, joint="curve")
    return image.resize((w, h), Image.Resampling.LANCZOS)


def text_image(project, layer):
    from .text import render_text, UnsupportedText

    try:
        return render_text(project, layer)
    except UnsupportedText:
        return legacy_text_image(project, layer)


def legacy_text_image(project, layer):
    from .render import font_for, text_metrics, color

    settings = layer.get("text_layout", {})
    working = deepcopy(layer)
    w, h = layer["width"], layer["height"]
    if settings.get("path"):
        image = Image.new("RGBA", (w, h))
        points = settings["path"]
        segments = [(a, b, math.dist(a, b)) for a, b in zip(points, points[1:]) if a != b]
        require(segments, "Text path must have nonzero length")
        distance = 0.0
        font = font_for(project, working)
        for char in layer["text"]:
            advance = font.getlength(char)
            center = distance + advance / 2
            offset = 0
            for a, b, length in segments:
                if center <= offset + length:
                    t = (center - offset) / length
                    glyph = {**working, "text": char}
                    gw, gh, box = text_metrics(project, glyph)
                    tile = Image.new("RGBA", (gw, gh))
                    ImageDraw.Draw(tile).text(
                        (-box[0], -box[1]), char, font=font, fill=color(layer.get("color", "white"))
                    )
                    tile = tile.rotate(
                        -math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])),
                        Image.Resampling.BICUBIC,
                        expand=True,
                    )
                    image.alpha_composite(
                        tile,
                        (
                            round(a[0] + t * (b[0] - a[0]) - tile.width / 2),
                            round(a[1] + t * (b[1] - a[1]) - tile.height / 2),
                        ),
                    )
                    break
                offset += length
            distance += advance
        return image

    def wrapped(size):
        working["size"] = size
        font = font_for(project, working)
        lines = []
        for paragraph in layer["text"].split("\n"):
            line = ""
            # Split at whitespace where possible, and hard-wrap oversized words.
            for word in paragraph.split(" "):
                proposed = line + (" " if line else "") + word
                if font.getlength(proposed) <= w:
                    line = proposed
                    continue
                if line:
                    lines.append(line)
                line = ""
                for char in word:
                    if line and font.getlength(line + char) > w:
                        lines.append(line)
                        line = ""
                    line += char
            lines.append(line)
        working["text"] = "\n".join(lines)
        return text_metrics(project, working)

    if "width" in settings:
        if settings.get("fit"):
            low, high = 1, layer["size"]
            while low < high:
                mid = (low + high + 1) // 2
                tw, th, _ = wrapped(mid)
                if tw <= w and th <= h:
                    low = mid
                else:
                    high = mid - 1
            metrics = wrapped(low)
        else:
            metrics = wrapped(layer["size"])
    else:
        metrics = text_metrics(project, working)
    tw, th, box = metrics
    project.limits.size(tw, th)
    image = Image.new("RGBA", (w, h) if settings else (tw, th))
    offset = (
        (w - tw) / 2 if working.get("align") == "center" else w - tw if working.get("align") == "right" else 0
    )
    ImageDraw.Draw(image).multiline_text(
        (offset - box[0] if settings else -box[0], -box[1]),
        working["text"],
        font=font_for(project, working),
        fill=color(working.get("color", "white")),
        spacing=working.get("spacing", 4),
        align=working.get("align", "left"),
        stroke_width=working.get("stroke_width", 0),
        stroke_fill=color(working.get("stroke_color", "black")),
    )
    warp = settings.get("warp", "none")
    if warp != "none":
        source = image
        image = Image.new("RGBA", source.size)
        amount = settings.get("amount", 0.2)
        for x in range(source.width):
            t = 2 * x / max(1, source.width - 1) - 1
            strip = source.crop((x, 0, x + 1, source.height))
            if warp == "bulge":
                height = max(1, round(source.height * (1 - abs(amount) + amount * (1 - t * t))))
                strip = strip.resize((1, height), Image.Resampling.BICUBIC)
                y = (source.height - height) // 2
            else:
                y = round(
                    amount * source.height * ((t * t - 0.5) if warp == "arc" else math.sin(t * math.pi))
                )
            image.alpha_composite(strip, (x, y))
    return image


def special_image(project, layer):
    from .render import render_layers, layer_image, transformed_size

    kind = layer["type"]
    if kind == "shape":
        return shape_image(project, layer)
    if kind == "group":
        c = (layer["content_width"], layer["content_height"])
        return render_layers(project, parent=layer["id"], size=c)
    if kind == "pathfinder":
        w, h = layer["width"], layer["height"]
        sx, sy = w / layer["content_width"], h / layer["content_height"]
        masks = []
        for operand in layer["operands"]:
            item = deepcopy(operand)
            item.update(width=max(1, round(item["width"] * sx)), height=max(1, round(item["height"] * sy)))
            tile = layer_image(project, item, (0, 0, *transformed_size(item)))
            mask = Image.new("L", (w, h))
            mask.paste(tile.getchannel("A"), (round(item["x"] * sx), round(item["y"] * sy)))
            masks.append(mask)
        alpha = masks[0]
        for mask in masks[1:]:
            alpha = {
                "union": ImageChops.lighter,
                "subtract": ImageChops.subtract,
                "intersect": ImageChops.darker,
            }[layer["mode"]](alpha, mask)
        from .render import color

        image = Image.new("RGBA", (w, h), color(resolve_color(layer.get("fill", "white"), project.state)))
        image.putalpha(alpha)
        return image
    if kind == "frame":
        source = project.image(layer["asset"])
        size = (layer["width"], layer["height"])
        if layer.get("fit", "fill") == "fill":
            return ImageOps.fit(source, size, Image.Resampling.LANCZOS)
        tile = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
        image = Image.new("RGBA", size)
        image.alpha_composite(tile, ((size[0] - tile.width) // 2, (size[1] - tile.height) // 2))
        return image
    raise ValueError(f"Unsupported procedural layer: {kind}")


def apply_lookup(project, image, settings):
    lut = project.state["luts"][settings["name"]]
    n = lut["size"]
    table = np.array(lut["values"], dtype=np.float32).reshape(n, n, n, 3)
    # .cube ordering: red varies fastest, then green, then blue.
    rgb = np.asarray(image, dtype=np.float32)[:, :, :3] / 255
    coordinates = rgb * (n - 1)
    lo = coordinates.astype(int)
    hi = np.minimum(lo + 1, n - 1)
    frac = coordinates - lo
    output = np.zeros_like(rgb)
    for r in (0, 1):
        for g in (0, 1):
            for b in (0, 1):
                idx = [hi[:, :, i] if flag else lo[:, :, i] for i, flag in enumerate((r, g, b))]
                weight = np.prod(
                    np.stack(
                        [frac[:, :, i] if flag else 1 - frac[:, :, i] for i, flag in enumerate((r, g, b))],
                        axis=-1,
                    ),
                    axis=-1,
                )
                output += table[idx[2], idx[1], idx[0]] * weight[:, :, None]
    amount = settings.get("amount", 1)
    result = Image.fromarray(np.uint8(np.clip(output * amount + rgb * (1 - amount), 0, 1) * 255 + 0.5))
    result.putalpha(image.getchannel("A"))
    return result


def styled_image(project, image, styles):
    from .render import color

    alpha = image.getchannel("A")
    result = Image.new("RGBA", image.size)
    for name in ("drop-shadow", "outer-glow", "stroke"):
        settings = styles.get(name)
        if settings is None or not settings.get("enabled", True):
            continue
        mask = alpha
        if name == "stroke":
            radius = round(settings.get("width", 2))
            if radius:
                mask = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(radius * 2 + 1)), alpha)
            else:
                continue
        else:
            mask = mask.filter(ImageFilter.GaussianBlur(settings.get("blur", 8)))
        if name == "drop-shadow":
            shifted = Image.new("L", image.size)
            shifted.paste(mask, (round(settings.get("dx", 4)), round(settings.get("dy", 4))))
            mask = shifted
        rgba = color(
            resolve_color(settings.get("color", "white" if name == "outer-glow" else "black"), project.state)
        )
        tile = Image.new("RGBA", image.size, rgba)
        tile.putalpha(mask.point(lambda a: round(a * settings.get("opacity", 1) * rgba[3] / 255)))
        result.alpha_composite(tile)
    for name in ("color-overlay", "gradient-overlay"):
        settings = styles.get(name)
        if settings is None or not settings.get("enabled", True):
            continue
        if name == "gradient-overlay":
            box = alpha.getbbox()
            tile = Image.new("RGBA", image.size)
            if box:
                tile.paste(gradient_image(project, settings, (box[2] - box[0], box[3] - box[1])), box[:2])
        else:
            tile = Image.new(
                "RGBA", image.size, color(resolve_color(settings.get("color", "white"), project.state))
            )
        tile.putalpha(tile.getchannel("A").point(lambda a: round(a * settings.get("opacity", 1))))
        # Blend RGB within the original silhouette without making translucent edges opaque.
        rgb = Image.composite(tile.convert("RGB"), image.convert("RGB"), tile.getchannel("A"))
        overlay = rgb.convert("RGBA")
        overlay.putalpha(alpha)
        image = overlay
    result.alpha_composite(image)
    return result


def artboard_project(project, name=None, comp=None, variables=None):
    if not name and not comp and not variables:
        return project
    candidate = copy(project)
    candidate.state = deepcopy(project.state)
    candidate._cache = {}
    if comp:
        from .design import execute_design

        execute_design(candidate, {"type": "comp-apply", "name": comp})
    if name:
        require(name in candidate.state.get("artboards", {}), f"Unknown artboard: {name}")
        board = candidate.state["artboards"][name]
        candidate.state["canvas"].update({k: board[k] for k in ("width", "height", "background")})
        candidate.state["variables"].update(board.get("variables", {}))
        if "targets" in board:
            allowed = set(board["targets"])
            for layer in candidate.state["layers"]:
                if not layer.get("parent") and layer["id"] not in allowed:
                    layer["visible"] = False
    candidate.state["variables"].update(variables or {})
    if comp:
        from .validation import check_state

        check_state(candidate, candidate.state)
    return candidate


def repeat_items(layer):
    settings = layer["repeat"]
    count = settings["count"]
    for i in range(count):
        item = deepcopy(layer)
        item.pop("repeat")
        item.update(rotation=0, flip_x=False, flip_y=False, effects=[], mask=None, opacity=1)
        item.pop("lookup", None)
        item["width"] = round(layer["width"] + i * settings.get("dw", 0))
        item["height"] = round(layer["height"] + i * settings.get("dh", 0))
        for key, end in settings.get("end", {}).items():
            t = i / max(1, count - 1)
            if key in ("width", "height"):
                item[key] = round(layer[key] * (1 - t) + end * t)
            elif key in ("fill", "color"):
                from .render import color

                a, b = color(layer.get(key, "white")), color(end)
                item[key] = "#" + "".join(f"{round(x * (1 - t) + y * t):02x}" for x, y in zip(a, b))
        yield item, round(i * settings.get("dx", 0)), round(i * settings.get("dy", 0))


def repeat_bounds(layer):
    items = list(repeat_items(layer))
    return max(x + item["width"] for item, x, y in items), max(y + item["height"] for item, x, y in items)


def repeat_image(project, layer):
    from .render import layer_image

    size = repeat_bounds(layer)
    project.limits.size(*size)
    image = Image.new("RGBA", size)
    for item, x, y in repeat_items(layer):
        project.limits.size(item["width"], item["height"])
        tile = layer_image(project, item, (0, 0, item["width"], item["height"]))
        image.alpha_composite(tile, (x, y))
    return image
