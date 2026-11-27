"""The worker's side of Full Cloud: a ClipForge started with CLIPFOUNDRY_WORKER_KEY takes Make clips jobs from the
owner's desktop ClipForge (fullcloud/__init__.py).

Every request must carry ``Authorization: Bearer <key>``; without the key set (24 characters or more) these routes
do not exist (404). A job is an ordinary project in the worker's own data folder, run by the worker's own job thread
(jobs.py), so it shows progress, can be stopped and is picked up again when the worker restarts. The desktop's clip
choices come with the job and are applied just before it runs. Finished jobs wait for the desktop to fetch them and
are deleted when it says so, or KEEP_HOURS after they ended.

Nothing here publishes, schedules or reaches any account: a job's options never carry destinations.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .. import __version__, config, db

log = logging.getLogger(__name__)

KEY_ENV = "CLIPFOUNDRY_WORKER_KEY"
MIN_KEY = 24
KEEP_HOURS = 72
TIDY_EVERY_S = 3600
API = "/api/worker/v1"
MAX_UPLOAD_GB = float(os.environ.get("CLIPFOUNDRY_WORKER_MAX_GB", "20") or 20)
# What a worker does, in the order a job does it, and what each stage of the pipeline counts as.
STAGES = ("ingest", "transcribe", "analyze", "framing", "captions", "render")
PIPELINE_STAGE = {"queued": "", "download": "ingest", "probe": "ingest", "audio": "ingest", "transcribe": "transcribe",
                  "candidates": "analyze", "scoring": "analyze", "stories": "analyze", "render": "render",
                  "done": "render"}
# The desktop's clip choices a job carries (never accounts, keys, addresses, AI services or paths).
SETTING_KEYS = ("language", "clip_count", "min_duration", "max_duration", "target_duration", "min_score",
                "ai_max_candidates", "deep_analysis", "caption_style", "caption_position", "highlight_words",
                "tracking", "layout", "split_view", "split_game", "silence", "remove_fillers", "auto_zoom",
                "caption_emphasis", "hook_overlay", "hook_seconds", "normalize_audio", "clean_sound", "crf",
                "x264_preset", "max_fps", "auto_color", "look", "look_strength", "clean_picture",
                "sound_effects", "loop_ending")
OPTION_KEYS = ("clip_count", "min_duration", "max_duration", "target_duration", "caption_style", "tracking", "layout",
               "silence", "auto_zoom", "hook_overlay", "caption_position", "highlight_words", "remove_fillers",
               "caption_emphasis", "story_split")
CLIP_MODES = ("highlights", "full_stories")
SAFE_NAME = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
PROJECT_FILES = ("transcript.json", "loudness.json", "thumb.jpg")  # a job's own files the desktop takes back


def key() -> str:
    return os.environ.get(KEY_ENV, "").strip()


def enabled() -> bool:
    return len(key()) >= MIN_KEY


def _auth(request: Request) -> None:
    if not enabled():
        raise HTTPException(404, "Not Found")
    if not _key_ok(request.headers.get("authorization", "")):  # WorkerOnly checked it already; checked again here
        raise HTTPException(401, "This worker's key is not right.")


router = APIRouter(dependencies=[Depends(_auth)])


def _key_ok(header: str) -> bool:
    return header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip().encode(), key().encode())


def _body_limit() -> int:
    """The most a request may send: one video at the upload limit, its transcript and the job's choices."""
    return int(MAX_UPLOAD_GB * 1024 ** 3) + 64 * 1024 * 1024


class _TooBig(Exception):
    pass


