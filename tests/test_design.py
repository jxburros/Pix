"""Rendering regressions for editable design and template workflows."""

from copy import deepcopy
import io

from PIL import Image
import pytest

from vixl import Project
from vixl.assets import add_image
from vixl.commands import compile_command
from vixl.errors import VixlError
from vixl.interfaces import Session


def shape(p, name, **kwargs):
    p.apply({"type": "shape", "shape": "rectangle", "name": name, "width": 20, "height": 20, **kwargs})


def test_group_repeat_clips_stripes_to_sun_and_survives_history(tmp_path):
    p = Project(100, 100)
    shape(p, "sun", shape="ellipse", x=20, y=20, width=60, height=60, fill="orange")
    shape(p, "stripe", width=100, height=2, y=20, fill="red")
    p.apply(
        [
            {"type": "repeat", "target": "stripe", "count": 16, "dy": 4},
            {"type": "group", "name": "stripes", "targets": ["stripe"]},
            {"type": "clip", "target": "stripes", "base": "sun"},
        ]
    )
    actual = p.render()
    assert actual.getpixel((0, 20))[3] == 0
    assert actual.getpixel((50, 40)) == (255, 0, 0, 255)
    assert len(p.state["layers"]) == 3
    p.save(tmp_path / "poster.vixl")
    restored = Project.load(tmp_path / "poster.vixl")
    assert restored.render().tobytes() == actual.tobytes()
    restored.undo()
    assert len(restored.state["layers"]) == 2
    restored.redo()
    assert restored.render().tobytes() == actual.tobytes()


def test_group_composites_opacity_once_and_moves_children():
    p = Project(60, 60)
    shape(p, "a", fill="red", x=10, y=10)
    shape(p, "b", fill="blue", x=20, y=10)
    before = p.render().tobytes()
    p.apply({"type": "group", "name": "g", "targets": ["a", "b"]})
    assert p.render().tobytes() == before
    p.apply({"type": "opacity", "target": "g", "value": 0.5})
    assert p.render().getpixel((25, 15)) == (0, 0, 255, 128)
    p.apply({"type": "move", "target": "g", "x": 20, "y": 30})
    assert p.render().getpixel((35, 35)) == (0, 0, 255, 128)
    assert p.render().getpixel((25, 15))[3] == 0
    p.apply({"type": "hide", "target": "g"})
    assert p.render().getbbox() is None


def test_nested_group_ungroup_and_cycle_rejection():
    p = Project(80, 80)
    shape(p, "a", fill="red", x=20, y=20)
    p.apply(
        [
            {"type": "group", "name": "inner", "targets": ["a"]},
            {"type": "group", "name": "outer", "targets": ["inner"]},
        ]
    )
    before = p.render().tobytes()
    p.apply({"type": "ungroup", "target": "outer"})
    p.apply({"type": "ungroup", "target": "inner"})
    assert p.render().tobytes() == before
    shape(p, "b")
    p.apply({"type": "clip", "target": "a", "base": "b"})
    before = deepcopy(p.state)
    with pytest.raises(VixlError, match="cycle"):
        p.apply({"type": "clip", "target": "b", "base": "a"})
    assert before == p.state


@pytest.mark.parametrize("kind", ["rounded-rectangle", "ellipse", "polygon", "star", "line"])
def test_shapes_remain_procedural_on_resize(kind):
    p = Project(100, 100)
    shape(p, "s", shape=kind, fill="red", stroke="blue", stroke_width=2)
    p.apply({"type": "resize", "target": "s", "width": 80, "height": 70})
    assert p.layer("s")["type"] == "shape"
    assert p.render().getbbox()
    assert p.render().getpixel((99, 99))[3] == 0


def test_layer_styles_shadow_stroke_and_overlays():
    p = Project(70, 70)
    shape(p, "s", x=20, y=20, fill="red")
    p.apply(
        [
            {"type": "layer-style", "name": "drop-shadow", "settings": {"dx": 8, "dy": 8, "blur": 0}},
            {"type": "layer-style", "name": "stroke", "settings": {"color": "blue", "width": 2}},
            {"type": "layer-style", "name": "color-overlay", "settings": {"color": "lime"}},
        ]
    )
    image = p.render()
    assert image.getpixel((45, 45)) == (0, 0, 0, 255)
    assert image.getpixel((19, 25)) == (0, 0, 255, 255)
    assert image.getpixel((25, 25)) == (0, 255, 0, 255)
    p.apply({"type": "layer-style", "name": "color-overlay", "remove": True})
    assert p.render().getpixel((25, 25)) == (255, 0, 0, 255)
    p.apply({"type": "layer-style", "name": "outer-glow", "settings": {"blur": 4}})
    assert p.render().getpixel((15, 25))[3] > 0
    p.apply(
        {"type": "layer-style", "name": "gradient-overlay", "settings": {"start": "white", "end": "black"}}
    )
    assert p.render().getpixel((25, 25))[0] > p.render().getpixel((25, 35))[0]


