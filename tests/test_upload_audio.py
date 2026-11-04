"""Real samples retain source timing and stay below clipping before and after a fake YouTube upload."""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import needs_ffmpeg
from test_autopilot_publish import connect, env  # noqa: F401


@pytest.fixture()
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _ffmpeg(*args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                          capture_output=True, check=True, timeout=45)


def _late_audio(path: Path, channels: int = 1) -> Path:
    tone = "0.75*sin(2*PI*440*t)"
    if channels == 6:
        tone = "(0.03+0.72*lt(mod(t\\,1)\\,0.05))*sin(2*PI*440*t)"
    generated = "aevalsrc=" + "|".join([tone] * channels) + ":s=48000:d=2.8"
    if channels == 6:
        generated += ":c=5.1"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=4",
            "-itsoffset", "1.2", "-f", "lavfi", "-i", generated, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "pcm_s16le", path)
    return path


def _samples(path: Path) -> np.ndarray:
    raw = _ffmpeg("-i", path, "-map", "0:a:0", "-ac", "2", "-ar", "48000", "-f", "f32le", "-")
    return np.frombuffer(raw.stdout, dtype="<f4").reshape(-1, 2)


def _rms(samples) -> float:
    return float(np.sqrt(np.mean(np.square(samples))))


def _frequency(samples, rate: int) -> float:
    samples = samples - samples.mean()
    spectrum = abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.argmax(spectrum) * rate / len(samples))


@needs_ffmpeg
def test_transcription_audio_preserves_a_delayed_track_and_full_video_timeline(profile):
    from clipfoundry.pipeline.ffmpeg_utils import extract_audio, probe

    source = _late_audio(profile / "late.mkv")
    assert probe(source)["audio_start"] == pytest.approx(1.2, abs=.01)
    target = profile / "speech.wav"
    extract_audio(source, target, 4)
    with wave.open(str(target)) as wav:
        assert wav.getframerate() == 16000 and wav.getnchannels() == 1
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32768
    assert len(samples) == 4 * 16000
    assert _rms(samples[1600:17600]) < .0001  # Real initial silence must not disappear before Whisper.
    assert _rms(samples[20800:30400]) > .2
    assert _frequency(samples[20800:30400], 16000) == pytest.approx(440, abs=3)


@needs_ffmpeg
def test_transcription_uses_the_same_first_track_as_probe_and_render(profile):
    from clipfoundry.pipeline.ffmpeg_utils import extract_audio

    source = profile / "two-tracks.mkv"
    _ffmpeg("-f", "lavfi", "-i", "color=size=160x90:rate=10:duration=2", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=2", "-f", "lavfi", "-i",
            "aevalsrc=sin(2*PI*880*t)|sin(2*PI*880*t):s=48000:d=2", "-map", "0:v", "-map", "1:a",
            "-map", "2:a", "-disposition:a:0", "0", "-disposition:a:1", "0", "-c:v", "libx264",
            "-preset", "ultrafast", "-c:a", "pcm_s16le", source)
    target = profile / "first-track.wav"
    extract_audio(source, target, 2)
    with wave.open(str(target)) as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32768
    # Automatic FFmpeg selection prefers the second stereo track; the rendered first track says something else.
    assert _frequency(samples[1600:24000], 16000) == pytest.approx(440, abs=2)


@needs_ffmpeg
def test_transcription_keeps_a_timestamp_gap_in_the_middle_of_a_recording(profile):
    from clipfoundry.pipeline.ffmpeg_utils import extract_audio

    source = profile / "interrupted-audio.mkv"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=4", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=3.4", "-filter:a",
            "asetpts=PTS+gte(T\\,1)*0.6/TB", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "pcm_s16le", source)
    target = profile / "interrupted.wav"
    extract_audio(source, target, 4)
    with wave.open(str(target)) as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2") / 32768
    assert len(samples) == 64000
    assert _rms(samples[3200:12800]) > .05
    assert _rms(samples[18400:24000]) < .0001
    assert _rms(samples[27200:35200]) > .05  # Returning speech stays after the interruption.


@needs_ffmpeg
@pytest.mark.parametrize(("normalize", "gain", "channels"), [(False, 12, 1), (True, 12, 1),
                                                             (True, 0, 6), (False, 0, 6)])
