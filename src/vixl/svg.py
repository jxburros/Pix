"""Self-contained SVG with vector logo geometry and explicit raster fallbacks."""

import base64
from copy import deepcopy
import io
import json
import math
import xml.etree.ElementTree as ET

from .assets import png_bytes
from .design import resolve_color
from .design_render import artboard_project
from .geometry import shape_path
from .render import color, font_for, layer_image, render, resolved_layers, resolve_layout, text_metrics

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)


def node(parent, kind, **attrs):
    return ET.SubElement(parent, f"{{{NS}}}{kind}", {k.replace("_", "-"): str(v) for k, v in attrs.items()})


def paint(value, state):
    r, g, b, a = color(resolve_color(value, state))
    return f"rgb({r},{g},{b})", a / 255


def bitmap(root, image, x=0, y=0):
    node(
        root,
        "image",
        x=x,
        y=y,
        width=image.width,
        height=image.height,
        href="data:image/png;base64," + base64.b64encode(png_bytes(image)).decode(),
    )


def styles(layer):
    return {
        name: settings for name, settings in layer.get("styles", {}).items() if settings.get("enabled", True)
    }


def vector_overlay(layer, state):
    """Full-strength opaque overlays preserve a vector silhouette exactly."""
    active = styles(layer)
    if not active:
        return True
    if set(active) - {"gradient-overlay", "color-overlay"}:
        return False
    for name, settings in active.items():
        if settings.get("opacity", 1) != 1:
            return False
        values = (
            (
                [s["color"] for s in settings["stops"]]
                if settings.get("stops")
                else [settings.get("start", "black"), settings.get("end", "white")]
            )
            if name == "gradient-overlay"
            else [settings.get("color", "white")]
        )
        if any(color(resolve_color(value, state))[3] != 255 for value in values):
            return False
    return True


