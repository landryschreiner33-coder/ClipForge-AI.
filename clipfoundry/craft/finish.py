"""The edit in FilmCraft, and FilmCraft's render of the final video.

1. The cut becomes a FilmCraft project: the OpenTimelineIO timeline and SRT captions ClipForge already makes
   (studio/interchange.py, frame-exact against the FFmpeg engine's frame map), imported by `filmcraft-cli`.
2. ClipForge's own editing decisions that a timeline cannot hold are made with FilmCraft's tools, on the clips they
   belong to: punch-in zooms and "fill the frame" framing (Motion scale), the blurred copies behind fitted pictures
   (Gaussian Blur), the push-in and fades of pictures over the video (Scale and Opacity keyframes), sound fades
   (Volume keyframes), music dipping under speech (Essential Sound: dialogue and music types, Generate Ducking), the
   caption look (caption track style, burned in on export) and the loudness (export normalised to -14 LUFS).
3. The opening title becomes an animated effects shot made in EffectCraft (shots.py), placed in the edit.
4. With an AI service set up, the AI adds its own finishing with FilmCraft's tools and EffectCraft shots (ai.py).
5. FilmCraft renders the project. The file is checked like the FFmpeg engine's own renders (length, picture size,
   sound, the AAC timing check); anything wrong raises, and the caller renders with FFmpeg instead.

Everything is written in `<render folder>/filmcraft/`: the project (`edit.fcproj`), the steps that were run and what
each one answered (`report.json`), so the person can open the same edit in FilmCraft's editor.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..pipeline.captions import STYLE_PRESETS
from ..studio import engine, interchange
from . import apps
from .runner import CraftError, EffectCraft, FilmCraft

LOUDNESS_LUFS = -14.0      # the FFmpeg engine's loudnorm target
BLUR = 40.0                # Gaussian Blur blurriness for the background copies (FFmpeg: boxblur 20:2)
SILENT_DB = -60.0          # where a sound fade starts or ends
TRACK_MAP = {"Video 1": "V1"}


@dataclass
class Edit:
    folder: Path
    project: Path
    timeline: interchange.Timeline
    steps: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    shots: list[dict] = field(default_factory=list)
    ai: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def failed(self) -> list[dict]:
        return [{"id": s["id"], "why": r.get("error", ""), "for": s.get("for", "")}
                for s, r in zip(self.steps, self.results) if not r.get("ok")]

    def report(self) -> dict:
        return {"project": str(self.project), "steps": len(self.steps), "failed": self.failed(),
                "shots": self.shots, "ai": self.ai, "notes": self.notes}


# ------------------------------------------------------------------ FilmCraft's ids for the timeline's clips
def items_by_track(seq: dict) -> dict[str, list[dict]]:
    """FilmCraft's sequence, as track name -> items [{id, start, frames}] (from `inspect sequence`)."""
    out: dict[str, list[dict]] = {}
    for t in [*(seq.get("video") or []), *(seq.get("audio") or [])]:
        rows = []
        for i in t.get("items") or []:
            iid = i.get("id", i.get("clip"))
            if iid is None:
                continue
            rows.append({"id": iid, "start": int(i.get("startFrame") or 0), "frames": int(i.get("durationFrames") or 0),
                         "kind": i.get("kind") or i.get("type") or ""})
        out[t.get("name") or ""] = rows
    return out


def match(otio: dict, seq: dict) -> list[dict]:
    """Every timeline clip with FilmCraft's id for it: [{track, start, frames, meta, id}] (id None if not found)."""
    fc = items_by_track(seq)
    out = []
    for track in otio["tracks"]["children"]:
        mine = fc.get(track["name"]) or []
        by_pos = {(r["start"], r["frames"]): r["id"] for r in mine}
        by_start = {r["start"]: r["id"] for r in mine}
        for p in interchange.placements(track):
            meta = (p["clip"].get("metadata") or {}).get("clipforge") or {}
            iid = by_pos.get((p["start"], p["frames"]), by_start.get(p["start"]))
            out.append({"track": track["name"], "kind": track["kind"], "start": p["start"], "frames": p["frames"],
                        "meta": meta, "id": iid})
    return out


