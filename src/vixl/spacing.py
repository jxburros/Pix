"""Explicit geometric spacing checks: measure intentions supplied by the caller."""

from .errors import require
from .model import finite
from .render import resolve_layout
from .design import selected
from .design_render import artboard_project


def measure_spacing(
    project,
    *,
    targets=None,
    axis="vertical",
    around=None,
    before=None,
    after=None,
    expected=None,
    tolerance=1,
    artboard=None,
    comp=None,
    variables=None,
):
    require(axis in ("horizontal", "vertical"), "Axis must be horizontal or vertical")
    finite(tolerance, "tolerance", 0, 16384)
    if expected is not None:
        finite(expected, "expected spacing", 0, 1e9)
    candidate = artboard_project(project, artboard, comp, variables)
    if around is not None:
        require(targets is None and before and after, "Use around with before and after, without targets")
        refs = [before, around, after]
    else:
        require(before is None and after is None, "Before/after require around")
        require(
            isinstance(targets, list) and 2 <= len(targets) <= project.limits.max_layers,
            "Provide 2 or more intended spacing targets",
        )
        refs = targets
    layers = selected(candidate, refs)
    require(len(layers) == len(set(item["id"] for item in layers)), "Spacing targets must be distinct")
    require(all(item["visible"] for item in layers), "Spacing targets must be visible")
    bounds = resolve_layout(candidate)
    index = 0 if axis == "horizontal" else 1
    ordered = sorted(layers, key=lambda item: bounds[item["id"]][index])
    require(around is None or ordered == layers, "Before, around, after must follow the requested axis order")
    gaps = []
    for first, second in zip(ordered, ordered[1:]):
        a, b = bounds[first["id"]], bounds[second["id"]]
        gap = b[index] - a[index] - a[index + 2]
        cross = 1 - index
        overlap = max(0, min(a[cross] + a[cross + 2], b[cross] + b[cross + 2]) - max(a[cross], b[cross]))
        gaps.append(
            {
                "from": first["id"],
                "from_name": first["name"],
                "to": second["id"],
                "to_name": second["name"],
                "pixels": gap,
                "overlap": gap < 0,
                "cross_axis_overlap": overlap,
            }
        )
    values = [gap["pixels"] for gap in gaps]
    minimum, maximum = min(values), max(values)
    equal = maximum - minimum <= tolerance
    matches = all(abs(value - expected) <= tolerance for value in values) if expected is not None else None
    return {
        "axis": axis,
        "scope": layers[0].get("parent") or "canvas",
        "gaps": gaps,
        "minimum": minimum,
        "maximum": maximum,
        "spread": maximum - minimum,
        "mean": sum(values) / len(values),
        "tolerance": tolerance,
        "expected": expected,
        "equal": equal if len(values) >= 2 else None,
        "matches_expected": matches,
        "passed": all(value >= 0 for value in values) and (matches if expected is not None else equal),
        "intent": "balanced" if around else "equal-gaps" if expected is None else "expected-gap",
        "bounds_basis": "geometry; excludes shadows and glows",
    }
