"""The Brain: test-audience observations, cohorts and conservative, versioned strategy updates.

What it is: structured memory of what genuine viewers did with each clip, kept with its provenance, plus a small,
guarded strategy system. It is not an autonomous agent, it never edits code, secrets, privacy, spending caps or safety
limits, and it never claims that learning improved anything.

Evidence and provenance (never mixed up):

* ``platform_api``: numbers a platform's API reported (YouTube Analytics/Data API; TikTok rarely, see stats.py).
* ``owner_import``: numbers the owner copied from a platform's own screens/exports (manual form or CSV import).
* ``tester_feedback``: what invited testers said themselves (ratings, comment, where they stopped). Self-reported,
  never shown as measured watch time or retention.

Cohorts keep audiences apart: YouTube invited viewers and TikTok approved followers are separate test cohorts,
versioned with the group (``audience_<platform>_group_version``); owner-only staging is not a cohort at all; older
public results are ``public:<platform>`` and are never mixed with test cohorts, nor changed by them.

The one history-to-decision loop (section 14 of the owner's brief): the **clip-length preference** of a test cohort.
With enough mature, independent evidence it moves the Autopilot's target clip length by at most 10% per accepted
update; ranking (pipeline/candidates.py) then uses that version for new clips, and each project records which
strategy version it used. Without enough evidence nothing changes and the Brain says "Not enough evidence yet".
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
import time

from . import audience, db

PROVENANCE = ("platform_api", "owner_import", "tester_feedback")
PROVENANCE_LABELS = {"platform_api": "Platform API", "owner_import": "Your import (platform numbers)",
                     "tester_feedback": "Tester feedback / self-reported"}
# metrics the owner may enter/import, with their unit; anything else is rejected, not guessed
METRICS = {"views": "count", "watch_time_minutes": "minutes", "avg_view_duration_s": "seconds",
           "avg_view_percentage": "percent", "completion_rate": "percent", "rewatches": "count", "likes": "count",
           "comments": "count", "shares": "count", "impressions": "count", "ctr": "percent",
           "audience_size": "count"}
RATINGS = ("hook", "context", "payoff", "captions", "overall")  # tester ratings, 1-5
STATES = ("Cold start", "Collecting data", "Evaluating", "Strategy updated", "Paused", "Error")
ANALYTICS_STATES = ("Awaiting viewer access", "Awaiting observations", "API data available",
                    "Manual feedback available", "Insufficient evidence", "Analytics unavailable")

# Conservative guardrails (configurable through settings; documented in docs/BRAIN.md)
DEFAULTS = {"brain_min_clips": 30, "brain_min_sources": 10, "brain_min_viewers_per_clip": 3, "brain_min_testers": 5,
            "brain_maturity_hours": 48, "brain_max_step": 0.10, "brain_min_arm": 20, "brain_exploration_share": 0.10}
LENGTH_PARAM = "target_duration"
LENGTH_BOUNDS = (12.0, 90.0)


class ImportProblem(ValueError):
    pass


def _cfg(settings: dict, key: str) -> float:
    v = settings.get(key)
    return float(DEFAULTS[key] if v in (None, "") else v)


# ------------------------------------------------------------------ cohorts
def cohort_for(platform: str, settings: dict, intent: str | None = None) -> tuple[str, str]:
    """(cohort id, audience type) for observations of a clip shown on `platform` now."""
    it = intent or audience.intent(platform, settings)
    if it == audience.SELECTED_AUDIENCE:
        group = "invited" if platform == "youtube" else audience.tiktok_group(settings).lower()
        version = int(settings.get(f"audience_{platform}_group_version") or 1)
        return f"selected:{platform}:{group}:v{version}", "selected"
    if it == audience.OWNER_ONLY:
        return f"owner:{platform}", "owner"
    if it in ("public", "PUBLIC"):
        return f"public:{platform}", "public"
    return f"local:{platform}", "local"


def cohort_of_publication(pub: dict, settings: dict) -> tuple[str, str]:
    a = (pub.get("info") or {}).get("audience") or {}
    if not a:  # uploaded before the audience policy: whatever it was, it is not a test cohort
        wide = (pub.get("privacy") or pub.get("requested_privacy") or "") in audience.WIDE
        return (f"public:{pub['platform']}", "public") if wide else (f"legacy:{pub['platform']}", "legacy")
    return cohort_for(pub["platform"], settings, a.get("intent"))


# ------------------------------------------------------------------ storing observations
def _key(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _render_sha(clip: dict) -> str:
    return (((clip.get("render_info") or {}).get("artifact") or {}).get("sha256") or "")


def record(clip_id: str, platform: str, provenance: str, metric: str, value: float | None, *, settings: dict,
           cohort: str = "", audience_type: str = "", observed_at: float | None = None,
           window_start: float | None = None, window_end: float | None = None, sample_size: int | None = None,
           publication_id: str = "", platform_video_id: str = "", tester_id: str = "", import_id: str = "",
           note: str = "") -> dict:
    """Store one observation idempotently. The same cumulative reading again is a no-op; a different value for the
    same reading is a correction (a new version that supersedes the old one, never added to it)."""
    if provenance not in PROVENANCE:
        raise ImportProblem(f"Unknown evidence source {provenance!r}")
    if provenance != "tester_feedback" and metric not in METRICS:
        raise ImportProblem(f"Unknown metric {metric!r}")
    if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
        raise ImportProblem(f"{metric}: the value must be a number ≥ 0 (or empty when it was not reported)")
    if metric in ("avg_view_percentage", "completion_rate", "ctr") and value is not None and value > 100:
        raise ImportProblem(f"{metric}: a percentage cannot exceed 100")
    clip = db.get_clip(clip_id)
    if not clip:
        raise ImportProblem(f"No clip {clip_id!r} in this library")
    if not cohort:
        cohort, audience_type = cohort_for(platform, settings)
    observed_at = float(observed_at or time.time())
    reading = _key(clip_id, platform, provenance, metric, cohort, tester_id, window_start, window_end,
                   None if provenance == "tester_feedback" else round(observed_at))
    current = db.select("observations", "reading_key = ? AND superseded_by = ''", (reading,))
    if current:
        old = current[0]
        if old["value"] == value and old["sample_size"] == sample_size:
            return {**old, "duplicate": True}
    row = db.insert("observations", {
        "clip_id": clip_id, "render_sha256": _render_sha(clip), "publication_id": publication_id,
        "platform": platform, "platform_video_id": platform_video_id, "cohort": cohort,
        "audience_type": audience_type, "provenance": provenance, "metric": metric,
        "unit": METRICS.get(metric, "rating" if metric.startswith("rating_") else ""), "value": value,
        "window_start": window_start, "window_end": window_end, "observed_at": observed_at,
        "sample_size": sample_size, "tester_id": tester_id[:64], "import_id": import_id, "note": note[:500],
        "reading_key": reading, "version": (current[0]["version"] + 1) if current else 1, "superseded_by": ""})
    if current:
        db.update("observations", current[0]["id"], superseded_by=row["id"])
    return row


def record_platform_snapshot(pub: dict, snapshot: dict, settings: dict) -> int:
    """A stats.py snapshot of a selected-audience/staging upload, filed as platform_api evidence (null stays null)."""
    cohort, kind = cohort_of_publication(pub, settings)
    n = 0
    for metric in METRICS:
        if metric not in snapshot:
            continue
        value = snapshot.get(metric)
        record(pub["clip_id"], pub["platform"], "platform_api", metric, None if value is None else float(value),
               settings=settings, cohort=cohort, audience_type=kind, observed_at=snapshot.get("fetched_at"),
               window_start=pub.get("created_at"), window_end=snapshot.get("fetched_at"),
               sample_size=snapshot.get("views"), publication_id=pub["id"],
               platform_video_id=pub.get("remote_id") or "")
        n += 1
    return n


def record_tester(clip_id: str, platform: str, ratings: dict, settings: dict, tester_id: str = "",
                  comment: str = "", stopped_at_s: float | None = None, import_id: str = "") -> list[dict]:
    """Voluntary ratings (1-5) from one tester, labeled self-reported. A repeat by the same tester replaces theirs."""
    out = []
    clean = {k: ratings.get(k) for k in RATINGS if ratings.get(k) not in (None, "")}
    if not clean and stopped_at_s is None and not comment.strip():
        raise ImportProblem("Enter at least one rating, a comment or where they stopped watching")
    for k, v in clean.items():
        v = float(v)
        if not 1 <= v <= 5:
            raise ImportProblem(f"{k}: ratings are 1 to 5")
        out.append(record(clip_id, platform, "tester_feedback", f"rating_{k}", v, settings=settings,
                          tester_id=tester_id, import_id=import_id, note=comment))
    if stopped_at_s is not None:
        if stopped_at_s < 0:
            raise ImportProblem("Where they stopped must be ≥ 0 seconds")
        out.append(record(clip_id, platform, "tester_feedback", "self_reported_stop_s", float(stopped_at_s),
                          settings=settings, tester_id=tester_id, import_id=import_id, note=comment))
    if not out:
        out.append(record(clip_id, platform, "tester_feedback", "comment", None, settings=settings,
                          tester_id=tester_id, import_id=import_id, note=comment))
    return out


# ------------------------------------------------------------------ CSV import (preview, then commit)
def _when(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text) if text.replace(".", "", 1).isdigit() and len(text) >= 9 else \
            dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise ImportProblem(f"Date {text!r} is not a date (use 2026-10-07 or 2026-10-07T18:00)") from exc


def _number(text: str) -> float | None:
    text = (text or "").strip().replace(",", "")
    if text in ("", "-", "—", "n/a", "N/A"):
        return None  # not reported: stays unavailable, never zero
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError as exc:
        raise ImportProblem(f"{text!r} is not a number") from exc


def preview_csv(text: str, settings: dict) -> dict:
    """Parse an owner-provided export. Accepts long rows (clip_id, platform, metric, value, ...) or wide rows with
    one column per known metric. Only fields actually present are taken; every row is checked before anything is
    stored. Returns rows to commit plus the problems, nothing is written."""
    if len(text) > 2_000_000:
        raise ImportProblem("The file is too large (2 MB at most)")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ImportProblem("The file has no header row")
    fields = [f.strip().lower() for f in reader.fieldnames]
    wide = [f for f in fields if f in METRICS]
    if "metric" not in fields and not wide:
        raise ImportProblem("No known metric columns. Use a 'metric' and 'value' column, or columns named like "
                            + ", ".join(list(METRICS)[:5]) + ", …")
    rows, problems = [], []
    by_video = {p.get("remote_id"): p for p in db.list_publications() if p.get("remote_id")}
    for n, raw in enumerate(reader, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        try:
            clip_id = r.get("clip_id", "")
            pub = by_video.get(r.get("platform_video_id") or r.get("video_id") or "")
            if not clip_id and pub:
                clip_id = pub["clip_id"]
            if not clip_id or not db.get_clip(clip_id):
                raise ImportProblem("clip not found (give clip_id, or the platform video ID of an upload)")
            platform = (r.get("platform") or (pub or {}).get("platform") or "").lower()
            if platform not in audience.PLATFORMS:
                raise ImportProblem("platform must be youtube or tiktok")
            if pub and pub["clip_id"] != clip_id:
                raise ImportProblem("the video ID belongs to another clip")
            cohort, kind = (cohort_of_publication(pub, settings) if pub else cohort_for(platform, settings))
            if r.get("audience_group"):
                cohort = r["audience_group"][:80]
                kind = cohort.split(":", 1)[0]
            base = {"clip_id": clip_id, "platform": platform, "cohort": cohort, "audience_type": kind,
                    "observed_at": _when(r.get("observed_at", "")) or None,
                    "window_start": _when(r.get("window_start", "")), "window_end": _when(r.get("window_end", "")),
                    "sample_size": int(_number(r["sample_size"])) if _number(r.get("sample_size", "")) is not None
                    else None, "publication_id": (pub or {}).get("id", ""),
                    "platform_video_id": (pub or {}).get("remote_id", "")}
            if base["observed_at"] is None:
                raise ImportProblem("observed_at (when the numbers were read) is required")
            if base["window_start"] and base["window_end"] and base["window_end"] < base["window_start"]:
                raise ImportProblem("window_end is before window_start")
            pairs = [(r.get("metric", "").lower(), r.get("value", ""))] if "metric" in fields else \
                [(m, r.get(m, "")) for m in wide]
            for metric, value in pairs:
                if metric not in METRICS:
                    raise ImportProblem(f"unknown metric {metric!r}")
                unit = r.get("unit", "").lower()
                if unit and unit != METRICS[metric]:
                    raise ImportProblem(f"{metric} is measured in {METRICS[metric]}, not {unit}")
                v = _number(value)
                if v is not None and (v < 0 or (METRICS[metric] == "percent" and v > 100)):
                    raise ImportProblem(f"{metric}: {value} is out of range")
                rows.append({**base, "metric": metric, "value": v, "line": n})
        except ImportProblem as exc:
            problems.append({"line": n, "problem": str(exc)})
    return {"rows": rows, "problems": problems, "accepted": len(rows), "rejected": len(problems),
            "columns": fields}


def commit_csv(text: str, settings: dict, filename: str = "") -> dict:
    preview = preview_csv(text, settings)
    if preview["problems"]:
        raise ImportProblem(f"{preview['rejected']} row(s) have problems; fix them first (nothing was imported)")
    imp = db.insert("observation_imports", {"filename": filename[:200], "kind": "csv", "rows": preview["accepted"],
                                            "sha256": hashlib.sha256(text.encode()).hexdigest()})
    new = dup = 0
    for r in preview["rows"]:
        out = record(r["clip_id"], r["platform"], "owner_import", r["metric"], r["value"], settings=settings,
                     cohort=r["cohort"], audience_type=r["audience_type"], observed_at=r["observed_at"],
                     window_start=r["window_start"], window_end=r["window_end"], sample_size=r["sample_size"],
                     publication_id=r["publication_id"], platform_video_id=r["platform_video_id"],
                     import_id=imp["id"])
        dup += bool(out.get("duplicate"))
        new += not out.get("duplicate")
    db.update("observation_imports", imp["id"], accepted=new, duplicates=dup)
    return {"import_id": imp["id"], "stored": new, "duplicates": dup}


# ------------------------------------------------------------------ per-clip evidence
def current(where: str = "", args: tuple = ()) -> list[dict]:
    clause = "superseded_by = ''" + (f" AND {where}" if where else "")
    return db.select("observations", clause, args, "observed_at")


def clip_status(clip_id: str) -> dict:
    """The Test feedback state of one clip (separate from transfer and visibility)."""
    obs = current("clip_id = ?", (clip_id,))
    pubs = [p for p in db.list_publications(clip_id) if p["status"] in ("done", "action_needed")]
    api = [o for o in obs if o["provenance"] == "platform_api" and o["value"] is not None]
    manual = [o for o in obs if o["provenance"] != "platform_api"]
    access = any(audience.viewers_can_watch(p) for p in pubs)
    if api:
        state, nxt = "API data available", "Numbers arrive as the platform reports them."
    elif manual:
        state, nxt = "Manual feedback available", "Add more tester feedback or imported numbers."
    elif not pubs:
        state, nxt = "Awaiting viewer access", "Post or share the clip with your selected viewers first."
    elif not access:
        state, nxt = "Awaiting viewer access", "Invite your viewers (YouTube Studio) or finish the TikTok post."
    elif any(o["provenance"] == "platform_api" for o in obs):
        state, nxt = "Analytics unavailable", "The platform reported no numbers; enter tester feedback instead."
    else:
        state, nxt = "Awaiting observations", "Results come later; nothing blocks the next clip meanwhile."
    return {"state": state, "next": nxt, "observations": len(obs),
            "by_provenance": {p: sum(o["provenance"] == p for o in obs) for p in PROVENANCE}}


def _outcome(obs: list[dict]) -> tuple[str, float | None, int]:
    """(metric used, value, independent viewers) for one clip in one cohort: platform/imported retention first,
    else the testers' overall rating (self-reported, rescaled to 0-100). Cumulative snapshots: the latest counts."""
    for metric in ("avg_view_percentage", "completion_rate"):
        rows = [o for o in obs if o["metric"] == metric and o["value"] is not None
                and o["provenance"] in ("platform_api", "owner_import")]
        if rows:
            last = max(rows, key=lambda o: o["observed_at"])
            return metric, float(last["value"]), int(last.get("sample_size") or 0)
    ratings = {}
    for o in obs:
        if o["metric"] == "rating_overall" and o["value"] is not None:
            ratings[o["tester_id"] or o["id"]] = float(o["value"])  # one answer per tester
    if ratings:
        return "rating_overall", 25.0 * (statistics.fmean(ratings.values()) - 1.0), len(ratings)
    return "", None, 0


