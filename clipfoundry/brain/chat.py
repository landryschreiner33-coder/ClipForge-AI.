"""ClipForge AI's chat (docs/clipforge/CLIPFORGE_AI.md): one chat per video and one for everything else.

With a model set up (the built-in one, or an AI helper), everything you say goes to ClipForge AI the assistant
(assistant.py): it answers like a person, with the conversation so far, your projects and your memories, and uses
its tools (tools.py) to look things up and do things; anything that changes or deletes something waits for your OK
button (`decide`). "@Name …" talks to one of your helper agents (agents.py). Two things never need the model:
"remember: …" (with the colon, and no question in it) saves exactly your words, and "forget <the exact words>"
removes that memory; "remember that …" is a turn of the conversation, and the model saves it with its remember tool.
In a video's chat, a change the rules understand on their own ("move clip 4 before clip 2") is proposed at once.

Without a model, the rules answer alone, as before: teaching ("remember …", "always …", "never …"), forgetting,
listing what it knows, explaining the last answer; a video's chat makes change requests; a question gets the
built-in know-how that fits it, and the chat offers to set up the built-in model.

Another part of ClipForge can answer some chats itself (`route`): the new-video planner answers a draft video's chat.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Callable

from .. import db
from . import agents, allowance, assistant, knowhow, memories, tools

log = logging.getLogger("clipfoundry.brain.chat")

MAX_TEXT = 4000                 # one message (an idea or a plan can be long)
KEEP = 200                      # messages kept per chat (older ones are dropped)
CANDIDATES = 5
TOOLS = ("remember", "forget", "list", "explain", "change", "answer", "help", "talk")
HELP = ("Right now I have no model to think with, so I only follow a few rules: I remember what you tell me "
        "(\"remember: …\", \"always …\", \"never …\"), forget it (\"forget …\"), list what I know (\"what do "
        "you know about …\") and explain my last answer (\"why …\"). In a video's chat, anything else is a change I "
        "propose for you to apply or discard; here, I answer editing questions (hooks, pacing, captions, sound, "
        "music, colour, effects, picking clips, export) from my built-in know-how. Set up the built-in model (free, "
        "on this computer) and I become a real assistant: I talk with you, know your projects, do things in "
        "ClipForge when you ask, and work with your helper agents.")
NO_MODEL = ("I need a model to think with before I can really talk. Set up the built-in model (free, it runs on this "
            "computer) with the button above, or choose an AI helper in Settings → ClipForge AI. Until then I can "
            "remember, forget and list what you tell me, and answer editing questions from my built-in know-how.")
_REMEMBER = re.compile(r"^(?:please\s+)?(?:remember|note|keep in mind)(?:\s+that)?\s*[:,\-]?\s*(.+)$", re.I | re.S)
_STANDING = re.compile(r"^(?:from now on|always|never|i (?:like|love|want|prefer|hate|don't want|do not want|"
                       r"never want|always want))\b", re.I)
_RULE_WORDS = re.compile(r"\b(always|never|don't|do not|only|every|from now on|must|should|no)\b", re.I)
_FORGET = re.compile(r"^(?:please\s+)?forget(?:\s+(?:that|about|the|my|what i said about))*\s*[:,]?\s*(.*)$",
                     re.I | re.S)
_LIST = re.compile(r"^(?:what do you (?:know|remember)|what have you learned|what (?:is|'s) in your brain|"
                   r"(?:show|list)(?: me)?(?: your| my)? memor(?:y|ies))\b\s*(?:about|of|on)?\s*(.*)$", re.I | re.S)
_EXPLAIN = re.compile(r"^(?:why\b|what did you use|explain\b|how did you decide)", re.I)
_HELP = re.compile(r"^(?:help|what can you do|\?)[\s?.!]*$", re.I)
_HERE = re.compile(r"\b(?:for|in|on) this (?:video|one|project)\b|\bhere\b", re.I)

_REMEMBER_EXACT = re.compile(r"^(?:please\s+)?remember\s*:\s*(.+)$", re.I | re.S)
_FORGET_WORD = re.compile(r"^(?:please\s+)?forget\b\s*[:,]?\s*", re.I)
_lock = threading.Lock()
_decide_lock = threading.Lock()
_routes: list[tuple[Callable[[dict, dict | None], bool], Callable[[str, str, str], dict]]] = []


class ChatError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _message(value: object, limit: int) -> str:
    """What the owner wrote, tidied but keeping its lines: spaces in a line joined, at most one empty line."""
    lines = [" ".join(ln.split()) for ln in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:limit]


def _same(a: Callable, b: Callable) -> bool:
    if a is b:
        return True
    name = getattr(b, "__qualname__", "")
    return "<lambda>" not in name and (getattr(a, "__module__", None), getattr(a, "__qualname__", None)) == \
        (getattr(b, "__module__", None), name)


def route(applies: Callable[[dict, dict | None], bool], handle: Callable[[str, str, str], dict]) -> None:
    """Let another part of ClipForge answer some chats itself. `applies(chat, video)` (video: the chat's
    studio_projects row, or None for the general chat) says whether `handle(ws, project_id, text)` answers instead;
    it adds the messages itself and returns {"owner", "ai"} like `send`. The new-video planner answers a draft video's
    chat this way. Registering the same handler again replaces the earlier registration."""
    with _lock:
        _routes[:] = [r for r in _routes if not _same(r[1], handle)]
        _routes.append((applies, handle))


def _routed(chat: dict) -> Callable[[str, str, str], dict] | None:
    video = db.fetch("studio_projects", chat["project_id"]) if chat.get("project_id") else None
    for applies, handle in list(_routes):
        try:
            if applies(chat, video):
                return handle
        except Exception:  # noqa: BLE001 - a broken route never breaks the chat
            log.exception("chat route failed")
    return None


# ------------------------------------------------------------------ chats and messages
def open_chat(ws: str, project_id: str = "", create: bool = True) -> dict:
    """The chat of one video (it must be this workspace's), or the general chat; made when first opened (with
    `create`; without it, a missing chat is an error). A video deleted while its chat is opened gets no new chat:
    deleting removes the video and its chats together, so a chat made in between is removed again."""
    title = "ClipForge AI"
    if project_id:
        project = db.fetch("studio_projects", project_id)
        if not project or project["workspace_id"] != ws:
            raise ChatError("Video not found.", 404)
        title = project.get("name") or "Video"
    rows = db.select("brain_chats", "workspace_id = ? AND project_id = ?", (ws, project_id), "created_at ASC", 1)
    if rows:
        if rows[0].get("title") != title:
            db.update("brain_chats", rows[0]["id"], title=title)
        return {**rows[0], "title": title}
    if not create:
        raise ChatError("Chat not found.", 404)
    chat = db.insert("brain_chats", {"workspace_id": ws, "project_id": project_id, "title": title})
    if project_id and not db.fetch("studio_projects", project_id):  # deleted in between
        db.execute("DELETE FROM brain_chats WHERE id = ?", (chat["id"],))
        raise ChatError("Video not found.", 404)
    return chat


def get_chat(ws: str, chat_id: str) -> dict:
    row = db.fetch("brain_chats", chat_id)
    if not row or row["workspace_id"] != ws:
        raise ChatError("Chat not found.", 404)
    return row


def _view(row: dict, ws: str) -> dict:
    """A message for the page. A message about a change request shows that request as it stands now; an old-style
    change message (tool "change") also takes over the request's state once it has finished thinking."""
    out = {k: row.get(k) for k in ("id", "chat_id", "role", "text", "status", "created_at", "updated_at")}
    data = dict(row.get("data") or {})
    rid = data.get("request_id") or ""
    if rid:
        from ..studio import edit_requests as er

        try:
            req = er.view(rid, ws)
        except er.RequestError:
            req = None
        if req:
            data["request"] = req
            if data.get("tool") == "change":
                if req["status"] != "thinking" and row.get("status") == "thinking":
                    out["status"], out["text"] = "done", _request_words(req)
                    db.update("brain_chat_messages", row["id"], status="done", text=out["text"])
                elif req["status"] != "thinking" and out["text"] != _request_words(req):
                    out["text"] = _request_words(req)
    out["data"] = data
    return out