def test_gradient_stops_radial_angle_and_bad_order():
    p = Project(21, 21)
    stops = [{"offset": 0, "color": "red"}, {"offset": 0.5, "color": "lime"}, {"offset": 1, "color": "blue"}]
    p.apply({"type": "gradient", "direction": "horizontal", "stops": stops})
    assert p.render().getpixel((10, 5)) == (0, 255, 0, 255)
    p.apply({"type": "gradient", "name": "radial", "direction": "radial", "stops": stops})
    assert p.render().getpixel((10, 10)) == (255, 0, 0, 255)
    p.apply({"type": "gradient", "name": "angled", "direction": "angled", "angle": 90, "stops": stops})
    assert p.render().getpixel((10, 0)) == (255, 0, 0, 255)
    with pytest.raises(VixlError):
        p.apply({"type": "gradient", "name": "bad", "stops": stops[::-1]})


def test_align_distribute_guides():
    p = Project(100, 100)
    for name, x, w in [("a", 10, 10), ("b", 25, 20), ("c", 80, 10)]:
        shape(p, name, x=x, width=w)
    p.apply({"type": "distribute", "axis": "horizontal", "targets": ["c", "a", "b"]})
    assert p.layer("b")["x"] == 40
    p.apply({"type": "align", "target": "b", "relative_to": "a", "alignment": "left"})
    assert p.layer("b")["x"] == 10
    p.apply(
        [
            {"type": "guide", "name": "margin", "axis": "x", "position": 15},
            {"type": "constrain", "target": "a", "constraints": {"left": "guide:margin.left+2"}},
        ]
    )
    assert p.inspect("a")["resolved_bounds"][0] == 17
    p.apply({"type": "grid", "name": "layout", "columns": 2, "margin": 10, "gutter": 10})
    assert p.state["guides"]["layout-x2-start"]["position"] == 55


def test_live_swatches_and_text_styles_and_symbols():
    p = Project(200, 100)
    p.apply(
        [
            {"type": "swatch", "name": "brand", "color": "red"},
            {"type": "style-define", "name": "Heading", "settings": {"size": 20, "color": "@brand"}},
            {
                "type": "style-define",
                "name": "Centered",
                "kind": "paragraph",
                "settings": {"align": "center", "spacing": 8},
            },
            {"type": "text", "text": "Hello", "name": "title"},
            {"type": "style-apply", "name": "Heading", "target": "title"},
            {"type": "style-apply", "name": "Centered", "kind": "paragraph", "target": "title"},
        ]
    )
    w = p.inspect("title")["resolved_bounds"][2]
    p.apply({"type": "style-define", "name": "Heading", "settings": {"size": 40, "color": "@brand"}})
    assert p.inspect("title")["resolved_bounds"][2] > w
    shape(p, "master", fill="@brand", y=70)
    p.apply(
        [
            {"type": "symbol", "name": "logo", "target": "master"},
            {"type": "symbol-instance", "symbol": "logo", "name": "copy", "x": 60, "y": 70},
        ]
    )
    assert p.render().getpixel((65, 75)) == (255, 0, 0, 255)
    p.apply({"type": "swatch", "name": "brand", "color": "blue"})
    assert p.render().getpixel((65, 75)) == (0, 0, 255, 255)


def test_frame_replace_and_data_rows_without_mutation(tmp_path):
    p = Project(20, 20)
    red = add_image(p, Image.new("RGBA", (40, 20), "red"))
    blue = add_image(p, Image.new("RGBA", (20, 40), "blue"))
    p.apply({"type": "frame", "asset": red, "name": "photo", "width": 20, "height": 20, "fit": "fit"})
    assert p.render().getpixel((0, 0))[3] == 0
    p.apply(
        [
            {"type": "replace-contents", "target": "photo", "asset": blue, "fit": "fill"},
            {"type": "variable", "name": "image", "value": red},
            {"type": "replace-contents", "target": "photo", "variable": "image"},
        ]
    )
    before = deepcopy(p.state)
    assert p.render({"image": blue}).getpixel((10, 10)) == (0, 0, 255, 255)
    csv = tmp_path / "rows.csv"
    csv.write_text("image\n" + red + "\n" + blue + "\n")
    result = p.render_data(csv, tmp_path / "out")
    assert len(result) == 2
    assert Image.open(result[1]["output"]).getpixel((10, 10)) == (0, 0, 255, 255)
    assert p.state == before
    with pytest.raises(VixlError):
        p.render_data(csv, tmp_path / "out")


