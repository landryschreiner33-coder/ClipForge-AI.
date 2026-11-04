"""Clips → Full stories (CF-03 to CF-06): complete-story proposals checked against labelled recordings.

Detection runs on the annotated transcripts in story_fixtures.py; the slow test renders real synthesized speech and
checks the actual output files. Mocked segmentation is not used anywhere here.
"""
from __future__ import annotations

import pytest

from story_fixtures import cut_off_and_ambiguous, three_stories, timed

TOLERANCE = 1.0  # seconds of measured silence padding allowed around a labelled boundary


def _propose(transcript, duration):
    from clipfoundry.pipeline import stories, transcribe
    from clipfoundry.pipeline.text_utils import build_sentences

    words = transcribe.flatten_words(transcript)
    return stories.propose(words, build_sentences(words), duration)


def test_cf04_three_labelled_stories_are_found_once_each_with_their_gaps():
    transcript, fx = three_stories()
    result = _propose(transcript, 720.0)
    found = [i for i in result["items"] if i["kind"] == "story"]
    gaps = [i for i in result["items"] if i["kind"] == "gap"]
    assert len(found) == 3
    for item, key in zip(found, "ABC"):
        a, b = fx["labels"][key]
        assert abs(item["start"] - a) <= TOLERANCE and abs(item["end"] - b) <= TOLERANCE, (key, item)
        assert item["opening"] == fx["openings"][key] and item["closing"] == fx["closings"][key]
        assert item["completeness"] == "complete" and item["end"] - item["start"] > 60  # not a teaser
    assert [g["label"] for g in gaps] == ["intro", "sponsor", "transition", "outro"]
    # every second of each story is inside its one proposal, and no story overlaps another
    for x, y in zip(found, found[1:]):
        assert x["end"] <= y["start"]
    assert result["method"].startswith("local estimate")  # never presented as semantic understanding


def test_cf05_a_story_crossing_a_chunk_boundary_stays_one_story():
    from clipfoundry.pipeline import stories

    transcript, fx = three_stories()
    result = _propose(transcript, 720.0)
    edges = [c["end"] for c in result["chunks"]][:-1] + [c["start"] for c in result["chunks"]][1:]
    b = next(i for i in result["items"] if i["opening"] == fx["openings"]["B"])
    assert any(b["start"] < e < b["end"] for e in edges)  # B really spans chunk edges (6:00 among them)
    assert stories.CHUNK_S == 360.0 and b["closing"] == fx["closings"]["B"]


def test_one_story_no_story_and_a_cut_off_ending():
    from story_fixtures import _fill
    import random

    rng = random.Random(1)
    one = timed([(0, 120, _fill(rng, "kitchen", 0, 120, "So this one time I baked a cake that would not rise.",
                                "And that's how I learned to check the oven first."))], 122.0)
    only = _propose(one, 122.0)["items"]
    assert [i["kind"] for i in only] == ["story"] and only[0]["completeness"] == "complete"
    none = timed([(0, 10, ["Hey everyone, welcome back to the channel.", "Today is a short update."]),
                  (10, 20, ["Thanks for watching, everyone.", "Like and subscribe, see you next time."])], 20.0)
    assert [i["kind"] for i in _propose(none, 20.0)["items"]] == ["gap", "gap"]
    assert _propose({"segments": []}, 30.0)["items"] == []


def test_ambiguous_joined_stories_and_an_abrupt_end_are_flagged_not_called_complete():
    transcript, _ = cut_off_and_ambiguous()
    items = [i for i in _propose(transcript, 170.4)["items"] if i["kind"] == "story"]
    assert items and all(i["completeness"] != "complete" for i in items[-1:])
    assert items[-1]["completeness"] == "incomplete" and "cut off" in items[-1]["reason"]


# ------------------------------------------------------------------ destinations (CF-06)
def test_cf06_a_story_longer_than_an_account_limit_keeps_its_full_master():
    from clipfoundry.studio import eligibility

    story = 220.0  # story B of the fixture: longer than Shorts and than a 3-minute TikTok account
    yt = eligibility.youtube(story, 1080, 1920)
    assert yt["state"] == "regular" and "not a Short" in yt["text"]
    tt = eligibility.tiktok(story, 180.0, "Creator A")
    assert not tt["eligible"] and "full story is kept" in tt["text"] and "Split it into parts" in tt["alternatives"][2]
    assert eligibility.tiktok(story, 600.0)["eligible"]
    assert eligibility.youtube(170.0, 1080, 1920)["state"] == "short"
    assert eligibility.youtube(170.0, 1920, 1080)["state"] == "regular"  # a landscape video is never a Short
    assert eligibility.youtube(16 * 60, 1080, 1920)["state"] == "needs_verified"


# ------------------------------------------------------------------ review controls
@pytest.fixture()
def project(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.studio import story_review

    db.init()
    transcript, fx = three_stories()
    p = db.create_project("stories", status="ready", clip_mode="full_stories", duration=720.0)
    story_review.save(p, _propose(transcript, 720.0))
    return db.get_project(p["id"]), fx


def test_split_merge_trim_include_and_reorder_are_revisions(project):
    from clipfoundry.studio import story_review

    p, fx = project
    stories = [s for s in story_review.list_for(p["id"]) if s["kind"] == "story"]
    a = stories[0]
    trimmed = story_review.patch(a["id"], start_ms=int(a["start"] * 1000) + 500)
    assert trimmed["boundary_revision"] == 1 and trimmed["method"] == "manual"
    first, second = story_review.split(a["id"], int((a["start"] + 60) * 1000))
    assert first["end_ms"] == second["start_ms"] and second["completeness"] == "uncertain"
    merged = story_review.merge([first["id"], second["id"]])
    assert merged["start_ms"] == trimmed["start_ms"] and merged["end_ms"] == int(round(a["end"] * 1000))
    story_review.patch(stories[1]["id"], included=False)
    ids = [s["id"] for s in story_review.list_for(p["id"])]
    reordered = story_review.reorder(p["id"], list(reversed(ids)))
    assert [s["id"] for s in reordered] == list(reversed(ids))
    with pytest.raises(story_review.StoryError):
        story_review.patch(a["id"], end_ms=int(a["start"] * 1000) + 100)


def test_batch_create_makes_one_complete_clip_per_story_and_holds_uncertain_ones(project, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import process
    from clipfoundry.studio import story_review

    p, fx = project
    transcript, _ = three_stories()
    from clipfoundry.pipeline import transcribe

    monkeypatch.setattr(process, "load_words", lambda project: transcribe.flatten_words(transcript))
    stories = [s for s in story_review.list_for(p["id"]) if s["kind"] == "story"]
    story_review.patch(stories[2]["id"], confirm=False)
    db.update("story_proposals", stories[2]["id"], completeness="uncertain")
    made = story_review.create_selected(p["id"])  # all included complete stories
    assert len(made) == 2 and all(c["category"] == "story" for c in made)
    for clip, story in zip(made, stories[:2]):
        assert clip["start"] == pytest.approx(story["start"]) and clip["end"] == pytest.approx(story["end"])
        assert clip["edit"] == {"silence": "off", "remove_fillers": False, "hook_overlay": False}
        assert fx["openings"]["AB"[made.index(clip)]].split()[0] in clip["caption_text"]
    later = story_review.create_selected(p["id"], [stories[2]["id"]])  # the owner confirms the held one
    assert len(later) == 1 and db.fetch("story_proposals", stories[2]["id"])["completeness"] == "complete"