def _request_words(req: dict) -> str:
    p = req.get("proposal") or {}
    if req["status"] == "ready":
        changes = p.get("changes") or []
        lead = p.get("summary") or "Here is what I would change."
        return lead + ("\n" + "\n".join(f"- {c}" for c in changes[:12]) if changes else "") + \
            "\nApply it as a new version, or discard it."
    if req["status"] == "question":
        choices = [c.get("label") or c.get("request") for c in (p.get("choices") or []) if isinstance(c, dict)]
        return str(req.get("message") or p.get("question") or "Can you say more?") + \
            ("\n" + "\n".join(f"- {c}" for c in choices if c) if choices else "")
    if req["status"] == "applied":
        return str(req.get("message") or "Applied.")
    return str(req.get("message") or req["status"])


def messages(ws: str, chat_id: str, after: str = "", limit: int = KEEP) -> list[dict]:
    get_chat(ws, chat_id)
    rows = db.select("brain_chat_messages", "chat_id = ?", (chat_id,), "created_at ASC, rowid ASC")
    if after:
        ids = [r["id"] for r in rows]
        rows = rows[ids.index(after) + 1:] if after in ids else rows
    return [_view(r, ws) for r in rows[-max(1, min(int(limit), KEEP)):]]


def clear(ws: str, chat_id: str) -> int:
    get_chat(ws, chat_id)
    return db.execute("DELETE FROM brain_chat_messages WHERE chat_id = ?", (chat_id,))


