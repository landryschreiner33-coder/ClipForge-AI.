"""Installer boundary regressions: bad archives, interrupted transfers and occupied ports."""
import hashlib
import importlib.util
from pathlib import Path
import socket
import zipfile

import pytest

pytest.importorskip("fcntl", reason="The macOS installer uses POSIX file locks")

spec = importlib.util.spec_from_file_location("mac_setup", Path(__file__).parents[1] / "macos/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../../escape", "a\\escape"])
def test_unsafe_package_paths_are_rejected(tmp_path, name):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        setup.extract_app(archive, tmp_path / "out")
    assert not (tmp_path / "escape").exists()


def test_symlink_package_is_rejected(tmp_path):
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as z:
        item = zipfile.ZipInfo("link")
        item.external_attr = 0o120777 << 16
        z.writestr(item, "../../outside")
    with pytest.raises(ValueError, match="Unsafe"):
        setup.extract_app(archive, tmp_path / "out")


def test_release_install_preserves_data_and_other_releases(tmp_path):
    bundle, base = tmp_path / "bundle", tmp_path / "profile"
    bundle.mkdir()
    (base / "data").mkdir(parents=True)
    (base / "data/knowledge.txt").write_text("my notes")
    archive = bundle / "app.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("clipfoundry/__main__.py", "pass")
    manifest = {"source_commit": "a" * 40, "app_sha256": setup.digest(archive)}
    first = setup.install_release(bundle, base, manifest)
    (first / ".setup-complete").write_text("done")
    assert setup.install_release(bundle, base, manifest) == first
    manifest["source_commit"] = "b" * 40
    second = setup.install_release(bundle, base, manifest)
    assert second != first and (first / ".setup-complete").read_text() == "done"
    assert (base / "data/knowledge.txt").read_text() == "my notes"
    manifest["app_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        setup.install_release(bundle, base, manifest)


def test_failed_download_cannot_replace_a_verified_file(tmp_path, monkeypatch):
    from io import BytesIO
    target = tmp_path / "video.gz"
    target.write_bytes(b"previous")
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *a, **k: BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="checksum"):
        setup.fetch("https://github.com/eugeneware/ffmpeg-static/releases/download/test/tool.gz",
                    hashlib.sha256(b"wanted").hexdigest(), target)
    assert target.read_bytes() == b"previous"
    assert not target.with_suffix(".partial").exists()


def test_another_listener_is_not_terminated():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="No process was stopped"):
            setup.check_port(listener.getsockname()[1])
        assert listener.fileno() >= 0
