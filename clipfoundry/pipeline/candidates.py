"""Stage 1: fast local clip discovery over the full transcript + loudness.

Every window that starts and ends on a sentence boundary and fits the
duration range is scored with cheap features (running aggregates, O(1) per
window).  The best windows are then de-duplicated so the pool handed to the
Stage 2 evaluator covers different moments and topics.
"""
from __future__ import annotations

import math
from collections import Counter

from .audio import Loudness
import numpy as np

from .text_utils import (DANGLING_STARTS, EMOTION_WORDS, HOOK_PHRASES, HOOK_WORDS, PAYOFF_PHRASES, PROMO_PHRASES,
                         RESPONSE_STARTS, SETUP_PHRASES, SLOW_OPEN_PHRASES, STORY_MARKERS, TRANSITION_PHRASES,
                         content_tokens, cosine, count_phrases, ends_sentence, tf_vector, tokens)

FILLER_TOKENS = {"um", "uh", "erm", "hmm", "mm"}


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def sentence_features(sentences: list[dict], words: list[dict]) -> list[dict]:
    feats = []
    for k, s in enumerate(sentences):
        text = s["text"]
        low = text.lower()
        toks = tokens(text)
        lead = [t for t in toks[:4] if t not in FILLER_TOKENS]
        first = lead[0] if lead else ""
        hookw = sum(1 for t in toks if t in HOOK_WORDS) + 2 * count_phrases(low, HOOK_PHRASES)
        f = {
            "n": s["n"],
            "dur": max(0.1, s["end"] - s["start"]),
            "dangling": first in DANGLING_STARTS,
            "question": text.rstrip().endswith("?"),
            "complete": ends_sentence(words[s["i1"]]["w"]),
            "hookw": hookw,
            "emo": sum(1 for t in toks if t in EMOTION_WORDS),
            "you": sum(1 for t in toks if t in ("you", "your", "you're", "yourself")),
            "nums": sum(1 for t in toks if t.isdigit()),
            "payoff": count_phrases(low, PAYOFF_PHRASES),
            "story": count_phrases(low, STORY_MARKERS),
            "filler": sum(1 for t in toks if t in FILLER_TOKENS),
            "content": len(content_tokens(text)),
            "gap_before": s["start"] - sentences[k - 1]["end"] if k else s["start"],
            "gap_after": sentences[k + 1]["start"] - s["end"] if k + 1 < len(sentences) else 5.0,
            "transition": count_phrases(low, TRANSITION_PHRASES) > 0,
            "setup": text.rstrip().endswith("?") or count_phrases(low, SETUP_PHRASES) > 0,
            "promo": count_phrases(low, PROMO_PHRASES),
            "slow_open": count_phrases(low[:60], SLOW_OPEN_PHRASES) > 0,  # "so today I want to talk about..."
            "response": first in RESPONSE_STARTS,  # "Exactly." / "No, ..." answers someone outside the clip
        }
        h = 0.30 * f["question"] + 0.12 * min(hookw, 3) + 0.10 * (f["you"] > 0) + 0.10 * (f["nums"] > 0)
        h += 0.06 * min(f["emo"], 2)
        h += 0.12 if 4 <= f["n"] <= 18 else (-0.05 if f["n"] > 18 else 0.0)
        h -= 0.35 * f["dangling"] + 0.10 * min(f["filler"], 2) + 0.30 * f["slow_open"] + 0.25 * f["response"]
        f["opener"] = max(0.0, min(1.0, h + 0.15))
        feats.append(f)
    for f, depth in zip(feats, topic_boundaries(sentences)):
        f["boundary"] = depth
    return feats


def topic_boundaries(sentences: list[dict], block: int = 3) -> list[float]:
    """TextTiling-style topic shift strength before each sentence (z-scored)."""
    n = len(sentences)
    if n < 4:
        return [0.0] * n
    tfs = [tf_vector(s["text"]) for s in sentences]
    gaps = np.zeros(n)
    for k in range(1, n):
        left: Counter = Counter()
        right: Counter = Counter()
        for t in tfs[max(0, k - block):k]:
            left.update(t)
        for t in tfs[k:k + block]:
            right.update(t)
        gaps[k] = 1.0 - cosine(left, right)
    body = gaps[1:]
    std = float(body.std()) or 1.0
    z = (gaps - float(body.mean())) / std
    z[0] = 0.0
    return z.tolist()


