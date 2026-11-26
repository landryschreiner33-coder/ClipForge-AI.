"""Speed changes, speed ramps, freeze frames and slow camera moves in the full-video engine (studio/retime.py).

Fast checks: the time map (out_at/src_at are inverses, speed 1 is the identity, ramps are smooth), what validate
says, how captions, overlays and attached sounds follow a clip's speed, and the WSOLA time-stretch (pitch kept, the
identity map leaves the sound unchanged). Slow checks render real files: a frame-clock video (each frame's number
drawn in its brightness) with a stepped tone shows the source frame and the sound heard at every output frame.
"""
from __future__ import annotations

import copy
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.studio import engine, retime

SR = 48000


def _clip(cid="c1", asset="clock", a=1000, b=5000, **extra) -> dict:
    return {"id": cid, "asset_id": asset, "label": cid, "in_ms": a, "out_ms": b, "include": True, "kind": "video",
            **extra}


# ---------------------------------------------------------------- the time map
def test_normal_speed_maps_every_time_to_itself():
    c = _clip()
    assert not retime.retimed(c)
    assert retime.out_len_ms(c) == 4000
    assert [retime.out_at(c, u) for u in (-50, 0, 1234.5, 4000, 4100)] == [-50, 0, 1234.5, 4000, 4100]
    assert retime.src_at(c, 2222) == 2222 and retime.setpts(c, 0) == "" and retime.describe(c) == ""


def test_constant_speed_and_its_inverse():
    c = _clip(speed=2)
    assert retime.out_len_ms(c) == 2000 and retime.edge_speeds(c) == (2.0, 2.0)
    assert retime.out_at(c, 3000) == 1500 and retime.src_at(c, 1500) == 3000
    assert retime.setpts(c, 0) == "setpts='(0.000000000+T)*0.500000000/TB-0.000000000/TB'"
    # read from 100 ms before the piece's first moment: those frames get negative times
    assert retime.setpts(c, 1000, 900) == "setpts='(0.900000000+T)*0.500000000/TB-0.500000000/TB'"
    slow = _clip(speed=0.25)
    assert retime.out_len_ms(slow) == 16000 and retime.src_at(slow, 16000) == 4000
    assert retime.describe(c) == "2×"


@pytest.mark.parametrize("preset", sorted(retime.RAMPS))
def test_a_ramp_is_smooth_continuous_and_inverted_exactly(preset):
    c = _clip(speed_ramp=retime.ramp_value(preset))
    assert retime.problems(c, None) == []
    total = retime.out_exact_ms(c)
    pts = retime.RAMPS[preset][1]
    # the output length is the integral of 1/speed: each segment contributes its length times the mean rate
    want = sum((b[0] - a[0]) * 4000 * (1 / a[1] + 1 / b[1]) / 2 for a, b in zip(pts, pts[1:]))
    assert total == pytest.approx(want)
    us = np.linspace(-300, 4300, 400)
    outs = [retime.out_at(c, u) for u in us]
    assert all(b > a for a, b in zip(outs, outs[1:]))  # strictly increasing: never backwards, never stuck
    assert max(abs(retime.src_at(c, o) - u) for u, o in zip(us, outs)) < 1e-6
    vec = retime.src_positions(c, np.array(outs))
    assert np.abs(vec - us).max() < 0.01
    # the speed (d source / d output) changes smoothly: no jump bigger than the ramp's own slope allows
    rates = np.diff(outs) / np.diff(us)
    assert np.abs(np.diff(rates)).max() < 0.1
    assert retime.edge_speeds(c) == (pts[0][1], pts[-1][1])


def test_a_freeze_holds_one_moment():
    c = _clip(kind="freeze", a=2000, b=2000, hold_ms=1500)
    assert retime.out_len_ms(c) == 1500 and retime.src_at(c, 900) == 0 and retime.edge_speeds(c) == (0, 0)
    assert retime.out_at(c, 700) == 700 and retime.out_at(c, 9000) == 1500  # attached things: video time
    assert retime.describe(c) == "freeze 1.5 s"


