"""Resumable private uploads (CF-02 input side): exact resume after an interruption, integrity, dedupe, limits
and workspace isolation."""
from __future__ import annotations

import hashlib
import os
import subprocess

import pytest

from cloud_support import ORIGIN, OWNER, SECOND, cloud_env, sign_in


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def video(tmp_path, seconds: float = 2.0, name: str = "talk.mp4") -> bytes:
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=25:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out.read_bytes()


def send(api, upload: dict, data: bytes, chunk: int = 64 * 1024, stop_after: int | None = None) -> dict:
    sent = 0
    while upload["received"] < len(data):
        a = upload["received"]
        r = api.put(f"/api/uploads/{upload['id']}?offset={a}", content=data[a:a + chunk])
        assert r.status_code == 200, r.text
        upload = r.json()
        sent += 1
        if stop_after is not None and sent >= stop_after:
            break
    return upload


def test_interrupted_upload_resumes_exactly_and_becomes_one_asset(api, tmp_path):
    data = video(tmp_path)
    fp = f"talk.mp4|{len(data)}|1700000000"
    up = api.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data), "fingerprint": fp,
                                        "sha256": hashlib.sha256(data).hexdigest()}).json()
    up = send(api, up, data, chunk=16 * 1024, stop_after=2)  # the browser was closed after two chunks
    assert 0 < up["received"] < len(data) and up["status"] == "receiving"
    early = api.post(f"/api/uploads/{up['id']}/complete")
    assert early.status_code == 409 and "Resume upload" in early.json()["detail"]
    again = api.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data), "fingerprint": fp}).json()
    assert again["id"] == up["id"] and again["received"] == up["received"]  # same upload, not a duplicate row
    stale = api.put(f"/api/uploads/{up['id']}?offset=0", content=data[:10])
    assert stale.status_code == 409 and stale.json()["received"] == up["received"]
    up = send(api, again, data)
    asset = api.post(f"/api/uploads/{up['id']}/complete").json()
    assert asset["sha256"] == hashlib.sha256(data).hexdigest() and asset["kind"] == "video"
    assert asset["duration"] == pytest.approx(2.0, abs=0.2) and asset["has_audio"]
    media = api.get(f"/api/assets/{asset['id']}/media")
    assert media.content == data
    assert api.get(f"/api/assets/{asset['id']}/media", headers={"Range": "bytes=0-9"}).status_code == 206
    assert api.get(f"/api/assets/{asset['id']}/thumbnail").status_code == 200


def test_a_failed_write_is_cut_back_so_the_next_chunk_continues_cleanly(api, tmp_path, monkeypatch):
    from clipfoundry.studio import uploads

    data = os.urandom(300_000)
    up = api.post("/api/uploads", json={"filename": "x.mp4", "size": len(data)}).json()
    up = send(api, up, data, stop_after=1)
    real = os.fsync
    calls = {"n": 0}

    def flaky(fd):
        calls["n"] += 1
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(uploads.os, "fsync", flaky)
    r = api.put(f"/api/uploads/{up['id']}?offset={up['received']}", content=data[up["received"]:up["received"] + 1000])
    assert r.status_code == 507 and r.json()["received"] == up["received"]
    monkeypatch.setattr(uploads.os, "fsync", real)
    assert (uploads.uploads_dir() / f"{up['id']}.part").stat().st_size == up["received"]


def test_damaged_transfer_is_refused_and_nothing_is_stored(api, tmp_path):
    data = video(tmp_path)
    up = api.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data),
                                        "sha256": hashlib.sha256(b"other").hexdigest()}).json()
    send(api, up, data)
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 422 and "damaged" in r.json()["detail"]
    assert api.get(f"/api/uploads/{up['id']}").json()["status"] == "failed"


def test_the_same_file_twice_is_stored_once(api, tmp_path):
    data = video(tmp_path)
    ids = set()
    for _ in range(2):
        up = api.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data)}).json()
        send(api, up, data)
        ids.add(api.post(f"/api/uploads/{up['id']}/complete").json()["id"])
    assert len(ids) == 1


def test_unreadable_and_unsupported_files_get_their_own_errors(api, tmp_path):
    r = api.post("/api/uploads", json={"filename": "notes.exe", "size": 10})
    assert r.status_code == 400 and "Unsupported file type" in r.json()["detail"]
    junk = b"not a video at all" * 100
    up = api.post("/api/uploads", json={"filename": "broken.mp4", "size": len(junk)}).json()
    send(api, up, junk)
    r = api.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 422 and "not a readable video" in r.json()["detail"]


