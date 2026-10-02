from copy import deepcopy
import io
import zipfile

import numpy as np
from PIL import Image
import pytest

from pix import Project, PixError
from pix.assets import add_image
from pix.model import Limits
from pix.render import composite, BLENDS, EFFECTS
from pix.validation import assert_rule, validate


def solid(project, name="box", color="red", size=(8, 8)):
    project.apply({"type": "solid", "name": name, "color": color, "width": size[0], "height": size[1]})
    return project.layer()["id"]


def test_portable_roundtrip_and_embedded_font(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (8, 8), "red").save(source)
    p = Project(32, 32)
    p.apply(
        [
            {"type": "add", "path": str(source), "name": "photo"},
            {"type": "text", "text": "Pix", "name": "title", "size": 12, "y": 12},
        ]
    )
    expected = p.render().tobytes()
    p.save(tmp_path / "doc.pix")
    source.unlink()
    q = Project.load(tmp_path / "doc.pix")
    assert q.render().tobytes() == expected
    assert q.layer("photo")["provenance"]["original_filename"] == "source.png"
    assert q.state == p.state
    assert q.nodes == p.nodes


def test_atomic_failure_and_dry_run():
    p = Project(32, 32)
    solid(p)
    before = deepcopy(p.manifest())
    with pytest.raises(PixError):
        p.apply([{"type": "move", "x": 9}, {"type": "opacity", "value": 2}])
    assert p.manifest() == before
    result = p.apply([{"type": "move", "x": 12}], dry_run=True)
    assert result["changes"]["layers"]["after"][0]["x"] == 12
    assert p.manifest() == before


def test_history_branches_and_transactions_survive_restart(tmp_path):
    p = Project(32, 32)
    solid(p)
    p.checkpoint("base")
    p.apply({"type": "move", "x": 10})
    p.branch("vivid")
    p.checkout("base")
    p.apply({"type": "move", "x": 20})
    p.branch("muted")
    p.checkout("vivid")
    assert p.layer()["x"] == 10
    p.undo()
    assert p.layer()["x"] == 0
    p.redo()
    assert p.layer()["x"] == 10
    p.begin()
    p.apply({"type": "opacity", "value": 0.5})
    p.save(tmp_path / "history.pix")
    q = Project.load(tmp_path / "history.pix")
    q.rollback()
    assert q.layer()["opacity"] == 1
    q.begin()
    q.apply([{"type": "move", "y": 12}, {"type": "opacity", "value": 0.3}])
    q.commit()
    q.undo()
    assert q.layer()["y"] == 0 and q.layer()["opacity"] == 1
    q.checkout("muted")
    assert q.layer()["x"] == 20
    with pytest.raises(PixError):
        q.undo(999)
    assert q.layer()["x"] == 20


