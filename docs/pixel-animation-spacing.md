# Spacing checks and pixel animation (0.9.0)

## Check the spacing you intended

Spacing analysis is opt-in. Vixl does not assume every object in a document should be evenly spaced.

```bash
# Equal edge-to-edge gaps between these siblings, allowing one pixel of rounding.
vixl spacing --targets heading body footer --axis vertical --tolerance 1

# Specifically compare the space above and below body.
vixl spacing --around body --before heading --after footer --axis vertical --tolerance 0

# Require each gap to be 24 pixels; fail the command if the intention is not met.
vixl spacing --targets first second third --axis horizontal --expected 24 --tolerance 1 --check
```

Results include each pair's stable IDs/names, exact gap in pixels, overlap flags, cross-axis overlap, minimum/maximum/mean gap, spread, and `passed`. A negative gap is overlap and always fails. For equal spacing, the largest gap minus the smallest must be within `tolerance`; for an expected spacing, every gap must be within tolerance of `expected`. `equal` is `null` when only one gap is measured. Normal measurement exits successfully even on a mismatch; `--check` returns the structured `spacing_mismatch` error with all measurements and a nonzero exit code.

The targets must be distinct visible siblings. Lists are sorted by position along the requested axis, accounting for unequal object sizes. The `before/around/after` form preserves and validates that explicit order. Bounds use resolved constraints and transformed geometry, excluding shadows/glows. Gaps inside groups use local coordinates; rotated objects use their axis-aligned bounds. A cross-axis overlap of zero is reported for context, not treated as an error. `--artboard` and `--comp` inspect a render variant without changing the document. An artboard's hidden targets cannot be checked.

Python: `project.measure_spacing(targets=[...], axis="vertical", expected=24, tolerance=1)` or `project.measure_spacing(around="body", before="heading", after="footer")`. REST: POST `/spacing` with the same options. MCP: `vixl_measure_spacing`. Use `align` or `distribute` when you actually want to change spacing; measurement never edits the document.

## Make a compact pixel sprite

```bash
vixl new 16x16 --background transparent -o coin.vixl
vixl pixel-art --name coin --width 16 --height 16 --palette '{".":"transparent","g":"#ffc44d","s":"#9c5f22","w":"#fff3bd"}'
vixl pixel-draw coin rect 4 3 --width 8 --height 10 --color s
vixl pixel-draw coin rect 5 4 --width 6 --height 8 --color g
vixl pixel-draw coin line 6 5 --x2 9 --y2 5 --color w
vixl pixels coin
vixl export coin-large.png --scale 8 --sampling nearest
```

A pixel layer stores a small grid of single-character palette indices instead of image bytes. `pixels` returns just the grid, palette, native dimensions and layer ID/name. An agent can read or replace a 16×16 sprite as sixteen short strings. Create a complete pattern in one operation:

```json
{"type":"pixel-art","name":"spark","rows":[".w.","www",".w."],"palette":{".":"transparent","w":"#ffffff"},"x":6,"y":1}
```

Grids are 1–256 pixels per axis with 1–94 printable non-space ASCII palette symbols; every cell must have a palette entry. Palette colors can use `@swatch` or `${variable}`. Without a palette, `.` is transparent and `#` is black. Blank grids use `.` by default; pass `--background SYMBOL` with a custom palette. Explicit rows supply their own dimensions/background and cannot be combined with width/height/background.

`pixel-draw` tools:

- `pixel X Y --color SYMBOL`: set one cell.
- `line X Y --x2 X --y2 Y --color SYMBOL`: one-pixel-wide integer line, including both endpoints.
- `rect X Y --width W --height H --color SYMBOL`: filled rectangle, exactly W×H cells.
- `fill X Y --color SYMBOL`: flood-fill connected cells of the original palette index using four neighbors.

Drawing coordinates refer to the native grid, even after resizing or positioning the layer. Out-of-bounds edits fail atomically. `pixel-palette NAME --colors '{"g":"#ffdd66"}'` updates all cells with that index. Ordinary layer operations such as duplicate, move, flip, resize, mask, and effects still work. Pixel layer transforms use nearest-neighbor sampling; use integer display sizes and 90° rotations for uniform blocks. Filters/styles can intentionally soften pixels. Final ordinary exports default to smooth sampling for compatibility, so specify `--sampling nearest` when enlarging pixel artwork.

Python: `project.inspect_pixels(target)`. REST: GET `/pixels/{target}`. MCP: `vixl_pixels_inspect`; edits use `vixl_operations_apply` with `pixel-art`, `pixel-draw`, and `pixel-palette`.

## Save and export animation frames

```bash
vixl frame-save idle --duration 150
vixl pixel-draw coin pixel 5 4 --color w
vixl frame-save glint --duration 100
vixl frame-apply idle
vixl pixel-draw coin pixel 10 10 --color w
vixl frame-save glint-low --duration 100
vixl animation
vixl animation-set --order idle glint glint-low --loop 0
vixl export-animation --out coin.gif --format gif --scale 8
vixl export-animation --out coin.apng --format apng
vixl export-animation --out coin-sheet.png --format sheet --columns 3
```

Frames are named snapshots of the current editable scene, including palette, variables, styles, masks and geometry, while reusing embedded image assets. Later edits do not change saved frames. `frame-save` creates a frame or replaces the frame with that name in place; omitted duration defaults to 100 ms for a new frame and preserves an existing duration. `frame-apply` restores a frame for editing while keeping the full animation library. `frame-delete NAME` removes a frame. These operations autosave, participate in transactions and support undo/redo.

Animation is intentionally small: at most 256 frames, each with a canvas no larger than 256×256, all the same size. Durations are 10–60,000 ms in multiples of 10 so GIF and APNG timings agree. Linked files must be embedded before capture. There is no interpolation, onion skin, audio track or timeline GUI. The loop count is the number of additional repetitions after the first play; zero means infinite. Both exports encode that same meaning, despite GIF/APNG's different loop conventions.

`animation` / `vixl_animation_inspect` list names, dimensions, durations and total duration without returning full snapshots. In MCP compact operation results, saving a frame returns changed frame names/timing, not a duplicate scene. `vixl_animation_preview(name, scale=1)` previews a saved frame at its native size by default. Python offers `project.render_frame(name, scale=1)` and `project.inspect_animation()`. REST offers GET `/animation` and GET `/animation/frame/{name}?scale=1`.

GIF and APNG export the sequence and timing. GIF uses up to 255 opaque palette colors per frame, no dithering, and an alpha threshold of 128 for its binary transparency; APNG preserves RGBA. Encoders may combine identical consecutive frames while retaining their duration. A sprite sheet preserves every named frame, accompanied by a same-stem JSON file with frame rectangles and durations for game engines. `--columns` controls sheet layout; its default is a roughly square grid. Empty cells remain transparent.

Export scaling is integer 1–32 with nearest-neighbor sampling. Pixel budgets apply to the entire scaled sequence and the sheet canvas before allocation. Existing output files are never overwritten. Exporting does not change the document. Python: `project.export_animation(path, format="sheet", scale=1, columns=3)`. MCP: `vixl_export_animation` writes inside the configured workspace. Ordinary PNG export via `vixl_export_file` also accepts `sampling="nearest"`.

Run `python examples/build_sprite.py --output DIR` for an editable animated potion, GIF/APNG previews and a game-ready sprite sheet.
