"""The Viral Predictor's model: from measured signals to a hook score, a hold curve, an attention map and a viral
score, each with the reasons behind it.

How it is built (docs/clipforge/VIRAL_PREDICTOR.md has the sources and every number):

* Five channels, one value per second from 0 to 1, the same five areas Higgsfield's predictor shows as a "brain"
  heatmap: Vision (movement, new shots, faces), Sound (loudness, sudden sounds, reactions), Language (speech, how
  much it says, hook words, on-screen text), Attention (something new keeps the eye: cuts, sound jumps, emphasis, a
  question; it fades when nothing changes) and Memory (what sticks: emphasis, emotion, payoff lines, reactions,
  numbers, and the ending). They are measured from the clip, not read from a brain model.
* The hook is the first three seconds of picture, sound and words. Viewers decide there whether to stay (YouTube
  counts an engaged view only past the start; TikTok weighs skips), and a study of brain activity while watching
  (Tong et al., PNAS 2020) found that the reaction in the first seconds forecast how a video did online.
* The hold curve is a modelled audience: part of it swipes away in the first two seconds (fewer the stronger the
  hook), then a few per cent a second leave, more when nothing new happens, during dead air and in stretches that
  give the eye, the ear and the mind little; an open question keeps them. Hold rate is the share still there at the
  end, average watched the share of the clip an average viewer sees.
* The viral score mixes the clip's content (the 11-factor Viral Potential of its own words), the hook, how much of it
  is watched and its memorable moments. The mix can learn from the owner's real results (predictor/learn.py).

All of it is an estimate for comparing clips and finding what to fix. It never promises views.
"""
from __future__ import annotations

import math

import numpy as np

from ..pipeline.text_utils import (CONTRAST_WORDS, EMOTION_WORDS, HOOK_WORDS, OPEN_LOOP_PHRASES, PAYOFF_PHRASES,
                                   content_tokens, count_phrases, tokens)
from .signals import BIN, SILENT_DB, Signals

MODEL_VERSION = 1
CHANNELS = ("vision", "sound", "language", "attention", "memory")
CHANNEL_LABELS = {"vision": "Vision", "sound": "Sound", "language": "Language", "attention": "Attention",
                  "memory": "Memory"}
CHANNEL_HELP = {
    "vision": "Movement, new shots and faces on screen",
    "sound": "Loudness, sudden sounds and reactions",
    "language": "Speech, how much it says, hook words and on-screen text",
    "attention": "Something new keeps the eye; it fades when nothing changes",
    "memory": "What sticks: emphasis, emotion, payoff lines, reactions, numbers and the ending",
}
# the viral score's mix (learned values replace these within bounds, see learn.py)
WEIGHTS = {"content": 0.25, "hook": 0.25, "watch": 0.30, "memory": 0.10, "look": 0.10}
COMPONENT_LABELS = {"content": "What it says (Viral Potential)", "hook": "Hook", "watch": "How much is watched",
                    "memory": "Memorable moments", "look": "Something to look at"}
BANDS = ((90, "Very high"), (75, "High"), (60, "Good"), (40, "Fair"), (0, "Low"))
HOOK_SECONDS = 3.0
SWIPE_SECONDS = 2.0
STAY_MIN, STAY_SPAN = 0.40, 0.45       # share past the first 2 s: 40% with no hook at all, 85% with a perfect one
BASE_HAZARD = 0.010                    # per second: viewers who leave anyway
LOW_HAZARD = 0.045                     # per second, extra, when a stretch gives the viewer nothing
BORED_AFTER = 3.0                      # seconds without anything new before boredom builds
BORED_STEP, BORED_MAX = 0.008, 0.035   # per second of it, per second
DEAD_HAZARD = 0.08                     # per second of silence over a still picture
BLANK_HAZARD = 0.02                    # per second, extra, while there is nothing to look at (no movement, no face)
OPEN_LOOP_KEEP = 0.75                  # an unanswered question: hazard times this until it is answered
ATTENTION_HALF_LIFE = 2.5              # seconds for the pull of something new to halve
ESTIMATE_NOTE = ("A prediction from this clip's picture, sound and words, used to compare clips and find what to "
                 "fix. It is not a promise of views.")
NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "hundred", "thousand",
                "million", "billion", "percent", "half", "double", "twice"}
QUESTION_STARTS = {"why", "how", "what", "who", "when", "where", "which", "would", "could", "should", "did", "do",
                   "does", "is", "are", "can", "have"}


def _clamp(x):
    return np.clip(x, 0.0, 1.0)


def band(score: float) -> str:
    return next(label for floor, label in BANDS if score >= floor)


def _per_second(bins: np.ndarray, duration: float) -> list[float]:
    secs = max(1, int(math.ceil(duration - 1e-9)))
    out = []
    for s in range(secs):
        part = bins[int(s / BIN):int((s + 1) / BIN)]
        out.append(round(float(part.mean()) if len(part) else float(bins[-1]), 3))
    return out


def _smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    k = max(1, int(round(seconds / BIN)))
    if k <= 1 or len(x) < 2:
        return x.copy()
    pad = np.concatenate([np.full(k // 2, x[0]), x, np.full(k - 1 - k // 2, x[-1])])
    return np.convolve(pad, np.ones(k) / k, mode="valid")[:len(x)]


def _fmt(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ------------------------------------------------------------------ words, per bin
def word_bins(sig: Signals) -> dict:
    """What the words say in each bin: content words, hook words, emotion, numbers, payoff and question lines."""
    n = sig.n
    out = {k: np.zeros(n) for k in ("content", "hookw", "emotion", "numbers", "payoff", "question", "line_start")}
    words = sig.words
    for w in words:
        k = min(n - 1, int(float(w["start"]) // BIN))
        toks = tokens(w["w"])
        if not toks:
            continue
        t = toks[0]
        out["content"][k] += 1.0 if content_tokens(w["w"]) else 0.0
        out["hookw"][k] += 1.0 if (t in HOOK_WORDS or t in CONTRAST_WORDS or t == "you") else 0.0
        out["emotion"][k] += 1.0 if t in EMOTION_WORDS else 0.0
        out["numbers"][k] += 1.0 if (t in NUMBER_WORDS or any(c.isdigit() for c in t)) else 0.0
    from ..pipeline.text_utils import build_sentences

    for s in build_sentences([{"w": w["w"], "start": float(w["start"]), "end": float(w["end"])} for w in words]) \
            if words else []:
        a = min(n - 1, int(float(s["start"]) // BIN))
        b = min(n - 1, int(max(float(s["start"]), float(s["end"]) - 0.01) // BIN))
        low = s["text"].lower()
        first = (tokens(low) or [""])[0]
        out["line_start"][a] = 1.0
        if s["text"].rstrip().endswith("?") or (first in QUESTION_STARTS and len(tokens(low)) <= 14
                                                and not low.rstrip().endswith(".")):
            out["question"][a] = 1.0
        if count_phrases(low, OPEN_LOOP_PHRASES):
            out["question"][a] = max(out["question"][a], 0.7)
        if count_phrases(low, PAYOFF_PHRASES):
            out["payoff"][b] = 1.0
    return out


# ------------------------------------------------------------------ the five channels
def channels(sig: Signals, wb: dict | None = None) -> tuple[dict[str, np.ndarray], dict]:
    """Per-bin channel values (0-1) and the per-bin events behind them (for the reasons and the hold curve)."""
    n = sig.n
    wb = wb or word_bins(sig)
    ev: dict[str, np.ndarray] = {}
    # --- vision
    if sig.has_picture:
        motion = _clamp(np.asarray(sig.motion) / 0.05)
        cuts = np.asarray(sig.cuts)
        novelty = np.zeros(n)
        level = 0.0
        for k in range(n):
            level = max(level * (0.6 ** BIN), min(1.0, float(cuts[k])))
            novelty[k] = level
        face = np.nan_to_num(np.asarray(sig.face, dtype=float), nan=0.0)
        face_n = _clamp(face / 0.22)
        text = np.nan_to_num(np.asarray(sig.text, dtype=float), nan=0.0)
        dark = np.asarray(sig.luma) < 0.07
        vision = _clamp(0.42 * motion + 0.33 * novelty + 0.25 * face_n + 0.08 * text)
        vision = np.where(dark, vision * 0.35, vision)
        ev.update(cut=cuts > 0, face=face >= 0.08, text=text > 0.5, dark=dark,
                  still=(np.asarray(sig.motion) < 0.004) & (cuts == 0))
        face_appears = np.zeros(n, dtype=bool)
        face_appears[1:] = (face[1:] >= 0.08) & (face[:-1] < 0.08)
        text_appears = np.zeros(n, dtype=bool)
        text_appears[1:] = (text[1:] > 0.5) & (text[:-1] <= 0.5)
    else:
        vision = np.full(n, np.nan)
        face_appears = text_appears = np.zeros(n, dtype=bool)
        text = np.zeros(n)
        ev.update(cut=np.zeros(n, dtype=bool), face=np.zeros(n, dtype=bool), text=np.zeros(n, dtype=bool),
                  dark=np.zeros(n, dtype=bool), still=np.zeros(n, dtype=bool))
    # --- sound
    reacting = np.zeros(n, dtype=bool)
    for a, b in sig.reactions:
        reacting[int(a // BIN):min(n, int(math.ceil(b / BIN)))] = True
    if sig.has_sound:
        lv = np.asarray(sig.level, dtype=float)
        loud_n = _clamp((lv + 50.0) / 35.0)
        onsets = np.asarray(sig.onsets if sig.onsets is not None else np.zeros(n))
        onset_n = _clamp(onsets / (2.0 * BIN))
        jump = np.zeros(n)
        jump[1:] = np.abs(np.diff(lv))
        dyn = _clamp(jump / 9.0)
        sound = _clamp(0.58 * loud_n + 0.22 * onset_n + 0.20 * dyn + 0.30 * reacting)
        silent = lv < SILENT_DB
        ev.update(silent=silent, sound_jump=(jump >= 6.0) & ~silent, onset=onsets > 0)
    else:
        sound = np.full(n, np.nan)
        ev.update(silent=np.ones(n, dtype=bool), sound_jump=np.zeros(n, dtype=bool), onset=np.zeros(n, dtype=bool))
    ev["reaction"] = reacting
    # --- language
    sp = np.asarray(sig.speech, dtype=float)
    rate = _clamp(wb["content"] / (2.2 * BIN))
    hook_n = _clamp((wb["hookw"] + wb["emotion"] + wb["numbers"]) / 2.0)
    reading = text * np.where(sp > 0.3, 0.5, 1.0)
    language = _clamp(sp * (0.45 + 0.35 * rate) + 0.20 * hook_n + 0.25 * reading + 0.15 * wb["question"])
    ev.update(speech=sp > 0.3, question=wb["question"] > 0, payoff=wb["payoff"] > 0)
    # --- attention: something new, fading with ATTENTION_HALF_LIFE
    emph = np.zeros(n, dtype=bool)
    for t in sig.emphasis:
        if 0 <= t < n * BIN:
            emph[int(t // BIN)] = True
    ev["emphasis"] = emph
    hook_line = (wb["line_start"] > 0) & ((wb["hookw"] > 0) | (wb["question"] > 0) | (wb["numbers"] > 0))
    events = _clamp(1.0 * ev["cut"] + 0.5 * np.minimum(2, np.asarray(sig.onsets if sig.onsets is not None
                                                                         else np.zeros(n))) / 2
                    + 0.6 * ev["sound_jump"] + 0.6 * emph + 0.6 * hook_line + 0.8 * reacting + 0.5 * face_appears
                    + 0.4 * text_appears + 0.25 * (wb["line_start"] > 0))
    ev["new"] = events >= 0.25
    decay = 0.5 ** (BIN / ATTENTION_HALF_LIFE)
    pull = np.zeros(n)
    level = 0.0
    for k in range(n):
        level = max(level * decay, float(events[k]))
        pull[k] = level
    base = np.nanmean(np.vstack([vision, sound, language]), axis=0)
    base = np.nan_to_num(base, nan=0.0)
    attention = _clamp(0.4 * base + 0.6 * pull)
    # --- memory: what sticks, and the ending (people remember the peak and the end)
    mem = (0.5 * emph + 0.4 * _clamp(wb["emotion"]) + 0.6 * (wb["payoff"] > 0) + 0.7 * reacting
           + 0.3 * _clamp(wb["numbers"]) + 0.25 * (wb["question"] > 0))
    memory = _clamp(_smooth(mem.astype(float), 1.5) * 1.6)
    if n >= 4 and sig.words:
        last_word = max(float(w["end"]) for w in sig.words)
        if last_word >= sig.duration - 2.5 and (ev["payoff"][-6:].any() or emph[-6:].any() or reacting[-6:].any()):
            memory[-4:] = np.maximum(memory[-4:], 0.6)  # it ends on its point: the ending is what people keep
    chans = {"vision": vision, "sound": sound, "language": language, "attention": attention, "memory": memory}
    return chans, ev


def engagement(chans: dict[str, np.ndarray]) -> np.ndarray:
    """One engagement value per bin from the channels that were measured."""
    weights = {"vision": 0.25, "sound": 0.22, "language": 0.30, "attention": 0.23}
    stack, ws = [], []
    for k, w in weights.items():
        v = chans[k]
        if not np.isnan(v).all():
            stack.append(np.nan_to_num(v, nan=0.0))
            ws.append(w)
    if not stack:
        return np.zeros(len(chans["memory"]))
    if np.allclose(chans["language"], 0):  # no words at all: the picture and the sound carry it
        out = []
        for k, w in zip([k for k in weights if not np.isnan(chans[k]).all()], ws):
            out.append((np.nan_to_num(chans[k], nan=0.0), 0.0 if k == "language" else w))
        tot = sum(w for _, w in out) or 1.0
        return sum(v * w for v, w in out) / tot
    return sum(v * w for v, w in zip(stack, ws)) / sum(ws)


# ------------------------------------------------------------------ the hook
def hook(sig: Signals, chans: dict, ev: dict, wb: dict, content: dict | None = None) -> dict:
    """The first three seconds: picture, sound and words (each 0-1, None when not measured) and the hook (0-100)."""
    first = max(1, int(HOOK_SECONDS / BIN))
    early = max(1, int(1.0 / BIN))
    parts: dict[str, float | None] = {"picture": None, "sound": None, "words": None}
    notes: list[str] = []
    if sig.has_picture:
        v = float(np.mean(chans["vision"][:first]))
        p = 0.55 * v + 0.2 * bool(ev["face"][:early].any()) + 0.15 * bool(ev["text"][:early].any()) \
            + 0.15 * bool(ev["cut"][:first].any() or float(np.mean(sig.motion[:early])) > 0.012)
        if ev["dark"][0]:
            p -= 0.35
            notes.append("starts on a dark or black picture")
        elif bool(ev["still"][:int(SWIPE_SECONDS / BIN)].all()):
            p -= 0.15
            notes.append("the picture does not move in the first 2 s")
        parts["picture"] = float(np.clip(p, 0, 1))
    if sig.has_sound:
        s = float(np.mean(np.nan_to_num(chans["sound"][:first])))
        quiet_open = bool(ev["silent"][:early].all())
        sound_at = next((k * BIN for k in range(sig.n) if not ev["silent"][k]), sig.duration)
        s += 0.2 if sound_at <= 0.5 else 0.0
        if quiet_open:
            s -= 0.4
            notes.append("silent for the first second")
        parts["sound"] = float(np.clip(s, 0, 1))
    first_word = next((float(w["start"]) for w in sig.words if content_tokens(w["w"])), None)
    if sig.words:
        timing = float(np.clip(1.0 - max(0.0, (first_word if first_word is not None else 9.0) - 0.4) / 2.0, 0, 1))
        hooky = bool(wb["hookw"][:first].any() or wb["question"][:first].any() or wb["numbers"][:first].any())
        f = (content or {}).get("factors") or {}
        said = (0.6 * float(f.get("hook", 0.5)) + 0.4 * float(f.get("opening", 0.5))) if f else 0.5
        parts["words"] = float(np.clip(0.5 * said + 0.3 * timing + 0.2 * hooky, 0, 1))
        if first_word is not None and first_word > 1.5:
            notes.append(f"the first real word comes at {first_word:.1f} s")
    weights = {"picture": 0.35, "sound": 0.20, "words": 0.45}
    have = {k: v for k, v in parts.items() if v is not None}
    if not sig.words and "words" not in have:
        weights = {"picture": 0.6, "sound": 0.4, "words": 0.0}
    tot = sum(weights[k] for k in have) or 1.0
    value = sum(weights[k] * v for k, v in have.items()) / tot if have else 0.5
    return {"score": int(round(100 * value)), "value": round(value, 4),
            "parts": {k: (None if v is None else int(round(100 * v))) for k, v in parts.items()},
            "first_word_s": None if first_word is None else round(first_word, 2), "notes": notes}


# ------------------------------------------------------------------ the hold curve
def hold(sig: Signals, chans: dict, ev: dict, wb: dict, hook_value: float) -> dict:
    """A modelled audience, half a second at a time: the share still watching, the share at the end (hold rate),
    the average share of the clip watched, and where most leave."""
    n = sig.n
    e = _smooth(engagement(chans), 2.0)
    stay0 = STAY_MIN + STAY_SPAN * float(np.clip(hook_value, 0, 1))
    swipe_bins = max(1, min(n, int(SWIPE_SECONDS / BIN)))
    shares = np.array([0.4, 0.3, 0.2, 0.1][:swipe_bins])
    shares = shares / shares.sum()
    # open question: from the first question in the first 40% until the last payoff line (or 80% of the clip)
    open_from = next((k for k in range(int(0.4 * n) + 1) if k < n and wb["question"][k] > 0), None)
    close_at = max((k for k in range(n) if wb["payoff"][k] > 0), default=int(0.8 * n))
    since, last_new = np.zeros(n), -1
    for k in range(n):
        if ev["new"][k]:
            last_new = k
        since[k] = (k - last_new) * BIN if last_new >= 0 else (k + 1) * BIN
    dead = ev["silent"] & (ev["still"] if sig.has_picture else np.ones(n, dtype=bool))
    if not sig.has_sound:
        dead = np.zeros(n, dtype=bool)
    blank_k = (np.nan_to_num(chans["vision"], nan=1.0) < 0.08) & ~ev["face"] if sig.has_picture \
        else np.zeros(n, dtype=bool)
    lengths = np.full(n, BIN)
    lengths[-1] = max(0.05, min(BIN, sig.duration - (n - 1) * BIN))
    hazard = np.zeros(n)
    why = [""] * n
    surv = np.ones(n + 1)
    for k in range(n):
        if k < swipe_bins:
            loss = (1.0 - stay0) * shares[k]
            why[k] = "the first 2 seconds"
            surv[k + 1] = surv[k] - loss  # a share of everyone who started
            hazard[k] = loss / max(1e-9, surv[k])
            continue
        low = LOW_HAZARD * max(0.0, 0.5 - float(e[k])) / 0.5
        bored = min(BORED_MAX, BORED_STEP * max(0.0, since[k] - BORED_AFTER))
        dd = DEAD_HAZARD if dead[k] else 0.0
        blank = BLANK_HAZARD if blank_k[k] else 0.0
        h = BASE_HAZARD + low + bored + dd + blank
        if open_from is not None and open_from <= k < close_at:
            h *= OPEN_LOOP_KEEP
        parts = {"dead air over a still picture": dd, f"nothing new for {since[k]:.0f} s": bored,
                 "little to see, hear or follow": low, "nothing to look at (no movement, no face)": blank}
        why[k] = max(parts, key=parts.get) if max(parts.values()) > 0.01 else ""
        hazard[k] = min(0.5, h * BIN * lengths[k] / BIN)
        surv[k + 1] = surv[k] * (1.0 - hazard[k])
    curve = surv[1:]
    hold_rate = float(curve[-1])
    avg = float(np.mean(np.concatenate([[1.0], curve]) if n < 2 else (surv[:-1] + surv[1:]) / 2))
    drops = []
    order = np.argsort(-hazard)
    taken: list[int] = []
    for k in order:
        if len(drops) >= 3:
            break
        k = int(k)
        rate = hazard[k] / BIN
        if k < swipe_bins:
            continue
        if rate < 0.035 or any(abs(k - j) * BIN < 3.0 for j in taken):
            continue
        taken.append(k)
        drops.append({"t": round(k * BIN, 1), "per_second": round(float(100 * rate), 1), "why": why[k]})
    drops.sort(key=lambda d: d["t"])
    seconds = max(1, int(math.ceil(sig.duration - 1e-9)))
    per_second = [round(float(np.interp(s, np.arange(n + 1) * BIN, surv)), 4) for s in range(seconds + 1)]
    return {"hold_rate": round(hold_rate, 4), "avg_view": round(avg, 4), "stay_after_swipe": round(stay0, 4),
            "curve": per_second, "drops": drops, "open_loop": open_from is not None,
            "hazard": hazard, "why": why}


# ------------------------------------------------------------------ peaks, memory and the viral score
def peak(sig: Signals, chans: dict) -> dict:
    """The clip's strongest moment: where engagement and memory peak together (Higgsfield calls it the peak hook)."""
    e = engagement(chans)
    score = _smooth(0.7 * e + 0.3 * chans["memory"], 1.5)
    k = int(np.argmax(score)) if len(score) else 0
    first = score[:int(HOOK_SECONDS / BIN)]
    return {"t": round(k * BIN, 1), "value": round(float(score[k]) if len(score) else 0.0, 3),
            "in_hook": k * BIN < HOOK_SECONDS,
            "hook_vs_peak": round(float(first.max()) / max(1e-6, float(score[k])), 3) if len(first) else 0.0}


def memorable(chans: dict, sig: Signals) -> dict:
    m = chans["memory"]
    moments: list[float] = []
    for k in np.argsort(-m):
        if m[k] < 0.5 or len(moments) >= 4:
            break
        t = float(k) * BIN
        if all(abs(t - x) >= 3.0 for x in moments):
            moments.append(t)
    top = float(np.mean(np.sort(m)[-max(1, len(m) // 5):])) if len(m) else 0.0
    value = float(np.clip(0.6 * top + 0.4 * min(1.0, len(moments) / 3.0), 0, 1))
    return {"value": round(value, 4), "moments": sorted(round(t, 1) for t in moments)}


def look(sig: Signals, chans: dict, ev: dict) -> float | None:
    """Something to look at (0-1): how much the picture gives the eye, and how little of it stands still. None
    before the picture is measured."""
    if not sig.has_picture:
        return None
    vision = float(np.mean(np.nan_to_num(chans["vision"], nan=0.0)))
    still = float(np.mean(ev["still"] & ~ev["face"]))
    return float(np.clip(0.6 * min(1.0, vision / 0.35) + 0.4 * (1.0 - still), 0.0, 1.0))


def viral_score(parts: dict[str, float | None], weights: dict[str, float] | None = None) -> tuple[int, dict]:
    """0-100 from the components (each 0-1); missing ones are left out and the weights renormalized."""
    w = {**WEIGHTS, **(weights or {})}
    have = {k: float(v) for k, v in parts.items() if v is not None and k in w}
    tot = sum(w[k] for k in have) or 1.0
    raw = sum(w[k] * v for k, v in have.items()) / tot
    score = 100.0 / (1.0 + math.exp(-(raw - 0.5) * 7.0))
    used = {k: round(w[k] / tot, 3) for k in have}
    return int(round(score)), {"raw": round(raw, 4), "weights": used}


# ------------------------------------------------------------------ the whole prediction
def watch_value(avg_view: float) -> float:
    """How much is watched, as a component: 30% of the clip on average counts 0, 75% or more counts 1."""
    return float(np.clip((avg_view - 0.30) / 0.45, 0.0, 1.0))


def predict(sig: Signals, content: dict | None = None, learned: dict | None = None) -> dict:
    """The prediction for one clip. `content`: the 11-factor analysis of its own words (virality.analyze), when
    there are words; `learned`: what learn.py learned from the owner's results (weights, hold calibration)."""
    wb = word_bins(sig)
    chans, ev = channels(sig, wb)
    hk = hook(sig, chans, ev, wb, content)
    hd = hold(sig, chans, ev, wb, hk["value"])
    pk = peak(sig, chans)
    mem = memorable(chans, sig)
    learned = learned or {}
    avg_view, hold_rate = hd["avg_view"], hd["hold_rate"]
    cal = learned.get("hold") or {}
    calibrated = None
    if cal.get("n"):
        k = float(cal.get("shrink", 0.0))
        fit = float(cal["slope"]) * avg_view + float(cal["intercept"])
        calibrated = float(np.clip(avg_view + k * (fit - avg_view), 0.02, 1.0))
    vp = float(content["viral_potential"]) / 100.0 if content and content.get("viral_potential") is not None \
        else None
    components = {"content": vp, "hook": hk["value"], "watch": watch_value(calibrated if calibrated is not None
                                                                          else avg_view),
                  "memory": mem["value"], "look": look(sig, chans, ev)}
    score, mix = viral_score(components, learned.get("weights"))
    out = {
        "model": MODEL_VERSION, "score": score, "band": band(score),
        "hook": {k: v for k, v in hk.items() if k != "value"}, "peak": pk,
        "hold": {"rate": int(round(100 * hold_rate)), "avg_view": int(round(100 * avg_view)),
                 **({"avg_view_calibrated": int(round(100 * calibrated)), "calibrated_on": int(cal["n"])}
                    if calibrated is not None else {}),
                 "stay_after_swipe": int(round(100 * hd["stay_after_swipe"])), "curve": hd["curve"],
                 "drops": hd["drops"], "open_loop": hd["open_loop"]},
        "channels": {k: _per_second(np.nan_to_num(v, nan=0.0), sig.duration) for k, v in chans.items()},
        "measured": {"picture": sig.has_picture, "sound": sig.has_sound, "words": bool(sig.words),
                     "speech": sig.meta.get("speech_source", "none")},
        "memory": mem,
        "components": {k: (None if v is None else int(round(100 * v))) for k, v in components.items()},
        "mix": mix, "duration": round(sig.duration, 2), "note": ESTIMATE_NOTE,
        **({"learned": {"weights_from": int(learned.get("n") or 0)}} if learned.get("weights") else {}),
    }
    out["reasons"] = reasons(out, sig, ev, content)
    out["_internal"] = {"hazard": hd["hazard"], "why": hd["why"], "ev": ev, "wb": wb}
    out["_content"] = content
    return out


def public(pred: dict) -> dict:
    """The prediction as stored and sent (no arrays)."""
    return {k: v for k, v in pred.items() if not k.startswith("_")}


# ------------------------------------------------------------------ reasons, in plain words
def reasons(pred: dict, sig: Signals, ev: dict, content: dict | None) -> list[dict]:
    """What helps and what hurts, each tied to a moment of the clip: [{"area", "good", "text", "t"?}]."""
    out: list[dict] = []

    def add(area: str, good: bool | None, text: str, t: float | None = None) -> None:
        out.append({"area": area, "good": good, "text": text, **({"t": round(t, 1)} if t is not None else {})})

    hk = pred["hook"]
    hs = hk["score"]
    add("Hook", hs >= 60, f"Hook {hs}/100: " + ("the first seconds give a reason to stay." if hs >= 60 else
                                               "; ".join(hk["notes"]) + "." if hk["notes"] else
                                               "the first seconds are weak, so many swipe away."), 0.0)
    pk = pred["peak"]
    if not pk["in_hook"] and pk["hook_vs_peak"] < 0.75:
        add("Hook", False, f"The strongest moment comes at {_fmt(pk['t'])}, after most viewers have decided. Open "
                           "closer to it, or show its line on screen at the start.", pk["t"])
    elif pk["in_hook"]:
        add("Hook", True, f"The strongest moment is in the first {HOOK_SECONDS:.0f} seconds ({_fmt(pk['t'])}).",
            pk["t"])
    h = pred["hold"]
    add("Hold", h["avg_view"] >= 55, f"About {h['avg_view']}% of the clip watched on average, {h['rate']}% to the "
                                     f"end (modelled audience).")
    for d in h["drops"][:2]:
        add("Hold", False, f"Viewers leave fastest around {_fmt(d['t'])}: {d['why']} (about {d['per_second']:.0f}% a "
                           "second).", d["t"])
    if h["open_loop"]:
        add("Hold", True, "Asks a question early and answers it later, which keeps people watching.")
    if sig.has_picture:
        cuts = float(np.sum(sig.cuts))
        per10 = cuts / max(1.0, sig.duration) * 10
        still = float(np.mean(ev["still"]))
        if still >= 0.5 and per10 < 0.5:
            add("Vision", False, f"The picture barely changes ({still:.0%} of the clip is still, {cuts:.0f} cuts).")
        elif per10 >= 1.0:
            add("Vision", True, f"The picture keeps changing ({per10:.1f} new shots per 10 s).")
        elif float(np.mean(sig.motion)) > 0.012:
            add("Vision", True, "The picture keeps moving.")
        faces = float(np.mean(ev["face"]))
        if faces >= 0.4:
            add("Vision", True, f"A face is on screen {faces:.0%} of the time.")
        text = np.nan_to_num(np.asarray(sig.text, dtype=float), nan=0.0)
        if sig.words and float(np.mean(text)) < 0.25:
            add("Language", False, "Little or no text on screen while people talk: many watch with the sound off.")
        elif float(np.mean(text)) >= 0.5:
            add("Language", True, "Text on screen most of the time (captions or titles).")
    else:
        add("Vision", None, "The picture is measured once the clip is rendered.")
    if sig.has_sound:
        lv = np.asarray(sig.level)
        heard = lv[lv > SILENT_DB]
        if len(heard) and float(np.median(heard)) < -32:
            add("Sound", False, f"Quiet: the sound sits around {float(np.median(heard)):.0f} dBFS; most shorts are "
                                "much louder.")
        silent_s = float(np.sum(ev["silent"])) * BIN
        if silent_s >= 1.5:
            first = int(np.argmax(ev["silent"]))
            add("Sound", False, f"{silent_s:.1f} s of silence.", first * BIN)
        if sig.reactions:
            add("Sound", True, f"{len(sig.reactions)} reaction{'s' if len(sig.reactions) > 1 else ''} in the sound "
                               "(a laugh, a shout or a crowd).", sig.reactions[0][0])
        if sig.monotone:
            add("Sound", False, "The voice stays flat (little change in pitch).")
    else:
        add("Sound", False, "No sound track.")
    mem = pred["memory"]
    if mem["moments"]:
        add("Memory", True, f"{len(mem['moments'])} moment{'s' if len(mem['moments']) > 1 else ''} likely to stick "
                            f"(first at {_fmt(mem['moments'][0])}).", mem["moments"][0])
    else:
        add("Memory", False, "No moment that clearly stands out to remember or share.")
    if content:
        st = content.get("structure") or {}
        if st.get("label") and st.get("label") != "No clear structure":
            add("Words", bool(st.get("complete")), f"Structure: {st['label']}.")
        for fl in (content.get("flags") or [])[:3]:
            if fl.get("severity") in ("warn", "block"):
                add("Words", False, f"{fl['label']}: {fl['detail']}.")
    elif not sig.words:
        add("Words", None, "No words were heard, so it is judged on its picture and sound.")
    return out
