"""Steadying shaky camera footage (pipeline/steady.py, batch 4d): what counts as shake, what is left alone, the
corrections in the clip renderer and in the full-video engine, and the setting everywhere it is read."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry import config
from clipfoundry.pipeline import render, steady
from clipfoundry.pipeline.common import JobContext

from synthetic_media import needs_ffmpeg

FPS = 30
W, H = 640, 360


def _scene(w: int, h: int, seed: int) -> np.ndarray:
    """A picture full of corners (shapes of every colour), larger than the frame so the camera can move over it."""
    import cv2

    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 60, np.uint8)
    for _ in range(int(w * h / 700)):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        c = tuple(int(v) for v in rng.integers(30, 255, 3))
        if rng.random() < 0.5:
            cv2.circle(img, (x, y), int(rng.integers(3, 18)), c, -1)
        else:
            cv2.rectangle(img, (x, y), (x + int(rng.integers(4, 30)), y + int(rng.integers(4, 30))), c, -1)
    return cv2.GaussianBlur(img, (3, 3), 0)


def _encode(path: Path, frames, w: int = W, h: int = H, fps: int = FPS) -> Path:
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                            f"{w}x{h}", "-r", str(fps), "-i", "pipe:0", "-c:v", "libx264", "-preset", "ultrafast",
                            "-crf", "16", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        enc.stdin.write(np.ascontiguousarray(f).tobytes())  # type: ignore[union-attr]
    enc.stdin.close()  # type: ignore[union-attr]
    assert enc.wait() == 0
    return path


def _camera(path: Path, seconds: float = 3.0, shake: float = 0.012, roll: float = 0.4, pan: float = 0.0,
            seed: int = 1, hud: bool = False, w: int = W, h: int = H, fps: int = FPS, sky: bool = False) -> Path:
    """A camera over a busy scene: hand shake (3 and 7 Hz, `shake` of the width; `roll` degrees), a pan (`pan`
    widths a second), with `hud`, a game's fixed HUD drawn over it (the same size in pixels at any `w`), and with
    `sky`, a plain sky over the top half (nothing to follow in the picture's top corners)."""
    import cv2

    big = _scene(int(w * 1.6), int(h * 1.6), seed)
    if sky:
        big[: big.shape[0] // 2] = (210, 170, 120)
    bh, bw = big.shape[:2]
    ph = np.random.default_rng(seed + 7).uniform(0, 6.28, 6)

    def frames():
        for k in range(int(seconds * fps)):
            t = k / fps
            jx = shake * w * (0.6 * math.sin(2 * math.pi * 3.1 * t + ph[0]) + 0.4 * math.sin(2 * math.pi * 7.3 * t))
            jy = shake * w * (0.6 * math.sin(2 * math.pi * 2.7 * t + ph[2]) + 0.4 * math.sin(2 * math.pi * 6.1 * t))
            ja = roll * math.sin(2 * math.pi * 2.3 * t + ph[4]) if shake else 0.0
            cx, cy = bw / 2 + pan * w * t + jx, bh / 2 + jy
            m = cv2.getRotationMatrix2D((cx, cy), ja, 1.0)
            m[0, 2] += w / 2 - cx
            m[1, 2] += h / 2 - cy
            f = cv2.warpAffine(big, m, (w, h), flags=cv2.INTER_LINEAR)
            if hud:
                cv2.rectangle(f, (10, 10), (150, 45), (20, 20, 20), -1)
                cv2.putText(f, "HP 100 AMMO 30", (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                cv2.rectangle(f, (w - 110, h - 110), (w - 10, h - 10), (40, 40, 40), -1)
                for i in range(12):
                    cv2.circle(f, (w - 100 + 8 * i, h - 60 + (i % 3) * 10), 3, (200, 200, 50), -1)
            yield f
    return _encode(path, frames(), w, h, fps)


def _person(path: Path, plain: bool, seconds: float = 3.0, bw: int = 210, bh: int = 280,
            top: float | None = None) -> Path:
    """A still camera; a busy 'person' (bw x bh, from `top`) sways and nods in front of a busy (or a plain) wall. A
    large one from near the top is a close-up: head and shoulders, cut off by the bottom of the picture."""
    import cv2

    wall = np.full((H, W, 3), 90, np.uint8) if plain else _scene(W, H, 3)
    body = _scene(bw, bh, 4)
    mask = np.zeros((bh, bw), np.uint8)
    cv2.ellipse(mask, (bw // 2, bh // 2), (bw // 2 - 5, bh // 2 - 5), 0, 0, 360, 255, -1)
    top = H / 2 - bh / 2 if top is None else top

    def frames():
        for k in range(int(seconds * FPS)):
            t = k / FPS
            x = int(W / 2 - bw / 2 + 20 * math.sin(2 * math.pi * 1.7 * t))
            y = int(top + 8 * math.sin(2 * math.pi * 3.3 * t))
            f = wall.copy()
            roi = f[y:y + bh, x:x + bw]
            m = mask[:roi.shape[0], :roi.shape[1]] > 0
            roi[m] = body[:roi.shape[0], :roi.shape[1]][m]
            yield f
    return _encode(path, frames())


def _shake(path: Path, seconds: float, t0: float = 0.0, size: tuple[int, int] = (W, H)) -> dict:
    """The first shot's measure (shake in % of the width, roll, why it was or was not steadied)."""
    return steady.plan(steady.measure(str(path), t0, seconds, FPS, size)).shots[0]


def _apply(src: Path, out: Path, p: steady.Plan) -> Path:
    import cv2

    cap = cv2.VideoCapture(str(src))

    def frames():
        k = 0
        while True:
            ok, f = cap.read()
            if not ok:
                return
            yield cv2.warpAffine(f, p.matrix(k, W, H), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            k += 1
    return _encode(out, frames())


@needs_ffmpeg
def test_shaky_camera_footage_is_found_and_steadied_without_showing_an_edge(tmp_path):
    src = _camera(tmp_path / "shaky.mp4")
    p = steady.plan(steady.measure(str(src), 0.0, 3.0, FPS, (W, H)))
    shot = p.shots[0]
    assert p.active and shot["steadied"] and shot["shake_pct"] > 0.5
    assert 1.0 < shot["zoom"] <= steady.MAX_ZOOM
    assert steady._inside(p.tx, p.ty, p.ta, p.zoom, p.aspect).all()  # noqa: SLF001
    after = _shake(_apply(src, tmp_path / "fixed.mp4", p), 2.9)
    assert after["shake_pct"] < 0.2 * shot["shake_pct"] and after["roll_deg"] < 0.1, after
    s = p.summary()
    assert s["seconds"] == pytest.approx(3.0, abs=0.05) and s["zoom"] == shot["zoom"] and s["shots"]
    # with a plain sky over the top half the shake is still the camera's: it holds hand tremor (a person's sway
    # in front of a plain wall does not, see below)
    sky = _shake(_camera(tmp_path / "sky.mp4", sky=True), 3.0)
    assert sky["steadied"] and sky["hand_share"] >= steady.HAND_SHARE, sky


@needs_ffmpeg
def test_footage_that_does_not_shake_is_left_exactly_as_it_is(tmp_path):
    cases = {"tripod": _camera(tmp_path / "tripod.mp4", shake=0.0, roll=0.0),
             "pan": _camera(tmp_path / "pan.mp4", shake=0.0, roll=0.0, pan=0.08),
             "person": _person(tmp_path / "person.mp4", plain=False),
             "person on a plain wall": _person(tmp_path / "plain.mp4", plain=True),
             "close-up on a plain wall": _person(tmp_path / "close.mp4", plain=True, bw=500, bh=640, top=30)}
    whys = {name: _shake(path, 3.0).get("why") for name, path in cases.items()}
    # on a plain wall the person is the only thing that moves: that is them, not the camera, even when they fill
    # half the picture (nothing moves with them in its corners)
    assert whys == {"tripod": "steady", "pan": "steady", "person": "steady",
                    "person on a plain wall": "not the camera", "close-up on a plain wall": "not the camera"}, whys
    for path in cases.values():
        assert steady.for_stretch(str(path), 0.0, 3.0, FPS, (W, H)) is None


@needs_ffmpeg
def test_a_game_s_hud_or_a_screen_s_toolbar_is_never_steadied(tmp_path):
    shot = _shake(_camera(tmp_path / "game.mp4", hud=True), 3.0)
    assert shot["shake_pct"] > 0.5 and not shot["steadied"] and shot["why"] == "fixed overlay"
    # a shake that is nearly all roll (the middle of the picture hardly moves; the HUD in its corners would)
    rolled = _shake(_camera(tmp_path / "rolled.mp4", shake=0.0001, roll=1.0, hud=True), 3.0)
    assert rolled["roll_deg"] > steady.SHAKY_ROLL and rolled["why"] == "fixed overlay", rolled
    # 60 fps (half the move from frame to frame) and a small HUD in a big picture (a point or two of 200)
    for hud in (False, True):
        src = _camera(tmp_path / f"fast{hud}.mp4", shake=0.005, roll=0.0, hud=hud, w=1280, h=720, fps=60)
        shot = steady.plan(steady.measure(str(src), 0.0, 3.0, 60, (1280, 720))).shots[0]
        assert shot["steadied"] is not hud and (shot.get("why") == "fixed overlay") is hud, (hud, shot)


def _track(shake: np.ndarray, t0: float = 10.0, still: float = 0.0) -> steady.Track:
    """A measured stretch whose camera moves by `shake` (its position, share of the width) and nothing stays put."""
    n = len(shake)
    move = np.diff(shake, prepend=shake[0])
    return steady.Track(t0, FPS, (480, 270), move, np.zeros(n), np.zeros(n), np.ones(n), np.full(n, still),
                        np.full(n, 0.9), [0], np.full(n, 4.0))


def test_only_the_part_the_clip_shows_decides_and_is_reported():
    t = np.arange(150) / FPS  # 10.0-15.0 s of the file
    hand = 0.006 * np.sin(2 * np.pi * 5 * t)
    p = steady.plan(_track(hand))
    assert p.active and p.summary()["seconds"] == pytest.approx(5.0, abs=0.05)
    shown = steady.plan(_track(hand), span=(10.5, 12.5))
    s = shown.summary()
    assert s["seconds"] == pytest.approx(2.0, abs=0.05) and s["shots"][0]["start_s"] == 10.5
    assert s["shots"][0]["end_s"] == 12.5
    # in the clip's own seconds: here it plays at double speed
    assert shown.summary(lambda x: (x - 10.5) / 2)["seconds"] == pytest.approx(1.0, abs=0.05)
    # a jolt after the clip's end neither steadies a calm clip nor enlarges it
    jolt = np.where(t > 4.0, 0.03 * np.sin(2 * np.pi * 6 * t), 0.0)  # (t: seconds from 10.0)
    assert steady.plan(_track(jolt)).active
    calm = steady.plan(_track(jolt), span=(10.0, 13.5))
    assert not calm.active and calm.shots[0]["why"] == "steady" and calm.crop_zoom() == 1.0
    # a shake with nothing measured to tell whether something stays put is left alone
    unknown = steady.plan(_track(hand, still=np.nan))
    assert not unknown.active and unknown.shots[0]["why"] == "cannot tell"
    # the framing found on the picture before it was enlarged lands where the enlargement put it
    z = float(p.zoom[40])
    assert p.framed(40, 0.8, 0.3) == pytest.approx((0.5 + 0.3 * z, 0.5 - 0.2 * z))


@needs_ffmpeg
def test_the_full_video_s_frames_are_the_file_s_own_at_any_start(tmp_path):
    """Frame k of an exact measurement is the file's frame nearest t0 + k / fps, also when t0 falls between two
    milliseconds (a seek rounded up drops a frame) and when the file has another frame rate."""
    for rate in (30, 25):
        src = tmp_path / f"count{rate}.mp4"
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s",
                                "64x36", "-r", str(rate), "-i", "pipe:0", "-c:v", "libx264", "-preset", "ultrafast",
                                "-qp", "0", str(src)], stdin=subprocess.PIPE)
        for k in range(70):
            enc.stdin.write(np.full((36, 64), 20 + 3 * k, np.uint8).tobytes())  # type: ignore[union-attr]
        enc.stdin.close()  # type: ignore[union-attr]
        assert enc.wait() == 0
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf", "format=gray", "-f", "rawvideo",
                              "-vsync", "passthrough", "pipe:1"], capture_output=True, check=True).stdout
        table = np.frombuffer(raw, np.uint8).reshape(-1, 36 * 64).mean(axis=1)  # each frame's own brightness
        for m in range(30, 45):
            t0 = m / FPS
            got = [int(np.argmin(np.abs(table - f.mean()))) for f in steady._frames(  # noqa: SLF001
                str(src), t0, 0.5, FPS, (64, 36), None, exact=True)]
            want = [int(round((t0 + k / FPS) * rate - 1e-6)) for k in range(len(got))]
            assert len(got) >= 14 and got == want, (rate, m, got, want)


@needs_ffmpeg
def test_a_pan_stays_while_the_shake_goes(tmp_path):
    src = _camera(tmp_path / "pan.mp4", pan=0.08)
    p = steady.plan(steady.measure(str(src), 0.0, 3.0, FPS, (W, H)))
    assert p.active
    out = _apply(src, tmp_path / "fixed.mp4", p)
    track = steady.measure(str(out), 0.0, 2.9, FPS, (W, H))
    pan = -0.08 / FPS  # the scene slides left as the camera pans right (share of the width per frame)
    assert float(np.mean(track.dx[1:])) == pytest.approx(pan, rel=0.15)
    assert steady.plan(track).shots[0]["shake_pct"] < 0.2


@needs_ffmpeg
def test_a_violent_shake_is_corrected_only_as_far_as_the_largest_zoom_allows(tmp_path):
    src = _camera(tmp_path / "violent.mp4", shake=0.04, roll=1.0)
    p = steady.plan(steady.measure(str(src), 0.0, 3.0, FPS, (W, H)))
    assert p.shots[0]["steadied"] and p.shots[0]["zoom"] == steady.MAX_ZOOM
    assert steady._inside(p.tx, p.ty, p.ta, p.zoom, p.aspect).all()  # noqa: SLF001


@needs_ffmpeg
def test_a_cut_starts_a_new_shot_and_only_the_shaky_one_is_steadied(tmp_path):
    a = _camera(tmp_path / "a.mp4", seconds=2.0, shake=0.0, roll=0.0, seed=11)
    b = _camera(tmp_path / "b.mp4", seconds=2.0, seed=12)
    joined = tmp_path / "joined.mp4"
    (tmp_path / "list.txt").write_text(f"file '{a}'\nfile '{b}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    str(tmp_path / "list.txt"), "-c", "copy", str(joined)], check=True)
    track = steady.measure(str(joined), 0.0, 4.0, FPS, (W, H))
    assert track.cuts == [0, 60]
    p = steady.plan(track)
    assert [s["steadied"] for s in p.shots] == [False, True]
    assert not any(p.moves(k) for k in range(60)) and all(p.moves(k) for k in range(60, 120))
    assert p.summary()["seconds"] == pytest.approx(2.0, abs=0.05)


@needs_ffmpeg
def test_a_clip_is_measured_whole_and_a_long_calm_stretch_only_sampled(tmp_path, monkeypatch):
    # a clip: a shaky insert between two tripod shots is found wherever it falls
    w, h = 320, 180
    parts = [_camera(tmp_path / "a.mp4", seconds=7.0, shake=0.0, roll=0.0, seed=21, w=w, h=h),
             _camera(tmp_path / "b.mp4", seconds=7.0, seed=22, w=w, h=h),
             _camera(tmp_path / "c.mp4", seconds=16.5, shake=0.0, roll=0.0, seed=23, w=w, h=h)]
    joined = tmp_path / "joined.mp4"
    (tmp_path / "list.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    str(tmp_path / "list.txt"), "-c", "copy", str(joined)], check=True)
    p = steady.for_stretch(str(joined), 0.0, 30.5, FPS, (w, h))
    assert p is not None and [s["steadied"] for s in p.shots] == [False, True, False]
    # a stretch longer than FULL_S (a long recording in a full video) is sampled first: PROBE_S every PROBE_EVERY_S
    monkeypatch.setattr(steady, "FULL_S", 20.0)
    src = tmp_path / "long.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=45",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    read = []
    real = steady.measure

    def counted(path, t0, length, fps, size, cancelled=None, exact=False):
        read.append(length)
        return real(path, t0, length, fps, size, cancelled, exact)
    monkeypatch.setattr(steady, "measure", counted)
    assert steady.for_stretch(str(src), 0.0, 45.0, FPS, (320, 180), cache=tmp_path / "cache") is None
    assert read == [steady.PROBE_S] * math.ceil(45 / steady.PROBE_EVERY_S)  # samples, not 45 s of picture
    assert steady.for_stretch(str(src), 0.0, 45.0, FPS, (320, 180), cache=tmp_path / "cache") is None
    assert len(read) == math.ceil(45 / steady.PROBE_EVERY_S)  # the second time from the cache


@needs_ffmpeg
def test_the_filter_graph_steadies_like_the_clip_renderer(tmp_path):
    """The full-video engine (rotate and crop driven by sendcmd, after an input seek) shows the same picture as the
    clip renderer's warp of the same frame."""
    import cv2

    from clipfoundry.studio import engine

    src = _camera(tmp_path / "shaky.mp4", seconds=4.0)
    p = steady.plan(steady.measure(str(src), 0.0, 4.0, FPS, (W, H)))
    assert p.active and p.rolls()
    seek, length = 1.0, 2.0
    lines: list[str] = []
    label = engine._steady_filters(p, seek, length, 0, "[0:v]", lines, tmp_path)  # noqa: SLF001
    lines.append(f"{label}scale={W}:{H}:flags=bicubic,setsar=1,format=bgr24[v]")
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{seek}", "-t", f"{length}", "-i", str(src),
                          "-filter_complex", ";".join(lines), "-map", "[v]", "-f", "rawvideo", "pipe:1"],
                         capture_output=True, cwd=tmp_path, check=True).stdout
    got = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float64)
    cap = cv2.VideoCapture(str(src))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    assert np.all(p.zoom == p.crop_zoom())  # one shot: the engine's window is the clip renderer's zoom
    for j in (0, 17, 45):
        k = int(round(seek * FPS)) + j
        want = cv2.warpAffine(frames[k], p.matrix(k, W, H), (W, H), flags=cv2.INTER_LINEAR).astype(np.float64)
        inner = (slice(20, H - 20), slice(20, W - 20))
        assert np.abs(got[j][inner] - want[inner]).mean() < 8, j


def test_steadying_is_a_setting_the_editors_full_cloud_and_requests_know():
    from clipfoundry import api
    from clipfoundry.fullcloud import worker_api
    from clipfoundry.pipeline import artifact
    from clipfoundry.studio import edit_requests, engine, video_flow

    assert config.DEFAULT_SETTINGS["stabilize"] is True
    assert config.validate_settings({"stabilize": "off"})["stabilize"] is False
    assert "stabilize" in api.EDIT_KEYS and "stabilize" in worker_api.SETTING_KEYS
    assert "stabilize" in artifact.SETTINGS_KEYS
    assert render.effective_options({**config.DEFAULT_SETTINGS}, {}, {"stabilize": False})["stabilize"] is False
    # full videos: new plans follow Settings; a plan made before steadying existed renders as it always did
    assert engine.default_color({})["steady"] is True and engine.default_color({"stabilize": False})["steady"] is False
    assert engine.steady_on({"color": engine.default_color({})})
    assert not engine.steady_on({"color": {"auto": True, "match": True, "look": "natural", "strength": 100,
                                           "clean": True}}) and not engine.steady_on({})
    assert any("steadying" in m for m in engine.validate({"color": {"steady": "yes"}, "clips": []}, {}))
    assert "steady" in engine.capabilities()["supported"]
    p = {"color": engine.default_color({}), "clips": [{"id": "c1", "label": "Clip 1"}]}
    assert video_flow._set_color(p, "steady_footage", False) == "Steadying shaky footage off"  # noqa: SLF001
    assert p["color"]["steady"] is False
    video_flow._clip_set(p, {"clip_id": "c1"}, "steady", False)  # noqa: SLF001
    assert p["clips"][0]["steady"] is False
    video_flow._clip_set(p, {"clip_id": "c1"}, "steady", True)  # noqa: SLF001
    assert "steady" not in p["clips"][0]
    # plain words: the whole video, or kept as shot; a shake added on purpose is not this
    on, off = {"color": {"steady": True}}, {"color": {"steady": False}}
    assert edit_requests._steady_rule("the footage is too shaky", off)[0] == [  # noqa: SLF001
        {"op": "set", "field": "steady_footage", "value": True}]
    assert edit_requests._steady_rule("keep the handheld shake", on)[0] == [  # noqa: SLF001
        {"op": "set", "field": "steady_footage", "value": False}]
    assert edit_requests._steady_rule("add a camera shake on the punchline", off) is None  # noqa: SLF001
    assert "steady_footage" in edit_requests.SETTABLE and "steady" in edit_requests.CLIP_FIELDS
    # a complaint about the shake wants it steadied; only a "no" said of the steadying itself keeps it
    wanted = {"i don't like how shaky the video is": True, "stop it from shaking": True,
              "don't let it wobble": True, "it's too shaky, never mind the zoom": True, "remove the shake": True,
              "turn off stabilization": False, "don't stabilize it": False, "i like the handheld shake": False,
              "keep the footage as it was shot, shaky": False}
    for text, want in wanted.items():
        assert edit_requests._steady_rule(text, off if want else on)[0] == [  # noqa: SLF001
            {"op": "set", "field": "steady_footage", "value": want}], text
    # "steady" said of something else, a handheld look, and requests that belong to other rules
    for text in ("add a slow steady zoom in on clip 2", "keep a steady pace", "give it a handheld look",
                 "make it look handheld", "slow down clip 2 to a steady half speed", "cut the shaky part at the start",
                 "remove the shaky clip 2"):
        assert edit_requests._steady_rule(text, on) is None and edit_requests._steady_rule(text, off) is None, text
    # the change is shown, so it can be applied (a proposal that changes nothing is never offered)
    clip = {"id": "c2", "asset_id": "a1", "label": "Clip 2", "in_ms": 0, "out_ms": 2000, "include": True}
    lines = edit_requests.changes({"color": {"steady": False}, "clips": [clip]},
                                  {"color": {"steady": True}, "clips": [{**clip, "steady": False}]})
    assert lines == ["Clip 1 “Clip 2”: kept as shot (not steadied)", "Steadying shaky footage on"], lines
    assert edit_requests.changes({"color": {}, "clips": []}, {"color": {"steady": True}, "clips": []}) == [
        "Steadying shaky footage on"]  # a plan made before steadying existed had it off
    # Settings reach new full videos through the editing choices (guidance), like the other colour switches
    from clipfoundry.studio import capabilities, guidance

    assert capabilities.FIELDS["stabilize"].kind == "bool"
    for value in (True, False):
        snap = guidance.resolve("full_video", settings={**config.DEFAULT_SETTINGS, "stabilize": value}, context={})
        assert engine.default_color(snap["values"])["steady"] is value


def _measure_output(path: Path, seconds: float) -> float:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    info = probe(path)
    return _shake(path, seconds, size=(int(info["width"]), int(info["height"])))["shake_pct"]


@needs_ffmpeg
@pytest.mark.slow
def test_a_real_shaky_clip_renders_steady(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.init()
    src = _camera(tmp_path / "src.mp4", seconds=4.0, w=1280, h=720)
    meta = probe(src)
    project = {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(tmp_path / "proj"),
               "info": meta, "options": {}, **meta}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast", "auto_zoom": False}
    out = {}
    for on in (True, False):
        clip = {"id": f"c{int(on)}", "start": 0.0, "end": 3.5, "hook": "",
                "edit": {"tracking": "center", "layout": "fill", "silence": "off", "loop_ending": False,
                         "captions_enabled": False, "stabilize": on}}
        out[on] = render.render_clip(project, clip, [], settings, JobContext())
    info = out[True]["render_info"]["steady"]
    assert info["seconds"] == pytest.approx(3.5, abs=0.05) and 1.0 < info["zoom"] <= steady.MAX_ZOOM  # the clip's
    assert "steady" not in out[False]["render_info"]
    shaky, steadied = _measure_output(Path(out[False]["output_path"]), 3.3), \
        _measure_output(Path(out[True]["output_path"]), 3.3)
    assert steadied < 0.3 * shaky, (steadied, shaky)


@needs_ffmpeg
@pytest.mark.slow
def test_a_full_video_steadies_its_shaky_clip_and_leaves_the_steady_one(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.studio import engine

    # 25 fps under a 30 fps video, read from a moment between two milliseconds (1.3667 s): every correction must
    # still land on its own frame
    shaky = _camera(tmp_path / "shaky.mp4", seconds=5.0, w=1280, h=720, fps=25)
    tripod = _camera(tmp_path / "tripod.mp4", seconds=4.0, shake=0.0, roll=0.0, seed=5, w=1280, h=720)
    assets = {p.stem: {"id": p.stem, "kind": "video", "filename": p.name, "path": str(p), "sha256": p.stem,
                       "probe": probe(p)} for p in (shaky, tripod)}

    def plan(color):
        clips = [{"id": "c1", "asset_id": "shaky", "label": "c1", "in_ms": 1367, "out_ms": 4367, "include": True,
                  "kind": "video"},
                 {"id": "c2", "asset_id": "tripod", "label": "c2", "in_ms": 500, "out_ms": 2500, "include": True,
                  "kind": "video"}]
        return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
                "output": {"aspect": "16:9", "fps": 30}, "layout": "fill", "clips": clips,
                "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
                "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
                "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": [],
                **({"color": color} if color else {})}

    still = {"auto": False, "match": False, "look": "natural", "strength": 100, "clean": False}
    on = engine.render(plan({**still, "steady": True}), assets, {}, tmp_path / "on" / "out.mp4")
    off = engine.render(plan({**still, "steady": False}), assets, {}, tmp_path / "off" / "out.mp4")
    old = engine.render(plan(None), assets, {}, tmp_path / "old" / "out.mp4")
    assert set(on["steady"]) == {"c1"} and on["steady"]["c1"]["seconds"] == pytest.approx(3.0, abs=0.05)
    assert off["steady"] == {} and old["steady"] == {}
    shaky_part = _measure_output(tmp_path / "off" / "out.mp4", 2.9)
    steadied_part = _measure_output(tmp_path / "on" / "out.mp4", 2.9)
    assert steadied_part < 0.3 * shaky_part, (steadied_part, shaky_part)
    # the steady clip is the same picture either way (not enlarged, not moved)
    a = steady.measure(str(tmp_path / "on" / "out.mp4"), 3.1, 1.8, FPS, (1280, 720))
    assert steady.plan(a).shots[-1]["why"] == "steady"
    assert engine.steadying_in_use(plan({**still, "steady": True}), assets, tmp_path / "on" / "pieces")
    assert not engine.steadying_in_use(plan({**still, "steady": False}), assets, tmp_path / "on" / "pieces")
