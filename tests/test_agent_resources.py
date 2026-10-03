import asyncio
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import httpx
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from vixl import Project, VixlError
from vixl.ai import encoded, make_provider, plan
from vixl.fonts import import_font
from vixl.geometry import EXTRA_SHAPES
from vixl.interfaces import Session, create_app, mcp_server
from vixl.models import catalog_provider, discovery_command, discover, load_config, route, save_provider
from vixl.resources import catalog, create_template, get, register


@pytest.fixture(autouse=True)
def isolated_libraries(tmp_path, monkeypatch):
    monkeypatch.setenv("VIXL_RESOURCES", str(tmp_path / "resources.json"))
    monkeypatch.setenv("VIXL_PROVIDERS", str(tmp_path / "providers.json"))
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MISTRAL_API_KEY",
        "LLAMA_API_KEY",
        "GEMINI_API_KEY",
        "VIXL_AI_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("shape", [s for s in EXTRA_SHAPES if s != "path"])
def test_shortcut_shapes_render_and_export_as_vectors(shape):
    p = Project(64, 64)
    p.apply({"type": "shape", "shape": shape, "width": 48, "height": 48, "x": 8, "y": 8, "fill": "#ff000080"})
    image = p.render()
    assert image.getbbox() and image.getpixel((0, 0))[3] == 0
    root = ET.fromstring(p.export(format="SVG"))
    assert not root.findall(".//{*}image")
    assert root.findall(".//{*}path") or root.findall(".//{*}rect")


def test_editable_bezier_path_resize_roundtrip_and_atomic_rejection(tmp_path):
    p = Project(100, 100)
    p.apply(
        {
            "type": "shape",
            "shape": "path",
            "name": "curve",
            "width": 100,
            "height": 100,
            "path": "M0 0 C0 100 100 100 100 0 L100 100 L0 100 Z",
            "fill": "red",
        }
    )
    p.apply({"type": "resize", "width": 50, "height": 50})
    assert p.render().getpixel((25, 45))[3] > 200
    output = tmp_path / "curve.vixl"
    p.save(output)
    reopened = Project.load(output)
    assert reopened.layer()["path_view"] == [100, 100]
    svg = reopened.export(format="SVG")
    assert b"C0 100 100 100 100 0" in svg and b'viewBox="0 0 100 100"' in svg
    before = deepcopy(p.state)
    with pytest.raises(VixlError):
        p.apply({"type": "shape", "shape": "path", "path": "M0 0 A40 40 0 0 0 100 100"})
    assert p.state == before


def test_transparent_png_jpeg_background_and_native_svg_blur():
    p = Project(20, 20)
    p.apply({"type": "shape", "shape": "rectangle", "width": 10, "height": 10, "fill": "red"})
    with Image.open(BytesIO(p.export(format="PNG"))) as image:
        assert image.mode == "RGBA" and image.getpixel((19, 19))[3] == 0
    with Image.open(BytesIO(p.export(format="JPG", background="blue", quality=100))) as image:
        assert image.mode == "RGB" and image.getpixel((19, 19))[2] > 240
    p.apply({"type": "blur", "value": 1})
    root = ET.fromstring(p.export(format="SVG"))
    assert root.find(".//{*}image") is None
    assert root.find(".//{*}feGaussianBlur").attrib["stdDeviation"] == "1"


