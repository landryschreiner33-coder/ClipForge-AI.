"""Split a video's or stream's clips between the chosen YouTube channels: each clip goes to one of them, in turn.

Built on the channel choice (tests/test_post_to_channels.py): fake platforms only, no real account is used.
"""
from __future__ import annotations

import time

import pytest

from quality_stub import passed_report
from test_autopilot_publish import H
from test_multi_accounts import api, env  # noqa: F401 - fake Google/TikTok with several accounts at once
from test_post_to_channels import add_channel, add_file, chans, options, post, ready  # noqa: F401

TITLES = ["Ask customers before you build anything", "Why the cheapest plan sold the most",
          "The meeting that changed our roadmap", "How one refund taught us pricing",
          "Nobody read the manual we wrote", "A competitor copied the wrong feature",
          "The launch day server story", "What the first hire got right"]


def clips(chans, source, count):  # noqa: F811
    """`count` finished clips of one submitted video, planned one after the other; returns each clip's posts."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.pipeline import fingerprint

    out = []
    first, posts = ready(chans["tmp"], source, created=1, title=TITLES[0])
    out.append(posts)
    project_id = first["project_id"]
    for title in TITLES[1:count]:
        video = chans["tmp"] / f"clip-{time.time_ns()}.mp4"
        video.write_bytes(b"video " + title.encode())
        clip = db.create_clip(project_id, start=0, end=30, title=title, status="ready", output_path=str(video),
                              duration=30.0, caption_text=title, score=80.0)
        db.insert("clip_scores", {"clip_id": clip["id"], "clip": 80.0, "diversity": 80.0, "retention": 60.0},
                  key="clip_id")
        db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(title),
                                        "phash": [], "title_norm": title.lower()}, key="clip_id")
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "style": "direct",
                                          "title": title, "description": title, "caption": title, "tags": ["test"],
                                          "hashtags": ["#test"], "score": 60.0, "selected": 1})
        passed_report(clip)
        assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
        out.append({row["connection_id"]: row for row in db.select("scheduled_publications", "clip_id = ?",
                                                                   (clip["id"],))})
    return out


def test_taking_turns_needs_two_channels_and_is_part_of_the_request(chans):  # noqa: F811
    from clipfoundry.autopilot import submissions

    a, b = chans["a"], chans["b"]
    with pytest.raises(ValueError, match="at least two YouTube channels"):
        add_file(a, split="turns")
    with pytest.raises(ValueError, match="at least two YouTube channels"):
        add_file(account_id="UCchanA", split="turns")  # a request without a channel list is one channel
    with pytest.raises(ValueError, match="shared between the channels"):
        add_file(a, b, split="sideways")
    source = add_file(b, a, split="turns")
    row = submissions.for_source(source)
    assert row["settings"]["split"] == "turns" and submissions.takes_turns(row["settings"])
    assert "YouTube channels Channel B and Channel A (each clip to one of them, taking turns) as private" in row["text"]
    assert submissions.item(source)["submission"]["split"] == "turns"
    # the request still covers both channels: which one a clip goes to is decided when it is planned
    assert submissions.target_connections(source) == [b["id"], a["id"]]

    every = add_file(a, b)  # not asked for: every channel gets every clip, stored exactly as before
    assert "split" not in submissions.for_source(every)["settings"]
    assert submissions.item(every)["submission"]["split"] == "each"
    assert "taking turns" not in submissions.for_source(every)["text"]
    assert submissions.item(add_file(a, b, split="each"))["submission"]["split"] == "each"
    assert submissions.item(add_file(auto_upload=False))["submission"]["split"] == "each"


def test_each_clip_goes_to_one_channel_and_the_channels_take_turns(chans):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    source = add_file(b, a, split="turns")
    posts = clips(chans, source, 5)
    assert [list(p) for p in posts] == [[b["id"]], [a["id"]], [b["id"]], [a["id"]], [b["id"]]]
    for planned in posts:
        (row,) = planned.values()
        assert row["status"] == "approved" and row["approval"]["by"] == "submission"
        assert row["approval"]["connection_id"] == row["connection_id"]
    # planning again adds nothing: no clip gets a second post on the other channel
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 0
    assert len(db.select("scheduled_publications", "source_id = ?", (source["id"],))) == 5


def test_several_clips_planned_in_one_pass_are_shared_evenly(chans):  # noqa: F811
    """Clips that become ready together (a stream's backlog) are dealt out in the same pass, before any of their
    posts exists."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    c = add_channel(chans["google"], "UCchanC", "Channel C")
    source = add_file(a, b, c, split="turns")
    posts = clips(chans, source, 1)
    project_id = db.select("scheduled_publications", "source_id = ?", (source["id"],))[0]["clip_id"]
    project_id = db.get_clip(project_id)["project_id"]
    from clipfoundry.pipeline import fingerprint

    for title in TITLES[1:7]:
        video = chans["tmp"] / f"batch-{time.time_ns()}.mp4"
        video.write_bytes(b"video " + title.encode())
        clip = db.create_clip(project_id, start=0, end=30, title=title, status="ready", output_path=str(video),
                              duration=30.0, caption_text=title, score=80.0)
        db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(title),
                                        "phash": [], "title_norm": title.lower()}, key="clip_id")
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "style": "direct",
                                          "title": title, "description": title, "caption": title, "tags": ["test"],
                                          "hashtags": ["#test"], "score": 60.0, "selected": 1})
        passed_report(clip)
    found = scheduler.candidates(db.get_settings(), time.time())
    assert len(found) == 6 and len({item["clip"]["id"] for item in found}) == 6  # one channel per clip
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 6
    rows = db.select("scheduled_publications", "source_id = ?", (source["id"],))
    per_channel = {cid: sum(r["connection_id"] == cid for r in rows) for cid in (a["id"], b["id"], c["id"])}
    assert list(posts[0]) == [a["id"]] and per_channel == {a["id"]: 3, b["id"]: 2, c["id"]: 2}
    assert len({r["clip_id"] for r in rows}) == 7
    assert submissions.takes_turns(submissions.for_source(source)["settings"])


