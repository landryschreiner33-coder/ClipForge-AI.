"""ClipForge AI's commands: what the owner can ask it to do with posts, work, clips, missions and settings.

Every command runs the very function the app's own button runs (the route functions in api.py and
autopilot/routes.py), so the same checks, time zone, gap between posts and approval rules apply, and an action the
app refuses is refused here in the app's own words. Changes wait for the owner's OK on a card that says exactly what
will happen (tools.WAITS); a card for several posts lists each one (a batch change is approved once, as a whole).
With Settings → ClipForge AI → "Act without asking" on (the default, Landry's wish of Nov 26) a command marked
`alone` runs at once and the card shows it done (assistant._offer); deleting always waits for the OK. ClipForge AI
approves and posts YouTube posts (approve_post) with the post page's own checks; a TikTok post always waits for the
owner's OK on its page (TikTok's rules for apps: a preview and the owner's own privacy choice on every post).

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
    show = "\n".join(lines[1:])  # the owner's list, without the model's notes
    if clash and view != "published":
        lines.append(f"{len(clash)} post(s) are too close to another on the same account: fix_post_conflicts moves "
                     "them to the nearest free times.")
    return Result("\n".join(lines), f"Looked at your posts ({len(rows)})",
                  {"links": [{"label": "Missions → Schedule", "href": "#/missions"}]}, show=show)


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


EDITABLE = ("awaiting_approval", "approved", "failed", "action_needed", "blocked", "canceled")  # scheduler.edit


def _tag_list(value, platform: str) -> list[str]:
    """Hashtags as the owner said them ("#fishing #bass", ["fishing", "bass"]) in the form the platform keeps:
    YouTube tags without #, TikTok hashtags with it."""
    words = value if isinstance(value, list) else re.split(r"[\s,]+", str(value or ""))
    out: list[str] = []
    for w in words:
        w = re.sub(r"[^\w]", "", str(w).strip().lstrip("#"), flags=re.UNICODE)[:40]
        tag = ("#" + w) if platform == "tiktok" else w
        if w and tag.lower() not in {t.lower() for t in out}:
            out.append(tag)
    return out[:10]


def _edit_post_fields(item: dict, args: dict) -> tuple[dict, list[str]]:
    fields, words = {}, []
    tiktok = item["platform"] == "tiktok"
    if args.get("title") is not None and str(args["title"]).strip():
        if tiktok:   # TikTok posts only the caption
            raise ToolError("A TikTok post has no title of its own: change its caption (description) instead.")
        fields["title"] = str(args["title"]).strip()[:100]
        words.append(f"title “{fields['title']}”")
    if args.get("description") is not None:
        fields["description"] = str(args["description"]).strip()[:2200 if tiktok else 4000]
        words.append(("caption “" if tiktok else "description “") + one_line(fields["description"], 80) + "”"
                     if fields["description"] else "no description")
    if args.get("hashtags") is not None:
        fields["tags"] = _tag_list(args["hashtags"], item["platform"])
        words.append("hashtags " + (" ".join(("#" + t.lstrip("#")) for t in fields["tags"]) or "none"))
        if tiktok:   # TikTok's hashtags are the ones in the caption it posts: they go at its end
            caption = str(fields.get("description", item.get("description") or ""))
            caption = re.sub(r"(\s*#\w+)+\s*$", "", caption, flags=re.UNICODE).rstrip()
            fields["description"] = (caption + " " + " ".join(fields["tags"])).strip()[:2200]
    if not fields:
        raise ToolError("Say what to change: title, description or hashtags.")
    return fields, words


def _edit_post_preview(ctx: Ctx, args: dict) -> dict:
    item = find_post(args, EDITABLE, "can be edited")
    fields, words = _edit_post_fields(item, args)
    platform = PLATFORM_NAMES.get(item["platform"], item["platform"])
    return {"label": f"Change “{_post_name(item)}” on {platform}: " + "; ".join(words),
            "detail": ["The same change as editing the text on its page."] +
                      (["It was approved: approve it again after this change."] if item["status"] == "approved"
                       else []),
            "blocked": "", "args": {"post": item["id"], **{k: args[k] for k in ("title", "description", "hashtags")
                                                          if args.get(k) is not None}}}


