"""YouTube Shorts publishing against a local stand-in for Google's OAuth and YouTube Data API servers."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.requests import Request

from clipfoundry import config
from fake_platforms import FakeGoogle

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def google(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry.publish import jobs, youtube

    fake = FakeGoogle()
    monkeypatch.setattr(youtube, "AUTH_URL", f"{fake.url}/o/oauth2/v2/auth")
    monkeypatch.setattr(youtube, "TOKEN_URL", f"{fake.url}/token")
    monkeypatch.setattr(youtube, "REVOKE_URL", f"{fake.url}/revoke")
    monkeypatch.setattr(youtube, "API_URL", f"{fake.url}/youtube/v3")
    monkeypatch.setattr(youtube, "UPLOAD_URL", f"{fake.url}/upload/youtube/v3/videos")
    monkeypatch.setattr(youtube, "CHUNK", 256 * 1024)
    real_upload = youtube.upload
    monkeypatch.setattr(youtube, "upload", lambda *a, **k: real_upload(*a, **{**k, "sleep": lambda s: None}))
    jobs.worker.cancelled.clear()
    yield fake
    fake.stop()


@pytest.fixture()
def app_client(google):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


@pytest.fixture()
def clip(app_client, tmp_path):
    from clipfoundry import db

    video = tmp_path / "clip.mp4"
    video.write_bytes(os.urandom(700_000))  # three chunks of 256 KiB
    project = db.create_project("talk", source_path=str(tmp_path / "source.mp4"), status="ready")
    c = db.create_clip(project["id"], start=0, end=20, title="Why do most diets fail?", status="ready",
                       output_path=str(video), score=88.0, duration=20.0,
                       analysis={"subscores": {"hook": 80}, "factors": {"hook": 8.0}, "structure": {"label": "x"}})
    return c, video.read_bytes()


def _setup(client) -> None:
    r = client.put("/api/settings", json={"youtube_client_id": "cid.apps.googleusercontent.com",
                                          "youtube_client_secret": "csecret"})
    assert r.json()["youtube_client_secret"] == "********"


def _connect(client, google) -> dict:
    _setup(client)
    auth_url = client.post("/api/publish/youtube/connect", headers=H).json()["auth_url"]
    q = parse_qs(urlparse(auth_url).query)
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/api/oauth/youtube/callback"]
    assert q["access_type"] == ["offline"] and q["client_id"] == ["cid.apps.googleusercontent.com"]
    assert "https://www.googleapis.com/auth/youtube.upload" in q["scope"][0].split()
    page = client.get("/api/oauth/youtube/callback", params={"state": q["state"][0], "code": google.approve(auth_url)})
    assert page.status_code == 200 and "YouTube connected" in page.text and "Test Channel" in page.text
    return q


def _wait(client, pub_id: str, until=("done", "failed", "cancelled"), timeout: float = 20) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/publications/{pub_id}").json()
        if p["status"] in until:
            return p
        time.sleep(0.05)
    raise AssertionError(f"publication stuck: {p}")


def _publish(client, clip_id: str, **kw) -> dict:
    body = {"title": "Why do most diets fail?", "description": "Because willpower is a terrible strategy.\n\n#diets",
            "tags": ["#diets", "#willpower"], "privacy": "private", "made_for_kids": False, "confirm": True, **kw}
    return client.post(f"/api/clips/{clip_id}/publish/youtube", json=body, headers=H)


def test_connect_needs_setup_first(app_client):
    r = app_client.post("/api/publish/youtube/connect", headers=H)
    assert r.status_code == 400 and "Desktop app" in r.json()["fix"]
    assert app_client.get("/api/publish/accounts").json()["youtube"]["configured"] is False


def test_oauth_connect_shows_channel_and_never_stores_plain_tokens(app_client, google):
    _connect(app_client, google)
    yt = app_client.get("/api/publish/accounts").json()["youtube"]
    assert yt["connected"] and yt["name"] == "Test Channel" and yt["analytics"]
    assert "Private" in yt["restriction"]  # unverified API project: explained before any upload
    assert google.grants == ["authorization_code"]
    raw = (config.db_path()).read_bytes() + b"".join(p.read_bytes() for p in config.data_dir().glob("*.db-wal"))
    assert google.access.encode() not in raw and google.refresh_token.encode() not in raw  # tokens are sealed
    assert b"csecret" not in raw
    conn = sqlite3.connect(config.db_path())
    stored = conn.execute("SELECT value FROM settings WHERE key = 'youtube_client_secret'").fetchone()[0]
    assert json.loads(stored).startswith(("local:", "dpapi:"))


def test_callback_rejects_unknown_state_and_denied_access(app_client, google):
    _setup(app_client)
    page = app_client.get("/api/oauth/youtube/callback", params={"state": "forged", "code": "x"})
    assert "not connected" in page.text and "not valid" in page.text
    page = app_client.get("/api/oauth/youtube/callback", params={"error": "access_denied"})
    assert "declined access" in page.text
    assert not app_client.get("/api/publish/accounts").json()["youtube"]["connected"]


def test_upload_is_resumable_and_reports_the_video(app_client, google, clip):
    c, data = clip
    _connect(app_client, google)
    google.fail_puts = 1  # one chunk fails with 503: the upload asks for the offset and resumes
    r = _publish(app_client, c["id"])
    assert r.status_code == 200, r.text
    pub = _wait(app_client, r.json()["id"])
    assert pub["status"] == "done" and pub["progress"] == 1.0, pub
    video = google.videos[pub["remote_id"]]
    assert video["bytes"] == data
    assert video["snippet"] == {"title": "Why do most diets fail?", "categoryId": "22", "tags": ["diets", "willpower"],
                                "description": "Because willpower is a terrible strategy.\n\n#diets"}
    assert video["status"]["selfDeclaredMadeForKids"] is False
    assert pub["privacy"] == "private" and pub["url"] == f"https://www.youtube.com/shorts/{pub['remote_id']}"
    assert pub["features"]["viral_potential"] == 88.0  # snapshot kept for comparing with real performance later
    assert sum(1 for m, p in google.log if m == "PUT" and "upload-session" in p) >= 4


def test_a_rate_limited_upload_waits_as_long_as_youtube_asks(app_client, google, clip, monkeypatch):
    from clipfoundry.publish import youtube

    asked: list = []
    real = youtube._pause
    monkeypatch.setattr(youtube, "_pause", lambda a, backoff, sleep, cancelled: (asked.append(a),
                                                                                 real(a, backoff, sleep, cancelled)))
    c, data = clip
    _connect(app_client, google)
    google.rate_limit_puts, google.retry_after = 1, "7"
    pub = _wait(app_client, _publish(app_client, c["id"]).json()["id"])
    assert pub["status"] == "done" and google.videos[pub["remote_id"]]["bytes"] == data
    assert asked == [7.0] and len(google.videos) == 1  # YouTube's own wait, then the same session continued


def test_retry_after_is_read_in_both_forms():
    from email.utils import formatdate

    import httpx

    from clipfoundry.publish.common import MAX_RETRY_AFTER, retry_after

    def answer(value):
        return httpx.Response(429, headers={"Retry-After": value} if value is not None else {})

    assert retry_after(answer("120")) == 120.0
    assert abs(retry_after(answer(formatdate(1_000_090, usegmt=True)), now=1_000_000) - 90) < 1e-6
    assert retry_after(answer(formatdate(999_000, usegmt=True)), now=1_000_000) == 0.0  # already past: go now
    assert retry_after(answer("-5")) == 0.0 and retry_after(answer("999999999")) == MAX_RETRY_AFTER
    for nothing in (None, "", "soon", "nan", "inf"):
        assert retry_after(answer(nothing)) is None, nothing
    assert retry_after(None) is None


def test_upload_pauses_are_bounded_and_can_be_stopped():
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import Cancelled

    slept: list[float] = []
    youtube._pause(12.0, 2.0, slept.append, lambda: False)
    assert sum(slept) == 12.0 and max(slept) <= 5.0  # short steps: stopping is never held up for long
    slept.clear()
    youtube._pause(None, 2.0, slept.append, lambda: False)
    assert slept == [2.0]  # no Retry-After: the usual backoff
    slept.clear()
    youtube._pause(86400.0, 2.0, slept.append, lambda: False)
    assert sum(slept) == youtube.UPLOAD_PAUSE_MAX
    slept.clear()
    with pytest.raises(Cancelled):
        youtube._pause(30.0, 2.0, slept.append, lambda: len(slept) >= 2)
    assert sum(slept) == 10.0


def test_unverified_project_lock_is_explained(app_client, google, clip):
    c, _ = clip
    _connect(app_client, google)
    google.lock_private = True
    pub = _wait(app_client, _publish(app_client, c["id"], privacy="public").json()["id"])
    assert pub["status"] == "done" and pub["requested_privacy"] == "public" and pub["privacy"] == "private"
    assert pub["info"]["locked_private"] and "audit" in pub["message"]


def test_explicit_confirmation_and_required_fields(app_client, google, clip):
    c, _ = clip
    _connect(app_client, google)
    assert "confirmation" in _publish(app_client, c["id"], confirm=False).json()["detail"]
    assert "made for kids" in _publish(app_client, c["id"], made_for_kids=None).json()["detail"]
    assert "100 characters" in _publish(app_client, c["id"], title="x" * 101).json()["detail"]
    assert "Public, Unlisted or Private" in _publish(app_client, c["id"], privacy="friends").json()["detail"]
    assert not google.sessions  # nothing reached YouTube


def test_expired_access_token_is_refreshed(app_client, google, clip):
    from clipfoundry import db

    c, _ = clip
    _connect(app_client, google)
    tokens = db.account_tokens("youtube")
    db.save_account("youtube", tokens={**tokens, "expires_at": time.time() - 10})
    pub = _wait(app_client, _publish(app_client, c["id"]).json()["id"])
    assert pub["status"] == "done" and google.grants == ["authorization_code", "refresh_token"]


def test_revoked_access_asks_to_reconnect(app_client, google, clip):
    from clipfoundry import db

    c, _ = clip
    _connect(app_client, google)
    google.revoked = True
    db.save_account("youtube", tokens={**db.account_tokens("youtube"), "expires_at": 0})
    pub = _wait(app_client, _publish(app_client, c["id"]).json()["id"])
    assert pub["status"] == "failed" and "Connect YouTube again" in pub["fix"] and "7 days" in pub["fix"]
    assert app_client.get("/api/publish/accounts").json()["youtube"]["needs_reconnect"]


def test_quota_exceeded_is_explained(app_client, google, clip):
    c, _ = clip
    _connect(app_client, google)
    google.quota_exceeded = True
    pub = _wait(app_client, _publish(app_client, c["id"]).json()["id"])
    assert pub["status"] == "failed" and "quota" in pub["error"] and "Pacific" in pub["fix"]


def test_cancel_during_upload(app_client, google, clip):
    c, _ = clip
    _connect(app_client, google)
    google.chunk_delay = 0.3
    pub_id = _publish(app_client, c["id"]).json()["id"]
    _wait(app_client, pub_id, until=("uploading",))
    assert app_client.post(f"/api/clips/{c['id']}/publish/youtube", json={}, headers=H).status_code in (400, 409)
    app_client.post(f"/api/publications/{pub_id}/cancel", headers=H)
    assert _wait(app_client, pub_id)["status"] == "cancelled"
    assert not google.videos


def test_refresh_status_and_disconnect(app_client, google, clip):
    c, _ = clip
    _connect(app_client, google)
    pub = _wait(app_client, _publish(app_client, c["id"], privacy="unlisted").json()["id"])
    google.videos[pub["remote_id"]]["status"]["privacyStatus"] = "private"  # e.g. locked after processing
    pub = app_client.post(f"/api/publications/{pub['id']}/refresh", headers=H).json()
    assert pub["privacy"] == "private" and pub["info"]["locked_private"] and "audit" in pub["message"]
    app_client.post("/api/publish/youtube/disconnect", headers=H)
    assert google.revoked and not app_client.get("/api/publish/accounts").json()["youtube"]["connected"]
    assert app_client.get(f"/api/clips/{c['id']}/publications").json()[0]["id"] == pub["id"]  # history is kept


def test_publishing_only_from_this_computer_and_this_page(app_client):
    from fastapi import HTTPException

    from clipfoundry.publish.common import app_request, local_only

    assert app_client.post("/api/publish/youtube/disconnect").status_code == 403  # no X-ClipFoundry header

    def req(client_host: str, host: str, header: bool = True) -> Request:
        headers = [(b"host", host.encode())] + ([(b"x-clipfoundry", b"1")] if header else [])
        return Request({"type": "http", "method": "POST", "path": "/", "headers": headers,
                        "client": (client_host, 5000), "query_string": b""})

    for client_host, host in [("192.168.1.20", "192.168.1.5:8765"), ("127.0.0.1", "evil.example:8765")]:
        with pytest.raises(HTTPException) as err:
            local_only(req(client_host, host))
        assert err.value.status_code == 403
    local_only(req("127.0.0.1", "127.0.0.1:8765"))
    local_only(req("::1", "localhost:8765"))
    with pytest.raises(HTTPException):
        app_request(req("127.0.0.1", "127.0.0.1:8765", header=False))


def test_secret_sealing_round_trip():
    from clipfoundry import secure

    sealed = secure.seal("token-123")
    assert sealed != "token-123" and secure.unseal(sealed) == "token-123"
    assert secure.unseal("legacy-plain") == "legacy-plain" and secure.seal("") == ""
    with pytest.raises(secure.SecretError):
        secure.unseal("dpapi:AAAA")  # encrypted by Windows for someone else
