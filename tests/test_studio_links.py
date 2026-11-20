"""Make clips from a video link (CF2-03, CF2-04): the same flow as a file, with recoverable progress and clear errors.

Real yt-dlp extraction runs against a fake HTTP transport (no internet). YouTube itself cannot be reached here, so
YouTube links are covered by normalization and by a stand-in download of a synthetic recording; the rest of the path
(request validation, frozen guidance, durable job, asset, project, pipeline hand-off) is the production code.
"""
from __future__ import annotations

import ipaddress
import subprocess
import time
from pathlib import Path

import httpx
import pytest

H = {"X-ClipFoundry": "1"}


def synthetic_video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=25:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


# ------------------------------------------------------------------ normalization (no network)
@pytest.mark.parametrize("raw", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghijkl&index=4&t=42s&si=track",
    "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ&pp=xyz",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
    "https://youtu.be/dQw4w9WgXcQ?si=abc&t=10",
    "https://www.youtube.com/live/dQw4w9WgXcQ?si=abc",
    "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    "  youtube.com/watch?v=dQw4w9WgXcQ  ",
    "youtu.be/dQw4w9WgXcQ",
])
def test_supported_youtube_variants_become_one_recording(raw):
    from clipfoundry.studio import link_import

    out = link_import.normalize(raw)
    assert out == {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "platform": "youtube",
                   "video_id": "dQw4w9WgXcQ", "title": "YouTube video dQw4w9WgXcQ"}


@pytest.mark.parametrize("raw, code", [
    ("https://www.youtube.com/playlist?list=PLabcdefghijkl", "playlist"),
    ("https://www.youtube.com/watch?list=PLabcdefghijkl", "playlist"),
    ("https://www.youtube.com/@somechannel", "channel"),
    ("https://www.youtube.com/channel/UC123", "channel"),
    ("https://www.youtube.com/watch?v=short", "not_one_video"),
    ("https://www.youtube.com/feed/trending", "not_one_video"),
    ("not a link", "invalid"),
    ("ftp://example.com/video.mp4", "invalid"),
    ("https://user:pass@example.com/video.mp4", "invalid"),
    ("", "invalid"),
])
def test_unusable_links_get_a_specific_readable_reason(raw, code):
    from clipfoundry.studio import link_import

    with pytest.raises(link_import.LinkError) as err:
        link_import.normalize(raw)
    view = err.value.view()
    assert view["code"] == code and view["label"] and view["why"] and view["fix"]


def test_other_links_drop_tracking_and_fragment_but_keep_their_own_parameters():
    from clipfoundry.studio import link_import

    out = link_import.normalize("https://Video.Example/clips/talk.mp4?id=7&utm_source=x&fbclid=y#t=4")
    assert out["url"] == "https://video.example/clips/talk.mp4?id=7" and out["platform"] == "link"


def test_classification_distinguishes_unavailable_private_restricted_and_live():
    from clipfoundry.jobs import DownloadRefused
    from clipfoundry.media_import import MediaUnavailable
    from clipfoundry.studio import link_import

    assert link_import._classify(DownloadRefused("x", "live_only")).label == "Live stream"  # noqa: SLF001
    assert link_import._classify(MediaUnavailable("gone", "not_found")).label == "Unavailable"  # noqa: SLF001
    assert link_import._classify(MediaUnavailable("p", "private")).label == "Private video"  # noqa: SLF001
    assert link_import._classify(MediaUnavailable("s", "login_required")).code == "login_required"  # noqa: SLF001
    assert link_import._classify(MediaUnavailable("g", "geo_blocked")).label == "Restricted"  # noqa: SLF001
    assert link_import._classify(MediaUnavailable("n", "network")).view()["temporary"] is True  # noqa: SLF001


