"""Deleting a project (studio/project_delete.py): a full video and a clips project go with everything kept only for
them (history, renders, folders, the media nothing else uses, the chat and the memories of that project only, planned
posts that have not started), while the owner's own files, media another project or example uses, anything posted,
memories for every video and the taste ClipForge AI learned stay. The plan says exactly that before anything changes;
running work is stopped first; Autopilot's work and a post on its way out are never interrupted; a draft with only a
planning chat goes too; and the routes answer with the plan or a reason and its code.
"""
from __future__ import annotations

import json
import os
import stat
import time

import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.jobs import worker

    db.init()
    monkeypatch.setattr(worker, "current", None)
    return tmp_path


def _stored(n: int, ws: str = "local", size: int = 3000) -> dict:
    """An upload ClipForge keeps: its read-only copy and what was made from it, in the asset's own folder."""
    from clipfoundry import db
    from clipfoundry.studio import uploads

    aid = f"as-{n:016x}"
    folder = uploads.assets_dir(ws) / aid
    folder.mkdir(parents=True)
    original = folder / "original.mp4"
    original.write_bytes(b"v" * size)
    os.chmod(original, 0o440)
    (folder / "transcript.json").write_text("{}")
    return db.insert("assets", {"id": aid, "workspace_id": ws, "kind": "video", "filename": f"clip{n}.mp4",
                                "sha256": f"{n:064x}", "size": size, "path": str(original),
                                "thumb_path": str(folder / "thumb.jpg"), "probe": {"duration": 5.0}})


def _linked(n: int, tmp_path, ws: str = "local") -> dict:
    """The owner's own file used where it is: ClipForge only keeps what it made from it."""
    from clipfoundry import db
    from clipfoundry.studio import uploads

    own = tmp_path / "My Videos" / f"trip{n}.mp4"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(b"own" * 100)
    aid = f"as-{n:016x}"
    work = uploads.assets_dir(ws) / aid
    work.mkdir(parents=True)
    (work / "audio.wav").write_bytes(b"w" * 500)
    return db.insert("assets", {"id": aid, "workspace_id": ws, "kind": "video", "filename": own.name,
                                "sha256": "quick:" + f"{n:064x}", "size": own.stat().st_size, "path": str(own),
                                "probe": {"duration": 5.0}})


def _video(name: str, asset_ids: list[str], ws: str = "local", **fields) -> dict:
    from clipfoundry import db

    return db.insert("studio_projects", {"workspace_id": ws, "name": name, "asset_ids": asset_ids,
                                         "status": "ready", **fields})


def _memories(ws: str, project_id: str) -> dict:
    from clipfoundry.brain import memories

    here = memories.remember(ws, "Keep the intro under five seconds for this video", kind="rule",
                             project_id=project_id)
    episode = memories.episode(ws, "Asked to cut the boring part: applied", project_id=project_id)
    everywhere = memories.remember(ws, "Never use red captions", kind="rule")
    memories.record_use(ws, [here["id"], everywhere["id"]], "chat", "msg-1")
    return {"here": here, "episode": episode, "everywhere": everywhere}


def _chat(ws: str, project_id: str, messages: int) -> dict:
    from clipfoundry import db

    chat = db.insert("brain_chats", {"workspace_id": ws, "project_id": project_id, "title": "Planning"})
    for k in range(messages):
        db.insert("brain_chat_messages", {"chat_id": chat["id"], "workspace_id": ws,
                                          "role": "owner" if k % 2 == 0 else "ai", "text": f"line {k}"})
    return chat


