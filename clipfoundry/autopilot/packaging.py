"""Packaging AI: platform-specific metadata for each selected clip, scored and checked against the transcript.

For every clip and platform, several packaging candidates in different styles are written (curiosity, direct,
emotional, debate, surprising, context), each from the clip's own words. With an AI provider configured its
suggestions are added, and every suggestion must pass the same checks:

* grounding: no names, numbers, quotes, claims or topics that the transcript does not contain
* no unsupported implication (too many words that are not in the clip)
* not repetitive, not a duplicate of an earlier title
* hashtags are words the clip actually uses

A failed AI suggestion is regenerated up to three times with the problems spelled out; after that the safe,
transcript-extracted fallback is used. The best-scoring candidate becomes the suggestion you approve or edit in the
Publish Center. The only words not taken from the clip are fixed call-to-action templates and, for Creative Commons
sources, the attribution line.
"""
from __future__ import annotations

import json
import re
import time

from .. import db
from ..pipeline import artifact, fingerprint, llm, postpack
from ..pipeline.text_utils import (CONTRAST_WORDS, EMOTION_WORDS, INTENSIFIERS, OPEN_LOOP_PHRASES, clean_text,
                                   content_tokens, count_phrases, keywords, tokens)
from . import queue, rights, state
from .host import Job, handler

STYLES = ["curiosity", "direct", "emotional", "debate", "surprising", "context"]
STYLE_LABELS = {"curiosity": "Curiosity", "direct": "Direct", "emotional": "Emotional", "debate": "Debate",
                "surprising": "Surprising", "context": "Context", "ai": "AI suggestion", "fallback": "Safe fallback"}
DEBATE_PHRASES = ["i think", "i believe", "honestly", "wrong", "overrated", "underrated", "should", "shouldn't",
                  "the problem with", "nobody", "everyone", "most people", "that's not", "the truth"]
SURPRISE_PHRASES = ["turns out", "actually", "but", "instead", "the opposite", "believe it or not", "what nobody",
                    "no one tells", "the crazy thing", "i couldn't believe"]
DEBATE_CTA = "Agree or disagree? Tell me in the comments."
YT_TITLE_IDEAL = (25, 70)
TIKTOK_CAPTION_IDEAL = 150
MAX_ATTEMPTS = 3
DUPLICATE_TITLE = 0.8
WEIGHTS = {"curiosity": 0.16, "emotion": 0.12, "clarity": 0.16, "natural": 0.12, "platform_fit": 0.12,
           "searchability": 0.12, "uniqueness": 0.12, "click": 0.08}


# ------------------------------------------------------------------ validation (also used right before publishing)
def _quotes(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[\"“”]([^\"“”]{3,200})[\"“”]", text)]


def _norm(text: str) -> str:
    return " ".join(tokens(text))


def repetition_problems(text: str) -> list[str]:
    toks = [t for t in tokens(text) if len(t) > 3]
    counts = {t: toks.count(t) for t in set(toks)}
    rep = [t for t, n in counts.items() if n >= 3]
    return [f"repeats “{rep[0]}” {counts[rep[0]]} times"] if rep else []


def validate(meta: dict, clip_text: str, prior_titles: list[str] | None = None, allowed_lines: list[str] | None = None
             ) -> list[str]:
    """Everything wrong with a title/caption/description/tags set for this transcript (empty = publishable)."""
    problems: list[str] = []
    template = {_norm(x) for x in [*postpack.CTAS.values(), postpack.CTA_DEFAULT, DEBATE_CTA, *(allowed_lines or [])]}
    for field in ("title", "caption", "description"):
        text = str(meta.get(field) or "")
        body = "\n".join(line for line in text.splitlines()
                         if _norm(re.sub(r"#\w+", "", line)) not in template and not line.startswith("Source: “"))
        body = re.sub(r"#\w+", " ", body).strip()
        if not body:
            continue
        problems += [f"{field}: {p}" for p in postpack.grounding_problems(body, clip_text)]
        for q in _quotes(body):
            if _norm(q) not in _norm(clip_text):
                problems.append(f"{field}: the quote “{q[:60]}” is not what was said")
        problems += [f"{field}: {p}" for p in repetition_problems(body)]
    for tag in [*(meta.get("hashtags") or []), *[f"#{t}" for t in meta.get("tags") or []]]:
        problems += postpack.hashtag_problems("#" + re.sub(r"\W", "", tag), clip_text)
    title = str(meta.get("title") or "")
    for prior in prior_titles or []:
        if title and fingerprint.title_similarity(title, prior) >= DUPLICATE_TITLE:
            problems.append(f"title: nearly the same as an earlier title (“{prior[:60]}”)")
            break
    return list(dict.fromkeys(problems))