def test_resources_custom_templates_guidance_and_undo(tmp_path):
    assert len(catalog("palettes")) >= 30
    register("palettes", "brand", ["#123456", "#abcdef"])
    p = Project(10, 10)
    p.apply({"type": "palette-apply", "name": "brand"})
    assert p.state["swatches"]["brand-1"] == "#123456"
    register("guidance", "brand", "Use our two colors and generous margins.")
    p.apply({"type": "guidance", "name": "brand", "style": "brand"})
    document = tmp_path / "guide.vixl"
    p.save(document)
    assert Project.load(document).state["design_guidance"]["brand"] == get("guidance", "brand")
    register(
        "templates",
        "custom",
        {
            "width": 30,
            "height": 20,
            "defaults": {"color": "red"},
            "operations": [
                {
                    "type": "shape",
                    "shape": "triangle",
                    "fill": "${color}",
                    "name": "mark",
                    "width": 10,
                    "height": 10,
                }
            ],
        },
    )
    created = create_template("custom", {"color": "blue"})
    assert created.render().getpixel((5, 8))[2] > 200
    created.undo()
    assert not created.state["layers"]
    for bad in (
        {"width": 1},
        {"width": 10, "height": 10, "operations": [{"type": "add", "path": "/secret"}]},
        {"width": 10, "height": 10, "operations": [{"type": "template-apply", "name": "custom"}]},
    ):
        with pytest.raises(VixlError):
            register("templates", "bad", bad)
    for name in catalog("templates"):
        assert create_template(name).render().getbbox()


def test_font_import_portable_registered_names_and_https(monkeypatch, tmp_path):
    font = Path(__import__("vixl").__file__).parent / "data" / "DejaVuSans.ttf"
    p = Project(128, 64)
    data = font.read_bytes()
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data)), **kw
        ),
    )
    import_font(p, "https://fonts.example/font.ttf", "brand")
    p.apply({"type": "text", "text": "Vixl", "font": "brand", "size": 24})
    asset = p.layer()["font"]
    assert asset.startswith("fonts/") and asset in p.assets
    path = tmp_path / "font.vixl"
    p.save(path)
    assert Project.load(path).render().getbbox()
    before = deepcopy(p.state)
    with pytest.raises(VixlError):
        import_font(p, "http://fonts.example/font.ttf", "unsafe")
    assert p.state == before
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"not a font")), **kw
        ),
    )
    with pytest.raises(VixlError, match="TrueType"):
        import_font(p, "https://fonts.example/font.css", "invalid")


def test_document_independent_help_catalog_and_compact_cli(tmp_path):
    def cli(*args, input=None):
        return subprocess.run(
            [sys.executable, "-m", "vixl", *args], cwd=tmp_path, input=input, capture_output=True, timeout=20
        )

    for cmd in (
        "export",
        "validate",
        "shape",
        "ask",
        "font",
        "palette",
        "template",
        "guidance",
        "models",
        "providers",
        "inspect",
        "serve",
    ):
        result = cli(cmd, "--help")
        assert result.returncode == 0 and b"No current project" not in result.stderr, (cmd, result.stderr)
    commands = json.loads(cli("commands", "--json").stdout)["commands"]
    assert {"shape", "export", "palette", "models", "template"} <= set(commands)
    assert cli("template", "new", "logo", "-o", "logo.vixl").returncode == 0
    result = cli("apply", "-", input=b'{"operations":[{"type":"move","target":"mark","x":1}]}')
    compact = json.loads(result.stdout)
    assert "layers" in compact["changes"] and "canvas" not in compact["changes"]
    result = cli(
        "--detail",
        "full",
        "apply",
        "-",
        "--dry-run",
        input=b'{"operations":[{"type":"move","target":"mark","x":2}]}',
    )
    assert "before" in json.loads(result.stdout)["changes"]["layers"]


def test_mcp_resources_templates_font_and_vector_geometry(tmp_path):
    server = mcp_server(workspace=tmp_path)
    font = Path(__import__("vixl").__file__).parent / "data" / "DejaVuSans.ttf"
    (tmp_path / "font.ttf").write_bytes(font.read_bytes())

    async def run():
        await server.call_tool("vixl_template_create", {"path": "logo.vixl", "name": "logo"})
        await server.call_tool("vixl_import_font", {"path": "font.ttf", "name": "brand"})
        await server.call_tool(
            "vixl_text_add", {"text": "Vixl", "name": "label", "font": "brand", "size": 16}
        )
        await server.call_tool(
            "vixl_operations_apply",
            {
                "operations": [
                    {
                        "type": "shape",
                        "shape": "path",
                        "name": "curve",
                        "width": 100,
                        "height": 100,
                        "path": "M0 0 Q50 100 100 0 Z",
                    }
                ]
            },
        )
        await server.call_tool("vixl_export_file", {"path": "logo.svg"})

    asyncio.run(run())
    assert ET.fromstring((tmp_path / "logo.svg").read_bytes()).find(".//{*}path") is not None
    assert Project.load(tmp_path / "logo.vixl").state["fonts"]
    s = Session(workspace=tmp_path)
    s.open("logo.vixl")
    with pytest.raises(VixlError):
        s.apply({"type": "text", "font": "/etc/passwd", "text": "bad"})


