"""Caption looks for short videos made to be watched on a phone (animated shorts: docs/clipforge/ANIMATED_SHORTS.md).

The captions of the shorts people watch to the end are part of the picture: two or three big words at a time in a
heavy font with a thick outline, each group popping in, the word being said lit in a colour and a little bigger, the
words a narrator leans on in a second colour, all of it low in the middle of the frame where neither the subject nor
the apps' buttons are. The editor's three caption styles (pipeline/captions.py) were made for long videos; a plan
whose captions name a `look` from here is drawn this way instead. Everything else about captions stays the plan's:
on or off, the size, the position, whether the spoken word is lit.

A plan may also carry a `hook`: {"text": ..., "ms": 3000}, the headline over the first seconds of the video (what
the short is about, in a few words), drawn as a label near the top, below the apps' top bar.

Events are (start, end, text) in seconds, or (start, end, text, style) for the headline; the text carries ASS tags.
Animations use \\t with explicit times, so an event that is cut by the edge of a render piece goes on where it was
(`shift`), never starting again.
"""
from __future__ import annotations

import re

from ..pipeline.captions import _FILLER, hex_to_ass

# font: a family in config.FONTS_DIR; size: pixels on a 1080-wide frame; pop: the scale a group starts from and
# overshoots to; word: how much bigger the word being said is; colours: the words, the word being said, the words
# leaned on, the outline.
LOOKS = {
    "pop": {"name": "Pop", "font": "Poppins Black", "bold": 0, "size": 104, "upper": True, "max_words": 3,
            "max_chars": 16, "outline": 9, "shadow": 4, "spacing": 0, "pop": (80, 106), "word": 110,
            "ink": "#FFFFFF", "active": "#FFE500", "lift": "#3CFF6B", "edge": "#000000"},
    "impact": {"name": "Impact", "font": "Anton", "bold": 0, "size": 132, "upper": True, "max_words": 2,
               "max_chars": 13, "outline": 9, "shadow": 5, "spacing": 1, "pop": (78, 108), "word": 108,
               "ink": "#FFFFFF", "active": "#FFE500", "lift": "#FF5E5B", "edge": "#000000"},
    "one": {"name": "One word", "font": "Poppins Black", "bold": 0, "size": 136, "upper": True, "max_words": 1,
            "max_chars": 14, "outline": 10, "shadow": 5, "spacing": 0, "pop": (70, 110), "word": 100,
            "ink": "#FFFFFF", "active": "#FFFFFF", "lift": "#FFE500", "edge": "#000000"},
    "comic": {"name": "Comic", "font": "Bangers", "bold": 0, "size": 128, "upper": True, "max_words": 3,
              "max_chars": 16, "outline": 9, "shadow": 6, "spacing": 2, "pop": (76, 110), "word": 110,
              "ink": "#FFFFFF", "active": "#FFD23F", "lift": "#FF5E5B", "edge": "#000000"},
    "soft": {"name": "Soft", "font": "Fredoka", "bold": -1, "size": 92, "upper": False, "max_words": 4,
             "max_chars": 22, "outline": 7, "shadow": 2, "spacing": 0, "pop": (90, 103), "word": 106,
             "ink": "#FFFFFF", "active": "#FFD27A", "lift": "#FFB37A", "edge": "#3B2616"},
}
HOOK_TOP = 0.13            # the headline starts this share of the height down (below the apps' top bar)
HOOK_MARGIN = 96           # its left and right margins on a 1080-wide frame
HOOK_SIZES = ((22, 76), (40, 66), (10 ** 9, 56))   # (up to this many characters, font size)
HOOK_MS = (1500, 8000)     # how long a headline may show
HOOK_CHARS = 80
MARGIN = 110               # the captions' left and right margins on a 1080-wide frame (clear of the buttons)
_T = re.compile(r"\\t\((-?\d+),(-?\d+),")


def get(captions: dict | None) -> dict | None:
    """The caption look a plan's captions ask for, or None (the editor's own styles)."""
    return LOOKS.get(str((captions or {}).get("look") or ""))


def hook_of(plan: dict | None) -> dict | None:
    """The plan's headline as {"text", "ms"}, or None when it has none."""
    hook = (plan or {}).get("hook")
    if not isinstance(hook, dict):
        return None
    text = " ".join(str(hook.get("text") or "").split())[:HOOK_CHARS]
    if not text:
        return None
    try:
        ms = int(hook.get("ms") or 3000)
    except (TypeError, ValueError):
        ms = 3000
    return {"text": text, "ms": min(HOOK_MS[1], max(HOOK_MS[0], ms))}


def _escape(text: str) -> str:
    return str(text).strip().replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


_SMALL = frozenset("a an the to of in on at by for and or but so as is it its my his her our your their with "
                   "from that this".split())


def chunks(words: list[dict], look: dict) -> list[list[dict]]:
    """Timed words in the groups shown together: a few words, never across a breath, ending where a phrase ends,
    and never ending on a little word that belongs to what comes next ("the", "to", "of")."""
    words = [w for w in words if str(w.get("w") or "").strip() and not _FILLER.match(w["w"].strip())]
    out: list[list[dict]] = []
    cur: list[dict] = []
    chars = 0

    def close(next_word: dict | None) -> list[dict]:
        """End the group; the little word it would end on starts the next one instead."""
        carry: list[dict] = []
        if next_word is not None and len(cur) >= 2 and look["max_words"] > 1 and \
                cur[-1]["w"].strip().lower() in _SMALL and next_word["start"] - cur[-1]["end"] <= 0.6 and \
                any(x["w"].strip().lower() not in _SMALL for x in cur[:-1]):
            carry = [cur.pop()]
        out.append(list(cur))
        return carry

    for w in words:
        text = w["w"].strip()
        if cur and (len(cur) >= look["max_words"] or chars + len(text) + 1 > look["max_chars"]
                    or w["start"] - cur[-1]["end"] > 0.6):
            cur = close(w)
            chars = sum(len(x["w"].strip()) + 1 for x in cur)
        cur.append(w)
        chars += len(text) + 1
        if text.endswith((".", "?", "!", ",", ";", ":")):
            out.append(cur)
            cur, chars = [], 0
    if cur:
        out.append(cur)
    return out


