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
    # captions placed at the top would cover the face cam: they go on the line too; the middle stays the middle
    top = captions.build_ass(words, {**opts, "caption_position": "top", "picture_seam": 0.36}, 6.0, "")
    assert all(f"\\an5\\pos(540,{seam})" in line for line in top.splitlines() if line.startswith("Dialogue: 1"))
    middle = captions.build_ass(words, {**opts, "caption_position": "middle", "picture_seam": 0.36}, 6.0, "")
    assert "\\pos(" not in middle
    # nothing changes without a split view
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


# ------------------------------------------------------------------ the whole picture under the cam
CAM_16_9 = {"box": [0.02, 0.6, 0.27, 0.6 + 0.25], "face": [0.14, 0.7, 0.05, 0.1]}       # 320x180 on 1280x720
CAM_4_3 = {"box": [0.02, 0.6, 0.27, 0.6 + 0.25 * 16 / 9 * 0.75], "face": [0.14, 0.72, 0.05, 0.1]}


@pytest.mark.parametrize("cam, size", [(CAM_16_9, (1280, 720)), (CAM_4_3, (1280, 720)), (CAM_4_3, (1440, 1080)),
                                       (CAM_16_9, (1080, 1080)), (CAM_16_9, (720, 1280))])
def test_whole_split_view_keeps_all_of_the_picture_under_the_cam(cam, size):
    from clipfoundry.pipeline import reframe

    width, height = size
    split = reframe.split_layout(cam, width, height)
    view = reframe.split_panels(split, width, height, "whole")
    (cam_y, cam_h), (px, py, pw, ph) = view["cam"], view["picture"]
    assert view["game"] == "whole"
    # all of the picture, in its own shape, as large as the frame allows
    assert abs(pw / ph - width / height) < 0.01
    assert pw == 1080 or py + ph >= 1918
    assert px == (1080 - pw) // 2 and 0 <= px
    # the cam, then the captions' strip, then the picture: nothing overlaps and nothing leaves the frame
    assert 0 <= cam_y and cam_y + cam_h <= py and py + ph <= 1920
    assert reframe.SPLIT_WHOLE_TOP[0] <= cam_h / 1920 <= reframe.SPLIT_WHOLE_TOP[1] + 0.001
    band = py - (cam_y + cam_h)
    assert band <= int(1920 * reframe.SPLIT_BAND)
    assert view["seam"] == cam_y + cam_h + band / 2          # the captions' line is the middle of that strip
    # what is left over goes mostly below the picture, where the phone apps draw over the video anyway
    assert cam_y <= 1920 - (py + ph) and cam_y <= 1920 * reframe.SPLIT_HEAD[1]
    if size == (1280, 720):
        assert (pw, ph) == (1080, 608) and band == int(1920 * reframe.SPLIT_BAND)
        assert cam_y + cam_h + 4 <= view["hook"] <= cam_y + cam_h + band // 4   # a headline starts in the strip
    # the zoomed split view is the picture it always was: cam on top, the rest filling everything below
    zoom = reframe.split_panels(split, width, height, "zoom")
    top = int(round(1920 * split["top"])) // 2 * 2
    assert zoom == {"game": "zoom", "cam": (0, top), "picture": (0, top, 1080, 1920 - top), "seam": top,
                    "hook": None}


