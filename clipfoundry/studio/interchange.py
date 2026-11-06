"""Hand a cut to another editor: an OpenTimelineIO timeline with SRT captions (docs/clipforge/FILMCRAFT.md).

The timeline is made from the same frame map the FFmpeg engine renders from (engine.frame_map), so every clip starts
and ends on the frame it has in ClipForge's own render:

* V1 holds the sequence: the opening title (as a still picture), every included clip and image, and the joins between
  them. A ClipForge join overlaps two neighbours by the transition length; in the timeline that becomes a cut at the
  middle of the overlap with an OTIO transition reaching half the overlap to each side, so the program length and
  every frame of picture are the same.
* V2 holds the pictures shown over the video (B-roll), where the editor placed them.
* A1 holds the sound of the clips (same cuts as V1, joined with constant-power crossfades); then one track per
  ClipForge track (voiceover, music, sound effects), with more lanes when items on one track play at the same time.
  A looping music bed is laid as repeated copies of its file.
* Chapters become markers; captions are an SRT file on the same output timeline (FilmCraft imports it as a caption
  track).

OTIO has no fields for clip volume or the sequence's frame size. They are written in `metadata.filmcraft`, which
FilmCraft reads (its OTIO round-trip metadata) and other editors ignore. ClipForge's own ids and settings are kept in
`metadata.clipforge`. What a timeline cannot carry (ducking, fades, punch-ins, fill framing, caption looks, the final
loudness leveling) is listed in `not_carried()` and written in the README next to the timeline.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..pipeline.ffmpeg_utils import FFmpegError, ffmpeg_bin, filter_path
from . import engine

FORMAT = "clipforge.otio/v1"
SR = 48000
TITLE_BG = "0B0D14"  # the title card's background in the FFmpeg engine
VIDEO_TRANSITIONS = {"dissolve": ("Cross Dissolve", "SMPTE_Dissolve"), "fade": ("Dip to Black", "Custom_Transition")}
AUDIO_TRANSITION = ("Cross Fade (+3dB)", "SMPTE_Dissolve")
TRACK_NAMES = {"source": "Sound from your videos", "voiceover": "Voiceover", "music": "Music",
               "effects": "Sound effects"}
_UNSAFE = re.compile(r"[^\w\- .()&,'+]+", re.UNICODE)


class HandoffError(ValueError):
    """The timeline could not be made (the reason is written for the person)."""


# ------------------------------------------------------------------ OTIO building blocks
def _num(v: float) -> float:
    v = round(float(v), 6)
    return float(int(v)) if v == int(v) else v


def _rt(frames: float, fps: int) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(fps), "value": _num(frames)}


def _tr(start: float, duration: float, fps: int) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, fps), "duration": _rt(duration, fps)}


def _gap(frames: int, fps: int) -> dict:
    return {"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": _tr(0, frames, fps), "effects": [], "markers": [],
            "enabled": True, "metadata": {}}


def _transition(name: str, kind: str, a: int, b: int, fps: int) -> dict:
    return {"OTIO_SCHEMA": "Transition.1", "name": name, "transition_type": kind, "in_offset": _rt(a, fps),
            "out_offset": _rt(b, fps), "metadata": {}}


def _external(url: str, name: str, available_frames: float | None, fps: int) -> dict:
    return {"OTIO_SCHEMA": "ExternalReference.1", "name": name, "target_url": url,
            "available_range": _tr(0, available_frames, fps) if available_frames else None,
            "available_image_bounds": None, "metadata": {}}


def _clip(name: str, ref: dict, start: float, frames: int, fps: int, filmcraft: dict, clipforge: dict) -> dict:
    return {"OTIO_SCHEMA": "Clip.2", "name": name, "source_range": _tr(start, frames, fps),
            "media_references": {"DEFAULT_MEDIA": ref}, "active_media_reference_key": "DEFAULT_MEDIA",
            "effects": [], "markers": [], "enabled": True,
            "metadata": {"filmcraft": filmcraft, "clipforge": clipforge}}


def _track(name: str, kind: str, children: list[dict], filmcraft: dict | None = None) -> dict:
    return {"OTIO_SCHEMA": "Track.1", "name": name, "kind": kind, "source_range": None, "children": children,
            "effects": [], "markers": [], "enabled": True, "metadata": {"filmcraft": filmcraft or {}}}


def _marker(name: str, frame: int, fps: int, comment: str = "") -> dict:
    return {"OTIO_SCHEMA": "Marker.2", "name": name, "marked_range": _tr(frame, 0, fps), "color": "GREEN",
            "comment": comment, "metadata": {}}


def sequence_settings(width: int, height: int, fps: int) -> dict:
    """FilmCraft's SequenceSettings (every field it requires), so the sequence opens at the video's own frame size
    and rate instead of FilmCraft's 1920x1080 default."""
    return {"width": width, "height": height, "frame_rate": {"num": fps, "den": 1}, "par": [1, 1],
            "sample_rate": SR, "drop_frame": False, "preset": f"ClipForge {width}x{height} {fps} fps",
            "audio_master": "Stereo", "preview_codec": "ProRes 422", "max_bit_depth": False,
            "max_render_quality": False, "working_space": "Rec. 709"}


