---
name: vixl
description: Create and edit layered, editable images with Vixl (the `vixl` CLI, its MCP server, REST API, or Python API). Use whenever a task involves making or changing a poster, social graphic, thumbnail, banner, photo edit, template, CSV-driven image variants, pixel-art sprite or GIF/sprite-sheet animation, or checking an image's layout, spacing, contrast or dimensions — and whenever `vixl_*` MCP tools, `.vixl` files, `.vixlscript` files, or the `vixl` command are available or mentioned. Covers every operation type, CLI command, MCP tool, REST route, AI-provider feature, and the verify-by-preview loop.
---

# Vixl for agents

Vixl is a headless, programmable image-document engine. A `.vixl` file is a ZIP holding a layer
stack (raster images, text, shapes, groups, pixel grids, adjustment layers…), effects, masks,
constraints, variables, styles, artboards, animation frames and a full branching history. Every
interface — CLI, `.vixlscript`, Python, REST, MCP, AI planner — compiles to the **same canonical
JSON operations**, so anything you learn in one transfers to the others.

Key properties to rely on:

- **Everything stays editable.** Text is text until `rasterize`; effects are a stack you can
  disable/edit/remove; masks and styles are attachments. Prefer editing over re-creating.
- **Batches are atomic.** A list of operations either fully applies or changes nothing.
- **Every successful edit autosaves** and is undoable (CLI and MCP).
- **Layers are addressed by unique name or immutable ID** (`lyr_…`). IDs survive renames;
  prefer them in long sessions. Omitting `target` uses the *active* layer (the last one added/selected).
- **Coordinates are integer-ish pixels, origin top-left**, layers ordered bottom→top.
- **Errors are structured and fail loudly** (`layer_not_found`, `invalid_operation`,
  `validation_failed`, `resource_limit`, `spacing_mismatch`…). Nothing fails silently — except
  the one gotcha listed below.

## 1. Pick the interface

| You have… | Use | Reference |
| --- | --- | --- |
| `vixl_*` tools in your tool list | **MCP** — typed tools, compact diffs, inline previews | [references/mcp-rest-python.md](references/mcp-rest-python.md) |
| A shell with `vixl` on PATH | **CLI** (add `--json` for machine errors) or `vixl apply ops.json` | [references/cli.md](references/cli.md) |
| Python with `vixl` importable | `from vixl import Project` | [references/mcp-rest-python.md](references/mcp-rest-python.md) |
| A running `vixl serve` | REST (`POST /operations`, `GET /render`) | [references/mcp-rest-python.md](references/mcp-rest-python.md) |

Whatever the interface, the edit payload is the operation list in
[references/operations.md](references/operations.md). Load that file before composing
non-trivial batches. Ready-made multi-step workflows are in [references/recipes.md](references/recipes.md).
AI-provider features (generate, inpaint, segmentation, OCR, plan) are in
[references/ai.md](references/ai.md).

Check availability first: `vixl --version` (CLI) or call `vixl_workspace_list` (MCP). Install from
source with `pip install -e ".[server,mcp]"` (Python ≥ 3.11); Windows users use the installer.
Set `VIXL_NO_UPDATE=1` in automation so the Windows auto-updater never runs mid-task.

## 2. The core loop (do this every time)

1. **Orient** — inspect before editing. MCP: `vixl_document_inspect()` returns a compact summary
   (one line per layer with `bounds`; `detail="full"` for every field, `target=` for one layer).
   CLI: `vixl -p F.vixl inspect --json` / `vixl layers`. Note canvas size, layer names/IDs and
   bounds (`[x, y, width, height]` after constraints).
2. **Plan a batch** of canonical operations. Group related edits into one atomic call.
3. **Dry-run anything risky** (`dry_run: true` / `vixl apply ops.json --dry-run`). It returns the
   changes without saving.
4. **Apply.** Read the returned change summary — new layers come back with ID, name, type and
   `bounds`; changed layers list only their new values. If it contains `normalized`, note the
   canonical spelling it reports and use that next time.
5. **Check without looking:** `vixl_check` / `vixl check` reports content cut off by the canvas,
   overlapping text, low WCAG contrast, safe-area or reserved-zone violations (`safe_area="5%"`,
   `avoid=[[x,y,w,h]]`) and text too small at thumbnail width. It lists only problems.
