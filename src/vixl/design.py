"""Editable design operations. References are immutable IDs; groups use local coordinates."""

from copy import deepcopy
import re

from .errors import require
from .model import new_layer, finite
from .design_schema import SHAPES, STYLES


def named(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[\w-]{1,100}", value),
        "Resource names must use 1–100 letters, numbers, underscores or hyphens",
    )
    return value


def selected(project, targets):
    layers = [project.layer(t) for t in targets]
    require(len({item["id"] for item in layers}) == len(layers), "Duplicate layer references")
    require(len({item.get("parent") for item in layers}) == 1, "Layers must share a parent")
    return layers


def descendants(project, ident):
    result = set()
    pending = [ident]
    while pending:
        parent = pending.pop()
        for layer in project.state["layers"]:
            if layer.get("parent") == parent:
                require(layer["id"] not in result, "Group cycle")
                result.add(layer["id"])
                pending.append(layer["id"])
    return result


def union_bounds(bounds):
    x, y = min(b[0] for b in bounds), min(b[1] for b in bounds)
    return x, y, max(b[0] + b[2] for b in bounds) - x, max(b[1] + b[3] for b in bounds) - y


def execute_design(project, op):
    from .operations import append_layer, execute
    from .render import resolve_layout, CANVAS_PRESETS, color

    kind = op["type"]
    state = project.state
    if kind == "shape":
        c = state["canvas"]
        fields = {
            k: deepcopy(v) for k, v in op.items() if k not in ("type", "target", "name", "width", "height")
        }
        if op["shape"] == "path":
            fields["path_view"] = [op.get("width", c["width"]), op.get("height", c["height"])]
        append_layer(
            project,
            new_layer(
                op.get("name", "shape"),
                "shape",
                op.get("width", c["width"]),
                op.get("height", c["height"]),
                **fields,
            ),
        )
    elif kind == "group":
        children = selected(project, op["targets"])
        bounds = resolve_layout(project)
        x, y, w, h = union_bounds([bounds[item["id"]] for item in children])
        parent = children[0].get("parent")
        group = new_layer(op["name"], "group", w, h, x=x, y=y, parent=parent)
        # Insert at the highest selected slot; child order remains the document order.
        position = max(state["layers"].index(item) for item in children) + 1
        append_layer(project, group)
        state["layers"].remove(group)
        state["layers"].insert(position, group)
        for child in children:
            b = bounds[child["id"]]
            child.update(parent=group["id"], x=b[0] - x, y=b[1] - y, constraints={})
        group["content_width"], group["content_height"] = w, h
    elif kind == "ungroup":
        group = project.layer(op.get("target"))
        require(group["type"] == "group", "Target must be a group")
        require(
            not group["rotation"]
            and group["opacity"] == 1
            and not group["mask"]
            and not group["effects"]
            and not group.get("styles")
            and not group.get("clip")
            and not group.get("repeat")
            and not group["flip_x"]
            and not group["flip_y"]
            and group["blend"] == "normal"
            and group["visible"]
            and (group["width"], group["height"]) == (group["content_width"], group["content_height"]),
            "Reset group transforms, masks and effects before ungrouping",
        )
        all_bounds = resolve_layout(project)
        b = all_bounds[group["id"]]
        children = [item for item in state["layers"] if item.get("parent") == group["id"]]
        index = state["layers"].index(group)
        for child in children:
            require(child.get("clip") != group["id"], "Cannot ungroup referenced clipping base")
            local = all_bounds[child["id"]]
            child.update(parent=group.get("parent"), x=local[0] + b[0], y=local[1] + b[1], constraints={})
            state["layers"].remove(child)
        index = state["layers"].index(group)
        state["layers"][index : index + 1] = children
        state["active_layer"] = children[-1]["id"] if children else None
    elif kind == "clip":
        layer = project.layer(op.get("target"))
        if op.get("release"):
            layer.pop("clip", None)
        else:
            require(op.get("base"), "Clipping requires a base layer")
            base = project.layer(op["base"])
            require(
                base["id"] != layer["id"] and base.get("parent") == layer.get("parent"),
                "Clipping base must be another layer in the same group",
            )
            layer["clip"] = base["id"]
    elif kind == "layer-style":
        styles = project.layer(op.get("target")).setdefault("styles", {})
        if op.get("remove"):
            styles.pop(op["name"], None)
        else:
            settings = deepcopy(op.get("settings", {}))
            validate_style(op["name"], settings, state)
            styles[op["name"]] = settings
    elif kind == "distribute":
        layers = selected(project, op["targets"])
        require(len(layers) >= 3, "Distribute requires at least three layers")
        bounds = resolve_layout(project)
        axis = 0 if op["axis"] == "horizontal" else 1
        layers.sort(key=lambda item: bounds[item["id"]][axis])
        first, last = bounds[layers[0]["id"]], bounds[layers[-1]["id"]]
        gap = op.get(
            "gap",
            (last[axis] + last[axis + 2] - first[axis] - sum(bounds[item["id"]][axis + 2] for item in layers))
            / (len(layers) - 1),
        )
        pos = first[axis]
        for layer in layers:
            b = bounds[layer["id"]]
            layer.update(x=b[0], y=b[1], constraints={})
            layer["x" if axis == 0 else "y"] = pos
            pos += b[axis + 2] + gap
    elif kind == "style-define":
        category = op.get("kind", "character")
        settings = deepcopy(op["settings"])
        validate_text_style(category, settings, state)
        state.setdefault(category + "_styles", {})[named(op["name"])] = settings
    elif kind == "style-apply":
        category = op.get("kind", "character")
        require(op["name"] in state.get(category + "_styles", {}), "Unknown named style")
        layer = project.layer(op.get("target"))
        require(layer["type"] == "text", "Styles require a text layer")
        layer[category + "_style"] = op["name"]
    elif kind == "swatch":
        color(op["color"])
        state.setdefault("swatches", {})[named(op["name"])] = op["color"]
    elif kind == "artboard":
        name = named(op["name"])
        boards = state.setdefault("artboards", {})
        if op.get("delete"):
            require(name in boards, "Unknown artboard")
            del boards[name]
        else:
            board = deepcopy(boards.get(name, state["canvas"]))
            if "preset" in op:
                require(op["preset"] in CANVAS_PRESETS, "Unknown canvas preset")
                board["width"], board["height"] = CANVAS_PRESETS[op["preset"]]
            board.update(
                {k: deepcopy(op[k]) for k in ("width", "height", "background", "variables") if k in op}
            )
            if "targets" in op:
                board["targets"] = [project.layer(t)["id"] for t in op["targets"]]
            project.limits.size(board["width"], board["height"])
            boards[name] = board
    elif kind in ("frame", "replace-contents"):
        if kind == "frame":
            execute(
                project,
                {
                    k: v
                    for k, v in {**op, "type": "add"}.items()
                    if k in ("type", "name", "path", "asset", "x", "y")
                },
            )
            layer = project.layer()
            layer.update(
                type="frame",
                width=op.get("width", layer["width"]),
                height=op.get("height", layer["height"]),
                fit=op.get("fit", "fill"),
            )
        else:
            layer = project.layer(op.get("target"))
            require(layer["type"] in ("raster", "frame"), "Replace Contents requires an image layer")
            if "path" in op:
                from .assets import add_image, decode, read_bounded

                layer["asset"] = add_image(
                    project, decode(read_bounded(op["path"], project.limits.max_asset_bytes), project.limits)
                )
            elif "asset" in op:
                project.image(op["asset"])
                layer["asset"] = op["asset"]
            if "variable" in op:
                layer["asset_variable"] = named(op["variable"])
            elif "asset" in op or "path" in op:
                layer.pop("asset_variable", None)
            if "fit" in op:
                layer["fit"] = op["fit"]
                layer["type"] = "frame"
            layer.pop("linked", None)
            layer.pop("crop", None)
    elif kind in ("repeat", "repeat-blend"):
        layer = project.layer(op.get("target"))
        layer["repeat"] = {k: deepcopy(v) for k, v in op.items() if k not in ("type", "target")}
        validate_design(project, state)
    elif kind == "adjustment":
        c = state["canvas"]
        append_layer(
            project,
            new_layer(
                op.get("name", "adjustment"),
                "adjustment",
                c["width"],
                c["height"],
                effects=deepcopy(op["effects"]),
            ),
        )
    elif kind == "lut":
        size = op["size"]
        require(
            2 <= size <= 33 and len(op["values"]) == size**3, "LUT requires size³ RGB entries (size 2–33)"
        )
        for triplet in op["values"]:
            for value in triplet:
                finite(value, "LUT channel", 0, 1)
        state.setdefault("luts", {})[named(op["name"])] = {"size": size, "values": deepcopy(op["values"])}
    elif kind == "lookup":
        require(op["name"] in state.get("luts", {}), "Unknown LUT")
        project.layer(op.get("target"))["lookup"] = {
            "name": op["name"],
            "amount": finite(op.get("amount", 1), "amount", 0, 1),
        }
    elif kind == "comp-save":
        fields = ("visible", "x", "y", "rotation", "opacity", "blend", "constraints", "styles")
        state.setdefault("comps", {})[named(op["name"])] = {
            item["id"]: {k: deepcopy(item.get(k, {})) for k in fields} for item in state["layers"]
        }
    elif kind == "comp-apply":
        require(op["name"] in state.get("comps", {}), "Unknown layer comp")
        for layer in state["layers"]:
            layer.update(deepcopy(state["comps"][op["name"]].get(layer["id"], {})))
    elif kind == "text-layout":
        layer = project.layer(op.get("target"))
        require(layer["type"] == "text", "Text layout requires a text layer")
        layer["text_layout"] = {k: deepcopy(v) for k, v in op.items() if k not in ("type", "target")}
        if "width" in op or "height" in op:
            layer.update(
                width=op.get("width", layer["width"]),
                height=op.get("height", layer["height"]),
                auto_size=False,
            )
    elif kind == "guide":
        state.setdefault("guides", {})[named(op["name"])] = {"axis": op["axis"], "position": op["position"]}
    elif kind == "grid":
        name = named(op["name"])
        margin, gutter = op.get("margin", 0), op.get("gutter", 0)
        finite(margin, "margin", 0)
        finite(gutter, "gutter", 0)
        guides = state.setdefault("guides", {})
        # Replace old generated guides when changing row/column counts.
        for key in list(guides):
            if guides[key].get("grid") == name:
                del guides[key]
        for axis, key, size in (
            ("x", "columns", state["canvas"]["width"]),
            ("y", "rows", state["canvas"]["height"]),
        ):
            count = op.get(key, 1)
            require(count <= 512, "Grid limit is 512 rows/columns")
            cell = (size - 2 * margin - (count - 1) * gutter) / count
            require(cell > 0, "Grid margins and gutters exceed canvas")
            for i in range(count):
                for edge, offset in (("start", 0), ("end", cell)):
                    guides[f"{name}-{axis}{i + 1}-{edge}"] = {
                        "axis": axis,
                        "position": margin + i * (cell + gutter) + offset,
                        "grid": name,
                    }
        state.setdefault("grids", {})[name] = {k: v for k, v in op.items() if k != "type"}
    elif kind == "pathfinder":
        children = selected(project, op["targets"])
        require(
            all(item["type"] in ("shape", "pathfinder") for item in children),
            "Pathfinder requires shape layers",
        )
        require(
            all(not item.get("repeat") and not item.get("clip") for item in children),
            "Expand repeats/clipping first",
        )
        bounds = resolve_layout(project)
        x, y, w, h = union_bounds([bounds[item["id"]] for item in children])
        operands = deepcopy(children)
        for layer in operands:
            b = bounds[layer["id"]]
            layer.update(x=b[0] - x, y=b[1] - y, constraints={})
        append_layer(
            project,
            new_layer(
                op["name"],
                "pathfinder",
                w,
                h,
                x=x,
                y=y,
                parent=children[0].get("parent"),
                operands=operands,
                mode=op["mode"],
                content_width=w,
                content_height=h,
                fill=children[0].get("fill", "white"),
            ),
        )
        for layer in children:
            layer["visible"] = False
    elif kind == "symbol":
        layer = project.layer(op.get("target"))
        require(
            layer["type"] not in ("group", "adjustment", "symbol"), "Symbol masters must be drawable layers"
        )
        state.setdefault("symbols", {})[named(op["name"])] = layer["id"]
    elif kind == "symbol-instance":
        require(op["symbol"] in state.get("symbols", {}), "Unknown symbol")
        master = project.layer(state["symbols"][op["symbol"]])
        append_layer(
            project,
            new_layer(
                op.get("name", op["symbol"] + "-instance"),
                "symbol",
                op.get("width", master["width"]),
                op.get("height", master["height"]),
                symbol=op["symbol"],
                x=op.get("x", 0),
                y=op.get("y", 0),
            ),
        )
    else:
        return False
    return True


