"""Windows integration: real archive download/stage/probe/switch plus broken-candidate recovery.
Only GitHub transport is replaced; installed frozen executables are really executed.
"""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

from pix import __version__
from pix import updater

root = Path(sys.argv[1]).resolve()
bundle = Path(sys.argv[2]).resolve()
launcher = root / "bin" / "pix.exe"
env = os.environ.copy()
env.pop("PIX_NO_UPDATE", None)
# Simulate an older directory layout using the working runtime as our baseline fixture.
old = "0.0.1"
shutil.move(root / "versions" / __version__, root / "versions" / old)
state = updater.read_state(root)
state.update(current=old, previous=None, pending=None, last_check=time.time())
updater.atomic_json(root / "install.json", state)
release = {
    "version": __version__,
    "url": "fixture",
    "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
    "size": bundle.stat().st_size,
    "release_url": "fixture",
}


def download(_url, destination, limit=0):
    shutil.copyfile(bundle, destination)
    return release["sha256"], release["size"]


with (
    patch.object(updater, "latest", return_value=release),
    patch.object(updater, "download", side_effect=download),
):
    assert updater.update(root)["status"] == "ready"
assert updater.read_state(root)["current"] == old
assert updater.read_state(root)["pending"] == __version__
result = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, env=env, timeout=90)
assert result.returncode == 0, result.stderr
assert result.stdout.strip() == __version__
assert updater.read_state(root)["current"] == __version__
assert updater.read_state(root)["previous"] == old
# A corrupted candidate must never prevent the known-good version from running.
broken = "999.0.0"
(root / "versions" / broken).mkdir()
(root / "versions" / broken / "pix-engine.exe").write_bytes(b"not an executable")
state = updater.read_state(root)
state.update(pending=broken, last_check=time.time())
updater.atomic_json(root / "install.json", state)
result = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, env=env, timeout=90)
assert result.returncode == 0 and result.stdout.strip() == __version__, result.stderr
state = updater.read_state(root)
assert state["current"] == __version__ and state["pending"] is None and state["rejected"] == broken
# A failed user command is not a reason to roll back a healthy application.
subprocess.run([str(launcher), "not-a-command"], capture_output=True, env=env, timeout=60)
assert updater.read_state(root)["current"] == __version__
print("Native staging, checksum, health check, activation and failed-candidate recovery passed.")
