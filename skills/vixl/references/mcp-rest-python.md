# MCP, REST and Python interfaces

Vixl is headless and designed for autonomous AI agents; humans can use the same interfaces. See [new resources and SVG](resources.md) for 0.11 additions.

## MCP server

Start: `vixl mcp --workspace DIR` (stdio; requires the `mcp` extra or the Windows installer).
Legacy form `vixl --project /abs/poster.vixl mcp` opens that document and uses its folder as the
workspace. Client config:

```json
{"mcpServers": {"vixl": {"command": "vixl", "args": ["mcp", "--workspace", "/home/you/Pictures/Vixl"],
                         "env": {"VIXL_NO_UPDATE": "1"}}}}
```

Windows installer path if `vixl` is not on PATH: `%LOCALAPPDATA%\Vixl\bin\vixl.exe` (escape
backslashes in JSON). Restart the client after install/config changes.

**Session model:** one *active document* at a time. Nothing works until you call
`vixl_document_create` or `vixl_document_open` (error: "Create or open a document first").
All paths are server-local and relative to (or absolute inside) the workspace; escaping paths and
symlinks out are rejected; parent directories must exist. Successful edits are saved immediately,
so switching documents never loses work. External edits to the file are detected and reloaded.

### Documents and files

| Tool | Parameters | Returns / notes |
| --- | --- | --- |
| `vixl_workspace_list` | `directory="."`, `offset=0`, `limit=100` (≤200) | `entries[{path,directory}]`, `active_document`, `next_offset` |
| `vixl_document_create` | **`path`**, **`width`**, **`height`**, `background="transparent"` | Creates + activates; refuses existing files |
| `vixl_document_open` | **`path`** | Activates an existing `.vixl` |
| `vixl_document_inspect` | `target=None` | Whole document, or one layer (with `resolved_bounds`) |
| `vixl_import_image` | **`path`**, `name="image"` | Embeds a workspace image as a new layer (≤64 MiB) |
| `vixl_export_file` | **`path`**, `quality=90`, `scale=1` (0.01–16), `profile`, `variables`, `background="white"`, `overwrite=False`, `sampling="smooth"\|"nearest"`, `artboard`, `comp` | Writes PNG/JPEG/WEBP/TIFF/AVIF (by extension); returns `{path, format, bytes}` |

### Editing and viewing

| Tool | Parameters | Returns / notes |
| --- | --- | --- |
| `vixl_operations_apply` | **`operations`** (1–1000 operation objects), `dry_run=False`, `detail="compact"\|"full"` | Atomic; compact diff keyed by layer ID. Full operation schema is embedded in this tool's input schema. |
| `vixl_render_preview` | `variables`, `max_width=1024`, `max_height=1024` (≤4096), `max_bytes=1048576` (64 KiB–4 MiB), `artboard`, `comp` | PNG image content; aspect preserved, never upscaled |
| `vixl_history` | `action="list"\|"undo"\|"redo"\|"branch"\|"checkpoint"\|"checkout"\|"begin"\|"commit"\|"rollback"`, `ref`, `count=1`, `offset`, `limit=20` | `list` → paginated node summaries; others → new head/branch |

Transactions: `vixl_history(action="begin")` → several `vixl_operations_apply` calls →
`commit` (one undo step) or `rollback`. Name branches/checkpoints with `ref`.

### Measurement and validation (read-only)

| Tool | Parameters | Returns |
| --- | --- | --- |
| `vixl_measure` | `point=[x,y]`, `region=[x,y,w,h]`, `foreground`, `target`, `artboard`, `comp` | RGBA/hex sample, alpha-weighted average, histograms, WCAG contrast min/mean/max |
| `vixl_measure_spacing` | `targets`, `axis="vertical"`, `around`/`before`/`after`, `expected`, `tolerance=1`, `artboard`, `comp` | Per-gap pixels, overlap, min/max/mean/spread, `passed` |
| `vixl_validate` | `profile` (`instagram-post`, `instagram-square`, `story`, `youtube-thumbnail`), `rules` (assertion strings) | `{valid, checks[{rule,passed,severity}]}`; failures raise `validation_failed` with checks |

Assertion grammar: `canvas.width == 1920`, `layer.NAME.exists`, `layer.NAME.bounds within canvas`,
`text.NAME.font-size >= 48`; comparators `== != > < >= <=`.

### Pixel art and animation

| Tool | Parameters | Notes |
| --- | --- | --- |
| `vixl_pixels_inspect` | `target` | `{id,name,width,height,palette,rows}` — read/modify sprites as text |
| `vixl_animation_inspect` | — | Frame names, sizes, durations, total |
| `vixl_animation_preview` | **`name`**, `scale=1` (1–8) | Crisp nearest-neighbor PNG of a saved frame |
| `vixl_export_animation` | **`path`**, `format="gif"\|"apng"\|"sheet"`, `scale=1` (1–32), `columns` | Sheet also writes `same-stem.json` with frame rects/durations; never overwrites |

Edits use `vixl_operations_apply` with `pixel-art`, `pixel-draw`, `pixel-palette`, `frame-save`,
`frame-apply`, `frame-delete`, `animation-set`.

### AI tools (need configured providers; see ai.md)