def test_selection_effect_is_local_and_persistent(tmp_path):
    p = Project(10, 10)
    solid(p, size=(10, 10))
    p.apply(
        [
            {"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 5, "height": 10},
            {"type": "invert"},
            {"type": "select", "shape": "none"},
        ]
    )
    image = p.render()
    assert image.getpixel((4, 5)) == (0, 255, 255, 255)
    assert image.getpixel((5, 5)) == (255, 0, 0, 255)
    p.save(tmp_path / "mask.pix")
    assert Project.load(tmp_path / "mask.pix").render().tobytes() == image.tobytes()
    p.apply({"type": "effect-disable", "effect": 1})
    assert p.render().getpixel((4, 5)) == (255, 0, 0, 255)


def test_mask_moves_with_layer_and_toggle():
    p = Project(20, 10)
    solid(p, size=(10, 10))
    p.apply(
        [
            {"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 5, "height": 10},
            {"type": "mask", "action": "from-selection"},
            {"type": "move", "x": 5},
        ]
    )
    assert p.render().getpixel((6, 5))[3] == 255
    assert p.render().getpixel((11, 5))[3] == 0
    p.apply({"type": "mask", "action": "invert"})
    assert p.render().getpixel((6, 5))[3] == 0
    assert p.render().getpixel((11, 5))[3] == 255
    p.apply({"type": "mask", "action": "disable"})
    assert p.render().getpixel((6, 5))[3] == 255


@pytest.mark.parametrize("blend", BLENDS)
def test_blends_preserve_source_over_transparent_background(blend):
    bottom = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    top = Image.new("RGBA", (1, 1), (100, 150, 200, 128))
    assert composite(bottom, top, blend).getpixel((0, 0)) == (100, 150, 200, 128)


@pytest.mark.parametrize(
    "blend,expected",
    [("multiply", (64, 64, 64, 255)), ("screen", (192, 192, 192, 255)), ("difference", (0, 0, 0, 255))],
)
def test_blend_pixels(blend, expected):
    assert (
        composite(
            Image.new("RGBA", (1, 1), (128, 128, 128, 255)),
            Image.new("RGBA", (1, 1), (128, 128, 128, 255)),
            blend,
        ).getpixel((0, 0))
        == expected
    )


def test_constraints_stable_ids_reflow_and_cycle_rejection():
    p = Project(100, 100)
    solid(p, "logo")
    p.apply({"type": "constrain", "constraints": {"right": "canvas.right-10", "top": "canvas.top+10"}})
    assert p.inspect("logo")["resolved_bounds"] == (82, 10, 8, 8)
    solid(p, "label")
    p.apply({"type": "constrain", "constraints": {"top": "logo.bottom+5"}})
    p.apply({"type": "rename", "target": "logo", "name": "brand"})
    p.apply({"type": "canvas", "width": 200, "height": 150})
    assert p.inspect("brand")["resolved_bounds"] == (182, 10, 8, 8)
    assert p.inspect("label")["resolved_bounds"][1] == 23
    before = deepcopy(p.state)
    with pytest.raises(PixError, match="cycle"):
        p.apply({"type": "constrain", "target": "brand", "constraints": {"top": "label.bottom+5"}})
    assert p.state == before


def test_variables_render_without_mutation():
    p = Project(300, 100)
    p.apply(
        [
            {"type": "variable", "name": "title", "value": "A"},
            {"type": "text", "text": "${title}", "size": 30, "name": "title"},
            {"type": "constrain", "constraints": {"right": "canvas.right-10"}},
        ]
    )
    before = deepcopy(p.state)
    first = p.render()
    second = p.render({"title": "Long title"})
    assert first.tobytes() != second.tobytes()
    assert p.state == before
    assert p.inspect("title")["text"] == "${title}"


@pytest.mark.parametrize("effect", EFFECTS)
def test_effects_render_and_disable(effect):
    p = Project(16, 16)
    a = Image.fromarray(np.tile(np.arange(16, dtype=np.uint8) * 16, (16, 1))).convert("RGBA")
    p.apply({"type": "add", "asset": add_image(p, a)})
    amount = {
        "gamma": 1.2,
        "posterize": 4,
        "threshold": 128,
        "noise": 0.1,
        "grain": 0.1,
        "vignette": 0.4,
        "blur": 1,
        "gaussian-blur": 1,
        "exposure": 0.5,
    }.get(effect, 5)
    op = {"type": "effect", "name": effect, "amount": amount}
    if effect == "curves":
        op["points"] = [[0, 0], [128, 180], [255, 255]]
    p.apply(op)
    assert p.render().size == (16, 16)
    assert p.render().tobytes() == p.render().tobytes()
    p.apply({"type": "effect-disable", "effect": 1})
    assert p.render().tobytes() == a.tobytes()


def test_rasterize_preserves_render():
    p = Project(100, 100)
    p.apply(
        [
            {"type": "text", "name": "title", "text": "Pix", "size": 24},
            {"type": "rotate", "value": 15},
            {"type": "opacity", "value": 0.5},
        ]
    )
    before = p.render().tobytes()
    p.apply({"type": "rasterize"})
    assert p.layer()["type"] == "raster"
    assert p.render().tobytes() == before
    p.undo()
    assert p.layer()["type"] == "text"


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "TIFF"])
def test_export_codecs(fmt):
    p = Project(10, 10)
    solid(p)
    data = p.export(format=fmt, scale=2)
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (20, 20)


def test_invalid_numbers_limits_unknown_operations():
    p = Project(10, 10)
    solid(p)
    for op in [
        {"type": "move", "x": float("nan")},
        {"type": "resize", "width": 100000},
        {"type": "gamma", "value": 0},
        {"type": "unknown"},
        {"type": "opacity", "value": -1},
        {"type": "effect", "name": "curves", "points": [[1, 2], [1, 3]]},
    ]:
        with pytest.raises(PixError):
            p.apply(op)
    with pytest.raises(PixError):
        Project(10, 10, limits=Limits(max_pixels=50))


