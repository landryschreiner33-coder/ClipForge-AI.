"""How loud a render is, measured the way players and platforms measure it, and checked on the finished file.

Both renderers (pipeline/render.py for clips, studio/engine.py for full videos) set the sound's level with one
constant gain from a measurement of the exact edited sound, then catch any peak that is left with a limiter. This
module holds the shared parts:

* the measurement is FFmpeg's ``ebur128`` (ITU-R BS.1770: K-weighted, gated integrated loudness, and the true
  peak from 4x oversampling). ``loudnorm``'s own ``input_i`` read up to 0.75 LU off on speech with level jumps;
* the limiter runs at 192 kHz (4x), so it also catches the peaks between samples, with its ceiling at -2 dBFS:
  the AAC encoder adds its own overshoot, and EBU Tech 3344 asks for -2 dBTP before a codec;
* after the encode the finished file is measured again. A file that missed its level by more than ``FIX_LU`` is
  given its sound once more with the difference corrected (the picture is copied, not encoded again); a file
  whose true peak is above ``MAX_TP`` gets its sound again with a lower ceiling (lower_ceiling).

The level is never pushed past what the peaks allow by squashing them (that pumps and flattens speech): a clip
held back by its peaks stays quieter than -14 LUFS, and the check says so and by how much ("Clean up the sound"
evens such speech out).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable

from .ffmpeg_utils import FFmpegError, ffmpeg_bin, run_process

TARGET_LUFS = -14.0      # YouTube's reference (it turns louder videos down and never turns quieter ones up)
HEADROOM_DBTP = -1.5     # the constant gain leaves the measured true peak at or under this
LIMIT_DBFS = -2.0        # the 4x-oversampled limiter's ceiling (true peak before the encoder)
LOW_LIMIT_DBFS = -3.0    # ... and at most this on the second try, when the encoder pushed the true peak over MAX_TP
MIN_LIMIT_DBFS = -6.0    # ... and never lower than this
MAX_TP = -1.0            # a finished file's true peak over this is too hot (EBU R128; codecs on platforms add more)
MAX_BOOST_DB = 24.0      # quieter sound than -38 LUFS is not raised all the way (its noise would come up too)
FIX_LU = 0.5             # a finished file further than this from its level gets its sound once more
NEAR_LU = 1.0            # within this of the target counts as on target (EBU R128's tolerance)
MAX_FIX_DB = 6.0         # a correction is never larger than this
SILENT_LUFS = -69.9      # ebur128 reports -70 LUFS when every block was gated out (silence)
FILTER = "ebur128=peak=true:framelog=quiet"

_NUM = r"(-?(?:\d+(?:\.\d+)?|inf))"


def limiter(ceiling_dbfs: float = LIMIT_DBFS) -> list[str]:
    """The end-stage limiter at 4x the sample rate (inter-sample peaks included), back at 48 kHz after it. Its
    automatic level is off and its lookahead compensated, so cuts and captions stay where they are."""
    return ["aresample=192000",
            f"alimiter=limit={10 ** (ceiling_dbfs / 20):.6f}:attack=5:release=50:level=disabled:latency=1",
            "aresample=48000"]


def parse(stderr: str | bytes) -> dict:
    """The last ebur128 summary in FFmpeg's log: integrated loudness (LUFS; None for silence), loudness range (LU)
    and true peak (dBTP; None for digital silence). Raises ValueError when there is none or it cannot be read."""
    text = stderr.decode("utf-8", "replace") if isinstance(stderr, bytes) else stderr
    at = text.rfind("Summary:")
    if at < 0:
        raise ValueError("no loudness summary")
    tail = text[at:]
    i = re.search(r"\bI:\s+" + _NUM + r" LUFS", tail)
    lra = re.search(r"\bLRA:\s+" + _NUM + r" LU\b", tail)
    peak = re.search(r"True peak:\s+Peak:\s+" + _NUM + r" dBFS", tail)
    if not (i and lra and peak):
        raise ValueError("incomplete loudness summary")
    vi, vl, vp = (float(m.group(1)) for m in (i, lra, peak))
    if any(math.isnan(v) for v in (vi, vl, vp)) or vi == math.inf or vp == math.inf:
        raise ValueError("invalid loudness")
    return {"lufs": vi if vi > SILENT_LUFS else None, "lra": vl if math.isfinite(vl) else 0.0,
            "tp": vp if math.isfinite(vp) else None}


def gain_for(lufs: float | None, tp: float | None, min_db: float = -MAX_BOOST_DB) -> tuple[float, str]:
    """The constant gain that brings `lufs` to the target without taking its true peak over HEADROOM_DBTP (at most
    MAX_BOOST_DB up, `min_db` down), and what held it short of the target: "peaks", "cap" (a very quiet recording
    raised by the most allowed) or "". Silence gets no gain: its background noise is never raised blindly."""
    if lufs is None:
        return 0.0, ""
    want = TARGET_LUFS - lufs
    room = HEADROOM_DBTP - tp if tp is not None else want
    gain = max(min_db, min(want, room, MAX_BOOST_DB))
    held = "" if gain >= want - 0.01 else "peaks" if room <= MAX_BOOST_DB else "cap"
    return gain, held


def lower_ceiling(tp: float) -> float:
    """The limiter's ceiling for the second try after the encoder took the true peak to `tp`, over MAX_TP. The
    encoder's overshoot shrinks by only 0.7-1 dB for each dB the ceiling comes down (measured on AAC-LC at 128 and
    256 kbps), so the ceiling comes down 1.5 times as far as the peak went over, and half a dB more."""
    return round(max(MIN_LIMIT_DBFS, min(LOW_LIMIT_DBFS, LIMIT_DBFS - 1.5 * (tp - MAX_TP) - 0.5)), 2)


def check(out: dict, expected: float | None, *, normalized: bool, owner_gain_db: float = 0.0,
          held: str = "") -> dict:
    """Judge a finished file's measurement `out` ({lufs, lra, tp}). `expected`: the level the render aimed at
    (the target, or lower when the peaks held it back); None when its level was left alone (normalization off,
    or silence). `held`: what kept the gain short of the target (gain_for). Returns {status: pass | warn |
    skipped (silence), note, fix_db (a correction worth one more try, or 0), lower_ceiling (the true peak is too
    hot), ceiling_dbfs (the limiter's ceiling for that try)}. A measurement that failed is "unmeasured" (judge,
    and both renderers' checks)."""
    lufs, tp = out.get("lufs"), out.get("tp")
    if lufs is None:
        return {"status": "skipped", "note": "Silent: no loudness to check.", "fix_db": 0.0, "lower_ceiling": False,
                "ceiling_dbfs": LIMIT_DBFS}
    notes, fix = [], 0.0
    hot = tp is not None and tp > MAX_TP
    if normalized and expected is not None:
        miss = expected - lufs
        if abs(miss) > FIX_LU:
            fix = max(-MAX_FIX_DB, min(MAX_FIX_DB, miss))
            if fix > 0 and tp is not None:
                fix = min(fix, max(0.0, LIMIT_DBFS - tp))  # never into the limiter
            if fix > 0 and held == "cap":
                fix = 0.0  # already raised by the most allowed (gating makes it read a little under)
            fix = round(fix, 2) if abs(fix) > FIX_LU else 0.0
    status = "pass"
    # the owner's own volume is named as the reason only when, without it, the file would be on target
    owner_made_it = abs(owner_gain_db) > 0.01 and abs(lufs - owner_gain_db - TARGET_LUFS) <= NEAR_LU
    if abs(lufs - TARGET_LUFS) > NEAR_LU:
        status = "warn"
        if lufs < TARGET_LUFS:
            why = ("normalization is off" if not normalized else
                   "your volume setting" if owner_made_it else
                   f"a very quiet recording, raised by the most allowed ({MAX_BOOST_DB:.0f} dB)" if held == "cap"
                   else "its loudest peaks held it back" if held == "peaks" or (
                       expected is not None and expected < TARGET_LUFS - NEAR_LU) else "")
            if why and why != "your volume setting" and owner_gain_db < -0.01:
                why += f", and your volume setting takes {-owner_gain_db:.1f} dB off"
            notes.append(f"Plays {TARGET_LUFS - lufs:.1f} dB quieter than most videos ({lufs:.1f} LUFS)"
                         + (f": {why}" if why else "") + ".")
        else:
            why = ("normalization is off" if not normalized else
                   "your volume setting" if owner_gain_db > 0.01 else "")
            notes.append(f"Louder than most videos ({lufs:.1f} LUFS): platforms will turn it down"
                         + (f" ({why})" if why else "") + ".")
    if hot:
        status = "warn"
        notes.append(f"Peaks reach {tp:.1f} dBTP: they may distort after the platform's own encoding.")
    if status == "pass":
        peaks = f", peaks {tp:.1f} dBTP" if tp is not None else ""
        notes.append(f"As loud as most videos ({lufs:.1f} LUFS{peaks}).")
    return {"status": status, "note": " ".join(notes), "fix_db": fix, "lower_ceiling": hot,
            "ceiling_dbfs": lower_ceiling(tp) if hot else LIMIT_DBFS}


def measure(path: str | Path, cancelled: Callable[[], bool] | None = None, timeout: float = 600.0) -> dict:
    """The loudness of a finished file's sound ({lufs, lra, tp}, see parse)."""
    result = run_process([ffmpeg_bin(), "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(path),
                          "-map", "0:a:0", "-af", FILTER, "-f", "null", "-"], timeout=timeout, cancel=cancelled)
    if result.returncode:
        raise FFmpegError("Could not measure the finished sound: " +
                          result.stderr.decode("utf-8", "replace")[-300:])
    try:
        return parse(result.stderr)
    except ValueError as exc:
        raise FFmpegError("The finished sound's measurement was incomplete.") from exc


def judge(path: str | Path, cancelled: Callable[[], bool] | None = None, timeout: float = 600.0) -> dict:
    """How a file made elsewhere (FilmCraft's export, normalised to the target by FilmCraft itself) sounds, measured
    and judged but not changed: {status, note, lufs, lra, tp, fixed_db: 0}; "skipped" when it cannot be measured."""
    try:
        out = measure(path, cancelled, timeout)
    except FFmpegError:
        return {"status": "unmeasured", "note": "The finished sound could not be measured.", "fixed_db": 0.0}
    verdict = check(out, TARGET_LUFS, normalized=True)
    return {"status": verdict["status"], "note": verdict["note"], **out, "fixed_db": 0.0}