class Exporter:
    def __init__(self, project, root):
        self.project, self.root = project, root
        self.layers = resolved_layers(project)
        self.bounds = resolve_layout(project, layers=self.layers)
        self.index = {item["id"]: item for item in self.layers}
        self.children = {}
        for layer in self.layers:
            self.children.setdefault(layer.get("parent"), []).append(layer)
        self.defs = node(root, "defs")
        self.counter = 0
        self.fallbacks = []

    def ident(self, prefix):
        self.counter += 1
        return f"vixl-{prefix}-{self.counter}"

    def visible(self, layer):
        while layer:
            if not layer["visible"]:
                return False
            layer = self.index.get(layer.get("parent"))
        return True

    def transform(self, layer, bounds):
        x, y, w, h = bounds
        # SVG's y axis points down, like Vixl. Positive angles are clockwise.
        return (
            f"translate({x + w / 2} {y + h / 2}) rotate({layer['rotation']}) "
            f"scale({-1 if layer['flip_x'] else 1} {-1 if layer['flip_y'] else 1}) "
            f"translate({-layer['width'] / 2} {-layer['height'] / 2})"
        )

    def attrs(self, layer):
        fill, alpha = paint(layer.get("fill", "white"), self.project.state)
        stroke, sa = paint(layer.get("stroke", "transparent"), self.project.state)
        return dict(
            fill=fill,
            fill_opacity=alpha,
            stroke=stroke,
            stroke_opacity=sa,
            stroke_width=layer.get("stroke_width", 1),
        )

    def shape(self, parent, layer):
        attrs = self.attrs(layer)
        sw, sh = layer["width"], layer["height"]
        shape = layer.get("shape", "rectangle")
        if shape in ("rectangle", "rounded-rectangle", "capsule"):
            node(
                parent,
                "rect",
                width=sw,
                height=sh,
                rx=layer.get("radius", min(sw, sh) / (2 if shape == "capsule" else 5))
                if shape != "rectangle"
                else 0,
                **attrs,
            )
        elif shape == "ellipse":
            node(parent, "ellipse", cx=sw / 2, cy=sh / 2, rx=sw / 2, ry=sh / 2, **attrs)
        elif shape == "line":
            attrs.update(
                stroke=attrs["stroke"] if attrs["stroke_opacity"] else attrs["fill"],
                stroke_opacity=attrs["stroke_opacity"] or attrs["fill_opacity"],
            )
            node(parent, "line", x1=0, y1=0, x2=sw, y2=sh, **attrs)
        else:
            path, view = shape_path(layer)
            nested = node(
                parent,
                "svg",
                width=sw,
                height=sh,
                viewBox=f"0 0 {view[0]} {view[1]}",
                preserveAspectRatio="none",
            )
            node(nested, "path", d=path, **attrs)

    def text(self, parent, layer):
        """Outline plain Latin wordmarks: portable, no installed fonts required."""
        from fontTools.pens.svgPathPen import SVGPathPen
        from fontTools.pens.transformPen import TransformPen
        from fontTools.ttLib import TTFont, TTLibError

        text = layer["text"]
        # Complex shaping, ligatures and text layout retain their faithful raster
        # appearance rather than exporting a misleading sequence of glyphs.
        if (
            layer.get("text_layout")
            or any(ord(c) < 32 or ord(c) > 126 for c in text)
            or any(pair in text for pair in ("fi", "fl", "ff"))
        ):
            return False
        font = font_for(self.project, layer)
        source = self.project.assets.get(layer.get("font"))
        source = io.BytesIO(source) if source is not None else font.path
        try:
            with TTFont(source) as outline:
                cmap = outline.getBestCmap()
                if any(ord(c) not in cmap for c in text):
                    return False
                glyphs = outline.getGlyphSet()
                factor = layer["size"] / outline["head"].unitsPerEm
                tw, th, box = text_metrics(self.project, layer)
                group = node(parent, "g", transform=f"scale({layer['width'] / tw} {layer['height'] / th})")
                fill, alpha = paint(layer.get("color", "white"), self.project.state)
                stroke, sa = paint(layer.get("stroke_color", "black"), self.project.state)
                baseline = font.getmetrics()[0] - box[1]
                cursor = 0
                for i, char in enumerate(text):
                    x = cursor - box[0]
                    pen = SVGPathPen(glyphs)
                    transformed = TransformPen(pen, (factor, 0, 0, -factor, x, baseline))
                    glyphs[cmap[ord(char)]].draw(transformed)
                    path = pen.getCommands()
                    if path:
                        node(
                            group,
                            "path",
                            d=path,
                            fill=fill,
                            fill_opacity=alpha,
                            stroke=stroke,
                            stroke_opacity=sa if layer.get("stroke_width", 0) else 0,
                            stroke_width=2 * layer.get("stroke_width", 0),
                            paint_order="stroke fill",
                        )
                    # Pair kerning keeps plain wordmarks aligned with Pillow
                    # without repeatedly shaping an ever-growing prefix.
                    cursor += (
                        font.getlength(char + text[i + 1]) - font.getlength(text[i + 1])
                        if i + 1 < len(text)
                        else font.getlength(char)
                    )
                return True
        except (OSError, ValueError, KeyError, TTLibError):
            return False

    def gradient(self, settings, box):
        ident = self.ident("gradient")
        x, y, w, h = box
        direction = settings.get("direction", "vertical")
        if direction == "radial":
            gradient = node(
                self.defs,
                "radialGradient",
                id=ident,
                gradientUnits="userSpaceOnUse",
                cx=0,
                cy=0,
                r=1,
                gradientTransform=f"translate({x + w / 2} {y + h / 2}) scale({w / 2} {h / 2})",
            )
        else:
            a = math.radians(settings.get("angle", 0))
            dx, dy = (
                (math.cos(a), math.sin(a))
                if direction == "angled"
                else ((1, 0) if direction == "horizontal" else (0, 1))
            )
            norm = abs(dx) + abs(dy)
            qx, qy = dx / max(1, w - 1) / norm, dy / max(1, h - 1) / norm
            square = qx * qx + qy * qy
            cx, cy = x + (w - 1) / 2, y + (h - 1) / 2
            gradient = node(
                self.defs,
                "linearGradient",
                id=ident,
                gradientUnits="userSpaceOnUse",
                x1=cx - qx / (2 * square),
                y1=cy - qy / (2 * square),
                x2=cx + qx / (2 * square),
                y2=cy + qy / (2 * square),
            )
        for stop in settings.get("stops") or [
            {"offset": 0, "color": settings.get("start", "black")},
            {"offset": 1, "color": settings.get("end", "white")},
        ]:
            fill, alpha = paint(stop["color"], self.project.state)
            node(gradient, "stop", offset=stop["offset"], stop_color=fill, stop_opacity=alpha)
        return f"url(#{ident})"

    def pathfinder(self, parent, layer):
        from .render import transformed_size

        # SVG masks match opaque boolean operands. Translucent operands retain
        # Vixl's alpha max/min/subtraction through the raster implementation.
        for operand in layer["operands"]:
            if (
                operand["opacity"] != 1
                or operand.get("effects")
                or operand.get("mask")
                or styles(operand)
                or operand.get("repeat")
                or operand.get("lookup")
                or color(resolve_color(operand.get("fill", "white"), self.project.state))[3] != 255
                or color(resolve_color(operand.get("stroke", "transparent"), self.project.state))[3]
                not in (0, 255)
            ):
                return False
        w, h = layer["width"], layer["height"]
        sx, sy = w / layer["content_width"], h / layer["content_height"]
        masks = []
        for operand in layer["operands"]:
            item = deepcopy(operand)
            item.update(width=max(1, round(item["width"] * sx)), height=max(1, round(item["height"] * sy)))
            item["x"], item["y"] = round(item["x"] * sx), round(item["y"] * sy)
            ident = self.ident("operand")
            mask = node(
                self.defs,
                "mask",
                id=ident,
                maskUnits="userSpaceOnUse",
                x=0,
                y=0,
                width=w,
                height=h,
                mask_type="alpha",
            )
            g = node(
                mask, "g", transform=self.transform(item, (item["x"], item["y"], *transformed_size(item)))
            )
            if not self.geometry(g, item):
                return False
            masks.append(ident)
        ident = self.ident("boolean")
        mask = node(self.defs, "mask", id=ident, maskUnits="userSpaceOnUse", x=0, y=0, width=w, height=h)
        if layer["mode"] == "union":
            for operand in masks:
                node(mask, "rect", width=w, height=h, fill="white", mask=f"url(#{operand})")
        elif layer["mode"] == "subtract":
            node(mask, "rect", width=w, height=h, fill="white", mask=f"url(#{masks[0]})")
            for operand in masks[1:]:
                node(mask, "rect", width=w, height=h, fill="black", mask=f"url(#{operand})")
        else:
            current = mask
            for operand in masks:
                current = node(current, "g", mask=f"url(#{operand})")
            node(current, "rect", width=w, height=h, fill="white")
        fill, _ = paint(layer.get("fill", "white"), self.project.state)
        node(parent, "rect", width=w, height=h, fill=fill, mask=f"url(#{ident})")
        return True

    def geometry(self, parent, layer):
        kind = layer["type"]
        if kind in ("shape", "solid"):
            self.shape(parent, layer)
        elif kind == "text":
            return self.text(parent, layer)
        elif kind == "gradient":
            node(
                parent,
                "rect",
                width=layer["width"],
                height=layer["height"],
                fill=self.gradient(layer, (0, 0, layer["width"], layer["height"])),
            )
        elif kind == "pathfinder":
            return self.pathfinder(parent, layer)
        elif kind == "pixel":
            rows = layer["pixels"]
            group = node(
                parent,
                "g",
                transform=f"scale({layer['width'] / len(rows[0])} {layer['height'] / len(rows)})",
                shape_rendering="crispEdges",
            )
            for y, row in enumerate(rows):
                x = 0
                while x < len(row):
                    end = x + 1
                    while end < len(row) and row[end] == row[x]:
                        end += 1
                    fill, alpha = paint(layer["palette"][row[x]], self.project.state)
                    if alpha:
                        node(group, "rect", x=x, y=y, width=end - x, height=1, fill=fill, fill_opacity=alpha)
                    x = end
        elif kind == "group":
            cw, ch = layer["content_width"], layer["content_height"]
            ident = self.ident("group-clip")
            clip = node(self.defs, "clipPath", id=ident)
            node(clip, "rect", width=cw, height=ch)
            group = node(
                parent,
                "g",
                transform=f"scale({layer['width'] / cw} {layer['height'] / ch})",
                clip_path=f"url(#{ident})",
            )
            for child in self.children.get(layer["id"], []):
                self.layer(group, child)
        else:
            return False
        return True

    def layer(self, parent, layer):
        if not layer["visible"]:
            return
        b = self.bounds[layer["id"]]
        simple = not any(layer.get(k) for k in ("mask", "effects", "clip", "repeat", "lookup"))
        group = ET.Element(f"{{{NS}}}g", {"opacity": str(layer["opacity"]), "data-layer": layer["name"]})
        geometry = node(group, "g", transform=self.transform(layer, b))
        if simple and self.geometry(geometry, layer):
            overlay = styles(layer)
            if overlay:
                alpha = layer_image(self.project, {**layer, "styles": {}, "opacity": 1}, b).getchannel("A")
                box = alpha.getbbox()
                if box:
                    ident = self.ident("overlay-mask")
                    mask = node(
                        self.defs,
                        "mask",
                        id=ident,
                        maskUnits="userSpaceOnUse",
                        x=b[0],
                        y=b[1],
                        width=b[2],
                        height=b[3],
                        mask_type="alpha",
                    )
                    group.remove(geometry)
                    mask.append(geometry)
                    x, y = b[0] + box[0], b[1] + box[1]
                    w, h = box[2] - box[0], box[3] - box[1]
                    fill = (
                        self.gradient(overlay["gradient-overlay"], (x, y, w, h))
                        if "gradient-overlay" in overlay
                        else paint(overlay["color-overlay"].get("color", "white"), self.project.state)[0]
                    )
                    node(group, "rect", x=x, y=y, width=w, height=h, fill=fill, mask=f"url(#{ident})")
            parent.append(group)
        else:
            bitmap(parent, layer_image(self.project, layer, b), b[0], b[1])
            self.fallbacks.append(
                {"layer": layer["name"], "reason": "unsupported vector appearance or text shaping"}
            )


