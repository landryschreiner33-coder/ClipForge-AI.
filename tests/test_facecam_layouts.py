"""Gameplay + Facecam, Picture-in-picture and Gameplay only, a face cam box you draw or lock, and a separate camera
recording lined up by sound (pipeline/facecam.py, reframe.pip_panels/clear_of_cam, render).

Streams are drawn here and encoded with FFmpeg (test_split_view's helpers: a moving game, and a webcam picture with
the repository's face fixture found by the real detector); every check reads the exported clip's own frames."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import needs_ffmpeg
from test_split_view import FPS, H, SECONDS, W, _cam, _game, _stream

H_ = {"X-ClipFoundry": "1"}
BOTTOM_LEFT = (30, 440, 320, 240)    # a framed cam in the bottom-left corner
TOP_RIGHT = (960, 0, 320, 180)       # flush in the top-right corner


def _project(tmp_path: Path, video: Path) -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    meta = probe(video)
    folder = tmp_path / "proj"
    folder.mkdir(exist_ok=True)
    return {"id": "p1", "name": "stream", "source_path": str(video), "dir": str(folder), "info": meta,
            "options": {}, **meta}


def _settings() -> dict:
    from clipfoundry import config

    return {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast", "normalize_audio": False,
            "hook_overlay": False}


def _render(project: dict, edit: dict, cid: str = "c1") -> dict:
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    clip = {"id": cid, "start": 0.0, "end": 5.0, "hook": "", "edit": {"silence": "off", **edit}}
    return render.render_clip(project, clip, [], _settings(), JobContext())


def _frame(path: str | Path, n: int, size: str = "1080:1920") -> np.ndarray:
    width, height = (int(v) for v in size.split(":"))
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
                          f"select=eq(n\\,{n}),scale={size}", "-vsync", "0", "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "bgr24", "pipe:1"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(np.float32)


def _alike(a: np.ndarray, b: np.ndarray) -> float:
    """How alike two pictures of one size are (brightness, -1..1): the drawn source has no colour tags."""
    return float(np.corrcoef(a.mean(axis=2).ravel(), b.mean(axis=2).ravel())[0, 1])


def _source_frames(video: Path, first: int, count: int) -> list[np.ndarray]:
    return [_frame(video, n, f"{W}:{H}") for n in range(first, first + count)]


# ------------------------------------------------------------------ Picture-in-picture
@needs_ffmpeg
@pytest.mark.parametrize("cam, corner", [(BOTTOM_LEFT, "left"), (TOP_RIGHT, "right")])
def test_picture_in_picture_puts_the_cam_in_a_box_over_the_filled_gameplay(tmp_path, monkeypatch, cam, corner):
    import cv2

    from clipfoundry import db
    from clipfoundry.pipeline import captions, facecam, quality, reframe

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    video = tmp_path / "stream.mp4"
    _stream(video, cam)
    project = _project(tmp_path, video)
    out = _render(project, {"layout": "pip"})
    info = out["render_info"]
    assert info["mode"] == "split" and info["layout"] == "pip" and info["pip_corner"] == corner
    assert "layout_asked" not in info and "split_game" not in info
    assert "Picture-in-picture" in quality.framing_checks(info)[0]["detail"]
    assert facecam.cam_check(info)["state"] == "found"
    split = info["framing_evidence"]["split"]
    view = reframe.pip_panels(split, W, H, corner)
    left, top, w, h = view["inset"]
    assert (left < 540) == (corner == "left") and top == round(1920 * reframe.PIP_TOP)
    assert w == 432 and 0.5 * w <= h <= 1920 * reframe.PIP_MAX_H
    # the exported frame: the cam's own picture in the box, a light frame around it, the gameplay everywhere else
    made = _frame(out["output_path"], 24)
    x, y, cw, ch = cam
    sources = _source_frames(video, 20, 12)
    cams = [cv2.resize(s[y:y + ch, x:x + cw], (w, round(w * ch / cw))) for s in sources]
    box = made[top:top + h, left:left + w]
    assert max(_alike(box, c[:h]) if c.shape[0] >= h else -1 for c in cams) > 0.8
    ring = made[top - view["border"]:top - 1, left:left + w]
    assert ring.mean() > 200                                 # the light frame
    fill_x, crop_w = split["fill_x"], reframe.crop_fraction(W, H)[0]
    assert (fill_x - crop_w / 2) * W >= x + cw or (fill_x + crop_w / 2) * W <= x   # the cam is not in the gameplay
    game = [cv2.resize(s[:, round((fill_x - crop_w / 2) * W):round((fill_x + crop_w / 2) * W)], (1080, 1920))
            for s in sources]
    below = slice(view["clear_top"] + 10, 1900)
    assert max(_alike(made[below], g[below]) for g in game) > 0.95
    # the headline and captions placed at the top start below the box
    ass = captions.build_ass([{"w": "hello", "start": 0.0, "end": 0.5}],
                             {"caption_position": "top", "clear_top": view["clear_top"], "hook_overlay": True},
                             2.0, "A headline")
    hook = next(line for line in ass.splitlines() if line.startswith("Style: Hook"))
    caption = next(line for line in ass.splitlines() if line.startswith("Style: Caption"))
    assert int(hook.split(",")[-2]) > view["clear_top"] and int(caption.split(",")[-2]) > view["clear_top"]
    # the other corner, asked for in the editor
    other = "right" if corner == "left" else "left"
    moved = _render(project, {"layout": "pip", "pip_corner": other}, "c2")["render_info"]
    assert moved["pip_corner"] == other


@needs_ffmpeg
def test_without_a_face_cam_the_cam_layouts_fall_back_and_say_so(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import facecam

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    video = tmp_path / "game.mp4"
    _stream(video, None)
    project = _project(tmp_path, video)
    for k, layout in enumerate(("pip", "split", "game")):
        info = _render(project, {"layout": layout}, f"c{k}")["render_info"]
        assert info["mode"] != "split" and info["layout"] == "fill" and info["layout_asked"] == layout
        check = facecam.cam_check(info)
        assert check["state"] == "none" and "draw its box" in check["text"]
    auto = _render(project, {"layout": "auto"}, "c9")["render_info"]
    assert facecam.cam_check(auto) is None   # nobody asked for a face cam: one picture is simply the clip


# ------------------------------------------------------------------ Gameplay only
def test_gameplay_only_moves_the_crop_off_a_cam_in_the_middle_only_as_far_as_it_may():
    from clipfoundry.pipeline import reframe

    crop = reframe.crop_fraction(W, H)[0]
    assert reframe.clear_of_cam([0.02, 0.6, 0.27, 0.93], crop) == 0.5          # a corner cam is already out
    near = reframe.clear_of_cam([0.2, 0.6, 0.36, 0.93], crop)                  # just inside the middle crop
    assert near - crop / 2 >= 0.36 and near - 0.5 <= reframe.PIP_SHIFT
    far = reframe.clear_of_cam([0.45, 0.6, 0.7, 0.93], crop)                   # right in the middle
    assert far == pytest.approx(0.5 - reframe.PIP_SHIFT)


@needs_ffmpeg
def test_gameplay_only_fills_the_frame_with_the_gameplay_and_leaves_the_cam_out(tmp_path, monkeypatch):
    import cv2

    from clipfoundry import db
    from clipfoundry.pipeline import quality, reframe

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    cam = (560, 440, 320, 240)   # a cam low in the middle: the middle crop would show half of it
    video = tmp_path / "stream.mp4"
    _stream(video, cam)
    project = _project(tmp_path, video)
    out = _render(project, {"layout": "game"})
    info = out["render_info"]
    assert info["mode"] == "split" and info["layout"] == "game"
    assert "Gameplay only" in quality.framing_checks(info)[0]["detail"]
    fill_x = info["framing_evidence"]["split"]["fill_x"]
    crop = reframe.crop_fraction(W, H)[0]
    assert fill_x == pytest.approx(0.5 - reframe.PIP_SHIFT)
    a, b = round((fill_x - crop / 2) * W), round((fill_x + crop / 2) * W)
    made = _frame(out["output_path"], 24)
    sources = _source_frames(video, 20, 12)
    assert max(_alike(made, cv2.resize(s[:, a:b], (1080, 1920))) for s in sources) > 0.95
    shown = max(0, b - cam[0]) / cam[2]
    assert shown < 0.5   # less of the cam than the middle crop would have shown (the shift is bounded)


# ------------------------------------------------------------------ a box you draw, or lock
def _faceless_stream(path: Path) -> tuple[int, int, int, int]:
    """A stream whose cam shows no face the detector can find (a cardboard cut-out): nothing is found by itself."""
    box = (900, 420, 320, 240)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    for index in range(FPS * SECONDS):
        frame = np.zeros((H, W, 3), np.uint8)
        _game(frame, index)
        x, y, w, h = box
        frame[y:y + h, x:x + w] = (30, 160, 230)
        frame[y + 40:y + 200, x + 100:x + 220] = (20, 40, 200 + index % 40)
        process.stdin.write(frame.tobytes())
    process.stdin.close()
    assert process.wait(timeout=60) == 0
    return box


@needs_ffmpeg
def test_a_cam_box_you_draw_is_used_for_that_clip_and_a_locked_one_for_every_clip(tmp_path, monkeypatch):
    import cv2

    from clipfoundry import db
    from clipfoundry.pipeline import facecam

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    video = tmp_path / "stream.mp4"
    x, y, w, h = _faceless_stream(video)
    project = _project(tmp_path, video)
    pdir = Path(project["dir"])
    assert _render(project, {"layout": "split"})["render_info"]["mode"] != "split"   # not found by itself
    drawn = [x / W, y / H, (x + w) / W, (y + h) / H]
    out = _render(project, {"layout": "split", "split_game": "zoom", "cam_box": drawn})
    info = out["render_info"]
    assert info["mode"] == "split" and info["framing_evidence"]["cam"]["kind"] == "manual"
    assert info["framing_evidence"]["split"]["cam"] == pytest.approx(drawn, abs=1e-4)
    assert facecam.cam_check(info) == {"state": "manual", "text": "The face cam is where you drew it."}
    top = info["framing_evidence"]["split"]["top"]
    made = _frame(out["output_path"], 24)
    panel = made[:int(1920 * top) // 2 * 2 - 6]
    cam_pic = _source_frames(video, 24, 1)[0][y:y + h, x:x + w]
    assert panel[..., 0].mean() < 60 and panel[..., 2].mean() > 150     # the orange cut-out fills the top
    assert _alike(cv2.resize(cam_pic, (1080, round(1080 * h / w)))[:panel.shape[0]], panel) > 0.6
    # another clip without a box of its own: nothing found, until the box is locked for the whole video
    assert _render(project, {"layout": "pip"}, "c2")["render_info"]["mode"] != "split"
    facecam.set_lock(pdir, drawn)
    locked = _render(project, {"layout": "pip"}, "c2")["render_info"]
    assert locked["mode"] == "split" and locked["layout"] == "pip"
    assert locked["framing_evidence"]["cam"]["kind"] == "manual"
    # what is found in a later clip never replaces a locked box; unlocking looks again
    assert facecam.found(pdir)["locked"] is True
    facecam.set_lock(pdir, None)
    assert facecam.found(pdir) is None
    assert _render(project, {"layout": "pip"}, "c2")["render_info"]["mode"] != "split"
    with pytest.raises(ValueError):
        facecam.clean_box([0.1, 0.1, 0.11, 0.5])   # too narrow to be a cam


# ------------------------------------------------------------------ a separate camera recording
RATE = 16000


def _clicks(seconds: float, seed: int) -> np.ndarray:
    """Sound with a pattern to line up by: short bursts at uneven times over quiet noise."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 200, int(seconds * RATE))
    t = 0.3
    while t < seconds - 0.2:
        a = int(t * RATE)
        x[a:a + 1600] += rng.normal(0, 9000, 1600) * np.hanning(1600)
        t += rng.uniform(0.25, 1.4)
    return np.clip(x, -32000, 32000).astype(np.int16)


