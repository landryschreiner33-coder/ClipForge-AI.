"""A Make clips project run on the owner's ClipForge worker (Full Cloud; fullcloud/__init__.py).

jobs.py runs this instead of the pipeline for a project made while Settings → Processing was on Full Cloud:

1. **Upload**: the video goes to the worker (or the link does, and the worker downloads it), with the project's clip
   choices and the clip choices of Settings. Before that, the estimate and this month's limit are checked.
2. **Follow**: the worker's stage, progress and messages show on the project (a log keeps each step). Stop stops the
   job there too. When the worker does not answer, ClipForge keeps trying for LOST_LIMIT_S (the work goes on there).
3. **Bring back**: the transcript, the clips with all their rows, and each clip's folder come back into the project
   (a link's video comes back too, so a clip can be edited and rendered again here); then the job is deleted on the
   worker. The project then works like any other.

Where it got to is kept in the project's info ("cloud"), so after ClipForge restarts (or the computer was off) the
project picks up the same job on the worker instead of sending the video again: the worker keeps finished jobs for
worker_api.KEEP_HOURS.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path

from .. import db
from ..pipeline.common import Cancelled, JobContext
from . import client, usage
from .worker_api import CHILDREN, OPTION_KEYS, PROJECT_FILES, SAFE_NAME, SETTING_KEYS

log = logging.getLogger(__name__)

POLL_S = 1.5
ID_RE = re.compile(r"^[0-9a-f]{12}$")  # db.new_id: the worker's job and clip ids
LOST_LIMIT_S = 30 * 60
LOG_MAX = 150
UPLOAD_SHARE, FOLLOW_SHARE = 0.15, 0.75   # of the project's progress bar; bringing back is the rest
STEP_WORDS = {"ingest": "Getting the video", "transcribe": "Transcribing", "analyze": "Finding the best moments",
              "framing": "Framing", "captions": "Captions", "render": "Rendering the clips"}
UNSUPPORTED = (
    "Publishing, scheduling and your accounts stay on this computer: finished clips are posted from here.",
    "Autopilot and live streams run on this computer.",
    "Animated shorts, Text Stories, Make a YouTube video and FilmCraft run on this computer (their pictures and "
    "video can use the cloud computer: Hybrid).",
    "Editing a clip and rendering it again run on this computer, from the video (a link's video comes back with the "
    "clips).",
    "The worker picks clips with its own transcription model and its own AI setup. This computer's Brain notes, "
    "ClipForge AI keys and accounts never go to it: only the style choices made for this project (captions, layout, "
    "framing), without the names of the styles, skills or notes they came from.",
)


class RemoteError(Exception):
    pass


def mode_for_new_project(settings: dict | None = None) -> str:
    """"full_cloud" when new Make clips projects go to the worker (Full Cloud on and a worker set up), else ""."""
    s = settings if settings is not None else db.get_settings()
    return "full_cloud" if s.get("processing_mode") == "full_cloud" and client.configured(s) else ""


def decide(project_id: str, *, again: bool = False) -> str:
    """Where a project's clip-making runs, kept in its info ("processing"): decided when it is first sent to the job
    thread, and again when the owner presses Retry or Process again (`again`), except while a job is on the worker
    (that one is followed to its end). Autopilot, live and the worker's own jobs always run where they are."""
    p = db.get_project(project_id)
    if not p:
        return ""
    info = dict(p.get("info") or {})
    if info.get("worker_job") or (p.get("origin") or "manual") in ("autopilot", "live"):
        return ""
    if "processing" in info and not again:
        return info["processing"]
    if (info.get("cloud") or {}).get("phase") in ("running", "fetching") and info.get("processing") == "full_cloud":
        return "full_cloud"
    info["processing"] = mode_for_new_project()
    db.update_project(project_id, info=info)
    return info["processing"]


# ------------------------------------------------------------------ the project's record of the job
def state(project_id: str) -> dict:
    return dict(((db.get_project(project_id) or {}).get("info") or {}).get("cloud") or {})


def _save(project_id: str, **changes) -> dict:
    p = db.get_project(project_id) or {}
    info = dict(p.get("info") or {})
    st = {**(info.get("cloud") or {}), **changes}
    info["cloud"] = st
    db.update_project(project_id, info=info)
    return st


def _log(project_id: str, text: str) -> None:
    st = state(project_id)
    lines = list(st.get("log") or [])
    lines.append({"at": round(time.time(), 1), "text": text[:300]})
    _save(project_id, log=lines[-LOG_MAX:])


