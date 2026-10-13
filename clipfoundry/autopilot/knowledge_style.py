"""Compile a bounded vocabulary of editing guidance locally; text never becomes executable instructions."""
from __future__ import annotations

import math
import re


PRIORITIES = {
    "hook": r"\b(?:hooks?|grab attention|attention.grabbing)\b",
    "opening": r"\b(?:strong opening|slow opening|warm.up|immediate opening|get to the point)\b",
    "curiosity": r"\b(?:curiosity|open loop|surprising|surprise)\b",
    "emotion": r"\b(?:emotion\w*|humou?r|funny|tension|passion)\b",
    "density": r"\b(?:information density|useful information|filler|repetition|rambling)\b",
    "payoff": r"\b(?:payoffs?|punchlines?|complete stor(?:y|ies)|complete ideas?|satisfying conclusion)\b",
    "standalone": (r"\b(?:standalone|stand.alone|preserve.{0,20}context|essential context|full context|"
                   r"out.of.context)\b"),
    "pacing": r"\b(?:pacing|dead air|tight delivery)\b",
    "uniqueness": r"\b(?:uniqueness|original moments?|avoid duplicates?)\b",
    "clarity": r"\b(?:clarity|clear speech|speaker clarity|intelligible|preserve.{0,20}meaning)\b",
    "retention": r"\b(?:retention|watch to the end|watch through|completion)\b",
}


def compile_note(row: dict) -> dict:
    """Recognize supported settings and ranking priorities, without guessing from unrelated prose or video pixels."""
    text = "\n".join([str(row.get("title") or ""), str(row.get("content") or ""),
                      *(str(v) for v in (row.get("features") or {}).values())]).lower().replace("_", " ")
    preferences: dict = {}
    # Only caption-specific declarations count. A note about a clean fight or a bold claim changes no captions.
    styles = {"clean": r"clean", "bold": r"bold", "minimal": r"minimal|quiet|subtle",
              "high_energy": r"high[ -]energy"}
    for value, pattern in styles.items():
        explicit = rf"\bcaption style\s*[:=\-]\s*(?:{pattern})\b"
        natural = rf"\b(?:prefer|use|keep|choose|want)\s+(?:a |the )?(?:{pattern}).{{0,18}}\bcaptions?\b"
        adjacent = rf"\b(?:{pattern})\s+(?:readable\s+)?(?:captions?|subtitles?)\b"
        matches = list(re.finditer(rf"{explicit}|{natural}|{adjacent}", text))
        matches = [m for m in matches if not re.search(r"\b(?:no|not|avoid|never|without|don't)\s+$",
                                                     text[max(0, m.start() - 16):m.start()])]
        if matches:
            preferences["caption_style"] = value
    for value in ("bottom", "middle", "top"):
        if re.search(rf"\bcaption position\s*[:=\-]\s*{value}\b|"
                     rf"\b(?:captions?|subtitles?)\s+(?:at|in|near|on)\s+(?:the\s+)?{value}\b", text):
            preferences["caption_position"] = value
    if re.search(r"\b(?:caption emphasis\s*[:=\-]\s*(?:off|false)|"
                 r"(?:no|disable|avoid|without)\s+(?:caption\s+)?emphasis)\b", text):
        preferences["caption_emphasis"] = False
    elif re.search(r"\b(?:caption emphasis\s*[:=\-]\s*(?:on|true)|"
                   r"(?:use|enable|add)\s+(?:caption\s+)?emphasis)\b", text):
        preferences["caption_emphasis"] = True
    if re.search(r"\b(?:keep (?:the )?story continuous|continuous (?:story|pacing)|"
                 r"pacing\s*[:=\-]\s*continuous|avoid jump cuts|no jump cuts)\b", text):
        preferences["pacing"] = "continuous"
    elif re.search(r"\b(?:safe cuts|safe sentence cuts|remove weak middle sentences(?: when safe)?)\b", text):
        preferences["pacing"] = "safe_cuts"
    # Explicit controls win over interpretations of prose, even when their value is False.
    preferences.update(row.get("preferences") or {})
    priorities = [key for key, pattern in PRIORITIES.items() if re.search(pattern, text)]
    duration = None
    media = row.get("media") or {}
    value = media.get("duration_s")
    if row.get("kind") == "example" and row.get("example_label") == "good" and isinstance(value, (int, float)):
        if not isinstance(value, bool) and math.isfinite(value) and 5 <= value <= 180:
            duration = float(value)
    return {"preferences": preferences, "priorities": priorities, "example_duration": duration}
