"""Design self-checks for agents that cannot look at every pixel.

``check_design`` reports only problems, so a passing document costs a few tokens. Checks run on
top-level layers (a group is checked as one unit). Full-canvas layers are treated as background.
"""

import re

import numpy as np

from .errors import require
from .model import finite

CHECKS = ("bounds", "overlap", "contrast", "safe_area", "legibility")
PERCENT = re.compile(r"^(-?\d+(?:\.\d+)?)%$")


def _length(value, base, name):
    if isinstance(value, str):
        match = PERCENT.match(value)
        require(match, f"{name} must be pixels or a percentage like '5%'", field=name)
        return float(match[1]) * base / 100
    return finite(value, name, 0, 1e6)


def _insets(safe_area, width, height):
    if isinstance(safe_area, dict):
        allowed = {"left", "top", "right", "bottom"}
        require(not set(safe_area) - allowed, "safe_area keys are left, top, right, bottom", field="safe_area")
        return tuple(
            _length(safe_area.get(k, 0), width if k in ("left", "right") else height, f"safe_area.{k}")
            for k in ("left", "top", "right", "bottom")
        )
    left = _length(safe_area, width, "safe_area")
    top = _length(safe_area, height, "safe_area")
    return left, top, left, top


def _box(value, width, height, name):
    require(isinstance(value, (list, tuple)) and len(value) == 4, f"{name} must be [x, y, width, height]")
    x, y, w, h = (_length(v, width if i % 2 == 0 else height, name) for i, v in enumerate(value))
    return x, y, w, h


def _intersects(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _contains(outer, inner):
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[0] + outer[2] >= inner[0] + inner[2]
        and outer[1] + outer[3] >= inner[1] + inner[3]
    )


def check_design(
    project,
    *,
    checks=None,
    targets=None,
    safe_area=None,
    avoid=None,
    thumbnail_width=320,
    min_thumbnail_text=10,
    min_contrast=None,
    artboard=None,
    comp=None,
    variables=None,
):
    """Return ``{"passed", "errors", "warnings", "issues", "checked"}`` for the rendered design."""
    from .design_render import artboard_project
    from .render import layer_image, resolve_layout, resolved_layers

    checks = list(checks or CHECKS)
    unknown = sorted(set(checks) - set(CHECKS))
    require(not unknown, f"Unknown check(s) {unknown}; available: {', '.join(CHECKS)}", field="checks")
    candidate = artboard_project(project.clone(), artboard, comp, variables)
    c = candidate.state["canvas"]
    width, height = c["width"], c["height"]
    resolved = {item["id"]: item for item in resolved_layers(candidate)}
    bounds = resolve_layout(candidate, layers=list(resolved.values()))
    layers = [
        item
        for item in candidate.state["layers"]
        if not item.get("parent") and item["visible"] and item["type"] != "adjustment"
    ]
    if targets:
        wanted = {candidate.layer(t)["id"] for t in targets}
        layers = [item for item in layers if item["id"] in wanted]

    def background(item):
        return _contains(bounds[item["id"]], (0, 0, width, height))

    content = [item for item in layers if not background(item)]
    issues = []

    def is_text(item):
        return resolved[item["id"]]["type"] == "text"


    def issue(check, severity, message, layers=(), **extra):
        issues.append(
            {"check": check, "severity": severity, "layers": [x["name"] for x in layers], "message": message, **extra}
        )

    if "bounds" in checks:
        for item in content:
            x, y, w, h = bounds[item["id"]]
            if x >= width or y >= height or x + w <= 0 or y + h <= 0:
                issue("bounds", "error", f"{item['name']!r} is entirely outside the canvas", [item], bounds=[x, y, w, h])
            elif x < 0 or y < 0 or x + w > width or y + h > height:
                severity = "error" if is_text(item) else "warning"
                issue("bounds", severity, f"{item['name']!r} is cut off by the canvas edge", [item], bounds=[x, y, w, h])

    alphas = {}

    def alpha(item):
        if item["id"] not in alphas:
            b = bounds[item["id"]]
            tile = layer_image(candidate, {**resolved[item["id"]], "opacity": 1}, b)
            alphas[item["id"]] = np.asarray(tile.getchannel("A")) > 32
        return alphas[item["id"]]

    if "overlap" in checks:
        for i, first in enumerate(content):
            for second in content[i + 1 :]:
                a, b = bounds[first["id"]], bounds[second["id"]]
                if not _intersects(a, b):
                    continue
                texts = [x for x in (first, second) if is_text(x)]
                if not texts:
                    continue  # Overlapping images and shapes are ordinary composition.
                if len(texts) == 1:
                    other = second if texts[0] is first else first
                    if _contains(bounds[other["id"]], bounds[texts[0]["id"]]):
                        continue  # A label inside its button or panel.
                left, top = max(a[0], b[0]), max(a[1], b[1])
                right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
                ma = alpha(first)[top - a[1] : bottom - a[1], left - a[0] : right - a[0]]
                mb = alpha(second)[top - b[1] : bottom - b[1], left - b[0] : right - b[0]]
                pixels = int(np.logical_and(ma, mb).sum())
                smaller = max(1, min(int(alpha(first).sum()), int(alpha(second).sum())))
                if pixels > 4 and pixels / smaller > 0.005:
                    severity = "error" if len(texts) == 2 else "warning"
                    issue(
                        "overlap",
                        severity,
                        f"{first['name']!r} and {second['name']!r} overlap by {pixels} px "
                        f"({pixels / smaller:.1%} of the smaller layer)",
                        [first, second],
                        region=[left, top, right - left, bottom - top],
                    )

    texts = [item for item in content if is_text(item)]
    if "contrast" in checks:
        from .measure import measure

        for item in texts:
            try:
                result = measure(candidate, target=item["id"])["contrast"]
            except Exception as exc:  # A text layer without visible pixels has no contrast.
                issue("contrast", "warning", f"Could not measure {item['name']!r}: {exc}", [item])
                continue
            large = resolved[item["id"]].get("size", 0) >= 24
            threshold = min_contrast or (3.0 if large else 4.5)
            if result["p10"] < threshold:
                issue(
                    "contrast",
                    "error",
                    f"{item['name']!r} contrast is {result['p10']:.2f}:1 for most glyph pixels "
                    f"(minimum {result['minimum']:.2f}:1); needs {threshold:g}:1",
                    [item],
                    contrast=result["p10"],
                    required=threshold,
                )

    if "safe_area" in checks and (safe_area is not None or avoid):
        if safe_area is not None:
            left, top, right, bottom = _insets(safe_area, width, height)
            safe = (left, top, width - left - right, height - top - bottom)
            for item in content:
                if not _contains(safe, bounds[item["id"]]):
                    issue(
                        "safe_area",
                        "error" if is_text(item) else "warning",
                        f"{item['name']!r} extends outside the safe area",
                        [item],
                        bounds=list(bounds[item["id"]]),
                        safe_area=[round(v, 2) for v in safe],
                    )
        for zone in avoid or []:
            box = _box(zone, width, height, "avoid")
            for item in content:
                if _intersects(box, bounds[item["id"]]):
                    issue(
                        "safe_area",
                        "error",
                        f"{item['name']!r} intrudes on a reserved zone",
                        [item],
                        zone=[round(v, 2) for v in box],
                    )

    if "legibility" in checks:
        finite(thumbnail_width, "thumbnail_width", 16, 16384)
        scale = thumbnail_width / width
        for item in texts:
            size = resolved[item["id"]].get("size", 0)
            if item.get("text_layout", {}).get("fit"):
                lines = max(1, resolved[item["id"]]["text"].count("\n") + 1)
                size = min(size, bounds[item["id"]][3] / lines)
            effective = size * scale
            if effective < min_thumbnail_text:
                issue(
                    "legibility",
                    "warning",
                    f"{item['name']!r} is {effective:.1f} px tall at {thumbnail_width} px wide; "
                    f"aim for at least {min_thumbnail_text} px (font size {size * min_thumbnail_text / effective:.0f}+)",
                    [item],
                    thumbnail_size=round(effective, 2),
                )

    errors = sum(1 for x in issues if x["severity"] == "error")
    return {
        "passed": errors == 0,
        "errors": errors,
        "warnings": len(issues) - errors,
        "issues": issues,
        "checked": {"checks": checks, "layers": len(content), "text_layers": len(texts)},
    }