def _wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(samples.tobytes())


def _video_with_sound(path: Path, frames, count: int, size: tuple[int, int], sound: Path) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "pipe:0", "-i", str(sound), "-c:v", "libx264",
               "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    for index in range(count):
        process.stdin.write(frames(index).tobytes())
    process.stdin.close()
    assert process.wait(timeout=120) == 0


@needs_ffmpeg
def test_a_separate_camera_is_lined_up_by_sound_and_shown_as_the_face_cam(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import facecam

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    late = 2.5   # the camera was started 2.5 s after the stream: camera time = video time - 2.5
    heard = _clicks(20.0, 7)
    _wav(tmp_path / "main.wav", heard)
    _wav(tmp_path / "cam.wav", heard[int(late * RATE):int((late + 14.0) * RATE)])
    video = tmp_path / "stream.mp4"

    def game(i):
        frame = np.zeros((H, W, 3), np.uint8)
        _game(frame, i)
        return frame

    def camera(i):   # the camera's picture gets one step brighter every second of its own time
        frame = np.zeros((360, 640, 3), np.uint8)
        _cam(frame, (0, 0, 640, 360), i, 0)
        frame[:40] = 30 + 15 * (i // FPS)
        return frame

    _video_with_sound(video, game, FPS * 20, (W, H), tmp_path / "main.wav")
    project = _project(tmp_path, video)
    pdir = Path(project["dir"])
    cam_file = pdir / "camera.mp4"
    _video_with_sound(cam_file, camera, FPS * 14, (640, 360), tmp_path / "cam.wav")
    rec = facecam.add_camera(pdir, cam_file, main_audio=video, name="facecam take 2.mp4")
    assert rec["synced"] == "sound" and rec["offset"] == pytest.approx(-late, abs=0.06) and rec["match"] > 0.3
    assert rec["name"] == "facecam take 2.mp4" and (rec["width"], rec["height"]) == (640, 360)

    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    clip = {"id": "c1", "start": 6.0, "end": 11.0, "hook": "", "edit": {"silence": "off", "layout": "split",
                                                                       "split_game": "zoom"}}
    out = render.render_clip(project, clip, [], _settings(), JobContext())
    info = out["render_info"]
    assert info["mode"] == "split" and info["framing_evidence"]["cam"]["kind"] == "camera"
    assert facecam.cam_check(info)["state"] == "camera"
    # the cam panel shows the camera's own picture at the matching moment: its brightness step says which second
    start = float(info["start"])
    for n in (12, 36, 48):   # half-way through a second of the camera's, away from its steps
        made = _frame(out["output_path"], n)
        band = made[2:30, 200:880].mean()
        cam_second = int(start + n / FPS - late)
        assert abs(band - (30 + 15 * cam_second)) < 7, (n, band, cam_second)
    # a camera with no sound in common is not lined up (the offset stays 0 and says so); the owner can type one
    _wav(tmp_path / "other.wav", _clicks(14.0, 99))
    other = pdir / "camera2.mp4"
    _video_with_sound(other, camera, FPS * 14, (640, 360), tmp_path / "other.wav")
    rec2 = facecam.add_camera(pdir, other, main_audio=video)
    assert rec2["synced"] == "none" and rec2["offset"] == 0.0
    rec3 = facecam.update_camera(pdir, offset=-2.5, box=[0.0, 0.0, 0.6, 1.0])
    assert rec3["synced"] == "you" and rec3["box"] == [0.0, 0.0, 0.6, 1.0]
    facecam.remove_camera(pdir)
    assert facecam.camera(pdir) is None and not other.exists()


# ------------------------------------------------------------------ the routes the clip editor uses
@needs_ffmpeg
def test_the_face_cam_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    folder = tmp_path / "p"
    folder.mkdir()
    video = folder / "source.mp4"
    _stream(video, BOTTOM_LEFT)
    project = db.create_project("stream", source_path=str(video), status="ready")
    clip = db.create_clip(project["id"], start=0.0, end=5.0, title="t", status="ready")
    base = f"/api/projects/{project['id']}"
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.get(f"{base}/facecam").json() == {"found": None, "camera": None}
        bad = c.put(f"{base}/facecam", json={"box": [0.1, 0.1, 0.105, 0.9]}, headers=H_)
        assert bad.status_code == 400 and "too small" in bad.json()["detail"]
        locked = c.put(f"{base}/facecam", json={"box": [0.02, 0.6, 0.28, 0.95]}, headers=H_).json()
        assert locked["found"] == {"box": [0.02, 0.6, 0.28, 0.95], "kind": "manual", "locked": True}
        assert c.put(f"{base}/facecam", json={"box": None}, headers=H_).json()["found"] is None
        # a clip's own box and corner
        r = c.patch(f"/api/clips/{clip['id']}", json={"edit": {"cam_box": [0.02, 0.6, 0.28, 0.95],
                                                                "pip_corner": "left", "layout": "pip"}}, headers=H_)
        assert r.status_code == 200 and r.json()["edit"] == {"cam_box": [0.02, 0.6, 0.28, 0.95],
                                                             "pip_corner": "left", "layout": "pip"}
        assert c.patch(f"/api/clips/{clip['id']}", json={"edit": {"cam_box": ["a", 1, 2, 3]}},
                       headers=H_).status_code == 400
        odd = c.patch(f"/api/clips/{clip['id']}", json={"edit": {"pip_corner": "middle"}}, headers=H_).json()
        assert odd["edit"]["pip_corner"] == "left"   # an unknown corner is ignored
        assert r.json()["cam_check"] is None          # not rendered yet
        # a separate camera recording: uploaded, lined up, adjusted, removed
        with open(video, "rb") as f:
            added = c.post(f"{base}/camera", files={"file": ("my cam.mp4", f, "video/mp4")}, data={"offset": "1.5"},
                           headers=H_).json()
        assert added["camera"]["name"] == "my cam.mp4" and added["camera"]["offset"] == 1.5
        assert added["camera"]["synced"] == "you"
        assert c.get(f"{base}/camera/video").status_code == 200
        moved = c.patch(f"{base}/camera", json={"offset": -0.75, "box": [0.0, 0.5, 0.3, 1.0]}, headers=H_).json()
        assert moved["camera"]["offset"] == -0.75 and moved["camera"]["box"] == [0.0, 0.5, 0.3, 1.0]
        assert c.patch(f"{base}/camera", json={"whole": True}, headers=H_).json()["camera"]["box"] is None
        with open(video, "rb") as f:
            text = c.post(f"{base}/camera", files={"file": ("notes.txt", f, "text/plain")}, headers=H_)
        assert text.status_code == 400
        assert c.delete(f"{base}/camera", headers=H_).json()["camera"] is None
        assert c.get(f"{base}/camera/video").status_code == 404
        assert c.patch(f"{base}/camera", json={"offset": 1}, headers=H_).status_code == 404
