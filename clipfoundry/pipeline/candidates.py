"""Stage 1: fast local clip discovery over the full transcript + loudness.

Every window that starts and ends on a sentence boundary and fits the
duration range is scored with cheap features (running aggregates, O(1) per
window).  The best windows are then de-duplicated so the pool handed to the
Stage 2 evaluator covers different moments and topics.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .audio import Loudness
import numpy as np

from .text_utils import (AD_PHRASES, CHAT_CHORES, DANGLING_STARTS, EMOTION_WORDS, GENERIC_WORDS, HOOK_PHRASES,
                         HOOK_WORDS, LOSS_PHRASES, LOSS_WORDS, ONE_THING, OUTRO_PHRASES, PAYOFF_PHRASES, PERSON_NOUNS,
                         PERSON_PRONOUNS, PROMO_PHRASES, RESPONSE_STARTS, SETUP_PHRASES, SLOW_OPEN_PHRASES,
                         STOPWORDS, STORY_MARKERS, TRANSITION_OPENERS, TRANSITION_PHRASES, content_tokens, cosine,
                         count_phrases, count_words, ends_sentence, tf_vector, tokens)

FILLER_TOKENS = {"um", "uh", "erm", "hmm", "mm"}


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# "the third one", "two of them", "the other guy": counted people the line points at
COUNTED_PEOPLE = re.compile(r"\b(?:first|second|third|fourth|fifth|last|other|another|one|two|three|four|five)\s+"
                            r"(?:one|ones|guy|guys|of them|of us)\b")


EXCLAIMS = re.compile(r"(?:no|yes|yeah)[\s,.!]+(?:way|no|yes|yeah)\b")


def proper_names(sentences: list[dict]) -> set[str]:
    """Words the transcript capitalizes in the middle of a sentence (names: "Sarah", "Northwind"), lowercased."""
    out = set()
    for s in sentences:
        for w in s["text"].split()[1:]:
            bare = w.strip(".,!?;:\"'")
            if bare[:1].isupper() and bare.lower() not in ("i", "i'm", "i've", "i'd", "i'll"):
                out.add(bare.lower())
    return out


def names_someone(text: str, proper: set[str] | frozenset[str] = frozenset()) -> bool:
    """Whether a line introduces a person: a word like "grandfather" or "boss", "the third one", or a name (a word
    capitalized after the first; the first word only when the transcript capitalizes it elsewhere too, since every
    sentence starts with a capital)."""
    if any(t in PERSON_NOUNS for t in tokens(text)) or COUNTED_PEOPLE.search(text.lower()):
        return True
    for j, w in enumerate(text.split()):
        bare = w.strip(".,!?;:\"'")
        if bare[:1].isupper() and bare.lower() not in ("i", "i'm", "i've", "i'd", "i'll") \
                and (j > 0 or bare.lower() in proper):
            return True
    return False


def unnamed_person(text: str, proper: set[str] | frozenset[str] = frozenset()) -> str:
    """The "he" or "she" a line uses before it names anyone ("People in town thought he was crazy"): as the first
    line of a clip it leaves the viewer asking who. "" when the line names someone first or has no such word."""
    for m in re.finditer(r"[A-Za-z']+", text):
        if m.group(0).lower() in PERSON_PRONOUNS:
            return "" if names_someone(text[:m.start()], proper) else m.group(0).lower()
    return ""


def sentence_features(sentences: list[dict], words: list[dict]) -> list[dict]:
    feats = []
    proper = proper_names(sentences)
    for k, s in enumerate(sentences):
        text = s["text"]
        low = text.lower()
        toks = tokens(text)
        lead = [t for t in toks[:4] if t not in FILLER_TOKENS]
        first = lead[0] if lead else ""
        hookw = sum(1 for t in toks if t in HOOK_WORDS) + 2 * count_phrases(low, HOOK_PHRASES) \
            + 2 * bool(ONE_THING.search(low))
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
            "transition": count_phrases(low, TRANSITION_PHRASES) > 0 or bool(TRANSITION_OPENERS.match(low)),
            # a question, "here's why", or "says one thing": a line that promises what comes next
            "setup": text.rstrip().endswith("?") or count_phrases(low, SETUP_PHRASES) > 0
            or bool(ONE_THING.search(low)),
            "promo": count_phrases(low, PROMO_PHRASES) + count_words(low, AD_PHRASES),
            "ad": count_words(low, AD_PHRASES) > 0,        # "use code SHOW at checkout": an ad read
            "chores": count_words(low, CHAT_CHORES) > 0,   # "thanks for the follow", "let me read chat"
            "who": unnamed_person(text, proper),     # "he" before the line says who (virality: standalone)
            "names": names_someone(text, proper),
            "slow_open": count_phrases(low[:60], SLOW_OPEN_PHRASES) > 0,  # "so today I want to talk about..."
            # "Exactly." / "No, ..." answers someone outside the clip; "No way!", "Yes, yes!" is a reaction
            "response": first in RESPONSE_STARTS and not EXCLAIMS.match(low),
            "outro": count_phrases(low, OUTRO_PHRASES) > 0,  # "to recap", "thanks for watching": the video is ending
            # "stop doing this", "the mistake that costs you": a loss or a warning hooks better than a promise
            "loss": sum(1 for t in toks if t in LOSS_WORDS) + count_phrases(low, LOSS_PHRASES),
        }
        h = 0.30 * f["question"] + 0.12 * min(hookw, 3) + 0.10 * (f["you"] > 0) + 0.10 * (f["nums"] > 0)
        h += 0.06 * min(f["emo"], 2) + 0.06 * min(f["loss"], 2)
        h += 0.06 if f["story"] and not f["dangling"] else 0.0  # in the middle of the action beats an introduction
        h += 0.12 if 4 <= f["n"] <= 18 else (-0.05 if f["n"] > 18 else 0.0)
        h -= 0.35 * f["dangling"] + 0.10 * min(f["filler"], 2) + 0.30 * f["slow_open"] + 0.25 * f["response"]
        h -= 0.30 * f["outro"] + 0.30 * f["ad"] + 0.25 * f["chores"]
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


def window(sentences: list[dict], feats: list[dict], i: int, j: int, loud: Loudness, opts: dict,
           global_top: Counter | None = None) -> dict:
    """One sentence range [i, j] scored exactly like find_candidates scores its windows, for moments named by other
    means (ClipForge AI's scout, a person). `global_top` (the video's commonest content words) adds the relevance
    term the shortlist gets; without it, density stands in."""
    agg = {"n": 0, "content": 0, "emo": 0, "hookw": 0, "questions": 0, "max_gap": 0.0,
           "story_first_half": 0, "last_payoff": -1, "internal_transition": 0, "internal_boundary": 0.0, "promo": 0}
    start = sentences[i]["start"]
    for k in range(i, j + 1):
        f = feats[k]
        dur = sentences[k]["end"] - start
        agg["n"] += f["n"]
        agg["content"] += f["content"]
        agg["emo"] += f["emo"]
        agg["hookw"] += f["hookw"]
        agg["questions"] += f["question"]
        agg["promo"] += f["promo"]
        if f["payoff"]:
            agg["last_payoff"] = k
        if k > i:
            agg["max_gap"] = max(agg["max_gap"], f["gap_before"])
            agg["internal_transition"] += f["transition"]
            agg["internal_boundary"] = max(agg["internal_boundary"], f["boundary"])
        if sentences[k]["start"] - start < max(8.0, dur * 0.5):
            agg["story_first_half"] += f["story"]
    w = _window_scores(sentences, feats, i, j, agg, loud, opts)
    text = " ".join(sentences[k]["text"] for k in range(i, j + 1))
    w["text"] = text
    rel = cosine(tf_vector(text), global_top) if global_top else w["criteria"]["density"]
    w["criteria"]["relevance"] = rel
    w["criteria"]["context"] = 0.6 * rel + 0.4 * w["criteria"]["density"]
    w["stage1"] = 0.92 * w["stage1"] + 0.08 * w["criteria"]["context"]
    return w


def common_words(sentences: list[dict]) -> Counter:
    """The video's 40 commonest content words (the relevance reference find_candidates uses)."""
    global_tf: Counter = Counter()
    for s in sentences:
        global_tf.update(content_tokens(s["text"]))
    return Counter(dict(global_tf.most_common(40)))


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


