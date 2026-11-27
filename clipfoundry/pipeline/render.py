"""Render one clip: trim -> silence cleanup -> 9:16 reframe -> zoom -> captions -> H.264/AAC MP4.

Video frames flow ffmpeg (decode) -> numpy/OpenCV (sub-pixel crop, zoom,
layout) -> ffmpeg (burn ASS captions + encode).  Audio is cut with the same
keep-segments so picture and sound stay in sync.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from contextlib import nullcontext
from pathlib import Path

import cv2
import numpy as np

from .. import config, gpu
from ..config import OUTPUT_H, OUTPUT_W
from . import artifact, audio_timing, captions, cleanup, facecam, grade, loops, moves, reframe, trims
from . import blueprint as blueprint_mod
from .common import Cancelled, JobContext, log, read_json, write_json
from .ffmpeg_utils import (NO_WINDOW, AUDIO_BITRATE, FFmpegError, MediaWatchdog, delivery_args, ffmpeg_bin,
                           filter_path, run_process, thumbnail, video_encoder_args)

SILENCE_PRESETS = {"light": (0.8, 0.22), "aggressive": (0.35, 0.08)}  # (min gap removed, padding kept)
FILLER_WORD = re.compile(r"^(um+|uh+|erm+|hmm+|mm+|ah+)[,.!?]*$", re.I)
SPEED_RANGE = (0.8, 1.25)
PLAN_VERSION = 3  # moving-content fallback and recovery after prolonged face dropouts
CAM_FILE = facecam.CAM_FILE  # in the project's folder: the face cam found in this video (find_cam's hint)
CAPTIONS_STEP = "Writing captions"  # progress messages that tell the office which part of the render runs
FRAMES_STEP = "Rendering"
COLOUR_STEP = "Checking the colour"


# ------------------------------------------------------------ timeline
def heard(folder: str | Path, words: list[dict], start: float, end: float,
          settings: dict | None = None, offset: float = 0.0) -> list[tuple[float, float]]:
    """Loud stretches without words in [start, end] (a laugh, a shout, a crowd; virality.wordless_loud), from the
    loudness measured when the project's video was analyzed (`folder`: the project folder). Remove pauses keeps
    them: they are not silence. `offset`: where the rendered file starts in that recording (a live clip renders from
    a window of the stream; its words and times are the window's, the loudness is the whole recording's)."""
    if offset:
        moved = [{**w, "start": w["start"] + offset, "end": w["end"] + offset} for w in words]
        return [(round(a - offset, 3), round(b - offset, 3))
                for a, b in heard(folder, moved, start + offset, end + offset, settings)]
    env = read_json(Path(folder) / "loudness.json", None)
    if not env or not env.get("db"):
        return []
    from .audio import Loudness
    from .virality import wordless_loud

    runs = wordless_loud(words, Loudness(env), start, end)
    sounds = Path(folder) / "sounds.json"
    from . import listen

    # what ClipForge AI heard there too (listen.py): a quiet laugh is not a pause either (not when Listening is off)
    if sounds.is_file() and (settings is None or listen.enabled(settings)):
        from .virality import HEARD_REACTIONS

        got = listen.load(sounds)
        if got is not None:
            runs = sorted(runs + got.reaction_runs(start, end, words, kinds=HEARD_REACTIONS))
            merged: list[tuple[float, float]] = []
            for a, b in runs:
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], b))
                else:
                    merged.append((a, b))
            runs = merged
    return runs


def keep_segments(words: list[dict], start: float, end: float, mode: str, fps: float,
                  drop_fillers: bool = False, within: list[tuple[float, float]] | None = None,
                  loud: list[tuple[float, float]] | None = None) -> list[tuple[float, float]]:
    """Source-time ranges to keep; long pauses between words are removed, except that a pause that builds tension
    keeps up to a second (trims.tension_pause). With `drop_fillers`, an "um" or "uh"
    counts as part of the pause around it, so it goes too when that pause is long enough to cut. `within` (a
    blueprint's source intervals) keeps only what lies inside them, before everything is put on the frame grid.
    `loud` (`heard`) are reactions without words: kept like words, so a laugh after the punchline stays."""
    segs: list[tuple[float, float]]
    if mode not in SILENCE_PRESETS or not words:
        segs = [(start, end)]
    else:
        min_gap, pad = SILENCE_PRESETS[mode]
        cuts = []
        ws = [w for w in words if w["end"] > start and w["start"] < end
              and not (drop_fillers and FILLER_WORD.match(w["w"].strip()))]
        ws = sorted(ws + [{"w": "", "start": a, "end": b} for a, b in loud or [] if b > start and a < end],
                    key=lambda w: w["start"])
        prev_end = start
        for k, w in enumerate(ws):
            if w["start"] - prev_end > min_gap:
                # a pause that builds tension (after a question, "guess what") is shortened, never removed
                said = [x for x in ws[:k] if x["w"]]
                keep = trims.TENSION_KEEP[mode] / 2 if said and ws[k - 1]["w"] and trims.tension_pause(said) else pad
                a = prev_end + keep if prev_end > start else start
                b = w["start"] - keep
                if b - a > 0.05:
                    cuts.append((a, b))
            prev_end = max(prev_end, w["end"])
        if end - prev_end > min_gap + pad:
            cuts.append((prev_end + pad + 0.1, end))
        segs = []
        cur = start
        for a, b in cuts:
            if a > cur:
                segs.append((cur, a))
            cur = max(cur, b)
        if cur < end:
            segs.append((cur, end))
    if within:
        segs = [(max(a, wa), min(b, wb)) for a, b in segs for wa, wb in within if min(b, wb) - max(a, wa) > 1e-6]
    # snap to the frame grid so audio and video lengths match exactly
    out = []
    for a, b in segs:
        fa = start + round((a - start) * fps) / fps
        fb = start + round((b - start) * fps) / fps
        if fb - fa >= 2 / fps:
            if out and abs(out[-1][1] - fa) < 1e-6:
                out[-1] = (out[-1][0], fb)
            else:
                out.append((fa, fb))
    return out or [(start, end)]


class Timeline:
    """Maps source time to output time: kept segments back to back, played at `speed`."""

    def __init__(self, segs: list[tuple[float, float]], speed: float = 1.0):
        self.segs = segs
        self.speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], float(speed or 1.0)))
        self.offsets = []
        acc = 0.0
        for a, b in segs:
            self.offsets.append(acc)
            acc += b - a
        self.duration = acc / self.speed

    def to_out(self, t: float) -> float:
        for (a, b), off in zip(self.segs, self.offsets):
            if t < a:
                return off / self.speed
            if t <= b:
                return (off + (t - a)) / self.speed
        return self.duration

    def contains(self, t: float) -> bool:
        return any(a - 1e-6 <= t < b - 1e-6 for a, b in self.segs)

    def cut_frames(self, start: float, fps: float) -> list[float]:
        """Output times (whole frames) at which render_clip's frame loop first shows each part after the first: the
        frame after the last one the part before fills (the loop writes while `written <= to_out(t) * fps + 0.5`)."""
        out = []
        for _a, b in self.segs[:-1]:
            k = math.ceil((b - 1e-6 - start) * fps) - 1  # the part's last source frame (start + k / fps < b - 1e-6)
            while start + (k + 1) / fps < b - 1e-6:
                k += 1
            while k > 0 and not start + k / fps < b - 1e-6:
                k -= 1
            out.append((math.floor(self.to_out(start + k / fps) * fps + 0.5) + 1) / fps)
        return out


# ------------------------------------------------------------ emphasis (the zoom itself: moves.py)
EMPHASIS_EXTRA = {"never", "always", "biggest", "worst", "best", "most", "only", "first", "last", "every", "nobody",
                  "everyone", "secret", "truth", "mistake", "wrong", "simple", "whole", "exactly"}


def emphasis_words(words_out: list[dict], keywords: set[str] | None = None, min_gap: float = 2.5) -> set[int]:
    """Indices of words worth stressing (numbers, strong or emotional words, the clip's keywords), at most one per
    `min_gap` seconds so emphasis stays rare enough to mean something."""
    from .text_utils import EMOTION_WORDS, HOOK_WORDS

    keywords = keywords or set()
    scored = []
    for i, w in enumerate(words_out):
        tok = re.sub(r"[^\w']", "", w["w"].lower())
        if len(tok) < 3 and not tok.isdigit():
            continue
        score = ((3 if tok in keywords else 0) + (3 if any(c.isdigit() for c in tok) else 0)
                 + (2 if tok in EMOTION_WORDS else 0) + (1 if tok in HOOK_WORDS or tok in EMPHASIS_EXTRA else 0))
        if score:
            scored.append((score, i))
    picked: list[int] = []
    for _, i in sorted(scored, key=lambda x: (-x[0], x[1])):
        if all(abs(words_out[i]["start"] - words_out[j]["start"]) >= min_gap for j in picked):
            picked.append(i)
    return set(picked)


# ------------------------------------------------------------ helpers
def _decode_size(w: int, h: int) -> tuple[int, int]:
    s = min(1.0, 1920 / max(1, h), 3840 / max(1, w))
    dw, dh = int(w * s) // 2 * 2, int(h * s) // 2 * 2
    return max(2, dw), max(2, dh)


def _audio_filter(segs: list[tuple[float, float]], start: float, opts: dict, *,
                  normalization_gain_db: float | None = None, measure: bool = False,
                  input_label: str = "1:a:0", effects_label: str | None = None,
                  effects_gain_db: float = 0.0) -> str:
    rel = [(a - start, b - start) for a, b in segs]
    # Input seeking resets the shared source clock, but the first audio packet may still arrive late. Rebuild
    # that clock before any trims: resetting PTS independently would move all speech earlier than the picture.
    parts = [f"[{input_label}]aresample=48000:async=1:first_pts=0,apad=whole_dur={rel[-1][1]:.6f}[clock]"]
    fade = 0.01
    if len(rel) == 1:
        a, b = rel[0]
        # 10 ms in and out, like every part of a cut clip: a clip that starts or stops mid-sound never clicks
        parts.append(f"[clock]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d={fade},"
                     f"afade=t=out:st={max(0.0, b - a - fade):.4f}:d={fade}[ac]")
    else:
        labels = "".join(f"[s{i}]" for i in range(len(rel)))
        parts.append(f"[clock]asplit={len(rel)}{labels}")
        for i, (a, b) in enumerate(rel):
            d = b - a
            parts.append(f"[s{i}]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0.0, d - fade):.4f}:d={fade}[c{i}]")
        parts.append("".join(f"[c{i}]" for i in range(len(rel))) + f"concat=n={len(rel)}:v=0:a=1[ac]")
    chain = "[ac]"
    # Downmix before loudness/peak control so a multichannel mix cannot overload after being limited.
    post = ["aformat=sample_fmts=dbl:sample_rates=48000:channel_layouts=stereo"]
    speed = float(opts.get("speed", 1.0) or 1.0)
    if abs(speed - 1.0) > 0.001:
        post.append(f"atempo={max(SPEED_RANGE[0], min(SPEED_RANGE[1], speed)):.4f}")  # faster, same pitch
    if measure:
        # Discard this output. Only the measurements of the exact edited timeline are used on the encode pass.
        post.append("loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json")
        parts.append(chain + ",".join(post) + "[a]")
        return ";".join(parts)
    if opts.get("normalize_audio", True):
        if normalization_gain_db is None or not math.isfinite(normalization_gain_db):
            raise ValueError("Audio normalization requires a measured, finite gain")
        # One constant gain avoids single-pass loudnorm's excessive startup boost and slow volume pumping.
        post.append(f"volume={normalization_gain_db:.6f}dB:precision=double")
    if effects_label:
        # The sound effects (moves.py) are made for speech at -14 LUFS; `effects_gain_db` moves them with the
        # speech's real loudness (normalization off or held back by peaks). They join after the loudness gain and
        # before the owner's volume, so that volume turns the whole mix up or down, and share the limiter.
        parts.append(chain + ",".join(post) + "[speech]")
        parts.append(f"[{effects_label}]aformat=sample_fmts=dbl:sample_rates=48000:channel_layouts=stereo,"
                     f"volume={effects_gain_db:.2f}dB[fx]")
        chain, post = "[speech][fx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0", [""]
    gain = float(opts.get("gain_db", 0) or 0)
    if abs(gain) > 0.01:
        post.append(f"volume={gain:.2f}dB")
    # Gain follows normalization, so even normalized speech can otherwise hard-clip at the allowed +12 dB.
    # Disable the limiter's default auto-level boost and compensate its lookahead to keep cuts/captions aligned.
    post += ["aresample=48000", "alimiter=limit=0.841395:attack=5:release=50:level=disabled:latency=1",
             "asettb=1/48000", "asetpts=N/SR/TB"]
    # Rebuild the final clock from actual output samples, after every rate/cut/limiter operation. Source
    # delays are already represented by samples above; filter buffering must not become MP4 timestamp gaps.
    parts.append(chain + ",".join(post) + "[a]")
    return ";".join(parts)


def _measure_audio(audio_in: list[str], segs: list[tuple[float, float]], start: float, opts: dict,
                   duration: float, ctx: JobContext, always: bool = False) -> dict:
    """Measure the kept/downmixed/speed-adjusted audio once, without storing samples or touching the GPU. With
    normalization off it is measured only when `always` (the sound effects need the speech's loudness)."""
    base = {"version": 1, "normalization": "off", "normalization_gain_db": 0.0}
    normalize = bool(opts.get("normalize_audio", True))
    if not normalize and not always:
        return base
    ctx.check()
    ctx.progress(0.03, "Measuring audio")
    graph = _audio_filter(segs, start, opts, measure=True, input_label="0:a:0")
    result = run_process([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info",
                          *audio_in, "-filter_complex", graph, "-map", "[a]", "-f", "null", "-"],
                         timeout=max(60.0, duration * 5), cancel=ctx.cancelled)
    if result.returncode:
        raise FFmpegError("Could not measure the clip's audio. Check the source and try rendering again.")
    try:
        # FFmpeg reports input measurements after processing the whole edited clip, including its last word.
        blocks = re.findall(r'\{\s*"input_i"\s*:.*?\}', result.stderr.decode("utf-8", "replace"), re.S)
        measured = json.loads(blocks[-1])
        integrated, peak = float(measured["input_i"]), float(measured["input_tp"])
        if math.isnan(integrated) or math.isnan(peak) or integrated == math.inf or peak == math.inf:
            raise ValueError("invalid loudness")
        if peak == -math.inf and integrated != -math.inf:
            raise ValueError("invalid peak")
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise FFmpegError("Audio measurement was incomplete. Try rendering the clip again.") from exc
    if not normalize:
        return {**base, "integrated_lufs": integrated if math.isfinite(integrated) else None}
    # Ungated/silent material has no usable integrated loudness; never amplify its background noise blindly.
    gain = min(-14.0 - integrated, -1.5 - peak, 24.0) if math.isfinite(integrated) else 0.0
    return {**base, "normalization": "measured_fixed_gain", "target_lufs": -14.0,
            "integrated_lufs": integrated if math.isfinite(integrated) else None,
            "true_peak_dbfs": peak if math.isfinite(peak) else None,
            "normalization_gain_db": gain, "max_boost_db": 24.0,
            "peak_limited": math.isfinite(integrated) and -1.5 - peak < -14.0 - integrated}


def _clean_sound(src: str, start: float, end: float, words_all: list[dict], opts: dict,
                 ctx: JobContext) -> "cleanup.Result | None":
    """The clip's cleaned-up sound (pipeline/cleanup.py), or None to use the source's own. A failure keeps the
    original sound and says why in the render's notes; it never fails the render."""
    mode = opts.get("clean_sound") or "off"
    if mode == "off" or mode not in cleanup.MODES:
        return None
    return cleanup.clean_or_keep(src, start, end, words_all, mode, cancelled=ctx.cancelled,
                                 progress=lambda _f, message: ctx.progress(0.03, message))


def _map_words(words: list[dict], tl: Timeline, start: float, end: float) -> list[dict]:
    out = []
    for w in words:
        if w["end"] <= start or w["start"] >= end:
            continue
        s = tl.to_out(max(start, w["start"]))
        e = tl.to_out(min(end, w["end"]))
        if e - s < 0.04:
            e = s + 0.04
        out.append({"start": s, "end": min(e, tl.duration), "w": w["w"]})
    return out


def effective_options(settings: dict, project_opts: dict, edit: dict) -> dict:
    keys = ["caption_style", "caption_position", "highlight_words", "tracking", "layout", "silence", "auto_zoom",
            "hook_overlay", "hook_seconds", "normalize_audio", "remove_fillers", "caption_emphasis", "clean_sound",
            "split_view", "split_game", "auto_color", "look", "look_strength", "clean_picture", "sound_effects",
            "loop_ending"]
    opts = {k: settings.get(k) for k in keys}
    opts.update({k: v for k, v in (project_opts or {}).items() if k in keys and v is not None})
    opts.update({k: v for k, v in (edit or {}).items() if v is not None})
    return opts


def cam_layout(opts: dict, chosen: bool, rendered: dict | None = None) -> str:
    """The layout a clip is planned with. When nobody chose this clip's layout (it is simply the one from Settings)
    and Settings → Split view is on, the picture is first searched for a face cam ("auto"): with one the clip
    becomes a split view, without one it gets the Settings layout as before. A layout somebody chose for this clip,
    its video or its kind of video (the editor, the project, a style, a Brain note, story clips) stays that.

    A clip that was rendered before (`rendered`, its render_info) keeps whether it looked for a face cam: a later
    change of Settings → Split view, or an update that added it, is for new clips. So a re-render for a caption fix
    or a version gives the look the clip editor shows, and a clip made before split view existed stays as made."""
    layout = opts.get("layout") or "fill"
    if layout not in config.LAYOUTS or chosen:
        return layout
    looks = (rendered or {}).get("layout_asked") == "auto" if (rendered or {}).get("layout") else \
        opts.get("split_view") == "auto"
    return "auto" if looks else layout


def layout_chosen(project: dict, clip: dict, blueprint=None) -> bool:
    """Whether somebody chose this clip's layout (see cam_layout), before any Brain note is asked. The plan of an
    Autopilot clip made that call when it was written, and the clip's own editor always counts: a layout set there,
    or a way to follow the picture (the owner is placing the crop by hand). A ClipForge project's guidance names a
    layout in every case, so there it counts only when it is not simply the one from Settings."""
    edit = clip.get("edit") or {}
    if blueprint is not None or edit.get("layout") is not None or edit.get("tracking") not in (None, "auto"):
        return True
    guidance = project.get("guidance") or {}
    if guidance.get("schema"):
        return any(d.get("field") == "layout" and (d.get("from") or {}).get("level") != "settings"
                   for d in guidance.get("decisions") or [])
    return (project.get("options") or {}).get("layout") is not None


# ------------------------------------------------------------ main
def edit_hash(edit: dict) -> str:
    """Fingerprint of an edit (tells whether a rendered version still matches the clip's current edit)."""
    import hashlib
    import json

    return hashlib.sha1(json.dumps(edit, sort_keys=True, default=str).encode()).hexdigest()[:12]


def snap_to_cuts(src: str, start: float, end: float, words_all: list[dict], edit: dict) -> tuple[float, float, list]:
    """Move AI-chosen cut points onto a hard scene cut right next to them (no one-frame flash of the previous shot),
    never past a word. A trim the user made is left alone. Returns (start, end, which edges moved)."""
    snapped = []
    if "start" not in edit:
        c = next((c for c in reframe.precise_cuts(src, start - 0.05, start + 0.7) if start < c <= start + 0.6), None)
        if c is not None and not any(start <= w["start"] < c - 0.05 for w in words_all):
            start, _ = c, snapped.append("start")
    if "end" not in edit:
        cs = [c for c in reframe.precise_cuts(src, end - 0.7, end + 0.05) if end - 0.6 <= c < end]
        if cs and not any(w["start"] < end and w["end"] > cs[-1] + 0.05 for w in words_all if w["end"] > start):
            end, _ = cs[-1], snapped.append("end")
    return start, end, snapped


def thumbnail_time(clip: dict, duration: float) -> float:
    """Where the thumbnail is taken: the frame ClipForge AI picked when it looked at the clip (pipeline/eyes.py), if
    it falls inside the rendered clip, else a moment near the start."""
    default = min(1.2, duration / 3)
    seen = ((clip.get("analysis") or {}).get("deep") or {}).get("seen") or {}
    try:
        rel = float(seen["thumbnail_t"]) - float(clip.get("start") or 0.0)
    except (KeyError, TypeError, ValueError):
        return default
    speed = float((clip.get("edit") or {}).get("speed") or 1.0) or 1.0
    rel = rel / speed
    return rel if 0.2 <= rel <= max(0.2, duration - 0.2) else default


def render_clip(project: dict, clip: dict, words_all: list[dict], settings: dict, ctx: JobContext,
                out_dir: Path | None = None, blueprint: "blueprint_mod.Blueprint | None" = None,
                source_offset: float = 0.0) -> dict:
    """Render `clip` (with its edit) to a new MP4 in `out_dir` (default: the clip's folder; versions use a
    subfolder). The framing analysis is cached in the clip's folder and shared by all versions.

    With a `blueprint` (Autopilot clips) the render follows that validated plan exactly: its source intervals,
    speed, framing, captions, emphasis, audio and hook. Without one (manual clips) it renders as it always has.
    `source_offset`: where `project`'s source starts in the clip's recording (a live clip renders from a window of
    the stream); kept in render_info so the predictor's trims are in the recording's time."""
    t0 = time.time()
    src = project["source_path"]
    info = project.get("info") or {}
    src_w, src_h = int(project["width"]), int(project["height"])
    src_fps = float(project.get("fps") or 30.0)
    max_fps = float(settings.get("max_fps", 30))
    fps = src_fps if 10 <= src_fps <= max_fps + 0.5 else min(max_fps, 30.0)
    opts = effective_options(settings, project.get("options") or {}, clip.get("edit") or {})
    brain_used = []
    chosen = layout_chosen(project, clip, blueprint)
    if blueprint is not None:
        opts.update(blueprint_mod.render_options(blueprint))
        brain_used = list(blueprint.knowledge)
    elif (project.get("guidance") or {}).get("schema"):
        # A ClipForge project: its guidance was resolved once when it was made (project choice > style > skills >
        # Brain notes > Settings) and frozen, so a retry or re-render reproduces the same choices.
        from ..studio import guidance as guidance_mod

        opts.update(guidance_mod.render_values(project["guidance"]))
        opts.update({key: value for key, value in (clip.get("edit") or {}).items() if value is not None})
        brain_used = guidance_mod.brain_influences(project["guidance"])
    else:
        from ..autopilot import brain, knowledge

        with brain.consultation("render", settings, ref=("clip", clip["id"])) as activity:
            opts, brain_used = knowledge.choose(knowledge.context(clip, project), opts, settings)
            # An explicit edit in the clip/version editor remains the owner's final choice for this render.
            overrides = {key: value for key, value in (clip.get("edit") or {}).items() if value is not None}
            opts.update(overrides)
            brain_used = [{**item, "decisions": {key: value for key, value in item["decisions"].items()
                                                if key not in overrides and key != "pacing"}}
                          for item in brain_used]
            brain_used = [item for item in brain_used if item["decisions"]]
            chosen = chosen or any("layout" in item["decisions"] for item in brain_used)
            if activity is not None:
                activity.use(brain_used, replace=True)
        # Ranking-only notes (for example, standalone moments) select the range rather than a caption style.
        # Preserve their original revision evidence on manual clips as well as on Autopilot blueprints.
        selected = (clip.get("analysis") or {}).get("brain_knowledge") or []
        combined = {}
        for item in selected + brain_used:
            key = (item["knowledge_id"], item["revision"])
            if key not in combined:
                combined[key] = {**item, "decisions": dict(item["decisions"])}
            else:
                combined[key]["decisions"].update(item["decisions"])
        brain_used = list(combined.values())

    duration_src = float(project.get("duration") or 0)
    if blueprint is not None:
        start, end = blueprint.window()  # the plan already placed its cuts (scene cuts included)
        start, end = max(0.0, start), min(duration_src or 1e9, end)
    else:
        start = max(0.0, float(opts.get("start", clip["start"])))
        end = min(duration_src or 1e9, float(opts.get("end", clip["end"])))
    if end - start < 1.0:
        raise ValueError("Clip is shorter than one second; adjust the trim.")
    snapped = []
    if blueprint is None:
        start, end, snapped = snap_to_cuts(src, start, end, words_all, clip.get("edit") or {})

    clip_dir = Path(project["dir"]) / "clips" / clip["id"]
    clip_dir.mkdir(parents=True, exist_ok=True)
    own_file = out_dir is None  # the clip's own render (a version is changed on its own page)
    out_dir = out_dir or clip_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    words = opts.get("caption_words") or [w for w in words_all if w["end"] > start and w["start"] < end]
    within = [(i.start, i.end) for i in blueprint.intervals] if blueprint is not None else None
    silence = opts.get("silence", "off")
    loop_on = bool(opts.get("loop_ending", True))
    # reactions without words (a live clip's window is `source_offset` into the recording the loudness is of)
    loud = heard(project["dir"], words_all, start, end, offset=source_offset) \
        if silence in SILENCE_PRESETS or loop_on else None
    segs = keep_segments(words, start, end, silence, fps, bool(opts.get("remove_fillers")), within,
                         loud if silence in SILENCE_PRESETS else None)
    cleaned = sum(b - a for a, b in segs)  # what silence and filler cleanup kept (the loop seam is counted apart)
    loop = None
    if loop_on:
        # a loop ending: the clip stops just after its last sound and starts just before its first (loops.py),
        # from what is said (the transcript, whatever the captions show), never inside another shot
        said = [w for w in words_all if w["end"] > start and w["start"] < end]
        speed = max(SPEED_RANGE[0], min(SPEED_RANGE[1], float(opts.get("speed", 1.0) or 1.0)))
        segs, loop = loops.seam(segs, said, start, fps, speed, loud, lambda a, b: reframe.precise_cuts(src, a, b))
        if loop is not None:  # a word the seam left out gets no caption
            words = loops.within(words, segs)
    tl = Timeline(segs, float(opts.get("speed", 1.0) or 1.0))
    fillers_cut = sum(1 for w in words if FILLER_WORD.match(w["w"].strip()) and not tl.contains(w["start"] + 0.01))
    if blueprint is not None:  # only words that are heard get captions (whole sentences may be cut out)
        words = [w for w in words if artifact.kept_fraction(max(start, w["start"]), min(end, w["end"]), segs) >= 0.5]
    words_out = _map_words(words, tl, start, end)
    # where pauses and fillers were cut out (punch-ins, caption pages), on the frames that really show the new part
    cuts = moves.jump_cuts(segs, tl.speed, tl.cut_frames(start, fps))

    # ---- framing plan (cached: expensive analysis is skipped on caption-only edits)
    mode = opts.get("tracking", "auto")
    layout = cam_layout(opts, chosen, clip.get("render_info"))
    # the layout without a face cam: the one the plan was written with, else the video's or the Settings one
    usual = next(v for v in (opts.get("layout_fallback"), opts.get("layout"), settings.get("layout"), "fill")
                 if v in config.LAYOUTS)
    edit = clip.get("edit") or {}
    if layout in reframe.SPLIT_LAYOUTS and edit.get("layout") is None and edit.get("tracking") not in (None, "auto"):
        # The owner frames this clip by hand in the editor (Framing) and chose no layout there: one picture,
        # placed where they asked, never a split view that would ignore it. Plans and manual clips alike.
        layout = usual
    plan_key = f"v{PLAN_VERSION}-{start:.3f}-{end:.3f}-{mode}-{fps:.3f}-{float(opts.get('crop_x', 0.5)):.3f}"
    # a face cam the owner set (their own box, one locked for the video, a separate camera recording)
    cam_set = facecam.chosen(Path(project["dir"]), opts) if layout in reframe.SPLIT_LAYOUTS else None
    if layout in reframe.SPLIT_LAYOUTS:
        # These also look for a face cam; "fill" and "fit" plans are what they always were, under their old key.
        plan_key += f"-{layout}" + (f"-cam{facecam.key(cam_set)}" if cam_set else "")
    plan_path = clip_dir / "framing.json"
    cached = read_json(plan_path, {})
    if cached.get("key") == plan_key:
        plan = reframe.Plan.from_json(cached["plan"])
    else:
        ctx.progress(0.02, "Analyzing framing")
        speech = [(max(0.0, w["start"] - start), w["end"] - start) for w in words_all
                  if w["end"] > start and w["start"] < end and not FILLER_WORD.match(w["w"].strip())]
        cam_path = Path(project["dir"]) / CAM_FILE
        plan = reframe.plan(src, start, end, src_w, src_h, mode, fps, ctx, float(opts.get("crop_x", 0.5)),
                            speech=speech if words_all else None, layout=layout,
                            cam_hint=read_json(cam_path, None) if layout in reframe.SPLIT_LAYOUTS else None,
                            cam_set=cam_set)
        write_json(plan_path, {"key": plan_key, "plan": plan.to_json()})
        _remember_cam(cam_path, plan)
    split = plan.info.get("split") if plan.mode == "split" else None
    if layout in reframe.SPLIT_LAYOUTS:
        # What this clip is, now that the picture has been looked at: "auto" with a face cam is a split view, and
        # without a face cam every one of them gets the layout the owner uses for every other clip.
        asked = layout
        layout = ("split" if asked == "auto" else asked) if split else usual
    else:
        asked = layout

    # ---- colour (pipeline/grade.py): phone HDR converted, the clip's own white balance, exposure and contrast
    # corrected and a look added; measured once per clip (cached with its framing) so the picture never flickers
    ctx.progress(0.03, COLOUR_STEP)
    colour = grade.source_colour(src)
    look, look_stats = grade.for_footage(src, [(start, end)], opts, cache=clip_dir / "grade.json",
                                        screen=plan.faces_found == 0, cancelled=ctx.cancelled)
    dw, dh = _decode_size(src_w, src_h)
    # the grain is measured at full size and cleaned at the decoding size (smaller for 4K sources)
    denoise = grade.denoise_for(look_stats, opts, max(dw, dh) / max(src_w, src_h, 1))

    # ---- captions (emphasis: numbers, strong words and the clip's own keywords, at most one every 2.5 s)
    ctx.progress(0.03, CAPTIONS_STEP)
    keywords = {t.lstrip("#").lower() for t in ((clip.get("post") or {}).get("hashtags") or clip.get("hashtags") or [])}
    emphasis = blueprint_mod.emphasis_indices(blueprint, words) if blueprint is not None else \
        emphasis_words(words_out, keywords)
    if opts.get("caption_emphasis"):
        for i in emphasis:
            words_out[i] = {**words_out[i], "em": True}
    hook_text = opts.get("hook") if opts.get("hook") is not None else clip.get("hook", "")
    # where the picture sits: captions "above" it need its top edge (fit keeps the whole frame, centred)
    fit_scale = min(OUTPUT_W / dw, OUTPUT_H / dh)
    picture_top = (OUTPUT_H - dh * fit_scale) / 2 if layout == "fit" else None
    rendered_game = (clip.get("render_info") or {}).get("split_game")
    if (clip.get("edit") or {}).get("split_game") is None and rendered_game in reframe.SPLIT_GAMES and \
            not (blueprint is not None and blueprint.framing.game):
        opts["split_game"] = rendered_game  # the look it was made with, like its layout (cam_layout)
    if split and layout == "pip":
        corner = reframe.pip_corner(split, opts.get("pip_corner"))
        split = {**split, "view": reframe.pip_panels(split, dw, dh, corner, OUTPUT_W, OUTPUT_H)}
    elif split and layout == "game":
        split = {**split, "view": {"game": "game"}}
    elif split:
        # how the two pictures are laid out: the whole picture under the cam unless the zoomed one was asked for
        game = opts.get("split_game") if opts.get("split_game") in reframe.SPLIT_GAMES else reframe.SPLIT_GAMES[0]
        split = {**split, "view": reframe.split_panels(split, dw, dh, game, OUTPUT_W, OUTPUT_H)}
    view = split["view"] if split else {}
    two = view.get("game") in reframe.SPLIT_GAMES   # a split view: the captions sit on the line between them
    ass = captions.build_ass(words_out, {**opts, "picture_top": picture_top,
                                         "picture_seam": view["seam"] / OUTPUT_H if two else None,
                                         "seam_hook_top": view.get("hook") if two else None,
                                         "clear_top": view.get("clear_top"), "page_breaks": [t for t, _ in cuts]},
                             tl.duration, hook_text or "")
    (out_dir / "captions.ass").write_text(ass, encoding="utf-8")
    (out_dir / "captions.srt").write_text(captions.build_srt(words_out, opts.get("caption_style", "clean")),
                                          encoding="utf-8")

    # ---- geometry
    cw_frac, ch_frac = reframe.crop_fraction(src_w, src_h)
    base_w, base_h = cw_frac * dw, ch_frac * dh
    base_zoom = max(1.0, min(2.5, float(opts.get("zoom", 1.0) or 1.0)))
    n_out_frames = int(round(tl.duration * fps))
    # punch-ins on the jump cuts, a change at least every 5 s, a push on rationed stressed words (moves.py)
    punch = moves.punch_strength(src_h) if opts.get("auto_zoom") else 0.0
    zc = moves.punch_curve(words_out, cuts, n_out_frames, fps, punch, emphasis, loop=loop is not None) * base_zoom
    framing_changes = moves.changes(words_out, cuts, tl.duration, loop=loop is not None) if punch else []
    if loop is not None:  # an odd number of changes: the shot size switches where the end runs back into the start
        loop["switch"] = len(framing_changes) % 2 == 1
    pushed = moves.pushes(words_out, emphasis, tl.duration) if punch else []
    # sound effects from the edit: a whoosh with each push, a pop with each key word the captions colour (a style
    # without an emphasis colour, like Minimal, shows no key words, so it gets no pops)
    coloured = opts.get("captions_enabled", True) and bool(captions.STYLE_PRESETS.get(
        opts.get("caption_style", "bold"), captions.STYLE_PRESETS["bold"]).get("emphasis"))
    effects = moves.effect_events(words_out if coloured else [], pushed, tl.duration) \
        if opts.get("sound_effects", True) else []

    frame_bytes = dw * dh * 3
    n_src_frames = plan.n
    # a separate camera recording: decoded alongside, its frame `offset` seconds from the video's
    camera = cam_set if split and cam_set and cam_set.get("kind") == "camera" else None
    cam_cmd, cam_bytes, cam_lead, cam_shape = None, 0, 0, (0, 0)
    if camera:
        cdw, cdh = _decode_size(*camera["size"])
        t_cam = start + float(camera["offset"])
        cam_lead = int(round(max(0.0, -t_cam) * fps))  # frames before the camera started: dark
        cam_shape, cam_bytes = (cdh, cdw), cdw * cdh * 3
        # the camera's own recording: read in its own colours (a phone's HDR converted), with the clip's look
        cam_file = str(Path(project["dir"]) / camera["file"])
        cam_colour = grade.source_colour(cam_file)
        cam_look = grade.Grade(hdr=grade.hdr_kind(cam_colour), max_cll=float(cam_colour.get("max_cll") or 0),
                               look=look.look, strength=look.strength)
        cam_cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t_cam):.3f}",
                   "-i", cam_file, "-t", f"{end - start + 0.5:.3f}", "-map", "0:v:0", "-an", "-sn",
                   "-vf", f"fps={fps},scale={cdw}:{cdh}:flags=bicubic,"
                          f"{grade.rgb_filters(cam_colour, cam_look, '', clip_dir, camera['size'][1])}",
                   "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    dec_cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", src,
               "-t", f"{end - start + 0.5:.3f}", "-map", "0:v:0", "-an", "-sn",
               "-vf", f"fps={fps},scale={dw}:{dh}:flags=bicubic,"
                      f"{grade.rgb_filters(colour, look, denoise, clip_dir, src_h)}",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]

    enc_args, encoder = video_encoder_args(settings)
    fonts = filter_path(config.FONTS_DIR, out_dir)
    # The frames arrive as RGB. Without an explicit matrix FFmpeg converts them to YUV with BT.601 coefficients
    # while every player treats a 1080x1920 file as BT.709, which shifts reds and greens; so the conversion and the
    # tags both say BT.709 (delivery_args).
    vf = f"[0:v]ass=captions.ass:fontsdir={fonts},scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]"
    audio_in: list[str]
    sound = _clean_sound(src, start, end + 0.2, words_all, opts, ctx) if info.get("has_audio", True) else None
    if sound is not None and sound.path is not None:
        # The cleaned sound starts exactly at `start`, so every cut below lines up as it does with the source.
        audio_in = sound.input_args()
    elif info.get("has_audio", True):
        audio_in = ["-ss", f"{start:.3f}", "-t", f"{end - start + 0.2:.3f}", "-i", src]
    else:
        audio_in = ["-f", "lavfi", "-t", f"{end - start + 0.2:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    audio_processing = _measure_audio(audio_in, segs, start, opts, tl.duration, ctx, always=bool(effects))
    if sound is not None:
        audio_processing["clean_sound"] = sound.report
    effects_in: list[str] = []
    fx_path = out_dir / "effects.wav"
    fx_gain = 0.0
    if effects:
        moves.write_wav(moves.effects_track(effects, tl.duration), fx_path)
        effects_in = ["-i", str(fx_path)]
        fx_gain = moves.effects_gain(audio_processing.get("integrated_lufs"),
                                     float(audio_processing.get("normalization_gain_db") or 0.0))
        audio_processing["effects_gain_db"] = round(fx_gain, 2)
    fc = vf + ";" + _audio_filter(segs, start, opts,
                                normalization_gain_db=audio_processing["normalization_gain_db"],
                                effects_label="2:a:0" if effects else None, effects_gain_db=fx_gain)
    tmp_out = out_dir / "render.tmp.mp4"
    enc_cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUTPUT_W}x{OUTPUT_H}", "-framerate", f"{fps}",
               "-i", "pipe:0", *audio_in, *effects_in, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               *enc_args, *delivery_args(fps), "-r", f"{fps}", "-c:a", "aac", "-profile:a", "aac_low",
               "-b:a", AUDIO_BITRATE, "-ac", "2", "-ar", "48000",
               # The timeline already bounds both streams. FFmpeg's -shortest can stop consuming the raw
               # video pipe early when concatenated audio is buffered, dropping frames after a silence cut.
               "-movflags", "+faststart", "-t", f"{tl.duration:.6f}", tmp_out.name]

    log_path = out_dir / "render.log"
    # NVENC encodes on the GPU, so it takes the same lock as transcription and local models: on a 4-8 GB card an
    # encoder session next to Whisper can fail for lack of memory. An x264 encode runs on the CPU and never waits.
    hold_gpu = gpu.manager.heavy("video encode", project.get("name") or f"clip {clip['id']}",
                                 cancelled=ctx.cancelled, on_wait=lambda m: ctx.progress(0.03, m)) \
        if encoder == "h264_nvenc" else nullcontext()
    with hold_gpu, open(log_path, "wb") as logf, MediaWatchdog(ctx.cancelled, max(1800.0, tl.duration * 60)) as watch:
        dec = watch.add(subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=logf, creationflags=NO_WINDOW,
                                         bufsize=frame_bytes, cwd=str(clip_dir)))
        cam_dec = watch.add(subprocess.Popen(cam_cmd, stdout=subprocess.PIPE, stderr=logf, creationflags=NO_WINDOW,
                                             bufsize=cam_bytes, cwd=str(clip_dir))) if cam_cmd else None
        cam_last = np.zeros((*cam_shape, 3), np.uint8) if cam_cmd else None
        enc = watch.add(subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf,
                                         cwd=str(out_dir), creationflags=NO_WINDOW))
        written = 0
        last = None
        try:
            for k in range(n_src_frames):
                watch.check()
                buf = dec.stdout.read(frame_bytes)  # type: ignore[union-attr]
                watch.check()
                if len(buf) == frame_bytes:
                    last = np.frombuffer(buf, np.uint8).reshape(dh, dw, 3)
                elif last is None:
                    raise FFmpegError("Could not decode video frames for this clip.")
                if cam_dec is not None and k >= cam_lead:
                    got = cam_dec.stdout.read(cam_bytes)  # type: ignore[union-attr]
                    if len(got) == cam_bytes:  # past the camera's end its last frame stays
                        cam_last = np.frombuffer(got, np.uint8).reshape(*cam_shape, 3)
                t_src = start + k / fps
                if not tl.contains(t_src) or written >= n_out_frames:
                    continue
                # With speed > 1 some source frames are skipped; at speed 1 every kept frame is written once.
                out_t = tl.to_out(t_src)
                while written < n_out_frames and written <= out_t * fps + 0.5:
                    z = float(zc[min(written, len(zc) - 1)])
                    frame = _compose(last, plan.cx[min(k, plan.n - 1)], plan.cy[min(k, plan.n - 1)], z, dw, dh,
                                     base_w, base_h, layout, fit_scale, split, cam_last)
                    enc.stdin.write(frame.data)  # type: ignore[union-attr]
                    written += 1
                    if written % 15 == 0:
                        if ctx.cancelled():
                            raise Cancelled()
                        ctx.progress(0.05 + 0.9 * written / max(1, n_out_frames), FRAMES_STEP)
            # pad if decoding ended early
            while written < n_out_frames and last is not None:
                watch.check()
                frame = _compose(last, plan.cx[-1], plan.cy[-1], float(zc[-1]), dw, dh, base_w, base_h, layout,
                                 fit_scale, split, cam_last)
                enc.stdin.write(frame.data)  # type: ignore[union-attr]
                written += 1
            enc.stdin.close()  # type: ignore[union-attr]
            rc = enc.wait()
        except (BrokenPipeError, OSError) as exc:
            enc.kill()
            enc.wait()
            raise FFmpegError(f"Encoder stopped unexpectedly: {_tail(log_path)}") from exc
        except BaseException:
            enc.kill()
            enc.wait()
            raise
        finally:
            for proc in (dec, cam_dec):
                if proc is not None:
                    proc.kill()
                    proc.wait()
            fx_path.unlink(missing_ok=True)  # only the encode reads it (and Full Cloud would download it)
    if rc != 0 or not tmp_out.exists():
        raise FFmpegError(f"Encoding failed: {_tail(log_path)}")
    audio_processing["packet_timing"] = audio_timing.require_valid(tmp_out, ctx.cancelled)
    # Versioned names: on Windows a file that the browser is still streaming cannot be replaced.
    stamp = str(int(time.time() * 1000))
    out_path = out_dir / f"clip-{stamp}.mp4"
    os.replace(tmp_out, out_path)
    thumb = out_dir / f"thumb-{stamp}.jpg"
    try:
        thumbnail(out_path, thumbnail_time(clip, tl.duration), thumb, 360, cancel=ctx.cancelled)
    except FFmpegError as exc:
        log.warning("thumbnail failed: %s", exc)
    for old in list(out_dir.glob("clip*.mp4")) + list(out_dir.glob("thumb*.jpg")):
        if old not in (out_path, thumb):
            try:
                old.unlink()
            except OSError:
                pass  # still open somewhere; cleaned up on the next render
    followed = blueprint.summary() if blueprint is not None else None
    if blueprint is not None:
        write_json(out_dir / "blueprint.json", blueprint.to_dict())
    record = artifact.record(out_path, out_dir, tl, words, start, end, opts, encoder, followed)
    # the viral predictor watches the finished file: a score, the hook, the hold curve, reasons and fixes
    # (predictor/; never stops a render)
    from .. import predictor

    prediction = None
    if predictor.enabled(settings):
        ctx.progress(0.98, "Predicting how it will do")
        prediction = predictor.for_render(out_path, record, opts, clip, settings, ctx.cancelled, editable=own_file,
                                          source_offset=source_offset)
    ctx.progress(1.0, "Done")
    return {
        "output_path": str(out_path),
        "thumb_path": str(thumb) if thumb.exists() else "",
        "duration": round(tl.duration, 2),
        "render_info": {"brain_knowledge": brain_used, "mode": plan.mode, "faces": plan.faces_found,
                        "audio_processing": audio_processing,
                        "framing_evidence": dict(plan.info),
                        "cuts": len(plan.cuts), "encoder": encoder,
                        "crop_w": round(cw_frac, 3), "layout": layout,
                        # what was asked for when that differs from what the picture made of it ("auto": a split
                        # view only with a face cam), and which split view it is
                        **({"layout_asked": asked} if asked != layout else {}),
                        # the layout used when no face cam is found (the clip editor's one-picture layout)
                        **({"layout_fallback": usual} if asked in reframe.SPLIT_LAYOUTS else {}),
                        **({"split_game": view["game"]} if two else {}),
                        **({"pip_corner": view["corner"]} if view.get("game") == "pip" else {}),
                        "fps": fps, "segments": len(segs),
                        "removed_s": round((end - start) - cleaned, 2),
                        "fillers_removed": fillers_cut, "speed": tl.speed, "emphasis_words": len(emphasis),
                        "moves": {"punch": punch, "on_cuts": sum(1 for _, c in framing_changes if c),
                                  "eased": sum(1 for _, c in framing_changes if not c), "pushes": len(pushed),
                                  "effects": [e["kind"] for e in effects]},
                        **({"loop": loop} if loop is not None else {}),
                        "colour": {**look.summary(), "denoise": bool(denoise),
                                   "noise": round(float((look_stats or {}).get("noise") or 0), 2)},
                        "render_seconds": round(time.time() - t0, 1), "start": start, "end": end,
                        "snapped_to_cut": snapped, "edit_hash": edit_hash(clip.get("edit") or {}),
                        **({"source_offset": round(float(source_offset), 3)} if source_offset else {}),
                        "artifact": record, **({"prediction": prediction} if prediction else {})},
    }


