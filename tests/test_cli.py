import json
import subprocess
import sys

from PIL import Image
import pytest

from vixl import Project
from vixl.commands import compile_command


def cli(tmp_path, *args, input=None):
    return subprocess.run(
        [sys.executable, "-m", "vixl", *args], cwd=tmp_path, input=input, capture_output=True, timeout=20
    )


def ok(tmp_path, *args):
    r = cli(tmp_path, *args)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout) if r.stdout else None


def test_full_cli_persistent_workflow(tmp_path):
    ok(tmp_path, "new", "120x80", "--background", "#111111", "-o", "poster.vixl")
    ok(tmp_path, "layer", "solid", "--name", "logo", "--color", "red", "--width", "20", "--height", "20")
    ok(tmp_path, "align", "logo", "top-right", "--margin", "5")
    ok(tmp_path, "text", "add", "Hello", "--name", "title", "--size", "16", "--y", "30")
    ok(tmp_path, "text", "title", "--text", "Vixl")
    ok(tmp_path, "checkpoint", "layout")
    ok(tmp_path, "transaction", "begin")
    ok(tmp_path, "opacity", "logo", "0.5")
    ok(tmp_path, "transaction", "rollback")
    assert ok(tmp_path, "inspect", "logo", "--json")["opacity"] == 1
    ok(tmp_path, "export", "out.png")
    assert Image.open(tmp_path / "out.png").size == (120, 80)
    assert ok(tmp_path, "inspect", "logo")["resolved_bounds"] == [95, 5, 20, 20]
    r = cli(tmp_path, "move", "nonexistent", "0", "0", "--json")
    assert r.returncode == 1
    assert json.loads(r.stderr)["error"] == "layer_not_found"
    r = cli(tmp_path, "apply", "-", input=b'{"operations":[{"type":"move","target":"logo","x":1}]}')
    assert r.returncode == 0, r.stderr
    assert Project.load(tmp_path / "poster.vixl").layer("logo")["x"] == 1


def test_scripts_batch_and_dryrun(tmp_path):
    for n in ("a", "b"):
        Image.new("RGB", (10, 10), "red").save(tmp_path / f"{n}.png")
    script = tmp_path / "clean.vixlscript"
    script.write_text("grayscale\ncontrast +10\n")
    result = ok(tmp_path, "batch", "*.png", "--run", "clean.vixlscript", "--output", "processed")
    assert len(result) == 2
    assert (
        Image.open(tmp_path / "processed/a.png").getpixel((1, 1))[0]
        == Image.open(tmp_path / "processed/a.png").getpixel((1, 1))[1]
    )
    ok(tmp_path, "new", "10x10", "-o", "a.vixl")
    ok(tmp_path, "add", "a.png")
    before = (tmp_path / "a.vixl").read_bytes()
    ok(tmp_path, "run", "clean.vixlscript", "--dry-run")
    assert (tmp_path / "a.vixl").read_bytes() == before
    ok(tmp_path, "run", "clean.vixlscript")
    assert len(Project.load(tmp_path / "a.vixl").layer()["effects"]) == 2


@pytest.mark.parametrize(
    "command,expected",
    [
        ("resize portrait --width 800", {"type": "resize", "target": "portrait", "width": 800}),
        ("scale logo 80%", {"type": "scale", "target": "logo", "value": 0.8}),
        ("brightness +10", {"type": "brightness", "value": 10.0}),
        ("move logo 10 20", {"type": "move", "target": "logo", "x": 10.0, "y": 20.0, "relative": False}),
        ("filter gaussian-blur --radius 12", {"type": "effect", "name": "gaussian-blur", "amount": 12.0}),
    ],
)
def test_command_compilation(command, expected):
    assert compile_command(command) == expected


def test_binary_pipelines(tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "red").save(path)
    result = cli(tmp_path, "convert", "--grayscale", input=path.read_bytes())
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(b"\x89PNG")
    ok(tmp_path, "new", "4x4", "-o", "a.vixl")
    result = cli(tmp_path, "export", "-")
    assert result.stdout.startswith(b"\x89PNG")


def test_each_and_assert_exit(tmp_path):
    ok(tmp_path, "new", "10x10")
    ok(tmp_path, "solid", "--name", "card-a", "--width", "2", "--height", "2")
    ok(tmp_path, "solid", "--name", "card-b", "--width", "2", "--height", "2")
    ok(tmp_path, "each", "layer", "--name", "card-*", "--", "opacity", ".5")
    assert all(x["opacity"] == 0.5 for x in Project.load(tmp_path / "untitled.vixl").state["layers"])
    assert cli(tmp_path, "assert", "canvas.width", "==", "20").returncode == 1


def test_presets_and_variable_delete_via_cli(tmp_path):
    ok(tmp_path, "new", "20x20")
    ok(tmp_path, "solid", "--name", "base")
    ok(tmp_path, "contrast", "+12")
    ok(tmp_path, "preset", "save", "warm")
    ok(tmp_path, "effect", "remove", "base", "1")
    ok(tmp_path, "preset", "apply", "warm", "--set", "contrast=25")
    assert Project.load(tmp_path / "untitled.vixl").layer()["effects"][0]["amount"] == 25
    ok(tmp_path, "variable", "set", "unused", "yes")
    ok(tmp_path, "variable", "delete", "unused")
    assert Project.load(tmp_path / "untitled.vixl").state["variables"] == {}


def test_script_failure_does_not_save_earlier_operations(tmp_path):
    ok(tmp_path, "new", "20x20")
    ok(tmp_path, "solid", "--name", "base")
    (tmp_path / "bad.vixlscript").write_text("move 4 5\nopacity 250\n")
    before = (tmp_path / "untitled.vixl").read_bytes()
    assert cli(tmp_path, "run", "bad.vixlscript").returncode == 1
    assert (tmp_path / "untitled.vixl").read_bytes() == before
