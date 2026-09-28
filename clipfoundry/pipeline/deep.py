"""Deep Clip Analyzer: staged ranking of a broad candidate pool, cheapest checks first.

1. Fast filter     every pool candidate is measured once on its original range with the 11 Viral Potential factors
                   (virality.py); clearly weak ones stop here.
2. Semantic        local sentence embeddings (semantic.py): one topic or several, does the ending tie back to the
                   opening, does it lean on what came just before, how distinctive is it within the video.
3. Deep rerank     the strongest candidates get the full evaluation (nearby sentence ranges, the optional AI
                   provider, hooks and titles, see scoring.py), audio analysis (speech density, silence, energy
                   spikes, laughter/applause-like reactions), and for the very best a visual pass (faces, scene
                   changes, motion, sharpness). Extra factors: quoteability, debate potential, shareability,
                   titleability, loopability and relevance to the source's trend.
4. Boundaries      exact start/end times: cut in the quietest moment of the pause around the first and last word,
                   with little dead air and without clipping speech.
5. Diversity       diversity.py picks the final clips.

The 11-factor Viral Potential stays the base of the Clip Score; the later stages adjust it by a bounded, explained
amount. Scores are estimates for ranking, never a prediction of views.
"""
from __future__ import annotations

import numpy as np

from . import candidates as cand_mod
from . import diversity, hooks, reframe, scoring, semantic, virality
from .audio import Loudness
from .common import Cancelled, JobContext, log
from .text_utils import CONTRAST_WORDS, EMOTION_WORDS, PAYOFF_PHRASES, content_tokens, count_phrases, tokens

FAST_KEEP_MIN = 20
DEEP_KEEP = 12
VISUAL_KEEP = 6
DEBATE_PHRASES = ["i think", "i believe", "honestly", "wrong", "overrated", "underrated", "unpopular opinion",
                  "disagree", "should", "shouldn't", "the problem with", "change my mind", "hot take",
                  "controversial", "nobody wants to", "let's be real", "that's not", "no way", "what do you think",
                  "would you"]
PRACTICAL_PHRASES = ["how to", "you should", "the trick", "tip", "here's how", "the key", "step", "mistake",
                     "you need to", "do this", "stop doing", "the secret"]
SURPRISE_PHRASES = ["turns out", "actually", "believe it or not", "the crazy thing", "what nobody", "no one tells",
                    "plot twist", "suddenly", "out of nowhere", "i couldn't believe"]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# ------------------------------------------------------------------ audio
def _runs(mask: np.ndarray) -> list[int]:
    """Lengths of the runs of True in a boolean array."""
    runs, run = [], 0
    for flag in mask:
        if flag:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    return runs


def audio_features(start: float, end: float, words: list[dict], loud: Loudness) -> dict:
    dur = max(0.1, end - start)
    ws = [w for w in words if w["end"] > start and w["start"] < end]
    speech = sum(max(0.0, min(w["end"], end) - max(w["start"], start)) for w in ws)
    a, b = int(start / loud.hop), int(end / loud.hop)
    z = loud.z[a:b] if b > a else np.zeros(1)
    covered = np.zeros(len(z), dtype=bool)
    for w in ws:
        covered[max(0, int((w["start"] - start) / loud.hop)):max(0, int((w["end"] - start) / loud.hop) + 1)] = True
    # dead air: quiet stretches without words longer than 0.7 s
    silence = sum(r * loud.hop for r in _runs(~covered & (z < -0.5)) if r * loud.hop > 0.7) / dur
    win = max(1, int(1.0 / loud.hop))
    smooth = np.convolve(z, np.ones(win) / win, mode="same") if len(z) >= win else z
    peaks = [k for k in range(1, len(smooth) - 1) if smooth[k] > 1.5 and smooth[k] >= smooth[k - 1]
             and smooth[k] >= smooth[k + 1]]
    spikes, last = 0, -10 ** 9
    for k in peaks:
        if k - last >= 2 * win:
            spikes += 1
            last = k
    # loud stretches without words: laughter, applause, a crowd reacting (an estimate from loudness alone)
    reactions = [r * loud.hop for r in _runs(~covered & (z > 1.0)) if r * loud.hop >= 0.4]
    score = (0.35 * _clamp(speech / dur) + 0.25 * (1 - min(1.0, silence * 3)) + 0.2 * min(1.0, spikes / 3)
             + 0.2 * min(1.0, len(reactions) / 2))
    return {"speech_density": round(speech / dur, 3), "silence_ratio": round(silence, 3),
            "mean_z": round(float(z.mean()), 2) if len(z) else 0.0, "peak_z": round(float(smooth.max()), 2)
            if len(smooth) else 0.0, "energy_spikes": spikes, "reactions": len(reactions),
            "reaction_seconds": round(sum(reactions), 1), "score": round(score, 3),
            "estimated": ["reactions (loud moments without speech: laughter, applause, crowd)"]}