def eligible_clips(cohort: str, settings: dict, now: float | None = None) -> list[dict]:
    """Clips with mature, usable evidence in one comparable cohort (fixtures and other cohorts excluded)."""
    now = now or time.time()
    maturity = _cfg(settings, "brain_maturity_hours") * 3600
    min_viewers = _cfg(settings, "brain_min_viewers_per_clip")
    by_clip: dict[str, list[dict]] = {}
    for o in current("cohort = ?", (cohort,)):
        # YouTube's Developer Policies: metrics derived from its API need Google's approval before they may steer
        # anything (as in learner.usable); your own imports and tester answers are not API data
        if o["provenance"] == "platform_api" and o["platform"] == "youtube" and \
                not settings.get("youtube_derived_metrics_approved"):
            continue
        by_clip.setdefault(o["clip_id"], []).append(o)
    out = []
    for clip_id, obs in by_clip.items():
        clip = db.get_clip(clip_id)
        if not clip:
            continue
        metric, value, viewers = _outcome(obs)
        if value is None:
            continue
        first = min(o.get("window_start") or o["observed_at"] for o in obs)
        mature = metric == "rating_overall" or now - first >= maturity
        if not mature or viewers < min_viewers:
            continue
        project = db.get_project(clip["project_id"]) or {}
        out.append({"clip_id": clip_id, "duration": float(clip.get("duration") or (clip["end"] - clip["start"])),
                    "metric": metric, "value": value, "viewers": viewers,
                    "source": project.get("source_id") or project.get("id") or clip["project_id"],
                    "testers": sorted({o["tester_id"] for o in obs if o.get("tester_id")})})
    return out