def test_storage_full_stops_admitting_without_deleting(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    idp = cloud_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLIPFOUNDRY_STORAGE_LIMIT_GB", str(1 / 1024))  # 1 MB
    from clipfoundry.cloud import settings as cloud_settings

    cloud_settings.reset()
    with TestClient(app, base_url=ORIGIN) as c:
        sign_in(c, idp)
        ok = c.post("/api/uploads", json={"filename": "a.mp4", "size": 600_000})
        assert ok.status_code == 200
        full = c.post("/api/uploads", json={"filename": "b.mp4", "size": 600_000})
        assert full.status_code == 507 and "Nothing was deleted" in full.json()["detail"]
        assert c.get(f"/api/uploads/{ok.json()['id']}").json()["status"] == "receiving"
    cloud_settings.reset()


def test_uploads_and_assets_never_cross_workspaces(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    idp = cloud_env(monkeypatch, tmp_path)
    data = video(tmp_path)
    with TestClient(app, base_url=ORIGIN) as a, TestClient(app, base_url=ORIGIN) as b:
        sign_in(a, idp, OWNER)
        sign_in(b, idp, SECOND)
        up = a.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data)}).json()
        assert b.get(f"/api/uploads/{up['id']}").status_code == 404
        assert b.put(f"/api/uploads/{up['id']}?offset=0", content=data[:100]).status_code == 404
        send(a, up, data)
        asset = a.post(f"/api/uploads/{up['id']}/complete").json()
        for path in (f"/api/assets/{asset['id']}", f"/api/assets/{asset['id']}/media",
                     f"/api/assets/{asset['id']}/thumbnail"):
            assert b.get(path, headers={"Range": "bytes=0-9"}).status_code == 404, path
        # B uploading the very same bytes gets its own asset, never A's
        up_b = b.post("/api/uploads", json={"filename": "talk.mp4", "size": len(data)}).json()
        send(b, up_b, data)
        assert b.post(f"/api/uploads/{up_b['id']}/complete").json()["id"] != asset["id"]
    from clipfoundry.cloud import settings as cloud_settings

    cloud_settings.reset()


def test_a_project_still_downloading_from_a_link_has_no_picture_yet_and_does_not_crash(api):
    from clipfoundry import db

    p = db.create_project("From a link", status="importing", stage="download")  # no source file yet
    assert db.get_project(p["id"])["source_path"] in (None, "")
    for path in (f"/api/projects/{p['id']}/thumbnail", f"/api/projects/{p['id']}/source"):
        assert api.get(path).status_code == 404
    item = next(i for i in api.get("/api/studio/projects").json() if i["id"] == p["id"])
    assert item["thumbnail"] == ""  # the Studio shows the plain frame instead of asking for a picture


def test_a_full_video_whose_first_file_has_no_picture_is_listed_without_one(api, tmp_path):
    from clipfoundry import db

    sound = tmp_path / "voice.m4a"
    sound.write_bytes(b"x")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"\xff\xd8\xff")
    a = db.insert("assets", {"workspace_id": "local", "kind": "audio", "filename": "voice.m4a", "sha256": "s1",
                             "size": 1, "path": str(sound), "probe": {"duration": 9, "has_audio": True}})
    b = db.insert("assets", {"workspace_id": "local", "kind": "video", "filename": "trip.mp4", "sha256": "s2",
                             "size": 1, "path": str(sound), "thumb_path": str(frame), "probe": {"duration": 9}})
    quiet = db.insert("studio_projects", {"workspace_id": "local", "name": "Voice first", "asset_ids": [a["id"]]})
    shown = db.insert("studio_projects", {"workspace_id": "local", "name": "Picture first", "asset_ids": [b["id"]]})
    items = {i["id"]: i for i in api.get("/api/studio/projects?kind=full_video").json()}
    assert items[quiet["id"]]["thumbnail"] == ""  # no request that can only answer 404
    assert items[shown["id"]]["thumbnail"] == f"/api/assets/{b['id']}/thumbnail"
    assert api.get(items[shown["id"]]["thumbnail"]).status_code == 200


def _received(api, data: bytes, name: str = "talk.mp4") -> str:
    """An upload with every byte received, not completed yet."""
    up = api.post("/api/uploads", json={"filename": name, "size": len(data)}).json()
    return send(api, up, data)["id"]


