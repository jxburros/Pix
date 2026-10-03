"""Package immutable release files; updater assets have a fixed public contract."""

import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

from pix import __version__

parser = argparse.ArgumentParser()
parser.add_argument("--checksums", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == __version__
output = root / "dist" / "release"
output.mkdir(parents=True, exist_ok=True)
if args.checksums:
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(output.iterdir())
        if p.is_file() and p.name != "SHA256SUMS.txt"
    ]
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
else:
    runtime = root / "dist" / "runtime" / "pix-engine"
    assert (runtime / "pix-engine.exe").is_file()
    bundle = output / f"pix-{__version__}-windows-x64.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(runtime.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(runtime).as_posix())
    manifest = {
        "protocol": 1,
        "version": __version__,
        "platform": "windows-x64",
        "asset": bundle.name,
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "size": bundle.stat().st_size,
    }
    (output / "pix-update.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