def _frames(ms: float, fps: int) -> int:
    return round(ms * fps / 1000)


def _length_frames(asset: dict, fps: int) -> float | None:
    seconds = float((asset.get("probe") or {}).get("duration") or 0)
    return seconds * fps if seconds > 0 else None


# ------------------------------------------------------------------ the timeline
@dataclass
class Timeline:
    otio: dict
    srt: str
    fps: int
    width: int
    height: int
    frames: int
    media: dict[str, dict] = field(default_factory=dict)  # asset id -> asset, every file the timeline points at
    counts: dict = field(default_factory=dict)
    title_still: bool = False


def build(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], *, name: str,
          url_for: Callable[[dict], str], title_url: str | None = None, info: dict | None = None) -> Timeline:
    """The OTIO timeline and SRT captions of one plan. `url_for(asset)` gives the address written for a file (an
    absolute file URL, or a path relative to the timeline for a portable package); `title_url` is a still of the
    opening title card (without it the title is a black matte with a marker naming the text)."""
    plan = engine.upgrade(plan)
    problems = engine.validate(plan, assets)
    if problems:
        raise HandoffError("; ".join(problems))
    fps = int((plan.get("output") or {}).get("fps") or 30)
    width, height = engine.ASPECTS[plan["output"]["aspect"]]
    els, _overlap = engine.frame_map(plan, fps)
    total_f = els[-1]["end_f"]
    clips = {c["id"]: c for c in plan.get("clips") or []}
    tracks = {**engine.default_tracks(), **(plan.get("tracks") or {})}
    used: dict[str, dict] = {}

    def ref(asset: dict) -> dict:
        used[asset["id"]] = asset
        return _external(url_for(asset), asset["filename"], _length_frames(asset, fps) if asset["kind"] != "image"
                         else None, fps)

    # cut k sits between els[k-1] and els[k]: (frame of the cut, transition frames before it, after it)
    cuts = []
    for k in range(1, len(els)):
        ov = els[k]["ov_in"]
        a = ov // 2
        cuts.append((els[k]["start_f"] + a, a, ov - a))
    left = [0] + [c for c, _, _ in cuts]
    right = [c for c, _, _ in cuts] + [total_f]
    ttype = (plan.get("transition") or {}).get("type", "cut")

    # ---- V1: the sequence, A1: the sound of its clips
    v1: list[dict] = []
    a1_slots: list[dict] = []   # per element: its sound clip, or a gap
    sound_slots: list[bool] = []
    for k, e in enumerate(els):
        frames = right[k] - left[k]
        into = left[k] - e["start_f"]  # frames of this element before its left cut (inside the transition)
        link = k + 1
        if k and sum(cuts[k - 1][1:]):
            tname, tkind = VIDEO_TRANSITIONS.get(ttype, VIDEO_TRANSITIONS["dissolve"])
            v1.append(_transition(tname, tkind, cuts[k - 1][1], cuts[k - 1][2], fps))
        if e["kind"] == "title":
            text = plan["title"]["text"]
            if title_url:
                still = {"OTIO_SCHEMA": "ExternalReference.1", "name": "Title card", "target_url": title_url,
                         "available_range": None, "available_image_bounds": None, "metadata": {}}
            else:
                still = {"OTIO_SCHEMA": "GeneratorReference.1", "name": "Title card", "generator_kind": "SolidColor",
                         "parameters": {"color": [11 / 255, 13 / 255, 20 / 255, 1.0]}, "available_range": None,
                         "metadata": {}}
            item = _clip(f"Title: {text[:60]}", still, into, frames, fps, {"scale_to_frame": True},
                         {"kind": "title", "text": text})
            if not title_url:
                item["markers"].append(_marker(f"Title: {text[:80]}", into, fps, "Opening title card"))
            v1.append(item)
            a1_slots.append(_gap(frames, fps))
            sound_slots.append(False)
            continue
        c = clips[e["clip_id"]]
        asset = assets[e["asset_id"]]
        label = c.get("label") or asset["filename"]
        start = e["src_in_ms"] * fps / 1000 + into if e["kind"] == "video" else into
        meta_cf = {"clip_id": c["id"], "asset_id": asset["id"], "kind": e["kind"],
                   "layout": c.get("layout") or plan.get("layout") or "fit", "zoom": float(c.get("zoom") or 1.0)}
        v1.append(_clip(label, ref(asset), start, frames, fps, {"scale_to_frame": True, "link": link}, meta_cf))
        audible = (e["kind"] == "video" and (asset.get("probe") or {}).get("has_audio") and not c.get("mute"))
        if audible:
            a1_slots.append(_clip(label, ref(asset), start, frames, fps,
                                  {"gain_db": float(c.get("gain_db") or 0.0), "link": link},
                                  {"clip_id": c["id"], "asset_id": asset["id"],
                                   "fade_in_ms": int(c.get("fade_in_ms") or 0),
                                   "fade_out_ms": int(c.get("fade_out_ms") or 0)}))
        else:
            a1_slots.append(_gap(frames, fps))
        sound_slots.append(bool(audible))
    # the same cuts on A1, with a constant-power crossfade wherever at least one side has sound
    a1: list[dict] = []
    for k, item in enumerate(a1_slots):
        if k and sum(cuts[k - 1][1:]) and (sound_slots[k - 1] or sound_slots[k]):
            a1.append(_transition(*AUDIO_TRANSITION, cuts[k - 1][1], cuts[k - 1][2], fps))
        a1.append(item)
    source_gain = float(tracks["source"].get("gain_db") or 0.0)

    # ---- V2: pictures over the video, where the render shows them
    by_overlay = {o["id"]: o for o in plan.get("overlays") or []}
    flat = sorted((o for items in engine._overlay_frames(plan, els, fps, assets).values() for o in items),
                  key=lambda o: o["start_f"])
    v2: list[dict] = []
    pos = 0
    for o in flat:
        src = by_overlay[o["id"]]
        asset = assets[src["asset_id"]]
        if o["start_f"] > pos:
            v2.append(_gap(o["start_f"] - pos, fps))
        start = o["src_in_ms"] * fps / 1000 if asset["kind"] == "video" else 0
        v2.append(_clip(src.get("label") or asset["filename"], ref(asset), start, o["end_f"] - o["start_f"], fps,
                        {"scale_to_frame": True},
                        {"overlay_id": o["id"], "asset_id": asset["id"], "fit": o["fit"], "motion": o["motion"]}))
        pos = o["end_f"]

    # ---- voiceover, music and sound effects, each on its own track (more lanes where items overlap)
    segs = engine.render_timeline(plan, fps)
    total_ms = round(total_f * 1000 / fps)
    items = {i["id"]: i for i in plan.get("audio") or []}
    lanes: dict[str, list[list[tuple[int, int, dict]]]] = {}
    for place in engine.audio_timeline(plan, segs, total_ms):
        s, t = min(total_f, _frames(place["out_start_ms"], fps)), min(total_f, _frames(place["out_end_ms"], fps))
        if t <= s:
            continue
        rows = lanes.setdefault(place["track"], [])
        row = next((r for r in rows if r[-1][1] <= s), None)
        if row is None:
            rows.append(row := [])
        row.append((s, t, place))
    audio_tracks: list[dict] = []
    for track_name in ("voiceover", "music", "effects"):
        state = tracks.get(track_name) or {}
        rows = lanes.get(track_name) or []
        for n, row in enumerate(rows):
            children: list[dict] = []
            pos = 0
            for s, t, place in row:
                item = items[place["audio_id"]]
                asset = assets[item["asset_id"]]
                if s > pos:
                    children.append(_gap(s - pos, fps))
                meta_fc = {"gain_db": float(item.get("gain_db") or 0.0)}
                meta_cf = {"audio_id": item["id"], "asset_id": asset["id"], "role": item["role"],
                           "duck": bool(item.get("duck")), "fade_in_ms": int(item.get("fade_in_ms") or 0),
                           "fade_out_ms": int(item.get("fade_out_ms") or 0), "loop": bool(item.get("loop"))}
                label = item.get("label") or asset["filename"]
                if place["loop"]:
                    length = _length_frames(asset, fps)
                    piece = max(1, math.floor(length)) if length else t - s
                    at = s
                    while at < t:
                        d = min(piece, t - at)
                        children.append(_clip(label, ref(asset), 0, d, fps, meta_fc, meta_cf))
                        at += d
                else:
                    children.append(_clip(label, ref(asset), place["src_in_ms"] * fps / 1000, t - s, fps, meta_fc,
                                          meta_cf))
                pos = t
            title = TRACK_NAMES[track_name] + (f" {n + 1}" if len(rows) > 1 else "")
            audio_tracks.append(_track(title, "Audio", children, {"volume_db": float(state.get("gain_db") or 0.0),
                                                                  "muted": bool(state.get("mute"))}))

    # ---- markers (every chapter, also ones YouTube would not show), captions, the whole document
    markers = [_marker(ch["title"], min(total_f - 1, _frames(ch["ms"], fps)), fps, "Chapter")
               for ch in chapter_marks(plan)]
    stack_tracks = [_track("Video 1", "Video", v1)]
    if v2:
        stack_tracks.append(_track("Pictures over the video", "Video", v2))
    if any(sound_slots):
        stack_tracks.append(_track(TRACK_NAMES["source"], "Audio", a1, {"volume_db": source_gain,
                                                                        "muted": bool(tracks["source"].get("mute"))}))
    stack_tracks += audio_tracks
    otio = {"OTIO_SCHEMA": "Timeline.1", "name": name,
            "global_start_time": _rt(0, fps),
            "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": stack_tracks, "effects": [],
                       "markers": markers, "enabled": True, "source_range": None, "metadata": {}},
            "metadata": {"filmcraft": {"settings": sequence_settings(width, height, fps)},
                         "clipforge": {"format": FORMAT, "fps": fps, "width": width, "height": height,
                                       "frames": total_f, **(info or {})}}}
    words = engine.output_words(plan, words_by_asset, segs)
    captions = plan.get("captions") or {}
    events = engine.caption_events(words, captions) if captions.get("enabled") and words else []
    counts = {"clips": sum(1 for e in els if e["kind"] != "title"), "title": any(e["kind"] == "title" for e in els),
              "transitions": sum(1 for _, a, b in cuts if a + b), "overlays": len(flat),
              "audio_items": sum(len(r) for rows in lanes.values() for r in rows),
              "audio_tracks": len(audio_tracks) + (1 if any(sound_slots) else 0), "captions": len(events),
              "chapters": len(markers)}
    return Timeline(otio=otio, srt=srt(events, total_f / fps), fps=fps, width=width, height=height, frames=total_f,
                    media=used, counts=counts, title_still=bool(title_url))


