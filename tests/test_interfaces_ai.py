import asyncio
from copy import deepcopy
import os
import sys

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from vixl import Project, VixlError
from vixl.ai import ai_command, encoded, generate, plan
from vixl.interfaces import create_app


@pytest.fixture
def project_path(tmp_path):
    p = Project(16, 16)
    p.apply({"type": "solid", "name": "logo", "color": "red", "width": 8, "height": 8})
    path = tmp_path / "test.vixl"
    p.save(path)
    return path


def test_rest_operations_preview_auth_and_sandbox(project_path):
    client = TestClient(create_app(project_path, token="test-token"))
    assert client.get("/document").status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    response = client.get("/document", headers=headers)
    assert response.status_code == 200 and response.json()["canvas"]["width"] == 16
    response = client.post(
        "/operations", headers=headers, json={"operations": [{"type": "move", "target": "logo", "x": 4}]}
    )
    assert response.status_code == 200, response.text
    assert Project.load(project_path).layer()["x"] == 4
    before = project_path.read_bytes()
    response = client.post(
        "/operations",
        headers=headers,
        json={"operations": [{"type": "opacity", "value": 0.2}], "dry_run": True},
    )
    assert response.json()["dry_run"]
    assert project_path.read_bytes() == before
    response = client.post(
        "/operations", headers=headers, json={"operations": [{"type": "add", "path": "/etc/passwd"}]}
    )
    assert response.status_code == 403
    response = client.get("/render", headers=headers)
    assert response.headers["content-type"] == "image/png" and response.content.startswith(b"\x89PNG")
    assert client.post("/validate", headers=headers, json={}).json()["valid"]
    assert client.post("/history/undo", headers=headers, json={}).status_code == 200
    assert Project.load(project_path).layer()["x"] == 0
    data = Project(4, 4, "blue").export(format="PNG")
    response = client.post("/assets?name=blue", headers=headers, content=data)
    assert response.status_code == 200, response.text
    assert Project.load(project_path).layer()["name"] == "blue"


