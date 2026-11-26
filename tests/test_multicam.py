"""Several cameras of one recording and pictures in a corner (studio/multicam.py, studio/camera_edits.py).

Fast checks use made-up loudness tracks of a conversation (two people taking turns, each filmed by a close camera
with its own gain, and a wide camera hearing both): lining the cameras up by their sound (offset, drift, no match),
telling who speaks, the switching rules (wide shot at the start, the end and in long pauses, no shot under 2 s,
cuts in the gaps between words), what validate says, the editor's and plain-words edits, the editor page's view and
the export. Slow checks render real files: every output frame shows the right camera at the synced moment, also at
another speed, and a camera in the corner shows its own synced frame inside a light border.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.studio import camera_edits, edit_requests as er, engine, interchange, multicam
from clipfoundry.studio import video_flow as vf

R = multicam.RATE


# ---------------------------------------------------------------- a made-up conversation
def _talk(minutes: float = 3.0, seed: int = 3):
    """(words, true speaker per word, frames): A and B take turns of 3-15 s; one turn in ten ends in a 3 s pause."""
    rng = np.random.default_rng(seed)
    total = minutes * 60
    words, who = [], []
    t, spk = 1.0, "A"
    while t < total - 5:
        end = min(total - 5, t + rng.uniform(3, 15))
        while t < end:
            for _ in range(int(rng.integers(3, 9))):
                d = rng.uniform(0.18, 0.45)
                words.append({"w": "x", "start": t, "end": t + d})
                who.append(spk)
                t += d + rng.uniform(0.04, 0.12)
            t += rng.uniform(0.35, 0.8)
        t += rng.uniform(0.3, 1.5) + (3.0 if rng.random() < 0.1 else 0.0)
        spk = "B" if spk == "A" else "A"
    return words, who, int(total * R)


def _levels(words, who, frames, seed: int = 4):
    """Loudness (dB, 100 per second) heard by the wide camera and by each person's close camera."""
    rng = np.random.default_rng(seed)
    floor = -70 + rng.normal(0, 1.5, frames)
    va, vb = np.full(frames, -200.0), np.full(frames, -200.0)
    for w, s in zip(words, who):
        a, b = int(w["start"] * R), int(w["end"] * R)
        (va if s == "A" else vb)[a:b] = -22 + rng.normal(0, 3) + rng.normal(0, 2, b - a)

    def mix(*parts):
        return (10 * np.log10(sum(10 ** (p / 10) for p in parts))).astype(np.float32)

    # each close camera hears its own person 5-6 dB louder and has its own gain (+3 dB, -6 dB)
    return mix(floor, va, vb), mix(floor + 3, va + 9, vb - 1), mix(floor - 6, vb - 1, va - 11)


def _later(levels: np.ndarray, offset_ms: float, seed: int = 5) -> np.ndarray:
    """The same sound recorded by a camera started `offset_ms` earlier (positive) or later (negative)."""
    k = int(round(offset_ms / 10))
    rng = np.random.default_rng(seed)
    if k >= 0:
        return np.concatenate([-70 + rng.normal(0, 1.5, k), levels]).astype(np.float32)
    return levels[-k:].copy()


# ---------------------------------------------------------------- lining up by sound
def test_cameras_line_up_by_their_sound_whichever_started_first():
    words, who, n = _talk()
    main, cam_a, cam_b = _levels(words, who, n)
    early = multicam.line_up(main, _later(cam_a, 12340))
    late = multicam.line_up(main, _later(cam_b, -7500))
    assert early and abs(early["offset_ms"] - 12340) <= 10 and early["drift_ppm"] == 0 and early["match"] >= 0.3
    assert late and abs(late["offset_ms"] + 7500) <= 10
    cam = {"offset_ms": early["offset_ms"], "drift_ppm": 0}
    assert multicam.to_cam_ms(cam, 1000) == pytest.approx(1000 + early["offset_ms"])


def test_a_long_recording_whose_clock_runs_fast_is_lined_up_along_its_whole_length():
    words, who, n = _talk(minutes=15, seed=7)
    main, _, cam_b = _levels(words, who, n, seed=8)
    off, drift = -7500.0, 40e-6
    tb = np.arange(int((n * 10 + off) / 10)) * 10.0
    drifting = np.interp((tb - off) / (1 + drift) / 10, np.arange(n), cam_b).astype(np.float32)
    found = multicam.line_up(main, drifting)
    assert found and abs(found["drift_ppm"] - 40) <= 4 and abs(found["offset_ms"] - off) <= 15
    # an hour in, the camera is 144 ms ahead: lined up within a frame there too
    at = 14 * 60 * 1000
    assert abs(multicam.to_cam_ms(found, at) - (off + at * (1 + drift))) <= 33


def test_recordings_without_the_same_sound_are_not_lined_up():
    words, who, n = _talk()
    main, _, _ = _levels(words, who, n)
    rng = np.random.default_rng(9)
    other = _levels(*_talk(seed=11)[:3], seed=12)[0]  # another conversation
    assert multicam.line_up(main, (-60 + rng.normal(0, 5, 50000)).astype(np.float32)) is None
    assert multicam.line_up(main, other) is None
    assert multicam.line_up(main, main[:200]) is None  # under 3 s: too short to tell


def test_aligned_puts_a_cameras_sound_on_the_main_recordings_frames():
    lv = np.arange(1000, dtype=np.float32)
    out = multicam.aligned(lv, {"offset_ms": 2000, "drift_ppm": 0}, 900)
    assert out[0] == 200 and out[799] == 999 and np.isnan(out[800:]).all()
    before = multicam.aligned(lv, {"offset_ms": -500, "drift_ppm": 0}, 100)
    assert np.isnan(before[:50]).all() and before[50] == 0


# ---------------------------------------------------------------- who speaks
def test_who_speaks_tells_two_people_apart_whatever_each_cameras_level():
    words, who, n = _talk(minutes=6)
    _, cam_a, cam_b = _levels(words, who, n)
    got, info = multicam.who_speaks(words, {"ca": cam_a, "cb": cam_b})
    assert info["separable"], info
    sure = [(g, t) for g, t in zip(got, who) if g]
    assert len(sure) >= 0.8 * len(words)
    assert np.mean([g == ("ca" if t == "A" else "cb") for g, t in sure]) >= 0.97
    assert set(info["seconds"]) == {"ca", "cb"}