def chapter_marks(plan: dict) -> list[dict]:
    """Every chapter of the plan at its place in the output (ms), in order; unlike the YouTube description
    (smart_edit.chapter_times) none is dropped for being short or too close to another."""
    segs = {s["clip_id"]: s for s in engine.timeline(plan)}
    return sorted(({"title": str(c.get("title") or "Chapter")[:100],
                    "ms": min(segs[c["clip_id"]]["out_end_ms"] - 1,
                              segs[c["clip_id"]]["out_start_ms"] + int(c.get("offset_ms") or 0))}
                   for c in plan.get("chapters") or [] if c.get("clip_id") in segs), key=lambda r: r["ms"])


def _srt_time(t: float) -> str:
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(events: list[tuple[float, float, str]], total_s: float) -> str:
    """SubRip captions; a caption ends before the next one starts and never after the video."""
    out = []
    for n, (a, b, text) in enumerate(events):
        nxt = events[n + 1][0] if n + 1 < len(events) else total_s
        b = min(b, nxt, total_s)
        if b - a < 0.04:
            continue
        out.append(f"{len(out) + 1}\n{_srt_time(a)} --> {_srt_time(b)}\n{text.strip()}\n")
    return "\n".join(out)


def not_carried(plan: dict, title_still: bool) -> list[str]:
    """What the timeline cannot carry, for this plan only, in the person's words."""
    plan = engine.upgrade(plan)
    inc = [c for c in plan.get("clips") or [] if c.get("include", True)]
    audio = plan.get("audio") or []
    out = []
    if any(i.get("duck") for i in audio if i.get("role") != "voiceover"):
        out.append("Music and effects dipping under speech (ducking): lower them by hand or with keyframes.")
    if any(int(x.get("fade_in_ms") or 0) or int(x.get("fade_out_ms") or 0) for x in inc + audio):
        out.append("Sound fades on clips and audio items: add them as audio transitions or volume keyframes.")
    if any(float(c.get("zoom") or 1.0) > 1.001 for c in inc):
        out.append("Punch-in zooms on jump cuts: set Scale on those clips in Effect Controls.")
    layouts = {c.get("layout") or plan.get("layout") or "fit" for c in inc if c.get("kind", "video") == "video"}
    if "fill" in layouts:
        out.append("“Fill the frame” framing: clips are scaled to fit the frame; raise Scale to crop them.")
    if "fit" in layouts:
        out.append("The blurred background behind clips that do not fill the frame (FilmCraft shows black there).")
    if plan.get("overlays"):
        out.append("The slow push-in and the fades of pictures over the video.")
    if (plan.get("captions") or {}).get("enabled"):
        out.append("The caption look (style, size and position): captions come in with FilmCraft's caption style.")
    if engine._has_title(plan):
        what = ("The opening title is a picture of the text" if title_still else
                "The opening title is a dark colour matte with a marker naming its text")
        out.append(f"{what}: change it in ClipForge, or replace it with a FilmCraft title.")
    out.append("ClipForge's final loudness leveling: FilmCraft plays the tracks at the levels set here.")
    return out


