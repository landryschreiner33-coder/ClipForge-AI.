"""Stage 2: evaluate the strongest candidates, rank them by Viral Potential and build clip metadata.

Every candidate is measured on eleven factors (see virality.py). Nearby sentence ranges are compared first, so a
clip can drop a warm-up opening, stop at its payoff, or run one sentence longer instead of cutting before an answer.
With an AI provider configured, its factor scores are blended with the measured ones; with no provider (the
default) the local analysis alone is used, fully offline.
"""
from __future__ import annotations

from collections import Counter

from . import candidates as cand_mod
from . import hooks as hk
from . import llm, postpack, virality
from .audio import Loudness
from .common import JobContext, log
from .text_utils import keywords

# Old five-criterion AI answers map onto the new factors.
LEGACY_AI = {"hook": "hook", "payoff": "payoff", "standalone": "standalone", "engagement": "emotion",
             "context": "density"}


def _words_from_sentences(sentences: list[dict]) -> list[dict]:
    """Evenly timed words when only sentences are available (tests, imported transcripts without words)."""
    out = []
    for s in sentences:
        toks = s["text"].split()
        step = (s["end"] - s["start"]) / max(1, len(toks))
        out += [{"start": s["start"] + k * step, "end": s["start"] + (k + 1) * step, "w": t} for k, t in enumerate(toks)]
    return out


def document_frequencies(sentences: list[dict]) -> Counter:
    """In how many sentences each keyword occurs (makes keywords specific to a clip within its video)."""
    df: Counter = Counter()
    for s in sentences:
        df.update(set(keywords(s["text"], top=50)))
    return df


def reason_text(r: dict) -> str:
    """One line on why the clip ranks where it does, from its structure, best factors and warnings."""
    f = r["factors"]
    best = sorted(("hook", "curiosity", "emotion", "density", "payoff"), key=lambda k: f[k], reverse=True)[:2]
    parts = [r["structure"]["label"] if r["structure"]["label"] != "No clear structure" else ""]
    parts.append("strongest: " + ", ".join(virality.FACTOR_LABELS[k].lower() for k in best))
    warns = [fl["label"].lower() for fl in r["flags"] if fl["severity"] == "warn"]
    if warns:
        parts.append("watch out: " + ", ".join(warns))
    text = "; ".join(p for p in parts if p)
    return text[:1].upper() + text[1:]


