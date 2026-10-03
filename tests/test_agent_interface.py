import asyncio
import base64
import io
import json

from PIL import Image
import numpy as np
import pytest

from vixl import Project, VixlError
from vixl.interfaces import Session, mcp_server
from vixl.proxy import render_preview, scaled_project


def call(server, name, arguments):
    """Call an MCP tool; return (is_error, text, images)."""

    async def run():
        try:
            result = await server.call_tool(name, arguments)
        except Exception as exc:  # FastMCP surfaces tool failures as ToolError
            return True, str(exc), []
        content = result[0] if isinstance(result, tuple) else result
        text = "".join(getattr(item, "text", "") for item in content)
        images = [item for item in content if getattr(item, "type", None) == "image"]
        return False, text, images

    return asyncio.run(run())


def error_payload(text):
    return json.loads(text[text.index("{") :])


# --- normalization -------------------------------------------------------------------------


def test_common_model_guesses_are_normalized_and_reported():
    p = Project(400, 200)
    result = p.apply(
        [
            {"type": "rect", "name": "box", "width": "50%", "height": 40, "color": "rgba(255, 0, 0, 0.5)", "x": "center", "y": "10%"},
            {"type": "text", "name": "title", "text": "Hi", "fontSize": 30, "fill": "white", "x": "center", "y": "center"},
            {"type": "opacity", "layer": "box", "value": 50},
            {"type": "drop_shadow", "target": "title", "offsetX": 3, "radius": 2},
            {"type": "circle", "name": "dot", "width": 20, "height": 20, "fill": "blue"},
            {"type": "shape", "shape": "hexagonal", "name": "hex", "width": 20, "height": 20},
        ]
    )
    box, title = p.layer("box"), p.layer("title")
    assert box["type"] == "shape" and box["shape"] == "rectangle" and box["fill"] == "rgba(255, 0, 0, 0.5)"
    assert box["width"] == 200 and box["x"] == 100 and box["y"] == 20 and box["opacity"] == 0.5
    assert title["size"] == 30 and title["color"] == "white"
    bounds = p.inspect("title")["resolved_bounds"]
    assert abs(bounds[0] + bounds[2] / 2 - 200) <= 1 and abs(bounds[1] + bounds[3] / 2 - 100) <= 1
    assert title["styles"]["drop-shadow"] == {"dx": 3, "blur": 2}
    assert p.layer("dot")["shape"] == "ellipse"
    assert p.layer("hex")["shape"] == "polygon" and p.layer("hex")["sides"] == 6
    notes = " ".join(result["normalized"])
    assert "operations[0]" in notes and "'fontSize' → 'size'" in notes and "percent" in notes
    assert p.render().getpixel((200, 30))[0] > 100  # The CSS rgba() color rendered.


def test_percentages_resolve_against_parent_group():
    p = Project(400, 400)
    p.apply([{"type": "solid", "name": "a", "width": 100, "height": 100, "x": 200, "y": 200}])
    p.apply({"type": "group", "name": "g", "targets": ["a"]})
    p.apply({"type": "move", "target": "a", "x": "50%", "y": 0})
    assert p.layer("a")["x"] == 50  # 50% of the 100 px group, not the 400 px canvas


def test_opacity_is_percent_in_every_interface(tmp_path):
    from vixl.commands import compile_command

    assert compile_command("opacity 40")["value"] == 40.0
    p = Project(8, 8)
    p.apply({"type": "solid", "name": "s"})
    p.apply(compile_command("opacity 40"))
    assert p.layer("s")["opacity"] == 0.4
    with pytest.raises(VixlError):
        p.apply({"type": "opacity", "value": 250})


# --- errors --------------------------------------------------------------------------------


