"""A pasted script becomes the scenes of an animated short (docs/clipforge/ANIMATED_SHORTS.md).

Viral voice-over shorts change the picture every two to four seconds, so a scene is one picture for 6-16 spoken words
(at 175 words a minute, 6 words take two seconds and 16 take five and a half). The words are the owner's: a scene's
narration is exactly what the voice reads and the captions show, with only what is not meant to be said taken out
(scene headings, speaker labels, timings, directions, hashtags, emoji and markdown).

How a script is read:

* A blank line, a heading ("Scene 3", "## The twist") or a direction ends a scene.
* A direction is a line such as "[Visual: an octopus waving]", "(b-roll of the reef)" or "Show: a map"; it is the
  picture of the next scene, its label taken off. A direction inside a spoken line ("... three hearts [show a heart
  diagram].") is the picture of that line's scene. Sound and pause directions ("[music swells]", "(pause)") are
  dropped.
* "Narrator:", "VO:", "Hook:" and the like are taken off and the words after them are spoken; "Title:", "On-screen
  text:", "Music:", "Hashtags:" and the like are not spoken.
* The spoken lines are cut into sentences; a sentence over 16 words is split at a comma, a dash or a joining word
  ("but", "because") near its middle, and short sentences are merged until a scene has at least 6 words (never more
  than 16).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

LENGTHS = {"short": (15, 30, 22), "standard": (30, 60, 45), "long": (60, 90, 75)}   # min, max, target seconds
WPM = 175                       # words a minute at speed 1.0
SCENE_WORDS = (6, 16)           # a scene's spoken words (soft minimum, hard maximum when merging)
MAX_SCENES = 80                 # 600 words in scenes of 6-16 words
MAX_WORDS = 600
PICTURE_CHARS = 200             # a picture idea taken from a script or made from a scene's words


class SceneError(ValueError):
    """What the owner must change in the script, in plain words."""


# ------------------------------------------------------------------ what is not said
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF⬀-⯿︎️"
                    "‍⃣]")
_HEAD = re.compile(r"^(?:#{1,6}\s*)?(?P<word>scene|beat|shot|slide|panel|frame)\s*#?\s*\d{1,3}"
                   r"(?:\s*[(\[][^)\]]{0,40}[)\]])?\s*(?:[:.)\-–—|]+\s*|$)", re.I)
_MD_HEAD = re.compile(r"^#{1,6}\s+\S")
_RULE = re.compile(r"^(?:[-*_=~]\s*){3,}$")
_BULLET = re.compile(r"^(?:[-*•●▪◦‣–]\s+)+")
_CLOCK = r"\d{1,2}:\d{2}(?:\.\d+)?"
_SECS = r"\d{1,3}(?:\.\d+)?"
_TO = r"\s*(?:-|–|—|to)\s*"
_TIME = re.compile(r"^(?:[\[(]\s*" + _CLOCK + "(?:" + _TO + _CLOCK + r")?\s*[\])]"
                   r"|" + _CLOCK + "(?:" + _TO + _CLOCK + r")?(?=\s)"
                   r"|[\[(]?\s*" + _SECS + _TO + _SECS + r"\s*s(?:ec(?:onds?)?)?\b\s*[\])]?"
                   r"|[\[(]\s*" + _SECS + r"\s*s(?:ec(?:onds?)?)?\s*[\])])\s*[:\-–—|]?\s*", re.I)
_LABEL = re.compile(r"^\[?\s*(?P<label>[A-Za-z][A-Za-z .\-/']{0,28}?)\s*(?:\([^)]{0,30}\))?\s*\]?\s*:\s*(?P<rest>.*)$")
_SPOKEN_LABELS = {"narrator", "narration", "voiceover", "voice-over", "voice over", "vo", "v.o", "voice", "audio",
                  "script", "hook", "intro", "introduction", "opening", "body", "middle", "main", "ending", "end",
                  "outro", "close", "closing", "cta", "call to action", "line", "speaker", "host", "spoken", "read",
                  "dialogue", "dialog", "payoff", "twist", "setup", "reveal", "punchline", "voice line"}
_PICTURE_LABELS = {"visual", "visuals", "image", "images", "picture", "pictures", "show", "shot", "shots", "b-roll",
                   "broll", "b roll", "b-roll footage", "scene description", "description of scene", "footage",
                   "video", "animation", "illustration", "background", "camera", "scene", "setting", "frame",
                   "art", "artwork", "prompt", "image prompt", "visual prompt", "picture prompt", "cut to",
                   "on camera", "stock footage", "screen"}
_DROPPED_LABELS = {"title", "video title", "on-screen text", "on screen text", "onscreen text", "text on screen",
                   "on-screen", "on screen", "text overlay", "overlay", "caption", "captions", "subtitle",
                   "subtitles", "music", "song", "sound", "sounds", "sound effect", "sound effects", "sfx", "fx",
                   "hashtags", "hashtag", "tags", "description", "video description", "duration", "length",
                   "runtime", "timing", "format", "style", "tone", "notes", "note to editor", "editor note",
                   "thumbnail", "transition", "transitions", "font", "pace", "pacing", "word count",
                   "target audience", "audience", "platform", "text"}
_SOUND_WORDS = ("pause", "beat", "music", "sfx", "sound", "whoosh", "silence", "laugh", "laughs", "laughter",
                "breath", "breathe", "sigh", "drum", "drumroll", "bass", "ding", "transition", "cut", "fade",
                "applause", "click", "boom", "swoosh", "audio", "song", "chime", "echo", "record scratch", "beat drop")
_PICTURE_WORDS = ("visual", "visuals", "image", "picture", "show", "shows", "showing", "shot", "b-roll", "broll",
                  "b roll", "close-up", "close up", "closeup", "wide shot", "cut to", "zoom", "pan", "footage",
                  "illustration", "animation", "on screen", "camera", "scene", "graphic", "diagram", "map")
_BRACKETS = re.compile(r"\[([^\[\]]{1,300})\]|\{([^{}]{1,300})\}")
_PARENS = re.compile(r"\(([^()]{1,300})\)")
_TRAILING_TAGS = re.compile(r"(?:\s+#[^\s#]+)+$")


def _plain(text: str) -> str:
    """One line without markdown emphasis, emoji, odd spaces or wrapping quotes."""
    s = unicodedata.normalize("NFC", text).replace("\t", " ").replace(" ", " ").replace(" ", " ")
    s = _EMOJI.sub("", s)
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", s)
    s = re.sub(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])", r"\1", s)
    s = " ".join(s.split())
    quotes = s.count('"') + s.count("“") + s.count("”")
    if len(s) > 2 and s[0] in "\"“" and s[-1] in "\"”" and quotes == 2:
        s = s[1:-1].strip()
    return s


def _label_kind(label: str) -> str:
    key = " ".join(label.lower().replace("_", " ").split()).rstrip(".")
    for kind, names in (("spoken", _SPOKEN_LABELS), ("picture", _PICTURE_LABELS), ("dropped", _DROPPED_LABELS)):
        if key in names or (key.endswith("s") and key[:-1] in names):
            return kind
    if key.startswith(("scene ", "visual ", "image ", "picture ", "b-roll ", "shot ")):
        return "picture"
    return ""


def _direction(inner: str) -> str:
    """The picture a direction describes ('' for a sound or pause direction)."""
    s = _plain(inner).strip(" .:;-–—")
    low = s.lower()
    if not s or any(low == w or low.startswith((w + " ", w + ":", w + ",")) for w in _SOUND_WORDS):
        return ""
    m = _LABEL.match(s)
    if m:
        kind = _label_kind(m.group("label"))
        if kind == "dropped":
            return ""
        if kind:
            s = m.group("rest").strip()
    s = re.sub(r"^(?:b-?\s?roll|stock footage|footage|cut to|show(?:ing)?|visuals?|image)\s*(?:of\b|:)?\s*", "", s,
               flags=re.I)
    return " ".join(s.split()).strip(" .")[:PICTURE_CHARS]


def _is_direction(inner: str) -> bool:
    low = inner.strip().lower()
    return any(low == w or low.startswith((w + " ", w + ":", w + ",")) for w in _PICTURE_WORDS + _SOUND_WORDS)


def _speakable(line: str) -> tuple[str, str, str]:
    """(a picture named at the start of the line, the words to say, a picture named later in the line)."""
    lead = later = ""
    s = line
    m = re.match(r"^\s*(?:\[([^\[\]]{1,300})\]|\{([^{}]{1,300})\})", s)
    if not m:
        paren = re.match(r"^\s*\(([^()]{1,300})\)", s)
        m = paren if paren and _is_direction(paren.group(1)) else None
    if m:
        lead = _direction(next(g for g in m.groups() if g is not None))
        s = s[m.end():]

    def take(match: re.Match) -> str:
        nonlocal later
        idea = _direction(next(g for g in match.groups() if g is not None))
        later = later or idea
        return " "

    def take_paren(match: re.Match) -> str:
        if not _is_direction(match.group(1)):
            return match.group(0)
        return take(match)

    s = _BRACKETS.sub(take, s)
    s = _PARENS.sub(take_paren, s)
    s = _TRAILING_TAGS.sub("", s)
    s = " ".join(s.split())
    s = re.sub(r"\s+([,.!?;:…])", r"\1", s)
    s = re.sub(r"\s+[—–-]$", "", s)
    return lead, s.strip(" |"), later


def _read(text: str) -> list[tuple]:
    """The script as ("say", words, picture named in the line), ("picture", idea) and ("break",) items."""
    out: list[tuple] = []
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    for raw in text.split("\n"):
        line = _plain(raw)
        if not line or _RULE.match(line):
            out.append(("break",))
            continue
        head = _HEAD.match(line)
        if head:
            out.append(("break",))
            rest = line[head.end():].strip(" -–—:|")
            if not rest:
                continue
            if head.group("word").lower() in ("shot", "panel", "frame") and not _LABEL.match(rest):
                idea = _direction(rest)
                if idea:
                    out.append(("picture", idea))
                continue
            if not _LABEL.match(rest) and (len(rest.split()) < 4 or not re.search(r"[.!?…][\"'”’)]*$", rest)):
                continue  # "Scene 2: The twist" is a heading, not words to say
            line = rest
        elif _MD_HEAD.match(line):
            out.append(("break",))
            continue
        line = _BULLET.sub("", line)
        timed = _TIME.match(line)
        if timed:
            out.append(("break",))  # "0:03-0:06 ..." starts a scene of its own
            line = line[timed.end():].strip()
        if not line or re.fullmatch(r"(?:#[^\s#]+\s*)+", line):
            continue  # a timing or hashtags alone
        whole = re.fullmatch(r"[\[({](.+)[\])}]", line)
        if whole and not re.search(r"[\])}].*[\[({]", whole.group(1)) and \
                (line[0] != "(" or _is_direction(whole.group(1)) or not re.search(r"[.!?]$", whole.group(1))):
            idea = _direction(whole.group(1))
            out.append(("break",))
            if idea:
                out.append(("picture", idea))
            continue
        m = _LABEL.match(line)
        if m:
            kind = _label_kind(m.group("label"))
            rest = m.group("rest").strip()
            if kind == "dropped":
                continue
            if kind == "picture":
                out.append(("break",))
                idea = _direction(rest)
                if idea:
                    out.append(("picture", idea))
                continue
            if kind == "spoken":
                line = rest
        lead, say, later = _speakable(line)
        if lead:
            out += [("break",), ("picture", lead)]
        if re.search(r"[^\W_]", say):
            out.append(("say", say, later))
        elif later:
            out += [("break",), ("picture", later)]
    return out


# ------------------------------------------------------------------ sentences and scenes
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "prof.", "vs.", "etc.", "e.g.", "i.e.", "mt.",
                  "no.", "u.s.", "u.k.", "a.m.", "p.m.", "approx.", "inc.", "ltd.", "co.", "fig.", "ft.", "lb.",
                  "oz.", "vol.", "gen.", "sgt.", "capt.", "lt.", "col.", "gov.", "rev.", "ave."}
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"'”’»)\]]*\s+")
_JOINERS = {"but", "because", "so", "and", "which", "while", "when", "until", "then", "or", "though", "although",
            "since", "unless", "whereas", "yet", "where", "who", "after", "before", "if", "instead"}


def _sentences(line: str) -> list[str]:
    out: list[str] = []
    for p in (p.strip() for p in _SENTENCE_END.split(line)):
        if not p:
            continue
        if out:
            last = out[-1].split()[-1].lower()
            if last in _ABBREVIATIONS or re.fullmatch(r"(?:[^\W\d_]\.){1,3}", last) or \
                    (p[:1].islower() and not out[-1].endswith(("!", "?", "…"))):
                out[-1] = f"{out[-1]} {p}"
                continue
        out.append(p)
    return out


def _spoken(token: str) -> bool:
    """A token the voice says (a lone dash or another mark is said as a pause, not as a word)."""
    return bool(re.search(r"[^\W_]", token))


def _count(tokens: list[str]) -> int:
    return sum(1 for t in tokens if _spoken(t))


def _cut_long(tokens: list[str], most: int) -> list[list[str]]:
    """One sentence in pieces of at most `most` words, cut where a speaker would pause, near the middle."""
    total = _count(tokens)
    if total <= most:
        return [tokens]
    edge = min(4, total // 2)
    best, best_score = None, None
    for i in range(1, len(tokens)):
        before, after = tokens[i - 1], tokens[i]
        if not _spoken(after):
            continue  # a dash stays with the words before it
        if before.endswith((",", ";", ":", "—", "–")) or not _spoken(before):
            weight = 0.0
        elif after.lower().strip(",;:") in _JOINERS:
            weight = 1.5
        else:
            continue
        left = _count(tokens[:i])
        if left < edge or total - left < edge:
            continue
        score = abs(left - total / 2) / total * 10 + weight
        if best_score is None or score < best_score:
            best, best_score = i, score
    if best is None or max(_count(tokens[:best]), total - _count(tokens[:best])) > most * 1.6:
        half, seen, best = (total + 1) // 2, 0, len(tokens) // 2
        for i, t in enumerate(tokens):
            seen += _spoken(t)
            if seen == half:
                best = i + 1
                break
    return _cut_long(tokens[:best], most) + _cut_long(tokens[best:], most)


def _pieces(lines: list[tuple[str, str]]) -> list[tuple[list[str], str]]:
    """Each spoken line's sentences, long ones cut, with the picture the line named (on its first piece)."""
    out: list[tuple[list[str], str]] = []
    for text, picture in lines:
        first = True
        for sentence in _sentences(text):
            for words in _cut_long(sentence.split(), SCENE_WORDS[1]):
                if _count(words):
                    out.append((words, picture if first else ""))
                    first = False
    return out


