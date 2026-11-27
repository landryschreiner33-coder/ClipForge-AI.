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


def _encode(path: Path, frames, w: int = W, h: int = H) -> Path:
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s",
                            f"{w}x{h}", "-r", str(FPS), "-i", "pipe:0", "-c:v", "libx264", "-preset", "ultrafast",
                            "-crf", "16", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        enc.stdin.write(np.ascontiguousarray(f).tobytes())  # type: ignore[union-attr]
    enc.stdin.close()  # type: ignore[union-attr]
    assert enc.wait() == 0
    return path


def _camera(path: Path, seconds: float = 3.0, shake: float = 0.012, roll: float = 0.4, pan: float = 0.0,
            seed: int = 1, hud: bool = False, w: int = W, h: int = H) -> Path:
    """A camera over a busy scene: hand shake (3 and 7 Hz, `shake` of the width; `roll` degrees), a pan (`pan`
    widths a second) and, with `hud`, a game's fixed HUD drawn over it."""
    import cv2

    big = _scene(int(w * 1.6), int(h * 1.6), seed)
    bh, bw = big.shape[:2]
    ph = np.random.default_rng(seed + 7).uniform(0, 6.28, 6)

    def frames():
        for k in range(int(seconds * FPS)):
            t = k / FPS
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
    return _encode(path, frames(), w, h)


def _person(path: Path, plain: bool, seconds: float = 3.0) -> Path:
    """A still camera; a busy 'person' sways and nods in front of a busy (or a plain) wall."""
    import cv2

    wall = np.full((H, W, 3), 90, np.uint8) if plain else _scene(W, H, 3)
    body = _scene(210, 280, 4)
    mask = np.zeros((280, 210), np.uint8)
    cv2.ellipse(mask, (105, 140), (100, 135), 0, 0, 360, 255, -1)

    def frames():
        for k in range(int(seconds * FPS)):
            t = k / FPS
            x = int(W / 2 - 105 + 20 * math.sin(2 * math.pi * 1.7 * t))
            y = int(H / 2 - 140 + 8 * math.sin(2 * math.pi * 3.3 * t))
            f = wall.copy()
            roi = f[y:y + 280, x:x + 210]
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


@needs_ffmpeg
def test_footage_that_does_not_shake_is_left_exactly_as_it_is(tmp_path):
    cases = {"tripod": _camera(tmp_path / "tripod.mp4", shake=0.0, roll=0.0),
             "pan": _camera(tmp_path / "pan.mp4", shake=0.0, roll=0.0, pan=0.08),
             "person": _person(tmp_path / "person.mp4", plain=False),
             "person on a plain wall": _person(tmp_path / "plain.mp4", plain=True)}
    whys = {name: _shake(path, 3.0).get("why") for name, path in cases.items()}
    # the person on a plain wall is the only thing that moves: that is them, not the camera
    assert whys == {"tripod": "steady", "pan": "steady", "person": "steady",
                    "person on a plain wall": "not the camera"}, whys
    for path in cases.values():
        assert steady.for_stretch(str(path), 0.0, 3.0, FPS, (W, H)) is None


@needs_ffmpeg
def test_a_game_s_hud_or_a_screen_s_toolbar_is_never_steadied(tmp_path):
    shot = _shake(_camera(tmp_path / "game.mp4", hud=True), 3.0)
    assert shot["shake_pct"] > 0.5 and not shot["steadied"] and shot["why"] == "fixed overlay"


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
def test_a_long_calm_stretch_is_only_sampled_and_the_answer_is_kept(tmp_path, monkeypatch):
    src = tmp_path / "long.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={FPS}:d=45",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    read = []
    real = steady.measure

    def counted(path, t0, length, fps, size, cancelled=None):
        read.append(length)
        return real(path, t0, length, fps, size, cancelled)
    monkeypatch.setattr(steady, "measure", counted)
    assert steady.for_stretch(str(src), 0.0, 45.0, FPS, (320, 180), cache=tmp_path / "cache") is None
    assert read == [steady.PROBE_S] * 3  # three 2 s samples, not 45 s of picture
    assert steady.for_stretch(str(src), 0.0, 45.0, FPS, (320, 180), cache=tmp_path / "cache") is None
    assert len(read) == 3  # the second time from the cache


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
    assert info["seconds"] > 3.0 and 1.0 < info["zoom"] <= steady.MAX_ZOOM
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

    shaky = _camera(tmp_path / "shaky.mp4", seconds=5.0, w=1280, h=720)
    tripod = _camera(tmp_path / "tripod.mp4", seconds=4.0, shake=0.0, roll=0.0, seed=5, w=1280, h=720)
    assets = {p.stem: {"id": p.stem, "kind": "video", "filename": p.name, "path": str(p), "sha256": p.stem,
                       "probe": probe(p)} for p in (shaky, tripod)}

    def plan(color):
        clips = [{"id": "c1", "asset_id": "shaky", "label": "c1", "in_ms": 1000, "out_ms": 4000, "include": True,
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
    assert set(on["steady"]) == {"c1"} and on["steady"]["c1"]["seconds"] > 4.0
    assert off["steady"] == {} and old["steady"] == {}
    shaky_part = _measure_output(tmp_path / "off" / "out.mp4", 2.9)
    steadied_part = _measure_output(tmp_path / "on" / "out.mp4", 2.9)
    assert steadied_part < 0.3 * shaky_part, (steadied_part, shaky_part)
    # the steady clip is the same picture either way (not enlarged, not moved)
    a = steady.measure(str(tmp_path / "on" / "out.mp4"), 3.1, 1.8, FPS, (1280, 720))
    assert steady.plan(a).shots[-1]["why"] == "steady"
    assert engine.steadying_in_use(plan({**still, "steady": True}), assets, tmp_path / "on" / "pieces")
    assert not engine.steadying_in_use(plan({**still, "steady": False}), assets, tmp_path / "on" / "pieces")
