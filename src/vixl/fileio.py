"""Atomic file publication that honors the user's umask and keeps existing permissions."""

import os
from pathlib import Path
import stat
import uuid


def temporary(directory, suffix=".tmp", like=None):
    """Create an exclusive temporary file in ``directory``; return ``(fd, path)``.

    ``tempfile.mkstemp`` always creates mode 0600, which silently made saved projects and
    exports private. Creating with 0666 lets the umask decide, and an existing destination's
    mode is preserved when ``like`` names it.
    """
    directory = Path(directory)
    while True:
        path = directory / f".vixl-{uuid.uuid4().hex}{suffix}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
            break
        except FileExistsError:
            continue
    if like is not None:
        try:
            os.chmod(path, stat.S_IMODE(os.stat(like).st_mode))
        except OSError:
            pass
    return fd, str(path)
