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
            [executable, "--json", *map(str, args)],
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


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="vixl-native-design-") as temporary:
        verify(sys.argv[1], Path(temporary))
    print("Frozen normalization, SVG rotation, grouped geometry and wordmark verified")
