"""Backup, restore and retention preview: hashes verified, nothing overwritten, originals never listed."""
from __future__ import annotations

import json

import pytest


def test_backup_restores_byte_for_byte_and_refuses_damage(monkeypatch, tmp_path):
    from clipfoundry import backup, config, db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    p = db.create_project("kept", status="ready")
    src = config.projects_dir() / p["id"]
    src.mkdir(parents=True)
    (src / "source.mp4").write_bytes(b"original-bytes" * 100)
    (src / "audio.wav").write_bytes(b"cache" * 100)
    out = backup.backup(tmp_path / "bk")
    manifest = json.loads((tmp_path / "bk" / "manifest.json").read_text())
    assert out["files"] == len(manifest["files"]) and f"projects/{p['id']}/source.mp4" in manifest["files"]
    with pytest.raises(FileExistsError):
        backup.restore(tmp_path / "bk", into=tmp_path / "data")  # never over an existing database
    restored = tmp_path / "restored"
    backup.restore(tmp_path / "bk", into=restored)
    assert (restored / "projects" / p["id"] / "source.mp4").read_bytes() == b"original-bytes" * 100
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(restored))
    assert db.get_project(p["id"])["name"] == "kept"
    (tmp_path / "bk" / "projects" / p["id"] / "source.mp4").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="missing or changed"):
        backup.restore(tmp_path / "bk", into=tmp_path / "other")
    assert not (tmp_path / "other" / "clipfoundry.db").exists()


def test_retention_lists_only_regenerable_caches(monkeypatch, tmp_path):
    from clipfoundry import backup, config, db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    d = config.projects_dir() / "p1"
    (d / "clips").mkdir(parents=True)
    for name in ("source.mp4", "transcript.json", "clips/c1.mp4", "audio.wav", "loudness.json"):
        (d / name).write_bytes(b"x" * 10)
    preview = backup.retention_preview()
    listed = {i["path"] for i in preview["items"]}
    assert listed == {"projects/p1/audio.wav", "projects/p1/loudness.json"}
    assert backup.apply_retention(["projects/p1/source.mp4", *listed])["removed"] == 2
    assert (d / "source.mp4").exists() and (d / "clips" / "c1.mp4").exists() and not (d / "audio.wav").exists()
