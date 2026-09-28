"""Caption chunking and ASS/SRT generation (burned in by ffmpeg/libass)."""
from __future__ import annotations

import re

from ..config import OUTPUT_H, OUTPUT_W

STYLE_PRESETS = {
    "clean": {"font": "Poppins SemiBold", "size": 76, "upper": False, "max_words": 5, "max_chars": 26,
              "outline": 5, "shadow": 1, "highlight": "#FFD23F", "pop": False, "word_scale": 100,
              "emphasis": "#5CE1E6"},
    "bold": {"font": "Poppins ExtraBold", "size": 92, "upper": True, "max_words": 3, "max_chars": 18,
             "outline": 7, "shadow": 3, "highlight": "#FFE500", "pop": False, "word_scale": 100,
             "emphasis": "#FF5E5B"},
    "high_energy": {"font": "Anton", "size": 132, "upper": True, "max_words": 2, "max_chars": 14,
                    "outline": 8, "shadow": 4, "highlight": "#3CFF6B", "pop": True, "word_scale": 112,
                    "emphasis": "#FFE500"},
    "minimal": {"font": "Poppins Medium", "size": 62, "upper": False, "max_words": 7, "max_chars": 34,
                "outline": 0, "shadow": 2, "highlight": "#FFFFFF", "pop": False, "word_scale": 100,
                "emphasis": ""},
}

POSITIONS = {"bottom": (2, 0.23), "middle": (5, 0.0), "top": (8, 0.16)}


def hex_to_ass(color: str, alpha: int = 0) -> str:
    c = (color or "#FFFFFF").lstrip("#")
    if len(c) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFFFFF"
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


_FILLER = re.compile(r"^(um+|uh+|erm|hmm+|mm+)[,.]?$", re.I)


def chunk_words(words: list[dict], style: str) -> list[list[dict]]:
    """Split timed words (output timeline) into short caption groups."""
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["bold"])
    words = [w for w in words if not _FILLER.match(w["w"].strip())]
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    chars = 0
    for i, w in enumerate(words):
        text = w["w"].strip()
        if cur and (len(cur) >= p["max_words"] or chars + len(text) + 1 > p["max_chars"]
                    or w["start"] - cur[-1]["end"] > 0.6):
            chunks.append(cur)
            cur, chars = [], 0
        cur.append(w)
        chars += len(text) + 1
        if text.endswith((".", "?", "!", ",", ";", ":")) and len(cur) >= max(1, p["max_words"] // 2):
            chunks.append(cur)
            cur, chars = [], 0
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[dict], opts: dict, duration: float, hook_text: str = "") -> str:
    """`words` are already on the output timeline (seconds from clip start)."""
    style = opts.get("caption_style", "bold")
    p = dict(STYLE_PRESETS.get(style, STYLE_PRESETS["bold"]))
    scale = float(opts.get("caption_size", 1.0) or 1.0)
    size = int(p["size"] * max(0.5, min(1.8, scale)))
    align, margin_frac = POSITIONS.get(opts.get("caption_position", "bottom"), POSITIONS["bottom"])
    margin_v = int(OUTPUT_H * margin_frac)
    highlight = hex_to_ass(opts.get("highlight_color") or p["highlight"])
    primary = hex_to_ass(opts.get("caption_color") or "#FFFFFF")
    outline_col = "&H00000000"
    back = "&H64000000" if style != "minimal" else "&H96000000"
    bold_flag = -1 if style in {"bold", "high_energy"} else 0
    emph = hex_to_ass(p["emphasis"]) if opts.get("caption_emphasis") and p.get("emphasis") else ""
    hook_on = bool(opts.get("hook_overlay", True)) and hook_text.strip()
    hook_secs = float(opts.get("hook_seconds", 3.0) or 3.0)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {OUTPUT_W}",
        f"PlayResY: {OUTPUT_H}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{p['font']},{size},{primary},{highlight},{outline_col},{back},{bold_flag},0,0,0,100,100,"
        f"1,0,1,{p['outline']},{p['shadow']},{align},90,90,{margin_v},1",
        f"Style: Hook,Poppins ExtraBold,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H28161616,-1,0,0,0,100,100,0,0,3,"
        f"18,0,8,110,110,{int(OUTPUT_H * 0.11)},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if hook_on:
        text = _escape(hook_text.strip())
        end = min(duration, hook_secs)
        lines.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(end)},Hook,,0,0,0,,{{\\fad(120,250)}}{text}")

    if opts.get("captions_enabled", True):
        highlight_on = bool(opts.get("highlight_words", True)) and style != "minimal"
        chunks = chunk_words(words, style)
        for ci, chunk in enumerate(chunks):
            c_start = chunk[0]["start"]
            next_start = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else duration
            c_end = chunk[-1]["end"]
            # hold the caption through short gaps so it does not flicker
            c_end = next_start if next_start - c_end < 0.35 else c_end + 0.15
            c_end = min(max(c_end, c_start + 0.2), duration)
            texts = [_escape(w["w"].strip()) for w in chunk]
            if p["upper"]:
                texts = [t.upper() for t in texts]
            if emph:  # key words keep their own color (and a slight size bump) for the whole chunk
                texts = [f"{{\\c{emph}\\fscx108\\fscy108}}{t}{{\\r}}" if w.get("em") else t
                         for t, w in zip(texts, chunk)]
            pop = "{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}" if p["pop"] else ""
            if not highlight_on:
                lines.append(f"Dialogue: 1,{_ass_time(c_start)},{_ass_time(c_end)},Caption,,0,0,0,,{pop}"
                             + " ".join(texts))
                continue
            for wi, w in enumerate(chunk):
                w_start = c_start if wi == 0 else w["start"]
                w_end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else c_end
                if w_end - w_start < 0.02:
                    continue
                parts = []
                for k, t in enumerate(texts):
                    if k == wi:
                        grow = (f"\\fscx{p['word_scale']}\\fscy{p['word_scale']}" if p["word_scale"] != 100 else "")
                        parts.append(f"{{\\c{highlight}{grow}}}{t}{{\\r}}")
                    else:
                        parts.append(t)
                lead = pop if wi == 0 else ""
                lines.append(f"Dialogue: 1,{_ass_time(w_start)},{_ass_time(w_end)},Caption,,0,0,0,,{lead}"
                             + " ".join(parts))
    return "\n".join(lines) + "\n"


def build_srt(words: list[dict], style: str = "clean") -> str:
    out = []
    chunks = chunk_words(words, "minimal" if style == "minimal" else "clean")
    for i, chunk in enumerate(chunks, 1):
        text = " ".join(w["w"].strip() for w in chunk)
        out.append(f"{i}\n{_srt_time(chunk[0]['start'])} --> {_srt_time(chunk[-1]['end'] + 0.1)}\n{text}\n")
    return "\n".join(out)
