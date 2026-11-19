"""How the owner's Brain steers which moments become clips. No model is needed and nothing leaves the computer.

What is read: the memories that apply to the video (what the owner said, and what was imported, such as the viral
lessons and examples) and the advice lines of switched-on skills for clips. Each line is read into a small fixed
vocabulary only: kinds of moment to look for or pass over, subjects the owner wants or does not want, which parts
of the score matter more, and how long a clip should be. A line that says none of that is left alone, and nothing
in a line is ever executed.

What it does: a bounded nudge on a candidate's score (never more than LIMIT either way), a warning on a moment the
owner said to avoid, clip lengths where the owner said one, and the reason, in words, on the clip.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..pipeline.common import log
from ..pipeline.text_utils import STOPWORDS, content_tokens
from . import knowhow
from .library import skill_lines, stem

UNIT = 0.02           # raw score for one kind of moment, clearly shown and fully weighted (3-4 points mid-scale)
LIMIT = 0.045         # the whole nudge on one candidate, either way: as much as one warning
MIN_WEIGHT = 0.2      # below this a kind is hearsay: one skill line, or one example
MIN_SHOWN = 0.34      # how clearly a candidate must show a kind before the Brain speaks about it
AVOID_SHOWN = 0.5     # ... and before an owner's "never" becomes a warning on the clip
MAX_BY = 3            # sources kept per kind, for the reason shown on the clip
MAX_TOPICS = 12
SHORTEST, LONGEST = 5.0, 180.0  # the bounds Settings keeps for clip lengths
# How much one line counts. What the owner said outweighs what was imported, which outweighs a skill's advice; one
# example is weak, and a pattern across several examples adds up.
WEIGHT = {"rule": 1.0, "said": 0.7, "did": 0.4, "guessed": 0.25, "lesson": 0.5, "example": 0.2, "skill": 0.35,
          "results": 0.45, "results_strong": 0.65}  # results: what the owner's own posted clips showed (lessons.py)
SKILL_MODES = ("highlights", "full_stories")


@dataclass(frozen=True)
class Kind:
    """A kind of moment: the words a Brain line uses for it, and the words in a clip that show it."""
    id: str
    label: str
    names: str
    cues: str = ""
    need: float = 2.0


KINDS = (
    Kind("funny", "a funny moment",
         r"funny|funnier|funniest|humou?r\w*|jokes?|laugh\w*|comedy|comedic|hilarious|punch ?lines?",
         r"laugh\w*|lol|lmao|ha(?:ha)+|hilarious|funny|jok(?:e|es|ing)|kidding|cracking up|i'm dead|i can't"),
    Kind("reaction", "a big reaction",
         r"reactions?|reacts?|reacting|hype\w*|freak\w* out|scream\w*|rag(?:e|es|ing)",
         r"oh my god|oh my gosh|omg|no way|what the|wait wait|let's go+|holy|are you kidding|what is that|oh no+|"
         r"no+ no+|bro+|yo+|dude|what just happened|are you serious|i can't believe"),
    Kind("emotional", "an emotional moment",
         r"emotion\w*|vulnerab\w*|heartfelt|touching|personal stor\w+|honest\w*|sad|tears?|cry\w*|cries",
         r"cr(?:y|ied|ying)|tears|scared|afraid|heartbroken|passed away|died|depress\w*|anxiety|proud|grateful|"
         r"ashamed|lonely|to be honest|honestly|struggl\w*|hurt|i miss\w*|i lost"),
    Kind("story", "a complete story", r"stor(?:y|ies)|storytelling|narratives?|micro-arc|anecdotes?"),
    Kind("teaching", "a clear tip or lesson",
         r"tips?|advice|lessons?|educational|how[- ]to|tutorials?|insights?|takeaways?|actionable",
         r"how to|the reason|here's why|here is why|the trick|the secret|the key|you should|you need to|step one|"
         r"the mistake|the lesson|what i learned|pro tip|the rule|the best way"),
    Kind("question", "an open question", r"questions?(?! \d)|curiosity|open loops?|cliff ?hangers?|myster\w+"),
    Kind("friction", "a disagreement or hot take",
         r"controvers\w*|debates?|hot takes?|disagree\w*|friction|conflicts?|arguments?|argu(?:e|es|ing)|"
         r"counter[- ]?intuitive|contrarian|unpopular|drama|spicy|bold claims?",
         r"unpopular opinion|hot take|i disagree|that's wrong|you're wrong|nobody talks|everyone thinks|"
         r"the truth is|is a lie|myth|overrated|but here's the thing|controversial|i don't agree|that's not true"),
    Kind("surprise", "a surprise or reveal",
         r"surpris\w*|reveals?|plot twists?|twists?|unexpected|shock\w*",
         r"turns out|turned out|suddenly|plot twist|didn't expect|never thought|out of nowhere|shocked|surprised|"
         r"unexpected|guess what|you won't believe|i found out"),
    Kind("win", "a win or clutch play",
         r"wins?|clutch\w*|victor\w+|kills?|aces?|highlight plays?|big plays?|insane plays?|skill plays?",
         r"clutch\w*|let's go+|we won|i won|victory|gg|ace|headshot|one shot|first try|new record|world record|"
         r"got him|got them|got 'em"),
    Kind("fail", "a fail or scare",
         r"(?:epic|funny|gaming|game|stream) fails?|fail (?:clips?|moments?|compilations?)|"
         r"(?<!hook )fails(?= (?:clips?|moments?|and|or|compilations?)|[,.;]|$)|deaths?|bloopers?|jump ?scares?|"
         r"scares?|rage ?quits?|chok(?:e|es|ing)|wipe ?outs?",
         r"i'm dead|i died|we died|no+ no+|what happened|how did i|i fell|jump ?scare|scared me|i choked|we lost|"
         r"i lost|rage|bugged|glitch\w*"),
    Kind("quotable", "a short line people repeat",
         r"quot\w+|one[- ]liners?|sayable|catch ?phrases?|sound ?bites?|punchy|memorable lines?"),
    Kind("numbers", "specific numbers", r"numbers?|stats?|statistics|data|money|figures|dollars?|specifics?"),
    Kind("swearing", "swearing",
         r"swear\w*|curs(?:e|es|ing)|cuss\w*|profan\w*|explicit language|bad words?|bad language",
         r"fuck\w*|shit\w*|bitch\w*|asshole\w*|damn|goddamn|bastard\w*|dick\w*|piss\w*|crap", 1.0),
    Kind("promo", "an intro, outro or ad read",
         r"intros?|outros?|sponsor\w*|ads?|ad reads?|promo\w*|self[- ]promo\w*|plugs?|shout ?outs?|housekeeping|"
         r"greetings?",
         r"sponsor\w*|use code|link in|subscribe|welcome back|thanks for watching|patreon|merch|check out my", 1.0),
    Kind("smalltalk", "small talk",
         r"small ?talk|banter|chit[- ]?chat|rambl\w*|dead air|tangents?|consensus|polite|pleasantries"),
)
BY_ID = {k.id: k for k in KINDS}
_NAMES = {k.id: re.compile(rf"\b(?:{k.names})\b") for k in KINDS}
_CUES = {k.id: re.compile(rf"\b(?:{k.cues})\b") for k in KINDS if k.cues}
# "Family friendly" names no kind of moment, yet it says one thing about picking: no swearing.
_CLEAN = re.compile(r"\b(?:family[- ]friendly|kid[- ]friendly|child[- ]friendly|keep it clean|clean language|sfw)\b")

_QUOTED = re.compile(r"[\"“][^\"”]{0,240}[\"”]")  # an example's quoted words are not advice
_CLAUSE = re.compile(r"(?<=[.;!?])\s+|\s+but\s+|\n+")
# "friction over consensus", "funny moments, not sad ones": what follows is the side passed over
_VERSUS = re.compile(r"(?<!pass)\s+over\s+(?!\d)|\s+(?:instead of|rather than)\s+|,\s*(?:and\s+)?not\s+")
_VERSUS_REACH = 30  # how far into the passed-over side a kind still belongs to it
_NO = (r"never|avoid\w*|don'?t|do not|doesn'?t|no|not|without|skip\w*|less|fewer|hate\w*|dislike\w*|exclud\w*|"
       r"ban|banned|reject\w*|steer clear|stay away|leave out|pass over|bur(?:y|ies|ying)|"
       r"hid(?:e|es|ing)(?!\s+behind)|forget(?:s|ting)?")
_NEG = re.compile(rf"\b(?:{_NO})\b")
# "banter does not provoke debate": the kind after such a verb is what is missing, not what to pass over
_CAUSE = re.compile(r"\b(?:provok\w*|caus\w*|creat\w*|spark\w*|start\w*|trigger\w*|draws?|drew|driv\w*|earn\w*|"
                    r"gets?|bring\w*|leads? to)\b")
# Nobody's advice is to look for these; only the owner's own words can ask for them.
UNWANTED = ("smalltalk", "promo", "swearing")
# an owner's own verbs for leaving something out; in imported advice "cut" is also how a clip is made
_NEG_OWNER = re.compile(rf"\b(?:{_NO}|drop\w*|remov\w*|trim\w*|stop\w*|(?:cut|cuts|cutting)"
                        r"(?!\s+(?:more|clips?|shorts?|highlights?|out (?:clips?|shorts?|more))\b))\b")
_PICK = re.compile(r"\b(?:clips?|clipping|clipped|moments?|pick\w*|choos\w*|chose|highlights?|excerpts?|segments?|"
                   r"select\w*|shorts)\b")
_PREFER = re.compile(r"\b(?:like|likes|love|loves|want|wants|prefer\w*|favou?r\w*|more|best|always|do well|"
                     r"does well|perform\w*|go(?:es)? viral|look for|find|prioriti[sz]e\w*|focus\w*|audience|"
                     r"viewers|fans|followers|only)\b")
# what an owner's line needs, besides a kind of moment, to be about picking: a liking, or a plain "leave it out"
_LEAVE_OUT = re.compile(r"\b(?:hate\w*|dislike\w*|avoid\w*|skip\w*|never|cut|drop\w*|remov\w*|ban|leave out|"
                        r"pass over|no more|stop\w*|without)\b")
_EDITING = re.compile(r"\b(?:music|songs?|captions?|subtitles?|fonts?|colou?rs?|zoom\w*|transitions?|emoji\w*|"
                      r"titles?|hashtags?|thumbnails?|volume|logos?|watermarks?|descriptions?|post text|posting|"
                      r"upload\w*|schedul\w*|voice-?overs?)\b")
# An imported memory's tags say what it is about: these subjects are for other parts of the app, unless the memory
# is also tagged as being about picking.
_OTHER_TAGS = frozenset("titles title captions caption posting rights music packaging series style sound timing "
                        "animated voice-over thumbnails hashtags description".split())
_PICK_TAGS = frozenset(("clip picking", "picking", "moments", "highlights"))
_PICK_SKILL = re.compile(r"\b(?:clip picking|clip selection|choosing clips|picking clips|clip viability|"
                         r"what to clip|finding clips)\b", re.I)
_ABOUT = re.compile(r"\b(?:about|on|where|when|with|mention\w*|featur\w*|cover\w*|show\w*)\s+(.+)")
_TOPIC_STOP = frozenset("""talk talks talking say says said saying speak speaks speaking mention discuss discussing
clip clips moment moments video videos part parts thing things stuff time times people someone something anything
everything channel content viewers audience""".split())

# ------------------------------------------------------------------ clip lengths the owner asked for
_NUM = r"(\d{1,3}(?:\.\d)?)"
_UNIT = r"\s*-?\s*(seconds?|secs?|s|minutes?|mins?|m)\b"
_SPAN = re.compile(rf"{_NUM}(?:{_UNIT})?\s*(?:-|–|to|and)\s*{_NUM}{_UNIT}")
_AT_LEAST = re.compile(rf"(?:at least|no shorter than|not shorter than|minimum(?: of)?|min|longer than|more than|"
                       rf"over|above)\s+{_NUM}{_UNIT}")
_AT_MOST = re.compile(rf"(?:at most|no longer than|not longer than|maximum(?: of)?|max|under|shorter than|"
                      rf"less than|below|up to|within)\s+{_NUM}{_UNIT}")
_ABOUT_LONG = re.compile(rf"(?:about|around|roughly|approximately|ideally|~)\s*{_NUM}{_UNIT}")
_BARE_LONG = re.compile(rf"{_NUM}{_UNIT}")
_LONGER = re.compile(r"\b(?:longer|too short|so short|not (?:so|as|that) short|more length)\b")
_SHORTER = re.compile(r"\b(?:shorter|too long|so long|not (?:so|as|that) long)\b")
_LENGTH_OF_CLIPS = re.compile(r"\bclips?\b")
# a length said about something else: an intro, a pause, a whole video, a story (stories have their own cap)
_OTHER_LENGTH = re.compile(r"\b(?:intros?|outros?|hooks?|captions?|titles?|pauses?|silences?|gaps?|full videos?|"
                           r"long videos?|whole videos?|stor(?:y|ies)|live ?streams?|songs?|music)\b")
_WORD_NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "ten": "10", "fifteen": "15",
                 "twenty": "20", "thirty": "30", "forty": "40", "forty-five": "45", "fifty": "50", "sixty": "60",
                 "ninety": "90"}
LONGER, SHORTER = 1.3, 0.75  # "make the clips longer" with no number
# "no more than 60 seconds", "I don't want my clips to be longer than 30 seconds": a "no" before a bound turns it
# around, when only such words stand between them ("clips that are not boring and under 60 seconds" does not)
_LEN_NEG = re.compile(r"\b(?:no|not|never|cannot|(?:do|does|did|is|are|was|were|should|must|ca|wo|would|could)n'?t|"
                      r"do not)(?:\s+(?:be|make|let|get|want|wants|clips?|shorts?|videos?|a|an|any|my|them|they|it|"
                      r"its|to|should|ever|you|i|me|of|the|that|are|is|have|has|been|being|please|one|ones|all|single|"
                      r"these|those|do|does|will|would|can|could|really|actually))*\s*$")
_FLIP = {"min": "max", "max": "min"}
_BARE_BOUND = re.compile(r"^(?:longer than|shorter than|more than|less than|over|under|above|below)\b")
_OR_LESS = re.compile(rf"{_NUM}{_UNIT}\s+or (?:less|under|shorter)\b(?!\s+(?:than|\d))")   # not "or under 90"
_OR_MORE = re.compile(rf"{_NUM}{_UNIT}\s+or (?:more|over|longer)\b(?!\s+(?:than|\d))")
# "grab attention in the first 10 seconds", "a cut every 3 seconds", "get to the action in 10 seconds or less": a
# time inside the clip, not how long it is; "in 45 second clips" and "keep clips in 30 seconds or less" are lengths
_POINT_IN_CLIP = re.compile(r"\b(?:first|last|opening|final|after|every|each|by)\s+$")
_IN_POINT = re.compile(r"\bin\s+$")
_CLIPS_AFTER = re.compile(r"^\s*(?:long\s+)?(?:clips?|shorts?|videos?)\b")
_OR_BOUND_AFTER = re.compile(r"^\s+or (?:less|under|shorter|more|over|longer)")
_CLIPS_IN = re.compile(r"\b(?:clips?|shorts?|videos?|make|keep|cut)\s+in\s+$")


def _point_in_clip(low: str, m: re.Match) -> bool:
    before, after = low[:m.start(1)], low[m.end(2):]
    if _POINT_IN_CLIP.search(before):
        return True
    return bool(_IN_POINT.search(before) and not (_CLIPS_AFTER.match(after)
                                                  or (_OR_BOUND_AFTER.match(after) and _CLIPS_IN.search(before))))


def _seconds(value: str, unit: str | None) -> float:
    n = float(value)
    return n * 60.0 if unit and unit.startswith("m") else n


def _plain(text: object) -> str:
    low = str(text or "").lower().replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", low).strip()


def _length(low: str) -> dict:
    """The clip length a line asks for: any of min, max and target in seconds, or a factor when it only says
    longer or shorter. Empty when the line is not about how long clips are."""
    if not _LENGTH_OF_CLIPS.search(low) or _OTHER_LENGTH.search(low):
        return {}
    low = re.sub(r"\bhalf a minute\b", "30 seconds", low)
    low = re.sub(r"\ba minute and a half\b", "90 seconds", low)
    low = re.sub(r"\b(?:a|one) minute\b", "60 seconds", low)
    low = re.sub(r"\b(" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")(?=[ -](?:seconds?|minutes?))",
                 lambda m: _WORD_NUMBERS[m.group(1)], low)
    out: dict = {}
    span = _SPAN.search(low)
    if span:
        a, b = _seconds(span.group(1), span.group(2) or span.group(4)), _seconds(span.group(3), span.group(4))
        out["min"], out["max"] = min(a, b), max(a, b)
    else:
        found: dict[int, tuple[str, re.Match]] = {}   # by where the number is: one reading per number
        for key, pattern in (("max", _OR_LESS), ("min", _OR_MORE), ("min", _AT_LEAST), ("max", _AT_MOST),
                             ("target", _ABOUT_LONG)):
            for m in pattern.finditer(low):
                if not _point_in_clip(low, m):
                    found.setdefault(m.start(1), (key, m))
        flipped, last_end = False, 0
        for _at, (key, m) in sorted(found.items()):
            flip = bool(_LEN_NEG.search(low[:m.start()]))
            # "shouldn't be shorter than 20 seconds or longer than 90": the "no" goes on across "or"
            if not flip and flipped and re.fullmatch(r"\s*(?:,\s*)?(?:or|nor)\s+", low[last_end:m.start()]) \
                    and _BARE_BOUND.match(low[m.start():]):
                flip = True
            said = _FLIP[key] if flip and key in _FLIP else key
            out.setdefault(said, _seconds(m.group(1), m.group(2)))
            flipped, last_end = flip and key in _FLIP, m.end()
        if not out:
            for m in _BARE_LONG.finditer(low):
                if not _point_in_clip(low, m):
                    out["target"] = _seconds(m.group(1), m.group(2))
                    break
    out = {k: v for k, v in out.items() if SHORTEST <= v <= LONGEST}
    if not out:
        if _LONGER.search(low) and not _SHORTER.search(low):
            out["factor"] = LONGER
        elif _SHORTER.search(low) and not _LONGER.search(low):
            out["factor"] = SHORTER
    return out


def lengths(st: dict, shortest: float, longest: float, ideal: float) -> tuple[float, float, float]:
    """The clip lengths with what the owner told the Brain applied: (shortest, longest, ideal), kept inside what
    Settings allows, with room between them."""
    want = (st or {}).get("length") or {}
    if not want:
        return shortest, longest, ideal
    f = float(want.get("factor") or 1.0)
    lo, hi, mid = shortest * f, longest * f, ideal * f
    lo, hi = float(want.get("min", lo)), float(want.get("max", hi))
    if "target" in want:
        mid = float(want["target"])
        if "min" not in want:
            lo = min(lo, round(0.6 * mid))
        if "max" not in want:
            hi = max(hi, round(1.5 * mid))
    if "min" in want and "max" not in want:
        hi = max(hi, round(2 * lo))      # a raised minimum needs room above it, or every clip is one length
    if "max" in want and "min" not in want:
        lo = min(lo, round(0.5 * hi))
    lo = max(SHORTEST, min(LONGEST - 10, lo))
    hi = max(lo + 5, min(LONGEST, hi))
    if "target" not in want and ("min" in want or "max" in want):
        mid = max(mid, lo + (hi - lo) / 3) if "min" in want else min(mid, lo + 2 * (hi - lo) / 3)
    return round(lo, 1), round(hi, 1), round(max(lo, min(hi, mid)), 1)


# ------------------------------------------------------------------ reading a line
# Where a "no" stops reaching: the line turns to what it does want ("no intros, just funny moments", "less talking,
# more reactions", "drop the banter, keep the reactions", "skip the intro and go straight to the reactions").
# A turn counts only once the "no" before it has named what it refuses: "don't pick clips that are just small talk"
# still refuses small talk, "no intros, just funny moments" turns to funny moments.
_RESET = re.compile(r"\b(?:just|only|instead|rather|but|keep\w*|focus\w* on|stick to|straight to|lead with|"
                    r"(?<!\bno )(?<!\bany )more|and (?:go|keep|focus|pick|show|use|find|look|stick|leave in|add|"
                    r"include)\w*)\b")
# "never pick intros or lead with small talk", "no intros or any more small talk": the "no" goes on across "or"
_OR_GOES_ON = re.compile(r"\b(?:or|nor)\s+(?:any\s+)?$")
_ANY_KIND = re.compile(r"\b(?:" + "|".join(k.names for k in KINDS) + r")\b")
# words around a "no" that do not end it at a comma ("never, ever clip intros", "don't, under any circumstances, ...")
_ASIDE = re.compile(r"\b(?:ever|at all|please|really|seriously|again|under any circumstances|whatever happens|"
                    r"i mean|ok(?:ay)?|even once)\b")
# After a comma a list of what is left out goes on ("no swearing, boring small talk or ads", "like banter or
# chit-chat"); anything else turns away, and so does a kind that starts a sentence of its own ("..., the funny
# moments are what my fans want"). A list item may carry a word or two before its kind, never a verb or a liking.
_NOT_A_MODIFIER = (r"(?:keep|pick|show|use|find|look|go|give|make|want|need|get|put|add|include|focus|stick|clip|"
                   r"cut|leave|is|are|be|i|we|you|they|it|love|loves|like|likes|prefer|more|most|best|always|only|"
                   r"just|great|good|nice|amazing|awesome|better|cool|strong|epic|" + _NO + r")")
_LIST_GOES_ON = re.compile(r"(?:or |and |nor |like |such as |especially |including )?(?:the |any |all |my |those |"
                           rf"these )?(?:(?!{_NOT_A_MODIFIER}\b)[a-z'-]+\s+){{0,2}}"
                           r"(?:" + "|".join(k.names for k in KINDS) + r")\b"
                           r"(?:\s+(?:moments?|clips?|parts?|bits?|ones?|stuff|reads?|segments?))?"
                           r"\s*(?:[,.;!?]|$|(?:or|and|nor|in|from|on|out of)\b)")
# A line about where a clip starts or ends ("never end clips on a question") says nothing about which moments to pick.
_CUT_POINT = re.compile(r"\b(?:end|ends|ending|ended|start|starts|starting|open|opens|opening|begin\w*|"
                        r"cut off|cuts off)\s+(?:(?:my|the|your|a|each|every|all)\s+)?(?:clips?\s+|shorts?\s+|"
                        r"videos?\s+)?(?:on|with|before|after|at|in the middle of|mid|right (?:on|after|before))\b")


def _scope(part: str, at: int, neg: re.Pattern) -> str:
    """The words before a kind of moment that a "no" can come from: since the line last turned to what it wants."""
    before = part[:at]
    nos = [m.end() for m in neg.finditer(before)]
    named = [m.start() for m in _ANY_KIND.finditer(before)]

    def last_no(pos: int) -> int | None:
        return max((e for e in nos if e <= pos), default=None)

    start = 0
    for m in _RESET.finditer(before):
        if _OR_GOES_ON.search(before[:m.start()]):
            continue
        no = last_no(m.start())
        if no is None or any(no <= k < m.start() for k in named):
            start = max(start, m.end())
    for m in re.finditer(r",\s*", before):     # a colon explains what came before it: it does not turn away
        if _LIST_GOES_ON.match(part[m.end():]):
            continue
        no = last_no(m.start())
        if no is not None and not _ASIDE.sub("", before[no:m.start()]).strip(" ,"):
            continue                       # nothing refused yet: "never, ever clip intros"
        start = max(start, m.end())
    return before[start:]


def _kinds_in(part: str, owner: bool, flipped_until: int = 0) -> dict[str, int]:
    """The kinds of moment a part of a clause names, each with +1 (look for it) or -1 (pass it over)."""
    neg = _NEG_OWNER if owner else _NEG
    out: dict[str, int] = {}
    for kid, pattern in _NAMES.items():
        for m in pattern.finditer(part):
            before = _scope(part, m.start(), neg)
            sign = -1 if len(neg.findall(before)) % 2 else 1
            if sign < 0 and _CAUSE.search(before):
                continue
            if m.start() < flipped_until or (kid in UNWANTED and not owner):
                sign = -1                # the side after "over", "instead of" or ", not"
            out[kid] = out.get(kid, 0) + sign
    return {k: (1 if v > 0 else -1) for k, v in out.items() if v}


def _topic(clause: str, owner: bool) -> tuple[list[str], int] | None:
    """The subject an owner's line wants in clips or out of them: its words (stems) and +1 or -1."""
    if not owner or not _PICK.search(clause):
        return None
    m = _ABOUT.search(clause)
    if not m:
        return None
    words = [stem(t) for t in content_tokens(m.group(1)) if t not in _TOPIC_STOP and t not in knowhow.GENERIC
             and t not in STOPWORDS and not any(p.fullmatch(t) for p in _NAMES.values())]
    words = list(dict.fromkeys(w for w in words if len(w) >= 3))[:6]
    if not words:
        return None
    return words, (-1 if len(_NEG_OWNER.findall(clause[:m.start()])) % 2 else 1)


