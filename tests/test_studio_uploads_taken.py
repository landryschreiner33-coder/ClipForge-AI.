"""A file the owner uploads for a project is that project's own, also when ClipForge already had the same bytes.

Deleting a project keeps a file the owner "added again" in the last day, because a page may be about to use it
(project_delete._added_again). ClipForge keeps one copy per file, so an upload of bytes it already had gives the same
copy. Each page sends the uploads it makes a project from, or adds to one, with their files (`upload_ids`), and only
those uploads become that project's (uploads.taken). Deleting a project counts only uploads no project took: when the
project took its own uploads, every other one in the day is another page's. So a project's own later upload of a file
ClipForge already had no longer keeps that file forever (a video's files, music and voice-over, a file added to a
video's bin, also one it has already, a clips project's video), and another page's upload is never taken by a project
that did not get it. The same picture chosen for two scenes of a short, and an earlier picture chosen again, are in
tests/test_studio_shorts_tidy.py; a copy handed to an upload while the project is deleted is at the end.
"""
from __future__ import annotations

import os
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
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: None)
    monkeypatch.setattr(worker, "submit_project", lambda project_id, url=None: None)
    return tmp_path


def _had(n: int, kind: str = "video", filename: str = "") -> dict:
    """A file ClipForge got an hour ago (an earlier upload, Find media, a link): its read-only copy in its folder."""
    from clipfoundry import db
    from clipfoundry.studio import uploads

    ext = {"video": ".mp4", "image": ".png", "audio": ".m4a"}[kind]
    aid = f"as-{n:016x}"
    folder = uploads.assets_dir("local") / aid
    folder.mkdir(parents=True)
    original = folder / f"original{ext}"
    original.write_bytes(b"v" * 3000)
    os.chmod(original, 0o440)
    db.insert("assets", {"id": aid, "workspace_id": "local", "kind": kind, "sha256": f"{n:064x}",
                         "filename": filename or f"file{n}{ext}", "size": 3000, "path": str(original),
                         "probe": {"duration": 0 if kind == "image" else 8.0, "has_audio": kind != "image"}})
    with db.connect() as conn:
        conn.execute("UPDATE assets SET created_at = ? WHERE id = ?", (time.time() - 3600, aid))
    return db.fetch("assets", aid)


def _uploaded(asset: dict) -> dict:
    """The owner uploads the same bytes again now: ClipForge gives them the copy it has."""
    from clipfoundry import db

    return db.insert("uploads", {"workspace_id": "local", "filename": asset["filename"], "size": 3000,
                                 "status": "complete", "asset_id": asset["id"]})


def _again(lines: list[str]) -> bool:
    return any("because you added" in line for line in lines)


def _taken(*rows: dict) -> list[str]:
    from clipfoundry import db

    return [db.fetch("uploads", r["id"])["taken"] for r in rows]


