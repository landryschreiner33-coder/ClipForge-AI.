"""The short-clip editor's moves: punch-ins on jump cuts, a framing change every few seconds, and sound effects that
come from the edit itself (batch 2 of the editing-quality work; research and numbers in
docs/clipforge/EDITING_CRAFT_RESEARCH.md, what the owner sees in docs/clipforge/SHORTS_EDITING.md).

* **Punch-ins.** Where a pause or a filler was cut out of continuous speech, the picture jumps; editors hide that
  jump by changing the shot size on the cut: 1.00 and 1.10 alternate at every jump cut, switched on the cut itself
  (an eased zoom across a cut looks like a mistake). Sources under 1080 lines get a smaller step (more upscaling
  would show). The zoom is centred on the tracked face (render._compose), so the face stays where it was.
* **Something changes every few seconds.** No framing is held longer than `MAX_HOLD` seconds: a long stretch
  without cuts gets an eased change at the pause nearest the middle of the window (never mid-word when a pause is
  there).
* **Emphasis push.** On a stressed word (render.emphasis_words: numbers, strong words, the clip's keywords) the
  camera pushes in a little further, eased, and lets go at the next change; at most one every `PUSH_GAP` seconds, so
  it still means something.
* **Sound effects from the edit.** A soft whoosh lands with each emphasis push and a light pop with each key word
  that is coloured in the captions, never two within `FX_GAP` seconds, never in the first moment or the last
  second (the loop), 18-22 dB under the speech. They are made here from noise and tones (no sound files, nothing
  to license) and varied, so two pops never sound the same.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from .text_utils import ends_sentence

PUNCH = 0.10            # the jump-cut punch-in (research: 1.10-1.15 at every jump cut inside continuous speech)
PUNCH_LOW_RES = 0.06    # sources under 1080 lines: they are already enlarged to fill a 1080x1920 frame
MIN_SHOT = 0.6          # a cut this close to the last change (or the end) keeps the framing: no flicker
MAX_HOLD = 5.0          # the framing changes at least this often (research: something changes every 2-5 s)
HOLD_AIM = 3.5          # where in a long stretch the change goes, if a pause is there
LOOP_AIM = 1.5          # a loop ending's extra change goes about this long before the end (loops.py)
EASE = 0.4              # seconds an eased change takes
PUSH_SHARE = 0.5        # the emphasis push, as a share of the punch
PUSH_LEAD = 0.3         # the push starts this long before the word and lands on it
PUSH_HOLD = 2.5         # and lets go at the next change, at the latest after this long
PUSH_GAP = 6.0          # pushes at least this far apart
SR = 48000
FX_GAP = 4.0            # no two effects closer than this
FX_EDGE = (0.3, 1.0)    # no effects in the first 0.3 s or the last second (the loop back to the start)
WHOOSH_PEAK_DB = -24.0  # peak level after the clip's loudness is set to -14 LUFS: about 18-20 dB under speech
POP_PEAK_DB = -22.0
WORD_LEAD = 0.04        # captions light a word about one frame before it is heard (sound after picture is noticed
                        # from 45 ms; a highlight that is late feels wrong, one that is early does not)


def punch_strength(source_height: int) -> float:
    return PUNCH if source_height >= 1080 else PUNCH_LOW_RES


def jump_cuts(segs: list[tuple[float, float]], speed: float = 1.0,
              frames: list[float] | None = None) -> list[tuple[float, float]]:
    """(output time, seconds of the source skipped) for each cut between two kept parts of one recording. With
    `frames` (the output times at which the renderer really shows each new part, whole frames), those are used, so
    a switch lands on exactly the first frame of the new shot at any speed."""
    out, acc = [], 0.0
    for i, ((a, b), nxt) in enumerate(zip(segs, segs[1:])):
        acc += b - a
        out.append((frames[i] if frames is not None and i < len(frames) else acc / speed, nxt[0] - b))
    return out


def _pauses(words: list[dict]) -> list[float]:
    """Output times between two words where a change can go: a gap of at least 0.12 s or the end of a sentence."""
    out = []
    for w, nxt in zip(words, words[1:]):
        if nxt["start"] - w["end"] >= 0.12 or ends_sentence(w["w"]):
            out.append((w["end"] + nxt["start"]) / 2)
    return out


def _smooth(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def changes(words: list[dict], cuts: list[tuple[float, float]], duration: float,
            max_hold: float = MAX_HOLD, loop: bool = False) -> list[tuple[float, bool]]:
    """(time, on a cut) for every framing change: the jump cuts (not too close together) and eased changes in
    long stretches without one. With `loop` (a loop ending, loops.py) the number of changes is made odd, so the
    clip ends on the other shot size than it starts with and the loop back to the start switches it too."""
    hard, last = [], 0.0
    for t, _skipped in cuts:
        if t - last >= MIN_SHOT and duration - t >= MIN_SHOT:
            hard.append(t)
            last = t
    pauses = _pauses(words)
    soft = []
    bounds = [0.0, *hard, duration]
    for a, b in zip(bounds, bounds[1:]):
        cur = a
        while b - cur > max_hold:
            lo, hi = cur + 2.5, min(cur + max_hold, b - MIN_SHOT)
            if hi <= lo:
                break
            near = [p for p in pauses if lo <= p <= hi]
            t = min(near, key=lambda p: abs(p - (cur + HOLD_AIM))) if near else min(hi, cur + max_hold - 1.0)
            soft.append(t)
            cur = t
    events = sorted([(t, True) for t in hard] + [(t, False) for t in soft])
    return _odd(events, pauses, duration) if loop and len(events) % 2 == 0 else events


def _odd(events: list[tuple[float, bool]], pauses: list[float], duration: float) -> list[tuple[float, bool]]:
    """Every change switches the size, so an even number of them ends on the size the clip started with. One more
    eased change, in the last stretch if it has room (at a pause about `LOOP_AIM` before the end) or else in the
    longest one that has (held at least 2.5 s before it and 1 s after it), or, when none has, one eased change
    fewer. A clip whose changes are all jump cuts close together stays as it is (a jump cut always switches)."""
    bounds = [0.0, *(t for t, _ in events), duration]
    room = [(lo, hi) for lo, hi in ((a + 2.5, b - 1.0) for a, b in zip(bounds, bounds[1:])) if hi >= lo]
    if room:
        lo, hi = room[-1] if room[-1][1] == duration - 1.0 else max(room, key=lambda r: r[1] - r[0])
        aim = duration - LOOP_AIM if hi == duration - 1.0 else (lo + hi) / 2
        near = [p for p in pauses if lo <= p <= hi]
        at = min(near, key=lambda p: abs(p - aim)) if near else min(hi, max(lo, aim))
        return sorted(events + [(at, False)])
    eased = [e for e in events if not e[1]]
    return [e for e in events if e != eased[-1]] if eased else events


def pushes(words: list[dict], emphasis: set[int] | None, duration: float) -> list[float]:
    """Output times of the stressed words the camera pushes in on (rationed)."""
    kept: list[float] = []
    for i in sorted(emphasis or (), key=lambda i: words[i]["start"]):
        t = words[i]["start"]
        if t < 0.5 or duration - t < 1.0 or (kept and t - kept[-1] < PUSH_GAP):
            continue
        kept.append(t)
    return kept


def punch_curve(words: list[dict], cuts: list[tuple[float, float]], n: int, fps: float, strength: float,
                emphasis: set[int] | None = None, loop: bool = False) -> np.ndarray:
    """The zoom for each output frame (1.0 = the framing's own size): switched on jump cuts, eased elsewhere, with
    a push on rationed stressed words. With `loop` (a loop ending) the last framing differs from the first, so the
    loop back to the start changes the shot size too (`changes`)."""
    z = np.ones(n)
    if strength <= 0 or n < 2:
        return z
    duration = n / fps
    t = np.arange(n) / fps
    events = changes(words, cuts, duration, loop=loop)
    level, value = np.ones(n), 1.0
    for at, on_cut in events:
        new = 1.0 + strength if value == 1.0 else 1.0
        k = min(n, int(round(at * fps)))
        level[k:] = new if on_cut else value + (new - value) * _smooth((t[k:] - at) / EASE)
        value = new
    push = np.zeros(n)
    amount = strength * PUSH_SHARE
    for at in pushes(words, emphasis, duration):
        a = at - PUSH_LEAD
        # a jump cut just before the word: the push comes in on the cut with the new shot (never eased across it)
        cut_before = max((e for e, c in events if c and a < e <= at), default=None)
        end = min(next((e for e, _ in events if e > at + 0.8), duration), at + PUSH_HOLD)
        on_cut = any(abs(e - end) < 1e-9 and c for e, c in events)
        k0 = min(n, int(round(cut_before * fps))) if cut_before is not None else max(0, int(a * fps))
        # letting go on a cut: on the same frame as the level switch above, so no frame gets both
        k1 = min(n, int(round(end * fps)) if on_cut else int(math.ceil(end * fps)))
        seg = t[k0:k1]
        shape = np.ones(len(seg)) if cut_before is not None else _smooth((seg - a) / PUSH_LEAD)
        if not on_cut:
            shape = shape * (1 - _smooth((seg - (end - EASE)) / EASE))
        push[k0:k1] = np.maximum(push[k0:k1], amount * shape)
    return level + push


# ------------------------------------------------------------------ sound effects
def effect_events(words: list[dict], push_times: list[float], duration: float) -> list[dict]:
    """The effects a clip gets: a whoosh landing with each push, a pop on each coloured key word (`em`)."""
    lo, hi = FX_EDGE[0], duration - FX_EDGE[1]
    wanted = [(at, "whoosh") for at in push_times] + \
             [(max(0.0, w["start"] - WORD_LEAD), "pop") for w in words if w.get("em")]
    picked: list[tuple[float, str]] = []
    # the pushes first: a key word that is pushed in on gets its whoosh, not a pop as well
    for at, kind in sorted(wanted, key=lambda x: (x[1] != "whoosh", x[0])):
        if lo <= at <= hi and all(abs(at - p) >= FX_GAP for p, _ in picked):
            picked.append((at, kind))
    return [{"at": round(at, 3), "kind": kind, "n": i} for i, (at, kind) in enumerate(sorted(picked))]


def whoosh(seed: int, length: float = 0.42, land: float = 0.7) -> np.ndarray:
    """Air moving past: noise through a band-pass whose centre rises, swelling to its peak at `land` of its length
    (the moment it lands on) and dying away; it moves from one side to the other. Stereo, peak 1.0."""
    rng = np.random.default_rng(1000 + seed)
    n = int(length * SR)
    noise = rng.standard_normal(n)
    spec = np.fft.rfft(noise)
    f = np.fft.rfftfreq(n, 1 / SR)
    out = np.zeros(n)
    hop = 1024
    win = np.hanning(2 * hop)
    lo_f, hi_f = 500 * (1 + 0.15 * rng.uniform(-1, 1)), 3200 * (1 + 0.15 * rng.uniform(-1, 1))
    for k0 in range(-hop, n, hop):  # overlap-add of short band-passed slices, the band rising with time
        frac = min(1.0, max(0.0, (k0 + hop) / n))
        centre = lo_f * (hi_f / lo_f) ** frac
        band = np.exp(-0.5 * (np.log(np.maximum(f, 1.0) / centre) / 0.55) ** 2)
        sl = np.fft.irfft(spec * band, n)
        a, b = max(0, k0), min(n, k0 + 2 * hop)
        out[a:b] += sl[a:b] * win[a - k0:b - k0]
    x = np.arange(n) / n
    env = np.where(x < land, (x / land) ** 2, np.exp(-(x - land) / (1 - land) * 4.0))
    mono = out * env
    mono /= np.abs(mono).max() + 1e-12
    pan = np.linspace(-0.6, 0.6, n) * (1 if seed % 2 == 0 else -1)   # constant-power pan, -1 left .. 1 right
    angle = (pan + 1) * np.pi / 4
    stereo = np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1)
    return stereo / (np.abs(stereo).max() + 1e-12)


def pop(seed: int, length: float = 0.09) -> np.ndarray:
    """A light pop: a short tone that drops in pitch, with a tiny click on top. Stereo (centre), peak 1.0."""
    rng = np.random.default_rng(2000 + seed)
    n = int(length * SR)
    t = np.arange(n) / SR
    f0 = 900 * (1 + 0.12 * rng.uniform(-1, 1))
    freq = f0 * (0.45 + 0.55 * np.exp(-t / 0.02))
    phase = 2 * np.pi * np.cumsum(freq) / SR
    tone = np.sin(phase) * np.exp(-t / 0.025) * np.minimum(1.0, t / 0.002)
    click = rng.standard_normal(n) * np.exp(-t / 0.003) * 0.25
    mono = tone + click
    mono /= np.abs(mono).max() + 1e-12
    return np.stack([mono, mono], axis=1)


def effects_track(events: list[dict], duration: float) -> np.ndarray:
    """The clip's effects as one stereo track (float, 48 kHz) on the output timeline."""
    track = np.zeros((int(math.ceil(duration * SR)) + 1, 2))
    for e in events:
        if e["kind"] == "whoosh":
            sound, land, peak = whoosh(e["n"]), 0.7, WHOOSH_PEAK_DB
        else:
            sound, land, peak = pop(e["n"]), 0.0, POP_PEAK_DB
        sound = sound * 10 ** (peak / 20)
        k = int(round((e["at"] - land * len(sound) / SR) * SR))
        a, b = max(0, k), min(len(track), k + len(sound))
        if b > a:
            track[a:b] += sound[a - k:b - k]
    return track


def effects_gain(speech_lufs: float | None, normalization_gain_db: float) -> float:
    """dB to move the effects by so they keep their distance under the speech: they are made for speech at -14
    LUFS, and speech can end up quieter (normalization held back by peaks, or off) or louder (off)."""
    if speech_lufs is None or not math.isfinite(speech_lufs):
        return 0.0
    return max(-30.0, min(6.0, speech_lufs + normalization_gain_db + 14.0))


def write_wav(track: np.ndarray, path: Path) -> Path:
    """16-bit stereo WAV at 48 kHz (every FFmpeg reads it; the levels are far below clipping)."""
    pcm = (np.clip(track, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path
