"""An explicit source grant applies only to new work from that input, never a channel or Brain lesson."""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from quality_stub import passed_report
from test_autopilot_publish import connect, env, run_publish  # noqa: F401 - fake platforms, never real accounts
from test_autopilot_scheduler import make_clip


BRAIN_TABLES = ("brain_knowledge", "brain_influences", "brain_observations", "brain_strategies")
PRIVATE_STATEMENT = "Creator approval filed as private test agreement CF-source-481."


@pytest.fixture
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_tiktok": False, "autopilot_youtube": True,
                      "autopilot_review_before_publish": True, "autopilot_input_mode": "submitted"})
    db.save_account("youtube", tokens={"access_token": "isolated-source-token"}, account_id="UCsource-audit",
                    display_name="Isolated source channel")
    return tmp_path


def options(**changes):
    from clipfoundry.autopilot import submissions

    shown = submissions.setup()
    return {"auto_upload": True, "account_id": "UCsource-audit", "privacy": "private", "made_for_kids": False,
            "audience_version": shown["audience"]["group_version"], "reuse_basis": "permission",
            "reuse_statement": PRIVATE_STATEMENT, "agreed": True, **changes}


def add_file(name="A complete thought.mp4", content=b"isolated original file", **changes):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    before = {row["id"] for row in db.select("sources")}
    submissions.add_file(io.BytesIO(content), name, options(**changes))
    fresh = [row for row in db.select("sources") if row["id"] not in before]
    assert len(fresh) == 1
    return fresh[0]


def ready_item(data, source, *, warning=None):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    clip = make_clip(data, "A complete thought worth sharing", 90, source=source)
    project = db.get_project(clip["project_id"])
    db.update_project(project["id"], source_path=source["local_path"])
    db.update("sources", source["id"], project_id=project["id"], status="analyzed")
    submissions.bind_project(db.fetch("sources", source["id"]), db.get_project(project["id"]))
    report = passed_report(clip)
    if warning:
        db.update("quality_reports", report["id"],
                  checks=[{"name": warning, "status": "warn", "label": "Final check", "detail": "Review needed"}],
                  warnings=["Final check: Review needed"])
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    return db.select("scheduled_publications", "clip_id = ?", (clip["id"],))[0], clip


