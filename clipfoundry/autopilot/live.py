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
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .. import config, db, gpu, locks, netguard
from ..pipeline import candidates as cand_mod
from ..pipeline import blueprint, deep, hooks, postpack, process, render, scoring, transcribe, virality
from ..pipeline.audio import Loudness, loudness_envelope
from ..pipeline.common import JobContext, log, read_json, write_json
from ..pipeline.ffmpeg_utils import NO_WINDOW, extract_audio, ffmpeg_bin, probe
from ..pipeline.text_utils import build_sentences
from . import queue, rights, state
from .host import Job, handler
from .stream_access import StreamRefused
from .hunter import (gpu_failed, gpu_policy, max_source_bytes, plan_clips, prior_fingerprints, project_options,
                     render_in_priority_order, store_fingerprint)

SEGMENT_SECONDS = 60
WINDOW_SECONDS = 900          # the rolling window searched for live clips
EDGE_MARGIN = 15.0            # a live clip must have ended this long before the live edge
STALL_SECONDS = 90            # no new data this long: the stream or recording has ended
REPLACE_MARGIN = 3.0          # a post-live clip replaces a live clip only if clearly better
TURN_SECONDS = 2.0             # release the monitor between safe processing steps; captures keep recording


class StreamEnded(Exception):
    """The platform confirmed this broadcast ended; finalize any previously captured minutes."""


# ------------------------------------------------------------------ inputs
def input_args(src: dict, settings: dict, public_relays: list | None = None,
               byte_budget: int | None = None, on_retry=None) -> list[str]:
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
    try:  # network protocols only, and no private or local addresses unless you typed the address yourself
        if rights.is_platform_url(url):
            ok, why = rights.download_allowed(src, settings)
            if not ok:
                raise queue.Fail(why, "Allow downloads of authorized sources in Settings, or record the stream "
                                      "yourself into a watch folder.")
            url = _resolve_platform_stream(url)
        public = not rights.url_typed_by_user(src) or rights.is_platform_url(src.get("url") or "")
        if src.get("user_added") and urlsplit(url).scheme.lower() not in netguard.HTTP:
            raise queue.Fail("This public stream format cannot be accessed safely. Use a public HTTP stream link "
                             "or add your own local recording.")
        if public and public_relays is not None and urlsplit(url).scheme.lower() in netguard.HTTP:
            from .stream_access import PublicStream

            relay = PublicStream(url, max_bytes=byte_budget if byte_budget is not None else max_source_bytes(settings),
                                 on_retry=on_retry)
            public_relays.append(relay)
            return [*timeout, "-protocol_whitelist", "http,tcp,crypto", "-i", relay.url]
        return [*timeout, *netguard.ffmpeg_input(url, allow_private=not public)]
    except (netguard.UnsafeUrl, StreamRefused) as exc:
        raise queue.Fail(f"Not captured: {exc}", "Use a stream address on the internet, or add your own stream "
                                                 "in Autopilot → Sources.") from exc


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
        if info.get("live_status") in ("was_live", "post_live") or info.get("was_live"):
            raise StreamEnded()
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
        # One atomic checkpoint owns both the timeline and words. Separate convenience files can lag after a crash.
        self.transcript = st.get("transcript") or self.transcript
        self.capture_complete = bool(st.get("capture_complete"))
        self.limit_reached = bool(st.get("limit_reached"))
        # A crash after the database render commit but before this checkpoint must not rediscover the same moment.
        known = {c["id"] for c in self.clips}
        for clip in db.list_clips(project["id"]):
            if clip["id"] not in known and clip.get("score_source") == "Live analysis" and \
                    clip["status"] == "ready" and Path(clip.get("output_path") or "").is_file():
                self.clips.append({"id": clip["id"], "start": clip["start"], "end": clip["end"],
                                   "score": clip.get("score") or 0})
        self.words = transcribe.flatten_words(self.transcript)
        self.save()

    @property
    def listfile(self) -> Path:
        return self.segdir / f"run{self.run}.csv"

    def save(self) -> None:
        write_json(self.segdir / "state.json", {"run": self.run, "segments": self.segments, "offset": self.offset,
                                                "env": self.env, "clips": self.clips, "meta": self.meta,
                                                "untranscribed": self.untranscribed, "transcript": self.transcript,
                                                "capture_complete": self.capture_complete,
                                                "limit_reached": self.limit_reached})
        write_json(self.pdir / "transcript.json", {**self.transcript, "duration": self.offset})
        write_json(self.pdir / "loudness.json", {"hop": 0.1, "db": self.env})

    def done_names(self) -> set[str]:
        return {s["name"] for s in self.segments}


