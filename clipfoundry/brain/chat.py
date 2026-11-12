"""ClipForge AI's chat (docs/clipforge/CLIPFORGE_AI.md): one chat per video and one for everything else.

With a model set up (the built-in one, or an AI helper), everything you say goes to ClipForge AI the assistant
(assistant.py): it answers like a person, with the conversation so far, your projects and your memories, and uses
its tools (tools.py) to look things up and do things; anything that changes or deletes something waits for your OK
button (`decide`). "@Name …" talks to one of your helper agents (agents.py). Two things never need the model:
"remember: …" (with the colon, no question in it, and words that name something, not only "that" or "it") saves
exactly your words, and "forget <the exact words>" removes every memory that says them; "remember that …" is a turn
of the conversation, and the model saves it with its remember tool.
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
# whole words, and so is the "that" it leaves out, which goes only before a space, a colon or a comma, or before ".",
# "!", "?" or "…" that end the message or a sentence: "Notes from the shoot …", "Note-taking …", "Remember that's …"
# and "Remember that;…" keep every letter; "Remember that." leaves "." (nothing to keep) and "Remember that. My intro
# is …" the sentence after it. A colon or a comma separates right after the word or with a space after it, and a dash
# only with spaces on both sides ("note - the drone shots …"), so "Note -14 LUFS …" keeps its minus and "Remember
# that :D" its smiley
_REMEMBER = re.compile(r"^(?:please\s+)?(?:remember|note|keep in mind)(?=[\s:,])"
                       r"(?:\s+that(?=[\s:,]|[.!?…]+(?:\s|$))(?:[.!?…]+(?=\s))?)?"
                       r"(?:[:,]|\s+[:,](?!\S)|\s+-(?=\s))?\s*(.+)$", re.I | re.S)
# Words that name nothing to remember on their own ("Remember that one, please", "I like it!", "Remember that from
# now on", "Always for this video", "Never do that again"): all they do is point at something said before, ask
# nicely, say when or where, or repeat the request. They are read as turns of speech and not word by word, so a fact
# made of everyday words ("I am not in the videos", "I'm in the US", "one video at a time", "one video for every
# project", "just me") names something and is kept. When in doubt the words are kept: their answer has an Undo.
_POINTS = (r"(?:do(?:ing)? )?(?:that|this|it|these|those|them|all|everything"
           r"|(?:(?:that|this|the|these|those) )?(?:(?:last|next|other|same|one) )?(?:ones?|things?|stuff)"
           r"|(?:that|this|these|those) (?:videos?|projects?)|all (?:of )?(?:that|this|it|them|these|those))")
_ASKS = (r"please|pls|plz|thanks|thank you|thx|kindly|ok|okay|too|also|as well|just|and|for me"
         r"|(?:will|would|could|can) you|remember|forget")
_WHEN = (r"now|later|again|always|never|ever|forever|for (?:now|later|ever|good|today|tomorrow|tonight)"
         r"|from (?:now|here) on(?:wards?)?(?: out)?|(?:for )?(?:the )?(?:next|last) time|(?:this|every|each) time"
         r"|all the time|at all times|(?:for|in) (?:the )?future|going forward")
_WHERE = (r"here|everywhere|(?:for|in|on) (?:(?:all|each|every|this|that|these|those|the|my|of|next|other|future"
          r"|new) )+(?:videos?|projects?|ones?)")
_TURN = re.compile(rf"{_POINTS}|{_ASKS}|{_WHEN}|{_WHERE}")  # one turn of speech
_TURN_WORDS = 8  # none is read longer than this
_IN_MIND = re.compile(r"\b(?:keep|bear)\b(.*?)\bin mind\b")  # "keep that in mind": the request, around its words
_WORD = re.compile(r"(?:[^\W_]|')+")
_SMILEY = re.compile(r"(?<!\w)(?:[:;=][-'^o]?[()\[\]{}<>|/\\*$@DPpOo03]+|<3+)(?!\w)")  # ":D", ";-)", "<3"
_STANDING = re.compile(r"^(?:from now on|always|never(?!\s*mind\b)|i (?:like|love|want|prefer|hate|don['’]t want|"
                       r"do not want|never want|always want))\b", re.I)
_NEVER_MIND = re.compile(r"^never\s*mind[\s.!,]*$", re.I)
_RULE_WORDS = re.compile(r"\b(always|never|don['’]t|do not|only|every|from now on|must|should|no)\b", re.I)
# "forget" and the words it skips are whole words: "Forgetting captions loses viewers", "Forget-me-nots …" and "forget
# mystery music" are not "forget" + "ting captions …" or "forget my" + "stery music"; a word is skipped only with a
# space and then a word or an opening quote, so "forget that, …" and "forget that 😅 …" look for "that, …" and
# "that 😅 …"
_GOES_ON = r"(?=[^\W_]|[“\"])"  # what follows "forget" or a skipped word when the same request goes on
_FORGET = re.compile(r"^(?:please\s+)?forget(?![\w'’-])"
                     rf"(?:\s+(?:that|about|the|my|what i said about)(?=[ \t]+{_GOES_ON}))*\s*[:,]?\s*(.*)$",
                     re.I | re.S)
_LIST = re.compile(r"^(?:what do you (?:know|remember)|what have you learned|what (?:is|'s) in your brain|"
                   r"(?:show|list)(?: me)?(?: your| my)? memor(?:y|ies))\b\s*(?:about|of|on)?\s*(.*)$", re.I | re.S)
_EXPLAIN = re.compile(r"^(?:why\b|what did you use|explain\b|how did you decide)", re.I)
_HELP = re.compile(r"^(?:help|what can you do|\?)[\s?.!]*$", re.I)
# In a video's chat, words that point at this video ("this video", "this one", "here") keep a memory to it
# (`memories.points_here`), and the words are kept as they were said, with nothing cut out of them ("never zoom in
# here" does not become "never zoom"). The one thing left out is a label in front of the words, which says only where
# they apply and is set apart from them by a colon, a comma or a dash with spaces ("for this video: …", "only for
# this one, …", "for this video only – …", "here: …"). "Here, There and Everywhere" keeps every word.
_LABEL = re.compile(r"^\s*(?:(?:(?:only|just)\s+)?(?:for|in|on)\s+this\s+(?:video|one|project)(?:\s+only)?\s*"
                    r"(?:[:,]|\s[-–—](?=\s))|here\s*:)\s*", re.I)

_REMEMBER_EXACT = re.compile(r"^(?:please\s+)?remember\s*:\s*(.+)$", re.I | re.S)
# What forgets at once: "forget" and a space or a colon, then the words, which start with a letter or a digit, or
# are all in quotes (“…” or "…"). Anything else after "forget" or after a skipped word (a comma, a full stop, a dash,
# a new line, an emoji, a bracket, other quote marks, or a quote followed by more words) ends the request ("Forget
# that, keep the music low", "Forget the “🔇”, keep …", or "Forget that 😅" and the rule on the next line, set
# something aside and say the rule again): the conversation, or without a model "Which one?", answers it.
_FORGET_WORD = re.compile(rf"^(?:please\s+)?forget(?:[ \t]*:\s*|[ \t]+){_GOES_ON}", re.I)
_FORGET_SKIPS = re.compile(rf"^(?:that|about|the|my|what i said about)[ \t]+{_GOES_ON}", re.I)
# For the list to pick from only (nothing is forgotten before a pick), the words may also name their memory the way
# the help does ("forget the rule about zooms", "forget the one that says -3 dB"), or ask nicely behind it ("forget
# -3 dB here, please", "… too"): they are looked up without those as well (`_named`).
_LEADS = re.compile(r"^(?:that|about|the|my|what i said about|(?:rule|one|memory|fact|note)s?"
                    r"(?: (?:about|on|that says|saying))?)(?:[ \t]+|$)", re.I)
_POLITE = re.compile(r"(?<![\w'’-])(?:please|pls|plz|thanks|thank you|thx|too|as well|also|ok|okay)[\s.!?]*$", re.I)
_FORMS = 12  # the ways one "forget …" is read, at most: a message of nothing but skipped words is not read 1,000 ways
# what a "Which one?" button sends (“…”, around words that may have quotes of their own) or words typed in quotes
_QUOTED = re.compile(r"“(.+)”[.!]?|\"([^\"]+)\"[.!]?", re.S)
_EDGES = " \t\r\n.,;:!?-–—“”\"'‘’"  # around the words "forget …" looks for
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
    """What the owner wrote, tidied but keeping its lines: spaces in a line joined, at most one empty line. Every
    line break counts as one (a line or paragraph separator, a page break from a pasted document), so "Forget that"
    with the rule on the next line stays two lines. Half of an emoji (a message cut in the middle of one) is left
    out: it cannot be saved."""
    lines = [" ".join(ln.split()) for ln in tools.whole(str(value or "")).splitlines()]
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
def send(ws: str, chat_id: str, text: object, base_revision: int | None = None, *, choice: bool = False,
         forget: object = None) -> dict:
    """Your message and the answer. The answer is final unless its status is `thinking`: the model is writing it in
    the background and the page polls the message, which grows as it is written. `choice`: the words are a quick
    reply you pressed, which the model or the editor wrote: they never forget anything at once (a Forget card, or
    without a model "Which one?", shows what would go first). `forget`: a "Which one?" button pressed, with the
    memory's words it shows, sent apart from the message: exactly those words are forgotten (`_forget_picked`)."""
    chat = get_chat(ws, chat_id)
    text = _message(text, MAX_TEXT + 1)
    if not text:
        raise ChatError("Say something first.")
    if len(text) > MAX_TEXT:
        raise ChatError(f"Keep a message under {MAX_TEXT} characters.")
    if forget is not None and choice:  # a quick reply's words are the model's or the editor's: it never forgets
        raise ChatError("A quick reply cannot forget a memory: press the memory's own Forget button.")
    handle = _routed(chat)
    if handle is not None:
        return handle(ws, chat.get("project_id") or "", text)
    if db.scalar("SELECT COUNT(*) FROM brain_chat_messages WHERE chat_id = ? AND status = 'thinking'", (chat_id,)):
        raise ChatError("I am still answering your last message. Wait for it, or press Stop.", 409)
    owner = _add(chat, "owner", text)
    try:
        if forget is not None:
            reply = _forget_picked(ws, chat.get("project_id") or "", forget)
        else:
            reply = _answer(chat, text, base_revision, bool(choice))
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


