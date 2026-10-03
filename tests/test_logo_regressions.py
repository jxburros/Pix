"""Visual and persistence regressions found during the four-logo CLI workflow."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image
import pytest
import resvg_py

from vixl import Project


def svg_image(project):
    data = project.export(format="SVG")
    return Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=data.decode()))).convert(
        "RGBA"
    ), ET.fromstring(data)


def overlap(first, second):
    a, b = np.asarray(first)[:, :, 3] > 128, np.asarray(second)[:, :, 3] > 128
    return (a & b).sum() / (a | b).sum()


@pytest.mark.parametrize("angle", [30, 90, 135, 270, 330])
@pytest.mark.parametrize("flip", [None, "horizontal", "vertical"])
def test_native_svg_rotations_match_png(angle, flip):
    p = Project(400, 400)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "rectangle",
                "width": 70,
                "height": 250,
                "x": 106,
                "y": 65,
                "fill": "#10b4a0",
            },
            {"type": "rotate", "value": angle},
        ]
    )
    if flip:
        p.apply({"type": "flip", "direction": flip})
    image, root = svg_image(p)
    assert not root.findall(".//{*}image")
    assert overlap(p.render(), image) > 0.97


def test_group_resize_opacity_clipping_and_wordmark_stay_vector():
    p = Project(500, 400)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "rectangle",
                "name": "first",
                "width": 50,
                "height": 150,
                "x": 100,
                "y": 50,
                "fill": "teal",
            },
            {"type": "rotate", "target": "first", "value": 30},
            {
                "type": "shape",
                "shape": "ellipse",
                "name": "second",
                "width": 90,
                "height": 90,
                "x": 180,
                "y": 70,
                "fill": "purple",
            },
            {"type": "group", "name": "mark", "targets": ["first", "second"]},
            {"type": "resize", "target": "mark", "width": 250, "height": 180},
            {"type": "opacity", "target": "mark", "value": 0.5},
            {
                "type": "text",
                "name": "wordmark",
                "text": "vixl AV",
                "size": 64,
                "x": 100,
                "y": 260,
                "color": "#222222",
            },
        ]
    )
    image, root = svg_image(p)
    assert root.findall(".//{*}clipPath") and root.findall(".//{*}path")
    assert not root.findall(".//{*}image")
    # Test the wordmark separately because the group's 50% alpha is thresholded.
    a, b = p.render().crop((100, 260, 400, 340)), image.crop((100, 260, 400, 340))
    assert overlap(a, b) > 0.9
    assert abs(image.getpixel((200, 110))[3] - p.render().getpixel((200, 110))[3]) <= 2


@pytest.mark.parametrize("mode", ["union", "subtract", "intersect"])
def test_boolean_logo_geometry_and_gradient_overlay_are_vector(mode):
    p = Project(300, 300)
    p.apply(
        [
            {
                "type": "shape",
                "shape": "ellipse",
                "name": "a",
                "width": 180,
                "height": 180,
                "x": 40,
                "y": 40,
                "fill": "purple",
            },
            {
                "type": "shape",
                "shape": "ellipse",
                "name": "b",
                "width": 120,
                "height": 120,
                "x": 100,
                "y": 70,
                "fill": "purple",
            },
            {"type": "pathfinder", "name": "logo", "targets": ["a", "b"], "mode": mode},
            {
                "type": "layer-style",
                "target": "logo",
                "name": "gradient-overlay",
                "settings": {"start": "#956dff", "end": "#4136db", "direction": "angled", "angle": 35},
            },
        ]
    )
    image, root = svg_image(p)
    assert not root.findall(".//{*}image")
    assert root.findall(".//{*}linearGradient") and root.findall(".//{*}mask")
    assert overlap(p.render(), image) > 0.97
    a, b = np.asarray(p.render()), np.asarray(image)
    interior = (a[:, :, 3] == 255) & (b[:, :, 3] == 255)
    assert np.abs(a[interior, :3].astype(int) - b[interior, :3].astype(int)).mean() < 3


def test_pixel_grid_svg_is_scalable_and_exact_at_integer_scale():
    p = Project(80, 80)
    p.apply(
        [
            {
                "type": "pixel-art",
                "name": "v",
                "rows": ["A..B", ".AB.", ".CC.", "...."],
                "palette": {"A": "lime", "B": "cyan", "C": "teal", ".": "transparent"},
            },
            {"type": "resize", "target": "v", "width": 80, "height": 80},
        ]
    )
    image, root = svg_image(p)
    assert not root.findall(".//{*}image")
    assert image.tobytes() == p.render().tobytes()


def test_hidden_group_styles_do_not_flatten_visible_vectors():
    p = Project(100, 100)
    p.apply(
        [
            {"type": "shape", "shape": "rectangle", "name": "hidden", "width": 10, "height": 10},
            {"type": "layer-style", "target": "hidden", "name": "drop-shadow"},
            {"type": "group", "name": "hidden-group", "targets": ["hidden"]},
            {"type": "hide", "target": "hidden-group"},
            {"type": "shape", "shape": "ellipse", "width": 80, "height": 80, "fill": "red"},
        ]
    )
    _, root = svg_image(p)
    assert not root.findall(".//{*}image")


def test_ligatures_use_shared_outlines_without_raster_fallback():
    p = Project(180, 60)
    p.apply({"type": "text", "text": "office", "size": 32, "color": "red"})
    image, root = svg_image(p)
    assert not root.findall(".//{*}image")
    assert root.findall(".//{*}path")
    assert image.tobytes() == p.render().tobytes()


def test_fonts_compress_but_images_keep_original_bytes(tmp_path):
    font = Path(__import__("vixl").__file__).parent / "data/DejaVuSans.ttf"
    source = tmp_path / "photo.png"
    Image.new("RGBA", (100, 100), "red").save(source)
    p = Project(150, 100)
    p.apply(
        [
            {"type": "text", "name": "label", "text": "Vixl", "font": str(font), "size": 24},
            {"type": "add", "path": str(source), "name": "photo"},
        ]
    )
    path = tmp_path / "logo.vixl"
    p.save(path)
    with zipfile.ZipFile(path) as archive:
        fonts = [i for i in archive.infolist() if i.filename.startswith("fonts/")]
        images = [i for i in archive.infolist() if i.filename.startswith("assets/")]
        assert fonts and all(
            i.compress_type == zipfile.ZIP_DEFLATED and i.compress_size < i.file_size for i in fonts
        )
        assert all(i.compress_type == zipfile.ZIP_STORED for i in images)
        assert archive.read(images[0].filename) == source.read_bytes()
    reopened = Project.load(path)
    assert reopened.render().tobytes() == p.render().tobytes()
    reopened.undo()
    assert not reopened.state["layers"]
    reopened.redo()
    assert reopened.render().tobytes() == p.render().tobytes()


def test_cli_normalization_under_legacy_windows_output_encoding(tmp_path):
    p = Project(400, 400)
    path = tmp_path / "logo.vixl"
    p.save(path)
    operations = {
        "operations": [
            {
                "type": "shape",
                "shape": "rect",
                "name": "Normalized",
                "width": "25%",
                "height": "10%",
                "x": "50%",
                "y": 300,
                "fill": "rgba(255, 100, 0, 0.5)",
            },
            {"type": "opacity", "target": "Normalized", "value": 50},
        ]
    }
    result = subprocess.run(
        [sys.executable, "-m", "vixl", "--json", "-p", str(path), "apply", "-"],
        input=json.dumps(operations).encode(),
        capture_output=True,
        timeout=20,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["normalized"]
    q = Project.load(path)
    assert q.layer("Normalized")["width"] == 100 and q.layer("Normalized")["opacity"] == 0.5


def test_version_and_global_help_do_not_import_image_engine():
    code = (
        "import sys; from vixl.cli import dispatch; dispatch(['--version']); dispatch(['--help']); "
        "assert 'numpy' not in sys.modules; assert 'vixl.project' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=20)
