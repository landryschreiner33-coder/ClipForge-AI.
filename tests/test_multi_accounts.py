"""Several YouTube channels and TikTok accounts at once (CF-10, CF-11, account migration).

Fake platforms only: every token, refresh and upload is tied to the fake account it belongs to, so these tests prove
which account received which bytes. No real account is used.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time

import pytest

from multi_fakes import FakeGoogleMulti, FakeTikTokMulti
from test_autopilot_publish import H, passed_report

YT = {"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogleMulti(), FakeTikTokMulti()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    monkeypatch.setattr(tiktok, "POLL_SECONDS", 0.01)
    db.init()
    db.save_settings({**YT, "audience_tiktok": "owner_only"})
    yield g, t, tmp_path
    g.stop()
    t.stop()


@pytest.fixture()
def api(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def connect(api, fake, platform: str, operation: str = "add", connection_id: str = "", **who) -> dict:
    """Add (or reconnect) an account through the real endpoints and the provider's callback."""
    from urllib.parse import parse_qs, urlparse

    path = f"/api/connections/{connection_id}/reconnect" if operation == "reconnect" else \
        f"/api/connections/{platform}/add"
    r = api.post(path, headers=H)
    assert r.status_code == 200, r.text
    auth_url = r.json()["auth_url"]
    code = fake.approve(auth_url, **who)
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    page = api.get(f"/api/oauth/{platform}/callback?state={state}&code={code}")
    assert page.status_code == 200
    return {"page": page.text, "connections": api.get("/api/connections").json()["connections"]}


def make_clip(tmp, size: int = 300_000) -> dict:
    from clipfoundry import db

    video = tmp / f"clip-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(size))
    project = db.create_project("talk", status="ready")
    clip = db.create_clip(project["id"], start=0, end=20, title="Talk to customers first", status="ready",
                          output_path=str(video), duration=20.0, caption_text="Talk to customers first.")
    passed_report(clip)
    return clip


def publish_youtube(api, clip_id: str, connection_id: str):
    return api.post(f"/api/clips/{clip_id}/publish/youtube", headers=H, json={
        "title": "Talk to customers first", "description": "Talk to customers first.", "tags": [],
        "privacy": "private", "made_for_kids": False, "confirm": True, "connection_id": connection_id})


def wait_done(pub_id: str, timeout: float = 20.0) -> dict:
    from clipfoundry import db
    from clipfoundry.publish import jobs

    end = time.time() + timeout
    while time.time() < end:
        pub = db.get_publication(pub_id)
        if pub["status"] not in jobs.ACTIVE:
            return pub
        time.sleep(0.05)
    raise AssertionError(f"publication {pub_id} still {db.get_publication(pub_id)['status']}")


# ------------------------------------------------------------------ connecting accounts
def test_adding_a_second_channel_keeps_the_first_and_its_default(env, api):
    g, _, _ = env
    first = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"]
    assert [c["display_name"] for c in first] == ["Channel A"] and first[0]["is_default"]
    both = connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
    by_name = {c["display_name"]: c for c in both}
    assert set(by_name) == {"Channel A", "Channel B"}
    assert by_name["Channel A"]["is_default"] and not by_name["Channel B"]["is_default"]
    assert by_name["Channel A"]["id"] == first[0]["id"]  # the first connection kept its identity
    from clipfoundry import db

    assert db.connection_tokens(by_name["Channel A"]["id"])["access_token"] != \
        db.connection_tokens(by_name["Channel B"]["id"])["access_token"]
    assert db.get_account("youtube")["account_id"] == "UCchanA"  # older single-account paths are unchanged


def test_two_channels_from_one_google_sign_in_are_two_connections(env, api):
    """A Google identity can own several channels (Brand Accounts); the channel, not the email, is the identity."""
    g, _, _ = env
    connect(api, g, "youtube", channel="UCpersonal", title="Personal channel")
    rows = connect(api, g, "youtube", channel="UCbrand", title="Brand channel")["connections"]
    assert sorted(c["account_id"] for c in rows) == ["UCbrand", "UCpersonal"]


def test_reconnecting_the_same_channel_updates_it_without_a_duplicate(env, api):
    g, _, _ = env
    a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    rows = connect(api, g, "youtube", channel="UCchanA", title="Channel A renamed")["connections"]
    assert len(rows) == 1 and rows[0]["id"] == a["id"] and rows[0]["display_name"] == "Channel A renamed"
    rows = connect(api, g, "youtube", "reconnect", a["id"], channel="UCchanA", title="Channel A")["connections"]
    assert len(rows) == 1 and rows[0]["id"] == a["id"]


def test_reconnect_refuses_a_different_channel(env, api):
    g, _, _ = env
    a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    out = connect(api, g, "youtube", "reconnect", a["id"], channel="UCother", title="Other")
    assert "not “Channel A”" in out["page"]
    assert [c["account_id"] for c in out["connections"]] == ["UCchanA"]