# ------------------------------------------------------------------ scoring
def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(meta: dict, platform: str, clip_text: str, clip_keywords: list[str], trend_keywords: list[str],
          prior_titles: list[str], problems: list[str]) -> dict:
    """Packaging Score (0-100) with its components. A package with problems scores 0: it is never used."""
    headline = str(meta.get("title") or meta.get("caption") or "")
    low = headline.lower()
    toks = tokens(headline)
    content = content_tokens(headline)
    n = len(headline)
    comps = {
        "curiosity": _clamp((headline.rstrip().endswith("?") * 0.5) + 0.35 * count_phrases(low, OPEN_LOOP_PHRASES)
                            + 0.15 * sum(1 for t in toks if t in CONTRAST_WORDS)),
        "emotion": _clamp(0.35 * sum(1 for t in toks if t in EMOTION_WORDS) + 0.2 * sum(1 for t in toks
                                                                                         if t in INTENSIFIERS)),
        "clarity": _clamp(0.5 * min(1.0, len(content) / 4) + 0.5 * (len(content) / max(1, len(toks)) >= 0.35)),
        "natural": _clamp(1.0 - 0.4 * headline.endswith("...") - 0.3 * bool(re.search(r"\b[A-Z]{4,}\b", headline))
                          - 0.3 * bool(repetition_problems(headline)) - 0.3 * (len(toks) < 3)),
    }
    if platform == "youtube":
        lo, hi = YT_TITLE_IDEAL
        fit = 1.0 if lo <= n <= hi else max(0.0, 1 - (lo - n) / lo) if n < lo else max(0.0, 1 - (n - hi) / 60)
    else:
        cap = len(str(meta.get("caption") or ""))
        fit = 1.0 if 40 <= cap <= TIKTOK_CAPTION_IDEAL else max(0.0, 1 - abs(cap - 95) / 400)
        fit = fit * (1.0 if 2 <= len(meta.get("hashtags") or []) <= 5 else 0.7)
    comps["platform_fit"] = _clamp(fit)
    words = set(content_tokens(" ".join([headline, str(meta.get("description") or meta.get("caption") or ""),
                                         " ".join(meta.get("hashtags") or []), " ".join(meta.get("tags") or [])])))
    comps["searchability"] = _clamp(0.6 * len(words & set(clip_keywords)) / 3 + 0.4 * (
        len(words & set(trend_keywords)) / 2 if trend_keywords else 0.5))
    similar = max((fingerprint.title_similarity(headline, p) for p in prior_titles), default=0.0)
    comps["uniqueness"] = _clamp(1 - similar)
    comps["click"] = _clamp(0.45 * comps["curiosity"] + 0.3 * comps["emotion"] + 0.25 * comps["clarity"])
    value = 0.0 if problems else sum(WEIGHTS[k] * comps[k] for k in WEIGHTS)
    out = {"score": round(100 * value, 1), "components": {k: round(v, 3) for k, v in comps.items()},
           "grounded": not problems}
    if value and meta.get("style"):
        from . import learner

        lift, posts = learner.lift("style", meta["style"], platform)
        if posts:  # how this packaging style did on your own posts
            adj = max(-8.0, min(8.0, 10 * (lift - 1)))
            out["score"] = round(max(0.0, min(100.0, out["score"] + adj)), 1)
            out["components"]["your_results"] = round(lift, 3)
            out["note"] = f"{adj:+.1f} from {posts} of your {platform} posts in this style"
    return out


# ------------------------------------------------------------------ candidates
def _ranked(sents: list[str], fn) -> list[str]:
    return [s for s in sorted(sents, key=fn, reverse=True) if fn(s) > 0]


