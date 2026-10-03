"""Real yt-dlp extraction against a fake HTTP transport; no internet or accounts."""
import ipaddress

import httpx
import pytest

REAL_HTTP_CLIENT = httpx.Client


@pytest.fixture
def public_site(monkeypatch, tmp_path):
    from clipfoundry import db, media_import, netguard

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    routes, calls = {}, []
    client_class = httpx.Client

    def serve(request):
        calls.append(request)
        status, headers, body = routes.get(request.url.path, (404, {}, b"missing"))
        return httpx.Response(status, headers=headers, content=b"" if request.method == "HEAD" else body)

    monkeypatch.setattr(media_import.httpx, "Client",
                        lambda **kw: client_class(transport=httpx.MockTransport(serve), **kw))
    monkeypatch.setattr(netguard, "resolve", lambda host: [ipaddress.ip_address(
        host if host in ("127.0.0.1", "169.254.169.254") else "8.8.8.8")])
    return routes, calls, tmp_path


def video_page(routes, address="/movie.mp4"):
    routes["/watch"] = (200, {"Content-Type": "text/html"},
                        f'<html><head><title>Public interview</title></head><body><video controls '
                        f'src="{address}"></video></body></html>'.encode())


def test_real_extractor_imports_html_video_and_queues_local_work(public_site):
    from clipfoundry import db, media_import
    from clipfoundry.autopilot import access, host, intake, queue, rights

    routes, calls, _ = public_site
    video_page(routes)
    routes["/movie.mp4"] = (200, {"Content-Type": "video/mp4"}, b"public video")
    metadata = media_import.inspect_video("https://public.example/watch")
    assert "Public interview" in metadata["title"] and metadata["kind"] == "recorded"
    added = intake.add("https://public.example/watch")["item"]
    host.WorkerHost(periodic=False)
    row = queue.claim("source_scout", "test")
    intake.identify_link(host.Job(row, "test"))
    source = db.fetch("sources", added["id"])
    assert access.resolve(source, db.get_settings())["method"] == "webpage"
    assert rights.local_allowed(source) and not rights.evaluate(source)["auto_allowed"]
    assert any(j["kind"] == "hunt_source" for j in queue.jobs())
    assert all(str(r.url.host) == "8.8.8.8" and r.headers["host"] == "public.example" for r in calls)


def test_completed_download_only_is_promoted_to_project_source(public_site):
    from clipfoundry import db, jobs
    from clipfoundry.pipeline.common import JobContext

    routes, calls, tmp_path = public_site
    video_page(routes)
    content = b"public video bytes"
    routes["/movie.mp4"] = (200, {"Content-Type": "video/mp4", "Content-Length": str(len(content))}, content)
    pdir = tmp_path / "project"
    pdir.mkdir()
    project = db.create_project("Imported", source_path=str(pdir / "source.mp4"))
    jobs.download_url(project["id"], "https://public.example/watch", JobContext(), max_bytes=1000)
    assert (pdir / "source.mp4").read_bytes() == content
    assert db.get_project(project["id"])["source_path"] == str(pdir / "source.mp4")
    assert calls


@pytest.mark.parametrize("address", ["http://127.0.0.1/private.mp4", "http://169.254.169.254/private.mp4"])
def test_embedded_private_video_never_reaches_transport(public_site, address):
    from clipfoundry import media_import, netguard

    routes, calls, _ = public_site
    video_page(routes, address)
    with pytest.raises((media_import.MediaUnavailable, netguard.UnsafeUrl)):
        media_import.inspect_video("https://public.example/watch")
    assert not any(r.url.path == "/private.mp4" for r in calls)


def test_private_redirect_is_checked_before_following(public_site):
    from clipfoundry import media_import, netguard

    routes, calls, _ = public_site
    routes["/watch"] = (302, {"Location": "http://127.0.0.1/private"}, b"")
    with media_import.public_extractor() as ydl:
        with pytest.raises(netguard.UnsafeUrl):
            ydl.urlopen("https://public.example/watch")
    assert len(calls) == 1


def test_size_limit_counts_unknown_length_across_requests(public_site):
    from clipfoundry import media_import

    routes, _, _ = public_site
    routes["/movie.mp4"] = (200, {"Content-Type": "video/mp4"}, b"123456")
    with media_import.public_extractor(max_bytes=10) as ydl:
        ydl.fetching_media = True
        with ydl.urlopen("https://public.example/movie.mp4") as response:
            assert response.read() == b"123456"
        with ydl.urlopen("https://public.example/movie.mp4") as response:
            with pytest.raises(Exception, match="size limit"):
                response.read()


def test_retry_after_is_not_shortened(public_site):
    from clipfoundry import media_import
    from clipfoundry.autopilot import queue

    routes, _, _ = public_site
    routes["/watch"] = (429, {"Retry-After": "7200"}, b"")
    with media_import.public_extractor() as ydl:
        with pytest.raises(queue.Wait) as waited:
            ydl.urlopen("https://public.example/watch")
    assert waited.value.seconds == 7200