def capture_command(sess: Session, args: list[str]) -> list[str]:
    # Output seeking discards everything before the saved local timeline instead of copying earlier keyframes.
    # Include completed-but-unprocessed CSV rows so a restart cannot record those minutes a second time.
    recorded = sess.offset + sum(d for _, d in finished_segments(sess))
    seek = ["-ss", f"{recorded:.6f}"] if sess.src.get("local_path") and recorded > 0 else []
    limit = float(sess.settings.get("autopilot_max_source_minutes") or 240) * 60
    duration = ["-t", f"{max(0.001, limit - recorded):.6f}"]
    return [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", *args, *seek,
            *duration, "-map", "0:v:0?", "-map", "0:a:0?",
            "-c", "copy", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), "-reset_timestamps", "1",
            "-segment_list", str(sess.listfile), "-segment_list_type", "csv",
            str(sess.segdir / f"r{sess.run:03d}_%05d.mkv")]


def finished_segments(sess: Session) -> list[tuple[str, float]]:
    """(file name, duration) of segments ffmpeg has finished writing and that were not processed yet."""
    out = []
    try:
        lists = sorted(sess.segdir.glob("run*.csv"), key=lambda p: int(p.stem.removeprefix("run")))
        done = sess.done_names()
        for listing in lists:
            with open(listing, newline="", encoding="utf-8") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 3 and Path(row[0]).name == row[0] and row[0] not in done:
                        try:
                            duration = max(0.0, float(row[2]) - float(row[1]))
                        except ValueError:
                            continue  # a concurrent write's unfinished row is retried on the next turn
                        out.append((row[0], duration))
                        done.add(row[0])
    except OSError:
        pass
    return out