def _add(chat: dict, role: str, text: str, data: dict | None = None, status: str = "done") -> dict:
    row = db.insert("brain_chat_messages", {"chat_id": chat["id"], "workspace_id": chat["workspace_id"], "role": role,
                                            "text": text, "data": data or {}, "status": status})
    db.update("brain_chats", chat["id"], title=chat.get("title") or "")
    extra = db.scalar("SELECT COUNT(*) FROM brain_chat_messages WHERE chat_id = ?", (chat["id"],)) - KEEP
    if extra > 0:
        db.execute("DELETE FROM brain_chat_messages WHERE id IN (SELECT id FROM brain_chat_messages WHERE chat_id = ? "
                   "ORDER BY created_at ASC, rowid ASC LIMIT ?)", (chat["id"], int(extra)))
    return row


# ------------------------------------------------------------------ what you say
def send(ws: str, chat_id: str, text: object, base_revision: int | None = None) -> dict:
    """Your message and the answer. The answer is final unless its status is `thinking`: the model is writing it in
    the background and the page polls the message, which grows as it is written."""
    chat = get_chat(ws, chat_id)
    text = _message(text, MAX_TEXT + 1)
    if not text:
        raise ChatError("Say something first.")
    if len(text) > MAX_TEXT:
        raise ChatError(f"Keep a message under {MAX_TEXT} characters.")
    handle = _routed(chat)
    if handle is not None:
        return handle(ws, chat.get("project_id") or "", text)
    if db.scalar("SELECT COUNT(*) FROM brain_chat_messages WHERE chat_id = ? AND status = 'thinking'", (chat_id,)):
        raise ChatError("I am still answering your last message. Wait for it, or press Stop.", 409)
    owner = _add(chat, "owner", text)
    try:
        reply = _answer(chat, text, base_revision)
    except (ChatError, memories.Invalid) as exc:  # a memory it cannot keep or find is said in plain words too
        reply = {"text": str(exc), "data": {"tool": "help"}, "status": "failed"}
    except Exception as exc:  # noqa: BLE001 - the chat never crashes on one message
        log.exception("chat message failed")
        reply = {"text": f"Something went wrong ({exc.__class__.__name__}); nothing was changed.",
                 "data": {"tool": "help"}, "status": "failed"}
    ai = _add(chat, reply.get("role", "ai"), reply["text"], reply.get("data"), reply.get("status", "done"))
    # The answer as it was written; a model that is started by `after` finishes it in the background (the page polls)
    out = {"owner": _view(owner, ws), "ai": _view(ai, ws)}
    if reply.get("after"):
        reply["after"](ai)
    return out


