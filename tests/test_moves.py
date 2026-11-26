"""Short-clip editing moves (pipeline/moves.py): punch-ins on jump cuts, a framing change every few seconds, rationed
pushes on stressed words, sound effects from the edit, and the caption changes that go with them (pages that turn
on a cut, words lit a frame early, margins clear of the apps' buttons, a gentle pop)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from clipfoundry import config
from clipfoundry.pipeline import captions, moves, render
from clipfoundry.pipeline.common import JobContext

from synthetic_media import make_video, needs_ffmpeg

FPS = 25.0


def _talk(seconds: float, step: float = 0.4, every: int = 6) -> list[dict]:
    """Continuous speech: a word every `step` seconds, a sentence end every `every` words."""
    out, t, i = [], 0.2, 0
    while t + 0.3 < seconds:
        out.append({"w": "word." if i % every == every - 1 else "word", "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += step
        i += 1
    return out


def _frame(sec: float) -> int:
    return int(round(sec * FPS))


def test_punch_ins_switch_on_jump_cuts_and_ease_everywhere_else():
    words = _talk(20.0)
    cuts = [(3.0, 0.5), (3.3, 0.4), (7.0, 0.6), (15.0, 0.5)]
    n = int(20 * FPS)
    z = moves.punch_curve(words, cuts, n, FPS, moves.PUNCH)
    k = _frame(3.0)
    assert z[k - 1] == pytest.approx(1.0) and z[k] == pytest.approx(1.0 + moves.PUNCH)  # on the cut, in one frame
    assert z[_frame(3.3) - 1] == z[_frame(3.3)]           # a cut 0.3 s after the last change keeps the framing
    assert z[_frame(7.0)] == pytest.approx(1.0)           # the next cut goes back to the wide framing
    events = moves.changes(words, cuts, 20.0)
    times = [0.0, *(t for t, _ in events), 20.0]
    assert max(b - a for a, b in zip(times, times[1:])) <= moves.MAX_HOLD + 1e-6  # something changes every 5 s
    eased = [t for t, on_cut in events if not on_cut]
    assert eased and all(7.0 < t < 15.0 or t > 15.0 for t in eased)
    for t in eased:  # eased changes: small steps, and at a pause between words, never in the middle of one
        seg = z[_frame(t) - 2:_frame(t + moves.EASE) + 2]
        assert np.abs(np.diff(seg)).max() < 0.02
        assert not any(w["start"] < t < w["end"] for w in words)
    assert 1.0 - 1e-9 <= z.min() and z.max() <= 1.0 + moves.PUNCH + 1e-9


def test_a_cut_right_at_the_end_keeps_the_framing_and_small_sources_get_a_smaller_step():
    words = _talk(4.5)
    z = moves.punch_curve(words, [(4.2, 0.5)], int(4.5 * FPS), FPS, moves.PUNCH)
    assert np.allclose(z, 1.0)  # a short clip: one framing, no switch 0.3 s before the end
    assert moves.punch_strength(1080) == moves.PUNCH and moves.punch_strength(720) == moves.PUNCH_LOW_RES
    assert np.allclose(moves.punch_curve(words, [(3.0, 0.5)], 150, FPS, 0.0), 1.0)  # push-ins off


def test_pushes_are_rationed_and_land_on_the_stressed_word():
    words = _talk(20.0)
    near = lambda sec: min(range(len(words)), key=lambda i: abs(words[i]["start"] - sec))  # noqa: E731
    emphasis = {near(0.2), near(2.0), near(4.0), near(9.0), near(19.5)}
    pushed = moves.pushes(words, emphasis, 20.0)
    assert pushed == [words[near(2.0)]["start"], words[near(9.0)]["start"]]  # not at 0.2 s, 6 s apart, not at the end
    n = int(20 * FPS)
    plain = moves.punch_curve(words, [], n, FPS, moves.PUNCH)
    z = moves.punch_curve(words, [], n, FPS, moves.PUNCH, emphasis)
    for at in pushed:
        assert z[_frame(at) + 1] - plain[_frame(at) + 1] == pytest.approx(moves.PUNCH * moves.PUSH_SHARE, abs=0.01)
        assert z[_frame(at - moves.PUSH_LEAD) - 1] == pytest.approx(plain[_frame(at - moves.PUSH_LEAD) - 1])


def test_sound_effects_are_rare_tied_to_the_edit_and_kept_off_the_edges():
    words = [{"w": w, "start": s, "end": s + 0.3, **({"em": True} if em else {})}
             for w, s, em in (("one", 0.1, True), ("two", 2.0, False), ("three", 3.0, True), ("four", 8.0, True),
                              ("five", 9.5, True))]
    events = moves.effect_events(words, [2.0], 10.0)
    assert [(e["kind"], e["at"]) for e in events] == [("whoosh", 2.0), ("pop", round(8.0 - moves.WORD_LEAD, 3))]
    assert moves.effect_events(words, [], 10.0)[0]["kind"] == "pop"  # no pushes: the key words still pop
    # a pushed key word gets the whoosh only (its pop would be 40 ms earlier and too close)
    assert [e["kind"] for e in moves.effect_events(words, [3.0], 10.0)] == ["whoosh", "pop"]


def test_effect_sounds_are_quiet_varied_and_land_on_time(tmp_path):
    events = [{"at": 1.0, "kind": "whoosh", "n": 0}, {"at": 3.0, "kind": "pop", "n": 1}]
    track = moves.effects_track(events, 5.0)
    assert np.abs(track).max() <= 10 ** (moves.POP_PEAK_DB / 20) + 1e-6  # at least 22 dB under full scale
    env = np.abs(track[:, 0]) + np.abs(track[:, 1])
    whoosh = env[: int(2.5 * moves.SR)]
    assert abs(np.argmax(np.convolve(whoosh, np.ones(480) / 480, "same")) / moves.SR - 1.0) < 0.08  # lands at 1.0 s
    assert env[int(2.6 * moves.SR):int(2.995 * moves.SR)].max() < 1e-6 < env[int(3.0 * moves.SR):].max()
    assert not np.allclose(moves.pop(0), moves.pop(1)) and not np.allclose(moves.whoosh(0), moves.whoosh(1))
    path = moves.write_wav(track, tmp_path / "fx.wav")
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getframerate()) == (2, 48000)
        assert abs(w.getnframes() / 48000 - 5.0) < 0.01


def test_captions_turn_the_page_on_a_cut_light_words_early_and_stay_clear_of_the_buttons():
    words = [{"w": w, "start": 0.2 + i * 0.4, "end": 0.5 + i * 0.4}
             for i, w in enumerate("we cut here and then go".split())]
    assert [len(c) for c in captions.chunk_words(words, "clean")] == [5, 1]
    assert [len(c) for c in captions.chunk_words(words, "clean", [1.05])] == [3, 3]  # the cut starts a new page
    assert [len(c) for c in captions.chunk_words(words, "clean", [0.55])] == [5, 1]  # never a one-word page
    ass = captions.build_ass(words, {"caption_style": "clean", "page_breaks": [1.05]}, 3.0)
    style = next(ln for ln in ass.splitlines() if ln.startswith("Style: Caption"))
    assert f",{captions.SIDE_MARGIN},{captions.SIDE_MARGIN}," in style
    first = next(ln for ln in ass.splitlines() if ln.startswith("Dialogue: 1"))
    assert first.split(",")[1] == "0:00:00.16"  # 0.2 s minus the lead: lit a frame before it is heard
    assert "\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)" in first
    minimal = captions.build_ass(words, {"caption_style": "minimal"}, 3.0)
    assert "\\t(0,90" not in minimal


def test_sound_effects_is_a_setting_the_editor_skills_and_full_cloud_know():
    from clipfoundry import api
    from clipfoundry.fullcloud import worker_api
    from clipfoundry.studio import capabilities, guidance

    assert config.DEFAULT_SETTINGS["sound_effects"] is True
    assert config.validate_settings({"sound_effects": "off"})["sound_effects"] is False
    assert "sound_effects" in api.EDIT_KEYS and "sound_effects" in worker_api.SETTING_KEYS
    assert capabilities.FIELDS["sound_effects"].kind == "bool"
    # one choice for clips and full videos (two fields of one name used to hide the clips' one)
    assert set(capabilities.FIELDS["sound_effects"].modes) >= {"highlights", "full_stories", "full_video"}
    assert capabilities.clean({"sound_effects": False}, ("highlights",))[0] == {"sound_effects": False}
    assert guidance.render_values({"values": {"sound_effects": False}}) == {"sound_effects": False}
    opts = render.effective_options({**config.DEFAULT_SETTINGS}, {}, {"sound_effects": False})
    assert opts["sound_effects"] is False


@needs_ffmpeg
def test_a_real_clip_gets_punch_ins_on_its_cuts_and_quiet_effects(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.init()
    src = make_video(tmp_path / "src.mp4", seconds=14.0)
    meta = probe(src)
    project = {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(tmp_path / "proj"),
               "info": meta, "options": {}, **meta}
    # speech with three long pauses (cut out: jump cuts); "never" and "100" are stressed
    words, t = [], 0.2
    for k, sentence in enumerate(("I never knew this worked.", "It took 100 days to learn.",
                                  "Then everything was simple.", "Try it yourself today.")):
        for tok in sentence.split():
            words.append({"w": tok, "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.4
        t += 1.2
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast"}
    edit = {"tracking": "center", "silence": "aggressive", "caption_emphasis": True}
    outs = {}
    for fx in (True, False):
        clip = {"id": f"c{int(fx)}", "start": 0.0, "end": t, "hook": "", "edit": {**edit, "sound_effects": fx}}
        outs[fx] = render.render_clip(project, clip, words, settings, JobContext())
    on = outs[True]["render_info"]["moves"]
    assert on["punch"] == moves.PUNCH_LOW_RES and on["on_cuts"] >= 2 and on["effects"]
    assert outs[False]["render_info"]["moves"]["effects"] == []
    assert not (Path(outs[True]["output_path"]).parent / "effects.wav").exists()  # only the encode needs it
    assert outs[True]["render_info"]["audio_processing"]["effects_gain_db"] <= 0.0

    def samples(path: str) -> np.ndarray:
        import subprocess

        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "48000",
                                       "-f", "f32le", "-"])
        return np.frombuffer(raw, "<f4")

    with_fx, without = samples(outs[True]["output_path"]), samples(outs[False]["output_path"])
    n = min(len(with_fx), len(without)) // 2400 * 2400
    blocks = lambda x: np.sqrt(np.mean(x[:n].reshape(-1, 2400) ** 2, axis=1))  # noqa: E731  (50 ms blocks)
    fx, speech = blocks(with_fx - without), blocks(without)  # the speech is set the same way with or without them
    assert fx.max() > 1e-3                                    # the effects are there...
    loud = np.median(speech[speech > 0.01])
    assert 20 * np.log10(fx.max() / loud) < -12               # ...well under the speech, even at their loudest
    assert (fx > 1e-3).mean() < 0.15                          # and only now and then


def _loop_first_frames(tl: render.Timeline, start: float, fps: float) -> list[int]:
    """The output frame at which render_clip's frame loop first shows each part after the first (copied loop)."""
    n_out = int(round(tl.duration * fps))
    n_src = int(round((tl.segs[-1][1] - start) * fps)) + 2
    part_of, written = [], 0
    for k in range(n_src):
        t_src = start + k / fps
        if not tl.contains(t_src) or written >= n_out:
            continue
        out_t = tl.to_out(t_src)
        while written < n_out and written <= out_t * fps + 0.5:
            part_of.append(next(i for i, (a, b) in enumerate(tl.segs) if a - 1e-6 <= t_src < b - 1e-6))
            written += 1
    return [part_of.index(i) for i in range(1, len(tl.segs)) if i in part_of]