| Tool | Parameters |
| --- | --- |
| `vixl_ai_generate` | **`prompt`**, `mode="generate"\|"inpaint"\|"img2img"`, `width`+`height` (both or neither; default canvas), `seed`, `name="generated"`, `provider`, `model`, `negative_prompt`, `strength=0.75` |
| `vixl_ai_extend` | **`prompt`**, `left`/`right`/`top`/`bottom` (px, ≥1 positive), `seed`, `name`, `provider` |
| `vixl_ai_upscale` | **`layer`**, `scale=2` (≤16), `provider` |
| `vixl_ai_regenerate` | **`layer`**, `prompt`, `seed`, `provider` (defaults to the original provider) |
| `vixl_ai_remove_background` | **`layer`**, `provider` — attaches an editable mask |
| `vixl_ai_select_object` | **`label`**, `provider` — sets the active selection |
| `vixl_ai_select_subject` | `provider` |
| `vixl_ai_remove` | `name="removed-object"`, `provider` — inpaints the current selection |
| `vixl_ai_content_aware_fill` | `prompt`, `name="filled-region"`, `provider` |
| `vixl_ai_analyze` | **`capability`** `describe`\|`detect`\|`ocr`, `query`, `provider` |
| `vixl_ai_plan` | **`prompt`**, `apply=False`, `provider` — proposes operations; review before `apply=true` |

### Resource

`vixl://operations` — the full operation JSON Schema (same as `vixl schema`). Usually unnecessary
because the schema is inline in `vixl_operations_apply`.

### MCP-specific restrictions

- Operation fields `path`, `linked`, `font` are rejected → import with `vixl_import_image`; reference
  embedded images by `asset` ID (see `vixl_document_inspect`), e.g. in `frame`/`replace-contents`/`add`.
- No custom font files over MCP; the bundled DejaVu Sans and system font names still work.
- No plugins, no linked files. CSV `render --data` and `export-screens` are CLI/Python only.
- Tool errors come back as text like `Error executing tool …: Layer 'x' does not exist` — re-inspect,
  correct, retry. Nothing was changed by a failed call.

## REST API

Start: `vixl -p poster.vixl serve [--host 127.0.0.1] [--port 8765]`. OpenAPI docs at `/docs`.
Non-loopback hosts require a bearer token from `VIXL_API_TOKEN` (or `--token-env NAME`); send
`Authorization: Bearer …`. One fixed project per server.

| Route | Body / query | Result |
| --- | --- | --- |
| `GET /schema` | | Operation JSON Schema |
| `GET /document` · `GET /layers` | | Inspection |
| `POST /operations` | `{"operations":[…],"dry_run":false,"detail":"compact"}` | Change summary |
| `GET /render` | | PNG |
| `POST /render` | `{"variables":{…},"artboard":…,"comp":…}` | PNG |
| `POST /measure` | `{"point":[x,y]}` / `{"region":[…],"foreground":…}` / `{"target":…}` | Measurements |
| `POST /spacing` | same keys as `vixl_measure_spacing` | Spacing report |
| `POST /validate` | `{"profile":…,"rules":[…]}` | Checks |
| `GET /pixels/{target}` | | Pixel rows/palette |
| `GET /animation` · `GET /animation/frame/{name}?scale=1` | | Frame list · PNG |
| `GET /history` · `POST /history/{action}` | `{"ref":…,"count":1}` | History graph / new head |
| `POST /assets?name=photo` | raw image bytes | New layer |
| `POST /ai/{command}` | `{"args":["--prompt","forest","--provider","local"]}` | CLI-style AI call |

Errors: HTTP 400 with `{"error":CODE,"message":…}` (403 for `forbidden`, 413 for oversized bodies).
`path`/`linked`/`font` operation fields are rejected, as with MCP.

```bash
curl -s -X POST http://127.0.0.1:8765/operations -H 'Content-Type: application/json' \
  -d '{"operations":[{"type":"move","target":"logo","x":20,"y":40}]}'
curl -s http://127.0.0.1:8765/render -o preview.png
curl -s -X POST 'http://127.0.0.1:8765/assets?name=photo' --data-binary @photo.jpg
```

## Python API

```python
from vixl import Project, VixlError
from vixl.model import Limits

p = Project(1080, 1080, background="#101828")              # new, unsaved
p = Project.load("poster.vixl", limits=Limits(max_pixels=16_000_000), allow_linked=False)

p.apply([{"type": "text", "name": "title", "text": "Hi", "size": 64}], dry_run=False, detail="compact")
p.inspect()                 # dict; p.inspect("title") for one layer
p.layer("title")            # live layer dict (read-only use)
img = p.render(variables={"title": "Hello"}, artboard=None, comp=None)   # Pillow RGBA
data = p.export("out.png", quality=90, scale=2, profile=None, sampling="smooth")  # bytes, writes path
p.save() ; p.save("copy.vixl")

p.undo(1); p.redo(1); p.checkpoint("clean"); p.branch("vivid"); p.checkout("clean")
p.begin(); ...; p.commit()  # or p.rollback()

p.measure(point=(10, 10)); p.measure(region=(0, 0, 100, 100), foreground="#fff"); p.measure(target="title")
p.measure_spacing(targets=["a", "b", "c"], axis="vertical", expected=24, tolerance=1)
p.inspect_pixels("sprite"); p.inspect_animation(); p.render_frame("idle", scale=4)
p.export_animation("sprite.gif", format="gif", scale=8)      # or "apng" / "sheet" (columns=)
p.export_screens("screens", scales=(1, 2))
p.render_data("rows.csv", "campaign")
p.manifest()

try:
    p.apply({"type": "move", "target": "nope", "x": 1})
except VixlError as e:
    print(e.code, e.details, e.as_dict())
```

Python is a trusted local API: `path`, `font` and `linked` fields work. Enable plugins with
`vixl.plugins.enable_plugins()`.
