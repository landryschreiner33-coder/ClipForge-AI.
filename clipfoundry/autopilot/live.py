"""Live Monitor: clip approved live sources while they run, then analyze the full recording afterwards.

Live clipping
    ffmpeg records the live source in one-minute segments (stream copy, no re-encoding): a recording that is still
    being written (OBS in a watch folder), a stream URL you may use (HLS/RTMP/SRT), or - only when the rights pass
    and downloads of authorized platform sources are allowed in Settings - a platform live stream. Each segment is
    transcribed as it completes (one heavy GPU job at a time), the last 15 minutes are searched for complete
    moments, and a moment that passes the quality bar and has finished being said becomes a clip right away.

Post-live analysis
    When the stream ends, the segments are joined into the full recording and analyzed like any other source (deep
    analysis, diversity). A better version of a live clip replaces it, but only if the live clip was not published
    or scheduled for publishing; moments that were missed live are added.

Everything is saved as it happens, so a restart continues the capture and keeps what was already found.
"""
from __future__ import annotations

import csv
import subprocess
import time
from pathlib import Path

from .. import config, db, gpu
from ..pipeline import candidates as cand_mod
from ..pipeline import blueprint, deep, hooks, postpack, process, render, scoring, transcribe, virality
from ..pipeline.audio import Loudness, loudness_envelope
from ..pipeline.common import JobContext, log, read_json, write_json
from ..pipeline.ffmpeg_utils import NO_WINDOW, extract_audio, ffmpeg_bin, probe
from ..pipeline.text_utils import build_sentences
from . import queue, rights, state
from .host import Job, handler
from .hunter import gpu_failed, gpu_policy, plan_clips, prior_fingerprints, project_options, store_fingerprint

SEGMENT_SECONDS = 60
WINDOW_SECONDS = 900          # the rolling window searched for live clips
EDGE_MARGIN = 15.0            # a live clip must have ended this long before the live edge
STALL_SECONDS = 90            # no new data this long: the stream or recording has ended
REPLACE_MARGIN = 3.0          # a post-live clip replaces a live clip only if clearly better


# ------------------------------------------------------------------ inputs
def input_args(src: dict, settings: dict) -> list[str]:
    """ffmpeg input arguments for a live source (raises queue.Fail when it may not be captured)."""
    timeout = ["-rw_timeout", str(STALL_SECONDS * 1_000_000)]
    if src.get("local_path"):
        path = Path(src["local_path"])
        if not path.exists():
            raise queue.Fail("The recording file no longer exists")
        return ["-follow", "1", *timeout, "-i", f"file:{path}"]
    url = src.get("url") or ""
    if not url:
        raise queue.Fail("The live source has no file or URL")
    if rights.is_platform_url(url):
        ok, why = rights.download_allowed(src, settings)
        if not ok:
            raise queue.Fail(why, "Allow downloads of authorized sources in Settings, or record the stream yourself "
                                  "into a watch folder.")
        return [*timeout, "-i", _resolve_platform_stream(url)]
    return [*timeout, "-i", url]


