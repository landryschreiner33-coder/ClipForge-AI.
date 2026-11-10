"""Big footage used where it is (docs/clipforge/LONG_VIDEOS.md, "Big footage"): the folders this computer offers,
browsing them, linking a file without copying it, the quick content id, the desktop upload limit that follows free
space, the routes, and what deleting an example of a linked file removes (never the owner's file)."""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from synthetic_media import make_video, needs_ffmpeg

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """A data folder and one allowed root ("home") of this test's own."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLIPFOUNDRY_LOCAL_ROOTS", str(home))
    from clipfoundry import db

    db.init()
    return home


def _footage(home: Path) -> Path:
    """A folder with media, other files, a hidden file, a sub-folder and a Windows drive's own folder."""
    folder = home / "footage"
    folder.mkdir()
    for name in ("b.mov", "a.MP4", "notes.txt", ".hidden.mp4", "music.mp3", "pic.jpg", "Zed.webm"):
        (folder / name).write_bytes(b"x" * 10)
    (folder / "sub").mkdir()
    (folder / "$RECYCLE.BIN").mkdir()
    return folder


def test_roots_come_from_the_override_and_only_folders_that_exist(env, monkeypatch, tmp_path):
    from clipfoundry.studio import local_files

    assert local_files.roots() == [{"label": "home", "path": str(env)}]
    monkeypatch.setenv("CLIPFOUNDRY_LOCAL_ROOTS", os.pathsep.join([str(env), str(tmp_path / "missing"), str(env)]))
    assert local_files.roots() == [{"label": "home", "path": str(env)}]  # missing left out, no duplicates
    monkeypatch.delenv("CLIPFOUNDRY_LOCAL_ROOTS")
    real = local_files.roots()  # this computer's own places: the home folder first, each one an existing folder
    assert real and real[0]["label"] == "Home" and real[0]["path"] == str(Path.home().resolve())
    assert all(Path(r["path"]).is_dir() for r in real)
    assert len({r["path"] for r in real}) == len(real)


def test_browse_lists_the_roots_then_media_files_and_folders(env, tmp_path):
    from clipfoundry.studio import local_files

    folder = _footage(env)
    top = local_files.browse("")
    assert top == {"path": "", "parent": "", "roots": local_files.roots(), "files": [], "truncated": False,
                   "folders": [{"name": "home", "path": str(env)}]}
    assert local_files.browse(str(env))["parent"] == ""  # a root has no parent to go up to
    got = local_files.browse(str(folder))
    assert got["path"] == str(folder) and got["parent"] == str(env) and got["roots"] == local_files.roots()
    assert got["folders"] == [{"name": "sub", "path": str(folder / "sub")}]  # hidden and system folders skipped
    assert [(f["name"], f["kind"], f["size"]) for f in got["files"]] == \
        [("a.MP4", "video", 10), ("b.mov", "video", 10), ("music.mp3", "audio", 10), ("pic.jpg", "image", 10),
         ("Zed.webm", "video", 10)]  # only media, sorted without regard to case
    assert all(f["path"] == str(folder / f["name"]) and f["modified"] > 0 for f in got["files"])
    assert got["truncated"] is False
    with pytest.raises(local_files.LocalError) as outside:
        local_files.browse(str(tmp_path))  # the parent of the root is not allowed
    assert outside.value.status == 403 and "your own folders" in str(outside.value)
    with pytest.raises(local_files.LocalError) as missing:
        local_files.browse(str(env / "nope"))
    assert missing.value.status == 404 and "no folder" in str(missing.value)
    with pytest.raises(local_files.LocalError) as relative:
        local_files.browse("footage")
    assert relative.value.status == 400
    if hasattr(os, "symlink"):  # a link inside the root that points outside it is followed, then refused
        (tmp_path / "elsewhere").mkdir()
        os.symlink(tmp_path / "elsewhere", env / "link")
        with pytest.raises(local_files.LocalError) as linked:
            local_files.browse(str(env / "link"))
        assert linked.value.status == 403
        assert not local_files.allowed(env / "link") and local_files.allowed(folder / "a.MP4")


def test_browse_cuts_a_huge_folder_short_and_says_so(env, monkeypatch):
    from clipfoundry.studio import local_files

    monkeypatch.setattr(local_files, "MAX_ENTRIES", 3)
    folder = _footage(env)
    got = local_files.browse(str(folder))
    assert [f["name"] for f in got["files"]] == ["a.MP4", "b.mov", "music.mp3"] and got["truncated"] is True


