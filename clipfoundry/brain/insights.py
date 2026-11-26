"""How the owner's posts did, for ClipForge AI and its helpers to read (docs/clipforge/CLIPFORGE_AI.md, "Results").

The `results` tool reads the same numbers the app shows, the same way:

* Totals are each post's newest reading, as Publishing → Results counts them (`/api/performance`).
* Best and weakest posts are compared fairly: every post read about 48 hours after the owner's viewers could first
  watch it (`autopilot/compare.posts`, `learner._snapshot`), the owner's own views never counted. A post younger than
  that is "too new to compare yet", never ranked on a reading taken at another age.
* "By format / channel / niche / length" is `autopilot/compare.compare`: one platform and one audience at a time,
  medians, "too few posts" or "no clear difference yet" instead of a guess, and a test to run next.
* YouTube numbers are used only after the owner confirmed Google's approval for metrics derived from YouTube API data
  (`learner.usable`), as YouTube's Developer Policies require; until then the tool says so and leaves them out.
* What ClipForge learned from the results (`brain/lessons.py`) is listed with them.

Everything here is what happened with the owner's posts so far, never a promise of views.
"""
from __future__ import annotations

import time

from .. import db
from .tools import Ctx, Result, Tool, ToolError, one_line, register

PERIODS = {"7": 7, "30": 30, "90": 90, "all": 0}
BY = ("format", "channel", "niche", "length")
TOP = 5            # best posts listed
LOW = 3            # weakest posts listed
GROUPS = 6         # groups of a comparison listed per platform
LESSONS = 4        # lessons from results listed
PLATFORM_NAMES = {"youtube": "YouTube", "tiktok": "TikTok"}
LINKS = [{"label": "Publishing → Results", "href": "#/publishing/results"},
         {"label": "Brain → Performance history", "href": "#/brain/results"}]


def _n(v: float | None) -> str:
    return "not reported" if v is None else f"{int(round(v)):,}"


def _words(text: str) -> set[str]:
    from .toolbox import _said_words

    return {w for w in _said_words(text) if len(w) > 2}


def _post_name(pub: dict) -> tuple[str, str]:
    """(the post's title, the project it came from)."""
    clip = db.get_clip(pub.get("clip_id") or "") or {}
    project = db.get_project(clip.get("project_id") or pub.get("project_id") or "") or {}
    title = one_line(pub.get("title") or clip.get("title") or "Untitled", 80)
    return title, one_line(project.get("name") or "", 60)


def _hits(pub: dict, words: set[str]) -> int:
    """How many of `words` the post's title and its project's name hold."""
    title, project = _post_name(pub)
    return len(words & _words(f"{title} {project}"))


def _lessons(ws: str) -> list[str]:
    from .lessons import TAG

    rows = db.select("brain_memories", "workspace_id = ? AND enabled = 1", (ws,), "updated_at DESC", 50)
    return [one_line(r.get("text"), 300) for r in rows if TAG in (r.get("tags") or [])][:LESSONS]