def _answer(chat: dict, text: str, base_revision: int | None) -> dict:
    ws, pid = chat["workspace_id"], chat.get("project_id") or ""
    if not assistant.ready():
        return _rules(chat, text, base_revision)
    m = _REMEMBER_EXACT.match(text)
    if m and "?" not in m.group(1):  # "remember: is my intro too long?" is a question for the conversation
        return _remember(ws, pid, m.group(1).strip())
    m = _FORGET.match(text)
    if m and m.group(1).strip():
        # the exact words of a memory, also when they start with a word the pattern skips ("forget my intro is …")
        said = {memories._norm(m.group(1)), memories._norm(_FORGET_WORD.sub("", text))}  # noqa: SLF001
        exact = [x for x in memories.list_(ws, q=m.group(1).strip(), limit=CANDIDATES)
                 if memories._norm(x["text"]) in said]  # noqa: SLF001
        if exact:
            gone = memories.forget(ws, exact[0]["id"])
            return {"text": f"Forgotten: “{gone['text']}”.", "data": {"tool": "forget", "forgotten": gone,
                                                                     "used": []}}
    mention = agents.mentioned(ws, text)
    if mention and not mention[1]:
        return {"text": f"What should {mention[0]['name']} do? Write it after the name, like “@{mention[0]['name']} "
                        "…”.", "data": {"tool": "help"}}
    if pid and not mention and len(text) <= 500:
        ruled = _rules_change(ws, pid, text, base_revision)
        if ruled:
            return ruled
    return _talk(chat, text, mention[0] if mention else None)


def _rules(chat: dict, text: str, base_revision: int | None) -> dict:
    """Without a model: the rules alone (unchanged from before ClipForge AI could talk)."""
    ws, pid = chat["workspace_id"], chat.get("project_id") or ""
    if _HELP.match(text):
        return {"text": HELP, "data": {"tool": "help"}}
    m = _REMEMBER.match(text)
    if m or _STANDING.match(text):
        return _remember(ws, pid, m.group(1).strip() if m else text)
    m = _FORGET.match(text)
    if m:
        return _forget(ws, pid, m.group(1).strip())
    m = _LIST.match(text)
    if m:
        return _list(ws, pid, m.group(1).strip())
    if _EXPLAIN.match(text):
        return _explain(ws, pid)
    if pid:
        return _change(ws, pid, text[:500], base_revision)
    return _question(ws, text)


def _rules_change(ws: str, pid: str, text: str, base_revision: int | None) -> dict | None:
    """A change the editor's rules understand completely ("move clip 4 before clip 2") is proposed at once, without
    the model; anything they do not fully understand goes to the conversation."""
    from ..studio import edit_requests as er

    video = db.fetch("studio_projects", pid)
    if not video or not video.get("plan_revision"):
        return None
    try:
        plan, _assets, _words, rows = er._context(video, video["plan_revision"])  # noqa: SLF001
        ruled = er.by_rules(text, plan, rows)
    except Exception:  # noqa: BLE001 - the rules are a shortcut; the model handles the rest
        return None
    if not ruled or not ruled.get("operations"):
        return None
    return _change(ws, pid, text, base_revision)


def _talk(chat: dict, text: str, agent: dict | None) -> dict:
    """A turn of the conversation: ClipForge AI (or the agent named with @) answers in the background."""
    from ..pipeline import llm

    ws = chat["workspace_id"]
    settings = db.get_settings()
    local = llm.is_local(settings)
    if allowance.reached(ws, settings):  # every request to an online AI counts (an answer can make several)
        return {"text": f"{allowance.message(settings)} Nothing was sent.", "data": {"tool": "talk"},
                "status": "failed"}
    label = llm.provider_label(settings)
    what = ("the conversation, the memories and know-how that fit it, your project names and the details of the "
            "projects it looks at. Never your files or their sound.")
    sent = (f"Stays on this computer: {label} answers it." if local else f"Sent over the internet to {label}: {what}")
    data: dict = {"tool": "talk", "provider": label, "sent": sent, "remote": not local}
    role = "ai"
    if agent:
        data["agent"] = agents.card(agent)
        role = "agent"
        task = agents.mentioned(ws, text)
        text = task[1] if task else text

    def after(row: dict) -> None:
        assistant.start(ws, chat, text, row["id"], agent=agent, base=data)

    return {"text": "", "data": data, "status": "thinking", "after": after, "role": role}