6. **Look at the result.** MCP: `vixl_render_preview()` returns an image (≤1024 px, ≤1 MiB by
   default; `region=[x,y,w,h]` zooms in). `vixl_render_compare()` shows previous vs current.
   CLI: `vixl render --out /tmp/preview.png` then view the file. Never declare a visual
   task done without looking.
7. **Measure, don't eyeball,** when precision matters: `vixl_measure` / `vixl info` (colors,
   WCAG contrast of a text layer), `vixl_measure_spacing` / `vixl spacing` (gaps),
   `vixl_validate` / `vixl validate` (bounds, aspect ratios, assertions).
8. **Fix with targeted edits or `undo`**, then **export** (`vixl_export_file` / `vixl export`).

## 3. Minimal examples

**MCP**

```text
vixl_workspace_list()                                   # see files; paths are relative to the workspace
vixl_document_create(path="poster.vixl", width=1080, height=1350, background="#101828")
vixl_import_image(path="photos/portrait.jpg", name="portrait")
vixl_operations_apply(operations=[
  {"type":"resize","target":"portrait","width":1080},
  {"type":"align","target":"portrait","alignment":"top"},
  {"type":"gradient","name":"fade","width":1080,"height":600,"y":750,
   "stops":[{"offset":0,"color":"#10182800"},{"offset":1,"color":"#101828"}]},
  {"type":"text","name":"title","text":"AFTER HOURS","size":120,"color":"#f6ecd7"},
  {"type":"constrain","target":"title","constraints":{"center-x":"canvas.center-x","bottom":"canvas.bottom-120"}},
  {"type":"layer-style","target":"title","name":"drop-shadow","settings":{"blur":8,"dy":6,"opacity":0.6}}
])
vixl_check(safe_area="5%")                              # overlap, contrast, bounds, legibility
vixl_render_preview()
vixl_export_file(path="poster.png")
```

**CLI** (quote `#` colors; every edit autosaves)

```bash
vixl new 1080x1350 --background '#101828' -o poster.vixl
vixl -p poster.vixl add photos/portrait.jpg --name portrait
vixl -p poster.vixl resize portrait --width 1080
vixl -p poster.vixl text add 'AFTER HOURS' --name title --size 120 --color '#f6ecd7'
vixl -p poster.vixl constrain title --center-x canvas --bottom canvas.bottom-120
vixl -p poster.vixl layer-style title drop-shadow --settings '{"blur":8,"dy":6,"opacity":0.6}'
vixl -p poster.vixl render --out preview.png
vixl -p poster.vixl export poster.png
```

Or put the operations in a file and run `vixl -p poster.vixl apply ops.json` (atomic, one undo step).

## 4. Rules and gotchas that save retries

- **Always pass the project explicitly in the CLI** (`-p file.vixl`). `vixl open` stores a
  per-directory default in `.vixl-session.json`, which is fragile across concurrent work.
- **CLI edit output is verbose** (full before/after layer snapshots). Pipe to `> /dev/null` or
  read only `success`; use `inspect LAYER` afterwards. MCP/REST default to `detail:"compact"`.
- **Errors are structured.** MCP tool errors and CLI `--json` failures are
  `{"error": CODE, "message", "field", "operation_index", "operation_type", "allowed"?, "suggestions"?}`.
  Fix the named operation and field (try a suggestion) and retry; a failed batch changed nothing.
- **Common spellings are accepted and reported** under `normalized`: `rect`/`circle`/`triangle`,
  `font_size`, `fill`/`color`, camelCase keys, `drop_shadow`, CSS `rgba(…, 0.5)`, blur `radius`.
  `x`/`y` take pixels, `"center"` or `"50%"`; `width`/`height` take pixels or `"25%"` (of the canvas,
  or of the parent group).
- **Blur strength is `amount`** (`{"type":"effect","name":"blur","amount":4}`); `radius` on blur is
  read as `amount`. `radius` is its own field for `vignette` (0–1.4) and `rounded-rectangle` corners.
- **Opacity is 0–1; values from 1 to 100 are read as a percentage** in every interface (`50` = 0.5).
- **Scale `value` is a factor** (`0.8`); CLI accepts `80%`.
- **Absolute `move` and `align`/`distribute` clear constraints** on that layer. Use `constrain`
  when layout should survive canvas resizes, artboards or text changes; use `align` for a one-off.
- **One constraint per axis** (e.g. `left` *or* `center-x` *or* `right`). Anchors: `canvas`, a layer
  name/ID, or `guide:NAME`, plus `.left/.right/.top/.bottom/.center-x/.center-y` and `+N`/`-N`.
