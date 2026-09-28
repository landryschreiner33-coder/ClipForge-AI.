"""Learning Worker: learns from the real results of your own posts, and only from those.

1. Refreshes the statistics of recent posts through the official APIs (more often while they are new, within the
   quota budgets). Numbers a platform does not report stay empty; nothing is estimated.
2. Turns each post into one learning row: when it went out (local hour and weekday), platform, topic, source type,
   the source's trend score, the clip's scores and length, how the clip opens (hook type) and the packaging style of
   its title/caption, next to its real views and, when reported, retention.
3. Compares posts only within a platform (z-scores of log views with outliers capped, plus average percentage
   viewed when available),
   and needs at least 10 posts before it concludes anything. Small groups are pulled toward your average (shrinkage),
   so one lucky post does not become a rule.
4. Feeds the results back: posting times (scheduler), topics (source ranking), packaging styles, the weights of the
   Final Opportunity Score, and a calibrated Expected Retention.

YouTube's Developer Policies do not allow derived metrics from YouTube API data without Google's approval, so YouTube
results are only used here when you confirm your project has that approval. They are still shown as reported.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from collections import defaultdict

import numpy as np

from .. import db, learning
from ..pipeline.text_utils import tokens
from ..publish import stats
from ..publish.common import PublishError
from . import state
from .host import Job, handler
from .scout import tz

MIN_SAMPLES = 10
MIN_GROUP = 3
SHRINK = 5.0
REFERENCE_AGE_H = 48.0
DIMENSIONS = ("hour", "weekday", "topic", "source_type", "style", "hook_type", "duration")
DIMENSION_LABELS = {"hour": "Posting hour", "weekday": "Weekday", "topic": "Topic", "source_type": "Source type",
                    "style": "Packaging style", "hook_type": "Hook type", "duration": "Clip length"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCORE_KEYS = ("clip", "packaging", "trend", "source", "diversity", "retention")


def usable(platform: str, settings: dict) -> bool:
    return platform != "youtube" or bool(settings.get("youtube_derived_metrics_approved"))


# ------------------------------------------------------------------ 1. refresh
def refresh_due(settings: dict, job: Job | None = None, now: float | None = None) -> dict:
    """Refresh statistics of posts from the last 30 days: every 6 h in their first 2 days, then daily."""
    now = now or time.time()
    done, failed, skipped = 0, [], 0
    youtube_stopped = False
    for pub in db.list_publications():
        if pub["status"] not in ("done", "action_needed") or now - pub["created_at"] > 30 * 86400:
            continue
        if pub["platform"] == "youtube" and youtube_stopped:
            skipped += 1
            continue
        hist = db.performance_history(pub["id"])
        age_h = (now - pub["created_at"]) / 3600
        every = 6 * 3600 if age_h < 48 else 24 * 3600
        if hist and now - hist[0]["fetched_at"] < every:
            continue
        if job:
            job.check()
        try:
            stats.refresh(pub)
            done += 1
        except PublishError as exc:
            failed.append({"publication_id": pub["id"], "error": str(exc)})
            if pub["platform"] == "youtube" and exc.code in ("quota_budget", "quotaExceeded", "reconnect"):
                youtube_stopped = True
    return {"refreshed": done, "failed": failed, "deferred": skipped}


# ------------------------------------------------------------------ 2. rows
def _snapshot(pub: dict) -> dict | None:
    """The reading closest to 48 hours after posting (at least 20 hours in), so posts are compared fairly."""
    hist = [h for h in db.performance_history(pub["id"]) if h.get("views") is not None
            and h["fetched_at"] - pub["created_at"] >= 20 * 3600]
    if not hist:
        return None
    return min(hist, key=lambda h: abs((h["fetched_at"] - pub["created_at"]) / 3600 - REFERENCE_AGE_H))


def _hook_type(text: str) -> str:
    from ..pipeline.diversity import _opener_type

    first = (text or "").split(". ")[0]
    return _opener_type(first) if tokens(first) else "unknown"


def _duration_bucket(d: float | None) -> str:
    if not d:
        return "unknown"
    return "<20 s" if d < 20 else "20-35 s" if d < 35 else "35-50 s" if d < 50 else "50+ s"


def rows(settings: dict) -> list[dict]:
    out = []
    zone = tz(settings)
    for pub in db.list_publications():
        if pub["status"] not in ("done", "action_needed"):
            continue
        snap = _snapshot(pub)
        if not snap:
            continue
        item = db.fetch("scheduled_publications", pub.get("scheduled_id") or "") if pub.get("scheduled_id") else None
        clip = db.get_clip(pub["clip_id"]) or {}
        project = db.get_project(clip.get("project_id") or "") or {}
        source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
        meta = db.fetch("metadata_candidates", (item or {}).get("metadata_id") or "") if item and \
            item.get("metadata_id") else None
        scores = db.fetch("clip_scores", pub["clip_id"], "clip_id") or {}
        posted = float((pub.get("options") or {}).get("publish_at") or (item or {}).get("planned_at")
                       or pub["created_at"])
        local = dt.datetime.fromtimestamp(posted, zone)
        feats = pub.get("features") or {}
        out.append({
            "publication_id": pub["id"], "clip_id": pub["clip_id"], "platform": pub["platform"],
            "hour": str(local.hour), "weekday": str(local.weekday()),
            "topic": ((source or {}).get("topic") or (source or {}).get("category") or clip.get("category") or
                      "unknown").lower(),
            "source_type": (source or {}).get("platform") or project.get("origin") or "manual",
            "style": (meta or {}).get("style") or "manual", "hook_type": _hook_type(clip.get("caption_text") or ""),
            "duration": _duration_bucket(feats.get("duration") or clip.get("duration")),
            "scores": {"clip": scores.get("clip", feats.get("viral_potential")), "packaging": scores.get("packaging"),
                       "trend": scores.get("trend"), "source": scores.get("source"),
                       "diversity": scores.get("diversity"), "retention": scores.get("retention")},
            "views": snap["views"], "avg_view_percentage": snap.get("avg_view_percentage"),
            "age_h": round((snap["fetched_at"] - pub["created_at"]) / 3600, 1)})
    return out


# ------------------------------------------------------------------ 3. compare within a platform
def _robust_z(x: np.ndarray) -> np.ndarray:
    """z-scores after capping the values at the 10th and 90th percentiles (winsorizing): one viral outlier neither
    dominates nor flattens every other difference."""
    lo, hi = np.percentile(x, [10, 90])
    w = np.clip(x, lo, hi)
    return np.clip((w - w.mean()) / (w.std() or 1.0), -3.0, 3.0)


def add_performance(rs: list[dict]) -> None:
    by = defaultdict(list)
    for r in rs:
        by[r["platform"]].append(r)
    for group in by.values():
        zv = _robust_z(np.array([math.log1p(r["views"]) for r in group]))
        pct = [r["avg_view_percentage"] for r in group]
        have = [p for p in pct if p is not None]
        zp = None
        if len(have) >= MIN_SAMPLES:
            zh = iter(_robust_z(np.array(have, dtype=float)).tolist())
            zp = [next(zh) if p is not None else None for p in pct]
        for k, r in enumerate(group):
            r["perf"] = float(zv[k]) if not zp or zp[k] is None else float(0.7 * zv[k] + 0.3 * zp[k])


def aggregate(rs: list[dict]) -> list[dict]:
    out = []
    for platform in sorted({r["platform"] for r in rs}) + ["all"]:
        group = rs if platform == "all" else [r for r in rs if r["platform"] == platform]
        for dim in DIMENSIONS:
            keys = defaultdict(list)
            for r in group:
                keys[r[dim]].append(r["perf"])
            for key, vals in keys.items():
                n = len(vals)
                mean = float(np.mean(vals))
                shrunk = mean * n / (n + SHRINK)
                out.append({"id": f"{dim}:{key}:{platform}:performance", "dimension": dim, "key": key,
                            "platform": platform, "metric": "performance", "n": n, "mean": round(mean, 4),
                            "shrunk": round(shrunk, 4), "lift": round(math.exp(0.5 * shrunk), 4),
                            "data": {"reliable": n >= MIN_GROUP}})
    return out


def learned_weights(rs: list[dict]) -> dict:
    """How well each score ordered your real results (Spearman); weights move by at most ±50%."""
    from .scheduler import FINAL_WEIGHTS

    out = {}
    for k in SCORE_KEYS:
        pairs = [(r["scores"][k], r["perf"]) for r in rs if r["scores"].get(k) is not None]
        if len(pairs) < MIN_SAMPLES:
            continue
        rho = learning.spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if rho is None:
            continue
        out[k] = {"weight": round(FINAL_WEIGHTS[k] * (1 + max(-0.5, min(0.5, rho))), 4), "rho": round(rho, 3),
                  "n": len(pairs)}
    return out


def retention_calibration(rs: list[dict]) -> dict | None:
    """Observed average percentage viewed vs the Expected Retention estimate (a straight-line fit)."""
    pairs = [(r["scores"]["retention"], r["avg_view_percentage"]) for r in rs
             if r["scores"].get("retention") is not None and r.get("avg_view_percentage") is not None]
    if len(pairs) < MIN_SAMPLES:
        return None
    x, y = np.array([p[0] for p in pairs], float), np.array([p[1] for p in pairs], float)
    if x.std() == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    return {"slope": round(float(slope), 4), "intercept": round(float(intercept), 3), "n": len(pairs)}


# ------------------------------------------------------------------ 4. what the other workers read
def lift(dimension: str, key: str, platform: str = "all") -> tuple[float, int]:
    """(multiplier, posts) for a learned group; (1.0, 0) when there is no reliable result."""
    row = db.fetch("learning_metrics", f"{dimension}:{key}:{platform}:performance")
    if not row or not (row.get("data") or {}).get("reliable"):
        return 1.0, 0
    return float(row["lift"]), int(row["n"])


def weights() -> dict[str, float]:
    return {r["key"]: float(r["lift"]) for r in db.select("learning_metrics", "dimension = 'weight'")}


def expected_retention(estimate: float | None) -> tuple[float | None, str]:
    row = db.fetch("learning_metrics", "calibration:retention:all:retention")
    if estimate is None or not row:
        return estimate, ""
    d = row.get("data") or {}
    value = max(0.0, min(100.0, d["slope"] * estimate + d["intercept"]))
    return round(value, 1), f"calibrated on {row['n']} of your posts (average % viewed)"


def findings(metrics: list[dict], limit: int = 8) -> list[str]:
    """Plain statements backed by your own data (only reliable groups, strongest first)."""
    out = []
    for m in sorted((m for m in metrics if (m.get("data") or {}).get("reliable") and m["platform"] != "all"),
                    key=lambda m: -abs(m["lift"] - 1)):
        if abs(m["lift"] - 1) < 0.15:
            continue
        key = f"{int(m['key']):02d}:00" if m["dimension"] == "hour" else WEEKDAYS[int(m["key"])] \
            if m["dimension"] == "weekday" else m["key"]
        word = "better" if m["lift"] > 1 else "worse"
        out.append(f"{m['platform'].title()} · {DIMENSION_LABELS[m['dimension']]} {key}: {m['lift']:.2f}x "
                   f"({word} than your average) across {m['n']} posts")
        if len(out) >= limit:
            break
    return out


@handler("learn")
def learn(job: Job) -> dict:
    settings = db.get_settings()
    refreshed = refresh_due(settings, job)
    all_rows = rows(settings)
    allowed = [r for r in all_rows if usable(r["platform"], settings)]
    excluded = len(all_rows) - len(allowed)
    note = ("YouTube results are shown but not used for learning: YouTube's Developer Policies require Google's "
            "approval for metrics derived from YouTube API data." if excluded else "")
    status = {"at": time.time(), "samples": len(allowed), "needed": MIN_SAMPLES, "excluded_youtube": excluded,
              "note": note, "refreshed": refreshed["refreshed"], "findings": [], "weights": {}, "calibration": None}
    db.execute("DELETE FROM learning_metrics")
    if len(allowed) < MIN_SAMPLES:
        status["message"] = (f"Not enough results yet: {len(allowed)} of {MIN_SAMPLES} posts with real numbers. "
                             "Until then posting times are spread evenly and the scores are not adjusted.")
        state.put("learning:status", status)
        return {**refreshed, "message": status["message"]}
    add_performance(allowed)
    metrics = aggregate(allowed)
    for m in metrics:
        db.insert("learning_metrics", m, replace=True)
    w = learned_weights(allowed)
    for k, v in w.items():
        db.insert("learning_metrics", {"id": f"weight:{k}:all:weight", "dimension": "weight", "key": k,
                                       "platform": "all", "metric": "weight", "n": v["n"], "lift": v["weight"],
                                       "data": {"rho": v["rho"]}}, replace=True)
    cal = retention_calibration(allowed)
    if cal:
        db.insert("learning_metrics", {"id": "calibration:retention:all:retention", "dimension": "calibration",
                                       "key": "retention", "platform": "all", "metric": "retention", "n": cal["n"],
                                       "data": cal}, replace=True)
    status.update(findings=findings(metrics), weights=w, calibration=cal,
                  message=f"Learned from {len(allowed)} of your posts.")
    state.put("learning:status", status)
    state.event("learned", status["message"] + (" " + "; ".join(status["findings"][:3]) if status["findings"] else ""))
    return {**refreshed, "samples": len(allowed), "message": status["message"]}
