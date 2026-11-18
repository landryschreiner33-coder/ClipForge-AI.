"""Choose which YouTube channels each submitted video posts to: one planned post per chosen channel, each bound to
its own channel from approval to upload. Fake platforms only (tests/multi_fakes.py): every token and upload belongs
to one fake channel, so these tests prove which channel received which bytes. No real account is used.
"""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

from quality_stub import passed_report
from test_autopilot_publish import H, run_publish
from test_autopilot_scheduler import make_clip
from test_multi_accounts import api, env  # noqa: F401 - fake Google/TikTok with several accounts at once

STATEMENT = "I filmed this talk myself and may post clips from it."


def add_channel(google, channel: str, title: str) -> dict:
    from clipfoundry import db
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    settings = db.get_settings()
    verifier = code_verifier()
    code = google.approve(youtube.auth_url(settings, "http://127.0.0.1:8765/cb", "st", challenge_s256(verifier)),
                          channel=channel, title=title)
    return youtube.exchange_code(settings, code, verifier, "http://127.0.0.1:8765/cb")


def add_tiktok(fake, open_id: str, name: str) -> dict:
    from clipfoundry import db
    from clipfoundry.publish import tiktok
    from clipfoundry.publish.common import challenge_hex, code_verifier

    settings = db.get_settings()
    verifier = code_verifier()
    code = fake.approve(tiktok.auth_url(settings, "http://127.0.0.1:8765/cb", "st", challenge_hex(verifier)),
                        open_id=open_id, name=name)
    return tiktok.exchange_code(settings, code, verifier, "http://127.0.0.1:8765/cb")


@pytest.fixture
def chans(env):  # noqa: F811
    from clipfoundry import db

    google, tik, tmp = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_tiktok": False,
                      "autopilot_min_gap_minutes": 0, "autopilot_input_mode": "submitted",
                      "autopilot_review_before_publish": True})
    a = add_channel(google, "UCchanA", "Channel A")
    b = add_channel(google, "UCchanB", "Channel B")
    assert a["is_default"] and not b["is_default"]
    return {"google": google, "tiktok": tik, "tmp": tmp, "a": a, "b": b}


def options(*chosen: dict, **changes) -> dict:
    from clipfoundry.autopilot import submissions

    shown = submissions.setup()
    body = {"auto_upload": True, "privacy": shown["privacy"], "made_for_kids": False,
            "audience_version": shown["audience"]["group_version"], "reuse_basis": "owned",
            "reuse_statement": STATEMENT, "agreed": True}
    if chosen:
        body["connections"] = [{"id": c["id"], "account_id": c["external_id"]} for c in chosen]
        body["account_id"] = chosen[0]["external_id"]
    return {**body, **changes}


def add_file(*chosen: dict, **changes) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    before = {row["id"] for row in db.select("sources")}
    submissions.add_file(io.BytesIO(os.urandom(256)), "My talk.mp4", options(*chosen, **changes))
    fresh = [row for row in db.select("sources") if row["id"] not in before]
    assert len(fresh) == 1
    return fresh[0]


def ready(tmp, source: dict, created: int, title: str = "A complete thought worth sharing") -> tuple[dict, dict]:
    """Finish one clip of the submitted video and plan it; returns the clip and its posts by connection_id."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    clip = make_clip(tmp, title, 90, source=source)
    project = db.get_project(clip["project_id"])
    db.update_project(project["id"], source_path=source["local_path"])
    db.update("sources", source["id"], project_id=project["id"], status="analyzed")
    submissions.bind_project(db.fetch("sources", source["id"]), db.get_project(project["id"]))
    passed_report(clip)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == created
    return clip, {row["connection_id"]: row for row in db.select("scheduled_publications", "clip_id = ?",
                                                                 (clip["id"],))}


def post(item_id: str) -> dict:
    from clipfoundry import db

    return db.fetch("scheduled_publications", item_id)


def owner_item(tmp, connection_id: str, title: str = "Talk to customers first") -> dict:
    """A planned post bound to one channel that the owner approves himself (not from a submitted video)."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    video = tmp / f"owner-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(4096))
    project = db.create_project("talk", status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=20, title=title, status="ready", output_path=str(video),
                          duration=20.0, caption_text="Talk to customers first.", score=72.0)
    passed_report(clip)
    item = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "platform": "youtube", "title": title, "description": "Talk to customers first.",
        "tags": [], "privacy": "private", "options": {"made_for_kids": None}, "connection_id": connection_id,
        "planned_at": time.time() + 7200, "status": "awaiting_approval", "final_score": 70})
    return scheduler.approve(item["id"], {"options": {"made_for_kids": False}})