class Capture:
    """Recording outlives a short queue turn, while its parent pipe makes crashes stop it safely."""

    def __init__(self, sess: Session, job: Job, args: list[str], relays: list | None = None):
        self.sess = sess
        self.job_id = job.id
        self.host = job.host
        self.started = time.monotonic()
        self.stopped_reason = ""
        self.stopped = threading.Event()
        self._close_lock = threading.Lock()
        self.relays = relays or []
        self.error_path = sess.segdir / f"run{sess.run}.log"
        # Desktop launchers and sandboxes may import the app by extending sys.path from a different cwd. The
        # child needs that same package root, while retaining cwd for ffmpeg's relative file/executable paths.
        package_root = str(Path(__file__).resolve().parents[2])
        python_path = os.pathsep.join(p for p in (package_root, os.environ.get("PYTHONPATH", "")) if p)
        child_env = {**os.environ, "PYTHONPATH": python_path}
        with open(self.error_path, "wb") as err:
            self.proc = subprocess.Popen([sys.executable, "-m", "clipfoundry.autopilot.live", "--capture",
                                          sess.src["id"]], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=err, creationflags=NO_WINDOW, env=child_env)
        try:
            self.proc.stdin.write((json.dumps(capture_command(sess, args)) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except BaseException:
            self.stop()
            raise
        if self.host is not None:
            threading.Thread(target=self._watch, daemon=True, name=f"cf-live-{sess.src['id'][:8]}").start()

    def stop(self, reason: str = "") -> None:
        with self._close_lock:
            self.stopped_reason = self.stopped_reason or reason
            self.stopped.set()
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()  # EOF tells the lock-owning wrapper to finish and reap ffmpeg
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # Keep the source lock until the child really stops; another capture must not overlap it.
                log.error("live recording did not stop promptly: %s", self.sess.src["id"])
            for relay in self.relays:
                relay.close()

    def _watch(self) -> None:
        while not self.stopped.wait(1.0):
            if self.proc.poll() is not None:
                return
            try:
                row = queue.get(self.job_id)
                settings = db.get_settings()
                src = db.fetch("sources", self.sess.src["id"])
                if self.host._stop.is_set():
                    self.stop("restart")
                    return
                if state.paused() or (row and (row.get("cancel_requested") or row["status"] == "canceled")):
                    self.stop("canceled")
                    if src:
                        db.update("sources", src["id"], status="canceled", status_note="Canceled by you")
                    return
                if row is None or row["status"] in queue.TERMINAL:
                    self.stop("canceled")
                    return
                if not state.enabled(settings) and int((row or {}).get("priority") or 0) < 100:
                    self.stop("paused")
                    if src:
                        db.update("sources", src["id"], status="queued", status_note="Recording paused")
                    return
                ok, why = capture_allowed(src, settings) if src else (False, "The live source was removed")
                if not ok:
                    self.stop(why)
                    return
                if _recorded_bytes(self.sess) >= max_source_bytes(settings):
                    self.stop("limit")
                    return
            except Exception:  # a database read failure must never leave an unattended recorder running
                log.exception("could not check live recording permission")
                self.stop("Recording stopped because its permission could not be checked")
                return

    def error(self) -> str:
        refused = next((relay.error() for relay in self.relays if relay.error()), "")
        if refused:
            return refused
        try:
            with open(self.error_path, "rb") as fh:
                fh.seek(max(0, self.error_path.stat().st_size - 800))
                return fh.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""


_captures: dict[tuple[str, str], Capture] = {}
_capture_lock = threading.Lock()


def _capture_key(source_id: str) -> tuple[str, str]:
    return str(config.data_dir()), source_id


def _recorded_bytes(sess: Session) -> int:
    return sum(p.stat().st_size for p in sess.segdir.glob("r*_*.mkv"))


def stop_captures(host=None) -> None:
    """Host shutdown also stops recorders whose queue jobs are waiting between turns."""
    with _capture_lock:
        captures = [c for c in _captures.values() if host is None or c.host is host]
    for capture in captures:
        capture.stop("restart")


def _capture_worker(source_id: str) -> int:
    """Internal subprocess: hold the source lock and stop ffmpeg on parent exit, including a hard crash."""
    lock = locks.named(f"live-capture-{source_id}")
    if not lock.acquire(timeout=0, poll=0.01):
        return 75
    proc = None
    parent_gone = threading.Event()
    try:
        cmd = json.loads(sys.stdin.buffer.readline())
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=sys.stderr, creationflags=NO_WINDOW)

        def watch_parent() -> None:
            # BufferedReader holds an interpreter lock while blocked, so its daemon thread can abort Python at
            # normal shutdown. Raw pipe reads release the GIL and remain safe when ffmpeg finishes first.
            while os.read(sys.stdin.fileno(), 65536):
                pass  # no more commands; EOF is the parent death/shutdown signal
            parent_gone.set()

        threading.Thread(target=watch_parent, daemon=True).start()
        while proc.poll() is None:
            if parent_gone.wait(0.2):
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        return proc.returncode
    finally:
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        lock.release()


# ------------------------------------------------------------------ per segment
def _check_local_permission(sess: Session) -> None:
    src = db.fetch("sources", sess.src["id"])
    if not src:
        raise queue.Fail("The live source was deleted")
    if (src.get("intake") or {}).get("canceled") or (src.get("intake") or {}).get("removed"):
        raise queue.Canceled()
    r = rights.recheck(src, db.get_settings())
    if not rights.local_allowed(src, r):
        raise queue.Fail(f"Not used: {r['label']} ({r['basis']})")


def process_segment(sess: Session, name: str, duration: float, job: Job) -> None:
    job.check()
    _check_local_permission(sess)
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
    job.check()
    _check_local_permission(sess)
    r, sents, loud = found["r"], found["sents"], found["loud"]
    bounds = deep.optimize_bounds(r, sents, loud, sess.offset)
    start, end = bounds["start"], bounds["end"]
    texts = [sents[k]["text"] for k in range(r["s0"], r["s1"] + 1)]
    hook, alts = hooks.heuristic_hooks(texts)
    all_sents = build_sentences(sess.words)
    post = postpack.generate(texts, hook, alts, hooks.categorize(" ".join(texts)), sess.settings,
                             scoring.document_frequencies(all_sents), max(1, len(all_sents)), use_ai=False)
    clip_id = hashlib.sha256(f"live:{sess.project['id']}:{start:.6f}:{end:.6f}".encode()).hexdigest()[:32]
    clip = db.get_clip(clip_id)
    if clip and clip["status"] == "ready" and Path(clip.get("output_path") or "").is_file():
        return _store_live_clip(sess, clip, r, job)
    clip = clip or db.create_clip(sess.project["id"], id=clip_id, rank=len(sess.clips),
                          start=start, end=end, title=post["title"],
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
    heard = blueprint.heard_fields(bp, sess.words, clip, sess.settings)  # weak middle parts cut out
    if heard:
        db.update_clip(clip["id"], **heard)
        clip = {**clip, **heard}
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
    return _store_live_clip(sess, clip, r, job)


def _store_live_clip(sess: Session, clip: dict, r: dict, job: Job) -> dict:
    start, end = clip["start"], clip["end"]
    sub = virality.summary(r)["subscores"]
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": r["viral_potential"], "retention": sub.get("retention"),
                              "source": sess.src.get("source_score"), "components": {"live": True},
                              "explanation": [f"Viral Potential {r['viral_potential']:.0f} (live analysis of the last "
                                              f"{WINDOW_SECONDS // 60} minutes)"]}, key="clip_id", replace=True)
    store_fingerprint(clip, sess.src)
    if not any(c["id"] == clip["id"] for c in sess.clips):
        sess.clips.append({"id": clip["id"], "start": start, "end": end, "score": r["viral_potential"]})
    sess.save()
    queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": sess.src["id"]}, idem_key=f"package:{clip['id']}",
                  ref=("clip", clip["id"]), priority=queue.source_priority(sess.src, job.row.get("priority") or 0))
    state.event("live_clip", f"Live clip from “{sess.src.get('title', '')[:60]}” at {start / 60:.1f} min "
                             f"(Viral Potential {r['viral_potential']:.0f})", ref_type="clip", ref_id=clip["id"])
    return clip