def _edit_post(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    item = db.fetch("scheduled_publications", str(args.get("post") or ""))
    if not item:
        raise ToolError("That post is not there any more.")
    fields, _words = _edit_post_fields(item, args)
    try:
        out = routes.edit_item(item["id"], routes.EditBody(**fields))
    except HTTPException as exc:
        raise _http(exc) from exc
    tags = " ".join(("#" + t.lstrip("#")) for t in out.get("tags") or [])
    text = (f"“{_post_name(out)}” now has the title “{out.get('title')}”" + (f" and hashtags {tags}" if tags else "")
            + f"; it is {STATUS_WORDS.get(out['status'], out['status'])}.")
    if out.get("warnings"):
        text += " Check: " + one_line(out["warnings"][0], 160)
    return Result(text, "Changed the post's text", {"links": _post_links(out)})


def _approve_problems(item: dict, settings: dict) -> list[str]:
    """What stands between this post and an approval ClipForge AI may give for the owner: the post page's own list
    (PostReview.tsx `missing`) for a YouTube post. TikTok asks for the owner's OK on every post."""
    from ..autopilot import gate, rights
    from ..autopilot.targets import account_view, usable

    if item["platform"] == "tiktok":
        return ["TikTok's rules for apps need your own OK on every post, with its preview and your own privacy "
                "choice: approve it on its page"]
    problems = []
    acc = db.get_connection(account_view(item)["connection_id"]) if account_view(item)["connection_id"] else None
    if not usable(acc):
        problems.append("connect YouTube again (Settings → Accounts)")
    if not str(item.get("title") or "").strip():
        problems.append("it has no title")
    if len(str(item.get("title") or "")) > 100:
        problems.append("its title is longer than 100 characters")
    if type((item.get("options") or {}).get("made_for_kids")) is not bool:
        problems.append("answer “made for kids” on its page (YouTube asks you)")
    if not item.get("privacy"):
        problems.append("choose who can see it on its page")
    clip = db.get_clip(item["clip_id"]) or {}
    rep = gate.report_for(clip) if clip else None
    if rep and rep["status"] == "failed":
        problems.append("its clip failed the final check (" + "; ".join(rep.get("blockers") or [])[:120] + ")")
    review = rights.review_info(item, settings)
    if review.get("required") and not review.get("confirmed"):
        problems.append("say why you can reuse this clip on its page")
    return problems


def _approve_preview(ctx: Ctx, args: dict) -> dict:
    from ..autopilot.targets import item_account

    settings = _settings()
    now = bool(args.get("now"))
    item = find_post(args, ("awaiting_approval", "failed", *(("approved",) if now else ())), "waits for approval"
                     if not now else "can be approved or posted")
    platform = PLATFORM_NAMES.get(item["platform"], item["platform"])
    # an approved post that goes out now is still checked when it is a TikTok post: ClipForge AI never posts there
    problems = [] if item["status"] == "approved" and item["platform"] != "tiktok" \
        else _approve_problems(item, settings)
    if now and settings.get("autopilot_publishing_paused"):
        problems.append("publishing is paused (Office → bottom bar)")
    tags = " ".join(("#" + t.lstrip("#")) for t in item.get("tags") or [])
    detail = [f"Title: “{one_line(item.get('title'), 100)}”",
              *([f"Text: “{one_line(item.get('description'), 140)}”"] if item.get("description") else []),
              *([f"Hashtags: {tags}"] if tags else []),
              f"On {platform}, {_account(item)[1]}, for: {item.get('privacy') or 'not chosen'}.",
              ("It goes out now." if now else f"It goes out at its time, {_label(item.get('planned_at'), settings)}"
               + ("" if settings.get("autopilot_auto_publish") else " once you press Publish now (automatic "
                  "publishing is off)") + ".")]
    verb = "Post" if now and item["status"] == "approved" else "Approve and post" if now else "Approve"
    return {"label": f"{verb} “{_post_name(item)}” on {platform} ({_account(item)[1]})", "detail": detail,
            "blocked": ("To approve it: " + "; ".join(problems) + ".") if problems else "",
            # the account the card shows: approving checks the post still goes there (as the post page does)
            "args": {"post": item["id"], "now": now, "account": item_account(item)}}


def _approve(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes
    from ..autopilot.targets import item_account

    item = db.fetch("scheduled_publications", str(args.get("post") or ""))
    if not item:
        raise ToolError("That post is not there any more.")
    problems = [] if item["status"] == "approved" and item["platform"] != "tiktok" \
        else _approve_problems(item, _settings())
    if problems:
        raise ToolError("To approve it: " + "; ".join(problems) + ".")
    shown = str(args.get("account") or "")
    if shown and shown != item_account(item):
        raise ToolError("Another account is connected now than the one this was for. Check the post on its page.")
    out = item
    try:
        if item["status"] != "approved":
            opts = item.get("options") or {}
            out = routes.approve_as(item["id"], routes.ApproveBody(
                confirm=True, title=item.get("title"), description=item.get("description") or "",
                tags=list(item.get("tags") or []), privacy=item.get("privacy"),
                made_for_kids=opts.get("made_for_kids"), expected_account_id=shown or item_account(item)),
                "ClipForge AI")
        if args.get("now"):
            out = routes.publish_now(item["id"])
    except HTTPException as exc:
        raise _http(exc) from exc
    except ValueError as exc:  # PublishError and the scheduler's own reasons
        raise ToolError(str(exc)) from exc
    text = f"“{_post_name(out)}” is {STATUS_WORDS.get(out['status'], out['status'])}"
    if out["status"] == "approved" and not _settings().get("autopilot_auto_publish"):
        text += "; automatic publishing is off, so it waits for Publish now (approve_post with now)"
    if out.get("warnings"):
        text += ". Check: " + one_line(out["warnings"][0], 160)
    return Result(text + ".", "Posting it now" if args.get("now") else "Approved it",
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
                  {"links": [{"label": "Missions → Activity", "href": "#/missions/activity"}]},
                  show="\n".join([head, *lines[:LIST_MAX + 4]]))


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
    # making a project's clips again from the start replaces the clips it has (as Make clips again does): that
    # deletes them, so it always waits for the OK
    made = len(db.list_clips(row["id"])) if kind == "project" else 0
    return {"label": what[0].upper() + what[1:], "detail": [f"Now: {d['state']}: {d['why']}."]
            + (["It is stopped first; press OK again once it has stopped."] if d["state"] == "stalled"
               and _queue()[0] == row["id"] else [])
            + ([f"The {made} clip{'s' if made != 1 else ''} it has now are replaced: their edits and versions are "
                "lost. Posts already on YouTube or TikTok stay there."] if made else []),
            "blocked": "", "ask": bool(made), "args": {"kind": kind, "id": row["id"]}}


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


def _clip_text_preview(ctx: Ctx, args: dict) -> dict:
    p, c, n = _find_clip(ctx.ws, args.get("project", ""), args.get("clip", ""), ctx.project_id)
    words, keep = [], {}
    if str(args.get("title") or "").strip():
        keep["title"] = str(args["title"]).strip()
        words.append(f"title “{keep['title']}”")
    if args.get("hashtags") is not None:
        keep["hashtags"] = " ".join("#" + t for t in _tag_list(args["hashtags"], "youtube"))
        words.append("hashtags " + (keep["hashtags"] or "none"))
    if str(args.get("hook") or "").strip():
        keep["hook"] = str(args["hook"]).strip()
        words.append(f"hook “{keep['hook']}”")
    if not keep:
        raise ToolError("Say the title, hashtags or hook to use.")
    return {"label": f"Use your own words for clip {n} of “{p['name']}”: " + "; ".join(words),
            "detail": ["The same as typing them in the clip editor's Post tab. Posts already planned keep their own "
                       "text (edit_post changes those)."],
            "blocked": "", "args": {"clip_id": c["id"], **keep}}


def _clip_text(ctx: Ctx, args: dict) -> Result:
    api = _api()
    clip_id = str(args.get("clip_id") or "")
    try:
        tags = None if args.get("hashtags") is None else ["#" + t for t in _tag_list(args["hashtags"], "youtube")]
        out = api.patch_clip(clip_id, api.ClipPatch(title=args.get("title"), hashtags=tags, hook=args.get("hook")))
    except HTTPException as exc:
        raise _http(exc) from exc
    post = out.get("post") or {}
    return Result(f"Clip “{one_line(post.get('title') or out.get('title'), 80)}” now uses your words; hashtags: "
                  f"{' '.join(post.get('hashtags') or out.get('hashtags') or []) or 'none'}.", "Changed the clip's text",
                  {"links": [{"label": "Open the clip", "href": f"#/clip/{clip_id}"}]})


MIN_CLIP_S = 3.0  # a trim never leaves less than this


def _clip_edit(c: dict, p: dict, args: dict) -> tuple[dict, list[str], bool | None]:
    """(the clip editor's change, the owner's words for it, keep/drop or None) from edit_clip's arguments."""
    from .. import config
    from ..pipeline.blueprint import GAIN_RANGE, SPEED_RANGE

    was = dict(c.get("edit") or {})
    start, end = float(was.get("start", c.get("start") or 0)), float(was.get("end", c.get("end") or 0))
    edit, words = {}, []
    if args.get("cut_start") or args.get("cut_end"):
        new_start = max(0.0, start + float(args.get("cut_start") or 0))
        new_end = end - float(args.get("cut_end") or 0)
        total = float(p.get("duration") or 0)
        if total > 0:
            new_end = min(new_end, total)
        if new_end - new_start < MIN_CLIP_S:
            raise ToolError(f"That would leave {max(0.0, new_end - new_start):.1f} seconds: a clip needs at least "
                            f"{MIN_CLIP_S:.0f}. It is {end - start:.1f} seconds now.")
        edit.update(start=round(new_start, 2), end=round(new_end, 2))
        words.append(f"from {new_start:.1f}s to {new_end:.1f}s ({new_end - new_start:.1f} seconds, was "
                     f"{end - start:.1f})")
    if args.get("captions") is not None:
        edit["captions_enabled"] = bool(args["captions"])
        words.append("captions " + ("on" if args["captions"] else "off"))
    if args.get("caption_style"):
        if args["caption_style"] not in config.CAPTION_STYLES:
            raise ToolError("Caption styles: " + ", ".join(config.CAPTION_STYLES) + ".")
        edit["caption_style"] = args["caption_style"]
        words.append(f"caption style {args['caption_style'].replace('_', ' ')}")
    if args.get("caption_size") is not None:
        edit["caption_size"] = round(max(0.6, min(1.6, float(args["caption_size"]) / 100)), 2)
        words.append(f"captions at {edit['caption_size'] * 100:.0f}%")
    if args.get("speed") is not None:
        edit["speed"] = round(max(SPEED_RANGE[0], min(SPEED_RANGE[1], float(args["speed"]))), 2)
        words.append(f"speed {edit['speed']}×")
    if args.get("volume_db") is not None:
        edit["gain_db"] = round(max(GAIN_RANGE[0], min(GAIN_RANGE[1], float(args["volume_db"]))) * 2) / 2
        words.append(f"sound {edit['gain_db']:+g} dB")
    if args.get("pauses"):
        if args["pauses"] not in config.SILENCE_MODES:
            raise ToolError("Pause cutting: " + ", ".join(config.SILENCE_MODES) + ".")
        edit["silence"] = args["pauses"]
        words.append(f"pause cutting {args['pauses']}")
    if args.get("fillers") is not None:
        edit["remove_fillers"] = bool(args["fillers"])
        words.append("“um” and “uh” " + ("cut" if args["fillers"] else "kept"))
    keep = None if args.get("keep") is None else bool(args["keep"])
    if keep is not None:
        words.append("kept in the project's picks" if keep else "taken out of the project's picks")
    if not edit and keep is None:
        raise ToolError("Say what to change: cut_start, cut_end, captions, caption_style, caption_size, speed, "
                        "volume_db, pauses, fillers or keep.")
    return edit, words, keep


def _edit_clip_preview(ctx: Ctx, args: dict) -> dict:
    p, c, n = _find_clip(ctx.ws, args.get("project", ""), args.get("clip", ""), ctx.project_id)
    edit, words, keep = _clip_edit(c, db.get_project(p["id"]) or p, args)
    busy = c.get("status") in ("queued", "rendering")
    return {"label": f"Edit clip {n} of “{p['name']}”: " + ", ".join(words),
            "detail": ["The same change as the clip editor."] + ([] if not edit else [
                "Then it is rendered again." if not busy else
                "It is rendering now: the change is used the next time it renders."]),
            "blocked": "", "args": {"clip_id": c["id"], "edit": edit, **({"keep": keep} if keep is not None else {})}}


def _edit_clip(ctx: Ctx, args: dict) -> Result:
    api = _api()
    clip_id = str(args.get("clip_id") or "")
    edit = dict(args.get("edit") or {})
    keep = args.get("keep")
    queued = False
    try:
        api.patch_clip(clip_id, api.ClipPatch(edit=edit or None, selected=None if keep is None else bool(keep)))
        if edit:
            try:
                api.rerender(clip_id)
                queued = True
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
    except HTTPException as exc:
        raise _http(exc) from exc
    out = api.get_clip(clip_id)
    name = f"“{one_line(out.get('title') or 'the clip', 50)}”"
    text = f"Saved the change to {name}" + (" and queued its render." if queued else
                                            "; it is rendering now, so render it again after." if edit else ".")
    return Result(text, "Edited the clip", {"links": [{"label": "Open the clip", "href": f"#/clip/{clip_id}"}],
                                            "work": [_work("clip", clip_id, f"Render {name}")] if queued else []})


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
                  "Looked at your missions", {"links": [{"label": "Missions", "href": "#/missions"}]},
                  show="\n".join(lines))


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


# ------------------------------------------------------------------ new work: clips from a link, missions, stories
_LINK = re.compile(r"https?://[^\s<>\"']+", re.I)


def _link(args: dict) -> str:
    found = _LINK.search(str(args.get("link") or ""))
    if not found:
        raise ToolError("Give the video's link (https://…).")
    return found.group(0).rstrip(".,;)")


def _make_clips_preview(ctx: Ctx, args: dict) -> dict:
    url = _link(args)
    return {"label": f"Make clips from {one_line(url, 90)}",
            "detail": ["ClipForge downloads the video and makes clips with your Settings → Defaults, like Make clips "
                       "→ Paste a link. Use only videos you may reuse."],
            "blocked": "", "args": {"link": url}}


def _make_clips(ctx: Ctx, args: dict) -> Result:
    api = _api()
    try:
        out = api.create_from_url(api.UrlImport(url=_link(args)))
    except HTTPException as exc:
        raise _http(exc) from exc
    name = f"“{one_line(out.get('name'), 60)}”"
    return Result(f"Started making clips from that link as the project {name}; the chat shows when they are ready.",
                  "Started making clips", {"work": [_work("project", out["id"], f"Clips from {name}")],
                                           "links": [{"label": "Open the project", "href": f"#/project/{out['id']}"}]})


def _mission_preview(ctx: Ctx, args: dict) -> dict:
    url = _link(args)
    live = bool(args.get("live"))
    return {"label": f"{'Clip the live stream' if live else 'Add the mission'} {one_line(url, 90)}",
            "detail": ["Like Missions → " + ("Live streams" if live else "Add a video") + " with Make clips only: "
                       "ClipForge makes the clips; turning on uploads for it stays on Missions, where you confirm "
                       "the channels and your right to reuse it."],
            "blocked": "", "args": {"link": url, "live": live}}


def _mission(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    try:
        out = routes.submit_link(routes.SubmissionIn(url=_link(args), auto_upload=False, live=bool(args.get("live"))))
    except HTTPException as exc:
        raise _http(exc) from exc
    title = one_line((out.get("source") or {}).get("title") or out.get("title") or _link(args), 70)
    return Result(f"Added “{title}” to Missions (clips only). It shows on Missions as it is checked and clipped.",
                  "Added a mission", {"links": [{"label": "Missions", "href": "#/missions"}]})


def _story_preview(ctx: Ctx, args: dict) -> dict:
    from ..makers import writer

    idea = str(args.get("idea") or "").strip()
    if len(idea) < 4:
        raise ToolError("Say what the story is about.")
    tone = args.get("tone") if args.get("tone") in writer.STORY_TONES else "drama"
    return {"label": f"Write a Text Story: “{one_line(idea, 90)}”",
            "detail": [f"A new story on Text Stories, written in a {tone} tone, with backgrounds ClipForge picks from "
                       "your videos. You can change the script, voice and background there, then export it."],
            "blocked": "", "args": {"idea": idea, "tone": tone}}


def _story(ctx: Ctx, args: dict) -> Result:
    from ..makers import textstory

    idea = str(args.get("idea") or "").strip()
    try:
        story = textstory.create(ctx.ws, name=one_line(idea, 60))
        try:
            story = textstory.auto_backgrounds(story)
        except textstory.StoryError:
            pass  # no usable videos: the story keeps its moving colour
        story = textstory.start(story, "write", {"topic": idea, "tone": args.get("tone") or "drama",
                                                 "length": "standard", "change": ""})
    except textstory.StoryError as exc:
        raise ToolError(str(exc)) from exc
    return Result(f"Started writing the story “{one_line(idea, 60)}” on Text Stories; open it to hear and export it.",
                  "Started a Text Story", {"links": [{"label": "Open the story", "href": f"#/stories/{story['id']}"}]})


AUTOPILOT_ACTIONS = {"on": "Turn Autopilot on", "off": "Turn Autopilot off (queued work waits)",
                     "stop_all": "Stop all jobs (renders, uploads, Autopilot) until you resume",
                     "resume": "Allow jobs again after Stop all", "auto_publish_off":
                     "Turn automatic publishing off (posts wait for an approval)"}


def _autopilot_preview(ctx: Ctx, args: dict) -> dict:
    action = args.get("action")
    if action not in AUTOPILOT_ACTIONS:
        raise ToolError("Say on, off, stop_all, resume or auto_publish_off. Turning automatic publishing on stays "
                        "on Missions, where you agree to its rules.")
    s = _settings()
    if action == "on" and s.get("autopilot_enabled"):
        raise ToolError("Autopilot is already on.")
    if action == "off" and not s.get("autopilot_enabled"):
        raise ToolError("Autopilot is already off.")
    return {"label": AUTOPILOT_ACTIONS[action], "detail": ["The same as the button on Missions and the Office."],
            "blocked": "", "args": {"action": action}}


def _autopilot(ctx: Ctx, args: dict) -> Result:
    from ..autopilot import routes

    action = args.get("action")
    try:
        if action in ("on", "off"):
            routes.enable(routes.EnableBody(enabled=action == "on"))
            said = f"Autopilot is {action}."
        elif action == "stop_all":
            out = routes.stop_all()
            said = (f"Stopped all jobs: {out['canceled']} waiting canceled, {out['stopping']} running stopping, "
                    f"{out['manual']} renders or uploads stopped. Nothing new starts until resume.")
        elif action == "resume":
            routes.resume()
            said = "Jobs are allowed again."
        else:
            back = routes.auto_publish_off("youtube").get("returned_to_review") or 0
            said = "Automatic publishing is off: new posts wait for an approval" + (
                f"; {back} post(s) it had approved wait for one again." if back else ".")
    except HTTPException as exc:
        raise _http(exc) from exc
    return Result(said, AUTOPILOT_ACTIONS.get(action, "Autopilot"), {"links": [{"label": "Missions",
                                                                                 "href": "#/missions"}]})


# Settings ClipForge AI may change: editing choices and the posting rules (gap, hours, posts a day, time zone).
# Accounts, spending limits, the AI model and automatic publishing stay on their own pages, changed by the owner.
PUBLISHING_WORDS = (
    ("autopilot_min_gap_minutes", "Minutes between posts on one account"),
    ("autopilot_active_start", "Earliest posting hour (0-23)"), ("autopilot_active_end", "Latest posting hour (1-24)"),
    ("autopilot_youtube_daily_limit", "YouTube posts a day at most"),
    ("autopilot_tiktok_daily_limit", "TikTok posts a day at most"), ("autopilot_timezone", "Posting time zone"))
SETTING_NAMES = dict(_SETTINGS_WORDS) | dict(PUBLISHING_WORDS)


def _which_setting(text: str) -> str:
    key = str(text or "").strip()
    if key in SETTING_NAMES:
        return key
    words = set(_said_words(key))
    scored = sorted(((len(words & set(_said_words(label))), k) for k, label in SETTING_NAMES.items()), reverse=True)
    if not scored or scored[0][0] == 0 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        raise ToolError("Say which setting: " + ", ".join(SETTING_NAMES.values()) + ". Accounts, spending limits, "
                        "the AI model and automatic publishing are changed by the owner on their own pages.")
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
    publishing = key in dict(PUBLISHING_WORDS)
    return {"label": f"Change {SETTING_NAMES[key]} from {now} to {clean[key]}",
            "detail": ["Posts planned from now on follow it; posts already planned keep their times." if publishing
                       else "New projects use it; a project or clip you changed by hand keeps its own."],
            "blocked": "", "args": {"setting": key, "value": clean[key]}}


def _setting(ctx: Ctx, args: dict) -> Result:
    out = _api().put_settings({args["setting"]: args["value"]})
    page = ({"label": "Settings → Advanced → Autopilot posting", "href": "#/settings/advanced"} if args["setting"] in
            dict(PUBLISHING_WORDS) else {"label": "Settings → Defaults", "href": "#/settings/defaults"})
    return Result(f"{SETTING_NAMES.get(args['setting'], args['setting'])} is now {out.get(args['setting'])}.",
                  "Changed a setting", {"links": [page]})


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
# Words that mean the owner may want one of these commands. A small model (the built-in one, or one run by Ollama)
# reads every tool's description on every turn, so for it the commands (about 6,000 characters) are offered only
# when the owner's recent words are about posts, work, clips, missions, stories or settings; any other turn reads
# the tool list as it was before them. A bigger model always has them all.
CUES = re.compile(r"\b(?:posts?|posting|posted|schedul\w*|upload\w*|publish\w*|times?|o'?clock|\d{1,2}(?::\d{2})?\s*"
                  r"(?:am|pm)|\d{1,2}:\d{2}|at \d{1,2}|tonight|tomorrow|today|later|earlier|move|moving|reschedul\w*|"
                  r"push\w*|shift\w*|delay\w*|postpone\w*|bring (?:it )?forward|monday|tuesday|wednesday|thursday|"
                  r"friday|saturday|sunday|weekend|january|february|march|april|may|june|july|august|september|"
                  r"october|november|december|cancel\w*|kill|don'?t (?:post|send|upload)|retry|again|clash\w*|"
                  r"conflict\w*|too close|overlap\w*|render\w*|crop\w*|fram\w*|zoom\w*|layout|face ?cam|centre|center|"
                  r"left|right|stuck|stall\w*|frozen|hang\w*|job|jobs|queue\w*|working|running|progress|restart\w*|"
                  r"stop\w*|fail\w*|error\w*|mission\w*|pause\w*|resume|setting\w*|titles?|hashtags?|tags?|hooks?|"
                  r"caption\w*|post text|metadata|description|clips?|clips per|videos?|youtube|tiktok|crew|robots?|"
                  r"check\w*|review\w*|quality|trim\w*|cut\w*|shorter|longer|seconds?|length|speed\w*|faster|"
                  r"slower|louder|quieter|volume|sound|turn (?:it )?(?:on|off)|switch (?:it )?(?:on|off)|autopilot|"
                  r"approv\w*|go live|links?|https?://\S+|story|stories|keep|drop|gap|hours?|time ?zone|limit)\b",
                  re.I)


def offered(tool_list: list[Tool], words: str, settings: dict | None = None) -> list[Tool]:
    """The tools for one answer: all of them for a bigger model; for a small one, the commands only when `words`
    (the owner's message and the ones just before it) are about something they do."""
    provider = (settings or {}).get("ai_provider") if settings is not None else None
    if provider and provider not in ("builtin", "ollama", "heuristic"):
        return tool_list
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
ALONE = {"for_agents": False, "alone": True}  # a change made at once when the owner lets ClipForge AI act alone

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
              **ALONE))
