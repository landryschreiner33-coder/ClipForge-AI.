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


def _level(events: list[tuple[float, bool]]) -> int:
    """0 = the plain framing, 1 = punched in, after every change."""
    return len(events) % 2


def test_on_a_loop_the_shot_size_changes_where_the_end_runs_back_into_the_start():
    words = _words(0.2, 14.0)
    fixed = 0
    # jump cuts with eased changes after them, jump cuts with short stretches, one cut, none (short and long)
    for cuts, dur in (([(3.0, 0.5), (6.0, 0.5)], 14.0), ([(3.0, 0.5), (6.0, 0.5)], 7.5),
                      ([(3.0, 0.5), (6.5, 0.5)], 9.0), ([(3.0, 0.5)], 6.0), ([], 4.6), ([], 12.0)):
        k = int(dur * FPS)
        plain = moves.changes(words, cuts, dur)
        looped = moves.changes(words, cuts, dur, loop=True)
        if len(plain) % 2:                                   # it already ended on the other size: unchanged
            assert looped == plain
        elif all(on for _, on in plain) and all(
                b - a < 3.5 for a, b in zip([0, *(t for t, _ in plain)], [*(t for t, _ in plain), dur])):
            assert looped == plain                           # jump cuts close together: nothing can be done
        else:
            assert _level(looped) == 1, (cuts, dur, plain, looped)   # now it does
            fixed += 1
            assert [e for e in plain if e[1]] == [e for e in looped if e[1]]   # jump cuts are never touched
            bounds = [0.0, *(t for t, _ in looped), dur]
            for i, (t, on_cut) in enumerate(looped):
                if not on_cut and (t, on_cut) not in plain:  # an added change: held 2.5 s before, 1 s after
                    assert t - bounds[i] >= 2.5 - 1e-9 and bounds[i + 2] - t >= 1.0 - 1e-9
        z = moves.punch_curve(words, cuts, k, FPS, moves.PUNCH, loop=True)
        assert z[0] == 1.0                                       # every clip still opens on the plain framing
        if _level(looped):
            assert abs(z[-1] - (1 + moves.PUNCH)) < 0.1 * moves.PUNCH                  # and ends punched in
        assert np.allclose(moves.punch_curve(words, cuts, k, FPS, moves.PUNCH)[:1], 1.0)
    assert fixed >= 2                                            # the even counts really were tested
    # no stretch with room for one more change: one eased change fewer
    assert moves._odd([(1.0, True), (3.0, False)], [], 4.0) == [(1.0, True)]  # noqa: SLF001
    # two jump cuts and no room anywhere: a jump cut always switches, so nothing can be done
    tight = moves.changes(words, [(2.0, 0.5), (4.0, 0.5)], 5.0, loop=True)
    assert tight == [(2.0, True), (4.0, True)]
    # two jump cuts with a short end but a long middle: the extra change goes in the middle
    mid = moves.changes(words, [(1.0, 0.5), (6.0, 0.5)], 7.5, loop=True)
    assert len(mid) == 3 and 3.5 <= mid[1][0] <= 5.0 and not mid[1][1]


def test_an_end_never_cuts_into_a_word_or_shows_a_frame_of_another_shot():
    words = _words(0.6, 4.0)                                 # the last word heard ends at 3.7
    last = words[-1]["end"]
    nxt = {"w": "next", "start": last + 0.08, "end": last + 1.5}   # the clip's end (4.4) cuts it, mostly after
    segs, _ = loops.seam([(0.0, 4.4)], words + [nxt], 0.0, FPS)
    assert last <= segs[-1][1] <= nxt["start"] + 1e-9          # stops before it, not 0.15 s into it
    before = {"w": "was", "start": -0.8, "end": 0.55}         # the clip's start cuts through this one
    segs, _ = loops.seam([(0.0, 4.4)], [before] + words, 0.0, FPS)
    assert before["end"] - 1e-9 <= segs[0][0] <= words[0]["start"]
    assert segs[0][0] > words[0]["start"] - loops.HEAD_KEEP     # later than usual: not into "was"
    # a hard scene cut 0.06 s after the last word: the end goes on it (no 2-3 frames of the next shot)
    seen = []

    def cuts(a, b):
        seen.append((a, b))
        return [c for c in (last + 0.06, 0.55) if a <= c <= b]

    segs, got = loops.seam([(0.0, 4.4)], words, 0.0, FPS, cuts=cuts)
    assert segs[-1][1] <= last + 0.06 + 1e-9 and segs[-1][1] >= last - 1 / FPS
    assert segs[0][0] >= 0.55 - 1e-9 and segs[0][0] <= words[0]["start"]      # starts on the new shot
    assert seen                                                # only asked about the ends it moved
    # a cut in the middle of the last word: that end is left as it was rather than clip the word
    segs, _ = loops.seam([(0.0, 4.4)], words, 0.0, FPS, cuts=lambda a, b: [last - 0.2] if a < last - 0.2 < b else
                         ([last + 0.05] if a <= last + 0.05 <= b else []))
    assert segs[-1][1] <= last + 0.05 + 1e-9


