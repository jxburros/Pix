# AI providers

Vixl contains adapters, not model weights. Configure only providers you trust; generation can incur your provider's charges. No AI service is called until you explicitly run an AI command. Provider URL/key configuration is local; it is not loaded from `.vixl` documents.

Create `~/.config/vixl/providers.json` (or set `VIXL_PROVIDERS` to another file):

```json
{
  "default": "local",
  "providers": {
    "openai": {
      "type": "openai", "url": "https://api.openai.com/v1",
      "key_env": "OPENAI_API_KEY", "model": "gpt-image-2.5-flare",
      "reasoning_model": "gpt-5-mini"
    },
    "gemini": {
      "type": "gemini", "key_env": "GEMINI_API_KEY",
      "model": "gemini-3.1-flash-image", "vision_model": "gemini-3.8-flash",
      "image_size": "2K"
    },
    "flux": {
      "type": "bfl", "key_env": "BFL_API_KEY",
      "model": "flux-2-pro", "fill_model": "flux-pro-1.0-fill", "job_timeout": 300
    },
    "claude": {
      "type": "anthropic", "key_env": "ANTHROPIC_API_KEY",
      "model": "claude-opus-5-5", "effort": "medium", "fallbacks": true
    },
    "local": {
      "type": "automatic1111", "url": "http://127.0.0.1:7860",
      "upscaler": "R-ESRGAN 4x+", "options": {"steps": 25}
    },
    "comfy": {
      "type": "comfyui", "url": "http://127.0.0.1:8188",
      "workflow": "/absolute/path/to/workflow-api.json",
      "output_node": "9", "job_timeout": 300
    },
    "vision": {
      "type": "http", "url": "http://127.0.0.1:9000",
      "key_env": "VISION_API_KEY"
    }
  }
}
```

Use environment variables for keys; omit `key_env` for unauthenticated local services. `url_env` can substitute for `url`. `VIXL_AI_PROVIDER` overrides the default. `--provider NAME` selects a provider per command. Four providers work without a config entry once their key is set: `--provider openai` (`OPENAI_API_KEY`), `--provider gemini` (`GEMINI_API_KEY`), `--provider flux` (`BFL_API_KEY`) and `--provider anthropic` (`ANTHROPIC_API_KEY`, or an `ant auth login` profile).

The Anthropic provider uses the official `anthropic` SDK: install `vixl-engine[anthropic]` (included in the Windows installer and the `dev` extra). Images are downscaled to at most 1568 px on the long edge before sending, so Claude's pixel coordinates map back exactly to the document. Describe/detect/OCR use JSON-schema structured output. Server-side refusal fallbacks (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) are enabled by default; set `"fallbacks": false` to disable them, for example on platforms that do not offer them. A request Claude still declines fails with `provider_refused`.

## Capability matrix

| Feature | OpenAI | Gemini | FLUX (BFL) | Anthropic | Automatic1111 | ComfyUI | HTTP gateway |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Natural-language plan | Chat completions | generateContent (JSON) | No | Messages API | No | No | `/plan` |
| Description / detection / OCR | Multimodal chat | generateContent; `box_2d` converted | No | Structured output | No | No | `/describe`, `/detect`, `/ocr` |
| Semantic selection / background mask | No | No | No | No | No | Configured mask workflow | `/segment`, `/background-remove` |
| Text-to-image | Images API, sizes in multiples of 16 | Native image output, nearest aspect ratio | `flux-2-pro` | No | txt2img | Configured workflow | `/generate` |
| Inpaint / outpaint / image-to-image | Image edits with mask | Edit with source (+ mask as a second image) | `flux-pro-1.0-fill` with mask; `input_image` edits | No | img2img + mask | Configured workflow | `/generate` |
| Upscale | No | No | No | No | extra-single-image | Configured workflow | `/upscale` |

Detection results are normalized for every adapter to `{"objects": [{"label", "box": [x, y, w, h]}]}` in document pixels.

Adapters are tested with mocked HTTP payloads/workflow responses. Live provider inference has **not** been verified in this repository's development environment. Availability, model names, accepted dimensions, quotas, and workflow nodes belong to the configured service. Unsupported capabilities fail explicitly. There is no fake-success or placeholder-image fallback.

