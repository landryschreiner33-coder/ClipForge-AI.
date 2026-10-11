"""Render one clip: trim -> silence cleanup -> 9:16 reframe -> zoom -> captions -> H.264/AAC MP4.

Video frames flow ffmpeg (decode) -> numpy/OpenCV (sub-pixel crop, zoom,
layout) -> ffmpeg (burn ASS captions + encode).  Audio is cut with the same
keep-segments so picture and sound stay in sync.
"""
from __future__ import annotations

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
from . import artifact, captions, reframe
from . import blueprint as blueprint_mod
from .common import Cancelled, JobContext, log, read_json, write_json
from .ffmpeg_utils import (NO_WINDOW, FFmpegError, MediaWatchdog, ffmpeg_bin, filter_path, thumbnail,
                           video_encoder_args)
from .text_utils import ends_sentence

SILENCE_PRESETS = {"light": (0.8, 0.22), "aggressive": (0.35, 0.08)}  # (min gap removed, padding kept)
FILLER_WORD = re.compile(r"^(um+|uh+|erm+|hmm+|mm+|ah+)[,.!?]*$", re.I)
SPEED_RANGE = (0.8, 1.25)
PLAN_VERSION = 2  # bump when the framing analysis changes, so cached plans are recomputed
CAPTIONS_STEP = "Writing captions"  # progress messages that tell the office which part of the render runs
FRAMES_STEP = "Rendering"


# ------------------------------------------------------------ timeline
def keep_segments(words: list[dict], start: float, end: float, mode: str, fps: float,
                  drop_fillers: bool = False, within: list[tuple[float, float]] | None = None
                  ) -> list[tuple[float, float]]:
    """Source-time ranges to keep; long pauses between words are removed. With `drop_fillers`, an "um" or "uh"
    counts as part of the pause around it, so it goes too when that pause is long enough to cut. `within` (a
    blueprint's source intervals) keeps only what lies inside them, before everything is put on the frame grid."""
    segs: list[tuple[float, float]]
    if mode not in SILENCE_PRESETS or not words:
        segs = [(start, end)]
    else:
        min_gap, pad = SILENCE_PRESETS[mode]
        cuts = []
        ws = [w for w in words if w["end"] > start and w["start"] < end
              and not (drop_fillers and FILLER_WORD.match(w["w"].strip()))]
        prev_end = start
        for w in ws:
            if w["start"] - prev_end > min_gap:
                a = prev_end + pad if prev_end > start else start
                b = w["start"] - pad
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


# ------------------------------------------------------------ zoom
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


def zoom_curve(words_out: list[dict], n: int, fps: float, strength: float,
               emphasis: set[int] | None = None) -> np.ndarray:
    """Subtle, eased zoom. With `emphasis`, the camera pushes in on the sentences that carry an emphasized word and
    eases back out for the rest; otherwise it alternates between sentences."""
    z = np.ones(n)
    if strength <= 0 or n < 2:
        return z
    boundaries = [0.0]
    for i, w in enumerate(words_out[:-1]):
        if ends_sentence(w["w"]) and words_out[i + 1]["start"] - boundaries[-1] >= 2.5:
            boundaries.append(words_out[i + 1]["start"])
    dur = n / fps
    # never hold one zoom level for too long
    filled = [boundaries[0]]
    for b in boundaries[1:] + [dur]:
        while b - filled[-1] > 7.0:
            filled.append(filled[-1] + 5.0)
        if b < dur:
            filled.append(b)
    levels = [1.0 + strength if k % 2 == 1 else 1.0 for k in range(len(filled))]
    if emphasis:
        spans = list(zip(filled, filled[1:] + [dur]))
        marks = [any(a <= words_out[j]["start"] < b for j in emphasis) for a, b in spans]
        if 0 < sum(marks) < len(marks):
            levels = [1.0 + strength if m else 1.0 for m in marks]
    for b, level in zip(filled, levels):
        z[int(b * fps):] = level
    win = max(3, int(0.35 * fps))
    kernel = np.hanning(win + 2)[1:-1]
    kernel /= kernel.sum()
    pad = win // 2
    zp = np.pad(z, (pad, win - 1 - pad), mode="edge")
    return np.convolve(zp, kernel, mode="valid")[:n]


# ------------------------------------------------------------ helpers
def _decode_size(w: int, h: int) -> tuple[int, int]:
    s = min(1.0, 1920 / max(1, h), 3840 / max(1, w))
    dw, dh = int(w * s) // 2 * 2, int(h * s) // 2 * 2
    return max(2, dw), max(2, dh)


