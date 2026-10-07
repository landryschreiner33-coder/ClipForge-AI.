"""System Guardian (PATCH): health readings with a status, the actual reason and the next step.

Statuses are Healthy, Degraded, Error or Unknown. A reading that could not be taken is Unknown, never green. Every
reading carries the time it was taken, so a page that stopped receiving updates can show it as stale.
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


def _c(cid: str, label: str, status: str, reason: str, action: str = "", **data: object) -> dict:
    return {"id": cid, "label": label, "status": status, "status_label": LABEL[status], "reason": reason,
            "action": action, "checked_at": time.time(), **data}


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
    try:
        from .. import gpu as gpu_mod

        st = gpu_mod.manager.status(settings)
    except Exception as exc:  # noqa: BLE001 - a broken driver must not break the health page
        return _c("gpu", "GPU (CUDA)", "unknown", f"The GPU could not be read: {exc}"[:200],
                  "Run: .venv\\Scripts\\python.exe -m clipfoundry gpu-check")
    if not st["available"]:
        return _c("gpu", "GPU (CUDA)", "error" if not settings.get("autopilot_allow_cpu_fallback") else "degraded",
                  st.get("problem") or "No NVIDIA GPU was found.",
                  st.get("fix") or "Run: .venv\\Scripts\\python.exe -m clipfoundry gpu-check", name="")
    if st.get("problem"):
        return _c("gpu", "GPU (CUDA)", "degraded", st["problem"], st.get("fix") or "", name=st.get("name"))
    return _c("gpu", "GPU (CUDA)", "healthy", f"{st.get('name') or 'NVIDIA GPU'} ready"
              + (" (busy)" if st.get("busy") else ""), name=st.get("name"))


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
        return _c("database", "Database", "error", f"The database could not be read: {exc}"[:200],
                  "Close ClipFoundry and start it again; your data folder keeps a copy in data\\backups.")
    return _c("database", "Database", "healthy", f"Readable ({size / 1e6:.0f} MB).")


def accounts(settings: dict) -> dict:
    rows = {p: db.get_account(p) or {} for p in ("youtube", "tiktok")}
    bad = [{"youtube": "YouTube", "tiktok": "TikTok"}[p] for p, a in rows.items()
           if (a.get("info") or {}).get("needs_reconnect")]
    if bad:
        return _c("accounts", "Accounts", "degraded", f"{' and '.join(bad)} need to be connected again.",
                  "Settings → Integrations → Connect again.")
    if not any(a.get("has_tokens") for a in rows.values()):
        return _c("accounts", "Accounts", "unknown", "No account is connected (clips stay on this PC).",
                  "Settings → Integrations, when you want uploads.")
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


def check(settings: dict | None = None) -> dict:
    """All readings and the overall status (the worst one; Unknown only when nothing is worse)."""
    settings = settings or db.get_settings()
    checks = [scheduler(settings), queue_age(settings), gpu(settings), ffmpeg(), disk(), database(),
              accounts(settings), audience_incidents(), quotas(settings)]
    worst = max(checks, key=lambda c: ORDER[c["status"]])
    overall = worst["status"]
    return {"status": overall, "label": LABEL[overall], "checked_at": time.time(),
            "headline": worst["reason"] if overall != "healthy" else "Everything checked is working.",
            "action": worst["action"] if overall != "healthy" else "", "checks": checks}