def _answer(chat: dict, text: str, base_revision: int | None, choice: bool = False) -> dict:
    ws, pid = chat["workspace_id"], chat.get("project_id") or ""
    if not assistant.ready():
        return _rules(chat, text, base_revision, choice)
    m = _REMEMBER_EXACT.match(text)
    # "remember: is my intro too long?" is a question for the conversation, and "remember: that" (also "remember: that
    # for this video" or "remember: it from now on") points at something only the conversation can read
    if m and "?" not in m.group(1) and not _names_nothing(m.group(1)):
        return _remember(ws, pid, m.group(1).strip())
    m = _FORGET.match(text)
    if m and m.group(1).strip() and not choice:  # a quick reply's words are the model's: its Forget card shows them
        forgot = _forget_words(ws, pid, text)
        if forgot:
            return forgot
    mention = agents.mentioned(ws, text)
    if mention and not mention[1]:
        return {"text": f"What should {mention[0]['name']} do? Write it after the name, like “@{mention[0]['name']} "
                        "…”.", "data": {"tool": "help"}}
    if pid and not mention and len(text) <= 500:
        ruled = _rules_change(ws, pid, text, base_revision)
        if ruled:
            return ruled
    return _talk(chat, text, mention[0] if mention else None)


def _rules(chat: dict, text: str, base_revision: int | None, choice: bool = False) -> dict:
    """Without a model: the rules alone (unchanged from before ClipForge AI could talk)."""
    ws, pid = chat["workspace_id"], chat.get("project_id") or ""
    if _HELP.match(text):
        return {"text": HELP, "data": {"tool": "help"}}
    if _NEVER_MIND.match(text):
        return {"text": NEVER_MIND, "data": {"tool": "help"}}
    m = _REMEMBER.match(text)
    if m:
        return _remember(ws, pid, m.group(1).strip())
    m = _STANDING.match(text)
    if m:
        # "Always.", "Never again", "I like that", "Always for this video": no rule or fact of its own
        if _names_nothing(text[m.end():]):
            raise ChatError(_SAY_WHAT)
        return _remember(ws, pid, text)
    m = _FORGET.match(text)
    if m:
        return _forget(ws, pid, m.group(1), text, at_once=not choice)
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


