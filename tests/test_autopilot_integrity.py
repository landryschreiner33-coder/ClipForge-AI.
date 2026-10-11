"""Schedule integrity: the cooldown between replacements of a slot, approvals bound to the video's exact bytes, unique
clips counted apart from platform posts, both America/Chicago daylight-saving changes, and the upgrade of an existing
database. Against local stand-ins for YouTube and TikTok and placeholder files (mock tests: nothing here reaches a
real service or a real account)."""
from __future__ import annotations

import datetime as dt
import os
import time
import types
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fake_platforms import FakeGoogle, FakeTikTok
from quality_stub import passed_report

CHI = ZoneInfo("America/Chicago")
NO_KIDS = {"options": {"made_for_kids": False}}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(var, "127.0.0.1,localhost")
    from clipfoundry import db
    from clipfoundry.publish import tiktok, youtube

    g, t = FakeGoogle(), FakeTikTok()
    for name, value in {"AUTH_URL": f"{g.url}/o/oauth2/v2/auth", "TOKEN_URL": f"{g.url}/token",
                        "REVOKE_URL": f"{g.url}/revoke", "API_URL": f"{g.url}/youtube/v3",
                        "UPLOAD_URL": f"{g.url}/upload/youtube/v3/videos", "CHUNK": 256 * 1024}.items():
        monkeypatch.setattr(youtube, name, value)
    monkeypatch.setattr(tiktok, "AUTH_URL", f"{t.url}/v2/auth/authorize/")
    monkeypatch.setattr(tiktok, "API_URL", f"{t.url}/v2")
    db.init()
    db.save_settings({"youtube_client_id": "cid.apps.googleusercontent.com", "youtube_client_secret": "csecret",
                      "tiktok_client_key": "tkkey", "tiktok_client_secret": "tksecret", "autopilot_enabled": True,
                      "autopilot_youtube": True, "autopilot_tiktok": False, "autopilot_min_gap_minutes": 60,
                      "autopilot_youtube_daily_limit": 3, "autopilot_tiktok_daily_limit": 3})
    yield {"g": g, "t": t, "tmp": tmp_path}
    g.stop()
    t.stop()


def make_clip(env, title: str, score: float = 70.0, packaging: float = 60.0) -> dict:
    """A ready Autopilot clip (placeholder bytes, not a video) packaged for both platforms, passed by the gate."""
    from clipfoundry import db
    from clipfoundry.pipeline import fingerprint

    video = env["tmp"] / f"clip-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(200_000))
    project = db.create_project(title, status="ready", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=20, title=title, status="ready", output_path=str(video),
                          duration=20.0, caption_text=title, score=score)
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": score, "diversity": 80.0, "retention": 60.0},
              key="clip_id")
    db.insert("clip_fingerprints", {"clip_id": clip["id"], "text_sig": fingerprint.text_signature(title), "phash": [],
                                    "title_norm": title.lower()}, key="clip_id")
    for p in ("youtube", "tiktok"):
        db.insert("metadata_candidates", {"clip_id": clip["id"], "platform": p, "style": "direct", "title": title,
                                          "description": f"{title}\n\nFollow for more.", "caption": f"{title} #talk",
                                          "tags": ["talk"], "hashtags": ["#talk"], "score": packaging,
                                          "selected": 1})
    passed_report(clip)
    return clip


def restart() -> None:
    """What a restart of ClipFoundry leaves behind: the database and the files, nothing held in memory."""
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db._ready.clear()  # noqa: SLF001
    db._columns.clear()  # noqa: SLF001
    scheduler._sha_memo.clear()  # noqa: SLF001


