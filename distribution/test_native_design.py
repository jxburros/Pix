"""Repeat logo regressions through the installed, frozen Windows CLI."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image
import resvg_py


def verify(executable, workspace):
    def cli(*args, operations=None):
        result = subprocess.run(
            [*([executable] if isinstance(executable, str) else executable), "--json", *map(str, args)],
            cwd=workspace,
            input=json.dumps(operations).encode() if operations is not None else None,
            capture_output=True,
            timeout=60,
            env={**os.environ, "VIXL_NO_UPDATE": "1", "PYTHONIOENCODING": "cp1252"},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    cli("new", "400x400", "-o", "normalization.vixl")
    result = cli(
        "apply",
        "-",
        operations={
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
        },
    )
    assert result["normalized"]
    cli("new", "400x400", "-o", "rotation.vixl")
    cli(
        "apply",
        "-",
        operations={
            "operations": [
                {
                    "type": "shape",
                    "shape": "rectangle",
                    "name": "bar",
                    "width": 70,
                    "height": 250,
                    "x": 106,
                    "y": 65,
                    "fill": "#10b4a0",
                },
                {"type": "rotate", "target": "bar", "value": 30},
                {"type": "group", "name": "mark", "targets": ["bar"]},
                {"type": "text", "text": "Vixl", "name": "wordmark", "size": 40, "x": 130, "y": 330},
            ]
        },
    )
    cli("export", "logo.svg")
    cli("export", "logo.png")
    svg = (workspace / "logo.svg").read_text(encoding="utf-8")
    assert not ET.fromstring(svg).findall(".//{*}image"), "Frozen fontTools failed to outline wordmark"
    raster = np.asarray(Image.open(workspace / "logo.png"))[:, :, 3] > 128
    image = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg)))
    vector = np.asarray(image)[:, :, 3] > 128
    assert (raster & vector).sum() / (raster | vector).sum() > 0.97
    cli("new", "400x200", "-o", "unicode.vixl")
    cli(
        "apply",
        "-",
        operations={
            "operations": [
                {
                    "type": "text",
                    "name": "label",
                    "text": "Office Café العربية",
                    "size": 28,
                    "color": "#875634",
                    "x": 5,
                    "y": 10,
                },
                {"type": "sepia"},
                {"type": "layer-style", "name": "drop-shadow", "settings": {"blur": 2}},
            ]
        },
    )
    cli("export", "unicode.svg", "--svg-policy", "strict")
    svg = ET.parse(workspace / "unicode.svg")
    assert svg.findall(".//{*}path") and svg.findall(".//{*}filter") and not svg.findall(".//{*}image")
    cli("glass", "4", "--seed", "17")
    cli("export", "glass.png")
    with Image.open(workspace / "glass.png") as image:
        assert image.getbbox() and image.mode == "RGBA"
    cli("effect", "disable", "label", "2")
    cli("ink-blot", "128", "--radius", "2")
    cli("export", "ink.png")
    with Image.open(workspace / "ink.png") as image:
        colors = np.asarray(image)[:, :, :3]
        assert set(np.unique(colors)).issubset({0, 255})


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="vixl-native-design-") as temporary:
        verify(sys.argv[1], Path(temporary))
    print("Frozen Unicode shaping, SVG filters, strict export, glass/ink filters and logo workflow verified")
