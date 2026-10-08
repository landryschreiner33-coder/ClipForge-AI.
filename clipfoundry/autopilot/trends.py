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

Sparse data never looks strong (`combine`): a part without data counts as the neutral 0.5, so a score is the average
of the parts with data shrunk toward 50 by the share of the documented weight that had none (its coverage). Each
score also says how far it can be trusted in words (`confidence`), never as an invented percentage.
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
NEUTRAL = 0.5             # what a part without data counts as: neither a strong nor a weak sign
MIN_GAP = 1200            # readings closer than 20 minutes apart say nothing about views per hour
HIGH_COVERAGE, MEDIUM_COVERAGE = 0.75, 0.5
CONFIDENCE_NOTE = {"high": "high", "medium": "medium", "low": "low (too little data: the score stays near 50)"}


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


def combine(parts: dict[str, dict], weights: dict[str, float]) -> tuple[float, float]:
    """(value 0-1, coverage 0-1) of the parts that apply. A part with `value` None had no data; `quality` (0-1,
    default 1) is how much of a part's own evidence was there (the Source Score's trend part carries the Trend
    Score's coverage):

        coverage = Σ weight × quality over the parts with data ÷ Σ weight over the parts that apply
        value    = Σ weight × value over all parts ÷ Σ weight, a part without data counting as NEUTRAL

    so a part without data pulls the score toward 50 instead of being left out (which let two good numbers look
    like complete evidence) or counted as 0 (which would call it weak). With coverage c (every quality 1) the score
    stays between 50 × (1 − c) and 50 + 50 × c. Quality only lowers coverage: a trend part's value is already
    shrunk."""
    total = sum(weights[k] for k in parts)
    if not total:
        return NEUTRAL, 0.0
    value = sum(weights[k] * (NEUTRAL if p["value"] is None else p["value"]) for k, p in parts.items()) / total
    known = sum(weights[k] * float(p.get("quality", 1.0)) for k, p in parts.items() if p["value"] is not None)
    return value, known / total


def confidence(coverage: float, readings: int) -> str:
    """How far a score can be trusted, in words (never an invented percentage):

    * high    at least 75% of the weighted parts had data, and two readings at least 20 minutes apart
    * medium  at least half of the weighted parts had data, and at least one reading of the numbers
    * low     anything less
    """
    if coverage >= HIGH_COVERAGE and readings >= 2:
        return "high"
    if coverage >= MEDIUM_COVERAGE and readings >= 1:
        return "medium"
    return "low"


def spaced_readings(times: list[float]) -> int:
    """How many timestamped readings are at least MIN_GAP apart (repeated readings minutes apart count once)."""
    count, last = 0, None
    for at in sorted(times):
        if last is None or at - last >= MIN_GAP:
            count, last = count + 1, at
    return count


def evidence(coverage: float, readings: int, missing: dict[str, str]) -> dict:
    """What a score stands on, stored with its parts (key "evidence", weight 0 so it never counts as a part)."""
    level = confidence(coverage, readings)
    summary = (f"{coverage:.0%} of the weighted parts had data; {readings} reading{'s' if readings != 1 else ''}; "
               f"confidence {CONFIDENCE_NOTE[level]}")
    note = summary + (". Counted as neutral (no data): " + "; ".join(f"{k} ({why})" for k, why in missing.items())
                      if missing else "")
    return {"value": round(coverage, 3), "weight": 0.0, "status": "summary", "coverage": round(coverage, 3),
            "confidence": level, "readings": readings, "missing": missing, "summary": summary, "note": note}


def _result(value: float, mode: str, comps: dict[str, dict], notes: list[str], coverage: float, readings: int,
            weights: dict[str, float]) -> dict:
    """The score with the parts that had data in `components`, and the missing parts with their reason (None is
    never shown as a number)."""
    missing = {k: c["note"] for k, c in comps.items() if c["value"] is None}
    have = {k: c for k, c in comps.items() if c["value"] is not None}
    for k, c in have.items():
        c["weight"] = weights[k]
        c["value"] = round(c["value"], 3)
    ev = evidence(coverage, readings, missing)
    if missing:
        notes.append("No data yet, counted as neutral (50): " + ", ".join(missing) + ".")
    notes.append(f"Evidence: {ev['summary']}.")
    return {"score": round(100 * value, 1), "mode": mode, "components": have, "notes": notes,
            "coverage": ev["coverage"], "confidence": ev["confidence"], "readings": readings, "missing": missing,
            "evidence": ev}


def velocity(metrics: dict, history: list[dict], published_at: float | None, now: float) -> tuple[float | None, str,
                                                                                                    float | None]:
    """(views per hour, provenance, acceleration). Two readings at least 20 minutes apart give an observed
    velocity; otherwise the average since upload is an estimate."""
    pts = sorted((h for h in history if h.get("views") is not None), key=lambda h: h["at"])
    if len(pts) >= 2 and pts[-1]["at"] - pts[0]["at"] >= MIN_GAP:
        last = pts[-1]
        prev = next((p for p in reversed(pts[:-1]) if last["at"] - p["at"] >= MIN_GAP), pts[0])
        v1 = max(0.0, (last["views"] - prev["views"]) / ((last["at"] - prev["at"]) / 3600))
        accel = None
        older = [p for p in pts if prev["at"] - p["at"] >= MIN_GAP]
        if older:
            p0 = older[-1]
            v0 = max(0.0, (prev["views"] - p0["views"]) / ((prev["at"] - p0["at"]) / 3600))
            accel = (v1 - v0) / max(v0, 1.0)
        return v1, "observed", accel
    views = val(metrics, "views")
    if views is not None and published_at:
        return views / max(1.0, (now - published_at) / 3600), "estimated", None
    return None, "unavailable", None


