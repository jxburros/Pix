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
            changes[key] = {"before": before.get(key), "after": after.get(key)}
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
    for ident in old.keys() | new.keys():
        if ident not in old:
            layers[ident] = {"added": new[ident]}
        elif ident not in new:
            layers[ident] = {"removed": True, "name": old[ident]["name"]}
        else:
            delta = {
                key: {"before": old[ident].get(key), "after": new[ident].get(key)}
                for key in old[ident].keys() | new[ident].keys()
                if old[ident].get(key) != new[ident].get(key)
            }
            if delta:
                layers[ident] = delta
    if layers:
        changes["layers"] = layers
    if list(old) != list(new):
        changes["layer_order"] = list(new)
    return changes
