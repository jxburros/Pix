"""Deterministic, local artistic treatments. No models or network calls."""

import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .constants import ARTISTIC_DEFAULTS


def blend(original, changed, amount):
    return Image.blend(original, changed, amount / 100)


def luminance(image):
    # Use Pillow's grayscale weights, also used by SVG component filters.
    return np.asarray(ImageOps.grayscale(image), dtype=np.float32)


def edge_filter(image, kernel):
    """Extend edge pixels before convolution; avoid an artificial picture frame."""
    values = np.asarray(image)
    padding = ((1, 1), (1, 1)) + (((0, 0),) if values.ndim == 3 else ())
    padded = Image.fromarray(np.pad(values, padding, mode="edge"))
    return padded.filter(kernel).crop((1, 1, image.width + 1, image.height + 1))


def remap(image, coordinates):
    """Bilinear spatial filters, chunked and premultiplied to protect alpha edges."""
    source = np.asarray(image)
    output = np.empty_like(source)
    h, w = source.shape[:2]
    for first in range(0, h, 128):
        yy, xx = np.mgrid[first : min(first + 128, h), :w].astype(np.float32)
        x, y = coordinates(xx, yy)
        x, y = np.clip(x, 0, w - 1), np.clip(y, 0, h - 1)
        x0, y0 = x.astype(np.int32), y.astype(np.int32)
        x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
        fx, fy = (x - x0)[..., None], (y - y0)[..., None]
        result = np.zeros((*x.shape, 4), dtype=np.float32)
        for ix, iy, weight in (
            (x0, y0, (1 - fx) * (1 - fy)),
            (x1, y0, fx * (1 - fy)),
            (x0, y1, (1 - fx) * fy),
            (x1, y1, fx * fy),
        ):
            pixel = source[iy, ix].astype(np.float32)
            pixel[..., :3] *= pixel[..., 3:] / 255
            result += pixel * weight
        result[..., :3] *= 255 / np.maximum(result[..., 3:], 1e-6)
        output[first : first + len(x)] = np.uint8(np.clip(result, 0, 255) + 0.5)
    return Image.fromarray(output)


