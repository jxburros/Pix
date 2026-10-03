"""Release selection, integrity, side-by-side activation and failure recovery."""

from copy import deepcopy
import hashlib
import io
from pathlib import Path
import subprocess
import zipfile

import pytest

from pix import updater as u
from pix.cli import dispatch
from pix.errors import PixError


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / "Pix with spaces"
    (root / "versions" / "0.7.0").mkdir(parents=True)
    (root / "versions" / "0.7.0" / "pix-engine.exe").write_bytes(b"baseline")
    u.atomic_json(
        root / "install.json",
        {"protocol": 1, "current": "0.7.0", "previous": None, "pending": None, "auto": True, "last_check": 0},
    )
    monkeypatch.setenv("PIX_MANAGED_ROOT", str(root))
    return root


def bundle_bytes(members=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, value in (
            members or {"pix-engine.exe": b"new runtime", "_internal/font.ttf": b"font"}
        ).items():
            archive.writestr(name, value)
    return stream.getvalue()


def release_fixture(monkeypatch, payload=None, release="0.8.0"):
    data = payload if payload is not None else bundle_bytes()
    info = {
        "version": release,
        "url": "fixture",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "release_url": f"https://github.com/jxburros/Pix/releases/tag/v{release}",
    }
    monkeypatch.setattr(u, "latest", lambda: deepcopy(info))

    def download(url, destination, limit=u.MAX_DOWNLOAD):
        Path(destination).write_bytes(data)
        return hashlib.sha256(data).hexdigest(), len(data)

    monkeypatch.setattr(u, "download", download)
    return info


def test_stage_is_atomic_then_activate_and_rollback(install, monkeypatch):
    release_fixture(monkeypatch)
    probes = []
    monkeypatch.setattr(u, "probe", lambda root, release, folder=None: probes.append((release, folder)))
    assert u.update(install)["status"] == "ready"
    state = u.read_state(install)
    assert state["current"] == "0.7.0" and state["pending"] == "0.8.0"
    assert (install / "versions/0.7.0/pix-engine.exe").read_bytes() == b"baseline"
    exe, due = u.prepare_launch(install)
    assert exe == install / "versions/0.8.0/pix-engine.exe" and due
    assert u.read_state(install)["previous"] == "0.7.0"
    assert u.rollback(install)["current"] == "0.7.0"
    assert not u.status(install)["automatic"]
    assert probes[0][1] is not None


def test_check_only_and_no_downgrades(install, monkeypatch):
    release_fixture(monkeypatch)
    before = u.read_state(install)
    assert u.update(install, check_only=True)["status"] == "available"
    assert u.read_state(install) == before
    assert list((install / "versions").iterdir()) == [install / "versions/0.7.0"]
    release_fixture(monkeypatch, release="0.6.9")
    assert u.update(install)["status"] == "up-to-date"


def test_bad_checksum_and_interrupted_download_keep_working_version(install, monkeypatch):
    info = release_fixture(monkeypatch)
    info["sha256"] = "0" * 64
    monkeypatch.setattr(u, "latest", lambda: info)
    with pytest.raises(u.UpdateError, match="checksum"):
        u.update(install)
    assert u.read_state(install)["current"] == "0.7.0"
    assert not (install / "versions/0.8.0").exists()

    def broken(*args):
        raise u.UpdateError("interrupted")

    monkeypatch.setattr(u, "download", broken)
    with pytest.raises(u.UpdateError, match="interrupted"):
        u.update(install)
    assert not u.read_state(install)["pending"]


def test_failed_pending_health_check_and_daily_check_cadence(install, monkeypatch):
    state = u.read_state(install)
    state["pending"] = "0.8.0"
    u.atomic_json(install / "install.json", state)

    def broken(*args, **kwargs):
        raise u.UpdateError("bad runtime")

    monkeypatch.setattr(u, "probe", broken)
    exe, due = u.prepare_launch(install)
    assert exe == install / "versions/0.7.0/pix-engine.exe" and due
    state = u.read_state(install)
    assert state["pending"] is None and state["rejected"] == "0.8.0"
    assert state["last_error"] == "bad runtime"
    assert u.prepare_launch(install)[1] is False


def test_background_failure_is_silent(install, monkeypatch, capsys):
    monkeypatch.setattr(u, "latest", lambda: (_ for _ in ()).throw(u.UpdateError("offline")))
    u.background(install)
    assert capsys.readouterr() == ("", "")
    assert u.status(install)["last_error"] == "offline"
    assert u.prepare_launch(install)[0].is_file()


def test_disabled_and_no_update_launches_do_not_activate(install, monkeypatch):
    state = u.read_state(install)
    state["pending"] = "0.8.0"
    u.atomic_json(install / "install.json", state)
    monkeypatch.setattr(u, "probe", lambda *args, **kwargs: pytest.fail("must not probe"))
    exe, due = u.prepare_launch(install, allow_updates=False)
    assert "0.7.0" in str(exe) and not due
    assert u.read_state(install)["pending"] == "0.8.0"
    u.preference(install, False)
    assert u.read_state(install)["pending"] is None
    monkeypatch.setattr(u, "latest", lambda: pytest.fail("must not request network"))
    assert u.update(install, automatic=True)["status"] == "disabled"
    assert u.prepare_launch(install)[1] is False


def test_disable_during_download_prevents_pending_switch(install, monkeypatch):
    release_fixture(monkeypatch)

    def probe(root, release, folder=None):
        u.preference(root, False)

    monkeypatch.setattr(u, "probe", probe)
    assert u.update(install, automatic=True)["status"] == "disabled"
    assert u.read_state(install)["pending"] is None


def test_rejected_version_is_not_automatically_retried(install, monkeypatch):
    release_fixture(monkeypatch)
    state = u.read_state(install)
    state["rejected"] = "0.8.0"
    u.atomic_json(install / "install.json", state)
    assert u.update(install, automatic=True)["status"] == "previously-rejected"


@pytest.mark.parametrize(
    "member",
    [
        "../escape",
        "/absolute",
        "C:/escape",
        "dir\\escape",
        "file.exe:stream",
        "dir/CON.txt",
        "dir/file.",
        "dir/file ",
        "a/../../escape",
    ],
)
def test_malicious_archive_paths_are_rejected(tmp_path, member):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(bundle_bytes({member: b"bad"}))
    with pytest.raises(u.UpdateError):
        u.extract_bundle(archive, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_zip_links_and_case_collisions(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(bundle_bytes({"File": b"a", "file": b"b"}))
    with pytest.raises(u.UpdateError, match="Duplicate"):
        u.extract_bundle(archive, tmp_path / "out")
    with zipfile.ZipFile(archive, "w") as z:
        entry = zipfile.ZipInfo("link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        z.writestr(entry, "/outside")
    with pytest.raises(u.UpdateError, match="link"):
        u.extract_bundle(archive, tmp_path / "out")


def test_latest_only_trusts_published_stable_correct_platform(monkeypatch):
    release = {
        "tag_name": "v0.8.0",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": "pix-update.json"}, {"name": "pix-0.8.0-windows-x64.zip"}],
    }
    manifest = {
        "protocol": 1,
        "version": "0.8.0",
        "platform": "windows-x64",
        "asset": "pix-0.8.0-windows-x64.zip",
        "sha256": "a" * 64,
        "size": 123,
    }

    def read(url):
        return deepcopy(release if url == u.API else manifest)

    monkeypatch.setattr(u, "json_download", read)
    assert (
        u.latest()["url"]
        == "https://github.com/jxburros/Pix/releases/download/v0.8.0/pix-0.8.0-windows-x64.zip"
    )
    release["prerelease"] = True
    with pytest.raises(u.UpdateError):
        u.latest()
    release["prerelease"] = False
    manifest["protocol"] = 2
    with pytest.raises(u.UpdateError, match="newer installer"):
        u.latest()
    manifest["protocol"] = 1
    manifest["asset"] = "https://evil.test/run.exe"
    with pytest.raises(u.UpdateError):
        u.latest()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/file",
        "https://evil.test/file",
        "https://github.com@evil.test/file",
        "https://github.com:8443/file",
        "file:///etc/passwd",
    ],
)
def test_download_and_redirect_host_allowlist(url):
    with pytest.raises(u.UpdateError):
        u.check_url(url)


def test_cli_management_without_project(install, monkeypatch):
    monkeypatch.chdir(install)
    value, _ = dispatch(["updates", "off", "--json"])
    assert value == {"automatic": False}
    value, _ = dispatch(["updates", "status"])
    assert value["current"] == "0.7.0"
    release_fixture(monkeypatch)
    value, _ = dispatch(["update", "--check"])
    assert value["status"] == "available"
    monkeypatch.delenv("PIX_MANAGED_ROOT")
    with pytest.raises(PixError, match="Windows installer"):
        dispatch(["update"])


def test_probe_checks_real_version_and_health_result(install, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, b'{"ok":true,"version":"0.7.0"}', b""),
    )
    u.probe(install, "0.7.0")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, b'{"ok":true,"version":"9.0.0"}', b""),
    )
    with pytest.raises(u.UpdateError):
        u.probe(install, "0.7.0")


