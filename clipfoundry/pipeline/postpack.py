"""Post packages: what you need to publish a clip, written only from the clip's own words.

For every clip: three title options (one recommended), three caption/description options, hashtags, a short
description, a call-to-action suggestion and hook text. Titles, captions, the description, the hook and the hashtags
are extracted from the clip's transcript. The only words that are not from the clip are the fixed call-to-action
templates, which ask the viewer to do something and state nothing about the content.

`grounding_problems` checks text against the transcript: numbers, names, claims and words that are not in the clip
are reported. An AI provider's suggestions are used only when they pass that check; everything else falls back to the
extracted text. The user edits and approves the package before anything is published.

How the text looks follows the owner: what they told ClipForge AI about titles, post text and hashtags ("titles in
lower case, no emoji", "three hashtags at most") is read by brain/poststyle.py and applied to the finished package.
It changes letter case, removes emoji and hashtags and picks among the clip's own lines; it never adds a word.
"""
from __future__ import annotations

import re
import time
from collections import Counter

from .. import db
from . import hooks as hk
from . import llm
from .common import log
from .text_utils import (OPEN_LOOP_PHRASES, PAYOFF_PHRASES, STOPWORDS, build_sentences, clean_text, content_tokens,
                         count_phrases, keywords, tokens)

TITLE_MAX = 100          # YouTube's limit; TikTok has no separate title
CAPTION_MAX = 2200       # TikTok's caption limit (YouTube descriptions allow 5000 bytes)
DESCRIPTION_MAX = 160
HASHTAG_LIMIT = 5        # three to five specific hashtags do more than a long row of them (brain/knowhow.py)
ADVICE_CHARS = 600       # what a model reads of the owner's skills before it writes post text
# Hashtags that say nothing about the video. They are left out even when the speaker says the word ("this went
# viral"): a hashtag is there to say what the clip is about.
GROWTH_TAGS = {"fyp", "foryou", "foryoupage", "fy", "viral", "trending", "trend", "explore", "explorepage",
               "xyzbca", "follow", "like", "likes", "subscribe"}
# What a clip is: never a hashtag ("In this video I show you ...").
MEDIUM_TAGS = {"video", "videos", "clip", "clips", "short", "content"}
# Where a clip is posted: no hashtag, unless the clip is about the platform, which its title shows by naming it as
# its subject ("Why I quit Instagram", "YouTube Shorts or TikTok?"); "This went viral on TikTok" is not about TikTok.
PLATFORM_TAGS = {"tiktok", "youtube", "shorts", "reels", "instagram"}
GENERIC_TAGS = GROWTH_TAGS | MEDIUM_TAGS | PLATFORM_TAGS
_PLATFORM = r"(?:tik ?tok|you ?tube|shorts|reels|instagram|insta)"
_POSTED_ON = re.compile(rf"\b(?:on|to|from|for|via|in|at|across|onto)\s+(?:the\s+|my\s+)?({_PLATFORM}"
                        rf"(?:(?:\s*,\s*|\s+(?:and|or|&)\s+|\s+){_PLATFORM})*)\b")


def title_subject(title: str) -> set[str]:
    """The content words of a title, without the platforms it names only as where the clip went."""
    words = content_tokens(title)
    places = [set(content_tokens(m.group(1))) for m in _POSTED_ON.finditer(str(title or "").lower())]
    named = PLATFORM_TAGS & set(words)
    # platforms named apart ("from TikTok to YouTube", "left TikTok for YouTube") are what the title compares
    where = set().union(*places) if any(named <= p for p in places) else set()
    return {w for w in words if not (w in PLATFORM_TAGS and w in where)}


def generic_tag(word: str, lead: set[str] | frozenset[str] = frozenset()) -> bool:
    """A hashtag word that says nothing about this clip; `lead`: its title's subject words (title_subject)."""
    word = word.lstrip("#").lower()
    if word in PLATFORM_TAGS:
        return word not in lead
    return word in GROWTH_TAGS or word in MEDIUM_TAGS

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


