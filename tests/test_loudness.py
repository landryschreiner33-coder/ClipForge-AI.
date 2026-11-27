"""The sound check after every render (pipeline/loudness.py): FFmpeg's ebur128 summary is read the way players and
platforms measure loudness, the constant gain says what held it short of -14 LUFS, the finished file is judged in
plain words, and a render whose file missed its level or whose true peak went over -1 dBTP gets its sound made once
more with the picture copied. Synthetic tones and noise only; nothing here is a real platform's own measurement."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from clipfoundry.pipeline import loudness

from synthetic_media import make_video, needs_ffmpeg


def _summary(i: str, lra: str = "4.0", peak: str = "-3.0") -> str:
    return (f"[Parsed_ebur128_0 @ 0x1] Summary:\n\n  Integrated loudness:\n    I:         {i} LUFS\n"
            f"    Threshold: -30.0 LUFS\n\n  Loudness range:\n    LRA:         {lra} LU\n"
            f"    Threshold: -40.0 LUFS\n\n  True peak:\n    Peak:       {peak} dBFS\n")


# ------------------------------------------------------------------ reading the measurement
def test_parse_reads_the_last_summary_and_marks_silence():
    two = _summary("-30.0", peak="-9.0") + "more log\n" + _summary("-14.2", "6.5", "-1.8")
    assert loudness.parse(two) == {"lufs": -14.2, "lra": 6.5, "tp": -1.8}
    assert loudness.parse(_summary("-14.2").encode()) == {"lufs": -14.2, "lra": 4.0, "tp": -3.0}
    silent = loudness.parse(_summary("-70.0", "0.0", "-inf"))
    assert silent == {"lufs": None, "lra": 0.0, "tp": None}  # gated out: no loudness, never a number to boost


@pytest.mark.parametrize("text", ["", "no summary here", _summary("nan"), _summary("-20.0", peak="inf"),
                                  _summary("-20.0").split("  True peak")[0]])
def test_parse_rejects_a_missing_or_broken_summary(text):
    with pytest.raises(ValueError):
        loudness.parse(text)


# ------------------------------------------------------------------ the constant gain
def test_gain_reaches_the_target_unless_the_peaks_or_the_boost_cap_hold_it():
    assert loudness.gain_for(-24.0, -12.0) == (10.0, "")
    gain, held = loudness.gain_for(-26.0, -5.0)  # wants +12, the peaks leave room for +3.5
    assert (gain, held) == (pytest.approx(3.5), "peaks")
    gain, held = loudness.gain_for(-60.0, -50.0)  # wants +46: a very quiet recording rises by 24 dB at most
    assert (gain, held) == (loudness.MAX_BOOST_DB, "cap")
    assert loudness.gain_for(-6.0, -0.5) == (-8.0, "")  # loud sound comes down
    assert loudness.gain_for(None, None) == (0.0, "")  # silence: its noise is never raised blindly


# ------------------------------------------------------------------ judging the finished file
def test_a_file_on_target_passes_with_its_numbers():
    verdict = loudness.check({"lufs": -14.3, "lra": 5.0, "tp": -2.1}, -14.0, normalized=True)
    assert verdict == {"status": "pass", "note": "As loud as most videos (-14.3 LUFS, peaks -2.1 dBTP).", "fix_db": 0.0,
                       "lower_ceiling": False, "ceiling_dbfs": loudness.LIMIT_DBFS}


@pytest.mark.parametrize(("kwargs", "why"), [
    ({"normalized": True, "held": "peaks"}, "its loudest peaks held it back"),
    ({"normalized": True, "held": "cap"}, "a very quiet recording, raised by the most allowed (24 dB)"),
    ({"normalized": False}, "normalization is off"),
    ({"normalized": True, "owner_gain_db": -6.0}, "your volume setting"),
])
def test_a_quiet_file_says_why_it_is_quiet(kwargs, why):
    verdict = loudness.check({"lufs": -21.0, "lra": 5.0, "tp": -4.0}, None if not kwargs["normalized"] else -21.0,
                             **kwargs)
    assert verdict["status"] == "warn" and verdict["fix_db"] == 0.0
    assert verdict["note"] == f"Plays 7.0 dB quieter than most videos (-21.0 LUFS): {why}."


def test_a_loud_file_or_a_hot_peak_warns_and_a_hot_peak_asks_for_a_lower_ceiling():
    loud = loudness.check({"lufs": -9.5, "lra": 3.0, "tp": -2.0}, -9.5, normalized=True, owner_gain_db=4.5)
    assert loud["status"] == "warn" and not loud["lower_ceiling"]
    assert loud["note"] == "Louder than most videos (-9.5 LUFS): platforms will turn it down (your volume setting)."
    hot = loudness.check({"lufs": -14.0, "lra": 3.0, "tp": -0.4}, -14.0, normalized=True)
    assert hot["status"] == "warn" and hot["lower_ceiling"] and hot["ceiling_dbfs"] == -3.4
    assert "Peaks reach -0.4 dBTP" in hot["note"]
    # the further the encoder went over, the lower the second try's ceiling, within -3 to -6 dBFS
    assert [loudness.lower_ceiling(tp) for tp in (-0.9, -0.4, 0.5, 3.0)] == [-3.0, -3.4, -4.75, -6.0]


def test_a_missed_level_gets_one_bounded_fix_that_never_drives_the_limiter():
    def fix(lufs, tp, expected=-14.0):
        return loudness.check({"lufs": lufs, "lra": 4.0, "tp": tp}, expected, normalized=True)["fix_db"]

    assert fix(-14.4, -6.0) == 0.0  # within half a dB: left alone
    assert fix(-16.0, -6.0) == pytest.approx(2.0)  # 2 dB short with room under the ceiling
    assert fix(-16.0, -3.0) == pytest.approx(1.0)  # only the room the limiter's ceiling (-2 dBFS) leaves
    assert fix(-16.0, -2.2) == 0.0  # no room at all: never pushed into the limiter
    assert fix(-11.0, -2.0) == pytest.approx(-3.0)  # too loud comes down
    assert fix(-30.0, -40.0) == loudness.MAX_FIX_DB  # never more than 6 dB in one go
    assert loudness.check({"lufs": -30.0, "lra": 4.0, "tp": -40.0}, None, normalized=False)["fix_db"] == 0.0
    assert loudness.check({"lufs": None, "lra": 0.0, "tp": None}, -14.0, normalized=True)["status"] == "skipped"


# ------------------------------------------------------------------ the limiter, through a real encoder
def _ff(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                          capture_output=True, check=True, timeout=120)


@needs_ffmpeg
@pytest.mark.parametrize("bitrate", ["128k", "256k"])
def test_the_limiter_keeps_true_peaks_under_minus_one_dbtp_after_aac(tmp_path, monkeypatch, bitrate):
    """A hot source (speech-like noise pushed into a limiter, plus a quarter-rate tone whose samples miss its true
    peak by 3 dB) turned up 12 dB by the owner: the old 48 kHz limiter at -1.5 dBFS let it reach about +2 dBTP
    after AAC at 128k; the 4x limiter at -2 dBFS keeps it under -1 dBTP."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    src = tmp_path / "hot.wav"
    speech = ("anoisesrc=c=pink:seed=42:a=0.25:d=6,"
              "volume='0.15+0.85*gt(sin(2*PI*3.3*t)*sin(2*PI*0.7*t+1),0)':eval=frame,volume=12,"
              "alimiter=limit=0.99:level=disabled")
    _ff("-filter_complex", f"{speech}[s];aevalsrc='0.5*sin(2*PI*12000*t+PI/4)':s=48000:d=6[t];"
        "[s][t]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo:sample_rates=48000", "-t", "6", src)
    opts = {"normalize_audio": True, "gain_db": 12}
    measured = render._measure_audio(["-i", str(src)], [(0, 6)], 0, opts, 6, JobContext())

    def encode(ceiling: float) -> dict:
        graph = render._audio_filter([(0, 6)], 0, opts, input_label="0:a:0",
                                     normalization_gain_db=measured["normalization_gain_db"], ceiling_dbfs=ceiling)
        out = tmp_path / "hot.m4a"
        _ff("-i", src, "-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", bitrate, "-ar", "48000",
            "-ac", "2", out)
        return loudness.measure(out)

    got = encode(loudness.LIMIT_DBFS)
    verdict = loudness.check(got, None, normalized=True, owner_gain_db=12)
    if bitrate == "256k":  # the renders' own bitrate: the limiter alone keeps it under
        assert got["tp"] <= loudness.MAX_TP, got
    if verdict["lower_ceiling"]:  # 128k (the studio's previews) can overshoot: the second try brings it under
        got = encode(verdict["ceiling_dbfs"])
    assert got["tp"] <= loudness.MAX_TP, got
    assert got["lufs"] > -14.0  # the owner's +12 dB is kept (and the check calls it louder than most videos)


