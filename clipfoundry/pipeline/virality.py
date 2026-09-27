"""Viral Potential: an estimate of how well a candidate clip should work as a short.

Eleven factors are measured from the clip's own transcript, word timings, Whisper word confidence and loudness.
They are combined into a 0-100 Viral Potential score and four sub-scores (Hook, Retention Potential, Context,
Engagement Potential). All of them are estimates for ranking candidates against each other, never a prediction of
views.

On top of the factors the analysis looks for the HOOK -> CONTEXT -> PAYOFF structure that works best in short-form
video, and flags what to avoid: slow openings, excessive setup, repetition, missing context, misleading cuts and weak
endings. Flags marked "block" keep a clip out of the results entirely (quality over quantity); "warn" flags lower
the score.
"""
from __future__ import annotations

import math
from collections import Counter

from .audio import Loudness
from .text_utils import (BACKREF_PHRASES, CONTRAST_WORDS, INTENSIFIERS, OPEN_LOOP_PHRASES, SETUP_PHRASES,
                         SLOW_OPEN_PHRASES, content_tokens, cosine, count_phrases, tf_vector, tokens)

FACTORS = ["hook", "opening", "curiosity", "emotion", "density", "payoff", "standalone", "pacing", "uniqueness",
           "clarity", "retention"]
FACTOR_LABELS = {
    "hook": "Hook strength", "opening": "Opening strength", "curiosity": "Curiosity", "emotion": "Emotional intensity",
    "density": "Information density", "payoff": "Story / payoff", "standalone": "Standalone context",
    "pacing": "Pacing", "uniqueness": "Uniqueness", "clarity": "Speaker clarity", "retention": "Retention potential",
}
APPEAL = {"hook": 0.28, "curiosity": 0.18, "emotion": 0.16, "payoff": 0.24, "retention": 0.14}
QUALITY = {"opening": 0.20, "density": 0.20, "standalone": 0.30, "pacing": 0.15, "uniqueness": 0.10, "clarity": 0.05}
WEIGHTS = {**APPEAL, **QUALITY}  # every factor counts; see finalize() for how the two groups combine
SUBSCORES = {"hook": "Hook Score", "retention": "Retention Potential", "context": "Context Score",
             "engagement": "Engagement Potential"}
PENALTY = {"warn": 0.045, "block": 0.10}
ESTIMATE_NOTE = "Estimates from the clip's transcript and audio, used to rank clips. Not a guarantee of views."

FILLERS = {"um", "uh", "erm", "hmm", "mm"}
NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty", "thirty", "fifty",
                "hundred", "thousand", "million", "billion", "percent", "half", "double", "twice"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _flag(fid: str, label: str, severity: str, detail: str) -> dict:
    return {"id": fid, "label": label, "severity": severity, "detail": detail}


def _repetition(tok_lists: list[list[str]]) -> tuple[float, bool]:
    """Share of repeated word trigrams, and whether two sentences say nearly the same thing."""
    seq = [t for toks in tok_lists for t in toks]
    grams = [tuple(seq[k:k + 3]) for k in range(len(seq) - 2)]
    rep = 1.0 - len(set(grams)) / len(grams) if len(grams) >= 6 else 0.0
    sets = [set(content_tokens(" ".join(toks))) for toks in tok_lists]
    dup = any(len(sets[a]) >= 2 and len(sets[b]) >= 2 and len(sets[a] & sets[b]) / len(sets[a] | sets[b]) >= 0.75
              for a in range(len(sets)) for b in range(a + 1, len(sets)))
    return rep, dup


