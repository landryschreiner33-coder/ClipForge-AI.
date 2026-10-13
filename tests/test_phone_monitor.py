"""Phone access stays narrow, revocable and separate from the desktop application."""
from __future__ import annotations

import json
import socket
import time
import datetime as dt
import types
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path / "data"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def monitor(data, monkeypatch):
    from clipfoundry import phone

    manager = phone.PhoneManager()
    monkeypatch.setattr(phone, "discover_addresses", lambda: [{"mode": "wifi", "address": "192.168.50.7"}])
    start = manager._start
    # Only the throwaway loopback socket is opened. The setup route still validates a discovered private address.
    monkeypatch.setattr(manager, "_start", lambda address, port, allow_fallback:
                        start("127.0.0.1", port, allow_fallback))
    setup_app = FastAPI()
    setup_app.include_router(phone.create_setup_router(manager))
    setup = TestClient(setup_app, base_url="http://127.0.0.1:8765")
    companion = TestClient(phone.create_companion_app(manager), base_url="http://192.168.50.7:8766")
    try:
        yield manager, setup, companion
    finally:
        setup.close()
        companion.close()
        manager.stop()


def enable(monitor):
    manager, setup, companion = monitor
    response = setup.post("/api/phone-monitor/enable", headers=H,
                          json={"mode": "wifi", "address": "192.168.50.7", "port": free_port()})
    assert response.status_code == 200, response.text
    assert manager.status()["state"] == "running"
    return companion


def pair(monitor):
    _, setup, companion = monitor
    packet = setup.post("/api/phone-monitor/pairing", headers=H).json()
    response = companion.post("/api/pair", json={"code": packet["code"]})
    assert response.status_code == 200, response.text
    return packet, response.json()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def database_dump():
    from clipfoundry import db

    with db.connect() as conn:
        return "\n".join(conn.iterdump())


def test_companion_is_default_off_and_static_page_has_no_status(monitor, data, monkeypatch):
    manager, setup, companion = monitor
    from clipfoundry import config, db

    static = data / "static"
    (static / "phone").mkdir(parents=True)
    for name in ("index.html", "style.css", "app.js"):
        (static / "phone" / name).write_text("phone static fixture", encoding="utf-8")
    monkeypatch.setattr(config, "FRONTEND_DIST", static)
    assert not db.get_settings()["phone_enabled"]
    assert manager.status()["state"] == "off"
    assert setup.get("/api/phone-monitor").json()["state"] == "off"
    assert setup.post("/api/phone-monitor/pairing", headers=H).status_code >= 400
    for path in ("/", "/style.css", "/app.js"):
        response = companion.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert companion.get("/api/status").status_code == 401


def test_pairing_is_short_lived_single_use_and_stores_only_token_hash(monitor):
    from clipfoundry import db

    enable(monitor)
    packet, device = pair(monitor)
    _, _, companion = monitor
    assert len(packet["code"]) == 8 and packet["code"].isascii() and packet["code"].isdigit()
    assert 0 < packet["expires_at"] - time.time() <= 5 * 60
    assert "?" not in packet["address"] and "#" not in packet["address"]
    assert len(device["token"]) >= 32
    assert 89 * 86400 < device["expires_at"] - time.time() <= 90 * 86400
    assert companion.get("/api/status", headers=bearer(device["token"])).status_code == 200
    assert companion.post("/api/pair", json={"code": packet["code"]}).status_code in (401, 403)
    rows = db.select("phone_devices")
    assert len(rows) == 1
    assert device["token"] not in json.dumps(rows)
    assert packet["code"] not in json.dumps(rows)
    assert device["token"] not in database_dump()


def test_pairing_and_device_tokens_expire(monitor, monkeypatch):
    from clipfoundry import phone

    enable(monitor)
    _, device = pair(monitor)
    _, setup, companion = monitor
    packet = setup.post("/api/phone-monitor/pairing", headers=H).json()
    now = time.time()
    monkeypatch.setattr(phone.time, "time", lambda: now + 5 * 60 + 1)
    assert companion.post("/api/pair", json={"code": packet["code"]}).status_code in (401, 403)
    assert companion.get("/api/status", headers=bearer(device["token"])).status_code == 200
    monkeypatch.setattr(phone.time, "time", lambda: device["expires_at"] + 1)
    assert companion.get("/api/status", headers=bearer(device["token"])).status_code == 401