def _metric_why(metrics: dict, key: str, fallback: str) -> str:
    return (metrics.get(key) or {}).get("note") or fallback


def score(signal: dict, history: list[dict], settings: dict, recurring: int = 0, now: float | None = None) -> dict:
    """{"score", "mode", "components", "notes", "coverage", "confidence", "readings", "missing", "evidence"} for one
    signal (0-100). `components` holds the parts that had data; `missing` names the others with the reason."""
    now = now or time.time()
    metrics = signal.get("metrics") or {}
    if not derived_allowed(signal["platform"], settings):
        rank, size = signal.get("platform_rank"), (signal.get("raw") or {}).get("list_size") or 50
        weights = {"platform_order": 1.0}
        if rank:
            part = {"value": _clamp((size - rank + 1) / size), "status": "observed",
                    "note": f"#{rank} of {size} in YouTube's list"}
        else:  # no position in a list is unknown, not last place
            part = {"value": None, "status": "unavailable", "note": "YouTube gave no list position"}
        ranked = [h["at"] for h in history if h.get("platform_rank") is not None]
        readings = max(spaced_readings(ranked), 1 if rank else 0)
        value, coverage = combine({"platform_order": part}, weights)
        return _result(value, PLATFORM_ORDER, {"platform_order": part}, [DERIVED_NOTE], coverage, readings, weights)
    comps: dict[str, dict] = {}
    notes: list[str] = []
    vel, vel_status, accel = velocity(metrics, history, signal.get("published_at"), now)
    views, likes, comments = val(metrics, "views"), val(metrics, "likes"), val(metrics, "comments")
    if vel is not None:
        comps["velocity"] = {"value": _clamp(math.log10(1 + vel) / math.log10(1 + 50_000)), "status": vel_status,
                             "note": f"{vel:,.0f} views/hour" + (" (average since upload)" if vel_status ==
                                                                 "estimated" else "")}
    else:
        comps["velocity"] = {"value": None, "status": "unavailable",
                             "note": _metric_why(metrics, "views", "no view counts") if views is None else
                             "no upload time and no second reading"}
    if accel is not None:
        comps["acceleration"] = {"value": _clamp(0.5 + 0.5 * math.tanh(accel)), "status": "observed",
                                 "note": f"{accel:+.0%} change in views/hour"}
    else:
        comps["acceleration"] = {"value": None, "status": "unavailable",
                                 "note": "needs three view readings at least 20 minutes apart"}
    if views and likes is not None:
        rate = (likes + 2 * (comments or 0)) / views
        comps["engagement"] = {"value": _clamp(rate / 0.08), "status": "observed" if comments is not None else
                               "estimated", "note": f"{rate:.1%} likes+comments per view"}
    else:  # a rate needs both numbers, and 0 views (a measured zero) gives no rate yet
        why = (_metric_why(metrics, "likes", "likes not reported") if likes is None else
               "0 views so far" if views == 0 else _metric_why(metrics, "views", "views not reported"))
        comps["engagement"] = {"value": None, "status": "unavailable", "note": why}
    if signal.get("published_at"):
        age_h = max(0.0, (now - signal["published_at"]) / 3600)
        comps["recency"] = {"value": math.exp(-age_h / 36), "status": "observed", "note": f"{age_h:.0f} h old"}
    else:
        comps["recency"] = {"value": None, "status": "unavailable", "note": "upload time not reported"}
    if signal.get("kind") == "live":  # only a live stream has viewers right now; for a recording it does not apply
        live = val(metrics, "live_viewers")
        comps["live"] = ({"value": _clamp(math.log10(1 + live) / 5), "status": "observed",
                          "note": f"{live:,.0f} watching now"} if live is not None else
                         {"value": None, "status": "unavailable",
                          "note": _metric_why(metrics, "live_viewers", "viewer count not reported")})
    comps["size"] = ({"value": _clamp(math.log10(1 + views) / 7), "status": "observed", "note": f"{views:,.0f} views"}
                     if views is not None else {"value": None, "status": "unavailable",
                                                "note": _metric_why(metrics, "views", "views not reported")})
    if signal.get("keywords") or recurring:
        comps["recurrence"] = {"value": _clamp(recurring / 4), "status": "observed",
                               "note": f"topic seen from {recurring} other creator(s)" if recurring else "only source"}
    else:  # without topic words nothing can be compared: unknown, not "only source"
        comps["recurrence"] = {"value": None, "status": "unavailable", "note": "no topic words in the title"}
    weights = {k: WEIGHTS[k] for k in comps}
    value, coverage = combine(comps, weights)
    times = [h["at"] for h in history if h.get("views") is not None]
    readings = max(spaced_readings(times), 1 if views is not None else 0)
    if signal["platform"] == "youtube":
        notes.append(DERIVED_DISCLOSURE)
    return _result(value, MOMENTUM, comps, notes, coverage, readings, weights)
