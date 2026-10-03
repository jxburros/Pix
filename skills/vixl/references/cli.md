# CLI reference

```text
vixl [GLOBAL OPTIONS] COMMAND [ARGS]
vixl                      # interactive shell (don't use from an agent; use commands)
vixl COMMAND --help       # exact argument syntax for any editing command
```

**Global options** (before or after the command): `--project/-p FILE`, `--json` (structured
errors on stderr), `--allow-linked` (trust linked file references), `--plugins` (enable installed
filter/provider entry points — trusted code), `--max-pixels N`, `--version`.

Agent conventions:

- Always pass `-p FILE.vixl`. Without it Vixl uses the project recorded by `vixl open` in
  `./.vixl-session.json`.
- Add `--json` so errors are machine-readable: `{"error":"layer_not_found","message":…,"suggestions":[…]}`, exit 1.
- Editing commands autosave and print a full before/after diff — redirect it if you don't need it.
- Quote `#` colors (`'#ff8800'`), JSON arguments, and text.
- A target is a unique layer name or `lyr_…` ID; most commands default to the active layer when it is omitted.
- Every editing command below compiles to a canonical operation (see `operations.md`), so
  `vixl apply ops.json` can replace any sequence of them atomically.

## Documents and inspection

| Command | Effect |
| --- | --- |
| `new 1920x1080 -o F.vixl [--background COLOR]` | Create (refuses to overwrite); also selects it |
| `open F.vixl` | Select as default project for this directory |
| `save [COPY.vixl]` | Save / save-as |
| `status` | Canvas, active layer, head, branch, transaction flag |
| `inspect [LAYER]` | Full JSON state (or one layer) incl. `resolved_bounds` |
| `layers` | Layer list |
| `describe` | Document description |
| `effects [LAYER]` | Effect stack with IDs/indices |
| `manifest`, `dependencies`, `reproduce --check` | Assets, fonts, providers; can it re-render? |
| `schema` | JSON Schema of all operations |
| `pixels [LAYER]` | Pixel layer as rows + palette |
| `animation` | Frame names, sizes, durations |

## Creating layers

```bash
vixl add photo.jpg --name hero [--x 0 --y 0] [--linked]         # alias: layer add
vixl solid --name panel --width 400 --height 200 --color '#26344e' [--x --y]
vixl gradient --name sky --start '#152641' --end '#635e83' --direction vertical|horizontal|radial|angled [--angle 35]
vixl gradient --name sky --direction angled --angle 35 --stops '[{"offset":0,"color":"#152235"},{"offset":1,"color":"#e8885c"}]'
vixl text add 'Hello' --name title --size 96 --color white [--font path.ttf] [--align center] [--spacing 8] [--x center --y 120]
vixl shape rectangle|rounded-rectangle|ellipse|polygon|star|line --name s --width W --height H [--x --y] \
     [--fill C] [--stroke C] [--stroke-width N] [--radius N] [--sides N] [--inner-radius 0.4]
vixl frame --path portrait.jpg --name photo --width 400 --height 500 --fit fill|fit [--asset ID]
vixl pixel-art --name sprite --width 16 --height 16 [--palette '{".":"transparent","g":"#ffc44d"}'] [--background .]
vixl pixel-art --name spark --rows '[".w.","www",".w."]' --palette '{".":"transparent","w":"#fff"}'
vixl adjustment warmth --effects '[{"name":"temperature","amount":500},{"name":"contrast","amount":10}]'
vixl symbol-instance Brandmark --name footer-logo --x 100 --y 800 --width 100 --height 100
```

## Layer management and transforms

```bash
vixl select-layer hero
vixl layer rename hero portrait          # 'layer' namespace optional: vixl rename …
vixl duplicate portrait copy
vixl hide copy ; vixl show copy ; vixl remove copy   # rm = remove
vixl raise|lower|top|bottom portrait
vixl reorder logo --above portrait       # or --below
vixl move portrait 100 200 ; vixl move portrait --x 100 ; vixl move portrait 20 0 --relative   # mv = move
vixl scale portrait 80%                  # or 0.8
vixl resize portrait 800x600 ; vixl resize portrait --width 800
vixl rotate portrait 15                  # clockwise degrees
vixl flip portrait horizontal|vertical
vixl crop portrait 0 0 300 400           # X Y W H in the source raster
vixl opacity portrait 0.75               # or 75 (1–100 = percent)
vixl blend portrait multiply             # normal multiply screen overlay darken lighten difference add subtract
vixl rasterize title
vixl group stripes stripe1 stripe2 ; vixl ungroup stripes
vixl clip TARGET BASE ; vixl clip TARGET --release
```

