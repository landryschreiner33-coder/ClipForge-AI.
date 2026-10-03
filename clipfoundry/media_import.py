"""Public webpage extraction with DNS-pinned requests and bounded, native media downloads.

No browser sessions, saved cookies, credentials, external network downloader or DRM fallback is used.
ffmpeg may merge already downloaded local files; it never receives a remote address here.
"""
from __future__ import annotations

import io
from http.cookiejar import CookieJar
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import netguard
from .pipeline.common import Cancelled

MAX_METADATA_BYTES = 20 << 20
MAX_METADATA_TOTAL = 64 << 20
NATIVE_PROTOCOLS = {"http", "https", "m3u8_native", "m3u8", "http_dash_segments"}


class MediaUnavailable(RuntimeError):
    pass


class _NoCookies(CookieJar):
    def set_cookie(self, cookie, *args, **kwargs):
        pass  # DNS-pinned hosts can share an IP; never let a cookie carry across public websites.


class _Body(io.RawIOBase):
    def __init__(self, response, count, cancelled):
        self.response, self.count, self.cancelled = response, count, cancelled
        self.chunks = response.iter_bytes(65536)
        self.pending = bytearray()

    def readable(self):
        return True

    def read(self, size=-1):
        size = -1 if size is None else size
        while size < 0 or len(self.pending) < size:
            if self.cancelled():
                raise Cancelled()
            chunk = next(self.chunks, None)
            if chunk is None:
                break
            self.count(len(chunk))
            self.pending.extend(chunk)
        take = len(self.pending) if size < 0 else min(size, len(self.pending))
        result = bytes(self.pending[:take])
        del self.pending[:take]
        return result

    def close(self):
        self.response.close()
        super().close()


class _Quiet:
    def debug(self, *_):
        pass

    info = warning = error = debug


