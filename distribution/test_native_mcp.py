"""Exercise the installed, frozen Windows executable through a real MCP stdio client."""

import asyncio
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image


async def verify(executable, workspace):
    Image.new("RGB", (2400, 1600), "blue").save(workspace / "input photo.jpg")
    params = StdioServerParameters(
        command=executable,
        args=["mcp", "--workspace", str(workspace)],
        env={**os.environ, "PIX_NO_UPDATE": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert tools["pix_operations_apply"].inputSchema["properties"]["operations"]["items"]["oneOf"]
            assert "pix_ai_remove_background" in tools and "pix_ai" not in tools

            async def call(tool, **arguments):
                result = await client.call_tool(tool, arguments)
                assert not result.isError, result
                return result

            await call("pix_document_create", path="new.pix", width=2400, height=1600)
            await call("pix_import_image", path="input photo.jpg", name="photo")
            result = await call("pix_operations_apply", operations=[{"type": "move", "x": 5}])
            assert len(json.dumps(result.model_dump())) < 1500
            result = await call("pix_render_preview", max_width=512, max_height=512, max_bytes=65536)
            data = base64.b64decode(result.content[0].data)
            assert len(data) <= 65536 and Image.open(BytesIO(data)).width <= 512
            await call("pix_export_file", path="exported.png")
            await call("pix_document_create", path="second.pix", width=16, height=16)
            await call("pix_document_open", path="new.pix")
            await call("pix_document_inspect", target="photo")
            await call("pix_document_create", path="sprite.pix", width=4, height=4)
            await call(
                "pix_operations_apply",
                operations=[
                    {"type": "pixel-art", "name": "sprite", "width": 4, "height": 4},
                    {"type": "pixel-draw", "x": 0, "y": 0, "color": "#"},
                    {"type": "frame-save", "name": "idle", "duration": 100},
                    {"type": "pixel-draw", "x": 1, "y": 0, "color": "#"},
                    {"type": "frame-save", "name": "spark", "duration": 200},
                ],
            )
            await call("pix_pixels_inspect", target="sprite")
            await call("pix_animation_preview", name="idle")
            await call("pix_export_animation", path="sprite.gif", format="gif", scale=2)
            await call("pix_export_animation", path="sprite.png", format="sheet", scale=2)
            await call(
                "pix_operations_apply",
                operations=[
                    {"type": "solid", "name": "a", "width": 1, "height": 1},
                    {"type": "solid", "name": "b", "width": 1, "height": 1, "y": 2},
                ],
            )
            await call("pix_measure_spacing", targets=["a", "b"], expected=1, tolerance=0)
    assert Image.open(workspace / "exported.png").size == (2400, 1600)
    assert Image.open(workspace / "sprite.gif").n_frames == 2
    assert Image.open(workspace / "sprite.png").size == (16, 8)
    assert json.loads((workspace / "sprite.json").read_text())["frames"][1]["duration"] == 200
    print(
        "Installed MCP schemas, document lifecycle, path import, bounded preview and full-size export passed."
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pix MCP workspace ") as directory:
        asyncio.run(verify(sys.argv[1], Path(directory)))