# ------------------------------------------------------------------ files
def safe_name(name: str, fallback: str = "ClipForge video") -> str:
    s = _UNSAFE.sub(" ", name or "").strip(" .")
    s = re.sub(r"\s+", " ", s)[:60].strip(" .")
    return s or fallback


def title_still(text: str, width: int, height: int, out: Path) -> bool:
    """A still of the title card exactly as the FFmpeg engine draws it (same font, size and colours)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent
    (work / "title.txt").write_text(text[:120], encoding="utf-8")
    font = filter_path(engine._font(), work)
    try:
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
               f"color=c=0x{TITLE_BG}:s={width}x{height}:d=1", "-vf",
               f"drawtext=fontfile={font}:textfile=title.txt:fontcolor=white:fontsize={int(height * 0.07)}:"
               f"x=(w-text_w)/2:y=(h-text_h)/2", "-frames:v", "1", out.name]
        done = subprocess.run(cmd, cwd=work, capture_output=True, timeout=60)  # noqa: S603 - our own ffmpeg
        ok = done.returncode == 0 and out.is_file() and out.stat().st_size > 0
    except (FFmpegError, OSError, subprocess.SubprocessError):
        ok = False
    finally:
        (work / "title.txt").unlink(missing_ok=True)
    if not ok:
        out.unlink(missing_ok=True)
    return ok


def _n(count: int, what: str) -> str:
    return f"{count} {what}" if count == 1 else f"{count} {what}s"


def readme(name: str, revision: int, tl: Timeline, files: dict[str, str], missing: list[str]) -> str:
    c = tl.counts
    lines = [f"{name}, version {revision}: timeline from ClipForge", "",
             f"{tl.width}x{tl.height}, {tl.fps} frames per second, {tl.frames / tl.fps:.2f} seconds "
             f"({tl.frames} frames).", "", "Files", f"  {files['timeline']}  the edit (OpenTimelineIO)"]
    if files.get("captions"):
        lines.append(f"  {files['captions']}  captions ({c['captions']}), on the same timeline")
    if files.get("title"):
        lines.append(f"  {files['title']}  the opening title card")
    if files.get("media"):
        lines.append(f"  {files['media']}/  the video, picture and sound files the timeline uses")
    lines += ["", "Open it in FilmCraft",
              "  File > Import..., choose the .otio file, then import the .srt file the same way (it becomes a",
              "  caption track on the sequence). Other editors that read OpenTimelineIO can import the .otio too.",
              "", "What came across",
              f"  {_n(c['clips'], 'clip')} with their exact trims and order, {_n(c['transitions'], 'join')} "
              f"(dissolves or dips to black), {_n(c['overlays'], 'picture')} over the video, the sound of each clip, "
              f"{_n(c['audio_items'], 'voiceover, music or sound-effect item')} on their own tracks, clip and track "
              f"volume, mutes, {_n(c['chapters'], 'chapter marker')} and the frame size and rate.", "",
              "Not carried over (redo these by hand if you want them)"]
    lines += [f"  - {x}" for x in not_carried_text(tl)]
    if missing:
        lines += ["", "Files not found when this was made (they show as offline):"] + [f"  - {m}" for m in missing]
    return "\n".join(lines) + "\n"


def not_carried_text(tl: Timeline) -> list[str]:
    return tl.otio["metadata"]["clipforge"].get("not_carried") or []


@dataclass
class Package:
    folder: Path
    timeline: Path
    captions: Path | None
    title: Path | None
    readme: Path
    built: Timeline
    media: dict[str, Path]  # name inside the package (portable) or original path -> file


def _media_names(assets: list[dict]) -> dict[str, str]:
    """A unique, readable file name per asset inside a portable package."""
    out, taken = {}, set()
    for n, a in enumerate(assets, 1):
        stem, ext = Path(a["filename"]).stem, Path(a["filename"]).suffix or Path(a["path"]).suffix
        base = safe_name(stem, f"file {n}")
        cand = f"{base}{ext.lower()}"
        k = 2
        while cand.lower() in taken:
            cand = f"{base} ({k}){ext.lower()}"
            k += 1
        taken.add(cand.lower())
        out[a["id"]] = cand
    return out


def write(folder: Path, plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], *, name: str,
          revision: int, portable: bool, info: dict | None = None) -> Package:
    """Write the timeline, captions, title still and README into `folder`. Portable packages point at
    `media/<file>` next to the timeline (the caller copies the files there); otherwise at the original files."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{safe_name(name)} v{revision}"
    plan = engine.upgrade(plan)
    width, height = engine.ASPECTS[plan["output"]["aspect"]]
    title_png = folder / "Title card.png"
    has_title = engine._has_title(plan) and title_still(plan["title"]["text"], width, height, title_png)
    names = _media_names(list(assets.values())) if portable else {}

    def url_for(asset: dict) -> str:
        if portable:
            return "media/" + names[asset["id"]].replace("%", "%25").replace(" ", "%20")
        return Path(asset["path"]).resolve().as_uri()

    title_url = (("Title%20card.png" if portable else title_png.resolve().as_uri()) if has_title else None)
    tl = build(plan, assets, words_by_asset, name=stem, url_for=url_for, title_url=title_url,
               info={"revision": revision, **(info or {})})
    tl.otio["metadata"]["clipforge"]["not_carried"] = not_carried(plan, has_title)
    timeline = folder / f"{stem}.otio"
    timeline.write_text(json.dumps(tl.otio, indent=2, ensure_ascii=False), encoding="utf-8")
    captions = None
    if tl.srt.strip():
        captions = folder / f"{stem}.srt"
        captions.write_text(tl.srt, encoding="utf-8")
    media = {names[aid] if portable else a["path"]: Path(a["path"]) for aid, a in tl.media.items()}
    missing = [a["filename"] for a in tl.media.values() if not Path(a["path"]).is_file()]
    files = {"timeline": timeline.name, "captions": captions.name if captions else "",
             "title": title_png.name if has_title else "", "media": "media" if portable else ""}
    note = folder / "README.txt"
    note.write_text(readme(name, revision, tl, files, missing), encoding="utf-8")
    return Package(folder=folder, timeline=timeline, captions=captions, title=title_png if has_title else None,
                   readme=note, built=tl, media=media)