def test_old_pairing_code_is_replaced_and_invalid_attempts_are_limited(monitor):
    enable(monitor)
    _, setup, companion = monitor
    old = setup.post("/api/phone-monitor/pairing", headers=H).json()["code"]
    current = setup.post("/api/phone-monitor/pairing", headers=H).json()["code"]
    assert old != current
    assert companion.post("/api/pair", json={"code": old}).status_code in (401, 403)
    wrong = "00000000" if current != "00000000" else "11111111"
    statuses = [companion.post("/api/pair", json={"code": wrong}).status_code for _ in range(20)]
    assert 429 in statuses
    assert statuses[-1] == 429
    assert companion.post("/api/pair", json={"code": current}).status_code == 429


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", "Basic private", "Bearer " + "x" * 10000])
def test_status_requires_a_bounded_bearer_header(monitor, authorization):
    enable(monitor)
    _, _, companion = monitor
    response = companion.get("/api/status", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert "private" not in response.text and "wrong" not in response.text and "x" * 100 not in response.text


def test_credentials_in_urls_do_not_authenticate_and_no_cors_is_granted(monitor):
    enable(monitor)
    _, device = pair(monitor)
    _, _, companion = monitor
    assert companion.get("/api/status", params={"token": device["token"]}).status_code == 401
    response = companion.get("/api/status", headers={**bearer(device["token"]), "Origin": "https://untrusted.test"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    response = companion.options("/api/status", headers={"Origin": "https://untrusted.test",
                                                        "Access-Control-Request-Headers": "authorization"})
    assert "access-control-allow-origin" not in response.headers


def test_revoke_invalidates_existing_devices_and_pending_pairing(monitor):
    from clipfoundry import db

    enable(monitor)
    _, first = pair(monitor)
    _, second = pair(monitor)
    _, setup, companion = monitor
    code = setup.post("/api/phone-monitor/pairing", headers=H).json()["code"]
    assert setup.post("/api/phone-monitor/revoke", headers=H).status_code == 200
    for device in (first, second):
        assert companion.get("/api/status", headers=bearer(device["token"])).status_code == 401
    assert companion.post("/api/pair", json={"code": code}).status_code in (401, 403)
    assert db.select("phone_devices") == []
    _, replacement = pair(monitor)
    assert companion.get("/api/status", headers=bearer(replacement["token"])).status_code == 200


def test_disable_closes_listener_and_rejects_authenticated_status(monitor):
    from clipfoundry import db

    enable(monitor)
    _, device = pair(monitor)
    manager, setup, companion = monitor
    assert setup.post("/api/phone-monitor/disable", headers=H).status_code == 200
    assert manager.status()["state"] == "off"
    assert not db.get_settings()["phone_enabled"]
    assert companion.get("/api/status", headers=bearer(device["token"])).status_code == 401
    assert setup.post("/api/phone-monitor/pairing", headers=H).status_code >= 400


@pytest.mark.parametrize("method,path", [
    ("get", "/api/settings"), ("put", "/api/settings"), ("get", "/api/projects"),
    ("post", "/api/autopilot/start"), ("post", "/api/autopilot/pause"),
    ("get", "/api/publish/youtube"), ("post", "/api/publish/youtube/disconnect"),
    ("get", "/api/oauth/youtube/callback"), ("get", "/api/clips/private/video"),
    ("get", "/api/brain"), ("get", "/api/office"), ("get", "/api/phone-monitor"),
    ("get", "/openapi.json"), ("get", "/docs"), ("get", "/redoc"),
    ("get", "/assets/desktop.js"), ("get", "/legal/privacy.html"),
])
def test_companion_never_exposes_desktop_routes(monitor, method, path):
    enable(monitor)
    _, device = pair(monitor)
    _, _, companion = monitor
    response = companion.request(method, path, headers={**H, **bearer(device["token"])})
    assert response.status_code in (404, 405), (path, response.text)


def test_setup_mutations_require_local_app_header_and_reads_require_local_host(monitor):
    _, setup, _ = monitor
    for path in ("enable", "disable", "pairing", "revoke"):
        body = {"mode": "wifi", "address": "192.168.50.7"} if path == "enable" else None
        assert setup.post("/api/phone-monitor/" + path, json=body).status_code == 403
        assert setup.post("/api/phone-monitor/" + path, json=body,
                          headers={**H, "Host": "untrusted.test:8765"}).status_code == 403
    assert setup.get("/api/phone-monitor", headers={"Host": "192.168.50.7:8765"}).status_code == 403
    with TestClient(setup.app, base_url="http://127.0.0.1:8765", client=("192.168.50.10", 54321)) as remote:
        headers = {**H, "X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "127.0.0.1:8765"}
        assert remote.get("/api/phone-monitor", headers=headers).status_code == 403
        assert remote.post("/api/phone-monitor/enable", headers=headers,
                           json={"mode": "wifi", "address": "192.168.50.7"}).status_code == 403


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "127.0.0.1", "8.8.8.8", "example.com"])
def test_enable_rejects_wildcard_public_hostname_and_loopback_addresses(monitor, address):
    _, setup, _ = monitor
    response = setup.post("/api/phone-monitor/enable", headers=H,
                          json={"mode": "wifi", "address": address, "port": free_port()})
    assert response.status_code in (400, 422), response.text


def test_generic_settings_cannot_enable_or_reconfigure_phone(data):
    from clipfoundry import config, db
    from clipfoundry.api import put_settings

    keys = {key for key in config.DEFAULT_SETTINGS if key.startswith("phone_")}
    assert keys
    assert keys <= config.ACTION_ONLY_KEYS
    before = {key: db.get_settings()[key] for key in keys}
    patch = {key: True if isinstance(value, bool) else 9999 if isinstance(value, int) else "192.168.50.7"
             for key, value in before.items()}
    put_settings(patch)
    assert {key: db.get_settings()[key] for key in keys} == before


def test_occupied_port_failure_leaves_desktop_data_and_jobs_intact(monitor):
    from clipfoundry import db

    manager, setup, _ = monitor
    project = db.create_project("Still available")
    before_jobs = db.select("worker_jobs")
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        response = setup.post("/api/phone-monitor/enable", headers=H, json={
            "mode": "wifi", "address": "192.168.50.7", "port": occupied.getsockname()[1],
        })
        assert response.status_code == 200
        assert response.json()["state"] == "failed"
        assert response.json()["error"]
        assert not response.json()["running"]
    assert db.get_project(project["id"]) == project
    assert db.select("worker_jobs") == before_jobs
    manager.stop()
    assert manager.status()["state"] == "off"


def test_pairing_device_limit_and_normal_restart_preserve_existing_grants(monitor):
    from clipfoundry import db

    enable(monitor)
    manager, setup, companion = monitor
    grants = []
    for number in range(8):
        packet = setup.post("/api/phone-monitor/pairing", headers=H)
        assert packet.status_code == 200
        with TestClient(companion.app, base_url="http://192.168.50.7:8766",
                        client=(f"192.168.50.{number + 10}", 50000)) as other:
            response = other.post("/api/pair", json={"code": packet.json()["code"]})
        assert response.status_code == 200
        grants.append(response.json())
    assert setup.post("/api/phone-monitor/pairing", headers=H).status_code == 409
    assert len(db.select("phone_devices")) == 8
    manager.stop()
    assert companion.get("/api/status", headers=bearer(grants[0]["token"])).status_code == 401
    manager.restore()
    assert manager.status()["state"] == "running"
    assert companion.get("/api/status", headers=bearer(grants[0]["token"])).status_code == 200


def test_unexpected_optional_listener_failure_does_not_break_desktop_state(monitor, monkeypatch):
    from clipfoundry import db

    manager, setup, _ = monitor
    project = db.create_project("Desktop work survives")

    def broken_listener(*args, **kwargs):
        raise RuntimeError("synthetic-private-listener-diagnostic")

    monkeypatch.setattr(manager, "_start", broken_listener)
    response = setup.post("/api/phone-monitor/enable", headers=H,
                          json={"mode": "wifi", "address": "192.168.50.7", "port": free_port()})
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert "synthetic-private-listener-diagnostic" not in response.text
    assert db.get_project(project["id"]) == project
    assert setup.post("/api/phone-monitor/disable", headers=H).status_code == 200
    assert manager.status()["state"] == "off"


def test_restore_does_not_bind_the_custom_desktop_port(data, monkeypatch):
    from clipfoundry import db, phone

    monkeypatch.setenv("CLIPFOUNDRY_PORT", "8999")
    monkeypatch.setattr(phone, "discover_addresses", lambda: [{"mode": "wifi", "address": "192.168.50.7"}])
    manager = phone.PhoneManager()
    db.save_settings({"phone_enabled": True, "phone_mode": "wifi", "phone_address": "192.168.50.7",
                      "phone_port": 8999})

    def forbidden_bind(*args, **kwargs):
        pytest.fail("Restoring the companion attempted to take the desktop port")

    monkeypatch.setattr(manager, "_start", forbidden_bind)
    manager.restore()
    assert manager.status()["state"] == "failed"
    assert not manager.running


@pytest.mark.parametrize("body", [
    {"code": "1234567"}, {"code": "123456789"}, {"code": "１２３４５６７８"},
    {"code": "12345678", "token": "synthetic-sensitive-input"}, {"code": "secret-sensitive-input"},
])
def test_invalid_pairing_input_is_bounded_and_never_echoed(monitor, body):
    enable(monitor)
    _, _, companion = monitor
    response = companion.post("/api/pair", json=body)
    assert response.status_code == 422
    assert body["code"] not in response.text
    assert "synthetic-sensitive-input" not in response.text


def test_companion_lifespan_never_starts_desktop_workers(monitor, monkeypatch):
    from clipfoundry.autopilot import host
    from clipfoundry.jobs import worker
    from clipfoundry.publish import jobs

    def unexpected_start():
        raise AssertionError("The companion started a desktop worker")

    monkeypatch.setattr(worker, "start", unexpected_start)
    monkeypatch.setattr(jobs.worker, "start", unexpected_start)
    monkeypatch.setattr(host.supervisor, "start", unexpected_start)
    with TestClient(monitor[2].app) as companion:
        assert companion.get("/api/status").status_code == 401


def test_snapshot_omits_secrets_accounts_paths_and_raw_diagnostics(data, monkeypatch):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import queue, state
    from clipfoundry.office import health

    secret = "synthetic-secret-marker"
    account = "synthetic-account-marker"
    path = "/private/synthetic-path-marker/recording.mp4"
    url = "https://example.invalid/synthetic-url-marker?access_token=" + secret
    diagnostic = "synthetic-diagnostic-marker " + path + " " + url
    db.save_settings({"autopilot_enabled": True, "openai_api_key": secret, "ffmpeg_path": path})
    db.save_account("youtube", tokens={"access_token": secret}, account_id=account, display_name=account,
                    scopes=[account], avatar_url=url, info={"error": diagnostic})
    project = db.create_project("A useful video", source_path=path, source_url=url, error=diagnostic)
    clip = db.create_clip(project["id"], start=0, end=20, title="Clip " + path + " " + url,
                          output_path=path, error=diagnostic)
    job = queue.enqueue("analyze_source", {"project_id": project["id"], "secret": secret},
                        ref=("clip", clip["id"]))
    db.update("worker_jobs", job["id"], status="running", progress=0.25, message=diagnostic, error=diagnostic)
    now = time.time()
    state.put("host_heartbeat", {"at": now, "pid": 12345, "account": account})
    state.action("private-fixture", "gpu", diagnostic, detail=diagnostic, fix=diagnostic)
    db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube",
                                         "title": "Upcoming " + url, "planned_at": now + 60,
                                         "status": "awaiting_approval", "last_error": diagnostic, "fix": diagnostic,
                                         "description": secret, "options": {"account": account}})
    monkeypatch.setattr(health, "check", lambda settings: {
        "status": "error", "label": "Error", "checked_at": now, "headline": diagnostic, "action": diagnostic,
        "checks": [{"id": "gpu", "label": "GPU (CUDA)", "status": "error", "checked_at": now,
                    "reason": diagnostic, "action": diagnostic, "name": account}],
    })
    snapshot = phone.status_snapshot()
    payload = json.dumps(snapshot)
    for marker in (secret, account, "synthetic-path-marker", "synthetic-url-marker", "synthetic-diagnostic-marker"):
        assert marker not in payload
    assert set(snapshot) == {"version", "server_time", "timezone", "run", "workers", "currently", "working",
                             "today", "posts", "next_post", "health", "health_checks", "needs_you", "desktop_note"}
    assert set(snapshot["run"]) == {"state", "label", "publishing_paused"}
    assert set(snapshot["workers"]) == {"alive", "heartbeat_at"}
    assert set(snapshot["working"]) == {"title", "step", "progress"}
    assert snapshot["working"]["progress"] == 0.25
    assert set(snapshot["next_post"]) == {"platform", "title", "planned_at", "status"}
    assert set(snapshot["health_checks"][0]) == {"id", "label", "status", "checked_at"}
    assert snapshot["needs_you"] and all(set(row) == {"kind", "title"} for row in snapshot["needs_you"])


