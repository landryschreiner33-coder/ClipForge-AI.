"""Missing live sound and final-check handoffs are durable, bounded and tied to actual media."""
from __future__ import annotations

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True})
    return tmp_path


def video(path: Path, *, audio: bool) -> Path:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg needed for real video-only detection")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=1"]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=500:duration=1"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac"]
    subprocess.run([*cmd, str(path)], check=True, capture_output=True)
    return path


def test_video_only_source_fails_before_whisper_and_health_explains_it(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, queue
    from clipfoundry.office import health

    host.WorkerHost(periodic=False)
    src = db.insert("sources", {"platform": "local", "external_id": "no-sound", "title": "No sound",
                                "local_path": str(video(data / "silent.mp4", audio=False)), "user_added": 1})
    queue.enqueue("hunt_source", {"source_id": src["id"]}, ref=("source", src["id"]))
    row = queue.claim("clip_hunter", "test")
    attempts = []
    monkeypatch.setattr(hunter.process, "prepare", lambda *a, **kw: attempts.append(True))
    with pytest.raises(queue.Fail, match="no audio track") as failed:
        hunter.hunt_source(host.Job(row, "test"))
    queue.fail(row, "test", str(failed.value), failed.value.fix)
    saved = db.fetch("sources", src["id"])
    assert not attempts and saved["status"] == "failed"
    assert db.get_project(saved["project_id"])["info"]["has_audio"] is False
    assert db.fetch("worker_jobs", row["id"])["status"] == "failed"
    assert health.media_workflow()["status"] == "degraded"


def test_live_skips_video_only_minute_and_transcribes_later_audio_once(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue

    src = db.insert("sources", {"platform": "local", "external_id": "mixed", "title": "Mixed stream",
                                "kind": "live", "local_path": str(data / "stream.mkv"), "user_added": 1})
    sess = live.Session(src, db.get_settings())
    video(sess.segdir / "silent.mkv", audio=False)
    video(sess.segdir / "talk.mkv", audio=True)
    row = queue.enqueue("live_capture", {"source_id": src["id"]}, ref=("source", src["id"]))
    job = host.Job(row, "test")
    locks, calls = [], []

    @contextmanager
    def locked(*args, **kwargs):
        locks.append(args[0])
        yield

    def transcribe(wav, duration, settings, ctx, **kwargs):
        assert Path(wav).is_file() and kwargs["allow_cpu_fallback"] is False
        calls.append(True)
        return {"language": "en", "segments": [{"start": 0.1, "end": 0.5, "text": "hello",
                                                "words": [{"w": "hello", "start": 0.1, "end": 0.5}]}]}

    monkeypatch.setattr(live.gpu.manager, "heavy", locked)
    monkeypatch.setattr(live.transcribe, "transcribe", transcribe)
    live.process_segment(sess, "silent.mkv", 1.0, job)
    assert not calls and not locks and sess.missing_audio == [[0, 1]] and sess.offset == 1
    live.process_segment(sess, "talk.mkv", 1.0, job)
    assert calls == [True] and locks == ["live transcription"] and sess.words[0]["start"] == pytest.approx(1.1)
    again = live.Session(db.fetch("sources", src["id"]), db.get_settings())
    assert again.missing_audio == [[0, 1]] and again.done_names() == {"silent.mkv", "talk.mkv"}
    assert db.get_project(sess.project["id"])["info"]["has_audio"] is True


def test_entire_video_only_live_recording_is_saved_without_post_live_retry(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, live, queue

    src = db.insert("sources", {"platform": "local", "external_id": "mute-live", "title": "Mute live",
                                "kind": "live", "user_added": 1})
    sess = live.Session(src, db.get_settings())
    video(sess.segdir / "silent.mkv", audio=False)
    row = queue.enqueue("live_capture", {"source_id": src["id"]}, ref=("source", src["id"]))
    job = host.Job(row, "test")
    live.process_segment(sess, "silent.mkv", 1.0, job)
    with pytest.raises(queue.Fail, match="video only"):
        live._finish_capture(sess, job)
    assert (sess.pdir / "source.mkv").is_file()
    assert db.fetch("sources", src["id"])["status"] == "failed"
    assert not [j for j in queue.jobs(worker="live_monitor") if j["kind"] == "post_live"]


def test_final_recording_preserves_returning_audio_after_a_silent_segment(data):
    import math
    import wave
    from array import array
    from clipfoundry import db
    from clipfoundry.autopilot import live
    from clipfoundry.pipeline.ffmpeg_utils import extract_audio, probe

    src = db.insert("sources", {"platform": "local", "external_id": "returning-sound", "kind": "live"})
    sess = live.Session(src, db.get_settings())
    video(sess.segdir / "silent.mkv", audio=False)
    video(sess.segdir / "talk.mkv", audio=True)
    sess.segments = [{"name": "silent.mkv", "start": 0, "end": 1},
                     {"name": "talk.mkv", "start": 1, "end": 2}]
    sess.missing_audio, sess.offset = [[0, 1]], 2
    output = live.finalize(sess)
    assert probe(output)["has_audio"] and probe(output)["duration"] == pytest.approx(2, abs=.15)
    wav = data / "joined.wav"
    extract_audio(output, wav, 2)
    with wave.open(str(wav)) as sound:
        samples = array("h", sound.readframes(sound.getnframes()))
        rate = sound.getframerate()
    rms = lambda values: math.sqrt(sum(v * v for v in values) / len(values))
    assert rms(samples[int(.2 * rate):int(.8 * rate)]) < 5
    assert rms(samples[int(1.2 * rate):int(1.8 * rate)]) > 200
    assert not list(sess.segdir.glob("joined-audio-*.mkv"))


def automatic_clip(data):
    from clipfoundry import db

    original, output = data / "source.mp4", data / "clip.mp4"
    original.write_bytes(b"saved source")
    output.write_bytes(b"saved output")
    src = db.insert("sources", {"platform": "local", "external_id": "saved", "user_added": 1})
    project = db.create_project("Saved", origin="autopilot", source_id=src["id"], source_path=str(original),
                                duration=12)
    return db.create_clip(project["id"], start=1.2, end=9.4, status="ready", output_path=str(output))


@pytest.mark.parametrize(("failure", "robot", "stage"), [("captions", "glyph", "captions"),
                                                         ("cuts", "story", "plan"),
                                                         ("decode", "splice", "render")])
def test_quality_returns_specific_reason_to_the_responsible_stage(data, failure, robot, stage):
    from clipfoundry.autopilot import gate, queue
    from clipfoundry.office import view

    clip = automatic_clip(data)
    rep = {"id": "report", "artifact_sha256": "old-bytes", "blockers": ["A specific defect"],
           "checks": [{"name": failure, "status": "fail"}]}
    work = gate.repair_media(clip, rep)
    assert work["max_attempts"] == 1 and work["payload"]["handoff"]["to_role"] == robot
    assert work["payload"]["handoff"]["stage"] == stage
    task = next(r for r in view.role_states({"autopilot_enabled": True}) if r["id"] == robot)["task"]
    assert task["handoff"]["reason"] == "A specific defect" and task["handoff"]["attempt"] == 1
    assert task["shared"]["clip_id"] == clip["id"] and task["progress"] is None
    assert "Final check returned this work with a specific reason" in task["dependencies"]
    queue.cancel(work["id"])
    assert gate.repair_media(clip, rep) is None


def test_grounding_repair_stays_local_and_has_a_specific_bounded_handoff(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, packaging

    clip = automatic_clip(data)
    rep = {"artifact_sha256": "checked", "metadata": {"youtube": {"status": "failed", "problems": ["invented name"]}}}
    work = gate.repair_text(clip, rep, 10)
    db.save_settings({"ai_provider": "claude", "autopilot_youtube": True})
    captured = []
    monkeypatch.setattr(packaging, "package", lambda c, s, p, settings: captured.append(settings) or
                        {"score": 80, "title": "Real words", "style": "fallback"})
    monkeypatch.setattr(gate, "request", lambda *a, **kw: None)
    packaging.package_clip(host.Job(work, "test"))
    assert captured[0]["ai_provider"] == "heuristic" and not captured[0]["nvidia_enabled"]
    assert work["payload"]["handoff"]["to_role"] == "quill"
    assert "invented name" in work["payload"]["handoff"]["reason"]


def test_story_repair_keeps_complete_words_and_validates_the_new_plan(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate
    from clipfoundry.pipeline import blueprint

    clip = automatic_clip(data)
    words = [{"w": "First", "start": 1, "end": 1.5}, {"w": "last", "start": 9, "end": 9.5}]
    bp = blueprint.Blueprint(clip["id"], clip["project_id"], "source", "input", [blueprint.Interval(1.2, 9.4)])
    bp.audio.silence = "light"
    db.insert("clip_blueprints", {"clip_id": clip["id"], "origin": "strategist", "status": "valid",
                                  "sha256": bp.sha256(), "blueprint": bp.to_dict()})
    monkeypatch.setattr(gate.process, "load_words", lambda project: words)
    gate._repair_cut_plan(clip, "The output clipped the first word")
    updated = blueprint.plan_of(clip["id"])
    assert updated.intervals[0].start < 1 and updated.intervals[-1].end > 9.5
    assert updated.audio.silence == "off" and not blueprint.errors(blueprint.validate(updated, 12, words))
    assert "first word" in updated.reasons[-1]


def test_track_timing_checks_report_measured_offsets_without_claiming_lip_sync():
    from clipfoundry.pipeline import quality

    info = {"has_audio": True, "video_start": 0, "audio_start": 0.7, "video_duration": 10, "audio_duration": 9.3}
    check = quality._av_timing(info)
    assert check["status"] == "fail" and check["values"]["start_offset_s"] == 0.7
    assert "Lip sync not measured" in check["detail"]
    assert quality._av_timing({**info, "audio_start": 0})["status"] == "pass"
    assert quality._av_timing({"has_audio": False})["status"] == "skipped"
