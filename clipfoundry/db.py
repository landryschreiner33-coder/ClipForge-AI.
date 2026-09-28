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
""" + """
-- ------------------------------------------------------------------ Autopilot (see docs/AUTOPILOT.md)
CREATE TABLE IF NOT EXISTS worker_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    worker TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued running waiting retrying completed failed canceled
    priority INTEGER DEFAULT 0,
    payload TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    idem_key TEXT,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    run_after REAL DEFAULT 0,
    lease_owner TEXT DEFAULT '',
    lease_until REAL DEFAULT 0,
    timeout_s REAL DEFAULT 3600,
    progress REAL DEFAULT 0,
    stage TEXT DEFAULT '',
    message TEXT DEFAULT '',
    error TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    wait_reason TEXT DEFAULT '',
    cancel_requested INTEGER DEFAULT 0,
    parent_id TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idem ON worker_jobs(idem_key) WHERE idem_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON worker_jobs(worker, status, run_after);
CREATE INDEX IF NOT EXISTS idx_jobs_ref ON worker_jobs(ref_type, ref_id);
CREATE TABLE IF NOT EXISTS job_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT DEFAULT '',
    worker TEXT DEFAULT '',
    at REAL NOT NULL,
    level TEXT DEFAULT 'info',
    event TEXT DEFAULT '',
    message TEXT DEFAULT '',
    data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id, at);
