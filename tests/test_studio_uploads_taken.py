"""A file the owner uploads for a project is that project's own, also when ClipForge already had the same bytes.

Deleting a project keeps a file the owner "added again" in the last day, because a page may be about to use it
(project_delete._added_again). ClipForge keeps one copy per file, so an upload of bytes it already had gives the same
copy. Each place a project takes the owner's files marks the newest finished upload of each file that no project took
yet as that project's (uploads.taken), and deleting a project only counts uploads no project took. So a project's own
later upload of a file ClipForge already had no longer keeps that file forever: a video's files, music and voice-over,
a file added to a video's bin (also one it has already), a clips project's video. The same picture chosen for two
scenes of a short is in tests/test_studio_shorts_tidy.py.
"""
from __future__ import annotations

import os
import time

import pytest


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
    asset = db.insert("assets", {"id": aid, "workspace_id": "local", "kind": kind, "sha256": f"{n:064x}",
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
        for a in (clip, pic, music, voice):
            _uploaded(a)
        return video_flow.create("local", "local", name=name, asset_ids=[clip["id"], pic["id"]],
                                 brief={"music": "supplied", "music_asset_id": music["id"],
                                        "voiceover_asset_ids": [voice["id"]]},
                                 style_id="settings", remember={"enabled": False})["id"]

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
    (the owner uploaded it again and added it, so nothing changes in the bin)."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete, video_flow

    clip, extra = _had(11), _had(12, "image")
    _uploaded(clip)
    vid = video_flow.create("local", "local", name="Lake", asset_ids=[clip["id"]], brief={},
                            style_id="settings", remember={"enabled": False})["id"]
    _uploaded(clip)  # uploaded again and added to the bin it is in already
    _uploaded(extra)
    assert video_flow.add_media(vid, [clip["id"], extra["id"]]) == {"added": [extra["id"]]}
    assert all(r["taken"] == vid for r in db.select("uploads", "1 = 1"))
    plan = project_delete.plan("local", vid, "full_video")
    assert plan["counts"]["files"] == 2 and plan["counts"]["files_kept"] == 0 and not _again(plan["stays"])


def test_two_clips_projects_made_from_one_recording_on_the_same_day_both_let_it_go(env):
    """Two clips projects made the same day from one recording (uploaded twice: ClipForge stored it once). Deleted
    newest first, the recording stays while the older project uses it, and goes with the older one."""
    from clipfoundry import db
    from clipfoundry.studio import clips_flow, project_delete

    rec = _had(21, filename="stream.mp4")
    _uploaded(rec)
    first = clips_flow.create("local", "local", asset_id=rec["id"], mode="highlights")["id"]
    _uploaded(rec)
    second = clips_flow.create("local", "local", asset_id=rec["id"], mode="highlights")["id"]
    assert sorted(r["taken"] for r in db.select("uploads", "1 = 1")) == sorted([first, second])
    plan = project_delete.plan("local", second, "clips")
    assert plan["counts"]["files_kept"] == 1 and not _again(plan["stays"])  # the older project uses it
    project_delete.delete("local", second, "clips")
    plan = project_delete.plan("local", first, "clips")
    assert plan["counts"]["files"] == 1 and plan["counts"]["files_kept"] == 0 and not _again(plan["stays"])
    project_delete.delete("local", first, "clips")
    assert db.fetch("assets", rec["id"]) is None and not os.path.exists(rec["path"])


def test_a_project_takes_only_finished_uploads_no_project_took_and_the_newest_first(env):
    from clipfoundry import db
    from clipfoundry.studio import uploads

    clip = _had(31)
    older = _uploaded(clip)
    time.sleep(0.01)
    newer = _uploaded(clip)
    waiting = db.insert("uploads", {"workspace_id": "local", "filename": "x.mp4", "size": 3000,
                                    "status": "receiving", "asset_id": clip["id"]})
    other_ws = db.insert("uploads", {"workspace_id": "other", "filename": "x.mp4", "size": 3000,
                                     "status": "complete", "asset_id": clip["id"]})
    uploads.taken("local", [clip["id"], clip["id"], ""], "vid-a")  # one file named twice is taken once
    assert [db.fetch("uploads", u["id"])["taken"] for u in (older, newer, waiting, other_ws)] == ["", "vid-a", "", ""]
    uploads.taken("local", [clip["id"]], "vid-b")
    uploads.taken("local", [clip["id"]], "vid-c")  # nothing left to take: nothing changes
    assert [db.fetch("uploads", u["id"])["taken"] for u in (older, newer)] == ["vid-b", "vid-a"]
