"""The render artifact record: what a rendered MP4 is, how it was made and what is heard in it.

Every render writes two files next to its MP4:

* `edl.json`               the edit decisions: which source ranges were kept, in output order, at which speed, and
                           where each one lands in the output. This is the time map used for the captions, the
                           emphasis and the final transcript.
* `transcript.final.json`  the words actually heard in the output, with their output times and their original source
                           times. Words inside removed ranges (long pauses, fillers) are not in it.

and returns a record (stored as `render_info["artifact"]`) with the MP4's SHA-256 and size, a probe of its streams,
the effective render settings, the caption files and the blueprint it was rendered from. Packaging and the final
quality gate read these instead of re-deriving them from the source transcript, so what they describe and check is
exactly what was rendered.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Protocol

from . import ffmpeg_utils
from .common import read_json, write_json
from .text_utils import build_sentences

ARTIFACT_VERSION = 1
EDL_FILE = "edl.json"
TRANSCRIPT_FILE = "transcript.final.json"
# Render options that change what the output looks or sounds like (recorded with every artifact)
SETTINGS_KEYS = ("caption_style", "caption_position", "highlight_words", "caption_emphasis", "tracking", "layout",
                 "crop_x", "zoom", "auto_zoom", "silence", "remove_fillers", "speed", "normalize_audio", "gain_db",
                 "hook", "hook_overlay", "hook_seconds")


class TimeMap(Protocol):
    """What `render.Timeline` provides: kept source segments, their offsets and the playback speed."""

    segs: list[tuple[float, float]]
    offsets: list[float]
    speed: float
    duration: float

    def to_out(self, t: float) -> float: ...


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def edit_decisions(tl: TimeMap) -> list[dict]:
    """The time map: each kept source range and the output range it plays in."""
    return [{"src_start": round(a, 3), "src_end": round(b, 3), "out_start": round(off / tl.speed, 3),
             "out_end": round((off + b - a) / tl.speed, 3), "speed": round(tl.speed, 4)}
            for (a, b), off in zip(tl.segs, tl.offsets)]


def _kept_fraction(a: float, b: float, segs: list[tuple[float, float]]) -> float:
    if b - a <= 1e-6:
        return 1.0 if any(sa - 1e-6 <= a < sb for sa, sb in segs) else 0.0
    return sum(max(0.0, min(b, sb) - max(a, sa)) for sa, sb in segs) / (b - a)


def final_words(words: list[dict], tl: TimeMap, start: float, end: float) -> tuple[list[dict], int]:
    """(words heard in the output with output and source times, number of words cut out). A word counts as heard
    when at least half of it is inside a kept range."""
    out, removed = [], 0
    for w in words:
        if w["end"] <= start or w["start"] >= end:
            continue
        a, b = max(start, float(w["start"])), min(end, float(w["end"]))
        if _kept_fraction(a, b, tl.segs) < 0.5:
            removed += 1
            continue
        out.append({"w": w["w"], "start": round(tl.to_out(a), 3), "end": round(min(tl.to_out(b), tl.duration), 3),
                    "src_start": round(a, 3), "src_end": round(b, 3)})
    return out, removed


def record(out_path: Path, out_dir: Path, tl: TimeMap, words: list[dict], start: float, end: float, opts: dict,
           encoder: str, blueprint: dict | None = None) -> dict:
    """Write the EDL and the final transcript next to the MP4 and return the artifact record."""
    edl = edit_decisions(tl)
    heard, removed = final_words(words, tl, start, end)
    write_json(out_dir / EDL_FILE, {"version": ARTIFACT_VERSION, "source_range": [round(start, 3), round(end, 3)],
                                    "speed": tl.speed, "duration": round(tl.duration, 3), "segments": edl})
    write_json(out_dir / TRANSCRIPT_FILE, {"version": ARTIFACT_VERSION, "duration": round(tl.duration, 3),
                                           "words": heard, "removed_words": removed,
                                           "text": " ".join(w["w"].strip() for w in heard)})
    try:
        streams = ffmpeg_utils.probe(out_path)
    except ffmpeg_utils.FFmpegError as exc:
        streams = {"error": str(exc)[:300]}
    return {
        "version": ARTIFACT_VERSION, "path": str(out_path), "sha256": sha256_file(out_path),
        "size": out_path.stat().st_size, "duration": round(tl.duration, 3), "encoder": encoder, "probe": streams,
        "edl": str(out_dir / EDL_FILE), "segments": len(edl), "transcript": str(out_dir / TRANSCRIPT_FILE),
        "transcript_sha256": sha256_json(heard), "words": len(heard), "removed_words": removed,
        "captions": {"ass": str(out_dir / "captions.ass"), "srt": str(out_dir / "captions.srt")},
        "settings": {k: opts.get(k) for k in SETTINGS_KEYS if opts.get(k) is not None},
        "blueprint": blueprint, "created_at": round(time.time(), 3),
    }


# ------------------------------------------------------------------ reading
def of(render_info: dict | None) -> dict | None:
    """The artifact record of a clip's or version's render (None for renders made before records existed)."""
    art = (render_info or {}).get("artifact")
    return art if isinstance(art, dict) and art.get("sha256") else None


def active(clip: dict) -> tuple[str, str, dict]:
    """(video path, version id, render_info) of what would be published for this clip: the chosen alternative
    version when it is rendered, otherwise the clip's own render."""
    from .. import db

    if clip.get("active_version"):
        v = db.get_version(clip["active_version"])
        if v and v["status"] == "ready" and Path(v.get("output_path") or "").exists():
            return v["output_path"], v["id"], v.get("render_info") or {}
    return clip.get("output_path") or "", "", clip.get("render_info") or {}


def final_transcript(render_info: dict | None) -> dict | None:
    art = of(render_info)
    if not art:
        return None
    data = read_json(Path(art["transcript"]), None)
    return data if isinstance(data, dict) and isinstance(data.get("words"), list) else None


def final_sentences(render_info: dict | None) -> list[str] | None:
    """The sentences heard in the rendered clip (None when the render has no final transcript)."""
    data = final_transcript(render_info)
    if data is None:
        return None
    words = [{"w": w["w"], "start": w["src_start"], "end": w["src_end"]} for w in data["words"]]
    return [s["text"] for s in build_sentences(words)]
