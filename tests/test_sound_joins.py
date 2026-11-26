"""How a full video's sound is joined (studio/sound_joins.py and the engine's sound section): split edits (J and L
cuts) only where no word changes hands, equal-power crossfades at cuts between recordings that never reach into a
cut-out word, room tone under title cards, photos and silent videos, music back-timed to end on the last frame, and
the editing defaults that go with them (hard cuts between recordings, punch-ins at jump cuts, rationed whooshes, a
short's hook drawn on its first frame, click-free clip edges)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.studio import sound_joins as SJ

FPS = 30


def _el(asset: str, start_f: int, frames: int, src_in_ms: int, ov_in: int = 0) -> dict:
    return {"asset_id": asset, "start_f": start_f, "end_f": start_f + frames, "frames": frames,
            "src_in_ms": src_in_ms, "ov_in": ov_in, "kind": "video"}


def _words(*spans: tuple[float, float]) -> list[dict]:
    return [{"w": "w", "start": a, "end": b} for a, b in spans]


def test_a_j_cut_where_both_sides_pause_and_an_l_cut_when_the_next_has_no_room_before_it():
    els = [_el("A", 0, 90, 0), _el("B", 90, 90, 2000)]
    words = {"A": _words((0.2, 2.4)), "B": _words((2.3, 4.5))}   # A pauses 0.6 s before its end, B 0.3 s after in
    assert SJ.split_edits(els, [True, True], words, {"A": 10000, "B": 10000}, FPS) == {1: (8, 0)}
    # B starts at the very beginning of its file: nothing before it to lead with, so A's room sound runs on instead
    els[1]["src_in_ms"] = 0
    words["B"] = _words((0.6, 2.5))
    assert SJ.split_edits(els, [True, True], words, {"A": 10000, "B": 10000}, FPS) == {1: (0, 8)}
    # a shorter split when only a short pause is there: B's first word 0.3 s after its in point allows 4 frames
    words["B"] = _words((0.33, 2.5))
    assert SJ.split_edits(els, [True, True], words, {"A": 10000, "B": 10000}, FPS) == {1: (0, 6)}


def test_no_split_where_a_word_would_change_hands_or_nothing_is_known():
    els = [_el("A", 0, 90, 0), _el("B", 90, 90, 2000)]
    lengths = {"A": 10000, "B": 10000}
    busy = {"A": _words((0.2, 2.95)), "B": _words((1.95, 4.5))}   # talking right up to both cut points
    assert SJ.split_edits(els, [True, True], busy, lengths, FPS) == {}
    assert SJ.split_edits(els, [True, True], {"A": []}, lengths, FPS) == {}  # B was never transcribed
    same = [_el("A", 0, 90, 0), _el("A", 90, 90, 5000)]            # a jump cut inside one recording: never
    assert SJ.split_edits(same, [True, True], {"A": []}, {"A": 10000}, FPS) == {}
    dissolve = [_el("A", 0, 90, 0), _el("B", 78, 90, 2000, ov_in=12)]
    assert SJ.split_edits(dissolve, [True, True], {"A": [], "B": []}, lengths, FPS) == {}
    assert SJ.split_edits(els, [True, False], {"A": [], "B": []}, lengths, FPS) == {}  # a muted side
    tiny = [_el("A", 0, 10, 0), _el("B", 10, 90, 2000)]           # a clip too short to give frames away
    assert SJ.split_edits(tiny, [True, True], {"A": [], "B": []}, lengths, FPS) == {}


def test_equal_power_crossfades_keep_the_level_of_two_unrelated_sounds(tmp_path):
    from clipfoundry.studio import engine

    rng = np.random.default_rng(3)
    n, xf = 48000, 4800
    a = (rng.standard_normal((n, 2)) * 0.1).astype("<f4")
    b = (rng.standard_normal((n, 2)) * 0.1).astype("<f4")
    a.tofile(tmp_path / "a.raw")
    b.tofile(tmp_path / "b.raw")
    for power in (False, True):
        parts = [{"start": 0, "n": n, "path": tmp_path / "a.raw", "ramp_out": xf, "power_out": power},
                 {"start": n - xf, "n": n, "path": tmp_path / "b.raw", "ramp_in": xf, "power_in": power}]
        engine.mix(2 * n - xf, parts, tmp_path / "bus.raw")
        bus = np.fromfile(tmp_path / "bus.raw", dtype="<f4").reshape(-1, 2)
        mid = bus[n - xf // 2 - 600:n - xf // 2 + 600]
        dip = 20 * np.log10(np.sqrt((mid ** 2).mean()) / 0.1)
        assert (abs(dip) < 0.6) if power else (dip < -2.0), (power, dip)


def test_room_tone_comes_from_the_quietest_pause_and_loops_without_seams():
    words = _words((0.5, 2.0), (2.4, 5.0), (8.0, 9.0))
    gaps = SJ.tone_candidates(words, 10.0)
    assert gaps == [pytest.approx((5.12, 7.88)), pytest.approx((9.12, 9.88))]  # longest first, kept off the words
    assert SJ.tone_candidates(_words((0.2, 9.8)), 10.0) == []                   # talking all the way: none
    long = SJ.tone_candidates([], 20.0)[0]
    assert long[1] - long[0] == pytest.approx(SJ.TONE_MAX_S)                      # a sample, looped later
    assert not any(any(w["start"] < b and w["end"] > a for w in words) for a, b in gaps)
    assert SJ.usable_tone(-55.0) and not SJ.usable_tone(-90.0) and not SJ.usable_tone(-20.0)
    rng = np.random.default_rng(5)
    sample = rng.standard_normal((24000, 2)).astype(np.float32) * 0.01
    tone = SJ.loop_tone(sample, 5 * 48000, 48000)
    assert tone.shape == (5 * 48000, 2)
    blocks = np.sqrt((tone[: len(tone) // 2400 * 2400].reshape(-1, 2400, 2) ** 2).mean(axis=(1, 2)))
    assert 20 * np.log10(blocks.max() / blocks.min()) < 2.5  # no dips or bumps where it repeats


def test_music_is_started_so_its_own_end_lands_on_the_last_frame():
    assert SJ.back_time_offset(30, 100) == 70          # a song longer than the video: its last 30 play
    assert SJ.back_time_offset(250, 100) == 50         # a bed that repeats: skip 50, then 2 whole repeats
    assert SJ.back_time_offset(300, 100) == 0
    assert SJ.back_time_offset(30, 0) == 0             # unknown length: as before


def test_which_music_is_back_timed_and_room_tone_in_blocks():
    from clipfoundry.studio import engine

    bed = {"role": "music", "asset_id": "m"}
    assert SJ.back_times(bed, "ClipForge music - Sunny steps (balanced).m4a")   # a bed in whole bars
    assert not SJ.back_times(bed, "my song.mp3")                                # your song keeps its start
    assert SJ.back_times({**bed, "back_time": True}, "my song.mp3")             # unless you tick it
    assert not SJ.back_times({**bed, "back_time": False}, "ClipForge music - Sunny steps (balanced).m4a")
    assets = {"m": {"filename": "ClipForge music - x.m4a"}}
    to_end = {"loop": True, "out_start_ms": 0, "out_end_ms": 10000}
    assert engine._back_timed(bed, to_end, 10000, assets)  # noqa: SLF001
    # music set to play for 3 s (under the opening only) keeps its start: its ending is not the video's
    assert not engine._back_timed(bed, {**to_end, "out_end_ms": 3000}, 10000, assets)  # noqa: SLF001
    assert not engine._back_timed(bed, {**to_end, "loop": False}, 10000, assets)  # noqa: SLF001
    # room tone is made a copy at a time: an hour costs no more memory than a second
    sample = np.random.default_rng(2).standard_normal((4800, 2)).astype(np.float32)
    blocks = list(SJ.loop_tone_blocks(sample, 3600 * 48000 // 100, 48000))
    assert max(len(b) for b in blocks) <= len(sample) and sum(len(b) for b in blocks) == 3600 * 480
    assert np.allclose(np.concatenate(blocks)[:48000], SJ.loop_tone(sample, 48000, 48000))


def test_room_tone_steps_aside_where_a_voiceover_plays():
    from clipfoundry.studio import engine

    els = [{"start_f": 0, "end_f": 90}, {"start_f": 90, "end_f": 150}, {"start_f": 150, "end_f": 240}]
    items = {"v": {"role": "voiceover"}, "m": {"role": "music"}}
    placed = [{"audio_id": "v", "track": "voiceover", "out_start_ms": 3200, "out_end_ms": 4500},
              {"audio_id": "m", "track": "music", "out_start_ms": 0, "out_end_ms": 8000}]
    tracks = engine.default_tracks()
    spans = engine._voiceovers(placed, items, tracks)  # noqa: SLF001
    assert spans == [(3200, 4500)]
    assert engine._voiceovers(placed, items, {**tracks, "voiceover": {"mute": True}}) == []  # noqa: SLF001
    # a voiceover inside a photo (3.0-5.0 s): the photo keeps its tone before and after it
    assert engine._narrated(els, spans, 30) == set()  # noqa: SLF001
    # one that covers it from end to end, also in two pieces or with a rounding sliver left: no tone at all
    assert engine._narrated(els, [(2990, 5000.4)], 30) == {1}  # noqa: SLF001
    assert engine._narrated(els, [(3000, 4200), (4100, 5000)], 30) == {1}  # noqa: SLF001
    # a voiceover that runs 10 ms on past its clip takes nothing from the photo after it
    assert engine._narrated(els, [(0, 3010)], 30) == {0}  # noqa: SLF001
    assert SJ.uncovered_ms(0, 1000, [(100, 300), (200, 400), (900, 1200)]) == 600
    # the tone is silent under the voiceover and fades over `ramp` samples just outside it
    gain = SJ.duck_gain(0, 1000, [(400, 600)], 100)[:, 0]
    assert gain[0] == gain[299] == gain[700] == gain[999] == 1.0
    assert gain[400] == gain[500] == gain[600] == 0.0 and gain[350] == pytest.approx(0.5)
    assert gain[650] == pytest.approx(0.5)
    assert SJ.duck_gain(0, 250, [(400, 600)], 100) is None  # nowhere near: nothing to change
    assert SJ.duck_gain(1000, 100, [(400, 600)], 100) is None


def test_the_editing_defaults_that_go_with_it():
    from clipfoundry.pipeline import captions, render
    from clipfoundry.studio import smart_edit, video_flow

    assert video_flow.FEEL_TRANSITIONS["balanced"] == ("cut", 0) and video_flow.FEEL_TRANSITIONS["calm"][0] == \
        "dissolve"
    assert smart_edit.options({"smart_edit": "smart"}, {})["punch_in"] is True   # wide/tight at jump cuts
    assert smart_edit.options({"smart_edit": "smart", "punch_in": False}, {})["punch_in"] is False
    ass = captions.build_ass([{"w": "hi", "start": 0.3, "end": 0.6}], {"hook_overlay": True}, 3.0, "The hook")
    assert "{\\fad(0,250)}The hook" in ass  # the hook is drawn on frame 0
    graph = render._audio_filter([(0.0, 5.0)], 0.0, {"normalize_audio": False})
    assert "afade=t=in:st=0:d=0.01" in graph and "afade=t=out:st=4.9900:d=0.01" in graph


def test_whooshes_at_changes_of_recording_are_rationed():
    from clipfoundry.studio import smart_edit

    clips = [{"id": f"c{k}", "asset_id": f"r{k}", "kind": "video", "in_ms": 0, "out_ms": 6000, "include": True}
             for k in range(8)]
    plan = {"clips": clips, "transition": {"type": "cut", "ms": 0}, "title": {"enabled": False, "text": "", "ms": 0},
            "audio": [], "overlays": []}
    stats: dict = {}
    smart_edit._place_effects(plan, {"whoosh": {"id": "w", "filename": "w.m4a"}}, stats)  # noqa: SLF001
    at = [i["anchor"]["clip_id"] for i in plan["audio"]]
    assert at == ["c1", "c4", "c7"]  # a change every 6 s; a whoosh at most every 15 s


# ------------------------------------------------------------------ a real render
def _recording(path: Path, freq: int, speak: tuple[float, float], hum: int, seconds: float = 6.0,
               seed: int | None = None) -> Path:
    """A video whose sound is a tone (the "speech") from speak[0] to speak[1] over its room: quiet pink noise and
    a faint hum at `hum` Hz that tells the two rooms apart. The noise has a fixed seed (FFmpeg picks a random one),
    so a measurement gives the same answer every run."""
    a, b = speak
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000:duration={seconds}",
                    "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.01:duration={seconds}:sample_rate=48000:"
                    f"seed={hum if seed is None else seed}",
                    "-f", "lavfi", "-i", f"sine=frequency={hum}:sample_rate=48000:duration={seconds}",
                    "-filter_complex", f"[1:a]volume='if(between(t,{a},{b}),0.5,0)':eval=frame[s];[3:a]volume=0.004[h];"
                    "[s][2:a][h]amix=inputs=3:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@pytest.mark.slow
def test_a_render_splits_the_cut_fills_the_photo_with_room_tone_and_ends_the_music_on_time(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    from test_studio_editor_render import _asset, _band, _pcm, _plan

    A = _asset(_recording(tmp_path / "A.mp4", 440, (0.3, 2.9), 5000), "video")
    B = _asset(_recording(tmp_path / "B.mp4", 660, (1.2, 5.0), 7000), "video")
    img = tmp_path / "pic.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:d=1", "-frames:v",
                    "1", str(img)], check=True)
    pic = {"id": "pic", "kind": "image", "filename": "pic.png", "path": str(img), "sha256": "pic",
           "probe": {"width": 640, "height": 360}}
    # music: a 220 Hz bed with a 1000 Hz "last bar" in its final 0.4 s
    music = tmp_path / "bed.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=3.6",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.4", "-filter_complex",
                    "[0:a]atrim=0:3.2[a];[a][1:a]concat=n=2:v=0:a=1,volume=0.3[m]", "-map", "[m]", "-ar", "48000",
                    str(music)], check=True)
    bed = _asset(music, "audio")
    assets = {"A": A, "B": B, "pic": pic, "bed": bed}
    words = {"A": _words((0.3, 2.9)), "B": _words((1.2, 5.0))}
    clips = [{"id": "a", "asset_id": "A", "kind": "video", "in_ms": 0, "out_ms": 3600, "include": True},
             {"id": "b", "asset_id": "B", "kind": "video", "in_ms": 800, "out_ms": 5200, "include": True,
              "gain_db": -6.0},  # turned down: the room tone under the photo follows
             {"id": "p", "asset_id": "pic", "kind": "image", "in_ms": 0, "out_ms": 2000, "include": True}]
    audio = [{"id": "m", "asset_id": "bed", "role": "music", "label": "bed", "start_ms": 0, "in_ms": 0,
              "out_ms": None, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": False, "loop": True, "anchor": None, "back_time": True}]  # "End on the last frame" ticked
    plan = _plan(clips, audio=audio)
    assert engine.validate(plan, assets) == []
    info = engine.render(plan, assets, words, tmp_path / "out.mp4", preview=True)
    joins = info["sound_joins"]
    assert joins["split_edits"] == [{"at_s": 3.6, "j_frames": 8, "l_frames": 0}]
    assert joins["room_tone_s"] == 2.0 and joins["music_back_timed_s"]["m"] > 0
    pcm = _pcm(tmp_path / "out.mp4")
    total = info["duration"]
    # the J cut: B's room (its 7 kHz hum) under A's last 8 frames (3.33-3.6 s) in place of A's (5 kHz), and no
    # speech moved: A's tone ends at 2.9 s, B's starts at 4.0 s
    b_room = _band(pcm, 3.65, 3.95, 7000)
    # (before the lead, A's own pink noise alone measures 0.1-0.2 of B's hum here; B's hum would measure about 1)
    assert _band(pcm, 3.39, 3.58, 7000) > 0.7 * b_room and _band(pcm, 2.9, 3.25, 7000) < 0.4 * b_room
    assert _band(pcm, 3.39, 3.58, 5000) < 0.1 * _band(pcm, 2.95, 3.25, 5000)
    assert _band(pcm, 3.36, 3.58, 440) < 0.02 * _band(pcm, 1.0, 2.5, 440)
    assert _band(pcm, 3.0, 3.58, 660) < 0.02 * _band(pcm, 4.5, 6.5, 660)
    assert _band(pcm, 4.1, 6.5, 660) > 0.9 * _band(pcm, 4.5, 6.5, 660)  # B's speech whole (from 4.0 s)
    # the photo (8.0-10.0 s) is not digital silence: it has the room sound of B, the recording before it
    on_photo = _band(pcm, 8.2, 9.5, 7000)
    assert 0.6 * b_room < on_photo < 1.6 * b_room, (on_photo, b_room)
    # the music's last bar (1000 Hz) plays at the very end, not cut off somewhere in the middle of the bed
    assert _band(pcm, total - 0.35, total - 0.02, 1000) > 5 * _band(pcm, total - 0.35, total - 0.02, 220)
    assert _band(pcm, total - 0.9, total - 0.5, 220) > 5 * _band(pcm, total - 0.9, total - 0.5, 1000)
    # it therefore starts inside the bed, so it fades in rather than starting on a hard edge
    assert _band(pcm, 0.0, 0.25, 220) < 0.4 * _band(pcm, 1.2, 2.2, 220)


@pytest.mark.slow
def test_looping_aac_music_repeats_without_gaps_and_still_ends_on_the_last_frame(tmp_path, monkeypatch):
    """FFmpeg's own looping of an AAC (or MP3) file drifts by the encoder's padding on every repeat, until its
    resampler pads in about 0.1 s of silence every 5 repeats: a gap in the music, and a back-timed ending 0.1 s
    late (its last bar cut off). The engine repeats one decoded pass instead."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    from test_studio_editor_render import _asset, _band, _pcm, _plan

    img = tmp_path / "pic.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:d=1", "-frames:v",
                    "1", str(img)], check=True)
    pic = {"id": "pic", "kind": "image", "filename": "pic.png", "path": str(img), "sha256": "pic",
           "probe": {"width": 640, "height": 360}}
    # a 1 s AAC bed at 44.1 kHz: 220 Hz, then a 1000 Hz "last bar" in its final 0.1 s
    music = tmp_path / "bed.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=0.9:"
                    "sample_rate=44100", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.1:sample_rate=44100",
                    "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1,volume=0.3[m]", "-map", "[m]", "-c:a", "aac",
                    "-b:a", "128k", str(music)], check=True)
    bed = _asset(music, "audio")
    clips = [{"id": "p", "asset_id": "pic", "kind": "image", "in_ms": 0, "out_ms": 11500, "include": True}]
    audio = [{"id": "m", "asset_id": "bed", "role": "music", "label": "bed", "start_ms": 0, "in_ms": 0,
              "out_ms": None, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": False, "loop": True, "anchor": None, "back_time": True}]
    plan = _plan(clips, audio=audio)
    info = engine.render(plan, {"pic": pic, "bed": bed}, {}, tmp_path / "out.mp4", preview=True)
    assert info["sound_joins"]["music_back_timed_s"]["m"] > 0
    pcm = _pcm(tmp_path / "out.mp4")
    total = info["duration"]
    # about 12 repeats: no stretch of silence anywhere after the fade-in (the drift put two 0.1 s gaps in it)
    win = 1440  # 30 ms
    usable = pcm[48000:int((total - 0.05) * 48000)]
    rms = np.sqrt((usable[: len(usable) // win * win].reshape(-1, win) ** 2).mean(axis=1))
    assert rms.min() > 0.3 * np.median(rms), (rms.min(), np.median(rms))
    # and the bed's own last 0.1 s (1000 Hz) is what plays at the very end
    assert _band(pcm, total - 0.09, total - 0.01, 1000) > 5 * _band(pcm, total - 0.09, total - 0.01, 220)
    assert _band(pcm, total - 0.6, total - 0.2, 220) > 5 * _band(pcm, total - 0.6, total - 0.2, 1000)


def _quiet_recording(path: Path, speak: tuple[float, float], seconds: float = 6.0, seed: int = 1) -> Path:
    """A video: a 440 Hz "voice" from speak[0] to speak[1] over pink-noise room sound (a fixed seed)."""
    a, b = speak
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
                    "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.01:duration={seconds}:sample_rate=48000:"
                    f"seed={seed}",
                    "-filter_complex", f"[1:a]volume='if(between(t,{a},{b}),0.5,0)':eval=frame[s];"
                    "[s][2:a]amix=inputs=2:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


@pytest.mark.slow
def test_room_tone_runs_under_a_clips_own_fade_and_stays_out_from_under_a_voiceover(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    from test_studio_editor_render import _asset, _plan

    A = _asset(_quiet_recording(tmp_path / "A.mp4", (0.3, 2.0)), "video")
    B = _asset(_quiet_recording(tmp_path / "B.mp4", (1.5, 3.5), seed=2), "video")
    img = tmp_path / "pic.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:d=1", "-frames:v",
                    "1", str(img)], check=True)
    pic = {"id": "pic", "kind": "image", "filename": "pic.png", "path": str(img), "sha256": "pic",
           "probe": {"width": 640, "height": 360}}
    vo_file = tmp_path / "vo.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                    "-ar", "48000", str(vo_file)], check=True)
    vo = _asset(vo_file, "audio")
    clips = [{"id": "a", "asset_id": "A", "kind": "video", "in_ms": 0, "out_ms": 3000, "include": True,
              "fade_out_ms": 400},
             {"id": "p", "asset_id": "pic", "kind": "image", "in_ms": 0, "out_ms": 2000, "include": True},
             {"id": "b", "asset_id": "B", "kind": "video", "in_ms": 1000, "out_ms": 4000, "include": True,
              "fade_in_ms": 400},
             {"id": "p2", "asset_id": "pic", "kind": "image", "in_ms": 0, "out_ms": 2000, "include": True}]
    audio = [{"id": "v", "asset_id": "vo", "role": "voiceover", "label": "vo", "start_ms": 0, "in_ms": 0,
              "out_ms": 2000, "length_ms": None, "gain_db": 0.0, "mute": False, "fade_in_ms": 0, "fade_out_ms": 0,
              "duck": False, "loop": False, "anchor": {"clip_id": "p2", "offset_ms": 500}}]
    plan = _plan(clips, audio=audio)
    assets = {"A": A, "B": B, "pic": pic, "vo": vo}
    assert engine.validate(plan, assets) == []
    info = engine.render(plan, assets, {"A": _words((0.3, 2.0)), "B": _words((1.5, 3.5))}, tmp_path / "o.mp4",
                         preview=True)
    # the first photo, and the second until its voiceover starts (8.5 s; it runs to the end)
    assert info["sound_joins"]["room_tone_s"] == 2.5
    steep = ",".join(["highpass=f=3000"] * 3)  # the room's hiss only: no voice, no voiceover
    hiss = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(tmp_path / "o.mp4"), "-af", steep,
                                    "-f", "f32le", "-ac", "1", "-ar", "48000", "-"])
    hp = np.frombuffer(hiss, dtype=np.float32)

    def db(t0: float, t1: float) -> float:
        return float(20 * np.log10(np.sqrt(np.mean(hp[int(t0 * 48000):int(t1 * 48000)] ** 2)) + 1e-12))
    room = db(2.15, 2.55)  # A's room after its words, before its fade
    # A fades out into the photo's room tone and the tone fades out into B's fade-in: the room never dips
    windows = [db(t, t + 0.05) for t in np.arange(2.55, 5.45, 0.05)]
    assert min(windows) > room - 4.5, (room, min(windows))
    # the second photo has the room until the voiceover, then steps aside: under the voiceover (8.5-10 s) no second
    # room, only what the voiceover brings (a 300 Hz tone, filtered out)
    assert db(8.05, 8.35) > room - 4.5
    assert db(8.6, 9.8) < room - 20
