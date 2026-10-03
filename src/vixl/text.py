"""Shared Unicode shaping, layout and glyph outlines for PNG and SVG text."""

from dataclasses import dataclass
from functools import lru_cache
import io
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from bidi import algorithm as bidi
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.unicodedata import script
from PIL import Image
import resvg_py
import uharfbuzz as hb

from .errors import require
from .model import finite


class UnsupportedText(ValueError):
    """A font or layout cannot be outlined without changing its appearance."""


@dataclass
class Glyph:
    name: str
    x: float
    y: float
    advance: float


@dataclass
class Plan:
    width: int
    height: int
    paths: list
    box: tuple


@lru_cache(maxsize=16)
def face(data):
    outline = TTFont(io.BytesIO(data))
    if not any(table in outline for table in ("glyf", "CFF ", "CFF2")) or any(
        table in outline for table in ("COLR", "CBDT", "sbix", "SVG ")
    ):
        raise UnsupportedText("bitmap/color fonts require appearance-preserving raster export")
    native = hb.Face(data)
    font = hb.Font(native)
    font.scale = (native.upem, native.upem)
    hb.ot_font_set_funcs(font)
    return outline, font


def font_data(project, layer):
    from .render import font_for

    name = project.state.get("fonts", {}).get(layer.get("font"), layer.get("font"))
    if name in project.assets:
        return project.assets[name]
    font = font_for(project, layer)
    path = font.path
    return path.getvalue() if hasattr(path, "getvalue") else Path(path).read_bytes()


def runs(text):
    """Resolve bidi levels, shape logical script runs, then order runs visually."""
    if not text:
        return []
    storage = bidi.get_empty_storage()
    storage["base_level"] = bidi.get_base_level(text)
    storage["base_dir"] = ("L", "R")[storage["base_level"]]
    bidi.get_embedding_levels(text, storage)
    for index, char in enumerate(storage["chars"]):
        char["index"] = index
    try:
        for stage in (
            bidi.explicit_embed_and_overrides,
            bidi.resolve_weak_types,
            bidi.resolve_neutral_types,
            bidi.resolve_implicit_levels,
        ):
            stage(storage, False)
    except AssertionError as exc:
        raise UnsupportedText("Unicode isolate controls require raster text layout") from exc
    logical = list(storage["chars"])
    tags = [script(char["ch"]) for char in logical]
    for i, tag in enumerate(tags):
        if tag in ("Zyyy", "Zinh", "Zzzz"):
            left = next(
                (tags[j] for j in range(i - 1, -1, -1) if tags[j] not in ("Zyyy", "Zinh", "Zzzz")), None
            )
            right = next(
                (tags[j] for j in range(i + 1, len(tags)) if tags[j] not in ("Zyyy", "Zinh", "Zzzz")), None
            )
            tags[i] = left or right or "Latn"
    result = []
    for char, tag in zip(logical, tags):
        key = (char["level"], tag)
        if not result or result[-1][0] != key:
            result.append((key, []))
        result[-1][1].append(char)
        char["run"] = len(result) - 1
    bidi.reorder_resolved_levels(storage, False)
    order = list(dict.fromkeys(char["run"] for char in storage["chars"]))
    return [(result[i][0], "".join(c["ch"] for c in result[i][1])) for i in order]


def shape(data, text, size):
    outline, font = face(data)
    names, factor = outline.getGlyphOrder(), size / font.face.upem
    glyphs, cursor = [], 0.0
    for (level, tag), content in runs(text):
        buffer = hb.Buffer()
        buffer.add_str(content)
        buffer.direction = "rtl" if level % 2 else "ltr"
        buffer.script = tag
        buffer.guess_segment_properties()
        hb.shape(font, buffer)
        for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions):
            glyphs.append(
                Glyph(
                    names[info.codepoint],
                    cursor + pos.x_offset * factor,
                    -pos.y_offset * factor,
                    pos.x_advance * factor,
                )
            )
            cursor += pos.x_advance * factor
    return glyphs, cursor


@lru_cache(maxsize=2048)
def glyph_outline(data, name):
    glyphs = face(data)[0].getGlyphSet()
    pen = SVGPathPen(glyphs)
    glyphs[name].draw(pen)
    bounds = BoundsPen(glyphs)
    glyphs[name].draw(bounds)
    return pen.getCommands(), bounds.bounds


