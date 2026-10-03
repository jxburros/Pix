"""Frozen runtime entry point, including a real offline installation health check."""

import json
import multiprocessing
from pathlib import Path
import sys
import tempfile


def main():
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--pix-healthcheck"]:
        from pix import Project, __version__
        from pix.interfaces import create_app, mcp_server

        with tempfile.TemporaryDirectory(prefix="pix-health-") as tmp:
            p = Project(64, 32)
            p.apply({"type": "text", "text": "Pix", "size": 16})
            assert p.export(format="PNG").startswith(b"\x89PNG")
            path = Path(tmp) / "health.pix"
            p.save(path)
            create_app(path)
            mcp_server(path)
        print(json.dumps({"ok": True, "version": __version__}))
        return 0
    from pix.cli import main as cli

    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