def test_who_speaks_says_so_when_the_cameras_cannot_tell_the_people_apart():
    words, who, n = _talk()
    main, _, _ = _levels(words, who, n)
    got, info = multicam.who_speaks(words, {"ca": main + 4, "cb": main - 7})  # both hear the same mix
    assert not info["separable"] and info["why"] and not any(got)
    one, info1 = multicam.who_speaks(words, {"ca": main})
    assert not info1["separable"] and not any(one)


def test_who_speaks_goes_on_where_one_camera_has_stopped_recording():
    words, who, n = _talk(minutes=6)
    main, cam_a, cam_b = _levels(words, who, n)
    on = {"offset_ms": 0, "drift_ppm": 0}
    levels = {"main": multicam.aligned(main, None, n), "ca": multicam.aligned(cam_a, on, n),
              "cb": multicam.aligned(cam_b[: 120 * R], on, n)}  # camera B's battery died after 2 minutes
    got, info = multicam.who_speaks(words, levels)
    assert info["separable"]
    late = [(g, t) for w, g, t in zip(words, got, who) if w["start"] > 125]
    sure = [(g, t) for g, t in late if g]
    assert len(sure) >= 0.8 * len(late)  # the other cameras still tell the people apart
    assert np.mean([g == ("ca" if t == "A" else "cb") for g, t in sure]) >= 0.95
    shots = {"main": "wide", "ca": "close", "cb": "close"}
    cuts = multicam.plan_cuts([(0, n * 10)], words, got, shots, "speaker", lambda c, a, b: c != "cb" or b <= 120000)
    a_late = [w for w, t in zip(words, who) if t == "A" and w["start"] > 125]
    on_a = sum(multicam.camera_at({"cuts": cuts}, (w["start"] + w["end"]) * 500) == "ca" for w in a_late)
    assert on_a >= 0.8 * len(a_late)  # A is still shown on camera A after camera B stopped
    assert all(c != "cb" for t, c in cuts if t > 120000)


# ---------------------------------------------------------------- the switching rules
def _played(cuts, ranges, step=10):
    """(start, length, camera) of each shot as the video plays `ranges` in order (ms of the video)."""
    seq = [multicam.camera_at({"cuts": cuts}, t) for a, b in ranges for t in np.arange(a, b, step)]
    out, k = [], 0
    for i in range(1, len(seq) + 1):
        if i == len(seq) or seq[i] != seq[k]:
            out.append((k * step, (i - k) * step, seq[k]))
            k = i
    return out


@pytest.mark.parametrize("mode", ["speaker", "angles"])
@pytest.mark.parametrize("ranges", [[(30000, 90000), (30000, 90000)], [(0, 60000), (120000, 180000), (0, 30000)],
                                    [(250000, 265000), (0, 300000)], [(0, 200000), (50000, 90000), (150000, 250000)],
                                    [(0, 150000), (100000, 200000)]])
def test_moments_the_video_plays_twice_keep_the_cameras_planned_where_they_first_play(ranges, mode):
    """A part used again, or a teaser of a later moment: the cuts are in the recording's time, so a later range only
    plans moments not planned yet; the video still opens on the wide shot, and no shot inside a range is short."""
    words, who, _ = _talk(minutes=6)
    truth = ["ca" if t == "A" else "cb" for t in who]
    shots = {"main": "wide", "ca": "close", "cb": "close"}
    cuts = multicam.plan_cuts(ranges, words, truth if mode == "speaker" else None, shots, mode, lambda c, a, b: True,
                              seed="s")
    played = _played(cuts, ranges)
    assert played[0][2] == "main" and played[0][1] >= multicam.OPEN_MS - 100
    edges, base = set(), 0
    for a, b in ranges:
        edges |= {base, base + b - a}
        base += b - a
    short = [x for x in played[1:-1] if x[1] < multicam.MIN_HOLD_MS and x[0] not in edges and x[0] + x[1] not in edges]
    assert short == []


def _shown(cuts, t):
    cam = "main"
    for at, c in cuts:
        if at <= t:
            cam = c
    return cam


def test_switching_to_the_speaker_follows_the_editors_rules():
    words, who, n = _talk(minutes=6)
    truth = ["ca" if s == "A" else "cb" for s in who]
    shots = {"main": "wide", "ca": "close", "cb": "close"}
    end = n * 10
    cuts = multicam.plan_cuts([(0, end)], words, truth, shots, "speaker", lambda c, a, b: True, "rec")
    assert len(cuts) > 20
    times = [c[0] for c in cuts]
    assert times == sorted(times)
    assert all(b - a >= multicam.MIN_HOLD_MS for a, b in zip(times, times[1:]))  # no shot under 2 s
    assert all(_shown(cuts, t) == "main" for t in range(0, multicam.OPEN_MS, 100))  # opens on the wide shot
    assert _shown(cuts, end - 10) == "main" and _shown(cuts, end - multicam.END_MS - 100) is not None
    for at, cam in cuts:  # a cut never lands inside a word
        assert not any(w["start"] * 1000 < at < w["end"] * 1000 - 1 for w in words), at
    # long pauses go to the wide shot
    for w0, w1 in zip(words, words[1:]):
        gap = (w1["start"] - w0["end"]) * 1000
        if gap >= multicam.SILENCE_MS + 2 * multicam.MIN_HOLD_MS:
            assert _shown(cuts, (w0["end"] + w1["start"]) * 500) == "main"
    # most of the talk shows the person talking
    on = [_shown(cuts, (w["start"] + w["end"]) * 500) == t for w, t in zip(words, truth)]
    assert np.mean(on) >= 0.75
    # no close-up runs on for much longer than the rule allows before the wide shot breaks it
    shots_len = [(b - a, cam) for (a, cam), (b, _) in zip(cuts, cuts[1:])]
    assert max(d for d, cam in shots_len if cam != "main") <= multicam.MAX_CLOSE_MS + 8000