LEANS_ON = {"if", "when", "because", "while", "although", "though", "since", "unless", "until", "whereas", "that's",
            "it's", "there's", "they're", "he's", "she's", "then", "and", "but", "or", "so", "also", "which", "that",
            "it", "this", "these", "those", "he", "she", "they", "him", "her", "them", "his", "its", "there", "same",
            "anyway", "yeah", "right", "exactly", "well", "plus"}


def stands_alone(title: str) -> bool:
    """Whether a line makes sense as a title with nothing around it: it does not open on a word that points at
    something said before ("That's the setting", "It does not") or on a clause waiting for its other half ("If you
    upload in ten eighty"). Questions are kept ("Do you know what he did?" asks; it does not point back)."""
    toks = tokens(title)
    if not toks:
        return False
    return title.rstrip().endswith("?") or toks[0] not in LEANS_ON


def _title_score(t: str) -> float:
    s = hk._hookiness(t, 0.0)  # noqa: SLF001
    n = len(t)
    s += 1.0 if 25 <= n <= 70 else (-1.0 if n > 90 else 0.0)
    s += 0.4 if 40 <= n <= 60 else 0.0   # the length that reads whole on a phone
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
    lead = title_subject(prefer)
    kws = [k for k in keywords(clip_text, global_df, n_docs, top=HASHTAG_LIMIT * 4)
           if k.isalpha() and k not in WEAK_TAGS and not generic_tag(k, lead) and not k.endswith(("ly", "est"))]
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
    # a title is read on its own: "That's the setting" or "If you upload in ten eighty" says nothing without the clip
    alone = [t for t in full + clauses if stands_alone(t)]
    titles = _distinct([_clean_title(t) for t in alone], 3)
    if len(titles) < 3 and kws:
        titles = _distinct(titles + [_keyword_title(kws)], 3)
    if len(titles) < 3:
        titles = _distinct(titles + [_clean_title(t) for t in full + clauses], 3)
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


# ------------------------------------------------------------------ three kinds of title, per destination
# Every package offers a Searchable title (the topic's words first: YouTube's own advice is to "put the most
# important words near the beginning"), a Curiosity title (a question or open loop the clip answers) and The moment
# (what happens or is said, specifically). All three come from the clip's own words. See
# docs/clipforge/CLIP_QUALITY_RESEARCH.md for which parts are platform rules and which are hypotheses.
KINDS = {"search": "Searchable", "curiosity": "Curiosity", "moment": "The moment"}
NUMBERISH = re.compile(r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|first|"
                       r"last)\b", re.I)


def topics(clip_text: str, global_df: Counter | None = None, n_docs: int = 1) -> list[str]:
    """The clip's topic words (what a Searchable title leads with): specific to the clip, not weak or generic."""
    kws = keywords(clip_text, global_df, n_docs, top=10) if clip_text else []
    return [k for k in kws if k.isalpha() and len(k) > 3 and k not in WEAK_TAGS and not generic_tag(k)
            and not k.endswith("ly")][:3]


def title_kind(title: str, kws: list[str]) -> str:
    """Which of the three kinds a title is: "curiosity" (a question or an open loop), "search" (one of the clip's
    topic words among its first four words), else "moment"."""
    low = title.lower()
    if title.rstrip().endswith("?") or count_phrases(low, OPEN_LOOP_PHRASES):
        return "curiosity"
    if kws and any(k in tokens(title)[:4] for k in kws[:3]):
        return "search"
    return "moment"


