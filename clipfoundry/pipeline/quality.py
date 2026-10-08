"""Final quality gate, media part: independent checks of the exact file that would be published.

Nothing here trusts the renderer's own account of what it made. The file is hashed, probed and decoded in full (a
truncated MP4 with its index at the front still reports its whole length, so only a full decode shows the damage),
and one pass through ffmpeg's detectors finds black, frozen and silent stretches. The results are judged in context:
a still picture over speech (a podcast with a cover image) is a warning, a still picture over silence is a failure.

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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import config
from . import artifact
from .common import Cancelled, read_json
from .ffmpeg_utils import NO_WINDOW, FFmpegError, ffmpeg_bin, probe

GATE_VERSION = 2
PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skipped"
DETERMINISTIC, HEURISTIC = "deterministic", "heuristic"
MIN_SECONDS = 1.0
SHORTS_MAX_SECONDS = 180.0
# detector settings: black = darker than 10% for 0.5 s; frozen = no change for 2 s; silent = below -50 dB for 1 s
BLACK_FILTER = "blackdetect=d=0.5:pix_th=0.10"
FREEZE_FILTER = "freezedetect=n=-60dB:d=2"
SILENCE_FILTER = "silencedetect=noise=-50dB:d=1"
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
         cancelled: Callable[[], bool] | None = None) -> Scan:
    """Decode every frame and sample once, with the black, freeze and silence detectors."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "level+info", "-progress", "pipe:1",
           "-i", str(path), "-map", "0:v:0", "-vf", f"{BLACK_FILTER},{FREEZE_FILTER}"]
    if has_audio:
        cmd += ["-map", "0:a:0", "-af", SILENCE_FILTER]
    cmd += ["-f", "null", "-"]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if (cancelled and cancelled()) or time.monotonic() > deadline:
                proc.kill()
                proc.wait()
                if cancelled and cancelled():
                    raise Cancelled()
                raise FFmpegError("Decoding the clip took too long")
            time.sleep(0.1)
        out.seek(0)
        err.seek(0)
        progress = out.read().decode("utf-8", "replace").splitlines()
        log = err.read().decode("utf-8", "replace").splitlines()
    res = Scan(returncode=proc.returncode)
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
    return res


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

    sc = scan(path, info["has_audio"], timeout=max(120.0, duration * 10), cancelled=cancelled)
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
    return out


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
    if mode in ("face", "speaker"):
        n = int(render_info.get("faces") or 0)
        return [check("framing", "Framing", HEURISTIC, PASS, f"Follows {n} face{'s' if n != 1 else ''} (estimate).")]
    if mode in ("screen", "manual"):
        return [check("framing", "Framing", HEURISTIC, PASS, "Follows the screen's action (estimate)." if mode ==
                      "screen" else "Framed by you.")]
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
                "srt": (art.get("captions") or {}).get("srt") or _default_srt(path)}
    checks = media_checks(path, expected, cancelled) + framing_checks(render_info) + content_checks(clip)
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
