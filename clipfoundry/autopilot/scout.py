"""Trend Scout and Source Scout.

Trend Scout collects signals from the legitimate providers (providers.py), keeps their history, and scores them
(trends.py). Source Scout turns signals into candidate sources, runs the rights gate on each, estimates how many
strong clips each one is likely to hold, ranks them, and sends the best eligible ones to the Clip Hunter, up to the
number of sources per day. A source that turns out weak does not count: Source Scout picks another one instead of
padding the day with weak clips.

Nothing that is unclear blocks the day. A video no agreement, license or ownership covers, or whose file cannot be
obtained in an allowed way (access.py), is skipped with its reason (the activity log shows it) and the next best
video is tried. You are only asked about such videos if you turn that on under Advanced.

A channel a feed names is confirmed with the platform before any channel rule or ownership counts for it
(verify.py). A video whose channel could not be confirmed is skipped with the reason and never asked about.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from zoneinfo import ZoneInfo

from .. import db
from ..pipeline import fingerprint
from ..publish.common import PublishError
from . import access, providers, quota, rights, state, trends, verify
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


def day_bounds(settings: dict, now: float | None = None) -> tuple[float, float]:
    """(start, end) in UTC seconds of the local day that contains `now`: 23 or 25 hours on daylight-saving days."""
    zone = tz(settings)
    day = dt.datetime.fromtimestamp(now or time.time(), zone).date()
    return (dt.datetime.combine(day, dt.time(0, 0), zone).timestamp(),
            dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), zone).timestamp())


def topics(settings: dict) -> list[str]:
    return [t.strip() for t in str(settings.get("trend_topics") or "").split(",") if t.strip()]


EMERGING_MAX = 3


def emerging_topics(signals: list[dict], known: list[str]) -> list[str]:
    """Words that several different creators' web results share and that are not one of your topics yet: an
    emerging topic, searched on YouTube in the next scans."""
    seen: dict[str, set] = {}
    for s in signals:
        for k in (s.get("keywords") or [])[:3]:
            seen.setdefault(k, set()).add(s.get("channel_id") or s.get("external_id"))
    low = {t.lower() for t in known}
    ranked = sorted((k for k, who in seen.items() if len(who) >= 2 and k not in low), key=lambda k: -len(seen[k]))
    return ranked[:EMERGING_MAX]


# ------------------------------------------------------------------ signals
def _official(provider: str) -> bool:
    """A signal built from the platform's own API answer (not a list someone else keeps)."""
    return provider.startswith("youtube_")


def upsert_signal(sig: dict, now: float) -> dict:
    existing = db.select("trend_signals", "platform = ? AND external_id = ?", (sig["platform"], sig["external_id"]))
    if existing and _official(existing[0].get("provider") or "") and not _official(sig.get("provider") or ""):
        # a feed row about a video the platform's own API already described: it keeps the video active, but never
        # replaces what the platform reported (its channel, link, license or made-for-kids flag)
        db.update("trend_signals", existing[0]["id"], last_checked=now, status="active")
        return db.fetch("trend_signals", existing[0]["id"]) or existing[0]
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
        try:
            r = trends.score(s, history(s["id"]), settings, rec[s["id"]], now)
        except Exception as exc:  # noqa: BLE001 - one unreadable discovery row never blocks the rest
            db.update("trend_signals", s["id"], status="expired")
            state.event("discovery_skipped", f"Skipped an unreadable video description: {exc}", "warning")
            continue
        # the evidence entry (weight 0) keeps the coverage, confidence and missing parts next to the parts
        db.update("trend_signals", s["id"], score=r["score"], score_mode=r["mode"],
                  components={**r["components"], "evidence": r["evidence"]}, notes=r["notes"],
                  topic=trends.topic_label(s, active) or s.get("topic") or "")
        db.execute("UPDATE trend_history SET score = ? WHERE id = (SELECT MAX(id) FROM trend_history WHERE "
                   "signal_id = ?)", (r["score"], s["id"]))
    return len(active)


def _provider_status(name: str, status: str, detail: str = "", count: int = 0, fix: str = "",
                     problem: str = "") -> dict:
    """`detail` is the technical line (Advanced → System); `problem`, when set, is why it did not work in plain words
    (the main page, home.discovery_status)."""
    return {"name": name, "status": status, "detail": detail, "count": count, "fix": fix, "problem": problem,
            "at": time.time()}


def _search_error(name: str, exc: Exception) -> dict:
    """Keep a temporary failure local to one search; later periodic scans always get a fresh attempt."""
    asked = getattr(exc, "retry_after", None)
    if asked is not None:
        state.put("next:trend_scan", max(float(state.get("next:trend_scan", 0) or 0), time.time() + float(asked)))
    return _provider_status(name, "error", str(exc), problem=f"{name} did not work last time.",
                            fix="ClipFoundry will try again automatically.")


