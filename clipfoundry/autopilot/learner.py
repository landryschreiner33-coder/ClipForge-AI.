"""Learning Worker: learns from the real results of your own posts, and only from those.

1. Refreshes the statistics of recent posts through the official APIs (more often while they are new, within the
   quota budgets). Numbers a platform does not report stay empty; nothing is estimated.
2. Turns each post into one learning row: when it went out (local hour and weekday), platform, topic, source type,
   the source's trend score, the clip's scores and length, how the clip opens (hook type) and the packaging style of
   its title/caption, next to its real views and, when reported, retention.
3. Compares posts only within a platform and one audience (your selected viewers, in the current version of that
   group): z-scores of log views with outliers capped, plus average percentage viewed when available. It needs at
   least 30 posts (`brain_min_clips`) with `brain_min_views` views each, from at least 5 different videos, before it
   concludes anything, small groups are pulled toward your average
   (shrinkage), so one lucky post does not become a rule, and each update moves a learned value by at most 10%
   (`brain_max_step`) from the previous one.
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

MIN_SAMPLES = 30  # the floor of the brain_min_clips setting (section 14 of the build brief)
NEW_RESULTS = 10  # new posts needed before the learned values move again
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
    """The reading closest to 48 hours after your viewers could watch (at least 48 hours in), so posts are compared
    fairly."""
    start = shown_at(pub)
    hist = [h for h in db.performance_history(pub["id"]) if h.get("views") is not None
            and h["fetched_at"] - start >= REFERENCE_AGE_H * 3600]
    if not hist:
        return None
    return min(hist, key=lambda h: abs((h["fetched_at"] - start) / 3600 - REFERENCE_AGE_H))


def _hook_type(text: str) -> str:
    from ..pipeline.diversity import _opener_type

    first = (text or "").split(". ")[0]
    return _opener_type(first) if tokens(first) else "unknown"


def _duration_bucket(d: float | None) -> str:
    if not d:
        return "unknown"
    return "<20 s" if d < 20 else "20-35 s" if d < 35 else "35-50 s" if d < 50 else "50+ s"


# what an upload's delivery record says once your viewers can watch it (publish/audience.delivery_after_upload): you
# shared the Private YouTube video, you posted and linked the TikTok package, or TikTok posted it to the group
DELIVERED = ("user_confirmed", "manual_confirmed", "account_group", "api_verified")


def cohort(pub: dict) -> str:
    """Which audience a post reached: "selected" (your test viewers), "owner_only" (nobody else, nothing to learn),
    "public_legacy" (posted publicly before the selected-audience version) or "unconfirmed" (meant for your viewers,
    but they cannot watch it yet: Private with nobody invited, or a package you have not posted and linked; any
    intent this version does not know). Results of different audiences are never mixed: a small test group does not
    react like the public, and your own views are not your viewers'."""
    from ..publish import audience

    stamp = pub.get("audience") or {}
    want = stamp.get("intent") or ""
    if not want:
        want = db._legacy_intent(pub["platform"], pub.get("requested_privacy") or "")  # noqa: SLF001
    group = {audience.SELECTED: "selected", audience.PUBLIC: "public", audience.OWNER_ONLY: "owner_only",
             audience.LEGACY_PUBLIC: "public_legacy"}.get(want, "unconfirmed")
    delivery = pub.get("delivery") or {}
    seen = delivery.get("visibility") or {}
    expected = stamp.get("visibility") or pub.get("requested_privacy") or seen.get("requested")
    if want in (audience.SELECTED, audience.OWNER_ONLY) and int(stamp.get("policy_version") or 0) >= 1 \
            and seen.get("evidence") == "api" and seen.get("returned") and expected \
            and seen["returned"] != expected:
        # A wider or different audience cannot become selected-viewer evidence merely because it was requested.
        # Previously collected observations retain their original provenance and cohort snapshot.
        return "unconfirmed"
    setup = delivery.get("audience_setup") or ""  # empty: posted before deliveries were recorded
    if setup == "owner_only":
        return "owner_only"
    if group == "public":
        # An upload acceptance is not proof of public visibility. TikTok may not report its final audience.
        return "public" if setup == "public_api_verified" else "public_requested" if setup == "public_requested" \
            else "unconfirmed"
    if group == "selected" and setup and setup not in DELIVERED:
        return "unconfirmed"
    return group


