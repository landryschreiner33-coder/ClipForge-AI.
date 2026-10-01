"""The simple Autopilot page: what Autopilot is doing, what it found, what is planned, and what needs you.

A plain-language view over the existing workers, sources, schedule and action items, so a first-time user never has
to learn what a source, feed, provider or worker is. The technical detail stays on the Advanced pages. The only new
state is when START AUTOPILOT was pressed and which accounts it started with.

What Autopilot skipped (nothing covers the video, no allowed way to get its file, too short, a re-upload, weak) is
not a problem that needs you: it is listed in the activity log, with the reason, for when you want to look.
"""
from __future__ import annotations

import time

from .. import db
from . import autopublish, queue, rights, state

NAME = {"youtube": "YouTube", "tiktok": "TikTok"}

# What a running job means, for someone who does not know the workers. Checked in this order when several run.
DOING = {
    "publish": "Publishing a post",
    "live_capture": "Recording a live stream",
    "analyze_source": "Finding the best moments",
    "hunt_source": "Getting a video ready",
    "post_live": "Finishing a live stream",
    "quality_check": "Checking a finished clip",
    "package_clip": "Writing titles and captions",
    "trend_scan": "Finding trending videos",
    "source_scout": "Choosing the best videos",
    "feed_scan": "Checking your folders",
    "live_watch": "Watching for live streams",
    "rights_check": "Checking permissions",
    "schedule_tick": "Planning posting times",
    "learn": "Learning from your results",
    "maintenance": "Tidying up",
    "selftest": "Checking itself",
}

# Where a found video stands, in plain words (by source status)
STAGE = {
    "discovered": "Checking", "eligible": "Next in line", "needs_rights": "Skipped: not covered",
    "needs_file": "Skipped: no allowed way to get the file", "queued": "Up next for clipping",
    "ingesting": "Getting the video", "analyzing": "Finding the best moments", "weak": "No strong moments",
    "exhausted": "Done", "failed": "Could not be processed",
}
NOT_OPPORTUNITIES = ("skipped", "blocked", "needs_rights", "needs_file")  # listed in the activity log instead
ACTIVITY = ("skipped", "blocked", "needs_rights", "needs_file", "weak", "failed", "queued", "ingesting", "analyzing",
            "analyzed", "exhausted")
PC_NOTE = ("Keep this PC on and awake: ClipFoundry finds videos and makes clips only while it runs. YouTube posts that "
           "were already uploaded go out at their time even if the PC is off (YouTube publishes them); TikTok posts "
           "need the PC on at their time.")
UPCOMING = ("awaiting_approval", "approved", "publishing", "reconciling", "action_needed")
RIGHTS_NOTE = ("Only say yes if the creator gave you permission, for example through a clipping program you joined. "
               "Being public or trending does not make a video reusable.")
QUIET_KINDS = ("quota",)  # informational (resets by itself); shown under Advanced, never as "Needs you"


# ------------------------------------------------------------------ START AUTOPILOT
def connected(platforms: dict) -> list[str]:
    return [p for p in NAME if (platforms.get(p) or {}).get("connected") and not platforms[p].get("needs_reconnect")]


def start(platforms: dict, topics: str | None = None) -> dict:
    """Turn Autopilot on with the accounts that are connected (one is enough) and the topics you chose (the
    suggestion stays if you did not change it). Everything else keeps its defaults; the scans themselves are started
    by the caller."""
    ready = connected(platforms)
    patch: dict = {"autopilot_enabled": True}
    if topics is not None and topics.strip():
        patch["trend_topics"] = ", ".join(t.strip() for t in topics.split(",") if t.strip())[:1000]
    if ready:  # post only where you are signed in; with none yet, a platform is used once you connect it
        patch.update({f"autopilot_{p}": p in ready for p in NAME})
    db.save_settings(patch)
    state.put("setup:started", time.time())
    state.put("setup:platforms", ready)
    names = " and ".join(NAME[p] for p in ready) or "no account connected yet"
    state.event("autopilot_on", f"Autopilot started ({names})")
    return {"platforms": ready}


def started_before() -> bool:
    return bool(state.get("setup:started")) or bool(state.events(1, kind="autopilot_on"))


