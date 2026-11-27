"""Final quality gate, media part: independent checks of the exact file that would be published.

Nothing here trusts the renderer's own account of what it made. The file is hashed, probed and decoded in full (a
truncated MP4 with its index at the front still reports its whole length, so only a full decode shows the damage),
and one pass through ffmpeg's detectors finds black, frozen and silent stretches. The results are judged in context:
a still picture over speech (a podcast with a cover image) is a warning, a still picture over silence is a failure.

The same pass measures the sound's loudness and true peak (``ebur128``, as the renderers do: loudness.py) and keeps
two small frames a second, from which the picture's levels are judged against EBU R103 (added 2026-11-27, batch 5c).
These are warnings only: platforms publish no loudness target, and a level a little outside the broadcast range is
clipped by the player, not lost.

Every check says what kind it is:

* deterministic  measured on the file (hash, streams, dimensions, duration, decode errors, caption timing)
* heuristic      a threshold on a measurement or an estimate from the transcript analysis; it can be wrong, so its
                 results are warnings unless the problem is unmistakable, and none of them proves the clip is good

A report with any failed check blocks scheduling and publishing; warnings are shown with the post for review.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from . import artifact, audio_timing, grade, loudness
from .common import Cancelled, read_json
from .ffmpeg_utils import NO_WINDOW, FFmpegError, ffmpeg_bin, probe

GATE_VERSION = 4             # 4: loudness, true peak, picture levels and colour tags (2026-11-27)
PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skipped"
DETERMINISTIC, HEURISTIC = "deterministic", "heuristic"
MIN_SECONDS = 1.0
SHORTS_MAX_SECONDS = 180.0
# detector settings: black = darker than 10% for 0.5 s; frozen = no change for 2 s; silent = below -50 dB for 1 s
BLACK_FILTER = "blackdetect=d=0.5:pix_th=0.10"
FREEZE_FILTER = "freezedetect=n=-60dB:d=2"
SILENCE_FILTER = "silencedetect=noise=-50dB:d=1"
# picture levels (EBU R103, measured on 8-bit codes after a low-pass: here a quarter-size area average)
LEVEL_FPS = 2                # frames a second kept for the levels
LEVEL_SCALE = 4              # ... at a quarter of the width and height
LUMA_SAFE = (14, 241)        # -1% to 103% of the 16-235 range (EBU R103's luma limits, Telestream's defaults)
RGB_SAFE = (-0.05, 1.05)     # -5% to 105% for each of R, G and B
LEVEL_AREA = 0.01            # ... a frame is outside when more than 1% of it is
WRONG_RANGE = 0.05           # over 5% of the picture under 16 or over 235 in most frames: full-range video
LEVEL_MAX_FRAMES = 600       # ... fewer a second for a long file (a one-hour master: one every 6 s)
# checks that only inform (never hold a clip): listed after the others, so a short list of warnings shows those first
LAST_CHECKS = ("levels", "colour_tags", "loudness")
LEVEL_MATRIX = {"bt709": (0.2126, 0.0722), "bt601": (0.299, 0.114), "bt2020": (0.2627, 0.0593)}  # Kr, Kb
_DETECT = re.compile(r"(black_start|black_end|freeze_start|freeze_end|silence_start|silence_end):\s*([-\d.]+)")
_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def check(name: str, label: str, kind: str, status: str, detail: str = "", **values: object) -> dict:
    return {"name": name, "label": label, "kind": kind, "status": status, "detail": detail,
            **({"values": values} if values else {})}


# ------------------------------------------------------------------ one decode pass with the detectors
@dataclass
class Scan:
    frames: int = 0
    decoded_s: float = 0.0
    returncode: int = 0
    errors: list[str] = field(default_factory=list)
    black: list[tuple[float, float]] = field(default_factory=list)
    frozen: list[tuple[float, float]] = field(default_factory=list)
    silent: list[tuple[float, float]] = field(default_factory=list)
    loudness: dict | None = None      # {lufs, lra, tp} of the whole sound (loudness.parse), None when not measured
    levels: list[dict] = field(default_factory=list)  # per kept frame: t, luma_out, rgb_out, strict_out


def _intervals(events: list[tuple[str, float]], start: str, end: str, until: float) -> list[tuple[float, float]]:
    out, open_at = [], None
    for key, t in events:
        if key == start:
            open_at = t
        elif key == end and open_at is not None:
            out.append((open_at, t))
            open_at = None
    if open_at is not None:  # still black/frozen/silent when the file ended
        out.append((open_at, max(open_at, until)))
    return out


def scan(path: str | Path, has_audio: bool, timeout: float = 600.0,
         cancelled: Callable[[], bool] | None = None, size: tuple[int, int] | None = None,
         matrix: str = "bt709", seconds: float = 0.0) -> Scan:
    """Decode every frame and sample once, with the black, freeze and silence detectors, the loudness measurement,
    and (when `size`, the picture's width and height, is given) small frames for the picture levels, read with the
    file's `matrix` (LEVEL_MATRIX), LEVEL_FPS a second or, when the file's `seconds` would give more than
    LEVEL_MAX_FRAMES, that many spread over it."""
    graph = f"[0:v:0]{BLACK_FILTER},{FREEZE_FILTER}"
    small = None
    rate = min(float(LEVEL_FPS), LEVEL_MAX_FRAMES / seconds) if seconds > 0 else float(LEVEL_FPS)
    if size and size[0] > 0 and size[1] > 0:
        small = (max(2, round(size[0] / LEVEL_SCALE)), max(2, round(size[1] / LEVEL_SCALE)))
        graph += (f",split[v1][v2];[v2]fps={rate:.6g},scale={small[0]}:{small[1]}:flags=area,"
                  "format=yuv444p[v3]")
    else:
        graph += "[v1]"
    # the sound in a graph of its own: a complex graph is rebuilt (and ebur128 starts again) when the picture's size
    # or format changes part-way through a file
    sound = ["-map", "0:a:0", "-af", f"{SILENCE_FILTER},{loudness.FILTER}"] if has_audio else []
    levels: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="clipforge-scan-") as tmp:
        progress_file = Path(tmp) / "progress.txt"
        # the detectors' output first: the progress counts its frames, every one of them (the decode check); the
        # small frames come through a pipe, measured as they arrive, so nothing large is written to the disk
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "level+info",
               "-progress", str(progress_file), "-i", str(path), "-filter_complex", graph, "-map", "[v1]", *sound,
               "-f", "null", "-"] + (["-map", "[v3]", "-f", "rawvideo", "pipe:1"] if small else [])
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if small else subprocess.DEVNULL, stderr=err,
                                    stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            reader = None
            if small:
                reader = threading.Thread(target=_read_levels, args=(proc.stdout, small, matrix, rate, levels),
                                          daemon=True)
                reader.start()
            try:
                deadline = time.monotonic() + timeout
                while proc.poll() is None:
                    if (cancelled and cancelled()) or time.monotonic() > deadline:
                        proc.kill()
                        proc.wait()
                        if cancelled and cancelled():
                            raise Cancelled()
                        raise FFmpegError("Decoding the clip took too long")
                    time.sleep(0.1)
            finally:
                if reader is not None:
                    reader.join(timeout=30)
                    proc.stdout.close()
            err.seek(0)
            text = err.read().decode("utf-8", "replace")
        try:
            progress = progress_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            progress = []
    log = text.splitlines()
    res = Scan(returncode=proc.returncode, levels=levels)
    for line in progress:
        key, _, value = line.partition("=")
        try:
            if key == "frame":
                res.frames = int(value)
            elif key == "out_time_us" and value.strip().lstrip("-").isdigit():
                res.decoded_s = max(0.0, int(value) / 1e6)
        except ValueError:
            continue
    events: list[tuple[str, float]] = []
    for line in log:
        if "[error]" in line or "[fatal]" in line:
            res.errors.append(re.sub(r"^(\[[^\]]*\]\s*)+", "", line).strip()[:200])  # drop "[h264 @ 0x..] [error]"
        for key, value in _DETECT.findall(line):
            events.append((key, float(value)))
    res.black = _intervals(events, "black_start", "black_end", res.decoded_s)
    res.frozen = _intervals(events, "freeze_start", "freeze_end", res.decoded_s)
    res.silent = _intervals(events, "silence_start", "silence_end", res.decoded_s)
    if has_audio:
        try:
            res.loudness = loudness.parse(text)
        except ValueError:
            res.loudness = None
    return res


def level_matrix(tags: dict) -> str:
    """The matrix a player reads the file's colours with (grade.input_matrix, as the renderers read files): its tag,
    or for an untagged file BT.709 from 720 lines up and BT.601 under that."""
    m = grade.input_matrix(tags, int(tags.get("height") or 0))
    return m if m in LEVEL_MATRIX else "bt709"


def _read_levels(stream, size: tuple[int, int], matrix: str, rate: float, out: list[dict]) -> None:
    """Reads the small frames from FFmpeg's pipe until it closes, measuring each (`_frame_levels`). It always reads
    to the end, even when a measurement fails, so FFmpeg never waits on a full pipe."""
    w, h = size
    frame = w * h * 3
    i, broken = 0, False
    while True:
        try:
            buf = stream.read(frame)
        except (OSError, ValueError):
            return
        if len(buf) < frame:
            return
        if not broken:
            try:
                out.append(_frame_levels(np.frombuffer(buf, np.uint8).reshape(3, h, w), i / rate, matrix))
            except Exception:  # noqa: BLE001 - no levels (the check skips) rather than a stuck decode
                out.clear()
                broken = True
        i += 1


def _frame_levels(data: np.ndarray, t: float, matrix: str) -> dict:
    """One frame's levels: the share of the picture outside the luma limits (LUMA_SAFE), with any of R, G, B outside
    RGB_SAFE (read with the file's matrix), and under 16 or over 235 (strict, for full-range video in a
    limited-range file)."""
    kr, kb = LEVEL_MATRIX.get(matrix, LEVEL_MATRIX["bt709"])
    kg = 1.0 - kr - kb
    y = data[0].astype(np.float32)
    pb = (data[1].astype(np.float32) - 128.0) / 224.0
    pr = (data[2].astype(np.float32) - 128.0) / 224.0
    yn = (y - 16.0) / 219.0
    r = yn + 2.0 * (1.0 - kr) * pr
    b = yn + 2.0 * (1.0 - kb) * pb
    g = (yn - kr * r - kb * b) / kg
    outside = np.zeros(y.shape, bool)
    for c in (r, g, b):
        outside |= (c < RGB_SAFE[0]) | (c > RGB_SAFE[1])
    return {"t": round(t, 2), "luma_out": float(((y < LUMA_SAFE[0]) | (y > LUMA_SAFE[1])).mean()),
            "rgb_out": float(outside.mean()), "strict_out": float(((y < 16) | (y > 235)).mean()),
            "y_min": int(data[0].min()), "y_max": int(data[0].max())}


def _total(iv: list[tuple[float, float]]) -> float:
    return sum(max(0.0, b - a) for a, b in iv)


def _fmt(iv: list[tuple[float, float]], limit: int = 3) -> str:
    return ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in iv[:limit]) + (" ..." if len(iv) > limit else "")


# ------------------------------------------------------------------ captions and transcript
def srt_cues(path: str | Path) -> list[tuple[float, float, str]] | None:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        m = next((_SRT_TIME.search(line) for line in lines if "-->" in line), None)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = " ".join(line for line in lines if "-->" not in line and not line.strip().isdigit()).strip()
        cues.append((a, b, body))
    return cues


# ------------------------------------------------------------------ the checks
def media_checks(path: str | Path, expected: dict, cancelled: Callable[[], bool] | None = None) -> list[dict]:
    """Every technical check of one file. `expected`: duration, has_audio, sha256 (from the artifact record, when
    known), transcript (the final transcript dict), edl (the EDL dict), srt (caption file path)."""
    path = Path(path)
    out: list[dict] = []
    if not path.is_file() or path.stat().st_size == 0:
        return [check("file", "Video file", DETERMINISTIC, FAIL, "The rendered file is missing or empty.",
                      path=str(path))]
    sha = artifact.sha256_file(path)
    if expected.get("sha256"):
        same = sha == expected["sha256"]
        out.append(check("hash", "Same file as rendered", DETERMINISTIC, PASS if same else FAIL,
                         "" if same else "The file changed after it was rendered.", sha256=sha))
    else:
        out.append(check("hash", "Same file as rendered", DETERMINISTIC, SKIP,
                         "No render record to compare with (rendered before records existed).", sha256=sha))
    try:
        info = probe(path)
    except FFmpegError as exc:
        return [*out, check("streams", "Streams", DETERMINISTIC, FAIL, f"The file cannot be read: {exc}")]
    duration = float(info["duration"] or 0)
    want_audio = bool(expected.get("has_audio", True))
    codecs_ok = info["video_codec"] == "h264" and (info["audio_codec"] == "aac" or not info["has_audio"])
    out.append(check("codecs", "H.264 video and AAC audio", DETERMINISTIC, PASS if codecs_ok else WARN,
                     "" if codecs_ok else f"Unexpected codecs: {info['video_codec']}/{info['audio_codec'] or '-'}",
                     video=info["video_codec"], audio=info["audio_codec"]))
    if want_audio and not info["has_audio"]:
        out.append(check("audio_stream", "Audio track", DETERMINISTIC, FAIL, "The clip has no audio track."))
    else:
        out.append(check("audio_stream", "Audio track", DETERMINISTIC, PASS))
    out.append(_av_timing(info))
    out.append(_audio_packet_timing(path, cancelled))
    dims_ok = (info["width"], info["height"]) == (config.OUTPUT_W, config.OUTPUT_H)
    out.append(check("dimensions", f"{config.OUTPUT_W}x{config.OUTPUT_H} vertical", DETERMINISTIC,
                     PASS if dims_ok else FAIL, "" if dims_ok else f"The file is {info['width']}x{info['height']}.",
                     width=info["width"], height=info["height"]))
    exp_d = expected.get("duration")
    if duration < MIN_SECONDS:
        out.append(check("duration", "Duration", DETERMINISTIC, FAIL, f"Only {duration:.1f} s long.",
                         seconds=duration))
    elif exp_d and abs(duration - float(exp_d)) > max(0.3, 0.02 * float(exp_d)):
        out.append(check("duration", "Duration", DETERMINISTIC, FAIL,
                         f"{duration:.1f} s instead of the {float(exp_d):.1f} s that were rendered.", seconds=duration))
    elif duration > SHORTS_MAX_SECONDS:
        out.append(check("duration", "Duration", DETERMINISTIC, WARN,
                         f"{duration:.0f} s: longer than YouTube Shorts allow ({SHORTS_MAX_SECONDS:.0f} s).",
                         seconds=duration))
    else:
        out.append(check("duration", "Duration", DETERMINISTIC, PASS, f"{duration:.1f} s", seconds=duration))

    tags = grade.source_colour(path)
    sc = scan(path, info["has_audio"], timeout=max(120.0, duration * 10), cancelled=cancelled,
              size=(info["width"], info["height"]), matrix=level_matrix({**tags, "height": info["height"]}),
              seconds=duration)
    decoded = sc.frames / info["fps"] if info["fps"] else sc.decoded_s
    truncated = decoded < duration * 0.97 - 0.3
    if sc.returncode or sc.errors or truncated:
        why = [f"only {decoded:.1f} of {duration:.1f} s decode"] if truncated else []
        why += sc.errors[:3] + ([f"ffmpeg exit code {sc.returncode}"] if sc.returncode else [])
        out.append(check("decode", "Decodes completely", DETERMINISTIC, FAIL, "; ".join(why), frames=sc.frames,
                         decoded_s=round(decoded, 2)))
    else:
        out.append(check("decode", "Decodes completely", DETERMINISTIC, PASS, f"{sc.frames} frames",
                         frames=sc.frames, decoded_s=round(decoded, 2)))
    out += _picture_checks(sc, duration)
    out += _sound_checks(sc, duration, info["has_audio"], expected.get("transcript"))
    out += _caption_checks(expected.get("srt"), duration, expected.get("transcript"))
    out += _cut_checks(expected.get("transcript"), expected.get("edl"))
    out += [_levels_check(sc), _colour_tags(tags, info["height"]),
            _loudness_check(sc, info["has_audio"], expected.get("sound"))]
    return out


def informing_last(checks: list[dict]) -> list[dict]:
    """The checks with those that only inform (LAST_CHECKS) moved to the end, in their order."""
    return [c for c in checks if c["name"] not in LAST_CHECKS] + [c for c in checks if c["name"] in LAST_CHECKS]


def sound_intent(render_info: dict | None) -> dict:
    """What the render asked of the sound (normalization on or off, the owner's volume, what held the level back,
    the level it aimed at), so the final check explains the loudness as the renderer did (loudness.check)."""
    info = render_info or {}
    settings = (artifact.of(info) or {}).get("settings") or {}
    plan = info.get("audio_processing") or {}
    qc = (info.get("qc") or {}).get("sound") or {}
    capped, peaks = qc.get("boost_capped", plan.get("boost_capped")), qc.get("peak_limited", plan.get("peak_limited"))
    return {"normalized": settings.get("normalize_audio", True) is not False,
            "owner_gain_db": float(settings.get("gain_db") or 0), "held": "cap" if capped else "peaks" if peaks else "",
            "expected_lufs": qc.get("expected_lufs")}


def _audio_packet_timing(path: str | Path, cancelled: Callable[[], bool] | None = None) -> dict:
    label = "Audio timing for upload"
    try:
        result = audio_timing.inspect(path, cancelled)
    except FFmpegError as exc:
        return check("audio_packet_timing", label, DETERMINISTIC, FAIL, str(exc))
    if not result["applicable"]:
        return check("audio_packet_timing", label, DETERMINISTIC, SKIP, result["reason"])
    return check("audio_packet_timing", label, DETERMINISTIC, PASS if result["valid"] else FAIL,
                 "Stored audio timestamps are continuous." if result["valid"] else
                 "The file has broken audio timestamps that can cause glitches or silence after upload. "
                 "Render it again before uploading.", **result)


def _av_timing(info: dict) -> dict:
    """Container track timing only; this cannot verify lip sync or align speech with moving mouths."""
    start_v, start_a = info.get("video_start"), info.get("audio_start")
    if not info.get("has_audio") or start_v is None or start_a is None:
        return check("av_timing", "Audio/video track timing", DETERMINISTIC, SKIP,
                     "Track timestamps are unavailable; lip sync was not measured.")
    offset = abs(float(start_v) - float(start_a))
    dv, da = info.get("video_duration"), info.get("audio_duration")
    difference = abs(float(dv) - float(da)) if dv is not None and da is not None else None
    status = FAIL if offset > 0.5 or (difference is not None and difference > max(1.0, 0.03 * float(dv))) else \
        WARN if offset > 0.15 else PASS
    detail = f"Tracks start {offset:.2f} s apart" + (f"; lengths differ by {difference:.2f} s" if difference is not
                                                    None else "; track lengths unavailable") + ". Lip sync not measured."
    return check("av_timing", "Audio/video track timing", DETERMINISTIC, status, detail,
                 start_offset_s=round(offset, 3), duration_difference_s=difference)


def _picture_checks(sc: Scan, duration: float) -> list[dict]:
    out = []
    black = _total(sc.black)
    if black >= 0.5 * duration:
        out.append(check("black", "Black frames", HEURISTIC, FAIL, f"Black for {black:.1f} of {duration:.1f} s.",
                         seconds=round(black, 2)))
    elif sc.black and sc.black[0][0] < 0.1:
        out.append(check("black", "Black frames", HEURISTIC, WARN,
                         f"Opens on a black screen ({sc.black[0][1]:.1f} s).", seconds=round(black, 2)))
    elif any(b - a >= 1.5 for a, b in sc.black):
        out.append(check("black", "Black frames", HEURISTIC, WARN, f"Black at {_fmt(sc.black)}.",
                         seconds=round(black, 2)))
    else:
        out.append(check("black", "Black frames", HEURISTIC, PASS))
    frozen, silent = _total(sc.frozen), _total(sc.silent)
    if frozen >= 0.9 * duration and silent >= 0.5 * duration:
        out.append(check("frozen", "Moving picture", HEURISTIC, FAIL, "A still picture with little or no sound.",
                         seconds=round(frozen, 2)))
    elif frozen >= 0.9 * duration:
        out.append(check("frozen", "Moving picture", HEURISTIC, WARN,
                         "The picture hardly changes (fine for a still image over speech; check it is intended).",
                         seconds=round(frozen, 2)))
    elif any(b - a >= 3.0 for a, b in sc.frozen):
        out.append(check("frozen", "Moving picture", HEURISTIC, WARN, f"The picture stands still at {_fmt(sc.frozen)}.",
                         seconds=round(frozen, 2)))
    else:
        out.append(check("frozen", "Moving picture", HEURISTIC, PASS))
    return out


def _levels_check(sc: Scan) -> dict:
    """The picture's levels against EBU R103: more than 1% of a frame outside the luma or RGB limits."""
    label = "Picture levels"
    if not sc.levels:
        return check("levels", label, HEURISTIC, SKIP, "The picture's levels were not measured.")
    n = len(sc.levels)
    wrong = sum(1 for f in sc.levels if f["strict_out"] > WRONG_RANGE)
    bad = [f for f in sc.levels if f["luma_out"] > LEVEL_AREA or f["rgb_out"] > LEVEL_AREA]
    worst = max(sc.levels, key=lambda f: max(f["luma_out"], f["rgb_out"]))
    values = {"frames": n, "frames_outside": len(bad), "worst_at_s": worst["t"],
              "worst_luma": round(worst["luma_out"], 4), "worst_rgb": round(worst["rgb_out"], 4),
              "y_min": min(f["y_min"] for f in sc.levels), "y_max": max(f["y_max"] for f in sc.levels)}
    if wrong >= max(1, n / 2):
        return check("levels", label, HEURISTIC, WARN,
                     "The blacks and whites go past the video range in most of the clip (full-range picture in a "
                     "limited-range file?): it will look harsher after upload.", **values)
    if bad:
        share = max(worst["luma_out"], worst["rgb_out"]) * 100
        return check("levels", label, HEURISTIC, WARN,
                     f"Colours outside the broadcast range in {len(bad)} of {n} sampled frames (worst at "
                     f"{worst['t']:.1f} s: {share:.1f}% of the picture); players clip them.", **values)
    return check("levels", label, HEURISTIC, PASS, f"Within the broadcast range ({n} sampled frames).", **values)


def _colour_tags(tags: dict, height: int) -> dict:
    """The file's colour tags (grade.source_colour): ClipForge makes BT.709 limited range; another tag makes players
    show other colours. An untagged HD file is read as BT.709 by players, so it passes."""
    allowed = {"matrix": ("bt709",), "primaries": ("bt709",), "transfer": ("bt709", "bt1886"), "range": ("tv",)}
    wrong = [f"{k} {tags[k]}" for k, ok in allowed.items() if tags.get(k) and tags[k] not in ok]
    values = {k: tags.get(k) or "" for k in ("matrix", "primaries", "transfer", "range")}
    if wrong:
        return check("colour_tags", "Colour tags", DETERMINISTIC, WARN,
                     "Tagged " + ", ".join(wrong) + " (ClipForge makes BT.709 limited range): players may show "
                     "other colours.", **values)
    untagged = [k for k in ("matrix", "primaries", "transfer", "range") if not tags.get(k)]
    assumed = "BT.709" if level_matrix({**tags, "height": height}) == "bt709" else "BT.601"
    return check("colour_tags", "Colour tags", DETERMINISTIC, PASS,
                 "BT.709, limited range" + (f" (partly untagged: players assume {assumed})" if untagged else ""),
                 **values)


def _loudness_check(sc: Scan, has_audio: bool, intent: dict | None = None) -> dict:
    """How loud the file plays, judged as the renderers judge it (loudness.check): within 1 LU of -14 LUFS, peaks at
    or under -1 dBTP. `intent` (sound_intent): what the render asked of the sound, which explains a level off target
    (normalization off, the owner's volume, peaks that held it back)."""
    label = "Loudness"
    if not has_audio:
        return check("loudness", label, HEURISTIC, SKIP, "No audio track to check.")
    if sc.loudness is None:
        return check("loudness", label, HEURISTIC, SKIP, "The loudness could not be measured.")
    if sc.loudness.get("lufs") is None:
        return check("loudness", label, HEURISTIC, SKIP, "Silent: no loudness to check.", **sc.loudness)
    intent = intent or {}
    normalized = intent.get("normalized", True)
    aimed = intent.get("expected_lufs")
    verdict = loudness.check(sc.loudness, aimed if aimed is not None else loudness.TARGET_LUFS if normalized else None,
                             normalized=normalized, owner_gain_db=float(intent.get("owner_gain_db") or 0),
                             held=intent.get("held") or "")
    return check("loudness", label, HEURISTIC, PASS if verdict["status"] == "pass" else WARN, verdict["note"],
                 **sc.loudness)


def _sound_checks(sc: Scan, duration: float, has_audio: bool, transcript: dict | None) -> list[dict]:
    if not has_audio:
        return [check("silence", "Sound", HEURISTIC, SKIP, "No audio track to check.")]
    silent = _total(sc.silent)
    words = (transcript or {}).get("words") or []
    muted = [w for w in words if any(a - 0.05 <= w["start"] and w["end"] <= b + 0.05 for a, b in sc.silent)]
    if silent >= 0.5 * duration:
        return [check("silence", "Sound", HEURISTIC, FAIL, f"Silent for {silent:.1f} of {duration:.1f} s.",
                      seconds=round(silent, 2))]
    if words and len(muted) >= max(3, 0.3 * len(words)):
        return [check("silence", "Sound", HEURISTIC, FAIL,
                      f"{len(muted)} of {len(words)} spoken words fall where the audio is silent (sound lost?).",
                      seconds=round(silent, 2))]
    problems = []
    if sc.silent and sc.silent[0][0] < 0.1 and sc.silent[0][1] >= 1.5:
        problems.append(f"starts with {sc.silent[0][1]:.1f} s of silence")
    if sc.silent and sc.silent[-1][1] >= duration - 0.1 and sc.silent[-1][1] - sc.silent[-1][0] >= 2.0:
        problems.append(f"ends with {sc.silent[-1][1] - sc.silent[-1][0]:.1f} s of silence")
    inner = [(a, b) for a, b in sc.silent if a >= 0.1 and b < duration - 0.1 and b - a >= 3.0]
    if inner:
        problems.append(f"silent at {_fmt(inner)}")
    if muted:
        problems.append(f"{len(muted)} spoken word(s) where the audio is silent")
    detail = "; ".join(problems)
    return [check("silence", "Sound", HEURISTIC, WARN if problems else PASS, detail[:1].upper() + detail[1:],
                  seconds=round(silent, 2))]


def _caption_checks(srt: str | None, duration: float, transcript: dict | None) -> list[dict]:
    if not srt:
        return [check("captions", "Caption timing", DETERMINISTIC, SKIP, "No caption file recorded.")]
    cues = srt_cues(srt)
    if cues is None:
        return [check("captions", "Caption timing", DETERMINISTIC, FAIL, "The caption file is missing.")]
    words = (transcript or {}).get("words") or []
    if not cues:
        status = WARN if words else PASS
        return [check("captions", "Caption timing", DETERMINISTIC, status,
                      "No captions although the clip has speech." if words else "No speech, no captions.")]
    bad = [(a, b) for a, b, _ in cues if a < 0 or b <= a or a >= duration or b > duration + 0.25]
    empty = sum(1 for *_, body in cues if not body)
    if bad:
        return [check("captions", "Caption timing", DETERMINISTIC, FAIL,
                      f"{len(bad)} caption(s) outside the clip ({_fmt(bad)}; clip is {duration:.1f} s).",
                      cues=len(cues))]
    return [check("captions", "Caption timing", DETERMINISTIC, WARN if empty else PASS,
                  f"{empty} empty caption(s)." if empty else f"{len(cues)} captions inside the clip", cues=len(cues))]


def _cut_checks(transcript: dict | None, edl: dict | None) -> list[dict]:
    """Does a cut fall inside a word? At the start or the end that is a failure (the clip starts or stops
    mid-word); inside the clip it is a warning (a silence cut clipped a word)."""
    words = (transcript or {}).get("words") or []
    segs = (edl or {}).get("segments") or []
    if not words or not segs:
        return [check("cuts", "Cuts between words", DETERMINISTIC, SKIP, "No time map or final transcript.")]
    first, last = segs[0]["src_start"], segs[-1]["src_end"]
    starts_mid = words[0]["src_start"] < first - 0.05
    ends_mid = words[-1]["src_end"] > last + 0.05
    inner = [w["w"] for w in words[1:-1]
             if not any(s["src_start"] - 0.05 <= w["src_start"] and w["src_end"] <= s["src_end"] + 0.05 for s in segs)]
    if starts_mid or ends_mid:
        where = " and ".join(x for x, y in (("starts", starts_mid), ("ends", ends_mid)) if y)
        return [check("cuts", "Cuts between words", DETERMINISTIC, FAIL, f"The clip {where} in the middle of a word.")]
    if inner:
        return [check("cuts", "Cuts between words", DETERMINISTIC, WARN,
                      f"A cut clips {len(inner)} word(s): {', '.join(inner[:4])}.")]
    return [check("cuts", "Cuts between words", DETERMINISTIC, PASS)]


def content_checks(clip: dict) -> list[dict]:
    """Hook, context, payoff and misleading-edit estimates from the transcript analysis made when the moment was
    chosen. Estimates only: they cannot prove the clip is accurate or fair, so they never pass silently when the
    clip was edited after the analysis."""
    analysis = clip.get("analysis") or {}
    if not analysis.get("structure") and not analysis.get("flags"):
        return [check("content", "Hook, context and payoff", HEURISTIC, SKIP, "No transcript analysis for this clip.")]
    st = analysis.get("structure") or {}
    blocks = [f for f in analysis.get("flags") or [] if f.get("severity") == "block"]
    warns = [f for f in analysis.get("flags") or [] if f.get("severity") == "warn"]
    edited = any(k in (clip.get("edit") or {}) for k in ("start", "end", "caption_words"))
    missing = [k for k in ("hook", "context", "payoff") if not st.get(k)]
    if blocks:
        return [check("content", "Hook, context and payoff", HEURISTIC, FAIL,
                      "; ".join(f"{f['label']}: {f['detail']}" for f in blocks))]
    notes = [f"{f['label']}: {f['detail']}" for f in warns]
    if missing:
        notes.append("no clear " + ", ".join(missing))
    if edited:
        notes.append("the clip was edited after this analysis: review the edited clip yourself")
    return [check("content", "Hook, context and payoff", HEURISTIC, WARN if notes else PASS,
                  "; ".join(notes) or "Hook, context and payoff found (estimate)")]


def framing_checks(render_info: dict) -> list[dict]:
    """Is the subject kept in the vertical frame? A heuristic from the framing plan the renderer used: a centre crop
    of a wide picture in which no face or subject was tracked can cut people off."""
    crop, mode = render_info.get("crop_w"), render_info.get("mode")
    if crop is None or not mode:
        return [check("framing", "Framing", HEURISTIC, SKIP, "No framing record for this render.")]
    if float(crop) >= 0.999 or render_info.get("layout") == "fit":
        return [check("framing", "Framing", HEURISTIC, PASS, "The whole picture is kept (no crop).")]
    if mode == "split":
        cam = (render_info.get("framing_evidence") or {}).get("cam") or {}
        found = {"border": "its rectangle was found", "manual": "where you drew it",
                 "camera": "from your camera recording"}.get(cam.get("kind"), "framed around the face")
        if render_info.get("layout") == "pip":
            return [check("framing", "Framing", HEURISTIC, PASS, f"Picture-in-picture: the gameplay fills the frame "
                                                                 f"and the face cam ({found}) sits in a box at the "
                                                                 "top (estimate).")]
        if render_info.get("layout") == "game":
            return [check("framing", "Framing", HEURISTIC, PASS, f"Gameplay only: the gameplay fills the frame and "
                                                                 f"the face cam ({found}) is left out (estimate).")]
        below = "the whole picture" if render_info.get("split_game") == "whole" else "the rest of the picture"
        return [check("framing", "Framing", HEURISTIC, PASS,
                      f"Split view: the face cam on top ({found}) and {below} below (estimate).")]
    if mode in ("face", "speaker"):
        n = int(render_info.get("faces") or 0)
        return [check("framing", "Framing", HEURISTIC, PASS, f"Follows {n} face{'s' if n != 1 else ''} (estimate).")]
    if mode in ("screen", "manual"):
        return [check("framing", "Framing", HEURISTIC, PASS, "Follows the screen's action (estimate)." if mode ==
                      "screen" else "Framed by you.")]
    if mode == "motion":
        evidence = render_info.get("framing_evidence") or {}
        samples, tracked = evidence.get("samples") or 0, evidence.get("visual_target_samples") or 0
        if samples >= 3 and tracked >= max(3, samples * .5) and (evidence.get("motion") or 0) > .25:
            return [check("framing", "Framing", HEURISTIC, PASS,
                          "Follows measured moving visual activity (estimate); this is not face identification.")]
    return [check("framing", "Framing", HEURISTIC, WARN, "No face or subject was tracked, so the picture is cropped in "
                                                        "the middle; people at the sides may be cut off.")]


# ------------------------------------------------------------------ one file, everything
def evaluate(path: str | Path, render_info: dict, clip: dict, has_audio: bool = True,
             cancelled: Callable[[], bool] | None = None) -> dict:
    """The media report of one rendered file: checks, blockers, warnings, what it is bound to and what was
    (not) covered."""
    art = artifact.of(render_info) or {}
    transcript = artifact.final_transcript(render_info)
    edl = read_json(Path(art["edl"]), None) if art.get("edl") else None
    expected = {"duration": art.get("duration") or render_info.get("duration") or clip.get("duration"),
                "has_audio": has_audio, "sha256": art.get("sha256"), "transcript": transcript, "edl": edl,
                "srt": (art.get("captions") or {}).get("srt") or _default_srt(path), "sound": sound_intent(render_info)}
    checks = informing_last(media_checks(path, expected, cancelled) + framing_checks(render_info) +
                            content_checks(clip))
    sha = next((c["values"]["sha256"] for c in checks if c["name"] == "hash"), None) or ""
    st = os.stat(path) if Path(path).exists() else None
    return {
        "gate_version": GATE_VERSION, "artifact_path": str(path), "artifact_sha256": sha,
        "file_stamp": file_stamp(path) if st else "",
        "checks": checks,
        "blockers": [f"{c['label']}: {c['detail']}" for c in checks if c["status"] == FAIL],
        "warnings": [f"{c['label']}: {c['detail']}" for c in checks if c["status"] == WARN],
        "passed": not any(c["status"] == FAIL for c in checks),
        "bindings": {"transcript_sha256": art.get("transcript_sha256") or "", "edl": art.get("edl") or "",
                     "blueprint": art.get("blueprint"), "rendered_at": art.get("created_at")},
        "coverage": {
            "deterministic": sorted(c["name"] for c in checks if c["kind"] == DETERMINISTIC and c["status"] != SKIP),
            "heuristic": sorted(c["name"] for c in checks if c["kind"] == HEURISTIC and c["status"] != SKIP),
            "skipped": sorted(c["name"] for c in checks if c["status"] == SKIP),
            "note": "Technical checks decode the whole file. Content checks are estimates from the transcript; "
                    "they do not prove that the clip is accurate or fair.",
        },
    }


def _default_srt(path: str | Path) -> str:
    srt = Path(path).parent / "captions.srt"
    return str(srt) if srt.exists() else ""


def file_stamp(path: str | Path) -> str:
    """Cheap identity of a file on disk (size and modification time), for finding its report without hashing."""
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"
