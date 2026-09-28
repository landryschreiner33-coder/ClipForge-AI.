"""Smarter editing (speech-gated speaker framing, filler removal, speed, emphasis zoom and captions) and versions."""
from __future__ import annotations

import json
import shutil
import sys
import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry import config
from clipfoundry.pipeline import captions, reframe, render, transcribe, versions
from test_core import SCRIPT, _srt

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _w(t: float, text: str, d: float = 0.3) -> dict:
    return {"start": t, "end": t + d, "w": text}


def test_filler_words_go_with_the_pause_around_them():
    words = [_w(0.2, "So"), _w(0.6, "the"), _w(1.0, "um,", 0.35), _w(1.5, "answer"), _w(1.9, "is"), _w(2.3, "yes.")]
    keep = render.keep_segments(words, 0.0, 3.0, "aggressive", 25.0)
    tl = render.Timeline(keep)
    assert tl.contains(1.1)  # without filler removal the "um" is spoken audio and stays
    dropped = render.Timeline(render.keep_segments(words, 0.0, 3.0, "aggressive", 25.0, drop_fillers=True))
    assert not dropped.contains(1.15) and dropped.duration < tl.duration
    assert dropped.contains(0.7) and dropped.contains(1.6)  # real words are kept
    light = render.Timeline(render.keep_segments(words, 0.0, 3.0, "light", 25.0, drop_fillers=True))
    assert light.contains(1.15)  # a short "um" in a light cleanup stays: cutting it would sound choppy


def test_speed_shortens_the_timeline_and_keeps_order():
    tl = render.Timeline([(0.0, 10.0)], speed=1.08)
    assert tl.duration == pytest.approx(10 / 1.08)
    assert tl.to_out(5.4) == pytest.approx(5.0) and tl.to_out(0.0) == 0.0
    assert render.Timeline([(0.0, 10.0)], speed=3.0).speed == render.SPEED_RANGE[1]  # clamped


def test_emphasis_zoom_pushes_in_on_emphasized_sentences_only():
    words = []
    t = 0.0
    for sent in ["I lost everything in one night.", "Then I went home and slept.", "The lesson is simple.",
                 "We walked to the shop and back."]:
        for tok in sent.split():
            words.append(_w(t, tok, 0.35))
            t += 0.45
        t += 0.4
    emph = render.emphasis_words(words, {"lesson"})
    marked = {words[i]["w"] for i in emph}
    assert "lesson" in marked and len(emph) >= 2
    n = int(t * 25)
    z = render.zoom_curve(words, n, 25.0, 0.07, emph)
    at = lambda sec: z[min(n - 1, int(sec * 25))]  # noqa: E731
    first = next(w for w in words if w["w"] == "Then")["start"]
    lesson = next(w for w in words if w["w"] == "lesson")["start"]
    assert at(lesson + 0.8) > 1.05 and at(first + 1.0) < 1.01
    assert z.max() <= 1.0701 and np.abs(np.diff(z)).max() < 0.02  # subtle and eased
    spaced = sorted(words[i]["start"] for i in emph)
    assert all(b - a >= 2.5 for a, b in zip(spaced, spaced[1:]))  # rare enough to mean something


def test_caption_emphasis_colors_key_words():
    words = [dict(_w(i * 0.4, w), **({"em": True} if w == "simple" else {})) for i, w in enumerate(
        "the lesson is simple talk first".split())]
    off = captions.build_ass(words, {"caption_style": "bold"}, 3.0)
    on = captions.build_ass(words, {"caption_style": "bold", "caption_emphasis": True}, 3.0)
    emph = captions.hex_to_ass(captions.STYLE_PRESETS["bold"]["emphasis"])
    assert emph not in off and f"{{\\c{emph}\\fscx108\\fscy108}}SIMPLE{{\\r}}" in on
    assert emph not in captions.build_ass(words, {"caption_style": "minimal", "caption_emphasis": True}, 3.0)


def _two_face_analysis(speech: np.ndarray) -> dict:
    n = len(speech)
    a, b = reframe.Track(0), reframe.Track(1)
    for i in range(n):
        a.boxes[i] = (0.10, 0.3, 0.1, 0.18)
        b.boxes[i] = (0.80, 0.3, 0.1, 0.18)
        a.activity[i] = 0.6 if i < n // 2 else 0.05   # A talks in the first half
        b.activity[i] = 0.05 if i < n // 2 else 0.6   # B's mouth moves in the second half
    return {"n": n, "times": [i / reframe.ANALYSIS_FPS for i in range(n)], "tracks": [a, b], "speech": speech}


