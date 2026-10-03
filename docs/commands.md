# Command reference

See [spacing checks and pixel animation](pixel-animation-spacing.md) for the 0.9.0 tools and API examples.

See [design tools and template production](design-tools.md) for groups, clipping, shapes, styles, artboards, CSV rendering, measurements, and the other design operations.

Global options can appear before or after the command: `--project FILE` / `-p FILE`, `--json`, `--allow-linked`, `--plugins`, `--max-pixels N`, `--version`. The default project is stored in the current directory's `.pix-session.json`. Use explicit paths in CI and concurrent workflows. `pix COMMAND --help` prints syntax for editing commands.

## Installed application updates

For the Windows installer edition, these commands work without an open project:

| Command | Behavior |
| --- | --- |
| `update --check` | Check for a newer published stable release without downloading the runtime |
| `update` | Download, verify and stage the latest stable runtime for the next launch |
| `updates status` | Show current/previous/pending version, automatic-update setting and last error |
| `updates off` / `updates on` | Persist the preference; off also clears a queued activation |
| `update --rollback` | Select the previous runtime for future launches and turn automatic updates off |

Set `PIX_NO_UPDATE=1` to suppress both automatic checks and pending activation for a process (useful in CI). Python/pip installations are never modified by this updater. See [releases](releases.md).

## Documents and output

| Command | Behavior |
| --- | --- |
| `new 1920x1080 -o poster.pix --background '#111111'` | Create a project; refuses existing files |
| `open poster.pix` | Select an existing project for this directory |
| `save [copy.pix]` | Save, or save as a new selected project |
| `status`, `inspect [LAYER]`, `describe`, `layers` | JSON state, including resolved bounds |
| `manifest`, `dependencies`, `reproduce --check` | List assets/fonts/providers; check current renderability |
| `render [project.pix] --out preview.png --set title=Hello` | Render without persisting overrides |
| `export image.jpg --quality 90 --scale 2x` | Export, preserving the editable document |
| `export image.png --profile discord` | Contain in 512×512; Instagram contains in 1080×1080; print emits RGB/RGBA TIFF at 300 DPI |
| `canvas resize 1080x1080`, `canvas preset story` | Resize and reflow constraints |
| `canvas background transparent` | Set the canvas base color |

Exports support PNG, JPEG, WebP, TIFF; AVIF depends on the installed Pillow codec. JPEG flattens transparency onto white, configurable with `--background`. Explicit `--format` overrides a profile or filename. Profiles **contain**, not crop or stretch; `print` does not imply CMYK or color-managed prepress.

## Layers and editing

Layers are ordered bottom to top. A target is a unique layer name or immutable ID. Most editing commands accept an omitted target and use the active layer.

```bash
pix layer add image.png --name hero
pix add logo.png --name logo --linked
pix select-layer hero
pix layer rename hero portrait
pix layer duplicate portrait copy
pix layer hide copy
pix layer show copy
pix layer remove copy
pix layer raise portrait
pix layer lower portrait
pix layer top logo
pix layer bottom portrait
pix layer reorder logo --above portrait
pix move portrait 100 200
pix move portrait --x 100 --y 200
pix move x +20
pix scale portrait 80%
pix resize portrait 800x600
pix resize portrait --width 800
pix rotate portrait 15
pix flip portrait horizontal
pix crop portrait 0 0 300 400
pix opacity portrait 0.75
pix blend portrait multiply
pix align logo top-right --margin 40
```

`layer` is an optional namespace. `rm` aliases remove and `mv` aliases move. Rotation is clockwise, expands the layer bounds, and anchors the expanded bounding box at its x/y position. Crop coordinates refer to the original embedded raster. Resize with one dimension preserves aspect ratio; with two, it stretches. Numeric scale values are factors; `80%` is `0.8`. The CLI accepts opacity `75` as 75%; canonical JSON always requires 0–1.

Alignment supports center, center-x/y, left/right/top/bottom and corner pairs. Absolute moves and alignment clear constraints. `move x +20` and `--relative` add offsets.

```bash
pix solid --name panel --width 400 --height 200 --color '#26344e'
pix gradient --name sky --start '#152641' --end '#635e83' --direction vertical
pix text add 'Hello' --name title --size 96 --font DejaVuSans.ttf --color white --x center --y 120
pix text title --text 'Good evening' --size 80 --align center
pix text title --stroke-width 2 --stroke-color black
pix rasterize title
```

Text remains editable until rasterized. Custom `--font /path/to/font.ttf` imports and embeds a font. Other font names use Pillow's system-font lookup. Font substitution is never silent. Multiline text is supported; text wrapping, shaping guarantees for every script, and font-family style resolution are not implemented.

## Selections, masks, effects

