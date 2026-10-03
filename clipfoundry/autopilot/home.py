"""The simple Autopilot page: what Autopilot is doing, what it found, what is planned, and what needs you.

A plain-language view over the existing workers, sources, schedule and action items, so a first-time user never has
to learn what a source, feed, provider or worker is. The technical detail stays on the Advanced pages. The only new
state is when START AUTOPILOT was pressed and which accounts it started with.
"""
from __future__ import annotations

import time

from .. import db
from . import queue, rights, state

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
    "discovered": "Checking", "eligible": "Next in line", "needs_rights": "Needs your OK",
    "needs_file": "Needs the video file", "queued": "Up next for clipping", "ingesting": "Getting the video",
    "analyzing": "Finding the best moments", "weak": "No strong moments", "exhausted": "Done",
    "failed": "Could not be processed",
}
NOT_OPPORTUNITIES = ("skipped", "blocked")
UPCOMING = ("awaiting_approval", "approved", "publishing", "reconciling", "action_needed")
RIGHTS_NOTE = ("Only say yes if the creator gave you permission, for example through a clipping program you joined. "
               "Being public or trending does not make a video reusable.")
QUIET_KINDS = ("quota",)  # informational (resets by itself); shown under Advanced, never as "Needs you"


# ------------------------------------------------------------------ START AUTOPILOT
def connected(platforms: dict) -> list[str]:
    return [p for p in NAME if (platforms.get(p) or {}).get("connected") and not platforms[p].get("needs_reconnect")]


def start(platforms: dict) -> dict:
    """Turn Autopilot on with the accounts that are connected (one is enough). Everything else keeps its defaults;
    the scans themselves are started by the caller."""
    ready = connected(platforms)
    patch: dict = {"autopilot_enabled": True}
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
    """Is there anything to find content with? (a connected YouTube account, an API key, or a folder/feed)"""
    yt = platforms.get("youtube") or {}
    if (yt.get("connected") and not yt.get("needs_reconnect")) or settings.get("youtube_api_key"):
        return True
    return bool(db.scalar("SELECT COUNT(*) FROM source_feeds WHERE enabled = 1"))


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
def currently(settings: dict, workers_alive: bool) -> str:
    if state.paused():
        return "Stopped: all jobs are on hold"
    if not settings.get("autopilot_enabled"):
        return "Off"
    kinds = {j["kind"] for j in queue.jobs(("running",), limit=50)}
    for kind, words in DOING.items():
        if kind in kinds:
            return words
    busy = {r["status"] for r in db.select("sources", "status IN ('ingesting', 'analyzing')")}
    if busy:  # between two of a video's jobs nothing runs for a moment, but the video is still being worked on
        return DOING["analyze_source"] if "analyzing" in busy else DOING["hunt_source"]
    if not workers_alive:
        return "Starting"
    if any(j["wait_reason"] == "gpu" for j in queue.jobs(("waiting",), limit=50)):
        return "Waiting for the GPU"
    return "Looking for opportunities"


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
            items.append({"key": key, "type": "approve", "title": a["title"],
                          "detail": "YouTube and TikTok need your OK on every post. Approved posts go out at their "
                                    "time by themselves.", "link": "#/publish-center"})
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
    marks = ",".join("?" * len(UPCOMING))
    rows = db.select("scheduled_publications", f"status IN ({marks})", UPCOMING, "planned_at IS NULL, planned_at",
                     limit)
    return [{"id": r["id"], "platform": r["platform"], "title": r.get("title") or "", "planned_at": r.get("planned_at"),
             "status": r["status"]} for r in rows]


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
    return "No strong opportunities yet. ClipFoundry is still looking."


def view(settings: dict, platforms: dict, workers_alive: bool) -> dict:
    """Everything the simple Autopilot page shows."""
    found = opportunities()
    discover = can_discover(settings, platforms)
    return {"setup": {"started": started_before(), "connected": connected(platforms), "can_discover": discover},
            "currently": currently(settings, workers_alive), "needs_you": needs_you(settings, platforms),
            "opportunities": found, "upcoming": upcoming(), "empty": empty_message(settings, discover, found)}