def read(text: object, *, owner: bool = False, about_picking: bool = False) -> dict:
    """One Brain line as picking advice: {"kinds": {id: +1|-1}, "topics": [(words, sign)], "priorities": [...]}.

    `owner`: the owner's own words (their verbs for leaving something out count, and they may name a subject).
    `about_picking`: the line comes from something that is about choosing moments (a memory tagged so, a skill on
    clip picking), so it needs no picking word of its own.
    """
    from ..autopilot.knowledge_style import PRIORITIES

    low = _QUOTED.sub(" ", _plain(text))
    kinds: dict[str, int] = {}
    topics: list[tuple[list[str], int]] = []
    priorities: list[str] = []
    for clause in _CLAUSE.split(low):
        clause = clause.strip()
        if not clause:
            continue
        picking = bool(_PICK.search(clause))
        if _EDITING.search(clause) and (owner or not picking):
            continue                     # "no music under funny moments" is about the music, not the moments
        if _CUT_POINT.search(clause):    # "never end clips on a question" is about the cut, not the moment
            pieces = re.split(r"(\s*(?:[,;:]|\band\b|\bbut\b)\s*)", clause)
            kept = [pieces[0]] if not _CUT_POINT.search(pieces[0]) else []
            dropping = not kept          # "never end a clip on a joke, a question, or a cliffhanger": the list too
            for sep, piece in zip(pieces[1::2], pieces[2::2]):
                if _CUT_POINT.search(piece) or (dropping and _LIST_GOES_ON.match(piece)):
                    dropping = True
                    continue
                dropping = False
                kept += [sep, piece] if kept else [piece]
            clause = "".join(kept).strip()
            if not clause:
                continue
        if not (picking or about_picking or (owner and (_PREFER.search(clause) or _LEAVE_OUT.search(clause)))):
            continue
        found: dict[str, int] = {}
        left_has = False
        pos = 0
        for m in list(_VERSUS.finditer(clause)) + [None]:
            end = m.start() if m else len(clause)
            part = clause[pos:end]
            got = _kinds_in(part, owner, _VERSUS_REACH if (pos and left_has) else 0)
            left_has = left_has or bool(got)
            for k, v in got.items():
                found.setdefault(k, v)
            pos = m.end() if m else end
        if _CLEAN.search(clause):
            found["swearing"] = -1
        for k, v in found.items():
            kinds.setdefault(k, v)
        t = _topic(clause, owner)
        if t:
            topics.append(t)
        if not _NEG.search(clause):
            priorities += [key for key, pattern in PRIORITIES.items() if re.search(pattern, clause)]
    return {"kinds": kinds, "topics": topics, "priorities": list(dict.fromkeys(priorities))}