@pytest.mark.parametrize("speed", [0.8, 1.0, 1.25, 1.5])
def test_the_zoom_switches_on_the_first_frame_of_the_new_shot_at_any_speed(speed):
    rng = np.random.default_rng(7)
    fps, start = 30.0, 12.0
    for _ in range(40):
        t, segs = start, []
        for _ in range(4):
            a = t + rng.integers(0, 20) / fps
            b = a + rng.integers(30, 90) / fps
            segs.append((a, b))
            t = b + rng.integers(5, 30) / fps
        tl = render.Timeline(segs, speed)
        frames = tl.cut_frames(start, fps)
        assert [int(round(f * fps)) for f in frames] == _loop_first_frames(tl, start, fps)
        cuts = moves.jump_cuts(segs, tl.speed, frames)
        z = moves.punch_curve(_talk(tl.duration), cuts, int(round(tl.duration * fps)), fps, moves.PUNCH)
        for at, on_cut in moves.changes(_talk(tl.duration), cuts, tl.duration):
            if on_cut:
                k = int(round(at * fps))
                assert z[k] != z[k - 1] and z[k - 1] == z[k - 2]  # the old shot keeps its framing to its last frame


def test_a_push_never_eases_across_a_cut_and_never_spikes_after_one():
    fps = 25.0
    words = _talk(20.0)
    near = lambda sec: min(range(len(words)), key=lambda i: abs(words[i]["start"] - sec))  # noqa: E731
    word = words[near(5.0)]["start"]
    cut = word - 0.12                                     # the stressed word is heard just after a jump cut
    z = moves.punch_curve(words, [(cut, 1.0)], int(20 * fps), fps, moves.PUNCH, {near(5.0)})
    k = int(round(cut * fps))
    assert np.allclose(z[k - 8:k], z[k - 8])              # the old shot does not creep in before the cut
    assert z[k] == pytest.approx(1.0 + moves.PUNCH * (1 + moves.PUSH_SHARE))  # the push comes in with the cut
    # a push that lets go on a cut whose time is a hair past a frame boundary (float noise)
    word = words[near(2.0)]["start"]
    end = 4.0 + 1e-12
    z = moves.punch_curve(words, [(end, 1.0)], int(20 * fps), fps, moves.PUNCH, {near(2.0)})
    k = int(round(end * fps))
    assert z[k] == pytest.approx(1.0 + moves.PUNCH) and z[k + 1] == pytest.approx(z[k])  # no one-frame spike


