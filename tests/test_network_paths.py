"""Addresses of other computers never reach the file system.

On Windows, merely looking at \\\\server\\share\\x (or //server/share/x, or any mix of the two slashes: resolving it,
asking whether it is a file, listing it) connects to that server and signs in as the person, handing it their
password hash. Any web page the person visits can make the browser ask ClipForge's own address for something (an
image or script tag needs no permission), a downloaded FilmCraft project can carry any text, and an AI model's
answer can be steered by the words in a video. So each place below refuses such an address before a single file is
looked at. The calls that would reach the file system are recorded, so this is checked on every computer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

BASE = "http://127.0.0.1:8765"
NETWORK = ["//evil.example/share/x.mp4", "\\\\evil.example\\share\\x.mp4", "\\/evil.example/share/x.mp4",
           "/\\evil.example\\share\\x.mp4", "\\\\?\\UNC\\evil.example\\share\\x.mp4", "\\\\.\\pipe\\evil"]


def _record(monkeypatch) -> list[str]:
    """Every path the code below looks at, from now on."""
    looked: list[str] = []

    def spy(owner, name):
        real = getattr(owner, name)

        def wrapper(target, *a, **k):
            looked.append(str(target))
            return real(target, *a, **k)

        monkeypatch.setattr(owner, name, wrapper)

    for name in ("resolve", "is_file", "is_dir", "exists", "stat", "iterdir"):
        spy(Path, name)
    for owner, name in ((os.path, "realpath"), (os.path, "isfile"), (os.path, "exists"), (os, "scandir")):
        spy(owner, name)
    return looked


def _evil(looked: list[str]) -> list[str]:
    return [p for p in looked if "evil" in p]


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLIPFOUNDRY_LOCAL_ROOTS", str(home))
    from clipfoundry import db

    db.init()
    return home


# ------------------------------------------------------------------ the app's own page (api.py, the catch-all)
def test_the_app_page_never_looks_at_another_computers_address(data, monkeypatch):
    """Every address the app does not know otherwise serves its page (a link into the app, say), and its files are
    served by name: /\\\\evil\\share\\x was resolved first, then checked."""
    from fastapi.testclient import TestClient

    from clipfoundry import config
    from clipfoundry.api import app

    if not (config.FRONTEND_DIST / "index.html").is_file():
        pytest.skip("the app's page is not built")
    page = (config.FRONTEND_DIST / "index.html").read_text(encoding="utf-8")
    with TestClient(app, base_url=BASE) as api:
        looked = _record(monkeypatch)
        for bad in ("//evil.example/share/x", "%5C%5Cevil.example%5Cshare%5Cx", "%5C/evil.example/share/x",
                    "/%5Cevil.example%5Cshare%5Cx", "C:/evil/x", "C:evil", "index.html:evil", "%2E%2E/%2E%2E/evil",
                    "evil%00", "phone/%2E%2E/%2E%2E/evil"):
            r = api.get(f"{BASE}/{bad}")
            assert r.status_code == 200 and r.text == page, bad  # the app's own page, nothing else
        assert not _evil(looked), _evil(looked)
        r = api.get(f"{BASE}/app-icon.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert api.get(f"{BASE}/phone/app.js").status_code == 200
        assert api.get(f"{BASE}/projects/abc").text == page  # a link into the app
        assert api.get(f"{BASE}/api/nothing-here").status_code == 404


# ------------------------------------------------------------------ "Add from this computer" (studio/local_files.py)
@pytest.mark.parametrize("bad", NETWORK)
def test_the_folder_picker_never_looks_at_another_computer(data, monkeypatch, bad):
    """GET /api/local/browse?path=\\\\evil\\share\\x was resolved before it was checked against the folders
    ClipForge may read."""
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.studio import local_files

    with TestClient(app, base_url=BASE) as api:
        looked = _record(monkeypatch)
        with pytest.raises(local_files.LocalError) as err:
            local_files.browse(bad)
        assert err.value.status == 403 and "other computers" in str(err.value)
        r = api.get(f"{BASE}/api/local/browse", params={"path": bad})
        assert r.status_code == 403
    assert not _evil(looked), _evil(looked)


@pytest.mark.parametrize("bad", NETWORK)
def test_linking_never_looks_at_another_computer(data, monkeypatch, bad):
    from clipfoundry.studio import uploads

    looked = _record(monkeypatch)
    with pytest.raises(uploads.UploadError) as err:
        uploads.link_local("local", bad)
    assert err.value.status == 403 and "other computers" in str(err.value)
    assert not _evil(looked), _evil(looked)


def test_a_network_folder_the_owner_listed_is_still_allowed():
    """CLIPFOUNDRY_LOCAL_ROOTS may name a share the owner keeps footage on: addresses on that share (any letter
    case) are still looked at, other computers are not. Decided from the text alone."""
    from clipfoundry.studio import local_files

    tops = [{"label": "home", "path": "C:\\Users\\Ana"}, {"label": "footage", "path": "\\\\nas\\footage"}]
    assert local_files.other_computer("\\\\evil\\share\\x", tops)
    assert local_files.other_computer("//evil/share/x", tops)
    assert local_files.other_computer("\\\\nas\\private\\x", tops)  # same server, another share
    assert local_files.other_computer("\\\\.\\pipe\\x", tops)
    assert not local_files.other_computer("\\\\NAS\\Footage\\2026\\a.mp4", tops)
    assert not local_files.other_computer("//nas/footage/2026", tops)
    assert not local_files.other_computer("C:\\Users\\Ana\\Videos", tops)
    assert not local_files.other_computer("/home/ana/Videos", tops)


# ------------------------------------------------------------------ FilmCraft's editor (craft/web.py, craft/ai.py)
def test_filmcraft_projects_never_send_the_editor_to_another_computer(tmp_path, monkeypatch):
    """Opening FilmCraft's editor looks up every text in the project as a possible file (the AI's titles and markers,
    a project saved from the editor): network addresses are not looked up, and the video's own files still are."""
    from clipfoundry.craft import web

    clip = tmp_path / "media" / "talk.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"x")
    folder = tmp_path / "r1" / "filmcraft"
    folder.mkdir(parents=True)
    project = folder / "edit.fcproj"
    doc = {"media": [{"File": {"path": str(clip)}}], "titles": [{"text": t} for t in NETWORK],
           "markers": [{"name": "file:////evil.example/share/m.mp4"}, {"name": "Q: why?"}]}
    project.write_text(json.dumps(doc))
    looked = _record(monkeypatch)
    got = web.session(project, tmp_path / "web-r1.json", "/api/studio/videos/v/filmcraft/files")
    assert not _evil(looked), _evil(looked)
    assert [m["name"] for m in got["media"]] == ["01-talk.mp4"]
    opened = json.loads((tmp_path / "web-r1.fcproj").read_text())
    assert opened["media"][0]["File"]["path"] == "/files/01-talk.mp4"
    assert [t["text"] for t in opened["titles"]] == NETWORK  # text stays text