def events(words: list[dict], captions: dict) -> list[tuple]:
    """The caption events of these words in the plan's caption look: each group pops in; with `highlight` the word
    being said is lit (one event per word while the group shows, held through short gaps so nothing flickers); the
    words marked `em` keep their own colour."""
    look = get(captions) or LOOKS["pop"]
    ink, active, lift = hex_to_ass(look["ink"]), hex_to_ass(look["active"]), hex_to_ass(look["lift"])
    lit = bool(captions.get("highlight", True))
    lo, hi = look["pop"]
    pop = f"{{\\fscx{lo}\\fscy{lo}\\t(0,80,\\fscx{hi}\\fscy{hi})\\t(80,150,\\fscx100\\fscy100)}}"
    groups = chunks(words, look)
    out: list[tuple] = []
    for gi, group in enumerate(groups):
        texts = [_escape(w["w"]) for w in group]
        texts = [t.upper() for t in texts] if look["upper"] else texts
        start = group[0]["start"]
        following = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        end = group[-1]["end"] + 0.15
        if following is not None and following - group[-1]["end"] < 0.35:
            end = following
        end = max(end, start + 0.2)

        def line(said: int | None, first: bool) -> str:
            parts = []
            for k, (t, w) in enumerate(zip(texts, group)):
                colour = active if k == said else lift if w.get("em") else ink
                grow = look["word"] if k == said and not first and look["word"] != 100 else 100
                if colour == ink and grow == 100:
                    parts.append(t)
                elif grow == 100:
                    parts.append(f"{{\\c{colour}}}{t}{{\\c{ink}}}")
                else:  # the word being said lands a little bigger and settles
                    parts.append(f"{{\\c{colour}\\fscx{grow + 8}\\fscy{grow + 8}\\t(0,90,\\fscx{grow}\\fscy{grow})}}{t}"
                                 f"{{\\c{ink}\\fscx100\\fscy100}}")
            return (pop if first else "") + " ".join(parts)

        if not lit:
            out.append((start, end, line(None, True)))
            continue
        for wi in range(len(group)):
            a = start if wi == 0 else group[wi]["start"]
            b = group[wi + 1]["start"] if wi + 1 < len(group) else end
            if b - a < 0.02:
                continue
            out.append((a, b, line(wi, wi == 0)))
    return out


def hook_events(plan: dict | None, total_s: float) -> list[tuple]:
    """The headline's event: it pops in at the start and fades away at its end."""
    hook = hook_of(plan)
    if hook is None or total_s <= 0.3:
        return []
    end = min(float(total_s), hook["ms"] / 1000)
    ms = int(round(end * 1000))
    text = _escape(hook["text"])
    tags = (f"{{\\fscx70\\fscy70\\t(0,110,\\fscx104\\fscy104)\\t(110,190,\\fscx100\\fscy100)"
            f"\\t({max(200, ms - 260)},{ms},\\alpha&HFF&)}}")
    return [(0.0, end, tags + text, "Hook")]


def shift(text: str, elapsed_ms: int) -> str:
    """The event's text for a piece that starts `elapsed_ms` into the event: its animations go on from there."""
    if elapsed_ms <= 0:
        return text
    return _T.sub(lambda m: f"\\t({int(m[1]) - elapsed_ms},{(int(m[2]) - elapsed_ms) or -1},", text)


def hook_style(plan: dict | None, width: int, height: int) -> str:
    """The ASS style line of the headline: dark words on a white label."""
    hook = hook_of(plan) or {"text": ""}
    scale = min(width, height) / 1080 * (0.72 if width > height else 1.0)
    n = len(hook["text"])
    px = max(12, int(next(size for limit, size in HOOK_SIZES if n <= limit) * scale))
    margin = int(HOOK_MARGIN * min(width, height) / 1080)
    return (f"Style: Hook,Poppins ExtraBold,{px},{hex_to_ass('#111111')},{hex_to_ass('#111111')},"
            f"{hex_to_ass('#FFFFFF')},&H50000000,-1,0,0,0,100,100,0,0,3,{max(4, int(16 * scale))},"
            f"{max(1, int(3 * scale))},8,{margin},{margin},{int(height * HOOK_TOP)},1")


def cap_style(captions: dict, width: int, height: int, sizes: dict, positions: dict) -> str:
    """The ASS style line of the captions in the plan's look, sized and placed for this frame."""
    look = get(captions) or LOOKS["pop"]
    scale = min(width, height) / 1080
    size = max(14, int(look["size"] * scale * (0.72 if width > height else 1.0)
                       * sizes.get(captions.get("size") or "medium", 1.0)))
    align, share = positions.get(captions.get("position") or "lower", positions["bottom"])
    margin = int(MARGIN * scale)
    return (f"Style: Cap,{look['font']},{size},{hex_to_ass(look['ink'])},{hex_to_ass(look['ink'])},"
            f"{hex_to_ass(look['edge'])},&H78000000,{look['bold']},0,0,0,100,100,{look['spacing']},0,1,"
            f"{max(2, int(round(look['outline'] * scale)))},{max(1, int(round(look['shadow'] * scale)))},{align},"
            f"{margin},{margin},{int(height * share)},1")
