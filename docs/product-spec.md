# Vixl

Vixl is a headless application designed for autonomous AI agents; humans can use the same interfaces. This supplied specification is historical design context; [coverage](coverage.md) describes implemented behavior.
## Programmable, Scriptable, AI-Native Image Editing Engine

**Status:** Concept / Product Specification
**Working Name:** Vixl
**Primary Interface:** Command Line
**Secondary Interfaces:** Interactive shell, API, MCP/agent interface, future TUI/GUI
**Core Philosophy:** A deterministic image-document engine designed primarily for autonomous AI agents, also usable by humans and scripts.

---

# 1. Product Summary

Vixl is a command-line image editing application inspired by the document model of programs such as GIMP, but intentionally simpler, more programmable, and designed from the beginning for automation and AI.

Rather than attempting to recreate the full GIMP interface in a terminal, Vixl treats image editing as a set of structured operations applied to a persistent editable document.

The basic model is:

```text
Image Document
    ↓
Layers
    ↓
Selections / Masks
    ↓
Transforms / Adjustments / Filters
    ↓
Rendering
    ↓
Export
```

Vixl should support traditional image-editing operations while adding capabilities that are difficult or unnatural in conventional GUI image editors, including:

- deterministic command-line editing
- structured machine-readable document state
- branchable editing history
- parameterized designs
- layout constraints
- batch operations
- automatic validation
- semantic object selection
- natural-language editing
- AI image generation and inpainting
- first-class AI-agent control

Vixl should ultimately be considered an **image editing engine with a CLI**, rather than simply a CLI application.

This distinction allows the same engine to eventually power:

- a command-line interface
- an interactive terminal environment
- a TUI
- a GUI
- Python bindings
- REST APIs
- MCP tools
- AI Server Studio integrations
- automated asset-generation workflows

---

# 2. Product Vision

Vixl should occupy the space between:

- GIMP
- ImageMagick
- scripting libraries such as Pillow
- design automation software
- generative image tools
- AI agent infrastructure

The goal is not to reproduce every feature available in professional graphics software.

Instead, Vixl should make the **most useful image editing concepts simple, composable, inspectable, automatable, and reproducible.**

A core principle is:

> Every meaningful action should be representable as structured data.

For example:

```json
{
  "operation": "set_opacity",
  "layer": "portrait",
  "value": 0.65
}
```

The CLI, API, interactive shell, and AI interfaces should all ultimately generate these same underlying operations.

---

# 3. Primary Differentiator

Traditional image editors are primarily designed around:

```text
Human
  ↓
Mouse / Keyboard
  ↓
Graphical Interface
  ↓
Image Editor
```

Vixl should support this model instead:

```text
Human / Script / AI Agent
            ↓
     Structured Operations
            ↓
       Vixl Engine
            ↓
     Editable Document
            ↓
         Renderer
```

This makes automation and AI usage architectural concepts rather than plugins added after the fact.

---

# 4. Core Design Principles

## 4.1 Deterministic

An operation should produce predictable results.

Traditional editing operations should not depend on hidden application state.

---

## 4.2 Inspectable

Users and software should be able to ask Vixl what exists in a document.

Example:

```bash
vixl inspect --json
```

Vixl should provide structured information about:

- canvas
- layers
- positions
- dimensions
- masks
- effects
- fonts
- relationships
- generation metadata
- history

---

## 4.3 Scriptable

Anything that can be done interactively should be possible through commands or APIs.

---

## 4.4 Nondestructive Where Practical

Vixl should prefer document operations over permanently modifying source imagery.

---

## 4.5 Agent-Friendly

AI agents should never need to simulate mouse movements.

They should interact directly with the document model.

---

## 4.6 Modular

The image engine must not depend on the CLI.

The ideal architecture is:

```text
Interfaces
 ├── CLI
 ├── Interactive shell
 ├── API
 ├── MCP
 ├── GUI
 └── TUI
       ↓
Operation Layer
       ↓
Document Engine
       ↓
Rendering / Imaging Engine
```

---

# 5. Target Users

Vixl could serve several distinct audiences.

### Developers

Developers who want image manipulation without creating custom graphics code.

### Designers

Designers who want repeatable and parameterized workflows.

### Automation Engineers

People producing large numbers of related assets.

### AI Developers

Developers building multimodal agents.

### AI Agents

Software capable of inspecting a project, making changes, rendering previews, and evaluating results.

### Creators

Musicians, artists, streamers, game developers, and other creators producing repetitive visual material.

---

# 6. Core Concepts

The initial document model should revolve around seven concepts:

1. Canvas
2. Layers
3. Selections
4. Masks
5. Transforms
6. Adjustments / Filters
7. Export

Additional concepts can build on this foundation.

---

# 7. Project Files

Vixl should use its own editable project format.

Example:

```text
poster.vixl
```

