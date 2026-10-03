"""Public Python API. All interfaces share Project.apply and Project.render."""

__version__ = "0.11.0"

from .project import Project  # noqa: E402
from .errors import VixlError  # noqa: E402

__all__ = ["Project", "VixlError"]
