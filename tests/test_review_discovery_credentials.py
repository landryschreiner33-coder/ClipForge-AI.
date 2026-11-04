"""Search credentials are tested with real HTTP request plumbing and disposable state, never real keys."""
from __future__ import annotations

import time

import httpx
import pytest


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"youtube_api_key": "synthetic-search-secret", "trend_topics": "podcast",
                      "tavily_api_key": "synthetic-web-secret", "autopilot_enabled": True})
    return tmp_path


def transport(monkeypatch, respond):
    from clipfoundry.autopilot import providers

    monkeypatch.setattr(providers, "client", lambda timeout: httpx.Client(transport=httpx.MockTransport(respond)))


def connect_oauth(monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    db.save_settings({"youtube_api_key": "", "youtube_client_id": "synthetic-client",
                      "youtube_client_secret": "synthetic-client-secret"})
    db.save_account("youtube", tokens={"access_token": "old-token", "refresh_token": "synthetic-refresh",
                                       "expires_at": time.time() + 3600}, account_id="UCsynthetic")
    token_calls = []

    def get(self, force=False):
        token_calls.append(force)
        return "new-token" if force else "old-token"

    monkeypatch.setattr(youtube.Token, "get", get)
    return token_calls


@pytest.mark.parametrize("status,reason,code", [
    (401, "", "api_key_invalid"),
    (400, "keyInvalid", "api_key_invalid"),
    (400, "API_KEY_INVALID", "api_key_invalid"),
    (403, "API_KEY_HTTP_REFERRER_BLOCKED", "api_key_restricted"),
    (403, "API_KEY_SERVICE_BLOCKED", "api_key_restricted"),
    (403, "ipRefererBlocked", "api_key_restricted"),
    (403, "SERVICE_DISABLED", "api_disabled"),
    (403, "accessNotConfigured", "api_disabled"),
    (403, "forbidden", "api_key_rejected"),
    (400, "anything-else", "api_key_rejected"),
    (400, {"unexpected": "shape"}, "api_key_rejected"),
    (400, ["unexpected", "shape"], "api_key_rejected"),
    (400, None, "api_key_rejected"),
])
def test_key_errors_are_specific_do_not_echo_credentials_and_never_switch_to_account(data, monkeypatch,
                                                                                   status, reason, code):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import PublishError

    db.save_settings({"youtube_client_id": "synthetic-client", "youtube_client_secret": "client-secret"})
    db.save_account("youtube", tokens={"access_token": "connected-token"}, account_id="UCsynthetic")
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.params["key"] == "synthetic-search-secret"
        assert "authorization" not in request.headers
        return httpx.Response(status, json={"error": {"message": "synthetic-search-secret in provider echo",
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}]}})

    def forbidden_account(*args, **kwargs):
        raise AssertionError("A rejected optional key must not silently select the account")

    monkeypatch.setattr(youtube.Token, "get", forbidden_account)
    transport(monkeypatch, respond)
    client = providers.YouTubeDiscovery(db.get_settings())
    with pytest.raises(PublishError) as caught:
        client.check_connection()
    assert caught.value.code == code
    assert "synthetic-search-secret" not in str(caught.value) + caught.value.fix
    assert "Search connections" in caught.value.fix
    assert "reconnect" not in caught.value.fix.lower()
    assert len(requests) == client.calls == 1
    assert quota.usage()["default"]["by_purpose"]["discovery"] == 1
    assert db.get_settings()["youtube_api_key"] == "synthetic-search-secret"