def test_errors_locate_the_operation_and_suggest_fixes():
    p = Project(100, 100)
    p.apply({"type": "solid", "name": "title"})
    with pytest.raises(VixlError) as error:
        p.apply([{"type": "solid", "name": "x"}, {"type": "move", "target": "Title", "x": 1}])
    details = error.value.as_dict()
    assert details["operation_index"] == 1 and details["operation_type"] == "move"
    assert details["suggestions"] == ["title"] and "operations[1] (move)" in details["message"]
    with pytest.raises(VixlError) as error:
        p.apply({"type": "text", "text": "a", "sise": 3})
    assert error.value.details["suggestions"] == {"sise": "size"} and "size" in error.value.details["allowed"]
    with pytest.raises(VixlError) as error:
        p.apply({"type": "blend", "value": "multiplyy"})
    assert error.value.details["suggestions"] == ["multiply"]
    with pytest.raises(VixlError) as error:
        p.apply({"type": "mvoe", "x": 1})
    assert error.value.code == "unknown_operation" and "move" in error.value.details["suggestions"]
    with pytest.raises(VixlError) as error:
        p.apply({"type": "move"})
    assert "at least one of: x, y" in str(error.value)
    with pytest.raises(VixlError) as error:
        p.apply({"type": "layer-style", "target": "title", "name": "drop-shadow", "settings": {"spread": 2}})
    assert "allowed" in error.value.details and "dx" in error.value.details["allowed"]


def test_mcp_errors_are_structured_json(tmp_path):
    server = mcp_server(workspace=tmp_path)
    call(server, "vixl_document_create", {"path": "a.vixl", "width": 64, "height": 64})
    call(server, "vixl_operations_apply", {"operations": [{"type": "solid", "name": "title"}]})
    failed, text, _ = call(server, "vixl_operations_apply", {"operations": [{"type": "move", "target": "TITLE", "x": 2}]})
    assert failed
    payload = error_payload(text)
    assert payload["error"] == "layer_not_found" and payload["suggestions"] == ["title"]
    assert payload["field"] == "target" and payload["operation_index"] == 0
    failed, text, _ = call(server, "vixl_operations_apply", {"operations": [{"type": "text", "text": "a", "font_family": "/etc/passwd"}]})
    assert failed and error_payload(text)["error"] == "forbidden"  # aliases cannot bypass service limits


# --- token diet ------------------------------------------------------------------------------


def test_mcp_responses_are_minified_and_compact(tmp_path):
    server = mcp_server(workspace=tmp_path)
    call(server, "vixl_document_create", {"path": "a.vixl", "width": 200, "height": 100})
    _, text, _ = call(server, "vixl_operations_apply", {"operations": [{"type": "text", "name": "t", "text": "Hello"}]})
    assert ": " not in text and "\n" not in text
    result = json.loads(text)
    (added,) = result["changes"]["layers"].values()
    assert added["added"] and added["name"] == "t" and len(added["bounds"]) == 4
    assert "effects" not in added and "constraints" not in added
    _, text, _ = call(server, "vixl_document_inspect", {})
    summary = json.loads(text)
    assert summary["layers"][0]["text"] == "Hello" and "flip_x" not in summary["layers"][0]
    _, text, _ = call(server, "vixl_measure", {})
    assert "histogram" not in json.loads(text) and "median" in json.loads(text)["channels"]["red"]
    _, text, _ = call(server, "vixl_measure", {"histogram": "full"})
    assert len(json.loads(text)["histogram"]["red"]) == 256


def test_slim_schema_mode_and_schema_lookup(tmp_path):
    async def sizes(server):
        return {t.name: t for t in await server.list_tools()}

    full = asyncio.run(sizes(mcp_server(workspace=tmp_path)))
    slim = asyncio.run(sizes(mcp_server(workspace=tmp_path, schema="slim")))
    assert len(json.dumps(slim["vixl_operations_apply"].inputSchema)) < len(
        json.dumps(full["vixl_operations_apply"].inputSchema)
    ) / 4
    assert "vixl_ai_plan" not in full
    assert "vixl_ai_plan" in asyncio.run(sizes(mcp_server(workspace=tmp_path, planner=True)))
    for tool in full.values():
        assert '"title"' not in json.dumps(tool.inputSchema)
    _, text, _ = call(mcp_server(workspace=tmp_path, schema="slim"), "vixl_operation_schema", {"types": ["shape", "rect_angle"]})
    result = json.loads(text)
    assert "rectangle" in result["shape"]["properties"]["shape"]["enum"]
    assert result["rect_angle"]["error"] == "unknown operation type"


