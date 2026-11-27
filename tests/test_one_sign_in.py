"""Connect YouTube and TikTok with one sign-in: ClipForge's own app registrations (clipfoundry/publish/oauth_apps.py),
the TikTok token broker that holds TikTok's client secret (deploy/tiktok_broker/app.py, run for real here under
uvicorn), your own developer app under Advanced still winning, and what each connected account can do."""
from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeGoogle, FakeTikTok

H = {"X-ClipFoundry": "1"}
ROOT = Path(__file__).resolve().parents[1]


def _broker_module():
    spec = importlib.util.spec_from_file_location("tiktok_broker_app", ROOT / "deploy/tiktok_broker/app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tiktok_broker_app"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos"}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    yield g, t
    g.stop()
    t.stop()


@pytest.fixture()
def broker(fakes, monkeypatch):
    """The broker, really served over HTTP, with TikTok's secret in its own environment only."""
    import uvicorn

    _, t = fakes
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "tkkey")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "tksecret")
    monkeypatch.setenv("TIKTOK_API_URL", f"{t.url}/v2")
    mod = _broker_module()
    mod._seen.clear()  # noqa: SLF001
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mod.app, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", mod
    server.should_exit = True
    thread.join(5)


@pytest.fixture()
def client(fakes):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def _sign_in(client, platform: str, fake) -> dict:
    url = client.post(f"/api/connections/{platform}/add", headers=H).json()["auth_url"]
    q = parse_qs(urlparse(url).query)
    page = client.get(f"/api/oauth/{platform}/callback", params={"state": q["state"][0], "code": fake.approve(url)})
    assert page.status_code == 200 and "connected" in page.text, page.text
    return q


def test_youtube_connects_with_one_sign_in_and_no_codes_to_paste(fakes, client, monkeypatch):
    from clipfoundry import config, db

    g, _ = fakes
    assert client.get("/api/connections").json()["apps"]["youtube"]["ready"] is False
    refused = client.post("/api/connections/youtube/add", headers=H)
    assert refused.status_code == 400 and "no built-in YouTube sign-in" in refused.json()["detail"]
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_SECRET", "csecret")
    apps = client.get("/api/connections").json()["apps"]
    assert apps["youtube"] == {"ready": True, "source": "built_in",
                               "text": "One sign-in: ClipForge's own app registration."}
    q = _sign_in(client, "youtube", g)
    assert q["client_id"] == ["cid.apps.googleusercontent.com"] and q["code_challenge_method"] == ["S256"]
    rows = client.get("/api/connections").json()["connections"]
    assert [r["display_name"] for r in rows] == ["Test Channel"] and rows[0]["health"]["state"] == "ok"
    caps = {c["key"]: c["on"] for c in rows[0]["capabilities"]}
    assert caps == {"upload": True, "schedule": True, "read": True, "analytics": True}
    settings = db.get_settings()
    assert not settings.get("youtube_client_id") and not settings.get("youtube_client_secret")  # nothing pasted
    raw = config.db_path().read_bytes()
    assert b"csecret" not in raw  # the built-in registration is never written into your settings
    from clipfoundry.publish import youtube

    assert youtube.Token(db.get_settings(), rows[0]["id"]).get(force=True)  # renewed with the same registration
    assert g.grants[-1] == "refresh_token"