def _resume_live_outputs(sess: Session, job: Job) -> None:
    """Packaging may not have been queued when a completed render was interrupted by a crash."""
    for saved in sess.clips:
        clip = db.get_clip(saved["id"])
        if clip and clip["status"] == "ready" and Path(clip.get("output_path") or "").is_file():
            if not db.fetch("clip_fingerprints", clip["id"], "clip_id"):
                store_fingerprint(clip, sess.src)
            queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": sess.src["id"]},
                          idem_key=f"package:{clip['id']}", ref=("clip", clip["id"]),
                          priority=queue.source_priority(sess.src, job.row.get("priority") or 0))


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
    if not rights.local_allowed(src, r, settings):
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
        if src.get("live_status") == "ended" or (src.get("intake") or {}).get("canceled"):
            continue
        ok, why = capture_allowed(src, settings)
        if not ok:
            db.update("sources", src["id"], status_note=why)
            continue
        row = queue.enqueue("live_capture", {"source_id": src["id"]}, idem_key=f"live:{src['id']}",
                      ref=("source", src["id"]), timeout_s=24 * 3600, max_attempts=5,
                      priority=queue.source_priority(src), revive=False)
        if row["status"] not in queue.ACTIVE:
            continue
        db.update("sources", src["id"], status="ingesting", status_note="Live: capturing")
        started.append(src["id"])
    return {"started": started, "message": f"{len(started)} live source(s) started"}


