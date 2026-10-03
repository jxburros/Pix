# Changelog

## 0.8.0

- Expose canonical operation schemas directly in MCP tools/list, including required fields and enums; no resource fetch needed.
- Return changed layer fields by default; opt into full snapshots with `detail: "full"`. Paginate MCP history and allow inspection of one layer.
- Bound MCP PNG previews to 1024×1024 and 1 MiB by default, with explicit dimension/byte controls and aspect-preserving resizing.
- Add workspace browsing, document creation/opening, path-based image import, and full-resolution file export. Start with `pix mcp --workspace DIR` without an existing project.
- Replace MCP CLI-string AI dispatch with typed tools for generation, background removal, selection, planning, analysis, upscale, regeneration, and outpainting.
- Keep service projects loaded between calls, detect external file changes, and serialize edits across threads/processes without losing updates. Discard cached state after failed operations/saves.
- MCP migration: `pix_import_image` now accepts `path` instead of `image_base64`; `pix_ai` is replaced by the typed `pix_ai_*` tools. Existing `--project FILE mcp` launch configurations still work, with the project's parent as workspace. CLI/Python AI interfaces remain compatible.

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
