"""Clip Hunter and Deep Clip Analyzer workers.

Clip Hunter (GPU stage): puts the source's video in a project, reads it, transcribes it (one heavy GPU job at a
time, waiting for free GPU memory) and builds a broad pool of candidate windows (60 by default, roughly 30-100 for
typical videos).

Deep Clip Analyzer (CPU stage): ranks the pool in stages (pipeline/deep.py), picks meaningfully different clips that
pass the quality bar (pipeline/diversity.py), renders them, fingerprints them for duplicate protection, and hands
them to Packaging. A source that yields fewer strong clips than half its target is marked weak: it does not count
toward the day, and Source Scout picks another source instead of padding.
"""
from __future__ import annotations

import math
import os
import shutil
import time
from pathlib import Path

from .. import config, db, gpu, netguard
from ..jobs import DownloadRefused, download_url
from ..pipeline import blueprint, cuda, fingerprint, process, transcribe
from ..pipeline.common import JobContext, read_json, write_json
from ..pipeline.ffmpeg_utils import FFmpegError, probe
from ..publish.common import client
from . import access, queue, rights, state
from .host import Job, handler

POOL_SIZE = 60
DIRECT_MEDIA = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".ogv")


GPU_PAUSE_SECONDS = 1800


def gpu_policy(settings: dict, job: Job) -> dict:
    plan = transcribe.whisper_plan(settings, cuda.probe())
    need = int(settings.get("gpu_min_free_vram_mb") or 0) if plan["mode"] == "gpu" else 0
    return {"need_free_mb": need, "max_wait_s": 60.0 * float(settings.get("gpu_wait_minutes") or 20),
            "job_id": job.id, "allow_cpu_fallback": bool(settings.get("autopilot_allow_cpu_fallback"))}


def gpu_failed(exc: transcribe.GpuTranscriptionFailed, what: str) -> queue.Wait:
    """Strict GPU: the job pauses (without using an attempt) and the user learns what to do."""
    state.action("gpu:strict", "gpu", "Autopilot transcription is paused: the GPU could not be used",
                 f"{what}: {exc}", (exc.fix + " " if exc.fix else "") + "Run gpu-check.bat. To let Autopilot "
                 "transcribe on the CPU meanwhile (slower), turn on Settings → Autopilot → "
                 "Allow CPU transcription.",
                 level="error")
    return queue.Wait("gpu_failed", GPU_PAUSE_SECONDS, f"GPU transcription failed; paused. {exc}")


def project_options(settings: dict) -> dict:
    return {"clip_count": int(settings.get("autopilot_clips_per_source") or 5), "deep_analysis": True,
            "pool_size": POOL_SIZE, "min_quality": float(settings.get("autopilot_min_quality") or 0)}


# ------------------------------------------------------------------ media
def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)  # instant on the same drive, no extra disk space
    except OSError:
        shutil.copy2(src, dst)


MIN_FREE_DISK = 2e9  # never fill the disk: this much stays free after a download


def max_source_bytes(settings: dict) -> int:
    return int(float(settings.get("autopilot_max_source_gb") or 8) * 1e9)


