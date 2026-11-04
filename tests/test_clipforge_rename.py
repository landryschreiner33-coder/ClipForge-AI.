"""CF-15: an existing ClipFoundry profile opens under the ClipForge name with everything it had.

The product name changed; the data folder, database file, secrets, account IDs, approvals and history did not. No
new empty profile is created and the old addresses and settings keys keep working.
"""
from __future__ import annotations

import json
import sqlite3

from test_autopilot_publish import H


def test_old_profile_opens_with_the_same_projects_notes_accounts_and_history(monkeypatch, tmp_path):
    from clipfoundry import config, db

    data = tmp_path / "ClipFoundry data"
    data.mkdir()
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(data))
    old_schema = db.SCHEMA.split("-- ---------------------------------------------------------------- ClipForge")[0]
    conn = sqlite3.connect(data / "clipfoundry.db")
    conn.executescript(old_schema)
    conn.execute("INSERT INTO projects (id, name, created_at, updated_at, status) VALUES ('p1', 'Old talk', 1, 1, "
                 "'ready')")
    conn.execute("INSERT INTO clips (id, project_id, start, end, created_at, updated_at, status) VALUES ('c1', 'p1', 0, "
                 "20, 1, 1, 'ready')")
    conn.execute("INSERT INTO brain_knowledge (id, kind, title, content, tags, features, preferences, enabled, "
                 "created_at, updated_at) VALUES ('k1', 'instruction', 'Lower captions', '', '[]', '{}', "
                 "'{\"caption_position\": \"bottom\"}', 1, 1, 1)")
    conn.execute("INSERT INTO accounts (platform, account_id, display_name, tokens, connected_at, updated_at) "
                 "VALUES ('youtube', 'UCowner', 'Owner channel', 'local:e30=', 1, 1)")
    approval = json.dumps({"approved_account": "UCowner", "approved_video_sha256": "ab" * 32})
    conn.execute("INSERT INTO publications (id, clip_id, platform, status, options, created_at, updated_at) VALUES "
                 "('pub1', 'c1', 'youtube', 'done', ?, 1, 1)", (approval,))
    conn.execute("INSERT INTO settings (key, value) VALUES ('caption_style', '\"bold\"')")
    conn.commit()
    conn.close()
    before = sorted(p.name for p in tmp_path.iterdir())

    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        assert config.APP_NAME == "ClipForge" and api.app.title == "ClipForge"
        assert [p["name"] for p in api.get("/api/projects").json()] == ["Old talk"]
        assert api.get("/api/clips/c1").status_code == 200
        notes = api.get("/api/brain/knowledge").json()
        assert [n["title"] for n in notes] == ["Lower captions"]
        accounts = api.get("/api/connections").json()["connections"]
        assert [(a["account_id"], a["display_name"], a["is_default"]) for a in accounts] == [
            ("UCowner", "Owner channel", True)]
        pub = db.get_publication("pub1")
        assert pub["options"] == json.loads(approval) and pub["connection_id"] == db.legacy_connection_id("youtube")
        assert api.get("/api/settings").json()["caption_style"] == "bold"  # old settings keys still work
        assert "ClipForge" in api.get("/").text  # the page itself carries the new name
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no new profile folder appeared
    assert (data / "clipfoundry.db").exists() and not (tmp_path / "ClipForge").exists()


def test_old_publish_header_is_still_accepted(monkeypatch, tmp_path):
    """The X-ClipFoundry request header stays the publish guard's name (compatibility, docs/clipforge/RENAME_PLAN.md)."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "d"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        assert api.post("/api/publish/youtube/connect").status_code == 403
        assert api.post("/api/publish/youtube/connect", headers=H).status_code in (200, 400)