def analyze(s0: int, s1: int, sentences: list[dict], feats: list[dict], words: list[dict], loud: Loudness,
            opts: dict) -> dict:
    """Measure one sentence range [s0, s1]. Returns factors (0-1), structure, flags and aggregate scores."""
    sents = sentences[s0:s1 + 1]
    fs = feats[s0:s1 + 1]
    f0, fj = fs[0], fs[-1]
    start, end = sents[0]["start"], sents[-1]["end"]
    dur = max(0.1, end - start)
    ws = [w for w in words if w["end"] > start and w["start"] < end]
    tok_lists = [tokens(s["text"]) for s in sents]
    all_toks = [t for toks in tok_lists for t in toks]
    n_words = max(1, len(all_toks))
    nxt = feats[s1 + 1] if s1 + 1 < len(feats) else None
    ns = len(sents)

    # --- hook: the first line (plus the next when the first is very short) and the energy of the first 3 s
    hook = f0["opener"]
    if f0["dur"] < 2.5 and ns > 1:
        hook = min(1.0, hook + 0.5 * fs[1]["opener"])
    first_z, _ = loud.stats(start, min(end, start + 3.0))
    hook = _clamp(0.85 * hook + 0.15 * _sig(1.5 * first_z))

    # --- opening: how fast the clip gets to the point
    content_times = [w["start"] for w in ws if content_tokens(w["w"])]
    to_content = (content_times[0] - start) if content_times else dur
    lead_fillers = sum(1 for w in ws if w["start"] < start + 3.0 and tokens(w["w"])[:1] and
                       tokens(w["w"])[0] in FILLERS)
    opening = 0.75
    opening -= 0.35 * f0["slow_open"] + 0.25 * f0["dangling"] + 0.2 * f0["response"]
    opening -= min(0.3, 0.12 * lead_fillers) + min(0.3, 0.2 * max(0.0, to_content - 0.8))
    opening -= 0.2 if f0["n"] > 28 else 0.0
    opening -= 0.12 if ns > 1 and f0["gap_after"] > 1.2 else 0.0
    opening += 0.12 if 4 <= f0["n"] <= 16 and not f0["slow_open"] else 0.0  # short and punchy, not a greeting
    opening += 0.13 if (f0["question"] or f0["hookw"]) else 0.0
    opening = _clamp(opening)

    # --- curiosity: an open loop early that the clip closes later
    k_early = max(1, math.ceil(ns * 0.4))
    early_low = " ".join(s["text"] for s in sents[:k_early]).lower()
    early_q = any(f["question"] for f in fs[:k_early])
    open_loop = min(1.0, 0.5 * early_q + 0.35 * count_phrases(early_low, OPEN_LOOP_PHRASES))
    contrast = min(1.0, sum(1 for t in all_toks if t in CONTRAST_WORDS) / max(1.0, dur / 12.0))
    late = fs[max(k_early, ns - max(1, math.ceil(ns * 0.4))):] if ns > 1 else []
    closed = any(f["payoff"] for f in late) or (ns > 1 and fj["complete"] and not fj["question"])
    curiosity = _clamp(0.5 * open_loop + 0.2 * contrast + 0.25 * (open_loop > 0 and closed)
                       + 0.05 * any(f["you"] for f in fs))

    # --- emotional intensity: emotional words, intensifiers, vocal energy and dynamics
    emo = sum(f["emo"] for f in fs)
    intens = sum(1 for t in all_toks if t in INTENSIFIERS)
    excl = sum(s["text"].count("!") for s in sents)
    lex = min(1.0, (emo + 0.5 * intens + excl) / max(1.0, dur / 8.0) / 2.5)
    mean_z, std_z = loud.stats(start, end)
    emotion = _clamp(0.5 * lex + 0.25 * _sig(1.2 * mean_z) + 0.25 * min(1.0, std_z / 1.2))

    # --- information density: content words per word and per second, specifics, little filler or repetition
    content = sum(f["content"] for f in fs)
    specifics = sum(f["nums"] for f in fs) + sum(1 for t in all_toks if t in NUMBER_WORDS)
    filler_ratio = sum(f["filler"] for f in fs) / n_words
    rep, near_dup = _repetition(tok_lists)
    density = _clamp(0.45 * min(1.0, content / n_words / 0.45) + 0.4 * min(1.0, content / dur / 1.3)
                     + 0.15 * min(1.0, specifics / 2.0) - 3.0 * filler_ratio - 0.5 * rep)

    # --- story progression / payoff delivery
    end_hits = fj["payoff"] + (fs[-2]["payoff"] if ns > 1 else 0)
    story_first_half = sum(f["story"] for f, s in zip(fs, sents) if s["start"] - start < max(8.0, dur * 0.5))
    last_payoff = max((k for k, f in enumerate(fs) if f["payoff"]), default=-1)
    payoff = (0.35 * fj["complete"] + 0.25 * min(1.0, end_hits * 0.5)
              + 0.15 * (1.0 if story_first_half and (end_hits or fj["complete"]) else 0.0)
              + 0.25 * min(1.0, fj["gap_after"] / 0.8))
    payoff -= 0.1 if fj["question"] else 0.0
    after_payoff = ns - 1 - last_payoff if last_payoff >= 0 else 0
    # "The lesson is simple." usually introduces the conclusion, so one more sentence after a marker is fine
    payoff -= min(0.3, 0.12 * max(0, after_payoff - 1))
    payoff -= 0.25 if (fj["setup"] and ns > 1) else 0.0
    payoff += 0.1 if (nxt is None or nxt["transition"] or nxt["boundary"] > 1.0) else 0.0
    # "Exactly. And that's what he told me too." near the end: the clip drifts into a back-and-forth after its point
    late_reply = ns > 2 and any(f["response"] for f in fs[max(1, ns - max(2, ns // 3)):])
    payoff -= 0.2 if late_reply else 0.0
    payoff = _clamp(payoff)

    # --- standalone context: no dependence on what came before, no topic change inside
    low = " ".join(s["text"] for s in sents).lower()
    backrefs = count_phrases(low, BACKREF_PHRASES)
    max_gap = max((fs[k]["gap_before"] for k in range(1, ns)), default=0.0)
    internal_transition = any(f["transition"] for f in fs[1:])
    internal_boundary = max((f["boundary"] for f in fs[1:]), default=0.0)
    standalone = 1.0
    standalone -= 0.45 * f0["dangling"] + 0.25 * (f0["response"] and not f0["dangling"])
    standalone -= 0.20 * (f0["gap_before"] < 0.3) + 0.25 * (max_gap > 3.0) + 0.15 * (not fj["complete"])
    standalone -= 0.30 * internal_transition + 0.15 * max(0.0, min(1.0, internal_boundary - 1.0))
    standalone -= min(0.4, 0.2 * backrefs)
    standalone += 0.05 if (f0["boundary"] > 1.0 or f0["transition"]) else 0.0
    standalone = _clamp(standalone)

    # --- pacing: speaking rate, dead air, filler words, run-on sentences
    wps = n_words / dur
    rate_fit = 1.0 - min(1.0, abs(wps - 2.9) / 1.6)
    gaps = [ws[k + 1]["start"] - ws[k]["end"] for k in range(len(ws) - 1)]
    dead_air = sum(g - 0.5 for g in gaps if g > 0.7) / dur
    long_sents = sum(1 for f in fs if f["n"] > 35) / ns
    pacing = _clamp(0.45 * rate_fit + 0.35 * (1.0 - min(1.0, dead_air * 4.0))
                    + 0.2 * (1.0 - min(1.0, filler_ratio * 8.0)) - 0.1 * long_sents)

    # --- uniqueness (inside the clip; the pool comparison is added by `set_uniqueness`)
    internal_unique = _clamp(1.0 - min(1.0, rep * 3.0) - 0.3 * near_dup)

    # --- speaker clarity: Whisper word confidence, and how clearly speech stands out from the background
    probs = [w["p"] for w in ws if w.get("p") is not None]
    if probs and min(probs) >= 1.0:
        probs = []  # placeholder values from subtitles imported by older versions, not a measurement
    spread = loud.spread_db(start, end)
    snr = _clamp((spread - 8.0) / 20.0) if spread is not None else 0.6
    if len(probs) >= 5:
        mean_p = sum(probs) / len(probs)
        low_conf = sum(1 for p in probs if p < 0.4) / len(probs)
        clarity = _clamp(0.7 * _clamp((mean_p - 0.5) / 0.4 - low_conf) + 0.3 * snr)
    else:  # imported subtitles: no confidence values
        clarity = _clamp(0.45 + 0.35 * snr)

    # --- retention potential: hook, pacing, payoff, open loop and a length that suits short-form
    length_fit = (dur / 15.0 if dur < 15 else 1.0 if dur <= 45 else math.exp(-(((dur - 45.0) / 25.0) ** 2)))
    retention = _clamp(0.30 * hook + 0.20 * pacing + 0.20 * payoff + 0.15 * curiosity + 0.15 * length_fit
                       - min(0.2, dead_air))

    factors = {"hook": hook, "opening": opening, "curiosity": curiosity, "emotion": emotion, "density": density,
               "payoff": payoff, "standalone": standalone, "pacing": pacing, "uniqueness": internal_unique,
               "clarity": clarity, "retention": retention}

    # --- structure: HOOK -> CONTEXT -> PAYOFF
    has_hook = hook >= 0.45 or f0["question"] or f0["hookw"] >= 2 or opening >= 0.8
    middle = fs[1:-1]
    has_context = (ns >= 3 and sum(f["content"] for f in middle) >= 4 and not internal_transition
                   and standalone >= 0.5)
    has_payoff = ns > 1 and fj["complete"] and not fj["question"] and not fj["setup"] and (
        end_hits > 0 or payoff >= 0.55)
    parts = [p for p, ok in (("Hook", has_hook), ("Context", has_context), ("Payoff", has_payoff)) if ok]
    structure = {"hook": bool(has_hook), "context": bool(has_context), "payoff": bool(has_payoff),
                 "complete": bool(has_hook and has_context and has_payoff),
                 "label": " → ".join(parts) if parts else "No clear structure",
                 "missing": [p for p in ("Hook", "Context", "Payoff") if p not in parts]}

    # --- what to avoid
    flags: list[dict] = []
    if f0["slow_open"] or opening < 0.4 or to_content > 2.0:
        why = ("starts with a warm-up line" if f0["slow_open"] else
               f"{to_content:.1f} s before the first real word" if to_content > 2.0 else "weak first line")
        flags.append(_flag("slow_opening", "Slow opening", "warn", why))
    first_strong = next((k for k, f in enumerate(fs) if f["opener"] >= 0.5 or f["payoff"]), ns - 1)
    preamble = sents[first_strong]["start"] - start
    setups = sum(count_phrases(s["text"].lower(), SETUP_PHRASES + SLOW_OPEN_PHRASES) for s in sents[:k_early])
    if (hook < 0.4 and preamble > max(10.0, 0.45 * dur)) or setups >= 3:
        flags.append(_flag("excessive_setup", "Excessive setup", "warn",
                           f"{preamble:.0f} s of setup before anything lands" if preamble > 5 else
                           "several setup lines before the point"))
    if rep > 0.18 or near_dup:
        flags.append(_flag("repetitive", "Repetitive", "warn",
                           "says nearly the same thing twice" if near_dup else f"{rep:.0%} repeated phrases"))
    if standalone < 0.5:
        why = ("starts in the middle of a thought" if f0["dangling"] else
               "starts as a reply to something outside the clip" if f0["response"] else
               "refers back to earlier parts of the video" if backrefs else
               "changes topic inside the clip" if internal_transition else "needs context from the full video")
        flags.append(_flag("weak_context", "Needs outside context", "block" if standalone < 0.35 else "warn", why))
    continues = nxt is not None and not nxt["transition"] and nxt["boundary"] < 1.0 and fj["gap_after"] < 1.2
    if continues and (fj["question"] or fj["setup"]):
        flags.append(_flag("misleading_cut", "Misleading cut", "block",
                           "ends on a question or setup whose answer comes right after the cut"))
    elif continues and (nxt["payoff"] or fj["n"] <= 5):
        # a short last line ("It's not." / "The lesson is simple.") leads into the next one, which is cut off
        flags.append(_flag("misleading_cut", "Misleading cut", "warn" if end_hits and not nxt["payoff"] else "block",
                           "stops right before the point is made"))
    if internal_transition:
        flags.append(_flag("topic_change", "Topic change inside", "block",
                           "moves on to a different topic partway through"))
    if not fj["complete"]:
        flags.append(_flag("weak_ending", "Weak ending", "block", "ends mid-sentence"))
    elif after_payoff >= 3 or late_reply or fj["transition"] or payoff < 0.35:
        why = ("keeps talking after the payoff" if after_payoff >= 3 else
               "drifts into a back-and-forth after the point" if late_reply else
               "ends on a transition to another topic" if fj["transition"] else "ends without a clear payoff")
        flags.append(_flag("weak_ending", "Weak ending", "warn", why))

    result = {"s0": s0, "s1": s1, "start": start, "end": end, "dur": dur, "factors": factors,
              "structure": structure, "flags": flags,
              "signals": {"wps": round(wps, 2), "dead_air": round(dead_air, 3), "to_content_s": round(to_content, 2),
                          "repetition": round(rep, 3), "mean_confidence": round(sum(probs) / len(probs), 3)
                          if probs else None, "internal_uniqueness": round(internal_unique, 3)},
              "tf": tf_vector(low)}
    return finalize(result)


def set_uniqueness(results: list[dict]) -> None:
    """Blend in how different each clip is from the other candidates of the same video."""
    for i, r in enumerate(results):
        others = [cosine(r["tf"], o["tf"]) for j, o in enumerate(results) if j != i and o.get("tf")]
        pool_sim = max(others, default=0.0)
        r["factors"]["uniqueness"] = _clamp(0.6 * r["signals"]["internal_uniqueness"] + 0.4 * (1.0 - pool_sim))
        r["signals"]["pool_similarity"] = round(pool_sim, 3)
        finalize(r)


def finalize(r: dict) -> dict:
    """(Re)compute the weighted Viral Potential and the four sub-scores from the factors and flags.

    Appeal factors (hook, curiosity, emotion, payoff, retention) decide how interesting a clip is; quality factors
    (opening, density, standalone, pacing, uniqueness, clarity) decide how much of that appeal survives. A clean
    but dull clip therefore stays average instead of scoring high on tidiness alone.
    """
    f = r["factors"]
    appeal = sum(APPEAL[k] * f[k] for k in APPEAL)
    quality = sum(QUALITY[k] * f[k] for k in QUALITY)
    raw = appeal * (0.5 + 0.5 * quality)
    st = r.get("structure") or {}
    raw += 0.06 if st.get("complete") else 0.02 if sum(bool(st.get(k)) for k in ("hook", "context", "payoff")) == 2 \
        else 0.0
    raw -= sum(PENALTY[fl["severity"]] for fl in r.get("flags", []))
    r["raw"] = raw
    r["viral_potential"] = round(100.0 / (1.0 + math.exp(-(raw - 0.45) * 7.5)), 1)
    r["subscores"] = {
        "hook": round(100 * (0.5 * f["hook"] + 0.3 * f["opening"] + 0.2 * f["curiosity"])),
        "retention": round(100 * f["retention"]),
        "context": round(100 * (0.6 * f["standalone"] + 0.25 * f["density"] + 0.15 * f["clarity"])),
        "engagement": round(100 * (0.35 * f["emotion"] + 0.25 * f["curiosity"] + 0.2 * f["uniqueness"]
                                   + 0.2 * f["hook"])),
    }
    r["blocked"] = any(fl["severity"] == "block" for fl in r.get("flags", []))
    return r


def blend_ai(r: dict, ai_factors: dict, weight: float = 0.6) -> dict:
    """Mix an AI provider's 0-10 factor scores into the measured ones (only the factors it returned)."""
    for k, v in ai_factors.items():
        if k in r["factors"]:
            r["factors"][k] = _clamp(weight * v / 10.0 + (1.0 - weight) * r["factors"][k])
    return finalize(r)


def no_speech(cand: dict) -> dict:
    """Candidates found from loudness alone (no transcript): only the audio energy is known."""
    e = float(cand["criteria"].get("engagement", 0.5))
    factors = {k: 0.5 for k in FACTORS}
    factors.update({"emotion": e, "hook": 0.3 + 0.4 * e, "retention": 0.3 + 0.4 * e, "clarity": 0.5})
    r = {"s0": -1, "s1": -1, "start": cand["start"], "end": cand["end"], "dur": cand["dur"], "factors": factors,
         "structure": {"hook": False, "context": False, "payoff": False, "complete": False,
                       "label": "No speech (scored on audio energy)", "missing": []},
         "flags": [], "signals": {"internal_uniqueness": 1.0}, "tf": Counter()}
    finalize(r)
    r["viral_potential"] = round(35 + 40 * e, 1)
    return r


def variants(s0: int, s1: int, sentences: list[dict], opts: dict, feats: list[dict] | None = None
             ) -> list[tuple[int, int]]:
    """Nearby sentence ranges worth comparing: start one line earlier (a hook just before the cut) or up to three
    lines later (skip a warm-up), end up to four lines earlier (stop at the payoff) or two lines later (include the
    answer)."""
    n = len(sentences)
    min_d, max_d = float(opts["min_duration"]), float(opts["max_duration"])
    total = sentences[-1]["end"] - sentences[0]["start"] if sentences else 0.0
    if total < min_d:
        min_d = max(5.0, 0.5 * total)
    hard_min = max(5.0, 0.75 * min_d)
    out = [(s0, s1)]
    for a in range(max(0, s0 - 1), min(s0 + 4, s1 + 1)):
        if a == s0 - 1 and feats is not None and (feats[a]["dangling"] or feats[a]["opener"] < 0.5):
            continue  # only reach back for a real hook line
        for b in range(max(a, s1 - 4), min(n, s1 + 3)):
            if (a, b) == (s0, s1):
                continue
            dur = sentences[b]["end"] - sentences[a]["start"]
            if hard_min <= dur <= max_d:
                out.append((a, b))
    return out


def summary(r: dict) -> dict:
    """What is stored with a clip (0-10 factors, 0-100 sub-scores)."""
    return {
        "factors": {k: round(10 * r["factors"][k], 1) for k in FACTORS},
        "subscores": r["subscores"],
        "structure": r["structure"],
        "flags": r["flags"],
        "signals": {k: v for k, v in r.get("signals", {}).items() if k != "internal_uniqueness"},
        "viral_potential": r["viral_potential"],
        "note": ESTIMATE_NOTE,
    }
