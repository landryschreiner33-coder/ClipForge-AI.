"""SQLite persistence for projects, clips and settings.

Every call opens its own short-lived connection, which keeps the module safe to
use from the API threads and the background worker at the same time.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import config, secure

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    source_filename TEXT,
    source_path TEXT,
    source_url TEXT,
    duration REAL DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    fps REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created',
    stage TEXT DEFAULT '',
    progress REAL DEFAULT 0,
    message TEXT DEFAULT '',
    error TEXT DEFAULT '',
    options TEXT DEFAULT '{}',
    info TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rank INTEGER DEFAULT 0,
    start REAL NOT NULL,
    end REAL NOT NULL,
    title TEXT DEFAULT '',
    hook TEXT DEFAULT '',
    hooks_alt TEXT DEFAULT '[]',
    caption_text TEXT DEFAULT '',
    hashtags TEXT DEFAULT '[]',
    category TEXT DEFAULT '',
    score REAL DEFAULT 0,
    scores TEXT DEFAULT '{}',
    score_source TEXT DEFAULT 'heuristic',
    reason TEXT DEFAULT '',
    edit TEXT DEFAULT '{}',
    status TEXT DEFAULT 'queued',
    progress REAL DEFAULT 0,
    error TEXT DEFAULT '',
    output_path TEXT DEFAULT '',
    thumb_path TEXT DEFAULT '',
    duration REAL DEFAULT 0,
    selected INTEGER DEFAULT 1,
    render_info TEXT DEFAULT '{}',
    analysis TEXT DEFAULT '{}',
    post TEXT DEFAULT '{}',
    active_version TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    platform TEXT PRIMARY KEY,
    account_id TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    scopes TEXT DEFAULT '[]',
    tokens TEXT DEFAULT '',
    info TEXT DEFAULT '{}',
    connected_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    project_id TEXT DEFAULT '',
    platform TEXT NOT NULL,
    mode TEXT DEFAULT 'direct',
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL DEFAULT 0,
    message TEXT DEFAULT '',
    error TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    requested_privacy TEXT DEFAULT '',
    privacy TEXT DEFAULT '',
    remote_id TEXT DEFAULT '',
    url TEXT DEFAULT '',
    video_path TEXT DEFAULT '',
    version_id TEXT DEFAULT '',
    options TEXT DEFAULT '{}',
    info TEXT DEFAULT '{}',
    features TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publications_clip ON publications(clip_id);
CREATE TABLE IF NOT EXISTS clip_versions (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT DEFAULT '',
    description TEXT DEFAULT '',
    edit TEXT DEFAULT '{}',
    status TEXT DEFAULT 'queued',
    progress REAL DEFAULT 0,
    error TEXT DEFAULT '',
    output_path TEXT DEFAULT '',
    thumb_path TEXT DEFAULT '',
    duration REAL DEFAULT 0,
    render_info TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_clip ON clip_versions(clip_id);
CREATE TABLE IF NOT EXISTS performance (
    id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL,
    clip_id TEXT DEFAULT '',
    platform TEXT NOT NULL,
    remote_id TEXT DEFAULT '',
    fetched_at REAL NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    watch_time_minutes REAL,
    avg_view_duration_s REAL,
    avg_view_percentage REAL,
    source TEXT DEFAULT '',
    notes TEXT DEFAULT '[]',
    raw TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_performance_pub ON performance(publication_id, fetched_at);
"""

JSON_FIELDS = {
    "projects": {"options", "info"},
    "clips": {"hooks_alt", "hashtags", "scores", "edit", "render_info", "analysis", "post"},
    "accounts": {"scopes", "info"},
    "publications": {"tags", "options", "info", "features"},
    "clip_versions": {"edit", "render_info"},
    "performance": {"notes", "raw"},
}

