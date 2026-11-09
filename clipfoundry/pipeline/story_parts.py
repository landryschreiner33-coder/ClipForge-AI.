"""Clips → stories cut into parts: where a story is split, in both story modes.

Two rules use this module. **Full story** makes one clip per story and splits a story only when it is longer than
five minutes (no story clip is ever longer than `MAX_CLIP_S`): it then makes the fewest parts that fit. **Story
parts** splits every story that is long enough into parts of about `PART_TARGET_S` (each part over a minute, so it
counts as a long video on TikTok, and under three minutes, so it fits YouTube Shorts and Instagram Reels).

A story is cut only between two sentences, at the places that make the best end of a part, scored from the words
and the timing (local and deterministic): a line that leaves the viewer hanging ("...and that's when I saw the
text."), right before a reveal or a jump in time ("Turns out...", "The next morning..."), right before an update
the poster added ("Update: ..."), a longer pause than this narrator usually makes, or a change of scene. A cut
before "and", "because" or "which" (the same thought going on) or after a sentence that is not finished is avoided.
The parts are kept close to the same length (a dynamic programme picks the best set of cuts), and the five-minute
cap is a hard limit. When no set of sentence boundaries fits, Full story first tries one part more (a clean cut is
better than the fewest parts) and Story parts tries fewer, longer parts; only then is a part cut at the longest pause
between two words, or inside a long stretch without talking (gameplay), and never inside a word. ClipForge AI's
model, when one is set up, may pick among the best few places for each cut inside a time budget; its choice is used
only when it keeps every rule.
"""
from __future__ import annotations

import bisect
import math
import re
import statistics
from typing import Callable

from .text_utils import cosine, tf_vector

MAX_CLIP_S = 300.0       # no story clip is longer than five minutes, in any mode
CAP_PLAN_S = 299.5       # parts are planned a little shorter, so rounding to milliseconds never crosses the cap
PART_TARGET_S = 110.0    # Story parts: about a minute and three quarters each
PART_MIN_S = 62.0        # over a minute (TikTok counts videos over a minute as long videos)
PART_MAX_S = 175.0       # under three minutes (YouTube Shorts, Instagram Reels)
EDGE_S = 15.0            # never cut this close to the story's own start or end
LEAD_S = 0.4             # the next part starts this long before its first word when the pause allows
CHOICES = 4              # places offered to ClipForge AI's model for one cut
GAP_BUCKET_S = 2.0       # fallback cuts between words: the longest pause in each stretch this long
SILENCE_S = 8.0          # a stretch this long without words (gameplay, no talking) may be cut inside
SILENCE_STEP_S = 2.0     # places offered inside such a stretch, this far apart

# The end of a part that leaves the viewer wanting the next one (said in the last sentence of the part).
CLIFF_PHRASES = [r"\bthat'?s when\b", r"\b(and|but) then\W*$", r"\bsuddenly\b", r"\buntil\W*$",
                 r"\blittle did (i|we|he|she|they) know\b", r"\b(you|you'?ll) (won'?t|never) (believe|guess)\b",
                 r"\bwhat (he|she|they|i|we) (said|did|found|saw) next\b", r"\b(i|we) froze\b",
                 r"\bmy (heart|stomach) (sank|dropped)\b", r"\band guess what\b", r"\bit gets worse\b",
                 r"\bplot twist\b", r"\b(that'?s|this is) (not|n'?t) even the (worst|best) part\b",
                 r"\bwhat happened next\b", r"\bhere'?s (where|the thing|the kicker)\b", r"\bout of nowhere\b",
                 r"\b(i|we) (saw|heard|found|noticed|realized|realised) (something|it|her|him|them|the)\b",
                 r"\b(he|she|they) (looked at me|turned to me|leaned in) and said\b", r"\bwithout (a word|warning)\b",
                 r"\bi couldn'?t believe\b", r"\bthe door (opened|swung open|burst open)\b", r"\bthere was a knock\b"]
# The first words of the next part that make a good start: a reveal, a jump in time, the poster's update.
REVEAL_STARTS = [r"^(it )?turns? out\b", r"^(it )?turned out\b", r"^apparently\b", r"^that'?s when\b",
                 r"^suddenly\b", r"^out of nowhere\b", r"^(but|and) then\b", r"^so,? (here'?s|that'?s)\b",
                 r"^(the|that) (truth|reason|problem) (is|was)\b"]
