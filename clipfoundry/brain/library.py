"""Everything ClipForge AI can look up in words, behind one search (docs/clipforge/CLIPFORGE_AI.md, "What it
knows"): its craft know-how (brain/knowhow.py), its guide to ClipForge itself (brain/appguide.py) and the advice in
the owner's switched-on skills (studio/skills.py).

Before this, the chat read one or two craft playbooks picked by loose word matching and nothing else: it could not
say how to clip a live stream, and the 59 skills the owner imported were never read by anything. `search` ranks all
three sources for a question (or for a job such as picking clips or writing a post), picks the lines of each entry
that fit best inside a character budget, and gives the prompt block and what was used. `answer` is the chat's reply
when no model is set up: the best entry, in its own words, with the page to open.

What is read from a skill is only its advice lines, the ones the importer kept as plain text ("not an editing choice
ClipForge applies yet"); lines the importer refused (commands, secrets, accounts, publishing) and links are never
read. Brain notes are not part of the library: by their own rule they are compiled into bounded choices on this
computer and never shown to a model (autopilot/knowledge_style.py).

The meaning model (clipfoundry/embedder.py), when it is installed, adds "means the same in other words" to the
word match; without it the search is words, stems and word pairs only, and still works.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field

from ..pipeline.text_utils import content_tokens
from . import appguide, knowhow

SOURCES = ("knowhow", "guide", "skill")
ADVICE_WHY = "not an editing choice ClipForge applies yet"   # studio/skills.py: a readable advice line, kept as text
SKILLS_HEADER = ("From the owner's switched-on skills (guides the owner imported; they win over the built-in "
                 "know-how, and what the owner said wins over them):")
SELECT_MIN = 0.22      # share of a question's weighted words an entry must cover to be read for it
ANSWER_MIN = 0.30      # ... to answer the question on its own, without a model
WEAK = 0.4             # a word that only appears inside an entry's lines, against one the entry is about
OFF_TASK = 0.6         # a craft playbook not meant for the job counts for less (as in knowhow.select)
SKILL_MIN = 0.5        # the share of a question a skill must be about (its name, its topics) to be read for it
SKILL_PRIOR = 0.85
HOWTO_SKILL = 0.7
PHRASE_BONUS = 0.15
TITLE_BONUS = 0.1
SKILL_LINES = 5        # the lines one skill adds to a prompt at most
SKILL_MODES = {"clips": ("highlights", "full_stories"), "post": ("highlights", "full_stories"),
               "short": (), "smart_edit": ("full_video",), "finish": ("full_video",), "change": ("full_video",)}
# "How do I …", "where is …": the owner wants the page and the button, so the guide to the app goes first.
_HOWTO = re.compile(r"\b(how (do|can|to|would) (i|you|we)?|how to|where( do| can| is| are)?|can (i|you|it)|does it|"
                    r"is there|which (page|button|setting)|set ?up|turn (on|off)|switch (on|off))\b", re.I)
# "What makes a good hook", "the best titles": a question about the craft, so the playbook goes first even when the
# words also name a page.
_CRAFT = re.compile(r"\b(good|best|better|great|viral|engaging|should|tips?|ideas?|advice|improve|more views|"
                    r"what makes|why do)\b", re.I)
BOOST = 1.2
# "where is the button to change captions?", "which button do I press?": pressing one of ClipForge's buttons, so a
# word that counts only beside others ("buttons" beside "text") does not count
_PRESSING = re.compile(r"\b(?:which|what) (?:\w+ )?buttons?\b|\bbuttons? (?:to|for)\b|"
                       r"\b(?:captions?|subtitles?|text|words?) buttons?\b|"
                       r"\b(?:press|click|tap|hit|find)\w* (?:on )?(?:the |a |that |this |my )?(?:\w+ )?buttons?\b",
                       re.I)


@dataclass(frozen=True)
class Entry:
    id: str                     # "sound", "guide:live", "skill:<row id>"
    source: str                 # knowhow | guide | skill
    title: str
    lines: tuple[str, ...]
    strong: frozenset           # the words it is about (its title and the words a question may use for it)
    terms: frozenset            # strong plus every word of its lines
    named: frozenset = frozenset()          # the words of its title alone
    together: tuple = ()                    # (word, words): the word counts in full only beside one of the words
    tasks: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    link: tuple[str, str] | None = None     # (label, href)


@dataclass
class Hit:
    entry: Entry
    score: float
    lines: list[str]

    @property
    def text(self) -> str:
        return f"{self.entry.title}: " + " ".join(self.lines)


@dataclass
class Found:
    """What a question or a job read from the library, best first, and the prompt block for a model."""
    hits: list[Hit] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.hits

    def of(self, source: str) -> list[Hit]:
        return [h for h in self.hits if h.entry.source == source]

    @property
    def ids(self) -> list[str]:
        return [h.entry.id for h in self.hits]

    def prompt(self) -> str:
        """One block per source, the built-in craft first (so a reader that knows `knowhow.HEADER` still finds it),
        then the app guide, then the owner's skills, which are told to win."""
        out = []
        for source, header in (("knowhow", knowhow.HEADER), ("guide", appguide.HEADER), ("skill", SKILLS_HEADER)):
            rows = self.of(source)
            if rows:
                out.append(header + "\n" + "\n".join(h.text for h in rows))
        return "\n".join(out)

    def snapshot(self) -> list[dict]:
        """What the answer shows it used, best first: a craft playbook under its own id ("sound"), a guide section
        as "guide:…", a skill as "skill:…", each with its source."""
        return [{"id": h.entry.id, "title": h.entry.title, "score": round(h.score, 3), "source": h.entry.source}
                for h in self.hits]

    def links(self, limit: int = 2) -> list[dict]:
        out: list[dict] = []
        for h in self.hits:
            if h.entry.link and all(x["href"] != h.entry.link[1] for x in out):
                out.append({"label": h.entry.link[0], "href": h.entry.link[1]})
        return out[:limit]