def test_validate_names_what_is_wrong_with_speed_ramps_freezes_and_moves(tmp_path):
    f = tmp_path / "clock.mp4"
    f.write_bytes(b"x")
    assets = {"clock": {"id": "clock", "kind": "video", "filename": "clock.mp4", "path": str(f),
                        "probe": {"duration": 10.0, "fps": 30.0}},
              "pic": {"id": "pic", "kind": "image", "filename": "p.png", "path": str(f), "probe": {}}}

    def problems(**clip):
        plan = {"schema": engine.SCHEMA, "timebase": 1000, "output": {"aspect": "16:9", "fps": 30},
                "clips": [_clip(**clip)]}
        return engine.validate(plan, assets)
    assert problems(speed=2) == [] and problems(speed=0.25) == []
    assert any("between 0.25× and 4×" in p for p in problems(speed=5))
    assert any("between 0.25× and 4×" in p for p in problems(speed=True))
    assert any("Only a video clip" in p for p in problems(asset="pic", kind="image", speed=2))
    assert any("in order" in p for p in problems(speed_ramp={"points": [{"at": 0.5, "speed": 1},
                                                                        {"at": 1, "speed": 2}]}))
    assert any("not readable" in p for p in problems(speed_ramp={"points": [{"at": 0}]}))
    assert problems(kind="freeze", a=3000, b=3000, hold_ms=2000) == []
    assert any("at least 0.2 s" in p for p in problems(kind="freeze", a=3000, b=3000, hold_ms=100))
    # 30 fps, 10 s: the last frame starts at 9966.7 ms, so 9990 is inside it and 10000 is past the picture
    assert problems(kind="freeze", a=9990, b=9990, hold_ms=1000) == []
    assert any("outside its file" in p for p in problems(kind="freeze", a=10000, b=10000, hold_ms=1000))
    assert any("frame of a video" in p for p in problems(asset="pic", kind="freeze", a=0, b=0, hold_ms=1000))
    assert any("unknown kind" in p for p in problems(kind="hologram"))
    assert problems(motion=retime.motion_value("zoom_in")) == []
    assert problems(asset="pic", kind="image", motion=retime.motion_value("pan_left")) == []
    assert any("keep one" in p for p in problems(motion=retime.motion_value("zoom_in"), zoom=1.1))
    bad = retime.motion_value("zoom_in")
    bad["keys"][1]["zoom"] = 3
    assert any("zoom 1 to 1.5" in p for p in problems(motion=bad))
    # fades are in video time: 1.5 s of fades fit a 4 s range at normal speed, not at 4×
    assert problems(fade_in_ms=800, fade_out_ms=700) == []
    assert any("fades" in p for p in problems(speed=4, fade_in_ms=800, fade_out_ms=700))


def test_the_timeline_captions_and_attached_things_follow_a_clips_speed():
    plan = {"clips": [_clip("a", a=0, b=2000), _clip("b", a=1000, b=5000, speed=2),
                      _clip("f", a=5000, b=5000, kind="freeze", hold_ms=1000), _clip("c", a=5000, b=6000)],
            "output": {"fps": 30},
            "overlays": [{"id": "o", "asset_id": "pic", "clip_id": "b", "offset_ms": 2000, "length_ms": 800}],
            "audio": [{"id": "s", "asset_id": "fx", "role": "effect", "in_ms": 0, "out_ms": 300,
                       "anchor": {"clip_id": "b", "offset_ms": 1000}}]}
    tl = engine.timeline(plan)
    assert [(s["out_start_ms"], s["out_end_ms"]) for s in tl] == [(0, 2000), (2000, 4000), (4000, 5000),
                                                                  (5000, 6000)]
    assert tl[1]["speed"] == 2 and tl[2]["freeze"] and tl[2]["hold_ms"] == 1000 and "speed" not in tl[0]
    assert engine.render_timeline(plan, 30)[1]["src_out_ms"] == 5000
    # a word 2 s into clip b's range is said 1 s into its part of the video; the freeze says nothing
    words = {"clock": [{"w": "hi", "start": 3.0, "end": 3.4}, {"w": "there", "start": 5.2, "end": 5.5}]}
    said = engine.output_words(plan, words)
    assert [(w["w"], w["start"], w["end"]) for w in said] == [("hi", 3.0, 3.2), ("there", 5.2, 5.5)]
    assert engine.overlay_timeline(plan)[0]["out_start_ms"] == 3000  # 2 s of file = 1 s of video
    assert engine.audio_timeline(plan)[0]["out_start_ms"] == 2500
    assert engine.offset_out_ms(plan["clips"][2], 400) == 400  # on a freeze: video time


def test_split_edits_leave_sped_up_cuts_alone():
    from clipfoundry.studio import sound_joins

    els = [{"asset_id": "A", "src_in_ms": 0, "frames": 120, "ov_in": 0, "clip": {"in_ms": 0, "out_ms": 4000}},
           {"asset_id": "B", "src_in_ms": 2000, "frames": 120, "ov_in": 0,
            "clip": {"in_ms": 2000, "out_ms": 10000, "speed": 2}}]
    words = {"A": [{"w": "x", "start": 0.5, "end": 1.0}], "B": [{"w": "y", "start": 5.0, "end": 5.5}]}
    assert sound_joins.split_edits(els, [True, True], words, {"A": 10000, "B": 12000}, 30) == {}
    els[1]["clip"].pop("speed")
    els[1]["clip"]["out_ms"] = 6000
    assert sound_joins.split_edits(els, [True, True], words, {"A": 10000, "B": 12000}, 30) != {}


