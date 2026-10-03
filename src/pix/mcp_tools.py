"""Typed, bounded MCP tools for a persistent Pix workspace session."""

from copy import deepcopy
from io import BytesIO
import json
import os
import tempfile
from types import SimpleNamespace
from typing import Annotated, Literal

from filelock import FileLock
from PIL import Image as PILImage
from pydantic import Field, WithJsonSchema

from .assets import read_bounded
from .errors import require
from .schema import operation_schema


def service_operation_schema():
    """Advertise canonical service operations directly in tools/list, without alias repetition."""
    from .render import EFFECTS

    groups = {}
    for variant in deepcopy(operation_schema()["properties"]["operations"]["items"]["oneOf"]):
        props = variant["properties"]
        kind = props.pop("type")["const"]
        if kind in EFFECTS:
            continue  # All effects use the canonical {type: effect, name: ...} form.
        for field in ("path", "linked", "font"):
            if kind != "text-layout" or field != "path":
                props.pop(field, None)
        if kind in ("add", "frame"):
            variant.pop("anyOf")
            variant["required"].append("asset")
        if kind == "replace-contents":
            variant["anyOf"] = [{"required": ["asset"]}, {"required": ["variable"]}]
        if kind == "mask":
            props["action"]["enum"].remove("import")
        if kind == "effect":
            props["name"] = {"type": "string", "enum": sorted(EFFECTS)}
        key = json.dumps(variant, sort_keys=True)
        groups.setdefault(key, []).append(kind)
    variants = []
    for key, kinds in groups.items():
        variant = json.loads(key)
        variant["properties"]["type"] = {"type": "string", "enum": kinds}
        variants.append(variant)
    # Hoist identical property constraints once. Each variant still lists its allowed
    # fields (additionalProperties=false), keeping per-operation validation strict.
    definitions = {}
    for variant in variants:
        for key, value in variant["properties"].items():
            definitions.setdefault(key, []).append(value)
    common = {
        key: values[0]
        for key, values in definitions.items()
        if key != "type" and len(values) > 1 and all(value == values[0] for value in values)
    }
    for variant in variants:
        variant.pop("type", None)
        variant["required"].remove("type")
        if not variant["required"]:
            variant.pop("required")
        for key in common.keys() & variant["properties"].keys():
            variant["properties"][key] = {}
    return {"type": "object", "required": ["type"], "properties": common, "oneOf": variants}


Operation = Annotated[dict, WithJsonSchema(service_operation_schema())]
Positive = Annotated[int, Field(ge=1)]
Detail = Literal["compact", "full"]


def preview(
    session, variables=None, max_width=1024, max_height=1024, max_bytes=1_048_576, artboard=None, comp=None
):
    require(1 <= max_width <= 4096 and 1 <= max_height <= 4096, "Preview dimensions must be 1–4096")
    require(65_536 <= max_bytes <= 4_194_304, "Preview byte limit must be 65536–4194304")
    with session.project() as project:
        image = project.render(variables=variables, artboard=artboard, comp=comp)
        image.thumbnail((max_width, max_height), PILImage.Resampling.LANCZOS)
        while True:
            stream = BytesIO()
            image.save(stream, format="PNG")
            data = stream.getvalue()
            if len(data) <= max_bytes:
                return data
            image = image.resize(
                (max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)), PILImage.Resampling.LANCZOS
            )


