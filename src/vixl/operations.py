"""Canonical operation dispatcher. CLI, scripts, REST and MCP use this same boundary."""

from .design_schema import TYPES as DESIGN_TYPES
from .pixel import PIXEL_TYPES
from .animation import ANIMATION_TYPES
from .resources import RESOURCE_TYPES

from copy import deepcopy
import hashlib
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .assets import add_image, decode, read_bounded
from .errors import VixlError, require
from .model import finite, new_layer, uid
from .render import (
    BLENDS,
    EFFECTS,
    CANVAS_PRESETS,
    color,
    layer_image,
    resolve_layout,
    text_metrics,
)

ALIASES = {
    "set_opacity": "opacity",
    "set_blend": "blend",
    "add_layer": "add",
    "remove_layer": "remove",
    "move_layer": "move",
    "set_effect": "effect",
    "make_selection": "select",
}

OPERATION_TYPES = list(DESIGN_TYPES + PIXEL_TYPES + ANIMATION_TYPES + RESOURCE_TYPES) + [
    "add",
    "solid",
    "gradient",
    "text",
    "text-set",
    "remove",
    "rename",
    "duplicate",
    "move",
    "resize",
    "scale",
    "rotate",
    "flip",
    "crop",
    "opacity",
    "blend",
    "hide",
    "show",
    "reorder",
    "raise",
    "lower",
    "top",
    "bottom",
    "select-layer",
    "align",
    "constrain",
    "unconstrain",
    "canvas",
    "select",
    "mask",
    "effect",
    "effect-set",
    "effect-disable",
    "effect-enable",
    "effect-remove",
    "rasterize",
    "variable",
    "preset-save",
    "preset-apply",
]


def effect_valid(effect):
    name = effect["name"]
    value = finite(effect.get("amount", 0), "amount", -100000, 100000)
    if name in ("blur", "gaussian-blur"):
        finite(value, "radius", 0, 1000)
    elif name == "sharpen":
        finite(value, "amount", 0, 100)
    elif name == "gamma":
        finite(value, "gamma", 0.01, 100)
    elif name == "exposure":
        finite(value, "exposure", -32, 32)
    elif name == "posterize":
        require(int(value) == value and 1 <= value <= 8, "Posterize bits must be 1–8")
    elif name == "threshold":
        finite(value, "threshold", 0, 255)
    elif name in ("grain", "noise"):
        finite(value, "noise", 0, 1)
    elif name == "vignette":
        finite(effect.get("strength", value), "strength", 0, 1)
        finite(effect.get("radius", 0.7), "radius", 0, 1.4)
    elif name == "levels":
        finite(effect.get("black", 0), "black", 0, 254)
        finite(effect.get("white", 255), "white", 1, 255)
        require(effect.get("black", 0) < effect.get("white", 255), "Levels white must exceed black")
    elif name == "curves":
        points = effect.get("points", [])
        require(
            2 <= len(points) <= 256 and all(len(p) == 2 for p in points),
            "Curves require 2–256 [input,output] points",
        )
        for x, y in points:
            finite(x, "input", 0, 255)
            finite(y, "output", 0, 255)
        require(
            all(points[i][0] < points[i + 1][0] for i in range(len(points) - 1)), "Curve inputs must increase"
        )
    if "seed" in effect:
        require(isinstance(effect["seed"], int) and effect["seed"] >= 0, "Seed must be a nonnegative integer")


def unique_name(project, proposed):
    require(isinstance(proposed, str) and 0 < len(proposed) <= 200, "Layer name must be 1–200 characters")
    require(
        not any(proposed in (x["name"], x["id"]) for x in project.state["layers"]),
        f"Layer name already exists: {proposed}",
    )
    return proposed


def append_layer(project, layer):
    require(len(project.state["layers"]) < project.limits.max_layers, "Layer limit reached", "resource_limit")
    unique_name(project, layer["name"])
    project.limits.size(layer["width"], layer["height"])
    project.state["layers"].append(layer)
    project.state["active_layer"] = layer["id"]
    return layer


