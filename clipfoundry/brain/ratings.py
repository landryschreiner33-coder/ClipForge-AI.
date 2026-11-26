"""👍 and 👎 on ClipForge AI's answers and its helpers' (docs/clipforge/CLIPFORGE_AI.md, "Thumbs on answers").

Landry asked for an AI that is "way smarter and more useful"; the owner is the best judge of an answer, so each
answer has a thumbs up and a thumbs down, and a thumbs down takes an optional reason ("too long", "you didn't do it").
A rating lives in the answer's own message (`data.rating`: good, why, the question it answered), so it goes with
its chat: clearing or deleting the chat, or deleting the project, removes it too.

What the next answers read (`taste`, in the system prompt):

* a disliked answer to a question very like the new one, to answer differently;
* the newest reasons the owner gave for a thumbs down, to avoid (always, whatever is asked: only the reasons, never
  the question or the answer they were about);
* the liked answer to the question most like the new one (the same words, at least two of them), as an example of
  how to answer, with the tools it used first: its way of answering, never its facts, which come from the app as it
  is now.

They fit in `budget` characters (assistant.budgets: "ratings"), kept in that order: the liked example is shortened or
left out first. ClipForge AI's own answers teach ClipForge AI; a helper's (an answer to "@Name …") teach that helper
only. With learning off (learn_from_edits, the switch in Brain → Learned) the answers read none of them. Only a
model's answer (data.tool "talk") is rated: never the app's own replies or the video planner's messages.
"""
from __future__ import annotations

import time

from .. import db
from ..pipeline.text_utils import STOPWORDS
from .tools import one_line

QUESTION_CHARS = 400   # of the owner's question kept with a rating
WHY_CHARS = 300        # of a thumbs down's reason
EXAMPLE_CHARS = 600    # of a liked answer shown as an example
RECENT = 300           # newest rated answers read for one turn
REASONS = 3            # thumbs-down reasons shown
LIKE = 0.3             # how alike a liked answer's question must be (shared words / all words)
UNLIKE = 0.5           # how alike a disliked answer's question must be to be shown
MIN_SHARED = 2         # words two questions share at least
BUDGET = 1500          # characters of the system prompt, when the caller gives none
MIN_EXAMPLE = 120      # a liked answer shortened below this is left out


class RatingError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _words(text: str) -> set[str]:
    from .toolbox import _said_words

    return {w for w in _said_words(text) if len(w) > 2 and w not in STOPWORDS}


def _alike(a: set[str], b: set[str]) -> float:
    shared = len(a & b)
    return shared / len(a | b) if shared >= MIN_SHARED else 0.0


def _question(row: dict) -> str:
    """The owner's message the answer `row` answered: the newest owner message before it in its chat."""
    before = db.select("brain_chat_messages", "chat_id = ? AND role = 'owner' AND (created_at < ? OR "
                       "(created_at = ? AND rowid < (SELECT rowid FROM brain_chat_messages WHERE id = ?)))",
                       (row["chat_id"], row["created_at"], row["created_at"], row["id"]),
                       "created_at DESC, rowid DESC", 1)
    return one_line(before[0]["text"], QUESTION_CHARS) if before else ""


def rate(ws: str, chat_id: str, message_id: str, good: bool | None, why: str = "") -> dict:
    """Rate one finished answer (None takes the rating back). Returns the message as the page shows it."""
    from . import chat

    chat.get_chat(ws, chat_id)  # another workspace's chat is not found
    row = db.fetch("brain_chat_messages", message_id)
    if not row or row["chat_id"] != chat_id:
        raise RatingError("That answer is not there any more.", 404)
    if row["role"] not in ("ai", "agent") or (row.get("data") or {}).get("tool") != "talk":
        # a model's answer only: never the app's own replies (help, memories) or the video planner's (Make a video)
        raise RatingError("Only ClipForge AI's answers and its helpers' can be rated.")
    if row["status"] == "thinking":
        raise RatingError("Wait for the answer to finish first.", 409)
    rating = None if good is None else {"good": bool(good), "why": one_line(why, WHY_CHARS) if not good else "",
                                        "question": _question(row), "at": round(time.time(), 3)}
    with chat._decide_lock:  # noqa: SLF001 - an OK pressed at the same moment writes the same message's data
        now = db.fetch("brain_chat_messages", message_id)
        if not now:
            raise RatingError("That answer is not there any more.", 404)
        data = dict(now.get("data") or {})
        if rating is None:
            data.pop("rating", None)
        else:
            data["rating"] = rating
        db.update("brain_chat_messages", message_id, data=data)
    from . import learned

    # the page's view, and whether the next answers read it (learning on: Settings, as in Brain → Learned)
    return {**chat._view(db.fetch("brain_chat_messages", message_id) or now, ws),  # noqa: SLF001
            "learning": learned.on()}