def can_discover(settings: dict, platforms: dict) -> bool:
    """Include the free library and agreement folders, which do not require a connected account."""
    from . import scout

    if settings.get("library_discovery", True) or settings.get("tavily_api_key"):
        return True
    yt = platforms.get("youtube") or {}
    if (yt.get("connected") and not yt.get("needs_reconnect")) or settings.get("youtube_api_key"):
        return True
    return bool(scout.discovery_feeds(settings))


# ------------------------------------------------------------------ the answer to a rights question
def answer_rights(source_id: str, allowed: bool) -> dict:
    """Your one-click answer, recorded as a rights decision for this source only (with its date as the basis).
    Yes means the creator gave you permission (Allowlisted); No means it is never used (Blocked)."""
    day = time.strftime("%Y-%m-%d")
    if allowed:
        return rights.confirm(source_id, rights.ALLOWLISTED,
                              f"You said you have permission to use this video (Autopilot question, {day})")
    return rights.confirm(source_id, rights.BLOCKED, f"You said you do not have permission to use it ({day})")


# ------------------------------------------------------------------ what the page shows
def currently(settings: dict, workers_alive: bool, discovery: dict | None = None) -> str:
    if state.paused():
        return "Stopped: all jobs are on hold"
    if not settings.get("autopilot_enabled"):
        return "Off"
    if not workers_alive:
        started = float(state.get("setup:started", 0) or 0)
        beat = float((state.get("host_heartbeat") or {}).get("at") or 0)
        return "Background work has stopped" if (started or beat) and time.time() - max(started, beat) > 60 else "Starting"
    kinds = {j["kind"] for j in queue.jobs(("running",), limit=50)}
    for kind, words in DOING.items():
        if kind in kinds:
            return words
    busy = {r["status"] for r in db.select("sources", "status IN ('ingesting', 'analyzing')")}
    if busy:  # between two of a video's jobs nothing runs for a moment, but the video is still being worked on
        return DOING["analyze_source"] if "analyzing" in busy else DOING["hunt_source"]
    if any(j["wait_reason"] in ("gpu", "gpu_failed") for j in queue.jobs(("waiting",), limit=50)):
        return "Waiting for the GPU"
    discovery = discovery if discovery is not None else discovery_status()
    counts = discovery["counts"]
    if not any(counts.get(s) for s in ("eligible", "queued", "ingesting", "analyzing")):
        if counts.get("needs_file"):
            return "No usable video files yet"
        if counts.get("needs_rights") or counts.get("blocked"):
            return "No covered videos found yet"
        if discovery["problems"]:
            return "Some searches are unavailable"
    return "Waiting for the next search" if discovery["last_scan"] else "Looking for opportunities"


def discovery_status() -> dict:
    """Enough evidence on the main page to distinguish an empty search, missing files and broken discovery."""
    last = state.get("trend:last_scan") or {}
    with db.connect() as conn:
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM sources GROUP BY status")}
    problems = [{"name": p.get("name") or "Search", "detail": p.get("detail") or "Search is unavailable",
                 "fix": p.get("fix") or "It will try again on the next search."}
                for p in (state.get("providers") or {}).values() if p.get("status") in ("error", "quota", "budget")]
    return {"last_scan": last.get("at"), "next_scan": state.get("next:trend_scan"),
            "found": int(last.get("signals") or 0), "counts": counts, "problems": problems}


def _source_view(src: dict) -> dict:
    return {"id": src["id"], "title": src.get("title") or "", "channel": src.get("channel_title") or "",
            "url": src.get("url") or "", "platform": src.get("platform") or "", "kind": src.get("kind") or "",
            "score": round(src["source_score"]) if src.get("source_score") is not None else None}


def _was_connected(platform: str) -> bool:
    return platform in (state.get("setup:platforms") or []) or bool(
        db.scalar("SELECT COUNT(*) FROM publications WHERE platform = ?", (platform,)))


