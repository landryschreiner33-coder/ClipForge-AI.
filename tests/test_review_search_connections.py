"""Explicit credential checks use disposable keys and intercepted HTTP, never owner accounts or live services."""
from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

H = {"X-ClipFoundry": "1"}
YT_KEY = "synthetic-youtube-secret"
WEB_KEY = "synthetic-tavily-secret"
YT_ANSWER = {"kind": "youtube#videoListResponse", "items": [{"id": "test-video"}]}
USAGE = {"key": {"usage": 2, "limit": None},
         "account": {"current_plan": "Researcher", "plan_usage": 12, "plan_limit": 1000}}


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"youtube_api_key": YT_KEY, "tavily_api_key": WEB_KEY,
                      "discovery_monthly_budget_usd": 0, "tavily_free_credits": 0})
    return tmp_path


@pytest.fixture
def client(data):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as connection:
        yield connection


@pytest.fixture
def network(monkeypatch):
    from clipfoundry.autopilot import providers, search_connections
    from clipfoundry.publish import youtube

    class Intercepted:
        def __init__(self):
            self.requests = []
            self.handler = None

        def dispatch(self, request):
            self.requests.append(request)
            assert self.handler is not None, "This test did not authorize an outbound request"
            return self.handler(request)

        def client(self, *args, **kwargs):
            return httpx.Client(transport=httpx.MockTransport(self.dispatch))

    intercepted = Intercepted()
    for module in (providers, search_connections, youtube):
        monkeypatch.setattr(module, "client", intercepted.client)
    return intercepted


def dump() -> str:
    from clipfoundry import db

    with db.connect() as connection:
        return "\n".join(connection.iterdump())


def safe_public(value) -> None:
    text = json.dumps(value)
    assert YT_KEY not in text and WEB_KEY not in text
    assert "identity" not in text


