"""Render artifact records (time map, final transcript, hash) and the final quality gate, on real renders of small
synthetic videos (ffmpeg test pattern + tone; transcripts are synthetic and labeled as such)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipfoundry import config
from clipfoundry.pipeline import artifact, render
from clipfoundry.pipeline.common import JobContext

from synthetic_media import make_video, needs_ffmpeg, words_every, words_from

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


# ------------------------------------------------------------------ final quality gate: media checks
SPEECH = ("Talk to customers before you build anything. Most founders skip this step and regret it later. "
          "Ask them which problem costs them real money every week.")


def _status(checks: list[dict]) -> dict[str, str]:
    return {c["name"]: c["status"] for c in checks}


@pytest.fixture()
def rendered(data, tmp_path):
    """A real 1080x1920 render of a synthetic source (test pattern + tone, synthetic transcript)."""
    src = make_video(tmp_path / "src.mp4", seconds=9.0)
    project = _project(src, tmp_path / "proj")
    clip = {"id": "c1", "start": 0.1, "end": 8.4, "hook": "", "edit": {"tracking": "center"}}
    out = render.render_clip(project, clip, words_from(SPEECH), {**config.DEFAULT_SETTINGS, **FAST}, JobContext())
    return out


@needs_ffmpeg
def test_a_clean_render_passes_every_check(rendered):
    from clipfoundry.pipeline import quality

    rep = quality.evaluate(rendered["output_path"], rendered["render_info"], {"edit": {}})
    st = _status(rep["checks"])
    assert rep["passed"] and not rep["blockers"], rep["blockers"]
    for name in ("hash", "codecs", "audio_stream", "dimensions", "duration", "decode", "black", "frozen", "silence",
                 "captions", "cuts"):
        assert st[name] == "pass", (name, rep["checks"])
    assert st["content"] == "skipped"  # no transcript analysis for a hand-made clip: said, not assumed
    assert rep["artifact_sha256"] == rendered["render_info"]["artifact"]["sha256"]
    assert rep["bindings"]["transcript_sha256"] == rendered["render_info"]["artifact"]["transcript_sha256"]
    assert "decode" in rep["coverage"]["deterministic"] and "black" in rep["coverage"]["heuristic"]


@needs_ffmpeg
def test_truncated_or_changed_files_are_caught(rendered, tmp_path):
    from clipfoundry.pipeline import quality

    good = Path(rendered["output_path"])
    cut = tmp_path / "truncated.mp4"
    cut.write_bytes(good.read_bytes()[: good.stat().st_size * 2 // 5])  # index at the front: still "full length"
    rep = quality.evaluate(cut, rendered["render_info"], {"edit": {}})
    st = _status(rep["checks"])
    assert not rep["passed"] and st["decode"] == "fail" and st["hash"] == "fail"
    assert any("decode" in b.lower() for b in rep["blockers"])
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert quality.media_checks(empty, {})[0]["status"] == "fail"


@needs_ffmpeg
def test_picture_and_sound_problems_are_judged_in_context(data, tmp_path):
    from clipfoundry.pipeline import quality

    def run(path: Path, **expected) -> dict[str, str]:
        return _status(quality.media_checks(path, {"has_audio": True, **expected}))

    small = run(make_video(tmp_path / "small.mp4", seconds=4.0))
    assert small["dimensions"] == "fail" and small["decode"] == "pass"
    black = run(make_video(tmp_path / "black.mp4", seconds=6.0, size="360x640", black=(0, 5.5)))
    assert black["black"] == "fail"
    opens_black = run(make_video(tmp_path / "opens.mp4", seconds=6.0, size="360x640", black=(0, 1.0)))
    assert opens_black["black"] == "warn"
    still_silent = run(make_video(tmp_path / "still.mp4", seconds=6.0, size="360x640", frozen=True, silent=(0, 6)))
    assert still_silent["frozen"] == "fail" and still_silent["silence"] == "fail"
    still_talking = run(make_video(tmp_path / "podcast.mp4", seconds=6.0, size="360x640", frozen=True))
    assert still_talking["frozen"] == "warn" and still_talking["silence"] == "pass"  # a still image over speech
    no_audio = run(make_video(tmp_path / "mute.mp4", seconds=3.0, size="360x640", audio=False))
    assert no_audio["audio_stream"] == "fail"
    gap = make_video(tmp_path / "gap.mp4", seconds=8.0, size="360x640", silent=(2.0, 5.0))
    words = [{"w": f"w{i}", "start": 2.2 + 0.5 * i, "end": 2.5 + 0.5 * i, "src_start": 0, "src_end": 0}
             for i in range(6)]
    assert run(gap, transcript={"words": words})["silence"] == "fail"  # speech where the sound is gone
    assert run(gap)["silence"] == "warn"  # a 3 s pause without known speech: only a warning


@needs_ffmpeg
def test_caption_and_cut_timing(rendered, tmp_path):
    from clipfoundry.pipeline import quality

    art = rendered["render_info"]["artifact"]
    bad_srt = tmp_path / "late.srt"
    bad_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n\n2\n00:00:30,000 --> 00:00:31,000\ntoo late\n")
    checks = quality.media_checks(rendered["output_path"], {"srt": str(bad_srt), "duration": art["duration"]})
    assert _status(checks)["captions"] == "fail"
    edl = {"segments": [{"src_start": 1.0, "src_end": 4.0}, {"src_start": 5.0, "src_end": 8.0}]}
    w = lambda text, a, b: {"w": text, "src_start": a, "src_end": b}  # noqa: E731
    ok = {"words": [w("a", 1.1, 1.4), w("b", 5.2, 5.5), w("c", 7.5, 7.9)]}
    assert quality._cut_checks(ok, edl)[0]["status"] == "pass"  # noqa: SLF001
    ends_mid = {"words": [w("a", 1.1, 1.4), w("c", 7.8, 8.3)]}
    assert quality._cut_checks(ends_mid, edl)[0]["status"] == "fail"  # noqa: SLF001
    clipped = {"words": [w("a", 1.1, 1.4), w("mid", 3.8, 4.3), w("c", 7.5, 7.9)]}
    assert quality._cut_checks(clipped, edl)[0]["status"] == "warn"  # noqa: SLF001


def test_content_estimates_never_pass_an_edited_clip_silently():
    from clipfoundry.pipeline import quality

    analysis = {"structure": {"hook": True, "context": True, "payoff": True}, "flags": []}
    assert quality.content_checks({"analysis": analysis, "edit": {}})[0]["status"] == "pass"
    assert quality.content_checks({"analysis": analysis, "edit": {"end": 20.0}})[0]["status"] == "warn"
    blocked = {**analysis, "flags": [{"id": "misleading_cut", "label": "Misleading cut", "severity": "block",
                                      "detail": "ends before the answer"}]}
    assert quality.content_checks({"analysis": blocked, "edit": {}})[0]["status"] == "fail"


# ------------------------------------------------------------------ the gate in the Autopilot pipeline
def _drain(worker: str) -> list[dict]:
    """Run every due job of one worker to completion, the way the worker host would."""
    from clipfoundry.autopilot import host, queue

    done = []
    while (job := queue.claim(worker, "test")) is not None:
        result = host.HANDLERS[job["kind"]](host.Job(job, "test")) or {}
        queue.complete(job, "test", result)
        done.append(result)
    return done


@needs_ffmpeg
def test_the_gate_decides_what_is_scheduled_and_uploaded(data, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue, scheduler, state
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import write_json
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.save_settings({**FAST, "autopilot_youtube": True, "autopilot_tiktok": True})
    pdir = data / "projects" / "p1"
    pdir.mkdir(parents=True)
    src = make_video(pdir / "source.mp4", seconds=9.0)
    meta = probe(src)
    project = db.create_project("synthetic", source_path=str(src), status="ready", origin="autopilot", info=meta,
                                **{k: meta[k] for k in ("duration", "width", "height", "fps")})
    write_json(pdir / "transcript.json", {"segments": [{"words": words_from(SPEECH)}]})  # synthetic transcript
    clip = db.create_clip(project["id"], start=0.1, end=8.4, title="Talk to customers before you build anything",
                          status="queued", caption_text=SPEECH, edit={"tracking": "center"})
    process.render_single(clip["id"], JobContext())
    clip = db.get_clip(clip["id"])
    assert clip["status"] == "ready"
    host.WorkerHost(periodic=False)  # registers the handlers

    def planned() -> set[str]:
        return {c["platform"] for c in scheduler.candidates(db.get_settings(), 0) if c["clip"]["id"] == clip["id"]}

    assert planned() == set()  # nothing is scheduled before packaging and the gate
    queue.enqueue("package_clip", {"clip_id": clip["id"]})
    _drain("packager")
    [result] = _drain("quality_gate")
    assert result["status"] == "passed", result
    rep = gate.report_for(clip)
    assert rep["status"] == "passed" and set(rep["metadata"]) == {"youtube", "tiktok"}
    assert rep["artifact_sha256"] == clip["render_info"]["artifact"]["sha256"]
    rows = db.select("metadata_candidates", "clip_id = ? AND selected = 1", (clip["id"],))
    assert {r["artifact_sha256"] for r in rows} == {rep["artifact_sha256"]}  # written for this very render
    assert planned() == {"youtube", "tiktok"}

    # an invented claim in the YouTube text keeps YouTube out; TikTok is unaffected
    yt = next(r for r in rows if r["platform"] == "youtube")
    db.update("metadata_candidates", yt["id"], selected=0)
    db.insert("metadata_candidates", {**{k: yt[k] for k in ("clip_id", "platform", "style", "description", "caption",
                                                             "tags", "hashtags", "score", "artifact_sha256")},
                                      "title": "7 secrets every founder hides from investors", "selected": 1})
    assert planned() == {"tiktok"}  # the new text has not been checked yet
    _drain("quality_gate")
    assert planned() == {"tiktok"}
    assert gate.report_for(clip)["metadata"]["youtube"]["status"] == "failed"

    # right before an upload the file is hashed again
    path = clip["output_path"]
    assert gate.verify_file(clip, path)["status"] == "passed"
    good = Path(path).read_bytes()
    Path(path).write_bytes(good[: len(good) // 3])  # the file is damaged after it was checked
    assert planned() == set()
    with pytest.raises(queue.Wait):
        gate.verify_file(clip, path)  # not checked yet: wait for the gate, never upload unchecked bytes
    [result] = _drain("quality_gate")
    assert result["status"] == "failed"
    with pytest.raises(queue.Fail):
        gate.verify_file(clip, path)
    assert planned() == set()
    assert any(e["kind"] == "quality_failed" for e in state.events(ref_type="clip", ref_id=clip["id"]))
    item = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "title": "t",
                                                "description": "d", "privacy": "public", "planned_at": 1e10,
                                                "options": {"made_for_kids": False}, "status": "awaiting_approval"})
    with pytest.raises(ValueError, match="did not pass the final quality check"):
        scheduler.approve(item["id"], {})  # approving a file that failed the gate is refused up front
