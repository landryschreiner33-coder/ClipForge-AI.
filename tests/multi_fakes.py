"""Fake Google and TikTok servers with several accounts at once (multiple YouTube channels, including two
channels reached from one Google sign-in, and several TikTok creators). Every token, refresh and upload is tied to
the account it belongs to, so a test can prove which account received which bytes."""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse

from fake_platforms import FakeGoogle, FakeTikTok


class FakeGoogleMulti(FakeGoogle):
    def __init__(self) -> None:
        self.code_channel: dict[str, str] = {}
        self.access_channel: dict[str, str] = {}
        self.refresh_channel: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.revoked_refresh: set[str] = set()
        self.refreshes: dict[str, int] = {}
        self.refresh_delay = 0.0
        self.mu = threading.Lock()
        super().__init__()

    def approve(self, auth_url: str, channel: str = "UCchanA", title: str = "Channel A") -> str:  # type: ignore[override]
        code = super().approve(auth_url)
        self.code_channel[code] = channel
        self.titles[channel] = title
        return code

    def revoke_channel(self, channel: str) -> None:
        """The owner revoked ClipForge's access for this channel at Google."""
        self.revoked_refresh |= {r for r, c in self.refresh_channel.items() if c == channel}
        for a in [a for a, c in self.access_channel.items() if c == channel]:
            del self.access_channel[a]

    def uploads_to(self, channel: str) -> list[dict]:
        return [v for v in self.videos.values() if v.get("channel") == channel]

    def _token(self, h, body: bytes) -> None:
        form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
        self.grants.append(form["grant_type"])
        if form.get("client_id") != "cid.apps.googleusercontent.com" or form.get("client_secret") != "csecret":
            return h._send(401, {"error": "invalid_client"})
        if form["grant_type"] == "authorization_code":
            challenge = self.codes.pop(form.get("code", ""), None)
            calc = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) \
                .rstrip(b"=").decode()
            channel = self.code_channel.pop(form.get("code", ""), "")
            if challenge is None or calc != challenge or not channel:
                return h._send(400, {"error": "invalid_grant"})
            access, refresh = "access-" + secrets.token_hex(4), "refresh-" + secrets.token_hex(4)
            with self.mu:
                self.access_channel[access] = channel
                self.refresh_channel[refresh] = channel
            return h._send(200, {"access_token": access, "expires_in": 3599, "token_type": "Bearer",
                                 "refresh_token": refresh, "scope": self.scope})
        refresh = form.get("refresh_token", "")
        channel = self.refresh_channel.get(refresh, "")
        if not channel or refresh in self.revoked_refresh:
            return h._send(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        access = "access-" + secrets.token_hex(4)
        with self.mu:
            self.refreshes[channel] = self.refreshes.get(channel, 0) + 1
            self.access_channel[access] = channel
        return h._send(200, {"access_token": access, "expires_in": 3599, "scope": self.scope})

    def handle(self, h, method: str, body: bytes) -> None:
        u = urlparse(h.path)
        q = parse_qs(u.query)
        if u.path == "/token":
            return self._token(h, body)
        auth = (h.headers.get("Authorization") or "")[len("Bearer "):]
        channel = self.access_channel.get(auth, "")
        if u.path == "/youtube/v3/channels" and q.get("mine") == ["true"]:
            if not channel:
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            return h._send(200, {"items": [{"id": channel, "snippet": {"title": self.titles.get(channel, channel),
                                                                        "thumbnails": {}}}]})
        with self.mu:
            self.access = auth if channel else ""  # the parent's own check then accepts exactly this token
            before = set(self.sessions)
            super().handle(h, method, body)
            for sid in set(self.sessions) - before:
                self.sessions[sid]["channel"] = channel

    def _progress(self, h, s: dict) -> None:
        before = set(self.videos)
        out = super()._progress(h, s)
        for vid in set(self.videos) - before:  # tests read uploads after the transfer, so tagging after it is fine
            self.videos[vid]["channel"] = s.get("channel")
        return out


class FakeTikTokMulti(FakeTikTok):
    def __init__(self) -> None:
        self.code_account: dict[str, str] = {}
        self.access_account: dict[str, str] = {}
        self.names: dict[str, str] = {}
        super().__init__()

    def approve(self, auth_url: str, open_id: str = "open-a", name: str = "Creator A") -> str:  # type: ignore[override]
        code = super().approve(auth_url)
        self.code_account[code] = open_id
        self.names[open_id] = name
        return code

    def uploads_by(self, open_id: str) -> list[dict]:
        return [u for u in self.uploads.values() if u.get("account") == open_id]

    def handle(self, h, method: str, body: bytes) -> None:
        u = urlparse(h.path)
        if u.path == "/v2/oauth/token/":
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            code = form.get("code", "")
            account = self.code_account.pop(code, "") if form["grant_type"] == "authorization_code" else ""
            challenge, redirect = self.codes.pop(code, ("", ""))
            calc = hashlib.sha256(form.get("code_verifier", "").encode()).hexdigest()
            if form["grant_type"] != "authorization_code" or not account or calc != challenge:
                return h._send(200, {"error": "invalid_grant", "error_description": "bad code"})
            access = "act." + secrets.token_hex(6)
            self.access_account[access] = account
            return h._send(200, {"access_token": access, "expires_in": 86400, "open_id": account,
                                 "refresh_expires_in": 31536000, "refresh_token": "rft-" + account,
                                 "scope": self.scope, "token_type": "Bearer"})
        auth = (h.headers.get("Authorization") or "")[len("Bearer "):]
        account = self.access_account.get(auth, "")
        if u.path == "/v2/user/info/" and account:
            return self._ok(h, {"user": {"open_id": account, "display_name": self.names[account],
                                         "avatar_url": "https://p16.example/a.jpg"}})
        self.access = auth if account else ""
        before = set(self.uploads)
        super().handle(h, method, body)
        for pid in set(self.uploads) - before:
            self.uploads[pid]["account"] = account
        return None