def test_artboards_comps_export_screens(tmp_path):
    p = Project(100, 100)
    shape(p, "logo", fill="red")
    p.apply(
        [
            {"type": "constrain", "target": "logo", "constraints": {"right": "canvas.right"}},
            {"type": "artboard", "name": "square", "width": 50, "height": 50},
            {"type": "artboard", "name": "story", "width": 50, "height": 100},
            {"type": "comp-save", "name": "with-logo"},
            {"type": "hide", "target": "logo"},
            {"type": "comp-save", "name": "without-logo"},
        ]
    )
    before = deepcopy(p.state)
    assert p.render(artboard="square", comp="with-logo").getpixel((40, 10)) == (255, 0, 0, 255)
    assert p.render(artboard="story", comp="without-logo").getbbox() is None
    outputs = p.export_screens(tmp_path / "screens", comp="with-logo")
    assert len(outputs) == 4
    assert Image.open(tmp_path / "screens/story@2x.png").size == (100, 200)
    assert p.state == before


def test_repeat_blend_and_resource_rollback():
    p = Project(50, 30)
    shape(p, "stripe", width=10, height=2, fill="red")
    p.apply({"type": "repeat-blend", "count": 3, "dy": 10, "end": {"height": 4, "fill": "blue"}})
    assert p.render().getpixel((5, 23)) == (0, 0, 255, 255)
    before = deepcopy(p.state)
    with pytest.raises(VixlError):
        p.apply({"type": "repeat", "count": 100000})
    assert p.state == before


def test_adjustments_auto_and_lut():
    p = Project(20, 20)
    shape(p, "base", fill="#406080")
    p.apply({"type": "adjustment", "effects": [{"name": "invert"}]})
    assert p.render().getpixel((5, 5)) == (191, 159, 127, 255)
    shape(p, "top", fill="red", width=5, height=5)
    assert p.render().getpixel((2, 2)) == (255, 0, 0, 255)
    values = [[1 - r, 1 - g, 1 - b] for b in (0, 1) for g in (0, 1) for r in (0, 1)]
    p.apply(
        [
            {"type": "lut", "name": "invert", "size": 2, "values": values},
            {"type": "lookup", "target": "top", "name": "invert"},
        ]
    )
    assert p.render().getpixel((2, 2)) == (0, 255, 255, 255)
    p.apply({"type": "auto-color", "target": "base"})
    assert p.render().size == (20, 20)


@pytest.mark.parametrize(
    "mode, points",
    [("union", (True, True, True)), ("subtract", (True, False, False)), ("intersect", (False, True, False))],
)
def test_pathfinder(mode, points):
    p = Project(80, 40)
    shape(p, "a", x=0, width=30, height=30)
    shape(p, "b", x=20, width=30, height=30)
    p.apply({"type": "pathfinder", "name": "combined", "targets": ["a", "b"], "mode": mode})
    image = p.render()
    assert tuple(image.getpixel((x, 10))[3] > 0 for x in (5, 25, 45)) == points
    p.apply({"type": "resize", "target": "combined", "width": 70, "height": 35})
    assert p.render().getbbox()


@pytest.mark.parametrize("warp", ["none", "arc", "flag", "bulge"])
def test_text_box_fit_warp_and_path(warp):
    p = Project(200, 100)
    p.apply(
        [
            {"type": "text", "text": "A longer headline", "size": 60},
            {"type": "text-layout", "width": 100, "height": 70, "fit": True, "warp": warp},
        ]
    )
    assert p.render().getbbox()[2] <= 100
    p.apply({"type": "text-layout", "path": [[10, 30], [100, 30], [180, 60]], "width": 200, "height": 100})
    assert p.render().getbbox()


