"""The office: a fixed cast of 25 robots, an event feed made only of real job transitions, the managers' automatic
reports, the Director's recorded checkpoint decisions, health readings and the bottom-bar controls."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


@pytest.fixture()
def client(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def test_the_cast_is_one_director_eight_managers_and_sixteen_workers():
    from clipfoundry.autopilot import queue
    from clipfoundry.office import roles

    assert roles.validate() == []
    ranks = [r["rank"] for r in roles.ROLES]
    assert (ranks.count("director"), ranks.count("manager"), ranks.count("worker")) == (1, 8, 16)
    assert len({r["id"] for r in roles.ROLES}) == len({r["name"] for r in roles.ROLES}) == 25
    assert "core" not in roles.BY_ID  # CORE is the Brain room's object, not a 26th robot
    # the Schedule department is CLOCK alone: no worker was invented to fill a chair
    assert not [r for r in roles.ROLES if r["department"] == "schedule" and r["rank"] == "worker"]
    # every kind of real work has a robot that is not the catch-all, so the office never shows work nobody does
    for _label, kinds in queue.WORKERS.values():
        for kind in kinds:
            rid = roles.role_for(kind)
            assert rid in roles.BY_ID
            if kind not in ("maintenance", "selftest"):
                assert rid != "patch", kind


def test_the_drawn_cast_matches_the_registry():
    """frontend/src/office/cast.ts draws the robots: the same 25 ids, names, ranks, rooms and managers as roles.py,
    so the office never draws a robot the job system does not know (or the other way round)."""
    import re
    from pathlib import Path

    from clipfoundry.office import roles

    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "office" / "cast.ts").read_text("utf-8")
    drawn = {m["id"]: m for m in (re.search(
        r'id: "(?P<id>[a-z]+)", name: "(?P<name>[A-Z]+)", title: "(?P<title>[^"]+)", rank: "(?P<rank>[a-z]+)", '
        r'dept: "(?P<dept>[a-z]+)", room: "(?P<room>[a-z]+)",\s*manager: "(?P<manager>[a-z]*)"', line)
        for line in re.split(r"\n  \{ ", src)) if m}
    assert set(drawn) == set(roles.BY_ID), "cast.ts and roles.py list different robots"
    for rid, role in roles.BY_ID.items():
        d = drawn[rid]
        assert (d["name"], d["title"], d["rank"], d["dept"], d["room"], d["manager"]) == (
            role["name"], role["title"], role["rank"], role["department"], role["room"], role["manager"]), rid


def test_stages_move_work_between_robots():
    from clipfoundry.office import roles

    assert roles.role_for("analyze_source", "plan") == "story"
    assert roles.role_for("analyze_source", "captions") == "glyph"
    assert roles.role_for("analyze_source", "render") == "splice"
    assert roles.role_for("publish", "audience") == "lock" and roles.role_for("publish", "upload") == "dock"
    assert roles.role_for("schedule_tick") == "clock"


def test_job_transitions_become_events_and_a_manager_report(data):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    start = feed.cursor()
    job = queue.enqueue("rights_check", ref=("source", "s1"))
    j = queue.claim(queue.KIND_WORKER["rights_check"], "w")
    assert j and j["id"] == job["id"]
    queue.progress(j["id"], 0.4, "Reading the license", stage="rights")
    queue.complete(j, "w", {"message": "Licensed for reuse", "warnings": ["Attribution needed"]})
    events = feed.events_after(start)["events"]
    types = [e["type"] for e in events]
    assert types[:3] == ["job_started", "job_stage", "job_done"] and "report" in types
    assert {e["role"] for e in events if e["type"].startswith("job_")} == {"gavel"}
    rep = [e for e in events if e["type"] == "report"][0]
    assert rep["role"] == "vector" and rep["data"]["recommendation"] == "continue"
    row = feed.db.select("office_reports", "job_id = ?", (job["id"],))[0]
    assert row["warnings"] == ["Attribution needed"] and row["worker"] == "gavel"


def test_routine_runs_that_did_nothing_are_not_reported(data):
    from clipfoundry.autopilot import queue
    from clipfoundry.office import feed

    queue.enqueue("schedule_tick")
    j = queue.claim(queue.KIND_WORKER["schedule_tick"], "w")
    queue.complete(j, "w", {"message": "Nothing due", "started": 0})
    assert not feed.db.select("office_reports")
    queue.enqueue("selftest", {"permanent": True})
    j = queue.claim("maintenance", "w")
    queue.fail(j, "w", "Self-test permanent failure", "Nothing to do")
    assert [r["state"] for r in feed.db.select("office_reports")] == ["failed"]  # a failure is always reported


def test_the_feed_resumes_from_a_cursor_and_says_when_to_reload(data):
    from clipfoundry.office import feed

    first = feed.emit("test", "radar", message="one")
    feed.emit("test", "radar", message="two")
    feed.emit("test", "radar", message="three")
    page = feed.events_after(first, limit=1)
    assert [e["message"] for e in page["events"]] == ["two"] and page["more"]
    rest = feed.events_after(page["cursor"])
    assert [e["message"] for e in rest["events"]] == ["three"] and not rest["more"]
    assert feed.events_after(rest["cursor"])["events"] == []  # nothing is delivered twice
    assert feed.events_after(10_000)["reset"]  # a cursor from another database: reload the snapshot


def test_a_decision_is_recorded_once_per_subject(data):
    from clipfoundry.office import feed

    a = feed.decide("upload", "approved", ("scheduled", "p1"), "Eligible", once=True)
    b = feed.decide("upload", "approved", ("scheduled", "p1"), "Eligible", once=True)
    assert a["id"] == b["id"] and len(feed.decisions_for("scheduled", "p1")) == 1
    feed.decide("upload", "held", ("scheduled", "p1"), "Who watches changed", once=True)
    assert [d["action"] for d in feed.decisions_for("scheduled", "p1")] == ["held", "approved"]
    assert feed.decisions_for("scheduled", "p1")[0]["rule_version"] == feed.RULES
    with pytest.raises(AssertionError):
        feed.decide("upload", "maybe", ("scheduled", "p1"), "not a decision")


def test_robot_states_come_only_from_the_jobs(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state
    from clipfoundry.office import view

    db.save_settings({"autopilot_enabled": True})
    by_id = lambda: {r["id"]: r for r in view.role_states(db.get_settings())}  # noqa: E731
    assert by_id()["gavel"]["state"] == "idle" and by_id()["gavel"]["task"] is None
    job = queue.enqueue("rights_check", ref=("source", "s1"))
    j = queue.claim(queue.KIND_WORKER["rights_check"], "w")
    task = by_id()["gavel"]["task"]
    assert task["message"] == "Started" and task["progress"] is None  # running, not "Waiting in queue"; unmeasured
    queue.progress(j["id"], 0.5, "Reading the license", stage="rights")
    now = by_id()
    assert now["gavel"]["state"] == "working" and now["gavel"]["task"]["job_id"] == job["id"]
    assert now["gavel"]["task"]["progress"] == 0.5  # measured, so shown
    assert now["vector"]["state"] == "working"  # its manager watches the department's running work
    assert now["command"]["state"] == "working"
    queue.fail(j, "w", "The license page could not be read", "Try again later")
    now = by_id()
    assert now["gavel"]["state"] == "error" and "license page" in now["gavel"]["error"]
    state.put("emergency_stop", True)
    assert view.run_state(db.get_settings())["state"] == "stopped"
    assert by_id()["radar"]["state"] == "paused"


def test_run_state_offers_only_actions_that_fit(data):
    from clipfoundry import db
    from clipfoundry.autopilot import state
    from clipfoundry.office import view

    assert view.run_state(db.get_settings())["actions"] == ["start"]  # never started
    db.save_settings({"autopilot_enabled": True})
    assert view.run_state(db.get_settings())["actions"] == ["pause", "stop"]
    state.put("setup:started", time.time())
    db.save_settings({"autopilot_enabled": False})
    assert view.run_state(db.get_settings())["actions"] == ["resume", "stop"]
    state.put("emergency_stop", True)
    assert view.run_state(db.get_settings())["actions"] == ["start"]


def test_controls_compose_the_existing_buttons(client):
    from clipfoundry import db
    from clipfoundry.autopilot import state

    snap = client.get("/api/office/snapshot").json()
    assert snap["run"]["state"] == "stopped" and snap["cursor"] >= 0 and len(snap["roles"]) == 25
    assert snap["audience"]["footer"].startswith("Selected audience: YouTube") and "TikTok" in snap["audience"]["footer"]
    assert client.post("/api/office/control", json={"action": "pause"}, headers=H).status_code == 409
    assert client.post("/api/office/control", json={"action": "start"}).status_code == 403  # only from the app's page
    assert client.post("/api/office/control", json={"action": "start"}, headers=H).json()["run"]["state"] == "running"
    assert client.post("/api/office/control", json={"action": "pause"}, headers=H).json()["run"]["state"] == "paused"
    assert not db.get_settings()["autopilot_enabled"]
    assert client.post("/api/office/control", json={"action": "resume"}, headers=H).json()["run"]["state"] == "running"
    out = client.post("/api/office/control", json={"action": "stop"}, headers=H).json()
    assert out["run"]["state"] == "stopped" and state.paused()
    assert client.post("/api/office/control", json={"action": "start"}, headers=H).json()["run"]["state"] == "running"
    assert not state.paused()
    out = client.post("/api/office/control", json={"action": "pause_publishing"}, headers=H).json()
    assert out["run"]["publishing_paused"] and out["run"]["state"] == "running"  # clips are still made
    assert client.post("/api/office/control", json={"action": "resume_publishing"}, headers=H).json()["run"][
        "publishing_paused"] is False
    kinds = [e["data"]["action"] for e in client.get("/api/office/events").json()["events"] if e["type"] == "control"]
    assert kinds == ["start", "pause", "resume", "stop", "start", "pause_publishing", "resume_publishing"]


def test_read_endpoints(client):
    from clipfoundry.office import feed

    cast = client.get("/api/office/roles").json()
    assert len(cast["roles"]) == 25 and cast["problems"] == [] and cast["core"]["id"] == "core"
    assert all("kinds" not in r for r in cast["roles"])
    feed.decide("source", "rejected", ("source", "s9"), "No reuse permission", reported_by="gavel")
    assert client.get("/api/office/decisions", params={"point": "source"}).json()[0]["subject_id"] == "s9"
    health = client.get("/api/office/health").json()
    assert health["status"] in ("healthy", "degraded", "error", "unknown")
    assert {c["id"] for c in health["checks"]} >= {"scheduler", "queue", "gpu", "ffmpeg", "disk", "database"}
    assert all(c["checked_at"] and c["reason"] for c in health["checks"])
    room = client.get("/api/office/rooms/boss").json()
    assert room["decisions"][0]["reason"] == "No reuse permission" and "queue" in room
    assert client.get("/api/office/rooms/attic").status_code == 404
    for rid in ("discover", "analyze", "studio", "caption", "schedule", "dock", "system", "brain", "lounge"):
        assert client.get(f"/api/office/rooms/{rid}").status_code == 200, rid


def test_health_never_shows_green_for_a_reading_it_could_not_take(data, monkeypatch):
    from clipfoundry import gpu
    from clipfoundry.office import health

    def broken(*_a, **_k):
        raise RuntimeError("driver crashed")

    monkeypatch.setattr(gpu.manager, "status", broken)
    reading = health.gpu({})
    assert reading["status"] == "unknown" and "driver crashed" in reading["reason"]
    # the workers are off in tests: Background work is Unknown, never Healthy
    assert health.scheduler({"autopilot_enabled": False})["status"] == "unknown"


def test_old_events_are_pruned(data):
    from clipfoundry import db
    from clipfoundry.office import feed

    old = feed.emit("test", "radar", message="old")
    db.execute("UPDATE office_events SET at = ? WHERE id = ?", (time.time() - 30 * 86400, old))
    feed.emit("test", "radar", message="new")
    assert feed.prune() == 1
    assert [e["message"] for e in feed.events_after(0)["events"]] == ["new"]


# ------------------------------------------------------------ Settings → Integrations: waits, Test connection
@pytest.fixture()
def platforms(monkeypatch, data):
    """YouTube and TikTok stand-ins (tests/fake_platforms.py) with a connected, confirmed account on each."""
    from fake_platforms import FakeGoogle, FakeTikTok

    from clipfoundry import db
    from clipfoundry.publish import tiktok, youtube

    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    g, t = FakeGoogle(), FakeTikTok()
    monkeypatch.setattr(youtube, "TOKEN_URL", f"{g.url}/token")
    monkeypatch.setattr(youtube, "API_URL", f"{g.url}/youtube/v3")
    monkeypatch.setattr(youtube, "UPLOAD_URL", f"{g.url}/upload/youtube/v3/videos")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    g.access, t.access = "access-1", "act.1"
    later = time.time() + 3000
    db.save_account("youtube", tokens={"access_token": g.access, "expires_at": later, "refresh_token": g.refresh_token},
                    account_id="UC123", display_name="Test Channel", scopes=youtube.SCOPES[:2])
    db.save_account("tiktok", tokens={"access_token": t.access, "expires_at": later, "refresh_token": t.refresh_token,
                                      "refresh_expires_at": later * 2},
                    account_id="open-1", display_name="Test Creator",
                    scopes=["user.info.basic", "video.upload", "video.publish"])
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret", "tiktok_app_audited": True,
                      "audience_youtube_confirmed_at": time.time(), "audience_tiktok_confirmed_at": time.time()})
    yield g, t
    g.stop()
    t.stop()


def _cards(client) -> dict:
    return {c["id"]: c for c in client.get("/api/integrations").json()["cards"]}


def test_rate_limited_cards_read_the_waits_the_code_records(platforms, client):
    """`platform_limits` (a long Retry-After or a posting cap) and YouTube's daily quota, for both platforms."""
    from clipfoundry.autopilot import quota, scheduler

    cards = _cards(client)
    assert cards["youtube"]["status"] == "connected" and cards["tiktok"]["status"] == "connected"
    scheduler.block_platform("tiktok", time.time() + 3600, "TikTok asked to wait 1 h (rate_limit_exceeded)")
    tt = _cards(client)["tiktok"]
    assert tt["status"] == "rate_limited" and "asked to wait 1 h" in tt["detail"] and tt["limit"]["until"] > time.time()
    assert _cards(client)["youtube"]["status"] == "connected"  # one platform's wait does not stop the other
    quota.mark_exhausted("videos.insert", "The request cannot be completed because you have exceeded your quota.")
    yt = _cards(client)["youtube"]
    assert yt["status"] == "rate_limited" and "uploads (videos.insert calls)" in yt["detail"]
    assert yt["limit"]["until"] == quota.next_reset()