def _dedupe(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for it in items:
        key = it.lower().strip(" .!?\"“”")
        if it and key and all(key != o.lower().strip(" .!?\"“”") for o in out):
            out.append(it)
        if len(out) >= limit:
            break
    return out


def evaluate(cands: list[dict], sentences: list[dict], settings: dict, ctx: JobContext, video_name: str,
             lo: float, hi: float, words: list[dict] | None = None, loud: Loudness | None = None
             ) -> tuple[list[dict], dict]:
    provider = settings.get("ai_provider", "heuristic")
    use_ai = provider in llm.PROVIDERS
    max_ai = int(settings.get("ai_max_candidates", 12))
    failures, ai_ok = 0, 0
    notes: dict = {"provider": llm.provider_label(settings) if use_ai else "Local analysis"}
    words = words if words is not None else _words_from_sentences(sentences)
    loud = loud or Loudness({"hop": 0.1, "db": [-20.0] * 10})
    feats = cand_mod.sentence_features(sentences, words) if sentences else []

    global_df = document_frequencies(sentences)
    n_docs = max(1, len(sentences))

    results = []
    for n, cand in enumerate(cands):
        ctx.check()
        ctx.progress(lo + (hi - lo) * n / max(1, len(cands)),
                     f"Evaluating candidate {n + 1}/{len(cands)}" + (f" with {notes['provider']}" if use_ai else ""))
        if cand["s0"] < 0:  # no speech: loudness-only candidate
            r = virality.no_speech(cand)
        else:
            # Compare nearby ranges (weak opening trimmed, talk after the payoff trimmed, answer included).
            orig = (cand["s0"], cand["s1"])
            r = max((virality.analyze(a, b, sentences, feats, words, loud, settings)
                     for a, b in virality.variants(*orig, sentences, settings, feats)),
                    key=lambda x: x["raw"] - (0.01 if (x["s0"], x["s1"]) != orig else 0.0))
        s0, s1 = r["s0"], r["s1"]
        has_text = s0 >= 0
        sent_texts = [sentences[k]["text"] for k in range(s0, s1 + 1)] if has_text else []

        ai = None
        if use_ai and has_text and n < max_ai and failures < 2:
            before = sentences[s0 - 1]["text"] if s0 > 0 else ""
            try:
                ai = llm.evaluate(settings, video_name, sent_texts, before, r["dur"])
                ai_ok += 1
            except llm.ProviderError as exc:
                failures += 1
                notes["warning"] = f"AI provider failed ({exc}); used the local analysis."
                log.warning("Stage 2 provider error: %s", exc)
        if ai and ai.get("range"):
            a, b = ai["range"]
            ns0, ns1 = s0 + a, s0 + b
            new_dur = sentences[ns1]["end"] - sentences[ns0]["start"]
            if (ns0, ns1) != (s0, s1) and new_dur >= max(8.0, 0.6 * settings["min_duration"]):
                r = virality.analyze(ns0, ns1, sentences, feats, words, loud, settings)
                s0, s1 = ns0, ns1
                sent_texts = [sentences[k]["text"] for k in range(s0, s1 + 1)]
        if ai:
            ai_factors = ai.get("factors") or {LEGACY_AI[k]: v for k, v in ai["scores"].items() if k in LEGACY_AI}
            virality.blend_ai(r, ai_factors)
            source = f"{notes['provider']} + local analysis"
        else:
            source = "Local analysis"
        clip_text = " ".join(sent_texts)

        hook, alts = hk.heuristic_hooks(sent_texts) if sent_texts else ("", [])
        if ai:
            ai_hooks = [h for h in [ai.get("hook_text", "")] + ai.get("alt_hooks", []) if hk.is_grounded(h, clip_text)]
            if ai_hooks:
                pool = _dedupe(ai_hooks + ([hook] if hook else []) + alts, 4)
                hook, alts = pool[0], pool[1:4]
        kws = keywords(clip_text, global_df, n_docs, top=4)
        category = (ai or {}).get("category") or hk.categorize(clip_text)
        title = (ai or {}).get("title") or ""
        if not title or not hk.is_grounded(title, clip_text):
            title = hk.make_title(hook, kws)
        # hashtags are words the clip actually uses (AI suggestions only when they pass the same check)
        tags = [t for t in (ai or {}).get("hashtags") or [] if not postpack.hashtag_problems(t, clip_text)] \
            or postpack.hashtags_for(clip_text, global_df, n_docs)
        results.append({
            **cand,
            "s0": s0, "s1": s1, "start": r["start"], "end": r["end"], "dur": r["dur"],
            "analysis": r,
            "score_source": source,
            "title": title,
            "hook": hook,
            "hooks_alt": alts,
            "category": category,
            "hashtags": tags,
            "ai_reason": (ai or {}).get("reason") or "",
            "caption_text": clip_text,
        })
    virality.set_uniqueness([res["analysis"] for res in results if res["s0"] >= 0])
    for res in results:
        a = res["analysis"]
        res["score"] = a["viral_potential"]
        res["scores"] = virality.summary(a)["factors"]
        res["reason"] = res.pop("ai_reason") or reason_text(a)
    if use_ai and ai_ok == 0:
        notes.setdefault("warning", "AI provider unavailable; used the local analysis.")
    return results, notes


def _overlaps(r: dict, picked: list[dict]) -> bool:
    return any(min(r["end"], p["end"]) - max(r["start"], p["start"]) > 0.15 * min(r["dur"], p["dur"]) for p in picked)


def rejection(r: dict, min_score: float) -> list[str]:
    """Why a candidate is not good enough to show (empty = it passes the quality bar)."""
    reasons = [f"{fl['label']}: {fl['detail']}" for fl in r["analysis"]["flags"] if fl["severity"] == "block"]
    if r["score"] < min_score:
        reasons.append(f"Viral Potential {r['score']:.0f} is below the minimum of {min_score:.0f}")
    return reasons


def select(results: list[dict], count: int, min_score: float) -> list[dict]:
    """Best-first by Viral Potential, diverse, quality-gated.

    Only candidates that pass the quality bar are returned, so a video with four strong moments gives four clips even
    when ten were requested, and a video with none gives none. Weaker filler is never added to reach the count.
    """
    picked: list[dict] = []
    for r in sorted(results, key=lambda r: r["score"], reverse=True):
        if len(picked) >= count:
            break
        if not rejection(r, min_score) and not _overlaps(r, picked):
            picked.append(r)
    return picked


def quality_report(results: list[dict], picked: list[dict], count: int, min_score: float) -> dict:
    """What the project page shows about the candidates that were not turned into clips."""
    ids = {id(p) for p in picked}
    rejected, counts = [], Counter()
    for r in sorted(results, key=lambda r: r["score"], reverse=True):
        if id(r) in ids:
            continue
        reasons = rejection(r, min_score) or (["Overlaps a better clip"] if _overlaps(r, picked) else [])
        if not reasons:
            continue  # passed the bar but the requested count was already reached
        for reason in reasons:
            counts[reason.split(":")[0].split(" is below")[0]] += 1
        rejected.append({"start": round(r["start"], 2), "end": round(r["end"], 2), "score": r["score"],
                         "text": r.get("caption_text", "")[:160], "reasons": reasons})
    return {"evaluated": len(results), "passed": sum(1 for r in results if not rejection(r, min_score)),
            "shown": len(picked), "requested": count, "min_score": min_score, "reject_counts": dict(counts),
            "rejected": rejected[:8], "note": virality.ESTIMATE_NOTE}
