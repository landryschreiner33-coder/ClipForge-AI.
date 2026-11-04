"""Durable studio jobs (CF-02 worker side): idempotent keys, one lease holder, no double completion, recovery."""
from __future__ import annotations

import time


def test_leases_allow_exactly_one_completion_and_recover_after_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.studio import jobs

    db.init()
    job = jobs.enqueue("local", "video_render", "vid-1", 3, submit=False)
    assert jobs.enqueue("local", "video_render", "vid-1", 3, submit=False)["id"] == job["id"]  # same work, same job
    first = jobs.claim(job["id"])
    assert first is not None and jobs.claim(job["id"]) is None  # a second worker cannot take a live lease
    # the first worker stalls past its lease; another worker takes the job over
    db.update("studio_jobs", job["id"], lease_until=time.time() - 1)
    second = jobs.claim(job["id"])
    assert second is not None and second.token != first.token
    assert not jobs.finish(first, {"artifact": "late"})  # the stale worker cannot commit a result
    assert jobs.finish(second, {"artifact": "real"})
    assert not jobs.finish(second, {"artifact": "again"})  # and nothing completes twice
    done = db.fetch("studio_jobs", job["id"])
    assert done["status"] == "done" and done["result"] == {"artifact": "real"}
    assert jobs.enqueue("local", "video_render", "vid-1", 3, submit=False)["status"] == "done"  # not re-run

    crashed = jobs.enqueue("local", "video_preview", "vid-1", 4, submit=False)
    jobs.claim(crashed["id"])  # the process died while running it
    submitted = []
    from clipfoundry import jobs as app_jobs

    monkeypatch.setattr(app_jobs.worker, "submit_studio", lambda job_id: submitted.append(job_id))
    assert jobs.recover() == 1 and submitted == [crashed["id"]]


def test_cancel_stops_progress_and_is_not_undone_by_recovery(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.studio import jobs

    db.init()
    job = jobs.enqueue("local", "video_render", "vid-2", 1, submit=False)
    lease = jobs.claim(job["id"])
    lease.progress(0.2, "Rendering")
    assert jobs.cancel(job["id"])
    assert lease.canceled()
    try:
        lease._last = 0  # noqa: SLF001
        lease.progress(0.5, "Rendering")
        raise AssertionError("progress after cancel must stop the job")
    except jobs.Canceled:
        pass
    assert jobs.recover() == 0 and db.fetch("studio_jobs", job["id"])["status"] == "canceled"
