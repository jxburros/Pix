import asyncio
from copy import deepcopy
import io
import json

import jsonschema
from PIL import Image
import pytest

from vixl import Project
from vixl.errors import VixlError
from vixl.model import Limits
from vixl.animation import animation_bytes


def solid(p, name, x=0, y=0, width=10, height=10):
    p.apply({"type": "solid", "name": name, "x": x, "y": y, "width": width, "height": height})


def sprite():
    p = Project(4, 4)
    p.apply(
        {
            "type": "pixel-art",
            "name": "sprite",
            "rows": ["....", ".rr.", ".rr.", "...."],
            "palette": {".": "transparent", "r": "#ff0000", "b": "#0000ff"},
        }
    )
    return p


def test_spacing_intent_tolerance_unequal_sizes_and_no_mutation():
    p = Project(100, 100)
    solid(p, "header", y=0)
    solid(p, "body", y=20, height=30)
    solid(p, "footer", y=61)
    before = deepcopy(p.manifest())
    result = p.measure_spacing(around="body", before="header", after="footer")
    assert [g["pixels"] for g in result["gaps"]] == [10, 11]
    assert result["passed"] and result["spread"] == 1
    assert not p.measure_spacing(targets=["footer", "body", "header"], tolerance=0)["passed"]
    assert p.measure_spacing(targets=["header", "body"], expected=10, tolerance=0)["passed"]
    assert p.manifest() == before
    with pytest.raises(VixlError):
        p.measure_spacing()
    with pytest.raises(VixlError):
        p.measure_spacing(around="body", before="footer", after="header")


def test_spacing_reports_overlap_not_false_equal_and_parent_scope():
    p = Project(100, 100)
    for name, x in [("a", 0), ("b", 8), ("c", 16)]:
        solid(p, name, x=x)
    result = p.measure_spacing(targets=["a", "b", "c"], axis="horizontal")
    assert result["equal"] and not result["passed"]
    assert all(g["overlap"] for g in result["gaps"])
    p.apply({"type": "group", "name": "g", "targets": ["a", "b", "c"]})
    result = p.measure_spacing(targets=["a", "b"], axis="horizontal")
    assert result["scope"] == p.layer("g")["id"]
    with pytest.raises(VixlError):
        p.measure_spacing(targets=["g", "a"])


def test_spacing_uses_constraints_artboard_and_rejects_hidden():
    p = Project(100, 100)
    solid(p, "a")
    solid(p, "b", y=45)
    solid(p, "c")
    p.apply(
        [
            {"type": "constrain", "target": "c", "constraints": {"bottom": "canvas.bottom"}},
            {"type": "artboard", "name": "short", "width": 100, "height": 80},
        ]
    )
    assert p.measure_spacing(targets=["a", "b", "c"])["passed"]
    assert not p.measure_spacing(targets=["a", "b", "c"], artboard="short")["passed"]
    p.apply({"type": "hide", "target": "b"})
    with pytest.raises(VixlError):
        p.measure_spacing(targets=["a", "b"])


def test_pixel_editing_grid_palette_and_nearest_scale():
    p = sprite()
    p.apply(
        [
            {
                "type": "pixel-draw",
                "target": "sprite",
                "tool": "line",
                "x": 0,
                "y": 0,
                "x2": 3,
                "y2": 3,
                "color": "b",
            },
            {"type": "pixel-draw", "tool": "rect", "x": 0, "y": 3, "width": 4, "height": 1, "color": "r"},
            {"type": "pixel-draw", "tool": "fill", "x": 1, "y": 0, "color": "r"},
        ]
    )
    assert p.inspect_pixels()["rows"] == ["brrr", ".brr", ".rbr", "rrrr"]
    p.apply({"type": "pixel-palette", "colors": {"r": "#00ff00"}})
    assert p.render().getpixel((1, 0)) == (0, 255, 0, 255)
    image = Image.open(io.BytesIO(p.export(scale=8, sampling="nearest")))
    assert image.size == (32, 32)
    assert {image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)} <= {
        (0, 0, 0, 0),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
    }
    assert image.getpixel((7, 7)) == (0, 0, 255, 255)
    p.apply({"type": "resize", "width": 16, "height": 16})
    assert p.inspect_pixels()["width"] == 4  # Grid stays editable independently of display size.
    assert {p.render().getpixel((x, y)) for y in range(4) for x in range(4)} <= {
        (0, 0, 0, 0),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
    }