def resolve_color(value, state, variables=None):
    from .render import substitute

    value = substitute(value, {**state["variables"], **(variables or {})})
    if value.startswith("@"):
        require(value[1:] in state.get("swatches", {}), f"Unknown swatch: {value}")
        return state["swatches"][value[1:]]
    return value


def validate_text_style(kind, settings, state):
    from .render import color

    allowed = (
        {"size", "color", "stroke_width", "stroke_color"} if kind == "character" else {"align", "spacing"}
    )
    require(isinstance(settings, dict) and not set(settings) - allowed, "Invalid named text style settings")
    for key in ("color", "stroke_color"):
        if key in settings:
            color(resolve_color(settings[key], state))
    for key, low, high in (("size", 1, 4096), ("stroke_width", 0, 100), ("spacing", 0, 1000)):
        if key in settings:
            finite(settings[key], key, low, high)
            require(isinstance(settings[key], int), f"{key} must be an integer")
    if "align" in settings:
        require(settings["align"] in ("left", "center", "right"), "Invalid paragraph alignment")


def validate_gradient(data, state):
    from .render import color

    stops = data.get("stops")
    if stops is not None:
        require(isinstance(stops, list) and 2 <= len(stops) <= 64, "Gradients require 2–64 stops")
        last = -1
        for stop in stops:
            require(isinstance(stop, dict) and set(stop) == {"offset", "color"}, "Invalid gradient stop")
            finite(stop["offset"], "stop offset", 0, 1)
            require(stop["offset"] > last, "Gradient offsets must strictly increase")
            last = stop["offset"]
            color(resolve_color(stop["color"], state))
    for key in ("start", "end"):
        if key in data:
            color(resolve_color(data[key], state))
    require(
        data.get("direction", "vertical") in ("vertical", "horizontal", "radial", "angled"),
        "Invalid gradient direction",
    )
    finite(data.get("angle", 0), "angle", -36000, 36000)