@needs_ffmpeg
def test_linking_uses_the_file_where_it_is(env, tmp_path):
    from clipfoundry import config, db
    from clipfoundry.studio import uploads

    file = make_video(env / "clip.mp4", seconds=2.0)
    mode = file.stat().st_mode
    row = uploads.link_local("local", str(file))
    assert row["sha256"].startswith("quick:") and uploads.is_linked(row) and row["kind"] == "video"
    assert row["path"] == str(file) and row["size"] == file.stat().st_size and row["filename"] == "clip.mp4"
    assert row["probe"]["duration"] == pytest.approx(2.0, abs=0.2) and row["probe"]["has_audio"]
    work = uploads.work_dir(row)
    data = config.data_dir().resolve()
    assert work == data / "assets" / "local" / row["id"] and work.is_dir()
    assert env not in work.parents  # nothing of ClipForge's lands next to the owner's file
    assert Path(row["thumb_path"]) == work / "thumb.jpg" and (work / "thumb.jpg").is_file()
    assert list(env.iterdir()) == [file] and file.stat().st_mode == mode  # the file and its folder are untouched
    view = uploads.asset_view(row)
    assert view["linked"] is True and view["proxy"] is False and view["has_thumbnail"]
    assert uploads.link_local("local", str(file))["id"] == row["id"]  # the same file twice is one asset
    assert len(db.select("assets", "workspace_id = 'local'")) == 1
    moved = file.rename(env / "moved.mp4")  # the same file found again elsewhere: the asset follows it
    again = uploads.link_local("local", str(moved))
    assert again["id"] == row["id"] and again["path"] == str(moved)


@needs_ffmpeg
def test_linking_is_refused_where_it_must_be(env, tmp_path, monkeypatch):
    from clipfoundry import config, db
    from clipfoundry.studio import local_files, uploads

    def refused(path: str, status: int, words: str) -> None:
        with pytest.raises(uploads.UploadError) as exc:
            uploads.link_local("local", path)
        assert exc.value.status == status and words in str(exc.value), str(exc.value)

    (tmp_path / "elsewhere.mp4").write_bytes(b"x")
    refused(str(tmp_path / "elsewhere.mp4"), 403, "outside the folders ClipForge may read")
    (env / "notes.txt").write_text("hi")
    refused(str(env / "notes.txt"), 400, "Unsupported file type")
    refused("clip.mp4", 400, "full path")
    refused(str(env / "missing.mp4"), 404, "no file")
    refused(str(env), 400, "not a file")
    (env / "empty.mp4").write_bytes(b"")
    refused(str(env / "empty.mp4"), 400, "empty")
    (env / "broken.mp4").write_bytes(os.urandom(5000))
    refused(str(env / "broken.mp4"), 422, "broken.mp4 is not a readable video file")
    assert db.select("assets") == [] and not list((config.data_dir() / "assets" / "local").glob("*"))
    inside = config.data_dir() / "inside.mp4"
    inside.write_bytes(b"x")
    monkeypatch.setenv("CLIPFOUNDRY_LOCAL_ROOTS", str(tmp_path))  # even with the data folder under a root
    refused(str(inside), 400, "ClipForge's own data folder")
    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    good = make_video(env / "clip.mp4", seconds=1.0)
    refused(str(good), 403, "cloud")
    with pytest.raises(local_files.LocalError) as browse:
        local_files.browse("")
    assert browse.value.status == 403 and "cloud" in str(browse.value)