def refine_bounds(cand: dict, sentences: list[dict], video_duration: float,
                  loud: Loudness | None = None) -> tuple[float, float]:
    """Pad cut points into the surrounding pauses so words are never clipped. With `loud`, a laugh or a shout right
    after the last word (virality.reaction_after) stays in the clip."""
    i, j = cand["s0"], cand["s1"]
    start, end = sentences[i]["start"], sentences[j]["end"]
    prev_end = sentences[i - 1]["end"] if i > 0 else 0.0
    next_start = sentences[j + 1]["start"] if j + 1 < len(sentences) else video_duration
    start -= min(0.3, max(0.0, (start - prev_end) * 0.5))
    from .virality import reaction_after

    late = reaction_after(sentences, j, loud) if loud is not None else None
    end = min(next_start - 0.02, late[1] + 0.3) if late else end + min(0.5, max(0.05, (next_start - end) * 0.6))
    return max(0.0, round(start, 3)), min(video_duration, round(end, 3))


SENSE_BONUS = 0.10          # stage-1 bonus for a moment built around what was seen or heard (at full strength)
SENSE_LEAD = 0.75           # a clip around an action keeps this share of its length before it, the rest after


SNAP_CUT = 3.0              # a time window's edge moves to a shot cut this close


def around(a: dict, length: float, duration: float) -> tuple[float, float]:
    """The stretch of `length` seconds that holds anchor `a`: ending just after a reaction (its cause comes before
    it), or with SENSE_LEAD of its length before an action and the rest after it."""
    at, until = float(a["at"]), float(a.get("until") or a["at"])
    start = until + 0.5 - length if a.get("end_after") else at - SENSE_LEAD * length
    start = max(0.0, min(max(0.0, duration - length), start))
    return start, min(duration, start + length)


