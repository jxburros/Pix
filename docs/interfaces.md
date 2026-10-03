# Python, REST, MCP, and extension interfaces

Vixl is a headless application designed for autonomous AI agents; humans can use the same interfaces.

See [spacing checks and pixel animation](pixel-animation-spacing.md) for the 0.9.0 tools and API examples.

See [design tools and template production](design-tools.md) for groups, clipping, shapes, styles, artboards, CSV rendering, measurements, and the other design operations.

## Python

```python
from vixl import Project, VixlError
from vixl.model import Limits

project = Project.load("poster.vixl", limits=Limits(max_pixels=16_000_000))
proposal = [{"type": "opacity", "target": "logo", "value": 0.7}]
print(project.apply(proposal, dry_run=True))
project.apply(proposal)
project.save()
```

`Project.apply(..., detail="compact")` returns changed fields keyed by stable layer ID; the Python API keeps `detail="full"` as its compatibility default.

`Project.render()` returns a Pillow RGBA image. `Project.export()` returns encoded bytes, optionally writing to a path. `Project.inspect()` returns an independent JSON-serializable state description. History methods: `undo`, `redo`, `branch`, `checkpoint`, `checkout`, `begin`, `commit`, `rollback`.

Loading does not implicitly trust linked image paths; use `allow_linked=True` only when those local file references are intended. Direct Python APIs are trusted local APIs and can import files. Exceptions expose `VixlError.code`, `.details`, and `.as_dict()`.

## REST

```bash
python -m pip install -e '.[server]'
vixl -p poster.vixl serve
```

Default binding is `127.0.0.1:8765`. OpenAPI is at `/docs`. To bind beyond loopback, configure a bearer token with `VIXL_API_TOKEN` and use `--host 0.0.0.0`; use TLS at a reverse proxy. `--token-env NAME` selects a different environment variable. A configured token protects every route, including docs. Without a token, host-header validation restricts requests to loopback names. This is a local single-user service, not a multi-tenant hosted product.

| Route | Request / result |
| --- | --- |
| `GET /document` | Inspected state |
| `GET /layers` | Layer list |
| `GET /schema` | Canonical operation batch JSON Schema |
| `POST /operations` | `{operations: [...], dry_run: false, detail: "compact"}` → change summary (use `full` for snapshots) |
| `GET /render` | PNG bytes |
| `POST /render` | `{variables: {title: "Hello"}}` → PNG bytes |
| `POST /validate` | `{profile: "instagram-post", rules: [...]}` → checks |
| `GET /history` | History graph and named references |
| `POST /history/{action}` | `{ref: "name", count: 1}`; undo/redo/branch/checkpoint/checkout/begin/commit/rollback |
| `POST /assets?name=photo` | Raw image bytes → imported layer |
| `POST /ai/{command}` | `{args: ["--prompt", "forest", "--provider", "local"]}`; uses locally configured providers |

```bash
curl http://127.0.0.1:8765/document
curl -X POST http://127.0.0.1:8765/operations \
  -H 'Content-Type: application/json' \
  -d '{"operations":[{"type":"move","target":"logo","x":20,"y":40}]}'
curl http://127.0.0.1:8765/render -o preview.png
```

REST sessions fix the project path when launched. Operation `path`, `linked`, and `font` fields are rejected; import image bytes with `/assets`. Services do not enable third-party plugins or linked-file reads. Local AI configuration is trusted, and services can invoke it. Do not share API access with users who should not be able to use your configured AI service. Authentication is all-or-nothing; there are no per-user roles or quotas.

## MCP

The Windows installer includes MCP. For source installs, install `.[mcp]`. Give Vixl an existing workspace directory that contains the images/documents the model should edit:

```powershell
vixl mcp --workspace "C:\Users\jeffr\Pictures\Vixl"
```

The workspace can start without any `.vixl` documents. MCP runs over stdio using the official SDK; stdout contains protocol messages only. Configure your client to start it (escape Windows backslashes in JSON):

```json
{
  "mcpServers": {
    "vixl": {
      "command": "vixl",
      "args": ["mcp", "--workspace", "C:\\Users\\jeffr\\Pictures\\Vixl"]
    }
  }
}
```

If the client cannot find `vixl` on PATH, use the absolute executable path, normally `C:\Users\jeffr\AppData\Local\Vixl\bin\vixl.exe` for the Windows installer. Restart the client after installing/updating or changing its configuration. On macOS/Linux, use your installed `vixl` executable and a workspace such as `/home/you/Pictures/Vixl`.