def test_disconnecting_one_account_leaves_the_others(env, api):
    g, t, _ = env
    connect(api, g, "youtube", channel="UCchanA", title="Channel A")
    rows = connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
    connect(api, t, "tiktok", open_id="open-a", name="Creator A")
    b = next(c for c in rows if c["account_id"] == "UCchanB")
    assert api.post(f"/api/connections/{b['id']}/disconnect", headers=H).json()["status"] == "disconnected"
    state = {c["account_id"]: c["health"]["state"] for c in api.get("/api/connections").json()["connections"]}
    assert state == {"UCchanA": "ok", "UCchanB": "disconnected", "open-a": "ok"}


def test_a_connection_id_of_another_workspace_or_platform_is_refused(env, api, tmp_path):
    from clipfoundry import db

    g, t, _ = env
    yt = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    clip = make_clip(tmp_path)
    r = api.post(f"/api/clips/{clip['id']}/publish/tiktok", headers=H, json={
        "description": "x", "privacy": "SELF_ONLY", "mode": "inbox", "confirm": True, "connection_id": yt["id"]})
    assert r.status_code == 400 and "Choose a connected TikTok account" in r.json()["detail"]
    other, _ = db.upsert_connection("youtube", "UCforeign", {"access_token": "x", "expires_at": 9e9},
                                    workspace_id="ws-someone-else")
    r = publish_youtube(api, clip["id"], other["id"])
    assert r.status_code == 400 and not g.videos
    assert api.post(f"/api/connections/{other['id']}/disconnect", headers=H).status_code == 404


def test_concurrent_refreshes_of_one_account_happen_once_and_accounts_do_not_wait_on_each_other(env, api):
    from clipfoundry import db
    from clipfoundry.publish import youtube

    g, _, _ = env
    connect(api, g, "youtube", channel="UCchanA", title="Channel A")
    rows = connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
    ids = {c["account_id"]: c["id"] for c in rows}
    for cid in ids.values():  # both access tokens expired
        tok = db.connection_tokens(cid)
        db.update_connection(cid, tokens={**tok, "expires_at": time.time() - 10})
    g.refresh_delay = 0.3
    results: dict[str, list[str]] = {"UCchanA": [], "UCchanB": []}

    def get(channel):
        results[channel].append(youtube.Token(db.get_settings(), ids[channel]).get())

    threads = [threading.Thread(target=get, args=(ch,)) for ch in ("UCchanA",) * 4 + ("UCchanB",) * 4]
    started = time.time()
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert g.refreshes == {"UCchanA": 1, "UCchanB": 1}
    assert len(set(results["UCchanA"])) == 1 and len(set(results["UCchanB"])) == 1
    assert results["UCchanA"][0] != results["UCchanB"][0]
    assert g.access_channel[results["UCchanA"][0]] == "UCchanA"  # never another account's token
    assert time.time() - started < 4 * 0.3  # the two accounts refreshed side by side, not one after the other


# ------------------------------------------------------------------ CF-10: one clip, two channels
def test_partial_success_retries_only_the_failed_channel(env, api, tmp_path):
    from clipfoundry import db

    g, _, _ = env
    a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    b = next(c for c in connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
             if c["account_id"] == "UCchanB")
    clip = make_clip(tmp_path)
    # Channel B's access was revoked at Google and its access token has expired.
    g.revoke_channel("UCchanB")
    db.update_connection(b["id"], tokens={**db.connection_tokens(b["id"]), "expires_at": time.time() - 10})
    pa = publish_youtube(api, clip["id"], a["id"])
    pb = publish_youtube(api, clip["id"], b["id"])
    assert pa.status_code == 200 and pb.status_code == 200, (pa.text, pb.text)
    done_a, failed_b = wait_done(pa.json()["id"]), wait_done(pb.json()["id"])
    assert done_a["status"] == "done" and failed_b["status"] == "failed"
    assert failed_b["info"].get("code") == "reconnect" or "Reconnect" in (failed_b.get("fix") or "")
    assert len(g.uploads_to("UCchanA")) == 1 and g.uploads_to("UCchanB") == []
    health = {c["account_id"]: c["health"]["state"] for c in api.get("/api/connections").json()["connections"]}
    assert health == {"UCchanA": "ok", "UCchanB": "needs_reconnect"}
    # The owner reconnects B and publishes to B again: A is not uploaded to a second time.
    connect(api, g, "youtube", "reconnect", b["id"], channel="UCchanB", title="Channel B")
    retry = publish_youtube(api, clip["id"], b["id"])
    assert retry.status_code == 200, retry.text
    assert wait_done(retry.json()["id"])["status"] == "done"
    assert len(g.uploads_to("UCchanA")) == 1 and len(g.uploads_to("UCchanB")) == 1
    a_bytes, b_bytes = g.uploads_to("UCchanA")[0]["bytes"], g.uploads_to("UCchanB")[0]["bytes"]
    assert a_bytes == b_bytes == open(clip["output_path"], "rb").read()  # the exact checked file, to each
    # A second upload to A is refused while... it is simply a new explicit request; the active-check is per account
    assert db.get_publication(pa.json()["id"])["connection_id"] == a["id"]
    assert db.get_publication(retry.json()["id"])["connection_id"] == b["id"]