def zip_package(pkg: Package, out: Path) -> Path:
    """One .zip with the timeline, captions, README and (stored, not recompressed) every media file under media/."""
    need = sum(p.stat().st_size for p in pkg.media.values() if p.is_file()) + (16 << 20)
    free = shutil.disk_usage(out.parent).free
    if free < need:
        raise HandoffError(f"Not enough free disk space to pack the timeline with its media: {need / 1e9:.1f} GB "
                           f"needed, {free / 1e9:.1f} GB free.")
    part = out.with_suffix(".part")
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        for p in (pkg.timeline, pkg.captions, pkg.title, pkg.readme):
            if p:
                z.write(p, p.name, compress_type=zipfile.ZIP_STORED if p.suffix == ".png" else zipfile.ZIP_DEFLATED)
        for name, p in pkg.media.items():
            if p.is_file():
                z.write(p, f"media/{name}", compress_type=zipfile.ZIP_STORED)
    part.replace(out)
    return out


# ------------------------------------------------------------------ one version of a ClipForge video
def for_video(project: dict, revision: int, folder: Path, *, portable: bool) -> Package:
    """Write the handoff package of one saved version of a video project into `folder`."""
    from .. import db
    from . import video_flow

    plan = video_flow.plan_at(project["id"], revision)
    assets = video_flow._assets(project, plan)
    settings = db.get_settings()
    used = {c["asset_id"] for c in plan.get("clips") or [] if c.get("include", True)}
    words = {aid: video_flow.transcript_words(a, settings, cached_only=True) for aid, a in assets.items()
             if a["kind"] == "video" and aid in used}
    return write(folder, plan, assets, words, name=project["name"], revision=revision, portable=portable,
                 info={"video_id": project["id"], "plan_sha256": video_flow.plan_hash(plan)})


def local_folder(project: dict, revision: int) -> Path:
    """Where "Open in FilmCraft" keeps a version's timeline (next to the video's renders)."""
    from . import video_flow

    return video_flow.video_dir(project["id"]) / "filmcraft" / f"v{revision}"