# ------------------------------------------------------------------ visual
def visual_features(video: str, start: float, end: float, meta: dict, ctx: JobContext | None) -> dict | None:
    if not video or not meta.get("width") or not meta.get("has_video", True):
        return None
    try:
        a = reframe.analyze(video, start, end, int(meta["width"]), int(meta["height"]), ctx)
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - visual analysis is a bonus, never a blocker
        log.warning("visual analysis failed: %s", exc)
        return None
    n = max(1, a["n"])
    dur = max(0.1, end - start)
    face = max((t.presence for t in a["tracks"]), default=0) / n
    speakers = sum(1 for t in a["tracks"] if t.presence > 0.2 * n)
    cuts10 = len(a["cuts"]) / dur * 10
    motion = float(a["motion"])
    sharp = _clamp(float(a["edge"]) / 0.06)
    motion_fit = 1 - abs(_clamp(motion / 8) - 0.45) / 0.55
    quality = 0.4 * _clamp(face * 1.5) + 0.3 * sharp + 0.3 * _clamp(motion_fit)
    activity = 0.6 * _clamp(motion / 8) + 0.4 * _clamp(cuts10 / 2)
    return {"face_presence": round(face, 3), "speakers_on_screen": speakers, "scene_changes_per_10s": round(cuts10, 2),
            "motion": round(motion, 2), "sharpness": round(sharp, 3), "quality": round(quality, 3),
            "activity": round(activity, 3)}


# ------------------------------------------------------------------ text extras
def text_extras(sents: list[str], sem: dict, dur: float, trend_keywords: list[str] | None) -> dict:
    text = " ".join(sents)
    low = text.lower()
    toks = tokens(text)
    n_words = max(1, len(toks))
    best_line = max(sents, key=lambda s: hooks._hookiness(s, 0.0), default="")  # noqa: SLF001
    quote = 0.0
    for s in sents:
        k = len(s.split())
        if 5 <= k <= 16 and s.rstrip().endswith((".", "!", "?")):
            quote = max(quote, _clamp((hooks._hookiness(s, 0.0) - 0.5) / 3.5)  # noqa: SLF001
                        + 0.3 * bool(count_phrases(s.lower(), PAYOFF_PHRASES)))
    debate = _clamp(count_phrases(low, DEBATE_PHRASES) / 3 + 0.3 * low.count("?") / max(1, len(sents)))
    emotion = _clamp(sum(1 for t in toks if t in EMOTION_WORDS) / max(1.0, n_words / 25))
    practical = _clamp(count_phrases(low, PRACTICAL_PHRASES) / 2)
    surprise = _clamp(count_phrases(low, SURPRISE_PHRASES) / 2 + sum(1 for t in toks if t in CONTRAST_WORDS)
                      / max(1.0, n_words / 20))
    share = 0.35 * emotion + 0.25 * _clamp(quote) + 0.2 * practical + 0.2 * surprise
    titleable = _clamp((hooks._hookiness(best_line, 0.0) - 0.5) / 4) if best_line else 0.0  # noqa: SLF001
    loop = _clamp(0.5 * max(0.0, sem.get("closure", 0.0)) + 0.3 * (dur <= 35) + 0.2 * (dur <= 60))
    out = {"quoteability": round(_clamp(quote), 3), "debate": round(debate, 3), "shareability": round(share, 3),
           "titleability": round(titleable, 3), "loopability": round(loop, 3), "trend_relevance": None}
    if trend_keywords:
        kws = set(content_tokens(text))
        hits = len(kws & set(trend_keywords))
        out["trend_relevance"] = round(_clamp(hits / 2), 3)
    return out


