"""Selected owner approvals publish exact real renders, without approving later work."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from synthetic_media import make_video, needs_ffmpeg, words_from
from test_autopilot_publish import connect, env, make_item  # noqa: F401


@pytest.mark.slow
@needs_ffmpeg
def test_bulk_review_uploads_only_selected_real_files_and_restart_never_duplicates(env):
    from clipfoundry import config, db
    from clipfoundry.autopilot import bulk_review, gate, host, packaging, queue, rights, scheduler
    from clipfoundry.pipeline import artifact, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    google, tiktok, tmp = env
    connect(google, tiktok)
    db.save_settings({"autopilot_tiktok": False, "encoder": "x264", "x264_preset": "ultrafast"})
    source_path = make_video(tmp / "bulk-review-original.mp4", seconds=9.0)
    entries = (
        ("Talk to customers first", "Talk to customers before you build anything. Most founders skip this step "
         "and regret it later. Ask them which problem costs them real money every week."),
        ("Protect a quiet morning", "Protect a quiet morning for focused work. Put your phone in another room "
         "and finish the difficult task first. Take a short walk when you need a break."),
    )
    reports = {}
    sources = []
    for index, (title, text) in enumerate(entries):
        source = db.insert("sources", {"platform": "youtube", "external_id": f"bulkreview{index}",
                                       "status": "analyzed", "license": "youtube", "title": title,
                                       "rights_status": rights.MANUAL})
        sources.append(source)
        project = db.create_project(title, origin="autopilot", source_id=source["id"], status="ready",
                                    source_path=str(source_path), info=probe(source_path))
        project.update(project["info"])
        project["dir"] = str(config.projects_dir() / project["id"])
        clip = db.create_clip(project["id"], start=0.1, end=8.4, title=title, score=90,
                              caption_text=text, edit={"tracking": "center"})
        rendered = render.render_clip(project, clip, words_from(text), db.get_settings(), JobContext())
        db.update_clip(clip["id"], **rendered, status="ready")
        clip = db.get_clip(clip["id"])
        packaging.package(clip, source, "youtube", db.get_settings())
        report = gate.run(clip, db.get_settings())
        assert report["status"] == "passed", report["blockers"]
        assert report["metadata"]["youtube"]["status"] == "passed", report["metadata"]
        assert report["coverage"]["needs_reuse_review"]
        assert {"hash", "dimensions", "decode", "captions"} <= {c["name"] for c in report["checks"]}
        reports[clip["id"]] = report

    now = time.time()
    assert scheduler.plan_new(db.get_settings(), now)["created"] == 2
    drafts = db.select("scheduled_publications", "platform = 'youtube'")
    assert len(drafts) == 2 and all(item["status"] == "awaiting_approval" for item in drafts)
    preview = bulk_review.preview([item["id"] for item in drafts])
    assert set(preview["eligible_ids"]) == {item["id"] for item in drafts}
    assert not google.sessions and not google.videos
    approved = bulk_review.approve(
        preview["token"], confirm=True, reuse_confirmed=True, reuse_kind="custom",
        reuse_basis="I hold written permission for every selected clip, including its audio.", made_for_kids=False,
    )
    assert approved["approved"] == 2 and approved["skipped"] == 0, approved
    for item in drafts:
        current = db.fetch("scheduled_publications", item["id"])
        assert current["approval"]["by"] == "you" and scheduler.approval_valid(current)
        assert not rights.confirmation_problem(current)

    # Neither the selection nor its one-time consent becomes a grant for work made afterwards.
    later = make_item(tmp, planned_in=-30, text="A later clip still needs the owner's individual review.")
    later_source = db.insert("sources", {"platform": "local", "external_id": "later-review",
                                         "status": "analyzed", "rights_status": rights.MANUAL})
    db.update_project(db.get_clip(later["clip_id"])["project_id"], source_id=later_source["id"])
    db.init()
    scheduler.process_due(db.get_settings(), time.time() + 1)
    host.WorkerHost(periodic=False)
    for index in range(2):
        job = queue.claim("publisher", f"bulk-media-{index}")
        assert job and job["kind"] == "publish"
        outcome = host.HANDLERS["publish"](host.Job(job, f"bulk-media-{index}"))
        queue.complete(job, f"bulk-media-{index}", outcome)
    assert queue.claim("publisher", "bulk-media-unselected") is None
    assert len(google.videos) == len(google.sessions) == 2
    for item in drafts:
        current = db.fetch("scheduled_publications", item["id"])
        publication = db.get_publication(current["publication_id"])
        assert current["status"] == "published"
        uploaded = google.videos[publication["remote_id"]]
        clip = db.get_clip(item["clip_id"])
        assert hashlib.sha256(uploaded["bytes"]).hexdigest() == reports[clip["id"]]["artifact_sha256"] == (
            artifact.sha256_file(clip["output_path"]))
        assert len(uploaded["bytes"]) == Path(clip["output_path"]).stat().st_size
        assert uploaded["status"]["privacyStatus"] == "private" and "publishAt" not in uploaded["status"]
    assert db.fetch("scheduled_publications", later["id"])["status"] == "awaiting_approval"
    assert not db.fetch("scheduled_publications", later["id"])["approval"]
    assert not db.select("source_rights") and not db.select("publish_consents")
    assert all(db.fetch("sources", source["id"])["rights_status"] == rights.MANUAL for source in sources)

    db.init()
    scheduler.process_due(db.get_settings(), now + 86400)
    for item in drafts:
        queue.enqueue("publish", {"scheduled_id": item["id"]}, idem_key=f"publish:{item['id']}")
    assert queue.claim("publisher", "bulk-media-restart") is None
    assert len(google.videos) == len(google.sessions) == 2
    assert db.fetch("scheduled_publications", later["id"])["status"] == "awaiting_approval"
