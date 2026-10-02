"""Content-addressed, normalized image assets; imports never execute project content."""

import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageOps

from .errors import PixError, require


def decode(data, limits, mode="RGBA"):
    require(len(data) <= limits.max_asset_bytes, "Asset exceeds byte limit", "resource_limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                limits.size(*image.size)
                return ImageOps.exif_transpose(image).convert(mode)
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise PixError("invalid_image", f"Cannot decode image: {exc}") from exc


def png_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG", compress_level=6)
    return stream.getvalue()


def read_bounded(path, limit):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "File exceeds byte limit", "resource_limit")
    return data


def add_image(project, image, category="assets"):
    project.limits.size(*image.size)
    data = png_bytes(image)
    require(len(data) <= project.limits.max_asset_bytes, "Asset exceeds byte limit", "resource_limit")
    name = f"{category}/{hashlib.sha256(data).hexdigest()}.png"
    project.assets[name] = data
    return name