def test_the_stretch_keeps_the_pitch_and_leaves_normal_speed_unchanged(tmp_path):
    t = np.arange(3 * SR) / SR
    x = np.repeat((0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)[:, None], 2, axis=1)
    x.tofile(tmp_path / "src.raw")
    n = int(1.5 * SR)
    retime.stretch(tmp_path / "src.raw", len(x), n, lambda j: j * 2.0, tmp_path / "fast.raw")
    y = np.fromfile(tmp_path / "fast.raw", dtype="<f4").reshape(-1, 2)[:, 0]
    assert len(y) == n
    spec = np.abs(np.fft.rfft(y[2000:-2000] * np.hanning(n - 4000)))
    peak = np.fft.rfftfreq(n - 4000, 1 / SR)[np.argmax(spec)]
    assert abs(peak - 440) < 3  # not 880: twice as fast, same note
    retime.stretch(tmp_path / "src.raw", len(x), n, lambda j: j + 1000.0, tmp_path / "same.raw", 0, 0)
    z = np.fromfile(tmp_path / "same.raw", dtype="<f4").reshape(-1, 2)[:, 0]
    assert np.abs(z[600:-600] - x[1600:1000 + n - 600, 0]).max() < 1e-5
    retime.stretch(tmp_path / "src.raw", len(x), n, lambda j: j + 0.0, tmp_path / "fade.raw", 4800, 4800)
    f = np.fromfile(tmp_path / "fade.raw", dtype="<f4").reshape(-1, 2)[:, 0]
    assert abs(f[0]) < 1e-6 and abs(f[-1]) < 1e-6 and np.abs(f[SR // 2:SR]).max() > 0.45


def test_the_editors_own_edits_set_speed_ramps_moves_and_freeze_frames():
    from clipfoundry.studio import video_flow as vf

    plan = _plan([_clip("a", a=0, b=4000), _clip("b", a=4000, b=8000)])
    plan["outline"] = [{"clip_id": "a", "duration": 4.0}, {"clip_id": "b", "duration": 4.0}]
    p, said = vf.apply_edit(plan, {"op": "set", "clip_id": "a", "field": "speed", "value": 2}, {})
    assert p["clips"][0]["speed"] == 2 and p["outline"][0]["duration"] == 2.0 and "2× speed" in said
    assert engine.duration_ms(p) == 6000 and not engine.retiming_in_use(plan) and engine.retiming_in_use(p)
    with pytest.raises(vf.VideoError, match="between 0.25 and 4"):
        vf.apply_edit(p, {"op": "set", "clip_id": "a", "field": "speed", "value": 5}, {})
    with pytest.raises(vf.VideoError, match="half a second"):  # 1.5 s of file at 4× is under half a second
        vf.apply_edit(p, {"op": "trim", "clip_id": "a", "in_ms": 0, "out_ms": 900}, {})
    p, said = vf.apply_edit(p, {"op": "set", "clip_id": "a", "field": "speed_ramp", "value": "slow_middle"}, {})
    assert "speed" not in p["clips"][0] and p["clips"][0]["speed_ramp"]["preset"] == "slow_middle"
    whole = retime.out_exact_ms(p["clips"][0])
    p, _ = vf.apply_edit(p, {"op": "split", "clip_id": "a", "at_ms": 2000}, {})
    first, second = p["clips"][0], p["clips"][1]
    assert retime.edge_speeds(first)[1] == retime.edge_speeds(second)[0] == pytest.approx(0.35)
    assert retime.out_exact_ms(first) + retime.out_exact_ms(second) == pytest.approx(whole, abs=1e-6)
    # a freeze frame at the end, inside and at the start of a clip (frames on a 30 fps grid without a probe)
    p, said = vf.apply_edit(p, {"op": "freeze", "clip_id": "b"}, {})
    held = p["clips"][3]
    assert held["kind"] == "freeze" and held["in_ms"] == held["out_ms"] == 7967 and held["hold_ms"] == 2000
    assert held["join"] == "cut" and "after" in said and engine.validate is not None
    p, said = vf.apply_edit(p, {"op": "freeze", "clip_id": "b", "at_ms": 6000, "length_ms": 1000}, {})
    kinds = [(c["id"], c.get("kind"), c["in_ms"], c["out_ms"], c.get("join")) for c in p["clips"][2:]]
    assert kinds[:3] == [("b", "video", 4000, 6000, None), ("f5", "freeze", 6000, 6000, "cut"),
                         ("bs", "video", 6000, 8000, "cut")], kinds
    with pytest.raises(vf.VideoError, match="holds one moment"):
        vf.apply_edit(p, {"op": "trim", "clip_id": "f5", "in_ms": 0, "out_ms": 1000}, {})
    p, said = vf.apply_edit(p, {"op": "set", "clip_id": "f5", "field": "hold_ms", "value": 1500}, {})
    assert "1.5 s" in said
    # a camera move replaces a still punch-in, and the other way round
    p, _ = vf.apply_edit(p, {"op": "set", "clip_id": "b", "field": "zoom", "value": 1.1}, {})
    p, _ = vf.apply_edit(p, {"op": "set", "clip_id": "b", "field": "motion", "value": "pan_left"}, {})
    assert "zoom" not in p["clips"][2] and p["clips"][2]["motion"]["preset"] == "pan_left"
    p, _ = vf.apply_edit(p, {"op": "set", "clip_id": "b", "field": "zoom", "value": 1.2}, {})
    assert "motion" not in p["clips"][2]


def test_a_split_plays_every_ramp_and_move_exactly_as_before():
    """Review of batch 4a: a split (or a freeze inside a clip) must not change how the clip plays. Each half keeps
    the whole clip's curve over its own share of the file (speed_ramp.range, motion.range)."""
    from clipfoundry.studio import video_flow as vf

    for preset in retime.RAMPS:
        for at in (1600, 2900, 4400):
            whole = _clip("a", a=1000, b=5000, speed_ramp=retime.ramp_value(preset))
            p, _ = vf.apply_edit(_plan([copy.deepcopy(whole)]), {"op": "split", "clip_id": "a", "at_ms": at}, {})
            first, second = p["clips"]
            assert retime.out_exact_ms(first) + retime.out_exact_ms(second) == pytest.approx(
                retime.out_exact_ms(whole), abs=1e-6), (preset, at)
            for u in (0, 333, at - 1000, 2500, 3999):  # each file moment plays when it did in the whole clip
                half, rel = (first, u) if u < at - 1000 else (second, u - (at - 1000))
                lead = 0 if half is first else retime.out_exact_ms(first)
                assert lead + retime.out_at(half, rel) == pytest.approx(retime.out_at(whole, u), abs=1e-6)
            assert retime.speed_at(first, 1.0) == pytest.approx(retime.speed_at(second, 0.0), abs=1e-6)
    # a camera move: the first half ends where the second starts, each moving over its share of the move
    whole = _clip("m", a=0, b=4000, motion=retime.motion_value("zoom_in"))
    p, _ = vf.apply_edit(_plan([copy.deepcopy(whole)]), {"op": "split", "clip_id": "m", "at_ms": 1000}, {})
    assert retime.motion_range(p["clips"][0]) == (0.0, 0.25) and retime.motion_range(p["clips"][1]) == (0.25, 1.0)
    p, _ = vf.apply_edit(p, {"op": "split", "clip_id": "ms", "at_ms": 3000}, {})
    assert [retime.motion_range(c) for c in p["clips"]] == [(0.0, 0.25), (0.25, 0.75), (0.75, 1.0)]
    assert retime.motion_filter(p["clips"][1], 0, 60, 640, 360) == retime.motion_filter(
        {**whole, "motion": {**whole["motion"], "range": [0.25, 0.75]}}, 0, 60, 640, 360)


def test_attached_things_stay_with_their_moment_through_a_split_and_a_freeze():
    from clipfoundry.studio import video_flow as vf

    plan = _plan([_clip("a", a=0, b=8000)],
                 overlays=[{"id": "o", "asset_id": "pic", "clip_id": "a", "offset_ms": 5000, "length_ms": 2000}],
                 chapters=[{"clip_id": "a", "offset_ms": 6000, "title": "Summit"},
                           {"clip_id": "a", "offset_ms": 1000, "title": "Start"}])
    plan["audio"] = [{"id": "s", "asset_id": "fx", "label": "fx", "role": "effect", "in_ms": 0, "out_ms": 300,
                      "anchor": {"clip_id": "a", "offset_ms": 6000}},
                     {"id": "w", "asset_id": "fx", "role": "effect", "in_ms": 0, "out_ms": 300,
                      "anchor": {"clip_id": "a", "offset_ms": 5000, "lead_ms": 270}}]
    p, _ = vf.apply_edit(plan, {"op": "freeze", "clip_id": "a", "at_ms": 3000, "length_ms": 2000}, {})
    assert [c["id"] for c in p["clips"]] == ["a", "f2", "as"]
    placed = {x["audio_id"]: x["out_start_ms"] for x in engine.audio_timeline(p)}
    assert placed == {"s": 8000, "w": 7000 - 270}  # file second 6 now plays at 8.0 s; the swish leads its picture
    assert engine.overlay_timeline(p)[0]["out_start_ms"] == 7000
    assert sorted((c["clip_id"], c["offset_ms"]) for c in p["chapters"]) == [("a", 1000), ("as", 3000)]


def test_leads_before_a_moment_are_video_time_at_any_speed(tmp_path):
    """A whoosh 540 ms before a cut and a swish 270 ms before a picture stay that far ahead when the clip is slowed
    or sped up; the editor's "Starts after its clip" is video time too."""
    from clipfoundry.studio import video_flow as vf

    for s in (0.25, 0.5, 1, 2, 4):
        c = _clip("b", a=0, b=8000, speed=s)
        assert engine.offset_out_ms(c, -540) == -540
        assert engine.anchor_out_ms(c, {"offset_ms": 2000, "lead_ms": 270}) == round(2000 / s) - 270
        assert engine.offset_from_out_ms(c, engine.offset_out_ms(c, 3000)) == 3000
    assert engine.anchor_lead_ms({"lead_ms": True}) == 0 and engine.anchor_lead_ms(None) == 0
    plan = _plan([_clip("a", a=0, b=2000), _clip("b", a=0, b=8000, speed=0.25)])
    plan["audio"] = [{"id": "s", "asset_id": "fx", "label": "fx", "role": "effect", "in_ms": 0, "out_ms": 300,
                      "anchor": {"clip_id": "b", "offset_ms": 0}}]
    p, _ = vf.apply_edit(plan, {"op": "audio_move", "audio_id": "s", "clip_id": "b", "out_offset_ms": 1000}, {})
    assert p["audio"][0]["anchor"] == {"clip_id": "b", "offset_ms": 250}
    assert engine.audio_timeline(p)[0]["clip_ms"] == 1000 and engine.audio_timeline(p)[0]["out_start_ms"] == 3000
    with pytest.raises(vf.VideoError, match="at most 10 s before"):
        vf.apply_edit(p, {"op": "audio_move", "audio_id": "s", "clip_id": "b", "out_offset_ms": -20000}, {})
    (tmp_path / "fx.m4a").write_bytes(b"x")
    fx = {"id": "fx", "kind": "audio", "filename": "fx.m4a", "path": str(tmp_path / "fx.m4a"), "probe": {"duration": 1}}
    p["audio"][0]["anchor"]["lead_ms"] = 99999
    assert any("more than 10 s" in x for x in engine.validate(p, {"fx": fx}))


def test_freeze_frames_land_on_the_files_own_frames(tmp_path):
    """24 fps footage (frames 41.7 ms apart): the last frame of a 3 s file starts at 2958.3 ms, past its sound's
    end is no frame at all; a freeze inside holds the frame on screen, a freeze near the end ends the clip on it,
    and a freeze of a moving clip keeps the framing it had there."""
    from clipfoundry.studio import video_flow as vf

    f = tmp_path / "c24.mp4"
    f.write_bytes(b"x")
    a24 = {"id": "c24", "kind": "video", "filename": "c24.mp4", "path": str(f),
           "probe": {"duration": 3.05, "video_duration": 3.0, "fps": 24.0}}
    assets = {"c24": a24}
    p, said = vf.apply_edit(_plan([_clip("a", "c24", a=0, b=3050)]), {"op": "freeze", "clip_id": "a"}, {}, assets)
    assert p["clips"][1]["in_ms"] == 2959 and engine.validate(p, assets) == []
    p, _ = vf.apply_edit(_plan([_clip("a", "c24", a=0, b=3000)]),
                         {"op": "freeze", "clip_id": "a", "at_ms": 1510}, {}, assets)
    assert [(c["id"], c["in_ms"], c["out_ms"]) for c in p["clips"]] == [("a", 0, 1500), ("f2", 1500, 1500),
                                                                        ("as", 1500, 3000)]
    p, said = vf.apply_edit(_plan([_clip("a", "c24", a=0, b=3000)]),
                            {"op": "freeze", "clip_id": "a", "at_ms": 2700}, {}, assets)
    assert p["clips"][0]["out_ms"] == 2709 and p["clips"][1]["in_ms"] == 2667 and "now ends there" in said
    moving = _clip("m", "c24", a=0, b=3000, motion=retime.motion_value("zoom_in"))
    p, _ = vf.apply_edit(_plan([moving]), {"op": "freeze", "clip_id": "m", "at_ms": 1500}, {}, assets)
    held = p["clips"][1]
    assert retime.motion_range(held) == (0.5, 0.5) and retime.motion_range(p["clips"][2]) == (0.5, 1.0)
    assert any("outside its file" in x for x in engine.validate(
        _plan([_clip("f", "c24", a=3010, b=3010, kind="freeze", hold_ms=1000)]), assets))


# ---------------------------------------------------------------- real renders
def _clock_video(path: Path, seconds: float = 8, size: str = "320x180", sound_after: float = 0.0) -> Path:
    """Each frame's number N drawn in its brightness (left half: N mod 25, right half: N div 25, 8 and 20 levels a
    step above a dark grey, so a preview's coarse encoding cannot blur it),
    with a tone that steps up every second (300, 500, 700, ... Hz). `sound_after`: the sound runs on that long
    after the last frame, as a phone's or camera's often does."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"nullsrc=s={size}:r=30:d={seconds},format=yuv420p,"
                    "geq=lum='if(lt(X,W/2),30+mod(N,25)*8,30+floor(N/25)*20)':cb=128:cr=128",
                    "-f", "lavfi", "-i",
                    f"aevalsrc='0.5*sin(2*PI*(300+200*floor(t))*t)':s=48000:d={seconds + sound_after}",
                    "-c:v", "libx264", "-crf", "4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
                    *([] if sound_after else ["-shortest"]), str(path)], check=True)
    return path


def _lumas(path: Path, w: int = 160, h: int = 90) -> np.ndarray:
    """The luma plane of every frame, scaled down (frames, h, w)."""
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}",
                                   "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"])
    per = w * h * 3 // 2
    return np.frombuffer(raw, np.uint8).reshape(-1, per)[:, :w * h].reshape(-1, h, w).astype(np.float64)


def _source_frames(path: Path) -> list[int]:
    y = _lumas(path)
    left, right = y[:, 30:60, 20:60].mean(axis=(1, 2)), y[:, 30:60, 100:140].mean(axis=(1, 2))
    return [int(round((a - 30) / 8)) + 25 * int(round((b - 30) / 20)) for a, b in zip(left, right)]


def _band(x: np.ndarray, t0: float, t1: float, freq: float) -> float:
    seg = x[int(t0 * SR):int(t1 * SR)]
    win = np.hanning(len(seg))
    spec = np.abs(np.fft.rfft(seg * win)) * 2 / win.sum()
    bins = np.fft.rfftfreq(len(seg), 1 / SR)
    return float(spec[(bins > freq - 25) & (bins < freq + 25)].max())


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar",
                                   str(SR), "-"])
    return np.frombuffer(raw, dtype=np.float32)


def _asset(path: Path, kind: str = "video") -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    return {"id": path.stem, "kind": kind, "filename": path.name, "path": str(path), "sha256": path.stem,
            "probe": probe(path) if kind == "video" else {}}


def _plan(clips: list[dict], **extra) -> dict:
    return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "16:9", "fps": 30}, "layout": "fill", "clips": clips,
            "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 2500},
            "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": [], **extra}


@pytest.mark.slow
def test_double_speed_shows_every_other_frame_and_keeps_the_voice_in_tune_and_in_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    clock = _asset(_clock_video(tmp_path / "clock.mp4"))
    plan = _plan([_clip(a=1000, b=5000, speed=2)])
    info = engine.render(plan, {"clock": clock}, {}, tmp_path / "out.mp4", preview=True)
    assert info["frames"] == 60 and info["timeline"][0]["src_out_ms"] == 5000 and info["timeline"][0]["speed"] == 2
    frames = _source_frames(tmp_path / "out.mp4")
    assert len(frames) == 60
    assert all(abs(f - (30 + 2 * i)) <= 1 for i, f in enumerate(frames)), frames
    pcm = _pcm(tmp_path / "out.mp4")
    # file second 1-2 (500 Hz) plays in the video's first half second, 2-3 (700 Hz) in the next, ...
    for k, freq in enumerate((500, 700, 900, 1100)):
        t0, t1 = k * 0.5 + 0.06, k * 0.5 + 0.44
        here = _band(pcm, t0, t1, freq)
        assert here > 0.2, (freq, here)
        assert _band(pcm, t0, t1, freq * 2) < 0.05 * here  # the pitch is kept (no chipmunk octave)
    # the step from 500 to 700 Hz is heard at the frame it is shown (0.5 s), within a frame
    hop = int(0.005 * SR)
    t = np.arange(int(0.3 * SR), int(0.7 * SR), hop)
    hi = [_band(pcm, s / SR, s / SR + 0.03, 700) > _band(pcm, s / SR, s / SR + 0.03, 500) for s in t]
    assert abs((t[hi.index(True)] / SR + 0.015) - 0.5) < 1 / 30


@pytest.mark.slow
def test_a_ramp_slows_in_the_middle_and_a_freeze_holds_its_frame_with_the_clip_going_on_after(
        tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    clock = _asset(_clock_video(tmp_path / "clock.mp4"))
    ramp = _clip("r", a=0, b=2000, speed_ramp=retime.ramp_value("slow_middle"))
    freeze = _clip("f", a=2000, b=2000, kind="freeze", hold_ms=1000)
    after = _clip("n", a=2000, b=3000)
    plan = _plan([ramp, freeze, after])
    assert engine.validate(plan, {"clock": clock}) == []
    info = engine.render(plan, {"clock": clock}, {}, tmp_path / "out.mp4", preview=True)
    r_frames = round(retime.out_exact_ms(ramp) * 30 / 1000)
    assert info["frames"] == r_frames + 30 + 30
    frames = _source_frames(tmp_path / "out.mp4")
    for i in range(0, r_frames, 3):  # every ramp frame shows the file frame the map says (frames are whole)
        assert abs(frames[i] - retime.src_at(ramp, i * 1000 / 30) * 30 / 1000) <= 1.5, (i, frames[i])

    step = np.diff(frames[:r_frames])
    middle = step[r_frames // 2 - 6:r_frames // 2 + 6].mean()
    assert middle < 0.45 and step[2:12].mean() > 1.5 * middle and step[-10:].mean() > 1.5 * middle

    held = frames[r_frames:r_frames + 30]
    assert set(held) == {60}, held  # one frame (2.0 s into the file) for exactly the hold
    assert abs(frames[r_frames + 30] - 60) <= 1 and frames[-1] in (89, 90)  # the clip after goes on from there
    pcm = _pcm(tmp_path / "out.mp4")
    r_s = r_frames / 30
    assert _band(pcm, r_s + 0.1, r_s + 0.9, 700) < 0.01  # a freeze brings no sound of its own
    # the ramp's sound follows its picture: file second 1 (300 -> 500 Hz) is heard when frame 30 is shown
    shown = next(i for i, f in enumerate(frames) if f >= 30) / 30
    hop = int(0.005 * SR)
    t = np.arange(int((shown - 0.3) * SR), int((shown + 0.3) * SR), hop)
    hi = [_band(pcm, s / SR, s / SR + 0.03, 500) > _band(pcm, s / SR, s / SR + 0.03, 300) for s in t]
    assert abs((t[hi.index(True)] / SR + 0.015) - shown) < 0.05


@pytest.mark.slow
def test_a_slow_zoom_moves_smoothly_on_a_video_and_a_photo(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    ramp = tmp_path / "ramp.mp4"  # brightness rises from left to right
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=640x360:r=30:d=3,format=yuv420p,geq=lum='16+X*200/W':cb=128:cr=128",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264", "-crf", "4",
                    "-c:a", "aac", str(ramp)], check=True)
    photo = tmp_path / "photo.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=640x360,format=gray,geq=lum='X*255/W'", "-frames:v", "1", str(photo)], check=True)
    assets = {"ramp": _asset(ramp), "photo": _asset(photo, "image")}
    plan = _plan([_clip("v", "ramp", a=0, b=2000, motion=retime.motion_value("zoom_in")),
                  _clip("p", "photo", a=0, b=2000, kind="image", motion=retime.motion_value("pan_right"))])
    assert engine.validate(plan, assets) == []
    # a final render: a preview's coarse encoding skips changes smaller than a brightness level
    engine.render(plan, assets, {}, tmp_path / "out.mp4")
    y = _lumas(tmp_path / "out.mp4")
    # brightness across the frame is a straight line: its slope says how far in the framing is, where it starts
    # says where the framing's left edge is (fitted over every column: far finer than one pixel)
    x = np.linspace(0, 1, y.shape[2])
    fits = np.array([np.polyfit(x[8:-8], f[20:70].mean(axis=0)[8:-8], 1) for f in y])
    zoom = fits[:60, 0][0] / fits[:60, 0]  # the first frame shows the whole picture
    assert abs(zoom[-1] - 1.2) < 0.02
    steps = np.diff(zoom)
    # a new framing every frame (no stair steps, never back); the eased ends move by less than a level
    assert (steps[5:-5] > 0).all() and (steps > -1e-3).all(), steps
    assert steps[25:35].mean() > 2 * steps[:5].mean() and steps[25:35].mean() > 2 * steps[-5:].mean()  # eased
    pan = fits[60:, 1]  # the photo pans right: the left edge moves right at a steady zoom
    assert (np.diff(pan)[5:-5] > 0).all() and pan[-1] - pan[0] > 25
    assert np.ptp(fits[60:, 0]) < 0.03 * fits[60:, 0].mean()


@pytest.mark.slow
def test_changing_only_the_speed_renders_that_clip_again(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    clock = _asset(_clock_video(tmp_path / "clock.mp4", 4))
    cache = tmp_path / "pieces"
    engine.render(_plan([_clip(a=0, b=2000)]), {"clock": clock}, {}, tmp_path / "a.mp4", preview=True,
                  cache_dir=cache)
    engine.render(_plan([_clip(a=0, b=2000, speed=0.5)]), {"clock": clock}, {}, tmp_path / "b.mp4", preview=True,
                  cache_dir=cache)
    frames = _source_frames(tmp_path / "b.mp4")
    assert len(frames) == 120 and frames[1] == 0 and frames[2] == 1 and frames[-1] in (59, 60)


@pytest.mark.slow
def test_freezes_and_slow_motion_show_the_exact_frame_of_the_file(tmp_path, monkeypatch):
    """Review of batch 4a, rendered. A freeze at the end of a file whose sound runs 0.2 s past its picture holds the
    last picture (no empty frame), the clip ends on it and the next clip starts clean; 0.25× slow motion from an in
    point on or inside a frame shows, at every output frame, exactly the file frame the time map points at."""
    from clipfoundry.studio import video_flow as vf

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    (tmp_path / "a").mkdir()
    clock = _asset(_clock_video(tmp_path / "a" / "clock.mp4", 3, sound_after=0.2))
    assets = {"clock": clock}
    length = engine._length(clock)  # noqa: SLF001 (the sound's end: 3.2 s)
    plan = _plan([_clip("c", a=1000, b=length), _clip("d", a=0, b=1000)])
    p, said = vf.apply_edit(plan, {"op": "freeze", "clip_id": "c"}, {}, assets)
    assert [(c["in_ms"], c["out_ms"]) for c in p["clips"]] == [(1000, 3000), (2967, 2967), (0, 1000)], said
    assert engine.validate(p, assets) == []
    info = engine.render(p, assets, {}, tmp_path / "freeze.mp4", preview=True)
    frames = _source_frames(tmp_path / "freeze.mp4")
    assert info["frames"] == len(frames) == 150
    assert frames[:60] == list(range(30, 90)) and set(frames[60:120]) == {89} and frames[120:] == list(range(30))

    slow = _asset(_clock_video(tmp_path / "clock.mp4", 4))
    for a_ms in (1000, 1010, 1030):
        c = _clip(a=a_ms, b=a_ms + 600, speed=0.25)
        engine.render(_plan([c]), {"clock": slow}, {}, tmp_path / f"slow{a_ms}.mp4", preview=True)
        shown = _source_frames(tmp_path / f"slow{a_ms}.mp4")
        want = [math.floor((a_ms + retime.src_at(c, i * 1000 / 30)) * 30 / 1000 + 1e-6) for i in range(len(shown))]
        assert len(shown) == 72 and shown == want, (a_ms, shown, want)


@pytest.mark.slow
def test_slow_zooms_keep_their_pace_on_24_and_60_fps_footage(tmp_path, monkeypatch):
    """Review of batch 4a: the move counts the video's own frames, so on 60 fps footage a 2 s zoom does not finish
    in 1 s and on 24 fps footage it does not stop at 80 %."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for fps in (24, 60):
        ramp = tmp_path / f"ramp{fps}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"nullsrc=s=640x360:r={fps}:d=3,format=yuv420p,geq=lum='16+X*200/W':cb=128:cr=128",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264", "-crf",
                        "4", "-c:a", "aac", str(ramp)], check=True)
        plan = _plan([_clip("v", ramp.stem, a=0, b=2000, motion=retime.motion_value("zoom_in"))])
        engine.render(plan, {ramp.stem: _asset(ramp)}, {}, tmp_path / f"out{fps}.mp4")
        y = _lumas(tmp_path / f"out{fps}.mp4")
        x = np.linspace(0, 1, y.shape[2])
        slopes = np.array([np.polyfit(x[8:-8], f[20:70].mean(axis=0)[8:-8], 1)[0] for f in y])
        zoom = slopes[0] / slopes
        assert len(zoom) == 60
        assert abs(zoom[-1] - 1.2) < 0.02 and abs(zoom[30] - 1.1) < 0.02, (fps, zoom[[0, 15, 30, 45, 59]])