def test_repeated_snapshots_are_read_only_without_network_or_folder_scan(data, monkeypatch):
    import httpx
    import urllib.request

    from clipfoundry import phone
    from clipfoundry.autopilot import home, myvideos, routes

    def forbidden(*args, **kwargs):
        raise AssertionError("Phone snapshots must not request a complete status, scan videos or contact a service")

    monkeypatch.setattr(home, "view", forbidden)
    monkeypatch.setattr(myvideos, "view", forbidden)
    monkeypatch.setattr(routes, "status", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    before = database_dump()
    for _ in range(3):
        snapshot = phone.status_snapshot()
        assert snapshot["run"]["state"] == "stopped"
        assert snapshot["working"] is None
        assert database_dump() == before


@pytest.mark.parametrize("day,hours", [(dt.date(2026, 3, 8), 23), (dt.date(2026, 11, 1), 25)])
def test_today_counts_unique_clips_platform_posts_and_local_dst_day(data, monkeypatch, day, hours):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import scout

    zone = ZoneInfo("America/Chicago")
    now = dt.datetime.combine(day, dt.time(12), zone).timestamp()
    monkeypatch.setattr(phone, "time", types.SimpleNamespace(time=lambda: now))
    settings = db.save_settings({"autopilot_timezone": "America/Chicago"})
    start, end = scout.day_bounds(settings, now)
    assert (end - start) / 3600 == hours
    project = db.create_project("Automatic", origin="autopilot")
    posted = db.create_clip(project["id"], start=0, end=20, title="Posted", status="ready", created_at=start + 1)
    later = db.create_clip(project["id"], start=0, end=20, title="Later", status="ready", created_at=start + 1)
    db.create_clip(project["id"], start=0, end=20, title="Yesterday", status="ready", created_at=start - 1)
    rows = [(posted, "youtube", start, "published"), (posted, "tiktok", now - 1, "published"),
            (later, "youtube", now + 60, "approved"), (later, "tiktok", now + 120, "awaiting_approval"),
            (later, "youtube", start - 1, "published"), (later, "tiktok", end, "awaiting_approval")]
    for clip, platform, planned_at, status in rows:
        db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": platform,
                                             "planned_at": planned_at, "status": status, "title": clip["title"]})
    today = phone.status_snapshot()["today"]
    assert {key: today[key] for key in ("published", "scheduled", "published_posts", "scheduled_posts")} == {
        "published": 1, "scheduled": 1, "published_posts": 2, "scheduled_posts": 2,
    }
    assert today["processed"] == 2


