# Canonical operations reference

Vixl is headless and designed for autonomous AI agents; humans can use the same interfaces. See [new resources and SVG](resources.md) for 0.11 additions.

Every edit in Vixl is a JSON object with a `type`. Send a single object, an array, or
`{"operations": [...]}` to: MCP `vixl_operations_apply(operations=[...])`, CLI `vixl apply FILE|-`,
REST `POST /operations`, or Python `Project.apply(...)`. Unknown fields, unknown types, malformed
sizes and non-finite numbers are rejected. Max 1 000 operations per batch; the batch is atomic.

Conventions used below: **bold** = required. `target` is a layer name or `lyr_…` ID and, when
omitted, defaults to the active layer. Colors accept CSS names, `#rgb`, `#rrggbb`, `#rrggbbaa`,
`transparent`, `@swatch`, and `${variable}`.

The authoritative schema is always `vixl schema` / `GET /schema` / `vixl://operations`.

## Creating layers

| type | fields | notes |
| --- | --- | --- |
| `add` | **`path`** *or* **`asset`**, `name`, `x`, `y`, `linked` | `path` is CLI/Python only (MCP: use `vixl_import_image`). `asset` = an embedded ID like `assets/<sha256>.png`. `linked` keeps an external reference (needs `--allow-linked`). |
| `solid` | `name`, `width`, `height`, `color`, `x`, `y` | Defaults to canvas size. |
| `gradient` | `name`, `width`, `height`, `start`, `end`, `direction`, `stops`, `angle`, `x`, `y` | `direction`: `vertical` (default), `horizontal`, `angled` (`angle` 0°=left→right, 90°=top→bottom), `radial`. `stops`: 2–64 `{"offset":0..1,"color":…}` strictly increasing. |
| `text` | **`text`**, `name`, `size`, `color`, `align` (`left`/`center`/`right`), `spacing` (line spacing px), `font`, `x`, `y` | `x`/`y` may be `"center"`. `font` (file path) is CLI/Python only; default font DejaVu Sans is bundled. Multiline via `\n`. |
| `shape` | **`shape`**, `name`, `width`, `height`, `x`, `y`, `fill`, `stroke`, `stroke_width`, `radius`, `sides`, `inner_radius` | `shape`: `rectangle`, `rounded-rectangle` (`radius`), `ellipse`, `polygon` (`sides`), `star` (`sides`, `inner_radius` 0.01–1), `line`. Procedural, redrawn crisply on resize. |
| `frame` | `name`, `width`, `height`, `x`, `y`, `path` *or* `asset`, `fit` (`fill`/`fit`) | Image placed in a fixed box; `fill` crops, `fit` letterboxes. |
| `pixel-art` | `name`, `width`, `height`, `x`, `y`, `palette`, `background`, **or** `rows` | Character-grid sprite (1–256 per side). See *Pixel art* below. |
| `adjustment` | **`effects`** (list of effect objects), `name` | Adjustment layer: filters the composited stack *below it* in its parent. |
| `symbol-instance` | **`symbol`**, `name`, `x`, `y`, `width`, `height` | Live copy of a symbol master. |
| `duplicate` | `target`, `name` | |

## Layer management

| type | fields |
| --- | --- |
| `rename` | `target`, **`name`** |
| `remove`, `hide`, `show` | `target` |
| `raise`, `lower`, `top`, `bottom` | `target` |
| `reorder` | `target`, `above` *or* `below` (layer) |
| `select-layer` | `target` — makes it the active layer |
| `rasterize` | `target` — bakes text/shape/etc. to pixels (remove styles/clip first) |
| `group` | **`name`**, **`targets`** (list) — children keep local coordinates; nest ≤16 |
| `ungroup` | `target` |
| `clip` | `target`, `base` (sibling) — multiplies target alpha by base alpha; `release: true` removes |

## Transform and appearance

| type | fields | notes |
| --- | --- | --- |
| `move` | `target`, `x`, `y`, `relative` | Absolute move clears constraints; `relative: true` adds offsets. |
| `resize` | `target`, `width`, `height` | One dimension keeps aspect ratio; two stretch. Turns off text auto-size. |
| `scale` | `target`, **`value`** | Factor (0.8 = 80 %). |
| `rotate` | `target`, **`value`** | Degrees clockwise; bounds expand. |
| `flip` | `target`, **`direction`** | `horizontal` / `vertical`. |
| `crop` | `target`, **`x`, `y`, `width`, `height`** | In the original embedded raster's coordinates. |
| `opacity` | `target`, **`value`** | 0–1. |
| `blend` | `target`, **`value`** | `normal`, `multiply`, `screen`, `overlay`, `darken`, `lighten`, `difference`, `add`, `subtract`. |
| `text-set` | `target`, `text`, `size`, `color`, `align`, `spacing`, `stroke_width`, `stroke_color` | Edit an existing text layer. |
| `text-layout` | `target`, `width`, `height`, `fit`, `warp`, `amount`, `path` | Box wrapping; `fit: true` shrinks font to fit; `warp`: `none`/`arc`/`flag`/`bulge` with `amount` −1..1; `path`: polyline `[[x,y],…]` in local px. Replaces previous layout. |
| `layer-style` | `target`, **`name`**, `settings`, `remove` | See *Layer styles*. |
| `replace-contents` | `target`, `path` *or* `asset` *or* `variable`, `fit` | Swap image, keep ID/box/effects/mask/styles. |

