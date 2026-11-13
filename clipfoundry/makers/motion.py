"""A scene's moving clip for an animated short (docs/clipforge/ANIMATED_SHORTS.md).

`still_clip` moves a still picture with a slow camera (a push-in, a pull-out or a pan, the "Ken Burns" move viral
shorts use so the picture is never still) and lays the scene's voice under it. The picture always covers the frame;
the move is drawn frame by frame with OpenCV at sub-pixel precision, so it glides without the one-pixel jitter of
FFmpeg's zoompan, and the frames are piped straight into FFmpeg.

`video_clip` covers the frame with the video engine's motion, slows it down (at most 1.5 times) when it is shorter
than the voice, and holds its last frame for the rest.

With a `direction` (director.py writes one for every scene of a short made since the viral-look upgrade),
`still_clip` films the picture instead of sliding it: the camera eases, punches in on a phrase, lands on the cut or
whips in, and shakes when something hits (camera.py); the picture is graded and dust, rain, snow, embers, fog or
light drift over it (fx.py); and with a depth map of the picture (depth.py) near things move more than far things.
Fast frames are drawn smeared, as a real shutter would. Without a direction it is the slow move it always was, frame
for frame (shorts made before keep their look until the owner asks for the new one).

Both write an H.264 (BT.709, 4:2:0) + AAC 48 kHz MP4 whose length is exactly frames / fps; the sound is the voice,
padded with silence to the end. Nothing here is sent anywhere.
"""
from __future__ import annotations

import logging
import math
import re
import subprocess
from collections import deque
from pathlib import Path
from threading import Thread
from typing import Callable

from ..pipeline import ffmpeg_utils
from ..pipeline.common import Cancelled

log = logging.getLogger(__name__)

MOVES = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "still")
ORDER = ("zoom_in", "pan_right", "zoom_out", "pan_left")    # scene after scene, so every cut changes direction
PAN_TRAVEL = 1.5           # a pan travels at most this many times `strength` of the frame, however wide the picture
MAX_SLOWDOWN = 1.5         # the engine's video is slowed down at most this much to cover the voice
CRF = "16"                 # scene clips are made again in the final render, so they keep the detail
AUDIO_RATE = "48000"
SHUTTER = 0.7              # a frame in fast motion is the average of moments spread over this share of its time
BLUR_STEP = 5.0            # ...one moment for every this many pixels the picture travels (so the smear has no steps)
BLUR_SAMPLES = (2, 16)     # ...but at least and at most this many
DEPTH_BLUR = 0.011         # the depth map is softened by this share of the picture's width, so edges never tear
PUSH_PARALLAX = 1.6        # a push-in parts near and far this many times `parallax` at the frame's edge


class MotionError(RuntimeError):
    """The clip could not be made; the message says why in plain words."""


def pick_move(index: int) -> str:
    """The camera move for the scene at `index` when the owner left it on automatic."""
    return ORDER[int(index or 0) % len(ORDER)]


def _encode_args(fps: int, frames: int, duration: float) -> list[str]:
    return ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-profile:v", "high", "-pix_fmt", "yuv420p",
            *ffmpeg_utils.delivery_args(fps), "-r", str(fps), "-frames:v", str(frames),
            "-c:a", "aac", "-b:a", ffmpeg_utils.AUDIO_BITRATE, "-ar", AUDIO_RATE, "-ac", "2",
            "-t", f"{duration:.6f}", "-movflags", "+faststart"]


def _audio_args(audio: Path, duration: float) -> list[str]:
    return ["-i", str(audio), "-filter_complex", f"[1:a]aresample={AUDIO_RATE},apad=whole_dur={duration:.6f}[a]",
            "-map", "0:v:0", "-map", "[a]"]