QUOTA_CODES = ("quotaExceeded", "dailyLimitExceeded")  # YouTube's daily allowance: it resets by itself


def discovery_rules(settings: dict) -> list[dict]:
    """Recorded, active permissions also tell discovery where to look; every video still passes the rights gate."""
    now = time.time()
    return [r for r in rights.rules() if rights.auto_allowed(r["status"], settings)
            and (not r.get("expires_at") or r["expires_at"] > now)]


def discovery_channels(settings: dict) -> list[dict]:
    channels = {f["config"]["channel_id"]: f.get("name") for f in providers.feeds("youtube_channel")
                if f["config"].get("channel_id")}
    account = db.get_account("youtube") or {}
    if account.get("has_tokens") and account.get("account_id"):
        channels.setdefault(account["account_id"], account.get("display_name") or "Your channel")
    for rule in discovery_rules(settings):
        if rule["scope"] == "channel" and rule.get("platform") in ("", "youtube") and rule["value"].startswith("UC"):
            channels.setdefault(rule["value"], rule.get("label") or rule["value"])
    return [{"channel_id": channel, "name": name} for channel, name in channels.items()]


def discovery_feeds(settings: dict) -> list[dict]:
    feeds = providers.feeds()
    folders = {rights.normalize_path(f["config"].get("path") or "") for f in feeds if f["kind"] == "watch_folder"}
    for rule in discovery_rules(settings):
        if rule["scope"] != "folder" or (rule.get("conditions") or {}).get("kind") != "agreement":
            continue
        path = rights.normalize_path(rule["value"])
        if path in folders:
            continue
        folders.add(path)
        feeds.append({"id": f"agreement:{rule['id']}", "kind": "watch_folder", "name": rule.get("label") or
                      "Creator's shared folder", "config": {"path": path, "recursive": True}, "implicit": True})
    return feeds


def collect_feeds(job: Job | None, statuses: dict) -> list[dict]:
    out: list[dict] = []
    for feed in discovery_feeds(db.get_settings()):
        scan = providers.FEED_SCANNERS.get(feed["kind"])
        if not scan:
            continue
        try:
            sigs = scan(feed)
            if not feed.get("implicit"):
                db.update("source_feeds", feed["id"], last_checked=time.time(), last_error="")
            out += sigs
            statuses[f"feed:{feed['id']}"] = _provider_status(feed.get("name") or feed["kind"], "ok",
                                                               f"{len(sigs)} item(s)", len(sigs))
        except Exception as exc:  # noqa: BLE001 - one broken feed must not stop discovery
            if not feed.get("implicit"):
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
    per_scan = max(1, min(len(topics(settings)), 4))
    cursor = int(state.get("trend:topic_cursor", 0) or 0)
    all_topics = topics(settings)
    chosen = [all_topics[(cursor + k) % len(all_topics)] for k in range(per_scan)] if all_topics else []
    state.put("trend:topic_cursor", cursor + per_scan)
    emerging = [t for t in (state.get("trend:emerging") or []) if t not in chosen][:1]
    chosen += emerging
    yt: providers.YouTubeDiscovery | None = None
    job.progress(0.05, "Asking YouTube for trending and recent videos", stage="youtube")
    try:
        yt = providers.YouTubeDiscovery(settings)
        channels = discovery_channels(settings)
        include_live = bool(int(state.get("trend:scans", 0) or 0) % 2 == 0)
        sigs = yt.discover(chosen, channels, include_live, job)
        collected += sigs
        detail = f"{len(sigs)} videos · {yt.calls} API calls · {yt.cache_hits} from cache"
        if yt.denied:
            detail += f" · stopped early: {yt.denied[0]}"
        status = "quota" if yt.denied and not sigs else "ok"
        fix = problem = ""
        if yt.errors:
            first = yt.errors[0]
            status = "quota" if any(e.code in QUOTA_CODES for e in yt.errors) else "error"
            fix, problem = first.fix, str(first)
            detail += f" · {first}"
            for exc in yt.errors:
                if exc.retry_after is not None:
                    state.put("next:trend_scan", max(float(state.get("next:trend_scan", 0) or 0), now + exc.retry_after))
                if exc.code in ("reconnect", "setup"):
                    state.action("youtube:discovery", "youtube", "YouTube discovery stopped", str(exc), exc.fix,
                                 level="warning")
            yt = None  # optional searches must not reuse this client to bypass a platform's wait
        else:
            state.resolve("youtube:discovery")
        statuses["youtube"] = _provider_status("YouTube Data API", status, detail, len(sigs), fix, problem)
    except providers.Unavailable as exc:
        statuses["youtube"] = _provider_status("YouTube Data API", exc.status, str(exc), fix=exc.fix)
    except PublishError as exc:
        yt = None
        statuses["youtube"] = _provider_status("YouTube Data API", "quota" if exc.code in QUOTA_CODES else "error",
                                               str(exc), fix=exc.fix)
        if exc.retry_after is not None:  # YouTube asked to wait: the next scan is not sooner than that
            state.put("next:trend_scan", max(float(state.get("next:trend_scan", 0) or 0), now + exc.retry_after))
        if exc.code in ("reconnect", "setup"):
            state.action("youtube:discovery", "youtube", "YouTube discovery stopped", str(exc), exc.fix,
                         level="warning")
    except queue.Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - the free library and folders still work while YouTube is unavailable
        yt = None
        statuses["youtube"] = _search_error("YouTube search", exc)
    state.put("trend:scans", int(state.get("trend:scans", 0) or 0) + 1)
    job.check()
    job.progress(0.3, "Searching the web for public TikTok links", stage="web")
    collected += web_search(settings, chosen, yt, statuses, job)
    job.progress(0.4, "Searching the free-license library", stage="library")
    collected += library_search(settings, chosen, statuses, job)
    job.progress(0.5, "Checking watch folders and feeds", stage="feeds")
    collected += collect_feeds(job, statuses)
    for key, (name, detail) in providers.UNAVAILABLE.items():
        statuses[key] = _provider_status(name, "unavailable", detail)
    state.put("providers", statuses)
    accepted = 0
    for sig in collected:
        job.check()
        try:
            upsert_signal(sig, now)
            accepted += 1
        except Exception as exc:  # noqa: BLE001 - malformed result is skipped, other searches are retained
            state.event("discovery_skipped", f"Skipped an unreadable video description: {exc}", "warning")
    job.progress(0.8, "Scoring trends", stage="score")
    active = rescore(settings, now)
    state.put("trend:last_scan", {"at": now, "signals": accepted, "active": active})
    queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}", priority=job.row["priority"])
    return {"signals": len(collected), "active": active, "topics": chosen,
            "message": f"{len(collected)} signals checked, {active} active"}