def compare(project, before="previous", after="head", *, max_width=1024, max_height=1024, mode="side-by-side"):
    """Render two revisions for an at-a-glance review. Returns ``(image, summary)``."""
    from PIL import Image, ImageChops

    from .proxy import render_preview

    require(mode in ("side-by-side", "diff"), "mode must be side-by-side or diff", field="mode")
    left_project, right_project = project.at(before), project.at(after)
    half = max_width // 2 if mode == "side-by-side" else max_width
    left = render_preview(left_project, half, max_height).convert("RGBA")
    right = render_preview(right_project, half, max_height).convert("RGBA")
    if left.size != right.size:
        right = right.resize(left.size, Image.Resampling.LANCZOS) if mode == "diff" else right
    summary = {"before": project.resolve_ref(before), "after": project.resolve_ref(after)}
    if left.size == right.size:
        difference = ImageChops.difference(left, right).convert("L").point(lambda v: 255 if v > 8 else 0)
        box = difference.getbbox()
        changed = int(np.count_nonzero(np.asarray(difference)))
        scale = project.at(after).state["canvas"]["width"] / right.width
        summary.update(
            changed_fraction=round(changed / (right.width * right.height), 4),
            changed_region=[round(v * scale) for v in (box[0], box[1], box[2] - box[0], box[3] - box[1])]
            if box
            else None,
        )
    else:
        difference = None
        summary["changed_region"] = "canvas size changed"
    if mode == "diff" and difference is not None:
        dimmed = Image.blend(Image.new("RGBA", right.size, "black"), right, 0.35)
        highlight = Image.new("RGBA", right.size, (255, 40, 40, 255))
        return Image.composite(highlight, dimmed, difference), summary
    canvas = Image.new("RGBA", (left.width + right.width + 8, max(left.height, right.height)), (128, 128, 128, 255))
    canvas.alpha_composite(left, (0, 0))
    canvas.alpha_composite(right, (left.width + 8, 0))
    return canvas, summary
