# Python, REST, MCP, and extension interfaces

See [spacing checks and pixel animation](pixel-animation-spacing.md) for the 0.9.0 tools and API examples.

See [design tools and template production](design-tools.md) for groups, clipping, shapes, styles, artboards, CSV rendering, measurements, and the other design operations.

## Python

```python
from pix import Project, PixError
from pix.model import Limits

project = Project.load("poster.pix", limits=Limits(max_pixels=16_000_000))
proposal = [{"type": "opacity", "target": "logo", "value": 0.7}]
print(project.apply(proposal, dry_run=True))
project.apply(proposal)
project.save()
```

`Project.apply(..., detail="compact")` returns changed fields keyed by stable layer ID; the Python API keeps `detail="full"` as its compatibility default.

`Project.render()` returns a Pillow RGBA image. `Project.export()` returns encoded bytes, optionally writing to a path. `Project.inspect()` returns an independent JSON-serializable state description. History methods: `undo`, `redo`, `branch`, `checkpoint`, `checkout`, `begin`, `commit`, `rollback`.

Loading does not implicitly trust linked image paths; use `allow_linked=True` only when those local file references are intended. Direct Python APIs are trusted local APIs and can import files. Exceptions expose `PixError.code`, `.details`, and `.as_dict()`.

## REST

```bash
python -m pip install -e '.[server]'
pix -p poster.pix serve
```

Default binding is `127.0.0.1:8765`. OpenAPI is at `/docs`. To bind beyond loopback, configure a bearer token with `PIX_API_TOKEN` and use `--host 0.0.0.0`; use TLS at a reverse proxy. `--token-env NAME` selects a different environment variable. A configured token protects every route, including docs. Without a token, host-header validation restricts requests to loopback names. This is a local single-user service, not a multi-tenant hosted product.

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

The Windows installer includes MCP. For source installs, install `.[mcp]`. Give Pix an existing workspace directory that contains the images/documents the model should edit:

```powershell
pix mcp --workspace "C:\Users\jeffr\Pictures\Pix"
```

The workspace can start without any `.pix` documents. MCP runs over stdio using the official SDK; stdout contains protocol messages only. Configure your client to start it (escape Windows backslashes in JSON):

```json
{
  "mcpServers": {
    "pix": {
      "command": "pix",
      "args": ["mcp", "--workspace", "C:\\Users\\jeffr\\Pictures\\Pix"]
    }
  }
}
```

If the client cannot find `pix` on PATH, use the absolute executable path, normally `C:\Users\jeffr\AppData\Local\Pix\bin\pix.exe` for the Windows installer. Restart the client after installing/updating or changing its configuration. On macOS/Linux, use your installed `pix` executable and a workspace such as `/home/you/Pictures/Pix`.

Existing `pix --project /absolute/path/poster.pix mcp` configurations still work: they open that document and use its parent directory as the workspace. You can also pass `--workspace` explicitly; the starting project must be within it.

### Tools and workflow

| Tool | Purpose |
| --- | --- |
| `pix_workspace_list(directory, offset, limit)` | Discover workspace paths; default 100 entries per page |
| `pix_document_create(path, width, height, background)` | Create and activate a new `.pix`; refuses overwrites |
| `pix_document_open(path)` | Switch active document; all previous successful edits are already saved |
| `pix_document_inspect(target?)` | Inspect the whole document, or one layer by ID/name |
| `pix_import_image(path, name)` | Read an image file into an embedded layer without passing base64 |
| `pix_operations_apply(operations, dry_run, detail)` | Atomic edits; schemas are included directly in tools/list |
| `pix_render_preview(variables, max_width, max_height, max_bytes)` | Native MCP image content, bounded dimensions and encoded size |
| `pix_export_file(path, quality, scale, profile, variables, background, overwrite)` | Save full-resolution PNG/JPEG/WEBP/TIFF/AVIF; return only file metadata |
| `pix_validate(profile, rules)` | Check bounds, profiles, assertions |
| `pix_history(action, ref, count, offset, limit)` | Undo/redo/transactions/branches/checkpoints; paginated summaries |