def destination_cohort(platform: str, settings: dict) -> str:
    from ..publish import audience

    return {audience.PUBLIC: "public", audience.SELECTED: "selected", audience.OWNER_ONLY: "owner_only",
            audience.LOCAL_ONLY: "local_only"}[audience.destination(platform, settings)["intent"]]


def learning_context(settings: dict) -> dict:
    from ..publish import audience

    return {p: {"cohort": destination_cohort(p, settings),
                "group_version": int(audience.destination(p, settings)["group_version"])}
            for p in ("youtube", "tiktok")}


def context_matches(settings: dict | None = None) -> bool:
    settings = db.get_settings() if settings is None else settings
    stored = state.get("learning:context")
    if stored is None:
        # Metrics written before this version belonged only to selected viewers.
        return all(destination_cohort(p, settings) == "selected" for p in ("youtube", "tiktok"))
    return stored == learning_context(settings)


def _context_matches() -> bool:
    return context_matches()


def shown_at(pub: dict) -> float:
    """When your viewers could first watch a post: the upload, or later, when you said you shared it or linked the
    post you made yourself. Results count as mature 48 hours after this, not after the upload."""
    return max(float(pub["created_at"]), float((pub.get("delivery") or {}).get("confirmed_at") or 0))


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
            "publication_id": pub["id"], "clip_id": pub["clip_id"], "platform": pub["platform"], "cohort": cohort(pub),
            "group_version": int((pub.get("audience") or {}).get("group_version") or 1),
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
            "source_key": project.get("source_id") or clip.get("project_id") or pub["clip_id"],
            "age_h": round((snap["fetched_at"] - shown_at(pub)) / 3600, 1)})
    return out


# ------------------------------------------------------------------ 3. compare within a platform
def _robust_z(x: np.ndarray) -> np.ndarray:
    """z-scores after capping the values at the 10th and 90th percentiles (winsorizing): one viral outlier neither
    dominates nor flattens every other difference."""
    lo, hi = np.percentile(x, [10, 90])
    w = np.clip(x, lo, hi)
    return np.clip((w - w.mean()) / (w.std() or 1.0), -3.0, 3.0)


def add_performance(rs: list[dict], minimum: int = MIN_SAMPLES) -> None:
    by = defaultdict(list)
    for r in rs:
        by[r["platform"]].append(r)
    for group in by.values():
        zv = _robust_z(np.array([math.log1p(r["views"]) for r in group]))
        pct = [r["avg_view_percentage"] for r in group]
        have = [p for p in pct if p is not None]
        zp = None
        if len(have) >= minimum:
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


def bounded(new: float, previous: float, step: float) -> float:
    """One accepted update moves a learned value by at most `step` (10%) of its previous value."""
    return max(previous * (1 - step), min(previous * (1 + step), new))


def learned_weights(rs: list[dict], previous: dict[str, float] | None = None, step: float = 0.10,
                    minimum: int = MIN_SAMPLES) -> dict:
    """How well each score ordered your real results (Spearman). The evidence may point up to ±50% away from the
    starting weight, but each update moves the weight by at most `step` from where it was."""
    from .scheduler import FINAL_WEIGHTS

    previous = previous or {}
    out = {}
    for k in SCORE_KEYS:
        pairs = [(r["scores"][k], r["perf"]) for r in rs if r["scores"].get(k) is not None]
        if len(pairs) < minimum:
            continue
        rho = learning.spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if rho is None:
            continue
        aim = FINAL_WEIGHTS[k] * (1 + max(-0.5, min(0.5, rho)))
        out[k] = {"weight": round(bounded(aim, previous.get(k, FINAL_WEIGHTS[k]), step), 4), "rho": round(rho, 3),
                  "n": len(pairs), "aim": round(aim, 4)}
    return out


def retention_calibration(rs: list[dict], minimum: int = MIN_SAMPLES) -> dict | None:
    """Observed average percentage viewed vs the Expected Retention estimate (a straight-line fit)."""
    pairs = [(r["scores"]["retention"], r["avg_view_percentage"]) for r in rs
             if r["scores"].get("retention") is not None and r.get("avg_view_percentage") is not None]
    if len(pairs) < minimum:
        return None
    x, y = np.array([p[0] for p in pairs], float), np.array([p[1] for p in pairs], float)
    if x.std() == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    return {"slope": round(float(slope), 4), "intercept": round(float(intercept), 3), "n": len(pairs)}


