"""Users, workspaces and server-side sessions.

A session cookie holds 32 random bytes; the database keeps only their SHA-256, so a copy of the database cannot be
used to sign in. Sessions end at a fixed lifetime, after an idle period, on logout, or when the owner signs out
everywhere. Only identities configured by the operator (issuer + stable subject) are admitted.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from .. import db
from . import settings as cloud_settings
from .principal import Principal

PRIMARY = cloud_settings.PRIMARY_WORKSPACE


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_primary_workspace() -> None:
    if not db.fetch("workspaces", PRIMARY):
        db.insert("workspaces", {"id": PRIMARY, "name": "Primary workspace"})


def admitted_workspace(issuer: str, subject: str) -> str | None:
    """The workspace an identity may use, or None when it is not an authorized owner. The first configured owner
    uses the primary workspace (the migrated desktop data); any further configured identity gets its own empty
    workspace. Nothing here looks at email addresses."""
    owners = cloud_settings.current().owners
    for index, owner in enumerate(owners):
        if hmac.compare_digest(owner.issuer, issuer) and hmac.compare_digest(owner.subject, subject):
            if index == 0:
                return PRIMARY
            return "ws-" + _hash(owner.key)[:20]
    return None


def sign_in(issuer: str, subject: str, *, email: str = "", name: str = "", user_agent: str = "") -> tuple[dict, str]:
    """Create (or reuse) the user, its workspace membership and a new session. Returns (session, cookie value).
    The caller must have verified the identity token; unauthorized identities raise PermissionError."""
    workspace = admitted_workspace(issuer, subject)
    if workspace is None:
        raise PermissionError("This ClipForge studio is private.")
    ensure_primary_workspace()
    now = time.time()
    user = db.select("users", "issuer = ? AND subject = ?", (issuer, subject))
    if user:
        uid = user[0]["id"]
        db.update("users", uid, email=email[:320], name=name[:200], last_login_at=now)
    else:
        uid = "user-" + secrets.token_hex(8)
        db.insert("users", {"id": uid, "issuer": issuer, "subject": subject, "email": email[:320],
                            "name": name[:200], "last_login_at": now})
    if not db.fetch("workspaces", workspace):
        db.insert("workspaces", {"id": workspace, "name": (name or "Owner")[:80] + "'s workspace",
                                 "owner_key": f"{issuer}|{subject}"})
    if not db.select("workspace_members", "workspace_id = ? AND user_id = ?", (workspace, uid)):
        db.execute("INSERT INTO workspace_members (workspace_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
                   (workspace, uid, now))
    token = secrets.token_urlsafe(32)
    s = cloud_settings.current()
    session = db.insert("auth_sessions", {
        "id": "sess-" + secrets.token_hex(8), "token_hash": _hash(token), "csrf": secrets.token_urlsafe(24),
        "user_id": uid, "workspace_id": workspace, "last_seen_at": now,
        "expires_at": now + s.session_hours * 3600, "user_agent": user_agent[:200]})
    return session, token


IDLE_WRITE_EVERY = 60.0  # seconds between last-seen updates, so every request does not write to the database


def resolve(token: str) -> Principal | None:
    """The principal of a session cookie, or None if it is unknown, expired, idle too long or revoked."""
    if not token or len(token) > 200:
        return None
    rows = db.select("auth_sessions", "token_hash = ?", (_hash(token),))
    if not rows:
        return None
    s = rows[0]
    now = time.time()
    idle = cloud_settings.current().idle_hours * 3600
    if s["revoked_at"] or s["expires_at"] <= now or now - s["last_seen_at"] > idle:
        return None
    member = db.select("workspace_members", "workspace_id = ? AND user_id = ?", (s["workspace_id"], s["user_id"]))
    user = db.fetch("users", s["user_id"])
    if not member or not user or admitted_workspace(user["issuer"], user["subject"]) != s["workspace_id"]:
        return None  # the operator removed this identity: its old sessions stop working at once
    if now - s["last_seen_at"] >= IDLE_WRITE_EVERY:
        db.update("auth_sessions", s["id"], last_seen_at=now)
    return Principal(user_id=s["user_id"], workspace_id=s["workspace_id"], session_id=s["id"],
                     subject=user["subject"], name=user.get("name") or user.get("email") or "Owner", csrf=s["csrf"])


def revoke(session_id: str) -> None:
    db.update("auth_sessions", session_id, revoked_at=time.time())


def revoke_all(user_id: str) -> int:
    return db.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = 0",
                      (time.time(), user_id))


def purge_expired() -> None:
    now = time.time()
    db.execute("DELETE FROM auth_sessions WHERE expires_at < ? OR (revoked_at > 0 AND revoked_at < ?)",
               (now - 86400, now - 86400))
    db.execute("DELETE FROM auth_logins WHERE created_at < ?", (now - 3600,))