def test_speaker_switch_needs_speech():
    n = 160
    talking = np.ones(n, dtype=bool)
    xs, _, _ = reframe._face_targets(_two_face_analysis(talking), 0.32, 1.0, speaker=True)
    assert xs[20] < 0.3 and xs[-5] > 0.7  # switches to B when B speaks

    silent_second_half = talking.copy()
    silent_second_half[n // 2:] = False  # B only moves its mouth (nodding, chewing) while nobody speaks
    xs, _, switches = reframe._face_targets(_two_face_analysis(silent_second_half), 0.32, 1.0, speaker=True)
    assert xs[-5] < 0.3 and not switches  # the camera holds on A


def test_speech_mask_from_word_timings():
    mask = reframe.speech_mask([0.0, 1.0, 2.0, 3.0, 4.0], [(0.9, 1.4), (3.2, 3.5)])
    assert mask.tolist() == [False, True, False, True, False]
    assert reframe.speech_mask([0.0, 1.0], None).all()


@pytest.fixture()
def script_words():
    return transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(SCRIPT))})


def test_version_edits(script_words):
    words = script_words
    start = next(w["start"] for w in words if w["w"] == "Anyway,")  # "Anyway, uh ..." then a strong story line
    end = next(w["end"] for w in words if w["w"] == "notes.")
    clip = {"start": start - 0.2, "end": end, "hook": "Anyway, uh, that was a lot of talking.",
            "hooks_alt": ["Next week we will talk about the schedule"], "edit": {"caption_style": "bold"}}
    project = {"options": {}}
    settings = dict(config.DEFAULT_SETTINGS)
    edit, desc = versions.build("faster", clip, project, settings, words)
    assert edit == {"silence": "aggressive", "remove_fillers": True, "speed": versions.FASTER_SPEED} and "8%" in desc
    edit, desc = versions.build("alt_captions", clip, project, settings, words)
    assert edit == {"caption_style": "high_energy", "caption_emphasis": True} and "High Energy" in desc
    edit, desc = versions.build("alt_hook", clip, project, settings, words)
    assert edit["hook"] == "Next week we will talk about the schedule" and edit["hook_overlay"]
    with pytest.raises(ValueError):
        versions.build("nope", clip, project, settings, words)


def test_alternative_opening_skips_a_weak_first_line():
    from test_virality import PODCAST

    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(PODCAST))})
    start = next(w["start"] for w in words if w["w"] == "Okay")   # "Okay so, the first thing is the new studio."
    end = next(w["end"] for w in words if w["w"] == "everything.")
    new = versions.alt_opening({"start": start - 0.1, "end": end, "edit": {}}, words)
    first = next(w for w in words if w["start"] >= new)
    assert first["w"] == "Here's"  # "Here's the thing nobody tells you about quitting your job."
    assert versions.alt_opening({"start": first["start"] - 0.1, "end": end, "edit": {}}, words) is None  # already strong


@needs_ffmpeg
@pytest.mark.slow
def test_faster_version_renders_shorter_and_in_sync(tmp_path, monkeypatch):
    """Real render: speed + aggressive cleanup + filler removal keep picture, sound and captions aligned."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    here = Path(__file__).parent
    if not (shutil.which("espeak-ng") or shutil.which("espeak")):
        pytest.skip("espeak-ng is needed to build the speech test video")
    media = tmp_path / "media"
    media.mkdir()
    subprocess.run([sys.executable, str(here / "make_test_video.py"), str(media), str(here / "fixtures" / "face.jpg")],
                   check=True, capture_output=True)
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    src = media / "talk.mp4"
    meta = probe(src)
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles((media / "speech.srt").read_text())})
    project = {"source_path": str(src), "dir": str(tmp_path / "proj"), "info": meta, "options": {}, **meta}
    clip = {"id": "c1", "start": 0.3, "end": 16.0, "hook": "Here's the biggest mistake", "edit": {}}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast"}
    base = render.render_clip(project, clip, words, settings, JobContext())
    fast_clip = {**clip, "edit": {"silence": "aggressive", "remove_fillers": True, "speed": 1.08,
                                  "caption_emphasis": True}}
    fast = render.render_clip(project, fast_clip, words, settings, JobContext(), out_dir=tmp_path / "v")
    assert Path(fast["output_path"]).parent == tmp_path / "v" and Path(base["output_path"]).exists()
    assert fast["duration"] < base["duration"] and fast["render_info"]["speed"] == 1.08

    def streams(path: str) -> dict:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", path], capture_output=True,
                             text=True, check=True)
        return {s["codec_type"]: float(s["duration"]) for s in json.loads(out.stdout)["streams"]}

    for r in (base, fast):
        d = streams(r["output_path"])
        assert abs(d["video"] - d["audio"]) < 0.15, d  # picture and sound stay in sync
        assert abs(d["video"] - r["duration"]) < 0.2, (d, r["duration"])
    assert (tmp_path / "v" / "captions.srt").exists() and (tmp_path / "proj" / "clips" / "c1" / "framing.json").exists()