def _stage(project_id: str, stage: str, progress: float, message: str) -> None:
    db.update_project(project_id, stage=stage, progress=round(min(max(progress, 0.0), 0.999), 4), message=message[:200])


# ------------------------------------------------------------------ the run
def run(project_id: str, url: str | None, ctx: JobContext) -> None:
    p = db.get_project(project_id)
    if not p:
        return
    settings = db.get_settings()
    cfg = client.configured(settings)
    if not cfg:
        raise RemoteError("This project is set to run on your worker, but no worker is set up. Add one in Settings → "
                          "Processing, or switch to Local there and press Retry.")
    c = client.Client(cfg["url"], cfg["key"])
    st = state(project_id)
    again = bool(st.get("job")) and st.get("phase") in ("running", "fetching") and st.get("worker") == cfg["host"]
    # this run's worker-time record: set as soon as _submit makes it, so a failure or Stop during the upload closes it
    box = {"run": str(st.get("run") or "") if again else ""}
    try:
        if again:
            _log(project_id, "Picked up the job on the worker again (ClipForge was closed or restarted; the work "
                             "went on there).")
            usage.update(box["run"], status="running")
        else:
            st = _submit(p, url, c, cfg, settings, ctx, box)
        run_id = box["run"]
        job = _follow(project_id, c, st["job"], run_id, ctx)
        _save(project_id, phase="fetching")
        usage.update(run_id, status="fetching")
        count = _fetch(project_id, c, st["job"], ctx)
        try:
            c.delete(st["job"])
            _log(project_id, "Deleted the job and its files on the worker.")
        except client.WorkerError as exc:  # it is deleted there after worker_api.KEEP_HOURS anyway
            _log(project_id, f"The job could not be deleted on the worker yet ({exc}); it deletes itself after "
                             f"3 days.")
        seconds = usage.measured(job)
        price = float(settings.get("worker_price_per_hour") or 0)
        _save(project_id, phase="done", ran=job.get("ran") or {}, how=job.get("how") or {}, seconds=seconds,
              cost=round(seconds / 3600 * price, 2) if price else None, clips=count, finished=time.time())
        usage.update(run_id, status="done", ended_at=time.time(), seconds=seconds,
                     info={"video_seconds": job.get("duration") or 0, "ran": job.get("ran") or {}, "clips": count})
        _log(project_id, f"Brought back {count} clip{'s' if count != 1 else ''}. Worker time: "
                         f"{round(seconds / 60, 1)} minutes.")
    except (Cancelled, client.Stopped):
        _stop(project_id, c, box["run"])
        raise Cancelled() from None
    except Exception as exc:
        if state(project_id).get("phase") in ("running", "fetching"):  # the job goes on there: Retry picks it up
            usage.update(box["run"], status="waiting")
        else:
            usage.update(box["run"], status="failed", ended_at=time.time())
            if state(project_id).get("phase") not in ("gone", "failed", "canceled"):
                _save(project_id, phase="failed")  # the card must not say it is still sending or waiting
        _log(project_id, f"Stopped: {str(exc)[:240]}")
        if isinstance(exc, client.WorkerLost):
            raise RemoteError(f"{exc} Press Retry to try again.") from exc
        raise
    _after(project_id)


NOT_OWN_FOLDER = ("This project's video is not in its own ClipForge folder (the data folder was moved or copied "
                  "since it was added), so its clips cannot be brought back here. Switch to Local in Settings → "
                  "Processing and press Process again to make them on this computer.")


