# Changelog

## 0.7.0

- Add a per-user Windows installer with bundled Python, font, REST and MCP dependencies.
- Register a stable `pix` command in the Windows user PATH; uninstall without removing user projects.
- Check published stable GitHub releases in the background once per day when Pix starts.
- Verify downloaded runtime checksums, validate archive paths, and health-check side-by-side runtimes before activation.
- Preserve existing sessions and the previous runtime; add manual check/update, opt-out/status, and rollback commands.
- Build installer/update/Python artifacts and publish complete GitHub releases from matching version tags.
- Add Python 3.14 CI and native Windows installer/update/uninstall tests.

## 0.6.0

- Initial programmable image engine with editable projects, CLI/shell, automation, AI provider adapters, REST, and MCP.
