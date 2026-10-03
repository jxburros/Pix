"""Independent visual checks for local filters and shared text/strict SVG export."""

import io
import json
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import pytest
import resvg_py

from vixl import Project, VixlError
from vixl.constants import ARTISTIC_DEFAULTS
from vixl.render import apply_effect
from vixl.text import font_data, shape
from vixl.assets import add_image


def sample():
    y, x = np.mgrid[:80, :96]
    a = np.stack([x * 255 // 95, y * 255 // 79, (x * 7 + y * 13) % 256, (x + y) * 255 // 174], axis=-1)
    return Image.fromarray(a.astype(np.uint8))


def svg_image(project, **options):
    svg = project.export(format="SVG", **options)
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg.decode()))).convert(
        "RGBA"
    ), ET.fromstring(svg)


def visual_error(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    # Transparent RGB is immaterial; compare premultiplied appearance.
    a[..., :3] *= a[..., 3:] / 255
    b[..., :3] *= b[..., 3:] / 255
    return np.abs(a - b).mean()


@pytest.mark.parametrize("name", ARTISTIC_DEFAULTS)
def test_artistic_filters_are_visible_repeatable_and_keep_alpha(name):
    original = sample()
    effect = {"name": name, "amount": ARTISTIC_DEFAULTS[name], "seed": 11}
    first, second = apply_effect(original, effect), apply_effect(original, effect)
    assert first.mode == "RGBA" and first.size == original.size
    assert first.tobytes() == second.tobytes()
    assert first.tobytes() != original.tobytes()
    if name not in ("pixelate", "swirl", "ripple", "wave", "glass"):
        assert first.getchannel("A").tobytes() == original.getchannel("A").tobytes()


@pytest.mark.parametrize("name", ["find-edges", "emboss", "charcoal", "photocopy"])
def test_convolution_treatments_do_not_invent_a_border_on_flat_color(name):
    image = Image.new("RGBA", (12, 10), (200, 150, 100, 128))
    result = np.asarray(apply_effect(image, {"name": name, "amount": ARTISTIC_DEFAULTS[name]}))
    assert np.all(result == result[5, 5])


@pytest.mark.parametrize("name", ["glass", "watercolor"])
def test_seed_changes_artwork_and_roundtrips_history(name, tmp_path):
    p = Project(96, 80)
    p.apply({"type": "add", "asset": add_image(p, sample()), "name": "art"})
    p.apply({"type": name, "seed": 11})
    first = p.render().tobytes()
    p.apply({"type": "effect-set", "effect": 1, "seed": 12})
    assert p.render().tobytes() != first
    p.undo()
    assert p.render().tobytes() == first
    path = tmp_path / "filtered.vixl"
    p.save(path)
    assert Project.load(path).render().tobytes() == first
    p.apply({"type": "effect-disable", "effect": 1})
    assert p.render().tobytes() == sample().tobytes()


@pytest.mark.parametrize(
    "op",
    [
        {"type": "sepia", "amount": 101},
        {"type": "oil-paint", "amount": 8},
        {"type": "halftone", "amount": 2.5},
        {"type": "swirl", "radius": 0},
        {"type": "ink-blot", "radius": 500},
        {"type": "glass", "seed": -1},
        {"type": "duotone", "shadow_color": "rgba(0,0,0,0.5)"},
    ],
)
def test_invalid_filter_parameters_are_atomic(op):
    p = Project(96, 80)
    p.apply({"type": "add", "asset": add_image(p, sample())})
    state = json.dumps(p.state, sort_keys=True)
    with pytest.raises(VixlError):
        p.apply(op)
    assert json.dumps(p.state, sort_keys=True) == state


@pytest.mark.parametrize(
    "text", ["office ffi AV", "Café naïve e\u0301", "العربية", "עברית", "Vixl العربية 123", "Hello\nWorld"]
)
def test_unicode_ligatures_and_multiline_text_stay_vector_and_match_png(text):
    p = Project(600, 160)
    p.apply({"type": "text", "text": text, "size": 40, "color": "#ad2344", "x": 10, "y": 10})
    rendered, root = svg_image(p, svg_policy="strict")
    assert root.findall(".//{*}path") and not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 0.2
    if text.startswith("office"):
        glyphs, _ = shape(font_data(p, p.layer()), "office", 40)
        assert len(glyphs) < len("office")


@pytest.mark.parametrize("warp", ["none", "arc", "flag", "bulge"])
def test_shared_fit_wrapping_and_warp_are_outlines(warp):
    p = Project(240, 180)
    p.apply(
        [
            {"type": "text", "text": "Office Café\nA longer headline", "size": 44, "color": "teal"},
            {"type": "text-layout", "width": 190, "height": 130, "fit": True, "warp": warp},
        ]
    )
    rendered, root = svg_image(p, svg_policy="strict")
    assert not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 0.2


def test_shaped_path_text_and_registered_embedded_font(tmp_path):
    import vixl
    from pathlib import Path

    p = Project(300, 120)
    font = Path(vixl.__file__).parent / "data/DejaVuSans.ttf"
    from vixl.fonts import import_font

    import_font(p, font, "brand")
    p.apply(
        [
            {"type": "text", "text": "office Café", "font": "brand", "size": 28, "color": "purple"},
            {"type": "text-layout", "width": 280, "height": 110, "path": [[10, 55], [150, 55], [260, 90]]},
        ]
    )
    path = tmp_path / "text.vixl"
    p.save(path)
    p = Project.load(path)
    rendered, root = svg_image(p, svg_policy="strict")
    assert not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 0.2


@pytest.mark.parametrize(
    "effect",
    [
        {"type": "sepia"},
        {"type": "duotone", "amount": 60},
        {"type": "invert"},
        {"type": "grayscale"},
        {"type": "brightness", "amount": 20},
        {"type": "contrast", "amount": 20},
        {"type": "saturation", "amount": -30},
        {"type": "posterize", "amount": 3},
        {"type": "gamma", "amount": 1.4},
        {"type": "exposure", "amount": 0.5},
        {"type": "threshold", "amount": 128},
        {"type": "solarize"},
        {"type": "blur", "amount": 3},
        {"type": "curves", "points": [[0, 0], [128, 180], [255, 255]]},
    ],
)
def test_native_svg_filters_keep_geometry_and_appearance(effect):
    p = Project(200, 150)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "ellipse",
                "width": 120,
                "height": 100,
                "x": 30,
                "y": 20,
                "fill": "#a37421",
            },
            effect,
        ]
    )
    rendered, root = svg_image(p, svg_policy="strict")
    assert root.findall(".//{*}filter") and not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 2.5


