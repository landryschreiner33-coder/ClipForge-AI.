"""Clips → Full stories (CF-03 to CF-06): complete-story proposals checked against labelled recordings.

Detection runs on the annotated transcripts in story_fixtures.py; the slow test renders real synthesized speech and
checks the actual output files. Mocked segmentation is not used anywhere here.
"""
from __future__ import annotations

import pytest

from story_fixtures import REDDIT_TITLES, cut_off_and_ambiguous, read_aloud, reddit_reader, three_stories, timed

TOLERANCE = 1.0  # seconds of measured silence padding allowed around a labelled boundary


def test_long_story_waits_for_channel_verification_before_any_upload(monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate
    from clipfoundry.publish import routes
    from clipfoundry.studio import autopublish

    clip = {"id": "long-story", "project_id": "p", "status": "ready", "duration": 16 * 60,
            "analysis": {}, "render_info": {"width": 1080, "height": 1920}}
    request = {"auto": ["a", "b"], "accounts": {"a": "channel-a", "b": "channel-b"}}
    monkeypatch.setattr(db, "get_clip", lambda _: clip)
    monkeypatch.setattr(db, "get_project", lambda _: {"workspace_id": "local", "destinations": request})
    monkeypatch.setattr(db, "get_settings", lambda: {})
    monkeypatch.setattr(db, "get_connection", lambda cid: {
        "id": cid, "platform": "youtube", "status": "connected", "external_id": "channel-" + cid})
    monkeypatch.setattr(db, "list_publications", lambda *args: [])
    monkeypatch.setattr(db, "update_clip", lambda _, **values: clip.update(values))
    monkeypatch.setattr(gate, "run", lambda *args: {"status": "passed"})
    uploaded = []
    monkeypatch.setattr(routes, "publish", lambda *args: uploaded.append(args))

    autopublish.after_render(clip["id"])

    assert uploaded == []
    results = clip["analysis"]["destinations"]
    assert {d["connection_id"] for d in results} == {"a", "b"}
    assert all(d["state"] == "held" and "cannot confirm" in d["text"] for d in results)
    assert clip["status"] == "ready"  # keep the complete master available


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
    ends = {"A": 190, "B": 440, "C": 700}  # B runs until C starts: the remark between them stays with B
    for item, key in zip(found, "ABC"):
        a, _b = fx["labels"][key]
        assert abs(item["start"] - a) <= TOLERANCE and abs(item["end"] - ends[key]) <= TOLERANCE, (key, item)
        assert item["opening"] == fx["openings"][key]
        assert item["completeness"] == "complete" and item["end"] - item["start"] > 60  # not a teaser
    assert found[0]["closing"] == fx["closings"]["A"] and found[2]["closing"] == fx["closings"]["C"]
    assert found[1]["closing"] == "Grab a drink, because the last one is long."  # the remark after B
    assert [g["label"] for g in gaps] == ["intro", "sponsor", "outro"]  # the transition is part of B's clip
    assert found[1]["end"] == found[2]["start"]  # nothing between two stories is lost
    for x, y in zip(found, found[1:]):
        assert x["end"] <= y["start"]
    assert result["method"].startswith("local estimate")  # never presented as semantic understanding
    assert found[0]["title"] == "This one time I got completely lost in the forest with nothing but a…"


def test_cf05_a_story_crossing_a_chunk_boundary_stays_one_story():
    from clipfoundry.pipeline import stories

    transcript, fx = three_stories()
    result = _propose(transcript, 720.0)
    edges = [c["end"] for c in result["chunks"]][:-1] + [c["start"] for c in result["chunks"]][1:]
    b = next(i for i in result["items"] if i["opening"] == fx["openings"]["B"])
    assert any(b["start"] < e < b["end"] for e in edges)  # B really spans chunk edges (6:00 among them)
    assert stories.CHUNK_S == 360.0
    assert fx["labels"]["B"][1] - 1 < b["end"] and b["end"] <= fx["labels"]["C"][0] + TOLERANCE  # one story, up to C


# ------------------------------------------------------------------ a narrator reading posts straight through
def _sentences(transcript):
    from clipfoundry.pipeline import transcribe
    from clipfoundry.pipeline.text_utils import build_sentences

    return build_sentences(transcribe.flatten_words(transcript))


def test_reddit_reader_every_post_is_one_clip_until_the_next_with_no_pauses_at_all():
    transcript, fx = reddit_reader()
    result = _propose(transcript, transcript["duration"])
    items = result["items"]
    found = [i for i in items if i["kind"] == "story"]
    labels = [p for p in fx["parts"] if p[0] == "story"]
    assert len(found) == 5 and [g["label"] for g in items if g["kind"] == "gap"] == ["intro", "outro"]
    for item, (_kind, start, _end), title in zip(found, labels, REDDIT_TITLES):
        assert abs(item["start"] - start) <= TOLERANCE, (item["title"], item["start"], start)
        expected = title.rstrip(".")
        assert item["title"] == (expected[:70].rsplit(" ", 1)[0] + "…" if len(expected) > 70 else expected)
        assert item["completeness"] == "complete" and item["confidence"] >= 0.8
    for x, y in zip(found, found[1:]):
        assert x["end"] == y["start"]  # each story runs exactly until the next one starts
    remark = next(p for p in fx["parts"] if p[0] == "remark")
    assert found[0]["end"] > remark[2] and found[0]["closing"] == "Man, that one still gets me every time."
    assert found[-1]["end"] < next(p for p in fx["parts"] if p[0] == "outro")[1]
    assert result["numbered"] == 3 and result["separators"] == ["story N"]
    # the update, the edit and the comments read out inside a post never split it; nor does a long breath
    sents = _sentences(transcript)
    starts = {round(b["time"]) for b in result["boundaries"]}
    for s in sents:
        if s["text"].startswith(("Update:", "Edit:", "Top comment:", "Someone replied")):
            assert round(s["start"]) not in starts and round(s["start"] - 0.1) not in starts
    long_breaths = [s for s, n in zip(sents, sents[1:]) if n["start"] - s["end"] > 3.0]
    assert len(long_breaths) == 2 and all(round(n["start"]) not in starts for n in long_breaths)


def test_silence_alone_never_splits_and_the_story_number_wins_over_a_pause():
    from clipfoundry.pipeline import stories

    body = ["We walked past the venue and the caterer while my friend checked the seating.",
            "Then the dress started to look different and the flowers were nowhere near the cake.",
            "My cousin kept talking about the vows even though the photographer needed attention.",
            "Somehow the ceremony ended up next to the reception and nobody could explain the toddlers."]
    quiet = read_aloud([("story", ["Story one.", "AITA for leaving early?", *body, *body]),
                        ("story", ["Story two.", "TIFU by sleeping in.", *body, *body])],
                       pauses={body[1]: 4.0})  # four long breaths, all inside the stories
    transcript, _ = quiet
    result = _propose(transcript, transcript["duration"])
    found = [i for i in result["items"] if i["kind"] == "story"]
    assert [i["title"] for i in found] == ["AITA for leaving early?", "TIFU by sleeping in"]
    assert all(b["gap"] < 1.0 for b in result["boundaries"])  # the number decides, never the silence
    assert stories.title_like("Am I wrong for selling the car?") and not stories.title_like("We drove to the lake.")
    assert stories.continues("Update: she never called.") and stories.continues("Top comment says I was right.")
    assert not stories.continues("The next morning I called her.")
    assert stories.numbered(_sentences(transcript)) and not stories.numbered(
        _sentences(read_aloud([("story", ["The first one is black.", "The second one is white."])])[0]))


def test_story_titles_come_from_the_post_not_the_announcement():
    from clipfoundry.pipeline import stories

    assert stories.story_title([{"text": "Next story."}, {"text": "My boss made me work on my wedding day."}]) == \
        "My boss made me work on my wedding day"
    assert stories.story_title([{"text": "Posted by u/throwaway in r/AITA: AITA for leaving the party early?"}]) == \
        "AITA for leaving the party early?"
    assert stories.story_title([{"text": "Okay, so story number four, titled WIBTA if I moved out?"}]) == "WIBTA if I moved out?"
    assert stories.story_title([{"text": "One day I was walking home from work."}]) == "One day I was walking home from work"
    assert stories.story_title([{"text": "The third story was wild."}, {"text": "So my sister adopted a goat."}]) == \
        "My sister adopted a goat"


class _FakeJudge:
    """Stands in for ClipForge AI: answers from a fixed table, or fails."""

    def __init__(self, answers: dict[int, bool] | None = None, fail: bool = False):
        self.answers, self.fail, self.asked = answers or {}, fail, []

    def review(self, accepted, near):
        from clipfoundry.pipeline import stories

        self.asked = [b["after"] for b in accepted if b["score"] < 0.7] + [b["after"] for b in near]
        if self.fail:
            raise RuntimeError("model down")
        kept = [b for b in accepted if self.answers.get(b["after"], True)]
        kept += [{**b, "score": stories.THRESHOLD} for b in near if self.answers.get(b["after"])]
        return sorted(kept, key=lambda b: b["time"]), {"answered": len(self.asked)}


GARDEN = ["Our whole garden was taken over by beetles that summer.", "The tomatoes drooped and the roses lost their petals.",
          "I bought a rake, a hose and three bags of compost.", "Every evening I pulled weeds until the shovel bent.",
          "The sunflowers came back taller than the fence.", "By August the harvest filled every basket we owned.",
          "The beetles never returned to the tomatoes or the roses.", "We finally saved the garden after a long summer."]
HIGHWAY = ["The ridge above the creek was where the lantern went missing.", "We hiked past the campfire with a compass and a map.",
           "The trail climbed through pines toward the valley.", "My boots filled with creek water near the tent.",
           "The branches scratched the backpack on the way up the ridge.", "Nobody remembered where the lantern was last lit.",
           "The compass pointed back toward the campfire by morning.", "We walked out of the forest with the map in pieces."]


def _two_topics():
    """Two stories read straight through: no pause, no announcement, nothing but a change of subject."""
    transcript, _ = read_aloud([("story", GARDEN), ("story", HIGHWAY)])
    return transcript, _sentences(transcript)


def test_the_model_can_confirm_a_near_miss_and_deny_a_weak_boundary_but_never_replaces_the_rules():
    from clipfoundry.pipeline import stories, transcribe

    transcript, sents = _two_topics()
    words, duration = transcribe.flatten_words(transcript), transcript["duration"]
    plain = stories.propose(words, sents, duration)
    assert sum(1 for i in plain["items"] if i["kind"] == "story") == 1  # the rules alone keep them together
    joint = next(k for k, s in enumerate(sents) if s["text"].startswith("The ridge above the creek")) - 1
    _accepted, near, _chunks, _marks = stories.candidates(sents, duration)
    assert joint in {b["after"] for b in near}  # a change of subject: close enough to ask about
    judged = stories.propose(words, sents, duration, judge=_FakeJudge({joint: True}))
    found = [i for i in judged["items"] if i["kind"] == "story"]
    assert len(found) == 2 and found[1]["opening"].startswith("The ridge above the creek")
    assert found[0]["end"] == found[1]["start"] and judged["method"].endswith("checked by ClipForge AI")
    denied = stories.propose(words, sents, duration, judge=_FakeJudge({joint: False}))
    assert sum(1 for i in denied["items"] if i["kind"] == "story") == 1


def test_the_real_judge_parses_answers_and_survives_a_dead_model(monkeypatch):
    from clipfoundry.pipeline import stories

    transcript, sents = _two_topics()
    joint = next(k for k, s in enumerate(sents) if s["text"].startswith("The ridge above the creek")) - 1
    accepted, near, _chunks, _marks = stories.candidates(sents, transcript["duration"])
    prompts = []

    def model(settings, prompt, **kw):
        prompts.append(prompt)
        place = next(n for n, b in enumerate([b for b in near if b["after"] == joint], 1))
        return '{"new_story": [%d]}' % place if "marked" in prompt else '{"titles": {"1": "The ridge and the creek"}}'

    judge = stories.Judge({"ai_provider": "builtin", "ai_edit_timeout_s": 5}, sents, budget_s=30, complete=model)
    kept, report = judge.review(accepted, [b for b in near if b["after"] == joint])
    assert joint in {b["after"] for b in kept} and report["answered"] == 1 and report["changed"] == 1
    assert ">>> marked:" in prompts[0] and "new_story" in prompts[0]
    titles = judge.titles([{"kind": "story", "opening": "The ridge above the creek was where the lantern went missing."}])
    assert titles == {0: "The ridge and the creek"}  # only words that are said
    assert judge.titles([{"kind": "story", "opening": "Nothing in common here."}]) == {}

    def dead(settings, prompt, **kw):
        from clipfoundry.pipeline import llm

        raise llm.ProviderError("no model")

    broken = stories.Judge({"ai_provider": "builtin"}, sents, budget_s=30, complete=dead)
    kept2, report2 = broken.review(accepted, near)
    assert [b["after"] for b in kept2] == [b["after"] for b in accepted] and report2["problems"]


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
    long_video = eligibility.youtube(16 * 60, 1080, 1920)
    assert long_video["state"] == "needs_verified" and not long_video["eligible"]
    assert eligibility.youtube(15 * 60, 1080, 1920)["eligible"]
    destinations = eligibility.for_output(16 * 60, 1080, 1920, [
        {"id": "channel-a", "platform": "youtube", "display_name": "Channel A"},
        {"id": "channel-b", "platform": "youtube", "display_name": "Channel B"},
    ])
    assert all(not d["eligible"] and d["state"] == "needs_verified" for d in destinations)


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


def test_every_story_becomes_a_clip_uncertain_ones_too_and_nothing_waits(project, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import process, transcribe
    from clipfoundry.studio import story_review

    p, fx = project
    transcript, _ = three_stories()
    monkeypatch.setattr(process, "load_words", lambda project: transcribe.flatten_words(transcript))
    stories = [s for s in story_review.list_for(p["id"]) if s["kind"] == "story"]
    db.update("story_proposals", stories[2]["id"], completeness="uncertain")
    made = story_review.create_selected(p["id"])  # every included story, however sure ClipForge is
    assert len(made) == 3 and all(c["category"] == "story" for c in made)
    for clip, story in zip(made, stories):
        assert clip["start"] == pytest.approx(story["start"]) and clip["end"] == pytest.approx(story["end"])
        assert clip["edit"] == {"silence": "off", "remove_fillers": False, "hook_overlay": False}
    assert fx["openings"]["A"].split()[0] in made[0]["caption_text"]
    assert db.fetch("story_proposals", stories[2]["id"])["completeness"] == "uncertain"  # a label, not a gate
    assert story_review.create_selected(p["id"]) == []  # nothing left to make
    words = transcribe.flatten_words(transcript)
    assert story_review.auto_clips(db.get_project(p["id"]), words, {}) == []
    db.update("story_proposals", stories[1]["id"], clip_id="")
    assert [c["start"] for c in story_review.auto_clips(db.get_project(p["id"]), words, {})] == \
        [pytest.approx(stories[1]["start"])]  # the pipeline makes the missing one without asking