def test_source_reuse_record_leaves_saved_brain_and_source_rights_unchanged(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge, rights, submissions

    knowledge.create({"kind": "instruction", "title": "Readable captions", "content": "Use minimal captions."})
    knowledge.create({"kind": "reference", "title": "My deliberate source reference",
                      "content": "I keep my creator agreements in my own records."})
    before = {table: db.select(table) for table in BRAIN_TABLES}
    source = add_file()
    submission = submissions.for_source(source)
    assert submission and submission["source_id"] == source["id"]
    assert source["user_added"] and source["intake"]["submitted"] is True
    assert source["intake"]["submission_id"] == submission["id"]
    assert rights.evaluate(source)["status"] == rights.MANUAL
    assert not db.select("source_rights") and not db.select("publish_consents")
    item, _clip = ready_item(data, source)
    assert item["status"] == "approved" and item["approval"]["by"] == "submission"
    assert PRIVATE_STATEMENT in item["reuse_confirmation"]["basis"]
    assert {table: db.select(table) for table in BRAIN_TABLES} == before
    assert not db.select("publications")


@pytest.mark.parametrize("changed", [
    {"auto_upload": "true"}, {"auto_upload": 1}, {"agreed": "true"}, {"agreed": 1},
    {"agreed": False}, {"made_for_kids": "false"}, {"made_for_kids": 0},
    {"account_id": "another-account"}, {"audience_version": 9999},
    {"privacy": "public"}, {"reuse_basis": "invented"},
    {"reuse_basis": "legal_exception", "reuse_statement": ""},
])
def test_invalid_source_consent_creates_neither_jobs_nor_partial_inputs(data, changed):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    before = {table: db.select(table) for table in ("sources", "source_submissions", "projects", "worker_jobs")}
    with pytest.raises(ValueError):
        submissions.add_file(io.BytesIO(b"original"), "sample.mp4", options(**changed))
    assert {table: db.select(table) for table in before} == before


@pytest.mark.parametrize("status", ["discovered", "analyzed", "canceled"])
def test_repeated_link_never_attaches_automatic_permission_to_an_existing_source(data, monkeypatch, status):
    from clipfoundry import db
    from clipfoundry.autopilot import intake, submissions

    identity = {"platform": "youtube", "external_id": "audit-link-1",
                "url": "https://www.youtube.com/watch?v=audit-link-1", "title": "Existing source"}
    source = db.insert("sources", {**identity, "status": status})
    make_clip(data, "An old draft from this same video", 90, source=source)
    # URL normalization is independent of this no-retroactive-grant invariant and has its own network tests.
    monkeypatch.setattr(intake, "canonical_url", lambda _value: identity)
    before = {table: db.select(table) for table in ("sources", "source_submissions", "projects", "clips",
                                                   "scheduled_publications", "worker_jobs")}
    with pytest.raises(ValueError):
        submissions.add_link(identity["url"], options())
    assert {table: db.select(table) for table in before} == before


@pytest.mark.parametrize("change", ["account", "audience", "source_path", "source_bytes", "terms", "blocked",
                                    "canceled", "removed"])
def test_bound_source_grant_stops_on_current_source_or_destination_changes(data, change):
    from clipfoundry import db
    from clipfoundry.autopilot import rights, scheduler, submissions

    source = add_file()
    item, _clip = ready_item(data, source)
    source = db.fetch("sources", source["id"])
    assert not submissions.problem(source)
    if change == "account":
        db.save_account("youtube", tokens={"access_token": "other-token"}, account_id="UCdifferent-source-channel")
    elif change == "audience":
        db.save_settings({"audience_youtube_group_version": 2})
    elif change == "source_path":
        replacement = data / "replacement.mp4"
        replacement.write_bytes(Path(source["local_path"]).read_bytes())
        db.update("sources", source["id"], local_path=str(replacement))
    elif change == "source_bytes":
        original = Path(source["local_path"])
        original.write_bytes(b"changed original bytes")
    elif change in ("terms", "blocked"):
        rights.add_rule("source", source["id"], rights.BLOCKED if change == "blocked" else rights.OWNED,
                        "A later source decision")
    else:
        db.update("sources", source["id"], intake={**source["intake"], change: True})
    current = db.fetch("sources", source["id"])
    assert submissions.problem(current)
    assert not submissions.still_covers(item)
    assert scheduler.approval_problem(item)
    assert not submissions.auto_approve(item, db.get_settings(), time.time())
    scheduler.process_due(db.get_settings(), time.time())
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    assert not db.select("publications")


def test_approval_survives_review_default_but_never_spreads_to_another_input_or_old_backlog(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    # A legacy draft exists before the new source-specific automation decision.
    db.save_settings({"autopilot_input_mode": "discovery"})
    old_clip = make_clip(data, "An earlier completed draft still needs review", 88)
    assert scheduler.plan_new(db.get_settings(), time.time())["created"] == 1
    old = db.select("scheduled_publications", "clip_id = ?", (old_clip["id"],))[0]
    before = db.fetch("scheduled_publications", old["id"])
    db.save_settings({"autopilot_input_mode": "submitted"})
    source = add_file()
    item, _clip = ready_item(data, source)
    approved = db.fetch("scheduled_publications", item["id"])
    assert approved["status"] == "approved"
    assert approved["approval"]["by"] == "submission"
    assert approved["approval"]["submission_id"] == submissions.for_source(source)["id"]
    assert scheduler.approval_valid(approved)
    assert submissions.still_covers(approved)
    assert scheduler.hold_automatic_approvals(db.get_settings()) == 0
    assert db.fetch("scheduled_publications", old["id"]) == before
    assert not scheduler.auto_approve(before, db.get_settings(), time.time())
    another = add_file("Another input.mp4", content=b"another original", auto_upload=False, agreed=False)
    assert submissions.problem(another)
    assert db.get_settings()["autopilot_review_before_publish"] is True
    assert not db.select("publish_consents") and not db.select("publications")


def test_post_content_or_render_changes_do_not_reuse_source_approval(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    source = add_file()
    item, clip = ready_item(data, source)
    approved = db.fetch("scheduled_publications", item["id"])
    assert approved["status"] == "approved"
    assert scheduler.approval_valid(approved)
    db.update("scheduled_publications", item["id"], description=approved["description"] + " Changed manually.")
    assert scheduler.approval_problem(db.fetch("scheduled_publications", item["id"]))
    db.update("scheduled_publications", item["id"], description=approved["description"])
    Path(clip["output_path"]).write_bytes(b"different rendered file")
    assert scheduler.approval_problem(db.fetch("scheduled_publications", item["id"]))
    assert not db.select("publications")


@pytest.mark.parametrize("warning", ["content", "framing", "cuts", "captions", "silence", "black", "sound_rights"])
def test_source_request_never_overrides_a_final_check_that_requires_review(data, warning):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    source = add_file()
    item, _clip = ready_item(data, source, warning=warning)
    assert item["status"] == "awaiting_approval" and not item["approval"]
    assert not submissions.auto_approve(item, db.get_settings(), time.time())
    assert "held" in db.fetch("scheduled_publications", item["id"])["status_note"].lower()
    assert not db.select("publications")


def test_revoking_source_permission_invalidates_its_unstarted_post_only(data):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    source = add_file()
    item, _clip = ready_item(data, source)
    approved = db.fetch("scheduled_publications", item["id"])
    assert approved["status"] == "approved"
    assert submissions.still_covers(approved)
    record = submissions.for_source(source)
    db.update("source_submissions", record["id"], revoked_at=time.time())
    assert not submissions.still_covers(approved)
    assert scheduler.approval_problem(approved)
    assert not db.select("publications")


@pytest.mark.parametrize("kids", [False, True])
def test_source_grant_dispatches_exact_checked_bytes_once_with_review_default_on(env, kids):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions
    from clipfoundry.pipeline import artifact

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_input_mode": "submitted", "autopilot_review_before_publish": True,
                      "autopilot_tiktok": False})
    source = add_file(made_for_kids=kids, account_id=db.get_account("youtube")["account_id"])
    item, clip = ready_item(tmp, source)
    approved = db.fetch("scheduled_publications", item["id"])
    assert approved["status"] == "approved"
    assert approved["approval"]["by"] == "submission" and scheduler.approval_valid(approved)
    assert not db.select("publish_consents")
    before = Path(clip["output_path"]).read_bytes()
    assert approved["approval"]["video_sha256"] == artifact.sha256_file(clip["output_path"])
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published", after
    publication = db.get_publication(after["publication_id"])
    uploaded = google.videos[publication["remote_id"]]
    assert uploaded["bytes"] == before
    assert uploaded["status"]["selfDeclaredMadeForKids"] is kids
    assert uploaded["status"]["privacyStatus"] == "private"
    assert db.get_settings()["autopilot_review_before_publish"] is True
    assert submissions.still_covers(after)
    run_publish(item["id"])
    assert len(google.videos) == 1 and len(db.select("publications")) == 1


def test_source_request_survives_an_unstarted_upload_limit_without_reapproval_or_duplicate(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, quota, scheduler, submissions

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_input_mode": "submitted", "autopilot_review_before_publish": True,
                      "autopilot_tiktok": False})
    source = add_file(account_id=db.get_account("youtube")["account_id"])
    item, clip = ready_item(tmp, source)
    google.quota_exceeded = True
    with pytest.raises(queue.Wait) as waited:
        run_publish(item["id"])
    waiting = db.fetch("scheduled_publications", item["id"])
    first_publication = db.list_publications(clip["id"], "youtube")[0]
    assert waiting["status"] == "approved" and waited.value.reason == "quota"
    assert not waiting["publication_id"] and first_publication["status"] == "failed"
    assert waited.value.seconds >= quota.next_reset() - time.time() + 119
    assert quota.exhausted("uploads")
    assert not google.sessions and not google.videos
    assert submissions.still_covers(waiting) and scheduler.approval_valid(waiting)
    # Only the synthetic provider date advances; production retains YouTube's exact wait and quota history.
    next_day = quota.day_key(time.time() + 86400)
    monkeypatch.setattr(quota, "day_key", lambda _now=None: next_day)
    google.quota_exceeded = False
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published" and after["approval"] == waiting["approval"]
    assert db.get_publication(first_publication["id"]) == first_publication
    publication = db.get_publication(after["publication_id"])
    assert google.videos[publication["remote_id"]]["bytes"] == Path(clip["output_path"]).read_bytes()
    assert len(google.videos) == len(google.sessions) == 1
    assert sorted(p["status"] for p in db.list_publications(clip["id"], "youtube")) == ["done", "failed"]


