"""Your script, read and matched to what was said in the footage.

An owner's script says what the video should say, in which order. ClipForge reads it (plain text, Markdown, Word,
PDF or Final Draft) into numbered lines, tells the spoken lines from headings and directions, and looks for every
spoken line in the words transcribed from the footage. Each place a line was said is a *take*, scored by how much
of the line was heard in order (its coverage) and how cleanly it was said (its quality: fillers, stumbles, pauses,
word confidence). The best take of each line is chosen, a stretch of speech is never used by two lines, lines said
one after another make one clip, and what was said but is not in the script is listed as unused. That is what
DaVinci Resolve's IntelliScript and Avid's ScriptSync do, done here with fixed rules a person can follow: the same
script and footage always give the same cut, and `report` says in words what happened.

Nothing here touches the database or the app; video_flow wires the result into the plan.
"""
from __future__ import annotations

import difflib
import io
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from ..pipeline.text_utils import ABBREV, STOPWORDS
from .smart_edit import PURE_FILLERS, is_filler

SUPPORTED = (".txt", ".text", ".md", ".markdown", ".docx", ".pdf", ".fdx")
FORMATS = {".txt": "txt", ".text": "txt", ".md": "md", ".markdown": "md", ".docx": "docx", ".pdf": "pdf",
           ".fdx": "fdx"}
MAX_BYTES = 5_000_000
MAX_CHARS = 200_000
MAX_LINES = 2_000
SPLIT_WORDS = 30             # a paragraph longer than this is looked for sentence by sentence
TAKE = 0.6                   # coverage from which a take counts as the line, found
WEAK = 0.4                   # ... found only partly; below it the line is missing
MAX_ANCHORS = 4              # the rarest words of a line that say where to look
MAX_WINDOWS = 60             # places looked at per line (the ones with most anchors)
MAX_ALTERNATIVES = 4
USED_SHARE = 0.3             # a take may share at most this much of its words with an earlier line's take
SAME_SHARE = 0.5             # two takes sharing more than this of the shorter one are the same take
CHAIN_GAP_S = 1.5            # lines said one after another within this gap make one clip
PAUSE_S = 0.7                # a silence inside a take longer than this counts against it
MIN_UNUSED = 3               # words: shorter leftovers between takes are not worth listing
SAID_CHARS = 300

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
            "twelve": "twelfth"}

_WORD_RE = re.compile(r"[a-z]+|\$?\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?%?")
_LIST_RE = re.compile(r"^(?:[-*•·–—>]|\d{1,3}[.)]|\(\d{1,3}\))\s+")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_WRAPPED_RE = re.compile(r"^\[[^\]]*\]$|^\([^)]*\)$")
_DIRECTION_RE = re.compile(r"(?:b-?roll|visuals?|show|on[ -]screen|sfx|music|graphic|title|caption|note)\s*:"
                           r"|cut to\b|fade (?:in|out)\b", re.IGNORECASE)
_SCENE_RE = re.compile(r"(?:INT|EXT)[./ ]|(?i:scene|part|chapter|section|act|segment|beat)\s*\d+")
_SPEAKER_RE = re.compile(r"([A-Z][A-Z0-9 .'\-]{0,30}?)(?:\s*\([^)]{1,15}\))?:\s+(?=\S)")
_SENTENCE_END_RE = re.compile(r"[.!?]+[\"”’)]*\s+(?=[A-Z0-9\"“(])")


class ScriptError(ValueError):
    """The script cannot be used; the message says why in plain words."""