# ------------------------------------------------------------------ ClipForge's decisions as FilmCraft edits
def _key(clip, effect: str, param: str, frame: int, value, why: str) -> dict:
    return {"id": "effects.setParam", "params": {"clip": clip, "effect": effect, "param": param, "value": value,
                                                  "frame": int(frame), "keyframe": True}, "for": why}


def _set(clip, effect: str, param: str, value, why: str) -> dict:
    return {"id": "effects.setParam", "params": {"clip": clip, "effect": effect, "param": param, "value": value},
            "for": why}


def _fade_keys(clip, start: int, frames: int, fade_in: int, fade_out: int, level: float, why: str) -> list[dict]:
    """Volume keyframes for a fade in and/or out (FilmCraft's Volume level is in dB, 0 = the clip's own level)."""
    out = []
    end = start + frames
    if fade_in > 0:
        out += [_key(clip, "volume", "level", start, SILENT_DB, why),
                _key(clip, "volume", "level", min(end - 1, start + fade_in), level, why)]
    if fade_out > 0:
        out += [_key(clip, "volume", "level", max(start, end - 1 - fade_out), level, why),
                _key(clip, "volume", "level", end - 1, SILENT_DB, why)]
    return out


def caption_style(plan: dict, width: int, height: int) -> dict | None:
    """The caption track's look, the same as the FFmpeg engine's captions (sizes are per 1080-line frame)."""
    caps = plan.get("captions") or {}
    if not caps.get("enabled"):
        return None
    style = caps.get("style") or "clean"
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["clean"])
    scale = min(width, height) / 1080
    size = max(14, int(p["size"] * scale * (0.72 if width > height else 1.0)
                       * engine.CAPTION_SIZES.get(caps.get("size") or "medium", 1.0)))
    _align, share = engine.CAPTION_POSITIONS.get(caps.get("position") or "bottom", engine.CAPTION_POSITIONS["bottom"])
    anchor = {"middle": "middle", "top": "top"}.get(caps.get("position") or "bottom", "bottom")
    weight = {"clean": "SemiBold", "bold": "ExtraBold", "high_energy": "Black", "minimal": "Medium"}.get(style, "SemiBold")
    per_1080 = 1080 / height
    return {"track": "C1", "font": "Inter", "fontStyle": weight, "size": round(size * per_1080, 1),
            "color": "#ffffffff", "background": False, "align": "center", "anchor": anchor,
            "margin": round(min(0.45, share), 4), "outline": round(max(2, int(p.get("outline", 4) * scale))
                                                                    * per_1080, 1),
            "outlineColor": "#000000ff"}


