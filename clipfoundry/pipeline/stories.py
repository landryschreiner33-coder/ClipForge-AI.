"""Clips → Full stories: find every story in a long recording and give each one a continuous clip that runs from
where the story starts to where the next one starts (local and deterministic; ClipForge AI's model may check the
boundaries the rules are least sure of, inside a time budget, when one is set up).

The whole transcript is analysed in overlapping chunks (so the same code bounds the context a model would get);
boundaries found by neighbouring chunks are reconciled globally, and a chunk edge never creates a boundary, so a story
that crosses a chunk stays one story. A boundary needs evidence: wording that opens or closes a story, the narrator's
own separator phrase ("Next story", "Story number three", learned from the recording itself), numbering, a change of
topic, a change between story and intro/sponsor/outro material, or a real pause together with one of those. Silence
alone is never enough, and an update, an edit or a comment read after a story never starts a new one.

Every story becomes a clip; nothing waits for the owner. A story's clip keeps everything said until the next story
starts (the narrator's remarks after it included), with only the intro, sponsor reads and the outro kept out.
Stories whose boundaries are weak or cut off at the end of the recording are labelled so the owner can check them
later; the label never holds a clip back. This is an estimate from pauses and wording; it is labelled as such and
never presented as semantic understanding.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import statistics

import numpy as np
import time
from collections import defaultdict
from typing import Callable

from . import semantic
from .text_utils import STOPWORDS, cosine, tf_vector

METHOD = "local estimate from pauses, wording, the narrator's own separators and topic change"
CHUNK_S = 360.0
STEP_S = 300.0          # chunks overlap by CHUNK_S - STEP_S seconds
EDGE_S = 20.0           # context this close to a chunk edge is incomplete; the neighbouring chunk decides
THRESHOLD = 0.5
STRONG = 0.75           # needed away from the narrator's separators once those are known
NEAR = 0.2              # a candidate with this much evidence is worth asking ClipForge AI about
MERGE_S = 2.0
MIN_STORY_S = 12.0      # shorter unlabelled talk next to intro/sponsor/outro material is part of that material
LEAD_S = 0.4            # a story's clip starts this long before its first word when the pause allows
TAIL_S = 1.0            # and the last story keeps this much of the recording's tail

# Deliberate words for "here comes the next story" (strong), and the ways a story tends to begin (weak).
STRONG_OPENERS = [r"\bstory (number |no\.? |#)?(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b",
           r"^(the|my|our|this|and the|now the|and now,? the|so the|okay,? the|alright,? the|here'?s the) "
           r"(next|second|third|fourth|fifth|last|final|first) (story|one|post|tale)\b",
           r"^(here'?s|this is|now for|time for|on to|onto) (a|another|the|our) (next |last |final |second |third )?(story|one|post)\b",
           r"^(next|another|last|final) (story|one|post)\b",
           r"^(okay|ok|alright|right|so|and|now|anyway|anyways),? (so |then |now )?(next|moving on|on to|onto|story|let'?s move|number)\b",
           r"^moving on\b", r"^(let me tell you|i'?m going to tell you|i'?ll tell you) (about|a)\b",
           r"^(this|the next|our next|this next|the last|the final) (one|story|post) (is|was|comes|is titled|is called|is from|was posted)\b",
           r"^(posted|submitted|written|sent in) by\b", r"^(reddit )?user \w+ (asks|says|writes|posted|wrote)\b",
           r"^(from|in|over on) (the )?(subreddit|r/|r slash|are slash)\b", r"\br/\w+", r"\b(r|are) slash \w+",
           r"^(aita|aitah|wibta|wibtah|tifu)\b", r"^(am i the (asshole|a-hole|ahole|jerk)|today i (fucked|messed|screwed) up|would i be the (asshole|a-hole))\b",
           r"^(the )?title (is|says|reads)\b", r"^(this one'?s|this one is) (titled|called|about)\b",
           r"^(okay|ok|alright|right),? (so )?(next|story)\b"]
WEAK_OPENERS = [r"^so,? (this|one) (one )?time\b", r"^(another|one) time\b", r"^it all (started|began)\b",
                r"^(back in|years ago|a few years ago|when i was)\b", r"^once upon a time\b",
                r"^i remember (when|the)\b", r"^this (one )?happened\b"]
OPENERS = STRONG_OPENERS + WEAK_OPENERS
CLOSERS = [r"\b(and )?that'?s (how|why|the story|what happened)\b", r"\bthe end\b", r"\bmoral of the story\b",
           r"\b(never|ever) (again|since)\b", r"\bto this day\b", r"\b(and|so) that was (it|that)\b",
           r"\bi learned (that|my lesson|to)\b", r"\bend of (the )?story\b", r"\bthat'?s (the end|all) of (that|this) (one|story)\b"]
# A sentence that reads like the title of a post or the first line of a story (one more sign, never enough alone).
TITLE_STARTS = [r"^(aita|aitah|wibta|wibtah|tifu)\b",
                r"^(am|was|would|should|is|are|do|does|did|how|why|what|can|could) (i|it|my|we|he|she|they)\b",
                r"^(my|our) (\w+ ){1,4}(is|was|are|were|keeps|kept|won'?t|wants|wanted|refuses|refused|thinks|said|told|"
                r"has|had|got|made|makes|does|did|caught|found|called|left|screamed|yelled|cheated|lied|wont)\b"]
# Read after a story, these continue it: an update, an edit, the comments. Never a new story.
CONTINUATIONS = [r"^(update|edit|final update|small update|quick update|tl;?dr|tldr)\b",
                 r"^(op|the (original )?poster) (replied|said|here|responded|added|wrote)\b",
                 r"^(top|first|second|next|another|a|one|the top|the next) (comment|reply|commenter|response)\b",
                 r"^(comment|comments|reply|replies|response)\b", r"^(someone|somebody|another (user|person)|a (user|person)) "
                 r"(said|replied|commented|asked|wrote|responded)\b", r"^(and )?then (he|she|they) (replied|responded)\b"]
GAP_KINDS = {
    "intro": [r"\b(hey|hi|hello),? (everyone|everybody|guys|friends)\b", r"\bwelcome (back )?to\b",
              r"\bin (this|today'?s) video\b", r"\btoday i('?m| am| have| want)\b", r"\btoday'?s (stories|video)\b"],
    "sponsor": [r"\bsponsor(ed)?\b", r"\bbrought to you by\b", r"\buse (my |the )?code\b",
                r"\blink in the description\b", r"\bpromo\b", r"\bdiscount\b"],
    "transition": [r"\bthat one still\b", r"\bgrab a (drink|snack|coffee)\b", r"\bthe (last|next) one is\b",
                   r"\b(moving on|let'?s move on)\b", r"\bbefore (we|i) (get to|move on to)\b"],
    "outro": [r"\bthanks? (you )?for (watching|listening)\b", r"\bsee you (next time|soon|in the next|guys|all)\b",
              r"\b(like and )?subscribe\b", r"\bthat'?s (all|it) for today\b", r"\bcomment below\b",
              r"\bthat'?s (all|it) (for )?(the stories|for now|from me)\b"],
}
# Words that belong to a separator phrase; a learned phrase needs one of them, or to be said on its own.
SEPARATOR_WORDS = {"story", "stories", "post", "posts", "next", "number", "another", "last", "final", "first",
                   "second", "third", "submission", "confession", "tale", "#", "reddit", "subreddit", "user",
                   "posted", "titled", "title", "entry", "episode", "chapter", "part"}
NUMBER_WORDS = {w: n for n, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                            "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                                            "sixteen", "seventeen", "eighteen", "nineteen", "twenty"])}
ORDINALS = {w: n for n, w in enumerate(["zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                                        "eighth", "ninth", "tenth", "eleventh", "twelfth"])}
_NUMBERED = re.compile(r"^(?:(?:okay|ok|alright|so|and|now|next|the|on to|onto|here'?s)[,.]?\s+)*"
                       r"(?:(?:story|number|post|no\.?|#|part|entry|tale|submission|confession)\s*)+"
                       r"(\d{1,3}|[a-z]+)\b", re.I)
_ORDINAL = re.compile(r"^(?:(?:okay|ok|alright|so|and|now)[,.]?\s+)*(?:the |my |our )?([a-z]+) (?:story|post|tale|one\b)", re.I)
_BARE_NUMBER = re.compile(r"^(?:number |no\.? |#)?(\d{1,3}|[a-z]+)[.!:]?$", re.I)
NUMBER_SPACING_S = 30.0  # "the first one... the second one" seconds apart is a list inside a story, not its number


def _match(patterns: list[str], text: str) -> bool:
    t = text.lower().strip(" \"'")
    return any(re.search(p, t) for p in patterns)


def gap_kind(text: str) -> str:
    return next((k for k, pats in GAP_KINDS.items() if _match(pats, text)), "")


def title_like(text: str) -> bool:
    """Short and shaped like a post title or a story's first line."""
    t = text.strip().strip("\"'")
    return len(t.split()) <= 25 and (t.endswith("?") or _match(TITLE_STARTS, t))