def howto(query: str) -> bool:
    """True for "how do I …", "where is …", "can I …": a question about using ClipForge, not about the craft."""
    return bool(_HOWTO.search(query or "")) and not _CRAFT.search(query or "")


# ------------------------------------------------------------------ the entries
_SUFFIXES = ("nesses", "ness", "ings", "ing", "edly", "ed", "ies", "es", "s", "ly")  # not "er": cover, paper


def stem(word: str) -> str:
    """A word without its ending, so "titles", "titled" and "title" meet, and "loud" finds "loudness". Rough on
    purpose: it only has to be the same for the forms of one word, and different for "model" and "modes"."""
    w = word
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)] + ("y" if suf == "ies" else "")
            break
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
        w = w[:-1]                       # "clipp(ing)" -> "clip"
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]                       # "make" and "mak(ing)"
    return w


def _stems(text: str) -> list[str]:
    return [stem(t) for t in content_tokens(text or "") if t not in knowhow.GENERIC]


def _terms(text: str) -> set[str]:
    """What a text is made of for matching: the stems of its content words (the generic ones left out) and each
    pair of neighbours as a phrase."""
    st = _stems(text)
    return set(st) | {f"{a}_{b}" for a, b in zip(st, st[1:])}


def _entry(id_: str, source: str, title: str, lines, words, about: str = "", **kw) -> Entry:
    """`words` are what the entry is about (they count in full); `about` is a summary that is matched like its lines
    but never shown."""
    strong, together = set(_terms(title)), []
    for w in words:
        if w.startswith("="):            # a phrase that counts only whole ("=cover the bottom": not "bottom" alone)
            strong |= {t for t in _terms(w[1:]) if "_" in t}
        elif w.startswith("+"):          # "+buttons: text cover ...": "buttons" counts only beside one of those
            head, _, rest = w[1:].partition(":")
            together += [(t, frozenset(_stems(rest))) for t in _stems(head)]
        else:
            strong |= _terms(w)
    return Entry(id_, source, title, tuple(lines), frozenset(strong),
                 frozenset(strong | _terms(" ".join((about, *lines)))), frozenset(_terms(title)),
                 together=tuple(together), **kw)