def test_the_quick_hash_reads_three_samples_whatever_the_size(env, tmp_path):
    from clipfoundry.studio import uploads

    big = tmp_path / "big.bin"
    size = 200 << 20
    with open(big, "wb") as f:
        f.truncate(size)  # a sparse 200 MB file: reading all of it would take far longer than the samples
    t = time.perf_counter()
    first = uploads.quick_hash(big)
    assert time.perf_counter() - t < 1.0 and first.startswith("quick:") and len(first) == len("quick:") + 64

    def poke(offset: int) -> str:
        with open(big, "r+b") as f:
            f.seek(offset)
            f.write(b"\x01")
        return uploads.quick_hash(big)

    assert poke(10 << 20) == first  # between the samples: not read
    middle = poke((size - uploads.QUICK_SAMPLE) // 2 + 5)
    assert middle != first  # the middle sample
    end = poke(size - 1)
    assert end not in (first, middle)  # the last sample
    start = poke(0)
    assert start not in (first, middle, end)  # the first sample
    with open(big, "r+b") as f:
        f.truncate(size + 1)
    assert uploads.quick_hash(big) != start  # the size is part of it
    (tmp_path / "s1.bin").write_bytes(b"a" * 1000)
    (tmp_path / "s2.bin").write_bytes(b"a" * 999 + b"b")
    assert uploads.quick_hash(tmp_path / "s1.bin") != uploads.quick_hash(tmp_path / "s2.bin")  # small: all of it


def test_the_desktop_upload_limit_follows_free_space(env, monkeypatch):
    from clipfoundry.cloud import settings as cloud_settings
    from clipfoundry.studio import uploads

    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda path: SimpleNamespace(free=int(9.3e9)))
    assert uploads.max_upload_bytes() == int(9.3e9) - uploads.DISK_RESERVE
    with pytest.raises(uploads.UploadError) as exc:
        uploads.start("local", "footage.mp4", 17_000_000_000)
    assert exc.value.status == 413 and exc.value.extra == {"free": int(9.3e9)}
    assert str(exc.value) == ("The file is 17.0 GB and only 9.3 GB is free where ClipForge keeps its files. Free "
                              "some space, or use Add from this computer, which uses the file where it is without "
                              "copying it.")
    assert uploads.start("local", "small.mp4", 5_000_000_000)["status"] == "receiving"  # fits in the space left
    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda path: SimpleNamespace(free=1 << 30))
    assert uploads.max_upload_bytes() == 0  # less than the reserve: nothing can be copied in
    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda path: SimpleNamespace(free=1 << 50))
    assert uploads.max_upload_bytes() == uploads.DESKTOP_UPLOAD_CAP
    with pytest.raises(uploads.UploadError) as huge:
        uploads.start("local", "huge.mov", 600 << 30)
    assert huge.value.status == 413 and "at most 512 GB" in str(huge.value) and "Add from this computer" in str(huge.value)
    monkeypatch.setattr(cloud_settings, "enabled", lambda: True)  # the cloud keeps its configured limit
    monkeypatch.setattr(cloud_settings, "current", lambda: SimpleNamespace(max_upload_bytes=8 << 30))
    assert uploads.max_upload_bytes() == 8 << 30
    with pytest.raises(uploads.UploadError) as cloud:
        uploads.start("local", "footage.mp4", 17_000_000_000)
    assert str(cloud.value) == "The file is 17.0 GB; the limit is 8.6 GB." and cloud.value.extra == {}


