"""How a full video's sound is joined (batch 3 of the editing-quality work; research and numbers in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/LONG_EDITING.md).

* **Split edits (J and L cuts).** At a straight cut between two different recordings the sound edit moves a few
  frames off the picture cut: the next recording's sound starts early under the last frames of the outgoing picture
  (a J cut), or, when that cannot be done cleanly, the outgoing sound runs on a few frames into the new picture (an
  L cut). Only room sound ever moves across the cut: the frames that change hands must hold no word on either side,
  so nobody is cut off or heard twice, and the captions (placed by the words) stay right.
* **No clicks at a cut between recordings:** the two sounds cross over 40 ms with an equal-power curve (two
  unrelated sounds keep their level through it, where a straight-line crossfade dips 3 dB).
* **Room tone.** A title card, a photo or a video without sound would leave digital silence, which sounds like a
  dropout; it gets the room sound of the nearest recording instead (its quietest stretch between words, looped
  with crossfades), so the background never stops. It steps aside wherever a voiceover plays (the narration brings
  its own room).
* **Music back-timed.** ClipForge's own music beds (made in whole bars, no intro to lose) are started so that their
  own end lands on the video's last frame, instead of being cut wherever the video stops; they then start inside
  the music, so they fade in (at least 1 s). Only music set to repeat ("loop") that plays to the end is moved. The
  owner's own songs start at their start unless "End on the last frame" is ticked for them (`back_time` on the
  item, which also turns it off for a bed). Looping music repeats one decoded pass sample for sample (engine
  _one_pass), so the ending lands where this module says it will.

FilmCraft's timeline (craft/finish.py) has none of this, so with the editing app on "auto" a final that would use
it is rendered by the built-in engine, like the preview the owner approved (`engine.sound_joins_in_use`).
"""
from __future__ import annotations

import math

from . import retime

SPLIT_FRAMES = (8, 6, 4)    # how far the sound edit may move off the picture cut (research: 4-12 frames)
SPLIT_MIN_FRAMES = 3        # each side keeps at least this many times the split as its own sound
WORD_MARGIN_S = 0.1         # a word this close to the frames that change hands still counts (transcript timing)
SCENE_XFADE_MS = 40         # the equal-power crossfade at a sound edit between two recordings or room tone
TONE_MIN_S = 0.5            # a stretch between words at least this long can give room tone
TONE_TRIM_S = 0.12          # kept clear of the words on both sides (breaths, the end of a consonant)
TONE_MAX_S = 3.0            # the sample taken (looped for longer gaps)
TONE_CANDIDATES = 3         # the longest stretches measured; the quietest usable one wins
TONE_RANGE_DB = (-75.0, -38.0)  # quieter is digital silence (nothing to add); louder is not room sound
TONE_XFADE_S = 0.08         # crossfade where the looped sample repeats
BACK_TIME_FADE_IN_MS = 1000  # a back-timed bed starts inside the music, so it always fades in at least this long
LIBRARY_MUSIC_PREFIX = "ClipForge music - "  # library.filename's music beds: back-timed unless the item says not
TONE_BLOCK = 1 << 16        # room tone is written in blocks of this many samples (any length, bounded memory)
TONE_DUCK_MS = 100          # room tone fades out this long before a voiceover and back in after it


def _busy(words: list[dict], a: float, b: float, before: float = 0.0, after: float = 0.0) -> bool:
    """Whether a word is heard in [a, b] (seconds of the recording), widened by `before` and `after`."""
    return any(float(w["end"]) > a - before and float(w["start"]) < b + after for w in words)


def split_edits(els: list[dict], sounding: list[bool], words_by_asset: dict[str, list[dict]],
                lengths_ms: dict[str, int], fps: int) -> dict[int, tuple[int, int]]:
    """{k: (lead, lag)} in frames for each straight cut into element k from a different recording: `lead` frames
    of k's sound start before its picture (J cut) or the outgoing sound runs `lag` frames into it (L cut). Only
    where both recordings were transcribed, so it is known that no word changes hands."""
    out: dict[int, tuple[int, int]] = {}
    for k in range(1, len(els)):
        p, q = els[k - 1], els[k]
        if not (sounding[k - 1] and sounding[k]) or q["ov_in"] or p["asset_id"] == q["asset_id"]:
            continue
        if retime.retimed(p.get("clip") or {}) or retime.retimed(q.get("clip") or {}):
            continue  # a sped-up or slowed side: its sound edit stays with its picture (a crossfade only)
        pw, qw = words_by_asset.get(p["asset_id"]), words_by_asset.get(q["asset_id"])
        if pw is None or qw is None:
            continue
        p_end = (p["src_in_ms"] + p["frames"] * 1000 / fps) / 1000  # where the outgoing picture's source ends
        q_in = q["src_in_ms"] / 1000
        p_len = lengths_ms.get(p["asset_id"], 0) / 1000
        for f in SPLIT_FRAMES:
            s = f / fps
            if min(p["frames"], q["frames"]) < SPLIT_MIN_FRAMES * f:
                continue
            m = WORD_MARGIN_S
            # J: q's room sound from before its in point replaces the outgoing's last frames: no word of q may
            # end in (or just before) those frames, and the outgoing's last word must end well before them
            if q_in - s >= 0 and not _busy(qw, q_in - s, q_in, m) and not _busy(pw, p_end - s, p_end, m):
                out[k] = (f, 0)
                break
            # L: the outgoing room sound runs on under q's first frames: no word of the outgoing may start in
            # them, and q's first word must start well after them
            if p_len and p_end + s <= p_len and not _busy(pw, p_end, p_end + s, 0, m) \
                    and not _busy(qw, q_in, q_in + s, 0, m):
                out[k] = (0, f)
                break
    return out