# ------------------------------------------------------------------ reading the file
def parse(filename: str, data: bytes | str) -> dict:
    """Read a script file, or pasted text (a `str`), into numbered lines.

    Returns {"filename", "format", "text", "lines", "counts"}: `text` is the script as read (what the Script panel
    shows and what is kept for "Edit it for me" again); each line is {"n", "text", "kind", "speaker", "section",
    "tokens"} with kind "line" (spoken), "heading" (a chapter) or "direction" (never said: B-roll and camera notes,
    [bracketed] and (parenthesised) asides); `counts` says how much there is to match ("words" counts the spoken
    lines). Raises ScriptError for a format, size or emptiness the owner has to fix.
    """
    fmt = _format(filename, data)
    if isinstance(data, str):
        text = _newlines(data)
        blocks = _plain_blocks(text)
    else:
        if len(data) > MAX_BYTES:
            raise ScriptError(f"The script file is {len(data) / 1e6:.1f} MB; the limit is "
                              f"{MAX_BYTES // 1_000_000} MB.")
        text, blocks = _READERS[fmt](data)
    if len(text) > MAX_CHARS:
        raise ScriptError(f"The script is longer than {MAX_CHARS:,} characters; give only the part this video "
                          "follows.")
    lines = _lines(blocks)
    if len(lines) > MAX_LINES:
        raise ScriptError(f"The script has more than {MAX_LINES:,} lines; give only the part this video follows.")
    if not lines:
        raise ScriptError("The script has no text.")
    counts = {"lines": sum(1 for ln in lines if ln["kind"] == "line"),
              "headings": sum(1 for ln in lines if ln["kind"] == "heading"),
              "directions": sum(1 for ln in lines if ln["kind"] == "direction"),
              "words": sum(len(ln["text"].split()) for ln in lines if ln["kind"] == "line")}
    return {"filename": filename, "format": fmt, "text": text, "lines": lines, "counts": counts}


def _format(filename: str, data: bytes | str) -> str:
    if isinstance(data, str):
        return "txt"
    ext = Path(filename or "").suffix.lower()
    if ext not in FORMATS:
        raise ScriptError(f"ClipForge cannot read '{filename or 'the file'}' as a script: use a .txt, .md, .docx, "
                          ".pdf or .fdx file, or paste the text.")
    return FORMATS[ext]


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _plain_blocks(text: str) -> list[tuple[str, str, str]]:
    """Every physical line is a block to classify: (text, kind known from the file format or "", speaker)."""
    return [(line, "", "") for line in text.split("\n")]


def _read_text(data: bytes) -> tuple[str, list[tuple[str, str, str]]]:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    text = _newlines(text)
    return text, _plain_blocks(text)


def _read_docx(data: bytes) -> tuple[str, list[tuple[str, str, str]]]:
    """Word paragraphs in their order, with the cells of a table row by row where the table stands."""
    import docx
    from docx.table import Table

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several kinds for a broken or non-Word file
        raise ScriptError("The Word file could not be read; save it as .docx again or paste the text.") from exc
    parts: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            for row in item.rows:
                parts.extend(cell.text for cell in row.cells)
        else:
            parts.append(item.text)
    text = _newlines("\n".join(parts))
    return text, _plain_blocks(text)


def _read_pdf(data: bytes) -> tuple[str, list[tuple[str, str, str]]]:
    """The text of every page; words broken at a line end are mended and hard-wrapped lines joined."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf raises several kinds for a broken, locked or non-PDF file
        raise ScriptError("The PDF could not be read; export it again or paste the text.") from exc
    text = _unwrap_pdf("\n".join(pages))
    if not re.search(r"[A-Za-z]", text):
        raise ScriptError("The PDF has no text in it (a scanned page needs OCR first); paste the text instead.")
    return text, _plain_blocks(text)


def _unwrap_pdf(text: str) -> str:
    """"hel-\\nlo" → "hello"; a line without an end mark followed by a line starting in lowercase was one line."""
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", _newlines(text))
    out: list[str] = []
    for line in text.split("\n"):
        previous = out[-1].rstrip() if out else ""
        if previous and line[:1].islower() and not previous.endswith((".", "!", "?", ":", '"', "”", "…")):
            out[-1] = previous + " " + line.lstrip()
        else:
            out.append(line)
    return "\n".join(out)


def _read_fdx(data: bytes) -> tuple[str, list[tuple[str, str, str]]]:
    """Final Draft: scene headings, action and parentheticals (directions), characters naming the dialogue that
    follows. `text` renders it so that reading it back as plain text gives the same lines."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ScriptError("The Final Draft file could not be read; export it as .fdx again or paste the text.") from exc
    content = root.find("Content")
    shown: list[str] = []
    blocks: list[tuple[str, str, str]] = []
    speaker = ""
    for p in (content if content is not None else root).iter("Paragraph"):
        kind = p.get("Type", "")
        text = re.sub(r"\s+", " ", "".join("".join(t.itertext()) for t in p.findall("Text"))).strip()
        if not text:
            continue
        if kind == "Character":
            speaker = _speaker_name(text)
        elif kind == "Scene Heading":
            shown.append(text)
            blocks.append((text, "heading", ""))
        elif kind in ("Action", "Parenthetical"):
            shown.append(text if kind == "Parenthetical" else f"[{text}]")
            blocks.append((text, "direction", ""))
        elif kind == "Dialogue":
            shown.append(f"{speaker.upper()}: {text}" if speaker else text)
            blocks.append((text, "line", speaker))
    return "\n".join(shown), blocks


