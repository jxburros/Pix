"""Native SVG equivalents of supported local effects and layer appearances."""

import numpy as np

from .render import color
from .design import resolve_color
from .constants import ARTISTIC_DEFAULTS

NATIVE_EFFECTS = {
    "blur",
    "gaussian-blur",
    "brightness",
    "contrast",
    "saturation",
    "grayscale",
    "invert",
    "sepia",
    "duotone",
    "solarize",
    "posterize",
    "threshold",
    "exposure",
    "gamma",
    "temperature",
    "tint",
    "shadows",
    "highlights",
    "levels",
    "curves",
}


def supported(layer):
    return all(
        e["name"] in NATIVE_EFFECTS and not e.get("selection")
        for e in layer.get("effects", [])
        if e.get("enabled", True)
    )


def native_styles(layer, state):
    active = {k: v for k, v in layer.get("styles", {}).items() if v.get("enabled", True)}
    if set(active) - {"drop-shadow", "outer-glow", "stroke", "color-overlay", "gradient-overlay"}:
        return False
    gradient = active.get("gradient-overlay")
    if gradient:
        values = (
            [s["color"] for s in gradient["stops"]]
            if gradient.get("stops")
            else [gradient.get("start", "black"), gradient.get("end", "white")]
        )
        if gradient.get("opacity", 1) != 1 or any(color(resolve_color(c, state))[3] != 255 for c in values):
            return False
    return True


def effect_filter(exporter, effects, bounds):
    from .svg import node

    ident = exporter.ident("effects")
    x, y, w, h = bounds
    container = node(
        exporter.defs,
        "filter",
        id=ident,
        filterUnits="userSpaceOnUse",
        x=x,
        y=y,
        width=w,
        height=h,
        color_interpolation_filters="sRGB",
    )
    for effect in effects:
        if not effect.get("enabled", True):
            continue
        name, amount = effect["name"], effect.get("amount", ARTISTIC_DEFAULTS.get(effect["name"], 0))
        if name in ("blur", "gaussian-blur"):
            node(container, "feGaussianBlur", stdDeviation=amount)
        elif name in ("saturation", "grayscale", "sepia"):
            if name in ("saturation", "grayscale"):
                # Pillow's luma weights differ slightly from SVG's saturate matrix.
                factor = 0 if name == "grayscale" else max(0, 1 + amount / 100)
                matrix = np.tile([0.299, 0.587, 0.114], (3, 1)) * (1 - factor) + np.eye(3) * factor
            else:
                factor = amount / 100
                previous = exporter.ident("sepia-input")
                node(
                    container,
                    "feColorMatrix",
                    type="matrix",
                    values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0",
                    result=previous,
                )
                matrix = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
            values = [value for row in matrix for value in [*row, 0, 0]] + [0, 0, 0, 1, 0]
            node(container, "feColorMatrix", type="matrix", values=" ".join(map(str, values)))
            if name == "sepia" and amount != 100:
                node(container, "feComposite", in2=previous, operator="arithmetic", k2=factor, k3=1 - factor)
        else:
            # Tables model Pillow's byte-domain adjustments without assuming SVG
            # hueRotate (YIQ) is equivalent to Vixl's HSV hue operation.
            previous = exporter.ident("input")
            # A no-op names the current filter result; SourceAlpha always refers
            # to the original vector silhouette, not this intermediate input.
            node(
                container,
                "feColorMatrix",
                type="matrix",
                values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0",
                result=previous,
            )
            if name in ("threshold", "duotone"):
                node(
                    container,
                    "feColorMatrix",
                    values=".299 .587 .114 0 0 .299 .587 .114 0 0 .299 .587 .114 0 0 0 0 0 1 0",
                )
            transfer = node(container, "feComponentTransfer")
            samples = np.linspace(0, 1, 256)
            for i, channel in enumerate("RGB"):
                t = samples.copy()
                if name == "brightness":
                    t *= max(0, 1 + amount / 100)
                elif name == "contrast":
                    # Contrast uses the rendered visible mean; compute it once
                    # from the pre-effect input at this point in the stack.
                    mean = effect.get("_mean", 0.5)
                    t = (t - mean) * max(0, 1 + amount / 100) + mean
                elif name == "invert":
                    t = 1 - t
                elif name == "solarize":
                    t = np.where(t * 255 >= amount, 1 - t, t)
                elif name == "posterize":
                    t = (np.arange(256) & (256 - (1 << (8 - int(amount))))) / 255
                elif name == "threshold":
                    t = (t * 255 >= amount).astype(float)
                elif name == "duotone":
                    low = color(effect.get("shadow_color", "#172544"))[i] / 255
                    high = color(effect.get("highlight_color", "#ffe6ac"))[i] / 255
                    t = low + (high - low) * t
                elif name == "exposure":
                    t *= 2**amount
                elif name == "gamma":
                    t = t ** (1 / amount)
                elif name == "temperature":
                    t += [amount / 10000, 0, -amount / 10000][i]
                elif name == "tint":
                    t += [amount / 200, -amount / 100, amount / 200][i]
                elif name == "shadows":
                    t += amount / 100 * (1 - t) ** 2
                elif name == "highlights":
                    t += amount / 100 * t**2
                elif name == "levels":
                    t = (t * 255 - effect.get("black", 0)) / (
                        effect.get("white", 255) - effect.get("black", 0)
                    )
                elif name == "curves":
                    t = np.interp(
                        t * 255, [p[0] for p in effect["points"]], [p[1] / 255 for p in effect["points"]]
                    )
                node(
                    transfer,
                    "feFunc" + channel,
                    type="table",
                    tableValues=" ".join(f"{v:.6f}" for v in np.clip(t, 0, 1)),
                )
            if name == "duotone" and amount != 100:
                node(
                    container,
                    "feComposite",
                    in2=previous,
                    operator="arithmetic",
                    k2=amount / 100,
                    k3=1 - amount / 100,
                )
    return f"url(#{ident})"