# ------------------------------------------------------------------ 4. what the other workers read
def lift(dimension: str, key: str, platform: str = "all") -> tuple[float, int]:
    """(multiplier, posts) for a learned group; (1.0, 0) when there is no reliable result."""
    if db.get_settings().get("brain_paused") or not _context_matches():
        return 1.0, 0
    row = db.fetch("learning_metrics", f"{dimension}:{key}:{platform}:performance")
    if not row or not (row.get("data") or {}).get("reliable"):
        return 1.0, 0
    return float(row["lift"]), int(row["n"])


def weights() -> dict[str, float]:
    if db.get_settings().get("brain_paused") or not _context_matches():
        return {}
    return {r["key"]: float(r["lift"]) for r in db.select("learning_metrics", "dimension = 'weight'")}


def expected_retention(estimate: float | None) -> tuple[float | None, str]:
    if db.get_settings().get("brain_paused") or not _context_matches():
        return estimate, ""
    row = db.fetch("learning_metrics", "calibration:retention:all:retention")
    if estimate is None or not row:
        return estimate, ""
    d = row.get("data") or {}
    value = max(0.0, min(100.0, d["slope"] * estimate + d["intercept"]))
    return round(value, 1), f"calibrated on {row['n']} of your posts (average % viewed)"


def findings(metrics: list[dict], limit: int = 8) -> list[str]:
    """Plain statements backed by your own data (only reliable groups, strongest first)."""
    out = []
    seen = lambda m: float((m.get("data") or {}).get("aim") or m["lift"])  # noqa: E731 - what the data showed
    for m in sorted((m for m in metrics if (m.get("data") or {}).get("reliable") and m["platform"] != "all"),
                    key=lambda m: -abs(seen(m) - 1)):
        if abs(seen(m) - 1) < 0.15:
            continue
        key = f"{int(m['key']):02d}:00" if m["dimension"] == "hour" else WEEKDAYS[int(m["key"])] \
            if m["dimension"] == "weekday" else m["key"]
        word = "better" if seen(m) > 1 else "worse"
        out.append(f"{m['platform'].title()} · {DIMENSION_LABELS[m['dimension']]} {key}: {seen(m):.2f}x "
                   f"({word} than your average) across {m['n']} posts; used as {m['lift']:.2f}x for now")
        if len(out) >= limit:
            break
    return out


def minimum(settings: dict) -> int:
    return max(MIN_SAMPLES, int(settings.get("brain_min_clips") or MIN_SAMPLES))


