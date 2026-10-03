"""Local intent is durable, but never supplies a publishing or media-access grant."""
from types import SimpleNamespace

import pytest

from clipfoundry import config, db
from clipfoundry.autopilot import access, rights
from clipfoundry.pipeline import process, virality
from clipfoundry.pipeline.common import JobContext


@pytest.fixture
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    return tmp_path


def test_user_submission_keeps_local_intent_separate_from_reuse_and_access(data):
    src = db.insert("sources", {"platform": "youtube", "external_id": "abcdefghijkl",
                                "url": "https://www.youtube.com/watch?v=abcdefghijkl", "user_added": 1,
                                "title": "Submitted video", "status": "queued"})
    r = rights.evaluate(src)
    assert r["status"] == rights.MANUAL and not r["auto_allowed"]
    assert rights.local_allowed(src, r)
    assert not access.resolve(src, {**config.DEFAULT_SETTINGS, "autopilot_public_videos": False})["ok"]
    assert rights.apply(src)["status"] == "queued"
    assert db.fetch("sources", src["id"])["rights_status"] == rights.MANUAL
    assert not rights.url_typed_by_user(src)  # later media redirects still require public addresses
    assert not rights.local_allowed({**src, "user_added": 0}, r)
    rights.add_rule("source", src["id"], rights.BLOCKED, "Do not process")
    assert not rights.local_allowed(src)


def test_cancel_stops_future_scheduling_even_for_an_owned_source(data):
    src = db.insert("sources", {"platform": "url", "external_id": "owned-link", "user_added": 1,
                                "title": "Owned video", "status": "analyzed"})
    rights.add_rule("source", src["id"], rights.OWNED, "My original video")
    assert rights.gate(src, "schedule")["auto_allowed"]
    db.update("sources", src["id"], status="canceled", intake={"canceled": True})
    # A caller holding the pre-cancel source snapshot must still observe the durable cancel flag.
    for stage in ("schedule", "publish"):
        with pytest.raises(rights.RightsBlocked, match="Canceled by you"):
            rights.gate(src, stage)
    assert not rights.local_allowed(db.fetch("sources", src["id"]))


def test_resuming_clip_creation_keeps_completed_file_and_id(data):
    project = db.create_project("Durable analysis")
    p = SimpleNamespace(id=project["id"], sentences=[{"text": "Ask customers before building a business."}],
                        opts=config.DEFAULT_SETTINGS)
    chosen = [{"bounds": {"start": 1.0, "end": 18.0}, "s0": 0, "s1": 0, "hook": "Ask customers",
               "hooks_alt": ["Ask customers"], "category": "Education", "title": "Ask customers",
               "caption_text": "Ask customers before building a business.", "hashtags": ["#customers"],
               "score": 75.0, "scores": {}, "score_source": "Heuristic", "reason": "Useful advice",
               "analysis": {"factors": {key: 0.5 for key in virality.FACTORS}, "subscores": {},
                            "structure": {}, "flags": [], "viral_potential": 75.0}}]
    first = process.create_clips(p, chosen, JobContext(), durable=True)[0]
    path = data / "completed.mp4"
    path.write_bytes(b"completed-file-preserved")
    db.update_clip(first["id"], status="ready", output_path=str(path))
    second = process.create_clips(p, chosen, JobContext(), durable=True)[0]
    assert second["id"] == first["id"] and second["status"] == "ready"
    assert path.read_bytes() == b"completed-file-preserved"
    assert len(db.list_clips(project["id"])) == 1
