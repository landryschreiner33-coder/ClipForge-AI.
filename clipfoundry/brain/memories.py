"""ClipForge AI's memories: the one door to what it remembers (docs/clipforge/CLIPFORGE_AI.md).

A memory is plain words with what a model needs to use it well: its kind (a standing rule, a fact, an episode of
what happened, an asset, an answer), where it came from (you said it, it watched what you did, it guessed, a brain
file), how sure it is, where it applies (every video, one video, one platform, one mode), and its meaning as numbers
(meaning.py). `recall` picks the few memories that fit a question within a model's budget, rules first;
`record_use` keeps track of which answers used which memories, so every answer can explain itself and the Brain
page can show what a memory did. Nothing here ever runs anything: memories are data for a prompt.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field

import numpy as np

from .. import config, db
from . import meaning
from .tools import whole

log = logging.getLogger("clipfoundry.brain")

FORMAT = "clipforge.brain-memories/v1"
KINDS = ("rule", "fact", "episode", "asset", "answer")
SOURCES = ("said", "did", "guessed", "imported")
CONFIDENCE = {"said": 1.0, "imported": 0.7, "did": 0.8, "guessed": 0.5}
RANK = {"said": 3, "imported": 2, "did": 1, "guessed": 0}      # the stronger source wins when twins merge
BOOST = {"said": 0.15, "did": 0.05, "guessed": -0.10, "imported": 0.0}
MODES = ("clips", "video")
WHERE = ("change_request", "filmcraft", "smart_edit", "chat", "guidance", "short_script",
         "agent")  # agent: a helper agent's job
MAX_TEXT = 600
MAX_TAGS = 12
MAX_RULES = 8
MIN_SCORE = 0.2
MIN_MEANING = 0.15              # a memory needs a word in common or this much meaning in common: boosts alone never
DUPLICATE = 0.92
GUESS_DAYS = 60                 # a guess expires unless confirmed
STALE_DAYS = 90                 # an unused guess is reported by the brain check
RECENT_S = 30 * 86400
CHECK_ROWS = 4000               # the duplicate check compares at most this many memories of one kind
MAX_IMPORT = 20000
MAX_COUNT = 10 ** 9             # a revision or a use count read from a brain file stays a number the database can hold
MAX_ID = 40                     # characters of a memory's id; a brain file's longer one is not kept
_ID = re.compile(r"[A-Za-z0-9_-]{1,%d}" % MAX_ID)
LASTING = ("rule", "fact")      # what holds from now on; the other kinds are notes of what happened or was made
HEADER = "What the owner has told ClipForge AI (standing rules first; follow them):"


CHANGED = "The memory changed while this was being saved. Try again."


class Invalid(ValueError):
    status = 422

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# What never changes what words say, so `_norm` leaves it out: full-width letters, digits and signs (typed with an
# Asian keyboard) are their plain forms, every dash and minus is "-", every apostrophe "'", and what nobody sees goes:
# the soft hyphen, the zero-width space, word joiner and byte-order mark, the marks that only set the writing
# direction, and the ones that only pick how an emoji is drawn. (The zero-width joiner and non-joiner stay: they
# make other emoji and, in Persian or Hindi, other words.)
_UNSEEN = ("\u00ad\u200b\u2060\ufeff\u200e\u200f\u061c\u180e\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
           "\ufe0e\ufe0f")
_PLAIN = {**{c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}, 0x3000: 0x20,
          **{ord(c): "-" for c in "‐‑‒–—―−﹣"}, **{ord(c): "'" for c in "’‘ʼ"}, **{ord(c): None for c in _UNSEEN}}
# The only marks `_norm` leaves out, and only at the edge of a word that has a letter or a digit: quotes and brackets
# on either side (`_around`), ¿ and ¡ in front, and behind it the marks that end a sentence or a part of one, in any
# script. Those are Unicode's own list (the property Terminal_Punctuation, as of Unicode 17: . , ; : ! ? and the
# Armenian ։, Arabic ، ؛ ؟, Devanagari ।, Ethiopic ። ፣, Khmer ។, Tibetan །, Burmese ။, Chinese 。 、, half-width ｡ ､
# and their like), written out here so that every Python reads the same list, with … and with · (what the Greek
# raised point is once composed).
_QUOTES = frozenset("'\"`´")
_OPENING = frozenset("¿¡")
_STOPS = frozenset(chr(c) for run in (
    "21 2c 2e 3a-3b 3f b7 37e 387 589 5c3 60c 61b 61d-61f 6d4 700-70a 70c 7f8-7f9 830-835 837-83e 85e 964-965 "
    "e5a-e5b f08 f0d-f12 104a-104b 1361-1368 166e 16eb-16ed 1735-1736 17d4-17d6 17da 1802-1805 1808-1809 1944-1945 "
    "1aa8-1aab 1b4e-1b4f 1b5a-1b5b 1b5d-1b5f 1b7d-1b7f 1c3b-1c3f 1c7e-1c7f 2024 2026 203c-203d 2047-2049 2cf9-2cfb "
    "2e2e 2e3c 2e41 2e4c 2e4e-2e4f 2e53-2e54 2e60-2e61 3001-3002 a4fe-a4ff a60d-a60f a6f3-a6f7 a876-a877 a8ce-a8cf "
    "a92f a9c7-a9c9 aa5d-aa5f aadf aaf0-aaf1 abeb fe12 fe15-fe16 fe50-fe52 fe54-fe57 ff01 ff0c ff0e ff1a-ff1b ff1f "
    "ff61 ff64 1039f 103d0 10857 1091f 10a56-10a57 10af0-10af5 10b3a-10b3f 10b99-10b9c 10f55-10f59 10f86-10f89 "
    "11047-1104d 110be-110c1 11141-11143 111c5-111c6 111cd 111de-111df 11238-1123c 112a9 113d4-113d5 1144b-1144d "
    "1145a-1145b 115c2-115c5 115c9-115d7 11641-11642 1173c-1173e 11944 11946 11a42-11a43 11a9b-11a9c 11aa1-11aa2 "
    "11c41-11c43 11c71 11ef7-11ef8 11f43-11f44 12470-12474 16a6e-16a6f 16af5 16b37-16b39 16b44 16d6e-16d6f "
    "16e97-16e98 1bc9f 1da87-1da8a"
).split() for c in range(int(run.split("-")[0], 16), int(run.split("-")[-1], 16) + 1))
# Scripts written without spaces between words (Thai, Lao, Tibetan, Burmese, Khmer, Chinese, Japanese), and Korean,
# whose words carry their endings: there a part of a memory's words starts and ends anywhere (`holding`).
_UNSPACED = re.compile("[\u0e00-\u0eff\u0f00-\u0fff\u1000-\u109f\u1100-\u11ff\u1780-\u17ff\u3005-\u3007\u3040-\u30ff"
                       "\u3130-\u318f\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\ua9e0-\ua9ff\uaa60-\uaa7f"
                       "\uac00-\ud7ff\uf900-\ufaff\uff66-\uff9f\U00020000-\U0003ffff]")


def _around(ch: str) -> bool:
    """A quote or a bracket, in any script."""
    return ch in _QUOTES or unicodedata.category(ch) in ("Ps", "Pe", "Pi", "Pf")


def _norm(text: object) -> str:
    """The words of a memory as they are compared: two memories with the same norm say the same thing, so one is
    written over, merged or forgotten for the other. What is left out is listed here, and nothing else is: capital
    letters, spacing, how a letter with an accent was typed (composed first), full-width forms, the kind of dash or
    apostrophe, characters nobody sees (`_PLAIN`), and around a word that has a letter or a digit its quotes and
    brackets, ¿ or ¡ in front of it and the sentence marks behind it (. , ; : ! ? … and their like in other scripts).
    Everything else counts, in any language: every letter and mark of a letter (Thai tone marks, Indic vowel signs;
    "Maßen" is not "Massen"), digits with what stands in or before them ("-3" is not "+3", "3" or "<3"; "0:42" not
    "0.42"; ".5" not "5"), signs and symbols ("EV+1" is not "EV-1", "50%" not "50", "5*" not "5"), a hyphen inside a
    word ("b-roll" is not "b roll"), emoji, and whatever stands alone between spaces, as it is: a mark a rule names
    ("never end a caption with !" is not "… with ?"), a minus set apart ("- 3 dB" is not "3 dB"), a dash or a bullet
    ("music low - voice up" is not "music low voice up"), a smiley.

    When in doubt the words count as different: two memories then stand side by side, where a wrong match would
    write one over the other or forget both. So French spacing ("basse !") makes other words than "basse!": a second
    memory at worst, never a lost one. One known limit the other way: a quote mark right after a number is a quote
    here, so 5' and 5" (feet and inches, minutes and seconds) are both 5; ′ and ″, "ft", "in", "min" and "s" are told
    apart."""
    t = unicodedata.normalize("NFC", str(text or "").translate(_PLAIN))
    t = unicodedata.normalize("NFC", t.lower())  # lower, not casefold: "Maßen" and "Massen" are two words
    words = []
    for token in t.split():
        if any(ch.isalnum() for ch in token):  # a word: its letters and digits end both loops
            start, end = 0, len(token)
            while _around(token[start]) or token[start] in _OPENING:
                start += 1
            while _around(token[end - 1]) or token[end - 1] in _STOPS:
                end -= 1
            token = token[start:end]
        words.append(token)
    return " ".join(words)


_norms_current: set[str] = set()  # the databases whose stored norms this process has brought up to date


def _refresh_norms() -> None:
    """Store every memory's norm as `_norm` makes it now, once per database in this process, so a lookup by norm
    finds every memory: one kept by an earlier build has that build's norm until then (a-z and 0-9 words only, in
    the builds released before this one), and so has one a brain file or an older build added since. One step
    under the database's write lock; a memory's words, revision and dates stay as they are."""
    path = str(config.db_path())
    if path in _norms_current:
        return
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for mid, text, norm in conn.execute("SELECT id, text, norm FROM brain_memories").fetchall():
            now = _norm(text)
            if now != norm:
                conn.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", (now, mid))
    _norms_current.add(path)


def saying(ws: str, text: object, kinds: tuple[str, ...] = KINDS) -> list[dict]:
    """Every memory of the workspace that says the same words as `text` (`_norm`) as one of these kinds, oldest first,
    wherever it applies and switched on or off. Memories an earlier build stored are found too: their stored norms
    are brought up to date first (`_refresh_norms`), and each memory found is compared again by its words."""
    _refresh_norms()
    norm = _norm(text)
    where = f"workspace_id = ? AND kind IN ({', '.join('?' for _ in kinds)}) AND norm = ?"
    rows = db.select("brain_memories", where, (ws, *kinds, norm), "created_at ASC")
    return [r for r in rows if _norm(r["text"]) == norm]


def _holds(words: str, part: str) -> bool:
    """Whether `words` hold `part` as whole words (both as `_norm` gives them): each end of the part stands at an end
    of the words or at a space, or one of the two characters that meet there belongs to a script written without
    spaces (`_UNSPACED`: "字幕" is in "字幕は黄色で", and "YouTube" in "字幕はYouTube用")."""
    at = words.find(part)
    while at >= 0:
        end = at + len(part)
        if (at == 0 or words[at - 1] == " " or _UNSPACED.match(part[0]) or _UNSPACED.match(words[at - 1])) and \
                (end == len(words) or words[end] == " " or _UNSPACED.match(part[-1]) or _UNSPACED.match(words[end])):
            return True
        at = words.find(part, at + 1)
    return False


def holding(ws: str, text: object, limit: int = 20, project_id: str = "") -> list[dict]:
    """The memories of the workspace whose words hold the words of `text` as they stand and in that order (`_norm`;
    whole words, so "3 dB" is not in "-3 dB"), newest first: what "forget …" offers when the words named are a part
    of a memory. It reads the words themselves, so it finds a memory by a number, a short word or a word in another
    script, which the search by meaning (`list_`) leaves out; in a script written without spaces between words, a
    part of the words is found wherever it stands (`_holds`). With `project_id` (asked in a video's chat), only the
    ones such a "forget" is about (`meant`), chosen before the cut to `limit`: any number of newer notes of other
    videos never hide the one that applies in this video."""
    part = _norm(text)
    if not part:
        return []
    _refresh_norms()
    with db.connect() as conn:  # the stored forms first (they are up to date), then each memory found by its words
        rows = conn.execute("SELECT id, norm, scope FROM brain_memories WHERE workspace_id = ? AND "
                            "instr(norm, ?) > 0 ORDER BY created_at DESC", (ws, part)).fetchall()
    held = meant([{"id": mid, "scope": scope} for mid, norm, scope in rows if _holds(norm, part)], project_id)
    ids = [r["id"] for r in held][:max(1, min(int(limit), 500))]
    found = {r["id"]: r for r in db.select("brain_memories", f"id IN ({', '.join('?' for _ in ids)})", ids)} \
        if ids else {}
    return [r for r in (found.get(mid) for mid in ids) if r and _holds(_norm(r["text"]), part)]


def _same_words(ws: str, kind: str, text: object, *, other_than: str = "", scope: str | None = None) -> dict | None:
    """The memory of this kind in the workspace that says the same words as `text` (`saying`), or None: the oldest.
    With `scope`, where the words are to be kept: the memory that is theirs to write over. Where a memory is kept is
    part of what it is, so one kept for another video, platform or kind of project than `scope` is left out (the
    same words said for two videos are two memories: "no captions here"); the one kept in that very place comes
    first, then one kept for every video (it stays so), then, for words to keep for every video, the oldest kept
    anywhere (it widens)."""
    rows = [r for r in saying(ws, text, (kind,)) if r["id"] != other_than]
    if scope is not None:
        rows = [r for r in rows if scope == "all" or (r["scope"] or "all") in (scope, "all")]
        rows.sort(key=lambda r: (r["scope"] != scope, (r["scope"] or "all") != "all"))  # stable: oldest of each first
    return rows[0] if rows else None


def _clean(text: object, what: str = "remember") -> str:
    out = " ".join(whole(str(text or "")).split())  # half of an emoji cannot be saved: it is left out
    if not out:
        raise Invalid(f"Say what to {what}.")
    if len(out) > MAX_TEXT:
        raise Invalid(f"Keep a memory under {MAX_TEXT} characters.")
    return out


def _scope(scope: str | None, project_id: str, platform: str, mode: str) -> str:
    if scope:
        s = str(scope).strip()
        kind, _, value = s.partition(":")
        if s == "all" or (kind in ("project", "platform", "mode") and value and len(s) <= 80
                          and (kind != "mode" or value in MODES)):
            return s
        raise Invalid("A memory applies to all, project:<id>, platform:<name> or mode:<clips|video>.")
    if project_id:
        return f"project:{project_id}"
    if platform:
        return f"platform:{platform}"
    if mode:
        if mode not in MODES:
            raise Invalid("The mode is clips or video.")
        return f"mode:{mode}"
    return "all"


def _tags(tags: object) -> list[str]:
    if not isinstance(tags, (list, tuple)):
        return []
    out = []
    for t in tags[:MAX_TAGS]:
        s = " ".join(str(t).split())[:40]
        if s and s not in out:
            out.append(s)
    return out


def view(row: dict) -> dict:
    """A memory for the API: no vector, no normalised words."""
    out = {k: v for k, v in row.items() if k not in ("meaning", "norm")}
    out["expired"] = bool(row.get("expires_at") and row["expires_at"] <= time.time())
    out["has_meaning"] = bool(row.get("meaning")) and row.get("meaning_model") == meaning.model()
    return out


# ------------------------------------------------------------------ where words apply
# Said in a video's chat, what keeps a memory to that video: words that point at it. "This video", "this project" or
# "this one", with or without "for", "in" or "on" before them; a piece of it ("this clip", "this shot", "this scene",
# "these clips"); or "here" as a word of its own, in small letters or all capitals ("no captions here, please",
# "never zoom in here"; with a capital only in front of the words, "Here: …" or "Here, …", so a title such as "Here
# Comes the Sun" is not it, and "here's" and "where" are other words). Such words can only be read in this video's
# chat: in another one "this video" means that other video, so "this video is private, never upload it again" must
# not become a rule for every video. Other things said with "this" ("this channel", "this style", "this video-game
# series") say nothing about where, and neither do words that only bring on what follows: "this one thing: …",
# "this one rule", and "here is …" or "here are …" in front of the words.
_THIS_VIDEO = re.compile(r"(?i:\bthis (?:video|project|clip|shot|scene|one(?! (?:thing|rule|fact|note|point|tip|trick"
                         r"|request|favou?r|exception|detail)s?\b))(?![\w-])"
                         r"|\bthese (?:clips|shots|scenes)(?![\w-]))|(?<![\w'’-])(?:here|HERE)(?![\w'’-])")
_HERE_FIRST = re.compile(r"here ?[:,]", re.I)
_HERE_IS = re.compile(r"here (?:is|are|comes?|goes?)\b", re.I)
# Only two turns of speech make them reach further, and then the memory is for every video: "not only" or "not just"
# right before them ("not only in this video", "not just here"), and "from here on" where it can only mean from now
# on: in front of the words, at their end or before a comma, or as "from here on out" or "from here onwards" ("put
# the logo from here on the thumbnail" speaks of this video).
_NOT_ONLY = re.compile(r"\bnot (?:only|just) (?:(?:for|in|on) )?$", re.I)
_FROM_ON = (re.compile(r"\bfrom $", re.I), re.compile(r" (?:on(?:wards?)?|out)\b", re.I))
_FROM_NOW_ON = re.compile(r" (?:on out\b|onwards?\b|(?:on|out)(?=$|[,.;:!?]))", re.I)
_BEFORE = 24  # the characters before the pointing words that these patterns read: more than the longest of them
# Words kept for this video may still have been meant as a rule for every video: when they also speak of other
# videos or of later ("every video", "all my videos", "the next ones", "never … again", "next time", "from now on",
# "in future", "starting with …", "from this video on"), or liken something to this one ("like in this video",
# "shorter than this video", "the same as here", "unlike here"). They stay with this video, the only place where
# they can be read, and the answer says why, and how to say them for every video (`chat._applies`, `toolbox._keep`).
_LIKENS = re.compile(r"\b(?:(?:like|than|unlike) (?:(?:for|in|on) )?|as (?:(?:in|on) )?)$", re.I)
_PIECE = re.compile(r"(?:clip|shot|scene)s?$", re.I)  # "from this shot on" is a place in this video
_ELSEWHERE = re.compile(
    r"\b(?:every|each|all|other|another|next|future)(?: (?:of|my|the|your|our|other|next|new|few|future))* "
    r"(?:videos?|projects?|ones?)\b|\b(?:never|don['’]t|do not|no more)\b.*\bagain\b"
    r"|\bnext time\b|\bfrom now on\b|\bin (?:the )?future\b|\bgoing forward\b"
    r"|\b(?:starting|beginning) (?:with|from)\b|\bas of\b", re.I)


def points_here(said: object) -> tuple[str, bool]:
    """What words said in a video's chat say about where they apply: the first of them that point at this video
    ("this video", "this one", "here"; "" when none do, or each only reaches further: "not only this video", "from
    here on"), and whether the words that point at it also speak of other videos or of later, or liken something to
    this one (`_THIS_VIDEO` and the patterns after it)."""
    said = " ".join(str(said or "").split())
    points, further = (said[:4] if _HERE_FIRST.match(said) else ""), False
    for m in _THIS_VIDEO.finditer(said, 4 if _HERE_IS.match(said) else 0):  # "here is the plan: …" names no place
        before = said[max(0, m.start() - _BEFORE):m.start()]
        from_on = bool(_FROM_ON[0].search(before) and _FROM_ON[1].match(said, m.end()))
        if _NOT_ONLY.search(before) or (from_on and m.group().lower() == "here"
                                        and (m.start() == 5 or _FROM_NOW_ON.match(said, m.end()))):
            continue  # "not only in this video", "not just here"; "from here on, …": from now on
        points = points or m.group()
        further = further or bool(_LIKENS.search(before)) or (from_on and not _PIECE.search(m.group()))
    return points, bool(points) and (further or bool(_ELSEWHERE.search(said)))


def said_instead(points: str) -> str:
    """What to say in place of words that point at this video, so that the words read the same in any chat and can
    be kept for every video: the video's name, or for a piece of it ("this clip", "these shots") which one."""
    piece = _PIECE.search(points)
    return f"which {piece.group().lower()}" if piece else "the video's name"


# ------------------------------------------------------------------ writing
def remember(ws: str, text: object, *, kind: str = "fact", source: str = "said", scope: str | None = None,
             project_id: str = "", platform: str = "", mode: str = "", tags: object = (), data: dict | None = None,
             confidence: float | None = None, expires_at: float | None = None) -> dict:
    """Keep a memory. The same words (as `_norm` compares them) of the same kind kept in the same place, or for every
    video, update that memory instead of adding a twin (`twin`): the stronger source and confidence win, and a
    confirmed guess no longer expires. Words to keep for every video widen the memory that says them for one video
    or platform. A memory never moves from one place to another: the same words kept for another video (or platform,
    or kind of project) are a memory of their own, so what was said for one video stays with it."""
    if kind not in KINDS:
        raise Invalid(f"A memory is one of: {', '.join(KINDS)}.")
    if source not in SOURCES:
        raise Invalid(f"A memory's source is one of: {', '.join(SOURCES)}.")
    text = _clean(text)
    scope = _scope(scope, project_id, platform, mode)
    if scope.startswith("project:"):
        project_id = scope[8:]
    elif scope.startswith("platform:"):
        platform = scope[9:]
    conf = CONFIDENCE[source] if confidence is None else max(0.0, min(1.0, float(confidence)))
    if source == "guessed" and expires_at is None:
        expires_at = time.time() + GUESS_DAYS * 86400
    norm = _norm(text)
    for _ in range(5):  # the twin changed or went between reading and writing it (Tidy, Forget, an edit): again
        old = twin(ws, text, kind, scope)
        if not old:
            break
        stronger = source if RANK[source] >= RANK[old["source"]] else old["source"]
        fields = {"text": text if RANK[source] >= RANK[old["source"]] else old["text"], "source": stronger,
                  "confidence": max(conf, float(old.get("confidence") or 0)),
                  "scope": "all" if scope == "all" or old["scope"] == "all" else scope,
                  "tags": _tags(list(old.get("tags") or []) + list(_tags(tags))),
                  "data": {**(old.get("data") or {}), **(data or {})}, "enabled": 1,
                  "expires_at": None if stronger != "guessed" else (old.get("expires_at") or expires_at),
                  "revision": int(old.get("revision") or 1) + 1}
        merged = fields["scope"]  # the video or platform it is kept for always follows its scope
        fields["project_id"] = merged[8:] if merged.startswith("project:") else ""
        fields["platform"] = merged[9:] if merged.startswith("platform:") else ""
        if fields["text"] != old["text"] or old.get("meaning_model") != meaning.model():
            fields["meaning"], fields["meaning_model"] = meaning.make(fields["text"])
        row = _write_over(old, fields)
        if row:
            return row
    else:
        raise Invalid(CHANGED, 409)
    vec, vec_model = meaning.make(text)
    row = {"workspace_id": ws, "kind": kind, "text": text, "norm": norm, "source": source, "confidence": conf,
           "scope": scope, "project_id": project_id if scope.startswith("project:") else "",
           "platform": platform if scope.startswith("platform:") else "", "tags": _tags(tags), "data": data or {},
           "meaning": vec, "meaning_model": vec_model, "enabled": 1,
           "expires_at": expires_at, "revision": 1}
    return db.insert("brain_memories", row)


def twin(ws: str, text: object, kind: str | tuple[str, ...], scope: str | None = None) -> dict | None:
    """The memory of this workspace that already says `text` (the same words, as `_norm` compares them) as this kind
    (or as one of these kinds, the first found first), or None. With `scope`, where the words are to be kept, it is
    the one `remember` writes over instead of adding a twin (`_same_words`: never one kept for another video);
    without it, the oldest that says them anywhere."""
    for k in (kind,) if isinstance(kind, str) else kind:
        row = _same_words(ws, k, text, scope=scope)
        if row:
            return row
    return None


def episode(ws: str, text: object, *, project_id: str = "", platform: str = "", data: dict | None = None,
            source: str = "did") -> dict:
    """What happened, in one line, remembered for the video it happened in."""
    return remember(ws, text, kind="episode", source=source, project_id=project_id, platform=platform, data=data)


def get(ws: str, memory_id: str) -> dict:
    row = db.fetch("brain_memories", memory_id)
    if not row or row["workspace_id"] != ws:
        raise Invalid("Memory not found.", 404)
    return row


def edit(ws: str, memory_id: str, *, text: object = None, kind: str | None = None, scope: str | None = None,
         tags: object = None, enabled: bool | None = None) -> dict:
    """The owner's change to a memory. Like `remember`, it writes only over the memory as it read it: one changed in
    between (the same words said again, Tidy) is read again and the change made on what is there now, so no two
    different memories ever share a revision; one forgotten or tidied away meanwhile answers "Memory not found."."""
    made: dict = {}  # the new words' meaning, made once (outside the write lock: an embedder can be slow)
    for _ in range(5):
        row = get(ws, memory_id)
        fields: dict = {}
        if text is not None:
            new = _clean(text)
            if new != row["text"]:
                if new not in made:
                    made[new] = meaning.make(new)
                vec, vec_model = made[new]
                fields.update(text=new, norm=_norm(new), meaning=vec, meaning_model=vec_model)
        if kind is not None:
            if kind not in KINDS:
                raise Invalid(f"A memory is one of: {', '.join(KINDS)}.")
            fields["kind"] = kind
        if scope is not None:
            s = _scope(scope, "", "", "")
            fields.update(scope=s, project_id=s[8:] if s.startswith("project:") else "",
                          platform=s[9:] if s.startswith("platform:") else "")
        if tags is not None:
            fields["tags"] = _tags(tags)
        if enabled is not None:
            fields["enabled"] = 1 if enabled else 0
        if not fields:
            return row
        if "norm" in fields or "kind" in fields:
            if _same_words(ws, fields.get("kind", row["kind"]), fields.get("text", row["text"]),
                           other_than=memory_id, scope=fields.get("scope", row["scope"])):
                raise Invalid("Another memory already says that.", 409)
        fields["revision"] = int(row.get("revision") or 1) + 1
        written = _write_over(row, fields)
        if written:
            return written
    raise Invalid(CHANGED, 409)


def confirm(ws: str, memory_id: str) -> dict:
    """A guess you agree with becomes something you said: full confidence, no expiry. Written only over the memory
    as read, like an edit: a guess said again meanwhile never undoes the confirmation."""
    for _ in range(5):
        row = get(ws, memory_id)
        written = _write_over(row, {"source": "said", "confidence": 1.0, "expires_at": None, "enabled": 1,
                                    "revision": int(row.get("revision") or 1) + 1})
        if written:
            return written
    raise Invalid(CHANGED, 409)


def _write_over(old: dict, fields: dict) -> dict | None:
    """Write `fields` over the memory `old` in one step, only while it is still as `old` was read (its revision):
    the memory as written, or None when it changed or went in between (Tidy merged it, Forget, a video's delete, an
    edit), so the caller reads it again instead of putting back what it read before (tags, expiry, its words). Every
    change of a memory's words, source or switch goes through here (remember, edit, confirm, a brain file) or holds
    the write lock while it reads and writes (Tidy), so a revision names one state of the memory."""
    enc = db._encode("brain_memories", {**fields, "updated_at": time.time()})  # noqa: SLF001
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute(f"UPDATE brain_memories SET {', '.join(f'{k} = ?' for k in enc)} WHERE id = ? AND "
                            "COALESCE(revision, 1) = ?", (*enc.values(), old["id"], int(old.get("revision") or 1))
                            ).rowcount:
            return None
        return db._decode("brain_memories", conn.execute(  # noqa: SLF001
            "SELECT * FROM brain_memories WHERE id = ?", (old["id"],)).fetchone())


CHANGED_SINCE = ("It changed since that answer (said again, edited, or switched off or on), so Undo left it as it "
                 "is. Brain → Memory shows it.")


def forget(ws: str, memory_id: str, *, words: object = None, revision: int | None = None) -> dict:
    """Delete a memory and the record of where it was used; an answer that used it keeps its own copy. One
    transaction: a use an answer records at the same moment goes with the memory or is not recorded (`record_use`),
    never left over for nothing. With `words`, only while the memory still says them (`_norm`): one changed since they
    were shown stays as it is now (409), so a Forget button never forgets words it did not show. With `revision`,
    only while the memory is still at that revision (`undo`)."""
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")  # what is checked is what goes: nothing changes it in between
        raw = conn.execute("SELECT * FROM brain_memories WHERE id = ?", (memory_id,)).fetchone()
        row = db._decode("brain_memories", raw) if raw else None  # noqa: SLF001 - read inside this transaction
        if not row or row["workspace_id"] != ws:
            raise Invalid("Memory not found.", 404)
        if revision is not None and int(row.get("revision") or 1) != revision:
            raise Invalid(CHANGED_SINCE, 409)
        if words is not None and _norm(row["text"]) != _norm(words):
            raise Invalid("The memory says other words now.", 409)
        conn.execute("DELETE FROM brain_memory_uses WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM brain_memories WHERE id = ?", (memory_id,))
    return view(row)


def undo(ws: str, memory_id: str, words: object) -> dict:
    """The Undo of a chip that said an answer kept a memory: it forgets the memory only while it is as that answer
    added it (revision 1, which every write over it, edit, switch, Tidy merge or brain file raises, and the same
    words). One changed since stays as it is (409, `CHANGED_SINCE`), and so does one an earlier build's answer wrote
    over, so Undo never forgets more than its answer added."""
    return forget(ws, memory_id, words=words, revision=1)


def meant(rows: list[dict], project_id: str = "") -> list[dict]:
    """Of memories that say the same words, the ones a "forget" asked in a video's chat (`project_id`) is about: not
    one kept for another video when one of them is kept for this video or for more than one video. The same words
    kept for two videos are two memories, and "forget no captions here" said in one video's chat is about that
    video. (When only other videos keep the words, it is about those; in the general chat, about all of them.)"""
    here = [r for r in rows if not (r["scope"] or "").startswith("project:") or r["scope"] == f"project:{project_id}"]
    return here if project_id and here else rows


def to_forget(ws: str, text: object, project_id: str = "") -> list[dict]:
    """The memories "forget" and these words are about: every memory that says them (`saying`: every kind, wherever
    it applies, switched on or off), oldest first; asked in a video's chat, as `meant` narrows them."""
    return meant(saying(ws, text), project_id)


def forget_words(ws: str, text: object, project_id: str = "") -> list[dict]:
    """Forget every memory that says `text` (`to_forget`: its twins too, so none still holds words the owner asked
    to forget; asked in a video's chat, another video's own note stays). One forgotten or changed meanwhile is left
    to that. Returns what went, oldest first."""
    gone = []
    for row in to_forget(ws, text, project_id):
        try:
            gone.append(forget(ws, row["id"], words=text))
        except Invalid:
            continue
    return gone


# ------------------------------------------------------------------ reading
def _query_terms(query: str) -> list[str]:
    return [t for t in meaning.terms(query) if "_" not in t]  # words and stems; pairs are for the vector


def _scores(query: str, rows: list[dict], project_id: str = "") -> list[tuple[float, float, float]]:
    """(score, words, meaning) per row: the share of the question's words found in the memory, weighted by how
    rare each word is in this brain, blended with the cosine of the meanings, plus the source and recency boosts."""
    q_terms = set(_query_terms(query))
    which = meaning.model()
    q_vec = meaning.embed(query, which)
    now = time.time()
    docs = [set(_query_terms(r["text"])) for r in rows]
    n = len(rows)
    idf = {t: math.log((n + 1) / (sum(1 for d in docs if t in d) + 1)) + 1.0 for t in q_terms}
    total = sum(idf.values()) or 1.0
    out = []
    for r, d in zip(rows, docs):
        words = sum(idf[t] for t in q_terms if t in d) / total if q_terms else 0.0
        vec = meaning.unpack(r.get("meaning")) if r.get("meaning_model") == which else None
        sim = max(0.0, meaning.cosine(q_vec, vec))
        score = 0.55 * words + 0.45 * sim + BOOST.get(r["source"], 0.0)
        if project_id and r.get("scope") == f"project:{project_id}":
            score += 0.10
        if max(r.get("last_used_at") or 0, r.get("created_at") or 0) > now - RECENT_S:
            score += 0.05
        out.append((score, words, sim))
    return out


def _in_scope(row: dict, project_id: str, platform: str, mode: str) -> bool:
    s = row.get("scope") or "all"
    return s == "all" or (bool(project_id) and s == f"project:{project_id}") or \
        (bool(platform) and s == f"platform:{platform}") or (bool(mode) and s == f"mode:{mode}")


def candidates(ws: str, *, project_id: str = "", platform: str = "", mode: str = "",
               kinds: tuple[str, ...] | None = None) -> list[dict]:
    """Enabled, unexpired memories that apply here."""
    rows = db.select("brain_memories", "workspace_id = ? AND enabled = 1 AND (expires_at IS NULL OR expires_at > ?)",
                     (ws, time.time()), "created_at DESC")
    return [r for r in rows if _in_scope(r, project_id, platform, mode) and (not kinds or r["kind"] in kinds)]


@dataclass
class Recall:
    """What a question recalled: the memories in the order a model should read them, and the prompt block."""
    memories: list[dict] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        return [m["id"] for m in self.memories]

    @property
    def empty(self) -> bool:
        return not self.memories

    def lines(self) -> list[str]:
        return [f"- [{m['kind']}] {m['text']}" for m in self.memories]

    def prompt(self) -> str:
        return (HEADER + "\n" + "\n".join(self.lines())) if self.memories else ""

    def snapshot(self) -> list[dict]:
        """What an answer keeps about the memories it used, even after one is forgotten."""
        return [{"id": m["id"], "kind": m["kind"], "text": m["text"], "score": round(m.get("score", 0.0), 3)}
                for m in self.memories]


def recall(query: str, ws: str, *, project_id: str = "", platform: str = "", mode: str = "",
           kinds: tuple[str, ...] | None = None, limit: int = 6, budget_chars: int = 1200,
           rules: bool = True) -> Recall:
    """The few memories a model should read for `query`: every rule that applies (the most relevant first, at most
    MAX_RULES), then the best other memories with a score of at least MIN_SCORE, cut to `limit` memories and
    `budget_chars` characters of memory lines (rules are never cut before facts). The same words are read once."""
    rows = candidates(ws, project_id=project_id, platform=platform, mode=mode, kinds=kinds)
    if not rows:
        return Recall()
    scores = _scores(query or "", rows, project_id)
    scored = [{**view(r), "score": round(s[0], 4), "words": round(s[1], 3), "meaning": round(s[2], 3)}
              for r, s in zip(rows, scores)]
    chosen: list[dict] = []
    if rules:
        standing = [m for m in scored if m["kind"] == "rule"]
        standing.sort(key=lambda m: (-m["score"], -float(m.get("confidence") or 0), -m["created_at"]))
        chosen += _once(standing)[:MAX_RULES]
    others = [m for m in scored if m["kind"] != "rule" or not rules]
    floor = meaning.min_similar()
    others = [m for m in others if m["score"] >= MIN_SCORE and (m["words"] > 0 or m["meaning"] >= floor)]
    others.sort(key=lambda m: (-m["score"], -m["created_at"]))
    chosen += _once(others)[:max(0, limit)]
    out, used = [], 0
    for m in chosen:
        line = len(f"- [{m['kind']}] {m['text']}") + 1
        if used + line > budget_chars and out:
            if m["kind"] == "rule":
                continue
            break
        out.append(m)
        used += line
    return Recall(out)


def _once(ranked: list[dict]) -> list[dict]:
    """The same words of the same kind kept twice (for every video and for this one, or two places that both apply
    here) are read once: the first of them in `ranked`, which holds only memories that fit (so a twin that does not
    fit the question never hides one that does)."""
    seen: set[tuple[str, str]] = set()
    out = []
    for m in ranked:
        key = (m["kind"], _norm(m["text"]))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def record_use(ws: str, memory_ids: list[str], where: str, ref_id: str = "") -> int:
    """An answer used these memories: remember where, and count it on each memory. A memory that is not there any
    more (forgotten, or deleted with its project while the answer was written) gets no record: its uses went with
    it, and one written after that would be left over for nothing."""
    if where not in WHERE:
        raise Invalid("Unknown place of use.")
    now = time.time()
    n = 0
    with db.connect() as conn:  # one transaction: a delete cannot come between the count and its record
        for mid in dict.fromkeys(memory_ids):
            if not mid:
                continue
            hit = conn.execute("UPDATE brain_memories SET used_count = used_count + 1, last_used_at = ? WHERE id = ? "
                               "AND workspace_id = ?", (now, mid, ws)).rowcount
            if hit:
                conn.execute("INSERT INTO brain_memory_uses (id, memory_id, workspace_id, where_used, ref_id, "
                             "created_at) VALUES (?, ?, ?, ?, ?, ?)", (db.new_id(), mid, ws, where, ref_id or "", now))
            n += hit
    return n


def uses(ws: str, memory_id: str, limit: int = 50) -> list[dict]:
    get(ws, memory_id)
    return db.select("brain_memory_uses", "memory_id = ?", (memory_id,), "created_at DESC", limit)


def list_(ws: str, q: str = "", kind: str = "", project_id: str = "", limit: int = 200) -> list[dict]:
    """Every memory, newest first; with `q`, the ones that match it, best first, each with its score. With
    `project_id`, the ones kept for that video or for every video. The scope says whom a memory is for (as for
    `recall` and a video's delete), never the project_id column by itself: the builds released before this one moved
    a memory to the video that said its words last and left that column naming the first video."""
    where, args = ["workspace_id = ?"], [ws]
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if project_id:
        where.append("scope IN (?, 'all')")
        args.append(f"project:{project_id}")
    rows = db.select("brain_memories", " AND ".join(where), args, "created_at DESC")
    if not q.strip():
        return [view(r) for r in rows[:max(1, min(int(limit), 1000))]]
    floor = meaning.min_similar()
    scored = [(s[0], r) for r, s in zip(rows, _scores(q, rows, project_id)) if s[1] > 0 or s[2] >= floor]
    scored.sort(key=lambda x: (-x[0], -x[1]["created_at"]))
    return [{**view(r), "score": round(s, 4)} for s, r in scored[:max(1, min(int(limit), 1000))]]


def closest(ws: str, q: str, project_id: str = "") -> dict | None:
    """The memory a description means that no memory says or holds ("the caption rule"): the search's best match
    (as `list_` finds and orders them), or None. Asked in a video's chat, a match that applies there (`meant`) comes
    before another video's own note when it holds a word named and at least as much of the words named as that
    note, or fits exactly as well: the chat of a video is about what holds in it, however new another video's note
    is and however close its other words are. A note of another video that holds more of the words named stays the
    best match (the owner named it), and so does one beside a match that shares no word with the request. What
    ClipForge AI only noted in this video (an episode of a change made here, an asset, an answer) comes before
    another video's rule or fact only when it holds more of the words named ("the captions size change you
    applied" names the change's log line): with no more of them ("the caption rule") the request is about
    something taught, and OK would have removed the log line instead."""
    rows = db.select("brain_memories", "workspace_id = ?", (ws,), "created_at DESC") if str(q).strip() else []
    floor = meaning.min_similar()
    found = [(s, r) for r, s in zip(rows, _scores(q, rows)) if s[1] > 0 or s[2] >= floor]
    if not found:
        return None
    found.sort(key=lambda x: (-round(x[0][0], 4), -x[1]["created_at"]))
    (score, words, _), best = found[0]
    here = {r["id"] for r in meant([r for _, r in found], project_id)}
    if best["id"] not in here:  # another video's own note, while a memory that applies in this video matches too
        taught = best["kind"] in LASTING
        for s, r in found:
            if r["id"] not in here:
                continue
            more = round(s[1], 6) > round(words, 6)  # of the words named than that note holds: the owner named it
            as_much = round(s[1], 6) == round(words, 6) and s[1] > 0 or round(s[0], 4) == round(score, 4)
            if more or as_much and (r["kind"] in LASTING or not taught):
                return view(r)
    return view(best)


# ------------------------------------------------------------------ health
def check(ws: str) -> dict:
    """How the brain is doing: counts, memories without a meaning or with an old embedder, near-duplicates (not two
    kept for different videos or platforms: each is its place's own), stale guesses, expired memories, size. `ok`
    is False when anything needs Tidy or Rebuild."""
    rows = db.select("brain_memories", "workspace_id = ?", (ws,), "created_at DESC")
    now = time.time()
    counts = {k: 0 for k in KINDS}
    sources = {s: 0 for s in SOURCES}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        sources[r["source"]] = sources.get(r["source"], 0) + 1
    missing = [r["id"] for r in rows if not r.get("meaning")]
    which = meaning.model()
    old = [r["id"] for r in rows if r.get("meaning") and r.get("meaning_model") != which]
    expired = [r["id"] for r in rows if r.get("expires_at") and r["expires_at"] <= now]
    stale = [r["id"] for r in rows if r["source"] == "guessed" and r.get("enabled") and
             max(r.get("last_used_at") or 0, r["created_at"]) < now - STALE_DAYS * 86400]
    pairs: list[list[str]] = []
    truncated = False
    for kind in KINDS:
        same = [r for r in rows if r["kind"] == kind and r.get("enabled") and r.get("meaning_model") == which
                and r.get("meaning")]
        if len(same) > CHECK_ROWS:
            same, truncated = same[:CHECK_ROWS], True
        if len(same) < 2:
            continue
        m = np.stack([meaning.unpack(r["meaning"]) for r in same])
        sim = m @ m.T
        for i in range(len(same)):
            for j in range(i + 1, len(same)):
                apart = "all" not in (same[i]["scope"], same[j]["scope"]) and same[i]["scope"] != same[j]["scope"]
                if sim[i, j] >= DUPLICATE and not apart and len(pairs) < 200:  # kept for two videos: not twins
                    pairs.append([same[i]["id"], same[j]["id"]])
    problems = []
    for code, ids, text in (
            ("missing_meaning", missing, "memories have no meaning yet (Rebuild makes it)"),
            ("old_meaning", old, "memories were embedded by an older embedder (Rebuild updates them)"),
            ("duplicates", [p[0] for p in pairs],
             "memories look like twins (review them; Tidy merges exact twins kept for the same videos)"),
            ("stale_guesses", stale, f"guesses were not used for {STALE_DAYS} days (confirm or forget them)"),
            ("expired", expired, "memories have expired (Tidy removes them)")):
        if ids:
            problems.append({"code": code, "count": len(ids), "text": f"{len(ids)} {text}", "ids": ids[:20]})
    size = sum(len(r["text"]) + len(r.get("meaning") or b"") + 200 for r in rows)
    return {"ok": not problems, "total": len(rows), "enabled": sum(1 for r in rows if r.get("enabled")),
            "counts": counts, "sources": sources, "meaning_model": which, "problems": problems,
            "duplicates": pairs[:50], "duplicates_truncated": truncated, "size_bytes": size,
            "uses": int(db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE workspace_id = ?", (ws,)) or 0),
            "checked_at": now}


def rebuild(ws: str) -> int:
    """Recompute the meaning of every memory made by another embedder (or none)."""
    n = 0
    which = meaning.model()
    for r in db.select("brain_memories", "workspace_id = ?", (ws,)):
        if r.get("meaning") and r.get("meaning_model") == which:
            continue
        vec, vec_model = meaning.make(r["text"])
        db.update("brain_memories", r["id"], meaning=vec, meaning_model=vec_model)
        n += 1
    return n


def tidy(ws: str) -> dict:
    """Remove expired memories and merge exact twins, keeping the stronger one. Twins say the same words as the same
    kind (`_norm`), apply in the same place (scope) and are switched on or off alike; the one kept stands for all of
    them (their uses, use count, last use and tags, and it expires only when the last of them would), so what
    ClipForge AI follows does not change. Twins kept for other videos, or switched on or off apart, stay as they are:
    one memory could not stand for both.

    One step nothing else comes into (it takes the database's write lock first): a guess confirmed, or a memory
    changed, forgotten or used while it runs is seen here or happens after it, never lost in between. Each memory
    goes with the record of its uses (as `forget`). Returns how many went."""
    now = time.time()
    expired = merged = 0
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for (mid,) in conn.execute("SELECT id FROM brain_memories WHERE workspace_id = ? AND expires_at IS NOT NULL "
                                   "AND expires_at <= ?", (ws, now)).fetchall():
            conn.execute("DELETE FROM brain_memory_uses WHERE memory_id = ?", (mid,))
            expired += conn.execute("DELETE FROM brain_memories WHERE id = ?", (mid,)).rowcount
        groups: dict[tuple, list[dict]] = {}
        for raw in conn.execute("SELECT * FROM brain_memories WHERE workspace_id = ? ORDER BY created_at ASC",
                                (ws,)).fetchall():
            r = db._decode("brain_memories", raw)  # noqa: SLF001 - read inside this step's own transaction
            norm = _norm(r["text"])
            if norm != r["norm"]:  # stored by an earlier build and not looked up since (`_refresh_norms`)
                conn.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", (norm, r["id"]))
            groups.setdefault((r["kind"], norm, r["scope"], bool(r["enabled"])), []).append(r)
        for twins in groups.values():
            if len(twins) < 2:
                continue
            twins.sort(key=lambda r: (-RANK[r["source"]], -float(r.get("confidence") or 0),
                                      -int(r.get("revision") or 1)))
            keep, rest = twins[0], twins[1:]
            ends = [t.get("expires_at") for t in twins]
            used = [t["last_used_at"] for t in twins if t.get("last_used_at")]
            conn.execute("UPDATE brain_memories SET used_count = ?, last_used_at = ?, tags = ?, expires_at = ?, "
                         "revision = ?, updated_at = ? WHERE id = ?",
                         (sum(int(t.get("used_count") or 0) for t in twins), max(used) if used else None,
                          json.dumps(_tags([tag for t in twins for tag in (t.get("tags") or [])])),
                          None if None in ends else max(ends), int(keep.get("revision") or 1) + 1, now, keep["id"]))
            for r in rest:
                conn.execute("UPDATE brain_memory_uses SET memory_id = ? WHERE memory_id = ?", (keep["id"], r["id"]))
                merged += conn.execute("DELETE FROM brain_memories WHERE id = ?", (r["id"],)).rowcount
    return {"expired": expired, "merged": merged}


# ------------------------------------------------------------------ files
EXPORT_FIELDS = ("id", "kind", "text", "source", "confidence", "scope", "project_id", "platform", "tags", "data",
                 "enabled", "expires_at", "used_count", "last_used_at", "revision", "created_at", "updated_at")


def export(ws: str) -> dict:
    rows = db.select("brain_memories", "workspace_id = ?", (ws,), "created_at ASC")
    return {"format": FORMAT, "exported_at": time.time(), "count": len(rows),
            "memories": [{k: r.get(k) for k in EXPORT_FIELDS} for r in rows]}


NUMBERS = ("confidence", "expires_at", "revision", "used_count", "last_used_at", "created_at")


def _number(value: object) -> float:
    """A number of a brain file: a number, or text that is one. Anything else (a date, a list, a number that is not
    finite) makes its entry invalid: stored as it was, text in "last_used_at" broke every later search."""
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        out = math.nan
    if not math.isfinite(out):
        raise Invalid("A brain file holds something that is not a number where a number belongs.")
    return out


def _on(value: object) -> int:
    """Whether a brain file's memory is switched on: "enabled" is a number (0 is off) or text that is one, and
    nothing there (null, "") is off. Anything else makes the entry invalid: read as plain text, "0" and "false"
    switched a memory back on that the owner had switched off."""
    return 0 if value is None or value == "" else int(bool(_number(value)))


def _data(value: object) -> dict:
    """A memory's extra data in a brain file: an object, kept as it is (anything else is none). A number in it that
    is not finite makes the entry invalid: it could be stored, but the brain could not be exported from then on."""
    if not isinstance(value, dict):
        return {}
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise Invalid("A brain file holds something that is not a number where a number belongs.") from None
    return value


def _file_id(m: object) -> str:
    """The id a brain file gives a memory, when it can be one: at most MAX_ID letters, digits, "-" and "_", as the
    app's own are. For any other, and for none, '': the entry is read as one without an id. Cut to fit (as it was),
    two long ids with the same start were one id and the second could never be stored; and under an id with "/" in
    it a memory had no address, so the Memory page could neither switch it off nor forget it."""
    mid = str(m.get("id") or "") if isinstance(m, dict) else ""
    return mid if _ID.fullmatch(mid) else ""


def _in_force(row: dict, now: float) -> bool:
    """Whether a memory holds as said: switched on and not only a guess (as the chat reads "already in my memory",
    `toolbox._already`), and not expired (as `candidates` reads what an answer follows)."""
    return bool(row.get("enabled")) and row.get("source") != "guessed" and \
        not (row.get("expires_at") and row["expires_at"] <= now)


def import_(ws: str, data: object) -> dict:
    """Merge a brain file: a memory with a newer revision updates the one with the same id (also when another memory
    says those words: such twins are read once, and Tidy merges those kept for the same videos and switched on or off
    alike), an unknown id is added (with a fresh id when that id belongs to another workspace) unless this brain
    keeps those words already where the file keeps them, the rest are skipped. Nothing is deleted, and a memory with
    another id is never changed: the file's memory for every video is added beside one kept for one video only
    (skipped, the rule would hold in that video alone).

    The file's changes to memories this brain has come first, and what the file adds is weighed against the brain as
    they leave it, never against a memory the file lists under an id of its own (the two were memories of their own
    where the file comes from): a backup comes back whole in whatever order it lists its memories, and the same
    file read twice adds nothing the second time. Entries without an id are told apart by their words, as are those
    whose id cannot be one (`_file_id`). An entry with something that is no number where a number belongs
    ("enabled" and the extra data included) is invalid, and the rest of the file is read; text that is a number is
    read as one."""
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("memories"), list):
        raise Invalid(f"This is not a ClipForge AI brain file ({FORMAT}).")
    if len(data["memories"]) > MAX_IMPORT:
        raise Invalid(f"A brain file holds at most {MAX_IMPORT} memories.")
    out = {"added": 0, "updated": 0, "skipped": 0, "invalid": 0}
    with db.connect() as conn:
        mine = {mid for (mid,) in conn.execute("SELECT id FROM brain_memories WHERE workspace_id = ?", (ws,))}
    listed = {_file_id(m) for m in data["memories"]} - {""}  # memories of their own where the file comes from
    fresh: set[str] = set()  # what this file added: it says nothing about what the brain kept before the file
    for m in sorted(data["memories"], key=lambda m: _file_id(m) not in mine):
        if not isinstance(m, dict) or m.get("kind") not in KINDS:
            out["invalid"] += 1
            continue
        try:
            text = _clean(m.get("text"))
            scope = _scope(m.get("scope") or "all", "", "", "")
            numbers = {k: n for k in NUMBERS if m.get(k) and (n := _number(m[k]))}  # "0" is none, as 0 is
            enabled, extra = _on(m.get("enabled", 1)), _data(m.get("data"))
        except Invalid:
            out["invalid"] += 1
            continue
        source = m.get("source") if m.get("source") in SOURCES else "imported"
        vec, vec_model = meaning.make(text)
        fields = {"kind": m["kind"], "text": text, "norm": _norm(text), "source": source,
                  "confidence": max(0.0, min(1.0, numbers.get("confidence", CONFIDENCE[source]))),
                  "scope": scope, "project_id": scope[8:] if scope.startswith("project:") else "",
                  "platform": scope[9:] if scope.startswith("platform:") else "", "tags": _tags(m.get("tags")),
                  "data": extra, "enabled": enabled,
                  "expires_at": numbers.get("expires_at"),
                  "revision": int(max(1, min(numbers.get("revision", 1), MAX_COUNT))),
                  "meaning": vec, "meaning_model": vec_model}
        for _ in range(3):  # None: the memory changed or went between reading and writing it, so again
            done = _import_one(ws, _file_id(m), fields, numbers, listed, fresh)
            if done:
                break
        out[done or "skipped"] += 1
    return out


def _import_one(ws: str, mid: str, fields: dict, numbers: dict, listed: set[str], fresh: set[str]) -> str | None:
    """One memory of a brain file: "updated" (a newer revision of one with the same id: what the owner changed on
    the other computer, so it is applied even when another memory says its words, or the replaced words would stay
    in force), "added" (an unknown id), "skipped" (not newer, or an unknown id whose words this brain keeps already:
    a memory in that very place says them, whatever the owner did with it, or one that is in force for every video,
    so adding it would change nothing), or None when the memory changed or went between reading and writing it
    (Tidy, Forget, an edit): then it is read again. `mid` is the entry's id in the file ('' for none), `listed` the
    ids the file lists and `fresh` the ids this file added: a memory that came with the file, or that the file
    lists and brought up to date or found as it is, does not make another entry of the file known (the two were
    kept side by side where the file comes from, and which of them the file lists first must not matter). An entry
    without an id is told apart by its words alone, so a line the file repeats is added once."""
    existing = db.fetch("brain_memories", mid) if mid else None
    if existing and existing["workspace_id"] == ws:
        if fields["revision"] <= int(existing.get("revision") or 1):
            return "skipped"
        return "updated" if _write_over(existing, fields) else None
    # not `_same_words`: for words to keep for every video it also finds a memory kept for one video, to widen it,
    # and a file widens nothing
    now = time.time()
    for r in saying(ws, fields["text"], (fields["kind"],)):
        if mid and r["id"] in listed:
            continue
        place = r["scope"] or "all"
        if place == fields["scope"] or (place == "all" and r["id"] not in fresh and _in_force(r, now)):
            return "skipped"
    row = {**fields, "workspace_id": ws, "used_count": int(max(0, min(numbers.get("used_count", 0), MAX_COUNT))),
           "last_used_at": numbers.get("last_used_at")}
    if mid and not existing:
        row["id"] = mid
    if "created_at" in numbers:
        row["created_at"] = numbers["created_at"]
    new = db.insert("brain_memories", row)["id"]
    fresh.add(new)
    if mid:  # under a new id when another workspace has the file's: the file's own memory all the same
        listed.add(new)
    return "added"