# ------------------------------------------------------------------ the whole Brain
LESSON_STARTS = "From your results:"  # brain/lessons.STARTS


def lesson_of(row: dict) -> dict:
    """The lesson a memory still holds as brain/lessons.py wrote it; {} once the owner rewrote its words (then the
    words are theirs and are read like any other memory)."""
    data = row.get("data") or {}
    learned = data.get("lesson") or {}
    if learned.get("kind") not in BY_ID or not learned.get("sign"):
        return {}
    text = str(row.get("text") or "")
    written = data.get("text")
    return learned if (text == written if written else text.startswith(LESSON_STARTS)) else {}


def _memory_lines(ws: str, project_id: str) -> list[dict]:
    from . import memories

    out = []
    for row in memories.candidates(ws, project_id=project_id, mode="clips", kinds=memories.LASTING):
        tags = {str(t).lower() for t in (row.get("tags") or [])}
        source = row.get("source") or "said"
        learned = lesson_of(row)
        if learned:
            # a lesson from the owner's results (brain/lessons.py) says what it means as data: no prose to read
            out.append({"id": row["id"], "from": "memory", "owner": False, "rule": False, "text": row["text"],
                        "level": "results_strong" if learned.get("strong") else "results", "about": True,
                        "preset": {learned["kind"]: 1 if learned["sign"] > 0 else -1}})
            continue
        if source == "imported":
            if tags & _OTHER_TAGS and not tags & _PICK_TAGS:
                continue
            level = "example" if "viral example" in tags else "lesson"
            about = True                 # an imported lesson or example is advice on what works, as a whole
        else:
            level = "rule" if (row["kind"] == "rule" and source == "said") else source
            about = bool(tags & _PICK_TAGS)
        out.append({"id": row["id"], "from": "memory", "level": level, "owner": source == "said",
                    "rule": level == "rule", "text": row["text"], "about": about})
    return out


