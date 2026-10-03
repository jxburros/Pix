"""Small, named animation snapshots and bounded nearest-neighbor exports."""

from copy import copy, deepcopy
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import require

ANIMATION_TYPES = ("frame-save", "frame-apply", "frame-delete", "animation-set")
MAX_FRAMES = 256


def frame_project(project, frame):
    candidate = copy(project)
    candidate.state = deepcopy(frame["state"])
    candidate._cache = {}
    return candidate


def validate_animation(project, state):
    if "animation" not in state:
        return
    from .validation import check_state
    from .render import resolve_layout

    animation = state["animation"]
    require(
        isinstance(animation, dict) and set(animation) <= {"frames", "loop"}, "Invalid animation settings"
    )
    frames = animation.get("frames", [])
    require(isinstance(frames, list) and len(frames) <= MAX_FRAMES, "Animation supports at most 256 frames")
    loop = animation.get("loop", 0)
    require(
        isinstance(loop, int) and not isinstance(loop, bool) and 0 <= loop <= 65535, "Loop must be 0–65535"
    )
    names, sizes = set(), set()
    total = 0
    for frame in frames:
        require(
            isinstance(frame, dict) and set(frame) == {"name", "duration", "state"}, "Invalid animation frame"
        )
        from .design import named

        named(frame["name"])
        require(frame["name"] not in names, "Duplicate animation frame")
        names.add(frame["name"])
        duration = frame["duration"]
        require(
            isinstance(duration, int) and 10 <= duration <= 60000 and duration % 10 == 0,
            "Frame duration must be 10–60000 ms, in multiples of 10",
        )
        snapshot = frame["state"]
        require(
            isinstance(snapshot, dict) and "animation" not in snapshot,
            "Nested animation frames are forbidden",
        )
        check_state(project, snapshot)
        require(
            not any(layer.get("linked") for layer in snapshot["layers"]),
            "Embed linked images before saving frames",
        )
        w, h = snapshot["canvas"]["width"], snapshot["canvas"]["height"]
        require(w <= 256 and h <= 256, "Animation frames are limited to 256×256 pixels")
        sizes.add((w, h))
        total += w * h
        require(total <= project.limits.max_pixels, "Animation exceeds pixel budget", "resource_limit")
        resolve_layout(frame_project(project, frame))
    require(len(sizes) <= 1, "All animation frames must have the same canvas size")


def execute_animation(project, op):
    animation = project.state.setdefault("animation", {"frames": [], "loop": 0})
    frames = animation["frames"]
    kind = op["type"]
    if kind == "animation-set":
        if "loop" in op:
            animation["loop"] = op["loop"]
        if "order" in op:
            require(
                len(op["order"]) == len(frames) and set(op["order"]) == {f["name"] for f in frames},
                "Order must list every frame exactly once",
            )
            by_name = {f["name"]: f for f in frames}
            animation["frames"] = [by_name[name] for name in op["order"]]
        return
    from .design import named

    name = named(op["name"])
    existing = next((f for f in frames if f["name"] == name), None)
    if kind == "frame-save":
        require(
            existing is not None or len(frames) < MAX_FRAMES,
            "Animation frame limit reached",
            "resource_limit",
        )
        snapshot = deepcopy({k: v for k, v in project.state.items() if k != "animation"})
        frame = {
            "name": name,
            "duration": op.get("duration", existing["duration"] if existing else 100),
            "state": snapshot,
        }
        if existing:
            frames[frames.index(existing)] = frame
        else:
            frames.append(frame)
        validate_animation(project, project.state)
    else:
        require(existing is not None, f"Unknown animation frame: {name}")
        if kind == "frame-delete":
            frames.remove(existing)
        else:
            project.state = deepcopy(existing["state"])
            project.state["animation"] = animation


def inspect_animation(project):
    animation = project.state.get("animation", {"frames": [], "loop": 0})
    return {
        "loop": animation.get("loop", 0),
        "total_duration": sum(f["duration"] for f in animation["frames"]),
        "frames": [
            {
                "name": f["name"],
                "duration": f["duration"],
                "canvas": f["state"]["canvas"],
                "layer_count": len(f["state"]["layers"]),
            }
            for f in animation["frames"]
        ],
    }


