"""The Missions page: each mission shows its next upload (time in the Autopilot time zone, platform, account), the
office robots working on it now, and whether its uploads are paused."""
from __future__ import annotations

import io
import time

import pytest


@pytest.fixture
def mission(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, submissions

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_timezone": "Europe/Berlin"})
    host.WorkerHost(periodic=False)
    db.save_account("youtube", tokens={"access_token": "t"}, account_id="UC-missions")
    setup = submissions.setup()
    result = submissions.add_file(io.BytesIO(b"original"), "talk.mp4", {
        "auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
        "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
        "reuse_basis": "owned", "agreed": True})
    return db.fetch("sources", result["item"]["id"]), result["submission"]["id"]


def test_a_mission_shows_its_next_upload_in_the_autopilot_time_zone(mission):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    source, _ = mission
    assert submissions.item(source)["submission"]["next_post"] is None  # nothing planned yet
    soon, later = time.time() + 3600, time.time() + 7200
    for at, status in ((later, "approved"), (soon, "awaiting_approval"), (soon - 60, "published")):
        db.insert("scheduled_publications", {"clip_id": "c", "platform": "youtube", "title": f"Post {at:.0f}",
                                             "planned_at": at, "status": status, "source_id": source["id"]})
    nxt = submissions.item(source)["submission"]["next_post"]
    assert nxt["at"] == soon and nxt["needs_ok"] is True and nxt["platform"] == "youtube"
    assert nxt["timezone"] == "Europe/Berlin" and nxt["label"]  # shown as Berlin wall time with the zone named


def test_a_mission_names_the_robots_working_on_it_and_can_be_paused(mission):
    from clipfoundry.autopilot import queue, submissions

    source, sid = mission
    agents = submissions.item(source)["submission"]["agents"]
    assert agents and all(a["name"] and a["state"] for a in agents)  # its intake job is already queued
    queue.enqueue("regenerate_clip", {"x": 1}, ref=("source", source["id"]), message="Rendering clip 2 of 5")
    agents = submissions.item(source)["submission"]["agents"]
    assert any(a["doing"] == "Rendering clip 2 of 5" for a in agents)
    assert len({a["role"] for a in agents}) == len(agents)  # one line per robot
    assert submissions.item(source)["submission"]["paused"] is False
    submissions.set_paused(sid, True)
    assert submissions.item(source)["submission"]["paused"] is True
    with pytest.raises(LookupError):
        submissions.set_paused("missing", True)
