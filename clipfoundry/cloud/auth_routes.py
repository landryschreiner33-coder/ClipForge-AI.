"""Sign-in endpoints. In desktop mode `/api/auth/me` simply reports the local owner and the others do not exist."""
from __future__ import annotations

import hashlib
import html
import logging
import secrets
import time
from http.cookies import SimpleCookie

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import config, db
from . import identity, middleware, oidc, principal
from . import settings as cloud_settings

router = APIRouter()
log = logging.getLogger("clipforge.auth")
LOGIN_TTL = 10 * 60


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _cookie(name: str, value: str, max_age: int, http_only: bool = True) -> str:
    s = cloud_settings.current()
    parts = [f"{name}={value}", "Path=/", f"Max-Age={max_age}", "SameSite=Lax"]
    if http_only:
        parts.append("HttpOnly")
    if s.secure_cookies:
        parts.append("Secure")
    return "; ".join(parts)


def _read_cookie(request: Request, name: str) -> str:
    jar = SimpleCookie()
    try:
        jar.load(request.headers.get("cookie", ""))
    except Exception:  # noqa: BLE001
        return ""
    return jar[name].value if name in jar else ""


def _safe_return(value: str) -> str:
    """Only an address inside this app ("#/projects", "/#/video/abc"); anything else returns to Home."""
    value = (value or "").strip()
    if value.startswith("#/") and len(value) < 300 and all(c.isprintable() for c in value):
        return "/" + value
    if value.startswith("/#/") and len(value) < 300 and all(c.isprintable() for c in value):
        return value
    return "/"


def _page(title: str, message: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(config.APP_NAME)}</title>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
        "<body style='font-family:system-ui,sans-serif;background:#0B0D14;color:#F5F6FA;display:flex;"
        "align-items:center;justify-content:center;min-height:100vh;margin:0'>"
        "<main style='max-width:480px;padding:32px;border:1px solid #2A3142;border-radius:14px;background:#151A25'>"
        f"<h1 style='font-size:22px;margin-top:0'>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
        "<p><a style='color:#9A7CFF' href='/'>Back to sign-in</a></p></main></body></html>", status_code=status)


@router.get("/api/auth/me")
def me() -> Response:
    if not cloud_settings.enabled():
        p = principal.LOCAL_OWNER
        return JSONResponse({"mode": "local", "signed_in": True, "name": p.name, "workspace_id": p.workspace_id,
                             "primary": True, "csrf": ""})
    try:
        p = principal.current()
    except principal.NotSignedIn:
        p = None
    if p is None:
        return JSONResponse({"mode": "cloud", "signed_in": False, "login": "/api/auth/login"}, status_code=401)
    return JSONResponse({"mode": "cloud", "signed_in": True, "name": p.name, "workspace_id": p.workspace_id,
                         "primary": p.primary, "csrf": p.csrf})


@router.get("/api/auth/login")
def login(request: Request, next: str = "") -> Response:  # noqa: A002 - query parameter name
    if not cloud_settings.enabled():
        raise HTTPException(404, "Not found")
    try:
        state, nonce, verifier, binder = (secrets.token_urlsafe(24), secrets.token_urlsafe(24),
                                          secrets.token_urlsafe(48), secrets.token_urlsafe(24))
        url = oidc.authorization_url(state, nonce, verifier)
    except oidc.SignInError as exc:
        return _page("Sign-in is not available", str(exc), 503)
    identity.purge_expired()
    db.insert("auth_logins", {"state_hash": _hash(state), "binder_hash": _hash(binder), "verifier": verifier,
                              "nonce": nonce, "return_to": _safe_return(next)}, key="state_hash")
    r = RedirectResponse(url, status_code=302)
    r.headers.append("set-cookie", _cookie(middleware.cookie_names()[1], binder, LOGIN_TTL))
    return r


@router.get("/api/auth/callback")
def callback(request: Request, state: str = "", code: str = "", error: str = "") -> Response:
    if not cloud_settings.enabled():
        raise HTTPException(404, "Not found")
    login_cookie = middleware.cookie_names()[1]
    rows = db.select("auth_logins", "state_hash = ?", (_hash(state or ""),)) if state else []
    if rows:
        db.execute("DELETE FROM auth_logins WHERE state_hash = ?", (rows[0]["state_hash"],))  # single use
    binder = _read_cookie(request, login_cookie)
    if not rows or time.time() - rows[0]["created_at"] > LOGIN_TTL or not binder or \
            not secrets.compare_digest(rows[0]["binder_hash"], _hash(binder)):
        return _page("Sign-in expired", "This sign-in link is not valid any more, or it was opened in another "
                                         "browser. Start again from the sign-in page.", 400)
    if error:
        return _page("Not signed in", "Sign-in was cancelled at the provider.", 400)
    try:
        tokens = oidc.exchange(code, rows[0]["verifier"])
        claims = oidc.verify_id_token(tokens["id_token"], rows[0]["nonce"])
        session, cookie = identity.sign_in(claims["iss"].rstrip("/"), claims["sub"],
                                           email=str(claims.get("email") or ""), name=str(claims.get("name") or ""),
                                           user_agent=request.headers.get("user-agent", ""))
    except oidc.SignInError as exc:
        return _page("Not signed in", str(exc), 400)
    except PermissionError:
        # The subject is an opaque account number, not a secret: the operator copies it into
        # CLIPFOUNDRY_OWNER_SUBJECTS to admit their own account (deploy/README.md).
        log.warning("refused identity %s|%s", claims["iss"].rstrip("/"), claims["sub"])
        return _page("This studio is private", "This account is not allowed to use this ClipForge studio. "
                                               "No data was opened.", 403)
    r = RedirectResponse(rows[0]["return_to"] or "/", status_code=303)
    hours = cloud_settings.current().session_hours
    r.headers.append("set-cookie", _cookie(middleware.cookie_names()[0], cookie, int(hours * 3600)))
    r.headers.append("set-cookie", _cookie(login_cookie, "", 0))
    return r


def _clear(r: Response) -> Response:
    r.headers.append("set-cookie", _cookie(middleware.cookie_names()[0], "", 0))
    return r


@router.post("/api/auth/logout")
def logout() -> Response:
    if not cloud_settings.enabled():
        raise HTTPException(404, "Not found")
    identity.revoke(principal.current().session_id)
    return _clear(JSONResponse({"signed_in": False}))


@router.post("/api/auth/logout-all")
def logout_all() -> Response:
    if not cloud_settings.enabled():
        raise HTTPException(404, "Not found")
    count = identity.revoke_all(principal.current().user_id)
    return _clear(JSONResponse({"signed_in": False, "sessions_ended": count}))


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Readiness for a reverse proxy or service manager: the database answers. No private information."""
    db.scalar("SELECT 1")
    return {"ok": True}
