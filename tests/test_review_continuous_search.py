"""Independent search services keep working without bypassing waits, budgets or bounded admission."""
from __future__ import annotations

import time

import httpx
import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db
    from clipfoundry.autopilot import host

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "youtube_api_key": "fake-search-key",
                      "tavily_api_key": "fake-web-key", "tavily_free_credits": 20,
                      "trend_topics": "interview", "autopilot_sources_per_day": 0})
    host.WorkerHost(periodic=False)
    return tmp_path


def run(kind):
    from clipfoundry.autopilot import host, queue

    row = queue.enqueue(kind)
    claimed = queue.claim(queue.KIND_WORKER[kind], "independent-search")
    assert claimed["id"] == row["id"]
    result = host.HANDLERS[kind](host.Job(claimed, "independent-search"))
    queue.complete(claimed, "independent-search", result)
    return result


def test_youtube_wait_does_not_stop_web_library_or_next_search_and_survives_restart(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    calls = []

    def response(request):
        calls.append(str(request.url.path))
        if request.url.path.endswith("/videos"):
            return httpx.Response(200, json={"items": []})
        if request.url.path.endswith("/search") and request.method == "GET":
            return httpx.Response(429, headers={"Retry-After": "7200"},
                                  json={"error": {"message": "Wait", "errors": [{"reason": "rateLimitExceeded"}]}})
        if request.method == "POST":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"query": {"pages": []}})

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(response)))
    first = time.time()
    run("trend_scan")
    assert providers.wait_until("youtube") >= first + 7200
    assert float(state.get("next:trend_scan", 0) or 0) < first + 7200
    assert len([p for p in calls if p.endswith("/search")]) == 3  # one YouTube, two independent web searches
    assert "/w/api.php" in calls
    before = len(calls)
    db.init()  # a new discovery object/database reopen must retain the exact service wait
    run("trend_scan")
    assert calls[before:] == ["/search", "/search", "/w/api.php"]
    assert state.get("providers")["library"]["status"] == "ok"
    assert providers.web_usage(db.get_settings())["used"] == 4
    assert providers.wait_until("youtube") >= first + 7200


def test_youtube_quota_does_not_lengthen_unrelated_search_period_and_full_queue_stays_bounded(data):
    from clipfoundry import db
    from clipfoundry.autopilot import quota, scout, state

    quota.mark_exhausted("search.list")
    assert quota.discovery_period_factor(db.get_settings()) == float("inf")
    assert scout._period(db.get_settings(), 3 * 3600) == 900
    for i in range(6):
        db.insert("sources", {"platform": "url", "external_id": f"busy-{i}", "status": "analyzing"})
    assert scout._period(db.get_settings(), 3 * 3600) == 3 * 3600
    assert not state.get("discovery:wait:library")
    assert "Other searches" in quota.status(db.get_settings())["warnings"][-1]


def test_legacy_global_wait_is_preserved_for_youtube_but_free_search_wakes_soon(data):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, scout, state

    old_wait = time.time() + 7 * 3600
    state.put("next:trend_scan", old_wait)
    state.put("providers", {"youtube": {"status": "error"}})
    assert scout._period(db.get_settings(), 3 * 3600) == 900
    assert providers.wait_until("youtube") >= old_wait
    assert state.get("next:trend_scan") <= time.time() + 900
    # This migration is one-time and may not repeatedly extend a requested service wait.
    until = providers.wait_until("youtube")
    scout._period(db.get_settings(), 3 * 3600)
    assert providers.wait_until("youtube") == until