@pytest.mark.parametrize(
    "op",
    [
        {"type": "pixel-art", "rows": ["..", "."], "palette": {".": "transparent"}},
        {"type": "pixel-art", "rows": ["z"], "palette": {".": "transparent"}},
        {"type": "pixel-art", "width": 1000000000},
        {"type": "pixel-draw", "x": 4, "y": 0, "color": "r"},
        {"type": "pixel-draw", "tool": "rect", "x": 2, "y": 2, "width": 4, "height": 4, "color": "r"},
        {"type": "pixel-draw", "tool": "line", "x": 0, "y": 0, "color": "r"},
        {"type": "pixel-draw", "x": 0, "y": 0, "color": "missing"},
        {"type": "pixel-palette", "colors": {"ab": "red"}},
    ],
)
def test_invalid_pixels_roll_back(op):
    p = sprite()
    before = deepcopy(p.manifest())
    with pytest.raises(VixlError):
        p.apply(op)
    assert p.manifest() == before


def test_animation_capture_edit_apply_reorder_delete_persistence(tmp_path):
    p = sprite()
    original = p.render().tobytes()
    p.apply({"type": "frame-save", "name": "idle", "duration": 120})
    p.apply({"type": "pixel-draw", "x": 0, "y": 0, "color": "b"})
    p.apply({"type": "frame-save", "name": "spark", "duration": 80})
    assert p.render_frame("idle").tobytes() == original
    assert p.render_frame("spark").getpixel((0, 0)) == (0, 0, 255, 255)
    p.apply({"type": "frame-apply", "name": "idle"})
    assert p.render().tobytes() == original
    p.apply({"type": "animation-set", "order": ["spark", "idle"], "loop": 2})
    summary = p.inspect_animation()
    assert summary["total_duration"] == 200 and summary["loop"] == 2
    assert [f["name"] for f in summary["frames"]] == ["spark", "idle"]
    p.save(tmp_path / "sprite.vixl")
    loaded = Project.load(tmp_path / "sprite.vixl")
    assert loaded.render_frame("spark").getpixel((0, 0)) == (0, 0, 255, 255)
    loaded.apply({"type": "frame-delete", "name": "spark"})
    assert len(loaded.inspect_animation()["frames"]) == 1
    loaded.undo()
    assert loaded.inspect_animation() == summary


@pytest.mark.parametrize("format", ["gif", "apng", "sheet"])
def test_animation_exports_timing_transparency_and_metadata(tmp_path, format):
    p = sprite()
    p.apply({"type": "frame-save", "name": "idle", "duration": 120})
    p.apply({"type": "pixel-draw", "x": 0, "y": 0, "color": "b"})
    p.apply({"type": "frame-save", "name": "spark", "duration": 80})
    before = deepcopy(p.manifest())
    path = tmp_path / ("sprite.gif" if format == "gif" else "sprite.png")
    p.export_animation(path, format=format, scale=2, columns=2 if format == "sheet" else None)
    image = Image.open(path)
    if format == "sheet":
        assert image.size == (16, 8)
        metadata = json.loads(path.with_suffix(".json").read_text())
        assert [f["duration"] for f in metadata["frames"]] == [120, 80]
        assert image.getpixel((8, 0)) == (0, 0, 255, 255)
    else:
        assert image.n_frames == 2
        assert image.info["duration"] == 120
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
        image.seek(1)
        assert image.info["duration"] == 80
        assert image.convert("RGBA").getpixel((0, 0)) == (0, 0, 255, 255)
    assert p.manifest() == before
    with pytest.raises(VixlError):
        p.export_animation(path, format=format)