def _remember(ws: str, pid: str, said: str) -> dict:
    said = said.strip()
    if said.endswith(".") and not said.endswith(".."):
        said = said[:-1].rstrip()
    if not said:
        raise ChatError("Say what to remember, for example: remember that my intro is 3 seconds.")
    here = bool(pid) and bool(_HERE.search(said))
    if here:  # "for this video: …" / "… here" scopes the memory; the words themselves are not kept
        said = " ".join(_HERE.sub(" ", said).split()).strip(" :,-")
    if len(" ".join(said.split())) > memories.MAX_TEXT:
        raise ChatError(f"That is too long to remember: keep a memory under {memories.MAX_TEXT} characters.")
    kind = "rule" if _RULE_WORDS.search(said) else "fact"
    row = memories.remember(ws, said, kind=kind, source="said", project_id=pid if here else "")
    where = "this video" if here else "every video"
    return {"text": f"Remembered: “{row['text']}”. It applies to {where}. Say “forget …” to remove it.",
            "data": {"tool": "remember", "memory": memories.view(row), "used": []}}


def _forget(ws: str, pid: str, query: str) -> dict:
    if not query:
        raise ChatError("Say what to forget, for example: forget the rule about zooms.")
    found = memories.list_(ws, q=query, limit=CANDIDATES)
    exact = [m for m in found if memories._norm(m["text"]) == memories._norm(query)]
    if exact:
        gone = memories.forget(ws, exact[0]["id"])
        return {"text": f"Forgotten: “{gone['text']}”.", "data": {"tool": "forget", "forgotten": gone, "used": []}}
    if not found:
        return {"text": "I have nothing like that in my memory.", "data": {"tool": "forget", "candidates": []}}
    lines = "\n".join(f"- [{m['kind']}] {m['text']}" for m in found)
    return {"text": f"Which one? I will forget the one you pick:\n{lines}",
            "data": {"tool": "forget", "candidates": [{"id": m["id"], "kind": m["kind"], "text": m["text"]}
                                                        for m in found], "used": []}}


def _list(ws: str, pid: str, about: str) -> dict:
    about = about.strip().strip("?.!,:;").strip()
    found = memories.list_(ws, q=about, project_id=pid, limit=8) if about else \
        [m for m in memories.list_(ws, project_id=pid, limit=200) if m["enabled"] and not m["expired"]][:8]
    if not found:
        text = "I remember nothing yet. Tell me things with “remember: …”, or “always …” and “never …”."
        return {"text": text, "data": {"tool": "list", "memories": []}}
    lines = "\n".join(f"- [{m['kind']}] {m['text']}" for m in found)
    tail = "\nOpen Brain → Memory to see and edit everything."
    head = f"What I know about “{about}”:" if about else "What I remember (newest first):"
    return {"text": f"{head}\n{lines}{tail}",
            "data": {"tool": "list", "memories": [{"id": m["id"], "kind": m["kind"], "text": m["text"],
                                                   "source": m["source"]} for m in found]}}


