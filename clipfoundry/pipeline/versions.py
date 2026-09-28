"""Alternative versions of a clip, to compare before publishing.

* Original: the clip as edited.
* Faster pacing: tighter silence cleanup, filler words ("um", "uh") removed, played 8% faster (same pitch).
* Alternative hook: another on-screen hook from the clip's own words and, when the clip has a stronger line within
  its first sentences, an opening that starts there.
* Alternative caption style: a contrasting caption style with key words emphasized.

A version is the clip's own edit plus a few overrides, rendered next to the original; the framing analysis is shared.
"""
from __future__ import annotations

from . import candidates, render
from .text_utils import build_sentences

KINDS = {
    "faster": "Faster pacing",
    "alt_hook": "Alternative hook",
    "alt_captions": "Alternative caption style",
}
CONTRAST_STYLE = {"bold": "high_energy", "clean": "bold", "high_energy": "clean", "minimal": "bold"}
STYLE_LABEL = {"clean": "Clean", "bold": "Bold", "high_energy": "High Energy", "minimal": "Minimal"}
FASTER_SPEED = 1.08


def clip_range(clip: dict) -> tuple[float, float]:
    edit = clip.get("edit") or {}
    return float(edit.get("start", clip["start"])), float(edit.get("end", clip["end"]))


def alt_opening(clip: dict, words: list[dict]) -> float | None:
    """A later start on a clearly stronger first line (never a line that leans on what came before), keeping most
    of the clip."""
    start, end = clip_range(clip)
    ws = [w for w in words if w["end"] > start + 0.05 and w["start"] < end - 0.05]
    sents = build_sentences(ws)
    if len(sents) < 3:
        return None
    feats = candidates.sentence_features(sents, ws)
    best, best_score = None, max(0.5, feats[0]["opener"] + 0.1)
    for k in (1, 2):
        if k >= len(sents) - 1:
            break
        f = feats[k]
        if f["dangling"] or f["response"] or f["slow_open"]:
            continue
        if f["opener"] >= best_score and end - sents[k]["start"] >= max(10.0, 0.6 * (end - start)):
            best, best_score = k, f["opener"]
    if best is None:
        return None
    return round(max(start, sents[best]["start"] - min(0.25, 0.5 * feats[best]["gap_before"])), 3)


def build(kind: str, clip: dict, project: dict, settings: dict, words: list[dict]) -> tuple[dict, str]:
    """(edit overrides, plain description of what differs from the original)."""
    opts = render.effective_options(settings, project.get("options") or {}, clip.get("edit") or {})
    if kind == "faster":
        return ({"silence": "aggressive", "remove_fillers": True, "speed": FASTER_SPEED},
                f"Pauses over 0.35 s and filler words cut, played {round((FASTER_SPEED - 1) * 100)}% faster "
                "(same voice pitch).")
    if kind == "alt_hook":
        current = (opts.get("hook") if opts.get("hook") is not None else clip.get("hook", "")) or ""
        pool = [*(clip.get("hooks_alt") or []), *((clip.get("post") or {}).get("hooks") or [])]
        alts = [h for h in pool if h and h.strip().lower() != current.strip().lower()]
        hook = alts[0] if alts else current
        edit: dict = {"hook": hook, "hook_overlay": True}
        parts = [f"On-screen hook “{hook}”"]
        new_start = alt_opening(clip, words)
        if new_start is not None:
            edit["start"] = new_start
            parts.append(f"starts {new_start - clip_range(clip)[0]:.1f} s later, on a stronger first line")
        return edit, "; ".join(parts)
    if kind == "alt_captions":
        style = CONTRAST_STYLE.get(opts.get("caption_style") or "bold", "bold")
        return ({"caption_style": style, "caption_emphasis": True},
                f"{STYLE_LABEL[style]} captions with key words in their own color.")
    raise ValueError(f"unknown version kind {kind}")