# Columns added after the first release. CREATE TABLE IF NOT EXISTS does not touch an existing database, so these
# are added with ALTER TABLE when missing (existing rows get the default).
ADDED_COLUMNS = {
    "clips": {"analysis": "TEXT DEFAULT '{}'", "post": "TEXT DEFAULT '{}'", "active_version": "TEXT DEFAULT ''"},
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


_ready: set[str] = set()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = str(config.db_path())
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if path not in _ready:  # create tables on first use of this database file
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        for f in (path, f"{path}-wal", f"{path}-shm"):  # it holds (sealed) publishing tokens
            secure.restrict_file(f)
        _ready.add(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect():
        pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _decode(table: str, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for key in JSON_FIELDS[table]:
        if key in d:
            try:
                d[key] = json.loads(d[key] or "null")
            except (TypeError, ValueError):
                d[key] = None
    return d


def _encode(table: str, fields: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in fields.items():
        out[k] = json.dumps(v) if k in JSON_FIELDS[table] else v
    return out


def _update(table: str, row_id: str, fields: dict[str, Any], key: str = "id") -> None:
    if not fields:
        return
    fields = _encode(table, {**fields, "updated_at": time.time()})
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {cols} WHERE {key} = ?", [*fields.values(), row_id])


# ---------------------------------------------------------------- projects
def create_project(name: str, **fields: Any) -> dict[str, Any]:
    now = time.time()
    row = {"id": new_id(), "name": name, "created_at": now, "updated_at": now, **fields}
    row = _encode("projects", row)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with connect() as conn:
        conn.execute(f"INSERT INTO projects ({cols}) VALUES ({marks})", list(row.values()))
    return get_project(row["id"])  # type: ignore[return-value]


def get_project(project_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _decode("projects", row)


def list_projects() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM clips c WHERE c.project_id = p.id) AS clip_count,"
            " (SELECT MAX(score) FROM clips c WHERE c.project_id = p.id) AS best_score"
            " FROM projects p ORDER BY p.created_at DESC"
        ).fetchall()
    return [_decode("projects", r) for r in rows]  # type: ignore[misc]


def update_project(project_id: str, **fields: Any) -> None:
    _update("projects", project_id, fields)


def delete_project(project_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM clip_versions WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
                     (project_id,))
        conn.execute("DELETE FROM clips WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ------------------------------------------------------------------- clips
def create_clip(project_id: str, **fields: Any) -> dict[str, Any]:
    now = time.time()
    row = {"id": new_id(), "project_id": project_id, "created_at": now, "updated_at": now, **fields}
    row = _encode("clips", row)
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with connect() as conn:
        conn.execute(f"INSERT INTO clips ({cols}) VALUES ({marks})", list(row.values()))
    return get_clip(row["id"])  # type: ignore[return-value]


def get_clip(clip_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _decode("clips", row)


def list_clips(project_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM clips WHERE project_id = ? ORDER BY rank ASC, score DESC", (project_id,)
        ).fetchall()
    return [_decode("clips", r) for r in rows]  # type: ignore[misc]


def update_clip(clip_id: str, **fields: Any) -> None:
    _update("clips", clip_id, fields)


def delete_clips(project_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM clip_versions WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
                     (project_id,))
        conn.execute("DELETE FROM clips WHERE project_id = ?", (project_id,))


# ---------------------------------------------------------------- clip versions
def create_version(clip_id: str, kind: str, **fields: Any) -> dict[str, Any]:
    now = time.time()
    row = _encode("clip_versions", {"id": new_id(), "clip_id": clip_id, "kind": kind, "created_at": now,
                                    "updated_at": now, **fields})
    with connect() as conn:
        conn.execute(f"INSERT INTO clip_versions ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                     list(row.values()))
    return get_version(row["id"])  # type: ignore[return-value]


def get_version(version_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM clip_versions WHERE id = ?", (version_id,)).fetchone()
    return _decode("clip_versions", row)


def list_versions(clip_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM clip_versions WHERE clip_id = ? ORDER BY created_at", (clip_id,)).fetchall()
    return [_decode("clip_versions", r) for r in rows]  # type: ignore[misc]


def update_version(version_id: str, **fields: Any) -> None:
    _update("clip_versions", version_id, fields)


def delete_version(version_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM clip_versions WHERE id = ?", (version_id,))
        conn.execute("UPDATE clips SET active_version = '' WHERE active_version = ?", (version_id,))


# ---------------------------------------------------------------- publishing accounts (OAuth)
def get_account(platform: str) -> dict[str, Any] | None:
    """Connected account without its tokens (use `account_tokens` for those)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE platform = ?", (platform,)).fetchone()
    acc = _decode("accounts", row)
    if acc:
        acc["has_tokens"] = bool(acc.pop("tokens"))
    return acc


def account_tokens(platform: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT tokens FROM accounts WHERE platform = ?", (platform,)).fetchone()
    if not row or not row["tokens"]:
        return None
    return json.loads(secure.unseal(row["tokens"]))


def save_account(platform: str, tokens: dict[str, Any] | None = None, **fields: Any) -> None:
    now = time.time()
    if tokens is not None:
        fields["tokens"] = secure.seal(json.dumps(tokens))
    enc = _encode("accounts", fields)
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM accounts WHERE platform = ?", (platform,)).fetchone()
        if exists:
            cols = ", ".join(f"{k} = ?" for k in [*enc, "updated_at"])
            conn.execute(f"UPDATE accounts SET {cols} WHERE platform = ?", [*enc.values(), now, platform])
        else:
            row = {"platform": platform, "connected_at": now, "updated_at": now, **enc}
            conn.execute(f"INSERT INTO accounts ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                         list(row.values()))


def delete_account(platform: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM accounts WHERE platform = ?", (platform,))


# ---------------------------------------------------------------- publications
def create_publication(clip_id: str, platform: str, **fields: Any) -> dict[str, Any]:
    now = time.time()
    row = _encode("publications", {"id": new_id(), "clip_id": clip_id, "platform": platform, "created_at": now,
                                   "updated_at": now, **fields})
    with connect() as conn:
        conn.execute(f"INSERT INTO publications ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                     list(row.values()))
    return get_publication(row["id"])  # type: ignore[return-value]


def get_publication(pub_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM publications WHERE id = ?", (pub_id,)).fetchone()
    return _decode("publications", row)


def list_publications(clip_id: str | None = None, platform: str | None = None) -> list[dict[str, Any]]:
    where, args = [], []
    if clip_id:
        where.append("clip_id = ?")
        args.append(clip_id)
    if platform:
        where.append("platform = ?")
        args.append(platform)
    sql = "SELECT * FROM publications" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY created_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_decode("publications", r) for r in rows]  # type: ignore[misc]


def update_publication(pub_id: str, **fields: Any) -> None:
    _update("publications", pub_id, fields)


# ---------------------------------------------------------------- performance (real platform metrics only)
METRICS = ("views", "likes", "comments", "shares", "watch_time_minutes", "avg_view_duration_s", "avg_view_percentage")


def add_performance(publication: dict, metrics: dict[str, Any], source: str, notes: list[str],
                    raw: dict[str, Any]) -> dict[str, Any]:
    """Store one snapshot. Metrics the platform did not report are stored as NULL, never estimated."""
    row = {"id": new_id(), "publication_id": publication["id"], "clip_id": publication.get("clip_id", ""),
           "platform": publication["platform"], "remote_id": metrics.get("remote_id", ""), "fetched_at": time.time(),
           "source": source, **{k: metrics.get(k) for k in METRICS}}
    row = _encode("performance", {**row, "notes": notes, "raw": raw})
    with connect() as conn:
        conn.execute(f"INSERT INTO performance ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
                     list(row.values()))
    return _decode("performance", _row("performance", row["id"]))  # type: ignore[return-value]


def _row(table: str, row_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()


def performance_history(publication_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM performance WHERE publication_id = ? ORDER BY fetched_at DESC",
                            (publication_id,)).fetchall()
    return [_decode("performance", r) for r in rows]  # type: ignore[misc]


def latest_performance() -> dict[str, dict[str, Any]]:
    """Newest snapshot per publication."""
    with connect() as conn:
        rows = conn.execute("SELECT p.* FROM performance p JOIN (SELECT publication_id, MAX(fetched_at) AS m FROM "
                            "performance GROUP BY publication_id) l ON l.publication_id = p.publication_id AND "
                            "l.m = p.fetched_at").fetchall()
    return {r["publication_id"]: _decode("performance", r) for r in rows}  # type: ignore[misc]


# ---------------------------------------------------------------- settings
def get_settings() -> dict[str, Any]:
    values = dict(config.DEFAULT_SETTINGS)
    with connect() as conn:
        for row in conn.execute("SELECT key, value FROM settings"):
            if row["key"] in values:
                try:
                    values[row["key"]] = json.loads(row["value"])
                except ValueError:
                    pass
    for key in config.SEALED_KEYS:
        try:
            values[key] = secure.unseal(values[key])
        except secure.SecretError:
            values[key] = ""  # unreadable here: the user enters it again
    return values


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    clean = config.validate_settings(patch)
    for key in config.SEALED_KEYS & set(clean):
        clean[key] = secure.seal(clean[key])
    with connect() as conn:
        for key, value in clean.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
    return get_settings()


def mark_interrupted() -> None:
    """Jobs do not survive a restart; flag anything that was mid-flight."""
    with connect() as conn:
        conn.execute(
            "UPDATE projects SET status = 'error', error = 'Interrupted (app was closed). Click Retry to resume.'"
            " WHERE status IN ('queued', 'processing')"
        )
        conn.execute(
            "UPDATE clips SET status = 'error', error = 'Interrupted (app was closed). Click Re-render.'"
            " WHERE status IN ('queued', 'rendering')"
        )
        conn.execute(
            "UPDATE clip_versions SET status = 'error', error = 'Interrupted (app was closed). Render it again.'"
            " WHERE status IN ('queued', 'rendering')"
        )
        conn.execute(
            "UPDATE publications SET status = 'failed', error = 'Interrupted (app was closed) before the upload "
            "finished. Nothing was published by this attempt; you can publish again.' WHERE status IN ('queued', "
            "'uploading')"
        )
