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

from ..brain import steer
from .audio import Loudness
from .text_utils import (BACKREF_PHRASES, CAUSAL_PHRASES, CAUSAL_WORDS, CONTRAST_WORDS, EPISODIC_PHRASES,
                         INTENSIFIERS, ONE_THING, OPEN_LOOP_PHRASES, OUTRO_PHRASES, RECAP_PHRASES, SETUP_PHRASES,
                         SLOW_OPEN_PHRASES, content_tokens, cosine, count_phrases, repeat_run, tf_vector, tokens)

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
# Length. A clip that runs under the shortest length the owner set loses a little (never a hard cut: a tight,
# complete moment may still win). And when the same moment can be cut short or with its build-up and ending
# (`grown`), each second short of the ideal length costs the short version a little, so the fuller one wins unless
# it is clearly weaker. Both are small on purpose: length never beats a better moment.
SHORT_PENALTY = 0.10
SHORT_OF_IDEAL = 0.0025     # per second, about half a point mid-scale
GROW_LINES = (6, 8)         # how many lines a moment may grow back and forward
ESTIMATE_NOTE = "Estimates from the clip's transcript and audio, used to rank clips. Not a guarantee of views."

FILLERS = {"um", "uh", "erm", "hmm", "mm"}
NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty", "thirty", "fifty",
                "hundred", "thousand", "million", "billion", "percent", "half", "double", "twice"}


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _potential(raw: float) -> float:
    return round(100.0 / (1.0 + math.exp(-(raw - 0.45) * 7.5)), 1)


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


REACTION_Z = 1.0          # louder than the stream's speech by this many standard deviations ...
REACTION_MIN = 0.4        # ... for at least this long, with nobody speaking: laughter, a shout, a crowd
REACTION_AFTER = 3.0      # a reaction this soon after the cut belongs to the clip (reactions often come late)
REACTION_KEEP = 3.0       # the cut keeps at most this much of it (a long stretch of music is not a reaction)
HEARD_REACTIONS = ("laughter", "applause", "cheering", "screaming", "gasp", "boom", "crash")  # listen.py kinds


def wordless_loud(words: list[dict], loud: Loudness, t0: float, t1: float) -> list[tuple[float, float]]:
    """Reactions without words in [t0, t1): (start, end) in seconds, the same ones deep.audio_features counts.

    When ClipForge AI listened to the video (listen.py; the Heard rides on `loud.heard`), these are the stretches
    where it heard laughter, applause, cheering, screaming, a gasp, an explosion or a crash and nobody speaks: a
    song, an engine or a door no longer passes for a reaction. Without it, loud stretches without words (an
    estimate from loudness alone)."""
    heard = getattr(loud, "heard", None)
    if heard is not None:
        return heard.reaction_runs(max(0.0, t0), t1, words, kinds=HEARD_REACTIONS)
    a, b = loud._idx(max(0.0, t0)), loud._idx(t1)  # noqa: SLF001
    if b - a < 2:
        return []
    base = a * loud.hop   # the time of frame a: every index below counts from it
    hot = loud.z[a:b] > REACTION_Z
    for w in words:
        if w["end"] > base and w["start"] < t1:
            hot[max(0, int((w["start"] - base) / loud.hop)):max(0, int((w["end"] - base) / loud.hop) + 1)] = False
    out, run = [], None
    for k, h in enumerate(list(hot) + [False]):
        if h and run is None:
            run = k
        elif not h and run is not None:
            if (k - run) * loud.hop >= REACTION_MIN:
                out.append((round(base + run * loud.hop, 2), round(base + k * loud.hop, 2)))
            run = None
    return out


def reaction_after(sentences: list[dict], j: int, loud: Loudness) -> tuple[float, float] | None:
    """The loud moment without words (laughter, a shout, a crowd) that starts within REACTION_AFTER seconds after
    sentence j and before anyone speaks again: reactions often come a second or two late, and they belong to the
    moment. Its end is capped at REACTION_KEEP seconds after it starts. None when there is none."""
    last = sentences[j]["end"]
    nxt = sentences[j + 1]["start"] if j + 1 < len(sentences) else last + REACTION_AFTER + REACTION_KEEP
    runs = [r for r in wordless_loud([], loud, last, nxt) if r[0] - last <= REACTION_AFTER]
    return (runs[0][0], min(runs[0][1], round(runs[0][0] + REACTION_KEEP, 2))) if runs else None