def test_a_video_goes_with_its_history_renders_chat_and_own_memories_and_keeps_what_others_use(env):
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete, uploads

    only = _stored(1)
    shared = _stored(2)
    in_old_revision = _stored(3)
    music = _stored(4)
    linked = _linked(5, env)
    vid = _video("Mountain trip", [only["id"], shared["id"], linked["id"]],
                 brief={"music": "supplied", "music_asset_id": music["id"]})["id"]
    other = _video("Other trip", [shared["id"]])
    old_plan = {"clips": [{"asset_id": in_old_revision["id"]}]}
    db.insert("edit_plans", {"project_id": vid, "revision": 1, "plan": old_plan}, key="project_id")
    db.insert("edit_plans", {"project_id": vid, "revision": 2, "plan": {"clips": [{"asset_id": only["id"]}]}},
              key="project_id")
    render = config.data_dir() / "videos" / vid / "r2" / "final.mp4"
    render.parent.mkdir(parents=True)
    render.write_bytes(b"r" * 4000)
    db.insert("studio_artifacts", {"project_id": vid, "revision": 2, "kind": "final", "path": str(render),
                                   "sha256": "x"})
    db.insert("edit_requests", {"workspace_id": "local", "project_id": vid, "base_revision": 2, "text": "shorter"})
    db.insert("media_imports", {"workspace_id": "local", "project_id": vid, "provider": "openverse", "kind": "image",
                                "external_id": "abc", "status": "ready", "asset_id": only["id"]})
    db.insert("asset_sources", {"workspace_id": "local", "asset_id": only["id"], "provider": "openverse",
                                "kind": "image", "external_id": "abc", "retrieved_at": 1.0, "sha256": "x"})
    db.insert("uploads", {"workspace_id": "local", "filename": "clip1.mp4", "size": 3000, "status": "complete",
                          "asset_id": only["id"]})
    mem = _memories("local", vid)
    _chat("local", vid, 4)
    _chat("local", "", 2)  # the general chat stays
    db.execute("INSERT INTO preferences (workspace_id, user_id, pref_key, schema_version, value, revision, updated_at) "
               "VALUES ('local', 'owner', 'appearance', 2, ?, 3, 1)",
               (json.dumps({"pinned": [vid, other["id"]]}),))

    plan = project_delete.plan("local", vid, "full_video")
    assert plan["blocked"] == "" and plan["working"] == ""
    assert plan["counts"] == {"clips": 0, "versions": 0, "revisions": 2, "renders": 1, "files": 4, "files_kept": 1,
                              "planned_posts": 0, "memories": 2, "chat_messages": 4}
    goes, stays = " ".join(plan["goes"]), " ".join(plan["stays"])
    assert "“Mountain trip” with its edit history (2 saved versions) and its previews and finished videos" in goes
    # in the order the video names them: its media, its brief, then older revisions
    assert "ClipForge's copies of “clip1.mp4”, “clip4.mp4”, “clip3.mp4”, which no other project uses" \
        in goes
    assert "What ClipForge made from “trip5.mp4” to work with it" in goes
    assert "2 notes ClipForge AI kept only for this project and its chat about it (4 messages)" in goes
    assert "“clip2.mp4” stays in ClipForge because another project or example uses it" in stays
    assert "Your own files on this computer stay where they are" in stays and "your rules and your taste" in stays
    # three copies (3000 bytes each with their transcripts), the render and the linked file's sound
    assert plan["freed_bytes"] == 3 * 3002 + 4000 + 500
    assert db.fetch("studio_projects", vid)  # the plan changed nothing

    out = project_delete.delete("local", vid, "full_video")
    assert out["deleted"] is True and out["goes"] == plan["goes"]
    assert db.fetch("studio_projects", vid) is None
    for table in ("edit_plans", "studio_artifacts", "edit_requests", "media_imports"):
        assert not db.select(table, "project_id = ?", (vid,)), table
    assert not (config.data_dir() / "videos" / vid).exists()
    for gone in (only, in_old_revision, music):
        assert db.fetch("assets", gone["id"]) is None and not uploads.work_dir(gone).exists()
    assert not db.select("asset_sources", "asset_id = ?", (only["id"],))
    assert not db.select("uploads", "asset_id = ?", (only["id"],))
    assert db.fetch("assets", shared["id"]) and os.path.isfile(shared["path"])
    assert stat.S_IMODE(os.stat(shared["path"]).st_mode) == 0o440  # a kept copy stays read-only
    assert db.fetch("assets", linked["id"]) is None and os.path.isfile(linked["path"])  # the owner's file stays
    assert not (uploads.assets_dir("local") / linked["id"]).exists()
    assert db.fetch("brain_memories", mem["here"]["id"]) is None
    assert db.fetch("brain_memories", mem["episode"]["id"]) is None
    assert db.fetch("brain_memories", mem["everywhere"]["id"])
    assert [u["memory_id"] for u in db.select("brain_memory_uses")] == [mem["everywhere"]["id"]]
    assert not db.select("brain_chats", "project_id = ?", (vid,))
    assert [c["project_id"] for c in db.select("brain_chats")] == [""]
    assert len(db.select("brain_chat_messages")) == 2
    pins = db.select("preferences", "pref_key = 'appearance'")[0]
    assert pins["value"]["pinned"] == [other["id"]] and pins["revision"] == 4
    assert db.fetch("studio_projects", other["id"])
    with pytest.raises(project_delete.DeleteError) as gone:
        project_delete.delete("local", vid, "full_video")
    assert gone.value.status == 404 and gone.value.code == "not_found"


