"""Live Monitor: clip approved live sources while they run, then analyze the full recording afterwards.

Live clipping
    ffmpeg records the live source in one-minute segments (stream copy, no re-encoding): a recording that is still
    being written (OBS in a watch folder), a stream URL you may use (HLS/RTMP/SRT), or - only when the rights pass
    and downloads of authorized platform sources are allowed in Settings - a platform live stream. Each segment is
    transcribed as it completes (one heavy GPU job at a time), the last 15 minutes are searched for complete
    moments, and the strongest one becomes a clip when it is strong enough for this stream and the stream's pace
    allows a clip now (quality over quantity: live_pick.py). Each stream has its own choices: how picky it is and
    how its clips are framed (split view when a face cam is found).

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

import numpy as np

from .. import config, db, gpu, locks, netguard
from ..pipeline import candidates as cand_mod
from ..pipeline import blueprint, deep, ears, hooks, postpack, process, render, scoring, semantic, transcribe, virality
from ..pipeline.audio import Loudness, loudness_envelope, read_samples
from ..pipeline.common import JobContext, log, read_json, write_json
from ..pipeline.ffmpeg_utils import NO_WINDOW, extract_audio, ffmpeg_bin, ffprobe_bin, probe, run_process
from ..pipeline.text_utils import build_sentences
from . import live_pick, queue, rights, state
from .host import Job, handler
from .stream_access import StreamRefused
from .hunter import (gpu_failed, gpu_policy, max_source_bytes, plan_clips, prior_fingerprints, project_options,
                     render_in_priority_order, require_disk_space, screen_stories, store_fingerprint)

SEGMENT_SECONDS = 60
WINDOW_SECONDS = 900          # the rolling window searched for live clips
EDGE_MARGIN = 15.0            # a live clip must have ended this long before the live edge
STALL_SECONDS = 90            # no new data this long: the stream or recording has ended
REPLACE_MARGIN = 3.0          # a post-live clip replaces a live clip only if clearly better
TURN_SECONDS = 2.0             # release the monitor between safe processing steps; captures keep recording
ARCHIVE_MAX_ATTEMPTS = 8       # an ended broadcast's public recording may take time to become available
ARCHIVE_MAX_WAIT_SECONDS = 6 * 3600
GPU_WAIT_SECONDS = 45          # a live minute waits this long for the GPU, then the turn is given to another stream
OFFLINE_GRACE_SECONDS = 300    # a channel that went offline mid-stream may come back (a dropped connection)


class StreamEnded(Exception):
    """The platform confirmed this broadcast ended; finalize any previously captured minutes."""


class StreamOffline(Exception):
    """The channel is not live right now (not started yet, or gone offline)."""


# ------------------------------------------------------------------ inputs
def input_args(src: dict, settings: dict, public_relays: list | None = None,
               byte_budget: int | None = None, on_retry=None, broadcast: dict | None = None) -> list[str]:
    """ffmpeg input arguments for a live source (raises queue.Fail when it may not be captured). For a platform
    stream, `broadcast` receives which broadcast the link points to right now."""
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
        if rights.is_platform_url(url) or (src.get("access") or {}).get("webpage"):
            ok, why = rights.download_allowed(src, settings)
            if not ok:
                raise queue.Fail(why, "Allow downloads of authorized sources in Settings, or record the stream "
                                      "yourself into a watch folder.")
            resolved = _resolve_platform_stream(url, seen=broadcast)
            url, audio_url = resolved if isinstance(resolved, tuple) else (resolved, None)
        else:
            audio_url = None
        public = not rights.url_typed_by_user(src) or rights.is_platform_url(src.get("url") or "")
        if src.get("user_added") and urlsplit(url).scheme.lower() not in netguard.HTTP:
            raise queue.Fail("This public stream format cannot be accessed safely. Use a public HTTP stream link "
                             "or add your own local recording.")
        if public and public_relays is not None and urlsplit(url).scheme.lower() in netguard.HTTP:
            from .stream_access import PublicStream

            relay = PublicStream(url, max_bytes=byte_budget if byte_budget is not None else max_source_bytes(settings),
                                 on_retry=on_retry, audio_url=audio_url)
            public_relays.append(relay)
            return [*timeout, "-protocol_whitelist", "http,tcp,crypto", "-i", relay.url]
        if audio_url:
            raise queue.Fail("Separate live video and audio require the guarded stream relay.")
        return [*timeout, *netguard.ffmpeg_input(url, allow_private=not public)]
    except (netguard.UnsafeUrl, StreamRefused) as exc:
        raise queue.Fail(f"Not captured: {exc}", "Use a stream address on the internet, or add your own stream "
                                                 "in Autopilot → Sources.") from exc


def _resolve_platform_stream(url: str, seen: dict | None = None) -> str | tuple[str, str]:
    """One combined HLS rendition or a synchronized video/audio pair; no logins, cookies or DRM."""
    from ..media_import import public_extractor, unavailable

    try:
        with public_extractor() as ydl:
            info = ydl.extract_info(url, download=False) or {}
    except (netguard.UnsafeUrl, queue.Wait):
        raise
    except Exception as exc:
        error = unavailable(exc)
        if error.code == "not_live":
            raise StreamOffline() from None
        if error.retry_after is not None:
            raise queue.Wait("server", error.retry_after, str(error)) from None
        if error.temporary:
            raise queue.Retry(str(error), error.fix) from None
        raise queue.Fail(str(error), error.fix) from None
    if not isinstance(info, dict) or info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
        raise queue.Fail("Use a link to one live video, rather than a playlist or channel.")
    if info.get("has_drm"):
        raise queue.Fail("Protected or DRM streams cannot be captured.")
    if not info.get("is_live"):
        if info.get("live_status") in ("was_live", "post_live") or info.get("was_live"):
            raise StreamEnded()
        raise StreamOffline()
    if seen is not None:
        seen.update({"id": str(info.get("id") or ""), "title": str(info.get("title") or "")[:200],
                     "url": str(info.get("webpage_url") or "")[:2000]})
    fmts = [f for f in info.get("formats") or [] if "m3u8" in str(f.get("protocol", "")) and
            (f.get("height") or 0) <= 1080 and not f.get("has_drm") and f.get("url")]
    if not fmts:
        raise queue.Fail("No live stream address was found")
    video = lambda f: f.get("vcodec") not in (None, "none")
    audio = lambda f: f.get("acodec") not in (None, "none")
    usable = [f for f in fmts if audio(f) and video(f)]
    if usable:
        return max(usable, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))["url"]
    videos = [f for f in fmts if video(f)]
    audios = [f for f in fmts if audio(f) and not video(f)]
    if videos and audios:
        picture = max(videos, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
        # Prefer the original/default language before bitrate, rather than unexpectedly recording a dub.
        sound = max(audios, key=lambda f: (bool(f.get("language") and f.get("language") == info.get("language")),
                                           f.get("language_preference") or 0, f.get("abr") or f.get("tbr") or 0))
        return picture["url"], sound["url"]
    raise queue.Fail("The live stream has no usable video and audio renditions.",
                     "Use a stream with sound or add your own recording; no transcription was attempted.")


# ------------------------------------------------------------------ session state (on disk, survives restarts)
class Session:
    def __init__(self, src: dict, settings: dict):
        self.src = src
        self.settings = settings
        project = db.get_project(src.get("project_id") or "") if src.get("project_id") else None
        if project is None:
            project = db.create_project((src.get("title") or "Live")[:120], origin="live", source_id=src["id"],
                                        source_url=src.get("url", ""), status="processing",
                                        options={**project_options(settings), **live_pick.choices(src, settings)})
            db.update("sources", src["id"], project_id=project["id"])
        elif "live_framing" not in (project.get("options") or {}):
            # A stream that was being recorded before streams had their own framing choice: it goes on with the
            # layout from Settings as it started (its card says No split view), not with a split view mid-stream.
            db.update_project(project["id"], options={**(project.get("options") or {}), "live_framing": "off",
                                                      "split_view": "off"})
            project = db.get_project(project["id"]) or project
        from . import submissions

        try:
            # A live input submitted with "Make & upload" covers the clips of this one recording project.
            submissions.bind_live(src, project)
        except ValueError as exc:
            raise queue.Fail(str(exc), "Add the stream again as a new live input.") from exc
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
        self.missing_audio: list[list[float]] = st.get("missing_audio", [])
        # Minute files FFmpeg cannot open. Joining skips them but keeps their time, so later times still line up.
        self.unreadable: list[str] = st.get("unreadable", [])
        self.transcript = read_json(self.pdir / "transcript.json", None) or {"language": "", "source": "live",
                                                                             "segments": []}
        # One atomic checkpoint owns both the timeline and words. Separate convenience files can lag after a crash.
        self.transcript = st.get("transcript") or self.transcript
        self.capture_complete = bool(st.get("capture_complete"))
        self.limit_reached = bool(st.get("limit_reached"))
        self.archive_recovery: dict = st.get("archive_recovery") or {}
        # Moments whose plan or render failed are not tried again on every later minute of the stream.
        self.skipped: list[list[float]] = st.get("skipped", [])
        self.stopped_by_owner = bool(st.get("stopped_by_owner"))
        self.offline_since = float(st.get("offline_since") or 0)
        # Which broadcast a channel link was recording, and when a recorder last ran (wall clock). A channel's
        # later broadcast is never appended to this recording or covered by this input's upload request.
        self.broadcast: dict = st.get("broadcast") or {}
        self.alive_at = float(st.get("alive_at") or 0)
        self.final: dict = st.get("final") or {}
        # The best score heard in each recorded minute: the stream's own measure of what a strong moment is.
        self.minute_best: dict[str, float] = st.get("minute_best") or {}
        # Strong moments of the last search that are not clips yet, the one waited for first (live_pick.keep).
        self.held: list[dict] = st.get("held") or []
        self.note: str = st.get("note") or ""  # why no clip is being made right now, in plain words
        self.voices: dict[tuple[float, float], dict | None] = {}  # this run's voice readings, by moment
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
                                                "missing_audio": self.missing_audio, "unreadable": self.unreadable,
                                                "capture_complete": self.capture_complete,
                                                "archive_recovery": self.archive_recovery,
                                                "limit_reached": self.limit_reached, "skipped": self.skipped,
                                                "stopped_by_owner": self.stopped_by_owner,
                                                "offline_since": self.offline_since, "broadcast": self.broadcast,
                                                "alive_at": self.alive_at, "final": self.final,
                                                "minute_best": self.minute_best, "held": self.held,
                                                "note": self.note})
        if not self.archive_recovery.get("complete"):
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
        self.stopped_at = 0.0  # wall clock of the first stop: a hold (pause, closing, disk) knows it was live until then
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
            self.stopped_at = self.stopped_at or time.time()
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
                if state.paused():
                    # Stop all jobs holds work: the recording is not canceled, and Resume continues it.
                    self.stop("paused")
                    if src:
                        db.update("sources", src["id"], status="queued", status_note="Recording paused by Stop all jobs")
                    return
                if row and (row.get("cancel_requested") or row["status"] == "canceled") and \
                        row.get("wait_reason") == queue.STOP_ALL:
                    # Stop all jobs, even when Resume was pressed before this turn ended: a hold, not a cancel.
                    # The turn ends held and the supervisor continues it after Resume with the saved minutes.
                    self.stop("paused")
                    if src:
                        db.update("sources", src["id"], status="queued",
                                  status_note="Recording paused by Stop all jobs")
                    return
                if row and (row.get("cancel_requested") or row["status"] == "canceled"):
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
                if _recorded_bytes(self.sess) >= max_source_bytes(settings) or _relay_limit(getattr(self, "relays", [])):
                    self.stop("limit")
                    return
                if src and _finish_requested(src["id"]):
                    self.stop("finish")  # "Stop recording": keep everything and finish like an ended stream
                    return
                try:
                    require_disk_space(self.sess.segdir)
                except queue.Wait:
                    self.stop("disk")
                    if src:
                        db.update("sources", src["id"], status="ingesting",
                                  status_note="Recording paused for disk space; saved minutes are kept")
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
_starting: dict[tuple[str, str], int] = {}  # disk room a stream reserved while its recorder is being started
_capture_lock = threading.Lock()


def _capture_key(source_id: str) -> tuple[str, str]:
    return str(config.data_dir()), source_id


def _relay_limit(relays: list) -> bool:
    return any(getattr(relay, "reached_limit", lambda: False)() for relay in relays)


def _recorded_bytes(sess: Session) -> int:
    return sum(p.stat().st_size for p in sess.segdir.glob("r*_*.mkv"))


def stop_captures(host=None) -> None:
    """Host shutdown also stops recorders whose queue jobs are waiting between turns (all at once: each may take a
    few seconds to close its file cleanly)."""
    with _capture_lock:
        captures = [c for c in _captures.values() if host is None or c.host is host]
    stoppers = [threading.Thread(target=capture.stop, args=("restart",), daemon=True) for capture in captures]
    for stopper in stoppers:
        stopper.start()
    for stopper in stoppers:
        stopper.join(timeout=20)


def resume_held() -> int:
    """After Stop all jobs: continue the live inputs it held (recording, waiting for the stream, finishing, or
    analyzing the full recording). Their saved minutes are kept; a channel that moved on to another broadcast is
    finished, not continued."""
    resumed = 0
    for row in db.select("worker_jobs", "kind IN ('live_capture', 'identify_link', 'post_live') AND status = "
                         "'canceled' AND wait_reason = ?", (queue.STOP_ALL,), "updated_at DESC", 200):
        src = db.fetch("sources", (row.get("payload") or {}).get("source_id") or "") or {}
        meta = src.get("intake") or {}
        if not src or meta.get("canceled") or meta.get("removed") or not meta.get("submitted") or \
                not (src.get("kind") == "live" or meta.get("live_requested")):
            continue
        queue.enqueue(row["kind"], row.get("payload") or {}, idem_key=row["idem_key"], ref=(row["ref_type"], row["ref_id"]),
                      priority=int(row.get("priority") or 0), max_attempts=int(row.get("max_attempts") or 5),
                      timeout_s=float(row.get("timeout_s") or 3600))
        resumed += 1
    return resumed


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
    try:
        meta = probe(path, cancel=job.cancelled)  # audio may disappear or return between live segments
    except queue.Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - one unreadable minute must not stop the whole recording
        log.warning("live minute %s could not be read: %s", name, exc)
        meta = {"unreadable": True}
        if name not in sess.unreadable:
            sess.unreadable.append(name)  # saved with this minute's checkpoint below
    if not meta.get("unreadable") and (not sess.meta or meta.get("has_audio")):
        sess.meta = meta
    duration = duration or float(meta.get("duration") or 0)
    wav = _minute_sound(sess, {"name": name})
    frames = int(round(duration / 0.1))
    ctx = JobContext(None, job.cancelled)
    if not meta.get("unreadable") and meta.get("has_audio"):
        try:
            extract_audio(path, wav, duration, cancel=job.cancelled)
        except queue.Canceled:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("live minute %s audio could not be read: %s", name, exc)
            meta = {**meta, "unreadable": True}
    sound = "" if meta.get("unreadable") or not meta.get("has_audio") else _sound_of(path, job.cancelled)
    if meta.get("unreadable"):
        # Kept on the timeline; the analysis of the full recording after the stream transcribes it again.
        sess.untranscribed.append([sess.offset, sess.offset + duration])
        env = [-60.0] * frames
        t = {"segments": [], "language": ""}
        job.log("live_unreadable_minute", f"Live minute {sess.offset / 60:.0f} could not be read; recording continues",
                start=sess.offset, end=sess.offset + duration)
    elif not meta.get("has_audio"):
        sess.missing_audio.append([sess.offset, sess.offset + duration])
        env = [-60.0] * frames
        t = {"segments": [], "language": "", "source": "no_audio"}
        reason = f"Live minute {sess.offset / 60:.0f} has no audio track; saved video without transcription"
        job.log("live_missing_audio", reason, start=sess.offset, end=sess.offset + duration)
        db.update("sources", sess.src["id"], status_note=reason)
        state.action(f"media:audio:{sess.src['id']}", "media", "The live recording has missing audio", reason,
                     "Check the stream or OBS audio track. Recording continues; silent minutes are not sent to "
                     "Whisper.", level="warning", ref_type="source", ref_id=sess.src["id"])
    else:
        env = loudness_envelope(wav)["db"]
        env = (env + [env[-1] if env else -60.0] * frames)[:frames]
        try:
            with gpu.manager.heavy("live transcription", sess.src.get("title", "")[:80], job.id, job.cancelled,
                                   max_wait_s=GPU_WAIT_SECONDS):
                t = transcribe.transcribe(wav, duration, sess.settings, ctx, allow_cpu_fallback=bool(
                    sess.settings.get("autopilot_allow_cpu_fallback")))
        except gpu.GpuBusy as exc:
            # Another stream or a long video is using the GPU. This minute stays waiting and is transcribed on a
            # later turn; the recorder keeps recording, and another stream may use this turn meanwhile.
            wav.unlink(missing_ok=True)
            raise queue.Wait("gpu", 10, "Recording; waiting for the GPU to transcribe the next minute") from exc
        except transcribe.GpuTranscriptionFailed as exc:
            # Keep recording; the post-live pass transcribes these minutes with the same strict GPU policy.
            gpu_failed(exc, f"live “{sess.src.get('title', '')[:60]}”")
            sess.untranscribed.append([sess.offset, sess.offset + duration])
            t = {"segments": [], "language": "", "runtime": {}}
        if t.get("runtime"):
            gpu.manager.record_transcription(t["runtime"], f"live: {sess.src.get('title', '')[:60]}")
    for seg in t.get("segments", []):
        shifted = {"start": seg["start"] + sess.offset, "end": seg["end"] + sess.offset, "text": seg.get("text", ""),
                   "words": [{**w, "start": w["start"] + sess.offset, "end": w["end"] + sess.offset}
                             for w in seg.get("words", [])]}
        sess.transcript["segments"].append(shifted)
    sess.transcript["language"] = sess.transcript.get("language") or t.get("language", "")
    sess.segments.append({"name": name, "start": sess.offset, "end": sess.offset + duration,
                          **({"sound": sound} if sound else {})})
    sess.offset += duration
    sess.env += env
    sess.words = transcribe.flatten_words(sess.transcript)
    # The minute's sound stays while it is inside the rolling window: a moment's voice (pitch, emphasis, laughter)
    # is part of how strong it is. Older minutes' files go; the recording itself keeps their sound.
    for old in sess.segments:
        if old["end"] < sess.offset - WINDOW_SECONDS - SEGMENT_SECONDS:
            _minute_sound(sess, old).unlink(missing_ok=True)
    sess.save()
    message = (f"Live: {sess.offset / 60:.0f} min recorded, {len(sess.clips)} clip(s)"
               + ("; this minute has no audio" if not meta.get("has_audio") else ""))
    db.update_project(sess.project["id"], duration=sess.offset, message=message,
                      info={**(db.get_project(sess.project["id"]) or {}).get("info", {}), **sess.meta,
                            "missing_audio": sess.missing_audio})


def _sound_of(path: Path, cancel=None) -> str:
    """The minute's first sound track as "codec,sample rate,channels" ("" when unknown). A stream copy keeps the
    first minute's sound settings for the whole join, so a minute recorded with other settings (a reconnect can
    bring them) would play at the wrong speed there."""
    try:
        out = run_process([ffprobe_bin(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                           "stream=codec_name,sample_rate,channels", "-of", "csv=p=0", str(path)],
                          timeout=60.0, cancel=cancel)
    except queue.Canceled:
        raise
    except Exception:  # noqa: BLE001 - unknown settings only mean the join does not compare them
        return ""
    text = out.stdout.decode("utf-8", "replace") if isinstance(out.stdout, bytes) else (out.stdout or "")
    return text.strip().splitlines()[0].strip() if out.returncode == 0 and text.strip() else ""


def _minute_sound(sess: Session, seg: dict) -> Path:
    """The 16 kHz sound file of one recorded minute (kept only while the minute is in the rolling window)."""
    return sess.segdir / (Path(seg["name"]).stem + ".wav")


def _drop_minute_sounds(sess: Session) -> None:
    for seg in sess.segments:
        _minute_sound(sess, seg).unlink(missing_ok=True)


def _voice(sess: Session, start: float, end: float) -> dict | None:
    """How the voice sounds over a moment (ears.analyze: pitch, emphasis, laughter), from the minutes' kept sound
    files. None when a minute of it has no sound file (no audio, unreadable, or older than the window)."""
    key = (round(start, 2), round(end, 2))
    if key in sess.voices:
        return sess.voices[key]
    parts = []
    for seg in sess.segments:
        if seg["end"] <= start or seg["start"] >= end:
            continue
        try:
            parts.append(read_samples(_minute_sound(sess, seg), max(0.0, start - seg["start"]),
                                      min(seg["end"], end) - seg["start"]))
        except (OSError, ValueError, EOFError):
            parts = []
            break
    voice = None
    if parts:
        try:
            voice = ears.analyze(np.concatenate(parts), start,
                                 [w for w in sess.words if w["end"] > start and w["start"] < end])
        except Exception:  # noqa: BLE001 - the voice is a bonus; a moment is still rated by its words and loudness
            log.exception("live voice reading failed")
    if len(sess.voices) > 400:
        sess.voices.clear()
    sess.voices[key] = voice
    return voice


def detect(sess: Session, job: Job) -> dict | None:
    """The strongest complete moment in the rolling window that is not already a clip, when it is strong enough
    for this stream and the stream's pace allows a clip now (live_pick: quality over quantity)."""
    from . import knowledge
    from .scout import clip_reason

    pace = live_pick.pace(sess.project, sess.settings)
    edge = sess.offset
    words = [w for w in sess.words if w["start"] >= edge - WINDOW_SECONDS]
    sents = build_sentences(words)
    if len(sents) < 3:
        return _listening(sess, "nothing")
    opts = process._options(sess.project, sess.settings, words=words)  # noqa: SLF001 - the project's clip options
    loud = Loudness({"hop": 0.1, "db": sess.env})
    feats = cand_mod.sentence_features(sents, words)
    emb = semantic.embed_sentences(sents, opts)
    floor = max(float(sess.settings.get("autopilot_min_quality") or 0), float(opts.get("min_score", 50))) \
        + pace["above"]
    taken = [*sess.clips, *({"start": a, "end": b} for a, b in sess.skipped)]

    def shared(start: float, end: float) -> float:  # seconds of this stretch that a clip already shows
        return max((min(end, k["end"]) - max(start, k["start"]) for k in taken), default=0.0)

    def knowing(a: int, b: int) -> tuple[dict, list]:  # the options for these sentences, and what the Brain added
        local, used = knowledge.selection_options(
            {"title": sess.project.get("name") or "", "caption_text": " ".join(
                sentence["text"] for sentence in sents[a:b + 1])}, opts, sess.settings)
        if not any("target_duration" in item["decisions"] for item in used):
            used += opts.get("brain_duration_knowledge") or []
        return local, used

    rated: list[dict] = []
    for c in cand_mod.find_candidates(words, sents, loud, opts, pool_size=live_pick.POOL):
        job.check()
        if any(live_pick.overlaps(c, k) for k in taken):
            continue
        local, used = knowing(c["s0"], c["s1"])
        core = max((virality.analyze(a, b, sents, feats, words, loud, local)
                    for a, b in virality.variants(c["s0"], c["s1"], sents, local, feats)), key=lambda x: x["raw"])
        # ... and the same moment with its build-up and its ending, when that is about as strong (live_pick.fuller).
        # What is added must not show a clip's footage again: the moment as found may share a little with a clip
        # (OVERLAP of its length); a longer version may share that much and no more.
        allowed = max(1.0, shared(core["start"], core["end"]))
        wider = [(a, b) for a, b in live_pick.fuller(core["s0"], core["s1"], sents, feats, local)
                 if shared(sents[a]["start"], sents[b]["end"]) <= allowed]
        versions = [v for v in (core, *(virality.analyze(a, b, sents, feats, words, loud, local) for a, b in wider))
                    if not v["blocked"] and not clip_reason(v, sess.settings)]
        if not versions:
            continue
        # The first estimate names the few versions worth the full live rating; that rating decides between them.
        short = live_pick.ranked(versions, local)[:live_pick.FULL_RATE]
        short += [core] if core in versions and core not in short else []
        for v in short:
            v["live"] = live_pick.rate(v, sents, words, loud, emb)
        r = live_pick.ranked(short, local)[0]
        if r is not core and r["live"]["score"] < floor <= (core.get("live") or {"score": -1.0})["score"]:
            r = core  # the fuller version is not strong enough on its own: clip the moment as it was found
        if any((r["s0"], r["s1"]) == (other["s0"], other["s1"]) for other in rated):
            continue  # two moments found close together are the same story once each is told in full
        if r is not core:
            r["fuller"] = {"from": round(core["end"] - core["start"], 1), "to": round(r["end"] - r["start"], 1),
                           "core": [core["start"], core["end"]]}  # the moment as found, for the overlap rule
        r["brain_knowledge"] = used
        rated.append(r)
    # A minute later the search may cut the same speech differently. The moments remembered from the last search
    # (the one the picker waits for among them) are rated again as they were, so waiting never loses a moment.
    for kept in sess.held:
        job.check()
        core = (kept.get("fuller") or {}).get("core")
        if core and shared(kept["start"], kept["end"]) > max(1.0, shared(*core)):
            # A clip made since then shares more with the fuller version than with the moment itself: the same
            # rule as for a fresh search, so the moment is tried as it was found.
            kept = {"start": core[0], "end": core[1]}
        a = next((k for k, s in enumerate(sents) if abs(s["start"] - kept["start"]) < 0.05), None)
        b = next((k for k, s in enumerate(sents) if abs(s["end"] - kept["end"]) < 0.05), None)
        if a is None or b is None or b < a or any((a, b) == (other["s0"], other["s1"]) for other in rated) \
                or any(live_pick.overlaps(kept, k) for k in taken):
            continue  # no longer in the window, found again by the search, or a clip by now
        local, used = knowing(a, b)
        r = virality.analyze(a, b, sents, feats, words, loud, local)
        if r["blocked"] or clip_reason(r, sess.settings):
            continue
        r["live"] = live_pick.rate(r, sents, words, loud, emb)
        if kept.get("fuller"):
            r["fuller"] = kept["fuller"]
        r["brain_knowledge"] = used
        rated.append(r)
    # The voice is read for the few strongest only: it costs the most, and it can only decide between them.
    for r in sorted(rated, key=lambda item: item["live"]["score"], reverse=True)[:live_pick.VOICE_TOP]:
        job.check()
        voice = _voice(sess, r["start"], r["end"])
        if voice:
            r["live"] = live_pick.rate(r, sents, words, loud, emb, voice)
    for r in rated:
        r["live_score"], r["explanation"] = r["live"]["score"], [*r["live"]["why"], *(
            [f"Kept the build-up and the ending: {r['fuller']['to']:g} s instead of {r['fuller']['from']:g} s"]
            if r.get("fuller") else [])]
        if r["end"] <= edge - EDGE_MARGIN:  # a moment still being said is rated again when it is complete
            minute = str(int(r["start"] // SEGMENT_SECONDS))
            sess.minute_best[minute] = max(float(sess.minute_best.get(minute) or 0.0), r["live_score"])
    found, why, waited = live_pick.choose(rated, clips=sess.clips, edge=edge, unit=SEGMENT_SECONDS, floor=floor,
                                          pace=pace, minute_best=sess.minute_best, edge_margin=EDGE_MARGIN)
    sess.held = live_pick.keep(rated, found, waited, floor)
    _listening(sess, why)
    return {"r": found, "sents": sents, "loud": loud} if found else None


def _listening(sess: Session, why: str) -> None:
    """Remember, in plain words, why no clip is being made right now (shown with the stream)."""
    note = live_pick.NOTES.get(why, "")
    if note != sess.note:
        sess.note = note
        db.update_project(sess.project["id"], info={**(db.get_project(sess.project["id"]) or {}).get("info", {}),
                                                  "live_note": note})
    sess.save()  # with the minute's ratings
    return None


# FFmpeg's concat reader skips a file it cannot open and still exits successfully: the joined file is then shorter
# and every later moment is moved earlier. These lines in its log mean a file was skipped or cut short.
JOIN_ERRORS = ("Impossible to open", "Error during demuxing", "Error retrieving a packet")
KEPT = "The live clips made during the stream and their uploads are kept."


def _join_problem(result) -> str:
    err = result.stderr or ""
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    return next((line.strip() for line in err.splitlines() if any(word in line for word in JOIN_ERRORS)), "")


def _concat_listing(sess: Session, segs: list[dict], paths: list[Path]) -> str:
    """Concat reader lines for these minutes, without the ones that cannot be opened.

    Every minute is placed by its recorded length (the recorder's segment list), which is the live timeline the
    transcript and clips use. Left to itself FFmpeg places each file by its container length, which with stream
    copy runs some 40-70 ms past the cut, so a long recording would drift seconds away from its saved times. Each
    minute but the last also ends at its recorded length: media a file holds past it (audio after a stalled
    picture, encoder priming) would otherwise overlap the next minute, and FFmpeg squeezes the overlap without an
    error. A skipped minute keeps its place: the readable minute before it is declared long enough to cover it,
    and FFmpeg leaves a gap there."""
    bad = set(sess.unreadable)
    keep = [(seg, path) for seg, path in zip(segs, paths) if seg["name"] not in bad]
    lines = []
    for index, (seg, path) in enumerate(keep):
        quoted = path.as_posix().replace("'", "'\\''")  # the concat reader's quoting, as for filter paths
        last = index + 1 == len(keep)
        later = float(seg["end"]) if last else float(keep[index + 1][0]["start"])
        cut = "" if last else f"outpoint {float(seg['end']) - float(seg['start']):.6f}\n"
        lines.append(f"file '{quoted}'\nduration {later - float(seg['start']):.6f}\n{cut}")
    return "".join(lines)


def _opens(path: Path, cancel=None) -> bool:
    try:
        probe(path, cancel=cancel)
        return True
    except queue.Canceled:
        raise
    except Exception:  # noqa: BLE001 - only whether FFmpeg can open it matters here
        return False


def _window_file(sess: Session, start: float, end: float, *, cancel=None) -> tuple[Path, float]:
    """The segments around [start, end] joined into one file and the time where it starts (the full recording's
    join: a silent neighbour minute first must not drop the moment's sound)."""
    bad = set(sess.unreadable)
    segs = [s for s in sess.segments if s["end"] > start - 3 and s["start"] < end + 3]
    if any(s["name"] in bad and s["end"] > start and s["start"] < end for s in segs):
        raise ValueError("Part of this moment was recorded in a minute that could not be read")
    segs = [s for s in segs if s["name"] not in bad]  # a neighbour minute that cannot be read is left out
    if not segs:
        raise ValueError("The recorded minutes around this moment could not be read")
    first, last = (next(i for i, s in enumerate(sess.segments) if s["name"] == seg["name"])
                   for seg in (segs[0], segs[-1]))
    out = sess.segdir / "window.mkv"
    problem = _assemble(sess, segs, sess.segments[first:last + 1], out, cancel=cancel,
                        timeout=max(600.0, end - start), listing="window.txt", sounds="window-sound.txt",
                        audio="window-audio", assembled=sess.segdir / "window.tmp.mkv")
    if problem:
        raise ValueError(f"The recorded minutes around this moment could not be joined: {problem[:200]}")
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
    taught = _learned(sess)
    post = postpack.generate(texts, hook, alts, hooks.categorize(" ".join(texts)), {**sess.settings,
                                                                                    "learned": taught},
                             scoring.document_frequencies(all_sents), max(1, len(all_sents)), use_ai=False,
                             name=postpack.video_names(sess.project),
                             starts=[float(sents[k].get("start", start)) - start for k in range(r["s0"], r["s1"] + 1)])
    clip_id = hashlib.sha256(f"live:{sess.project['id']}:{start:.6f}:{end:.6f}".encode()).hexdigest()[:32]
    clip = db.get_clip(clip_id)
    if clip and clip["status"] == "ready" and Path(clip.get("output_path") or "").is_file():
        return _store_live_clip(sess, clip, r, job)
    clip = clip or db.create_clip(sess.project["id"], id=clip_id, rank=len(sess.clips),
                          start=start, end=end, title=post["title"],
                          hook=hook, hooks_alt=alts, caption_text=" ".join(texts), hashtags=post["hashtags"],
                          category=hooks.categorize(" ".join(texts)), score=_live_score(r),
                          scores=virality.summary(r)["factors"], score_source="Live analysis",
                          reason=scoring.reason_text(r), analysis=virality.summary(r), post=post,
                          edit=_learned_look(taught),
                          status="rendering", duration=round(end - start, 2))
    try:
        window, shift = _window_file(sess, start, end, cancel=job.cancelled)
        meta = probe(window, cancel=job.cancelled)
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
            _skip(sess, start, end)
            return clip
        heard = blueprint.heard_fields(bp, sess.words, clip, sess.settings)  # weak middle parts cut out
        if heard:
            db.update_clip(clip["id"], **heard)
            clip = {**clip, **heard}
        look = {k: v for k, v in (clip.get("edit") or {}).items() if k not in ("start", "end", "caption_words")}
        out = render.render_clip(proj, {**clip, "start": start - shift, "end": end - shift, "edit": look}, shifted,
                                 sess.settings, JobContext(None, job.cancelled),
                                 # the learned look over the plan, as for_render does for every other render
                                 blueprint=blueprint.shifted(blueprint.with_edit(bp, look, "edit") if look else bp,
                                                             -shift))
        db.update_clip(clip["id"], status="ready", progress=1.0, error="", **out)
    except (queue.Canceled, queue.Wait):
        raise
    except Exception as exc:  # noqa: BLE001 - one failed moment (a bad segment, a render) must not stop the capture
        log.exception("live clip failed")
        db.update_clip(clip["id"], status="error", error=str(exc)[:500])
        if not job.cancelled():
            _skip(sess, start, end)  # the full-recording analysis after the stream may still find this moment
        return clip
    clip = db.get_clip(clip["id"]) or clip
    return _store_live_clip(sess, clip, r, job)


def _learned(sess: Session) -> dict:
    """What your edits taught (Brain → Learned), checked before use; {} when learning is off."""
    from ..brain import learned

    try:
        return learned.defaults(str(sess.project.get("workspace_id") or "local"), sess.settings)
    except Exception:  # noqa: BLE001 - a live clip is made without it rather than not at all
        log.exception("could not read what was learned for a live clip")
        return {}


def _learned_look(taught: dict) -> dict:
    """How a live clip starts in the editor from what your edits taught: your captions and pacing. Its framing
    stays the stream's own (the face cam and gameplay view), and its start and end stay the live pick."""
    from ..brain import learned

    keys = set(learned.FIELDS["captions"]) | set(learned.FIELDS["pacing"])
    edit = {k: v for k, v in taught.items() if k in keys}
    if edit:
        edit["learned_keys"] = sorted(edit)
    return edit


def _skip(sess: Session, start: float, end: float) -> None:
    """The full-recording analysis after the stream may still find a better cut of this moment."""
    sess.skipped.append([start, end])
    sess.save()


def _live_score(r: dict) -> float:
    """The moment's Clip Score from the live analysis (its Viral Potential when it was not rated live)."""
    return float(r.get("live_score", r["viral_potential"]))


def _store_live_clip(sess: Session, clip: dict, r: dict, job: Job) -> dict:
    start, end = clip["start"], clip["end"]
    sub = virality.summary(r)["subscores"]
    score = _live_score(r)
    why = [str(line) for line in r.get("explanation") or [f"Viral Potential {r['viral_potential']:.0f}"]]
    pace = live_pick.pace(sess.project, sess.settings)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": score, "retention": sub.get("retention"),
                              "source": sess.src.get("source_score"),
                              "components": {"live": True, "pick": pace["name"],
                                             "viral_potential": r["viral_potential"],
                                             **({"lively": r["live"]["lively"]} if r.get("live") else {})},
                              "explanation": [*why, f"Live analysis of the last {WINDOW_SECONDS // 60} minutes "
                                                    f"(estimate). This stream keeps: {live_pick.LABELS[pace['name']]}"
                                              ]}, key="clip_id", replace=True)
    store_fingerprint(clip, sess.src)
    if not any(c["id"] == clip["id"] for c in sess.clips):
        sess.clips.append({"id": clip["id"], "start": start, "end": end, "score": score})
    sess.save()
    queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": sess.src["id"]},
                  idem_key=f"package:{clip['id']}",
                  ref=("clip", clip["id"]), priority=queue.source_priority(sess.src, job.row.get("priority") or 0))
    state.event("live_clip", f"Live clip from “{sess.src.get('title', '')[:60]}” at {start / 60:.1f} min "
                             f"(Clip Score {score:.0f}, live estimate)", ref_type="clip", ref_id=clip["id"])
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