def _skill_lines(ws: str) -> list[dict]:
    from ..studio import skills

    out = []
    for row in skills.enabled_skills(ws):
        modes = tuple(row.get("modes") or ())
        if modes and not set(modes) & set(SKILL_MODES):
            continue
        about = bool(_PICK_SKILL.search(" ".join(skills.match_words(row)).lower()))
        out += [{"id": row["id"], "from": "skill", "level": "skill", "owner": False, "rule": False, "text": line,
                 "about": about, "name": skills.shown_name(row)} for line in skill_lines(row)]
    return out


def _by(line: dict) -> dict:
    text = " ".join(str(line["text"]).split())
    return {"id": line["id"], "from": line["from"], "level": line["level"],
            "text": text if len(text) <= 160 else text[:157].rstrip() + "…", **({"name": line["name"]}
                                                                               if line.get("name") else {})}


def compile_lines(lines: list[dict]) -> dict:
    """Every line read and added up: per kind a weight from -1 (pass over) to 1 (look for), the owner's subjects,
    the score parts that matter more, and the clip length the owner asked for."""
    sums: dict[str, dict] = {}
    topics: list[dict] = []
    priorities: list[str] = []
    length: dict = {}
    sources: dict[tuple, dict] = {}      # one memory or one skill speaks once about a kind, however many lines
    for line in lines:
        got = ({"kinds": line["preset"], "topics": [], "priorities": []} if line.get("preset")
               else read(line["text"], owner=line["owner"], about_picking=line["about"]))
        src = sources.setdefault((line["from"], line["id"]), {"line": line, "votes": {}, "first": {}})
        for kid, sign in got["kinds"].items():
            src["votes"][kid] = src["votes"].get(kid, 0) + sign
            src["first"].setdefault((kid, sign), line)
        w = WEIGHT.get(line["level"], 0.25)
        for words, sign in got["topics"]:
            if len(topics) < MAX_TOPICS:
                topics.append({"words": words, "w": sign * w, "by": _by(line)})
        if got["kinds"] or line["owner"]:  # a line that names no moment does not get to reweigh the score
            priorities += got["priorities"]
        if line["owner"] and not length:  # newest first: the latest thing the owner said about length holds
            said = _length(_plain(line["text"]))
            if said:
                length = {**said, "by": _by(line)}
    for src in sources.values():
        line = src["line"]
        w = WEIGHT.get(line["level"], 0.25)
        for kid, votes in src["votes"].items():
            if not votes:
                continue
            sign = 1 if votes > 0 else -1
            s = sums.setdefault(kid, {"all": 0.0, "rule": 0.0, "ruled": False, "by": []})
            s["all"] += sign * w
            if line["rule"]:
                s["rule"] += sign * w
                s["ruled"] = True
            s["by"].append((w, sign, _by(src["first"].get((kid, sign), line))))
    kinds = {}
    for kid, s in sums.items():
        # Where the owner made a rule about a kind, only the owner's rules speak about it.
        total = s["rule"] if s["ruled"] else s["all"]
        w = max(-1.0, min(1.0, total))
        if abs(w) < MIN_WEIGHT:
            continue
        side = [b for b in s["by"] if (b[1] > 0) == (w > 0) and (not s["ruled"] or b[2]["level"] == "rule")]
        side.sort(key=lambda b: -b[0])
        kinds[kid] = {"w": round(w, 3), "owner": s["ruled"], "by": [b[2] for b in side[:MAX_BY]]}
    return {"kinds": kinds, "topics": topics, "priorities": list(dict.fromkeys(priorities)), "length": length,
            "lines": len(lines)}