@pytest.mark.parametrize("bad", ["\\/evil.example/share/x.mp4", "/\\evil.example\\share\\x.mp4",
                                 "\\evil\\x.mp4", "..\\..\\evil.mp4", "a/../../evil.mp4", "media/..",
                                 " \\\\evil.example\\share\\x.mp4"])
def test_a_saved_filmcraft_project_naming_another_computer_is_refused(tmp_path, bad):
    """A save from the editor (a project the person downloaded and opened there, say) that names another computer or
    climbs out of the folder is refused, so neither the editor nor FilmCraft's render ever opens it."""
    from clipfoundry.craft import web
    from clipfoundry.craft.runner import CraftError

    manifest = tmp_path / "web-r1.json"
    manifest.write_text(json.dumps({"media": {}, "added": {}}))
    with pytest.raises(CraftError, match="outside this video's files"):
        web.accept(json.dumps({"media": [{"File": {"path": bad}}]}).encode(), manifest)


def test_ordinary_words_in_a_saved_project_are_kept(tmp_path):
    from clipfoundry.craft import web

    manifest = tmp_path / "web-r1.json"
    manifest.write_text(json.dumps({"media": {}, "added": {}}))
    words = ["Q: why?", "A: because", "wait... what", "..", "...", "and/or", "50/50", "C: drive is full"]
    clean, need = web.accept(json.dumps({"titles": [{"text": w} for w in words]}).encode(), manifest)
    assert not need and [t["text"] for t in json.loads(clean)["titles"]] == words


@pytest.mark.parametrize("bad", ["\\/evil.example/share/x.cube", "/\\evil.example\\share\\x.cube", "\\evil.cube",
                                 "\\\\evil.example\\share\\x.cube"])
def test_ai_finishing_steps_naming_another_computer_are_refused(bad):
    """The AI's FilmCraft steps are checked before they run; the words said in a video reach its prompt, so a step
    whose text or setting names another computer is refused like one that names a file."""
    from clipfoundry.craft import ai

    for params in ({"text": bad}, {"name": bad}, {"effect": "Lumetri Color", "param": "Look", "value": bad}):
        ok, refused = ai.check_steps([{"id": "graphics.newText", "params": params}], set())
        assert not ok and refused and "names a file or address" in refused[0], params
    ok, refused = ai.check_steps([{"id": "graphics.newText", "params": {"text": "Q: why?"}}], set())
    assert ok and not refused