Existing `vixl --project /absolute/path/poster.vixl mcp` configurations still work: they open that document and use its parent directory as the workspace. You can also pass `--workspace` explicitly; the starting project must be within it.

### Tools and workflow

Vixl is designed to be driven mainly by agents. The intended loop is: create or open a document → `vixl_operations_apply` in atomic batches (use `dry_run` to test) → `vixl_check` to find problems without looking → `vixl_render_preview` (with `region` to zoom) → fix → `vixl_export_file`.

| Tool | Purpose |
| --- | --- |
| `vixl_workspace_list(directory, offset, limit)` | Discover workspace paths and the open documents |
| `vixl_document_create(path, width, height, background)` | Create and activate a new `.vixl`; refuses overwrites |
| `vixl_document_open(path)` / `vixl_document_close(document)` | Activate an existing document / drop one from the session; edits are already saved |
| `vixl_document_inspect(target?, detail)` | `compact` (default): canvas plus one line per layer with resolved `[x, y, w, h]` bounds; `full`: every stored field |
| `vixl_import_image(path? \| data_base64?, name)` | Embed a workspace file or base64/data-URL bytes as a layer; returns id, size, bounds |
| `vixl_operations_apply(operations, dry_run, detail)` | Atomic edits; schemas are included directly in tools/list (or on demand in slim mode) |
| `vixl_operation_schema(types)` | Exact JSON Schema for named operation types |
| `vixl_check(checks, targets, safe_area, avoid, thumbnail_width, ...)` | Design problems: bounds, text overlap, WCAG contrast, safe area/reserved zones, thumbnail legibility |
| `vixl_render_preview(variables, max_width, max_height, max_bytes, region)` | Fast preview-resolution PNG; `region` zooms in (up to 8×) |
| `vixl_render_compare(before, after, mode)` | Side-by-side or red-highlight diff of two revisions (`previous`, `head~N`, branch, checkpoint, ID) plus the changed region |
| `vixl_export_file(path, quality, scale, profile, variables, background, overwrite)` | Save full-resolution PNG/JPEG/WEBP/TIFF/AVIF; return only file metadata |
| `vixl_measure`, `vixl_measure_spacing`, `vixl_validate` | Samples, channel statistics, contrast; spacing intent; assertions and profiles |
| `vixl_history(action, ref, count, offset, limit)` | Undo/redo/transactions/branches/checkpoints; newest-first summaries |

Every document tool accepts an optional `document` path. Up to 8 documents stay open per session; addressing one with `document` does not change the active document.

For example, create `poster.vixl` at 4000×3000, import `photo.jpg` as `photo`, apply `[{"type":"move","target":"photo","x":20}]`, run `vixl_check`, request a preview, then export `poster.png`. File paths refer to the machine running Vixl; a client without access to that file system can send image bytes with `data_base64` instead.

Relative and absolute paths are accepted within the workspace. Paths escaping it, including symlinks to outside directories, are rejected. Export refuses existing files unless `overwrite: true` is supplied, and cannot overwrite `.vixl` documents. Subdirectories must already exist. Operation `path`, `linked`, and `font` fields remain unavailable (checked after alias normalization); use the import tool. Services do not enable third-party plugins or linked-file reads.

### Forgiving input and actionable errors

Model-written operations are normalized before validation, the same way in every interface, and each rewrite is reported under `normalized` in the result so the agent learns the canonical form:

- type and key spellings: `rect`/`circle`/`triangle` (→ `shape`), `add-text`, `drop_shadow`, camelCase and kebab-case keys, `font_size`, `fill`/`color`, `layer`/`layer_id` → `target`;
- values: `opacity` 1–100 is a percentage; CSS `rgb()`/`rgba()` with 0–1 alpha; style setting aliases (`offsetX` → `dx`);
- geometry: `x`/`y` accept `"center"` and `"N%"`, `width`/`height` accept `"N%"` (of the canvas, or of the parent group).

Errors are JSON: `{"error", "message", "field", "operation_index", "operation_type", "allowed"?, "suggestions"?}`. Unknown layers suggest close (including case-insensitive) names and list available ones; unknown fields, enum values and operation types get did-you-mean suggestions; a failing batch names the operation that failed.

### Small responses and previews

Tool results are minified JSON text with no duplicated structured copy. Advertised schemas omit pydantic titles and collapse optional fields. `vixl mcp --schema slim` advertises only the operation type names (about half the tool-list size) and the agent fetches fields with `vixl_operation_schema`. The provider-backed planner (`vixl_ai_plan`) is hidden unless `--planner` is passed, because the calling agent already plans its own edits.