EMPTY = {"kinds": {}, "topics": [], "priorities": [], "length": {}, "lines": 0}


def build(ws: str, project_id: str = "") -> dict:
    """What the Brain says about picking clips for this video, as plain data. Never fails a job: a Brain that
    cannot be read steers nothing."""
    try:
        return compile_lines(_memory_lines(ws, project_id) + _skill_lines(ws))
    except Exception:  # noqa: BLE001 - picking must go on without the Brain
        log.exception("Brain steering could not be read")
        return dict(EMPTY)


# ------------------------------------------------------------------ one candidate
def _shown(kid: str, low: str, facts: dict) -> float:
    """How clearly a candidate shows a kind of moment, 0 to 1, from its words and what was measured."""
    kind = BY_ID[kid]
    hits = len(_CUES[kid].findall(low)) if kid in _CUES else 0
    base = min(1.0, hits / kind.need)
    f = facts.get
    if kid == "reaction":
        base = min(1.0, base + (0.4 if f("emotion", 0) >= 0.6 and hits else 0.0))
    elif kid == "emotional":
        base = min(1.0, base + (0.3 if f("emotion", 0) >= 0.6 else 0.0))
    elif kid == "story":
        base = min(1.0, f("story", 0) / 2.0) * (1.0 if f("complete") else 0.6)
    elif kid == "teaching":
        base = min(1.0, base + (0.3 if f("density", 0) >= 0.6 and hits else 0.0))
    elif kid == "question":
        base = 1.0 if f("question_early") else 0.6 if f("curiosity", 0) >= 0.55 else 0.0
    elif kid == "quotable":
        base = min(1.0, 0.7 * f("short_lines", 0))
    elif kid == "numbers":
        base = min(1.0, f("numbers", 0) / 3.0)
    elif kid == "promo":
        base = max(base, 1.0 if f("promo", 0) else 0.6 if (f("outro") or f("slow_open")) else 0.0)
    elif kid == "smalltalk":
        dull = f("density", 1) < 0.4 and f("emotion", 1) < 0.35 and f("hook", 1) < 0.4
        base = 1.0 if dull and f("density", 1) < 0.3 else 0.6 if dull else 0.0
    return base