def clusters(data, word):
    """Wrap only at safe shaping boundaries, preserving marks and conjuncts."""
    if not word:
        return []
    buffer = hb.Buffer()
    buffer.add_str(word)
    buffer.guess_segment_properties()
    hb.shape(face(data)[1], buffer)
    boundaries = sorted(
        {0, len(word)}
        | {info.cluster for info in buffer.glyph_infos if not info.flags & hb.GlyphFlags.UNSAFE_TO_BREAK}
    )
    return [word[a:b] for a, b in zip(boundaries, boundaries[1:])]


def lines(data, text, size, width=None):
    result = []
    for paragraph in text.expandtabs(4).split("\n"):
        if width is None:
            result.append(paragraph)
            continue
        line = ""
        for word in paragraph.split(" "):
            proposed = line + (" " if line else "") + word
            if shape(data, proposed, size)[1] <= width:
                line = proposed
                continue
            if line:
                result.append(line)
            line = ""
            for char in clusters(data, word):
                if line and shape(data, line + char, size)[1] > width:
                    result.append(line)
                    line = ""
                line += char
        result.append(line)
    return result


def measure(data, text, size, spacing=4, align="left", width=None):
    finite(size, "font size", 1, 4096)
    outline = face(data)[0]
    factor = size / outline["head"].unitsPerEm
    ascent = outline["hhea"].ascent * factor
    line_height = (outline["hhea"].ascent - outline["hhea"].descent) * factor + spacing
    shaped = [shape(data, line, size) for line in lines(data, text, size, width)]
    widest = max((advance for _, advance in shaped), default=0)
    paths, bounds = [], []
    for i, (glyphs, advance) in enumerate(shaped):
        offset = (widest - advance) / 2 if align == "center" else widest - advance if align == "right" else 0
        for glyph in glyphs:
            path, box = glyph_outline(data, glyph.name)
            if path:
                x, y = glyph.x + offset, glyph.y + ascent + i * line_height
                paths.append((path, (factor, 0, 0, -factor, x, y)))
                if box:
                    bounds.append(
                        (box[0] * factor + x, -box[3] * factor + y, box[2] * factor + x, -box[1] * factor + y)
                    )
    box = (
        min((b[0] for b in bounds), default=0),
        min((b[1] for b in bounds), default=0),
        max(widest, max((b[2] for b in bounds), default=0)),
        max((b[3] for b in bounds), default=ascent) if bounds else ascent,
    )
    return paths, box


def plan(project, layer):
    require(len(layer["text"]) <= 100000, "Text exceeds length limit", "resource_limit")
    data = font_data(project, layer)
    settings = layer.get("text_layout", {})
    size, spacing, align = layer["size"], layer.get("spacing", 4), layer.get("align", "left")
    width = layer["width"] if "width" in settings else None
    stroke = layer.get("stroke_width", 0)
    if settings.get("fit") and width:
        low, high = 1, size
        while low < high:
            middle = (low + high + 1) // 2
            _, box = measure(data, layer["text"], middle, spacing, align, width)
            if box[2] - box[0] + 2 * stroke <= width and box[3] - box[1] + 2 * stroke <= layer["height"]:
                low = middle
            else:
                high = middle - 1
        size = low
    paths, box = measure(data, layer["text"], size, spacing, align, width)
    box = (box[0] - stroke, box[1] - stroke, box[2] + stroke, box[3] + stroke)
    tw, th = max(1, math.ceil(box[2] - box[0])), max(1, math.ceil(box[3] - box[1]))
    project.limits.size(tw, th)
    target_w, target_h = (layer["width"], layer["height"]) if settings else (tw, th)
    offset = (target_w - tw) / 2 if align == "center" else target_w - tw if align == "right" else 0
    positioned = [(p, (*m[:4], m[4] - box[0] + (offset if settings else 0), m[5] - box[1])) for p, m in paths]
    if settings.get("path"):
        positioned = path_layout(data, layer["text"], size, settings["path"])
    if settings.get("warp", "none") != "none":
        positioned = warped(positioned, target_w, target_h, settings)
    return Plan(target_w, target_h, positioned, box)


