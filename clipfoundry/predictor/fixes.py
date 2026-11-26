"""Fixes the Viral Predictor suggests, each tried on the clip's own measurements before it is offered.

Every fix is a change ClipForge can make (a trim, removing pauses, captions, the hook text, punch-ins, louder sound)
or, for a video ClipForge did not make, the same change as advice with its times. Before a fix is listed, the
predictor applies it to the measured signals (cutting the bins a trim removes, marking captions as on screen, and so
on) and predicts again, so each fix says how much it should help. Fixes that would not help, or that would cut a
clip into something that needs outside context or ends before its point, are not offered.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from . import content as content_mod
from . import model
from .signals import BIN, SILENT_DB, Signals

MAX_FIXES = 5
MIN_GAIN = 1.0          # points of the viral score a fix must add to be offered
MIN_VIEW_GAIN = 2.0     # ...or percentage points of average watched
MIN_RATE_GAIN = 3.0     # ...or percentage points of viewers who reach the end
MAX_HOOK_LOSS = 3.0     # never a fix that costs score, or more than this many points of hook
START_REACH = 8.0       # a new start is looked for in the first 8 seconds
MIN_LENGTH = 5.0        # no fix leaves a clip shorter than this many seconds (or the owner's shortest clip)
BLOCKING = {"weak_context", "misleading_cut", "weak_ending", "topic_change"}


def _fmt(t: float) -> str:
    return model._fmt(t)  # noqa: SLF001


# ------------------------------------------------------------------ changing the signals
def trimmed(sig: Signals, a: float, b: float) -> Signals:
    """The signals of [a, b) of the clip, in the trimmed clip's time."""
    k0 = max(0, int(round(a / BIN)))
    k1 = min(sig.n, max(k0 + 1, int(math.ceil(b / BIN - 1e-9))))
    out = copy.copy(sig)
    for name in ("speech", "motion", "cuts", "luma", "face", "text", "level", "onsets"):
        v = getattr(sig, name)
        if v is not None:
            setattr(out, name, np.asarray(v)[k0:k1].copy())
    out.n = k1 - k0
    out.duration = round(min(b, sig.duration) - a, 3)
    shift = k0 * BIN if abs(k0 * BIN - a) < BIN else a
    out.words = [{**w, "start": max(0.0, float(w["start"]) - a), "end": min(b, float(w["end"])) - a}
                 for w in sig.words if (float(w["start"]) + float(w["end"])) / 2 >= a
                 and (float(w["start"]) + float(w["end"])) / 2 < b]  # at least half of the word is kept
    out.emphasis = [t - shift for t in sig.emphasis if a <= t < b]
    out.reactions = [(max(0.0, x - shift), min(out.duration, y - shift)) for x, y in sig.reactions if y > a and x < b]
    if out.cuts is not None and len(out.cuts):
        out.cuts = out.cuts.copy()
        out.cuts[0] = 0  # the clip's first frame is not a cut
    out.meta = {**sig.meta}
    return out


