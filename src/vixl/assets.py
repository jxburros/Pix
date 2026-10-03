"""Content-addressed, normalized image assets; imports never execute project content."""

import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps

from .errors import VixlError, require


def decode(data, limits, mode="RGBA", size_hint=None):
    """Decode a bounded image. ``size_hint`` lets JPEG decode at a reduced DCT scale when the
    caller only needs at least that many pixels (previews, downsized layers)."""
    require(len(data) <= limits.max_asset_bytes, "Asset exceeds byte limit", "resource_limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                limits.size(*image.size)
                if size_hint and image.format == "JPEG":
                    # Orientation may swap axes, so request the larger side on both.
                    side = max(size_hint)
                    image.draft("RGB", (side, side))
                image.load()
                if image.getexif().get(0x0112, 1) != 1:
                    image = ImageOps.exif_transpose(image)
                return image.convert(mode) if image.mode != mode else image.copy()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise VixlError("invalid_image", f"Cannot decode image: {exc}") from exc


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=6)
    return stream.getvalue()


def read_bounded(path, limit):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "File exceeds byte limit", "resource_limit")
    return data


SOURCE_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}


def add_encoded(project, data, category="assets"):
    """Embed an imported file. Compact still-image formats keep their original bytes (a JPEG
    photo stays a JPEG instead of growing ~10x as PNG); anything else is normalized to PNG.
    Returns ``(asset_name, decoded_image)``."""
    image = decode(data, project.limits)
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            frames = getattr(probe, "n_frames", 1)
    except (OSError, ValueError) as exc:
        raise VixlError("invalid_image", f"Cannot decode image: {exc}") from exc
    if fmt in SOURCE_FORMATS and frames == 1:
        name = f"{category}/{hashlib.sha256(data).hexdigest()}.{SOURCE_FORMATS[fmt]}"
        project.assets[name] = data
        return name, image
    return add_image(project, image, category), image


def add_image(project, image, category="assets"):
    project.limits.size(*image.size)
    data = png_bytes(image)
    require(len(data) <= project.limits.max_asset_bytes, "Asset exceeds byte limit", "resource_limit")
    name = f"{category}/{hashlib.sha256(data).hexdigest()}.png"
    project.assets[name] = data
    return name
