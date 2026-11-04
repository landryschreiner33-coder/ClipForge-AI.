"""A finished automatic clip keeps moving when its source batch is interrupted."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, rights

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_tiktok": False})
    host.WorkerHost(periodic=False)
    rights.add_rule("folder", str(tmp_path), rights.OWNED, "My recordings")
    # Only the media fingerprint boundary is replaced; database handoffs and durable jobs are real.
    monkeypatch.setattr(hunter.fingerprint, "video_signature", lambda path, duration: [1, 2, 3])
    return tmp_path


def automatic_clip(data: Path, *, origin="autopilot", clip_id=None):
    from clipfoundry import db
    from clipfoundry.pipeline import artifact, blueprint

    video = data / f"source-{db.new_id()}.mp4"
    video.write_bytes(b"source fixture; media operations are replaced at the renderer boundary")
    source = db.insert("sources", {"platform": "local", "external_id": db.new_id(), "local_path": str(video),
                                    "status": "analyzing", "title": "My recording"})
    project = db.create_project("My recording", source_path=str(video), origin=origin, source_id=source["id"])
    db.update("sources", source["id"], project_id=project["id"])
    fields = {"id": clip_id} if clip_id else {}
    clip = db.create_clip(project["id"], start=0.0, end=30.0, duration=30.0, status="ready", score=90,
                          title="Keep the complete story", caption_text="Keep the complete story.", **fields)
    bp = blueprint.Blueprint(clip_id=clip["id"], project_id=project["id"], source_id=source["id"], input_hash="fixture",
                             intervals=[blueprint.Interval(0.0, 30.0)])
    assert blueprint.validate(bp, 30.0, []) == []
    blueprint.save(bp, [])
    output = data / f"{clip['id']}.mp4"
    output.write_bytes(b"completed renderer fixture")
    info = {"artifact": {"path": str(output), "sha256": artifact.sha256_file(output),
                         "blueprint": {"sha256": bp.sha256()}}}
    db.update_clip(clip["id"], output_path=str(output), render_info=info)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": 90}, key="clip_id")
    db.insert("clip_analysis", {"clip_id": clip["id"], "project_id": project["id"]}, key="clip_id")
    return db.get_clip(clip["id"]), source, project


def test_each_finished_recorded_clip_hands_off_before_priority_wait(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, queue

    first, source, project = automatic_clip(data)
    second = db.create_clip(project["id"], start=30, end=60, status="queued")
    db.update_clip(first["id"], status="queued", output_path="")
    queued = queue.enqueue("analyze_source", {"source_id": source["id"], "project_id": project["id"]},
                           priority=10, ref=("source", source["id"]))
    row = queue.claim("analyzer", "first-claim")
    job = host.Job(row, "first-claim")
    p = SimpleNamespace(id=project["id"], project=project, pdir=data, words=[], settings=db.get_settings(),
                        stage=lambda stage, fraction, message: db.update_project(project["id"], stage=stage,
                                                                                 progress=fraction, message=message))
    renders = []

    def finished_render(project_row, clip, words, settings, ctx, **kwargs):
        renders.append(clip["id"])
        assert kwargs["blueprint"].clip_id == clip["id"]
        if len(renders) == 1:
            higher = db.insert("sources", {"platform": "local", "external_id": "newer", "user_added": 1})
            queue.enqueue("hunt_source", {"source_id": higher["id"]}, priority=80)
        output = data / f"{clip['id']}.mp4"
        output.write_bytes(b"finished exact clip")
        return {"output_path": str(output), "render_info": first["render_info"]}

    monkeypatch.setattr(hunter.process.render, "render_clip", finished_render)
    with pytest.raises(queue.Wait, match="higher-priority"):
        hunter.render_in_priority_order(p, [first, second], job.pipeline_ctx(), job, source, handoff=True)
    assert renders == [first["id"]]
    assert db.get_clip(first["id"])["status"] == "ready"
    assert db.get_clip(second["id"])["status"] == "queued"
    packaged = queue.jobs(worker="packager")
    assert len(packaged) == 1 and packaged[0]["payload"]["clip_id"] == first["id"]
    assert packaged[0]["idem_key"] == f"package:{first['id']}" and packaged[0]["priority"] == 10
    assert db.fetch("clip_fingerprints", first["id"], "clip_id")["source_key"].startswith("local:")
    assert not db.select("scheduled_publications")  # downstream checks still decide whether it may be posted
    hunter.ready_clip_handoff(db.get_clip(first["id"]), source)
    assert len(queue.jobs(worker="packager")) == 1 and queue.get(queued["id"])["status"] == "running"


@pytest.mark.parametrize("source_status", ["analyzing", "failed", "weak", "analyzed"])
def test_old_plan_bound_ready_output_resumes_once_even_after_source_failure(data, source_status):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue

    clip, source, _ = automatic_clip(data)
    db.update("sources", source["id"], status=source_status)
    before = Path(clip["output_path"]).read_bytes()
    assert hunter.recover_ready_clips() == 1
    assert hunter.recover_ready_clips() == 0
    assert hunter.recover_ready_clips() == 0
    job = queue.jobs(worker="packager")[0]
    assert job["payload"] == {"clip_id": clip["id"], "source_id": source["id"]}
    assert Path(clip["output_path"]).read_bytes() == before
    assert db.get_clip(clip["id"])["status"] == "ready"
    assert not db.select("quality_reports") and not db.select("scheduled_publications")


@pytest.mark.parametrize("hold", ["manual", "edit", "version", "manual_pending", "canceled_source", "removed_source",
                                  "canceled_stage", "cancel_requested", "blocked_rights", "failed_output",
                                  "missing_file",
                                  "invalid_plan", "missing_analysis", "missing_score", "changed_plan"])
def test_recovery_leaves_intentional_or_unproven_outputs_alone(data, hold):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue, rights

    clip, source, project = automatic_clip(data, origin="manual" if hold == "manual" else "autopilot")
    if hold == "edit":
        db.update_clip(clip["id"], edit={"caption_style": "bold"})
    elif hold == "version":
        db.update_clip(clip["id"], active_version="the-owner-version")
    elif hold == "manual_pending":
        db.update_clip(clip["id"], render_info={**clip["render_info"], "manual_render_pending": True})
    elif hold in ("canceled_source", "removed_source"):
        db.update("sources", source["id"], intake={"canceled": True, "removed": hold == "removed_source"})
    elif hold in ("canceled_stage", "cancel_requested"):
        job = queue.enqueue("analyze_source", {"source_id": source["id"], "project_id": project["id"]})
        if hold == "cancel_requested":
            queue.claim("analyzer", "cancel-requested")
        queue.cancel(job["id"])
    elif hold == "blocked_rights":
        rights.confirm(source["id"], rights.BLOCKED, "Do not use this recording")
    elif hold == "failed_output":
        db.update_clip(clip["id"], status="error", error="Incomplete render")
    elif hold == "missing_file":
        Path(clip["output_path"]).unlink()
    elif hold == "invalid_plan":
        db.execute("UPDATE clip_blueprints SET status = 'invalid' WHERE clip_id = ?", (clip["id"],))
    elif hold == "missing_analysis":
        db.execute("DELETE FROM clip_analysis WHERE clip_id = ?", (clip["id"],))
    elif hold == "missing_score":
        db.execute("DELETE FROM clip_scores WHERE clip_id = ?", (clip["id"],))
    elif hold == "changed_plan":
        db.update_clip(clip["id"], render_info={"artifact": {"blueprint": {"sha256": "not-this-render"}}})
    assert hunter.recover_ready_clips() == 0
    assert not queue.jobs(worker="packager") and not db.select("clip_fingerprints")


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "retrying", "completed", "failed", "canceled"])
def test_existing_packaging_jobs_are_never_duplicated_or_revived(data, status):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue

    clip, source, _ = automatic_clip(data)
    queued = queue.enqueue("package_clip", {"clip_id": clip["id"]}, idem_key=f"package:{clip['id']}",
                           ref=("clip", clip["id"]))
    db.update("worker_jobs", queued["id"], status=status, attempts=2, run_after=time.time() + 3600)
    before = queue.get(queued["id"])
    assert hunter.recover_ready_clips() == 0
    assert hunter.ready_clip_handoff(clip, source)["id"] == queued["id"]
    assert queue.get(queued["id"]) == before and len(queue.jobs(worker="packager")) == 1


def test_bounded_recovery_does_not_let_unreadable_earlier_files_starve_other_outputs(data):
    from clipfoundry.autopilot import hunter, queue

    bad, _, _ = automatic_clip(data, clip_id="a" * 32)
    good, _, _ = automatic_clip(data, clip_id="b" * 32)
    Path(bad["output_path"]).unlink()
    assert hunter.recover_ready_clips(limit=1) == 0
    assert hunter.recover_ready_clips(limit=1) == 1
    assert queue.jobs(worker="packager")[0]["payload"]["clip_id"] == good["id"]


def test_post_live_replacements_are_not_handed_off_before_their_decision(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, queue

    clip, source, project = automatic_clip(data, origin="live")
    hunter.store_fingerprint(clip, source)
    post = queue.enqueue("post_live", {"source_id": source["id"], "project_id": project["id"]})
    job = host.Job(post, "post-live")
    hunter.render_in_priority_order(SimpleNamespace(id=project["id"]), [clip], job.pipeline_ctx(), job, source)
    assert not queue.jobs(worker="packager")  # shared renderer's default preserves the replacement decision
    assert hunter.recover_ready_clips() == 0
    db.update("worker_jobs", post["id"], status="completed")
    assert hunter.recover_ready_clips() == 0  # previous scan wraps before revisiting this output
    assert hunter.recover_ready_clips() == 1
    assert len(queue.jobs(worker="packager")) == 1


def test_cancel_during_fingerprinting_prevents_the_late_packaging_handoff(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue

    clip, source, project = automatic_clip(data)
    queued = queue.enqueue("analyze_source", {"source_id": source["id"], "project_id": project["id"]})
    queue.claim("analyzer", "cancel-during-fingerprint")

    def cancel(path, duration):
        queue.cancel(queued["id"])
        return [1, 2, 3]

    monkeypatch.setattr(hunter.fingerprint, "video_signature", cancel)
    assert hunter.ready_clip_handoff(clip, source) is None
    assert not queue.jobs(worker="packager") and db.get_clip(clip["id"])["status"] == "ready"


def test_one_unreadable_output_does_not_block_other_verified_handoffs(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue

    bad, _, _ = automatic_clip(data, clip_id="a" * 32)
    good, _, _ = automatic_clip(data, clip_id="b" * 32)

    def inspect(path, duration):
        if path == bad["output_path"]:
            raise OSError("Temporary read error on this one completed output")
        return [1, 2, 3]

    monkeypatch.setattr(hunter.fingerprint, "video_signature", inspect)
    assert hunter.recover_ready_clips() == 1
    assert queue.jobs(worker="packager")[0]["payload"]["clip_id"] == good["id"]
    assert db.select("autopilot_events", "kind = 'clip_handoff_waiting'")[0]["ref_id"] == bad["id"]


def test_pause_and_cooperative_cancel_do_not_create_new_handoffs(data):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue, state

    automatic_clip(data)
    state.put("emergency_stop", True)
    assert hunter.recover_ready_clips() == 0
    state.put("emergency_stop", False)
    with pytest.raises(queue.Canceled):
        hunter.recover_ready_clips(cancelled=lambda: True)


@pytest.mark.parametrize('stop', ['parent_cancel', 'pause'])
def test_stop_during_recovery_fingerprinting_cannot_queue_late_work(data, monkeypatch, stop):
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue

    clip, source, project = automatic_clip(data)
    canceled = [False]

    def interrupt(path, duration):
        if stop == 'pause':
            db.save_settings({'autopilot_enabled': False})
        else:
            canceled[0] = True
        return ['synthetic-frame']

    monkeypatch.setattr(hunter.fingerprint, 'video_signature', interrupt)
    with pytest.raises(queue.Canceled):
        hunter.recover_ready_clips(cancelled=lambda: canceled[0])
    assert not queue.jobs(worker='packager')
    db.save_settings({"autopilot_enabled": False})
    assert hunter.recover_ready_clips() == 0 and not queue.jobs(worker="packager")