def test_rest_rebinding_body_limit_and_atomic_failure(project_path):
    client = TestClient(create_app(project_path))
    assert client.get("/document", headers={"host": "evil.example"}).status_code == 400
    assert (
        client.post("/assets", content=b"image", headers={"origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.post("/operations", content=b"x" * (1024 * 1024 + 1)).status_code == 413
    before = project_path.read_bytes()
    result = client.post(
        "/operations", json={"operations": [{"type": "move", "x": 10}, {"type": "opacity", "value": 5}]}
    )
    assert result.status_code == 400 and project_path.read_bytes() == before


class FakeProvider:
    name = "fixture"

    def __init__(self):
        self.requests = []

    def invoke(self, capability, request):
        self.requests.append((capability, deepcopy(request)))
        if capability == "plan":
            return {"operations": [{"type": "scale", "target": "logo", "value": 0.5}]}
        if capability in ("segment", "background-remove"):
            mask = Image.new("L", (request["width"], request["height"]), 0)
            mask.paste(255, (0, 0, request["width"] // 2, request["height"]))
            return {"mask": encoded(mask)}
        if capability in ("describe", "detect", "ocr"):
            return {"description": "fixture"}
        return {
            "image": encoded(Image.new("RGBA", (request["width"], request["height"]), "blue")),
            "seed": 123,
            "model": "fixture-v1",
        }


def test_reasoning_dryrun_and_restricted_plan(project_path):
    p = Project.load(project_path)
    backend = FakeProvider()
    result = plan(p, "smaller", backend)
    assert not result["applied"] and p.layer()["width"] == 8
    plan(p, "smaller", backend, apply=True)
    assert p.layer()["width"] == 4
    backend.invoke = lambda *_: {"operations": [{"type": "add", "path": "/etc/passwd"}]}
    with pytest.raises(VixlError):
        plan(p, "unsafe", backend, apply=True)


def test_ai_inpaint_outpaint_mask_and_regenerate(project_path, monkeypatch):
    import vixl.ai

    backend = FakeProvider()
    monkeypatch.setattr(vixl.ai, "provider", lambda _: backend)
    p = Project.load(project_path)
    p.apply({"type": "select", "shape": "rect", "x": 0, "y": 0, "width": 4, "height": 4})
    before = p.render()
    result, changed = ai_command(
        p, "generate", ["--prompt", "blue patch", "--mode", "inpaint", "--as", "patch"]
    )
    assert changed and result["provenance"]["seed"] == 123
    image = p.render()
    assert image.getpixel((1, 1)) == (0, 0, 255, 255)
    assert image.getpixel((5, 5)) == before.getpixel((5, 5))
    ident = p.layer()["id"]
    p.save()
    p = Project.load(project_path)
    ai_command(p, "ai", ["regenerate", "patch", "--prompt", "another blue"])
    assert p.layer()["id"] == ident
    assert len(p.state["layers"]) == 2
    p.undo()
    assert p.layer()["provenance"]["request"]["prompt"] == "blue patch"
    state = deepcopy(p.state)
    ai_command(p, "ai", ["extend", "--right", "8", "--as", "extension", "--prompt", "more blue"])
    assert p.state["canvas"]["width"] == 24
    assert p.render().getpixel((20, 8)) == (0, 0, 255, 255)
    p.undo()
    assert p.state == state


def test_ai_segmentation_and_background_removal(project_path, monkeypatch):
    import vixl.ai

    backend = FakeProvider()
    monkeypatch.setattr(vixl.ai, "provider", lambda _: backend)
    p = Project.load(project_path)
    ai_command(p, "select", ["object", "left half"])
    assert p.image(p.state["selection"], "L").getpixel((12, 2)) == 0
    ai_command(p, "ai", ["background-remove", "logo"])
    assert p.render().getpixel((6, 2))[3] == 0
    assert p.render().getpixel((2, 2))[3] == 255


def test_provider_failure_never_changes_state(project_path):
    p = Project.load(project_path)
    before = deepcopy(p.manifest())
    backend = FakeProvider()
    backend.invoke = lambda *_: {"image": "bad base64"}
    with pytest.raises(VixlError):
        generate(p, {"width": 16, "height": 16, "prompt": "x"}, backend)
    assert p.manifest() == before


def test_real_mcp_stdio_handshake_and_tools(project_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "vixl", "--project", str(project_path), "mcp"],
            env=os.environ.copy(),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "Vixl"
                listed = await client.list_tools()
                assert "vixl_operations_apply" in [t.name for t in listed.tools]
                result = await client.call_tool("vixl_document_inspect", {})
                assert not result.isError
                result = await client.call_tool(
                    "vixl_operations_apply", {"operations": [{"type": "move", "target": "logo", "y": 3}]}
                )
                assert not result.isError
                result = await client.call_tool("vixl_render_preview", {})
                assert not result.isError and result.content[0].type == "image"

    asyncio.run(run())
    assert Project.load(project_path).layer()["y"] == 3


def test_ai_regeneration_replaces_pixels_and_preserves_id(project_path, monkeypatch):
    import vixl.ai

    backend = FakeProvider()
    monkeypatch.setattr(vixl.ai, "provider", lambda _: backend)
    p = Project.load(project_path)
    ai_command(p, "generate", ["--prompt", "blue", "--as", "art"])
    ident = p.layer()["id"]
    old = p.layer()["asset"]
    backend.invoke = lambda *_: {"image": encoded(Image.new("RGBA", (16, 16), "green")), "seed": 456}
    ai_command(p, "ai", ["regenerate", "art", "--prompt", "green"])
    assert p.layer()["id"] == ident and p.layer()["asset"] != old
    assert p.layer()["provenance"]["request"]["prompt"] == "green"
    assert p.render().getpixel((12, 12)) == (0, 128, 0, 255)
    p.undo()
    assert p.layer()["asset"] == old
    assert p.render().getpixel((12, 12)) == (0, 0, 255, 255)


def test_ai_transaction_rollback_does_not_corrupt_prior_history(project_path, monkeypatch):
    import vixl.ai

    monkeypatch.setattr(vixl.ai, "provider", lambda _: FakeProvider())
    p = Project.load(project_path)
    nodes = deepcopy(p.nodes)
    state = deepcopy(p.state)
    p.begin()
    ai_command(p, "ai", ["background-remove", "logo"])
    ai_command(p, "ai", ["upscale", "logo"])
    assert p.nodes == nodes
    p.rollback()
    assert p.state == state
    p.undo()
    assert not p.state["layers"]


def test_service_invalid_history_and_help_cannot_exit(project_path):
    from vixl.interfaces import Session

    session = Session(project_path)
    with pytest.raises(VixlError):
        session.history("branch", ref=["bad"])
    with pytest.raises(VixlError):
        session.ai("generate", ["--help"])
