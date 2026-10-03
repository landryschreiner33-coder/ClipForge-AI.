"""Trend signals: normalization, topics and the Trend Score.

The Trend Score values momentum over size: a recent video gaining views quickly outranks a large video that stopped
growing. Every metric carries its provenance:

* observed     reported by the platform at a known time
* estimated    derived by ClipFoundry (e.g. average views per hour since upload, when only one reading exists)
* unavailable  the platform does not report it (never filled in with a guess)

YouTube's Developer Policies do not allow API data to be used to create derived metrics without Google's approval.
For YouTube signals the momentum score is therefore computed only when you confirm that your Google Cloud project
has that approval; otherwise YouTube results keep YouTube's own order ("platform order") and are shown exactly as
YouTube reported them.
"""
from __future__ import annotations

import math
import time
from collections import Counter

from ..pipeline.text_utils import content_tokens

MOMENTUM, PLATFORM_ORDER = "momentum", "platform_order"
DERIVED_NOTE = ("Ranked by YouTube's own order. YouTube's Developer Policies do not allow metrics derived from "
                "YouTube API data without Google's approval; turn on 'Google approved derived metrics' in Settings "
                "only if your project has it.")
DERIVED_DISCLOSURE = "Scores are calculated by ClipFoundry; they are not YouTube metrics."
YOUTUBE_CATEGORIES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
    "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}
WEIGHTS = {"velocity": 0.35, "acceleration": 0.10, "engagement": 0.12, "recency": 0.18, "live": 0.10,
           "size": 0.05, "recurrence": 0.10}
TOPIC_NOISE = {"official", "video", "full", "episode", "ep", "part", "live", "stream", "highlights", "new", "vs",
               "shorts", "short", "clip", "clips", "podcast", "show", "watch", "today", "2024", "2025", "2026"}


def m(value: float | int | None, status: str = "observed", note: str = "", at: float | None = None,
      source: str = "") -> dict:
    """One metric with its provenance: who reported it (`source`) and when it was observed (`at`). A number the
    source did not report stays unknown (None), with the reason in `note`."""
    if value is None:
        return {"value": None, "status": "unavailable", "note": note, "at": at, "source": source}
    return {"value": value, "status": status, "note": note, "at": at or time.time(), "source": source}


def val(metrics: dict, key: str) -> float | None:
    v = (metrics.get(key) or {}).get("value")
    return None if v is None else float(v)


def derived_allowed(platform: str, settings: dict) -> bool:
    return platform != "youtube" or bool(settings.get("youtube_derived_metrics_approved"))


def keywords(title: str, tags: list[str] | None = None, top: int = 5) -> list[str]:
    toks = [t for t in content_tokens(f"{title} {' '.join(tags or [])}") if not t.isdigit() and len(t) > 2
            and t not in TOPIC_NOISE]
    return [w for w, _ in Counter(toks).most_common(top)]


def recurrence(signals: list[dict]) -> dict[str, int]:
    """For each signal: how many *other creators'* signals share one of its two main keywords (a topic that shows
    up across sources is gaining attention, not one channel's campaign)."""
    owners: dict[str, set[str]] = {}
    for s in signals:
        for k in (s.get("keywords") or [])[:2]:
            owners.setdefault(k, set()).add(s.get("channel_id") or s["id"])
    out = {}
    for s in signals:
        me = s.get("channel_id") or s["id"]
        out[s["id"]] = max((len(owners.get(k, set()) - {me}) for k in (s.get("keywords") or [])[:2]), default=0)
    return out


