# Design resources and vector export

Vixl is a headless design engine built for autonomous AI agents. Humans can use the same CLI, Python, REST and MCP interfaces. No GUI or interactive approval is required for editing.

## Discover before designing

```bash
vixl commands --json
vixl shapes --json
vixl export --help
vixl validate --help
vixl palette list
vixl template list
vixl guidance list
```

These commands work without an open document. CLI edits return compact changes keyed by stable layer ID by default. Use `--detail full` for before/after snapshots. Prefer atomic `apply` batches, Python, or a persistent MCP/REST session for repeated edits; services reuse the loaded document between requests.

## Palettes

The library includes 32 named palettes, from `midnight`, `ocean`, `forest`, `sunset`, and `pastel` to `mono`, `nordic`, and `accessible-blue`. Palette names describe starting points; measure actual foreground/background contrast for the combinations you choose.

```bash
vixl palette show ocean
vixl palette apply ocean
vixl shape capsule --name label --width 200 --height 80 --fill @ocean-2
vixl palette add brand brand-colors.json
vixl palette apply brand --prefix company
```

Custom palette files are JSON arrays of 2–256 color strings, for example `["#123456", "#abcdef"]`. Applying creates editable named swatches (`ocean-1` through `ocean-5`); it does not recolor existing layers. Refer to swatches with `@NAME`.

## Templates

Built-in templates: `social-square`, `story`, `thumbnail`, `poster`, `business-card`, and transparent `logo`.

```bash
vixl template show social-square
vixl template new social-square -o campaign.vixl --set title='New launch' --set subtitle='Available today'
vixl template new logo -o logo.vixl --set accent='#e76f51'
vixl template add my-card card-template.json
vixl template apply my-card --set title='Next variant'
```

`new` creates a correctly sized document and refuses to overwrite a file. `apply` inserts template operations into the current document without resizing its canvas; duplicate layer names fail atomically. Custom JSON:

```json
{
  "width": 640,
  "height": 360,
  "background": "transparent",
  "defaults": {"accent": "#2563eb"},
  "operations": [
    {"type": "shape", "shape": "triangle", "name": "mark", "width": 100, "height": 100, "fill": "${accent}"}
  ]
}
```

Parameters can replace strings or whole typed values. Templates contain bounded canonical operations, not scripts or executable code. They cannot load files, import fonts, or recursively invoke templates. Import image/font assets explicitly first. The user library is stored in `~/.config/vixl/resources.json`; set `VIXL_RESOURCES` to isolate it in automation.

## Overall and style-specific guidance

```bash
vixl guidance apply overall
vixl guidance apply minimal --style minimal
vixl guidance add brand brand-guide.txt
vixl guidance apply brand --style brand
vixl guidance import campaign campaign-guide.txt --style campaign
vixl guidance remove campaign --style campaign
```

`add` stores plain text in the reusable library; `import` attaches file text directly to the document. Guidance is retained in `design_guidance`, survives save/open and undo, and is included in `ask` planning requests alongside the operation schema and current preview. It guides the external planner; deterministic drawing commands do not infer or enforce aesthetic rules. Imported guidance and image text are treated as data, and returned plans still pass Vixl's safety and operation validation.

## Fonts

```bash
vixl font import ./Brand-Regular.ttf --name brand
vixl font import https://example.com/fonts/Brand-Regular.otf --name brand
vixl font list
vixl text add 'Brand headline' --font brand --name title --size 64
```

The explicit import validates and embeds a TTF/OTF font (maximum 16 MiB) under a registered name. Later text creation needs no internet or original file. HTTPS imports accept direct font-file URLs and reject redirects; use the final HTTPS URL. Google Fonts stylesheet URLs, WOFF/WOFF2, and HTML are not font files. Download an authorized TTF/OTF from the font's source and retain its license where needed. No font downloads happen implicitly during rendering. Existing `text add ... --font FILE` local imports remain supported.

## Shape shortcuts and editable paths

`vixl shapes` lists the full catalog. In addition to rectangles, ellipses, polygons, stars and lines, shortcuts include triangles, diamonds, arrows, chevrons, crosses, hearts, speech bubbles, shields, trapezoids, parallelograms, pentagons, hexagons, octagons and capsules.

```bash
vixl shape heart --name mark --width 180 --height 180 --fill '#e76f51'
vixl shape path --name curve --width 200 --height 100 --fill '#2563eb' --path 'M0 0 C0 100 200 100 200 0 L200 100 L0 100 Z'
```

Paths retain a single editable contour with SVG `M L H V Q C Z` commands, including lowercase relative commands. Repeat the command before each coordinate set. Coordinates are in the layer's initial width/height; resizing scales that coordinate system. Arcs, shorthand commands, multiple contours and arbitrary SVG import are not supported. Raster previews sample curves with bounded antialiasing; SVG retains exact Bézier commands.

Positions refer to the top-left of the transformed bounding box. Rotation expands that box, so align/constrain after rotating, or inspect `resolved_bounds` before positioning. For clean logo joins, use a single path or a deliberate pathfinder union/subtraction rather than overlapping rotated bars by guesswork.

## Transparent PNG, JPG and SVG

```bash
vixl new 512x512 --background transparent -o mark.vixl
vixl shape diamond --name mark --width 256 --height 256 --x 128 --y 128 --fill '#2563eb'
vixl export mark.png
vixl export mark.jpg --background white --quality 95
vixl export mark.svg
vixl export - --format SVG
```

PNG preserves canvas/layer alpha. `canvas background transparent` changes an existing canvas; remove or hide opaque background layers too. JPEG flattens transparency against the chosen `--background`. PNG, JPEG/JPG, WebP, TIFF, AVIF and SVG are available from Python/CLI; MCP picks the format from the filename; REST `POST /export` returns the selected bytes.

SVG exports simple solids, shapes and paths as native scalable geometry. Text, images, gradients, groups, pathfinder silhouettes, masks and layer effects are embedded PNGs inside a self-contained SVG. Canvas-dependent clipping, layer styles, adjustment layers and non-normal blending flatten the document into an embedded PNG for faithful appearance. SVG export preserves supported vector geometry; it does not turn photographs or flattened effects into vectors. Raster export profiles do not apply to SVG. Native SVG strokes/antialiasing can differ slightly from the raster preview; inspect the final file for delivery.

## Agent interfaces

Python can use `vixl.resources.catalog/get/register/create_template` and `vixl.fonts.import_font`. The structured operations `palette-apply`, `template-apply`, `guidance`, and `font-register` share the normal atomic edit/history engine. Example:

```json
{"operations": [
  {"type": "palette-apply", "name": "ocean"},
  {"type": "guidance", "name": "minimal", "style": "minimal"},
  {"type": "shape", "shape": "arrow", "name": "next", "width": 80, "height": 40, "fill": "@ocean-2"}
]}
```

MCP exposes `vixl_resources_list`, `vixl_resource_get`, `vixl_resource_add`, `vixl_template_create`, `vixl_import_font`, `vixl_text_add`, and `vixl_models_list`. Font file paths and template destinations stay inside the server workspace. Use `vixl_text_add(font="brand", ...)` for a registered font; generic service operations continue to reject arbitrary filesystem font paths. REST adds GET/POST `/resources/{kind}/{name}`, GET `/resources/{kind}`, POST `/fonts?name=brand` with raw font bytes, and POST `/export` with JSON options such as `{"format":"SVG"}`. REST font uploads are limited to 16 MiB.