def _explain(ws: str, pid: str) -> dict:
    """The last thing ClipForge AI answered for this video (a change request or a FilmCraft pass) and the memories
    it used; in the general chat, the last answer here."""
    if pid:
        from ..studio import edit_requests as er

        reqs = er.recent(pid, 1)
        done = db.select("brain_memories", "workspace_id = ? AND kind = 'episode' AND project_id = ? AND text LIKE "
                         "'ClipForge AI finished the edit in FilmCraft%'", (ws, pid), "created_at DESC", 1)
        if not reqs and not done:
            return {"text": "I have not changed this video yet. Ask me for a change, and I will say why I propose it.",
                    "data": {"tool": "explain", "used": []}}
        if reqs and (not done or reqs[0]["created_at"] >= done[0]["created_at"]):
            r = reqs[0]
            p = r.get("proposal") or {}
            used = r.get("memories") or []
            how = "understood on my own, without a model" if r["source"] == "rules" else f"answered by {r['provider']}"
            lines = [f"Your last request: “{r['text']}” → {r['status']}, {how}."]
            if p.get("summary"):
                lines.append(f"What I proposed: {p['summary']}")
            for c in (p.get("changes") or [])[:6]:
                lines.append(f"- {c}")
            if r.get("message") and r["status"] not in ("ready", "applied"):
                lines.append(str(r["message"]))
            lines.append("From your brain I used: " + ("; ".join(f"[{m['kind']}] {m['text']}" for m in used)
                                                       if used else "nothing (no memory fitted)."))
            know = [k for k in (r.get("knowhow") or []) if isinstance(k, dict) and k.get("title")]
            if know:
                lines.append("From my know-how I read: " + "; ".join(k["title"].lower() for k in know) + ".")
            return {"text": "\n".join(lines), "data": {"tool": "explain", "request_id": r["id"], "used": used,
                                                     "knowhow": know}}
        e = done[0]
        used = db.select("brain_memory_uses", "workspace_id = ? AND where_used = 'filmcraft' AND ref_id = ?",
                         (ws, pid), "created_at DESC", 10)
        names = []
        for u in used:
            m = db.fetch("brain_memories", u["memory_id"])
            if m and m["text"] not in names:
                names.append(f"[{m['kind']}] {m['text']}")
        return {"text": f"{e['text']}.\nFrom your brain I used: " + ("; ".join(names) if names else "nothing."),
                "data": {"tool": "explain", "used": [{"text": n} for n in names]}}
    return {"text": "Ask this in a video's chat and I will explain what I changed there and what I used. Here I "
                    "can list what I remember: say “what do you know”.", "data": {"tool": "explain", "used": []}}


def _change(ws: str, pid: str, text: str, base_revision: int | None) -> dict:
    from ..studio import edit_requests as er

    try:
        r = er.ask(pid, ws, text, base_revision)
    except er.RequestError as exc:
        raise ChatError(str(exc), exc.status) from exc
    data = {"tool": "change", "request_id": r["id"], "used": r.get("memories") or [],
            "knowhow": r.get("knowhow") or []}
    if r["status"] == "thinking":
        return {"text": f"{r['message']}…", "data": data, "status": "thinking"}
    return {"text": _request_words(r), "data": data}


def _question(ws: str, text: str) -> dict:
    """Without a model: the one playbook that fits the question well answers it on its own."""
    topic = knowhow.answer(text)
    if topic:
        return {"text": knowhow.answer_text(topic),
                "data": {"tool": "answer", "used": [], "knowhow": [{"id": topic["id"], "title": topic["title"],
                                                                    "score": topic["score"]}]}}
    return {"text": NO_MODEL, "data": {"tool": "answer", "used": [], "knowhow": [], "setup": True}}


def recover() -> int:
    """After a restart: an answer that was waiting for the model is not asked again."""
    return db.execute("UPDATE brain_chat_messages SET status = 'failed', text = 'ClipForge restarted while this was "
                      "waiting for its model. Ask again if you still want it.', updated_at = ? "
                      "WHERE status = 'thinking'", (time.time(),))


# ------------------------------------------------------------------ acting on a proposal from the chat
def _request_message(ws: str, chat_id: str, message_id: str) -> tuple[dict, str]:
    get_chat(ws, chat_id)
    row = db.fetch("brain_chat_messages", message_id)
    if not row or row["chat_id"] != chat_id:
        raise ChatError("Message not found.", 404)
    rid = (row.get("data") or {}).get("request_id") or ""
    if not rid:
        raise ChatError("This message is not a proposed change.", 409)
    return row, rid


