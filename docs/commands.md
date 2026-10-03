# Command reference

See [spacing checks and pixel animation](pixel-animation-spacing.md) for the 0.9.0 tools and API examples.

See [design tools and template production](design-tools.md) for groups, clipping, shapes, styles, artboards, CSV rendering, measurements, and the other design operations.

Global options can appear before or after the command: `--project FILE` / `-p FILE`, `--json`, `--allow-linked`, `--plugins`, `--max-pixels N`, `--version`. The default project is stored in the current directory's `.vixl-session.json`. Use explicit paths in CI and concurrent workflows. `vixl COMMAND --help` prints syntax for editing commands.

## Installed application updates

For the Windows installer edition, these commands work without an open project:

| Command | Behavior |
| --- | --- |
| `update --check` | Check for a newer published stable release without downloading the runtime |
| `update` | Download, verify and stage the latest stable runtime for the next launch |
| `updates status` | Show current/previous/pending version, automatic-update setting and last error |
| `updates off` / `updates on` | Persist the preference; off also clears a queued activation |
| `update --rollback` | Select the previous runtime for future launches and turn automatic updates off |

Set `VIXL_NO_UPDATE=1` to suppress both automatic checks and pending activation for a process (useful in CI). Python/pip installations are never modified by this updater. See [releases](releases.md).

## Documents and output

| Command | Behavior |
| --- | --- |
| `new 1920x1080 -o poster.vixl --background '#111111'` | Create a project; refuses existing files |
| `open poster.vixl` | Select an existing project for this directory |
| `save [copy.vixl]` | Save, or save as a new selected project |
| `status`, `inspect [LAYER]`, `describe`, `layers` | JSON state, including resolved bounds |
| `manifest`, `dependencies`, `reproduce --check` | List assets/fonts/providers; check current renderability |
| `render [project.vixl] --out preview.png --set title=Hello` | Render without persisting overrides |
| `export image.jpg --quality 90 --scale 2x` | Export, preserving the editable document |
| `export image.png --profile discord` | Contain in 512×512; Instagram contains in 1080×1080; print emits RGB/RGBA TIFF at 300 DPI |
| `canvas resize 1080x1080`, `canvas preset story` | Resize and reflow constraints |
| `canvas background transparent` | Set the canvas base color |

Exports support PNG, JPEG, WebP, TIFF; AVIF depends on the installed Pillow codec. JPEG flattens transparency onto white, configurable with `--background`. Explicit `--format` overrides a profile or filename. Profiles **contain**, not crop or stretch; `print` does not imply CMYK or color-managed prepress.

## Layers and editing

Layers are ordered bottom to top. A target is a unique layer name or immutable ID. Most editing commands accept an omitted target and use the active layer.

```bash
vixl layer add image.png --name hero
vixl add logo.png --name logo --linked
vixl select-layer hero
vixl layer rename hero portrait
vixl layer duplicate portrait copy
vixl layer hide copy
vixl layer show copy
vixl layer remove copy
vixl layer raise portrait
vixl layer lower portrait
vixl layer top logo
vixl layer bottom portrait
vixl layer reorder logo --above portrait
vixl move portrait 100 200
vixl move portrait --x 100 --y 200
vixl move x +20
vixl scale portrait 80%
vixl resize portrait 800x600
vixl resize portrait --width 800
vixl rotate portrait 15
vixl flip portrait horizontal
vixl crop portrait 0 0 300 400
vixl opacity portrait 0.75
vixl blend portrait multiply
vixl align logo top-right --margin 40
```

`layer` is an optional namespace. `rm` aliases remove and `mv` aliases move. Rotation is clockwise, expands the layer bounds, and anchors the expanded bounding box at its x/y position. Crop coordinates refer to the original embedded raster. Resize with one dimension preserves aspect ratio; with two, it stretches. Numeric scale values are factors; `80%` is `0.8`. The CLI accepts opacity `75` as 75%; canonical JSON always requires 0–1.

Alignment supports center, center-x/y, left/right/top/bottom and corner pairs. Absolute moves and alignment clear constraints. `move x +20` and `--relative` add offsets.

```bash
vixl solid --name panel --width 400 --height 200 --color '#26344e'
vixl gradient --name sky --start '#152641' --end '#635e83' --direction vertical
vixl text add 'Hello' --name title --size 96 --font DejaVuSans.ttf --color white --x center --y 120
vixl text title --text 'Good evening' --size 80 --align center
vixl text title --stroke-width 2 --stroke-color black
vixl rasterize title
```

Text remains editable until rasterized. Custom `--font /path/to/font.ttf` imports and embeds a font. Other font names use Pillow's system-font lookup. Font substitution is never silent. Multiline text is supported; text wrapping, shaping guarantees for every script, and font-family style resolution are not implemented.

## Selections, masks, effects

