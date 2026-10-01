"""Idle Autopilot regressions: real queue/database, local platform stand-ins, no real accounts."""
from __future__ import annotations

import os
import time

import pytest

from fake_platforms import FakeGoogle


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True, "trend_topics": "space", "library_discovery": False})
    return tmp_path


@pytest.fixture()
def google(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    g = FakeGoogle()
    monkeypatch.setattr(youtube, "API_URL", f"{g.url}/youtube/v3")
    db.save_settings({"youtube_api_key": g.api_key})
    yield g
    g.stop()


def run(kind):
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue(kind)
    claimed = queue.claim(row["worker"], "test")
    assert claimed is not None
    result = host.HANDLERS[claimed["kind"]](host.Job(claimed, "test"))
    queue.complete(claimed, "test", result)
    return result


def test_connected_and_agreed_channels_are_discovered_without_a_feed(google):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    db.save_account("youtube", tokens={"access_token": "fake"}, account_id="UCmine")
    rights.add_agreement("Creator", ["UCcreator0000000000000001"], "Written permission")
    google.add_video("ownedvideo1", "My recording", channel="UCmine")
    google.add_video("creatorvid1", "An interview", channel="UCcreator0000000000000001")
    run("trend_scan")
    run("source_scout")
    sources = {s["external_id"]: s for s in db.select("sources")}
    assert sources["ownedvideo1"]["rights_status"] == rights.OWNED
    assert sources["creatorvid1"]["rights_status"] == rights.ALLOWLISTED
    assert all(s["status"] == "needs_file" for s in sources.values())
    assert not db.select("source_feeds")  # the user did not have to configure a second list


def test_a_search_limit_does_not_discard_the_chart_or_creator_uploads(google):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, state

    google.add_video("chartvideo1", "A popular interview")
    google.popular = ["chartvideo1"]
    rights.add_agreement("Creator", ["UCcreator0000000000000001"], "Written permission")
    google.add_video("creatorvid1", "An interview", channel="UCcreator0000000000000001")
    google.search_quota_exceeded = True
    run("trend_scan")
    assert {s["external_id"] for s in db.select("trend_signals")} == {"chartvideo1", "creatorvid1"}
    assert state.get("providers")["youtube"]["status"] != "ok"


def test_an_agreement_shared_folder_is_scanned_without_an_extra_watch_folder(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    folder = data / "creator"
    folder.mkdir()
    video = folder / "A complete interview.mp4"
    video.write_bytes(b"test file; ingestion is not run in this test")
    os.utime(video, (time.time() - 120,) * 2)
    rights.add_agreement("Creator", [], "Written permission", media_folder=str(folder))
    run("feed_scan")
    run("source_scout")
    sources = db.select("sources")
    assert len(sources) == 1 and sources[0]["status"] == "queued"
    assert sources[0]["rights_status"] == rights.ALLOWLISTED
    assert not db.select("source_feeds")


def test_expired_or_disabled_agreements_are_not_used_for_discovery(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    rules = rights.add_agreement("Creator", ["UCcreator0000000000000001"], "Written permission",
                                media_folder=str(data), expires_at=time.time() - 1)
    assert scout.discovery_feeds(db.get_settings()) == []
    assert scout.discovery_channels(db.get_settings()) == []
    for rule in rules:
        db.update("source_rights", rule["id"], expires_at=None, active=0)
    assert scout.discovery_feeds(db.get_settings()) == []
    assert scout.discovery_channels(db.get_settings()) == []


@pytest.mark.parametrize("outcome", ["failed", "canceled"])
def test_terminal_hunt_does_not_leave_source_busy_forever(data, outcome):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scout

    src = db.insert("sources", {"platform": "local", "external_id": "interrupted", "kind": "recorded",
                                "status": "ingesting", "selected_day": scout.local_day(db.get_settings())})
    project = db.create_project("Interrupted recording", source_id=src["id"], status="processing")
    db.update("sources", src["id"], project_id=project["id"])
    job = queue.enqueue("hunt_source", {"source_id": src["id"]}, ref=("source", src["id"]), max_attempts=1)
    claimed = queue.claim("clip_hunter", "gone")
    db.update("worker_jobs", job["id"], lease_until=time.time() - 1)
    if outcome == "failed":
        queue.recover()  # crash recovery cannot call the dead handler's exception guard
    else:
        queue.mark_canceled(claimed, "gone")
    db.execute("UPDATE sources SET updated_at = ? WHERE id = ?", (time.time() - 120, src["id"]))
    assert queue.get(job["id"])["status"] == outcome
    run("feed_scan")
    assert db.fetch("sources", src["id"])["status"] == "failed"
    assert db.get_project(project["id"])["status"] == "error"
    assert scout.today_counts(db.get_settings())["busy"] == 0
    assert not queue.jobs(queue.ACTIVE, ref=("source", src["id"]))  # a canceled job is not silently restarted


def test_active_retry_is_not_mistaken_for_an_abandoned_source(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scout

    src = db.insert("sources", {"platform": "local", "external_id": "retry", "kind": "recorded",
                                "status": "ingesting"})
    job = queue.enqueue("hunt_source", {"source_id": src["id"]}, ref=("source", src["id"]))
    claimed = queue.claim("clip_hunter", "test")
    queue.wait(claimed, "test", "server", 600, "The server asked us to wait")
    db.execute("UPDATE sources SET updated_at = ? WHERE id = ?", (time.time() - 120, src["id"]))
    assert scout.reconcile_sources() == 0
    assert db.fetch("sources", src["id"])["status"] == "ingesting"
    assert queue.get(job["id"])["status"] == "waiting"


def test_partial_discovery_preserves_retry_after_and_does_not_send_more_requests(google, monkeypatch):
    import httpx
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    google.add_video("chartvideo1", "Popular interview")
    google.popular = ["chartvideo1"]
    transport = httpx.HTTPTransport()
    requests = []

    def respond(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/search"):
            return httpx.Response(429, headers={"Retry-After": "600"},
                                  json={"error": {"message": "Wait", "errors": [{"reason": "rateLimitExceeded"}]}})
        return transport.handle_request(request)

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(respond)))
    before = time.time()
    run("trend_scan")
    assert state.get("next:trend_scan") >= before + 600
    assert requests == ["/youtube/v3/videos", "/youtube/v3/search"]
    assert db.select("trend_signals", "external_id = 'chartvideo1'")
    transport.close()


def test_waiting_file_is_rechecked_even_without_new_feed_entries(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights

    video = data / "original.mp4"
    src = db.insert("sources", {"platform": "local", "external_id": "waiting", "title": "My recording",
                                "local_path": str(video), "kind": "recorded", "status": "needs_file",
                                "expected_clips": 2, "source_score": 70})
    rights.add_rule("folder", str(data), rights.OWNED, "My recordings")
    video.write_bytes(b"arrived later")
    os.utime(video, (time.time() - 120,) * 2)
    run("feed_scan")
    assert queue.jobs(("queued",), worker="source_scout")
    run("source_scout")
    assert db.fetch("sources", src["id"])["status"] == "queued"


def test_available_file_after_eighty_missing_files_is_not_starved(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    rights.add_rule("folder", str(data), rights.OWNED, "My recordings")
    for i in range(81):
        video = data / f"recording-{i}.mp4"
        if i == 80:
            video.write_bytes(b"available")
        db.insert("sources", {"platform": "local", "external_id": str(i), "title": f"Recording {i}",
                              "local_path": str(video), "kind": "recorded", "status": "needs_file",
                              "expected_clips": 2, "source_score": 100 - i})
    picked = scout.select_for_today(db.get_settings())
    assert [s["external_id"] for s in picked] == ["80"]


def test_library_only_setup_is_shown_as_available(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home

    db.save_settings({"library_discovery": True})
    view = home.view(db.get_settings(), {}, True)
    assert view["setup"]["can_discover"]
    assert "Connect YouTube" not in view["empty"]


def test_stopped_workers_do_not_look_like_permanent_startup(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("setup:started", time.time() - 8 * 3600)
    monkeypatch.setattr(home, "BOOT", time.time() - 120)
    assert home.currently(db.get_settings(), False) == "Background work has stopped"


def test_skipped_videos_are_not_presented_as_an_active_search(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", {"at": time.time() - 120, "signals": 1, "active": 1})
    state.put("next:trend_scan", time.time() + 3600)
    db.insert("sources", {"platform": "youtube", "external_id": "missing", "status": "needs_file"})
    view = home.view(db.get_settings(), {}, True)
    assert view["currently"] == "No usable video files yet"
    assert view["discovery"]["last_scan"] and view["discovery"]["next_scan"]
    assert view["discovery"]["counts"]["needs_file"] == 1


def test_skipped_finds_do_not_hide_videos_that_were_already_clipped(data):
    """Seen in the sandbox: two posts waited for an OK while the status line said no covered video was found."""
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", {"at": time.time() - 120, "signals": 3, "active": 3})
    for i, status in enumerate(("needs_rights", "needs_file", "weak")):
        db.insert("sources", {"platform": "youtube", "external_id": f"v{i}", "status": status})
    assert home.view(db.get_settings(), {}, True)["currently"] == "Waiting for the next search"


def test_provider_failure_is_visible_on_the_main_page(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("providers", {"youtube": {"name": "YouTube", "status": "error", "detail": "Connection failed",
                                         "fix": "Check your internet connection.", "at": time.time()}})
    view = home.view(db.get_settings(), {}, True)
    assert view["discovery"]["problems"] == [{"name": "YouTube search", "detail": "Connection failed",
                                             "fix": "Check your internet connection."}]
    assert view["currently"] == "Some searches did not work"


def test_search_problems_are_in_plain_words(data):
    """The main page never shows the technical line (API calls, quota, provider names) of a search that failed."""
    from clipfoundry import db
    from clipfoundry.autopilot import home, scout, state

    state.put("providers", {
        "youtube": scout._provider_status("YouTube Data API", "quota", "0 videos · 3 API calls · stopped early: quota"),
        "web_search": scout._provider_status("Web search (Tavily)", "budget", "Web search paused: 1000 of 1000"),
        "feed:abc": scout._provider_status("Your videos folder", "error", "Folder not found: C:/Videos/ClipFoundry"),
        "library": scout._provider_status("Free-license library (Wikimedia Commons)", "ok", "3 videos"),
    })
    problems = home.view(db.get_settings(), {}, True)["discovery"]["problems"]
    assert [p["name"] for p in problems] == ["YouTube search", "Web search", "Checking “Your videos folder”"]
    text = " ".join(f"{p['name']} {p['detail']} {p['fix']}" for p in problems).lower()
    assert not [w for w in ("quota", "api call", "provider", "tavily", "feed") if w in text], text
    assert "after midnight pacific time" in text and "folder not found" in text


def test_youtube_daily_limit_is_reported_as_the_daily_limit(google):
    from clipfoundry.autopilot import state

    google.add_video("chartvideo1", "Popular interview")
    google.popular = ["chartvideo1"]
    google.search_quota_exceeded = True
    run("trend_scan")
    assert state.get("providers")["youtube"]["status"] == "quota"


def test_stopped_background_work_is_a_needs_you_item_but_not_right_after_start(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    settings = db.get_settings()
    state.put("setup:started", time.time() - 8 * 3600)
    monkeypatch.setattr(home, "BOOT", time.time())  # the app was just started: its workers get a moment
    assert home.currently(settings, False) == "Starting"
    assert not [i for i in home.needs_you(settings, {}, False) if i["type"] == "stopped"]
    monkeypatch.setattr(home, "BOOT", time.time() - 120)
    item = home.needs_you(settings, {}, False)[0]
    assert item["type"] == "stopped" and "start.bat" in item["fix"]
    assert not [i for i in home.needs_you(settings, {}, True) if i["type"] == "stopped"]
    state.put("emergency_stop", True)  # all jobs stopped on purpose: that is not "stopped working"
    assert not home.workers_stopped(settings, False)


def test_needs_videos_says_when_your_own_videos_have_no_file(data):
    """A connected channel's own uploads are found and covered, but YouTube does not let apps download them: Needs
    you must not say they belong to other people."""
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", {"at": time.time() - 60, "signals": 2, "active": 2})
    db.insert("sources", {"platform": "youtube", "external_id": "mine1", "status": "needs_file",
                          "updated_at": time.time()})
    db.insert("sources", {"platform": "youtube", "external_id": "other1", "status": "needs_rights",
                          "updated_at": time.time()})
    item = [i for i in home.view(db.get_settings(), {}, True)["needs_you"] if i["type"] == "videos"][0]
    assert "1 video it may use has no file it is allowed to download" in item["detail"]
    assert "The 1 other video it found online belongs to other people" in item["detail"]


def test_library_api_errors_are_not_reported_as_a_successful_empty_scan(data, monkeypatch):
    import httpx
    from clipfoundry.autopilot import providers

    def respond(request):
        return httpx.Response(200, json={"error": {"code": "maxlag", "info": "Waiting for replication"}})

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(providers.Unavailable, match="maxlag"):
        providers.Library({"library_discovery": True}).search("space")


def test_malformed_web_response_does_not_discard_youtube_results(google, monkeypatch):
    import httpx
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    google.add_video("spacevideo1", "Space interview")
    db.save_settings({"tavily_api_key": "fake-key"})
    monkeypatch.setattr(providers, "TAVILY_URL", "https://search.invalid/search")

    transport = httpx.HTTPTransport()

    def respond(request):
        if request.url.host == "search.invalid":
            return httpx.Response(200, text="not json")
        return transport.handle_request(request)

    def clients(timeout):
        return httpx.Client(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(providers, "client", clients)
    run("trend_scan")
    assert db.select("trend_signals", "external_id = 'spacevideo1'")
    assert state.get("providers")["web_search"]["status"] == "error"
    transport.close()