def test_rest_svg_and_resources(tmp_path):
    p = Project(16, 16)
    path = tmp_path / "api.vixl"
    p.save(path)
    client = TestClient(create_app(path))
    assert client.get("/resources/palettes").status_code == 200
    result = client.post(
        "/operations",
        json={
            "operations": [
                {"type": "shape", "shape": "path", "width": 16, "height": 16, "path": "M0 0 L16 0 L0 16 Z"}
            ]
        },
    )
    assert result.status_code == 200, result.text
    response = client.post("/export", json={"format": "SVG"})
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert ET.fromstring(response.content).find(".//{*}path") is not None
    assert client.post("/export", json={"path": "/bad"}).status_code == 400


@pytest.mark.parametrize(
    "kind,key,model,expected",
    [
        ("openai", "OPENAI_API_KEY", {"id": "gpt-image-1"}, ["generate"]),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            {"id": "claude-sonnet-4-5"},
            ["plan", "describe", "detect", "ocr"],
        ),
        (
            "mistral",
            "MISTRAL_API_KEY",
            {"id": "pixtral-large-latest", "capabilities": {"completion_chat": True, "vision": True}},
            ["plan", "describe", "detect", "ocr"],
        ),
        ("meta", "LLAMA_API_KEY", {"id": "Llama-4-Scout"}, ["plan", "describe", "detect", "ocr"]),
        (
            "gemini",
            "GEMINI_API_KEY",
            {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": ["generateContent"]},
            ["plan", "describe", "detect", "ocr", "generate"],
        ),
    ],
)
def test_add_provider_discovers_account_models_without_saving_keys(kind, key, model, expected, monkeypatch):
    monkeypatch.setenv(key, "test-secret")
    real_client = httpx.Client
    calls = []

    def handler(req):
        calls.append(req)
        if kind == "anthropic":
            assert req.headers["x-api-key"] == "test-secret" and "authorization" not in req.headers
        elif kind == "gemini":
            assert req.headers["x-goog-api-key"] == "test-secret" and "key=" not in str(req.url)
        else:
            assert req.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"models" if kind == "gemini" else "data": [model]})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )
    result = discovery_command("providers", ["add", kind, "--type", kind, "--key-env", key])
    assert result["models"][0]["capabilities"] == expected
    assert calls[0].url.path.endswith("/models")
    assert "test-secret" not in json.dumps(load_config())
    listed = discovery_command("models", ["--provider", kind])
    assert listed["models"][0]["id"] == model.get("id", model.get("name"))


def test_capability_routing_selects_available_provider_and_explicit_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    save_provider(
        "anthropic",
        {
            "type": "anthropic",
            "url": "https://api.anthropic.com/v1",
            "key_env": "ANTHROPIC_API_KEY",
            "models": [{"id": "claude", "capabilities": ["plan"]}],
        },
    )
    save_provider(
        "openai",
        {
            "type": "openai",
            "url": "https://api.openai.com/v1",
            "key_env": "OPENAI_API_KEY",
            "models": [
                {"id": "gpt-image-1", "capabilities": ["generate"]},
                {"id": "gpt-image-2", "capabilities": ["generate"]},
            ],
        },
    )
    monkeypatch.setenv("VIXL_AI_PROVIDER", "anthropic")
    backend = route("generate", model="gpt-image-2")
    assert backend.name == "openai" and backend.config["model"] == "gpt-image-2"
    with pytest.raises(VixlError, match="No configured model"):
        route("generate", "anthropic")
    with pytest.raises(VixlError, match="No configured model"):
        route("generate", "openai", "unknown")


