"""Synthetic render stand-ins verify rollback/crash recovery preserves the whole previously completed artifact."""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


def _clip(data):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, rights
    from clipfoundry.pipeline import artifact

    source_path = data / "synthetic-source.mp4"
    source_path.write_bytes(b"synthetic source; not decoded by these tests")
    source = db.insert("sources", {"platform": "local", "external_id": "synthetic", "status": "analyzed"})
    rights.add_rule("source", source["id"], rights.OWNED, "Synthetic test media")
    project = db.create_project("Synthetic", source_path=str(source_path), origin="autopilot", source_id=source["id"])
    output = data / "completed" / "clip-old.mp4"
    output.parent.mkdir()
    output.write_bytes(b"previously completed video")
    paths = [output.parent / name for name in
             ("captions.ass", "captions.srt", artifact.EDL_FILE, artifact.TRANSCRIPT_FILE, "thumb-old.jpg")]
    saved = {path: f"original {path.name}\n".encode() for path in paths}
    for path, content in saved.items():
        path.write_bytes(content)
    record = {"sha256": artifact.sha256_file(output), "path": str(output), "edl": str(paths[2]),
              "transcript": str(paths[3]), "captions": {"ass": str(paths[0]), "srt": str(paths[1])}}
    clip = db.create_clip(project["id"], status="ready", start=0, end=30, output_path=str(output),
                          thumb_path=str(paths[4]), duration=30, edit={"hook": "Owner's saved edit"},
                          render_info={"artifact": record})
    job = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    return clip, job, output, saved


def _replace_files(output, saved):
    from clipfoundry.pipeline import artifact

    for path in saved:
        path.write_bytes(f"attempted {path.name}\n".encode())
    Path(next(path for path in saved if path.name == "thumb-old.jpg")).unlink()
    new_video = output.with_name("clip-new.mp4")
    new_video.write_bytes(b"attempted new video")
    new_thumb = output.with_name("thumb-new.jpg")
    new_thumb.write_bytes(b"attempted new thumbnail")
    (output.parent / "blueprint.json").write_bytes(b"attempted blueprint")  # absent from the saved old artifact
    output.unlink()
    return {"output_path": str(new_video), "thumb_path": str(new_thumb),
            "render_info": {"artifact": {"sha256": artifact.sha256_file(new_video)}}, "duration": 31}


def _assert_restored(clip, output, saved):
    from clipfoundry import db
    from clipfoundry.autopilot import gate

    assert output.read_bytes() == b"previously completed video"
    assert all(path.read_bytes() == content for path, content in saved.items())
    assert not (output.parent / "blueprint.json").exists()
    current = db.get_clip(clip["id"])
    assert all(current[field] == clip[field] for field in gate.ORIGINAL_FIELDS)
    assert current["edit"] == clip["edit"]
    assert not list(output.parent.glob("*.bak*"))
    assert not list(output.parent.glob("*.sidecars.json"))


@pytest.mark.parametrize("outcome", ["failed_encode", "cancel_after_success"])
def test_regeneration_restores_video_sidecars_and_thumbnail(data, monkeypatch, outcome):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    clip, job, output, saved = _clip(data)
    claimed = queue.claim("analyzer", "repair")
    handler = host.Job(claimed, "repair")

    def interrupted(clip_id, ctx):
        new = _replace_files(output, saved)
        db.update_clip(clip_id, **new, status="ready" if outcome == "cancel_after_success" else "error",
                       error="" if outcome == "cancel_after_success" else "Synthetic encode failure")
        if outcome == "cancel_after_success":
            handler.cancel_event.set()

    monkeypatch.setattr(gate.process, "render_single", interrupted)
    error = queue.Canceled if outcome == "cancel_after_success" else queue.Fail
    with pytest.raises(error):
        gate.regenerate_clip(handler)
    _assert_restored(clip, output, saved)
    assert not queue.jobs(("queued",), worker="packager")
    assert claimed["id"] == job["id"]