def test_words_the_seam_leaves_out_get_no_caption():
    words = _words(0.6, 4.0) + [{"w": "next", "start": 4.3, "end": 4.9}]
    segs, _ = loops.seam([(0.0, 4.6)], words, 0.0, FPS)
    kept = loops.within(words, segs)
    assert kept == words[:-1]


def test_a_clip_never_gets_under_a_second_at_its_speed():
    words = [{"w": "no", "start": 0.6, "end": 1.0}, {"w": "way!", "start": 1.05, "end": 1.5}]
    assert loops.seam([(0.0, 2.4)], words, 0.0, 30.0, 1.0)[1] is not None     # 1.17 s at 1x: fine
    assert loops.seam([(0.0, 2.4)], words, 0.0, 30.0, 1.25) == ([(0.0, 2.4)], None)   # 0.93 s at 1.25x: not


def test_a_live_clip_hears_the_reactions_of_its_own_window(tmp_path):
    import json

    hop, offset = 0.1, 3600.0
    db = np.full(int((offset + 20) / hop), -30.0) + np.random.default_rng(1).normal(0, 1.5, int((offset + 20) / hop))
    db[int(5.2 / hop):int(6.0 / hop)] = -8.0                     # the stream's loud intro, 5.2-6.0 s in
    db[int((offset + 2.0) / hop):int((offset + 3.0) / hop)] = -8.0   # a cheer 2-3 s into the clip's window
    (tmp_path / "loudness.json").write_text(json.dumps({"hop": hop, "db": db.round(2).tolist()}))
    words = [{"w": "go", "start": 0.5, "end": 1.0}, {"w": "now", "start": 6.5, "end": 7.0}]
    got = render.heard(tmp_path, words, 0.0, 8.0, offset=offset)
    assert len(got) == 1 and got[0][0] == pytest.approx(2.0, abs=0.15) and got[0][1] == pytest.approx(3.0, abs=0.15)
    assert render.heard(tmp_path, words, 0.0, 8.0)[0][0] == pytest.approx(5.2, abs=0.15)   # without: the intro


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
    # the seam's seconds are not "pauses removed" (the Audio tab's note is about silence cleanup)
    assert out[True]["render_info"]["removed_s"] == pytest.approx(0.0, abs=0.05)
    moved = out[True]["render_info"]["moves"]
    assert info["switch"] == ((moved["on_cuts"] + moved["eased"]) % 2 == 1)
    # the owner took the last word out of the captions: it is still said, so the clip still ends after it
    edited = render.render_clip(project, {"id": "c2", "start": 0.0, "end": 6.0, "hook": "",
                                          "edit": {"tracking": "center", "silence": "off",
                                                   "caption_words": words[:-1]}},
                                words, settings, JobContext())
    assert edited["duration"] == pytest.approx(out[True]["duration"], abs=0.011)
    # the captions follow: the first word is lit at its new place (0.1 s in), not 0.7 s in
    ass = (tmp_path / "proj" / "clips" / "c1" / "captions.ass").read_text(encoding="utf-8")
    lit = [int(m) * 60 + float(s) for m, s in re.findall(r"^Dialogue: 1,0:(\d\d):(\d\d\.\d\d)", ass, re.M)]
    assert min(lit) == pytest.approx(first - head - moves.WORD_LEAD, abs=0.011)