def _make_kind(kind: str, sents: list[str], kws: list[str], taken: list[str]) -> str:
    """A title of this kind from the clip's sentences that is not like one already offered ("" when none)."""
    def free(t: str) -> bool:
        return bool(t) and len(t.split()) >= 3 and not any(_similar(t, o) for o in taken) and len(t) <= TITLE_MAX \
            and stands_alone(t.split(": ", 1)[-1])

    if kind == "curiosity":
        pool = [x for x in sents if x.rstrip().endswith("?") or count_phrases(x.lower(), OPEN_LOOP_PHRASES)]
    elif kind == "moment":
        payoff = _payoff_sentence(sents)
        pool = ([payoff] if payoff else []) + [x for x in sents if NUMBERISH.search(x)]
    else:  # the topic word early: a line that already starts with it, else "Topic: the line"
        pool = []
        for k in kws[:3]:
            lines = [_clean_title(x) for x in sents if k in tokens(_fragment(x))]
            pool += [t for t in lines if k in tokens(t)[:4]]
            pool += [f"{k.capitalize()}: {t[:1].lower() + t[1:]}" for t in lines if len(t.split()) <= 10]
    for t in pool:
        t = _clean_title(t) if kind != "search" else t[:TITLE_MAX].rstrip()
        if free(t) and not t.endswith("...") and title_kind(t, kws) == kind:
            return t
    return ""


def ensure_kinds(pkg: dict, sents: list[str], kws: list[str], keep: frozenset[str] = frozenset()) -> dict:
    """Make the three options one of each kind where the clip allows it: an option whose kind repeats another's is
    replaced by one of the missing kind. The recommended title and the titles in `keep` (a model's, already checked
    against the transcript) are never replaced."""
    titles = list(pkg.get("titles") or [])
    rec = int(pkg.get("recommended_title") or 0)
    for kind in KINDS:
        have = [title_kind(t, kws) for t in titles]
        if kind in have:
            continue
        spare = [i for i, k in enumerate(have) if i != rec and titles[i] not in keep and have.count(k) > 1]
        if not spare and len(titles) < 3:
            new = _make_kind(kind, sents, kws, titles)
            if new:
                titles.append(new)
            continue
        if not spare:
            continue
        new = _make_kind(kind, sents, kws, [t for i, t in enumerate(titles) if i != spare[-1]])
        if new:
            titles[spare[-1]] = new
    pkg["titles"] = titles
    return pkg


def title_guide(pkg: dict, kws: list[str] | None = None) -> dict:
    """The options labelled by kind, and the recommended one for each destination with a short reason.
    {"options": [{"kind", "label", "text"}], "youtube": {"recommended", "why"}, "tiktok": {"recommended", "why",
    "field"}}. YouTube's pick is the package's recommended title; TikTok has no title, so its pick is the line to open
    the caption with."""
    titles = list(pkg.get("titles") or [])
    clip_text = str(pkg.get("clip_text") or "")
    kws = kws if kws is not None else topics(clip_text)
    options = [{"kind": title_kind(t, kws), "label": KINDS[title_kind(t, kws)], "text": t} for t in titles]
    if not options:
        return {"options": [], "youtube": None, "tiktok": None}
    rec = max(0, min(len(titles) - 1, int(pkg.get("recommended_title") or 0)))
    pays_off = bool(count_phrases(clip_text.lower(), PAYOFF_PHRASES))

    def why(o: dict, where: str) -> str:
        if o["kind"] == "search":
            k = next((k for k in kws if k in tokens(o["text"])[:4]), "")
            return (f"Puts the topic{f' (“{k}”)' if k else ''} first, where people searching see it"
                    + ("; YouTube advises the most important words near the beginning." if where == "youtube" else "."))
        if o["kind"] == "curiosity":
            return "Opens a question the clip answers" + (" by the end" if pays_off else "") + \
                (", which gives a reason to keep watching (TikTok says watch time counts most for many viewers)."
                 if where == "tiktok" else ", so the title's promise is kept.")
        return "Says what actually happens or is said, so the viewer gets exactly what the title promised."

    order = {"curiosity": 0, "moment": 1, "search": 2}
    tk = min(range(len(options)), key=lambda i: (order[options[i]["kind"]], i != rec))
    return {"options": options,
            "youtube": {"recommended": rec, "why": why(options[rec], "youtube"),
                        "note": f"YouTube shows the first {YOUTUBE_HASHTAGS_SHOWN} hashtags above the title."},
            "tiktok": {"recommended": tk, "why": why(options[tk], "tiktok"), "field": "the caption's first line"}}


