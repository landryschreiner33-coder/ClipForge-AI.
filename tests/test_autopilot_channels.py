"""Channel claims: a feed can name any channel for any video. Ownership and channel rules count only when the
platform's own data confirms that exact video (and the link to it) belongs to that channel; a confirmed channel
still needs a rule. Unconfirmed videos are skipped with the reason in the activity log, never asked about, and work
queued before the check cannot get around it. Against local stand-ins for Google and TikTok (nothing here reaches a
real service)."""
from __future__ import annotations

import json
import time

import pytest
from fake_platforms import FakeGoogle, FakeTikTok

MINE = "UC123"                   # the connected channel of the Google stand-in
POD = "UCpod0000000000001"       # a creator you have an agreement with
OTHER = "UCother0000000000009"   # someone else


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    monkeypatch.setattr(youtube, "API_URL", f"{g.url}/youtube/v3")
    monkeypatch.setattr(tiktok, "OEMBED_URL", f"{t.url}/oembed")
    db.init()
    db.save_settings({"autopilot_public_videos": False})  # test channel eligibility in restricted discovery mode
    db.save_settings({"youtube_api_key": "test-api-key", "autopilot_enabled": True})
    db.save_account("youtube", tokens={"access_token": "x", "expires_at": 0}, account_id=MINE)
    yield {"g": g, "t": t, "tmp": tmp_path}
    g.stop()
    t.stop()


def run(kind: str, payload: dict | None = None) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue(kind, payload or {})
    return host.HANDLERS[kind](host.Job(queue.get(row["id"]), "test"))


def feed(env, rows: list[dict]) -> dict[str, dict]:
    """A signal feed with these rows, scanned; the sources it produced, by video ID."""
    from clipfoundry import db
    from clipfoundry.autopilot import providers

    path = env["tmp"] / f"feed-{time.time_ns()}.json"
    path.write_text(json.dumps([{"title": f"Episode {r['id']}: the long talk", "views": 900000, **r} for r in rows]))
    providers.add_feed("signal_feed", "Partner list", {"path": str(path)})
    run("feed_scan")
    run("source_scout")
    return {s["external_id"]: s for s in db.select("sources")}


def activity() -> dict[str, dict]:
    from clipfoundry.autopilot import home

    return {a["id"]: a for a in home.activity()}


def hunts() -> list[str]:
    from clipfoundry.autopilot import queue

    return [j["ref_id"] for j in queue.jobs(worker="clip_hunter")]


