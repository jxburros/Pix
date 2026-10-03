"""Frozen runtime entry point, including a real offline installation health check."""

import json
import multiprocessing
from pathlib import Path
import sys
import tempfile


def main():
    multiprocessing.freeze_support()
    if sys.argv[1:] == ["--vixl-healthcheck"]:
        from vixl import Project, __version__
        from vixl.interfaces import create_app, mcp_server
        from vixl.cli import dispatch

        assert dispatch(["--version"])[0] == __version__

        with tempfile.TemporaryDirectory(prefix="vixl-health-") as tmp:
            p = Project(64, 32)
            p.apply({"type": "text", "text": "Vixl", "size": 16})
            assert p.export(format="PNG").startswith(b"\x89PNG")
            import xml.etree.ElementTree as ET

            svg = ET.fromstring(p.export(format="SVG"))
            assert svg.findall(".//{*}path") and not svg.findall(".//{*}image")
            path = Path(tmp) / "health.vixl"
            p.save(path)
            create_app(path)
            mcp_server(path)
        print(json.dumps({"ok": True, "version": __version__}))
        return 0
    from vixl.cli import main as cli

    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