# ------------------------------------------------------------------ the fields each platform checks
YOUTUBE_HASHTAGS_IGNORED = 60   # "more than 60 hashtags": YouTube ignores every hashtag on the video
YOUTUBE_HASHTAGS_SHOWN = 3      # "up to three hashtags ... will appear by your video title"


def field_problems(pkg: dict) -> dict:
    """What each platform would refuse or ignore in this post text, checked before anything is posted:
    {"youtube": [...], "tiktok": [...]} (empty lists: nothing). Upload-time checks (publish/youtube.py,
    publish/tiktok.py) still run; this shows the problems while the text is being written."""
    from ..publish.tiktok import caption_length

    title = str(pkg.get("title") or "")
    desc = str(pkg.get("description") or "")
    caption = str(pkg.get("caption") or "")
    tags = [str(t) for t in pkg.get("hashtags") or []]
    yt, tt = [], []
    if not title.strip():
        yt.append("YouTube needs a title.")
    if len(title) > TITLE_MAX:
        yt.append(f"The title is {len(title)} characters; YouTube allows {TITLE_MAX}.")
    if re.search(r"[<>]", title + desc):
        yt.append("YouTube does not accept < or > in the title or description.")
    if len(desc.encode("utf-8")) > 5000:
        yt.append("The description is over YouTube's 5,000 bytes.")
    if len(tags) > YOUTUBE_HASHTAGS_IGNORED:
        yt.append(f"More than {YOUTUBE_HASHTAGS_IGNORED} hashtags: YouTube would ignore all of them.")
    spaced = [t for t in tags if " " in t.strip()]
    if spaced:
        yt.append(f"Hashtags can't contain spaces: {', '.join(spaced[:3])}.")
    full = (caption + (" " + " ".join(tags) if tags else "")).strip()
    if caption_length(full) > CAPTION_MAX:
        tt.append(f"The caption with its hashtags is {caption_length(full)} characters; TikTok allows {CAPTION_MAX}.")
    dupes = [t for t in dict.fromkeys(t.lower() for t in tags) if [x.lower() for x in tags].count(t) > 1]
    if dupes:
        yt.append(f"Repeated hashtags: {', '.join(dupes[:3])}.")
    return {"youtube": yt, "tiktok": tt}


# ------------------------------------------------------------------ optional AI provider
ADVICE_ABOUT = ("titles", "post text and descriptions", "hashtags")


def advice(settings: dict) -> str:
    """What the owner's switched-on skills say about titles and post text, for a model that writes them: the
    advice lines that fit, in a small budget. The built-in craft is already in the prompt as one line
    (knowhow.principles), so the playbooks written for the chat are not repeated here. "" when no skill is about
    it. Each question is one part of the job, not the clip's words: a skill has to be about titles, post text or
    hashtags to be read, whatever the speaker talks about."""
    try:
        from ..brain import library

        ws = str(settings.get("workspace_id") or "local")
        hits, left = [], ADVICE_CHARS
        for about in ADVICE_ABOUT:
            for hit in library.search(about, ws, task="post", sources=("skill",), limit=2, budget_chars=left,
                                      settings=settings, meaning=False).hits:  # no meaning model for every clip
                if all(hit.entry.id != h.entry.id for h in hits):
                    hits.append(hit)
                    left = max(0, left - len(hit.text) - 1)
        return library.Found(hits[:2]).prompt()
    except Exception:  # noqa: BLE001 - advice is extra; the writer works without it
        log.exception("post text advice failed")
        return ""