@pytest.mark.parametrize("name", ["drop-shadow", "outer-glow", "stroke", "color-overlay"])
def test_native_layer_styles_and_opacity(name):
    p = Project(240, 180)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "ellipse",
                "width": 100,
                "height": 90,
                "x": 60,
                "y": 40,
                "fill": "#456ab1",
            },
            {"type": "layer-style", "name": name, "settings": {"color": "#a831b4", "opacity": 0.6}},
            {"type": "opacity", "value": 0.5},
        ]
    )
    rendered, root = svg_image(p, svg_policy="strict")
    assert root.findall(".//{*}filter") and not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 2.5


def test_fallback_isolates_styled_layer_and_strict_refuses_before_writing(tmp_path):
    p = Project(200, 160)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "ellipse",
                "name": "ink",
                "width": 60,
                "height": 80,
                "x": 10,
                "y": 20,
                "fill": "teal",
            },
            {"type": "ink-blot"},
            {"type": "layer-style", "name": "drop-shadow"},
            {
                "type": "shape",
                "shape": "rectangle",
                "name": "vector",
                "width": 70,
                "height": 40,
                "x": 100,
                "y": 40,
                "fill": "red",
            },
        ]
    )
    rendered, root = svg_image(p)
    assert len(root.findall(".//{*}image")) == 1 and root.findall(".//{*}g[@data-layer='vector']")
    assert visual_error(p.render(), rendered) < 1
    path = tmp_path / "art.svg"
    path.write_text("existing artwork")
    with pytest.raises(VixlError) as caught:
        p.export(path, svg_policy="strict")
    assert caught.value.code == "svg_raster_required"
    assert caught.value.details["fallbacks"][0]["layer"] == "ink"
    assert caught.value.details["fallbacks"][0]["effects"] == ["ink-blot"]
    assert path.read_text() == "existing artwork"
    p.apply({"type": "effect-disable", "target": "ink", "effect": 1})
    assert not ET.fromstring(p.export(format="SVG", svg_policy="strict")).findall(".//{*}image")


def test_cli_filter_defaults_color_parameters_and_strict_svg(tmp_path, monkeypatch):
    from vixl.cli import dispatch

    monkeypatch.chdir(tmp_path)
    dispatch(["new", "120x100", "-o", "art.vixl"])
    dispatch(["shape", "ellipse", "--width", "80", "--height", "70", "--fill", "purple"])
    dispatch(["sepia"])
    dispatch(["filter", "duotone", "--shadow-color", "#111111", "--highlight-color", "#ffffcc"])
    dispatch(["export", "art.svg", "--svg-policy", "strict"])
    p = Project.load(tmp_path / "art.vixl")
    assert p.layer()["effects"][0]["amount"] == 100
    assert p.layer()["effects"][1]["shadow_color"] == "#111111"
    assert not ET.parse(tmp_path / "art.svg").findall(".//{*}image")