The default `detail: "compact"` apply response returns, per stable layer ID, only the **new** values of changed fields (including resolved `bounds`), new layers as `name`/`type`/`bounds` plus their main content, removals, and layer order when it changes. `detail: "full"` returns before/after snapshots. `vixl_measure` summarizes channels as percentiles unless `histogram: "full"`.

Preview defaults: **1024×1024 maximum and 1 MiB of encoded PNG data**, preserving transparency and aspect ratio. Previews render a geometrically scaled copy of the document (JPEG sources decode at reduced scale), so a 24-megapixel document previews in a fraction of a second; documents with canvas-sized effect selections fall back to a full render. `region: [x, y, w, h]` (pixels or percentages) zooms into part of the canvas. File export always uses full resolution unless a scale/profile is requested.

### Typed AI tools

These call your [configured providers](providers.md) with named fields, without CLI flags:

- `vixl_ai_generate(prompt, mode, width, height, seed, name, provider, model, negative_prompt, strength)`; mode is `generate`, `inpaint`, or `img2img`. Supply both dimensions or neither. Inpainting needs a selection.
- `vixl_ai_remove`, `vixl_ai_content_aware_fill`, `vixl_ai_select_subject`, `vixl_ai_remove_background(layer)` and `vixl_ai_select_object(label)`.
- `vixl_ai_analyze(capability, query, provider)`; capability is `describe`, `detect`, or `ocr`. Detections return `objects[].box` as `[x, y, w, h]` document pixels for every provider.
- `vixl_ai_upscale(layer, scale)`, `vixl_ai_regenerate(layer, prompt, seed)`, `vixl_ai_extend(prompt, left, right, top, bottom, seed, name)`.
- `vixl_ai_plan(prompt, apply)` only with `vixl mcp --planner`.

Provider capability limits still apply. Local provider settings and credentials remain on the server. Layer provenance is available through inspection.

### Session performance and consistency

REST and MCP retain loaded projects between calls. A file fingerprint (identity, size and high-resolution modification/change times) triggers a fresh load when an external edit is detected. Edit candidates share immutable history and the content-addressed render and decoded-image caches, so an edit costs roughly the same at revision 10 or 2,000. Thread and interprocess locks serialize edits; saves retain optimistic revision checks and atomic replacement, and store image assets without recompressing them. Failed edits, provider calls or saves discard the cached instance before the next access.

### REST additions

`POST /check` (same options as `vixl_check`), `POST /preview` (`max_width`, `max_height`, `max_bytes`, `region`, …; returns PNG) and `POST /compare` (`before`, `after`, `mode`; returns the summary plus `image_base64`). The REST service is bound to its one document and rejects a `document` field.

## Trusted extensions

Installed Python packages can register entry points:

```toml
[project.entry-points."vixl.filters"]
my_filter = "my_package:filter_image"
[project.entry-points."vixl.providers"]
my_provider = "my_package:Provider"
```

A filter receives `(rgba_image_copy, effect_dict)` and returns a same-size Pillow RGBA image. Provider classes accept `(provider_name, configuration)` and expose `invoke(capability, request) -> dict`; see the HTTP gateway contract for request/result shapes. The provider instance exposes `.name`.

Enable plugins explicitly with `vixl --plugins ...` or `vixl.plugins.enable_plugins()` in Python. Plugins are trusted Python code with the user's process privileges; they are **not sandboxed**. No plugin is imported from a project archive. Codec, layout, validator, and asset-source entry-point categories remain future work; built-in Pillow codecs and the current validator/layout engine cover those functions today.

## New agent resources (0.11)

MCP adds `vixl_resources_list`, `vixl_resource_get`, `vixl_resource_add`, `vixl_template_create`, `vixl_import_font`, `vixl_text_add`, and `vixl_models_list`. Resource discovery needs no open document. Font paths and document destinations remain workspace scoped. `vixl_export_file` accepts `.svg`; `vixl_text_add` permits registered font names while generic service operations continue to reject filesystem font paths.

REST adds GET `/resources/{kind}`, GET/POST `/resources/{kind}/{name}` (POST body `{"value":...}`), POST `/fonts?name=brand` with raw TTF/OTF bytes (16 MiB maximum), and POST `/export` with options such as `{"format":"SVG"}`. Export returns bytes and accepts no destination path. Python exposes the matching `vixl.resources` and `vixl.fonts` helpers. [Detailed examples and boundaries](agent-resources.md).