def shown_kinds(text: str, facts: dict) -> list[str]:
    """The kinds of moment a clip plainly shows, strongest first. Kept with the clip, so later results can be
    compared by kind (brain/lessons.py)."""
    low = _plain(text)
    got = [(k.id, _shown(k.id, low, facts)) for k in KINDS]
    return [kid for kid, s in sorted(got, key=lambda x: -x[1]) if s >= AVOID_SHOWN]


def brief_line(st: dict) -> str:
    """What the Brain looks for and passes over, in one line for a model that picks or ranks moments."""
    kinds = sorted((st or {}).get("kinds", {}).items(), key=lambda kv: -abs(kv[1]["w"]))
    want = [BY_ID[k].label for k, v in kinds if v["w"] > 0][:5]
    skip = [BY_ID[k].label for k, v in kinds if v["w"] < 0][:4]
    for t in (st or {}).get("topics") or []:
        (want if t["w"] > 0 else skip).append("clips about " + ", ".join(t["words"][:3]))
    parts = []
    if want:
        parts.append("look for " + ", ".join(want))
    if skip:
        parts.append("pass over " + ", ".join(skip))
    return ("From the owner's Brain (their rules, imported lessons and results): " + "; ".join(parts) + ".") \
        if parts else ""


def _who(by: dict) -> str:
    if by["from"] == "skill":
        return f"your skill “{by.get('name') or 'Skill'}”"
    return {"rule": "your rule", "said": "what you told it", "lesson": "a lesson you imported",
            "example": "examples you imported", "results": "your results",
            "results_strong": "your results"}.get(by["level"], "your Brain")