def needs_you(settings: dict, platforms: dict) -> list[dict]:
    """Only what really needs you, in plain words, most urgent first."""
    items: list[dict] = []
    for p, name in NAME.items():
        acc = platforms.get(p) or {}
        if not settings.get(f"autopilot_{p}"):
            continue
        planned = int(db.scalar("SELECT COUNT(*) FROM scheduled_publications WHERE platform = ? AND status IN "
                                "('awaiting_approval', 'approved', 'publishing', 'action_needed')", (p,)) or 0)
        if acc.get("connected") and acc.get("needs_reconnect"):
            items.append({"key": f"account:{p}", "type": "account", "platform": p, "title": f"Reconnect {name}",
                          "detail": f"{name} stopped accepting ClipFoundry's sign-in, so Autopilot cannot post there. "
                                    "Sign in again to continue."})
        elif not acc.get("connected") and planned:
            verb = "Reconnect" if _was_connected(p) else "Connect"
            items.append({"key": f"account:{p}", "type": "account", "platform": p, "title": f"{verb} {name}",
                          "detail": f"{name} is not connected, so {planned} planned post{'s' if planned != 1 else ''} "
                                    f"cannot go out."})
    accounts = {i["platform"] for i in items}
    for a in state.open_actions():
        kind, key = a["kind"], a["key"]
        if kind in QUIET_KINDS or (key.startswith("connect:") and key.split(":", 1)[1] in accounts):
            continue
        if kind == "rights":
            src = db.fetch("sources", a["ref_id"]) if a["ref_id"] else None
            if not src or src["status"] != "needs_rights":
                continue
            items.append({"key": key, "type": "rights", "title": "ClipFoundry found a strong trending video",
                          "question": "Can you use this content?", "detail": RIGHTS_NOTE, "source": _source_view(src)})
        elif kind == "source_file":
            src = db.fetch("sources", a["ref_id"]) if a["ref_id"] else None
            if not src or src["status"] != "needs_file":
                continue
            hosted = rights.is_platform_url(src.get("url") or "")
            items.append({"key": key, "type": "file", "title": f"Add the video file for “{src['title'][:80]}”",
                          "detail": ("ClipFoundry does not download videos from YouTube or other platforms by itself "
                                     "(their terms). Choose the original file on this computer; for your own "
                                     "videos, YouTube Studio → Download gives you one.") if hosted else a["detail"],
                          "source": _source_view(src)})
        elif kind == "approve":
            items.append({"key": key, "type": "approve", "title": a["title"], "detail": a["detail"],
                          "link": "#/publish-center"})
        elif kind == "publish":
            items.append({"key": key, "type": "publish", "title": a["title"], "detail": a["detail"],
                          "fix": a["fix"], "link": "#/publish-center/problems"})
        elif kind == "gpu":
            items.append({"key": key, "type": "gpu", "title": "GPU transcription is not working",
                          "detail": a["detail"], "fix": a["fix"], "link": "#/settings/advanced"})
        else:
            items.append({"key": key, "type": "other", "title": a["title"], "detail": a["detail"], "fix": a["fix"],
                          "link": "#/autopilot/system"})
    order = {"account": 0, "gpu": 1, "rights": 2, "file": 3, "approve": 4, "publish": 5, "other": 6}
    return sorted(items, key=lambda i: order.get(i["type"], 9))


def opportunities(limit: int = 5) -> list[dict]:
    """The strongest things discovery found, with where each one stands."""
    sigs = db.select("trend_signals", "status = 'active'", (), "score DESC, last_checked DESC", 60)
    by_signal: dict[str, dict] = {}
    if sigs:
        marks = ",".join("?" * len(sigs))
        for src in db.select("sources", f"signal_id IN ({marks})", [s["id"] for s in sigs]):
            by_signal.setdefault(src["signal_id"], src)
    out = []
    for s in sigs:
        src = by_signal.get(s["id"])
        if src and src["status"] in NOT_OPPORTUNITIES:
            continue
        made = int((src or {}).get("clips_selected") or 0)
        if src and src["status"] in ("analyzed", "weak", "exhausted") and made:
            stage = f"{made} clip{'s' if made != 1 else ''} made"
        else:
            stage = STAGE.get(src["status"], "Checking") if src else "Found"
        out.append({"id": s["id"], "title": s.get("title") or "", "url": s.get("url") or "",
                    "channel": s.get("channel_title") or "", "kind": s.get("kind") or "video",
                    "topic": s.get("topic") or s.get("category") or "", "score": round(s.get("score") or 0),
                    "stage": stage, "source_id": src["id"] if src else ""})
        if len(out) >= limit:
            break
    return out