def test_two_videos_made_from_the_same_uploads_both_let_them_go(env):
    """The owner makes a video from a clip, a picture, music and a voice-over, then uploads the same files again
    and makes a second video with them (ClipForge gives them the copies it has). Deleted newest first, the files
    stay while the older video uses them and go with it: the second uploads were the newer video's own, not files
    added again. An upload no project took yet (the same clip, uploaded once more for a page not saved yet) still
    keeps its file."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, video_flow

    clip, pic, music, voice = _had(1), _had(2, "image"), _had(3, "audio"), _had(4, "audio")

    def video(name: str) -> str:
        sent = [_uploaded(a)["id"] for a in (clip, pic, music, voice)]
        return video_flow.create("local", "local", name=name, asset_ids=[clip["id"], pic["id"]],
                                 brief={"music": "supplied", "music_asset_id": music["id"],
                                        "voiceover_asset_ids": [voice["id"]]},
                                 style_id="settings", remember={"enabled": False}, upload_ids=sent)["id"]

    first = video("Hike")
    time.sleep(0.01)
    second = video("Hike, shorter")
    assert sorted(r["taken"] for r in db.select("uploads", "1 = 1")) == sorted([first] * 4 + [second] * 4)
    plan = project_delete.plan("local", second, "full_video")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 4 and not _again(plan["stays"])
    project_delete.delete("local", second, "full_video")
    plan = project_delete.plan("local", first, "full_video")
    assert plan["counts"]["files"] == 4 and plan["counts"]["files_kept"] == 0 and not _again(plan["stays"])

    later = _uploaded(clip)  # the owner drops the clip on a new page that is not saved yet
    plan = project_delete.plan("local", first, "full_video")
    assert plan["counts"]["files"] == 3 and plan["counts"]["files_kept"] == 1
    assert f"“{clip['filename']}” stays in ClipForge because you added it again since." in plan["stays"]
    project_delete.delete("local", first, "full_video")
    assert db.fetch("uploads", later["id"])["taken"] == ""
    assert db.fetch("assets", clip["id"]) and os.path.isfile(clip["path"])
    for gone in (pic, music, voice):
        assert db.fetch("assets", gone["id"]) is None and not os.path.exists(gone["path"])


def test_a_file_added_to_a_videos_bin_is_its_own_also_when_the_bin_has_it_already(env):
    """Adding files to a video's bin takes the owner's uploads of them: a new file, and one the bin has already
    (the owner uploaded it again and added it, so nothing changes in the bin). Files added without an upload (Find
    media) take none."""
    from clipfoundry.studio import project_delete, video_flow

    clip, extra, found = _had(11), _had(12, "image"), _had(13, "image")
    first = _uploaded(clip)
    vid = video_flow.create("local", "local", name="Lake", asset_ids=[clip["id"]], brief={},
                            style_id="settings", remember={"enabled": False}, upload_ids=[first["id"]])["id"]
    again, new = _uploaded(clip), _uploaded(extra)  # uploaded again and added to the bin it is in already
    elsewhere = _uploaded(found)  # another page's upload of the file Find media adds next
    assert video_flow.add_media(vid, [clip["id"], extra["id"]],
                                upload_ids=[again["id"], new["id"]]) == {"added": [extra["id"]]}
    assert video_flow.add_media(vid, [found["id"]]) == {"added": [found["id"]]}
    assert _taken(first, again, new, elsewhere) == [vid, vid, vid, ""]
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 2 and plan["counts"]["files_kept"] == 1
    assert [line for line in plan["stays"] if _again([line])] == [
        f"“{found['filename']}” stays in ClipForge because you added it again since."]


def test_two_clips_projects_made_from_one_recording_on_the_same_day_both_let_it_go(env):
    """Two clips projects made the same day from one recording (uploaded twice: ClipForge stored it once). Deleted
    newest first, the recording stays while the older project uses it, and goes with the older one."""
    from clipfoundry import db
    from clipfoundry.studio import clips_flow, project_delete

    rec = _had(21, filename="stream.mp4")
    first = clips_flow.create("local", "local", asset_id=rec["id"], mode="highlights",
                              upload_ids=[_uploaded(rec)["id"]])["id"]
    second = clips_flow.create("local", "local", asset_id=rec["id"], mode="highlights",
                               upload_ids=[_uploaded(rec)["id"]])["id"]
    assert sorted(r["taken"] for r in db.select("uploads", "1 = 1")) == sorted([first, second])
    plan = project_delete.plan("local", second, "clips")
    assert plan["counts"]["files_kept"] == 1 and not _again(plan["stays"])  # the older project uses it
    project_delete.delete("local", second, "clips")
    plan = project_delete.plan("local", first, "clips")
    assert plan["counts"]["files"] == 1 and plan["counts"]["files_kept"] == 0 and not _again(plan["stays"])
    project_delete.delete("local", first, "clips")
    assert db.fetch("assets", rec["id"]) is None and not os.path.exists(rec["path"])


def test_a_project_takes_only_the_finished_uploads_it_was_given(env):
    from clipfoundry import db
    from clipfoundry.studio import uploads

    clip, other = _had(31), _had(32)
    mine, theirs = _uploaded(clip), _uploaded(clip)  # this page's upload, and another page's of the same file
    waiting = db.insert("uploads", {"workspace_id": "local", "filename": "x.mp4", "size": 3000,
                                    "status": "receiving", "asset_id": clip["id"]})
    other_ws = db.insert("uploads", {"workspace_id": "other", "filename": "x.mp4", "size": 3000,
                                     "status": "complete", "asset_id": clip["id"]})
    not_added = _uploaded(other)  # an upload of a file this project does not take
    uploads.taken("local", [mine["id"], mine["id"], waiting["id"], other_ws["id"], not_added["id"], "", "up-x"],
                  "vid-a", [clip["id"]])
    assert _taken(mine, theirs, waiting, other_ws, not_added) == ["vid-a", "", "", "", ""]
    uploads.taken("local", [mine["id"]], "vid-b", [clip["id"]])  # taken already: it stays the first project's
    uploads.taken("local", [], "vid-c", [clip["id"], other["id"]])  # no uploads given: none is taken
    uploads.taken("local", None, "vid-c", [clip["id"]])
    assert _taken(mine, theirs, not_added) == ["vid-a", "", ""]


def test_the_same_file_sent_twice_in_one_drop_is_the_projects_own_both_times(env):
    """Two copies of one file in a drop are two uploads that give ClipForge's one copy; the page sends both, so both
    are the video's. A later upload no project took is another page's and keeps the file."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, video_flow

    clip = _had(41)
    stored = float(clip["created_at"])
    sent = [db.insert("uploads", {"workspace_id": "local", "filename": clip["filename"], "size": 3000,
                                  "status": "complete", "asset_id": clip["id"], "created_at": started,
                                  "updated_at": stored + 1})["id"] for started in (stored - 2, stored - 1)]
    vid = video_flow.create("local", "local", name="Run", asset_ids=[clip["id"]], brief={}, style_id="settings",
                            remember={"enabled": False}, upload_ids=sent)["id"]
    assert [r["taken"] for r in db.select("uploads", "1 = 1")] == [vid, vid]
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 1 and not _again(plan["stays"])
    _uploaded(clip)
    assert _again(project_delete.plan("local", vid, "full_video")["stays"])


