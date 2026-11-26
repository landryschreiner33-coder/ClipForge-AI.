"""The viral predictor (clipfoundry/predictor/): the measured channels, the hook, the hold curve, the score, fixes that
are tried before they are offered (and never cost score), the edit list mapping for trims, learning from results
(bounded), the prediction kept with every render, Check a video, and the routes. Media is synthetic (ffmpeg test
pattern + tone); transcripts are synthetic and labelled as such."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from synthetic_media import make_video, needs_ffmpeg, words_every, words_from

H = {"X-ClipFoundry": "1"}
FAST = {"encoder": "x264", "x264_preset": "ultrafast"}
TALK = ("Why do most people never save money? Here is the reason. They spend first and save what is left, which is "
        "usually nothing. The fix is simple. Move ten percent to savings the day you get paid. That's why it works: "
        "you never see the money.")
LEAD_IN = "So, um, okay. Welcome back everyone. Today I want to talk about something. "


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _loud(seconds: float, level: float = -20.0, quiet: tuple[float, float] | None = None):
    from clipfoundry.pipeline.audio import Loudness

    db = level + 2.0 * np.sin(np.arange(int(seconds * 10)) / 3.0)
    if quiet:
        db[int(quiet[0] * 10):int(quiet[1] * 10)] = -70.0
    return Loudness({"hop": 0.1, "db": np.round(db, 1).tolist()})


def _predict(words, seconds, **kw):
    from clipfoundry.predictor import content, model, signals

    sig = signals.from_source(0.0, seconds, words, _loud(seconds, **kw))
    con = content.analyze(sig, {})
    return sig, model.predict(sig, con), con


# ------------------------------------------------------------------ the model
def test_a_prediction_has_every_part_and_stays_in_range():
    sig, pred, _ = _predict(words_from(TALK, step=0.35), 20.0)
    assert 0 <= pred["score"] <= 100 and pred["band"] in {b for _, b in __import__(
        "clipfoundry.predictor.model", fromlist=["BANDS"]).BANDS}
    assert set(pred["channels"]) == {"vision", "sound", "language", "attention", "memory"}
    curve = pred["hold"]["curve"]  # the share still watching at 0 s, 1 s, ... the end
    assert all(len(v) + 1 == len(curve) for v in pred["channels"].values())  # one heatmap cell per second
    assert curve[0] <= 1.0 and all(a >= b for a, b in zip(curve, curve[1:])), "nobody comes back once they leave"
    assert 0 <= pred["hold"]["rate"] <= pred["hold"]["avg_view"] <= 100
    assert pred["measured"] == {"picture": False, "sound": True, "words": True, "speech": "transcript"}
    assert pred["components"]["look"] is None  # the picture is measured once the clip is rendered
    assert pred["reasons"] and all({"area", "good", "text"} <= set(r) for r in pred["reasons"])
    from clipfoundry.predictor import model

    json.dumps(model.public(pred))  # stored and sent as plain JSON


def test_words_that_start_late_make_a_weaker_hook():
    words = words_from(TALK, step=0.35)
    late = [{**w, "start": w["start"] + 4.0, "end": w["end"] + 4.0} for w in words]
    _, early_pred, _ = _predict(words, 24.0, quiet=None)
    _, late_pred, _ = _predict(late, 24.0, quiet=(0.0, 4.0))
    assert late_pred["hook"]["score"] < early_pred["hook"]["score"] - 10
    assert late_pred["hold"]["avg_view"] < early_pred["hold"]["avg_view"]
    assert any("first real word" in n or "silent" in n for n in late_pred["hook"]["notes"])


def test_a_loud_stretch_is_a_reaction_only_when_it_clearly_stands_out():
    from clipfoundry.predictor import signals

    words = words_every(10.0)
    flat = 2.0 * np.sin(np.arange(100) / 3.0) - 20.0  # small ups and downs between words: not a laugh
    assert signals.reactions_from(flat, 0.1, [w for w in words if w["start"] < 5]) == []
    laugh = flat.copy()
    laugh[70:80] = -8.0  # 12 dB above the speech for a second, with no words
    found = signals.reactions_from(laugh, 0.1, [w for w in words if w["start"] < 5])
    assert found and found[0][0] == pytest.approx(7.0, abs=0.15)


def test_learned_calibration_and_weights_are_used_and_bounded():
    from clipfoundry.predictor import model, signals

    sig = signals.from_source(0.0, 20.0, words_from(TALK, step=0.35), _loud(20.0))
    base = model.predict(sig, None)
    cal = model.predict(sig, None, {"hold": {"slope": 1.0, "intercept": 0.2, "shrink": 0.5, "n": 40}})
    assert cal["hold"]["avg_view_calibrated"] == pytest.approx(min(100, base["hold"]["avg_view"] + 10), abs=1)
    assert cal["hold"]["calibrated_on"] == 40
    weighted = model.predict(sig, None, {"weights": {"hook": 0.6}, "n": 30})
    assert weighted["mix"]["weights"]["hook"] > base["mix"]["weights"]["hook"]


# ------------------------------------------------------------------ fixes
def test_a_long_lead_in_gets_a_start_later_fix_mapped_to_the_recording():
    from clipfoundry.predictor import fixes

    words = words_from(LEAD_IN + TALK, step=0.35)
    sig, pred, _ = _predict(words, words[-1]["end"] + 0.6)
    out = fixes.suggest(sig, pred, {}, None, edit={"silence": "light"}, to_source=lambda t: 100.0 + t)
    start = next(f for f in out if f["id"] == "start_later")
    why = next(w for w in words if w["w"] == "Why")
    assert start["kind"] == "edit" and start["edit"]["start"] == pytest.approx(100.0 + why["start"] - 0.12, abs=0.05)
    assert start["gain"]["score"] > 0 and start["gain"]["hook"] > 0
    assert "Why do most people never save money?" in start["why"]


def test_fixes_never_cost_score_and_are_advice_without_an_edit():
    from clipfoundry.predictor import fixes

    for text in (TALK, LEAD_IN + TALK):
        words = words_from(text, step=0.35)
        sig, pred, _ = _predict(words, words[-1]["end"] + 2.0)
        offered = fixes.suggest(sig, pred, {}, None, edit=None, to_source=None)
        assert all(f["gain"] is None or f["gain"]["score"] >= 0 for f in offered)
        assert all(f["kind"] == "advice" and f["edit"] is None for f in offered)
        assert len(offered) <= fixes.MAX_FIXES


def test_an_option_already_on_is_not_offered_again():
    from clipfoundry.predictor import fixes

    words = words_from(TALK, step=0.35)
    sig, pred, _ = _predict(words, words[-1]["end"] + 0.6, level=-40.0)  # quiet sound
    off = fixes.suggest(sig, pred, {}, None, edit={"normalize_audio": False})
    on = fixes.suggest(sig, pred, {}, None, edit={"normalize_audio": True})
    assert any(f["id"] == "louder" and f["edit"] == {"normalize_audio": True} for f in off)
    assert not any(f["id"] == "louder" for f in on)


def test_output_times_map_back_to_the_recording_across_removed_pauses():
    from clipfoundry import predictor

    f = predictor.to_source([{"src_start": 10.0, "src_end": 13.0, "out_start": 0.0, "out_end": 3.0, "speed": 1.0},
                             {"src_start": 15.5, "src_end": 18.0, "out_start": 3.0, "out_end": 5.5, "speed": 1.0}])
    assert f(1.0) == pytest.approx(11.0) and f(4.0) == pytest.approx(16.5) and f(9.0) == pytest.approx(18.0)
    fast = predictor.to_source([{"src_start": 0.0, "src_end": 12.0, "out_start": 0.0, "out_end": 10.0, "speed": 1.2}])
    assert fast(5.0) == pytest.approx(6.0)
    assert predictor.to_source([]) is None


# ------------------------------------------------------------------ clip picking (bounded)
def test_clip_picking_gets_a_bounded_explained_adjustment():
    from clipfoundry import predictor
    from clipfoundry.pipeline import deep

    words = words_from(LEAD_IN + TALK, step=0.35)
    loud = _loud(40.0)
    weak = predictor.moment(0.0, 20.0, words, loud, None, learned_values=None)
    strong = predictor.moment(words[18]["start"] - 0.1, words[-1]["end"] + 0.3, words, loud, None,
                              learned_values=None)
    assert -predictor.MOMENT_MAX <= weak["adjust"] <= predictor.MOMENT_MAX
    assert strong["hook"] > weak["hook"]
    r = {"score": 60.0, "deep": {"extras": {}, "audio": {"score": 0.5}, "semantic": {"score": 0.5}},
         "predicted": {**strong, "adjust": 4.0}}
    score, why = deep.clip_score(r)
    assert score == pytest.approx(64.0, abs=0.01) and any("viral predictor" in w for w in why)


# ------------------------------------------------------------------ learning from results
def _rows(n: int, platform: str = "tiktok", good: bool = True) -> list[dict]:
    rows = []
    for k in range(n):
        score = 20 + (60 * k) // max(1, n - 1)
        views = (10 + 20 * k) if good else (10 + 20 * (n - k))
        rows.append({"publication_id": f"pub{platform}{k}", "platform": platform, "views": views,
                     "avg_view_percentage": 30.0 + k, "prediction": {
                         "model": 1, "score": score, "band": "Good" if score >= 60 else "Fair", "hook": score,
                         "avg_view": 40 + k // 2, "rate": 30, "components": {
                             "content": score, "hook": score, "watch": 50, "memory": 40, "look": 60}}})
    return rows


def test_accuracy_needs_enough_posts_and_reads_the_rank_match():
    from clipfoundry.predictor import learn

    few = learn.accuracy(_rows(learn.MIN_RANK - 1))
    assert few["platforms"]["tiktok"]["spearman"] is None
    good = learn.accuracy(_rows(12))["platforms"]["tiktok"]
    assert good["spearman"] > 0.9 and good["top_third_hit"] == 1.0
    bad = learn.accuracy(_rows(12, good=False))["platforms"]["tiktok"]
    assert bad["spearman"] < -0.9
    assert good["avg_view_posts"] == 12 and good["avg_view_error"] is not None


def test_calibration_and_weights_wait_for_enough_posts_and_move_little():
    from clipfoundry.predictor import learn, model

    assert learn.calibrate(_rows(learn.MIN_CAL - 1)) is None
    cal = learn.calibrate(_rows(learn.MIN_CAL + 5))
    assert cal and learn.SLOPE_RANGE[0] <= cal["slope"] <= learn.SLOPE_RANGE[1] and 0 < cal["shrink"] < 1
    assert learn.weights(_rows(learn.MIN_WEIGHTS - 1)) is None
    w = learn.weights(_rows(learn.MIN_WEIGHTS + 10))
    for k, base in model.WEIGHTS.items():
        assert base * 0.9 - 1e-9 <= w["weights"][k] <= base * 1.1 + 1e-9  # one step: at most 10%
    # many updates never leave ±40% of the designed weight
    prev = None
    for _ in range(30):
        prev = learn.weights(_rows(learn.MIN_WEIGHTS + 10), prev)["weights"]
    for k, base in model.WEIGHTS.items():
        assert base * (1 - learn.MAX_SHIFT) - 1e-9 <= prev[k] <= base * (1 + learn.MAX_SHIFT) + 1e-9


def test_learning_keeps_its_results_and_pausing_the_brain_ignores_them(data):
    from clipfoundry import db, predictor
    from clipfoundry.predictor import learn

    out = learn.learn(_rows(learn.MIN_WEIGHTS + 2))
    assert "rank match" in out["message"]
    assert predictor.learned()["weights"] and predictor.learned()["hold"]["n"] >= learn.MIN_CAL
    assert learn.view()["platforms"]["tiktok"]["posts"] == learn.MIN_WEIGHTS + 2
    db.save_settings({"brain_paused": True})
    assert predictor.learned() is None


# ------------------------------------------------------------------ the real file
def _project(src: Path, pdir: Path) -> dict:
    from clipfoundry.pipeline.ffmpeg_utils import probe

    meta = probe(src)
    return {"id": "p1", "name": "synthetic", "source_path": str(src), "dir": str(pdir), "info": meta,
            "options": {}, **meta}


@needs_ffmpeg
def test_every_render_keeps_its_prediction_for_that_file(data):
    from clipfoundry import config, predictor
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    src = make_video(data / "src.mp4", seconds=9.0)
    words = words_every(3.0) + [{**w, "start": w["start"] + 5.3, "end": w["end"] + 5.3} for w in words_every(2.7)]
    clip = {"id": "c1", "start": 0.1, "end": 8.4, "hook": "", "edit": {"tracking": "center", "silence": "off"}}
    out = render.render_clip(_project(src, data / "proj"), clip, words, {**config.DEFAULT_SETTINGS, **FAST},
                             JobContext())
    info = out["render_info"]
    pred = info["prediction"]
    assert pred["file_sha256"] == info["artifact"]["sha256"] and pred["measured"]["picture"] is True
    assert len(pred["hold"]["curve"]) == math.ceil(out["duration"]) + 1  # 0 s, 1 s, ... the end
    assert pred["measured"]["speech"] == "transcript"
    pauses = next(f for f in pred["fixes"] if f["id"] == "remove_pauses")
    assert pauses["edit"] == {"silence": "light"} and pauses["gain"]["score"] >= 0
    # the stored prediction belongs to this file: another file's is not shown
    row = {"id": "c1", "output_path": out["output_path"], "render_info": info, "active_version": ""}
    assert predictor.stored(row)["score"] == pred["score"]
    other = {**row, "render_info": {**info, "artifact": {**info["artifact"], "sha256": "different"}}}
    assert predictor.stored(other) is None
    # switched off: renders carry no prediction
    off = render.render_clip(_project(src, data / "proj"), clip, words,
                             {**config.DEFAULT_SETTINGS, **FAST, "viral_predictor": False}, JobContext())
    assert "prediction" not in off["render_info"]


@needs_ffmpeg
def test_a_black_silent_opening_scores_low_and_says_why(data):
    from clipfoundry import config, predictor

    good = make_video(data / "good.mp4", seconds=10.0, size="540x960")
    bad = make_video(data / "bad.mp4", seconds=10.0, size="540x960", black=(0.0, 3.0), silent=(0.0, 3.0))
    words = words_from(TALK, step=0.35)[:24]
    late = [{**w, "start": w["start"] + 3.0, "end": w["end"] + 3.0} for w in words if w["end"] + 3.0 < 10]
    p_good = predictor.run(good, [w for w in words if w["end"] < 10], dict(config.DEFAULT_SETTINGS),
                           learned_values=None)
    p_bad = predictor.run(bad, late, dict(config.DEFAULT_SETTINGS), learned_values=None)
    assert p_bad["hook"]["score"] < p_good["hook"]["score"] and p_bad["score"] < p_good["score"]
    assert any("dark or black" in n for n in p_bad["hook"]["notes"])
    assert all(f["kind"] == "advice" for f in p_bad["fixes"])  # a file ClipForge did not make: advice only


# ------------------------------------------------------------------ Check a video and the routes
@pytest.fixture()
def checks_env(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import jobs as studio_jobs
    from clipfoundry.studio import video_flow

    def submit(job_id: str) -> None:
        job = db.fetch("studio_jobs", job_id)
        if job and job["kind"] == "viral_check":
            studio_jobs.run(job_id)

    monkeypatch.setattr(worker, "submit_studio", submit)
    monkeypatch.setattr(video_flow, "transcript_words", lambda asset, settings, lease=None, cached_only=False,
                        lo=0.05, hi=0.45: words_from(TALK, step=0.35)[:20])
    return data


def _asset(tmp: Path, n: int, seconds: float = 8.0, workspace: str = "local") -> dict:
    from clipfoundry import db

    path = make_video(tmp / f"check{n}.mp4", seconds=seconds, size="540x960")
    return db.insert("assets", {"id": f"as-{workspace}-{n}", "workspace_id": workspace, "kind": "video",
                                "filename": f"draft{n}.mp4", "sha256": f"sha-{n}", "size": path.stat().st_size,
                                "path": str(path), "probe": {"duration": seconds, "has_audio": True,
                                                             "width": 540, "height": 960}})


@needs_ffmpeg
def test_check_a_video_runs_as_a_job_and_keeps_the_file_on_delete(checks_env):
    from clipfoundry import db
    from clipfoundry.predictor import checks

    asset = _asset(checks_env, 1)
    row = checks.create("local", asset["id"], "")
    done = checks.view(checks.get(row["id"], "local"))
    assert done["status"] == "ready", done
    assert done["title"] == "draft1" and done["result"]["score"] == done["summary"]["score"]
    assert done["result"]["words_note"].startswith("Words from the transcript")
    assert done["media_url"] == f"/api/assets/{asset['id']}/media"
    assert checks.list_for("local")[0]["id"] == row["id"] and "result" not in checks.list_for("local")[0]
    with pytest.raises(checks.NotFound):
        checks.get(row["id"], "someone-else")
    again = checks.again(row["id"], "local")
    assert again["status"] == "ready"
    assert checks.delete(row["id"], "local")["notes"] == ["The video file stays in your media."]
    assert db.fetch("assets", asset["id"]) and Path(asset["path"]).is_file()


def test_a_long_video_or_a_picture_is_refused(checks_env):
    from clipfoundry import db
    from clipfoundry.predictor import checks

    path = checks_env / "long.mp4"
    path.write_bytes(b"x")
    db.insert("assets", {"id": "as-long", "workspace_id": "local", "kind": "video", "filename": "long.mp4",
                         "sha256": "sha-long", "size": 1, "path": str(path), "probe": {"duration": 3600.0}})
    with pytest.raises(checks.CheckError, match="short videos"):
        checks.create("local", "as-long")
    db.insert("assets", {"id": "as-pic", "workspace_id": "local", "kind": "image", "filename": "a.png",
                         "sha256": "sha-pic", "size": 1, "path": str(path), "probe": {}})
    with pytest.raises(checks.CheckError, match="video file"):
        checks.create("local", "as-pic")


def test_a_checked_video_is_kept_when_a_project_is_deleted(checks_env):
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    db.insert("viral_checks", {"id": "vc-1", "workspace_id": "local", "asset_id": "as-kept-1", "title": "x"})
    assert "as-kept-1" in project_delete._used_elsewhere("local", "clips", "p-none")  # noqa: SLF001


@needs_ffmpeg
def test_the_routes(checks_env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import config, db
    from clipfoundry.api import app
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    asset = _asset(checks_env, 2)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        made = api.post("/api/predictor/checks", json={"asset_id": asset["id"], "title": "My draft"}, headers=H)
        assert made.status_code == 200, made.text
        got = api.get(f"/api/predictor/checks/{made.json()['id']}", headers=H).json()
        assert got["status"] == "ready" and got["title"] == "My draft" and got["result"]["fixes"] is not None
        assert api.get("/api/predictor/checks", headers=H).json()[0]["summary"]["score"] == got["result"]["score"]
        assert api.post("/api/predictor/checks", json={"asset_id": "nope"}, headers=H).status_code == 404
        acc = api.get("/api/predictor/accuracy", headers=H).json()
        assert acc["min_posts"] > 0 and acc["designed_weights"]["watch"] > 0

        # a clip rendered before the predictor existed is predicted on request and keeps the result
        src = make_video(checks_env / "src.mp4", seconds=9.0)
        db.insert("projects", {"id": "p1", "name": "synthetic", "source_path": str(src), "status": "done",
                               "duration": 9.0, "width": 640, "height": 360, "fps": 25})
        clip = db.insert("clips", {"id": "c1", "project_id": "p1", "start": 0.1, "end": 8.0, "title": "t",
                                   "status": "ready"})
        out = render.render_clip(_project(src, checks_env / "proj"), clip, words_every(8.0),
                                 {**config.DEFAULT_SETTINGS, **FAST, "viral_predictor": False}, JobContext())
        db.update_clip("c1", **out)
        before = api.get("/api/clips/c1/prediction", headers=H).json()
        assert before["prediction"] is None and before["rendered"] is True
        made = api.post("/api/clips/c1/prediction", json={}, headers=H)
        assert made.status_code == 200, made.text
        after = api.get("/api/clips/c1/prediction", headers=H).json()["prediction"]
        assert after["score"] == made.json()["prediction"]["score"]
        card = api.get("/api/clips/c1", headers=H).json()
        assert card["prediction"]["score"] == after["score"]
        assert api.post("/api/clips/missing/prediction", json={}, headers=H).status_code == 404


def test_clipforge_ai_knows_where_the_predictor_is():
    from clipfoundry.brain import library

    for q in ("where is the viral score?", "how do I check a video before posting?", "what does the heatmap mean",
              "how do I use the predictor"):
        assert library.search(q, "").ids[0] == "guide:predictor", q
    # a craft question about hooks still reads the hook playbook first
    assert library.search("what makes a good hook?", "").ids[0] == "hooks"
