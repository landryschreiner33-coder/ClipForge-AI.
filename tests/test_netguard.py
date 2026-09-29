"""URLs that come from data never reach private or local addresses, local files or unbounded downloads."""
from __future__ import annotations

import ipaddress
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from clipfoundry import netguard

HOSTS = {"public.example": ["93.184.216.34"], "lan.example": ["192.168.1.20"], "meta.example": ["169.254.169.254"],
         "mixed.example": ["93.184.216.34", "10.0.0.1"], "cgnat.example": ["100.64.1.1"]}


@pytest.fixture()
def fake_dns(monkeypatch):
    real = netguard.resolve

    def resolve(host: str):
        if host in HOSTS:
            return [ipaddress.ip_address(a) for a in HOSTS[host]]
        return real(host)

    monkeypatch.setattr(netguard, "resolve", resolve)
    return HOSTS


@pytest.mark.parametrize("url, from_data, from_you", [
    ("https://public.example/v.mp4", True, True),
    ("http://lan.example/v.mp4", False, True),        # your own network: only for addresses you typed
    ("http://127.0.0.1:8765/api/settings", False, True),
    ("http://[::1]/x", False, True),
    ("http://meta.example/latest/meta-data", False, False),  # link-local (cloud metadata): never
    ("http://mixed.example/v.mp4", False, True),      # one private answer is enough to refuse
    ("http://cgnat.example/v.mp4", False, True),
    ("http://0.0.0.0/v.mp4", False, False),
    ("http://2130706433/v.mp4", False, True),         # 127.0.0.1 written as a number
    ("file:///etc/passwd", False, False),
    ("ftp://public.example/v.mp4", False, False),
    ("https://user:pass@public.example/v.mp4", False, True),
])
def test_addresses_and_schemes(fake_dns, url, from_data, from_you):
    def ok(allow_private: bool) -> bool:
        try:
            netguard.check(url, allow_private=allow_private)
            return True
        except netguard.UnsafeUrl:
            return False

    assert (ok(False), ok(True)) == (from_data, from_you)


def test_ffmpeg_gets_network_protocols_only(fake_dns):
    args = netguard.ffmpeg_input("rtmp://public.example/live/key")
    assert args[:2] == ["-protocol_whitelist", netguard.FFMPEG_NETWORK_PROTOCOLS] and args[-2:] == \
        ["-i", "rtmp://public.example/live/key"]
    assert "file" not in netguard.FFMPEG_NETWORK_PROTOCOLS.split(",")
    for bad in ("file:/home/me/secret.mp4", "concat:/etc/passwd", "pipe:0", "data:video/mp4;base64,AAAA",
                "rtmp://lan.example/live"):
        with pytest.raises(netguard.UnsafeUrl):
            netguard.ffmpeg_input(bad)
    assert netguard.ffmpeg_input("srt://lan.example:9000", allow_private=True)  # your own encoder on your network


# ------------------------------------------------------------------ downloads through a real local server
class Handler(BaseHTTPRequestHandler):
    seen: list[tuple[str, str]] = []

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        Handler.seen.append((self.path, self.headers.get("Host", "")))
        if self.path == "/video":
            body = b"v" * 5000
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/to-video":
            self.send_response(302)
            self.send_header("Location", "/video")
            self.end_headers()
        elif self.path == "/to-metadata":
            self.send_response(302)
            self.send_header("Location", "http://meta.example/latest/meta-data")
            self.end_headers()
        elif self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
        elif self.path == "/declared-big":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(50_000_000))
            self.end_headers()
        elif self.path == "/endless":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.end_headers()  # no length: HTTP/1.0 streams until the connection closes
            try:
                for _ in range(64):
                    self.wfile.write(b"x" * 65536)
            except OSError:
                pass
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def server():
    Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", httpd.server_address[1]
    httpd.shutdown()


def _client() -> httpx.Client:
    return httpx.Client(timeout=10, follow_redirects=False, trust_env=False)


def test_downloads_follow_checked_redirects_and_stay_bounded(fake_dns, server, tmp_path):
    base, _ = server
    dst = tmp_path / "source.mp4"
    with _client() as c:
        assert netguard.download(c, f"{base}/to-video", dst, allow_private=True, max_bytes=10_000) == 5000
        assert dst.read_bytes() == b"v" * 5000
        for path, why in (("/to-metadata", "special address"), ("/loop", "redirects"),
                          ("/declared-big", "limit"), ("/endless", "limit")):
            out = tmp_path / f"{path.strip('/')}.mp4"
            with pytest.raises(netguard.UnsafeUrl, match=why):
                netguard.download(c, f"{base}{path}", out, allow_private=True, max_bytes=1_000_000)
            assert not out.exists() and not out.with_suffix(".mp4.part").exists()  # nothing half-written is left
        before = len(Handler.seen)
        with pytest.raises(netguard.UnsafeUrl):  # a URL that came from data: refused before any request is made
            netguard.download(c, f"{base}/video", tmp_path / "x.mp4", max_bytes=10_000)
        assert len(Handler.seen) == before


