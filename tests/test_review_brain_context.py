"""Saved example lengths use actual source words before either fresh or resumed candidate selection."""
from __future__ import annotations

import pytest


@pytest.fixture()
def cached_source(tmp_path, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline.common import write_json

    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "profile"))
    db.init()
    db.save_settings({"min_duration": 20, "max_duration": 60, "target_duration": 40})
    directory = tmp_path / "source"
    directory.mkdir()
    meta = {"duration": 80, "width": 1920, "height": 1080, "fps": 30,
            "has_video": True, "has_audio": True}
    project = db.create_project("Episode 42", source_path=str(directory / "source.mp4"), origin="autopilot",
                                info=meta, **{key: meta[key] for key in ("duration", "width", "height", "fps")})
    # Cached files make these decision-stage tests independent of codecs and transcription providers.
    (directory / "audio.wav").touch()
    (directory / "thumb.jpg").touch()
    text = "Science explains why practice improves memory. In the end practice helped us learn."
    words = [{"w": word, "start": n * 2, "end": n * 2 + 1.5} for n, word in enumerate(text.split())]
    write_json(directory / "transcript.json", {"source": "import", "language": "en",
                                                "segments": [{"words": words}]})
    write_json(directory / "loudness.json", {"hop": .1, "db": [-20] * 800})
    return project, words, meta


def saved_example(*, tags=None, enabled=True):
    from clipfoundry.autopilot import knowledge

    return knowledge.create({"kind": "example", "title": "Short lesson", "example_label": "good",
                             "tags": tags if tags is not None else ["science"], "enabled": enabled},
                            media={"duration_s": 13, "width": 576, "height": 1024, "has_audio": True})


def prepared(cached_source, monkeypatch, resume):
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import JobContext

    project, _, meta = cached_source
    if resume:
        return process.load_prepared(project["id"])
    monkeypatch.setattr(process, "probe", lambda path: meta)
    return process.prepare(project["id"], JobContext())


@pytest.mark.parametrize("resume", [False, True], ids=["fresh", "resumed"])
def test_transcript_topic_example_is_used_before_generating_candidates(cached_source, monkeypatch, resume):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge
    from clipfoundry.pipeline import process
    from clipfoundry.pipeline.common import JobContext

    example = saved_example()
    source = prepared(cached_source, monkeypatch, resume)
    assert source.project["name"] == "Episode 42"  # The matching topic occurs only in the measured words.
    assert source.opts["target_duration"] == 33.25
    assert source.opts["brain_base_target_duration"] == 40
    decisions = source.opts["brain_duration_knowledge"]
    assert len(decisions) == 1 and decisions[0]["knowledge_id"] == example["id"]
    assert decisions[0]["revision"] == 1
    assert decisions[0]["decisions"]["target_duration"] == {"before": 40, "after": 33.25}
    # Real candidate generation receives the example-aware options; this does not create or approve a post.
    assert process.candidate_pool(source, JobContext())
    assert not db.select("scheduled_publications")
    later, _ = knowledge.selection_options({"caption_text": "Science shows why practice matters."},
                                           source.opts, source.settings)
    assert later["target_duration"] == 33.25  # Source and candidate lookups cannot compound the length hint.


@pytest.mark.parametrize("resume", [False, True], ids=["fresh", "resumed"])
@pytest.mark.parametrize("condition", ["different-topic", "disabled", "paused"])
def test_unrelated_disabled_or_paused_examples_keep_settings(cached_source, monkeypatch, resume, condition):
    from clipfoundry import db

    saved_example(tags=["cooking"] if condition == "different-topic" else ["science"],
                  enabled=condition != "disabled")
    if condition == "paused":
        db.save_settings({"brain_paused": True})
    source = prepared(cached_source, monkeypatch, resume)
    assert source.opts["target_duration"] == 40
    assert source.opts["brain_duration_knowledge"] == []


@pytest.mark.parametrize("resume", [False, True], ids=["fresh", "resumed"])
def test_current_example_revision_applies_on_resume_without_rewriting_saved_project(cached_source, monkeypatch, resume):
    from clipfoundry import db
    from clipfoundry.autopilot import knowledge

    example = saved_example()
    project, _, _ = cached_source
    original = db.get_project(project["id"])
    knowledge.edit(example["id"], {"content": "Caption style: minimal.", "expected_revision": 1})
    source = prepared(cached_source, monkeypatch, resume)
    assert source.opts["target_duration"] == 33.25
    assert source.opts["brain_duration_knowledge"][0]["revision"] == 2
    current = db.get_project(project["id"])
    assert current["options"] == original["options"]
    assert not db.select("scheduled_publications")
    assert not db.select("publications")