def without_pauses(sig: Signals, keep: float = 0.25) -> tuple[Signals, float]:
    """The clip with its pauses taken out (stretches of at least a second with no words and no reaction), keeping
    `keep` seconds of each. Returns the signals and the seconds removed."""
    if not sig.words:
        return sig, 0.0
    ws = sorted(sig.words, key=lambda w: float(w["start"]))
    gaps = []
    for x, y in zip(ws, ws[1:]):
        a, b = float(x["end"]), float(y["start"])
        if b - a >= 1.0 and not any(r0 < b and r1 > a for r0, r1 in sig.reactions):
            gaps.append((a + keep, b - keep))
    if not gaps:
        return sig, 0.0
    drop = np.zeros(sig.n, dtype=bool)
    for a, b in gaps:
        k0, k1 = int(math.ceil(a / BIN)), int(b // BIN)
        drop[k0:max(k0, k1)] = True
    removed = float(drop.sum()) * BIN
    if removed < BIN:
        return sig, 0.0
    keepm = ~drop
    out = copy.copy(sig)
    for name in ("speech", "motion", "cuts", "luma", "face", "text", "level", "onsets"):
        v = getattr(sig, name)
        if v is not None:
            setattr(out, name, np.asarray(v)[keepm].copy())
    out.n = int(keepm.sum())
    out.duration = round(sig.duration - removed, 3)
    shift = np.concatenate([[0.0], np.cumsum(drop.astype(float) * BIN)])

    def moved(t: float) -> float:
        return float(t) - float(shift[min(sig.n, int(t // BIN))])

    out.words = [{**w, "start": moved(w["start"]), "end": moved(w["end"])} for w in sig.words]
    out.emphasis = [moved(t) for t in sig.emphasis]
    out.reactions = [(moved(a), moved(b)) for a, b in sig.reactions]
    return out, removed


def with_text(sig: Signals, until: float | None = None) -> Signals:
    """On-screen text where people speak (captions), or everywhere up to `until` seconds (the hook text)."""
    out = copy.copy(sig)
    text = np.nan_to_num(np.asarray(sig.text if sig.text is not None else np.zeros(sig.n), dtype=float), nan=0.0)
    if until is not None:
        text[:max(1, int(math.ceil(until / BIN)))] = 1.0
    else:
        text = np.maximum(text, (np.asarray(sig.speech) > 0.3).astype(float))
    out.text = text
    return out


def with_moves(sig: Signals) -> Signals:
    """A framing change every few seconds in still stretches while someone speaks (punch-ins)."""
    out = copy.copy(sig)
    motion = np.asarray(sig.motion, dtype=float).copy()
    cuts = np.asarray(sig.cuts, dtype=float).copy()
    since = 99.0
    for k in range(sig.n):
        since = 0.0 if cuts[k] else since + BIN
        if sig.speech[k] > 0.3 and since >= 3.0:
            cuts[k] = 1.0
            since = 0.0
        if sig.speech[k] > 0.3:
            motion[k] = max(motion[k], 0.006)
    out.motion, out.cuts = motion, cuts
    return out


def louder(sig: Signals, target: float = -18.0) -> Signals:
    out = copy.copy(sig)
    lv = np.asarray(sig.level, dtype=float)
    heard = lv[lv > SILENT_DB]
    if len(heard):
        out.level = np.where(lv > SILENT_DB, lv + (target - float(np.median(heard))), lv)
    return out


# ------------------------------------------------------------------ trying a fix
class Trial:
    """Predicts a changed clip the same way the clip itself was predicted."""

    def __init__(self, base: dict, settings: dict, learned: dict | None):
        self.base, self.settings, self.learned = base, settings, learned

    def run(self, sig: Signals, words_changed: bool) -> tuple[dict, dict | None]:
        con = content_mod.analyze(sig, self.settings) if words_changed else self.base.get("_content")
        return model.predict(sig, con, self.learned), con

    def gain(self, pred: dict) -> dict:
        return {"score": pred["score"] - self.base["score"],
                "avg_view": pred["hold"]["avg_view"] - self.base["hold"]["avg_view"],
                "rate": pred["hold"]["rate"] - self.base["hold"]["rate"],
                "hook": pred["hook"]["score"] - self.base["hook"]["score"]}


def _helps(g: dict) -> bool:
    """A fix is offered when it adds to the score, or keeps more viewers without costing score or hook."""
    if g["score"] < 0 or g.get("hook", 0) < -MAX_HOOK_LOSS:
        return False
    return g["score"] >= MIN_GAIN or g["avg_view"] >= MIN_VIEW_GAIN or g.get("rate", 0) >= MIN_RATE_GAIN


def _breaks(con: dict | None, before: dict | None) -> str:
    """A trim that makes the words worse in a way that matters: a block the clip did not have."""
    if not con:
        return ""
    had = {fl["id"] for fl in (before or {}).get("flags") or [] if fl["severity"] == "block"}
    for fl in con.get("flags") or []:
        if fl["severity"] == "block" and fl["id"] in BLOCKING and fl["id"] not in had:
            return f"{fl['label'].lower()} ({fl['detail']})"
    return ""


def _line_at(sig: Signals, t: float) -> str:
    from ..pipeline.text_utils import build_sentences

    for s in build_sentences([{"w": w["w"], "start": float(w["start"]), "end": float(w["end"])} for w in sig.words]):
        if s["start"] - 0.05 <= t <= s["end"] + 0.05:
            return s["text"]
    return ""


def _quote(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return "“" + (text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…") + "”"


def suggest(sig: Signals, pred: dict, settings: dict | None = None, learned: dict | None = None,
            edit: dict | None = None, to_source=None) -> list[dict]:
    """The fixes worth offering for this clip, most helpful first.

    `edit`: the clip's current edit settings (None for a video ClipForge did not make: fixes are then advice).
    `to_source(t)`: maps a time in the clip to the time in its recording, for trims (None: advice only)."""
    settings = settings or {}
    trial = Trial(pred, settings, learned)
    before = pred.get("_content")
    out: list[dict] = []
    shortest = max(MIN_LENGTH, min(float(settings.get("min_duration") or 0) * 0.75, sig.duration * 0.6))
    editable = edit is not None

    def offer(fid: str, label: str, why: str, p: dict, change: dict | None, at: float | None = None) -> None:
        g = trial.gain(p)
        if not _helps(g):
            return
        out.append({"id": fid, "label": label, "why": why, "at": None if at is None else round(at, 2),
                    "gain": {"score": int(round(g["score"])), "avg_view": int(round(g["avg_view"])),
                             "rate": int(round(g["rate"])), "hook": int(round(g["hook"]))},
                    "edit": change if editable and change else None,
                    "kind": "edit" if editable and change else "advice"})

    # 1. start later: on the first real word, or on a stronger line in the first seconds
    words = sorted(sig.words, key=lambda w: float(w["start"]))
    starts: list[tuple[float, str]] = []
    first = next((float(w["start"]) for w in words if str(w["w"]).strip()), None)
    if first is not None and first > 0.6:
        starts.append((max(0.0, first - 0.15), "the first word"))
    from ..pipeline.text_utils import build_sentences

    lines = build_sentences([{"w": w["w"], "start": float(w["start"]), "end": float(w["end"])} for w in words]) \
        if words else []
    for s in lines[1:4]:
        if 0.6 < float(s["start"]) <= START_REACH:
            starts.append((max(0.0, float(s["start"]) - 0.12), _quote(s["text"])))
    if not words and sig.has_picture:  # no words: skip a dark or silent opening
        k = 0
        while k < sig.n - 1 and (sig.luma[k] < 0.07 or (sig.level is not None and sig.level[k] < SILENT_DB)):
            k += 1
        if k * BIN >= 0.5:
            starts.append((k * BIN, "the first moment with picture and sound"))
    best = None
    for t, what in starts:
        if sig.duration - t < shortest:
            continue
        cut = trimmed(sig, t, sig.duration)
        p, con = trial.run(cut, True)
        broke = _breaks(con, before)
        if broke:
            continue
        g = trial.gain(p)
        if _helps(g) and (best is None or g["score"] > best[2]["score"]):
            best = (t, what, g, p)
    best_start = best[0] if best else None
    if best:
        t, what, _, p = best
        src = to_source(t) if to_source else None
        offer("start_later", f"Start at {_fmt(t)}", f"Open on {what} instead of {t:.1f} s of lead-in.", p,
              {"start": round(src, 3)} if src is not None else None, at=0.0)

    # 2. end earlier: right after the last word, or on the last payoff line
    ends: list[tuple[float, str]] = []
    if words:
        last = max(float(w["end"]) for w in words)
        tail = sig.duration - last
        reacting = any(b > last for _, b in sig.reactions)
        if tail > 1.2 and not reacting:
            ends.append((min(sig.duration, last + 0.45), "after the last word"))
        payoffs = [s for s in lines if model.count_phrases(s["text"].lower(), model.PAYOFF_PHRASES)]
        if payoffs and lines.index(payoffs[-1]) <= len(lines) - 2:
            nxt = lines[lines.index(payoffs[-1]) + 1]
            ends.append((min(sig.duration, float(payoffs[-1]["end"]) + 0.35, float(nxt["start"]) - 0.05),
                         "on its payoff line " + _quote(payoffs[-1]["text"])))
    best = None
    for t, what in ends:
        if t < shortest or t >= sig.duration - 0.3:
            continue
        cut = trimmed(sig, 0.0, t)
        p, con = trial.run(cut, True)
        if _breaks(con, before):
            continue
        g = trial.gain(p)
        if _helps(g) and (best is None or g["score"] > best[2]["score"]):
            best = (t, what, g, p)
    if best:
        t, what, _, p = best
        src = to_source(t) if to_source else None
        offer("end_earlier", f"End at {_fmt(t)}", f"Stop {what}: the last {sig.duration - t:.1f} s lose viewers.", p,
              {"end": round(src, 3)} if src is not None else None, at=t)

    # 3. remove pauses
    cut, removed = without_pauses(sig)
    if removed >= 1.0:
        p, _ = trial.run(cut, True)
        mode = (edit or {}).get("silence") or settings.get("silence") or "off"
        nxt = {"off": "light", "light": "aggressive"}.get(mode)
        offer("remove_pauses", "Remove pauses", f"Takes out about {removed:.1f} s of pauses between sentences.", p,
              {"silence": nxt} if nxt else None)

    # 4. captions / 5. hook text on screen
    if sig.has_picture and words:
        text = np.nan_to_num(np.asarray(sig.text, dtype=float), nan=0.0)
        talking = np.asarray(sig.speech) > 0.3
        shown = float(text[talking].mean()) if talking.any() else 1.0
        enabled = (edit or {}).get("captions_enabled", settings.get("captions_enabled", True))
        if shown < 0.25 and not (editable and enabled is not False):
            p, _ = trial.run(with_text(sig), False)
            offer("captions", "Add captions", f"Text is on screen only {shown:.0%} of the time people talk; most "
                                              "short videos are watched with the sound off at first.", p,
                  {"captions_enabled": True} if enabled is False else None)
        hk = pred["hook"]
        if hk["score"] < 65 and not float(np.nan_to_num(np.asarray(sig.text[:2], dtype=float), nan=0.0).max()):
            line = (edit or {}).get("hook") or (_line_at(sig, pred["peak"]["t"]) if pred["peak"]["t"] > 0 else "")
            line = line or (lines[0]["text"] if lines else "")
            p, _ = trial.run(with_text(sig, until=3.0), False)
            on = (edit or {}).get("hook_overlay", settings.get("hook_overlay", True))
            change = {"hook_overlay": True, **({"hook": line[:160]} if line and not (edit or {}).get("hook") else {})}
            offer("hook_text", "Put the hook on screen", "Show " + (_quote(line) if line else "the clip's best line")
                  + " in the first seconds so a viewer knows why to stay.", p,
                  change if not on or not (edit or {}).get("hook") else None, at=0.0)

    # 6. punch-ins on long still stretches while someone talks
    if sig.has_picture and words:
        still = (np.asarray(sig.motion) < 0.004) & (np.asarray(sig.cuts) == 0) & (np.asarray(sig.speech) > 0.3)
        run = longest = 0
        at = None
        for k, s in enumerate(still):
            run = run + 1 if s else 0
            if run > longest:
                longest, at = run, (k - run + 1) * BIN
        on = (edit or {}).get("auto_zoom", settings.get("auto_zoom", True))
        if longest * BIN >= 4.0 and not (editable and on):
            p, _ = trial.run(with_moves(sig), False)
            offer("punch_ins", "Add punch-ins", f"The picture stays still for {longest * BIN:.0f} s from {_fmt(at)} "
                                                "while someone talks; a framing change every few seconds keeps the "
                                                "eye.", p, {"auto_zoom": True} if not on else None, at=at)

    # 7. louder sound
    if sig.has_sound:
        lv = np.asarray(sig.level)
        heard = lv[lv > SILENT_DB]
        on = (edit or {}).get("normalize_audio", settings.get("normalize_audio", True))
        if len(heard) and float(np.median(heard)) < -28 and not (editable and on):
            p, _ = trial.run(louder(sig), False)
            offer("louder", "Make it louder", f"The sound sits around {float(np.median(heard)):.0f} dBFS; shorts "
                                              "play around -14 LUFS.", p, {"normalize_audio": True} if not on else None)

    # 8. the strongest moment comes too late (advice: only the owner knows if the clip can open there)
    pk = pred["peak"]
    opened = next((f for f in out if f["id"] == "start_later"), None)
    near = opened is not None and best_start is not None and 0 <= pk["t"] - best_start <= 4.0
    if not pk["in_hook"] and pk["hook_vs_peak"] < 0.75 and pk["t"] > START_REACH and words and not near:
        line = _line_at(sig, pk["t"])
        out.append({"id": "tease_peak", "label": f"Tease {_fmt(pk['t'])} at the start",
                    "why": "The strongest moment is at " + _fmt(pk["t"]) + (f" ({_quote(line)})" if line else "")
                           + ". Open with a second of it, or put its line on screen in the first seconds.",
                    "at": pk["t"], "gain": None, "edit": None, "kind": "advice"})
    out.sort(key=lambda f: (-(f["gain"] or {"score": -1})["score"], -(f["gain"] or {"avg_view": -1})["avg_view"]))
    return out[:MAX_FIXES]