def export_svg(project, *, scale=1, variables=None, artboard=None, comp=None):
    candidate = artboard_project(project, artboard, comp, variables)
    c = candidate.state["canvas"]
    root = ET.Element(
        f"{{{NS}}}svg",
        {
            "width": str(c["width"] * scale),
            "height": str(c["height"] * scale),
            "viewBox": f"0 0 {c['width']} {c['height']}",
        },
    )
    exporter = Exporter(candidate, root)
    flatten = any(
        exporter.visible(item)
        and (
            item["type"] == "adjustment"
            or item["blend"] != "normal"
            or item.get("clip")
            or not vector_overlay(item, candidate.state)
        )
        for item in exporter.layers
    )
    if flatten:
        bitmap(root, render(candidate))
        exporter.fallbacks.append(
            {"layer": "document", "reason": "backdrop-dependent blend, clipping, or raster style"}
        )
    else:
        fill, alpha = paint(c["background"], candidate.state)
        if alpha:
            node(root, "rect", width=c["width"], height=c["height"], fill=fill, fill_opacity=alpha)
        for layer in exporter.children.get(None, []):
            exporter.layer(root, layer)
    if exporter.fallbacks:
        node(root, "metadata").text = json.dumps({"vixl": {"raster_fallbacks": exporter.fallbacks}})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