A `.vixl` file could internally be a ZIP archive.

Example:

```text
poster.vixl
│
├── project.json
│
├── assets/
│   ├── a81e23.png
│   ├── c12b99.jpg
│   └── logo.svg
│
├── masks/
│   ├── mask-001.png
│   └── mask-002.png
│
└── previews/
    └── thumbnail.webp
```

`project.json` stores the document structure.

Example:

```json
{
  "width": 1920,
  "height": 1080,
  "color_mode": "rgba8",
  "layers": [
    {
      "id": "layer-1",
      "name": "Background",
      "type": "raster",
      "asset": "assets/a81e23.png",
      "x": 0,
      "y": 0,
      "opacity": 1,
      "blend": "normal",
      "visible": true
    }
  ]
}
```

This architecture separates:

- document state
- source assets
- generated assets
- masks
- cached renders

---

# 8. Basic CLI

Example workflow:

```bash
vixl new 1920x1080 --background "#111111"

vixl add photo.jpg --name portrait

vixl resize portrait --width 900

vixl move portrait --x 510 --y 40

vixl brightness portrait +10

vixl contrast portrait +15

vixl add logo.png --name logo

vixl move logo --x 60 --y 920

vixl opacity logo 0.75

vixl export output.png
```

---

# 9. Command Namespaces

Commands should use consistent namespaces.

Example:

```bash
vixl layer add image.png
vixl layer remove portrait
vixl layer rename portrait hero
vixl layer duplicate hero
vixl layer move hero 300 100
vixl layer scale hero 800 600
vixl layer rotate hero 15
```

Common commands can receive short aliases:

```bash
vixl add image.png
vixl rm portrait
vixl mv portrait 300 100
vixl scale portrait 800x600
vixl rotate portrait 15
```

---

# 10. Current Layer

Vixl should support the concept of an active layer.

Example:

```bash
vixl select-layer portrait

vixl resize --width 800
vixl contrast +15
vixl saturation -10
vixl blur 4
```

This prevents every command from requiring a layer name.

---

# 11. Status Command

```bash
vixl status
```

Example output:

```text
Project: poster.vixl
Canvas: 1920 × 1080
Color: RGBA / 8-bit

Selected layer:
  portrait
  1200 × 900
  Position: 360, 90
  Opacity: 100%
  Blend: normal

History:
  23 operations
```

---

# 12. Layer Listing

```bash
vixl layers
```

Example:

```text
ID   NAME          SIZE        POS        OPACITY   VISIBLE
4    Title         1920x240    0,120      100%      yes
3    Logo          480x220     80,760     85%       yes
2    Portrait      1200x1080   360,0      100%      yes
1    Background    1920x1080   0,0        100%      yes
```

Machine-readable output should also be available.

```bash
vixl layers --json
```

---

# 13. Raster Layers

Raster layers should support:

- PNG
- JPEG
- WebP
- TIFF
- possibly AVIF
- other formats through codecs

Basic operations:

```bash
vixl layer add photo.jpg
vixl layer duplicate portrait
vixl layer hide portrait
vixl layer show portrait
vixl layer remove portrait
vixl layer rename portrait hero
```

---

# 14. Layer Ordering

```bash
vixl layer raise portrait
vixl layer lower portrait

vixl layer top logo
vixl layer bottom background
```

Possible explicit form:

```bash
vixl layer reorder portrait --above background
```

---

# 15. Transformations

Vixl should support:

```bash
vixl move portrait 100 200

vixl scale portrait 50%

vixl resize portrait 800x600

vixl rotate portrait 15

vixl flip portrait horizontal

vixl flip portrait vertical
```

Additional transforms can eventually include:

- skew
- perspective
- crop
- arbitrary transformation matrix

---

# 16. Alignment

CLI editing becomes much easier when semantic alignment is supported.

Examples:

```bash
vixl align logo center
vixl align logo top
vixl align logo top-right
vixl align portrait center-x
```

Margins:

```bash
vixl align logo top-right --margin 40
```

This should be preferred over requiring exact coordinates for routine layout.

---

# 17. Selections

Initial selections should include:

```bash
vixl select rect 100 100 500 300

vixl select ellipse 400 200 300 300

vixl select all

vixl select none

vixl select invert
```

Color selection:

```bash
vixl select color "#ffffff" --tolerance 15
```

Alpha selection:

```bash
vixl select alpha portrait
```

Operations should respect the current selection where appropriate.

Example:

```bash
vixl select rect 0 0 1920 300
vixl blur 12
```

---

# 18. Masks

Example operations:

```bash
vixl mask create portrait

vixl mask from-selection portrait

vixl mask invert portrait

vixl mask disable portrait

vixl mask enable portrait

vixl mask delete portrait
```

Masks should remain ordinary grayscale image data internally.

This allows AI-generated masks and manually generated masks to use the same system.

---