def test_caption_pages_turn_with_the_cut_even_when_a_word_follows_it_closely():
    words = [{"w": w, "start": s, "end": s + 0.25}
             for w, s in (("one", 0.2), ("two", 0.5), ("three", 0.8), ("four", 1.13), ("five", 1.45), ("six", 1.75))]
    ass = captions.build_ass(words, {"caption_style": "clean", "page_breaks": [1.1]}, 3.0)
    texts = [ln.split(",", 9)[9] for ln in ass.splitlines() if ln.startswith("Dialogue: 1")]
    assert any("four" in t and "three" not in t for t in texts), texts
    assert not any("three" in t and "four" in t for t in texts), texts


def test_effects_follow_the_coloured_words_and_the_speech_level():
    words = [{"w": "one", "start": 1.0, "end": 1.3, "em": True}, {"w": "two", "start": 6.0, "end": 6.3, "em": True}]
    assert len(moves.effect_events(words, [], 10.0)) == 2
    assert moves.effects_gain(-14.0, 0.0) == 0.0          # normalized speech: the effects as made
    assert moves.effects_gain(-20.0, 3.0) == pytest.approx(-3.0)  # normalization held back by peaks
    assert moves.effects_gain(-26.0, 0.0) == pytest.approx(-12.0)  # normalization off, quiet speech
    assert moves.effects_gain(None, 0.0) == 0.0
    graph = render._audio_filter([(0.0, 5.0)], 0.0, {"normalize_audio": True, "gain_db": -10},
                                 normalization_gain_db=3.0, effects_label="2:a:0", effects_gain_db=-2.5)
    mix = graph.index("amix")
    assert graph.index("volume=3.000000dB") < mix < graph.index("volume=-10.00dB")  # the owner's volume: whole mix
    assert "volume=-2.50dB[fx]" in graph