def test_a_quick_yeah_stays_with_the_speaker_but_a_question_after_a_pause_gets_its_own_shot():
    def w(t0, t1):
        return {"w": "x", "start": t0, "end": t1}

    shots = {"main": "wide", "ca": "close", "cb": "close"}
    # B talks 4-14 s, A says "yeah" (0.5 s) in a 0.3 s gap, B goes on to 24 s
    words = [w(4 + 0.5 * k, 4.4 + 0.5 * k) for k in range(20)] + [w(14.3, 14.8)] + \
        [w(15.1 + 0.5 * k, 15.5 + 0.5 * k) for k in range(18)]
    who = ["cb"] * 20 + ["ca"] + ["cb"] * 18
    cuts = multicam.plan_cuts([(0, 30000)], words, who, shots, "speaker", lambda c, a, b: True, "y")
    assert not any(c == "ca" for _, c in cuts)
    # B talks, a 4 s pause, A asks a 1.5 s question, B answers: the question is A's
    words = [w(4 + 0.5 * k, 4.4 + 0.5 * k) for k in range(20)] + [w(18 + 0.5 * k, 18.4 + 0.5 * k) for k in range(3)] + \
        [w(20 + 0.5 * k, 20.4 + 0.5 * k) for k in range(20)]
    who = ["cb"] * 20 + ["ca"] * 3 + ["cb"] * 20
    cuts = multicam.plan_cuts([(0, 34000)], words, who, shots, "speaker", lambda c, a, b: True, "y")
    assert _shown(cuts, 16000) == "main" and _shown(cuts, 18800) == "ca"


def test_one_person_several_angles_changes_angle_every_few_seconds_in_pauses():
    words, _, n = _talk(minutes=4)
    shots = {"main": "wide", "c2": "close", "c3": "other"}  # a screen recording is never switched to
    a = multicam.plan_cuts([(0, 120000), (130000, 230000)], words, None, shots, "angles", lambda c, x, y: True, "s")
    b = multicam.plan_cuts([(0, 120000), (130000, 230000)], words, None, shots, "angles", lambda c, x, y: True, "s")
    assert a == b and len(a) >= 10  # the same recording always gets the same angles
    assert {c for _, c in a} <= {"main", "c2"}
    inside = [t for t, _ in a if 0 < t < 120000]
    holds = np.diff(inside)
    assert holds.min() >= multicam.MIN_HOLD_MS and np.median(holds) <= multicam.ANGLE_HOLD_MS[1] + 3000


def test_a_camera_is_only_chosen_where_its_file_has_picture():
    words, who, n = _talk(minutes=3)
    truth = ["ca" if s == "A" else "cb" for s in who]
    shots = {"main": "wide", "ca": "close", "cb": "close"}

    def avail(cam, t0, t1):  # camera B's file ends after 60 s
        return cam != "cb" or t1 <= 60000

    cuts = multicam.plan_cuts([(0, n * 10)], words, truth, shots, "speaker", avail, "x")
    assert not any(c == "cb" and t >= 60000 for t, c in cuts)
    # and if a cut still points past its end, the main camera shows there
    g = {"cams": [{"id": "cb", "asset_id": "b", "offset_ms": 0, "drift_ppm": 0}], "cuts": [[50000, "cb"]]}
    spans = multicam.spans(g, 40000, 80000, {"cb": 60000})
    end = multicam.coverage(g["cams"][0], 60000)[1]  # a frame clear of the file's end
    assert 59800 <= end < 60000
    assert spans == [(40000, 50000, "main", None), (50000, end, "cb", None), (end, 80000, "main", None)]


def test_spans_split_a_drifting_camera_every_minute_and_show_the_corner_camera():
    g = {"cams": [{"id": "c2", "asset_id": "b", "offset_ms": 0, "drift_ppm": 100},
                  {"id": "c3", "asset_id": "c", "offset_ms": 0, "drift_ppm": 0}],
         "cuts": [[0, "c2"], [150000, "c3"]], "corner": {"cam": "c3"}}
    spans = multicam.spans(g, 0, 200000, {"c2": 10 ** 7, "c3": 10 ** 7})
    assert [s[2] for s in spans] == ["c2", "c2", "c2", "c3"]
    assert all(s[1] - s[0] <= multicam.DRIFT_PIECE_MS for s in spans[:3])
    assert spans[0][3] == "c3" and spans[-1][3] is None  # hidden while it is the full picture


# ---------------------------------------------------------------- the plan: validate, corner geometry, timeline
def _video(path: Path) -> dict:
    path.write_bytes(b"")
    return {"id": path.stem, "kind": "video", "filename": path.name, "path": str(path), "sha256": path.stem,
            "probe": {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0, "has_audio": True}}


def _plan(**extra) -> dict:
    return {"schema": engine.SCHEMA, "timebase": 1000, "engine": engine.ENGINE,
            "output": {"aspect": "16:9", "fps": 30}, "layout": "fill", "transition": {"type": "cut", "ms": 0},
            "title": {"enabled": False, "text": "", "ms": 2500},
            "clips": [{"id": "k1", "asset_id": "main", "label": "Clip 1", "in_ms": 1000, "out_ms": 5000,
                       "include": True, "kind": "video"},
                      {"id": "k2", "asset_id": "main", "label": "Clip 2", "in_ms": 6000, "out_ms": 10000,
                       "include": True, "kind": "video", "speed": 2}],
            "captions": {"enabled": False, "style": "clean", "position": "bottom", "size": "medium"},
            "audio": [], "tracks": engine.default_tracks(), "word_fixes": {}, "outline": [], "notes": [], **extra}


def _group(**extra) -> dict:
    return {"main": {"label": "Camera 1", "shot": "wide"},
            "cams": [{"id": "c2", "asset_id": "cam2", "label": "Camera 2", "shot": "close", "offset_ms": 2000.0,
                      "drift_ppm": 0, "match": 0.6},
                     {"id": "c3", "asset_id": "cam3", "label": "Camera 3", "shot": "close", "offset_ms": -1500.0,
                      "drift_ppm": 0, "match": 0.5}],
            "cuts": [[2000, "c2"], [3500, "c3"], [7000, "main"], [8000, "c2"]], "switching": "hand", **extra}


@pytest.fixture
def media(tmp_path):
    return {n: _video(tmp_path / f"{n}.mp4") for n in ("main", "cam2", "cam3", "other")}


