"""Review scheduling and exact owner publication with real FFmpeg media and isolated official-API stand-ins."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from synthetic_media import make_video, needs_ffmpeg, words_from
from test_autopilot_publish import connect, env  # noqa: F401


@pytest.mark.slow
@needs_ffmpeg
def test_real_checked_clip_waits_for_owner_reuse_review_and_survives_restart(env):
    from clipfoundry import config, db
    from clipfoundry.autopilot import autopublish, gate, host, packaging, queue, rights, scheduler
    from clipfoundry.pipeline import artifact, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    google, tt, tmp = env
    connect(google, tt)
    db.save_settings({"autopilot_review_before_publish": False, "autopilot_tiktok": False,
                      "encoder": "x264", "x264_preset": "ultrafast"})
    # A previous standing consent cannot turn this newly requested local-review mode into an upload grant.
    autopublish.enable("youtube", "private", False, 0, 0, 24, True)
    db.save_settings({"autopilot_review_before_publish": True})
    source_path = make_video(tmp / "review-original.mp4", seconds=9.0)
    source = db.insert("sources", {"platform": "youtube", "external_id": "review12345", "status": "analyzed",
                                   "url": "https://www.youtube.com/watch?v=review12345", "license": "youtube",
                                   "title": "Talk to customers first", "rights_status": rights.MANUAL})
    project = db.create_project("Synthetic original", origin="autopilot", source_id=source["id"], status="ready",
                                source_path=str(source_path), info=probe(source_path))
    project.update(project["info"])
    project["dir"] = str(config.projects_dir() / project["id"])
    text = ("Talk to customers before you build anything. Most founders skip this step and regret it later. "
            "Ask them which problem costs them real money every week.")
    clip = db.create_clip(project["id"], start=0.1, end=8.4, title="Talk to customers first", score=90,
                          caption_text=text, edit={"tracking": "center"})
    result = render.render_clip(project, clip, words_from(text), db.get_settings(), JobContext())
    db.update_clip(clip["id"], **result, status="ready")
    clip = db.get_clip(clip["id"])
    packaging.package(clip, source, "youtube", db.get_settings())
    report = gate.run(clip, db.get_settings())
    assert report["status"] == "passed", report["blockers"]
    assert report["metadata"]["youtube"]["status"] == "passed", report["metadata"]
    assert report["coverage"]["needs_reuse_review"]
    assert {"hash", "dimensions", "decode", "captions"} <= {c["name"] for c in report["checks"]}

    now = time.time()
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 1
    item = db.select("scheduled_publications")[0]
    assert item["status"] == "awaiting_approval" and not item["approval"]
    for advance in (0, 3600, 86400):
        scheduler.process_due(db.get_settings(), now + advance)
    assert not google.videos and not google.sessions
    assert not db.select("worker_jobs", "kind = 'publish'")

    # Closing/reopening the database preserves local review, without granting reuse or running a new upload.
    db.init()
    scheduler.process_due(db.get_settings(), now + 86400)
    assert not google.videos and db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    item = scheduler.approve(item["id"], {"options": {"made_for_kids": False}}, reuse_confirmed=True,
                             reuse_basis="I inspected this exact clip and have the creator's written reuse permission.")
    scheduler.process_due(db.get_settings(), now + 86400)
    host.WorkerHost(periodic=False)
    job = queue.claim("publisher", "review-media")
    assert job and job["kind"] == "publish"
    outcome = host.HANDLERS["publish"](host.Job(job, "review-media"))
    queue.complete(job, "review-media", outcome)
    final = db.fetch("scheduled_publications", item["id"])
    publication = db.get_publication(final["publication_id"])
    assert final["status"] == "published" and len(google.videos) == len(google.sessions) == 1
    uploaded = google.videos[publication["remote_id"]]
    assert hashlib.sha256(uploaded["bytes"]).hexdigest() == report["artifact_sha256"] == artifact.sha256_file(
        clip["output_path"])
    assert len(uploaded["bytes"]) == Path(clip["output_path"]).stat().st_size
    assert uploaded["status"]["privacyStatus"] == "private" and "publishAt" not in uploaded["status"]
    assert db.fetch("sources", source["id"])["rights_status"] == rights.MANUAL
    db.init()
    scheduler.process_due(db.get_settings(), now + 2 * 86400)
    queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}")
    assert queue.claim("publisher", "review-media-restart") is None
    assert len(google.videos) == len(google.sessions) == 1