def judge(st: dict, text: str, facts: dict) -> dict | None:
    """What the Brain adds to or takes from one candidate: {"adjust", "why", "used", "avoid"}; None when it has
    nothing to say about it. `avoid` is set when the owner's own rule says to pass this kind of moment over."""
    if not st or not (st.get("kinds") or st.get("topics")):
        return None
    low = _plain(text)
    total = 0.0
    why: list[tuple[float, str]] = []
    used: list[dict] = []
    avoid = None
    for kid, k in st["kinds"].items():
        shown = _shown(kid, low, facts)
        if shown < MIN_SHOWN:
            continue
        by = k["by"][0] if k["by"] else {"from": "memory", "level": "lesson", "id": "", "text": ""}
        if k["w"] <= -0.99 and k.get("owner") and shown >= AVOID_SHOWN and avoid is None:
            avoid = {"label": BY_ID[kid].label, "by": by}
            used += k["by"][:1]
            continue                     # the warning is the whole effect: no second penalty on top
        delta = UNIT * k["w"] * shown
        total += delta
        why.append((abs(delta), f"{'looks for' if delta > 0 else 'passes over'} {BY_ID[kid].label} ({_who(by)})"))
        used += k["by"][:1]
    stems = None
    for t in st.get("topics") or []:
        stems = stems if stems is not None else [stem(w) for w in content_tokens(low)]
        hits = sum(1 for s in stems if s in t["words"])
        if not hits:
            continue
        shown = min(1.0, hits / 2.0)
        named = ", ".join(t["words"][:3])
        if t["w"] <= -0.99 and avoid is None:
            avoid = {"label": f"clips about {named}", "by": t["by"]}
        else:
            delta = 1.25 * UNIT * t["w"] * shown
            total += delta
            why.append((abs(delta), f"{'wants' if delta > 0 else 'wants fewer'} clips about {named} "
                                    f"({_who(t['by'])})"))
        used.append(t["by"])
    if not why and not avoid:
        return None
    seen: set = set()
    once = [u for u in used if not ((u["from"], u["id"]) in seen or seen.add((u["from"], u["id"])))]
    return {"adjust": round(max(-LIMIT, min(LIMIT, total)), 4),
            "why": [w for _, w in sorted(why, key=lambda x: -x[0])][:3], "used": once[:6], "avoid": avoid}


def memory_ids(results: list[dict]) -> list[str]:
    """The memories that steered these chosen clips, to count their use."""
    out: list[str] = []
    for r in results:
        steer = ((r.get("analysis") or {}).get("brain_steer") or {})
        out += [u["id"] for u in steer.get("used") or [] if u.get("from") == "memory" and u.get("id")]
    return list(dict.fromkeys(out))