# ------------------------------------------------------------------ the clip renderer
FAST = {"encoder": "x264", "x264_preset": "ultrafast"}


def _render_clip(tmp_path: Path, name: str):
    from clipfoundry import config
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    src = make_video(tmp_path / f"{name}.mp4", seconds=4.0)
    meta = probe(src)
    project = {"id": name, "name": name, "source_path": str(src), "dir": str(tmp_path / name), "info": meta,
               "options": {}, **meta}
    clip = {"id": f"c-{name}", "start": 0.0, "end": 4.0, "hook": "", "edit": {"tracking": "center"}}
    return render.render_clip(project, clip, [], {**config.DEFAULT_SETTINGS, **FAST}, JobContext())


def _video_md5(path: Path) -> str:
    return _ff("-i", path, "-map", "0:v", "-c", "copy", "-f", "md5", "-").stdout.decode().strip()


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@needs_ffmpeg
def test_a_clip_render_reports_how_its_finished_file_sounds(data):
    out = _render_clip(data, "plain")
    sound = out["render_info"]["qc"]["sound"]
    assert out["render_info"]["qc"]["version"] == 1
    assert sound["status"] == "pass" and sound["fixed_db"] == 0.0 and "ceiling_dbfs" not in sound
    assert sound["lufs"] == pytest.approx(-14.0, abs=loudness.NEAR_LU) and sound["tp"] <= loudness.MAX_TP
    assert sound["expected_lufs"] == pytest.approx(-14.0, abs=0.1)
    assert sound["note"].startswith("As loud as most videos (") and sound["note"].endswith(" dBTP).")
    assert loudness.measure(out["output_path"])["lufs"] == pytest.approx(sound["lufs"], abs=0.05)
    assert out["render_info"]["audio_processing"]["version"] == 2