def test_animation_duration_size_limits_and_compact_changes():
    p = sprite()
    result = p.apply({"type": "frame-save", "name": "idle"}, detail="compact")
    assert len(json.dumps(result)) < 1000
    assert "state" not in json.dumps(result["changes"]["animation"])
    for op in (
        {"type": "frame-save", "name": "bad", "duration": 15},
        {"type": "animation-set", "order": ["missing"]},
        {"type": "frame-apply", "name": "missing"},
    ):
        before = deepcopy(p.state)
        with pytest.raises(VixlError):
            p.apply(op)
        assert p.state == before
    p.apply({"type": "canvas", "width": 5, "height": 5})
    with pytest.raises(VixlError, match="same canvas size"):
        p.apply({"type": "frame-save", "name": "bad-size"})
    with pytest.raises(VixlError):
        p.render_frame("idle", scale=1.5)
    p.limits = Limits(max_pixels=32)
    with pytest.raises(VixlError):
        animation_bytes(p, scale=2)


def test_cli_spacing_and_pixel_animation(tmp_path, monkeypatch):
    from vixl.cli import dispatch

    monkeypatch.chdir(tmp_path)
    dispatch(["new", "4x4", "-o", "sprite.vixl"])
    dispatch(["pixel-art", "--name", "sprite", "--width", "4", "--height", "4"])
    dispatch(["pixel-draw", "sprite", "pixel", "0", "0", "--color", "#"])
    dispatch(["frame-save", "idle", "--duration", "100"])
    dispatch(["pixel-draw", "sprite", "pixel", "1", "0", "--color", "#"])
    dispatch(["frame-save", "spark"])
    dispatch(["export-animation", "--out", "sheet.png", "--format", "sheet", "--scale", "2"])
    dispatch(["export", "nearest.png", "--scale", "8", "--sampling", "nearest"])
    assert Image.open("nearest.png").getpixel((15, 7)) == (0, 0, 0, 255)
    result, _ = dispatch(["pixels", "sprite"])
    assert result["rows"][0] == "##.."
    p = Project(100, 100)
    solid(p, "a", y=0)
    solid(p, "b", y=20)
    solid(p, "c", y=50)
    p.save("spacing.vixl")
    result, _ = dispatch(["--project", "spacing.vixl", "spacing", "--targets", "a", "b", "c"])
    assert not result["passed"]
    with pytest.raises(VixlError, match="inconsistent"):
        dispatch(["--project", "spacing.vixl", "spacing", "--targets", "a", "b", "c", "--check"])


def test_mcp_and_rest_pixel_animation_and_spacing(tmp_path):
    from vixl.interfaces import mcp_server, create_app
    from fastapi.testclient import TestClient

    p = sprite()
    p.save(tmp_path / "sprite.vixl")

    async def run():
        server = mcp_server(tmp_path / "sprite.vixl")
        tools = {t.name: t for t in await server.list_tools()}
        schema = tools["vixl_operations_apply"].inputSchema
        jsonschema.validate(
            {
                "operations": [
                    {"type": "frame-save", "name": "idle"},
                    {"type": "pixel-draw", "x": 0, "y": 0, "color": "b"},
                ]
            },
            schema,
        )
        assert {
            "vixl_measure_spacing",
            "vixl_pixels_inspect",
            "vixl_animation_inspect",
            "vixl_export_animation",
            "vixl_animation_preview",
        } <= tools.keys()
        await server.call_tool(
            "vixl_operations_apply", {"operations": [{"type": "frame-save", "name": "idle"}]}
        )
        assert await server.call_tool("vixl_pixels_inspect", {"target": "sprite"})
        assert await server.call_tool("vixl_animation_preview", {"name": "idle"})
        await server.call_tool("vixl_export_animation", {"path": "sprite.gif"})
        from mcp.server.fastmcp.exceptions import ToolError

        with pytest.raises(ToolError, match="outside the workspace"):
            await server.call_tool("vixl_export_animation", {"path": "../outside.gif"})

    asyncio.run(run())
    assert (tmp_path / "sprite.gif").exists()
    client = TestClient(create_app(tmp_path / "sprite.vixl"))
    assert client.get("/pixels/sprite").json()["rows"][0] == "...."
    assert client.get("/animation").json()["frames"][0]["name"] == "idle"
    response = client.get("/animation/frame/idle?scale=2")
    assert Image.open(io.BytesIO(response.content)).size == (8, 8)