def test_validate_names_whats_wrong_with_cameras_and_corners(media):
    assert engine.validate(_plan(multicam={"main": _group(corner={"cam": "c3", "place": "top_left"})}), media) == []
    bad = _group(corner={"cam": "c9"})
    bad["cams"][0].update(shot="sideways", offset_ms=10 ** 12)
    bad["cuts"] = [[3000, "c2"], [1000, "c3"]]
    said = " ".join(engine.validate(_plan(multicam={"main": bad}), media))
    for words in ("unknown kind of shot", "more than a day away", "camera change cannot be read",
                  "corner is not one of this recording's cameras"):
        assert words in said
    itself = _group()
    itself["cams"][0]["asset_id"] = "main"
    assert any("recording itself" in p for p in engine.validate(_plan(multicam={"main": itself}), media))
    gone = dict(media)
    Path(gone["cam2"]["path"]).unlink()
    assert any("missing on the server" in p for p in engine.validate(_plan(multicam={"main": _group()}), gone))
    over = {"id": "o1", "asset_id": "other", "clip_id": "k1", "offset_ms": 0, "length_ms": 2000, "motion": "still",
            "label": "Logo", "place": "middle", "size": 0.9}
    assert any("unknown place" in p for p in engine.validate(_plan(overlays=[over]), media))
    over["place"] = "top_left"
    assert any("of the frame's width" in p for p in engine.validate(_plan(overlays=[over]), media))
    # a setup that cannot be read is named, never a crash, and a camera id that is not text is refused before the
    # timeline and the editor page use it
    for broken in ({"cams": ["x"]}, {"cams": [{"id": "c2", "asset_id": ["cam2"]}]}, {"main": "Camera"},
                   {"main": [1]}, {"cams": [{"id": ["c2"], "asset_id": "cam2"}], "cuts": [[0, ["c2"]]]},
                   {"cams": [{"id": {"c": 2}, "asset_id": "cam2"}]}, {"cams": [{"id": "c2", "asset_id": "cam2",
                                                                              "label": ["Jake"]}]}):
        assert engine.validate(_plan(multicam={"main": {**_group(), **broken}}), media), broken


@pytest.mark.parametrize("w,h", [(1920, 1080), (1080, 1920), (1080, 1080), (1080, 1350)])
def test_a_corner_picture_stays_inside_the_frame_and_off_the_shorts_buttons(w, h):
    for place in multicam.CORNERS:
        for size in (0.15, 0.3, 0.5, None):
            for shape in (16 / 9, 4 / 3, 9 / 16, 3.0):
                x, y, bw, bh = multicam.corner_box(place, size, w, h, shape)
                assert 0 <= x and 0 <= y and x + bw <= w and y + bh <= h and bw % 2 == 0 and bh % 2 == 0
                assert bh <= 0.45 * h + 2
                if (w, h) == (1080, 1920):  # inside the 9:16 safe box: clear of the caption, the buttons
                    assert x >= 0.11 * w - 2 and x + bw <= 0.89 * w + 2
                    assert y >= 0.15 * h - 2 and y + bh <= 0.65 * h + 2
    assert multicam.corner_defaults(1080, 1920) == ("top_right", 0.42)
    assert multicam.border_px(1920, 1080) == 4 and multicam.border_px(640, 360) == 2


def test_a_camera_change_inside_a_dissolve_happens_at_its_edge(media):
    """A join shows one camera per side for the whole dissolve, so a camera change inside it moves to its edge: as
    the next clip comes in, the change happens when the dissolve ends; as a clip goes out, it does not happen."""
    plan = _plan(transition={"type": "dissolve", "ms": 1000},
                 multicam={"main": _group(cuts=[[4600, "c2"], [6300, "c3"]])})
    plan["clips"][1].pop("speed")
    rows = engine.camera_timeline(plan, media)
    k1 = [(r["cam"], r["out_start_ms"], r["out_end_ms"]) for r in rows if r["clip_id"] == "k1"]
    k2 = [(r["cam"], r["out_start_ms"], r["out_end_ms"]) for r in rows if r["clip_id"] == "k2"]
    assert k1 == [("main", 0, 4000)]  # clip 1 goes out during 3-4 s: camera 2 never comes on in it
    assert k2 == [("c2", 3000, 4000), ("c3", 4000, 7000)]  # camera 3 comes on as the dissolve ends
    els, _ = engine.frame_map(plan, 30)
    for k, rows_f in engine._camera_frames(plan, els, 30, media, False, 1920, 1080,  # noqa: SLF001
                                           lambda aid: ({}, None)).items():
        e = els[k]
        tail = els[k + 1]["ov_in"] if k + 1 < len(els) else 0
        assert not any(e["start_f"] < r["f0"] < e["start_f"] + e["ov_in"] or e["end_f"] - tail < r["f0"] < e["end_f"]
                       for r in rows_f)


def test_a_picture_in_the_corner_cameras_corner_moves_to_the_other_corner_on_that_side(media):
    over = {"id": "o1", "asset_id": "other", "clip_id": "k1", "offset_ms": 0, "length_ms": 2000, "motion": "still",
            "label": "Logo", "place": "bottom_right", "size": 0.2}
    plan = _plan(overlays=[over], multicam={"main": _group(corner={"cam": "c2"})})  # 16:9: usually bottom right
    els, _ = engine.frame_map(plan, 30)
    (placed,) = engine._overlay_frames(plan, els, 30, media)[0]  # noqa: SLF001
    assert placed["place"] == "bottom_left"
    plan["multicam"]["main"]["corner"]["place"] = "top_left"
    (placed,) = engine._overlay_frames(plan, els, 30, media)[0]  # noqa: SLF001
    assert placed["place"] == "bottom_right"


def test_the_camera_timeline_follows_each_clips_speed(media):
    plan = _plan(multicam={"main": _group(corner={"cam": "c3"})})
    rows = engine.camera_timeline(plan, media)
    got = [(r["clip_id"], r["cam"], r["corner"], r["out_start_ms"], r["out_end_ms"]) for r in rows]
    # clip 1 plays file 1-5 s at normal speed, clip 2 file 6-10 s at twice the speed from 4 s of the video; camera 3
    # started 1.5 s after the main recording, so it is in the corner only from then on
    assert got == [("k1", "main", None, 0, 500), ("k1", "main", "c3", 500, 1000), ("k1", "c2", "c3", 1000, 2500),
                   ("k1", "c3", None, 2500, 4000),
                   ("k2", "c3", None, 4000, 4500), ("k2", "main", "c3", 4500, 5000), ("k2", "c2", "c3", 5000, 6000)]
    assert engine.cameras_in_use(plan) and not engine.cameras_in_use(_plan())
    assert not engine.cameras_in_use(_plan(multicam={"main": _group(cuts=[])}))
    assert engine.cameras_in_use(_plan(multicam={"main": _group(cuts=[], corner={"cam": "c2"})}))
    over = {"id": "o1", "asset_id": "other", "clip_id": "k1", "offset_ms": 0, "length_ms": 2000, "motion": "still",
            "label": "Logo", "place": "top_left"}
    assert engine.cameras_in_use(_plan(overlays=[over]))  # FilmCraft cannot place a picture in a corner either
    assert set(multicam.used_assets(plan)) >= {"cam2", "cam3"}