def validate_style(name, settings, state):
    from .render import color

    require(name in STYLES and isinstance(settings, dict), "Invalid layer style")
    common = {"enabled", "opacity"}
    allowed = {
        "drop-shadow": {"color", "dx", "dy", "blur"},
        "outer-glow": {"color", "blur"},
        "stroke": {"color", "width"},
        "color-overlay": {"color"},
        "gradient-overlay": {"start", "end", "stops", "direction", "angle"},
    }[name] | common
    require(not set(settings) - allowed, f"Invalid {name} settings")
    if "enabled" in settings:
        require(isinstance(settings["enabled"], bool), "Style enabled must be boolean")
    for key, low, high in (
        ("opacity", 0, 1),
        ("blur", 0, 100),
        ("width", 0, 100),
        ("dx", -4096, 4096),
        ("dy", -4096, 4096),
    ):
        if key in settings:
            finite(settings[key], key, low, high)
    if "color" in settings:
        color(resolve_color(settings["color"], state))
    if name == "gradient-overlay":
        validate_gradient(settings, state)


def validate_design(project, state):
    """Validate both live and historical state without trusting archive payloads."""
    from .render import color, EFFECTS
    from .operations import effect_valid
    from .design_render import repeat_items, repeat_bounds

    layers = state["layers"]
    index = {item["id"]: item for item in layers}
    for category in (
        "swatches",
        "character_styles",
        "paragraph_styles",
        "artboards",
        "luts",
        "comps",
        "guides",
        "grids",
        "symbols",
    ):
        require(
            isinstance(state.get(category, {}), dict) and len(state.get(category, {})) <= 1024,
            f"Invalid {category} registry",
        )
    for name, value in state.get("swatches", {}).items():
        named(name)
        color(value)
    for category in ("character", "paragraph"):
        for name, value in state.get(category + "_styles", {}).items():
            named(name)
            validate_text_style(category, value, state)
    for name, board in state.get("artboards", {}).items():
        named(name)
        project.limits.size(board["width"], board["height"])
        color(resolve_color(board["background"], state, board.get("variables")))
        require(isinstance(board.get("variables", {}), dict), "Invalid artboard variables")
        require(all(t in index for t in board.get("targets", [])), "Artboard references missing layers")
    for name, guide in state.get("guides", {}).items():
        named(name)
        require(guide["axis"] in ("x", "y"), "Invalid guide axis")
        finite(guide["position"], "guide position", -1e9, 1e9)
    for name, lut in state.get("luts", {}).items():
        named(name)
        n = lut["size"]
        require(isinstance(n, int) and 2 <= n <= 33 and len(lut["values"]) == n**3, "Invalid LUT size")
        for triplet in lut["values"]:
            require(len(triplet) == 3, "Invalid LUT triplet")
            for value in triplet:
                finite(value, "LUT channel", 0, 1)
    for name, comp in state.get("comps", {}).items():
        named(name)
        require(isinstance(comp, dict) and len(comp) <= project.limits.max_layers, "Invalid layer comp")
        for settings in comp.values():
            require(
                isinstance(settings, dict)
                and not set(settings)
                - {"visible", "x", "y", "rotation", "opacity", "blend", "constraints", "styles"},
                "Invalid comp settings",
            )
    for name, ident in state.get("symbols", {}).items():
        named(name)
        require(
            ident in index and index[ident]["type"] not in ("symbol", "group", "adjustment"),
            "Invalid symbol master",
        )

    def check_layer(layer, depth=0):
        require(depth <= 16, "Design nesting exceeds 16 levels", "resource_limit")
        kind = layer["type"]
        if kind == "shape":
            require(layer["shape"] in SHAPES, "Invalid shape")
            if layer["shape"] == "path":
                from .geometry import parse_path

                parse_path(layer.get("path"))
                project.limits.size(*layer.get("path_view", [layer["width"], layer["height"]]))
            finite(layer.get("radius", 0), "radius", 0, 16384)
            finite(layer.get("stroke_width", 1), "stroke width", 0, 1024)
            sides = layer.get("sides", 5)
            require(isinstance(sides, int) and 3 <= sides <= 128, "Polygons/stars require 3–128 sides")
            finite(layer.get("inner_radius", 0.5), "inner radius", 0.01, 1)
        if kind == "gradient":
            validate_gradient(layer, state)
        if kind == "frame":
            require(layer.get("fit", "fill") in ("fill", "fit"), "Invalid frame fitting")
        if kind == "symbol":
            require(layer["symbol"] in state.get("symbols", {}), "Missing symbol master")
        if kind in ("group", "pathfinder"):
            project.limits.size(layer["content_width"], layer["content_height"])
        if kind == "pathfinder":
            require(layer["mode"] in ("union", "subtract", "intersect"), "Invalid pathfinder mode")
            require(1 <= len(layer["operands"]) <= project.limits.max_layers, "Invalid pathfinder operands")
            for item in layer["operands"]:
                require(item["type"] in ("shape", "pathfinder"), "Invalid pathfinder operand")
                project.limits.size(item["width"], item["height"])
                check_layer(item, depth + 1)
        for category in ("character", "paragraph"):
            if category + "_style" in layer:
                require(
                    layer[category + "_style"] in state.get(category + "_styles", {}),
                    "Missing named text style",
                )
        for key in ("fill", "color", "stroke", "stroke_color"):
            if key in layer:
                color(resolve_color(layer[key], state))
        styles = layer.get("styles", {})
        require(isinstance(styles, dict) and len(styles) <= 5, "Invalid styles")
        for name, value in styles.items():
            validate_style(name, value, state)
        if layer.get("lookup"):
            require(layer["lookup"]["name"] in state.get("luts", {}), "Missing LUT")
            finite(layer["lookup"].get("amount", 1), "LUT amount", 0, 1)
        if layer.get("repeat"):
            r = layer["repeat"]
            require(isinstance(r["count"], int) and 1 <= r["count"] <= 512, "Repeat count must be 1–512")
            for key in ("dx", "dy"):
                finite(r.get(key, 0), key, 0, 16384)
            for key in ("dw", "dh"):
                finite(r.get(key, 0), key, -16384, 16384)
            require(
                not set(r.get("end", {})) - {"width", "height", "fill", "color"}, "Invalid blend endpoint"
            )
            for key, value in r.get("end", {}).items():
                if key in ("fill", "color"):
                    color(value)
                else:
                    finite(value, key, 1, 16384)
            for item, _, _ in repeat_items(layer):
                project.limits.size(item["width"], item["height"])
            project.limits.size(*repeat_bounds(layer))
        if kind == "adjustment":
            require(
                not layer.get("clip") and not layer.get("repeat") and not layer.get("styles"),
                "Adjustment layers use effects, masks, blend and opacity",
            )
            for effect in layer["effects"]:
                require(effect.get("name") in EFFECTS, "Adjustments require built-in effects")
                effect_valid(effect)
        layout = layer.get("text_layout", {})
        if layout:
            require(
                kind == "text" and not set(layout) - {"width", "height", "fit", "warp", "amount", "path"},
                "Invalid text layout",
            )
            require(layout.get("warp", "none") in ("none", "arc", "flag", "bulge"), "Invalid warp")
            finite(layout.get("amount", 0.2), "warp amount", -1, 1)
            if "path" in layout:
                require(2 <= len(layout["path"]) <= 1024, "Invalid text path")
                for point in layout["path"]:
                    require(len(point) == 2, "Invalid path point")
                    for value in point:
                        finite(value, "path coordinate", -16384, 16384)

    for layer in layers:
        check_layer(layer)
        parent = layer.get("parent")
        if parent:
            require(parent in index and index[parent]["type"] == "group", "Missing parent group")
        if layer.get("clip"):
            base = index.get(layer["clip"])
            require(
                base and base.get("parent") == parent and base["type"] != "adjustment",
                "Invalid clipping base",
            )
        for expression in layer["constraints"].values():
            if isinstance(expression, str):
                match = re.fullmatch(
                    r"(.+)\.(left|right|top|bottom|center-x|center-y)([+-]\d+(?:\.\d+)?)?", expression
                )
                if match and match[1] in index:
                    require(
                        index[match[1]].get("parent") == parent, "Constraints must reference sibling layers"
                    )

    # Validate each dependency once; shared clipping bases must not cause exponential traversal.
    children = {}
    for layer in layers:
        if layer.get("parent"):
            children.setdefault(layer["parent"], []).append(layer["id"])
    depths, visiting = {}, set()

    def visit(ident):
        require(ident not in visiting, "Group/clipping cycle")
        if ident in depths:
            return depths[ident]
        require(len(visiting) < 16, "Group/clipping nesting exceeds 16 levels", "resource_limit")
        visiting.add(ident)
        refs = list(children.get(ident, []))
        if index[ident].get("clip"):
            refs.append(index[ident]["clip"])
        depth = 1
        for ref in refs:
            require(ref in index, "Missing clipping reference")
            depth = max(depth, 1 + visit(ref))
        require(depth <= 16, "Group/clipping nesting exceeds 16 levels", "resource_limit")
        visiting.remove(ident)
        depths[ident] = depth
        return depth

    for ident in index:
        visit(ident)
