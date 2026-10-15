"""Saved source-topic guidance reaches real captioned files and respects explicit edits."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from synthetic_media import make_video, needs_ffmpeg, words_from


@pytest.mark.slow
@needs_ffmpeg
def test_source_tagged_note_and_example_reach_real_render_without_claiming_overridden_style(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    from clipfoundry import config, db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import artifact, blueprint, render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe

    db.init()
    db.save_settings({"encoder": "x264", "x264_preset": "ultrafast", "caption_style": "minimal",
                      "caption_position": "bottom", "tracking": "center", "auto_zoom": False,
                      "hook_overlay": False, "silence": "off"})
    note = knowledge.create({"kind": "reference", "title": "Readable topic captions", "tags": ["science"],
                             "content": "Captions should be in the middle."})
    example = knowledge.create({"kind": "example", "title": "Preferred topic example", "tags": ["science"],
                                "example_label": "good", "features": {"captions": "bold"}})
    assert note["state"] == example["state"] == "active"
    # Only the original video's title matches the lessons; the chosen moment has its own short title/words.
    source = make_video(tmp_path / "science-original.mp4", seconds=3.8, fps=12)
    project = db.create_project("Science explained", origin="autopilot", status="ready",
                                source_path=str(source), info=probe(source))
    project.update(project["info"])
    project["dir"] = str(config.projects_dir() / project["id"])
    text = "Practice helps us remember. Take a short break."
    clip = db.create_clip(project["id"], start=0, end=3.6, title="Take a short break", caption_text=text)
    words = words_from(text, step=.36, length=.28)
    settings = db.get_settings()
    plan = blueprint.build(clip, project, words, settings)
    assert plan.captions.style == "bold" and plan.captions.position == "middle"
    saved = blueprint.save(plan, blueprint.validate(plan, project["duration"], words))
    expected = {
        note["id"]: {"caption_position": {"before": "bottom", "after": "middle"}},
        example["id"]: {"caption_style": {"before": "minimal", "after": "bold"}},
    }
    influences = knowledge.influences(clip["id"])
    assert {row["knowledge_id"]: row["decisions"] for row in influences} == expected
    assert all(row["revision"] == 1 and row["blueprint_id"] == saved["id"] for row in influences)

    def checked_render(current_clip, current_plan, directory):
        result = render.render_clip(project, current_clip, words, settings, JobContext(), out_dir=directory,
                                    blueprint=current_plan)
        record = result["render_info"]["artifact"]
        path = Path(result["output_path"])
        assert record["sha256"] == artifact.sha256_file(path)
        assert record["probe"]["width"] == 1080 and record["probe"]["height"] == 1920
        assert record["probe"]["has_audio"]
        # Decode every actual output frame, rather than trusting the renderer's own metadata.
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-i", str(path),
                        "-f", "null", "-"], check=True, capture_output=True, timeout=30)
        assert json.loads(Path(record["transcript"]).read_text())["text"] == text
        return result, Path(record["captions"]["ass"]).read_text(encoding="utf-8")

    result, ass = checked_render(clip, plan, tmp_path / "brain-render")
    assert result["render_info"]["brain_knowledge"] == plan.knowledge
    assert {row["knowledge_id"]: row["decisions"] for row in result["render_info"]["brain_knowledge"]} == expected
    assert result["render_info"]["artifact"]["settings"]["caption_style"] == "bold"
    assert "Style: Caption,Poppins ExtraBold,92," in ass
    assert ",7,3,5,90,90,0,1" in ass  # Bold preset outline/shadow; actual middle alignment/margin.
    assert "PRACTICE" in ass and "Practice" not in ass
    db.update_clip(clip["id"], **result, status="ready")
    db.init()  # A process/database reopen retains actual render provenance and the originally saved plan.
    assert db.get_clip(clip["id"])["render_info"] == result["render_info"]
    assert blueprint.plan_of(clip["id"]).knowledge == plan.knowledge

    edited_clip = {**clip, "edit": {"caption_style": "minimal"}}
    edited_plan = blueprint.with_edit(plan, edited_clip["edit"])
    edited, edited_ass = checked_render(edited_clip, edited_plan, tmp_path / "owner-edit-render")
    remaining = edited["render_info"]["brain_knowledge"]
    assert {row["knowledge_id"]: row["decisions"] for row in remaining} == {note["id"]: expected[note["id"]]}
    assert edited["render_info"]["artifact"]["settings"]["caption_style"] == "minimal"
    assert "Style: Caption,Poppins Medium,62," in edited_ass and "Practice" in edited_ass
    assert edited["render_info"]["artifact"]["sha256"] != result["render_info"]["artifact"]["sha256"]
    assert plan.captions.style == "bold" and len(plan.knowledge) == 2  # The base plan was not rewritten.
    assert not db.select("publications") and not db.select("scheduled_publications")
    assert not db.select("source_rights") and not db.select("publish_consents")