def test_a_feed_that_falsely_claims_your_channel_is_skipped(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, state

    g = env["g"]
    g.add_video("notmine00001", "Someone else's talk", OTHER, duration="PT40M")
    g.add_video("mytalk000001", "My own talk", MINE, duration="PT40M")
    g.add_video("mytalk000002", "My second talk", MINE, duration="PT40M")
    db.save_settings({"rights_ask_per_video": True})  # even with questions on, nothing unconfirmed is asked about
    src = feed(env, [
        # someone else's video, listed as yours
        {"id": "notmine00001", "title": "Why startups fail", "platform": "youtube", "channel_id": MINE,
         "url": "https://www.youtube.com/watch?v=notmine00001"},
        # your real video, paired with a file from somewhere else
        {"id": "mytalk000001", "title": "Cooking for beginners", "platform": "youtube", "channel_id": MINE,
         "url": "https://cdn.example.com/x.mp4"},
        # a video YouTube does not know
        {"id": "ghost0000001", "title": "The history of maps", "platform": "youtube", "channel_id": MINE,
         "url": "https://www.youtube.com/watch?v=ghost0000001"},
        # the control: your real video, listed correctly
        {"id": "mytalk000002", "title": "My second talk", "platform": "youtube", "channel_id": MINE,
         "url": "https://www.youtube.com/watch?v=mytalk000002"},
    ])
    log = activity()
    for vid, why in (("notmine00001", "YouTube says this video belongs to another channel (Channel 0009)"),
                     ("mytalk000001", "The link does not lead to this exact video"),
                     ("ghost0000001", "YouTube has no public video with this ID")):
        s = src[vid]
        assert s["rights_status"] == rights.MANUAL and s["status"] == "needs_rights", s
        assert not log[s["id"]]["used"] and log[s["id"]]["why"].startswith("Not covered: channel not confirmed")
        assert why in log[s["id"]]["why"], log[s["id"]]["why"]
    assert not hunts()  # nothing unconfirmed is clipped (or downloaded from the other link)...
    assert not [a for a in state.open_actions() if a["key"].startswith("rights:")]  # ...or asked about
    ok = src["mytalk000002"]
    assert ok["channel_check"]["state"] == "verified" and ok["rights_status"] == rights.OWNED
    assert ok["status"] == "needs_file"  # yours; YouTube does not let ClipFoundry download it, so it waits for the file


def test_a_feed_that_falsely_claims_an_allowed_channel_is_skipped(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    g, t = env["g"], env["t"]
    rights.add_agreement("Pod Creator", [POD, "@podcreator"], "Email of 2026-09-01: you may clip my episodes")
    rights.add_rule("channel", POD, rights.ALLOWLISTED, "Clipping program")  # a rule for that channel on any site
    g.add_video("stolen000001", "Episode 1", OTHER, duration="PT50M")
    g.add_video("podep0000002", "Episode 2", POD, duration="PT50M")
    g.add_video("podep0000004", "Episode 4", POD, duration="PT50M")
    t.authors.update({"7300000000000000011": ("someoneelse", "Someone Else"),
                      "7300000000000000012": ("PodCreator", "Pod Creator")})
    src = feed(env, [
        # someone else's video, listed under the creator's channel
        {"id": "stolen000001", "title": "Big game highlights", "platform": "youtube", "channel_id": POD,
         "url": "https://www.youtube.com/watch?v=stolen000001"},
        # the creator's real video, paired with a file from somewhere else
        {"id": "podep0000002", "title": "Gardening in spring", "platform": "youtube", "channel_id": POD,
         "url": "https://cdn.example.com/ep2.mp4"},
        # someone else's TikTok, with the creator's name in the link
        {"id": "7300000000000000011", "title": "Street food tour", "platform": "tiktok", "channel_id": "@podcreator",
         "url": "https://www.tiktok.com/@podcreator/video/7300000000000000011"},
        # a platform ClipFoundry cannot ask
        {"id": "podep0000003", "title": "Night sky photography", "platform": "feed", "channel_id": POD,
         "url": "https://cdn.example.com/ep3.mp4"},
        # the controls: really the creator's videos, with links to exactly them
        {"id": "podep0000004", "title": "Episode 4", "platform": "youtube", "channel_id": POD,
         "url": "https://www.youtube.com/watch?v=podep0000004"},
        {"id": "7300000000000000012", "title": "Studio tour", "platform": "tiktok", "channel_id": "@podcreator",
         "url": "https://www.tiktok.com/@podcreator/video/7300000000000000012"},
    ])
    log = activity()
    for vid, why in (("stolen000001", "YouTube says this video belongs to another channel (Channel 0009)"),
                     ("podep0000002", "The link does not lead to this exact video"),
                     ("7300000000000000011", "TikTok says this video belongs to another channel (Someone Else)"),
                     ("podep0000003", "can only confirm YouTube and TikTok channels")):
        s = src[vid]
        assert s["rights_status"] == rights.MANUAL and s["status"] == "needs_rights", (vid, s)
        assert why in log[s["id"]]["why"], (vid, log[s["id"]]["why"])
    assert not hunts()
    assert db.fetch("sources", src["stolen000001"]["id"])["channel_check"]["official"] == OTHER
    for vid, by in (("podep0000004", "YouTube Data API"), ("7300000000000000012", "TikTok")):
        s = src[vid]  # confirmed (TikTok user names ignore case), so the agreement counts
        assert s["rights_status"] == rights.ALLOWLISTED and s["channel_check"]["by"] == by, (vid, s)
        assert rights.evaluate(s)["auto_allowed"]


def test_a_confirmed_channel_still_needs_a_rule(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights

    env["g"].add_video("nobody000001", "A talk", "UCnobody00000000001", duration="PT50M")
    s = feed(env, [{"id": "nobody000001", "platform": "youtube", "channel_id": "UCnobody00000000001",
                    "url": "https://www.youtube.com/watch?v=nobody000001"}])["nobody000001"]
    assert s["channel_check"]["state"] == "verified"  # YouTube confirms who posted it...
    assert s["rights_status"] == rights.MANUAL and s["status"] == "needs_rights"  # ...which gives no permission
    assert activity()[s["id"]]["why"] == "Not covered: No agreement, license or ownership covers this video"
    rights.add_rule("channel", "UCnobody00000000001", rights.ALLOWLISTED, "Clipping program", platform="youtube")
    run("rights_check")
    assert db.fetch("sources", s["id"])["rights_status"] == rights.ALLOWLISTED


def test_videos_queued_before_the_check_cannot_get_around_it(env):
    """Sources a feed created before channels were confirmed, stored as covered and already waiting for the Clip
    Hunter: they lose their turn before anything is downloaded, and anything clipped is held back."""
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, rights, scout, verify

    g = env["g"]
    rights.add_agreement("Pod Creator", [POD], "Email of 2026-09-01: you may clip my episodes")
    g.add_video("stolen000002", "Episode 5", OTHER, duration="PT50M")
    g.add_video("podep0000005", "Episode 6", POD, duration="PT50M")

    def old_row(vid: str, status: str, url: str = "https://cdn.example.com/ep.mp4") -> dict:
        return db.insert("sources", {"platform": "youtube", "external_id": vid, "title": f"Episode {vid}",
                                     "channel_id": POD, "url": url, "status": status, "source_score": 90.0,
                                     "expected_clips": 3.0, "rights_status": rights.ALLOWLISTED,
                                     "selected_day": scout.local_day(db.get_settings())})

    queued = old_row("stolen000002", "queued", "https://www.youtube.com/watch?v=stolen000002")
    job = queue.enqueue("hunt_source", {"source_id": queued["id"]}, idem_key=f"hunt:{queued['id']}",
                        ref=("source", queued["id"]))
    host.WorkerHost(periodic=False)
    claimed = queue.claim("clip_hunter", "test")
    assert claimed["id"] == job["id"]
    out = host.HANDLERS["hunt_source"](host.Job(claimed, "test"))
    assert out["skipped"] and "channel not confirmed" in out["message"]  # skipped, not failed
    row = db.fetch("sources", queued["id"])
    assert row["status"] == "needs_rights" and not row["project_id"]  # nothing was downloaded or clipped
    assert "belongs to another channel" in activity()[row["id"]]["why"]
    with pytest.raises(rights.RightsBlocked):  # a clip that already exists is held back at scheduling and publishing
        rights.gate(row, "schedule")
    with pytest.raises(rights.RightsBlocked):
        rights.gate(row, "publish")

    # waiting in the queue: the maintenance check cancels the turn of the false one only
    waiting = old_row("stolen000003", "queued", "https://www.youtube.com/watch?v=stolen000003")
    g.add_video("stolen000003", "Episode 7", OTHER, duration="PT50M")
    fine = old_row("podep0000005", "queued", "https://www.youtube.com/watch?v=podep0000005")
    jobs = {s["id"]: queue.enqueue("hunt_source", {"source_id": s["id"]}, idem_key=f"hunt:{s['id']}",
                                   ref=("source", s["id"])) for s in (waiting, fine)}
    out = scout.confirm_channels()
    assert out["channels_checked"] == 2
    assert db.fetch("sources", waiting["id"])["status"] == "needs_rights"
    assert queue.get(jobs[waiting["id"]]["id"])["status"] == "canceled"
    assert db.fetch("sources", fine["id"])["status"] == "queued"  # really the creator's: it keeps its turn
    assert queue.get(jobs[fine["id"]]["id"])["status"] == "queued"
    assert rights.evaluate(db.fetch("sources", fine["id"]))["status"] == rights.ALLOWLISTED

    # stored as eligible before the upgrade: judged again before it is picked
    eligible = old_row("stolen000004", "eligible", "https://www.youtube.com/watch?v=stolen000004")
    g.add_video("stolen000004", "Episode 8", OTHER, duration="PT50M")
    verify.ensure([eligible])
    picked = scout.select_for_today({**db.get_settings(), "autopilot_sources_per_day": 30})
    assert eligible["id"] not in [p["id"] for p in picked]
    assert db.fetch("sources", eligible["id"])["status"] == "needs_rights"


def test_an_unreachable_platform_leaves_the_video_unconfirmed_and_asks_again_later(env):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, verify

    rights.add_agreement("Pod Creator", [POD], "Email of 2026-09-01: you may clip my episodes")
    env["g"].add_video("podep0000009", "Episode 9", POD, duration="PT50M")
    db.save_settings({"youtube_api_key": ""})
    db.delete_account("youtube")  # and no connected account: YouTube cannot be asked
    s = feed(env, [{"id": "podep0000009", "platform": "youtube", "channel_id": POD, "url": ""}])["podep0000009"]
    assert s["rights_status"] == rights.MANUAL and "YouTube is not connected" in activity()[s["id"]]["why"]
    assert not verify.due(s) and verify.due(s, time.time() + 3601)  # asked again after an hour, not every scan
    db.save_settings({"youtube_api_key": "test-api-key"})
    verify.ensure([s], now=time.time() + 3601)
    assert rights.apply(s)["rights_status"] == rights.ALLOWLISTED


def test_a_feed_cannot_overwrite_what_youtube_reported(env):
    from clipfoundry import db

    env["g"].add_video("kids00000001", "Cartoon hour", OTHER, duration="PT50M", made_for_kids=True)
    env["g"].popular = ["kids00000001"]
    db.save_settings({"trend_topics": "cartoon"})
    run("trend_scan")
    feed(env, [{"id": "kids00000001", "platform": "youtube", "channel_id": MINE, "url": ""}])
    sig = db.select("trend_signals", "external_id = 'kids00000001'")[0]
    assert sig["provider"].startswith("youtube_") and sig["channel_id"] == OTHER and sig["raw"]["made_for_kids"]
    src = db.select("sources", "external_id = 'kids00000001'")[0]
    assert src["status"] == "skipped"  # made for kids, as YouTube says


def test_links_are_read_strictly():
    from clipfoundry.autopilot import verify

    assert verify.link_video("youtube", "https://www.youtube.com/watch?v=abcdefghijk&t=5") == ("abcdefghijk", "")
    assert verify.link_video("youtube", "https://youtu.be/abcdefghijk") == ("abcdefghijk", "")
    assert verify.link_video("youtube", "https://m.youtube.com/shorts/abcdefghijk") == ("abcdefghijk", "")
    assert verify.link_video("youtube", "") == ("", "")
    for bad in ("https://cdn.example.com/abcdefghijk.mp4", "https://youtube.com.evil.example/watch?v=abcdefghijk",
                "ftp://youtube.com/watch?v=abcdefghijk", "https://www.youtube.com/watch?v=a,b"):
        assert verify.link_video("youtube", bad) is None, bad
    assert verify.link_video("tiktok", "https://www.tiktok.com/@pod.creator/video/7300000000000000012") == (
        "7300000000000000012", "pod.creator")
    assert verify.link_video("tiktok", "https://www.tiktok.com/@pod/photo/7300000000000000012") is None
    assert verify.link_video("feed", "https://cdn.example.com/x.mp4") is None
