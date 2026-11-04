"""Cloud mode (CF-01): owner-only sign-in, sessions, CSRF, host checks, workspace isolation and encrypted secrets.

Everything runs against a fake OpenID provider with a real RSA signing key; no real account or network is used.
"""
from __future__ import annotations

import base64
import json
import os
import time

import pytest

from cloud_support import ISSUER, ORIGIN, OWNER, SECOND, cloud_env, sign_in


@pytest.fixture()
def cloud(monkeypatch, tmp_path):
    idp = cloud_env(monkeypatch, tmp_path)
    yield idp
    from clipfoundry.cloud import settings as cloud_settings

    cloud_settings.reset()


@pytest.fixture()
def owner(cloud):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url=ORIGIN) as c:
        sign_in(c, cloud)
        yield c


def _client():
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    return TestClient(app, base_url=ORIGIN)


def _project(name: str, workspace: str, tmp_path) -> dict:
    from clipfoundry import db

    folder = tmp_path / "data" / "projects" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.mp4").write_bytes(b"\x00" * 4096)
    (folder / "thumb.jpg").write_bytes(b"\xff\xd8thumb")
    p = db.create_project(name, source_path=str(folder / "source.mp4"), status="ready", workspace_id=workspace)
    clip_dir = folder / "clips"
    clip_dir.mkdir(exist_ok=True)
    (clip_dir / "c.mp4").write_bytes(b"\x00" * 2048)
    c = db.create_clip(p["id"], start=0, end=10, status="ready", output_path=str(clip_dir / "c.mp4"))
    return {"project": p, "clip": c}


# ------------------------------------------------------------------ startup refuses an unsafe configuration
def test_cloud_mode_lists_every_missing_protection(monkeypatch, tmp_path):
    from clipfoundry.cloud import settings as cloud_settings

    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    for var in ("CLIPFOUNDRY_PUBLIC_URL", "CLIPFOUNDRY_OIDC_ISSUER", "CLIPFOUNDRY_OIDC_CLIENT_ID",
                "CLIPFOUNDRY_OIDC_CLIENT_SECRET", "CLIPFOUNDRY_OWNER_SUBJECTS", "CLIPFOUNDRY_SECRET_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)
    cloud_settings.reset()
    problems = " ".join(cloud_settings.problems())
    for needed in ("PUBLIC_URL", "OIDC_ISSUER", "CLIENT_ID", "CLIENT_SECRET", "OWNER_SUBJECTS", "SECRET_KEY_FILE"):
        assert needed in problems
    monkeypatch.setenv("CLIPFOUNDRY_PUBLIC_URL", "http://studio.example.com")
    monkeypatch.setenv("CLIPFOUNDRY_OWNER_SUBJECTS", "owner@example.com")
    monkeypatch.setenv("CLIPFOUNDRY_PUBLIC_SIGNUP", "on")
    cloud_settings.reset()
    problems = " ".join(cloud_settings.problems())
    assert "https://" in problems and "email address" in problems and "sign-up must stay off" in problems
    cloud_settings.reset()


def test_app_refuses_to_start_without_its_protections(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.cloud import settings as cloud_settings

    cloud_env(monkeypatch, tmp_path)
    monkeypatch.delenv("CLIPFOUNDRY_SECRET_KEY_FILE")
    with pytest.raises(RuntimeError, match="cannot start safely"):
        with TestClient(app, base_url=ORIGIN):
            pass
    cloud_settings.reset()


def test_key_file_must_be_private_and_outside_the_data_folder(monkeypatch, tmp_path):
    from clipfoundry.cloud import settings as cloud_settings

    cloud_env(monkeypatch, tmp_path)
    key = tmp_path / "keys" / "secret.key"
    os.chmod(key, 0o644)
    assert any("chmod 600" in p for p in cloud_settings.problems())
    inside = tmp_path / "data" / "k.key"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text(key.read_text())
    os.chmod(inside, 0o600)
    monkeypatch.setenv("CLIPFOUNDRY_SECRET_KEY_FILE", str(inside))
    cloud_settings.reset()
    assert any("outside the data folder" in p for p in cloud_settings.problems())
    cloud_settings.reset()


# ------------------------------------------------------------------ sign-in
def test_owner_signs_in_and_reaches_their_data(owner, tmp_path):
    me = owner.get("/api/auth/me").json()
    assert me["signed_in"] and me["primary"] and me["workspace_id"] == "local"
    made = _project("mine", "local", tmp_path)
    assert [p["id"] for p in owner.get("/api/projects").json()] == [made["project"]["id"]]
    assert owner.get(f"/api/clips/{made['clip']['id']}/video").status_code == 200
    ranged = owner.get(f"/api/clips/{made['clip']['id']}/video", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100


def test_sign_in_returns_to_the_requested_address_only_inside_the_app(cloud):
    with _client() as c:
        r = c.get("/api/auth/login?next=%23/video/abc", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"])
        r = c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
        assert r.headers["location"] == "/#/video/abc"
    with _client() as c:
        r = c.get("/api/auth/login?next=https%3A//evil.example/", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"])
        r = c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
        assert r.headers["location"] == "/"


def test_unknown_identity_is_refused_without_a_session(cloud, tmp_path):
    _project("private-name", "local", tmp_path)
    with _client() as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"], subject="stranger-subject")
        r = c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
        assert r.status_code == 403 and "private" in r.text and "private-name" not in r.text
        assert "cf_session" not in r.headers.get("set-cookie", "")
        assert c.get("/api/projects").status_code == 401


def test_an_email_never_authorizes_and_only_the_subject_counts(cloud):
    with _client() as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"], subject="someone-else",
                                    email=f"{OWNER}@example.test")  # the owner's address, another account
        assert c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False).status_code == 403


@pytest.mark.parametrize("override, why", [
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"aud": "another-app"}, "audience"),
    ({"iss": "https://evil.test"}, "issuer"),
    ({"nonce": "replayed"}, "nonce"),
])
def test_invalid_identity_tokens_are_refused(cloud, override, why):
    with _client() as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"])
        cloud.overrides = dict(override)
        r = c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
        assert r.status_code == 400, why
        assert c.get("/api/auth/me").status_code == 401


def test_a_token_signed_by_another_key_is_refused(cloud):
    from cryptography.hazmat.primitives.asymmetric import rsa

    with _client() as c:
        r = c.get("/api/auth/login", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"])
        cloud.overrides = {"_key": rsa.generate_private_key(public_exponent=65537, key_size=2048)}
        r = c.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
        assert r.status_code == 400 and c.get("/api/auth/me").status_code == 401


def test_a_callback_from_another_browser_or_a_reused_state_fails(cloud):
    with _client() as a, _client() as b:
        r = a.get("/api/auth/login", follow_redirects=False)
        state, code = cloud.approve(r.headers["location"])
        assert b.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False).status_code == 400
        # the state was used up by that attempt: the right browser cannot replay it either
        assert a.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False).status_code == 400