# ---------------------------------------------------------------- the editor's edits
@pytest.fixture
def lined(media, monkeypatch):
    """Sound profiles from the made-up conversation: cam2 started 2 s before the main recording, cam3 1.5 s after,
    and "other" has another sound."""
    words, who, n = _talk(minutes=2)
    main, ca, cb = _levels(words, who, n)
    prof = {"main": main, "cam2": _later(ca, 2000), "cam3": _later(cb, -1500),
            "other": _levels(*_talk(minutes=2, seed=21)[:3], seed=22)[0]}
    monkeypatch.setattr(camera_edits, "_profile", lambda a: prof[a["id"]])
    monkeypatch.setattr(camera_edits, "guess_shot", lambda a, at: "wide" if a["id"] == "main" else "close")
    for a in media.values():
        a["probe"]["duration"] = 130.0
    plan = _plan()
    plan["clips"] = [{"id": "k1", "asset_id": "main", "label": "Clip 1", "in_ms": 1000, "out_ms": 60000,
                      "include": True, "kind": "video"},
                     {"id": "k2", "asset_id": "main", "label": "Clip 2", "in_ms": 61000, "out_ms": 110000,
                      "include": True, "kind": "video"}]
    return plan, media, {"main": words}, who


def test_lining_up_switching_and_choosing_cameras_in_the_editor(lined):
    plan, media, words, who = lined
    p, note = vf.apply_edit(plan, {"op": "cameras_add"}, words, media)
    assert "Camera 2 (cam2.mp4, one person)" in note and "Not the same sound, left out: other.mp4" in note
    g = p["multicam"]["main"]
    assert [(c["asset_id"], round(c["offset_ms"] / 10)) for c in g["cams"]] == [("cam2", 200), ("cam3", -150)]
    p, note = vf.apply_edit(p, {"op": "cameras_auto", "mode": "speaker"}, words, media)
    assert note.startswith("Cameras switch to whoever is speaking") and p["multicam"]["main"]["switching"] == "speaker"
    cuts = p["multicam"]["main"]["cuts"]
    assert len(cuts) >= 6 and {c for _, c in cuts} == {"main", "c2", "c3"}
    p, note = vf.apply_edit(p, {"op": "camera_set", "clip_id": "k2", "cam": "c3"}, words, media)
    g = p["multicam"]["main"]
    assert g["switching"] == "hand" and all(c == "c3" for t, c in g["cuts"] if 61000 <= t < 110000)
    assert {r["cam"] for r in engine.camera_timeline(p, media) if r["clip_id"] == "k2"} == {"c3"}
    p, _ = vf.apply_edit(p, {"op": "camera_cut", "clip_id": "k2", "offset_ms": 4000, "cam": "c2"}, words, media)
    assert [65000.0, "c2"] in p["multicam"]["main"]["cuts"]
    p, note = vf.apply_edit(p, {"op": "camera_edit", "cam": "c2", "field": "label", "value": "Jake"}, words, media)
    assert note == "Renamed the camera to Jake"
    p, _ = vf.apply_edit(p, {"op": "camera_edit", "cam": "c2", "field": "offset_ms", "value": 2033.3}, words, media)
    assert p["multicam"]["main"]["cams"][0]["match"] is None and p["multicam"]["main"]["cams"][0]["offset_ms"] == 2033.3
    p, note = vf.apply_edit(p, {"op": "camera_corner", "cam": "c3", "place": "top_left", "size": 0.3}, words, media)
    assert p["multicam"]["main"]["corner"] == {"cam": "c3", "place": "top_left", "size": 0.3}
    p, _ = vf.apply_edit(p, {"op": "camera_corner", "cam": "c2"}, words, media)  # keeps its place and size
    assert p["multicam"]["main"]["corner"] == {"cam": "c2", "place": "top_left", "size": 0.3}
    assert engine.validate(p, media) == []
    p, _ = vf.apply_edit(p, {"op": "cameras_auto", "mode": "off"}, words, media)
    assert p["multicam"]["main"]["cuts"] == [] and p["multicam"]["main"]["corner"]["cam"] == "c2"
    p, note = vf.apply_edit(p, {"op": "cameras_remove"}, words, media)
    assert "multicam" not in p and "stay in your media" in note
    for bad, says in (({"op": "camera_set", "clip_id": "k1", "cam": "c2"}, "no other cameras yet"),
                      ({"op": "cameras_auto", "mode": "off"}, "no other cameras")):
        with pytest.raises(vf.VideoError, match=says):
            vf.apply_edit(plan, bad, words, media)


def test_parts_cut_from_a_cameras_own_file_play_from_the_main_recording_once_lined_up(lined):
    plan, media, words, _ = lined
    plan["clips"].append({"id": "k3", "asset_id": "cam2", "label": "Clip 3", "in_ms": 30000, "out_ms": 35000,
                          "include": True, "kind": "video"})
    plan["clips"].append({"id": "k4", "asset_id": "cam2", "label": "Clip 4", "in_ms": 500, "out_ms": 1500,
                          "include": True, "kind": "video"})  # before the main recording started: stays
    p, note = vf.apply_edit(plan, {"op": "cameras_add"}, words, media)
    k3, k4 = p["clips"][2], p["clips"][3]
    off = p["multicam"]["main"]["cams"][0]["offset_ms"]
    assert k3["asset_id"] == "main" and abs(k3["in_ms"] - (30000 - off)) <= 1 and k3["out_ms"] - k3["in_ms"] == 5000
    assert k4["asset_id"] == "cam2"
    assert "1 part cut from another camera's file now plays from main.mp4 with that camera shown" in note
    assert {r["cam"] for r in engine.camera_timeline(p, media) if r["clip_id"] == "k3"} == {"c2"}
    assert p["multicam"]["main"]["switching"] == "hand" and engine.validate(p, media) == []


