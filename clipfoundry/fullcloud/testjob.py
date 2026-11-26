"""The private test job (Settings → Processing → Run a test job): proof that the worker does the whole job, with
nothing of the owner's sent.

ClipForge makes a one-minute test video here (a moving test pattern with a narrator reading TEST_SCRIPT in this
computer's own voice), sends it to the worker as a Make clips job of one clip, follows it, brings the clip back,
checks it plays (picture, sound, length) and deletes the job there. The result says which stages ran on the worker,
how long each part took and what it cost at the owner's price. Without a voice on this computer the video has a tone
and a ready-made transcript instead, and the result says that transcription was not tried.

It runs as a studio job (one at a time, with progress and Stop) and counts as worker time like any other job.
"""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from .. import db
from ..pipeline import ffmpeg_utils
from ..pipeline.common import Cancelled
from ..studio.jobs import Canceled, Lease, cancel as cancel_job, enqueue, handler
from . import client, usage
from .worker_api import SETTING_KEYS, STAGES

log = logging.getLogger(__name__)

KIND = "cloud_test"
TEST_SCRIPT = (
    "This is a private test of your ClipForge worker. Nothing here is yours: ClipForge made this video a moment ago. "
    "The worker gets the video, listens to it, finds the best moment, frames it for a phone, writes the captions "
    "and renders the clip. Then your computer brings the clip back and checks that it plays. "
    "Here is the moment worth keeping. A good short starts with a hook. It says one clear thing. It ends before "
    "anyone gets bored. If you can hear these words in the finished clip, with captions under them, the test "
    "worked. The job is deleted from the worker when the test ends, and the time it took is added to this month's "
    "worker time. That is the whole test. Thank you for listening.")
WORDS_PER_S = 2.6


class TestError(Exception):
    status = 409


def last(workspace_id: str = "local") -> dict | None:
    rows = db.select("cloud_runs", "workspace_id = ? AND kind = 'test'", (workspace_id,), order="started_at DESC",
                     limit=1)
    if not rows:
        return None
    r = rows[0]
    job = db.select("studio_jobs", "kind = ? AND target_id = ?", (KIND, r["id"]), limit=1)
    j = job[0] if job else {}
    return {"id": r["id"], "status": r["status"], "worker": r["worker"], "started_at": r["started_at"],
            "ended_at": r["ended_at"], "seconds": r["seconds"], "uploaded_bytes": r["uploaded_bytes"],
            **(r.get("info") or {}), "job": {k: j.get(k) for k in ("status", "progress", "message", "error")}
            if j else None}


def start(workspace_id: str) -> dict:
    settings = db.get_settings()
    cfg = client.configured(settings)
    if not cfg:
        raise TestError("Add your worker's address and key first.")
    current = last(workspace_id)
    if current and (current.get("job") or {}).get("status") in ("queued", "running"):
        return current
    problem = usage.limit_problem(settings, workspace_id, usage.MIN_SECONDS)
    if problem:
        raise TestError(problem)
    run = usage.start("test", cfg["host"], "", usage.estimate(60, cfg["host"], settings), workspace_id)
    enqueue(workspace_id, KIND, run["id"], 1)
    return last(workspace_id) or {}


def stop(workspace_id: str) -> dict | None:
    current = last(workspace_id)
    if current:
        for j in db.select("studio_jobs", "kind = ? AND target_id = ? AND status IN ('queued', 'running')",
                           (KIND, current["id"])):
            cancel_job(j["id"])
            usage.update(current["id"], status="canceled", ended_at=time.time())
    return last(workspace_id)


