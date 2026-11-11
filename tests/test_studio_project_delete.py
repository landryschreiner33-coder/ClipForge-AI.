"""Deleting a project (studio/project_delete.py): a full video and a clips project go with everything kept only for
them (history, renders, folders, the media nothing else uses, the chat and the memories of that project only, planned
posts that have not started), while the owner's own files, media another project or example uses, anything posted,
memories for every video and the taste ClipForge AI learned stay. The plan says exactly that before anything changes;
running work is stopped first (also work that was already asked to stop and the next step a stopped step queues);
Autopilot's work and a post on its way out are never interrupted; a draft with only a planning chat goes too; a memory
saved again for another project and a file added again since stay; files that are in use are deleted at the next
start; and the routes answer with the plan or a reason and its code, only to ClipForge's own page on this computer.
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


def _stored(n: int, ws: str = "local", size: int = 3000, kind: str = "video", filename: str = "") -> dict:
    """An upload ClipForge keeps: its read-only copy and what was made from it, in the asset's own folder."""
    from clipfoundry import db
    from clipfoundry.studio import uploads

    aid = f"as-{n:016x}"
    folder = uploads.assets_dir(ws) / aid
    folder.mkdir(parents=True)
    original = folder / ("original.png" if kind == "image" else "original.mp4")
    original.write_bytes(b"v" * size)
    os.chmod(original, 0o440)
    (folder / "transcript.json").write_text("{}")
    return db.insert("assets", {"id": aid, "workspace_id": ws, "kind": kind, "filename": filename or f"clip{n}.mp4",
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
                          "asset_id": only["id"], "created_at": 1.0, "updated_at": 1.0})  # before the video used it
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


def test_work_still_ending_after_a_stop_and_the_step_it_queues_next_are_stopped_before_anything_goes(env, monkeypatch):
    """A render that was asked to stop (its row says canceled) is still running until its next safe point: deleting
    again waits for it instead of deleting from under it. A step that ends while deleting waits may queue the next
    step; that one is stopped too, and only then does the project go."""
    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import project_delete

    vid = _video("Stopping", [])["id"]
    render = db.insert("studio_jobs", {"workspace_id": "local", "kind": "video_render", "target_id": vid,
                                       "revision": 1, "idempotency_key": f"video_render:{vid}:1",
                                       "status": "canceled"})
    monkeypatch.setattr(worker, "current", render["id"])  # canceled, but still inside the render
    assert "rendering the finished video" in project_delete.plan("local", vid, "full_video")["working"]
    with pytest.raises(project_delete.DeleteError) as stopping:
        project_delete.delete("local", vid, "full_video", wait=0.3)
    assert stopping.value.code == "stopping" and db.fetch("studio_projects", vid)

    real_sleep = time.sleep
    queued: list[dict] = []

    def render_ends_and_queues_a_preview(seconds):
        if not queued:
            monkeypatch.setattr(worker, "current", None)
            queued.append(db.insert("studio_jobs", {"workspace_id": "local", "kind": "video_preview", "target_id": vid,
                                                    "revision": 2, "idempotency_key": f"video_preview:{vid}:2"}))
        real_sleep(min(seconds, 0.01))

    monkeypatch.setattr(worker, "current", render["id"])
    monkeypatch.setattr(project_delete.time, "sleep", render_ends_and_queues_a_preview)
    out = project_delete.delete("local", vid, "full_video", wait=5)
    assert out["deleted"] and db.fetch("studio_projects", vid) is None
    assert db.fetch("studio_jobs", queued[0]["id"])["status"] == "canceled"


