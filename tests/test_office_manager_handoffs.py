"""Real reports/checkpoints route through responsible managers; quiet rooms never manufacture work."""
from __future__ import annotations

import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True})
    return db


def _claim(kind: str, ref: tuple[str, str], payload: dict | None = None) -> dict:
    from clipfoundry.autopilot import queue

    row = queue.enqueue(kind, payload, ref=ref)
    job = queue.claim(queue.KIND_WORKER[kind], "test-office")
    assert job and job["id"] == row["id"]
    return job


def _events(type_: str) -> list[dict]:
    from clipfoundry import db

    return db.select("office_events", "type = ?", (type_,), "id ASC")


def _states(db) -> dict[str, dict]:
    from clipfoundry.office import view

    return {row["id"]: row for row in view.role_states(db.get_settings())}


def test_completed_work_goes_to_its_own_manager_then_the_boss(data):
    from clipfoundry.autopilot import queue

    job = _claim("rights_check", ("source", "source-one"))
    queue.complete(job, "test-office", {"message": "Recorded reuse agreement covers YouTube"})
    event = _events("report")[0]
    assert event["data"]["handoff_path"] == ["gavel", "vector", "command"]
    assert event["data"]["handoff_kind"] == "report"
    assert data.fetch("office_reports", event["data"]["report_id"])["worker"] == "gavel"
    states = _states(data)
    assert states["vector"]["state"] == states["command"]["state"] == "reviewing"
    assert states["command"]["last"]["summary"] == "Recorded reuse agreement covers YouTube"
    assert not data.select("office_decisions")  # receiving a report does not fabricate a boss approval


def test_manager_own_job_keeps_priority_over_an_older_report(data):
    from clipfoundry.autopilot import queue

    finished = _claim("schedule_tick", ("clip", "clip-one"))
    queue.complete(finished, "test-office", {"started": 1, "message": "Dispatched one eligible upload"})
    running = _claim("schedule_tick", ("clip", "clip-two"))
    queue.progress(running["id"], 0.5, "Finding a posting time")
    clock = _states(data)["clock"]
    assert clock["state"] == "working"
    assert clock["task"]["job_id"] == running["id"] and clock["task"]["progress"] == 0.5
    assert _events("report")[0]["data"]["handoff_path"] == ["clock", "command"]


def test_manager_failure_is_not_hidden_by_its_own_failure_report(data):
    from clipfoundry.autopilot import queue

    failed = _claim("schedule_tick", ("clip", "clip-one"))
    queue.fail(failed, "test-office", "Could not read the schedule", "Retry after checking the database")
    clock = _states(data)["clock"]
    assert clock["state"] == "error" and "Could not read the schedule" in clock["error"]


def test_unproductive_periodic_checks_do_not_create_report_handoffs(data):
    from clipfoundry.autopilot import queue

    periodic = _claim("schedule_tick", ("", ""))
    queue.complete(periodic, "test-office", {"message": "Nothing due", "started": 0})
    assert not _events("report")
    assert _states(data)["command"]["state"] == "idle"


def test_stage_change_respects_departments_and_real_checkpoint_dispatch(data):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    job = _claim("analyze_source", ("source", "source-one"))
    queue.progress(job["id"], 0.55, "Checking the story", stage="plan")
    plan = _events("job_stage")[-1]
    assert plan["data"]["handoff_path"] == ["boost", "vector", "frame", "story"]
    decision = feed.decide("clip", "approved", ("clip", "clip-one"), "Kept the complete moment",
                           job_id=job["id"], reported_by="frame", source_id="source-one")
    assert _events("decision")[-1]["data"]["handoff_path"] == ["frame", "command"]
    queue.progress(job["id"], 0.6, "Rendering the accepted moment", stage="render")
    render = _events("job_stage")[-1]
    assert render["data"]["handoff_path"] == ["command", "frame", "splice"]
    assert render["data"]["decision_id"] == decision["id"]
    queue.progress(job["id"], 0.8, "Laying out captions", stage="captions")
    assert _events("job_stage")[-1]["data"]["handoff_path"] == ["splice", "frame", "script", "glyph"]
    states = _states(data)
    assert states["glyph"]["state"] == states["script"]["state"] == "working"
    assert states["glyph"]["task"]["progress"] == 0.8 and states["script"]["task"] is None


def test_accepted_checkpoint_does_not_dispatch_work_until_a_real_transition(data):
    from clipfoundry.office import feed

    before = data.scalar("SELECT COUNT(*) FROM worker_jobs")
    feed.decide("upload", "approved", ("scheduled", "post-one"), "Actual audience check passed",
                reported_by="harbor")
    assert _events("decision")[-1]["data"]["handoff_path"] == ["harbor", "command"]
    assert data.scalar("SELECT COUNT(*) FROM worker_jobs") == before
    assert _states(data)["dock"]["state"] == "idle"  # recording the checkpoint alone starts no upload