def test_your_own_google_app_under_advanced_wins_over_the_built_in_one(fakes, client, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import oauth_apps

    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_ID", "builtin.apps.googleusercontent.com")
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_SECRET", "builtin-secret")
    client.put("/api/settings", json={"youtube_client_id": "cid.apps.googleusercontent.com",
                                      "youtube_client_secret": "csecret"})
    assert oauth_apps.source(db.get_settings(), "youtube") == "own"
    q = _sign_in(client, "youtube", fakes[0])
    assert q["client_id"] == ["cid.apps.googleusercontent.com"]
    # one code of your own app alone never mixes with the built-in registration
    half = {"youtube_client_id": "mine.apps.googleusercontent.com", "youtube_client_secret": ""}
    assert oauth_apps.effective(half)["youtube_client_id"] == "builtin.apps.googleusercontent.com"


def test_tiktok_connects_through_the_broker_and_the_app_never_has_the_secret(fakes, broker, client, monkeypatch):
    from clipfoundry import config, db
    from clipfoundry.publish import tiktok

    _, t = fakes
    url, _mod = broker
    monkeypatch.setenv("CLIPFORGE_TIKTOK_CLIENT_KEY", "tkkey")
    monkeypatch.setenv("CLIPFORGE_TIKTOK_BROKER", url)
    assert client.get("/api/publish/accounts").json()["tiktok"]["app"] == "built_in"
    q = _sign_in(client, "tiktok", t)
    assert q["client_key"] == ["tkkey"] and q["redirect_uri"] == ["http://127.0.0.1:8765/api/oauth/tiktok/callback"]
    assert t.grants == ["authorization_code"]  # TikTok got the code with the secret, which only the broker has
    rows = client.get("/api/connections").json()["connections"]
    assert rows[0]["display_name"] == "Test Creator"
    caps = {c["key"]: c for c in rows[0]["capabilities"]}
    assert caps["direct_post"]["on"] and "Only me" in caps["direct_post"]["note"]
    assert caps["inbox"]["on"] and caps["handoff"]["on"] and "no scheduling" in caps["schedule"]["note"]
    assert "tksecret" not in str(db.get_settings()) and b"tksecret" not in config.db_path().read_bytes()
    cid = rows[0]["id"]
    tok = tiktok.Token(db.get_settings(), cid)
    assert tok.get(force=True) and t.grants[-1] == "refresh_token"  # refreshed through the broker too
    assert client.post(f"/api/connections/{cid}/disconnect", headers=H).status_code == 200
    assert t.revoked  # revoked at TikTok through the broker


def test_the_broker_refuses_anything_but_clipforges_own_sign_ins(broker):
    from starlette.testclient import TestClient

    _, mod = broker
    mod._seen.clear()  # noqa: SLF001
    c = TestClient(mod.app)
    good = {"client_key": "tkkey", "grant_type": "authorization_code", "code": "c", "code_verifier": "v" * 43,
            "redirect_uri": "http://127.0.0.1:8765/api/oauth/tiktok/callback"}
    assert c.post("/token", json={**good, "client_key": "someone-else"}).json()["error"] == "invalid_client"
    elsewhere = c.post("/token", json={**good, "redirect_uri": "https://evil.example/api/oauth/tiktok/callback"})
    assert elsewhere.status_code == 400 and elsewhere.json()["error"] == "invalid_request"
    assert c.post("/token", json={**good, "grant_type": "client_credentials"}).json()["error"] == \
        "unsupported_grant_type"
    assert c.post("/token", content=b"x" * 9000).status_code == 400  # too big
    assert c.post("/token", json={**good, "code": 5}).status_code == 400  # strings only
    assert c.get("/health").json() == {"ok": True}
    mod._seen.clear()  # noqa: SLF001
    answers = [c.post("/token", json={**good, "client_key": "x"}).status_code for _ in range(mod.PER_MINUTE + 1)]
    assert answers[-1] == 429 and set(answers[:-1]) == {400}


def test_a_broker_address_must_be_https(monkeypatch):
    from clipfoundry.publish import oauth_apps

    monkeypatch.setenv("CLIPFORGE_TIKTOK_CLIENT_KEY", "tkkey")
    for bad in ("http://broker.example.com", "ftp://broker.example.com", "not a url"):
        monkeypatch.setenv("CLIPFORGE_TIKTOK_BROKER", bad)
        assert "tiktok" not in oauth_apps.built_in()
    monkeypatch.setenv("CLIPFORGE_TIKTOK_BROKER", "https://broker.example.com/")
    assert oauth_apps.built_in()["tiktok"] == {"client_key": "tkkey", "broker": "https://broker.example.com"}


def test_a_release_build_writes_the_registration_file_without_printing_it(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("write_oauth_apps", ROOT / "scripts/write_oauth_apps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path / "oauth_apps.json")
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("CLIPFORGE_TIKTOK_CLIENT_KEY", "tkkey")
    monkeypatch.setenv("CLIPFORGE_TIKTOK_BROKER", "http://not-https.example")
    assert module.main() == 0
    out = capsys.readouterr().out
    assert "youtube" in out and "s3cret" not in out and "tiktok" not in out
    from clipfoundry.publish import oauth_apps

    monkeypatch.delenv("CLIPFORGE_YOUTUBE_CLIENT_ID")
    monkeypatch.delenv("CLIPFORGE_YOUTUBE_CLIENT_SECRET")
    monkeypatch.setattr(oauth_apps, "BUNDLED", tmp_path / "oauth_apps.json")
    assert oauth_apps.built_in()["youtube"]["client_id"] == "id.apps.googleusercontent.com"
    assert (ROOT / ".gitignore").read_text().count("clipfoundry/oauth_apps.json") == 1  # never committed


def test_a_release_without_built_in_sign_in_is_flagged_and_can_be_required(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("write_oauth_apps", ROOT / "scripts/write_oauth_apps.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path / "oauth_apps.json")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for name in ("CLIPFORGE_YOUTUBE_CLIENT_ID", "CLIPFORGE_YOUTUBE_CLIENT_SECRET", "CLIPFORGE_TIKTOK_CLIENT_KEY",
                 "CLIPFORGE_TIKTOK_BROKER"):
        monkeypatch.delenv(name, raising=False)
    assert module.main([]) == 0 and "::warning" not in capsys.readouterr().out   # a test build: no flag
    assert module.main(["--release"]) == 0
    out = capsys.readouterr().out
    assert "::warning title=No built-in sign-in::" in out and "YouTube and TikTok" in out
    assert "No built-in sign-in for YouTube and TikTok" in summary.read_text()
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("CLIPFORGE_YOUTUBE_CLIENT_SECRET", "s3cret")
    assert module.main(["--require"]) == 1   # TikTok still missing
    out = capsys.readouterr().out
    assert "::error title=No built-in sign-in::" in out and "TikTok" in out and "s3cret" not in out
    workflow = (ROOT / ".github/workflows/macos-desktop.yml").read_text()
    assert "write_oauth_apps.py ${RELEASE:+--release}" in workflow and "RELEASE: ${{ inputs.version }}" in workflow