# --- self checks -----------------------------------------------------------------------------


def checked(p, **options):
    return {(i["check"], tuple(i["layers"])): i for i in p.check(**options)["issues"]}


def test_check_reports_overlap_contrast_safe_area_and_legibility():
    p = Project(1280, 720, "#101820")
    p.apply(
        [
            {"type": "solid", "name": "bg", "color": "#101820"},
            {"type": "text", "name": "title", "text": "Headline", "size": 96, "x": 60, "y": 80, "color": "white"},
            {"type": "text", "name": "sub", "text": "subtitle", "size": 48, "x": 70, "y": 150, "color": "#202833"},
            {"type": "text", "name": "tiny", "text": "credits", "size": 14, "x": 1150, "y": 690, "color": "white"},
            {"type": "shape", "shape": "rectangle", "name": "button", "width": 300, "height": 100, "x": 400, "y": 500, "fill": "#ff4040"},
            {"type": "text", "name": "label", "text": "PLAY", "size": 40, "x": 480, "y": 525, "color": "white"},
            {"type": "text", "name": "edge", "text": "cut", "size": 40, "x": 1250, "y": 10, "color": "white"},
        ]
    )
    issues = checked(p, safe_area="5%", avoid=[["85%", "85%", "15%", "15%"]])
    assert issues[("overlap", ("title", "sub"))]["severity"] == "error"
    assert ("overlap", ("button", "label")) not in issues  # label sits inside its button
    assert issues[("contrast", ("sub",))]["contrast"] < 3
    assert ("contrast", ("title",)) not in issues
    assert issues[("bounds", ("edge",))]["severity"] == "error"
    assert ("safe_area", ("tiny",)) in issues
    assert ("legibility", ("tiny",)) in issues
    assert ("bounds", ("bg",)) not in issues  # full-canvas layers are background
    result = p.check(checks=["overlap"], targets=["label", "button"])
    assert result["passed"]


def test_compare_revisions_and_history_refs():
    from vixl.checks import compare

    p = Project(200, 100, "white")
    p.apply({"type": "solid", "name": "box", "width": 20, "height": 20, "color": "black"})
    p.apply({"type": "move", "target": "box", "x": 150, "y": 50})
    assert p.resolve_ref("previous") == p.nodes[p.head]["parent"]
    assert p.at("head~1").layer("box")["x"] == 0
    image, summary = compare(p, "previous", "head", max_width=400, max_height=200)
    assert image.width > 200 and 0 < summary["changed_fraction"] < 0.2
    x, y, w, h = summary["changed_region"]
    assert x <= 2 and x + w >= 168
    diff, _ = compare(p, mode="diff", max_width=200, max_height=100)
    assert diff.getpixel((160, 60))[0] > 200
    with pytest.raises(VixlError):
        p.resolve_ref("head~9")


# --- previews and speed ------------------------------------------------------------------------


def test_proxy_preview_matches_full_render():
    p = Project.load("examples/after-hours.vixl")
    full = p.render()
    full.thumbnail((400, 400))
    quick = render_preview(p, 400, 400)
    assert quick.size == full.size
    difference = np.abs(np.asarray(full, dtype=int) - np.asarray(quick, dtype=int))
    assert difference.mean() < 6


