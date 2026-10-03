# Changelog

## 0.10.0

- Rename the application to Vixl throughout: `vixl` CLI, `vixl-engine` distribution, `vixl` Python API, and `VixlError`.
- Use `.vixl` documents, `.vixlscript` scripts, `vixl_*` MCP tools, `VIXL_*` environment variables, and Vixl configuration/session paths.
- Brand Windows installers, bundled executables, update manifests, release assets, repository links, documentation, and examples as Vixl.
- Start a distinct Windows installation identity; no legacy command, import, or file-format compatibility aliases are provided.

## 0.9.0

- Add opt-in spacing analysis for equal gaps, expected distances and balanced space before/after an object, with tolerances and structured measurements.
- Add compact palette-indexed pixel layers, integer pixel/line/rectangle/flood-fill tools, named animation frames with timing, and nearest-neighbor GIF/APNG/sprite-sheet export.
- Expose compact pixel/frame inspection and spacing tools through CLI, Python, REST and typed MCP tools; keep frame-save responses free of full snapshots by default in MCP.

- Add editable design operations: groups/clipping, procedural shapes, layer styles, linked typography and swatches, frames, repeats/blends, guides/grids, pathfinder and symbols.
- Add artboards, CSV data-set rendering, layer comps and multi-scale screen exports.
- Add richer gradients, adjustment layers, histogram-based automatic corrections, named 3D LUTs, text box/warp/polyline layout, and read-only pixel/histogram/contrast measurements.
- Expose shared operations through CLI/Python/REST/MCP and AI plans, plus provider-backed Remove, Content-Aware Fill and Select Subject.
- Rebuild the example poster with one repeated stripe clipped to a live ellipse.

## 0.8.0

- Expose canonical operation schemas directly in MCP tools/list, including required fields and enums; no resource fetch needed.
- Return changed layer fields by default; opt into full snapshots with `detail: "full"`. Paginate MCP history and allow inspection of one layer.
- Bound MCP PNG previews to 1024×1024 and 1 MiB by default, with explicit dimension/byte controls and aspect-preserving resizing.
- Add workspace browsing, document creation/opening, path-based image import, and full-resolution file export. Start with `vixl mcp --workspace DIR` without an existing project.
- Replace MCP CLI-string AI dispatch with typed tools for generation, background removal, selection, planning, analysis, upscale, regeneration, and outpainting.
- Keep service projects loaded between calls, detect external file changes, and serialize edits across threads/processes without losing updates. Discard cached state after failed operations/saves.
- MCP migration: `vixl_import_image` now accepts `path` instead of `image_base64`; `vixl_ai` is replaced by the typed `vixl_ai_*` tools. Existing `--project FILE mcp` launch configurations still work, with the project's parent as workspace. CLI/Python AI interfaces remain compatible.

## 0.7.0

- Add a per-user Windows installer with bundled Python, font, REST and MCP dependencies.
- Register a stable `vixl` command in the Windows user PATH; uninstall without removing user projects.
- Check published stable GitHub releases in the background once per day when Vixl starts.
- Verify downloaded runtime checksums, validate archive paths, and health-check side-by-side runtimes before activation.
- Preserve existing sessions and the previous runtime; add manual check/update, opt-out/status, and rollback commands.
- Build installer/update/Python artifacts and publish complete GitHub releases from matching version tags.
- Add Python 3.14 CI and native Windows installer/update/uninstall tests.

## 0.6.0

- Initial programmable image engine with editable projects, CLI/shell, automation, AI provider adapters, REST, and MCP.