def test_test_connection_reads_once_and_changes_nothing(platforms, client):
    from clipfoundry import db

    g, t = platforms
    assert client.post("/api/integrations/youtube/test").status_code == 403  # only from ClipFoundry's own page
    assert _cards(client)["youtube"]["checked_at"] is None
    out = client.post("/api/integrations/youtube/test", headers=H).json()
    assert out["ok"] and out["status"] == "connected" and "Test Channel" in out["detail"]
    assert g.calls == {"/youtube/v3/channels": 1} and not g.sessions and not g.videos  # one read, no upload
    used = db.select("quota_usage", "method = 'channels.list'")
    assert [(u["purpose"], u["units"]) for u in used] == [("account", 1)]
    yt = _cards(client)["youtube"]
    assert yt["checked_at"] == out["at"] and yt["last_check"]["ok"] and yt["can_test"]
    assert "grant" not in yt["last_check"] and g.refresh_token not in client.get("/api/integrations").text
    # TikTok: creator_info, never an init, a chunk or a status call; "Everyone" is not offered as an audience
    out = client.post("/api/integrations/tiktok/test", headers=H).json()
    assert out["ok"] and "Followers" in out["detail"] and "Everyone" not in out["detail"]
    assert not t.inits and not t.uploads and not t.status_calls
    assert _cards(client)["tiktok"]["checked_at"] == out["at"]