# ------------------------------------------------------------------ strategy
def active_strategy(scope: str, parameter: str = LENGTH_PARAM) -> dict | None:
    rows = db.select("strategy_versions", "scope = ? AND parameter = ? AND status = 'active'", (scope, parameter),
                     "created_at DESC", 1)
    return rows[0] if rows else None


def primary_scope(settings: dict) -> str | None:
    """The test cohort whose strategy guides Autopilot's ranking: the first destination set to Selected audience
    (YouTube first). None when no destination is a test audience (then the baseline stays)."""
    for p in audience.PLATFORMS:
        if audience.intent(p, settings) == audience.SELECTED_AUDIENCE:
            return cohort_for(p, settings)[0]
    return None


def ranking_options(settings: dict) -> dict:
    """What new Autopilot clips are ranked with: the active test-cohort strategy, else the baseline setting."""
    base = float(settings.get("target_duration") or 30.0)
    scope = primary_scope(settings)
    s = active_strategy(scope) if scope else None
    if not s:
        return {"target_duration": base, "strategy_version": "baseline", "strategy_scope": scope or ""}
    return {"target_duration": float(s["new_value"]), "strategy_version": s["id"], "strategy_scope": scope}


def _bucket(d: float) -> str:
    return "short" if d < 25 else "medium" if d < 45 else "long"