def test_the_same_file_finishing_twice_at_once_is_stored_once_and_both_finish(api, tmp_path, monkeypatch):
    """Two uploads of the same file that finish at the same moment (the file dropped twice, or on two pages) both
    become the one stored asset: neither is refused, left "receiving", or leaves a folder of its own behind."""
    import threading

    from clipfoundry.studio import uploads

    data = video(tmp_path)
    first, second = _received(api, data), _received(api, data)
    arrived, both_in = [], threading.Event()
    real = uploads._inspect

    def slow_inspect(*a, **k):  # both stores look for the file before either has saved it
        arrived.append(1)
        if len(arrived) >= 2:
            both_in.set()
        both_in.wait(1.5)
        return real(*a, **k)

    monkeypatch.setattr(uploads, "_inspect", slow_inspect)
    answers: dict = {}

    def finish(upload_id: str) -> None:
        answers[upload_id] = api.post(f"/api/uploads/{upload_id}/complete")

    threads = [threading.Thread(target=finish, args=(u,)) for u in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert [answers[u].status_code for u in (first, second)] == [200, 200], [answers[u].text for u in answers]
    assert answers[first].json()["id"] == answers[second].json()["id"]
    assert {api.get(f"/api/uploads/{u}").json()["status"] for u in (first, second)} == {"complete"}
    folders = [p.name for p in uploads.assets_dir("local").iterdir()]
    assert folders == [answers[first].json()["id"]]  # one copy, no stray folder
    assert not list(uploads.uploads_dir().glob("*.part"))


@pytest.fixture()
def windows_deletes(monkeypatch):
    """Deleting as on Windows, which refuses to delete a read-only file (a stored copy is kept read-only)."""
    import stat

    real_unlink = os.unlink

    def windows_unlink(path, *args, dir_fd=None, **kw):
        st = os.lstat(path, dir_fd=dir_fd)
        if not stat.S_ISLNK(st.st_mode) and not st.st_mode & stat.S_IWRITE:
            raise PermissionError(13, "Access is denied", str(path))
        return real_unlink(path, *args, dir_fd=dir_fd, **kw)

    monkeypatch.setattr(os, "unlink", windows_unlink)
    monkeypatch.setattr(os, "remove", windows_unlink)


def test_a_file_another_clipforge_stored_a_moment_earlier_is_used_and_the_copy_is_removed(api, tmp_path,
                                                                                          monkeypatch,
                                                                                          windows_deletes):
    """The lock is per program; another ClipForge program (Autopilot runs in its own) can store the same bytes
    between the check and the save. The save then finds that file, uses it, and removes its own read-only copy."""
    from clipfoundry import db
    from clipfoundry.studio import uploads

    data = video(tmp_path)
    upload_id = _received(api, data)
    digest = hashlib.sha256(data).hexdigest()
    other = uploads.assets_dir("local") / "as-other0000000000"
    other.mkdir()
    (other / "original.mp4").write_bytes(data)
    real = uploads._inspect
    made: list = []

    def other_program_saves_first(file, kind, folder, *a, **k):
        made.append(folder)
        db.insert("assets", {"id": "as-other0000000000", "workspace_id": "local", "kind": "video",
                             "filename": "talk.mp4", "sha256": digest, "size": len(data),
                             "path": str(other / "original.mp4"), "probe": {"duration": 2.0}})
        return real(file, kind, folder, *a, **k)

    monkeypatch.setattr(uploads, "_inspect", other_program_saves_first)
    r = api.post(f"/api/uploads/{upload_id}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "as-other0000000000"
    assert api.get(f"/api/uploads/{upload_id}").json()["status"] == "complete"
    assert made and not made[0].exists()  # its own read-only copy was removed, also on Windows
    assert len(db.select("assets", "workspace_id = 'local'")) == 1 and (other / "original.mp4").is_file()


def test_a_copy_that_cannot_be_read_is_removed_also_when_it_is_read_only(api, windows_deletes):
    """A stored copy is kept read-only; an upload that turns out not to be a readable file removes it all the same
    (Windows refuses to delete a read-only file unless it is made writable first)."""
    from clipfoundry.studio import uploads

    junk = b"not a video at all" * 100
    up = api.post("/api/uploads", json={"filename": "broken.mp4", "size": len(junk)}).json()
    send(api, up, junk)
    assert api.post(f"/api/uploads/{up['id']}/complete").status_code == 422
    assert not list(uploads.assets_dir("local").iterdir())