def _window_scores(sentences, feats, i, j, agg, loud: Loudness, opts) -> dict:
    s_i, s_j = sentences[i], sentences[j]
    start, end = s_i["start"], s_j["end"]
    dur = max(0.1, end - start)
    fi, fj = feats[i], feats[j]

    # Hook: opening sentence (plus the next one when the first is very short).
    hook = fi["opener"]
    if fi["dur"] < 2.5 and i + 1 <= j:
        hook = min(1.0, hook + 0.5 * feats[i + 1]["opener"])
    first_z, _ = loud.stats(start, min(end, start + 3.0))
    hook = min(1.0, 0.85 * hook + 0.15 * _sig(1.5 * first_z))

    # Engagement: vocal energy, dynamics, emotional/lexical intensity, pacing.
    mean_z, std_z = loud.stats(start, end)
    energy = _sig(1.2 * mean_z)
    dyn = min(1.0, std_z / 1.2)
    wps = agg["n"] / dur
    rate = 1.0 - min(1.0, abs(wps - 2.9) / 1.6)
    lex = min(1.0, (agg["emo"] + 0.5 * agg["hookw"] + agg["questions"]) / max(1.0, dur / 10.0) / 3.0)
    engagement = 0.35 * energy + 0.15 * dyn + 0.25 * lex + 0.25 * rate
    engagement -= min(0.4, 0.2 * agg["promo"])

    # Payoff / story structure: finishes a thought, lands on a conclusion.
    end_hits = fj["payoff"] + (feats[j - 1]["payoff"] if j - 1 >= i else 0)
    story_arc = 1.0 if agg["story_first_half"] and (end_hits or fj["complete"]) else 0.0
    payoff = (0.35 * fj["complete"] + 0.25 * min(1.0, end_hits * 0.5) + 0.15 * story_arc
              + 0.25 * min(1.0, fj["gap_after"] / 0.8))
    if fj["question"]:
        payoff -= 0.1
    if agg["last_payoff"] >= 0 and agg["last_payoff"] < j:
        payoff -= min(0.3, 0.12 * (j - agg["last_payoff"]))  # keeps talking after the punchline
    if fj["setup"] and j > i:
        payoff -= 0.25  # ends on a line that sets up something else
    nxt = feats[j + 1] if j + 1 < len(feats) else None
    if nxt is None or nxt["transition"] or nxt["boundary"] > 1.0:
        payoff += 0.1  # the next sentence starts something new: natural end

    # Standalone: does not lean on earlier context, no dead air inside.
    standalone = 1.0
    standalone -= 0.45 * fi["dangling"] + 0.25 * (fi["response"] and not fi["dangling"])
    standalone -= 0.20 * (fi["gap_before"] < 0.3)
    standalone -= 0.25 * (agg["max_gap"] > 3.0)
    standalone -= 0.15 * (not fj["complete"])
    standalone -= 0.30 * bool(agg["internal_transition"])
    standalone -= 0.15 * max(0.0, min(1.0, agg["internal_boundary"] - 1.0))
    if fi["boundary"] > 1.0 or fi["transition"]:
        standalone += 0.05
    standalone = max(0.0, min(1.0, standalone))

    span = max(1.0, 0.6 * (opts["max_duration"] - opts["min_duration"]))
    length = math.exp(-(((dur - opts["target_duration"]) / span) ** 2))
    # soft minimum: a tight, complete moment may run a little short of min_duration
    short_pen = 0.35 * max(0.0, 1.0 - dur / opts["min_duration"])
    density = min(1.0, (agg["content"] / max(1, agg["n"])) / 0.45)

    score = (0.30 * hook + 0.22 * engagement + 0.20 * payoff + 0.18 * standalone
             + 0.05 * length + 0.05 * density) - short_pen
    return {
        "start": start, "end": end, "s0": i, "s1": j, "dur": dur, "stage1": score,
        "criteria": {"hook": hook, "engagement": engagement, "payoff": max(0.0, payoff),
                     "standalone": standalone, "density": density, "length": length},
        "signals": {"question_open": fi["question"], "hook_words": fi["hookw"], "energy_z": round(mean_z, 2),
                    "wps": round(wps, 2), "complete_end": fj["complete"], "story": bool(agg["story_first_half"]),
                    "payoff_markers": end_hits, "dangling_start": fi["dangling"]},
    }


def _overlap(a: dict, b: dict) -> float:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    return max(0.0, inter) / max(0.1, min(a["dur"], b["dur"]))


