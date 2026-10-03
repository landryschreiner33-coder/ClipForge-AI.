"""Public HLS resources stay behind the DNS-pinned URL guard, including inside ffmpeg."""
from __future__ import annotations

import gzip
import ipaddress
import re
import shutil
import subprocess
import httpx
import pytest

from clipfoundry import netguard
from clipfoundry.autopilot import stream_access


@pytest.fixture()
def internet(monkeypatch):
    routes, requests = {}, []

    def resolve(host):
        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return [ipaddress.ip_address("8.8.8.8")]

    def transport(request):
        # Production open_checked is exercised: the target is pinned, while Host retains the checked authority.
        assert request.url.host == "8.8.8.8"
        original = f"{request.url.scheme}://{request.headers['host']}{request.url.raw_path.decode()}"
        requests.append((original, request.headers.get("range")))
        reply = routes.get(original)
        if reply is None:
            return httpx.Response(404)
        if callable(reply):
            return reply(request)
        return httpx.Response(reply[0], headers=reply[1], content=reply[2])

    monkeypatch.setattr(netguard, "resolve", resolve)
    monkeypatch.setattr(stream_access, "client", lambda _: httpx.Client(transport=httpx.MockTransport(transport)))
    return routes, requests


def fetch(url, **kwargs):
    # This client reaches the real local relay; only its upstream transport is fake.
    with httpx.Client(trust_env=False) as local:
        return local.get(url, **kwargs)


def playlist(body):
    return 200, {"Content-Type": "application/vnd.apple.mpegurl"}, body.encode()


@pytest.mark.parametrize("resource", ["http://127.0.0.1:8765/api/autopilot/status", "http://[::1]/video.ts",
                                       "http://169.254.169.254/latest", "http://192.168.1.1/key",
                                       "file:///tmp/private.ts", "data:video/mp2t;base64,aaaa"])
def test_manifest_cannot_send_ffmpeg_to_private_or_non_http_resources(internet, resource):
    routes, requests = internet
    routes["https://video.example/live.m3u8"] = playlist(f"#EXTM3U\n#EXTINF:1,\n{resource}\n")
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        answer = fetch(relay.url)
        assert answer.status_code == 502
        assert "safe public HTTP" in relay.error()
        assert resource not in answer.text
    assert len(requests) == 1


def test_every_redirect_is_checked_and_signed_addresses_are_not_exposed(internet):
    routes, requests = internet
    signed = "https://video.example/part.ts?secret=private-signature"
    routes["https://video.example/live.m3u8"] = playlist(f"#EXTM3U\n#EXTINF:1,\n{signed}\n")
    routes[signed] = (302, {"Location": "http://127.0.0.1:8765/secret"}, b"")
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        root = fetch(relay.url)
        assert root.status_code == 200 and "private-signature" not in root.text
        address = next(line for line in root.text.splitlines() if line.startswith("http://"))
        answer = fetch(address)
        assert answer.status_code == 502
        assert "private-signature" not in answer.text + relay.error()
    assert [r[0] for r in requests] == ["https://video.example/live.m3u8", signed]


def test_nested_playlists_key_map_and_media_uris_are_all_relayed(internet):
    routes, requests = internet
    routes["https://video.example/start.m3u8"] = (302, {"Location": "/dir/master.m3u8"}, b"")
    routes["https://video.example/dir/master.m3u8"] = playlist(
        '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=200000\nchild.m3u8\n')
    routes["https://video.example/dir/child.m3u8"] = playlist(
        '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin",KEYFORMAT="identity"\n'
        '#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\npart.ts\n#EXT-X-ENDLIST\n')
    for name in ("key.bin", "init.mp4", "part.ts"):
        routes["https://video.example/dir/" + name] = (200, {"Content-Type": "application/octet-stream"}, b"media")
    with stream_access.PublicStream("https://video.example/start.m3u8") as relay:
        root = fetch(relay.url)
        child = fetch(root.text.splitlines()[-1])
        assert root.status_code == child.status_code == 200
        assert "video.example" not in root.text + child.text
        resources = re.findall(r'URI="([^"]+)"', child.text) + [child.text.splitlines()[-2]]
        assert len(resources) == 3
        assert all(fetch(address).content == b"media" for address in resources)
    assert all(url.startswith("https://video.example/") for url, _ in requests)


@pytest.mark.parametrize("line", ['#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key.bin"',
                                  '#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="com.apple.streamingkeydelivery",URI="key.bin"',
                                  '#EXT-X-SESSION-KEY:METHOD=AES-128,KEYFORMAT=drm,URI="key.bin"',
                                  '#EXT-X-DEFINE:NAME="unsafe",VALUE="anything"',
                                  '#EXT-X-CONTENT-STEERING:SERVER-URI="other.json"',
                                  '#EXT-X-MAP:URI=http://192.168.1.1/private'])
def test_protected_or_unsupported_manifests_fail_closed(internet, line):
    routes, _ = internet
    routes["https://video.example/live.m3u8"] = playlist(f"#EXTM3U\n{line}\npart.ts\n")
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        assert fetch(relay.url).status_code == 502
        assert relay.error()


def test_dash_and_oversize_playlists_fail_with_clear_limits(internet, monkeypatch):
    routes, _ = internet
    with pytest.raises(stream_access.StreamRefused, match="DASH"):
        stream_access.PublicStream("https://video.example/live.mpd")
    routes["https://video.example/unknown"] = (200, {"Content-Type": "application/dash+xml"}, b"<MPD/>")
    with stream_access.PublicStream("https://video.example/unknown") as relay:
        assert fetch(relay.url).status_code == 502 and "DASH" in relay.error()
    monkeypatch.setattr(stream_access, "MAX_MANIFEST_BYTES", 80)
    routes["https://video.example/live.m3u8"] = playlist("#EXTM3U\n" + "#comment\n" * 20)
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        assert fetch(relay.url).status_code == 502 and "too large" in relay.error()