def native_steps(plan: dict, tl: interchange.Timeline, clips: list[dict]) -> tuple[list[dict], list[str]]:
    """The FilmCraft edits that make the project look and sound like ClipForge's own render."""
    plan = engine.upgrade(plan)
    fps = tl.fps
    steps: list[dict] = []
    notes: list[str] = []
    fade_frames = lambda n, ms: min(n // 2, round(int(ms or 0) * fps / 1000))  # noqa: E731
    ov_fade = lambda n: min(round(engine.OVERLAY_FADE_S * fps), n // 4)  # noqa: E731
    missing = [c for c in clips if c["id"] is None]
    if missing:
        notes.append(f"{len(missing)} clips were not found in FilmCraft's sequence; their finishing was left out.")
    for c in clips:
        if c["id"] is None:
            continue
        m, iid, s, n = c["meta"], c["id"], c["start"], c["frames"]
        if c["kind"] == "Video" and m.get("clip_id"):  # V1 and the blurred copies under it
            fill = m.get("layout") in ("fill", "follow") or m.get("role") == "background"
            scale = 100.0 * (float(m.get("cover") or 1.0) if fill else 1.0) * float(m.get("zoom") or 1.0)
            if abs(scale - 100.0) > 0.05:
                steps.append(_set(iid, "motion", "scale", round(scale, 3), "punch-in / framing"))
            if m.get("role") == "background":
                steps.append({"id": "effects.apply", "params": {"clips": [iid], "effect": "gaussian_blur"},
                              "for": "blurred background"})
                steps.append(_set(iid, "gaussian_blur", "blurriness", BLUR, "blurred background"))
                steps.append(_set(iid, "gaussian_blur", "repeat_edge", True, "blurred background"))
        elif c["kind"] == "Video" and m.get("overlay_id"):  # pictures over the video (and their blurred copies)
            fill = m.get("fit") == "fill" or m.get("role") == "background"
            base = 100.0 * (float(m.get("cover") or 1.0) if fill else 1.0)
            if m.get("motion") == "zoom":
                steps += [_key(iid, "motion", "scale", s, round(base, 3), "push-in"),
                          _key(iid, "motion", "scale", s + n - 1, round(base * (1 + engine.OVERLAY_PUSH), 3),
                               "push-in")]
            elif abs(base - 100.0) > 0.05:
                steps.append(_set(iid, "motion", "scale", round(base, 3), "framing"))
            if m.get("role") == "background":
                steps.append({"id": "effects.apply", "params": {"clips": [iid], "effect": "gaussian_blur"},
                              "for": "blurred background"})
                steps.append(_set(iid, "gaussian_blur", "blurriness", BLUR, "blurred background"))
                steps.append(_set(iid, "gaussian_blur", "repeat_edge", True, "blurred background"))
            f = ov_fade(n)
            if f > 0:
                steps += [_key(iid, "opacity", "opacity", s, 0, "fade"),
                          _key(iid, "opacity", "opacity", s + f, 100, "fade"),
                          _key(iid, "opacity", "opacity", s + n - 1 - f, 100, "fade"),
                          _key(iid, "opacity", "opacity", s + n - 1, 0, "fade")]
    # ---- sound: speech and music types, ducking, then fades (ducking writes Volume keyframes first)
    audio = [c for c in clips if c["kind"] == "Audio" and c["id"] is not None]
    speech = [c["id"] for c in audio if c["meta"].get("clip_id") or c["meta"].get("role") == "voiceover"]
    ducked = [c["id"] for c in audio if c["meta"].get("duck") and c["meta"].get("role") != "voiceover"]
    if speech and ducked:
        depth = float((plan.get("ducking") or {}).get("depth_db", engine.DUCK_DEPTH_DB))
        steps += [{"id": "essentialSound.setType", "params": {"clips": speech, "type": "dialogue"}, "for": "ducking"},
                  {"id": "essentialSound.setType", "params": {"clips": ducked, "type": "music"}, "for": "ducking"},
                  {"id": "essentialSound.set", "params": {"clips": ducked, "key": "ducking.reduceDb",
                                                          "value": -abs(depth)}, "for": "ducking"},
                  {"id": "essentialSound.generateDucking", "params": {"clips": ducked}, "for": "ducking"}]
    by_item: dict[str, list[dict]] = {}
    for c in audio:
        key = c["meta"].get("audio_id") or f"clip:{c['meta'].get('clip_id')}:{c['start']}"
        by_item.setdefault(key, []).append(c)
    for key, parts in by_item.items():
        parts.sort(key=lambda c: c["start"])
        m = parts[0]["meta"]
        first, last = parts[0], parts[-1]
        fin = fade_frames(first["frames"], m.get("fade_in_ms"))
        fout = fade_frames(last["frames"], m.get("fade_out_ms"))
        if first is last:
            steps += _fade_keys(first["id"], first["start"], first["frames"], fin, fout, 0.0, "sound fade")
        else:
            steps += _fade_keys(first["id"], first["start"], first["frames"], fin, 0, 0.0, "sound fade")
            steps += _fade_keys(last["id"], last["start"], last["frames"], 0, fout, 0.0, "sound fade")
    style = caption_style(plan, tl.width, tl.height)
    if style and tl.counts.get("captions"):
        steps.append({"id": "captions.setStyle", "params": style, "for": "caption look"})
    return steps, notes


# ------------------------------------------------------------------ the whole edit and the render
def tools(cancelled: Callable[[], bool] | None = None) -> tuple[FilmCraft, EffectCraft | None]:
    film = apps.find_cli("filmcraft")
    if not film:
        raise apps.CraftUnavailable("FilmCraft is not set up in ClipForge yet.")
    effect = apps.find_cli("effectcraft")
    return FilmCraft(film["path"], cancelled), EffectCraft(effect["path"], cancelled) if effect else None


def edit_key(plan: dict, settings: dict | None, use_ai: bool = True) -> str:
    """What decides the FilmCraft edit of a plan: the plan, the apps' versions and whether the AI finishes it."""
    s = settings or {}
    ai_on = bool(use_ai and s.get("craft_ai_finish", True) and s.get("ai_provider", "heuristic") != "heuristic")
    raw = json.dumps({"plan": engine.upgrade(plan), "ai": ai_on and s.get("ai_provider"),
                      "apps": {k: a.version for k, a in apps.APPS.items()}}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def reuse_edit(folder: Path, key: str, plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]],
               *, name: str, revision: int) -> Edit | None:
    """The edit already made for exactly this plan (for the editor page, or by an earlier try), so the video
    rendered is the edit the person saw."""
    try:
        done = json.loads((folder / "report.json").read_text())
    except (OSError, ValueError):
        return None
    project = folder / "edit.fcproj"
    if done.get("key") != key or not project.is_file():
        return None
    tl = interchange.build(plan, assets, words_by_asset, name=name, url_for=lambda a: Path(a["path"]).as_uri(),
                           info={"revision": revision})
    edit = Edit(folder=folder, project=project, timeline=tl, shots=done.get("shots") or [], ai=done.get("ai") or {},
                notes=done.get("notes") or [])
    edit.steps = [{k: v for k, v in r.items() if k not in ("ok", "error")} for r in done.get("steps_run") or []]
    edit.results = [{"id": r.get("id"), "ok": r.get("ok"), "error": r.get("error", "")}
                    for r in done.get("steps_run") or []]
    return edit


def build_edit(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], folder: Path, *,
               name: str, revision: int, use_ai: bool = True, progress: Callable[[float, str], None] | None = None,
               cancelled: Callable[[], bool] | None = None, settings: dict | None = None) -> Edit:
    """Make the FilmCraft project of one plan in `folder` (replacing what was there)."""
    from . import ai, shots

    report = progress or (lambda _f, _m: None)
    film, effect = tools(cancelled)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    report(0.02, "Making the timeline for FilmCraft")
    pkg = interchange.write(folder / "timeline", plan, assets, words_by_asset, name=name, revision=revision,
                            portable=False)
    project = folder / "edit.fcproj"
    files = [pkg.timeline] + ([pkg.captions] if pkg.captions else [])
    imported = film.import_files(files, project)
    if not project.is_file():
        raise CraftError("FilmCraft did not write the project.")
    offline = [m for d in imported.get("documents") or [] if isinstance(d, dict) for m in d.get("offlineMedia") or []]
    if offline:
        raise CraftError(f"FilmCraft could not read {len(offline)} of the video's files.")
    edit = Edit(folder=folder, project=project, timeline=pkg.built)
    clips = match(pkg.built.otio, film.inspect(project))
    steps, edit.notes = native_steps(plan, pkg.built, clips)
    report(0.08, "Editing in FilmCraft")
    if effect and engine._has_title(engine.upgrade(plan)):
        title = next((c for c in clips if c["meta"].get("kind") == "title" and c["id"] is not None), None)
        if title:
            try:
                shot = shots.title_shot(effect, folder / "shots", plan["title"]["text"], pkg.built.width,
                                        pkg.built.height, pkg.built.fps, title["frames"])
                item = place_shot(film, project, shot["path"])
                steps.append({"id": "clip.replaceFromBin", "params": {"clips": [title["id"]], "item": item},
                              "for": "animated title (EffectCraft)"})
                edit.shots.append({**shot, "path": str(shot["path"]), "use": "title", "item": item})
            except (CraftError, apps.CraftUnavailable, OSError) as exc:
                edit.notes.append(f"The animated title was left out ({exc}); the title card is the still picture.")
    edit.steps = steps
    edit.results = film.run_steps(project, steps)
    if use_ai:
        report(0.14, "The AI is editing in FilmCraft")
        edit.ai = ai.finish(film, effect, edit, plan, words_by_asset, settings or {})
    (folder / "report.json").write_text(json.dumps({**edit.report(), "key": edit_key(plan, settings, use_ai),
                                                    "steps_run": [
        {**{k: v for k, v in s.items()}, "ok": r.get("ok"), "error": r.get("error", "")}
        for s, r in zip(edit.steps, edit.results)]}, indent=1, default=str))
    return edit


