"""The office shows the work you started yourself, truthfully (studio upgrade handoff, section 4).

Before this, robots read only Autopilot's queue: a Make clips project, a rough cut, a final render, a Find media
download or an editor request left the whole office idle, and every robot looked "paused" when Autopilot had simply
never been started. Each state here comes from a recorded row; nothing is estimated or invented.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return db


def _states(db) -> dict[str, dict]:
    from clipfoundry.office import view

    return {row["id"]: row for row in view.role_states(db.get_settings())}


def _video(db, name="Trip video", ws="local") -> dict:
    return db.insert("studio_projects", {"workspace_id": ws, "name": name})


def _job(db, kind: str, target: str, status: str, ws="local", **fields) -> dict:
    from clipfoundry.studio.jobs import enqueue

    job = enqueue(ws, kind, target, 0, submit=False)
    db.update("studio_jobs", job["id"], status=status, **fields)
    return db.fetch("studio_jobs", job["id"])


def test_never_started_autopilot_is_not_a_pause(data):
    rows = _states(data)
    assert {r["state"] for r in rows.values()} <= {"idle", "unavailable"}
    assert all(r["idle_reason"] for r in rows.values())
    assert rows["radar"]["idle_reason"] == "Waiting for a file or link you add."


def test_a_make_clips_project_moves_through_the_departments(data):
    p = data.create_project("Interview", status="processing", stage="transcribe", progress=0.3,
                            message="Transcribing")
    rows = _states(data)
    archive = rows["archive"]
    assert archive["state"] == "working" and archive["owner_tasks"] == 1
    task = archive["task"]
    assert task["origin"] == "owner" and task["title"] == "Interview" and task["message"] == "Transcribing"
    assert task["progress"] == 0.3 and task["shared"]["project_id"] == p["id"]
    # its manager and the Director follow it, even though Autopilot was never started
    assert rows["vector"]["state"] == rows["command"]["state"] == "working"
    assert rows["splice"]["state"] == "idle"
    data.update_project(p["id"], stage="render", progress=0.8, message="Rendering clips")
    rows = _states(data)
    assert rows["archive"]["state"] == "idle" and rows["splice"]["state"] == "working"
    assert rows["frame"]["state"] == "working"
    data.update_project(p["id"], status="ready", stage="done", progress=1.0)
    assert _states(data)["splice"]["state"] == "idle"


def test_unmeasured_work_shows_no_progress(data):
    data.create_project("Interview", status="processing", stage="candidates", progress=0, message="")
    task = _states(data)["spark"]["task"]
    assert task["progress"] is None and task["message"] == "Finding moments"


def test_studio_jobs_are_queued_running_and_failed_truthfully(data):
    v = _video(data)
    _job(data, "video_build", v["id"], "queued")
    rows = _states(data)
    assert rows["story"]["state"] == "queued" and rows["story"]["task"]["title"] == "Trip video"
    assert rows["story"]["task"]["status"] == "queued" and rows["story"]["task"]["progress"] is None
    assert "Queued" in rows["story"]["idle_reason"]
    render = _job(data, "video_render", v["id"], "running", progress=0.4, message="Rendering 4 of 10 pieces")
    rows = _states(data)
    assert rows["check"]["state"] == "working" and rows["check"]["task"]["progress"] == 0.4
    assert rows["check"]["task"]["shared"]["video_id"] == v["id"]
    data.update("studio_jobs", render["id"], status="failed", error="Not enough free disk space")
    rows = _states(data)
    assert rows["check"]["state"] == "error" and "free disk space" in rows["check"]["error"]
    # an old failure is history, not a robot stuck in error
    data.execute("UPDATE studio_jobs SET updated_at = ? WHERE id = ?", (time.time() - 3 * 3600, render["id"]))
    assert _states(data)["check"]["state"] == "idle"


def test_find_media_and_example_videos_have_their_robots(data):
    v = _video(data)
    imp = data.insert("media_imports", {"workspace_id": "local", "project_id": v["id"], "provider": "openverse",
                                        "kind": "effect", "external_id": "rain-1", "title": "Rain on a roof",
                                        "status": "importing"})
    _job(data, "media_import", imp["id"], "running", message="Downloading")
    asset = data.insert("assets", {"workspace_id": "local", "kind": "video", "sha256": "ab" * 32, "size": 10,
                                   "path": "/nowhere"})
    ref = data.insert("reference_videos", {"workspace_id": "local", "asset_id": asset["id"], "title": "Fast edit"})
    _job(data, "reference_analysis", ref["id"], "running", message="Measuring cuts")
    rows = _states(data)
    assert rows["pulse"]["state"] == "working" and rows["pulse"]["task"]["title"] == "Rain on a roof"
    assert rows["clock"]["state"] == "working"  # Media research's manager
    assert rows["boost"]["state"] == "working" and rows["boost"]["task"]["ref_type"] == "example"


def test_a_link_download_belongs_to_intake_and_names_its_project(data):
    p = data.create_project("Talk", status="importing", stage="download")
    link = data.insert("link_imports", {"workspace_id": "local", "project_id": p["id"],
                                        "url": "https://www.youtube.com/watch?v=abc", "status": "running",
                                        "request_id": "req-1"})
    _job(data, "link_import", link["id"], "running", message="Downloading the video")
    radar = _states(data)["radar"]
    assert radar["state"] == "working" and radar["task"]["title"] == "Talk"
    assert radar["task"]["shared"]["project_id"] == p["id"] and radar["tasks"] == 1  # not counted twice


def test_an_editor_request_waiting_for_the_ai_service(data):
    v = _video(data)
    data.insert("edit_requests", {"workspace_id": "local", "project_id": v["id"], "text": "keep the story together", "base_revision": 1,
                                  "status": "thinking", "source": "ai", "provider": "Ollama"})
    story = _states(data)["story"]
    assert story["state"] == "working" and "Ollama" in story["task"]["message"]


def test_paused_autopilot_does_not_hide_your_own_work(data):
    from clipfoundry.autopilot import state

    state.put("setup:started", time.time())
    data.save_settings({"autopilot_enabled": False})  # turned off after a start: paused
    data.create_project("Interview", status="processing", stage="scoring", progress=0.5)
    rows = _states(data)
    assert rows["boost"]["state"] == "working"
    assert rows["vector"]["state"] == "working" and rows["command"]["state"] == "working"
    assert rows["radar"]["state"] == "paused" and "Your own projects still run" in rows["radar"]["idle_reason"]


def test_autopilot_projects_are_not_counted_twice(data):
    data.create_project("Found", status="processing", stage="render", origin="autopilot")
    assert _states(data)["splice"]["state"] == "idle"  # its own queue job is what shows Autopilot's work


def test_another_workspace_is_not_shown(data):
    v = _video(data, ws="someone-else")
    _job(data, "video_build", v["id"], "running", ws="someone-else")
    data.create_project("Theirs", status="processing", stage="render", workspace_id="someone-else")
    rows = _states(data)
    assert rows["story"]["state"] == rows["splice"]["state"] == "idle"


def test_rooms_list_your_recent_work(data):
    from clipfoundry.office import view

    p = data.create_project("Interview", status="processing", stage="transcribe")
    v = _video(data)
    intake = view.room("intake")
    assert [x["id"] for x in intake["projects"]] == [p["id"]] and intake["videos"][0]["id"] == v["id"]
    assert intake["does"].startswith("Your files and links")
    control = view.room("control")
    assert control["yours"] == {"running": 1, "queued": 0}
    assert view.room("research")["media"] == [] and view.room("editing")["videos"][0]["name"] == "Trip video"
    assert view.room("discover")["id"] == "intake"  # an old address finds the room that replaced it
    with pytest.raises(KeyError):
        view.room("attic")


def test_the_snapshot_lists_your_work_item_by_item(data):
    from clipfoundry.office import view

    v = _video(data)
    _job(data, "video_build", v["id"], "queued")
    p = data.create_project("Interview", status="processing", stage="render", progress=0.6, message="Rendering clips")
    work = {w["kind"]: w for w in view.snapshot()["work"]}
    assert work["video_build"] == {"id": work["video_build"]["id"], "kind": "video_build", "stage": "",
                                   "status": "queued", "role": "story", "message": "Waiting for a worker",
                                   "progress": None, "project_id": "", "video_id": v["id"], "title": "Trip video",
                                   "waiting_on": ""}
    assert work["project"]["role"] == "splice" and work["project"]["progress"] == 0.6
    assert work["project"]["project_id"] == p["id"]


def test_an_editor_question_or_proposal_waits_for_you_until_the_edit_moves_on(data):
    from clipfoundry.office import view

    v = data.insert("studio_projects", {"workspace_id": "local", "name": "Trip video", "plan_revision": 3})
    ask = data.insert("edit_requests", {"workspace_id": "local", "project_id": v["id"], "text": "move the part",
                                        "base_revision": 3, "status": "question",
                                        "message": "Which part do you mean: the summit or the lake?"})
    story = _states(data)["story"]
    assert story["state"] == "waiting" and story["task"]["waiting_on"] == "you"
    assert story["task"]["blocked_reason"].startswith("Waiting for your answer: Which part")
    work = view.snapshot()["work"]
    assert [(w["status"], w["title"], w["waiting_on"], w["video_id"]) for w in work] == \
        [("waiting", "Trip video", "you", v["id"])]
    data.update("edit_requests", ask["id"], status="ready", message="Check the changes, then apply them.")
    assert "check the proposed changes" in _states(data)["story"]["task"]["message"]
    # another edit made the proposal out of date: the editor says so, and nothing waits on it any more
    data.update("studio_projects", v["id"], plan_revision=4)
    assert _states(data)["story"]["state"] == "idle" and view.snapshot()["work"] == []


def test_each_robot_keeps_a_log_of_your_work_that_ended(data):
    from clipfoundry.office import work

    v = _video(data, name="Lake video")
    _job(data, "video_build", v["id"], "done")
    _job(data, "video_render", v["id"], "failed", error="Not enough free disk space")
    _job(data, "video_preview", v["id"], "canceled")
    data.create_project("Interview", status="ready", stage="done")
    data.create_project("Talk", status="error", stage="transcribe", error="No sound in the file")
    data.insert("edit_requests", {"workspace_id": "local", "project_id": v["id"], "text": "shorten the intro",
                                  "base_revision": 1, "status": "applied"})
    theirs = _video(data, name="Their video", ws="someone-else")
    _job(data, "video_build", theirs["id"], "done", ws="someone-else")
    from clipfoundry.studio.jobs import enqueue

    old = enqueue("local", "video_build", v["id"], 7, submit=False)  # an earlier revision's rough cut, two days ago
    data.update("studio_jobs", old["id"], status="done")
    data.execute("UPDATE studio_jobs SET updated_at = ? WHERE id = ?", (time.time() - 2 * 86400, old["id"]))

    story = work.history("story")
    assert [e["type"] for e in story] == ["job_done", "job_done"]  # this workspace, this day only
    assert {e["message"] for e in story} == {"Building the rough cut: Lake video",
                                             "Changes applied: “shorten the intro”"}
    check = work.history("check")
    assert check[0]["type"] == "job_failed" and "free disk space" in check[0]["message"]
    assert {e["message"] for e in work.history("splice")} >= {"Clips rendered: Interview",
                                                              "Rendering a preview: Lake video"}
    archive = work.history("archive")
    assert archive == [{**archive[0], "type": "job_failed", "message": "Transcribing: Talk (No sound in the file)"}]
    assert work.history("radar") == []


def test_the_robot_log_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        db.create_project("Interview", status="ready", stage="done")
        assert c.get("/api/office/robots/splice/log").json()["entries"][0]["message"] == "Clips rendered: Interview"
        assert c.get("/api/office/robots/attic/log").status_code == 404
