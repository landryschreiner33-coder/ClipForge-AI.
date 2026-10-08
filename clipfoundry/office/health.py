"""System Guardian (PATCH): health readings with a status, the actual reason and the next step.

Statuses are Healthy, Degraded, Error or Unknown. A reading that could not be taken is Unknown, never green. Every
reading carries the time it was taken, so a page that stopped receiving updates can show it as stale.

A reading marked `info` (no account connected, Autopilot off) is shown but does not count towards the overall status:
it is a fact about the setup, not a fault, and clipping on this PC works without it.
"""
from __future__ import annotations

import os
import shutil
import time

from .. import config, db

ORDER = {"error": 3, "degraded": 2, "unknown": 1, "healthy": 0}
LABEL = {"healthy": "Healthy", "degraded": "Degraded", "error": "Error", "unknown": "Unknown"}
HEARTBEAT_STALE = 180.0        # a worker host that has not reported for this long is not running
QUEUE_STUCK = 15 * 60.0        # due work nobody started for this long
SEARCH_LATE = 2.0              # a search more than this many polling periods late: nothing is starting it
GPU_FIX = "Run gpu-check.bat in the ClipFoundry folder; it says what to fix."
# GpuBusy (gpu.py) is recorded as the last GPU error too, but it means another program held the GPU, not a failure
GPU_BUSY = ("The GPU stayed busy", "MB of GPU memory was free")


def _c(cid: str, label: str, status: str, reason: str, action: str = "", **data: object) -> dict:
    return {"id": cid, "label": label, "status": status, "status_label": LABEL[status], "reason": reason,
            "action": action, "checked_at": time.time(), **data}


def _span(seconds: float) -> str:
    """A duration in words (no clock times: the page shows times in the Autopilot time zone, this text cannot)."""
    seconds = max(0.0, seconds)
    if seconds < 90:
        return "a minute"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} h".replace(".0 h", " h")
    return f"{round(seconds / 86400)} days"


def scheduler(settings: dict) -> dict:
    beats = [float(r.get("heartbeat") or 0) for r in db.select("worker_state")]
    last = max(beats, default=0.0)
    on = bool(settings.get("autopilot_enabled"))
    if os.environ.get("CLIPFOUNDRY_WORKERS", "").lower() == "off" and not last:
        return _c("scheduler", "Background work", "unknown", "Background workers are turned off in this process.",
                  "Start ClipFoundry normally (start.bat) to run them.")
    if not last:
        return _c("scheduler", "Background work", "unknown" if not on else "error",
                  "The background workers have not reported yet." if not on else
                  "Autopilot is on, but the background workers never reported.",
                  "Close ClipFoundry and run start.bat again." if on else "")
    age = time.time() - last
    if age > HEARTBEAT_STALE:
        return _c("scheduler", "Background work", "error" if on else "degraded",
                  f"The background workers last reported {int(age // 60)} min ago.",
                  "Close ClipFoundry and run start.bat again. If the PC slept, it continues after waking.",
                  last_heartbeat=last)
    return _c("scheduler", "Background work", "healthy", "The background workers are running.", last_heartbeat=last)


def queue_age(settings: dict) -> dict:
    now = time.time()
    oldest = db.scalar("SELECT MIN(run_after) FROM worker_jobs WHERE status IN ('queued', 'retrying') AND "
                       "run_after <= ? AND cancel_requested = 0", (now,))
    stalled = int(db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE status = 'running' AND lease_until > 0 AND "
                            "lease_until < ?", (now - 60,)) or 0)
    from ..autopilot import state

    held = state.paused()
    if stalled:
        return _c("queue", "Work queue", "degraded", f"{stalled} job(s) stopped reporting; they are restarted "
                  "automatically by maintenance.", "Nothing to do unless this stays for more than an hour.")
    if oldest and now - float(oldest) > QUEUE_STUCK and not held and settings.get("autopilot_enabled"):
        return _c("queue", "Work queue", "degraded", f"Work has been waiting {int((now - float(oldest)) // 60)} min "
                  "to start.", "Check that the background workers run (see Background work).")
    return _c("queue", "Work queue", "healthy", "Work starts when it is due.")