def test_uncertain_source_upload_is_reconciled_even_after_future_source_permission_is_revoked(env):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_input_mode": "submitted", "autopilot_review_before_publish": True,
                      "autopilot_tiktok": False})
    source = add_file(account_id=db.get_account("youtube")["account_id"])
    item, _clip = ready_item(tmp, source)
    google.drop_final_reply = google.expire_sessions = google.hide_uploads = True
    run_publish(item["id"])
    uncertain = db.fetch("scheduled_publications", item["id"])
    assert uncertain["status"] == "reconciling" and len(google.videos) == 1
    record = submissions.for_source(source)
    db.update("source_submissions", record["id"], revoked_at=time.time())
    db.update("sources", source["id"], intake={**source["intake"], "canceled": True})
    run_publish(item["id"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "reconciling"
    assert len(google.videos) == 1
    google.hide_uploads = False
    run_publish(item["id"])
    after = db.fetch("scheduled_publications", item["id"])
    assert after["status"] == "published" and after["publication_id"] == uncertain["publication_id"]
    assert len(google.videos) == len(db.select("publications")) == 1
    assert db.fetch("source_submissions", record["id"])["revoked_at"]


@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_manual_action_during_source_approval_is_never_overwritten(data, monkeypatch, operation):
    from clipfoundry import db
    from clipfoundry.autopilot import scheduler, submissions

    source = add_file()
    # Hold only the automatic decision while constructing the pending draft; the real planner and all bindings run.
    with monkeypatch.context() as context:
        context.setattr(submissions, "auto_approve", lambda *_args: False)
        item, _clip = ready_item(data, source)
    assert item["status"] == "awaiting_approval"
    record = scheduler.approval_record
    expected = []

    def intervene(*args, **kwargs):
        approval = record(*args, **kwargs)
        # A separate owner request finishes while the automatic worker is hashing this post.
        if operation == "edit":
            scheduler.edit(item["id"], {"description": item["description"] + " My saved edit."})
        else:
            db.update("scheduled_publications", item["id"], status="canceled", status_note="Canceled by owner")
        expected.append(db.fetch("scheduled_publications", item["id"]))
        return approval

    monkeypatch.setattr(scheduler, "approval_record", intervene)
    assert not submissions.auto_approve(item, db.get_settings(), time.time())
    assert len(expected) == 1 and db.fetch("scheduled_publications", item["id"]) == expected[0]
    assert not db.select("publications")


def accepted_before_enqueue(monkeypatch):
    from clipfoundry.autopilot import submissions

    def interrupted(_source):
        raise OSError("Synthetic interruption before durable job creation")

    with monkeypatch.context() as context:
        context.setattr(submissions, "_enqueue", interrupted)
        return add_file()


def test_accepted_file_survives_enqueue_interruption_and_recovers_only_once(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import submissions

    db.save_settings({"autopilot_enabled": False})
    source = accepted_before_enqueue(monkeypatch)
    assert db.get_settings()["autopilot_enabled"] is True
    assert Path(source["local_path"]).read_bytes() == b"isolated original file"
    assert len(db.select("source_submissions")) == 1 and not db.select("worker_jobs")
    assert submissions.recover_unstarted() == 1
    jobs = db.select("worker_jobs")
    assert len(jobs) == 1 and jobs[0]["kind"] == "hunt_source"
    assert jobs[0]["payload"]["source_id"] == source["id"]
    assert submissions.recover_unstarted() == 0 and db.select("worker_jobs") == jobs


@pytest.mark.parametrize("stop", ["revoked", "canceled", "removed", "failed_source", "blocked", "failed_job",
                                  "canceled_job", "paused"])
def test_enqueue_recovery_never_revives_canceled_blocked_or_previously_attempted_work(data, monkeypatch, stop):
    from clipfoundry import db
    from clipfoundry.autopilot import queue, rights, state, submissions

    source = accepted_before_enqueue(monkeypatch)
    if stop == "revoked":
        db.update("source_submissions", submissions.for_source(source)["id"], revoked_at=time.time())
    elif stop in ("canceled", "removed"):
        db.update("sources", source["id"], intake={**source["intake"], stop: True})
    elif stop == "failed_source":
        db.update("sources", source["id"], status="failed")
    elif stop == "blocked":
        rights.add_rule("source", source["id"], rights.BLOCKED, "Owner blocked this exact source")
    elif stop.endswith("_job"):
        job = queue.enqueue("hunt_source", {"source_id": source["id"]}, ref=("source", source["id"]))
        db.update("worker_jobs", job["id"], status="failed" if stop == "failed_job" else "canceled", attempts=1)
    else:
        state.put("emergency_stop", True)
    before = {table: db.select(table) for table in ("sources", "source_submissions", "worker_jobs")}
    assert submissions.recover_unstarted() == 0
    assert {table: db.select(table) for table in before} == before
    assert Path(source["local_path"]).is_file()
