# Design tools and template production

Vixl is a headless application designed for autonomous AI agents; humans can use the same interfaces.

All edits below are canonical operations, available through Python `Project.apply`, CLI commands/scripts, REST `/operations`, and MCP `vixl_operations_apply`. `vixl schema` describes their fields. Successful edits participate in atomic batches, dry runs, undo/redo, transactions, and `.vixl` persistence. Existing documents remain readable. New design documents require this version of the engine.

## Groups, clipping, shapes, and repeats

```bash
vixl shape ellipse --name sun --width 640 --height 640 --x 564 --y 165 --fill '#e8885c'
vixl layer-style sun gradient-overlay --settings '{"start":"#e8885c","end":"#4853a4"}'
vixl shape rectangle --name stripe --width 700 --height 6 --x 534 --y 190 --fill '#152235'
vixl repeat stripe --count 16 --dy 37 --dh 1
vixl group stripes stripe
vixl clip stripes sun
```

The stripe stays one editable layer. Repeat counts include the original; `dx/dy` are nonnegative offsets between copies and `dw/dh` change each copy's size. `repeat-blend stripe --count 16 --dy 37 --end '{"height":21,"fill":"#4853a4"}'` interpolates size and RGBA color to the last copy. Reapplying repeat replaces its settings; `--count 1` leaves only the original. Counts are bounded to 512 and all resulting dimensions are checked before allocation.

Shapes support `rectangle`, `rounded-rectangle`, `ellipse`, `polygon`, `star`, and `line`; options include `--fill`, `--stroke`, `--stroke-width`, `--radius`, `--sides`, and star `--inner-radius` (0.01–1). Geometry is retained and redrawn at the layer's current size with bounded antialiasing. Version 0.11.0 adds named shape shortcuts and editable single-contour Bézier paths, plus SVG export of simple geometry. See [design resources and vector export](agent-resources.md) for syntax and raster fallback limits.

Groups preserve member stacking order and use local child coordinates. Moving, hiding, masking, styling, or changing the opacity of a group affects its combined contents once. Groups nest to 16 dependency levels and duplicate with independent child IDs; edits address children by their existing names or IDs. Group bounds are fixed to the union of member bounds at creation, and resizing transforms the combined group raster. Content moved outside those bounds is cropped. Constraints between layers and clipping references must stay among siblings; `canvas` inside a group means the group's local content box. Grouping nonadjacent layers places the group at the highest selected slot.

`clip TARGET BASE` multiplies TARGET's rendered alpha by the sibling BASE's alpha. It follows base transforms and masks, works on groups, and rejects cycles. The base remains an ordinary visible layer. `clip TARGET --release` removes the relationship. `ungroup NAME` restores local members to their parent; reset group appearance and transforms first when ungrouping would discard those settings. `remove GROUP` removes its descendants. Reordering always stays among siblings.

## Attached layer styles

```bash
vixl layer-style title drop-shadow --settings '{"color":"#000000","dx":4,"dy":6,"blur":8,"opacity":0.65}'
vixl layer-style title stroke --settings '{"color":"#ffffff","width":2}'
vixl layer-style logo outer-glow --settings '{"color":"#80cfff","blur":12}'
vixl layer-style logo color-overlay --settings '{"color":"@brand"}'
vixl layer-style title drop-shadow --remove
```

Styles are editable settings, one per kind, applied after effects and masks. `enabled` and `opacity` are shared settings. Shadow, glow, and outer stroke sit behind the content; color and gradient overlays recolor it while preserving alpha. Overlays use the visible silhouette's bounding box. Group/layer opacity is applied to the styled result, then it is composited with the selected blend mode. Shadows and glows can extend past the layer's geometric bounds but remain within the parent canvas. Inspection/alignment report geometry bounds, not effect extents. Rasterizing a styled or externally clipped layer requires removing those attachments first.

## Alignment and distribution

```bash
vixl align title left --relative-to logo
vixl align title center-y --targets title logo badge
vixl distribute horizontal title logo badge
vixl distribute vertical first second third --gap 24
```

`align` supports `targets` and `relative_to`: `canvas`, `selection` (the union of the selected bounds), or another sibling's name/ID. Multiple targets default to selection bounds; one target defaults to the canvas. Distribution sorts by current position. Without a gap it preserves the outer edges and computes equal edge-to-edge spacing, accounting for unequal sizes; with a gap it starts at the first layer. It requires at least three siblings. Both commands bake resolved positions and clear constraints on affected layers.

## Named character styles, paragraph styles, and swatches