# ------------------------------------------------------------------ B1: which accounts start ticked
def test_accounts_say_which_start_ticked_and_which_can_post(chans, api):  # noqa: F811
    from clipfoundry import db

    a, b = chans["a"], chans["b"]
    rows = {c["account_id"]: c for c in api.get("/api/connections").json()["connections"]}
    assert rows["UCchanA"]["post_by_default"] is True and rows["UCchanB"]["post_by_default"] is False
    assert rows["UCchanA"]["postable"] is True and rows["UCchanB"]["postable"] is True
    assert rows["UCchanA"]["can_direct_post"] is False and rows["UCchanA"]["can_inbox"] is False
    ticked = api.patch(f"/api/connections/{b['id']}", headers=H, json={"post_by_default": True})
    assert ticked.status_code == 200 and ticked.json()["post_by_default"] is True
    assert db.get_connection(b["id"])["info"]["needs_reconnect"] is False  # the flag merged into info
    untick = api.patch(f"/api/connections/{a['id']}", headers=H, json={"post_by_default": False}).json()
    assert untick["post_by_default"] is False and untick["is_default"] is True  # the default stays the default
    assert api.patch(f"/api/connections/{a['id']}", headers=H, json={"nickname": "Main"}).json()["post_by_default"] \
        is False  # other edits keep the choice
    api.post(f"/api/connections/{b['id']}/disconnect", headers=H)
    rows = {c["account_id"]: c for c in api.get("/api/connections").json()["connections"]}
    assert rows["UCchanB"]["postable"] is False and rows["UCchanB"]["post_by_default"] is True
    creator = add_tiktok(chans["tiktok"], "open-a", "Creator A")
    tik = api.get("/api/connections?platform=tiktok").json()["connections"][0]
    assert tik["id"] == creator["id"] and tik["can_direct_post"] is True and tik["can_inbox"] is True
    other, _ = db.upsert_connection("youtube", "UCforeign", {"access_token": "x", "expires_at": 9e9},
                                    workspace_id="ws-someone-else")
    assert api.patch(f"/api/connections/{other['id']}", headers=H, json={"post_by_default": True}).status_code == 404
    assert "post_by_default" not in (db.get_connection(other["id"])["info"] or {})


