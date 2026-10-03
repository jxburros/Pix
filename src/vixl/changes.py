"""Small, stable-ID edit summaries; full snapshots remain an explicit option."""


def compact_changes(before, after):
    changes = {}
    for key in (
        "canvas",
        "selection",
        "variables",
        "active_layer",
        "presets",
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
        if before.get(key) != after.get(key):
            changes[key] = after.get(key)
    if before.get("animation") != after.get("animation"):
        previous = {f["name"]: f for f in before.get("animation", {}).get("frames", [])}
        current = {f["name"]: f for f in after.get("animation", {}).get("frames", [])}
        changes["animation"] = {
            "loop": after.get("animation", {}).get("loop", 0),
            "frames": [{"name": name, "duration": f["duration"]} for name, f in current.items()],
            "changed": [name for name, f in current.items() if previous.get(name) != f],
            "removed": [name for name in previous if name not in current],
        }
    old = {layer["id"]: layer for layer in before["layers"]}
    new = {layer["id"]: layer for layer in after["layers"]}
    layers = {}
    for ident in [*new, *(i for i in old if i not in new)]:
        if ident not in old:
            layers[ident] = {"added": True, **_brief(new[ident])}
        elif ident not in new:
            layers[ident] = {"removed": True, "name": old[ident]["name"]}
        else:
            # New values only: the caller already knows what it changed from.
            delta = {
                ("bounds" if key == "resolved_bounds" else key): new[ident].get(key)
                for key in [*new[ident], *(k for k in old[ident] if k not in new[ident])]
                if old[ident].get(key) != new[ident].get(key)
            }
            if delta:
                layers[ident] = delta
    if layers:
        changes["layers"] = layers
    survivors = [ident for ident in old if ident in new]
    if [ident for ident in new if ident in old] != survivors:
        changes["layer_order"] = list(new)
    return changes


def _brief(layer):
    """One-line description of a layer: identity, kind, geometry and the main content field."""
    result = {"name": layer["name"], "type": layer["type"]}
    if "resolved_bounds" in layer:
        result["bounds"] = list(layer["resolved_bounds"])
    if layer["type"] == "text":
        text = layer.get("text", "")
        result["text"] = text if len(text) <= 80 else text[:77] + "..."
        result["size"] = layer.get("size")
    if layer["type"] == "shape":
        result["shape"] = layer.get("shape")
    for key in ("color", "fill"):
        if key in layer:
            result[key] = layer[key]
    if layer.get("parent"):
        result["parent"] = layer["parent"]
    if not layer.get("visible", True):
        result["visible"] = False
    if layer.get("opacity", 1) != 1:
        result["opacity"] = layer["opacity"]
    if layer.get("blend", "normal") != "normal":
        result["blend"] = layer["blend"]
    if layer.get("rotation"):
        result["rotation"] = layer["rotation"]
    if layer.get("effects"):
        result["effects"] = [effect["name"] for effect in layer["effects"]]
    if layer.get("styles"):
        result["styles"] = sorted(layer["styles"])
    if layer.get("mask"):
        result["mask"] = True
    if layer.get("clip"):
        result["clip"] = layer["clip"]
    if layer.get("constraints"):
        result["constraints"] = layer["constraints"]
    return result


def summarize(project, target=None):
    """Token-light document description for agents (see inspect() for every stored field)."""
    state = project.inspect()
    if target:
        ident = project.layer(target)["id"]
        layer = next(item for item in state["layers"] if item["id"] == ident)
        return {"id": ident, **_brief(layer)}
    canvas = state["canvas"]
    result = {
        "canvas": {"width": canvas["width"], "height": canvas["height"], "background": canvas["background"]},
        "active_layer": state["active_layer"],
        "head": state["head"],
        "layers": [{"id": layer["id"], **_brief(layer)} for layer in state["layers"]],
    }
    for key in ("variables", "swatches", "presets"):
        if state.get(key):
            result[key] = state[key] if key != "presets" else sorted(state[key])
    for key in ("artboards", "comps", "symbols", "guides", "character_styles", "paragraph_styles", "luts"):
        if state.get(key):
            result[key] = sorted(state[key])
    if state.get("selection"):
        result["selection"] = True
    if state.get("animation", {}).get("frames"):
        result["animation_frames"] = [frame["name"] for frame in state["animation"]["frames"]]
    if state["transaction"]:
        result["transaction"] = True
    return result
