"""Split view: a stream's face cam on top and the rest of the picture below.

The pictures are drawn here and encoded with FFmpeg; the face is the repository's fixture and is found by the real
face detector, so the whole path from the encoded file to the plan is exercised."""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic_media import needs_ffmpeg

FACE = Path(__file__).parent / "fixtures" / "face.jpg"
W, H, FPS, SECONDS = 1280, 720, 12, 6


def _game(frame: np.ndarray, index: int) -> None:
    """A picture that keeps moving everywhere: bars and blocks sliding across a changing background."""
    height, width = frame.shape[:2]
    frame[:] = (40 + 30 * np.sin(index / 5.0), 60, 90 + 40 * np.cos(index / 7.0))
    for k in range(14):
        x = int((k * 137 + index * (9 + k % 5) * 3) % (width + 200)) - 100
        y = int((k * 71 + index * (4 + k % 3) * 2) % (height + 100)) - 50
        color = (int(60 + 13 * k) % 255, int(200 - 11 * k) % 255, int(90 + 29 * k) % 255)
        cv2.rectangle(frame, (x, y), (x + 90 + 12 * (k % 4), y + 60 + 9 * (k % 5)), color, -1)
        cv2.line(frame, (x - 40, y + 20), (x + 160, y - 30), (255 - color[0], 255, color[2]), 3)


def _cam(frame: np.ndarray, box: tuple[int, int, int, int], index: int, border: int) -> None:
    """A webcam picture: a room that stays still, with the fixture person (head and shoulders) swaying a little.
    The photo's own straight sides are lines inside the cam's picture, like a door frame behind the streamer."""
    x, y, w, h = box
    room = np.full((h, w, 3), (96, 104, 112), np.uint8)
    cv2.rectangle(room, (int(0.72 * w), int(0.1 * h)), (int(0.93 * w), int(0.5 * h)), (70, 80, 120), -1)  # a poster
    cv2.line(room, (0, int(0.86 * h)), (w, int(0.86 * h)), (60, 60, 60), 2)                                # a desk
    size = int(0.9 * h)
    person = cv2.resize(cv2.imread(str(FACE))[5:133, 49:177], (size, size), interpolation=cv2.INTER_CUBIC)
    px, py = int(0.1 * w) + int(round(1.5 * np.sin(index / 3.0))), h - size
    room[py:py + size, px:px + size] = person
    frame[y:y + h, x:x + w] = room
    if border:
        cv2.rectangle(frame, (x - border, y - border), (x + w + border - 1, y + h + border - 1), (255, 255, 255),
                      border)


def _stream(path: Path, cam: tuple[int, int, int, int] | None, *, border: int = 3, moving: bool = True,
            full_face: bool = False) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for index in range(FPS * SECONDS):
            frame = np.zeros((H, W, 3), np.uint8)
            if full_face:  # the camera's own picture: one person filling the frame
                _cam(frame, (0, 0, W, H), index, 0)
            else:
                _game(frame, index if moving else 0)
                if cam:
                    _cam(frame, cam, index, border)
            process.stdin.write(frame.tobytes())
    finally:
        process.stdin.close()
        assert process.wait(timeout=60) == 0


def _pixels(box: list[float]) -> list[int]:
    return [round(box[0] * W), round(box[1] * H), round(box[2] * W), round(box[3] * H)]


@needs_ffmpeg
@pytest.mark.parametrize("cam, border", [((30, 440, 320, 240), 3),     # a framed cam in the bottom-left corner
                                         ((960, 0, 320, 180), 0),      # flush in the top-right corner, no frame
                                         ((900, 420, 320, 240), 0)])   # no drawn frame, away from the edges