@pytest.mark.parametrize("action", ["held", "rejected"])
def test_suggested_rework_recipient_does_not_imply_assigned_work(data, action):
    from clipfoundry.office import feed

    feed.decide("qc", action, ("clip", "clip-one"), "Cannot repair automatically", reported_by="check",
                next_role="glyph", repair_job_id="")
    assert _events("decision")[-1]["data"]["handoff_path"] == ["check", "switch", "command"]
    assert _states(data)["glyph"]["state"] == "idle"


def test_actual_repair_is_returned_through_the_recipients_manager(data):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    repair = queue.enqueue("regenerate_clip", {"handoff": {"to_role": "glyph"}}, ref=("clip", "clip-one"))
    feed.decide("qc", "rework", ("clip", "clip-one"), "Repair the caption timing", reported_by="check",
                next_role="glyph", repair_job_id=repair["id"])
    event = _events("decision")[-1]
    assert event["data"]["handoff_path"] == ["check", "switch", "command", "script", "glyph"]
    assert _states(data)["glyph"]["task"]["job_id"] == repair["id"]
    assert _states(data)["glyph"]["state"] == "waiting"


@pytest.mark.parametrize("wrong", ["reference", "canceled", "recipient"])
def test_repair_route_requires_the_assigned_matching_job(data, wrong):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    repair = queue.enqueue("regenerate_clip", {"handoff": {"to_role": "glyph"}},
                           ref=("clip", "another-clip" if wrong == "reference" else "clip-one"))
    if wrong == "canceled":
        queue.cancel(repair["id"])
    if wrong == "recipient":
        data.update("worker_jobs", repair["id"], payload={"handoff": {"to_role": "splice"}})
    feed.decide("qc", "rework", ("clip", "clip-one"), "Repair requested", reported_by="check",
                next_role="glyph", repair_job_id=repair["id"])
    assert _events("decision")[-1]["data"]["handoff_path"] == ["check", "switch", "command"]


def test_next_job_receives_a_fresh_matching_completed_report(data):
    from clipfoundry.autopilot import queue

    finished = _claim("package_clip", ("clip", "clip-one"))
    queue.complete(finished, "test-office", {"message": "Post text is saved"})
    _claim("quality_check", ("clip", "clip-one"))
    event = _events("job_started")[-1]
    assert event["data"]["handoff_path"] == ["command", "switch", "check"]
    assert event["data"]["report_id"] == _events("report")[-1]["data"]["report_id"]


@pytest.mark.parametrize("wrong", ["reference", "kind", "stale"])
def test_unrelated_or_old_history_never_creates_a_new_assignment_handoff(data, wrong):
    from clipfoundry.autopilot import queue

    finished = _claim("package_clip", ("clip", "clip-one"))
    queue.complete(finished, "test-office", {"message": "Post text is saved"})
    if wrong == "stale":
        data.execute("UPDATE office_reports SET created_at = ?", (time.time() - 31,))
    _claim("publish" if wrong == "kind" else "quality_check",
           ("clip", "clip-two" if wrong == "reference" else "clip-one"))
    assert _events("job_started")[-1]["data"]["handoff_path"] == []


def test_stale_stage_history_does_not_dispatch_a_live_document(data):
    from clipfoundry.autopilot import queue

    job = _claim("analyze_source", ("source", "source-one"))
    data.execute("UPDATE office_events SET at = ?", (time.time() - 31,))
    queue.progress(job["id"], 0.5, "Planning a moment", stage="plan")
    assert _events("job_stage")[-1]["data"]["handoff_path"] == []


def test_previous_file_approval_does_not_dispatch_a_new_file_check(data):
    from clipfoundry.office import feed

    feed.decide("qc", "approved", ("clip", "clip-one"), "An earlier file passed", reported_by="switch")
    _claim("quality_check", ("clip", "clip-one"))
    assert _events("job_started")[-1]["data"]["handoff_path"] == []


def test_newer_different_checkpoint_supersedes_an_old_clip_approval(data):
    from clipfoundry.office import feed

    feed.decide("clip", "approved", ("clip", "clip-one"), "An earlier moment was accepted", reported_by="frame")
    feed.decide("qc", "held", ("clip", "clip-one"), "Post text needs attention", reported_by="check")
    _claim("package_clip", ("clip", "clip-one"))
    assert _events("job_started")[-1]["data"]["handoff_path"] == []


def test_a_skipped_result_never_dispatches_the_next_job(data):
    from clipfoundry.autopilot import queue

    finished = _claim("hunt_source", ("source", "source-one"))
    queue.complete(finished, "test-office", {"message": "Source was not selected", "skipped": True})
    _claim("analyze_source", ("source", "source-one"))
    assert _events("job_started")[-1]["data"]["handoff_path"] == []