def gpu(settings: dict) -> dict:
    """The GPU as the last real work found it: a failed CUDA run is an Error until a later transcription works on the
    GPU again, and a transcription that ran on the CPU instead is Degraded (slower, and visible, never silent)."""
    try:
        from .. import gpu as gpu_mod

        st = gpu_mod.manager.status(settings)
    except Exception as exc:  # noqa: BLE001 - a broken driver must not break the health page
        return _c("gpu", "GPU (CUDA)", "unknown", f"The GPU could not be read: {exc}"[:200], GPU_FIX)
    if not st["available"]:
        return _c("gpu", "GPU (CUDA)", "error" if not settings.get("autopilot_allow_cpu_fallback") else "degraded",
                  st.get("problem") or "No NVIDIA GPU was found.", st.get("fix") or GPU_FIX, name="")
    name = st.get("name") or "NVIDIA GPU"
    err = st.get("last_error") or {}
    last = st.get("last_transcription") or {}
    worked_at = float(last.get("at") or 0) if last.get("device") == "cuda" else 0.0
    if err and float(err.get("at") or 0) > worked_at:
        text = str(err.get("error") or "no details")
        what = err.get("kind") or "GPU work"
        if any(m in text for m in GPU_BUSY):
            return _c("gpu", "GPU (CUDA)", "degraded", f"The last {what} could not get the GPU: {text}"[:300],
                      "Close other programs that use the GPU (games, video editors, other AI tools); the work waits "
                      "and tries again.", name=name, failed_at=err.get("at"))
        return _c("gpu", "GPU (CUDA)", "error", f"The last {what} on the GPU failed: {text}"[:300],
                  GPU_FIX + " This clears after the next transcription works on the GPU.", name=name,
                  failed_at=err.get("at"))
    if last.get("requested_device") == "cuda" and last.get("device") and last.get("device") != "cuda":
        return _c("gpu", "GPU (CUDA)", "degraded", ("The last transcription ran on the CPU instead of the GPU (much "
                  "slower). " + str(last.get("warning") or "")).strip()[:300], last.get("fix") or GPU_FIX, name=name,
                  fallback_at=last.get("at"))
    if st.get("problem"):
        return _c("gpu", "GPU (CUDA)", "degraded", st["problem"], st.get("fix") or GPU_FIX, name=st.get("name"))
    return _c("gpu", "GPU (CUDA)", "healthy", f"{name} ready" + (" (busy)" if st.get("busy") else ""),
              name=st.get("name"))


def ffmpeg() -> dict:
    from ..pipeline.ffmpeg_utils import find_binary

    exe = find_binary("ffmpeg", db.get_settings().get("ffmpeg_path", ""))
    if not exe:
        return _c("ffmpeg", "FFmpeg", "error", "FFmpeg was not found.",
                  "Install it (winget install Gyan.FFmpeg) or put ffmpeg.exe in tools\\ffmpeg\\bin.")
    return _c("ffmpeg", "FFmpeg", "healthy", "FFmpeg found.")


def disk() -> dict:
    try:
        free = shutil.disk_usage(config.data_dir()).free
    except OSError as exc:
        return _c("disk", "Disk space", "unknown", f"Free space could not be read: {exc}"[:200])
    gb = free / 1e9
    if gb < 2:
        return _c("disk", "Disk space", "error", f"Only {gb:.1f} GB free.", "Free some space; new work waits.",
                  free_gb=round(gb, 1))
    if gb < 10:
        return _c("disk", "Disk space", "degraded", f"{gb:.1f} GB free.", "Free some space soon.", free_gb=round(gb, 1))
    return _c("disk", "Disk space", "healthy", f"{gb:.0f} GB free.", free_gb=round(gb, 1))


def database() -> dict:
    try:
        db.scalar("SELECT 1")
        size = os.path.getsize(config.db_path()) if os.path.exists(config.db_path()) else 0
    except Exception as exc:  # noqa: BLE001
        # No regular backups are made (only a one-time copy before one update), so none is promised here.
        return _c("database", "Database", "error", f"The database could not be read: {exc}"[:200],
                  "Close ClipFoundry and start it again. If it still fails, keep a copy before trying anything else: "
                  f"with ClipFoundry closed, copy the whole data folder ({config.data_dir()}) somewhere safe.")
    return _c("database", "Database", "healthy", f"Readable ({size / 1e6:.0f} MB).")


def accounts(settings: dict) -> dict:
    rows = {p: db.get_account(p) or {} for p in ("youtube", "tiktok")}
    bad = [{"youtube": "YouTube", "tiktok": "TikTok"}[p] for p, a in rows.items()
           if (a.get("info") or {}).get("needs_reconnect")]
    if bad:
        return _c("accounts", "Accounts", "degraded", f"{' and '.join(bad)} need to be connected again.",
                  "Settings → Integrations → Connect again.")
    if not any(a.get("has_tokens") for a in rows.values()):
        # Not a fault: making clips works without accounts, so this does not decide the overall status.
        return _c("accounts", "Accounts", "unknown", "No account is connected (clips stay on this PC).",
                  "Settings → Integrations, when you want uploads.", status_label="Not connected", info=True)
    return _c("accounts", "Accounts", "healthy", "Connected accounts work.")


