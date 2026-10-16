"""Reuse answers belong to the exact post; Brain guidance remains explicitly saved owner material."""
from __future__ import annotations

import json
import time

import pytest

from test_review_bulk import data, draft  # noqa: F401

H = {"X-ClipFoundry": "1"}
BRAIN_TABLES = ("brain_knowledge", "brain_influences", "brain_observations", "brain_strategies")
PRIVATE_BASIS = "Creator agreement CF-private-review-672 permits this exact clip with its original sound."


def _brain_snapshot() -> dict:
    from clipfoundry import db

    return {table: db.select(table, "", (), "id") for table in BRAIN_TABLES}


def _saved_brain(clip: dict) -> dict:
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge

    lesson = knowledge.create({"kind": "instruction", "title": "Readable lessons",
                               "content": "Prefer complete stories. Use minimal captions."})
    # An owner may explicitly keep a rights-related reference. Reviewing a post must not alter or remove it.
    knowledge.create({"kind": "reference", "title": "My deliberately saved source reference",
                      "content": "The creator's agreement is filed with my own records."})
    db.insert("brain_influences", {"clip_id": clip["id"], "blueprint_id": "existing-plan",
                                   "knowledge_id": lesson["id"], "revision": 1,
                                   "snapshot": {"title": lesson["title"]},
                                   "decisions": {"caption_style": {"before": "bold", "after": "minimal"}}})
    brain.add(clip["id"], "", "tester_feedback", {"hook": 4}, tester="test viewer")
    db.insert("brain_strategies", {"name": "clip_length", "platform": "youtube", "cohort": "selected",
                                   "version": 1, "params": {"target_duration": 33},
                                   "evidence": {"source": "existing synthetic test evidence"}})
    return _brain_snapshot()


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("reuse_kind", ["custom", "creator_permission"])
def test_reuse_form_keeps_existing_brain_unchanged_and_records_only_selected_posts(data, mode, reuse_kind):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app
    from clipfoundry.autopilot import bulk_review, knowledge, rights, scheduler

    first, first_clip, first_source = draft(data)
    second, _clip, second_source = draft(data, "Another complete thought to review")
    before = _saved_brain(first_clip)
    selected = [first["id"], second["id"]] if mode == "bulk" else [first["id"]]
    expected_basis = bulk_review.resolve_reuse_basis(reuse_kind, PRIVATE_BASIS)
    body = {"confirm": True, "reuse_confirmed": True, "reuse_kind": reuse_kind,
            "reuse_basis": PRIVATE_BASIS, "made_for_kids": False}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        if mode == "bulk":
            preview = client.post("/api/autopilot/scheduled/bulk-preview", headers=H,
                                  json={"ids": selected})
            assert preview.status_code == 200
            assert preview.json()["eligible_ids"] == selected
            response = client.post("/api/autopilot/scheduled/bulk-approve", headers=H,
                                   json={**body, "token": preview.json()["token"]})
            assert response.status_code == 200 and response.json()["approved"] == len(selected)
        else:
            response = client.post(f"/api/autopilot/scheduled/{first['id']}/approve", headers=H, json=body)
            assert response.status_code == 200

        for item_id in selected:
            saved = db.fetch("scheduled_publications", item_id)
            assert saved["status"] == "approved" and scheduler.approval_valid(saved)
            confirmation = saved["reuse_confirmation"]
            assert confirmation["owner_confirmed"] is True and confirmation["basis"] == expected_basis
            assert confirmation["binding"]["scheduled_id"] == item_id
            assert not rights.confirmation_problem(saved)
            detail = client.get(f"/api/autopilot/scheduled/{item_id}").json()["item"]
            assert detail["reuse_review"]["confirmed"] and detail["reuse_review"]["basis"] == expected_basis

        assert _brain_snapshot() == before
        exported = client.get("/api/brain/knowledge/export")
        assert exported.status_code == 200 and PRIVATE_BASIS not in exported.text
        assert knowledge.get(before["brain_knowledge"][1]["id"])["content"] == before["brain_knowledge"][1]["content"]

    if mode == "single":
        untouched = db.fetch("scheduled_publications", second["id"])
        assert untouched["status"] == "awaiting_approval" and not untouched["reuse_confirmation"]
    for source in (first_source, second_source):
        assert rights.evaluate(db.fetch("sources", source["id"]))["status"] == rights.MANUAL
    assert not db.select("source_rights") and not db.select("publish_consents")
    assert not db.select("publications") and not db.select("performance")


def test_real_metric_ingestion_and_learning_features_never_copy_reuse_details(data):
    from clipfoundry import db, learning
    from clipfoundry.autopilot import brain, learner, rights, scheduler

    item, clip, _source = draft(data, kids=False)
    approved = scheduler.approve(item["id"], {}, reuse_confirmed=True, reuse_basis=PRIVATE_BASIS)
    before_knowledge = db.select("brain_knowledge")
    before_influences = db.select("brain_influences")
    before_strategies = db.select("brain_strategies")
    # Only an isolated synthetic record: no publish worker or external account is called.
    pub = db.create_publication(clip["id"], "youtube", status="done", scheduled_id=item["id"],
                                options={"made_for_kids": False,
                                         "reuse_confirmation": approved["reuse_confirmation"]},
                                features={"duration": clip["duration"], "viral_potential": 90},
                                audience=approved["audience"])
    now = time.time()
    db.execute("UPDATE publications SET created_at = ? WHERE id = ?", (now - 3 * 86400, pub["id"]))
    db.execute("UPDATE clips SET created_at = ? WHERE id = ?", (now - 3 * 86400 - 3600, clip["id"]))
    pub = db.get_publication(pub["id"])
    db.add_performance(pub, {"views": 120, "likes": 3, "comments": 0}, "synthetic test API", [], {})
    assert brain.ingest_platform(pub) == 1
    assert brain.ingest_platform(pub) == 0  # the same reading stays idempotent
    observed = brain.observations(clip["id"])
    assert observed[0]["metrics"] == {"views": 120, "likes": 3, "comments": 0}
    assert observed[0]["note"] == "" and observed[0]["origin"] == "youtube API"
    learned = learner.rows(db.get_settings())
    assert len(learned) == 1 and learned[0]["views"] == 120
    assert len(learning.dataset()) == 1
    evidence = json.dumps({"observations": observed, "features": learned, "dataset": learning.dataset()})
    assert PRIVATE_BASIS not in evidence and "reuse_confirmation" not in evidence
    assert "reuse_basis" not in evidence and "owner_confirmed" not in evidence
    assert db.get_publication(pub["id"])["options"]["reuse_confirmation"] == approved["reuse_confirmation"]
    assert not rights.confirmation_problem(db.fetch("scheduled_publications", item["id"]))
    assert db.select("brain_knowledge") == before_knowledge
    assert db.select("brain_influences") == before_influences
    assert db.select("brain_strategies") == before_strategies