def web_search(settings: dict, chosen: list[str], yt: providers.YouTubeDiscovery | None, statuses: dict,
               job: Job) -> list[dict]:
    """Optional web search: public TikTok links (no statistics) and the originals behind popular TikTok clips. A
    failure or an empty allowance never stops the rest of discovery."""
    name = "Web search (Tavily)"
    try:
        ws = providers.WebSearch(settings)
        sigs = ws.discover(chosen, yt, job)
    except providers.Unavailable as exc:
        statuses["web_search"] = _provider_status(name, "unavailable" if exc.status == "not_configured" else
                                                  exc.status, str(exc), fix=exc.fix)
        return []
    except queue.Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - optional search must not prevent other discovery
        statuses["web_search"] = _search_error("Web search", exc)
        return []
    use = providers.web_usage(settings)
    tiktok = [s for s in sigs if s["platform"] == "tiktok"]
    state.put("trend:emerging", emerging_topics(tiktok, topics(settings)))
    detail = (f"{len(tiktok)} TikTok links, {len(sigs) - len(tiktok)} originals · {use['used']} of {use['allowed']} "
              f"credits this month" + (f" · stopped early: {ws.stopped}" if ws.stopped else ""))
    statuses["web_search"] = _provider_status(name, "ok", detail, len(sigs))
    return sigs


def library_search(settings: dict, chosen: list[str], statuses: dict, job: Job) -> list[dict]:
    name = "Free-license library (Wikimedia Commons)"
    try:
        lib = providers.Library(settings)
        sigs = lib.discover(chosen, job)
    except providers.Unavailable as exc:
        statuses["library"] = _provider_status(name, "unavailable" if exc.status == "off" else exc.status, str(exc),
                                               fix=exc.fix)
        return []
    except (ValueError, TypeError) as exc:  # an answer in an unexpected shape: skip it this time
        statuses["library"] = _provider_status(name, "error", f"Unexpected answer: {exc}",
                                               problem="Wikimedia Commons sent an answer ClipFoundry could not read.")
        return []
    except queue.Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - folders are still checked when the library is offline
        statuses["library"] = _search_error("The free video library", exc)
        return []
    statuses["library"] = _provider_status(name, "ok", f"{len(sigs)} videos with a license", len(sigs))
    return sigs


