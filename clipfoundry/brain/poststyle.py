"""How the owner wants titles, post text and hashtags to look, read from their Brain.

pipeline/postpack.py and Autopilot's packaging write every title, post text and hashtag from the words said in the
clip. What the owner told ClipForge AI about how that text should look ("titles in lower case, no emoji", "three
hashtags at most", "don't ask people to follow") was remembered but only the chat read it. This module reads those
memories, once per run, into a small fixed set of choices and applies them to the finished text.

It never adds a word. It changes the letter case, takes emoji and hashtags away, prefers one of the clip's own
lines over another and can leave the call to action out. So the rule that post text comes from the clip holds
whatever a memory says, and a rule this module does not know changes nothing.

Only the owner's own words count (memories they said): how a post is worded is their taste, and imported advice
already reaches the writers as know-how (brain/library.py). "Captions" alone means the words on the video, which
have their own settings, so a rule changes the written post text only when it names the post text.
"""
from __future__ import annotations

import re

from ..pipeline.common import log

TITLE_SHORT = 50                 # "short titles": the middle of what reads whole on a phone (brain/knowhow.py)
TITLE_CHARS = (20, 100)          # a rule outside these is a slip of the pen, not a wish
TITLE_WORDS = (3, 15)
TAGS_MOST = 10
FEWER_TAGS = 3
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10}
_NUM = r"(\d{1,3}|" + "|".join(NUMBERS) + ")"

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
_THING = (r"(?:the |any |my )?(?:hash ?tags?|emojis?|emoticons?|call[- ]to[- ]actions?|ctas?|titles?|post text|"
          r"descriptions?)")
# "no emoji but hashtags are fine": a "but" before the next thing starts a part of its own
_PART = re.compile(r",\s*|\s+(?:and|but)\s+(?=(?:no|never|don'?t|do not|without|always|use|add|keep|make|write)\b)"
                   rf"|\s+but\s+(?={_THING}\b)")
# "isn't", "aren't", "didn't" describe ("my titles aren't getting clicks", "why didn't you add hashtags?"): not a rule
_NO_WORDS = (r"no|not|never|cannot|(?:do|does|should|must|ca|wo|would|could)n'?t|do not|without|"
             r"stop|avoid|skip|drop|leave out|hate|zero")
_NEG = re.compile(rf"\b({_NO_WORDS})\b(?!\s+go wrong)")   # "you can't go wrong with emoji" is a yes
# "don't forget the hashtags", "never miss a chance to add hashtags": after a "no", these say the opposite
_UNDO = re.compile(r"\b(forget\w*|forgot\w*|miss\w*|lose)\b")
# ... and so do these, which on their own leave something out ("skip the hashtags", "never skip the emoji")
_TURN = re.compile(r"\b(skip\w*|drop\w*|leave out|stop|avoid)\b")
# A "no" reaches back only within its own instruction: "titles shouldn't be too long and should have an emoji",
# "my titles aren't getting clicks so make them questions"; and only over the last few words before the thing.
_NEW_ORDER = re.compile(r"\b(?:so|because|since|if|unless|as long as|then|and (?:should|make|keep|use|add|always|"
                        r"put))\b")
_NO_REACH = 8
# what the owner allows is not banned by the list before it ("no emoji in titles, hashtags welcome")
_OK = re.compile(r"\b(welcome|fine|ok(?:ay)?|good|great|allowed|yes|keep|want)\b")
_TITLE = re.compile(r"\btitles?\b")
_TEXT = re.compile(r"\b(post texts?|descriptions?|post captions?|written captions?|caption under)\b")
# what else a part of a sentence can be about: then a title rule needs the part to name titles itself
# ("for every video", "on my clips" only says where the rule holds: "titles, lower case for every video")
_ELSEWHERE = re.compile(r"\b(thumbnails?|on[- ]screen|captions?|subtitles?|hooks?|overlays?|"
                        r"text on (?:the )?(?:video|screen))\b|(?<!\bfor )(?<!\bfor every )(?<!\bfor each )"
                        r"(?<!\bfor all )(?<!\bfor any )(?<!\bfor my )(?<!\bfor the )(?<!\bfor all my )"
                        r"(?<!\bfor every single )(?<!\bfor all future )\b(clips?|videos?)\b")
