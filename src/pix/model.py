"""JSON document model and resource policy; no interface dependencies."""

from dataclasses import dataclass, asdict
import math
import uuid

from .errors import require


@dataclass(frozen=True)
class Limits:
    max_pixels: int = 40_000_000
    max_dimension: int = 16384
    max_layers: int = 512
    max_asset_bytes: int = 64 * 1024 * 1024
    max_project_bytes: int = 256 * 1024 * 1024
    max_operations: int = 1000
    max_history: int = 2000

    def size(self, width, height):
        require(isinstance(width, int) and isinstance(height, int), "Dimensions must be integers")
        require(
            0 < width <= self.max_dimension and 0 < height <= self.max_dimension,
            f"Dimensions must be 1–{self.max_dimension}",
            "resource_limit",
        )
        require(width * height <= self.max_pixels, "Image exceeds pixel limit", "resource_limit")


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def finite(value, name="value", low=None, high=None):
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        f"{name} must be a finite number",
    )
    require(low is None or value >= low, f"{name} must be at least {low}")
    require(high is None or value <= high, f"{name} must be at most {high}")
    return value


def new_state(width, height, background):
    return {
        "canvas": {"width": width, "height": height, "background": background, "color_mode": "rgba8"},
        "layers": [],
        "active_layer": None,
        "selection": None,
        "variables": {},
        "presets": {},
    }


def new_layer(name, kind, width, height, **kwargs):
    return {
        "id": uid("lyr"),
        "name": name,
        "type": kind,
        "width": width,
        "height": height,
        "x": 0,
        "y": 0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
        "opacity": 1.0,
        "blend": "normal",
        "visible": True,
        "effects": [],
        "mask": None,
        "constraints": {},
        **kwargs,
    }


def policy_dict(limits):
    return asdict(limits)