def continues(text: str) -> bool:
    """An update, an edit or the comments of the same story: the story goes on."""
    return _match(CONTINUATIONS, text)


def _start_tokens(text: str, n: int) -> tuple[str, ...]:
    toks = re.findall(r"[a-z0-9'#]+", text.lower().replace("’", "'"))
    toks = ["#" if t.isdigit() or t in NUMBER_WORDS or t in ORDINALS else t for t in toks]
    return tuple(toks[:n])


def separators(sents: list[dict]) -> dict[int, str]:
    """Sentences that repeat the narrator's own way of moving to the next story ("Next story", "This one is from",
    "Story number three"), learned from the recording: a short phrase said at the start of a sentence three times
    or more, well apart. Returns sentence index → the phrase."""
    hits: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for k, s in enumerate(sents):
        toks = _start_tokens(s["text"], 3)
        for n in (2, 3):
            if len(toks) >= n:
                prefix = toks[:n]
                if any(t not in STOPWORDS for t in prefix):
                    hits[prefix].append(k)
    out: dict[int, str] = {}
    for prefix, ks in sorted(hits.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if len(ks) < 3:
            continue
        times = [sents[k]["start"] for k in ks]
        spacing = [t2 - t1 for t1, t2 in zip(times, times[1:])]
        if min(spacing) < 20.0 or statistics.median(spacing) < 45.0:
            continue
        short = sum(1 for k in ks if len(sents[k]["text"].split()) <= 8)
        if not (set(prefix) & SEPARATOR_WORDS) or short * 2 < len(ks):
            continue  # "The next day" three times is a story, not a separator
        for k in ks:
            out.setdefault(k, " ".join(prefix).replace("#", "N"))
    return out


def _number_of(text: str) -> tuple[int, bool] | None:
    """The story number a sentence announces, and whether it is a bare number ("Three.") rather than a labelled
    one ("Story three", "the third story")."""
    t = text.lower().strip(" \"'")
    m = _NUMBERED.match(t)
    if m:
        tok = m.group(1)
        n = int(tok) if tok.isdigit() else NUMBER_WORDS.get(tok) or ORDINALS.get(tok)
        return (n, False) if n else None
    m = _ORDINAL.match(t)
    if m and (not t[m.start(1):].split()[1].startswith("one") or len(t.split()) <= 4):
        n = ORDINALS.get(m.group(1)) or NUMBER_WORDS.get(m.group(1))
        return (n, False) if n else None
    m = _BARE_NUMBER.match(t) if len(t.split()) <= 3 else None
    if m:
        tok = m.group(1)
        n = int(tok) if tok.isdigit() else NUMBER_WORDS.get(tok)
        return (n, not t.startswith(("number", "no", "#"))) if n else None
    return None


def numbered(sents: list[dict]) -> dict[int, int]:
    """Sentences that count the stories ("Story one", "Number two", "the third story"), in increasing order and
    well apart; "the first one, the second one" inside a story is not counted, and bare numbers ("Three.") only
    count when there are three or more of them. Returns sentence index → number."""
    seq: list[tuple[int, int, bool]] = []
    for k, s in enumerate(sents):
        got = _number_of(s["text"])
        if not got or got[0] <= 0:
            continue
        if seq and (got[0] <= seq[-1][1] or s["start"] - sents[seq[-1][0]]["start"] < NUMBER_SPACING_S):
            continue
        seq.append((k, got[0], got[1]))
    labelled = sum(1 for _k, _n, bare in seq if not bare)
    if len(seq) < 2 or (labelled == 0 and len(seq) < 3):
        return {}
    return {k: n for k, n, _bare in seq}


def marks_of(sents: list[dict]) -> dict[int, str]:
    """Sentence index → 'separator' or 'number' (the strongest evidence of a new story)."""
    out = {k: "separator" for k in separators(sents)}
    out.update({k: "number" for k in numbered(sents)})
    return out


def _cohesion(sents: list[dict], i: int, lo: int, hi: int) -> float:
    before = " ".join(s["text"] for s in sents[max(lo, i - 5):i + 1])
    after = " ".join(s["text"] for s in sents[i + 1:min(hi + 1, i + 7)])
    return cosine(tf_vector(before), tf_vector(after))


def meaning_shifts(sents: list[dict], emb) -> tuple[np.ndarray, np.ndarray] | None:
    """With the meaning model: for every gap between sentences, how much the six sentences after it still talk
    about what the six before it talked about (calibrated cosine), and how unusual that is for this recording (a
    robust z-score). None with word-based vectors (the word cohesion above already covers those)."""
    if emb is None or getattr(emb, "model", "lexical") == "lexical" or len(sents) < 8 or not len(emb):
        return None
    n = len(sents)
    arr = np.asarray(emb, dtype=np.float32)
    sums = np.cumsum(np.vstack([np.zeros((1, arr.shape[1]), dtype=np.float32), arr]), axis=0)
    shifts = np.zeros(n - 1, dtype=np.float32)
    for i in range(n - 1):
        a = sums[i + 1] - sums[max(0, i - 5)]
        b = sums[min(n, i + 7)] - sums[i + 1]
        shifts[i] = semantic.cos_cal(emb, a, b)
    med = float(np.median(shifts))
    mad = float(np.median(np.abs(shifts - med))) * 1.4826 or float(np.std(shifts)) or 1e-6
    return shifts, (shifts - med) / mad


def _boundary(sents: list[dict], i: int, lo: int, hi: int, marks: dict[int, str], baseline: float = 0.0,
              meaning: tuple[float, float] | None = None) -> dict:
    """Evidence for a boundary between sentence i and i+1, using only sentences lo..hi (one chunk's context).
    `baseline` is the chunk's usual cohesion, so a dip below it counts as a change of topic too. `meaning` is the
    meaning model's (shift, z) for this gap when it is available (meaning_shifts)."""
    a, b = sents[i], sents[i + 1]
    gap = max(0.0, b["start"] - a["end"])
    cohesion = _cohesion(sents, i, lo, hi)
    mark = marks.get(i + 1)
    strong = bool(mark) or _match(STRONG_OPENERS, b["text"])
    opener = strong or _match(WEAK_OPENERS, b["text"])
    closer = _match(CLOSERS, a["text"])
    kind_a, kind_b = gap_kind(a["text"]), gap_kind(b["text"])
    # intro, sponsor and outro material usually comes in runs of sentences: a run starting or ending is explicit
    block = (kind_b and (i + 2 >= len(sents) or gap_kind(sents[i + 2]["text"]) == kind_b)) or \
        (kind_a and (i == 0 or gap_kind(sents[i - 1]["text"]) == kind_a))
    titled = title_like(b["text"])
    goes_on = continues(b["text"])
    score, why = 0.0, []
    if gap >= 3.0:
        score += 0.38
    elif gap >= 1.5:
        score += 0.26
    elif gap >= 0.9:
        score += 0.12
    if gap >= 0.9:
        why.append(f"a {gap:.1f} s pause")
    if mark == "separator":
        score += 0.55
        why.append("the narrator's usual words for the next story")
    elif mark == "number":
        score += 0.55
        why.append("the story's number")
    elif strong:
        score += 0.55
        why.append("words that announce the next story")
    elif opener:
        score += 0.35
        why.append("wording that starts a story")
    if closer:
        score += 0.30
        why.append("wording that ends a story")
    if kind_a != kind_b:
        score += 0.50 if block else 0.35
        why.append(f"{(kind_b or kind_a)} material {'starts' if kind_b else 'ends'}")
    if titled and not goes_on:
        score += 0.10
        why.append("the next sentence reads like a title")
    topic = 0.20 if cohesion < 0.08 else 0.08 if cohesion < 0.15 else 0.0
    if baseline > 0 and cohesion < 0.5 * baseline and cohesion < 0.2:
        topic = max(topic, 0.10)
    if meaning is not None:  # the meaning model: the subject changes even when the words do not say so
        shift, z = meaning
        if z <= -2.5 and shift <= 0.25:
            topic = max(topic, 0.22)
        elif z <= -1.8 and shift <= 0.35:
            topic = max(topic, 0.12)
    if topic >= 0.10:
        why.append("a change of topic")
    score += topic
    if goes_on:
        score -= 0.4
        why.append("but the same story goes on (an update or a comment)")
    explicit = opener or kind_a != kind_b or (titled and closer)
    if gap < 0.25 and not explicit:
        score = min(score, 0.3)  # no pause and no explicit change: not a boundary, whatever the wording
    cut = b["start"] - LEAD_S if gap >= 2 * LEAD_S else (a["end"] + b["start"]) / 2
    return {"after": i, "time": (a["end"] + b["start"]) / 2, "cut": round(cut, 3), "gap": gap,
            "score": round(max(0.0, min(score, 1.0)), 3), "why": why, "opener": opener, "strong": strong,
            "closer": closer, "mark": mark or "", "sure": (strong or bool(block)) and not goes_on}


def _chunks(duration: float) -> list[dict]:
    chunks, start = [], 0.0
    while True:
        end = min(duration, start + CHUNK_S)
        chunks.append({"start": start, "end": end})
        if end >= duration:
            break
        start += STEP_S
    return chunks


def candidates(sents: list[dict], duration: float, emb=None
               ) -> tuple[list[dict], list[dict], list[dict], dict[int, str]]:
    """Accepted boundaries (reconciled across chunks), near misses worth a second opinion, the chunks analysed and
    the separator/number marks. Once the narrator's separators are known (three or more), a boundary elsewhere needs
    much stronger evidence: the narrator says where the stories change. `emb` (semantic.embed_sentences) adds the
    meaning model's view of where the subject changes."""
    marks = marks_of(sents)
    shifts = meaning_shifts(sents, emb)

    def meaning_at(i: int) -> tuple[float, float] | None:
        return (float(shifts[0][i]), float(shifts[1][i])) if shifts is not None and i < len(shifts[0]) else None
    templated = sum(1 for v in marks.values()) >= 3
    chunks = _chunks(duration)
    found: list[dict] = []
    for c in chunks:
        idx = [k for k, s in enumerate(sents) if s["start"] >= c["start"] - 1e-6 and s["end"] <= c["end"] + 1e-6]
        if len(idx) < 2:
            continue
        lo, hi = idx[0], idx[-1]
        baseline = statistics.median(_cohesion(sents, i, lo, hi) for i in range(lo, hi)) if hi - lo >= 4 else 0.0
        for i in range(lo, hi):
            b = _boundary(sents, i, lo, hi, marks, baseline, meaning_at(i))
            if b["score"] < NEAR:
                continue
            near_edge = (b["time"] - c["start"] < EDGE_S and c["start"] > 0) or \
                (c["end"] - b["time"] < EDGE_S and c["end"] < duration)
            found.append({**b, "chunk": chunks.index(c), "edge": near_edge})
    merged: dict[int, dict] = {}
    for b in found:  # the same boundary seen by two overlapping chunks is one boundary
        key = b["after"]
        if key not in merged or (merged[key]["edge"] and not b["edge"]) or b["score"] > merged[key]["score"]:
            merged[key] = b
    accepted, near = [], []
    for b in sorted(merged.values(), key=lambda x: x["time"]):
        if b["edge"]:
            # Seen only with truncated context: recompute with full context before trusting it.
            full = _boundary(sents, b["after"], 0, len(sents) - 1, marks, 0.0, meaning_at(b["after"]))
            b = {**full, "chunk": b["chunk"], "edge": False}
        need = STRONG if templated and not b["sure"] else THRESHOLD
        if b["score"] >= need:
            if accepted and _too_close(sents, accepted[-1], b):
                continue
            accepted.append(b)
        elif b["score"] >= NEAR:
            near.append(b)
    return accepted, near, chunks, marks


def _too_close(sents: list[dict], last: dict, b: dict) -> bool:
    """Two boundaries that are one boundary: within MERGE_S, or a short announcement ("Next story.") followed by the
    post's title, which both open the same story."""
    if b["time"] - last["time"] < MERGE_S:
        return True
    between = sents[last["after"] + 1:b["after"] + 1]
    return last["strong"] and len(between) <= 2 and sum(len(x["text"].split()) for x in between) <= 10


def boundaries(sents: list[dict], duration: float) -> tuple[list[dict], list[dict]]:
    """Accepted boundaries (reconciled across chunks) and the chunks analysed."""
    accepted, _near, chunks, _marks = candidates(sents, duration)
    return accepted, chunks


def _clip_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip().strip(",").strip("\"'“”")
    t = t[:1].upper() + t[1:]
    if len(t) <= 70:
        return t
    cut = t[:70].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


_NUM = r"(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_LEAD_IN = re.compile(
    r"^(?:(?:okay|ok|alright|right|so|and|now|anyway|anyways|next up|moving on)[,.!:]?\s+)*"
    r"(?:(?:"
    r"(?:(?:the|my|our|this|here'?s the|here'?s|this is|now for|time for|on to|onto|and the|now the)\s+)?"
    r"(?:(?:next|last|final|first|second|third|fourth|fifth|another|one more)\s+(?:story|one|post|tale)|story|post|tale|stories)"
    rf"(?:\s+(?:number|no\.?|#)?\s*{_NUM})?(?:\s+(?:is|was|comes)(?:\s+(?:from|titled|called|about))?|\s+(?:from|titled|called|about))?"
    rf"|(?:number|no\.?|#)\s*{_NUM}"
    r"|(?:posted|submitted|written|sent in) by \S+(?: (?:in|on|over on) \S+)?"
    r"|(?:from |in |over on )?(?:the subreddit |r/|r slash |are slash )\S+"
    r"|(?:reddit )?user \S+ (?:asks|says|writes|posted|wrote)"
    r"|(?:the )?title (?:is|says|reads)"
    r"|(?:titled|called|named)"
    r"|this one'?s (?:titled|called|about)"
    r"|(?:this|the next|our next|this next|the last|the final) (?:one|story|post) (?:is|was|comes)(?: (?:from|titled|called|about))?"
    r")\b[,.:;!]?\s*)*", re.I)


