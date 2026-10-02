"""Automatic recovery keeps useful work moving; explicit cancellation remains final."""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    from clipfoundry import db

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    db.init()
    db.save_settings({"autopilot_enabled": True, "autopilot_sources_per_day": 1, "library_discovery": False})
    return tmp_path


def test_app_shutdown_preserves_unfinished_work_but_explicit_cancel_does_not(data, monkeypatch):
    from clipfoundry.autopilot import host, queue

    reached = threading.Event()

    def safe_step(job):
        reached.set()
        job.cancel_event.wait(5)
        job.check()

    h = host.WorkerHost(workers=["maintenance"], periodic=False, poll=0.02)
    monkeypatch.setitem(host.HANDLERS, "selftest", safe_step)
    item = queue.enqueue("selftest", max_attempts=1)
    row = queue.claim("maintenance", "claim")
    thread = threading.Thread(target=h._run, args=("maintenance", row))
    thread.start()
    assert reached.wait(3)
    h._stop.set()
    h.running()[item["id"]].cancel_event.set()
    thread.join(3)
    saved = queue.get(item["id"])
    assert saved["status"] == "waiting" and saved["wait_reason"] == "restart"
    resumed = queue.claim("maintenance", "new-host", now=saved["run_after"] + 1)
    assert resumed["attempts"] == 1 and resumed["id"] == item["id"]
    queue.complete(resumed, "new-host")

    canceled = queue.enqueue("selftest", idem_key="cancel-me")
    queue.cancel(canceled["id"])
    queue.enqueue("selftest", idem_key="cancel-me")
    assert queue.get(canceled["id"])["status"] == "canceled"
    assert queue.claim("maintenance", "restart") is None