@handler("learn")
def learn(job: Job) -> dict:
    from ..publish import audience
    from . import brain

    settings = db.get_settings()
    need, step = minimum(settings), min(0.10, float(settings.get("brain_max_step") or 0.10))
    job.progress(0.05, "Collecting results", stage="refresh")
    refreshed = refresh_due(settings, job)
    for pub in db.list_publications():
        if pub["status"] in ("done", "action_needed"):
            brain.ingest_platform(pub)  # the Brain's copy, with its provenance; repeats add nothing
    if settings.get("brain_paused"):
        evaluated = brain.evaluate(settings)
        message = "Learning is paused: results are collected, and learned values stay unchanged."
        state.put("learning:status", {**(state.get("learning:status") or {}), "at": time.time(),
                                      "refreshed": refreshed["refreshed"], "message": message})
        return {**refreshed, "message": message, "brain": evaluated["message"]}
    job.progress(0.5, "Comparing results", stage="evaluate")
    all_rows = rows(settings)
    usable_rows = [r for r in all_rows if usable(r["platform"], settings)]
    excluded = len(all_rows) - len(usable_rows)
    groups = {p: int(audience.destination(p, settings)["group_version"]) for p in ("youtube", "tiktok")}
    context = learning_context(settings)
    # Only confirmed audiences matching each platform's current destination, never legacy or requested visibility.
    allowed = [r for r in usable_rows if r["cohort"] in ("selected", "public") and
               r["cohort"] == context[r["platform"]]["cohort"] and
               r["group_version"] == groups[r["platform"]]]
    other_audience = len(usable_rows) - len(allowed)
    # the Brain's guards apply here too: a post counts once it has brain_min_views views (a handful of plays from a
    # few followers is not a result), and the posts must come from at least brain.MIN_SOURCES different videos
    min_views = int(settings.get("brain_min_views") or 10)
    few_views = sum(r["views"] < min_views for r in allowed)
    allowed = [r for r in allowed if r["views"] >= min_views]
    sources = len({r["source_key"] for r in allowed})
    note = ("YouTube results are shown but not used for learning: YouTube's Developer Policies require Google's "
            "approval for metrics derived from YouTube API data." if excluded else "")
    if other_audience:
        note = (note + " " if note else "") + (
            f"{other_audience} post{'s' if other_audience != 1 else ''} reached another audience (public before this "
            "version, only you, not yet shared with your viewers, or an earlier version of your viewer group) and are "
            "kept apart from your current audience's results.")
    if few_views:
        note = (note + " " if note else "") + (f"{few_views} post{'s' if few_views != 1 else ''} with fewer than "
                                               f"{min_views} views do not count yet.")
    previous = {r["id"]: float(r["lift"]) for r in db.select("learning_metrics") if r.get("lift") is not None} \
        if _context_matches() else {}
    status = {"at": time.time(), "samples": len(allowed), "needed": need, "excluded_youtube": excluded,
              "excluded_other_audience": other_audience, "note": note, "refreshed": refreshed["refreshed"],
              "findings": [], "weights": {}, "calibration": None}
    status.update(excluded_few_views=few_views, sources=sources)
    evaluated = brain.evaluate(settings)
    if len({r["cohort"] for r in allowed}) > 1:
        status["message"] = ("Public and selected-viewer results are kept separate. Shared score and timing "
                             "learning waits for one comparable audience; clip-length strategies stay per platform.")
        state.put("learning:status", status)
        return {**refreshed, "message": status["message"], "brain": evaluated["message"]}
    if len(allowed) < need or sources < brain.MIN_SOURCES:
        # too few results now: the learned values stay as they were (they never jump back and forth)
        found = f"{len(allowed)} of {need} posts with real numbers from {sources} of {brain.MIN_SOURCES} videos"
        status["message"] = (f"Not enough results yet: {found}. Until then posting times are spread evenly and the "
                             "scores are not adjusted." if not previous else
                             f"Not enough new results: {found}; the values learned earlier stay.")
        state.put("learning:status", status)
        return {**refreshed, "message": status["message"], "brain": evaluated["message"]}
    basis = set(state.get("learning:basis") or []) if _context_matches() else set()
    fresh = sum(r["publication_id"] not in basis for r in allowed)
    if previous and fresh < NEW_RESULTS:  # the same results never move the learned values twice
        status["message"] = (f"Waiting for new results: {fresh} of {NEW_RESULTS} new posts since the last update; "
                             "the values learned earlier stay.")
        state.put("learning:status", status)
        return {**refreshed, "samples": len(allowed), "message": status["message"], "brain": evaluated["message"]}
    state.put("learning:basis", [r["publication_id"] for r in allowed])
    state.put("learning:context", context)
    db.execute("DELETE FROM learning_metrics")
    add_performance(allowed, need)
    metrics = aggregate(allowed)
    for m in metrics:
        m["data"]["aim"] = m["lift"]
        m["lift"] = round(bounded(m["lift"], previous.get(m["id"], 1.0), step), 4)
        db.insert("learning_metrics", m, replace=True)
    w = learned_weights(allowed, {k.split(":")[1]: v for k, v in previous.items() if k.startswith("weight:")}, step,
                        need)
    for k, v in w.items():
        db.insert("learning_metrics", {"id": f"weight:{k}:all:weight", "dimension": "weight", "key": k,
                                       "platform": "all", "metric": "weight", "n": v["n"], "lift": v["weight"],
                                       "data": {"rho": v["rho"]}}, replace=True)
    cal = retention_calibration(allowed, need)
    if cal:
        db.insert("learning_metrics", {"id": "calibration:retention:all:retention", "dimension": "calibration",
                                       "key": "retention", "platform": "all", "metric": "retention", "n": cal["n"],
                                       "data": cal}, replace=True)
    status.update(findings=findings(metrics), weights=w, calibration=cal,
                  message=f"Learned from {len(allowed)} of your posts.")
    state.put("learning:status", status)
    state.event("learned", status["message"] + (" " + "; ".join(status["findings"][:3]) if status["findings"] else ""))
    return {**refreshed, "samples": len(allowed), "message": status["message"], "brain": evaluated["message"]}