def test_direct_media_preserves_ranges_and_caps_total_capture_bytes(internet):
    routes, requests = internet
    routes["https://video.example/live.ts"] = (206, {"Content-Type": "video/mp2t", "Content-Range": "bytes 0-3/8"},
                                               b"1234")
    with stream_access.PublicStream("https://video.example/live.ts", max_bytes=5) as relay:
        result = fetch(relay.url, headers={"Range": "bytes=0-3"})
        assert result.status_code == 206 and result.content == b"1234"
        assert result.headers["content-range"] == "bytes 0-3/8"
        assert requests[0][1] == "bytes=0-3"
        assert fetch(relay.url).status_code == 502
        assert "size limit" in relay.error()


@pytest.mark.parametrize("ranged", [False, True])
def test_compressed_media_does_not_forward_its_encoded_content_length(internet, ranged):
    routes, requests = internet
    media = bytes(range(256)) * 8
    encoded = gzip.compress(media)
    headers = {"Content-Type": "video/mp2t", "Content-Encoding": "gzip", "Content-Length": str(len(encoded))}
    if ranged:
        headers["Content-Range"] = f"bytes 0-{len(encoded) - 1}/{len(encoded)}"

    def compressed(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(206 if ranged else 200, headers=headers, content=encoded)

    routes["https://video.example/live.ts"] = compressed
    with stream_access.PublicStream("https://video.example/live.ts") as relay:
        result = fetch(relay.url, headers={"Range": f"bytes=0-{len(encoded) - 1}"} if ranged else {})
        if ranged:
            assert result.status_code == 502 and "compressed byte range" in relay.error()
        else:
            assert result.status_code == 200 and result.content == media
            assert not relay.error()
    assert len(requests) == 1


def test_opaque_tokens_are_bounded_and_shutdown_is_idempotent(internet, monkeypatch):
    routes, requests = internet
    monkeypatch.setattr(stream_access, "MAX_TOKENS", 3)
    routes["https://video.example/live.m3u8"] = playlist("#EXTM3U\n" + "\n".join(f"part{x}.ts" for x in range(8)))
    relay = stream_access.PublicStream("https://video.example/live.m3u8")
    try:
        assert fetch(relay.url).status_code == 200
        assert len(relay._tokens) == len(relay._reverse) == 3
        assert fetch(relay.url).status_code == 200  # token eviction never loses the recording's playlist entry point
        assert fetch(relay._base + "/https://private.example/key").status_code == 404
        assert len(requests) == 2
    finally:
        relay.close()
        relay.close()
    assert not relay._thread.is_alive()


def test_retry_after_blocks_later_resource_requests(internet):
    routes, requests = internet
    routes["https://video.example/live.ts"] = (503, {"Retry-After": "600"}, b"Unavailable")
    deadlines = []
    with stream_access.PublicStream("https://video.example/live.ts", on_retry=deadlines.append) as relay:
        assert fetch(relay.url).status_code == 502
        second = fetch(relay.url)
        assert second.status_code == 503 and int(second.headers["retry-after"]) >= 599
        assert deadlines == [relay.retry_until()] and deadlines[0] > stream_access.time.time() + 590
    assert len(requests) == 1


@pytest.mark.parametrize("encrypted", [False, True])
def test_real_ffmpeg_reads_a_rewritten_synthetic_hls_stream(internet, tmp_path, encrypted):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is not installed")
    encryption = []
    if encrypted:
        (tmp_path / "key.bin").write_bytes(b"0123456789abcdef")
        (tmp_path / "key-info.txt").write_text("key.bin\n" + str(tmp_path / "key.bin") + "\n")
        encryption = ["-hls_key_info_file", str(tmp_path / "key-info.txt")]
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=96x160:r=25:d=3", "-c:v", "libx264", "-threads", "1", "-g", "25",
                    "-f", "hls", "-hls_time", "1", "-hls_list_size", "0", *encryption,
                    str(tmp_path / "live.m3u8")],
                   check=True, capture_output=True, timeout=30)
    routes, requests = internet
    for path in tmp_path.iterdir():
        kind = "application/vnd.apple.mpegurl" if path.suffix == ".m3u8" else "video/mp2t"
        routes["https://video.example/" + path.name] = (200, {"Content-Type": kind}, path.read_bytes())
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "http,tcp,crypto",
                        "-i", relay.url, "-c", "copy", str(tmp_path / "recorded.mkv")], check=True,
                       capture_output=True, timeout=30)
    assert (tmp_path / "recorded.mkv").stat().st_size > 0
    assert sum(url.endswith(".ts") for url, _ in requests) >= 3


def test_manifest_addressing_work_is_bounded_before_resolving_resources(internet, monkeypatch):
    routes, requests = internet
    monkeypatch.setattr(stream_access, "MAX_MANIFEST_RESOURCES", 3)
    routes["https://video.example/live.m3u8"] = playlist("#EXTM3U\n" + "part.ts\n" * 5)
    with stream_access.PublicStream("https://video.example/live.m3u8") as relay:
        assert fetch(relay.url).status_code == 502 and "too many resources" in relay.error()
    assert len(requests) == 1