def test_failed_source_releases_its_slot_and_selects_another_immediately(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, rights, scout

    h = host.WorkerHost(periodic=False)
    rights.add_rule("folder", str(data), rights.OWNED, "My recordings")
    video = data / "working.mp4"
    video.write_bytes(b"test media; access only")
    bad = db.insert("sources", {"platform": "local", "external_id": "bad", "title": "Bad video",
                                "status": "ingesting", "selected_day": scout.local_day(db.get_settings())})
    good = db.insert("sources", {"platform": "local", "external_id": "good", "title": "Good video",
                                 "status": "eligible", "local_path": str(video), "expected_clips": 2,
                                 "source_score": 80})

    def fail(job):
        raise queue.Fail("File cannot be decoded")

    monkeypatch.setitem(host.HANDLERS, "hunt_source", fail)
    queue.enqueue("hunt_source", {"source_id": bad["id"]}, ref=("source", bad["id"]))
    h._run("clip_hunter", queue.claim("clip_hunter", "bad-claim"))
    assert db.fetch("sources", bad["id"])["status"] == "failed"
    replacement = queue.claim("source_scout", "replacement")
    assert replacement and replacement["kind"] == "source_scout"
    h._run("source_scout", replacement)
    assert db.fetch("sources", good["id"])["status"] == "queued"
    assert queue.claim("clip_hunter", "good-claim")["payload"]["source_id"] == good["id"]


def test_one_broken_access_check_does_not_prevent_the_next_video(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import access, rights, scout

    rights.add_rule("folder", str(data), rights.OWNED, "My recordings")
    sources = []
    for key, score in (("broken", 90), ("good", 80)):
        video = data / f"{key}.mp4"
        video.write_bytes(b"access test")
        sources.append(db.insert("sources", {"platform": "local", "external_id": key, "title": key,
                                              "local_path": str(video), "status": "eligible",
                                              "expected_clips": 2, "source_score": score}))
    resolve = access.resolve

    def inspect(src, settings):
        if src["external_id"] == "broken":
            raise OSError("temporarily unavailable mount")
        return resolve(src, settings)

    monkeypatch.setattr(access, "resolve", inspect)
    assert [s["id"] for s in scout.select_for_today(db.get_settings())] == [sources[1]["id"]]
    assert db.fetch("sources", sources[0]["id"])["status"] == "failed"


def test_periodic_discovery_cannot_bypass_an_existing_retry_after_wait(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue, state

    host.WorkerHost(periodic=False)
    queue.enqueue("trend_scan", max_attempts=1)
    row = queue.claim("trend_scout", "search")
    queue.wait(row, "search", "rate_limit", 6 * 3600)
    state.put("next:trend_scan", 0)
    later = time.time() + 4 * 3600
    assert "trend_scan" not in host.run_periodic(db.get_settings(), later)
    assert len(queue.jobs(worker="trend_scout")) == 1
    resumed = queue.claim("trend_scout", "search-again", now=time.time() + 7 * 3600)
    assert resumed["attempts"] == 1
    queue.complete(resumed, "search-again")
    assert "trend_scan" in host.run_periodic(db.get_settings(), time.time() + 8 * 3600)


def test_unexpected_search_failure_preserves_the_other_search_results(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import host, providers, queue, scout, state

    host.WorkerHost(periodic=False)

    def unavailable(settings):
        raise RuntimeError("unexpected temporary response")

    monkeypatch.setattr(providers, "YouTubeDiscovery", unavailable)
    monkeypatch.setattr(scout, "library_search", lambda *args: [{"provider": "library", "platform": "commons",
                                                              "external_id": "good", "title": "Good result"}])
    queue.enqueue("trend_scan")
    row = queue.claim("trend_scout", "scan")
    result = scout.trend_scan(host.Job(row, "scan"))
    assert result["signals"] == 1 and db.select("trend_signals", "external_id = 'good'")
    assert state.get("providers")["youtube"]["status"] == "error"
    assert queue.jobs(("queued",), worker="source_scout")
    assert not state.open_actions()


def _automatic_clip(data):
    from clipfoundry import db

    video = data / "original.mp4"
    video.write_bytes(b"original media")
    src = db.insert("sources", {"platform": "local", "external_id": f"original-{time.time_ns()}", "status": "analyzed"})
    project = db.create_project("Video", source_path=str(video), origin="autopilot", source_id=src["id"])
    output = data / "clip.mp4"
    output.write_bytes(b"damaged output")
    return db.create_clip(project["id"], status="ready", start=0, end=30, output_path=str(output))


def test_quality_regeneration_is_bounded_and_preserves_cancel_and_unsafe_failures(data):
    from clipfoundry.autopilot import gate, host, queue

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    structural = {"checks": [{"name": "decode", "status": "fail"}]}
    first = gate.repair_media(clip, structural, priority=80)
    assert first["priority"] == 80
    assert gate.repair_media(clip, structural)["id"] == first["id"]
    row = queue.claim("analyzer", "first")
    queue.complete(row, "first")
    second = gate.repair_media(clip, structural)
    row = queue.claim("analyzer", "second")
    queue.complete(row, "second")
    assert second["id"] != first["id"] and gate.repair_media(clip, structural) is None

    canceled_clip = _automatic_clip(data)
    item = gate.repair_media(canceled_clip, structural)
    queue.cancel(item["id"])
    assert gate.repair_media(canceled_clip, structural) is None
    unsafe_clip = _automatic_clip(data)
    assert gate.repair_media(unsafe_clip, {"checks": [{"name": "sound_rights", "status": "fail"}]}) is None


def test_normal_recovered_errors_and_a_lack_of_videos_never_need_the_user(data):
    from clipfoundry import db
    from clipfoundry.autopilot import home, state

    state.put("trend:last_scan", {"at": time.time(), "signals": 0})
    state.action("workers:spawn", "workers", "Background process stopped")
    state.action("job:ordinary", "job", "A video failed")
    assert home.needs_you(db.get_settings(), {}, workers_alive=True) == []
    state.action("disk:space", "disk", "Disk critically low", "No safe cleanup remains")
    assert [i["title"] for i in home.needs_you(db.get_settings(), {}, True)] == ["Disk critically low"]


def test_failed_regeneration_keeps_the_completed_local_file_available(data, monkeypatch):
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue, rights

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    source = gate._source(clip)
    rights.add_rule("source", source["id"], rights.OWNED, "My original recording")
    output = Path(clip["output_path"])
    original_bytes = output.read_bytes()
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    claimed = queue.claim("analyzer", "repair")

    def broken_render(clip_id, ctx):
        output.write_bytes(b"partial failed render")
        db.update_clip(clip_id, status="error", error="encoder interrupted")

    monkeypatch.setattr(gate.process, "render_single", broken_render)
    with pytest.raises(queue.Fail, match="encoder interrupted"):
        gate.regenerate_clip(host.Job(claimed, "repair"))
    saved = db.get_clip(clip["id"])
    assert saved["status"] == "ready" and saved["output_path"] == clip["output_path"]
    assert output.read_bytes() == original_bytes and not list(output.parent.glob("*.bak"))
    assert repair["id"] == claimed["id"]


def test_crash_inside_regeneration_restores_local_output_before_a_bounded_retry(data):
    import shutil
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    original = Path(clip["output_path"])
    saved_bytes = original.read_bytes()
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    queue.claim("analyzer", "dead-host")
    backup = original.with_name(f"{original.name}.regeneration-{repair['id']}.bak")
    shutil.copy2(original, backup)
    original.write_bytes(b"unfinished bytes from crashed renderer")
    db.update_clip(clip["id"], status="rendering")
    db.update("worker_jobs", repair["id"], lease_until=time.time() - 1)
    assert queue.recover()["failed"] == 1
    assert gate.recover_regenerations() == 1
    assert original.read_bytes() == saved_bytes and db.get_clip(clip["id"])["status"] == "ready"
    jobs = [j for j in queue.jobs(ref=("clip", clip["id"])) if j["kind"] == "regenerate_clip"]
    assert len(jobs) == 2 and sum(j["status"] == "queued" for j in jobs) == 1
    assert gate.recover_regenerations() == 0


def test_discovered_batch_yields_after_a_finished_clip_and_resumes_only_the_remainder(data, monkeypatch):
    from types import SimpleNamespace

    from clipfoundry import db
    from clipfoundry.autopilot import host, hunter, queue

    host.WorkerHost(periodic=False)
    source = db.insert("sources", {"platform": "local", "external_id": "discovered", "status": "analyzing"})
    project = db.create_project("Discovered video", origin="autopilot", source_id=source["id"])
    clips = [db.create_clip(project["id"], start=i * 30, end=(i + 1) * 30, status="queued") for i in range(2)]
    queue.enqueue("analyze_source", {"source_id": source["id"], "project_id": project["id"]}, priority=10)
    row = queue.claim("analyzer", "discovered")
    job = host.Job(row, "discovered")
    p = SimpleNamespace(id=project["id"])
    rendered = []
    higher = []

    def finish_one(prepared, rows, ctx, **kwargs):
        clip = rows[0]
        rendered.append(clip["id"])
        output = data / f"{clip['id']}.mp4"
        output.write_bytes(f"completed {clip['id']}".encode())
        db.update_clip(clip["id"], status="ready", output_path=str(output))
        if len(rendered) == 1:
            submitted = db.insert("sources", {"platform": "local", "external_id": "submitted", "user_added": 1})
            higher.append(queue.enqueue("hunt_source", {"source_id": submitted["id"]}, priority=80,
                                        ref=("source", submitted["id"])))

    monkeypatch.setattr(hunter.process, "render_clips", finish_one)
    with pytest.raises(queue.Wait) as wait:
        hunter.render_in_priority_order(p, clips, job.pipeline_ctx(), job, source)
    assert wait.value.reason == "priority" and rendered == [clips[0]["id"]]
    completed = db.get_clip(clips[0]["id"])
    assert completed["status"] == "ready" and db.get_clip(clips[1]["id"])["status"] == "queued"
    from clipfoundry.pipeline.artifact import sha256_file

    saved_hash = sha256_file(completed["output_path"])
    queue.wait(row, "discovered", "priority", 2)
    high = queue.claim("clip_hunter", "submitted")
    assert high["id"] == higher[0]["id"]
    queue.complete(high, "submitted")
    resumed = queue.claim("analyzer", "discovered-again", now=time.time() + 3)
    again = host.Job(resumed, "discovered-again")
    hunter.render_in_priority_order(p, clips, again.pipeline_ctx(), again, source)
    assert rendered == [c["id"] for c in clips] and resumed["attempts"] == 1
    assert sha256_file(completed["output_path"]) == saved_hash


def test_future_streams_auth_waits_and_listening_recorders_do_not_hold_rendering(data):
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    current = queue.enqueue("analyze_source", priority=10)
    queue.enqueue("hunt_source", priority=80, delay=3600)
    queue.enqueue("post_live", priority=90, delay=3600)
    queue.enqueue("live_capture", priority=95)
    waiting = queue.enqueue("regenerate_clip", priority=90)
    claimed = queue.claim("analyzer", "auth")
    assert claimed["id"] == waiting["id"]
    queue.wait(claimed, "auth", "not_connected", 1)
    assert not queue.has_higher_priority_work(current, 10, now=time.time() + 2)
    due = queue.enqueue("hunt_source", priority=80)
    assert queue.has_higher_priority_work(current, 10)
    queue.cancel(due["id"])
    assert not queue.has_higher_priority_work(current, 10)


def test_manual_alternative_version_of_an_automatic_clip_gets_a_safe_turn(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    project = db.create_project("Automatic video", origin="autopilot")
    clip = db.create_clip(project["id"], start=0, end=30, status="ready")
    current = queue.enqueue("analyze_source", {"project_id": project["id"]}, priority=10)
    assert not queue.has_higher_priority_work(current, 10)
    version = db.create_version(clip["id"], "alt_hook", status="queued")
    assert queue.has_higher_priority_work(current, 10)
    assert not queue.has_higher_priority_work(current, 100)
    db.update_version(version["id"], status="ready")
    assert not queue.has_higher_priority_work(current, 10)


def test_restart_separates_live_durable_work_from_explicit_manual_render_requests(data, monkeypatch):
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    source = db.insert("sources", {"platform": "stream", "external_id": "live", "status": "canceled",
                                   "intake": {"canceled": True}})
    live = db.create_project("Live", origin="live", source_id=source["id"], status="processing")
    automatic = db.create_project("Automatic", origin="autopilot", source_id=source["id"], status="ready")
    abandoned = db.create_clip(automatic["id"], start=0, end=30, status="queued")
    owned = db.create_clip(automatic["id"], start=30, end=60, status="queued")
    queue.enqueue("post_live", {"source_id": source["id"], "project_id": automatic["id"]},
                  ref=("source", source["id"]))
    explicit = db.create_clip(automatic["id"], start=60, end=90, status="ready",
                              render_info={"artifact": {"sha256": "previous-file"}})
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_render(explicit["id"])
    version = db.create_version(explicit["id"], "alt_hook", status="queued")
    interrupted = db.interrupted_work()
    assert live["id"] not in [p["id"] for p in interrupted["projects"]]
    assert interrupted["clips"] == [explicit["id"]]
    assert abandoned["id"] not in interrupted["clips"] and owned["id"] not in interrupted["clips"]
    assert interrupted["versions"] == [version["id"]]
    assert db.get_clip(explicit["id"])["render_info"]["artifact"]["sha256"] == "previous-file"


@pytest.mark.parametrize("outcome", ["ready", "failed", "canceled"])
def test_manual_render_provenance_clears_when_the_request_finishes(data, monkeypatch, outcome):
    from clipfoundry import db, jobs
    from clipfoundry.autopilot import host, queue

    host.WorkerHost(periodic=False)
    automatic = db.create_project("Automatic", origin="autopilot", status="ready")
    clip = db.create_clip(automatic["id"], start=0, end=30, status="ready",
                          render_info={"artifact": {"sha256": "previous-file"}})
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_render(clip["id"])
    current = queue.enqueue("analyze_source", {"project_id": automatic["id"]}, priority=10)
    assert queue.has_higher_priority_work(current, 10)

    def render(clip_id, ctx):
        if outcome == "ready":
            db.update_clip(clip_id, status="ready", render_info={"artifact": {"sha256": "new-file"}})
        else:
            db.update_clip(clip_id, status="error", error=outcome)
            if outcome == "canceled":
                raise queue.Canceled()

    monkeypatch.setattr(jobs.process, "render_single", render)
    worker._run_render(clip["id"])
    saved = db.get_clip(clip["id"])
    assert not saved["render_info"].get("manual_render_pending")
    assert saved["render_info"]["artifact"]["sha256"] == ("new-file" if outcome == "ready" else "previous-file")
    assert not queue.has_higher_priority_work(current, 10)
    assert clip["id"] not in db.interrupted_work()["clips"]


def test_failed_restore_retains_the_last_saved_file_until_recovery_can_copy_it(data, monkeypatch):
    import errno
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue, rights

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    source = gate._source(clip)
    rights.add_rule("source", source["id"], rights.OWNED, "My original recording")
    output = Path(clip["output_path"])
    original_bytes = output.read_bytes()
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    claimed = queue.claim("analyzer", "repair")
    backup = output.with_name(f"{output.name}.regeneration-{repair['id']}.bak")
    copy = gate.shutil.copy2

    def fail_restore(src, dst, *args, **kwargs):
        if str(src).endswith(".bak"):
            raise OSError(errno.ENOSPC, "No space to restore")
        return copy(src, dst, *args, **kwargs)

    def broken_render(clip_id, ctx):
        output.unlink()
        db.update_clip(clip_id, status="error", error="render output failed")

    monkeypatch.setattr(gate.shutil, "copy2", fail_restore)
    monkeypatch.setattr(gate.process, "render_single", broken_render)
    with pytest.raises(OSError, match="No space to restore"):
        gate.regenerate_clip(host.Job(claimed, "repair"))
    assert backup.read_bytes() == original_bytes and not output.exists()
    queue.fail(claimed, "repair", "No space to restore")
    assert gate.recover_regenerations() == 0 and backup.exists()
    monkeypatch.setattr(gate.shutil, "copy2", copy)
    assert gate.recover_regenerations() == 1
    assert output.read_bytes() == original_bytes and db.get_clip(clip["id"])["status"] == "ready"


@pytest.mark.parametrize("new_path", [False, True])
def test_later_completed_regeneration_is_never_replaced_by_an_older_recovery_backup(data, new_path):
    import shutil
    from pathlib import Path

    from clipfoundry import db
    from clipfoundry.autopilot import gate, host, queue

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    output = Path(clip["output_path"])
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    claimed = queue.claim("analyzer", "old-attempt")
    backup = output.with_name(f"{output.name}.regeneration-{repair['id']}.bak")
    shutil.copy2(output, backup)
    queue.fail(claimed, "old-attempt", "Restore was interrupted")
    current = data / "new-location.mp4" if new_path else output
    if new_path:
        output.unlink()
    current.write_bytes(b"new completed file")
    db.update_clip(clip["id"], status="ready", output_path=str(current),
                   render_info={"artifact": {"sha256": "new-file"}})
    assert gate.recover_regenerations() == 0
    assert current.read_bytes() == b"new completed file" and not backup.exists()
    assert db.get_clip(clip["id"])["output_path"] == str(current)
    assert queue.jobs(("queued",), worker="packager")


@pytest.mark.parametrize("status", ["queued", "rendering"])
def test_backup_recovery_leaves_an_explicit_manual_render_of_the_same_edit_alone(data, monkeypatch, status):
    import shutil
    from pathlib import Path

    from clipfoundry import db, jobs
    from clipfoundry.autopilot import gate, host, queue

    host.WorkerHost(periodic=False)
    clip = _automatic_clip(data)
    output = Path(clip["output_path"])
    saved_bytes = output.read_bytes()
    repair = gate.repair_media(clip, {"checks": [{"name": "decode", "status": "fail"}]})
    claimed = queue.claim("analyzer", "old-attempt")
    backup = output.with_name(f"{output.name}.regeneration-{repair['id']}.bak")
    shutil.copy2(output, backup)
    queue.fail(claimed, "old-attempt", "Restore was interrupted")
    worker = jobs.Worker()
    monkeypatch.setattr(worker, "start", lambda: None)
    worker.submit_render(clip["id"])
    db.update_clip(clip["id"], status=status)
    output.write_bytes(b"the manual renderer owns these bytes")
    assert gate.recover_regenerations() == 0
    assert backup.read_bytes() == saved_bytes
    assert output.read_bytes() == b"the manual renderer owns these bytes"
    current = db.get_clip(clip["id"])
    assert current["status"] == status and current["render_info"]["manual_render_pending"]