@pytest.mark.parametrize("progress,expected", [(0, None), (0.375, 0.375)])
def test_snapshot_progress_is_measured_or_null(data, progress, expected):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import queue

    db.save_settings({"autopilot_enabled": True})
    project = db.create_project("Measured video")
    clip = db.create_clip(project["id"], start=0, end=20, title="Measured clip")
    job = queue.enqueue("analyze_source", ref=("clip", clip["id"]))
    db.update("worker_jobs", job["id"], status="running", progress=progress)
    assert phone.status_snapshot()["working"]["progress"] == expected


def test_snapshot_ignores_automatic_retry_actions_that_do_not_need_the_owner(data):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import home, state

    db.save_settings({"autopilot_enabled": True})
    state.put("host_heartbeat", {"at": time.time()})
    for kind in home.QUIET_KINDS:
        state.action("automatic:" + kind, kind, "synthetic-private-action-title",
                     detail="synthetic-private-action-detail", fix="synthetic-private-action-fix")
    assert len(state.open_actions()) == len(home.QUIET_KINDS)
    before = database_dump()
    snapshot = phone.status_snapshot()
    assert snapshot["needs_you"] == []
    assert "synthetic-private-action" not in json.dumps(snapshot)
    assert database_dump() == before


def test_snapshot_derives_stopped_background_work_and_clears_when_it_recovers(data, monkeypatch):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import home, state

    now = time.time()
    db.save_settings({"autopilot_enabled": True})
    state.put("setup:started", now - 300)
    state.put("host_heartbeat", {"at": now - 300})
    monkeypatch.setattr(home, "BOOT", now - 600)
    assert state.open_actions() == []
    before = database_dump()
    assert phone.status_snapshot()["needs_you"] == [
        {"kind": "stopped", "title": "Background work needs attention"},
    ]
    assert database_dump() == before
    state.put("host_heartbeat", {"at": time.time()})
    assert phone.status_snapshot()["needs_you"] == []