def test_the_connection_goes_to_the_address_that_was_checked(fake_dns, server, tmp_path, monkeypatch):
    _, port = server
    HOSTS["media.example"] = ["127.0.0.1"]  # e.g. a DNS answer; later answers cannot change where we connect
    with _client() as c:
        netguard.download(c, f"http://media.example:{port}/video", tmp_path / "v.mp4", allow_private=True,
                          max_bytes=10_000)
    assert Handler.seen[-1] == ("/video", f"media.example:{port}")  # right server, original host name
    del HOSTS["media.example"]


def test_feed_urls_cannot_reach_your_network_but_yours_can(fake_dns, server, tmp_path, monkeypatch):
    """The Clip Hunter's direct-media download, for a source you added and for one a signal feed delivered."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import hunter, queue
    from clipfoundry.pipeline.common import JobContext

    db.init()
    base, _ = server
    settings = db.get_settings()
    mine = {"id": "s1", "signal_id": "", "url": f"{base}/video"}
    hunter._http_download(mine["url"], tmp_path / "mine.mp4", JobContext(), mine, settings)  # noqa: SLF001
    assert (tmp_path / "mine.mp4").stat().st_size == 5000
    sig = db.insert("trend_signals", {"provider": "signal_feed", "platform": "feed", "external_id": "x",
                                      "title": "x", "first_seen": 0, "last_checked": 0})
    fed = {"id": "s2", "signal_id": sig["id"], "url": f"{base}/video"}
    with pytest.raises(queue.Fail, match="Not downloaded"):
        hunter._http_download(fed["url"], tmp_path / "fed.mp4", JobContext(), fed, settings)  # noqa: SLF001
    assert not (tmp_path / "fed.mp4").exists()


def test_live_capture_refuses_local_files_and_private_streams_from_feeds(fake_dns, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import live, queue

    db.init()
    settings = db.get_settings()
    sig = db.insert("trend_signals", {"provider": "signal_feed", "platform": "stream", "external_id": "y",
                                      "title": "y", "first_seen": 0, "last_checked": 0})
    for url in ("concat:/home/me/a.mp4|/home/me/b.mp4", "file:/etc/passwd", "rtmp://lan.example/live"):
        with pytest.raises(queue.Fail, match="Not captured"):
            live.input_args({"signal_id": sig["id"], "url": url}, settings)
    mine = db.insert("trend_signals", {"provider": "stream_url", "platform": "stream", "external_id": "z",
                                       "title": "z", "first_seen": 0, "last_checked": 0})
    args = live.input_args({"signal_id": mine["id"], "url": "rtmp://lan.example/live"}, settings)  # your stream
    assert "-protocol_whitelist" in args and args[-1] == "rtmp://lan.example/live"


def test_autopilot_bounds_source_size_and_length(tmp_path, monkeypatch):
    from synthetic_media import make_video

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import hunter, queue
    from clipfoundry.pipeline.common import JobContext

    db.init()
    video = make_video(tmp_path / "long.mp4", seconds=4.0)
    hunter.check_length({"source_path": str(video)}, {"autopilot_max_source_minutes": 1})
    with pytest.raises(queue.Fail, match="up to 0 min"):
        hunter.check_length({"source_path": str(video)}, {"autopilot_max_source_minutes": 0.05})

    seen = {}

    class FakeYDL:  # yt-dlp stand-in: records the options, downloads nothing (as when a limit filters the video)
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            return None

    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    project = db.create_project("p", source_path=str(tmp_path / "p" / "source.mp4"))
    (tmp_path / "p").mkdir()
    with pytest.raises(jobs.DownloadRefused, match="larger than 2.0 GB or longer than 30 min"):
        jobs.download_url(project["id"], "https://www.youtube.com/watch?v=x", JobContext(), max_bytes=2_000_000_000,
                          max_seconds=1800)
    assert seen["max_filesize"] == 2_000_000_000 and seen["match_filter"] is not None
    assert Path(tmp_path / "p").exists()