@handler("feed_scan")
def feed_scan(job: Job) -> dict:
    """Frequent, free check of watch folders and stream/signal feeds (no API quota)."""
    statuses: dict = dict(state.get("providers", {}) or {})
    now = time.time()
    reconcile_sources(now)
    sigs = collect_feeds(job, statuses)
    state.put("providers", statuses)
    new = 0
    for sig in sigs:
        before = db.select("trend_signals", "platform = ? AND external_id = ?", (sig["platform"], sig["external_id"]))
        upsert_signal(sig, now)
        new += not before
    if sigs:
        rescore(db.get_settings(), now)
    # A known recording can stop growing, or a creator's missing original can arrive, without a new signal ID.
    # Check these on the free folder cadence instead of waiting for another (possibly quota-delayed) web scan.
    if sigs or db.scalar("SELECT COUNT(*) FROM sources WHERE status IN ('eligible', 'needs_file')"):
        queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}",
                      priority=job.row["priority"])
    return {"signals": len(sigs), "new": new, "message": f"{new} new item(s) in watch folders and feeds"}


def reconcile_sources(now: float | None = None) -> int:
    """A canceled/timed-out/crashed handler may never run its source cleanup. Release that source's daily slot.
    Leave active leases, retries and waits alone, and never restart work the user canceled."""
    now = time.time() if now is None else now
    changed = 0
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT s.id, s.project_id, j.status, j.error, j.message FROM sources s JOIN worker_jobs j ON j.id = "
            "(SELECT id FROM worker_jobs WHERE ref_type = 'source' AND ref_id = s.id AND kind IN "
            "('hunt_source', 'analyze_source') ORDER BY created_at DESC LIMIT 1) "
            "WHERE s.kind = 'recorded' AND s.status IN ('queued', 'ingesting', 'analyzing') "
            "AND j.status IN ('failed', 'canceled') AND NOT EXISTS "
            "(SELECT 1 FROM worker_jobs a WHERE a.ref_type = 'source' AND a.ref_id = s.id "
            "AND a.status IN ('queued', 'running', 'waiting', 'retrying'))").fetchall()
        for row in rows:
            detail = (row["error"] or row["message"] or row["status"])[:400]
            note = f"Processing stopped: {detail}"
            conn.execute("UPDATE sources SET status = 'failed', error = ?, status_note = ?, updated_at = ? WHERE id = ?",
                         (detail, note, now, row["id"]))
            if row["project_id"]:
                conn.execute("UPDATE projects SET status = 'error', error = ?, message = ?, updated_at = ? WHERE id = ?",
                             (detail, note, now, row["project_id"]))
            changed += 1
    return changed


def refill(item: dict) -> dict | None:
    """A failed or weak video releases its turn immediately; select another without waiting for the next search.
    Explicit cancellation remains final for that video. The replacement is separate, ordinary discovery work."""
    if not state.enabled():
        return None
    key = item.get("ref_id") or item.get("id") or "recovery"
    return queue.enqueue("source_scout", {"reason": "replacement"},
                         idem_key=f"refill:{key}:{item.get('updated_at') or item.get('finished_at') or ''}",
                         revive=False, message="Choosing another video")


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
    if raw.get("webpage"):
        base["access"] = {"webpage": True}
    if sig["platform"] == "youtube":
        return {**base, "kind": "live" if sig.get("kind") == "live" else "recorded", "license": raw.get("license", ""),
                "live_status": raw.get("live_status", ""), "duration": raw.get("duration_s")}
    if sig["platform"] == "local":
        return {**base, "kind": "live" if raw.get("growing") else "recorded", "local_path": raw.get("path", ""),
                "live_status": "live" if raw.get("growing") else ""}
    if sig["platform"] == "stream":
        return {**base, "kind": "live", "live_status": "live"}
    if sig["platform"] == "commons":
        return {**base, "kind": "recorded", "license": raw.get("license", ""), "duration": raw.get("duration_s"),
                "rights_info": {k: raw.get(k) for k in providers.LICENSE_KEYS}}
    if raw.get("signal_only") and not db.get_settings().get("autopilot_public_videos"):
        return None  # a web search result: a topic signal and a pointer to originals, not something to clip
    return {**base, "kind": "live" if sig.get("kind") == "live" else "recorded"}


def upsert_source(src: dict) -> tuple[dict, bool]:
    existing = db.select("sources", "platform = ? AND external_id = ?", (src["platform"], src["external_id"]))
    if existing:
        keep = existing[0]
        refresh = {k: v for k, v in src.items() if k in ("title", "channel_title", "metrics", "live_status", "signal_id",
                                                           "topic", "category", "license", "duration", "kind",
                                                           "rights_info")
                   and v not in (None, "", {})}
        if keep["status"] in DONE_SOURCE and refresh.get("kind") == "live":
            refresh.pop("kind")  # already clipped: a live flag must not restart it
        db.update("sources", keep["id"], **refresh)
        return db.fetch("sources", keep["id"]) or keep, False
    return db.insert("sources", {**src, "status": "discovered"}), True