For example, create `poster.pix` at 4000×3000, import `photo.jpg` as `photo`, apply `[{"type":"move","target":"photo","x":20}]`, request a preview, then export `poster.png`. Put the photo in the workspace first. File paths refer to the machine running Pix; a remote client cannot use paths on a different machine unless it transfers the files there separately.

Relative and absolute paths are accepted within the workspace. Paths escaping it, including symlinks to outside directories, are rejected. Export refuses existing files unless `overwrite: true` is supplied, and cannot overwrite `.pix` documents. Subdirectories must already exist. Operation `path`, `linked`, and `font` fields remain unavailable; use the import tool. Services do not enable third-party plugins or linked-file reads.

### Small responses and previews

Canonical operation variants, required fields, effect names and enums are embedded in `pix_operations_apply`'s input schema. The model does not need to fetch `pix://operations`; that resource remains available as a reference. Repeated effect aliases are omitted from the advertised schema: use `{"type":"effect","name":"blur","radius":2}`.

The default `detail: "compact"` response includes changed fields keyed by stable layer ID, added/removed layers, and layer order when it changes. A one-layer move does not echo the other layers. `detail: "full"` explicitly requests before/after snapshots. `dry_run: true` returns the same kind of summary without modifying the document. Inspect a single layer with `target` when more detail is needed. History lists default to 20 node summaries without replaying their operation payloads.

Preview defaults: **1024×1024 maximum and 1 MiB of encoded PNG data**, with no upscaling and preserved transparency/aspect ratio. If the PNG exceeds the byte budget, it shrinks further. You may request dimensions up to 4096 and a byte limit from 64 KiB to 4 MiB. MCP base64 transport adds roughly one third to the encoded byte size. Previews do not resize the document; file export uses full resolution unless a scale/profile is requested. Rendering still computes the full canvas before downsampling, so complex large images can take time.

### Typed AI tools

These call your [configured providers](providers.md) with named fields, without CLI flags:

- `pix_ai_generate(prompt, mode, width, height, seed, name, provider, model, negative_prompt, strength)`; mode is `generate`, `inpaint`, or `img2img`. Supply both dimensions or neither. Inpainting needs a selection.
- `pix_ai_remove_background(layer, provider)` and `pix_ai_select_object(label, provider)`.
- `pix_ai_plan(prompt, apply, provider)`; defaults to a proposal without applying it.
- `pix_ai_analyze(capability, query, provider)`; capability is `describe`, `detect`, or `ocr`.
- `pix_ai_upscale(layer, scale, provider)`, `pix_ai_regenerate(layer, prompt, seed, provider)`, and `pix_ai_extend(prompt, left, right, top, bottom, seed, name, provider)`.

Provider capability limits still apply. Local provider settings and credentials remain on the server. Layer provenance is available through inspection. In 0.8.0, `pix_ai(command,args)` is replaced by these tools, and `pix_import_image(image_base64,...)` changes to `pix_import_image(path,...)`. Reconnect clients to refresh their tool lists. CLI/Python AI calls remain compatible.

### Session performance and consistency

REST and MCP retain the loaded project between calls. A file fingerprint (identity, size and high-resolution modification/change times) triggers a fresh load when an external edit is detected. Reads reuse the render cache. Thread and interprocess locks serialize edits; saves retain optimistic revision checks and atomic replacement. Failed edits, provider calls or saves discard the cached instance before the next access. Switching documents loads the selected file. Successful mutations still save the project archive; caching removes repeated archive loading/validation, not the cost of rendering or saving.

## Trusted extensions

Installed Python packages can register entry points:

```toml
[project.entry-points."pix.filters"]
my_filter = "my_package:filter_image"
[project.entry-points."pix.providers"]
my_provider = "my_package:Provider"
```

A filter receives `(rgba_image_copy, effect_dict)` and returns a same-size Pillow RGBA image. Provider classes accept `(provider_name, configuration)` and expose `invoke(capability, request) -> dict`; see the HTTP gateway contract for request/result shapes. The provider instance exposes `.name`.

Enable plugins explicitly with `pix --plugins ...` or `pix.plugins.enable_plugins()` in Python. Plugins are trusted Python code with the user's process privileges; they are **not sandboxed**. No plugin is imported from a project archive. Codec, layout, validator, and asset-source entry-point categories remain future work; built-in Pillow codecs and the current validator/layout engine cover those functions today.
