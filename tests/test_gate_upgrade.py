"""A new final check (quality.GATE_VERSION) makes every stored report out of date. A post waiting to be approved,
automatically or in a batch, must ask for the new check itself: nothing else does for a post that is already
planned (batch 5c review)."""
from __future__ import annotations

import time

from quality_stub import passed_report
from test_autopilot_publish import connect, env, make_item  # noqa: F401
from test_review_bulk import data as bulk_data  # noqa: F401
from test_review_bulk import draft
from test_review_submitted_consent_audit import add_file, data, ready_item  # noqa: F401


def _older_gate(clip_id: str) -> None:
    from clipfoundry import db
    from clipfoundry.pipeline import quality

    db.execute("UPDATE quality_reports SET gate_version = ? WHERE clip_id = ?", (quality.GATE_VERSION - 1, clip_id))


def _requests(monkeypatch) -> list[tuple[str, dict]]:
    from clipfoundry.autopilot import gate

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(gate, "request", lambda clip, *a, **k: calls.append((clip["id"], k)))
    return calls


def test_automatic_publishing_asks_for_the_new_check_of_a_waiting_post(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import autopublish, scheduler

    g, t, tmp = env
    connect(g, t)
    autopublish.enable("youtube", "private", False, 3, 0, 24, True)
    item = make_item(tmp, planned_in=600)
    _older_gate(item["clip_id"])
    calls = _requests(monkeypatch)
    assert not scheduler.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())
    assert [c for c, _ in calls] == [item["clip_id"]]
    assert "has not run yet" in db.fetch("scheduled_publications", item["id"])["status_note"]
    # once the new check has passed, the next tick approves it
    passed_report(db.get_clip(item["clip_id"]))
    assert scheduler.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())


def test_an_upload_request_asks_for_the_new_check_of_a_waiting_post(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    item, clip = ready_item(data, add_file(reuse_basis="owned"))
    db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={})
    _older_gate(clip["id"])
    calls = _requests(monkeypatch)
    assert not submissions.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())
    assert [c for c, _ in calls] == [clip["id"]]
    passed_report(db.get_clip(clip["id"]))
    assert submissions.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())


def test_a_batch_review_starts_the_new_check_and_says_so(bulk_data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import bulk_review

    item, clip, _ = draft(bulk_data)
    _older_gate(clip["id"])
    calls = _requests(monkeypatch)
    row = bulk_review.preview([item["id"]])["items"][0]
    assert not row["eligible"] and "The check has started" in row["reason"]
    assert calls == [(clip["id"], {"priority": 100, "sha": ""})]
    passed_report(db.get_clip(clip["id"]))
    assert bulk_review.preview([item["id"]])["items"][0]["eligible"]
