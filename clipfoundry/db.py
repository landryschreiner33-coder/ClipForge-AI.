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

from . import config, locks, secure

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
CREATE TABLE IF NOT EXISTS publish_consents (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,                   -- youtube (TikTok requires your consent for each post)
    settings TEXT DEFAULT '{}',               -- visibility, made for kids, daily limit, posting window, content rule
    text TEXT DEFAULT '',                     -- exactly what you agreed to
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    revoked_at REAL
);
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
-- dynamic replacement history: the cooldown between replacements of a slot reads it (autopilot/scheduler.py)
CREATE TABLE IF NOT EXISTS slot_replacements (
    replacement_id TEXT PRIMARY KEY,            -- the stronger post proposed for the slot
    replaced_id TEXT NOT NULL,                  -- the post whose slot it takes
    platform TEXT NOT NULL,
    slot_at REAL NOT NULL,                      -- the slot's time (UTC seconds)
    clip_id TEXT DEFAULT '',                    -- the replacement's clip
    status TEXT NOT NULL DEFAULT 'proposed',    -- proposed (waits for approval) replaced
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_slot_replacements ON slot_replacements(platform, slot_at);
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
CREATE TABLE IF NOT EXISTS clip_blueprints (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    version_id TEXT DEFAULT '',
    origin TEXT DEFAULT 'strategist',         -- strategist (the plan) edit version (changes applied on top)
    schema_version INTEGER DEFAULT 1,
    sha256 TEXT NOT NULL,
    blueprint TEXT NOT NULL,
    status TEXT DEFAULT 'valid',              -- valid invalid
    issues TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blueprints_clip ON clip_blueprints(clip_id, origin, created_at);
CREATE TABLE IF NOT EXISTS quality_reports (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    version_id TEXT DEFAULT '',
    artifact_path TEXT DEFAULT '',
    artifact_sha256 TEXT NOT NULL,
    file_stamp TEXT DEFAULT '',               -- size:mtime of the file, to find its report without hashing it
    gate_version INTEGER DEFAULT 1,
    status TEXT NOT NULL,                     -- passed failed
    checks TEXT DEFAULT '[]',
    blockers TEXT DEFAULT '[]',
    warnings TEXT DEFAULT '[]',
    bindings TEXT DEFAULT '{}',               -- final transcript, EDL, blueprint the file was rendered from
    metadata TEXT DEFAULT '{}',               -- platform -> the packaging checked against this file
    coverage TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_clip ON quality_reports(clip_id, file_stamp);
CREATE INDEX IF NOT EXISTS idx_quality_sha ON quality_reports(artifact_sha256);
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    method TEXT DEFAULT '',
    response TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS office_events (    -- the office feed (office/feed.py): one row per real transition
    id INTEGER PRIMARY KEY AUTOINCREMENT,     -- the client's resume cursor
    at REAL NOT NULL,
    type TEXT NOT NULL,                       -- job_started, job_stage, job_done, job_failed, report, decision, ...
    role TEXT DEFAULT '',
    job_id TEXT DEFAULT '',
    kind TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    message TEXT DEFAULT '',
    data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_office_events_at ON office_events(at);
CREATE INDEX IF NOT EXISTS idx_office_events_job ON office_events(job_id);
CREATE TABLE IF NOT EXISTS office_reports (   -- a manager's automatic review of one finished job
    id TEXT PRIMARY KEY,
    job_id TEXT DEFAULT '',
    kind TEXT DEFAULT '',
    department TEXT DEFAULT '',
    manager TEXT DEFAULT '',
    worker TEXT DEFAULT '',
    ref_type TEXT DEFAULT '',
    ref_id TEXT DEFAULT '',
    state TEXT DEFAULT '',                    -- done, failed, waiting, canceled
    summary TEXT DEFAULT '',
    warnings TEXT DEFAULT '[]',
    recommendation TEXT DEFAULT '',           -- continue, rework, retry_later, needs_owner, stop
    confidence REAL,                          -- NULL when nothing measured it
    resources TEXT DEFAULT '{}',              -- elapsed seconds, attempts, GPU use when known
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_office_reports_at ON office_reports(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_office_reports_job ON office_reports(job_id, state);
CREATE TABLE IF NOT EXISTS office_decisions ( -- the Director's recorded decisions at the four checkpoints
    id TEXT PRIMARY KEY,
    point TEXT NOT NULL,                      -- source, clip, qc, upload
    subject_type TEXT DEFAULT '',
    subject_id TEXT DEFAULT '',
    job_id TEXT DEFAULT '',
    decided_by TEXT DEFAULT 'command',
    reported_by TEXT DEFAULT '',
    action TEXT NOT NULL,                     -- approved, rework, rejected, held
    reason TEXT DEFAULT '',
    evidence TEXT DEFAULT '{}',
    rule_version TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_office_decisions_subject ON office_decisions(subject_type, subject_id, created_at);
CREATE TABLE IF NOT EXISTS brain_observations ( -- results evidence with provenance (autopilot/brain.py)
    id TEXT PRIMARY KEY,
    clip_id TEXT DEFAULT '',
    publication_id TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    cohort TEXT DEFAULT 'selected',           -- selected (test viewers), public_legacy, owner_only
    group_version INTEGER DEFAULT 0,
    provenance TEXT NOT NULL,                 -- platform_api, owner_import, tester_feedback
    observed_at REAL NOT NULL,                -- when the numbers were true, not when they were entered
    age_hours REAL,                           -- hours after posting, when known
    metrics TEXT DEFAULT '{}',                -- missing metrics stay missing (never 0)
    tester TEXT DEFAULT '',                   -- a tester's own label; no personal data needed
    note TEXT DEFAULT '',
    origin TEXT DEFAULT '',                   -- "form", a CSV file name, or the platform API
    dedupe_key TEXT NOT NULL,
    revision INTEGER DEFAULT 1,               -- a correction replaces the values and keeps the earlier ones below
    previous TEXT DEFAULT '[]',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_obs_dedupe ON brain_observations(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_brain_obs_clip ON brain_observations(clip_id, observed_at);
CREATE TABLE IF NOT EXISTS brain_strategies ( -- versioned strategy settings, with the evidence and a rollback
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,                       -- e.g. clip_length
    platform TEXT NOT NULL,
    cohort TEXT NOT NULL,
    version INTEGER NOT NULL,
    params TEXT DEFAULT '{}',
    evidence TEXT DEFAULT '{}',
    status TEXT DEFAULT 'active',             -- active, superseded, rolled_back
    reason TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_strategies ON brain_strategies(name, platform, cohort, version);
CREATE TABLE IF NOT EXISTS brain_knowledge ( -- owner references/examples; never posting-results evidence
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    features TEXT DEFAULT '{}',
    preferences TEXT DEFAULT '{}',
    example_label TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    approved_at REAL,
    revision INTEGER DEFAULT 1,
    filename TEXT DEFAULT '',
    asset_path TEXT DEFAULT '',
    asset_sha256 TEXT DEFAULT '',
    media TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_knowledge_active ON brain_knowledge(enabled, approved_at);
CREATE TABLE IF NOT EXISTS brain_influences ( -- immutable explanations of actual blueprint choices
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    blueprint_id TEXT NOT NULL,
    knowledge_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    snapshot TEXT DEFAULT '{}',
    decisions TEXT DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_influence_once ON brain_influences(blueprint_id, knowledge_id);
CREATE INDEX IF NOT EXISTS idx_brain_influence_clip ON brain_influences(clip_id, created_at);
CREATE TABLE IF NOT EXISTS ai_usage (         -- optional cloud text AI: every request and its budget reservation
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    day TEXT NOT NULL,                        -- local day the budget counts against
    job_id TEXT DEFAULT '',
    task TEXT DEFAULT '',
    model TEXT DEFAULT '',
    status TEXT DEFAULT 'reserved',           -- reserved, done, failed, canceled
    reserved_tokens INTEGER DEFAULT 0,
    input_tokens INTEGER,                     -- NULL when the provider did not report usage
    output_tokens INTEGER,
    cost_usd REAL,                            -- NULL when unknown: never shown as $0
    error TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_day ON ai_usage(provider, day);
"""

JSON_FIELDS = {
    "projects": {"options", "info"},
    "clips": {"hooks_alt", "hashtags", "scores", "edit", "render_info", "analysis", "post"},
    "accounts": {"scopes", "info"},
    "publications": {"tags", "options", "info", "features", "audience", "delivery"},
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
    "sources": {"components", "metrics", "rights_info", "access", "channel_check", "intake"},
    "source_rights": {"conditions"},
    "publish_consents": {"settings"},
    "clip_candidates": {"scores", "rejected"},
    "clip_analysis": {"audio", "visual", "semantic", "boundary", "deep"},
    "clip_scores": {"components", "explanation"},
    "clip_fingerprints": {"text_sig", "phash"},
    "metadata_candidates": {"tags", "hashtags", "components", "problems"},
    "scheduled_publications": {"tags", "options", "slot", "scores", "approval", "audit", "audience", "delivery"},
    "slot_replacements": set(),
    "platform_limits": set(),
    "learning_metrics": {"data"},
    "quota_usage": set(),
    "api_cache": set(),
    "office_events": {"data"},
    "office_reports": {"warnings", "resources"},
    "office_decisions": {"evidence"},
    "brain_observations": {"metrics", "previous"},
    "brain_strategies": {"params", "evidence"},
    "brain_knowledge": {"tags", "features", "preferences", "media"},
    "brain_influences": {"snapshot", "decisions"},
    "ai_usage": set(),
    "quality_reports": {"checks", "blockers", "warnings", "bindings", "metadata", "coverage"},
    "clip_blueprints": {"blueprint", "issues"},
}

# Columns added after the first release. CREATE TABLE IF NOT EXISTS does not touch an existing database, so these
# are added with ALTER TABLE when missing (existing rows get the default).
ADDED_COLUMNS = {
    "clips": {"analysis": "TEXT DEFAULT '{}'", "post": "TEXT DEFAULT '{}'", "active_version": "TEXT DEFAULT ''"},
    "projects": {"origin": "TEXT DEFAULT 'manual'", "source_id": "TEXT DEFAULT ''"},
    # who may watch (publish/audience.py) and what actually happened, field by field: transfer, returned visibility,
    # audience setup (invitations, followers, manual post) and results; never one overloaded "success"
    "publications": {"scheduled_id": "TEXT DEFAULT ''", "audience": "TEXT DEFAULT '{}'",
                     "delivery": "TEXT DEFAULT '{}'"},
    "scheduled_publications": {"audience": "TEXT DEFAULT '{}'", "delivery": "TEXT DEFAULT '{}'"},
    "action_items": {"dismissed_at": "REAL"},
    "metadata_candidates": {"artifact_sha256": "TEXT DEFAULT ''"},
    # reuse terms of a rule (an agreement's credit line, commercial use, platforms, third-party material, files)
    "source_rights": {"conditions": "TEXT DEFAULT '{}'", "evidence": "TEXT DEFAULT ''"},
    # what the provider reported about a source's license, how its file was obtained, and whether the platform
    # confirmed the channel the source names (autopilot/verify.py)
    "sources": {"rights_info": "TEXT DEFAULT '{}'", "access": "TEXT DEFAULT '{}'",
                "channel_check": "TEXT DEFAULT '{}'", "user_added": "INTEGER DEFAULT 0",
                "intake": "TEXT DEFAULT '{}'"},
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    # replacements made before the history table existed count for the cooldown too (idempotent: one row per
    # replacement post)
    conn.execute(
        "INSERT OR IGNORE INTO slot_replacements (replacement_id, replaced_id, platform, slot_at, clip_id, status, "
        "created_at, updated_at) SELECT n.id, w.id, n.platform, COALESCE(w.planned_at, n.planned_at, 0), n.clip_id, "
        "CASE WHEN w.replaced_by = n.id THEN 'replaced' ELSE 'proposed' END, n.created_at, n.updated_at "
        "FROM scheduled_publications n JOIN scheduled_publications w ON (n.replaces != '' AND w.id = n.replaces) OR "
        "(w.replaced_by != '' AND w.replaced_by = n.id)")
    # secrets saved before they were sealed (the AI service keys until 2026-10-01) are sealed now, not at their next
    # save, so none stays readable in the database file
    for row in conn.execute(f"SELECT key, value FROM settings WHERE key IN ({','.join('?' * len(config.SEALED_KEYS))})",
                            sorted(config.SEALED_KEYS)).fetchall():
        try:
            value = json.loads(row["value"])
        except ValueError:
            continue
        if isinstance(value, str) and value and not value.startswith((secure.DPAPI, secure.LOCAL)):
            conn.execute("UPDATE settings SET value = ? WHERE key = ?", (json.dumps(secure.seal(value)), row["key"]))
    _migrate_audience(conn)


AUDIENCE_MIGRATION = "audience_migrated_v1"
_LEGACY_PUBLIC = {"public", "unlisted", "PUBLIC_TO_EVERYONE"}


def _legacy_intent(platform: str, privacy: str) -> str:
    """What a post planned before the audience policy amounts to. Nothing becomes wider than it was: a private
    YouTube post or a TikTok "Only me" post stays owner-only; a public one is kept but blocked."""
    if privacy in _LEGACY_PUBLIC:
        return "LEGACY_PUBLIC"
    if (platform == "youtube" and privacy == "private") or privacy == "SELF_ONLY":
        return "OWNER_ONLY"
    return "SELECTED_AUDIENCE"  # a TikTok privacy not chosen yet, or followers/friends chosen by the owner


def _migrate_audience(conn: sqlite3.Connection) -> None:
    """Once per database: stamp posts planned before the selected-audience policy with what they were, hold the
    public ones, and stop asking YouTube for public uploads by default. A copy of the database is kept first."""
    if conn.execute("SELECT 1 FROM autopilot_state WHERE key = ?", (AUDIENCE_MIGRATION,)).fetchone():
        return
    rows = conn.execute("SELECT id, platform, privacy, status, audit FROM scheduled_publications WHERE "
                        "audience IN ('', '{}') OR audience IS NULL").fetchall()
    pubs = conn.execute("SELECT id, platform, requested_privacy, status FROM publications WHERE "
                        "audience IN ('', '{}') OR audience IS NULL").fetchall()
    setting = conn.execute("SELECT value FROM settings WHERE key = 'autopilot_youtube_privacy'").fetchone()
    consents = conn.execute("SELECT COUNT(*) FROM publish_consents WHERE revoked_at IS NULL").fetchone()[0]
    now = time.time()
    if rows or pubs or setting or consents:
        conn.commit()
        backups = config.data_dir() / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        copy = sqlite3.connect(str(backups / f"clipfoundry-before-audience-v1-{int(now)}.db"))
        try:
            conn.backup(copy)
        finally:
            copy.close()
    held = 0
    for r in rows:
        want = _legacy_intent(r["platform"], r["privacy"] or "")
        stamp = {"intent": want, "platform": r["platform"], "policy_version": 0, "legacy": True,
                 "visibility": r["privacy"] or ""}
        if want == "LEGACY_PUBLIC" and r["status"] in ("awaiting_approval", "approved", "action_needed", "failed"):
            note = ("Held: planned as public before this version, which posts only to the viewers you choose. Use "
                    "“Send to my selected viewers” to plan it for them, or cancel it.")
            try:
                audit = json.loads(r["audit"] or "[]")
            except ValueError:
                audit = []
            audit.append({"at": now, "event": "audience_hold", "detail": note})
            conn.execute("UPDATE scheduled_publications SET audience = ?, status = 'blocked', status_note = ?, "
                         "approval = '{}', audit = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(stamp), note, json.dumps(audit), now, r["id"]))
            held += 1
        else:
            conn.execute("UPDATE scheduled_publications SET audience = ? WHERE id = ?", (json.dumps(stamp), r["id"]))
    for p in pubs:
        want = _legacy_intent(p["platform"], p["requested_privacy"] or "")
        stamp = {"intent": want, "platform": p["platform"], "policy_version": 0, "legacy": True,
                 "visibility": p["requested_privacy"] or ""}
        if want == "LEGACY_PUBLIC" and p["status"] == "queued":
            conn.execute("UPDATE publications SET audience = ?, status = 'cancelled', message = ?, updated_at = ? "
                         "WHERE id = ?", (json.dumps(stamp), "Not uploaded: public posting is off in this version.",
                                          now, p["id"]))
        else:
            conn.execute("UPDATE publications SET audience = ? WHERE id = ?", (json.dumps(stamp), p["id"]))
    if setting and json.loads(setting["value"] or '""') in ("public", "unlisted"):
        conn.execute("UPDATE settings SET value = ? WHERE key = 'autopilot_youtube_privacy'", (json.dumps("private"),))
    wide = [c for c in conn.execute("SELECT id, settings FROM publish_consents WHERE revoked_at IS NULL").fetchall()
            if (json.loads(c["settings"] or "{}") or {}).get("visibility") != "private"]
    for c in wide:  # a permission to publish publicly no longer covers anything: it ends, and you are asked again
        conn.execute("UPDATE publish_consents SET revoked_at = ?, updated_at = ? WHERE id = ?", (now, now, c["id"]))
    if wide:
        conn.execute("INSERT OR IGNORE INTO action_items (id, key, kind, level, title, detail, fix, ref_type, ref_id, "
                     "created_at, updated_at) VALUES (?, 'consent_renew:youtube', 'audience', 'action', ?, ?, ?, '', '', "
                     "?, ?)", (new_id(), "Turn automatic YouTube publishing on again",
                               "Your permission was for public or unlisted videos. This version uploads Private videos "
                               "only, so that permission ended.",
                               "Autopilot → Permissions & sources → Automatic publishing: read the new wording and "
                               "turn it on again.", now, now))
    conn.execute("INSERT OR REPLACE INTO autopilot_state (key, value, updated_at) VALUES (?, ?, ?)",
                 (AUDIENCE_MIGRATION, json.dumps({"at": now, "held": held, "posts": len(rows),
                                                  "uploads": len(pubs), "consents_ended": len(wide)}), now))
    if held:
        conn.execute("INSERT INTO autopilot_events (at, kind, level, message, ref_type, ref_id, data) VALUES "
                     "(?, 'audience_hold', 'warning', ?, '', '', '{}')",
                     (now, f"{held} post(s) planned as public were held: this version posts only to the viewers "
                           "you choose"))


_ready: set[str] = set()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = str(config.db_path())
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        if path not in _ready:  # API and worker processes can reach a new/old database together
            with locks.named("database-init"):
                if path not in _ready:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.executescript(SCHEMA)
                    _migrate(conn)
                    conn.commit()  # the next initializer must see all migrated columns and rows
                    for f in (path, f"{path}-wal", f"{path}-shm"):
                        secure.restrict_file(f)  # it holds (sealed) publishing tokens
                    _ready.add(path)
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


# Deleted with their clip. Kept on purpose: the post history (publications, scheduled_publications,
# slot_replacements, performance) and clip_fingerprints, which stop the same clip from being posted twice.
CLIP_CHILDREN = ("clip_versions", "clip_blueprints", "quality_reports", "clip_analysis", "clip_scores",
                 "metadata_candidates")


def delete_project(project_id: str) -> None:
    with connect() as conn:
        for table in CLIP_CHILDREN:
            conn.execute(f"DELETE FROM {table} WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
                         (project_id,))
        conn.execute("DELETE FROM clip_candidates WHERE project_id = ?", (project_id,))  # transcript windows
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
        for table in CLIP_CHILDREN:
            conn.execute(f"DELETE FROM {table} WHERE clip_id IN (SELECT id FROM clips WHERE project_id = ?)",
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
    is marked as interrupted and can be checked and published again. A YouTube upload whose final bytes may have
    been sent is held until its outcome is read; an interruption cannot authorize a duplicate. An upload waiting
    for the time a platform asked for (`info.retry_at`) keeps waiting (publish/jobs.py starts it at that time).
    """
    with connect() as conn:
        projects = [dict(r) for r in conn.execute(
            "SELECT id, source_path, source_url, info FROM projects WHERE status IN ('queued', 'processing') "
            "AND COALESCE(origin, 'manual') NOT IN ('autopilot', 'live')")]
        clips = []
        for row in conn.execute("SELECT c.id, c.render_info, p.origin, p.status AS project_status FROM clips c "
                                "JOIN projects p ON p.id = c.project_id WHERE c.status IN ('queued', 'rendering')"):
            info = (_decode("clips", row) or {}).get("render_info") or {}
            explicit = bool(info.get("manual_render_pending"))
            manual = (row["origin"] or "manual") == "manual" and row["project_status"] not in ("queued", "processing")
            if explicit or manual:
                clips.append(row["id"])
        versions = [r["id"] for r in conn.execute(
            "SELECT id FROM clip_versions WHERE status IN ('queued', 'rendering')")]
        for row in conn.execute("SELECT * FROM publications WHERE platform = 'youtube' AND status IN "
                                "('queued', 'uploading') AND COALESCE(scheduled_id, '') = ''").fetchall():
            pub = _decode("publications", row) or {}
            info = pub.get("info") or {}
            if not info.get("final_chunk_at"):
                continue
            # This durable marker is written before the last request. Even a lost/crashed reply may have posted it.
            info.update(outcome_unknown=True, code="outcome_unknown", studio_url="https://studio.youtube.com/")
            delivery = {**(pub.get("delivery") or {}), "transfer": "outcome_unknown"}
            conn.execute("UPDATE publications SET status = 'processing', info = ?, delivery = ?, error = ?, "
                         "message = ?, fix = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(info), json.dumps(delivery), "Interrupted before YouTube confirmed the outcome.",
                          "Upload outcome unknown: YouTube may already have the video. Another upload is held to "
                          "avoid a duplicate.",
                          "Open YouTube Studio → Content and use Refresh status to find the existing upload.",
                          time.time(), pub["id"]))
        waiting = [r["id"] for r in conn.execute(
            "SELECT id, info FROM publications WHERE status = 'queued' AND COALESCE(scheduled_id, '') = ''")
            if ((_decode("publications", r) or {}).get("info") or {}).get("retry_at")]
        keep = ",".join("?" * len(waiting)) or "''"
        conn.execute(
            "UPDATE publications SET status = 'failed', error = 'Interrupted (the app was closed) before the upload "
            "was confirmed. Check the platform before publishing again: the upload may or may not have finished.' "
            f"WHERE status IN ('queued', 'uploading') AND COALESCE(scheduled_id, '') = '' AND id NOT IN ({keep})",
            waiting)
    return {"projects": projects, "clips": clips, "versions": versions}
