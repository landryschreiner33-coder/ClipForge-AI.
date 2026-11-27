"""Cloud request guard (pure ASGI, so streamed media and range requests pass through unchanged).

For every request in cloud mode, in this order:
1. The Host header must be one of the configured hosts.
2. Everything under /api/ (data, media, thumbnails, exports, job events) needs a valid session cookie, except the
   sign-in endpoints and the bare /healthz probe. The page shell and its static files are public: they hold no data.
3. Changes (POST/PUT/PATCH/DELETE) need the session's CSRF token in `X-ClipForge-CSRF` and, when the browser sends
   an Origin, the configured origin.
4. Secondary workspaces (configured test or future identities) reach only workspace-scoped endpoints; the
   single-workspace parts (Autopilot, Brain notes, global settings, publishing) answer 403 for them.
5. Sign-in, upload creation and general API use are rate limited per client.
Every response gets security headers. Hiding navigation in the page is never relied on.
"""
from __future__ import annotations

import hmac
import json
import re
import threading
import time
from collections import defaultdict
from http.cookies import SimpleCookie

import anyio

from . import identity, principal
from . import settings as cloud_settings

SESSION_COOKIE = "__Host-cf_session"
DEV_SESSION_COOKIE = "cf_session"  # only for http://localhost testing, where the __Host- prefix cannot be used
LOGIN_COOKIE = "__Host-cf_login"
DEV_LOGIN_COOKIE = "cf_login"
CSRF_HEADER = b"x-clipforge-csrf"