def _builtin() -> list[Entry]:
    out = [_entry(t.id, "knowhow", t.title, t.lines, t.words, t.summary, tasks=t.tasks) for t in knowhow.TOPICS]
    for s in appguide.SECTIONS:
        page = appguide.PAGES.get(s.page)
        out.append(_entry(f"guide:{s.id}", "guide", s.title, s.lines, s.words, tasks=("chat",),
                          link=(f"Open {page[0]}", page[1]) if page else None))
    return out


_BUILTIN = _builtin()


def skill_lines(row: dict) -> list[str]:
    """A skill's advice as plain lines: only what the importer kept as readable text, never a refused line, a link
    or a contradicted choice. The importer's checks run again here, so a skill kept before they covered a line
    (or a file that names a reason of its own) cannot put a refused line in front of a model."""
    from ..studio.skills import refused

    out = []
    for u in row.get("unsupported") or []:
        text = " ".join(str(u.get("text") or "").split()) if isinstance(u, dict) else ""
        if text and u.get("why") == ADVICE_WHY and not refused(text):
            out.append(text)
    return out


def _skill_entry(row: dict) -> Entry | None:
    lines = skill_lines(row)
    if not lines:
        return None
    from ..studio.skills import match_words, shown_name

    # the name the file gave counts in full for finding the skill, even when a model may only see "Skill"
    return _entry(f"skill:{row['id']}", "skill", shown_name(row), lines, match_words(row),
                  str(row.get("description") or ""), modes=tuple(row.get("modes") or ()),
                  link=("Open Brain → More → Skills", "#/brain/skills"))


@dataclass
class _Corpus:
    entries: list[Entry]
    df: dict[str, int]

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((len(self.entries) + 1) / (1 + df)) if df else 0.0


_lock = threading.Lock()
_cache: dict[str, tuple[tuple, _Corpus]] = {}


def _corpus(ws: str) -> _Corpus:
    """The built-in entries and the workspace's switched-on skills, with how many entries use each word. Built again
    only when a skill was added, changed or switched."""
    rows: list[dict] = []
    if ws:
        try:
            from ..studio import skills

            rows = skills.enabled_skills(ws)
        except Exception:  # noqa: BLE001 - a missing table (an old database mid-upgrade) reads as no skills
            rows = []
    sig = tuple((r["id"], r.get("revision"), r.get("updated_at")) for r in rows)
    with _lock:
        hit = _cache.get(ws)
        if hit and hit[0] == sig:
            return hit[1]
    entries = list(_BUILTIN) + [e for e in (_skill_entry(r) for r in rows) if e]
    df: dict[str, int] = {}
    for e in entries:
        for t in e.terms:
            df[t] = df.get(t, 0) + 1
    corpus = _Corpus(entries, df)
    with _lock:
        _cache[ws] = (sig, corpus)
    return corpus


# ------------------------------------------------------------------ ranking
Unit = tuple[str, float]   # one word (by its stem) or one phrase of the question, and its weight


@dataclass
class _Query:
    words: list[Unit]
    phrases: list[Unit]
    said: frozenset = frozenset()       # the question's words another word may count beside (Entry.together)

    @property
    def all(self) -> list[Unit]:
        return self.words + self.phrases


def _units(query: str, corpus: _Corpus) -> _Query:
    """The question as weighted words and phrases (two neighbouring words). Rarer ones weigh more; those nothing in
    the library uses do not count, so a question about penguins and loudness is still a loudness question."""
    st = _stems(query)

    def known(terms: list[str]) -> list[Unit]:
        out, seen = [], set()
        for t in terms:
            w = corpus.idf(t)
            if w > 0 and t not in seen:
                seen.add(t)
                out.append((t, w))
        return out

    pressing = bool(_PRESSING.search(query or ""))
    # a question about pressing a button ("is there a button to hide captions?") is about the app: "button" counts
    # neither beside other words nor in a pair ("=buttons hide" is the platforms' buttons covering text)
    pairs = [f"{a}_{b}" for a, b in zip(st, st[1:]) if not (pressing and "button" in (a, b))]
    return _Query(known(st), known(pairs), frozenset() if pressing else frozenset(st))


