"""ClipForge AI's commands: what the owner can ask it to do with posts, work, clips, missions and settings.

Every command runs the very function the app's own button runs (the route functions in api.py and
autopilot/routes.py), so the same checks, time zone, gap between posts and approval rules apply, and an action the
app refuses is refused here in the app's own words. Changes wait for the owner's OK on a card that says exactly what
will happen (tools.WAITS); a card for several posts lists each one (a batch change is approved once, as a whole).
ClipForge AI never publishes and never approves a post: a post goes out only through its approval page.

Before acting, a command finds exactly one post, project, clip or mission. When more than one fits, it names them and
the model asks the owner which one; times are clock times in the Autopilot time zone (Settings), which `posts` shows.
After acting, it reads the thing back and reports what the app shows now, with a link. Work it queues (a render, a
project made again) is returned as `work` and the chat shows it as queued, running, completed or failed (work_state).
"""
from __future__ import annotations

import re
import time

from fastapi import HTTPException

from .. import db
from .toolbox import _SETTINGS_WORDS, _find_clip, _said_words, find
from .tools import Ctx, Result, Tool, ToolError, TryAgain, one_line, register

PLATFORM_NAMES = {"youtube": "YouTube", "tiktok": "TikTok"}
STATUS_WORDS = {"awaiting_approval": "waiting for your approval", "approved": "approved, waiting for its time",
                "publishing": "uploading now", "reconciling": "being checked with the platform",
                "action_needed": "needs you", "failed": "failed", "blocked": "held", "published": "posted",
                "canceled": "canceled", "replaced": "replaced by a stronger clip"}
MOVABLE = ("awaiting_approval", "approved", "failed")          # scheduler.reschedule moves only these
RETRYABLE = ("failed", "blocked", "action_needed", "canceled")  # autopilot/routes.retry_item
CANCELABLE = ("awaiting_approval", "approved", "failed", "action_needed", "blocked")
VIEWS = {"upcoming": ("awaiting_approval", "approved", "publishing", "reconciling", "action_needed"),
         "problems": ("failed", "blocked", "action_needed", "reconciling"),
         "published": ("published",)}
STALL_S = 10 * 60       # a running job without progress this long is reported as stalled
RECENT_S = 2 * 86400    # failed work this recent is listed
LIST_MAX = 12           # lines one list gives the model
WORK_KINDS = ("project", "clip", "post", "job")
FINAL = ("completed", "failed", "canceled")


def _http(exc: HTTPException) -> ToolError:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return ToolError(detail.rstrip(".") + ".")


def _settings() -> dict:
    return db.get_settings()


def _zone(settings: dict) -> str:
    from ..autopilot import scheduler

    return scheduler.tz(settings).key


def _label(ts: float | None, settings: dict) -> str:
    from ..autopilot import scheduler

    return scheduler._label(ts, settings) if ts else "no time yet"


def _local(ts: float, settings: dict) -> str:
    from ..autopilot import scheduler

    return scheduler._local(ts, settings).strftime("%Y-%m-%dT%H:%M")


def _api():
    from .. import api

    return api


# ------------------------------------------------------------------ posts
def _account(item: dict) -> tuple[str, str]:
    """(the account's id, its name) as every check reads it (autopilot/targets.py)."""
    from ..autopilot import targets

    view = targets.account_view(item)
    return str(view.get("connection_id") or ""), str(view.get("name") or "default account")


def _post_name(item: dict) -> str:
    clip = db.get_clip(item.get("clip_id") or "") or {}
    return one_line(item.get("title") or clip.get("title") or "untitled post", 70)


def _post_words(item: dict, settings: dict) -> str:
    clip = db.get_clip(item.get("clip_id") or "") or {}
    project = db.get_project(clip.get("project_id") or "") or {}
    when = _local(item["planned_at"], settings).replace("T", " ") if item.get("planned_at") else ""
    return " ".join(str(x or "") for x in (item.get("title"), clip.get("title"), project.get("name"),
                                           PLATFORM_NAMES.get(item["platform"], item["platform"]), _account(item)[1],
                                           when, _label(item.get("planned_at"), settings)))


def _gap(settings: dict) -> float:
    return 60.0 * float(settings.get("autopilot_min_gap_minutes", 0) or 0)


def conflicts(settings: dict | None = None) -> dict[str, dict]:
    """Posts not yet out that are closer than the minimum gap to another post on the same account: {post id: the
    other post}. scheduler.reschedule refuses such a time; one can still arise when the gap or an account changes."""
    settings = settings if settings is not None else _settings()
    gap = _gap(settings)
    if gap <= 0:
        return {}
    rows = [r for r in db.select("scheduled_publications", "status IN ('awaiting_approval', 'approved', "
                                 "'publishing', 'reconciling', 'published') AND planned_at IS NOT NULL", (),
                                 "planned_at ASC", 600)]
    out: dict[str, dict] = {}
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b["planned_at"] - a["planned_at"] >= gap:
                break
            if a["platform"] != b["platform"] or _account(a)[0] != _account(b)[0]:
                continue
            for mine, other in ((b, a), (a, b)):  # the one that can still move is the one to fix
                if mine["status"] in ("awaiting_approval", "approved") and mine["id"] not in out:
                    out[mine["id"]] = other
                    break
    return out


def _post_line(n: int, item: dict, settings: dict, clash: dict[str, dict]) -> str:
    from ..autopilot import submissions

    text = (f"{n}. “{_post_name(item)}” on {PLATFORM_NAMES.get(item['platform'], item['platform'])} "
            f"({_account(item)[1]}): {_label(item.get('planned_at'), settings)}, "
            f"{STATUS_WORDS.get(item['status'], item['status'])}")
    if item.get("status_note"):
        text += f" ({one_line(item['status_note'], 90)})"
    if item["status"] in ("failed", "blocked", "action_needed") and (item.get("last_error") or item.get("fix")):
        text += f". Why: {one_line(item.get('last_error') or '', 140)}"
        if item.get("fix"):
            text += f" What to do: {one_line(item['fix'], 140)}"
    if item["id"] in clash:
        other = clash[item["id"]]
        text += (f". Too close to “{_post_name(other)}” at {_label(other['planned_at'], settings)} on the same "
                 "account")
    if item["status"] in ("approved", "awaiting_approval") and submissions.paused_for(item):
        text += ". Its mission's uploads are paused"
    return text + "."


def find_post(args: dict, statuses: tuple[str, ...], doing: str) -> dict:
    """The one post `args` names (post: words from its title, its video, its time like "18:30" or "Nov 26", or its
    id; platform; account: words from the account's name), among posts in `statuses`. Raises ToolError naming the
    candidates when none or several fit, so the model asks the owner which one."""
    settings = _settings()
    marks = ",".join("?" * len(statuses))
    rows = db.select("scheduled_publications", f"status IN ({marks})", tuple(statuses),
                     "planned_at IS NULL, planned_at ASC", 400)
    want = str(args.get("post") or "").strip()
    exact = [r for r in rows if r["id"] == want]
    if exact:
        return exact[0]
    if args.get("platform"):
        rows = [r for r in rows if r["platform"] == args["platform"]]
    if args.get("account"):
        who = set(_said_words(str(args["account"])))
        rows = [r for r in rows if who & set(_said_words(_account(r)[1]))]
    if not rows:
        raise ToolError(f"There is no post that {doing}" + (" on that account or platform." if (
            args.get("platform") or args.get("account")) else ". Use posts to see them all."))
    if want:
        words = {w for w in _said_words(want) if len(w) > 2} | set(re.findall(r"\d{1,2}:\d{2}", want))
        scored = []
        for r in rows:
            have = _post_words(r, settings).lower()
            hit = sum(1 for w in words if w in set(_said_words(have)) or (":" in w and w in have))
            scored.append((hit, r))
        best = max(h for h, _ in scored)
        rows = [r for h, r in scored if h == best and h > 0]
        if not rows:
            raise ToolError(f"No post that {doing} matches “{one_line(want, 60)}”. They are: " + _names(
                [r for _, r in scored], settings) + ".")
    if len(rows) > 1:
        raise ToolError(f"More than one post that {doing} fits: " + _names(rows, settings)
                        + ". Ask the owner which one (its title, channel or time).")
    return rows[0]


