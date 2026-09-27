"""Post packages: what you need to publish a clip, written only from the clip's own words.

For every clip: three title options (one recommended), three caption/description options, hashtags, a short
description, a call-to-action suggestion and hook text. Titles, captions, the description, the hook and the hashtags
are extracted from the clip's transcript. The only words that are not from the clip are the fixed call-to-action
templates, which ask the viewer to do something and state nothing about the content.

`grounding_problems` checks text against the transcript: numbers, names, claims and words that are not in the clip
are reported. An AI provider's suggestions are used only when they pass that check; everything else falls back to the
extracted text. The user edits and approves the package before anything is published.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from . import hooks as hk
from . import llm
from .common import log
from .text_utils import (PAYOFF_PHRASES, STOPWORDS, build_sentences, clean_text, content_tokens, count_phrases,
                         keywords, tokens)

TITLE_MAX = 100          # YouTube's limit; TikTok has no separate title
CAPTION_MAX = 2200       # TikTok's caption limit (YouTube descriptions allow 5000 bytes)
DESCRIPTION_MAX = 160
HASHTAG_LIMIT = 6

# Call-to-action templates. They ask for an action and make no statement about the clip.
CTAS = {
    "question": "What would you do? Tell me in the comments.",
    "Opinion": "Agree or disagree? Let me know in the comments.",
    "Educational": "Save this so you have it when you need it.",
    "Motivational": "Send this to someone who needs to hear it.",
    "Emotional": "Send this to someone who needs to hear it.",
    "Funny": "Tag someone who needs to see this.",
    "Business": "Save this for later.",
    "Story": "Follow for more stories like this.",
    "Q&A": "What would you ask? Tell me in the comments.",
}
CTA_DEFAULT = "Follow for more clips like this."
CTA_WORDS = set(tokens(" ".join(CTAS.values()) + " " + CTA_DEFAULT))

# Words that make a claim; allowed only when the clip itself says them.
CLAIM_WORDS = {"viral", "shocking", "insane", "banned", "exposed", "secret", "secrets", "guaranteed", "proven",
               "official", "breaking", "exclusive", "leaked", "revealed", "reveals", "best", "worst", "never", "always",
               "everyone", "nobody", "ever", "only", "first", "last", "famous", "scientists", "experts", "study",
               "research", "doctors", "billionaire", "millionaire"}
NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million", "billion", "percent",
                "half", "double", "twice", "dozen"}
EDITABLE = {"titles", "recommended_title", "captions", "hashtags", "description", "cta", "hook", "title", "caption"}


# ------------------------------------------------------------------ grounding
def _known(clip_text: str):
    src = set(tokens(clip_text))
    stems = {t[:4] for t in src if len(t) >= 4}
    return src, lambda t, allowed=frozenset(): t in src or t in allowed or (len(t) >= 4 and t[:4] in stems)


def grounding_problems(text: str, clip_text: str, allowed: set[str] | frozenset = frozenset()) -> list[str]:
    """What in `text` is not supported by the clip's transcript (empty list = fully grounded)."""
    problems: list[str] = []
    src, known = _known(clip_text)
    src_digits = re.sub(r"(?<=\d),(?=\d)", "", clip_text.lower())
    for num in re.findall(r"\d[\d,.]*", text):
        n = re.sub(r"(?<=\d),(?=\d)", "", num).strip(".,")
        if n and not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", src_digits):
            problems.append(f"the number {num.strip('.,')} is not in the clip")
    toks = tokens(text)
    for t in dict.fromkeys(toks):
        if t in NUMBER_WORDS and t not in src:
            problems.append(f"“{t}” is not in the clip")
        elif t in CLAIM_WORDS and t not in src and t not in allowed:
            problems.append(f"“{t}” makes a claim the clip does not make")
    for sentence in re.split(r"(?<=[.!?:])\s+|\n+", text):
        words = re.findall(r"[A-Za-z][A-Za-z'’\-]*", sentence)
        for w in words[1:]:
            low = w.lower().replace("’", "'")
            if w[0].isupper() and low not in STOPWORDS and low != "i" and not known(low, allowed):
                problems.append(f"the name “{w}” is not in the clip")
    content = [t for t in content_tokens(text) if t not in allowed]
    unknown = [t for t in dict.fromkeys(content) if not known(t)]
    if content and len(unknown) / len(set(content)) > 0.25:
        problems.append("adds words that are not in the clip: " + ", ".join(unknown[:5]))
    return list(dict.fromkeys(problems))