def topic_label(signal: dict, signals: list[dict]) -> str:
    counts = Counter(k for s in signals for k in (s.get("keywords") or [])[:2])
    ks = signal.get("keywords") or []
    if not ks:
        return ""
    return max(ks[:3], key=lambda k: (counts[k], -ks.index(k)))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def velocity(metrics: dict, history: list[dict], published_at: float | None, now: float) -> tuple[float | None, str,
                                                                                                    float | None]:
    """(views per hour, provenance, acceleration). Two readings at least 20 minutes apart give an observed
    velocity; otherwise the average since upload is an estimate."""
    pts = sorted((h for h in history if h.get("views") is not None), key=lambda h: h["at"])
    if len(pts) >= 2 and pts[-1]["at"] - pts[0]["at"] >= 1200:
        last = pts[-1]
        prev = next((p for p in reversed(pts[:-1]) if last["at"] - p["at"] >= 1200), pts[0])
        v1 = max(0.0, (last["views"] - prev["views"]) / ((last["at"] - prev["at"]) / 3600))
        accel = None
        older = [p for p in pts if prev["at"] - p["at"] >= 1200]
        if older:
            p0 = older[-1]
            v0 = max(0.0, (prev["views"] - p0["views"]) / ((prev["at"] - p0["at"]) / 3600))
            accel = (v1 - v0) / max(v0, 1.0)
        return v1, "observed", accel
    views = val(metrics, "views")
    if views is not None and published_at:
        return views / max(1.0, (now - published_at) / 3600), "estimated", None
    return None, "unavailable", None


def score(signal: dict, history: list[dict], settings: dict, recurring: int = 0, now: float | None = None) -> dict:
    """{"score", "mode", "components", "notes"} for one signal (0-100)."""
    now = now or time.time()
    metrics = signal.get("metrics") or {}
    if not derived_allowed(signal["platform"], settings):
        rank, size = signal.get("platform_rank"), (signal.get("raw") or {}).get("list_size") or 50
        order = 100.0 * (size - (rank or size) + 1) / size if rank else 0.0
        return {"score": round(order, 1), "mode": PLATFORM_ORDER,
                "components": {"platform_order": {"value": round(order / 100, 3), "weight": 1.0, "status": "observed",
                                                  "note": f"#{rank} of {size} in YouTube's list" if rank else ""}},
                "notes": [DERIVED_NOTE]}
    comps: dict[str, dict] = {}
    notes: list[str] = []
    vel, vel_status, accel = velocity(metrics, history, signal.get("published_at"), now)
    if vel is not None:
        comps["velocity"] = {"value": _clamp(math.log10(1 + vel) / math.log10(1 + 50_000)), "status": vel_status,
                             "note": f"{vel:,.0f} views/hour" + (" (average since upload)" if vel_status ==
                                                                 "estimated" else "")}
    if accel is not None:
        comps["acceleration"] = {"value": _clamp(0.5 + 0.5 * math.tanh(accel)), "status": "observed",
                                 "note": f"{accel:+.0%} change in views/hour"}
    views, likes, comments = val(metrics, "views"), val(metrics, "likes"), val(metrics, "comments")
    if views and likes is not None:
        rate = (likes + 2 * (comments or 0)) / views
        comps["engagement"] = {"value": _clamp(rate / 0.08), "status": "observed" if comments is not None else
                               "estimated", "note": f"{rate:.1%} likes+comments per view"}
    if signal.get("published_at"):
        age_h = max(0.0, (now - signal["published_at"]) / 3600)
        comps["recency"] = {"value": math.exp(-age_h / 36), "status": "observed", "note": f"{age_h:.0f} h old"}
    live = val(metrics, "live_viewers")
    if signal.get("kind") == "live" and live is not None:
        comps["live"] = {"value": _clamp(math.log10(1 + live) / 5), "status": "observed",
                         "note": f"{live:,.0f} watching now"}
    if views is not None:
        comps["size"] = {"value": _clamp(math.log10(1 + views) / 7), "status": "observed", "note": f"{views:,.0f} views"}
    comps["recurrence"] = {"value": _clamp(recurring / 4), "status": "observed",
                           "note": f"topic seen from {recurring} other creator(s)" if recurring else "only source"}
    total_w = sum(WEIGHTS[k] for k in comps)
    value = sum(WEIGHTS[k] * c["value"] for k, c in comps.items()) / total_w if total_w else 0.0
    for k in comps:
        comps[k]["weight"] = WEIGHTS[k]
        comps[k]["value"] = round(comps[k]["value"], 3)
    missing = [k for k in ("velocity", "engagement", "recency") if k not in comps]
    if missing:
        notes.append("Not reported, so not counted: " + ", ".join(missing) + ".")
    if signal["platform"] == "youtube":
        notes.append(DERIVED_DISCLOSURE)
    return {"score": round(100 * value, 1), "mode": MOMENTUM, "components": comps, "notes": notes}