```bash
vixl swatch brand '#e8885c'
vixl style-define Heading --settings '{"size":80,"color":"@brand","stroke_width":1}'
vixl style-define Caption --kind paragraph --settings '{"align":"center","spacing":8}'
vixl style-apply title Heading
vixl style-apply title Caption --kind paragraph
vixl swatch brand '#78bbdc'
```

Swatch references use `@name` in color fields. Character styles support size, color, stroke width/color; paragraph styles support alignment and line spacing. Named styles remain linked and take precedence over the layer's corresponding local values. Redefining a style or swatch updates all uses on the next render, including constraint measurements. Resource names use letters, numbers, underscores and hyphens (maximum 100 characters).

## Artboards, data sets, and image frames

```bash
vixl artboard square --preset instagram-square
vixl artboard story --preset story
vixl artboard banner --width 1600 --height 600
vixl render --artboard story --out story.png
vixl export-screens --out screens --scales 1 2
```

Artboards are named canvas configurations in one document. They share the editable layer stack and resolve canvas constraints at each board's size. Optional `variables` supply board defaults and `targets` selects top-level layer IDs; absent `targets` means all layers, while an empty stored list shows none. Render overrides take precedence over board variables. `export-screens` writes every board at each scale as `NAME@SCALE x.png` (without the space, e.g. `story@2x.png`); `--artboards square story` selects boards. PNG outputs are staged before publication and existing destinations are rejected. Scaled exports resample the composed raster, as existing Vixl exports do.

```bash
vixl frame --path portrait.jpg --name photo --width 400 --height 500 --fit fill
vixl replace-contents photo --path replacement.jpg
vixl replace-contents photo --fit fit --asset assets/EMBEDDED_HASH.png
```

Frames center and fill/crop or fit/letterbox their boxes. Replacement keeps the layer ID, box, position, transforms, styles, effects and mask. Explicit replacement clears an old source crop, linked-file path, and image-variable binding. Frame imports embed the image in the project. Remote clients use already-imported `asset` IDs instead of paths.

Image variables reference embedded assets during ordinary rendering:

```bash
vixl variable set photo_asset assets/EMBEDDED_HASH.png
vixl replace-contents photo --variable photo_asset
vixl render --set photo_asset=assets/OTHER_HASH.png --out variant.png
vixl render --data rows.csv --out campaign
```

CSV requires unique headers and at least one complete row. Each row becomes render variables and produces `0001.png`, `0002.png`, etc., without mutating the project. Quoted commas, quoted newlines, and UTF-8 BOMs are supported. `--set` overrides row values. Bound image columns may contain an embedded asset ID or a file path relative to the CSV; only this explicit local CSV workflow imports paths. CSVs are limited to 8 MiB and 10,000 rows. All rows are rendered to temporary files before output publication; bad rows leave no partial campaign. Existing outputs are never overwritten. Data rendering also accepts `--artboard` and `--comp`.

Python exposes `project.render(artboard=..., comp=..., variables=...)`, `project.render_data(csv_path, directory, ...)`, and `project.export_screens(directory, scales=(1, 2), ...)`. REST POST `/render` and MCP previews accept `artboard` and `comp`; local-directory batch exports remain CLI/Python operations.

## Measuring the rendered image

```bash
vixl sample 100 150
vixl histogram --region 40 40 300 200
vixl info --region 40 40 300 200 --foreground '#ffffff'
vixl info --target title
```

Measurements return JSON: RGBA/hex point sample, alpha-weighted average RGB, mean alpha, four 256-bin histograms (excluding fully transparent pixels), and optional WCAG luminance contrast minimum/mean/maximum. `--foreground` compares the specified RGBA color against every pixel in the region; transparency composites over `--background white` by default. `--target` uses the actual rendered layer (including nested group children) against the stack below it, including opacity, styles and blending, with antialiased fringe pixels excluded. The target must be visible and drawable. Top-level bounds must be within the canvas; grouped targets measure their visible canvas coverage. Contrast thresholds are 4.5 for normal text and 3 for large text; font size eligibility remains the caller's responsibility.

Use `project.measure(...)`, REST POST `/measure`, or MCP `vixl_measure` for the same read-only results. These are measurements, not a GUI info panel.

## Gradients, adjustments, automatic corrections, and LUTs

