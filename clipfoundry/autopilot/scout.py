"""Trend Scout and Source Scout.

Trend Scout collects signals from the legitimate providers (providers.py), keeps their history, and scores them
(trends.py). Source Scout turns signals into candidate sources, runs the rights gate on each, estimates how many
strong clips each one is likely to hold, ranks them, and sends the best eligible ones to the Clip Hunter, up to the
number of sources per day. A source that turns out weak does not count: Source Scout picks another one instead of
padding the day with weak clips.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from zoneinfo import ZoneInfo

from .. import db
from ..publish.common import PublishError
from . import providers, quota, rights, state, trends
from .host import MAINTENANCE_STEPS, PERIOD_ADJUST, Job, handler
from . import queue  # noqa: E402 - after host (registration order does not matter)

MIN_SOURCE_SECONDS = 240          # shorter videos rarely contain several standalone moments
YOUTUBE_RETENTION_DAYS = 30       # YouTube API data is refreshed or deleted within 30 days
ACTIVE_SOURCE = ("queued", "ingesting", "analyzing")
DONE_SOURCE = ("analyzed", "weak", "exhausted", "failed")
# Strong standalone moments per minute of video, by category (a starting estimate; learning refines it)
YIELD_PER_MINUTE = {"People & Blogs": 0.10, "Comedy": 0.10, "Education": 0.08, "Entertainment": 0.08,
                    "News & Politics": 0.08, "Sports": 0.07, "Science & Technology": 0.08, "Howto & Style": 0.06,
                    "Gaming": 0.05, "Film & Animation": 0.03, "Music": 0.01}
DEFAULT_YIELD = 0.07
SOURCE_WEIGHTS = {"trend": 0.35, "clip_potential": 0.30, "creator": 0.15, "freshness": 0.10, "live": 0.10,
                  "topic_results": 0.15}


def tz(settings: dict) -> ZoneInfo:
    try:
        return ZoneInfo(settings.get("autopilot_timezone") or "America/Chicago")
    except Exception:  # noqa: BLE001 - no tz database: stay usable
        return ZoneInfo("UTC")


def local_day(settings: dict, now: float | None = None) -> str:
    return dt.datetime.fromtimestamp(now or time.time(), tz(settings)).date().isoformat()


def topics(settings: dict) -> list[str]:
    return [t.strip() for t in str(settings.get("trend_topics") or "").split(",") if t.strip()]


# ------------------------------------------------------------------ signals
def upsert_signal(sig: dict, now: float) -> dict:
    existing = db.select("trend_signals", "platform = ? AND external_id = ?", (sig["platform"], sig["external_id"]))
    fields = {k: sig.get(k) for k in ("provider", "kind", "title", "url", "channel_id", "channel_title", "category",
                                      "keywords", "query", "region", "language", "published_at", "platform_rank",
                                      "metrics", "raw")}
    fields.update(last_checked=now, status="active")
    if existing:
        db.update("trend_signals", existing[0]["id"], **fields)
        sid = existing[0]["id"]
    else:
        sid = db.insert("trend_signals", {**fields, "platform": sig["platform"], "external_id": sig["external_id"],
                                          "first_seen": now})["id"]
    mt = sig.get("metrics") or {}
    if any(trends.val(mt, k) is not None for k in ("views", "live_viewers")):
        db.execute("INSERT INTO trend_history (signal_id, at, views, likes, comments, live_viewers, platform_rank) "
                   "VALUES (?,?,?,?,?,?,?)", (sid, now, trends.val(mt, "views"), trends.val(mt, "likes"),
                                              trends.val(mt, "comments"), trends.val(mt, "live_viewers"),
                                              sig.get("platform_rank")))
    return db.fetch("trend_signals", sid) or {}


def history(signal_id: str) -> list[dict]:
    return db.select("trend_history", "signal_id = ?", (signal_id,), "at")


def rescore(settings: dict, now: float | None = None) -> int:
    now = now or time.time()
    max_age = 3600 * float(settings.get("trend_max_age_hours") or 72)
    db.execute("UPDATE trend_signals SET status = 'expired' WHERE status = 'active' AND last_checked < ?",
               (now - max_age,))
    active = db.select("trend_signals", "status = 'active'")
    rec = trends.recurrence(active)
    for s in active:
        r = trends.score(s, history(s["id"]), settings, rec[s["id"]], now)
        db.update("trend_signals", s["id"], score=r["score"], score_mode=r["mode"], components=r["components"],
                  notes=r["notes"], topic=trends.topic_label(s, active) or s.get("topic") or "")
        db.execute("UPDATE trend_history SET score = ? WHERE id = (SELECT MAX(id) FROM trend_history WHERE "
                   "signal_id = ?)", (r["score"], s["id"]))
    return len(active)


def _provider_status(name: str, status: str, detail: str = "", count: int = 0, fix: str = "") -> dict:
    return {"name": name, "status": status, "detail": detail, "count": count, "fix": fix, "at": time.time()}


def collect_feeds(job: Job | None, statuses: dict) -> list[dict]:
    out: list[dict] = []
    for feed in providers.feeds():
        scan = providers.FEED_SCANNERS.get(feed["kind"])
        if not scan:
            continue
        try:
            sigs = scan(feed)
            db.update("source_feeds", feed["id"], last_checked=time.time(), last_error="")
            out += sigs
            statuses[f"feed:{feed['id']}"] = _provider_status(feed.get("name") or feed["kind"], "ok",
                                                               f"{len(sigs)} item(s)", len(sigs))
        except Exception as exc:  # noqa: BLE001 - one broken feed must not stop discovery
            db.update("source_feeds", feed["id"], last_checked=time.time(), last_error=str(exc)[:500])
            statuses[f"feed:{feed['id']}"] = _provider_status(feed.get("name") or feed["kind"], "error", str(exc))
        if job:
            job.check()
    return out


@handler("trend_scan")
def trend_scan(job: Job) -> dict:
    settings = db.get_settings()
    now = time.time()
    statuses: dict = dict(state.get("providers", {}) or {})
    collected: list[dict] = []
    job.progress(0.05, "Asking YouTube for trending and recent videos", stage="youtube")
    try:
        yt = providers.YouTubeDiscovery(settings)
        channels = [{"channel_id": f["config"].get("channel_id"), "name": f.get("name")}
                    for f in providers.feeds("youtube_channel")]
        per_scan = max(1, min(len(topics(settings)), 4))
        cursor = int(state.get("trend:topic_cursor", 0) or 0)
        all_topics = topics(settings)
        chosen = [all_topics[(cursor + k) % len(all_topics)] for k in range(per_scan)] if all_topics else []
        state.put("trend:topic_cursor", cursor + per_scan)
        include_live = bool(int(state.get("trend:scans", 0) or 0) % 2 == 0)
        sigs = yt.discover(chosen, channels, include_live, job)
        collected += sigs
        detail = f"{len(sigs)} videos · {yt.calls} API calls · {yt.cache_hits} from cache"
        if yt.denied:
            detail += f" · stopped early: {yt.denied[0]}"
        statuses["youtube"] = _provider_status("YouTube Data API", "quota" if yt.denied and not sigs else "ok", detail,
                                               len(sigs))
    except providers.Unavailable as exc:
        statuses["youtube"] = _provider_status("YouTube Data API", exc.status, str(exc), fix=exc.fix)
    except PublishError as exc:
        statuses["youtube"] = _provider_status("YouTube Data API", "error", str(exc), fix=exc.fix)
        if exc.code in ("reconnect", "setup"):
            state.action("youtube:discovery", "youtube", "YouTube discovery stopped", str(exc), exc.fix,
                         level="warning")
    state.put("trend:scans", int(state.get("trend:scans", 0) or 0) + 1)
    job.check()
    job.progress(0.5, "Checking watch folders and feeds", stage="feeds")
    collected += collect_feeds(job, statuses)
    for key, (name, detail) in providers.UNAVAILABLE.items():
        statuses[key] = _provider_status(name, "unavailable", detail)
    state.put("providers", statuses)
    for sig in collected:
        upsert_signal(sig, now)
    job.progress(0.8, "Scoring trends", stage="score")
    active = rescore(settings, now)
    state.put("trend:last_scan", {"at": now, "signals": len(collected), "active": active})
    queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}", priority=job.row["priority"])
    return {"signals": len(collected), "active": active, "message": f"{len(collected)} signals checked, "
                                                                   f"{active} active"}


@handler("feed_scan")
def feed_scan(job: Job) -> dict:
    """Frequent, free check of watch folders and stream/signal feeds (no API quota)."""
    statuses: dict = dict(state.get("providers", {}) or {})
    now = time.time()
    sigs = collect_feeds(job, statuses)
    state.put("providers", statuses)
    new = 0
    for sig in sigs:
        before = db.select("trend_signals", "platform = ? AND external_id = ?", (sig["platform"], sig["external_id"]))
        upsert_signal(sig, now)
        new += not before
    if sigs:
        rescore(db.get_settings(), now)
    if new:
        queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}",
                      priority=job.row["priority"])
    return {"signals": len(sigs), "new": new, "message": f"{new} new item(s) in watch folders and feeds"}


def _period(settings: dict, period: float) -> float:
    factor = quota.discovery_period_factor(settings)
    if factor == float("inf"):
        return max(period, quota.next_reset() - time.time() + 60)
    return period * factor


PERIOD_ADJUST["trend_scan"] = _period


# ------------------------------------------------------------------ sources
def source_from_signal(sig: dict) -> dict | None:
    raw = sig.get("raw") or {}
    base = {"platform": sig["platform"], "external_id": sig["external_id"], "title": sig.get("title", ""),
            "url": sig.get("url", ""), "channel_id": sig.get("channel_id", ""),
            "channel_title": sig.get("channel_title", ""), "signal_id": sig["id"], "topic": sig.get("topic", ""),
            "category": sig.get("category", ""), "published_at": sig.get("published_at"),
            "feed_id": raw.get("feed_id", ""), "metrics": sig.get("metrics") or {}}
    if sig["platform"] == "youtube":
        return {**base, "kind": "live" if sig.get("kind") == "live" else "recorded", "license": raw.get("license", ""),
                "live_status": raw.get("live_status", ""), "duration": raw.get("duration_s")}
    if sig["platform"] == "local":
        return {**base, "kind": "live" if raw.get("growing") else "recorded", "local_path": raw.get("path", ""),
                "live_status": "live" if raw.get("growing") else ""}
    if sig["platform"] == "stream":
        return {**base, "kind": "live", "live_status": "live"}
    return {**base, "kind": "live" if sig.get("kind") == "live" else "recorded"}


def upsert_source(src: dict) -> tuple[dict, bool]:
    existing = db.select("sources", "platform = ? AND external_id = ?", (src["platform"], src["external_id"]))
    if existing:
        keep = existing[0]
        refresh = {k: v for k, v in src.items() if k in ("title", "channel_title", "metrics", "live_status", "signal_id",
                                                           "topic", "category", "license", "duration", "kind")
                   and v not in (None, "")}
        if keep["status"] in DONE_SOURCE and refresh.get("kind") == "live":
            refresh.pop("kind")  # already clipped: a live flag must not restart it
        db.update("sources", keep["id"], **refresh)
        return db.fetch("sources", keep["id"]) or keep, False
    return db.insert("sources", {**src, "status": "discovered"}), True


def skip_reason(src: dict, sig: dict | None) -> str:
    raw = (sig or {}).get("raw") or {}
    if raw.get("made_for_kids"):
        return "Made for kids: not used (content safety)"
    if src["platform"] == "youtube" and src.get("kind") != "live":
        dur = src.get("duration")
        if dur is not None and dur < MIN_SOURCE_SECONDS:
            return f"Too short to clip from ({dur:.0f} s)"
    return ""


def yield_multiplier(category: str, channel_id: str) -> tuple[float, int]:
    """How past sources of this category/creator did against their estimate (shrunk toward 1 with little data)."""
    match, args = [], []
    if category:
        match.append("category = ?")
        args.append(category)
    if channel_id:
        match.append("channel_id = ?")
        args.append(channel_id)
    if not match:
        return 1.0, 0
    rows = db.select("sources", f"status IN ('analyzed', 'weak', 'exhausted') AND expected_clips > 0 AND "
                                f"({' OR '.join(match)})", args)
    if not rows:
        return 1.0, 0
    ratio = sum(r["clips_selected"] / max(0.5, r["expected_clips"]) for r in rows)
    k = 3.0  # pseudo-observations at the prior of 1.0
    return (ratio + k) / (len(rows) + k), len(rows)


def score_source(src: dict, sig: dict | None, settings: dict, now: float) -> dict:
    """Source Score (0-100), the expected number of strong clips, and the reasons."""
    cps = int(settings.get("autopilot_clips_per_source") or 5)
    comps: dict[str, dict] = {}
    if sig and sig.get("score") is not None:
        mode = sig.get("score_mode") or ""
        comps["trend"] = {"value": sig["score"] / 100, "note": f"Trend Score {sig['score']:.0f}"
                          + (" (YouTube's order)" if mode == trends.PLATFORM_ORDER else "")}
    else:
        comps["trend"] = {"value": 0.5, "note": "no trend signal (your own file or stream)"}
    minutes = (src.get("duration") or 0) / 60
    rate = YIELD_PER_MINUTE.get(src.get("category") or "", DEFAULT_YIELD)
    mult, n = yield_multiplier(src.get("category") or "", src.get("channel_id") or "")
    if src.get("kind") == "live":
        expected = float(cps)
        note = "live: judged while it runs"
    elif minutes:
        expected = min(float(cps), minutes * rate * mult)
        note = f"{minutes:.0f} min × {rate:.2f}/min" + (f" × {mult:.2f} from {n} past source(s)" if n else "")
    else:
        expected = min(float(cps), 2.0 * mult)
        note = "length unknown until the file is read"
    comps["clip_potential"] = {"value": min(1.0, expected / max(1, cps)), "note": note}
    if n:
        comps["creator"] = {"value": max(0.0, min(1.0, mult / 2)), "note": f"{mult:.2f}x the estimate before"}
    if src.get("published_at") and trends.derived_allowed(src["platform"], settings):
        age_h = max(0.0, (now - src["published_at"]) / 3600)
        comps["freshness"] = {"value": math.exp(-age_h / 48), "note": f"{age_h:.0f} h old"}
    if settings.get("autopilot_learning", True):
        from . import learner

        topic = (src.get("topic") or src.get("category") or "").lower()
        lift, posts = learner.lift("topic", topic) if topic else (1.0, 0)
        if posts:
            comps["topic_results"] = {"value": max(0.0, min(1.0, 0.5 * lift)),
                                      "note": f"{lift:.2f}x your average across {posts} of your posts on “{topic}”"}
    if src.get("kind") == "live":
        comps["live"] = {"value": 1.0 if settings.get("autopilot_live_monitoring") else 0.0,
                         "note": "live now" + ("" if settings.get("autopilot_live_monitoring") else
                                               " (live monitoring is off)")}
    total = sum(SOURCE_WEIGHTS[k] for k in comps)
    value = sum(SOURCE_WEIGHTS[k] * c["value"] for k, c in comps.items()) / total
    for k, c in comps.items():
        c["weight"] = SOURCE_WEIGHTS[k]
        c["value"] = round(c["value"], 3)
    return {"score": round(100 * value, 1), "expected": round(expected, 2), "components": comps}


def today_counts(settings: dict, now: float | None = None) -> dict:
    day = local_day(settings, now)
    rows = db.select("sources", "selected_day = ?", (day,))
    counted = [r for r in rows if r["status"] not in ("weak", "failed", "skipped", "needs_file")]
    clips = sum(r.get("clips_selected") or 0 for r in rows)
    return {"day": day, "selected": len(rows), "counted": len(counted), "clips": clips,
            "busy": sum(1 for r in rows if r["status"] in ACTIVE_SOURCE)}


RIGHTS_QUESTIONS = 5  # open rights questions at a time (the most promising sources)


@handler("source_scout")
def source_scout(job: Job) -> dict:
    settings = db.get_settings()
    now = time.time()
    all_rules = rights.rules()
    signals = db.select("trend_signals", "status = 'active'", (), "score DESC")
    created = 0
    for sig in signals:
        src = source_from_signal(sig)
        if not src:
            continue
        row, new = upsert_source(src)
        created += new
        if row["status"] in ("discovered", "eligible", "needs_rights", "blocked", "skipped"):
            reason = skip_reason(row, sig)
            if reason:
                db.update("sources", row["id"], status="skipped", status_note=reason)
                continue
            row = rights.apply(row, settings, all_rules)
            sc = score_source(row, sig, settings, now)
            db.update("sources", row["id"], source_score=sc["score"], expected_clips=sc["expected"],
                      components=sc["components"])
    job.check()
    picked = select_for_today(settings, now)
    # Ask about rights only for the most promising sources (not every trending video): the open questions are
    # always the current top 5; the rest stay listed under Autopilot → Sources.
    top = db.select("sources", "status = 'needs_rights'", (), "source_score DESC", RIGHTS_QUESTIONS)
    for src in top:
        rights.request_confirmation(src)
    asked = {f"rights:{s['id']}" for s in top}
    for item in state.open_actions():
        if item["key"].startswith("rights:") and item["key"] not in asked:
            state.resolve(item["key"])
    return {"sources_new": created, "picked": [p["id"] for p in picked],
            "message": f"{created} new source(s); {len(picked)} sent to the Clip Hunter"}


def select_for_today(settings: dict, now: float | None = None) -> list[dict]:
    """Send the best eligible sources to the Clip Hunter, up to today's number of sources.

    Weak sources do not count toward the day, so a weak pick is replaced by the next best source. When the day's
    sources are done but the clip target was not reached, one more source is tried at a time (at most three times
    the daily number of sources), never lowering the quality bar.
    """
    now = now or time.time()
    day = local_day(settings, now)
    per_day = int(settings.get("autopilot_sources_per_day") or 3)
    counts = today_counts(settings, now)
    needed = per_day - counts["counted"]
    if needed <= 0 and counts["busy"] == 0 and counts["clips"] < int(settings.get("autopilot_daily_target") or 15) \
            and counts["selected"] < 3 * per_day:
        needed = 1
    picked: list[dict] = []
    if needed <= 0:
        return picked
    for src in db.select("sources", "status = 'eligible' AND kind = 'recorded'", (), "source_score DESC", 50):
        if len(picked) >= needed:
            break
        if (src.get("expected_clips") or 0) < 1:
            db.update("sources", src["id"], status="skipped", status_note="Unlikely to contain a strong clip")
            continue
        ok, why = rights.download_allowed(src, settings)
        if not ok:
            db.update("sources", src["id"], status="needs_file", status_note=why)
            state.action(f"file:{src['id']}", "source_file", f"Add the video file for “{src['title'][:80]}”", why,
                         "Autopilot → Sources → Add file.", ref_type="source", ref_id=src["id"],
                         snooze_s=rights.ASK_AGAIN_AFTER)
            continue
        db.update("sources", src["id"], status="queued", selected_day=day, status_note="Waiting for the Clip Hunter")
        queue.enqueue("hunt_source", {"source_id": src["id"]}, idem_key=f"hunt:{src['id']}", ref=("source", src["id"]),
                      max_attempts=3, timeout_s=6 * 3600)
        state.event("source_selected", f"Selected “{src['title'][:80]}” (Source Score {src['source_score']:.0f}, "
                                       f"about {src['expected_clips']:.1f} strong clips expected)",
                    ref_type="source", ref_id=src["id"])
        picked.append(src)
    return picked


@handler("rights_check")
def rights_check(job: Job) -> dict:
    """Re-apply the rights rules to every source that is not finished (after a rule changed)."""
    settings = db.get_settings()
    all_rules = rights.rules()
    rows = db.select("sources", "status IN ('discovered', 'eligible', 'needs_rights', 'blocked', 'needs_file', "
                                "'queued')")
    changed = 0
    for src in rows:
        after = rights.apply(src, settings, all_rules)
        changed += after["rights_status"] != src["rights_status"]
        if after["rights_status"] == rights.BLOCKED and src["status"] == "queued":
            for j in queue.jobs(("queued", "retrying", "waiting"), ref=("source", src["id"])):
                queue.cancel(j["id"], "Rights status changed to Blocked")
    queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}", priority=job.row["priority"])
    return {"checked": len(rows), "changed": changed, "message": f"{changed} source(s) changed rights status"}


# ------------------------------------------------------------------ retention (YouTube: refresh or delete in 30 days)
def youtube_retention(job: Job | None = None, now: float | None = None) -> dict:
    """YouTube API data may be stored for at most 30 days, then it must be refreshed or deleted. Public data about
    other channels' videos (trend signals, discovered sources, cached responses) always follows this rule. Google's
    additional policy for derived metrics and data storage lets an approved project keep the statistics of the
    connected user's own videos longer, as long as the user still authorizes it (the account stays connected)."""
    settings = db.get_settings()
    keep_own = bool(settings.get("youtube_derived_metrics_approved")) and bool(db.get_account("youtube"))
    now = now or time.time()
    cutoff = now - YOUTUBE_RETENTION_DAYS * 86400
    old = [r["id"] for r in db.select("trend_signals", "platform = 'youtube' AND last_checked < ?", (cutoff,))]
    for sid in old:
        db.execute("DELETE FROM trend_history WHERE signal_id = ?", (sid,))
        db.execute("DELETE FROM trend_signals WHERE id = ?", (sid,))
    db.execute("DELETE FROM trend_history WHERE at < ? AND signal_id IN (SELECT id FROM trend_signals WHERE "
               "platform = 'youtube')", (cutoff,))
    unused = db.execute("DELETE FROM sources WHERE platform = 'youtube' AND updated_at < ? AND project_id = '' AND "
                        "status NOT IN ('queued', 'ingesting', 'analyzing')", (cutoff,))
    cleared = db.execute("UPDATE sources SET metrics = '{}', updated_at = ? WHERE platform = 'youtube' AND "
                         "updated_at < ? AND metrics != '{}'", (now, cutoff))
    perf = 0 if keep_own else db.execute("DELETE FROM performance WHERE platform = 'youtube' AND fetched_at < ?",
                                         (cutoff,))
    db.execute("DELETE FROM api_cache WHERE fetched_at < ?", (cutoff,))
    return {"youtube_signals_deleted": len(old), "youtube_sources_deleted": unused,
            "youtube_sources_cleared": cleared, "youtube_snapshots_deleted": perf,
            "own_statistics": "kept (storage approved)" if keep_own else "30 days"}


MAINTENANCE_STEPS.append(youtube_retention)