_LOWER = re.compile(r"\b(lower[- ]?case|all lower|small letters)\b")
_UPPER = re.compile(r"\b(all[- ]?caps|upper[- ]?case|all capitals|in (?:all |big |block )?(?:capital letters|capitals|"
                    r"caps))\b")
# "only the first letter in capital letters", "names in capitals": some capitals, not an all-caps rule
_SOME_CAPITALS = re.compile(r"\b(first (?:letters?|words?)|names?|initials|acronyms?)\b")
# bare "capitals" is about shouting only when it is refused ("no capitals"); "keep their capitals" is not a rule
_CAPITALS = re.compile(r"\b(capital letters|capitals)\b")
_EACH = re.compile(r"\b(title case|capitali[sz]e (each|every) word|every word capitali[sz]ed|"
                   r"capital letters? (?:at the start of|for|on) (?:each|every) word)\b")
_EMOJI_WORD = re.compile(r"\b(emojis?|emoticons?|smileys?)\b")
_TAG = r"hash ?tags?"
_TAG_WORD = re.compile(rf"\b{_TAG}\b")
_TAG_RANGE = re.compile(rf"\b{_NUM}\s*(?:-|–|to|or)\s*{_NUM}\s+(?:\w+\s+)?{_TAG}\b")
_TAG_COUNT = re.compile(rf"\b(at least|minimum(?: of)?|min)?\s*{_NUM}\s+(?:\w+\s+)?{_TAG}\b")
_FEWER = re.compile(rf"\b(fewer|less|few)\s+{_TAG}\b")
_CHARS = re.compile(rf"\b(under|below|less than|shorter than|at most|max(?:imum)?(?: of)?|no longer than|"
                    rf"no more than|not more than|up to|within)\s+{_NUM}\s*(characters|chars|letters|words)\b")
_SHORT = re.compile(r"\bshort(er)?\b")
_QUESTION = re.compile(r"\bquestions?\b")
_NEXT = re.compile(rf"\s*(?:or |and |nor )?(?:any )?(?:emojis?|emoticons?|{_TAG}|capitals|"
                   r"call[- ]to[- ]actions?|ctas?)\b")
_CTA = re.compile(r"\b(call[- ]to[- ]actions?|ctas?|follow for more|"
                  r"ask(?:ing)? (?:people|viewers|them|anyone|everyone|the viewer|for)\b[^.]*?"
                  r"\b(?:follows?|subscribe|subscribers|likes?|comments?|share)\b)")
# Emoji and the marks that only draw one (a skin tone, the selector after a heart, a joiner between two emoji).
# The joiner on its own stays: some languages write with it.
_EMOJI = re.compile("(?:[\U0001F000-\U0001FAFF☀-➿⌚-⏿⭐⭕‼⁉]|[#*0-9]️?⃣)"
                    "(?:[️‍\U0001F3FB-\U0001F3FF]|[\U0001F000-\U0001FAFF☀-➿])*")

EMPTY: dict = {}


def _number(word: str) -> int:
    return NUMBERS[word] if word in NUMBERS else int(word)