def _ai_package(settings: dict, sents: list[str], category: str, style: dict | None = None) -> dict:
    from ..brain import knowhow, poststyle

    numbered = "\n".join(f"- {s}" for s in sents)
    read = advice(settings)
    prompt = (
        f"Short video clip transcript ({category or 'clip'}):\n{numbered}\n\n"
        "Write a post package for TikTok and YouTube Shorts. " + knowhow.principles("post") + " "
        + (read + "\n" if read else "") +
        "Use ONLY information in the transcript: no names, "
        "numbers, facts, events or claims that are not in it, and no hype words the speaker does not use. "
        + poststyle.prompt(style or {}) +
        "Reply with JSON: {\"titles\": [3 different titles, max 70 characters], \"recommended\": index 0-2, "
        "\"captions\": [3 different captions, max 220 characters, no hashtags], \"description\": one sentence, max "
        "150 characters, \"hook\": on-screen hook, max 12 words, \"hashtags\": [3-5 hashtags made of words the "
        "speaker says, about the topic, never #fyp or #viral]}"
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
    titles = base.get("titles") or []
    rec = base.get("recommended_title") or 0
    lead = title_subject(titles[rec] if 0 <= rec < len(titles) else "")
    tags = [t for t in tags if not hashtag_problems(t, clip_text) and not generic_tag(t, lead)]
    if tags:
        base["hashtags"] = list(dict.fromkeys(tags + base["hashtags"]))[:HASHTAG_LIMIT]
        used += 1
    return base, used


# ------------------------------------------------------------------ public API
def generate(sents: list[str], hook: str, hooks_alt: list[str], category: str, settings: dict | None = None,
             global_df: Counter | None = None, n_docs: int = 1, use_ai: bool = True) -> dict:
    from ..brain import poststyle

    clip_text = " ".join(sents)
    pkg = extract(sents, hook, hooks_alt, category, global_df, n_docs)
    source = "Extracted from the clip's transcript"
    settings = settings or {}
    style = poststyle.for_settings(settings)
    extracted = set(pkg["titles"])
    if use_ai and settings.get("ai_provider", "heuristic") in llm.PROVIDERS and sents:
        try:
            pkg, used = _merge_ai(pkg, _ai_package(settings, sents, category, style), clip_text)
            if used:
                source = f"{llm.provider_label(settings)}, checked against the transcript"
        except llm.ProviderError as exc:
            log.warning("post package: AI provider failed (%s); using the extracted text", exc)
    kws = topics(clip_text, global_df, n_docs)
    pkg = ensure_kinds(pkg, sents, kws, frozenset(t for t in pkg["titles"] if t not in extracted))  # a model's stay
    if style:
        pkg = poststyle.dress(pkg, style)   # the owner's way: case, emoji, hashtags; never a new word
        source += " · " + poststyle.note(style)
        pkg["brain"] = {"rules": list(style.get("lines") or []), "memories": list(style.get("ids") or [])}
    pkg["title"] = pkg["titles"][pkg["recommended_title"]] if pkg["titles"] else ""
    pkg["caption"] = pkg["captions"][0] if pkg["captions"] else ""
    pkg.update({"source": source, "generated_at": time.time(), "edited": False,
                "checks": checks(pkg, clip_text), "clip_text": clip_text})
    pkg["guide"] = title_guide(pkg, kws)
    pkg["limits"] = field_problems(pkg)
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

    from ..brain import poststyle

    all_sents = build_sentences(words) if words else []
    df = document_frequencies(all_sents)
    if "post_style" not in settings:  # a clip written again on its own: read what the Brain says for its video
        project = db.get_project(str(clip.get("project_id") or "")) or {}
        ws = str(project.get("workspace_id") or "local")
        settings = {**settings, "workspace_id": ws, "post_style": poststyle.build(ws, str(project.get("id") or ""))}
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
    out["guide"] = title_guide(out)
    out["limits"] = field_problems(out)
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