def test_measurement_histogram_contrast_and_services(tmp_path):
    p = Project(20, 20, "white")
    shape(p, "s", fill="black", width=10, height=20)
    result = p.measure(point=[2, 2], region=[0, 0, 10, 20], foreground="white")
    assert result["sample"]["rgba"] == [0, 0, 0, 255]
    assert result["average"]["rgb"] == [0, 0, 0]
    assert result["histogram"]["red"][0] == 200
    assert result["contrast"]["minimum"] == 21
    p.save(tmp_path / "p.vixl")
    session = Session(tmp_path / "p.vixl")
    assert session.measure(point=[2, 2])["sample"] == result["sample"]
    session.apply([{"type": "group", "name": "g", "targets": ["s"]}])
    assert Image.open(io.BytesIO(session.render())).getpixel((2, 2)) == (0, 0, 0, 255)
    with pytest.raises(VixlError):
        session.apply([{"type": "frame", "path": "/etc/passwd"}])


@pytest.mark.parametrize(
    "command",
    [
        "shape ellipse --name sun --width 50 --height 50 --fill orange",
        "group stripes a b",
        "clip stripes sun",
        "repeat stripe --count 16 --dy 37 --dh 1",
        'style-define Heading --settings \'{"size":64,"color":"red"}\'',
        "artboard story --preset story",
        "frame --asset assets/photo.png --width 50 --height 50",
        "auto-contrast title",
        "gradient --direction radial --start red --end blue",
        "align title left --relative-to logo",
    ],
)
def test_cli_schemas(command):
    from vixl.schema import validate_operation

    validate_operation(compile_command(command))


def test_duplicate_group_and_reorder_keep_siblings():
    p = Project(100, 100)
    shape(p, "base", fill="red")
    shape(p, "top", fill="blue")
    p.apply(
        [
            {"type": "clip", "target": "top", "base": "base"},
            {"type": "group", "name": "g", "targets": ["base", "top"]},
            {"type": "duplicate", "target": "g", "name": "copy"},
            {"type": "move", "target": "copy", "x": 50},
        ]
    )
    assert p.render().getpixel((55, 10)) == (0, 0, 255, 255)
    p.apply({"type": "top", "target": "base"})
    assert p.render().getpixel((10, 10)) == (255, 0, 0, 255)
    assert p.render().getpixel((55, 10)) == (0, 0, 255, 255)
    p.apply({"type": "remove", "target": "copy"})
    assert p.render().getpixel((55, 10))[3] == 0


def test_bad_repeat_before_group_is_bounded_and_atomic():
    p = Project(10, 10)
    shape(p, "s", width=1, height=1)
    before = deepcopy(p.state)
    with pytest.raises(VixlError):
        p.apply([{"type": "repeat", "count": 1000000000}, {"type": "group", "name": "g", "targets": ["s"]}])
    assert p.state == before


def test_auto_histogram_stretches_range_and_preserves_alpha():
    from vixl.render import apply_effect

    image = Image.new("RGBA", (3, 1))
    image.putdata([(50, 80, 100, 255), (150, 180, 200, 128), (0, 0, 0, 0)])
    result = apply_effect(image, {"name": "auto-tone"})
    assert result.getpixel((0, 0)) == (0, 0, 0, 255)
    assert result.getpixel((1, 0)) == (255, 255, 255, 128)
    assert result.getpixel((2, 0))[3] == 0


def test_cli_render_data_and_artboards(tmp_path, monkeypatch):
    from vixl.cli import dispatch

    monkeypatch.chdir(tmp_path)
    dispatch(["new", "30x30", "-o", "p.vixl"])
    dispatch(["swatch", "brand", "red"])
    dispatch(["shape", "ellipse", "--name", "sun", "--fill", "@brand", "--width", "20", "--height", "20"])
    dispatch(["artboard", "small", "--width", "20", "--height", "20"])
    dispatch(["render", "--out", "small.png", "--artboard", "small"])
    assert Image.open("small.png").size == (20, 20)
    dispatch(["export-screens", "--out", "screens"])
    assert Image.open("screens/small@2x.png").size == (40, 40)
    dispatch(["variable", "set", "label", "Default"])
    dispatch(["text", "add", "${label}", "--size", "10", "--name", "label"])
    (tmp_path / "rows.csv").write_text('label\n"A, B"\nSecond\n')
    result, _ = dispatch(["render", "--data", "rows.csv", "--out", "rows"])
    assert len(result) == 2
    result, _ = dispatch(["sample", "10", "20"])
    assert "sample" in result


