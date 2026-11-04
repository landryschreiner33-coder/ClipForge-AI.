"""API retention discards stale readings without deleting an explicit input's source or request."""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from test_autopilot_intake import data  # noqa: F401 - isolated DB and no network resolver


@pytest.mark.parametrize("status", ["failed", "canceled"])
@pytest.mark.parametrize("age_from", ["source", "signal"])
def test_retention_preserves_submitted_source_and_consent_but_clears_stale_api_data(data, status, age_from):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scout, submissions

    now, old = time.time(), time.time() - 31 * 86400
    db.save_account("youtube", tokens={"access_token": "isolated-retention-token"}, account_id="UC-retention")
    setup = submissions.setup()
    request = submissions.add_link("https://youtu.be/retention01", {
        "auto_upload": True, "account_id": setup["account_id"], "privacy": setup["privacy"],
        "made_for_kids": False, "audience_version": setup["audience"]["group_version"],
        "reuse_basis": "permission", "reuse_statement": "My source-specific creator agreement.", "agreed": True})
    source = db.fetch("sources", request["item"]["id"])
    grant = submissions.for_source(source)
    local = submissions.add_file(io.BytesIO(b"owner file retained byte for byte"), "original.mp4", {"auto_upload": False})
    local_source = db.fetch("sources", local["item"]["id"])
    local_grant = submissions.for_source(local_source)
    signal = db.insert("trend_signals", {"provider": "youtube_search", "platform": "youtube", "external_id": "old",
                                          "first_seen": old, "last_checked": old})
    db.execute("INSERT INTO trend_history (signal_id,at,views) VALUES (?,?,5)", (signal["id"], old))
    db.update("sources", source["id"], status=status, metrics={"views": 40},
              signal_id=signal["id"] if age_from == "signal" else "")
    db.execute("UPDATE sources SET updated_at=? WHERE id=?", (old if age_from == "source" else now, source["id"]))
    source = db.fetch("sources", source["id"])
    ordinary = db.insert("sources", {"platform": "youtube", "external_id": "old-unreferenced-discovery",
                                       "status": "failed", "updated_at": old, "metrics": {"views": 12}})
    db.execute("INSERT INTO performance (id,publication_id,platform,fetched_at,views) VALUES (?,?,?,?,3)",
               ("old-api-reading", "unreferenced-publication", "youtube", old))
    db.execute("INSERT INTO api_cache (key,response,fetched_at,expires_at) VALUES (?,?,?,?)",
               ("old-api-cache", "{}", old, old + 300))
    rights_before = rights.evaluate(source)

    result = scout.youtube_retention(now=now)

    assert result["youtube_sources_deleted"] == 1 and result["youtube_sources_cleared"] == 1
    assert result["youtube_signals_deleted"] == 1 and result["youtube_snapshots_deleted"] == 1
    assert db.fetch("sources", source["id"]) == {**source, "metrics": {}, "updated_at": now}
    assert db.fetch("source_submissions", grant["id"]) == grant
    assert rights.evaluate(db.fetch("sources", source["id"])) == rights_before
    assert not db.fetch("sources", ordinary["id"])
    assert not db.select("trend_signals") and not db.select("trend_history")
    assert not db.select("performance") and not db.select("api_cache")
    assert db.fetch("sources", local_source["id"]) == local_source
    assert db.fetch("source_submissions", local_grant["id"]) == local_grant
    assert Path(local_source["local_path"]).read_bytes() == b"owner file retained byte for byte"
    assert not db.select("source_rights") and not db.select("publications")