# ------------------------------------------------------------------ boundaries
def optimize_bounds(r: dict, sentences: list[dict], loud: Loudness, duration: float) -> dict:
    """Exact cut points: in the quietest moment of the pause before the first word and after the last one."""
    i, j = r["s0"], r["s1"]
    first, last = sentences[i]["start"], sentences[j]["end"]
    prev_end = sentences[i - 1]["end"] if i > 0 else 0.0
    next_start = sentences[j + 1]["start"] if j + 1 < len(sentences) else duration
    reasons = []
    gap_before, gap_after = first - prev_end, next_start - last
    if gap_before < 0.08:
        start = max(0.0, first - 0.02)
        reasons.append("starts right after the previous words (tight cut)")
    else:
        q = loud.quietest(max(prev_end, first - 0.6), max(prev_end, first - 0.02))
        start = max(q, first - 0.35)
    if gap_after < 0.1:
        end = last + max(0.0, gap_after / 2)
        reasons.append("the next words follow immediately (tight cut)")
    else:
        q = loud.quietest(last + 0.05, min(next_start - 0.02, last + 0.8))
        end = max(last + 0.12, min(q, last + 0.6))
    start, end = max(0.0, round(start, 3)), min(duration, round(end, 3))
    return {"start": start, "end": end, "lead_in": round(first - start, 3), "tail": round(end - last, 3),
            "gap_before": round(gap_before, 3), "gap_after": round(gap_after, 3), "notes": reasons}


# ------------------------------------------------------------------ combine
def clip_score(r: dict) -> tuple[float, list[str]]:
    """Clip Score = Viral Potential (11 factors) + bounded, explained adjustments from the deeper stages."""
    base = float(r["score"])
    why = [f"Viral Potential {base:.0f} (11 factors)"]
    d = r["deep"]
    extras = [v for k, v in d["extras"].items() if v is not None and k != "trend_relevance"]
    extras.append(d["audio"]["score"])
    if d.get("visual"):
        extras.append(d["visual"]["quality"])
    adj_x = max(-8.0, min(8.0, 16 * (sum(extras) / len(extras) - 0.5)))
    adj_s = max(-6.0, min(6.0, 10 * (d["semantic"]["score"] - 0.5)))
    adj_t = 4 * d["extras"]["trend_relevance"] if d["extras"].get("trend_relevance") is not None else 0.0
    adj_v = -4.0 if d.get("visual") and d["visual"]["quality"] < 0.25 else 0.0
    for label, v in (("shareability, quotes, debate, titles, loops, audio/visual", adj_x),
                     ("semantic shape (one topic, closure, standalone, distinct)", adj_s),
                     ("matches the source's trending topic", adj_t), ("weak picture", adj_v)):
        if abs(v) >= 0.5:
            why.append(f"{v:+.1f} {label}")
    return round(max(0.0, min(100.0, base + adj_x + adj_s + adj_t + adj_v)), 1), why


