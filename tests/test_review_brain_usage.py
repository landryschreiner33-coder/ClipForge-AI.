"""Enabled guidance survives source-to-clip context changes and records only supported effects."""
from __future__ import annotations

import pytest


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    from clipfoundry import db

    db.init()
    return tmp_path


def lesson(**fields):
    from clipfoundry.autopilot import knowledge

    return knowledge.create({"kind": "reference", "title": "Editing guide", "tags": ["science"],
                             "content": "Captions should be minimal. Keep the story continuous.", **fields})


def test_source_topic_survives_ranked_clip_title_and_persists_actual_plan(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import blueprint

    row = lesson()
    project = db.create_project("Science explained", origin="autopilot", duration=6)
    text = "Practice helps us remember."
    clip = db.create_clip(project["id"], start=0, end=5, duration=5, title="Practice helps", caption_text=text)
    words = [{"w": word, "start": n, "end": n + .8} for n, word in enumerate(text.split())]
    plan = blueprint.build(clip, project, words, db.get_settings())
    assert plan.captions.style == "minimal"
    saved = blueprint.save(plan, [])
    influence = knowledge.influences(clip["id"])[0]
    assert influence["knowledge_id"] == row["id"] and influence["revision"] == 1
    assert influence["blueprint_id"] == saved["id"]
    assert influence["decisions"]["caption_style"] == {"before": "bold", "after": "minimal"}
    assert not db.select("scheduled_publications") and not db.select("publications")
    # Changing guidance never silently rewrites a previously saved clip plan.
    knowledge.edit(row["id"], {"preferences": {"caption_style": "clean"}})
    assert blueprint.plan_of(clip["id"]).captions.style == "minimal"


def test_manual_render_consults_source_context_without_claiming_unused_pacing(data):
    from clipfoundry import db
    from clipfoundry.autopilot import brain
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext

    lesson()
    project = {"id": "p1", "name": "Science explained", "width": 1080, "height": 1920,
               "source_path": "unused.mp4", "duration": 1}
    clip = {"id": "c1", "start": 0, "end": .2, "title": "Practice helps", "edit": {}}
    # The real boundary rejects a too-short manual clip after resolving its real guidance controls.
    with pytest.raises(ValueError, match="shorter than one second"):
        render.render_clip(project, clip, [], db.get_settings(), JobContext())
    activity = brain.summary()["activity"]["last"]
    assert activity["consulted"] == 1 and activity["applied"] == 1  # Captions; no manual pacing trim.
    clip["edit"] = {"caption_style": "bold"}
    with pytest.raises(ValueError, match="shorter than one second"):
        render.render_clip(project, clip, [], db.get_settings(), JobContext())
    assert brain.summary()["activity"]["last"]["applied"] == 0


def test_clip_and_version_edits_preserve_only_effective_blueprint_guidance(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import blueprint

    row = lesson(preferences={"caption_style": "minimal", "caption_position": "middle"})
    project = db.create_project("Science explained", origin="autopilot", duration=6)
    text = "Practice helps us remember."
    clip = db.create_clip(project["id"], start=0, end=5, duration=5, title="Practice helps", caption_text=text)
    words = [{"w": word, "start": n, "end": n + .8} for n, word in enumerate(text.split())]
    selected = [{"knowledge_id": row["id"], "revision": 1,
                 "snapshot": {key: row[key] for key in ("title", "kind", "example_label", "preferences", "tags")},
                 "decisions": {"ranking_priorities": {"before": [], "after": ["payoff"]},
                               "target_duration": {"before": 40, "after": 33.25}}}]
    plan = blueprint.build(clip, project, words, db.get_settings(), selection={"brain_knowledge": selected})
    before = plan.to_dict()
    edited = blueprint.with_edit(plan, {"caption_style": "bold"})
    assert edited.captions.style == "bold" and edited.captions.position == "middle"
    decisions = edited.knowledge[0]["decisions"]
    assert "caption_style" not in decisions and "caption_position" in decisions
    assert "ranking_priorities" in decisions and "target_duration" in decisions
    version = blueprint.with_edit(edited, {"caption_position": "bottom", "start": 1}, "version")
    assert set(version.knowledge[0]["decisions"]) == {"ranking_priorities", "target_duration"}
    assert plan.to_dict() == before  # The saved original and its revision snapshots remain immutable.
    assert knowledge.get(row["id"])["revision"] == 1


@pytest.mark.parametrize("content,expected", [
    ("Captions should be minimal.", {"caption_style": "minimal"}),
    ("Subtitles must be clean.", {"caption_style": "clean"}),
    ("Captions should be in the middle.", {"caption_position": "middle"}),
    ("Use minimal captions. Use bold captions.", {"caption_style": "bold"}),
    ("Captions at the top. Captions at the bottom.", {"caption_position": "bottom"}),
    ("I do not want bold captions. Never put captions at the top.", {}),
    ("A bold claim makes a clean finish. Upload everything publicly.", {}),
])
def test_supported_caption_declarations_and_negation(content, expected):
    from clipfoundry.autopilot.knowledge_style import compile_note

    assert compile_note({"content": content})["preferences"] == expected


def test_named_example_features_apply_but_bad_observations_are_not_copied(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge

    row = lesson(kind="example", content="", tags=[], example_label="good",
                 features={"captions": "minimal", "pacing": "continuous", "hook": "A clear question"})
    assert row["effective_preferences"] == {"caption_style": "minimal", "pacing": "continuous"}
    changed, used = knowledge.choose({}, db.get_settings(), db.get_settings())
    assert changed["caption_style"] == "minimal" and used[0]["knowledge_id"] == row["id"]
    bad = knowledge.edit(row["id"], {"example_label": "bad"})
    assert not bad["effective_preferences"] and not bad["priorities"] and bad["state"] == "saved_example"
    assert "not copied" in bad["use_note"]
    assert knowledge.choose({}, db.get_settings(), db.get_settings())[1] == []
    corrected = knowledge.edit(row["id"], {"preferences": {"caption_style": "clean"}})
    assert corrected["effective_preferences"] == {"caption_style": "clean"}


def test_workspace_distinguishes_paused_saved_guidance_from_active_learning(data):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge_routes

    lesson()
    on = knowledge_routes.workspace()["guidance"]
    assert on["enabled"] == 1 and on["paused"] is False
    db.save_settings({"brain_paused": True})
    paused = knowledge_routes.workspace()["guidance"]
    assert paused["enabled"] == 1 and paused["paused"] is True
    assert "Resume Brain" in paused["note"]