def render_frame(project, name, scale=1):
    require(
        isinstance(scale, int) and not isinstance(scale, bool) and 1 <= scale <= 32,
        "Pixel scale must be an integer 1–32",
    )
    frame = next((f for f in project.state.get("animation", {}).get("frames", []) if f["name"] == name), None)
    require(frame is not None, f"Unknown animation frame: {name}")
    c = frame["state"]["canvas"]
    size = c["width"] * scale, c["height"] * scale
    project.limits.size(*size)
    image = frame_project(project, frame).render()
    return image.resize(size, Image.Resampling.NEAREST) if scale != 1 else image


def gif_frame(image):
    # Reserve index 0 for transparency, with a deterministic alpha threshold.
    indexed = image.convert("RGB").quantize(
        colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    pixels = np.asarray(indexed, dtype=np.uint16) + 1
    pixels[np.asarray(image.getchannel("A")) < 128] = 0
    result = Image.fromarray(pixels.astype("uint8")).convert("P")
    result.putpalette([0, 0, 0] + indexed.getpalette()[:765])
    result.info["transparency"] = 0
    return result


def animation_bytes(project, *, format="gif", scale=1, columns=None):
    require(format in ("gif", "apng", "sheet"), "Animation format must be gif, apng or sheet")
    validate_animation(project, project.state)
    animation = project.state.get("animation", {})
    frames = animation.get("frames", [])
    require(frames, "Save at least one animation frame")
    require(
        isinstance(scale, int) and not isinstance(scale, bool) and 1 <= scale <= 32,
        "Pixel scale must be an integer 1–32",
    )
    c = frames[0]["state"]["canvas"]
    w, h = c["width"] * scale, c["height"] * scale
    project.limits.size(w, h)
    require(
        w * h * len(frames) <= project.limits.max_pixels,
        "Animation export exceeds pixel budget",
        "resource_limit",
    )
    require(columns is None or format == "sheet", "Columns apply only to sprite sheets")
    stream = io.BytesIO()
    metadata = None
    durations = [f["duration"] for f in frames]
    if format == "sheet":
        columns = columns if columns is not None else math.ceil(math.sqrt(len(frames)))
        require(isinstance(columns, int) and 1 <= columns <= len(frames), "Invalid sprite-sheet column count")
        rows = math.ceil(len(frames) / columns)
        project.limits.size(w * columns, h * rows)
        image = Image.new("RGBA", (w * columns, h * rows))
        metadata = {
            "width": image.width,
            "height": image.height,
            "loop": animation.get("loop", 0),
            "frames": [],
        }
        for i, frame in enumerate(frames):
            x, y = i % columns * w, i // columns * h
            image.paste(render_frame(project, frame["name"], scale), (x, y))
            metadata["frames"].append(
                {
                    "name": frame["name"],
                    "duration": frame["duration"],
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                }
            )
        image.save(stream, format="PNG")
    else:
        images = [render_frame(project, f["name"], scale) for f in frames]
        loop = animation.get("loop", 0)
        if format == "gif":
            images = [gif_frame(image) for image in images]
            images[0].save(
                stream,
                format="GIF",
                save_all=True,
                append_images=images[1:],
                duration=durations,
                loop=loop,
                disposal=2,
                transparency=0,
                optimize=False,
            )
        else:
            images[0].save(
                stream,
                format="PNG",
                save_all=True,
                append_images=images[1:],
                duration=durations,
                loop=loop + 1 if loop else 0,
                disposal=0,
                blend=0,
            )
    return stream.getvalue(), metadata


def export_animation(project, path, *, format=None, scale=1, columns=None):
    path = Path(path)
    format = format or (".gif" == path.suffix.lower() and "gif") or "apng"
    require(
        path.suffix.lower() in ((".gif",) if format == "gif" else (".png", ".apng")),
        "Use a GIF or PNG/APNG output filename",
    )
    destinations = [path] + ([path.with_suffix(".json")] if format == "sheet" else [])
    require(not any(p.exists() for p in destinations), "Animation output already exists")
    data, metadata = animation_bytes(project, format=format, scale=scale, columns=columns)
    # Create only after all rendering succeeds. Refuse concurrent clobbers as well.
    with path.open("xb") as stream:
        stream.write(data)
    if metadata is not None:
        with destinations[1].open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2)
    return {
        "output": str(path),
        "format": format,
        "bytes": len(data),
        **({"metadata": str(destinations[1])} if metadata is not None else {}),
    }
