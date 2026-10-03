"""Explicit manual requests remain recoverable without stealing automatic work on restart."""
from __future__ import annotations

import shutil

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    return tmp_path


@pytest.mark.parametrize("origin", ["autopilot", "live"])
def test_manual_reprocessing_of_an_automatic_project_survives_restart(data, monkeypatch, origin):
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    project = db.create_project("Make clips again", origin=origin, status="ready", info={"word_count": 20})
    untouched = db.create_project("Automatic work", origin=origin, status="processing")
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_project(project["id"])
    pending = db.interrupted_work()
    assert [p["id"] for p in pending["projects"]] == [project["id"]]
    assert untouched["id"] not in [p["id"] for p in pending["projects"]]
    ordinary = queue.enqueue("analyze_source", {"project_id": untouched["id"]}, priority=10)
    assert queue.has_higher_priority_work(ordinary, 10)
    assert db.get_project(project["id"])["info"]["word_count"] == 20

    restarted = jobs.Worker()
    monkeypatch.setattr(restarted, "start", lambda: None)
    assert restarted.resume(pending)["projects"] == 1
    assert restarted.q.get_nowait() == ("project", project["id"], None)
    monkeypatch.setattr(jobs.process, "run_project", lambda *args: None)
    restarted._run_project(project["id"], None)
    assert not db.get_project(project["id"])["info"].get("manual_process_pending")
    assert not queue.has_higher_priority_work(ordinary, 10)


def test_canceling_a_queued_manual_render_releases_saved_backup_recovery(data, monkeypatch):
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import gate, host, queue

    host.WorkerHost(periodic=False)
    source_file = data / "source.mp4"
    source_file.write_bytes(b"original source")
    source = db.insert("sources", {"platform": "local", "external_id": "original", "status": "analyzed"})
    project = db.create_project("Video", source_path=str(source_file), origin="autopilot", source_id=source["id"])
    output = data / "clip.mp4"
    output.write_bytes(b"previous completed clip")
    clip = db.create_clip(project["id"], status="ready", start=0, end=30, output_path=str(output))
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    claimed = queue.claim("analyzer", "interrupted-repair")
    backup = output.with_name(f"{output.name}.regeneration-{repair['id']}.bak")
    shutil.copy2(output, backup)
    queue.fail(claimed, "interrupted-repair", "Restore interrupted")
    output.unlink()

    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_render(clip["id"])
    assert gate.recover_regenerations() == 0  # the explicit request owns the output until canceled
    assert worker.cancel_all() == 1
    assert not db.get_clip(clip["id"])["render_info"].get("manual_render_pending")
    assert gate.recover_regenerations() == 1
    assert output.read_bytes() == b"previous completed clip" and not backup.exists()


@pytest.mark.parametrize("ending", ["queued_cancel", "running_cancel", "failure", "resume_limit"])
def test_manual_project_terminal_states_release_automatic_work(data, monkeypatch, ending):
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    project = db.create_project("Manual retry", origin="live", status="ready", info={"word_count": 20})
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_project(project["id"])
    ordinary = queue.enqueue("hunt_source", priority=10)
    assert queue.has_higher_priority_work(ordinary, 10)
    if ending == "queued_cancel":
        assert worker.cancel_all() == 1
    elif ending == "resume_limit":
        info = db.get_project(project["id"])["info"]
        db.update_project(project["id"], info={**info, "resume_count": 2})
        assert worker.resume(db.interrupted_work())["not_resumed"] == 1
    else:
        def stop_processing(*args):
            if ending == "running_cancel":
                raise jobs.Cancelled()
            raise OSError("Source unavailable")

        monkeypatch.setattr(jobs.process, "run_project", stop_processing)
        worker._run_project(project["id"], None)
    saved = db.get_project(project["id"])
    assert saved["status"] == ("cancelled" if "cancel" in ending else "error")
    assert saved["info"]["word_count"] == 20
    assert not saved["info"].get("manual_process_pending")
    assert not db.interrupted_work()["projects"]
    assert not queue.has_higher_priority_work(ordinary, 10)


@pytest.mark.parametrize("ending", ["ready", "cancelled", "error"])
def test_finishing_a_manual_project_does_not_clear_a_new_request(data, monkeypatch, ending):
    from clipfoundry import db, jobs

    project = db.create_project("Make clips again", origin="autopilot", status="ready")
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_project(project["id"])
    worker.q.get_nowait()
    update = db.update_project

    def submit_after_completion(project_id, **fields):
        result = update(project_id, **fields)
        if fields.get("status") == ending:
            worker.submit_project(project_id)  # the next API request arrives as soon as processing finishes
        return result

    def processing(*args):
        if ending == "cancelled":
            raise jobs.Cancelled()
        if ending == "error":
            raise OSError("Source unavailable")

    monkeypatch.setattr(db, "update_project", submit_after_completion)
    monkeypatch.setattr(jobs.process, "run_project", processing)
    worker._run_project(project["id"], None)
    pending = db.interrupted_work()
    assert db.get_project(project["id"])["status"] == "queued"
    assert [row["id"] for row in pending["projects"]] == [project["id"]]
    restarted = jobs.Worker()
    monkeypatch.setattr(restarted, "start", lambda: None)
    assert restarted.resume(pending)["projects"] == 1