def test_snapshot_derives_account_reconnect_without_exporting_account_details(data):
    from clipfoundry import db, phone
    from clipfoundry.autopilot import state

    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True})
    state.put("host_heartbeat", {"at": time.time()})
    db.save_account("youtube", tokens={"access_token": "synthetic-private-account-token"},
                    account_id="synthetic-private-account-id", display_name="synthetic-private-account-name",
                    info={"needs_reconnect": True, "error": "synthetic-private-account-error"})
    assert state.open_actions() == []
    before = database_dump()
    snapshot = phone.status_snapshot()
    assert snapshot["needs_you"] == [{"kind": "account", "title": "An account needs attention"}]
    assert "synthetic-private-account" not in json.dumps(snapshot)
    assert database_dump() == before
    db.save_account("youtube", info={"needs_reconnect": False})
    assert phone.status_snapshot()["needs_you"] == []


def test_snapshot_derives_failed_keep_awake_without_exporting_the_raw_error(data, monkeypatch):
    from clipfoundry import awake, db, phone
    from clipfoundry.autopilot import state

    db.save_settings({"autopilot_enabled": True, "autopilot_keep_awake": True})
    state.put("host_heartbeat", {"at": time.time()})
    keeper = awake.KeepAwake()
    keeper.supported = True
    keeper.error = "synthetic-private-sleep-error /private/sleep-diagnostic"
    monkeypatch.setattr(awake, "keeper", keeper)
    assert state.open_actions() == []
    before = database_dump()
    snapshot = phone.status_snapshot()
    assert snapshot["needs_you"] == [{"kind": "sleep", "title": "PC sleep settings need attention"}]
    assert "synthetic-private-sleep-error" not in json.dumps(snapshot)
    assert "/private/sleep-diagnostic" not in json.dumps(snapshot)
    assert database_dump() == before
    keeper.error = ""
    keeper.holding = True
    assert phone.status_snapshot()["needs_you"] == []
