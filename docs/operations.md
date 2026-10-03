# Operations and document semantics

See [design tools and template production](design-tools.md) for groups, clipping, shapes, styles, artboards, CSV rendering, measurements, and the other design operations.

`pix schema` or REST `GET /schema` returns the full Draft 2020-12 JSON Schema. MCP exposes the same schema at `pix://operations`. Every editing operation is schema-checked before I/O, then validated against the document and resource limits.

```json
{"operations":[
  {"type":"add","path":"portrait.png","name":"portrait"},
  {"type":"resize","target":"portrait","width":800},
  {"type":"align","target":"portrait","alignment":"top-right","margin":40},
  {"type":"select","shape":"rect","x":0,"y":0,"width":500,"height":300},
  {"type":"effect","target":"portrait","name":"brightness","amount":15},
  {"type":"mask","target":"portrait","action":"from-selection"}
]}
```

`Project.apply` accepts a single operation, an array, or an `operations` envelope. The complete batch succeeds or none of its state/assets/history changes do. File reads may occur during validation; dry-run never saves or changes the live project. Dry-run returns the same before/after document changes that a real apply would make. Generated IDs in separate dry-run and apply calls need not match.

Legacy `operation`/`layer` keys normalize to `type`/`target`. Supported type aliases are `set_opacity`, `set_blend`, `add_layer`, `remove_layer`, `move_layer`, `set_effect`, and `make_selection`. New code should use canonical keys. Unknown fields, malformed dimensions, nonfinite numbers, and unknown types are rejected.

Common operation fields:

| Type | Fields |
| --- | --- |
| add | path **or** embedded asset; name, x, y, linked |
| solid / gradient | name, width, height, color **or** start/end/direction |
| text | text, name, font, size, color, align, spacing, x/y |
| text-set | target; text, size, color, align, spacing, stroke_width/stroke_color |
| move / resize / scale | target; x/y/relative **or** width/height **or** value factor |
| rotate / opacity / blend | target, value |
| align | target, alignment, margin |
| constrain | target, constraints object |
| select | shape, shape-specific coordinates/color/target/asset; mode, feather |
| mask | target, action; path for import |
| effect | target, name, amount; seed, radius, strength, black/white, points |
| effect-set / enable / disable / remove | target, effect ID or 1-based index; amount etc. for set |
| variable | name, value; or delete: true |
| preset-save / preset-apply | name, target; overrides for apply |
| canvas | width, height, background or preset |

History transitions and project lifecycle use explicit methods / commands, not editing operations. Provider results are recorded as `ai-result` / `ai-mask` audit events; those audit events are not public operation types. History snapshots and embedded assets reproduce their pixels without recontacting a provider.

## `.pix` format, version 1

A ZIP archive contains `project.json`, `assets/<sha256>.png`, `masks/<sha256>.png`, and optionally `fonts/<sha256>.ttf`. Imports normalize orientation and convert to RGBA8 PNG. All members are checksummed. No archive paths are extracted to disk.

The manifest stores current state, stable object IDs, the history DAG with complete state snapshots, branch/checkpoint references, redo stack, and an optional open transaction. Image bytes are shared between revisions by content hash. Asset hashes identify bytes; revision and object IDs are intentionally unique, not pixel-deterministic. Archive timestamps/IDs are not intended for byte-identical builds.

Rendering resolves variables and acyclic layout constraints, loads source layers, crops/resizes/flips/rotates, applies effects with their captured selection masks, applies the layer mask and opacity, then composites bottom-to-top. Raster sources and text stay editable. Layer masks are defined in transformed local bounds; effect selections are defined in canvas coordinates. These conventions are explicit so scripts can reason about moving a selected/filtered layer.

Default text size tracks the text's rendered bounds. Explicit resize turns off automatic sizing; editing text turns it back on. Imported fonts are embedded. The bundled default font makes basic text independent of host font installation. Exact raster output can still vary with Pillow/FreeType versions; pin your environment for reproducible builds.

History is snapshot-based, not a replay engine. Undo, checkpoints, branching and comparison use captured state and assets. AI replay is a separate network operation and may vary with provider/model revisions even when a seed is retained.