def _audio_filter(segs: list[tuple[float, float]], start: float, opts: dict) -> str:
    rel = [(a - start, b - start) for a, b in segs]
    parts = []
    fade = 0.01
    if len(rel) == 1:
        a, b = rel[0]
        parts.append(f"[1:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS[ac]")
    else:
        labels = "".join(f"[s{i}]" for i in range(len(rel)))
        parts.append(f"[1:a]asplit={len(rel)}{labels}")
        for i, (a, b) in enumerate(rel):
            d = b - a
            parts.append(f"[s{i}]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0.0, d - fade):.4f}:d={fade}[c{i}]")
        parts.append("".join(f"[c{i}]" for i in range(len(rel))) + f"concat=n={len(rel)}:v=0:a=1[ac]")
    chain = "[ac]"
    post = []
    speed = float(opts.get("speed", 1.0) or 1.0)
    if abs(speed - 1.0) > 0.001:
        post.append(f"atempo={max(SPEED_RANGE[0], min(SPEED_RANGE[1], speed)):.4f}")  # faster, same pitch
    if opts.get("normalize_audio", True):
        post.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    gain = float(opts.get("gain_db", 0) or 0)
    if abs(gain) > 0.01:
        post.append(f"volume={gain:.2f}dB")
    post.append("aresample=48000")
    parts.append(chain + ",".join(post) + "[a]")
    return ";".join(parts)


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
            "hook_overlay", "hook_seconds", "normalize_audio", "remove_fillers", "caption_emphasis"]
    opts = {k: settings.get(k) for k in keys}
    opts.update({k: v for k, v in (project_opts or {}).items() if k in keys and v is not None})
    opts.update({k: v for k, v in (edit or {}).items() if v is not None})
    return opts


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


