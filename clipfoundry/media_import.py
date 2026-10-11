"""Public webpage extraction with DNS-pinned requests and bounded, native media downloads.

No browser sessions, saved cookies, credentials, external network downloader or DRM fallback is used.
ffmpeg may merge already downloaded local files; it never receives a remote address here.

When a video's file cannot be obtained, MediaUnavailable says why with one of the ACCESS codes (from yt-dlp's error
types, HTTP statuses and messages, `classify`), so the user gets a specific reason and a fallback instead of one
generic sentence. A code describes the media access only: it never says anything about the right to reuse a video.
"""
from __future__ import annotations

import errno
import io
from http.cookiejar import CookieJar
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import netguard
from .pipeline.common import Cancelled

MAX_METADATA_BYTES = 20 << 20
MAX_METADATA_TOTAL = 64 << 20
NATIVE_PROTOCOLS = {"http", "https", "m3u8_native", "m3u8", "http_dash_segments"}


OTHER_VIDEOS = ("Autopilot goes on with other videos. If you have your own copy of this video, add the file in "
                "Clips → Add video.")
# code: (short label, why in plain words, what to do instead). Nothing here is ever worked around: no logins,
# cookies, location tricks or DRM removal.
ACCESS = {
    "login_required": ("Sign-in required", "The website only shares this video with signed-in viewers or paying "
                       "members. ClipFoundry never signs in or uses your browser's cookies.", OTHER_VIDEOS),
    "private": ("Private video", "This video is private: only people its owner chose can watch it.", OTHER_VIDEOS),
    "access_denied": ("Access denied", "The website refused to share this video's file.", OTHER_VIDEOS),
    "geo_blocked": ("Not available in your country", "The website does not show this video in your country.",
                    OTHER_VIDEOS),
    "protected": ("Copy-protected", "This video is copy-protected (DRM or an encrypted stream). ClipFoundry never "
                  "gets around a protection.", OTHER_VIDEOS),
    "not_found": ("Not found", "This video was removed or made unavailable, or the link is wrong.",
                  "Autopilot goes on with other videos. If you added the link yourself, check that it still works."),
    "unsupported_site": ("Unsupported website", "ClipFoundry has no supported way to get videos from this website "
                         "or player.", "Use a direct link to the video file, or add your own copy in Clips → Add "
                         "video. Autopilot goes on with other videos."),
    "rate_limited": ("Asked to slow down", "The website asked ClipFoundry to slow down (too many requests).",
                     "ClipFoundry tries again after the wait the website asked for and goes on with other videos "
                     "meanwhile."),
    "network": ("Network problem", "The website did not answer properly (a network problem or a server error).",
                "ClipFoundry tries again automatically. If this keeps happening, check this PC's internet "
                "connection."),
    "too_large": ("Over the limits", "The video is larger or longer than Autopilot's limits.",
                  "Raise the limits in Settings → Autopilot, or add a shorter video."),
    "disk_space": ("Disk almost full", "There is not enough free disk space for this download.",
                   "Free up space on the drive of the data folder; ClipFoundry tries again by itself."),
    "playlist": ("Not one video", "The link leads to a playlist or channel, not to one video.",
                 "Use a link to one video."),
    "extraction_failed": ("No video found", "No downloadable video was found on this page.", OTHER_VIDEOS),
}
TEMPORARY = ("rate_limited", "network", "disk_space")  # trying again later can work; the others stay as they are
# Words in yt-dlp's (or a website's) error messages, checked in this order: the first match decides.
MESSAGES = (
    ("protected", ("drm", "encrypted")),
    ("private", ("private video", "video is private", "this account is private")),
    ("login_required", ("sign in", "log in", "login", "logged-in", "authentication", "members-only", "members only",
                        "subscriber", "premium", "requires payment", "purchase", "rental", "age-restricted",
                        "confirm your age", "not a bot", "cookies")),
    ("geo_blocked", ("your country", "geo restrict", "geo-restrict", "geoblock", "not available in your")),
    ("rate_limited", ("too many requests", "rate limit", "rate-limit")),
    ("unsupported_site", ("unsupported url", "unsupported network downloader", "unsupported video request",
                          "no suitable extractor")),
    ("not_found", ("video unavailable", "has been removed", "no longer available", "does not exist", "not found",
                   "was deleted", "is unavailable")),
    ("disk_space", ("no space left", "disk full", "not enough free disk")),
    ("network", ("timed out", "timeout", "connection", "network", "name resolution", "temporary failure",
                 "unreachable", "ssl", "incomplete read")),
)
HTTP_CODES = {401: "login_required", 402: "login_required", 403: "access_denied", 404: "not_found",
              410: "not_found", 451: "geo_blocked", 429: "rate_limited"}