def skip_reason(src: dict, sig: dict | None, settings: dict | None = None) -> str:
    raw = (sig or {}).get("raw") or {}
    if raw.get("made_for_kids"):
        return "Made for kids: not used (content safety)"
    if not src.get("user_added") and src["platform"] in ("youtube", "commons") and src.get("kind") != "live":
        dur = src.get("duration")
        if dur is not None and dur < MIN_SOURCE_SECONDS:
            return f"Too short to clip from ({dur:.0f} s)"
    limit = float((settings or {}).get("autopilot_max_source_gb") or 8) * 1e9
    if raw.get("size") and float(raw["size"]) > limit:
        return f"The file is too large ({float(raw['size']) / 1e9:.1f} GB; the limit is {limit / 1e9:.0f} GB)"
    return repeat_of(src)


def repeat_of(src: dict) -> str:
    """Why this looks like a video already processed under another address (a re-upload), or ""."""
    title = fingerprint.norm_title(src.get("title") or "")
    if len(title.split()) < 3:
        return ""
    done = db.select("sources", "status IN ('queued', 'ingesting', 'analyzing', 'analyzed', 'weak', 'exhausted') AND "
                                "NOT (platform = ? AND external_id = ?)", (src["platform"], src["external_id"]))
    for d in done:
        if fingerprint.title_similarity(d.get("title") or "", src.get("title") or "") < 0.85:
            continue
        if src.get("duration") and d.get("duration") and abs(float(src["duration"]) - float(d["duration"])) > 5:
            continue  # same words, different video (a later episode)
        return f"Same video as “{(d.get('title') or '')[:60]}”, already {d['status']}"
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
    """Source Score (0-100), the expected number of strong clips, and the reasons.

    Every part that applies counts; one without data counts as neutral (trends.combine), so a video ClipFoundry knows
    little about stays near 50 instead of ranking high on one or two numbers. `components` stores the parts with
    data and an "evidence" entry (weight 0): coverage, confidence and the missing parts with their reason."""
    cps = int(settings.get("autopilot_clips_per_source") or 5)
    comps: dict[str, dict] = {}
    readings = 0
    if sig and sig.get("score") is not None:
        mode = sig.get("score_mode") or ""
        ev = (sig.get("components") or {}).get("evidence") or {}
        # a sparse Trend Score is already shrunk toward 50; its coverage only lowers this score's coverage
        quality = float(ev["coverage"]) if ev.get("coverage") is not None else 1.0
        readings = int(ev["readings"]) if ev.get("readings") is not None else 1  # scored before readings were kept
        comps["trend"] = {"value": sig["score"] / 100, "quality": quality,
                          "note": f"Trend Score {sig['score']:.0f}" + (" (YouTube's order)" if mode ==
                                                                       trends.PLATFORM_ORDER else "")
                          + (f", confidence {ev['confidence']}" if ev.get("confidence") else "")}
    else:
        comps["trend"] = {"value": None, "note": "no trend signal (your own file or stream, or a link you added)"}
    minutes = (src.get("duration") or 0) / 60
    rate = YIELD_PER_MINUTE.get(src.get("category") or "", DEFAULT_YIELD)
    mult, n = yield_multiplier(src.get("category") or "", src.get("channel_id") or "")
    if src.get("kind") == "live":
        expected = float(cps)
        comps["clip_potential"] = {"value": None, "note": "live: judged while it runs"}
    elif minutes:
        expected = min(float(cps), minutes * rate * mult)
        comps["clip_potential"] = {"value": min(1.0, expected / max(1, cps)),
                                   "note": f"{minutes:.0f} min × {rate:.2f}/min" +
                                   (f" × {mult:.2f} from {n} past source(s)" if n else "")}
    else:
        expected = min(float(cps), 2.0 * mult)  # only decides whether it is worth reading; not counted as evidence
        comps["clip_potential"] = {"value": None, "note": "length unknown until the file is read"}
    comps["creator"] = ({"value": max(0.0, min(1.0, mult / 2)), "note": f"{mult:.2f}x the estimate before"} if n else
                        {"value": None, "note": "no finished videos of this creator or category yet"})
    if src.get("published_at") and trends.derived_allowed(src["platform"], settings):
        age_h = max(0.0, (now - src["published_at"]) / 3600)
        comps["freshness"] = {"value": math.exp(-age_h / 48), "note": f"{age_h:.0f} h old"}
    else:
        comps["freshness"] = {"value": None, "note": "upload time not reported" if not src.get("published_at") else
                              "not computed from YouTube data without Google's approval"}
    if settings.get("autopilot_learning", True):
        from . import learner

        topic = (src.get("topic") or src.get("category") or "").lower()
        lift, posts = learner.lift("topic", topic) if topic else (1.0, 0)
        comps["topic_results"] = ({"value": max(0.0, min(1.0, 0.5 * lift)),
                                   "note": f"{lift:.2f}x your average across {posts} of your posts on “{topic}”"}
                                  if posts else {"value": None, "note": "no results of your posts on this topic yet"})
    if src.get("kind") == "live":
        comps["live"] = {"value": 1.0 if settings.get("autopilot_live_monitoring") else 0.0,
                         "note": "live now" + ("" if settings.get("autopilot_live_monitoring") else
                                               " (live monitoring is off)")}
    weights = {k: SOURCE_WEIGHTS[k] for k in comps}
    value, coverage = trends.combine(comps, weights)
    missing = {k: c["note"] for k, c in comps.items() if c["value"] is None}
    have = {k: c for k, c in comps.items() if c["value"] is not None}
    for k, c in have.items():
        c.pop("quality", None)
        c["weight"] = SOURCE_WEIGHTS[k]
        c["value"] = round(c["value"], 3)
    ev = trends.evidence(coverage, readings, missing)
    return {"score": round(100 * value, 1), "expected": round(expected, 2), "components": {**have, "evidence": ev},
            "coverage": ev["coverage"], "confidence": ev["confidence"], "missing": missing}