def story_title(seg: list[dict]) -> str:
    """A title from the story's own first words: the post's title when one is read out, otherwise the first
    sentence after the narrator's lead-in ("Next story.", "Story number two, posted by u/x:")."""
    for s in seg[:3]:
        text = s["text"].strip()
        rest = _LEAD_IN.sub("", text, count=1).strip(" ,.:;!\"'“”")
        if len(rest.split()) >= 3:
            return _clip_title(rest)
    return _clip_title(seg[0]["text"])


def _item(sents: list[dict], seg: list[dict], start: float, end: float, start_b: dict | None,
          end_b: dict | None, duration: float) -> dict:
    kinds = [gap_kind(s["text"]) for s in seg]
    labelled = [x for x in kinds if x]
    span = seg[-1]["end"] - seg[0]["start"]
    kind = "gap" if labelled and (len(labelled) * 2 >= len(seg) or span < 25) else "story"
    item = {"kind": kind, "label": max(set(labelled), key=labelled.count) if labelled and kind == "gap" else "",
            "start": round(start, 3), "end": round(end, 3), "opening": seg[0]["text"], "closing": seg[-1]["text"],
            "sentences": len(seg), "title": story_title(seg) if kind == "story" else _clip_title(seg[0]["text"])}
    if kind != "story":
        item.update({"completeness": "complete", "confidence": 1.0,
                     "reason": f"{item['label'] or 'non-story'} material, kept out of the stories"})
        return item
    sure = 0.85  # a boundary the narrator's own words announce is as sure as a clear pause and closer
    s_strength = max(start_b["score"], sure if start_b["sure"] else 0.0) if start_b else \
        (0.8 if _match(OPENERS, seg[0]["text"]) or seg[0]["start"] < 2.0 else 0.4)
    trailing = duration - seg[-1]["end"]
    closes = _match(CLOSERS, seg[-1]["text"])
    e_strength = max(end_b["score"], sure if end_b["sure"] else 0.0) if end_b else \
        (0.8 if closes or trailing >= 1.5 else 0.2)
    reasons = []
    if start_b:
        reasons.append("starts after " + ", ".join(start_b["why"]))
    if end_b:
        reasons.append("runs until the next part starts (" + ", ".join(end_b["why"]) + ")")
    completeness = "complete"
    unfinished = not re.search(r"[.!?…]['\")]*$", seg[-1]["text"].strip())
    if not end_b and not closes and (trailing < 1.0 or (unfinished and trailing < 2.0)):
        completeness = "incomplete"
        reasons.append("the recording stops right after the last words, so the story may be cut off")
    elif min(s_strength, e_strength) < 0.6 or span < 20:
        completeness = "uncertain"
        reasons.append("a boundary is weak or the story is very short: check where it starts and ends")
    item.update({"completeness": completeness, "confidence": round(min(s_strength, e_strength), 2),
                 "reason": "; ".join(reasons) or "the whole recording"})
    return item