def evaluate_length(cohort: str, settings: dict, now: float | None = None, apply: bool = True) -> dict:
    """Propose (and, when the guards pass, apply) a bounded clip-length change for one test cohort.

    Guards: at least `brain_min_clips` distinct mature clips from at least `brain_min_sources` sources, each with
    `brain_min_viewers_per_clip` viewers; with tester ratings, at least `brain_min_testers` distinct testers (the
    same few people rating many clips are not independent evidence). Sources are averaged first, so several clips of
    one video count as one source. The best bucket must beat the rest by more than two standard errors; otherwise
    the result is "inconclusive" and nothing changes. A change moves the target by at most `brain_max_step`
    (relative) toward the better bucket. Only `selected:` cohorts can change; public strategy is never touched."""
    now = now or time.time()
    if not cohort.startswith("selected:"):
        raise ValueError("Only selected-audience test cohorts have an automatic strategy")
    clips = eligible_clips(cohort, settings, now)
    need_clips, need_sources = int(_cfg(settings, "brain_min_clips")), int(_cfg(settings, "brain_min_sources"))
    sources = {c["source"] for c in clips}
    testers = {t for c in clips for t in c["testers"]}
    base = ranking_options({**settings}) if primary_scope(settings) == cohort else \
        {"target_duration": float(settings.get("target_duration") or 30.0)}
    act = active_strategy(cohort)
    old = float(act["new_value"]) if act else float(base["target_duration"])
    evidence = {"cohort": cohort, "eligible_clips": len(clips), "sources": len(sources), "testers": len(testers),
                "needed": {"clips": need_clips, "sources": need_sources},
                "metrics": sorted({c["metric"] for c in clips})}
    result = {"cohort": cohort, "parameter": LENGTH_PARAM, "old_value": old, "evidence": evidence}
    if len(clips) < need_clips or len(sources) < need_sources:
        return {**result, "decision": "insufficient", "message": "Not enough evidence yet"}
    if any(c["metric"] == "rating_overall" for c in clips) and len(testers) < _cfg(settings, "brain_min_testers"):
        return {**result, "decision": "insufficient",
                "message": "Not enough evidence yet: too few different testers to count clips as independent"}
    # one value per (source, bucket): clips from the same video are not independent evidence
    per: dict[tuple, list[float]] = {}
    for c in clips:
        per.setdefault((c["source"], _bucket(c["duration"])), []).append(c["value"])
    buckets: dict[str, list[float]] = {}
    durations: dict[str, list[float]] = {}
    for (src, b), vals in per.items():
        buckets.setdefault(b, []).append(statistics.fmean(vals))
    for c in clips:
        durations.setdefault(_bucket(c["duration"]), []).append(c["duration"])
    stats_ = {b: {"n": len(v), "mean": statistics.fmean(v),
                  "se": (statistics.stdev(v) / math.sqrt(len(v))) if len(v) > 1 else float("inf")}
              for b, v in buckets.items() if len(v) >= 3}
    evidence["buckets"] = {b: {k: (round(x, 2) if math.isfinite(x) else None) for k, x in s.items()}
                           for b, s in stats_.items()}
    if len(stats_) < 2:
        return {**result, "decision": "inconclusive", "message": "Clip lengths were too similar to compare"}
    best = max(stats_, key=lambda b: stats_[b]["mean"])
    rest = [v for b, vals in buckets.items() if b != best for v in vals]
    rest_mean = statistics.fmean(rest)
    rest_se = statistics.stdev(rest) / math.sqrt(len(rest)) if len(rest) > 1 else float("inf")
    gap = stats_[best]["mean"] - rest_mean
    se = math.sqrt(stats_[best]["se"] ** 2 + rest_se ** 2)
    evidence.update(best_bucket=best, difference=round(gap, 2), standard_error=round(se, 2) if math.isfinite(se)
                    else None, correlation_note="Observed correlation in this test group, not proof of cause.")
    if not math.isfinite(se) or gap <= 2 * se:
        return {**result, "decision": "inconclusive", "message": "No clear difference between clip lengths yet"}
    goal = statistics.fmean(durations[best])
    step = _cfg(settings, "brain_max_step") * old
    new = old + max(-step, min(step, goal - old))
    new = round(max(LENGTH_BOUNDS[0], min(LENGTH_BOUNDS[1], new)), 1)
    if abs(new - old) < 0.05:
        return {**result, "decision": "unchanged", "message": "Already at the preferred length"}
    proposal = {**result, "decision": "update", "new_value": new,
                "message": f"{best.title()} clips did better with this test group; target length {old:.0f} s → "
                           f"{new:.0f} s (at most {int(_cfg(settings, 'brain_max_step') * 100)}% per update)."}
    if apply:
        proposal["version"] = _apply(cohort, LENGTH_PARAM, old, new, proposal["message"], evidence, act)
    return proposal


