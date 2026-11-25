"""ClipForge's TikTok token broker: the one place that holds the client secret of ClipForge's TikTok app.

TikTok says an app's client secret lives server-side only, so the desktop app cannot finish a TikTok sign-in by itself.
It sends this broker what TikTok's token endpoint needs besides the secret; the broker adds the secret, asks TikTok,
and passes TikTok's answer back unchanged. It keeps nothing: no tokens, no sign-in codes, no accounts, no logs of
request bodies. It can only finish what a person already approved on TikTok's own page: a sign-in code is useless
without the PKCE verifier that only the person's ClipForge has, and a refresh needs the person's refresh token.

    POST /token   {"client_key", "grant_type": "authorization_code", "code", "code_verifier", "redirect_uri"}
                  {"client_key", "grant_type": "refresh_token", "refresh_token"}
    POST /revoke  {"client_key", "token"}
    GET  /health  {"ok": true}

Settings (environment): TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET (required), TIKTOK_API_URL (tests only).
Run: uvicorn app:app --host 0.0.0.0 --port 8080   (in this folder, behind HTTPS; see README.md)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

MAX_BODY = 8 * 1024
PER_MINUTE = 30  # per caller address: a person signs in or refreshes a few times a day
# a ClipForge sign-in always returns to ClipForge on the person's own computer
REDIRECT = re.compile(r"http://(127\.0\.0\.1|localhost):\d{2,5}/api/oauth/tiktok/callback")
_seen: dict[str, list[float]] = {}
_seen_lock = threading.Lock()


def _api() -> str:
    return os.environ.get("TIKTOK_API_URL", "https://open.tiktokapis.com/v2").rstrip("/")


def _app() -> tuple[str, str]:
    return os.environ.get("TIKTOK_CLIENT_KEY", ""), os.environ.get("TIKTOK_CLIENT_SECRET", "")


def _refuse(code: str, words: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code, "error_description": words}, status_code=status)


def _too_often(request: Request) -> bool:
    who = request.client.host if request.client else "?"
    now = time.monotonic()
    with _seen_lock:
        recent = [t for t in _seen.get(who, []) if now - t < 60]
        recent.append(now)
        _seen[who] = recent
        if len(_seen) > 10_000:  # forget quiet callers so memory stays small
            for k in [k for k, v in _seen.items() if not v or now - v[-1] > 60]:
                _seen.pop(k, None)
    return len(recent) > PER_MINUTE


async def _body(request: Request) -> dict | None:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return None
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()) else None


async def _forward(path: str, form: dict) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
            r = await c.post(f"{_api()}{path}", data=form,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    except httpx.HTTPError:
        return _refuse("unreachable", "TikTok did not answer. Try again in a moment.", 502)
    try:
        answer = r.json()
    except ValueError:
        answer = {"error": "bad_answer", "error_description": f"TikTok answered {r.status_code}."}
    return JSONResponse(answer, status_code=r.status_code)


async def token(request: Request) -> JSONResponse:
    if _too_often(request):
        return _refuse("rate_limited", "Too many sign-ins from here. Wait a minute.", 429)
    key, secret = _app()
    if not key or not secret:
        return _refuse("not_set_up", "This broker has no TikTok app set up.", 503)
    data = await _body(request)
    if data is None:
        return _refuse("invalid_request", "Send a small JSON object of strings.")
    if data.get("client_key") != key:
        return _refuse("invalid_client", "This broker serves ClipForge's TikTok app only.")
    grant = data.get("grant_type", "")
    if grant == "authorization_code":
        if not (data.get("code") and data.get("code_verifier") and REDIRECT.fullmatch(data.get("redirect_uri", ""))):
            return _refuse("invalid_request", "A sign-in needs its code, its verifier and ClipForge's own address.")
        form = {k: data[k] for k in ("code", "code_verifier", "redirect_uri")}
    elif grant == "refresh_token":
        if not data.get("refresh_token"):
            return _refuse("invalid_request", "A refresh needs the refresh token.")
        form = {"refresh_token": data["refresh_token"]}
    else:
        return _refuse("unsupported_grant_type", "Only a sign-in or a refresh.")
    return await _forward("/oauth/token/", {"client_key": key, "client_secret": secret, "grant_type": grant,
                                            **form})


async def revoke(request: Request) -> JSONResponse:
    if _too_often(request):
        return _refuse("rate_limited", "Too many requests from here. Wait a minute.", 429)
    key, secret = _app()
    data = await _body(request)
    if not key or not secret:
        return _refuse("not_set_up", "This broker has no TikTok app set up.", 503)
    if data is None or data.get("client_key") != key or not data.get("token"):
        return _refuse("invalid_request", "Send ClipForge's client key and the token to revoke.")
    return await _forward("/oauth/revoke/", {"client_key": key, "client_secret": secret, "token": data["token"]})


async def health(_: Request) -> JSONResponse:
    key, secret = _app()
    return JSONResponse({"ok": bool(key and secret)})


app = Starlette(routes=[Route("/token", token, methods=["POST"]), Route("/revoke", revoke, methods=["POST"]),
                        Route("/health", health, methods=["GET"])])