def _absorb(items: list[dict]) -> list[dict]:
    """Talk between two stories that is not an intro, a sponsor read or the outro (the narrator's remarks, a short
    transition) stays with the story before it, so each clip runs until the next story starts."""
    out: list[dict] = []
    for item in items:
        if item["kind"] == "gap" and item["label"] in ("transition", "other", "") and out and out[-1]["kind"] == "story":
            prev = out[-1]
            prev.update({"end": item["end"], "closing": item["closing"], "sentences": prev["sentences"] + item["sentences"],
                         "reason": prev["reason"] + f"; the {item['end'] - item['start']:.0f} s said after it stay with it"})
            continue
        out.append(item)
    merged: list[dict] = []
    for item in out:  # a stray remark before the first story joins that story
        if merged and merged[-1]["kind"] == "gap" and merged[-1]["label"] in ("transition", "other", "") and \
                item["kind"] == "story" and (len(merged) == 1 or merged[-2]["kind"] == "gap"):
            gap = merged.pop()
            item.update({"start": gap["start"], "opening": gap["opening"], "sentences": gap["sentences"] + item["sentences"]})
        merged.append(item)
    return merged


def _assemble(sents: list[dict], accepted: list[dict], duration: float) -> list[dict]:
    cuts = [-1] + [b["after"] for b in accepted] + [len(sents) - 1]
    by_after = {b["after"]: b for b in accepted}
    items = []
    for k in range(len(cuts) - 1):
        seg = sents[cuts[k] + 1:cuts[k + 1] + 1]
        if not seg:
            continue
        start_b, end_b = by_after.get(cuts[k]), by_after.get(cuts[k + 1])
        if start_b:
            start = start_b["cut"]
        else:
            start = max(0.0, seg[0]["start"] - LEAD_S) if seg[0]["start"] > 1.0 else 0.0
        end = end_b["cut"] if end_b else min(duration, seg[-1]["end"] + TAIL_S)
        items.append(_item(sents, seg, start, end, start_b, end_b, duration))
    for k, item in enumerate(items):
        # A few seconds of unlabelled talk is not a story: it belongs to the neighbouring material
        # ("Today is a short update." after the greeting). A long unlabelled part always stays a story.
        if item["kind"] == "story" and item["end"] - item["start"] < MIN_STORY_S and len(items) > 1:
            near = [x for x in (items[k - 1] if k else None, items[k + 1] if k + 1 < len(items) else None)
                    if x and x["kind"] == "gap"]
            item.update({"kind": "gap", "label": near[0]["label"] if near else "other", "completeness": "complete",
                         "confidence": 1.0, "reason": "too short to be a story; include it by hand if it is one"})
    merged: list[dict] = []
    for item in items:  # neighbouring non-story parts of the same kind (two intro sentences) are one gap
        if merged and item["kind"] == "gap" and merged[-1]["kind"] == "gap" and \
                item["label"] == merged[-1]["label"]:
            merged[-1].update({"end": item["end"], "closing": item["closing"],
                               "sentences": merged[-1]["sentences"] + item["sentences"]})
            continue
        merged.append(item)
    return _absorb(merged)