def test_a_clips_project_goes_with_its_clips_copy_and_planned_posts_but_posted_history_stays(env):
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete, uploads

    asset = _stored(7, size=6000)
    p = db.create_project("Lake day", source_filename="clip7.mp4", status="ready", workspace_id="local",
                          asset_id=asset["id"], clip_mode="full_stories")
    pdir = config.projects_dir() / p["id"]
    pdir.mkdir(parents=True)
    os.link(asset["path"], pdir / "source.mp4")  # the project's link to the kept copy: frees nothing by itself
    db.update_project(p["id"], source_path=str(pdir / "source.mp4"))
    (pdir / "transcript.json").write_text("{" + " " * 98 + "}")
    clips = [db.create_clip(p["id"], start=0, end=10, status="ready"), db.create_clip(p["id"], start=20, end=30)]
    (pdir / "clips").mkdir()
    (pdir / "clips" / "1.mp4").write_bytes(b"c" * 900)
    db.create_version(clips[0]["id"], "edit", status="ready")
    db.insert("clip_scores", {"clip_id": clips[0]["id"], "final": 80}, key="clip_id")
    db.insert("clip_fingerprints", {"clip_id": clips[0]["id"], "source_key": "k"}, key="clip_id")
    db.insert("story_proposals", {"project_id": p["id"], "workspace_id": "local", "position": 0, "start_ms": 0,
                                  "end_ms": 10000})
    db.insert("taste_events", {"workspace_id": "local", "project_id": p["id"], "clip_id": clips[0]["id"],
                               "kind": "exported", "value": 1.0, "features": "[]"})
    db.insert("publications", {"clip_id": clips[0]["id"], "project_id": p["id"], "platform": "youtube",
                               "status": "done", "url": "https://youtu.be/x"})
    planned = db.insert("scheduled_publications", {"clip_id": clips[1]["id"], "platform": "youtube",
                                                   "status": "approved", "planned_at": 2e9})
    posted = db.insert("scheduled_publications", {"clip_id": clips[0]["id"], "platform": "tiktok",
                                                  "status": "published"})
    other = db.create_project("Another day", workspace_id="local", status="ready")
    found = db.insert("sources", {"platform": "local", "external_id": "lake.mp4", "title": "Lake day",
                                  "status": "analyzed", "project_id": p["id"]})

    plan = project_delete.plan("local", p["id"], "clips")
    assert plan["counts"]["clips"] == 2 and plan["counts"]["versions"] == 1 and plan["counts"]["planned_posts"] == 1
    goes, stays = " ".join(plan["goes"]), " ".join(plan["stays"])
    assert "The project “Lake day” and its 2 clips, with their edits and versions." in goes
    assert "ClipForge's copy of “clip7.mp4”, which no other project uses." in goes
    assert "1 planned post of its clips that has not been uploaded yet." in goes
    assert "Anything already posted to YouTube or TikTok stays there" in stays
    assert plan["freed_bytes"] == 6002 + 100 + 900  # the copy once (not its link), the transcript and a clip

    project_delete.delete("local", p["id"], "clips")
    assert db.get_project(p["id"]) is None and not db.list_clips(p["id"])
    assert not db.select("clip_versions", "clip_id = ?", (clips[0]["id"],))
    assert db.fetch("clip_scores", clips[0]["id"], "clip_id") is None
    assert not db.select("story_proposals", "project_id = ?", (p["id"],))
    assert not pdir.exists() and db.fetch("assets", asset["id"]) is None and not uploads.work_dir(asset).exists()
    assert db.fetch("scheduled_publications", planned["id"])["status"] == "canceled"
    assert "its project was deleted" in db.fetch("scheduled_publications", planned["id"])["status_note"]
    assert db.fetch("scheduled_publications", posted["id"])["status"] == "published"
    assert db.select("publications", "clip_id = ?", (clips[0]["id"],))  # the post history stays
    assert db.fetch("clip_fingerprints", clips[0]["id"], "clip_id")  # so the same clip is never posted twice
    assert db.select("taste_events", "project_id = ?", (p["id"],))  # and the taste it taught stays
    assert db.get_project(other["id"])
    found = db.fetch("sources", found["id"])  # Autopilot's record of the video stays, with no link to a lost project
    assert found["status"] == "analyzed" and found["project_id"] == ""