def test_a_clip_keeps_its_channel_whatever_becomes_of_its_post(chans):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    source = add_file(a, b, split="turns")
    posts = clips(chans, source, 2)
    first = posts[0][a["id"]]
    scheduler.cancel(first["id"], "Canceled by you")
    assert post(first["id"])["status"] == "canceled"
    # the canceled clip is planned again on the next pass, as before; it is still channel A's clip
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    rows = db.select("scheduled_publications", "clip_id = ?", (first["clip_id"],))
    assert {r["connection_id"] for r in rows} == {a["id"]} and len(rows) == 2
    # the next new clip continues the turns: A has one (its canceled post does not count), B has one
    more = clips_after(chans, source, first, TITLES[2])
    assert list(more) == [a["id"]] or list(more) == [b["id"]]
    counts = {cid: len({r["clip_id"] for r in db.select(
        "scheduled_publications", "source_id = ? AND connection_id = ? AND status != 'canceled'",
        (source["id"], cid))}) for cid in (a["id"], b["id"])}
    assert abs(counts[a["id"]] - counts[b["id"]]) <= 1


def clips_after(chans, source, earlier_post, title):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.pipeline import fingerprint

    project_id = db.get_clip(earlier_post["clip_id"])["project_id"]
    video = chans["tmp"] / f"later-{time.time_ns()}.mp4"
    video.write_bytes(b"video " + title.encode())
    clip = db.create_clip(project_id, start=0, end=30, title=title, status="ready", output_path=str(video),
                          duration=30.0, caption_text=title, score=80.0)
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(title),
                                    "phash": [], "title_norm": title.lower()}, key="clip_id")
    db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "style": "direct",
                                      "title": title, "description": title, "caption": title, "tags": ["test"],
                                      "hashtags": ["#test"], "score": 60.0, "selected": 1})
    passed_report(clip)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    return {row["connection_id"]: row for row in db.select("scheduled_publications", "clip_id = ?", (clip["id"],))}


def test_a_channel_that_needs_reconnect_gets_no_new_clips_and_catches_up(chans):  # noqa: F811
    from clipfoundry import db

    a, b = chans["a"], chans["b"]
    source = add_file(a, b, split="turns")
    posts = clips(chans, source, 2)
    assert [list(p) for p in posts] == [[a["id"]], [b["id"]]]
    db.disconnect_connection(b["id"])  # channel B needs Reconnect
    held = [clips_after(chans, source, posts[0][a["id"]], title) for title in TITLES[2:4]]
    assert [list(p) for p in held] == [[a["id"]], [a["id"]]]  # uploads go on with the channel that works
    assert post(posts[1][b["id"]]["id"])["connection_id"] == b["id"]  # B's own clip stays B's and waits for it
    add_channel(chans["google"], "UCchanB", "Channel B")  # reconnected: the same connection is usable again
    assert db.get_connection(b["id"])["status"] == "connected"
    after = [clips_after(chans, source, posts[0][a["id"]], title) for title in TITLES[4:6]]
    assert [list(p) for p in after] == [[b["id"]], [b["id"]]]  # B catches up to three each


def test_the_app_takes_the_split_with_a_stream_and_shows_it(chans, api, monkeypatch):  # noqa: F811
    import ipaddress

    from clipfoundry import db, netguard
    from clipfoundry.autopilot import submissions

    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("8.8.8.8")])  # no real lookups
    a, b = chans["a"], chans["b"]
    body = {**options(a, b), "url": "https://www.twitch.tv/somestreamer", "live": True, "split": "turns",
            "live_pick": "balanced", "live_framing": "split"}
    added = api.post("/api/autopilot/submissions/link", headers=H, json=body)
    assert added.status_code == 200, added.text
    source = db.fetch("sources", added.json()["item"]["id"])
    assert submissions.for_source(source)["settings"]["split"] == "turns"
    assert source["intake"]["live_choices"] == {"pick": "balanced", "framing": "split"}
    shown = api.get("/api/autopilot/submissions/live", headers=H).json()[0]
    assert shown["submission"]["split"] == "turns"
    assert shown["live"]["pick"] == "balanced" and shown["live"]["framing"] == "split"
    assert shown["live"]["pick_label"] == "Balanced" and shown["live"]["framing_label"] == "Always split view"
    assert not shown["live"]["clipping_stopped"] and shown["live"]["note"] == ""
    for wrong in ({"split": "sideways"}, {"live_pick": "everything"}, {"live_framing": "sideways"}):
        refused = api.post("/api/autopilot/submissions/link", headers=H,
                           json={**body, "url": "https://kick.com/another", **wrong})
        assert refused.status_code == 400, wrong
    assert len(db.select("sources")) == 1  # nothing was saved for a refused choice
    # a stream added without choices follows Settings; a video never carries live choices
    plain = api.post("/api/autopilot/submissions/link", headers=H,
                     json={**options(a), "url": "https://kick.com/plain", "live": True})
    assert plain.status_code == 200 and "live_choices" not in db.fetch("sources", plain.json()["item"]["id"])["intake"]
    video = api.post("/api/autopilot/submissions/link", headers=H,
                     json={**options(a), "url": "https://www.youtube.com/watch?v=abcdefghijk", "live_pick": "most"})
    assert video.status_code == 200 and "live_choices" not in db.fetch("sources", video.json()["item"]["id"])["intake"]