## Layout

| type | fields | notes |
| --- | --- | --- |
| `align` | **`alignment`**, `target`, `targets`, `margin`, `relative_to` | `alignment`: `center`, `center-x`, `center-y`, `top`, `bottom`, `left`, `right`, `top-left`, `top-right`, `bottom-left`, `bottom-right`. `relative_to`: `canvas` (default for one target), `selection` (default for several; union bounds) or a sibling. Bakes positions, clears constraints. |
| `distribute` | **`targets`** (≥3 siblings), **`axis`** (`horizontal`/`vertical`), `gap` | Without `gap`: equal edge-to-edge spacing between outer items. |
| `constrain` | `target`, **`constraints`** | e.g. `{"center-x":"canvas.center-x","top":"logo.bottom+40"}`. Keys `left/right/center-x` (one per axis) and `top/bottom/center-y`. Values: `canvas`, layer name/ID, or `guide:NAME`, then `.edge` and optional `+N`/`-N`. Cycles rejected. Siblings only inside groups. |
| `unconstrain` | `target` | |
| `canvas` | `width`, `height`, `background`, `preset` | Presets: `instagram-square`/`instagram-post` 1080², `story` 1080×1920, `youtube-thumbnail` 1280×720, `discord` 512². Constraints reflow. |
| `guide` | **`name`**, **`axis`** (`x`/`y`), **`position`** | Named, never rendered; use in constraints as `guide:NAME.left+8`. |
| `grid` | **`name`**, `columns`, `rows`, `margin`, `gutter` | Generates guides `NAME-x1-start`, `NAME-x1-end`, `NAME-y1-start`, … |
| `artboard` | **`name`**, `preset` *or* `width`/`height`, `x`, `y`, `background`, `variables`, `targets`, `delete` | Named alternate canvas sizes in one document. `targets` = top-level layer IDs shown (absent = all). |

## Selections and masks

| type | fields | notes |
| --- | --- | --- |
| `select` | **`shape`**, `x`, `y`, `width`, `height`, `color`, `tolerance`, `target`, `asset`, `mode`, `feather` | `shape`: `rect`, `ellipse` (x,y,w,h), `color` (`color`, `tolerance`), `alpha` (`target` layer), `asset` (grayscale mask asset), `all`, `none`, `invert`. `mode`: `replace`/`add`/`subtract`/`intersect`. Canvas coordinates. |
| `mask` | `target`, **`action`**, `path` | `action`: `create` (white), `from-selection`, `import` (`path`; CLI/Python only), `invert`, `enable`, `disable`, `delete`. White = visible. Masks follow the layer's transform. |

New effects are limited to the selection active **when they are added**. Select `none` first for whole-layer effects.

## Effects (non-destructive filter stack)

Add with `{"type":"effect","name":NAME,...}` or the shorthand `{"type":NAME,...}`. Field `amount`
(alias `value`) unless noted.

| name | meaning of `amount` |
| --- | --- |
| `brightness`, `contrast`, `saturation` | % relative to neutral (−100…; 0 = none) |
| `hue` | degrees |
| `exposure` | stops (−32…32) |
| `gamma` | > 0 (1 = none) |
| `temperature` | warm(+)/cool(−), e.g. 300 |
| `tint` | magenta(+)/green(−), e.g. 10 |
| `shadows`, `highlights` | % lift(+)/cut(−) |
| `blur`, `gaussian-blur` | **radius in px via `amount`** (0–1000). ⚠️ a `radius` field is ignored for blur |
| `sharpen` | factor (1 = none, 0–100) |
| `grayscale`, `invert` | — |
| `posterize` | bits 1–8 |
| `threshold` | 0–255 |
| `noise`, `grain` | std-dev 0–1, plus `seed` (default 0) |
| `vignette` | `strength` 0–1 (or `amount`), `radius` 0–1.4 (default 0.7) |
| `levels` | `black` 0–254, `white` 1–255 |
| `curves` | `points`: `[[0,0],[128,160],[255,255]]` |
| `auto-tone`, `auto-color`, `auto-contrast` | — (percentile stretch) |

