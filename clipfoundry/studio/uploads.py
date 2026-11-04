"""Resumable uploads that become immutable, private assets.

The browser sends a file in chunks at the exact offset the server reports, so an interrupted transfer resumes where
the last complete chunk ended (a partly received chunk is cut off again). Completion re-hashes the whole file,
compares it with the hash the browser computed, probes it, and stores it once per workspace and content hash. An
upload that has not completed is never shown as ready. Originals are kept until an explicit retention choice.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

from .. import config, db
from ..cloud import settings as cloud_settings
from ..pipeline.ffmpeg_utils import FFmpegError, probe, thumbnail

CHUNK_MAX = 16 * 1024 * 1024
STALE_SECONDS = 3 * 86400  # unfinished uploads are kept this long, so a transfer can resume the next day
KINDS = {"video": config.VIDEO_EXTENSIONS, "audio": {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"},
         "image": {".png", ".jpg", ".jpeg", ".webp"}}

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class UploadError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _lock(upload_id: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(upload_id, threading.Lock())


def uploads_dir() -> Path:
    d = config.data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir(workspace_id: str) -> Path:
    safe = "".join(c for c in workspace_id if c.isalnum() or c in "-_") or "local"
    d = config.data_dir() / "assets" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _part(upload_id: str) -> Path:
    return uploads_dir() / f"{upload_id}.part"


def kind_of(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), None)


def max_upload_bytes() -> int:
    return cloud_settings.current().max_upload_bytes if cloud_settings.enabled() else 8 * (1 << 30)


def storage_limit_bytes() -> int | None:
    return cloud_settings.current().storage_limit_bytes if cloud_settings.enabled() else None


def storage_used(workspace_id: str) -> int:
    assets = db.scalar("SELECT COALESCE(SUM(size), 0) FROM assets WHERE workspace_id = ?", (workspace_id,)) or 0
    pending = db.scalar("SELECT COALESCE(SUM(size), 0) FROM uploads WHERE workspace_id = ? AND status = 'receiving'",
                        (workspace_id,)) or 0
    return int(assets) + int(pending)


def clean_stale(now: float | None = None) -> int:
    """Forget unfinished uploads older than the retention; their partial bytes are deleted, nothing else."""
    now = now or time.time()
    n = 0
    for row in db.select("uploads", "status = 'receiving' AND updated_at < ?", (now - STALE_SECONDS,)):
        _part(row["id"]).unlink(missing_ok=True)
        db.update("uploads", row["id"], status="failed", error="This upload was not finished in time and expired.")
        n += 1
    return n


def view(row: dict) -> dict:
    return {k: row[k] for k in ("id", "filename", "kind", "size", "received", "status", "error", "asset_id")} | {
        "chunk_size": CHUNK_MAX // 2}


def start(workspace_id: str, filename: str, size: int, sha256: str = "", fingerprint: str = "") -> dict:
    name = Path(filename or "").name[:200]
    kind = kind_of(name)
    if not name or kind is None:
        raise UploadError("Unsupported file type. Use a video (MP4, MOV, MKV, WEBM, M4V), audio (MP3, M4A, WAV, FLAC) "
                          "or image (PNG, JPG, WEBP) file.")
    if not isinstance(size, int) or size <= 0:
        raise UploadError("The file is empty.")
    if size > max_upload_bytes():
        raise UploadError(f"The file is {size / 1e9:.1f} GB; the limit is {max_upload_bytes() / 1e9:.1f} GB.", 413)
    sha256 = (sha256 or "").lower()
    if sha256 and (len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256)):
        raise UploadError("The file hash is not a SHA-256 hex string.")
    clean_stale()
    fingerprint = fingerprint[:300]
    if fingerprint:  # the same file again: resume its unfinished upload instead of making another
        same = db.select("uploads", "workspace_id = ? AND fingerprint = ? AND size = ? AND status = 'receiving'",
                         (workspace_id, fingerprint, size), "updated_at DESC", 1)
        if same:
            return view(same[0])
    limit = storage_limit_bytes()
    if limit is not None and storage_used(workspace_id) + size > limit:
        used = storage_used(workspace_id)
        raise UploadError(f"Storage is full ({used / 1e9:.1f} of {limit / 1e9:.1f} GB used). Nothing was deleted. "
                          "Free space in Settings → Storage, then try again.", 507, used=used, limit=limit)
    row = db.insert("uploads", {"id": "up-" + os.urandom(8).hex(), "workspace_id": workspace_id, "filename": name,
                                "kind": kind, "size": size, "sha256": sha256, "fingerprint": fingerprint})
    _part(row["id"]).touch()
    return view(row)


def get(upload_id: str) -> dict:
    row = db.fetch("uploads", upload_id)
    if not row:
        raise UploadError("Upload not found.", 404)
    return row


def put_chunk(upload_id: str, offset: int, data: bytes) -> dict:
    """Append one chunk at `offset`. A chunk for another offset is refused with the received count, so the
    browser continues from what the server really has. A failed write is cut back to the last whole chunk."""
    with _lock(upload_id):
        row = get(upload_id)
        if row["status"] != "receiving":
            raise UploadError("This upload is not accepting data any more.", 409, received=row["received"])
        if offset != row["received"]:
            raise UploadError("The upload continues at another position.", 409, received=row["received"])
        if not data or len(data) > CHUNK_MAX:
            raise UploadError(f"Send chunks of 1 byte to {CHUNK_MAX >> 20} MB.", 413, received=row["received"])
        if row["received"] + len(data) > row["size"]:
            raise UploadError("More data than the announced file size.", 400, received=row["received"])
        part = _part(upload_id)
        try:
            with open(part, "r+b" if part.exists() else "wb") as f:
                f.truncate(row["received"])  # drop anything a broken earlier chunk left behind
                f.seek(row["received"])
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            with open(part, "r+b") as f:
                f.truncate(row["received"])
            raise UploadError("The server could not store this part (disk full?). Resume upload.", 507,
                              received=row["received"]) from exc
        db.update("uploads", upload_id, received=row["received"] + len(data))
        return view(get(upload_id))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def complete(upload_id: str) -> dict:
    """Verify, probe and store the finished file as an asset (the same bytes are stored once per workspace)."""
    with _lock(upload_id):
        row = get(upload_id)
        if row["status"] == "complete":
            return asset_view(db.fetch("assets", row["asset_id"]))  # type: ignore[arg-type]
        if row["received"] != row["size"]:
            raise UploadError(f"Only {row['received']:,} of {row['size']:,} bytes arrived. Resume upload.", 409,
                              received=row["received"])
        part = _part(upload_id)
        if not part.exists() or part.stat().st_size != row["size"]:
            db.update("uploads", upload_id, status="failed", error="The received data is missing on the server.")
            raise UploadError("The received data is missing on the server. Upload the file again.", 409)
        digest = _sha256(part)
        if row["sha256"] and digest != row["sha256"]:
            part.unlink(missing_ok=True)
            db.update("uploads", upload_id, status="failed", error="The file changed or was damaged in transfer.")
            raise UploadError("The file arrived damaged (its fingerprint does not match). Upload it again.", 422)
        existing = db.select("assets", "workspace_id = ? AND sha256 = ?", (row["workspace_id"], digest))
        if existing:
            part.unlink(missing_ok=True)
            db.update("uploads", upload_id, status="complete", asset_id=existing[0]["id"])
            return asset_view(existing[0])
        asset_id = "as-" + os.urandom(8).hex()
        folder = assets_dir(row["workspace_id"]) / asset_id
        folder.mkdir(parents=True)
        dest = folder / ("original" + Path(row["filename"]).suffix.lower())
        shutil.move(str(part), dest)
        os.chmod(dest, 0o440)  # immutable original: edits only ever reference it
        info: dict = {}
        thumb = ""
        try:
            info = probe(dest)
        except (FFmpegError, OSError, ValueError) as exc:
            if row["kind"] != "image":
                shutil.rmtree(folder, ignore_errors=True)
                db.update("uploads", upload_id, status="failed", error=f"Not a readable {row['kind']} file.")
                raise UploadError(f"This file is not a readable {row['kind']} file ({str(exc)[:120]}).", 422) from exc
        if row["kind"] in ("video", "image"):
            try:
                t = min(float(info.get("duration") or 0) * 0.1, 5.0) if row["kind"] == "video" else 0.0
                thumbnail(dest, t, folder / "thumb.jpg", 480)
                thumb = str(folder / "thumb.jpg")
            except Exception:  # noqa: BLE001 - a missing thumbnail never fails the upload
                thumb = ""
        asset = db.insert("assets", {"id": asset_id, "workspace_id": row["workspace_id"], "kind": row["kind"],
                                     "filename": row["filename"], "sha256": digest, "size": row["size"],
                                     "path": str(dest), "thumb_path": thumb, "probe": info})
        db.update("uploads", upload_id, status="complete", asset_id=asset_id)
        return asset_view(asset)


def cancel(upload_id: str) -> None:
    with _lock(upload_id):
        row = get(upload_id)
        if row["status"] == "receiving":
            _part(upload_id).unlink(missing_ok=True)
            db.update("uploads", upload_id, status="failed", error="Cancelled.")


def asset_view(a: dict) -> dict:
    p = a.get("probe") or {}
    return {"id": a["id"], "kind": a["kind"], "filename": a["filename"], "sha256": a["sha256"], "size": a["size"],
            "duration": p.get("duration"), "width": p.get("width"), "height": p.get("height"), "fps": p.get("fps"),
            "has_audio": p.get("has_audio"), "has_video": p.get("has_video"),
            "has_thumbnail": bool(a.get("thumb_path")), "created_at": a.get("created_at")}


def asset(asset_id: str, workspace_id: str) -> dict:
    a = db.fetch("assets", asset_id)
    if not a or a["workspace_id"] != workspace_id:
        raise UploadError("Asset not found.", 404)
    return a