def test_periodic_search_deadline_shortens_when_the_processing_queue_drains(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, providers, queue, state

    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    settings = {**db.get_settings(), "trend_poll_minutes": 180}
    state.put("discovery:independent_checks", True)  # Ordinary operation after the one-time migration.
    providers.defer("youtube", 7200)
    remote_wait = providers.wait_until("youtube")
    sources = [db.insert("sources", {"platform": "url", "external_id": f"pipeline-{i}",
                                     "status": "analyzing"}) for i in range(6)]
    assert "trend_scan" in host.run_periodic(settings, now=clock[0])
    assert state.get("next:trend_scan") == pytest.approx(clock[0] + 3 * 3600)
    claimed = queue.claim("trend_scout", "drained-search")
    assert claimed and claimed["kind"] == "trend_scan"
    queue.complete(claimed, "drained-search", {"message": "Search completed while processing was full"})
    for source in sources:
        db.update("sources", source["id"], status="done")

    clock[0] += 100
    assert "trend_scan" not in host.run_periodic(settings, now=clock[0])
    due = float(state.get("next:trend_scan"))
    assert clock[0] < due <= clock[0] + 900
    assert providers.wait_until("youtube") == remote_wait
    assert len(queue.jobs(worker="trend_scout")) == 1

    clock[0] = due - 1
    assert "trend_scan" not in host.run_periodic(settings, now=clock[0])
    assert state.get("next:trend_scan") == due  # Polling must not keep pushing the check into the future.
    clock[0] = due
    assert "trend_scan" in host.run_periodic(settings, now=clock[0])
    assert "trend_scan" not in host.run_periodic(settings, now=clock[0])
    assert len(queue.jobs(worker="trend_scout")) == 2
    assert providers.wait_until("youtube") == remote_wait


def test_free_feed_tick_refills_unused_saved_signals_without_network_or_new_feed_items(data):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    db.insert("trend_signals", {"provider": "web_search", "platform": "url", "external_id": "saved-pick",
                                "status": "active", "title": "Interview with useful context",
                                "first_seen": time.time(), "last_checked": time.time()})
    run("feed_scan")
    assert len(queue.jobs(("queued",), worker="source_scout")) == 1


def test_youtube_search_rotates_five_bounded_pages_and_keeps_exact_query_across_resume(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    requests = []

    def response(request):
        params = dict(request.url.params)
        page = int(params.get("pageToken", "page0").removeprefix("page"))
        requests.append(params)
        return httpx.Response(200, json={"items": [{"id": {"videoId": f"video-{page}"}}],
                                        "nextPageToken": f"page{page + 1}"})

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(response)))
    found, offsets = [], []
    since = time.time() - 3 * 86400
    for i in range(6):
        db.init()
        youtube = providers.YouTubeDiscovery(db.get_settings())
        found += youtube.search("interview", "US", "en", since + i * 3600)
        offsets.append(youtube.search_offset)
    assert found == ["video-0", "video-1", "video-2", "video-3", "video-4", "video-0"]
    assert offsets == [0, 25, 50, 75, 100, 0]
    assert len(requests) == 6  # exactly one call per pass, new time boundary after the bounded cycle
    assert len({r["publishedAfter"] for r in requests[:5]}) == 1
    assert all("key" in r for r in requests)


def test_library_cursor_is_bounded_and_retry_after_only_holds_library(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    offsets = []
    limited = False

    def response(request):
        offset = int(request.url.params.get("gsroffset", "0"))
        offsets.append(offset)
        if limited:
            return httpx.Response(503, headers={"Retry-After": "172800"})
        return httpx.Response(200, json={"query": {"pages": []}, "continue": {"gsroffset": offset + 10}})

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(response)))
    for _ in range(6):
        providers.Library(db.get_settings()).search("interview")
    assert offsets == [0, 10, 20, 30, 40, 0]
    limited = True
    before = time.time()
    with pytest.raises(providers.Unavailable):
        providers.Library(db.get_settings()).search("another topic")
    assert providers.wait_until("library") >= before + 172800
    assert providers.wait_until("youtube") == 0
    calls = len(offsets)
    db.init()
    with pytest.raises(providers.Unavailable) as exc:
        providers.Library(db.get_settings()).search("third topic")
    assert exc.value.retry_after > 172700 and len(offsets) == calls


def test_missing_or_exhausted_web_allowance_never_enables_paid_search(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, state

    def unexpected(*args):
        raise AssertionError("No HTTP request is allowed after the explicit free allowance")

    state.put(f"cost:tavily:{providers.month_key()}", 20)
    monkeypatch.setattr(providers, "client", unexpected)
    with pytest.raises(providers.Unavailable, match="paused for this month"):
        providers.WebSearch(db.get_settings()).search("interview", [])
    assert providers.web_usage(db.get_settings())["cost_usd"] == 0