def _names(rows: list[dict], settings: dict) -> str:
    return "; ".join(f"“{_post_name(r)}” on {PLATFORM_NAMES.get(r['platform'], r['platform'])} ({_account(r)[1]}), "
                     f"{_label(r.get('planned_at'), settings)}" for r in rows[:6]) + ("; …" if len(rows) > 6 else "")


def _post_links(item: dict) -> list[dict]:
    return [{"label": f"Open “{_post_name(item)}”", "href": f"#/post/{item['id']}"},
            {"label": "Missions → Schedule", "href": "#/missions"}]


def _posts(ctx: Ctx, args: dict) -> Result:
    settings = _settings()
    view = args.get("view") or "upcoming"
    statuses = VIEWS.get(view) or VIEWS["upcoming"]
    marks = ",".join("?" * len(statuses))
    order = "planned_at IS NULL, planned_at ASC" if view != "published" else "planned_at DESC"
    rows = db.select("scheduled_publications", f"status IN ({marks})", statuses, order, 400)
    if args.get("words"):
        words = {w for w in _said_words(args["words"]) if len(w) > 2}
        rows = [r for r in rows if words & set(_said_words(_post_words(r, settings)))] or rows
    clash = conflicts(settings)
    lines = [f"Times are in {_zone(settings)} (Settings → Autopilot time zone); it is now "
             f"{_label(time.time(), settings)} there. Posts on one account keep at least "
             f"{_gap(settings) / 60:.0f} minutes apart."]
    if not rows:
        lines.append(f"No {view} posts.")
    lines += [_post_line(i + 1, r, settings, clash) for i, r in enumerate(rows[:LIST_MAX])]
    if len(rows) > LIST_MAX:
        lines.append(f"…and {len(rows) - LIST_MAX} more.")
    if clash and view != "published":
        lines.append(f"{len(clash)} post(s) are too close to another on the same account: fix_post_conflicts moves "
                     "them to the nearest free times.")
    return Result("\n".join(lines), f"Looked at your posts ({len(rows)})",
                  {"links": [{"label": "Missions → Schedule", "href": "#/missions"}]})


def _when_preview(item: dict, when: str, settings: dict) -> tuple[float, list[str]]:
    """The time a post would move to and why: the owner's clock time, or the nearest free one when it is too close
    to another post on the same account (scheduler.nearest_free, the time Change the time offers)."""
    from ..autopilot import scheduler

    notes: list[str] = []
    if str(when).strip().lower() in ("nearest", "nearest_free", "nearest free", "next free"):
        wanted = float(item.get("planned_at") or time.time() + 600)
        notes.append("You asked for the nearest free time.")
    else:
        try:
            wanted = scheduler.from_wall_time(when, settings)
        except ValueError as exc:
            raise ToolError(f"{exc} Use the form 2026-11-26T18:30, in {_zone(settings)}.") from exc
    if wanted < time.time() + 60:
        raise ToolError(f"{_label(wanted, settings)} has passed in {_zone(settings)}. Choose a time in the future.")
    gap = _gap(settings)
    clash = [o for o in scheduler._taken(item, settings) if abs(o - wanted) < gap]
    if clash or (notes and any(abs(o - wanted) < gap for o in scheduler._taken(item, settings))):
        free = scheduler.nearest_free(item, wanted, settings)
        if free is None:
            raise ToolError("Every time within a day of that is taken on this account. Choose another day.")
        if not notes:
            notes.append(f"{_label(wanted, settings)} is less than {gap / 60:.0f} minutes from another post on the "
                         f"same account, so this is the nearest free time.")
        wanted = free
    return wanted, notes


def _approval_note(item: dict) -> str:
    if item["status"] == "approved":
        return "It keeps your approval."
    if item["status"] == "failed":
        return "It goes out at the new time only if nothing changed since you approved it; otherwise it asks again."
    return "It still needs your approval on its page before it posts."


def _reschedule_preview(ctx: Ctx, args: dict) -> dict:
    settings = _settings()
    item = find_post(args, MOVABLE, "can be moved")
    at, notes = _when_preview(item, str(args.get("when") or ""), settings)
    platform = PLATFORM_NAMES.get(item["platform"], item["platform"])
    return {"label": f"Move “{_post_name(item)}” ({platform}, {_account(item)[1]}) to {_label(at, settings)}",
            "detail": [f"Now: {_label(item.get('planned_at'), settings)}. Times are in {_zone(settings)}.", *notes,
                       _approval_note(item)],
            "blocked": "", "args": {"post": item["id"], "when": _local(at, settings)}}


def _move(item_id: str, local: str) -> dict:
    """Move one post through the reschedule route (the same as Change the time)."""
    from fastapi.responses import JSONResponse

    from ..autopilot import routes

    try:
        out = routes.reschedule_item(item_id, routes.RescheduleBody(local=local))
    except HTTPException as exc:
        raise _http(exc) from exc
    if isinstance(out, JSONResponse):
        import json

        body = json.loads(out.body)
        hint = f" The nearest free time now is {body['suggestion_local'].replace('T', ' ')}." if body.get(
            "suggestion_local") else ""
        raise ToolError(f"{body.get('detail', 'That time is taken.')}{hint} Ask again to move it there.".replace(
            "..", "."))
    return out


def _reschedule(ctx: Ctx, args: dict) -> Result:
    settings = _settings()
    item = db.fetch("scheduled_publications", args.get("post") or "")
    if not item:
        raise ToolError("That post is not there any more.")
    out = _move(item["id"], args["when"])
    return Result(f"Moved “{_post_name(out)}” to {_label(out.get('planned_at'), settings)} ({_zone(settings)}); it "
                  f"is {STATUS_WORDS.get(out['status'], out['status'])}.",
                  f"Moved to {_label(out.get('planned_at'), settings)}",
                  {"links": _post_links(out), "work": [_work("post", out["id"], f"“{_post_name(out)}”")]})