@pytest.mark.parametrize("completed", [False, True])
def test_crash_recovery_restores_or_preserves_the_whole_committed_artifact(data, monkeypatch, completed):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    class SyntheticCrash(BaseException):
        pass

    clip, job, output, saved = _clip(data)
    claimed = queue.claim("analyzer", "repair")
    new = {}

    def crash(clip_id, ctx):
        new.update(_replace_files(output, saved))
        db.update_clip(clip_id, **(new if completed else {}), status="ready" if completed else "rendering")
        raise SyntheticCrash()

    monkeypatch.setattr(gate.process, "render_single", crash)
    with pytest.raises(SyntheticCrash):
        gate.regenerate_clip(host.Job(claimed, "repair"))
    assert list(output.parent.glob("*.sidecars.json"))
    db.update("worker_jobs", job["id"], lease_until=0)
    assert queue.recover()["failed"] == 1
    assert gate.recover_regenerations() == (0 if completed else 1)
    if not completed:
        _assert_restored(clip, output, saved)
        assert len([j for j in queue.jobs(ref=("clip", clip["id"])) if j["kind"] == "regenerate_clip"]) == 2
    else:
        assert db.get_clip(clip["id"])["output_path"] == new["output_path"]
        assert Path(new["output_path"]).read_bytes() == b"attempted new video"
        assert (output.parent / "captions.srt").read_bytes() == b"attempted captions.srt\n"
        assert not Path(clip["thumb_path"]).exists()
        assert Path(new["thumb_path"]).is_file()
        assert not list(output.parent.glob("*.bak*")) and not list(output.parent.glob("*.sidecars.json"))
        assert queue.jobs(("queued",), worker="packager")


@pytest.mark.parametrize("cancel_after_success", [False, True])
def test_sidecar_restore_failure_retains_the_entire_checkpoint_for_recovery(data, monkeypatch,
                                                                           cancel_after_success):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    clip, job, output, saved = _clip(data)
    claimed = queue.claim("analyzer", "repair")
    handler = host.Job(claimed, "repair")
    copy = gate.shutil.copy2

    def fail_saved_caption(src, dst, *args, **kwargs):
        if str(src).endswith(".sidecar-1.bak"):
            raise OSError("Synthetic sidecar restore failure")
        return copy(src, dst, *args, **kwargs)

    def broken_render(clip_id, ctx):
        new = _replace_files(output, saved)
        db.update_clip(clip_id, **(new if cancel_after_success else {}),
                       status="ready" if cancel_after_success else "error",
                       error="" if cancel_after_success else "Synthetic encode failure")
        if cancel_after_success:
            handler.cancel_event.set()

    monkeypatch.setattr(gate.process, "render_single", broken_render)
    monkeypatch.setattr(gate.shutil, "copy2", fail_saved_caption)
    with pytest.raises(OSError, match="sidecar restore"):
        gate.regenerate_clip(handler)
    assert list(output.parent.glob("*.sidecars.json"))
    assert db.get_clip(clip["id"])["status"] == "error"  # never expose a partially restored artifact as Ready
    queue.fail(claimed, "repair", "Restore was interrupted")
    assert gate.recover_regenerations() == 0  # failure does not discard the remaining saved bytes
    monkeypatch.setattr(gate.shutil, "copy2", copy)
    assert gate.recover_regenerations() == 1
    _assert_restored(clip, output, saved)