def _negated(part: str, at: int, carried: bool) -> bool:
    """A "no" before the words in the same part of the sentence, or handed on by a list ("no hashtags, emoji").
    After a "no", forget, miss, skip or drop says the opposite ("don't forget the hashtags", "never miss a chance to
    add hashtags"); "no, no hashtags" is one "no"."""
    before = part[:at]
    cut = [m.end() for m in _NEW_ORDER.finditer(before)]
    before = before[cut[-1]:] if cut else before
    words = list(re.finditer(r"\S+", before))
    before = before[words[-_NO_REACH].start():] if len(words) > _NO_REACH else before
    no, last = False, None   # `last`: where the last plain "no" ended
    for m in re.finditer(rf"\b(?:{_NO_WORDS}|forget\w*|forgot\w*|miss\w*|lose|skip\w*|drop\w*|leave out)\b"
                         r"(?!\s+go wrong)", before):
        word = m.group(0)
        if _UNDO.fullmatch(word):
            no = False           # "don't forget": the thing is wanted; "forget it" alone is no rule
            last = None
        elif _TURN.fullmatch(word):
            no = not no          # "never skip the emoji" wants it, "skip the hashtags" leaves them out
            last = None
        elif last is not None and not before[last:m.start()].strip(" ,!"):
            last = m.end()       # "no, no hashtags": said twice, meant once
        else:
            no, last = not no, m.end()
    return no or carried


# "no generic hashtags", "don't use the same hashtags on every clip", "no hashtags like #fyp": a rule about which
# hashtags, not about how many; "no hashtags in titles" says where (unless the post text is named too)
_TAG_WHICH = re.compile(rf"\b(?:generic|same|similar|repeated|irrelevant|random|spammy|banned|broad|big|popular|"
                        rf"trending)\s+(?:\w+\s+)?{_TAG}\b|\b{_TAG}\s+(?:like|such as|that(?! much)|which|"
                        rf"from (?!now\b|today\b|here\b|then\b|on\b))|#\w")
# "don't use hashtags that much", "too many hashtags": fewer of them, not none
_TAGS_MUCH = re.compile(rf"\b{_TAG}\s+(?:that|so) much\b")
_TOO_MANY = re.compile(rf"\btoo many\s+(?:\w+\s+)?{_TAG}\b|\b{_TAG}\s+too much\b")
_TAG_WHERE = re.compile(rf"\b{_TAG}\s+(?:\w+\s+)?in (?:the |my |a |your )?titles?\b")


def read(text: str) -> dict:
    """The choices one note makes. A sentence must name what it is about (titles, the post text, hashtags, emoji
    or the call to action); a "no" counts only inside its own part of the sentence."""
    out: dict = {}
    for sentence in _SENTENCE.split(str(text or "").lower().replace("’", "'")):
        said_title, said_text = bool(_TITLE.search(sentence)), bool(_TEXT.search(sentence))
        was_no = False
        for part in _PART.split(sentence):
            if not part or not part.strip():
                continue
            # "no hashtags, emoji or links": a part that starts with the next thing goes on with the list, unless
            # it allows it ("no emoji in titles, hashtags welcome")
            carried = was_no and not _NEG.search(part) and bool(_NEXT.match(part)) and not _OK.search(part)
            was_no = bool(_NEG.search(part)) or carried
            # what this part is about: its own words first ("thumbnail text in capitals, title in lower case")
            on_title, on_text = bool(_TITLE.search(part)), bool(_TEXT.search(part))
            if not (on_title or on_text or _ELSEWHERE.search(part)):
                on_title, on_text = said_title, said_text
            for rx, yes, no in ((_LOWER, "lower", None), (_EACH, "title", None), (_UPPER, "upper", "sentence"),
                                (_CAPITALS, None, "lower")):
                m = rx.search(part)
                if not m or not (on_title or on_text):
                    continue
                each = _EACH.search(part)
                if rx is _CAPITALS and each and each.start() <= m.start() < each.end():
                    continue     # "no capital letters at the start of each word" refuses Title Case, not capitals
                if rx is _UPPER and _SOME_CAPITALS.search(part[:m.start()]):
                    continue
                value = no if _negated(part, m.start(), carried) else yes
                if not value:
                    continue
                if on_title:
                    out.setdefault("title_case", value)
                if on_text and value == "lower":
                    out.setdefault("text_case", value)
                break
            m = _EMOJI_WORD.search(part)
            if m and _negated(part, m.start(), carried):
                out.setdefault("emoji", False)
            m = _TAG_WORD.search(part)
            if m:
                span, count, least = _TAG_RANGE.search(part), _TAG_COUNT.search(part), False
                if span:
                    n = max(_number(span.group(1)), _number(span.group(2)))
                elif count:
                    n, least = _number(count.group(2)), bool(count.group(1))
                elif _FEWER.search(part) or _TOO_MANY.search(part):
                    n = FEWER_TAGS
                elif _TAGS_MUCH.search(part):
                    n = FEWER_TAGS if _negated(part, m.start(), carried) else None
                elif _TAG_WHICH.search(part) or (_TAG_WHERE.search(part) and not _TEXT.search(part)):
                    n = None
                else:
                    n = 0 if _negated(part, m.start(), carried) else None
                if n is not None and not least:   # "at least 5" cannot be promised: the clip may not say five things
                    out.setdefault("tags", max(0, min(TAGS_MOST, n)))
            m = _CTA.search(part)
            if m and _negated(part, m.start(), carried):
                out.setdefault("cta", False)
            if on_title:
                m = _CHARS.search(part)
                if m:
                    n, words = _number(m.group(2)), m.group(3) == "words"
                    lo, hi = TITLE_WORDS if words else TITLE_CHARS
                    if lo <= n <= hi:
                        out.setdefault("title_words" if words else "title_max", n)
                else:
                    m = _SHORT.search(part)
                    if m and not _negated(part, m.start(), carried):
                        out.setdefault("title_max", TITLE_SHORT)
                m = _QUESTION.search(part)
                if m:
                    out.setdefault("question", -1 if _negated(part, m.start(), carried) else 1)
    return out


