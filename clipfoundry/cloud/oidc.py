"""OpenID Connect sign-in (authorization code + PKCE + nonce) against the configured provider.

Google works directly (issuer https://accounts.google.com); any standards-compliant provider with discovery works
the same way. The ID token's signature (provider JWKS), issuer, audience, expiry, issue time and nonce are all
verified before its subject is compared with the configured owners. The provider is reached only over HTTPS at the
operator-configured issuer; nothing a browser sends chooses where the server connects.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx

from . import settings as cloud_settings

ALGORITHMS = ["RS256", "ES256", "PS256"]
DISCOVERY_TTL = 3600.0
LEEWAY = 60  # seconds of clock difference tolerated on exp/iat/nbf


class SignInError(Exception):
    """A sign-in that must not succeed; the message is safe to show."""


_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
# Tests replace this with a transport that serves a fake provider.
transport: httpx.BaseTransport | None = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False, transport=transport)


def _get_json(url: str) -> dict:
    if not url.startswith("https://") and transport is None:
        raise SignInError("The sign-in provider must be reached over HTTPS.")
    with _client() as c:
        r = c.get(url)
    if r.status_code != 200:
        raise SignInError("The sign-in provider did not answer. Try again in a moment.")
    return r.json()


def discovery() -> dict:
    s = cloud_settings.current()
    with _lock:
        hit = _cache.get("discovery")
        if hit and time.time() - hit[0] < DISCOVERY_TTL:
            return hit[1]
    doc = _get_json(f"{s.oidc_issuer}/.well-known/openid-configuration")
    if doc.get("issuer", "").rstrip("/") != s.oidc_issuer:
        raise SignInError("The sign-in provider's configuration does not match the configured issuer.")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not str(doc.get(key, "")).startswith("https://") and transport is None:
            raise SignInError("The sign-in provider's configuration is incomplete.")
    with _lock:
        _cache["discovery"] = (time.time(), doc)
    return doc


def _jwks(force: bool = False) -> dict:
    with _lock:
        hit = _cache.get("jwks")
        if hit and not force and time.time() - hit[0] < DISCOVERY_TTL:
            return hit[1]
    keys = _get_json(discovery()["jwks_uri"])
    with _lock:
        _cache["jwks"] = (time.time(), keys)
    return keys


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def redirect_uri() -> str:
    return f"{cloud_settings.current().origin}/api/auth/callback"


def authorization_url(state: str, nonce: str, verifier: str) -> str:
    s = cloud_settings.current()
    return discovery()["authorization_endpoint"] + "?" + urlencode({
        "client_id": s.oidc_client_id, "response_type": "code", "scope": "openid email profile",
        "redirect_uri": redirect_uri(), "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": challenge(verifier), "code_challenge_method": "S256"})


def exchange(code: str, verifier: str) -> dict:
    s = cloud_settings.current()
    if not code or len(code) > 4096:
        raise SignInError("The sign-in response was incomplete. Try again.")
    with _client() as c:
        r = c.post(discovery()["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
            "client_id": s.oidc_client_id, "client_secret": s.oidc_client_secret, "code_verifier": verifier})
    if r.status_code != 200 or "id_token" not in (body := r.json()):
        raise SignInError("The sign-in provider did not confirm this sign-in. Try again.")
    return body


def verify_id_token(id_token: str, nonce: str) -> dict:
    """Validated claims of an ID token, or SignInError. Every check fails closed."""
    import jwt  # PyJWT (requirements-cloud.txt)

    s = cloud_settings.current()
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise SignInError("The sign-in token could not be read.") from exc
    if header.get("alg") not in ALGORITHMS:
        raise SignInError("The sign-in token uses an unsupported signature.")
    kid = header.get("kid")

    def find(keys: dict):
        for k in keys.get("keys", []):
            if k.get("kid") == kid or (kid is None and len(keys.get("keys", [])) == 1):
                return jwt.PyJWK(k)
        return None

    key = find(_jwks()) or find(_jwks(force=True))  # one refetch: the provider may have rotated its keys
    if key is None:
        raise SignInError("The sign-in token was signed with an unknown key.")
    try:
        claims = jwt.decode(id_token, key=key.key, algorithms=[header["alg"]], audience=s.oidc_client_id,
                            issuer=s.oidc_issuer, leeway=LEEWAY,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except jwt.PyJWTError as exc:
        raise SignInError("The sign-in token is not valid (expired, for another app, or altered).") from exc
    auds = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if len(auds) > 1 and claims.get("azp") != s.oidc_client_id:
        raise SignInError("The sign-in token was issued to another app.")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SignInError("The sign-in token does not belong to this sign-in attempt.")
    if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 255:
        raise SignInError("The sign-in token has no usable account identity.")
    return claims
