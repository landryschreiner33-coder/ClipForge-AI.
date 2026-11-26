"""Missions → Advanced → Workers: a worker that has never started has no heartbeat, so its row says only
"Not started", never "(last heard Invalid Date)"."""
from __future__ import annotations

from pathlib import Path

FRONT = Path(__file__).resolve().parents[1] / "frontend" / "src"


def test_a_worker_that_never_started_has_no_heartbeat(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.autopilot import routes

    db.init()
    rows = routes.workers()["workers"]
    assert rows
    for w in rows:
        # what the page gets for a worker with no row yet: stale, and no time it was last heard
        assert w["message"] == "Not started" and w["stale"] is True and not w.get("heartbeat")


def test_the_last_heard_time_shows_only_when_there_is_one():
    src = (FRONT / "components" / "apAdvanced.tsx").read_text(encoding="utf-8")
    assert "w.stale && w.heartbeat ? ` (last heard ${timeAgo(w.heartbeat)})`" in src
    assert "w.stale ? ` (last heard" not in src
    assert "heartbeat?: number;" in (FRONT / "autopilot.ts").read_text(encoding="utf-8")