def test_initialize_rejects_downgrade_preserves_opt_out(install, monkeypatch):
    monkeypatch.setattr(u, "probe", lambda *a, **kw: None)
    u.preference(install, False)
    u.initialize(install, "0.8.0")
    state = u.read_state(install)
    assert state["previous"] == "0.7.0" and state["auto"] is False
    with pytest.raises(u.UpdateError, match="downgrades"):
        u.initialize(install, "0.6.0")
    assert u.read_state(install) == state


def test_process_lock_excludes_other_processes(install):
    script = "from pathlib import Path; from pix.updater import locked; import sys\nwith locked(Path(sys.argv[1]), timeout=.1): pass"
    import sys

    with u.locked(install):
        result = subprocess.run([sys.executable, "-c", script, str(install)], capture_output=True, timeout=5)
    assert result.returncode != 0 and b"Another Pix update" in result.stderr


def test_launcher_rollback_does_not_depend_on_running_engine(install, monkeypatch, capsys):
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "distribution" / "launcher.py"
    monkeypatch.setitem(sys.modules, "updater", u)
    spec = importlib.util.spec_from_file_location("pix_launcher_test", path)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    state = u.read_state(install)
    state["previous"] = "0.6.0"
    u.atomic_json(install / "install.json", state)
    monkeypatch.setattr(sys, "executable", str(install / "bin/pix.exe"))
    monkeypatch.setattr(sys, "argv", ["pix", "update", "--rollback", "--json"])
    monkeypatch.setattr(u, "probe", lambda *a, **kw: None)
    monkeypatch.setattr(
        subprocess, "call", lambda *a, **kw: pytest.fail("broken active CLI must not execute")
    )
    assert launcher.main() == 0
    assert json.loads(capsys.readouterr().out)["current"] == "0.6.0"
    assert not u.read_state(install)["auto"]
