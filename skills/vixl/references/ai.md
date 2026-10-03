# AI features (external providers)

Vixl is headless and designed for autonomous AI agents; humans can use the same interfaces. See [new resources and SVG](resources.md) for 0.11 additions.

Vixl ships adapters, not models. Every AI command calls a provider **you** configured; there is no
offline or placeholder fallback, and unsupported capabilities fail explicitly. If a call fails with
a provider/configuration error, report it to the user instead of looping.

## Configuration

`~/.config/vixl/providers.json` (or the file named by `VIXL_PROVIDERS`):

```json
{
  "default": "local",
  "providers": {
    "openai": {"type": "openai", "url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "model": "gpt-image-1", "reasoning_model": "gpt-4.1-mini"},
    "local":  {"type": "automatic1111", "url": "http://127.0.0.1:7860", "upscaler": "R-ESRGAN 4x+", "options": {"steps": 25}},
    "comfy":  {"type": "comfyui", "url": "http://127.0.0.1:8188", "workflow": "/abs/workflow-api.json",
               "workflows": {"inpaint": "/abs/inpaint-api.json", "segment": "/abs/seg-api.json"},
               "output_node": "9", "job_timeout": 300},
    "vision": {"type": "http", "url": "http://127.0.0.1:9000", "key_env": "VISION_API_KEY"}
  }
}
```

- Keys are referenced by env-var name (`key_env`); `url_env` may replace `url`.
- `VIXL_AI_PROVIDER` overrides `default`; `--provider NAME` / `provider=` overrides per call.
- `--provider openai` works without a config entry if `OPENAI_API_KEY` is set.
- Provider config is never read from `.vixl` files. MCP/REST servers use the server machine's config.

## Capability matrix

| Capability | OpenAI | Automatic1111 | ComfyUI | HTTP gateway |
| --- | --- | --- | --- | --- |
| Plan (natural language → operations) | ✓ | — | — | `/plan` |
| Describe / detect / OCR | ✓ (multimodal) | — | — | `/describe` `/detect` `/ocr` |
| Segmentation / background mask | — | — | workflow | `/segment` `/background-remove` |
| Text-to-image | ✓ | ✓ | workflow | `/generate` |
| Inpaint / outpaint / img2img | ✓ (size limits) | ✓ | workflow | `/generate` |
| Upscale | — | ✓ | workflow | `/upscale` |

OpenAI rejects `seed` and needs supported sizes (e.g. `1024x1024`); Vixl never silently resizes
provider output. So for OpenAI generation into an arbitrary canvas, generate at a supported size and
then `resize`/`frame` the resulting layer.

## Operations

| Goal | MCP | CLI |
| --- | --- | --- |
| Generate a new layer | `vixl_ai_generate(prompt, width, height, seed, name, provider)` | `vixl generate --prompt '…' --size 1024x1024 --as NAME --provider P [--seed N]` |
| Inpaint a region | select first (`select` op), then `vixl_ai_generate(prompt, mode="inpaint")` | `vixl select rect …` then `vixl generate --prompt '…' --mode inpaint --as NAME` |
| Image-to-image (whole canvas) | `vixl_ai_generate(prompt, mode="img2img", strength=0.6)` | `vixl generate --mode img2img --strength 0.6 …` |
| Outpaint / extend canvas | `vixl_ai_extend(prompt, right=500)` | `vixl ai extend --right 500 --prompt '…' --as extension` |
| Upscale a layer | `vixl_ai_upscale(layer, scale=2)` | `vixl ai upscale LAYER --2x` / `--scale 4` |
| Re-roll a generated layer | `vixl_ai_regenerate(layer, prompt?, seed?)` | `vixl ai regenerate LAYER [--seed 42]` |
| Provenance of a layer | `vixl_document_inspect(target)` → `provenance` | `vixl ai info LAYER` |
| Remove background | `vixl_ai_remove_background(layer)` | `vixl ai background-remove LAYER` |
| Select an object by label | `vixl_ai_select_object(label)` | `vixl select object 'the red car' --provider vision` |
| Select main subject | `vixl_ai_select_subject()` | `vixl ai select-subject` |
| Remove selected object | `vixl_ai_remove()` | `vixl ai remove --as removed-object` |
| Content-aware fill selection | `vixl_ai_content_aware_fill(prompt?)` | `vixl ai content-aware-fill --prompt '…'` |
| Describe / detect / OCR | `vixl_ai_analyze("describe"\|"detect"\|"ocr", query)` | `vixl ai describe` · `vixl detect objects\|faces` · `vixl ocr` |
| Plan edits from English | `vixl_ai_plan(prompt)` then `apply=True` | `vixl ask '…'` then `vixl ask '…' --apply` |

Behavior worth knowing:

- Results are **ordinary editable layers/masks/selections**: inpaint/remove/fill insert a new
  layer masked to the selection (originals untouched); background removal adds a layer mask
  (`mask disable` to undo visually); selections can feed `mask from-selection` or effects.
- Provenance (prompt, provider, model, returned seed, source, mask) is stored for regeneration.
  Regeneration reuses the captured source/mask, not the current composite.
- Extending left/top shifts existing layers to keep their visual position and freezes their
  constraints; re-add constraints afterward if needed.
- `plan`/`ask` validate and preview the proposed batch; nothing changes without `apply`. As an
  agent you can usually write the operations yourself — prefer that over `plan` unless asked.
- Providers receive the rendered canvas, selection and document metadata. Don't call AI tools on
  sensitive images without the user's consent; calls may incur provider charges.

## Model discovery (0.11)

Use `vixl providers add NAME --type openai|anthropic|mistral|meta|gemini --key-env ENV` to fetch the account catalog before saving. `vixl models --refresh` and `vixl_models_list` return available IDs and capability labels. `--provider` pins a provider and `--model` pins an exact model. Otherwise Vixl routes to a matching configured model, using vendor metadata or documented model-family mappings. Native Anthropic messages and Gemini content/image adapters join OpenAI-compatible Mistral/Meta chat. Midjourney needs an authorized HTTP gateway exposing `/models` and the Vixl capability routes. Keys remain environment references; no credentials enter projects. Live provider size/mask/seed limits apply, and mocked CI does not verify paid-service access or output quality.