def finalize(sess: Session, *, cancel=None) -> Path | None:
    """Join the recording without dropping audio that returns after a video-only segment.

    Normal recordings keep stream copy. Mixed recordings copy video and normalize only their audio tracks,
    inserting silence for known missing audio so later speech keeps its source timeline. A minute FFmpeg cannot
    open is left out with its time kept as a gap; a join that FFmpeg still cuts short is never used.
    """
    if not sess.segments:
        return None
    problem = ""
    for _ in range(3):
        problem = _join_recording(sess, cancel)
        if not problem:
            out = sess.pdir / "source.mkv"
            db.update_project(sess.project["id"], source_path=str(out), source_filename=out.name, duration=sess.offset)
            return out
        # Find the minutes FFmpeg cannot open now and join again without them.
        bad = [s["name"] for s in sess.segments if s["name"] not in sess.unreadable and
               not _opens(sess.segdir / s["name"], cancel)]
        if not bad:
            break
        for seg in sess.segments:
            if seg["name"] in bad:
                # Its live words and loudness describe a part the joined file no longer has: the full-recording
                # analysis transcribes again (the gap is silence there), and its loudness is silence.
                sess.untranscribed.append([seg["start"], seg["end"]])
                first, last = round(float(seg["start"]) / 0.1), round(float(seg["end"]) / 0.1)
                sess.env[first:last] = [-60.0] * len(sess.env[first:last])
        sess.unreadable += bad
        sess.save()
    raise queue.Fail(f"The recorded minutes could not be joined into one recording. {problem[:200]}".strip(), KEPT)