def _http_download(url: str, dst: Path, ctx: JobContext, src: dict, settings: dict) -> None:
    """A direct media link, checked against private/local addresses on every redirect and bounded in size."""
    def accept(r) -> None:
        if r.status_code != 200:
            raise queue.Retry(f"The media URL answered {r.status_code}", "Check that the link still works.")
        kind = r.headers.get("content-type", "")
        if not kind.startswith(("video/", "application/octet-stream", "binary/", "application/ogg")):
            raise queue.Fail(f"The URL is not a video file ({kind or 'unknown type'})",
                             "Use a direct link to the video file, or add the file itself.")
        need = int(r.headers.get("content-length") or 0) + MIN_FREE_DISK
        free = shutil.disk_usage(dst.parent).free
        if free < need:
            state.action("disk:space", "disk", "Not enough free disk space for Autopilot downloads",
                         f"{free / 1e9:.1f} GB free; this source needs {need / 1e9:.1f} GB including a reserve.",
                         "Free up space on the drive of the data folder (Settings → System).", level="warning")
            raise queue.Wait("disk", 1800, "Waiting for free disk space")

    def progress(done: int, total: int) -> None:
        if total:
            ctx.progress(0.02 * done / total, f"Downloading {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    try:
        with client(120) as c:
            netguard.download(c, url, dst, allow_private=rights.url_typed_by_user(src),
                              max_bytes=max_source_bytes(settings), accept=accept, progress=progress,
                              cancelled=ctx.cancelled)
    except netguard.UnsafeUrl as exc:
        raise queue.Fail(f"Not downloaded: {exc}", "Use a direct link to a video on the internet, or add the file "
                                                   "itself.") from exc
    state.resolve("disk:space")


def write_provenance(pdir: Path, src: dict, found: dict, settings: dict) -> None:
    """Keep the file together with where it came from and why it may be used: the source, the rights decision with
    its conditions and evidence, the license the provider reported, and how the file was obtained."""
    r = rights.evaluate(src, settings)
    rule = db.fetch("source_rights", r["rule_id"]) if r.get("rule_id") else None
    f = next((p for p in pdir.glob("source.*") if p.suffix.lower() in config.VIDEO_EXTENSIONS), None)
    write_json(pdir / "provenance.json", {
        "source": {k: src.get(k) for k in ("id", "platform", "external_id", "title", "url", "channel_id",
                                           "channel_title", "published_at", "signal_id")},
        "rights": {k: r.get(k) for k in ("status", "label", "basis", "rule_id", "conditions")},
        "evidence": {"text": (rule or {}).get("evidence", ""), "url": (rule or {}).get("evidence_url", "")},
        "license": src.get("rights_info") or {},
        "attribution": rights.attribution({**src, "rights_status": r["status"], "rights_rule_id": r["rule_id"]}),
        "access": {k: found.get(k) for k in ("method", "label", "detail", "local_path", "url")},
        "file": {"name": f.name, "bytes": f.stat().st_size} if f else None,
        "obtained_at": time.time()})


def ensure_project(src: dict, settings: dict, ctx: JobContext) -> dict:
    """The project that holds this source's video (created once; re-used when the job is retried)."""
    project = db.get_project(src.get("project_id") or "") if src.get("project_id") else None
    if project is None:
        project = db.create_project((src.get("title") or "Autopilot source")[:120], origin="autopilot",
                                    source_id=src["id"], source_url=src.get("url", ""), status="processing",
                                    options=project_options(settings))
        db.update("sources", src["id"], project_id=project["id"])
    pdir = config.projects_dir() / project["id"]
    pdir.mkdir(parents=True, exist_ok=True)
    existing = next((p for p in pdir.glob("source.*") if p.suffix.lower() in config.VIDEO_EXTENSIONS), None)
    if existing:
        dst = existing
    else:
        found = access.resolve(src, settings)  # how the file may be obtained, apart from the right to reuse it
        db.update("sources", src["id"], access=access.record(src, found))
        if not found["ok"]:
            raise queue.Fail(found["detail"], "Add the original file on the Autopilot page (Activity).")
        if found.get("local_path"):
            local = Path(found["local_path"])
            if not local.exists():
                raise queue.Fail("The source file no longer exists", "Add the file again in Autopilot → Sources.")
            dst = pdir / f"source{local.suffix.lower()}"
            _link_or_copy(local, dst)
        elif found["method"] != "platform" or (found.get("url") or "").lower().split("?")[0].endswith(DIRECT_MEDIA):
            dst = pdir / f"source{_suffix(found['url'])}"
            _http_download(found["url"], dst, ctx, src, settings)
        else:
            db.update_project(project["id"], source_path=str(pdir / "source.mp4"))
            try:  # the existing importer (no logins, cookies or DRM), with Autopilot's size and length limits
                download_url(project["id"], found["url"], ctx, max_bytes=max_source_bytes(settings),
                             max_seconds=60.0 * float(settings.get("autopilot_max_source_minutes") or 240))
            except DownloadRefused as exc:
                raise queue.Fail(str(exc), "Raise the limits in Settings → Autopilot, or add a shorter source.") \
                    from exc
            write_provenance(pdir, src, found, settings)
            return db.get_project(project["id"]) or project
        write_provenance(pdir, src, found, settings)
    db.update_project(project["id"], source_path=str(dst), source_filename=dst.name)
    return db.get_project(project["id"]) or project


def _suffix(url: str) -> str:
    """The downloaded file keeps its container's extension (a library serves WebM or Ogg as often as MP4)."""
    ext = Path(url.split("?")[0].split("#")[0]).suffix.lower()
    return ext if ext in config.VIDEO_EXTENSIONS else ".mp4"


def check_length(project: dict, settings: dict) -> None:
    """Autopilot processes sources up to the configured length (transcribing and analyzing costs grow with it)."""
    limit = 60.0 * float(settings.get("autopilot_max_source_minutes") or 240)
    try:
        duration = float(probe(project["source_path"])["duration"] or 0)
    except FFmpegError as exc:
        raise queue.Fail(f"The source video cannot be read: {exc}", "Add another copy of the file.") from exc
    if duration > limit:
        raise queue.Fail(f"The source is {duration / 60:.0f} min long; Autopilot processes sources up to "
                         f"{limit / 60:.0f} min", "Raise the limit in Settings → Autopilot, or clip it by hand.")


# ------------------------------------------------------------------ Clip Hunter
def _source_failed(job: Job, exc: Exception) -> None:
    """Keep the source and its project honest about a failure (final, or retrying)."""
    src = db.fetch("sources", job.payload.get("source_id", ""))
    if not src:
        return
    final = isinstance(exc, queue.Fail) or job.row["attempts"] >= job.row["max_attempts"]
    if final:
        db.update("sources", src["id"], status="failed", error=str(exc)[:500], status_note=f"Failed: {exc}"[:300])
        if src.get("project_id"):
            db.update_project(src["project_id"], status="error", error=str(exc)[:500], message="Failed")
        state.event("source_failed", f"“{src['title'][:80]}” failed: {exc}", "error", ref_type="source",
                    ref_id=src["id"])
    else:
        db.update("sources", src["id"], status_note=f"Retrying after: {exc}"[:300])


def _guard(fn):
    def run(job: Job) -> dict:
        try:
            return fn(job)
        except (queue.Wait, queue.Canceled):
            raise
        except Exception as exc:
            _source_failed(job, exc)
            raise
    run.__name__ = fn.__name__
    return run


@handler("hunt_source")
@_guard
def hunt_source(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    if not src:
        raise queue.Fail("The source was deleted")
    try:
        rights.gate(src, "ingest", settings)
    except rights.RightsBlocked as exc:
        db.update("sources", src["id"], status="blocked" if exc.status == rights.BLOCKED else "needs_rights",
                  status_note=str(exc))
        raise queue.Fail(str(exc), "Change the source's rights status in Autopilot → Sources.") from exc
    db.update("sources", src["id"], status="ingesting", status_note="Getting the video")
    ctx = job.pipeline_ctx(0.0, 1.0)
    try:
        project = ensure_project(src, settings, ctx)
        check_length(project, settings)
        db.update_project(project["id"], status="processing", message="Autopilot: reading the video", error="")
        job.progress(0.05, "Reading and transcribing", stage="transcribe")
        p = process.prepare(project["id"], ctx, gpu_policy(settings, job))
    except gpu.GpuBusy as exc:
        db.update("sources", src["id"], status="queued", status_note=str(exc))
        raise queue.Wait("gpu", 600, f"{exc} Trying again in 10 minutes.") from exc
    except transcribe.GpuTranscriptionFailed as exc:
        db.update("sources", src["id"], status="queued", status_note=f"Paused: GPU transcription failed. {exc}"[:300])
        raise gpu_failed(exc, f"“{src.get('title', '')[:60]}”") from exc
    state.resolve("gpu:strict")
    if p is None:
        raise queue.Fail("The project could not be prepared")
    cands = process.candidate_pool(p, ctx)
    p.save_info()
    db.execute("DELETE FROM clip_candidates WHERE project_id = ?", (p.id,))
    for c in cands:
        db.insert("clip_candidates", {"project_id": p.id, "source_id": src["id"], "start": c["start"],
                                      "end": c["end"], "s0": c.get("s0", -1), "s1": c.get("s1", -1), "stage": "pool",
                                      "stage1": round(float(c.get("stage1", 0)), 4), "text": (c.get("text") or "")[:500],
                                      "id": f"{p.id}-{c['cid']}"})
    db.update("sources", src["id"], status="analyzing", candidates_found=len(cands), duration=p.meta.get("duration"),
              status_note=f"{len(cands)} candidate moments found; waiting for the analyzer")
    db.update_project(p.id, message=f"{len(cands)} candidate moments; analyzing")
    queue.enqueue("analyze_source", {"source_id": src["id"], "project_id": p.id},
                  idem_key=f"analyze:{src['id']}:{p.id}", ref=("source", src["id"]), priority=job.row["priority"],
                  timeout_s=4 * 3600)
    return {"project_id": p.id, "candidates": len(cands), "message": f"{len(cands)} candidate moments found"}


# ------------------------------------------------------------------ Deep Clip Analyzer
def prior_fingerprints(exclude_project: str) -> list[dict]:
    """Fingerprints of clips that were published or are scheduled (never post the same moment twice)."""
    return db.select("clip_fingerprints", "clip_id IN (SELECT clip_id FROM publications WHERE status IN ('done', "
                                          "'action_needed', 'uploading', 'processing', 'queued') UNION SELECT clip_id "
                                          "FROM scheduled_publications WHERE status NOT IN ('canceled', 'replaced', "
                                          "'failed')) AND clip_id NOT IN (SELECT id FROM clips WHERE project_id = ?)",
                     (exclude_project,))


def store_fingerprint(clip: dict, src: dict) -> None:
    video = fingerprint.video_signature(clip["output_path"], float(clip.get("duration") or 0)) \
        if clip.get("output_path") and Path(clip["output_path"]).exists() else []
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "source_key": f"{src['platform']}:{src['external_id']}",
                                    "start": clip["start"], "end": clip["end"],
                                    "text_sig": fingerprint.text_signature(clip.get("caption_text") or ""),
                                    "phash": video, "title_norm": fingerprint.norm_title(clip.get("title") or "")},
              key="clip_id", replace=True)


