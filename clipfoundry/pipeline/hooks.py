"""Grounded hooks, titles, hashtags and categories.

Everything here is extracted from the clip's own words, so the heuristic
output can never invent facts.  LLM output is passed through `is_grounded`
before it is accepted.
"""
from __future__ import annotations

import re
from collections import Counter

from .text_utils import (CATEGORY_LEXICON, EMOTION_WORDS, HOOK_PHRASES, HOOK_WORDS, STOPWORDS, clean_text,
                         content_tokens, count_phrases, keywords, tokens)

CATEGORY_TAGS = {"Story": "storytime", "Educational": "learnontiktok", "Motivational": "motivation",
                 "Funny": "funny", "Opinion": "hottake", "Emotional": "real", "Business": "business",
                 "Highlight": "highlights", "Q&A": "qanda"}

_LEAD_JUNK = re.compile(r"^(?:(?:and|but|so|or|well|yeah|okay|ok|like|um|uh|now|anyway|right|also|then)\b[,.]?\s+)+",
                        re.I)
NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "fifteen", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million",
                "billion", "percent"}


def _trim_tail(words: list[str]) -> list[str]:
    while len(words) > 3 and words[-1].lower().strip(",;:") in STOPWORDS:
        words = words[:-1]
    return words


def _tidy(text: str, max_words: int = 14) -> str:
    text = clean_text(text)
    text = _LEAD_JUNK.sub("", text).strip(" ,;:-")
    words = text.split()
    if len(words) > max_words:
        # cut at a clause boundary when possible
        cut = max_words
        for k in range(max_words, max(4, max_words - 5), -1):
            if words[k - 1].endswith((",", ";", ":")):
                cut = k
                break
        text = " ".join(_trim_tail(words[:cut])).rstrip(",;:") + "..."
    if text:
        text = text[0].upper() + text[1:]
    return text


def _clauses(sentence: str) -> list[str]:
    parts = re.split(r"(?<=[,;:])\s+|\s+(?:but|because|and then|so)\s+", sentence)
    return [p.strip() for p in parts if len(p.split()) >= 4]


def _hookiness(text: str, position: float) -> float:
    low = text.lower()
    toks = tokens(text)
    n = len(toks)
    s = 0.0
    s += 2.0 if text.rstrip(".").endswith("?") else 0.0
    s += 1.2 * count_phrases(low, HOOK_PHRASES)
    s += 0.5 * sum(1 for t in toks if t in HOOK_WORDS)
    s += 0.4 * sum(1 for t in toks if t in EMOTION_WORDS)
    s += 0.6 if any(t.isdigit() or t in NUMBER_WORDS for t in toks) else 0.0
    s += 0.5 if "you" in toks else 0.0
    s += 1.0 if 5 <= n <= 14 else (-1.0 if n < 4 else -0.8 - 0.3 * (n - 14) / 5)
    s += 0.6 * (1.0 - position)  # early lines hook better
    return s


def heuristic_hooks(sentences: list[str]) -> tuple[str, list[str]]:
    """Pick a recommended hook + 3 alternatives, all quoted/extracted from the clip."""
    pool: list[tuple[float, str]] = []
    n = max(1, len(sentences))
    for k, s in enumerate(sentences):
        pos = k / n
        pool.append((_hookiness(s, pos), s))
        for c in _clauses(s):
            pool.append((_hookiness(c, pos) - 0.2, c))
    pool.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    picks: list[str] = []
    for _, text in pool:
        t = _tidy(text)
        key = " ".join(tokens(t))[:40]
        if not t or len(t.split()) < 3 or key in seen:
            continue
        if any(key in s or s in key for s in seen):
            continue
        seen.add(key)
        picks.append(t)
        if len(picks) >= 4:
            break
    # Stylistic variants of already grounded text (no new facts).
    if picks and len(picks) < 4:
        picks.append(f"“{picks[0].rstrip('.')}”")
    while len(picks) < 4 and sentences:
        extra = _tidy(sentences[min(len(sentences) - 1, len(picks))], 9)
        if extra in picks:
            break
        picks.append(extra)
    if not picks:
        return "", []
    return picks[0], picks[1:4]


def make_title(hook: str, kws: list[str]) -> str:
    base = hook.strip().rstrip(".").strip("“”\"")
    words = base.split()
    if len(words) > 12:
        cut = next((k for k in range(12, 5, -1) if words[k - 1].endswith((",", ";", ":"))), 12)
        base = " ".join(_trim_tail(words[:cut])).rstrip(",;:") + "..."
    if not base and kws:
        base = " / ".join(k.capitalize() for k in kws[:3])
    return base or "Untitled clip"


def categorize(text: str) -> str:
    low = text.lower()
    scores = {cat: count_phrases(low, words) for cat, words in CATEGORY_LEXICON.items()}
    if low.count("?") >= 3:
        scores["Q&A"] = low.count("?")
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 2 else "Highlight"


def hashtags(text: str, category: str, global_df: Counter | None, n_docs: int) -> list[str]:
    tags = [f"#{k}" for k in keywords(text, global_df, n_docs, top=4) if k.isalpha()]
    cat_tag = CATEGORY_TAGS.get(category)
    if cat_tag:
        tags.append(f"#{cat_tag}")
    tags.append("#shorts")
    out: list[str] = []
    for t in tags:
        if t.lower() not in [o.lower() for o in out]:
            out.append(t)
    return out[:6]


def is_grounded(hook: str, clip_text: str) -> bool:
    """Reject LLM hooks that mention numbers, names or topics absent from the clip."""
    if not hook or len(hook) > 140:
        return False
    src_low = clip_text.lower()
    src_tokens = set(tokens(clip_text))
    src_stems = {t[:5] for t in src_tokens}
    for num in re.findall(r"\d[\d,.]*", hook):
        digits = num.strip(".,")
        if digits and digits not in src_low:
            return False
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", hook)
    for k, w in enumerate(words):
        if k and w[0].isupper() and w.lower() not in STOPWORDS and w.lower() not in src_tokens:
            # A capitalised word mid-sentence is probably a name; it must come from the clip.
            if w.lower()[:5] not in src_stems:
                return False
    content = content_tokens(hook)
    if not content:
        return True
    hits = sum(1 for t in content if t in src_tokens or t[:5] in src_stems)
    return hits / len(content) >= 0.5