def _submit(p: dict, url: str | None, c: client.Client, cfg: dict, settings: dict, ctx: JobContext,
            box: dict) -> dict:
    from .worker_api import own_folder

    pid = p["id"]
    # the clips come back only into the project's own folder (_fetch): said before any upload or worker time
    if not p.get("source_path") or not own_folder(Path(p["source_path"]).parent):
        raise RemoteError(NOT_OWN_FOLDER)
    src = Path(p["source_path"]) if p.get("source_path") else None
    link = (url or "") if not (src and src.is_file()) else ""
    if not link and not (src and src.is_file()):
        raise RemoteError("The video is not on this computer any more, and there is no link to send.")
    seconds = None
    if src and src.is_file():
        try:
            from ..pipeline.ffmpeg_utils import probe

            seconds = float(probe(src).get("duration") or 0) or None
        except Exception:  # noqa: BLE001 - the estimate is only a guide
            seconds = None
    est = usage.estimate(seconds, cfg["host"], settings)
    problem = usage.limit_problem(settings, p.get("workspace_id") or "local", est["seconds"])
    if problem:
        raise RemoteError(problem)
    _stage(pid, "upload", 0.0, "Checking the worker")
    try:
        facts = c.info()
    except client.WorkerLost as exc:
        raise RemoteError(f"The worker at {cfg['host']} is not answering. Check that it is on, or switch to Local in "
                          f"Settings → Processing.") from exc
    if not facts.get("worker"):
        raise RemoteError("That address is not a ClipForge worker.")
    size = src.stat().st_size if src and not link else 0
    most = float(facts.get("max_upload_gb") or 0)
    if most and size > most * 1024 ** 3:  # refused there only after the whole upload: say so before sending it
        raise RemoteError(f"The video is {_mb(size)}; your worker takes videos up to {most:g} GB "
                          f"(CLIPFOUNDRY_WORKER_MAX_GB on the worker). Raise it there, or switch to Local in "
                          f"Settings → Processing.")
    ctx.check()
    run_row = usage.start("project", cfg["host"], pid, est, p.get("workspace_id") or "local")
    box["run"] = run_row["id"]
    transcript = Path(str((p.get("options") or {}).get("transcript_file") or ""))
    # what leaves this computer, as the owner knows it (the video's own name, not ClipForge's copy of it)
    sent = [{"what": "video", "name": (p.get("source_filename") or src.name) if src and not link else "",
             "link": link, "bytes": src.stat().st_size if src and not link else 0}]
    if transcript.is_file():
        sent.append({"what": "transcript", "name": transcript.name, "link": "", "bytes": transcript.stat().st_size})
    _save(pid, phase="upload", worker=cfg["host"], run=run_row["id"], job="", estimate=est, uploaded=sent,
          worker_info={"version": facts.get("version"), "whisper": facts.get("whisper") or {},
                       "ai": facts.get("ai") or ""},
          started=time.time(), log=[], unsupported=list(UNSUPPORTED))
    _log(pid, f"Worker {cfg['host']} is ready (ClipForge {facts.get('version')}, transcription: "
              f"{(facts.get('whisper') or {}).get('model') or 'its own'}"
              f"{' on ' + str((facts.get('whisper') or {}).get('device')) if (facts.get('whisper') or {}).get('device') else ''}).")
    usage.update(run_row["id"], status="uploading")

    def sent_so_far(n: int, total: int) -> None:
        _stage(pid, "upload", UPLOAD_SHARE * n / max(total, 1),
               f"Uploading the video to the worker ({_mb(n)} of {_mb(total)})")

    if link:
        _stage(pid, "upload", 0.02, "Sending the link to the worker")
    options = {k: v for k, v in (p.get("options") or {}).items() if k in OPTION_KEYS}
    job = c.submit(source=None if link else src, link=link, transcript=transcript if transcript.is_file() else None,
                   options=options, settings={k: settings[k] for k in SETTING_KEYS if k in settings},
                   name=p.get("name") or "", clip_mode=p.get("clip_mode") or "highlights",
                   guidance=lean_guidance(p.get("guidance") or {}), progress=sent_so_far, cancel=ctx.cancelled)
    up = sum(int(x["bytes"]) for x in sent)
    _log(pid, "Sent the link; the worker downloads the video itself." if link else
         f"Uploaded {sent[0]['name']}{' and its transcript' if len(sent) > 1 else ''} ({_mb(up)}).")
    if not ID_RE.match(str(job.get("id") or "")):
        raise RemoteError("The worker's answer could not be read (no job id).")
    usage.update(run_row["id"], status="running", remote_id=job["id"], uploaded_bytes=up)
    return _save(pid, phase="running", job=job["id"])