PUBLIC_API = {"/api/auth/login", "/api/auth/callback", "/api/auth/me"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# What a secondary workspace may reach: its own projects, media, studio work, styles, skills, preferences, robot
# names and connections. Ownership of each referenced object is checked again in the route dependency (api.py).
# Guidance and processing still consult the primary owner's Brain/settings, even when their output rows have
# workspace IDs. Keep those paths owner-only until the underlying knowledge and worker services are scoped too.
SECONDARY_ALLOWED = re.compile(
    r"^/api/(auth/|uploads(/|$)|assets/|studio/|projects(/|$)|clips/[^/]+(/(video|thumbnail|words|versions))?$|"
    r"versions/[^/]+/(video|thumbnail)$|stories/|preferences/|robots/names|connections(/|$)|stats$|health$)")
SECONDARY_BLOCKED = re.compile(
    r"/publish|/publications|/post-package|/guidance(?:/|$)|^/api/studio/(?:clips|videos|references|media|requests)(?:/|$)|"
    r"^/api/assets/[^/]+/source$")
SECONDARY_SHARED_WRITES = re.compile(r"^/api/(?:projects|clips|versions|stories)(?:/|$)")

CSP = ("default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; worker-src 'self' blob:; "
       "font-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class _Bucket:
    """A sliding one-minute counter per key."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, list[float]] = defaultdict(list)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            hits = [t for t in self.hits[key] if now - t < 60.0]
            if len(hits) >= self.per_minute:
                self.hits[key] = hits
                return False
            hits.append(now)
            self.hits[key] = hits
            if len(self.hits) > 10000:  # bounded memory under a flood of distinct clients
                self.hits = defaultdict(list, {k: v for k, v in self.hits.items() if v and now - v[-1] < 60})
            return True


LIMITS = {"auth": _Bucket(20), "upload": _Bucket(60), "api": _Bucket(1200)}


def cookie_names() -> tuple[str, str]:
    secure = cloud_settings.current().secure_cookies
    return (SESSION_COOKIE, LOGIN_COOKIE) if secure else (DEV_SESSION_COOKIE, DEV_LOGIN_COOKIE)


def _headers(scope) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for k, v in scope.get("headers") or []:
        out[k.lower()] = v  # the last value wins; a duplicated security header is not merged
    return out


def client_ip(scope, headers: dict[bytes, bytes]) -> str:
    peer = (scope.get("client") or ("", 0))[0]
    s = cloud_settings.current()
    if peer in s.trusted_proxies and b"x-forwarded-for" in headers:
        hops = [h.strip() for h in headers[b"x-forwarded-for"].decode("latin-1").split(",") if h.strip()]
        for hop in reversed(hops):  # the right-most address the trusted proxy did not add itself
            if hop not in s.trusted_proxies:
                return hop
    return peer


def session_token(headers: dict[bytes, bytes]) -> str:
    raw = headers.get(b"cookie", b"").decode("latin-1")
    if not raw:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 - a malformed cookie header is simply not a session
        return ""
    name = cookie_names()[0]
    return jar[name].value if name in jar else ""


async def _send_json(send, status: int, body: dict, extra: list[tuple[bytes, bytes]] | None = None) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            *security_headers(True), *(extra or [])]})
    await send({"type": "http.response.body", "body": data})


def security_headers(api: bool) -> list[tuple[bytes, bytes]]:
    out = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
           (b"x-frame-options", b"DENY"), (b"content-security-policy", CSP.encode()),
           (b"cross-origin-opener-policy", b"same-origin-allow-popups"),
           (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
    if cloud_settings.current().secure_cookies:
        out.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
    if api:
        out.append((b"cache-control", b"no-store"))
    return out


class CloudGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not cloud_settings.enabled():
            return await self.app(scope, receive, send)
        s = cloud_settings.current()
        headers = _headers(scope)
        host = headers.get(b"host", b"").decode("latin-1").strip().lower()
        hostname = host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0] if ":" in host else host
        if hostname not in {h.lower() for h in s.allowed_hosts}:
            return await _send_json(send, 400, {"detail": "Unknown host."})
        path = scope.get("path") or "/"
        method = scope.get("method", "GET").upper()
        api = path.startswith("/api/") or path == "/api"
        ip = client_ip(scope, headers)

        if path in ("/api/auth/login", "/api/auth/callback") and not LIMITS["auth"].allow(ip):
            return await _send_json(send, 429, {"detail": "Too many sign-in attempts. Wait a minute."},
                                    [(b"retry-after", b"60")])
        # The session lookup reads SQLite: run it off the event loop, like every other database call.
        who = await anyio.to_thread.run_sync(identity.resolve, session_token(headers)) if api else None
        if api and path not in PUBLIC_API:
            if who is None:
                return await _send_json(send, 401, {"detail": "Sign in to ClipForge.", "code": "signed_out"})
            if not LIMITS["api"].allow(who.session_id):
                return await _send_json(send, 429, {"detail": "Too many requests. Wait a minute."},
                                        [(b"retry-after", b"60")])
            if method == "POST" and path == "/api/uploads" and not LIMITS["upload"].allow(who.session_id):
                return await _send_json(send, 429, {"detail": "Too many new uploads. Wait a minute."},
                                        [(b"retry-after", b"60")])
            if method in MUTATING:
                origin = headers.get(b"origin", b"").decode("latin-1")
                token = headers.get(CSRF_HEADER, b"").decode("latin-1")
                if origin and origin.rstrip("/") != s.origin:
                    return await _send_json(send, 403, {"detail": "This request did not come from ClipForge."})
                if not token or not hmac.compare_digest(token, who.csrf):
                    return await _send_json(send, 403, {"detail": "This request did not come from the ClipForge "
                                                                  "page. Reload the page and try again."})
            if not who.primary and (not SECONDARY_ALLOWED.search(path) or SECONDARY_BLOCKED.search(path)
                                    or (method in MUTATING and SECONDARY_SHARED_WRITES.search(path))):
                return await _send_json(send, 403, {"detail": "This part of ClipForge is available only in the "
                                                              "primary workspace during the private release."})

        token = principal.bind(who)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers") or []}
                message["headers"] = [*(message.get("headers") or []),
                                      *[h for h in security_headers(api) if h[0] not in names]]
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            principal.reset(token)