register(Tool("fix_post_conflicts", "move every post that is too close to another post on the same account to the "
              "nearest free time (one OK for all)",
              {"type": "object", "properties": {"platform": POST["platform"],
                                                "moves": {"type": "array", "items": {"type": "object"},
                                                          "maxItems": 40, "internal": True}}},
              _fix, "change", "Fix posts that are too close", preview=_fix_preview, **ALONE))
register(Tool("cancel_upload", "cancel a post that is uploading now (nothing is posted). " + POST_HELP,
              {"type": "object", "properties": POST}, _cancel_upload, "change", "Cancel the upload of {post}",
              preview=_cancel_upload_preview, **ALONE))
register(Tool("cancel_post", "take a planned post off the schedule so it is not posted. " + POST_HELP,
              {"type": "object", "properties": POST}, _cancel_post, "change", "Don't post {post}",
              preview=_cancel_post_preview, **ALONE))
register(Tool("retry_post", "try a failed, held or canceled post again (it still needs a valid approval). "
              + POST_HELP, {"type": "object", "properties": POST}, _retry, "change", "Try {post} again",
              preview=_retry_preview, **ALONE))
register(Tool("restart_work", "start a stalled, failed or stopped project (or one clip's render) again. project: its "
              "name; clip: its number or title words (for one render)",
              {"type": "object", "properties": {**CLIP, "kind": {"type": "string", "internal": True},
                                                "id": {"type": "string", "internal": True}}},
              _restart, "change", "Start {project} again", preview=_restart_preview, **ALONE))