def _snap(start: float, end: float, senses, words: list[dict], min_d: float, max_d: float) -> tuple[float, float]:
    """Move a time window's edges to the nearest shot cuts (when watched) and never through a word."""
    cuts = list(senses.watched.cuts) if senses is not None and senses.watched is not None else []

    def near(t: float) -> float:
        c = min(cuts, key=lambda x: abs(x - t), default=None)
        return c if c is not None and abs(c - t) <= SNAP_CUT else t

    a, b = near(start), near(end)
    if not min_d <= b - a <= max_d:
        a, b = start, end
    for w in words:
        if w["start"] < a < w["end"]:
            a = w["start"]
        if w["start"] < b < w["end"]:
            b = w["end"]
    return round(max(0.0, a), 3), round(b, 3)


def from_senses(sentences: list[dict], feats: list[dict], loud: Loudness, opts: dict, senses, found: list[dict],
                words: list[dict] | None = None, duration: float | None = None) -> list[dict]:
    """New candidate clips built around what ClipForge AI saw and heard (senses.Senses.anchors): a clip that ends
    just after a laugh, a cheer or applause (its cause is the lines before it), or one that holds an explosion, a
    crash or a burst of action with its lead-up. Each is snapped to whole sentences and scored like any other
    window. Where no line is near the moment (a fight, a chase, a goal with nobody talking), the clip is a stretch
    of time around it instead, its edges on shot cuts, scored on what was seen and heard (virality.no_speech). One
    that repeats a candidate already found (overlap above 60%) marks that one instead (`sense`) and raises its
    stage-1 score. Nothing is trusted on its own: every candidate still passes every stage."""
    if senses is None or not sentences:
        return []
    anchors = senses.anchors()
    if not anchors:
        return []
    target = float(opts.get("target_duration", 45))
    max_d, min_d = float(opts["max_duration"]), float(opts["min_duration"])
    top = common_words(sentences)
    duration = float(duration or max([sentences[-1]["end"]] + [x.duration for x in (senses.heard, senses.watched)
                                                               if x is not None]))
    added: list[dict] = []
    base = senses.base_action()

    def keep(w: dict, a: dict) -> None:
        note = {"kind": a["kind"], "why": a["why"], "at": round(float(a["at"]), 2)}
        bonus = SENSE_BONUS * max(0.0, min(1.0, float(a["strength"])))
        twin = max(found + added, key=lambda c: _overlap(w, c), default=None)
        if twin is not None and _overlap(w, twin) > 0.6:
            if "sense" not in twin:
                twin["sense"] = note
                twin["stage1"] = twin["stage1"] + bonus
            return
        w["sense"] = note
        w["stage1"] += bonus
        added.append(w)

    for a in anchors:
        at, until = float(a["at"]), float(a.get("until") or a["at"])
        if a.get("end_after"):
            # the line the reaction answers: the last sentence that starts before the reaction does
            j = max((k for k, s in enumerate(sentences) if s["start"] < at - 0.2), default=-1)
            stop = until
        else:
            stop = until + (1 - SENSE_LEAD) * target
            j = max((k for k, s in enumerate(sentences) if s["start"] <= stop), default=-1)
        if j < 0:
            added_time = _time_window(a, words or [], senses, opts, duration, base)
            if added_time is not None:
                keep(added_time, a)
            continue
        i = j
        while i > 0 and sentences[j]["end"] - sentences[i - 1]["start"] <= min(max_d, max(target, min_d)):
            i -= 1
        while j + 1 < len(sentences) and sentences[j]["end"] - sentences[i]["start"] < min_d \
                and sentences[j + 1]["end"] - sentences[i]["start"] <= max_d:
            j += 1
        if not sentences[i]["start"] - 1.0 <= at <= sentences[j]["end"] + 3.0:
            # no line near the moment (a reaction long after the last words, a fight nobody talks over)
            added_time = _time_window(a, words or [], senses, opts, duration, base)
            if added_time is not None:
                keep(added_time, a)
            continue
        keep(window(sentences, feats, i, j, loud, opts, top), a)
    return added