def _join_recording(sess: Session, cancel=None) -> str:
    """Write source.mkv from the readable minutes. Returns what went wrong, or "" when it was written."""
    bad = set(sess.unreadable)
    if sess.segments[0]["name"] in bad:
        # The joined file would start later than the live timeline, so no saved time would match it any more.
        raise queue.Fail("The first recorded minute could not be read, so the full recording cannot be lined up "
                         "with the live clips.", KEPT)
    segs = [s for s in sess.segments if s["name"] not in bad]
    return _assemble(sess, segs, sess.segments, sess.pdir / "source.mkv", cancel=cancel,
                     timeout=max(600.0, min(7200.0, sess.offset * 2)))


def _assemble(sess: Session, segs: list[dict], span: list[dict], out: Path, *, cancel=None, timeout: float,
              listing: str = "all.txt", sounds: str = "sound.txt", audio: str = "joined-audio",
              assembled: Path | None = None) -> str:
    """Join the readable minutes `segs` of the recorded minutes `span` into `out`. Returns what went wrong, or ""
    when it was written.

    The picture is joined by stream copy, each minute placed by its recorded length. So is the sound, unless the
    minutes do not share one sound: some had none (a stream copy keeps only the tracks of its first file, so sound
    after a silent first minute would be dropped), or a reconnect changed its settings (the first minute's settings
    would be used for all, playing the others at the wrong speed). Then the sound track is built minute by minute
    exactly as each minute was heard live (the live transcription's own filter, padded or cut to the minute's
    recorded length; silence for a minute without sound or one that cannot be read), and encoded once.
    Sample-exact minutes never overlap or drift, which a per-minute AAC encode (with its priming) would."""
    bad = set(sess.unreadable)
    assembled = assembled or sess.pdir / "assembly.tmp.mkv"
    temporary: list[Path] = [assembled]
    try:
        paths = [sess.segdir / s["name"] for s in segs]
        readable = [s for s in span if s["name"] not in bad]
        heard = [s for s in readable if [s["start"], s["end"]] not in sess.missing_audio]
        mixed_audio = bool(heard) and len(heard) < len(readable)
        size = sum(path.stat().st_size for path in paths)
        require_disk_space(sess.segdir, size)
        if len(heard) > 1 and not mixed_audio:
            # Minutes recorded before their sound settings were saved (or whose check failed then) are read now.
            seen = {s.get("sound") or _sound_of(sess.segdir / s["name"], cancel) for s in heard}
            mixed_audio = len(seen - {""}) > 1
        if mixed_audio:
            # Each minute's sound as PCM (48 kHz stereo, 192 kB a second) until the whole is encoded once.
            length = float(span[-1]["end"]) - float(span[0]["start"])
            require_disk_space(sess.segdir, size + int(192_000 * length))
        inputs = ["-f", "concat", "-safe", "0", "-i", str(sess.segdir / listing)]
        codecs = ["-c", "copy"]
        if mixed_audio:
            sound = []
            for index, segment in enumerate(span):
                source = sess.segdir / segment["name"]
                target = sess.segdir / f"{audio}-{index:06d}.wav"
                length = float(segment["end"]) - float(segment["start"])
                temporary.append(target)
                if segment["name"] in bad or [segment["start"], segment["end"]] in sess.missing_audio:
                    args = ["-f", "lavfi", "-t", f"{length:.6f}", "-i",
                            "anullsrc=channel_layout=stereo:sample_rate=48000"]
                else:
                    args = ["-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn", "-af",
                            f"aresample=48000:async=1:first_pts=0,apad=whole_dur={length:.6f},atrim=end={length:.6f}"]
                try:
                    run_process([ffmpeg_bin(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error", *args, "-ac",
                                 "2", "-ar", "48000", "-c:a", "pcm_s16le", str(target)], check=True, cancel=cancel,
                                timeout=max(600.0, length * 20))
                except subprocess.CalledProcessError:
                    if not _opens(source, cancel):
                        return f"Impossible to open '{segment['name']}'"
                    raise
                quoted = target.as_posix().replace("'", "'\\''")
                sound.append(f"file '{quoted}'\n")
            (sess.segdir / sounds).write_text("".join(sound), encoding="utf-8")
            inputs += ["-f", "concat", "-safe", "0", "-i", str(sess.segdir / sounds)]
            codecs = ["-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ac", "2", "-ar", "48000"]
        (sess.segdir / listing).write_text(_concat_listing(sess, segs, paths), encoding="utf-8")
        try:
            result = run_process([ffmpeg_bin(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error", *inputs,
                                  *codecs, str(assembled)], check=True, cancel=cancel, timeout=timeout)
        except subprocess.CalledProcessError as exc:
            # A file FFmpeg cannot open at the start of the list stops the join with an error instead.
            bad = next((s["name"] for s in segs if not _opens(sess.segdir / s["name"], cancel)), "")
            if not bad:
                raise
            return _join_problem(exc) or f"Impossible to open '{bad}'"
        problem = _join_problem(result)
        if problem:
            return problem
        os.replace(assembled, out)
        return ""
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


# ------------------------------------------------------------------ jobs
def capture_allowed(src: dict, settings: dict) -> tuple[bool, str]:
    r = rights.evaluate(src, settings)
    if not rights.local_allowed(src, r, settings):
        return False, f"{r['label']}: {r['explain']}"
    if src.get("local_path"):
        return Path(src["local_path"]).exists(), "Recording file"
    if rights.is_platform_url(src.get("url") or "") and not (settings.get("rights_allow_remote_download") or
                                                              settings.get("autopilot_public_videos")):
        from . import submissions

        if not submissions.for_source(src):  # a link you added in Live streams is recorded without that setting
            return False, "Platform live stream: allow downloads of authorized sources in Settings to capture it"
    return bool(src.get("url")), "Stream URL"


def _recover_ended_stream(sess: Session, job: Job) -> Path:
    """An ended platform broadcast may expose its ordinary public archive only after processing.

    Only an empty capture uses the archive: replacing a partial recording would change all saved live times.
    Attempts and server waits survive restarts, and the existing importer owns every network/media guard.
    """
    from ..jobs import DownloadRefused, download_url
    from ..media_import import MediaUnavailable

    src, settings = sess.src, sess.settings
    fix = "The saved minutes are kept. Add your own recording, or retry when the platform's public recording exists."

    def fail(message: str) -> None:
        db.update("sources", src["id"], status="needs_file", status_note=message, error=message)
        raise queue.Fail(message, fix)

    from .intake import channel_live_page

    if src.get("local_path") or not (rights.is_platform_url(src.get("url") or "") or
                                     (src.get("access") or {}).get("webpage")):
        fail("The ended stream has no saved minutes or public recording to recover.")
    if channel_live_page(src.get("url") or ""):
        # A channel page shows whatever the channel has now, not the broadcast that ended.
        fail("The stream ended before ClipForge recorded any of it.")
    ok, why = rights.download_allowed(src, settings)
    if not ok:
        fail(why)
    recovery = sess.archive_recovery
    now = time.time()
    until = float(recovery.get("until") or 0)
    if until > now:
        raise queue.Wait("archive", until - now, "Waiting for the platform's public recording")

    # A completed download is atomically moved here. Reuse it after a crash between that move and checkpoint.
    paths = sorted(p for p in sess.pdir.glob("source.*") if p.suffix.lower() in config.VIDEO_EXTENSIONS)
    output = paths[0] if paths else None
    if output is None:
        attempts = int(recovery.get("attempts") or 0)
        started = float(recovery.get("started") or now)
        if attempts >= ARCHIVE_MAX_ATTEMPTS or now - started >= ARCHIVE_MAX_WAIT_SECONDS:
            fail("The platform has not provided a usable public recording after repeated checks.")
        job.check()
        require_disk_space(sess.pdir, max_source_bytes(settings))
        sess.archive_recovery = recovery = {**recovery, "started": started, "attempts": attempts + 1, "until": 0}
        sess.save()  # claim the attempt before I/O, so a crash cannot cause unlimited immediate retries
        db.update_project(sess.project["id"], source_path=str(sess.pdir / "source.mp4"))
        try:
            download_url(sess.project["id"], src["url"], job.pipeline_ctx(0, 1),
                         max_bytes=max_source_bytes(settings),
                         max_seconds=60.0 * float(settings.get("autopilot_max_source_minutes") or 240))
        except (MediaUnavailable, queue.Wait, queue.Retry) as exc:
            if isinstance(exc, MediaUnavailable) and exc.code not in ("extraction_failed", "network", "rate_limited"):
                fail(str(exc))  # no retrying private, blocked, removed, protected or unsupported media
            if recovery["attempts"] >= ARCHIVE_MAX_ATTEMPTS:
                fail("The platform has not provided a usable public recording after repeated checks.")
            requested = (exc.seconds if isinstance(exc, queue.Wait) else
                         exc.retry_after if isinstance(exc, MediaUnavailable) else exc.delay)
            delay = requested if requested is not None else min(900, 60 * 2 ** (recovery["attempts"] - 1))
            recovery["until"] = time.time() + max(1, delay)
            sess.save()
            message = "The stream ended; waiting for its public recording to become available"
            db.update("sources", src["id"], status="ingesting", status_note=message)
            raise queue.Wait("archive", delay, message) from None
        except DownloadRefused as exc:
            if exc.code == "disk_space":
                raise queue.Wait("disk", 1800, "Waiting for free disk space; saved work is kept") from None
            fail(str(exc))
        except netguard.UnsafeUrl:
            fail("The public recording contains an address that cannot be accessed safely.")
        fresh = db.get_project(sess.project["id"]) or {}
        candidate = Path(fresh.get("source_path") or "")
        output = candidate if candidate.parent == sess.pdir and candidate.is_file() else None
    if output is None:
        fail("The ended stream's public recording could not be recovered.")
    job.check()
    _check_local_permission(sess)
    metadata = probe(output, cancel=job.cancelled)
    duration = float(metadata.get("duration") or 0)
    if not metadata.get("has_video") or not metadata.get("has_audio") or duration <= 0:
        fail("The public recording has no usable video and audio; add a complete recording with sound.")
    if duration > 60.0 * float(settings.get("autopilot_max_source_minutes") or 240) + 0.1 or \
            output.stat().st_size > max_source_bytes(settings):
        fail("The public recording exceeds the configured source limits.")
    if not recovery.get("complete"):
        sess.archive_recovery = {**recovery, "complete": output.name, "until": 0}
        sess.offset = duration
        sess.untranscribed = [[0, duration]]  # the empty live transcript must never stand in for archive speech
        sess.capture_complete = True
        sess.meta = metadata
        sess.save()
        (sess.pdir / "transcript.json").unlink(missing_ok=True)
        (sess.pdir / "loudness.json").unlink(missing_ok=True)
    db.update_project(sess.project["id"], source_path=str(output), source_filename=output.name,
                      duration=duration, info=metadata)
    return output


@handler("live_watch")
def live_watch(job: Job) -> dict:
    from . import scout

    settings = db.get_settings()
    if not config.discovery_enabled(settings):
        return {"started": [], "message": "Automatic stream discovery is off. Add a stream explicitly to record it."}
    if not settings.get("autopilot_live_monitoring"):
        return {"message": "Live monitoring is off"}
    started = []
    for src in db.select("sources", "kind = 'live' AND status IN ('eligible', 'needs_file')", (),
                         "user_added DESC, source_score DESC"):
        if src.get("live_status") == "ended" or (src.get("intake") or {}).get("canceled"):
            continue
        broad = scout.automatic_discovery(src, settings=settings)
        remaining = scout.discovery_attempts_remaining(settings)
        if broad and settings.get("autopilot_discovery_uploadable_only", True) and \
                not rights.discovery_publishable(src, settings):
            continue
        if broad and settings.get("discovery_quality_first", True) and remaining is not None and remaining <= 0:
            continue  # selected streams and explicit links keep their intent; do not restart held recordings
        ok, why = capture_allowed(src, settings)
        if not ok:
            db.update("sources", src["id"], status_note=why)
            continue
        with locks.named("discovery-selection"):
            remaining = scout.discovery_attempts_remaining(settings)
            if broad and settings.get("discovery_quality_first", True) and remaining is not None and remaining <= 0:
                continue
            if not src.get("user_added") and int(settings.get("autopilot_sources_per_day") or 0) == 0 and \
                    scout.still_needed(settings) <= 0:
                continue
            row = queue.enqueue("live_capture", {"source_id": src["id"]}, idem_key=f"live:{src['id']}",
                          ref=("source", src["id"]), timeout_s=24 * 3600, max_attempts=5,
                          priority=queue.source_priority(src), revive=False)
            if row["status"] not in queue.ACTIVE:
                continue
            fields = {"selected_day": scout.local_day(settings)} if broad else {}
            db.update("sources", src["id"], status="ingesting", status_note="Live: capturing", **fields)
        started.append(src["id"])
    return {"started": started, "message": f"{len(started)} live source(s) started"}


_turns: dict[tuple[str, str], threading.Lock] = {}


@handler("live_capture")
def live_capture(job: Job) -> dict:
    """One turn of one stream. Several streams take turns at the same time (worker lanes); one stream never runs two
    turns at once, even if its job were claimed again while an earlier turn is still finishing."""
    with _capture_lock:
        turn = _turns.setdefault(_capture_key(job.payload.get("source_id", "")), threading.Lock())
    if not turn.acquire(blocking=False):
        raise queue.Wait("live", TURN_SECONDS, "Watching live — listening for good moments")
    try:
        return _live_turn(job)
    finally:
        turn.release()


def _finish_requested(source_id: str) -> bool:
    from .intake import finish_requested

    return finish_requested(source_id)


def _clipping_stopped(source_id: str) -> bool:
    from .intake import clipping_stopped

    return clipping_stopped(source_id)


def _clip_minute(sess: Session, job: Job) -> None:
    """After a minute was heard: make a clip when a moment is ready. Not after "Stop clipping": the minute is
    still kept for the recording, and the clips already made go on to their checks and uploads."""
    if _clipping_stopped(sess.src["id"]):
        _listening(sess, "stopped")
        return
    found = detect(sess, job)
    if found and _clipping_stopped(sess.src["id"]):  # pressed while this minute was being searched
        _listening(sess, "stopped")
        return
    if found:
        make_live_clip(sess, found, job)


def _stopped_empty(src: dict) -> dict:
    reason = "Stopped by you before anything was recorded"
    db.execute("UPDATE sources SET live_status = 'stopped', status = 'canceled', status_note = ?, updated_at = ?, "
               "intake = json_set(COALESCE(intake, '{}'), '$.canceled', json('true')) WHERE id = ?",
               (reason, time.time(), src["id"]))
    return {"minutes": 0, "live_clips": 0, "message": reason}


def _other_broadcast(sess: Session, src: dict, found: dict, recorded: float) -> bool:
    """Is the channel now showing a different broadcast than the one recorded so far? A channel link stands for one
    broadcast: a later one (a new broadcast id, or a long gap that cannot be shown to be the same broadcast) ends
    this recording instead of being appended to it under the same upload request."""
    from .intake import channel_live_page

    if src.get("local_path"):
        return False
    known, current = sess.broadcast.get("id") or "", found.get("id") or ""
    if recorded > 0:
        if known and current and known != current:
            return True
        # Only a channel page can show a later broadcast at the same link. A link to one stream (a live video, an
        # .m3u8 address) is that stream, however long ClipForge was paused or waiting for disk space.
        if channel_live_page(src.get("url") or "") and not (known and current == known) and sess.alive_at and \
                time.time() - sess.alive_at > OFFLINE_GRACE_SECONDS:
            return True
    if current and not known:
        sess.broadcast = {**found, "first_seen": time.time()}
        sess.save()
    return False


def _live_turn(job: Job) -> dict:
    settings = db.get_settings()
    src = db.fetch("sources", job.payload.get("source_id", ""))
    if not src:
        raise queue.Fail("The live source was deleted")
    if (src.get("intake") or {}).get("canceled") or (src.get("intake") or {}).get("removed"):
        raise queue.Canceled()
    analysis = db.fetch("worker_jobs", f"post_live:{src['id']}:{src.get('project_id') or ''}", "idem_key")
    if analysis and (analysis["status"] in queue.ACTIVE or analysis["status"] == "completed"):
        # The recording was finished and joined. Opening its session again would rewrite the files the analysis
        # reads; only Try again after a failed analysis whose joined file is gone comes back here.
        saved = read_json(config.projects_dir() / src["project_id"] / "live" / "state.json", {}) or {}
        return {"minutes": round(float(saved.get("offset") or 0) / 60, 1), "live_clips": len(saved.get("clips") or []),
                "message": "The recording was finished; its full recording is analyzed separately"}
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
    finishing = _finish_requested(src["id"])
    with _capture_lock:
        capture = _captures.get(key)
        if capture and (capture.job_id != job.id or capture.stopped_reason in ("restart", "paused", "disk")):
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
        if old and old.stopped_reason in ("restart", "paused", "disk") and \
                float(getattr(old, "stopped_at", 0) or 0) > sess.alive_at:
            # ClipForge stopped that recorder (a pause, closing, disk space), not the stream: it was live until then.
            sess.alive_at = float(old.stopped_at)
            sess.save()
        _resume_live_outputs(sess, job)
        retry_path = sess.segdir / "server-wait.json"
        retry_at = float((read_json(retry_path, {}) or {}).get("until") or 0)
        if retry_at > time.time() and not finishing:
            raise queue.Wait("server", retry_at - time.time(), "The video server asked to wait before recording")
        recorded = sess.offset + sum(d for _, d in finished_segments(sess))
        byte_budget = max_source_bytes(settings) - _recorded_bytes(sess)
        if recorded >= float(settings.get("autopilot_max_source_minutes") or 240) * 60 or byte_budget <= 0:
            src = {**src, "live_status": "ended"}
            sess.limit_reached = True
        if finishing and not sess.capture_complete:
            # "Stop recording" while no recorder runs (waiting for the stream, the GPU or a retry): finish now.
            src = {**src, "live_status": "ended"}
            sess.stopped_by_owner = True
        if src.get("live_status") == "ended":
            pending = finished_segments(sess)
            for name, dur in pending[:1] if job.host is not None else pending:
                process_segment(sess, name, dur, job)
            if finished_segments(sess):
                raise queue.Wait("live", TURN_SECONDS, "Recovering the final recorded minutes")
            if not sess.segments and sess.stopped_by_owner:
                return _stopped_empty(src)
            if not sess.segments:
                return _finish_capture(sess, job, recording=_recover_ended_stream(sess, job))
            sess.capture_complete = True
            sess.save()
        if not sess.capture_complete:
            # A local growing recording has an observable current size; remote streams need their remaining
            # configured budget reserved because neither their length nor their bitrate is trustworthy.
            expected = (min(byte_budget, Path(src["local_path"]).stat().st_size)
                        if src.get("local_path") else byte_budget)
            relays: list = []
            broadcast: dict = {}
            try:
                args = input_args(src, settings, public_relays=relays, byte_budget=max(1, byte_budget),
                                  on_retry=lambda until: write_json(retry_path, {"until": until}),
                                  broadcast=broadcast)
            except StreamEnded:
                from .intake import channel_live_page

                if channel_live_page(src.get("url") or "") and recorded <= 0:
                    _offline(sess, src, recorded)  # the page still shows an earlier broadcast: wait for the next
                db.update("sources", src["id"], live_status="ended")
                raise queue.Wait("live", TURN_SECONDS, "Stream ended — recovering the full recording")
            except StreamOffline:
                _offline(sess, src, recorded)
            except queue.Fail as exc:
                db.update("sources", src["id"], status="needs_file", status_note=str(exc)[:300])
                raise
            # Streams recording at the same time share the disk: reserve what the others may still write, so a
            # new stream waits to start rather than every stream stopping halfway when the disk fills up.
            # A reconnect counts them too: what was checked when it started may since have been taken by a stream
            # that started while it had no recorder (or by anything else on the disk). Their remaining room shrinks
            # as they record, so a reconnect needs no more than its first start did. Streams starting at the same
            # moment (one per live lane) count each other as well: the check and this stream's reservation happen
            # together, and the reservation lasts until its recorder is listed or the start gives up. Only a
            # stream found live reserves: one still looking up its address (it may be offline) holds nothing.
            try:
                with _capture_lock:
                    others = [c for k, c in _captures.items() if k != key and c.proc.poll() is None]
                    reserved = sum(max(0, max_source_bytes(c.sess.settings) - _recorded_bytes(c.sess)) for c in others)
                    reserved += sum(room for k, room in _starting.items() if k != key)
                    require_disk_space(sess.segdir, max(1, expected) + reserved)
                    _starting[key] = max(1, expected)
            except BaseException:
                for relay in relays:
                    relay.close()
                raise
            try:
                try:
                    state.resolve("disk:space")
                    # Checked only once there is room: a stream waiting for disk space has not started recording
                    # this broadcast, and remembering its id would end the channel's next broadcast later.
                    if _other_broadcast(sess, src, broadcast, recorded):
                        db.update("sources", src["id"], live_status="ended", status_note=(
                            "The channel is showing a different broadcast now. The recorded one is being finished; "
                            "add the link again to clip the new broadcast."))
                        raise queue.Wait("live", TURN_SECONDS, "Finishing the recorded broadcast")
                    capture = Capture(sess, job, args, relays=relays)
                    capture.recorded_at_start = recorded
                except BaseException:
                    for relay in relays:
                        relay.close()
                    raise
                with _capture_lock:
                    _captures[key] = capture
                    _starting.pop(key, None)
            finally:
                with _capture_lock:
                    _starting.pop(key, None)
            sess.offline_since = 0.0
            sess.alive_at = time.time()
            sess.save()
            if src.get("live_status") != "live" or src.get("status") != "ingesting":
                db.update("sources", src["id"], live_status="live", status="ingesting", status_note="Live: recording")
            job.log("capture_started", "Recording a permitted live source", run=sess.run)
        else:
            return _finish_capture(sess, job)
    sess = capture.sess
    sess.src, sess.settings = src, settings
    _resume_live_outputs(sess, job)
    proc = capture.proc
    if finishing and not capture.stopped_reason:
        capture.stop("finish")
    try:
        while True:
            job.check()
            if capture.stopped_reason == "disk":
                with _capture_lock:
                    _captures.pop(key, None)
                _seen_live(sess)
                raise queue.Wait("disk", 1800, "Recording paused for disk space; saved minutes are kept")
            if capture.stopped_reason == "canceled":
                raise queue.Canceled()
            if capture.stopped_reason and capture.stopped_reason not in ("restart", "paused", "limit", "finish"):
                raise queue.Fail(capture.stopped_reason)
            pending = finished_segments(sess)
            for name, dur in pending[:1] if job.host is not None else pending:
                job.progress(None, f"Live: transcribing minute {sess.offset / 60:.0f}", stage="live")
                process_segment(sess, name, dur, job)
                _clip_minute(sess, job)
            if proc.poll() is None:
                sess.alive_at = time.time()  # saved with the next minute's checkpoint
            if job.host is not None and (proc.poll() is None or finished_segments(sess)):
                raise queue.Wait("live", TURN_SECONDS, "Watching live — listening for good moments")
            if proc.poll() is not None:
                if job.host is None:  # EOF can append the final CSV row between the earlier read and this poll
                    for name, dur in finished_segments(sess):
                        process_segment(sess, name, dur, job)
                        _clip_minute(sess, job)
                break
            job.cancel_event.wait(2.0)
    except queue.Wait:
        raise  # the recorder owns the source lock and keeps writing while another stream gets a turn
    except BaseException:
        capture.stop(_stop_reason(job))
        with _capture_lock:
            _captures.pop(key, None)
        if capture.stopped_reason in ("restart", "paused", "disk"):
            _seen_live(sess)  # held (closing, Stop all jobs): the stream was live until now
        if capture.stopped_reason == "paused" and _stop_reason(job) == "paused":
            db.update("sources", src["id"], status="queued", status_note="Recording paused by Stop all jobs")
        raise
    capture.stop()
    with _capture_lock:
        _captures.pop(key, None)
    if capture.stopped_reason in ("disk", "restart", "paused"):
        _seen_live(sess)
    if capture.stopped_reason == "disk":
        raise queue.Wait("disk", 1800, "Recording paused for disk space; saved minutes are kept")
    if capture.stopped_reason in ("restart", "paused"):
        # The app closed or Autopilot was paused during this turn: the broadcast did not end. The next turn starts
        # a new recorder after the saved minutes, without using an attempt or finishing the recording here.
        raise queue.Wait(capture.stopped_reason, TURN_SECONDS, "Recording paused; it continues when Autopilot runs")
    if _relay_limit(getattr(capture, "relays", [])) and capture.stopped_reason != "finish":
        capture.stopped_reason = "limit"  # the stream relay reached the recording size limit: finish normally
    finished = capture.stopped_reason in ("limit", "finish")
    err = capture.error()
    retry_at = float((read_json(sess.segdir / "server-wait.json", {}) or {}).get("until") or 0)
    if retry_at > time.time() and not finished:
        raise queue.Wait("server", retry_at - time.time(), "The video server asked to wait before recording")
    relay_error = any(relay.error() for relay in getattr(capture, "relays", []))
    read_error = not src.get("local_path") and "Error during demuxing" in err
    if (proc.returncode or relay_error or read_error) and not finished:
        if proc.returncode == 75:
            raise queue.Wait("recording", TURN_SECONDS, "Recovering the interrupted recording")
        message = f"The live recording was interrupted. {err[:200]}".strip()
        db.update("sources", src["id"], status="ingesting", status_note=message[:300])
        fatal = any(word in err for word in ("DASH", "Protected", "DRM", "safe public HTTP", "unsupported",
                                             "download size limit", "safe download limit"))
        out_of_attempts = int(job.row.get("attempts") or 0) >= int(job.row.get("max_attempts") or 3)
        if (fatal or out_of_attempts) and sess.segments and not src.get("local_path"):
            # The minutes already recorded are kept and finished like an ended stream, never left unjoined.
            db.update("sources", src["id"], live_status="ended", status_note=(
                "The stream stopped responding; finishing what was recorded. " + message)[:300])
            raise queue.Wait("live", TURN_SECONDS, "Finishing what was recorded")
        if fatal:
            db.update("sources", src["id"], status="needs_file", status_note=message[:300])
            raise queue.Fail(message)
        if sess.offset > getattr(capture, "recorded_at_start", sess.offset) + 5 and not src.get("local_path"):
            # This recorder had been recording: a dropped connection mid-stream reconnects right away without
            # using up an attempt. A recorder that keeps failing before it records anything still uses them.
            db.update("sources", src["id"], status_note="The stream connection dropped; reconnecting. Saved "
                                                       "minutes are kept.")
            raise queue.Wait("reconnect", 3, "Reconnecting to the stream")
        if int(job.row.get("attempts") or 0) >= int(job.row.get("max_attempts") or 3):
            db.update("sources", src["id"], status="error", status_note=message[:300])
        raise queue.Retry(message)
    if not sess.segments and capture.stopped_reason == "finish":
        return _stopped_empty(src)
    if not sess.segments:
        message = "The live source ended without any usable recorded video"
        db.update("sources", src["id"], status="error", status_note=message)
        raise queue.Fail(message)
    sess.capture_complete = True
    sess.stopped_by_owner = sess.stopped_by_owner or capture.stopped_reason == "finish"
    sess.limit_reached = capture.stopped_reason == "limit" or sess.offset >= \
        float(settings.get("autopilot_max_source_minutes") or 240) * 60 - 0.1
    sess.save()
    return _finish_capture(sess, job)


def _stop_reason(job: Job) -> str:
    """Why a turn that ends with an exception stops its recorder. Stop all jobs (even when it reached this turn
    before the recorder's watchdog, or Resume was pressed meanwhile) is a hold, not a cancel."""
    if job.host and job.host._stop.is_set():
        return "restart"
    try:
        row = queue.get(job.id) or {}
        if row.get("wait_reason") == queue.STOP_ALL or (state.paused() and not row.get("cancel_requested")):
            return "paused"
    except Exception:  # noqa: BLE001 - never hide the turn's own exception
        log.exception("could not read why the live turn stopped")
    return "canceled"


def _seen_live(sess: Session) -> None:
    """ClipForge stopped the recorder (closing, a pause, disk space), not the stream: it was live until now."""
    sess.alive_at = time.time()
    sess.save()


def _offline(sess: Session, src: dict, recorded: float) -> None:
    """The channel is not live. Before anything was recorded it has not started yet; after that, it ended, unless
    it comes back within a few minutes (a streamer's dropped connection keeps one recording)."""
    from .intake import UPCOMING_MAX_WAIT

    now = time.time()
    meta = src.get("intake") or {}
    if recorded > 0:
        if not sess.offline_since:
            sess.offline_since = now
            sess.save()
        if now - sess.offline_since >= OFFLINE_GRACE_SECONDS:
            db.update("sources", src["id"], live_status="ended")
            raise queue.Wait("live", TURN_SECONDS, "The stream ended — finishing the recording")
        db.update("sources", src["id"], status_note="The stream went offline; waiting a few minutes in case it "
                                                   "comes back. Saved minutes are kept.")
        raise queue.Wait("offline", 60, "The stream went offline; checking again in a minute")
    if meta.get("submitted") and now - float(meta.get("added_at") or src.get("created_at") or now) > UPCOMING_MAX_WAIT:
        db.update("sources", src["id"], status="failed", status_note="The stream did not start within a day.")
        raise queue.Fail("The stream did not start within a day.",
                         "Add the link again in Live streams when the streamer is live.")
    db.update("sources", src["id"], live_status="upcoming", status="queued", status_note="Waiting for the stream to start")
    raise queue.Wait("offline", 120, "Waiting for the stream to start")


def _joined(sess: Session) -> Path | None:
    """The recording joined by an earlier finishing turn, if it is still exactly that file. Joining again writes a
    new container (new bytes) around the same minutes, which would change what later approvals were checked against."""
    path = Path(sess.final.get("path") or "")
    try:
        st = path.stat()
    except OSError:
        return None
    same = path.is_file() and [st.st_size, st.st_mtime_ns] == [sess.final.get("size"), sess.final.get("mtime_ns")] and \
        sess.final.get("segments") == len(sess.segments)
    return path if same else None


def _finish_capture(sess: Session, job: Job, *, recording: Path | None = None) -> dict:
    src = sess.src
    _drop_minute_sounds(sess)  # only the live picking read them; the recording keeps the sound
    output = recording or _joined(sess) or finalize(sess, cancel=job.cancelled)
    if output and not recording and Path(output).is_file() and not _joined(sess):
        st = Path(output).stat()
        sess.final = {"path": str(output), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "segments": len(sess.segments)}
        sess.save()
    no_audio = bool(sess.missing_audio) and all([s["start"], s["end"]] in sess.missing_audio for s in sess.segments)
    if output and Path(output).is_file():
        final_meta = probe(output, cancel=job.cancelled)
        db.update_project(sess.project["id"], info={**(db.get_project(sess.project["id"]) or {}).get("info", {}),
                                                  **final_meta, "missing_audio": sess.missing_audio})
        no_audio = not final_meta.get("has_audio")
    job.check()
    _check_local_permission(sess)
    if no_audio:
        reason = "The completed live recording contains video only; no usable audio track is available."
        db.update("sources", src["id"], live_status="stopped" if sess.limit_reached else "ended", status="failed",
                  error=reason, status_note=reason)
        db.update_project(sess.project["id"], status="error", stage="audio", error=reason, message=reason)
        raise queue.Fail(reason, "The recording is saved. Check the stream or OBS audio track before trying a "
                         "new recording; speech transcription cannot recover missing audio.")
    stopped = sess.limit_reached or sess.stopped_by_owner
    detail = "Stopped by you" if sess.stopped_by_owner else "Recording limit reached" if sess.limit_reached else "Live ended"
    after = "no more clips are made; the ones already made still upload" if _clipping_stopped(src["id"]) else \
        "analyzing the full recording"
    db.update("sources", src["id"], kind="live", live_status="stopped" if stopped else "ended",
              status="analyzing", status_note=f"{detail} after {sess.offset / 60:.0f} min with "
              f"{len(sess.clips)} live clip(s); {after}")
    queue.enqueue("post_live", {"source_id": src["id"], "project_id": sess.project["id"]},
                  idem_key=f"post_live:{src['id']}:{sess.project['id']}", ref=("source", src["id"]),
                  timeout_s=6 * 3600, priority=queue.source_priority(src, job.row.get("priority") or 0))
    state.event("live_ended", f"“{src.get('title', '')[:60]}” ended: {sess.offset / 60:.0f} min, "
                              f"{len(sess.clips)} live clip(s)", ref_type="source", ref_id=src["id"])
    return {"minutes": round(sess.offset / 60, 1), "live_clips": len(sess.clips),
            "message": f"Live capture ended after {sess.offset / 60:.0f} min"}


def _kept(clip_id: str) -> bool:
    """Published, being published, or approved to upload: a better post-live cut does not replace it."""
    return _published(clip_id) or bool(db.scalar(
        "SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND status IN ('approved', 'action_needed')",
        (clip_id,)))


def _published(clip_id: str) -> bool:
    return bool(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE clip_id = ? AND status IN "
                          "('publishing', 'reconciling', 'published')", (clip_id,))) or bool(db.scalar(
        "SELECT COUNT(*) FROM publications WHERE clip_id = ? AND status IN ('done', 'action_needed', 'uploading', "
        "'processing', 'queued')", (clip_id,)))


def supersede(clip: dict, reason: str) -> None:
    db.update_clip(clip["id"], status="superseded", error=reason)
    for item in db.select("scheduled_publications", "clip_id = ? AND status IN ('awaiting_approval', 'approved')",
                          (clip["id"],)):
        audit = json.dumps([*(item.get("audit") or []), {"at": time.time(), "event": "replaced", "detail": reason}])
        # Compare-and-set: a post the scheduler started publishing meanwhile keeps its status.
        db.execute("UPDATE scheduled_publications SET status = 'replaced', status_note = ?, audit = ?, updated_at = ? "
                   "WHERE id = ? AND status IN ('awaiting_approval', 'approved')", (reason, audit, time.time(), item["id"]))
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
    project = db.get_project(project_id) or {}
    if project.get("source_path"):
        from . import submissions

        try:
            # Clips cut from the full recording are covered by a live input's "Make & upload" request only
            # against these exact recorded bytes, like a submitted video's original.
            submissions.bind_live_recording(src, project, Path(project["source_path"]))
        except ValueError as exc:
            raise queue.Fail(str(exc), "The live clips made during the stream are kept.") from exc
    ctx = job.pipeline_ctx(0.0, 1.0)
    live_state_path = config.projects_dir() / project_id / "live" / "state.json"
    live_state = read_json(live_state_path, {}) or {}

    def stopped() -> bool:
        return _clipping_stopped(src["id"])

    if stopped() and read_json(live_state_path.parent / "post-live-selection.json", None) is None:
        # "Stop clipping" before anything was chosen from the full recording: nothing is transcribed, searched or
        # rendered. The recording is saved, and the clips made live keep going.
        return _close_stopped(src, project_id, job)
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
        chosen = screen_stories(p, chosen, settings)
        # Quality over quantity holds after the stream too: a moment found in the full recording must clear the
        # same bar as a live one, and the whole stream gets no more clips than its pace over its length.
        pace = live_pick.pace(project, settings)
        floor = max(float(settings.get("autopilot_min_quality") or 0), float(p.opts.get("min_score", 50))) \
            + pace["above"]
        chosen = [r for r in chosen if r.get("clip_score", r["score"]) >= floor]
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
            if _kept(old["id"]) or r.get("clip_score", r["score"]) < (old.get("score") or 0) + REPLACE_MARGIN:
                continue
            replacements[str(len(keep))] = old["id"]
            live.remove(old)
            keep.append(r)
        cps = live_pick.total_cap(pace, int(settings.get("autopilot_clips_per_source") or 5),
                                  float(live_state.get("offset") or p.meta.get("duration") or 0))
        keep = keep[:max(0, cps - len(live))] if len(live) + len(keep) > cps else keep
        selection = {"chosen": keep, "replacements": replacements}
        write_json(selection_path, selection)  # retry the exact selected moments, regardless of new fingerprints
    keep = selection["chosen"]
    rows: list[dict] = []
    if "rows" in selection or not stopped():  # "Stop clipping" before a chosen moment had its clip: none is made
        rows = process.create_clips(p, keep, ctx, replace_existing=False, durable=True)
        if selection.get("rows") != [r["id"] for r in rows]:
            selection = {**selection, "rows": [r["id"] for r in rows]}
            write_json(selection_path, selection)
    planned = [] if stopped() else plan_clips(p, rows, keep, src["id"])
    fresh = db.fetch("sources", src["id"])
    if not fresh or not rights.local_allowed(fresh, settings=db.get_settings()):
        raise queue.Fail("The recording's content permission changed before rendering")
    if (fresh.get("intake") or {}).get("canceled") or (fresh.get("intake") or {}).get("removed"):
        raise queue.Canceled()
    render_in_priority_order(p, planned, ctx, job, src, stop=stopped)
    halted = stopped()
    replaced = 0
    for index, old_id in selection.get("replacements", {}).items():
        if int(index) >= len(rows):
            continue
        new = db.get_clip(rows[int(index)]["id"])
        old = db.get_clip(old_id)
        if not old or not new or new["status"] != "ready":
            continue  # a failed replacement must leave the usable live clip available
        if halted:
            # "Stop clipping": the live clip and its upload stay as they are; the second cut of the same moment
            # is not kept next to it. When an earlier run of this step had already put the better cut in the live
            # clip's place, the better cut is what is kept: dropping it now would leave the moment with no clip.
            if old["status"] != "superseded" and not _published(new["id"]):
                db.update_clip(new["id"], status="superseded", error="Clipping was stopped by you; the live clip "
                                                                     "of this moment is kept")
            continue
        if _kept(old_id):
            if not _published(new["id"]):
                db.update_clip(new["id"], status="superseded", error="The original live clip was already published "
                                                                     "or approved to upload")
            continue
        if old["status"] != "superseded":
            r = keep[int(index)]
            supersede(old, f"Replaced by the post-live analysis: a better cut of the same moment "
                           f"({r.get('clip_score', r['score']):.0f} vs {old['score']:.0f})")
        replaced += 1
    if halted:
        for row in rows:  # chosen from the full recording but not made before the stop: never made
            clip = db.get_clip(row["id"])
            if clip and clip["status"] not in ("ready", "superseded"):
                db.update_clip(clip["id"], status="superseded", error="Not made: clipping was stopped by you")
    added = [c for c in (db.get_clip(r["id"]) for r in rows) if c and c["status"] == "ready"]
    for clip in added:
        store_fingerprint(clip, src)
        queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": src["id"]},
                      idem_key=f"package:{clip['id']}", ref=("clip", clip["id"]),
                      priority=queue.source_priority(src, job.row.get("priority") or 0))
    if halted:
        return _close_stopped(src, p.id, job, added=len(added))
    total = sum(1 for c in db.list_clips(p.id) if c["status"] == "ready")
    db.update_project(p.id, status="ready", progress=1.0, stage="done", message=f"{total} clip(s) ready")
    db.update("sources", src["id"], status="analyzed" if total else "weak", clips_selected=total,
              status_note=f"Post-live: {len(added)} clip(s) added, {replaced} live clip(s) replaced by better cuts")
    return {"added": len(added), "replaced": replaced, "message": f"Post-live analysis: {len(added)} added, "
                                                                  f"{replaced} replaced"}


