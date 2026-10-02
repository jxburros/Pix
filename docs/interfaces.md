# Python, REST, MCP, and extension interfaces

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
| `POST /operations` | `{operations: [...], dry_run: false}` → change summary |
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

Service sessions fix the project path when launched. Operation `path`, `linked`, and `font` fields are rejected; import image bytes with `/assets`. Services do not enable third-party plugins or linked-file reads. Local AI configuration is trusted, and services can invoke it. Do not share API access with users who should not be able to use your configured AI service. Authentication is all-or-nothing; there are no per-user roles or quotas.

## MCP

```bash
python -m pip install -e '.[mcp]'
pix --project /absolute/path/poster.pix mcp
```

Example client configuration:

```json
{
  "mcpServers": {
    "pix": {
      "command": "/absolute/path/Pix/.venv/bin/pix",
      "args": ["--project", "/absolute/path/poster.pix", "mcp"]
    }
  }
}
```

Tools: `pix_document_inspect`, `pix_operations_apply`, `pix_render_preview`, `pix_validate`, `pix_history`, `pix_import_image`, `pix_ai`. The renderer returns native MCP image content, not a host file path. The `pix://operations` resource provides the full operation schema. MCP uses the official Python SDK over stdio; stdout contains protocol messages only.

The MCP service shares the REST project boundary. The client selects the project at server startup, submits operations against stable IDs, validates, and requests previews. Multi-operation edits are atomic. `dry_run: true` lets an agent inspect consequences first.

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