def summary(ws: str, *, period: str = "30", platform: str = "", by: str = "", words: str = "",
            settings: dict | None = None, now: float | None = None) -> dict:
    """The results as data and as lines a model reads: {"lines", "posts", "counted", "blocked"}."""
    from ..autopilot import compare, learner
    from ..learning import YOUTUBE_NOTE

    settings = settings if settings is not None else db.get_settings()
    now = now or time.time()
    days = PERIODS.get(str(period or "30"), 30)
    since = now - days * 86400 if days else 0.0
    want = _words(words) if words else set()
    platforms = [platform] if platform in PLATFORM_NAMES else list(PLATFORM_NAMES)
    pubs = [p for p in db.list_publications() if p["status"] in ("done", "action_needed")
            and p["platform"] in platforms and learner.shown_at(p) >= since]
    if want:  # the posts that hold the most of the words ("old stream" is the old stream, not every stream)
        hits = {p["id"]: _hits(p, want) for p in pubs}
        best = max(hits.values(), default=0)
        pubs = [p for p in pubs if best and hits[p["id"]] == best]
    span = f"the last {days} days" if days else "all time"
    lines = [f"Results of your posts from {span}" + (f" about “{one_line(words, 60)}”" if words else "") + "."]
    if not pubs:
        lines.append("No post from ClipForge went out in that time" + (" that matches those words" if want else "")
                     + ", so there are no results to read. Publishing shows what is planned.")
        return {"lines": lines, "posts": 0, "counted": 0, "blocked": []}
    latest = db.latest_performance()
    blocked = [p for p in platforms if not learner.usable(p, settings) and any(x["platform"] == p for x in pubs)]
    counted = 0
    for plat in platforms:
        mine = [p for p in pubs if p["platform"] == plat]
        if not mine:
            continue
        name = PLATFORM_NAMES[plat]
        if plat in blocked:
            lines.append(f"{name}: {len(mine)} post(s); their numbers are not used here. {YOUTUBE_NOTE}")
            continue
        read = [latest[p["id"]] for p in mine if p["id"] in latest]
        counted += len(read)

        def total(key: str) -> str:
            vals = [r[key] for r in read if r.get(key) is not None]
            return _n(sum(vals)) if vals else "not reported"

        last = max((r["fetched_at"] for r in read), default=0.0)
        lines.append(f"{name}: {len(mine)} post(s), {len(read)} with numbers (newest readings"
                     + (f", last refreshed {max(0, (now - last) / 3600):.0f} hours ago" if last else "") + "): "
                     f"{total('views')} views, {total('likes')} likes, {total('comments')} comments, "
                     f"{total('shares')} shares.")
    # fair: each post read at about 48 hours, the owner's own views left out
    ids = {p["id"] for p in pubs}
    fair = [r for r in compare.posts(settings, now) if r["publication_id"] in ids and r["cohort"] != "owner_only"
            and r["platform"] not in blocked]
    young = sum(1 for p in pubs if p["platform"] not in blocked and now - learner.shown_at(p) < 48 * 3600)
    if fair:
        cohorts = {r["cohort"] for r in fair}

        def line(n: int, r: dict) -> str:
            pub = db.get_publication(r["publication_id"]) or {}
            title, project = _post_name(pub)
            pct = f", {r['pct']:.0f}% watched on average" if r.get("pct") is not None else ""
            who = f", {compare.COHORT_NAMES.get(r['cohort'], r['cohort'])}" if len(cohorts) > 1 else ""
            return (f"{n}. “{title}”" + (f" (from “{project}”)" if project else "") +
                    f" on {PLATFORM_NAMES.get(r['platform'], r['platform'])}: {_n(r['views'])} views at 48 hours"
                    f"{pct}; {r['format']}, {r['length']}{who}.")

        ranked = sorted(fair, key=lambda r: -r["views"])
        lines.append(f"Best posts (each read about 48 hours after it went out, so they compare fairly; "
                     f"{len(fair)} post(s)):")
        lines += [line(i + 1, r) for i, r in enumerate(ranked[:TOP])]
        if len(ranked) > TOP:
            low = ranked[-min(LOW, len(ranked) - TOP):]
            lines.append("Weakest:")
            lines += [line(len(ranked) - len(low) + i + 1, r) for i, r in enumerate(low)]
    if young:
        lines.append(f"{young} post(s) are under 48 hours old: too new to compare yet.")
    if by in BY:
        out = compare.compare(by, settings, now)
        for place in out["places"]:
            if place["platform"] not in platforms:
                continue
            head = f"By {out['label'].lower()} on {PLATFORM_NAMES[place['platform']]} ({place['audience']}):"
            if not place.get("available"):
                lines.append(f"{head} {place.get('note') or 'not available'}")
                continue
            lines.append(head)
            for g in place["groups"][:GROUPS]:
                lines.append(f"- {one_line(g['group'], 60)} ({g['posts']} posts): {g['text']} Next: {g['test']}")
            if place.get("periods"):
                lines.append(f"- Over time: {place['periods']['text']}")
        lines.append(out["note"])
    learned = _lessons(ws)
    if learned:
        lines.append("What ClipForge learned from your results (it follows these when it picks clips):")
        lines += [f"- {t}" for t in learned]
    lines.append("These are what happened with your posts so far, not a promise of views.")
    return {"lines": lines, "posts": len(pubs), "counted": counted, "blocked": blocked}


def _results(ctx: Ctx, args: dict) -> Result:
    by = str(args.get("by") or "")
    if by and by not in BY:
        raise ToolError(f"results: by must be one of {', '.join(BY)}.")
    out = summary(ctx.ws, period=str(args.get("period") or "30"), platform=str(args.get("platform") or ""), by=by,
                  words=str(args.get("words") or ""))
    return Result("\n".join(out["lines"]), f"Read your results ({out['posts']} posts)", {"links": list(LINKS)},
                  show="\n".join(out["lines"]))


register(Tool("results", "how the owner's posts did: views, likes, % watched, the best and weakest posts (read "
              "fairly at 48 hours), totals, and what ClipForge learned from them. period: 7, 30, 90 or all days; "
              "by: compare by format, channel, niche or length; words narrow it to a project or title",
              {"type": "object", "properties": {"period": {"type": "string", "enum": list(PERIODS)},
                                                "platform": {"type": "string", "enum": list(PLATFORM_NAMES)},
                                                "by": {"type": "string", "enum": list(BY)},
                                                "words": {"type": "string", "maxLength": 200}}},
              _results, "look", "Read your results"))