def test_a_failed_check_shows_the_state_reason_and_what_to_do(platforms, client):
    from clipfoundry import db

    _g, t = platforms
    first = client.post("/api/integrations/youtube/test", headers=H).json()
    # today's API budget is used: Rate limited until the reset, the last successful check stays
    db.save_settings({"youtube_quota_default": 1})
    out = client.post("/api/integrations/youtube/test", headers=H).json()
    assert not out["ok"] and out["status"] == "rate_limited" and "midnight Pacific" in out["fix"]
    yt = _cards(client)["youtube"]
    assert yt["status"] == "rate_limited" and yt["checked_at"] == first["at"] and yt["action"] == out["fix"]
    db.save_settings({"youtube_quota_default": 10000})
    # TikTok no longer accepts the access token and the refresh token was revoked: connect again
    t.access, t.revoked = "act.other", True
    out = client.post("/api/integrations/tiktok/test", headers=H).json()
    assert not out["ok"] and out["status"] == "error" and "Connect TikTok again" in out["fix"]
    assert _cards(client)["tiktok"]["status"] == "error"
    assert not t.inits and not t.uploads
    # connecting again replaces the tokens the check tested: the old failure no longer decides the card
    tokens = db.account_tokens("tiktok")
    t.access, t.revoked, t.refresh_token = "act.2", False, "rft-new"
    db.save_account("tiktok", tokens={**tokens, "access_token": "act.2", "refresh_token": "rft-new"},
                    info={"needs_reconnect": False})
    tt = _cards(client)["tiktok"]
    assert tt["status"] == "connected" and tt["last_check"]["current"] is False
    assert client.post("/api/integrations/tiktok/test", headers=H).json()["ok"]


def test_test_connection_needs_a_connected_account(client):
    assert client.post("/api/integrations/youtube/test", headers=H).status_code == 409
    assert client.post("/api/integrations/tiktok/test", headers=H).status_code == 409
    assert client.post("/api/integrations/nvidia/test", headers=H).status_code == 409  # NVIDIA's own test still routes
