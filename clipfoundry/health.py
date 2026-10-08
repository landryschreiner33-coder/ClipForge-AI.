"""System Guardian: Healthy / Degraded / Error / Unknown, each with the actual reason and one next action.

Built from stored heartbeats and cheap local checks only (no uploads, no paid calls). A value that cannot be known
here is Unknown, never green. Every check carries `checked_at` so a disconnected page can show that it is stale.
"""
from __future__ import annotations

import shutil
import time

from . import config, db

HEALTHY, DEGRADED, ERROR, UNKNOWN = "Healthy", "Degraded", "Error", "Unknown"
ORDER = {HEALTHY: 0, UNKNOWN: 1, DEGRADED: 2, ERROR: 3}
HEARTBEAT_STALE_S = 120
QUEUE_STALE_S = 6 * 3600


def _c(cid: str, label: str, state: str, reason: str, action: str = "") -> dict:
    return {"id": cid, "label": label, "state": state, "reason": reason, "action": action, "checked_at": time.time()}


def _scheduler(settings: dict) -> dict:
    from .autopilot import state

    beat = float((state.get("host_heartbeat") or {}).get("at") or 0)
    if not settings.get("autopilot_enabled"):
        return _c("scheduler", "Autopilot workers", HEALTHY if beat else UNKNOWN,
                  "Autopilot is off" + ("" if beat else "; the workers have not reported yet"))
    if not beat:
        return _c("scheduler", "Autopilot workers", UNKNOWN, "No heartbeat recorded yet",
                  "Keep ClipFoundry open for a minute; it starts its workers by itself.")
    age = time.time() - beat
    if age > HEARTBEAT_STALE_S:
        return _c("scheduler", "Autopilot workers", ERROR, f"Autopilot is on but the workers last answered "
                  f"{int(age // 60)} min ago", "Restart ClipFoundry. If it repeats, open System → Dev Log.")
    return _c("scheduler", "Autopilot workers", HEALTHY, f"Heartbeat {int(age)} s ago")


def _queue() -> dict:
    now = time.time()
    oldest = db.scalar("SELECT MIN(created_at) FROM worker_jobs WHERE status = 'queued' AND (run_after IS NULL OR "
                       "run_after <= ?)", (now,))
    stalled = int(db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE status = 'running' AND lease_until < ?",
                            (now - 60,)) or 0)
    failed = int(db.scalar("SELECT COUNT(*) FROM worker_jobs WHERE status = 'failed' AND updated_at >= ?",
                           (now - 86400,)) or 0)
    if stalled:
        return _c("queue", "Job queue", DEGRADED, f"{stalled} job(s) stopped reporting (expired lease)",
                  "They are recovered automatically on the next start of the workers.")
    if oldest and now - float(oldest) > QUEUE_STALE_S:
        return _c("queue", "Job queue", DEGRADED, f"A job has waited {int((now - float(oldest)) // 3600)} h to run",
                  "Check that Autopilot is on and not stopped, and that the GPU is free.")
    if failed:
        return _c("queue", "Job queue", DEGRADED, f"{failed} job(s) failed in the last 24 h",
                  "See Queue → Problems for each reason.")
    return _c("queue", "Job queue", HEALTHY, "Jobs are moving")


def _disk() -> dict:
    try:
        free = shutil.disk_usage(config.data_dir()).free / 1e9
    except OSError as exc:
        return _c("disk", "Disk space", UNKNOWN, f"Could not read free space: {exc.__class__.__name__}")
    if free < 2:
        return _c("disk", "Disk space", ERROR, f"Only {free:.1f} GB free", "Free up disk space or move old clips.")
    if free < 10:
        return _c("disk", "Disk space", DEGRADED, f"{free:.1f} GB free", "Consider deleting sources you no longer need.")
    return _c("disk", "Disk space", HEALTHY, f"{free:.0f} GB free")


def _ffmpeg(settings: dict) -> dict:
    from .pipeline.ffmpeg_utils import find_binary

    path = find_binary("ffmpeg", settings.get("ffmpeg_path", ""))
    return _c("ffmpeg", "FFmpeg", HEALTHY, "Found") if path else \
        _c("ffmpeg", "FFmpeg", ERROR, "FFmpeg was not found", "Install FFmpeg (see INSTALL.md) or set its folder.")


def _gpu(settings: dict) -> dict:
    """The last known GPU state, without probing again (a probe can take seconds)."""
    from .pipeline import cuda

    status = getattr(cuda, "_status", None)
    if status is None:
        return _c("gpu", "GPU (CUDA)", UNKNOWN, "Not checked yet in this session",
                  "Open Settings → System to run the GPU check.")
    if status.get("devices", 0) > 0 and status.get("libs_ok"):
        return _c("gpu", "GPU (CUDA)", HEALTHY, "NVIDIA GPU and CUDA libraries found")
    if settings.get("autopilot_allow_cpu_fallback"):
        return _c("gpu", "GPU (CUDA)", DEGRADED, "No usable GPU; transcription falls back to the CPU (slow)",
                  "Check the NVIDIA driver and CUDA libraries (Settings → System).")
    return _c("gpu", "GPU (CUDA)", ERROR, "No usable GPU, and CPU fallback is off",
              "Check the NVIDIA driver and CUDA libraries (Settings → System).")


def _accounts() -> dict:
    bad = [a["platform"] for a in db.select("accounts") if (a.get("info") or {}).get("needs_reconnect")]
    if bad:
        return _c("accounts", "Accounts", DEGRADED, f"{', '.join(bad)} needs to be reconnected",
                  "Settings → Integrations → Reconnect.")
    return _c("accounts", "Accounts", HEALTHY, "No sign-in problems recorded")


def _nvidia(settings: dict) -> dict | None:
    if not settings.get("nvidia_enabled"):
        return None
    from .pipeline import nvidia

    st = nvidia.status(settings)
    if st["state"] == "Connected":
        return _c("nvidia", "NVIDIA AI (optional)", HEALTHY, "Configured; local analysis is the fallback")
    return _c("nvidia", "NVIDIA AI (optional)", DEGRADED, st["blocker"] or st["state"],
              "Local analysis is used meanwhile; see Settings → Integrations.")


def checks(settings: dict | None = None) -> list[dict]:
    settings = settings if settings is not None else db.get_settings()
    out = [_scheduler(settings), _queue(), _disk(), _ffmpeg(settings), _gpu(settings), _accounts()]
    nv = _nvidia(settings)
    if nv:
        out.append(nv)
    out.append(_c("network", "Network", UNKNOWN, "Checked only when a job needs it (no background pings)"))
    return out


def summary(settings: dict | None = None) -> dict:
    items = checks(settings)
    known = [c for c in items if c["id"] != "network"]
    worst = max(known, key=lambda c: ORDER[c["state"]])
    state = worst["state"]
    first = worst if state != HEALTHY else None
    return {"state": state, "reason": first["reason"] if first else "All checks passed",
            "action": first["action"] if first else "", "checks": items, "checked_at": time.time()}