def propose(words: list[dict], sents: list[dict], duration: float, judge: "Judge | None" = None,
            opts: dict | None = None) -> dict:
    """Stories and gaps in source order. Times are seconds; callers store integer milliseconds. `judge` (optional)
    first reads the recording through and names where new stories begin, then is asked about the boundaries the
    rules are not sure of; its answers are recorded, and the rules stand when it has none. `opts` (the settings)
    decides whether the meaning model is used for the change-of-subject signal."""
    if not sents:
        return {"items": [], "chunks": [], "method": METHOD,
                "note": "No speech was found, so no story boundaries can be estimated. Add the stories by hand."}
    emb = semantic.embed_sentences(sents, opts) if len(sents) >= 8 else None
    accepted, near, chunks, marks = candidates(sents, duration, emb)
    ai: dict = {}
    if judge is not None:
        scan = getattr(judge, "scan", None)
        if scan is not None:
            accepted, near = scan(accepted, near, marks)
        accepted, ai = judge.review(accepted, near)
    if emb is not None and getattr(emb, "model", "lexical") != "lexical":
        ai = {**ai, "meaning_model": emb.model}
    items = _assemble(sents, accepted, duration)
    phrases = sorted({v for v in separators(sents).values()})
    method = METHOD + (" and the meaning model" if ai.get("meaning_model") else "") + \
        (", checked by ClipForge AI" if ai.get("answered") or ai.get("scanned") else "")
    return {"items": items, "chunks": chunks, "method": method,
            "boundaries": [{k: b[k] for k in ("time", "gap", "score", "why")} for b in accepted],
            "separators": phrases, "numbered": sum(1 for v in marks.values() if v == "number"), "ai": ai}