def lines(style: dict) -> list[str]:
    """The choices in plain words, for the owner (the post text's source line) and for a model that writes."""
    out = []
    case = {"lower": "titles in lower case", "upper": "titles in capitals",
            "title": "every word of a title capitalised", "sentence": "no all-caps titles"}.get(style.get("title_case"))
    if case:
        out.append(case)
    if style.get("text_case") == "lower":
        out.append("post text in lower case")
    if style.get("title_max"):
        out.append(f"titles of {style['title_max']} characters or fewer where the clip has such a line")
    if style.get("title_words"):
        out.append(f"titles of {style['title_words']} words or fewer where the clip has such a line")
    if style.get("question"):
        out.append("a question as the title where the clip asks one" if style["question"] > 0 else
                   "no question as the title where the clip has another line")
    if style.get("emoji") is False:
        out.append("no emoji")
    if style.get("tags") is not None:
        n = style["tags"]
        out.append("no hashtags" if n == 0 else f"at most {n} hashtag{'s' if n != 1 else ''}")
    if style.get("cta") is False:
        out.append("no call to action")
    return out


def _order(row: dict) -> tuple:
    scope = str(row.get("scope") or "all")
    return (0 if scope.startswith("project:") else 1 if scope != "all" else 2, 0 if row.get("kind") == "rule" else 1)


def build(ws: str, project_id: str = "", platform: str = "") -> dict:
    """The owner's choices for post text that apply here: {} when the Brain says nothing about it. A note for this
    video wins over a general one, a rule over a remark, a newer one over an older one. Never raises: the writers
    work the same without it."""
    try:
        from . import memories

        rows = [r for r in memories.candidates(str(ws or "local"), project_id=project_id, platform=platform,
                                               mode="clips", kinds=memories.LASTING)
                if (r.get("source") or "said") == "said"]
        style: dict = {}
        ids: list[str] = []
        for row in sorted(rows, key=_order):      # stable: candidates() lists the newest first
            new = {k: v for k, v in read(row["text"]).items() if k not in style}
            if new:
                style.update(new)
                ids.append(row["id"])
        return {**style, "ids": ids, "lines": lines(style)} if style else {}
    except Exception:  # noqa: BLE001
        log.exception("reading the Brain's post text rules failed")
        return {}


