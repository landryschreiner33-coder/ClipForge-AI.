"""Backup, restore and retention preview for the data folder.

`backup` takes a consistent copy of the database with SQLite's online backup API (safe while the app runs) and
copies every file of the data folder except regenerable caches and locks, then writes a manifest with each file's
SHA-256. `restore` verifies every hash before anything is copied and refuses to overwrite a data folder that
already holds a database. Secrets stay sealed: a cloud backup is useless without the separately stored key file,
and desktop DPAPI/Keychain secrets cannot be decrypted on another machine (reconnect the accounts there).

`retention_preview` lists exactly what a cleanup would delete. Originals (sources, uploaded assets, rendered
outputs) are never in that list: only regenerable caches and expired unfinished uploads.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from . import config

SKIP_DIRS = {"locks", "models", "tmp", "scratch"}
SKIP_FILES = {"clipfoundry.db", "clipfoundry.db-wal", "clipfoundry.db-shm"}
# regenerable, per project: decoded audio and its measurements are rebuilt from the original source on demand
CACHE_NAMES = {"audio.wav", "loudness.json"}
CACHE_DIRS = {"proxies", "previews", "_cache"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts[0] in SKIP_DIRS or (len(rel.parts) == 1 and rel.name in SKIP_FILES):
            continue
        if rel.parts[0] == "uploads" and path.suffix == ".part":
            continue  # unfinished uploads are resumable transfers, not data
        yield rel, path


def backup(dest: str | os.PathLike) -> dict:
    src = config.data_dir()
    out = Path(dest)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; choose a new folder for the backup")
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "created_at": time.time(), "app": config.APP_NAME, "files": {}}
    live = sqlite3.connect(str(config.db_path()))
    copy = sqlite3.connect(str(out / "clipfoundry.db"))
    with copy:
        live.backup(copy)
    live.close()
    copy.close()
    manifest["files"]["clipfoundry.db"] = _sha256(out / "clipfoundry.db")
    for rel, path in _files(src):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest["files"][str(rel)] = _sha256(target)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return {"files": len(manifest["files"]), "folder": str(out)}


def restore(src: str | os.PathLike, *, into: str | os.PathLike | None = None) -> dict:
    """Verify every file of a backup, then copy it into an empty data folder."""
    source = Path(src)
    manifest = json.loads((source / "manifest.json").read_text())
    bad = [rel for rel, digest in manifest["files"].items()
           if not (source / rel).is_file() or _sha256(source / rel) != digest]
    if bad:
        raise ValueError(f"{len(bad)} file(s) of the backup are missing or changed, e.g. {bad[0]}; nothing restored")
    target = Path(into) if into else config.data_dir()
    if (target / "clipfoundry.db").exists():
        raise FileExistsError(f"{target} already has a database; restore into an empty folder")
    for rel in manifest["files"]:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, dest)
    return {"files": len(manifest["files"]), "folder": str(target)}


def retention_preview(now: float | None = None) -> dict:
    """What a cleanup would delete, with sizes. Nothing is deleted here."""
    from .studio import uploads

    root = config.data_dir()
    items = []
    for path in (root / "projects").rglob("*") if (root / "projects").exists() else []:
        if path.is_file() and (path.name in CACHE_NAMES or any(p in CACHE_DIRS for p in path.parts)):
            items.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                          "why": "Regenerable cache: rebuilt from the original when needed."})
    now = now or time.time()
    for part in uploads.uploads_dir().glob("*.part"):
        if now - part.stat().st_mtime > uploads.STALE_SECONDS:
            items.append({"path": str(part.relative_to(root)), "bytes": part.stat().st_size,
                          "why": "Unfinished upload older than the resume window."})
    return {"items": items, "bytes": sum(i["bytes"] for i in items),
            "kept": "Original sources, uploaded files, finished renders, projects, Brain, accounts and history."}


def apply_retention(paths: list[str]) -> dict:
    """Delete exactly the previewed cache files the owner confirmed (each must still be in a fresh preview)."""
    allowed = {i["path"] for i in retention_preview()["items"]}
    root = config.data_dir()
    removed, freed = 0, 0
    for rel in paths:
        if rel not in allowed:
            continue
        p = root / rel
        freed += p.stat().st_size if p.exists() else 0
        p.unlink(missing_ok=True)
        removed += 1
    return {"removed": removed, "bytes": freed}