def _read_picture(picture: Path, size: tuple[int, int] | None = None, strength: float = 0.0,
                  background: str | None = None):
    """The picture as BGR pixels, upright (its EXIF orientation), a see-through picture laid on `background`
    ("#RRGGBB", black when None). A JPEG much larger than the move needs for `size` is decoded at a half, a quarter
    or an eighth of its size, so a huge photo never takes gigabytes; a picture over Pillow's size limit (about 180
    million pixels) is refused. Raises MotionError in plain words."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    unreadable = "ClipForge could not open this scene's picture. Choose another picture."
    try:
        with Image.open(picture) as im:
            if size:
                w, h = im.size
                # either way up (EXIF may turn it), with the room the move needs
                need = max(size[0] / w, size[1] / h, size[0] / h, size[1] / w) * (1 + strength)
                if need < 0.5:
                    im.draft(None, (max(1, math.ceil(w * need)), max(1, math.ceil(h * need))))
            im = ImageOps.exif_transpose(im)
            if im.mode == "RGB":
                rgb = im
            else:
                rgba = im.convert("RGBA")
                colour = background if re.fullmatch(r"#[0-9a-fA-F]{6}", str(background or "")) else "#000000"
                rgb = Image.alpha_composite(Image.new("RGBA", rgba.size, colour), rgba).convert("RGB")
            img = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    except Image.DecompressionBombError as exc:
        raise MotionError("This scene's picture is too large to use. Choose a smaller picture.") from exc
    except Exception as exc:  # noqa: BLE001 - a format only OpenCV reads gets one more try
        try:
            img = cv2.imread(str(picture), cv2.IMREAD_COLOR)
        except cv2.error:
            img = None
        if img is None:
            log.info("scene picture unreadable: %s", exc)
            raise MotionError(unreadable) from exc
    if img.ndim != 3 or img.shape[0] < 2 or img.shape[1] < 2:
        raise MotionError("This scene's picture is empty. Choose another picture.")
    return img


def _prepare(img, size: tuple[int, int], strength: float):
    """The picture at about the size the move needs (a much larger picture is scaled down smoothly first, so the
    frames never shimmer), and the scale that just covers the frame."""
    import cv2

    w_out, h_out = size
    h, w = img.shape[:2]
    cover = max(w_out / w, h_out / h)
    need = cover * (1 + strength)
    if need < 0.75:
        k = need / 0.95
        img = cv2.resize(img, (max(2, round(w * k)), max(2, round(h * k))), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
        cover = max(w_out / w, h_out / h)
    return img, cover


def _transform(move: str, p: float, w: int, h: int, size: tuple[int, int], cover: float,
               strength: float) -> tuple[float, float, float]:
    """(scale, x, y) of the picture at progress `p` (0-1) through the scene."""
    w_out, h_out = size
    if move == "zoom_in":
        s = cover * (1 + strength * p)
    elif move == "zoom_out":
        s = cover * (1 + strength * (1 - p))
    elif move == "still":
        s = cover
    else:
        s = cover * (1 + strength)
    x0, y0 = (w_out - w * s) / 2, (h_out - h * s) / 2   # centred
    if move in ("pan_left", "pan_right"):
        travel = min(w * s - w_out, w_out * strength * PAN_TRAVEL)
        shift = travel * (p - 0.5) if move == "pan_right" else travel * (0.5 - p)
        return s, x0 - shift, y0
    if move in ("pan_up", "pan_down"):
        travel = min(h * s - h_out, h_out * strength * PAN_TRAVEL)
        shift = travel * (p - 0.5) if move == "pan_down" else travel * (0.5 - p)
        return s, x0, y0 - shift
    return s, x0, y0


def _drain(stream, tail: deque) -> None:
    for raw in iter(stream.readline, b""):
        tail.append(raw.decode("utf-8", "replace").rstrip())
    stream.close()


def _check(cancel: Callable[[], bool] | None) -> None:
    if cancel and cancel():
        raise Cancelled("Stopped.")


def _frames(duration_s: float, fps: int) -> int:
    if not (isinstance(duration_s, (int, float)) and math.isfinite(duration_s) and duration_s > 0):
        raise MotionError("The scene has no length. Make its voice again.")
    return max(1, round(float(duration_s) * fps))


def _read_depth(path: Path | None, shape: tuple[int, int]):
    """The picture's depth map (any size, grey: bright is near) fitted to the picture: 0 (far) to 1 (near), soft at
    the edges of things; None when there is none or it cannot be read (the camera then moves without it)."""
    import cv2
    import numpy as np
    from PIL import Image

    if not path:
        return None
    try:
        with Image.open(path) as im:
            raw = np.asarray(im.convert("F"), dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 - depth is an extra: without it the picture still moves
        log.info("depth map unreadable: %s", exc)
        return None
    h, w = shape
    depth = cv2.resize(raw, (w, h), interpolation=cv2.INTER_LINEAR)
    lo, hi = np.percentile(depth, (2, 98))
    if not hi - lo > 1e-6:
        return None   # flat: nothing is nearer than anything else
    depth = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
    return cv2.GaussianBlur(depth, (0, 0), max(1.5, w * DEPTH_BLUR))


class _Stage:
    """A picture being filmed by a direction: `frame(i)` is frame i of the scene (BGR, uint8)."""

    def __init__(self, img, size: tuple[int, int], frames: int, fps: int, direction: dict, depth=None):
        import numpy as np

        from . import camera, fx

        d = direction if isinstance(direction, dict) else {}
        self.size = (int(size[0]), int(size[1]))
        grade = d.get("grade") if isinstance(d.get("grade"), dict) else {}
        self.img = fx.finish(img, grade)
        h, w = self.img.shape[:2]
        seed = int(d.get("seed") or 0)
        self.depth = depth if depth is not None and depth.shape[:2] == (h, w) else None
        focus = None
        if not d.get("focus"):
            focus = _near_focus(self.depth) if self.depth is not None else camera.find_focus(self.img)
        self.cam = camera.Camera(d, (w, h), self.size, frames, fps, focus, seed)
        self.air = fx.Atmosphere(d.get("fx") or (), self.size, fps, seed, float(d.get("fx_amount") or 1.0))
        self.finish = fx.Frame(self.size, grade.get("vignette") or 0.0, grade.get("grain") or 0.0, seed)
        self.parallax = self.cam.parallax * self.size[0] if self.depth is not None else 0.0
        if self.parallax:
            self.pivot = float(np.median(self.depth))
            vv, uu = np.mgrid[0:self.size[1], 0:self.size[0]].astype(np.float32)
            self.u, self.v = uu, vv

    def _draw(self, shot):
        import cv2
        import numpy as np

        m = np.array(self.cam.matrix(shot), dtype=np.float64)
        sharp = cv2.INTER_CUBIC if shot.scale > 1.02 else cv2.INTER_LINEAR
        if not self.parallax:
            return cv2.warpAffine(self.img, m, self.size, flags=sharp, borderMode=cv2.BORDER_REFLECT)
        # near things move more than far things: each frame pixel looks a little further along the camera's path
        # the nearer the thing it shows (the depth is read where the pixel would look without it)
        inv = cv2.invertAffineTransform(m)
        rel = cv2.warpAffine(self.depth, m, self.size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        rel -= self.pivot
        edge = PUSH_PARALLAX * self.cam.parallax * shot.push
        ox = rel * (self.parallax * shot.lateral[0] - edge * (self.u - self.size[0] / 2))
        oy = rel * (self.parallax * shot.lateral[1] - edge * (self.v - self.size[1] / 2))
        map_x = (inv[0, 0] * (self.u + ox) + inv[0, 1] * (self.v + oy) + inv[0, 2]).astype(np.float32)
        map_y = (inv[1, 0] * (self.u + ox) + inv[1, 1] * (self.v + oy) + inv[1, 2]).astype(np.float32)
        return cv2.remap(self.img, map_x, map_y, sharp, borderMode=cv2.BORDER_REFLECT)

    def _moments(self, i: int) -> int:
        """How many moments frame i's smear is made of: enough that the picture's furthest-moving corner steps no
        more than BLUR_STEP pixels between two of them."""
        import numpy as np

        a = np.array(self.cam.matrix(self.cam.at(max(0.0, i - SHUTTER / 2))), dtype=np.float64)
        b = np.array(self.cam.matrix(self.cam.at(i + SHUTTER / 2)), dtype=np.float64)
        h, w = self.img.shape[:2]
        corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], dtype=np.float64).T
        travel = float(np.abs(a @ corners - b @ corners).max())
        return int(min(BLUR_SAMPLES[1], max(BLUR_SAMPLES[0], math.ceil(travel / BLUR_STEP))))

    def frame(self, i: int):
        import numpy as np

        shot = self.cam.at(i)
        if shot.blur:   # the average of the moments around this one
            n = self._moments(i)
            total = np.zeros((self.size[1], self.size[0], 3), dtype=np.float32)
            for k in range(n):
                total += self._draw(self.cam.at(max(0.0, i + ((k + 0.5) / n - 0.5) * SHUTTER)))
            frame = (total / n).astype(np.uint8)
        else:
            frame = self._draw(shot)
        self.air.apply(frame, i)
        self.finish.apply(frame, i, shot.flash)
        return frame


def _near_focus(depth) -> tuple[float, float]:
    """Where the nearest things in the picture are, as shares of its width and height (kept where a short's
    subject sits)."""
    import cv2
    import numpy as np

    from . import camera

    small = cv2.resize(depth, (48, 86), interpolation=cv2.INTER_AREA)
    near = np.clip(small - np.percentile(small, 70), 0, None)
    total = float(near.sum())
    if total <= 1e-6:
        return camera.FOCUS
    yy, xx = np.mgrid[0:small.shape[0], 0:small.shape[1]].astype(np.float32)
    fx_ = float((near * xx).sum() / total) / (small.shape[1] - 1)
    fy_ = float((near * yy).sum() / total) / (small.shape[0] - 1)
    (x0, x1), (y0, y1) = camera.FOCUS_BOX
    return min(x1, max(x0, fx_)), min(y1, max(y0, fy_))


def _room(direction: dict) -> float:
    """How much closer than "the picture just covers the frame" this direction ever goes (the picture is kept that
    much larger, so the closest framing is still sharp)."""
    from . import camera

    d = direction if isinstance(direction, dict) else {}
    try:
        strength = min(camera.MAX_STRENGTH, max(0.0, float(d.get("strength") or 0.08)))
    except (TypeError, ValueError):
        strength = 0.08
    punch = 1.0
    for b in d.get("beats") or []:
        try:
            punch = max(punch, punch * float(b.get("zoom") or 1.0))
        except (AttributeError, TypeError, ValueError):
            continue
    return min(1.2, (1.0 + strength * 1.6) * min(camera.MAX_PUNCH, punch) - 1.0)


def still_clip(picture: Path, audio: Path, out: Path, *, duration_s: float, move: str = "zoom_in", fps: int = 30,
               size: tuple[int, int] = (1080, 1920), strength: float = 0.08,
               cancel: Callable[[], bool] | None = None,
               progress: Callable[[float], None] | None = None, background: str | None = None,
               direction: dict | None = None, depth: Path | None = None) -> dict:
    """The still picture moving with the voice under it: {"path", "duration_s", "frames"}. A see-through picture is
    laid on `background` ("#RRGGBB"; black when None). With `direction` (camera.py describes it) the picture is
    filmed: eased moves, punch-ins, an entry, the air over it and its grade; `depth` is the picture's depth map
    (a grey picture, bright is near), which parts near and far as the camera moves. Raises MotionError."""
    import cv2
    import numpy as np

    _check(cancel)
    move = move if move in MOVES else "zoom_in"
    fps = int(fps)
    frames = _frames(duration_s, fps)
    duration = frames / fps
    strength = min(0.3, max(0.0, float(strength)))
    w_out, h_out = int(size[0]), int(size[1])
    room = _room({"move": move, **direction}) if direction is not None else strength
    img, cover = _prepare(_read_picture(Path(picture), (w_out, h_out), room, background), (w_out, h_out), room)
    h, w = img.shape[:2]
    stage = None
    if direction is not None:
        stage = _Stage(img, (w_out, h_out), frames, fps, {"move": move, "strength": strength, **direction},
                       _read_depth(depth, (h, w)))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part" + out.suffix)
    cmd = [ffmpeg_utils.ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w_out}x{h_out}", "-framerate", str(fps), "-i", "pipe:0",
           *_audio_args(Path(audio), duration), *_encode_args(fps, frames, duration), "-f", "mp4", str(part)]
    tail: deque = deque(maxlen=30)
    try:
        with ffmpeg_utils.MediaWatchdog(cancel, max(600.0, duration * 30)) as watch:
            proc = watch.add(subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.PIPE, creationflags=ffmpeg_utils.NO_WINDOW))
            reader = Thread(target=_drain, args=(proc.stderr, tail), daemon=True)
            reader.start()
            assert proc.stdin is not None
            try:
                still = None
                for i in range(frames):
                    watch.check()
                    p = i / (frames - 1) if frames > 1 else 0.0
                    if stage is not None:
                        frame = stage.frame(i)
                    elif move == "still" and still is not None:
                        frame = still
                    else:
                        s, x, y = _transform(move, p, w, h, (w_out, h_out), cover, strength)
                        m = np.array([[s, 0.0, x], [0.0, s, y]], dtype=np.float64)
                        frame = cv2.warpAffine(img, m, (w_out, h_out), flags=cv2.INTER_LINEAR,
                                               borderMode=cv2.BORDER_REFLECT)
                        still = frame if move == "still" else None
                    proc.stdin.write(np.ascontiguousarray(frame).tobytes())
                    if progress and (i % 10 == 0 or i == frames - 1):
                        progress((i + 1) / frames)
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                watch.check()  # a cancel or a time limit killed FFmpeg: report that
                proc.wait()
                reader.join(timeout=2)
                raise MotionError(_failed(tail)) from None
            proc.wait()
            reader.join(timeout=2)
            watch.check()
        if proc.returncode != 0:
            raise MotionError(_failed(tail))
        part.replace(out)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return {"path": out, "duration_s": duration, "frames": frames}


def _failed(tail: deque) -> str:
    log.warning("scene clip failed: %s", " | ".join(list(tail)[-6:]))
    return "ClipForge could not make this scene's moving picture. Try again; if it keeps failing, choose another " \
           "picture."


def video_clip(video: Path, audio: Path, out: Path, *, duration_s: float, fps: int = 30,
               size: tuple[int, int] = (1080, 1920), cancel: Callable[[], bool] | None = None,
               progress: Callable[[float], None] | None = None) -> dict:
    """The video engine's motion covering the frame, with the voice: {"path", "duration_s", "frames"}. A video
    shorter than the voice is slowed down (at most 1.5 times) and its last frame held for the rest. Raises
    MotionError."""
    _check(cancel)
    fps = int(fps)
    frames = _frames(duration_s, fps)
    duration = frames / fps
    try:
        info = ffmpeg_utils.probe(video, cancel=cancel)
    except ffmpeg_utils.FFmpegError as exc:
        raise MotionError("The video maker's clip could not be read.") from exc
    length = float(info.get("video_duration") or info.get("duration") or 0.0)
    if length <= 0.05:
        raise MotionError("The video maker's clip is empty.")
    slow = min(MAX_SLOWDOWN, max(1.0, duration / length))
    hold = max(0.0, duration - length * slow) + 1.0 / fps
    w_out, h_out = int(size[0]), int(size[1])
    vf = (f"[0:v]setpts={slow:.6f}*(PTS-STARTPTS),fps={fps},"
          f"scale={w_out}:{h_out}:force_original_aspect_ratio=increase:flags=lanczos,crop={w_out}:{h_out},"
          f"setsar=1,tpad=stop_mode=clone:stop_duration={hold:.6f},"
          f"scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v];"
          f"[1:a]aresample={AUDIO_RATE},apad=whole_dur={duration:.6f}[a]")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.stem + ".part" + out.suffix)
    args = ["-i", str(video), "-i", str(audio), "-filter_complex", vf, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-profile:v", "high", "-pix_fmt", "yuv420p",
            *ffmpeg_utils.delivery_args(fps), "-r", str(fps), "-frames:v", str(frames),
            "-c:a", "aac", "-b:a", ffmpeg_utils.AUDIO_BITRATE, "-ar", AUDIO_RATE, "-ac", "2",
            "-t", f"{duration:.6f}", "-movflags", "+faststart", "-f", "mp4", str(part)]
    try:
        ffmpeg_utils.run(args, duration=duration, cancel=cancel,
                         progress=(lambda f: progress(f)) if progress else None)
        part.replace(out)
    except ffmpeg_utils.FFmpegError as exc:
        part.unlink(missing_ok=True)
        log.warning("engine scene clip failed: %s", exc)
        raise MotionError("ClipForge could not fit the video maker's clip to the voice.") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return {"path": out, "duration_s": duration, "frames": frames}