def rewrite_in_place(path: str) -> None:
    """Change the file's bytes but keep its size and modification time (an edit in place, a re-render that reused
    the name): exactly what a size-and-time check cannot see."""
    st = os.stat(path)
    data = bytearray(Path(path).read_bytes())
    data[len(data) // 2] ^= 0xFF
    Path(path).write_bytes(bytes(data))
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = os.stat(path)
    assert (after.st_size, after.st_mtime_ns) == (st.st_size, st.st_mtime_ns)


def local(day: dt.date, hour: int, minute: int = 0) -> float:
    return dt.datetime.combine(day, dt.time(hour, minute), CHI).timestamp()


def consent_youtube(env) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish

    if not (db.get_account("youtube") or {}).get("has_tokens"):
        connect_youtube(env["g"])
    return autopublish.enable("youtube", "private", False, 3, 9, 21, True, "")


def item_for(clip: dict, platform: str = "youtube") -> dict:
    from clipfoundry import db

    return db.select("scheduled_publications", "clip_id = ? AND platform = ?", (clip["id"], platform),
                     "created_at DESC", 1)[0]


def connect_youtube(g) -> None:
    from clipfoundry import db
    from clipfoundry.publish import youtube
    from clipfoundry.publish.common import challenge_s256, code_verifier

    s = db.get_settings()
    v = code_verifier()
    code = g.approve(youtube.auth_url(s, "http://127.0.0.1:8765/cb", "st", challenge_s256(v)))
    youtube.exchange_code(s, code, v, "http://127.0.0.1:8765/cb")


def run_publish(item_id: str) -> dict:
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    row = queue.enqueue("publish", {"scheduled_id": item_id}, idem_key=f"publish:{item_id}:{time.time_ns()}")
    return host.HANDLERS["publish"](host.Job(queue.get(row["id"]), "test"))


# ------------------------------------------------------------------ replacement cooldown
def test_one_pending_swap_per_slot_a_declined_swap_is_not_proposed_again_and_the_slot_rests(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_youtube_daily_limit": 1, "autopilot_replacement_threshold": 15})
    now = local(dt.datetime.now(CHI).date(), 6)
    weak = make_clip(env, "Weak clip about pricing", score=40)
    for k in range(2):
        make_clip(env, f"Strong clip number {k} about customers", score=95, packaging=95)
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 3  # today, tomorrow, the day after: all full
    for it in db.select("scheduled_publications"):
        scheduler.approve(it["id"], NO_KIDS)  # your OK on each: an approved post is only swapped with your OK
    w = item_for(weak)
    first = make_clip(env, "A much stronger new opportunity", score=95, packaging=95)
    assert scheduler.plan_new(db.get_settings(), now)["replaced"] == 1
    proposal = item_for(first)
    assert proposal["replaces"] == w["id"] and proposal["status"] == "awaiting_approval"
    assert db.fetch("scheduled_publications", w["id"])["status"] == "approved"  # untouched until you decide
    assert [a["event"] for a in db.fetch("scheduled_publications", w["id"])["audit"]][-1] == "replacement_proposed"

    second = make_clip(env, "Another strong opportunity", score=96, packaging=95)
    for _ in range(2):  # several ticks, and a restart in between: never a second proposal for the same slot
        out = scheduler.plan_new(db.get_settings(), now)
        restart()
        assert out["replaced"] == 0
    pending = db.select("scheduled_publications", "replaces = ? AND status = 'awaiting_approval'", (w["id"],))
    assert [p["id"] for p in pending] == [proposal["id"]]
    assert not db.select("scheduled_publications", "clip_id = ?", (second["id"],))

    scheduler.cancel(proposal["id"])  # you said no to the swap
    restart()
    out = scheduler.plan_new(db.get_settings(), now + 3600)
    assert out["replaced"] == 0 and out["replacement_cooldown"] >= 2  # the same clip again, and the other one
    assert db.fetch("scheduled_publications", w["id"])["status"] == "approved"
    assert not db.select("scheduled_publications", "replaces = ? AND status != 'canceled'", (w["id"],))
    [history] = db.select("slot_replacements")
    assert (history["replaced_id"], history["replacement_id"], history["clip_id"], history["status"]) == (
        w["id"], proposal["id"], first["id"], "proposed")
    assert history["slot_at"] == w["planned_at"]

    s = db.get_settings()
    w = db.fetch("scheduled_publications", w["id"])
    assert "less than 24 hours ago" in scheduler.replacement_blocked(w, second["id"], s, now + 23 * 3600)
    assert scheduler.replacement_blocked(w, second["id"], s, now + 25 * 3600) == ""  # the slot rested a day
    assert "already proposed" in scheduler.replacement_blocked(w, first["id"], s, now + 30 * 24 * 3600)
    db.save_settings({"autopilot_replacement_cooldown_hours": 0})
    assert scheduler.replacement_blocked(w, second["id"], db.get_settings(), now + 3600) == ""  # 0 turns it off


def test_the_cooldown_follows_the_slot_and_the_posts_of_a_replacement(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    s = {**db.get_settings(), "autopilot_replacement_cooldown_hours": 12}
    now = time.time()
    slot = now + 86400
    db.insert("slot_replacements", {"replacement_id": "new1", "replaced_id": "old1", "platform": "youtube",
                                    "slot_at": slot, "clip_id": "c-new", "status": "replaced", "created_at": now},
              key="replacement_id")
    moved_in = {"id": "other", "platform": "youtube", "planned_at": slot + 30}  # another post later moved into it
    assert "12 hours" in scheduler.replacement_blocked(moved_in, "c2", s, now + 3600)
    moved_away = {"id": "new1", "platform": "youtube", "planned_at": slot + 7200}  # the replacement, moved later
    assert "12 hours" in scheduler.replacement_blocked(moved_away, "c2", s, now + 3600)
    elsewhere = {"id": "x", "platform": "youtube", "planned_at": slot + 7200}
    assert scheduler.replacement_blocked(elsewhere, "c2", s, now + 3600) == ""
    tiktok = {"id": "y", "platform": "tiktok", "planned_at": slot}  # the same time on the other platform
    assert scheduler.replacement_blocked(tiktok, "c2", s, now + 3600) == ""
    assert scheduler.replacement_blocked(moved_in, "c2", s, now + 13 * 3600) == ""


def test_an_automatic_swap_keeps_the_whole_audit_trail(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    consent_youtube(env)  # (it also sets the YouTube posts per day to its own limit)
    db.save_settings({"autopilot_youtube_daily_limit": 1})
    now = local(dt.datetime.now(CHI).date(), 6)
    for k in range(3):
        make_clip(env, f"Weak clip {k} about pricing", score=40 + k)
    scheduler.plan_new(db.get_settings(), now)
    weakest = min(db.select("scheduled_publications"), key=lambda i: i["final_score"])
    assert weakest["status"] == "approved" and weakest["approval"]["by"] == "automatic"
    strong = make_clip(env, "A much stronger new opportunity", score=95, packaging=95)
    assert scheduler.plan_new(db.get_settings(), now)["replaced"] == 1
    new = item_for(strong)
    old = db.fetch("scheduled_publications", weakest["id"])
    assert new["status"] == "approved" and new["approval"]["by"] == "automatic"
    assert new["status_note"].startswith("Approved automatically")  # not "approve it to replace ..."
    assert old["status"] == "replaced" and old["replaced_by"] == new["id"]
    events = [a["event"] for a in old["audit"]]
    assert events[-1] == "replaced" and "replacement_proposed" not in events and "auto_approved" in events
    assert db.select("slot_replacements")[0]["status"] == "replaced"


# ------------------------------------------------------------------ approvals bound to the exact bytes
def test_a_clip_changed_in_place_needs_a_new_approval_across_restarts(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler
    from clipfoundry.pipeline import artifact

    connect_youtube(env["g"])
    db.save_settings({"autopilot_tiktok": True})
    clip = make_clip(env, "Talk to customers first")
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    yt = scheduler.approve(item_for(clip)["id"], NO_KIDS)
    tt = scheduler.approve(item_for(clip, "tiktok")["id"], {"privacy": "SELF_ONLY"})
    before = artifact.sha256_file(clip["output_path"])
    assert yt["approval"]["video_sha256"] == before and yt["approval"]["scheme"] == scheduler.APPROVAL_SCHEME
    restart()
    assert all(scheduler.approval_valid(db.fetch("scheduled_publications", i["id"])) for i in (yt, tt))

    rewrite_in_place(clip["output_path"])
    restart()
    for i in (yt, tt):
        cur = db.fetch("scheduled_publications", i["id"])
        assert not scheduler.approval_valid(cur)
        assert scheduler.approval_problem(cur) == "the clip or its text changed after approval"
    db.update("scheduled_publications", yt["id"], planned_at=now + 600)  # due: YouTube uploads 30 minutes early
    db.update("scheduled_publications", tt["id"], planned_at=now - 60)  # due: TikTok posts at its time
    scheduler.process_due(db.get_settings(), now)
    for i in (yt, tt):
        cur = db.fetch("scheduled_publications", i["id"])
        assert cur["status"] == "awaiting_approval" and cur["approval"] == {}
        assert cur["status_note"] == "Needs a new approval: the clip or its text changed after approval"
        assert cur["audit"][-1]["event"] == "approval_invalidated"
        assert cur["audit"][-1]["approved_sha256"] == before
    with pytest.raises(queue.Fail):
        run_publish(yt["id"])  # nothing is uploaded without a valid approval
    assert not env["g"].videos

    # a fresh approval of the changed clip, after the gate checked these bytes (test double for its run)
    passed_report(db.get_clip(clip["id"]))
    yt = scheduler.approve(yt["id"], NO_KIDS)
    after = artifact.sha256_file(clip["output_path"])
    assert yt["approval"]["video_sha256"] == after != before
    restart()
    assert scheduler.approval_valid(db.fetch("scheduled_publications", yt["id"]))
    run_publish(yt["id"])
    done = db.fetch("scheduled_publications", yt["id"])
    video = next(iter(env["g"].videos.values()))
    assert done["status"] == "published" and video["bytes"] == Path(clip["output_path"]).read_bytes()
    assert db.fetch("scheduled_publications", tt["id"])["status"] == "awaiting_approval"  # TikTok: your OK again


def test_youtube_is_approved_again_automatically_only_after_the_gate_checked_the_new_bytes(env):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, scheduler
    from clipfoundry.pipeline import artifact

    db.save_settings({"autopilot_tiktok": True})
    consent_youtube(env)
    clip = make_clip(env, "Talk to customers first")
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    yt, tt = item_for(clip), item_for(clip, "tiktok")
    assert yt["status"] == "approved" and yt["approval"]["by"] == "automatic"
    assert tt["status"] == "awaiting_approval"  # TikTok: never approved automatically
    first_sha = yt["approval"]["video_sha256"]

    rewrite_in_place(clip["output_path"])
    restart()
    db.update("scheduled_publications", yt["id"], planned_at=now + 600)
    scheduler.process_due(db.get_settings(), now)  # due: the approval no longer covers the file
    assert db.fetch("scheduled_publications", yt["id"])["status"] == "awaiting_approval"
    db.update("scheduled_publications", yt["id"], planned_at=now + 7200)
    scheduler.process_due(db.get_settings(), now)
    held = db.fetch("scheduled_publications", yt["id"])
    assert held["status"] == "awaiting_approval" and "final check has not run" in held["status_note"]
    [job] = queue.jobs(worker="quality_gate")  # a check of these bytes, although size and time did not change
    assert job["status"] == "queued" and job["idem_key"].endswith(artifact.sha256_file(clip["output_path"])[:16])

    host.WorkerHost(periodic=False)  # the real gate runs on the new bytes: placeholder bytes are not a video
    claimed = queue.claim("quality_gate", "test")
    host.HANDLERS["quality_check"](host.Job(claimed, "test"))
    queue.complete(claimed, "test", {})
    scheduler.process_due(db.get_settings(), now)
    held = db.fetch("scheduled_publications", yt["id"])
    assert held["status"] == "awaiting_approval" and "did not pass the final check" in held["status_note"]

    passed_report(db.get_clip(clip["id"]))  # stands in for a passing check of a good new render
    scheduler.process_due(db.get_settings(), now)
    again = db.fetch("scheduled_publications", yt["id"])
    assert again["status"] == "approved" and again["approval"]["by"] == "automatic"
    assert again["approval"]["video_sha256"] != first_sha and scheduler.approval_valid(again)
    assert [a["event"] for a in again["audit"]].count("auto_approved") == 2
    assert db.fetch("scheduled_publications", tt["id"])["status"] == "awaiting_approval"


def test_approvals_and_automatic_publishing_stay_with_the_account_they_were_given_for(env):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    connect_youtube(env["g"])
    db.save_settings({"autopilot_tiktok": True})
    clip = make_clip(env, "Talk to customers first")
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    yt = scheduler.approve(item_for(clip)["id"], NO_KIDS)
    assert yt["approval"]["account"] == "UC123"
    other = make_clip(env, "Ask what they got wrong")
    consent_youtube(env)  # given while UC123 is connected
    scheduler.plan_new(db.get_settings(), now)
    auto = item_for(other)
    assert auto["status"] == "approved" and auto["approval"]["by"] == "automatic"

    db.save_account("youtube", account_id="UCsomeoneelse", display_name="Another channel")  # another channel signed in
    restart()
    for i in (yt, auto):
        cur = db.fetch("scheduled_publications", i["id"])
        assert scheduler.approval_problem(cur) == "another account is connected now than the one it was approved for"
        db.update("scheduled_publications", i["id"], planned_at=now + 600)
    scheduler.process_due(db.get_settings(), now)
    for i in (yt, auto):
        cur = db.fetch("scheduled_publications", i["id"])
        assert cur["status"] == "awaiting_approval" and cur["approval"] == {}
    scheduler.process_due(db.get_settings(), now)  # the permission names UC123: nothing is approved for the new one
    held = db.fetch("scheduled_publications", auto["id"])
    assert held["status"] == "awaiting_approval" and "another channel" in held["status_note"]
    with pytest.raises(queue.Fail):
        run_publish(yt["id"])
    assert not env["g"].videos

    db.save_account("youtube", account_id="UC123", display_name="Channel")  # the first channel again
    assert scheduler.approval_valid(scheduler.approve(yt["id"], NO_KIDS))


def test_missing_or_unreadable_video_is_never_approved(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.pipeline import artifact

    clip = make_clip(env, "Talk to customers first")
    other = make_clip(env, "Build what they asked for")
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    approved = scheduler.approve(item_for(clip)["id"], NO_KIDS)
    os.remove(clip["output_path"])
    with pytest.raises(ValueError, match="missing or cannot be read"):
        scheduler.approve(approved["id"], NO_KIDS)
    assert scheduler.approval_problem(approved) == "the video file is missing or cannot be read"
    db.update("scheduled_publications", approved["id"], planned_at=now + 600)
    scheduler.process_due(db.get_settings(), now)
    gone = db.fetch("scheduled_publications", approved["id"])
    assert gone["status"] == "awaiting_approval" and "missing or cannot be read" in gone["status_note"]

    def locked(path, chunk=1 << 20):  # e.g. another program holds the file open on Windows
        raise PermissionError(13, "Permission denied", str(path))

    ok = scheduler.approve(item_for(other)["id"], NO_KIDS)
    monkeypatch.setattr(artifact, "sha256_file", locked)
    restart()
    assert not scheduler.approval_valid(db.fetch("scheduled_publications", ok["id"]))
    with pytest.raises(ValueError, match="missing or cannot be read"):
        scheduler.approve(ok["id"], NO_KIDS)
    consent_youtube(env)
    db.update("scheduled_publications", ok["id"], status="awaiting_approval", approval={})
    assert not scheduler.auto_approve(db.fetch("scheduled_publications", ok["id"]), db.get_settings(), now)
    assert "missing or cannot be read" in db.fetch("scheduled_publications", ok["id"])["status_note"]


def test_approvals_from_before_the_content_hash_are_asked_again(env):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_tiktok": True})
    clip = make_clip(env, "Talk to customers first")
    now = time.time()
    scheduler.plan_new(db.get_settings(), now)
    yt, tt = item_for(clip), item_for(clip, "tiktok")
    old = {"at": now - 3600, "by": "you", "hash": "0" * 40}  # what an earlier version stored (size + time)
    db.update("scheduled_publications", yt["id"], status="approved", approval=old, options={"made_for_kids": False},
              planned_at=now + 600)  # due: YouTube uploads 30 minutes early
    db.update("scheduled_publications", tt["id"], status="approved", approval=old, privacy="SELF_ONLY",
              planned_at=now - 60)  # due: TikTok posts at its time
    restart()
    for i in (yt, tt):
        cur = db.fetch("scheduled_publications", i["id"])
        assert not scheduler.approval_valid(cur)
        assert scheduler.approval_problem(cur) == "approved before ClipFoundry checked the exact video file"
    consent_youtube(env)
    scheduler.process_due(db.get_settings(), now)  # due: both go back to approval
    assert {db.fetch("scheduled_publications", i["id"])["status"] for i in (yt, tt)} == {"awaiting_approval"}
    db.update("scheduled_publications", yt["id"], planned_at=now + 7200)
    db.update("scheduled_publications", tt["id"], planned_at=now + 7200 + 3600)
    scheduler.process_due(db.get_settings(), now)
    yt, tt = (db.fetch("scheduled_publications", i["id"]) for i in (yt, tt))
    assert yt["status"] == "approved" and yt["approval"]["by"] == "automatic"  # under the permission in force
    assert yt["approval"]["scheme"] == scheduler.APPROVAL_SCHEME and scheduler.approval_valid(yt)
    assert tt["status"] == "awaiting_approval"  # TikTok waits for your OK


def test_the_publish_center_does_not_hash_every_file_on_every_refresh(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.pipeline import artifact

    clip = make_clip(env, "Talk to customers first")
    scheduler.plan_new(db.get_settings(), time.time())
    item = scheduler.approve(item_for(clip)["id"], NO_KIDS)
    calls = []
    real = artifact.sha256_file
    monkeypatch.setattr(artifact, "sha256_file", lambda p, chunk=1 << 20: calls.append(p) or real(p, chunk))
    assert scheduler.approval_valid(item, quick=True)
    n = len(calls)
    for _ in range(5):
        assert scheduler.approval_valid(item, quick=True)
    assert len(calls) == n  # unchanged file: the display reuses the hash
    assert scheduler.approval_valid(item) and len(calls) == n + 1  # a decision always hashes the bytes
    with open(clip["output_path"], "r+b") as fh:  # a write changes the change time (POSIX) or the size
        fh.write(b"x")
    assert not scheduler.approval_valid(item, quick=True)


# ------------------------------------------------------------------ unique clips and platform posts
def test_the_dashboard_counts_unique_clips_and_platform_posts_separately(env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import routes

    day = dt.date(2026, 10, 14)
    now = local(day, 13)
    both = make_clip(env, "Posted on both platforms")
    later = make_clip(env, "Scheduled on both platforms")
    early = make_clip(env, "Uploaded early to YouTube")
    rows = [(both, "youtube", local(day, 9), "published"), (both, "tiktok", local(day, 10), "published"),
            (later, "youtube", local(day, 17), "approved"), (later, "tiktok", local(day, 18), "awaiting_approval"),
            (early, "youtube", local(day, 20), "published"),  # uploaded; YouTube makes it public at 20:00
            (early, "tiktok", local(day - dt.timedelta(days=1), 12), "published")]  # yesterday: not today
    for clip, platform, at, status in rows:
        db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": platform, "title": clip["title"],
                                             "planned_at": at, "status": status})
    counts = routes.today_posts(db.select("scheduled_publications", "planned_at >= ? AND planned_at < ?",
                                          (local(day, 0), local(day + dt.timedelta(days=1), 0))), now)
    assert (counts["published"], counts["published_posts"]) == (1, 2)  # one clip, two platform posts
    assert (counts["scheduled"], counts["scheduled_posts"]) == (2, 3)
    assert counts["posts_by_platform"] == {"youtube": {"published": 1, "scheduled": 2},
                                           "tiktok": {"published": 1, "scheduled": 1}}
    monkeypatch.setattr(routes, "time", types.SimpleNamespace(time=lambda: now))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        target = client.get("/api/autopilot/status").json()["target"]
    assert {k: target[k] for k in ("published", "published_posts", "scheduled", "scheduled_posts")} == {
        "published": 1, "published_posts": 2, "scheduled": 2, "scheduled_posts": 3}
    assert "unique clips" in target["note"]


# ------------------------------------------------------------------ daylight-saving time in America/Chicago
@pytest.mark.parametrize("day, before, after", [
    (dt.date(2026, 3, 8), -6, -5),   # 2:00 CST -> 3:00 CDT: a 23-hour day
    (dt.date(2026, 11, 1), -5, -6),  # 2:00 CDT -> 1:00 CST: a 25-hour day
])
def test_planning_across_a_daylight_saving_change(env, day, before, after):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, scout

    s = db.get_settings()
    start, end = scout.day_bounds(s, local(day, 12))
    assert end - start == (23 if after > before else 25) * 3600
    assert dt.datetime.fromtimestamp(start, CHI).utcoffset() == dt.timedelta(hours=before)
    assert dt.datetime.fromtimestamp(end - 1, CHI).date() == day

    for k in range(8):
        make_clip(env, f"Clip number {k} about customers", score=60 + k)
    now = local(day, 0, 30)  # before the change
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 8
    items = sorted(db.select("scheduled_publications"), key=lambda i: i["planned_at"])
    per_day: dict[str, int] = {}
    for it in items:
        at = dt.datetime.fromtimestamp(it["planned_at"], CHI)
        assert 9 <= at.hour < 21 and at.date() >= day  # the 9 a.m. to 9 p.m. window, on the local clock
        assert scout.local_day(s, it["planned_at"]) == at.date().isoformat() == it["slot"]["local"][:10]
        utc = dt.datetime.fromtimestamp(it["planned_at"], dt.timezone.utc)
        assert utc == dt.datetime.combine(at.date(), at.time(), CHI).astimezone(dt.timezone.utc)
        if at.date() == day:
            assert at.utcoffset() == dt.timedelta(hours=after)  # the new offset after 2 a.m.
            assert utc.hour == (at.hour - after) % 24
        per_day[at.date().isoformat()] = per_day.get(at.date().isoformat(), 0) + 1
    assert per_day[day.isoformat()] == 3 and max(per_day.values()) == 3  # the daily limit, per local day
    assert all(b["planned_at"] - a["planned_at"] >= 3600 for a, b in zip(items, items[1:]))  # the minimum gap
    first = dt.datetime.fromtimestamp(items[0]["planned_at"], CHI)
    assert (first.date(), first.hour) == (day, 11)  # centers of three 4-hour blocks: 11:00, 15:00, 19:00


@pytest.mark.parametrize("day", [dt.date(2026, 3, 8), dt.date(2026, 11, 1)])
def test_missed_posts_are_replanned_once_each_without_a_burst_across_the_change(env, day):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, scheduler

    db.save_settings({"autopilot_youtube_daily_limit": 4, "autopilot_min_gap_minutes": 45})
    missed = [local(day - dt.timedelta(days=1), 20, 30), local(day, 9, 0), local(day, 10, 0), local(day, 11, 15)]
    ids = []
    for k, at in enumerate(missed):  # approved, then the PC was off from the evening before until noon
        clip = make_clip(env, f"Missed clip {k} about customers")
        item = db.insert("scheduled_publications", {
            "clip_id": clip["id"], "platform": "youtube", "title": clip["title"], "description": "d", "tags": [],
            "privacy": "private", "options": {"made_for_kids": False}, "planned_at": at,
            "status": "awaiting_approval"})
        scheduler.approve(item["id"], {})
        ids.append(item["id"])
    now = local(day, 12)
    out = scheduler.process_due(db.get_settings(), now)
    assert out["publishing"] == 0 and out["missed"] == 4  # nothing is posted late in a burst
    assert not queue.jobs(worker="publisher")
    rows = [db.fetch("scheduled_publications", i) for i in ids]
    assert all(r["status"] == "approved" and scheduler.approval_valid(r) for r in rows)  # still approved
    times = sorted(r["planned_at"] for r in rows)
    assert len(set(times)) == 4 and all(t > now for t in times)
    assert all(b - a >= 45 * 60 for a, b in zip(times, times[1:]))
    for t in times:
        at = dt.datetime.fromtimestamp(t, CHI)
        assert 9 <= at.hour < 21
    per_day: dict = {}
    for t in times:
        d = dt.datetime.fromtimestamp(t, CHI).date()
        per_day[d] = per_day.get(d, 0) + 1
    assert max(per_day.values()) <= 4
    assert len(db.select("scheduled_publications")) == 4  # no copies: each post once
    again = scheduler.process_due(db.get_settings(), now + 60)  # the next tick changes nothing
    assert again["missed"] == 0 and again["publishing"] == 0
    assert sorted(db.fetch("scheduled_publications", i)["planned_at"] for i in ids) == times
    first = min(rows, key=lambda r: r["planned_at"])
    due = first["planned_at"] - 60 * float(db.get_settings()["autopilot_upload_lead_minutes"])
    assert scheduler.process_due(db.get_settings(), due + 1)["publishing"] == 1  # one at a time, at its time


# ------------------------------------------------------------------ upgrading an existing database
def test_an_existing_database_is_upgraded_in_place(env):
    """A database from before this version: no replacement history table, approvals by size and time. Opening it
    keeps every row and setting, adds the table with the replacements already made, and asks again for approvals
    it cannot trust."""
    import sqlite3

    from clipfoundry import config, db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_daily_target": 7, "autopilot_timezone": "America/Chicago"})
    clip = make_clip(env, "Talk to customers first")
    strong = make_clip(env, "A stronger clip")
    now = time.time()
    weak = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "title": "w",
                                                "planned_at": now + 86400, "status": "replaced",
                                                "approval": {}, "replaced_by": "n1"})
    db.insert("scheduled_publications", {"id": "n1", "clip_id": strong["id"], "platform": "youtube", "title": "n",
                                         "planned_at": now + 86400, "status": "awaiting_approval",
                                         "replaces": weak["id"]})
    legacy = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "tiktok", "title": "t",
                                                  "planned_at": now + 7200, "status": "approved",
                                                  "privacy": "SELF_ONLY",
                                                  "approval": {"at": now, "by": "you", "hash": "f" * 40}})
    path = str(config.db_path())
    with sqlite3.connect(path) as conn:  # back to the earlier schema
        conn.execute("DROP TABLE slot_replacements")
    restart()
    counts = {t: db.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("clips", "projects", "scheduled_publications",
                                                                  "quality_reports", "metadata_candidates")}
    [history] = db.select("slot_replacements")
    assert (history["replaced_id"], history["replacement_id"], history["status"]) == (weak["id"], "n1", "replaced")
    assert history["slot_at"] == weak["planned_at"]
    restart()  # opening it again adds nothing twice
    assert len(db.select("slot_replacements")) == 1
    assert {t: db.scalar(f"SELECT COUNT(*) FROM {t}") for t in counts} == counts
    assert db.get_settings()["autopilot_daily_target"] == 7
    assert db.get_settings()["autopilot_replacement_cooldown_hours"] == 24.0  # the new default
    old = db.fetch("scheduled_publications", legacy["id"])
    assert old["status"] == "approved" and not scheduler.approval_valid(old)  # never trusted, asked again