def _merge(pieces: list[tuple[list[str], str]], least: int, most: int) -> list[tuple[list[str], str]]:
    """Short pieces joined until a scene has at least `least` words, never more than `most`."""
    scenes: list[tuple[list[str], str]] = []
    for words, picture in pieces:
        if scenes and _count(scenes[-1][0]) < least and _count(scenes[-1][0]) + _count(words) <= most and \
                not (picture and scenes[-1][1]):
            scenes[-1] = (scenes[-1][0] + words, scenes[-1][1] or picture)
        else:
            scenes.append((list(words), picture))
    if len(scenes) > 1 and _count(scenes[-1][0]) < least and \
            _count(scenes[-2][0]) + _count(scenes[-1][0]) <= most and not (scenes[-1][1] and scenes[-2][1]):
        words, picture = scenes.pop()
        scenes[-1] = (scenes[-1][0] + words, scenes[-1][1] or picture)
    return scenes


def _blocks(items: list[tuple]) -> list[dict]:
    """Spoken lines between two breaks, each block with the picture a direction named for it."""
    blocks: list[dict] = []
    current: dict = {"lines": [], "picture": ""}
    waiting = ""

    def close() -> None:
        nonlocal current
        if current["lines"]:
            blocks.append(current)
        current = {"lines": [], "picture": ""}

    for item in items:
        if item[0] == "break":
            close()
        elif item[0] == "picture":
            close()
            waiting = item[1]
        else:
            if not current["lines"] and waiting:
                current["picture"], waiting = waiting, ""
            current["lines"].append((item[1], item[2]))
    close()
    if waiting and blocks and not blocks[-1]["picture"]:
        blocks[-1]["picture"] = waiting   # a direction after the last words pictures the last block
    return blocks