def test_a_one_frame_nudge_keeps_the_measured_clock_drift(lined):
    plan, media, words, _ = lined
    p, _ = vf.apply_edit(plan, {"op": "cameras_add"}, words, media)
    cam = p["multicam"]["main"]["cams"][0]
    cam.update(offset_ms=-7500.0, drift_ppm=40.0, match=0.9)
    before = [multicam.to_cam_ms(cam, t) for t in (0, 600000, 3600000)]
    p, note = vf.apply_edit(p, {"op": "camera_edit", "cam": "c2", "field": "nudge_ms", "value": 33.3}, words, media)
    cam = p["multicam"]["main"]["cams"][0]
    assert note == "Camera 2 33 ms later (-7.47 s)" and cam["drift_ppm"] == 40.0 and cam["match"] == 0.9
    assert [round(multicam.to_cam_ms(cam, t) - b, 1) for t, b in zip((0, 600000, 3600000), before)] == [33.3] * 3
    p, _ = vf.apply_edit(p, {"op": "camera_edit", "cam": "c2", "field": "offset_ms", "value": -7000}, words, media)
    cam = p["multicam"]["main"]["cams"][0]
    assert cam["offset_ms"] == -7000 and cam["drift_ppm"] == 40.0 and cam["match"] is None  # lined up by hand
    with pytest.raises(vf.VideoError):
        vf.apply_edit(p, {"op": "camera_edit", "cam": "c2", "field": "nudge_ms", "value": 5000}, words, media)


@pytest.mark.parametrize("edit", [{"op": "cameras_add", "of": ["main"]}, {"op": "cameras_add", "asset_ids": 5},
                                  {"op": "cameras_add", "asset_ids": [["cam2"]]},
                                  {"op": "camera_edit", "cam": "main", "field": "shot", "value": "wide", "of": "main"}])
def test_odd_camera_edits_get_a_plain_error(lined, edit):
    plan, media, words, _ = lined
    if edit["op"] == "camera_edit":  # a group whose main camera cannot be read is mended, not a crash
        plan = {**plan, "multicam": {"main": {**_group(), "main": None}}}
        p, note = vf.apply_edit(plan, edit, words, media)
        assert p["multicam"]["main"]["main"] == {"shot": "wide"}
        return
    with pytest.raises(vf.VideoError):
        vf.apply_edit(plan, edit, words, media)


def test_cameras_that_hear_one_person_loudest_become_close_ups_unless_the_owner_chose(lined, monkeypatch):
    plan, media, words, who = lined
    monkeypatch.setattr(camera_edits, "guess_shot", lambda a, at: "wide")  # no face the picture could read
    p, note = vf.apply_edit(plan, {"op": "cameras_auto", "mode": "speaker"}, words, media)
    g = p["multicam"]["main"]
    assert g["switching"] == "speaker" and [c["shot"] for c in g["cams"]] == ["close", "close"]
    assert "Camera 2 and Camera 3 each hear one person loudest, so they are used as close-ups" in note
    assert g["main"]["shot"] == "wide"
    # a shot the owner chose is kept
    p2, _ = vf.apply_edit(plan, {"op": "cameras_add"}, words, media)
    p2, _ = vf.apply_edit(p2, {"op": "camera_edit", "cam": "c2", "field": "shot", "value": "wide"}, words, media)
    p2, note2 = vf.apply_edit(p2, {"op": "cameras_auto", "mode": "speaker"}, words, media)
    assert [c["shot"] for c in p2["multicam"]["main"]["cams"]] == ["wide", "close"] and "c2" not in note2


def test_switching_to_the_speaker_without_words_changes_angles_and_says_why(lined):
    plan, media, _, _ = lined
    p, note = vf.apply_edit(plan, {"op": "cameras_auto", "mode": "speaker"}, {}, media)
    assert p["multicam"]["main"]["switching"] == "angles"
    assert "could not follow the speaker: this recording has no words yet" in note


def test_the_editor_page_lists_the_cameras(lined):
    plan, media, words, _ = lined
    p, _ = vf.apply_edit(plan, {"op": "cameras_auto", "mode": "speaker"}, words, media)
    view = vf._cameras_view(p, media)
    (g,) = view["cameras"]
    assert g["of"] == "main" and g["switching"] == "speaker" and g["changes"] == len(p["multicam"]["main"]["cuts"])
    assert [c["id"] for c in g["cams"]] == ["main", "c2", "c3"] and g["cams"][1]["filename"] == "cam2.mp4"
    assert view["camera_timeline"] and view["camera_timeline"][0]["cam"] == "main"
    assert vf._cameras_view(_plan(), media) == {"cameras": [], "camera_timeline": []}


def test_pictures_can_go_small_in_a_corner(media):
    over = {"id": "o1", "asset_id": "other", "clip_id": "k1", "offset_ms": 0, "length_ms": 2000, "motion": "still",
            "label": "Logo"}
    p, _ = vf.apply_edit(_plan(overlays=[over]), {"op": "overlay_set", "overlay_id": "o1", "field": "place",
                                                  "value": "bottom_left"}, {}, media)
    p, _ = vf.apply_edit(p, {"op": "overlay_set", "overlay_id": "o1", "field": "size", "value": 0.25}, {}, media)
    assert p["overlays"][0]["place"] == "bottom_left" and p["overlays"][0]["size"] == 0.25
    p, _ = vf.apply_edit(p, {"op": "overlay_set", "overlay_id": "o1", "field": "place", "value": "full"}, {}, media)
    assert "place" not in p["overlays"][0] and "size" not in p["overlays"][0]


# ---------------------------------------------------------------- in plain words
def _asked(text, plan):
    return er.by_rules(text, plan, er.clip_rows(plan, {}))


def test_camera_requests_in_plain_words(media):
    one = _plan()
    three = _plan(multicam={"main": _group()})
    assert _asked("switch cameras to whoever is talking", one)["operations"] == [{"op": "cameras", "mode": "speaker"}]
    assert _asked("follow the speaker", three)["operations"] == [{"op": "cameras", "mode": "speaker"}]
    assert _asked("switch between camera angles", three)["operations"] == [{"op": "cameras", "mode": "angles"}]
    assert _asked("stop switching cameras", three)["operations"] == [{"op": "cameras", "mode": "off"}]
    assert "one camera" in _asked("stop switching cameras", one)["explain"]
    assert _asked("use camera 2 for clip 2", three)["operations"] == [{"op": "camera", "clip_id": "k2", "cam": "c2"}]
    assert _asked("use the wide shot for clip 1", three)["operations"] == [
        {"op": "camera", "clip_id": "k1", "cam": "main"}]
    assert "no camera 5" in _asked("use camera 5 for clip 1", three)["explain"]
    assert _asked("put camera 3 in the top left corner", three)["operations"] == [
        {"op": "camera_corner", "cam": "c3", "place": "top_left"}]
    q = _asked("picture in picture", three)
    assert q["question"] == "Which camera in the corner?" and [c["label"] for c in q["choices"]] == [
        "Camera 2", "Camera 3"]
    assert _asked(q["choices"][1]["request"], three)["operations"] == [{"op": "camera_corner", "cam": "c3"}]
    face = _asked("use the face cam for clip 1", three)
    assert _asked(face["choices"][0]["request"], three)["operations"] == [
        {"op": "camera", "clip_id": "k1", "cam": "c2"}]
    with_corner = _plan(multicam={"main": _group(corner={"cam": "c2", "size": 0.3})})
    assert _asked("remove the corner camera", with_corner)["operations"] == [{"op": "camera_corner", "cam": None}]
    assert "No camera" in _asked("remove the camera in the corner", three)["explain"]
    assert _asked("make the corner camera bigger", with_corner)["operations"] == [
        {"op": "camera_corner", "cam": "c2", "size": 0.41}]
    # not about cameras: left to the other rules
    assert _asked("put the logo in the top right corner", three) is None
    assert _asked("remove clip 2", three)["operations"] == [{"op": "remove", "clip_id": "k2"}]
    assert "operations" not in (_asked("cut the part where the speaker says hi", three) or {})