class WorkerOnly:
    """A worker answers worker requests only: with the key set, every other address (the app's pages and its whole
    API, which have no sign-in on a desktop) is 404, so putting the worker on the internet exposes nothing else.

    The key and the size are checked here, before the app reads a byte of the body: without the key, or over the
    upload limit, nothing is written to the worker's disk (FastAPI stores an upload before its route runs)."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    async def _answer(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" and enabled():  # a worker has none: refused before it is accepted
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http" and enabled():
            path = scope.get("path") or ""
            if not (path.startswith(API + "/") or path == "/healthz"):
                await self._answer(send, 404, "Not Found")
                return
            if path != "/healthz":
                headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
                if not _key_ok(headers.get("authorization", "")):
                    await self._answer(send, 401, "This worker's key is not right.")
                    return
                limit = _body_limit()
                length = headers.get("content-length", "")
                if length.isdigit() and int(length) > limit:
                    await self._answer(send, 413, f"The video is over this worker's {MAX_UPLOAD_GB:g} GB limit.")
                    return
                seen = [0]

                async def counted():  # a body sent without its length stops at the limit too
                    message = await receive()
                    if message.get("type") == "http.request":
                        seen[0] += len(message.get("body") or b"")
                        if seen[0] > limit:
                            raise _TooBig()
                    return message

                try:
                    await self.app(scope, counted, send)
                except _TooBig:
                    await self._answer(send, 413, f"The video is over this worker's {MAX_UPLOAD_GB:g} GB limit.")
                return
        await self.app(scope, receive, send)


def apply_settings(project: dict) -> None:
    """Just before a job runs (jobs.py): the desktop's clip choices that came with it become the worker's."""
    snapshot = ((project.get("info") or {}).get("worker_job") or {}).get("settings") or {}
    clean = {k: v for k, v in snapshot.items() if k in SETTING_KEYS}
    if clean:
        db.save_settings(clean)


def job_started(project_id: str) -> None:
    """jobs.py, as a job starts here: the desktop's clip choices become the worker's, and the start is noted (the
    worker time the desktop counts runs from here)."""
    p = db.get_project(project_id) or {}
    info = dict(p.get("info") or {})
    job = dict(info.get("worker_job") or {})
    apply_settings(p)
    job.update(started_at=job.get("started_at") or time.time(), ended_at=0)
    db.update_project(project_id, info={**info, "worker_job": job})


def job_ended(project_id: str) -> None:
    p = db.get_project(project_id)
    if not p:
        return
    info = dict(p.get("info") or {})
    job = dict(info.get("worker_job") or {})
    job["ended_at"] = time.time()
    db.update_project(project_id, info={**info, "worker_job": job})


def _job(job_id: str) -> dict:
    p = db.get_project(job_id)
    if not p or not (p.get("info") or {}).get("worker_job"):
        raise HTTPException(404, "No such job on this worker")
    return p


def _pdir(p: dict) -> Path:
    return Path(p["source_path"]).parent


def _ran(p: dict) -> dict:
    """Which stages ran here, from what the job left behind (never from what it was asked to do)."""
    pdir, info = _pdir(p), p.get("info") or {}
    clips = db.list_clips(p["id"])
    made = [c for c in clips if c.get("output_path") and Path(c["output_path"]).is_file()]
    t = _read(pdir / "transcript.json")
    ran = {"ingest": bool(p.get("duration")) and Path(p["source_path"]).is_file(),
           "transcribe": bool(t), "analyze": p.get("status") == "ready" or bool(clips),
           "framing": any((c.get("render_info") or {}).get("framing_evidence") is not None for c in made),
           "captions": any((pdir / "clips" / c["id"] / "captions.ass").is_file() for c in made),
           "render": bool(made)}
    how = {"transcribe": (t or {}).get("source") or "", "ingest": "link" if p.get("source_url") else "upload",
           "analyze": info.get("scoring_source") or ""}
    return {"ran": ran, "how": {k: v for k, v in how.items() if v}}


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def view(p: dict) -> dict:
    job = (p.get("info") or {}).get("worker_job") or {}
    src = Path(p["source_path"]) if p.get("source_path") else None
    return {"id": p["id"], "status": p["status"], "stage": p.get("stage") or "",
            "step": PIPELINE_STAGE.get(p.get("stage") or "", ""), "progress": p.get("progress") or 0,
            "message": p.get("message") or "", "error": p.get("error") or "", "duration": p.get("duration") or 0,
            "created_at": p["created_at"], "updated_at": p["updated_at"],
            "started_at": job.get("started_at") or 0, "ended_at": job.get("ended_at") or 0,
            "source": {"name": p.get("source_filename") or "", "link": bool(p.get("source_url")),
                       "bytes": src.stat().st_size if src and src.is_file() else 0},
            "clips": len(db.list_clips(p["id"])), "now": time.time(), **_ran(p)}


def tidy(now: float | None = None) -> int:
    """Delete finished jobs nobody fetched within KEEP_HOURS (their videos stay on the worker's disk otherwise)."""
    now = now or time.time()
    gone = 0
    for p in db.list_projects():
        job = (p.get("info") or {}).get("worker_job")
        if job and p["status"] in ("ready", "error", "cancelled") and now - p["updated_at"] > KEEP_HOURS * 3600:
            _delete(p)
            gone += 1
    return gone


_tidying = threading.Event()


def start_tidying() -> None:
    """On a worker (api.lifespan): unfetched jobs are deleted KEEP_HOURS after they ended, checked at start and every
    hour, whether or not another job ever comes (the privacy page promises it)."""
    if not enabled() or _tidying.is_set():
        return
    _tidying.set()

    def loop() -> None:
        while True:
            try:
                tidy()
            except Exception:  # noqa: BLE001 - tried again next hour
                log.exception("Could not delete old worker jobs")
            time.sleep(TIDY_EVERY_S)

    threading.Thread(target=loop, name="worker-tidy", daemon=True).start()


def own_folder(pdir: Path) -> bool:
    """Whether `pdir` is one project's own folder directly inside ClipForge's projects folder. A folder is deleted
    only then: a project row naming a file anywhere else (a broken row, an old version's) never takes that file's
    folder with it."""
    try:
        return pdir.resolve().parent == config.projects_dir().resolve()
    except (OSError, RuntimeError, ValueError):
        return False


def _delete(p: dict) -> None:
    from ..jobs import worker

    worker.cancel(p["id"])
    if p.get("source_path"):
        if own_folder(_pdir(p)):
            shutil.rmtree(_pdir(p), ignore_errors=True)
        else:
            log.warning("Worker job %s names a file outside the projects folder; only its row was deleted", p["id"])
    db.delete_project(p["id"])


@router.get(API + "/info")
def info() -> dict:
    from ..jobs import worker
    from ..pipeline import cuda, llm, transcribe

    tidy()
    settings = db.get_settings()
    try:
        plan = transcribe.whisper_plan(settings, cuda.probe())
        whisper = {"model": plan["model"], "device": plan["device"], "gpu": plan["gpu"], "vram_mb": plan["vram_mb"]}
    except Exception:  # noqa: BLE001 - the rest still answers
        whisper = {}
    jobs = [p for p in db.list_projects() if (p.get("info") or {}).get("worker_job")]
    return {"worker": True, "version": __version__, "stages": list(STAGES), "whisper": whisper,
            "ai": llm.provider_label(settings), "max_upload_gb": MAX_UPLOAD_GB, "keep_hours": KEEP_HOURS,
            "busy": worker.current is not None, "queue": worker.q.qsize(),
            "jobs": {"waiting": sum(p["status"] in ("queued", "processing", "uploading") for p in jobs),
                     "finished": sum(p["status"] in ("ready", "error", "cancelled") for p in jobs)}}


@router.post(API + "/jobs")
async def submit(source: UploadFile | None = File(None), transcript: UploadFile | None = File(None),
                 link: str = Form(""), options: str = Form("{}"), settings: str = Form("{}"),
                 name: str = Form(""), clip_mode: str = Form("highlights"), guidance: str = Form("{}")) -> dict:
    from ..jobs import worker

    tidy()
    link = link.strip()
    if bool(link) == bool(source is not None and source.filename):
        raise HTTPException(400, "Send a video or a link.")
    if link and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "The link must start with http:// or https://.")
    try:
        opts, snap, guide = json.loads(options or "{}"), json.loads(settings or "{}"), json.loads(guidance or "{}")
    except ValueError as exc:
        raise HTTPException(400, "The options are not JSON.") from exc
    if not isinstance(opts, dict) or not isinstance(snap, dict) or not isinstance(guide, dict):
        raise HTTPException(400, "The options are not JSON objects.")
    if clip_mode not in CLIP_MODES:
        raise HTTPException(400, "Unknown clip mode.")
    split = opts.get("story_split")
    opts = config.validate_settings({k: v for k, v in opts.items() if k in OPTION_KEYS})
    if isinstance(split, str) and split.isidentifier():  # Story parts: how a long story is split (studio/clips_flow)
        opts["story_split"] = split[:40]
    snap = config.validate_settings({k: v for k, v in snap.items() if k in SETTING_KEYS})
    filename = Path(source.filename or "video.mp4").name if source is not None and source.filename else ""
    ext = Path(filename).suffix.lower() if filename else ".mp4"
    if filename and ext not in config.VIDEO_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'.")
    label = (name or Path(filename).stem or link)[:120] or "Video"
    p = db.create_project(label, source_filename=filename, source_url=link or None, options=opts,
                          status="uploading", info={"worker_job": {"settings": snap, "submitted_at": time.time()}},
                          clip_mode=clip_mode, guidance=guide)
    pdir = config.projects_dir() / p["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    dest = pdir / f"source{ext}"
    limit = int(MAX_UPLOAD_GB * 1024 ** 3)
    try:
        if source is not None and filename:
            got = 0
            with open(dest, "wb") as out:
                while chunk := await source.read(4 * 1024 * 1024):
                    got += len(chunk)
                    if got > limit:
                        raise HTTPException(413, f"The video is over this worker's {MAX_UPLOAD_GB:g} GB limit.")
                    out.write(chunk)
        if transcript is not None and transcript.filename:
            t_ext = Path(transcript.filename).suffix.lower()
            if t_ext not in config.TRANSCRIPT_EXTENSIONS:
                raise HTTPException(400, "A transcript must be .srt, .vtt or .json.")
            tpath = pdir / f"imported_transcript{t_ext}"
            tpath.write_bytes((await transcript.read())[:20 * 1024 * 1024])
            opts["transcript_file"] = str(tpath)
    except BaseException:
        shutil.rmtree(pdir, ignore_errors=True)
        db.delete_project(p["id"])
        raise
    db.update_project(p["id"], source_path=str(dest), options=opts)
    worker.submit_project(p["id"], url=link or None)
    return view(db.get_project(p["id"]))  # type: ignore[arg-type]


@router.get(API + "/jobs/{job_id}")
def job(job_id: str) -> dict:
    return view(_job(job_id))


@router.post(API + "/jobs/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    from ..jobs import worker

    p = _job(job_id)
    if p["status"] in ("queued", "processing", "uploading"):
        worker.cancel(job_id)
        if p["status"] != "processing":  # not started: it never will
            db.update_project(job_id, status="cancelled", message="Cancelled")
    return view(_job(job_id))


@router.delete(API + "/jobs/{job_id}")
def delete(job_id: str) -> dict:
    _delete(_job(job_id))
    return {"deleted": True}


CHILDREN = ("clip_blueprints", "quality_reports", "clip_analysis", "clip_scores", "metadata_candidates")


@router.get(API + "/jobs/{job_id}/result")
def result(job_id: str) -> dict:
    """Everything the desktop needs to rebuild the project: its facts, every clip with its rows and the files in
    each clip's folder (names and sizes), and the project's own files."""
    p = _job(job_id)
    if p["status"] != "ready":
        raise HTTPException(409, "The job has not finished.")
    pdir = _pdir(p)
    clips = []
    with db.connect() as conn:
        for c in db.list_clips(job_id):
            rows = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} WHERE clip_id = ?", (c["id"],))]
                    for t in CHILDREN}
            folder = pdir / "clips" / c["id"]
            files = sorted(({"name": f.name, "bytes": f.stat().st_size} for f in folder.iterdir()
                            if f.is_file() and set(f.name) <= SAFE_NAME and not f.name.startswith(".")),
                           key=lambda f: f["name"]) if folder.is_dir() else []
            raw = dict(conn.execute("SELECT * FROM clips WHERE id = ?", (c["id"],)).fetchone())
            clips.append({"row": raw, "children": rows, "files": files})
        candidates = [dict(r) for r in conn.execute("SELECT * FROM clip_candidates WHERE project_id = ?",
                                                    (job_id,))]
    own = [n for n in PROJECT_FILES if (pdir / n).is_file()]
    src = Path(p["source_path"])
    return {"job": view(p), "dir": str(pdir), "project": {k: p.get(k) for k in ("duration", "width", "height", "fps")},
            "info": {k: v for k, v in (p.get("info") or {}).items() if k != "worker_job"},
            "clips": clips, "candidates": candidates, "files": own,
            "source": {"name": src.name, "bytes": src.stat().st_size} if p.get("source_url") and src.is_file() else None}


@router.get(API + "/jobs/{job_id}/files/{name}")
def project_file(job_id: str, name: str) -> FileResponse:
    p = _job(job_id)
    pdir = _pdir(p)
    if name == "source":
        path = Path(p["source_path"])
    elif name in PROJECT_FILES:
        path = pdir / name
    else:
        raise HTTPException(404, "No such file")
    if not path.is_file():
        raise HTTPException(404, "No such file")
    return FileResponse(path)


@router.get(API + "/jobs/{job_id}/clips/{clip_id}/{name}")
def clip_file(job_id: str, clip_id: str, name: str) -> FileResponse:
    p = _job(job_id)
    c = db.get_clip(clip_id)
    if not c or c["project_id"] != job_id or not set(name) <= SAFE_NAME or name.startswith("."):
        raise HTTPException(404, "No such file")
    path = _pdir(p) / "clips" / clip_id / name
    if not path.is_file():
        raise HTTPException(404, "No such file")
    return FileResponse(path)