def _scenes(blocks: list[dict], least: int) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        for k, (words, named) in enumerate(_merge(_pieces(b["lines"]), least, SCENE_WORDS[1])):
            picture = (b["picture"] if k == 0 else "") or named
            out.append({"narration": " ".join(words), "picture": picture[:PICTURE_CHARS],
                        "picture_from": "script" if picture else ""})
    return out


def split(text: str) -> list[dict]:
    """A pasted script as scenes: [{"narration", "picture", "picture_from": "script" | ""}] in order. Raises
    SceneError when there are no words to say, more than MAX_WORDS words or more than MAX_SCENES scenes."""
    blocks = _blocks(_read(text))
    count = sum(_count(t.split()) for b in blocks for t, _ in b["lines"])
    if not count:
        raise SceneError("There are no words for the voice to say. Paste the words of your short.")
    if count > MAX_WORDS:
        raise SceneError(f"The script has {count} words, and a short can have at most {MAX_WORDS} (about three and "
                         "a half minutes). Cut it down, or make two shorts.")
    scenes: list[dict] = []
    for least in (SCENE_WORDS[0], 10, 13, SCENE_WORDS[1]):
        scenes = _scenes(blocks, least)
        if len(scenes) <= MAX_SCENES:
            return scenes
    raise SceneError(f"The script makes {len(scenes)} scenes, and a short can have at most {MAX_SCENES}. Join some "
                     "short lines together, or make two shorts.")


