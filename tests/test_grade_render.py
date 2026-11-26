"""Colour in real renders (slow, real FFmpeg): a full video with a blue-cast recording and a phone HDR (HLG) recording
comes out as tagged BT.709 with the cast reduced and the HDR picture converted the same way as the colour math; a
plan made before colour existed only converts the HDR; a look re-renders only the pieces it changes; a short clip
gets the same correction.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from test_grade import H, W, _encode, _grey_cast, _scene

pytestmark = pytest.mark.slow


def _with_sound(video: Path, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=3", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


def _hlg(path: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=3", "-vf",
                    "format=yuv420p10le", "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-crf", "8",
                    "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def _asset(path: Path) -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    return {"id": path.stem, "kind": "video", "filename": path.name, "path": str(path), "sha256": path.stem,
            "probe": probe(path)}


def _plan(color: dict | None) -> dict:
    from clipfoundry.studio import engine

    clips = [{"id": "c1", "asset_id": "blue", "kind": "video", "in_ms": 0, "out_ms": 2000, "label": "blue",
              "gain_db": 0.0, "include": True},
             {"id": "c2", "asset_id": "hdr", "kind": "video", "in_ms": 0, "out_ms": 2000, "label": "hdr",
              "gain_db": 0.0, "include": True}]
    plan = {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "16:9", "fps": 30}, "layout": "fit", "clips": clips,
            "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
            "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": []}
    if color is not None:
        plan["color"] = color
    return plan


def _frame_at(path: Path, t: float, w: int, h: int) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                                   "-vf", f"scale={w}:{h}:in_color_matrix=bt709:in_range=tv,format=gbrp16le,"
                                   "format=rgb48le", "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"])
    return np.frombuffer(raw, "<u2").reshape(h, w, 3) / 65535.0


def test_full_video_colour_hdr_cast_old_plans_and_looks(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline import grade
    from clipfoundry.studio import engine

    blue = _with_sound(_encode(_scene((0.85, 1.0, 1.2)), tmp_path / "blue_raw.mp4", 3.0), tmp_path / "blue.mp4")
    hdr = _hlg(tmp_path / "hdr.mp4")
    assets = {"blue": _asset(blue), "hdr": _asset(hdr)}
    plan = _plan(engine.default_color({}))
    assert engine.validate(plan, assets) == []
    out = tmp_path / "r" / "final.mp4"
    info = engine.render(plan, assets, {}, out, cache_dir=tmp_path / "pieces")
    tags = grade.source_colour(out)
    assert (tags["transfer"], tags["primaries"], tags["matrix"]) == ("bt709", "bt709", "bt709")
    assert info["colour"]["blue"]["corrected"] and any("White balance" in n for n in info["colour"]["blue"]["notes"])
    assert info["colour"]["hdr"]["hdr"] == "hlg"
    w, h = info["width"], info["height"]
    # the cast recording: its grey blocks are much closer to grey than in the original
    src = _frame_at(blue, 1.0, w, h)
    got = _frame_at(out, 1.0, w, h)
    assert _grey_cast(got) < 0.6 * _grey_cast(src)
    # the HDR recording: the same average colour as the colour math on its own pixels (fit: same picture, scaled)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(hdr), "-frames:v", "1", "-vf",
                                   f"scale={w}:{h}:in_color_matrix=bt2020:in_range=tv,format=gbrp16le,format=rgb48le",
                                   "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"])
    hdr_px = np.frombuffer(raw, "<u2").reshape(-1, 3) / 65535.0
    looks = engine.grades(plan, assets, tmp_path / "pieces")
    want = grade.apply(hdr_px, looks["hdr"]["grade"]).mean(axis=0)
    assert np.abs(_frame_at(out, 3.0, w, h).reshape(-1, 3).mean(axis=0) - want).max() * 255 < 3

    # a plan made before colour existed: the HDR recording is still converted, nothing else is corrected
    old = engine.render(_plan(None), assets, {}, tmp_path / "o" / "final.mp4", cache_dir=tmp_path / "pieces")
    assert not old["colour"]["blue"]["corrected"] and old["colour"]["hdr"]["hdr"] == "hlg"
    assert _grey_cast(_frame_at(tmp_path / "o" / "final.mp4", 1.0, w, h)) > 0.8 * _grey_cast(src)

    # black and white: every piece changes (new pieces), the output has no colour left
    mono = _plan({**engine.default_color({}), "look": "mono"})
    m = engine.render(mono, assets, {}, tmp_path / "m" / "final.mp4", cache_dir=tmp_path / "pieces")
    assert m["colour"]["blue"]["look"] == "mono"
    px = _frame_at(tmp_path / "m" / "final.mp4", 1.0, w, h)
    assert np.abs(px[..., 0] - px[..., 2]).mean() * 255 < 2
    # the same plan again reuses every piece and the measurements
    pieces = sorted(p.name for p in (tmp_path / "pieces").glob("*.mp4"))
    engine.render(mono, assets, {}, tmp_path / "m2" / "final.mp4", cache_dir=tmp_path / "pieces")
    assert sorted(p.name for p in (tmp_path / "pieces").glob("*.mp4")) == pieces


def test_a_short_clip_gets_the_same_correction(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline import grade

    blue = _with_sound(_encode(_scene((0.85, 1.0, 1.2)), tmp_path / "blue_raw.mp4", 3.0), tmp_path / "blue.mp4")
    g, _ = grade.for_footage(str(blue), [(0.0, 3.0)], {}, screen=False)
    colour = grade.source_colour(blue)
    # the clip renderer's decoder chain (pipeline/render.py): scale, correct matrix, colour table, then BGR for numpy
    vf = f"scale={W}:{H}:flags=bicubic,{grade.rgb_filters(colour, g, '', tmp_path, H)},format=rgb48le"
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(blue), "-frames:v", "1", "-vf", vf,
                                   "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"], cwd=tmp_path)
    got = np.frombuffer(raw, "<u2").reshape(H, W, 3) / 65535.0
    assert _grey_cast(got) < 0.6 * _grey_cast(_scene((0.85, 1.0, 1.2)))