@pytest.mark.parametrize("text", ["put the wide shot in slow motion", "remove the part where I put my camera in the corner",
                                  "delete the part where I show the wide shot on the screen",
                                  "move the part where I put my camera in the corner to the end",
                                  "put the subscribe button in the corner", "use the wide shot of the lake for the intro",
                                  "speed up the part where I talk about the camera angles"])
def test_requests_that_only_mention_a_camera_are_left_to_the_other_rules(media, text):
    for plan in (_plan(), _plan(multicam={"main": _group()})):
        try:
            got = _asked(text, plan) or {}
        except LookupError:
            continue  # nobody's rule: ClipForge AI's
        said = " ".join(str(v) for v in got.values())
        assert not any(op["op"] in ("cameras", "camera", "camera_corner") for op in got.get("operations") or []), got
        assert "one camera" not in said and "Line up the other camera" not in said and "Which camera" not in said, got


def test_with_two_recordings_with_cameras_a_request_finds_its_recording(media):
    plan = _plan(multicam={"main": _group(), "other": {
        "main": {"label": "Camera 1", "shot": "wide"}, "switching": "off", "cuts": [],
        "cams": [{"id": "c2", "asset_id": "cam3", "label": "Camera 2", "shot": "close", "offset_ms": 0.0,
                  "drift_ppm": 0, "match": 0.6}]}})
    plan["clips"][1]["asset_id"] = "other"
    assert engine.validate(plan, media) == []
    assert _asked("use camera 2 for clip 2", plan)["operations"] == [{"op": "camera", "clip_id": "k2", "cam": "c2"}]
    for text, op in (("put camera 2 in the bottom right corner", {"op": "camera_corner", "cam": "c2",
                                                                  "place": "bottom_right"}),
                     ("go back to one camera", {"op": "cameras", "mode": "off"}),
                     ("switch cameras to whoever is talking", {"op": "cameras", "mode": "speaker"})):
        q = _asked(text, plan)
        assert q["question"].startswith("Which recording?") and len(q["choices"]) == 2, q
        assert _asked(q["choices"][1]["request"], plan)["operations"] == [{**op, "of": "other"}]
    p, note = vf.apply_edit(plan, er._translate(plan, {"op": "camera_corner", "cam": "c2", "of": "other"}), {}, media)
    assert p["multicam"]["other"]["corner"] == {"cam": "c2"} and "corner" not in p["multicam"]["main"]


def test_camera_proposals_are_checked_and_applied_as_editor_edits(lined):
    plan, media, words, _ = lined
    p, _ = vf.apply_edit(plan, {"op": "cameras_add"}, words, media)
    new, notes = er.check(p, [{"op": "camera", "clip_id": "k1", "cam": "c3"},
                              {"op": "camera_corner", "cam": "c2", "place": "bottom_left"}], words, media)
    assert new["multicam"]["main"]["corner"] == {"cam": "c2", "place": "bottom_left"} and len(notes) == 2
    new, _ = er.check(plan, [{"op": "cameras", "mode": "speaker"}], words, media)
    assert new["multicam"]["main"]["switching"] == "speaker"
    for bad in ([{"op": "cameras", "mode": "sideways"}], [{"op": "camera", "cam": "c2"}],
                [{"op": "camera", "clip_id": "k1", "cam": "c9"}]):
        with pytest.raises(er.Invalid):
            er.check(p, bad, words, media)
    prompt = er.build_prompt("switch cameras", p, er.clip_rows(p, words), {}, [])
    assert '"cameras"' in prompt and "Camera 2" in prompt and "cam2.mp4" not in prompt


# ---------------------------------------------------------------- the export
def test_other_cameras_go_on_their_own_track_in_the_export(media):
    plan = _plan(multicam={"main": _group(corner={"cam": "c3"})})
    tl = interchange.build(plan, media, {}, name="x", url_for=lambda a: a["path"])
    tracks = {t["name"]: t for t in tl.otio["tracks"]["children"]}
    cams = tracks[interchange.CAMERAS_TRACK]
    named = [c for c in cams["children"] if c.get("name")]
    assert named and all(c["media_references"]["DEFAULT_MEDIA"]["target_url"].endswith(("cam2.mp4", "cam3.mp4"))
                         for c in named)
    # camera 2 shows main 2-3.5 s: its own file 4-5.5 s (it started 2 s earlier)
    first = named[0]["source_range"]
    assert round(first["start_time"]["value"] / first["start_time"]["rate"], 2) == 4.0
    corner = tracks[interchange.CORNER_TRACK]
    assert corner["enabled"] is False and any(c.get("name") for c in corner["children"])
    assert any("corner" in line for line in interchange.not_carried(plan, False))


# ---------------------------------------------------------------- real files
def _cam_video(path: Path, start: float, seconds: float, cb: int, cr: int) -> dict:
    """A camera's recording of one scene: each frame shows the scene's frame number (from `start`) in its brightness,
    the camera's own colour cast (cb, cr) tells which camera it is, and the sound is the same tone bursts."""
    k = int(start * 30)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"nullsrc=s=320x180:r=30:d={seconds},format=yuv420p,"
                    f"geq=lum='if(lt(X,W/2),30+mod(N+{k},25)*8,30+floor((N+{k})/25)*11)':cb={cb}:cr={cr}",
                    "-f", "lavfi", "-i",
                    f"aevalsrc='0.6*sin(2*PI*440*(t+{start}))*gt(sin(2*PI*0.9*(t+{start}))*"
                    f"sin(2*PI*0.37*(t+{start})+1),0.2)':s=48000:d={seconds}",
                    "-c:v", "libx264", "-crf", "4", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(path)], check=True)
    from clipfoundry.pipeline.ffmpeg_utils import probe

    return {"id": path.stem, "kind": "video", "filename": path.name, "path": str(path), "sha256": path.stem,
            "probe": probe(path)}