_READERS = {"txt": _read_text, "md": _read_text, "docx": _read_docx, "pdf": _read_pdf, "fdx": _read_fdx}


# ------------------------------------------------------------------ lines
def _lines(blocks: list[tuple[str, str, str]]) -> list[dict]:
    """Numbered lines from the blocks read: list markers stripped, long paragraphs split into sentences, each told
    as a heading, a direction or a spoken line (with its speaker), under the last heading seen."""
    out: list[dict] = []
    section = ""
    for raw, preset, speaker in blocks:
        for piece in _pieces(raw):
            if preset:
                kind, text = preset, (_unwrap(piece) if preset == "direction" else piece)
            else:
                kind, text, speaker = _classify(piece)
            if kind == "line":
                text = _spoken(text)
            if not re.search(r"[^\W_]", text):
                continue
            if kind == "heading":
                section = text
            out.append({"n": len(out) + 1, "text": text, "kind": kind, "speaker": speaker, "section": section,
                        "tokens": normalize(text)})
    return out


def _pieces(raw: str) -> list[str]:
    """A block as it will be matched: list marker and Markdown dressing gone, a long paragraph in sentences."""
    text = _LIST_RE.sub("", raw.strip())
    text = _LINK_RE.sub(r"\1", text).replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    if not re.search(r"[^\W_]", text):
        return []
    return _sentences(text) if len(text.split()) > SPLIT_WORDS else [text]


def _sentences(text: str) -> list[str]:
    """Split at ". ! ?" followed by a capital or a digit, never after "Dr.", "e.g." or an initial."""
    out: list[str] = []
    start = 0
    for m in _SENTENCE_END_RE.finditer(text):
        before = text[start:m.end()].rstrip()
        last = before.split()[-1].lower()
        if last in ABBREV or re.fullmatch(r"[a-z]\.", last):
            continue
        out.append(before)
        start = m.end()
    rest = text[start:].strip()
    return out + ([rest] if rest else [])


def _classify(text: str) -> tuple[str, str, str]:
    """What a line of plain text is: (kind, its text, its speaker). A direction is wholly in [brackets] or
    (parentheses) or starts with "B-ROLL:", "VISUAL:", "CUT TO" and the like; a heading starts with "#", "INT.",
    "Scene 3", or is short and in capitals or ends with ":"; "NAME:" in front names the speaker."""
    if text.startswith("#"):
        return "heading", text.strip("# ").rstrip(":").strip(), ""
    if _DIRECTION_RE.match(text) or _WRAPPED_RE.match(text):
        return "direction", _unwrap(text), ""
    words = len(text.split())
    if words <= 12 and _SCENE_RE.match(text):
        return "heading", text.rstrip(":").strip(), ""
    m = _SPEAKER_RE.match(text)
    if m:
        return "line", text[m.end():].strip(), _speaker_name(m.group(1))
    letters = re.sub(r"[^A-Za-z]", "", text)
    if words <= 8 and letters and letters.isupper() and not text.rstrip("\"”").endswith((".", "!", "?", "…")):
        return "heading", text.rstrip(":").strip(), ""
    if words <= 8 and text.endswith(":"):
        return "heading", text.rstrip(":").strip(), ""
    return "line", text, ""


def _unwrap(text: str) -> str:
    return text[1:-1].strip() if _WRAPPED_RE.match(text) else text


def _spoken(text: str) -> str:
    """The words to say: a short "(beat)", "(laughs)" or "[B-roll here]" inside a line is not one of them."""
    text = re.sub(r"\[[^\[\]]*\]", " ", text)
    text = re.sub(r"\((?:[^()\s]+\s*){1,4}\)", " ", text)
    return re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s+", " ", text)).strip()


def _speaker_name(label: str) -> str:
    return re.sub(r"\([^)]*\)", "", label).strip(" .:").title()