def export_file(session, path, overwrite=False, **options):
    with session._mutex:
        destination = session.resolve(path)
        require(
            destination.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".avif"),
            "Choose a PNG, JPEG, WEBP, TIFF or AVIF filename",
        )
        require(destination.parent.is_dir(), "Destination directory must exist")
        with FileLock(str(destination) + ".lock", timeout=10, is_singleton=True):
            require(overwrite or not destination.exists(), "Destination already exists; set overwrite=true")
            fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}.get(
                destination.suffix.lower(), destination.suffix[1:].upper()
            )
            with session.project() as project:
                data = project.export(format=fmt, **options)
            fd, temporary = tempfile.mkstemp(dir=destination.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if overwrite:
                    os.replace(temporary, destination)
                else:
                    # Atomic no-clobber publication, including non-Pix writers.
                    os.link(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {"path": str(destination.relative_to(session.workspace)), "format": fmt, "bytes": len(data)}


def typed_ai(session, command, words=(), **options):
    from .ai import ai_execute

    defaults = dict(
        words=list(words),
        provider=None,
        prompt=None,
        negative_prompt=None,
        size=None,
        model=None,
        mode=None,
        selection=None,
        name="generated",
        seed=None,
        strength=0.75,
        apply=False,
        detail="compact",
        double=False,
        scale=2,
        left=0,
        right=0,
        top=0,
        bottom=0,
    )
    defaults.update(options)
    with session.project() as project:
        result, changed = ai_execute(project, command, SimpleNamespace(**defaults))
        if changed:
            project.save()
        return result


def build_server(session):
    from mcp.server.fastmcp import FastMCP, Image

    server = FastMCP(
        "Pix",
        instructions=(
            "Edit images in the configured workspace. Start with pix_workspace_list, then create/open a document. "
            "Imports and exports use server-local paths relative to the workspace. Edits autosave atomically. "
            "Use stable layer IDs from inspect/results. Operation formats are in pix_operations_apply's schema. "
            "Previews are resized for model context; export writes full resolution. AI tools need a configured provider."
        ),
    )

    @server.tool()
    def pix_workspace_list(
        directory: str = ".",
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=200)] = 100,
    ) -> dict:
        """List files/directories in the workspace, paginated; paths are local to this server."""
        directory_path = session.resolve(directory)
        require(directory_path.is_dir(), "Directory does not exist")
        entries = sorted(
            (
                p
                for p in directory_path.iterdir()
                if not p.name.endswith(".lock") and p.resolve().is_relative_to(session.workspace)
            ),
            key=lambda p: p.name,
        )
        return {
            "workspace": str(session.workspace),
            "active_document": str(session.path) if session.path else None,
            "entries": [
                {"path": str(p.relative_to(session.workspace)), "directory": p.is_dir()}
                for p in entries[offset : offset + limit]
            ],
            "next_offset": offset + limit if offset + limit < len(entries) else None,
        }

    @server.tool()
    def pix_document_create(
        path: str, width: Positive, height: Positive, background: str = "transparent"
    ) -> dict:
        """Create and activate a new .pix file. Never overwrites an existing file."""
        return session.create(path, width, height, background)

    @server.tool()
    def pix_document_open(path: str) -> dict:
        """Open/activate an existing .pix file in the workspace. Previous edits are already saved."""
        return session.open(path)

    @server.tool()
    def pix_document_inspect(target: str | None = None) -> dict:
        """Inspect the document, or just one layer by stable ID/name, including resolved pixel bounds."""
        with session.project() as project:
            return project.inspect(target)

    @server.tool()
    def pix_operations_apply(
        operations: Annotated[list[Operation], Field(min_length=1, max_length=1000)],
        dry_run: bool = False,
        detail: Detail = "compact",
    ) -> dict:
        """Apply typed operations atomically and autosave. Compact returns changed fields by layer ID;
        full explicitly includes before/after snapshots. dry_run validates without saving.
        Coordinates are pixels in the parent group or canvas; omit target to use the active layer. Import paths via pix_import_image.
        """
        return session.apply(operations, dry_run, detail)

    @server.tool()
    def pix_render_preview(
        variables: dict | None = None,
        max_width: Annotated[int, Field(ge=1, le=4096)] = 1024,
        max_height: Annotated[int, Field(ge=1, le=4096)] = 1024,
        max_bytes: Annotated[int, Field(ge=65536, le=4194304)] = 1_048_576,
        artboard: str | None = None,
        comp: str | None = None,
    ) -> Image:
        """Return an aspect-preserving PNG, capped in dimensions AND encoded bytes (default 1 MiB).
        If needed, shrink further to fit the byte limit. Original document resolution is unchanged.
        """
        return Image(
            data=preview(session, variables, max_width, max_height, max_bytes, artboard, comp), format="png"
        )

    @server.tool()
    def pix_import_image(path: str, name: str = "image") -> dict:
        """Read a server-local workspace image file and embed it as a layer; no base64 output needed."""
        return session.import_image(read_bounded(session.resolve(path), session.limits.max_asset_bytes), name)

    @server.tool()
    def pix_export_file(
        path: str,
        quality: Annotated[int, Field(ge=1, le=100)] = 90,
        scale: Annotated[float, Field(ge=0.01, le=16)] = 1,
        profile: str | None = None,
        variables: dict | None = None,
        background: str = "white",
        overwrite: bool = False,
        sampling: Literal["smooth", "nearest"] = "smooth",
        artboard: str | None = None,
        comp: str | None = None,
    ) -> dict:
        """Export the active document to a workspace file, format from extension; full size by default.
        Supports PNG/JPEG/WEBP/TIFF/AVIF. Returns file metadata, never image bytes.
        """
        return export_file(
            session,
            path,
            overwrite,
            quality=quality,
            scale=scale,
            profile=profile,
            variables=variables,
            background=background,
            sampling=sampling,
            artboard=artboard,
            comp=comp,
        )

    @server.tool()
    def pix_measure_spacing(
        targets: list[str] | None = None,
        axis: Literal["horizontal", "vertical"] = "vertical",
        around: str | None = None,
        before: str | None = None,
        after: str | None = None,
        expected: float | None = None,
        tolerance: Annotated[float, Field(ge=0)] = 1,
        artboard: str | None = None,
        comp: str | None = None,
    ) -> dict:
        """Check intended equal gaps or balance before/after an object. Opt-in; no layout guessing.
        Returns exact geometric gaps, overlap, spread and pass/fail within the supplied tolerance.
        """
        return session.measure_spacing(
            targets=targets,
            axis=axis,
            around=around,
            before=before,
            after=after,
            expected=expected,
            tolerance=tolerance,
            artboard=artboard,
            comp=comp,
        )

    @server.tool()
    def pix_pixels_inspect(target: str | None = None) -> dict:
        """Inspect a pixel layer as compact character rows and palette colors, without image bytes."""
        with session.project() as project:
            return project.inspect_pixels(target)

    @server.tool()
    def pix_animation_inspect() -> dict:
        """List saved animation frame names, sizes and durations without full snapshots."""
        with session.project() as project:
            return project.inspect_animation()

    @server.tool()
    def pix_animation_preview(name: str, scale: Annotated[int, Field(ge=1, le=8)] = 1) -> Image:
        """Preview a saved frame with crisp integer scaling (default: native pixel size)."""
        with session.project() as project:
            image = project.render_frame(name, scale)
            stream = BytesIO()
            image.save(stream, format="PNG")
            require(len(stream.getvalue()) <= 4_194_304, "Frame preview exceeds 4 MiB; use a smaller scale")
            return Image(data=stream.getvalue(), format="png")

    @server.tool()
    def pix_export_animation(
        path: str,
        format: Literal["gif", "apng", "sheet"] = "gif",
        scale: Annotated[int, Field(ge=1, le=32)] = 1,
        columns: Positive | None = None,
    ) -> dict:
        """Write saved frames as GIF, APNG or PNG sprite sheet plus JSON timing metadata in the workspace.
        Never overwrites files. Scaling uses nearest-neighbor sampling; sheets preserve every named frame.
        """
        with session.project() as project:
            destination = session.resolve(path)
            result = project.export_animation(destination, format=format, scale=scale, columns=columns)
            result["output"] = str(destination.relative_to(session.workspace))
            if "metadata" in result:
                result["metadata"] = str(destination.with_suffix(".json").relative_to(session.workspace))
            return result

    @server.tool()
    def pix_measure(
        point: list[int] | None = None,
        region: list[int] | None = None,
        foreground: str | None = None,
        target: str | None = None,
        artboard: str | None = None,
        comp: str | None = None,
    ) -> dict:
        """Read RGBA samples, alpha-weighted averages, histograms and rendered layer contrast."""
        return session.measure(
            point=point, region=region, foreground=foreground, target=target, artboard=artboard, comp=comp
        )

    @server.tool()
    def pix_validate(profile: str | None = None, rules: list[str] | None = None) -> dict:
        """Check bounds, export profiles and assertions without changing the document."""
        return session.validate(profile, rules)

    @server.tool()
    def pix_history(
        action: Literal[
            "list", "undo", "redo", "branch", "checkpoint", "checkout", "begin", "commit", "rollback"
        ] = "list",
        ref: str | None = None,
        count: Positive = 1,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict:
        """Navigate history. List returns paginated node summaries; mutation returns the current head."""
        result = session.history(action, ref, count)
        nodes = result.pop("nodes")
        if action == "list":
            result["nodes"] = [
                {k: v for k, v in node.items() if k != "operations"}
                for node in nodes[offset : offset + limit]
            ]
            result["next_offset"] = offset + limit if offset + limit < len(nodes) else None
        return result

    @server.tool()
    def pix_ai_generate(
        prompt: str,
        mode: Literal["generate", "inpaint", "img2img"] = "generate",
        width: Positive | None = None,
        height: Positive | None = None,
        seed: int | None = None,
        name: str = "generated",
        provider: str | None = None,
        model: str | None = None,
        negative_prompt: str | None = None,
        strength: Annotated[float, Field(ge=0, le=1)] = 0.75,
    ) -> dict:
        """Generate an image layer. Defaults to canvas size; supply both width/height together.
        inpaint uses the current selection; img2img uses the canvas. Both must match canvas size.
        """
        require((width is None) == (height is None), "Supply both width and height, or neither")
        return typed_ai(
            session,
            "generate",
            prompt=prompt,
            mode=mode,
            size=f"{width}x{height}" if width is not None else None,
            seed=seed,
            name=name,
            provider=provider,
            model=model,
            negative_prompt=negative_prompt,
            strength=strength,
        )

    @server.tool()
    def pix_ai_remove(name: str = "removed-object", provider: str | None = None) -> dict:
        """Inpaint the selected object using a provider; insert a masked editable layer."""
        return typed_ai(session, "ai", ["remove"], name=name, provider=provider)

    @server.tool()
    def pix_ai_content_aware_fill(
        prompt: str | None = None, name: str = "filled-region", provider: str | None = None
    ) -> dict:
        """Fill the current selection using a configured provider, preserving pixels outside it."""
        return typed_ai(session, "ai", ["content-aware-fill"], prompt=prompt, name=name, provider=provider)

    @server.tool()
    def pix_ai_select_subject(provider: str | None = None) -> dict:
        """Select the main subject using a provider-generated segmentation mask."""
        return typed_ai(session, "ai", ["select-subject"], provider=provider)

    @server.tool()
    def pix_ai_remove_background(layer: str, provider: str | None = None) -> dict:
        """Attach a provider-generated foreground mask to a layer, preserving editable source pixels."""
        return typed_ai(session, "ai", ["background-remove", layer], provider=provider)

    @server.tool()
    def pix_ai_select_object(label: str, provider: str | None = None) -> dict:
        """Select the named object using a provider-generated mask of the current canvas."""
        return typed_ai(session, "select", ["object", label], provider=provider)

    @server.tool()
    def pix_ai_plan(prompt: str, apply: bool = False, provider: str | None = None) -> dict:
        """Ask a configured provider to propose edits; inspect the proposal before apply=true."""
        return typed_ai(session, "ask", prompt=prompt, apply=apply, provider=provider)

    @server.tool()
    def pix_ai_analyze(
        capability: Literal["describe", "detect", "ocr"], query: str = "", provider: str | None = None
    ) -> dict:
        """Describe the canvas, detect objects, or read its text using a configured vision provider."""
        return typed_ai(
            session,
            "ai" if capability == "describe" else capability,
            ["describe", query] if capability == "describe" else [query],
            provider=provider,
        )

    @server.tool()
    def pix_ai_upscale(
        layer: str, scale: Annotated[float, Field(gt=0, le=16)] = 2, provider: str | None = None
    ) -> dict:
        """Create an upscaled copy of a layer using a configured provider."""
        return typed_ai(session, "ai", ["upscale", layer], scale=scale, provider=provider)

    @server.tool()
    def pix_ai_regenerate(
        layer: str, prompt: str | None = None, seed: int | None = None, provider: str | None = None
    ) -> dict:
        """Regenerate a generated layer using its saved settings, preserving its stable ID."""
        return typed_ai(session, "ai", ["regenerate", layer], prompt=prompt, seed=seed, provider=provider)

    @server.tool()
    def pix_ai_extend(
        prompt: str,
        left: Annotated[int, Field(ge=0)] = 0,
        right: Annotated[int, Field(ge=0)] = 0,
        top: Annotated[int, Field(ge=0)] = 0,
        bottom: Annotated[int, Field(ge=0)] = 0,
        seed: int | None = None,
        name: str = "extension",
        provider: str | None = None,
    ) -> dict:
        """Outpaint the canvas by the specified pixel distances; at least one must be positive."""
        return typed_ai(
            session,
            "ai",
            ["extend"],
            prompt=prompt,
            left=left,
            right=right,
            top=top,
            bottom=bottom,
            seed=seed,
            name=name,
            provider=provider,
        )

    @server.resource("pix://operations")
    def operations_reference() -> str:
        return json.dumps(operation_schema())

    return server
