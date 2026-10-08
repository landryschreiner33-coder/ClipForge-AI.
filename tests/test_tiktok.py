"""TikTok publishing against a local stand-in for TikTok's Login Kit and Content Posting API."""
from __future__ import annotations

import os
import time
from urllib.parse import parse_qs, urlparse

import pytest

from fake_platforms import FakeTikTok

H = {"X-ClipFoundry": "1"}
MB = 1024 * 1024


@pytest.fixture()
def tt(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry.publish import jobs, tiktok

    fake = FakeTikTok()
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{fake.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{fake.url}/v2")
    monkeypatch.setattr(tiktok, "CHUNK", 5 * MB)
    monkeypatch.setattr(tiktok, "POLL_SECONDS", 0.01)
    jobs.worker.cancelled.clear()
    yield fake
    fake.stop()


@pytest.fixture()
def app_client(tt):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


@pytest.fixture()
def clip(app_client, tmp_path):
    from clipfoundry import db

    video = tmp_path / "clip.mp4"
    video.write_bytes(os.urandom(12 * MB))  # 5 MB + 7 MB chunks
    project = db.create_project("talk", source_path=str(tmp_path / "source.mp4"), status="ready")
    c = db.create_clip(project["id"], start=0, end=30, title="t", status="ready", output_path=str(video),
                       duration=30.0, score=80.0)
    return c, video.read_bytes()


def _connect(client, tt, audited: bool = False) -> None:
    # audience policy: an unaudited app can only stage ("Only me"); an audited one posts to the private account's
    # friends here (the fake account offers Friends, not Followers)
    audience = {"audience_tiktok_intent": "SELECTED_AUDIENCE", "audience_tiktok_group": "FRIENDS",
                "audience_tiktok_private_confirmed": True, "audience_tiktok_followers_reviewed": True} if audited \
        else {"audience_tiktok_intent": "OWNER_ONLY"}
    client.put("/api/settings", json={"tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret",
                                      "tiktok_app_audited": audited, **audience})
    acc = client.get("/api/publish/accounts").json()["tiktok"]
    assert acc["redirect_uri"] == "http://127.0.0.1:8765/api/oauth/tiktok/callback"  # what to register at TikTok
    auth_url = client.post("/api/publish/tiktok/connect", headers=H).json()["auth_url"]
    q = parse_qs(urlparse(auth_url).query)
    assert q["client_key"] == ["tkkey"] and q["redirect_uri"] == [acc["redirect_uri"]]
    assert q["scope"] == ["user.info.basic,video.upload,video.publish,video.list"]
    page = client.get("/api/oauth/tiktok/callback", params={"state": q["state"][0], "code": tt.approve(auth_url),
                                                            "scopes": q["scope"][0]})
    assert "TikTok connected" in page.text and "Test Creator" in page.text


def _wait(client, pub_id: str, until=("done", "action_needed", "failed", "cancelled"), timeout: float = 30) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = client.get(f"/api/publications/{pub_id}").json()
        if p["status"] in until:
            return p
        time.sleep(0.05)
    raise AssertionError(f"publication stuck: {p}")


def _post(client, clip_id: str, **kw):
    body = {"description": "Why do most diets fail? #diets #willpower", "privacy": "SELF_ONLY", "mode": "direct",
            "confirm": True, **kw}
    return client.post(f"/api/clips/{clip_id}/publish/tiktok", json=body, headers=H)


def test_connect_with_hex_pkce_and_show_account(app_client, tt):
    _connect(app_client, tt)
    acc = app_client.get("/api/publish/accounts").json()["tiktok"]
    assert acc["connected"] and acc["name"] == "Test Creator"
    assert acc["can_direct_post"] and acc["can_inbox"] and acc["can_read_stats"]
    assert "Only me" in acc["restriction"]  # unaudited app: explained up front
    creator = app_client.get("/api/publish/tiktok/creator").json()
    assert creator["nickname"] == "Test Creator" and "SELF_ONLY" in creator["privacy_options"]
    assert creator["duet_disabled"] and creator["max_duration"] == 600


def test_direct_post_uploads_in_chunks_and_polls_until_posted(app_client, tt, clip):
    c, data = clip
    _connect(app_client, tt)
    r = _post(app_client, c["id"])
    assert r.status_code == 200, r.text
    pub = _wait(app_client, r.json()["id"])
    assert pub["status"] == "done" and pub["privacy"] == "SELF_ONLY", pub
    assert "few minutes" in pub["message"] and pub["url"] == ""  # "Only me" posts have no public link
    up = tt.uploads[pub["remote_id"]]
    assert bytes(up["data"]) == data
    init = tt.inits[-1]
    assert init["source_info"] == {"source": "FILE_UPLOAD", "video_size": 12 * MB, "chunk_size": 5 * MB,
                                   "total_chunk_count": 2}
    # TikTok guidelines: interactions stay off unless the user turns them on; no commercial toggles by default
    assert init["post_info"] == {"title": "Why do most diets fail? #diets #willpower", "privacy_level": "SELF_ONLY",
                                 "disable_comment": True, "disable_duet": True, "disable_stitch": True,
                                 "brand_content_toggle": False, "brand_organic_toggle": False}


def test_a_rate_limited_chunk_waits_as_long_as_tiktok_asks(app_client, tt, clip):
    c, data = clip
    _connect(app_client, tt)
    tt.rate_limit_chunks, tt.retry_after = 1, "1"  # a short wait: the chunk is sent again after it
    t0 = time.time()
    pub = _wait(app_client, _post(app_client, c["id"]).json()["id"])
    assert pub["status"] == "done" and bytes(tt.uploads[pub["remote_id"]]["data"]) == data
    assert time.time() - t0 >= 1.0
    # a long wait is not spent inside the upload, and not shortened: the post waits for TikTok's time, then starts
    # again (TikTok never posts the unfinished upload)
    tt.rate_limit_chunks, tt.retry_after = 1, "600"
    t1 = time.time()
    pid = _post(app_client, c["id"]).json()["id"]
    pub = _wait(app_client, pid, until=("queued",))
    while not (pub.get("info") or {}).get("retry_at"):
        pub = _wait(app_client, pid, until=("queued",))
    assert pub["info"]["retry_at"] >= t1 + 600 and "TikTok asked to wait 10 minutes" in pub["message"]
    from clipfoundry.publish import jobs

    assert pid in jobs.worker.timers
    jobs.worker.later(pid, time.time())  # the time TikTok asked for has come
    pub = _wait(app_client, pid)
    assert pub["status"] == "done" and bytes(tt.uploads[pub["remote_id"]]["data"]) == data


def test_friends_post_after_audit_links_to_the_video(app_client, tt, clip):
    c, _ = clip
    _connect(app_client, tt, audited=True)
    pub = _wait(app_client, _post(app_client, c["id"], privacy="MUTUAL_FOLLOW_FRIENDS",
                                  allow_comment=True).json()["id"])
    assert pub["status"] == "done" and pub["privacy"] == "MUTUAL_FOLLOW_FRIENDS"
    assert tt.inits[-1]["post_info"]["disable_comment"] is False
    assert tt.inits[-1]["post_info"]["privacy_level"] == "MUTUAL_FOLLOW_FRIENDS"
    assert pub["info"]["audience"]["setup"] == "api_verified" and pub["info"]["audience"]["intent"] == \
        "SELECTED_AUDIENCE"


def test_unaudited_app_is_limited_to_only_me(app_client, tt, clip):
    c, _ = clip
    _connect(app_client, tt, audited=False)
    r = _post(app_client, c["id"], privacy="PUBLIC_TO_EVERYONE")
    assert r.status_code == 400 and "Only me" in r.json()["detail"] and "inbox" in r.json()["fix"]
    assert not tt.inits


def test_everyone_and_only_me_never_reach_selected_viewers(app_client, tt, clip):
    c, _ = clip
    _connect(app_client, tt, audited=True)
    r = _post(app_client, c["id"], privacy="PUBLIC_TO_EVERYONE")
    assert r.status_code == 400 and r.json()["code"] == "audience_blocked"
    r = _post(app_client, c["id"], privacy="SELF_ONLY")
    assert r.status_code == 400 and "cannot reach your test viewers" in r.json()["detail"]
    assert not tt.inits


@pytest.mark.parametrize("kw, text", [
    ({"privacy": ""}, "no default"),
    ({"allow_duet": True}, "do not allow duets"),
    ({"disclose": True}, "chose no option"),
    ({"privacy": "FOLLOWER_OF_CREATOR"}, "does not offer"),
    ({"description": "x" * 2201}, "2200"),
    ({"confirm": False}, "explicit confirmation"),
])
def test_guideline_checks_before_upload(app_client, tt, clip, kw, text):
    c, _ = clip
    _connect(app_client, tt, audited=True)
    r = _post(app_client, c["id"], **kw)
    assert r.status_code == 400 and text in r.json()["detail"] + r.json()["fix"], r.json()
    assert not tt.inits


def test_branded_content_cannot_be_only_me(app_client, tt, clip):
    c, _ = clip
    _connect(app_client, tt, audited=True)
    r = _post(app_client, c["id"], disclose=True, brand_content=True, privacy="SELF_ONLY")
    assert r.status_code == 400 and "Branded content" in r.json()["detail"]
    ok = _post(app_client, c["id"], disclose=True, brand_content=True, privacy="MUTUAL_FOLLOW_FRIENDS")
    assert ok.status_code == 200
    _wait(app_client, ok.json()["id"])
    assert tt.inits[-1]["post_info"]["brand_content_toggle"] is True


def test_private_account_requirement_falls_back_to_inbox(app_client, tt, clip):
    c, data = clip
    _connect(app_client, tt)
    tt.init_error = "unaudited_client_can_only_post_to_private_accounts"
    pub = _wait(app_client, _post(app_client, c["id"]).json()["id"])
    assert pub["status"] == "failed" and "private" in pub["error"] and "inbox" in pub["fix"]
    tt.init_error = ""
    pub = _wait(app_client, _post(app_client, c["id"], mode="inbox", privacy="").json()["id"])
    assert pub["status"] == "action_needed" and pub["mode"] == "inbox" and "TikTok app" in pub["message"]
    assert tt.inits[-1]["path"].endswith("/inbox/video/init/") and "post_info" not in tt.inits[-1]
    assert bytes(tt.uploads[pub["remote_id"]]["data"]) == data


def test_processing_failure_is_reported(app_client, tt, clip):
    c, _ = clip
    _connect(app_client, tt)
    tt.fail_reason = "frame_rate_check_failed"
    pub = _wait(app_client, _post(app_client, c["id"]).json()["id"])
    assert pub["status"] == "failed" and "frame rate" in pub["error"] and "30" in pub["fix"]


def test_missing_direct_post_permission(app_client, tt, clip):
    c, _ = clip
    tt.scope = "user.info.basic,video.upload"  # the app only has the inbox upload
    _connect(app_client, tt)
    acc = app_client.get("/api/publish/accounts").json()["tiktok"]
    assert not acc["can_direct_post"] and acc["can_inbox"] and not acc["can_read_stats"]
    r = _post(app_client, c["id"])
    assert r.status_code == 400 and "video.publish" in r.json()["detail"]
    assert _post(app_client, c["id"], mode="inbox", privacy="").status_code == 200


def test_expired_token_is_refreshed_and_disconnect_revokes(app_client, tt, clip):
    from clipfoundry import db

    c, _ = clip
    _connect(app_client, tt)
    db.save_account("tiktok", tokens={**db.account_tokens("tiktok"), "expires_at": 0})
    pub = _wait(app_client, _post(app_client, c["id"]).json()["id"])
    assert pub["status"] == "done" and tt.grants == ["authorization_code", "refresh_token"]
    app_client.post("/api/publish/tiktok/disconnect", headers=H)
    assert tt.revoked and not app_client.get("/api/publish/accounts").json()["tiktok"]["connected"]


def test_chunking_rules():
    from clipfoundry.publish import tiktok

    assert tiktok.chunking(3 * MB) == (3 * MB, 1)                    # under 5 MB: one chunk of the whole file
    assert tiktok.chunking(12 * MB) == (10 * MB, 1)                  # the last chunk carries the remainder
    assert tiktok.chunking(100 * MB) == (10 * MB, 10)
    assert tiktok.caption_length("😀" * 1100) == 2200                # TikTok counts UTF-16 code units


def test_unreachable_platform_is_a_plain_error_not_a_crash(app_client, tt, monkeypatch):
    from clipfoundry.publish import tiktok

    _connect(app_client, tt)
    monkeypatch.setattr(tiktok, "API_URL", "http://127.0.0.1:9/v2")  # nothing listens there
    r = app_client.get("/api/publish/tiktok/creator")
    assert r.status_code == 400 and "Could not reach TikTok" in r.json()["detail"]
    assert "internet connection" in r.json()["fix"]