def _fix_preview(ctx: Ctx, args: dict) -> dict:
    """One move for each post that is too close to another on its account, to the nearest time that keeps the gap
    from every other post, including the moves before it on this card."""
    settings = _settings()
    clash = conflicts(settings)
    if args.get("platform"):
        clash = {k: v for k, v in clash.items() if (db.fetch("scheduled_publications", k) or {}).get(
            "platform") == args["platform"]}
    if not clash:
        raise ToolError("No posts are too close to each other now.")
    gap, moves, detail, planned = _gap(settings), [], [], {}
    for item_id in clash:
        item = db.fetch("scheduled_publications", item_id)
        if not item:
            continue
        taken = [planned.get(o_id, o) for o_id, o in _taken_with_ids(item)]  # with the moves planned above
        free = None
        for step in range(1, 24 * 12 + 1):
            for t in (item["planned_at"] + step * 300, item["planned_at"] - step * 300):
                if t >= time.time() + 120 and all(abs(o - t) >= gap for o in taken):
                    free = t
                    break
            if free:
                break
        if free is None:
            detail.append(f"“{_post_name(item)}”: no free time within a day; it stays.")
            continue
        planned[item_id] = free
        moves.append({"post": item_id, "when": _local(free, settings)})
        detail.append(f"“{_post_name(item)}” ({PLATFORM_NAMES.get(item['platform'], item['platform'])}, "
                      f"{_account(item)[1]}): {_label(item['planned_at'], settings)} → {_label(free, settings)}")
    if not moves:
        raise ToolError("Those posts have no free time within a day. Move one by hand on Missions → Schedule.")
    detail.append(f"Times are in {_zone(settings)}; each keeps its approval as it is.")
    return {"label": f"Move {len(moves)} post(s) so posts on one account are at least {gap / 60:.0f} minutes apart",
            "detail": detail[:16], "blocked": "", "args": {"moves": moves}}


def _taken_with_ids(item: dict) -> list[tuple[str, float]]:
    account = _account(item)[0]
    return [(o["id"], o["planned_at"]) for o in db.select(
        "scheduled_publications", "platform = ? AND id != ? AND status IN ('awaiting_approval', 'approved', "
        "'publishing', 'reconciling', 'published') AND planned_at IS NOT NULL", (item["platform"], item["id"]))
        if _account(o)[0] == account]


def _fix(ctx: Ctx, args: dict) -> Result:
    settings = _settings()
    done, failed, work = [], [], []
    for move in args.get("moves") or []:
        item = db.fetch("scheduled_publications", str(move.get("post") or ""))
        if not item:
            failed.append("a post that is not there any more")
            continue
        try:
            out = _move(item["id"], str(move.get("when") or ""))
        except ToolError as exc:
            failed.append(f"“{_post_name(item)}”: {exc}")
            continue
        done.append(f"“{_post_name(out)}” to {_label(out.get('planned_at'), settings)}")
        work.append(_work("post", out["id"], f"“{_post_name(out)}”"))
    text = ("Moved " + "; ".join(done) + "." if done else "Nothing was moved.") + (
        " Not moved: " + " ".join(failed) if failed else "")
    left = len(conflicts(settings))
    text += f" {left} post(s) are still too close to another." if left else " No posts are too close now."
    return Result(text, f"Moved {len(done)} post(s)", {"links": [{"label": "Missions → Schedule",
                                                                  "href": "#/missions"}], "work": work},
                  ok=bool(done))


def _cancel_upload_preview(ctx: Ctx, args: dict) -> dict:
    item = find_post(args, ("publishing",), "is uploading now")
    platform = PLATFORM_NAMES.get(item["platform"], item["platform"])
    return {"label": f"Cancel the upload of “{_post_name(item)}” to {platform} ({_account(item)[1]})",
            "detail": ["It stops after the part being sent and ends as canceled: nothing is posted, unless "
                       f"{platform} already has the whole video, which is then shown as it is.",
                       "You can try it again later from its page."],
            "blocked": "", "args": {"post": item["id"]}}