def make_video(folder: Path, cancel=None) -> tuple[Path, Path | None, str]:
    """The test video, and a transcript when this computer has no voice to read the script ("" or why not)."""
    out = folder / "clipforge-worker-test.mp4"
    wav = folder / "narration.wav"
    srt: Path | None = None
    why = ""
    try:
        from ..makers import voice

        voice.speak(TEST_SCRIPT, wav, voice="auto", speed=1.0, cancel=cancel)
        seconds = float(ffmpeg_utils.probe(wav).get("duration") or 0)
        if seconds < 10:
            raise RuntimeError("the narration came out too short")
    except (Cancelled, Canceled):
        raise
    except Exception as exc:  # noqa: BLE001 - a tone and a transcript stand in
        log.info("no voice for the worker test: %s", exc)
        why = "This computer has no voice to read the test, so the worker was given the words (transcription was " \
              "not tried)."
        seconds = round(len(TEST_SCRIPT.split()) / WORDS_PER_S, 1)
        ffmpeg_utils.run(["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-ac", "1", "-ar", "16000",
                          str(wav)], duration=seconds, cancel=cancel)
        srt = folder / "clipforge-worker-test.srt"
        srt.write_text(_srt(TEST_SCRIPT, seconds), encoding="utf-8")
    ffmpeg_utils.run(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-i", str(wav), "-t", f"{seconds:.2f}",
                      "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                      str(out)], duration=seconds, cancel=cancel)
    return out, srt, why


def _srt(text: str, seconds: float) -> str:
    sentences = [s.strip() + "." for s in text.replace("!", ".").split(".") if s.strip()]
    per_word = seconds / max(1, len(text.split()))
    t, out = 0.0, []
    for i, s in enumerate(sentences, 1):
        d = len(s.split()) * per_word
        out.append(f"{i}\n{_ts(t)} --> {_ts(t + d)}\n{s}\n")
        t += d
    return "\n".join(out)


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


@handler(KIND)
def run_test(job: dict, lease: Lease) -> dict:
    run_id = job["target_id"]
    settings = db.get_settings()
    cfg = client.configured(settings)
    if not cfg:
        usage.update(run_id, status="failed", ended_at=time.time(), info={"problem": "No worker is set up."})
        raise TestError("No worker is set up.")
    c = client.Client(cfg["url"], cfg["key"])
    t0 = time.time()
    remote = ""
    result: dict = {"stages": list(STAGES)}
    try:
        lease.progress(0.02, "Making the test video on this computer")
        with tempfile.TemporaryDirectory(prefix="clipforge-worker-test-") as tmp:
            video, srt, why = make_video(Path(tmp), cancel=lease.canceled)
            result.update(note=why, transcription_tried=srt is None)
            facts = c.info()
            result["worker_info"] = {"version": facts.get("version"), "whisper": facts.get("whisper") or {},
                                     "ai": facts.get("ai") or ""}
            size = video.stat().st_size
            t_up = time.time()
            usage.update(run_id, status="uploading")
            got = c.submit(source=video, transcript=srt, options={"clip_count": 1, "min_duration": 15.0,
                                                                  "target_duration": 25.0, "max_duration": 45.0},
                           settings={k: settings[k] for k in SETTING_KEYS if k in settings},
                           name="ClipForge worker test",
                           progress=lambda n, total: lease.progress(0.1 + 0.1 * n / max(total, 1),
                                                                    "Uploading the test video"),
                           cancel=lease.canceled)
            remote = got["id"]
            up_s = max(0.01, time.time() - t_up)
            result.update(upload_seconds=round(up_s, 1), upload_mbps=round(size * 8 / up_s / 1e6, 1),
                          uploaded_bytes=size)
            usage.update(run_id, status="running", remote_id=remote, uploaded_bytes=size)
            last_msg = ""
            while True:
                if lease.canceled():
                    raise Canceled()
                state = c.job(remote)
                usage.update(run_id, seconds=usage.measured(state))
                if state.get("message") and state["message"] != last_msg:
                    last_msg = state["message"]
                lease.progress(0.2 + 0.6 * float(state.get("progress") or 0), f"On the worker: {last_msg or 'waiting'}")
                if state["status"] == "ready":
                    break
                if state["status"] in ("error", "cancelled"):
                    raise TestError(f"The worker could not finish the test: {state.get('error') or state['status']}")
                time.sleep(1.0)
            res = c.result(remote)
            result.update(ran=state.get("ran") or {}, how=state.get("how") or {}, clips=len(res["clips"]),
                          worker_seconds=usage.measured(state))
            lease.progress(0.85, "Bringing the clip back")
            if not res["clips"]:
                raise TestError("The worker finished but made no clip from the test video.")
            first = res["clips"][0]
            mp4 = next((f["name"] for f in first.get("files") or [] if f["name"].endswith(".mp4")), "")
            if not mp4:
                raise TestError("The worker made a clip but its video is missing.")
            back = Path(tmp) / "back.mp4"
            c.download(f"/jobs/{remote}/clips/{first['row']['id']}/{mp4}", back, cancel=lease.canceled)
            meta = ffmpeg_utils.probe(back)
            plays = bool(meta.get("video_codec")) and int(meta.get("width") or 0) > 0 and bool(meta.get("has_audio")) \
                and float(meta.get("duration") or 0) > 1
            result["clip"] = {"seconds": round(float(meta.get("duration") or 0), 1), "width": meta.get("width"),
                              "height": meta.get("height"), "plays": plays, "bytes": back.stat().st_size}
            if not plays:
                raise TestError("The clip came back but does not play (no picture or no sound).")
        c.delete(remote)
        remote = ""
        result.update(ok=True, round_trip_seconds=round(time.time() - t0, 1))
        price = float(settings.get("worker_price_per_hour") or 0)
        if price:
            result["cost"] = round(float(result.get("worker_seconds") or 0) / 3600 * price, 3)
        usage.update(run_id, status="done", ended_at=time.time(), seconds=result.get("worker_seconds") or 0,
                     info=result)
        lease.progress(1.0, "The test worked")
        return {"ok": True}
    except (Canceled, Cancelled, client.Stopped):
        _forget(c, remote)
        usage.update(run_id, status="canceled", ended_at=time.time(), info=result)
        raise Canceled() from None
    except Exception as exc:
        _forget(c, remote)
        result.update(ok=False, problem=str(exc)[:400], round_trip_seconds=round(time.time() - t0, 1))
        usage.update(run_id, status="failed", ended_at=time.time(), info=result)
        if isinstance(exc, (TestError, client.WorkerError)):
            raise TestError(str(exc)) from exc
        raise


def _forget(c: client.Client, remote: str) -> None:
    if not remote:
        return
    try:
        c.cancel(remote)
        c.delete(remote)
    except client.WorkerError:
        pass
