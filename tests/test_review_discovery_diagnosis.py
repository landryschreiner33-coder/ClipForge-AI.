"""Discovery advice reflects the service and review mode, with no writes from status reads."""
from __future__ import annotations

import os
import time

import httpx
import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_review_before_publish": True,
                      "trend_topics": "interview", "trend_poll_minutes": 180})
    host.WorkerHost(periodic=False)
    return tmp_path


def _dump():
    from clipfoundry import db

    with db.connect() as connection:
        return "\n".join(connection.iterdump())


@pytest.mark.parametrize("provider,name,service", [("web_search", "Web search", "Tavily"),
                                                   ("library", "The free video library", "Wikimedia Commons")])
def test_independent_service_wait_does_not_claim_youtube_daily_quota(data, provider, name, service):
    from clipfoundry.autopilot import home, state

    state.put("providers", {provider: {"status": "quota", "detail": "raw response is not needed here",
                                       "fix": "This service asked to wait 10 minutes; other work continues."}})
    before = _dump()
    problem = home.discovery_status()["problems"][0]
    assert problem["name"] == name and service in problem["detail"]
    assert "10 minutes" in problem["fix"]
    assert "YouTube" not in str(problem) and "midnight" not in str(problem)
    assert "raw response" not in str(problem)
    assert _dump() == before


def test_youtube_daily_allowance_keeps_reset_advice_and_actual_safe_explanation(data):
    from clipfoundry.autopilot import home, state

    state.put("providers", {"youtube": {"status": "quota", "detail": "0 videos · 0 API calls"}})
    problem = home.discovery_status()["problems"][0]
    assert "daily discovery allowance" in problem["detail"] and "midnight Pacific" in problem["fix"]
    state.put("providers", {"youtube": {"status": "quota", "problem": "The discovery share is used up.",
                                        "fix": "Other searches continue until tomorrow's reset."}})
    problem = home.discovery_status()["problems"][0]
    assert problem["detail"] == "The discovery share is used up."
    assert problem["fix"] == "Other searches continue until tomorrow's reset."


