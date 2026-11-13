"""Resumable uploads that become immutable, private assets, and files used where they are.

The browser sends a file in chunks at the exact offset the server reports, so an interrupted transfer resumes where
the last complete chunk ended (a partly received chunk is cut off again). Completion re-hashes the whole file,
compares it with the hash the browser computed, probes it, and stores it once per workspace and content hash. An
upload that has not completed is never shown as ready. Originals are kept until an explicit retention choice.

On the desktop a file can also be *linked* (`link_local`): it stays where it is, nothing is copied or uploaded, and
the asset's `path` is the file itself. Everything ClipForge makes for an asset (its 16 kHz sound, transcript,
preview proxy and thumbnail) lives in `work_dir(asset)`: the asset's own folder under the data folder, never next
to the owner's file, which is never changed or made read-only. A linked file's content id is a quick hash ("quick:"
plus a SHA-256 of its size and three 1 MB samples), so adding a 17 GB file twice is one asset without reading it.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
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
UNSUPPORTED = ("Unsupported file type. Use a video (MP4, MOV, MKV, WEBM, M4V), audio (MP3, M4A, WAV, FLAC) or image "
               "(PNG, JPG, WEBP) file.")
LINK_PREFIX = "quick:"            # the content id of a linked file starts with this; a full SHA-256 never does
QUICK_SAMPLE = 1 << 20            # each of the three samples a quick hash reads
DESKTOP_UPLOAD_CAP = 512 << 30    # the desktop copies a file into the data folder: free space is the limit...
DISK_RESERVE = 2 << 30            # ...less this reserve, so the computer keeps working

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()
_same_bytes = [threading.Lock() for _ in range(64)]  # one file is stored by one save at a time (see _store)


class UploadError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _lock(upload_id: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(upload_id, threading.Lock())


def _content_lock(workspace_id: str, digest: str) -> threading.Lock:
    """The lock of one file's content: two saves of the same bytes (the same file dropped twice, or added on two
    pages, finishing at the same moment) take turns, so the second finds what the first stored."""
    key = hashlib.sha256(f"{workspace_id}\0{digest}".encode()).digest()
    return _same_bytes[key[0] % len(_same_bytes)]


def _discard(folder: Path) -> None:
    """Remove a folder this module just made (a copy that was not kept). The stored copy in it is read-only, which
    Windows refuses to delete until it is made writable again."""
    def unlock(func, path, _exc):  # noqa: ANN001
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    try:
        shutil.rmtree(folder, onexc=unlock)  # type: ignore[call-arg]
    except TypeError:  # Python < 3.12
        shutil.rmtree(folder, onerror=unlock)
    except OSError:
        pass


REUSE_HOLD_S = 3600.0  # how long a file handed out again is left alone by a short's tidying (makers/shorts._drop)


def _mark(conn, asset_id: str, now: float, project_id: str = "", upload_id: str = "") -> None:
    """Note whom a stored file was just handed out to again, in the step that marks it (assets.reused_at): the
    project whose own work stored the same bytes once more (`project_id`: its build, a download or import for it,
    its music and sound effects), or the upload that got it (`upload_id`: an upload of the same bytes, or a file
    added from this computer). Deleting a project then keeps the file only for a hand-out to someone else
    (project_delete._handed_out); a note naming neither is someone unknown. Notes older than the hour a hand-out
    counts are removed here."""
    conn.execute("DELETE FROM asset_hand_outs WHERE at < ?", (now - REUSE_HOLD_S,))
    conn.execute("INSERT INTO asset_hand_outs (asset_id, at, project_id, upload_id) VALUES (?, ?, ?, ?)",
                 (asset_id, now, project_id or "", upload_id or ""))


def _reuse(workspace_id: str, digest: str, *, project_id: str = "", upload_id: str = "") -> dict | None:
    """The stored file with these bytes, marked as handed out again just now, or None. Whoever gets it records it a
    moment later (an upload, a link, a short's scene); until then nothing names it, so tidying would see an unused
    file: the mark keeps it (shorts._drop). The mark notes whom it went to (`_mark`), and the check, the mark and the
    note are one step in the database, so a file deleted in between is not handed out."""
    now = time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM assets WHERE workspace_id = ? AND sha256 = ?",
                           (workspace_id, digest)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE assets SET reused_at = ? WHERE id = ?", (now, row["id"]))
        _mark(conn, row["id"], now, project_id, upload_id)
    return db._decode("assets", row) | {"reused_at": now}  # noqa: SLF001


def _stored_already(workspace_id: str, digest: str, folder: Path, *, project_id: str = "",
                    upload_id: str = "") -> dict | None:
    """After a save was refused because the same bytes are stored already (another ClipForge program, such as
    Autopilot's, stored them between the check and the save): that asset, handed out again to whoever this save was
    for, with this save's own folder removed. Refused (409, try again) when that asset was deleted again in the
    meantime."""
    existing = _reuse(workspace_id, digest, project_id=project_id, upload_id=upload_id)
    _discard(folder)
    if existing is None:  # stored and deleted again in between: this save is refused, nothing is left behind
        raise UploadError("ClipForge was saving the same file at that moment. Try again.", 409)
    return existing


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


def is_linked(asset: dict) -> bool:
    """Whether the asset is the owner's own file used where it is (not a copy ClipForge keeps)."""
    return str(asset.get("sha256") or "").startswith(LINK_PREFIX)


def work_dir(asset: dict) -> Path:
    """Where ClipForge keeps what it makes for an asset: its 16 kHz `audio.wav`, `transcript.json`, `proxy.mp4` and
    `thumb.jpg`. A stored upload's own folder (the original is there too); for a linked file, the asset's own
    folder under the data folder, made when first needed. Never a folder that holds the owner's own file."""
    if is_linked(asset):
        d = assets_dir(asset.get("workspace_id") or "") / asset["id"]
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(asset["path"]).parent


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def max_upload_bytes() -> int:
    """The largest file an upload may announce: the cloud's configured limit; on the desktop the free space where
    ClipForge keeps its files less a 2 GB reserve (at most 512 GB), because an upload is a copy into that folder."""
    if cloud_settings.enabled():
        return cloud_settings.current().max_upload_bytes
    return min(DESKTOP_UPLOAD_CAP, max(0, shutil.disk_usage(config.data_dir()).free - DISK_RESERVE))


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
        raise UploadError(UNSUPPORTED)
    if not isinstance(size, int) or size <= 0:
        raise UploadError("The file is empty.")
    limit = max_upload_bytes()
    if size > limit:
        if cloud_settings.enabled():
            raise UploadError(f"The file is {size / 1e9:.1f} GB; the limit is {limit / 1e9:.1f} GB.", 413)
        free = shutil.disk_usage(config.data_dir()).free
        hint = "use Add from this computer, which uses the file where it is without copying it."
        if size > free - DISK_RESERVE:
            raise UploadError(f"The file is {size / 1e9:.1f} GB and only {free / 1e9:.1f} GB is free where ClipForge "
                              f"keeps its files. Free some space, or {hint}", 413, free=free)
        raise UploadError(f"The file is {size / 1e9:.1f} GB; at most {DESKTOP_UPLOAD_CAP >> 30} GB can be copied in. "
                          f"Instead, {hint}", 413, free=free)
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


def probe_audio(path: Path) -> dict:
    """Duration and format of an audio-only file (the video probe requires a picture)."""
    import json
    import subprocess

    from ..pipeline.ffmpeg_utils import ffprobe_bin

    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,sample_rate,channels", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    data = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    audio = [st for st in data.get("streams") or [] if st.get("codec_type") == "audio"]
    if not audio:
        raise FFmpegError("The file has no audio stream.")
    return {"duration": float((data.get("format") or {}).get("duration") or 0), "has_audio": True,
            "has_video": False, "sample_rate": int(audio[0].get("sample_rate") or 0),
            "channels": int(audio[0].get("channels") or 0)}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def quick_hash(path: Path, size: int | None = None) -> str:
    """The content id of a linked file: "quick:" plus a SHA-256 of its size (8 bytes) and three 1 MB samples (the
    start, the middle and the end; the whole file when it is 3 MB or less). It reads at most 3 MB whatever the
    size, so linking a 17 GB file takes a moment; a full hash of an upload can never start with "quick:"."""
    size = path.stat().st_size if size is None else size
    h = hashlib.sha256(size.to_bytes(8, "big"))
    with open(path, "rb") as f:
        if size <= 3 * QUICK_SAMPLE:
            h.update(f.read())
        else:
            for offset in (0, (size - QUICK_SAMPLE) // 2, size - QUICK_SAMPLE):
                f.seek(offset)
                h.update(f.read(QUICK_SAMPLE))
    return LINK_PREFIX + h.hexdigest()


def complete(upload_id: str) -> dict:
    """Verify, probe and store the finished file as an asset (the same bytes are stored once per workspace). The
    answer is the asset with `upload_id`, the upload the page sends when it makes or adds to a project (taken)."""
    with _lock(upload_id):
        row = get(upload_id)
        if row["status"] == "complete":
            return _again(row)
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
        try:
            stored = _store(row["workspace_id"], part, row["filename"], row["kind"], digest, row["size"],
                            upload_id=upload_id)
        except UploadError as exc:
            db.update("uploads", upload_id, status="failed",
                      error=str(exc) if exc.status == 409 else f"Not a readable {row['kind']} file.")
            raise
        db.update("uploads", upload_id, status="complete", asset_id=stored["id"])
        return {**asset_view(stored), "upload_id": upload_id}


def _again(row: dict) -> dict:
    """A finished upload finished again: the same file dropped on two pages while its first upload was still
    arriving resumes that one upload (start), so the second page finishes it too. That page gets an upload of its
    own (a copy of the row, which no project took yet), so a project made on the first page never takes the second
    page's, and deleting it keeps the file for the second page (project_delete._added_again). The file is marked
    as handed out again, like any upload of bytes ClipForge has (_reuse), in one step with the copy of the row, so a
    project being deleted either keeps the file or has deleted it already (409: upload it again)."""
    mine, now = "up-" + os.urandom(8).hex(), time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("UPDATE assets SET reused_at = ? WHERE id = ?", (now, row["asset_id"])).rowcount:
            raise UploadError("The file was deleted meanwhile. Upload it again.", 409)
        _mark(conn, row["asset_id"], now, upload_id=mine)
        conn.execute("INSERT INTO uploads (id, workspace_id, filename, kind, size, received, sha256, status, "
                     "asset_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'complete', ?, ?, ?)",
                     (mine, row["workspace_id"], row["filename"], row["kind"], row["size"], row["size"],
                      row["sha256"], row["asset_id"], now, now))
        asset = db._decode("assets", conn.execute(  # noqa: SLF001
            "SELECT * FROM assets WHERE id = ?", (row["asset_id"],)).fetchone())
    return {**asset_view(asset), "upload_id": mine}  # type: ignore[arg-type]


def _inspect(file: Path, kind: str, folder: Path, label: str = "This file") -> tuple[dict, str]:
    """Probe a media file and make its thumbnail in `folder`: (probe, thumbnail path or ""). A file ffmpeg cannot
    read is refused (422), except an image, which is kept without a probe."""
    info: dict = {}
    thumb = ""
    try:
        info = probe_audio(file) if kind == "audio" else probe(file)
    except (FFmpegError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        if kind != "image":
            raise UploadError(f"{label} is not a readable {kind} file ({str(exc)[:120]}).", 422) from exc
    if kind in ("video", "image"):
        try:
            t = min(float(info.get("duration") or 0) * 0.1, 5.0) if kind == "video" else 0.0
            thumbnail(file, t, folder / "thumb.jpg", 480)
            thumb = str(folder / "thumb.jpg") if (folder / "thumb.jpg").is_file() else ""  # ffmpeg may write none
        except Exception:  # noqa: BLE001 - a missing thumbnail never fails the upload
            thumb = ""
    return info, thumb


def _store(workspace_id: str, source: Path, filename: str, kind: str, digest: str, size: int, *,
           project_id: str = "", upload_id: str = "") -> dict:
    """Move a verified file into private asset storage (or reuse the asset with the same bytes) and probe it. Two
    saves of the same bytes take turns; when another ClipForge program saved them in the meantime, its asset is used
    and this copy is removed. A reused asset is handed out again to whoever this save is for (`_mark`): the project
    whose work stored it, or the upload it completes."""
    with _content_lock(workspace_id, digest):
        existing = _reuse(workspace_id, digest, project_id=project_id, upload_id=upload_id)
        if existing is not None:
            source.unlink(missing_ok=True)
            return existing
        asset_id = "as-" + os.urandom(8).hex()
        folder = assets_dir(workspace_id) / asset_id
        folder.mkdir(parents=True)
        dest = folder / ("original" + Path(filename).suffix.lower())
        shutil.move(str(source), dest)
        os.chmod(dest, 0o440)  # immutable original: edits only ever reference it
        try:
            info, thumb = _inspect(dest, kind, folder)
        except UploadError:
            _discard(folder)
            raise
        try:
            return db.insert("assets", {"id": asset_id, "workspace_id": workspace_id, "kind": kind,
                                        "filename": filename, "sha256": digest, "size": size, "path": str(dest),
                                        "thumb_path": thumb, "probe": info})
        except sqlite3.IntegrityError:
            return _stored_already(workspace_id, digest, folder, project_id=project_id, upload_id=upload_id)


def link_local(workspace_id: str, path: str) -> dict:
    """Use a file on this computer where it is (desktop only): no copy, no upload. Returns the asset row (the same
    one when the file was linked before; a linked file that moved is found again by its content) with the page's
    `upload_id` (_hand_out). Refused in the
    cloud, outside the folders ClipForge may read (local_files.roots), inside the data folder, and when the file
    is not a readable media file; the owner's file is never changed."""
    from . import local_files  # local_files lists media files with kind_of, so the import is made here

    if cloud_settings.enabled():
        raise UploadError("Files cannot be used where they are in the cloud; upload the file instead.", 403)
    if local_files.other_computer(str(path or ""), local_files.roots()):
        raise UploadError(local_files.ELSEWHERE, 403)  # before anything looks at it (local_files.other_computer)
    raw = Path(str(path or "").strip())
    if not str(raw) or not raw.is_absolute():
        raise UploadError("Give the full path of the file, starting at the root folder or the drive.", 400)
    try:
        file = raw.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UploadError(f"There is no file at {raw}.", 404) from exc
    if not file.is_file():
        raise UploadError(f"{raw} is not a file.", 400)
    if not os.access(file, os.R_OK):
        raise UploadError(f"ClipForge is not allowed to read {raw}.", 403)
    if not local_files.allowed(file):
        raise UploadError(f"{raw} is outside the folders ClipForge may read (your home folder and external drives).",
                          403)
    if _inside(file, config.data_dir().resolve()):
        raise UploadError("That file is inside ClipForge's own data folder; it is already here.", 400)
    name = file.name[:200]
    kind = kind_of(name)
    if kind is None:
        raise UploadError(UNSUPPORTED)
    size = file.stat().st_size
    if size <= 0:
        raise UploadError("The file is empty.")
    digest = quick_hash(file, size)
    mine = "up-" + os.urandom(8).hex()  # the page's record of this link (_hand_out), named in the hand-out's note
    with _content_lock(workspace_id, digest):
        existing = _reuse(workspace_id, digest, upload_id=mine)
        if existing is not None:
            if not Path(existing["path"]).is_file():  # the same file, found again after it was moved
                db.update("assets", existing["id"], path=str(file))
            return _hand_out(existing, name, again=True, upload_id=mine)
        asset_id = "as-" + os.urandom(8).hex()
        folder = assets_dir(workspace_id) / asset_id
        folder.mkdir(parents=True)
        try:
            info, thumb = _inspect(file, kind, folder, file.name)
        except UploadError:
            _discard(folder)
            raise
        try:
            stored, again = db.insert("assets", {"id": asset_id, "workspace_id": workspace_id, "kind": kind,
                                                 "filename": name, "sha256": digest, "size": size,
                                                 "path": str(file), "thumb_path": thumb, "probe": info}), False
        except sqlite3.IntegrityError:  # another ClipForge program linked it a moment ago
            stored, again = _stored_already(workspace_id, digest, folder, upload_id=mine), True
        return _hand_out(stored, name, again, upload_id=mine)


def _hand_out(asset: dict, name: str, again: bool, upload_id: str = "") -> dict:
    """Add from this computer gave the page this file: the asset, with `upload_id`, a finished upload of it that no
    project took yet, as an upload of the file leaves. The page sends it when it makes a project from the file or
    adds the file to one (taken), so deleting a project tells the page's own link from another page's, also one made
    before the project (project_delete._added_again; an example's delete, reference._drop_file). A file ClipForge
    had already (`again`) is marked as handed out again to that upload (_reuse, _mark) in one step with that, so a
    project being deleted either keeps the file or has deleted it already: then the page is told to add it again
    (409). `upload_id` is the id the upload gets (link_local names it in its own mark first)."""
    mine, now = upload_id or "up-" + os.urandom(8).hex(), time.time()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("UPDATE assets SET reused_at = CASE WHEN ? THEN ? ELSE reused_at END WHERE id = ?",
                            (int(again), now, asset["id"])).rowcount:
            raise UploadError("The file was deleted meanwhile. Add it again.", 409)
        if again:
            _mark(conn, asset["id"], now, upload_id=mine)
        conn.execute("INSERT INTO uploads (id, workspace_id, filename, kind, size, received, status, asset_id, "
                     "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'complete', ?, ?, ?)",
                     (mine, asset["workspace_id"], name, asset["kind"], asset["size"], asset["size"], asset["id"],
                      now, now))
        row = db._decode("assets", conn.execute(  # noqa: SLF001
            "SELECT * FROM assets WHERE id = ?", (asset["id"],)).fetchone())
    return {**row, "upload_id": mine}  # type: ignore[dict-item]


def taken(workspace_id: str, upload_ids, project_id: str, asset_ids) -> None:
    """A project took the owner's uploads the page sent with it (`upload_ids`: the uploads it was made from or added
    to it; `asset_ids`: the files it took). Each finished upload of one of those files that no project took yet
    becomes this project's; any other id is left alone, so a project only ever takes the uploads its page made, never
    another page's of the same file. ClipForge keeps one copy per file, so the owner's upload of a file it already had
    gives that copy; deleting a project keeps a file the owner uploaded again in the last day in case a page is about
    to use it (project_delete._added_again), and only an upload no project took counts. The same file dropped on two
    pages while its first upload is still arriving resumes that one upload: the first project to take it has it."""
    files = list(dict.fromkeys(str(a) for a in asset_ids or () if a))
    if not files:
        return
    with db.connect() as conn:
        for uid in dict.fromkeys(str(u) for u in upload_ids or () if u):
            conn.execute(
                f"UPDATE uploads SET taken = ? WHERE id = ? AND workspace_id = ? AND status = 'complete' AND "
                f"taken = '' AND asset_id IN ({', '.join('?' * len(files))})",
                (project_id, uid, workspace_id, *files))


def store_file(workspace_id: str, path: Path, filename: str, *, project_id: str = "") -> dict:
    """A file ClipForge obtained itself (a supplied link's download, an imported library item, what a short's build
    made) becomes a private asset exactly like an upload: hashed, probed, stored once per workspace and content hash.
    `path` is moved. `project_id`: the project whose work this is, when the bytes are stored already (that copy is
    then handed out again to that project: deleting the project lets it go, project_delete._handed_out)."""
    name = Path(filename or path.name).name[:200]
    kind = kind_of(name)
    if kind is None:
        raise UploadError("Unsupported file type.")
    size = path.stat().st_size
    if size <= 0:
        raise UploadError("The file is empty.")
    limit = storage_limit_bytes()
    if limit is not None and storage_used(workspace_id) + size > limit:
        raise UploadError("Storage is full. Nothing was deleted. Free space in Settings → Storage, then try again.",
                          507)
    return _store(workspace_id, path, name, kind, _sha256(path), size, project_id=project_id)


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
            "has_thumbnail": bool(a.get("thumb_path")), "linked": is_linked(a),
            "proxy": bool(a.get("proxy_path")) and Path(a["proxy_path"]).is_file(), "created_at": a.get("created_at")}


def asset(asset_id: str, workspace_id: str) -> dict:
    a = db.fetch("assets", asset_id)
    if not a or a["workspace_id"] != workspace_id:
        raise UploadError("Asset not found.", 404)
    return a