def apply(ws: str, chat_id: str, message_id: str) -> dict:
    from ..studio import edit_requests as er

    row, rid = _request_message(ws, chat_id, message_id)
    try:
        er.apply(rid, ws)
    except er.RequestError as exc:
        raise ChatError(str(exc), exc.status) from exc
    return _view(db.fetch("brain_chat_messages", row["id"]), ws)


def discard(ws: str, chat_id: str, message_id: str) -> dict:
    from ..studio import edit_requests as er

    row, rid = _request_message(ws, chat_id, message_id)
    try:
        er.cancel(rid, ws)
    except er.RequestError as exc:
        raise ChatError(str(exc), exc.status) from exc
    return _view(db.fetch("brain_chat_messages", row["id"]), ws)


# ------------------------------------------------------------------ stopping an answer, pressing OK
def stop(ws: str, chat_id: str) -> list[dict]:
    """Stop the answer being written in this chat (it keeps what it wrote so far). Returns the chat's messages."""
    get_chat(ws, chat_id)
    for row in db.select("brain_chat_messages", "chat_id = ? AND status = 'thinking'", (chat_id,)):
        assistant.stop(row["id"])
    return messages(ws, chat_id)


def decide(ws: str, chat_id: str, message_id: str, action_id: str, do: bool) -> dict:
    """The owner's answer to a button ClipForge AI showed: `do` runs the change or delete it proposed (checked
    again now), otherwise it is skipped. A button is answered once; pressing it again returns the message as it is.
    When the action removed this very chat (its video was deleted), the answer says so with `gone`."""
    chat = get_chat(ws, chat_id)
    with _decide_lock:
        row = db.fetch("brain_chat_messages", message_id)
        if not row or row["chat_id"] != chat_id:
            raise ChatError("Message not found.", 404)
        if row.get("status") == "thinking":
            raise ChatError("Wait until I finish writing this answer.", 409)
        data = dict(row.get("data") or {})
        acts = [dict(a) for a in data.get("pending") or [] if isinstance(a, dict)]
        act = next((a for a in acts if a.get("id") == action_id), None)
        if act is None:
            raise ChatError("That button is not in this message.", 404)
        if act.get("state") != "waiting":
            return _view(row, ws)
        result = None
        if not do:
            act["state"] = "skipped"
        else:
            tool = tools.get(act.get("tool", ""))
            ctx = tools.Ctx(ws=ws, chat=chat, project_id=chat.get("project_id") or "", message_id=message_id)
            try:
                if tool is None or tool.risk not in tools.WAITS:
                    raise tools.ToolError("This action is not available any more.")
                result = tool.run(ctx, tools.check_args(tool, act.get("args") or {}, button=True))
                act["state"], act["result"] = ("done" if result.ok else "failed"), result.summary or result.text
            except tools.TryAgain as exc:  # not yet (a delete waits for running work to stop): the button stays
                act["result"] = str(exc)
            except tools.ToolError as exc:
                act["state"], act["result"] = "failed", str(exc)
            except Exception as exc:  # noqa: BLE001 - a failed action is reported on its button
                log.exception("action %s failed", act.get("tool"))
                act["state"], act["result"] = "failed", f"It failed ({exc.__class__.__name__}). Nothing else changed."
        data["pending"] = acts
        if result is not None and result.data.get("links"):
            data["links"] = [*(data.get("links") or []), *result.data["links"]]
        if result is not None and isinstance(result.data.get("memory"), dict):  # kept after the OK: its Undo chip
            data["remembered"] = [*(data.get("remembered") or []), result.data["memory"]]
        if db.fetch("brain_chat_messages", message_id) is None:  # the action deleted this chat with its video
            return {"id": message_id, "chat_id": chat_id, "gone": True, "role": "ai", "status": "done",
                    "text": act.get("result") or "", "data": {"tool": "talk", "pending": acts}}
        db.update("brain_chat_messages", message_id, data=data)
    return _view(db.fetch("brain_chat_messages", message_id), ws)
