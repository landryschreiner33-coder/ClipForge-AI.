"""Real saved guidance, input-scoped reuse and pacing survive creation and publisher restarts."""
from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path

import pytest

from test_autopilot_publish import connect, env, make_item, run_publish  # noqa: F401
from test_autopilot_scheduler import make_clip
from test_review_submitted_consent_audit import add_file, data, ready_item  # noqa: F401


def test_reported_standalone_note_with_platform_tags_applies_across_topics(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge

    general = knowledge.create({"kind": "reference", "title": "Clip preferences",
                                "content": "Find strong standalone moments across topics for TikTok and "
                                           "YouTube Shorts. Prioritize:",
                                "tags": ["TikTok", "YouTube Shorts"]})
    scoped = knowledge.create({"kind": "instruction", "title": "Boxing only", "tags": ["TikTok", "boxing"],
                               "content": "Use minimal captions."})
    context = {"title": "How to bake bread", "caption_text": "The dough needs time to rise."}
    after, used = knowledge.selection_options(context, db.get_settings(), db.get_settings())
    assert after["brain_priorities"] == ["standalone"]
    assert [row["knowledge_id"] for row in used] == [general["id"]]
    assert scoped["id"] not in {row["id"] for row, _ in knowledge.matching(context, db.get_settings())}
    knowledge.edit(general["id"], {"enabled": False})
    assert knowledge.selection_options(context, db.get_settings(), db.get_settings())[0]["brain_priorities"] == []


def test_manual_creation_keeps_real_ranking_guidance_with_the_selected_clip(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import process, scoring
    from clipfoundry.pipeline.audio import Loudness
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.text_utils import build_sentences
    from synthetic_media import words_from

    lesson = knowledge.create({"kind": "reference", "title": "Standalone moments", "tags": ["TikTok"],
                               "content": "Find strong standalone moments across topics."})
    words = words_from("Bread rises because yeast releases gas. The dough traps bubbles as it rests. "
                       "That is why resting dough makes a lighter loaf.", step=.5, length=.4)
    sentences = build_sentences(words)
    settings = {**db.get_settings(), "min_duration": 3, "max_duration": 30, "target_duration": 15,
                "min_score": 0, "ai_provider": "heuristic"}
    project = db.create_project("Baking bread", duration=20, source_path=str(data / "source.mp4"))
    loud = Loudness({"hop": .1, "db": [-20.0] * 200})
    prepared = process.Prepared(project, settings, process._options(project, settings, words=words), data,
                               {"duration": 20}, {}, words, sentences, loud)
    candidates = [{"s0": 0, "s1": len(sentences) - 1, "start": words[0]["start"],
                   "end": words[-1]["end"], "dur": words[-1]["end"] - words[0]["start"], "criteria": {}}]
    ranked, _ = scoring.evaluate(candidates, sentences, prepared.opts, JobContext(), project["name"], 0, 1,
                                 words=words, loud=loud)
    assert ranked[0]["analysis"]["brain_priorities"] == ["standalone"]
    knowledge.edit(lesson["id"], {"enabled": False})
    baseline, _ = scoring.evaluate(candidates, sentences, prepared.opts, JobContext(), project["name"], 0, 1,
                                   words=words, loud=loud)
    assert baseline[0]["analysis"]["brain_priorities"] == []
    assert ranked[0]["score"] != baseline[0]["score"]
    clip = process.create_clips(prepared, ranked, JobContext())[0]
    stored = db.get_clip(clip["id"])["analysis"]["brain_knowledge"]
    assert stored[0]["knowledge_id"] == lesson["id"]
    assert stored[0]["decisions"]["ranking_priorities"]["after"] == ["standalone"]


def test_lost_intake_marker_does_not_discard_an_existing_exact_source_request(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    source = add_file(reuse_basis="owned")
    request = submissions.for_source(source)
    db.update("sources", source["id"], intake={"submitted": True, "identified": True})
    source = db.fetch("sources", source["id"])
    assert submissions.for_source(source)["id"] == request["id"]
    item, _ = ready_item(data, source)
    assert item["status"] == "approved" and item["approval"]["by"] == "submission"
    assert scheduler.approval_valid(item)
    db.update("source_submissions", request["id"], revoked_at=time.time())
    assert submissions.problem(source) and not submissions.still_covers(item)


def test_queue_review_carries_source_reuse_without_retyping_it(data):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler, submissions

    source = add_file(reuse_basis="owned")
    item, _clip = ready_item(data, source)
    # A quality/manual review can remain necessary without asking to repeat the source reuse declaration.
    db.update("scheduled_publications", item["id"], status="awaiting_approval", approval={}, reuse_confirmation={})
    pending = db.fetch("scheduled_publications", item["id"])
    review = rights.review_info(pending)
    assert review["confirmed"] and review["confirmed_from"] == "source_submission"
    assert submissions.for_source(source)["settings"]["reuse_statement"] in review["basis"]
    approved = scheduler.approve(item["id"], {})
    assert approved["approval"]["by"] == "you"
    assert approved["reuse_confirmation"]["confirmed_from"] == "source_submission"
    assert scheduler.approval_valid(approved)


def test_automatic_repair_gets_fresh_exact_file_approval_without_reasking_source_reuse(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions
    from quality_stub import passed_report

    source = add_file(reuse_basis="owned")
    item, clip = ready_item(data, source)
    original_hash = item["approval"]["hash"]
    Path(clip["output_path"]).write_bytes(b"new automatically repaired video bytes")
    scheduler.process_due(db.get_settings(), time.time() + 1)
    pending = db.fetch("scheduled_publications", item["id"])
    assert pending["status"] == "awaiting_approval"
    assert not submissions.auto_approve(pending, db.get_settings(), time.time())
    passed_report(db.get_clip(clip["id"]))
    assert submissions.auto_approve(db.fetch("scheduled_publications", item["id"]), db.get_settings(), time.time())
    renewed = db.fetch("scheduled_publications", item["id"])
    assert renewed["approval"]["hash"] != original_hash and renewed["approval"]["by"] == "submission"
    assert scheduler.approval_valid(renewed)


def test_owner_selected_version_does_not_become_an_automatic_repair(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions
    from quality_stub import passed_report

    source = add_file(reuse_basis="owned")
    item, clip = ready_item(data, source)
    output = data / "owner-selected-version.mp4"
    output.write_bytes(b"different owner-selected generated variant")
    variant = db.create_version(clip["id"], "alt_captions", edit={"caption_style": "clean"},
                                status="ready", output_path=str(output))
    # The active-version API selects this field without writing a post edit audit or clip.edit.
    db.update_clip(clip["id"], active_version=variant["id"])
    scheduler.process_due(db.get_settings(), time.time() + 1)
    pending = db.fetch("scheduled_publications", item["id"])
    assert pending["status"] == "awaiting_approval" and not db.get_clip(clip["id"])["edit"]
    passed_report(db.get_clip(clip["id"]))
    assert not submissions.auto_approve(pending, db.get_settings(), time.time())
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    # Source reuse still carries through the owner's exact-version review without retyping.
    approved = scheduler.approve(item["id"], {})
    assert approved["approval"]["by"] == "you" and scheduler.approval_valid(approved)


def test_old_backlog_and_other_inputs_never_inherit_source_reuse(data):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    original = add_file(reuse_basis="owned")
    item, _ = ready_item(data, original)
    another = add_file("Other.mp4", b"different original", auto_upload=False, agreed=False)
    clip = make_clip(data, "Another completely unrelated video", 90, source=another)
    assert submissions.reuse_confirmation({**item, "clip_id": clip["id"], "source_id": another["id"]},
                                           db.get_settings()) is None
    db.update("clips", item["clip_id"], created_at=submissions.for_source(original)["created_at"] - 1)
    assert submissions.reuse_confirmation(item, db.get_settings()) is None


def test_same_batch_and_concurrent_replanning_get_distinct_times(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    db.save_settings({"autopilot_input_mode": "discovery", "autopilot_min_gap_minutes": 30,
                      "autopilot_active_start": 0, "autopilot_active_end": 24})
    for index in range(6):
        make_clip(data, f"Independently selected story {index}", 90)
    now = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: scheduler.plan_new(db.get_settings(), now), range(2)))
    assert sum(result["created"] for result in results) == 6
    times = sorted(row["planned_at"] for row in db.select("scheduled_publications"))
    assert times[0] == pytest.approx(now)
    assert all(b - a >= 1800 for a, b in zip(times, times[1:]))


def test_pending_collision_repair_keeps_approval_and_manual_times(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    now = time.time()
    rows = []
    for index in range(4):
        item = make_item(data, approve={"options": {"made_for_kids": False}})
        db.update("scheduled_publications", item["id"], planned_at=now + 600,
                  audit=[*item["audit"], *([{"event": "rescheduled", "detail": "Moved by you"}]
                                          if index == 0 else [])])
        rows.append(db.fetch("scheduled_publications", item["id"]))
    assert scheduler.space_pending_posts(db.get_settings(), now) == 3
    after = [db.fetch("scheduled_publications", row["id"]) for row in rows]
    assert after[0]["planned_at"] == rows[0]["planned_at"]
    assert [row["approval"] for row in after] == [row["approval"] for row in rows]
    times = sorted(row["planned_at"] for row in after)
    assert all(b - a >= 1800 for a, b in zip(times, times[1:]))
    assert scheduler.space_pending_posts(db.get_settings(), now) == 0


def test_dispatch_spacing_reservation_is_atomic_and_survives_restart(data):
    from clipfoundry import config, db
    from clipfoundry.autopilot import scheduler

    now = time.time()
    settings = db.get_settings()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        waits = list(executor.map(lambda i: scheduler.reserve_upload_spacing(
            {"id": f"post-{i}", "platform": "youtube"}, settings, now), range(4)))
    assert waits.count(0) == 1 and sorted(waits) == [0, 1800, 1800, 1800]
    db._ready.discard(str(config.db_path()))
    db.init()
    assert scheduler.reserve_upload_spacing({"id": "later", "platform": "youtube"}, settings, now + 600) == 1200


def test_long_platform_wait_and_slow_completion_do_not_release_a_burst(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler

    now = time.time()
    settings = db.get_settings()
    first = {"id": "first", "platform": "youtube"}
    other = {"id": "other", "platform": "youtube"}
    assert scheduler.reserve_upload_spacing(first, settings, now) == 0
    # The platform resumes hours later. Merely keeping the original queue-time reservation would allow both.
    assert scheduler.reserve_upload_spacing(first, settings, now + 7200, starting=True) == 0
    assert scheduler.reserve_upload_spacing(other, settings, now + 7201) == 1799
    scheduler.record_upload_finished(first, now + 8400)
    assert scheduler.reserve_upload_spacing(other, settings, now + 9000) == 1200


def test_same_time_queued_jobs_upload_spaced_not_in_a_burst(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_min_gap_minutes": 30})
    first = make_item(tmp, approve={"options": {"made_for_kids": False}})
    second = make_item(tmp, text="A volcano forms when molten rock reaches the surface and cools into layers.",
                       approve={"options": {"made_for_kids": False}})
    run_publish(first["id"])
    with pytest.raises(queue.Wait) as waiting:
        run_publish(second["id"])
    assert waiting.value.reason == "upload_spacing"
    assert len(google.videos) == 1
    assert db.fetch("scheduled_publications", second["id"])["approval"]["hash"] == second["approval"]["hash"]
    clock = time.time() + 1801
    monkeypatch.setattr(time, "time", lambda: clock)
    run_publish(second["id"])
    assert len(google.videos) == 2
    run_publish(first["id"])
    assert len(google.videos) == 2


def test_spacing_upgrade_is_once_and_preserves_future_explicit_choices(data):
    from clipfoundry import config, db

    db.save_settings({"autopilot_min_gap_minutes": 0})
    with db.connect() as conn:
        conn.execute("DELETE FROM autopilot_state WHERE key=?", (db.POST_SPACING_MIGRATION,))
    db._ready.discard(str(config.db_path()))
    db.init()
    assert db.get_settings()["autopilot_min_gap_minutes"] == 30
    db.save_settings({"autopilot_min_gap_minutes": 12})
    db._ready.discard(str(config.db_path()))
    db.init()
    assert db.get_settings()["autopilot_min_gap_minutes"] == 12