REACTION_BEFORE = 0.6      # a reaction that ends this close before the first word: the clip opens on its tail


def reaction_before(sentences: list[dict], i: int, loud: Loudness) -> tuple[float, float] | None:
    """The loud moment without words that ends just before sentence i starts (within REACTION_BEFORE seconds): a
    clip that starts there opens on a reaction whose cause came before the clip. None when there is none."""
    first = sentences[i]["start"]
    prev = sentences[i - 1]["end"] if i > 0 else 0.0
    runs = [r for r in wordless_loud([], loud, max(prev, first - REACTION_AFTER - REACTION_KEEP), first)
            if first - r[1] <= REACTION_BEFORE]
    return runs[-1] if runs else None


def _goodbye(text: str) -> bool:
    """An outro line that says goodbye ("thanks for watching", "see you tomorrow"), not only a recap."""
    low = text.lower()
    return count_phrases(low, OUTRO_PHRASES) > count_phrases(low, RECAP_PHRASES)


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
    open_loop = min(1.0, 0.5 * early_q + 0.35 * (count_phrases(early_low, OPEN_LOOP_PHRASES)
                                                 + bool(ONE_THING.search(early_low))))
    contrast = min(1.0, sum(1 for t in all_toks if t in CONTRAST_WORDS) / max(1.0, dur / 12.0))
    late = fs[max(k_early, ns - max(1, math.ceil(ns * 0.4))):] if ns > 1 else []
    closed = any(f["payoff"] for f in late) or (ns > 1 and fj["complete"] and not fj["question"])
    # the causal engine (retention guide): beats joined by "but" / "therefore" keep the viewer guessing; a chain of
    # "and then... and then" lets them see where it goes and leave
    whole_low = " ".join(s["text"] for s in sents).lower()
    pivots = sum(1 for t in all_toks if t in CAUSAL_WORDS) + sum(whole_low.count(ph) for ph in CAUSAL_PHRASES)
    episodic = sum(whole_low.count(ph) for ph in EPISODIC_PHRASES)
    and_then_chain = episodic >= 2 and pivots == 0
    curiosity = _clamp(0.5 * open_loop + 0.2 * contrast + 0.25 * (open_loop > 0 and closed)
                       + 0.05 * any(f["you"] for f in fs) + 0.06 * min(1.0, pivots / max(1.0, dur / 15.0))
                       - 0.10 * and_then_chain)

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
    # "To recap..." / "Thanks for watching": the video announces its end instead of stopping on the payoff
    outro = bool(fj["outro"] or (ns > 1 and fs[-2]["outro"]))
    # "Thanks for the follow", "let me read chat" in the last lines: the clip runs on after its point
    chores_end = bool(fj.get("chores") or (ns > 1 and fs[-2].get("chores")))
    payoff -= 0.2 if chores_end else 0.0
    # a laugh, a shout or a crowd right after the last word: the moment lands, and the cut keeps it
    # (deep.optimize_bounds, candidates.refine_bounds end after it)
    late = reaction_after(sentences, s1, loud)
    payoff += 0.08 if late else 0.0
    # ...and a clip that opens on one starts after whatever caused it
    opens_on = reaction_before(sentences, s0, loud)
    # "Consistency matters. Be consistent. Consistency is key.": the clip ends by circling one point
    repeats_end = repeat_run([s["text"] for s in sents]) if ns >= 4 else 0
    payoff -= 0.25 if repeats_end else 0.0
    payoff -= 0.2 if outro else 0.0
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
    # "People in town thought he was crazy" as the first line: who is "he"? The viewer met him earlier in the video.
    # the first "he" or "she" said before the clip says who anyone is (the first line, or a later one)
    who = ""
    for k, s_ in enumerate(sents):
        if k == 0 and f0["dangling"]:
            break          # counted above as a start in the middle of a thought
        who = fs[k].get("who") or ""
        if who or fs[k].get("names"):
            break
    standalone -= 0.3 if who else 0.0
    # ...and when the line just before the clip says who it is, the clip has cut off its own introduction
    who_cut = bool(who) and any(feats[k].get("names") for k in range(max(0, s0 - 3), s0)
                                if not any(feats[j]["transition"] or feats[j]["gap_before"] > 3.0
                                           for j in range(k + 1, s0 + 1)))
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

    # --- retention potential: hook, pacing, payoff, open loop and a length that suits short-form. The length is
    # read against the owner's own range: full marks from the shortest clip up to the middle of ideal and longest
    # (never less than 45 s), fading beyond.
    min_d = float(opts.get("min_duration") or 15.0)
    max_d = float(opts.get("max_duration") or 60.0)
    target_d = min(max_d, max(min_d, float(opts.get("target_duration") or 30.0)))
    spoken = sentences[-1]["end"] - sentences[0]["start"]
    if spoken < min_d:
        min_d = max(5.0, 0.5 * spoken)  # a video shorter than the shortest clip: as in `variants`
    full_to = max(45.0, 0.5 * (target_d + max_d))
    length_fit = (dur / min_d if dur < min_d else 1.0 if dur <= full_to
                  else math.exp(-(((dur - full_to) / 25.0) ** 2)))
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
    has_payoff = ns > 1 and fj["complete"] and not fj["question"] and not fj["setup"] and not outro and (
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
    first_strong = next((k for k, f in enumerate(fs) if f["opener"] >= 0.5 or f["payoff"]), None)
    if first_strong is None and payoff >= 0.55:
        # Plain talk has no marked line ("here's why", "the lesson is") to measure the setup against. When the clip
        # still ends on a finished point, a long build-up is the story, not setup: the weak first line is already
        # counted in the hook, and docking every longer clip of plain talk made clips short.
        preamble = 0.0
    else:
        preamble = sents[first_strong if first_strong is not None else ns - 1]["start"] - start
    setups = sum(count_phrases(s["text"].lower(), SETUP_PHRASES + SLOW_OPEN_PHRASES) for s in sents[:k_early])
    if (hook < 0.4 and preamble > max(10.0, 0.45 * dur)) or setups >= 3:
        flags.append(_flag("excessive_setup", "Excessive setup", "warn",
                           f"{preamble:.0f} s of setup before anything lands" if preamble > 5 else
                           "several setup lines before the point"))
    if rep > 0.18 or near_dup:
        flags.append(_flag("repetitive", "Repetitive", "warn",
                           "says nearly the same thing twice" if near_dup else f"{rep:.0%} repeated phrases"))
    if standalone < 0.5 or who:
        why = ("starts in the middle of a thought" if f0["dangling"] else
               "starts as a reply to something outside the clip" if f0["response"] else
               f"says “{who}” before saying who that is" if who else
               "refers back to earlier parts of the video" if backrefs else
               "changes topic inside the clip" if internal_transition else "needs context from the full video")
        flags.append(_flag("weak_context", "Needs outside context",
                           "block" if standalone < 0.35 or who_cut else "warn",
                           why + ("; the line just before the clip says who" if who_cut else "")))
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
    elif after_payoff >= 3 or late_reply or fj["transition"] or payoff < 0.35 or repeats_end:
        why = (f"ends by saying the same thing {repeats_end} times" if repeats_end else
               "keeps talking after the payoff" if after_payoff >= 3 else
               "drifts into a back-and-forth after the point" if late_reply else
               "ends on a transition to another topic" if fj["transition"] else "ends without a clear payoff")
        flags.append(_flag("weak_ending", "Weak ending", "warn", why))
    goodbyes = 0  # lines at the end that say goodbye or talk to chat (a recap sums the point up: not a goodbye)
    while goodbyes < ns and (fs[ns - 1 - goodbyes].get("chores") or _goodbye(sents[ns - 1 - goodbyes]["text"])):
        goodbyes += 1
    if opens_on:
        flags.append(_flag("starts_on_reaction", "Starts on a reaction", "warn",
                           "opens right after a loud moment without words (laughter, a shout, a crowd); what caused it "
                           "happened before the clip, so start earlier"))
    if outro:
        flags.append(_flag("outro", "Ends with an outro", "block" if goodbyes >= 2 else "warn",
                           "announces the end (\"to recap\", \"thanks for watching\") instead of stopping on the "
                           "point"))
    ads = sum(1 for f in fs if f.get("ad"))
    if ads:
        # two ad lines, or one in a short clip, make it an ad read: nobody shares a sponsor message as a clip
        flags.append(_flag("ad_read", "Ad or sponsor read",
                           "block" if ads >= 2 or ads / ns >= 0.25 else "warn",
                           f"{ads} line{'s' if ads > 1 else ''} of an ad or sponsor read (“use code”, “brought to "
                           "you by”)"))
    chores = sum(1 for f in fs if f.get("chores"))
    if chores:
        flags.append(_flag("chat_chores", "Talks to chat", "block" if chores >= 3 else "warn",
                           f"{chores} line{'s' if chores > 1 else ''} thanking followers or reading chat, which "
                           "mean nothing to someone watching the short"))

    if and_then_chain:
        flags.append(_flag("and_then", "\"And then\" chain", "warn",
                           "events strung together with \"and then\"; no turn (\"but\", \"which meant\") to keep "
                           "the viewer guessing"))

    # --- the owner's Brain: kinds of moment and subjects it looks for or passes over (brain/steer.py)
    st = opts.get("brain_steer") or {}
    facts = {"emotion": emotion, "density": density, "hook": hook, "curiosity": curiosity, "question_early": early_q,
             "story": sum(f["story"] for f in fs), "complete": structure["complete"],
             "promo": sum(f["promo"] for f in fs), "outro": outro, "slow_open": bool(f0["slow_open"]),
             "numbers": specifics, "text": low,
             "short_lines": sum(1 for f in fs if 2 <= f["n"] <= 8 and f["complete"]
                                and (f["hookw"] or f["emo"] or f["you"]))}
    said = steer.judge(st, low, facts) if (st.get("kinds") or st.get("topics")) else None
    if said and said.get("avoid"):
        flags.append(_flag("brain_avoid", "Your Brain says to pass this over", "warn",
                           f"{said['avoid']['label']}: “{said['avoid']['by'].get('text', '')[:120]}”"))
    priorities = list(dict.fromkeys(list(opts.get("brain_priorities") or []) + list(st.get("priorities") or [])))

    result = {"s0": s0, "s1": s1, "start": start, "end": end, "dur": dur, "factors": factors,
              "structure": structure, "flags": flags, "brain_priorities": priorities, "brain_steer": said,
              "short_by": round(max(0.0, 1.0 - dur / min_d), 4), "facts": facts,
              "signals": {"wps": round(wps, 2), "dead_air": round(dead_air, 3), "to_content_s": round(to_content, 2),
                          "reaction_after": list(late) if late else None,
                          "outro": outro, "causal_pivots": pivots, "episodic": episodic,
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
    priorities = set(r.get("brain_priorities") or [])

    def weighted(weights: dict) -> float:
        adjusted = {key: value * (1.25 if key in priorities else 1.0) for key, value in weights.items()}
        return sum(adjusted[key] * f[key] for key in adjusted) / sum(adjusted.values())

    appeal, quality = weighted(APPEAL), weighted(QUALITY)
    raw = appeal * (0.5 + 0.5 * quality)
    st = r.get("structure") or {}
    raw += 0.06 if st.get("complete") else 0.02 if sum(bool(st.get(k)) for k in ("hook", "context", "payoff")) == 2 \
        else 0.0
    raw -= sum(PENALTY[fl["severity"]] for fl in r.get("flags", []))
    raw -= SHORT_PENALTY * float(r.get("short_by") or 0.0)
    said = r.get("brain_steer")
    if said:  # kept on the result, so a later recount (uniqueness, an AI's factors) keeps what the Brain said
        said["points"] = round(_potential(raw + said["adjust"]) - _potential(raw), 1)
        raw += said["adjust"]
    r["raw"] = raw
    r["viral_potential"] = _potential(raw)
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
    """Candidates without a transcript: scored on the audio energy, or on what ClipForge AI saw and heard when it
    watched and listened (candidates.fallback_windows puts that into "engagement")."""
    e = float(cand["criteria"].get("engagement", 0.5))
    factors = {k: 0.5 for k in FACTORS}
    factors.update({"emotion": e, "hook": 0.3 + 0.4 * e, "retention": 0.3 + 0.4 * e, "clarity": 0.5})
    sensed = "seen_and_heard" in (cand.get("signals") or {})
    r = {"s0": -1, "s1": -1, "start": cand["start"], "end": cand["end"], "dur": cand["dur"], "factors": factors,
         "structure": {"hook": False, "context": False, "payoff": False, "complete": False,
                       "label": "No speech (scored on what ClipForge AI saw and heard)" if sensed else
                       "No speech (scored on audio energy)", "missing": []},
         "flags": [], "signals": {"internal_uniqueness": 1.0,
                                  **{k: cand["signals"][k] for k in ("seen_and_heard", "talk")
                                     if k in (cand.get("signals") or {})}}, "tf": Counter()}
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


def _topic_words(text: str) -> set[str]:
    return {t[:5] for t in content_tokens(text) if len(t) >= 3}


def grown(s0: int, s1: int, sentences: list[dict], opts: dict, feats: list[dict]) -> list[tuple[int, int]]:
    """Fuller versions of a moment: the same lines with more of what leads up to them and what follows, for a clip
    that would otherwise be only the strongest lines of a longer story. Never across a change of topic or a long
    pause, never longer than the longest clip, and not far past the ideal length.

    A line is taken in only while it is about the same thing (it shares a word with what the clip already holds, or
    sits between two lines that do). One line that does not is still taken when it is where the story plainly
    starts (a strong first line) or ends (a payoff line), and nothing beyond it."""
    n = len(sentences)
    max_d = float(opts["max_duration"])
    reach = min(max_d, 1.3 * float(opts.get("target_duration") or max_d))

    def new_start(k: int) -> bool:  # sentence k begins something else
        return bool(feats[k]["transition"] or feats[k]["boundary"] > 1.0 or feats[k]["gap_before"] > 3.0)

    held = set()
    for k in range(s0, s1 + 1):
        held |= _topic_words(sentences[k]["text"])

    def walk(first: int, step: int, most: int, edge) -> list[int]:
        """The lines taken going back (step -1) or forward (step 1) from `first`."""
        got, seen, good, off, k = [first], set(held), 0, 0, first + step
        while 0 <= k < n and len(got) <= most and not new_start(k if step > 0 else k + 1):
            words = _topic_words(sentences[k]["text"])
            if words & seen:
                seen |= words
                got.append(k)
                good, off = len(got) - 1, 0
            elif feats[k]["n"] <= 3:     # a word or two in passing ("Eleven.") is carried along
                got.append(k)
            elif not off:                # one line off the subject, kept only if the next ones are back on it
                off = 1
                got.append(k)
            else:
                break
            k += step
        tail = got[good + 1:]
        got = got[:good + 1]
        if tail and edge(tail[0]):       # where the story plainly starts, or ends
            got.append(tail[0])
        return got

    starts = walk(s0, -1, GROW_LINES[0], lambda k: feats[k]["opener"] >= 0.5 and not feats[k]["dangling"])
    ends = walk(s1, 1, GROW_LINES[1], lambda k: bool(feats[k]["payoff"]))
    out = []
    for a in starts:
        for b in ends:
            if (a, b) != (s0, s1) and sentences[b]["end"] - sentences[a]["start"] <= reach:
                out.append((a, b))
    return out


def short_of_ideal(r: dict, opts: dict) -> float:
    """What a version of a moment loses for each second it is short of the ideal length (see SHORT_OF_IDEAL)."""
    return SHORT_OF_IDEAL * max(0.0, float(opts.get("target_duration") or 0.0) - float(r["dur"]))


def summary(r: dict) -> dict:
    """What is stored with a clip (0-10 factors, 0-100 sub-scores)."""
    return {
        "factors": {k: round(10 * r["factors"][k], 1) for k in FACTORS},
        "subscores": r["subscores"],
        "structure": r["structure"],
        "flags": r["flags"],
        "signals": {k: v for k, v in r.get("signals", {}).items() if k != "internal_uniqueness"},
        "viral_potential": r["viral_potential"],
        **({"brain": {k: r["brain_steer"].get(k) for k in ("points", "why", "used", "avoid")}}
           if r.get("brain_steer") else {}),
        # the kinds of moment the clip shows ("reaction", "story"): what its results are later compared by
        **({"moment": steer.shown_kinds(r["facts"]["text"], r["facts"])} if r.get("facts") else {}),
        "note": ESTIMATE_NOTE,
    }


REASON_AREAS = ("Opening", "Context", "Pacing", "Payoff", "Audio", "Framing")


def reasons(summary_: dict, render_info: dict | None = None) -> list[dict]:
    """Why this clip ranks where it does, in plain words tied to the clip itself: one line each for its opening,
    context, pacing, payoff, how clearly the speech comes through and (once rendered) its framing.
    [{"area", "good": True/False/None (None: no measurement), "text"}]. Works on a stored analysis (`summary`), so
    older clips get reasons too."""
    f = summary_.get("factors") or {}
    sig = summary_.get("signals") or {}
    st = summary_.get("structure") or {}
    flags = {fl.get("id"): fl for fl in summary_.get("flags") or []}
    out: list[dict] = []

    def add(area: str, good: bool | None, text: str) -> None:
        out.append({"area": area, "good": good, "text": text})

    if not f:
        return out
    lead = sig.get("to_content_s")
    if "slow_opening" in flags:
        add("Opening", False, f"Slow start: {flags['slow_opening'].get('detail', '')}.")
    elif lead is not None:
        add("Opening", float(f.get("opening", 0)) >= 6, f"First real word after {float(lead):.1f} s"
            + ("; the first line gets to the point." if float(f.get("opening", 0)) >= 6 else "."))
    if "ad_read" in flags:
        add("Context", False, f"Has an ad in it: {flags['ad_read'].get('detail', '')}.")
    elif "chat_chores" in flags:
        add("Context", False, f"Talks to chat: {flags['chat_chores'].get('detail', '')}.")
    elif "weak_context" in flags:
        add("Context", False, f"Needs outside context: {flags['weak_context'].get('detail', '')}.")
    elif "starts_on_reaction" in flags:
        add("Context", False, "Starts right after a reaction (a laugh or a shout); what caused it is before the clip.")
    elif "topic_change" in flags:
        add("Context", False, "Changes topic partway through.")
    else:
        add("Context", float(f.get("standalone", 0)) >= 5,
            "Makes sense on its own: no lines lean on earlier parts of the video."
            if float(f.get("standalone", 0)) >= 5 else "Some lines may lean on earlier parts of the video.")
    wps, dead = sig.get("wps"), sig.get("dead_air")
    if wps is not None:
        per10 = 10 * float(dead or 0)
        good = float(f.get("pacing", 0)) >= 6
        add("Pacing", good, f"{float(wps):.1f} words a second, {per10:.1f} s of dead air per 10 s"
            + ("." if good else "; slower than most shorts hold attention."))
    if "misleading_cut" in flags:
        add("Payoff", False, f"Cut too early: {flags['misleading_cut'].get('detail', '')}.")
    elif "weak_ending" in flags:
        add("Payoff", False, f"Weak ending: {flags['weak_ending'].get('detail', '')}.")
    elif sig.get("reaction_after"):
        add("Payoff", True, "Ends on a reaction (a laugh, a shout or a crowd without words), kept in the cut.")
    elif st.get("payoff"):
        add("Payoff", True, "Ends on its payoff line, so the viewer gets what the opening promised.")
    else:
        add("Payoff", None, "No clear payoff line found (a reaction or a visual moment may still carry it).")
    conf = sig.get("mean_confidence")
    if conf is not None:
        c = float(conf)
        add("Audio", c >= 0.8, f"Speech recognized with {c:.0%} confidence"
            + (": clear enough to follow without sound." if c >= 0.8 else ": parts may be hard to hear or caption."))
    else:
        add("Audio", None, "No word confidence for this transcript (imported subtitles).")
    ri = render_info or {}
    mode = ri.get("mode")
    if mode == "split" and ri.get("layout") == "pip":
        add("Framing", True, "Picture-in-picture: the gameplay fills the frame with the face cam in a box on top.")
    elif mode == "split" and ri.get("layout") == "game":
        add("Framing", True, "Gameplay only: the gameplay fills the frame and the face cam is left out.")
    elif mode == "split":
        add("Framing", True, "Split view: the face cam and the gameplay both stay in the 9:16 frame.")
    elif mode in ("face", "speaker"):
        add("Framing", True, "The vertical frame follows the speaker's face.")
    elif ri.get("layout") == "fit" or (ri.get("crop_w") is not None and float(ri.get("crop_w") or 0) >= 0.999):
        add("Framing", True, "The whole picture is kept (no crop).")
    elif mode == "manual":
        add("Framing", True, "Framed by you.")
    elif mode:
        add("Framing", False, "No face or subject was tracked, so the picture is cropped in the middle.")
    else:
        add("Framing", None, "Framing is checked when the clip is rendered.")
    return out