def selection_image(project):
    selection = project.state["selection"]
    require(selection is not None, "No selection exists")
    return project.image(selection, "L")


def _select(project, op):
    c = project.state["canvas"]
    size = (c["width"], c["height"])
    shape = op.get("shape", "all")
    if shape == "none":
        project.state["selection"] = None
        return
    if shape == "invert":
        mask = ImageOps.invert(selection_image(project))
    elif shape == "all":
        mask = Image.new("L", size, 255)
    elif shape in ("rect", "ellipse"):
        x, y = finite(op.get("x", 0)), finite(op.get("y", 0))
        w, h = finite(op["width"], "width", 1), finite(op["height"], "height", 1)
        mask = Image.new("L", size)
        draw = ImageDraw.Draw(mask)
        getattr(draw, "rectangle" if shape == "rect" else "ellipse")((x, y, x + w - 1, y + h - 1), fill=255)
    elif shape == "alpha":
        layer = project.layer(op.get("target"))
        b = resolve_layout(project)[layer["id"]]
        rendered = layer_image(project, layer, b)
        mask = Image.new("L", size)
        mask.paste(rendered.getchannel("A"), (b[0], b[1]))
    elif shape == "color":
        rgb = np.asarray(project.render().convert("RGB"), dtype=np.int16)
        target = np.array(color(op["color"])[:3])
        tolerance = finite(op.get("tolerance", 15), "tolerance", 0, 255)
        mask = Image.fromarray(np.uint8(np.max(np.abs(rgb - target), axis=2) <= tolerance) * 255)
    elif shape == "asset":
        mask = project.image(op["asset"], "L")
        require(mask.size == size, "Selection mask must match canvas size")
    else:
        raise VixlError("invalid_selection", f"Unknown selection shape: {shape}")
    mode = op.get("mode", "replace")
    require(mode in ("replace", "add", "subtract", "intersect"), "Unknown selection combination")
    if mode != "replace" and project.state["selection"]:
        old, new = np.asarray(selection_image(project), dtype=np.int16), np.asarray(mask, dtype=np.int16)
        result = {
            "add": lambda: np.maximum(old, new),
            "subtract": lambda: np.maximum(0, old - new),
            "intersect": lambda: np.minimum(old, new),
        }[mode]()
        mask = Image.fromarray(np.uint8(result))
    if op.get("feather"):
        from PIL import ImageFilter

        radius = finite(op["feather"], "feather", 0, 1000)
        mask = mask.filter(ImageFilter.GaussianBlur(radius))
    project.state["selection"] = add_image(project, mask, "masks")