def _tail(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()[-600:]
    except OSError:
        return ""


def _remember_cam(path: Path, plan: "reframe.Plan") -> None:
    """Keep the face cam this plan found for the video's later clips, so all of them are framed alike and a clip
    in which the face is hidden still gets its split view. Only a cam whose own rectangle was found is kept; one
    found somewhere else replaces it (the streamer changed the layout)."""
    cam, split = plan.info.get("cam") or {}, plan.info.get("split") or {}
    if plan.mode != "split" or cam.get("kind") != "border" or cam.get("from") == "earlier":
        return
    known = read_json(path, None) or {}
    if known.get("locked") or (known.get("box") and reframe._overlap(known["box"], split["cam"]) >= 0.75):
        return  # the owner's own box is never replaced by what is found
    try:
        write_json(path, {"box": split["cam"], "face": [*split["focus"], 0.0, 0.0], "kind": "border",
                          "score": cam.get("score")})
    except OSError:
        log.warning("could not save the face cam's place")  # the next clip looks for it again


def _cam_panel(frame: np.ndarray, split: dict, top_h: int, width: int | None = None) -> np.ndarray:
    """As much of the cam as a panel of this size holds (as wide as the output unless `width` is given), the face a
    little above the middle. `frame` is the video's picture, or the separate camera recording's (the cam's box is
    then in that picture)."""
    width = OUTPUT_W if width is None else width
    dh, dw = frame.shape[:2]
    x0, y0, x1, y1 = (split["cam"][0] * dw, split["cam"][1] * dh, split["cam"][2] * dw, split["cam"][3] * dh)
    shape = width / top_h
    cw = min(x1 - x0, (y1 - y0) * shape)
    ch = cw / shape
    fx, fy = split["focus"][0] * dw, split["focus"][1] * dh
    left = min(x1 - cw, max(x0, fx - cw / 2))
    top = min(y1 - ch, max(y0, fy - 0.42 * ch))
    s = width / cw
    m = np.float32([[s, 0, -left * s], [0, s, -top * s]])
    return cv2.warpAffine(frame, m, (width, top_h), borderMode=cv2.BORDER_REPLICATE,
                          flags=cv2.INTER_CUBIC if s > 1.5 else cv2.INTER_LINEAR if s > 0.7 else cv2.INTER_AREA)


def _split_whole(frame: np.ndarray, z: float, dw: int, dh: int, split: dict, view: dict,
                 cam: np.ndarray | None = None) -> np.ndarray:
    """Split view that keeps the whole picture: the cam, a strip for the captions, then the picture as wide as the
    output, over the same blurred fill as the "fit" layout. A zoom moves in on the picture's middle and leaves its
    place and the cam as they are."""
    small = cv2.resize(frame, (54, 96), interpolation=cv2.INTER_AREA)
    out = cv2.resize(cv2.GaussianBlur(small, (0, 0), 3), (OUTPUT_W, OUTPUT_H), interpolation=cv2.INTER_LINEAR)
    out = cv2.convertScaleAbs(out, alpha=0.45)
    cam_y, top_h = view["cam"]
    out[cam_y:cam_y + top_h] = _cam_panel(frame if cam is None else cam, split, top_h)
    px, py, pw, ph = view["picture"]
    s = pw / dw * z
    m = np.float32([[s, 0, pw / 2 - dw / 2 * s], [0, s, ph / 2 - dh / 2 * s]])
    out[py:py + ph, px:px + pw] = cv2.warpAffine(frame, m, (pw, ph), borderMode=cv2.BORDER_REPLICATE,
                                                 flags=cv2.INTER_AREA if s < 0.7 else cv2.INTER_LINEAR)
    return out


def _split_view(frame: np.ndarray, cxn: float, z: float, dw: int, dh: int, split: dict,
                cam: np.ndarray | None = None) -> np.ndarray:
    """The face cam on top and the rest of the picture below (reframe.split_layout, split_panels). A zoom moves in
    on the lower picture only: the cam stays as it is, so the face never jumps."""
    view = split.get("view") or reframe.split_panels(split, dw, dh, "zoom", OUTPUT_W, OUTPUT_H)
    if view["game"] == "whole":
        return _split_whole(frame, z, dw, dh, split, view, cam)
    top_h = view["cam"][1]
    low_h = OUTPUT_H - top_h
    out = np.empty((OUTPUT_H, OUTPUT_W, 3), np.uint8)
    out[:top_h] = _cam_panel(frame if cam is None else cam, split, top_h)
    # below: the picture's full height (less when zoomed in), as wide as the panel's shape
    shape = OUTPUT_W / low_h
    ch = dh * float(split["content"][3]) / z
    cw = ch * shape
    if cw > dw:
        cw, ch = float(dw), dw / shape
    cx = min(dw - cw / 2, max(cw / 2, cxn * dw))
    s = OUTPUT_W / cw
    m = np.float32([[s, 0, -(cx - cw / 2) * s], [0, s, -(dh / 2 - ch / 2) * s]])
    out[top_h:] = cv2.warpAffine(frame, m, (OUTPUT_W, low_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    line = max(2, OUTPUT_H // 480)   # a thin dark line, so two pictures of the same colour do not run together
    out[top_h - line // 2:top_h + line - line // 2] = (12, 12, 12)
    return out


def _pip_inset(out: np.ndarray, frame: np.ndarray, split: dict, view: dict) -> np.ndarray:
    """The face cam in its box at the top of a Picture-in-picture clip, inside a thin light frame."""
    left, top, w, h = view["inset"]
    b = int(view.get("border") or 0)
    if b:
        out[max(0, top - b):top + h + b, max(0, left - b):left + w + b] = (236, 236, 236)
    out[top:top + h, left:left + w] = _cam_panel(frame, split, h, w)
    return out


def _compose(frame: np.ndarray, cxn: float, cyn: float, z: float, dw: int, dh: int, base_w: float,
             base_h: float, layout: str, fit_scale: float, split: dict | None = None,
             cam: np.ndarray | None = None) -> np.ndarray:
    if split and layout in ("pip", "game"):
        # the gameplay fills the frame, cropped where the face cam is left out of it (or where the owner put it);
        # Picture-in-picture then puts the cam in its box at the top
        cxn, cyn = float(split.get("fill_x", split["content"][0])), 0.5
        if layout == "pip":
            out = _compose(frame, cxn, cyn, z, dw, dh, base_w, base_h, "fill", fit_scale)
            return _pip_inset(np.ascontiguousarray(out), frame if cam is None else cam, split, split["view"])
    elif split:
        return _split_view(frame, cxn, z, dw, dh, split, cam)
    if layout == "fit":
        # whole frame (optionally zoomed) over a blurred, darkened fill
        vw, vh = dw / z, dh / z
        cx = min(dw - vw / 2, max(vw / 2, cxn * dw)) if z > 1.001 else dw / 2
        cy = min(dh - vh / 2, max(vh / 2, cyn * dh)) if z > 1.001 else dh / 2
        s = fit_scale * z
        fg_w, fg_h = dw * fit_scale, dh * fit_scale
        ox, oy = (OUTPUT_W - fg_w) / 2, (OUTPUT_H - fg_h) / 2
        small = cv2.resize(frame, (54, 96), interpolation=cv2.INTER_AREA)
        bg = cv2.GaussianBlur(small, (0, 0), 3)
        bg = cv2.resize(bg, (OUTPUT_W, OUTPUT_H), interpolation=cv2.INTER_LINEAR)
        bg = cv2.convertScaleAbs(bg, alpha=0.45)
        m = np.float32([[s, 0, ox + fg_w / 2 - cx * s], [0, s, oy + fg_h / 2 - cy * s]])
        x0, y0 = int(round(ox)), int(round(oy))
        x1, y1 = int(round(ox + fg_w)), int(round(oy + fg_h))
        fg = cv2.warpAffine(frame, m, (OUTPUT_W, OUTPUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        bg[y0:y1, x0:x1] = fg[y0:y1, x0:x1]
        return bg
    cw, ch = base_w / z, base_h / z
    cx = min(dw - cw / 2, max(cw / 2, cxn * dw))
    cy = min(dh - ch / 2, max(ch / 2, cyn * dh))
    s = OUTPUT_W / cw
    m = np.float32([[s, 0, -(cx - cw / 2) * s], [0, s, -(cy - ch / 2) * s]])
    return cv2.warpAffine(frame, m, (OUTPUT_W, OUTPUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