## Text

```bash
vixl text title --text 'Good evening' --size 80 --align center --color '#fff' --spacing 6
vixl text title --stroke-width 2 --stroke-color black
vixl text-layout title --width 600 --height 180 [--fit] [--warp arc|flag|bulge|none --amount 0.15] [--path '[[10,90],[300,20],[590,90]]']
vixl swatch brand '#e8885c'
vixl style-define Heading --settings '{"size":80,"color":"@brand","stroke_width":1}'
vixl style-define Caption --kind paragraph --settings '{"align":"center","spacing":8}'
vixl style-apply title Heading ; vixl style-apply title Caption --kind paragraph
```

## Layout

```bash
vixl align logo top-right --margin 40
vixl align title left --relative-to logo
vixl align title center-y --targets title logo badge      # relative to the selection's union
vixl distribute horizontal a b c [--gap 24]
vixl constrain title --center-x canvas --center-y canvas
vixl constrain logo --right canvas.right-40 --top canvas.top+40
vixl constrain caption --center-x canvas --below title 24  # top = title.bottom+24
vixl constrain title --left guide:left-margin.left
vixl unconstrain logo
vixl canvas resize 1080x1080 ; vixl canvas preset story ; vixl canvas background transparent
vixl guide left-margin x 64
vixl grid editorial --columns 3 --rows 2 --margin 64 --gutter 24
vixl artboard story --preset story ; vixl artboard banner --width 1600 --height 600
```

## Selections, masks, effects

```bash
vixl select rect X Y W H [--mode add|subtract|intersect|replace] [--feather 5]
vixl select ellipse X Y W H
vixl select color '#ffffff' --tolerance 15
vixl select alpha LAYER
vixl select all|none|invert
vixl mask create|from-selection|invert|enable|disable|delete LAYER
vixl mask import LAYER --path mask.png

# Effects: vixl EFFECT [LAYER] AMOUNT
vixl brightness portrait +20 ; vixl contrast -10 ; vixl saturation +15 ; vixl hue 30
vixl exposure 0.5 ; vixl gamma 1.1 ; vixl temperature 300 ; vixl tint 10
vixl shadows 15 ; vixl highlights -10 ; vixl blur 8 ; vixl sharpen 2
vixl grayscale ; vixl invert ; vixl posterize 6 ; vixl threshold 128
vixl auto-tone photo ; vixl auto-color photo ; vixl auto-contrast photo
vixl filter noise --amount 0.08 --seed 42
vixl filter vignette --radius 0.7 --strength 0.4
vixl filter levels --black 15 --white 240
vixl filter blur --radius 4 --target photo
vixl effect disable|enable|remove LAYER EFFECT        # EFFECT = 1-based index or fx_ ID
vixl effect set LAYER EFFECT --amount 20
vixl preset save gritty portrait ; vixl preset show gritty ; vixl preset apply gritty other --set noise=0.03
vixl lookup photo look --amount 0.8                  # LUT defined via a `lut` operation in apply
vixl layer-style title drop-shadow|stroke|outer-glow|color-overlay|gradient-overlay --settings '{...}'
vixl layer-style title drop-shadow --remove
```

Curves have no dedicated CLI flags; use `apply` with `{"type":"curves","points":[[0,0],[128,160],[255,255]]}`.

## Design production

```bash
vixl repeat stripe --count 16 --dy 37 [--dx 0 --dw 0 --dh 1]
vixl repeat-blend stripe --count 16 --dy 37 --end '{"height":21,"fill":"#4853a4"}'
vixl pathfinder badge outer inner --mode union|subtract|intersect
vixl symbol logo Brandmark
vixl comp-save with-logo ; vixl comp-apply with-logo
vixl replace-contents photo --path new.jpg [--fit fit] | --asset assets/HASH.png | --variable photo_asset
vixl variable set title 'Night Shift' ; vixl variable delete title
```

## Measurement and QA (read-only)

```bash
vixl sample 100 150                                  # RGBA + hex at a point
vixl histogram --region X Y W H
vixl info --region X Y W H --foreground '#ffffff' [--background white]   # WCAG contrast vs a color
vixl info --target title                             # contrast of a rendered layer vs what's beneath
vixl spacing --targets heading body footer --axis vertical --tolerance 1 [--expected 24] [--check]
vixl spacing --around body --before heading --after footer
vixl check [--safe-area 5%] [--avoid X Y W H] [--thumbnail-width 320] [--checks overlap contrast] [--strict]
vixl validate [instagram-post|instagram-square|story|youtube-thumbnail] [--rules rules.json]
vixl assert canvas.width == 1920
vixl assert layer.logo.exists
vixl assert layer.logo.bounds within canvas
vixl assert text.title.font-size '>=' 48
```

