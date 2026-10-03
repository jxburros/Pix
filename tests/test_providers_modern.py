import base64
import io
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from vixl import Project, VixlError
from vixl.ai import (
    AnthropicProvider,
    BFLProvider,
    GeminiProvider,
    OpenAIProvider,
    encoded,
    generate,
    nearest_ratio,
    openai_size,
    plan,
    provider,
)


def png(size=(32, 16), color="red"):
    return encoded(Image.new("RGBA", size, color))


REAL_CLIENT = httpx.Client


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_openai_defaults_and_arbitrary_sizes(monkeypatch):
    backend = OpenAIProvider("openai", {"url": "http://localhost"})
    calls = []
    monkeypatch.setattr(backend, "json", lambda method, route, **kw: calls.append(kw) or {"data": [{"b64_json": "YWJj"}]})
    backend.invoke("generate", {"width": 1280, "height": 720, "prompt": "x"})
    assert calls[-1]["json"]["model"] == "gpt-image-2.5-flare"
    width, height = map(int, calls[-1]["json"]["size"].split("x"))
    assert width % 16 == 0 and height % 16 == 0 and abs(width / height - 16 / 9) < 0.02
    assert openai_size(1000, 100, "gpt-image-2") [0] / openai_size(1000, 100, "gpt-image-2")[1] <= 3
    assert openai_size(512, 512, "gpt-image-1") == (512, 512)  # legacy models keep exact sizes
    monkeypatch.setattr(
        backend, "json", lambda method, route, **kw: calls.append(kw) or {"choices": [{"message": {"content": "{}"}}]}
    )
    backend.invoke("describe", {"source_image": "abc"})
    assert calls[-1]["json"]["model"] == "gpt-5-mini" and "temperature" not in calls[-1]["json"]


def test_generated_images_are_fitted_for_preset_size_providers(tmp_path):
    p = Project(300, 100)

    class Preset:
        name, fit_output = "preset", True

        def invoke(self, capability, request):
            return {"image": png((512, 256), "blue"), "model": "m"}

    result = generate(p, {"prompt": "x", "width": 300, "height": 100}, Preset())
    assert p.layer(result["layer"])["width"] == 300
    assert result["provenance"]["metadata"]["resized_from"] == [512, 256]

    class Strict(Preset):
        fit_output = False

    with pytest.raises(VixlError, match="dimensions"):
        generate(p, {"prompt": "x", "width": 300, "height": 100}, Strict())


def test_gemini_generation_editing_and_detection(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request, body))
        assert request.headers["x-goog-api-key"] == "g-key" and "authorization" not in request.headers
        if "IMAGE" in body["generationConfig"].get("responseModalities", []):
            parts = [{"text": "thinking", "thought": True}, {"inlineData": {"mimeType": "image/png", "data": png()}}]
        else:
            parts = [{"text": json.dumps([{"label": "cat", "box_2d": [100, 250, 600, 750]}])}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})

    mock_http(monkeypatch, handler)
    backend = provider("gemini")
    assert isinstance(backend, GeminiProvider) and backend.fit_output
    result = backend.invoke(
        "generate", {"prompt": "sky", "width": 1280, "height": 720, "source_image": png(), "mask": png()}
    )
    request, body = requests[-1]
    assert request.url.path.endswith("/models/gemini-3.1-flash-image:generateContent")
    assert body["generationConfig"]["imageConfig"] == {"aspectRatio": "16:9", "imageSize": "2K"}
    assert len(body["contents"][0]["parts"]) == 3 and "mask" in body["contents"][0]["parts"][2]["text"]
    assert result["image"] == png()
    detected = backend.invoke("detect", {"source_image": png(), "width": 400, "height": 200, "query": "cats"})
    assert requests[-1][0].url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert detected["objects"] == [{"label": "cat", "box": [100, 20, 200, 100]}]
    assert nearest_ratio(1080, 1920, ("1:1", "9:16", "16:9")) == "9:16"