def _resolve_platform_stream(url: str) -> str:
    """The HLS address of a platform live stream (no logins, cookies or DRM)."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise queue.Fail("Capturing this live stream needs yt-dlp") from exc
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                           "allow_unplayable_formats": False}) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    if not info.get("is_live"):
        raise queue.Wait("offline", 300, "The stream is not live right now")
    fmts = [f for f in info.get("formats") or [] if "m3u8" in str(f.get("protocol", "")) and
            (f.get("height") or 0) <= 1080]
    if not fmts:
        raise queue.Fail("No live stream address was found")
    return max(fmts, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))["url"]


# ------------------------------------------------------------------ session state (on disk, survives restarts)
class Session:
    def __init__(self, src: dict, settings: dict):
        self.src = src
        self.settings = settings
        project = db.get_project(src.get("project_id") or "") if src.get("project_id") else None
        if project is None:
            project = db.create_project((src.get("title") or "Live")[:120], origin="live", source_id=src["id"],
                                        source_url=src.get("url", ""), status="processing",
                                        options=project_options(settings))
            db.update("sources", src["id"], project_id=project["id"])
        self.project = project
        self.pdir = config.projects_dir() / project["id"]
        self.segdir = self.pdir / "live"
        self.segdir.mkdir(parents=True, exist_ok=True)
        st = read_json(self.segdir / "state.json", {}) or {}
        self.run = int(st.get("run", 0)) + 1
        self.segments: list[dict] = st.get("segments", [])
        self.offset = float(st.get("offset", 0.0))
        self.env: list[float] = st.get("env", [])
        self.clips: list[dict] = st.get("clips", [])
        self.meta: dict = st.get("meta", {})
        self.untranscribed: list[list[float]] = st.get("untranscribed", [])  # strict GPU: minutes not transcribed
        self.transcript = read_json(self.pdir / "transcript.json", None) or {"language": "", "source": "live",
                                                                             "segments": []}
        self.words = transcribe.flatten_words(self.transcript)
        self.save()

    @property
    def listfile(self) -> Path:
        return self.segdir / f"run{self.run}.csv"

    def save(self) -> None:
        write_json(self.segdir / "state.json", {"run": self.run, "segments": self.segments, "offset": self.offset,
                                                "env": self.env, "clips": self.clips, "meta": self.meta,
                                                "untranscribed": self.untranscribed})
        write_json(self.pdir / "transcript.json", {**self.transcript, "duration": self.offset})
        write_json(self.pdir / "loudness.json", {"hop": 0.1, "db": self.env})

    def done_names(self) -> set[str]:
        return {s["name"] for s in self.segments}


def capture_command(sess: Session, args: list[str]) -> list[str]:
    return [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", *args, "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1",
            "-segment_list", str(sess.listfile), "-segment_list_type", "csv",
            str(sess.segdir / f"r{sess.run:03d}_%05d.mkv")]


def finished_segments(sess: Session) -> list[tuple[str, float]]:
    """(file name, duration) of segments ffmpeg has finished writing and that were not processed yet."""
    out = []
    try:
        with open(sess.listfile, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) >= 3 and row[0] not in sess.done_names():
                    out.append((row[0], max(0.0, float(row[2]) - float(row[1]))))
    except (OSError, ValueError):
        pass
    return out


# ------------------------------------------------------------------ per segment
def process_segment(sess: Session, name: str, duration: float, job: Job) -> None:
    path = sess.segdir / name
    if not sess.meta:
        sess.meta = probe(path)
    duration = duration or float(probe(path).get("duration") or 0)
    wav = sess.segdir / (Path(name).stem + ".wav")
    extract_audio(path, wav, duration, cancel=job.cancelled)
    env = loudness_envelope(wav)["db"]
    frames = int(round(duration / 0.1))
    env = (env + [env[-1] if env else -60.0] * frames)[:frames]
    ctx = JobContext(None, job.cancelled)
    try:
        with gpu.manager.heavy("live transcription", sess.src.get("title", "")[:80], job.id, job.cancelled,
                               max_wait_s=600):
            t = transcribe.transcribe(wav, duration, sess.settings, ctx, allow_cpu_fallback=bool(
                sess.settings.get("autopilot_allow_cpu_fallback")))
    except transcribe.GpuTranscriptionFailed as exc:
        # Strict GPU: live clipping pauses, the recording goes on. The post-live pass transcribes the whole
        # recording again (on the GPU) before it is analyzed, so nothing said in these minutes is lost.
        gpu_failed(exc, f"live “{sess.src.get('title', '')[:60]}”")
        sess.untranscribed.append([sess.offset, sess.offset + duration])
        t = {"segments": [], "language": "", "runtime": {}}
    gpu.manager.record_transcription(t.get("runtime") or {}, f"live: {sess.src.get('title', '')[:60]}")
    for seg in t.get("segments", []):
        shifted = {"start": seg["start"] + sess.offset, "end": seg["end"] + sess.offset, "text": seg.get("text", ""),
                   "words": [{**w, "start": w["start"] + sess.offset, "end": w["end"] + sess.offset}
                             for w in seg.get("words", [])]}
        sess.transcript["segments"].append(shifted)
    sess.transcript["language"] = sess.transcript.get("language") or t.get("language", "")
    sess.segments.append({"name": name, "start": sess.offset, "end": sess.offset + duration})
    sess.offset += duration
    sess.env += env
    sess.words = transcribe.flatten_words(sess.transcript)
    wav.unlink(missing_ok=True)
    sess.save()
    db.update_project(sess.project["id"], duration=sess.offset, message=f"Live: {sess.offset / 60:.0f} min recorded, "
                                                                        f"{len(sess.clips)} clip(s)")


def detect(sess: Session, job: Job) -> dict | None:
    """The best complete, strong moment in the rolling window that is not already a clip."""
    edge = sess.offset
    words = [w for w in sess.words if w["start"] >= edge - WINDOW_SECONDS]
    sents = build_sentences(words)
    if len(sents) < 3:
        return None
    opts = process._options(sess.project, sess.settings)  # noqa: SLF001 - the project's clip options
    loud = Loudness({"hop": 0.1, "db": sess.env})
    feats = cand_mod.sentence_features(sents, words)
    min_quality = float(sess.settings.get("autopilot_min_quality") or 0)
    best = None
    for c in cand_mod.find_candidates(words, sents, loud, opts, pool_size=12):
        job.check()
        if c["end"] > edge - EDGE_MARGIN:
            continue  # still being said
        if any(min(c["end"], k["end"]) - max(c["start"], k["start"]) > 0.15 * (c["end"] - c["start"])
               for k in sess.clips):
            continue
        r = max((virality.analyze(a, b, sents, feats, words, loud, opts)
                 for a, b in virality.variants(c["s0"], c["s1"], sents, opts, feats)), key=lambda x: x["raw"])
        if r["blocked"] or r["viral_potential"] < max(min_quality, float(opts.get("min_score", 50))) or \
                r["end"] > edge - EDGE_MARGIN:
            continue
        if best is None or r["viral_potential"] > best[0]["viral_potential"]:
            best = (r, sents, loud)
    return {"r": best[0], "sents": best[1], "loud": best[2]} if best else None


def _window_file(sess: Session, start: float, end: float) -> tuple[Path, float]:
    """The segments around [start, end] joined into one file (stream copy) and the time where it starts."""
    segs = [s for s in sess.segments if s["end"] > start - 3 and s["start"] < end + 3]
    listing = sess.segdir / "window.txt"
    listing.write_text("".join(f"file '{(sess.segdir / s['name']).as_posix()}'\n" for s in segs), encoding="utf-8")
    out = sess.segdir / "window.mkv"
    subprocess.run([ffmpeg_bin(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "concat", "-safe",
                    "0", "-i", str(listing), "-c", "copy", str(out)], check=True, capture_output=True,
                   creationflags=NO_WINDOW)
    return out, segs[0]["start"]


def make_live_clip(sess: Session, found: dict, job: Job) -> dict:
    r, sents, loud = found["r"], found["sents"], found["loud"]
    bounds = deep.optimize_bounds(r, sents, loud, sess.offset)
    start, end = bounds["start"], bounds["end"]
    texts = [sents[k]["text"] for k in range(r["s0"], r["s1"] + 1)]
    hook, alts = hooks.heuristic_hooks(texts)
    all_sents = build_sentences(sess.words)
    post = postpack.generate(texts, hook, alts, hooks.categorize(" ".join(texts)), sess.settings,
                             scoring.document_frequencies(all_sents), max(1, len(all_sents)), use_ai=False)
    clip = db.create_clip(sess.project["id"], rank=len(sess.clips), start=start, end=end, title=post["title"],
                          hook=hook, hooks_alt=alts, caption_text=" ".join(texts), hashtags=post["hashtags"],
                          category=hooks.categorize(" ".join(texts)), score=r["viral_potential"],
                          scores=virality.summary(r)["factors"], score_source="Live analysis",
                          reason=scoring.reason_text(r), analysis=virality.summary(r), post=post, edit={},
                          status="rendering", duration=round(end - start, 2))
    window, shift = _window_file(sess, start, end)
    meta = probe(window)
    proj = {**sess.project, "source_path": str(window), "dir": str(sess.pdir), "width": meta["width"],
            "height": meta["height"], "fps": meta["fps"], "duration": meta["duration"], "info": meta, "options": {}}
    shifted = [{**w, "start": w["start"] - shift, "end": w["end"] - shift} for w in sess.words
               if w["end"] > shift and w["start"] < shift + meta["duration"]]
    # Engagement Strategist: the plan in recording time, stored before rendering; rendered on the window's time line
    bp = blueprint.build(clip, sess.project, sess.words, sess.settings, source_id=sess.src["id"], selection=r,
                         video_path=str(window), video_offset=shift)
    issues = blueprint.validate(bp, sess.offset or None, sess.words)
    blueprint.save(bp, issues)
    if blueprint.errors(issues):
        db.update_clip(clip["id"], status="error",
                       error=("Plan rejected: " + "; ".join(blueprint.errors(issues)[:3]))[:500])
        return clip
    try:
        out = render.render_clip(proj, {**clip, "start": start - shift, "end": end - shift, "edit": {}}, shifted,
                                 sess.settings, JobContext(None, job.cancelled),
                                 blueprint=blueprint.shifted(bp, -shift))
        db.update_clip(clip["id"], status="ready", progress=1.0, error="", **out)
    except queue.Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - one failed render must not stop the live capture
        log.exception("live clip render failed")
        db.update_clip(clip["id"], status="error", error=str(exc)[:500])
        return clip
    clip = db.get_clip(clip["id"]) or clip
    sub = virality.summary(r)["subscores"]
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": r["viral_potential"], "retention": sub.get("retention"),
                              "source": sess.src.get("source_score"), "components": {"live": True},
                              "explanation": [f"Viral Potential {r['viral_potential']:.0f} (live analysis of the last "
                                              f"{WINDOW_SECONDS // 60} minutes)"]}, key="clip_id", replace=True)
    store_fingerprint(clip, sess.src)
    sess.clips.append({"id": clip["id"], "start": start, "end": end, "score": r["viral_potential"]})
    sess.save()
    queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": sess.src["id"]}, idem_key=f"package:{clip['id']}",
                  ref=("clip", clip["id"]))
    state.event("live_clip", f"Live clip from “{sess.src.get('title', '')[:60]}” at {start / 60:.1f} min "
                             f"(Viral Potential {r['viral_potential']:.0f})", ref_type="clip", ref_id=clip["id"])
    return clip


def finalize(sess: Session) -> Path | None:
    """Join the segments into the full recording (stream copy)."""
    if not sess.segments:
        return None
    listing = sess.segdir / "all.txt"
    listing.write_text("".join(f"file '{(sess.segdir / s['name']).as_posix()}'\n" for s in sess.segments),
                       encoding="utf-8")
    out = sess.pdir / "source.mkv"
    subprocess.run([ffmpeg_bin(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "concat", "-safe",
                    "0", "-i", str(listing), "-c", "copy", str(out)], check=True, capture_output=True,
                   creationflags=NO_WINDOW)
    db.update_project(sess.project["id"], source_path=str(out), source_filename=out.name, duration=sess.offset)
    return out


# ------------------------------------------------------------------ jobs
def capture_allowed(src: dict, settings: dict) -> tuple[bool, str]:
    r = rights.evaluate(src, settings)
    if not r["auto_allowed"]:
        return False, f"{r['label']}: {r['explain']}"
    if src.get("local_path"):
        return Path(src["local_path"]).exists(), "Recording file"
    if rights.is_platform_url(src.get("url") or "") and not settings.get("rights_allow_remote_download"):
        return False, "Platform live stream: allow downloads of authorized sources in Settings to capture it"
    return bool(src.get("url")), "Stream URL"


@handler("live_watch")
def live_watch(job: Job) -> dict:
    settings = db.get_settings()
    if not settings.get("autopilot_live_monitoring"):
        return {"message": "Live monitoring is off"}
    started = []
    for src in db.select("sources", "kind = 'live' AND status IN ('eligible', 'needs_file')"):
        ok, why = capture_allowed(src, settings)
        if not ok:
            db.update("sources", src["id"], status_note=why)
            continue
        db.update("sources", src["id"], status="ingesting", status_note="Live: capturing")
        queue.enqueue("live_capture", {"source_id": src["id"]}, idem_key=f"live:{src['id']}",
                      ref=("source", src["id"]), timeout_s=24 * 3600, max_attempts=5)
        started.append(src["id"])
    return {"started": started, "message": f"{len(started)} live source(s) started"}


@handler("live_capture")
def live_capture(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    if not src:
        raise queue.Fail("The live source was deleted")
    rights.gate(src, "ingest", settings)
    sess = Session(src, settings)
    args = input_args(src, settings)
    cmd = capture_command(sess, args)
    job.log("capture_started", " ".join(cmd[:12]) + " ...", run=sess.run)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
    t0 = time.monotonic()
    try:
        while True:
            if job.cancelled():
                raise queue.Canceled()
            for name, dur in finished_segments(sess):
                job.progress(None, f"Live: transcribing minute {sess.offset / 60:.0f}", stage="live")
                process_segment(sess, name, dur, job)
                found = detect(sess, job)
                if found:
                    make_live_clip(sess, found, job)
            if proc.poll() is not None:
                break
            job.cancel_event.wait(2.0)
        for name, dur in finished_segments(sess):  # the last segment is listed when ffmpeg exits
            process_segment(sess, name, dur, job)
            found = detect(sess, job)
            if found:
                make_live_clip(sess, found, job)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
    err = (proc.stderr.read().decode("utf-8", "replace") if proc.stderr else "")[-800:]
    if not sess.segments:
        if time.monotonic() - t0 < STALL_SECONDS + 30:
            raise queue.Wait("offline", 300, f"The live source is not available right now. {err.strip()[:200]}")
        raise queue.Retry(f"No video was received from the live source. {err.strip()[:300]}")
    finalize(sess)
    db.update("sources", src["id"], kind="live", live_status="ended", status="analyzing",
              status_note=f"Live ended after {sess.offset / 60:.0f} min with {len(sess.clips)} live clip(s); "
                          "analyzing the full recording")
    queue.enqueue("post_live", {"source_id": src["id"], "project_id": sess.project["id"]},
                  idem_key=f"post_live:{src['id']}:{sess.run}", ref=("source", src["id"]), timeout_s=6 * 3600)
    state.event("live_ended", f"“{src.get('title', '')[:60]}” ended: {sess.offset / 60:.0f} min, "
                              f"{len(sess.clips)} live clip(s)", ref_type="source", ref_id=src["id"])
    return {"minutes": round(sess.offset / 60, 1), "live_clips": len(sess.clips),
            "message": f"Live capture ended after {sess.offset / 60:.0f} min"}


def _published(clip_id: str) -> bool:
    return bool(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND status IN "
                          "('publishing', 'published')", (clip_id,))) or bool(db.scalar(
        "SELECT COUNT(*) FROM publications WHERE clip_id = ? AND status IN ('done', 'action_needed', 'uploading', "
        "'processing', 'queued')", (clip_id,)))


def supersede(clip: dict, reason: str) -> None:
    db.update_clip(clip["id"], status="superseded", error=reason)
    for item in db.select("scheduled_publications", "clip_id = ? AND status IN ('awaiting_approval', 'approved')",
                          (clip["id"],)):
        db.update("scheduled_publications", item["id"], status="replaced", status_note=reason,
                  audit=[*(item.get("audit") or []), {"at": time.time(), "event": "replaced", "detail": reason}])
    state.event("live_clip_replaced", reason, ref_type="clip", ref_id=clip["id"])


@handler("post_live")
def post_live(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    project_id = job.payload.get("project_id", "")
    if not src or not db.get_project(project_id):
        raise queue.Fail("The live source or its project is missing")
    ctx = job.pipeline_ctx(0.0, 1.0)
    live_state_path = config.projects_dir() / project_id / "live" / "state.json"
    live_state = read_json(live_state_path, {}) or {}
    if live_state.get("untranscribed"):  # parts were not transcribed live: transcribe the whole recording
        (live_state_path.parent.parent / "transcript.json").unlink(missing_ok=True)
    try:
        p = process.prepare(project_id, ctx, gpu_policy(settings, job))  # usually the live transcript: no Whisper
    except transcribe.GpuTranscriptionFailed as exc:
        raise gpu_failed(exc, f"post-live “{src.get('title', '')[:60]}”") from exc
    if p is None:
        raise queue.Fail("The recording could not be read")
    if live_state.get("untranscribed"):
        write_json(live_state_path, {**live_state, "untranscribed": []})
    cands = process.candidate_pool(p, ctx)
    chosen = process.evaluate_select(p, cands, ctx, prior=prior_fingerprints(p.id))
    live = [c for c in db.list_clips(p.id) if c["status"] in ("ready", "rendering", "queued")]
    keep: list[dict] = []
    replaced = 0
    for r in chosen:
        b = r.get("bounds") or {"start": r["start"], "end": r["end"]}
        over = [c for c in live if min(b["end"], c["end"]) - max(b["start"], c["start"]) >
                0.3 * min(b["end"] - b["start"], c["end"] - c["start"])]
        if not over:
            keep.append(r)
            continue
        old = over[0]
        if _published(old["id"]) or r.get("clip_score", r["score"]) < (old.get("score") or 0) + REPLACE_MARGIN:
            continue  # the live clip stays (already out, or not clearly worse)
        supersede(old, f"Replaced by the post-live analysis: a better cut of the same moment "
                       f"({r.get('clip_score', r['score']):.0f} vs {old['score']:.0f})")
        live.remove(old)
        keep.append(r)
        replaced += 1
    cps = int(settings.get("autopilot_clips_per_source") or 5)
    keep = keep[:max(0, cps - len(live))] if len(live) + len(keep) > cps else keep
    rows = process.create_clips(p, keep, ctx, replace_existing=False)
    process.render_clips(p, plan_clips(p, rows, keep, src["id"]), ctx, lo=0.6, hi_total=0.95)
    added = [c for c in (db.get_clip(r["id"]) for r in rows) if c and c["status"] == "ready"]
    for clip in added:
        store_fingerprint(clip, src)
        queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": src["id"]},
                      idem_key=f"package:{clip['id']}", ref=("clip", clip["id"]))
    total = sum(1 for c in db.list_clips(p.id) if c["status"] == "ready")
    db.update_project(p.id, status="ready", progress=1.0, stage="done", message=f"{total} clip(s) ready")
    db.update("sources", src["id"], status="analyzed" if total else "weak", clips_selected=total,
              status_note=f"Post-live: {len(added)} clip(s) added, {replaced} live clip(s) replaced by better cuts")
    return {"added": len(added), "replaced": replaced, "message": f"Post-live analysis: {len(added)} added, "
                                                                  f"{replaced} replaced"}