@pytest.mark.slow
def test_a_split_inside_a_slowed_clip_joins_without_a_click(tmp_path, monkeypatch):
    """Review of batch 4a: the two halves of a slowed (or ramped) clip are stretched apart, so their sound is joined
    with a short straight crossfade; the join is as smooth as the tone around it."""
    from clipfoundry.studio import video_flow as vf

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    tone = tmp_path / "tone.mov"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=30:d=5",
                    "-f", "lavfi", "-i", "sine=f=440:r=48000:d=5", "-af", "volume=0.6", "-c:v", "libx264",
                    "-c:a", "pcm_s16le", "-shortest", str(tone)], check=True)
    for edits in ([{"op": "set", "clip_id": "c", "field": "speed", "value": 0.5}],
                  [{"op": "set", "clip_id": "c", "field": "speed_ramp", "value": "slow_middle"}]):
        p = _plan([_clip("c", "tone", a=0, b=4000)])
        for e in [*edits, {"op": "split", "clip_id": "c", "at_ms": 2000}]:
            p, _ = vf.apply_edit(p, e, {})
        engine.render(p, {"tone": _asset(tone)}, {}, tmp_path / "out.mp4", preview=True)
        join = int(engine.timeline(p)[1]["out_start_ms"] * SR / 1000)
        bend = np.abs(np.diff(_pcm(tmp_path / "out.mp4"), 2))
        around = bend[join - 480:join + 480].max()
        elsewhere = np.percentile(np.concatenate([bend[int(0.3 * SR):join - 2400], bend[join + 2400:-int(0.3 * SR)]]),
                                  99.9)
        assert around < 2 * elsewhere, (edits, around, elsewhere)
