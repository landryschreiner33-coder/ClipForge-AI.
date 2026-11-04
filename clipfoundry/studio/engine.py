"""The full-video engine adapter, version ffmpeg-v1 (docs/clipforge/EDITOR_INTEGRATION.md).

An edit plan is engine-independent JSON with integer-millisecond times (timebase 1000). This adapter declares what it
supports, validates a plan against it (anything else is reported before rendering, never silently dropped), builds
the exact output time map, and renders from the full originals on the server. A preview is the same plan at a small
size and a fast preset, so preview and export follow one code path.

Audio follows the clip renderer's rules: each input clock is rebuilt first (aresample async, first_pts=0), the whole
edited mix is measured once for one constant normalization gain (no startup pumping), a peak limiter without
auto-level runs last, and the final sample clock is rebuilt from the actual output samples (asetpts=N/SR/TB).
Supplied music is ducked under speech with a sidechain compressor; speech itself is never compressed.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable

from .. import config
from ..pipeline import audio_timing
from ..pipeline.captions import STYLE_PRESETS, chunk_words, hex_to_ass
from ..pipeline.ffmpeg_utils import FFmpegError, ffmpeg_bin, filter_path, probe, run, run_process

ENGINE = "ffmpeg-v1"
SCHEMA = 1
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
PREVIEW_HEIGHT = 360
TRANSITIONS = {"cut": None, "dissolve": "fade", "fade": "fadeblack"}
SUPPORTED = {"clips", "trim", "reorder", "include", "image", "transition", "title", "captions", "music", "gain",
             "aspect", "layout"}
UNSUPPORTED = {"color_grade": "colour grading", "keyframes": "keyframed motion", "pip": "picture in picture",
               "speed": "speed changes", "effects": "effects", "multicam": "multicam"}


def capabilities() -> dict:
    return {"engine": ENGINE, "schema": SCHEMA, "supported": sorted(SUPPORTED), "aspects": list(ASPECTS),
            "transitions": list(TRANSITIONS), "unsupported": UNSUPPORTED,
            "notes": "Renders from the full original files on the server; previews use the same plan at 360p."}


def _dur(c: dict) -> int:
    return int(c["out_ms"]) - int(c["in_ms"])


def validate(plan: dict, assets: dict[str, dict]) -> list[str]:
    """Problems that stop a render (unsupported operations are listed, never dropped)."""
    out = []
    if plan.get("schema") != SCHEMA or plan.get("timebase") != 1000:
        out.append("This plan was made for another editor version.")
    for key, label in UNSUPPORTED.items():
        if plan.get(key):
            out.append(f"{label.capitalize()} is not supported by this editor yet.")
    if (plan.get("output") or {}).get("aspect") not in ASPECTS:
        out.append("Choose 16:9, 9:16, 1:1 or 4:5.")
    clips = [c for c in plan.get("clips") or [] if c.get("include", True)]
    if not clips:
        out.append("Every clip is removed; keep at least one.")
    for c in clips:
        a = assets.get(c.get("asset_id"))
        if not a:
            out.append(f"Clip “{c.get('label', '?')}” refers to a file that is missing.")
            continue
        if a["kind"] not in ("video", "image"):
            out.append(f"“{a['filename']}” is not a video or image.")
        if not Path(a["path"]).is_file():
            out.append(f"The original file “{a['filename']}” is missing on the server. Upload it again.")
        if _dur(c) < 200:
            out.append(f"Clip “{c.get('label', '?')}” is shorter than 0.2 s.")
        if a["kind"] == "video":
            length = int(float((a.get("probe") or {}).get("duration") or 0) * 1000)
            if c["in_ms"] < 0 or (length and c["out_ms"] > length + 50):
                out.append(f"Clip “{c.get('label', '?')}” is trimmed outside its file.")
    music = plan.get("music") or {}
    if music.get("asset_id") and (assets.get(music["asset_id"]) or {}).get("kind") != "audio":
        out.append("The music track is missing or is not an audio file.")
    t = (plan.get("transition") or {})
    if t.get("type", "cut") not in TRANSITIONS:
        out.append("Unknown transition.")
    if t.get("type", "cut") != "cut" and clips:
        shortest = min(_dur(c) for c in clips)
        if int(t.get("ms") or 0) * 2 >= shortest:
            out.append("A transition is longer than half of the shortest clip; shorten it.")
    return out


def _has_title(plan: dict) -> bool:
    title = plan.get("title") or {}
    return bool(title.get("enabled") and title.get("text"))


def timeline(plan: dict) -> list[dict]:
    """The output time map: every included clip's source range and where it plays, in integer milliseconds.
    A transition overlaps each pair of neighbours (the title card counts as the first element), so every later
    element starts earlier by the transition length, exactly as the filter graph joins them."""
    t = plan.get("transition") or {}
    overlap = int(t.get("ms") or 0) if t.get("type", "cut") != "cut" else 0
    pos = int((plan.get("title") or {}).get("ms") or 0) if _has_title(plan) else 0
    first = not _has_title(plan)
    out = []
    for c in (c for c in plan.get("clips") or [] if c.get("include", True)):
        start = pos if first else pos - overlap
        first = False
        out.append({"clip_id": c["id"], "asset_id": c["asset_id"], "kind": c.get("kind", "video"),
                    "src_in_ms": int(c["in_ms"]), "src_out_ms": int(c["out_ms"]), "out_start_ms": start,
                    "out_end_ms": start + _dur(c)})
        pos = start + _dur(c)
    return out


def duration_ms(plan: dict) -> int:
    tl = timeline(plan)
    return tl[-1]["out_end_ms"] if tl else 0


def output_words(plan: dict, words_by_asset: dict[str, list[dict]]) -> list[dict]:
    """The words heard in the output, on the output timeline (seconds), through the time map."""
    out = []
    for seg in timeline(plan):
        a, b = seg["src_in_ms"] / 1000, seg["src_out_ms"] / 1000
        shift = seg["out_start_ms"] / 1000 - a
        for w in words_by_asset.get(seg["asset_id"]) or []:
            if w["start"] >= a - 0.01 and w["end"] <= b + 0.01:
                out.append({"w": w["w"], "start": round(w["start"] + shift, 3), "end": round(w["end"] + shift, 3),
                            "clip_id": seg["clip_id"], "src_start": w["start"], "src_end": w["end"]})
    return out


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def captions_ass(words: list[dict], captions: dict, width: int, height: int) -> str:
    """Captions sized and placed for this output frame (the clip captions assume 1080x1920)."""
    style = captions.get("style") or "clean"
    p = STYLE_PRESETS.get(style, STYLE_PRESETS["clean"])
    scale = min(width, height) / 1080
    size = max(18, int(p["size"] * scale * (0.72 if width > height else 1.0)))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(captions.get("position") or "bottom", 2)
    margin = int(height * (0.08 if align != 5 else 0))
    bold = -1 if style in ("bold", "high_energy") else 0
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding",
             f"Style: Cap,{p['font']},{size},{hex_to_ass('#FFFFFF')},{hex_to_ass('#FFFFFF')},&H00000000,&H64000000,"
             f"{bold},0,0,0,100,100,0,0,1,{max(2, int(4 * scale))},1,{align},60,60,{margin},1", "", "[Events]",
             "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for chunk in chunk_words(words, style):
        text = " ".join(w["w"].strip() for w in chunk).replace("{", "(").replace("}", ")").replace("\\", "/")
        if p.get("upper"):
            text = text.upper()
        lines.append(f"Dialogue: 0,{_ass_time(chunk[0]['start'])},{_ass_time(chunk[-1]['end'] + 0.15)},Cap,,0,0,0,,"
                     f"{text}")
    return "\n".join(lines) + "\n"


def _font() -> Path:
    return config.FONTS_DIR / "Poppins-SemiBold.ttf"


def _graph(plan: dict, assets: dict[str, dict], width: int, height: int, fps: int, work: Path,
           captions_file: str | None, norm_gain_db: float | None, measure: bool) -> tuple[list[str], str]:
    """(input arguments, filter graph) for the whole plan."""
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[tuple[str, str, int]] = []

    def video(part: str) -> None:
        if not measure:
            parts.append(part)

    layout = plan.get("layout") or "fit"
    title = plan.get("title") or {}
    if _has_title(plan):
        secs = int(title["ms"]) / 1000
        (work / "title.txt").write_text(title["text"][:120], encoding="utf-8")
        idx = 0
        inputs += ["-f", "lavfi", "-i", f"color=c=0x0B0D14:s={width}x{height}:r={fps}:d={secs:.3f}"]
        font = filter_path(_font(), work)
        video(f"[{idx}:v]drawtext=fontfile={font}:textfile=title.txt:fontcolor=white:fontsize="
                     f"{int(height * 0.07)}:x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p,setsar=1,settb=AVTB,"
                     f"setpts=PTS-STARTPTS,fps={fps},settb=AVTB[v_title]")
        parts.append(f"aevalsrc=0:c=stereo:s=48000:d={secs:.3f},aformat=sample_fmts=fltp:sample_rates=48000:"
                     f"channel_layouts=stereo[a_title]")
        labels.append(("[v_title]", "[a_title]", int(title["ms"])))
    for k, c in enumerate(c for c in plan["clips"] if c.get("include", True)):
        a = assets[c["asset_id"]]
        secs = _dur(c) / 1000
        idx = sum(1 for x in inputs if x == "-i")
        if a["kind"] == "image":
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.3f}", "-i", a["path"]]
        else:
            inputs += ["-ss", f"{c['in_ms'] / 1000:.3f}", "-t", f"{secs:.3f}", "-i", a["path"]]
        if layout == "fill":
            vchain = f"[{idx}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        else:
            video(f"[{idx}:v]split[bgs{k}][fgs{k}]")
            video(f"[bgs{k}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                         f"boxblur=20:2[bg{k}]")
            video(f"[fgs{k}]scale={width}:{height}:force_original_aspect_ratio=decrease[fg{k}]")
            vchain = f"[bg{k}][fg{k}]overlay=(W-w)/2:(H-h)/2"
        video(f"{vchain},fps={fps},format=yuv420p,setsar=1,trim=duration={secs:.3f},settb=AVTB,"
                     f"setpts=PTS-STARTPTS,fps={fps},settb=AVTB[v{k}]")
        gain = float(c.get("gain_db") or 0)
        has_audio = a["kind"] == "video" and (a.get("probe") or {}).get("has_audio")
        if has_audio:
            parts.append(f"[{idx}:a]aresample=48000:async=1:first_pts=0,apad=whole_dur={secs:.6f},"
                         f"atrim=duration={secs:.6f},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:"
                         f"sample_rates=48000:channel_layouts=stereo,volume={gain:.2f}dB[a{k}]")
        else:
            parts.append(f"aevalsrc=0:c=stereo:s=48000:d={secs:.6f},aformat=sample_fmts=fltp:sample_rates=48000:"
                         f"channel_layouts=stereo[a{k}]")
        labels.append((f"[v{k}]", f"[a{k}]", _dur(c)))
    t = plan.get("transition") or {}
    kind = TRANSITIONS.get(t.get("type", "cut"))
    if kind is None or len(labels) == 1:
        if measure:  # the measuring pass reads the audio only
            parts.append("".join(a for _, a, _ in labels) + f"concat=n={len(labels)}:v=0:a=1[aj]")
        else:
            parts.append("".join(v + a for v, a, _ in labels) + f"concat=n={len(labels)}:v=1:a=1[vj][aj]")
    else:
        ms = int(t.get("ms") or 400)
        vprev, aprev, offset = labels[0][0], labels[0][1], labels[0][2]
        for k, (v, a, d) in enumerate(labels[1:], 1):
            offset_s = (offset - ms) / 1000
            vout, aout = (f"[vx{k}]", f"[ax{k}]") if k < len(labels) - 1 else ("[vj]", "[aj]")
            # FFmpeg may clear the frame-rate metadata after timestamp edits or a preceding transition.
            # Re-establish a real CFR stream and common time base before the next xfade consumes this output.
            video(f"{vprev}{v}xfade=transition={kind}:duration={ms / 1000:.3f}:offset={offset_s:.3f},"
                         f"fps={fps},settb=AVTB{vout}")
            parts.append(f"{aprev}{a}acrossfade=d={ms / 1000:.3f}:c1=tri:c2=tri{aout}")
            vprev, aprev, offset = vout, aout, offset - ms + d
    total = duration_ms(plan) / 1000
    music = plan.get("music") or {}
    speech = "[aj]"
    if music.get("asset_id"):
        idx = sum(1 for x in inputs if x == "-i")
        inputs += ["-stream_loop", "-1", "-i", assets[music["asset_id"]]["path"]]
        level = float(music.get("level_db", -18))
        parts.append(f"[{idx}:a]aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:"
                     f"channel_layouts=stereo,atrim=duration={total:.6f},asetpts=PTS-STARTPTS,volume={level:.2f}dB[mus]")
        parts.append("[aj]asplit=2[sp][sc]")
        # the music dips while someone speaks; the speech path is never compressed
        parts.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[duck]")
        parts.append("[sp][duck]amix=inputs=2:duration=first:normalize=0[mix]")
        speech = "[mix]"
    post = ["aformat=sample_fmts=dbl:sample_rates=48000:channel_layouts=stereo"]
    if measure:
        post.append("loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json")
    else:
        if norm_gain_db is not None:
            post.append(f"volume={norm_gain_db:.6f}dB:precision=double")
        post += ["aresample=48000", "alimiter=limit=0.841395:attack=5:release=50:level=disabled:latency=1",
                 "asettb=1/48000", "asetpts=N/SR/TB"]
    parts.append(speech + ",".join(post) + "[aout]")
    if captions_file:
        fonts = filter_path(config.FONTS_DIR, work)
        video(f"[vj]ass={captions_file}:fontsdir={fonts},format=yuv420p[vout]")
    else:
        video("[vj]format=yuv420p[vout]")
    return inputs, ";".join(parts)


def _measure(plan: dict, assets: dict, width: int, height: int, fps: int, work: Path, cancelled) -> float:
    inputs, graph = _graph(plan, assets, width, height, fps, work, None, None, True)
    total = duration_ms(plan) / 1000
    result = run_process([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", *inputs,
                          "-filter_complex", graph, "-map", "[aout]", "-f", "null", "-"],
                         timeout=max(120.0, total * 6), cancel=cancelled, cwd=str(work))
    if result.returncode:
        raise FFmpegError("Could not measure the video's audio: " +
                          result.stderr.decode("utf-8", "replace")[-400:])
    blocks = re.findall(r'\{\s*"input_i"\s*:.*?\}', result.stderr.decode("utf-8", "replace"), re.S)
    if not blocks:
        return 0.0
    measured = json.loads(blocks[-1])
    integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
    if not math.isfinite(integrated):
        return 0.0  # silence: never amplify background noise blindly
    return max(-24.0, min(-14.0 - integrated, -1.5 - peak, 24.0))


def render(plan: dict, assets: dict[str, dict], words_by_asset: dict[str, list[dict]], out_path: Path, *,
           preview: bool = False, settings: dict | None = None, progress: Callable[[float], None] | None = None,
           cancelled: Callable[[], bool] | None = None) -> dict:
    """Render the plan to `out_path`; returns the probe, time map, final transcript and audio checks of the file."""
    problems = validate(plan, assets)
    if problems:
        raise ValueError("; ".join(problems))
    work = out_path.parent
    work.mkdir(parents=True, exist_ok=True)
    width, height = ASPECTS[plan["output"]["aspect"]]
    if preview:
        scale = PREVIEW_HEIGHT / min(width, height)
        width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    fps = int((plan.get("output") or {}).get("fps") or 30)
    words = output_words(plan, words_by_asset)
    captions = plan.get("captions") or {}
    cap_name = None
    if captions.get("enabled") and words:
        cap_name = ("preview" if preview else "final") + ".captions.ass"
        (work / cap_name).write_text(captions_ass(words, captions, width, height), encoding="utf-8")
    gain = _measure(plan, assets, width, height, fps, work, cancelled)
    inputs, graph = _graph(plan, assets, width, height, fps, work, cap_name, gain, False)
    total = duration_ms(plan) / 1000
    tmp = out_path.with_suffix(".tmp.mp4")
    encode = ["-c:v", "libx264", "-preset", "ultrafast" if preview else (settings or {}).get("video_preset")
              or "veryfast", "-crf", "30" if preview else "20", "-pix_fmt", "yuv420p", "-r", str(fps)]
    run([*inputs, "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]", *encode, "-c:a", "aac",
         "-profile:a", "aac_low", "-b:a", "128k" if preview else "192k", "-ac", "2", "-ar", "48000",
         "-movflags", "+faststart", "-t", f"{total:.6f}", tmp.name],
        duration=total, progress=progress, cancel=cancelled, cwd=work)
    tmp.replace(out_path)
    info = probe(out_path)
    timing = audio_timing.require_valid(out_path)
    return {"engine": ENGINE, "preview": preview, "width": info["width"], "height": info["height"],
            "duration": info["duration"], "expected_duration": round(total, 3), "fps": info["fps"],
            "has_audio": info["has_audio"], "audio_timing": timing, "normalization_gain_db": round(gain, 3),
            "timeline": timeline(plan), "words": words, "captions": bool(cap_name)}
