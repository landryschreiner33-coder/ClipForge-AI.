"""The Brain (brain.py): provenance, cohorts, idempotent imports and the guarded clip-length loop."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}
SELECTED = {"audience_youtube_intent": "SELECTED_AUDIENCE", "target_duration": 30.0}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings(SELECTED)
    return tmp_path


def _clip(duration: float = 30.0, source: str = "src") -> dict:
    from clipfoundry import db

    project = db.create_project("p", status="ready", origin="autopilot", source_id=source)
    return db.create_clip(project["id"], start=0, end=duration, duration=duration, title="t", status="ready")


def _settings() -> dict:
    from clipfoundry import db

    return db.get_settings()


def test_the_same_reading_twice_is_stored_once_and_a_new_value_is_a_correction(data):
    from clipfoundry import brain

    clip = _clip()
    at = time.time()
    a = brain.record(clip["id"], "youtube", "owner_import", "views", 12, settings=_settings(), observed_at=at)
    b = brain.record(clip["id"], "youtube", "owner_import", "views", 12, settings=_settings(), observed_at=at)
    assert b["duplicate"] and len(brain.current()) == 1
    c = brain.record(clip["id"], "youtube", "owner_import", "views", 15, settings=_settings(), observed_at=at)
    [only] = brain.current()
    assert only["id"] == c["id"] and only["version"] == 2 and only["value"] == 15  # replaced, never summed
    assert a["cohort"] == "selected:youtube:invited:v1"


def test_missing_numbers_stay_missing_and_bad_values_are_rejected(data):
    from clipfoundry import brain

    clip = _clip()
    row = brain.record(clip["id"], "youtube", "owner_import", "likes", None, settings=_settings())
    assert row["value"] is None
    for metric, value in (("views", -1), ("avg_view_percentage", 140), ("made_up", 3)):
        with pytest.raises(brain.ImportProblem):
            brain.record(clip["id"], "youtube", "owner_import", metric, value, settings=_settings())
    with pytest.raises(brain.ImportProblem):
        brain.record(clip["id"], "youtube", "invented_source", "views", 1, settings=_settings())


def test_cohorts_keep_test_groups_apart_and_change_with_the_group_version(data):
    from clipfoundry import brain

    s = _settings()
    assert brain.cohort_for("youtube", s)[0] == "selected:youtube:invited:v1"
    assert brain.cohort_for("youtube", {**s, "audience_youtube_group_version": 2})[0].endswith(":v2")
    assert brain.cohort_for("tiktok", {"audience_tiktok_intent": "OWNER_ONLY"}) == ("owner:tiktok", "owner")
    assert brain.cohort_of_publication({"platform": "youtube", "privacy": "public", "info": {}}, s)[1] == "public"


def test_csv_preview_checks_every_row_and_commit_is_idempotent(data):
    from clipfoundry import brain

    clip = _clip()
    good = (f"clip_id,platform,observed_at,views,avg_view_percentage,likes\n"
            f"{clip['id']},youtube,2026-10-05T12:00,14,61.5,\n")
    p = brain.preview_csv(good, _settings())
    assert p["accepted"] == 3 and not p["problems"]
    assert [r["value"] for r in p["rows"]] == [14, 61.5, None]  # an empty cell is "not reported", not zero
    first = brain.commit_csv(good, _settings(), "export.csv")
    again = brain.commit_csv(good, _settings(), "export.csv")
    assert first["stored"] == 3 and again == {**again, "stored": 0, "duplicates": 3}
    bad = good + "nope,youtube,2026-10-05,3,,\n" + f"{clip['id']},youtube,,3,,\n"
    p = brain.preview_csv(bad, _settings())
    assert {x["line"] for x in p["problems"]} == {3, 4}
    with pytest.raises(brain.ImportProblem, match="nothing was imported"):
        brain.commit_csv(bad, _settings())


def test_tester_ratings_are_self_reported_and_one_answer_per_tester(data):
    from clipfoundry import brain

    clip = _clip()
    rows = brain.record_tester(clip["id"], "youtube", {"overall": 4, "hook": 5}, _settings(), "ana", "nice", 22)
    assert {r["provenance"] for r in rows} == {"tester_feedback"}
    assert "self_reported_stop_s" in {r["metric"] for r in rows}  # never "watch time"
    brain.record_tester(clip["id"], "youtube", {"overall": 2}, _settings(), "ana")
    overall = [o for o in brain.current() if o["metric"] == "rating_overall"]
    assert len(overall) == 1 and overall[0]["value"] == 2
    with pytest.raises(brain.ImportProblem):
        brain.record_tester(clip["id"], "youtube", {"overall": 9}, _settings())
    assert brain.clip_status(clip["id"])["state"] == "Manual feedback available"


def _evidence(n_sources: int, per_source: int, short_score: float, long_score: float, noise: float = 2.0) -> None:
    """Short (15 s) and long (55 s) clips per source, with retention imported 3 days ago by the owner."""
    from clipfoundry import brain

    at = time.time() - 3 * 86400
    for s in range(n_sources):
        for i in range(per_source):
            for dur, score in ((15.0, short_score), (55.0, long_score)):
                clip = _clip(dur, f"src{s}")
                value = score + noise * ((s * 7 + i * 3) % 5 - 2)
                brain.record(clip["id"], "youtube", "owner_import", "avg_view_percentage", value,
                             settings=_settings(), observed_at=at, window_start=at, sample_size=5)


def test_not_enough_evidence_changes_nothing(data):
    from clipfoundry import brain

    _evidence(4, 2, 70, 40)  # 16 clips from 4 sources
    r = brain.evaluate_length("selected:youtube:invited:v1", _settings())
    assert r["decision"] == "insufficient" and r["message"].startswith("Not enough evidence yet")
    assert brain.ranking_options(_settings())["strategy_version"] == "baseline"


def test_a_clear_preference_moves_the_target_by_at_most_ten_percent_and_can_be_rolled_back(data):
    from clipfoundry import brain
    from clipfoundry.autopilot import hunter

    _evidence(12, 2, 72, 40)  # 48 clips from 12 sources: short clips held viewers clearly better
    cohort = "selected:youtube:invited:v1"
    r = brain.evaluate_length(cohort, _settings())
    assert r["decision"] == "update" and r["new_value"] == 27.0  # 30 s - 10%, not all the way to 15 s
    opts = hunter.project_options(_settings())
    assert opts["target_duration"] == 27.0 and opts["strategy_version"] == r["version"]["id"]
    second = brain.evaluate_length(cohort, _settings())
    assert second["new_value"] == pytest.approx(24.3)  # another bounded step from the active version
    brain.rollback(second["version"]["id"])
    assert hunter.project_options(_settings())["target_duration"] == 27.0
    brain.rollback(r["version"]["id"])
    assert hunter.project_options(_settings())["strategy_version"] == "baseline"


def test_no_clear_difference_is_inconclusive(data):
    from clipfoundry import brain

    _evidence(12, 2, 55, 54, noise=10)
    r = brain.evaluate_length("selected:youtube:invited:v1", _settings())
    assert r["decision"] == "inconclusive" and "new_value" not in r


def test_public_and_owner_cohorts_never_get_an_automatic_strategy(data):
    from clipfoundry import brain

    for cohort in ("public:youtube", "owner:youtube", "legacy:tiktok"):
        with pytest.raises(ValueError):
            brain.evaluate_length(cohort, _settings())


def test_youtube_api_numbers_need_googles_approval_before_they_steer(data):
    from clipfoundry import brain

    at = time.time() - 3 * 86400
    clip = _clip()
    brain.record(clip["id"], "youtube", "platform_api", "avg_view_percentage", 60, settings=_settings(),
                 observed_at=at, window_start=at, sample_size=9)
    assert brain.eligible_clips("selected:youtube:invited:v1", _settings()) == []
    s = {**_settings(), "youtube_derived_metrics_approved": True}
    assert len(brain.eligible_clips("selected:youtube:invited:v1", s)) == 1


def test_experiment_assignment_is_stable_and_bounded(data):
    from clipfoundry import brain

    exp = {"id": "e1", "share": 0.1, "variants": ["a", "b"]}
    picks = [brain.assign_variant(exp, f"clip{i}") for i in range(2000)]
    assert picks == [brain.assign_variant(exp, f"clip{i}") for i in range(2000)]
    assert 0.05 < sum(p != "control" for p in picks) / len(picks) < 0.15
    assert brain.compare_arms([1.0] * 5, [2.0] * 5)["result"] == "insufficient"
    a = [60 + (i % 3) for i in range(25)]
    assert brain.compare_arms(a, [x - 15 for x in a])["winner"] == "a"
    assert brain.compare_arms(a, list(a))["winner"] is None


def test_brain_api_and_states(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    clip = _clip()
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/brain").json()["state"] == "Cold start"
        assert c.post("/api/brain/feedback", json={}).status_code == 403  # not from ClipFoundry's page
        r = c.post("/api/brain/feedback", headers=H, json={"clip_id": clip["id"], "platform": "youtube",
                                                 "provenance": "tester_feedback", "ratings": {"overall": 4}})
        assert r.status_code == 200 and r.json()["stored"] == 1
        assert c.post("/api/brain/feedback", headers=H, json={"clip_id": clip["id"], "platform": "youtube",
                                                               "provenance": "platform_api",
                                                    "metrics": {"views": 1}}).status_code == 400
        view = c.get("/api/brain").json()
        assert view["state"] == "Collecting data" and view["by_provenance"]["tester_feedback"] == 1
        assert c.get(f"/api/brain/clips/{clip['id']}").json()["state"] == "Manual feedback available"