def test_archive_rejects_traversal_tampering_and_bombs(tmp_path):
    p = Project(10, 10)
    p.apply({"type": "add", "asset": add_image(p, Image.new("RGBA", (8, 8), "red"))})
    path = tmp_path / "doc.pix"
    p.save(path)
    with zipfile.ZipFile(path) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    bad = tmp_path / "bad.pix"
    with zipfile.ZipFile(bad, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
        z.writestr("../escape", "x")
    with pytest.raises(PixError):
        Project.load(bad)
    asset = next(n for n in entries if n.startswith("assets/"))
    entries[asset] = b"bad"
    with zipfile.ZipFile(bad, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
    with pytest.raises(PixError, match="checksum"):
        Project.load(bad)
    with pytest.raises(PixError):
        Project.load(path, limits=Limits(max_project_bytes=100))


def test_write_conflict(tmp_path):
    p = Project(10, 10)
    solid(p)
    path = tmp_path / "doc.pix"
    p.save(path)
    q = Project.load(path)
    p.apply({"type": "move", "x": 2})
    p.save()
    q.apply({"type": "move", "x": 3})
    with pytest.raises(PixError, match="changed"):
        q.save()
    assert Project.load(path).layer()["x"] == 2


def test_validation_and_assertions():
    p = Project(10, 10)
    solid(p)
    assert assert_rule(p, "canvas.width == 10")
    assert assert_rule(p, "layer.box.exists")
    assert not assert_rule(p, "layer.missing.exists")
    assert validate(p, "instagram-post")["valid"]
    p.apply({"type": "move", "x": 8})
    assert not validate(p)["valid"]
    with pytest.raises(PixError):
        assert_rule(p, "__import__('os').system('bad')")


def test_preset_and_selection_combinations():
    p = Project(10, 10)
    solid(p)
    p.apply(
        [
            {"type": "contrast", "value": 10},
            {"type": "preset-save", "name": "p"},
            {"type": "effect-remove", "effect": 1},
            {"type": "preset-apply", "name": "p", "overrides": {"contrast": 20}},
        ]
    )
    assert p.layer()["effects"][0]["amount"] == 20
    p.apply(
        [
            {"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 5, "height": 5},
            {"type": "select", "shape": "rect", "x": 5, "y": 5, "width": 5, "height": 5, "mode": "add"},
        ]
    )
    mask = p.image(p.state["selection"], "L")
    assert mask.getpixel((1, 1)) == 255 and mask.getpixel((8, 8)) == 255 and mask.getpixel((1, 8)) == 0


def test_embedded_custom_font_and_color_variables(tmp_path):
    import pix.render

    font = str(__import__("pathlib").Path(pix.render.__file__).parent / "data" / "DejaVuSans.ttf")
    p = Project(120, 80)
    p.apply(
        [
            {"type": "variable", "name": "accent", "value": "#ff0000"},
            {"type": "text", "name": "title", "text": "Pix", "font": font, "size": 24, "color": "${accent}"},
        ]
    )
    assert p.layer()["font"].startswith("fonts/")
    first = p.render().tobytes()
    p.save(tmp_path / "font.pix")
    q = Project.load(tmp_path / "font.pix")
    assert q.render().tobytes() == first
    assert q.render({"accent": "#00ff00"}).tobytes() != first


def test_schema_rejects_unknown_fields_and_nulls_atomically():
    p = Project(20, 20)
    solid(p)
    before = deepcopy(p.state)
    for op in [
        {"type": "move", "xx": 2},
        {"type": "text", "text": None},
        {"type": "variable", "name": "bad", "value": float("inf")},
        {"type": "canvas", "width": True},
    ]:
        with pytest.raises(PixError):
            p.apply(op)
    assert p.state == before
    p.apply({"operation": "set_opacity", "layer": "box", "value": 0.4})
    assert p.layer()["opacity"] == 0.4


def test_canvas_resize_preserves_selection_origin():
    p = Project(10, 10)
    p.apply({"type": "select", "shape": "rect", "x": 1, "y": 1, "width": 3, "height": 3})
    p.apply({"type": "canvas", "width": 20, "height": 20})
    mask = p.image(p.state["selection"], "L")
    assert mask.size == (20, 20) and mask.getpixel((2, 2)) == 255 and mask.getpixel((12, 12)) == 0
