"""Loop endings for short clips (batch 4c of the editing-quality work; research in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/SHORTS_EDITING.md, "Loop endings").

TikTok, Shorts and Reels play a clip again as soon as it ends. A clip that stops 100-150 ms after its last word,
without a fade or an end card, runs straight back into its start, and the replay reads as one more cut instead of a
restart. So the renderer:

* **Tightens the seam.** The kept picture and sound start `HEAD_KEEP` before the first sound and stop `TAIL_KEEP`
  after the last one (a word, or a laugh or shout heard after it), so the end and the start meet with about the
  pause people leave between two sentences (0.2-0.3 s). A quiet stretch longer than `MAX_HEAD` before the first
  word or `MAX_TAIL` after the last one is something else (a look, an action, a reveal) and stays as it is.
* **Puts no end inside another shot or word.** When a hard scene cut falls between the last word and the new end
  (or between the new start and the first word), that end goes on the cut; a word the clip's own edge cuts through
  is left out whole instead of clipped.
* **Switches the shot size on the seam** (moves.changes with `loop=True`): every jump cut in the clip changes
  between the plain and the punched-in framing, so the loop seam does too.

Nothing else moves: the clip's start and end stay where the owner (or ClipForge) put them; only what is played is
tightened, like silence cleanup does inside the clip.
"""
from __future__ import annotations

import math
from typing import Callable

HEAD_KEEP = 0.10   # before the first word: its attack (research keeps 30-50 ms; word times are estimates)
TAIL_KEEP = 0.15   # after the last sound (research: cut 100-150 ms after the last word, no fade, no end card)
MAX_HEAD = 0.8     # more quiet than this before the first word is a moment of its own: left alone
MAX_TAIL = 1.2     # the same after the last word
MIN_LENGTH = 1.0   # a clip never gets shorter than this (in its own time, at its speed)


def _mid_in(w: dict, segs: list[tuple[float, float]]) -> bool:
    mid = (float(w["start"]) + float(w["end"])) / 2
    return any(a <= mid < b for a, b in segs)


def _heard(words: list[dict], segs: list[tuple[float, float]]) -> list[dict]:
    """The words that are played: their middle lies in a kept part."""
    return [w for w in words if str(w.get("w", "")).strip() and _mid_in(w, segs)]


def within(words: list[dict], segs: list[tuple[float, float]]) -> list[dict]:
    """The words still played after the seam: the ones whose middle lies between the first kept moment and the last
    (a word the seam left out gets no caption)."""
    if not segs:
        return words
    a, b = segs[0][0], segs[-1][1]
    return [w for w in words if a <= (float(w["start"]) + float(w["end"])) / 2 < b]


def seam(segs: list[tuple[float, float]], words: list[dict], start: float, fps: float, speed: float = 1.0,
         loud: list[tuple[float, float]] | None = None,
         cuts: Callable[[float, float], list[float]] | None = None) -> tuple[list[tuple[float, float]], dict | None]:
    """The kept parts with the loop seam tightened, and what was done ({head_s, tail_s, seam_s}: source seconds
    taken off each end and the pause at the seam in the clip's own time), or None when there is nothing to do (no
    words heard). `words`: the transcript's words (what is said, whatever the captions show); `start`: the clip's
    start (the frame grid counts from it); `loud`: reactions without words (render.heard), kept like words;
    `cuts(t0, t1)`: hard scene cuts in a stretch of the source, so an end never shows a frame or two of another
    shot (it is put on the cut instead)."""
    if not segs:
        return segs, None
    said = _heard(words, segs)
    if not said:
        return segs, None
    played = {id(w) for w in said}
    first = min(float(w["start"]) for w in said)
    last = max(float(w["end"]) for w in said)
    for a, b in loud or []:  # a laugh right after the last word (or right before the first) is part of the clip
        if _mid_in({"start": a, "end": b}, segs):
            if a <= last + MAX_TAIL and b > last:
                last = b
            if b >= first - MAX_HEAD and a < first:
                first = a
    a0, b1 = segs[0][0], segs[-1][1]

    def down(t: float) -> float:  # the frame grid, at or before t
        return start + math.floor((t - start) * fps + 1e-6) / fps

    def up(t: float) -> float:   # the frame grid, at or after t
        return start + math.ceil((t - start) * fps - 1e-6) / fps

    # a little more kept rather than less (a word's first and last sounds survive), but never into a word that is
    # not played (one the clip's own edge cuts through)
    head = max([down(first - HEAD_KEEP)] + [up(float(w["end"])) for w in words
                                            if first - MAX_HEAD <= float(w["end"]) <= first and id(w) not in played])
    tail = min([up(last + TAIL_KEEP)] + [down(float(w["start"])) for w in words
                                         if last <= float(w["start"]) <= last + MAX_TAIL and id(w) not in played])
    new_a = head if a0 < head <= first and first - a0 <= MAX_HEAD else a0
    new_b = tail if last <= tail < b1 and b1 - last <= MAX_TAIL else b1
    if cuts is not None and new_b < b1:  # another shot starts before the new end: end on the cut, or as before
        shot = [c for c in cuts(last, new_b + 1 / fps) if last < c <= new_b + 1e-6]
        new_b = down(shot[0]) if shot and down(shot[0]) >= last - 1 / fps else (b1 if shot else new_b)
    if cuts is not None and new_a > a0:   # a shot ends after the new start: start on the new shot, or as before
        shot = [c for c in cuts(new_a - 1 / fps, first) if new_a - 1e-6 <= c < first]
        new_a = up(shot[-1]) if shot and up(shot[-1]) <= first + 1 / fps else (a0 if shot else new_a)
    out = [(max(a, new_a), min(b, new_b)) for a, b in segs]
    out = [(a, b) for a, b in out if b - a >= 2 / fps - 1e-9]
    if not out or sum(b - a for a, b in out) / max(speed, 1e-6) < MIN_LENGTH:
        return segs, None
    head_s, tail_s = max(0.0, out[0][0] - a0), max(0.0, b1 - out[-1][1])
    gap = (max(0.0, first - out[0][0]) + max(0.0, out[-1][1] - last)) / max(speed, 1e-6)
    return out, {"head_s": round(head_s, 3), "tail_s": round(tail_s, 3), "seam_s": round(gap, 3)}
