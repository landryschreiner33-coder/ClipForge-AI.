"""Measured active stage time from the office's real job transitions, never a hardware speed estimate."""
from __future__ import annotations

import math
import statistics
import time
from collections import defaultdict

from .. import db
from . import roles

ENDS = {"job_done", "job_failed", "job_retry", "job_waiting", "job_canceled"}


def summary(days: int = 7, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    days = max(1, min(14, days))
    events = db.select("office_events", "at >= ? AND type LIKE 'job_%'", (now - days * 86400,),
                       "id ASC", 20_000)
    active: dict[str, tuple[float, str, str]] = {}
    intervals: dict[tuple[str, str], list[float]] = defaultdict(list)
    outcomes: dict[str, int] = defaultdict(int)
    for event in events:
        job = event.get("job_id")
        if not job:
            continue
        kind, typ, at = event.get("kind") or "", event["type"], float(event["at"])
        data = event.get("data") or {}
        if typ == "job_started":
            active[job] = (at, kind, data.get("stage") or "starting")
        elif typ == "job_stage" or typ in ENDS:
            previous = active.pop(job, None)
            if previous is not None and at >= previous[0]:
                intervals[(previous[1], previous[2])].append(at - previous[0])
            if typ == "job_stage" and previous is not None:
                active[job] = (at, kind, data.get("stage") or "working")
            elif typ in ENDS:
                outcomes[typ.removeprefix("job_")] += 1
    stages = []
    for (kind, stage), samples in intervals.items():
        ordered = sorted(samples)
        stages.append({"kind": kind, "stage": stage, "role": roles.role_for(kind, stage),
                       "samples": len(samples), "total_s": round(sum(samples), 2),
                       "median_s": round(statistics.median(samples), 2),
                       "p95_s": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 2)})
    stages.sort(key=lambda row: row["total_s"], reverse=True)
    return {"days": days, "stages": stages, "outcomes": dict(outcomes), "active_jobs": len(active),
            "measured_active_s": round(sum(row["total_s"] for row in stages), 2),
            "note": "Measured active job time on this computer. Waits, incomplete stages and missing history are "
                    "excluded. Parallel times overlap; this is not elapsed time or a prediction for another PC."}
