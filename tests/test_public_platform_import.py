"""Real yt-dlp extraction/download with a fake HTTP transport; no real platform or private network is reached."""
from __future__ import annotations

import ipaddress
import json

import httpx
import pytest
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.networking.common import Request
from yt_dlp.networking.exceptions import RequestError

from clipfoundry import db, jobs, netguard, public_import
from clipfoundry.pipeline.common import Cancelled, JobContext


@pytest.fixture()
def network(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    seen, answers = [], {}
    real_resolve = netguard.resolve

    def resolve(host):
        if host in ("video.example", "media.example", "other.example"):
            return [ipaddress.ip_address("8.8.8.8")]
        return real_resolve(host)

    def respond(request):
        seen.append(request)
        key = (request.headers["host"], request.url.path)
        return answers.get(key, httpx.Response(404))

    monkeypatch.setattr(netguard, "resolve", resolve)
    monkeypatch.setattr(public_import, "client", lambda timeout: httpx.Client(
        transport=httpx.MockTransport(respond), trust_env=False))
    return seen, answers, tmp_path


def downloader(network, **options):
    return public_import.GuardedYoutubeDL({"quiet": True, "no_warnings": True,
                                          **public_import.public_options(), **options})


def test_platform_api_post_media_redirect_and_session_cookies_are_pinned(network):
    seen, answers, _ = network
    answers["video.example", "/api"] = httpx.Response(200, json={"ok": True},
                                                       headers={"Set-Cookie": "session=anonymous; Path=/"})
    answers["video.example", "/next"] = httpx.Response(307, headers={"Location": "https://media.example/file"})
    answers["media.example", "/file"] = httpx.Response(200, content=b"public media")
    with downloader(network) as ydl:
        with ydl.urlopen(Request("https://video.example/api", data=b'{"query":"video"}',
                                 headers={"Content-Type": "application/json"})) as response:
            assert json.loads(response.read()) == {"ok": True}
        with ydl.urlopen(Request("https://video.example/next", headers={"Authorization": "anonymous-token"})) as r:
            assert r.read() == b"public media" and r.url == "https://media.example/file"
        assert set(ydl._request_director.handlers) == {"Public"}
    assert len(seen) == 3 and seen[0].method == "POST" and seen[0].content == b'{"query":"video"}'
    assert all(request.url.host == "8.8.8.8" for request in seen)
    assert [request.extensions["sni_hostname"] for request in seen] == [
        "video.example", "video.example", "media.example"]
    assert seen[1].headers["cookie"] == "session=anonymous"
    assert "cookie" not in seen[2].headers and "authorization" not in seen[2].headers


@pytest.mark.parametrize("target", ["http://127.0.0.1/private", "http://169.254.169.254/metadata",
                                     "file:///etc/passwd", "https://user:password@other.example/file"])
def test_platform_redirects_cannot_leave_the_public_guard(network, target):
    seen, answers, _ = network
    answers["video.example", "/watch"] = httpx.Response(302, headers={"Location": target})
    with downloader(network) as ydl, pytest.raises(RequestError, match="Public video access refused"):
        ydl.urlopen("https://video.example/watch")
    assert len(seen) == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1/watch", "http://169.254.169.254/metadata",
                                  "file:///etc/passwd", "https://user:password@video.example/watch"])
def test_initial_autopilot_import_refused_before_any_extractor_runs(network, monkeypatch, url):
    seen, _, _ = network
    monkeypatch.setattr(public_import.GuardedYoutubeDL, "extract_info", lambda *a, **k: pytest.fail("extractor ran"))
    with pytest.raises(netguard.UnsafeUrl):
        jobs.download_url("unused", url, JobContext(), public_only=True)
    assert not seen


class PublicVideoIE(InfoExtractor):
    _VALID_URL = r"https://video\.example/watch/(?P<id>\d+)"

    def _real_extract(self, url):
        item = self._download_json("https://video.example/api", self._match_id(url), data=b"video=1")
        return {"id": "1", "title": "Public interview", "duration": 300,
                "formats": item["formats"]}