register(Tool("stop_work", "stop a project that is being made (or one clip's render)",
              {"type": "object", "properties": {**CLIP, "kind": {"type": "string", "internal": True},
                                                "id": {"type": "string", "internal": True}}},
              _stop, "change", "Stop {project}", preview=_stop_preview, **ALONE))
register(Tool("regenerate_post_text", "write a new title, post text and hashtags for a clip from what is said in it "
              "(replaces the current ones)",
              {"type": "object", "properties": {**CLIP, "clip_id": {"type": "string", "internal": True}}},
              _regen, "change", "New post text for {clip}", preview=_regen_preview, **ALONE))
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
              _crop, "change", "Change the framing of {clip}", preview=_crop_preview, **ALONE))
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
               "required": ["paused"]}, _pause, "change", "Pause {mission}", preview=_pause_preview, **ALONE))
register(Tool("change_setting", "change one setting: an editing choice (clips per video, clip lengths, captions, "
              "framing, pauses, sound) or a posting rule (minutes between posts, earliest and latest posting hour, "
              "posts a day, time zone); setting: its name, value: the new value as text (5, on, off, bold)",
              {"type": "object", "properties": {"setting": TEXT, "value": {"type": "string", "maxLength": 40}},
               "required": ["setting", "value"]}, _setting, "change", "Change {setting} to {value}",
              preview=_setting_preview, **ALONE))