@needs_ffmpeg
def test_routes_browse_link_and_prepare(env, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import db, jobs as app_jobs
    from clipfoundry.api import app
    from clipfoundry.studio import jobs, uploads, video_flow

    good = make_video(env / "clip.mp4", seconds=2.0)
    (env / "notes.txt").write_text("hi")
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        top = api.get("/api/local/browse", headers=H)
        assert top.status_code == 200 and top.json()["folders"] == [{"name": "home", "path": str(env)}]
        here = api.get("/api/local/browse", params={"path": str(env)}, headers=H).json()
        assert [f["name"] for f in here["files"]] == ["clip.mp4"] and here["parent"] == ""
        outside = api.get("/api/local/browse", params={"path": str(tmp_path)}, headers=H)
        assert outside.status_code == 403 and "your own folders" in outside.json()["detail"]
        assert api.get("/api/local/browse", params={"path": str(env / "nope")}, headers=H).status_code == 404

        r = api.post("/api/uploads/link", json={"paths": [str(good), str(env / "notes.txt")]}, headers=H)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [a["filename"] for a in body["assets"]] == ["clip.mp4"] and body["assets"][0]["linked"] is True
        assert body["problems"] == [{"path": str(env / "notes.txt"), "detail": uploads.UNSUPPORTED}]
        aid = body["assets"][0]["id"]
        assert api.get(f"/api/assets/{aid}").json()["linked"] is True
        assert api.get(f"/api/assets/{aid}/media").content == good.read_bytes()  # served from where it is
        assert api.get(f"/api/assets/{aid}/thumbnail").status_code == 200
        too_many = api.post("/api/uploads/link", json={"paths": [str(good)] * 201}, headers=H)
        assert too_many.status_code == 422

        submitted = []
        monkeypatch.setattr(app_jobs.worker, "submit_studio", lambda job_id: submitted.append(job_id))
        p = api.post(f"/api/assets/{aid}/prepare", headers=H)
        assert p.status_code == 200, p.text
        job = p.json()
        assert job["job"].startswith("job-") and job["status"] == "queued" and submitted == [job["job"]]
        assert api.post(f"/api/assets/{aid}/prepare", headers=H).json()["job"] == job["job"]  # one job per file
        s = api.get(f"/api/assets/{aid}/prepare", headers=H).json()
        assert s == {"transcript": False, "proxy": False,
                     "job": {"id": job["job"], "status": "queued", "progress": 0.0, "message": "Waiting for a worker",
                             "error": ""}}
        assert api.post("/api/assets/as-nobody/prepare", headers=H).status_code == 404
        assert api.get("/api/assets/as-nobody/prepare", headers=H).status_code == 404

        def listened(asset, settings, lease=None, cached_only=False):  # a stand-in for Whisper: writes nothing
            (uploads.work_dir(asset) / "transcript.json").write_text('{"segments": []}', encoding="utf-8")
            return []

        monkeypatch.setattr(video_flow, "transcript_words", listened)
        jobs.run(job["job"])  # what the worker does, here and now
        done = api.get(f"/api/assets/{aid}/prepare", headers=H).json()
        assert done["transcript"] is True and done["proxy"] is False  # a small clip needs no proxy
        assert done["job"]["status"] == "done" and done["job"]["progress"] == 1.0
        assert db.fetch("studio_jobs", job["job"])["result"] == {"transcript": True, "proxy": False}
        work = uploads.work_dir(db.fetch("assets", aid))
        assert (work / "audio.wav").is_file() and (work / "transcript.json").is_file()
        assert sorted(p.name for p in env.iterdir()) == ["clip.mp4", "notes.txt"]  # still nothing beside the file


@needs_ffmpeg
def test_deleting_an_example_of_a_linked_file_keeps_the_owners_file(env, tmp_path):
    from clipfoundry import db
    from clipfoundry.studio import reference, uploads

    linked = uploads.link_local("local", str(make_video(env / "clip.mp4", seconds=1.0)))
    work = uploads.work_dir(linked)
    (work / "audio.wav").write_bytes(b"x")
    (work / "transcript.parts").mkdir()
    (work / "transcript.parts" / "0.json").write_text("{}")
    note = reference._drop_file(linked["id"], "local")  # noqa: SLF001
    assert "stays where it is" in note and db.fetch("assets", linked["id"]) is None
    assert not work.exists() and (env / "clip.mp4").is_file()  # ClipForge's folder is gone, the owner's file is not
    copy = make_video(tmp_path / "upload.mp4", seconds=1.0)
    stored = uploads.store_file("local", copy, "upload.mp4")  # a stored upload loses its original as before
    folder = Path(stored["path"]).parent
    assert reference._drop_file(stored["id"], "local") == "The video file was deleted."  # noqa: SLF001
    assert not folder.exists() and db.fetch("assets", stored["id"]) is None


@needs_ffmpeg
def test_the_same_file_linked_twice_at_once_is_one_asset(env, monkeypatch):
    """Adding the same file twice at the same moment (two pages, or a double click) gives both the one asset, also
    when another ClipForge program linked it between the check and the save."""
    import threading

    from clipfoundry import db
    from clipfoundry.studio import uploads

    file = make_video(env / "clip.mp4", seconds=1.0)
    arrived, both_in = [], threading.Event()
    real = uploads._inspect

    def slow_inspect(*a, **k):
        arrived.append(1)
        if len(arrived) >= 2:
            both_in.set()
        both_in.wait(1.5)
        return real(*a, **k)

    monkeypatch.setattr(uploads, "_inspect", slow_inspect)
    got: list = []
    threads = [threading.Thread(target=lambda: got.append(uploads.link_local("local", str(file)))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(got) == 2 and got[0]["id"] == got[1]["id"]
    assert [p.name for p in uploads.assets_dir("local").iterdir()] == [got[0]["id"]]

    # another program saved the same file between this one's check and its save
    other = make_video(env / "other.mp4", seconds=1.2)
    digest = uploads.quick_hash(other)

    def other_program_saves_first(f, kind, folder, *a, **k):
        db.insert("assets", {"id": "as-other0000000000", "workspace_id": "local", "kind": "video",
                             "filename": "other.mp4", "sha256": digest, "size": other.stat().st_size,
                             "path": str(other), "probe": {"duration": 1.2}})
        return real(f, kind, folder, *a, **k)

    monkeypatch.setattr(uploads, "_inspect", other_program_saves_first)
    assert uploads.link_local("local", str(other))["id"] == "as-other0000000000"
    assert sorted(p.name for p in uploads.assets_dir("local").iterdir()) == sorted([got[0]["id"]])
    assert other.is_file()  # the owner's file is never touched