_SAY_WHAT = "Say what to remember, for example: remember that my intro is 3 seconds."
# true of this message only: what an answer before it kept or forgot is not taken back by it
NEVER_MIND = ("All right, I did nothing with that. What I kept or forgot before stays as it is: to remove a memory, "
              "press Undo on its answer or say “forget …”.")


def _names_nothing(words: str) -> bool:
    """Words that name nothing to remember on their own: no letter or digit once smileys are left out ("😅", ":D",
    a quote mark alone), or only turns of speech that point at something said before, ask nicely, or say when or
    where ("that one, please", "this for later", "it 👍", "that from now on", "always for this video", "keep that in
    mind"): one `_TURN` after another, to the last word."""
    said = " ".join(_SMILEY.sub(" ", words).lower().replace("’", "'").split())
    said = [w for w in (w.strip("'") for w in _WORD.findall(_IN_MIND.sub(r"\1", said))) if w]
    reached = {0}  # how many of the words the turns of speech read so far account for
    for start in range(len(said)):  # a few short matches per word, however the words repeat
        if start in reached:
            reached.update(end for end in range(start + 1, min(len(said), start + _TURN_WORDS) + 1)
                           if _TURN.fullmatch(" ".join(said[start:end])))
    return len(said) in reached


def _kept_words(pid: str, said: str) -> tuple[str, bool]:
    """The words "remember …" keeps, and whether they are kept for this video only. The words are the ones said, whole
    (one full stop that ends the last word left out; one that stands alone is a mark the words name, "never end a
    caption with ."): in a video's chat "here" or "this video" only says where the memory applies
    (`memories.points_here`), and nothing is cut out of the words ("never zoom in here" stays "never zoom in here",
    kept for this video, where it is read). Only a label in front of them goes (`_LABEL`): "for this video: -14
    LUFS" keeps "-14 LUFS"."""
    said = said.strip()
    if said.endswith(".") and not said.endswith("..") and not said[-2:-1].isspace():
        said = said[:-1].rstrip()
    here = bool(pid) and bool(memories.points_here(said)[0])
    return (_LABEL.sub("", said, count=1) if here else said), here


