"""Public-only platform importing: yt-dlp's HTTP requests use the same pinned guard as direct downloads.

Extractor pages, API requests, media URLs and redirects all use one handler. A failed guard cannot fall back to
another handler or an external network downloader. FFmpeg may merge the downloaded local audio/video files.
"""
from __future__ import annotations

import io
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit
from urllib.request import Request as CookieRequest

import httpx
from yt_dlp import YoutubeDL
from yt_dlp.networking.common import RequestHandler, Response
from yt_dlp.networking.exceptions import HTTPError, RequestError, TransportError
from yt_dlp.utils import determine_protocol

from . import netguard
from .pipeline.common import Cancelled

DOCUMENT_LIMIT = 64 << 20


def public_options() -> dict:
    # Progressive HTTP formats keep all networking inside the guarded handler. Local FFmpeg merging is safe;
    # manifest/external downloaders can fetch extra URLs outside that handler, so they are excluded.
    return {"format": "bv*[height<=1080][protocol=https]+ba[protocol=https]/"
                      "b[height<=1080][protocol=https]/bv*[height<=1080][protocol=http]+ba[protocol=http]/"
                      "b[height<=1080][protocol=http]",
            "external_downloader": "native", "proxy": "", "remote_components": [],
            "geo_bypass": False,
            "cachedir": False}


def client(timeout: float) -> httpx.Client:
    # Environment proxies must not resolve an unchecked address or replace a pinned connection.
    return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)


class _Body(io.RawIOBase):
    def __init__(self, response: httpx.Response, owner: "PublicRH"):
        self.response, self.owner = response, owner
        self.chunks = response.iter_bytes(64 << 10)
        self.pending = bytearray()

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1) -> bytes:
        if self.owner.cancelled():
            raise Cancelled()
        unlimited = size is None or size < 0
        limit = DOCUMENT_LIMIT + 1 if unlimited else size
        if limit == 0:
            return b""
        try:
            while len(self.pending) < limit:
                if self.owner.cancelled():
                    raise Cancelled()
                chunk = next(self.chunks, None)
                if chunk is None:
                    break
                self.owner.consume(len(chunk))
                self.pending.extend(chunk)
            if unlimited and len(self.pending) > DOCUMENT_LIMIT:
                raise TransportError("The platform's page or API answer exceeded the size limit")
            count = len(self.pending) if unlimited else min(size, len(self.pending))
            result = bytes(self.pending[:count])
            del self.pending[:count]
            return result
        except httpx.HTTPError as exc:
            raise TransportError(cause=exc) from exc

    def close(self) -> None:
        self.response.close()
        self.pending.clear()
        super().close()


class _Response(Response):
    def read(self, amt: int | None = None) -> bytes:
        # Response's generic wrapper would turn the pipeline's pause/cancel exception into a network retry.
        return self.fp.read(amt)


class PublicRH(RequestHandler):
    _SUPPORTED_URL_SCHEMES = netguard.HTTP
    _SUPPORTED_PROXY_SCHEMES = ()

    def __init__(self, *, budget: int, cancelled, **kwargs):
        super().__init__(**kwargs)
        self.remaining = budget
        self.cancelled = cancelled
        self.client = client(self.timeout)

    def _check_extensions(self, extensions) -> None:
        super()._check_extensions(extensions)
        for key in ("cookiejar", "timeout", "keep_header_casing"):
            extensions.pop(key, None)

    def consume(self, size: int) -> None:
        self.remaining -= size
        if self.remaining < 0:
            raise TransportError("The platform download exceeded the source size limit")

    def _send(self, request):
        url, method, data = request.url, request.method, request.data
        headers = self._get_headers(request)
        headers["Accept-Encoding"] = "identity"
        jar = self._get_cookiejar(request)
        try:
            for _ in range(netguard.MAX_REDIRECTS + 1):
                if self.cancelled():
                    raise Cancelled()
                ip = netguard.check(url)[0]
                target, pinned_headers, extensions = netguard._pinned(url, ip)
                cookie_request = CookieRequest(url)
                jar.add_cookie_header(cookie_request)
                hop_headers = {k: v for k, v in headers.items() if k.lower() not in ("cookie", "host")}
                if cookie_request.has_header("Cookie"):
                    hop_headers["Cookie"] = cookie_request.get_header("Cookie")
                # httpx's cookie jar uses the pinned IP; only the original host's jar may supply cookies.
                self.client.cookies.clear()
                req = self.client.build_request(method, target, content=data,
                                                headers={**hop_headers, **pinned_headers}, extensions=extensions,
                                                timeout=self._calculate_timeout(request))
                response = self.client.send(req, stream=True, follow_redirects=False)
                response_headers = {k: v for k, v in response.headers.items() if k.lower() != "content-encoding"}
                if response.headers.get("content-encoding"):
                    response_headers.pop("content-length", None)  # iter_bytes returns decompressed bytes
                wrapped = _Response(_Body(response, self), url, response_headers, response.status_code)
                jar.extract_cookies(SimpleNamespace(info=lambda: wrapped.headers), cookie_request)
                if response.is_redirect and response.headers.get("location"):
                    next_url = urljoin(url, response.headers["location"])
                    wrapped.close()
                    if (urlsplit(next_url).scheme, urlsplit(next_url).netloc) != \
                            (urlsplit(url).scheme, urlsplit(url).netloc):
                        headers = {k: v for k, v in headers.items()
                                   if k.lower() not in ("authorization", "proxy-authorization", "cookie")}
                    if response.status_code == 303 or response.status_code in (301, 302) and method == "POST":
                        method, data = "GET", None
                        headers = {k: v for k, v in headers.items()
                                   if k.lower() not in ("content-type", "content-length")}
                    url = next_url
                    continue
                if response.status_code >= 400:
                    raise HTTPError(wrapped)
                declared = response.headers.get("content-length")
                if declared and int(declared) > self.remaining:
                    wrapped.close()
                    raise TransportError("The platform download exceeded the source size limit")
                return wrapped
            raise RequestError("The platform sent too many redirects")
        except netguard.UnsafeUrl as exc:
            raise RequestError(f"Public video access refused: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransportError(cause=exc) from exc

    def close(self) -> None:
        self.client.close()


class GuardedYoutubeDL(YoutubeDL):
    public_budget = 8_000_000_000
    public_cancelled = staticmethod(lambda: False)

    def build_request_director(self, handlers, preferences=None):
        # Replace rather than prefer: refusing a URL must never enable an unguarded fallback handler.
        director = super().build_request_director([])
        director.add_handler(PublicRH(logger=director.logger, headers=self.params["http_headers"],
                                      cookiejar=self.cookiejar, budget=self.public_budget,
                                      cancelled=self.public_cancelled,
                                      timeout=self.params.get("socket_timeout") or 120))
        return director

    def urlopen(self, request):
        url = request if isinstance(request, str) else request.url if hasattr(request, "url") else request.full_url
        netguard.check(url)  # YoutubeDL.urlopen would otherwise strip URL credentials before our handler sees them
        if self.public_cancelled():
            raise Cancelled()
        return super().urlopen(request)

    def process_info(self, info):
        if info.get("is_live"):
            raise RequestError("This public video needs a network downloader that cannot be guarded")
        formats = info.get("requested_formats") or [info]
        for selected in formats:
            if (determine_protocol(selected) not in netguard.HTTP or selected.get("manifest_url")
                    or selected.get("fragments") or selected.get("is_live") or selected.get("section_start")
                    or selected.get("section_end")):
                raise RequestError("This public video needs a network downloader that cannot be guarded")
            netguard.check(selected["url"])
        return super().process_info(info)