def test_native_adapter_planning_and_gemini_image(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    a = make_provider(
        "a", {"type": "anthropic", "url": "https://example.test/v1", "key_env": "TEST_KEY", "model": "claude"}
    )
    calls = []

    def response(method, route, **kw):
        calls.append((route, kw))
        return {"content": [{"type": "text", "text": '{"operations":[{"type":"shape","shape":"triangle"}]}'}]}

    from types import SimpleNamespace

    def sdk_response(arguments):
        calls.append(("/messages", {"json": arguments}))
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text='{"operations":[{"type":"shape","shape":"triangle"}]}')
            ],
        )

    monkeypatch.setattr(a, "call", sdk_response)
    p = Project(16, 16)
    p.apply({"type": "guidance", "name": "logo", "style": "logo"})
    assert not plan(p, "make a mark", a)["applied"]
    body = calls[-1][1]["json"]
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert "design_guidance" in body["messages"][0]["content"][1]["text"]
    g = make_provider(
        "g",
        {
            "type": "gemini",
            "url": "https://example.test/v1beta",
            "key_env": "TEST_KEY",
            "model": "models/gemini-image",
        },
    )
    data = encoded(Image.new("RGBA", (16, 16), "red"))
    monkeypatch.setattr(
        g,
        "json",
        lambda *args, **kwargs: {"candidates": [{"content": {"parts": [{"inlineData": {"data": data}}]}}]},
    )
    assert g.invoke("generate", {"width": 16, "height": 16, "prompt": "red"})["image"] == data


def test_discovery_pagination_and_failed_onboarding_preserves_config(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    a = catalog_provider("a", {"type": "anthropic", "url": "https://example.test/v1", "key_env": "TEST_KEY"})
    calls = []

    def page(method, route, **kw):
        calls.append(kw["params"])
        return {"data": [{"id": "b" if len(calls) > 1 else "a"}], "has_more": len(calls) == 1, "last_id": "a"}

    monkeypatch.setattr(a, "json", page)
    assert len(discover(a)) == 2 and calls[1]["after_id"] == "a"
    save_provider("working", {"type": "http", "url": "http://localhost:1234", "models": []})
    before = load_config()
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(lambda req: httpx.Response(401)), **kw),
    )
    with pytest.raises(VixlError, match="401"):
        discovery_command("providers", ["add", "working", "--type", "openai", "--key-env", "TEST_KEY"])
    assert load_config() == before
    with pytest.raises(VixlError, match="no supported public API"):
        discovery_command("providers", ["add", "midjourney", "--type", "midjourney", "--key-env", "TEST_KEY"])


def test_every_discovered_cli_command_has_document_independent_help(tmp_path, monkeypatch, capsys):
    from vixl.cli import dispatch

    monkeypatch.chdir(tmp_path)
    result, _ = dispatch(["commands"])
    for command in result["commands"]:
        try:
            dispatch([command, "--help"])
        except SystemExit as exc:
            assert exc.code == 0, command
        capsys.readouterr()
    assert not list(tmp_path.glob("*.vixl"))


def test_template_expansion_counts_toward_operation_budget():
    from vixl.model import Limits

    register(
        "templates",
        "bounded",
        {
            "width": 8,
            "height": 8,
            "operations": [
                {"type": "variable", "name": "a", "value": 1},
                {"type": "variable", "name": "b", "value": 2},
                {"type": "variable", "name": "c", "value": 3},
            ],
        },
    )
    p = Project(8, 8, limits=Limits(max_operations=2))
    with pytest.raises(VixlError, match="operation limit"):
        p.apply({"type": "template-apply", "name": "bounded"})
    assert not p.state["variables"]
