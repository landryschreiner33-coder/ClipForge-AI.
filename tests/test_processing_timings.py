"""Bottleneck evidence must exclude idle waits, orphaned history and incomplete work."""
import pytest

from clipfoundry import db
from clipfoundry.office.performance import summary


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()


def event(at, typ, job="a", stage="", kind="hunt_source"):
    with db.connect() as conn:
        conn.execute("INSERT INTO office_events (at,type,job_id,kind,data) VALUES (?,?,?,?,?)",
                     (at, typ, job, kind, '{"stage": "' + stage + '"}'))


def test_active_time_excludes_restart_wait_and_unfinished_orphan_history():
    event(100, "job_started")
    event(105, "job_stage", stage="transcribe")
    event(125, "job_waiting")
    event(900, "job_started")
    event(905, "job_stage", stage="transcribe")
    event(915, "job_done")
    event(920, "job_stage", "missing", "render")
    event(930, "job_done", "missing")
    event(950, "job_started", "unfinished")
    report = summary(now=1000)
    transcribe = next(s for s in report["stages"] if s["stage"] == "transcribe")
    assert transcribe["total_s"] == 30
    assert transcribe["samples"] == 2
    assert report["measured_active_s"] == 40
    assert report["active_jobs"] == 1
    assert not any(s["stage"] == "render" for s in report["stages"])


def test_no_data_does_not_claim_a_bottleneck():
    assert summary(now=1000)["stages"] == []
    assert summary(now=1000)["measured_active_s"] == 0