# ------------------------------------------------------------------ the whole flow through the API
@pytest.fixture()
def site(monkeypatch, tmp_path):
    """A public website on a fake transport, a recorded hand-off to the clip pipeline, and the app."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import media_import, netguard
    from clipfoundry.api import app
    from clipfoundry.jobs import worker

    routes, calls = {}, []
    client_class = httpx.Client

    def serve(request):
        calls.append(request)
        status, headers, body = routes.get(request.url.path, (404, {}, b"missing"))
        return httpx.Response(status, headers=headers, content=b"" if request.method == "HEAD" else body)

    monkeypatch.setattr(media_import.httpx, "Client",
                        lambda **kw: client_class(transport=httpx.MockTransport(serve), **kw))
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address("8.8.8.8")])
    handed_off = []
    monkeypatch.setattr(worker, "submit_project", lambda pid, url=None: handed_off.append((pid, url)))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield {"client": client, "routes": routes, "calls": calls, "handed_off": handed_off, "tmp": tmp_path}


def page(routes, video: bytes, title: str = "Mountain interview") -> None:
    routes["/watch"] = (200, {"Content-Type": "text/html"},
                        f'<html><head><title>{title}</title></head><body><video controls src="/movie.mp4">'
                        f'</video></body></html>'.encode())
    routes["/movie.mp4"] = (200, {"Content-Type": "video/mp4", "Content-Length": str(len(video))}, video)


def wait_for(fn, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not reached")


def project(client, pid):
    r = client.get(f"/api/projects/{pid}", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_link_enters_the_same_pipeline_with_mode_style_and_destinations_frozen(site):
    from clipfoundry import db

    client, routes = site["client"], site["routes"]
    data = synthetic_video(site["tmp"] / "fixture.mp4").read_bytes()
    page(routes, data)
    style = client.post("/api/studio/styles", headers=H, json={"name": "Lower captions", "modes": ["full_stories"],
                        "values": {"caption_position": "bottom"}})
    assert style.status_code == 200, style.text
    body = {"url": "https://public.example/watch?utm_source=newsletter", "request_id": "req-1",
            "mode": "full_stories", "style_id": style.json()["id"], "choices": {"layout": "fit"}}
    started = client.post("/api/studio/clips", headers=H, json=body)
    assert started.status_code == 200, started.text
    pid = started.json()["id"]
    first = db.get_project(pid)
    # everything chosen on the page is frozen before anything is downloaded
    assert first["clip_mode"] == "full_stories" and first["guidance"]["values"]["layout"] == "fit"
    assert first["source_url"] == "https://public.example/watch"
    done = wait_for(lambda: site["handed_off"])
    assert done == [(pid, None)]  # handed to the normal clip pipeline as a local file, never as a URL to refetch
    p = db.get_project(pid)
    asset = db.fetch("assets", p["asset_id"])
    assert asset and asset["kind"] == "video" and Path(asset["path"]).read_bytes() == data
    assert Path(p["source_path"]).read_bytes() == data and p["name"].startswith("Mountain interview")
    assert p["clip_mode"] == "full_stories" and p["guidance"] == first["guidance"]
    view = project(client, pid)
    assert view["link_import"]["status"] == "done" and view["link_import"]["asset_id"] == asset["id"]
    # the same request again (a second click, a refreshed page) is the same project, not a second download
    again = client.post("/api/studio/clips", headers=H, json=body)
    assert again.json()["id"] == pid and again.json()["already_started"] is True
    assert len(db.select("link_imports")) == 1
    assert not list((Path(db.config.data_dir()) / "link-imports").iterdir())  # no partial files left


def test_upload_request_is_validated_before_any_download(site):
    from clipfoundry import db

    r = site["client"].post("/api/studio/clips", headers=H, json={
        "url": "https://public.example/watch", "mode": "highlights",
        "upload": {"intent": "make_and_upload", "destinations": []}})
    assert r.status_code == 422 and "Choose at least one account" in r.json()["detail"]
    assert not db.select("projects") and not site["calls"]


def test_bad_links_are_refused_with_the_reason_and_nothing_starts(site):
    from clipfoundry import db

    r = site["client"].post("/api/studio/clips", headers=H, json={
        "url": "https://www.youtube.com/playlist?list=PLabcdefghijkl", "mode": "highlights"})
    assert r.status_code == 422 and r.json()["problem"]["code"] == "playlist"
    check = site["client"].get("/api/studio/link-check", params={"url": "https://youtu.be/dQw4w9WgXcQ?t=3"}).json()
    assert check["ok"] and check["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    both = site["client"].post("/api/studio/clips", headers=H, json={"url": "https://public.example/watch",
                                                                     "asset_id": "as-x", "mode": "highlights"})
    assert both.status_code == 422
    assert not db.select("projects") and not site["calls"]


def test_unavailable_link_fails_readably_then_retry_succeeds_once(site):
    from clipfoundry import db

    client, routes = site["client"], site["routes"]
    r = client.post("/api/studio/clips", headers=H, json={"url": "https://public.example/watch",
                                                          "mode": "highlights", "request_id": "req-2"})
    pid = r.json()["id"]
    failed = wait_for(lambda: (lambda p: p if p["status"] == "error" else None)(project(client, pid)))
    problem = failed["link_import"]["problem"]
    assert problem["label"] and problem["fix"] and failed["message"] == problem["label"]
    assert not site["handed_off"]
    page(routes, synthetic_video(site["tmp"] / "fixture.mp4").read_bytes())
    retried = client.post(f"/api/projects/{pid}/process", headers=H, json={})
    assert retried.status_code == 200, retried.text
    wait_for(lambda: site["handed_off"])
    assert site["handed_off"] == [(pid, None)]
    # The hand-off happens inside the second job, just before the job is marked done: wait for that too.
    rounds = wait_for(lambda: (lambda jobs: jobs if len(jobs) == 2 and {j["status"] for j in jobs} == {"done"}
                               else None)(db.select("studio_jobs", "kind = 'link_import'")), timeout=10)
    assert len(rounds) == 2
    assert db.get_project(pid)["asset_id"]


def test_youtube_link_needs_no_search_key_and_keeps_its_mode(site, monkeypatch):
    """No discovery or search credential is consulted: the one recording is downloaded as supplied."""
    from clipfoundry import db
    from clipfoundry.studio import link_import

    assert not db.get_settings().get("youtube_api_key")
    asked = []
    video = synthetic_video(site["tmp"] / "yt.mp4")

    def fetch(url, staging, progress, cancelled):
        asked.append(url)
        staging.mkdir(parents=True, exist_ok=True)
        out = staging / "source.mp4"
        out.write_bytes(video.read_bytes())
        progress(50, 100, "50%")
        return out, {"title": "My summit story", "duration": 2.0}

    monkeypatch.setattr(link_import, "fetch", fetch)
    r = site["client"].post("/api/studio/clips", headers=H, json={
        "url": "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdefghijkl&index=2", "mode": "full_stories"})
    pid = r.json()["id"]
    wait_for(lambda: site["handed_off"])
    assert asked == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]  # only this video, never the playlist
    p = db.get_project(pid)
    assert p["clip_mode"] == "full_stories" and p["name"] == "My summit story"
    assert p["info"]["link"]["video_id"] == "dQw4w9WgXcQ"


def test_cancel_while_downloading_stops_and_cleans_partial_files(site, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import link_import

    started = []

    def slow_fetch(url, staging, progress, cancelled):
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "source.mp4.part").write_bytes(b"partial")
        started.append(True)
        while not cancelled():
            progress(1, 100, "1%")
            time.sleep(0.05)
        from clipfoundry.pipeline.common import Cancelled

        raise Cancelled()

    monkeypatch.setattr(link_import, "fetch", slow_fetch)
    client = site["client"]
    pid = client.post("/api/studio/clips", headers=H, json={"url": "https://public.example/watch",
                                                            "mode": "highlights"}).json()["id"]
    wait_for(lambda: started)
    assert project(client, pid)["status"] == "importing"
    assert client.post(f"/api/projects/{pid}/cancel", headers=H).status_code == 200
    wait_for(lambda: db.select("studio_jobs", "kind = 'link_import' AND status = 'canceled' AND lease_token = ''"))
    assert db.get_project(pid)["status"] == "cancelled" and not site["handed_off"]
    assert not list(link_import.imports_dir().iterdir())


def test_interrupted_import_continues_after_restart_without_a_second_project(monkeypatch, tmp_path):
    """A download that was running when the app stopped is picked up again by the durable job after a restart."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.jobs import worker
    from clipfoundry.studio import jobs as studio_jobs, link_import

    handed_off = []
    monkeypatch.setattr(worker, "submit_project", lambda pid, url=None: handed_off.append(pid))
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: None)  # "the app stops" before the job runs
    video = synthetic_video(tmp_path / "v.mp4")

    def fetch(url, staging, progress, cancelled):
        staging.mkdir(parents=True, exist_ok=True)
        out = staging / "source.mp4"
        out.write_bytes(video.read_bytes())
        return out, {"title": "Resumed"}

    monkeypatch.setattr(link_import, "fetch", fetch)
    db.init()
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        pid = client.post("/api/studio/clips", headers=H, json={"url": "https://public.example/watch",
                                                                "mode": "highlights"}).json()["id"]
    job = db.select("studio_jobs", "kind = 'link_import'")[0]
    db.update("studio_jobs", job["id"], status="running", lease_token="dead", lease_until=0)  # crashed mid-way
    ran = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: ran.append(job_id) or studio_jobs.run(job_id))
    assert studio_jobs.recover() == 1
    assert ran == [job["id"]] and handed_off == [pid]
    assert db.get_project(pid)["status"] != "importing" and len(db.select("projects")) == 1


