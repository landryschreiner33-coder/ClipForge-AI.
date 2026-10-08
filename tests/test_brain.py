"""The Brain: evidence with provenance (platform API, your imports, tester feedback), null versus zero, idempotent
imports and corrections, audiences kept apart, the guards before a strategy changes, the clip-length loop that later
clips actually use, and rollback. All observations here are synthetic and live in a temporary test database."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}
DAY = 86400


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": False, "autopilot_tiktok": True})
    return tmp_path


def source() -> dict:
    from clipfoundry import db

    return db.insert("sources", {"platform": "local", "external_id": f"s{time.time_ns()}"})


def published(platform: str = "tiktok", duration: float = 30.0, src: dict | None = None, days_ago: float = 5,
              intent: str = "SELECTED_AUDIENCE", group_version: int = 1, strategy: str = "") -> tuple[dict, dict]:
    from clipfoundry import db

    src = src or source()
    options = {"strategy": {"clip_length": {"id": strategy}}} if strategy else {}
    project = db.create_project("p", status="ready", origin="autopilot", source_id=src["id"], options=options)
    clip = db.create_clip(project["id"], start=0, end=duration, title="Talk", status="ready", duration=duration,
                          caption_text="Start with the customer.")
    pub = db.create_publication(clip["id"], platform, status="done", remote_id=f"v{time.time_ns()}",
                                audience={"intent": intent, "group_version": group_version, "policy_version": 1})
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (time.time() - days_ago * DAY, pub["id"]))
    db.execute("UPDATE clips SET created_at = ? WHERE id = ?", (time.time() - days_ago * DAY - 3600, clip["id"]))
    clip = db.get_clip(clip["id"])
    return clip, db.get_publication(pub["id"])


def reading(clip: dict, pct: float | None, views: int = 200, platform: str = "tiktok", **extra) -> dict:
    from clipfoundry.autopilot import brain

    values = {"views": views, "avg_view_percentage": pct, **extra}
    return brain.add(clip["id"], platform, "owner_import", values)


# ------------------------------------------------------------------ recording evidence
def test_missing_stays_missing_and_zero_stays_zero(data):
    from clipfoundry.autopilot import brain

    clip, _ = published()
    row = reading(clip, None, views=0, likes=0)["observation"]
    assert row["metrics"] == {"views": 0, "likes": 0}  # zero kept; the unreported percentage is absent, not 0
    assert row["cohort"] == "selected" and row["age_hours"] == pytest.approx(5 * 24, abs=0.1)
    with pytest.raises(brain.Invalid, match="watch_minutes"):
        brain.add(clip["id"], "tiktok", "owner_import", {"watch_minutes": 3})  # unknown fields are named
    with pytest.raises(brain.Invalid, match="outside"):
        brain.add(clip["id"], "tiktok", "owner_import", {"ctr": 140})
    with pytest.raises(brain.Invalid, match="future"):
        brain.add(clip["id"], "tiktok", "owner_import", {"views": 5}, observed_at=time.time() + 3 * DAY)
    with pytest.raises(brain.Invalid, match="email"):
        brain.add(clip["id"], "tiktok", "tester_feedback", {"overall": 4}, tester="sam@example.com")
    with pytest.raises(brain.Invalid, match="Platform numbers"):
        brain.add(clip["id"], "", "owner_import", {"views": 5})


def test_a_reading_entered_twice_counts_once_and_a_correction_keeps_the_old_values(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    clip, _ = published()
    when = time.time() - 3600
    first = brain.add(clip["id"], "tiktok", "owner_import", {"views": 120}, observed_at=when)
    assert brain.add(clip["id"], "tiktok", "owner_import", {"views": 120}, observed_at=when)["status"] == "duplicate"
    fixed = brain.add(clip["id"], "tiktok", "owner_import", {"views": 210}, observed_at=when)
    assert fixed["status"] == "corrected" and fixed["observation"]["id"] == first["observation"]["id"]
    assert fixed["observation"]["revision"] == 2 and fixed["observation"]["previous"][0]["metrics"] == {"views": 120}
    assert len(db.select("brain_observations")) == 1


def test_cumulative_snapshots_are_never_added_together(data):
    from clipfoundry.autopilot import brain

    clip, _ = published()
    brain.add(clip["id"], "tiktok", "owner_import", {"views": 100, "avg_view_percentage": 40},
              observed_at=time.time() - 2 * DAY)
    brain.add(clip["id"], "tiktok", "owner_import", {"views": 150, "avg_view_percentage": 44})
    ev = brain.evidence()[("tiktok", "selected", 1)]
    assert ev["measured"][clip["id"]]["value"] == 44  # the latest reading, not 100 + 150 views


def test_tester_feedback_is_self_reported_one_answer_per_tester(data):
    from clipfoundry.autopilot import brain

    clip, _ = published()
    for tester in ("t1", "T1", "t2"):
        brain.add(clip["id"], "tiktok", "tester_feedback", {"overall": 4, "hook": 5}, tester=tester)
    brain.add(clip["id"], "tiktok", "tester_feedback", {"overall": 5})  # anonymous: kept, cannot count as a person
    assert brain.clip_results(clip["id"])["testers"] == 2
    ev = brain.evidence()[("tiktok", "selected", 1)]
    assert clip["id"] not in ev["rated"]  # 2 different testers is below the 3 needed
    brain.add(clip["id"], "tiktok", "tester_feedback", {"overall": 2}, tester="t3")
    rated = brain.evidence()[("tiktok", "selected", 1)]["rated"][clip["id"]]
    assert rated["provenance"] == "tester_feedback" and rated["testers"] == 3
    assert rated["value"] == pytest.approx(10 / 3)
    with pytest.raises(brain.Invalid, match="views"):
        brain.add(clip["id"], "tiktok", "tester_feedback", {"views": 10}, tester="t4")  # testers do not report views


def test_platform_readings_are_mirrored_once_with_their_provenance(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    clip, pub = published("youtube")
    db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views, likes, "
               "avg_view_percentage) VALUES (?,?,?,?,?,?,?,?)",
               (db.new_id(), pub["id"], clip["id"], "youtube", time.time() - 3600, 90, None, 41.0))
    assert brain.ingest_platform(pub) == 1 and brain.ingest_platform(pub) == 0
    row = brain.observations(clip["id"])[0]
    assert row["provenance"] == "platform_api" and row["metrics"] == {"views": 90, "avg_view_percentage": 41.0}
    # YouTube API numbers need Google's derived-metrics approval before they may steer anything
    assert clip["id"] not in brain.evidence().get(("youtube", "selected", 1), {}).get("measured", {})


def test_mirrored_youtube_readings_follow_the_30_day_rule(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, scout

    clip, pub = published("youtube", days_ago=40)
    for age in (35, 2):
        db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views) "
                   "VALUES (?,?,?,?,?,?)", (db.new_id(), pub["id"], clip["id"], "youtube", time.time() - age * DAY,
                                            100 + age))
    assert brain.ingest_platform(pub) == 2
    brain.add(clip["id"], "youtube", "owner_import", {"views": 150}, observed_at=time.time() - 35 * DAY)
    scout.youtube_retention()
    left = {(o["provenance"], o["metrics"]["views"]) for o in brain.observations(clip["id"])}
    assert left == {("platform_api", 102), ("owner_import", 150)}  # what you typed in yourself is not API data
    assert brain.ingest_platform(pub) == 0  # the deleted reading does not come back


# ------------------------------------------------------------------ CSV import
def test_a_studio_export_is_previewed_then_imported_once(data):
    from clipfoundry.autopilot import brain

    a, pa = published("youtube")
    b, pb = published("youtube")
    text = ("Content,Video title,Views,Watch time (hours),Average view duration,Average percentage viewed (%),"
            "Comments added\n"
            "Total,,300,2.5,0:00:30,40,1\n"
            f"{pa['remote_id']},A,200,2,0:00:31,41.5,1\n"
            f"{pb['remote_id']},B,100,0.5,0:00:20,,0\n"
            "nope,Someone else's video,5,0,0:00:01,1,0\n")
    when = time.time() - 600
    pre = brain.preview(text, "owner_import", "", when)
    assert [r["status"] for r in pre["rows"]] == ["new", "new", "error"] and "not one of your" in pre["rows"][2][
        "message"]
    assert pre["rows"][0]["values"] == {"views": 200, "watch_time_minutes": 120.0, "avg_view_duration_s": 31.0,
                                        "avg_view_percentage": 41.5, "comments": 1}
    assert "avg_view_percentage" not in pre["rows"][1]["values"]  # an empty cell is missing, not zero
    assert "Video title" in pre["columns"]["ignored"]
    assert not brain.observations()  # a preview stores nothing
    first = brain.import_csv(text, "owner_import", "", when, "studio.csv")
    assert first["counts"] == {"added": 2, "error": 1}
    again = brain.import_csv(text, "owner_import", "", when, "studio.csv")
    assert again["counts"] == {"duplicate": 2, "error": 1} and len(brain.observations()) == 2
    assert brain.observations(a["id"])[0]["origin"] == "studio.csv"
    with pytest.raises(brain.Invalid, match="clip_id"):
        brain.preview("Views\n5\n")


def test_tester_feedback_file(data):
    from clipfoundry.autopilot import brain

    clip, _ = published()
    text = ("clip_id,platform,tester,hook,overall,stopped_at_s,note\n"
            f"{clip['id']},tiktok,ana,5,4,12,liked the start\n"
            f"{clip['id']},tiktok,ben,6,4,,\n")
    pre = brain.preview(text, "tester_feedback", "", time.time())
    assert pre["rows"][0]["status"] == "new" and pre["rows"][0]["values"] == {"hook": 5, "overall": 4,
                                                                               "stopped_at_s": 12.0}
    assert pre["rows"][1]["status"] == "error" and "hook" in pre["rows"][1]["message"]


# ------------------------------------------------------------------ the guards and the clip-length loop
def _cohort(n: int, value, *, platform: str = "tiktok", intent: str = "SELECTED_AUDIENCE", group_version: int = 1,
            sources: int = 8, strategy: str = "", durations=None) -> list[dict]:
    srcs = [source() for _ in range(sources)]
    clips = []
    for k in range(n):
        d = durations[k] if durations else 18 + (k % 14) * 2  # 18..44 s, both sides of the 30 s target
        clip, _ = published(platform, d, srcs[k % sources], intent=intent, group_version=group_version,
                            strategy=strategy)
        reading(clip, value(d, k), platform=platform)
        clips.append(clip)
    return clips


def test_too_few_clips_change_nothing(data):
    from clipfoundry.autopilot import brain, hunter

    _cohort(29, lambda d, k: 20 + d)
    out = brain.evaluate()
    assert out["groups"][0]["result"] == "not_enough" and "29 of 30" in out["message"]
    assert not brain.history() and brain.clip_length() is None
    assert "target_duration" not in hunter.project_options(brain.db.get_settings())
    assert brain.summary()["state"] == "collecting" and brain.summary()["label"] == "Collecting data"


def test_other_audiences_never_change_a_strategy(data):
    from clipfoundry.autopilot import brain

    _cohort(40, lambda d, k: 20 + d, intent="LEGACY_PUBLIC")          # public before this version
    _cohort(40, lambda d, k: 20 + d, intent="OWNER_ONLY")              # only you: self-views
    _cohort(40, lambda d, k: 20 + d, group_version=0)                  # an earlier version of the viewer group
    out = brain.evaluate()
    assert out["groups"] == [] and not brain.history()


def test_enough_selected_evidence_moves_the_clip_length_ten_percent_and_later_clips_use_it(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, hunter
    from clipfoundry.office import feed

    _cohort(40, lambda d, k: 20 + d + (k % 3))  # longer clips were watched further, in this synthetic cohort
    _cohort(40, lambda d, k: 90 - d, intent="LEGACY_PUBLIC")  # the old public posts said the opposite: ignored
    out = brain.evaluate()
    group = out["groups"][0]
    assert group["result"] == "updated" and group["cohort"] == "selected"
    s = group["strategy"]
    assert s["params"]["target_duration"] == 33.0 and s["params"]["previous_target"] == 30.0  # +10%, not to ~37
    assert s["params"]["rollback_to"] == "baseline" and s["evidence"]["long"]["n"] >= 10
    assert brain.summary()["state"] == "updated"
    opts = hunter.project_options(db.get_settings())  # the next video Autopilot starts uses that version
    assert opts["target_duration"] == 33.0 and opts["strategy"]["clip_length"]["id"] == s["id"]
    assert any(e["type"] == "brain_lookup" and e["role"] == "core" for e in feed.events_after(0)["events"])
    from clipfoundry.pipeline import process

    project = db.create_project("next", origin="autopilot", options=opts)
    assert process._options(project, db.get_settings())["target_duration"] == 33.0  # what the moment finder ranks by
    # the same evidence never moves it twice; new results may move it another bounded step from 33 s
    again = brain.evaluate()["groups"][0]
    assert again["result"] == "waiting" and len(brain.history()) == 1
    _cohort(12, lambda d, k: 20 + d + (k % 3))
    later = brain.evaluate()["groups"][0]
    assert later["result"] == "updated" and later["strategy"]["params"]["target_duration"] == pytest.approx(36.3)
    assert later["strategy"]["params"]["rollback_to"] == s["id"]


def test_no_difference_is_inconclusive(data):
    from clipfoundry.autopilot import brain

    _cohort(40, lambda d, k: 50 + (k % 5))
    out = brain.evaluate()
    assert out["groups"][0]["result"] == "inconclusive" and not brain.history()


def test_paused_brain_collects_but_changes_nothing(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    db.save_settings({"brain_paused": True})
    _cohort(40, lambda d, k: 20 + d)
    assert brain.evaluate()["state"] == "paused" and not brain.history()
    assert brain.summary()["label"] == "Paused" and brain.summary()["observations"]["owner_import"] == 40


def test_worse_later_results_roll_back_and_you_can_reset(data):
    from clipfoundry.autopilot import brain

    _cohort(40, lambda d, k: 20 + d + (k % 3))
    s = brain.evaluate()["groups"][0]["strategy"]
    _cohort(12, lambda d, k: 5 + (k % 2), strategy=s["id"], durations=[33] * 12)  # clips made under v1 did worse
    out = brain.evaluate()
    assert out["groups"][0]["result"] == "rolled_back" and "later results were worse" in out["message"]
    assert brain.db.fetch("brain_strategies", s["id"])["status"] == "rolled_back"
    assert brain.clip_length() is None  # back to your own setting
    with pytest.raises(brain.Invalid):
        brain.rollback(s["id"])
    brain.reset()
    assert not brain.db.select("brain_strategies", "status = 'active'")


def test_brain_api(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    clip, _ = published()
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        st = c.get("/api/brain").json()
        assert st["state"] == "cold_start" and st["min_clips"] == 30 and "overall" in st["fields"]["ratings"]
        body = {"clip_id": clip["id"], "platform": "tiktok", "provenance": "tester_feedback",
                "values": {"overall": 4}, "tester": "ana"}
        assert c.post("/api/brain/observations", json=body).status_code == 403  # only from the app's page
        assert c.post("/api/brain/observations", json=body, headers=H).json()["status"] == "added"
        assert c.post("/api/brain/observations", json={**body, "provenance": "platform_api"},
                      headers=H).status_code == 422  # API readings cannot be typed in
        bad = c.post("/api/brain/observations", json={**body, "values": {"overall": 9}}, headers=H)
        assert bad.status_code == 422 and "overall" in bad.json()["detail"]
        assert c.get(f"/api/brain/clips/{clip['id']}").json()["testers"] == 1
        pre = c.post("/api/brain/import/preview", json={"text": f"clip_id,views\n{clip['id']},5\n",
                                                        "platform": "tiktok", "observed_at": time.time()},
                     headers=H).json()
        assert pre["rows"][0]["status"] == "new"
        assert c.post("/api/brain/pause", json={"paused": True}, headers=H).json()["state"] == "paused"
        assert c.post("/api/brain/strategies/nope/rollback", headers=H).status_code == 409