def today_counts(settings: dict, now: float | None = None) -> dict:
    day = local_day(settings, now)
    rows = db.select("sources", "selected_day = ?", (day,))
    counted = [r for r in rows if not r.get("user_added") and r["status"] not in
               ("weak", "failed", "skipped", "needs_file", "needs_rights", "blocked", "canceled", "removed")]
    clips = sum(r.get("clips_selected") or 0 for r in rows)
    from . import gate

    for row in rows:
        if not row.get("project_id"):
            continue
        failed = sum(1 for c in db.list_clips(row["project_id"])
                     if (gate.report_for(c) or {}).get("status") == "failed")
        clips -= min(int(row.get("clips_selected") or 0), failed)
    return {"day": day, "selected": len(rows), "counted": len(counted), "clips": clips,
            "busy": sum(1 for r in rows if r["status"] in ACTIVE_SOURCE)}


RIGHTS_QUESTIONS = 3      # open rights questions at most, however many sources are short
RIGHTS_MIN_SCORE = 50.0   # below this Source Score a video is not worth asking you about


@handler("source_scout")
def source_scout(job: Job) -> dict:
    settings = db.get_settings()
    now = time.time()
    reconcile_sources(now)
    all_rules = rights.rules()
    signals = db.select("trend_signals", "status = 'active'", (), "score DESC")
    created = 0
    pending: list[tuple[dict, dict]] = []
    for sig in signals:
        src = source_from_signal(sig)
        if not src:
            continue
        row, new = upsert_source(src)
        created += new
        if row["status"] in ("discovered", "eligible", "needs_rights", "blocked", "skipped"):
            reason = skip_reason(row, sig, settings)
            if reason:
                db.update("sources", row["id"], status="skipped", status_note=reason)
                continue
            verify.from_signal(row, sig)  # found through the platform's API: its answer names the channel already
            pending.append((row, sig))
    verify.ensure([row for row, _ in pending], settings, now)  # the channels feeds named, 50 videos per lookup
    job.check()
    for row, sig in pending:
        row = rights.apply(row, settings, all_rules)
        sc = score_source(row, sig, settings, now)
        db.update("sources", row["id"], source_score=sc["score"], expected_clips=sc["expected"],
                  components=sc["components"])
    job.check()
    picked = select_for_today(settings, now)
    top = rights_questions(settings, now) if settings.get("rights_ask_per_video") else []
    for src in top:
        rights.request_confirmation(src)
    asked = {f"rights:{s['id']}" for s in top}
    for item in state.open_actions():  # a missing file is never asked about: the activity log offers "Add the file"
        if (item["key"].startswith("rights:") and item["key"] not in asked) or item["key"].startswith("file:"):
            state.resolve(item["key"])
    return {"sources_new": created, "picked": [p["id"] for p in picked],
            "message": f"{created} new source(s); {len(picked)} sent to the Clip Hunter"}