register(Tool("edit_post", "change a planned post's own title, description or hashtags (the words you are given, "
              "as they are). " + POST_HELP,
              {"type": "object", "properties": {**POST, "title": TEXT, "description": {"type": "string",
                                                                                     "maxLength": 4000},
                                                "hashtags": TEXT}},
              _edit_post, "change", "Change the text of {post}", preview=_edit_post_preview, **ALONE))
register(Tool("approve_post", "approve a post that waits for approval so it goes out at its time; now: true to post "
              "it right away (also an approved one). YouTube only: TikTok posts need the owner's OK on their page. "
              + POST_HELP,
              {"type": "object", "properties": {**POST, "now": {"type": "boolean"},
                                                "account": {"type": "string", "internal": True}}},
              _approve, "change", "Approve {post}", preview=_approve_preview, **ALONE))
register(Tool("set_clip_text", "use the owner's own title, hashtags or hook for a clip (exactly their words)",
              {"type": "object", "properties": {**CLIP, "title": TEXT, "hashtags": TEXT, "hook": TEXT,
                                                "clip_id": {"type": "string", "internal": True}}},
              _clip_text, "change", "Use your words for {clip}", preview=_clip_text_preview, **ALONE))
register(Tool("edit_clip", "edit a clip like the clip editor and render it again. cut_start / cut_end: seconds to cut "
              "off its start / end (negative makes it longer); captions: true/false; caption_style: clean, bold, "
              "high_energy or minimal; caption_size: 60 to 160 (%); speed: 0.8 to 1.25; volume_db: -12 to 12; "
              "pauses: off, light or aggressive; fillers: true cuts “um”; keep: false takes it out of the picks",
              {"type": "object", "properties": {
                  **CLIP, "cut_start": {"type": "number", "minimum": -60, "maximum": 600},
                  "cut_end": {"type": "number", "minimum": -60, "maximum": 600}, "captions": {"type": "boolean"},
                  "caption_style": {"type": "string", "enum": ["bold", "clean", "high_energy", "minimal"]},
                  "caption_size": {"type": "number", "minimum": 60, "maximum": 160},
                  "speed": {"type": "number", "minimum": 0.8, "maximum": 1.25},
                  "volume_db": {"type": "number", "minimum": -12, "maximum": 12},
                  "pauses": {"type": "string", "enum": ["aggressive", "light", "off"]}, "fillers": {"type": "boolean"},
                  "keep": {"type": "boolean"}, "clip_id": {"type": "string", "internal": True},
                  "edit": {"type": "object", "internal": True}}},
              _edit_clip, "change", "Edit {clip}", preview=_edit_clip_preview, **ALONE))