# 19. Image Adjustments

Core adjustments:

```bash
vixl brightness +20
vixl contrast -10
vixl saturation +15
vixl hue 30
vixl exposure 0.5
vixl gamma 1.1
```

Additional adjustments may include:

- temperature
- tint
- shadows
- highlights
- levels
- curves

---

# 20. Filters

Core filters:

```bash
vixl blur 8
vixl sharpen 2
vixl grayscale
vixl invert
vixl posterize 6
vixl threshold 128
```

Advanced syntax:

```bash
vixl filter gaussian-blur --radius 12

vixl filter noise --amount 0.08

vixl filter vignette --radius 0.7 --strength 0.4
```

A standardized filter interface will allow new filters to be added without cluttering the root CLI namespace.

---

# 21. Nondestructive Effects

Where practical, filters should be represented as operations attached to layers.

Example:

```text
Portrait
 ├── Brightness +8
 ├── Contrast +12
 ├── Saturation -6
 └── Gaussian Blur 1.5
```

Individual effects can then be changed or disabled.

Example:

```bash
vixl effects portrait
```

```text
1 brightness +8
2 contrast +12
3 saturation -6
4 gaussian-blur 1.5
```

Potential operations:

```bash
vixl effect disable portrait 4

vixl effect set portrait 2 --amount 20

vixl effect remove portrait 3
```

---

# 22. Text Layers

Text should be supported early.

Example:

```bash
vixl text add "FRIENDS AND FLAMES" \
  --font "Inter Bold" \
  --size 96 \
  --x center \
  --y 120
```

The text should remain editable.

Example:

```bash
vixl text title --text "FRIENDS & FLAMES"

vixl text title --size 120

vixl text title --align center

vixl text title --color "#ffffff"
```

Rasterization:

```bash
vixl rasterize title
```

Before rasterization, the underlying text content and formatting should remain available.

---

# 23. Blend Modes

Initial blend modes should include common options:

- normal
- multiply
- screen
- overlay
- darken
- lighten
- difference

Example:

```bash
vixl blend texture multiply
```

---

# 24. Interactive Shell

Running:

```bash
vixl
```

should open an interactive editing environment.

Example:

```text
VIXL 0.1
poster.vixl · 1920×1080 · 6 layers

poster > layers

  6  text
  5  logo
> 4  portrait
  3  gradient
  2  texture
  1  background

poster > opacity 80

poster > move x +20

poster > blur 4

poster > undo

poster > export poster-final.png
```

This provides a more natural interface for humans while using exactly the same underlying operation system.

---

# 25. Undo and Redo

Basic history:

```bash
vixl undo

vixl undo 3

vixl redo

vixl history
```

Example:

```text
27  Set opacity: logo → 75%
26  Move logo → 60,920
25  Add logo.png
24  Contrast portrait → +15
23  Brightness portrait → +10
```

---

# 26. Checkpoints

Users should be able to create named states.

```bash
vixl checkpoint initial-layout

vixl checkpoint finished-color
```

They can later return to them.

```bash
vixl checkout initial-layout
```

---

# 27. Branchable Editing History

Vixl should eventually treat creative history similarly to lightweight version control.

Example:

```bash
vixl checkpoint before-color

vixl brightness +15
vixl contrast +20

vixl branch vivid

vixl checkout before-color

vixl saturation -30

vixl branch muted
```

History:

```text
main
├── vivid
└── muted
```

Possible command:

```bash
vixl branches
```

Comparison:

```bash
vixl compare vivid muted
```

Vixl could render both versions side by side or generate separate outputs.

---

# 28. Presets

A sequence of operations can be saved.

Example workflow:

```bash
vixl contrast +12
vixl saturation -8
vixl temperature +300
vixl grain 0.07
vixl vignette 0.15

vixl preset save gritty-photo
```

Application:

```bash
vixl preset apply gritty-photo portrait
```

Inspection:

```bash
vixl preset show gritty-photo
```

Parameter override:

```bash
vixl preset apply gritty-photo \
  --set grain=0.03
```

---

# 29. Vixl Scripts

Vixl should eventually support script files.

Example:

```text
portrait-cleanup.vixlscript
```

Possible contents:

```text
brightness +4
contrast +8
saturation -3
sharpen 1.2
```

Execution:

```bash
vixl run portrait-cleanup.vixlscript
```

A Vixl script should ideally compile into normal operations rather than use an independent execution engine.

---

# 30. Batch Editing

CLI applications are particularly suited to bulk processing.

Example:

```bash
vixl batch ./photos/*.jpg \
  --run portrait-cleanup.vixlscript \
  --output ./processed/
```

Project-wide operations:

```bash
vixl each layer --type image -- saturation -10
```

Pattern filtering:

```bash
vixl each layer --name "card-*" -- resize 750x1050
```

---

# 31. Parameterized Designs