def hashtag_problems(tag: str, clip_text: str) -> list[str]:
    body = tag.lstrip("#")
    parts = [p.lower() for p in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", body)] or [body.lower()]
    _, known = _known(clip_text)
    missing = [p for p in parts if not p.isdigit() and not known(p)] + [p for p in parts if p.isdigit() and
                                                                        p not in clip_text]
    return [f"{tag} is not something the clip talks about"] if missing or not body else []


# ------------------------------------------------------------------ extraction
def _fragment(text: str, max_words: int = 12) -> str:
    """A long sentence becomes its most hook-like clause instead of being cut off with '...'."""
    text = text.strip().strip("“”\"")
    if len(text.split()) <= max_words:
        return text
    parts = [c for c in hk._clauses(text) if 4 <= len(c.split()) <= max_words]  # noqa: SLF001
    return max(parts, key=lambda c: hk._hookiness(c, 0.0)) if parts else text  # noqa: SLF001


def _clean_title(text: str) -> str:
    t = hk._tidy(_fragment(text), 12)  # noqa: SLF001 - shared extraction helper
    t = re.sub(r"[<>]", "", t).strip()
    if t.endswith(".") and not t.endswith("..."):
        t = t[:-1]
    return t[:TITLE_MAX].rstrip()


def _similar(a: str, b: str) -> bool:
    sa, sb = set(content_tokens(a)) or set(tokens(a)), set(content_tokens(b)) or set(tokens(b))
    return bool(sa and sb) and len(sa & sb) / len(sa | sb) >= 0.6


def _distinct(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for it in items:
        if it and len(it.split()) >= 3 and not any(_similar(it, o) for o in out):
            out.append(it)
        if len(out) >= limit:
            break
    return out


def _payoff_sentence(sents: list[str]) -> str:
    """The conclusion. A short lead-in ("The lesson is simple.") is joined with the line that delivers it."""
    for k in range(len(sents) - 1, -1, -1):
        if count_phrases(sents[k].lower(), PAYOFF_PHRASES):
            if len(sents[k].split()) <= 6 and k + 1 < len(sents):
                return f"{sents[k]} {sents[k + 1]}"
            return sents[k]
    return sents[-1] if sents else ""


def _title_score(t: str) -> float:
    s = hk._hookiness(t, 0.0)  # noqa: SLF001
    n = len(t)
    s += 1.0 if 25 <= n <= 70 else (-1.0 if n > 90 else 0.0)
    s -= 0.8 if t.endswith("...") else 0.0
    return s


def _keyword_title(kws: list[str]) -> str:
    kws = [k.capitalize() for k in kws[:3]]
    if len(kws) >= 3:
        return f"{kws[0]}, {kws[1]} and {kws[2]}"
    return " and ".join(kws)


def _join(parts: list[str], limit: int) -> str:
    out = ""
    for p in parts:
        p = clean_text(p).strip()
        if not p:
            continue
        cand = f"{out} {p}".strip()
        if len(cand) > limit:
            break
        out = cand
    return out or (clean_text(parts[0])[: limit - 3].rstrip() + "..." if parts else "")


# Words that are in the clip but say nothing about its topic, so they make poor hashtags.
WEAK_TAGS = set("""
nobody somebody everybody anybody without within part parts hour hours hard easy simple terrible faster slower fast slow
single whole thing things people way ways lot lots day days time times year years week weeks month months everything
nothing something anything really pretty enough exactly able sure kind sort place point stuff guy guys today tomorrow
tonight yesterday back front side start end still another other others different same small big large little great
good better bad worse true false right wrong okay minute minutes second seconds morning night person ones
tells thinks says makes takes gets goes knows wants needs feels looks seems keeps gives comes told said made took went
knew wanted needed felt looked seemed kept gave came started stopped asked tried called turned happened
later earlier soon everyone someone anyone almost also maybe
""".split())


def hashtags_for(clip_text: str, global_df: Counter | None = None, n_docs: int = 1, prefer: str = "") -> list[str]:
    """Topic words the clip actually uses, weighted by how specific they are to it within the video. Words that also
    appear in `prefer` (the title) rank first."""
    lead = set(content_tokens(prefer))
    kws = [k for k in keywords(clip_text, global_df, n_docs, top=HASHTAG_LIMIT * 3)
           if k.isalpha() and k not in WEAK_TAGS and not k.endswith(("ly", "est"))]
    kws.sort(key=lambda k: k not in lead)  # stable: keeps the keyword order otherwise
    tags = [f"#{k}" for k in kws]
    return [t for t in dict.fromkeys(tags) if not hashtag_problems(t, clip_text)][:HASHTAG_LIMIT]


def extract(sents: list[str], hook: str, hooks_alt: list[str], category: str,
            global_df: Counter | None = None, n_docs: int = 1) -> dict:
    """The offline package: every text is taken from the clip's sentences."""
    clip_text = " ".join(sents)
    kws = keywords(clip_text, global_df, n_docs, top=4) if clip_text else []
    questions = [s for s in sents if s.rstrip().endswith("?")]
    payoff = _payoff_sentence(sents)
    hook = hook or (sents[0] if sents else "")

    pool = [t for t in [hook, *questions, payoff, *hooks_alt, *sorted(sents, key=lambda s: -hk._hookiness(s, 0.0))]
            if t]  # noqa: SLF001
    # complete short sentences first, then the best clause of a long one; a cut-off sentence only as a last resort
    full = [t for t in pool if len(t.split()) <= 12]
    clauses = [f for f in (_fragment(t) for t in pool if len(t.split()) > 12) if len(f.split()) <= 12]
    titles = _distinct([_clean_title(t) for t in full + clauses], 3)
    if len(titles) < 3 and kws:
        titles = _distinct(titles + [_keyword_title(kws)], 3)
    if len(titles) < 3:
        titles = _distinct(titles + [_clean_title(t) for t in pool], 3)
    rec = max(range(len(titles)), key=lambda i: _title_score(titles[i])) if titles else 0

    middle = sorted(sents[1:-1], key=lambda s: -len(content_tokens(s)))
    answer = ""
    if questions:
        k = sents.index(questions[0])
        answer = sents[k + 1] if k + 1 < len(sents) else ""
    captions = _distinct([
        _join([hook, *(middle[:1] or sents[1:2])], 300),
        _join([questions[0], answer], 300) if questions else _join([payoff], 300),
        f"“{clean_text(payoff).strip()}”" if payoff and not _similar(payoff, hook) else _join(sents[-2:], 300),
        _join(sents[:3], 300),
        _join(sents[-3:], 300),
    ], 3)

    desc_parts = [hook, payoff] if payoff and not _similar(hook, payoff) else [hook]
    description = _join(desc_parts, DESCRIPTION_MAX)
    cta = CTAS["question"] if questions and category not in CTAS else CTAS.get(category, CTA_DEFAULT)
    return {
        "titles": titles, "recommended_title": rec, "captions": captions,
        "hashtags": hashtags_for(clip_text, global_df, n_docs, titles[rec] if titles else hook),
        "description": description, "cta": cta,
        "hook": clean_text(hook).strip().strip("“”\""), "hooks": [h for h in [hook, *hooks_alt] if h][:4],
    }


# ------------------------------------------------------------------ optional AI provider
def _ai_package(settings: dict, sents: list[str], category: str) -> dict:
    numbered = "\n".join(f"- {s}" for s in sents)
    prompt = (
        f"Short video clip transcript ({category or 'clip'}):\n{numbered}\n\n"
        "Write a post package for TikTok and YouTube Shorts. Use ONLY information in the transcript: no names, "
        "numbers, facts, events or claims that are not in it, and no hype words the speaker does not use. "
        "Reply with JSON: {\"titles\": [3 different titles, max 70 characters], \"recommended\": index 0-2, "
        "\"captions\": [3 different captions, max 220 characters, no hashtags], \"description\": one sentence, max "
        "150 characters, \"hook\": on-screen hook, max 12 words, \"hashtags\": [3-6 hashtags made of words the "
        "speaker says]}"
    )
    text = llm.complete(settings, prompt)
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise llm.ProviderError("model did not return JSON")
    import json

    try:
        return json.loads(m.group(0))
    except ValueError as exc:
        raise llm.ProviderError(f"invalid JSON from model: {exc}") from exc


def _merge_ai(base: dict, ai: dict, clip_text: str) -> tuple[dict, int]:
    """Keep only AI suggestions that pass the grounding check; count how many were used."""
    used = 0

    def ok(s: object, limit: int) -> str:
        s = str(s or "").strip().strip("\"")
        return s if s and len(s) <= limit and not grounding_problems(s, clip_text) else ""

    titles = [t for t in (ok(re.sub(r"[<>]", "", str(t)), TITLE_MAX) for t in (ai.get("titles") or [])[:3]) if t]
    if titles:
        merged = _distinct(titles + base["titles"], 3)
        used += sum(1 for t in merged if t in titles)
        rec = ai.get("recommended")
        rec_title = titles[rec] if isinstance(rec, int) and 0 <= rec < len(titles) else titles[0]
        base["titles"] = merged
        base["recommended_title"] = merged.index(rec_title) if rec_title in merged else 0
    caps = [c for c in (ok(c, 300) for c in (ai.get("captions") or [])[:3]) if c and "#" not in c]
    if caps:
        merged = _distinct(caps + base["captions"], 3)
        used += sum(1 for c in merged if c in caps)
        base["captions"] = merged
    for key, limit in (("description", DESCRIPTION_MAX), ("hook", 120)):
        v = ok(ai.get(key), limit)
        if v:
            base[key] = v
            used += 1
    tags = ["#" + re.sub(r"[^\w]", "", str(t)) for t in (ai.get("hashtags") or []) if re.sub(r"[^\w]", "", str(t))]
    tags = [t for t in tags if not hashtag_problems(t, clip_text)]
    if tags:
        base["hashtags"] = list(dict.fromkeys(tags + base["hashtags"]))[:HASHTAG_LIMIT]
        used += 1
    return base, used


# ------------------------------------------------------------------ public API
def generate(sents: list[str], hook: str, hooks_alt: list[str], category: str, settings: dict | None = None,
             global_df: Counter | None = None, n_docs: int = 1, use_ai: bool = True) -> dict:
    clip_text = " ".join(sents)
    pkg = extract(sents, hook, hooks_alt, category, global_df, n_docs)
    source = "Extracted from the clip's transcript"
    settings = settings or {}
    if use_ai and settings.get("ai_provider", "heuristic") in llm.PROVIDERS and sents:
        try:
            pkg, used = _merge_ai(pkg, _ai_package(settings, sents, category), clip_text)
            if used:
                source = f"{llm.provider_label(settings)}, checked against the transcript"
        except llm.ProviderError as exc:
            log.warning("post package: AI provider failed (%s); using the extracted text", exc)
    pkg["title"] = pkg["titles"][pkg["recommended_title"]] if pkg["titles"] else ""
    pkg["caption"] = pkg["captions"][0] if pkg["captions"] else ""
    pkg.update({"source": source, "generated_at": time.time(), "edited": False,
                "checks": checks(pkg, clip_text), "clip_text": clip_text})
    return pkg


def checks(pkg: dict, clip_text: str) -> dict:
    """Grounding problems per field (shown next to user-edited text; generated text has none)."""
    out = {}
    for key in ("title", "caption", "description", "hook"):
        p = grounding_problems(str(pkg.get(key) or ""), clip_text)
        if p:
            out[key] = p
    tags = [p for t in pkg.get("hashtags") or [] for p in hashtag_problems(t, clip_text)]
    if tags:
        out["hashtags"] = tags
    return out


def clip_sentences(words: list[dict], clip: dict) -> list[str]:
    """The clip's sentences from the transcript words inside its (possibly trimmed) range."""
    edit = clip.get("edit") or {}
    start, end = float(edit.get("start", clip["start"])), float(edit.get("end", clip["end"]))
    ws = edit.get("caption_words") or [w for w in words if w["end"] > start + 0.05 and w["start"] < end - 0.05]
    return [s["text"] for s in build_sentences(ws)] or ([clip["caption_text"]] if clip.get("caption_text") else [])


def for_clip(clip: dict, words: list[dict], settings: dict, use_ai: bool = True) -> dict:
    from .scoring import document_frequencies

    all_sents = build_sentences(words) if words else []
    df = document_frequencies(all_sents)
    return generate(clip_sentences(words, clip), clip.get("hook", ""), clip.get("hooks_alt") or [],
                    clip.get("category", ""), settings, df, max(1, len(all_sents)), use_ai)


def _text(v: object, limit: int) -> str:
    return str(v or "").replace("\r", "")[:limit].strip()


def _tag(t: object) -> str:
    body = re.sub(r"[^\w]", "", str(t or "").strip().lstrip("#"))
    return f"#{body}" if body else ""


def apply_edit(pkg: dict, patch: dict) -> dict:
    """Merge the user's edits. User text is saved as typed (length-limited); grounding notes are informational."""
    out = dict(pkg or {})
    for key, value in patch.items():
        if key not in EDITABLE:
            continue
        if key in ("titles", "captions"):
            limit = TITLE_MAX if key == "titles" else CAPTION_MAX
            out[key] = [_text(v, limit) for v in (value or [])][:3]
        elif key == "hashtags":
            out[key] = [t for t in dict.fromkeys(_tag(v) for v in (value or [])) if t][:15]
        elif key == "recommended_title":
            out[key] = max(0, min(len(out.get("titles") or [""]) - 1, int(value or 0)))
        elif key == "title":
            out[key] = re.sub(r"[<>]", "", _text(value, TITLE_MAX))
        elif key == "caption":
            out[key] = _text(value, CAPTION_MAX)
        elif key == "description":
            out[key] = _text(value, 5000)
        elif key == "cta":
            out[key] = _text(value, 300)
        elif key == "hook":
            out[key] = _text(value, 160)
    out["edited"] = True
    out["checks"] = checks(out, out.get("clip_text", ""))
    return out


def as_text(pkg: dict) -> str:
    """Plain-text version for exports."""
    if not pkg:
        return ""
    lines = ["POST PACKAGE (generated from the clip's transcript; review before posting)", ""]
    for i, t in enumerate(pkg.get("titles") or []):
        lines.append(f"Title option {i + 1}{' (recommended)' if i == pkg.get('recommended_title') else ''}: {t}")
    lines.append(f"Chosen title: {pkg.get('title', '')}")
    lines.append("")
    for i, c in enumerate(pkg.get("captions") or []):
        lines.append(f"Caption option {i + 1}: {c}")
    lines += ["", f"Chosen caption: {pkg.get('caption', '')}", f"Short description: {pkg.get('description', '')}",
              f"Hashtags: {' '.join(pkg.get('hashtags') or [])}", f"Call to action: {pkg.get('cta', '')}",
              f"Hook text: {pkg.get('hook', '')}"]
    return "\n".join(lines) + "\n"
