"""The face cam of a video, as the owner sets it: their own box around the cam (for one clip, or locked for every
clip of the video), or a separate camera recording that stands in for a cam laid over the gameplay.

Files in the project's folder:
- cam.json: the cam found in this video (reframe.find_cam's hint, written by render._remember_cam), or the owner's
  locked box ({"kind": "manual", "locked": true}); a locked box is never replaced by what is found.
- camera.json + camera.<ext>: a separate camera recording: {"file", "offset" (the camera's time at the video's
  second 0; camera time = video time + offset), "width", "height", "duration", "synced" ("sound": matched by the
  sound both recorded; "you": typed by the owner; "none"), "match" (how well the sound matched, 0-1), "box" (the
  part of the camera's picture to show; the whole picture when absent)}.

`chosen` gives reframe.plan the cam to use without looking; `cam_check` tells the clip editor how sure the cam of
a rendered clip is, so the owner is pointed to setting it by hand when it is a guess or was not found.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from .common import read_json, write_json
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin, probe

CAM_FILE = "cam.json"
CAMERA_FILE = "camera.json"
MIN_SIDE = 0.04          # a box narrower or shorter than this share of the picture is not a cam
ENV_RATE = 50            # samples a second of the sound's loudness used to line the two recordings up
SYNC_LISTEN = 300.0      # seconds of the camera's sound compared with the video's
SYNC_MIN = 0.2           # the best match must be at least this good ...
SYNC_APART = 1.25        # ... and this much better than the best match more than a second away from it
SURE = 0.65              # a cam rectangle found with a score this close to reframe.CAM_SCORE is shown as a guess
#                          (a cam flush in a corner scores about 0.7: the frame's edge stands in for two sides)


def clean_box(value) -> list[float] | None:
    """A box [x0, y0, x1, y1] in shares of the picture (0-1), or None for none. Raises ValueError when it is not."""
    if value is None:
        return None
    try:
        box = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError("The face cam box must be four numbers.") from exc
    if len(box) != 4 or not all(np.isfinite(box)):
        raise ValueError("The face cam box must be four numbers.")
    x0, y0, x1, y1 = (min(1.0, max(0.0, v)) for v in box)
    if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
        raise ValueError("The face cam box is too small.")
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


# ------------------------------------------------------------------ the owner's box
def found(pdir: Path) -> dict | None:
    """What cam.json holds: the cam found in this video, or the owner's locked box."""
    cam = read_json(Path(pdir) / CAM_FILE, None)
    return cam if isinstance(cam, dict) and len(cam.get("box") or []) == 4 else None


def locked(pdir: Path) -> list[float] | None:
    cam = found(pdir)
    return [float(v) for v in cam["box"]] if cam and cam.get("locked") else None


def set_lock(pdir: Path, box: list[float] | None) -> None:
    """Lock this box for every clip of the video (None: unlock, and look for the cam again)."""
    path = Path(pdir) / CAM_FILE
    if box is None:
        if (found(pdir) or {}).get("locked"):
            path.unlink(missing_ok=True)
        return
    write_json(path, {"box": clean_box(box), "kind": "manual", "locked": True})


# ------------------------------------------------------------------ a separate camera recording
def camera(pdir: Path) -> dict | None:
    """The separate camera recording's record, when its file is still there."""
    rec = read_json(Path(pdir) / CAMERA_FILE, None)
    if not isinstance(rec, dict) or not rec.get("file") or not (Path(pdir) / rec["file"]).is_file():
        return None
    return rec


def camera_path(pdir: Path) -> Path | None:
    rec = camera(pdir)
    return Path(pdir) / rec["file"] if rec else None


