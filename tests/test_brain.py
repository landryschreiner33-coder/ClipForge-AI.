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
              intent: str = "SELECTED_AUDIENCE", group_version: int = 1, strategy: str = "",
              delivery: dict | None = None) -> tuple[dict, dict]:
    from clipfoundry import db

    src = src or source()
    options = {"strategy": {"clip_length": {"id": strategy}}} if strategy else {}
    project = db.create_project("p", status="ready", origin="autopilot", source_id=src["id"], options=options)
    clip = db.create_clip(project["id"], start=0, end=duration, title="Talk", status="ready", duration=duration,
                          caption_text="Start with the customer.")
    pub = db.create_publication(clip["id"], platform, status="done", remote_id=f"v{time.time_ns()}",
                                audience={"intent": intent, "group_version": group_version, "policy_version": 1},
                                delivery=delivery or {})
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
            sources: int = 8, strategy: str = "", durations=None, delivery: dict | None = None) -> list[dict]:
    srcs = [source() for _ in range(sources)]
    clips = []
    for k in range(n):
        d = durations[k] if durations else 18 + (k % 14) * 2  # 18..44 s, both sides of the 30 s target
        clip, _ = published(platform, d, srcs[k % sources], intent=intent, group_version=group_version,
                            strategy=strategy, delivery=delivery)
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

    _cohort(50, lambda d, k: 20 + d + (k % 3))  # longer clips were watched further, in this synthetic cohort
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

    _cohort(50, lambda d, k: 50 + (k % 5))
    out = brain.evaluate()
    assert out["groups"][0]["result"] == "inconclusive" and "about the same" in out["message"]
    assert not brain.history()


def test_each_side_of_the_comparison_needs_twenty_clips(data):
    from clipfoundry.autopilot import brain

    _cohort(40, lambda d, k: 20 + d + (k % 3))  # 40 clips, but only 18 shorter than the 30 s target
    group = brain.evaluate()["groups"][0]
    assert group["result"] == "inconclusive" and "at least 20 clips shorter" in group["message"]
    assert not brain.history() and brain.clip_length() is None


def test_identical_ratings_show_no_uncertainty_and_change_nothing(data):
    from clipfoundry.autopilot import brain

    srcs, when = [source() for _ in range(8)], time.time() - 3600
    for k in range(52):  # three testers gave every longer clip 5 and every shorter one 2: no spread to judge by
        d = 18 + (k % 14) * 2
        clip, _ = published("tiktok", d, srcs[k % 8])
        for tester in ("ana", "ben", "cy"):
            brain.add(clip["id"], "tiktok", "tester_feedback", {"overall": 5 if d >= 30 else 2}, tester=tester,
                      observed_at=when)
    # rounding left a standard error of about 1e-16 here, which used to pass for a measured, significant difference
    group = brain.evaluate(now=when + 600)["groups"][0]
    assert group["result"] == "inconclusive" and "no spread" in group["message"] and not brain.history()


