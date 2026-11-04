"""Clips → Full stories: find every complete story in a long recording (local, deterministic, no model).

The whole transcript is analysed in overlapping chunks (so the same code bounds the context a model would get);
boundaries found by neighbouring chunks are reconciled globally, and a chunk edge never creates a boundary, so a story
that crosses a chunk stays one story. A boundary needs evidence: a real pause, wording that opens or closes a story,
a change of topic, or a change between story and intro/sponsor/outro material. Silence alone is never enough.

Every distinct story is proposed, not only "strong" ones. Each proposal keeps one continuous source interval from its
opening sentence to its closing sentence (no internal sentence is removed, nothing is sped up), with only measured
silence as padding. Stories whose boundaries are weak, too short, or cut off at the end of the recording are marked
uncertain or incomplete for review instead of being called complete. This is an estimate from pauses and wording; it
is labelled as such and never presented as semantic understanding.
"""
from __future__ import annotations

import re

from .text_utils import cosine, tf_vector

METHOD = "local estimate from pauses, wording and topic change"
CHUNK_S = 360.0
STEP_S = 300.0          # chunks overlap by CHUNK_S - STEP_S seconds
EDGE_S = 20.0           # context this close to a chunk edge is incomplete; the neighbouring chunk decides
THRESHOLD = 0.5
MERGE_S = 2.0
MIN_STORY_S = 12.0      # shorter unlabelled talk next to intro/sponsor/outro material is part of that material

OPENERS = [r"^so,? (this|one) (one )?time\b", r"\bstory (number )?(one|two|three|four|five|\d+)\b",
           r"^(the|my) (next|second|third|last|final|first) story\b", r"^(here'?s|this is) (a|another|the) story\b",
           r"^let me tell you (about|a)\b", r"^(another|one) time\b", r"^it all (started|began)\b",
           r"^(back in|years ago|a few years ago|when i was)\b", r"^once upon a time\b", r"^i remember (when|the)\b",
           r"^this (one )?happened\b", r"^(okay|ok|alright|right),? (so )?(next|story)\b"]
CLOSERS = [r"\b(and )?that'?s (how|why|the story|what happened)\b", r"\bthe end\b", r"\bmoral of the story\b",
           r"\b(never|ever) (again|since)\b", r"\bto this day\b", r"\b(and|so) that was (it|that)\b",
           r"\bi learned (that|my lesson|to)\b", r"\bend of (the )?story\b"]
GAP_KINDS = {
    "intro": [r"\b(hey|hi|hello),? (everyone|everybody|guys|friends)\b", r"\bwelcome (back )?to\b",
              r"\bin (this|today'?s) video\b", r"\btoday i('?m| am| have| want)\b"],
    "sponsor": [r"\bsponsor(ed)?\b", r"\bbrought to you by\b", r"\buse (my |the )?code\b",
                r"\blink in the description\b", r"\bpromo\b", r"\bdiscount\b"],
    "transition": [r"\bthat one still\b", r"\bgrab a (drink|snack|coffee)\b", r"\bthe (last|next) one is\b",
                   r"\b(moving on|let'?s move on)\b", r"\bbefore (we|i) (get to|move on to)\b"],
    "outro": [r"\bthanks? (you )?for watching\b", r"\bsee you (next time|soon|in the next)\b",
              r"\b(like and )?subscribe\b", r"\bthat'?s (all|it) for today\b", r"\bcomment below\b"],
}


def _match(patterns: list[str], text: str) -> bool:
    t = text.lower().strip(" \"'")
    return any(re.search(p, t) for p in patterns)


def gap_kind(text: str) -> str:
    return next((k for k, pats in GAP_KINDS.items() if _match(pats, text)), "")


def _boundary(sents: list[dict], i: int, lo: int, hi: int) -> dict:
    """Evidence for a boundary between sentence i and i+1, using only sentences lo..hi (one chunk's context)."""
    a, b = sents[i], sents[i + 1]
    gap = max(0.0, b["start"] - a["end"])
    before = " ".join(s["text"] for s in sents[max(lo, i - 4):i + 1])
    after = " ".join(s["text"] for s in sents[i + 1:min(hi + 1, i + 6)])
    cohesion = cosine(tf_vector(before), tf_vector(after))
    opener, closer = _match(OPENERS, b["text"]), _match(CLOSERS, a["text"])
    kind_a, kind_b = gap_kind(a["text"]), gap_kind(b["text"])
    score, why = 0.0, []
    if gap >= 3.0:
        score += 0.45
    elif gap >= 1.5:
        score += 0.30
    elif gap >= 0.9:
        score += 0.12
    if gap >= 0.9:
        why.append(f"a {gap:.1f} s pause")
    if opener:
        score += 0.35
        why.append("wording that starts a story")
    if closer:
        score += 0.30
        why.append("wording that ends a story")
    if kind_a != kind_b:
        score += 0.35
        why.append(f"{(kind_b or kind_a)} material {'starts' if kind_b else 'ends'}")
    if cohesion < 0.08:
        score += 0.15
        why.append("a change of topic")
    elif cohesion < 0.15:
        score += 0.08
    if gap < 0.25 and not (opener or kind_a != kind_b):
        score = min(score, 0.3)  # no pause and no explicit change: not a boundary, whatever the wording
    return {"after": i, "time": (a["end"] + b["start"]) / 2, "gap": gap, "score": round(min(score, 1.0), 3),
            "why": why, "opener": opener, "closer": closer}


