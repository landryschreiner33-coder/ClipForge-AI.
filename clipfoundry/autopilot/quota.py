"""YouTube Data API quota manager.

Google gives every Cloud project a daily quota that resets at midnight Pacific Time. Since June 1, 2026 it has three
buckets: `videos.insert` calls (uploads), `search.list` calls, and units for every other method. ClipFoundry

* counts every call it makes, by method and purpose (publish, account, stats, discovery),
* enforces the budgets configured in Settings (set them to your project's real quota),
* limits discovery to a share of each bucket and never lets it eat the quota needed for publishing, statistics and
  account checks,
* caches recent discovery answers and never sends the same discovery request twice while it is fresh,
* slows trend polling down as discovery approaches its share, and stops it when the share is used,
* believes YouTube over its own count: when YouTube answers `quotaExceeded`, that bucket is treated as empty until the
  next reset, and nothing claims quota is available when it is not.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .. import db
from . import state

PACIFIC = ZoneInfo("America/Los_Angeles")

# method -> (bucket, cost in that bucket's unit)
COSTS: dict[str, tuple[str, int]] = {
    "videos.insert": ("uploads", 1),
    "search.list": ("search", 1),
    "videos.list": ("default", 1),
    "channels.list": ("default", 1),
    "playlistItems.list": ("default", 1),
    "videoCategories.list": ("default", 1),
    "videos.update": ("default", 50),
    "videos.delete": ("default", 50),
    "thumbnails.set": ("default", 50),
    "analytics.reports": ("analytics", 1),  # YouTube Analytics API: a separate API with its own quota
}
BUCKETS = ("default", "uploads", "search")
BUCKET_LABELS = {"default": "API units (all other methods)", "uploads": "Uploads (videos.insert calls)",
                 "search": "Searches (search.list calls)"}
PURPOSES = ("publish", "account", "stats", "discovery")
RESERVE_PER_UPLOAD = 3        # default-bucket units a scheduled upload may need (status checks, channel)
RESERVE_STATS = 100           # default-bucket units kept for statistics refreshes and account checks


class QuotaDenied(Exception):
    def __init__(self, message: str, bucket: str, retry_at: float):
        super().__init__(message)
        self.bucket = bucket
        self.retry_at = retry_at


def day_key(now: float | None = None) -> str:
    return dt.datetime.fromtimestamp(now or time.time(), PACIFIC).date().isoformat()


def next_reset(now: float | None = None) -> float:
    local = dt.datetime.fromtimestamp(now or time.time(), PACIFIC)
    tomorrow = (local + dt.timedelta(days=1)).date()
    return dt.datetime.combine(tomorrow, dt.time(0, 0), PACIFIC).timestamp()


def budgets(settings: dict) -> dict[str, int]:
    return {"default": int(settings.get("youtube_quota_default", 10000)),
            "uploads": int(settings.get("youtube_quota_uploads", 100)),
            "search": int(settings.get("youtube_quota_search", 100))}


def discovery_allowance(settings: dict) -> dict[str, int]:
    b = budgets(settings)
    return {"default": int(b["default"] * float(settings.get("youtube_discovery_share", 40)) / 100),
            "uploads": 0,
            "search": int(b["search"] * float(settings.get("youtube_search_discovery_share", 90)) / 100)}


def usage(day: str | None = None) -> dict[str, dict[str, Any]]:
    day = day or day_key()
    rows = db.select("quota_usage", "day = ?", (day,))
    out: dict[str, dict[str, Any]] = {b: {"units": 0, "calls": 0, "by_method": {}, "by_purpose": {}}
                                      for b in (*BUCKETS, "analytics")}
    for r in rows:
        b = out.setdefault(r["bucket"], {"units": 0, "calls": 0, "by_method": {}, "by_purpose": {}})
        b["units"] += r["units"]
        b["calls"] += r["calls"]
        b["by_method"][r["method"]] = b["by_method"].get(r["method"], 0) + r["units"]
        b["by_purpose"][r["purpose"]] = b["by_purpose"].get(r["purpose"], 0) + r["units"]
    return out


def _exhausted_key(bucket: str, day: str) -> str:
    return f"quota:exhausted:{day}:{bucket}"


def exhausted(bucket: str, now: float | None = None) -> bool:
    return bool(state.get(_exhausted_key(bucket, day_key(now))))


def planned_uploads_today(now: float | None = None) -> int:
    """YouTube posts still scheduled before the next quota reset (they need upload quota)."""
    now = now or time.time()
    return int(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE platform = 'youtube' AND status IN "
                         "('approved', 'awaiting_approval', 'planned') AND planned_at < ?", (next_reset(now),)) or 0)


def reserve(settings: dict, bucket: str, now: float | None = None) -> int:
    """Quota discovery must leave untouched in a bucket (for publishing, statistics and account checks)."""
    if bucket == "default":
        return RESERVE_STATS + RESERVE_PER_UPLOAD * planned_uploads_today(now)
    if bucket == "uploads":
        return budgets(settings)["uploads"]
    return 0


def check(method: str, purpose: str, settings: dict | None = None, calls: int = 1, now: float | None = None) -> None:
    """Raise QuotaDenied when this call would break a budget or YouTube already reported the bucket empty."""
    now = now or time.time()
    settings = settings if settings is not None else db.get_settings()
    bucket, unit = COSTS.get(method, ("default", 1))
    cost = unit * calls
    if bucket == "analytics":
        return  # separate API and quota; YouTube reports if it runs out
    reset = next_reset(now)
    if exhausted(bucket, now):
        raise QuotaDenied(f"YouTube reported today's {BUCKET_LABELS[bucket].lower()} quota as used up.", bucket, reset)
    used = usage(day_key(now))[bucket]
    budget = budgets(settings)[bucket]
    if used["units"] + cost > budget:
        raise QuotaDenied(f"Today's budget for {BUCKET_LABELS[bucket].lower()} is used ({used['units']} of {budget}).",
                          bucket, reset)
    if purpose == "discovery":
        allowance = discovery_allowance(settings)[bucket]
        disc = used["by_purpose"].get("discovery", 0)
        if disc + cost > allowance:
            raise QuotaDenied(f"Discovery used its share of today's {BUCKET_LABELS[bucket].lower()} "
                              f"({disc} of {allowance}).", bucket, reset)
        if budget - used["units"] - cost < reserve(settings, bucket, now):
            raise QuotaDenied("Keeping the rest of today's quota for publishing, statistics and account checks.",
                              bucket, reset)


def record(method: str, purpose: str, calls: int = 1, now: float | None = None) -> None:
    now = now or time.time()
    bucket, unit = COSTS.get(method, ("default", 1))
    with db.connect() as conn:
        conn.execute("INSERT INTO quota_usage (day, bucket, method, purpose, units, calls, last_at) VALUES "
                     "(?,?,?,?,?,?,?) ON CONFLICT(day, bucket, method, purpose) DO UPDATE SET units = units + "
                     "excluded.units, calls = calls + excluded.calls, last_at = excluded.last_at",
                     (day_key(now), bucket, method, purpose, unit * calls, calls, now))


def charge(method: str, purpose: str, settings: dict | None = None) -> None:
    """check() + record() for one call about to be sent."""
    check(method, purpose, settings)
    record(method, purpose)


def mark_exhausted(method: str, detail: str = "", now: float | None = None) -> None:
    """YouTube answered quotaExceeded: trust it until the next reset."""
    bucket = COSTS.get(method, ("default", 1))[0]
    day = day_key(now)
    if not state.get(_exhausted_key(bucket, day)):
        state.put(_exhausted_key(bucket, day), {"at": time.time(), "method": method, "detail": detail[:300]})
        state.action(f"quota:{bucket}:{day}", "quota", f"YouTube quota used up: {BUCKET_LABELS[bucket]}",
                     f"YouTube reported the {BUCKET_LABELS[bucket].lower()} quota of your Google Cloud project as used "
                     "up for today. Calls that need it wait until midnight Pacific Time.",
                     "Wait for the reset, or request more quota in the Google Cloud console and raise the budget in "
                     "Settings → Autopilot → YouTube quota.", level="warning")


# ------------------------------------------------------------------ discovery helpers
def cached(key_parts: Any, ttl: float, fetch: Callable[[], Any], method: str = "") -> tuple[Any, bool]:
    """(response, from_cache). Equivalent requests share one fresh answer (de-duplication)."""
    key = hashlib.sha1(json.dumps(key_parts, sort_keys=True, default=str).encode()).hexdigest()
    now = time.time()
    row = db.fetch("api_cache", key, "key")
    if row and row["expires_at"] > now:
        _count("cache_hits")
        return json.loads(row["response"]), True
    data = fetch()
    db.execute("INSERT OR REPLACE INTO api_cache (key, method, response, fetched_at, expires_at) VALUES (?,?,?,?,?)",
               (key, method, json.dumps(data), now, now + ttl))
    return data, False


def _count(name: str) -> None:
    day = day_key()
    counters = state.get(f"quota:counters:{day}", {}) or {}
    counters[name] = counters.get(name, 0) + 1
    state.put(f"quota:counters:{day}", counters)


def discovery_period_factor(settings: dict, now: float | None = None) -> float:
    """How much to stretch the trend polling interval: 1 = normal, larger = slower, inf = stop until reset."""
    now = now or time.time()
    used = usage(day_key(now))
    allow = discovery_allowance(settings)
    worst = 0.0
    for bucket in ("default", "search"):
        if exhausted(bucket, now):
            return float("inf")
        if allow[bucket] > 0:
            worst = max(worst, used[bucket]["by_purpose"].get("discovery", 0) / allow[bucket])
    if worst >= 1.0:
        return float("inf")
    return 4.0 if worst >= 0.85 else 2.0 if worst >= 0.6 else 1.0


def status(settings: dict, now: float | None = None) -> dict:
    now = now or time.time()
    day = day_key(now)
    used = usage(day)
    b = budgets(settings)
    allow = discovery_allowance(settings)
    reset = next_reset(now)
    local = dt.datetime.fromtimestamp(now, PACIFIC)
    start = dt.datetime.combine(local.date(), dt.time(0, 0), PACIFIC).timestamp()
    frac_day = max(0.05, (now - start) / max(1.0, reset - start))
    uploads_planned = planned_uploads_today(now)
    buckets = {}
    warnings: list[str] = []
    for name in BUCKETS:
        u = used[name]
        projected = u["units"] / frac_day
        if name == "uploads":
            projected = u["units"] + uploads_planned
        entry = {"label": BUCKET_LABELS[name], "budget": b[name], "used": u["units"], "calls": u["calls"],
                 "remaining": max(0, b[name] - u["units"]), "by_method": u["by_method"], "by_purpose": u["by_purpose"],
                 "discovery_used": u["by_purpose"].get("discovery", 0), "discovery_allowance": allow[name],
                 "reserve": reserve(settings, name, now), "projected": round(projected),
                 "exhausted": exhausted(name, now)}
        if entry["exhausted"]:
            warnings.append(f"YouTube reported the {entry['label'].lower()} quota as used up until the reset.")
        elif b[name] and projected > b[name]:
            warnings.append(f"At this rate, {entry['label'].lower()} will run out before the reset "
                            f"(projected {round(projected)} of {b[name]}).")
        buckets[name] = entry
    factor = discovery_period_factor(settings, now)
    if factor == float("inf"):
        warnings.append("Trend discovery is paused until the quota resets, to keep quota for publishing.")
    elif factor > 1:
        warnings.append(f"Trend discovery runs {factor:.0f}x less often to stay within its share of the quota.")
    return {"day": day, "resets_at": reset, "buckets": buckets, "analytics_calls": used["analytics"]["calls"],
            "planned_uploads": uploads_planned, "discovery_slowdown": None if factor == float("inf") else factor,
            "discovery_paused": factor == float("inf"), "warnings": warnings,
            "cache": state.get(f"quota:counters:{day}", {}) or {},
            "note": "Counted by ClipFoundry from the calls it made. Set the budgets to your Google Cloud project's "
                    "real quota (Google Cloud console → APIs & Services → YouTube Data API v3 → Quotas)."}