def test_another_pages_upload_that_finished_after_the_video_was_made_keeps_the_file(env):
    """The same file dropped on two pages at about the same time: page 2's upload started first, page 1's stored
    the file and page 1 made its video from it; page 2's upload finished after that. Deleting page 1's video keeps
    the file for page 2."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, video_flow

    clip = _had(51)
    stored = float(clip["created_at"])
    page2 = db.insert("uploads", {"workspace_id": "local", "filename": clip["filename"], "size": 3000,
                                  "status": "receiving", "created_at": stored - 10, "updated_at": stored - 10})
    page1 = db.insert("uploads", {"workspace_id": "local", "filename": clip["filename"], "size": 3000,
                                  "status": "complete", "asset_id": clip["id"], "created_at": stored - 5,
                                  "updated_at": stored})
    vid = video_flow.create("local", "local", name="Talk", asset_ids=[clip["id"]], brief={}, style_id="settings",
                            remember={"enabled": False}, upload_ids=[page1["id"]])["id"]
    db.update("uploads", page2["id"], status="complete", asset_id=clip["id"])
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 0 and plan["counts"]["files_kept"] == 1 and _again(plan["stays"])
    project_delete.delete("local", vid, "full_video", as_of=plan["as_of"])
    assert db.fetch("assets", clip["id"]) and db.fetch("uploads", page2["id"])["asset_id"] == clip["id"]


def test_the_pages_send_the_uploads_they_used(env):
    """Make a YouTube video, Add files, Make clips, the classic video request and a scene's own picture each carry
    the uploads the page used, and those become the project's."""
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.makers.routes import SceneChange

    clip, extra, rec, old = _had(61), _had(62, "image"), _had(63), _had(64)
    u_clip, u_extra, u_rec, u_old = (_uploaded(a) for a in (clip, extra, rec, old))
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.post("/api/studio/videos/setup", headers=H,
                     json={"asset_ids": [clip["id"]], "upload_ids": [u_clip["id"]], "idea": "a lake day",
                           "mode": "ask", "style_id": "settings", "remember": {"enabled": False}})
        assert r.status_code == 200, r.text
        draft = r.json()["id"]
        r = api.post(f"/api/studio/videos/{draft}/media", headers=H,
                     json={"asset_ids": [extra["id"]], "upload_ids": [u_extra["id"]]})
        assert r.status_code == 200, r.text
        r = api.post("/api/studio/clips", headers=H,
                     json={"asset_id": rec["id"], "upload_ids": [u_rec["id"]], "mode": "highlights"})
        assert r.status_code == 200, r.text
        clips = r.json()["id"]
        r = api.post("/api/studio/videos", headers=H,
                     json={"name": "Old", "asset_ids": [old["id"]], "upload_ids": [u_old["id"]],
                           "style_id": "settings", "remember": {"enabled": False}})
        assert r.status_code == 200, r.text
        classic = r.json()["id"]
    assert _taken(u_clip, u_extra, u_rec, u_old) == [draft, draft, clips, classic]
    assert SceneChange(picture_asset_id="as-1", upload_ids=["up-1", "up-2"]).model_dump(exclude_none=True) == {
        "picture_asset_id": "as-1", "upload_ids": ["up-1", "up-2"]}


