"""What the owner plainly asked for, read without a model, so a small model's slips do not cost the owner the answer
(docs/clipforge/CLIPFORGE_AI.md, "Guards for a small model").

The real Basic model (Qwen3-VL 2B) on GitHub's machines, Nov 26 2026, answered "Hi! How are you today?" with the very
same words, "Let me look. Here are your projects:" with none of them, "Delete the project Old gear review" with
"Let me look." and no tool, and "Ask the script writer for a title" with "[Script writer] Ask for a title …" instead
of handing the job over. The assistant (assistant.think) uses these readings:

* `handoff`: the owner asks one of their switched-on helpers by name ("ask the Critic to …", "get the Researcher to
  …"): the job goes to that helper first, and ClipForge AI reviews its work, as its rules always said.
* `guess`: one tool call for a request phrased so plainly that there is only one reading ("what projects do I have",
  "delete the project Hike" when a project is called exactly that, "how are my clips doing?", a bare link or "make
  clips from <link>"). It is used only when the model's own round did nothing with the request: no tool, and words
  that only repeat the owner, promise to look, or stop at a colon. A change it reads always shows its card and waits
  for the OK, even when ClipForge AI acts on its own (assistant.think).
* `echo`: the words only repeat the owner's message.
* `promise`: the words only say what it will look at or do ("Let me check.", "I'll write a hook. Let me think of
  a strong opening line."), sentence by sentence.

Everything here is a reading of the owner's own message; a tool it names still runs with the app's own checks, and a
change or a delete still shows its card (deleting always waits for the OK).
"""
from __future__ import annotations

import difflib
import re
import unicodedata

ECHO = 0.85          # how alike (word by word) the answer and the owner's message must be to be an echo
PROMISE_CHARS = 320  # a promise is a short answer: a long one says more than what it will do

_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_QUOTES = "\"'“”‘’«»"


def _plain_words(text: str) -> list[str]:
    """`text`'s words, without case or punctuation (a word is letters, marks and digits)."""
    out, word = [], []
    for ch in unicodedata.normalize("NFKC", str(text or "")).casefold():
        if unicodedata.category(ch)[0] in "LNM":
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def echo(said: str, owner: str) -> bool:
    """The answer only repeats the owner's message (the same words in the same order, give or take a few): "Hi! How
    are you today?" for "Hi! How are you today?", "@Script writer, write a hook" for "@Script writer write a hook"."""
    a, b = _plain_words(said), _plain_words(owner)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(b) < 3:  # "ok" for "ok", handled above; "Thanks!" for "thanks a lot" is a fine answer
        return False
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= ECHO


# A promise is the whole answer: every sentence only says what it will look at or do ("Let me look.", "One moment,
# I'll check your projects.", "I'll delete the project “Old gear review”. First, I'll check it. Let me look at it.",
# "I'll write a two-line hook. Let me think of a strong opening line."), or is a pleasantry ("Sure!", "Let me know if
# you want more."), and nothing more. "Let's get you a title: “Ride the Ridge”", "I'll be honest: the hook is weak",
# "Got it: your channel is about biking. I'll save it." and "I can see you have 3 projects." are answers.
_PROMISE = re.compile(
    r"^(?:(?:ok(?:ay)?|sure|alright|all right|of course|certainly|great|no problem|absolutely)[,!.]?\s+)?"
    r"(?:(?:one (?:moment|sec(?:ond)?)|give me a (?:moment|sec(?:ond)?)|hold on|just a (?:moment|sec(?:ond)?))"
    r"[,.!…]*\s*)?"
    r"(?:(?:first|now|then|next|so)(?:,\s*|\s+))?"
    r"(?:let me|let's|lemme|happy to|i(?:'ll| will|’ll| am going to|'m going to|’m going to| am ready to|'m ready to|"
    r"’m ready to|'d be happy to|’d be happy to| would be happy to))\s+(?:quickly\s+|just\s+|now\s+|go\s+|first\s+|"
    r"also\s+|then\s+|go ahead and\s+)?"
    r"(?:check|look|find|see|search|pull up|fetch|open|review|read|dig|go through|take a look|have a look|"
    r"ask (?:the|your|my)|get (?:that|it|your|the|those|them|back)|do (?:that|it|this|so)|take care of (?:it|that)|"
    r"handle (?:it|that)|delete|remove|rename|write|draft|make(?! sure)|create|come up with|think|plan|"
    r"put together|work on|generate|prepare|figure out|help|provide|give you|show you|list|gather|proceed)\b",
    re.I)