Vixl projects should optionally define variables.

Example:

```text
artist = "Jeffrey X Guntly"
title = "Friends and Flames"
date = "October 30"
cover = "cover.jpg"
```

The document can reference these values.

Example:

```bash
vixl variable set title "Permission"
```

Rendering with overrides:

```bash
vixl render \
  --set title="Permission" \
  --set cover=permission.jpg \
  --out permission-poster.png
```

This turns a Vixl document into a reusable design template.

Potential applications include:

- social graphics
- promotional posters
- thumbnails
- cards
- merchandise graphics
- album announcements
- game assets
- banners

---

# 32. Layout Constraints

Vixl should eventually allow positions to be defined relative to other objects rather than fixed pixel coordinates.

Example:

```bash
vixl constrain logo \
  --right canvas.right-40 \
  --top canvas.top+40
```

Text:

```bash
vixl constrain title \
  --center-x canvas \
  --below portrait 60
```

If the canvas changes size, constrained elements can automatically reposition.

This enables responsive design behavior.

---

# 33. Smart Canvas Resizing

With constraints enabled:

```bash
vixl canvas resize 1080x1080
```

could reflow the design automatically.

Potential presets:

```bash
vixl canvas preset instagram-square

vixl canvas preset youtube-thumbnail

vixl canvas preset story
```

The same design could therefore produce multiple formats.

---

# 34. Validation

Vixl should allow rules to be applied to projects.

Examples:

```bash
vixl assert canvas.width == 1920

vixl assert canvas.height == 1080

vixl assert layer.logo.exists

vixl assert layer.logo.bounds within canvas

vixl assert text.title.font-size >= 48
```

---

# 35. Validation Profiles

A reusable validation profile could be run:

```bash
vixl validate instagram-post
```

Example output:

```text
✓ Canvas ratio 1:1
✓ RGB image
✓ All layers within canvas
⚠ Text "subtitle" is only 21 px tall
✗ Export exceeds 8 MB
```

This is particularly useful for automation and AI agents because they can determine whether their output satisfies requirements.

---

# 36. Machine-Readable Inspection

Commands should generally support:

```bash
--json
```

Example:

```bash
vixl inspect portrait --json
```

Output:

```json
{
  "name": "portrait",
  "type": "raster",
  "size": [1024, 1365],
  "position": [448, 0],
  "opacity": 1,
  "blend": "normal"
}
```

Document inspection:

```bash
vixl describe --json
```

Possible output:

```json
{
  "canvas": [1920, 1080],
  "layers": [
    {
      "id": "hero",
      "type": "image",
      "bounds": [300, 40, 900, 1000]
    },
    {
      "id": "title",
      "type": "text",
      "text": "FRIENDS AND FLAMES",
      "bounds": [120, 80, 1680, 200]
    }
  ]
}
```

This should be considered an essential feature rather than a convenience option.

---

# 37. Rendering

Vixl needs the ability to produce temporary renders without exporting or modifying the project.

Example:

```bash
vixl render --preview preview.png
```

AI agents can use this for iterative inspection.

A typical agent loop becomes:

```text
Inspect document
      ↓
Perform edits
      ↓
Render preview
      ↓
Inspect image
      ↓
Revise
      ↓
Render again
```

---

# 38. Export

Basic output:

```bash
vixl export image.png
```

Options:

```bash
vixl export image.jpg --quality 90

vixl export image.webp --quality 85

vixl export image.png --scale 2x
```

Future export profiles may include:

```bash
vixl export --profile instagram

vixl export --profile discord

vixl export --profile print
```

---

# 39. AI Architecture

AI should exist at three distinct layers.

```text
AI Features

1. Vision
2. Reasoning
3. Generation
```

These should remain independent wherever possible.

---

# 40. AI Level 1: Vision

Vision features understand existing imagery.

Examples:

```bash
vixl detect objects

vixl describe image

vixl OCR

vixl detect faces
```

Most importantly, vision can create selections.

---

# 41. Semantic Selection

Traditional selection:

```bash
vixl select rect ...
```

Semantic selection:

```bash
vixl select object person

vixl select object sky

vixl select object face

vixl select object text

vixl select object "the red car"
```

The AI subsystem determines where the object is.

Vixl converts the result into an ordinary selection mask.

Afterward, normal deterministic commands work.

Example:

```bash
vixl select object sky

vixl saturation -40

vixl brightness -15
```

This division is important:

```text
AI determines WHERE.

Vixl determines WHAT happens there.
```

---

# 42. AI Level 2: Reasoning

Vixl can allow a model to translate natural-language intent into ordinary Vixl operations.

Example:

```bash
vixl ask "make the logo about 20% smaller and put it in the upper right with a 40px margin"
```

The AI might produce:

```text
scale logo 80%
align logo top-right
margin logo 40
```

Before applying:

```text
Proposed operations:

1. Scale layer "logo" → 80%
2. Align → top-right
3. Apply margin → 40px

Apply? [Y/n]
```

Automatic execution:

```bash
vixl ask "..." --apply
```

The AI therefore **does not directly manipulate pixels**.

It translates natural language into Vixl's deterministic intermediate operation format.

---

# 43. AI Level 3: Image Generation

Vixl should allow external image-generation systems to act as operation providers.

Example:

```bash
vixl generate \
  --prompt "foggy forest at night" \
  --size 1024x1024 \
  --provider comfyui \
  --as background
```

---

# 44. AI Inpainting

Selections can become masks sent to image models.

Example:

```bash
vixl select rect 400 200 500 500

vixl generate \
  --prompt "replace this area with a broken neon sign" \
  --mode inpaint \
  --selection current
```

Vixl packages:

```text
source image
selection mask
prompt
dimensions
generation parameters
```

The provider returns the generated result.

Vixl inserts it into the document.

---

# 45. AI Image Extension / Outpainting

Example:

```bash
vixl ai extend --right 500
```

Vixl could:

1. enlarge the canvas
2. create a generation mask
3. provide context imagery
4. request an outpainting operation
5. insert the returned imagery nondestructively

---

# 46. AI Background Removal

Example:

```bash
vixl ai background-remove portrait
```

Ideally, this returns a mask rather than immediately deleting pixels.

The resulting mask remains editable.

---

# 47. AI Upscaling

Example:

```bash
vixl ai upscale portrait --2x
```

The provider could be:

- local
- remote
- plugin-based

Vixl itself should not need to know the underlying model implementation.

---

# 48. AI Generation Provider Interface

Vixl should not implement image-generation models itself.

Instead:

```text
Vixl
  ↓
Generation Provider Interface
  ↓
Provider
```

Possible providers:

```text
OpenAI
ComfyUI
InvokeAI
Automatic1111-compatible servers
Diffusers
local applications
custom HTTP endpoints
future providers
```

The provider interface normalizes different services.

---

# 49. Generation Request

Conceptually:

```text
GenerationRequest
```

contains:

```text
prompt
negative_prompt?
width
height
source_image?
mask?
seed?
model?
strength?
provider_options?
```

---

# 50. Generation Result

```text
GenerationResult
```

contains:

```text
image
provider
model
seed
parameters
generation_metadata
```

Vixl then converts the result into a normal document asset.

---

# 51. AI Generation as Document State

Generated imagery should retain provenance.

Example:

```text
Layer: Roses

Source: Generated
Provider: ComfyUI
Model: FLUX
Prompt: red roses spilling across a wooden table
Seed: 18472811
Created: 2026-10-02
```

Possible inspection:

```bash
vixl ai info roses
```

---

# 52. Regeneration

Because generation parameters are preserved:

```bash
vixl ai regenerate roses
```

could recreate the generation.

Alternative seed:

```bash
vixl ai regenerate roses --seed random
```

Alternative prompt:

```bash
vixl ai regenerate roses \
  --prompt "white roses spilling across a wooden table"
```

This turns generation into reproducible editable state instead of treating it as pasted pixels.

---

# 53. Agent-Native Workflow

Vixl should provide explicit capabilities for autonomous agents.

A typical workflow:

```text
Agent
  ↓
vixl describe --json
  ↓
Agent understands layer structure
  ↓
vixl render --preview
  ↓
Agent sees result
  ↓
Agent submits operations
  ↓
Vixl changes project
  ↓
Agent validates
```

The AI does not need to manipulate windows or controls.

---

# 54. Agent Operation Format

Although CLI commands are convenient for humans, agents should also be able to submit structured operations.

Example:

```json
{
  "operations": [
    {
      "type": "scale",
      "target": "logo",
      "value": 0.8
    },
    {
      "type": "align",
      "target": "logo",
      "alignment": "top-right",
      "margin": 40
    }
  ]
}
```

Possible interface:

```bash
vixl apply operations.json
```

---

# 55. Dry Run

AI agents and automation systems should be able to inspect proposed consequences.

Example:

```bash
vixl apply operations.json --dry-run
```

Result:

```text
Would perform:

1. Scale logo from 480×220 → 384×176
2. Move logo → 1496,40
3. No objects leave canvas
4. No assets modified
```

---

# 56. Transactions

Multiple operations should optionally apply atomically.

Example:

```bash
vixl transaction begin

vixl scale logo 80%
vixl align logo top-right
vixl margin logo 40

vixl transaction commit
```

If one step fails:

```bash
vixl transaction rollback
```

This will be particularly useful for automated agents.

---

# 57. stdin / stdout Support

Vixl should behave like a good command-line tool.

Possible examples:

```bash
vixl layers --json | jq ...
```

and:

```bash
cat operations.json | vixl apply -
```

Potential image pipelines:

```bash
cat photo.png | vixl convert --grayscale > result.png
```

where appropriate.

---

# 58. Human-Friendly Instruction Files

Eventually Vixl could support a friendly command language.

Example:

```text
add portrait.jpg as portrait
resize portrait width 800
center portrait
brightness portrait +5
add logo.png as logo
move logo bottom-right margin 60
export cover.png
```

Vixl could parse this into canonical operations.

However, the canonical operation format should always remain underneath this syntax.

---

# 59. Core Architecture

Recommended structure:

```text
src/
│
├── cli/
│   ├── commands/
│   ├── parser/
│   └── output/
│
├── core/
│   ├── document/
│   ├── layer/
│   ├── selection/
│   ├── mask/
│   ├── history/
│   ├── constraints/
│   ├── variables/
│   └── operations/
│
├── imaging/
│   ├── resize/
│   ├── filters/
│   ├── transform/
│   ├── compositor/
│   ├── text/
│   └── codecs/
│
├── ai/
│   ├── vision/
│   ├── reasoning/
│   ├── generation/
│   └── providers/
│
└── interfaces/
    ├── api/
    ├── mcp/
    └── bindings/
```

---

# 60. Operation Architecture

The CLI should not directly modify bitmap data.

Avoid:

```text
CLI command
    ↓
Pillow / image library
    ↓
Pixels
```

Prefer:

```text
CLI command
    ↓
Operation
    ↓
Document Model
    ↓
Rendering Engine
```

Example:

```json
{
  "operation": "set_opacity",
  "layer": "portrait",
  "value": 0.65
}
```

The same operation can originate from:

```text
CLI
API
AI
GUI
TUI
Vixl script
```

---

# 61. Renderer

The renderer is responsible for transforming document state into actual image pixels.

Conceptually:

```text
Project
 ↓
Resolve variables
 ↓
Resolve constraints
 ↓
Load layers
 ↓
Apply masks
 ↓
Apply transforms
 ↓
Apply effects
 ↓
Composite layers
 ↓
Output bitmap
```

---

# 62. Caching

Rendering should eventually use caching.

For example:

```text
Layer changed?
    no
    ↓
reuse cached layer render
```

This becomes increasingly important for:

- large canvases
- AI-generated assets
- many filters
- interactive previews

---

# 63. Technology Choice

Two particularly reasonable implementations are Python and Rust.

### Python

Possible stack:

```text
Python
Typer
Pillow
NumPy
OpenCV
```

Advantages:

- very fast prototyping
- excellent image libraries
- excellent AI ecosystem
- easy experimentation

Disadvantages:

- application packaging is less elegant
- higher memory use
- performance limitations for large workflows
- less ideal for a long-lived system executable

---

# 64. Rust

Possible libraries include:

```text
clap
serde
image
imageproc
resvg
tiny-skia
cosmic-text
```

Potential integration with:

```text
libvips
```

where more advanced image processing is required.

Advantages:

- excellent CLI binaries
- performance
- memory safety
- easy distribution
- good foundation for a reusable core engine

Disadvantages:

- slower initial development
- some advanced imaging functionality requires additional integration work

---

# 65. Recommended Technology Strategy

For a serious long-term project:

> **Rust core + provider-based integrations**

Vixl could later expose:

```text
C API
Python bindings
REST API
MCP server
```

AI experiments can still be prototyped separately in Python.

---

# 66. Relationship to ImageMagick

Vixl should not position itself as simply replacing ImageMagick.

ImageMagick generally follows:

```text
input image
  ↓
transformation pipeline
  ↓
output image
```

Vixl follows:

```text
editable document
  ↓
structured operations
  ↓
persistent state
  ↓
rendering
```

Example:

ImageMagick:

```bash
magick input.jpg -resize 800x800 -blur 0x4 output.jpg
```

Vixl:

```bash
vixl open poster.vixl

vixl select-layer portrait

vixl resize --width 800

vixl blur 4

vixl save
```

The project remains editable afterward.

---

# 67. Relationship to GIMP

Vixl takes inspiration from concepts common in GIMP:

- layers
- masks
- selections
- filters
- transformations
- compositing
- editable projects

It intentionally avoids recreating the entire graphical editing environment.

The primary differentiation is:

```text
GIMP:
graphic editor with automation capabilities

Vixl:
programmable document engine with editing interfaces
```

---

# 68. Explicit Non-Goals for Initial Releases

Vixl should initially avoid trying to implement:

- professional painting brushes
- tablet-pressure systems
- complex vector illustration
- CMYK prepress workflows
- advanced print color management
- animation
- hundreds of artistic filters
- Photoshop/GIMP compatibility
- complete RAW photo development
- advanced typography
- desktop publishing
- full GUI parity with GIMP

These features dramatically increase complexity without strengthening Vixl's primary advantage.

---

# 69. MVP