def add_camera(pdir: Path, path: Path, offset: float | None = None, main_audio: Path | None = None,
               name: str = "") -> dict:
    """Record `path` (already in the project's folder) as the video's camera, lined up by the sound both recorded
    unless `offset` is given. `name` is the file's own name, shown to the owner. Raises ValueError when it is not a
    video."""
    try:
        meta = probe(path)
    except Exception as exc:  # noqa: BLE001 - FFmpegError and anything ffprobe could not read
        raise ValueError("That file is not a video ClipForge can read.") from exc
    rec = {"file": path.name, "name": name or path.name, "width": int(meta["width"]), "height": int(meta["height"]),
           "duration": round(float(meta["duration"]), 3), "offset": 0.0, "synced": "none", "match": None}
    if offset is not None:
        rec.update(offset=round(float(offset), 3), synced="you")
    elif meta.get("has_audio") and main_audio is not None and Path(main_audio).exists():
        found_offset, match = sync(main_audio, path)
        if found_offset is not None:
            rec.update(offset=found_offset, synced="sound")
        rec["match"] = None if match is None else round(match, 3)
    write_json(Path(pdir) / CAMERA_FILE, rec)
    return rec


def update_camera(pdir: Path, offset: float | None = None, box=...) -> dict:
    """Change the camera's offset (typed by the owner) or the part of its picture shown (`box`, None: all of it)."""
    rec = camera(pdir)
    if rec is None:
        raise LookupError("This video has no separate camera recording.")
    if offset is not None:
        if not np.isfinite(float(offset)):
            raise ValueError("The offset must be a number of seconds.")
        rec.update(offset=round(float(offset), 3), synced="you")
    if box is not ...:
        if box is None:
            rec.pop("box", None)
        else:
            rec["box"] = clean_box(box)
    write_json(Path(pdir) / CAMERA_FILE, rec)
    return rec


def remove_camera(pdir: Path) -> None:
    rec = read_json(Path(pdir) / CAMERA_FILE, None)
    if isinstance(rec, dict) and rec.get("file") and "/" not in rec["file"] and "\\" not in rec["file"]:
        (Path(pdir) / rec["file"]).unlink(missing_ok=True)
    (Path(pdir) / CAMERA_FILE).unlink(missing_ok=True)


