# Architecture and operational boundaries

Vixl is a headless application designed for autonomous AI agents; humans can use the same interfaces.

```text
CLI / shell / scripts / Python / REST / MCP / AI planner
                         |
             schema + canonical operations
                         |
      atomic candidate document + state validation
                         |
        history snapshots + embedded asset store
                         |
   variables / constraints / Pillow + NumPy renderer
                         |
                    PNG / JPEG / WebP / TIFF / AVIF / SVG
```

`project.py` owns document lifecycle, candidate-state commits, history and archives. `operations.py` changes document state; it has no dependency on CLI output. `render.py` converts state into pixels without changing it. `commands.py` compiles the human syntax; scripts use the same compiler. `ai.py` delegates inference to providers and inserts ordinary assets/masks. `interfaces.py` exposes the shared boundary to REST and MCP. `schema.py` publishes the operation contract. `validation.py` checks structures, design rules, and dependencies.

The implementation uses Python, Pillow, and NumPy to cover the complete editing/automation workflow with a reusable API. The specification's Rust-core recommendation is a future performance/distribution option, not the current implementation. Image operations are deterministic for a fixed document and imaging-library/font environment; random filters use explicit seeds. AI inference and provider availability are external.

## Persistence and concurrency

A successful CLI editing command autosaves via a same-directory temporary file, `fsync`, and atomic replace. An advisory project lock serializes CLI and service read-modify-write cycles. Direct Python saves use an optimistic archive hash check to reject stale writes. A loader hashes the exact archive bytes it parses, preventing a concurrent replacement from being mistaken for the same revision.

History is a DAG of revisions. Each revision stores a structural delta from its parent, with a full snapshot every 32 revisions on a chain, so memory and file size grow with what changed rather than with document size × edits. Historical states are reconstructed, then validated, when a revision is restored. When `max_history` (2,000) is reached, the oldest revisions not referenced by the head, a branch, a checkpoint or the redo stack are squashed (their children become snapshots), so editing never stops. Font assets are ZIP-compressed; already-compressed images remain stored without recompression. Assets are content-addressed and shared; assets no remaining revision references are dropped on save. Open transactions preserve provisional state across commands, then commit as one history entry or restore the previous state. Transactions provide rollback, not isolation from other clients. Use separate projects or a single coordinating client for simultaneous independent editing.

## Resource policy

Defaults (`vixl.model.Limits`):

- 40 million pixels per canvas/layer; 16,384 pixels per dimension.
- 512 layers; 256 effects per layer.
- 64 MiB per imported asset/provider response.
- 256 MiB per archive and its expanded contents.
- 1,000 operations per submitted batch; 2,000 history revisions (older ones are squashed, not refused).
- At most 10,000 archive entries.
- Layer-render cache: 16 entries / 64 MiB, with entries under 32 MiB; decoded-asset cache: 256 MiB.

`--max-pixels` adjusts the pixel budget; Python APIs can pass a complete `Limits` instance. These are input/allocation bounds, **not a hard resident-memory or CPU quota**. Float blending and snapshot copies can use multiples of image size. Use operating-system/container limits for untrusted workloads and reduce pixel/layer/history limits on small machines. CLI processes do not share render caches; caching benefits a reused Python `Project` instance. REST/MCP cache the active document, reloading when the on-disk file changes, and serialize read/write requests for persistence/concurrency correctness.

## Trust and security

Archive members are validated and read in memory, never extracted; duplicate/unsafe entries, missing assets, bad checksums, cyclic history, unsupported format versions, and oversized expanded content are rejected. Images are decoded with decompression-bomb handling and explicit dimensions. Do not disable these limits for unknown files.

Scripts compile only supported Vixl operations; they do not run shell/Python code. Assertions use a parsed comparison grammar. JSON operations are schema-checked, including unknown-field rejection and finite-number checks. Service clients cannot request arbitrary host file imports, linked files, custom font paths, or Python plugins. Linked files are opt-in for the CLI/Python API and remain external dependencies.

Plugins and local provider configuration are trusted code/configuration. A provider may transmit the current rendered image, selection, text and document metadata to its configured service. Credentials are referenced by environment-variable name and not copied into Vixl's request provenance. Provider metadata should contain provenance only. HTTP adapters preserve TLS verification and do not follow redirects. They fetch result URLs only where a service requires it: FLUX polling and signed result URLs must be HTTPS on approved hosts (`*.bfl.ai`, `*.blob.core.windows.net`, configurable) and are fetched without credentials. ComfyUI files are fetched only from the configured server.

The REST service defaults to loopback, validates host headers without a token, requires a token for non-loopback binding, and limits bodies before JSON parsing. Use a TLS reverse proxy for remote use. API tokens do not create a multi-tenant permission system. Image/font codecs and optional plugins still execute native/Python code in-process; a container remains the appropriate boundary for hostile inputs.

## Verification

The test suite covers pixel-level blending, selection boundaries, effect disable/re-enable, masks, text/rasterization, variables, constraints and cycles, archive round trips, malformed archives, resource limits, optimistic write conflicts, history/transactions, subprocess CLI and binary pipelines, batch processing, authenticated REST and request limits, real MCP stdio negotiation/tool calls, and mocked AI adapter contracts. Live AI services are not required by tests.
