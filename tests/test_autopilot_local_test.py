"""Broad recorded discovery may make local test clips without becoming a reuse or upload grant."""
from __future__ import annotations

import ipaddress
from pathlib import Path

import pytest

from clipfoundry import db, netguard
from clipfoundry.autopilot import access, home, host, hunter, queue, rights, scout
from clipfoundry.pipeline.common import JobContext
from fake_platforms import FakeGoogle


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    return tmp_path


def source(**fields):
    return db.insert("sources", {"platform": "youtube", "external_id": db.new_id(), "title": "A useful interview",
                                 "signal_id": "discovered-signal", "kind": "recorded", "status": "discovered",
                                 "url": "https://www.youtube.com/watch?v=video000001", **fields})


def run(kind, payload=None):
    host.WorkerHost(periodic=False)
    row = queue.enqueue(kind, payload or {})
    return host.HANDLERS[kind](host.Job(row, "test"))


def test_local_mode_changes_processing_and_access_without_granting_reuse(data):
    src = source()
    normal = db.get_settings()
    test = {**normal, "autopilot_local_test_mode": True}
    assert not normal["autopilot_local_test_mode"] and not normal["rights_allow_remote_download"]
    assert not rights.local_allowed(src, settings=normal)
    assert not access.resolve(src, normal)["ok"]
    evaluation = rights.evaluate(src, test)
    assert evaluation["status"] == rights.MANUAL and not evaluation["auto_allowed"]
    assert rights.local_allowed(src, evaluation, test)
    found = access.resolve(src, test)
    assert found["ok"] and found["method"] == "platform" and "local testing" in found["label"]
    updated = rights.apply(src, test)
    assert updated["status"] == "eligible" and updated["rights_status"] == rights.MANUAL
    assert not updated["user_added"] and not db.select("source_rights")
    for stage in ("schedule", "publish"):
        with pytest.raises(rights.RightsBlocked):
            rights.gate(updated, stage, test)
    assert not rights.local_allowed(updated, settings=normal)


def test_local_mode_keeps_blocks_cancellation_removal_and_live_policy(data):
    settings = {**db.get_settings(), "autopilot_local_test_mode": True}
    src = source()
    for fields in ({"intake": {"canceled": True}}, {"intake": {"removed": True}},
                   {"status": "canceled"}, {"status": "removed"}, {"kind": "live"}, {"signal_id": ""}):
        assert not rights.local_allowed({**src, **fields}, settings=settings)
        assert not access.resolve({**src, **fields}, settings)["ok"]
    rights.add_rule("source", src["id"], rights.BLOCKED, "Skip this video")
    assert not rights.local_allowed(src, settings=settings)
    assert rights.apply(src, settings)["status"] == "blocked"
    assert not access.resolve(src, settings)["ok"]


def test_local_discoveries_still_require_public_urls(data):
    settings = {**db.get_settings(), "autopilot_local_test_mode": True}
    src = source(url="http://127.0.0.1/private.mp4")
    assert rights.local_allowed(src, settings=settings)
    assert not rights.url_typed_by_user(src)
    with pytest.raises(netguard.UnsafeUrl):
        netguard.check(src["url"], allow_private=rights.url_typed_by_user(src))


def test_platform_discovery_resolving_to_private_address_fails_without_retry(data, monkeypatch):
    db.save_settings({"autopilot_local_test_mode": True})
    src = source(status="queued")
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("127.0.0.1")])
    with pytest.raises(queue.Fail, match="Public video access refused"):
        run("hunt_source", {"source_id": src["id"]})
    failed = db.fetch("sources", src["id"])
    assert failed["status"] == "failed"
    assert not Path(db.get_project(failed["project_id"])["source_path"]).exists()


def test_trending_unknown_sources_are_ranked_and_queued_with_normal_limits(data, monkeypatch):
    from clipfoundry.publish import youtube

    google = FakeGoogle()
    monkeypatch.setattr(youtube, "API_URL", google.url + "/youtube/v3")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    db.save_settings({"youtube_api_key": google.api_key, "trend_topics": "podcast", "library_discovery": False,
                      "autopilot_local_test_mode": True, "autopilot_sources_per_day": 1,
                      "autopilot_live_monitoring": False})
    try:
        for vid, views in (("trend000001", 900_000), ("trend000002", 700_000)):
            google.add_video(vid, "A podcast interview with practical advice", views=views, duration="PT1H")
        google.add_video("short000001", "A podcast clip", views=2_000_000, duration="PT40S")
        google.add_video("block000001", "A podcast to skip", views=3_000_000, duration="PT1H")
        rights.add_rule("source", "youtube:block000001", rights.BLOCKED, "Skip this video")
        google.popular = ["block000001", "short000001", "trend000001", "trend000002"]
        assert run("trend_scan")["signals"] >= 4
        result = run("source_scout")
        assert len(result["picked"]) == 1
        picked = db.fetch("sources", result["picked"][0])
        assert picked["external_id"] == "trend000001" and picked["expected_clips"] >= 1
        assert picked["rights_status"] == rights.MANUAL and not picked["user_added"]
        hunts = queue.jobs(ref=("source", picked["id"]))
        assert len(hunts) == 1 and hunts[0]["kind"] == "hunt_source" and hunts[0]["priority"] == 0
        assert not scout.select_for_today(db.get_settings())
        assert db.select("sources", "external_id = 'short000001'")[0]["status"] == "skipped"
        assert db.select("sources", "external_id = 'block000001'")[0]["status"] == "blocked"
        assert not db.get_settings()["rights_allow_remote_download"]
    finally:
        google.stop()