The first usable version should prove the document and operation architecture.

### MVP Features

- create/open/save projects
- `.vixl` document format
- raster layers
- layer ordering
- layer naming
- positioning
- scaling
- resizing
- rotation
- opacity
- visibility
- basic blend modes
- rectangular selections
- basic masks
- brightness
- contrast
- saturation
- grayscale
- blur
- sharpen
- text layers
- undo/redo
- PNG/JPEG/WebP export
- JSON document inspection
- structured operation format
- interactive CLI shell

---

# 70. Version 0.2

Focus on automation.

Add:

- Vixl scripts
- batch processing
- presets
- checkpoints
- variables
- validation
- assertions
- alignment commands
- reusable export profiles
- stdin/stdout support

---

# 71. Version 0.3

Focus on advanced document behavior.

Add:

- constraint-based positioning
- responsive resizing
- branchable history
- version comparison
- more blend modes
- nondestructive effect stacks
- cached rendering

---

# 72. Version 0.4

Focus on AI vision.

Add:

- object detection
- semantic segmentation
- semantic selections
- OCR
- background masking
- image descriptions

These should use provider interfaces so Vixl does not depend on one specific model.

---

# 73. Version 0.5

Focus on generative AI.

Add:

- generation provider API
- text-to-image
- inpainting
- outpainting
- image extension
- AI upscaling
- background generation
- generation metadata
- regeneration

---

# 74. Version 0.6

Focus on AI agents.

Add:

- agent API
- MCP server
- machine-readable validation
- transaction support
- dry-run support
- rendered preview endpoint
- structured operation submission
- change summaries

---

# 75. Future Interfaces

Once the engine is mature, multiple front ends become possible.

```text
Vixl Core
│
├── CLI
├── Interactive shell
├── TUI
├── GUI
├── Web interface
├── REST API
├── Python API
├── MCP server
└── AI Server Studio integration
```

No interface should need to implement its own editing engine.

---

# 76. Potential TUI

A future terminal interface could show:

```text
┌──────────────────── Layers ────────────────────┐
│ [T] Title                                      │
│ [I] Logo                                       │
│ [I] Portrait                                   │
│ [I] Background                                 │
└────────────────────────────────────────────────┘

┌────────────────── Properties ──────────────────┐
│ Portrait                                       │
│ Position: 360, 0                               │
│ Size: 1200 × 1080                              │
│ Opacity: 100%                                  │
└────────────────────────────────────────────────┘

> _
```

An image preview could be displayed through terminals supporting modern image protocols.

---

# 77. Possible GUI

A GUI should eventually become only another client.

It could offer:

- canvas preview
- layers panel
- properties panel
- command console
- history tree
- effects stack
- AI prompt interface

The GUI would submit the same operations as the CLI.

---

# 78. AI Server Studio Integration

Vixl could fit naturally into an AI orchestration environment.

An AI agent could receive tools such as:

```text
inspect_image_project
list_layers
render_preview
add_layer
move_layer
set_effect
make_selection
generate_image
inpaint_region
validate_project
export_project
```

This would allow an AI to construct and revise visual assets without needing desktop-control automation.

---

# 79. MCP Interface

A future MCP server could expose Vixl operations directly.

Potential tool families:

```text
vixl.document.*
vixl.layer.*
vixl.selection.*
vixl.mask.*
vixl.effect.*
vixl.text.*
vixl.render.*
vixl.ai.*
vixl.history.*
vixl.validate.*
```

For example:

```text
vixl.layer.move
```

could receive:

```json
{
  "project": "poster.vixl",
  "layer": "logo",
  "x": 120,
  "y": 50
}
```

---

# 80. Plugin Architecture

Vixl should eventually allow third-party extensions.

Possible plugin categories:

```text
filters
file codecs
AI providers
vision providers
export providers
validators
layout systems
asset sources
```

Plugins should interact with public interfaces rather than manipulate internal state directly.

---

# 81. Security Considerations

AI and plugin systems introduce additional risks.

Vixl should consider:

- project path sandboxing
- limits on plugin filesystem access
- network permissions
- generation-provider credentials
- arbitrary script execution
- remote asset handling
- malicious image files
- decompression bombs
- huge canvas allocations
- untrusted project files

Scripts should ideally consist of Vixl operations rather than unrestricted shell code.

---

# 82. Resource Limits

Automated systems should be able to specify limits.

Examples:

```bash
vixl --max-memory 4GB ...
```

Potential limits include:

- memory
- canvas dimensions
- number of layers
- rendered megapixels
- execution time
- generated asset size

This prevents a malformed or AI-generated operation from exhausting system resources.

---

# 83. Error Design

Errors should work equally well for humans and software.

Human output:

```text
ERROR: Layer "portraitt" does not exist.

Did you mean:
  portrait
```

Machine output:

```json
{
  "error": "layer_not_found",
  "requested": "portraitt",
  "suggestions": ["portrait"]
}
```

---

# 84. Operation Results

Commands should report exactly what changed.

Example:

```text
✓ Moved layer "logo"

Previous: 1320,80
Current: 1496,40
```

Machine response:

```json
{
  "success": true,
  "operation": "move",
  "target": "logo",
  "before": [1320, 80],
  "after": [1496, 40]
}
```

This is particularly useful for AI agents.

---

# 85. Stable Object IDs

Layer names should not be the only way of identifying objects.

Each object should receive an immutable ID.

Example:

```text
ID: lyr_f32da2
Name: portrait
```

Humans can reference:

```bash
vixl opacity portrait 0.8
```

Software can reference:

```text
lyr_f32da2
```

Renaming the layer therefore does not break automation.

---

# 86. Asset Provenance

Imported assets should retain source information.

For example:

```text
Source:
  type: imported
  original_filename: portrait.jpg
  checksum: ...
```

Generated images:

```text
Source:
  type: generated
  provider: ...
  model: ...
  prompt: ...
  seed: ...
```

This improves reproducibility.

---

# 87. Embedded vs Linked Assets

Vixl could eventually allow both.

Embedded:

```bash
vixl add photo.jpg
```

Linked:

```bash
vixl add photo.jpg --linked
```

A linked layer updates if the external source file changes.

This is useful for automated design pipelines.

---

# 88. Project Dependencies

Possible command:

```bash
vixl dependencies
```

Output:

```text
Embedded:
  portrait.jpg

Linked:
  ./assets/logo.svg
  ./assets/current-cover.jpg

Fonts:
  Inter Bold
  Inter Regular

AI Providers:
  comfyui-local
```

---

# 89. Reproducibility

Vixl should strive to make a document reproducible wherever possible.

A project could retain:

- imported assets
- fonts or font references
- effect parameters
- generation parameters
- model names
- seeds
- operation history
- Vixl version

Possible command:

```bash
vixl reproduce --check
```

which identifies missing dependencies.

---

# 90. Project Manifest

A project could expose:

```bash
vixl manifest
```

Example:

```text
Vixl Version: 0.6.2
Canvas: 1920×1080
Layers: 12
Fonts: 3
Linked Assets: 2
Generated Assets: 4
External Providers: 1
History Entries: 84
```

---

# 91. Headless Operation

Vixl should never require a graphical display.

Everything important should work:

```text
on servers
inside containers
through SSH
inside CI
inside AI runtimes
```

This is fundamental to its value.

---

# 92. CI/CD Use

Projects can be validated and rendered during software builds.

Example:

```bash
vixl validate assets/social.vixl

vixl render assets/social.vixl \
  --set version=$APP_VERSION \
  --out dist/social.png
```

This makes visual assets part of reproducible software workflows.

---

# 93. Template Ecosystem

Eventually `.vixl` files could function as reusable templates.

Examples:

```text
album-announcement.vixl
youtube-thumbnail.vixl
game-card.vixl
social-post.vixl
product-card.vixl
poster.vixl
```

Users could supply variables and assets without understanding the complete design.

---

# 94. Long-Term Opportunity

The most significant opportunity is not recreating GIMP.

It is establishing a standard workflow where an image document can be:

```text
understood
edited
versioned
generated
validated
automated
rendered
```

by both humans and software.

Vixl could therefore become something closer to:

> **Git + ImageMagick + a layer-based image editor + an AI tool interface**

without needing the complexity of a full professional desktop graphics suite.

---

# 95. One-Sentence Product Definition

> **Vixl is a deterministic, programmable, AI-native image document engine that provides layer-based editing, automation, generative-image integration, and agent control through a simple command-line interface.**

---

# 96. Short Product Pitch

Traditional image editors are optimized around people manipulating graphical interfaces.

Vixl treats image editing as structured data.

Create layers, make selections, transform images, edit text, apply effects, build reusable templates, branch creative versions, validate designs, automate thousands of assets, or allow AI agents to manipulate projects directly.

Image-generation models can act as providers for generating, replacing, extending, masking, or upscaling imagery without being hard-coded into the editor.

Everything remains part of an inspectable, editable, reproducible document.

---

# 97. Guiding Rule

When deciding whether a feature belongs in Vixl, the question should be:

> **Does this become substantially more useful when image editing is programmable, reproducible, or controlled by software?**

If yes, it is probably a strong fit for Vixl.

If its primary value depends on a sophisticated graphical user interface, it is probably not an early priority.

---

# 98. Product Identity

The project should avoid defining itself merely as:

> "GIMP for the command line."

That description is useful for initially explaining the concept, but undersells the architecture.

A more accurate identity is:

> **A programmable image-document engine built for autonomous AI agents, also usable by humans and scripts.**

The CLI is simply its first—and potentially most important—interface.