def still_needed(settings: dict, now: float | None = None) -> int:
    """How many more sources today's plan needs.

    Weak sources do not count toward the day, so a weak pick is replaced by the next best source. When the day's
    sources are done but the clip target was not reached, one more source is tried at a time, never lowering the
    quality bar or permanently exhausting discovery after a series of weak results.
    """
    per_day = int(settings.get("autopilot_sources_per_day") or 3)
    counts = today_counts(settings, now)
    needed = per_day - counts["counted"]
    if needed <= 0 and counts["busy"] == 0 and counts["clips"] < int(settings.get("autopilot_daily_target") or 15):
        needed = 1
    return max(0, needed)


def rights_questions(settings: dict, now: float | None = None) -> list[dict]:
    """The sources worth asking you about: only while today's plan is still short after every source that may
    already be used was picked, only strong ones, and never more than RIGHTS_QUESTIONS. Everything else stays in
    discovery (listed under Advanced) until it becomes important enough."""
    short = min(RIGHTS_QUESTIONS, still_needed(settings, now))
    if short <= 0:
        return []
    rows = db.select("sources", "status = 'needs_rights' AND source_score >= ? AND expected_clips >= 1",
                     (RIGHTS_MIN_SCORE,), "source_score DESC", 50)
    # a video whose channel the platform did not confirm is skipped, never asked about
    return [s for s in rows if _usable_after_yes(s, settings) and not verify.unconfirmed_claim(s)][:short]


def _usable_after_yes(src: dict, settings: dict) -> bool:
    """A platform's live stream can only be recorded with the download setting (there is no file to give): a yes
    would lead nowhere, so it is not asked about."""
    return not (src.get("kind") == "live" and rights.is_platform_url(src.get("url") or "")
                and not settings.get("rights_allow_remote_download"))


def select_for_today(settings: dict, now: float | None = None) -> list[dict]:
    """Send the best eligible sources to the Clip Hunter, up to what today's plan still needs (still_needed)."""
    now = now or time.time()
    day = local_day(settings, now)
    needed = still_needed(settings, now)
    picked: list[dict] = []
    rows = db.select("sources", "status IN ('eligible', 'needs_file') AND kind = 'recorded'", (),
                     "user_added DESC, status = 'needs_file', source_score DESC")
    all_rules = rights.rules()
    automatic_picks = 0
    for src in rows:
        if not src.get("user_added") and automatic_picks >= needed:
            continue
        if not src.get("user_added") and (src.get("expected_clips") or 0) < 1:
            db.update("sources", src["id"], status="skipped", status_note="Unlikely to contain a strong clip")
            continue
        if not rights.local_allowed(src, rights.evaluate(src, settings, all_rules), settings):
            rights.apply(src, settings, all_rules)
            continue
        try:
            found = access.resolve(src, settings)  # one bad file cannot stop other useful videos
        except queue.Canceled:
            raise
        except Exception as exc:  # noqa: BLE001 - failed access is scoped to this video
            db.update("sources", src["id"], status="failed", error=str(exc)[:500],
                      status_note=f"Could not access video: {exc}"[:300])
            state.event("source_failed", f"Skipped “{src['title'][:80]}”: {exc}", "warning",
                        ref_type="source", ref_id=src["id"])
            continue
        if not found["ok"]:
            if src["status"] != "needs_file" or src.get("status_note") != found["detail"]:
                db.update("sources", src["id"], status="needs_file", status_note=found["detail"],
                          access=access.record(src, found))
            continue
        state.resolve(f"file:{src['id']}")
        db.update("sources", src["id"], status="queued", selected_day=day, status_note="Waiting for the Clip Hunter",
                  access=access.record(src, found))
        queue.enqueue("hunt_source", {"source_id": src["id"]}, idem_key=f"hunt:{src['id']}", ref=("source", src["id"]),
                      priority=queue.source_priority(src) if src.get("user_added") else 0, revive=False,
                      max_attempts=3, timeout_s=6 * 3600)
        sure = ((src.get("components") or {}).get("evidence") or {}).get("confidence")  # how far the score holds
        state.event("source_selected", f"Selected “{src['title'][:80]}” (Source Score {src['source_score']:.0f}"
                                       + (f", confidence {sure}" if sure else "") +
                                       f", about {src['expected_clips']:.1f} strong clips expected)",
                    ref_type="source", ref_id=src["id"])
        picked.append(src)
        automatic_picks += not src.get("user_added")
    return picked


REAPPLY = ("discovered", "eligible", "needs_rights", "blocked", "needs_file", "queued")  # not started yet


