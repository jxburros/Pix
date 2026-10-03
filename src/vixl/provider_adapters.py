"""Native Anthropic and Gemini protocols; Mistral/Meta use OpenAI chat compatibility."""

from urllib.parse import quote

from .ai import HTTPProvider
from .errors import require, VixlError
from .models import json_content, prompt_for


class AnthropicProvider(HTTPProvider):
    def __init__(self, name, config):
        super().__init__(name, config)
        token = self.headers.pop("Authorization", "").removeprefix("Bearer ")
        self.headers.update({"x-api-key": token, "anthropic-version": "2023-06-01"})

    def invoke(self, capability, request):
        require(
            capability in ("plan", "describe", "detect", "ocr"),
            "Anthropic supports planning and vision, not image generation",
            "unsupported_capability",
        )
        model = request.get("model") or self.config.get("reasoning_model") or self.config.get("model")
        require(model, "Discover/select an Anthropic model first")
        content = [{"type": "text", "text": prompt_for(capability, request)}]
        if request.get("source_image"):
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": request["source_image"]},
                }
            )
        result = self.json(
            "POST",
            "/messages",
            json={
                "model": model,
                "max_tokens": self.config.get("max_tokens", 4096),
                "messages": [{"role": "user", "content": content}],
            },
        )
        return json_content(
            "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        )


class GeminiProvider(HTTPProvider):
    def __init__(self, name, config):
        super().__init__(name, config)
        self.headers["x-goog-api-key"] = self.headers.pop("Authorization", "").removeprefix("Bearer ")

    def invoke(self, capability, request):
        require(
            capability in ("plan", "describe", "detect", "ocr", "generate"),
            "Unsupported Gemini capability",
            "unsupported_capability",
        )
        model = (
            request.get("model")
            or self.config.get("model" if capability == "generate" else "reasoning_model")
            or self.config.get("model")
        )
        require(model, "Discover/select a Gemini model first")
        model = model.removeprefix("models/")
        route = "/models/" + quote(model, safe="")
        if capability == "generate" and "imagen" in model:
            require(not request.get("source_image"), "Imagen generation adapter does not support editing")
            require(request.get("seed") is None, "This Imagen adapter does not expose deterministic seeds")
            w, h = request["width"], request["height"]
            ratio = next(
                (
                    r
                    for r in ("1:1", "3:4", "4:3", "9:16", "16:9")
                    if abs(w / h - int(r.split(":")[0]) / int(r.split(":")[1])) < 0.02
                ),
                None,
            )
            require(ratio, "Imagen requires a supported aspect ratio")
            result = self.json(
                "POST",
                route + ":predict",
                json={
                    "instances": [{"prompt": request.get("prompt", "")}],
                    "parameters": {"sampleCount": 1, "aspectRatio": ratio},
                },
            )
            predictions = result.get("predictions", [])
            require(
                predictions and predictions[0].get("bytesBase64Encoded"),
                "Gemini returned no image",
                "provider_error",
            )
            return {"image": predictions[0]["bytesBase64Encoded"], "model": model}
        parts = [
            {
                "text": request.get("prompt", "")
                if capability == "generate"
                else prompt_for(capability, request)
            }
        ]
        if request.get("source_image"):
            parts.append({"inlineData": {"mimeType": "image/png", "data": request["source_image"]}})
        if capability == "generate":
            require(request.get("seed") is None, "Gemini image adapter does not expose deterministic seeds")
            require(not request.get("mask"), "Gemini image adapter does not support mask-based inpainting")
        settings = (
            {"responseModalities": ["TEXT", "IMAGE"]}
            if capability == "generate"
            else {"responseMimeType": "application/json"}
        )
        result = self.json(
            "POST",
            route + ":generateContent",
            json={"contents": [{"role": "user", "parts": parts}], "generationConfig": settings},
        )
        try:
            output = result["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VixlError("provider_error", "Gemini returned no content") from exc
        if capability == "generate":
            image = next(
                (
                    p.get("inlineData", p.get("inline_data", {})).get("data")
                    for p in output
                    if p.get("inlineData") or p.get("inline_data")
                ),
                None,
            )
            require(image, "Gemini returned no image", "provider_error")
            return {"image": image, "model": model}
        return json_content("".join(p.get("text", "") for p in output))