def _envelope(path: Path, seconds: float | None = None) -> np.ndarray:
    """How the sound's loudness rises, ENV_RATE times a second (onsets: claps, words, game sounds), read in pieces
    so an hours-long stream never sits in memory whole."""
    rate, win = 8000, 8000 // ENV_RATE
    cmd = [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0", "-vn",
           *(["-t", f"{seconds:.3f}"] if seconds else []), "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    levels: list[np.ndarray] = []
    rest = np.zeros(0, np.float32)
    try:
        while True:
            buf = proc.stdout.read(rate * 2 * 60)  # type: ignore[union-attr]
            if not buf:
                break
            x = np.concatenate([rest, np.frombuffer(buf[: len(buf) // 2 * 2], np.int16).astype(np.float32)])
            n = len(x) // win
            rest = x[n * win:]
            if n:
                levels.append(np.sqrt(np.mean(x[: n * win].reshape(n, win) ** 2, axis=1)))
    finally:
        proc.kill()
        proc.wait()
    if not levels:
        return np.zeros(0, np.float32)
    level = np.log(np.concatenate(levels) + 1.0)
    rise = np.maximum(0.0, np.diff(level, prepend=level[:1]))
    return ((rise - rise.mean()) / (rise.std() + 1e-6)).astype(np.float32)


def sync(main: Path, cam: Path) -> tuple[float | None, float | None]:
    """The camera's offset (camera time = video time + offset) found by matching the first SYNC_LISTEN seconds of
    its sound against the whole video's sound, and how good the match is (0-1). (None, match) when no single
    place matches clearly (no shared sound, or a camera without the same microphone)."""
    a, b = _envelope(main), _envelope(cam, SYNC_LISTEN)
    if len(a) < ENV_RATE * 3 or len(b) < ENV_RATE * 3:
        return None, None
    # the camera may start before the video (its first seconds hang over the front) or after it
    pad = np.zeros(len(b), np.float32)
    big = np.concatenate([pad, a, pad])
    size = 1 << int(np.ceil(np.log2(len(big) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(big, size) * np.conj(np.fft.rfft(b, size)), size)[: len(big) - len(b) + 1]
    # how much of the camera's sound lies over the video's at each place: a match over a sliver counts less
    j = np.arange(len(corr))
    over = np.maximum(0, np.minimum(j + len(b), len(pad) + len(a)) - np.maximum(j, len(pad)))
    score = corr / len(b) * np.minimum(1.0, over / max(ENV_RATE * 10, len(b) * 0.5))
    best = int(np.argmax(score))
    match = float(score[best])
    away = np.abs(np.arange(len(score)) - best) > ENV_RATE
    second = float(score[away].max()) if away.any() else 0.0
    if match < SYNC_MIN or match < SYNC_APART * max(second, 1e-6):
        return None, max(0.0, min(1.0, match))
    lag = best - len(pad)  # the camera's first sample lines up with the video's sample `lag`
    return round(-lag / ENV_RATE, 3), max(0.0, min(1.0, match))


# ------------------------------------------------------------------ what a render uses
def chosen(pdir: Path, opts: dict) -> dict | None:
    """The cam the owner set for this clip, for reframe.plan: a separate camera recording (its own box, or all of
    it), else this clip's own box (`cam_box` in the clip editor), else the box locked for the whole video."""
    rec = camera(pdir)
    if rec:
        return {"kind": "camera", "box": rec.get("box") or [0.0, 0.0, 1.0, 1.0],
                "size": [int(rec["width"]), int(rec["height"])], "offset": float(rec.get("offset") or 0.0),
                "file": rec["file"]}
    try:
        box = clean_box(opts.get("cam_box"))
    except ValueError:
        box = None
    box = box or locked(pdir)
    return {"kind": "manual", "box": box} if box else None


def key(cam_set: dict | None) -> str:
    """A short fingerprint of the cam the owner set, for the framing plan's cache key."""
    if not cam_set:
        return ""
    return hashlib.sha1(json.dumps(cam_set, sort_keys=True).encode()).hexdigest()[:10]


def cam_check(render_info: dict | None) -> dict | None:
    """How sure the face cam of a rendered clip is, for the clip editor: {"state", "text"}; None when the clip's
    layout does not use a face cam. state: "found" (its rectangle was found), "unsure" (a guess: check it), "none"
    (no cam found: the clip was made without one), "manual" (the owner's box), "camera" (a separate recording)."""
    from .reframe import SPLIT_LAYOUTS

    ri = render_info or {}
    asked = ri.get("layout_asked") or ri.get("layout")
    if asked not in SPLIT_LAYOUTS:
        return None
    cam = (ri.get("framing_evidence") or {}).get("cam")
    if not cam:
        if asked == "auto":
            return None  # nobody asked for a cam view: a clip without one is simply one picture
        return {"state": "none", "text": "No face cam was found in this clip, so it was made without one. If the "
                                         "video has a face cam, draw its box and ClipForge uses that."}
    kind = cam.get("kind")
    if kind == "manual":
        return {"state": "manual", "text": "The face cam is where you drew it."}
    if kind == "camera":
        return {"state": "camera", "text": "The face cam comes from your separate camera recording."}
    if kind == "face":
        return {"state": "unsure", "text": "No edges were found around the face cam, so its box is a guess around "
                                           "the face. Check it, and draw it yourself if it is off."}
    if cam.get("from") == "earlier":
        return {"state": "found", "text": "The face cam is where it was found in an earlier clip of this video (the "
                                          "face was hidden in this one)."}
    if float(cam.get("score") or 0.0) < SURE:
        return {"state": "unsure", "text": "Only some of the face cam's edges were found, so its box may be a little "
                                           "off. Check it, and draw it yourself if it is."}
    return {"state": "found", "text": "The face cam was found by its edges."}
