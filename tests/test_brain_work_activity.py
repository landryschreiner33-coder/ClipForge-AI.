"""The office describes real saved-guidance use separately from results learning and idle history."""
from __future__ import annotations

import json
import threading
import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    db.save_settings({"autopilot_enabled": True})
    return tmp_path


def lesson(**fields):
    from clipfoundry.autopilot import knowledge

    return knowledge.create({"kind": "reference", "title": "Private saved lesson title",
                             "content": "Use minimal captions. Prioritize payoff. PrivateNoteSentinel",
                             **fields})


def consultations():
    from clipfoundry import db
    from clipfoundry.autopilot import brain

    return db.select("office_events", "type IN (?, ?, ?)", brain.CONSULTATION_EVENTS, "id ASC")


def test_live_guidance_lookup_finishes_and_is_never_confused_with_mature_results(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge

    lesson()
    settings = db.get_settings()
    with brain.consultation("blueprint", settings, ref=("clip", "c1")):
        active = brain.summary(settings)
        assert active["state"] == "cold_start" and active["min_clips"] == 30
        assert active["enabled_guidance"] == 1
        assert active["activity"]["state"] == "working"
        assert active["activity"]["ref_id"] == "c1" and active["activity"]["role"] == "synapse"
        options, _ = knowledge.choose({}, {"caption_style": "bold"}, settings)
        assert options["caption_style"] == "minimal"
    summary = brain.summary(settings)
    assert summary["activity"]["state"] == "idle"
    assert summary["activity"]["last"]["state"] == "done"
    assert summary["activity"]["last"]["consulted"] == 1
    assert summary["activity"]["last"]["applied"] == 1
    assert summary["activity"]["last"]["lookups"] == 1
    assert "Enabled saved guidance" in summary["message"] and "mature evidence" in summary["message"]
    events = consultations()
    assert [e["type"] for e in events] == ["brain_consultation_started", "brain_consultation_done"]
    assert events[-1]["data"]["handoff_path"] == ["synapse", "curator", "command"]
    assert events[-1]["data"]["handoff_kind"] == "report"
    assert "Private" not in json.dumps(events) and "PrivateNoteSentinel" not in json.dumps(summary)
    assert not db.select("brain_observations") and not db.select("brain_strategies")


def test_reads_and_previews_never_create_activity_or_change_knowledge(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge, knowledge_routes

    row = lesson()
    before = knowledge.get(row["id"])
    cursor = db.scalar("SELECT COALESCE(MAX(id), 0) FROM office_events")
    for _ in range(3):
        assert knowledge.choose({}, {}, db.get_settings())[0]["caption_style"] == "minimal"
        knowledge.selection_options({}, db.get_settings(), db.get_settings())
        knowledge_routes.preview(knowledge_routes.Preview(text="A complete story"))
        assert knowledge_routes.workspace()["brain"]["activity"]["state"] == "idle"
        assert brain.summary()["activity"]["last"] is None
    assert not consultations() and knowledge.get(row["id"]) == before
    assert db.scalar("SELECT COALESCE(MAX(id), 0) FROM office_events") == cursor


def test_paused_empty_and_disabled_memory_do_not_invent_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge
    from clipfoundry.pipeline import process

    settings = db.get_settings()
    process._options({"id": "p1", "name": "Source"}, settings)
    assert not consultations()
    row = lesson(enabled=False)
    process._options({"id": "p1", "name": "Source"}, settings)
    assert not consultations()
    knowledge.edit(row["id"], {"enabled": True})
    paused = {**settings, "brain_paused": True}
    options = process._options({"id": "p1", "name": "Source"}, paused)
    assert options["caption_style"] == paused["caption_style"] and options["brain_consulted"] == 0
    assert not consultations() and brain.summary(paused)["activity"]["state"] == "idle"


def test_topic_misses_are_scanned_without_claiming_a_changed_decision(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain
    from clipfoundry.pipeline import process

    lesson(tags=["science"])
    options = process._options({"id": "p1", "name": "Cooking"}, db.get_settings())
    assert options["brain_consulted"] == 0 and not options["brain_priorities"]
    last = brain.summary()["activity"]["last"]
    assert last["lookups"] == 1 and last["consulted"] == 0 and last["applied"] == 0


def test_failure_finalizes_activity_without_logging_private_exception_text(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge
    from clipfoundry.pipeline import process

    lesson()
    original_compile = knowledge.compile_note

    def broken(_):
        raise ValueError("PrivateNoteSentinel failure")

    monkeypatch.setattr(knowledge, "compile_note", broken)
    with pytest.raises(ValueError, match="PrivateNoteSentinel"):
        process._options({"id": "p1", "name": "Source"}, db.get_settings())
    activity = brain.summary()["activity"]
    assert activity["state"] == "idle" and activity["last"]["state"] == "failed"
    assert len(consultations()) == 2 and "PrivateNoteSentinel" not in json.dumps(consultations())
    assert consultations()[-1]["data"]["handoff_path"] == ["synapse", "curator"]
    monkeypatch.setattr(knowledge, "compile_note", original_compile)
    # A failed span cannot capture a later unrelated preview through a leaked context variable.
    before = len(consultations())
    knowledge.choose({}, {}, db.get_settings())
    assert len(consultations()) == before


def test_real_ranking_batch_consults_many_candidates_but_emits_one_pair(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain
    from clipfoundry.pipeline import scoring
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.text_utils import build_sentences

    lesson()
    original = [{"text": "Here is why practice matters.", "start": 0, "end": 5},
                {"text": "I practiced every day for a year.", "start": 5, "end": 10},
                {"text": "In the end I learned to stay consistent.", "start": 10, "end": 15}]
    sentences = build_sentences(scoring._words_from_sentences(original))
    candidates = [{"cid": n, "s0": 0, "s1": 2, "start": 0, "end": 15, "dur": 15, "criteria": {}}
                  for n in range(3)]
    results, notes = scoring.evaluate(candidates, sentences, db.get_settings(), JobContext(), "Source", 0, 1)
    assert len(results) == 3 and notes["brain_consulted"] == 1
    last = brain.summary()["activity"]["last"]
    assert last["purpose"] == "ranking" and last["lookups"] == 3
    assert last["consulted"] == 3 and last["applied"] == 3 and len(consultations()) == 2


def test_empty_ranking_or_work_cancelled_before_start_does_not_invent_a_lookup(data):
    from clipfoundry import db
    from clipfoundry.pipeline import scoring
    from clipfoundry.pipeline.common import Cancelled, JobContext

    lesson()
    results, _ = scoring.evaluate([], [], db.get_settings(), JobContext(), "Source", 0, 1)
    assert results == [] and not consultations()
    with pytest.raises(Cancelled):
        scoring.evaluate([{}], [], db.get_settings(), JobContext(is_cancelled=lambda: True), "Source", 0, 1)
    assert not consultations()


def test_manual_override_is_preserved_and_not_counted_as_an_applied_preference(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    lesson()
    project = {"id": "p1", "width": 1080, "height": 1920, "source_path": "unused.mp4", "duration": 1}
    clip = {"id": "c1", "start": 0, "end": .2, "edit": {"caption_style": "bold"}}
    # The actual render boundary rejects the short clip after its real guidance/override decision; no media needed.
    with pytest.raises(ValueError, match="shorter than one second"):
        render.render_clip(project, clip, [], db.get_settings(), JobContext())
    last = brain.summary()["activity"]["last"]
    assert last["purpose"] == "render" and last["consulted"] == 1 and last["applied"] == 0


def test_abandoned_future_and_completed_spans_never_show_live_work(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain
    from clipfoundry.office import feed

    now = time.time()
    event_id = feed.emit("brain_consultation_started", "synapse", consultation_id="abandoned", purpose="ranking")
    db.execute("UPDATE office_events SET at = ? WHERE id = ?", (now - brain.CONSULTATION_SECONDS - 1, event_id))
    assert brain.work_activity(db.get_settings(), now)["state"] == "idle"
    db.execute("UPDATE office_events SET at = ? WHERE id = ?", (now + 60, event_id))
    assert brain.work_activity(db.get_settings(), now)["state"] == "idle"
    db.execute("UPDATE office_events SET at = ? WHERE id = ?", (now, event_id))
    assert brain.work_activity(db.get_settings(), now)["state"] == "working"
    assert brain.work_activity({**db.get_settings(), "brain_paused": True}, now)["state"] == "idle"
    feed.emit("brain_consultation_done", "curator", consultation_id="abandoned", purpose="ranking")
    assert brain.work_activity(db.get_settings(), now + 1)["state"] == "idle"
    # Newer unrelated traffic cannot make an old start appear unmatched or promote completed history to work.
    with db.connect() as conn:
        conn.executemany("INSERT INTO office_events (at,type,role,data) VALUES (?, 'test', '', '{}')",
                         [(now,)] * 250)
    assert brain.work_activity(db.get_settings(), now + 2)["state"] == "idle"


def test_parallel_and_nested_consultations_are_independent_and_finish_cleanly(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain, knowledge

    lesson()
    settings = db.get_settings()
    started, finish = threading.Event(), threading.Event()
    errors = []

    def parallel():
        try:
            with brain.consultation("ranking", settings, ref=("project", "other")):
                knowledge.selection_options({}, settings, settings)
                started.set()
                assert finish.wait(5)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=parallel)
    thread.start()
    assert started.wait(5)
    try:
        with brain.consultation("blueprint", settings, ref=("clip", "mine")):
            with brain.consultation("render", settings):
                knowledge.choose({}, {"caption_style": "bold"}, settings)
        still_working = brain.work_activity(settings)
        assert still_working["state"] == "working" and still_working["ref_id"] == "other"
    finally:
        finish.set()
        thread.join(5)
    assert not thread.is_alive() and not errors
    assert brain.work_activity(settings)["state"] == "idle"
    events = consultations()
    assert len(events) == 4
    finished = [e for e in events if e["type"] == "brain_consultation_done"]
    assert len({e["data"]["consultation_id"] for e in finished}) == 2
    assert all(e["data"]["consulted"] == 1 and e["data"]["applied"] == 1 for e in finished)