```bash
vixl gradient --name sky --direction angled --angle 35 --stops '[{"offset":0,"color":"#152235"},{"offset":0.4,"color":"#b36881"},{"offset":1,"color":"#e8885c"}]'
vixl adjustment warmth --effects '[{"name":"temperature","amount":500},{"name":"contrast","amount":10}]'
vixl auto-tone photo
vixl auto-color photo
vixl auto-contrast photo
```

Gradient directions are `vertical`, `horizontal`, `angled` (0° left-to-right, 90° top-to-bottom), and `radial` (center-to-edge). Supply 2–64 strictly increasing stops at offsets 0–1; start/end remain backward compatible. Transparency interpolates in premultiplied alpha. Gradient overlays use the same fields.

Adjustment layers process the already-composited stack below them in their parent group. They accept built-in effects, opacity, masks and blend modes; layers above are unaffected. Auto Tone stretches channels independently between their visible-pixel 0.5th and 99.5th percentiles; Auto Contrast uses a shared range; Auto Color adds gray-world channel balancing. Alpha is preserved and flat ranges are handled without division by zero.

Named 3D LUTs are embedded, shareable JSON resources:

```json
{"type":"lut","name":"look","size":2,"values":[[0,0,0],[1,0,0],[0,1,0],[1,1,0],[0,0,1],[1,0,1],[0,1,1],[1,1,1]]}
```

This is an identity table. Sizes 2–33 require exactly `size³` normalized RGB triples, with red varying fastest, then green, then blue (cube ordering). `vixl lookup photo look --amount 0.8` attaches the named look, using trilinear interpolation and preserving alpha. Redefining the table updates all uses. Share the `lut` operation through JSON; native `.cube` parsing is not included.

## Comps, text layout, guides, pathfinder, and symbols

```bash
vixl comp-save with-logo
vixl hide logo
vixl comp-save without-logo
vixl render --comp with-logo --out branded.png
vixl comp-apply with-logo
vixl text-layout title --width 600 --height 180 --fit
vixl text-layout title --width 600 --height 180 --warp arc --amount 0.15
vixl text-layout title --width 600 --height 180 --path '[[10,90],[300,20],[590,90]]'
vixl guide left-margin x 64
vixl constrain title --left guide:left-margin.left
vixl grid editorial --columns 3 --rows 2 --margin 64 --gutter 24
vixl pathfinder badge outer inner --mode subtract
vixl symbol logo Brandmark
vixl symbol-instance Brandmark --name footer-logo --x 100 --y 800 --width 100 --height 100
```

Comps capture visibility, position, rotation, opacity, blend, constraints, and layer styles by ID, without duplicating imagery or full document history. New layers are unaffected and deleted IDs are ignored. `render --comp` is read-only; `comp-apply` is an undoable edit.

Text boxes wrap paragraphs and oversized words; `fit` shrinks from the configured font size to fit. Warps are `none`, `arc`, `flag`, and `bulge`, with amounts −1 to 1, applied inside the box. Paths are local pixel polylines: glyphs follow segment tangents and content beyond the path is omitted. This is basic glyph placement, not full shaping/kerning on Bézier paths. Box/warp content is clipped to the box, so allow room for curvature. A new `text-layout` operation replaces the previous settings.

Guides are named absolute x/y positions used in constraint expressions such as `guide:left-margin.left+8`. Grids generate guides `NAME-x1-start`, `NAME-x1-end`, `NAME-y1-start`, etc.; redefining the grid replaces its generated guides. Guides/grids are document metadata, never painted into output, and remain absolute when the canvas changes.

Pathfinder combines procedural shape silhouettes by union, subtraction in target order, or intersection. It retains procedural operand snapshots for resizing, hides the originals, and uses the first operand's fill. It does not rewrite editable vector paths or track subsequent edits to the original operands.

Symbols refer to a drawable master by immutable ID. Instances follow the master's content, styles and effects, with independent placement, size, opacity, blend, visibility and transforms. Group/adjustment/instance masters are excluded. Removing a master still used by instances is rejected atomically; update the master layer normally to refresh its instances.

## Provider-backed editing tools

```bash
vixl select rect 100 100 200 200
vixl ai remove --provider local --as removed-object
vixl ai content-aware-fill --prompt 'Continue the brick wall' --provider local --as filled-wall
vixl ai select-subject --provider vision
```

Remove and Content-Aware Fill call the existing provider's inpainting capability, retain generation provenance, and insert an editable layer masked to the selection. Select Subject calls segmentation and stores the returned mask as the active selection. They use configured providers and make no claim of an offline content-aware algorithm. Provider errors and invalid responses leave the document unchanged. Contract tests use fixtures; live service/model quality requires configured credentials.
