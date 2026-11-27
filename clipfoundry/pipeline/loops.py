"""Loop endings for short clips (batch 4c of the editing-quality work; research in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/SHORTS_EDITING.md, "Loop endings").

TikTok, Shorts and Reels play a clip again as soon as it ends. A clip that stops 100-150 ms after its last word,
without a fade or an end card, runs straight back into its start, and the replay reads as one more cut instead of a
restart. So the renderer:

* **Tightens the seam.** The kept picture and sound start `HEAD_KEEP` before the first sound and stop `TAIL_KEEP`
  after the last one (a word, or a laugh or shout heard after it), so the end and the start meet with about the
  pause people leave between two sentences (0.2-0.3 s). A quiet stretch longer than `MAX_HEAD` before the first
  word or `MAX_TAIL` after the last one is something else (a look, an action, a reveal) and stays as it is.
* **Switches the shot size on the seam** (moves.punch_curve with `loop=True`): every other jump cut in the clip
  changes between the plain and the punched-in framing, so the loop seam does too.

Nothing else moves: the clip's start and end stay where the owner (or ClipForge) put them; only what is played is
tightened, like silence cleanup does inside the clip.
"""
from __future__ import annotations

import math

HEAD_KEEP = 0.10   # before the first word: its attack (research keeps 30-50 ms; word times are estimates)
TAIL_KEEP = 0.15   # after the last sound (research: cut 100-150 ms after the last word, no fade, no end card)
MAX_HEAD = 0.8     # more quiet than this before the first word is a moment of its own: left alone
MAX_TAIL = 1.2     # the same after the last word
MIN_LENGTH = 1.0   # a clip never gets shorter than this


def _heard(words: list[dict], segs: list[tuple[float, float]]) -> list[dict]:
    """The words that are played: their middle lies in a kept part."""
    out = []
    for w in words:
        mid = (float(w["start"]) + float(w["end"])) / 2
        if str(w.get("w", "")).strip() and any(a <= mid < b for a, b in segs):
            out.append(w)
    return out


def seam(segs: list[tuple[float, float]], words: list[dict], start: float, fps: float, speed: float = 1.0,
         loud: list[tuple[float, float]] | None = None) -> tuple[list[tuple[float, float]], dict | None]:
    """The kept parts with the loop seam tightened, and what was done ({head_s, tail_s, seam_s}: source seconds
    taken off each end and the pause at the seam in the clip's own time), or None when there is nothing to do (no
    words heard). `start` is the clip's start (the frame grid counts from it); `loud`: reactions without words
    (render.heard), kept like words."""
    if not segs:
        return segs, None
    said = _heard(words, segs)
    if not said:
        return segs, None
    first = min(float(w["start"]) for w in said)
    last = max(float(w["end"]) for w in said)
    for a, b in loud or []:  # a laugh right after the last word (or right before the first) is part of the clip
        if any(x <= (a + b) / 2 < y for x, y in segs):
            if a <= last + MAX_TAIL and b > last:
                last = b
            if b >= first - MAX_HEAD and a < first:
                first = a
    a0, b1 = segs[0][0], segs[-1][1]
    # on the clip's frame grid: a little more kept rather than less (a word's first and last sounds survive)
    head = start + math.floor((first - HEAD_KEEP - start) * fps + 1e-6) / fps
    tail = start + math.ceil((last + TAIL_KEEP - start) * fps - 1e-6) / fps
    new_a = head if a0 < head and first - a0 <= MAX_HEAD else a0
    new_b = tail if tail < b1 and b1 - last <= MAX_TAIL else b1
    out = [(max(a, new_a), min(b, new_b)) for a, b in segs]
    out = [(a, b) for a, b in out if b - a >= 2 / fps - 1e-9]
    if not out or sum(b - a for a, b in out) < MIN_LENGTH:
        return segs, None
    head_s, tail_s = max(0.0, out[0][0] - a0), max(0.0, b1 - out[-1][1])
    gap = (max(0.0, first - out[0][0]) + max(0.0, out[-1][1] - last)) / max(speed, 1e-6)
    return out, {"head_s": round(head_s, 3), "tail_s": round(tail_s, 3), "seam_s": round(gap, 3)}