def _score(q: _Query, e: Entry) -> tuple[float, float]:
    """(how well the entry covers the question, the share of the question's words that the entry is about).
    Coverage is the weighted share of the words, a word the entry is about counting in full and one that only
    appears in its lines in part; a phrase the entry also has adds a little and never counts against the others."""
    total = sum(w for _, w in q.words)
    if total <= 0:
        return 0.0, 0.0
    got, about = 0.0, 0.0
    # a word the entry is about only inside a phrase ("side buttons") counts in full where the question says it so
    held = {part for t, _ in q.phrases if t in e.strong for part in t.split("_")}
    held |= {t for t, beside in e.together if beside & q.said}     # "buttons" beside "text" or "hidden"
    for t, w in q.words:
        if t in e.strong or t in held:
            got, about = got + w, about + w
        elif t in e.terms:
            got += w * WEAK
    extra = sum(w for _, w in q.phrases)
    if extra > 0:
        hit = sum(w * (1.0 if t in e.strong else WEAK) for t, w in q.phrases if t in e.terms)
        got += PHRASE_BONUS * total * hit / extra
    return got / total, about / total


def _meaning(query: str, entries: list[Entry], settings: dict | None) -> dict[str, float]:
    """With the meaning model: how close each entry's subject is to the question (0-1 above the floor where two
    texts count as related). Empty without the model."""
    try:
        from .. import embedder
        from . import meaning

        if not query.strip() or not embedder.usable(settings):
            return {}
        texts = [query] + [f"{e.title}. {e.lines[0] if e.lines else ''}"[:300] for e in entries]
        vecs = embedder.embed_or_none(texts, settings)
        if vecs is None:
            return {}
        floor = meaning.min_similar(embedder.MODEL)
        qv = vecs[0]
        return {e.id: max(0.0, (float(qv @ v) - floor) / (1.0 - floor)) for e, v in zip(entries, vecs[1:])}
    except Exception:  # noqa: BLE001 - the meaning model is an extra; the word match stands on its own
        return {}


def _pick_lines(e: Entry, q: _Query, budget: int) -> list[str]:
    """The entry's lines that fit the question best, in their own order, inside `budget` characters. A built-in
    section is short and read whole when it fits; a skill gives its best few lines (its first lines, the key rules,
    when no line matches a word)."""
    room = budget - len(e.title) - 2
    if e.source != "skill" and sum(len(x) + 1 for x in e.lines) <= room:
        return list(e.lines)
    scored = []
    for i, line in enumerate(e.lines):
        ts = _terms(line)
        scored.append((sum(w for t, w in q.all if t in ts), i, line))
    best = sorted(scored, key=lambda x: (-x[0], x[1]))
    if not best or best[0][0] <= 0:
        best = scored  # nothing matched a word: the opening lines
    cap = SKILL_LINES if e.source == "skill" else len(e.lines)
    chosen, used = [], 0
    for s, i, line in best:
        if len(chosen) >= cap:
            break
        if used + len(line) + 1 > room:
            continue
        chosen.append((i, line))
        used += len(line) + 1
    return [line for _, line in sorted(chosen)]