def test_native_adjustment_stack_and_partial_sepia_gradient():
    p = Project(160, 100, "#ffd9bc")
    p.apply(
        [
            {
                "type": "gradient",
                "name": "art",
                "width": 100,
                "height": 70,
                "x": 20,
                "y": 10,
                "start": "#ffeedd",
                "end": "#517ac8",
                "direction": "horizontal",
            },
            {"type": "sepia", "amount": 40},
            {"type": "adjustment", "effects": [{"name": "invert"}, {"name": "sepia"}]},
            {"type": "shape", "shape": "ellipse", "width": 15, "height": 15, "fill": "red", "x": 70, "y": 50},
        ]
    )
    rendered, root = svg_image(p, svg_policy="strict")
    assert not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 2


def test_unsupported_backdrop_reports_the_layer_and_zero_opacity_is_ignored():
    p = Project(100, 80)
    p.apply(
        [
            {"type": "shape", "shape": "rectangle", "name": "base", "width": 70, "height": 50},
            {"type": "adjustment", "name": "paper", "effects": [{"name": "watercolor"}]},
        ]
    )
    with pytest.raises(VixlError) as caught:
        p.export(format="SVG", svg_policy="strict")
    assert caught.value.details["fallbacks"][0]["layer"] == "paper"
    p.apply({"type": "opacity", "target": "paper", "value": 0})
    assert not ET.fromstring(p.export(format="SVG", svg_policy="strict")).findall(".//{*}image")


def test_native_clip_and_style_order_preserve_transparent_edges():
    p = Project(200, 160)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "ellipse",
                "name": "mask",
                "width": 80,
                "height": 90,
                "x": 40,
                "y": 30,
                "fill": "#cc8844",
            },
            {
                "type": "shape",
                "shape": "rectangle",
                "name": "art",
                "width": 120,
                "height": 110,
                "x": 20,
                "y": 10,
                "fill": "#774499",
            },
            {"type": "layer-style", "name": "drop-shadow"},
            {"type": "clip", "base": "mask"},
            {"type": "opacity", "value": 0.5},
        ]
    )
    rendered, root = svg_image(p, svg_policy="strict")
    assert not root.findall(".//{*}image")
    assert visual_error(p.render(), rendered) < 1.5


def test_rest_strict_svg_exports_and_returns_fallback_details(tmp_path):
    from fastapi.testclient import TestClient
    from vixl.interfaces import create_app

    p = Project(100, 80)
    p.apply([{"type": "text", "text": "office Café", "size": 16}, {"type": "sepia"}])
    path = tmp_path / "api.vixl"
    p.save(path)
    client = TestClient(create_app(path))
    result = client.post("/export", json={"format": "SVG", "svg_policy": "strict"})
    assert result.status_code == 200 and not ET.fromstring(result.content).findall(".//{*}image")
    assert client.post("/operations", json={"operations": [{"type": "ink-blot"}]}).status_code == 200
    result = client.post("/export", json={"format": "SVG", "svg_policy": "strict"})
    assert result.status_code == 400
    assert result.json()["error"] == "svg_raster_required"
    assert result.json()["fallbacks"][0]["effects"] == ["ink-blot"]


def test_mcp_strict_svg_and_new_filters_preserve_existing_file(tmp_path):
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError
    from vixl.interfaces import mcp_server

    p = Project(100, 80)
    p.apply({"type": "text", "text": "office Café", "size": 16})
    path = tmp_path / "api.vixl"
    p.save(path)
    server = mcp_server(path, workspace=tmp_path)

    async def run():
        await server.call_tool("vixl_operations_apply", {"operations": [{"type": "sepia"}]})
        await server.call_tool("vixl_export_file", {"path": "art.svg", "svg_policy": "strict"})
        before = (tmp_path / "art.svg").read_bytes()
        assert not ET.fromstring(before).findall(".//{*}image")
        await server.call_tool("vixl_operations_apply", {"operations": [{"type": "ink-blot"}]})
        with pytest.raises(ToolError, match="svg_raster_required"):
            await server.call_tool("vixl_export_file", {"path": "art.svg", "svg_policy": "strict", "overwrite": True})
        assert (tmp_path / "art.svg").read_bytes() == before

    asyncio.run(run())
