"""Self-contained SVG with vector logo geometry and explicit raster fallbacks."""

import base64
from copy import deepcopy
import json
import math
import xml.etree.ElementTree as ET

from .assets import png_bytes
from .design import resolve_color
from .design_render import artboard_project
from .geometry import shape_path
from .render import color, layer_image, render, resolved_layers, resolve_layout
from .errors import VixlError
from .svg_effects import supported, native_styles, effect_filter, style_filter

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
    return native_styles(layer, state)


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
        self.text_reasons = {}

    def ident(self, prefix):
        self.counter += 1
        return f"vixl-{prefix}-{self.counter}"

    def visible(self, layer):
        while layer:
            if not layer["visible"] or layer["opacity"] == 0:
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
        from .text import plan, append_paths, UnsupportedText

        try:
            layout = plan(self.project, layer)
            nested = node(
                parent,
                "svg",
                width=layer["width"],
                height=layer["height"],
                viewBox=f"0 0 {layout.width} {layout.height}",
                preserveAspectRatio="none",
                overflow="hidden",
            )
            append_paths(nested, layout, layer, self.project)
            return True
        except UnsupportedText as exc:
            self.text_reasons[layer["id"]] = str(exc)
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
        if not layer["visible"] or layer["opacity"] == 0:
            return
        if layer["type"] == "adjustment":
            parent_layer = self.index.get(layer.get("parent"))
            w, h = (
                (parent_layer["content_width"], parent_layer["content_height"])
                if parent_layer
                else (self.project.state["canvas"]["width"], self.project.state["canvas"]["height"])
            )
            previous = list(parent)
            wrapper = node(parent, "g", filter=effect_filter(self, layer["effects"], (0, 0, w, h)))
            for child in previous:
                if child is not self.defs:
                    parent.remove(child)
                    wrapper.append(child)
            return
        b = self.bounds[layer["id"]]
        simple = (
            not (layer.get("mask") and layer["mask"].get("enabled", True))
            and not any(layer.get(k) for k in ("repeat", "lookup"))
            and supported(layer)
            and vector_overlay(layer, self.project.state)
        )
        group = ET.Element(f"{{{NS}}}g", {"opacity": str(layer["opacity"]), "data-layer": layer["name"]})
        geometry = node(group, "g", transform=self.transform(layer, b))
        if simple and self.geometry(geometry, layer):
            effects = [dict(e) for e in layer.get("effects", []) if e.get("enabled", True)]
            if effects:
                from PIL import ImageStat, ImageOps

                for index, effect in enumerate(effects):
                    if effect["name"] == "contrast":
                        image = layer_image(
                            self.project, {**layer, "effects": effects[:index], "styles": {}, "opacity": 1}, b
                        )
                        effect["_mean"] = (
                            round(ImageStat.Stat(ImageOps.grayscale(image.convert("RGB"))).mean[0]) / 255
                        )
                wrapper = node(group, "g", filter=effect_filter(self, effects, b))
                group.remove(geometry)
                wrapper.append(geometry)
                geometry = wrapper
            overlay = styles(layer)
            if "gradient-overlay" in overlay:
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
            appearance = style_filter(self, layer, b)
            if layer.get("clip"):
                ident = self.ident("clip-mask")
                mask = node(
                    self.defs,
                    "mask",
                    id=ident,
                    maskUnits="userSpaceOnUse",
                    x=0,
                    y=0,
                    width=self.project.state["canvas"]["width"],
                    height=self.project.state["canvas"]["height"],
                    mask_type="alpha",
                )
                self.layer(mask, self.index[layer["clip"]])
                # Clip after styles, before overall layer opacity.
                wrapper = ET.Element(
                    f"{{{NS}}}g", {"opacity": group.attrib.pop("opacity"), "mask": f"url(#{ident})"}
                )
                wrapper.append(group)
                if appearance:
                    group.set("filter", appearance)
                parent.append(wrapper)
            elif appearance:
                group.set("filter", appearance)
                # Vixl applies opacity after layer styles.
                opacity = group.attrib.pop("opacity")
                outer = node(parent, "g", opacity=opacity)
                outer.append(group)
            else:
                parent.append(group)
        else:
            if layer.get("styles") or layer.get("clip"):
                from .render import layer_surface

                parent_layer = self.index.get(layer.get("parent"))
                size = (
                    (parent_layer["content_width"], parent_layer["content_height"])
                    if parent_layer
                    else (self.project.state["canvas"]["width"], self.project.state["canvas"]["height"])
                )
                bitmap(parent, layer_surface(self.project, layer, self.bounds, size, self.index))
            else:
                bitmap(parent, layer_image(self.project, layer, b), b[0], b[1])
            self.fallbacks.append(
                {
                    "layer": layer["name"],
                    "reason": self.text_reasons.get(layer["id"], "unsupported vector appearance"),
                    "effects": [
                        e["name"]
                        for e in layer.get("effects", [])
                        if e.get("enabled", True) and (not supported({"effects": [e]}))
                    ],
                    "styles": list(styles(layer)) if not native_styles(layer, self.project.state) else [],
                }
            )


def export_svg(project, *, scale=1, variables=None, artboard=None, comp=None, svg_policy="appearance"):
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
    backdrop = [
        item
        for item in exporter.layers
        if exporter.visible(item)
        and (
            item["blend"] != "normal"
            or (
                item["type"] == "adjustment"
                and (
                    not supported(item)
                    or item["opacity"] != 1
                    or item.get("mask")
                    or item.get("lookup")
                    or item.get("clip")
                    or any(e["name"] == "contrast" and e.get("enabled", True) for e in item["effects"])
                )
            )
        )
    ]
    if backdrop:
        bitmap(root, render(candidate))
        exporter.fallbacks.extend(
            {
                "layer": item["name"],
                "reason": "backdrop-dependent blend or adjustment requires document rasterization",
                "effects": [e["name"] for e in item.get("effects", []) if e.get("enabled", True)],
            }
            for item in backdrop
        )
    else:
        fill, alpha = paint(c["background"], candidate.state)
        if alpha:
            node(root, "rect", width=c["width"], height=c["height"], fill=fill, fill_opacity=alpha)
        for layer in exporter.children.get(None, []):
            exporter.layer(root, layer)
    if exporter.fallbacks:
        if svg_policy == "strict":
            raise VixlError(
                "svg_raster_required",
                "SVG requires raster content; see fallback details",
                fallbacks=exporter.fallbacks,
            )
        node(root, "metadata").text = json.dumps({"vixl": {"raster_fallbacks": exporter.fallbacks}})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