```bash
pix select rect 0 0 500 300
pix select ellipse 100 100 200 200 --mode add --feather 5
pix select color '#ffffff' --tolerance 15
pix select alpha portrait
pix select all
pix select invert
pix select none
pix mask create portrait
pix mask from-selection portrait
pix mask import portrait --path mask.png
pix mask invert portrait
pix mask disable portrait
pix mask enable portrait
pix mask delete portrait
```

Selection combination modes: replace, add (maximum), subtract, intersect (minimum). White means selected/visible; black means unselected/hidden. No selection means effects cover the whole layer. Each effect captures the selection as it existed when the effect was added; clearing the selection does not remove that boundary. Effect selection masks use canvas coordinates. Layer masks are mapped onto the transformed layer's bounding box and move/resize with it.

```bash
pix brightness portrait +20
pix contrast -10
pix saturation +15
pix hue 30
pix exposure 0.5
pix gamma 1.1
pix temperature 300
pix tint 10
pix shadows 15
pix highlights -10
pix blur 8
pix sharpen 2
pix grayscale
pix invert
pix posterize 6
pix threshold 128
pix filter noise --amount 0.08 --seed 42
pix filter vignette --radius 0.7 --strength 0.4
pix filter levels --black 15 --white 240
pix effects portrait
pix effect disable portrait 1
pix effect set portrait 2 --amount 20
pix effect remove portrait 3
```

Effect indices start at 1; stable effect IDs also work. Curves use JSON `points: [[0,0],[128,160],[255,255]]`. Brightness/contrast/saturation are percentages relative to neutral; exposure is stops; gamma must be positive; hue is degrees; sharpen is a factor (1 is neutral); noise/grain are 0–1 standard deviations; posterize is 1–8 bits. Temperature/tint and shadows/highlights are simple channel/tonal adjustments, not camera-calibrated or color-managed controls. Noise is seeded (default 0).

Blend modes: normal, multiply, screen, overlay, darken, lighten, difference, add, subtract.

## Layout, templates, validation

```bash
pix variable set title 'Night Shift'
pix variable delete unused
pix constrain title --center-x canvas --below portrait 60
pix constrain logo --right canvas.right-40 --top canvas.top+40
pix unconstrain logo
pix render --set title='Late Edition' --out variant.png
pix assert canvas.width == 1920
pix assert layer.logo.exists
pix assert layer.logo.bounds within canvas
pix assert text.title.font-size '>=' 48
pix validate instagram-post
pix validate --rules rules.json
```

A constraint uses `canvas` or a layer plus `.left`, `.right`, `.top`, `.bottom`, `.center-x`, `.center-y`, optionally followed by a numeric `+offset` or `-offset`. One constraint per axis is supported. Cycles and dangling references fail atomically. Layer references become stable IDs, so renames do not break them. Delete dependents' constraints before deleting their target.

Variables use `${name}` interpolation in text, colors, gradient fills, and raster asset identifiers. Asset variables must refer to **embedded asset IDs**; render overrides never load arbitrary files. Text dimensions are recomputed when variables change. Undefined variables fail explicitly.

Validation profiles: instagram-post / instagram-square (1:1; Instagram also checks PNG under 8 MB), story (9:16), youtube-thumbnail (16:9). All check layer bounds. Text under 24 px is a warning. Rules files are JSON arrays of assertion strings. Comparisons support `==`, `!=`, `>`, `<`, `>=`, `<=`; quote shell operators. Assertions are parsed, never evaluated as Python.

## Scripts, presets, history

A `.pixscript` contains one editing command per line; blank lines and `#` comments are allowed. Quote colors and text. It is a bounded Pix language, not a shell or Python. Files referenced in scripts resolve relative to the script. Project lifecycle, exports, AI calls, and history commands are invoked outside scripts. Use shell scripts or the Python API to orchestrate those steps.

```bash
pix run cleanup.pixscript
pix apply operations.json --dry-run
pix each layer --type raster --name 'card-*' -- saturation -10
pix preset save gritty portrait
pix preset show gritty
pix preset apply gritty other --set noise=0.03
pix undo 3
pix redo
pix checkpoint clean
pix branch vivid
pix checkout clean
pix history
pix branches
pix compare vivid clean --out comparison.png
```

Presets save the active/target layer's complete effect stack. Applying one assigns fresh effect IDs and captures the current selection. Branches name movable tips; checkpoints are fixed. Checking out a checkpoint detaches history; create a branch to name subsequent work. Undo/redo moves the current branch tip; alternate history nodes remain available by ID. Transactions allow provisional edits across processes and commit as one undoable history entry. They do not hide provisional state from other clients of the same project.

`batch` refuses output collisions and existing destinations, reports each input's result, and exits nonzero if any fail. Earlier successful outputs remain if a later item fails.
