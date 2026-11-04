"""Regression for audio that decodes locally but carries a broken MP4 timing table into an upload."""
import json
from types import SimpleNamespace

import pytest

from clipfoundry.pipeline import audio_timing, quality
from clipfoundry.pipeline.common import Cancelled
from clipfoundry.pipeline.ffmpeg_utils import FFmpegError, probe
from synthetic_media import needs_ffmpeg
from test_upload_audio import _ffmpeg, _samples


@needs_ffmpeg
def test_raw_clock_exposes_a_gap_hidden_by_normal_aac_playback(tmp_path):
    bad = tmp_path / "bad-clock.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=16x16:rate=10:duration=5", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=5", "-af", "asetpts=if(lt(T\\,3)\\,PTS/4\\,PTS)",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", bad)
    # Like the owner's MP4, decoding and the total duration alone cannot expose the damaged packet clock.
    assert len(_samples(bad)) / 48000 == pytest.approx(5, abs=.03)
    assert probe(bad)["duration"] == pytest.approx(5, abs=.03)
    result = audio_timing.inspect(bad)
    assert result["valid"] is False and result["invalid_packets"] > 100
    assert result["largest_clock_error_s"] > 2
    assert quality._audio_packet_timing(bad)["status"] == quality.FAIL
    with pytest.raises(FFmpegError, match="glitches or silence"):
        audio_timing.require_valid(bad)
    # A fresh sample clock produces an interoperable table without dropping any decoded speech.
    good = tmp_path / "good-clock.mp4"
    _ffmpeg("-i", bad, "-af", "asettb=1/48000,asetpts=N/SR/TB", "-c:a", "aac", good)
    assert audio_timing.require_valid(good)["invalid_packets"] == 0
    assert len(_samples(good)) == len(_samples(bad))


@needs_ffmpeg
@pytest.mark.parametrize("rate", [44100, 48000])
def test_normal_priming_and_short_final_packet_are_valid(tmp_path, rate):
    path = tmp_path / "good.mp4"
    _ffmpeg("-f", "lavfi", "-i", f"sine=sample_rate={rate}:duration=1.27", "-c:a", "aac", path)
    assert audio_timing.require_valid(path)["sample_rate"] == rate
    assert quality._audio_packet_timing(path)["status"] == quality.PASS


@pytest.mark.parametrize("payload", [b"broken json", b'{}',
    json.dumps({"streams": [{"codec_name": "aac", "profile": "LC", "sample_rate": "48000",
                             "time_base": "1/48000"}], "packets": []}).encode(),
    json.dumps({"streams": [{"codec_name": "aac", "profile": "LC", "sample_rate": "0",
                             "time_base": "1/48000"}], "packets": [{"pts": 0}]}).encode()])
def test_unreadable_clock_does_not_pass(monkeypatch, payload):
    monkeypatch.setattr(audio_timing, "run_process",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=payload))
    with pytest.raises(FFmpegError, match="could not be verified"):
        audio_timing.require_valid("unused.mp4")
    assert quality._audio_packet_timing("unused.mp4")["status"] == quality.FAIL


def test_cancellation_is_not_reported_as_bad_media(monkeypatch):
    def cancel(*args, **kwargs):
        raise Cancelled()
    monkeypatch.setattr(audio_timing, "run_process", cancel)
    with pytest.raises(Cancelled):
        quality._audio_packet_timing("unused.mp4")


def test_clock_failure_goes_back_to_rendering():
    from clipfoundry.autopilot import gate
    report = {"checks": [{"name": "audio_packet_timing", "status": quality.FAIL}]}
    assert gate.rework_target(report) == ("render", "splice")