def style_lines(sents: list[str], hook: str) -> dict[str, list[str]]:
    """For each style, the clip's own lines that carry it, best first (styles without a fitting line are left out)."""
    def emotional(s: str) -> float:
        toks = tokens(s)
        return sum(1 for t in toks if t in EMOTION_WORDS) + 0.5 * sum(1 for t in toks if t in INTENSIFIERS)

    payoff = postpack._payoff_sentence(sents)  # noqa: SLF001 - the conclusion, said plainly
    by = {
        "curiosity": _ranked(sents, lambda s: 2 * s.rstrip().endswith("?") + count_phrases(s.lower(),
                                                                                          OPEN_LOOP_PHRASES)),
        "emotional": _ranked(sents, emotional),
        "debate": _ranked(sents, lambda s: count_phrases(s.lower(), DEBATE_PHRASES)),
        "surprising": _ranked(sents, lambda s: count_phrases(s.lower(), SURPRISE_PHRASES)),
        "direct": [payoff] + [s for s in reversed(sents) if s != payoff] if payoff else [],
        "context": [x for x in [hook, *sents] if x],
    }
    return {k: v for k, v in by.items() if v}


def _title(line: str) -> str:
    return postpack._clean_title(line)  # noqa: SLF001 - shared extraction helper


def _caption(sents: list[str], lead: str, limit: int = 300) -> str:
    rest = [s for s in sents if s != lead]
    return postpack._join([lead, *rest[:1]], limit)  # noqa: SLF001


def build(platform: str, style: str, title: str, caption: str, hashtags: list[str], cta: str, attribution: str,
          clip_keywords: list[str]) -> dict:
    """A complete platform package from a title and caption."""
    hashtags = hashtags[:5]
    if platform == "youtube":
        parts = [caption, "", cta] if cta else [caption]
        if hashtags:
            parts += ["", " ".join(hashtags[:3])]
        if attribution:
            parts += ["", attribution]
        return {"platform": platform, "style": style, "title": title[:postpack.TITLE_MAX],
                "description": "\n".join(parts).strip()[:4900], "caption": caption,
                "tags": [t.lstrip("#") for t in hashtags] + [k for k in clip_keywords if f"#{k}" not in hashtags][:5],
                "hashtags": hashtags}
    text = " ".join(p for p in [caption, " ".join(hashtags)] if p)
    if attribution:
        text += f"\n{attribution}"
    return {"platform": platform, "style": style, "title": title[:postpack.TITLE_MAX], "caption": text[:2200],
            "description": "", "tags": [], "hashtags": hashtags}


def extracted_candidates(platform: str, sents: list[str], clip: dict, attribution: str, clip_keywords: list[str],
                         hashtags: list[str]) -> list[dict]:
    lines = style_lines(sents, clip.get("hook") or "")
    post = clip.get("post") or {}
    cta = post.get("cta") or postpack.CTA_DEFAULT
    out, seen = [], []
    for style in STYLES:
        pick = next(((line, _title(line)) for line in lines.get(style, [])
                     if _title(line) and all(fingerprint.title_similarity(_title(line), t) < 0.8 for t in seen)), None)
        if not pick:
            continue
        line, title = pick
        seen.append(title)
        style_cta = DEBATE_CTA if style == "debate" else cta
        out.append({**build(platform, style, title, _caption(sents, line), hashtags, style_cta, attribution,
                            clip_keywords), "origin": "extracted"})
    return out


def _ai_prompt(platform: str, sents: list[str], feedback: list[str]) -> str:
    numbered = "\n".join(f"- {s}" for s in sents)
    extra = ("\nYour previous suggestions were rejected because: " + "; ".join(feedback[:8]) +
             ". Fix these problems.") if feedback else ""
    what = "YouTube Shorts titles (max 70 characters)" if platform == "youtube" else "TikTok captions (max 150 " \
                                                                                      "characters, no hashtags)"
    return (f"Short video clip transcript:\n{numbered}\n\nWrite {what} in these styles: {', '.join(STYLES)}. "
            "Use ONLY information in the transcript: no names, numbers, quotes, facts, events, outcomes or claims "
            "that are not in it, and no hype words the speaker does not use. Quotes must be exact. "
            f"Reply with JSON: {{\"suggestions\": [{{\"style\": one of the styles, \"text\": ...}}]}}{extra}")