def _follow(pid: str, c: client.Client, job_id: str, run_id: str, ctx: JobContext) -> dict:
    lost_since = 0.0
    last = None
    wait = POLL_S
    while True:
        if ctx.cancelled():
            raise Cancelled()
        try:
            job = c.job(job_id)
            lost_since, wait = 0.0, POLL_S
        except client.WorkerLost:
            now = time.time()
            lost_since = lost_since or now
            if now - lost_since > LOST_LIMIT_S:
                raise RemoteError("The worker has not answered for 30 minutes. Press Retry to look for the job "
                                  "again; the work may have gone on there.") from None
            _stage(pid, (db.get_project(pid) or {}).get("stage") or "upload",
                   (db.get_project(pid) or {}).get("progress") or 0,
                   "The worker is not answering; trying again (the work goes on there)")
            if (last or ("", ""))[0] != "lost":
                _log(pid, "Lost the connection to the worker; trying again.")
                last = ("lost", "")
            _sleep(min(30.0, wait), ctx)
            wait *= 2
            continue
        except client.WorkerError as exc:
            if exc.status == 404:
                _save(pid, phase="gone", job="")
                raise RemoteError("The job is no longer on the worker (it was deleted, or the worker was reset). "
                                  "Press Retry to send the video again.") from exc
            raise RemoteError(str(exc)) from exc
        said = (job.get("stage") or "", job.get("message") or "")
        if said != last and (said[1] or said[0]):
            step = STEP_WORDS.get(job.get("step") or "", "")
            _log(pid, f"Worker: {said[1] or said[0]}" + (f" ({step})" if step and step not in said[1] else ""))
            last = said
        _stage(pid, job.get("stage") or "processing", UPLOAD_SHARE + FOLLOW_SHARE * float(job.get("progress") or 0),
               f"On the worker: {job.get('message') or 'working'}")
        usage.update(run_id, seconds=usage.measured(job))
        if job["status"] == "ready":
            return job
        if job["status"] == "error":
            _save(pid, phase="failed")
            raise RemoteError(f"The worker could not make the clips: {job.get('error') or 'it stopped'}")
        if job["status"] == "cancelled":
            _save(pid, phase="canceled")
            raise Cancelled()
        _sleep(POLL_S, ctx)


def _sleep(seconds: float, ctx: JobContext) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if ctx.cancelled():
            raise Cancelled()
        time.sleep(min(0.25, end - time.time()) if end > time.time() else 0)


def _fetch(pid: str, c: client.Client, job_id: str, ctx: JobContext) -> int:
    """Bring the finished job back: files first (into a folder of their own), then the rows, then the files go in
    place. Nothing of the project changes until everything has arrived."""
    from .worker_api import own_folder

    p = db.get_project(pid) or {}
    pdir = Path(p["source_path"]).parent
    if not own_folder(pdir):  # files come back only into the project's own folder (and only that is tidied)
        # the job ends here: Process again decides where to run afresh (decide) instead of following this job
        _save(pid, phase="failed", job="")
        try:
            c.delete(job_id)
        except client.WorkerError:
            pass  # it is deleted there after worker_api.KEEP_HOURS anyway
        raise RemoteError(NOT_OWN_FOLDER)
    res = checked(c.result(job_id), job_id)
    remote_dir, remote_id = str(res["dir"]), str(res["job"]["id"])
    staging = pdir / ".from-worker"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    wanted = [(f"/jobs/{job_id}/files/{n}", staging / n) for n in res.get("files") or []]
    for cl in res["clips"]:
        cid = cl["row"]["id"]
        wanted += [(f"/jobs/{job_id}/clips/{cid}/{f['name']}", staging / "clips" / cid / f["name"])
                   for f in cl.get("files") or []]
    src = Path(p["source_path"])
    if res.get("source") and not src.is_file():  # a link: the video comes back for edits and renders here
        wanted.append((f"/jobs/{job_id}/files/source", staging / "source"))
    total = sum(int(f["bytes"]) for cl in res["clips"] for f in cl.get("files") or []) + \
        int((res.get("source") or {}).get("bytes") or 0)
    done = [0]
    base = UPLOAD_SHARE + FOLLOW_SHARE

    for path, dest in wanted:
        before = done[0]

        def moved(n: int, before: int = before) -> None:
            done[0] = before + n
            _stage(pid, "fetch", base + (1 - base) * 0.95 * done[0] / max(total, 1),
                   f"Bringing the clips back ({_mb(done[0])} of {_mb(total)})")

        done[0] = before + c.download(path, dest, cancel=ctx.cancelled, progress=moved)
        ctx.check()
    _log(pid, f"Brought back {len(wanted)} files ({_mb(done[0])}).")
    count = _import(pid, res, staging, remote_dir, remote_id, str(pdir))
    if (staging / "source").is_file():
        (staging / "source").replace(src)
    for n in res.get("files") or []:
        if (staging / n).is_file():
            (staging / n).replace(pdir / n)
    shutil.rmtree(staging, ignore_errors=True)
    return count