def test_actual_yt_dlp_extractor_downloads_progressive_media_through_guard(network):
    seen, answers, path = network
    answers["video.example", "/api"] = httpx.Response(200, json={"formats": [
        {"url": "https://media.example/video.mp4", "format_id": "public", "ext": "mp4", "height": 720,
         "vcodec": "avc1", "acodec": "aac", "protocol": "https"}]})
    answers["media.example", "/video.mp4"] = httpx.Response(200, content=b"public video bytes",
                                                           headers={"Content-Length": "18"})
    with downloader(network, outtmpl=str(path / "source.%(ext)s")) as ydl:
        ydl.add_info_extractor(PublicVideoIE())
        item = ydl.extract_info("https://video.example/watch/1", download=True, ie_key="PublicVideo")
    assert item["id"] == "1" and (path / "source.mp4").read_bytes() == b"public video bytes"
    assert len(seen) == 2 and seen[0].method == "POST"
    assert seen[1].headers["host"] == "media.example"


def test_extracted_private_media_and_external_manifest_transport_are_refused(network):
    seen, _, _ = network
    with downloader(network) as ydl:
        with pytest.raises(netguard.UnsafeUrl):
            ydl.process_info({"id": "1", "title": "Video", "url": "http://127.0.0.1/private.mp4",
                              "ext": "mp4", "protocol": "http"})
        for fields in ({"protocol": "m3u8_native"}, {"protocol": "rtmp"}, {"manifest_url": "https://media.example/x"},
                       {"fragments": [{"url": "http://127.0.0.1/private"}]}, {"section_end": 10}, {"is_live": True}):
            with pytest.raises(RequestError, match="cannot be guarded"):
                ydl.process_info({"id": "1", "title": "Video", "url": "https://media.example/video.mp4",
                                  "ext": "mp4", "protocol": "https", **fields})
    assert not seen


def test_platform_import_enforces_total_bytes_and_cancellation(network):
    seen, answers, _ = network
    answers["media.example", "/file"] = httpx.Response(200, content=b"123456", headers={"Content-Length": "6"})
    with downloader(network) as ydl:
        ydl.public_budget = 5
        with pytest.raises(RequestError, match="source size limit"):
            ydl.urlopen("https://media.example/file")
    with downloader(network) as ydl:
        ydl.public_cancelled = lambda: True
        with pytest.raises(Cancelled):
            ydl.urlopen("https://media.example/file")
    assert len(seen) == 1


def test_importer_uses_guarded_downloader_only_for_public_autopilot(network, monkeypatch):
    seen, _, path = network
    project = db.create_project("Interview", source_path=str(path / "source.mp4"))
    calls = []

    def extract(ydl, url, download):
        calls.append((url, download, ydl.public_budget, ydl.params["external_downloader"]))
        (path / "source.mp4").write_bytes(b"video")
        return {"id": "1", "title": "Interview", "ext": "mp4"}

    monkeypatch.setattr(public_import.GuardedYoutubeDL, "extract_info", extract)
    jobs.download_url(project["id"], "https://video.example/watch/1", JobContext(),
                      max_bytes=1_000_000, max_seconds=600, public_only=True)
    assert calls == [("https://video.example/watch/1", True, 1_000_000, "native")]
    assert db.get_project(project["id"])["source_path"] == str(path / "source.mp4")
    assert not seen


def test_unknown_size_stream_stops_at_budget_and_rechecks_pause_before_buffered_reads(network):
    _, answers, _ = network
    answers["media.example", "/file"] = httpx.Response(200, stream=httpx.ByteStream(b"123456"))
    with downloader(network) as ydl:
        ydl.public_budget = 5
        with ydl.urlopen("https://media.example/file") as response, pytest.raises(RequestError, match="source size"):
            response.read(2)
    paused = [False]

    def cancelled():
        if paused[0]:
            from clipfoundry.autopilot import queue

            raise queue.Wait("local_permission", 30, "Local test mode is off")
        return False

    answers["media.example", "/file"] = httpx.Response(200, stream=httpx.ByteStream(b"123456"))
    with downloader(network) as ydl:
        ydl.public_cancelled = cancelled
        with ydl.urlopen("https://media.example/file") as response:
            assert response.read(1) == b"1"
            paused[0] = True
            from clipfoundry.autopilot import queue

            with pytest.raises(queue.Wait):
                response.read(1)
