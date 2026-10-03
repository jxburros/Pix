"""Small, stable-ID edit summaries; full snapshots remain an explicit option."""


def compact_changes(before, after):
    changes = {}
    for key in ("canvas", "selection", "variables", "active_layer", "presets"):
        if before[key] != after[key]:
            changes[key] = {"before": before[key], "after": after[key]}
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
