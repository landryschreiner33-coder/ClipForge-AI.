"""Persistent, explicitly approved teaching knowledge influences later real clip blueprints, never results."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def client(data):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def material(kind="instruction", **extra):
    return {"kind": kind, "title": "Readable science captions", "content": "Keep the facts and story intact.",
            "tags": ["science"], "preferences": {"caption_style": "minimal"},
            "example_label": "good" if kind == "example" else "", **extra}


def later_plan(text="Science explains why sleep matters."):
    from clipfoundry import db
    from clipfoundry.pipeline import blueprint

    project = db.create_project("A later source", origin="autopilot", duration=6)
    clip = db.create_clip(project["id"], start=0, end=5, duration=5, title=text, caption_text=text)
    words = [{"w": word, "start": 0.2 + k * 0.5, "end": 0.6 + k * 0.5} for k, word in enumerate(text.split())]
    settings = db.get_settings()
    plan = blueprint.build(clip, project, words, settings)
    issues = blueprint.validate(plan, 6, words)
    assert not blueprint.errors(issues)
    saved = blueprint.save(plan, issues)
    return clip, plan, saved


def test_uploaded_instruction_requires_approval_then_changes_persisted_later_blueprint(client, data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import blueprint

    response = client.post("/api/brain/knowledge/upload", headers=H,
                           files={"file": ("guide.md", b"# My science guide\nPrefer a quiet, readable caption style.")},
                           data={"metadata": json.dumps(material())})
    assert response.status_code == 200
    row = response.json()
    assert not row["approved"] and row["state"] == "needs_approval"
    assert "quiet" in client.get("/api/brain/knowledge?q=quiet").json()[0]["content"]
    first, before, _ = later_plan()
    assert before.captions.style == "bold" and not knowledge.influences(first["id"])
    assert client.post(f"/api/brain/knowledge/{row['id']}/approve", headers=H,
                       json={"revision": row["revision"]}).status_code == 200
    clip, plan, saved = later_plan()
    assert plan.captions.style == "minimal"
    influence = client.get(f"/api/brain/knowledge/influences/{clip['id']}").json()[0]
    assert influence["decisions"] == {"caption_style": {"before": "bold", "after": "minimal"}}
    assert influence["snapshot"]["title"] == row["title"] and influence["revision"] == 1
    assert "Approved instruction" in " ".join(plan.reasons)
    blueprint.save(plan, [])  # re-saving/rendering the plan does not create extra explanations
    assert len(knowledge.influences(clip["id"])) == 1
    db._ready.clear()  # another process/restart sees the durable DB and stored plan
    assert blueprint.plan_of(clip["id"]).captions.style == "minimal"
    assert knowledge.get(row["id"])["approved_at"] is not None
    assert client.get(f"/api/brain/knowledge/{row['id']}/asset?download=true").content.startswith(b"# My")
    exported = client.get("/api/brain/knowledge/export").json()
    assert exported["knowledge"][0]["asset_sha256"] and "asset_path" not in exported["knowledge"][0]
    assert exported["influences"][0]["blueprint_id"] == saved["id"]
    assert not db.select("brain_observations") and not db.select("performance")


def test_export_keeps_older_knowledge_and_influences_beyond_workspace_limits(client, data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge

    knowledge_ids = {f"lesson-{i:03}" for i in range(503)}
    influence_ids = {f"influence-{i:03}" for i in range(502)}
    with db.connect() as conn:
        conn.executemany("INSERT INTO brain_knowledge "
                         "(id, kind, title, content, filename, asset_path, created_at, updated_at) "
                         "VALUES (?, 'reference', ?, ?, 'guide.md', ?, ?, ?)",
                         [(f"lesson-{i:03}", f"Guide {i}", f"Saved guide text {i}",
                           str(data / "private-originals" / f"guide-{i}.md"), i + 1, i + 1)
                          for i in range(503)])
        conn.executemany("INSERT INTO brain_influences "
                         "(id, clip_id, blueprint_id, knowledge_id, revision, snapshot, decisions, created_at) "
                         "VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                         [(f"influence-{i:03}", f"clip-{i:03}", f"plan-{i:03}", f"lesson-{i:03}",
                           json.dumps({"title": f"Approved revision {i}"}),
                           json.dumps({"caption_style": {"before": "bold", "after": "minimal"}}), i + 1)
                          for i in range(502)])

    assert len(knowledge.search()) == 500  # browsing remains bounded
    response = client.get("/api/brain/knowledge/export")
    assert response.status_code == 200
    exported = response.json()
    assert {row["id"] for row in exported["knowledge"]} == knowledge_ids
    assert {row["id"] for row in exported["influences"]} == influence_ids
    oldest = next(row for row in exported["knowledge"] if row["id"] == "lesson-000")
    assert oldest["content"] == "Saved guide text 0" and oldest["filename"] == "guide.md"
    assert all("asset_path" not in row for row in exported["knowledge"])
    oldest_influence = next(row for row in exported["influences"] if row["id"] == "influence-000")
    assert oldest_influence["snapshot"]["title"] == "Approved revision 0"
    assert oldest_influence["decisions"]["caption_style"]["after"] == "minimal"
    assert "Uploaded files are downloaded separately" in exported["note"]


def test_edit_disable_delete_and_stale_approval_preserve_explanation(data):
    from clipfoundry.autopilot import knowledge
    from clipfoundry import db

    row = knowledge.create(material())
    knowledge.approve(row["id"], row["revision"])
    clip, _, _ = later_plan()
    edited = knowledge.edit(row["id"], {"content": "New reviewed instruction"})
    assert edited["revision"] == 2 and not edited["approved"]
    with pytest.raises(knowledge.Invalid, match="changed"):
        knowledge.approve(row["id"], 1)
    assert later_plan()[1].captions.style == "bold"
    knowledge.approve(row["id"], 2)
    knowledge.edit(row["id"], {"enabled": False})
    assert later_plan()[1].captions.style == "bold"
    knowledge.delete(row["id"])
    assert not db.select("brain_knowledge")
    saved = knowledge.influences(clip["id"])[0]
    assert not saved["knowledge_exists"] and saved["snapshot"]["title"] == row["title"]
    assert saved["revision"] == 1


def test_scoped_instruction_wins_example_and_pausing_stops_new_influence(data):
    from clipfoundry.autopilot import knowledge
    from clipfoundry import db

    example = knowledge.create(material("example", preferences={"caption_style": "clean", "pacing": "continuous"}))
    knowledge.approve(example["id"], 1)
    instruction = knowledge.create(material(preferences={"caption_style": "minimal"}))
    knowledge.approve(instruction["id"], 1)
    _, plan, _ = later_plan()
    assert plan.captions.style == "minimal" and len(plan.knowledge) == 2
    assert later_plan("Cooking makes a satisfying dinner.")[1].captions.style == "bold"
    db.save_settings({"brain_paused": True})
    assert not later_plan()[1].knowledge


def test_examples_upload_measured_media_and_corrective_preference_changes_later_plan(client, data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for the real-media example test")
    path = data / "example.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=navy:s=64x96:d=0.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)
    response = client.post("/api/brain/knowledge/upload", headers=H,
                           files={"file": ("bad-example.mp4", path.read_bytes(), "video/mp4")},
                           data={"metadata": json.dumps(material("example", example_label="bad",
                             features={"hook": "Too much setup", "captions": "Too much visual noise"},
                             preferences={"caption_style": "minimal", "caption_emphasis": False}))})
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["example_label"] == "bad" and row["media"]["duration_s"] == pytest.approx(0.52, abs=.1)
    assert row["media"]["width"] == 64 and row["media"]["has_audio"] is False
    knowledge.approve(row["id"], 1)
    clip, plan, _ = later_plan()
    assert plan.captions.style == "minimal"
    assert knowledge.influences(clip["id"])[0]["snapshot"]["example_label"] == "bad"
    assert not db.select("brain_observations") and not db.select("publications")
    asset = knowledge.asset_file(row["id"])[0]
    assert asset.is_file()
    knowledge.delete(row["id"])
    assert not asset.exists()


def test_uploads_do_not_execute_code_or_import_fake_results(client, data):
    from clipfoundry import db

    sentinel = data / "executed"
    text = f"import pathlib; pathlib.Path({str(sentinel)!r}).write_text('bad')".encode()
    assert client.post("/api/brain/knowledge/upload", headers=H, files={"file": ("guide.py", text)},
                       data={"metadata": json.dumps(material())}).status_code == 422
    response = client.post("/api/brain/knowledge/upload", headers=H,
                           files={"file": ("../../instructions.md", text)}, data={"metadata": json.dumps(material())})
    assert response.status_code == 200 and response.json()["filename"] == "instructions.md"
    assert not sentinel.exists() and not response.json()["approved"]
    response = client.post("/api/brain/knowledge/upload", headers=H, files={"file": ("results.csv", b"clip_id,views\nfake,9999999\n")},
                           data={"metadata": json.dumps(material("reference", preferences={}))})
    assert response.status_code == 200 and not db.select("brain_observations")
    assert client.post("/api/brain/knowledge", headers=H, json=material(approved_at=1)).status_code == 422
    assert client.post("/api/brain/knowledge", headers=H, json=material(preferences={"privacy": "public"})).status_code == 422
    assert client.post("/api/brain/knowledge", json=material()).status_code == 403


def test_oversized_invalid_and_macro_uploads_are_cleaned(client, data):
    from clipfoundry.autopilot import knowledge
    from clipfoundry import db

    for filename, payload in [("oversize.txt", b"x" * (knowledge.MAX_DOCUMENT + 1)),
                              ("invalid.mp4", b"not a video"), ("invalid.json", b"{broken"),
                              ("invalid.txt", b"\xff\x00")]:
        kind = "example" if filename.endswith("mp4") else "instruction"
        result = client.post("/api/brain/knowledge/upload", headers=H, files={"file": (filename, payload)},
                             data={"metadata": json.dumps(material(kind))})
        assert result.status_code == 422
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("word/vbaProject.bin", b"macro")
        zipped.writestr("word/document.xml", b"<doc>Text</doc>")
    result = client.post("/api/brain/knowledge/upload", headers=H, files={"file": ("macro.docx", archive.getvalue())},
                         data={"metadata": json.dumps(material())})
    assert result.status_code == 422
    assert not db.select("brain_knowledge")
    assert not list((data / "data" / "brain" / "knowledge").glob("*/original*"))


def test_public_visibility_cohorts_and_selected_learning_do_not_leak(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, learner, scheduler, state
    from clipfoundry.publish import audience

    pub = {"platform": "youtube", "audience": {"intent": audience.PUBLIC},
           "delivery": {"audience_setup": "public_api_verified"}}
    assert learner.cohort(pub) == "public"
    pub["delivery"]["audience_setup"] = "public_restricted"
    assert learner.cohort(pub) == "unconfirmed"
    pub["delivery"]["audience_setup"] = "public_requested"
    assert learner.cohort(pub) == "public_requested"
    selected = {"platform": "youtube", "audience": {"intent": audience.SELECTED}, "delivery": {"audience_setup": "user_confirmed"}}
    assert learner.cohort(selected) == "selected"
    db.insert("learning_metrics", {"id": "hour:19:youtube:performance", "dimension": "hour", "key": "19", "platform": "youtube",
                                   "metric": "performance", "lift": 1.1, "n": 30, "data": {"reliable": True}})
    assert learner.lift("hour", "19", "youtube") == (1.1, 30)
    assert scheduler.Timing("youtube", db.get_settings()).hour == {19: 1.1}
    db.save_settings({"audience_youtube": "public", "autopilot_youtube": True, "autopilot_tiktok": False})
    assert learner.lift("hour", "19", "youtube") == (1.0, 0)
    assert scheduler.Timing("youtube", db.get_settings()).hour == {}
    old = db.insert("brain_strategies", {"name": "clip_length", "platform": "youtube", "cohort": "selected", "version": 1,
                                        "params": {"group_version": 1, "target_duration": 33}, "evidence": {}})
    assert brain.clip_length() is None
    db.update("brain_strategies", old["id"], cohort="public")
    assert brain.clip_length()["target_duration"] == 33
    state.put("learning:context", learner.learning_context(db.get_settings()))
    assert learner.lift("hour", "19", "youtube") == (1.1, 30)