def clean_narration(text: str) -> str:
    """A scene's words as the voice should say them, on one line (what is not said is taken out)."""
    return " ".join(item[1] for item in _read(text) if item[0] == "say")


def split_narration(text: str) -> list[str]:
    """One narration in scene-sized pieces, by the same rules."""
    lines = [(item[1], "") for item in _read(text) if item[0] == "say"]
    return [" ".join(words) for words, _ in _merge(_pieces(lines), SCENE_WORDS[0], SCENE_WORDS[1])]


def seconds(text: str, speed: float = 1.0) -> float:
    """About how long the words take to say at this speed, with the pauses at the punctuation."""
    text = str(text or "")
    words = len(text.split())
    if not words:
        return 0.0
    speed = min(2.0, max(0.5, float(speed or 1.0)))
    pauses = 0.25 * len(re.findall(r"[.!?…](?=\s|$)", text)) + 0.12 * len(re.findall(r"[,;:—–](?=\s|$)", text))
    return round((words * 60.0 / WPM + pauses) / speed, 2)


# ------------------------------------------------------------------ a picture from the words
_NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                 "twelve", "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million", "billion",
                 "half", "dozen"}
STOP = frozenset("""
a about above after again against all almost alone along already also although always am among an and another any
anyone anything anyway are aren't around as at away back be became because become becomes been before began begin
being below beside besides best better between beyond both but by came can can't cannot could couldn't did didn't do
does doesn't doing don't done down during each either else enough even ever every everyone everything exactly far
few for from further get gets getting give given gives go goes going gone got had hadn't happen happened happens has
hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's however i i'd
i'll i'm i've if in inside instead into is isn't it it's its itself just keep keeps kept know knew known knows last
later least less let let's like likely made make makes making many may maybe me might mine more most much must
mustn't my myself near need needs never new next no nobody none nor not nothing now of off often oh ok okay on once
only onto or other others otherwise ought our ours ourselves out over own perhaps please pretty probably put quite
rather really right said same saw say says see seem seemed seems seen several shall she she'd she'll she's should
shouldn't since so some somebody someone something sometimes somewhere soon still such sure take taken takes than
that that's the their theirs them themselves then there there's these they they'd they'll they're they've thing
things think this those though through thus till to today together told too took toward towards tried truly try
under unless until up upon us use used uses using usually very via was wasn't way ways we we'd we'll we're we've
well went were weren't what what's whatever when when's where where's whether which while who who's whoever whole
whom whose why why's will with within without won't would wouldn't yeah yes yet you you'd you'll you're you've your
yours yourself yourselves actually basically literally simply totally stuff lot lots kind sort bit tell tells
telling call called calls look looks looking looked want wants wanted come comes coming find found finds turn turns
turned mean means meant work works worked thought thinking believe believed wait imagine guess listen watch stop
hello hi hey bye goodbye wow whoa yay ooh ah uh um hmm huh okay alright
""".split())
GENERIC = frozenset({"fact", "facts", "thing", "things", "people", "person", "time", "times", "year", "years", "day",
                     "days", "world", "life", "way", "ways", "story", "video", "today", "part", "reason", "reasons",
                     "truth", "secret", "question", "answer", "number", "kind", "lot", "end", "point", "moment",
                     "minute", "minutes", "second", "seconds", "hour", "hours", "short", "shorts", "first", "last"})