def test_media_another_project_or_example_uses_stays_and_only_its_link_goes(env):
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    asset = _stored(8)
    first = db.create_project("First", workspace_id="local", status="ready", asset_id=asset["id"])
    second = db.create_project("Second", workspace_id="local", status="ready", asset_id=asset["id"])
    for p in (first, second):
        pdir = config.projects_dir() / p["id"]
        pdir.mkdir(parents=True)
        os.link(asset["path"], pdir / "source.mp4")
    example = _stored(9)
    db.insert("reference_videos", {"workspace_id": "local", "asset_id": example["id"], "title": "Example"})
    vid = _video("Uses the example file", [example["id"]])["id"]

    plan = project_delete.plan("local", first["id"], "clips")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 1 and plan["freed_bytes"] == 0
    project_delete.delete("local", first["id"], "clips")
    assert db.fetch("assets", asset["id"]) and os.path.isfile(asset["path"])
    assert (config.projects_dir() / second["id"] / "source.mp4").is_file()
    assert stat.S_IMODE(os.stat(asset["path"]).st_mode) == 0o440
    project_delete.delete("local", vid, "full_video")
    assert db.fetch("assets", example["id"])  # the example still plays


def test_running_work_is_stopped_first_and_autopilot_or_a_post_on_its_way_waits(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import project_delete

    vid = _video("Rendering now", [])["id"]
    job = db.insert("studio_jobs", {"workspace_id": "local", "kind": "video_render", "target_id": vid, "revision": 1,
                                    "idempotency_key": f"video_render:{vid}:1", "status": "running"})
    queued = db.insert("studio_jobs", {"workspace_id": "local", "kind": "video_preview", "target_id": vid,
                                       "revision": 2, "idempotency_key": f"video_preview:{vid}:2"})
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["working"] == ("ClipForge is still working on it (rendering the finished video, making a preview). "
                               "Deleting stops that first.")
    monkeypatch.setattr(worker, "current", job["id"])  # the render is in the heavy-work thread right now
    with pytest.raises(project_delete.DeleteError) as stopping:
        project_delete.delete("local", vid, "full_video", wait=0.3)
    assert stopping.value.status == 409 and stopping.value.code == "stopping"
    assert db.fetch("studio_jobs", job["id"])["status"] == "canceled"  # asked to stop at its next safe point
    assert db.fetch("studio_jobs", queued["id"])["status"] == "canceled"
    assert db.fetch("studio_projects", vid)
    monkeypatch.setattr(worker, "current", None)  # it stopped
    assert project_delete.delete("local", vid, "full_video")["deleted"]

    p = db.create_project("Making clips", workspace_id="local", status="processing")
    monkeypatch.setattr(worker, "current", p["id"])
    assert "making its clips" in project_delete.plan("local", p["id"], "clips")["working"]
    with pytest.raises(project_delete.DeleteError):
        project_delete.delete("local", p["id"], "clips")
    assert p["id"] in worker.cancelled
    monkeypatch.setattr(worker, "current", None)
    project_delete.delete("local", p["id"], "clips")
    assert db.get_project(p["id"]) is None

    auto = db.create_project("From Autopilot", workspace_id="local", status="ready", origin="autopilot")
    db.insert("worker_jobs", {"kind": "render", "worker": "render", "status": "waiting", "ref_type": "project",
                              "ref_id": auto["id"]})
    plan = project_delete.plan("local", auto["id"], "clips")
    assert plan["blocked"].startswith("Autopilot is still working on this video")
    with pytest.raises(project_delete.DeleteError) as blocked:
        project_delete.delete("local", auto["id"], "clips")
    assert blocked.value.status == 409 and blocked.value.code == "blocked" and db.get_project(auto["id"])

    posting = db.create_project("Posting", workspace_id="local", status="ready")
    clip = db.create_clip(posting["id"], start=0, end=5, status="ready")
    post = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": "reconciling"})
    assert "being posted right now" in project_delete.plan("local", posting["id"], "clips")["blocked"]
    db.update("scheduled_publications", post["id"], status="published")
    db.insert("publications", {"clip_id": clip["id"], "project_id": posting["id"], "platform": "tiktok",
                               "status": "uploading"})
    assert "being posted right now" in project_delete.plan("local", posting["id"], "clips")["blocked"]


def test_a_video_still_being_copied_in_waits_but_a_copy_that_stopped_halfway_can_go(env):
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    p = db.create_project("Big upload", workspace_id="local", status="uploading")
    pdir = config.projects_dir() / p["id"]
    pdir.mkdir(parents=True)
    (pdir / "source.mp4").write_bytes(b"v" * 100)  # still being written
    assert project_delete.plan("local", p["id"], "clips")["blocked"].startswith(
        "ClipForge is still copying this video in")
    with pytest.raises(project_delete.DeleteError) as copying:
        project_delete.delete("local", p["id"], "clips")
    assert copying.value.code == "blocked" and (pdir / "source.mp4").is_file()
    old = time.time() - 600  # the app was closed in the middle: nothing has changed for ten minutes
    os.utime(pdir / "source.mp4", (old, old))
    os.utime(pdir, (old, old))
    assert project_delete.plan("local", p["id"], "clips")["blocked"] == ""
    project_delete.delete("local", p["id"], "clips")
    assert db.get_project(p["id"]) is None and not pdir.exists()


def test_a_draft_video_with_only_a_planning_chat_is_deleted(env):
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    draft = _video("Draft", [], status="draft")
    _chat("local", draft["id"], 3)
    plan = project_delete.plan("local", draft["id"], "full_video")
    assert plan["goes"] == ["The video project “Draft”.", "Its chat about it (3 messages)."]
    project_delete.delete("local", draft["id"], "full_video")
    assert db.fetch("studio_projects", draft["id"]) is None and not db.select("brain_chat_messages")


def test_another_workspace_and_an_unknown_kind_are_refused(env):
    from clipfoundry.studio import project_delete

    theirs = _video("Theirs", [], ws="ws-other")["id"]
    with pytest.raises(project_delete.DeleteError) as foreign:
        project_delete.plan("local", theirs, "full_video")
    assert foreign.value.status == 404
    with pytest.raises(project_delete.DeleteError) as kind:
        project_delete.delete("ws-other", theirs, "folder")
    assert kind.value.status == 422 and kind.value.code == "kind"


def test_routes_answer_with_the_plan_and_refuse_with_a_reason_and_code(env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.jobs import worker

    vid = _video("Route trip", [_stored(10)["id"]])["id"]
    p = db.create_project("Route clips", workspace_id="local", status="ready")
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        got = api.get(f"/api/studio/videos/{vid}/delete-plan")
        assert got.status_code == 200 and got.json()["counts"]["files"] == 1 and got.json()["blocked"] == ""
        assert api.get(f"/api/projects/{p['id']}/delete-plan").json()["name"] == "Route clips"
        assert api.get("/api/studio/videos/nope/delete-plan").status_code == 404
        monkeypatch.setattr(worker, "current", p["id"])
        monkeypatch.setattr("clipfoundry.studio.project_delete.WAIT_S", 0.2)
        busy = api.delete(f"/api/projects/{p['id']}", headers=H)
        assert busy.status_code == 409 and busy.json()["code"] == "stopping"
        monkeypatch.setattr(worker, "current", None)
        done = api.delete(f"/api/projects/{p['id']}", headers=H)
        assert done.status_code == 200 and done.json()["ok"] and done.json()["deleted"] is True
        assert api.get(f"/api/projects/{p['id']}").status_code == 404
        gone = api.delete(f"/api/studio/videos/{vid}", headers=H)
        assert gone.status_code == 200 and gone.json()["goes"][0] == "The video project “Route trip”."
        assert api.get(f"/api/studio/videos/{vid}").status_code == 404
        again = api.delete(f"/api/studio/videos/{vid}", headers=H)
        assert again.status_code == 404 and again.json()["code"] == "not_found"
        names = [i["name"] for i in api.get("/api/studio/projects").json()]
        assert "Route trip" not in names and "Route clips" not in names


def test_on_windows_read_only_copies_go_but_a_link_to_the_owners_own_file_is_never_changed(env, monkeypatch):
    """Windows refuses to delete a read-only file. An upload's copy (kept read-only) is made writable and deleted, a
    kept copy is read-only again afterwards, and a link to the owner's own read-only file is left as it is."""
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    real_unlink = os.unlink

    def windows_unlink(path, *args, dir_fd=None, **kw):
        st = os.lstat(path, dir_fd=dir_fd)
        if not stat.S_ISLNK(st.st_mode) and not st.st_mode & stat.S_IWRITE:
            raise PermissionError(13, "Access is denied", str(path))
        return real_unlink(path, *args, dir_fd=dir_fd, **kw)

    monkeypatch.setattr(os, "unlink", windows_unlink)
    own = env / "Videos" / "ClipForge" / "talk.mp4"  # Autopilot links the owner's file into its project folder
    own.parent.mkdir(parents=True)
    own.write_bytes(b"o" * 50)
    os.chmod(own, 0o444)
    auto = db.create_project("Talk", workspace_id="local", status="ready")
    adir = config.projects_dir() / auto["id"]
    adir.mkdir(parents=True)
    os.link(own, adir / "source.mp4")
    (adir / "transcript.json").write_text("{}")
    project_delete.delete("local", auto["id"], "clips")
    assert db.get_project(auto["id"]) is None and not (adir / "transcript.json").exists()
    assert own.is_file() and stat.S_IMODE(os.stat(own).st_mode) == 0o444  # never changed

    dropped = _stored(11)
    alone = db.create_project("Alone", workspace_id="local", status="ready", asset_id=dropped["id"])
    os.makedirs(config.projects_dir() / alone["id"])
    os.link(dropped["path"], config.projects_dir() / alone["id"] / "source.mp4")
    project_delete.delete("local", alone["id"], "clips")
    assert not (config.projects_dir() / alone["id"]).exists() and not os.path.exists(dropped["path"])

    kept = _stored(12)
    first, second = (db.create_project(n, workspace_id="local", status="ready", asset_id=kept["id"])
                     for n in ("First", "Second"))
    for p in (first, second):
        os.makedirs(config.projects_dir() / p["id"])
        os.link(kept["path"], config.projects_dir() / p["id"] / "source.mp4")
    project_delete.delete("local", first["id"], "clips")
    assert not (config.projects_dir() / first["id"]).exists()
    assert stat.S_IMODE(os.stat(kept["path"]).st_mode) == 0o440  # read-only again
    assert (config.projects_dir() / second["id"] / "source.mp4").is_file()
