"""Compact palette-indexed pixel layers and deterministic integer-coordinate drawing."""

from collections import deque
from copy import deepcopy

from PIL import Image, ImageDraw

from .errors import require
from .model import new_layer

PIXEL_TYPES = ("pixel-art", "pixel-draw", "pixel-palette")
MAX_GRID = 256


def validate_pixel(layer, state):
    from .render import color
    from .design import resolve_color

    rows, palette = layer["pixels"], layer["palette"]
    require(isinstance(rows, list) and 1 <= len(rows) <= MAX_GRID, "Pixel grid height must be 1–256")
    require(all(isinstance(row, str) for row in rows), "Pixel rows must be strings")
    width = len(rows[0])
    require(
        1 <= width <= MAX_GRID and all(len(row) == width for row in rows),
        "Pixel rows need equal widths of 1–256",
    )
    require(isinstance(palette, dict) and 1 <= len(palette) <= 94, "Palette needs 1–94 symbols")
    for symbol, value in palette.items():
        require(
            isinstance(symbol, str) and len(symbol) == 1 and 33 <= ord(symbol) <= 126,
            "Palette symbols must be single printable non-space ASCII characters",
        )
        color(resolve_color(value, state))
    require(set("".join(rows)) <= palette.keys(), "Every pixel must have a palette entry")


def pixel_image(project, layer):
    from .render import color
    from .design import resolve_color

    rows = layer["pixels"]
    palette = {key: color(resolve_color(value, project.state)) for key, value in layer["palette"].items()}
    image = Image.new("RGBA", (len(rows[0]), len(rows)))
    image.putdata([palette[symbol] for row in rows for symbol in row])
    return image


def inspect_pixels(project, target=None):
    layer = project.layer(target)
    require(layer["type"] == "pixel", "Target must be a pixel-art layer")
    return {
        "id": layer["id"],
        "name": layer["name"],
        "width": len(layer["pixels"][0]),
        "height": len(layer["pixels"]),
        "palette": deepcopy(layer["palette"]),
        "rows": list(layer["pixels"]),
    }


def execute_pixel(project, op):
    from .operations import append_layer

    if op["type"] == "pixel-art":
        rows = op.get("rows")
        palette = deepcopy(op.get("palette", {".": "transparent", "#": "black"}))
        if rows is None:
            width, height = op.get("width", 16), op.get("height", 16)
            require(1 <= width <= MAX_GRID and 1 <= height <= MAX_GRID, "Pixel grid dimensions must be 1–256")
            symbol = op.get("background", ".")
            require(symbol in palette, "Background symbol is not in the palette")
            rows = [symbol * width for _ in range(height)]
        else:
            require(
                "width" not in op and "height" not in op and "background" not in op,
                "Rows specify their own dimensions and background",
            )
        require(isinstance(rows, list) and rows and isinstance(rows[0], str), "Provide pixel rows")
        layer = new_layer(
            op.get("name", "sprite"),
            "pixel",
            len(rows[0]),
            len(rows),
            pixels=deepcopy(rows),
            palette=palette,
            x=op.get("x", 0),
            y=op.get("y", 0),
        )
        validate_pixel(layer, project.state)
        append_layer(project, layer)
        return
    layer = project.layer(op.get("target"))
    require(layer["type"] == "pixel", "Target must be a pixel-art layer")
    if op["type"] == "pixel-palette":
        layer["palette"].update(deepcopy(op["colors"]))
        validate_pixel(layer, project.state)
        return
    rows = layer["pixels"]
    w, h = len(rows[0]), len(rows)
    symbol = op["color"]
    require(symbol in layer["palette"], "Color must be a palette symbol")
    x, y = op["x"], op["y"]
    require(0 <= x < w and 0 <= y < h, "Pixel coordinate outside grid")
    tool = op.get("tool", "pixel")
    mask = Image.new("1", (w, h))
    draw = ImageDraw.Draw(mask)
    if tool == "fill":
        require(not any(key in op for key in ("x2", "y2", "width", "height")), "Fill needs only X/Y")
        old = rows[y][x]
        pending = deque([(x, y)])
        seen = {(x, y)}
        while pending:
            px, py = pending.popleft()
            mask.putpixel((px, py), 1)
            for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen and rows[ny][nx] == old:
                    seen.add((nx, ny))
                    pending.append((nx, ny))
    elif tool == "line":
        require("x2" in op and "y2" in op and "width" not in op and "height" not in op, "Line requires X2/Y2")
        require(0 <= op["x2"] < w and 0 <= op["y2"] < h, "Line endpoint outside grid")
        draw.line((x, y, op["x2"], op["y2"]), fill=1, width=1)
    elif tool == "rect":
        require(
            "width" in op and "height" in op and "x2" not in op and "y2" not in op,
            "Rectangle requires width/height",
        )
        require(x + op["width"] <= w and y + op["height"] <= h, "Rectangle outside grid")
        draw.rectangle((x, y, x + op["width"] - 1, y + op["height"] - 1), fill=1)
    else:
        require(
            tool == "pixel" and not any(key in op for key in ("x2", "y2", "width", "height")),
            "Pixel needs only X/Y",
        )
        draw.point((x, y), fill=1)
    layer["pixels"] = [
        "".join(symbol if mask.getpixel((px, py)) else rows[py][px] for px in range(w)) for py in range(h)
    ]