def reapply(rows: list[dict], settings: dict, all_rules: list[dict] | None = None) -> int:
    """Apply the rights again to sources that were not started yet. One that was waiting for the Clip Hunter and is
    no longer covered loses its turn: its queued hunt is canceled, and the activity log says why."""
    all_rules = rights.rules() if all_rules is None else all_rules
    changed = 0
    for src in rows:
        after = rights.apply(src, settings, all_rules)
        changed += after["rights_status"] != src["rights_status"]
        if src["status"] == "queued" and after["status"] != "queued":
            for j in queue.jobs(("queued", "retrying", "waiting"), ref=("source", src["id"])):
                queue.cancel(j["id"], f"Not used: {after['rights']['label']} ({after['rights']['basis']})"[:300])
    return changed


@handler("rights_check")
def rights_check(job: Job) -> dict:
    """Re-apply the rights rules to every source that is not finished (after a rule changed)."""
    settings = db.get_settings()
    marks = ",".join("?" * len(REAPPLY))
    rows = db.select("sources", f"status IN ({marks})", REAPPLY)
    verify.ensure(rows, settings)  # channels named by feeds that were never confirmed, or are due for another look
    changed = reapply(rows, settings)
    # A public video clipped before a rule covered (or blocked) it keeps its clips: its stored rights must follow
    # the rule, so the Queue and Activity say what the scheduler and publisher decide (they evaluate it afresh)
    done = db.select("sources", "status IN ('analyzed', 'weak', 'exhausted')")
    changed += reapply(done, settings)
    queue.enqueue("source_scout", {"after": job.id}, idem_key=f"source_scout:{job.id}", priority=job.row["priority"])
    return {"checked": len(rows), "changed": changed, "message": f"{changed} source(s) changed rights status"}


def confirm_channels(job: Job | None = None) -> dict:
    """Maintenance: ask the platforms about channel claims that are still unanswered: videos found while a platform
    could not be asked (offline, quota), and work queued before channels were confirmed. A video that is not
    confirmed loses its turn before any clipping; one already clipped is held back at scheduling and publishing."""
    settings = db.get_settings()
    now = time.time()
    rows = [r for r in db.select("sources", "channel_id != '' AND status NOT IN ('skipped', 'failed')")
            if verify.due(r, now)]
    asked = verify.ensure(rows, settings, now)
    changed = reapply([r for r in rows if r["status"] in REAPPLY], settings) if asked else 0
    return {"channels_checked": asked, "channels_changed": changed}


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
    # A found video's age counts from when YouTube last returned it (its signal's last_checked): Source Scout copies a
    # signal's stored numbers into the video's record for as long as the signal stays active, which refreshes
    # updated_at without asking YouTube again. So these run before the old signals they look at are deleted.
    stale = ("(updated_at < ? OR signal_id IN (SELECT id FROM trend_signals WHERE platform = 'youtube' AND "
             "last_checked < ?))")
    unused = db.execute(f"DELETE FROM sources WHERE platform = 'youtube' AND {stale} AND project_id = '' AND "
                        "status NOT IN ('queued', 'ingesting', 'analyzing')", (cutoff, cutoff))
    cleared = db.execute(f"UPDATE sources SET metrics = '{{}}', updated_at = ? WHERE platform = 'youtube' AND {stale} "
                         "AND metrics != '{}'", (now, cutoff, cutoff))
    old = [r["id"] for r in db.select("trend_signals", "platform = 'youtube' AND last_checked < ?", (cutoff,))]
    for sid in old:
        db.execute("DELETE FROM trend_history WHERE signal_id = ?", (sid,))
        db.execute("DELETE FROM trend_signals WHERE id = ?", (sid,))
    db.execute("DELETE FROM trend_history WHERE at < ? AND signal_id IN (SELECT id FROM trend_signals WHERE "
               "platform = 'youtube')", (cutoff,))
    perf = 0 if keep_own else db.execute("DELETE FROM performance WHERE platform = 'youtube' AND fetched_at < ?",
                                         (cutoff,))
    # the Brain's mirror of those readings (brain.ingest_platform) is YouTube API data too; numbers you typed in
    # yourself (owner_import) and tester answers are not, so they stay
    if not keep_own:
        perf += db.execute("DELETE FROM brain_observations WHERE platform = 'youtube' AND provenance = 'platform_api' "
                           "AND observed_at < ?", (cutoff,))
    db.execute("DELETE FROM api_cache WHERE fetched_at < ?", (cutoff,))
    return {"youtube_signals_deleted": len(old), "youtube_sources_deleted": unused,
            "youtube_sources_cleared": cleared, "youtube_snapshots_deleted": perf,
            "own_statistics": "kept (storage approved)" if keep_own else "30 days"}


MAINTENANCE_STEPS.append(youtube_retention)
MAINTENANCE_STEPS.append(confirm_channels)