# ------------------------------------------------------------------ requests
def test_everything_private_needs_a_session(cloud, tmp_path):
    made = _project("p", "local", tmp_path)
    with _client() as c:
        for path in ("/api/projects", f"/api/projects/{made['project']['id']}",
                     f"/api/projects/{made['project']['id']}/source", f"/api/clips/{made['clip']['id']}/video",
                     f"/api/clips/{made['clip']['id']}/thumbnail", "/api/settings", "/api/health",
                     "/api/autopilot/status", "/api/connections", "/api/office/snapshot"):
            r = c.get(path)
            assert r.status_code == 401, path
            assert "p" not in r.json().get("detail", "").split()  # nothing about the data
        assert c.get("/").status_code == 200  # the page shell itself holds no data
        assert c.get("/healthz").json() == {"ok": True}


def test_changes_need_the_csrf_token_and_the_own_origin(owner):
    token = owner.headers.pop("x-clipforge-csrf")
    assert owner.put("/api/settings", json={"clip_count": 3}).status_code == 403
    owner.headers["x-clipforge-csrf"] = "wrong"
    assert owner.put("/api/settings", json={"clip_count": 3}).status_code == 403
    owner.headers["x-clipforge-csrf"] = token
    assert owner.put("/api/settings", json={"clip_count": 3}, headers={"Origin": "https://evil.example"}
                     ).status_code == 403
    assert owner.put("/api/settings", json={"clip_count": 3}, headers={"Origin": ORIGIN}).status_code == 200


def test_unknown_host_is_refused(owner):
    assert owner.get("/api/projects", headers={"Host": "evil.example"}).status_code == 400