- **Effects capture the selection that exists when they are added.** Clear it
  (`{"type":"select","shape":"none"}`) before adding whole-layer effects.
- **Text auto-sizes** to its rendered bounds; an explicit `resize` turns that off, editing text turns it back on.
  For wrapping use `text-layout` with `width`/`height` (optionally `fit: true`).
- **Variables:** `${name}` works in text, colors, gradient fills and image-asset IDs. Undefined
  variables are errors. Swatches are `@name` in color fields.
- **Through MCP/REST, operation `path`, `linked` and `font` fields are rejected.** Import files with
  `vixl_import_image(path=…)` or, when you only have the bytes, `vixl_import_image(data_base64=…)`
  (MCP) or `POST /assets` (REST); reuse already-embedded images via `asset` IDs.
- **Several documents can be open over MCP.** Pass `document="other.vixl"` to any tool to address one
  without changing the active document.
- **MCP paths are relative to the server's `--workspace`**, must stay inside it, and subdirectories
  must already exist. Exports refuse to overwrite unless `overwrite: true`, and never overwrite `.vixl`.
- **CLI `new` and `export`/`render --out` refuse existing destinations** in batch/data/animation
  workflows; choose fresh names.
- **Pixel art:** export with `--sampling nearest` (`sampling:"nearest"` in MCP) or it will be smoothed.
- **AI features need a configured provider** (`~/.config/vixl/providers.json`). There is no
  offline fallback; if no provider is configured, say so instead of retrying.
- **Limits:** 40 MP per canvas/layer, 16 384 px per side, 512 layers, 256 effects/layer,
  1 000 operations per batch. History keeps 2 000 revisions; older unreferenced ones are squashed
  automatically, so long sessions never lock. Animation frames ≤ 256×256, ≤ 256 frames.
- **Not supported** (don't promise them): SVG/Bézier editing, brushes, skew/perspective, CMYK/ICC,
  RAW, PSD/XCF import, full animation timelines, GUI.

## 5. Feature map (where to look)

| Need | Operations / commands |
| --- | --- |
| New layers | `add` (image), `solid`, `gradient` (linear/angled/radial, multi-stop), `text`, `shape`, `frame` (image box with fill/fit), `pixel-art`, `adjustment`, `symbol-instance` |
| Transform | `move`, `resize`, `scale`, `rotate`, `flip`, `crop`, `opacity`, `blend`, `hide`/`show` |
| Stacking | `raise`, `lower`, `top`, `bottom`, `reorder` (`above`/`below`), `group`/`ungroup`, `clip` |
| Layout | `align` (to canvas/selection/layer), `distribute`, `constrain`/`unconstrain`, `guide`, `grid`, `canvas` (resize/preset), `artboard` |
| Color & filters | 25 built-in effects (brightness … auto-contrast), `effect-set/enable/disable/remove`, `lut` + `lookup`, `preset-save/apply` |
| Selections & masks | `select` (rect/ellipse/color/alpha/all/none/invert, add/subtract/intersect, feather), `mask` (create/from-selection/import/invert/enable/disable/delete) |
| Typography | `text`, `text-set`, `text-layout` (box, fit, warp, path), `style-define`/`style-apply`, `swatch` |
| Decoration | `layer-style` (drop-shadow, stroke, outer-glow, color-overlay, gradient-overlay), `repeat`, `repeat-blend`, `pathfinder` |
| Templates | `variable`, `replace-contents`, `comp-save`/`comp-apply`, CSV `render --data`, `export-screens` |
| Pixel art & animation | `pixel-art`, `pixel-draw`, `pixel-palette`, `frame-save/apply/delete`, `animation-set`, `export-animation` |
| History | undo/redo, checkpoint, branch, checkout, compare, transactions |
| QA | check (bounds/overlap/contrast/safe area/legibility), inspect, measure (sample/histogram/contrast), spacing, validate/assert, render preview (zoomable), compare revisions |
| AI (provider) | generate/inpaint/img2img, extend (outpaint), upscale, regenerate, background-remove, select object/subject, remove, content-aware-fill, describe/detect/OCR, natural-language plan |

When unsure of a field, get the authoritative schema: MCP embeds it in `vixl_operations_apply`'s
input schema (also resource `vixl://operations`); CLI `vixl schema`; REST `GET /schema`; per-command
syntax via `vixl COMMAND --help`.