# ------------------------------------------------------------------ the words compared
def normalize(text: str) -> list[str]:
    """The words both the script and the transcript are compared on: lowercase, apostrophes gone ("I'm" → "im"),
    other punctuation a break, numbers as the words a speaker says, a light stem (5+ letters lose a trailing
    "ing", "ed", "es" or "s"), fillers (um, uh ...) dropped."""
    out: list[str] = []
    for m in _WORD_RE.finditer(text.lower().replace("’", "").replace("'", "")):
        out.extend(_token(m.group()))
    return out


@lru_cache(maxsize=65536)
def _token(raw: str) -> tuple[str, ...]:
    if raw[0] in "$0123456789":
        return tuple(_number_words(raw))
    if raw in PURE_FILLERS:
        return ()
    return (_stem(raw),)


def _stem(t: str) -> str:
    if len(t) < 5:
        return t
    if t.endswith("ies"):
        return t[:-3] + "y"
    if t.endswith("ing") and len(t) >= 6:
        return t[:-3]
    if t.endswith("ed"):
        return t[:-2]
    if t.endswith(("sses", "xes", "zzes", "ches", "shes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _number_words(raw: str) -> list[str]:
    """"$20" → twenty dollars, "3.5" → three point five, "50%" → fifty percent, "2nd" → second, "1,000" → one
    thousand: a number is compared as the words a speaker says."""
    core = raw.strip("$%").replace(",", "")
    suffix = core[-2:] if core[-2:] in ("st", "nd", "rd", "th") else ""
    whole, _, frac = core[:len(core) - len(suffix)].partition(".")
    words = _int_words(int(whole)) if len(whole) <= 9 else [ONES[int(d)] for d in whole]
    if suffix:
        last = words[-1]
        words[-1] = ORDINALS.get(last, last[:-1] + "ieth" if last.endswith("y") else last + "th")
    if frac:
        words += ["point"] + [ONES[int(d)] for d in frac]
    if raw.startswith("$"):
        words.append("dollar" if core == "1" else "dollars")
    if raw.endswith("%"):
        words.append("percent")
    return words


def _int_words(n: int) -> list[str]:
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    for value, name in ((1_000_000, "million"), (1_000, "thousand"), (100, "hundred")):
        if n >= value:
            rest = n % value
            return _int_words(n // value) + [name] + (_int_words(rest) if rest else [])
    return []


def _bare(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", str(word).lower())


# ------------------------------------------------------------------ how well a take was said
def take_quality(words: list[dict]) -> float:
    """How cleanly a take was said, 0..1: fillers, stumbles (a run of one to three words said again at once) and
    pauses longer than PAUSE_S inside it count against it; Whisper's word confidence scales it (0.85 for a word
    without one)."""
    if not words:
        return 0.0
    n = len(words)
    fillers = sum(1 for w in words if is_filler(w))
    stumbles = _stumble_runs([b for b in (_bare(w["w"]) for w in words if not is_filler(w)) if b])
    span = words[-1]["end"] - words[0]["start"]
    paused = sum(gap for gap in (words[i]["start"] - words[i - 1]["end"] for i in range(1, n)) if gap > PAUSE_S)
    confidence = sum(w["p"] if w.get("p") is not None else 0.85 for w in words) / n
    q = 1.0 - 0.25 * fillers / n - min(0.3, 0.1 * stumbles) - 0.15 * (paused / span if span > 0 else 0.0)
    return round(min(1.0, max(0.0, q * confidence)), 3)


def _stumble_runs(toks: list[str]) -> int:
    """How many times a run of one to three words is said again right away ("the water was the water was")."""
    runs = k = 0
    while k < len(toks):
        hit = next((n for n in (3, 2, 1) if k + 2 * n <= len(toks) and toks[k:k + n] == toks[k + n:k + 2 * n]), 0)
        runs += 1 if hit else 0
        k += hit or 1
    return runs


# ------------------------------------------------------------------ matching
def match(lines: list[dict], transcripts: dict[str, list[dict]], file_order: list[str]) -> dict:
    """Find every spoken line of the script in the footage and choose its best take.

    `transcripts[asset_id]` is a video's timed words ({"start", "end", "w", "p"?}, as transcribe.flatten_words
    gives them) and `file_order` the media bin's order (a later file is a later take). Returns {"lines": one match
    per script line ({"n", "kind", "status", "coverage", "take", "takes"}: status matched / weak / missing /
    skipped / heading / direction, `take` the chosen Take, `takes` up to four other takes, best first), "clips":
    the chosen takes in script order, neighbours chained ({"asset_id", "i0", "i1", "lines", "start", "end"}),
    "unused": {asset_id: [[i0, i1], ...]} word spans of three or more words no take uses, "stats"}. A Take is
    {"asset_id", "i0", "i1", "start", "end", "coverage", "quality", "said", "fillers", "stumbles"} with i0..i1
    inclusive word indices into that transcript.
    """
    order = [a for a in file_order if a in transcripts] + [a for a in transcripts if a not in file_order]
    footage = _footage(order, transcripts)
    used = {aid: bytearray(len(transcripts[aid])) for aid in order}
    matches = [_match_line(line, footage, transcripts, used) for line in lines]
    unused = {aid: _unused(used[aid]) for aid in order}
    counts = Counter(m["status"] for m in matches)
    stats = {key: counts.get(key, 0) for key in ("matched", "weak", "missing", "skipped")}
    stats["alternatives"] = sum(len(m["takes"]) for m in matches)
    stats["off_script_words"] = sum(i1 - i0 + 1 for spans in unused.values() for i0, i1 in spans)
    stats["off_script_s"] = round(sum(transcripts[aid][i1]["end"] - transcripts[aid][i0]["start"]
                                      for aid, spans in unused.items() for i0, i1 in spans), 2)
    return {"lines": matches, "clips": _clips(matches), "unused": unused, "stats": stats}


def _footage(order: list[str], transcripts: dict[str, list[dict]]) -> dict:
    """Every transcript normalised once: its token stream, the word each token came from, and where every token
    occurs across the footage (the fewer places, the better an anchor it is)."""
    toks: dict[str, list[str]] = {}
    t2w: dict[str, list[int]] = {}
    index: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for ai, aid in enumerate(order):
        ts: list[str] = []
        tw: list[int] = []
        for wi, word in enumerate(transcripts[aid]):
            for t in normalize(str(word["w"])):
                index[t].append((ai, len(ts)))
                ts.append(t)
                tw.append(wi)
        toks[aid], t2w[aid] = ts, tw
    return {"order": order, "rank": {aid: i for i, aid in enumerate(order)}, "toks": toks, "t2w": t2w,
            "index": index}


def _match_line(line: dict, footage: dict, transcripts: dict[str, list[dict]], used: dict[str, bytearray]) -> dict:
    """One script line: its candidate takes scored and ranked, the best one not already used by an earlier line
    chosen and marked used, the others kept as alternatives."""
    kind, n = line.get("kind", "line"), line["n"]
    if kind != "line":
        return {"n": n, "kind": kind, "status": kind, "coverage": 0.0, "take": None, "takes": []}
    toks = line.get("tokens") or normalize(line.get("text", ""))
    if len(toks) < 2:
        return {"n": n, "kind": kind, "status": "skipped", "coverage": 0.0, "take": None, "takes": []}
    spec = {"toks": toks, "count": Counter(toks), "slack": max(3, len(toks) // 3)}
    scored = [c for c in (_score(spec, footage, transcripts, w) for w in _windows(spec, footage["index"])) if c]
    closest = max((c["coverage"] for c in scored), default=0.0)
    ranked = _distinct(sorted((c for c in scored if c["coverage"] >= WEAK),
                              key=lambda c: _rank(c, footage["rank"]), reverse=True))
    take = next((c for c in ranked if _free(used[c["asset_id"]], c)), None)
    if take:
        used[take["asset_id"]][take["i0"]:take["i1"] + 1] = b"\x01" * _length(take)
    status = "missing" if take is None else "matched" if take["coverage"] >= TAKE else "weak"
    return {"n": n, "kind": kind, "status": status, "coverage": take["coverage"] if take else closest,
            "take": take, "takes": [c for c in ranked if c is not take][:MAX_ALTERNATIVES]}


def _anchors(toks: list[str], index: dict) -> list[tuple[str, int]]:
    """The line's rarest words in the footage (at most MAX_ANCHORS; stopwords only when nothing else is there),
    each with its place in the line."""
    place: dict[str, int] = {}
    for k, t in enumerate(toks):
        if t in index and t not in place:
            place[t] = k
    ranked = sorted(place, key=lambda t: (len(index[t]), place[t]))
    content = [t for t in ranked if t not in STOPWORDS]
    return [(t, place[t]) for t in (content or ranked)[:MAX_ANCHORS]]


def _windows(spec: dict, index: dict) -> list[tuple[int, int, int]]:
    """Where the line may have been said, as (asset, first token, last token + 1): every occurrence of an anchor
    says where the line would start, starts within `slack` of each other are one place, and at most MAX_WINDOWS
    places (the ones with most anchors) are looked at."""
    length, slack = len(spec["toks"]), spec["slack"]
    starts: dict[int, list[int]] = defaultdict(list)
    for t, k in _anchors(spec["toks"], index):
        for ai, pos in index[t]:
            starts[ai].append(pos - k - slack)
    out: list[tuple[int, int, int, int]] = []
    for ai, found in starts.items():
        found.sort()
        lo = last = found[0]
        hits = 0
        for s in found:
            if s - last > slack:
                out.append((ai, lo, last + length + 2 * slack, hits))
                lo, hits = s, 0
            hits += 1
            last = s
        out.append((ai, lo, last + length + 2 * slack, hits))
    out.sort(key=lambda w: (-w[3], w[0], w[1]))
    return [w[:3] for w in out[:MAX_WINDOWS]]


def _score(spec: dict, footage: dict, transcripts: dict[str, list[dict]], window: tuple[int, int, int]) -> dict | None:
    """Align the line with one window of a transcript: a Take, or None when fewer than two words match in order.
    The take runs from the first matched word to the last."""
    ai, lo, hi = window
    aid = footage["order"][ai]
    toks = footage["toks"][aid]
    lo, hi = max(0, lo), min(len(toks), hi)
    wtoks = toks[lo:hi]
    if sum((spec["count"] & Counter(wtoks)).values()) < max(2, WEAK * len(spec["toks"])):
        return None  # not even the words are there, whatever their order
    blocks = _blocks(spec["toks"], wtoks, spec["slack"])
    matched = sum(b.size for b in blocks)
    if matched < 2:
        return None
    words = transcripts[aid]
    i0 = footage["t2w"][aid][lo + blocks[0].b]
    i1 = footage["t2w"][aid][lo + blocks[-1].b + blocks[-1].size - 1]
    span = words[i0:i1 + 1]
    clean = [b for b in (_bare(w["w"]) for w in span if not is_filler(w)) if b]
    return {"asset_id": aid, "i0": i0, "i1": i1, "start": span[0]["start"], "end": span[-1]["end"],
            "coverage": round(matched / len(spec["toks"]), 3), "quality": take_quality(span), "said": _said(span),
            "fillers": sum(1 for w in span if is_filler(w)), "stumbles": _stumble_runs(clean)}


def _blocks(a: list[str], b: list[str], slack: int) -> list:
    """The runs of words the line and the window share, in order; a lone word more than `slack` words away from
    the rest at either end is a stray, not part of the take."""
    blocks = [m for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if m.size]
    while len(blocks) > 1 and blocks[0].size == 1 and blocks[1].b - blocks[0].b - 1 > slack:
        blocks.pop(0)
    while len(blocks) > 1 and blocks[-1].size == 1 and blocks[-1].b - (blocks[-2].b + blocks[-2].size) > slack:
        blocks.pop()
    return blocks


def _rank(c: dict, rank: dict[str, int]) -> tuple:
    """Best take first: coverage (to a tenth), then quality, then the later take (later file, later start), then
    the shorter one."""
    return (round(c["coverage"], 1), c["quality"], rank[c["asset_id"]], c["start"], -(c["end"] - c["start"]))


def _length(c: dict) -> int:
    return c["i1"] - c["i0"] + 1


def _overlap(a: dict, b: dict) -> int:
    if a["asset_id"] != b["asset_id"]:
        return 0
    return max(0, min(a["i1"], b["i1"]) - max(a["i0"], b["i0"]) + 1)


def _distinct(ranked: list[dict]) -> list[dict]:
    """Drop a take that is the same stretch of speech as a better one (sharing over half of the shorter)."""
    out: list[dict] = []
    for c in ranked:
        if not any(_overlap(c, k) > SAME_SHARE * min(_length(c), _length(k)) for k in out):
            out.append(c)
    return out


def _free(used: bytearray, c: dict) -> bool:
    return sum(used[c["i0"]:c["i1"] + 1]) <= USED_SHARE * _length(c)


def _said(span: list[dict]) -> str:
    text = " ".join(str(w["w"]) for w in span)
    return text if len(text) <= SAID_CHARS else text[:SAID_CHARS - 1].rstrip() + "…"


def _clips(matches: list[dict]) -> list[dict]:
    """The chosen takes in script order; lines said one after another in the same recording (the next take within
    CHAIN_GAP_S of the previous) make one clip, so a paragraph read in one go is one clip and not ten. A heading
    starts a new clip, so its chapter begins exactly there."""
    clips: list[dict] = []
    clip: dict | None = None
    for m in matches:
        if m["kind"] == "heading":
            clip = None
        t = m["take"]
        if not t:
            continue
        same_file = clip is not None and clip["asset_id"] == t["asset_id"] and t["i0"] > clip["i1"]
        if same_file and t["start"] - clip["end"] <= CHAIN_GAP_S:
            clip.update(i1=t["i1"], end=t["end"])
            clip["lines"].append(m["n"])
        else:
            clip = {"asset_id": t["asset_id"], "i0": t["i0"], "i1": t["i1"], "lines": [m["n"]], "start": t["start"],
                    "end": t["end"]}
            clips.append(clip)
    return clips


def _unused(used: bytearray) -> list[list[int]]:
    """Maximal stretches of MIN_UNUSED or more words no chosen take covers."""
    spans: list[list[int]] = []
    start: int | None = None
    for i, taken in enumerate(used):
        if not taken and start is None:
            start = i
        elif taken and start is not None:
            if i - start >= MIN_UNUSED:
                spans.append([start, i - 1])
            start = None
    if start is not None and len(used) - start >= MIN_UNUSED:
        spans.append([start, len(used) - 1])
    return spans


# ------------------------------------------------------------------ in words
def report(result: dict, lines: list[dict]) -> list[str]:
    """What following the script did, in plain words for the plan's notes (only the sentences that apply)."""
    s = result["stats"]
    total = sum(1 for ln in lines if ln.get("kind", "line") == "line") or (s["matched"] + s["weak"] + s["missing"])
    if not total:
        return ["Your script has no spoken lines to look for in the footage (headings and directions are never said)."]
    found = s["matched"] + s["weak"]
    partly = f" ({s['weak']} of them only partly)" if s["weak"] else ""
    notes = [f"Followed your script: {found} of {total} {_plural(total, 'line')} were found in the footage{partly}."]
    missing = [m["n"] for m in result["lines"] if m["status"] == "missing"]
    if missing:
        notes.append(f"{len(missing)} {_plural(len(missing), 'line has', 'lines have')} no take in the footage: "
                     f"{_numbered('line', missing)} (see Script).")
    if total >= 5 and found < 0.3 * total:
        notes.append("Most of the script was not found: check that the script and the footage are in the same "
                     "language and that the right files are in the media bin.")
    if s["alternatives"]:
        n = s["alternatives"]
        notes.append(f"Kept {n} other {_plural(n, 'take')} switched off after the take that plays; Use this take "
                     f"swaps {'it' if n == 1 else 'them'}.")
    if s["off_script_s"] >= 1:
        notes.append(f"Left out {_duration(s['off_script_s'])} said in the footage that is not in the script "
                     "(switched off at the end).")
    if s["skipped"]:
        notes.append(f"Skipped {s['skipped']} one-word {_plural(s['skipped'], 'line')}: too short to look for.")
    return notes


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def _numbered(word: str, numbers: list[int], at_most: int = 8) -> str:
    """"line 7", "lines 7 and 20", "lines 7, 20 and 31", "lines 7, 20, ... and 12 more"."""
    shown = [str(n) for n in numbers[:at_most]]
    more = len(numbers) - len(shown)
    if more:
        return f"{word}s {', '.join(shown)} and {more} more"
    if len(shown) == 1:
        return f"{word} {shown[0]}"
    return f"{word}s {', '.join(shown[:-1])} and {shown[-1]}"


def _duration(seconds: float) -> str:
    total = round(seconds)
    h, m, s = total // 3600, total % 3600 // 60, total % 60
    if h:
        return f"{h} h {m} min" if m else f"{h} h"
    if m:
        return f"{m} min {s} s" if s else f"{m} min"
    return f"{s} s"
