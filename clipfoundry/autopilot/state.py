"""Persistent autopilot state: key/value flags, the audit/event log and the user's action items."""
from __future__ import annotations

import json
import time
from typing import Any

from .. import db
from ..pipeline.common import log


# ------------------------------------------------------------------ key/value
def get(key: str, default: Any = None) -> Any:
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM autopilot_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def put(key: str, value: Any) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO autopilot_state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE "
                     "SET value = excluded.value, updated_at = excluded.updated_at", (key, json.dumps(value), time.time()))


def delete(key: str) -> None:
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (key,))


def get_many(prefix: str) -> dict[str, Any]:
    with db.connect() as conn:
        rows = conn.execute("SELECT key, value FROM autopilot_state WHERE key LIKE ?", (prefix + "%",)).fetchall()
    out = {}
    for r in rows:
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            continue
    return out


def paused() -> bool:
    """STOP ALL JOBS was pressed and not yet released."""
    return bool(get("emergency_stop", False))


def enabled(settings: dict | None = None) -> bool:
    settings = settings if settings is not None else db.get_settings()
    return bool(settings.get("autopilot_enabled")) and not paused()


# ------------------------------------------------------------------ audit trail
def event(kind: str, message: str, level: str = "info", ref_type: str = "", ref_id: str = "", **data: Any) -> None:
    """One line in the autopilot's audit log (what happened and why)."""
    getattr(log, "warning" if level in ("warning", "error") else "info")("[autopilot] %s: %s", kind, message)
    db.execute("INSERT INTO autopilot_events (at, kind, level, message, ref_type, ref_id, data) VALUES (?,?,?,?,?,?,?)",
               (time.time(), kind, level, message[:2000], ref_type, ref_id, json.dumps(data, default=str)))


def events(limit: int = 100, ref_type: str = "", ref_id: str = "", kind: str = "") -> list[dict]:
    where, args = [], []
    for col, val in (("ref_type", ref_type), ("ref_id", ref_id), ("kind", kind)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    return db.select("autopilot_events", " AND ".join(where), args, "id DESC", limit)


# ------------------------------------------------------------------ action items (what the user needs to do)
def action(key: str, kind: str, title: str, detail: str = "", fix: str = "", level: str = "action",
           ref_type: str = "", ref_id: str = "") -> None:
    """Open (or refresh) an action item. The same key is never listed twice."""
    now = time.time()
    with db.connect() as conn:
        row = conn.execute("SELECT id, resolved_at FROM action_items WHERE key = ?", (key,)).fetchone()
        if row:
            conn.execute("UPDATE action_items SET kind=?, level=?, title=?, detail=?, fix=?, ref_type=?, ref_id=?, "
                         "updated_at=?, resolved_at=NULL WHERE key=?",
                         (kind, level, title, detail, fix, ref_type, ref_id, now, key))
            if row["resolved_at"] is None:
                return
        else:
            conn.execute("INSERT INTO action_items (id, key, kind, level, title, detail, fix, ref_type, ref_id, "
                         "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (db.new_id(), key, kind, level, title, detail, fix, ref_type, ref_id, now, now))
    event("action_needed", title, "warning" if level != "error" else "error", ref_type, ref_id, key=key)


def resolve(key: str) -> None:
    db.execute("UPDATE action_items SET resolved_at = ? WHERE key = ? AND resolved_at IS NULL", (time.time(), key))


def resolve_prefix(prefix: str) -> None:
    db.execute("UPDATE action_items SET resolved_at = ? WHERE key LIKE ? AND resolved_at IS NULL",
               (time.time(), prefix + "%"))


def open_actions() -> list[dict]:
    return db.select("action_items", "resolved_at IS NULL", (), "created_at DESC")
