"""Read-only rendered-image measurements for humans and agents."""

import numpy as np
from PIL import Image

from .errors import require
from .render import color, resolve_layout


def luminance(rgb):
    a = np.asarray(rgb, dtype=float) / 255
    linear = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def measure(
    project,
    *,
    point=None,
    region=None,
    foreground=None,
    target=None,
    artboard=None,
    comp=None,
    variables=None,
    background="white",
    histogram="full",
):
    from .design_render import artboard_project

    candidate = artboard_project(project.clone(), artboard, comp, variables)
    image = candidate.render()
    result = {"width": image.width, "height": image.height}
    if point is not None:
        require(len(point) == 2 and all(isinstance(v, int) for v in point), "Point requires integer X Y")
        x, y = point
        require(0 <= x < image.width and 0 <= y < image.height, "Point outside canvas")
        rgba = image.getpixel((x, y))
        result["sample"] = {
            "point": list(point),
            "rgba": list(rgba),
            "hex": "#" + "".join(f"{v:02x}" for v in rgba),
        }
    target_image = None
    coverage = None
    if target:
        layer = candidate.layer(target)
        b = resolve_layout(candidate)[layer["id"]]
        region = list(b)
        from .render import layer_canvas_surface, resolved_layers

        effective = next(item for item in resolved_layers(candidate) if item["id"] == layer["id"])
        require(
            layer["visible"] and layer["type"] != "adjustment", "Contrast target must be visible and drawable"
        )
        if layer.get("parent"):
            coverage = layer_canvas_surface(candidate, effective).getchannel("A")
            box = coverage.getbbox()
            require(box is not None, "Target has no visible content")
            region = [box[0], box[1], box[2] - box[0], box[3] - box[1]]
        # Exclude overlays above the target at every level of the group tree,
        # retaining the ancestors and siblings below it as the actual backdrop.
        branch = layer
        while branch:
            position = candidate.state["layers"].index(branch)
            for other in candidate.state["layers"][position + 1:]:
                if other.get("parent") == branch.get("parent"):
                    other["visible"] = False
            branch = candidate.layer(branch["parent"]) if branch.get("parent") else None
        layer["visible"] = False
        image = candidate.render()
        if foreground is None:
            layer["visible"] = True
            target_image = candidate.render()
            from .render import layer_image

            if coverage is None:
                tile = layer_image(candidate, effective, b)
                coverage = Image.new("L", image.size)
                coverage.paste(tile.getchannel("A"), b[:2])
    if region is not None:
        require(
            len(region) == 4 and all(isinstance(v, int) for v in region),
            "Region requires integer X Y WIDTH HEIGHT",
        )
        x, y, w, h = region
        require(
            w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= image.width and y + h <= image.height,
            "Region must be within canvas",
        )
        image = image.crop((x, y, x + w, y + h))
        if target_image is not None:
            target_image = target_image.crop((x, y, x + w, y + h))
        if coverage is not None:
            coverage = coverage.crop((x, y, x + w, y + h))
    pixels = np.asarray(image)
    alpha = pixels[:, :, 3].astype(float) / 255
    total = alpha.sum()
    average = (pixels[:, :, :3] * alpha[:, :, None]).sum(axis=(0, 1)) / total if total else np.zeros(3)
    result["region"] = list(region) if region is not None else [0, 0, image.width, image.height]
    result["average"] = {
        "rgb": [round(v, 3) for v in average.tolist()],
        "alpha": round(float(alpha.mean()), 6),
    }
    visible = pixels[alpha > 0]
    require(histogram in ("full", "summary", "none"), "histogram must be full, summary or none", field="histogram")
    channels = ("red", "green", "blue", "alpha")
    if histogram == "full":
        result["histogram"] = {
            channel: np.bincount(visible[:, i], minlength=256).tolist() for i, channel in enumerate(channels)
        }
    elif histogram == "summary" and len(visible):
        # Percentiles describe tone and range in a few numbers instead of 1,024 bins.
        result["channels"] = {
            channel: dict(
                zip(
                    ("min", "p5", "median", "p95", "max"),
                    (int(v) for v in np.percentile(visible[:, i], (0, 5, 50, 95, 100))),
                ),
                mean=round(float(visible[:, i].mean()), 2),
            )
            for i, channel in enumerate(channels)
        }
    result["visible_pixels"] = len(visible)
    if foreground or target_image is not None:
        from .design import resolve_color

        backdrop = Image.new("RGBA", image.size, color(background))
        require(backdrop.getpixel((0, 0))[3] == 255, "Contrast background must be opaque")
        backdrop.alpha_composite(image)
        bg = np.asarray(backdrop)[:, :, :3].astype(float)
        if target_image is not None:
            painted_image = Image.new("RGBA", image.size, color(background))
            painted_image.alpha_composite(target_image)
            painted = np.asarray(painted_image)[:, :, :3].astype(float)
        else:
            fg = color(resolve_color(foreground, candidate.state))
            painted = np.array(fg[:3]) * (fg[3] / 255) + bg * (1 - fg[3] / 255)
        a, b = luminance(painted), luminance(bg)
        ratios = (np.maximum(a, b) + 0.05) / (np.minimum(a, b) + 0.05)
        if coverage is not None:
            mask = np.asarray(coverage)
            require(mask.max() > 0, "Target has no visible content")
            # Exclude antialiased fringe pixels; compare the actual styled/transparent layer against its backdrop.
            ratios = ratios[mask >= mask.max() * 0.95]
        result["contrast"] = {
            "minimum": round(float(ratios.min()), 3),
            "p10": round(float(np.percentile(ratios, 10)), 3),
            "mean": round(float(ratios.mean()), 3),
            "maximum": round(float(ratios.max()), 3),
            "background": background,
            "wcag_aa_normal": bool(ratios.min() >= 4.5),
            "wcag_aa_large": bool(ratios.min() >= 3),
        }
    return result