def style_filter(exporter, layer, bounds):
    from .svg import node

    active = {k: v for k, v in layer.get("styles", {}).items() if v.get("enabled", True)}
    if not active:
        return None
    ident = exporter.ident("styles")
    parent = exporter.index.get(layer.get("parent"))
    w, h = (
        (parent["content_width"], parent["content_height"])
        if parent
        else (exporter.project.state["canvas"]["width"], exporter.project.state["canvas"]["height"])
    )
    container = node(
        exporter.defs,
        "filter",
        id=ident,
        filterUnits="userSpaceOnUse",
        x=0,
        y=0,
        width=w,
        height=h,
        color_interpolation_filters="sRGB",
    )
    merges = []
    for name in ("drop-shadow", "outer-glow", "stroke"):
        settings = active.get(name)
        if not settings:
            continue
        silhouette = exporter.ident("silhouette")
        if name == "stroke":
            radius = round(settings.get("width", 2))
            if not radius:
                continue
            node(container, "feMorphology", **{"in": "SourceAlpha"}, operator="dilate", radius=radius)
            node(container, "feComposite", in2="SourceAlpha", operator="out", result=silhouette)
        else:
            node(
                container,
                "feGaussianBlur",
                **{"in": "SourceAlpha"},
                stdDeviation=settings.get("blur", 8),
                result=silhouette,
            )
        if name == "drop-shadow":
            node(
                container,
                "feOffset",
                **{"in": silhouette},
                dx=round(settings.get("dx", 4)),
                dy=round(settings.get("dy", 4)),
                result=silhouette,
            )
        rgba = color(
            resolve_color(
                settings.get("color", "white" if name == "outer-glow" else "black"), exporter.project.state
            )
        )
        node(
            container,
            "feFlood",
            flood_color=f"rgb{rgba[:3]}",
            flood_opacity=settings.get("opacity", 1) * rgba[3] / 255,
        )
        result = exporter.ident("style")
        node(container, "feComposite", in2=silhouette, operator="in", result=result)
        merges.append(result)
    source = "SourceGraphic"
    overlay = active.get("color-overlay")
    if overlay and "gradient-overlay" not in active:
        rgba = color(resolve_color(overlay.get("color", "white"), exporter.project.state))
        amount = overlay.get("opacity", 1) * rgba[3] / 255
        node(container, "feFlood", flood_color=f"rgb{rgba[:3]}")
        node(container, "feComposite", in2="SourceAlpha", operator="in")
        source = exporter.ident("color-overlay")
        node(
            container,
            "feComposite",
            in2="SourceGraphic",
            operator="arithmetic",
            k2=amount,
            k3=1 - amount,
            result=source,
        )
    merge = node(container, "feMerge")
    for result in [*merges, source]:
        node(merge, "feMergeNode", **{"in": result})
    return f"url(#{ident})"