@needs_ffmpeg
def test_a_hot_peak_gets_the_sound_made_again_under_a_lower_ceiling_with_the_same_picture(data, monkeypatch):
    real, seen = loudness.measure, []

    def first_one_hot(path, cancelled=None, timeout=600.0):
        got = real(path, cancelled, timeout)
        if not seen:  # the encoder's first file: keep a copy and say its peak went over -1 dBTP
            shutil.copy(path, data / "before.mp4")
            got = {**got, "tp": -0.4}
        seen.append(got)
        return got

    monkeypatch.setattr(loudness, "measure", first_one_hot)
    out = _render_clip(data, "hot")
    sound = out["render_info"]["qc"]["sound"]
    assert len(seen) == 2 and sound["ceiling_dbfs"] == loudness.lower_ceiling(-0.4) <= loudness.LOW_LIMIT_DBFS
    assert sound["status"] == "pass" and sound["tp"] <= loudness.MAX_TP
    final = Path(out["output_path"])
    assert _video_md5(final) == _video_md5(data / "before.mp4")  # the picture was copied, not encoded again
    art = out["render_info"]["artifact"]
    assert art["sha256"] == hashlib.sha256(final.read_bytes()).hexdigest()  # the record is of the fixed file
    assert not list(final.parent.glob("render.sound.mp4"))


@needs_ffmpeg
def test_a_check_that_cannot_measure_or_fix_keeps_the_rendered_file(data, monkeypatch):
    from clipfoundry.pipeline import audio_timing
    from clipfoundry.pipeline.ffmpeg_utils import FFmpegError

    real, real_timing = loudness.measure, audio_timing.require_valid

    def broken(*a, **k):
        raise FFmpegError("no measurement")

    monkeypatch.setattr(loudness, "measure", broken)
    out = _render_clip(data, "unmeasured")
    assert Path(out["output_path"]).exists()
    assert out["render_info"]["qc"]["sound"]["status"] == "skipped"

    # the second try fails (its file's audio timing is refused): the first file stays, judged as it was measured
    monkeypatch.setattr(loudness, "measure", lambda path, *a, **k: {**real(path, *a, **k), "tp": -0.4})

    def refuse_second(path, *a, **k):
        if Path(path).name == "render.sound.mp4":
            raise FFmpegError("bad timing")
        return real_timing(path, *a, **k)

    monkeypatch.setattr(audio_timing, "require_valid", refuse_second)
    out = _render_clip(data, "unfixed")
    sound = out["render_info"]["qc"]["sound"]
    assert sound["status"] == "warn" and sound["fixed_db"] == 0.0 and "ceiling_dbfs" not in sound
    assert "Peaks reach -0.4 dBTP" in sound["note"]
    assert not list(Path(out["output_path"]).parent.glob("render.sound.mp4"))


# ------------------------------------------------------------------ the full-video renderer
@pytest.mark.slow
@needs_ffmpeg
def test_a_full_video_that_missed_its_level_gets_its_sound_once_more(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry.studio import engine

    from test_studio_editor_render import _asset, _plan, _tone_video

    real, seen = loudness.measure, []

    def first_one_short(path, cancelled=None, timeout=600.0):
        got = real(path, cancelled, timeout)
        if not seen:  # say the first file came out 2 dB short of its level, with room under the ceiling
            got = {**got, "lufs": got["lufs"] - 2.0, "tp": min(got["tp"], -6.0)}
        seen.append(got)
        return got

    monkeypatch.setattr(loudness, "measure", first_one_short)
    a = _asset(_tone_video(tmp_path / "A.mp4", 3, 440), "video")
    plan = _plan([{"id": "a", "asset_id": "A", "kind": "video", "in_ms": 0, "out_ms": 3000, "include": True}])
    assert engine.validate(plan, {"A": a}) == []
    info = engine.render(plan, {"A": a}, {}, tmp_path / "out.mp4", preview=True)
    sound = info["qc"]["sound"]
    assert info["qc"]["version"] == 1 and len(seen) == 2
    assert sound["fixed_db"] == pytest.approx(2.0) and sound["expected_lufs"] == pytest.approx(-14.0, abs=0.1)
    assert sound["source_lufs"] is not None and sound["boost_capped"] is False
    # the second file really is 2 dB louder than the first (the mix was made again with the correction)
    assert sound["lufs"] == pytest.approx(seen[0]["lufs"] + 4.0, abs=0.3)