def path_layout(data, text, size, points):
    segments = [(a, b, math.dist(a, b)) for a, b in zip(points, points[1:]) if a != b]
    require(segments, "Text path must have nonzero length")
    glyphs, _ = shape(data, text.replace("\n", " "), size)
    factor = size / face(data)[0]["head"].unitsPerEm
    result = []
    for glyph in glyphs:
        center, offset = glyph.x + glyph.advance / 2, 0
        for a, b, length in segments:
            if center <= offset + length:
                t = (center - offset) / length
                dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                path, _ = glyph_outline(data, glyph.name)
                x, y = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                result.append(
                    (
                        path,
                        (
                            factor * dx,
                            factor * dy,
                            factor * dy,
                            -factor * dx,
                            x - dx * glyph.advance / 2 - dy * glyph.y,
                            y - dy * glyph.advance / 2 + dx * glyph.y,
                        ),
                    )
                )
                break
            offset += length
    return result


def warped(paths, width, height, settings):
    from fontTools.pens.basePen import BasePen
    from fontTools.svgLib.path import parse_path

    class Pen(BasePen):
        def __init__(self, matrix):
            super().__init__(None)
            self.matrix, self.commands = matrix, []

        def point(self, p):
            a, b, c, d, e, f = self.matrix
            x, y = a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f
            t, amount = 2 * x / max(1, width - 1) - 1, settings.get("amount", 0.2)
            kind = settings["warp"]
            if kind == "bulge":
                factor = max(0.01, 1 - abs(amount) + amount * (1 - t * t))
                y = height / 2 + (y - height / 2) * factor
            else:
                y += amount * height * ((t * t - 0.5) if kind == "arc" else math.sin(t * math.pi))
            return f"{x:.5f},{y:.5f}"

        def _moveTo(self, p):
            self.commands.append("M" + self.point(p))

        def _lineTo(self, p):
            self.commands.append("L" + self.point(p))

        def _curveToOne(self, p1, p2, p3):
            p0 = self._getCurrentPoint()
            for i in range(1, 25):
                t = i / 24
                self._lineTo(
                    tuple(
                        (1 - t) ** 3 * p0[j]
                        + 3 * (1 - t) ** 2 * t * p1[j]
                        + 3 * (1 - t) * t * t * p2[j]
                        + t**3 * p3[j]
                        for j in (0, 1)
                    )
                )

        def _qCurveToOne(self, p1, p2):
            p0 = self._getCurrentPoint()
            for i in range(1, 17):
                t = i / 16
                self._lineTo(
                    tuple((1 - t) ** 2 * p0[j] + 2 * (1 - t) * t * p1[j] + t * t * p2[j] for j in (0, 1))
                )

        def _closePath(self):
            self.commands.append("Z")

        def _endPath(self):
            pass

    result = []
    for path, matrix in paths:
        pen = Pen(matrix)
        parse_path(path, pen)
        result.append((" ".join(pen.commands), (1, 0, 0, 1, 0, 0)))
    return result


def append_paths(parent, layout, layer, project):
    from .render import color
    from .design import resolve_color

    fill, stroke = [
        color(resolve_color(layer.get(key, default), project.state))
        for key, default in (("color", "white"), ("stroke_color", "black"))
    ]
    for path, matrix in layout.paths:
        ET.SubElement(
            parent,
            "{http://www.w3.org/2000/svg}path",
            {
                "d": path,
                "transform": "matrix(" + " ".join(map(str, matrix)) + ")",
                "fill": f"rgb{fill[:3]}",
                "fill-opacity": str(fill[3] / 255),
                "stroke": f"rgb{stroke[:3]}",
                "stroke-opacity": str(stroke[3] / 255),
                "stroke-width": str(
                    2 * layer.get("stroke_width", 0) / max(1e-6, math.hypot(matrix[0], matrix[1]))
                ),
                "paint-order": "stroke fill",
            },
        )


def render_text(project, layer):
    layout = plan(project, layer)
    root = ET.Element(
        "{http://www.w3.org/2000/svg}svg",
        {
            "width": str(layout.width),
            "height": str(layout.height),
            "viewBox": f"0 0 {layout.width} {layout.height}",
        },
    )
    append_paths(root, layout, layer, project)
    return Image.open(
        io.BytesIO(resvg_py.svg_to_bytes(svg_string=ET.tostring(root, encoding="unicode")))
    ).convert("RGBA")