@pytest.mark.parametrize("action", ["held", "rejected", "rework"])
def test_newer_checkpoint_stop_supersedes_an_old_approval(data, action):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    job = _claim("analyze_source", ("source", "source-one"))
    feed.decide("clip", "approved", ("clip", "clip-one"), "Earlier plan accepted", job_id=job["id"],
                reported_by="frame")
    feed.decide("clip", action, ("clip", "clip-one"), "Later plan cannot proceed", job_id=job["id"],
                reported_by="story")
    queue.progress(job["id"], 0.6, "A real stage update", stage="render")
    event = _events("job_stage")[-1]
    assert "command" not in event["data"]["handoff_path"]
    assert "decision_id" not in event["data"]


def test_newer_skipped_report_supersedes_an_old_continue_report(data):
    from clipfoundry.autopilot import queue

    prior = _claim("hunt_source", ("source", "source-one"))
    queue.complete(prior, "test-office", {"message": "Earlier source read completed"})
    later = _claim("hunt_source", ("source", "source-one"))
    queue.complete(later, "test-office", {"message": "Source is now skipped", "skipped": True})
    _claim("analyze_source", ("source", "source-one"))
    assert _events("job_started")[-1]["data"]["handoff_path"] == []


def test_actual_brain_consultation_is_work_and_completion_is_review_without_fake_jobs(data):
    from clipfoundry.autopilot import brain, knowledge
    from clipfoundry.office import view

    knowledge.create({"title": "Readable captions", "content": "Use minimal captions", "kind": "instruction",
                      "preferences": {"caption_style": "minimal"}})
    before = data.scalar("SELECT COUNT(*) FROM worker_jobs")
    with brain.consultation("blueprint", data.get_settings(), ref=("clip", "clip-one")):
        rows = _states(data)
        assert rows["synapse"]["state"] == rows["curator"]["state"] == "working"
        assert rows["synapse"]["task"]["kind"] == "brain_consultation"
        assert rows["synapse"]["task"]["progress"] is None and rows["synapse"]["task"]["job_id"] == ""
        assert rows["curator"]["task"] is None and rows["command"]["state"] == "working"
    rows = _states(data)
    assert rows["synapse"]["state"] == "idle"
    assert rows["curator"]["state"] == rows["command"]["state"] == "reviewing"
    assert data.scalar("SELECT COUNT(*) FROM worker_jobs") == before
    assert not data.select("office_reports") and not data.select("office_decisions")
    assert {row["id"]: row for row in view.role_states(data.get_settings(), time.time() + 9)}["curator"]["state"] \
        == "idle"


def test_pending_result_learning_does_not_hide_real_guidance_work(data):
    from clipfoundry.autopilot import brain, knowledge, queue

    knowledge.create({"title": "Readable captions", "content": "Use minimal captions", "kind": "instruction"})
    queued = queue.enqueue("learn", delay=3600)
    assert _states(data)["synapse"]["state"] == "waiting"
    with brain.consultation("ranking", data.get_settings()):
        synapse = _states(data)["synapse"]
        assert synapse["state"] == "working" and synapse["task"]["kind"] == "brain_consultation"
        assert data.fetch("worker_jobs", queued["id"])["status"] == "queued"
    assert _states(data)["synapse"]["state"] == "waiting"


def test_quiet_rooms_have_explanations_and_pause_does_not_show_live_consultation(data):
    from clipfoundry.autopilot import brain, knowledge

    knowledge.create({"title": "Complete story", "content": "Prefer complete stories", "kind": "instruction"})
    rows = _states(data)
    assert "mature" in rows["synapse"]["idle_reason"]
    assert all(row["idle_reason"] for row in rows.values())
    with brain.consultation("ranking", data.get_settings()):
        data.save_settings({"autopilot_enabled": False})
        rows = _states(data)
        assert rows["synapse"]["state"] == rows["curator"]["state"] == "paused"
        assert rows["synapse"]["task"] is None


def test_running_work_is_visible_even_when_many_newer_pending_jobs_exist(data):
    from clipfoundry.autopilot import queue

    running = _claim("rights_check", ("source", "source-one"))
    template = {"worker": queue.KIND_WORKER["package_clip"], "kind": "package_clip", "status": "queued",
                "message": "Waiting in queue", "ref_type": "clip", "ref_id": "clip-later"}
    with data.connect() as conn:
        conn.executemany("INSERT INTO worker_jobs (id, worker, kind, status, message, ref_type, ref_id, created_at, "
                         "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(f"pending-{i}", template["worker"], template["kind"], template["status"],
                           template["message"], template["ref_type"], template["ref_id"], time.time() + i + 1,
                           time.time() + i + 1) for i in range(405)])
    gavel = _states(data)["gavel"]
    assert gavel["state"] == "working" and gavel["task"]["job_id"] == running["id"]