def test_connected_search_refreshes_once_after_server_rejects_locally_unexpired_token(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota

    token_calls = connect_oauth(monkeypatch)
    requests = []

    def respond(request):
        requests.append(request)
        assert "key" not in request.url.params
        return httpx.Response(401 if len(requests) == 1 else 200,
                              json={"error": {"message": "invalid token"}} if len(requests) == 1 else
                              {"kind": "youtube#videoListResponse", "items": []})

    transport(monkeypatch, respond)
    client = providers.YouTubeDiscovery(db.get_settings())
    assert client.check_connection() == {"kind": "youtube#videoListResponse", "items": []}
    assert client.auth_mode == "connected_account"
    assert token_calls == [False, True]
    assert [r.headers["authorization"] for r in requests] == ["Bearer old-token", "Bearer new-token"]
    assert client.calls == 2
    assert quota.usage()["default"]["by_purpose"]["discovery"] == 2
    assert not db.select("api_cache")


@pytest.mark.parametrize("constraint", ["quota", "wait", "rejected_again"])
def test_oauth_refresh_respects_quota_and_server_wait_and_stops_after_one_refresh(data, monkeypatch, constraint):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota
    from clipfoundry.publish.common import PublishError

    token_calls = connect_oauth(monkeypatch)
    if constraint == "quota":
        db.save_settings({"youtube_quota_default": 1000, "youtube_discovery_share": 1})
        quota.record("videos.list", "discovery", calls=9)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401, headers={"Retry-After": "7200"} if constraint == "wait" else {},
                              json={"error": {"message": "old-token new-token"}})

    transport(monkeypatch, respond)
    client = providers.YouTubeDiscovery(db.get_settings())
    with pytest.raises((PublishError, quota.QuotaDenied)) as caught:
        client.check_connection()
    if constraint == "rejected_again":
        assert token_calls == [False, True]
        assert len(requests) == 2
        assert caught.value.code == "reconnect"
    else:
        assert token_calls == [False]
        assert len(requests) == 1
    if constraint == "wait":
        assert caught.value.retry_after == 7200
        assert providers.wait_until("youtube") >= time.time() + 7199
    assert "old-token" not in str(caught.value)