_NOT_PROMISE = re.compile(r"^(?:let me know|let's (?:get|make|try|go|do|start|write)\b)", re.I)
_PLEASANTRY = re.compile(r"^(?:ok(?:ay)?|sure(?: thing)?|alright|all right|of course|certainly|absolutely|great"
                         r"(?: question| idea)?|no problem|got it|happy to help|hi(?: there)?|hello(?: there)?|hey"
                         r"(?: there)?|let me know (?:if|when|what|how)\b.*)[\s!.,…]*$", re.I)
_SENTENCE = re.compile(r"(?<=[.!…])\s+")


def promise(said: str) -> bool:
    """The answer only says what it will look at or do (`_PROMISE`): every sentence does, or is a pleasantry, at
    least one says it, nothing comes after a colon, and there is no question."""
    s = " ".join((said or "").split())
    if not s or len(s) > PROMISE_CHARS or "?" in s:
        return False
    promised = False
    for part in _SENTENCE.split(s):
        if not part or _PLEASANTRY.match(part):
            continue
        if not _PROMISE.match(part) or _NOT_PROMISE.match(part) or part.rstrip(".!… ").partition(":")[2].strip():
            return False
        promised = True
    return promised


def stops_short(said: str) -> bool:
    """The answer ends where a list should begin ("Here are your projects:")."""
    return (said or "").rstrip().endswith((":", "："))


# ------------------------------------------------------------------ a helper asked by name
_ASK = re.compile(r"^(?:please\s+|hey\s+|ok(?:ay)?,?\s+)?(?:can you\s+|could you\s+|would you\s+)?"
                  r"(?:ask|get|have|let|tell|send (?:it|this|that) to|hand (?:it|this|that) to|give (?:it|this|that) to)"
                  r"\s+(?:the\s+|my\s+|our\s+)?", re.I)


def handoff(ws: str, text: str) -> tuple[dict, str] | None:
    """(the helper, the job) when the owner's message asks one of their switched-on helpers by name: "Ask the script
    writer for a title for my biking video", "Get the Critic to review this", "have my Researcher dig into trail
    building". The job is the owner's own words, so the helper reads exactly what was asked."""
    from . import agents

    raw = " ".join(str(text or "").split())
    m = _ASK.match(raw)
    if not m:
        return None
    rest = raw[m.end():]
    low = rest.casefold()
    hits = []
    for a in agents.list_(ws, enabled_only=True):
        name = a["name"].casefold()
        if low.startswith(name) and (len(low) == len(name) or not low[len(name)].isalnum()):
            hits.append(a)
    if not hits:
        return None
    agent = max(hits, key=lambda a: len(a["name"]))
    return agent, f"The owner asked: “{raw}”. Do that job now, completely."


# ------------------------------------------------------------------ one plainly asked request
_SHORT = 10  # words: a plain request is short ("how are my clips doing?"); a longer message is for the conversation
_PROJECTS = re.compile(r"^(?:(?:what|which)\s+(?:projects|videos|clips projects)\s+(?:do\s+)?i\s+(?:have|got)|"
                       r"(?:please\s+)?(?:list|show)(?:\s+me)?\s+(?:all\s+)?(?:of\s+)?my\s+(?:projects|videos)|"
                       r"my\s+projects|what\s+(?:am i working on|have i (?:made|got)))\b", re.I)
_POSTS = re.compile(r"^(?:what(?:'s|’s| is)\s+(?:scheduled|planned|coming up|going out)|"
                    r"(?:please\s+)?(?:show|list)(?:\s+me)?\s+my\s+(?:upcoming\s+|planned\s+|scheduled\s+|next\s+)?posts|"
                    r"when\s+(?:is|are)\s+my\s+next\s+posts?|what\s+posts?\s+(?:is|are)\s+(?:scheduled|planned|coming))",
                    re.I)