def test_a_copy_handed_to_an_upload_while_the_video_is_deleted_stays(env, monkeypatch):
    """The owner deletes a video while, on another page, an upload of one of its files finishes: ClipForge hands that
    upload the copy it has. Deleting checks again just before it removes anything, so the copy, and the upload that
    was given it, stay (and the answer says so)."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, uploads, video_flow

    clip = _had(71)
    data = b"\x89PNG\r\n\x1a\n" + os.urandom(2000)  # a picture ClipForge keeps without reading it

    def upload() -> tuple[dict, str]:
        up = uploads.start("local", "owl.png", len(data))
        uploads.put_chunk(up["id"], 0, data)
        return uploads.complete(up["id"]), up["id"]

    owl, first = upload()
    vid = video_flow.create("local", "local", name="Owls", asset_ids=[clip["id"], owl["id"]], brief={},
                            style_id="settings", remember={"enabled": False}, upload_ids=[first])["id"]
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 2 and not _again(plan["stays"])
    view, handed = project_delete._view, []

    def meanwhile(s):  # between the last look and the removal: another page's upload of the picture finishes
        out = view(s)
        if not handed:
            time.sleep(0.01)
            handed.append(upload())
        return out

    monkeypatch.setattr(project_delete, "_view", meanwhile)
    out = project_delete.delete("local", vid, "full_video", as_of=plan["as_of"])
    (again, second), = handed
    assert again["id"] == owl["id"]
    assert db.fetch("assets", owl["id"]) and os.path.isfile(db.fetch("assets", owl["id"])["path"])
    assert db.fetch("uploads", second)["asset_id"] == owl["id"]
    assert "“owl.png” stays in ClipForge because it was used again just now." in out["stays"]
    assert out["counts"]["files"] == 1 and out["counts"]["files_kept"] == 1
    assert db.fetch("assets", clip["id"]) is None and not os.path.exists(clip["path"])


def test_one_file_finished_on_two_pages_is_each_pages_own_upload(env):
    """The same file dropped on two pages while its first upload is still arriving resumes that one upload, so both
    pages finish it. Each gets an upload of its own: the video made on one page takes only its own, and deleting it
    keeps the file for the other page, whose upload no project took yet."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, uploads, video_flow

    clip = _had(81)
    data = b"\x89PNG\r\n\x1a\n" + os.urandom(3000)
    page1 = uploads.start("local", "owl.png", len(data), fingerprint="owl.png|3008|1")
    uploads.put_chunk(page1["id"], 0, data[:1000])
    page2 = uploads.start("local", "owl.png", len(data), fingerprint="owl.png|3008|1")
    assert page2["id"] == page1["id"] and page2["received"] == 1000  # one upload, resumed
    uploads.put_chunk(page1["id"], 1000, data[1000:])
    first, second = uploads.complete(page1["id"]), uploads.complete(page2["id"])
    assert first["id"] == second["id"] and first["upload_id"] == page1["id"] != second["upload_id"]
    assert db.fetch("uploads", second["upload_id"])["status"] == "complete"
    vid = video_flow.create("local", "local", name="Owls", asset_ids=[clip["id"], first["id"]], brief={},
                            style_id="settings", remember={"enabled": False},
                            upload_ids=[first["upload_id"]])["id"]
    assert db.fetch("uploads", second["upload_id"])["taken"] == ""
    plan = project_delete.plan("local", vid, "full_video")
    assert "“owl.png” stays in ClipForge because you added it again since." in plan["stays"]
    project_delete.delete("local", vid, "full_video", as_of=plan["as_of"])
    assert db.fetch("assets", first["id"]) and db.fetch("uploads", second["upload_id"])