def for_settings(settings: dict | None) -> dict:
    """The style a run already read (process._options keeps it in the options), or a fresh read for the place the
    settings name."""
    settings = settings or {}
    if isinstance(settings.get("post_style"), dict):
        return settings["post_style"]
    return build(str(settings.get("workspace_id") or "local"))


def _no_emoji(text: str) -> str:
    out = _EMOJI.sub("", text)
    if out == text:
        return text
    return re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()


def _cased(text: str, case: str | None) -> str:
    if case == "lower":
        return text.lower()
    if case == "upper":
        return text.upper()
    if case == "title":
        return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))
    if case == "sentence":
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 4 and sum(c.isupper() for c in letters) > 0.6 * len(letters):
            return text[:1].upper() + text[1:].lower()
    return text


def title(style: dict, text: str) -> str:
    text = str(text or "")
    if not style:
        return text
    return _cased(_no_emoji(text) if style.get("emoji") is False else text, style.get("title_case"))


def text(style: dict, body: str) -> str:
    body = str(body or "")
    if not style:
        return body
    return _cased(_no_emoji(body) if style.get("emoji") is False else body, style.get("text_case"))


def tags(style: dict, hashtags: list[str]) -> list[str]:
    if not style or style.get("tags") is None:
        return list(hashtags or [])
    return list(hashtags or [])[:style["tags"]]


def miss(style: dict, headline: str) -> float:
    """How far a title is from what the owner asked for (0 = it fits). Length weighs more than the question wish:
    a too-long title breaks a rule, a missing question only a preference."""
    if not style:
        return 0.0
    out = 0.0
    if style.get("title_max") and len(headline) > style["title_max"]:
        out += 1 + (len(headline) - style["title_max"]) / 100
    if style.get("title_words") and len(headline.split()) > style["title_words"]:
        out += 1 + (len(headline.split()) - style["title_words"]) / 20
    if style.get("question") and (style["question"] > 0) != headline.rstrip().endswith("?"):
        out += 0.5
    return out


def prefer(style: dict, titles: list[str], recommended: int) -> int:
    """Which of the clip's title options to recommend: the writer's own pick when it fits the owner's rules as well
    as any other, otherwise the option that fits best."""
    if not titles:
        return 0
    recommended = recommended if 0 <= recommended < len(titles) else 0
    if not style:
        return recommended
    best = min(range(len(titles)), key=lambda i: (miss(style, titles[i]), i))
    return recommended if miss(style, titles[recommended]) <= miss(style, titles[best]) else best


def dress(pkg: dict, style: dict) -> dict:
    """A written post package, the owner's way."""
    if not style:
        return pkg
    pkg["titles"] = [title(style, t) for t in pkg.get("titles") or []]
    pkg["recommended_title"] = prefer(style, pkg["titles"], int(pkg.get("recommended_title") or 0))
    pkg["captions"] = [text(style, c) for c in pkg.get("captions") or []]
    pkg["description"] = text(style, pkg.get("description") or "")
    pkg["hashtags"] = tags(style, pkg.get("hashtags") or [])
    if style.get("emoji") is False:
        pkg["hook"] = _no_emoji(str(pkg.get("hook") or ""))
        pkg["hooks"] = [_no_emoji(str(h)) for h in pkg.get("hooks") or []]
    if style.get("cta") is False:
        pkg["cta"] = ""
    return pkg


def note(style: dict) -> str:
    """For the line under the post text that says where it came from."""
    return ("your Brain: " + ", ".join(style["lines"])) if style and style.get("lines") else ""


def prompt(style: dict) -> str:
    """For a model that writes post text: the choices in ClipForge's own words, never the owner's notes."""
    if not style or not style.get("lines"):
        return ""
    return "The owner's rules for this text, which win over everything above: " + "; ".join(style["lines"]) + ". "