def _cancel_upload(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    try:
        out = routes.cancel_upload(str(args.get("post") or ""))
    except HTTPException as exc:
        raise _http(exc) from exc
    said = (out.get("cancel") or {}).get("message") or ""
    state = STATUS_WORDS.get(out["status"], out["status"])
    return Result(f"Asked to cancel the upload of “{_post_name(out)}”. {said} It is {state} now.".replace("  ", " "),
                  "Canceled the upload" if out["status"] == "canceled" else "Canceling the upload",
                  {"links": _post_links(out), "work": [_work("post", out["id"], f"“{_post_name(out)}”")]})


def _cancel_post_preview(ctx: Ctx, args: dict) -> dict:
    settings = _settings()
    item = find_post(args, CANCELABLE, "is planned")
    return {"label": f"Don't post “{_post_name(item)}” on {PLATFORM_NAMES.get(item['platform'], item['platform'])}",
            "detail": [f"Planned for {_label(item.get('planned_at'), settings)}. It is taken off the schedule; its "
                       "clip stays, and Try again on its page plans it again."],
            "blocked": "", "args": {"post": item["id"]}}


def _cancel_post(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    try:
        out = routes.cancel_item(str(args.get("post") or ""))
    except HTTPException as exc:
        raise _http(exc) from exc
    return Result(f"“{_post_name(out)}” is {STATUS_WORDS.get(out['status'], out['status'])}: it will not be posted.",
                  "Took it off the schedule", {"links": _post_links(out)})


def _retry_preview(ctx: Ctx, args: dict) -> dict:
    item = find_post(args, RETRYABLE, "failed, is held or was canceled")
    why = one_line(item.get("last_error") or item.get("status_note") or "", 160)
    return {"label": f"Try “{_post_name(item)}” again on {PLATFORM_NAMES.get(item['platform'], item['platform'])}",
            "detail": [*([f"Last time: {why}"] if why else []),
                       "It gets a new time; it goes out only with a valid approval (otherwise it asks you again)."],
            "blocked": "", "args": {"post": item["id"]}}


def _retry(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    try:
        out = routes.retry_item(str(args.get("post") or ""))
    except HTTPException as exc:
        raise _http(exc) from exc
    return Result(f"“{_post_name(out)}” is {STATUS_WORDS.get(out['status'], out['status'])}"
                  + (f" ({out['status_note']})" if out.get("status_note") else "") + ".", "Trying it again",
                  {"links": _post_links(out), "work": [_work("post", out["id"], f"“{_post_name(out)}”")]})


# ------------------------------------------------------------------ work: what is running, waiting or stuck
def _queue() -> tuple[str | None, list[tuple[str, str]]]:
    """(the key the worker runs now, the (kind, key) waiting in its line)."""
    worker = _api().worker
    with worker.q.mutex:
        waiting = [(kind, key) for kind, key, _extra in list(worker.q.queue)]
    return worker.current, waiting


def diagnose_project(p: dict, now: float | None = None) -> dict:
    """{state, why, next} for one clips project: running, queued, stalled, failed, canceled or done."""
    now = now or time.time()
    current, waiting = _queue()
    status = p.get("status") or ""
    since = now - float(p.get("updated_at") or now)
    if status in ("queued", "processing", "rendering"):
        if current == p["id"]:
            if since > STALL_S:
                return {"state": "stalled", "why": f"it is the job running now, but it has not moved for "
                        f"{int(since // 60)} minutes (at {p.get('stage') or 'its current step'})",
                        "next": "stop it and start it again with restart_work (what was already made is reused)"}
            return {"state": "running", "why": f"{p.get('message') or p.get('stage') or 'working'}, "
                    f"{round(float(p.get('progress') or 0) * 100)}% done", "next": "nothing: it is moving"}
        line = [k for _kind, k in waiting]
        if p["id"] in line:
            ahead = line.index(p["id"]) + (1 if current else 0)
            return {"state": "queued", "why": f"waiting in line: {ahead} job(s) before it (one heavy job runs at a "
                    "time so the computer stays usable)", "next": "nothing: it starts by itself"}
        return {"state": "stalled", "why": "it says it is being made, but nothing is working on it (ClipForge was "
                "probably closed or stopped while it ran)", "next": "start it again with restart_work"}
    if status == "importing":
        return {"state": "running", "why": p.get("message") or "downloading the video", "next": "nothing"}
    if status == "error":
        return {"state": "failed", "why": one_line(p.get("error") or p.get("message") or "it stopped with an error",
                                                   300),
                "next": "start it again with restart_work; if it fails the same way, the reason above says what to "
                        "change"}
    if status == "cancelled":
        return {"state": "canceled", "why": "it was stopped", "next": "start it again with restart_work"}
    return {"state": "done", "why": f"finished ({status})", "next": "nothing"}


def diagnose_clip(c: dict, now: float | None = None) -> dict:
    now = now or time.time()
    current, waiting = _queue()
    status = c.get("status") or ""
    since = now - float(c.get("updated_at") or now)
    if status in ("queued", "rendering"):
        if current == c["id"]:
            if since > STALL_S:
                return {"state": "stalled", "why": f"rendering, but no progress for {int(since // 60)} minutes",
                        "next": "stop it and render it again with restart_work"}
            return {"state": "running", "why": f"rendering, {round(float(c.get('progress') or 0) * 100)}% done",
                    "next": "nothing"}
        if c["id"] in [k for _kind, k in waiting]:
            return {"state": "queued", "why": "waiting in line to render", "next": "nothing: it starts by itself"}
        return {"state": "stalled", "why": "it says it is rendering, but nothing is working on it",
                "next": "render it again with restart_work"}
    if status == "error":
        return {"state": "failed", "why": one_line(c.get("error") or "the render failed", 300),
                "next": "render it again with restart_work"}
    return {"state": "done" if status == "ready" else status or "done", "why": status or "ready", "next": "nothing"}


def diagnose_job(j: dict, now: float | None = None) -> dict:
    """A background job (publishing, checks, live captures: worker_jobs)."""
    now = now or time.time()
    status = j.get("status") or ""
    if status == "running" and float(j.get("lease_until") or 0) and float(j["lease_until"]) < now - 60:
        return {"state": "stalled", "why": "its worker stopped checking in", "next": "ClipForge hands it to a worker "
                "again by itself within a few minutes; if it does not, restart ClipForge"}
    if status == "running":
        return {"state": "running", "why": j.get("message") or j.get("stage") or "working", "next": "nothing"}
    if status in ("waiting", "retrying"):
        when = float(j.get("run_after") or 0)
        later = f" (next try in {max(1, int((when - now) // 60))} minutes)" if when > now else ""
        return {"state": "waiting", "why": one_line(j.get("wait_reason") or j.get("error") or j.get("message")
                                                    or status, 200) + later,
                "next": one_line(j.get("fix") or "nothing: it tries again by itself", 200)}
    if status == "queued":
        return {"state": "queued", "why": "waiting for its turn", "next": "nothing"}
    if status == "failed":
        return {"state": "failed", "why": one_line(j.get("error") or "it failed", 240),
                "next": one_line(j.get("fix") or "try the post again with retry_post", 200)}
    return {"state": "done" if status == "completed" else status, "why": status, "next": "nothing"}


JOB_WORDS = {"publish": "Posting", "live_capture": "Recording a live stream", "live_clip": "Clipping a live stream"}


def _work_list(ctx: Ctx, args: dict) -> Result:
    now = time.time()
    lines: list[str] = []
    want = set(_said_words(args.get("words") or "")) - {"the", "my", "video", "project", "job", "stuck", "it"}

    def wanted(name: str) -> bool:
        return not want or bool(want & set(_said_words(name)))

    busy = db.select("projects", "status IN ('queued', 'processing', 'rendering', 'importing', 'error', "
                     "'cancelled') AND updated_at > ?", (now - RECENT_S,), "updated_at DESC", 40)
    busy = [p for p in busy if (p.get("workspace_id") or "local") == ctx.ws]
    for p in busy:
        if not wanted(p["name"]):
            continue
        d = diagnose_project(p, now)
        lines.append(f"- Project “{one_line(p['name'], 60)}”: {d['state']}: {d['why']}. Next: {d['next']}.")
    for c in db.select("clips", "status IN ('queued', 'rendering', 'error') AND updated_at > ?", (now - RECENT_S,),
                       "updated_at DESC", 30):
        proj = db.get_project(c["project_id"]) or {}
        if not wanted(f"{c.get('title')} {proj.get('name')}"):
            continue
        d = diagnose_clip(c, now)
        lines.append(f"- Render of “{one_line(c.get('title') or 'a clip', 50)}” ({one_line(proj.get('name'), 40)}): "
                     f"{d['state']}: {d['why']}. Next: {d['next']}.")
    for j in db.select("worker_jobs", "status IN ('queued', 'running', 'waiting', 'retrying', 'failed') AND "
                       "updated_at > ?", (now - RECENT_S,), "updated_at DESC", 30):
        item = db.fetch("scheduled_publications", j.get("ref_id") or "") if j.get("ref_type") == "scheduled" else None
        name = f"“{_post_name(item)}”" if item else (j.get("message") or j["kind"])
        if not wanted(str(name)):
            continue
        d = diagnose_job(j, now)
        lines.append(f"- {JOB_WORDS.get(j['kind'], j['kind'].replace('_', ' ').capitalize())} {one_line(name, 60)}: "
                     f"{d['state']}: {d['why']}. Next: {d['next']}.")
    for s in db.select("studio_jobs", "workspace_id = ? AND status IN ('queued', 'running', 'failed') AND "
                       "updated_at > ?", (ctx.ws, now - RECENT_S), "updated_at DESC", 20):
        stale = s["status"] == "running" and float(s.get("lease_until") or 0) < now - 60
        state = "stalled" if stale else s["status"]
        lines.append(f"- Studio job {s['kind'].replace('_', ' ')}: {state}: "
                     f"{one_line(s.get('error') or s.get('message') or s['status'], 160)}."
                     + (" Next: ClipForge picks it up again by itself; if not, restart ClipForge." if stale else ""))
    current, waiting = _queue()
    head = (f"The heavy-work line: {'one job running' if current else 'nothing running'}, {len(waiting)} waiting. "
            "Work started or failed in the last two days:")
    if not lines:
        lines.append("- Nothing" + (" matches those words." if want else " is running, waiting or failed."))
    return Result("\n".join([head, *lines[:LIST_MAX + 4]]), "Checked the work",
                  {"links": [{"label": "Missions → Activity", "href": "#/missions/activity"}]})


def _target(ctx: Ctx, args: dict) -> tuple[str, dict, str]:
    """("project" or "clip", the row, its name) for restart_work and stop_work."""
    if args.get("clip"):
        p, c, n = _find_clip(ctx.ws, args.get("project", ""), args["clip"], ctx.project_id)
        return "clip", c, f"clip {n} of “{p['name']}”"
    p = find(ctx.ws, args.get("project", ""), ctx.project_id, "clips")
    if p["kind"] != "clips":
        raise ToolError(f"“{p['name']}” is a YouTube video: its work is on its own page.")
    return "project", db.get_project(p["id"]) or {}, f"“{p['name']}”"


def _restart_preview(ctx: Ctx, args: dict) -> dict:
    kind, row, name = _target(ctx, args)
    d = (diagnose_project if kind == "project" else diagnose_clip)(row)
    if d["state"] in ("running", "queued"):
        raise ToolError(f"{name[0].upper() + name[1:]} is {d['state']} ({d['why']}): there is nothing to restart.")
    if d["state"] == "done":
        raise ToolError(f"{name[0].upper() + name[1:]} is finished. To change it, edit it or render a clip again.")
    what = ("Start making the clips of " + name + " again (the saved sound and transcript are reused)"
            if kind == "project" else "Render " + name + " again")
    return {"label": what[0].upper() + what[1:], "detail": [f"Now: {d['state']}: {d['why']}."]
            + (["It is stopped first; press OK again once it has stopped."] if d["state"] == "stalled"
               and _queue()[0] == row["id"] else []),
            "blocked": "", "args": {"kind": kind, "id": row["id"]}}


def _restart(ctx: Ctx, args: dict) -> Result:
    api, worker = _api(), _api().worker
    kind, row_id = args.get("kind"), str(args.get("id") or "")
    row = (db.get_project if kind == "project" else db.get_clip)(row_id)
    if not row:
        raise ToolError("It is not there any more.")
    current, waiting = _queue()
    name = f"“{row.get('name') or row.get('title') or 'it'}”"
    if current == row_id:  # stuck while running: ask it to stop, then the next press starts it
        worker.cancel(row_id)
        raise TryAgain(f"Asked {name} to stop. Press OK again in a moment to start it again.")
    if row_id in [k for _k, k in waiting]:
        raise ToolError(f"{name} is already waiting in line; it starts by itself.")
    try:
        if kind == "project":
            if row["status"] in ("queued", "processing", "rendering"):  # stalled: nothing is running it
                from pathlib import Path

                missing = not row.get("source_path") or not Path(row["source_path"]).exists()
                worker.submit_project(row_id, url=row.get("source_url") if missing else None)
            else:
                api.reprocess(row_id, api.ProcessBody())
        elif row["status"] in ("queued", "rendering"):
            worker.submit_render(row_id)
        else:
            api.rerender(row_id)
    except HTTPException as exc:
        raise _http(exc) from exc
    work = _work(kind, row_id, name)
    return Result(f"{name} is in line to be made again; the chat shows when it runs and when it is done.",
                  f"Started {name} again", {"work": [work], "links": [_open_link(kind, row)]})


def _stop_preview(ctx: Ctx, args: dict) -> dict:
    kind, row, name = _target(ctx, args)
    d = (diagnose_project if kind == "project" else diagnose_clip)(row)
    if d["state"] not in ("running", "queued", "stalled"):
        raise ToolError(f"{name[0].upper() + name[1:]} is not running ({d['state']}).")
    return {"label": f"Stop {'making ' if kind == 'project' else 'rendering '}{name}",
            "detail": ["It stops at its next step. What was already made stays; you can start it again later."],
            "blocked": "", "args": {"kind": kind, "id": row["id"]}}


def _stop(ctx: Ctx, args: dict) -> Result:
    api = _api()
    kind, row_id = args.get("kind"), str(args.get("id") or "")
    row = (db.get_project if kind == "project" else db.get_clip)(row_id)
    if not row:
        raise ToolError("It is not there any more.")
    if kind == "project":
        api.cancel(row_id)
    else:
        api.worker.cancel(row_id)
    name = f"“{row.get('name') or row.get('title') or 'it'}”"
    return Result(f"Asked {name} to stop; it stops at its next step.", f"Stopping {name}",
                  {"work": [_work(kind, row_id, name)], "links": [_open_link(kind, row)]})


def _open_link(kind: str, row: dict) -> dict:
    if kind == "clip":
        return {"label": "Open the clip", "href": f"#/clip/{row['id']}"}
    return {"label": f"Open “{one_line(row.get('name'), 40)}”", "href": f"#/project/{row['id']}"}


# ------------------------------------------------------------------ clips: post text, framing, render
def _regen_preview(ctx: Ctx, args: dict) -> dict:
    p, c, n = _find_clip(ctx.ws, args.get("project", ""), args.get("clip", ""), ctx.project_id)
    post = c.get("post") if isinstance(c.get("post"), dict) else {}
    return {"label": f"Write a new title, post text and hashtags for clip {n} of “{p['name']}”",
            "detail": [f"Replaces the current ones (now: “{one_line(post.get('title') or c.get('title'), 80)}”), "
                       "your own edits too.",
                       "Posts already planned keep their own text: change those on the post's page."],
            "blocked": "", "args": {"clip_id": c["id"]}}


def _regen(ctx: Ctx, args: dict) -> Result:
    api = _api()
    try:
        out = api.regenerate_post_package(str(args.get("clip_id") or ""), api.PostPackageBody())
    except HTTPException as exc:
        raise _http(exc) from exc
    post = out.get("post") or {}
    tags = " ".join(post.get("hashtags") or [])
    return Result(f"New title: “{post.get('title') or out.get('title')}”. Hashtags: {tags or 'none'}.",
                  "Wrote new post text", {"links": [{"label": "Open the clip", "href": f"#/clip/{out['id']}"}]})


FOLLOW = {"auto": "the action, automatically", "center": "the middle", "face": "the face", "speaker":
          "whoever is talking", "screen": "the screen"}
LAYOUT_WORDS = {"fill": "Fill (crop)", "fit": "Fit (whole frame)", "split": "Gameplay + Facecam",
                "pip": "Picture-in-picture", "game": "Gameplay only", "auto": "Automatic"}


def _framing(args: dict) -> tuple[dict, list[str]]:
    edit, words = {}, []
    if args.get("position") is not None:
        x = max(0.0, min(100.0, float(args["position"])))
        edit.update(tracking="manual", crop_x=round(x / 100, 3))
        words.append(f"the picture at {x:.0f}% from the left")
    elif args.get("follow"):
        edit["tracking"] = args["follow"]
        words.append(f"framing follows {FOLLOW[args['follow']]}")
    if args.get("layout"):
        edit["layout"] = args["layout"]
        words.append(f"layout {LAYOUT_WORDS[args['layout']]}")
    if args.get("zoom") is not None:
        edit["zoom"] = round(max(1.0, min(2.5, float(args["zoom"]))), 2)
        words.append(f"zoom {edit['zoom']}×")
    if args.get("corner"):
        edit["pip_corner"] = args["corner"]
        words.append(f"face cam box at the top {args['corner']}")
    if not edit:
        raise ToolError("Say what to change: position (0 to 100% from the left), follow, layout, zoom or corner.")
    return edit, words


def _crop_preview(ctx: Ctx, args: dict) -> dict:
    p, c, n = _find_clip(ctx.ws, args.get("project", ""), args.get("clip", ""), ctx.project_id)
    edit, words = _framing(args)
    busy = c.get("status") in ("queued", "rendering")
    return {"label": f"Frame clip {n} of “{p['name']}”: " + ", ".join(words),
            "detail": ["The same change as the clip editor's Layout tab.",
                       "Then it is rendered again with the new framing." if not busy else
                       "It is rendering now: the new framing is used the next time it renders."],
            "blocked": "", "args": {"clip_id": c["id"], "edit": edit}}


def _crop(ctx: Ctx, args: dict) -> Result:
    api = _api()
    clip_id = str(args.get("clip_id") or "")
    try:
        api.patch_clip(clip_id, api.ClipPatch(edit=dict(args.get("edit") or {})))
        out = api.rerender(clip_id)
        queued = True
    except HTTPException as exc:
        if exc.status_code != 409:
            raise _http(exc) from exc
        out, queued = api.get_clip(clip_id), False
    name = f"“{one_line(out.get('title') or 'the clip', 50)}”"
    return Result(f"Saved the new framing of {name}" + (" and queued its render." if queued else
                                                         "; it is already rendering, so render it again after."),
                  "Changed the framing", {"links": [{"label": "Open the clip", "href": f"#/clip/{clip_id}"}],
                                          "work": [_work("clip", clip_id, f"Render {name}")] if queued else []})


def _render(ctx: Ctx, args: dict) -> Result:
    api = _api()
    p, c, n = _find_clip(ctx.ws, args.get("project", ""), args.get("clip", ""), ctx.project_id)
    try:
        api.rerender(c["id"])
    except HTTPException as exc:
        raise _http(exc) from exc
    return Result(f"Clip {n} of “{p['name']}” is in line to render; the chat shows when it is done.",
                  f"Queued clip {n} to render", {"work": [_work("clip", c["id"], f"Render clip {n}")],
                                                 "links": [{"label": f"Open clip {n}", "href": f"#/clip/{c['id']}"}]})


# ------------------------------------------------------------------ the crew: the final check and its reviews
def _crew_clips(ctx: Ctx, args: dict) -> tuple[dict, list[tuple[int, dict]]]:
    """(the project, [(clip number, clip)]): one clip when `clip` is given, else the project's best ones."""
    if args.get("clip"):
        p, c, n = _find_clip(ctx.ws, args.get("project", ""), args["clip"], ctx.project_id)
        return p, [(n, c)]
    p = find(ctx.ws, args.get("project", ""), ctx.project_id, "clips")
    if p["kind"] != "clips":
        raise ToolError(f"“{p['name']}” is a YouTube video; the crew checks clips projects.")
    clips = sorted(db.list_clips(p["id"]), key=lambda c: -float(c.get("score") or 0))
    return p, [(i + 1, c) for i, c in enumerate(clips[:CREW_MAX])]


CREW_MAX = 6  # clips one request hands to the crew


def _crew_check(ctx: Ctx, args: dict) -> Result:
    """Hand clips to the crew's final check (the same job Autopilot runs before a post: CHECK checks the file,
    picture, sound, captions, cuts and text; a fixable problem goes back to the robot responsible, at most twice)."""
    from ..autopilot import gate
    from ..autopilot.host import MANUAL_PRIORITY

    p, picked = _crew_clips(ctx, args)
    work, skipped = [], []
    for n, c in picked:
        if c.get("status") != "ready":
            skipped.append(f"clip {n} is not rendered yet ({c.get('status')})")
            continue
        job = gate.request(c, priority=MANUAL_PRIORITY)
        if job:
            work.append(_work("job", job["id"], f"Final check of clip {n}"))
    if not work:
        raise ToolError("Nothing to check: " + "; ".join(skipped or ["no clips"])
                        + ". Render them first (render_clip).")
    text = (f"The crew is checking {len(work)} clip(s) of “{p['name']}”: CHECK looks at the file, picture, sound, "
            "captions, cuts and text, and sends a fixable problem back to the robot responsible (at most twice). "
            "The chat shows each check as it runs; crew_report tells what they found.")
    if skipped:
        text += " Not checked: " + "; ".join(skipped) + "."
    return Result(text, f"Handed {len(work)} clip(s) to the crew", {"work": work, "links": [
        {"label": "Office", "href": "#/office"}, {"label": f"Open “{p['name']}”", "href": f"#/project/{p['id']}"}]})


ACTION_WORDS = {"approved": "passed", "rework": "sent back", "rejected": "did not pass", "held": "held for you"}


def _crew_report(ctx: Ctx, args: dict) -> Result:
    """What the crew found and decided for clips: the final check's result, the Director's decisions and the
    repairs it asked for, with the command that fixes what is left."""
    from ..autopilot import gate, queue
    from ..office import feed

    p, picked = _crew_clips(ctx, args)
    lines = []
    for n, c in picked:
        rep = gate.report_for(c)
        line = f"Clip {n} “{one_line(c.get('title') or 'untitled', 50)}”: "
        if rep:
            line += "final check " + ("passed" if rep["status"] == "passed" else "failed")
            if rep.get("blockers"):
                line += "; problems: " + "; ".join(one_line(b, 90) for b in rep["blockers"][:3])
            if rep.get("warnings"):
                line += "; warnings: " + "; ".join(one_line(w, 80) for w in rep["warnings"][:2])
        else:
            line += "not checked yet (crew_check)" if c.get("status") == "ready" else "not rendered yet"
        decided = feed.decisions_for("clip", c["id"])[:2]
        if decided:
            line += ". Decisions: " + "; ".join(f"{ACTION_WORDS.get(d['action'], d['action'])} "
                                                f"({one_line(d['reason'], 90)})" for d in decided)
        busy = [j for j in queue.jobs(ref=("clip", c["id"]), limit=6) if j["status"] in queue.ACTIVE]
        if busy:
            line += ". Working now: " + ", ".join(
                f"{j['kind'].replace('_', ' ')} ({j['status']}, try {int(j.get('attempts') or 0) + 1} of "
                f"{j.get('max_attempts') or 1})" for j in busy[:3])
        lines.append(line + ".")
    lines.append("To fix what is left: post text → regenerate_post_text; framing → adjust_framing; a damaged or old "
                 "file → render_clip; then crew_check again.")
    return Result("\n".join(lines), "Read the crew's reviews", {"links": [{"label": "Office", "href": "#/office"}]})


# ------------------------------------------------------------------ missions and settings
def _mission_name(row: dict) -> str:
    source = db.fetch("sources", row["source_id"]) or {}
    return one_line(source.get("title") or source.get("url") or "a mission", 70)


def _find_mission(args: dict) -> dict:
    rows = db.select("source_submissions", "revoked_at IS NULL", (), "created_at DESC", 200)
    want = {w for w in _said_words(args.get("mission") or "") if len(w) > 2} - {"mission", "the", "my"}
    hits = [r for r in rows if r["id"] == args.get("mission")] or [
        r for r in rows if not want or want & set(_said_words(_mission_name(r)))]
    if not hits:
        raise ToolError("No mission fits that. They are: " + "; ".join(f"“{_mission_name(r)}”" for r in rows[:8])
                        + "." if rows else "There are no missions yet.")
    if len(hits) > 1:
        raise ToolError("More than one mission fits: " + "; ".join(f"“{_mission_name(r)}”" for r in hits[:8])
                        + ". Ask the owner which one.")
    return hits[0]


def _missions(ctx: Ctx, args: dict) -> Result:
    rows = db.select("source_submissions", "revoked_at IS NULL", (), "created_at DESC", 200)
    lines = [f"- “{_mission_name(r)}”: uploads {'paused' if (r.get('settings') or {}).get('paused') else 'on'}"
             for r in rows[:LIST_MAX]] or ["- No missions yet."]
    return Result("Missions (the videos and streams ClipForge clips and posts for you):\n" + "\n".join(lines),
                  "Looked at your missions", {"links": [{"label": "Missions", "href": "#/missions"}]})


def _pause_preview(ctx: Ctx, args: dict) -> dict:
    row = _find_mission(args)
    paused = bool(args.get("paused", True))
    return {"label": f"{'Pause' if paused else 'Resume'} the uploads of “{_mission_name(row)}”",
            "detail": ["Paused, none of its posts starts uploading (one already uploading finishes); its clips are "
                       "still made." if paused else
                       "Its posts go at their planned times, or now when that has passed, keeping the gap."],
            "blocked": "", "args": {"mission": row["id"], "paused": paused}}


def _pause(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    try:
        routes.pause_submission(str(args.get("mission") or ""), routes.PauseBody(paused=bool(args.get("paused"))))
    except HTTPException as exc:
        raise _http(exc) from exc
    row = db.fetch("source_submissions", str(args.get("mission") or "")) or {}
    on = bool((row.get("settings") or {}).get("paused"))
    return Result(f"“{_mission_name(row)}”: uploads {'paused' if on else 'on'}.",
                  "Paused the mission" if on else "Resumed the mission",
                  {"links": [{"label": "Missions", "href": "#/missions"}]})


# Settings ClipForge AI may change, with the owner's OK: editing choices only. Publishing rules, accounts, spending
# limits and daily targets stay on their own pages, changed by the owner there.
SETTING_NAMES = dict(_SETTINGS_WORDS)


def _which_setting(text: str) -> str:
    key = str(text or "").strip()
    if key in SETTING_NAMES:
        return key
    words = set(_said_words(key))
    scored = sorted(((len(words & set(_said_words(label))), k) for k, label in SETTING_NAMES.items()), reverse=True)
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        raise ToolError("Say which setting: " + ", ".join(SETTING_NAMES.values()) + ". Publishing, accounts, "
                        "spending limits and daily targets are changed by the owner on their own pages.")
    return scored[0][1]


def _setting_preview(ctx: Ctx, args: dict) -> dict:
    from .. import config

    key = _which_setting(args.get("setting", ""))
    try:
        clean = config.validate_settings({key: args.get("value")})
    except (TypeError, ValueError):
        clean = {}
    if key not in clean:
        raise ToolError(f"“{args.get('value')}” is not a choice for {SETTING_NAMES[key]}.")
    now = db.get_settings().get(key)
    if now == clean[key]:
        raise ToolError(f"{SETTING_NAMES[key]} is already {clean[key]}.")
    return {"label": f"Change {SETTING_NAMES[key]} from {now} to {clean[key]}",
            "detail": ["New projects use it; a project or clip you changed by hand keeps its own."],
            "blocked": "", "args": {"setting": key, "value": clean[key]}}


def _setting(ctx: Ctx, args: dict) -> Result:
    out = _api().put_settings({args["setting"]: args["value"]})
    return Result(f"{SETTING_NAMES.get(args['setting'], args['setting'])} is now {out.get(args['setting'])}.",
                  "Changed a setting", {"links": [{"label": "Settings → Defaults", "href": "#/settings/defaults"}]})


# ------------------------------------------------------------------ work the chat follows
def _work(kind: str, ref: str, label: str) -> dict:
    return {"kind": kind, "id": ref, "label": one_line(label, 80), "started": round(time.time(), 3)}


def work_owner(kind: str, ref: str) -> str | None:
    """The workspace a piece of work belongs to (None when it is not there): another workspace's work answers like
    work that is gone."""
    from ..cloud import ownership

    if kind == "project":
        return ownership.project_workspace(ref)
    if kind == "clip":
        return ownership.clip_workspace(ref)
    if kind == "post":
        clip = db.scalar("SELECT clip_id FROM scheduled_publications WHERE id = ?", (ref,))
        return ownership.clip_workspace(str(clip)) if clip else None
    j = db.fetch("worker_jobs", ref)
    if not j:
        return None
    if j.get("ref_type") == "clip":
        return ownership.clip_workspace(str(j.get("ref_id") or ""))
    if j.get("ref_type") == "project":
        return ownership.project_workspace(str(j.get("ref_id") or ""))
    return None


def work_state(kind: str, ref: str, ws: str | None = None) -> dict:
    """What a piece of work the chat started is doing now: {state: queued | running | completed | failed |
    canceled, progress 0-1, message, href}. The chat asks again every few seconds until the state is final. With
    `ws`, work of another workspace (or a job not tied to a clip or project) answers like work that is gone."""
    if ws is not None and work_owner(kind, ref) != ws:
        return {"state": "canceled", "progress": 0, "message": "It is not there any more.", "href": ""}
    if kind == "project":
        p = db.get_project(ref)
        if not p:
            return {"state": "canceled", "progress": 0, "message": "It is not there any more.", "href": ""}
        d = diagnose_project(p)
        state = {"done": "completed", "stalled": "failed"}.get(d["state"], d["state"])
        return {"state": state, "progress": float(p.get("progress") or 0), "message": d["why"],
                "href": f"#/project/{ref}"}
    if kind == "clip":
        c = db.get_clip(ref)
        if not c:
            return {"state": "canceled", "progress": 0, "message": "It is not there any more.", "href": ""}
        d = diagnose_clip(c)
        state = "completed" if c.get("status") == "ready" else (
            "canceled" if (c.get("error") or "") == "Cancelled" else
            "failed" if d["state"] in ("failed", "stalled") else d["state"])
        return {"state": state, "progress": float(c.get("progress") or 0), "message": d["why"],
                "href": f"#/clip/{ref}"}
    if kind == "post":
        item = db.fetch("scheduled_publications", ref)
        if not item:
            return {"state": "canceled", "progress": 0, "message": "It is not there any more.", "href": ""}
        status = item["status"]
        state = {"publishing": "running", "reconciling": "running", "published": "completed", "failed": "failed",
                 "blocked": "failed", "action_needed": "failed", "canceled": "canceled",
                 "replaced": "canceled"}.get(status, "queued")
        pub = db.get_publication(item["publication_id"]) if item.get("publication_id") else None
        return {"state": state, "progress": float((pub or {}).get("progress") or 0),
                "message": STATUS_WORDS.get(status, status) + (f" ({_label(item['planned_at'], _settings())})"
                                                               if status in ("approved", "awaiting_approval") and
                                                               item.get("planned_at") else ""),
                "href": f"#/post/{ref}"}
    if kind == "job":  # a job of the crew's queue (autopilot/queue.py), like the final check
        j = db.fetch("worker_jobs", ref)
        if not j:
            return {"state": "canceled", "progress": 0, "message": "It is not there any more.", "href": ""}
        result = j.get("result") if isinstance(j.get("result"), dict) else {}
        state = {"queued": "queued", "waiting": "queued", "retrying": "queued", "running": "running",
                 "completed": "completed", "failed": "failed", "canceled": "canceled"}.get(j["status"], "queued")
        said = result.get("message") or j.get("error") or j.get("wait_reason") or j.get("message") or ""
        target = f"#/clip/{j['ref_id']}" if j.get("ref_type") == "clip" else "#/office"
        return {"state": state, "progress": float(j.get("progress") or 0), "message": one_line(said, 200),
                "href": target}
    raise ToolError("Unknown kind of work.")


# ------------------------------------------------------------------ when the commands are offered
# Words that mean the owner may want one of these commands. A small model reads every tool's description on every
# turn, so the commands (about 3,400 characters) are offered only when the owner's recent words are about posts,
# work, clips' framing or text, missions or settings; any other turn reads the tool list as it was before them.
CUES = re.compile(r"\b(?:posts?|posting|posted|schedul\w*|upload\w*|publish\w*|times?|o'?clock|\d{1,2}(?::\d{2})?\s*"
                  r"(?:am|pm)|\d{1,2}:\d{2}|tonight|tomorrow|today|later|earlier|move|moving|reschedul\w*|cancel\w*|"
                  r"retry|again|clash\w*|conflict\w*|too close|overlap\w*|render\w*|crop\w*|fram\w*|zoom\w*|layout|"
                  r"face ?cam|centre|center|left|right|stuck|stall\w*|frozen|hang\w*|job|jobs|queue\w*|working|running|"
                  r"progress|restart\w*|stop\w*|fail\w*|error\w*|mission\w*|pause\w*|resume|setting\w*|titles?|"
                  r"hashtags?|caption\w*|post text|metadata|description|clips per|youtube|tiktok|crew|robots?|check\w*|"
                  r"review\w*|quality)\b", re.I)


def offered(tool_list: list[Tool], words: str) -> list[Tool]:
    """The tools for one answer: the commands only when `words` (the owner's message and the ones just before it)
    are about something they do."""
    if CUES.search(words or ""):
        return tool_list
    return [t for t in tool_list if t.name not in COMMANDS]


# ------------------------------------------------------------------ registering
TEXT = {"type": "string", "maxLength": 300}
POST = {"post": {"type": "string", "maxLength": 200}, "platform": {"type": "string", "enum": ["youtube", "tiktok"]},
        "account": {"type": "string", "maxLength": 120}}
POST_HELP = ("post: words from its title or video, or its time (\"18:30\", \"Nov 26\"); platform and account narrow "
             "it")
CLIP = {"project": TEXT, "clip": TEXT}
NOT_AGENTS = {"for_agents": False}

register(Tool("posts", "the owner's planned, uploading, failed and posted posts with their times (in the Autopilot "
              "time zone), accounts, problems and posts too close together; view: upcoming, problems or published",
              {"type": "object", "properties": {"words": TEXT, "view": {"type": "string", "enum": sorted(VIEWS)}}},
              _posts, "look", "Looked at your posts"))
register(Tool("work", "what ClipForge is working on: running, waiting, stalled and failed jobs (making clips, "
              "renders, uploads) with why and what to do next; words narrow it to one project or post",
              {"type": "object", "properties": {"words": TEXT}}, _work_list, "look", "Checked the work"))
register(Tool("missions", "the owner's missions and whether their uploads are paused",
              {"type": "object", "properties": {}}, _missions, "look", "Looked at your missions"))
register(Tool("reschedule_post", "move a planned post to another time. when: the clock time in the Autopilot time "
              "zone as 2026-11-26T18:30 (posts shows the zone and today's date), or nearest_free. " + POST_HELP,
              {"type": "object", "properties": {**POST, "when": {"type": "string", "maxLength": 40}},
               "required": ["when"]}, _reschedule, "change", "Move {post} to {when}", preview=_reschedule_preview,
              **NOT_AGENTS))
register(Tool("fix_post_conflicts", "move every post that is too close to another post on the same account to the "
              "nearest free time (one OK for all)",
              {"type": "object", "properties": {"platform": POST["platform"],
                                                "moves": {"type": "array", "items": {"type": "object"},
                                                          "maxItems": 40, "internal": True}}},
              _fix, "change", "Fix posts that are too close", preview=_fix_preview, **NOT_AGENTS))
register(Tool("cancel_upload", "cancel a post that is uploading now (nothing is posted). " + POST_HELP,
              {"type": "object", "properties": POST}, _cancel_upload, "change", "Cancel the upload of {post}",
              preview=_cancel_upload_preview, **NOT_AGENTS))
register(Tool("cancel_post", "take a planned post off the schedule so it is not posted. " + POST_HELP,
              {"type": "object", "properties": POST}, _cancel_post, "change", "Don't post {post}",
              preview=_cancel_post_preview, **NOT_AGENTS))
register(Tool("retry_post", "try a failed, held or canceled post again (it still needs a valid approval). "
              + POST_HELP, {"type": "object", "properties": POST}, _retry, "change", "Try {post} again",
              preview=_retry_preview, **NOT_AGENTS))
register(Tool("restart_work", "start a stalled, failed or stopped project (or one clip's render) again. project: its "
              "name; clip: its number or title words (for one render)",
              {"type": "object", "properties": {**CLIP, "kind": {"type": "string", "internal": True},
                                                "id": {"type": "string", "internal": True}}},
              _restart, "change", "Start {project} again", preview=_restart_preview, **NOT_AGENTS))
register(Tool("stop_work", "stop a project that is being made (or one clip's render)",
              {"type": "object", "properties": {**CLIP, "kind": {"type": "string", "internal": True},
                                                "id": {"type": "string", "internal": True}}},
              _stop, "change", "Stop {project}", preview=_stop_preview, **NOT_AGENTS))
register(Tool("regenerate_post_text", "write a new title, post text and hashtags for a clip from what is said in it "
              "(replaces the current ones)",
              {"type": "object", "properties": {**CLIP, "clip_id": {"type": "string", "internal": True}}},
              _regen, "change", "New post text for {clip}", preview=_regen_preview, **NOT_AGENTS))
register(Tool("adjust_framing", "change how a clip is framed (crop) and render it again. position: 0-100 (% from "
              "the left, a fixed crop); follow: auto, center, face, speaker or screen; layout: fill, fit, split "
              "(gameplay + face cam), pip, game or auto; zoom: 1 to 2.5; corner: left or right (pip face cam box)",
              {"type": "object", "properties": {
                  **CLIP, "position": {"type": "number", "minimum": 0, "maximum": 100},
                  "follow": {"type": "string", "enum": sorted(FOLLOW)},
                  "layout": {"type": "string", "enum": sorted(LAYOUT_WORDS)},
                  "zoom": {"type": "number", "minimum": 1, "maximum": 2.5},
                  "corner": {"type": "string", "enum": ["left", "right"]},
                  "clip_id": {"type": "string", "internal": True}, "edit": {"type": "object", "internal": True}}},
              _crop, "change", "Change the framing of {clip}", preview=_crop_preview, **NOT_AGENTS))
register(Tool("render_clip", "render a clip again (queued; the chat shows when it is done)",
              {"type": "object", "properties": CLIP}, _render, "make", "Queued a render", **NOT_AGENTS))
register(Tool("crew_check", "hand clips to the robot crew's final check (file, picture, sound, captions, cuts, text; "
              "fixable problems go back to the robot responsible). clip: one clip, or leave it out for the project's "
              "best clips", {"type": "object", "properties": CLIP}, _crew_check, "make", "Handed clips to the crew",
              **NOT_AGENTS))
register(Tool("crew_report", "what the robot crew found and decided for a project's clips (or one clip)",
              {"type": "object", "properties": CLIP}, _crew_report, "look", "Read the crew's reviews"))
register(Tool("pause_mission", "pause (paused true) or resume (paused false) one mission's uploads",
              {"type": "object", "properties": {"mission": TEXT, "paused": {"type": "boolean"}},
               "required": ["paused"]}, _pause, "change", "Pause {mission}", preview=_pause_preview, **NOT_AGENTS))
register(Tool("change_setting", "change one editing choice in Settings (clips per video, clip lengths, captions, "
              "framing, pauses, sound); setting: its name, value: the new value as text (5, on, off, bold)",
              {"type": "object", "properties": {"setting": TEXT, "value": {"type": "string", "maxLength": 40}},
               "required": ["setting", "value"]}, _setting, "change", "Change {setting} to {value}",
              preview=_setting_preview, **NOT_AGENTS))

COMMANDS = frozenset(("posts", "work", "missions", "crew_check", "crew_report", "reschedule_post", "fix_post_conflicts",
                      "cancel_upload", "cancel_post", "retry_post", "restart_work", "stop_work", "regenerate_post_text",
                      "adjust_framing", "render_clip", "pause_mission", "change_setting"))