def place_shot(film: FilmCraft, project: Path, path: Path) -> int:
    """Import a rendered shot into the project's bin; returns its item id."""
    got = film.exec(project, "file.import", {"paths": [str(path)]}, save=True)
    items = got.get("items") if isinstance(got, dict) else None
    if not items:
        raise CraftError(f"FilmCraft did not import {path.name}: {(got or {}).get('errors') if isinstance(got, dict) else got}")
    first = items[0]
    return int(first["id"] if isinstance(first, dict) else first)


EXPORT = {"format": "h264", "audioCodec": "aac", "range": "entire", "loudnessLufs": LOUDNESS_LUFS,
          "bitrateMode": "crf", "crf": 20, "h264Profile": "high"}


def _export(film: FilmCraft, project: Path, out_path: Path, *, captions: bool, seconds: float) -> tuple[Path, dict,
                                                                                                         dict]:
    """FilmCraft's render of `project` next to `out_path`, checked like the FFmpeg engine's renders: a picture, sound
    and the AAC timing check (the caller checks length and size). Returns (file, probe, audio timing)."""
    from ..pipeline import audio_timing
    from ..pipeline.ffmpeg_utils import FFmpegError

    tmp = out_path.with_suffix(".filmcraft.mp4")
    tmp.unlink(missing_ok=True)
    result = film.export(project, tmp, {**EXPORT, "burnCaptions": captions}, timeout=max(1800.0, seconds * 60))
    try:
        if isinstance(result, dict) and result.get("offlineMedia"):
            raise CraftError("FilmCraft drew 'media not found' for some files; the render was not used.")
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise CraftError("FilmCraft's render wrote no file.")
        info = engine.probe(tmp)
        if not info["has_audio"]:
            raise CraftError("FilmCraft's render has no sound.")
        timing = audio_timing.require_valid(tmp)
    except (CraftError, FFmpegError) as exc:
        tmp.unlink(missing_ok=True)
        raise CraftError(str(exc)) from exc
    return tmp, info, timing


