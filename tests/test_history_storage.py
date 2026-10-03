import io
import json
import os
import zipfile

from PIL import Image
import pytest

from vixl import Project, VixlError
from vixl.history import diff, patch
from vixl.model import Limits
from vixl.project import SNAPSHOT_INTERVAL


def moves(project, count, target="box"):
    for i in range(count):
        project.apply({"type": "move", "target": target, "x": i, "y": 0})


def test_delta_roundtrip_handles_keyed_lists_and_deletions():
    before = {"a": 1, "layers": [{"id": "x", "v": 1}, {"id": "y", "v": 2}], "gone": True}
    after = {"a": 1.5, "layers": [{"id": "y", "v": 3}, {"id": "z", "v": 4}], "new": [1, 2]}
    delta = diff(before, after)
    assert delta["s"]["layers"]["$"] == "l"
    assert patch(before, delta) == after
    assert diff(after, after) is None


def test_history_stores_deltas_with_periodic_snapshots(tmp_path):
    p = Project(64, 64)
    p.apply({"type": "solid", "name": "box", "color": "red", "width": 8, "height": 8})
    moves(p, SNAPSHOT_INTERVAL * 2)
    kinds = ["state" in node for node in p.nodes.values()]
    assert sum(kinds) == 3  # the root plus one snapshot per interval
    p.save(tmp_path / "doc.vixl")
    q = Project.load(tmp_path / "doc.vixl")
    assert q.state == p.state
    q.undo(SNAPSHOT_INTERVAL + 5)
    assert q.layer("box")["x"] == SNAPSHOT_INTERVAL * 2 - 1 - (SNAPSHOT_INTERVAL + 5)
    q.redo(3)
    assert q.layer("box")["x"] == SNAPSHOT_INTERVAL * 2 - 1 - (SNAPSHOT_INTERVAL + 2)


def test_edits_share_history_instead_of_copying_it():
    p = Project(16, 16)
    p.apply({"type": "solid", "name": "box", "color": "red"})
    first = next(iter(p.nodes.values()))
    moves(p, 5)
    assert next(iter(p.nodes.values())) is first


def test_history_limit_prunes_oldest_revisions_instead_of_locking(tmp_path):
    p = Project(16, 16, limits=Limits(max_history=40))
    p.apply({"type": "solid", "name": "box", "color": "red", "width": 4, "height": 4})
    p.checkpoint("start")
    start = p.checkpoints["start"]
    moves(p, 200)
    assert len(p.nodes) <= 40
    assert p.layer("box")["x"] == 199
    assert start in p.nodes
    p.undo(10)
    assert p.layer("box")["x"] == 189
    p.redo(10)
    p.save(tmp_path / "doc.vixl")
    q = Project.load(tmp_path / "doc.vixl", limits=Limits(max_history=40))
    q.checkout("start")
    assert q.layer("box")["x"] == 0
    assert any(node.get("squashed") for node in q.nodes.values())


def test_pruning_fails_only_when_every_revision_is_protected():
    p = Project(16, 16, limits=Limits(max_history=3))
    p.checkpoint("root")
    p.apply({"type": "solid", "name": "box", "color": "red"})
    p.checkpoint("solid")
    p.apply({"type": "move", "target": "box", "x": 1, "y": 0})
    with pytest.raises(VixlError) as error:
        p.apply({"type": "move", "target": "box", "x": 9, "y": 0})
    assert error.value.code == "resource_limit"


def test_pruned_history_releases_unreferenced_assets(tmp_path):
    p = Project(16, 16, limits=Limits(max_history=12))
    p.apply({"type": "solid", "name": "box", "color": "red", "width": 8, "height": 8})
    for i in range(30):
        p.apply({"type": "select", "shape": "rect", "x": i % 8, "y": 0, "width": 4, "height": 4})
    p.save(tmp_path / "doc.vixl")
    with zipfile.ZipFile(tmp_path / "doc.vixl") as archive:
        masks = [name for name in archive.namelist() if name.startswith("masks/")]
    assert len(masks) <= 12
    assert Project.load(tmp_path / "doc.vixl", limits=Limits(max_history=12)).state == p.state


