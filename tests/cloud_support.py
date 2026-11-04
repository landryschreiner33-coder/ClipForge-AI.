"""A fake OpenID Connect provider and cloud-mode environment for tests (no real accounts, no network)."""
from __future__ import annotations

import base64
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx

ISSUER = "https://idp.test"
CLIENT_ID = "clipforge-web"
OWNER = "owner-subject-0001"
SECOND = "second-subject-0002"
ORIGIN = "https://studio.test"


class FakeIdP:
    """Discovery, JWKS and the token endpoint of an OIDC provider, signing ID tokens with a real RSA key."""

    def __init__(self) -> None:
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.kid = "kid-1"
        self.jwks = {"keys": [{**jwk, "kid": self.kid, "alg": "RS256", "use": "sig"}]}
        self.codes: dict[str, dict] = {}
        self.transport = httpx.MockTransport(self.handle)
        self.overrides: dict = {}  # claims or header changes for the next tokens (expired, wrong audience...)

    def approve(self, auth_url: str, subject: str = OWNER, **claims) -> tuple[str, str]:
        """What the provider's page does: the person signs in; it redirects back with a code. Returns (state, code)."""
        q = {k: v[0] for k, v in parse_qs(urlparse(auth_url).query).items()}
        assert q["client_id"] == CLIENT_ID and q["code_challenge_method"] == "S256"
        assert q["redirect_uri"] == f"{ORIGIN}/api/auth/callback"
        code = "code-" + secrets.token_hex(6)
        self.codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "sub": subject, **claims}
        return q["state"], code

    def id_token(self, sub: str, nonce: str, **extra) -> str:
        import jwt

        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT_ID, "sub": sub, "iat": now, "exp": now + 600, "nonce": nonce,
                  "email": f"{sub}@example.test", "name": "Test Owner", **extra, **self.overrides}
        key = self.overrides.pop("_key", self.key)
        return jwt.encode({k: v for k, v in claims.items() if not k.startswith("_")}, key, algorithm="RS256",
                          headers={"kid": self.kid})

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                                             "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks"})
        if url == f"{ISSUER}/jwks":
            return httpx.Response(200, json=self.jwks)
        if url == f"{ISSUER}/token":
            import hashlib

            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            grant = self.codes.pop(form.get("code", ""), None)
            calc = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) \
                .rstrip(b"=").decode()
            if not grant or calc != grant["challenge"] or form.get("client_secret") != "oidc-secret":
                return httpx.Response(400, json={"error": "invalid_grant"})
            extra = {k: v for k, v in grant.items() if k not in ("nonce", "challenge", "sub")}
            return httpx.Response(200, json={"id_token": self.id_token(grant["sub"], grant["nonce"], **extra),
                                             "access_token": "unused", "token_type": "Bearer"})
        return httpx.Response(404)


def cloud_env(monkeypatch, tmp_path, owners: str | None = None) -> FakeIdP:
    """Cloud mode with a fake provider, an encrypted secret store and isolated data."""
    from clipfoundry.cloud import middleware, oidc
    from clipfoundry.cloud import settings as cloud_settings

    keys = tmp_path / "keys"
    keys.mkdir()
    key_file = keys / "secret.key"
    key_file.write_text(base64.b64encode(os.urandom(32)).decode())
    os.chmod(key_file, 0o600)
    env = {"CLIPFOUNDRY_MODE": "cloud", "CLIPFOUNDRY_DATA": str(tmp_path / "data"),
           "CLIPFOUNDRY_PUBLIC_URL": ORIGIN, "CLIPFOUNDRY_OIDC_ISSUER": ISSUER,
           "CLIPFOUNDRY_OIDC_CLIENT_ID": CLIENT_ID, "CLIPFOUNDRY_OIDC_CLIENT_SECRET": "oidc-secret",
           "CLIPFOUNDRY_OWNER_SUBJECTS": owners if owners is not None else f"{ISSUER}|{OWNER},{ISSUER}|{SECOND}",
           "CLIPFOUNDRY_SECRET_KEY_FILE": str(key_file)}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cloud_settings.reset()
    oidc.reset_cache()
    idp = FakeIdP()
    monkeypatch.setattr(oidc, "transport", idp.transport)
    for name, bucket in middleware.LIMITS.items():
        monkeypatch.setitem(middleware.LIMITS, name, type(bucket)(bucket.per_minute))
    return idp


def sign_in(client, idp: FakeIdP, subject: str = OWNER, next_: str = "#/projects", **claims) -> dict:
    """The whole browser sign-in through the fake provider; returns /api/auth/me."""
    from urllib.parse import quote

    r = client.get(f"/api/auth/login?next={quote(next_, safe='/')}", follow_redirects=False)
    assert r.status_code == 302, r.text
    state, code = idp.approve(r.headers["location"], subject, **claims)
    r = client.get(f"/api/auth/callback?state={state}&code={code}", follow_redirects=False)
    assert r.status_code == 303, r.text
    me = client.get("/api/auth/me").json()
    client.headers["x-clipforge-csrf"] = me["csrf"]
    client.headers["x-clipfoundry"] = "1"
    return me