def evaluate_select(sentences: list[dict], words: list[dict], loud: Loudness, opts: dict, ctx: JobContext,
                    video_name: str, cands: list[dict], video_path: str = "", meta: dict | None = None,
                    lo: float = 0.5, hi: float = 0.58, trend_keywords: list[str] | None = None,
                    prior: list[dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    """(chosen, evaluated results, notes). `notes["candidates"]` records how far each pool candidate got."""
    meta = meta or {}
    count = int(opts.get("clip_count", 5))
    min_score = float(opts.get("min_score", 50))
    min_quality = float(opts.get("min_quality", 0))
    for k, c in enumerate(cands):
        c.setdefault("cid", k)
    track = {c["cid"]: {"cid": c["cid"], "start": c["start"], "end": c["end"], "stage": "pool",
                        "stage1": round(float(c.get("stage1", 0)), 4), "score": None, "reasons": [],
                        "text": (c.get("text") or "")[:300]} for c in cands}
    if not sentences:  # no speech: the standard path handles loudness-only windows
        results, notes = scoring.evaluate(cands, sentences, opts, ctx, video_name, lo, hi, words=words, loud=loud)
        chosen = scoring.select(results, count, min_score)
        return chosen, results, {**notes, "candidates": list(track.values()), "stages": {"pool": len(cands)}}

    feats = cand_mod.sentence_features(sentences, words)
    emb = semantic.embed_sentences(sentences)
    # 1. fast filter
    ctx.progress(lo, f"Fast filter: {len(cands)} candidates")
    fast = []
    for c in cands:
        ctx.check()
        r = virality.analyze(c["s0"], c["s1"], sentences, feats, words, loud, opts) if c["s0"] >= 0 else \
            virality.no_speech(c)
        fast.append((c, r))
        track[c["cid"]]["score"] = r["viral_potential"]
    keep_n = max(FAST_KEEP_MIN, 4 * count)
    fast.sort(key=lambda cr: cr[1]["viral_potential"] + 10 * float(cr[0].get("stage1", 0)), reverse=True)
    kept = []
    for c, r in fast:
        if r["viral_potential"] < min_score - 25:
            track[c["cid"]]["reasons"].append(f"Fast filter: Viral Potential {r['viral_potential']:.0f} is far below "
                                              f"the minimum")
        elif len(kept) >= keep_n:
            track[c["cid"]]["reasons"].append("Fast filter: not among the strongest candidates")
        else:
            kept.append((c, r))
            track[c["cid"]]["stage"] = "fast"
    # 2. semantic
    ctx.progress(lo + (hi - lo) * 0.1, f"Semantic analysis: {len(kept)} candidates")
    ranked = []
    for c, r in kept:
        sem = semantic.features(emb, c["s0"], c["s1"])
        ranked.append((r["viral_potential"] + 10 * (sem["score"] - 0.5), c))
        track[c["cid"]]["stage"] = "semantic"
    ranked.sort(key=lambda x: x[0], reverse=True)
    deep_cands = [c for _, c in ranked[:DEEP_KEEP]]
    for _, c in ranked[DEEP_KEEP:]:
        track[c["cid"]]["reasons"].append("Semantic stage: not among the strongest candidates")
    # 3. deep rerank (full evaluation incl. nearby ranges and the optional AI provider)
    results, notes = scoring.evaluate(deep_cands, sentences, opts, ctx, video_name, lo + (hi - lo) * 0.15,
                                      lo + (hi - lo) * 0.7, words=words, loud=loud)
    for r in results:
        ctx.check()
        track[r["cid"]]["stage"] = "deep"
        sents = [sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)] if r["s0"] >= 0 else []
        sem = semantic.features(emb, r["s0"], r["s1"])
        r["deep"] = {"semantic": sem, "audio": audio_features(r["start"], r["end"], words, loud),
                     "extras": text_extras(sents, sem, r["end"] - r["start"], trend_keywords), "visual": None}
        r["clip_score"], r["explanation"] = clip_score(r)
    order = sorted(results, key=lambda r: r["clip_score"], reverse=True)
    visual_n = 0
    for k, r in enumerate(order[:VISUAL_KEEP]):
        ctx.progress(lo + (hi - lo) * (0.7 + 0.25 * k / VISUAL_KEEP), f"Visual analysis {k + 1} of "
                                                                         f"{min(VISUAL_KEEP, len(order))}")
        vis = visual_features(video_path, r["start"], r["end"], meta, ctx)
        if vis:
            r["deep"]["visual"] = vis
            r["clip_score"], r["explanation"] = clip_score(r)
            visual_n += 1
    # 4. boundaries
    duration = float(meta.get("duration") or sentences[-1]["end"] + 1.0)
    for r in results:
        if r["s0"] >= 0:
            r["bounds"] = optimize_bounds(r, sentences, loud, duration)
        track[r["cid"]]["score"] = r["clip_score"]
    # 5. diversity
    chosen, rejected = diversity.select(results, count, min_score, sentences, emb, min_quality, prior)
    for r in rejected:
        track[r["cid"]]["reasons"] += r["reasons"]
    for r in chosen:
        track[r["cid"]]["stage"] = "selected"
    notes["stages"] = {"pool": len(cands), "fast": len(kept), "semantic": len(ranked), "deep": len(results),
                       "visual": visual_n, "selected": len(chosen)}
    notes["candidates"] = list(track.values())
    notes["rejected"] = [{"start": r["start"], "end": r["end"], "score": r.get("clip_score"), "reasons": r["reasons"],
                          "text": (r.get("caption_text") or "")[:160]} for r in rejected]
    return chosen, results, notes