def test_whole_split_picture_shows_every_corner_of_the_game(monkeypatch):
    from clipfoundry.pipeline import reframe, render

    monkeypatch.setattr(render, "OUTPUT_W", 180)
    monkeypatch.setattr(render, "OUTPUT_H", 320)
    frame = np.zeros((360, 640, 3), np.uint8)
    frame[:, :] = (200, 0, 0)                 # the game: blue
    frame[:40, :40] = frame[:40, -40:] = frame[-40:, :40] = frame[-40:, -40:] = (0, 200, 0)   # its corners: green
    frame[220:320, 60:200] = (0, 0, 200)      # the cam: red
    cam = {"box": [60 / 640, 220 / 360, 200 / 640, 320 / 360], "face": [130 / 640, 260 / 360, 0.05, 0.1]}
    split = reframe.split_layout(cam, 640, 360)
    split["view"] = reframe.split_panels(split, 640, 360, "whole", 180, 320)
    out = render._compose(frame, split["content"][0], 0.5, 1.0, 640, 360, 0.0, 0.0, "split", 1.0, split)
    assert out.shape == (320, 180, 3) and out.dtype == np.uint8 and out.flags["C_CONTIGUOUS"]
    (cam_y, cam_h), (px, py, pw, ph) = split["view"]["cam"], split["view"]["picture"]
    top = out[cam_y + 2:cam_y + cam_h - 2]
    assert top[..., 2].mean() > 190 and top[..., 0].mean() < 10            # the cam panel holds only the cam
    picture = out[py:py + ph, px:px + pw]
    assert (pw, ph) == (180, 100)                                          # 640x360 as wide as the output
    for ys, xs in ((slice(0, 6), slice(0, 6)), (slice(0, 6), slice(-6, None)),
                   (slice(-6, None), slice(0, 6)), (slice(-6, None), slice(-6, None))):
        corner = picture[ys, xs].reshape(-1, 3).mean(axis=0)
        assert corner[1] > 150 and corner[0] < 60, corner                  # all four corners are in view
    assert picture[45:55, 80:100, 0].mean() > 190                          # and the middle of the game
    # between and around the two: the blurred, darkened fill, never a bare black bar
    strip = out[cam_y + cam_h + 2:py - 2]
    assert strip.size and 20 < strip.mean() < 120
    assert out[py + ph + 4:].mean() > 20
    zoomed = render._compose(frame, split["content"][0], 0.5, 1.5, 640, 360, 0.0, 0.0, "split", 1.0, split)
    assert np.array_equal(zoomed[:py], out[:py])                           # a zoom moves neither the cam nor the strip
    assert zoomed[py:py + 6, px:px + 6, 1].mean() < 60                     # ... it moves in on the picture's middle


def test_whole_split_view_headline_starts_in_the_strip_between_the_pictures():
    from clipfoundry.pipeline import captions

    words = [{"w": w, "start": 0.3 * k, "end": 0.3 * k + 0.25} for k, w in enumerate("one two three four".split())]
    words += [{"w": w, "start": 4.0 + 0.3 * k, "end": 4.25 + 0.3 * k} for k, w in enumerate("five six".split())]
    opts = {"caption_style": "bold", "caption_position": "bottom", "hook_overlay": True, "hook_seconds": 3.0,
            "picture_seam": 950 / captions.OUTPUT_H, "seam_hook_top": 856}
    ass = captions.build_ass(words, opts, 6.0, "The headline")
    hook_style = next(line for line in ass.splitlines() if line.startswith("Style: Hook"))
    assert hook_style.split(",")[-2] == "856"
    late = [line for line in ass.splitlines() if line.startswith("Dialogue: 1") and line.split(",")[1] >= "0:00:03.00"]
    assert late and all("\\an5\\pos(540,950)" in line for line in late)    # the captions: the middle of the strip