TIME_SKIPS = [r"^(the )?next (day|morning|night|week|evening|weekend|month|year)\b",
              r"^(a|one|two|three|a few|a couple( of)?|several) (minutes?|hours?|days?|weeks?|months?|years?) later\b",
              r"^fast[- ]?forward\b", r"^later (that|this|on)\b", r"^(that|this) (night|evening|morning|weekend)\b",
              r"^the following\b", r"^(after|before) (that|this|the)\b", r"^when (i|we) (got|came) (home|back)\b",
              r"^(on|by) (the )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend)\b"]
UPDATE_STARTS = [r"^(update|edit|final update|small update|quick update|second update|another update)\b"]
# The next sentence carries on the same thought: a poor place to stop.
GOES_ON = re.compile(r"^(and|or|because|which|who|whom|whose|that|so that|plus|but also|nor|than|as well)\b", re.I)
FINISHED = re.compile(r"[.!?…]['\")\]]*$")


def _match(patterns: list[str], text: str) -> bool:
    t = text.lower().strip(" \"'“”")
    return any(re.search(p, t) for p in patterns)


def rhythm(sents: list[dict]) -> dict:
    """How this narrator pauses between sentences (seconds): the median and the 90th and 97th percentiles. A pause
    counts as a break only when it is long for this recording: a gamer who stops talking every few seconds while
    playing is not starting a new scene each time."""
    gaps = sorted(max(0.0, b["start"] - a["end"]) for a, b in zip(sents, sents[1:]))
    if not gaps:
        return {"median": 0.0, "p90": 0.0, "p97": 0.0}

    def pct(q: float) -> float:
        return gaps[min(len(gaps) - 1, int(q * (len(gaps) - 1) + 0.5))]
    return {"median": round(statistics.median(gaps), 3), "p90": round(pct(0.90), 3), "p97": round(pct(0.97), 3)}


def pause_weight(gap: float, rh: dict) -> float:
    """0..1: how much of a break a pause of `gap` seconds is for this narrator."""
    long_ = max(1.5, 2.5 * rh.get("median", 0.0), rh.get("p97", 0.0))
    some = max(0.8, 1.5 * rh.get("median", 0.0), rh.get("p90", 0.0))
    if gap >= long_:
        return 1.0
    if gap >= some:
        return 0.35 + 0.65 * (gap - some) / max(1e-6, long_ - some)
    return 0.0


def cut_time(a: dict, b: dict) -> float:
    """Where a part ends between sentence `a` and the next sentence `b`."""
    gap = b["start"] - a["end"]
    return round(b["start"] - LEAD_S, 3) if gap >= 2 * LEAD_S else round((a["end"] + b["start"]) / 2, 3)


def _cohesion(sents: list[dict], j: int) -> float:
    before = " ".join(s["text"] for s in sents[max(0, j - 4):j + 1])
    after = " ".join(s["text"] for s in sents[j + 1:j + 6])
    return cosine(tf_vector(before), tf_vector(after))


def candidates(sents: list[dict], start: float, end: float, rh: dict) -> list[dict]:
    """Every place between two sentences inside [start, end] where a part could end, with how good a place it is
    (0..1 and the reasons). Places within EDGE_S of the story's start or end are left out."""
    inside = [k for k, s in enumerate(sents) if s["start"] >= start - 0.05 and s["end"] <= end + 0.05]
    out: list[dict] = []
    if len(inside) < 2:
        return out
    cohesions = [_cohesion(sents, j) for j in inside[:-1]]
    usual = statistics.median(cohesions) if cohesions else 0.0
    for n, j in enumerate(inside[:-1]):
        a, b = sents[j], sents[j + 1]
        t = cut_time(a, b)
        if t - start < EDGE_S or end - t < EDGE_S:
            continue
        q, why = 0.0, []
        gap = max(0.0, b["start"] - a["end"])
        pw = pause_weight(gap, rh)
        if pw:
            q += 0.25 * pw
            why.append(f"a {gap:.1f} s pause")
        text_a, text_b = a["text"].strip(), b["text"].strip()
        if _match(UPDATE_STARTS, text_b):
            q += 0.45
            why.append("the poster's update starts")
        elif _match(TIME_SKIPS, text_b):
            q += 0.35
            why.append("a jump in time")
        elif _match(REVEAL_STARTS, text_b):
            q += 0.3
            why.append("right before a reveal")
        if _match(CLIFF_PHRASES, text_a):
            q += 0.3
            why.append("ends on a line that leaves you hanging")
        elif text_a.endswith(("?", "!", "…", "...")):
            q += 0.12
            why.append("ends on a question or an exclamation" if not text_a.endswith(("…", "...")) else
                       "ends trailing off")
        if usual > 0 and cohesions[n] < 0.5 * usual and cohesions[n] < 0.15:
            q += 0.12
            why.append("a change of scene")
        if GOES_ON.match(text_b):
            q -= 0.3
            why.append("but the same thought goes on")
        if not FINISHED.search(text_a):
            q -= 0.3
            why.append("but the sentence is not finished")
        out.append({"after": j, "time": t, "quality": round(max(-1.0, min(1.0, q)), 3), "why": why,
                    "end_text": text_a, "next_text": text_b})
    return out