# ------------------------------------------------------------------ B2: choosing channels for a video
def test_setup_lists_every_channel_and_needs_only_one_usable(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    a, b = chans["a"], chans["b"]
    shown = submissions.setup()
    assert shown["account_id"] == "UCchanA" and shown["can_upload"]  # older callers still see the default
    assert [(c["id"], c["account_id"], c["name"], c["is_default"], c["post_by_default"], c["ok"])
            for c in shown["channels"]] == [(a["id"], "UCchanA", "Channel A", True, True, True),
                                            (b["id"], "UCchanB", "Channel B", False, False, True)]
    db.disconnect_connection(a["id"])
    shown = submissions.setup()
    assert shown["can_upload"] and not shown["channels"][0]["ok"] and shown["channels"][0]["text"]
    db.disconnect_connection(b["id"])
    shown = submissions.setup()
    assert not shown["can_upload"] and shown["blocker"] == "Connect a YouTube channel in Accounts first."


def test_a_video_can_be_sent_to_two_channels_and_the_request_names_both(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    a, b = chans["a"], chans["b"]
    db.update_connection(b["id"], nickname="Clips channel")
    source = add_file(b, a)
    row = submissions.for_source(source)
    cfg = row["settings"]
    assert cfg["connections"] == {b["id"]: "UCchanB", a["id"]: "UCchanA"}
    assert list(cfg["connections"]) == [b["id"], a["id"]]  # the owner's order
    assert cfg["account_id"] == "UCchanB"
    assert "YouTube channels Clips channel and Channel A as private" in row["text"]
    assert submissions.targets(cfg) == {b["id"]: "UCchanB", a["id"]: "UCchanA"}
    assert submissions.target_connections(source) == [b["id"], a["id"]]
    view = submissions.item(source)["submission"]
    assert view["channels"] == [{"id": b["id"], "name": "Clips channel", "account_id": "UCchanB"},
                                {"id": a["id"], "name": "Channel A", "account_id": "UCchanA"}]


def test_a_request_without_a_channel_list_still_means_the_default_channel(chans):
    from clipfoundry.autopilot import submissions

    a = chans["a"]
    source = add_file(account_id="UCchanA")
    row = submissions.for_source(source)
    assert "connections" not in row["settings"] and row["settings"]["account_id"] == "UCchanA"
    assert "YouTube channel UCchanA as private" in row["text"]
    assert submissions.targets(row["settings"]) == {}
    assert submissions.target_connections(source) == [""]
    assert submissions.item(source)["submission"]["channels"] == [
        {"id": a["id"], "name": "Channel A", "account_id": "UCchanA"}]
    with pytest.raises(ValueError, match="channel changed"):
        add_file(account_id="UCchanB")  # an old client naming another channel than the default
    only_local = add_file(auto_upload=False)
    assert submissions.target_connections(only_local) == []
    assert submissions.target_connections({"id": "no-such-source"}) is None


def test_channel_choices_are_checked_before_anything_is_saved(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    a, b = chans["a"], chans["b"]
    other, _ = db.upsert_connection("youtube", "UCforeign", {"access_token": "x", "expires_at": 9e9},
                                    workspace_id="ws-someone-else")
    tik = add_tiktok(chans["tiktok"], "open-a", "Creator A")
    before = {table: db.select(table) for table in ("sources", "source_submissions", "worker_jobs")}

    def refused(match: str, **changes) -> None:
        with pytest.raises(ValueError, match=match):
            submissions.add_file(io.BytesIO(os.urandom(64)), "x.mp4", options(**changes))

    refused("Choose at least one YouTube channel", connections=[], account_id="")
    refused("Choose at least one YouTube channel", account_id="")
    refused("only once", connections=[{"id": a["id"], "account_id": "UCchanA"}] * 2)
    refused("Channel B changed or needs Reconnect", connections=[{"id": b["id"], "account_id": "UCwrong"}])
    refused("changed or needs Reconnect", connections=[{"id": other["id"], "account_id": "UCforeign"}])
    refused("changed or needs Reconnect", connections=[{"id": tik["id"], "account_id": "open-a"}])
    refused("changed or needs Reconnect", connections=[{"id": "conn-missing", "account_id": "UCx"}])
    refused("at most 20", connections=[{"id": f"c{i}", "account_id": "UCx"} for i in range(21)])
    refused("Choose", connections=[{"id": a["id"]}])
    refused("Choose", connections="all")
    db.update_connection(b["id"], status="needs_reconnect", info={"needs_reconnect": True})
    refused("Channel B changed or needs Reconnect", connections=[{"id": b["id"], "account_id": "UCchanB"}])
    db.disconnect_connection(b["id"])
    refused("Channel B changed or needs Reconnect",
            connections=[{"id": a["id"], "account_id": "UCchanA"}, {"id": b["id"], "account_id": "UCchanB"}])
    assert {table: db.select(table) for table in before} == before


def test_the_routes_accept_a_channel_list(chans, api):  # noqa: F811
    from clipfoundry import db

    a, b = chans["a"], chans["b"]
    files = {"file": ("talk.mp4", os.urandom(128), "video/mp4")}
    ok = api.post("/api/autopilot/submissions/file", headers=H, files=files,
                  data={"options": json.dumps(options(a, b))})
    assert ok.status_code == 200, ok.text
    assert [c["id"] for c in ok.json()["submission"]["channels"]] == [a["id"], b["id"]]
    bad = api.post("/api/autopilot/submissions/file", headers=H, files={"file": ("t.mp4", b"other", "video/mp4")},
                   data={"options": json.dumps(options(a, connections=[{"id": a["id"], "account_id": 5}]))})
    assert bad.status_code in (400, 422)
    setup = api.get("/api/autopilot/submissions/setup").json()
    assert [c["id"] for c in setup["channels"]] == [a["id"], b["id"]]
    assert len(db.select("source_submissions")) == 1


# ------------------------------------------------------------------ B3: one post per chosen channel
def test_each_chosen_channel_gets_its_own_approved_post(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(a, b)
    _clip, posts = ready(chans["tmp"], source, created=2)
    assert set(posts) == {a["id"], b["id"]}
    for cid, account in ((a["id"], "UCchanA"), (b["id"], "UCchanB")):
        item = posts[cid]
        assert item["status"] == "approved" and item["approval"]["by"] == "submission"
        assert item["approval"]["account"] == account and item["approval"]["connection_id"] == cid
        assert item["reuse_confirmation"]["binding"]["account_id"] == account
        assert scheduler.approval_basis(item)["connection_id"] == cid
        assert not scheduler.approval_problem(item) and submissions.still_covers(item)
        assert scheduler._spacing_key(item) == f"upload_spacing:youtube:{account}"  # noqa: SLF001
        assert not rights.confirmation_problem(item)
    assert posts[a["id"]]["approval"]["hash"] != posts[b["id"]]["approval"]["hash"]
    # Planning again adds nothing: each channel already has this clip.
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 0
    assert submissions.problem(db.fetch("sources", source["id"])) == ""
    assert "not chosen" in submissions.problem(db.fetch("sources", source["id"]), connection_id="conn-other")


def test_making_another_channel_the_default_does_not_hold_chosen_channels(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(a, b)
    _clip, posts = ready(chans["tmp"], source, created=2)
    db.set_default_connection(b["id"])
    for item in posts.values():
        item = post(item["id"])
        assert not scheduler.approval_problem(item) and submissions.still_covers(item)
    scheduler.process_due(db.get_settings(), time.time())
    assert {post(i["id"])["status"] for i in posts.values()} == {"publishing"}


def test_a_channel_that_needs_reconnect_holds_only_its_own_post(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(a, b)
    _clip, posts = ready(chans["tmp"], source, created=2)
    db.update_connection(b["id"], status="needs_reconnect", info={"needs_reconnect": True})
    current = db.fetch("sources", source["id"])
    assert "Channel B needs Reconnect" in submissions.problem(current, connection_id=b["id"])
    assert submissions.problem(current, connection_id=a["id"]) == "" and submissions.problem(current) == ""
    scheduler.process_due(db.get_settings(), time.time())
    assert post(posts[a["id"]]["id"])["status"] == "publishing"
    held = post(posts[b["id"]]["id"])
    assert held["status"] == "awaiting_approval" and held["approval"] == {}
    assert not submissions.auto_approve(held, db.get_settings(), time.time())
    assert "Channel B needs Reconnect" in post(held["id"])["status_note"]
    db.update_connection(b["id"], status="connected", info={"needs_reconnect": False})  # the owner reconnected
    scheduler.process_due(db.get_settings(), time.time())
    again = post(held["id"])
    assert again["status"] == "publishing" and again["approval"]["account"] == "UCchanB"


def test_a_changed_account_behind_a_channel_is_not_covered(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(a, b)
    _clip, posts = ready(chans["tmp"], source, created=2)
    db.update("social_connections", b["id"], external_id="UCsomeoneelse")
    current = db.fetch("sources", source["id"])
    assert "The account behind Channel B changed" in submissions.problem(current, connection_id=b["id"])
    assert scheduler.approval_problem(post(posts[b["id"]]["id"]))
    assert not scheduler.approval_problem(post(posts[a["id"]]["id"]))


def test_the_publisher_uploads_each_post_to_its_own_channel_once(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import publisher

    a, b, google = chans["a"], chans["b"], chans["google"]
    source = add_file(a, b)
    clip, posts = ready(chans["tmp"], source, created=2)
    run_publish(posts[a["id"]]["id"])
    first = post(posts[a["id"]]["id"])
    assert first["status"] == "published"
    # Channel A having this clip is no reason to cancel channel B's post as a duplicate.
    assert publisher.already_published(post(posts[b["id"]]["id"])) == ""
    run_publish(posts[b["id"]]["id"])
    second = post(posts[b["id"]]["id"])
    assert second["status"] == "published", second
    pubs = {p["connection_id"]: p for p in db.list_publications(clip["id"], "youtube")}
    assert set(pubs) == {a["id"], b["id"]}
    assert pubs[a["id"]]["options"]["approved_account"] == "UCchanA"
    assert pubs[b["id"]]["options"]["approved_connection"] == b["id"]
    assert pubs[b["id"]]["options"]["approved_account"] == "UCchanB"
    data = Path(clip["output_path"]).read_bytes()
    assert [v["bytes"] for v in google.uploads_to("UCchanA")] == [data]
    assert [v["bytes"] for v in google.uploads_to("UCchanB")] == [data]
    run_publish(posts[b["id"]]["id"])  # nothing is uploaded twice
    assert len(google.videos) == 2 and len(db.list_publications(clip["id"], "youtube")) == 2
    # A second post of the same clip to channel A would be a duplicate.
    again = {**first, "id": "another-post", "publication_id": ""}
    assert publisher.already_published(again)


def test_the_publisher_holds_a_post_whose_own_channel_is_disconnected(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, state

    a, b, google = chans["a"], chans["b"], chans["google"]
    db.save_settings({"autopilot_review_before_publish": False})
    on_a = owner_item(chans["tmp"], a["id"], "Talk to customers first")
    on_b = owner_item(chans["tmp"], b["id"], "Build what they asked for")
    assert on_b["approval"]["account"] == "UCchanB" and on_b["approval"]["connection_id"] == b["id"]
    db.disconnect_connection(b["id"])
    with pytest.raises(queue.Wait):
        run_publish(on_b["id"])
    held = post(on_b["id"])
    assert held["status"] == "action_needed" and "Channel B" in held["status_note"]
    assert any(row["key"] == f"connect:{b['id']}" for row in state.open_actions())
    assert not any(row["key"] == "connect:youtube" for row in state.open_actions())
    run_publish(on_a["id"])
    assert post(on_a["id"])["status"] == "published"
    assert len(google.uploads_to("UCchanA")) == 1 and google.uploads_to("UCchanB") == []


def test_owner_approval_checks_the_posts_own_account(chans, api):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    db.save_settings({"autopilot_review_before_publish": False})
    item = owner_item(chans["tmp"], b["id"])
    scheduler.edit(item["id"], {"description": "Talk to customers first. Then build."})
    body = {"confirm": True, "made_for_kids": False}
    wrong = api.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers=H,
                     json={**body, "expected_account_id": "UCchanA"})
    assert wrong.status_code == 409
    right = api.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers=H,
                     json={**body, "expected_account_id": "UCchanB"})
    assert right.status_code == 200, right.text
    out = right.json()
    assert out["approval"]["account"] == "UCchanB" and out["account"]["connection_id"] == b["id"]
    assert out["account"]["name"] == "Channel B"
    db.set_default_connection(b["id"])
    db.set_default_connection(a["id"])
    assert not scheduler.approval_problem(post(item["id"]))


def bound_draft(tmp, connection_id: str, title: str = "A complete thought worth sharing") -> dict:
    """A planned post for one channel, made by the scheduler itself and waiting for the owner's review."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    clip = make_clip(tmp, title, 90)
    for meta in db.select("metadata_candidates", "clip_id = ?", (clip["id"],)):
        db.update("metadata_candidates", meta["id"], description=title, tags=[])
    passed_report(clip)
    meta = db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube'", (clip["id"],))[0]
    candidate = {"clip": clip, "source": None, "platform": "youtube", "connection_id": connection_id, "meta": meta,
                 "scores": {"clip": 90.0}, "urgency": 0.0}
    item = scheduler.create_item(candidate, time.time() + 7200, {"quality": 0.5, "note": "test"}, db.get_settings(),
                                 time.time())
    assert item["status"] == "awaiting_approval" and item["connection_id"] == connection_id
    return item


def test_bulk_review_checks_each_posts_own_channel(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    a, b = chans["a"], chans["b"]
    on_b = bound_draft(chans["tmp"], b["id"])
    shown = bulk_review.preview([on_b["id"]])
    assert shown["account"] == {"id": "UCchanA", "display_name": "Channel A"}  # the default, as before
    assert shown["items"][0]["account"] == {"connection_id": b["id"], "name": "Channel B", "account_id": "UCchanB",
                                            "bound": True}
    assert shown["eligible_ids"] == [on_b["id"]], shown["items"][0]["reason"]
    db.disconnect_connection(a["id"])  # the default channel needing Reconnect does not hold B's post
    assert db.get_connection(a["id"])["is_default"] and db.get_account("youtube") is None
    shown = bulk_review.preview([on_b["id"]])
    assert shown["eligible_ids"] == [on_b["id"]], shown["items"][0]["reason"]
    db.disconnect_connection(b["id"])  # its own channel does
    shown = bulk_review.preview([on_b["id"]])
    assert not shown["eligible_ids"] and "Reconnect Channel B" in shown["items"][0]["reason"]


def test_each_channel_has_its_own_daily_limit_gap_and_slots(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    now = time.time()
    settings = {**db.get_settings(), "autopilot_youtube_daily_limit": 1, "autopilot_daily_target": 0,
                "autopilot_min_gap_minutes": 60}
    plan = scheduler.Plan(settings, now)
    plan.items = [{"id": "1", "platform": "youtube", "clip_id": "c1", "planned_at": now + 3600, "status": "approved",
                   "connection_id": a["id"]}]
    later = now + 3 * 3600
    assert not plan.free("youtube", later, "c2", a["id"])  # A's one post that day
    assert not plan.free("youtube", later, "c2")  # an unbound post means the default channel, A
    assert plan.free("youtube", later, "c2", b["id"])
    assert plan.free("youtube", now + 3600, "c2", b["id"])  # B's own gap: the same time as A's post is fine
    settings["autopilot_youtube_daily_limit"] = 0
    plan = scheduler.Plan(settings, now)
    plan.items = [{"id": "1", "platform": "youtube", "clip_id": "c1", "planned_at": now + 3600, "status": "approved",
                   "connection_id": ""}]
    assert not plan.free("youtube", now + 3600 + 60, "c2", a["id"])
    assert plan.free("youtube", now + 3600 + 60, "c2", b["id"])


def test_a_daily_limit_of_one_still_plans_the_clip_for_every_chosen_channel(chans):
    from clipfoundry import db

    a, b = chans["a"], chans["b"]
    db.save_settings({"autopilot_youtube_daily_limit": 1})
    source = add_file(a, b)
    _clip, posts = ready(chans["tmp"], source, created=2)
    assert set(posts) == {a["id"], b["id"]}


def test_a_post_for_one_channel_never_replaces_another_channels_post(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    future = time.time() + 6 * 3600
    rows = {}
    for cid in ("", a["id"], b["id"]):
        rows[cid] = db.insert("scheduled_publications", {
            "clip_id": f"clip-{cid or 'legacy'}", "platform": "youtube", "title": "Weak", "connection_id": cid,
            "planned_at": future, "status": "awaiting_approval", "final_score": 10})
    on_b = {row["id"] for row in scheduler.replaceable("youtube", time.time(), b["id"])}
    on_a = {row["id"] for row in scheduler.replaceable("youtube", time.time(), a["id"])}
    assert on_b == {rows[b["id"]]["id"]}
    assert on_a == {rows[a["id"]]["id"], rows[""]["id"]}  # an unbound post goes to the default channel, A
    assert {row["id"] for row in scheduler.replaceable("youtube", time.time())} == on_a


def test_a_request_from_before_channel_choice_behaves_as_before(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(account_id="UCchanA")
    _clip, posts = ready(chans["tmp"], source, created=1)
    assert set(posts) == {""}
    item = posts[""]
    assert item["status"] == "approved" and item["approval"]["account"] == "UCchanA"
    assert "connection_id" not in item["approval"] and "connection_id" not in scheduler.approval_basis(item)
    assert scheduler._spacing_key(item) == "upload_spacing:youtube:UCchanA"  # noqa: SLF001
    # As before: making another channel the default holds a request that named the default channel.
    db.set_default_connection(b["id"])
    assert scheduler.approval_problem(post(item["id"]))
    assert "does not authorize" in submissions.problem(db.fetch("sources", source["id"]))
    scheduler.process_due(db.get_settings(), time.time())
    assert post(item["id"])["status"] == "awaiting_approval"
    db.set_default_connection(a["id"])
    scheduler.process_due(db.get_settings(), time.time())
    assert post(item["id"])["status"] == "publishing"
    run_publish(item["id"])
    published = post(item["id"])
    assert published["status"] == "published"
    pub = db.get_publication(published["publication_id"])
    assert pub["connection_id"] == a["id"] and "approved_account" not in pub["options"]


# ------------------------------------------------------------------ what the review found
def test_reconnecting_a_channel_keeps_its_tick_for_new_posts(chans, api):  # noqa: F811
    from clipfoundry import db

    b = chans["b"]
    assert api.patch(f"/api/connections/{b['id']}", headers=H, json={"post_by_default": True}).status_code == 200
    db.update_connection(b["id"], status="needs_reconnect", info={"needs_reconnect": True})
    again = add_channel(chans["google"], "UCchanB", "Channel B")  # Reconnect: the same channel signs in again
    assert again["id"] == b["id"] and again["status"] == "connected"
    info = db.get_connection(b["id"])["info"]
    assert info["post_by_default"] is True and info["needs_reconnect"] is False
    rows = {c["account_id"]: c for c in api.get("/api/connections").json()["connections"]}
    assert rows["UCchanB"]["post_by_default"] is True


def test_posts_planned_before_accounts_could_be_chosen_keep_going_to_the_default(chans):
    """The earlier connections migration wrote the default connection on every planned post, and nothing read it.
    The first start of this version clears it once, so those posts and their approvals behave exactly as before."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(account_id="UCchanA")
    _clip, posts = ready(chans["tmp"], source, created=1)
    item = posts[""]
    assert item["status"] == "approved" and "connection_id" not in item["approval"]
    db.execute("UPDATE scheduled_publications SET connection_id = ? WHERE id = ?", (a["id"], item["id"]))
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.SCHEDULED_ACCOUNTS_MIGRATION,))
    assert scheduler.approval_problem(post(item["id"]))  # read as a chosen account, the old approval would not fit
    with db.connect() as conn:
        db._migrate_scheduled_accounts(conn)  # noqa: SLF001 - the next start
    row = post(item["id"])
    assert row["connection_id"] == "" and scheduler.approval_problem(row) == "" and submissions.still_covers(row)
    # Only once: an account chosen from now on is never cleared by a later start.
    db.execute("UPDATE scheduled_publications SET connection_id = ? WHERE id = ?", (b["id"], item["id"]))
    with db.connect() as conn:
        db._migrate_scheduled_accounts(conn)  # noqa: SLF001
    assert post(item["id"])["connection_id"] == b["id"]


def test_a_post_without_a_chosen_account_is_checked_against_the_whole_platform(chans):
    """Making another channel the default must never plan or post the old backlog again."""
    from clipfoundry import db
    from clipfoundry.autopilot import publisher, scheduler

    a, b = chans["a"], chans["b"]
    source = add_file(account_id="UCchanA")
    clip, posts = ready(chans["tmp"], source, created=1)
    item = posts[""]
    scheduler.process_due(db.get_settings(), time.time())
    run_publish(item["id"])
    done = post(item["id"])
    assert done["status"] == "published" and db.get_publication(done["publication_id"])["connection_id"] == a["id"]
    db.set_default_connection(b["id"])
    assert scheduler._published_or_active(clip["id"], "youtube")  # noqa: SLF001 - no chosen account: anywhere
    assert scheduler._published_or_active(clip["id"], "youtube", a["id"])  # noqa: SLF001 - it went to channel A
    assert not scheduler._published_or_active(clip["id"], "youtube", b["id"])  # noqa: SLF001 - never to channel B
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 0
    again = {**done, "id": "another-post", "publication_id": ""}
    assert publisher.already_published(again)  # the default is channel B now; still a repeat
    assert publisher.already_published({**again, "connection_id": b["id"]}) == ""  # chosen: channel B never had it
    assert publisher.already_published({**again, "connection_id": a["id"]})


def test_home_counts_only_the_default_channels_posts_when_it_is_disconnected(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state
    from clipfoundry.publish.routes import _youtube_state

    a, b = chans["a"], chans["b"]
    on_b = owner_item(chans["tmp"], b["id"], "Build what they asked for")
    db.disconnect_connection(a["id"])

    def account_items() -> list[dict]:
        settings = db.get_settings()
        platforms = {"youtube": _youtube_state(settings)}
        return [i for i in home.needs_you(settings, platforms) if i.get("key") == "account:youtube"]

    assert account_items() == []  # the only planned post goes to channel B, which is connected
    waiting = db.insert("scheduled_publications", {
        "clip_id": on_b["clip_id"], "platform": "youtube", "title": "Unbound", "description": "", "tags": [],
        "privacy": "private", "options": {"made_for_kids": False}, "planned_at": time.time() + 7200,
        "status": "awaiting_approval", "final_score": 50})
    found = account_items()
    assert len(found) == 1 and "1 planned post cannot go out" in found[0]["detail"]
    # A chosen channel that was reconnected since no longer asks for Reconnect on Home.
    state.action(f"connect:{b['id']}", "publish", "Reconnect Channel B to publish", "", "", ref_type="scheduled",
                 ref_id=on_b["id"])
    keys = [i["key"] for i in home.needs_you(db.get_settings(), {})]
    assert f"connect:{b['id']}" not in keys
    db.disconnect_connection(b["id"])
    keys = [i["key"] for i in home.needs_you(db.get_settings(), {})]
    assert f"connect:{b['id']}" in keys
    assert waiting["id"]


def test_the_permission_statement_covers_each_chosen_channel(chans):
    from clipfoundry.autopilot import submissions

    a, b = chans["a"], chans["b"]
    many = submissions.for_source(add_file(a, b, reuse_basis="permission"))["settings"]["reuse_statement"]
    assert "uploading clips to each YouTube channel I chose." in many and STATEMENT in many
    one = submissions.for_source(add_file(b, reuse_basis="permission"))["settings"]["reuse_statement"]
    assert "uploading clips to this YouTube channel." in one
    old = submissions.for_source(add_file(account_id="UCchanA", reuse_basis="permission"))["settings"]
    assert "uploading clips to this YouTube channel." in old["reuse_statement"]
    shown = {row["id"]: row for row in submissions.setup()["reuse_bases"]}
    assert shown["permission"]["text_many"].endswith("each YouTube channel I chose.")
    assert "text_many" not in shown["owned"]


# ------------------------------------------------------------------ what the second review found
def host_publish(item_id: str) -> str:
    """Run a post's upload job and record its end the way the job host does: a refusal ends the job for good, a
    wait parks it to run again later."""
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    try:
        run_publish(item_id)
        end = "completed"
    except queue.Fail:
        end = "failed"
    except queue.Wait:
        end = "waiting"
    db.execute("UPDATE worker_jobs SET status = ? WHERE idem_key = ?", (end, f"publish:{item_id}"))
    return end


def home_keys() -> list[str]:
    from clipfoundry import db
    from clipfoundry.autopilot import home
    from clipfoundry.publish.routes import _youtube_state

    settings = db.get_settings()
    return [i["key"] for i in home.needs_you(settings, {"youtube": _youtube_state(settings)})]


def test_a_reconnect_notice_stays_while_its_post_still_waits_for_the_owner(chans, api):  # noqa: F811
    """YouTube refuses the sign-in during the upload: the post is held and no job tries it again, so "Needs you"
    keeps saying so even though the account still looks connected (the same as for a post without a channel)."""
    from clipfoundry import db

    b = chans["b"]
    db.save_settings({"autopilot_review_before_publish": False})
    item = owner_item(chans["tmp"], b["id"], "Build what they asked for")
    tokens = db.connection_tokens(b["id"])
    db.update_connection(b["id"], tokens={**tokens, "expires_at": 0, "refresh_token": ""})  # cannot be renewed
    assert host_publish(item["id"]) == "failed"
    assert post(item["id"])["status"] == "action_needed" and db.get_connection(b["id"])["status"] == "connected"
    assert f"connect:{b['id']}" in home_keys()
    add_channel(chans["google"], "UCchanB", "Channel B")  # the owner signs in again
    assert f"connect:{b['id']}" in home_keys()  # still shown: the post needs Retry, nothing tries it by itself
    assert api.post(f"/api/autopilot/scheduled/{item['id']}/retry", headers=H).status_code == 200
    assert post(item["id"])["status"] == "approved" and f"connect:{b['id']}" not in home_keys()


def test_a_reconnect_notice_goes_once_the_account_is_back_and_the_post_tries_again_itself(chans):
    from clipfoundry import db

    b = chans["b"]
    db.save_settings({"autopilot_review_before_publish": False})
    item = owner_item(chans["tmp"], b["id"], "Build what they asked for")
    db.disconnect_connection(b["id"])
    assert host_publish(item["id"]) == "waiting"  # found signed out before uploading: the job waits and tries again
    assert post(item["id"])["status"] == "action_needed" and f"connect:{b['id']}" in home_keys()
    add_channel(chans["google"], "UCchanB", "Channel B")
    assert f"connect:{b['id']}" not in home_keys()
    assert host_publish(item["id"]) == "completed" and post(item["id"])["status"] == "published"
    assert len(chans["google"].uploads_to("UCchanB")) == 1 and chans["google"].uploads_to("UCchanA") == []


def test_a_replaced_slot_on_one_channel_does_not_hold_the_same_time_on_another(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    a, b = chans["a"], chans["b"]
    now, at = time.time(), time.time() + 6 * 3600
    settings = db.get_settings()
    rows = {}
    for name, cid in (("a", a["id"]), ("a2", a["id"]), ("b", b["id"]), ("old", "")):
        rows[name] = db.insert("scheduled_publications", {
            "clip_id": f"clip-{name}", "platform": "youtube", "title": "Weak", "connection_id": cid,
            "planned_at": at, "status": "awaiting_approval", "final_score": 10})
    db.insert("slot_replacements", {"replacement_id": "new-on-a", "replaced_id": rows["a"]["id"],
                                    "platform": "youtube", "slot_at": at, "clip_id": "strong", "status": "replaced",
                                    "created_at": now, "updated_at": now}, key="replacement_id")
    assert scheduler.replacement_blocked(rows["b"], "another", settings, now) == ""  # channel B's own slot
    assert "replacement" in scheduler.replacement_blocked(rows["a"], "another", settings, now)
    assert "replacement" in scheduler.replacement_blocked(rows["a2"], "another", settings, now)  # A's slot, same time
    assert "replacement" in scheduler.replacement_blocked(rows["old"], "another", settings, now)  # default is A
    db.execute("DELETE FROM scheduled_publications WHERE id = ?", (rows["a"]["id"],))
    assert "replacement" in scheduler.replacement_blocked(rows["b"], "another", settings, now)  # unknown: as before


def test_an_upload_that_began_finishes_on_its_account_when_the_default_changes(chans, api):  # noqa: F811
    """A post without a channel of its own that is already uploading belongs to the account that upload began on:
    its page names that account, its approval stays valid and it finishes there."""
    from clipfoundry import db
    from clipfoundry.autopilot import queue, targets
    from test_autopilot_publish import make_item

    a, b, google = chans["a"], chans["b"], chans["google"]
    db.save_settings({"autopilot_review_before_publish": False})
    google.rate_limit_puts, google.retry_after = 1, "7200"  # YouTube asks to wait in the middle of the upload
    item = make_item(chans["tmp"], approve={"options": {"made_for_kids": False}})
    assert not item.get("connection_id") and item["approval"]["account"] == "UCchanA"
    with pytest.raises(queue.Wait):
        run_publish(item["id"])
    db.set_default_connection(b["id"])
    db.execute("DELETE FROM platform_limits")
    held = post(item["id"])
    assert targets.begun_on(held) == a["id"] and targets.item_account(held) == "UCchanA"
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]["account"]
    assert shown == {"connection_id": a["id"], "name": "Channel A", "account_id": "UCchanA", "bound": True}
    run_publish(item["id"])  # the wait is over: the same upload continues, with the approval it had
    done = post(item["id"])
    assert done["status"] == "published" and done["approval"]["account"] == "UCchanA"
    assert len(google.uploads_to("UCchanA")) == 1 and google.uploads_to("UCchanB") == []


def test_an_upload_that_never_started_follows_the_default_and_is_not_sent_to_the_old_one(chans, api):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import targets
    from test_autopilot_publish import make_item

    a, b, google = chans["a"], chans["b"], chans["google"]
    db.save_settings({"autopilot_review_before_publish": False})
    item = make_item(chans["tmp"], approve={"options": {"made_for_kids": False}})
    clip = db.get_clip(item["clip_id"])
    stale = db.create_publication(item["clip_id"], "youtube", project_id=clip["project_id"], status="queued",
                                  title=item["title"], scheduled_id=item["id"])
    assert stale["connection_id"] == a["id"]  # made while A was the default; nothing was sent
    db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={},
              publication_id=stale["id"])
    db.set_default_connection(b["id"])
    held = post(item["id"])
    assert targets.begun_on(held) == "" and targets.item_account(held) == "UCchanB"
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]["account"]
    assert shown == {"connection_id": b["id"], "name": "Channel B", "account_id": "UCchanB", "bound": False}
    body = {"confirm": True, "made_for_kids": False}
    wrong = api.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers=H,
                     json={**body, "expected_account_id": "UCchanA"})
    assert wrong.status_code == 409
    ok = api.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers=H,
                  json={**body, "expected_account_id": shown["account_id"]})
    assert ok.status_code == 200 and ok.json()["approval"]["account"] == "UCchanB"
    run_publish(item["id"])
    done = post(item["id"])
    assert done["status"] == "published" and done["publication_id"] != stale["id"]
    assert db.get_publication(stale["id"])["status"] == "cancelled"
    assert len(google.uploads_to("UCchanB")) == 1 and google.uploads_to("UCchanA") == []


def test_a_package_you_post_yourself_can_be_approved_while_tiktok_is_signed_out(chans, api):  # noqa: F811
    """The page names the post's account only while it is connected (PostReview.tsx): a signed-out account is not
    one the server can compare, and a TikTok package the owner posts himself needs no account at all."""
    from clipfoundry import db
    from clipfoundry.autopilot import targets

    creator = add_tiktok(chans["tiktok"], "open-a", "Creator A")
    video = chans["tmp"] / "package.mp4"
    video.write_bytes(os.urandom(4096))
    project = db.create_project("talk", status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=20, title="Talk", status="ready", output_path=str(video),
                          duration=20.0, caption_text="Talk to customers first.", score=72.0)
    passed_report(clip)
    item = db.insert("scheduled_publications", {
        "clip_id": clip["id"], "platform": "tiktok", "title": "Talk", "description": "Talk to customers first.",
        "tags": [], "privacy": "", "options": {"mode": "manual"}, "connection_id": "",
        "planned_at": time.time() + 7200, "status": "awaiting_approval", "final_score": 70})
    assert api.post(f"/api/connections/{creator['id']}/disconnect", headers=H).status_code == 200
    shown = api.get(f"/api/autopilot/scheduled/{item['id']}").json()["item"]["account"]
    assert (shown["name"], shown["account_id"], shown["bound"]) == ("Creator A", "open-a", False)
    assert targets.item_account(post(item["id"])) == ""  # nothing is connected to compare with
    row = [c for c in api.get("/api/connections").json()["connections"] if c["id"] == creator["id"]][0]
    assert row["health"]["state"] == "disconnected" and row["postable"] is False  # the page reads "not connected"
    body = {"title": "Talk", "description": "Talk to customers first.", "mode": "manual", "privacy": "",
            "allow_comment": False, "allow_duet": False, "allow_stitch": False, "disclose": False,
            "brand_organic": False, "brand_content": False, "confirm": True, "reuse_confirmed": True,
            "reuse_kind": "owned"}
    ok = api.post(f"/api/autopilot/scheduled/{item['id']}/approve", headers=H, json=body)
    assert ok.status_code == 200 and post(item["id"])["status"] == "approved"


def test_a_videos_status_names_the_one_chosen_channel_that_is_held(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import home, submissions

    a, b = chans["a"], chans["b"]
    source = add_file(a, b)
    old = add_file(account_id="UCchanA")  # a request from before channels could be chosen
    assert submissions.held_channels(source) == []
    db.disconnect_connection(b["id"])
    assert submissions.held_channels(source) == ["Channel B needs Reconnect. Other channels continue."]
    row = [s for s in home.activity() if s["id"] == source["id"]][0]
    assert row["posting"].startswith("Qualifying YouTube clips upload automatically")
    assert row["posting"].endswith("Channel B needs Reconnect. Other channels continue.")
    db.disconnect_connection(a["id"])
    assert submissions.held_channels(source) == []  # every channel is held: the request itself says why
    row = [s for s in home.activity() if s["id"] == source["id"]][0]
    assert row["posting"].startswith("Uploads held: ")
    assert submissions.held_channels(old) == []


def test_the_plan_counts_a_post_for_the_account_it_went_to(chans):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, targets

    a, b = chans["a"], chans["b"]
    item = owner_item(chans["tmp"], "", "Sent before the default changed")
    run_publish(item["id"])
    assert post(item["id"])["status"] == "published"
    db.set_default_connection(b["id"])
    plan = scheduler.Plan(db.get_settings(), time.time())
    sent = [row for row in plan.items if row["id"] == item["id"]][0]
    assert plan._of(sent) == ("youtube", a["id"]) == ("youtube", targets.effective_connection_id(sent))
    waiting = db.insert("scheduled_publications", {
        "clip_id": "clip-later", "platform": "youtube", "title": "Later", "planned_at": time.time() + 7200,
        "status": "awaiting_approval", "final_score": 10})
    assert plan._of(waiting) == ("youtube", b["id"])  # nothing sent yet: it follows today's default
    flagged = {**db.get_connection(b["id"]), "info": {"needs_reconnect": True}}
    assert targets.usable(db.get_connection(b["id"])) and not targets.usable(flagged)