_WORD = re.compile(r"[^\W_](?:[\w'’\-]*[^\W_])?")


def _low(word: str) -> str:
    return word.lower().replace("’", "'")


def _starts(narration: str) -> set[int]:
    """Positions of the words that start a sentence."""
    out, start = set(), True
    for k, raw in enumerate(str(narration or "").split()):
        if start:
            out.add(k)
        start = bool(re.search(r"[.!?…][\"'”’)]*$", raw))
    return out


def chunks(narration: str) -> list[list[str]]:
    """Runs of the words that carry a picture, in order: a stop word or a punctuation mark ends a run. A word
    capitalised only because it starts a sentence is lowercased; names keep their capital."""
    words = str(narration or "").split()
    starts = _starts(narration)
    capitalised_inside = {_low(_WORD.search(w).group(0)) for k, w in enumerate(words)
                          if k not in starts and _WORD.search(w) and _WORD.search(w).group(0)[:1].isupper()}
    out: list[list[str]] = []
    run: list[str] = []
    for k, raw in enumerate(words):
        m = _WORD.search(raw)
        word = m.group(0) if m else ""
        low = _low(word)
        base = low[:-2] if low.endswith("'s") else low
        if not word or (base in STOP and base not in _NUMBER_WORDS):
            if run:
                out.append(run)
            run = []
            continue
        if k in starts and word[:1].isupper() and not word.isupper() and low not in capitalised_inside:
            word = word[:1].lower() + word[1:]
        run.append(word)
        if re.search(r"[,.;:!?…—–)\]\"”]$", raw):
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def _singular(word: str) -> str:
    w = _low(word)
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "zes", "ches", "shes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def picture_words(narration: str, subject: str = "") -> str:
    """A picture idea from a scene's own words: the runs of words that carry a picture, with the short's subject in
    front when the scene does not name it ("octopuses, blue blood, copper, iron")."""
    picked: list[str] = []
    count = 0
    for run in chunks(narration):
        if len(run) == 1 and _low(run[0]) in GENERIC:
            continue
        if picked and count + len(run) > 10:
            break
        picked.append(" ".join(run))
        count += len(run)
    idea = ", ".join(picked)
    subject = " ".join(str(subject or "").split())
    if subject:
        have = {_singular(w) for p in picked for w in p.split()}
        if not all(_singular(w) in have for w in subject.split()):
            idea = f"{subject}, {idea}" if idea else subject
    if not idea:
        idea = " ".join(str(narration or "").split()[:8]).strip(" .,!?")
    return idea[:PICTURE_CHARS]