def execute(project, op):
    kind = op.get("type", op.get("operation"))
    kind = ALIASES.get(kind, kind)
    require(isinstance(kind, str), "Operation requires a type")
    target = op.get("target", op.get("layer"))
    if kind in RESOURCE_TYPES:
        from .resources import execute_resource

        execute_resource(project, op)
        return
    if kind in PIXEL_TYPES:
        from .pixel import execute_pixel

        execute_pixel(project, op)
        return
    if kind in ANIMATION_TYPES:
        from .animation import execute_animation

        execute_animation(project, op)
        return
    from .design import execute_design, resolve_color

    if kind in DESIGN_TYPES:
        execute_design(project, op)
        return
    if kind == "add":
        if "asset" in op:
            image = project.image(op["asset"])
            asset = op["asset"]
            provenance = op.get("provenance", {"type": "embedded"})
        else:
            source = Path(op["path"]).resolve()
            data = read_bounded(source, project.limits.max_asset_bytes)
            image = decode(data, project.limits)
            asset = add_image(project, image)
            provenance = {
                "type": "imported",
                "original_filename": source.name,
                "checksum": hashlib.sha256(data).hexdigest(),
            }
        layer = new_layer(
            op.get("name", Path(op.get("path", "image")).stem),
            "raster",
            *image.size,
            asset=asset,
            provenance=provenance,
        )
        if op.get("linked"):
            require("path" in op, "Linked layers require a path")
            layer["linked"] = str(source)
            project.allow_linked = True
        layer["x"], layer["y"] = finite(op.get("x", 0)), finite(op.get("y", 0))
        append_layer(project, layer)
        return
    if kind in ("solid", "gradient", "text"):
        c = project.state["canvas"]
        w, h = op.get("width", c["width"]), op.get("height", c["height"])
        layer = new_layer(op.get("name", kind), kind, w, h)
        if kind == "solid":
            color(resolve_color(op.get("color", "white"), project.state))
            layer["fill"] = op.get("color", "white")
        elif kind == "gradient":
            for key, default in (("start", "black"), ("end", "white")):
                color(resolve_color(op.get(key, default), project.state))
                layer[key] = op.get(key, default)
            layer["direction"] = op.get("direction", "vertical")
            layer.update({k: deepcopy(op[k]) for k in ("stops", "angle") if k in op})
        else:
            layer.update(
                {
                    "text": op["text"],
                    "font": project.state.get("fonts", {}).get(op.get("font"), op.get("font", "DejaVuSans.ttf")),
                    "size": op.get("size", 48),
                    "color": op.get("color", "white"),
                    "align": op.get("align", "left"),
                    "spacing": op.get("spacing", 4),
                    "auto_size": True,
                }
            )
            if Path(layer["font"]).is_file():
                data = read_bounded(layer["font"], project.limits.max_asset_bytes)
                name = f"fonts/{hashlib.sha256(data).hexdigest()}.ttf"
                project.assets[name] = data
                layer["font"] = name
            layer["width"], layer["height"], _ = text_metrics(project, layer)
            color(resolve_color(layer["color"], project.state))
        layer["x"] = finite(op.get("x", 0)) if op.get("x") != "center" else (c["width"] - layer["width"]) / 2
        layer["y"] = (
            finite(op.get("y", 0)) if op.get("y") != "center" else (c["height"] - layer["height"]) / 2
        )
        append_layer(project, layer)
        return
    if kind == "canvas":
        c = project.state["canvas"]
        w, h = (
            CANVAS_PRESETS[op["preset"]]
            if op.get("preset") in CANVAS_PRESETS
            else (op.get("width", c["width"]), op.get("height", c["height"]))
        )
        if "preset" in op:
            require(op["preset"] in CANVAS_PRESETS, "Unknown canvas preset")
        project.limits.size(w, h)
        background = op.get("background", c["background"])
        color(resolve_color(background, project.state))
        c.update(width=w, height=h, background=background)
        if project.state["selection"]:
            old = selection_image(project)
            mask = Image.new("L", (w, h))
            mask.paste(old, (0, 0))
            project.state["selection"] = add_image(project, mask, "masks")
        return
    if kind == "select":
        _select(project, op)
        return
    if kind == "variable":
        require(isinstance(op["name"], str) and re.fullmatch(r"[\w-]+", op["name"]), "Invalid variable name")
        if op.get("delete"):
            project.state["variables"].pop(op["name"], None)
        else:
            require(isinstance(op["value"], (str, int, float, bool)), "Variables must be scalar values")
            project.state["variables"][op["name"]] = op["value"]
        return
    layer = project.layer(target)
    layers = project.state["layers"]
    if kind == "select-layer":
        project.state["active_layer"] = layer["id"]
    elif kind == "remove":
        from .design import descendants

        removed = descendants(project, layer["id"]) | {layer["id"]}
        layers[:] = [item for item in layers if item["id"] not in removed]
        for item in layers:
            if item.get("clip") in removed:
                item.pop("clip")
        project.state["symbols"] = {
            k: v for k, v in project.state.get("symbols", {}).items() if v not in removed
        }
        for board in project.state.get("artboards", {}).values():
            if "targets" in board:
                board["targets"] = [ident for ident in board["targets"] if ident not in removed]
        if project.state["active_layer"] in removed:
            project.state["active_layer"] = layers[-1]["id"] if layers else None
    elif kind == "rename":
        layer["name"] = unique_name(project, op["name"])
    elif kind == "duplicate":
        duplicate = deepcopy(layer)
        duplicate["id"] = uid("lyr")
        duplicate["name"] = op.get("name", layer["name"] + " copy")
        append_layer(project, duplicate)
        if layer["type"] == "group":
            from .design import descendants

            children = descendants(project, layer["id"])
            copies = [deepcopy(item) for item in layers if item["id"] in children]
            mapping = {layer["id"]: duplicate["id"], **{item["id"]: uid("lyr") for item in copies}}
            for item in copies:
                original_id = item["id"]
                item["id"] = mapping[original_id]
                item["name"] = duplicate["name"] + "/" + original_id
                item["parent"] = mapping[item["parent"]]
                if item.get("clip") in mapping:
                    item["clip"] = mapping[item["clip"]]
                for anchor, expression in item["constraints"].items():
                    if isinstance(expression, str):
                        for old, new in mapping.items():
                            expression = expression.replace(old + ".", new + ".")
                        item["constraints"][anchor] = expression
                append_layer(project, item)
            project.state["active_layer"] = duplicate["id"]
    elif kind == "text-set":
        require(layer["type"] == "text", "Layer is not editable text")
        for key in ("text", "size", "color", "align", "spacing", "stroke_width", "stroke_color"):
            if key in op:
                layer[key] = op[key]
        require(layer["align"] in ("left", "center", "right"), "Invalid text alignment")
        finite(layer.get("spacing", 4), "spacing", 0, 1000)
        finite(layer.get("stroke_width", 0), "stroke_width", 0, 100)
        color(resolve_color(layer["color"], project.state))
        layer["width"], layer["height"], _ = text_metrics(project, layer)
        layer["auto_size"] = True
    elif kind == "move":
        bounds = resolve_layout(project)[layer["id"]]
        for i, axis in enumerate(("x", "y")):
            if axis in op:
                layer[axis] = finite(op[axis], axis) + (bounds[i] if op.get("relative") else 0)
        layer["constraints"] = {}
    elif kind in ("resize", "scale"):
        w, h = layer["width"], layer["height"]
        if kind == "scale":
            factor = finite(op["value"], "scale", 0.001, 100)
            w, h = max(1, round(w * factor)), max(1, round(h * factor))
        else:
            require("width" in op or "height" in op, "Resize requires width or height")
            w = op.get("width", max(1, round(w * op.get("height", h) / h)))
            h = op.get("height", max(1, round(h * w / layer["width"])))
        project.limits.size(w, h)
        layer.update(width=w, height=h, auto_size=False)
    elif kind == "rotate":
        layer["rotation"] = finite(op["value"], "angle") % 360
    elif kind == "flip":
        require(op["direction"] in ("horizontal", "vertical"), "Flip must be horizontal or vertical")
        key = "flip_x" if op["direction"] == "horizontal" else "flip_y"
        layer[key] = not layer[key]
    elif kind == "crop":
        require(layer["type"] == "raster", "Crop applies to raster layers")
        x, y, w, h = (int(op[k]) for k in ("x", "y", "width", "height"))
        project.limits.size(w, h)
        source = project.image(layer["asset"])
        require(
            x >= 0 and y >= 0 and x + w <= source.width and y + h <= source.height,
            "Crop exceeds source bounds",
        )
        layer.update(crop=[x, y, x + w, y + h], width=w, height=h)
    elif kind == "opacity":
        layer["opacity"] = finite(op["value"], "opacity", 0, 1)
    elif kind == "blend":
        require(op["value"] in BLENDS, "Unknown blend mode")
        layer["blend"] = op["value"]
    elif kind in ("hide", "show"):
        layer["visible"] = kind == "show"
    elif kind in ("raise", "lower", "top", "bottom", "reorder"):
        siblings = [item for item in layers if item.get("parent") == layer.get("parent")]
        index = siblings.index(layer)
        if kind == "reorder":
            other = project.layer(op.get("above", op.get("below")))
            require(
                other != layer and other.get("parent") == layer.get("parent"),
                "Reorder requires another layer in the same group",
            )
            layers.remove(layer)
            dest = layers.index(other) + (1 if "above" in op else 0)
        else:
            target_index = {
                "raise": min(index + 1, len(siblings) - 1),
                "lower": max(index - 1, 0),
                "top": len(siblings) - 1,
                "bottom": 0,
            }[kind]
            other = siblings[target_index]
            if other == layer:
                return
            layers.remove(layer)
            dest = layers.index(other) + (1 if target_index > index else 0)
        layers.insert(dest, layer)
    elif kind == "align":
        from .design import selected, union_bounds

        targets = selected(project, op.get("targets", [layer["id"]]))
        layout = resolve_layout(project)
        ref = op.get("relative_to", "selection" if "targets" in op else "canvas")
        if ref == "selection":
            box = union_bounds([layout[item["id"]] for item in targets])
        elif ref == "canvas":
            parent = targets[0].get("parent")
            c = project.layer(parent) if parent else project.state["canvas"]
            box = (0, 0, c.get("content_width", c["width"]), c.get("content_height", c["height"]))
        else:
            other = project.layer(ref)
            require(other.get("parent") == targets[0].get("parent"), "Alignment targets must share a parent")
            box = layout[other["id"]]
        margin = finite(op.get("margin", 0), "margin", 0)
        alignment = op["alignment"]
        for item in targets:
            x, y, w, h = layout[item["id"]]
            bx, by, bw, bh = box
            if "left" in alignment:
                x = bx + margin
            if "right" in alignment:
                x = bx + bw - w - margin
            if "top" in alignment:
                y = by + margin
            if "bottom" in alignment:
                y = by + bh - h - margin
            if alignment in ("center", "center-x"):
                x = bx + (bw - w) / 2
            if alignment in ("center", "center-y"):
                y = by + (bh - h) / 2
            item.update(x=x, y=y, constraints={})
    elif kind == "constrain":
        constraints = op["constraints"]
        require(isinstance(constraints, dict), "Constraints must be an object")
        for anchor, expression in constraints.items():
            require(
                anchor in ("left", "right", "top", "bottom", "center-x", "center-y"),
                "Unknown constraint anchor",
            )
            if isinstance(expression, str):
                match = re.fullmatch(
                    r"(.+)\.(left|right|top|bottom|center-x|center-y)([+-]\d+(?:\.\d+)?)?", expression
                )
                require(match, "Invalid constraint expression")
                if match[1] != "canvas" and not match[1].startswith("guide:"):
                    expression = project.layer(match[1])["id"] + "." + match[2] + (match[3] or "")
            layer["constraints"][anchor] = expression
        for axes in (("left", "right", "center-x"), ("top", "bottom", "center-y")):
            require(sum(x in layer["constraints"] for x in axes) <= 1, "Use one constraint per axis")
    elif kind == "unconstrain":
        b = resolve_layout(project)[layer["id"]]
        layer.update(x=b[0], y=b[1], constraints={})
    elif kind == "mask":
        action = op.get("action", "create")
        b = resolve_layout(project)[layer["id"]]
        if action in ("create", "from-selection", "import"):
            if action == "create":
                mask = Image.new("L", tuple(b[2:]), 255)
            elif action == "from-selection":
                mask = selection_image(project).crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
            else:
                mask = decode(read_bounded(op["path"], project.limits.max_asset_bytes), project.limits, "L")
            layer["mask"] = {"asset": add_image(project, mask, "masks"), "enabled": True}
        elif action == "delete":
            layer["mask"] = None
        else:
            require(layer["mask"], "Layer has no mask")
            if action in ("enable", "disable"):
                layer["mask"]["enabled"] = action == "enable"
            elif action == "invert":
                layer["mask"]["asset"] = add_image(
                    project, ImageOps.invert(project.image(layer["mask"]["asset"], "L")), "masks"
                )
            else:
                raise VixlError("invalid_mask", f"Unknown mask action: {action}")
    elif kind in ("effect", *EFFECTS):
        name = op["name"] if kind == "effect" else kind
        require(len(layer["effects"]) < 256, "Effect limit reached", "resource_limit")
        effect = {
            "id": uid("fx"),
            "name": name,
            "amount": op.get("amount", op.get("value", 0)),
            "enabled": True,
            "selection": project.state["selection"],
        }
        for key in ("seed", "radius", "strength", "black", "white", "points"):
            if key in op:
                effect[key] = op[key]
        effect_valid(effect)
        if name not in EFFECTS:
            from .plugins import filter_plugin

            filter_plugin(name)
        layer["effects"].append(effect)
    elif kind.startswith("effect-"):
        ref = op["effect"]
        if isinstance(ref, int) or str(ref).isdigit():
            index = int(ref) - 1
            require(0 <= index < len(layer["effects"]), "Effect index out of range (starts at 1)")
            effect = layer["effects"][index]
        else:
            effect = next((x for x in layer["effects"] if x["id"] == ref), None)
            require(effect, "Effect not found")
        if kind == "effect-remove":
            layer["effects"].remove(effect)
        elif kind in ("effect-enable", "effect-disable"):
            effect["enabled"] = kind == "effect-enable"
        elif kind == "effect-set":
            if "value" in op and "amount" not in op:
                op["amount"] = op["value"]
            for key in ("amount", "seed", "radius", "strength", "black", "white", "points"):
                if key in op:
                    effect[key] = op[key]
            effect_valid(effect)
        else:
            raise VixlError("unknown_operation", f"Unknown operation: {kind}")
    elif kind == "rasterize":
        require(
            not layer.get("styles") and not layer.get("clip"),
            "Remove layer styles/clipping before rasterizing",
        )
        b = resolve_layout(project)[layer["id"]]
        image = layer_image(project, layer, b)
        layer.update(
            type="raster",
            asset=add_image(project, image),
            width=image.width,
            height=image.height,
            x=b[0],
            y=b[1],
            rotation=0,
            flip_x=False,
            flip_y=False,
            effects=[],
            mask=None,
            opacity=1,
            constraints={},
            provenance={"type": "rasterized", "original": deepcopy(layer)},
        )
        if layer["provenance"]["original"]["type"] == "group":
            from .design import descendants

            removed = descendants(project, layer["id"])
            layers[:] = [item for item in layers if item["id"] not in removed]
        for key in ("text", "font", "size", "auto_size", "crop", "linked", "repeat", "lookup"):
            layer.pop(key, None)
    elif kind == "preset-save":
        project.state["presets"][op["name"]] = deepcopy(layer["effects"])
    elif kind == "preset-apply":
        require(op["name"] in project.state["presets"], "Preset not found")
        for item in project.state["presets"][op["name"]]:
            item = deepcopy(item)
            item["id"] = uid("fx")
            item["selection"] = project.state["selection"]
            if item["name"] in op.get("overrides", {}):
                item["amount"] = float(op["overrides"][item["name"]])
            effect_valid(item)
            layer["effects"].append(item)
        require(len(layer["effects"]) <= 256, "Effect limit reached", "resource_limit")
    else:
        raise VixlError("unknown_operation", f"Unknown operation: {kind}")