def plan_clips(p: process.Prepared, rows: list[dict], chosen: list[dict], source_id: str) -> list[dict]:
    """Engagement Strategist: a validated blueprint for every chosen clip, stored before anything is rendered.
    A clip whose plan is rejected is not rendered; the reasons are kept on the clip."""
    ok = []
    for row, r in zip(rows, chosen):
        bp = blueprint.build(row, p.project, p.words, p.settings, source_id=source_id, selection=r,
                             video_path=p.project.get("source_path"))
        issues = blueprint.validate(bp, p.meta.get("duration"), p.words)
        blueprint.save(bp, issues)
        problems = blueprint.errors(issues)
        if problems:
            db.update_clip(row["id"], status="error", error=("Plan rejected: " + "; ".join(problems[:3]))[:500])
            continue
        ok.append(row)
    return ok


@handler("analyze_source")
@_guard
def analyze_source(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    p = process.load_prepared(job.payload.get("project_id", ""))
    if not src or not p:
        raise queue.Fail("The source or its transcript is missing", "Start the source again in Autopilot → Sources.")
    ctx = job.pipeline_ctx(0.0, 1.0)
    cands = read_json(p.pdir / "candidates.json", []) or []
    db.update_project(p.id, status="processing", message="Autopilot: analyzing candidates")
    job.progress(0.05, f"Analyzing {len(cands)} candidates", stage="analyze")
    signal = db.fetch("trend_signals", src.get("signal_id") or "") if src.get("signal_id") else None
    trend_kw = (signal or {}).get("keywords") or []
    chosen = process.evaluate_select(p, cands, ctx, trend_keywords=trend_kw, prior=prior_fingerprints(p.id))
    for c in p.info.get("candidates", []):
        db.update("clip_candidates", f"{p.id}-{c['cid']}", stage=c["stage"], score=c["score"], rejected=c["reasons"])
    job.progress(0.6, f"Rendering {len(chosen)} clip(s)", stage="render")
    rows = process.create_clips(p, chosen, ctx)
    planned = plan_clips(p, rows, chosen, src["id"])
    for row, r in zip(rows, chosen):
        d = r.get("deep") or {}
        db.update("clip_candidates", f"{p.id}-{r['cid']}", clip_id=row["id"])
        db.insert("clip_analysis", {"clip_id": row["id"], "project_id": p.id, "semantic": d.get("semantic") or {},
                                    "audio": d.get("audio") or {}, "visual": d.get("visual") or {},
                                    "boundary": r.get("bounds") or {}, "deep": {"extras": d.get("extras") or {},
                                                                                "stages": p.info.get("quality", {})
                                                                                .get("stages", {})}},
                  key="clip_id", replace=True)
        sub = (r.get("analysis") or {}).get("subscores") or {}
        db.insert("clip_scores", {"clip_id": row["id"], "trend": (signal or {}).get("score"),
                                  "source": src.get("source_score"), "clip": r.get("clip_score", r["score"]),
                                  "diversity": (r.get("diversity") or {}).get("score"),
                                  "retention": sub.get("retention"),
                                  "components": {"viral_potential": r["score"], "subscores": sub,
                                                 "diversity": r.get("diversity") or {}},
                                  "explanation": r.get("explanation") or []}, key="clip_id", replace=True)
    process.render_clips(p, planned, ctx, lo=0.6, hi_total=0.95)
    ready = [c for c in db.list_clips(p.id) if c["status"] == "ready"]
    for clip in ready:
        job.check()
        store_fingerprint(clip, src)
    p.info["processing_seconds"] = round(time.time() - p.t_start, 1)
    db.update_project(p.id, status="ready", progress=1.0, stage="done", info=p.info,
                      message=f"{len(ready)} clip{'s' if len(ready) != 1 else ''} ready" if ready else
                      "No strong moments found")
    cps = int(p.opts.get("clip_count") or 5)
    weak = len(ready) < max(1, math.ceil(cps / 2))
    report = p.info.get("quality") or {}
    note = (f"{len(ready)} strong clip(s) of {report.get('evaluated', 0)} evaluated from {len(cands)} candidates"
            + ("; weak source: another source will be tried" if weak else ""))
    db.update("sources", src["id"], status="weak" if weak else "analyzed", clips_selected=len(ready),
              status_note=note, error="")
    state.event("source_analyzed", f"“{src['title'][:80]}”: {note}", "warning" if weak else "info",
                ref_type="source", ref_id=src["id"], clips=len(ready))
    for clip in ready:
        queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": src["id"]}, idem_key=f"package:{clip['id']}",
                      ref=("clip", clip["id"]), priority=job.row["priority"])
    queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}")
    return {"clips": len(ready), "weak": weak, "message": note}