def oauth(*, expired=False):
    from clipfoundry import db

    db.save_settings({"youtube_api_key": "", "youtube_client_id": "synthetic-client",
                      "youtube_client_secret": "synthetic-client-secret"})
    db.save_account("youtube", account_id="UCsynthetic", scopes=["youtube.readonly"],
                    tokens={"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                            "expires_at": 0 if expired else time.time() + 3600})


def test_get_status_is_read_only_does_not_probe_and_hides_secret_fingerprints(client, network):
    from clipfoundry.autopilot import search_connections

    network.handler = lambda request: httpx.Response(200, json=USAGE)
    assert search_connections.test("tavily")["ok"]
    before = dump()
    count = len(network.requests)
    response = client.get("/api/integrations/search")
    assert response.status_code == 200
    shown = response.json()
    assert shown["tavily"]["last_check"]["current"] and shown["tavily"]["configured"]
    assert shown["youtube"]["configured"] and shown["youtube"]["last_check"] is None
    safe_public(shown)
    assert len(network.requests) == count and dump() == before


@pytest.mark.parametrize("key", ["youtube_api_key", "tavily_api_key"])
def test_save_key_trims_masks_preserves_masked_value_and_can_remove(client, network, key):
    from clipfoundry import db

    response = client.put("/api/settings", json={key: "  synthetic-replacement-key\n"})
    assert response.status_code == 200 and response.json()[key] == "********"
    assert db.get_settings()[key] == "synthetic-replacement-key"
    assert "synthetic-replacement-key" not in response.text
    assert client.get("/api/settings").json()[key] == "********"
    assert client.put("/api/settings", json={key: "********"}).status_code == 200
    assert db.get_settings()[key] == "synthetic-replacement-key"
    assert client.put("/api/settings", json={key: ""}).json()[key] == ""
    assert db.get_settings()[key] == "" and not network.requests


@pytest.mark.parametrize("value", [123, None, "Bearer synthetic-secret", "synthetic\nsecret", "a\x00b", "x" * 4097])
@pytest.mark.parametrize("key", ["youtube_api_key", "tavily_api_key"])
def test_invalid_pasted_key_is_422_without_echo_or_partial_write(client, network, key, value):
    before = dump()
    response = client.put("/api/settings", json={key: value, "trend_region": "CA"})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text and "synthetic\\nsecret" not in response.text
    assert dump() == before and not network.requests


@pytest.mark.parametrize("guard", ["header", "remote_client", "remote_host"])
def test_check_requires_the_local_app_page_and_never_sends_a_refused_request(data, network, guard):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    host = "http://192.168.1.12:8765" if guard == "remote_host" else "http://127.0.0.1:8765"
    address = ("192.168.1.10", 1234) if guard == "remote_client" else ("127.0.0.1", 1234)
    connection = TestClient(app, base_url=host, client=address)
    before = dump()
    response = connection.post("/api/integrations/search/youtube/test", headers={} if guard == "header" else H)
    assert response.status_code == 403 and not network.requests and dump() == before


def test_unknown_provider_is_rejected_without_an_outbound_request(client, network):
    assert client.post("/api/integrations/search/unknown/test", headers=H).status_code == 422
    assert not network.requests


def test_youtube_check_bypasses_existing_cache_and_counts_one_general_quota_read(client, network):
    from clipfoundry.autopilot import quota

    params = {"part": "id", "chart": "mostPopular", "maxResults": 1, "regionCode": "US"}
    quota.cached(["youtube", "videos", params], 1800, lambda: {"cached": "not a credential check"}, "videos.list")
    network.handler = lambda request: httpx.Response(200, json=YT_ANSWER)
    response = client.post("/api/integrations/search/youtube/test", headers=H)
    assert response.status_code == 200 and response.json()["ok"] and response.json()["current"]
    request, = network.requests
    assert request.method == "GET" and request.url.path.endswith("/videos")
    assert request.url.params["key"] == YT_KEY and request.url.params["part"] == "id"
    usage = quota.usage()
    assert usage["default"]["units"] == 1 and usage["default"]["by_purpose"] == {"discovery": 1}
    assert usage["search"]["units"] == 0 and usage["uploads"]["units"] == 0
    safe_public(response.json())


def test_local_quota_denial_is_explained_without_sending_a_request(client, network):
    from clipfoundry.autopilot import quota

    quota.mark_exhausted("videos.list")
    response = client.post("/api/integrations/search/youtube/test", headers=H)
    assert response.status_code == 200
    assert not response.json()["ok"] and response.json()["status"] == "quota"
    assert response.json()["until"] == pytest.approx(quota.next_reset())
    assert not network.requests and quota.usage()["default"]["units"] == 0


def test_tavily_uses_only_get_usage_with_bearer_and_does_not_spend_search_credits(client, network):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, search_connections, state

    month = providers.month_key()
    state.put(f"cost:tavily:{month}", 1000)
    before = state.get(f"cost:tavily:{month}")
    network.handler = lambda request: httpx.Response(200, json=USAGE)
    response = client.post("/api/integrations/search/tavily/test", headers=H)
    assert response.status_code == 200 and response.json()["ok"]
    request, = network.requests
    assert request.method == "GET" and str(request.url) == search_connections.TAVILY_USAGE_URL
    assert request.headers["Authorization"] == f"Bearer {WEB_KEY}" and request.content == b""
    assert state.get(f"cost:tavily:{month}") == before
    assert providers.web_usage(db.get_settings())["allowed"] == 0
    safe_public(response.json())


@pytest.mark.parametrize("status", [401, 403, 402, 429, 432, 433, 500])
def test_tavily_auth_quota_account_and_server_errors_never_save_reflected_responses(client, network, status):
    from clipfoundry.autopilot import state

    network.handler = lambda request: httpx.Response(status, json={"detail": WEB_KEY, "debug": YT_KEY})
    response = client.post("/api/integrations/search/tavily/test", headers=H)
    assert response.status_code == 200 and not response.json()["ok"]
    safe_public(response.json())
    record = state.get("search:check:tavily")
    assert WEB_KEY not in json.dumps(record) and YT_KEY not in json.dumps(record)


@pytest.mark.parametrize("answer", [[], {}, {"key": {}, "account": {}},
                                    {**USAGE, "key": {"usage": True}},
                                    {**USAGE, "key": {"usage": -1}},
                                    {**USAGE, "account": {**USAGE["account"], "current_plan": ""}}])
def test_tavily_malformed_usage_cannot_be_a_success(client, network, answer):
    network.handler = lambda request: httpx.Response(200, json=answer)
    response = client.post("/api/integrations/search/tavily/test", headers=H)
    assert response.status_code == 200 and not response.json()["ok"]
    assert response.json()["code"] == "network_or_response"


@pytest.mark.parametrize("provider", ["youtube", "tavily"])
def test_network_failure_does_not_expose_request_or_exception_text(client, network, provider):
    from clipfoundry.autopilot import state

    def fail(request):
        raise httpx.ReadError(f"sensitive network diagnostics {YT_KEY} {WEB_KEY}", request=request)

    network.handler = fail
    response = client.post(f"/api/integrations/search/{provider}/test", headers=H)
    assert response.status_code == 200 and not response.json()["ok"]
    safe_public(response.json())
    record = state.get(f"search:check:{provider}")
    assert YT_KEY not in json.dumps(record) and WEB_KEY not in json.dumps(record)


def test_oauth_error_description_cannot_leak_client_secret_into_result_or_saved_state(client, network):
    from clipfoundry.autopilot import state

    oauth(expired=True)
    marker = "synthetic-client-secret"
    network.handler = lambda request: httpx.Response(400, json={
        "error": "unexpected", "error_description": f"provider reflected {marker}"})
    response = client.post("/api/integrations/search/youtube/test", headers=H)
    assert response.status_code == 200 and not response.json()["ok"]
    assert marker not in response.text and marker not in json.dumps(state.get("search:check:youtube"))
    assert network.requests[0].url.path.endswith("/token")


@pytest.mark.parametrize("provider", ["youtube", "tavily"])
def test_retry_after_survives_reopen_and_key_replacement_without_early_requests(data, network, provider):
    from clipfoundry import db
    from clipfoundry.autopilot import providers, search_connections, state

    started = time.time()
    network.handler = lambda request: httpx.Response(429, headers={"Retry-After": "7200"},
                                                    json={"detail": "too many requests"})
    first = search_connections.test(provider)
    assert not first["ok"] and first["until"] >= started + 7200
    which = "youtube" if provider == "youtube" else "web"
    until = providers.wait_until(which)
    assert until >= started + 7200
    immediate = search_connections.test(provider)
    assert immediate["code"] == "provider_wait" and immediate["until"] == until
    assert len(network.requests) == 1  # Never display the shorter local cooldown as the service's wait.
    db.init()
    db.save_settings({f"{provider}_api_key": "synthetic-new-key"})
    second = search_connections.test(provider)
    assert second["code"] == "provider_wait" and second["until"] == until
    assert len(network.requests) == 1 and providers.wait_until(which) == until
    assert state.get(f"search:check:{provider}")["at"] == first["at"]


def test_legacy_tavily_wait_is_respected_without_writing_or_sending_a_request(data, network):
    from clipfoundry.autopilot import search_connections, state

    until = time.time() + 20000
    state.put("web:wait_until", until)
    before = dump()
    result = search_connections.test("tavily")
    assert result["code"] == "provider_wait" and result["until"] == until
    assert not network.requests and dump() == before


def test_recent_check_cooldown_does_not_reuse_success_or_extend_the_wait(data, network, monkeypatch):
    from clipfoundry.autopilot import search_connections

    now = time.time()
    monkeypatch.setattr(search_connections.time, "time", lambda: now)
    network.handler = lambda request: httpx.Response(200, json=USAGE)
    first = search_connections.test("tavily")
    assert first["ok"]
    second = search_connections.test("tavily")
    assert not second["ok"] and second["code"] == "check_cooldown"
    assert second["until"] == now + 30 and len(network.requests) == 1
    now += 31
    assert search_connections.test("tavily")["ok"] and len(network.requests) == 2


def test_overlapping_checks_send_one_request_and_the_other_reports_running(data, network):
    from clipfoundry.autopilot import search_connections

    entered, release = threading.Event(), threading.Event()
    results, errors = [], []

    def response(request):
        entered.set()
        assert release.wait(10)
        return httpx.Response(200, json=USAGE)

    def check():
        try:
            results.append(search_connections.test("tavily"))
        except Exception as exc:
            errors.append(exc)

    network.handler = response
    thread = threading.Thread(target=check)
    thread.start()
    try:
        assert entered.wait(10)
        second = search_connections.test("tavily")
        assert second["code"] == "check_running" and not second["ok"]
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    assert len(results) == 1 and results[0]["ok"] and len(network.requests) == 1


@pytest.mark.parametrize("change", ["key", "account", "client_secret"])
def test_replaced_credential_invalidates_old_result_and_can_be_checked_without_old_cooldown(data, network, change):
    from clipfoundry import db
    from clipfoundry.autopilot import search_connections

    if change != "key":
        oauth()
    network.handler = lambda request: httpx.Response(200, json=YT_ANSWER)
    assert search_connections.test("youtube")["ok"]
    if change == "key":
        db.save_settings({"youtube_api_key": "synthetic-new-search-key"})
    elif change == "account":
        db.save_account("youtube", account_id="UCdifferent-synthetic")
    else:
        db.save_settings({"youtube_client_secret": "synthetic-new-client-secret"})
    before = dump()
    shown = search_connections.view()["youtube"]["last_check"]
    assert shown["current"] is False and dump() == before
    safe_public(shown)
    assert search_connections.test("youtube")["ok"] and len(network.requests) == 2


def test_normal_oauth_token_refresh_keeps_the_test_identity_current(client, network):
    from clipfoundry.autopilot import search_connections

    oauth(expired=True)

    def answer(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic-refreshed-access", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer synthetic-refreshed-access"
        return httpx.Response(200, json=YT_ANSWER)

    network.handler = answer
    response = client.post("/api/integrations/search/youtube/test", headers=H)
    assert response.status_code == 200 and response.json()["ok"] and response.json()["current"]
    assert search_connections.view()["youtube"]["last_check"]["current"]
    assert len(network.requests) == 2


def test_credential_changed_during_the_probe_is_immediately_marked_stale(data, network):
    from clipfoundry import db
    from clipfoundry.autopilot import search_connections

    def response(request):
        assert request.url.params["key"] == YT_KEY
        db.save_settings({"youtube_api_key": "synthetic-changed-during-request"})
        return httpx.Response(200, json=YT_ANSWER)

    network.handler = response
    result = search_connections.test("youtube")
    assert result["ok"] and result["current"] is False
    assert search_connections.view()["youtube"]["last_check"]["current"] is False
    assert len(network.requests) == 1