def public_extractor(options=None, *, max_bytes=8_000_000_000, cancelled=lambda: False):
    """Create a yt-dlp instance whose metadata, manifests and fragments all use the URL guard."""
    try:
        import yt_dlp
        from yt_dlp.downloader import get_suitable_downloader
        from yt_dlp.downloader.hls import HlsFD
        from yt_dlp.networking.common import Request, Response
        from yt_dlp.networking.exceptions import HTTPError
    except ImportError:
        raise MediaUnavailable("Video webpage import needs yt-dlp. Restart with start.bat to install it.") from None

    class PublicDL(yt_dlp.YoutubeDL):
        def __init__(self):
            self.fetching_media = False
            self.metadata_bytes = self.media_bytes = 0
            self.responses = []
            self.http = httpx.Client(timeout=60, follow_redirects=False, trust_env=False, cookies=_NoCookies())
            super().__init__({"quiet": True, "no_warnings": True, "logger": _Quiet(), "noplaylist": True,
                              "playlist_items": "1", "cachedir": False, "allow_unplayable_formats": False,
                              "hls_prefer_native": True, "external_downloader": "native",
                              "skip_unavailable_fragments": False, "retries": 2, "fragment_retries": 2,
                              "socket_timeout": 30, "concurrent_fragment_downloads": 1,
                              "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
                              "format_filter": lambda f: not f.get("has_drm") and
                              f.get("protocol") in NATIVE_PROTOCOLS, **(options or {})})

        def urlopen(self, request):
            if cancelled():
                raise Cancelled()
            self.responses = [response for response in self.responses if not response.closed]
            request = Request(request) if isinstance(request, str) else request
            if request.method not in ("GET", "HEAD", "POST") or request.data is not None and \
                    not isinstance(request.data, bytes):
                raise MediaUnavailable("This website uses an unsupported video request.")
            headers = {k: v for k, v in request.headers.items()
                       if k.lower() not in ("host", "cookie", "authorization", "accept-encoding")}
            response = netguard.open_checked(self.http, request.url, headers=headers,
                                             method=request.method, data=request.data)
            parts = urlsplit(str(response.url))
            address = urlunsplit((parts.scheme, response.request.headers.get("host") or parts.netloc,
                                 parts.path, parts.query, ""))
            used = 0
            per_request = max_bytes if self.fetching_media else MAX_METADATA_BYTES

            def count(size):
                nonlocal used
                used += size
                if self.fetching_media:
                    self.media_bytes += size
                    over = self.media_bytes > max_bytes
                else:
                    self.metadata_bytes += size
                    over = self.metadata_bytes > MAX_METADATA_TOTAL
                if used > per_request or over:
                    raise MediaUnavailable("The video download exceeded its size limit.")

            try:
                if self.fetching_media and int(response.headers.get("content-length") or 0) > per_request:
                    raise MediaUnavailable("The video download exceeded its size limit.")
                from .autopilot import queue
                from .publish.common import retry_after

                wait = retry_after(response)
                if wait is not None and (response.status_code == 429 or response.status_code >= 500):
                    raise queue.Wait("server", wait, "The video website asked to wait before trying again.")
                wrapped = Response(_Body(response, count, cancelled), address, dict(response.headers),
                                   response.status_code)
                self.responses.append(wrapped)
                if response.status_code >= 400:
                    raise HTTPError(wrapped)
                return wrapped
            except Exception:
                response.close()
                raise

        def dl(self, name, info, subtitle=False, test=False):
            downloader = get_suitable_downloader(info, self.params)
            if downloader is None or downloader.__name__ not in ("HttpFD", "HlsFD", "DashSegmentsFD"):
                raise MediaUnavailable("This video needs an unsupported network downloader.")
            if info.get("has_drm") or info.get("is_live"):
                raise MediaUnavailable("Use a direct public stream link for live video. DRM video cannot be imported.")
            if downloader is HlsFD:
                # HlsFD otherwise silently delegates unsupported playlists to ffmpeg, outside the URL guard.
                manifest = info.get("hls_media_playlist_data")
                if not manifest:
                    with self.urlopen(info["url"]) as response:
                        manifest = response.read(MAX_METADATA_BYTES + 1).decode("utf-8", "replace")
                if len(manifest.encode()) > MAX_METADATA_BYTES or "#EXT-X-ENDLIST" not in manifest or \
                        "#EXT-X-KEY" in manifest or "#EXT-X-SESSION-KEY" in manifest or \
                        not HlsFD.can_download(manifest, info, False):
                    raise MediaUnavailable("This stream cannot be imported safely. Use an unprotected recorded video.")
                info = {**info, "hls_media_playlist_data": manifest}
            self.fetching_media = True
            try:
                return super().dl(name, info, subtitle=subtitle, test=test)
            finally:
                self.fetching_media = False

        def close(self):
            for response in self.responses:
                response.close()
            self.responses.clear()
            self.http.close()
            super().close()

    return PublicDL()


def inspect_video(url: str) -> dict:
    """Public metadata only; never infer ownership or a reuse license from an extractor's creator field."""
    with public_extractor({"skip_download": True}) as ydl:
        try:
            meta = ydl.extract_info(url, download=False)
        except netguard.UnsafeUrl:
            raise
        except (MediaUnavailable, Cancelled):
            raise
        except Exception as exc:
            from .autopilot import queue

            if isinstance(exc, queue.Wait):
                raise
            raise MediaUnavailable("This webpage's video could not be accessed. It may require a login, be "
                                   "unavailable, or use an unsupported player.") from None
    if not isinstance(meta, dict) or meta.get("_type") in ("playlist", "multi_video") or meta.get("entries"):
        raise MediaUnavailable("Paste a link to one video, rather than a playlist or channel.")
    if meta.get("has_drm"):
        raise MediaUnavailable("DRM-protected video cannot be imported.")
    for fmt in meta.get("requested_formats") or [meta]:
        if fmt.get("url"):
            netguard.check(fmt["url"])
    return {"title": str(meta.get("title") or "Video link")[:120], "duration": meta.get("duration"),
            "kind": "live" if meta.get("is_live") or meta.get("live_status") == "is_upcoming" else "recorded",
            "live_status": "upcoming" if meta.get("live_status") == "is_upcoming" else
            "live" if meta.get("is_live") else ""}
