"""Stage 2: evaluate the strongest candidates and build clip metadata.

Scores five criteria (hook, engagement, context, payoff, standalone).  With an
AI provider configured, its scores are blended with the local heuristic; with
no provider (the default) the heuristic alone is used, fully offline.
"""
from __future__ import annotations

import math
from collections import Counter

from . import hooks as hk
from . import llm
from .common import JobContext, log
from .text_utils import keywords

WEIGHTS = {"hook": 0.30, "engagement": 0.20, "context": 0.15, "payoff": 0.20, "standalone": 0.15}


def heuristic_scores(cand: dict) -> dict:
    c = cand["criteria"]
    return {
        "hook": round(10 * c.get("hook", 0.5), 2),
        "engagement": round(10 * c.get("engagement", 0.5), 2),
        "context": round(10 * c.get("context", 0.5), 2),
        "payoff": round(10 * min(1.0, c.get("payoff", 0.5)), 2),
        "standalone": round(10 * c.get("standalone", 0.5), 2),
    }


def overall(scores: dict) -> float:
    raw = sum(WEIGHTS[k] * scores.get(k, 5.0) for k in WEIGHTS) / 10.0
    return round(100.0 / (1.0 + math.exp(-(raw - 0.45) * 7.0)), 1)


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
             lo: float, hi: float) -> tuple[list[dict], dict]:
    provider = settings.get("ai_provider", "heuristic")
    use_ai = provider in llm.PROVIDERS
    max_ai = int(settings.get("ai_max_candidates", 12))
    failures, ai_ok = 0, 0
    notes: dict = {"provider": llm.provider_label(settings) if use_ai else "Local heuristic"}

    global_df: Counter = Counter()
    for s in sentences:
        global_df.update(set(keywords(s["text"], top=50)))
    n_docs = max(1, len(sentences))

    results = []
    for n, cand in enumerate(cands):
        ctx.check()
        ctx.progress(lo + (hi - lo) * n / max(1, len(cands)),
                     f"Evaluating candidate {n + 1}/{len(cands)}" + (f" with {notes['provider']}" if use_ai else ""))
        s0, s1 = cand["s0"], cand["s1"]
        has_text = s0 >= 0
        sent_texts = [sentences[k]["text"] for k in range(s0, s1 + 1)] if has_text else []
        heur = heuristic_scores(cand)
        ai = None
        if use_ai and has_text and n < max_ai and failures < 2:
            before = sentences[s0 - 1]["text"] if s0 > 0 else ""
            try:
                ai = llm.evaluate(settings, video_name, sent_texts, before, cand["dur"])
                ai_ok += 1
            except llm.ProviderError as exc:
                failures += 1
                notes["warning"] = f"AI provider failed ({exc}); used local heuristic scoring."
                log.warning("Stage 2 provider error: %s", exc)

        if ai and ai.get("range"):
            a, b = ai["range"]
            ns0, ns1 = s0 + a, s0 + b
            new_dur = sentences[ns1]["end"] - sentences[ns0]["start"]
            if (ns0, ns1) != (s0, s1) and new_dur >= max(8.0, 0.6 * settings["min_duration"]):
                cand = {**cand, "s0": ns0, "s1": ns1, "start": sentences[ns0]["start"],
                        "end": sentences[ns1]["end"], "dur": new_dur}
                s0, s1 = ns0, ns1
                sent_texts = [sentences[k]["text"] for k in range(s0, s1 + 1)]

        if ai:
            scores = {k: round(0.65 * ai["scores"][k] + 0.35 * heur[k], 2) for k in WEIGHTS}
            source = notes["provider"]
        else:
            scores = heur
            source = "Local heuristic"
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
        tags = (ai or {}).get("hashtags") or hk.hashtags(clip_text, category, global_df, n_docs)
        reason = (ai or {}).get("reason") or hk.reason_text(cand["criteria"], cand.get("signals", {}))

        results.append({
            **cand,
            "scores": scores,
            "score": overall(scores),
            "score_source": source,
            "title": title,
            "hook": hook,
            "hooks_alt": alts,
            "category": category,
            "hashtags": tags,
            "reason": reason,
            "caption_text": clip_text,
        })
    if use_ai and ai_ok == 0:
        notes.setdefault("warning", "AI provider unavailable; used local heuristic scoring.")
    return results, notes


def select(results: list[dict], count: int, min_score: float) -> list[dict]:
    """Best-first, diverse, quality-gated. Returns fewer clips when fewer are strong."""
    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    picked: list[dict] = []
    for r in ranked:
        if len(picked) >= count:
            break
        if picked and r["score"] < min_score:
            break
        overlap = any(min(r["end"], p["end"]) - max(r["start"], p["start"]) > 0.15 * min(r["dur"], p["dur"])
                      for p in picked)
        if not overlap:
            picked.append(r)
    return picked