def test_security_headers_are_on_every_response(owner):
    for path in ("/", "/api/projects"):
        h = owner.get(path).headers
        assert h["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in h["content-security-policy"]
        assert "max-age" in h["strict-transport-security"] and "unsafe-eval" not in h["content-security-policy"]
    assert owner.get("/api/projects").headers["cache-control"] == "no-store"


def test_logout_and_sign_out_everywhere_end_sessions(cloud):
    with _client() as a, _client() as b:
        sign_in(a, cloud)
        sign_in(b, cloud)
        assert a.post("/api/auth/logout").json() == {"signed_in": False}
        assert a.get("/api/projects").status_code == 401 and b.get("/api/projects").status_code == 200
        sign_in(a, cloud)
        assert a.post("/api/auth/logout-all").json()["sessions_ended"] == 2
        assert a.get("/api/projects").status_code == 401 and b.get("/api/projects").status_code == 401


def test_sessions_expire_and_idle_out(owner, monkeypatch):
    from clipfoundry import db
    from clipfoundry.cloud import identity

    sid = db.select("auth_sessions", "revoked_at = 0")[0]["id"]
    db.update("auth_sessions", sid, last_seen_at=time.time() - 5 * 3600)  # longer than the 4-hour idle limit
    assert owner.get("/api/projects").status_code == 401
    db.update("auth_sessions", sid, last_seen_at=time.time(), expires_at=time.time() - 1)
    assert owner.get("/api/projects").status_code == 401
    assert identity.resolve("") is None and identity.resolve("x" * 500) is None


def test_removing_an_owner_from_the_configuration_ends_their_sessions(owner, monkeypatch):
    from clipfoundry.cloud import settings as cloud_settings

    monkeypatch.setenv("CLIPFOUNDRY_OWNER_SUBJECTS", f"{ISSUER}|someone-new")
    cloud_settings.reset()
    assert owner.get("/api/projects").status_code == 401


def test_the_database_never_holds_a_usable_session_cookie(owner):
    from clipfoundry import db

    cookie = next(v for k, v in owner.cookies.items() if k.endswith("cf_session"))
    rows = db.select("auth_sessions")
    assert rows and all(cookie not in json.dumps(r) for r in rows)


# ------------------------------------------------------------------ two identities: workspace isolation
def test_a_second_identity_sees_none_of_the_owners_data(cloud, tmp_path):
    with _client() as a, _client() as b:
        sign_in(a, cloud, OWNER)
        me_b = sign_in(b, cloud, SECOND)
        assert not me_b["primary"] and me_b["workspace_id"] != "local"
        mine = _project("owner-secret-project", "local", tmp_path)
        theirs = _project("second-project", me_b["workspace_id"], tmp_path)
        pid, cid = mine["project"]["id"], mine["clip"]["id"]
        listed = b.get("/api/projects").json()
        assert [p["id"] for p in listed] == [theirs["project"]["id"]]
        assert "owner-secret-project" not in b.get("/api/stats").text
        for path in (f"/api/projects/{pid}", f"/api/projects/{pid}/source", f"/api/projects/{pid}/thumbnail",
                     f"/api/projects/{pid}/transcript", f"/api/clips/{cid}", f"/api/clips/{cid}/video",
                     f"/api/clips/{cid}/thumbnail", f"/api/clips/{cid}/words"):
            r = b.get(path, headers={"Range": "bytes=0-10"})
            assert r.status_code == 404, path
            assert "owner-secret-project" not in r.text
        # Shared processing writes are owner-only before object lookup; other foreign objects stay 404.
        assert b.delete(f"/api/projects/{pid}").status_code == 403
        assert b.patch(f"/api/clips/{cid}", json={"title": "taken"}).status_code == 403
        # single-workspace areas (Autopilot, Brain notes, settings, accounts, publishing) are closed to it
        for path in ("/api/autopilot/status", "/api/settings", "/api/publish/accounts", "/api/knowledge",
                     "/api/office/snapshot", f"/api/clips/{theirs['clip']['id']}/publications"):
            assert b.get(path).status_code in (403, 404), path
        # and the owner cannot reach the second workspace's objects either
        assert a.get(f"/api/projects/{theirs['project']['id']}").status_code == 404
        assert [p["id"] for p in a.get("/api/projects").json()] == [pid]


def test_secondary_workspace_cannot_consult_shared_brain_or_start_shared_processing(cloud):
    with _client() as owner, _client() as second:
        sign_in(owner, cloud, OWNER)
        sign_in(second, cloud, SECOND)
        saved = owner.post("/api/brain/knowledge", headers={"X-ClipFoundry": "1"}, json={
            "kind": "instruction", "title": "Owner private caption guidance", "content": "",
            "preferences": {"caption_position": "middle"}})
        assert saved.status_code == 200
        mine = owner.get("/api/studio/guidance/preview", params={"mode": "highlights"})
        assert mine.status_code == 200 and "Owner private caption guidance" in mine.text
        for method, path in (
            ("GET", "/api/studio/guidance/preview?mode=highlights"),
            ("POST", "/api/studio/guidance/preview"),
            ("POST", "/api/studio/clips"),
            ("POST", "/api/studio/videos"),
            ("POST", "/api/projects"),
            ("POST", "/api/projects/any/retry"),
            ("PATCH", "/api/clips/any"),
            ("POST", "/api/stories/any/render"),
        ):
            response = second.request(method, path, json={} if method != "GET" else None)
            assert response.status_code == 403, (method, path, response.text)
            assert "Owner private caption guidance" not in response.text
        # Workspace-scoped storage and preferences remain available; processing stays owner-only for now.
        assert second.get("/api/studio/styles").status_code == 200
        assert second.get("/api/preferences/appearance").status_code == 200


# ------------------------------------------------------------------ encrypted secrets
def test_cloud_secrets_are_aes_gcm_and_fail_closed(cloud, monkeypatch, tmp_path):
    from clipfoundry import secure

    sealed = secure.seal("refresh-token-value")
    assert sealed.startswith(secure.AESGCM) and "refresh-token-value" not in sealed
    assert secure.unseal(sealed) == "refresh-token-value"
    tampered = sealed[:-4] + ("AAAA" if not sealed.endswith("AAAA") else "BBBB")
    with pytest.raises(secure.SecretError):
        secure.unseal(tampered)
    with pytest.raises(secure.SecretError, match="without encryption"):
        secure.unseal(secure.LOCAL + base64.b64encode(b"plain").decode())
    with pytest.raises(secure.SecretError, match="without encryption"):
        secure.unseal("plaintext-token")
    other = tmp_path / "keys" / "other.key"
    other.write_text(base64.b64encode(os.urandom(32)).decode())
    os.chmod(other, 0o600)
    monkeypatch.setenv("CLIPFOUNDRY_SECRET_KEY_FILE", str(other))
    with pytest.raises(secure.SecretError, match="different server key"):
        secure.unseal(sealed)
    monkeypatch.delenv("CLIPFOUNDRY_SECRET_KEY_FILE")
    with pytest.raises(secure.SecretError):
        secure.seal("anything")


def test_desktop_base64_secrets_are_upgraded_once_in_cloud_mode(monkeypatch, tmp_path):
    import sqlite3

    from clipfoundry import config, db, secure

    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "clipfoundry.db")
    conn.executescript(db.SCHEMA)
    legacy = secure.LOCAL + base64.b64encode(b"yt-client-secret").decode()
    conn.execute("INSERT INTO settings (key, value) VALUES ('youtube_client_secret', ?)", (json.dumps(legacy),))
    tokens = secure.LOCAL + base64.b64encode(json.dumps({"access_token": "a", "refresh_token": "r",
                                                          "expires_at": 1}).encode()).decode()
    conn.execute("INSERT INTO accounts (platform, account_id, display_name, tokens, connected_at, updated_at) "
                 "VALUES ('youtube', 'UC1', 'Mine', ?, 1, 1)", (tokens,))
    conn.commit()
    conn.close()
    cloud_env(monkeypatch, tmp_path)
    db.init()
    stored = json.loads(db.scalar("SELECT value FROM settings WHERE key = 'youtube_client_secret'"))
    assert stored.startswith(secure.AESGCM) and db.get_settings()["youtube_client_secret"] == "yt-client-secret"
    assert db.account_tokens("youtube")["refresh_token"] == "r"
    assert db.scalar("SELECT tokens FROM social_connections").startswith(secure.AESGCM)
    assert config.SEALED_KEYS