def test_a_link_downloaded_again_for_a_project_is_that_projects_own_when_it_is_deleted(site):
    """Two clips projects made from one link: the second download has the same bytes, so ClipForge gives the second
    project the copy it has, noting that it went to that project. The first project is deleted (the second still has
    the copy); the second is deleted from a window opened while its video was still downloading. That hand-out was the
    project's own, so the copy goes with it instead of staying with nothing naming it."""
    from clipfoundry import db
    from clipfoundry.studio import project_delete

    client, routes = site["client"], site["routes"]
    page(routes, synthetic_video(site["tmp"] / "fixture.mp4").read_bytes())

    def made(request_id: str) -> str:
        pid = client.post("/api/studio/clips", headers=H, json={"url": "https://public.example/watch",
                                                                "mode": "highlights", "request_id": request_id}
                          ).json()["id"]
        wait_for(lambda: (pid, None) in site["handed_off"])
        wait_for(lambda: all(j["status"] == "done" for j in db.select("studio_jobs", "kind = 'link_import'")))
        return pid

    first = made("req-first")
    window = time.time()  # the second project's window, opened while its video downloads
    time.sleep(0.01)
    second = made("req-second")
    asset_id = db.get_project(second)["asset_id"]
    assert asset_id == db.get_project(first)["asset_id"]
    assert db.scalar("SELECT project_id FROM asset_hand_outs WHERE asset_id = ?", (asset_id,)) == second
    project_delete.delete("local", first, "clips")
    assert db.fetch("assets", asset_id)  # the second project has it
    out = project_delete.delete("local", second, "clips", as_of=window)
    assert out["counts"]["files_kept"] == 0, out["stays"]
    assert db.fetch("assets", asset_id) is None
