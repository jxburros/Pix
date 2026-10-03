# AI providers

Vixl contains adapters, not model weights. Configure only providers you trust; generation can incur your provider's charges. No AI service is called until you explicitly run an AI command. Provider URL/key configuration is local; it is not loaded from `.vixl` documents.

Create `~/.config/vixl/providers.json` (or set `VIXL_PROVIDERS` to another file):

```json
{
  "default": "local",
  "providers": {
    "openai": {
      "type": "openai", "url": "https://api.openai.com/v1",
      "key_env": "OPENAI_API_KEY", "model": "gpt-image-1",
      "reasoning_model": "gpt-4.1-mini"
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

Use environment variables for keys; omit `key_env` for unauthenticated local services. `url_env` can substitute for `url`. `VIXL_AI_PROVIDER` overrides the default. `--provider NAME` selects a provider per command. OpenAI can also be used without a config entry via `--provider openai` and `OPENAI_API_KEY`.

## Capability matrix

| Feature | OpenAI adapter | Automatic1111 | ComfyUI | HTTP gateway |
| --- | --- | --- | --- | --- |
| Natural-language plan | Chat completions | No | No | `/plan` |
| Description / detection / OCR | Multimodal chat, model-dependent accuracy | No | No | `/describe`, `/detect`, `/ocr` |
| Semantic selection / background mask | No segmentation adapter | No | Configured mask workflow | `/segment`, `/background-remove` |
| Text-to-image | Images API | txt2img | Configured workflow | `/generate` |
| Inpaint / outpaint / image-to-image | Image edits; model size restrictions apply | img2img + mask | Configured workflow | `/generate` |
| Upscale | No dedicated upscaler | extra-single-image | Configured workflow | `/upscale` |

Adapters are tested with mocked HTTP payloads/workflow responses. Live provider inference has **not** been verified in this repository's development environment. Availability, model names, accepted dimensions, quotas, and workflow nodes belong to the configured service. Unsupported capabilities fail explicitly. There is no fake-success or placeholder-image fallback.

OpenAI seeds are rejected because the image API does not expose deterministic seed control. Request a supported image size (`1024x1024`, for example); Vixl does not silently resize provider output. For arbitrary canvas outpainting, use a provider/workflow that supports the requested dimensions. The `--model` field selects OpenAI models and is passed to generic/workflow providers; Automatic1111 uses its server-loaded checkpoint (it does not switch checkpoints based on this field).

## HTTP gateway contract

Each capability is `POST BASE_URL/<capability>` with JSON and optional `Authorization: Bearer ...`. No redirects are followed. Responses are bounded to 64 MiB; HTTP failures produce structured errors. Image fields are base64-encoded PNG data, without URLs. Vixl will not fetch arbitrary URLs returned by a provider.

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