_WORK = re.compile(r"^(?:what(?:'s|’s| is)\s+(?:running|stuck|in the queue)|"
                   r"is\s+(?:anything|something)\s+(?:running|stuck|working)|"
                   r"(?:please\s+)?(?:show|check)(?:\s+me)?\s+(?:the\s+)?(?:work|queue|jobs)\b)", re.I)
_MISSIONS = re.compile(r"^(?:please\s+)?(?:show|list)(?:\s+me)?\s+my\s+missions|^what\s+missions\b", re.I)
_DELETE = re.compile(r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+|my\s+)?(?P<kind>project|video|clips project)\s+"
                     r"(?P<x>.+?)\s*[.!]?$", re.I)
_RENAME = re.compile(r"^(?:please\s+)?rename\s+(?:the\s+|my\s+)?(?:project\s+|video\s+)?(?P<x>.+?)\s+to\s+(?P<y>.+?)"
                     r"\s*[.!]?$", re.I)
# "make clips from <link>", "clip this <link>", "cut shorts from <link>": an order at the start, never "don't make …",
# "I already made clips from …" or "here is my short <link>, what do you think"
_MAKE = re.compile(r"^(?:please\s+)?(?:can you\s+|could you\s+)?(?:make|cut|create|get)\s+(?:me\s+)?(?:some\s+)?"
                   r"(?:clips|shorts)\s+(?:from|of|out of|for)(?:\s+(?:this|that|it))?(?:\s+video)?\s*:?\s*$|"
                   r"^(?:please\s+)?clip(?:\s+(?:this|that|it))?(?:\s+video)?\s*:?\s*$", re.I)
_NEW_NAME_NOT = re.compile(r"(?:,|\bthen\b|\band\b|^something\b|^anything\b|\bbetter\b|\bcatchier\b)", re.I)


def _name(text: str) -> str:
    return text.strip().strip(_QUOTES).strip()


def _project_named(ws: str, words: str) -> bool:
    """`words` are exactly one of the owner's project names (case and quotes aside): only then is "delete the
    project X" or "rename X to Y" plain enough to read without a model."""
    from .toolbox import projects

    want = " ".join(_plain_words(words))
    return bool(want) and any(" ".join(_plain_words(p["name"])) == want for p in projects(ws))


def guess(text: str, names: set[str] | list[str], ws: str = "") -> dict | None:
    """One tool call ({"tool", "args"}) for a request phrased so plainly that there is only one reading, among the
    tools `names` offered in this chat; None for anything else. A short message only (`_SHORT` words, no comma),
    except a link; a project to delete or rename must be named exactly as it is called (in workspace `ws`)."""
    from .chat import _RESULTS

    t = " ".join(str(text or "").split())
    have = set(names)
    if not t or "\n" in str(text or "").strip():
        return None

    def call(tool: str, args: dict | None = None) -> dict | None:
        return {"tool": tool, "args": args or {}} if tool in have else None

    links = _URL.findall(t)
    if len(links) == 1:  # a bare link, or an order to clip it: nothing else
        rest = _URL.sub(" ", t).strip(" .,!")
        if not rest or _MAKE.match(rest):
            return call("make_clips", {"link": links[0].rstrip(".,!?)")})
        return None
    if links or "," in t or len(t.split()) > _SHORT:
        return None
    if _RESULTS.match(t):
        return call("results")
    if _PROJECTS.match(t):
        return call("find_projects")
    if _POSTS.match(t):
        return call("posts")
    if _WORK.match(t):
        return call("work")
    if _MISSIONS.match(t):
        return call("missions")
    if "?" in t or not ws:  # a question about deleting or renaming is for the conversation
        return None
    m = _DELETE.match(t)
    if m and _project_named(ws, _name(m.group("x"))):
        kind = "full_video" if m.group("kind").lower() == "video" else "clips" if "clips" in m.group("kind").lower() \
            else ""
        return call("delete_project", {"project": _name(m.group("x")), **({"kind": kind} if kind else {})})
    m = _RENAME.match(t)
    if m and _project_named(ws, _name(m.group("x"))) and _name(m.group("y")) and \
            not _NEW_NAME_NOT.search(_name(m.group("y"))):
        return call("rename_project", {"project": _name(m.group("x")), "name": _name(m.group("y"))})
    return None
