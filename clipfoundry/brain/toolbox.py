"""ClipForge's own tools for ClipForge AI (registered by tools.py the first time a tool is asked for).

Looking (runs at once): find_projects, open_project, recall, knowhow, app_status, go_to.
Making (runs at once, never touches what you have): remember, propose_change, ask_agent.
Changing and deleting (waits for the owner's OK): forget, rename_project, delete_project.

Every tool works inside the chat's workspace only, never sees a file path or a key, and returns plain sentences.
"""
from __future__ import annotations

import re
import time

from .. import db
from . import knowhow as knowhow_mod
from . import memories
from .tools import Ctx, Result, Tool, ToolError, clip, register

PAGES = {
    "studio": ("Studio", "#/"), "projects": ("Projects", "#/projects"), "make_clips": ("Make clips", "#/create/clips"),
    "make_video": ("Make a YouTube video", "#/create/video"), "from_link": ("Make clips from a link", "#/create/link"),
    "memory": ("Brain → Memory", "#/brain/memory"), "agents": ("Brain → Agents", "#/brain/agents"),
    "talk": ("Talk to ClipForge AI", "#/brain/talk"), "ai_settings": ("Settings → ClipForge AI", "#/settings/ai"),
    "publishing": ("Publishing", "#/publishing/review"), "missions": ("Missions", "#/missions"),
    "office": ("Office", "#/office"), "accounts": ("Accounts", "#/accounts"),
}
KIND_WORDS = {"clips": "clips project", "full_video": "YouTube video"}


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
    videos, as {id, kind, name, status, updated_at, mode, clips, href}."""
    out = []
    for p in db.list_projects():
        if (p.get("workspace_id") or "local") != ws:
            continue
        out.append({"id": p["id"], "kind": "clips", "name": p.get("name") or "Untitled", "status": p.get("status") or "",
                    "updated_at": p.get("updated_at") or 0, "mode": p.get("clip_mode") or "highlights",
                    "clips": int(p.get("clip_count") or 0), "href": f"#/project/{p['id']}"})
    for v in db.select("studio_projects", "workspace_id = ?", (ws,), "updated_at DESC"):
        out.append({"id": v["id"], "kind": "full_video", "name": v.get("name") or "My video",
                    "status": v.get("status") or "", "updated_at": v.get("updated_at") or 0, "mode": "full_video",
                    "versions": int(v.get("plan_revision") or 0), "files": len(v.get("asset_ids") or []),
                    "href": f"#/video/{v['id']}"})
    return sorted(out, key=lambda x: -float(x["updated_at"] or 0))


def line(p: dict, now: float | None = None) -> str:
    """One project in words, as the model reads it."""
    if p["kind"] == "clips":
        what = f"clips project ({'Full stories' if p['mode'] == 'stories' else 'Highlights'}), {p['clips']} clips"
    else:
        what = f"YouTube video, {p.get('versions', 0)} versions, {p.get('files', 0)} files"
    return f"- “{p['name']}” — {what}, {p['status'] or 'new'}, changed {ago(p['updated_at'], now)}"


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def find(ws: str, query: str, current: str = "") -> dict:
    """The one project `query` names (an id, the name, or words from the name; "this video" means the chat's own).
    Raises ToolError naming the candidates when it is not clear which one."""
    query = (query or "").strip().strip("“”\"'")
    every = projects(ws)
    if not query or query.lower() in ("this", "this video", "this project", "it", "current", "here"):
        hit = [p for p in every if p["id"] == current]
        if hit:
            return hit[0]
        raise ToolError("Say which project: there is no project open in this chat.")
    for test in (lambda p: p["id"] == query, lambda p: p["name"].lower() == query.lower()):
        hit = [p for p in every if test(p)]
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
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        names = ", ".join(f"“{p['name']}”" for _, p in scored[:5])
        raise ToolError(f"More than one project fits “{query}”: {names}. Ask the owner which one.")
    return scored[0][1]


def describe_project(ws: str, p: dict, budget: int = 1400) -> str:
    """What a model needs to talk about one project: its state and, for a clips project, its best clips; for a
    video, its versions, files, brief and script."""
    lines = [line(p)]
    if p["kind"] == "clips":
        row = db.get_project(p["id"]) or {}
        if row.get("duration"):
            lines.append(f"Source video: {int(row['duration'] // 60)} min {int(row['duration'] % 60)} s.")
        if row.get("message"):
            lines.append(f"Status note: {row['message']}")
        clips = sorted(db.list_clips(p["id"]), key=lambda c: -float(c.get("score") or 0))
        if clips:
            lines.append("Its clips (best first):")
        for c in clips[:15]:
            title = c.get("title") or c.get("hook") or "untitled"
            lines.append(f"  - “{title}” — score {round(float(c.get('score') or 0))}, "
                         f"{round(float(c.get('duration') or (c['end'] - c['start'])))} s, {c.get('status') or ''}")
    else:
        v = db.fetch("studio_projects", p["id"]) or {}
        if v.get("message"):
            lines.append(f"Status note: {v['message']}")
        brief = {k: val for k, val in (v.get("brief") or {}).items() if val not in ("", None, [], {})}
        if brief:
            lines.append("Brief: " + "; ".join(f"{k.replace('_', ' ')}: {val}" for k, val in list(brief.items())[:12]))
        script = v.get("script") or {}
        if script.get("lines"):
            lines.append(f"Script: {len(script['lines'])} lines" + (f" from “{script.get('name')}”"
                                                                    if script.get("name") else ""))
        rev = int(v.get("plan_revision") or 0)
        if rev:
            from ..studio import edit_requests as er

            try:
                plan, _assets, words, rows = er._context(v, rev)  # noqa: SLF001 - the same words the editor reads
                from ..studio import engine

                lines.append(f"Version {rev}, {round(engine.duration_ms(plan) / 1000)} s long, {len(rows)} parts:")
                for r in rows[:30]:
                    said = " ".join(w["w"] for w in r["words"])[:140]
                    tag = "" if r["included"] else " (left out)"
                    lines.append(f"  {r['n']}. {r['label'] or r['kind']}{tag}: {r['summary'] or said}")
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
    return Result("\n".join(f"- [{m['kind']}] {m['text']}" for m in found),
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
def _remember(ctx: Ctx, args: dict) -> Result:
    here = args.get("scope") == "this_video" and bool(ctx.project_id)
    kind = args.get("kind") or ("rule" if re.search(r"\b(always|never|don't|do not|only|every|must|no)\b",
                                                    args["text"], re.I) else "fact")
    try:
        row = memories.remember(ctx.ws, args["text"], kind=kind, source="said",
                                project_id=ctx.project_id if here else "")
    except memories.Invalid as exc:
        raise ToolError(str(exc)) from exc
    where = "this video" if here else "every video"
    return Result(f"Saved as a {row['kind']} for {where}: {row['text']}", f"Remembered “{row['text']}”",
                  {"memory": memories.view(row)})


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
                     deadline=ctx.deadline, cancel=ctx.cancel, on_text=ctx.on_helper)
    helper = {"agent": out["agent"], "task": args["task"], "text": out["text"], "ok": out["ok"],
              "steps": out.get("steps") or []}
    text = f"{agent['name']} answered:\n{out['text']}" if out["ok"] else f"{agent['name']} could not do it: {out['text']}"
    return Result(clip(text, 2400), f"Asked {agent['name']}", {"helpers": [helper]}, ok=out["ok"])


# ------------------------------------------------------------------ changing and deleting (after the owner's OK)
def _memory_for(ctx: Ctx, words: str) -> dict:
    found = memories.list_(ctx.ws, q=words, limit=5)
    exact = [m for m in found if memories._norm(m["text"]) == memories._norm(words)]  # noqa: SLF001
    if exact:
        return exact[0]
    if not found:
        raise ToolError("Nothing like that is in the memory.")
    return found[0]


def _forget_preview(ctx: Ctx, args: dict) -> dict:
    m = _memory_for(ctx, args["memory"])
    return {"label": f"Forget “{clip(m['text'], 120)}”", "detail": [f"It is a {m['kind']} you taught me."],
            "blocked": "", "args": {"memory": m["text"], "memory_id": m["id"]}}


def _forget(ctx: Ctx, args: dict) -> Result:
    mid = args.get("memory_id") or _memory_for(ctx, args["memory"])["id"]
    try:
        gone = memories.forget(ctx.ws, mid)
    except memories.Invalid as exc:
        raise ToolError(str(exc)) from exc
    return Result(f"Forgotten: {gone['text']}", f"Forgot “{clip(gone['text'], 80)}”")


def _rename_preview(ctx: Ctx, args: dict) -> dict:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    return {"label": f"Rename “{p['name']}” to “{args['name']}”", "detail": ["Only the name changes."], "blocked": "",
            "args": {"project": p["id"], "name": args["name"]}}


def _rename(ctx: Ctx, args: dict) -> Result:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    name = args["name"][:120]
    if p["kind"] == "clips":
        db.update_project(p["id"], name=name, updated_at=time.time())
    else:
        db.update("studio_projects", p["id"], name=name, updated_at=time.time())
    return Result(f"Renamed “{p['name']}” to “{name}”.", f"Renamed to “{name}”",
                  {"links": [{"label": f"Open “{name}”", "href": p["href"]}]})


def _deleter():
    try:
        from ..studio import project_delete  # the safe delete (its own module): plan() says what goes, delete() does it
    except ImportError as exc:
        raise ToolError("This version of ClipForge cannot delete projects from the chat yet; use the Projects "
                        "page.") from exc
    return project_delete


def _delete_preview(ctx: Ctx, args: dict) -> dict:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    pd = _deleter()
    try:
        plan = pd.plan(ctx.ws, p["id"], p["kind"])
    except pd.DeleteError as exc:
        raise ToolError(str(exc)) from exc
    detail = [f"Goes: {s}" for s in plan.get("goes") or []] + [f"Stays: {s}" for s in plan.get("stays") or []]
    return {"label": f"Delete the {KIND_WORDS[p['kind']]} “{p['name']}”", "detail": detail[:10],
            "blocked": plan.get("blocked") or "", "args": {"project": p["id"], "kind": p["kind"]}}


def _delete(ctx: Ctx, args: dict) -> Result:
    p = find(ctx.ws, args.get("project", ""), ctx.project_id)
    pd = _deleter()
    try:
        done = pd.delete(ctx.ws, p["id"], p["kind"])
    except pd.DeleteError as exc:
        raise ToolError(str(exc)) from exc
    return Result(f"Deleted the {KIND_WORDS[p['kind']]} “{p['name']}”.", f"Deleted “{p['name']}”",
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
register(Tool("remember", "save a lasting rule or fact the owner told you (scope this_video: only for this video)",
              {"type": "object", "properties": {"text": {"type": "string", "maxLength": 600},
                                                "kind": {"type": "string", "enum": ["rule", "fact"]},
                                                "scope": {"type": "string", "enum": ["all", "this_video"]}},
               "required": ["text"]}, _remember, "make", "Remembered “{text}”"))
register(Tool("propose_change", "propose a change to this video's cut (the owner applies or discards it); request "
              "is the change in plain words, like 'move the summit part before lunch'",
              {"type": "object", "properties": {"request": {"type": "string", "maxLength": 500}},
               "required": ["request"]}, _propose_change, "make", "Proposed a change", places=("video",)))
register(Tool("ask_agent", "hand a job to one of the owner's helper agents and get its work back",
              {"type": "object", "properties": {"agent": TEXT, "task": {"type": "string", "maxLength": 1500}},
               "required": ["agent", "task"]}, _ask_agent, "make", "Asked {agent}", for_agents=False))
register(Tool("forget", "remove something from the memory (memory: its words)",
              {"type": "object", "properties": {"memory": TEXT, "memory_id": TEXT}, "required": ["memory"]},
              _forget, "change", "Forget {memory}", preview=_forget_preview, for_agents=False))
register(Tool("rename_project", "rename a project or video",
              {"type": "object", "properties": {"project": TEXT, "name": {"type": "string", "maxLength": 120}},
               "required": ["name"]}, _rename, "change", "Rename {project} to {name}", preview=_rename_preview,
              for_agents=False))
register(Tool("delete_project", "delete a project or video and what belongs only to it",
              {"type": "object", "properties": {"project": TEXT, "kind": {"type": "string",
                                                                           "enum": ["clips", "full_video"]}}},
              _delete, "delete", "Delete {project}", preview=_delete_preview, for_agents=False))