```bash
vixl select rect 0 0 500 300
vixl select ellipse 100 100 200 200 --mode add --feather 5
vixl select color '#ffffff' --tolerance 15
vixl select alpha portrait
vixl select all
vixl select invert
vixl select none
vixl mask create portrait
vixl mask from-selection portrait
vixl mask import portrait --path mask.png
vixl mask invert portrait
vixl mask disable portrait
vixl mask enable portrait
vixl mask delete portrait
```

Selection combination modes: replace, add (maximum), subtract, intersect (minimum). White means selected/visible; black means unselected/hidden. No selection means effects cover the whole layer. Each effect captures the selection as it existed when the effect was added; clearing the selection does not remove that boundary. Effect selection masks use canvas coordinates. Layer masks are mapped onto the transformed layer's bounding box and move/resize with it.

```bash
vixl brightness portrait +20
vixl contrast -10
vixl saturation +15
vixl hue 30
vixl exposure 0.5
vixl gamma 1.1
vixl temperature 300
vixl tint 10
vixl shadows 15
vixl highlights -10
vixl blur 8
vixl sharpen 2
vixl grayscale
vixl invert
vixl posterize 6
vixl threshold 128
vixl filter noise --amount 0.08 --seed 42
vixl filter vignette --radius 0.7 --strength 0.4
vixl filter levels --black 15 --white 240
vixl effects portrait
vixl effect disable portrait 1
vixl effect set portrait 2 --amount 20
vixl effect remove portrait 3
```

Effect indices start at 1; stable effect IDs also work. Curves use JSON `points: [[0,0],[128,160],[255,255]]`. Brightness/contrast/saturation are percentages relative to neutral; exposure is stops; gamma must be positive; hue is degrees; sharpen is a factor (1 is neutral); noise/grain are 0–1 standard deviations; posterize is 1–8 bits. Temperature/tint and shadows/highlights are simple channel/tonal adjustments, not camera-calibrated or color-managed controls. Noise is seeded (default 0).

Blend modes: normal, multiply, screen, overlay, darken, lighten, difference, add, subtract.

## Layout, templates, validation

```bash
vixl variable set title 'Night Shift'
vixl variable delete unused
vixl constrain title --center-x canvas --below portrait 60
vixl constrain logo --right canvas.right-40 --top canvas.top+40
vixl unconstrain logo
vixl render --set title='Late Edition' --out variant.png
vixl assert canvas.width == 1920
vixl assert layer.logo.exists
vixl assert layer.logo.bounds within canvas
vixl assert text.title.font-size '>=' 48
vixl validate instagram-post
vixl validate --rules rules.json
```

A constraint uses `canvas` or a layer plus `.left`, `.right`, `.top`, `.bottom`, `.center-x`, `.center-y`, optionally followed by a numeric `+offset` or `-offset`. One constraint per axis is supported. Cycles and dangling references fail atomically. Layer references become stable IDs, so renames do not break them. Delete dependents' constraints before deleting their target.

Variables use `${name}` interpolation in text, colors, gradient fills, and raster asset identifiers. Asset variables must refer to **embedded asset IDs**; render overrides never load arbitrary files. Text dimensions are recomputed when variables change. Undefined variables fail explicitly.

Validation profiles: instagram-post / instagram-square (1:1; Instagram also checks PNG under 8 MB), story (9:16), youtube-thumbnail (16:9). All check layer bounds. Text under 24 px is a warning. Rules files are JSON arrays of assertion strings. Comparisons support `==`, `!=`, `>`, `<`, `>=`, `<=`; quote shell operators. Assertions are parsed, never evaluated as Python.

## Scripts, presets, history

A `.vixlscript` contains one editing command per line; blank lines and `#` comments are allowed. Quote colors and text. It is a bounded Vixl language, not a shell or Python. Files referenced in scripts resolve relative to the script. Project lifecycle, exports, AI calls, and history commands are invoked outside scripts. Use shell scripts or the Python API to orchestrate those steps.

```bash
vixl run cleanup.vixlscript
vixl apply operations.json --dry-run
vixl each layer --type raster --name 'card-*' -- saturation -10
vixl preset save gritty portrait
vixl preset show gritty
vixl preset apply gritty other --set noise=0.03
vixl undo 3
vixl redo
vixl checkpoint clean
vixl branch vivid
vixl checkout clean
vixl history
vixl branches
vixl compare vivid clean --out comparison.png
```

Presets save the active/target layer's complete effect stack. Applying one assigns fresh effect IDs and captures the current selection. Branches name movable tips; checkpoints are fixed. Checking out a checkpoint detaches history; create a branch to name subsequent work. Undo/redo moves the current branch tip; alternate history nodes remain available by ID. Transactions allow provisional edits across processes and commit as one undoable history entry. They do not hide provisional state from other clients of the same project.

`batch` refuses output collisions and existing destinations, reports each input's result, and exits nonzero if any fail. Earlier successful outputs remain if a later item fails.