OpenAI seeds are rejected because the image API does not expose deterministic seed control. Services with preset output sizes (OpenAI multiples of 16, Gemini aspect ratios and 1K/2K/4K presets, FLUX multiples of 16 up to 4 MP) are asked for the closest size; Vixl then fits the result to the requested canvas and records the provider's size as `resized_from` in the layer's provenance metadata. The HTTP gateway, Automatic1111 and ComfyUI must still return exactly the requested size. For arbitrary canvas outpainting, use a provider/workflow that supports the requested dimensions. The `--model` field selects OpenAI models and is passed to generic/workflow providers; Automatic1111 uses its server-loaded checkpoint (it does not switch checkpoints based on this field).

## HTTP gateway contract

Each capability is `POST BASE_URL/<capability>` with JSON and optional `Authorization: Bearer ...`. No redirects are followed. Responses are bounded to 64 MiB; HTTP failures produce structured errors. Image fields are base64-encoded PNG data, without URLs. Vixl will not fetch arbitrary URLs returned by a gateway (only the FLUX adapter downloads its signed results, from approved hosts).

Generation request:

```json
{
  "prompt":"foggy forest", "negative_prompt":null,
  "width":1024, "height":1024, "mode":"inpaint",
  "source_image":"BASE64_PNG", "mask":"BASE64_GRAYSCALE_PNG",
  "seed":42, "model":"your-model", "strength":0.75
}
```

`source_image`, `mask`, `seed`, and `model` are optional. **White mask pixels are editable; black pixels are protected.** Generate returns:

```json
{"image":"BASE64_PNG", "provider":"your-service", "model":"your-model", "seed":42, "metadata":{}}
```

The returned image must match requested dimensions. Vixl clips inpaint/outpaint layers to the selection mask even if a provider changes protected pixels. The request, returned seed/model, source, mask and metadata are retained for regeneration. Providers should return only provenance in `metadata`, never credentials. Credentials remain environment-only in Vixl's adapters.

Vision requests carry `source_image`, width/height, and a `label` for segmentation or a `query` for detection. `/segment` and `/background-remove` return `{"mask":"BASE64_PNG"}` with the exact input dimensions (white = selected foreground). `/describe`, `/detect`, and `/ocr` return a JSON object. Their content is provider-defined.

`/upscale` receives `source_image`, target width/height, and `scale`; it returns the generation response shape. The result becomes a new layer while the original stays editable.

`/plan` receives `prompt`, the inspected document, an operation reference, allowed type names, and `source_image`. Return `{"operations":[...]}`. Vixl rejects filesystem and plugin requests, validates the entire batch, then previews it. Only `--apply` changes the project; there is no automatic execution based on model prose.

## ComfyUI workflows

Export a workflow in ComfyUI's **API format**, not its UI graph format. Keep it as a local trusted configuration file. Values that are exactly `${prompt}`, `${negative_prompt}`, `${seed}`, `${width}`, `${height}`, `${model}`, `${strength}`, `${source_image}`, or `${mask}` are replaced with typed request values. Missing required substitutions fail explicitly.

Vixl uploads source/mask PNGs via `/upload/image`, substitutes the returned server filenames, submits `/prompt`, polls `/history/<prompt_id>`, and downloads the selected SaveImage output via `/view`. `output_node` identifies the desired output. Workflows must save an output image. For segmentation, save a grayscale foreground mask. Wire your workflow to interpret white as selected/edited; model-specific nodes and mask conversions belong in that workflow.

For multiple modes, configure `workflows` mapping `generate`, `inpaint`, `outpaint`, `upscale`, `segment`, and `background-remove` to API workflow files. `workflow` is the fallback. If a job times out, the server may still be running it; Vixl does not claim to cancel remote work.

## Commands

```bash
vixl detect objects --provider openai
vixl detect faces --provider vision
vixl ocr --provider openai
vixl ai describe --provider openai
vixl select object 'the red car' --provider vision
vixl ai background-remove portrait --provider vision
vixl ai upscale portrait --2x --provider local
vixl ai info forest
vixl ai regenerate forest --seed 42
```

Outpainting shifts existing layers when extending left/top and keeps their visual positions relative to the original image. It freezes their current constrained positions while expanding the canvas. Add new constraints afterward if you want further responsive layout. Regeneration uses the captured source/mask, not the current composite, and preserves the layer's stable identity and layout.
