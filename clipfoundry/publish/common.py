"""Shared plumbing for the publishing integrations: errors, HTTP, PKCE, pending OAuth logins, request guards."""
from __future__ import annotations

import base64
import functools
import hashlib
import html
import secrets
import threading
import time
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException, Request

from .. import db

LOGIN_TIMEOUT = 15 * 60  # a started "Connect" login is valid for 15 minutes


class PublishError(RuntimeError):
    """A publishing problem with a plain-language explanation and, when possible, what to do about it."""

    def __init__(self, message: str, fix: str = "", code: str = ""):
        super().__init__(message)
        self.fix = fix
        self.code = code


class Cancelled(Exception):
    pass


def network_errors(platform: str):
    """Turn connection problems (offline, proxy, firewall, timeouts) into a plain PublishError."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except httpx.HTTPError as exc:
                raise PublishError(f"Could not reach {platform} ({type(exc).__name__}: {exc}).",
                                   "Check the internet connection, proxy or firewall, then try again.",
                                   "network") from exc
        return inner
    return wrap


def client(timeout: float = 60.0) -> httpx.Client:
    # trust_env keeps system proxy settings working; TLS verification always stays on
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=20.0), follow_redirects=False)


# ------------------------------------------------------------------ PKCE (RFC 7636)
def code_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]  # 43-128 characters from the unreserved set


def challenge_s256(verifier: str) -> str:
    """Standard PKCE challenge (Google): base64url(SHA-256), no padding."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def challenge_hex(verifier: str) -> str:
    """TikTok's desktop Login Kit expects the SHA-256 of the verifier hex-encoded."""
    return hashlib.sha256(verifier.encode()).hexdigest()


# ------------------------------------------------------------------ pending logins
@dataclass
class PendingLogin:
    platform: str
    verifier: str
    redirect_uri: str
    created: float = field(default_factory=time.time)


_pending: dict[str, PendingLogin] = {}
_lock = threading.Lock()


def start_login(platform: str, redirect_uri: str) -> tuple[str, str]:
    """Returns (state, verifier). The state ties the provider's redirect back to this login attempt."""
    state = secrets.token_urlsafe(24)
    verifier = code_verifier()
    with _lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if now - v.created > LOGIN_TIMEOUT]:
            del _pending[k]
        _pending[state] = PendingLogin(platform, verifier, redirect_uri)
    return state, verifier


def finish_login(platform: str, state: str) -> PendingLogin:
    with _lock:
        login = _pending.pop(state or "", None)
    if not login or login.platform != platform or time.time() - login.created > LOGIN_TIMEOUT:
        raise PublishError("This sign-in link is not valid any more.", "Click Connect again in ClipFoundry.")
    return login


# ------------------------------------------------------------------ request guards
LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


def local_only(request: Request) -> None:
    """Accounts and publishing are only reachable from this computer, even if the app is shared on the network."""
    client_host = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
    if client_host not in LOOPBACK_CLIENTS or host not in LOOPBACK_HOSTS:
        raise HTTPException(403, "Publishing and account connections only work in the browser on the computer that "
                                 "runs ClipFoundry (http://127.0.0.1).")


def app_request(request: Request) -> None:
    """State-changing publish actions must come from ClipFoundry's own page (a custom header other sites cannot set
    without a CORS preflight, which this server never grants)."""
    local_only(request)
    if request.headers.get("x-clipfoundry") != "1":
        raise HTTPException(403, "This action can only be started from the ClipFoundry page.")


def redirect_uri(request: Request, platform: str) -> str:
    port = request.url.port or 80
    return f"http://127.0.0.1:{port}/api/oauth/{platform}/callback"


# ------------------------------------------------------------------ tokens
def save_tokens(platform: str, token_response: dict, extra: dict | None = None) -> dict:
    now = time.time()
    tokens = {"access_token": token_response["access_token"],
              "expires_at": now + float(token_response.get("expires_in") or 3600)}
    old = db.account_tokens(platform) or {}
    tokens["refresh_token"] = token_response.get("refresh_token") or old.get("refresh_token", "")
    if token_response.get("refresh_expires_in"):
        tokens["refresh_expires_at"] = now + float(token_response["refresh_expires_in"])
    elif old.get("refresh_expires_at"):
        tokens["refresh_expires_at"] = old["refresh_expires_at"]
    tokens.update(extra or {})
    return tokens


def callback_page(ok: bool, heading: str, message: str, fix: str = "") -> str:
    """Shown in the browser tab that the provider redirects back to after sign-in."""
    color = "#34d399" if ok else "#f87171"
    close = "<script>setTimeout(function(){window.close()},2500)</script>" if ok else ""
    fix_html = f"<p><b>What to do:</b> {html.escape(fix)}</p>" if fix else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>ClipFoundry</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
            "<body style='font-family:Segoe UI,system-ui,sans-serif;background:#0a0a0f;color:#f2f2f7;display:flex;"
            "align-items:center;justify-content:center;height:100vh;margin:0'>"
            "<div style='max-width:520px;padding:32px;border:1px solid #2a2a3a;border-radius:16px;background:#15151e'>"
            f"<h2 style='margin-top:0;color:{color}'>{html.escape(heading)}</h2><p>{html.escape(message)}</p>"
            f"{fix_html}<p style='color:#7d7d93'>You can close this tab and return to ClipFoundry.</p></div>"
            f"{close}</body></html>")
