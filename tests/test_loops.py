"""Loop endings for short clips (pipeline/loops.py): the clip stops just after its last sound and starts just before
its first, so the replay runs straight back into the start, and the shot size changes on that seam like on every
other jump cut (moves.punch_curve with loop=True)."""
from __future__ import annotations

import math
import re

import numpy as np
import pytest

from clipfoundry import config
from clipfoundry.pipeline import loops, moves, render
from clipfoundry.pipeline.common import JobContext

from synthetic_media import make_video, needs_ffmpeg

FPS = 25.0


def _words(t0: float, t1: float, step: float = 0.4) -> list[dict]:
    out, t, i = [], t0, 0
    while t + 0.3 <= t1 + 1e-9:
        out.append({"w": "word." if i % 6 == 5 else "word", "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += step
        i += 1
    return out


def _on_grid(x: float, start: float = 0.0) -> bool:
    k = (x - start) * FPS
    return abs(k - round(k)) < 1e-6


def test_the_seam_keeps_a_breath_before_the_first_word_and_cuts_just_after_the_last():
    words = _words(0.6, 6.0)                              # 0.6 s of quiet before, the last word ends at 5.7
    first, last = words[0]["start"], words[-1]["end"]
    segs, got = loops.seam([(0.0, 6.6)], words, 0.0, FPS)
    (a, b), = segs
    assert first - a == pytest.approx(loops.HEAD_KEEP, abs=1 / FPS + 1e-9) and a <= first - loops.HEAD_KEEP + 1e-9
    assert b - last == pytest.approx(loops.TAIL_KEEP, abs=1 / FPS + 1e-9) and b >= last + loops.TAIL_KEEP - 1e-9
    assert _on_grid(a) and _on_grid(b)
    assert got["head_s"] == pytest.approx(a) and got["tail_s"] == pytest.approx(6.6 - b)
    # the pause the viewer hears where the end runs back into the start: about the pause between two sentences
    assert 0.2 <= got["seam_s"] <= 0.3 + 2 / FPS


def test_a_long_quiet_moment_at_either_end_is_left_alone():
    words = _words(2.0, 5.0)                               # 2 s before the first word, 2 s after the last
    segs, got = loops.seam([(0.0, 7.4)], words, 0.0, FPS)
    assert segs == [(0.0, 7.4)] and got["head_s"] == 0 and got["tail_s"] == 0
    # one end quiet for long (left), the other short (tightened)
    segs, got = loops.seam([(1.5, 7.4)], words, 1.5, FPS)
    assert segs[0][0] > 1.5 and segs[-1][1] == 7.4 and got["tail_s"] == 0


def test_a_laugh_after_the_last_word_stays_and_the_cut_comes_after_it():
    words = _words(0.5, 4.0)
    last = words[-1]["end"]
    segs, _ = loops.seam([(0.0, 6.0)], words, 0.0, FPS, loud=[(last + 0.2, last + 0.9)])
    assert segs[-1][1] >= last + 0.9 + loops.TAIL_KEEP - 1e-9 and segs[-1][1] < 6.0


def test_only_the_ends_change_and_cut_words_do_not_count():
    words = _words(0.5, 3.0) + [{"w": "um", "start": 3.4, "end": 3.7}] + _words(4.5, 7.0)
    segs_in = [(0.0, 3.2), (4.3, 7.8)]                    # the "um" and its pause were cut out
    segs, got = loops.seam(segs_in, words, 0.0, FPS)
    assert segs[0][1] == 3.2 and segs[1][0] == 4.3       # the jump cut inside stays where it was
    assert segs[0][0] > 0 and segs[1][1] < 7.8
    # a filler that is cut is not the "last word": the end follows the last word heard
    segs, _ = loops.seam([(0.0, 3.2)], words, 0.0, FPS)
    assert segs[-1][1] < 3.2 or segs[-1][1] == pytest.approx(3.2)


def test_nothing_happens_without_words_or_when_the_clip_would_get_too_short():
    assert loops.seam([(0.0, 5.0)], [], 0.0, FPS) == ([(0.0, 5.0)], None)
    one = [{"w": "hi", "start": 0.5, "end": 0.7}]
    assert loops.seam([(0.0, 1.5)], one, 0.0, FPS) == ([(0.0, 1.5)], None)   # 0.4 + 0.15 s would be left


def test_the_seam_is_measured_in_the_clip_s_own_time_at_its_speed():
    words = _words(0.6, 6.0)
    _, at1 = loops.seam([(0.0, 6.6)], words, 0.0, FPS, 1.0)
    _, faster = loops.seam([(0.0, 6.6)], words, 0.0, FPS, 1.15)
    assert faster["seam_s"] == pytest.approx(at1["seam_s"] / 1.15, abs=1e-3)


def test_on_a_loop_the_shot_size_changes_where_the_end_runs_back_into_the_start():
    words = _words(0.2, 14.0)
    n = int(14.0 * FPS)
    for cuts in ([(3.0, 0.5), (6.0, 0.5)], [(3.0, 0.5), (6.0, 0.5), (9.0, 0.5)], []):
        events = moves.changes(words, cuts, 14.0)
        plain = moves.punch_curve(words, cuts, n, FPS, moves.PUNCH)
        looped = moves.punch_curve(words, cuts, n, FPS, moves.PUNCH, loop=True)
        assert plain[0] == 1.0                                   # without a loop ending: as before
        if events:
            assert looped[0] != pytest.approx(looped[-1])       # the seam switches the size
        if len(events) % 2:                                      # it already ended on the other size: unchanged
            assert np.allclose(plain, looped)
        elif events:                                             # it started tight instead, then alternated
            assert looped[0] == pytest.approx(1 + moves.PUNCH)
            assert np.allclose(looped[looped < 1 + moves.PUNCH - 1e-9].min(), 1.0)
    assert not moves.opens_tight([], True) and not moves.opens_tight([(1.0, True), (2.0, True)], False)


def test_loop_ending_is_a_setting_the_editor_and_full_cloud_know():
    from clipfoundry import api
    from clipfoundry.fullcloud import worker_api
    from clipfoundry.pipeline import artifact

    assert config.DEFAULT_SETTINGS["loop_ending"] is True
    assert config.validate_settings({"loop_ending": "off"})["loop_ending"] is False
    assert "loop_ending" in api.EDIT_KEYS and "loop_ending" in worker_api.SETTING_KEYS
    assert "loop_ending" in artifact.SETTINGS_KEYS
    assert render.effective_options({**config.DEFAULT_SETTINGS}, {}, {"loop_ending": False})["loop_ending"] is False


@needs_ffmpeg
def test_a_real_clip_stops_just_after_its_last_word(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.init()
    src = make_video(tmp_path / "src.mp4", seconds=8.0)
    meta = probe(src)
    project = {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(tmp_path / "proj"),
               "info": meta, "options": {}, **meta}
    words = _words(0.7, 5.2)                       # 0.7 s of quiet before, 1 s after (clip 0-6 s)
    first, last = words[0]["start"], words[-1]["end"]
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast"}
    out = {}
    for loop in (True, False):
        clip = {"id": f"c{int(loop)}", "start": 0.0, "end": 6.0, "hook": "",
                "edit": {"tracking": "center", "silence": "off", "loop_ending": loop}}
        out[loop] = render.render_clip(project, clip, words, settings, JobContext())
    fps = out[True]["render_info"]["fps"]
    head = math.floor((first - loops.HEAD_KEEP) * fps + 1e-6) / fps
    tail = math.ceil((last + loops.TAIL_KEEP) * fps - 1e-6) / fps
    assert out[True]["duration"] == pytest.approx(tail - head, abs=0.011)
    assert float(probe(out[True]["output_path"])["duration"]) == pytest.approx(tail - head, abs=0.08)
    info = out[True]["render_info"]["loop"]
    assert info["head_s"] == pytest.approx(head, abs=1e-3) and info["tail_s"] == pytest.approx(6.0 - tail, abs=1e-3)
    assert "loop" not in out[False]["render_info"] and out[False]["duration"] == pytest.approx(6.0, abs=0.011)
    # the captions follow: the first word is lit at its new place (0.1 s in), not 0.7 s in
    ass = (tmp_path / "proj" / "clips" / "c1" / "captions.ass").read_text(encoding="utf-8")
    lit = [int(m) * 60 + float(s) for m, s in re.findall(r"^Dialogue: 1,0:(\d\d):(\d\d\.\d\d)", ass, re.M)]
    assert min(lit) == pytest.approx(first - head - moves.WORD_LEAD, abs=0.011)
