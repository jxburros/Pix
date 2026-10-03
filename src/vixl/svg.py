"""Self-contained SVG: native simple shapes, embedded pixels for raster appearances."""

import base64
import xml.etree.ElementTree as ET

from .assets import png_bytes
from .design import resolve_color
from .design_render import artboard_project
from .geometry import shape_path
from .render import color, layer_image, render, resolved_layers, resolve_layout

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
    layers = resolved_layers(candidate)
    bounds = resolve_layout(candidate, layers=layers)
    # Adjustments and blend modes depend on the backdrop; flatten once for faithful output.
    if any(
        item["visible"]
        and (
            item["type"] == "adjustment"
            or item["blend"] != "normal"
            or item.get("clip")
            or item.get("styles")
        )
        for item in layers
    ):
        bitmap(root, render(candidate))
    else:
        fill, alpha = paint(c["background"], candidate.state)
        if alpha:
            node(root, "rect", width=c["width"], height=c["height"], fill=fill, fill_opacity=alpha)
        for layer in layers:
            if not layer["visible"] or layer.get("parent"):
                continue
            x, y, w, h = bounds[layer["id"]]
            simple = layer["type"] in ("shape", "solid") and not any(
                layer.get(k) for k in ("mask", "effects", "styles", "clip", "repeat", "lookup")
            )
            if not simple:
                bitmap(root, layer_image(candidate, layer, bounds[layer["id"]]), x, y)
                continue
            fill, alpha = paint(layer.get("fill", "white"), candidate.state)
            stroke, sa = paint(layer.get("stroke", "transparent"), candidate.state)
            group = node(root, "g", opacity=layer["opacity"], **{"data-layer": layer["name"]})
            # Rotation expands bounds in Pillow; retain that placement and rotate around the source center.
            transform = f"translate({x + w / 2} {y + h / 2}) rotate({-layer['rotation']}) scale({-1 if layer['flip_x'] else 1} {-1 if layer['flip_y'] else 1}) translate({-layer['width'] / 2} {-layer['height'] / 2})"
            group.set("transform", transform)
            attrs = dict(
                fill=fill,
                fill_opacity=alpha,
                stroke=stroke,
                stroke_opacity=sa,
                stroke_width=layer.get("stroke_width", 1),
            )
            sw, sh = layer["width"], layer["height"]
            shape = layer.get("shape", "rectangle")
            if shape in ("rectangle", "rounded-rectangle", "capsule"):
                node(
                    group,
                    "rect",
                    width=sw,
                    height=sh,
                    rx=layer.get("radius", min(sw, sh) / (2 if shape == "capsule" else 5))
                    if shape != "rectangle"
                    else 0,
                    **attrs,
                )
            elif shape == "ellipse":
                node(group, "ellipse", cx=sw / 2, cy=sh / 2, rx=sw / 2, ry=sh / 2, **attrs)
            elif shape == "line":
                attrs.update(stroke=stroke if sa else fill, stroke_opacity=sa if sa else alpha)
                node(group, "line", x1=0, y1=0, x2=sw, y2=sh, **attrs)
            else:
                path, view = shape_path(layer)
                nested = node(
                    group,
                    "svg",
                    width=sw,
                    height=sh,
                    viewBox=f"0 0 {view[0]} {view[1]}",
                    preserveAspectRatio="none",
                )
                node(nested, "path", d=path, **attrs)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