def test_review_mode_empty_state_does_not_claim_reuse_permission_is_stopping_discovery(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", {"at": time.time(), "signals": 1})
    db.insert("sources", {"platform": "url", "external_id": "weak-find", "status": "skipped",
                          "status_note": "Below the minimum source estimate"})
    settings = {**db.get_settings(), "autopilot_discovery_uploadable_only": True}
    before = _dump()
    message = home.empty_message(settings, True, [])
    assert "local review" in message and "Activity" in message and "public video link" in message
    assert "with posting permission" not in message and "agreement" not in message
    assert _dump() == before
    assert "posting permission" in home.empty_message({**settings, "autopilot_review_before_publish": False},
                                                       True, [])


def test_activity_keeps_reuse_unknown_and_explains_individual_review(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, rights

    source = db.insert("sources", {"platform": "url", "external_id": "prepared",
                                   "url": "https://example.com/interview.mp4", "status": "analyzed",
                                   "title": "Prepared interview", "clips_selected": 1})
    before = _dump()
    row = home.activity()[0]
    assert row["id"] == source["id"] and "check reuse" in row["posting"]
    assert "individual post in Queue" in row["posting"] and "never posted" not in row["posting"]
    assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    assert not db.select("source_rights") and not db.select("publish_consents")
    assert _dump() == before
    db.save_settings({"autopilot_review_before_publish": False})
    assert "never posted" in home.activity()[0]["posting"]


def test_next_search_fallback_uses_real_capacity_cadence_without_writing_a_deadline(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    last = time.time() - 60
    state.put("trend:last_scan", {"at": last, "signals": 0})
    before = _dump()
    assert home.next_look(db.get_settings()) == pytest.approx(last + 900)
    assert _dump() == before


@pytest.mark.parametrize("job_status", [None, "running", "waiting"])
def test_recent_search_does_not_make_rejected_keys_healthy_while_other_work_continues(data, job_status):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state
    from clipfoundry.office import health

    db.save_settings({"youtube_api_key": "synthetic-invalid-key", "tavily_api_key": "synthetic-invalid-web-key",
                      "library_discovery": True})
    state.put("trend:last_scan", {"at": time.time() - 60, "signals": 0})
    state.put("providers", {"youtube": {"status": "error", "detail": "never echo synthetic-invalid-key"},
                            "web_search": {"status": "error"}, "library": {"status": "ok"}})
    if job_status:
        job = queue.enqueue("trend_scan")
        queue.claim(queue.KIND_WORKER["trend_scan"], "health-audit")
        if job_status == "waiting":
            db.update("worker_jobs", job["id"], status="waiting", run_after=time.time() + 600,
                      message="A temporary service wait")
    before = _dump()
    reading = health.discovery(db.get_settings())
    assert reading["status"] == "degraded"
    assert "YouTube search, web search did not work" in reading["reason"]
    assert "Search connections" in reading["action"] and "folder checks continue" in reading["action"]
    assert "synthetic-invalid" not in str(reading)
    assert "stopped" not in reading["reason"]
    if job_status == "waiting":
        assert reading["next_scan"] > time.time()
    assert _dump() == before


def test_health_ignores_removed_optional_keys_and_recovers_after_a_success(data):
    from clipfoundry import db
    from clipfoundry.autopilot import state
    from clipfoundry.office import health

    db.save_settings({"youtube_api_key": "", "tavily_api_key": "", "library_discovery": True})
    state.put("providers", {"youtube": {"status": "error"}, "web_search": {"status": "error"},
                            "library": {"status": "error", "detail": "raw provider response"}})
    reading = health.discovery(db.get_settings())
    assert reading["status"] == "degraded" and "free video library" in reading["reason"]
    assert "YouTube search" not in reading["reason"] and "web search" not in reading["reason"]
    assert "internet connection" in reading["action"] and "raw provider response" not in str(reading)
    state.put("providers", {"youtube": {"status": "error"}, "web_search": {"status": "error"},
                            "library": {"status": "ok"}})
    before = _dump()
    assert health.discovery(db.get_settings())["status"] == "healthy"
    assert _dump() == before


def test_rejected_search_keys_do_not_stop_free_library_folder_or_local_queue(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import home, host, providers, queue, rights, state

    db.save_settings({"youtube_api_key": "synthetic-invalid-search-key", "tavily_api_key": "synthetic-invalid-web-key",
                      "tavily_free_credits": 20, "library_discovery": True})
    recording = data / "My interview original.mp4"
    recording.write_bytes(b"synthetic source admission only; media processing does not run")
    os.utime(recording, (time.time() - 120,) * 2)
    providers.add_feed("watch_folder", "My recordings", {"path": str(data)}, rights.OWNED, "My recordings")
    rights.add_rule("folder", str(data), rights.OWNED, "My recordings")  # the feed-creation API stores both
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(401, json={"detail": "invalid key"})
        if request.url.path.endswith("/w/api.php"):
            return httpx.Response(200, json={"query": {"pages": []}})
        return httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}],
                                                  "message": "API key not valid."}})

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(respond)))

    def run(kind):
        row = queue.enqueue(kind)
        claimed = queue.claim(queue.KIND_WORKER[kind], "key-failure-audit")
        assert claimed and claimed["id"] == row["id"]
        result = host.HANDLERS[kind](host.Job(claimed, "key-failure-audit"))
        queue.complete(claimed, "key-failure-audit", result)

    run("trend_scan")
    # The trend scan enqueued Source Scout; process that actual durable handoff.
    pending = queue.jobs(("queued",), worker="source_scout")
    assert len(pending) == 1
    claimed = queue.claim("source_scout", "key-failure-audit")
    result = host.HANDLERS["source_scout"](host.Job(claimed, "key-failure-audit"))
    queue.complete(claimed, "key-failure-audit", result)
    assert any(method == "POST" for method, _ in calls)
    assert any(path.endswith("/w/api.php") for _, path in calls)
    assert state.get("providers")["library"]["status"] == "ok"
    assert state.get("providers")["web_search"]["status"] == "error"
    sources = db.select("sources")
    assert len(sources) == 1 and sources[0]["platform"] == "local" and sources[0]["status"] == "queued"
    assert len(queue.jobs(("queued",), worker="clip_hunter")) == 1
    assert home.discovery_status()["problems"] and not db.select("publications")