def _apply(scope: str, parameter: str, old: float, new: float, reason: str, evidence: dict, prev: dict | None) -> dict:
    with db.connect() as conn:  # one active version per scope/parameter
        conn.execute("UPDATE strategy_versions SET status = 'superseded', updated_at = ? WHERE scope = ? AND "
                     "parameter = ? AND status = 'active'", (time.time(), scope, parameter))
    row = db.insert("strategy_versions", {"scope": scope, "parameter": parameter, "old_value": old, "new_value": new,
                                          "reason": reason, "evidence": evidence, "status": "active",
                                          "rollback_to": (prev or {}).get("id", ""), "kind": "automatic"})
    from .autopilot import state

    state.event("strategy_updated", f"Brain: {reason}", ref_type="strategy", ref_id=row["id"], scope=scope)
    return row


def rollback(version_id: str) -> dict:
    """Undo one strategy version: its predecessor (or the baseline) is active again. Recorded, never deleted."""
    row = db.fetch("strategy_versions", version_id)
    if not row or row["status"] != "active":
        raise ValueError("Only the active strategy version can be rolled back")
    db.update("strategy_versions", version_id, status="rolled_back")
    if row.get("rollback_to"):
        db.update("strategy_versions", row["rollback_to"], status="active")
    from .autopilot import state

    state.event("strategy_rolled_back", f"Brain: strategy for {row['scope']} rolled back to "
                                        f"{'the previous version' if row.get('rollback_to') else 'the baseline'}",
                ref_type="strategy", ref_id=version_id)
    return db.fetch("strategy_versions", version_id) or row