def test_website_cookies_are_not_forwarded_between_pinned_hosts(public_site):
    from clipfoundry import media_import

    routes, calls, _ = public_site
    routes["/watch"] = (302, {"Location": "https://other.example/movie.mp4",
                             "Set-Cookie": "session=private; Path=/"}, b"")
    routes["/movie.mp4"] = (200, {"Content-Type": "video/mp4"}, b"1234")
    with media_import.public_extractor() as ydl:
        with ydl.urlopen("https://public.example/watch") as response:
            assert response.read() == b"1234"
    assert len(calls) == 2 and not any("cookie" in request.headers for request in calls)


def test_automatic_public_selection_grants_no_reuse_and_respects_opt_out_and_blocks(public_site):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout

    settings = db.get_settings()
    assert settings["autopilot_public_videos"] is True
    source = db.insert("sources", {"platform": "url", "external_id": "interview", "signal_id": "search",
                                   "url": "https://public.example/watch", "title": "Interview podcast",
                                   "expected_clips": 5, "source_score": 80, "status": "discovered"})
    source = rights.apply(source, settings)
    assert source["status"] == "eligible" and not rights.evaluate(source)["auto_allowed"]
    assert scout.select_for_today(settings)[0]["id"] == source["id"]
    assert not rights.local_allowed(source, settings={**settings, "autopilot_public_videos": False})
    rights.add_rule("source", source["id"], rights.BLOCKED, "Do not use")
    assert not rights.local_allowed(source, settings=settings)
    with pytest.raises(rights.RightsBlocked):
        rights.gate(source, "publish", settings)


def test_default_mode_queues_platform_video_without_manual_sources(public_site, monkeypatch):
    from fake_platforms import FakeGoogle
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, rights
    from clipfoundry.publish import youtube

    # This uses the platform API stand-in directly, independently of the webpage transport fixture.
    monkeypatch.setattr(httpx, "Client", REAL_HTTP_CLIENT)
    _, _, tmp_path = public_site
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "fresh-data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    db.init()
    fake = FakeGoogle()
    try:
        monkeypatch.setattr(youtube, "API_URL", fake.url + "/youtube/v3")
        db.save_settings({"youtube_api_key": fake.api_key, "autopilot_enabled": True,
                          "library_discovery": False})
        fake.add_video("publicvideo1", "Podcast interview", channel="UCother0000000001", duration="PT30M")
        fake.popular = ["publicvideo1"]
        host.WorkerHost(periodic=False)
        for kind in ("trend_scan", "source_scout"):
            job = queue.enqueue(kind)
            host.HANDLERS[kind](host.Job(job, "test"))
        source = db.select("sources", "external_id = ?", ("publicvideo1",))[0]
        assert source["status"] == "queued" and source["rights_status"] == rights.MANUAL
        assert any(j["kind"] == "hunt_source" and j["ref_id"] == source["id"] for j in queue.jobs())
        assert not db.select("source_feeds") and not db.select("source_rights")
        assert not rights.evaluate(source)["auto_allowed"]
    finally:
        fake.stop()


def test_web_search_uses_existing_budget_and_returns_webpage_sources(public_site, monkeypatch):
    from clipfoundry.autopilot import providers, scout

    ws = providers.WebSearch({"tavily_api_key": "fake", "autopilot_public_videos": True})
    searches = []

    def search(query, domains, max_results, time_range):
        searches.append(domains)
        return [] if domains else [{"url": "https://public.example/watch", "title": "Interview"},
                                   {"url": "https://youtu.be/abc12345678?si=tracking", "title": "Podcast"}]

    monkeypatch.setattr(ws, "search", search)
    signals = ws.discover(["podcast"], None)
    assert [] in searches and ["tiktok.com"] in searches
    source = scout.source_from_signal({**signals[0], "id": "search-result"})
    assert source["access"]["webpage"] and source["channel_id"] == ""
    assert signals[1]["platform"] == "youtube" and signals[1]["external_id"] == "abc12345678"
    assert signals[1]["url"] == "https://www.youtube.com/watch?v=abc12345678"


def test_recorded_hls_webpage_imports_real_media_through_guard(public_site):
    import subprocess
    from synthetic_media import make_video

    from clipfoundry import db, jobs
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    routes, calls, tmp_path = public_site
    original = make_video(tmp_path / "original.mp4", seconds=2)
    playlist = tmp_path / "recorded.m3u8"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(original), "-c", "copy", "-hls_time", "1",
                    "-hls_list_size", "0", str(playlist)], check=True, capture_output=True)
    video_page(routes, "/recorded.m3u8")
    routes["/recorded.m3u8"] = (200, {"Content-Type": "application/vnd.apple.mpegurl"}, playlist.read_bytes())
    for segment in tmp_path.glob("recorded*.ts"):
        routes["/" + segment.name] = (200, {"Content-Type": "video/mp2t"}, segment.read_bytes())
    pdir = tmp_path / "project"
    pdir.mkdir()
    project = db.create_project("Recorded HLS", source_path=str(pdir / "source.mp4"))
    jobs.download_url(project["id"], "https://public.example/watch", JobContext(), max_bytes=10_000_000)
    output = db.get_project(project["id"])["source_path"]
    assert 1.9 <= probe(output)["duration"] <= 2.2
    assert any(r.url.path.endswith(".ts") for r in calls)
    assert all(r.url.host == "8.8.8.8" for r in calls)