def render_clip(project: dict, clip: dict, words_all: list[dict], settings: dict, ctx: JobContext,
                out_dir: Path | None = None, blueprint: "blueprint_mod.Blueprint | None" = None) -> dict:
    """Render `clip` (with its edit) to a new MP4 in `out_dir` (default: the clip's folder; versions use a
    subfolder). The framing analysis is cached in the clip's folder and shared by all versions.

    With a `blueprint` (Autopilot clips) the render follows that validated plan exactly: its source intervals,
    speed, framing, captions, emphasis, audio and hook. Without one (manual clips) it renders as it always has."""
    t0 = time.time()
    src = project["source_path"]
    info = project.get("info") or {}
    src_w, src_h = int(project["width"]), int(project["height"])
    src_fps = float(project.get("fps") or 30.0)
    max_fps = float(settings.get("max_fps", 30))
    fps = src_fps if 10 <= src_fps <= max_fps + 0.5 else min(max_fps, 30.0)
    opts = effective_options(settings, project.get("options") or {}, clip.get("edit") or {})
    if blueprint is not None:
        opts.update(blueprint_mod.render_options(blueprint))

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
    out_dir = out_dir or clip_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    words = opts.get("caption_words") or [w for w in words_all if w["end"] > start and w["start"] < end]
    within = [(i.start, i.end) for i in blueprint.intervals] if blueprint is not None else None
    segs = keep_segments(words, start, end, opts.get("silence", "off"), fps, bool(opts.get("remove_fillers")), within)
    tl = Timeline(segs, float(opts.get("speed", 1.0) or 1.0))
    fillers_cut = sum(1 for w in words if FILLER_WORD.match(w["w"].strip()) and not tl.contains(w["start"] + 0.01))
    if blueprint is not None:  # only words that are heard get captions (whole sentences may be cut out)
        words = [w for w in words if artifact.kept_fraction(max(start, w["start"]), min(end, w["end"]), segs) >= 0.5]
    words_out = _map_words(words, tl, start, end)

    # ---- framing plan (cached: expensive analysis is skipped on caption-only edits)
    mode = opts.get("tracking", "auto")
    plan_key = f"v{PLAN_VERSION}-{start:.3f}-{end:.3f}-{mode}-{fps:.3f}-{float(opts.get('crop_x', 0.5)):.3f}"
    plan_path = clip_dir / "framing.json"
    cached = read_json(plan_path, {})
    if cached.get("key") == plan_key:
        plan = reframe.Plan.from_json(cached["plan"])
    else:
        ctx.progress(0.02, "Analyzing framing")
        speech = [(max(0.0, w["start"] - start), w["end"] - start) for w in words_all
                  if w["end"] > start and w["start"] < end and not FILLER_WORD.match(w["w"].strip())]
        plan = reframe.plan(src, start, end, src_w, src_h, mode, fps, ctx, float(opts.get("crop_x", 0.5)),
                            speech=speech if words_all else None)
        write_json(plan_path, {"key": plan_key, "plan": plan.to_json()})

    # ---- captions (emphasis: numbers, strong words and the clip's own keywords, at most one every 2.5 s)
    ctx.progress(0.03, CAPTIONS_STEP)
    keywords = {t.lstrip("#").lower() for t in ((clip.get("post") or {}).get("hashtags") or clip.get("hashtags") or [])}
    emphasis = blueprint_mod.emphasis_indices(blueprint, words) if blueprint is not None else \
        emphasis_words(words_out, keywords)
    if opts.get("caption_emphasis"):
        for i in emphasis:
            words_out[i] = {**words_out[i], "em": True}
    hook_text = opts.get("hook") if opts.get("hook") is not None else clip.get("hook", "")
    ass = captions.build_ass(words_out, opts, tl.duration, hook_text or "")
    (out_dir / "captions.ass").write_text(ass, encoding="utf-8")
    (out_dir / "captions.srt").write_text(captions.build_srt(words_out, opts.get("caption_style", "clean")),
                                          encoding="utf-8")

    # ---- geometry
    dw, dh = _decode_size(src_w, src_h)
    cw_frac, ch_frac = reframe.crop_fraction(src_w, src_h)
    base_w, base_h = cw_frac * dw, ch_frac * dh
    base_zoom = max(1.0, min(2.5, float(opts.get("zoom", 1.0) or 1.0)))
    n_out_frames = int(round(tl.duration * fps))
    zc = zoom_curve(words_out, n_out_frames, fps, 0.07 if opts.get("auto_zoom") else 0.0, emphasis) * base_zoom
    layout = opts.get("layout", "fill")
    fit_scale = min(OUTPUT_W / dw, OUTPUT_H / dh)

    frame_bytes = dw * dh * 3
    n_src_frames = plan.n
    dec_cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", src,
               "-t", f"{end - start + 0.5:.3f}", "-map", "0:v:0", "-an", "-sn",
               "-vf", f"fps={fps},scale={dw}:{dh}:flags=bicubic", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]

    enc_args, encoder = video_encoder_args(settings)
    fonts = filter_path(config.FONTS_DIR, out_dir)
    vf = f"[0:v]ass=captions.ass:fontsdir={fonts},format=yuv420p[v]"
    audio_in: list[str]
    if info.get("has_audio", True):
        audio_in = ["-ss", f"{start:.3f}", "-t", f"{end - start + 0.2:.3f}", "-i", src]
    else:
        audio_in = ["-f", "lavfi", "-t", f"{end - start + 0.2:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    fc = vf + ";" + _audio_filter(segs, start, opts)
    tmp_out = out_dir / "render.tmp.mp4"
    enc_cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUTPUT_W}x{OUTPUT_H}", "-framerate", f"{fps}",
               "-i", "pipe:0", *audio_in, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
               *enc_args, "-r", f"{fps}", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
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
                                         bufsize=frame_bytes))
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
                t_src = start + k / fps
                if not tl.contains(t_src) or written >= n_out_frames:
                    continue
                # With speed > 1 some source frames are skipped; at speed 1 every kept frame is written once.
                out_t = tl.to_out(t_src)
                while written < n_out_frames and written <= out_t * fps + 0.5:
                    z = float(zc[min(written, len(zc) - 1)])
                    frame = _compose(last, plan.cx[min(k, plan.n - 1)], plan.cy[min(k, plan.n - 1)], z, dw, dh,
                                     base_w, base_h, layout, fit_scale)
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
                                 fit_scale)
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
            dec.kill()
            dec.wait()
    if rc != 0 or not tmp_out.exists():
        raise FFmpegError(f"Encoding failed: {_tail(log_path)}")
    # Versioned names: on Windows a file that the browser is still streaming cannot be replaced.
    stamp = str(int(time.time() * 1000))
    out_path = out_dir / f"clip-{stamp}.mp4"
    os.replace(tmp_out, out_path)
    thumb = out_dir / f"thumb-{stamp}.jpg"
    try:
        thumbnail(out_path, min(1.2, tl.duration / 3), thumb, 360, cancel=ctx.cancelled)
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
    ctx.progress(1.0, "Done")
    return {
        "output_path": str(out_path),
        "thumb_path": str(thumb) if thumb.exists() else "",
        "duration": round(tl.duration, 2),
        "render_info": {"mode": plan.mode, "faces": plan.faces_found, "cuts": len(plan.cuts), "encoder": encoder,
                        "crop_w": round(cw_frac, 3), "layout": layout,
                        "fps": fps, "segments": len(segs),
                        "removed_s": round((end - start) - sum(b - a for a, b in segs), 2),
                        "fillers_removed": fillers_cut, "speed": tl.speed, "emphasis_words": len(emphasis),
                        "render_seconds": round(time.time() - t0, 1), "start": start, "end": end,
                        "snapped_to_cut": snapped, "edit_hash": edit_hash(clip.get("edit") or {}),
                        "artifact": record},
    }


def _tail(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()[-600:]
    except OSError:
        return ""


def _compose(frame: np.ndarray, cxn: float, cyn: float, z: float, dw: int, dh: int, base_w: float,
             base_h: float, layout: str, fit_scale: float) -> np.ndarray:
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