def clear(words: list[dict] | None, a: float, length: float, file_s: float) -> bool:
    """Whether [a, a + length] (seconds of a transcribed recording) is inside the file and holds no word."""
    if words is None or a < 0 or (file_s and a + length > file_s):
        return False
    return not _busy(words, a, a + length, 0.05, 0.05)


def tone_candidates(words: list[dict], length_s: float) -> list[tuple[float, float]]:
    """The longest stretches between words (seconds of the recording, trimmed clear of the words), longest first."""
    edges = [0.0] + [x for w in sorted(words, key=lambda w: float(w["start"]))
                     for x in (float(w["start"]), float(w["end"]))] + [length_s]
    gaps = []
    for a, b in zip(edges[::2], edges[1::2]):
        a, b = a + TONE_TRIM_S, b - TONE_TRIM_S
        if b - a >= TONE_MIN_S:
            mid = (a + b) / 2
            half = min(b - a, TONE_MAX_S) / 2
            gaps.append((mid - half, mid + half))
    return sorted(gaps, key=lambda g: g[0] - g[1])[:TONE_CANDIDATES]


def level_db(x) -> float:
    import numpy as np

    rms = float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2))) if len(x) else 0.0
    return 20 * math.log10(max(rms, 1e-12))


def usable_tone(level: float) -> bool:
    return TONE_RANGE_DB[0] <= level <= TONE_RANGE_DB[1]


def loop_tone_blocks(sample, n: int, sr: int):
    """`n` samples of room tone from `sample` (shape (m, 2)), in pieces: the sample repeated with equal-power
    crossfades, every other copy played backwards so the seams and any slow change in it do not repeat the same way.
    Only one copy is held at a time, so an hour of tone takes no more memory than a second."""
    import numpy as np

    sample = np.asarray(sample, dtype=np.float32)
    m = len(sample)
    if n <= 0:
        return
    if m == 0:
        for at in range(0, n, TONE_BLOCK):
            yield np.zeros((min(TONE_BLOCK, n - at), 2), dtype=np.float32)
        return
    xf = min(int(TONE_XFADE_S * sr), m // 4)
    t = (np.arange(xf, dtype=np.float64) + 0.5) / max(1, xf)
    rise = np.sin(t * np.pi / 2).astype(np.float32)[:, None]
    fall = np.cos(t * np.pi / 2).astype(np.float32)[:, None]
    carry = None   # the faded tail of the copy before, which overlaps the start of the next
    written, k = 0, 0
    while written < n:
        piece = (sample if k % 2 == 0 else sample[::-1]).copy()
        if k and xf:
            piece[:xf] *= rise
        if xf:
            piece[m - xf:] *= fall
        if carry is not None:
            piece[:xf] += carry
        body, carry = (piece[:m - xf], piece[m - xf:]) if xf else (piece, None)
        take = min(len(body), n - written)
        yield body[:take]
        written += take
        k += 1


def uncovered_ms(a: float, b: float, spans: list[tuple[float, float]]) -> float:
    """How much of [a, b] (ms) no span covers (spans may overlap each other)."""
    covered, reach = 0.0, a
    for s, e in sorted(spans):
        s, e = max(s, reach), min(e, b)
        if e > s:
            covered += e - s
            reach = e
    return max(0.0, b - a - covered)


def duck_gain(at: int, m: int, quiet: list[tuple[int, int]], ramp: int):
    """The gain of samples at..at+m of a room-tone part that steps aside for a voiceover: 0 inside each `quiet`
    range (samples, relative to the part), a straight ramp over `ramp` samples just outside it, 1 elsewhere. None
    when no range comes near these samples (nothing to change)."""
    import numpy as np

    near = [(s, e) for s, e in quiet if s - ramp < at + m and e + ramp > at]
    if not near:
        return None
    t = np.arange(at, at + m, dtype=np.float64)
    gain = np.ones(m)
    for s, e in near:
        away = np.maximum(s - t, t - e)  # > 0 outside the range: samples to its nearer edge
        gain = np.minimum(gain, np.clip(away / max(1, ramp), 0.0, 1.0))
    return gain.astype(np.float32)[:, None]


def loop_tone(sample, n: int, sr: int):
    """loop_tone_blocks in one array (for short tones and tests)."""
    import numpy as np

    blocks = list(loop_tone_blocks(sample, n, sr))
    return np.concatenate(blocks) if blocks else np.zeros((0, 2), dtype=np.float32)


def back_times(item: dict, filename: str) -> bool:
    """Whether a music item that repeats and plays to the end is back-timed: as the item says ("End on the last
    frame"), else only ClipForge's own beds; the owner's own song keeps its start (often why it was chosen)."""
    choice = item.get("back_time")
    if choice is not None:
        return bool(choice)
    return str(filename or "").startswith(LIBRARY_MUSIC_PREFIX)


def back_time_offset(n: int, file_n: int) -> int:
    """Samples to skip at the start of a looping music file so that, after whole repeats, its own end lands on the
    last of the `n` samples it plays (0 when it already does, or the length is unknown)."""
    if file_n <= 0 or n <= 0:
        return 0
    repeats = math.ceil(n / file_n)
    return repeats * file_n - n