def checked(res: dict, job_id: str) -> dict:
    """A worker's answer is checked before any of it touches this computer: the names in it become file paths and
    rows here, so a broken or hostile worker must not reach outside the project. Every clip id is an id, every file
    name is a plain name in the clip's own folder, the project's files are the known three."""
    def bad(why: str) -> RemoteError:
        return RemoteError(f"The worker's answer was refused ({why}); nothing was changed here.")

    if not isinstance(res, dict) or not isinstance(res.get("job"), dict) or str(res["job"].get("id") or "") != job_id:
        raise bad("it is not for this job")
    if len(str(res.get("dir") or "").strip()) < 4:
        raise bad("no folder")
    if not all(isinstance(n, str) and n in PROJECT_FILES for n in res.get("files") or []):
        raise bad("an unknown project file")
    if not isinstance(res.get("clips"), list) or not all(isinstance(cl, dict) for cl in res["clips"]):
        raise bad("no clips")
    seen = set()
    for cl in res.get("clips") or []:
        cid = str((cl.get("row") or {}).get("id") or "")
        if not ID_RE.match(cid) or cid in seen:
            raise bad("a clip id that is not an id")
        seen.add(cid)
        for f in cl.get("files") or []:
            name = str((f or {}).get("name") or "")
            if not name or not set(name) <= SAFE_NAME or name.startswith(".") or not str(f.get("bytes", 0)).isdigit():
                raise bad("a file name that is not a plain name")
    return res


def _mapped(value, remote_dir: str, local_dir: str, remote_id: str, local_id: str):
    """A value with the worker's folder and project id changed to this computer's, in every string inside it."""
    if isinstance(value, str):
        return value.replace(remote_dir, local_dir).replace(remote_id, local_id)
    if isinstance(value, list):
        return [_mapped(v, remote_dir, local_dir, remote_id, local_id) for v in value]
    if isinstance(value, dict):
        return {k: _mapped(v, remote_dir, local_dir, remote_id, local_id) for k, v in value.items()}
    return value


def _rows_for(table: str, rows: list[dict], fix) -> list[dict]:
    """The worker's rows for this computer. Its JSON columns come as text: they are read, changed and written again
    (changing the text itself would put a Windows folder's backslashes into the JSON unescaped)."""
    cols, as_json = db.columns(table), db.JSON_FIELDS.get(table, set())
    out = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if k not in cols:
                continue
            if k in as_json and isinstance(v, str):
                try:
                    v = json.dumps(fix(json.loads(v)))
                except ValueError:
                    v = None
            else:
                v = fix(v)
            row[k] = v
        out.append(row)
    return out


def _insert(conn, table: str, row: dict) -> None:
    conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))


def lean_guidance(snapshot: dict) -> dict:
    """What a worker needs of a project's guidance snapshot (studio/guidance.py): the chosen values and, for each,
    which level decided it, by id only. The names of styles, skills, examples and Brain notes, and the conflicts and
    explanations, stay on this computer."""
    if not snapshot.get("schema"):
        return {}
    return {"schema": snapshot["schema"], "mode": snapshot.get("mode"), "values": snapshot.get("values") or {},
            "decisions": [{"field": d.get("field"), "value": d.get("value"),
                           "from": {k: (d.get("from") or {}).get(k) for k in ("level", "id", "revision")} | {"name": ""}}
                          for d in snapshot.get("decisions") or []]}