def subject_of(narrations: list[str], title: str = "") -> str:
    """The thing a script is about, for every picture ("octopuses"): a word the hook (the first scene) or the title
    names, or one said in more than one place; the hook's and the title's words win, then the one said most, then
    the hook's first. '' when nothing stands out."""
    said: Counter = Counter()
    forms: dict[str, Counter] = {}
    hook: dict[str, int] = {}
    titled: set[str] = set()

    def words(text: str):
        for run in chunks(text):
            for w in run:
                low = _low(w)
                if low in GENERIC or low in _NUMBER_WORDS or len(low) < 3 or any(c.isdigit() for c in low) or \
                        (len(low) >= 5 and low.endswith("ing")) or (len(low) >= 6 and low.endswith("ed")):
                    continue  # "scrolling", "changed": what happens, not what the short is about
                yield _singular(low), (w if w[:1].isupper() and not w.isupper() else low)

    for k, n in enumerate(narrations or []):
        for key, form in words(str(n or "")):
            said[key] += 1
            forms.setdefault(key, Counter())[form] += 1
            if k == 0:
                hook.setdefault(key, len(hook))
    for key, form in words(str(title or "")):
        titled.add(key)
        forms.setdefault(key, Counter())[form] += 1

    def score(key: str) -> int:
        return said[key] + (1 if key in hook else 0) + (3 if key in titled else 0)

    found = [key for key in forms if score(key) >= 2]
    if not found:
        return ""
    best = max(found, key=lambda key: (score(key), key in hook, -hook.get(key, 99), said[key]))
    return forms[best].most_common(1)[0][0]
