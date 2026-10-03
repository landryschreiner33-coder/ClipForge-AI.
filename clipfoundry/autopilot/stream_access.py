"""A private relay that keeps ffmpeg's public HTTP streams behind the URL guard.

ffmpeg follows playlist resources and redirects itself. Handing it a checked public URL alone would let a public
playlist send it into the user's network. The recorder instead receives opaque loopback URLs; every upstream
request is DNS pinned and every HLS resource is rewritten through this relay. Original (possibly signed) URLs
never appear in HTTP logs or failure messages.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .. import netguard
from ..publish.common import client, retry_after

MAX_MANIFEST_BYTES = 2 << 20
MAX_RESOURCE_BYTES = 8 << 30
MAX_TOKENS = 4096
MAX_MANIFEST_RESOURCES = 2048
MAX_MANIFEST_HOSTS = 64
HLS_TYPES = {"application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl"}
URI_ATTR = re.compile(r'(?<![\w-])URI\s*=\s*"([^"\r\n]*)"', re.IGNORECASE)
RANGE = re.compile(r"bytes=(?:\d+-\d*|-\d+)")


class StreamRefused(ValueError):
    """A safe, user-facing stream-access refusal, without the original address."""


def _public(url: str) -> None:
    try:
        netguard.check(url, allow_private=False)
        if len(url) > 16384 or any(ord(c) < 32 for c in url):
            raise ValueError()
    except (ValueError, OSError):
        raise StreamRefused("The stream contains an address that is not a safe public HTTP address.") from None


def _effective_url(response: httpx.Response) -> str:
    # open_checked substitutes the connection address, while Host retains the checked URL's actual authority.
    parts = urlsplit(str(response.url))
    host = response.request.headers.get("host") or parts.netloc
    return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))


class PublicStream:
    """An ephemeral, bounded HTTP/HLS relay. Keep it alive until its recording process has stopped."""

    def __init__(self, url: str, max_bytes: int = MAX_RESOURCE_BYTES,
                 on_retry: Callable[[float], None] | None = None):
        _public(url)
        if urlsplit(url).path.lower().endswith(".mpd"):
            raise StreamRefused("DASH streams are not supported for safe live capture. Use a public HLS stream.")
        self._lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._tokens: OrderedDict[str, str] = OrderedDict()
        self._reverse: dict[str, str] = {}
        self._clients: set[httpx.Client] = set()
        self._closed = threading.Event()
        self._error = ""
        self._retry_at = 0.0
        self._on_retry = on_retry
        self._max_bytes = max(1, int(max_bytes))
        self._bytes = 0
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler callback
                relay._serve(self)

            def log_message(self, *_):
                pass  # request paths are opaque, and upstream signed addresses are never logged

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self._base = f"http://127.0.0.1:{self._server.server_port}"
        self.url = self._map(url, checked=True)
        self._root_token = self.url[len(self._base):]
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.1},
                                        daemon=True, name="cf-public-stream")
        self._thread.start()

    def _map(self, url: str, checked: bool = False) -> str:
        if not checked:
            _public(url)
        with self._lock:
            token = self._reverse.get(url)
            if token:
                self._tokens.move_to_end(token)
                return self._base + token
            # The suffix helps ffmpeg recognize playlists and segment containers, without exposing their names.
            suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
            suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ""
            token = "/" + secrets.token_urlsafe(32) + suffix
            self._tokens[token] = url
            self._reverse[url] = token
            while len(self._tokens) > MAX_TOKENS:
                old, address = self._tokens.popitem(last=False)
                if old == getattr(self, "_root_token", ""):
                    self._tokens[old] = address
                    continue  # periodic playlist reloads must keep their original entry point for long recordings
                self._reverse.pop(address, None)
            return self._base + token

    def _playlist(self, body: bytes, base: str) -> bytes:
        if len(body) > MAX_MANIFEST_BYTES:
            raise StreamRefused("The stream playlist is too large to read safely.")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeError:
            raise StreamRefused("The stream playlist could not be read.") from None
        if not text.lstrip().startswith("#EXTM3U"):
            raise StreamRefused("The stream did not return a supported HLS playlist.")
        resource_count = sum(bool(line.strip()) and not line.strip().startswith("#") for line in text.splitlines())
        resource_count += len(re.findall(r"(?<![\w-])URI\s*=", text, re.IGNORECASE))
        if resource_count > MAX_MANIFEST_RESOURCES:
            raise StreamRefused("The stream playlist contains too many resources to read safely.")
        lines = []
        checked_hosts = set()
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith(("#EXT-X-DEFINE", "#EXT-X-CONTENT-STEERING")):
                raise StreamRefused("This HLS playlist uses unsupported stream addressing.")
            if line.startswith(("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:")):
                method = re.search(r"(?:^|,)METHOD=([^,]+)", line.partition(":")[2], re.IGNORECASE)
                fmt = re.search(r'(?:^|,)KEYFORMAT="([^"]*)"', line.partition(":")[2], re.IGNORECASE)
                if not method or method.group(1).upper() not in ("NONE", "AES-128") or \
                        (fmt and fmt.group(1).lower() != "identity") or \
                        ("KEYFORMAT=" in line.upper() and fmt is None):
                    raise StreamRefused("Protected or DRM streams cannot be captured.")

            def resource(value: str) -> str:
                if self._closed.is_set():
                    raise StreamRefused("The stream recording stopped.")
                if "{$" in value:
                    raise StreamRefused("This HLS playlist uses unsupported stream addressing.")
                target = urljoin(base, value)
                parts = urlsplit(target)
                host = (parts.scheme.lower(), parts.netloc.lower())
                # DNS is checked once per authority while rewriting; the eventual GET always checks it again and
                # pins the connection. Large playlists must not multiply the same DNS lookup thousands of times.
                if host not in checked_hosts:
                    if len(checked_hosts) >= MAX_MANIFEST_HOSTS:
                        raise StreamRefused("The stream playlist refers to too many servers to read safely.")
                    _public(target)
                    checked_hosts.add(host)
                if len(target) > 16384 or any(ord(c) < 32 for c in target):
                    raise StreamRefused("The stream playlist contains an unreadable resource address.")
                return self._map(target, checked=True)

            if line and not line.startswith("#"):
                raw = resource(line)
            elif re.search(r"(?<![\w-])URI\s*=", raw, re.IGNORECASE):
                matches = list(URI_ATTR.finditer(raw))
                if len(matches) != len(re.findall(r"(?<![\w-])URI\s*=", raw, re.IGNORECASE)):
                    raise StreamRefused("The stream playlist contains an unreadable resource address.")
                raw = URI_ATTR.sub(lambda m: 'URI="' + resource(m.group(1)) + '"', raw)
            lines.append(raw)
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _count(self, size: int) -> None:
        with self._lock:
            self._bytes += size
            if self._bytes > self._max_bytes:
                raise StreamRefused("The live stream reached the configured download size limit.")

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        with self._lock:
            url = self._tokens.get(handler.path)
            if url:
                self._tokens.move_to_end(handler.path)
        if not url or self._closed.is_set():
            handler.send_error(404, "Stream resource no longer available")
            return
        response = None
        upstream = client(30)
        sent = False
        try:
            with self._lock:
                if self._closed.is_set():
                    return
                self._clients.add(upstream)
                remaining = self._retry_at - time.time()
            if remaining > 0:
                handler.send_response(503)
                handler.send_header("Retry-After", str(max(1, int(remaining + 1))))
                handler.end_headers()
                return
            headers = {"Accept-Encoding": "identity"}  # byte ranges and media lengths describe unencoded bytes
            wanted = handler.headers.get("Range")
            if wanted:
                if not RANGE.fullmatch(wanted):
                    raise StreamRefused("The stream requested an unsupported byte range.")
                headers["Range"] = wanted
            response = netguard.open_checked(upstream, url, headers=headers)
            if response.status_code not in (200, 206):
                asked = retry_after(response)
                if asked is not None and (response.status_code == 429 or response.status_code >= 500):
                    with self._lock:
                        self._retry_at = max(self._retry_at, time.time() + asked)
                        deadline = self._retry_at
                        if self._on_retry:
                            self._on_retry(deadline)  # serialize durable writes with concurrent resource waits
                raise StreamRefused("The video server could not provide this stream resource.")
            content = response.headers.get("content-type", "").lower().split(";", 1)[0]
            base = _effective_url(response)
            declared = int(response.headers.get("content-length") or 0)
            if declared < 0 or declared > MAX_RESOURCE_BYTES:
                raise StreamRefused("The stream resource exceeds the safe download limit.")
            encoded = response.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity")
            if encoded:
                if response.status_code == 206 or response.headers.get("content-range"):
                    raise StreamRefused("The stream returned a compressed byte range that cannot be read safely.")
                # httpx decodes iter_bytes even if a server ignores Accept-Encoding. Its compressed length would
                # truncate the decoded media at our local HTTP client; close-delimited streaming remains bounded.
                declared = 0
            chunks = response.iter_bytes(65536)
            first = next(chunks, b"")
            self._count(len(first))
            sniff = first.lstrip(b"\xef\xbb\xbf \t\r\n")
            if content == "application/dash+xml" or urlsplit(base).path.lower().endswith(".mpd") or \
                    re.search(br"<(?:\w+:)?MPD(?:\s|>)", sniff[:4096]):
                raise StreamRefused("DASH streams are not supported for safe live capture. Use a public HLS stream.")
            playlist = content in HLS_TYPES or urlsplit(base).path.lower().endswith(".m3u8") or \
                sniff.startswith(b"#EXTM3U")
            if playlist:
                data = bytearray(first)
                for chunk in chunks:
                    if self._closed.is_set():
                        return
                    self._count(len(chunk))
                    data.extend(chunk)
                    if len(data) > MAX_MANIFEST_BYTES:
                        raise StreamRefused("The stream playlist is too large to read safely.")
                data = self._playlist(bytes(data), base)
                handler.send_response(200)
                handler.send_header("Content-Type", "application/vnd.apple.mpegurl")
                handler.send_header("Content-Length", str(len(data)))
                handler.end_headers()
                sent = True
                handler.wfile.write(data)
                return
            handler.send_response(response.status_code)
            handler.send_header("Content-Type", content or "application/octet-stream")
            if declared:
                handler.send_header("Content-Length", str(declared))
            if response.headers.get("content-range"):
                handler.send_header("Content-Range", response.headers["content-range"])
            handler.end_headers()
            sent = True
            total = len(first)
            handler.wfile.write(first)
            for chunk in chunks:
                if self._closed.is_set():
                    break
                self._count(len(chunk))
                total += len(chunk)
                if total > MAX_RESOURCE_BYTES:
                    raise StreamRefused("The stream resource exceeds the safe download limit.")
                handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the recorder may finish reading or stop before the upstream resource ends
        except Exception as exc:  # failures stay within this resource and never reveal its original signed address
            message = str(exc) if isinstance(exc, StreamRefused) else "The public stream resource could not be read safely."
            with self._lock:
                self._error = message
            if not sent and not self._closed.is_set():
                handler.send_error(502, message)
        finally:
            if response:
                response.close()
            upstream.close()
            with self._lock:
                self._clients.discard(upstream)

    def error(self) -> str:
        with self._lock:
            return self._error

    def retry_until(self) -> float:
        with self._lock:
            return self._retry_at

    def close(self) -> None:
        with self._close_lock:
            if self._closed.is_set():
                return
            self._closed.set()
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            clients = list(self._clients)
        for upstream in clients:
            upstream.close()
        self._thread.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