def _as_typed(text: str) -> str:
    """Words as typed, but for case, spacing and the kind of apostrophe."""
    return " ".join(text.lower().replace("’", "'").split())


def _scope_words(scope: str, pid: str) -> str:
    """Where a memory applies, as an answer says it."""
    kind, _, value = (scope or "all").partition(":")
    if kind == "project":
        return "this video" if value == pid else "another video"
    if kind == "platform":
        return value
    if kind == "mode":
        return "clips projects" if value == "clips" else "YouTube videos"
    return "every video"


def _applies(scope: str, pid: str, words: str) -> str:
    """The sentence of an answer that says where a memory applies. Words kept for this video that may have been
    meant for every one (`memories.points_here`: they also speak of other videos or of later, or liken something to
    this one) get the reason, and how to say them for every video: with the video's name, which reads the same in
    any chat (for a piece of it, "this clip": by saying which clip)."""
    where = _scope_words(scope, pid)
    points, further = memories.points_here(words) if where == "this video" else ("", False)
    if not further:
        return f"It applies to {where}."
    instead = memories.said_instead(points)
    name = tools.one_line((db.fetch("studio_projects", pid) or {}).get("name"), 60)
    if name and instead == "the video's name":
        instead += f" (“{name}”)"
    return (f"It applies to this video only, because it says “{points}”. To keep it for every video, say {instead} "
            "instead.")


def _remember(ws: str, pid: str, said: str) -> dict:
    """The owner's own words, kept at once, with an Undo chip. A memory that already says them, as a rule or a fact,
    is written over instead (switched on, the words as said now; kept for every video, or with words that point at
    this video the one kept for this video or for every video), and then the answer says what it was before and
    offers no Undo: Undo forgets the memory, and that one was there before this answer. A memory kept for another
    video is not written over: the same words said for this video are a memory of their own (`memories.twin`).
    Whether the memory was added is read from the write itself (a new memory is revision 1)."""
    said, here = _kept_words(pid, said)
    if _names_nothing(said):  # "Remember that." points at something said before, which only the conversation reads
        raise ChatError(_SAY_WHAT)
    if len(" ".join(said.split())) > memories.MAX_TEXT:
        raise ChatError(f"That is too long to remember: keep a memory under {memories.MAX_TEXT} characters.")
    kind = "rule" if _RULE_WORDS.search(said) else "fact"
    old = memories.twin(ws, said, (kind, "fact" if kind == "rule" else "rule"), f"project:{pid}" if here else "all")
    row = memories.remember(ws, said, kind=old["kind"] if old else kind, source="said",
                            project_id=pid if here else "")
    where = _applies(row.get("scope") or "all", pid, row["text"])
    if int(row.get("revision") or 1) == 1:
        return {"text": f"Remembered: “{row['text']}”. {where} Say “forget …” to remove it.",
                "data": {"tool": "remember", "memory": memories.view(row), "used": []}}
    was = old if old and old["id"] == row["id"] else None
    notes = []
    if was and not was.get("enabled"):
        notes.append("switched on again")
    if was and was.get("source") == "guessed":
        notes.append("no longer only a guess")
    if was and (was.get("scope") or "all") != (row.get("scope") or "all"):
        notes.append(f"before, only for {_scope_words(was.get('scope') or 'all', pid)}")
    also = f" ({'; '.join(notes)})" if notes else ""
    if was and _as_typed(was["text"]) != _as_typed(row["text"]):
        said_as = f"I already had “{was['text']}”{also}; it now says “{row['text']}”."
    else:
        said_as = f"I already remember “{row['text']}”{also}."
    return {"text": f"{said_as} {where} Say “forget …” to remove it.",
            "data": {"tool": "remember", "kept": memories.view(row), "used": []}}