def upcoming(limit: int = 5) -> list[dict]:
    """The next posts, including ones already uploaded that the platform will publish at their time."""
    marks = ",".join("?" * len(UPCOMING))
    rows = db.select("scheduled_publications", f"status IN ({marks}) OR (status = 'published' AND planned_at > ?)",
                     (*UPCOMING, time.time()), "planned_at IS NULL, planned_at", limit)
    return [{"id": r["id"], "platform": r["platform"], "title": r.get("title") or "", "planned_at": r.get("planned_at"),
             "status": r["status"], "auto": (r.get("approval") or {}).get("by") == "automatic",
             "on_platform": r["status"] == "published"} for r in rows]


def _why_not(src: dict) -> str:
    """Why a found video was not (or not yet) used, in plain words."""
    st = src["status"]
    if st == "needs_rights":
        return "Not covered: " + (src.get("rights_basis") or "no agreement, license or ownership")
    if st == "needs_file":
        return src.get("status_note") or "No allowed way to get the video file"
    if st == "blocked":
        return "Blocked: " + (src.get("rights_basis") or "by your rule")
    return src.get("status_note") or STAGE.get(st, st)


def activity(limit: int = 40) -> list[dict]:
    """The activity log: what Autopilot did with each video it found, newest first, with the reason when it skipped
    one. Optional reading; nothing here waits for you."""
    marks = ",".join("?" * len(ACTIVITY))
    rows = db.select("sources", f"status IN ({marks})", ACTIVITY, "updated_at DESC", limit)
    out = []
    for s in rows:
        used = s["status"] in ("queued", "ingesting", "analyzing", "analyzed", "exhausted")
        out.append({**_source_view(s), "status": s["status"], "used": used,
                    "stage": STAGE.get(s["status"], "Skipped") if s["status"] != "skipped" else "Skipped",
                    "why": _why_not(s), "rights": rights.LABELS.get(s.get("rights_status") or "", ""),
                    "access": (s.get("access") or {}).get("label", ""), "at": s.get("updated_at"),
                    "can_add_file": s["status"] == "needs_file" and bool(rights.evaluate(s)["auto_allowed"])})
    return out


def empty_message(settings: dict, discover: bool, found: list[dict]) -> str:
    """What to say when there is nothing to show yet (never "no sources configured")."""
    if found:
        return ""
    if not discover:
        return "Connect YouTube to start finding content."
    if not settings.get("autopilot_enabled"):
        return "Turn on Autopilot to start finding opportunities."
    if not state.get("trend:last_scan"):
        return "Autopilot is looking for opportunities."
    skipped = skipped_count()
    if skipped:
        return (f"No usable videos yet: the {skipped} found so far are not covered by an agreement or license, or their "
                "file cannot be obtained. ClipFoundry is still looking (Activity shows why each was skipped).")
    return "No strong opportunities yet. ClipFoundry is still looking."


def auto_publish(settings: dict) -> dict:
    """Per platform: publishes by itself, or waits for your OK (and why)."""
    v = autopublish.view(settings)
    return {p: {"enabled": v[p]["enabled"], "supported": v[p]["supported"], "note": v[p]["note"],
                "since": autopublish.since(v[p]["consent"], settings) if v[p]["consent"] else "",
                "settings": (v[p]["consent"] or {}).get("settings") or {}} for p in NAME}


def view(settings: dict, platforms: dict, workers_alive: bool) -> dict:
    """Everything the simple Autopilot page shows."""
    found = opportunities()
    discover = can_discover(settings, platforms)
    discovery = discovery_status()
    return {"setup": {"started": started_before(), "connected": connected(platforms), "can_discover": discover,
                      "topics": settings.get("trend_topics") or ""},
            "currently": currently(settings, workers_alive, discovery), "needs_you": needs_you(settings, platforms),
            "discovery": discovery,
            "opportunities": found, "upcoming": upcoming(), "empty": empty_message(settings, discover, found),
            "auto_publish": auto_publish(settings), "pc_note": PC_NOTE,
            "skipped_today": skipped_count()}


def skipped_count() -> int:
    """Videos looked at and skipped in the last 24 hours (the activity log explains each)."""
    return int(db.scalar("SELECT COUNT(*) FROM sources WHERE status IN ('skipped', 'needs_rights', 'needs_file', "
                         "'blocked') AND updated_at > ?", (time.time() - 86400,)) or 0)