def _import(pid: str, res: dict, staging: Path, remote_dir: str, remote_id: str, local_dir: str) -> int:
    def fix(v):
        return _mapped(v, remote_dir, local_dir, remote_id, pid)

    from ..studio import guidance as guidance_mod

    local_guidance = (db.get_project(pid) or {}).get("guidance") or {}
    # which Brain notes shaped the clips, named from this computer's own snapshot (the worker only had their ids)
    brain_used = guidance_mod.brain_influences(local_guidance) if local_guidance.get("schema") else None

    clips = res["clips"]
    clashes = [cl["row"]["id"] for cl in clips if (db.get_clip(cl["row"]["id"]) or {}).get("project_id") not in
               (None, pid)]
    if clashes:
        raise RemoteError("A clip from the worker has the same id as a clip here; nothing was changed. Press Retry.")
    clip_folder = Path(local_dir) / "clips"
    with db.connect() as conn:  # one transaction: the project's clips change all together or not at all
        for table in db.CLIP_CHILDREN:
            conn.execute(f"DELETE FROM {table} WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)", (pid,))
        conn.execute("DELETE FROM clips WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM clip_candidates WHERE project_id = ?", (pid,))
        for row in _rows_for("clip_candidates", res.get("candidates") or [], fix):
            _insert(conn, "clip_candidates", {**row, "project_id": pid})
        for cl in clips:
            row = {**_rows_for("clips", [cl["row"]], fix)[0], "project_id": pid}
            if brain_used is not None and row.get("render_info"):  # the worker's rows hold JSON as text
                info = json.loads(row["render_info"]) if isinstance(row["render_info"], str) else row["render_info"]
                row["render_info"] = json.dumps({**info, "brain_knowledge": brain_used})
            for t in CHILDREN:
                conn.execute(f"DELETE FROM {t} WHERE clip_id = ?", (row["id"],))
            _insert(conn, "clips", row)
            for t in CHILDREN:
                for child in _rows_for(t, (cl.get("children") or {}).get(t) or [], fix):
                    child["clip_id"] = row["id"]  # a child row belongs to the clip it came with, never another
                    if "project_id" in child:
                        child["project_id"] = pid
                    _insert(conn, t, child)
    for cl in clips:
        cid = cl["row"]["id"]
        got = staging / "clips" / cid
        if got.is_dir():
            dest = clip_folder / cid
            if dest.resolve().parent != clip_folder.resolve():  # checked() allows ids only; never outside the folder
                raise RemoteError("A clip folder from the worker was outside the project; nothing was moved.")
            shutil.rmtree(dest, ignore_errors=True)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(got), str(dest))
    p = db.get_project(pid) or {}
    meta = {k: v for k, v in (res.get("project") or {}).items() if v}
    info = {**(p.get("info") or {}), **{k: fix(v) for k, v in (res.get("info") or {}).items()
                                       if k not in ("cloud", "processing", "resume_count", "worker_job")}}
    db.update_project(pid, info=info, **meta)
    return len(clips)


def _after(pid: str) -> None:
    """As after a render here: a "Make & upload clips" request uploads the eligible clips, from this computer."""
    p = db.get_project(pid) or {}
    if not (p.get("destinations") or {}):
        return
    from ..studio import autopublish

    for clip in db.list_clips(pid):
        if clip.get("status") == "ready":
            autopublish.after_render(clip["id"])


def _stop(pid: str, c: client.Client, run_id: str) -> None:
    st = state(pid)
    if st.get("job"):
        try:
            c.cancel(st["job"])
            c.delete(st["job"])
            _log(pid, "Stopped. The job was stopped and deleted on the worker.")
        except client.WorkerError as exc:
            _log(pid, f"Stopped here; the worker could not be told ({exc}). It deletes the job after 3 days.")
    _save(pid, phase="canceled", job="")
    usage.update(run_id, status="canceled", ended_at=time.time())


def stop_waiting(pid: str) -> None:
    """Stop pressed on a project that was not running here (queued after a restart) while its job is still on the
    worker: the job there is stopped and deleted too, as Stop does for a running one."""
    p = db.get_project(pid) or {}
    st = state(pid)
    if (p.get("info") or {}).get("processing") != "full_cloud" or not st.get("job") or \
            st.get("phase") not in ("running", "fetching"):
        return
    try:
        c = client.Client.from_settings()
    except client.WorkerError:
        _log(pid, "Stopped here; no worker is set up to tell. The job deletes itself there after 3 days.")
        _save(pid, phase="canceled", job="")
        usage.update(str(st.get("run") or ""), status="canceled", ended_at=time.time())
        return
    _stop(pid, c, str(st.get("run") or ""))


def view(project: dict) -> dict | None:
    """What the project page shows about its Full Cloud run (None for a project made here, also one made here
    again after a run on the worker)."""
    info = project.get("info") or {}
    if info.get("processing") != "full_cloud":
        return None
    st = info.get("cloud") or {}
    return {"phase": st.get("phase") or "waiting", "worker": st.get("worker") or "", "uploaded": st.get("uploaded") or [],
            "estimate": st.get("estimate") or None, "seconds": st.get("seconds"), "cost": st.get("cost"),
            "ran": st.get("ran") or {}, "how": st.get("how") or {}, "log": (st.get("log") or [])[-60:],
            "worker_info": st.get("worker_info") or {}, "unsupported": list(UNSUPPORTED), "clips": st.get("clips")}


def _mb(n: float) -> str:
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1024 / 1024:.1f} MB" if n < 1024 ** 3 else f"{n / 1024 ** 3:.2f} GB"