def test_connection_check_bypasses_fresh_cached_results_but_normal_discovery_does_not(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota
    from clipfoundry.publish.common import PublishError

    params = {"part": "id", "chart": "mostPopular", "maxResults": 1, "regionCode": "US"}
    quota.cached(["youtube", "videos", params], 600, lambda: {"items": [{"id": "cached-public-video"}]})
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.path.endswith("/videos")
        assert request.url.params["part"] == "id"
        assert request.url.params["maxResults"] == "1"
        return httpx.Response(400, json={"error": {"errors": [{"reason": "keyInvalid"}]}})

    transport(monkeypatch, respond)
    client = providers.YouTubeDiscovery(db.get_settings())
    assert client._get("videos.list", "videos", params, 600)["items"][0]["id"] == "cached-public-video"
    assert len(requests) == 0 and client.cache_hits == 1
    with pytest.raises(PublishError, match="search API key"):
        client.check_connection()
    assert len(requests) == client.calls == 1
    assert quota.usage()["default"]["calls"] == 1
    assert len(db.select("api_cache")) == 1  # A credential check never overwrites regular cached discovery.


@pytest.mark.parametrize("status,method,bucket", [(403, "search.list", "search"),
                                                  (403, "videos.list", "default")])
def test_real_youtube_quota_failure_marks_only_actual_method_bucket_and_keeps_no_echo(data, monkeypatch,
                                                                                   status, method, bucket):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota, state
    from clipfoundry.publish.common import PublishError

    def respond(request):
        return httpx.Response(status, json={"error": {"message": "synthetic-search-secret",
                              "errors": [{"reason": "quotaExceeded"}]}})

    transport(monkeypatch, respond)
    with pytest.raises(PublishError) as caught:
        providers.YouTubeDiscovery(db.get_settings())._get(method, "videos", {}, 0)
    assert caught.value.code == "quotaExceeded"
    assert quota.exhausted(bucket)
    assert not quota.exhausted("default" if bucket == "search" else "search")
    assert "synthetic-search-secret" not in str(caught.value) + str(state.open_actions())


def test_tavily_busy_wait_survives_restart_without_blocking_other_services_or_spending(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, headers={"Retry-After": "7200"}, text="synthetic-web-secret")

    transport(monkeypatch, respond)
    before = time.time()
    with pytest.raises(providers.Unavailable) as caught:
        providers.WebSearch(db.get_settings()).search("podcast", [])
    assert caught.value.retry_after == 7200
    assert providers.wait_until("web") >= before + 7200
    assert providers.wait_until("youtube") == providers.wait_until("library") == 0
    assert providers.web_usage(db.get_settings())["used"] == 0
    assert "synthetic-web-secret" not in str(caught.value) + caught.value.fix
    db.init()
    with pytest.raises(providers.Unavailable, match="asked to wait"):
        providers.WebSearch(db.get_settings()).search("podcast", [])
    assert len(requests) == 1


def test_legacy_key_whitespace_is_trimmed_only_at_request_selection(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    settings = {**db.get_settings(), "youtube_api_key": "  synthetic-search-secret\r\n",
                "tavily_api_key": "  synthetic-web-secret\n"}
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            assert request.url.params["key"] == "synthetic-search-secret"
            return httpx.Response(200, json={"kind": "youtube#videoListResponse", "items": []})
        assert request.headers["authorization"] == "Bearer synthetic-web-secret"
        return httpx.Response(200, json={"results": []})

    transport(monkeypatch, respond)
    providers.YouTubeDiscovery(settings).check_connection()
    providers.WebSearch(settings).search("podcast", [])
    assert len(requests) == 2
    assert settings["youtube_api_key"].endswith("\r\n")  # No silent rewrite of saved settings.


@pytest.mark.parametrize("body", [
    {},
    {"error": {"message": "synthetic-search-secret"}},
    {"kind": "youtube#videoListResponse", "items": [], "error": None},
    {"kind": "youtube#videoListResponse"},
    {"kind": "youtube#searchListResponse", "items": []},
    {"kind": "youtube#videoListResponse", "items": ["not an item"]},
    {"kind": "youtube#videoListResponse", "items": [{"id": 17}]},
    {"kind": "youtube#videoListResponse", "items": [{"id": ""}]},
])
def test_connection_probe_never_calls_an_error_or_malformed_200_response_successful(data, monkeypatch, body):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota
    from clipfoundry.publish.common import PublishError

    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(PublishError) as caught:
        providers.YouTubeDiscovery(db.get_settings()).check_connection()
    assert caught.value.code == "response"
    assert "synthetic-search-secret" not in str(caught.value) + caught.value.fix
    assert quota.usage()["default"]["calls"] == 1
    assert not db.select("api_cache")


def test_simultaneous_connection_check_and_discovery_cannot_spend_the_same_last_quota_unit(data, monkeypatch):
    import concurrent.futures
    import threading

    from clipfoundry import db
    from clipfoundry.autopilot import providers, quota

    db.save_settings({"youtube_quota_default": 1000, "youtube_discovery_share": 1})
    quota.record("videos.list", "discovery", calls=9)
    settings = db.get_settings()
    entered, release, second_request = threading.Event(), threading.Event(), threading.Event()
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
        else:
            second_request.set()
        return httpx.Response(200, json={"kind": "youtube#videoListResponse", "items": []})

    transport(monkeypatch, respond)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(providers.YouTubeDiscovery(settings).check_connection)
        try:
            assert entered.wait(3)
            second = pool.submit(providers.YouTubeDiscovery(settings)._get, "videos.list", "videos",
                                 {"part": "id", "id": "synthetic-video"}, 0)
            # Before the first response is counted, an unguarded concurrent request would also claim its unit.
            second_request.wait(0.2)
        finally:
            release.set()
        assert first.result(timeout=3)["items"] == []
        with pytest.raises(quota.QuotaDenied):
            second.result(timeout=3)
    assert len(requests) == 1
    assert quota.usage()["default"]["by_purpose"]["discovery"] == 10
