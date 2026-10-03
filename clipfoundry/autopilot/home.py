"""The simple Autopilot page: what Autopilot is doing, what it found, what is planned, and what needs you.

A plain-language view over the existing workers, sources, schedule and action items, so a first-time user never has
to learn what a source, feed, provider or worker is. The technical detail stays on the Advanced pages. The only new
state is when START AUTOPILOT was pressed and which accounts it started with.

What Autopilot skipped (nothing covers the video, no allowed way to get its file, too short, a re-upload, weak) is
not a problem that needs you: it is listed in the activity log, with the reason, for when you want to look.
"""
from __future__ import annotations

import time
from pathlib import Path

from .. import awake, db
from . import autopublish, myvideos, queue, rights, state

NAME = {"youtube": "YouTube", "tiktok": "TikTok"}

# What a running job means, for someone who does not know the workers. Checked in this order when several run.
DOING = {
    "publish": "Publishing a post",
    "live_capture": "Recording a live stream",
    "analyze_source": "Finding the best moments",
    "hunt_source": "Getting a video ready",
    "post_live": "Finishing a live stream",
    "quality_check": "Checking a finished clip",
    "regenerate_clip": "Making a fresh copy of a clip",
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
PC_NOTE = ("Keep this PC on and leave the black ClipFoundry window open: Autopilot only works while ClipFoundry runs. "
           "{sleep} Posts go out between {start} and {end}. A YouTube post that is already uploaded still goes out if "
           "the PC is off; TikTok posts need the PC on.")
SLEEP = {  # by the real state of the keep-awake request (awake.KeepAwake.status), never by the setting alone
    "on": "ClipFoundry is keeping this PC from going to sleep (a laptop still sleeps if you close its lid).",
    "pending": "ClipFoundry is asking Windows to keep this PC from going to sleep.",
    "failed": "Windows did not let ClipFoundry keep this PC awake, so turn off sleep yourself (see Needs you).",
    "off": "While Autopilot is on, ClipFoundry keeps this PC from going to sleep.",
    "setting_off": ("Keep the PC awake is off in Settings, so turn off sleep in the PC's power settings, or Autopilot "
                    "stops when the PC sleeps."),
    "unsupported": "Turn off sleep in the PC's power settings, or Autopilot stops when the PC sleeps.",
}
SLEEP_FIX = ("Open Windows Settings, then System, then Power & sleep (Windows 10) or Power & battery (Windows 11), "
             "and set the sleep time for \"When plugged in\" to Never. Keep the PC plugged in and a laptop's lid open. "
             "ClipFoundry tries again every minute; this message goes away once it works.")
USABLE = ("eligible", "queued", "ingesting", "analyzing")  # a found video Autopilot may use and has not finished
UPCOMING = ("awaiting_approval", "approved", "publishing", "reconciling", "action_needed")
RIGHTS_NOTE = ("Only say yes if the creator gave you permission, for example through a clipping program you joined. "
               "Being public or trending does not make a video reusable.")
QUIET_KINDS = ("quota", "job", "retry", "provider", "source")  # normal failures are handled in the background
BOOT = time.time()  # when this app started: its background work needs a moment before it answers
STOPPED_AFTER = 60.0  # seconds without an answer from the background work before the page says it stopped
# The online searches by their key in state "providers" (scout.trend_scan), as the main page names them. A folder's
# key is "feed:<id>" and is named by the folder.
SEARCH_NAMES = {"youtube": "YouTube search", "web_search": "Web search", "library": "The free video library"}
SEARCH_PROBLEMS = {  # a search that did not work last time, by its status: what happened and what to do
    "error": ("It did not work last time.", "It tries again at the next search."),
    "quota": ("YouTube's daily limit for searches is used up.",
              "YouTube searches start again after midnight Pacific time. Your videos folder is still checked."),
    "budget": ("Web search reached this month's limit.",
               "It starts again next month. You can change the limit in Settings → Advanced."),
}


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
    myvideos.ensure()  # the one place to put your own videos, watched from now on
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
def workers_stopped(settings: dict, workers_alive: bool) -> bool:
    """Autopilot is on, but its background work has not answered for a minute, and it is not just starting up (the
    app and Autopilot were both started more than a minute ago). The app restarts a crashed worker process by itself,
    so this lasting means it could not."""
    if workers_alive or state.paused() or not settings.get("autopilot_enabled"):
        return False
    started = float(state.get("setup:started", 0) or 0)
    beat = float((state.get("host_heartbeat") or {}).get("at") or 0)
    return bool(started or beat) and time.time() - max(started, beat, BOOT) > STOPPED_AFTER


def currently(settings: dict, workers_alive: bool, discovery: dict | None = None) -> str:
    if state.paused():
        return "Stopped: all jobs are on hold"
    if not settings.get("autopilot_enabled"):
        return "Off"
    if not workers_alive:
        return "Background work has stopped" if workers_stopped(settings, workers_alive) else "Starting"
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
    if not any(counts.get(s) for s in USABLE):  # say why nothing is being clipped, not just "looking"
        # "yet" is only true while no found video was ever clipped; afterwards skipped finds are normal
        used = any(counts.get(s) for s in ("analyzed", "weak", "exhausted"))
        if counts.get("needs_file") and not used:
            return "No usable video files yet"
        if (counts.get("needs_rights") or counts.get("blocked")) and not used:
            return "No covered videos found yet"
        if discovery["problems"]:
            return "Some searches did not work"
    return "Waiting for the next search" if discovery["last_scan"] else "Looking for opportunities"


def discovery_status() -> dict:
    """Enough evidence on the main page to tell an empty search from missing files, videos nobody covers and a search
    that did not work. Problems are in plain words; the technical detail stays under Advanced → System."""
    last = state.get("trend:last_scan") or {}
    with db.connect() as conn:
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM sources GROUP BY status")}
    problems = []
    for key, p in (state.get("providers") or {}).items():
        status = p.get("status")
        if status not in SEARCH_PROBLEMS:
            continue
        detail, fix = SEARCH_PROBLEMS[status]
        if status == "error":
            detail, fix = p.get("problem") or p.get("detail") or detail, p.get("fix") or fix
        problems.append({"name": SEARCH_NAMES.get(key) or f"Checking “{p.get('name') or 'a folder'}”",
                         "detail": detail, "fix": fix})
    return {"last_scan": last.get("at"), "next_scan": state.get("next:trend_scan"),
            "found": int(last.get("signals") or 0), "counts": counts, "problems": problems}


def _source_view(src: dict) -> dict:
    return {"id": src["id"], "title": src.get("title") or "", "channel": src.get("channel_title") or "",
            "url": src.get("url") or "", "platform": src.get("platform") or "", "kind": src.get("kind") or "",
            "score": round(src["source_score"]) if src.get("source_score") is not None else None}


def _was_connected(platform: str) -> bool:
    return platform in (state.get("setup:platforms") or []) or bool(
        db.scalar("SELECT COUNT(*) FROM publications WHERE platform = ?", (platform,)))


def needs_you(settings: dict, platforms: dict, workers_alive: bool = True) -> list[dict]:
    """Only what really needs you, in plain words, most urgent first."""
    items: list[dict] = []
    if workers_stopped(settings, workers_alive):
        items.append({"key": "workers_stopped", "type": "stopped", "title": "Autopilot's background work has stopped",
                      "detail": "ClipFoundry is open, but the part that finds, clips and posts videos is not running, "
                                "so nothing happens.",
                      "fix": "Close the black ClipFoundry window, then start ClipFoundry again with start.bat. If "
                             "this keeps happening, see Autopilot → Advanced → System.",
                      "link": "#/autopilot/system"})
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
    accounts = {i["platform"] for i in items if i["type"] == "account"}
    for a in state.open_actions():
        kind, key = a["kind"], a["key"]
        if kind in QUIET_KINDS or (key.startswith("connect:") and key.split(":", 1)[1] in accounts):
            continue
        if kind == "workers" and workers_alive:
            continue  # the automatic in-app fallback already recovered this problem
        if kind == "rights":
            src = db.fetch("sources", a["ref_id"]) if a["ref_id"] else None
            if not settings.get("rights_ask_per_video") or not src or src["status"] != "needs_rights" \
                    or src.get("user_added"):
                continue
            items.append({"key": key, "type": "rights", "title": "ClipFoundry found a strong trending video",
                          "question": "Can you use this content?", "detail": RIGHTS_NOTE, "source": _source_view(src)})
        elif kind == "source_file":
            src = db.fetch("sources", a["ref_id"]) if a["ref_id"] else None
            if not src or src["status"] != "needs_file" or not src.get("user_added"):
                continue
            hosted = rights.is_platform_url(src.get("url") or "")
            items.append({"key": key, "type": "file", "title": f"Add the video file for “{src['title'][:80]}”",
                          "detail": ("ClipFoundry does not download videos from YouTube or other platforms by itself "
                                     "(their terms). Choose the original file on this computer; for your own "
                                     "videos, YouTube Studio → Download gives you one.") if hosted else a["detail"],
                          "source": _source_view(src)})
        elif kind == "approve":
            items.append({"key": key, "type": "approve", "title": a["title"], "detail": a["detail"],
                          "link": "#/posts/review"})
        elif kind == "publish":
            items.append({"key": key, "type": "publish", "title": a["title"], "detail": a["detail"],
                          "fix": a["fix"], "link": f"#/post/{a['ref_id']}" if a.get("ref_type") == "scheduled"
                          and a.get("ref_id") else "#/posts/scheduled"})
        elif kind == "gpu":
            items.append({"key": key, "type": "gpu", "title": "GPU transcription is not working",
                          "detail": a["detail"], "fix": a["fix"], "link": "#/settings/advanced"})
        else:
            items.append({"key": key, "type": "other", "title": a["title"], "detail": a["detail"], "fix": a["fix"],
                          "link": "#/autopilot/system"})
    for extra in (needs_sleep_fix(settings),):
        if extra:
            items.append(extra)
    order = {"stopped": 0, "account": 0, "sleep": 1, "gpu": 1, "rights": 2, "file": 3, "approve": 4, "publish": 5,
             "videos": 6, "other": 7}
    return sorted(items, key=lambda i: order.get(i["type"], 9))


def needs_videos(settings: dict) -> dict | None:
    """Autopilot is on and has looked, but has nothing it may clip: nothing it may use is waiting or being worked on,
    and it made no clip in the last day. Videos from other channels are skipped (the activity log says why), so
    this is said once, here, with the one thing that helps: your own videos in your videos folder."""
    if not state.enabled(settings) or not state.get("trend:last_scan"):
        return None
    marks = ",".join("?" * len(USABLE))
    if db.scalar(f"SELECT COUNT(*) FROM sources WHERE status IN ({marks})", USABLE):
        return None
    made = db.scalar("SELECT COUNT(*) FROM clips WHERE created_at >= ? AND project_id IN (SELECT id FROM projects "
                     "WHERE origin IN ('autopilot', 'live'))", (time.time() - 86400,))
    if made:
        return None
    folder = myvideos.view()
    if folder["watching"] and myvideos.unseen():
        return None  # a video you just added: the next folder check (every few minutes) picks it up
    if folder["videos"] and folder["watching"]:
        title = "Autopilot has used all your videos"
        detail = "Put new videos in your videos folder to get more clips."
    else:
        title = "Autopilot needs videos to work with"
        since = time.time() - 86400
        no_file = int(db.scalar("SELECT COUNT(*) FROM sources WHERE status = 'needs_file' AND updated_at > ?",
                                (since,)) or 0)
        others = int(db.scalar("SELECT COUNT(*) FROM sources WHERE status IN ('needs_rights', 'blocked') AND "
                               "updated_at > ?", (since,)) or 0)
        found = ""
        if no_file:  # e.g. your own YouTube videos: covered, but YouTube does not let apps download them
            found += (f"{no_file} video{'s' if no_file != 1 else ''} it may use {'have' if no_file != 1 else 'has'} "
                      "no file it is allowed to download (YouTube doesn't let apps download videos, even your own). ")
        if others:
            found += (f"The {others} {'other ' if no_file else ''}video{'s' if others != 1 else ''} it found online "
                      f"belong{'s' if others == 1 else ''} to other people, so it skipped "
                      f"{'them' if others != 1 else 'it'}. ")
        detail = (f"{found}Put videos you made in your videos folder, and Autopilot turns them into clips by itself.")
    return {"key": "videos", "type": "videos", "title": title, "detail": detail, "folder": folder}


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
        made = int(s.get("clips_selected") or 0)
        used = s["status"] in ("queued", "ingesting", "analyzing", "analyzed", "exhausted") or made > 0
        stage = STAGE.get(s["status"], "Skipped") if s["status"] != "skipped" else "Skipped"
        if made and s["status"] in ("analyzed", "weak", "exhausted"):
            stage = f"{made} clip{'s' if made != 1 else ''} made"  # a weak video still gave you these clips
        out.append({**_source_view(s), "status": s["status"], "used": used, "stage": stage,
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
        if settings.get("autopilot_public_videos"):
            return ("No accessible strong videos yet. ClipFoundry is still looking. "
                    "Activity shows why each video was skipped. You can also paste a public video link.")
        return (f"Nothing it may use yet: the {skipped} video{'s' if skipped != 1 else ''} it found belong to other "
                "people (not covered by an agreement or license) or cannot be downloaded. Put your own videos in your "
                "videos folder. Activity shows why each was skipped.")
    return "No strong opportunities yet. ClipFoundry is still looking."


def auto_publish(settings: dict) -> dict:
    """Per platform: publishes by itself, or waits for your OK (and why)."""
    v = autopublish.view(settings)
    return {p: {"enabled": v[p]["enabled"], "supported": v[p]["supported"], "note": v[p]["note"],
                "since": autopublish.since(v[p]["consent"], settings) if v[p]["consent"] else "",
                "settings": (v[p]["consent"] or {}).get("settings") or {}} for p in NAME}


def pc_note(settings: dict) -> str:
    def hour(h: int) -> str:
        return {0: "midnight", 12: "noon", 24: "midnight"}.get(h, f"{h % 12} {'AM' if h < 12 else 'PM'}")

    now = keep_awake(settings)
    if now == "off" and not settings.get("autopilot_keep_awake", True):
        now = "setting_off"
    start, end = settings.get("autopilot_active_start"), settings.get("autopilot_active_end")
    return PC_NOTE.format(sleep=SLEEP[now], start=hour(int(9 if start is None else start)),
                          end=hour(int(21 if end is None else end)))


def keep_awake(settings: dict) -> str:
    """Whether the PC is really kept awake now: on, pending, failed, off or unsupported (awake.KeepAwake.status)."""
    return awake.keeper.status(state.enabled(settings) and bool(settings.get("autopilot_keep_awake", True)))


def needs_sleep_fix(settings: dict) -> dict | None:
    """Windows refused to keep the PC awake while Autopilot is on: say so, with what to do instead. Computed from
    the live state, so it goes away by itself when a retry works or Autopilot or the setting is turned off."""
    if keep_awake(settings) != "failed":
        return None
    return {"key": "keep_awake", "type": "sleep", "title": "Your PC may go to sleep and stop Autopilot",
            "detail": "ClipFoundry asked Windows to keep this PC awake, but Windows said no. While the PC sleeps, "
                      "Autopilot finds, clips and posts nothing.",
            "fix": SLEEP_FIX}


def next_look(settings: dict) -> float | None:
    """When Autopilot next looks for new videos online (it checks your videos folder every few minutes)."""
    if not state.enabled(settings):
        return None
    due = float(state.get("next:trend_scan", 0) or 0)
    if due <= time.time():  # not planned yet (a look you started): the usual interval after the last look
        last = float((state.get("trend:last_scan") or {}).get("at") or 0)
        due = last + 60.0 * float(settings.get("trend_poll_minutes") or 180) if last else 0.0
    return due if due > time.time() else None


def _video_of(ref_type: str, ref_id: str) -> dict | None:
    """The video a job works on (a found video, a clip or a post of a clip), as the page shows it."""
    title, project_id = "", ""
    if ref_type == "source":
        src = db.fetch("sources", ref_id) or {}
        title, project_id = src.get("title") or "", src.get("project_id") or ""
    elif ref_type in ("clip", "scheduled"):
        clip_id = ref_id if ref_type == "clip" else (db.fetch("scheduled_publications", ref_id) or {}).get("clip_id")
        clip = db.get_clip(clip_id or "") or {}
        title, project_id = clip.get("title") or "", clip.get("project_id") or ""
    if not (title or project_id):
        return None
    project = db.get_project(project_id) if project_id else None
    source = (project or {}).get("source_path")
    return {"title": title or (project or {}).get("name") or "", "project_id": project_id if project else "",
            "has_thumbnail": bool(source and (Path(source).parent / "thumb.jpg").exists())}


def working(settings: dict) -> dict | None:
    """What Autopilot is busy with right now and which video it belongs to, for the page's "Working on". The
    progress is only what the job itself reports (0 to 1), or None; there is never a time estimate."""
    if state.paused() or not settings.get("autopilot_enabled"):
        return None
    order = list(DOING)
    running = sorted(queue.jobs(("running",), limit=50),
                     key=lambda j: order.index(j["kind"]) if j["kind"] in order else len(order))
    for job in running:
        video = _video_of(job.get("ref_type") or "", job.get("ref_id") or "")
        if video:
            progress = float(job.get("progress") or 0)
            return {**video, "step": DOING.get(job["kind"], "Working"),
                    "progress": round(min(1.0, progress), 3) if progress > 0 else None,
                    "message": job.get("message") or DOING.get(job["kind"], "Working")}
    return None


def post_counts() -> dict:
    """The sidebar's counts, the same as the Posts tabs: posts waiting for your OK (including approved posts whose
    video changed since, so the OK no longer covers it), and posts with a problem (an upload that was not confirmed,
    one to finish in the TikTok app, a failed or blocked one)."""
    from .scheduler import approval_valid

    def n(statuses: tuple[str, ...]) -> int:
        marks = ",".join("?" * len(statuses))
        return int(db.scalar(f"SELECT COUNT(*) FROM scheduled_publications WHERE status IN ({marks})", statuses) or 0)

    # quick: compared with the stored hash, as the Posts list does (display only; publishing hashes the file)
    outdated = sum(1 for i in db.select("scheduled_publications", "status = 'approved'")
                   if not approval_valid(i, quick=True))
    from . import gate

    ready = 0
    for clip in db.select("clips", "status = 'ready' AND id NOT IN (SELECT clip_id FROM scheduled_publications "
                                   "WHERE status IN ('awaiting_approval', 'approved', 'publishing', 'reconciling', "
                                   "'published'))"):
        rep = gate.report_for(clip)
        if rep and rep["status"] == "passed":
            ready += 1
    return {"review": n(("awaiting_approval",)) + outdated,
            "fix": n(("reconciling", "action_needed", "failed", "blocked")), "ready": ready,
            "scheduled": n(("approved", "publishing")) - outdated}


def next_step(settings: dict) -> str:
    """The next useful activity, without internal job names or time estimates."""
    if state.paused():
        return "Continue when you start Autopilot again"
    if not settings.get("autopilot_enabled"):
        return "Start Autopilot to continue"
    pending = queue.jobs(("queued", "retrying", "waiting"), limit=100)
    due = [j for j in pending if float(j.get("run_after") or 0) <= time.time()]
    if due:
        job = max(due, key=lambda j: (j.get("priority") or 0, -(j.get("created_at") or 0)))
        return DOING.get(job["kind"], "Continue preparing videos")
    if any(j["kind"] == "live_capture" for j in pending):
        return "Listen for more good moments"
    return "Check for more trending videos"


def view(settings: dict, platforms: dict, workers_alive: bool) -> dict:
    """Everything the simple Autopilot page shows."""
    found = opportunities()
    discover = can_discover(settings, platforms)
    discovery = discovery_status()
    return {"setup": {"started": started_before(), "connected": connected(platforms), "can_discover": discover,
                      "topics": settings.get("trend_topics") or "", "mode": settings.get("setup_mode") or ""},
            "currently": currently(settings, workers_alive, discovery), "next_look": next_look(settings),
            "next": next_step(settings),
            "discovery": discovery, "working": working(settings),
            "needs_you": needs_you(settings, platforms, workers_alive),
            "opportunities": found, "upcoming": upcoming(), "empty": empty_message(settings, discover, found),
            "auto_publish": auto_publish(settings), "pc_note": pc_note(settings), "keep_awake": keep_awake(settings),
            "skipped_today": skipped_count(), "my_videos": myvideos.view(), "posts": post_counts()}


def skipped_count() -> int:
    """Videos looked at and skipped in the last 24 hours (the activity log explains each)."""
    return int(db.scalar("SELECT COUNT(*) FROM sources WHERE status IN ('skipped', 'needs_rights', 'needs_file', "
                         "'blocked') AND updated_at > ?", (time.time() - 86400,)) or 0)