def artistic_filter(image, effect):
    name = effect["name"]
    amount = effect.get("amount", ARTISTIC_DEFAULTS[name])
    radius = effect.get("radius")
    rgb, alpha = image.convert("RGB"), image.getchannel("A")
    gray = ImageOps.grayscale(rgb)
    w, h = image.size
    if name in ("swirl", "ripple", "wave", "glass"):
        if amount == 0:
            return image.copy()
        if name == "glass":
            rng = np.random.default_rng(effect.get("seed", 0))
            cell = max(1, int(radius or 12))
            displacement = []
            for _ in range(2):
                noise = Image.fromarray(
                    rng.integers(
                        0, 256, (max(2, math.ceil(h / cell)), max(2, math.ceil(w / cell))), dtype=np.uint8
                    )
                ).resize((w, h), Image.Resampling.BICUBIC)
                displacement.append(np.asarray(noise, dtype=np.float32) / 127.5 - 1)

        def coordinates(x, y):
            if name == "wave":
                return x + amount * np.sin(y * 2 * np.pi / (radius or 32)), y
            if name == "glass":
                iy, ix = y.astype(int), x.astype(int)
                return x + displacement[0][iy, ix] * amount, y + displacement[1][iy, ix] * amount
            cx, cy = (w - 1) / 2, (h - 1) / 2
            dx, dy = x - cx, y - cy
            distance = np.hypot(dx, dy)
            if name == "swirl":
                extent = max(1, min(w, h) * (radius or 0.8) / 2)
                angle = np.arctan2(dy, dx) - math.radians(amount) * np.maximum(0, 1 - distance / extent) ** 2
                return cx + distance * np.cos(angle), cy + distance * np.sin(angle)
            offset = amount * np.sin(distance * 2 * np.pi / (radius or 32))
            factor = (distance + offset) / np.maximum(distance, 1e-6)
            return cx + dx * factor, cy + dy * factor

        return remap(image, coordinates)
    if name == "sepia":
        a = np.asarray(rgb, dtype=np.float32)
        a = a @ np.array([[0.393, 0.349, 0.272], [0.769, 0.686, 0.534], [0.189, 0.168, 0.131]])
        changed = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
        result = blend(rgb, changed, amount)
    elif name == "duotone":
        from .render import color

        low = np.array(color(effect.get("shadow_color", "#172544"))[:3], dtype=float)
        high = np.array(color(effect.get("highlight_color", "#ffe6ac"))[:3], dtype=float)
        t = luminance(rgb)[..., None] / 255
        changed = Image.fromarray(np.uint8(low + (high - low) * t + 0.5))
        result = blend(rgb, changed, amount)
    elif name == "solarize":
        result = ImageOps.solarize(rgb, int(amount))
    elif name == "pixelate":
        cell = int(amount)
        # Average colors in premultiplied space so transparent colored pixels do
        # not contaminate visible blocks. Spatial filters transform alpha too.
        size = (max(1, math.ceil(w / cell)), max(1, math.ceil(h / cell)))
        return (
            image.convert("RGBa")
            .resize(size, Image.Resampling.BOX)
            .resize((w, h), Image.Resampling.NEAREST)
            .convert("RGBA")
        )
    elif name in ("halftone", "crosshatch"):
        cell = int(amount)
        result = Image.new("RGB", image.size, "white")
        draw = ImageDraw.Draw(result)
        values = np.asarray(gray)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                darkness = 1 - float(values[y : y + cell, x : x + cell].mean()) / 255
                if name == "halftone":
                    r = cell * math.sqrt(darkness / math.pi)
                    cx, cy = x + cell / 2, y + cell / 2
                    if r:
                        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill="black")
                else:
                    if darkness > 0.2:
                        draw.line((x, y + cell - 1, x + cell - 1, y), fill="black")
                    if darkness > 0.45:
                        draw.line((x, y, x + cell - 1, y + cell - 1), fill="black")
                    if darkness > 0.7:
                        draw.line((x, y + cell // 2, x + cell - 1, y + cell // 2), fill="black", width=2)
    elif name in ("ink-blot", "stamp", "photocopy"):
        if name == "ink-blot":
            size = round(radius if radius is not None else 2)
            softened = gray.filter(ImageFilter.GaussianBlur(size / 2))
            ink = softened.point(lambda p: 255 if p < amount else 0)
            if size:
                ink = ink.filter(ImageFilter.MaxFilter(2 * size + 1)).filter(
                    ImageFilter.MinFilter(2 * size + 1)
                )
            result = ImageOps.invert(ink).convert("RGB")
        elif name == "stamp":
            result = gray.point(lambda p: 255 if p >= amount else 0).convert("RGB")
        else:
            edges = edge_filter(gray, ImageFilter.FIND_EDGES)
            result = (
                ImageChops.subtract(gray, edges).point(lambda p: 255 if p >= amount else 0).convert("RGB")
            )
    elif name in ("pencil-sketch", "charcoal"):
        blur = gray.filter(
            ImageFilter.GaussianBlur(radius if radius is not None else (12 if name == "pencil-sketch" else 2))
        )
        a, b = np.asarray(gray, dtype=np.float32), np.asarray(blur, dtype=np.float32)
        if name == "pencil-sketch":
            changed = Image.fromarray(np.uint8(np.clip(a * 255 / np.maximum(b, 1), 0, 255))).convert("RGB")
        else:
            edge = np.asarray(edge_filter(gray, ImageFilter.FIND_EDGES), dtype=np.float32)
            changed = Image.fromarray(np.uint8(np.clip(255 - edge * 2 - (255 - b) * 0.4, 0, 255))).convert(
                "RGB"
            )
        result = blend(rgb, changed, amount)
    elif name in ("find-edges", "emboss"):
        changed = edge_filter(rgb, ImageFilter.FIND_EDGES if name == "find-edges" else ImageFilter.EMBOSS)
        result = blend(rgb, changed, amount)
    elif name == "oil-paint":
        size = 2 * int(amount) + 1
        result = ImageOps.posterize(rgb.filter(ImageFilter.ModeFilter(size)), 5)
    elif name == "watercolor":
        changed = ImageOps.posterize(
            rgb.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.SMOOTH_MORE), 4
        )
        rng = np.random.default_rng(effect.get("seed", 0))
        a = np.asarray(changed, dtype=np.int16)
        paper = rng.integers(-6, 7, (h, w, 1), dtype=np.int16)
        changed = Image.fromarray(np.uint8(np.clip(a + paper, 0, 255)))
        result = blend(rgb, changed, amount)
    else:
        raise ValueError(f"Unknown artistic filter: {name}")
    result = result.convert("RGBA")
    result.putalpha(alpha)
    return result