def test_flux_async_job_and_url_allowlist(monkeypatch):
    monkeypatch.setenv("BFL_API_KEY", "b-key")
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert request.headers["x-key"] == "b-key"
            assert ("image" in body or body["width"] % 16 == 0) and body["output_format"] == "png"
            return httpx.Response(200, json={"id": "job1", "polling_url": "https://api.us.bfl.ai/v1/get_result?id=job1"})
        if request.url.host == "api.us.bfl.ai":
            if sum(1 for r in seen if r.url.host == "api.us.bfl.ai") == 1:
                return httpx.Response(200, json={"status": "Pending"})
            return httpx.Response(
                200,
                json={"status": "Ready", "result": {"sample": "https://bfldeliveryprod.blob.core.windows.net/results/a.png", "seed": 7}},
            )
        assert "x-key" not in request.headers  # signed result URLs get no credentials
        return httpx.Response(200, content=base64.b64decode(png()))

    mock_http(monkeypatch, handler)
    backend = BFLProvider("flux", {"poll_interval": 0})
    result = backend.invoke("generate", {"prompt": "sky", "width": 1000, "height": 500})
    assert result["seed"] == 7 and result["model"] == "flux-2-pro"
    assert seen[0].url.path == "/v1/flux-2-pro"
    backend.invoke("generate", {"prompt": "fill", "width": 64, "height": 64, "source_image": png(), "mask": png()})
    fill = [r for r in seen if r.method == "POST"][-1]
    assert fill.url.path == "/v1/flux-pro-1.0-fill" and set(json.loads(fill.content)) >= {"image", "mask"}

    def evil(request):
        return httpx.Response(200, json={"id": "x", "polling_url": "https://attacker.example/steal"})

    mock_http(monkeypatch, evil)
    with pytest.raises(VixlError, match="approved hosts"):
        backend.invoke("generate", {"prompt": "x", "width": 64, "height": 64})


class FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.calls, self.text, self.stop_reason = [], text, stop_reason

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="cyber"),
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=self.text)],
        )


def fake_client(text, stop_reason="end_turn"):
    messages = FakeMessages(text, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages), messages=messages), messages


def test_anthropic_vision_scales_coordinates_and_uses_fallbacks():
    pytest.importorskip("anthropic")
    client, messages = fake_client(json.dumps({"objects": [{"label": "dog", "x": 100, "y": 50, "width": 200, "height": 100}]}))
    backend = AnthropicProvider("anthropic", {}, client=client)
    result = backend.invoke("detect", {"source_image": png((3136, 1568)), "width": 3136, "height": 1568, "query": "dog"})
    call = messages.calls[-1]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    image_block = call["messages"][0]["content"][0]
    assert image_block["type"] == "image" and image_block["source"]["media_type"] == "image/png"
    with Image.open(io.BytesIO(base64.b64decode(image_block["source"]["data"]))) as sent:
        assert sent.size == (1568, 784)  # pre-resized, so the API does not rescale again
    assert result["objects"] == [{"label": "dog", "box": [200, 100, 400, 200]}]  # mapped back 2x


def test_anthropic_refusals_plans_and_configuration():
    pytest.importorskip("anthropic")
    client, messages = fake_client("{}", stop_reason="refusal")
    with pytest.raises(VixlError) as error:
        AnthropicProvider("anthropic", {}, client=client).invoke("describe", {"source_image": png()})
    assert error.value.code == "provider_refused" and "cyber" in str(error.value)
    client, messages = fake_client('Here you go:\n{"operations": [{"type": "rect", "name": "b", "width": 4, "height": 4}]}')
    backend = AnthropicProvider("anthropic", {"fallbacks": False, "model": "claude-sonnet-5-5", "effort": "low"}, client=client)
    p = Project(16, 16)
    result = plan(p, "add a box", backend, apply=True)
    assert p.layer("b")["shape"] == "rectangle" and result["applied"]
    call = messages.calls[-1]
    assert "fallbacks" not in call and call["model"] == "claude-sonnet-5-5"
    assert call["output_config"] == {"effort": "low"}
    with pytest.raises(VixlError, match="does not generate"):
        backend.invoke("generate", {})


def test_plans_cannot_smuggle_files_through_aliases():
    class Planner:
        name = "planner"

        def invoke(self, capability, request):
            return {"operations": [{"type": "add-text", "text": "x", "font_family": "/etc/passwd"}]}

    with pytest.raises(VixlError) as error:
        plan(Project(8, 8), "x", Planner())
    assert error.value.code == "unsafe_plan"