def ai_candidates(settings: dict, platform: str, sents: list[str], clip: dict, attribution: str,
                  clip_keywords: list[str], hashtags: list[str], clip_text: str, prior: list[str]) -> list[dict]:
    """AI suggestions that pass validation, regenerating up to MAX_ATTEMPTS times with the problems explained."""
    if settings.get("ai_provider", "heuristic") not in llm.PROVIDERS:
        return []
    feedback: list[str] = []
    cta = (clip.get("post") or {}).get("cta") or postpack.CTA_DEFAULT
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            text = llm.complete(settings, _ai_prompt(platform, sents, feedback))
            m = re.search(r"\{.*\}", text or "", re.S)
            data = json.loads(m.group(0)) if m else {}
        except (llm.ProviderError, ValueError):
            return []
        good = []
        feedback = []
        for sug in (data.get("suggestions") or [])[:8]:
            line = clean_text(str(sug.get("text") or "")).strip().strip('"')
            style = sug.get("style") if sug.get("style") in STYLES else "ai"
            if not line:
                continue
            title = _title(line) if platform == "youtube" else _title(sents[0] if sents else line)
            caption = line if platform != "youtube" else _caption(sents, sents[0] if sents else line)
            meta = {**build(platform, style, title, caption, hashtags, cta, attribution, clip_keywords),
                    "origin": "ai", "attempt": attempt}
            problems = validate(meta, clip_text, prior, [attribution])
            if problems:
                feedback += problems
            else:
                good.append(meta)
        if good:
            return good
    return []


def fallback(platform: str, sents: list[str], clip: dict, attribution: str, clip_keywords: list[str],
             hashtags: list[str], clip_text: str, prior: list[str]) -> dict:
    """Safe, transcript-extracted package: the clip's own lines, a fixed CTA, its own words as hashtags."""
    post = clip.get("post") or {}
    for t in [*(post.get("titles") or []), clip.get("title") or "", *(_title(s) for s in sents)]:
        meta = {**build(platform, "fallback", t, _caption(sents, sents[0] if sents else ""), hashtags,
                        postpack.CTA_DEFAULT, attribution, clip_keywords), "origin": "fallback"}
        if t and not validate(meta, clip_text, prior, [attribution]):
            return meta
    first = _title(sents[0]) if sents else (clip.get("title") or "Clip")
    return {**build(platform, "fallback", first, _caption(sents, sents[0] if sents else ""), [], postpack.CTA_DEFAULT,
                    attribution, clip_keywords), "origin": "fallback"}


# ------------------------------------------------------------------ the worker
def prior_titles(exclude_clip: str) -> list[str]:
    """Titles already published or scheduled (so a new title is not a near-duplicate)."""
    rows = db.select("publications", "status IN ('done', 'action_needed', 'uploading', 'processing') AND clip_id != ?",
                     (exclude_clip,))
    sched = db.select("scheduled_publications", "status NOT IN ('canceled', 'replaced', 'failed') AND clip_id != ?",
                      (exclude_clip,))
    return [r["title"] for r in rows + sched if r.get("title")]


def clip_sentences(clip: dict) -> tuple[list[str], str]:
    """(sentences, SHA-256 of the file) of what is heard in the render that would be published: its final
    transcript. Renders made before final transcripts existed fall back to the source words in the clip's range."""
    _, _, render_info = artifact.active(clip)
    art = artifact.of(render_info) or {}
    sents = artifact.final_sentences(render_info)
    if sents is None:
        words = []
        project = db.get_project(clip["project_id"])
        if project and project.get("source_path"):
            from ..pipeline.process import load_words

            words = load_words(project)
        sents = postpack.clip_sentences(words, clip)
    return sents or [clip.get("caption_text") or clip.get("title") or ""], art.get("sha256") or ""