def test_loudness_downmix_and_gain_do_not_overload_audio(profile, normalize, gain, channels):
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    source = profile / "peaks.wav"
    tone = "(0.03+0.72*lt(mod(t\\,1)\\,0.05))*sin(2*PI*440*t)"
    generated = "aevalsrc=" + "|".join([tone] * channels) + ":s=48000:d=4"
    if channels == 6:
        generated += ":c=5.1"
    _ffmpeg("-f", "lavfi", "-i", generated, source)
    opts = {"normalize_audio": normalize, "gain_db": gain}
    measured = render._measure_audio(["-i", str(source)], [(0, 4)], 0, opts, 4, JobContext())
    graph = render._audio_filter([(0, 4)], 0, opts,
                                 normalization_gain_db=measured["normalization_gain_db"])
    out = _ffmpeg("-f", "lavfi", "-i", "color=size=16x16:duration=4", "-i", source,
                  "-filter_complex", graph, "-map", "[a]", "-ac", "2", "-ar", "48000", "-f", "f32le", "-")
    samples = np.frombuffer(out.stdout, dtype="<f4").reshape(-1, 2)
    assert abs(len(samples) / 48000 - 4) < .025
    assert .2 < np.max(abs(samples)) < .85  # −1.5 dBFS ceiling, not digital full-scale flat tops.
    assert _rms(samples[48000:96000]) > .02


@pytest.mark.slow
@needs_ffmpeg
@pytest.mark.parametrize(("channels", "normalize", "gain"), [(1, False, 12), (6, True, 0)])
def test_cut_and_faster_render_preserves_delayed_speech_pitch_and_uploaded_samples(env, channels, normalize, gain):
    from clipfoundry import db
    from clipfoundry.pipeline import artifact, blueprint, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.publish import youtube

    google, tiktok, tmp = env
    connect(google, tiktok)
    source = _late_audio(tmp / "late-source.mkv", channels)
    meta = probe(source)
    project = {"id": "p-audio", "name": "Measured synthetic tone", "source_path": str(source),
               "dir": str(tmp / "project"), "info": meta, "options": {}, **meta}
    clip = {"id": "c-audio", "project_id": project["id"], "start": .2, "end": 3.8,
            "hook": "", "edit": {}}
    words = [{"w": "Synthetic", "start": 1.25, "end": 1.55},
             {"w": "tone.", "start": 2.3, "end": 2.6}]
    plan = blueprint.Blueprint(clip["id"], project["id"], "source", "synthetic-input",
                               [blueprint.Interval(.2, 1.6), blueprint.Interval(2.2, 3.8)], speed=1.25,
                               framing=blueprint.Framing(mode="center"),
                               audio=blueprint.Audio(normalize=normalize, gain_db=gain))
    assert not blueprint.errors(blueprint.validate(plan, 4, words))
    settings = {**db.get_settings(), "encoder": "x264", "x264_preset": "ultrafast"}
    result = render.render_clip(project, clip, words, settings, JobContext(), blueprint=plan)
    output = Path(result["output_path"])
    samples = _samples(output)
    # Source sound starts at 1.2; this .2-start, 1.25× clip must keep it silent for .8 seconds.
    assert _rms(samples[4800:30000]) < .0005
    assert _rms(samples[48000:96000]) > .01
    assert _frequency(samples[60000:96000, 0], 48000) == pytest.approx(440, abs=3)  # Pitch stays natural.
    steady = samples[62400:81600, 0]  # Away from the deliberate source transient and the edit join.
    spectrum = abs(np.fft.rfft(steady * np.hanning(len(steady)))) ** 2
    frequencies = np.fft.rfftfreq(len(steady), 1 / 48000)
    assert spectrum[abs(frequencies - 440) < 8].sum() / spectrum.sum() > .98
    assert np.max(abs(samples)) < .95
    assert len(samples) / 48000 == pytest.approx(2.4, abs=.05)
    measured = probe(output)
    assert abs(measured["video_duration"] - measured["audio_duration"]) < .05
    heard = json.loads(Path(result["render_info"]["artifact"]["transcript"]).read_text())["words"]
    assert heard[0]["start"] == pytest.approx(.84, abs=.001)
    assert result["render_info"]["segments"] == 2

    # The official resumable uploader sends this exact MP4; the fake platform must receive unchanged audio.
    body = {"snippet": {"title": "Synthetic audio regression"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
    uploaded = youtube.upload(str(output), body, youtube.Token(db.get_settings()))
    remote = tmp / "fake-youtube-received.mp4"
    remote.write_bytes(google.videos[uploaded["id"]]["bytes"])
    assert artifact.sha256_file(remote) == result["render_info"]["artifact"]["sha256"]
    assert np.array_equal(_samples(remote), samples)
    assert not db.select("publications") and not db.select("publish_consents")