def find_candidates(words: list[dict], sentences: list[dict], loud: Loudness, opts: dict,
                    pool_size: int = 12, max_overlap: float = 0.15) -> list[dict]:
    """The best distinct windows. A broad pool for staged analysis allows partly overlapping windows
    (`max_overlap` > 0.15); the final selection removes overlaps."""
    if not sentences:
        return []
    feats = sentence_features(sentences, words)
    min_d, max_d = opts["min_duration"], opts["max_duration"]
    total_speech = sentences[-1]["end"] - sentences[0]["start"]
    if total_speech < min_d:
        min_d = max(5.0, 0.5 * total_speech)
    local = {**opts, "min_duration": min_d}
    hard_min = max(5.0, 0.75 * min_d)

    windows: list[dict] = []
    for i in range(len(sentences)):
        agg = {"n": 0, "content": 0, "emo": 0, "hookw": 0, "questions": 0, "max_gap": 0.0,
               "story_first_half": 0, "last_payoff": -1, "internal_transition": 0, "internal_boundary": 0.0,
               "promo": 0}
        start = sentences[i]["start"]
        for j in range(i, len(sentences)):
            f = feats[j]
            dur = sentences[j]["end"] - start
            if dur > max_d:
                break
            agg["n"] += f["n"]
            agg["content"] += f["content"]
            agg["emo"] += f["emo"]
            agg["hookw"] += f["hookw"]
            agg["questions"] += f["question"]
            agg["promo"] += f["promo"]
            if f["payoff"]:
                agg["last_payoff"] = j
            if j > i:
                agg["max_gap"] = max(agg["max_gap"], f["gap_before"])
                agg["internal_transition"] += f["transition"]
                agg["internal_boundary"] = max(agg["internal_boundary"], f["boundary"])
            if sentences[j]["start"] - start < max(8.0, dur * 0.5):
                agg["story_first_half"] += f["story"]
            if dur >= hard_min:
                windows.append(_window_scores(sentences, feats, i, j, agg, loud, local))

    if not windows:  # very short input: take everything as one window
        agg = {"n": sum(f["n"] for f in feats), "content": sum(f["content"] for f in feats),
               "emo": sum(f["emo"] for f in feats), "hookw": sum(f["hookw"] for f in feats),
               "questions": sum(f["question"] for f in feats), "max_gap": 0.0, "story_first_half": 0,
               "last_payoff": -1, "internal_transition": 0, "internal_boundary": 0.0,
               "promo": sum(f["promo"] for f in feats)}
        windows.append(_window_scores(sentences, feats, 0, len(sentences) - 1, agg, loud, local))

    # Topic relevance for the strongest windows only (bag-of-words cosine vs the whole video). The shortlist is
    # spread over the video (a window almost identical to a stronger one is skipped), so long videos are not
    # represented by a few regions only.
    windows.sort(key=lambda w: w["stage1"], reverse=True)
    top: list[dict] = []
    near: dict[int, list[dict]] = {}  # kept windows by 10-second bucket of their start
    reach = int(max_d // 10) + 1
    for w in windows:
        if len(top) >= 600:
            break
        b = int(w["start"] // 10)
        if any(_overlap(w, t) > 0.85 for k in range(b - reach, b + reach + 1) for t in near.get(k, ())):
            continue
        top.append(w)
        near.setdefault(b, []).append(w)
    global_tf = Counter()
    for s in sentences:
        global_tf.update(content_tokens(s["text"]))
    global_top = Counter(dict(global_tf.most_common(40)))
    for w in top:
        text = " ".join(sentences[k]["text"] for k in range(w["s0"], w["s1"] + 1))
        w["text"] = text
        w["tf"] = tf_vector(text)
        w["criteria"]["relevance"] = cosine(w["tf"], global_top)
    max_rel = max((w["criteria"]["relevance"] for w in top), default=0.0) or 1.0
    for w in top:
        rel = w["criteria"]["relevance"] / max_rel
        w["criteria"]["context"] = 0.6 * rel + 0.4 * w["criteria"]["density"]
        w["stage1"] = 0.92 * w["stage1"] + 0.08 * w["criteria"]["context"]
    top.sort(key=lambda w: w["stage1"], reverse=True)

    picked: list[dict] = []
    for w in top:
        if len(picked) >= pool_size:
            break
        if any(_overlap(w, p) > max_overlap for p in picked):
            continue
        if any(cosine(w["tf"], p["tf"]) > max(0.8, max_overlap + 0.3) for p in picked):
            continue
        picked.append(w)
    for w in picked:
        w.pop("tf", None)
    return picked


def refine_bounds(cand: dict, sentences: list[dict], video_duration: float) -> tuple[float, float]:
    """Pad cut points into the surrounding pauses so words are never clipped."""
    i, j = cand["s0"], cand["s1"]
    start, end = sentences[i]["start"], sentences[j]["end"]
    prev_end = sentences[i - 1]["end"] if i > 0 else 0.0
    next_start = sentences[j + 1]["start"] if j + 1 < len(sentences) else video_duration
    start -= min(0.3, max(0.0, (start - prev_end) * 0.5))
    end += min(0.5, max(0.05, (next_start - end) * 0.6))
    return max(0.0, round(start, 3)), min(video_duration, round(end, 3))


def fallback_windows(loud: Loudness, duration: float, opts: dict, pool_size: int) -> list[dict]:
    """No speech found: pick the most energetic, non-overlapping stretches."""
    length = min(opts["target_duration"], max(5.0, duration))
    step = max(2.0, length / 2)
    wins = []
    t = 0.0
    while t + length <= duration + 0.01:
        mean_z, std_z = loud.stats(t, t + length)
        e = _sig(1.2 * mean_z)
        wins.append({"start": t, "end": t + length, "dur": length, "s0": -1, "s1": -1, "text": "",
                     "stage1": 0.3 + 0.3 * e,
                     "criteria": {"hook": 0.3, "engagement": e, "payoff": 0.3, "standalone": 0.5,
                                  "context": 0.3, "density": 0.0, "length": 1.0},
                     "signals": {"energy_z": round(mean_z, 2)}})
        t += step
    wins.sort(key=lambda w: w["stage1"], reverse=True)
    picked: list[dict] = []
    for w in wins:
        if len(picked) >= pool_size:
            break
        if all(_overlap(w, p) <= 0.15 for p in picked):
            picked.append(w)
    return picked
