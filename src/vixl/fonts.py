"""Explicit, bounded font imports with portable embedding and no implicit network access."""

import hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import ImageFont

from .assets import read_bounded
from .errors import VixlError, require


def validate_font(data):
    try:
        ImageFont.truetype(BytesIO(data), 16)
    except (OSError, ValueError) as exc:
        raise VixlError(
            "invalid_font", "Use a valid TrueType/OpenType font file; CSS and WOFF are not supported"
        ) from exc


def import_font(project, source, name):
    from .design import named

    named(name)
    limit = min(project.limits.max_asset_bytes, 16 * 1024 * 1024)
    if urlparse(str(source)).scheme in ("http", "https"):
        require(urlparse(str(source)).scheme == "https", "Font downloads require HTTPS")
        require(
            not urlparse(str(source)).username and not urlparse(str(source)).password,
            "Font URLs cannot contain credentials",
        )
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                with client.stream("GET", str(source)) as response:
                    require(
                        response.status_code == 200, f"Font download returned HTTP {response.status_code}"
                    )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        require(len(data) <= limit, "Font exceeds byte limit", "resource_limit")
                    data = bytes(data)
        except httpx.HTTPError as exc:
            raise VixlError("font_download_failed", f"Font download failed ({type(exc).__name__})") from exc
    else:
        data = read_bounded(Path(source), limit)
    validate_font(data)
    asset = f"fonts/{hashlib.sha256(data).hexdigest()}.ttf"
    candidate = project.clone()
    candidate.assets[asset] = data
    result = candidate.apply({"type": "font-register", "name": name, "asset": asset}, detail="compact")
    project.__dict__.update(candidate.__dict__)
    return result
