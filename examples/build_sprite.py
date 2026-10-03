"""Build a tiny editable animated potion and sprite sheet without external art assets."""

import argparse
from pathlib import Path

from vixl import Project


def build(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    project = Project(12, 12)
    project.apply(
        {
            "type": "pixel-art",
            "name": "potion",
            "palette": {
                ".": "transparent",
                "o": "#25334b",
                "c": "#bb8657",
                "g": "#a5ece4",
                "p": "#a263da",
                "l": "#efb9ff",
                "w": "#ffffff",
            },
            "rows": [
                "............",
                "....oooo....",
                "....occo....",
                "....oggo....",
                "...og..go...",
                "..og....go..",
                "..og.pp.go..",
                "..ogppppgo..",
                "..ogplppgo..",
                "..ogppppgo..",
                "...oooooo...",
                "............",
            ],
        }
    )
    project.apply({"type": "frame-save", "name": "idle", "duration": 250})
    for i, (x, y) in enumerate(((5, 8), (6, 7), (5, 6)), 1):
        project.apply(
            [
                {"type": "frame-apply", "name": "idle"},
                {"type": "pixel-draw", "target": "potion", "x": x, "y": y, "color": "w"},
                {"type": "frame-save", "name": f"bubble-{i}", "duration": 150},
            ]
        )
    project.apply({"type": "frame-apply", "name": "idle"})
    project.save(output / "potion.vixl")
    project.export_animation(output / "potion.gif", scale=8)
    project.export_animation(output / "potion.apng", format="apng", scale=8)
    project.export_animation(output / "potion-sheet.png", format="sheet", columns=4)
    project.export_animation(output / "potion-sheet-large.png", format="sheet", columns=4, scale=8)
    print(f"Created pixel animation and sprite sheet in {output.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="examples/sprite-output")
    build(parser.parse_args().output)