class MediaUnavailable(RuntimeError):
    """The video's file cannot be obtained in an allowed way. `code` is one of ACCESS; `retry_after` is the wait in
    seconds a website asked for (exactly as asked), when it named one."""

    def __init__(self, message: str = "", code: str = "extraction_failed", retry_after: float | None = None):
        code = code if code in ACCESS else "extraction_failed"
        super().__init__(message or ACCESS[code][1])
        self.code, self.retry_after = code, retry_after

    @property
    def label(self) -> str:
        return ACCESS[self.code][0]

    @property
    def fix(self) -> str:
        return ACCESS[self.code][2]

    @property
    def temporary(self) -> bool:
        return self.code in TEMPORARY


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and everything it wraps: yt-dlp nests the real cause in `exc_info` and `cause`."""
    seen: list[BaseException] = []
    todo: list = [exc]
    while todo and len(seen) < 12:
        e = todo.pop(0)
        if not isinstance(e, BaseException) or any(e is s for s in seen):
            continue
        seen.append(e)
        info = getattr(e, "exc_info", None)
        todo += [info[1] if isinstance(info, tuple) and len(info) > 1 else None, getattr(e, "cause", None),
                 e.__cause__, e.__context__]
    return seen


def _status(e: BaseException) -> tuple[int | None, float | None]:
    """(HTTP status, Retry-After seconds) of an HTTP error from yt-dlp or httpx, else (None, None)."""
    response = getattr(e, "response", None)
    status = getattr(e, "status", None)
    if not isinstance(status, int):
        status = getattr(response, "status_code", None) or getattr(response, "status", None)
    if not isinstance(status, int):
        return None, None
    from .publish.common import retry_after

    try:  # yt-dlp's and httpx's headers both look names up without regard to case
        return status, retry_after(response) if response is not None else None
    except (AttributeError, TypeError):  # an answer without readable headers names no wait
        return status, None


def classify(exc: BaseException) -> tuple[str, float | None]:
    """(ACCESS code, Retry-After seconds or None) for a failed extraction or download. The error types and HTTP
    statuses decide first; message words only when nothing more exact is there. Messages are untrusted text: they
    only pick a code and are never shown or followed."""
    chain = _chain(exc)
    for e in chain:
        if isinstance(e, MediaUnavailable):
            return e.code, e.retry_after
    try:
        from yt_dlp.networking.exceptions import TransportError
        from yt_dlp.utils import GeoRestrictedError, UnsupportedError
    except ImportError:  # pragma: no cover - yt-dlp is a dependency
        TransportError = GeoRestrictedError = UnsupportedError = ()  # type: ignore[assignment,misc]
    for e in chain:
        if GeoRestrictedError and isinstance(e, GeoRestrictedError):
            return "geo_blocked", None
        if UnsupportedError and isinstance(e, UnsupportedError):
            return "unsupported_site", None
    for e in chain:
        status, wait = _status(e)
        if status in HTTP_CODES:
            return HTTP_CODES[status], wait
        if status is not None and status >= 500:
            return "network", wait
    text = " ".join(str(e) for e in chain).lower()
    for code, words in MESSAGES:
        if any(w in text for w in words):
            return code, None
    if any(isinstance(e, OSError) and e.errno == errno.ENOSPC for e in chain):
        return "disk_space", None
    if any((TransportError and isinstance(e, TransportError)) or isinstance(e, (httpx.TransportError, OSError))
           for e in chain):
        return "network", None
    return "extraction_failed", None


def unavailable(exc: BaseException) -> MediaUnavailable:
    """A MediaUnavailable with the specific reason for `exc` (its own words, never the website's)."""
    code, wait = classify(exc)
    return MediaUnavailable(ACCESS[code][1], code, wait)


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
        raise MediaUnavailable("Video webpage import needs yt-dlp. Restart with start.bat to install it.",
                               "unsupported_site") from None

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
                raise MediaUnavailable("This website uses an unsupported video request.", "unsupported_site")
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
                    raise MediaUnavailable("The video download exceeded its size limit.", "too_large")

            try:
                if self.fetching_media and int(response.headers.get("content-length") or 0) > per_request:
                    raise MediaUnavailable("The video download exceeded its size limit.", "too_large")
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
                raise MediaUnavailable("This video needs an unsupported network downloader.", "unsupported_site")
            if info.get("has_drm"):
                raise MediaUnavailable("DRM video cannot be imported.", "protected")
            if info.get("is_live"):
                raise MediaUnavailable("Use a direct public stream link for live video.", "unsupported_site")
            if downloader is HlsFD:
                # HlsFD otherwise silently delegates unsupported playlists to ffmpeg, outside the URL guard.
                manifest = info.get("hls_media_playlist_data")
                if not manifest:
                    with self.urlopen(info["url"]) as response:
                        manifest = response.read(MAX_METADATA_BYTES + 1).decode("utf-8", "replace")
                if "#EXT-X-KEY" in manifest or "#EXT-X-SESSION-KEY" in manifest:
                    raise MediaUnavailable("This stream is encrypted, so it cannot be imported. Use an unprotected "
                                           "recorded video.", "protected")
                if len(manifest.encode()) > MAX_METADATA_BYTES or "#EXT-X-ENDLIST" not in manifest or \
                        not HlsFD.can_download(manifest, info, False):
                    raise MediaUnavailable("This stream cannot be imported safely. Use an unprotected recorded video.",
                                           "unsupported_site")
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
            err = unavailable(exc)
            if err.retry_after is not None:  # the website named its wait: not sooner
                raise queue.Wait("server", err.retry_after, str(err)) from None
            if err.temporary:  # a busy website or a network problem: checked again later, not given up
                raise queue.Retry(str(err), err.fix) from None
            raise err from None
    if not isinstance(meta, dict) or meta.get("_type") in ("playlist", "multi_video") or meta.get("entries"):
        raise MediaUnavailable("Paste a link to one video, rather than a playlist or channel.", "playlist")
    if meta.get("has_drm"):
        raise MediaUnavailable("DRM-protected video cannot be imported.", "protected")
    for fmt in meta.get("requested_formats") or [meta]:
        if fmt.get("url"):
            netguard.check(fmt["url"])
    return {"title": str(meta.get("title") or "Video link")[:120], "duration": meta.get("duration"),
            "kind": "live" if meta.get("is_live") or meta.get("live_status") == "is_upcoming" else "recorded",
            "live_status": "upcoming" if meta.get("live_status") == "is_upcoming" else
            "live" if meta.get("is_live") else ""}
