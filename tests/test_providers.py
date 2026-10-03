import base64
import io
import json

import httpx
from PIL import Image
import pytest

from vixl.ai import HTTPProvider, OpenAIProvider, Automatic1111Provider, ComfyUIProvider, encoded, provider
from vixl import VixlError


def adapter(cls=HTTPProvider, **options):
    return cls("fixture", {"url": "http://localhost:8188", **options})


def test_http_gateway_uses_bounded_transport_and_rejects_redirect(monkeypatch):
    real_client = httpx.Client

    def handler(request):
        assert request.url.path == "/describe"
        assert json.loads(request.content) == {"source_image": "fixture"}
        return httpx.Response(200, json={"description": "ok"})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    assert adapter().invoke("describe", {"source_image": "fixture"}) == {"description": "ok"}
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(302, headers={"location": "http://other-host/"})
            ),
            **kw,
        ),
    )
    with pytest.raises(VixlError, match="302"):
        adapter().invoke("describe", {})


def test_openai_generation_and_edit_mask_conversion(monkeypatch):
    backend = adapter(OpenAIProvider)
    calls = []

    def capture(method, route, **kwargs):
        calls.append((route, kwargs))
        return {"data": [{"b64_json": "YWJj"}]}

    monkeypatch.setattr(backend, "json", capture)
    backend.invoke("generate", {"width": 1024, "height": 1024, "prompt": "forest"})
    assert calls[-1][0] == "/images/generations"
    assert calls[-1][1]["json"]["size"] == "1024x1024"
    mask = Image.new("L", (2, 1))
    mask.putpixel((0, 0), 255)
    backend.invoke(
        "generate",
        {
            "width": 2,
            "height": 1,
            "prompt": "edit",
            "source_image": encoded(Image.new("RGBA", (2, 1))),
            "mask": encoded(mask),
        },
    )
    files = calls[-1][1]["files"]
    with Image.open(io.BytesIO(files["mask"][1])) as m:
        assert m.getpixel((0, 0))[3] == 0 and m.getpixel((1, 0))[3] == 255
    with pytest.raises(VixlError, match="seeds"):
        backend.invoke("generate", {"seed": 1, "width": 1024, "height": 1024})


def test_openai_reasoning_structured_response(monkeypatch):
    backend = adapter(OpenAIProvider)
    captured = []

    def capture(method, route, **kw):
        captured.append(kw["json"])
        return {"choices": [{"message": {"content": '{"operations":[{"type":"move","x":2}]}'}}]}

    monkeypatch.setattr(backend, "json", capture)
    assert backend.invoke("plan", {"prompt": "move", "source_image": "abc"})["operations"][0]["x"] == 2
    assert captured[0]["response_format"] == {"type": "json_object"}


def test_automatic1111_payloads(monkeypatch):
    backend = adapter(Automatic1111Provider)
    captured = []

    def capture(method, route, **kw):
        captured.append((route, kw["json"]))
        return {"images": ["abc"], "info": '{"seed":42}'}

    monkeypatch.setattr(backend, "json", capture)
    result = backend.invoke(
        "generate",
        {
            "prompt": "forest",
            "width": 64,
            "height": 64,
            "source_image": "source",
            "mask": "mask",
            "strength": 0.5,
        },
    )
    assert captured[-1][0] == "/sdapi/v1/img2img"
    assert captured[-1][1]["denoising_strength"] == 0.5
    assert captured[-1][1]["mask"] == "mask"
    assert result["seed"] == 42


def test_comfyui_workflow_substitution_and_polling(tmp_path, monkeypatch):
    file = tmp_path / "workflow.json"
    file.write_text(
        json.dumps(
            {
                "1": {
                    "class_type": "KSampler",
                    "inputs": {"seed": "${seed}", "text": "${prompt}", "image": "${source_image}"},
                }
            }
        )
    )
    backend = adapter(ComfyUIProvider, workflow=str(file), output_node="9")
    calls = []

    def capture(method, route, **kw):
        calls.append((route, kw))
        if route == "/upload/image":
            return {"name": "source.png", "subfolder": "vixl"}
        if route == "/prompt":
            return {"prompt_id": "job"}
        return {
            "job": {
                "status": {"status_str": "success"},
                "outputs": {"9": {"images": [{"filename": "output.png", "type": "output"}]}},
            }
        }

    monkeypatch.setattr(backend, "json", capture)
    monkeypatch.setattr(backend, "request", lambda *_args, **_kw: b"image")
    result = backend.invoke(
        "generate", {"seed": 12, "prompt": "sky", "source_image": encoded(Image.new("RGBA", (2, 2)))}
    )
    graph = calls[1][1]["json"]["prompt"]
    assert graph["1"]["inputs"] == {"seed": 12, "text": "sky", "image": "vixl/source.png"}
    assert base64.b64decode(result["image"]) == b"image"


def test_missing_provider_is_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("VIXL_PROVIDERS", str(tmp_path / "none.json"))
    monkeypatch.delenv("VIXL_AI_PROVIDER", raising=False)
    with pytest.raises(VixlError, match="Configure"):
        provider()