def _frames(path: Path, w: int = 320, h: int = 180) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}",
                                   "-pix_fmt", "yuv444p", "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(-1, 3, h, w).astype(np.float64)


def _which(cb: float, cr: float) -> str:
    return "main" if abs(cb - 128) < 15 and abs(cr - 128) < 15 else "c2" if cb < 100 else "c3" if cr > 160 else "?"


def _read(fr: np.ndarray) -> tuple[int, str, str]:
    """(scene frame number, camera on the full picture, camera in the bottom-right corner)."""
    y = fr[0]
    n = int(round((y[40:80, 20:100].mean() - 30) / 8)) + 25 * int(round((y[40:80, 180:240].mean() - 30) / 11))
    return (n, _which(fr[1][20:60, 20:140].mean(), fr[2][20:60, 20:140].mean()),
            _which(fr[1][150:165, 280:305].mean(), fr[2][150:165, 280:305].mean()))


@pytest.fixture
def cameras(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    main = _cam_video(tmp_path / "main.mp4", 2.0, 12, 128, 128)  # the scene from 2 s
    cam2 = _cam_video(tmp_path / "cam2.mp4", 0.0, 15, 70, 128)  # started 2 s before the main recording
    cam3 = _cam_video(tmp_path / "cam3.mp4", 3.5, 12, 128, 190)  # started 1.5 s after it
    return {a["id"]: a for a in (main, cam2, cam3)}


@pytest.mark.slow
def test_real_recordings_line_up_by_their_sound_and_the_levels_are_kept(cameras, tmp_path):
    ref = multicam.sound_profile(cameras["main"])
    c2 = multicam.line_up(ref, multicam.sound_profile(cameras["cam2"]))
    c3 = multicam.line_up(ref, multicam.sound_profile(cameras["cam3"]))
    assert c2 and abs(c2["offset_ms"] - 2000) <= 5 and c3 and abs(c3["offset_ms"] + 1500) <= 5
    kept = list((tmp_path / "data" / "cache" / "multicam").glob("*.npy"))
    assert len(kept) == 3
    assert np.array_equal(multicam.sound_profile(cameras["main"]), ref)


@pytest.mark.slow
def test_every_frame_shows_the_chosen_camera_at_the_synced_moment_with_the_corner_camera(cameras, tmp_path):
    plan = _plan(color={"auto": False, "match": False, "clean": False},
                 multicam={"main": _group(corner={"cam": "c3", "place": "bottom_right", "size": 0.3})})
    plan["clips"][1]["out_ms"] = 9000  # clip 2: file 6-9 s at twice the speed
    assert engine.validate(plan, cameras) == []
    engine.render(plan, cameras, {}, tmp_path / "out.mp4", preview=False)
    frames = _frames(tmp_path / "out.mp4")
    assert len(frames) == 120 + 45
    rows = [_read(f) for f in frames]
    for i, (n, cam, corner) in enumerate(rows):
        if i % 30 in (0, 29):
            continue  # a frame at a camera change may be either side of it
        main_ms = 1000 + i * 1000 / 30 if i < 120 else 6000 + (i - 120) * 2000 / 30
        want = _shown(plan["multicam"]["main"]["cuts"], main_ms)
        assert cam == want, (i, rows[i])
        assert abs(n - (60 + main_ms * 30 / 1000)) <= 1, (i, rows[i])  # the scene's frame: in sync on every camera
        if abs(main_ms - 1500) < 34:
            continue  # camera 3 starts 1.5 s into the main recording: before that, no corner
        # camera 3 in the corner, except before it started and while it is the full picture
        assert corner == ("c3" if want != "c3" and main_ms > 1500 else want), (i, rows[i])
    # a light border around the corner picture, just outside its box (frame 20: camera 3 in the corner)
    from clipfoundry.pipeline.ffmpeg_utils import probe

    info = probe(tmp_path / "out.mp4")
    fw, fh = int(info["width"]), int(info["height"])
    x, y, w, h = multicam.corner_box("bottom_right", 0.3, fw, fh, 16 / 9)
    bd = multicam.border_px(fw, fh)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(tmp_path / "out.mp4"), "-vf",
                                   r"select=eq(n\,20)", "-frames:v", "1", "-pix_fmt", "gray", "-f", "rawvideo", "-"])
    y_plane = np.frombuffer(raw, np.uint8).reshape(fh, fw).astype(np.float64)
    assert y_plane[y - bd: y, x + 4: x + w - 4].mean() > 200
    assert y_plane[y + h: y + h + bd, x + 4: x + w - 4].mean() > 200
    assert y_plane[y + 4: y + h - 4, x - bd: x].mean() > 200


@pytest.mark.slow
def test_the_corner_camera_dissolves_in_with_its_own_side_after_the_title(cameras, tmp_path):
    """The corner camera belongs to its clip: in the dissolve from the title card it fades in with the clip, never
    over the title at full strength."""
    plan = _plan(color={"auto": False, "match": False, "clean": False},
                 title={"enabled": True, "text": "Cameras", "ms": 1500}, transition={"type": "dissolve", "ms": 600},
                 multicam={"main": _group(cuts=[], corner={"cam": "c3", "place": "bottom_right", "size": 0.3})})
    plan["clips"][0]["in_ms"] = 2000  # camera 3 has picture from 1.5 s
    plan["clips"][1]["out_ms"] = 9000
    assert engine.validate(plan, cameras) == []
    engine.render(plan, cameras, {}, tmp_path / "out.mp4", preview=False)
    frames = _frames(tmp_path / "out.mp4")
    els, overlap = engine.frame_map(plan, 30)
    mid = els[1]["start_f"] + overlap // 2  # halfway through the dissolve from the title

    def corner_cr(f: int) -> float:
        return frames[f][2][150:165, 280:305].mean()

    full = corner_cr(els[1]["start_f"] + overlap + 10)
    assert full > 175  # camera 3 in the corner once the clip is in
    assert corner_cr(mid) < full - 15  # halfway: half title, half camera 3
    assert corner_cr(els[1]["start_f"] - 5) < 150  # the title alone: no corner camera