def test_a_layout_nobody_chose_looks_for_a_face_cam(monkeypatch, tmp_path):
    from clipfoundry import config, db
    from clipfoundry.pipeline import blueprint, render

    assert config.DEFAULT_SETTINGS["split_view"] == "auto" and config.DEFAULT_SETTINGS["split_game"] == "whole"
    assert config.validate_settings({"split_view": "always", "split_game": "tiny"}) == {}
    assert config.validate_settings({"split_view": "off", "split_game": "zoom"}) == {"split_view": "off",
                                                                                      "split_game": "zoom"}
    on = {"layout": "fit", "split_view": "auto"}
    assert render.cam_layout(on, chosen=False) == "auto"
    assert render.cam_layout(on, chosen=True) == "fit"                      # a layout somebody chose stays
    assert render.cam_layout({"layout": "fit", "split_view": "off"}, chosen=False) == "fit"
    assert render.cam_layout({"layout": "fit"}, chosen=False) == "fit"      # settings from before this choice
    assert render.cam_layout({"layout": "split", "split_view": "off"}, chosen=True) == "split"
    # a clip rendered before keeps whether it looked for a face cam, whatever Settings say now: a re-render (a
    # caption fix, a version) gives the look the editor shows, and a clip made before split view existed stays so
    assert render.cam_layout(on, chosen=False, rendered={"layout": "fit"}) == "fit"
    assert render.cam_layout({"layout": "fill", "split_view": "off"}, chosen=False,
                             rendered={"layout": "fill", "layout_asked": "auto"}) == "auto"
    assert render.cam_layout(on, chosen=False, rendered={}) == "auto"       # never rendered: Settings decide
    # who counts as having chosen
    plain = {"options": {}}
    assert not render.layout_chosen(plain, {"edit": {}})
    assert render.layout_chosen(plain, {"edit": {"layout": "fill"}})        # the clip's own editor
    assert render.layout_chosen(plain, {"edit": {"tracking": "center"}})    # ... also when it places the crop
    assert not render.layout_chosen(plain, {"edit": {"tracking": "auto"}})
    assert render.layout_chosen({"options": {"layout": "fit"}}, {"edit": {}})
    assert render.layout_chosen(plain, {"edit": {}}, blueprint=object())    # the plan decided when it was written

    def guided(level):
        return {"options": {"layout": "fill"}, "guidance": {"schema": 1, "decisions": [
            {"field": "layout", "value": "fill", "from": {"level": level}}]}}

    assert not render.layout_chosen(guided("settings"), {"edit": {}})       # only repeats the Settings layout
    for level in ("project", "style", "skill", "brain", "story", "reference"):
        assert render.layout_chosen(guided(level), {"edit": {}}), level
    # the plan of an Autopilot clip asks for the look when nobody chose a layout for the video
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    words = [{"w": w, "start": 0.2 + k * 0.5, "end": 0.6 + k * 0.5} for k, w in enumerate("a b c d e f g h".split())]

    def planned(options, **settings):
        project = db.create_project("A stream", origin="autopilot", duration=6, options=options)
        clip = db.create_clip(project["id"], start=0, end=5, duration=5, title="t", caption_text="a b c")
        return blueprint.build(clip, project, words, {**db.get_settings(), **settings}).framing.layout

    assert planned({}) == "auto"
    assert planned({}, split_view="off") == "fill"
    assert planned({}, layout="fit", split_view="off") == "fit"
    assert planned({"layout": "fit"}) == "fit"                              # chosen for this video
    assert planned({"layout": "split"}) == "split"                          # a live stream's "always"
    assert planned({"split_view": "off"}) == "fill"                         # a live stream's "no split view"
    # the plan keeps the layout without a face cam and the look under it, so a re-render after the Settings
    # changed looks the same
    project = db.create_project("A stream", origin="autopilot", duration=6, options={})
    clip = db.create_clip(project["id"], start=0, end=5, duration=5, title="t", caption_text="a b c")
    bp = blueprint.build(clip, project, words, {**db.get_settings(), "layout": "fit", "split_game": "zoom"})
    assert (bp.framing.layout, bp.framing.fallback, bp.framing.game) == ("auto", "fit", "zoom")
    assert blueprint.render_options(bp)["layout_fallback"] == "fit"
    assert blueprint.render_options(bp)["split_game"] == "zoom"
    assert blueprint.with_edit(bp, {"split_game": "whole"}).framing.game == "whole"   # the editor's choice
    plain = blueprint.build(clip, project, words, {**db.get_settings(), "split_view": "off"})
    assert plain.framing.fallback is plain.framing.game is None
    assert "layout_fallback" not in blueprint.render_options(plain)
    stored = blueprint.Blueprint.from_dict(bp.to_dict())
    assert stored.framing == bp.framing and not stored.unsupported
    wrong = blueprint.Blueprint.from_dict({**bp.to_dict(), "framing": {**bp.to_dict()["framing"], "game": "tiny"}})
    assert blueprint.errors(blueprint.validate(wrong, 6.0, words))
    assert blueprint.errors(blueprint.validate(blueprint.Blueprint(
        clip_id="c", project_id="p", source_id="", input_hash="h", intervals=[blueprint.Interval(0.0, 5.0)],
        framing=blueprint.Framing(layout="auto")), 6.0, words)) == []


