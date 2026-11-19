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


def clips_after(chans, source, earlier_post, title, plan=True):  # noqa: F811
    """One more finished clip of the same input; planned at once unless `plan` is False."""
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
    if not plan:
        return clip
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    return {row["connection_id"]: row for row in db.select("scheduled_publications", "clip_id = ?", (clip["id"],))}


def per_channel(source, *channels):
    from clipfoundry import db

    rows = db.select("scheduled_publications", "source_id = ? AND status NOT IN ('canceled', 'replaced')",
                     (source["id"],))
    return [len({r["clip_id"] for r in rows if r["connection_id"] == c["id"]}) for c in channels]


def test_a_clip_planned_again_on_its_channel_counts_for_it(chans):  # noqa: F811
    """Clips 1-3 went A, B, A. Clip 3's post is canceled and clip 4 is ready before the next pass: clip 3 is
    planned again on A and counts there, so clip 4 goes to B (two each, not three to one)."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    source = add_file(a, b, split="turns")
    posts = clips(chans, source, 3)
    assert [list(p) for p in posts] == [[a["id"]], [b["id"]], [a["id"]]]
    scheduler.cancel(posts[2][a["id"]]["id"], "Canceled by you")
    fourth = clips_after(chans, source, posts[0][a["id"]], TITLES[3], plan=False)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 2
    assert {r["connection_id"] for r in db.select("scheduled_publications", "clip_id = ?", (fourth["id"],))} \
        == {b["id"]}
    assert per_channel(source, a, b) == [2, 2]


def test_inputs_with_one_clip_each_still_share_the_channels(chans):  # noqa: F811
    """Each video or stream is its own request. When each has one clip, every one would start with the first
    channel ticked; the clips over all inputs that take turns decide the tie instead."""
    from clipfoundry import db

    a, b, c = chans["a"], chans["b"], add_channel(chans["google"], "UCchanC", "Channel C")
    went = []
    for k in range(6):
        source = add_file(a, b, c, split="turns")
        _, posts = ready(chans["tmp"], source, created=1, title=TITLES[k])
        went.append(list(posts))
    assert went == [[a["id"]], [b["id"]], [c["id"]], [a["id"]], [b["id"]], [c["id"]]]
    # an input whose channels do not take turns is not counted: it gives every channel every clip anyway
    every = add_file(a, b)
    ready(chans["tmp"], every, created=2, title=TITLES[6])
    source = add_file(a, b, split="turns")
    assert list(ready(chans["tmp"], source, created=1, title=TITLES[7])[1]) == [a["id"]]
    assert db.select("source_submissions", "source_id = ?", (every["id"],))


def test_a_clip_uploaded_by_hand_to_a_chosen_channel_stays_there(chans):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    source = add_file(a, b, split="turns")
    posts = clips(chans, source, 1)
    assert list(posts[0]) == [a["id"]]
    by_hand = clips_after(chans, source, posts[0][a["id"]], TITLES[1], plan=False)
    db.create_publication(by_hand["id"], "youtube", status="done", connection_id=a["id"])  # uploaded by the owner
    scheduler.plan_new(db.get_settings(), time.time())
    assert db.select("scheduled_publications", "clip_id = ?", (by_hand["id"],)) == []  # never to a second channel
    # and it counts for that channel: the next clip goes to B
    nxt = clips_after(chans, source, posts[0][a["id"]], TITLES[2])
    assert list(nxt) == [b["id"]]


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
    # a link added here that turns out to be a recorded video is clipped like any video: no stream choices shown
    project = db.create_project("A recorded video", origin="autopilot", source_id=source["id"])
    db.update("sources", source["id"], project_id=project["id"])
    shown = next(row for row in api.get("/api/autopilot/submissions/live", headers=H).json()
                 if row["id"] == source["id"])
    assert shown["live"]["pick_label"] == shown["live"]["framing_label"] == ""


def test_a_stronger_clip_approved_under_the_request_takes_the_weaker_posts_slot(chans):  # noqa: F811
    """A video's own upload request approves a replacement automatically. Like an approval by the owner, the
    replacement then takes the weaker post's slot: two approved posts never share one slot of a channel."""
    import datetime as dt

    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions
    from clipfoundry.pipeline import fingerprint
    from test_post_to_channels import make_clip

    a, b = chans["a"], chans["b"]
    db.save_settings({"autopilot_youtube_daily_limit": 1, "autopilot_dynamic_replacement": True,
                      "autopilot_replacement_cooldown_hours": 0})
    settings, now = db.get_settings(), time.time()
    start = now + 60.0 * (scheduler.LOCK_MINUTES + 5)
    today = scheduler._local(now, settings).date()  # noqa: SLF001 - the planner's own calendar
    per_channel = sum(t >= start for d in range(scheduler.HORIZON_DAYS + 1)
                      for t in scheduler.grid(settings, today + dt.timedelta(days=d), 1))
    source = add_file(a, b, split="turns")
    first = make_clip(chans["tmp"], TITLES[0], 90, source=source)
    project_id = first["project_id"]
    db.update_project(project_id, source_path=source["local_path"])
    db.update("sources", source["id"], project_id=project_id, status="analyzed")
    submissions.bind_project(db.fetch("sources", source["id"]), db.get_project(project_id))
    db.update_clip(first["id"], status="rejected")  # only the clips made below take part
    words = ["budget", "hiring", "office", "lunch", "roadmap", "pricing", "refund", "manual", "server", "launch"]

    def made(n, score):
        title = f"Story {n} about the {words[n % 10]} and the {words[(n * 7 + 3) % 10]}"
        video = chans["tmp"] / f"slot-{time.time_ns()}.mp4"
        video.write_bytes(b"video " + title.encode())
        clip = db.create_clip(project_id, start=n * 40, end=n * 40 + 30, title=title, status="ready",
                              output_path=str(video), duration=30.0, caption_text=title, score=score)
        db.insert("clip_scores", {"clip_id": clip["id"], "clip": score, "diversity": score, "retention": score},
                  key="clip_id")
        db.insert("clip_fingerprints", {"clip_id": clip["id"], "phash": [], "title_norm": title.lower(),
                                        "text_sig": fingerprint.text_signature(title + str(n) * 9)}, key="clip_id")
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": "youtube", "style": "direct",
                                          "title": title, "description": title, "caption": title, "tags": ["test"],
                                          "hashtags": ["#test"], "score": score, "selected": 1})
        passed_report(clip)
        return clip

    for n in range(2 * per_channel):  # every slot of both channels holds a weak clip
        made(n, 40.0)
    scheduler.plan_new(db.get_settings(), time.time())
    strong = made(50, 99.0)
    assert scheduler.plan_new(db.get_settings(), time.time())["replaced"] == 1
    (mine,) = db.select("scheduled_publications", "clip_id = ?", (strong["id"],))
    assert mine["status"] == "approved" and mine["approval"]["by"] == "submission"
    weak = post(mine["replaces"])
    assert weak["status"] == "replaced" and weak["replaced_by"] == mine["id"]
    for channel in (a, b):
        approved = db.select("scheduled_publications", "connection_id = ? AND status = 'approved'", (channel["id"],))
        assert len({r["planned_at"] for r in approved}) == len(approved) <= per_channel  # one post per slot
