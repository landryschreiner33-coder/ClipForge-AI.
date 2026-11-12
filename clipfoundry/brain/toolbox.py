"""ClipForge's own tools for ClipForge AI (registered by tools.py the first time a tool is asked for).

Looking (runs at once): find_projects, open_project, recall, knowhow, app_status, go_to.
Making (runs at once, never touches what you have): remember, propose_change, ask_agent. `remember` saves at once only
the owner's own words from this message, and never changes a memory the owner already has; anything else it asks
first: a "Remember “…”?" button that runs save_memory (hidden from the model) when the owner presses OK.
Changing and deleting (waits for the owner's OK): forget, rename_project, delete_project.

Every tool works inside the chat's workspace only, never sees a file path or a key, and returns plain sentences.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .. import db
from ..pipeline.text_utils import STOPWORDS
from . import knowhow as knowhow_mod
from . import memories
from .tools import AskFirst, Ctx, Result, Tool, ToolError, TryAgain, clip, one_line, register

PAGES = {
    "studio": ("Studio", "#/"), "projects": ("Projects", "#/projects"), "make_clips": ("Make clips", "#/create/clips"),
    "make_video": ("Make a YouTube video", "#/create/video"), "from_link": ("Make clips from a link", "#/create/link"),
    "memory": ("Brain → Memory", "#/brain/memory"), "agents": ("Brain → Agents", "#/brain/agents"),
    "talk": ("Talk to ClipForge AI", "#/brain/talk"), "ai_settings": ("Settings → ClipForge AI", "#/settings/ai"),
    "publishing": ("Publishing", "#/publishing/review"), "missions": ("Missions", "#/missions"),
    "office": ("Office", "#/office"), "accounts": ("Accounts", "#/accounts"),
}
KIND_WORDS = {"clips": "clips project", "full_video": "YouTube video"}
NAME_CHARS = 160    # a project name as the model reads it
GROUNDED = 0.6      # the share of a memory's meaningful words that must be in the owner's message to save it at once
# Words that turn a rule around ("No zooms" for "I love the zooms"): a part of a memory and the owner's words it comes
# from must both have one, or both not. Little words like "no" and "only" are left out of the 60% count, so they are
# checked here, with numbers ("30 seconds" for "3 seconds").
TURNERS = frozenset("""no not never nor none nothing nobody neither nowhere without cannot less fewer least avoid
avoids avoided avoiding stop stops stopped stopping skip skips skipped skipping hide hides hid hiding remove removes
removed removing drop drops dropped dropping cut cuts cutting ban bans banned hate hates hated dislike dislikes
disliked quit exclude excludes excluded mute mutes muted dont doesnt didnt isnt arent wasnt werent cant wont shouldnt
wouldnt couldnt mustnt havent hasnt hadnt aint""".split())
LIMITS = frozenset("only except unless instead more most solely exclusively".split())  # kept only when said
NUMBER_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())} | {
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
    "hundred": "100", "thousand": "1000", "million": "1000000", "half": "half", "quarter": "quarter",
    "double": "double", "twice": "double", "triple": "triple"}
MEMORY_PAGE = {"label": "Open Brain → Memory", "href": "#/brain/memory"}
_LETTERS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_PARTS = re.compile(r"[.!?;,\n]+|\b(?:but|though|however)\b", re.I)  # where one thing said ends and the next begins


# ------------------------------------------------------------------ your projects
def ago(ts: float | None, now: float | None = None) -> str:
    if not ts:
        return "never"
    s = max(0, int((now or time.time()) - float(ts)))
    for size, word in ((86400 * 30, "month"), (86400 * 7, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = s // size
            return f"{n} {word}{'s' if n != 1 else ''} ago"
    return "just now"


def projects(ws: str) -> list[dict]:
    """Every project of this workspace, newest change first: clips projects (Highlights, Full stories) and YouTube
    videos, as {id, kind, name, status, updated_at, mode, clips, href}. A name is one line (`one_line`): it can come
    from outside, such as a downloaded video's title, and it goes into the model's prompt."""
    out = []
    for p in db.list_projects():
        if (p.get("workspace_id") or "local") != ws:
            continue
        out.append({"id": p["id"], "kind": "clips", "name": one_line(p.get("name"), NAME_CHARS) or "Untitled",
                    "status": p.get("status") or "",
                    "updated_at": p.get("updated_at") or 0, "mode": p.get("clip_mode") or "highlights",
                    "clips": int(p.get("clip_count") or 0), "href": f"#/project/{p['id']}"})
    for v in db.select("studio_projects", "workspace_id = ?", (ws,), "updated_at DESC"):
        out.append({"id": v["id"], "kind": "full_video", "name": one_line(v.get("name"), NAME_CHARS) or "My video",
                    "status": v.get("status") or "", "updated_at": v.get("updated_at") or 0, "mode": "full_video",
                    "versions": int(v.get("plan_revision") or 0), "files": len(v.get("asset_ids") or []),
                    # a video still being planned in Make a YouTube video (a draft with its setup) opens on that
                    # page; everything else, a short stopped before its first version too, in the editor
                    "href": f"#/create/video/{v['id']}" if _planning(v) else f"#/video/{v['id']}"})
    return sorted(out, key=lambda x: -float(x["updated_at"] or 0))


def _planning(v: dict) -> bool:
    """A video still being planned on the Make a YouTube video page: a draft that has its setup there (other drafts,
    such as an animated short stopped before its first version, have none)."""
    return v.get("status") == "draft" and bool(v.get("setup")) and (v.get("workflow") or "full_video") == "full_video"


def line(p: dict, now: float | None = None) -> str:
    """One project in words, as the model reads it."""
    if p["kind"] == "clips":
        what = f"clips project ({'Full stories' if p['mode'] == 'stories' else 'Highlights'}), {p['clips']} clips"
    else:
        what = f"YouTube video, {p.get('versions', 0)} versions, {p.get('files', 0)} files"
    return f"- “{p['name']}” — {what}, {p['status'] or 'new'}, changed {ago(p['updated_at'], now)}"


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _which(found: list[dict]) -> str:
    """The projects' names, as the model and the owner tell them apart: a name two of them share says which kind
    each one is."""
    names = [p["name"].lower() for p in found]
    return ", ".join(f"“{p['name']}”" + (f" ({KIND_WORDS.get(p['kind'], 'project')})"
                                         if names.count(p["name"].lower()) > 1 else "") for p in found)


def find(ws: str, query: str, current: str = "", kind: str = "") -> dict:
    """The one project `query` names (an id, the name, or words from the name; "this video" means the chat's own).
    `kind` ("clips" or "full_video") decides between projects that fit as well, such as a clips project and a
    YouTube video with the same name. Raises ToolError naming the candidates when it is not clear which one."""
    query = (query or "").strip().strip("“”\"'")
    every = projects(ws)
    if not query or query.lower() in ("this", "this video", "this project", "it", "current", "here"):
        hit = [p for p in every if p["id"] == current]
        if hit:
            return hit[0]
        raise ToolError("Say which project: there is no project open in this chat.")
    for test in (lambda p: p["id"] == query, lambda p: p["name"].lower() == query.lower()):
        hit = [p for p in every if test(p)]
        if len(hit) > 1 and kind:
            hit = [p for p in hit if p["kind"] == kind] or hit
        if len(hit) == 1:
            return hit[0]
        if len(hit) > 1:
            break
    want = set(_words(query)) - {"the", "my", "video", "project", "clips", "a", "an", "of", "about"}
    scored = []
    for p in every:
        have = set(_words(p["name"]))
        share = len(want & have) / max(1, len(want)) if want else 0
        if query.lower() in p["name"].lower():
            share = max(share, 0.9)
        if share >= 0.5:
            scored.append((share, p))
    scored.sort(key=lambda x: (-x[0], -float(x[1]["updated_at"] or 0)))
    if not scored:
        names = ", ".join(f"“{p['name']}”" for p in every[:8]) or "none yet"
        raise ToolError(f"No project is called “{query}”. The projects are: {names}.")
    best = [p for share, p in scored if share == scored[0][0]]
    if len(best) > 1 and kind:
        best = [p for p in best if p["kind"] == kind] or best
    if len(best) > 1:
        raise ToolError(f"More than one project fits “{query}”: {_which([p for _, p in scored[:5]])}. Ask the owner "
                        "which one.")
    return best[0]


def describe_project(ws: str, p: dict, budget: int = 1400) -> str:
    """What a model needs to talk about one project: its state and, for a clips project, its best clips; for a
    video, its versions, files, brief and script."""
    lines = [line(p)]
    if p["kind"] == "clips":
        row = db.get_project(p["id"]) or {}
        if row.get("duration"):
            lines.append(f"Source video: {int(row['duration'] // 60)} min {int(row['duration'] % 60)} s.")
        if row.get("message"):
            lines.append(f"Status note: {one_line(row['message'], 300)}")
        clips = sorted(db.list_clips(p["id"]), key=lambda c: -float(c.get("score") or 0))
        if clips:
            lines.append("Its clips (best first):")
        for c in clips[:15]:
            title = one_line(c.get("title") or c.get("hook"), 120) or "untitled"
            lines.append(f"  - “{title}” — score {round(float(c.get('score') or 0))}, "
                         f"{round(float(c.get('duration') or (c['end'] - c['start'])))} s, {c.get('status') or ''}")
    else:
        v = db.fetch("studio_projects", p["id"]) or {}
        if v.get("message"):
            lines.append(f"Status note: {one_line(v['message'], 300)}")
        brief = {k: val for k, val in (v.get("brief") or {}).items() if val not in ("", None, [], {})}
        if brief:
            lines.append("Brief: " + "; ".join(f"{k.replace('_', ' ')}: {one_line(val, 300)}"
                                               for k, val in list(brief.items())[:12]))
        script = v.get("script") or {}
        if script.get("lines"):
            lines.append(f"Script: {len(script['lines'])} lines" + (f" from “{one_line(script.get('name'), 120)}”"
                                                                    if script.get("name") else ""))
        rev = int(v.get("plan_revision") or 0)
        if rev:
            from ..studio import edit_requests as er

            try:
                plan, _assets, words, rows = er._context(v, rev)  # noqa: SLF001 - the same words the editor reads
                from ..studio import engine

                lines.append(f"Version {rev}, {round(engine.duration_ms(plan) / 1000)} s long, {len(rows)} parts:")
                for r in rows[:30]:
                    said = " ".join(str(w["w"]) for w in r["words"])  # words from the video's own sound
                    tag = "" if r["included"] else " (left out)"
                    lines.append(f"  {r['n']}. {one_line(r['label'] or r['kind'], 80)}{tag}: "
                                 f"{one_line(r['summary'] or said, 200)}")
            except Exception:  # noqa: BLE001 - a video that cannot be read is still described by its row
                lines.append(f"Version {rev}.")
    return clip("\n".join(lines), budget)


# ------------------------------------------------------------------ looking
def _find_projects(ctx: Ctx, args: dict) -> Result:
    every = projects(ctx.ws)
    words = args.get("words", "")
    if words:
        want = set(_words(words)) - {"my", "the", "project", "projects", "video", "videos", "all"}
        if want:
            every = [p for p in every if want & set(_words(p["name"])) or words.lower() in p["name"].lower()]
    if not every:
        return Result("No projects match." if words else "The owner has no projects yet.", "No projects found")
    now = time.time()
    shown = every[:25]
    text = f"{len(every)} project{'s' if len(every) != 1 else ''}" + (f" (the newest {len(shown)})" if len(every) > 25
                                                                      else "") + ":\n" + \
        "\n".join(line(p, now) for p in shown)
    return Result(clip(text), f"Looked at your projects ({len(every)})",
                  {"links": [{"label": p["name"], "href": p["href"]} for p in shown[:4]]})


def _open_project(ctx: Ctx, args: dict) -> Result:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    return Result(describe_project(ctx.ws, p), f"Looked at “{p['name']}”",
                  {"links": [{"label": f"Open “{p['name']}”", "href": p["href"]}]})


def _recall(ctx: Ctx, args: dict) -> Result:
    found = memories.list_(ctx.ws, q=args.get("words", ""), project_id=ctx.project_id, limit=8)
    found = [m for m in found if m.get("enabled", True) and not m.get("expired")]
    if not found:
        return Result("Nothing in the memory matches.", "Searched your memories: nothing")
    return Result("\n".join(f"- [{m['kind']}] {one_line(m['text'])}" for m in found),
                  f"Searched your memories ({len(found)} found)")


def _knowhow(ctx: Ctx, args: dict) -> Result:
    picked = knowhow_mod.select(args.get("topic", ""), "chat", limit=1, budget_chars=1400)
    if picked.empty:
        return Result("No playbook fits that topic.", "Read its know-how: nothing fitted")
    return Result(picked.prompt(), "Read its editing know-how")


def _app_status(ctx: Ctx, args: dict) -> Result:
    from ..pipeline import llm

    s = db.get_settings()
    lines = [f"ClipForge AI's model: {llm.provider_label(s)}"
             + (", on this computer" if llm.is_local(s) else ", online") + "."]
    busy = db.select("studio_jobs", "status IN ('queued', 'running')", (), "created_at DESC", 10)
    working = [p for p in projects(ctx.ws) if p["status"] in ("processing", "building", "rendering", "queued")]
    lines.append(f"Work running now: {len(busy)} studio jobs; projects being made: "
                 + (", ".join(f"“{p['name']}” ({p['status']})" for p in working[:5]) or "none") + ".")
    counts = db.select("brain_memories", "workspace_id = ? AND enabled = 1", (ctx.ws,))
    lines.append(f"Memories: {len(counts)}.")
    from . import agents

    on = agents.list_(ctx.ws, enabled_only=True)
    lines.append("Helper agents switched on: " + (", ".join(a["name"] for a in on) or "none") + ".")
    return Result("\n".join(lines), "Checked how ClipForge is doing")


def _go_to(ctx: Ctx, args: dict) -> Result:
    if args.get("project"):
        p = find(ctx.ws, args["project"], ctx.project_id)
        return Result(f"A button to open “{p['name']}” is shown.", f"Link to “{p['name']}”",
                      {"links": [{"label": f"Open “{p['name']}”", "href": p["href"]}]})
    page = args.get("page", "")
    if page not in PAGES:
        raise ToolError("go_to needs a page or a project.")
    name, href = PAGES[page]
    return Result(f"A button to open {name} is shown.", f"Link to {name}", {"links": [{"label": name, "href": href}]})


# ------------------------------------------------------------------ making
def _said_words(text: str) -> list[str]:
    return [w.replace("’", "'") for w in _LETTERS.findall((text or "").lower())]


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


@dataclass(frozen=True)
class _Said:
    """One part of something said (up to a comma, a full stop or a "but"), as `grounded` compares it."""
    stems: frozenset       # its meaningful words (three letters or more, not little words; a plural s ignored)
    words: frozenset       # every word
    turned: bool           # it says no, never, don't, avoid, less …
    numbers: frozenset     # 3, 30, "three" (as "3"), "half" …


def _said(text: str) -> _Said:
    words = _said_words(text)
    return _Said(frozenset(_stem(w) for w in words if len(w) >= 3 and w not in STOPWORDS), frozenset(words),
                 any(w in TURNERS or w.endswith("n't") for w in words),
                 frozenset(re.findall(r"\d+", text) + [NUMBER_WORDS[w] for w in words if w in NUMBER_WORDS]))


def grounded(text: str, owner_text: str) -> bool:
    """True when `text` is the owner's own words from `owner_text` (the owner's message this turn), so `remember` may
    save it at once:
    - at least 60% of its meaningful words (three letters or more, not little words like "the" or "with"; a plural s
      ignored) are in the owner's message, and
    - each part of it (up to a comma, a full stop or a "but") says what the part of the owner's message with the most
      of its words says: both turned around (no, not, never, don't, avoid, less …) or both not, with only the
      numbers and the limiting words (only, except, more …) that part has. "No zooms" is not "I love the zooms",
      "30 seconds" is not "3 seconds", "only post on TikTok" is not "post on TikTok and YouTube"."""
    mine = [_said(p) for p in _PARTS.split(text or "")]
    want = frozenset().union(*(p.stems for p in mine))
    if not want:
        return False
    theirs = [_said(p) for p in _PARTS.split(owner_text or "")]
    if len(want & frozenset().union(*(p.stems for p in theirs))) < GROUNDED * len(want):
        return False
    for p in mine:
        limits = p.words & LIMITS
        if not (p.stems or p.numbers or p.turned or limits):
            continue
        best = max(len(p.stems & o.stems) for o in theirs)
        if p.stems and not best:  # a part with none of the owner's words: said by someone else
            return False
        near = [o for o in theirs if len(p.stems & o.stems) == best]
        if not any(o.turned == p.turned and p.numbers <= o.numbers and limits <= o.words for o in near):
            return False
    return True


def _here(ctx: Ctx, args: dict) -> bool:
    """Whether a memory is kept for this video only: the model said so, or its words point at this video ("this
    video", "this one", "here": `memories.points_here`). Those can only be read in this video's chat, whatever the
    model chose: kept for every video, "this video is for kids" would be read in every other video's chat."""
    return bool(ctx.project_id) and (args.get("scope") == "this_video" or bool(memories.points_here(args["text"])[0]))


def _kind(args: dict) -> str:
    return args.get("kind") or ("rule" if re.search(r"\b(always|never|don't|do not|only|every|must|no)\b",
                                                    args["text"], re.I) else "fact")


def _kinds(kind: str) -> tuple[str, str]:
    """The same words kept as the other kind are the same memory too (a rule the model calls a fact): never a twin."""
    return (kind, "fact" if kind == "rule" else "rule")


def _already(ctx: Ctx, twin: dict, here: bool) -> Result:
    """A memory that already says it is never changed from the chat: it is in the memory as asked, or the owner
    decides on it in Brain → Memory (it is switched off, kept for one video or one platform, or only a guess)."""
    words = clip(twin["text"], 80)
    scope = twin.get("scope") or "all"
    if twin.get("enabled") and twin.get("source") != "guessed" and \
            scope in ("all", f"project:{ctx.project_id}" if here else "all"):
        return Result("That is already in my memory.", f"Already in your memory: “{words}”")
    if not twin.get("enabled"):
        why = "switched off"
    elif twin.get("source") == "guessed":
        why = "only as a guess"
    elif ctx.project_id and scope == f"project:{ctx.project_id}":
        why = "only for this video"
    elif scope.startswith("project:"):
        why = "only for another video" if ctx.project_id else "only for one video"
    elif scope.startswith("platform:"):
        why = f"only for {scope[9:]}"
    else:
        why = "only for clips projects" if scope == "mode:clips" else "only for YouTube videos"
    return Result(f"Not saved again: that is already in the memory, but {why}. Nothing was changed: the owner can "
                  "change it in Brain → Memory (a button to it is shown).",
                  f"Already in your memory, but {why}: “{words}”", {"links": [MEMORY_PAGE]}, ok=False)


def _keep(ctx: Ctx, text: str, kind: str, here: bool) -> Result:
    """A new memory, as said by the owner; the only result that carries it (and so its Undo chip). Nothing is kept for
    a video deleted while this answer was written: its memories went with it (studio/project_delete.py)."""
    if here and not db.fetch("studio_projects", ctx.project_id):
        raise ToolError("This video was deleted, so nothing is kept for it.")
    try:
        row = memories.remember(ctx.ws, text, kind=kind, source="said", project_id=ctx.project_id if here else "")
    except memories.Invalid as exc:
        raise ToolError(str(exc)) from exc
    where = "this video" if here else "every video"
    label = f"Remembered “{row['text']}”" + (" for this video" if here else "")  # the owner's step line says where
    points, further = memories.points_here(row["text"]) if here else ("", False)
    if further:  # it also speaks of other videos or of later: the owner may have meant every video
        where += (f" only, because it says “{points}” (to keep it for every video, the owner can say it again and "
                  f"say {memories.said_instead(points)} instead)")
    elif points:  # the words decided it, whatever the model chose: its answer can say which words
        where += f", because it says “{points}”"
    return Result(f"Saved as a {row['kind']} for {where}: {row['text']}", label, {"memory": memories.view(row)})


def _remember(ctx: Ctx, args: dict) -> Result:
    text, kind, here = args["text"], _kind(args), _here(ctx, args)
    twin = memories.twin(ctx.ws, text, _kinds(kind), f"project:{ctx.project_id}" if here else "all")
    if twin:  # never changed from here: not switched back on, not moved or widened, a guess stays a guess
        return _already(ctx, twin, here)
    if not grounded(text, ctx.owner_text):  # words from a transcript, a name, a result or a helper: not at once
        if ctx.agent is not None:
            raise ToolError("Only the owner's own words from this message are saved at once: suggest this memory "
                            "to the owner in your answer instead.")
        raise AskFirst("Not saved yet: these are not the owner's own words from this message, so the owner is "
                       "asked first.", "save_memory", {"text": text, "kind": kind,
                                                        "scope": "this_video" if here else "all"})
    return _keep(ctx, text, kind, here)


LABEL_WORDS = 120  # a memory longer than this is shown whole under the card's label


def _save_memory_preview(ctx: Ctx, args: dict) -> dict:
    """The "Remember …?" card: OK keeps exactly the words it shows, so a long memory is shown whole (OK must never
    keep words the owner did not see)."""
    text, kind, here = args["text"], _kind(args), _here(ctx, args)
    short = len(text) <= LABEL_WORDS
    return {"label": f"Remember “{text}”?" if short else "Remember this?",
            "detail": ([] if short else [f"“{text}”"]) +
                      [f"I would keep it as a {kind} for {'this video' if here else 'every video'}.",
                       "These are not your own words from this message, so I ask first."],
            "blocked": "", "args": {"text": text, "kind": kind, "scope": "this_video" if here else "all"}}


def _save_memory(ctx: Ctx, args: dict) -> Result:
    """After the owner's OK: kept as said by the owner (they pressed OK), still never changing a memory they have."""
    text, kind, here = args["text"], _kind(args), _here(ctx, args)
    twin = memories.twin(ctx.ws, text, _kinds(kind), f"project:{ctx.project_id}" if here else "all")
    if twin:
        return _already(ctx, twin, here)
    return _keep(ctx, text, kind, here)


def _propose_change(ctx: Ctx, args: dict) -> Result:
    from ..studio import edit_requests as er

    if not ctx.project_id:
        raise ToolError("Changes are proposed in a video's own chat.")
    try:
        r = er.ask(ctx.project_id, ctx.ws, args["request"][: er.MAX_TEXT])
    except er.RequestError as exc:
        raise ToolError(str(exc)) from exc
    data = {"request_id": r["id"]}
    if r["status"] == "thinking":
        return Result("The change is being worked out now; the owner will see the proposal with Apply and Discard.",
                      "Started working out the change", data)
    p = r.get("proposal") or {}
    if r["status"] == "ready":
        changes = "; ".join((p.get("changes") or [])[:8])
        return Result(f"Proposal ready for the owner to apply or discard: {p.get('summary') or ''} {changes}".strip(),
                      "Proposed a change", data)
    if r["status"] == "question":
        choices = ", ".join(str(c.get("label") or c.get("request")) for c in p.get("choices") or [])
        return Result(f"The editor needs to know: {r.get('message')} Choices: {choices}", "The editor asked", data)
    return Result(f"Not done: {r.get('message')}", "Could not propose that change", data, ok=False)


def _ask_agent(ctx: Ctx, args: dict) -> Result:
    from . import agents

    agent = agents.find(ctx.ws, args["agent"])
    out = agents.run(ctx.ws, agent["id"], args["task"], chat=ctx.chat, project_id=ctx.project_id,
                     deadline=ctx.deadline, cancel=ctx.cancel, on_text=ctx.on_helper, owner_text=ctx.owner_text)
    helper = {"agent": out["agent"], "task": args["task"], "text": out["text"], "ok": out["ok"],
              "steps": out.get("steps") or []}
    data: dict = {"helpers": [helper]}
    saved = [m for m in (out.get("data") or {}).get("remembered") or [] if isinstance(m, dict)]
    if saved:  # what the helper kept shows in the answer like ClipForge AI's own, each with its Undo chip
        data["remembered"] = saved
    text = f"{agent['name']} answered:\n{out['text']}" if out["ok"] else \
        f"{agent['name']} could not do it: {out['text']}"
    return Result(clip(text, 2400), f"Asked {agent['name']}", data, ok=out["ok"])


# ------------------------------------------------------------------ changing and deleting (after the owner's OK)
FORGET_MAX = 16  # the memories one Forget card names, a line each (twins of the same words: usually two or three);
#                  with its first line this fits the lines a card shows (assistant.MAX_DETAIL)
FORGET_IDS = 50  # a card saved by an earlier build named up to 50: its OK reads them all, to refuse rather than cut


_NAMES_NONE = STOPWORDS | {"rule", "rules", "memory", "memories", "fact", "facts", "note", "notes"}
HELD = 500  # the newest memories holding a card's words that are looked through for one that applies in this chat


def _memories_for(ctx: Ctx, words: str) -> list[dict]:
    """What a Forget card is about: every memory that says these words (`memories.to_forget`: its twins too, kept
    for one video, switched off or as another kind; in a video's chat not another video's own note beside one that
    applies here). Else every one that says the words of the newest memory that holds them as a part of its own
    (`memories.holding`: "-3 dB" for "-3 dB here", a number, a short word or a word in another script, which the
    search leaves out; never for little words alone, such as "that" or "the rule"; in a video's chat the newest
    that applies there comes before another video's newer note, `memories.meant`), else of the closest memory the
    search finds; oldest first. Only the preview looks: OK forgets what its card named."""
    same = memories.to_forget(ctx.ws, words, ctx.project_id)
    if not same:
        named = any(w not in _NAMES_NONE for w in re.findall(r"[^\W_]+", str(words).lower()))
        held = memories.meant(memories.holding(ctx.ws, words, HELD), ctx.project_id) if named else []
        found = held[:1] or memories.list_(ctx.ws, q=words, limit=5)
        if not found:
            raise ToolError("Nothing like that is in the memory.")
        same = memories.to_forget(ctx.ws, found[0]["text"], ctx.project_id) or [found[0]]
    return same


def _a(kind: str) -> str:
    return f"{'an' if kind[:1] in 'aeiou' else 'a'} {kind}"


def _where(m: dict, names: dict[str, str]) -> str:
    """Where a memory applies, in plain words, and whether it is switched off."""
    scope, _, value = str(m.get("scope") or "all").partition(":")
    where = {"project": f"for “{names.get(value) or 'a deleted video'}” only", "platform": f"for {value} only",
             "mode": "for clips only" if value == "clips" else "for YouTube videos only"}.get(scope, "for every video")
    return where if m.get("enabled") else f"{where} (switched off)"


def _forget_preview(ctx: Ctx, args: dict) -> dict:
    """The Forget card names every memory that says those words, where each applies, so OK leaves no twin that still
    follows them. One that would name more than FORGET_MAX cannot be pressed: OK must never forget what it did not
    show, and the exact words said in the chat forget them all (`chat._forget_words`)."""
    same = _memories_for(ctx, args["memory"])
    first, n = same[0], len(same)
    label = f"Forget “{clip(first['text'], 120)}”"
    if n > FORGET_MAX:
        return {"label": label, "detail": [], "args": {"memory": first["text"]},
                "blocked": f"I keep these words {n} times, more than one card can show. To forget them all, say "
                           "“forget” and the exact words, or use Brain → Memory."}
    names = {p["id"]: p["name"] for p in projects(ctx.ws)}
    if n == 1:
        detail = [f"It is {_a(first['kind'])} you taught me, {_where(first, names)}."]
    else:
        detail = [f"I keep these words {n} times, and OK forgets them all:"] + \
                 [f"{_a(m['kind'])} {_where(m, names)}" for m in same]
    return {"label": label, "detail": detail, "blocked": "",
            "args": {"memory": first["text"], "memory_ids": [m["id"] for m in same]}}


def _forget(ctx: Ctx, args: dict) -> Result:
    """After the owner's OK: forgets the memories the card named (`memory_ids`; a card saved by an earlier build named
    one, `memory_id`), each only while it still says the card's words: one changed since stays as it is now, and one
    forgotten, or tidied into its twin, meanwhile is gone already. It never looks for memories again, and a card that
    names more than one card can show now (an earlier build's) forgets none: it could not show them all."""
    words = args["memory"]
    ids = args.get("memory_ids") or ([args["memory_id"]] if args.get("memory_id") else [])
    if not ids:
        raise ToolError("This button does not say which memories it forgets: ask me again.")
    if len(ids) > FORGET_MAX:
        raise ToolError(f"This card names {len(ids)} memories, more than one card can show, so nothing was forgotten. "
                        "To forget them all, say “forget” and the exact words, or use Brain → Memory.")
    gone, changed = [], 0
    for mid in ids:
        try:
            gone.append(memories.forget(ctx.ws, mid, words=words))
        except memories.Invalid as exc:
            changed += exc.status == 409
    if not gone:
        raise ToolError("That memory was changed since the card was shown, so nothing was forgotten." if changed
                        else "Memory not found.")
    note = f" ({len(gone)} times)" if len(gone) > 1 else ""
    if changed:
        note += (f"; {changed} was changed since the card was shown and stays" if changed == 1 else
                 f"; {changed} were changed since the card was shown and stay")
    return Result(f"Forgotten: {gone[0]['text']}{note}", f"Forgot “{clip(gone[0]['text'], 80)}”{note}")


def _rename_preview(ctx: Ctx, args: dict) -> dict:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    return {"label": f"Rename “{p['name']}” to “{args['name']}”", "detail": ["Only the name changes."], "blocked": "",
            "args": {"project": p["id"], "name": args["name"]}}


GONE = "That project is not there any more: it was deleted."


def _named(ctx: Ctx, args: dict) -> dict:
    """The project an OK button names. Its preview put the project's id there, so a project not found by that id was
    deleted since (on the Projects page, or by another button)."""
    hit = [p for p in projects(ctx.ws) if p["id"] == args.get("project")]
    if not hit:
        raise ToolError(GONE)
    return hit[0]


def _rename(ctx: Ctx, args: dict) -> Result:
    p = _named(ctx, args)
    name = args["name"][:120]
    if p["kind"] == "clips":
        db.update_project(p["id"], name=name, updated_at=time.time())
    else:
        db.update("studio_projects", p["id"], name=name, updated_at=time.time())
    return Result(f"Renamed “{p['name']}” to “{name}”.", f"Renamed to “{name}”",
                  {"links": [{"label": f"Open “{name}”", "href": p["href"]}]})


def _delete_preview(ctx: Ctx, args: dict) -> dict:
    """What deleting the project does, in the safe delete's own words (studio/project_delete.py, as the window on the
    Projects page says it). The button keeps when that was judged (`as_of`: a file it said stays because the owner
    added it again still stays when OK comes later) and what it listed beyond the project itself (`removes`: media
    files, the copy of the video it was made from, planned posts, and the files it said stay). OK deletes no more than
    that, or nothing: a card can wait long, and one answer can show two cards for projects that share a file."""
    from ..studio import project_delete as pd

    p = find(ctx.ws, args.get("project", ""), ctx.project_id, args.get("kind") or "")
    try:
        plan = pd.plan(ctx.ws, p["id"], p["kind"])
    except pd.DeleteError as exc:
        raise ToolError(GONE if exc.code == "not_found" else str(exc)) from exc
    detail = [f"Goes: {s}" for s in plan.get("goes") or []] + [f"Stays: {s}" for s in plan.get("stays") or []]
    if plan.get("working"):  # "ClipForge is still working on it (...). Deleting stops that first."
        detail.insert(0, str(plan["working"]))
    return {"label": f"Delete the {KIND_WORDS[p['kind']]} “{p['name']}”", "detail": detail,  # all: at most 16 lines
            "blocked": plan.get("blocked") or "", "args": {"project": p["id"], "kind": p["kind"],
                                                           "as_of": plan.get("as_of"),
                                                           "removes": plan.get("removes")}}


def _delete(ctx: Ctx, args: dict) -> Result:
    from ..studio import project_delete as pd

    p = _named(ctx, args)
    try:  # running work gets 10 s to stop, as on the Projects page
        done = pd.delete(ctx.ws, p["id"], p["kind"], wait=10.0, as_of=args.get("as_of"), removes=args.get("removes"))
    except pd.DeleteError as exc:
        if exc.code == "stopping":  # its work was asked to stop and has not yet: the button stays for another press
            raise TryAgain(str(exc)) from exc
        if exc.code == "changed":  # it would remove more than this card listed: a new card shows what goes now
            raise ToolError(f"{exc} Ask again to see what deleting it removes now.") from exc
        # blocked: Autopilot or a post started on it since the card was shown, and what goes can change until that
        # ends (a planned post, more clips), so this card's words no longer hold; asking again later shows a card
        # with the words of that moment, as the Projects page checks again after such an answer
        raise ToolError(GONE if exc.code == "not_found" else str(exc)) from exc
    later = (". A few of its files were open in another program; ClipForge removes them the next time it starts."
             if done.get("left_behind") else "")  # as the Projects page says it
    return Result(f"Deleted the {KIND_WORDS[p['kind']]} “{p['name']}”{later or '.'}", f"Deleted “{p['name']}”{later}",
                  {"deleted": {"id": p["id"], "kind": p["kind"], "name": done.get("name") or p["name"]}})


TEXT = {"type": "string", "maxLength": 300}
register(Tool("find_projects", "the owner's projects and YouTube videos, newest first; words narrow the list",
              {"type": "object", "properties": {"words": TEXT}}, _find_projects, "look", "Looked at your projects"))
register(Tool("open_project", "the details of one project or video (its clips, parts, brief); "
              "project is its name, or leave it out for this chat's video",
              {"type": "object", "properties": {"project": TEXT}}, _open_project, "look", "Looked at {project}"))
register(Tool("recall", "search what the owner told you before (memories)",
              {"type": "object", "properties": {"words": TEXT}, "required": ["words"]}, _recall, "look",
              "Searched your memories"))
register(Tool("knowhow", "read ClipForge's editing playbook on a topic (hooks, pacing, captions, sound, music, "
              "colour, effects, picking clips, platforms, retention)",
              {"type": "object", "properties": {"topic": TEXT}, "required": ["topic"]}, _knowhow, "look",
              "Read its editing know-how"))
register(Tool("app_status", "what ClipForge is doing now: the AI model, work running, memories, agents",
              {"type": "object", "properties": {}}, _app_status, "look", "Checked how ClipForge is doing"))
register(Tool("go_to", "show the owner a button that opens a page or a project",
              {"type": "object", "properties": {"page": {"type": "string", "enum": sorted(PAGES)}, "project": TEXT}},
              _go_to, "look", "Showed a link"))
MEMORY_ARGS = {"type": "object", "properties": {"text": {"type": "string", "maxLength": 600},
                                               "kind": {"type": "string", "enum": ["rule", "fact"]},
                                               "scope": {"type": "string", "enum": ["all", "this_video"]}},
               "required": ["text"]}
register(Tool("remember", "save a lasting rule or fact the owner told you in this message, in their words (scope "
              "this_video: only for this video); other words wait for the owner's OK", MEMORY_ARGS, _remember,
              "make", "Remembered “{text}”"))
register(Tool("save_memory", "keep a memory the owner said yes to (never offered: remember asks the owner with it)",
              MEMORY_ARGS, _save_memory, "change", "Remember “{text}”", places=(), preview=_save_memory_preview,
              for_agents=False))
register(Tool("propose_change", "propose a change to this video's cut (the owner applies or discards it); request "
              "is the change in plain words, like 'move the summit part before lunch'",
              {"type": "object", "properties": {"request": {"type": "string", "maxLength": 500}},
               "required": ["request"]}, _propose_change, "make", "Proposed a change", places=("video",)))
register(Tool("ask_agent", "hand a job to one of the owner's helper agents and get its work back",
              {"type": "object", "properties": {"agent": TEXT, "task": {"type": "string", "maxLength": 1500}},
               "required": ["agent", "task"]}, _ask_agent, "make", "Asked {agent}", for_agents=False))
register(Tool("forget", "remove something from the memory (memory: its words)",
              {"type": "object", "properties": {"memory": {"type": "string", "maxLength": memories.MAX_TEXT},
                                                # the memories its card named (one on a card saved by an earlier
                                                # build): only the button keeps them
                                                "memory_ids": {"type": "array", "items": {"type": "string"},
                                                               "maxItems": FORGET_IDS, "internal": True},
                                                "memory_id": {"type": "string", "internal": True}},
               "required": ["memory"]},
              _forget, "change", "Forget {memory}", preview=_forget_preview, for_agents=False))
register(Tool("rename_project", "rename a project or video",
              {"type": "object", "properties": {"project": TEXT, "name": {"type": "string", "maxLength": 120}},
               "required": ["name"]}, _rename, "change", "Rename {project} to {name}", preview=_rename_preview,
              for_agents=False))
register(Tool("delete_project", "delete a project or video and what belongs only to it",
              {"type": "object", "properties": {"project": TEXT,
                                                "kind": {"type": "string", "enum": ["clips", "full_video"]},
                                                # when its preview was shown and what it listed beyond the project:
                                                # only the button keeps them
                                                "as_of": {"type": "number", "internal": True},
                                                "removes": {"type": "object", "internal": True}}},
              _delete, "delete", "Delete {project}", preview=_delete_preview, for_agents=False))
