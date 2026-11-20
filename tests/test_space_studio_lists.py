"""The lists the space studio's Projects page reads: each project's length (real, or 0 when not known) and the channel
name of a live stream being recorded."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c


def test_a_clips_project_is_listed_with_its_source_length_and_0_before_it_is_read(api):
    from clipfoundry import db

    read = db.create_project("Podcast", status="ready", duration=74.6)
    fresh = db.create_project("Still downloading", status="importing")
    items = {i["id"]: i for i in api.get("/api/studio/projects?kind=clips").json()}
    assert items[read["id"]]["duration"] == 75
    assert items[fresh["id"]]["duration"] == 0  # not known yet: the card shows no length rather than 0:00


def test_a_video_is_listed_with_its_newest_finished_render_length_only(api):
    from clipfoundry import db

    rendered = db.insert("studio_projects", {"workspace_id": "local", "name": "Lake day"})
    planned = db.insert("studio_projects", {"workspace_id": "local", "name": "Not rendered"})
    now = time.time()
    for rev, kind, seconds in ((1, "final", 61.2), (2, "final", 128.4), (3, "preview", 999.0)):
        db.execute("INSERT INTO studio_artifacts (id, project_id, revision, kind, path, sha256, info, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"art-{rev}", rendered["id"], rev, kind, f"/x/{rev}.mp4", "s",
                                                       json.dumps({"duration": seconds}), now))
    items = {i["id"]: i for i in api.get("/api/studio/projects?kind=full_video").json()}
    assert items[rendered["id"]]["duration"] == 128  # the newest final render; a preview is not the video
    assert items[planned["id"]]["duration"] == 0


def test_a_live_stream_row_names_its_channel_or_nothing(api):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    base = {"platform": "twitch", "kind": "live", "live_status": "live", "user_added": 1, "status": "ingesting",
            "intake": {"submitted": 1, "live_requested": 1, "added_at": time.time()}}
    named = db.insert("sources", {**base, "external_id": "a", "url": "https://www.twitch.tv/a", "title": "Speedruns",
                                  "channel_title": "Demo Channel"})
    unnamed = db.insert("sources", {**base, "external_id": "b", "url": "https://www.twitch.tv/b", "title": "Chat"})
    rows = {r["id"]: r for r in submissions.live_items()}
    assert rows[named["id"]]["channel"] == "Demo Channel"
    assert rows[unnamed["id"]]["channel"] == ""  # the page then shows the stream's title
    assert api.get("/api/autopilot/submissions/live").json()[0]["channel"] in ("Demo Channel", "")