def test_a_file_another_video_took_while_this_one_was_deleted_stays(env, monkeypatch):
    """Deleting looks again at what names each file inside its own step, which nothing else can change meanwhile:
    a file another video's page added to its bin after the last look stays, and the answer says so."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, video_flow

    clip, pic = _had(91), _had(92, "image")
    vid = video_flow.create("local", "local", name="Lake", asset_ids=[clip["id"], pic["id"]], brief={},
                            style_id="settings", remember={"enabled": False},
                            upload_ids=[_uploaded(clip)["id"], _uploaded(pic)["id"]])["id"]
    other = video_flow.create("local", "local", name="Beach", asset_ids=[clip["id"]], brief={},
                              style_id="settings", remember={"enabled": False})["id"]
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 1 and plan["counts"]["files_kept"] == 1
    view = project_delete._view

    def meanwhile(s):  # after the last look: the other video's page adds the picture to its bin
        out = view(s)
        if pic["id"] not in db.fetch("studio_projects", other)["asset_ids"]:
            video_flow.add_media(other, [pic["id"]], upload_ids=[_uploaded(pic)["id"]])
        return out

    monkeypatch.setattr(project_delete, "_view", meanwhile)
    out = project_delete.delete("local", vid, "full_video", as_of=plan["as_of"])
    assert out["counts"]["files"] == 0 and out["counts"]["files_kept"] == 2
    assert db.fetch("assets", pic["id"]) and os.path.isfile(pic["path"])
    assert any(line.startswith("“file91.mp4”, “file92.png” stay") or line.startswith("“file92.png”, “file91.mp4” stay")
               for line in out["stays"]), out["stays"]


def test_a_bin_never_names_a_file_deleted_meanwhile(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow

    clip, pic = _had(95), _had(96, "image")
    vid = video_flow.create("local", "local", name="Lake", asset_ids=[clip["id"]], brief={}, style_id="settings",
                            remember={"enabled": False})["id"]
    real_owned = video_flow._owned

    def deleted_after_the_check(ws, aid):
        out = real_owned(ws, aid)
        if aid == pic["id"]:
            db.execute("DELETE FROM assets WHERE id = ?", (aid,))  # another project's delete, right after the check
        return out

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(video_flow, "_owned", deleted_after_the_check)
        with pytest.raises(video_flow.VideoError):
            video_flow.add_media(vid, [pic["id"]])
    assert db.fetch("studio_projects", vid)["asset_ids"] == [clip["id"]]


def test_a_project_made_another_way_never_counts_another_pages_upload_as_its_own(env):
    """A page uploads a file and has not made its video yet (its upload stored the file). A clips project gets the
    same file another way (a link's download, Find media: no upload is sent with it). Deleting that project keeps the
    file for the page, whose Start still works: a project made since ClipForge records which project took an upload
    owns only the uploads its page sent. A project made before that keeps the older rules."""
    from clipfoundry import db
    from clipfoundry.studio import clips_flow, project_delete, video_setup

    clip = _had(1)
    page = _uploaded(clip)
    with db.connect() as conn:  # it started before the file was stored and stored it
        conn.execute("UPDATE uploads SET created_at = ?, updated_at = ? WHERE id = ?",
                     (clip["created_at"] - 5, clip["created_at"] + 1, page["id"]))
    pid = clips_flow.create("local", "local", asset_id=clip["id"], mode="highlights")["id"]
    plan = project_delete.plan("local", pid, "clips")
    assert plan["counts"]["files_kept"] == 1 and _again(plan["stays"]), plan
    project_delete.delete("local", pid, "clips", as_of=plan["as_of"])
    assert db.fetch("assets", clip["id"]) and db.fetch("uploads", page["id"])["taken"] == ""
    video_setup.start("local", "local", asset_ids=[clip["id"]], idea="a lake day", mode="ask",
                      upload_ids=[page["id"]])  # the page's Start still works
