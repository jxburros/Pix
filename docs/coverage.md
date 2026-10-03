# Specification coverage

This is a working first implementation spanning the six roadmap stages in the supplied [specification](product-spec.md). It is not a claim of production maturity or complete GIMP parity. Version 0.8.0 adds workspace file tools, typed AI tools, inline operation schemas, bounded previews, compact edit summaries, and cached service sessions on top of Windows installation and automatic updates; the design tools below extend that scope.

| Specification area | Implemented |
| --- | --- |
| Core document (0.1) | New/open/save; ZIP `.vixl` format; embedded raster/font/mask assets; stable layer IDs; editable text; transforms, crop, ordering, opacity and visibility; common blend modes; selections and masks; adjustments and filters; PNG/JPEG/WebP/TIFF export; JSON inspection; shell; undo/redo |
| Automation (0.2) | Vixl command scripts; batch and per-layer edits; effect presets with overrides; checkpoints; variables and render overrides; design assertions/profiles; alignment; export profiles; stdin JSON and image pipelines |
| Advanced documents (0.3) | Acyclic anchor constraints; responsive canvas presets; branching history and visual comparison; nondestructive effect stacks; seeded filters; bounded in-process layer cache |
| Vision (0.4) | Provider calls for description, object/face detection, OCR, segmentation and background masks; semantic selection converts returned masks into ordinary selections |
| Generation (0.5) | Provider interface; OpenAI/ComfyUI/Automatic1111/HTTP adapters; text-to-image, image-to-image, selected inpainting, canvas extension/outpainting, upscaling; retained generation/source/mask provenance; regeneration |
| Agents (0.6) | Python API, REST, official-SDK MCP server; operation JSON Schema; atomic batches; dry-run change summaries; persistent transactions; validation and rendered previews |
| Design tools | Groups/clipping; procedural shapes; five layer styles; alignment/distribution; linked text styles/swatches; artboards; CSV data sets; image frames/replacement; repeats/blends; pixel measurements; richer gradients; adjustment layers; histogram corrections; LUTs; comps; text boxes/warps/polylines; guides/grids; shape silhouette boolean operations; symbols; multi-scale screen export; provider-backed Remove/Fill/Select Subject |
| Spacing and pixel animation (0.9) | Explicit equal-gap/balance/expected-spacing checks; palette-indexed pixel grids and integer drawing; saved timed frames; GIF/APNG/sprite-sheet export with nearest-neighbor scaling; compact agent inspection |
| Further concepts | Opt-in linked images; dependencies/reproducibility inspection; opt-in filter/provider entry-point plugins; bounded archives and images; structured errors; test/CI workflow |

## Explicit boundaries

- **AI needs a real configured service.** Vision segmentation and background removal require a mask-producing HTTP/ComfyUI provider. OpenAI provides multimodal description/detection/OCR and planning, not a native segmentation implementation here. Live provider calls were not exercised in the development environment. Mocked adapter tests validate request/response behavior, not model quality.
- **The core is Python**, not Rust. A Windows executable bundles the Python runtime. No C ABI, Rust core, or optimized tile/GPU renderer is supplied.
- **RGBA8/sRGB-style pixel processing.** No ICC-managed workflow, CMYK prepress, high-bit-depth editing, RAW development, or embedded camera metadata preservation. Input orientation is normalized. AVIF availability depends on Pillow's codecs.
- **Raster-oriented output with procedural shapes.** Shapes retain geometry, groups and clipping remain editable, and pathfinder retains shape snapshots. SVG/Bézier editing, skew/perspective/matrix transforms, brushes, pressure input, full animation timelines, and PSD/XCF compatibility are not implemented. See [design tools](design-tools.md) for group raster-scaling and shape-combination semantics.
- **Basic text layout.** Editable multiline text, wrapping/fitting, raster warp presets, polyline glyph placement, linked character/paragraph styles, alignment, spacing, stroke and font embedding are present. This is not an advanced publishing/shaping engine.
- **Explicit layout semantics.** One anchor per axis, dependency cycles rejected. No general constraint solver. Outpainting freezes existing constraints at their current positions.
- **Templates use embedded asset IDs.** Ordinary render variables cannot load arbitrary paths. Image-slot variables reference embedded asset IDs. The explicit local CSV data-set workflow can import image paths relative to its CSV file.
- **Scripts are a command language.** No alternate English-like parser, control-flow language, shell execution, AI steps, or file lifecycle/export commands inside a `.vixlscript`. Use the Python API or shell orchestration around scripts.
- **Snapshot history.** No branch merging, replay-based collaboration, asset garbage collection, or history compaction. Comparison renders two captured states side by side. Open transactions are not isolated from other clients.
- **Bounded inputs, not a process sandbox.** There is no `--max-memory` hard cap or universal execution timeout. Use OS/container resource limits. Installed plugins are trusted code. Filter/provider plugins exist; other plugin categories are deferred.
- **Headless interfaces only.** Desktop GUI, TUI, web editor, template marketplace, and dedicated AI Server Studio product integration remain future front ends. Any MCP client can use the implemented server.

The exact supported operation syntax is discoverable through `vixl schema` and documented in [commands](commands.md) and [operations](operations.md). Unsupported features fail explicitly or are absent from those interfaces.
