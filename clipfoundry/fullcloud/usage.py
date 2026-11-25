"""Worker time: what each Full Cloud job used, the estimate before it starts, and the monthly limit
(Settings → Processing).

ClipForge cannot know what the owner's provider charges, so the price is the owner's own number (an hour of the
worker); without it, estimates are in time only. Worker time is measured on the worker, from the job's start there
to its end (waiting in its queue and moving files are not counted). The estimate comes from earlier jobs on this
worker (worker seconds for each second of video, the middle of the last ten), or DEFAULT_RATIO before there are any.
"""
from __future__ import annotations

import calendar
import statistics
import time

from .. import db

DEFAULT_RATIO = 0.6       # worker seconds per second of video, before this worker has done a job
MIN_SECONDS = 60.0         # starting up, reading and writing: even a short video takes about a minute
DONE = ("done",)


def month_start(now: float | None = None) -> float:
    t = time.localtime(now or time.time())
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def month_end(now: float | None = None) -> float:
    t = time.localtime(now or time.time())
    days = calendar.monthrange(t.tm_year, t.tm_mon)[1]
    return time.mktime((t.tm_year, t.tm_mon, days, 23, 59, 59, 0, 0, -1))


def used_seconds(workspace_id: str = "local", now: float | None = None) -> float:
    """Worker time used this month (jobs that are running count what they used so far)."""
    total = 0.0
    for r in db.select("cloud_runs", "workspace_id = ? AND started_at >= ?", (workspace_id, month_start(now))):
        total += float(r.get("seconds") or 0)
    return round(total, 1)


def ratio(worker: str) -> float:
    rows = db.select("cloud_runs", "worker = ? AND status = 'done' AND kind = 'project' AND seconds > 0",
                     (worker,), order="started_at DESC", limit=10)
    seen = [float(r["seconds"]) / float((r.get("info") or {}).get("video_seconds") or 0)
            for r in rows if float((r.get("info") or {}).get("video_seconds") or 0) > 0]
    return round(statistics.median(seen), 3) if seen else DEFAULT_RATIO


def estimate(video_seconds: float | None, worker: str, settings: dict) -> dict:
    """{"seconds", "cost", "price", "ratio", "known"}: about how long the job takes on the worker, and what it
    costs at the owner's price (None when no price is set or the video's length is not known yet)."""
    price = float(settings.get("worker_price_per_hour") or 0)
    r = ratio(worker)
    if not video_seconds:
        return {"seconds": None, "cost": None, "price": price or None, "ratio": r, "known": False}
    secs = max(MIN_SECONDS, float(video_seconds) * r)
    return {"seconds": round(secs), "cost": round(secs / 3600 * price, 2) if price else None,
            "price": price or None, "ratio": r, "known": True}


def limit_problem(settings: dict, workspace_id: str = "local", need_seconds: float | None = None) -> str:
    """Why a job may not start because of the monthly limit ("" when it may)."""
    hours = float(settings.get("worker_month_hours") or 0)
    if hours <= 0:
        return "Worker time is set to 0 hours a month (Settings → Processing), so nothing is sent to the worker."
    used = used_seconds(workspace_id)
    left = hours * 3600 - used
    if left <= 0:
        return (f"This month's worker time ({hours:g} h) is used up. Raise it in Settings → Processing, or switch "
                "to Local to make the clips on this computer.")
    if need_seconds and need_seconds > left:
        return (f"This video needs about {_mins(need_seconds)} of worker time, and {_mins(left)} is left this month "
                f"(of {hours:g} h). Raise the limit in Settings → Processing, or switch to Local.")
    return ""


def _mins(seconds: float) -> str:
    m = max(1, round(seconds / 60))
    return f"{m} minute{'s' if m != 1 else ''}" if m < 120 else f"{m / 60:.1f} hours"


def view(settings: dict, workspace_id: str = "local") -> dict:
    used = used_seconds(workspace_id)
    hours = float(settings.get("worker_month_hours") or 0)
    price = float(settings.get("worker_price_per_hour") or 0)
    runs = db.select("cloud_runs", "workspace_id = ?", (workspace_id,), order="started_at DESC", limit=12)
    return {"used_seconds": used, "limit_hours": hours, "price_per_hour": price or None,
            "cost": round(used / 3600 * price, 2) if price else None, "resets_at": month_end() + 1,
            "runs": [{k: r.get(k) for k in ("id", "kind", "project_id", "worker", "status", "started_at", "ended_at",
                                             "seconds", "uploaded_bytes")} | {"cost": round(float(r["seconds"] or 0)
                                                                                         / 3600 * price, 2)
                                                                               if price else None}
                     for r in runs]}


def start(kind: str, worker: str, project_id: str = "", estimate_: dict | None = None,
          workspace_id: str = "local") -> dict:
    return db.insert("cloud_runs", {"workspace_id": workspace_id, "kind": kind, "project_id": project_id,
                                    "worker": worker, "status": "starting", "started_at": time.time(),
                                    "estimate": estimate_ or {}, "info": {}})


def update(run_id: str, **fields) -> None:
    if not run_id:
        return
    if "info" in fields:
        row = db.fetch("cloud_runs", run_id) or {}
        fields["info"] = {**(row.get("info") or {}), **fields["info"]}
    db._update("cloud_runs", run_id, fields)  # noqa: SLF001


def measured(job: dict) -> float:
    """Worker time of a job, from its own start and end on the worker (so far, while it runs)."""
    start_at = float(job.get("started_at") or 0)
    if not start_at:
        return 0.0
    end_at = float(job.get("ended_at") or 0) or float(job.get("now") or 0) or time.time()  # the worker's clock
    return round(max(0.0, end_at - start_at), 1)
