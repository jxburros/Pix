"""Generate the README poster and an editable template using only the Pix engine."""

import argparse
from pathlib import Path
from pix import Project

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="examples/output")
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
p = Project(1280, 960, "#131c2b")
ops = [
    {"type": "variable", "name": "event", "value": "AFTER\nHOURS"},
    {"type": "variable", "name": "date", "value": "OCT 30  /  DOORS 21:00"},
    {"type": "gradient", "name": "atmosphere", "start": "#1e2e43", "end": "#0c1420"},
    {"type": "solid", "name": "top-rule", "width": 1152, "height": 2, "color": "#718092", "x": 64, "y": 107},
    {
        "type": "text",
        "name": "brand",
        "text": "PIX  /  FIELD NOTES",
        "size": 22,
        "x": 64,
        "y": 58,
        "color": "#eae8df",
    },
    {
        "type": "text",
        "name": "edition",
        "text": "NO. 006     •     AUTUMN SESSIONS",
        "size": 17,
        "color": "#a0afc0",
    },
    {"type": "constrain", "constraints": {"right": "canvas.right-64", "top": "canvas.top+62"}},
    {
        "type": "gradient",
        "name": "orb",
        "width": 640,
        "height": 640,
        "start": "#e8885c",
        "end": "#4853a4",
        "x": 564,
        "y": 165,
    },
    {"type": "select", "shape": "ellipse", "x": 564, "y": 165, "width": 640, "height": 640},
    {"type": "mask", "action": "from-selection"},
    {"type": "select", "shape": "none"},
]
# Small gaps create a cut-paper sphere without flattening any source layers.
for index in range(16):
    ops.append(
        {
            "type": "solid",
            "name": f"stripe-{index:02}",
            "width": 700,
            "height": 6 + index,
            "color": "#152235",
            "x": 534,
            "y": 190 + index * 37,
        }
    )
ops += [
    {
        "type": "text",
        "name": "eyebrow",
        "text": "A LATE-NIGHT LISTENING ROOM",
        "size": 18,
        "color": "#cf9d77",
        "x": 67,
        "y": 201,
    },
    {
        "type": "text",
        "name": "title",
        "text": "${event}",
        "size": 132,
        "spacing": 0,
        "color": "#f5eddb",
        "x": 56,
        "y": 278,
    },
    {
        "type": "text",
        "name": "artists",
        "text": "NEW SOUNDS.\nFAMILIAR STRANGERS.",
        "size": 22,
        "spacing": 8,
        "color": "#b1bdca",
        "x": 68,
        "y": 621,
    },
    {"type": "solid", "name": "accent", "width": 42, "height": 5, "color": "#e3a57b", "x": 68, "y": 721},
    {
        "type": "solid",
        "name": "bottom-rule",
        "width": 1152,
        "height": 2,
        "color": "#718092",
        "x": 64,
        "y": 819,
    },
    {"type": "text", "name": "date", "text": "${date}", "size": 23, "color": "#f5eddb", "x": 64, "y": 859},
    {
        "type": "text",
        "name": "venue",
        "text": "THE OBSERVATORY\n48 NORTH AVENUE",
        "size": 17,
        "spacing": 7,
        "color": "#b1bdca",
        "align": "right",
    },
    {"type": "constrain", "constraints": {"right": "canvas.right-64", "bottom": "canvas.bottom-62"}},
]
p.apply(ops)
p.checkpoint("finished-layout")
p.save(out / "after-hours.pix")
p.export(out / "after-hours.png")
p.export(out / "late-edition.png", variables={"event": "LATE\nEDITION", "date": "NOV 13  /  DOORS 22:00"})
print(f"Created editable template and two renders in {out.resolve()}")
