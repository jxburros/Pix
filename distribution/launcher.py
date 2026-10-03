"""Stable per-user launcher. Frozen separately; it does not import the imaging engine."""

import os
import json
from pathlib import Path
import subprocess
import sys

import updater


def main():
    root = Path(sys.executable).resolve().parent.parent
    args = sys.argv[1:]
    try:
        if args[:1] == ["--pix-install"]:
            updater.require(len(args) == 2, "Installer requires a version")
            updater.initialize(root, args[1])
            return 0
        if args == ["--pix-background-update"]:
            updater.background(root)
            return 0
        # Recovery must work even when a regression prevents the active CLI from importing.
        if [arg for arg in args if arg != "--json"] == ["update", "--rollback"]:
            print(json.dumps(updater.rollback(root)))
            return 0
        # Update controls inspect the currently installed state without switching it underneath the command.
        controls = any(x in ("update", "updates") for x in args)
        allow = os.environ.get("PIX_NO_UPDATE") != "1" and not controls
        exe, due = updater.prepare_launch(root, allow_updates=allow)
        env = updater.child_environment(root)
        if due:
            try:
                subprocess.Popen(
                    [sys.executable, "--pix-background-update"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(root),
                    env=env,
                    close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            except OSError:
                pass  # Editing still works if Windows prevents background process creation.
        return subprocess.call([str(exe), *args], env=env)
    except updater.UpdateError as exc:
        message = (
            json.dumps({"error": "update_error", "message": str(exc)}) if "--json" in args else f"Pix: {exc}"
        )
        print(message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