def test_rollback_state_failure_keeps_checkpoint_and_does_not_copy_old_bytes(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    clip, _, output, saved = _clip(data)
    handler = host.Job(queue.claim("analyzer", "repair"), "repair")
    update = db.update_clip
    new = {}

    def interrupted(clip_id, ctx):
        new.update(_replace_files(output, saved))
        update(clip_id, **new, status="ready")
        handler.cancel_event.set()

    def cannot_mark_rollback(clip_id, **fields):
        if fields.get("error") == "Restoring the saved clip after an interrupted render":
            raise OSError("Synthetic rollback-state write failure")
        update(clip_id, **fields)

    monkeypatch.setattr(gate.process, "render_single", interrupted)
    monkeypatch.setattr(db, "update_clip", cannot_mark_rollback)
    with pytest.raises(OSError, match="rollback-state"):
        gate.regenerate_clip(handler)
    assert list(output.parent.glob("*.sidecars.json")) and list(output.parent.glob("*.bak"))
    assert not output.exists()  # no target byte is replaced until rollback intent is durable
    assert Path(new["output_path"]).read_bytes() == b"attempted new video"
    assert (output.parent / "captions.srt").read_bytes() == b"attempted captions.srt\n"


def test_failed_story_render_restores_rendered_plan_but_keeps_validated_future_plan(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue
    from clipfoundry.pipeline import artifact, blueprint, quality

    clip, repair, output, saved = _clip(data)
    source = gate._source(clip)
    words = [{"w": "First", "start": 1, "end": 1.5}, {"w": "last", "start": 9, "end": 9.5}]
    previous_plan = blueprint.Blueprint(clip["id"], clip["project_id"], source["id"], "input",
                                        [blueprint.Interval(1.2, 9.4)])
    previous_plan.audio.silence = "light"
    db.insert("clip_blueprints", {"clip_id": clip["id"], "origin": "strategist", "status": "valid",
                                  "sha256": previous_plan.sha256(), "blueprint": previous_plan.to_dict()})
    plan_path = output.parent / "blueprint.json"
    saved[plan_path] = json.dumps(previous_plan.to_dict()).encode()
    plan_path.write_bytes(saved[plan_path])
    render_info = {"artifact": {**clip["render_info"]["artifact"], "blueprint": previous_plan.summary()}}
    db.update_clip(clip["id"], edit={}, render_info=render_info)
    clip = db.get_clip(clip["id"])
    payload = {**repair["payload"], "render_identity": gate._render_identity(clip),
               "edit_identity": gate._edit_identity(clip),
               "original_clip": {key: clip[key] for key in gate.ORIGINAL_FIELDS},
               "handoff": {"stage": "plan", "reason": "Boundary word was clipped"}}
    db.update("worker_jobs", repair["id"], payload=payload)
    report = db.insert("quality_reports", {"clip_id": clip["id"], "artifact_path": str(output),
                                          "artifact_sha256": artifact.sha256_file(output),
                                          "file_stamp": quality.file_stamp(output),
                                          "gate_version": quality.GATE_VERSION, "status": "failed",
                                          "blockers": ["Boundary word was clipped"],
                                          "bindings": {"blueprint": previous_plan.summary()}})
    monkeypatch.setattr(gate.process, "load_words", lambda project: words)

    def failed_render(clip_id, ctx):
        future_plan = blueprint.plan_of(clip_id)
        assert future_plan.sha256() != previous_plan.sha256()
        assert future_plan.audio.silence == "off"
        assert plan_path.read_bytes() == saved[plan_path]  # saving the proposed plan changes only DB history
        _replace_files(output, saved)
        db.update_clip(clip_id, status="error", error="Synthetic story render failure")

    monkeypatch.setattr(gate.process, "render_single", failed_render)
    claimed = queue.claim("analyzer", "repair")
    with pytest.raises(queue.Fail, match="story render failure"):
        gate.regenerate_clip(host.Job(claimed, "repair"))
    assert output.read_bytes() == b"previously completed video"
    assert all(path.read_bytes() == content for path, content in saved.items())
    assert db.get_clip(clip["id"])["render_info"]["artifact"]["blueprint"] == previous_plan.summary()
    future_plan = blueprint.plan_of(clip["id"])
    assert future_plan.sha256() != previous_plan.sha256() and future_plan.audio.silence == "off"
    assert not blueprint.errors(blueprint.validate(future_plan, 12, words))
    current_report = gate.report_for(db.get_clip(clip["id"]))
    assert current_report["id"] == report["id"] and current_report["status"] == "failed"
    assert current_report["bindings"]["blueprint"] == previous_plan.summary()


@pytest.mark.parametrize("legacy", [True, False])
def test_quality_rule_upgrade_queues_a_fresh_check_despite_completed_old_job(data, monkeypatch, legacy):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, queue
    from clipfoundry.pipeline import artifact, quality

    clip, _, output, _ = _clip(data)
    stamp = quality.file_stamp(output)
    previous_version = quality.GATE_VERSION - 1 if legacy else quality.GATE_VERSION
    key = f"quality:{clip['id']}:{stamp}:" if legacy else f"quality:v{previous_version}:{clip['id']}:{stamp}:"
    old = queue.enqueue("quality_check", {"clip_id": clip["id"]}, idem_key=key, ref=("clip", clip["id"]))
    claimed = queue.claim("quality_gate", "old-gate")
    assert queue.complete(claimed, "old-gate")
    db.insert("quality_reports", {"clip_id": clip["id"], "artifact_path": str(output), "file_stamp": stamp,
                                  "artifact_sha256": artifact.sha256_file(output),
                                  "gate_version": previous_version, "status": "passed"})
    monkeypatch.setattr(quality, "GATE_VERSION", previous_version + 1)
    assert gate.report_for(clip) is None
    assert gate.schedulable(clip, "youtube", "new-metadata") == (False, "waiting for the final quality check")
    fresh = gate.request(clip)
    assert fresh["id"] != old["id"] and fresh["status"] == "queued"
    assert gate.request(clip)["id"] == fresh["id"]
    assert f":v{quality.GATE_VERSION}:" in fresh["idem_key"]
