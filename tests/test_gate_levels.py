"""Batch 5c (docs/clipforge/QC.md): the final quality gate's one decode pass also measures the loudness and true peak
(as the renderers do) and the picture's levels against EBU R103, and reads the colour tags. All of them warn, never
block: on real FFmpeg encodes of synthetic pictures and tones.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from clipfoundry.pipeline import loudness, quality

from synthetic_media import needs_ffmpeg

TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def _make(path: Path, video: str, *, audio: str | None = "sine=frequency=330:sample_rate=48000:duration=4",
          af: str = "anull", vf: str = "null", tags: list[str] = TAGS) -> Path:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        cmd += ["-f", "lavfi", "-i", audio, "-af", af, "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-vf", f"{vf},format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", *tags, "-shortest",
            str(path)]
    subprocess.run(cmd, check=True)
    return path


def _checks(path: Path, **expected) -> dict[str, dict]:
    return {c["name"]: c for c in quality.media_checks(path, {"has_audio": True, **expected})}


PATTERN = "testsrc2=s=360x640:r=30:d=4"
LEGAL = "scale=out_color_matrix=bt709:out_range=tv"


@needs_ffmpeg
def test_the_gate_reads_loudness_levels_and_tags_in_its_one_pass(tmp_path):
    assert quality.GATE_VERSION == 4  # every stored report is checked again once
    ok = _make(tmp_path / "ok.mp4", PATTERN, vf=LEGAL)
    c = _checks(ok)
    assert c["decode"]["status"] == "pass" and c["decode"]["values"]["frames"] == 120  # every frame still counted
    assert c["levels"]["status"] == "pass" and c["levels"]["values"]["frames"] == 8  # 2 a second
    assert c["colour_tags"]["status"] == "pass" and c["colour_tags"]["detail"] == "BT.709, limited range"
    # the same measurement as the renderers': a plain tone made with FFmpeg's defaults plays quieter than -14 LUFS
    lufs = loudness.measure(ok)["lufs"]
    assert c["loudness"]["status"] == "warn" and abs(c["loudness"]["values"]["lufs"] - lufs) < 0.05
    assert c["loudness"]["detail"].startswith(f"Plays {-14 - lufs:.1f} dB quieter than most videos")
    # brought to -14 LUFS: passes, with the level in the note
    level = _make(tmp_path / "level.mp4", PATTERN, vf=LEGAL, af=f"volume={-14 - lufs:.2f}dB")
    lv = _checks(level)["loudness"]
    assert lv["status"] == "pass" and lv["detail"].startswith("As loud as most videos (-14.")
    assert all(c["kind"] in ("deterministic", "heuristic") for c in _checks(level).values())


@needs_ffmpeg
def test_hot_sound_wrong_levels_and_other_tags_only_warn(tmp_path):
    hot = _checks(_make(tmp_path / "hot.mp4", PATTERN, vf=LEGAL, af="volume=24dB"))["loudness"]
    assert hot["status"] == "warn" and "Peaks reach" in hot["detail"] and hot["values"]["tp"] > -1
    # a full-range picture in a limited-range file: blacks and whites past the video range everywhere
    split = "color=c=white:s=360x640:r=30:d=4,drawbox=x=0:y=0:w=180:h=640:color=black:t=fill"
    wrong = _checks(_make(tmp_path / "wrong.mp4", split, vf="scale=in_range=tv:out_range=pc"))
    assert wrong["levels"]["status"] == "warn" and "full-range picture" in wrong["levels"]["detail"]
    assert wrong["levels"]["values"]["y_min"] < 16 and wrong["levels"]["values"]["y_max"] > 235
    # very saturated colours pushed past the RGB limits in part of the clip
    saturated = f"{LEGAL},hue=s=1.8:enable='gte(t,2)'"
    loud_colour = _checks(_make(tmp_path / "sat.mp4", PATTERN, vf=saturated))["levels"]
    assert loud_colour["status"] == "warn" and "outside the broadcast range" in loud_colour["detail"]
    assert 0 < loud_colour["values"]["frames_outside"] < loud_colour["values"]["frames"]
    sd_tags = ["-colorspace", "smpte170m", "-color_primaries", "smpte170m"]
    sd = _checks(_make(tmp_path / "sd.mp4", PATTERN, vf=LEGAL, tags=sd_tags))
    assert sd["colour_tags"]["status"] == "warn" and "matrix smpte170m" in sd["colour_tags"]["detail"]
    # an untagged file: players read it as BT.709, so it passes
    bare = _checks(_make(tmp_path / "bare.mp4", PATTERN, vf=LEGAL, tags=[]))["colour_tags"]
    assert bare["status"] == "pass" and "untagged" in bare["detail"]
    for c in (hot, wrong["levels"], loud_colour, sd["colour_tags"]):
        assert c["status"] != "fail"  # never blocks publishing


@needs_ffmpeg
def test_no_sound_or_silence_skips_the_loudness(tmp_path):
    mute = _checks(_make(tmp_path / "mute.mp4", PATTERN, vf=LEGAL, audio=None), has_audio=False)
    assert mute["loudness"]["status"] == "skipped" and mute["levels"]["status"] == "pass"
    silent = _checks(_make(tmp_path / "silent.mp4", PATTERN, vf=LEGAL, audio="anullsrc=r=48000:cl=stereo:d=4"))
    assert silent["loudness"]["status"] == "skipped" and silent["silence"]["status"] == "fail"