def test_a_post_that_starts_uploading_while_deleting_stops_the_delete(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler
    from clipfoundry.studio import project_delete

    p = db.create_project("Almost posted", workspace_id="local", status="ready")
    clip = db.create_clip(p["id"], start=0, end=5, status="ready")
    post = db.insert("scheduled_publications", {"clip_id": clip["id"], "platform": "youtube", "status": "approved",
                                                "planned_at": 2e9})
    # its publish step already started (Autopilot runs it): canceling the post would not stop the upload
    job = db.insert("worker_jobs", {"kind": "publish", "worker": "publish", "status": "running",
                                    "ref_type": "scheduled", "ref_id": post["id"]})
    assert "being posted right now" in project_delete.plan("local", p["id"], "clips")["blocked"]
    db.update("worker_jobs", job["id"], status="done")
    assert project_delete.plan("local", p["id"], "clips")["blocked"] == ""

    def started_uploading(post_id, note):
        db.update("scheduled_publications", post_id, status="publishing")
        raise ValueError("This post is already being published (or may already be live): check it first")

    monkeypatch.setattr(scheduler, "cancel", started_uploading)  # it started between the check and the cancel
    with pytest.raises(project_delete.DeleteError) as posting:
        project_delete.delete("local", p["id"], "clips")
    assert posting.value.code == "blocked" and "being posted right now" in str(posting.value)
    assert db.get_project(p["id"]) and db.fetch("clips", clip["id"])


def test_a_memory_saved_again_for_another_project_stays(env):
    """A memory saved again for another project is that project's now (its scope, and its project_id, which
    follows the scope since ClipForge AI's review fixes; a memory saved by an older version may still name the first
    project there), so only the scope decides what goes."""
    from clipfoundry import db
    from clipfoundry.brain import memories
    from clipfoundry.studio import project_delete

    first, second = _video("First", [])["id"], _video("Second", [])["id"]
    moved = memories.remember("local", "Open on the drone shot", kind="rule", project_id=first)
    memories.remember("local", "Open on the drone shot", kind="rule", project_id=second)
    moved = db.fetch("brain_memories", moved["id"])
    assert moved["scope"] == f"project:{second}" and moved["project_id"] == second
    db.update("brain_memories", moved["id"], project_id=first)  # as an older version kept it
    only_first = memories.remember("local", "Use the blue title card", kind="rule", project_id=first)
    assert project_delete.plan("local", first, "full_video")["counts"]["memories"] == 1
    project_delete.delete("local", first, "full_video")
    assert db.fetch("brain_memories", moved["id"]) and db.fetch("brain_memories", only_first["id"]) is None


def test_a_file_added_again_after_the_project_was_made_stays_while_it_is_new(env):
    """ClipForge keeps one copy per file: uploading the same file again (for a new video that has not saved it yet)
    gives the same copy, so it stays when the old project is deleted. What the window said holds even when the
    project changes before the delete (deleting stops its work first, which changes it). A second upload more than
    a day old protects nothing: no page is waiting for it any more."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    asset = _stored(13)
    db.insert("uploads", {"workspace_id": "local", "filename": "clip13.mp4", "size": 3000, "status": "complete",
                          "asset_id": asset["id"], "created_at": 1.0, "updated_at": 1.0})
    vid = _video("Old cut", [asset["id"]])["id"]
    assert project_delete.plan("local", vid, "full_video")["counts"]["files"] == 1
    db.insert("uploads", {"workspace_id": "local", "filename": "clip13.mp4", "size": 3000, "status": "complete",
                          "asset_id": asset["id"]})  # added again just now
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 1
    assert "“clip13.mp4” stays in ClipForge because you added it again since." in plan["stays"]
    time.sleep(0.01)
    db.update("studio_projects", vid, status="ready", message="Canceled")  # its work was stopped: it changed
    assert project_delete.plan("local", vid, "full_video")["counts"]["files_kept"] == 1
    out = project_delete.delete("local", vid, "full_video")
    assert "“clip13.mp4” stays in ClipForge because you added it again since." in out["stays"]
    assert db.fetch("assets", asset["id"]) and os.path.isfile(asset["path"])
    assert stat.S_IMODE(os.stat(asset["path"]).st_mode) == 0o440

    old = _stored(16)
    days = time.time() - 86400
    with db.connect() as conn:  # stored three days ago, by its own upload
        conn.execute("UPDATE assets SET created_at = ? WHERE id = ?", (days - 2 * 86400 + 1, old["id"]))
    for when in (days - 2 * 86400, days - 86400):  # its own upload, then once more two days ago
        db.insert("uploads", {"workspace_id": "local", "filename": "clip16.mp4", "size": 3000, "status": "complete",
                              "asset_id": old["id"], "created_at": when, "updated_at": when})
    long_ago = _video("Older cut", [old["id"]], created_at=days - 3 * 86400)["id"]
    assert project_delete.plan("local", long_ago, "full_video")["counts"]["files"] == 1
    project_delete.delete("local", long_ago, "full_video")
    assert db.fetch("assets", old["id"]) is None and not os.path.exists(old["path"])


def test_a_clips_projects_own_recording_or_download_is_named_in_what_goes(env):
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    live = db.create_project("Friday stream", workspace_id="local", status="ready", origin="live",
                             source_filename="friday.mp4")
    ldir = config.projects_dir() / live["id"]
    ldir.mkdir(parents=True)
    (ldir / "source.mp4").write_bytes(b"s" * 2000)
    db.update_project(live["id"], source_path=str(ldir / "source.mp4"))
    plan = project_delete.plan("local", live["id"], "clips")
    assert "The recording of the live stream (“friday.mp4”). ClipForge has the only copy." in plan["goes"]
    assert plan["counts"]["files"] == 1 and plan["freed_bytes"] == 2000

    link = db.create_project("From a link", workspace_id="local", status="ready", source_filename="talk.mp4",
                             source_url="https://example.com/talk")
    kdir = config.projects_dir() / link["id"]
    kdir.mkdir(parents=True)
    (kdir / "source.mp4").write_bytes(b"d" * 100)
    db.update_project(link["id"], source_path=str(kdir / "source.mp4"))
    assert "ClipForge's copy of the video it was made from (“talk.mp4”)." in \
        project_delete.plan("local", link["id"], "clips")["goes"]
    project_delete.delete("local", live["id"], "clips")
    assert not ldir.exists()


def test_files_in_use_are_deleted_at_the_next_start(env, monkeypatch):
    """On Windows a file open in another program (a finished video in a player) cannot be deleted. The project still
    goes, the answer says some files were left for now, and the next start deletes them. Only ClipForge's own
    folders that a delete listed are ever touched there."""
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    vid = _video("Playing now", [])["id"]
    final = config.data_dir() / "videos" / vid / "r1" / "final.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"f" * 300)
    real_unlink = os.unlink

    def open_in_a_player(path, *args, **kw):
        if os.path.basename(path) == "final.mp4":
            raise PermissionError(13, "The file is being used by another process", str(path))
        return real_unlink(path, *args, **kw)

    monkeypatch.setattr(os, "unlink", open_in_a_player)
    out = project_delete.delete("local", vid, "full_video")
    assert out["deleted"] and out["left_behind"] is True and db.fetch("studio_projects", vid) is None
    assert final.is_file()
    later = config.data_dir() / "delete-later.json"
    assert json.loads(later.read_text()) == [str(config.data_dir() / "videos" / vid)]

    own = env / "My Videos"  # never touched, even if the list names it
    own.mkdir()
    (own / "keep.mp4").write_bytes(b"k")
    kept = _stored(14)  # nor ClipForge's other folders
    listed = json.loads(later.read_text()) + [str(own), str(config.data_dir() / "assets"), str(config.data_dir())]
    later.write_text(json.dumps(listed))
    assert project_delete.finish_later() == 0  # still open
    assert final.is_file() and json.loads(later.read_text()) == [str(config.data_dir() / "videos" / vid)]
    monkeypatch.setattr(os, "unlink", real_unlink)  # the player was closed
    assert project_delete.finish_later() == 1
    assert not (config.data_dir() / "videos" / vid).exists() and not later.exists()
    assert (own / "keep.mp4").is_file() and os.path.isfile(kept["path"])
    assert project_delete.finish_later() == 0


def test_deleting_only_answers_clipforges_own_page_on_this_computer(env):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    vid = _video("Guarded", [])["id"]
    p = db.create_project("Guarded clips", workspace_id="local", status="ready")
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        for url in (f"/api/studio/videos/{vid}", f"/api/projects/{p['id']}"):
            assert api.delete(url).status_code == 403  # without the page's header
    with TestClient(app, base_url="http://192.168.1.20:8765") as api:  # from another device on the network
        refused = api.delete(f"/api/studio/videos/{vid}", headers=H)
        assert refused.status_code == 403 and "on the computer that runs it" in refused.json()["detail"]
    assert db.fetch("studio_projects", vid) and db.get_project(p["id"])


def test_a_reused_render_open_in_a_player_is_counted_once_and_deleted_at_the_next_start(env, monkeypatch):
    """A render reused for a later revision (after undo or restore) is one file with two links in the video's
    folder: the space it frees is counted once, and when it is open in a player it is listed for the next start
    like any other file in use (it is ClipForge's, not the owner's)."""
    from clipfoundry import config
    from clipfoundry.studio import project_delete

    vid = _video("Undone and redone", [])["id"]
    first = config.data_dir() / "videos" / vid / "r1" / "final.mp4"
    again = config.data_dir() / "videos" / vid / "r3" / "final.mp4"
    first.parent.mkdir(parents=True)
    again.parent.mkdir(parents=True)
    first.write_bytes(b"f" * 700)
    os.link(first, again)
    assert project_delete.plan("local", vid, "full_video")["freed_bytes"] == 700
    real_unlink = os.unlink

    def open_in_a_player(path, *args, **kw):
        if os.path.basename(path) == "final.mp4":
            raise PermissionError(32, "The file is being used by another process", str(path))
        return real_unlink(path, *args, **kw)

    monkeypatch.setattr(os, "unlink", open_in_a_player)
    out = project_delete.delete("local", vid, "full_video")
    assert out["left_behind"] is True and first.is_file() and again.is_file()
    monkeypatch.setattr(os, "unlink", real_unlink)
    assert project_delete.finish_later() == 1
    assert not (config.data_dir() / "videos" / vid).exists()


def test_a_link_to_a_kept_copy_left_by_a_delete_goes_at_the_next_start_and_the_copy_stays_read_only(
        env, monkeypatch):
    """Two clips projects made from one upload each link ClipForge's read-only copy. One is deleted while the other
    is rendering from that file (on Windows the file is then in use under every name), so its link stays for now.
    At the next start the link goes, even though the copy is read-only again (Windows refuses to delete a read-only
    file), and the copy the other project uses stays, read-only."""
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    kept = _stored(17)
    first, second = (db.create_project(n, workspace_id="local", status="ready", asset_id=kept["id"])
                     for n in ("Highlights", "Full stories"))
    for p in (first, second):
        os.makedirs(config.projects_dir() / p["id"])
        os.link(kept["path"], config.projects_dir() / p["id"] / "source.mp4")
    link = config.projects_dir() / first["id"] / "source.mp4"
    real_unlink = os.unlink

    def windows_unlink(path, *args, dir_fd=None, **kw):
        st = os.lstat(path, dir_fd=dir_fd)
        if not stat.S_ISLNK(st.st_mode) and not st.st_mode & stat.S_IWRITE:
            raise PermissionError(13, "Access is denied", str(path))
        return real_unlink(path, *args, dir_fd=dir_fd, **kw)

    def rendering_from_it(path, *args, **kw):
        if os.path.basename(path) == "source.mp4":
            raise PermissionError(32, "The file is being used by another process", str(path))
        return windows_unlink(path, *args, **kw)

    monkeypatch.setattr(os, "unlink", rendering_from_it)
    out = project_delete.delete("local", first["id"], "clips")
    assert out["left_behind"] is True and link.is_file()
    assert stat.S_IMODE(os.stat(kept["path"]).st_mode) == 0o440
    monkeypatch.setattr(os, "unlink", windows_unlink)  # the render ended; the copy is read-only again
    assert project_delete.finish_later() == 1
    assert not (config.projects_dir() / first["id"]).exists()
    assert db.fetch("assets", kept["id"]) and os.stat(kept["path"]).st_nlink == 2  # the copy and the other link
    assert stat.S_IMODE(os.stat(kept["path"]).st_mode) == 0o440
    assert not (config.data_dir() / "delete-later.json").exists()


def test_an_animated_shorts_scene_files_go_with_it_but_files_another_short_or_your_media_uses_stay(env):
    """An animated short names its scene files in its scenes (each scene's picture, its earlier pictures and the
    scene's clip, which is in the plan only once the scene is placed): they go with the short when nothing else uses
    them. A picture another short's scene uses, and a file imported for no project, stay. The short's build is
    stopped first and named in the window."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    picture, earlier = (_stored(n, kind="image", filename="Scene 1 picture.png") for n in (31, 32))
    placed, unplaced = _stored(33, filename="Scene 1.mp4"), _stored(34, filename="Scene 2.mp4")
    shared, imported = (_stored(n, kind="image") for n in (35, 36))
    short = _video("Shark facts", [], workflow="animated_short", short={"topic": "sharks"})["id"]
    other = _video("Owl facts", [], workflow="animated_short")["id"]
    db.insert("edit_plans", {"project_id": short, "revision": 1, "plan": {"clips": [{"asset_id": placed["id"]}]}},
              key="project_id")

    def scene(project_id: str, n: int, **files) -> None:
        db.insert("short_scenes", {"project_id": project_id, "workspace_id": "local", "position": n,
                                   "narration": f"Scene {n}", **files})

    scene(short, 1, picture_asset_id=picture["id"], clip_asset_id=placed["id"],
          pictures=[{"asset_id": earlier["id"], "prompt": "a shark, drawn as-is", "seed": 7}])
    scene(short, 2, picture_asset_id=shared["id"], clip_asset_id=unplaced["id"])
    scene(short, 3, picture_asset_id=imported["id"])
    scene(other, 1, picture_asset_id=shared["id"])
    db.insert("media_imports", {"workspace_id": "local", "project_id": "", "provider": "openverse", "kind": "image",
                                "external_id": "x1", "status": "ready", "asset_id": imported["id"]})
    build = db.insert("studio_jobs", {"workspace_id": "local", "kind": "short_build", "target_id": short,
                                      "revision": 1, "idempotency_key": f"short_build:{short}:1"})

    plan = project_delete.plan("local", short, "full_video")
    assert plan["working"] == "ClipForge is still working on it (making the short). Deleting stops that first."
    assert plan["counts"]["files"] == 4 and plan["counts"]["files_kept"] == 2
    assert "What ClipForge made for its scenes: 2 pictures and 2 clips." in plan["goes"]
    assert any("“clip35.mp4”, “clip36.mp4” stay in ClipForge because another project" in line
               for line in plan["stays"])
    out = project_delete.delete("local", short, "full_video")
    assert out["deleted"] and db.fetch("studio_jobs", build["id"])["status"] == "canceled"
    for gone in (picture, earlier, placed, unplaced):
        assert db.fetch("assets", gone["id"]) is None and not os.path.exists(gone["path"])
    for kept in (shared, imported):
        assert db.fetch("assets", kept["id"]) and os.path.isfile(kept["path"])
    assert not db.select("short_scenes", "project_id = ?", (short,))
    assert len(db.select("short_scenes", "project_id = ?", (other,))) == 1


def test_one_upload_of_a_file_clipforge_got_another_way_is_added_again_but_the_upload_that_stored_it_is_not(env):
    """A file ClipForge got itself (Find media, a link, a short's build) has no upload of its own, so one upload of
    the same bytes for a new page is the owner adding it again, and it stays. The upload that first stored a file is
    the project's own, also when the project was made before it (a planned video's files arrive after it)."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    found = _stored(41)
    with db.connect() as conn:  # Find media brought it in an hour ago
        conn.execute("UPDATE assets SET created_at = ? WHERE id = ?", (time.time() - 3600, found["id"]))
    vid = _video("Bridge video", [found["id"]], created_at=time.time() - 3500)["id"]
    assert project_delete.plan("local", vid, "full_video")["counts"]["files"] == 1
    db.insert("uploads", {"workspace_id": "local", "filename": "bridge.jpg", "size": 3000, "status": "complete",
                          "asset_id": found["id"]})  # the owner uploads the same file for a new video
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 1
    assert "“clip41.mp4” stays in ClipForge because you added it again since." in plan["stays"]

    own = _stored(42)
    db.insert("uploads", {"workspace_id": "local", "filename": "clip42.mp4", "size": 3000, "status": "complete",
                          "asset_id": own["id"], "created_at": own["created_at"] - 5})  # the upload that stored it,
    # started before ClipForge had the file and finished after the planned video was made
    planned = _video("Planned video", [own["id"]], status="draft", created_at=time.time() - 60)["id"]
    assert project_delete.plan("local", planned, "full_video")["counts"]["files"] == 1
    project_delete.delete("local", planned, "full_video")
    assert db.fetch("assets", own["id"]) is None and not os.path.exists(own["path"])


def test_the_window_counts_the_files_it_does_not_name(env):
    from clipfoundry.studio import project_delete

    files = [{"filename": f"take{n}.mp4"} for n in range(1, 6)]
    assert project_delete._names(files) == "“take1.mp4”, “take2.mp4”, “take3.mp4” and 2 more"
    assert project_delete._names(files[:4]) == "“take1.mp4”, “take2.mp4”, “take3.mp4” and 1 more"


def test_a_shorts_window_counts_what_clipforge_made_for_its_scenes_and_names_a_picture_you_chose(env):
    """The pictures and clips ClipForge made for a short's scenes are not copies of anything (ClipForge has the only
    one), and every remake of a picture has the same name, so the window counts them instead of naming them. A
    picture the owner chose for a scene is ClipForge's copy of their file. The pictures and voices the makers on this
    computer made keep their originals in their own folder, and the window says so under what stays."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    pics = [_stored(n, kind="image", filename="Scene 1 picture.png") for n in (51, 52, 53)]  # made three times
    clip1, clip2, old_clip = (_stored(n, filename=f"Scene {k}.mp4") for n, k in ((54, 1), (55, 2), (58, 2)))
    owl = _stored(56, kind="image", filename="my owl photo.png")
    short = _video("Owl facts", [], workflow="animated_short")["id"]
    db.insert("edit_plans", {"project_id": short, "revision": 1, "plan": {"clips": [
        {"asset_id": old_clip["id"], "scene_id": "sc-gone"}]}}, key="project_id")  # a scene deleted since
    db.insert("short_scenes", {"project_id": short, "workspace_id": "local", "position": 1, "narration": "Owls",
                               "picture_asset_id": pics[2]["id"], "clip_asset_id": clip1["id"],
                               "pictures": [{"asset_id": p["id"], "source": "engine"} for p in pics],
                               "info": {"picture": {"source": "engine"}, "voice": {"engine": "engine"},
                                        "motion": {"how": "camera"}}})
    db.insert("short_scenes", {"project_id": short, "workspace_id": "local", "position": 2, "narration": "Eyes",
                               "picture_asset_id": owl["id"], "picture_source": "upload", "clip_asset_id": clip2["id"],
                               "pictures": [{"asset_id": owl["id"], "source": "upload"}],
                               "info": {"picture": {"source": "upload"}, "voice": {"engine": "say"}}})
    plan = project_delete.plan("local", short, "full_video")
    assert plan["counts"]["files"] == 7 and plan["counts"]["files_kept"] == 0
    assert "What ClipForge made for its scenes: 3 pictures and 3 clips." in plan["goes"]
    assert "ClipForge's copy of “my owl photo.png”, which no other project uses." in plan["goes"]
    assert not any("Scene" in line for line in plan["goes"])
    assert ("The originals of the pictures and voices made for it on this computer stay in engines/made, each with a "
            "note of the words it was made from.") in plan["stays"]
    plain = _video("Plain video", [_stored(57)["id"]])["id"]
    assert not any("engines/made" in line for line in project_delete.plan("local", plain, "full_video")["stays"])
    out = project_delete.delete("local", short, "full_video")
    assert out["goes"] == plan["goes"]
    for gone in (*pics, clip1, clip2, old_clip, owl):
        assert db.fetch("assets", gone["id"]) is None and not os.path.exists(gone["path"])


def test_an_upload_that_started_before_the_file_was_stored_is_the_projects_own_even_when_saving_was_slow(env):
    """Whether an upload added a file again is decided by when it started, not by a guess at how long saving takes:
    the upload that stored the file, and the same file dropped twice at once, started before ClipForge had the file,
    so they are the project's own also when the database was busy for a while and they finished late."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    asset = _stored(43, kind="image", filename="green.png")
    stored = float(asset["created_at"])
    for started, done in ((stored - 30, stored + 8), (stored - 29, stored + 8.04)):  # one drop, a slow save
        db.insert("uploads", {"workspace_id": "local", "filename": "green.png", "size": 3000, "status": "complete",
                              "asset_id": asset["id"], "created_at": started, "updated_at": done})
    draft = _video("Draft", [asset["id"]], status="draft", created_at=stored - 40)["id"]
    plan = project_delete.plan("local", draft, "full_video")
    assert plan["counts"]["files"] == 1 and plan["counts"]["files_kept"] == 0
    project_delete.delete("local", draft, "full_video")
    assert db.fetch("assets", asset["id"]) is None and not os.path.exists(asset["path"])


def test_a_file_the_window_said_stays_still_stays_when_delete_is_pressed_a_while_later(env, monkeypatch):
    """The window is judged once, when it opens, and the page sends that moment back with Delete: a file it said
    stays (the owner added it again almost a day ago) is not deleted because the window stayed open past the day."""
    import types

    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.studio import project_delete

    asset = _stored(44, filename="talk.mp4")
    now = time.time()
    with db.connect() as conn:  # stored two days ago for the video
        conn.execute("UPDATE assets SET created_at = ? WHERE id = ?", (now - 2 * 86400, asset["id"]))
    vid = _video("Talk", [asset["id"]], created_at=now - 2 * 86400 + 60)["id"]
    db.insert("uploads", {"workspace_id": "local", "filename": "talk.mp4", "size": 3000, "status": "complete",
                          "asset_id": asset["id"], "created_at": now - 86400 + 30, "updated_at": now - 86400 + 40})
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        plan = api.get(f"/api/studio/videos/{vid}/delete-plan").json()
        assert plan["counts"]["files_kept"] == 1 and now <= plan["as_of"] <= time.time()
        assert "“talk.mp4” stays in ClipForge because you added it again since." in plan["stays"]
        later = time.time() + 120  # the window stayed open: by now that upload is more than a day old
        monkeypatch.setattr(project_delete, "time", types.SimpleNamespace(
            time=lambda: later, monotonic=time.monotonic, sleep=time.sleep))
        assert project_delete.plan("local", vid, "full_video")["counts"]["files_kept"] == 0  # a window opened now
        done = api.delete(f"/api/studio/videos/{vid}?as_of={plan['as_of']}", headers=H)
    assert done.status_code == 200 and done.json()["deleted"] and done.json()["counts"]["files_kept"] == 1
    assert db.fetch("assets", asset["id"]) and os.path.isfile(asset["path"])


def test_a_shorts_window_reads_its_saved_versions_and_a_picture_waiting_to_be_replaced(env):
    """A short's saved versions keep each scene as it was (also a scene deleted since), so its picture and clip are
    counted as made there too. The owner's own picture stays theirs while a new picture waits to replace it. The
    makers' work is found wherever the short recorded it: a saved version (the voice or motion was switched since,
    or the scene was deleted) or a voice note from a build stopped before any clip was made."""
    from clipfoundry import config, db
    from clipfoundry.studio import project_delete

    pic1, pic2 = (_stored(n, kind="image", filename=f"Scene {k} picture.png") for n, k in ((61, 1), (62, 2)))
    clip1, clip2 = (_stored(n, filename=f"Scene {k}.mp4") for n, k in ((63, 1), (64, 2)))
    owl = _stored(65, kind="image", filename="my owl photo.png")
    short = _video("Bees", [], workflow="animated_short")["id"]
    rows = {"sc-1": {"picture_asset_id": pic1["id"], "clip_asset_id": clip1["id"], "picture_source": "auto",
                     "info": {"picture": {"source": "card"}, "voice": {"engine": "engine"}, "motion": {"how": "camera"}}},
            "sc-2": {"picture_asset_id": pic2["id"], "clip_asset_id": clip2["id"], "picture_source": "auto",
                     "info": {"picture": {"source": "engine"}, "voice": {"engine": "say"}, "motion": {"how": "engine"}}}}
    db.insert("edit_plans", {"project_id": short, "revision": 1, "plan": {
        "clips": [{"asset_id": clip1["id"], "scene_id": "sc-1"}], "short": {"rows": rows}}}, key="project_id")
    # scene 2 was deleted since; scene 1 now shows the owner's photo, a new picture waits, the voice was switched
    db.insert("short_scenes", {"id": "sc-1", "project_id": short, "workspace_id": "local", "position": 1,
                               "narration": "Bees dance", "picture_asset_id": owl["id"], "picture_source": "auto",
                               "clip_asset_id": clip1["id"],
                               "pictures": [{"asset_id": pic1["id"], "source": "card"},
                                            {"asset_id": owl["id"], "source": "upload"}],
                               "info": {"picture": {"source": "upload"}, "voice": {"engine": "espeak"},
                                        "motion": {"how": "camera"}}})
    plan = project_delete.plan("local", short, "full_video")
    assert plan["counts"]["files"] == 5
    assert "What ClipForge made for its scenes: 2 pictures and 2 clips." in plan["goes"]
    assert "ClipForge's copy of “my owl photo.png”, which no other project uses." in plan["goes"]
    assert not any("Scene" in line for line in plan["goes"])
    assert ("The originals of the pictures, video clips and voices made for it on this computer stay in "
            "engines/made, each with a note of the words it was made from.") in plan["stays"]

    stopped = _video("Stopped short", [], workflow="animated_short")["id"]
    db.insert("short_scenes", {"project_id": stopped, "workspace_id": "local", "position": 1, "narration": "Ants"})
    notes = config.data_dir() / "videos" / stopped / "short" / "voice"
    notes.mkdir(parents=True)
    (notes / "k1.json").write_text(json.dumps({"engine": "engine", "voice": "F1"}))
    (notes / "k0.json").write_text("not json")
    assert ("The originals of the voices made for it on this computer stay in engines/made, each with a note of the "
            "words it was made from.") in project_delete.plan("local", stopped, "full_video")["stays"]
    (notes / "k1.json").write_text(json.dumps({"engine": "say", "voice": "Samantha"}))
    assert not any("engines/made" in line for line in project_delete.plan("local", stopped, "full_video")["stays"])


def test_another_pages_upload_of_the_same_file_keeps_it_even_when_it_finished_before_or_after_the_project(env):
    """A page makes a project only from finished uploads, so an upload that started before the project was made and
    finished after it is another page's (the same file under another name, sent at the same time). And two drops of
    a file in the last day mean another page may hold it: the project was made from one of them at most. Either way
    the file stays. One drop (the uploads that started before ClipForge had the file count as one) still goes."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    def upload(asset: dict, started: float, done: float) -> None:
        db.insert("uploads", {"workspace_id": "local", "filename": asset["filename"], "size": 3000,
                              "status": "complete", "asset_id": asset["id"], "created_at": started,
                              "updated_at": done})

    late = _stored(71, filename="talk.mp4")
    t = float(late["created_at"])
    upload(late, t - 5, t)          # "talk (1).mp4" on this page: stored the file
    upload(late, t - 10, t + 20)    # "talk.mp4" on another page: started first, finished after the video was made
    vid = _video("Talk", [late["id"]], created_at=t + 5)["id"]
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 1
    assert "“talk.mp4” stays in ClipForge because you added it again since." in plan["stays"]

    twice = _stored(72, filename="lake.mp4")
    t = float(twice["created_at"])
    upload(twice, t - 5, t)         # dropped on Make clips (stored it), that page is still open
    upload(twice, t + 10, t + 20)   # dropped again on Make a YouTube video, which made the video
    vid2 = _video("Lake", [twice["id"]], created_at=t + 30)["id"]
    assert project_delete.plan("local", vid2, "full_video")["counts"]["files_kept"] == 1

    once = _stored(73, filename="once.mp4")
    t = float(once["created_at"])
    upload(once, t - 5, t)          # the same file twice in one drop: both started before ClipForge had it
    upload(once, t - 4, t + 0.5)
    vid3 = _video("Once", [once["id"]], created_at=t + 30)["id"]
    assert project_delete.plan("local", vid3, "full_video")["counts"]["files"] == 1