def test_toggle_rechecks_waiting_work_without_starting_or_bypassing_autopilot(data):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    client = TestClient(app, base_url="http://127.0.0.1:8765")
    assert client.put("/api/settings", json={"autopilot_local_test_mode": True}).status_code == 200
    jobs = queue.jobs()
    assert len(jobs) == 1 and jobs[0]["kind"] == "rights_check" and jobs[0]["priority"] == 0
    assert not db.get_settings()["autopilot_enabled"]
    client.put("/api/settings", json={"autopilot_local_test_mode": True})
    assert len(queue.jobs()) == 1
    assert client.get("/api/autopilot/status").json()["settings"]["autopilot_local_test_mode"]
    response = client.post("/api/autopilot/scheduled/any/publish-now", headers={"X-ClipFoundry": "1"})
    assert response.status_code == 409 and "Local test mode" in response.text


def test_disabling_local_mode_rechecks_before_hunt(data):
    db.save_settings({"autopilot_local_test_mode": True})
    src = source(status="queued")
    assert rights.local_allowed(src)
    db.save_settings({"autopilot_local_test_mode": False})
    result = run("hunt_source", {"source_id": src["id"]})
    assert result["skipped"] and db.fetch("sources", src["id"])["status"] == "needs_rights"
    assert not db.select("projects")


def test_disabling_local_mode_stops_processing_at_the_next_checkpoint(data):
    db.save_settings({"autopilot_local_test_mode": True})
    src = source(status="ingesting")
    job = host.Job(queue.enqueue("hunt_source", {"source_id": src["id"]}), "test")
    ctx = hunter.source_context(job, src, db.get_settings())
    ctx.check()
    db.save_settings({"autopilot_local_test_mode": False})
    with pytest.raises(queue.Wait, match="Local clipping is paused"):
        ctx.check()


def test_switching_off_holds_test_work_and_switching_back_on_keeps_the_job(data):
    db.save_settings({"autopilot_local_test_mode": True})
    src = source(status="eligible", expected_clips=2, source_score=80)
    assert scout.select_for_today(db.get_settings())
    job = queue.jobs(ref=("source", src["id"]))[0]
    assert job["payload"]["local_test_mode"]
    db.save_settings({"autopilot_local_test_mode": False})
    scout.reapply([db.fetch("sources", src["id"])], db.get_settings())
    assert queue.get(job["id"])["status"] == "queued"
    with pytest.raises(queue.Wait, match="test video is held"):
        host.HANDLERS["hunt_source"](host.Job(job, "test"))
    db.save_settings({"autopilot_local_test_mode": True})
    scout.reapply([db.fetch("sources", src["id"])], db.get_settings())
    assert scout.select_for_today(db.get_settings())
    assert len(queue.jobs(ref=("source", src["id"]))) == 1
    assert queue.get(job["id"])["status"] == "queued"


def test_local_test_project_marker_survives_resumption_with_mode_off(data):
    original = data / "original.mp4"
    original.write_bytes(b"local original")
    src = source(local_path=str(original))
    settings = {**db.get_settings(), "autopilot_local_test_mode": True}
    project = hunter.ensure_project(src, settings, JobContext())
    assert project["options"]["local_test_mode"]
    src = db.fetch("sources", src["id"])
    resumed = hunter.ensure_project(src, db.get_settings(), JobContext())
    assert resumed["id"] == project["id"] and resumed["options"]["local_test_mode"]
    assert len(db.list_projects()) == 1


def test_start_can_clear_preferred_topics_for_broad_local_discovery(data):
    home.start({}, "")
    assert db.get_settings()["trend_topics"]
    db.save_settings({"autopilot_local_test_mode": True})
    home.start({}, "")
    assert db.get_settings()["trend_topics"] == ""
