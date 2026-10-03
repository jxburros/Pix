"""Shared vector paths for procedural shortcuts and bounded editable Bézier geometry."""

import math
import re

from .errors import require

SHORTCUTS = {
    "triangle": "M50 0 L100 100 L0 100 Z",
    "right-triangle": "M0 0 L100 100 L0 100 Z",
    "diamond": "M50 0 L100 50 L50 100 L0 50 Z",
    "arrow": "M0 30 L60 30 L60 0 L100 50 L60 100 L60 70 L0 70 Z",
    "chevron": "M0 0 L40 0 L100 50 L40 100 L0 100 L60 50 Z",
    "cross": "M35 0 L65 0 L65 35 L100 35 L100 65 L65 65 L65 100 L35 100 L35 65 L0 65 L0 35 L35 35 Z",
    "heart": "M50 95 C35 80 0 55 0 30 C0 0 35 -5 50 20 C65 -5 100 0 100 30 C100 55 65 80 50 95 Z",
    "speech-bubble": "M10 0 L90 0 Q100 0 100 10 L100 65 Q100 75 90 75 L45 75 L20 100 L20 75 L10 75 Q0 75 0 65 L0 10 Q0 0 10 0 Z",
    "shield": "M0 0 L100 0 L100 45 Q100 80 50 100 Q0 80 0 45 Z",
    "trapezoid": "M25 0 L75 0 L100 100 L0 100 Z",
    "parallelogram": "M25 0 L100 0 L75 100 L0 100 Z",
}
EXTRA_SHAPES = (*SHORTCUTS, "pentagon", "hexagon", "octagon", "capsule", "path")


def parse_path(path):
    require(isinstance(path, str) and 0 < len(path) <= 32768, "Path must contain 1–32768 characters")
    tokens = re.findall(r"[MLHVQCZmlhvqcz]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", path)
    remainder = re.sub(r"[MLHVQCZmlhvqcz]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?|[\s,]", "", path)
    require(not remainder and tokens and tokens[0].upper() == "M", "Use SVG path commands M L H V Q C Z")
    commands, i, current, start = [], 0, (0, 0), (0, 0)
    while i < len(tokens):
        command = tokens[i]
        require(command.isalpha(), "Repeat the command before every coordinate set")
        i += 1
        count = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6, "Z": 0}[command.upper()]
        require(i + count <= len(tokens), "Incomplete path command")
        values = tokens[i : i + count]
        require(all(not v.isalpha() for v in values), "Incomplete path coordinates")
        values = list(map(float, values))
        require(all(math.isfinite(v) and abs(v) <= 1e6 for v in values), "Path coordinates exceed limits")
        i += count
        upper = command.upper()
        if command.islower():
            values = [
                v + current[(1 if upper == "V" else 0) if count == 1 else j % 2] for j, v in enumerate(values)
            ]
        if upper == "H":
            upper, values = "L", [values[0], current[1]]
        if upper == "V":
            upper, values = "L", [current[0], values[0]]
        if upper == "M":
            require(not commands, "Use a single contour per path layer")
        if upper == "Z":
            current = start
        else:
            current = tuple(values[-2:])
            if upper == "M":
                start = current
        commands.append((upper, values))
        require(len(commands) <= 1024, "Path supports at most 1024 commands", "resource_limit")
    return commands


def path_polygons(path):
    polygons, points, current = [], [], (0, 0)
    for command, values in parse_path(path):
        if command == "M":
            if points:
                polygons.append(points)
            current = tuple(values)
            points = [current]
        elif command == "Z":
            if points:
                points.append(points[0])
                current = points[0]
        elif command == "L":
            current = tuple(values)
            points.append(current)
        else:
            controls = [current, *zip(values[::2], values[1::2])]
            for step in range(1, 49):
                t = step / 48
                working = controls
                while len(working) > 1:
                    working = [
                        (a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t)
                        for a, b in zip(working, working[1:])
                    ]
                points.append(working[0])
            current = tuple(values[-2:])
    if points:
        polygons.append(points)
    return polygons


def shape_path(layer):
    shape = layer["shape"]
    if shape == "path":
        return layer["path"], layer.get("path_view", (layer["width"], layer["height"]))
    if shape in SHORTCUTS:
        return SHORTCUTS[shape], (100, 100)
    sides = {"pentagon": 5, "hexagon": 6, "octagon": 8}.get(
        shape, layer.get("sides", 5 if shape == "star" else 6)
    )
    points = []
    for i in range(sides * 2 if shape == "star" else sides):
        radius = layer.get("inner_radius", 0.5) if shape == "star" and i % 2 else 1
        angle = i * 2 * math.pi / (sides * 2 if shape == "star" else sides) - math.pi / 2
        points.append((50 + math.cos(angle) * 50 * radius, 50 + math.sin(angle) * 50 * radius))
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in points) + " Z", (100, 100)