def boundaries(sents: list[dict], duration: float) -> tuple[list[dict], list[dict]]:
    """Accepted boundaries (reconciled across chunks) and the chunks analysed."""
    chunks, found = [], []
    start = 0.0
    while True:
        end = min(duration, start + CHUNK_S)
        chunks.append({"start": start, "end": end})
        if end >= duration:
            break
        start += STEP_S
    for c in chunks:
        idx = [k for k, s in enumerate(sents) if s["start"] >= c["start"] - 1e-6 and s["end"] <= c["end"] + 1e-6]
        if len(idx) < 2:
            continue
        lo, hi = idx[0], idx[-1]
        for i in range(lo, hi):
            b = _boundary(sents, i, lo, hi)
            near_edge = (b["time"] - c["start"] < EDGE_S and c["start"] > 0) or \
                (c["end"] - b["time"] < EDGE_S and c["end"] < duration)
            if b["score"] >= THRESHOLD:
                found.append({**b, "chunk": chunks.index(c), "edge": near_edge})
    merged: dict[int, dict] = {}
    for b in found:  # the same boundary seen by two overlapping chunks is one boundary
        key = b["after"]
        if key not in merged or (merged[key]["edge"] and not b["edge"]) or b["score"] > merged[key]["score"]:
            merged[key] = b
    accepted = []
    for b in sorted(merged.values(), key=lambda x: x["time"]):
        if b["edge"]:
            # Seen only with truncated context: recompute with full context before trusting it.
            full = _boundary(sents, b["after"], 0, len(sents) - 1)
            if full["score"] < THRESHOLD:
                continue
            b = {**full, "chunk": b["chunk"], "edge": False}
        if accepted and b["time"] - accepted[-1]["time"] < MERGE_S:
            continue
        accepted.append(b)
    return accepted, chunks


def _title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip().strip(",")
    if len(t) <= 70:
        return t
    cut = t[:70].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def propose(words: list[dict], sents: list[dict], duration: float) -> dict:
    """Stories and gaps in source order. Times are seconds; callers store integer milliseconds."""
    if not sents:
        return {"items": [], "chunks": [], "method": METHOD,
                "note": "No speech was found, so no story boundaries can be estimated. Add the stories by hand."}
    accepted, chunks = boundaries(sents, duration)
    cuts = [-1] + [b["after"] for b in accepted] + [len(sents) - 1]
    by_after = {b["after"]: b for b in accepted}
    items = []
    for k in range(len(cuts) - 1):
        seg = sents[cuts[k] + 1:cuts[k + 1] + 1]
        if not seg:
            continue
        kinds = [gap_kind(s["text"]) for s in seg]
        labelled = [x for x in kinds if x]
        span = seg[-1]["end"] - seg[0]["start"]
        kind = "gap" if labelled and (len(labelled) * 2 >= len(seg) or span < 25) else "story"
        start_b, end_b = by_after.get(cuts[k]), by_after.get(cuts[k + 1])
        prev_end = sents[cuts[k]]["end"] if cuts[k] >= 0 else 0.0
        next_start = sents[cuts[k + 1] + 1]["start"] if cuts[k + 1] + 1 < len(sents) else duration
        # measured padding only: half the silence on each side, at most 0.3 s before and 0.5 s after
        start = max(prev_end, seg[0]["start"] - min(0.3, (seg[0]["start"] - prev_end) / 2))
        end = min(next_start, seg[-1]["end"] + min(0.5, (next_start - seg[-1]["end"]) / 2))
        item = {"kind": kind, "label": max(set(labelled), key=labelled.count) if labelled else "",
                "start": round(start, 3), "end": round(end, 3), "opening": seg[0]["text"], "closing": seg[-1]["text"],
                "sentences": len(seg), "title": _title(seg[0]["text"])}
        if kind == "story":
            s_strength = start_b["score"] if start_b else (0.8 if _match(OPENERS, seg[0]["text"]) or
                                                          seg[0]["start"] < 2.0 else 0.4)
            trailing = duration - seg[-1]["end"]
            closes = _match(CLOSERS, seg[-1]["text"])
            if end_b:
                e_strength = end_b["score"]
            else:
                e_strength = 0.8 if closes or trailing >= 1.5 else 0.2
            reasons = []
            if start_b:
                reasons.append("starts after " + ", ".join(start_b["why"]))
            if end_b:
                reasons.append("ends before " + ", ".join(end_b["why"]))
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
        else:
            item.update({"completeness": "complete", "confidence": 1.0,
                         "reason": f"{item['label'] or 'non-story'} material, kept out of the stories"})
        items.append(item)
    for k, item in enumerate(items):
        # A few seconds of unlabelled talk is not a story: it belongs to the neighbouring non-story material
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
    items = merged
    return {"items": items, "chunks": chunks, "method": METHOD,
            "boundaries": [{k: b[k] for k in ("time", "gap", "score", "why")} for b in accepted]}