def test_paused_brain_collects_but_changes_nothing(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    db.save_settings({"brain_paused": True})
    _cohort(40, lambda d, k: 20 + d)
    assert brain.evaluate()["state"] == "paused" and not brain.history()
    assert brain.summary()["label"] == "Paused" and brain.summary()["observations"]["owner_import"] == 40


def test_paused_learning_worker_mirrors_results_but_preserves_values_and_resume_history(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, learner, state

    clip, pub = published()
    db.add_performance(pub, {"views": 100, "avg_view_percentage": 45}, "isolated API fixture", [], {})
    rows = [{"publication_id": f"p{k}", "clip_id": f"c{k}", "platform": "tiktok", "cohort": "selected",
             "group_version": 1, "source_key": f"s{k % 5}", "views": 1000 if k % 2 else 100,
             "avg_view_percentage": None, "hour": "19" if k % 2 else "10", "weekday": "1", "topic": "science",
             "source_type": "manual", "style": "manual", "hook_type": "question", "duration": "20-35 s",
             "scores": {}} for k in range(30)]
    monkeypatch.setattr(learner, "refresh_due", lambda *_args: {"refreshed": 0})
    monkeypatch.setattr(learner, "rows", lambda _settings: rows)
    db.insert("learning_metrics", {"id": "hour:19:tiktok:performance", "dimension": "hour", "key": "19",
                                   "platform": "tiktok", "metric": "performance", "n": 15, "lift": 1.05,
                                   "data": {"reliable": True}})
    db.insert("learning_metrics", {"id": "weight:clip:all:weight", "dimension": "weight", "key": "clip",
                                   "platform": "all", "metric": "weight", "n": 30, "lift": 0.3})
    db.insert("learning_metrics", {"id": "calibration:retention:all:retention", "dimension": "calibration",
                                   "key": "retention", "platform": "all", "metric": "retention", "n": 30,
                                   "data": {"slope": 0.5, "intercept": 10}})
    context = learner.learning_context(db.get_settings())
    basis = [r["publication_id"] for r in rows]
    state.put("learning:context", context)
    state.put("learning:basis", basis)
    saved_metrics, saved_history = db.select("learning_metrics"), brain.history()

    class Job:
        def progress(self, *_args, **_kwargs):
            pass

    db.save_settings({"brain_paused": True})
    result = learner.learn(Job())
    assert "paused" in result["message"] and brain.summary()["state"] == "paused"
    assert len(brain.observations(clip["id"])) == 1  # Collection continues while learning is paused.
    assert db.select("learning_metrics") == saved_metrics and brain.history() == saved_history
    assert state.get("learning:context") == context and state.get("learning:basis") == basis
    assert learner.lift("hour", "19", "tiktok") == (1.0, 0)
    assert learner.weights() == {} and learner.expected_retention(80) == (80, "")
    db.save_settings({"brain_paused": False})
    assert learner.lift("hour", "19", "tiktok") == (1.05, 15)
    assert learner.weights() == {"clip": 0.3} and learner.expected_retention(80)[0] == 50
    assert "Waiting for new results: 0" in learner.learn(Job())["message"]
    assert db.select("learning_metrics") == saved_metrics and brain.history() == saved_history
    assert state.get("learning:context") == context and state.get("learning:basis") == basis


@pytest.mark.parametrize("intent, setup, original_cohort", [
    ("SELECTED_AUDIENCE", "user_confirmed", "selected"), ("OWNER_ONLY", "owner_only", "owner_only")])
def test_api_visibility_drift_excludes_new_readings_without_rewriting_historical_cohort(
        data, intent, setup, original_cohort):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, learner

    clip, pub = published("youtube", intent=intent, delivery={"audience_setup": setup,
        "visibility": {"requested": "private", "returned": "private", "evidence": "api"}})
    db.update_publication(pub["id"], requested_privacy="private",
                          audience={**pub["audience"], "visibility": "private"})
    pub = db.get_publication(pub["id"])
    assert learner.cohort(pub) == original_cohort
    before = brain.add(clip["id"], "youtube", "platform_api", {"views": 100, "avg_view_percentage": 40},
                       observed_at=time.time() - 3600, publication_id=pub["id"])["observation"]
    db.update_publication(pub["id"], privacy="public", delivery={"audience_setup": setup,
        "visibility": {"requested": "private", "returned": "public", "evidence": "api"}})
    pub = db.get_publication(pub["id"])
    assert learner.cohort(pub) == "unconfirmed"
    after = brain.add(clip["id"], "youtube", "platform_api", {"views": 10000, "avg_view_percentage": 85},
                      publication_id=pub["id"])["observation"]
    assert after["cohort"] == "unconfirmed"
    assert db.fetch("brain_observations", before["id"]) == before and before["cohort"] == original_cohort
    settings = {**db.get_settings(), "youtube_derived_metrics_approved": True}
    evidence = brain.evidence(settings)
    assert evidence[("youtube", original_cohort, 1)]["measured"][clip["id"]]["value"] == 40
    assert evidence[("youtube", "unconfirmed", 1)]["measured"][clip["id"]]["value"] == 85


def test_worse_later_results_roll_back_and_you_can_reset(data):
    from clipfoundry.autopilot import brain

    _cohort(50, lambda d, k: 20 + d + (k % 3))
    s = brain.evaluate()["groups"][0]["strategy"]
    _cohort(12, lambda d, k: 5 + (k % 2), strategy=s["id"], durations=[33] * 12)  # clips made under v1 did worse
    out = brain.evaluate()
    assert out["groups"][0]["result"] == "rolled_back" and "later results were worse" in out["message"]
    assert brain.db.fetch("brain_strategies", s["id"])["status"] == "rolled_back"
    assert brain.clip_length() is None  # back to your own setting
    # the next evaluation does not adopt it again from the results that rolled it back
    assert brain.evaluate()["groups"][0]["result"] == "waiting" and brain.clip_length() is None
    with pytest.raises(brain.Invalid):
        brain.rollback(s["id"])
    brain.reset()
    assert not brain.db.select("brain_strategies", "status = 'active'")


def test_a_rollback_or_reset_by_you_is_not_undone_by_the_same_results(data):
    from clipfoundry.autopilot import brain

    _cohort(50, lambda d, k: 20 + d + (k % 3))
    s = brain.evaluate()["groups"][0]["strategy"]
    brain.rollback(s["id"])  # you pressed Roll back
    again = brain.evaluate()["groups"][0]
    assert again["result"] == "waiting" and "rollback" in again["message"]
    assert brain.clip_length() is None and len(brain.history()) == 1
    _cohort(12, lambda d, k: 20 + d + (k % 3))  # new results may change it again, one bounded step
    assert brain.evaluate()["groups"][0]["result"] == "updated" and brain.clip_length()["target_duration"] == 33.0
    brain.reset()  # you pressed Reset
    assert brain.evaluate()["groups"][0]["result"] == "waiting" and brain.clip_length() is None


def test_each_platform_keeps_its_own_strategy_and_both_still_roll_back(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    db.save_settings({"autopilot_youtube": True})
    _cohort(50, lambda d, k: 20 + d + (k % 3), platform="youtube")
    out = brain.evaluate()
    assert [(g["platform"], g["result"]) for g in out["groups"]] == [("youtube", "updated")]
    assert brain.clip_length() is None  # one clip goes to both: YouTube's viewers alone do not set TikTok's length
    _cohort(50, lambda d, k: 20 + d + (k % 3), platform="tiktok")
    brain.evaluate()
    both = brain.clip_length()  # both audiences agree: the next clips use both versions, and say so
    assert both["target_duration"] == 33.0 and {u["platform"] for u in both["used"]} == {"youtube", "tiktok"}
    tiktok_v = next(u["id"] for u in both["used"] if u["platform"] == "tiktok")
    _cohort(12, lambda d, k: 5 + (k % 2), platform="tiktok", strategy=both["id"], durations=[33] * 12)
    out = brain.evaluate()  # clips made under both versions did worse on TikTok: TikTok's version is rolled back
    assert {g["platform"]: g["result"] for g in out["groups"]} == {"tiktok": "rolled_back", "youtube": "waiting"}
    assert db.fetch("brain_strategies", tiktok_v)["status"] == "rolled_back" and brain.clip_length() is None


def test_posts_nobody_else_could_watch_yet_are_not_selected_viewers_evidence(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, learner

    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": True})
    # uploaded Private and nobody invited yet, and a TikTok package not posted or linked yet: your own views at most
    _cohort(50, lambda d, k: 20 + d + (k % 3), platform="youtube",
            delivery={"audience_setup": "awaiting_invitations"})
    _cohort(50, lambda d, k: 20 + d + (k % 3), platform="tiktok", delivery={"audience_setup": "manual_pending"})
    assert brain.evaluate()["groups"] == [] and not brain.history()
    assert {o["cohort"] for o in brain.observations(limit=500)} == {"unconfirmed"}
    assert learner.cohort({"platform": "tiktok", "audience": {"intent": "SOMETHING_NEW"}}) != "selected"
    # shared with your viewers a day ago: results count from then, not from the upload five days ago
    clip, _ = published("youtube", delivery={"audience_setup": "user_confirmed", "confirmed_at": time.time() - DAY})
    row = reading(clip, 50, platform="youtube")["observation"]
    assert row["cohort"] == "selected" and row["age_hours"] == pytest.approx(24, abs=0.1)
    assert clip["id"] not in brain.evidence()[("youtube", "selected", 1)]["measured"]  # not mature yet


def test_learning_worker_needs_views_and_several_videos(data, monkeypatch):
    import datetime as dt
    from zoneinfo import ZoneInfo

    from clipfoundry import db
    from clipfoundry.autopilot import host, learner, queue
    from clipfoundry.publish import stats

    monkeypatch.setattr(stats, "refresh", lambda pub: None)
    chicago = ZoneInfo("America/Chicago")

    def post(hour: int, views: int, src: dict) -> None:
        when = dt.datetime.combine(dt.datetime.now(chicago).date() - dt.timedelta(days=4), dt.time(hour, 0),
                                   chicago).timestamp()
        project = db.create_project("p", status="ready", origin="autopilot", source_id=src["id"])
        clip = db.create_clip(project["id"], start=0, end=30, title="t", status="ready", duration=30.0,
                              caption_text="Why do most people quit?")
        pub = db.create_publication(clip["id"], "tiktok", status="done",
                                    audience={"intent": "SELECTED_AUDIENCE", "group_version": 1})
        db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (when, pub["id"]))
        db.execute("INSERT INTO performance (id, publication_id, clip_id, platform, fetched_at, views) VALUES "
                   "(?,?,?,?,?,?)", (db.new_id(), pub["id"], clip["id"], "tiktok", when + 49 * 3600, views))

    def learn() -> str:
        host.WorkerHost(periodic=False)
        row = queue.enqueue("learn", {})
        return host.HANDLERS["learn"](host.Job(queue.get(row["id"]), "test"))["message"]

    srcs = [source() for _ in range(8)]
    for k in range(15):  # a few approved followers: a handful of plays per post is not a result yet
        post(19, 3, srcs[k % 8])
        post(10, 0, srcs[k % 8])
    assert "Not enough results yet: 0 of 30" in learn() and learner.lift("hour", "19", "tiktok") == (1.0, 0)
    one = source()
    for k in range(15):  # plenty of views, but every clip from one video
        post(19, 3000, one)
        post(10, 100, one)
    assert "from 1 of 5 videos" in learn() and learner.lift("hour", "19", "tiktok") == (1.0, 0)
    for k in range(15):  # the same pattern across several videos
        post(19, 3000, srcs[k % 8])
        post(10, 100, srcs[k % 8])
    assert learn().startswith("Learned from 60") and learner.lift("hour", "19", "tiktok")[0] == pytest.approx(1.1)


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