def search(query: str, ws: str = "", *, task: str = "chat", sources: tuple[str, ...] = SOURCES, limit: int = 4,
           budget_chars: int = 1800, settings: dict | None = None, fill: bool = False,
           meaning: bool = True) -> Found:
    """The entries that fit `query` for `task`, best first, each cut to its best lines, inside `budget_chars`
    characters of prompt text. With `fill`, a job whose words pick nothing still reads its default playbooks
    (knowhow.DEFAULTS)."""
    corpus = _corpus(ws)
    pool = [e for e in corpus.entries if e.source in sources]
    want = SKILL_MODES.get(task)
    if want is not None:
        pool = [e for e in pool if e.source != "skill" or (want and (not e.modes or set(e.modes) & set(want)))]
    if task != "chat":
        pool = [e for e in pool if e.source != "guide"]  # the guide is for the owner's questions, not for a job
    q = _units(query, corpus)
    craft = bool(_CRAFT.search(query or ""))
    asks_how = howto(query)
    close = _meaning(query or "", pool, settings) if (meaning and q.words) else {}
    ranked: list[tuple[float, int, Entry]] = []
    for n, e in enumerate(pool):
        s, about = _score(q, e)
        if e.source == "skill":
            # a long guide touches many words in passing: it must be about half of what was asked; a built-in
            # section that fits as well goes first (it is short; the skill then adds its best lines), and a
            # "where is the button" question is not what an editing guide is for
            s *= SKILL_PRIOR * (HOWTO_SKILL if asks_how else 1.0)
            if about < SKILL_MIN or s < SKILL_MIN:
                continue
        if e.source == "knowhow" and task in knowhow.TASKS and task not in e.tasks:
            s *= OFF_TASK
        if (e.source == "guide" and asks_how) or (e.source == "knowhow" and craft):
            s *= BOOST
        s += 0.35 * close.get(e.id, 0.0)
        if s > 0 and any(t in e.named for t, _ in q.words):
            s += TITLE_BONUS  # two entries about the same word: the one named after it goes first
        if s >= SELECT_MIN:
            ranked.append((s, n, e))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    if fill and task in knowhow.DEFAULTS and "knowhow" in sources:
        have = {e.id for _, _, e in ranked}
        by_id = {e.id: e for e in pool}
        ranked += [(0.0, 10 ** 6, by_id[i]) for i in knowhow.DEFAULTS[task] if i in by_id and i not in have]
    # a question reads from more than one source (the craft and the page); a job reads its craft first
    per_source = max(1, math.ceil(limit / 2))
    cap = {"knowhow": per_source if task == "chat" else limit, "guide": per_source, "skill": per_source}
    hits: list[Hit] = []
    count: dict[str, int] = {}
    headers = {"knowhow": len(knowhow.HEADER), "guide": len(appguide.HEADER), "skill": len(SKILLS_HEADER)}
    used = 0
    for s, _, e in ranked:
        if len(hits) >= max(0, limit):
            break
        if count.get(e.source, 0) >= cap[e.source]:
            continue
        head = 0 if count.get(e.source) else headers[e.source] + 1
        room = budget_chars - used - head
        each = max(260, int(budget_chars / max(1, min(limit, 3))))
        lines = _pick_lines(e, q, min(room, each if e.source == "skill" else room))
        if not lines:
            continue
        hit = Hit(e, s, lines)
        if used + head + len(hit.text) + 1 > budget_chars:
            continue
        hits.append(hit)
        count[e.source] = count.get(e.source, 0) + 1
        used += head + len(hit.text) + 1
    return Found(hits)


# ------------------------------------------------------------------ answering without a model
def answer(query: str, ws: str = "") -> dict | None:
    """The chat's reply to a question when no model is set up: the entry that fits best, in its own words, with a
    second one when it is nearly as good, and the pages to open. None when nothing fits well enough."""
    found = search(query, ws, task="chat", limit=2, budget_chars=2400, meaning=False)
    hits = [h for h in found.hits if h.score >= ANSWER_MIN]
    if not hits:
        return None
    hits = hits[:1] + [h for h in hits[1:]
                       if h.score >= 0.75 * hits[0].score and h.entry.source != hits[0].entry.source]
    parts = []
    for h in hits:
        lines = "\n".join(f"- {line}" for line in h.lines)
        lead = {"knowhow": f"From my built-in know-how, {h.entry.title.lower()}:",
                "guide": f"{h.entry.title}:",
                "skill": f"From your skill “{h.entry.title}”:"}[h.entry.source]
        parts.append(f"{lead}\n{lines}")
    tail = ("What you tell me with “remember: …” always wins over this. With a model set up (Settings → ClipForge "
            "AI) I can answer with your own memories too.")
    picked = Found(hits)
    return {"text": "\n\n".join(parts) + "\n" + tail, "found": picked, "links": picked.links()}