def test_csv_failed_row_does_not_publish_partial_output(tmp_path):
    p = Project(20, 20)
    asset = add_image(p, Image.new("RGBA", (10, 10), "red"))
    p.apply(
        [
            {"type": "frame", "asset": asset},
            {"type": "variable", "name": "photo", "value": asset},
            {"type": "replace-contents", "variable": "photo"},
        ]
    )
    (tmp_path / "rows.csv").write_text("photo\n" + asset + "\nmissing.png\n")
    with pytest.raises((VixlError, OSError)):
        p.render_data(tmp_path / "rows.csv", tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("action", ["remove", "content-aware-fill", "select-subject"])
def test_ai_edit_operations_use_provider_and_preserve_selection_boundary(action, monkeypatch):
    from vixl import ai

    calls = []

    class Backend:
        name = "fixture"

        def invoke(self, capability, request):
            calls.append((capability, request))
            return {
                "mask" if capability == "segment" else "image": ai.encoded(
                    Image.new("RGBA", (20, 20), "blue")
                )
            }

    monkeypatch.setattr(ai, "provider", lambda name: Backend())
    p = Project(20, 20, "red")
    p.apply({"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 10, "height": 20})
    result, changed = ai.ai_command(p, "ai", [action])
    assert changed and result
    assert calls[0][0] == ("segment" if action == "select-subject" else "generate")
    if action != "select-subject":
        assert calls[0][1]["mode"] == "inpaint"
        assert p.render().getpixel((2, 2)) == (0, 0, 255, 255)
        assert p.render().getpixel((15, 2)) == (255, 0, 0, 255)


def test_rest_measure_and_artboard_render(tmp_path):
    from fastapi.testclient import TestClient
    from vixl.interfaces import create_app

    p = Project(20, 20, "white")
    p.apply({"type": "artboard", "name": "wide", "width": 40, "height": 20})
    p.save(tmp_path / "p.vixl")
    client = TestClient(create_app(tmp_path / "p.vixl"))
    response = client.post("/measure", json={"point": [1, 1], "foreground": "black"})
    assert response.status_code == 200
    assert response.json()["contrast"]["minimum"] == 21
    response = client.post("/render", json={"artboard": "wide"})
    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).size == (40, 20)


def test_target_contrast_uses_opacity_and_overlay_without_mutation():
    p = Project(40, 40, "white")
    shape(p, "text-surrogate", fill="black")
    assert p.measure(target="text-surrogate")["contrast"]["minimum"] == 21
    p.apply({"type": "opacity", "value": 0.5})
    assert 3.9 < p.measure(target="text-surrogate")["contrast"]["minimum"] < 4.1
    p.apply({"type": "layer-style", "name": "color-overlay", "settings": {"color": "white"}})
    before = deepcopy(p.state)
    assert p.measure(target="text-surrogate")["contrast"]["minimum"] == 1
    assert p.state == before


def test_mcp_design_schema_measurement_and_typed_tools(tmp_path):
    import asyncio
    import jsonschema
    from vixl.interfaces import mcp_server
    from vixl.mcp_tools import preview

    p = Project(30, 30, "white")
    p.apply({"type": "artboard", "name": "wide", "width": 60, "height": 30})
    p.save(tmp_path / "p.vixl")
    session = Session(tmp_path / "p.vixl")
    result = session.apply([{"type": "swatch", "name": "brand", "color": "red"}])
    assert result["changes"]["swatches"]["after"] == {"brand": "red"}
    assert Image.open(io.BytesIO(preview(session, artboard="wide"))).size == (60, 30)

    async def run():
        server = mcp_server(tmp_path / "p.vixl")
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert {
            "vixl_measure",
            "vixl_ai_remove",
            "vixl_ai_content_aware_fill",
            "vixl_ai_select_subject",
        } <= tools.keys()
        schema = tools["vixl_operations_apply"].inputSchema
        for op in [
            {"type": "shape", "shape": "ellipse", "name": "sun"},
            {"type": "group", "targets": ["sun"], "name": "g"},
            {"type": "frame", "asset": "assets/id.png", "fit": "fill"},
            {"type": "replace-contents", "variable": "photo"},
            {"type": "text-layout", "path": [[0, 0], [20, 20]]},
        ]:
            jsonschema.validate({"operations": [op]}, schema)
        for op in [
            {"type": "frame", "path": "/etc/passwd"},
            {"type": "replace-contents", "path": "/etc/passwd"},
            {"type": "shape", "shape": "invalid"},
            {"type": "hide", "width": 10},
            {"type": "move", "x": "hello"},
            {"type": "text-layout", "path": "/etc/passwd"},
        ]:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({"operations": [op]}, schema)
        result = await server.call_tool("vixl_measure", {"point": [1, 1], "foreground": "black"})
        assert result

    asyncio.run(run())
