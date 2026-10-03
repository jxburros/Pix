"""Public Python API. All interfaces share Project.apply and Project.render."""

__version__ = "0.12.1"

from .errors import VixlError  # noqa: E402

__all__ = ["Project", "VixlError"]


def __getattr__(name):
    if name == "Project":
        from .project import Project

        globals()[name] = Project
        return Project
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