def _close_stopped(src: dict, project_id: str, job: Job, *, added: int = 0) -> dict:
    """The end of a stream whose clipping was stopped by the owner: the recording is saved and nothing more is
    made from it. Every clip that was made is handed to its checks (again, if a hand-over was interrupted), so
    it still reaches its place in the plan and its upload."""
    ready = [c for c in db.list_clips(project_id) if c["status"] == "ready"
             and Path(c.get("output_path") or "").is_file()]
    for clip in ready:
        if not db.fetch("clip_fingerprints", clip["id"], "clip_id"):
            store_fingerprint(clip, src)
        queue.enqueue("package_clip", {"clip_id": clip["id"], "source_id": src["id"]},
                      idem_key=f"package:{clip['id']}", ref=("clip", clip["id"]),
                      priority=queue.source_priority(src, job.row.get("priority") or 0))
    note = (f"Clipping stopped by you: {len(ready)} clip(s) were made and still upload" if ready else
            "Clipping stopped by you before a clip was made")
    db.update_project(project_id, status="ready", progress=1.0, stage="done", message=f"{len(ready)} clip(s) ready")
    db.update("sources", src["id"], status="analyzed" if ready else "weak", clips_selected=len(ready),
              status_note=note)
    state.event("live_clipping_stopped", f"“{src.get('title', '')[:60]}”: {note[0].lower()}{note[1:]}",
                ref_type="source", ref_id=src["id"])
    return {"added": added, "replaced": 0, "stopped": True, "message": note}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--capture":
        raise SystemExit("This module is an internal live recorder")
    raise SystemExit(_capture_worker(sys.argv[2]))
