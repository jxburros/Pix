"""Opt-in trusted Python extension entry points. Never load code from a .vixl archive."""

from importlib.metadata import entry_points
from .errors import VixlError

_ENABLED = False


def enable_plugins():
    global _ENABLED
    _ENABLED = True


def load(group, name):
    if not _ENABLED:
        raise VixlError("plugins_disabled", "Third-party plugins require --plugins or enable_plugins()")
    found = entry_points(group=f"vixl.{group}", name=name)
    if not found:
        raise VixlError("plugin_not_found", f"No {group} plugin named {name}")
    return next(iter(found)).load()


def filter_plugin(name):
    return load("filters", name)