def _said(text: str) -> tuple[list[str], bool]:
    """The words a "forget …" message may name a memory by, longest first, and whether they were in quotes: all of
    them after "forget", then without each leading word the pattern skips in turn ("forget that my intro is …": "that
    my intro is …", "my intro is …", "intro is …"; at most `_FORMS`). Words in quotes (what a "Which one?" button
    sends) count only as they are, never shorter. None when "forget" is not followed by a space or a colon and a word
    (_FORGET_WORD), and none from a quote that more words follow ("forget the “🔇”, keep the music low" sets
    something aside)."""
    head = _FORGET_WORD.match(text)
    rest, out = (text[head.end():].strip() if head else ""), []
    while rest and len(out) < _FORMS:
        quoted = _quoted(rest)
        if quoted:
            return [quoted], True
        if not rest[0].isalnum():  # a quote that is not all of the words: a memory's words start with a word
            break
        out.append(rest)
        skip = _FORGET_SKIPS.match(rest)
        rest = rest[skip.end():].strip() if skip else ""
    return out, False


def _quoted(words: str) -> str:
    """The words inside quotes when they are all in quotes, else "". In curly quotes they run from the first “ to the
    last ”, so a button for a memory that says “Trail Notes” or "hello" sends its words whole; curly quotes inside
    must pair up, so “a” and “b” typed in one message stay two quotes, and so do "a" and "b" (straight quotes never
    hold straight ones)."""
    m = _QUOTED.fullmatch(words)
    if not m:
        return ""
    inside, depth = (m.group(1) if m.group(1) is not None else m.group(2)), 0
    for ch in inside:
        depth += 1 if ch == "“" else -1 if ch == "”" else 0
        if depth < 0:
            return ""
    return inside.strip() if depth == 0 else ""


def _forget_words(ws: str, pid: str, text: str) -> dict | None:
    """“forget …” with the exact words of a memory: every memory that says them goes, its twins too (kept for one
    video, switched off, another kind), so nothing still follows them. In a video's chat, a note another video keeps
    under the same words stays when one that says them is kept for this video or for every video: the request is
    about this video, and the answer says what stays (`memories.meant`). The words are the first of `_said` that a
    memory says: "forget my intro is 3 seconds" forgets "my intro is 3 seconds", and "intro is 3 seconds" only when
    no memory says "my intro is 3 seconds". Words in quotes go only as they are: when no memory says them (a "Which
    one?" button pressed again, or after its memory was forgotten or changed elsewhere) the answer says so and
    nothing goes. None when the message names no memory's words."""
    said, quoted = _said(text)
    for words in said:
        gone = memories.forget_words(ws, words, pid)
        if gone:
            return _forgotten(ws, pid, gone)
    if quoted:
        return _nothing_says(said[0])
    return None


def _forgotten(ws: str, pid: str, gone: list[dict]) -> dict:
    """The answer for memories that went, with how many there were, and in a video's chat how many other videos
    still keep the same words (theirs stay: `memories.meant`)."""
    n = len(gone)
    also = "" if n == 1 else f" (I had it {n} times; {'both' if n == 2 else f'all {n}'} are gone)"
    left = {r["scope"] for r in memories.saying(ws, gone[0]["text"])
            if (r["scope"] or "").startswith("project:") and r["scope"] != f"project:{pid}"} if pid else set()
    stays = "" if not left else (" Another video keeps the same words: its note stays." if len(left) == 1 else
                                 f" {len(left)} other videos keep the same words: their notes stay.")
    return {"text": f"Forgotten: “{gone[0]['text']}”{also}.{stays}",
            "data": {"tool": "forget", "forgotten": gone[0], "used": []}}