@handler("live_capture")
def live_capture(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    if not src:
        raise queue.Fail("The live source was deleted")
    if (src.get("intake") or {}).get("canceled") or (src.get("intake") or {}).get("removed"):
        raise queue.Canceled()
    r = rights.recheck(src, settings)
    if not rights.local_allowed(src, r, settings):
        key = _capture_key(src["id"])
        with _capture_lock:
            capture = _captures.pop(key, None)
        if capture:
            capture.stop("Permission changed")
        db.update("sources", src["id"], status="blocked" if r["status"] == rights.BLOCKED else "needs_rights",
                  status_note=f"{r['label']}: {r['basis']}"[:300])
        return {"skipped": True, "message": f"Not used: {r['label']} ({r['basis']})"}
    ok, why = capture_allowed(src, settings)
    if not ok:
        with _capture_lock:
            capture = _captures.pop(_capture_key(src["id"]), None)
        if capture:
            capture.stop(why)
        db.update("sources", src["id"], status="needs_file", status_note=why[:300])
        raise queue.Fail(why)
    key = _capture_key(src["id"])
    with _capture_lock:
        capture = _captures.get(key)
        if capture and (capture.job_id != job.id or capture.stopped_reason in ("restart", "paused")):
            _captures.pop(key, None)
            old, capture = capture, None
        else:
            old = None
    if old:
        old.stop()
    if capture is None:
        # The parent pipe may still be finishing a recorder left by a hard crash. Never launch a second one.
        if locks.named(f"live-capture-{src['id']}").held_elsewhere():
            raise queue.Wait("recording", TURN_SECONDS, "Recovering the interrupted recording")
        sess = Session(src, settings)
        _resume_live_outputs(sess, job)
        retry_path = sess.segdir / "server-wait.json"
        retry_at = float((read_json(retry_path, {}) or {}).get("until") or 0)
        if retry_at > time.time():
            raise queue.Wait("server", retry_at - time.time(), "The video server asked to wait before recording")
        recorded = sess.offset + sum(d for _, d in finished_segments(sess))
        byte_budget = max_source_bytes(settings) - _recorded_bytes(sess)
        if recorded >= float(settings.get("autopilot_max_source_minutes") or 240) * 60 or byte_budget <= 0:
            src = {**src, "live_status": "ended"}
            sess.limit_reached = True
        if src.get("live_status") == "ended":
            pending = finished_segments(sess)
            for name, dur in pending[:1] if job.host is not None else pending:
                process_segment(sess, name, dur, job)
            if finished_segments(sess):
                raise queue.Wait("live", TURN_SECONDS, "Recovering the final recorded minutes")
            if not sess.segments:
                raise queue.Fail("The ended stream has no usable recording")
            sess.capture_complete = True
            sess.save()
        if not sess.capture_complete:
            relays = []
            try:
                args = input_args(src, settings, public_relays=relays, byte_budget=max(1, byte_budget),
                                  on_retry=lambda until: write_json(retry_path, {"until": until}))
            except StreamEnded:
                db.update("sources", src["id"], live_status="ended")
                raise queue.Wait("live", TURN_SECONDS, "Stream ended — recovering the full recording")
            except queue.Fail as exc:
                db.update("sources", src["id"], status="needs_file", status_note=str(exc)[:300])
                raise
            try:
                capture = Capture(sess, job, args, relays=relays)
            except BaseException:
                for relay in relays:
                    relay.close()
                raise
            with _capture_lock:
                _captures[key] = capture
            job.log("capture_started", "Recording a permitted live source", run=sess.run)
        else:
            return _finish_capture(sess, job)
    sess = capture.sess
    sess.src, sess.settings = src, settings
    _resume_live_outputs(sess, job)
    proc = capture.proc
    try:
        while True:
            job.check()
            if capture.stopped_reason == "canceled":
                raise queue.Canceled()
            if capture.stopped_reason and capture.stopped_reason not in ("restart", "paused", "limit"):
                raise queue.Fail(capture.stopped_reason)
            pending = finished_segments(sess)
            for name, dur in pending[:1] if job.host is not None else pending:
                job.progress(None, f"Live: transcribing minute {sess.offset / 60:.0f}", stage="live")
                process_segment(sess, name, dur, job)
                found = detect(sess, job)
                if found:
                    make_live_clip(sess, found, job)
            if job.host is not None and (proc.poll() is None or finished_segments(sess)):
                raise queue.Wait("live", TURN_SECONDS, "Watching live — listening for good moments")
            if proc.poll() is not None:
                if job.host is None:  # EOF can append the final CSV row between the earlier read and this poll
                    for name, dur in finished_segments(sess):
                        process_segment(sess, name, dur, job)
                        found = detect(sess, job)
                        if found:
                            make_live_clip(sess, found, job)
                break
            job.cancel_event.wait(2.0)
    except queue.Wait:
        raise  # the recorder owns the source lock and keeps writing while another stream gets a turn
    except BaseException:
        capture.stop("restart" if job.host and job.host._stop.is_set() else "canceled")
        with _capture_lock:
            _captures.pop(key, None)
        raise
    capture.stop()
    with _capture_lock:
        _captures.pop(key, None)
    if capture.stopped_reason in ("restart", "paused"):
        # The app closed or Autopilot was paused during this turn: the broadcast did not end. The next turn starts
        # a new recorder after the saved minutes, without using an attempt or finishing the recording here.
        raise queue.Wait(capture.stopped_reason, TURN_SECONDS, "Recording paused; it continues when Autopilot runs")
    err = capture.error()
    retry_at = float((read_json(sess.segdir / "server-wait.json", {}) or {}).get("until") or 0)
    if retry_at > time.time():
        raise queue.Wait("server", retry_at - time.time(), "The video server asked to wait before recording")
    relay_error = any(relay.error() for relay in getattr(capture, "relays", []))
    read_error = not src.get("local_path") and "Error during demuxing" in err
    if (proc.returncode or relay_error or read_error) and capture.stopped_reason != "limit":
        if proc.returncode == 75:
            raise queue.Wait("recording", TURN_SECONDS, "Recovering the interrupted recording")
        message = f"The live recording was interrupted. {err[:200]}".strip()
        db.update("sources", src["id"], status="ingesting", status_note=message[:300])
        if any(word in err for word in ("DASH", "Protected", "DRM", "safe public HTTP", "unsupported",
                                       "download size limit", "safe download limit")):
            db.update("sources", src["id"], status="needs_file", status_note=message[:300])
            raise queue.Fail(message)
        if int(job.row.get("attempts") or 0) >= int(job.row.get("max_attempts") or 3):
            db.update("sources", src["id"], status="error", status_note=message[:300])
        raise queue.Retry(message)
    if not sess.segments:
        message = "The live source ended without any usable recorded video"
        db.update("sources", src["id"], status="error", status_note=message)
        raise queue.Fail(message)
    sess.capture_complete = True
    sess.limit_reached = capture.stopped_reason == "limit" or sess.offset >= \
        float(settings.get("autopilot_max_source_minutes") or 240) * 60 - 0.1
    sess.save()
    return _finish_capture(sess, job)


def _finish_capture(sess: Session, job: Job) -> dict:
    src = sess.src
    finalize(sess)
    detail = "Recording limit reached" if sess.limit_reached else "Live ended"
    db.update("sources", src["id"], kind="live", live_status="stopped" if sess.limit_reached else "ended",
              status="analyzing", status_note=f"{detail} after {sess.offset / 60:.0f} min with "
              f"{len(sess.clips)} live clip(s); analyzing the full recording")
    queue.enqueue("post_live", {"source_id": src["id"], "project_id": sess.project["id"]},
                  idem_key=f"post_live:{src['id']}:{sess.project['id']}", ref=("source", src["id"]),
                  timeout_s=6 * 3600, priority=queue.source_priority(src, job.row.get("priority") or 0))
    state.event("live_ended", f"“{src.get('title', '')[:60]}” ended: {sess.offset / 60:.0f} min, "
                              f"{len(sess.clips)} live clip(s)", ref_type="source", ref_id=src["id"])
    return {"minutes": round(sess.offset / 60, 1), "live_clips": len(sess.clips),
            "message": f"Live capture ended after {sess.offset / 60:.0f} min"}


def _published(clip_id: str) -> bool:
    return bool(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND status IN "
                          "('publishing', 'reconciling', 'published')", (clip_id,))) or bool(db.scalar(
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
    if (src.get("intake") or {}).get("canceled") or (src.get("intake") or {}).get("removed"):
        return {"skipped": True, "message": "Canceled by you"}
    r = rights.recheck(src, settings)
    if not rights.local_allowed(src, r, settings):
        return {"skipped": True, "message": f"Not used: {r['label']} ({r['basis']})"}
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
    selection_path = live_state_path.parent / "post-live-selection.json"
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection = read_json(selection_path, None)
    if selection is None:
        cands = process.candidate_pool(p, ctx)
        chosen = process.evaluate_select(p, cands, ctx, prior=prior_fingerprints(p.id))
        live = [c for c in db.list_clips(p.id) if c["status"] in ("ready", "rendering", "queued")]
        keep: list[dict] = []
        replacements = {}
        for r in chosen:
            b = r.get("bounds") or {"start": r["start"], "end": r["end"]}
            over = [c for c in live if min(b["end"], c["end"]) - max(b["start"], c["start"]) >
                    0.3 * min(b["end"] - b["start"], c["end"] - c["start"])]
            if not over:
                keep.append(r)
                continue
            old = over[0]
            if _published(old["id"]) or r.get("clip_score", r["score"]) < (old.get("score") or 0) + REPLACE_MARGIN:
                continue
            replacements[str(len(keep))] = old["id"]
            live.remove(old)
            keep.append(r)
        cps = int(settings.get("autopilot_clips_per_source") or 5)
        keep = keep[:max(0, cps - len(live))] if len(live) + len(keep) > cps else keep
        selection = {"chosen": keep, "replacements": replacements}
        write_json(selection_path, selection)  # retry the exact selected moments, regardless of new fingerprints
    keep = selection["chosen"]
    rows = process.create_clips(p, keep, ctx, replace_existing=False, durable=True)
    planned = plan_clips(p, rows, keep, src["id"])
    fresh = db.fetch("sources", src["id"])
    if not fresh or not rights.local_allowed(fresh, settings=db.get_settings()):
        raise queue.Fail("The recording's content permission changed before rendering")
    if (fresh.get("intake") or {}).get("canceled") or (fresh.get("intake") or {}).get("removed"):
        raise queue.Canceled()
    render_in_priority_order(p, planned, ctx, job, src)
    replaced = 0
    for index, old_id in selection.get("replacements", {}).items():
        if int(index) >= len(rows):
            continue
        new = db.get_clip(rows[int(index)]["id"])
        old = db.get_clip(old_id)
        if not old or not new or new["status"] != "ready":
            continue  # a failed replacement must leave the usable live clip available
        if _published(old_id):
            if not _published(new["id"]):
                db.update_clip(new["id"], status="superseded", error="The original live clip was already published")
            continue
        if old["status"] != "superseded":
            r = keep[int(index)]
            supersede(old, f"Replaced by the post-live analysis: a better cut of the same moment "
                           f"({r.get('clip_score', r['score']):.0f} vs {old['score']:.0f})")
        replaced += 1
    added = [c for c in (db.get_clip(r["id"]) for r in rows) if c and c["status"] == "ready"]
    for clip in added:
        store_fingerprint(clip, src)
        queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": src["id"]},
                      idem_key=f"package:{clip['id']}", ref=("clip", clip["id"]),
                      priority=queue.source_priority(src, job.row.get("priority") or 0))
    total = sum(1 for c in db.list_clips(p.id) if c["status"] == "ready")
    db.update_project(p.id, status="ready", progress=1.0, stage="done", message=f"{total} clip(s) ready")
    db.update("sources", src["id"], status="analyzed" if total else "weak", clips_selected=total,
              status_note=f"Post-live: {len(added)} clip(s) added, {replaced} live clip(s) replaced by better cuts")
    return {"added": len(added), "replaced": replaced, "message": f"Post-live analysis: {len(added)} added, "
                                                                  f"{replaced} replaced"}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--capture":
        raise SystemExit("This module is an internal live recorder")
    raise SystemExit(_capture_worker(sys.argv[2]))