Manage the stack (effect = stable `fx_…` ID **or** 1-based index):

| type | fields |
| --- | --- |
| `effect-set` | `target`, **`effect`**, `amount`/`value`, `seed`, `radius`, `strength`, `black`, `white`, `points` |
| `effect-enable` / `effect-disable` / `effect-remove` | `target`, **`effect`** |
| `preset-save` | **`name`**, `target` — saves the layer's effect stack |
| `preset-apply` | **`name`**, `target`, `overrides` |
| `lut` | **`name`**, **`size`** (2–33), **`values`** (`size³` RGB triples 0–1, red fastest) |
| `lookup` | `target`, **`name`** (LUT), `amount` (0–1 mix) |

Plugin filters (enabled with `--plugins`) are also addressed by `name`.

## Layer styles (`layer-style`)

`{"type":"layer-style","target":"title","name":"drop-shadow","settings":{...}}`; `remove: true`
deletes it. One style per kind; all accept `enabled` (bool) and `opacity` (0–1).

| name | settings |
| --- | --- |
| `drop-shadow` | `color`, `dx`, `dy` (±4096), `blur` (0–100) |
| `outer-glow` | `color`, `blur` |
| `stroke` | `color`, `width` (0–100) — outer stroke |
| `color-overlay` | `color` |
| `gradient-overlay` | `start`, `end`, `stops`, `direction`, `angle` (same as `gradient`) |

## Text styles, swatches, variables, comps, symbols

| type | fields | notes |
| --- | --- | --- |
| `swatch` | **`name`**, **`color`** | Use as `@name`; redefining updates every use. |
| `style-define` | **`name`**, **`settings`**, `kind` | `character`: `size`, `color`, `stroke_width`, `stroke_color` (ints). `paragraph`: `align`, `spacing`. |
| `style-apply` | **`name`**, `target`, `kind` | Linked: redefining the style updates layers. |
| `variable` | **`name`**, `value`, or `delete: true` | `${name}` in text/colors/gradients/asset IDs. |
| `comp-save` | **`name`** | Captures visibility/position/rotation/opacity/blend/constraints/styles. |
| `comp-apply` | **`name`** | Undoable; `render --comp NAME` previews read-only. |
| `symbol` | **`name`**, `target` | Turn a drawable layer into a master. |
| `pathfinder` | **`name`**, **`targets`** (shapes), **`mode`** (`union`/`subtract`/`intersect`) | New layer; hides originals; uses first operand's fill. |
| `repeat` | `target`, **`count`** (≤512, includes original), `dx`, `dy` (≥0), `dw`, `dh` | Stays one layer; re-applying replaces settings. |
| `repeat-blend` | as `repeat` plus **`end`** `{width,height,fill,color}` | Interpolates size/color to the last copy. |

## Pixel art and animation

| type | fields | notes |
| --- | --- | --- |
| `pixel-art` | `name`, `width`, `height`, `palette`, `background`, `x`, `y` — **or** `rows` (+`palette`) | `rows`: list of equal-length strings, one char per pixel. `palette`: `{"symbol":"color"}` (1–94 printable ASCII symbols). Default palette `.`=transparent, `#`=black. |
| `pixel-draw` | `target`, **`x`**, **`y`**, **`color`** (palette symbol), `tool`, `x2`, `y2`, `width`, `height` | `tool`: `pixel` (default), `line` (to `x2`,`y2`), `rect` (`width`×`height` filled), `fill` (4-way flood). Native grid coordinates. |
| `pixel-palette` | `target`, **`colors`** | Recolor symbols everywhere. |
| `frame-save` | **`name`**, `duration` (10–60 000 ms, multiple of 10; default 100) | Snapshot the current scene as an animation frame (canvas ≤256×256). |
| `frame-apply` | **`name`** | Restore a frame for editing. |
| `frame-delete` | **`name`** | |
| `animation-set` | `order` (frame names), `loop` (extra repeats; 0 = infinite) | |

## Legacy aliases (avoid in new code)

`operation`→`type`, `layer`→`target`; `set_opacity`, `set_blend`, `add_layer`, `remove_layer`,
`move_layer`, `set_effect`, `make_selection`.

## Results

Apply returns `{"success": true, "dry_run": bool, "operations": N, "changes": {...}}`.
`detail:"compact"` (MCP/REST default; `Project.apply(..., detail="compact")`) keys changes by layer ID
with `before`/`after` per changed field and `added`/`removed` layers; `detail:"full"` (CLI and Python
default) includes complete before/after layer snapshots.