def test_changing_the_default_never_moves_a_queued_upload(env, api, tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.publish import jobs

    g, _, _ = env
    a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    b = next(c for c in connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
             if c["account_id"] == "UCchanB")
    monkeypatch.setattr(jobs.worker, "submit", lambda _pub_id: None)  # hold it in the queue
    pub = publish_youtube(api, make_clip(tmp_path)["id"], "").json()  # no account named: today's default (A)
    assert pub["connection_id"] == a["id"]
    assert api.patch(f"/api/connections/{b['id']}", headers=H, json={"make_default": True}).json()["is_default"]
    jobs.worker._run(pub["id"])
    assert db.get_publication(pub["id"])["status"] == "done"
    assert len(g.uploads_to("UCchanA")) == 1 and g.uploads_to("UCchanB") == []


def test_both_channels_share_the_api_project_quota(env, api, tmp_path):
    from clipfoundry.autopilot import quota

    g, _, _ = env
    a = connect(api, g, "youtube", channel="UCchanA", title="Channel A")["connections"][0]
    b = next(c for c in connect(api, g, "youtube", channel="UCchanB", title="Channel B")["connections"]
             if c["account_id"] == "UCchanB")
    before = sum(v.get("units", 0) for v in quota.usage().values())
    clip = make_clip(tmp_path)
    wait_done(publish_youtube(api, clip["id"], a["id"]).json()["id"])
    wait_done(publish_youtube(api, clip["id"], b["id"]).json()["id"])
    after = sum(v.get("units", 0) for v in quota.usage().values())
    assert after > before  # one Cloud project budget, counted for every channel: accounts never multiply it


# ------------------------------------------------------------------ TikTok: two creators
def test_two_tiktok_accounts_each_get_their_own_upload(env, api, tmp_path):
    from clipfoundry import db

    _, t, _ = env
    one = connect(api, t, "tiktok", open_id="open-a", name="Creator A")["connections"][0]
    two = next(c for c in connect(api, t, "tiktok", open_id="open-b", name="Creator B")["connections"]
               if c["account_id"] == "open-b")
    clip = make_clip(tmp_path)
    for cid in (one["id"], two["id"]):
        r = api.post(f"/api/clips/{clip['id']}/publish/tiktok", headers=H, json={
            "description": "Talk to customers first.", "privacy": "SELF_ONLY", "mode": "inbox", "confirm": True,
            "connection_id": cid})
        assert r.status_code == 200, r.text
        wait_done(r.json()["id"])
    assert len(t.uploads_by("open-a")) == 1 and len(t.uploads_by("open-b")) == 1
    assert {p["connection_id"] for p in db.list_publications(clip["id"], "tiktok")} == {one["id"], two["id"]}


# ------------------------------------------------------------------ migration of the single-account table
def test_old_single_accounts_migrate_with_tokens_history_and_approvals(monkeypatch, tmp_path):
    from clipfoundry import db

    data = tmp_path / "old"
    data.mkdir()
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(data))
    conn = sqlite3.connect(data / "clipfoundry.db")
    conn.executescript(db.SCHEMA.split("-- ---------------------------------------------------------------- "
                                       "ClipForge")[0])
    sealed = "local:" + base64.b64encode(json.dumps({"access_token": "a", "refresh_token": "r",
                                                     "expires_at": 1}).encode()).decode()
    conn.execute("INSERT INTO accounts (platform, account_id, display_name, tokens, scopes, connected_at, updated_at) "
                 "VALUES ('youtube', 'UCold', 'Old channel', ?, '[]', 5, 5)", (sealed,))
    for pid, approved in (("p-match", "UCold"), ("p-none", ""), ("p-other", "UCsomeoneelse")):
        conn.execute("INSERT INTO publications (id, clip_id, platform, status, options, created_at, updated_at) "
                     "VALUES (?, 'c1', 'youtube', 'done', ?, 1, 1)", (pid, json.dumps({"approved_account": approved})))
    conn.commit()
    conn.close()
    db.init()
    rows = db.select("social_connections")
    assert len(rows) == 1 and rows[0]["id"] == db.legacy_connection_id("youtube")
    assert rows[0]["tokens"] == sealed  # the very same sealed bytes, not re-encrypted
    assert rows[0]["external_id"] == "UCold" and rows[0]["is_default"] == 1
    assert db.get_account("youtube")["display_name"] == "Old channel"
    bound = {p["id"]: p["connection_id"] for p in db.list_publications()}
    assert bound == {"p-match": rows[0]["id"], "p-none": rows[0]["id"], "p-other": ""}
    old = sqlite3.connect(data / "clipfoundry.db").execute("SELECT tokens FROM accounts").fetchone()[0]
    assert old == sealed  # the old table is left as a rollback copy
    db._ready.clear()  # noqa: SLF001 - a second start runs the migrations again
    db.init()
    assert len(db.select("social_connections")) == 1