def test_face_cam_is_found_and_the_plan_is_a_split_view(tmp_path, cam, border):
    from clipfoundry.pipeline import reframe

    video = tmp_path / "stream.mp4"
    _stream(video, cam, border=border)
    plan = reframe.plan(str(video), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto")
    assert plan.mode == "split" and plan.info["layout"] == "split" and plan.info["cam"]["kind"] == "border"
    split = plan.info["split"]
    found, x, y, w, h = _pixels(split["cam"]), *cam
    assert max(abs(a - b) for a, b in zip(found, (x, y, x + w, y + h))) <= 8, (found, cam)
    assert reframe.SPLIT_TOP[0] <= split["top"] <= reframe.SPLIT_TOP[1]
    # the lower picture is moved away from the cam, so the cam is not shown twice
    cx, _, cw, _ = split["content"]
    centre = (x + w / 2) / W
    assert (cx > 0.5) == (centre < 0.5) and abs(cx - 0.5) <= reframe.SPLIT_SHIFT + 1e-6
    if centre < 0.5:
        assert cx - cw / 2 >= (x + w) / W or abs(cx - 0.5) == pytest.approx(reframe.SPLIT_SHIFT, abs=1e-4)
    assert np.allclose(plan.cx, cx) and plan.n == FPS * SECONDS
    # the same clip framed the old way is unchanged by the new code: one picture that follows the face
    old = reframe.plan(str(video), 0.0, float(SECONDS), W, H, "auto", float(FPS))
    assert old.mode == "face" and "layout" not in old.info


@needs_ffmpeg
def test_a_stream_without_a_cam_and_a_person_filling_the_frame_are_not_split(tmp_path):
    from clipfoundry.pipeline import reframe

    game = tmp_path / "game.mp4"
    _stream(game, None)
    plan = reframe.plan(str(game), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto")
    assert plan.mode == "motion" and plan.info["layout"] == "fill"
    person = tmp_path / "person.mp4"
    _stream(person, None, full_face=True)
    for layout in ("auto", "split"):  # even when split view is asked for: it would only show the same face twice
        plan = reframe.plan(str(person), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout=layout)
        assert plan.mode == "face" and plan.info["layout"] == "fill", layout


@needs_ffmpeg
def test_cam_over_a_still_picture_is_found_by_its_edges_and_a_centred_inset_is_not_a_cam(tmp_path):
    from clipfoundry.pipeline import reframe

    menu = tmp_path / "menu.mp4"
    _stream(menu, (30, 440, 320, 240), moving=False)
    a = reframe.analyze(str(menu), 0.0, float(SECONDS), W, H, layout=True)
    cam = reframe.find_cam(a)
    assert cam and cam["kind"] == "border"
    assert max(abs(p - q) for p, q in zip(_pixels(cam["box"]), (30, 440, 350, 680))) <= 8
    middle = tmp_path / "middle.mp4"
    _stream(middle, (480, 240, 320, 240), moving=False)
    a = reframe.analyze(str(middle), 0.0, float(SECONDS), W, H, layout=True)
    assert reframe.find_cam(a) is None            # a person in front of a window: the camera's own picture
    assert reframe.find_cam(a, force=True)        # the owner chose split view for this stream: it is taken


@needs_ffmpeg
def test_the_cam_found_earlier_stands_in_when_the_face_is_hidden(tmp_path, monkeypatch):
    from clipfoundry.pipeline import reframe

    video = tmp_path / "stream.mp4"
    _stream(video, (30, 440, 320, 240))
    first = reframe.plan(str(video), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto")
    hint = {"box": first.info["split"]["cam"], "face": [*first.info["split"]["focus"], 0.0, 0.0], "kind": "border"}
    monkeypatch.setattr(reframe, "_detector", lambda *_: None)   # the streamer leans out of the picture
    assert reframe.plan(str(video), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto").mode == "motion"
    again = reframe.plan(str(video), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto", cam_hint=hint)
    assert again.mode == "split" and again.info["cam"]["from"] == "earlier"
    assert again.info["split"]["cam"] == first.info["split"]["cam"]
    # ... but not when the stream no longer has a cam there
    game = tmp_path / "game.mp4"
    _stream(game, None)
    assert reframe.plan(str(game), 0.0, float(SECONDS), W, H, "auto", float(FPS), layout="auto",
                        cam_hint=hint).mode == "motion"


def test_split_picture_puts_the_cam_on_top_and_the_rest_below(monkeypatch):
    from clipfoundry.pipeline import reframe, render

    monkeypatch.setattr(render, "OUTPUT_W", 180)
    monkeypatch.setattr(render, "OUTPUT_H", 320)
    frame = np.zeros((360, 640, 3), np.uint8)
    frame[:, :] = (200, 0, 0)                 # the game: blue
    frame[240:340, 20:160] = (0, 0, 200)      # the cam: red
    cam = {"box": [20 / 640, 240 / 360, 160 / 640, 340 / 360], "face": [90 / 640, 280 / 360, 0.05, 0.1]}
    split = reframe.split_layout(cam, 640, 360)
    out = render._compose(frame, split["content"][0], 0.5, 1.0, 640, 360, 0.0, 0.0, "split", 1.0, split)
    assert out.shape == (320, 180, 3) and out.dtype == np.uint8 and out.flags["C_CONTIGUOUS"]
    seam = int(round(320 * split["top"])) // 2 * 2
    top, low = out[:seam - 4], out[seam + 4:]
    assert top[..., 2].mean() > 190 and top[..., 0].mean() < 10      # only the cam
    assert low[..., 0].mean() > 190 and low[..., 2].mean() < 10      # none of it below
    assert out[seam - 1:seam + 1].max() < 40                         # a dark line between the two
    zoomed = render._compose(frame, split["content"][0], 0.5, 1.5, 640, 360, 0.0, 0.0, "split", 1.0, split)
    assert np.array_equal(zoomed[:seam - 4], top)                    # a zoom never moves the face


def test_split_view_captions_sit_on_the_line_and_the_headline_goes_under_it():
    from clipfoundry.pipeline import captions

    words = [{"w": w, "start": 0.3 * k, "end": 0.3 * k + 0.25} for k, w in enumerate("one two three four".split())]
    words += [{"w": w, "start": 4.0 + 0.3 * k, "end": 4.25 + 0.3 * k} for k, w in enumerate("five six".split())]
    opts = {"caption_style": "bold", "caption_position": "bottom", "hook_overlay": True, "hook_seconds": 3.0}
    seam = int(captions.OUTPUT_H * 0.36)
    ass = captions.build_ass(words, {**opts, "picture_seam": 0.36}, 6.0, "The headline")
    hook_style = next(line for line in ass.splitlines() if line.startswith("Style: Hook"))
    assert hook_style.split(",")[-2] == str(seam + captions.SEAM_HOOK_GAP)   # under the line, off the face
    spoken = [line for line in ass.splitlines() if line.startswith("Dialogue: 1")]
    early = [line for line in spoken if line.split(",")[1] < "0:00:03.00"]
    late = [line for line in spoken if line.split(",")[1] >= "0:00:03.00"]
    assert early and late
    under = int(captions.hook_bottom("The headline", seam + captions.SEAM_HOOK_GAP) + captions.HOOK_GAP)
    assert all(f"\\an8\\pos(540,{under})" in line for line in early)          # below the headline while it shows
    assert all(f"\\an5\\pos(540,{seam})" in line for line in late)            # then centred on the line
    # the owner's own caption place is kept, and nothing changes without a split view
    top = captions.build_ass(words, {**opts, "caption_position": "top", "picture_seam": 0.36}, 6.0, "")
    assert "\\pos(" not in top
    plain = captions.build_ass(words, opts, 6.0, "The headline")
    assert "\\pos(" not in plain and plain == captions.build_ass(words, {**opts, "picture_seam": None}, 6.0,
                                                                  "The headline")


def test_split_view_passes_the_framing_check_and_is_a_clip_only_layout():
    from clipfoundry import config
    from clipfoundry.pipeline import blueprint, quality
    from clipfoundry.studio import capabilities

    info = {"crop_w": 0.316, "mode": "split", "layout": "split", "faces": 1,
            "framing_evidence": {"cam": {"kind": "border", "score": 0.9}}}
    check = quality.framing_checks(info)[0]
    assert check["status"] == quality.PASS and "Split view" in check["detail"] and "estimate" in check["detail"]
    # Settings, saved styles and the full-video editor keep their two layouts
    assert config.LAYOUTS == ["fill", "fit"] and set(config.CLIP_LAYOUTS) == {"fill", "fit", "auto", "split"}
    assert "layout" not in config.validate_settings({"layout": "split"})
    assert capabilities.FIELDS["layout"].choices == ("fill", "fit")
    bp = blueprint.Blueprint(clip_id="c", project_id="p", source_id="", input_hash="h",
                             intervals=[blueprint.Interval(0.0, 20.0)])
    for layout in config.CLIP_LAYOUTS:
        bp.framing.layout = layout
        assert not [e for e in blueprint.errors(blueprint.validate(bp, None, [])) if "layout" in e], layout
    bp.framing.layout = "sideways"
    assert any("layout" in e for e in blueprint.errors(blueprint.validate(bp, None, [])))