register(Tool("make_clips", "make clips from a video link the owner gives (a new clips project)",
              {"type": "object", "properties": {"link": TEXT}, "required": ["link"]}, _make_clips, "change",
              "Make clips from {link}", preview=_make_clips_preview, **ALONE))
register(Tool("start_mission", "add a video link (or a live stream: live true) to Missions so ClipForge clips it; "
              "uploads for it are turned on by the owner on Missions",
              {"type": "object", "properties": {"link": TEXT, "live": {"type": "boolean"}}, "required": ["link"]},
              _mission, "change", "Add {link} to Missions", preview=_mission_preview, **ALONE))
register(Tool("write_text_story", "start a new Text Story (a story read over background video) about the owner's "
              "idea; tone: drama, funny, scary, wholesome or the like",
              {"type": "object", "properties": {"idea": {"type": "string", "maxLength": 600},
                                                "tone": {"type": "string", "maxLength": 20}}, "required": ["idea"]},
              _story, "change", "Write a story about {idea}", preview=_story_preview, **ALONE))
register(Tool("autopilot", "Autopilot and the job controls. action: on, off, stop_all (stop every job until "
              "resume), resume, or auto_publish_off",
              {"type": "object", "properties": {"action": {"type": "string", "enum": sorted(AUTOPILOT_ACTIONS)}},
               "required": ["action"]}, _autopilot, "change", "Autopilot: {action}", preview=_autopilot_preview,
              **ALONE))

COMMANDS = frozenset(("posts", "work", "missions", "crew_check", "crew_report", "reschedule_post", "fix_post_conflicts",
                      "cancel_upload", "cancel_post", "retry_post", "restart_work", "stop_work", "regenerate_post_text",
                      "adjust_framing", "render_clip", "pause_mission", "change_setting", "edit_post", "approve_post",
                      "set_clip_text", "edit_clip", "make_clips", "start_mission", "write_text_story", "autopilot"))