def tampered(tmp_path, project, ident, delta):
    project.save(tmp_path / "doc.vixl")
    with zipfile.ZipFile(tmp_path / "doc.vixl") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    data = json.loads(files["project.json"])
    data["nodes"][ident]["delta"] = delta
    files["project.json"] = json.dumps(data).encode()
    with zipfile.ZipFile(tmp_path / "bad.vixl", "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return tmp_path / "bad.vixl"


def test_tampered_history_delta_is_rejected_when_used(tmp_path):
    p = Project(16, 16)
    p.apply({"type": "solid", "name": "box", "color": "red"})
    p.checkpoint("base")
    p.apply({"type": "move", "target": "box", "x": 5, "y": 0})
    p.branch("side")
    side = p.head
    p.checkout("base")
    p.apply({"type": "move", "target": "box", "x": 9, "y": 0})
    bad = {"$": "o", "s": {"canvas": {"$": "v", "v": "broken"}}}
    q = Project.load(tampered(tmp_path, p, side, bad))
    before = q.state
    with pytest.raises(VixlError):
        q.checkout("side")
    assert q.state == before
    # A corrupt ancestor of the current revision is rejected while loading.
    with pytest.raises(VixlError) as error:
        Project.load(tampered(tmp_path, p, p.head, {"$": "l", "k": "id", "o": [], "s": {}}))
    assert error.value.code == "invalid_project"


def test_format_1_projects_with_full_snapshots_still_load(tmp_path):
    p = Project(16, 16)
    p.apply({"type": "solid", "name": "box", "color": "red"})
    moves(p, 2)
    manifest = p.manifest()
    manifest["format_version"] = 1
    manifest["nodes"] = {
        ident: {
            "id": ident,
            "parent": node["parent"],
            "operations": node["operations"],
            "label": node["label"],
            "state": p._state_at(ident),
        }
        for ident, node in p.nodes.items()
    }
    with zipfile.ZipFile(tmp_path / "old.vixl", "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
    q = Project.load(tmp_path / "old.vixl")
    q.undo(2)
    assert q.layer("box")["x"] == 0


def test_imported_jpeg_keeps_original_bytes(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (64, 48), "orange").save(source, quality=80)
    p = Project(64, 48)
    p.apply({"type": "add", "path": str(source), "name": "photo"})
    asset = p.layer("photo")["asset"]
    assert asset.endswith(".jpg")
    assert p.assets[asset] == source.read_bytes()
    p.save(tmp_path / "doc.vixl")
    with zipfile.ZipFile(tmp_path / "doc.vixl") as archive:
        assert archive.getinfo(asset).compress_type == zipfile.ZIP_STORED
    q = Project.load(tmp_path / "doc.vixl")
    assert q.render().tobytes() == p.render().tobytes()


def test_animated_or_exotic_formats_are_normalized_to_png(tmp_path):
    frames = [Image.new("RGB", (8, 8), c) for c in ("red", "blue")]
    stream = io.BytesIO()
    frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:])
    (tmp_path / "anim.gif").write_bytes(stream.getvalue())
    p = Project(8, 8)
    p.apply({"type": "add", "path": str(tmp_path / "anim.gif"), "name": "anim"})
    assert p.layer("anim")["asset"].endswith(".png")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_saving_preserves_existing_file_permissions(tmp_path):
    path = tmp_path / "doc.vixl"
    p = Project(8, 8)
    p.save(path)
    os.chmod(path, 0o640)
    p.apply({"type": "solid", "name": "box", "color": "red"})
    p.save()
    assert os.stat(path).st_mode & 0o777 == 0o640
    fresh = Project(8, 8)
    fresh.save(tmp_path / "fresh.vixl")
    assert os.stat(tmp_path / "fresh.vixl").st_mode & 0o044  # not forced private by mkstemp