def render(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], out_path: Path, *,
           name: str, revision: int, settings: dict | None = None,
           progress: Callable[[float, str], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict:
    """The final video edited and rendered by FilmCraft; the same answer as engine.render (plus `filmcraft`).
    `progress(fraction, message)`; `cancelled()` is asked about once a second while a tool runs."""
    plan = engine.upgrade(plan)
    report = progress or (lambda _f, _m: None)
    started = time.monotonic()
    folder = out_path.parent / "filmcraft"
    edit = reuse_edit(folder, edit_key(plan, settings), plan, assets, words_by_asset, name=name,
                      revision=revision) or \
        build_edit(plan, assets, words_by_asset, folder, name=name, revision=revision,
                   progress=lambda f, m: report(f * 0.5, m), cancelled=cancelled, settings=settings)
    film, _effect = tools(cancelled)
    tl = edit.timeline
    total_s = tl.frames / tl.fps
    report(0.55, "FilmCraft is rendering the video")
    tmp, info, timing = _export(film, edit.project, out_path, captions=bool(tl.counts.get("captions")),
                                seconds=total_s)
    if abs(info["duration"] - total_s) > max(0.2, 2 / tl.fps) or (info["width"], info["height"]) != (tl.width,
                                                                                                   tl.height):
        tmp.unlink(missing_ok=True)
        raise CraftError(f"FilmCraft's render is {info['width']}x{info['height']}, {info['duration']:.2f} s instead "
                         f"of {tl.width}x{tl.height}, {total_s:.2f} s.")
    tmp.replace(out_path)
    report(0.98, "Checking FilmCraft's render")
    segs = engine.render_timeline(plan, tl.fps)
    return {"engine": "filmcraft", "preview": False, "width": info["width"], "height": info["height"],
            "duration": info["duration"], "expected_duration": round(total_s, 3), "fps": info["fps"],
            "has_audio": info["has_audio"], "audio_timing": timing, "timeline": segs,
            "audio_timeline": engine.audio_timeline(plan, segs, round(total_s * 1000)),
            "words": engine.output_words(plan, words_by_asset, segs), "captions": bool(tl.counts.get("captions")),
            "frames": tl.frames,
            "filmcraft": {**edit.report(), "version": apps.APPS["filmcraft"].version,
                          "seconds": round(time.monotonic() - started, 1)}}


def sequence_frames(seq: dict) -> int:
    """Where the sequence ends, from `inspect sequence` (its length, else the last frame any clip reaches)."""
    if isinstance(seq.get("durationFrames"), (int, float)) and seq["durationFrames"] > 0:
        return int(seq["durationFrames"])
    end = 0
    for items in items_by_track(seq).values():
        for i in items:
            if isinstance(i.get("start"), int) and isinstance(i.get("frames"), int):
                end = max(end, i["start"] + i["frames"])
    return end


def render_saved(saved: Path, plan: dict, words_by_asset: dict[str, list[dict]], out_path: Path, *, preview: bool,
                 progress: Callable[[float, str], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> dict:
    """A version the person finished by hand in FilmCraft's editor, rendered by FilmCraft from the saved project.
    The cut may differ from ClipForge's plan, so the video's own length is used, and ClipForge's time map and words
    are kept only while the length still matches the plan."""
    plan = engine.upgrade(plan)
    report = progress or (lambda _f, _m: None)
    started = time.monotonic()
    film, _effect = tools(cancelled)
    folder = out_path.parent / ("filmcraft-preview" if preview else "filmcraft")
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    project = folder / "edit.fcproj"
    shutil.copyfile(saved, project)
    report(0.05, "Opening your FilmCraft edit")
    frames = sequence_frames(film.inspect(project))
    fps = int((plan.get("output") or {}).get("fps") or 30)
    report(0.1, "FilmCraft is rendering your edit")
    tmp, info, timing = _export(film, project, out_path, captions=bool((plan.get("captions") or {}).get("enabled")),
                                seconds=max(frames / fps, 1.0))
    if frames and abs(info["duration"] - frames / fps) > max(0.2, 2 / fps):
        tmp.unlink(missing_ok=True)
        raise CraftError(f"FilmCraft's render is {info['duration']:.2f} s but the edit is {frames / fps:.2f} s.")
    tmp.replace(out_path)
    plan_s = engine.duration_ms(plan) / 1000
    same = abs(info["duration"] - plan_s) <= max(0.2, 2 / fps)
    segs = engine.render_timeline(plan, fps) if same else []
    return {"engine": "filmcraft", "preview": preview, "width": info["width"], "height": info["height"],
            "duration": info["duration"], "expected_duration": round(info["duration"] if not same else plan_s, 3),
            "fps": info["fps"], "has_audio": info["has_audio"], "audio_timing": timing, "timeline": segs,
            "audio_timeline": engine.audio_timeline(plan, segs, round(plan_s * 1000)) if same else [],
            "words": engine.output_words(plan, words_by_asset, segs) if same else [], "frames": frames,
            "filmcraft": {"hand_edited": True, "project": str(saved), "same_length_as_plan": same,
                          "version": apps.APPS["filmcraft"].version, "seconds": round(time.monotonic() - started, 1)}}