def _nothing_says(words: str) -> dict:
    return {"text": f"Nothing I remember says “{words}”, so nothing was forgotten.",
            "data": {"tool": "forget", "candidates": [], "used": []}}


def _forget_picked(ws: str, pid: str, words: object) -> dict:
    """A "Which one?" button: the words of the memory it shows, sent apart from the message, so no quote mark in them
    can change what they say. Every memory that says exactly those words goes (the list said picking them forgets
    each; in a video's chat, as typed words: not another video's own note), never one with fewer words (they are
    never cut short); when none says them any more, the answer says so and nothing goes."""
    said = " ".join(tools.whole(str(words or "")).split())
    if not said:
        raise ChatError("Say what to forget, for example: forget the rule about zooms.")
    gone = memories.forget_words(ws, said, pid)
    return _forgotten(ws, pid, gone) if gone else _nothing_says(said[:memories.MAX_TEXT])


def _named(words: str) -> list[str]:
    """What the words after "forget" may name, for the list to pick from: the words as they were typed, then without
    each leading word the request skips, in turn ("that", "the", "my", "about", and "the rule about" or "the one that
    says"), each also without a polite word behind it ("…, please", "… too"). At most `_FORMS`."""
    out, rest = [], words.strip()
    while rest and len(out) < _FORMS:
        out.append(rest)
        polite = _POLITE.search(rest)
        if polite and rest[:polite.start()].rstrip(" \t,;.!"):
            out.append(rest[:polite.start()].rstrip(" \t,;.!"))
        skip = _LEADS.match(rest)
        rest = rest[skip.end():].strip() if skip else ""
    return out[:_FORMS]


def _forget(ws: str, pid: str, query: str, text: str, at_once: bool = True) -> dict:
    """Without a model: a memory's exact words forget it at once (_forget_words); other words list the memories they
    could mean, each set of words once (its twins go with it). First in the list are the memories that say exactly
    the words named: words that start with a sign, a bracket or other quote marks ("forget -3 dB here", "forget
    «…» …") never forget at once (what follows "forget" there may set something aside), so their memory is offered.
    Then the memories that hold the words named as a part of theirs ("forget -3 dB" for "-3 dB here"; read from the
    words themselves, so a number, a short word or another script is found), then the ones the search finds like
    them. The words named are read each way `_named` gives ("forget the rule about -3 dB, please" finds it too).
    `at_once` False, for a quick reply you pressed: the list only, so nothing goes before you pick."""
    say_what = "Say what to forget, for example: forget the rule about zooms."
    if not query.strip():
        raise ChatError(say_what)
    if at_once:
        forgot = _forget_words(ws, pid, text)
        if forgot:
            return forgot
    like, named = query.strip(_EDGES), _named(query)
    like = _POLITE.sub("", like).strip(_EDGES) or like  # "forget -3 dB, thanks" looks for "3 dB"
    could = [m for words in named for m in memories.to_forget(ws, words, pid)[:1]]
    could += [m for words in named if not _names_nothing(words) and not _LEADS.fullmatch(words)  # not "about"
              for m in memories.holding(ws, words, CANDIDATES * 4)]
    found: list[list[dict]] = []
    listed: set[str] = set()
    for m in could + (memories.list_(ws, q=like, limit=CANDIDATES * 4) if like else []):
        if m["id"] in listed:
            continue
        every = memories.saying(ws, m["text"]) or [m]  # every memory that says these words, oldest first
        listed.update(r["id"] for r in every)
        found.append(memories.meant(every, pid))  # the ones a pick forgets (not another video's own note)
        if len(found) == CANDIDATES:
            break
    if not found and not like:
        raise ChatError(say_what)
    if not found:
        return {"text": "I have nothing like that in my memory.", "data": {"tool": "forget", "candidates": []}}
    lines = []
    for same in found:
        n, kinds = len(same), ", ".join(dict.fromkeys(r["kind"] for r in same))
        also = "" if n == 1 else f" ({n} times: picking it forgets {'both' if n == 2 else f'all {n}'})"
        lines.append(f"- [{kinds}] {same[0]['text']}{also}")
    return {"text": "Which one? I will forget the one you pick:\n" + "\n".join(lines),
            "data": {"tool": "forget", "candidates": [{"id": s[0]["id"], "kind": s[0]["kind"], "text": s[0]["text"]}
                                                        for s in found], "used": []}}


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