def rated(ws: str, agent_id: str = "") -> list[dict]:
    """The newest rated answers of ClipForge AI (or of one helper): {good, why, question, answer, at}."""
    rows = db.select("brain_chat_messages", "workspace_id = ? AND role IN ('ai', 'agent') AND "
                     "json_extract(data, '$.tool') = 'talk' AND json_extract(data, '$.rating.good') IS NOT NULL",
                     (ws,), "updated_at DESC", RECENT)
    out = []
    for r in rows:
        data = r.get("data") or {}
        who = (data.get("agent") or {}).get("id") or ""
        if (r["role"] == "agent" and who != agent_id) or (r["role"] == "ai" and agent_id):
            continue
        rating = data.get("rating") or {}
        used = []  # the tools the answer used before it answered: a liked answer is liked with them
        for s in [*(data.get("steps") or []), *(data.get("pending") or [])]:
            name = s.get("tool") if isinstance(s, dict) and (s.get("ok") or s.get("state") == "done") else ""
            if isinstance(name, str) and name and name not in used:
                used.append(name)
        out.append({"good": bool(rating.get("good")), "why": str(rating.get("why") or ""),
                    "question": str(rating.get("question") or ""), "answer": str(r.get("text") or ""),
                    "tools": used, "at": float(rating.get("at") or 0)})
    return sorted(out, key=lambda x: -x["at"])


def taste(ws: str, text: str, agent_id: str = "", budget: int = BUDGET, settings: dict | None = None) -> str:
    """What the owner's thumbs say about answering `text`, for the system prompt, in at most `budget` characters
    ("" when nothing applies or learning is off)."""
    from . import learned

    if not learned.on(settings):
        return ""
    rows = rated(ws, agent_id)
    if not rows:
        return ""
    asked = _words(text)
    disliked = ""
    unliked = sorted(((_alike(asked, _words(r["question"])), r) for r in rows if not r["good"] and r["answer"].strip()),
                     key=lambda x: -x[0])
    if unliked and unliked[0][0] >= UNLIKE:
        r = unliked[0][1]
        why = r["why"].rstrip(".")
        disliked = ("Your answer to a question very like this one was marked not helpful (👎): "
                    f"“{one_line(r['answer'], 200)}”. Answer differently" + (f": {why}." if why else "."))
    head = "The owner marked earlier answers as not helpful (👎) and said why; avoid that:"
    reasons = [f"- “{r['why']}”" for r in rows if not r["good"] and r["why"]][:REASONS]
    liked = sorted(((_alike(asked, _words(r["question"])), r) for r in rows if r["good"] and r["answer"].strip()),
                   key=lambda x: -x[0])
    good = liked[0][1] if liked and liked[0][0] >= LIKE else None

    def size(parts: list[str]) -> int:
        return sum(len(p) + 2 for p in parts if p)

    room = budget
    if disliked and len(disliked) > room:
        disliked = ""
    room -= size([disliked])
    while reasons and size([head, *reasons]) > room:
        reasons.pop()  # the oldest reason goes first
    said = (head + "\n" + "\n".join(reasons)) if reasons else ""
    room -= size([said])
    example = ""
    if good is not None:
        first = ("An answer the owner liked (👍), to a question like this one. Answer in its way; never copy its "
                 "facts, which may be old: facts come from \"Right now\" and your tools.\n"
                 f"Owner: “{one_line(good['question'], QUESTION_CHARS)}”\n" +
                 (f"You (after using {', '.join(good['tools'][:4])}): “" if good["tools"] else "You: “"))
        whole = one_line(good["answer"], EXAMPLE_CHARS)
        fits = min(EXAMPLE_CHARS, room - len(first) - 3)
        if fits >= min(MIN_EXAMPLE, len(whole)):  # whole, or shortened to no less than MIN_EXAMPLE
            example = first + one_line(whole, fits) + "”"
    return "\n\n".join(p for p in (disliked, said, example) if p)