# ------------------------------------------------------------------ ClipForge AI's second opinion
SYSTEM = ("You split a long recording of someone reading or telling several separate stories into the stories. "
          "Use only the words given; never invent anything. Reply with one JSON object and nothing else.")
MAX_QUESTIONS = 60
BATCH = 6
SCAN_SCHEMA = {"type": "object", "properties": {"starts": {"type": "array", "maxItems": 12, "items": {"type": "integer"}}},
               "required": ["starts"]}
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="stories-ai")


class Judge:
    """Asks ClipForge AI's model, inside a time budget, whether a new story begins at the places the rules are not
    sure of: near misses can become boundaries, weak boundaries can be dropped. Every answer is recorded in the
    boundary's reasons; a missing or late answer leaves the rules' decision."""

    def __init__(self, settings: dict, sents: list[dict], *, budget_s: float = 300.0,
                 heartbeat: Callable[[str], None] | None = None, canceled: Callable[[], bool] | None = None,
                 complete: Callable[..., str] | None = None):
        from . import llm

        self.settings, self.sents = settings, sents
        self.budget_s, self.heartbeat, self.canceled = budget_s, heartbeat, canceled
        self.complete = complete or llm.complete
        self.timeout = min(120.0, max(20.0, float(settings.get("ai_edit_timeout_s", 60)) * 2))
        self.report = {"provider": llm.provider_label(settings), "asked": 0, "answered": 0, "changed": 0,
                       "problems": []}

    def _ask(self, prompt: str, label: str, schema: dict | None = None) -> str:
        from . import llm

        call = _pool.submit(self.complete, self.settings, prompt, task="stories", system=SYSTEM, num_ctx=8192,
                            json_object=True, **({"json_schema": schema} if schema else {}))
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                return call.result(timeout=1.0)
            except concurrent.futures.TimeoutError:
                if self.heartbeat:
                    self.heartbeat(f"ClipForge AI is checking {label}")
                if (self.canceled and self.canceled()) or time.monotonic() > deadline:
                    self.report["problems"].append(f"{label}: no answer within {self.timeout:g} s.")
                    return ""
            except llm.ProviderError as exc:
                self.report["problems"].append(f"{label}: {str(exc)[:200]}")
                return ""
            except Exception as exc:  # noqa: BLE001 - reported, the rules decide
                self.report["problems"].append(f"{label}: {exc.__class__.__name__}")
                return ""

    def _context(self, b: dict) -> str:
        i = b["after"]
        before = " ".join(s["text"] for s in self.sents[max(0, i - 2):i + 1])
        marked = self.sents[i + 1]["text"]
        after = " ".join(s["text"] for s in self.sents[i + 2:i + 4])
        return f'  before: "{before[-400:]}"\n  >>> marked: "{marked[:300]}"\n  after: "{after[:300]}"'

    def _prompt(self, batch: list[dict]) -> str:
        places = "\n".join(f"Place {n}:\n{self._context(b)}" for n, b in enumerate(batch, 1))
        return ("Below are places in the transcript of a recording with several separate stories. At each place, "
                "decide whether the marked sentence (>>>) BEGINS A NEW STORY, a different story than the sentences "
                "before it. The same story continuing (a detail, an update, an edit, a comment read out, a pause) "
                "is NOT a new story. A greeting, a sponsor read or a goodbye is not a story either.\n\n"
                f"{places}\n\n"
                'Answer with {"new_story": [the place numbers where a new story begins]} (an empty list when none).')

    def scan(self, accepted: list[dict], near: list[dict], marks: dict[int, str]) -> tuple[list[dict], list[dict]]:
        """Read the recording through, part by part, and ask where new stories begin (a table of contents). A start
        the rules already found is confirmed; a near miss it names is promoted; a place nobody suspected becomes a
        boundary when the rules' own evidence there, plus the model's word, reaches the threshold, otherwise a near
        miss for review(). Uses at most half the budget; the rest is left for review()."""
        from . import scout

        parts = scout.windows(self.sents)
        started = time.monotonic()
        half = self.budget_s / 2
        self.report.setdefault("scanned", 0)
        self.report.setdefault("parts", len(parts))
        starts: set[int] = set()
        for k, (first, last) in enumerate(parts):
            if time.monotonic() - started > half or (self.canceled and self.canceled()):
                self.report["problems"].append(f"Out of time reading the recording after {k} of {len(parts)} parts.")
                break
            lines = "\n".join(f'{i} [{scout._stamp(self.sents[i]["start"])}] {self.sents[i]["text"][:240]}'
                              for i in range(first, last + 1))
            prompt = (f"Part {k + 1} of {len(parts)} of a recording with several separate stories. Each line is one "
                      f"sentence: its number, start time and words.\n\n{lines}\n\nList the numbers of the sentences "
                      "that BEGIN A NEW STORY (a different story than the sentences before it). The same story going "
                      "on (a detail, an update, a comment read out) is not a new story; a greeting, a sponsor read or a "
                      'goodbye is not a story. An empty list is a fine answer.\nAnswer: {"starts": [numbers]}')
            raw = self._ask(prompt, f"part {k + 1} of {len(parts)}", SCAN_SCHEMA)
            if not raw:
                continue
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                data = json.loads(m.group(0)) if m else None
                found = {int(x) for x in (data.get("starts") or []) if str(x).strip().lstrip("-").isdigit()}
            except (ValueError, TypeError, AttributeError):
                data = None
            if data is None:
                self.report["problems"].append("An answer was not readable; that part was left to the rules.")
                continue
            self.report["scanned"] += 1
            starts |= {i for i in found if first < i <= last}  # the first sentence of a part is never a new start
        if not starts:
            return accepted, near
        by_after = {b["after"]: b for b in accepted}
        near_by = {b["after"]: b for b in near}
        kept = []
        for b in accepted:
            if b["after"] + 1 in starts:
                b = {**b, "why": b["why"] + ["ClipForge AI read a new story beginning here"], "sure": True}
            kept.append(b)
        rest = []
        for b in near:
            if b["after"] + 1 in starts:
                self.report["changed"] += 1
                kept.append({**b, "score": max(b["score"], THRESHOLD),
                             "why": b["why"] + ["ClipForge AI read a new story beginning here"]})
            else:
                rest.append(b)
        for i in sorted(starts):
            after = i - 1
            if after in by_after or after in near_by or after < 0 or after >= len(self.sents) - 1:
                continue
            b = _boundary(self.sents, after, 0, len(self.sents) - 1, marks)
            b = {**b, "score": round(min(1.0, b["score"] + 0.35), 3),
                 "why": b["why"] + ["ClipForge AI read a new story beginning here"], "chunk": 0, "edge": False}
            if b["score"] >= THRESHOLD:
                self.report["changed"] += 1
                kept.append(b)
            else:
                rest.append(b)
        kept.sort(key=lambda x: x["time"])
        out: list[dict] = []
        for b in kept:
            if out and _too_close(self.sents, out[-1], b):
                continue
            out.append(b)
        return out, sorted(rest, key=lambda x: x["time"])

    def review(self, accepted: list[dict], near: list[dict]) -> tuple[list[dict], dict]:
        """The rules' boundaries after the model's answers: confirmed near misses join, denied weak ones leave."""
        weak = [b for b in accepted if b["score"] < 0.7 and not b["mark"]]
        likely = sorted(weak + near, key=lambda b: -b["score"])[:MAX_QUESTIONS]  # the likeliest places first
        questions = sorted(likely, key=lambda b: b["time"])
        if not questions or (self.canceled and self.canceled()):
            return accepted, self.report
        started = time.monotonic()
        verdicts: dict[int, bool] = {}
        for k in range(0, len(questions), BATCH):
            if time.monotonic() - started > self.budget_s or (self.canceled and self.canceled()):
                self.report["problems"].append("Out of time: the remaining places were left to the rules.")
                break
            batch = questions[k:k + BATCH]
            self.report["asked"] += len(batch)
            raw = self._ask(self._prompt(batch), f"story boundaries {k // BATCH + 1} of {(len(questions) + BATCH - 1) // BATCH}")
            if not raw:
                continue
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                data = json.loads(m.group(0)) if m else None
                starts = {int(x) for x in (data.get("new_story") or []) if str(x).strip().lstrip("-").isdigit()}
            except (ValueError, TypeError, AttributeError):
                data = None
            if data is None:  # an answer without JSON is no answer: it must not read as "no new story anywhere"
                self.report["problems"].append("An answer was not readable; those places were left to the rules.")
                continue
            self.report["answered"] += len(batch)
            for n, b in enumerate(batch, 1):
                verdicts[b["after"]] = n in starts
        kept = []
        for b in accepted:
            if verdicts.get(b["after"]) is False:
                self.report["changed"] += 1
                continue
            if verdicts.get(b["after"]):
                b = {**b, "why": b["why"] + ["ClipForge AI agrees a new story starts here"]}
            kept.append(b)
        for b in near:
            if verdicts.get(b["after"]):
                self.report["changed"] += 1
                kept.append({**b, "score": max(b["score"], THRESHOLD), "why": b["why"] + ["ClipForge AI says a new story starts here"]})
        kept.sort(key=lambda x: x["time"])
        out: list[dict] = []
        for b in kept:
            if out and _too_close(self.sents, out[-1], b):
                continue
            out.append(b)
        return out, self.report

    def titles(self, items: list[dict]) -> dict[int, str]:
        """A title per story from the model, by item index; only the stories it answered for. Each title is checked
        for length and used only when it is made of words that occur in the story's first sentences."""
        stories = [(k, it) for k, it in enumerate(items) if it["kind"] == "story"]
        out: dict[int, str] = {}
        started = time.monotonic()
        for k in range(0, len(stories), 8):
            if time.monotonic() - started > self.budget_s / 2 or (self.canceled and self.canceled()):
                break
            batch = stories[k:k + 8]
            listed = "\n".join(f'Story {n}: "{it["opening"][:220]}"' for n, (_, it) in enumerate(batch, 1))
            prompt = ("Each story below is given by its first words. Write a short title for each one (at most 8 "
                      "words), using only words that are said; when the narrator reads out the post's title, use that."
                      f"\n\n{listed}\n\nAnswer with {{\"titles\": {{\"1\": \"...\", \"2\": \"...\"}}}}.")
            raw = self._ask(prompt, f"story titles {k // 8 + 1}")
            m = re.search(r"\{.*\}", raw or "", re.S)
            try:
                titles = (json.loads(m.group(0)) if m else {}).get("titles") or {}
            except (ValueError, AttributeError):
                continue
            for n, (idx, it) in enumerate(batch, 1):
                t = " ".join(str(titles.get(str(n)) or "").split()).strip("\"'“”. ")
                said = set(re.findall(r"[a-z0-9']+", it["opening"].lower()))
                words = re.findall(r"[a-z0-9']+", t.lower())
                if 2 <= len(t) <= 80 and words and sum(1 for w in words if w in said) >= 0.7 * len(words):
                    out[idx] = t[:100]
        return out