def _word_gaps(words: list[dict], start: float, end: float) -> list[dict]:
    """Fallback places inside long sentences: the pauses between words, the longest one in every GAP_BUCKET_S (only
    used when no set of sentence boundaries fits under the cap)."""
    inside = [w for w in words if w["start"] >= start and w["end"] <= end]
    best: dict[int, dict] = {}
    for a, b in zip(inside, inside[1:]):
        gap = max(0.0, b["start"] - a["end"])
        t = round((a["end"] + b["start"]) / 2, 3)
        if not start + EDGE_S <= t <= end - EDGE_S:
            continue
        bucket = int((t - start) // GAP_BUCKET_S)
        if bucket in best and best[bucket]["gap"] >= gap:
            continue
        best[bucket] = {"after": -1, "time": t, "quality": round(-0.6 + min(0.3, gap / 2), 3), "gap": gap,
                        "why": [f"between two words ({gap:.1f} s pause): no sentence ends near here"],
                        "end_text": str(a.get("w", "")), "next_text": str(b.get("w", ""))}
    return [best[k] for k in sorted(best)]


def _silences(words: list[dict], start: float, end: float) -> list[dict]:
    """Fallback places inside the stretches of the story where nobody talks for SILENCE_S or more (gameplay between
    two posts): a part may end there without cutting a word."""
    inside = sorted((w for w in words if w["end"] > start and w["start"] < end), key=lambda w: w["start"])
    edges = [start] + [x for w in inside for x in (w["start"], w["end"])] + [end]
    out = []
    for a, b in zip(edges[0::2], edges[1::2]):  # (end of talking, start of talking) pairs
        if b - a < SILENCE_S:
            continue
        t = a + 1.0
        while t <= b - 1.0:
            if start + EDGE_S <= t <= end - EDGE_S:
                out.append({"after": -1, "time": round(t, 3), "quality": -0.2,
                            "why": [f"in a {b - a:.0f} s stretch without talking"], "end_text": "", "next_text": ""})
            t += SILENCE_STEP_S
    return out


def part_count(duration: float, mode: str) -> int:
    """How many parts a story of `duration` seconds becomes. `mode` is "whole" (Full story: split only past the
    five-minute cap) or "parts" (Story parts)."""
    if duration <= 0:
        return 1
    least = 1 if duration <= MAX_CLIP_S else math.ceil(duration / CAP_PLAN_S)
    if mode != "parts":
        return least
    if duration < 2 * PART_MIN_S:
        return least
    n = max(least, math.ceil(duration / PART_MAX_S), int(round(duration / PART_TARGET_S)))
    while n > least and duration / n < PART_MIN_S:
        n -= 1
    return max(1, n)


def _bounds(mode: str, duration: float, n: int) -> tuple[float, float]:
    """The lengths a part should keep (soft): Story parts between a minute and three minutes; Full story anything
    up to the cap, not much shorter than the others."""
    return (PART_MIN_S, PART_MAX_S) if mode == "parts" else (min(PART_MIN_S, duration / n), CAP_PLAN_S)


def _plan(cands: list[dict], start: float, end: float, n: int, hard_max: float, soft_min: float,
          soft_max: float) -> list[dict] | None:
    """The best n-1 cuts among `cands` (sorted by time; dynamic programme): high quality places, parts close to the
    same length, no part over `hard_max`; parts under `soft_min` or over `soft_max` cost a lot but are allowed.
    Only places a part of at most `hard_max` can reach are compared, so a long story stays quick."""
    if n <= 1:
        return []
    ideal = (end - start) / n
    m = len(cands)
    if m < n - 1:
        return None
    times = [c["time"] for c in cands]

    def cost(length: float) -> float | None:
        if length > hard_max + 1e-6 or length <= 0:
            return None
        dev = (length - ideal) / ideal
        c = 2.0 * dev * dev
        if length < soft_min:
            c += 1.0 + (soft_min - length) / soft_min
        if length > soft_max:
            c += 1.0 + (length - soft_max) / soft_max
        return c

    NEG = float("-inf")
    best = [[NEG] * m for _ in range(n - 1)]
    back = [[-1] * m for _ in range(n - 1)]
    for j in range(m):
        # cut k at place j must leave room for the parts before it and after it
        pen = cost(times[j] - start)
        if pen is not None and end - times[j] <= (n - 1) * hard_max + 1e-6:
            best[0][j] = cands[j]["quality"] - pen
    for k in range(1, n - 1):
        for j in range(m):
            tj = times[j]
            if tj - start > (k + 1) * hard_max + 1e-6 or end - tj > (n - 1 - k) * hard_max + 1e-6:
                continue
            for i in range(bisect.bisect_left(times, tj - hard_max - 1e-6), j):
                if best[k - 1][i] == NEG:
                    continue
                pen = cost(tj - times[i])
                if pen is None:
                    continue
                v = best[k - 1][i] + cands[j]["quality"] - pen
                if v > best[k][j]:
                    best[k][j], back[k][j] = v, i
    total, last = NEG, -1
    for j in range(bisect.bisect_left(times, end - hard_max - 1e-6), m):
        if best[n - 2][j] == NEG:
            continue
        pen = cost(end - times[j])
        if pen is None:
            continue
        v = best[n - 2][j] - pen
        if v > total:
            total, last = v, j
    if last < 0:
        return None
    picks = [last]
    for k in range(n - 2, 0, -1):
        picks.append(back[k][picks[-1]])
    return [cands[j] for j in reversed(picks)]


def _choose(cands: list[dict], start: float, end: float, counts: list[int], mode: str) -> list[dict] | None:
    """The cuts for the first count in `counts` that has a plan; with Story parts, the count whose plan keeps every
    part between a minute and three minutes (the closest to the wanted count), or else the one that breaks that
    the fewest times. None when no count has a plan under the cap."""
    duration = end - start
    fallback: tuple[int, list[dict]] | None = None
    for n in counts:
        soft_min, soft_max = _bounds(mode, duration, n)
        cuts = _plan(cands, start, end, n, CAP_PLAN_S, soft_min, soft_max)
        if cuts is None:
            continue
        if mode != "parts":
            return cuts
        bounds = [start] + [c["time"] for c in cuts] + [end]
        outside = sum(1 for a, b in zip(bounds, bounds[1:]) if not soft_min - 1e-6 <= b - a <= soft_max + 1e-6)
        if not outside:
            return cuts
        if fallback is None or outside < fallback[0]:
            fallback = (outside, cuts)
    return fallback[1] if fallback else None


def _even(words: list[dict], start: float, end: float, n: int) -> list[dict]:
    """Last resort: n equal parts, each cut moved to the nearest pause between two words when one is close, so a
    word is never cut in half."""
    step = (end - start) / n
    gaps = [((a["end"] + b["start"]) / 2, max(0.0, b["start"] - a["end"]))
            for a, b in zip(words, words[1:]) if start < (a["end"] + b["start"]) / 2 < end]
    cuts, prev = [], start
    for k in range(1, n):
        t = start + step * k
        inside = [w for w in words if w["start"] < t < w["end"]]
        why = ["no words here to cut between: cut at the length limit"]
        if inside:  # the planned place falls in a word: the nearest pause between words that keeps the cap
            near = [g for g in gaps if g[0] - prev <= CAP_PLAN_S and end - g[0] <= (n - k) * CAP_PLAN_S and g[0] > prev]
            if near:
                g = min(near, key=lambda g: abs(g[0] - t))
                t = g[0]
                why = [f"between two words ({g[1]:.1f} s pause): no sentence ends near here"]
        elif any(abs(w["start"] - t) < 30 or abs(w["end"] - t) < 30 for w in words):
            why = ["between two words: no sentence ends near here"]
        cuts.append({"after": -1, "time": round(t, 3), "quality": -1.0, "why": why, "end_text": "", "next_text": ""})
        prev = t
    return cuts


def split(sents: list[dict], words: list[dict], start: float, end: float, mode: str, rh: dict | None = None,
          chooser: Callable[[int, int, list[dict]], int | None] | None = None) -> list[dict]:
    """The parts of the story [start, end] (seconds): [{"start", "end", "why"}], a single part when it needs no
    cut. `mode` is "whole" or "parts" (see part_count). `rh` is the recording's rhythm(). `chooser(k, n, options)`
    (optional, ClipForge AI) may return the index of the option to use for cut k of n-1; anything else keeps the
    rules' choice."""
    duration = end - start
    n = part_count(duration, mode)
    if n <= 1:
        return [{"start": start, "end": end, "why": []}]
    rh = rh or rhythm(sents)
    least = part_count(duration, "whole")
    # Full story: the fewest parts, one more when that is what a clean cut between sentences needs; Story parts: the
    # wanted count, fewer and longer parts when the story's talking does not allow it (minutes of gameplay at its end)
    counts = [n, n + 1] if mode != "parts" else list(range(n, max(1, least) - 1, -1))
    cands = candidates(sents, start, end, rh)
    cuts = _choose(cands, start, end, counts, mode)
    if cuts is None:  # no set of sentence boundaries fits under the cap: pauses between words, wordless stretches
        pool = sorted(cands + _word_gaps(words, start, end) + _silences(words, start, end), key=lambda c: c["time"])
        cuts = _choose(pool, start, end, counts, mode)
    if cuts is None:
        cuts = _even(words, start, end, n)
    n = len(cuts) + 1
    if chooser is not None and cands:
        soft_min, soft_max = _bounds(mode, duration, n)
        cuts = _second_opinion(cuts, cands, start, end, n, soft_min, soft_max, chooser)
    bounds = [start] + [c["time"] for c in cuts] + [end]
    parts = []
    for k in range(n):
        why = [] if k == 0 else cuts[k - 1]["why"]
        parts.append({"start": round(bounds[k], 3), "end": round(bounds[k + 1], 3), "why": list(why)})
    return parts


def _second_opinion(cuts: list[dict], cands: list[dict], start: float, end: float, n: int, soft_min: float,
                    soft_max: float, chooser: Callable[[int, int, list[dict]], int | None]) -> list[dict]:
    """Offer ClipForge AI's model the best few places around each cut; use its pick only when both parts it
    touches stay inside the lengths the rules' own choice kept (at least `soft_min`, at most `soft_max`, never
    over the cap)."""
    out = list(cuts)
    for k in range(len(out)):
        lo = out[k - 1]["time"] if k else start
        hi = out[k + 1]["time"] if k + 1 < len(out) else end
        near = [c for c in cands if lo < c["time"] < hi]
        options = sorted(near, key=lambda c: (-c["quality"], abs(c["time"] - out[k]["time"])))[:CHOICES]
        if out[k] not in options and out[k] in near:
            options = [out[k]] + options[:CHOICES - 1]
        options.sort(key=lambda c: c["time"])
        if len(options) < 2:
            continue
        try:
            pick = chooser(k + 1, n, options)
        except Exception:  # noqa: BLE001 - the rules decide
            pick = None
        if pick is None or not 0 <= pick < len(options):
            continue
        c = options[pick]
        left, right = c["time"] - lo, hi - c["time"]
        floor = min(soft_min, out[k]["time"] - lo, hi - out[k]["time"])
        ceiling = min(CAP_PLAN_S, max(soft_max, out[k]["time"] - lo, hi - out[k]["time"]))
        if min(left, right) >= floor - 1e-6 and max(left, right) <= ceiling + 1e-6:
            out[k] = {**c, "why": c["why"] + ["ClipForge AI picked this place"]}
    return out