def test_a_video_being_planned_goes_with_its_planning_chat_and_an_answer_written_after_changes_nothing(env,
                                                                                                    monkeypatch):
    """A draft made on Make a YouTube video (studio/video_setup.py) is a full video with status "draft" and a plan
    being made in its own chat. Deleting it stops the reading of its files and removes the chat with ClipForge AI's
    answer still being written; that answer, when it finishes after the delete, makes no chat or message again."""
    from clipfoundry import config, db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import project_delete, video_setup

    later = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: None)  # the heavy-work thread is busy elsewhere
    monkeypatch.setattr(video_setup, "model_ready", lambda settings: True)
    monkeypatch.setattr(video_setup, "limit_reached", lambda ws, settings: "")
    monkeypatch.setattr(video_setup._pool, "submit", lambda fn, *a: later.append((fn, a)))  # written in the background
    monkeypatch.setattr(video_setup, "ask_model", lambda *a, **k: pytest.fail("no answer is asked for a deleted video"))
    trip = _stored(81, filename="trip.mp4")
    draft = video_setup.start("local", "owner", asset_ids=[trip["id"]], idea="A fun trip video", mode="ask")
    vid = draft["id"]
    assert video_setup.is_draft(db.fetch("studio_projects", vid)) and len(later) == 1
    chat = db.select("brain_chats", "project_id = ?", (vid,))[0]
    assert {r["status"] for r in db.select("brain_chat_messages", "chat_id = ?", (chat["id"],))} == {"done",
                                                                                                   "thinking"}

    plan = project_delete.plan("local", vid, "full_video")
    assert plan["working"] == ("ClipForge is still working on it (reading the files added to it). Deleting stops that "
                               "first.")
    assert "Its chat about it (2 messages)." in plan["goes"]
    assert "ClipForge's copy of “trip.mp4”, which no other project uses." in plan["goes"]
    out = project_delete.delete("local", vid, "full_video")
    assert out["deleted"] and db.fetch("studio_projects", vid) is None
    assert all(j["status"] != "queued" for j in db.select("studio_jobs", "target_id = ?", (vid,)))
    assert not db.select("brain_chats", "project_id = ?", (vid,)) and not db.select("brain_chat_messages")
    assert not (config.data_dir() / "videos" / vid).exists()

    fn, args = later[0]
    fn(*args)  # the answer finishes after the delete
    assert not db.select("brain_chats", "project_id = ?", (vid,)) and not db.select("brain_chat_messages")