def package(clip: dict, source: dict | None, platform: str, settings: dict) -> dict:
    """Write, check and score all candidates for one platform; returns the chosen one (stored as selected).
    Everything is written from, and checked against, what is heard in the rendered clip."""
    sents, artifact_sha = clip_sentences(clip)
    clip_text = " ".join(sents)
    signal = db.fetch("trend_signals", (source or {}).get("signal_id") or "") if source and source.get(
        "signal_id") else None
    trend_kw = (signal or {}).get("keywords") or []
    clip_kw = keywords(clip_text, top=6)
    hashtags = [t for t in (clip.get("hashtags") or (clip.get("post") or {}).get("hashtags") or [])
                if not postpack.hashtag_problems(t, clip_text)] or postpack.hashtags_for(clip_text)
    attribution = rights.attribution(source or {})
    prior = prior_titles(clip["id"])
    cands = extracted_candidates(platform, sents, clip, attribution, clip_kw, hashtags)
    cands += ai_candidates(settings, platform, sents, clip, attribution, clip_kw, hashtags, clip_text, prior)
    db.execute("DELETE FROM metadata_candidates WHERE clip_id = ? AND platform = ?", (clip["id"], platform))
    scored = []
    for meta in cands:
        problems = validate(meta, clip_text, prior, [attribution])
        sc = score(meta, platform, clip_text, clip_kw, trend_kw, prior, problems)
        scored.append((sc["score"], meta, sc, problems))
    passing = [x for x in scored if not x[3]]
    if not passing:
        meta = fallback(platform, sents, clip, attribution, clip_kw, hashtags, clip_text, prior)
        problems = validate(meta, clip_text, prior, [attribution])
        sc = score(meta, platform, clip_text, clip_kw, trend_kw, prior, [])
        scored.append((sc["score"], meta, {**sc, "note": "safe fallback"}, problems))
        best = scored[-1]
    else:
        best = max(passing, key=lambda x: x[0])
    chosen_id = ""
    for value, meta, sc, problems in scored:
        row = db.insert("metadata_candidates", {
            "clip_id": clip["id"], "platform": platform, "style": meta["style"], "title": meta["title"],
            "description": meta.get("description", ""), "caption": meta.get("caption", ""),
            "tags": meta.get("tags") or [], "hashtags": meta.get("hashtags") or [], "score": value,
            "components": sc["components"], "problems": problems, "attempt": meta.get("attempt", 1),
            "origin": meta.get("origin", "extracted"), "selected": int(meta is best[1]),
            "artifact_sha256": artifact_sha})
        if meta is best[1]:
            chosen_id = row["id"]
    return {**best[1], "id": chosen_id, "score": best[0], "components": best[2]["components"], "problems": best[3]}


def platforms(settings: dict) -> list[str]:
    return [p for p in ("youtube", "tiktok") if settings.get(f"autopilot_{p}")]


@handler("package_clip")
def package_clip(job: Job) -> dict:
    settings = db.get_settings()
    clip = db.get_clip(job.payload.get("clip_id", ""))
    if not clip or clip["status"] != "ready":
        raise queue.Fail("The clip is missing or not rendered")
    project = db.get_project(clip["project_id"]) or {}
    source = db.fetch("sources", project.get("source_id") or "") if project.get("source_id") else None
    if source and not rights.local_allowed(source, settings=settings):
        return {"message": "No further automatic work on this video; keeping its local clips"}
    chosen = {}
    for platform in platforms(settings):
        job.check()
        chosen[platform] = package(clip, source, platform, settings)
    scores = [c["score"] for c in chosen.values()]
    if scores:
        db.execute("UPDATE clip_scores SET packaging = ?, updated_at = ? WHERE clip_id = ?",
                   (round(sum(scores) / len(scores), 1), time.time(), clip["id"]))
    state.event("packaged", f"“{clip['title'][:80]}”: " + ", ".join(
        f"{p} “{c['title'][:50]}” ({c['score']:.0f}, {STYLE_LABELS.get(c['style'], c['style'])})"
        for p, c in chosen.items()), ref_type="clip", ref_id=clip["id"])
    from . import gate

    gate.request(clip, priority=job.row["priority"])  # the final quality gate decides whether it may be scheduled
    return {"platforms": list(chosen), "message": "Packaged for " + (", ".join(chosen) or "no platform")}
