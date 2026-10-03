"""Grouped content must remain visible to diagnostics, including transformed text."""

from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from vixl import Project
from vixl.render import layer_canvas_surface, resolved_layers


def logo():
    p = Project(400, 200, "white")
    p.apply([
        {"type": "text", "name": "label", "text": "Vixl", "size": 24, "x": 40, "y": 40, "color": "#eeeeee"},
        {"type": "shape", "name": "mark", "shape": "ellipse", "width": 30, "height": 30, "x": 10, "y": 40},
        {"type": "group", "name": "logo", "targets": ["mark", "label"]},
    ])
    return p


def test_grouped_text_is_counted_checked_and_targetable_without_mutation():
    p = logo()
    before = deepcopy(p.state)
    for target in (None, ["logo"], ["label"]):
        result = p.check(targets=target)
        assert result["checked"]["text_layers"] == 1
        assert not result["passed"]
        assert any(i["check"] == "contrast" and i["layers"] == ["label"] and i["contrast"] < 2 for i in result["issues"])
    assert p.state == before
    root = ET.fromstring(p.export(format="SVG", svg_policy="strict"))
    assert root.findall(".//{*}path") and not root.findall(".//{*}image")


@pytest.mark.parametrize("transform", [
    {"type": "move", "x": 100, "y": 80},
    {"type": "resize", "width": 160, "height": 60},
    {"type": "rotate", "value": 30},
    {"type": "flip", "direction": "horizontal"},
    {"type": "opacity", "value": 0.5},
])
def test_nested_target_coverage_matches_renderer(transform):
    p = Project(400, 200)
    p.apply([
        {"type": "text", "name": "label", "text": "Vixl", "size": 24, "x": 40, "y": 40},
        {"type": "group", "name": "inner", "targets": ["label"]},
        {"type": "group", "name": "outer", "targets": ["inner"]},
        {**transform, "target": "inner"},
        {"type": "resize", "target": "outer", "width": 120, "height": 65},
    ])
    layer = next(x for x in resolved_layers(p) if x["name"] == "label")
    assert layer_canvas_surface(p, layer).tobytes() == p.render().tobytes()


def test_nested_hidden_and_zero_opacity_groups_skip_text():
    p = logo()
    p.apply({"type": "group", "name": "outer", "targets": ["logo"]})
    assert p.check()["checked"]["text_layers"] == 1
    p.apply({"type": "hide", "target": "outer"})
    assert p.check()["checked"]["text_layers"] == 0
    p.apply([{"type": "show", "target": "outer"}, {"type": "opacity", "target": "logo", "value": 0}])
    assert p.check()["checked"]["text_layers"] == 0


def test_group_resize_affects_legibility_and_canvas_bounds():
    p = logo()
    p.apply({"type": "resize", "target": "logo", "width": 20, "height": 6})
    result = p.check(checks=["legibility"])
    assert result["issues"][0]["thumbnail_size"] < 5
    p.apply({"type": "move", "target": "logo", "x": 399, "y": 190})
    issues = p.check(checks=["bounds", "safe_area"], safe_area=10)["issues"]
    assert any(i["check"] == "bounds" and i["layers"] == ["label"] and i["severity"] == "error" for i in issues)
    assert any(i["check"] == "safe_area" and i["layers"] == ["label"] for i in issues)


def test_overlapping_text_in_separate_groups_is_reported():
    p = Project(300, 100)
    p.apply([
        {"type": "text", "name": "a", "text": "Same", "size": 32, "x": 20, "y": 20},
        {"type": "group", "name": "ga", "targets": ["a"]},
        {"type": "text", "name": "b", "text": "Same", "size": 32, "x": 20, "y": 20},
        {"type": "group", "name": "gb", "targets": ["b"]},
    ])
    result = p.check(checks=["overlap"])
    assert not result["passed"]
    assert len(result["issues"]) == 1 and result["issues"][0]["layers"] == ["a", "b"]


def test_group_contrast_uses_siblings_and_ancestors_backdrop():
    p = Project(300, 150, "white")
    p.apply([
        {"type": "shape", "name": "panel", "shape": "rectangle", "width": 150, "height": 80, "x": 20, "y": 20, "fill": "black"},
        {"type": "text", "name": "label", "text": "Vixl", "size": 24, "x": 40, "y": 40, "color": "white"},
        {"type": "group", "name": "inner", "targets": ["panel", "label"]},
        {"type": "group", "name": "outer", "targets": ["inner"]},
        {"type": "solid", "name": "overlay", "color": "red"},
    ])
    result = p.check(checks=["contrast"], targets=["outer"])
    assert result["issues"] == []
    p.apply({"type": "opacity", "target": "outer", "value": 0.1})
    assert not p.check(checks=["contrast"], targets=["outer"])["passed"]


def test_text_clipped_by_group_is_not_silently_clean():
    p = logo()
    p.apply({"type": "move", "target": "label", "x": 500, "y": 10})
    result = p.check()
    assert not result["passed"]
    assert any("clipped by group" in i["message"] for i in result["issues"])
    assert any(i["check"] == "contrast" and i["severity"] == "warning" for i in result["issues"])


def test_grouped_foreground_measurement_crops_coverage():
    from vixl.measure import measure

    result = measure(logo(), target="label", foreground="black", histogram="none")
    assert result["contrast"]["minimum"] == 21


def test_cli_svg_reports_raster_fallbacks(tmp_path, monkeypatch):
    from vixl.cli import dispatch

    monkeypatch.chdir(tmp_path)
    p = logo()
    p.save("logo.vixl")
    result, _ = dispatch(["-p", "logo.vixl", "export", "logo.svg"])
    assert result["svg"] == {"vector_only": True, "raster_fallbacks": []}
    p.apply({"type": "filter", "target": "label", "name": "ink-blot"})
    p.save("logo.vixl")
    result, _ = dispatch(["-p", "logo.vixl", "export", "logo.svg"])
    assert result["svg"]["vector_only"] is False
    assert any(f["layer"] == "label" for f in result["svg"]["raster_fallbacks"])


def test_repeated_group_coverage_and_geometry_limit_are_explicit():
    p = Project(300, 100)
    p.apply([
        {"type": "text", "name": "label", "text": "V", "size": 24, "x": 10, "y": 10},
        {"type": "group", "name": "repeated", "targets": ["label"]},
        {"type": "repeat", "target": "repeated", "count": 3, "dx": 50, "dy": 0},
    ])
    layer = next(x for x in resolved_layers(p) if x["name"] == "label")
    assert layer_canvas_surface(p, layer).tobytes() == p.render().tobytes()
    result = p.check(checks=["bounds"])
    assert any(i["check"] == "coverage" and i["layers"] == ["label"] for i in result["issues"])