# ------------------------------------------------------------------ experiments (bounded exploration)
def assign_variant(experiment: dict, clip_id: str) -> str:
    """Stable assignment: the same clip always gets the same variant (or 'control' outside the exploration
    share)."""
    h = int(hashlib.sha256(f"{experiment['id']}:{clip_id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    share = float(experiment.get("share") or DEFAULTS["brain_exploration_share"])
    if h >= share:
        return "control"
    variants = experiment.get("variants") or ["a", "b"]
    return variants[int(h / share * len(variants)) % len(variants)]


def compare_arms(values_a: list[float], values_b: list[float], min_arm: int = DEFAULTS["brain_min_arm"]) -> dict:
    """An A/B comparison: needs `min_arm` clips per arm and a difference beyond two standard errors; else
    inconclusive (no winner is declared)."""
    if len(values_a) < min_arm or len(values_b) < min_arm:
        return {"winner": None, "result": "insufficient", "message": f"Needs {min_arm} clips per variant"}
    ma, mb = statistics.fmean(values_a), statistics.fmean(values_b)
    se = math.sqrt(statistics.variance(values_a) / len(values_a) + statistics.variance(values_b) / len(values_b))
    if se == 0 or abs(ma - mb) <= 2 * se:
        return {"winner": None, "result": "inconclusive", "difference": round(ma - mb, 2), "se": round(se, 2)}
    return {"winner": "a" if ma > mb else "b", "result": "difference", "difference": round(ma - mb, 2),
            "se": round(se, 2)}


# ------------------------------------------------------------------ the Brain's own state
def view(settings: dict) -> dict:
    obs = current()
    cohorts = sorted({o["cohort"] for o in obs if o["cohort"].startswith("selected:")})
    latest = db.select("strategy_versions", "", (), "created_at DESC", 10)
    last_eval = db.select("autopilot_events", "kind IN ('brain_evaluated', 'brain_error')", (), "id DESC", 1)
    if not settings.get("autopilot_learning", True):
        state = "Paused"
    elif last_eval and last_eval[0]["kind"] == "brain_error":
        state = "Error"
    elif any(s["status"] == "active" and time.time() - s["created_at"] < 7 * 86400 for s in latest):
        state = "Strategy updated"
    elif not obs:
        state = "Cold start"
    else:
        state = "Collecting data"
    per = []
    for c in cohorts:
        el = eligible_clips(c, settings)
        act = active_strategy(c)
        per.append({"cohort": c, "eligible_clips": len(el), "needed": int(_cfg(settings, "brain_min_clips")),
                    "strategy": act, "status": "Strategy updated" if act else "Not enough evidence yet"
                    if len(el) < _cfg(settings, "brain_min_clips") else "Evaluating"})
    return {"state": state, "observations": len(obs),
            "by_provenance": {p: sum(o["provenance"] == p for o in obs) for p in PROVENANCE},
            "cohorts": per, "versions": latest, "ranking": ranking_options(settings),
            "guards": {k: _cfg(settings, k) for k in DEFAULTS},
            "note": "Results from your selected viewers are test-audience evidence, not proof of how the wider public "
                    "would respond. AI quality scores and uploads are not viewer outcomes."}


def collect_platform_numbers(settings: dict) -> int:
    """File the latest stats of every selected-audience or staging upload as platform_api evidence."""
    n = 0
    for pub in db.list_publications():
        if pub["status"] not in ("done", "action_needed") or not (pub.get("info") or {}).get("audience"):
            continue
        hist = db.performance_history(pub["id"])
        if hist:
            n += record_platform_snapshot(pub, hist[0], settings)  # newest first
    return n


def evaluate_all(settings: dict, now: float | None = None) -> list[dict]:
    """Evaluate every selected-audience cohort (called by the learning job; asynchronous, never blocks clipping)."""
    from .autopilot import state

    out = []
    cohorts = sorted({o["cohort"] for o in current() if o["cohort"].startswith("selected:")})
    for c in cohorts:
        try:
            out.append(evaluate_length(c, settings, now))
        except Exception as exc:  # noqa: BLE001 - recorded as the Brain's Error state, never stops other work
            state.event("brain_error", f"Brain evaluation failed for {c}: {exc}", level="error")
            out.append({"cohort": c, "decision": "error", "message": str(exc)})
            continue
    state.event("brain_evaluated", f"Brain checked {len(cohorts)} test group(s): "
                + ("; ".join(f"{r['cohort']}: {r['message']}" for r in out) or "no observations yet"))
    return out
