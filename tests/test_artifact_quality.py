"""Render artifact records (time map, final transcript, hash) and the final quality gate, on real renders of small
synthetic videos (ffmpeg test pattern + tone; transcripts are synthetic and labeled as such)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipfoundry import config
from clipfoundry.pipeline import artifact, render
from clipfoundry.pipeline.common import JobContext

from synthetic_media import make_video, needs_ffmpeg, words_every

FAST = {"encoder": "x264", "x264_preset": "ultrafast"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


def _project(src: Path, pdir: Path) -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    meta = probe(src)
    return {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(pdir), "info": meta,
            "options": {}, **meta}


def _speech_with_gap() -> list[dict]:
    """Synthetic transcript: words from 0.2-3 s, a 2.5 s pause, words from 5.5-8 s."""
    first = words_every(3.0)
    second = [{**w, "start": w["start"] + 5.3, "end": w["end"] + 5.3} for w in words_every(2.7)]
    return first + second


# ------------------------------------------------------------------ the time map
def test_edit_decisions_map_source_ranges_to_output_time():
    tl = render.Timeline([(1.0, 3.0), (4.0, 6.0)], speed=1.0)
    assert artifact.edit_decisions(tl) == [
        {"src_start": 1.0, "src_end": 3.0, "out_start": 0.0, "out_end": 2.0, "speed": 1.0},
        {"src_start": 4.0, "src_end": 6.0, "out_start": 2.0, "out_end": 4.0, "speed": 1.0}]
    fast = render.Timeline([(0.0, 5.0)], speed=1.25)
    assert artifact.edit_decisions(fast)[0]["out_end"] == 4.0


def test_final_transcript_keeps_only_what_is_heard():
    tl = render.Timeline([(1.0, 3.0), (4.0, 6.0)], speed=1.0)
    words = [{"w": "kept", "start": 1.2, "end": 1.5}, {"w": "edge", "start": 2.8, "end": 3.3},
             {"w": "um", "start": 3.1, "end": 3.9}, {"w": "after", "start": 4.1, "end": 4.4},
             {"w": "outside", "start": 6.5, "end": 6.8}]
    heard, removed = artifact.final_words(words, tl, 1.0, 6.0)
    assert [w["w"] for w in heard] == ["kept", "after"]
    assert removed == 2  # "edge" is mostly inside the cut, "um" entirely; "outside" is not in the clip at all
    after = heard[1]
    assert (after["src_start"], after["start"]) == (4.1, 2.1)  # original time and time in the output


# ------------------------------------------------------------------ a real render
@needs_ffmpeg
def test_render_writes_the_artifact_record(data, tmp_path):
    src = make_video(tmp_path / "src.mp4", seconds=9.0)
    project = _project(src, tmp_path / "proj")
    words = _speech_with_gap()
    clip = {"id": "c1", "start": 0.1, "end": 8.4, "hook": "", "edit": {"tracking": "center", "silence": "light"}}
    out = render.render_clip(project, clip, words, {**config.DEFAULT_SETTINGS, **FAST}, JobContext())

    art = out["render_info"]["artifact"]
    mp4 = Path(out["output_path"])
    assert art["path"] == str(mp4) and art["sha256"] == artifact.sha256_file(mp4) and art["size"] == mp4.stat().st_size
    assert (art["probe"]["width"], art["probe"]["height"]) == (1080, 1920)
    assert art["probe"]["video_codec"] == "h264" and art["probe"]["audio_codec"] == "aac"
    assert art["settings"]["silence"] == "light" and art["settings"]["tracking"] == "center"

    edl = json.loads(Path(art["edl"]).read_text())
    assert len(edl["segments"]) == 2, edl  # the long pause was cut
    assert edl["segments"][0]["out_start"] == 0.0
    assert abs(edl["segments"][-1]["out_end"] - art["duration"]) < 0.05
    assert abs(art["duration"] - out["duration"]) < 0.01

    final = json.loads(Path(art["transcript"]).read_text())
    assert final["words"] and all(0 <= w["start"] <= w["end"] <= art["duration"] + 1e-6 for w in final["words"])
    assert art["transcript_sha256"] == artifact.sha256_json(final["words"])
    # the second sentence plays right after the first one: the pause is gone from the output time line
    first_after_gap = next(w for w in final["words"] if w["src_start"] >= 5.3)
    assert first_after_gap["start"] < 4.0
    assert artifact.final_sentences(out["render_info"])[0].startswith("this is a test clip")
    assert artifact.of(out["render_info"]) == art and artifact.of({}) is None
