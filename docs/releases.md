# Windows installation, updates, and GitHub releases

Vixl is a headless application designed for autonomous AI agents; humans can use the same interfaces.

## Install once

1. Open [the latest GitHub release](https://github.com/jxburros/Vixl/releases/latest).
2. Download the file named **Vixl-Setup-VERSION-windows-x64.exe** and run it.
3. Close every window of your terminal application and reopen it. Restart VS Code too if you use its integrated terminal.
4. Run `vixl --version` and `vixl --help` from any directory.

Python and the engine dependencies are bundled. The installer requires no administrator privileges. It installs to `%LOCALAPPDATA%\Programs\Vixl` and prepends its `bin` directory to your **user** PATH, preserving the other entries. It supplies a Start menu shortcut and a normal Windows uninstaller. Windows x64 is the current installer target; macOS/Linux users can continue using the Python package. WSL is a separate Linux environment, not the Windows installation.

The first installer is not Authenticode-signed: a Windows publisher/SmartScreen warning may appear. The repository currently has no signing certificate configured. Download from the official repository's Releases page. `SHA256SUMS.txt` is provided for artifact verification; checksums do not constitute an independent publisher signature.

### Using the current terminal

An installer cannot change the environment of its parent terminal or agent process. To use the managed installation immediately in an existing PowerShell session, prepend only its launcher directory, preserving session-specific PATH entries:

```powershell
$VixlBin = Join-Path $env:LOCALAPPDATA 'Programs\Vixl\bin'
$env:Path = "$VixlBin;$env:Path"
Get-Command vixl -All
vixl --version
vixl updates status --json
```

For a custom install location, substitute its `bin` directory. To avoid any PATH ambiguity, use `& "$VixlBin\vixl.exe" --version` or `& "$VixlBin\vixl.exe" update`. In Command Prompt, use `set "PATH=%LOCALAPPDATA%\Programs\Vixl\bin;%PATH%"`.

Check the version from the exact executable your agent invokes before using documented options. A pip install and the Windows managed install are separate: updating one does not update the other. Documentation on `main` may describe features newer than the latest published installer; use documentation at your installed release tag or install the matching published release. Grouped SVG vectors/plain outlined text require 0.11.1+, and shaped Unicode text plus `--svg-policy strict` require 0.12.0+.

Immediate explicit activation is available in 0.12.1+. When upgrading from an older updater, it may still report a staged update once; launch Vixl once to activate that release, or run the matching installer. New installers also put update/check/rollback controls in the stable launcher so recovery does not depend on importing a broken or older engine. Runtime updates do not replace that launcher.

### Recovering from an inaccessible pending update

Older launchers can crash in `probe` / `Path.is_file` with `[WinError 5] Access is denied` before they reject an inaccessible pending runtime. If `install.json` still names a working `current` version, bypass the pending switch and turn off automatic retries:

```powershell
$VixlExe = Join-Path $env:LOCALAPPDATA 'Programs\Vixl\bin\vixl.exe'
& $VixlExe updates off
& $VixlExe --version
```

This clears `pending` without deleting projects or installed runtimes. `previous: null` means rollback is unavailable; it does not prevent continuing with `current`. The fixed launcher rejects the inaccessible candidate, preserves the active runtime, and records the path and operating-system error under `last_error` in `vixl updates status`. Update settings work even when the active engine cannot start.

Access denied can come from file permissions or security software; the traceback alone does not identify which. Repair the installation using an installer containing this fix, and check Windows Security's Protection History if access remains blocked. Installing only an engine update does not replace an older launcher. After repair, use `vixl updates on` to re-enable automatic updates.

### Moving from the earlier pip installation

Install the new Windows edition first. After reopening the terminal, `where vixl` (Command Prompt) or `Get-Command vixl` (PowerShell) should resolve to `...\Programs\Vixl\bin\vixl.exe`.

Once that works, you may remove the older Python package with `python -m pip uninstall vixl-engine`, using the same Python that installed it. This does not remove the managed Windows installation, your `.vixl` projects, or your provider configuration. A system-level `vixl.exe` earlier in the system PATH may take precedence over the user PATH; remove that older installation or launch the managed executable by its full path.

The source ZIP in Downloads is not needed by the installer edition. Keep your own projects outside the application's `versions` and `update-work` folders. The uninstaller removes installed runtimes, update metadata and its own PATH entry; it does not remove projects elsewhere or `~/.config/vixl/providers.json`.

## Automatic updates

Automatic updates are enabled on a new installation. A normal `vixl` launch starts a detached background check at most once every 24 hours, including failed/offline checks. There is no scheduled task or always-running service. If Vixl is not launched, it does not check. Editing starts without waiting for the network, and the worker never writes to CLI JSON, binary image output, or MCP streams.

Only the latest **published stable** GitHub release with a compatible Windows update manifest is eligible. Drafts, prereleases, equal versions, and downgrades are ignored or rejected. The updater:

1. Gets release metadata from the fixed `jxburros/Vixl` GitHub repository over HTTPS.
2. Downloads the runtime ZIP and verifies its exact size and SHA-256 against the release manifest.
3. Rejects unsafe ZIP paths, links, case-colliding paths, NTFS alternate streams and oversized archives.
4. Extracts into a temporary directory and runs an offline rendering/API/MCP startup health check.
5. Moves the validated runtime into its own version directory.
6. For explicit `vixl update`, checks the installed path and atomically switches the active-version pointer before returning success. Background updates remain pending and activate after another health check on a subsequent normal launch.

The previous runtime remains on disk. Existing processes continue using their original runtime: an update never replaces loaded executables or DLLs. A failed candidate health check clears the pending switch and leaves the current working version active. Failed user commands, validation failures and editing errors do **not** trigger rollbacks. Runtime regressions not detectable by the startup check may require manual rollback.

Offline operation keeps working. `vixl updates status` exposes the last background failure; checks remain silent otherwise. `update --check` and `updates` commands do not activate an already pending version before inspecting/changing settings. Explicit `update` activates the verified release immediately, including an already staged copy.

## Controls

```text
vixl update --check       Check now; do not download an application update
vixl update               Download, verify, and activate now; report the active version
vixl updates status       Inspect installed versions, settings, and last check/error
vixl updates off          Disable background checks and cancel pending activation
vixl updates on           Re-enable future automatic checks
vixl update --rollback    Use the previous runtime on subsequent launches; disable auto-update
```

All commands support `--json`. Explicit `vixl update` is allowed even with automatic updates turned off. An open interactive shell continues running its original version after these commands; exit and relaunch to use the selected version.

For reproducible scripts, either turn updates off or set `VIXL_NO_UPDATE=1` for their environment. That suppresses automatic checks **and pending activation** for those launches. For example, in Command Prompt:

```bat
set "VIXL_NO_UPDATE=1"
vixl --version
```

Downloaded runtimes are retained for recovery and are not garbage-collected automatically. The stable launcher implements update protocol 1. A future incompatible launcher/protocol change will require running a newer installer instead of silently replacing an executable currently in use. Re-running the installer preserves the automatic-update preference and refuses downgrades.

Python installations intentionally do not self-update or invoke pip. They return an explanatory error for managed update commands; update them using your environment's package-management workflow.

## Maintaining releases

`.github/workflows/release.yml` builds and tests Windows installers on pull requests. Test artifacts can be downloaded from the successful Actions run. Normal CI additionally tests Python 3.11–3.14 on Linux, macOS and Windows.

To publish a stable release:

1. Update the single-sourced version in `src/vixl/__init__.py` (package/API versions derive from it), and the displayed document versions; update release notes/documentation as needed.
2. Run tests and review the PR's **Windows installer and releases** workflow. It runs a real silent installer, verifies PATH lookup, creates/exports a project using the frozen runtime, activates an explicit update before any normal launch with mocked network transport, checks corrupted-candidate recovery, and uninstalls while preserving a user project and existing PATH entries.
3. Tag the reviewed commit with its exact version and push the tag:

   ```bash
   git tag v0.12.1 <reviewed-commit>
   git push origin v0.12.1
   ```

4. The tag workflow re-runs tests, checks tag/package-version consistency, builds the distributions, and creates a **draft** GitHub release. It uploads every artifact before publishing it as the latest stable release. No release becomes visible to the updater while files are still being uploaded.

The workflow uses GitHub's built-in token with `contents: write` only in the publish job. No personal token, external package registry, or certificate secret is required. If publication fails after draft creation, inspect that draft and the workflow logs; do not mutate assets of an already published version. Publish a new version for fixes. Release tags and assets are treated as immutable by convention.

Release assets:

- `Vixl-Setup-VERSION-windows-x64.exe` — installer for people.
- `vixl-VERSION-windows-x64.zip` — complete runtime used by the updater.
- `vixl-update.json` — protocol/platform/version, asset filename, SHA-256 and byte size.
- `SHA256SUMS.txt` — checksums of Windows release artifacts.
- Python wheel and source distribution — optional pip/developer installs.

An update trusts HTTPS and access control of the official GitHub repository. The manifest and artifact have the same trust root; checksums detect corruption or mismatched downloads but do not defend against compromise of the repository's release permissions. A separate signed-manifest trust system and Authenticode signing are future hardening options.