CREATE TABLE IF NOT EXISTS worker_state (
    name TEXT PRIMARY KEY,
    status TEXT DEFAULT 'idle',               -- idle working waiting completed failed
    job_id TEXT DEFAULT '',
    stage TEXT DEFAULT '',
    message TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    host TEXT DEFAULT '',
    pid INTEGER DEFAULT 0,
    heartbeat REAL DEFAULT 0,
    last_error TEXT DEFAULT '',
    last_completed_at REAL,
    counters TEXT DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS autopilot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS autopilot_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    level TEXT DEFAULT 'info',
    message TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ref ON autopilot_events(ref_type, ref_id, at);
CREATE TABLE IF NOT EXISTS action_items (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    level TEXT DEFAULT 'action',              -- action warning error
    title TEXT DEFAULT '',
    detail TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    resolved_at REAL,
    dismissed_at REAL                         -- dismissed by you (not re-asked while snoozed)
);
CREATE TABLE IF NOT EXISTS trend_signals (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    kind TEXT DEFAULT 'video',                -- video live topic
    title TEXT DEFAULT '',
    url TEXT DEFAULT '',
    channel_id TEXT DEFAULT '',
    channel_title TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    category TEXT DEFAULT '',
    keywords TEXT DEFAULT '[]',
    query TEXT DEFAULT '',
    region TEXT DEFAULT '',
    language TEXT DEFAULT '',
    published_at REAL,
    platform_rank INTEGER,
    metrics TEXT DEFAULT '{}',                -- {name: {value, status: observed|estimated|unavailable, at, note}}
    score REAL,
    score_mode TEXT DEFAULT '',
    components TEXT DEFAULT '{}',
    notes TEXT DEFAULT '[]',
    raw TEXT DEFAULT '{}',
    status TEXT DEFAULT 'active',
    first_seen REAL NOT NULL,
    last_checked REAL NOT NULL,
    UNIQUE(platform, external_id)
);
CREATE TABLE IF NOT EXISTS trend_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    at REAL NOT NULL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    live_viewers INTEGER,
    platform_rank INTEGER,
    score REAL
);
CREATE INDEX IF NOT EXISTS idx_trend_history ON trend_history(signal_id, at);
CREATE TABLE IF NOT EXISTS source_feeds (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                       -- watch_folder youtube_channel stream_url signal_feed
    name TEXT DEFAULT '',
    config TEXT DEFAULT '{}',
    rights_status TEXT DEFAULT '',
    rights_basis TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    last_checked REAL,
    last_error TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,                   -- youtube local stream url
    external_id TEXT NOT NULL,
    kind TEXT DEFAULT 'recorded',             -- recorded live
    live_status TEXT DEFAULT '',              -- live ended upcoming
    url TEXT DEFAULT '',
    local_path TEXT DEFAULT '',
    title TEXT DEFAULT '',
    channel_id TEXT DEFAULT '',
    channel_title TEXT DEFAULT '',
    license TEXT DEFAULT '',
    duration REAL,
    published_at REAL,
    feed_id TEXT DEFAULT '',
    signal_id TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    category TEXT DEFAULT '',
    rights_status TEXT DEFAULT 'MANUAL_CONFIRMATION_REQUIRED',
    rights_basis TEXT DEFAULT '',
    rights_rule_id TEXT DEFAULT '',
    rights_checked_at REAL,
    source_score REAL,
    expected_clips REAL,
    components TEXT DEFAULT '{}',
    status TEXT DEFAULT 'discovered',
    status_note TEXT DEFAULT '',
    project_id TEXT DEFAULT '',
    candidates_found INTEGER DEFAULT 0,
    clips_selected INTEGER DEFAULT 0,
    metrics TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    selected_day TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(platform, external_id)
);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status, source_score);
CREATE TABLE IF NOT EXISTS source_rights (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,                      -- source channel folder url_prefix
    platform TEXT DEFAULT '',
    value TEXT NOT NULL,
    label TEXT DEFAULT '',
    status TEXT NOT NULL,                     -- OWNED LICENSED CREATIVE_COMMONS ALLOWLISTED BLOCKED
    basis TEXT DEFAULT '',
    evidence_url TEXT DEFAULT '',
    created_by TEXT DEFAULT 'user',
    active INTEGER DEFAULT 1,
    expires_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rights_value ON source_rights(scope, value);
CREATE TABLE IF NOT EXISTS clip_candidates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_id TEXT DEFAULT '',
    start REAL NOT NULL,
    end REAL NOT NULL,
    s0 INTEGER DEFAULT -1,
    s1 INTEGER DEFAULT -1,
    stage TEXT DEFAULT 'pool',                -- how far it got: pool fast semantic deep selected
    stage1 REAL DEFAULT 0,
    score REAL,
    scores TEXT DEFAULT '{}',
    rejected TEXT DEFAULT '[]',
    clip_id TEXT DEFAULT '',
    text TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_project ON clip_candidates(project_id);
CREATE TABLE IF NOT EXISTS clip_analysis (
    clip_id TEXT PRIMARY KEY,
    project_id TEXT DEFAULT '',
    audio TEXT DEFAULT '{}',
    visual TEXT DEFAULT '{}',
    semantic TEXT DEFAULT '{}',
    boundary TEXT DEFAULT '{}',
    deep TEXT DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clip_scores (
    clip_id TEXT PRIMARY KEY,
    trend REAL,
    source REAL,
    clip REAL,
    diversity REAL,
    packaging REAL,
    retention REAL,
    publish_opportunity REAL,
    final REAL,
    components TEXT DEFAULT '{}',
    explanation TEXT DEFAULT '[]',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clip_fingerprints (
    clip_id TEXT PRIMARY KEY,
    source_key TEXT DEFAULT '',
    start REAL,
    end REAL,
    text_sig TEXT DEFAULT '[]',
    phash TEXT DEFAULT '[]',
    title_norm TEXT DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata_candidates (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    style TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    hashtags TEXT DEFAULT '[]',
    score REAL DEFAULT 0,
    components TEXT DEFAULT '{}',
    problems TEXT DEFAULT '[]',
    attempt INTEGER DEFAULT 1,
    origin TEXT DEFAULT '',
    selected INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metadata_clip ON metadata_candidates(clip_id, platform);
CREATE TABLE IF NOT EXISTS scheduled_publications (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    source_id TEXT DEFAULT '',
    platform TEXT NOT NULL,
    metadata_id TEXT DEFAULT '',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    privacy TEXT DEFAULT '',
    options TEXT DEFAULT '{}',
    planned_at REAL,
    timezone TEXT DEFAULT '',
    slot TEXT DEFAULT '{}',
    final_score REAL,
    scores TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'awaiting_approval',
    status_note TEXT DEFAULT '',
    approval TEXT DEFAULT '{}',
    publication_id TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    last_error TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    replaces TEXT DEFAULT '',
    replaced_by TEXT DEFAULT '',
    audit TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_status ON scheduled_publications(status, planned_at);
CREATE TABLE IF NOT EXISTS platform_limits (
    platform TEXT NOT NULL,
    key TEXT NOT NULL,
    value REAL,
    origin TEXT DEFAULT 'config',             -- config api observed
    note TEXT DEFAULT '',
    updated_at REAL NOT NULL,
    PRIMARY KEY (platform, key)
);
CREATE TABLE IF NOT EXISTS learning_metrics (
    id TEXT PRIMARY KEY,
    dimension TEXT NOT NULL,
    key TEXT NOT NULL,
    platform TEXT DEFAULT '',
    metric TEXT NOT NULL,
    n INTEGER DEFAULT 0,
    mean REAL,
    shrunk REAL,
    lift REAL,
    data TEXT DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_usage (
    day TEXT NOT NULL,
    bucket TEXT NOT NULL,
    method TEXT NOT NULL,
    purpose TEXT NOT NULL,
    units INTEGER DEFAULT 0,
    calls INTEGER DEFAULT 0,
    last_at REAL,
    PRIMARY KEY (day, bucket, method, purpose)
);
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    method TEXT DEFAULT '',
    response TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

JSON_FIELDS = {
    "projects": {"options", "info"},
    "clips": {"hooks_alt", "hashtags", "scores", "edit", "render_info", "analysis", "post"},
    "accounts": {"scopes", "info"},
    "publications": {"tags", "options", "info", "features"},
    "clip_versions": {"edit", "render_info"},
    "performance": {"notes", "raw"},
    "worker_jobs": {"payload", "result"},
    "job_logs": {"data"},
    "worker_state": {"counters"},
    "autopilot_events": {"data"},
    "action_items": set(),
    "trend_signals": {"keywords", "metrics", "components", "notes", "raw"},
    "trend_history": set(),
    "source_feeds": {"config"},
    "sources": {"components", "metrics"},
    "source_rights": set(),
    "clip_candidates": {"scores", "rejected"},
    "clip_analysis": {"audio", "visual", "semantic", "boundary", "deep"},
    "clip_scores": {"components", "explanation"},
    "clip_fingerprints": {"text_sig", "phash"},
    "metadata_candidates": {"tags", "hashtags", "components", "problems"},
    "scheduled_publications": {"tags", "options", "slot", "scores", "approval", "audit"},
    "platform_limits": set(),
    "learning_metrics": {"data"},
    "quota_usage": set(),
    "api_cache": set(),
}

# Columns added after the first release. CREATE TABLE IF NOT EXISTS does not touch an existing database, so these
# are added with ALTER TABLE when missing (existing rows get the default).
ADDED_COLUMNS = {
    "clips": {"analysis": "TEXT DEFAULT '{}'", "post": "TEXT DEFAULT '{}'", "active_version": "TEXT DEFAULT ''"},
    "projects": {"origin": "TEXT DEFAULT 'manual'", "source_id": "TEXT DEFAULT ''"},
    "publications": {"scheduled_id": "TEXT DEFAULT ''"},
    "action_items": {"dismissed_at": "REAL"},
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
    if "updated_at" in columns(table):
        fields = {**fields, "updated_at": time.time()}
    fields = _encode(table, fields)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE {table} SET {cols} WHERE {key} = ?", [*fields.values(), row_id])


_columns: dict[str, set[str]] = {}


def columns(table: str) -> set[str]:
    if table not in _columns:
        with connect() as conn:
            _columns[table] = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return _columns[table]


# ---------------------------------------------------------------- generic row helpers (autopilot tables)
def insert(table: str, fields: dict[str, Any], key: str = "id", replace: bool = False) -> dict[str, Any]:
    now = time.time()
    row = dict(fields)
    if key == "id" and not row.get("id"):
        row["id"] = new_id()
    cols = columns(table)
    for stamp in ("created_at", "updated_at"):
        if stamp in cols:
            row.setdefault(stamp, now)
    enc = _encode(table, row)
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    with connect() as conn:
        conn.execute(f"{verb} INTO {table} ({', '.join(enc)}) VALUES ({', '.join('?' for _ in enc)})",
                     list(enc.values()))
    return fetch(table, row[key], key) or row


def fetch(table: str, value: Any, key: str = "id") -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)).fetchone()
    return _decode(table, row)


def select(table: str, where: str = "", args: tuple | list = (), order: str = "", limit: int | None = None
           ) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + (f" ORDER BY {order}" if order else "")
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with connect() as conn:
        rows = conn.execute(sql, list(args)).fetchall()
    return [_decode(table, r) for r in rows]  # type: ignore[misc]


def update(table: str, value: Any, key: str = "id", **fields: Any) -> None:
    _update(table, value, fields, key)


def execute(sql: str, args: tuple | list = ()) -> int:
    with connect() as conn:
        return conn.execute(sql, list(args)).rowcount


def scalar(sql: str, args: tuple | list = ()) -> Any:
    with connect() as conn:
        row = conn.execute(sql, list(args)).fetchone()
    return row[0] if row else None


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


def interrupted_work() -> dict[str, list]:
    """What was mid-flight when the app stopped, so it can be resumed.

    Manual projects, renders and versions are resumed by the app's render worker (jobs.py). Autopilot projects are
    resumed by their own durable job (autopilot/queue.py). A manual upload is not restarted without the user: it
    is marked as interrupted and can be checked and published again.
    """
    with connect() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, source_path, source_url, info FROM projects WHERE status IN ('queued', 'processing') "
            "AND COALESCE(origin, 'manual') != 'autopilot'")]
        clips = [r["id"] for r in conn.execute(
            "SELECT c.id FROM clips c JOIN projects p ON p.id = c.project_id WHERE c.status IN ('queued', "
            "'rendering') AND p.status NOT IN ('queued', 'processing')")]
        versions = [r["id"] for r in conn.execute(
            "SELECT id FROM clip_versions WHERE status IN ('queued', 'rendering')")]
        conn.execute(
            "UPDATE publications SET status = 'failed', error = 'Interrupted (the app was closed) before the upload "
            "was confirmed. Check the platform before publishing again: the upload may or may not have finished.' "
            "WHERE status IN ('queued', 'uploading') AND COALESCE(scheduled_id, '') = ''"
        )
    return {"projects": projects, "clips": clips, "versions": versions}
