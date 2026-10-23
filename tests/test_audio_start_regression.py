"""Measured startup/loudness regressions through encoded AAC and fake platform transfers."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from synthetic_media import needs_ffmpeg
from test_autopilot_publish import connect, env  # noqa: F401
from test_upload_audio import _ffmpeg, _rms, _samples, profile  # noqa: F401


def _window(samples, start, end):
    return samples[int(start * 48000):int(end * 48000)]


def _purity(samples, frequency=440):
    signal = samples[:, 0]
    spectrum = abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
    frequencies = np.fft.rfftfreq(len(signal), 1 / 48000)
    return spectrum[abs(frequencies - frequency) < 12].sum() / spectrum.sum()


def _encode(source, target, opts, segs=None):
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    segs = segs or [(0, 15)]
    duration = sum(b - a for a, b in segs) / opts.get("speed", 1)
    measured = render._measure_audio(["-i", str(source)], segs, 0, opts, duration, JobContext())
    graph = render._audio_filter(segs, 0, opts, input_label="0:a:0",
                                 normalization_gain_db=measured["normalization_gain_db"])
    _ffmpeg("-i", source, "-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-ac", "2", target)
    return _samples(target), measured


@needs_ffmpeg
def test_a_loud_moment_does_not_turn_down_identical_speech_after_it(profile):
    source = profile / "quiet-loud-quiet.wav"
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc=(0.05+0.9*between(t\\,3\\,4))*sin(2*PI*440*t):s=48000:d=15", source)
    samples, measured = _encode(source, profile / "fixed.m4a", {"normalize_audio": True})
    first = _rms(_window(samples, .1, .6))
    for start in (1, 4.2, 8, 13):
        # Single-pass loudnorm used to change identical sound by over 24 dB around the loud moment.
        delta_db = 20 * np.log10(_rms(_window(samples, start, start + .5)) / first)
        assert abs(delta_db) < .3
    assert _purity(_window(samples, .05, .55)) > .995
    assert np.isfinite(samples).all() and np.max(abs(samples)) < .95
    assert measured["normalization"] == "measured_fixed_gain"


@needs_ffmpeg
def test_quiet_opening_is_not_amplified_into_a_loud_burst(profile):
    source = profile / "quiet-opening.wav"
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc=(0.001+0.149*gte(t\\,3))*sin(2*PI*440*t):s=48000:d=15", source)
    samples, _ = _encode(source, profile / "fixed.m4a", {"normalize_audio": True})
    ratio = _rms(_window(samples, .1, .6)) / _rms(_window(samples, 5, 5.5))
    assert ratio == pytest.approx(.001 / .15, rel=.08)
    assert _purity(_window(samples, .1, .6)) > .995


@needs_ffmpeg
def test_measurement_follows_kept_segments_speed_and_preserves_initial_silence(profile):
    source = profile / "edited.wav"
    _ffmpeg("-f", "lavfi", "-i",
            "aevalsrc=gte(t\\,1)*(0.05+0.9*between(t\\,3\\,4))*sin(2*PI*440*t):s=48000:d=15", source)
    whole, whole_measurement = _encode(source, profile / "whole.m4a", {"normalize_audio": True})
    edited, measurement = _encode(source, profile / "edit.m4a", {"normalize_audio": True, "speed": 1.25},
                                   [(0, 2.5), (4.5, 8)])
    assert measurement["normalization_gain_db"] > whole_measurement["normalization_gain_db"] + 10
    assert _rms(_window(edited, .1, .6)) < .0001
    assert _rms(_window(edited, 1, 1.5)) > .1
    assert len(edited) / 48000 == pytest.approx(4.8, abs=.05)
    assert len(whole) / 48000 == pytest.approx(15, abs=.05)


@needs_ffmpeg
@pytest.mark.parametrize("signal", ["0", "0.0005*sin(2*PI*440*t)"])
def test_silent_or_very_quiet_audio_has_no_unbounded_gain(profile, signal):
    source = profile / "quiet.wav"
    _ffmpeg("-f", "lavfi", "-i", f"aevalsrc={signal}:s=48000:d=15", source)
    samples, measurement = _encode(source, profile / "quiet.m4a", {"normalize_audio": True})
    assert 0 <= measurement["normalization_gain_db"] <= 24
    assert np.isfinite(samples).all() and np.max(abs(samples)) < .01
    json.dumps(measurement, allow_nan=False)


@pytest.mark.parametrize("stderr", [b"", b'{"input_i":"NaN","input_tp":"-1"}',
                                    b'{"input_i":"-20","input_tp":"inf"}',
                                    b'{"input_i":"-20","input_tp":"-inf"}',
                                    b'{"input_i":"-20"}'])
def test_missing_or_invalid_measurements_stop_the_render(profile, monkeypatch, stderr):
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import FFmpegError

    monkeypatch.setattr(render, "run_process", lambda *a, **k: SimpleNamespace(returncode=0, stderr=stderr))
    with pytest.raises(FFmpegError, match="measurement was incomplete"):
        render._measure_audio([], [(0, 5)], 0, {}, 5, JobContext())


def test_cancel_and_normalization_off_do_not_start_a_measurement(profile, monkeypatch):
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import Cancelled, JobContext

    def forbidden(*a, **k):
        pytest.fail("No media subprocess should start")

    monkeypatch.setattr(render, "run_process", forbidden)
    disabled = render._measure_audio([], [(0, 5)], 0, {"normalize_audio": False}, 5, JobContext())
    assert disabled["normalization"] == "off"
    with pytest.raises(Cancelled):
        render._measure_audio([], [(0, 5)], 0, {}, 5, JobContext(is_cancelled=lambda: True))


@pytest.mark.slow
@needs_ffmpeg
def test_rendered_startup_audio_reaches_both_fake_platforms_unchanged(env):
    from clipfoundry import db
    from clipfoundry.pipeline import artifact, blueprint, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.publish import tiktok, youtube

    google, tik, tmp = env
    connect(google, tik)
    source = tmp / "startup.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=12", "-f", "lavfi", "-i",
            "aevalsrc=(0.05+0.9*between(t\\,3\\,4))*sin(2*PI*440*t):s=44100:d=12",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k", source)
    meta = probe(source)
    project = {"id": "p-start", "name": "Synthetic audio", "source_path": str(source),
               "dir": str(tmp / "project"), "info": meta, "options": {}, **meta}
    clip = {"id": "c-start", "project_id": project["id"], "start": .2, "end": 11.8,
            "hook": "", "edit": {}}
    plan = blueprint.Blueprint(clip["id"], project["id"], "source", "test",
                               [blueprint.Interval(.2, 11.8)], framing=blueprint.Framing(mode="center"),
                               audio=blueprint.Audio(normalize=True))
    result = render.render_clip(project, clip, [],
                                {**db.get_settings(), "encoder": "x264", "x264_preset": "ultrafast"},
                                JobContext(), blueprint=plan)
    output = Path(result["output_path"])
    samples = _samples(output)
    first = _rms(_window(samples, .1, .6))
    assert _rms(_window(samples, 4.2, 4.7)) / first == pytest.approx(1, abs=.04)
    assert _purity(_window(samples, .05, .55)) > .995
    assert abs(probe(output)["audio_duration"] - probe(output)["video_duration"]) < .05
    assert result["render_info"]["audio_processing"]["normalization"] == "measured_fixed_gain"
    body = {"snippet": {"title": "Synthetic audio test"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
    uploaded = youtube.upload(str(output), body, youtube.Token(db.get_settings()))
    assert google.videos[uploaded["id"]]["bytes"] == output.read_bytes()
    init = tiktok.init_upload(tiktok.Token(db.get_settings()), "inbox", output.stat().st_size)
    tiktok.upload_chunks(init["upload_url"], str(output), lambda value: None, lambda: False)
    received = tmp / "received.mp4"
    received.write_bytes(bytes(tik.uploads[init["publish_id"]]["data"]))
    assert artifact.sha256_file(received) == result["render_info"]["artifact"]["sha256"]
    assert np.array_equal(_samples(received), samples)