def _time_window(a: dict, words: list[dict], senses, opts: dict, duration: float, base: float | None = None
                 ) -> dict | None:
    """A stretch of time around anchor `a` that is mostly not talk (under half of it), as a candidate without
    sentences (s0 = -1, scored by virality.no_speech on how much happens in it: senses.show)."""
    target = float(opts.get("target_duration", 45))
    min_d, max_d = float(opts["min_duration"]), float(opts["max_duration"])
    length = max(min_d, min(target, max_d, duration))
    if duration < min_d:
        return None
    start, end = _snap(*around(a, length, duration), senses, words, min_d, max_d)
    talk = sum(max(0.0, min(end, w["end"]) - max(start, w["start"])) for w in words) / max(0.1, end - start)
    if talk >= 0.5 or not start <= float(a["at"]) <= end:
        return None   # mostly talk: the sentence windows cover it
    e = (senses.show(senses.features(start, end), base) or 40.0) / 100.0
    text = " ".join(w["w"] for w in words if start <= w["start"] < end)
    return {"start": start, "end": end, "dur": round(end - start, 3), "s0": -1, "s1": -1, "text": text,
            "stage1": 0.3 + 0.3 * e,
            "criteria": {"hook": 0.3, "engagement": e, "payoff": 0.3, "standalone": 0.5, "context": 0.3,
                         "density": 0.0, "length": 1.0},
            "signals": {"seen_and_heard": round(e, 2), "talk": round(talk, 2)}}


def fallback_windows(loud: Loudness, duration: float, opts: dict, pool_size: int, senses=None) -> list[dict]:
    """No speech found: pick the most energetic, non-overlapping stretches; when ClipForge AI watched and listened,
    the stretches where most happens (what it heard and saw counts for more than loudness)."""
    length = min(opts["target_duration"], max(5.0, duration))
    step = max(2.0, length / 2)
    wins = []
    starts = []
    t = 0.0
    while t + length <= duration + 0.01:
        starts.append(t)
        t += step
    if senses is not None and senses.any():
        for a in senses.anchors():  # windows that hold each strong moment with its lead-up
            s0 = around(a, length, duration)[0]
            if all(abs(s0 - x) >= 1.0 for x in starts):
                starts.append(s0)
    for t in sorted(starts):
        mean_z, std_z = loud.stats(t, t + length)
        e = _sig(1.2 * mean_z)
        signals = {"energy_z": round(mean_z, 2)}
        if senses is not None and senses.any():
            seen_heard = senses.interest(t, t + length)
            e = 0.35 * e + 0.65 * seen_heard
            signals["seen_and_heard"] = round(seen_heard, 2)
        wins.append({"start": t, "end": t + length, "dur": length, "s0": -1, "s1": -1, "text": "",
                     "stage1": 0.3 + 0.3 * e,
                     "criteria": {"hook": 0.3, "engagement": e, "payoff": 0.3, "standalone": 0.5,
                                  "context": 0.3, "density": 0.0, "length": 1.0},
                     "signals": signals})
    wins.sort(key=lambda w: w["stage1"], reverse=True)
    picked: list[dict] = []
    for w in wins:
        if len(picked) >= pool_size:
            break
        if all(_overlap(w, p) <= 0.15 for p in picked):
            picked.append(w)
    return picked