@needs_ffmpeg
def test_a_stream_with_a_face_cam_renders_as_a_whole_split_view_by_default(monkeypatch, tmp_path):
    """The real path: a drawn stream, the default Settings, nobody choosing a layout."""
    from clipfoundry import config, db
    from clipfoundry.pipeline import quality, reframe, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    video = tmp_path / "stream.mp4"
    _stream(video, (30, 440, 320, 240))
    meta = probe(video)
    project = {"id": "p1", "name": "stream", "source_path": str(video), "dir": str(tmp_path / "proj"), "info": meta,
               "options": {}, **meta}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast", "normalize_audio": False}
    clip = {"id": "c1", "start": 0.0, "end": 5.5, "hook": "", "edit": {"silence": "off"}}
    out = render.render_clip(project, clip, [], settings, JobContext())
    info = out["render_info"]
    assert info["mode"] == "split" and info["layout"] == "split" and info["layout_asked"] == "auto"
    assert info["split_game"] == "whole"
    check = quality.framing_checks(info)[0]
    assert check["status"] == quality.PASS and "the whole picture" in check["detail"]
    # the picture strip is the stream itself, whole: the same frame of the source, scaled to the strip's size
    view = reframe.split_panels(info["framing_evidence"]["split"], W, H, "whole")
    px, py, pw, ph = view["picture"]
    assert (px, pw, ph) == (0, 1080, 608) and view["cam"][0] + view["cam"][1] < py

    def frames(path, scale, first, count):
        width, height = (int(v) for v in scale.split(":"))
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
                              f"select=between(n\\,{first}\\,{first + count - 1}),scale={scale}", "-vsync", "0",
                              "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3).astype(np.int16)

    def alike(a, b):   # brightness only: the drawn source carries no colour tags, so its colours decode a shade off
        return float(np.corrcoef(a.mean(axis=2).ravel(), b.mean(axis=2).ravel())[0, 1])

    # the clip's start may have moved onto a detected cut, so its frame 24 is one of the source's frames near there
    made, sources = frames(out["output_path"], "1080:1920", 24, 1)[0], frames(video, "1080:608", 20, 16)
    assert max(alike(made[py:py + ph], source) for source in sources) > 0.97   # the same picture, every part of it
    assert max(alike(made[py - 300:py - 300 + ph], source) for source in sources) < 0.5   # and nowhere else
    # the same stream with the zoomed split view chosen for this clip, and with a layout chosen for it
    zoom = render.render_clip(project, {**clip, "id": "c2", "edit": {"silence": "off", "split_game": "zoom"}}, [],
                              settings, JobContext())["render_info"]
    assert zoom["mode"] == "split" and zoom["split_game"] == "zoom"
    fill = render.render_clip(project, {**clip, "id": "c3", "edit": {"silence": "off", "layout": "fill"}}, [],
                              settings, JobContext())["render_info"]
    assert fill["mode"] != "split" and fill["layout"] == "fill" and "layout_asked" not in fill
    off = render.render_clip(project, {**clip, "id": "c4"}, [], {**settings, "split_view": "off"},
                             JobContext())["render_info"]
    assert off["mode"] != "split" and off["layout"] == "fill"
    # a re-render keeps the look the clip was made with, after Settings → Split view changed either way
    again = render.render_clip(project, {**clip, "id": "c4", "render_info": off, "edit": {"silence": "off",
                                                                                          "hook": "New words"}},
                               [], settings, JobContext())["render_info"]
    assert again["mode"] != "split" and again["layout"] == "fill"
    kept = render.render_clip(project, {**clip, "render_info": info}, [], {**settings, "split_view": "off"},
                              JobContext())["render_info"]
    assert kept["mode"] == "split" and kept["layout_asked"] == "auto"
    # framing the picture by hand (Framing in the editor) gives one picture, with a plan and without one alike;
    # the plan's own layout without a face cam is used, not the one Settings have now
    by_hand = {"silence": "off", "tracking": "manual", "crop_x": 0.2}
    manual = render.render_clip(project, {**clip, "id": "c5", "edit": by_hand}, [], settings,
                                JobContext())["render_info"]
    assert manual["mode"] == "manual" and manual["layout"] == "fill"
    from clipfoundry.pipeline import blueprint

    plan = blueprint.Blueprint(clip_id="c6", project_id="p1", source_id="", input_hash="h",
                               intervals=[blueprint.Interval(0.0, 5.5)],
                               framing=blueprint.Framing(layout="auto", fallback="fit", game="whole"))
    planned = render.render_clip(project, {**clip, "id": "c6", "edit": by_hand}, [], settings, JobContext(),
                                 blueprint=blueprint.with_edit(plan, by_hand))["render_info"]
    assert planned["mode"] == "manual" and planned["layout"] == "fit"