def test_already_sealed_settings_are_never_sealed_again(monkeypatch, tmp_path):
    """Regression: the start-up migration wrapped macOS Keychain values again at every start."""
    import sqlite3

    from clipfoundry import db

    data = tmp_path / "mac"
    data.mkdir()
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(data))
    conn = sqlite3.connect(data / "clipfoundry.db")
    conn.executescript(db.SCHEMA)
    for key, value in (("youtube_client_secret", "keychain:v1:abc:payload"),
                       ("tiktok_client_secret", "aesgcm:v1:abc:payload")):
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    conn.commit()
    conn.close()
    db.init()
    assert json.loads(db.scalar("SELECT value FROM settings WHERE key = 'youtube_client_secret'")) == \
        "keychain:v1:abc:payload"
    assert json.loads(db.scalar("SELECT value FROM settings WHERE key = 'tiktok_client_secret'")) == \
        "aesgcm:v1:abc:payload"


# ------------------------------------------------------------------ URL ingestion on a server
def test_cloud_never_fetches_private_or_metadata_addresses(cloud):
    from clipfoundry import netguard

    for url in ("http://127.0.0.1:8765/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/v.mp4",
                "http://[::1]/"):
        with pytest.raises(netguard.UnsafeUrl):
            netguard.check(url, allow_private=True)  # an owner-typed allowance does not apply on a server


def test_cloud_link_import_refuses_internal_addresses(owner):
    r = owner.post("/api/projects/url", json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 400