def test_preview_regions_zoom_and_fallback_for_selection_effects():
    p = Project(400, 400, "white")
    p.apply({"type": "solid", "name": "dot", "width": 10, "height": 10, "x": 300, "y": 300, "color": "red"})
    zoom = render_preview(p, 400, 400, region=[295, 295, 20, 20])
    assert zoom.size == (160, 160)  # enlarged at most 8x
    assert zoom.getpixel((80, 80))[:3] == (255, 0, 0)
    p.apply([{"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 50, "height": 50}, {"type": "invert"}])
    assert scaled_project(p, 0.5) is None
    assert render_preview(p, 100, 100).size == (100, 100)


def test_direct_compositing_matches_full_tiles_for_offcanvas_and_blends():
    p = Project(64, 64, "#336699")
    p.apply(
        [
            {"type": "solid", "name": "a", "width": 40, "height": 40, "x": -10, "y": -10, "color": "#ff000080"},
            {"type": "solid", "name": "b", "width": 40, "height": 40, "x": 40, "y": 40, "color": "#00ff00"},
            {"type": "blend", "target": "b", "value": "multiply"},
            {"type": "opacity", "target": "b", "value": 0.5},
        ]
    )
    image = p.render()
    assert image.getpixel((0, 0)) == (153, 25, 76, 255) or abs(image.getpixel((0, 0))[0] - 153) <= 2
    assert image.getpixel((50, 50))[1] > image.getpixel((50, 50))[2]
    assert image.getpixel((35, 35)) == (51, 102, 153, 255)


# --- sessions ------------------------------------------------------------------------------------


def test_several_documents_can_be_open(tmp_path):
    session = Session(workspace=tmp_path)
    session.create("one.vixl", 32, 32)
    session.create("two.vixl", 64, 64)
    session.apply([{"type": "solid", "name": "first"}], document="one.vixl")
    session.apply([{"type": "solid", "name": "second"}])
    assert [x["name"] for x in session.inspect(document="one.vixl")["layers"]] == ["first"]
    assert session.open_documents() == {"active": "two.vixl", "open": ["two.vixl", "one.vixl"]}
    assert [x["name"] for x in Project.load(tmp_path / "two.vixl").state["layers"]] == ["second"]
    session.close("one.vixl")
    assert session.open_documents()["active"] == "two.vixl"
    with pytest.raises(VixlError):
        session.inspect(document="../outside.vixl")


def test_import_image_from_base64_bytes(tmp_path):
    server = mcp_server(workspace=tmp_path)
    call(server, "vixl_document_create", {"path": "a.vixl", "width": 64, "height": 64})
    stream = io.BytesIO()
    Image.new("RGB", (16, 8), "green").save(stream, format="JPEG")
    encoded = base64.b64encode(stream.getvalue()).decode()
    failed, text, _ = call(server, "vixl_import_image", {"data_base64": "data:image/jpeg;base64," + encoded, "name": "pasted"})
    assert not failed
    result = json.loads(text)
    assert result["name"] == "pasted" and (result["width"], result["height"]) == (16, 8)
    assert result["asset"].endswith(".jpg")
    failed, text, _ = call(server, "vixl_import_image", {"data_base64": "not base64!!"})
    assert failed and error_payload(text)["field"] == "data_base64"
    failed, _, _ = call(server, "vixl_import_image", {})
    assert failed


def test_mcp_check_preview_and_compare_tools(tmp_path):
    server = mcp_server(workspace=tmp_path)
    call(server, "vixl_document_create", {"path": "a.vixl", "width": 800, "height": 400, "background": "white"})
    call(server, "vixl_operations_apply", {"operations": [{"type": "text", "name": "t", "text": "Grey", "color": "#eeeeee", "size": 30}]})
    _, text, _ = call(server, "vixl_check", {"checks": ["contrast"]})
    assert not json.loads(text)["passed"]
    failed, _, images = call(server, "vixl_render_preview", {"region": ["0%", "0%", "25%", "25%"], "max_width": 400})
    assert not failed and images
    call(server, "vixl_operations_apply", {"operations": [{"type": "move", "target": "t", "x": 300, "y": 100}]})
    failed, text, images = call(server, "vixl_render_compare", {"mode": "diff"})
    assert not failed and images and json.loads(text)["changed_fraction"] > 0
    _, text, _ = call(server, "vixl_history", {"limit": 1})
    history = json.loads(text)
    assert history["total"] == 3 and history["nodes"][0]["operations"] == ["move"]


def test_blur_radius_is_read_as_amount():
    p = Project(16, 16)
    p.apply({"type": "solid", "name": "s"})
    result = p.apply({"type": "effect", "target": "s", "name": "blur", "radius": 3})
    assert p.layer("s")["effects"][-1]["amount"] == 3 and "radius" in " ".join(result["normalized"])
    p.apply({"type": "gaussian-blur", "target": "s", "radius": 2})
    assert p.layer("s")["effects"][-1]["amount"] == 2