def audience_incidents() -> dict:
    from ..publish import audience

    halted = [p for p in ("youtube", "tiktok") if audience.halted(p)]
    if halted:
        return _c("audience", "Who can watch", "error", f"Uploads to {', '.join(p.title() for p in halted)} are "
                  "stopped: a video was reported with a wider audience than requested.",
                  "Check it on the platform, then press “I checked it” in Settings → Integrations.")
    return _c("audience", "Who can watch", "healthy", "Uploads go only to the audience you chose.")


def quotas(settings: dict) -> dict:
    try:
        from ..autopilot import quota

        q = quota.status(settings)
    except Exception as exc:  # noqa: BLE001
        return _c("quota", "Platform limits", "unknown", f"Could not be read: {exc}"[:200])
    if q.get("warnings"):
        return _c("quota", "Platform limits", "degraded", str(q["warnings"][0])[:200],
                  "Work that needs it waits for the reset; other work continues.")
    return _c("quota", "Platform limits", "healthy", "Within today's limits.")


def _places(settings: dict) -> list[str]:
    """Where Autopilot looks for videos with the current setup (the same sources trend_scan asks)."""
    from ..autopilot import scout

    places = []
    acc = db.get_account("youtube") or {}
    if settings.get("youtube_api_key") or acc.get("has_tokens"):
        places.append("YouTube")
    if settings.get("tavily_api_key"):
        places.append("web search")
    if settings.get("library_discovery"):
        places.append("the free-license library")
    if scout.discovery_feeds(settings):
        places.append("your folders")
    return places


def discovery(settings: dict) -> dict:
    """Autopilot is on but nothing is happening: it has nowhere to look, or the regular search stopped starting."""
    from ..autopilot import host, state

    label = "Finding videos"
    if not settings.get("autopilot_enabled") or state.paused():
        return _c("discovery", label, "unknown", "Autopilot is off, so it is not looking for videos.",
                  "Press Start when you want it to look.", status_label="Off", info=True)
    places = _places(settings)  # imports scout, which registers the quota's slowdown in PERIOD_ADJUST
    if not places:
        return _c("discovery", label, "error", "Autopilot is on, but it has nowhere to look for videos.",
                  "Put a video in your videos folder (Videos\\ClipFoundry), connect YouTube in Settings → "
                  "Integrations, or turn on the free-license library in Settings → Autopilot.")
    now = time.time()
    where = "Looks in " + ", ".join(places) + "."
    period = 60.0 * float(settings.get("trend_poll_minutes") or 180)
    slower = host.PERIOD_ADJUST.get("trend_scan")  # the quota manager stretches the period near its limit
    if slower:
        period = slower(settings, period)
    for job in db.select("worker_jobs", "kind = 'trend_scan' AND status IN ('running', 'queued', 'retrying', "
                                        "'waiting')", (), "created_at DESC", 5):
        if job["status"] == "running":
            return _c("discovery", label, "healthy", f"Searching for videos now. {where}")
        wake = float(job.get("run_after") or 0)
        if wake > now:  # a platform asked to wait (Retry-After) or a retry backs off: not a fault
            return _c("discovery", label, "healthy", f"The next search starts in {_span(wake - now)}: "
                      f"{job.get('message') or 'a platform asked to wait'}"[:300], next_scan=wake)
    last = float((state.get("trend:last_scan") or {}).get("at") or 0)
    turned_on = max([float(e["at"]) for k in ("autopilot_on", "resumed") for e in state.events(1, kind=k)] or [0.0])
    since = max(last, turned_on, float(state.get("setup:started", 0) or 0))
    if since and now - since > SEARCH_LATE * period:
        return _c("discovery", label, "degraded",
                  (f"The last search for videos was {_span(now - last)} ago" if last >= since else
                   f"No search for videos has run since Autopilot was turned on {_span(now - since)} ago")
                  + f"; it should run every {_span(period)}.",
                  "Check Background work above. If it is running, open Missions → Advanced → Jobs to see why the "
                  "search did not start.", last_scan=last or None)
    return _c("discovery", label, "healthy", where + (f" Last search {_span(now - last)} ago." if last else
                                                      " The first search starts soon."), last_scan=last or None)


def check(settings: dict | None = None) -> dict:
    """All readings and the overall status: the worst reading that counts (`info` readings do not), Unknown only
    when nothing is worse."""
    settings = settings or db.get_settings()
    checks = [scheduler(settings), queue_age(settings), discovery(settings), gpu(settings), ffmpeg(), disk(),
              database(), accounts(settings), audience_incidents(), quotas(settings)]
    counted = [c for c in checks if not c.get("info")]
    worst = max(counted, key=lambda c: ORDER[c["status"]]) if counted else checks[0]
    overall = worst["status"]
    return {"status": overall, "label": LABEL[overall], "checked_at": time.time(),
            "headline": worst["reason"] if overall != "healthy" else "Everything checked is working.",
            "action": worst["action"] if overall != "healthy" else "", "checks": checks}
