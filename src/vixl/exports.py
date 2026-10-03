"""Bounded data-set and artboard exports without changing the source document."""

import csv
import io
from pathlib import Path

from .assets import add_encoded, read_bounded
from .errors import require, VixlError


def export_screens(project, directory, *, scales=(1, 2), boards=None, **options):
    names = list(boards) if boards is not None else list(project.state.get("artboards", {}))
    require(names, "Create at least one artboard")
    require(1 <= len(scales) <= 8 and len(set(scales)) == len(scales), "Use 1–8 unique scales")
    from .model import finite

    for scale in scales:
        finite(scale, "scale", 0.01, 16)
    root = Path(directory)
    jobs = []
    for name in names:
        require(name in project.state.get("artboards", {}), f"Unknown artboard: {name}")
        for scale in scales:
            path = root / f"{name}@{scale:g}x.png"
            require(not path.exists(), f"Output already exists: {path}")
            jobs.append((name, scale, path))
    # Validate all renders before publishing any output; keep memory bounded to one image.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="vixl-screens-") as staging:
        for i, (name, scale, _) in enumerate(jobs):
            project.export(Path(staging) / f"{i}.png", artboard=name, scale=scale, format="PNG", **options)
        root.mkdir(parents=True, exist_ok=True)
        for i, (_, _, path) in enumerate(jobs):
            with path.open("xb") as stream:
                stream.write((Path(staging) / f"{i}.png").read_bytes())
    return [{"artboard": name, "scale": scale, "output": str(path)} for name, scale, path in jobs]


def render_data(project, csv_path, directory, *, variables=None, **options):
    content = read_bounded(csv_path, 8 * 1024 * 1024).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
    headers = reader.fieldnames
    require(
        headers and len(set(headers)) == len(headers) and all(headers), "CSV requires unique nonempty headers"
    )
    rows = []
    try:
        for row in reader:
            require(len(rows) < 10000, "Data sets support at most 10000 rows", "resource_limit")
            require(
                None not in row and all(v is not None for v in row.values()),
                "CSV row has wrong number of fields",
            )
            rows.append(row)
    except csv.Error as exc:
        raise VixlError("invalid_data", str(exc)) from exc
    require(rows, "CSV contains no data rows")
    root = Path(directory)
    destinations = [root / f"{i + 1:04d}.png" for i in range(len(rows))]
    require(not any(p.exists() for p in destinations), "Data output exists; use an empty directory")
    image_variables = {
        item["asset_variable"] for item in project.state["layers"] if item.get("asset_variable")
    }
    import tempfile

    with tempfile.TemporaryDirectory(prefix="vixl-data-") as staging:
        for i, row in enumerate(rows):
            candidate = project.clone()
            values = {**row, **(variables or {})}
            for key in image_variables & values.keys():
                if values[key] not in candidate.assets:
                    path = Path(values[key])
                    if not path.is_absolute():
                        path = Path(csv_path).resolve().parent / path
                    values[key], _ = add_encoded(
                        candidate, read_bounded(path, candidate.limits.max_asset_bytes)
                    )
            candidate.export(Path(staging) / f"{i}.png", variables=values, format="PNG", **options)
        root.mkdir(parents=True, exist_ok=True)
        for i, path in enumerate(destinations):
            with path.open("xb") as stream:
                stream.write((Path(staging) / f"{i}.png").read_bytes())
    return [{"row": i + 1, "output": str(path)} for i, path in enumerate(destinations)]