All accept `--artboard NAME` / `--comp NAME` where relevant. `--check` (spacing), `check --strict`
and failing `validate`/`assert` exit nonzero with details (`--json` shows every check).

## Output

```bash
vixl export out.png|.jpg|.webp|.tiff|.avif [--quality 90] [--scale 2x] [--profile instagram|discord|print] \
     [--format PNG] [--background white] [--sampling nearest] [--set var=value] [--artboard NAME] [--comp NAME]
vixl render [F.vixl] --out preview.png [--set title=Hello]      # same options; never persists overrides
vixl render --data rows.csv --out campaign_dir                  # one PNG per CSV row: 0001.png …
vixl export-screens --out screens --scales 1 2 [--artboards square story]   # NAME@2x.png
vixl export-animation --out sprite.gif --format gif|apng|sheet [--scale 8] [--columns 3]
vixl export - --format PNG > preview.png                        # to stdout
cat photo.png | vixl convert --grayscale [--format PNG] > gray.png
vixl compare REF_A REF_B --out comparison.png                   # side-by-side history states
```

`export-screens` requires at least one artboard; `export-animation` requires saved frames.
`render --data`, `export-screens` and `export-animation` never overwrite existing outputs.
Profiles *contain* (never crop/stretch): `instagram` 1080² JPEG, `discord` 512² PNG, `print` TIFF @300 DPI.
JPEG flattens transparency onto `--background` (white).

## Automation

```bash
vixl apply ops.json [--dry-run]          # or: cat ops.json | vixl apply -
vixl run script.vixlscript               # one editing command per line, # comments; atomic
vixl batch './photos/*.jpg' --run cleanup.vixlscript --output ./processed [--format png]
vixl each layer --type raster --name 'card-*' -- saturation -10
vixl transaction begin ; …edits… ; vixl transaction commit   # or rollback; one undo step
```

`.vixlscript` lines are editing commands without the `vixl` prefix (no new/open/export/AI/history
commands; no shell). Paths resolve relative to the script.

## History

```bash
vixl undo [N] ; vixl redo [N]
vixl history ; vixl branches
vixl checkpoint before-color             # fixed reference
vixl branch vivid                        # movable tip
vixl checkout before-color               # detaches; create a branch to continue
vixl compare vivid before-color --out cmp.png
```

## Pixel art and animation

```bash
vixl pixel-draw sprite pixel 5 5 --color g
vixl pixel-draw sprite line 6 5 --x2 9 --y2 5 --color w
vixl pixel-draw sprite rect 4 4 --width 8 --height 8 --color s
vixl pixel-draw sprite fill 0 0 --color .
vixl pixel-palette sprite --colors '{"g":"#ffdd66"}'
vixl frame-save idle [--duration 150] ; vixl frame-apply idle ; vixl frame-delete idle
vixl animation-set --order idle blink --loop 0
```

## AI (needs a configured provider — see ai.md)

```bash
vixl ask 'Make the logo 20% smaller and align it top-right' [--apply] [--provider NAME]
vixl generate --prompt 'foggy forest' --provider comfy --size 1024x1024 --as forest [--seed 42] [--mode inpaint|img2img] [--negative-prompt …] [--strength 0.75] [--model …]
vixl select object 'the person' --provider vision
vixl detect objects|faces --provider NAME ; vixl ocr --provider NAME ; vixl ai describe --provider NAME
vixl ai background-remove LAYER ; vixl ai upscale LAYER --2x|--scale 4
vixl ai extend --right 500 --prompt '…' --as extension ; vixl ai regenerate LAYER [--prompt …] [--seed …]
vixl ai info LAYER                      # provenance
vixl ai remove --as removed ; vixl ai content-aware-fill --prompt '…' ; vixl ai select-subject
```

## Services and updates

```bash
vixl -p F.vixl serve [--host 127.0.0.1] [--port 8765] [--token-env VIXL_API_TOKEN]
vixl mcp --workspace DIR                 # MCP over stdio
vixl update --check | vixl update | vixl update --rollback ; vixl updates status|on|off   # Windows installer only
```
