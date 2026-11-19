"""The Brain steers clip picking (brain/steer.py), clips grow to their build-up and ending (virality.grown), and
the results of posted clips become lessons the Brain picks by (brain/lessons.py)."""
from __future__ import annotations

import json
import time

import pytest

from clipfoundry import config, db
from clipfoundry.brain import lessons, memories, steer
from clipfoundry.pipeline import candidates, process, scoring, scout, transcribe, virality
from clipfoundry.pipeline.common import JobContext
from clipfoundry.pipeline.text_utils import build_sentences
from test_core import _srt, flat_loudness

DAY = 86400.0


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    db.init()


def _kinds(text: str, **kw) -> dict:
    return steer.read(text, **kw)["kinds"]


@pytest.mark.parametrize("said, kinds", [
    ("I love funny moments", {"funny": 1}),
    ("My audience loves it when I rage", {"reaction": 1}),
    ("never clip the sponsor read", {"promo": -1}),
    ("I hate small talk", {"smalltalk": -1}),
    ("I don't like banter in my clips", {"smalltalk": -1}),
    ("pick funny moments, not sad ones", {"funny": 1, "emotional": -1}),
    ("keep my clips family friendly", {"swearing": -1}),
    ("never skip the laughs when you pick clips", {"funny": 1}),
    # not about which moment to pick
    ("no music under funny moments", {}),
    ("captions on funny clips should be yellow", {}),
    ("I'm a funny guy", {}),
    ("the hook fails if it is slow", {}),
])
def test_what_the_owner_says_is_read_into_kinds_of_moment(said, kinds):
    assert _kinds(said, owner=True) == kinds


def test_imported_advice_is_read_with_care():
    assert _kinds("Pass over conversational consensus and polite banter: they don't provoke the comment debate "
                  "that a clip needs.", about_picking=True) == {"smalltalk": -1, "friction": 1}
    assert _kinds("Centre each chosen segment on ideological friction, counter-intuitive data or profound "
                  "vulnerability.", about_picking=True) == {"friction": 1, "numbers": 1, "emotional": 1}
    # an example's quoted words and a verb that only describes the edit are not advice
    assert _kinds('Hot Ones\' "funny reaction to every wing" Shorts cut one reaction per wing in rising order',
                  about_picking=True) == {"reaction": 1}
    # nobody's advice is to look for small talk, whatever the sentence looks like
    assert _kinds("Conversational consensus and polite banter fail to start anything.", about_picking=True) == {
        "smalltalk": -1}
    # advice about something else says nothing about picking unless it names clips
    assert _kinds("Moody contrast suits a mystery and a thriller.") == {}


def test_the_owners_rule_outweighs_lessons_and_one_source_speaks_once():
    lines = [
        {"id": "s1", "from": "skill", "level": "skill", "owner": False, "rule": False, "about": True, "name": "Picking",
         "text": "Look for segments centred on ideological friction."},
        {"id": "s1", "from": "skill", "level": "skill", "owner": False, "rule": False, "about": True, "name": "Picking",
         "text": "Friction and debate start the comments."},
        {"id": "m1", "from": "memory", "level": "lesson", "owner": False, "rule": False, "about": True,
         "text": "Keep the laugh or reaction in the clip."},
        {"id": "m2", "from": "memory", "level": "rule", "owner": True, "rule": True, "about": False,
         "text": "never pick clips with a big reaction"},
    ]
    st = steer.compile_lines(lines)
    assert st["kinds"]["friction"]["w"] == pytest.approx(0.35)       # one skill, however many lines
    assert st["kinds"]["funny"]["w"] == pytest.approx(0.5)
    assert st["kinds"]["reaction"] == {"w": -1.0, "owner": True, "by": [st["kinds"]["reaction"]["by"][0]]}
    assert st["kinds"]["reaction"]["by"][0]["id"] == "m2"            # the lesson that says the opposite is not it
    assert steer.compile_lines(lines[:1])["kinds"]["friction"]["by"][0]["name"] == "Picking"


@pytest.mark.parametrize("said, want", [
    ("clips should be at least 40 seconds", {"min": 40.0}),
    ("keep clips under a minute", {"max": 60.0}),
    ("make clips between 30 and 75 seconds", {"min": 30.0, "max": 75.0}),
    ("I want 45 second clips", {"target": 45.0}),
    ("clips about one minute long", {"target": 60.0}),
    ("make the clips longer", {"factor": steer.LONGER}),
    ("my clips are too long", {"factor": steer.SHORTER}),
    ("keep the intro of my clips under 3 seconds", {}),
    ("at least 40 seconds of silence", {}),
    ("stories should be at least 2 minutes", {}),
])
def test_clip_lengths_the_owner_asks_for(said, want):
    assert steer._length(said) == want  # noqa: SLF001


def test_a_length_from_the_brain_keeps_room_between_shortest_and_longest():
    assert steer.lengths({"length": {"min": 40.0}}, 25.0, 90.0, 45.0) == (40.0, 90.0, pytest.approx(56.7, abs=0.1))
    assert steer.lengths({"length": {"min": 60.0}}, 15.0, 60.0, 30.0)[:2] == (60.0, 120.0)
    assert steer.lengths({"length": {"max": 30.0}}, 25.0, 90.0, 45.0)[:2] == (15.0, 30.0)
    assert steer.lengths({"length": {"factor": steer.LONGER}}, 20.0, 60.0, 30.0) == (26.0, 78.0, 39.0)
    assert steer.lengths({"length": {"min": 500.0}}, 25.0, 90.0, 45.0)[:2] == (170.0, 180.0)
    assert steer.lengths({}, 25.0, 90.0, 45.0) == (25.0, 90.0, 45.0)


def _project(**options) -> dict:
    return db.create_project("A talk", source_path="/tmp/none/source.mp4", options=options)


def test_clip_options_follow_the_brain_but_not_over_the_projects_own_lengths():
    settings = db.get_settings()
    memories.remember("local", "clips should be at least 40 seconds", kind="rule")
    memories.remember("local", "I love funny moments", kind="rule")
    opts = process._options(_project(), settings)  # noqa: SLF001
    assert (opts["min_duration"], opts["max_duration"]) == (40.0, 90.0)
    assert opts["brain_steer"]["kinds"]["funny"]["w"] == 1.0
    assert opts["brain_steer"]["length"]["after"][0] == 40.0
    # the lengths Settings holds, sent along by the Create page, are not the owner's choice for this project
    sent = {k: settings[k] for k in ("min_duration", "max_duration", "target_duration")}
    same = process._options(_project(**sent), settings)  # noqa: SLF001
    assert same["min_duration"] == 40.0
    chosen = _project(min_duration=10.0, max_duration=30.0, target_duration=20.0)
    own = process._options(chosen, settings)  # noqa: SLF001
    assert (own["min_duration"], own["max_duration"]) == (10.0, 30.0)
    assert own["brain_steer"]["length"]["kept"] and own["brain_steer"]["kinds"]["funny"]["w"] == 1.0


TALK = [
    "Okay, what else, oh, the schedule for next month.",
    "We are moving the show to Thursdays.",
    "Right, so the other thing I wanted to talk about was sleep.",
    "I used to think I was fine on five hours of sleep.",
    "Everybody says that, right, I'm fine on five hours.",
    "Then I wore one of those sleep rings for a month.",
    "My deep sleep was eleven minutes a night.",
    "Eleven.",
    "The doctor told me that is what he sees in people twice my age.",
    "So I made one change, no phone in the bedroom, that's it.",
    "The phone charges in the kitchen now.",
    "First week I hated it, I kept reaching for the phone.",
    "Second week I was falling asleep in ten minutes instead of an hour.",
    "After a month my deep sleep was over an hour a night.",
    "One change, the phone in the kitchen, and I got my brain back.",
    "Anyway, that's the sleep thing, let's take some questions.",
    "Someone asks what microphone this is.",
    "It's the same one everybody has, honestly.",
]


def _setup(lines):
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(lines))})
    sentences = build_sentences(words)
    return words, sentences, flat_loudness(words[-1]["end"]), candidates.sentence_features(sentences, words)


def _find(sentences, prefix):
    return next(k for k, s in enumerate(sentences) if s["text"].startswith(prefix))


OPTS = {**config.DEFAULT_SETTINGS, "min_duration": 25.0, "max_duration": 90.0, "target_duration": 45.0,
        "clip_count": 3, "min_score": 0.0, "ai_provider": "heuristic"}


def test_a_moment_grows_to_its_build_up_but_never_into_another_subject():
    words, sents, loud, feats = _setup(TALK)
    s0, s1 = _find(sents, "The phone charges"), _find(sents, "One change, the phone")
    fuller = virality.grown(s0, s1, sents, OPTS, feats)
    starts = {a for a, _ in fuller}
    assert _find(sents, "My deep sleep was eleven") in starts            # carried over "Eleven." and the doctor
    assert min(starts) >= _find(sents, "Right, so the other thing")       # never back into the schedule
    assert all(b <= s1 for _, b in fuller)                                # "Anyway, ..." starts something else
    assert all(sents[b]["end"] - sents[a]["start"] <= 1.3 * 45.0 for a, b in fuller)
    assert virality.variants(s0, s1, sents, OPTS, feats)                  # the nearby cuts are a list of their own
    base = virality.analyze(s0, s1, sents, feats, words, loud, OPTS)
    grown = scoring._fuller(base, sents, feats, words, loud, OPTS)  # noqa: SLF001
    assert grown["dur"] > base["dur"] + 5 and not grown["blocked"]
    assert grown["s1"] == s1 and grown["s0"] < s0
    # at the ideal length there is nothing to grow toward
    at_ideal = {**OPTS, "target_duration": base["dur"]}
    assert scoring._fuller(base, sents, feats, words, loud, at_ideal) is base  # noqa: SLF001


def test_a_clip_under_the_shortest_length_loses_a_little_and_is_never_cut_out():
    words, sents, loud, feats = _setup(TALK)
    s0, s1 = _find(sents, "The phone charges"), _find(sents, "One change, the phone")
    at = virality.analyze(s0, s1, sents, feats, words, loud, {**OPTS, "min_duration": 15.0})
    under = virality.analyze(s0, s1, sents, feats, words, loud, {**OPTS, "min_duration": 28.0})
    assert at["short_by"] == 0 and 0 < under["short_by"] < 0.25
    assert 0 < at["raw"] - under["raw"] < 0.05 and not under["blocked"]


def test_the_brain_moves_the_score_within_bounds_and_says_why():
    words, sents, loud, feats = _setup(TALK)
    s0, s1 = _find(sents, "I used to think"), _find(sents, "One change, the phone")
    plain = virality.analyze(s0, s1, sents, feats, words, loud, OPTS)
    assert plain["brain_steer"] is None and "brain" not in virality.summary(plain)
    assert "numbers" in virality.summary(plain)["moment"]
    memories.remember("local", "I love clips with specific numbers", kind="rule")
    liked = virality.analyze(s0, s1, sents, feats, words, loud, {**OPTS, "brain_steer": steer.build("local")})
    assert 0 < liked["raw"] - plain["raw"] <= steer.LIMIT + 1e-9
    told = virality.summary(liked)["brain"]
    assert told["points"] > 0 and "specific numbers" in told["why"][0] and "your rule" in told["why"][0]
    assert told["used"][0]["text"] == "I love clips with specific numbers"
    assert "your Brain looks for specific numbers" in scoring.reason_text(liked)
    again = virality.finalize(liked)                                     # a recount keeps what the Brain said
    assert again["raw"] == pytest.approx(liked["raw"])
    # the owner's "never" is a warning on the clip, not a second penalty on top
    memories.remember("local", "never pick clips with specific numbers", kind="rule")
    for row in memories.list_("local"):
        if row["text"].startswith("I love clips"):
            memories.forget("local", row["id"])
    avoided = virality.analyze(s0, s1, sents, feats, words, loud, {**OPTS, "brain_steer": steer.build("local")})
    flag = next(f for f in avoided["flags"] if f["id"] == "brain_avoid")
    assert flag["severity"] == "warn" and "never pick clips with specific numbers" in flag["detail"]
    assert avoided["brain_steer"]["adjust"] == 0 and not avoided["blocked"]
    assert plain["raw"] - avoided["raw"] == pytest.approx(virality.PENALTY["warn"])


def test_the_ai_that_reads_the_video_is_told_what_the_brain_looks_for():
    memories.remember("local", "I love funny moments", kind="rule")
    memories.remember("local", "never clip the sponsor read", kind="rule")
    project = _project()
    opts = process._options(project, db.get_settings())  # noqa: SLF001
    text = scout.brief(opts, project).text()
    assert "look for a funny moment" in text and "pass over an intro, outro or ad read" in text
    assert "I love funny moments" in text                                 # the rule itself, from memory
    uses = [u["where_used"] for m in memories.list_("local") for u in memories.uses("local", m["id"])]
    assert uses and set(uses) == {"clips"}


# ------------------------------------------------------------------ lessons from results
def _posted(kind_text: str, n: int, watched: float, source: int) -> list[str]:
    """`n` clips of one source video, each with a mature reading."""
    project = db.create_project(f"Video {source}", source_path=f"/tmp/none/{source}.mp4", options={})
    ids = []
    for k in range(n):
        clip = db.create_clip(project["id"], rank=k, start=0.0, end=30.0, title="t", hook="", hooks_alt=[],
                              caption_text=kind_text, hashtags=[], category="", score=60.0, scores={},
                              score_source="Local analysis", reason="", analysis={}, post={}, edit={},
                              status="ready", duration=30.0)
        db.execute("INSERT INTO brain_observations (id, clip_id, platform, cohort, group_version, provenance, "
                   "observed_at, age_hours, metrics, dedupe_key, created_at, updated_at) VALUES "
                   "(?, ?, 'tiktok', ?, ?, 'owner_import', ?, 72, ?, ?, ?, ?)",
                   (db.new_id(), clip["id"], COHORT, GROUP, time.time() - DAY,
                    json.dumps({"views": 400, "avg_view_percentage": watched + (k % 3)}), db.new_id(),
                    time.time(), time.time()))
        ids.append(clip["id"])
    return ids


COHORT, GROUP = "selected", 0
REACTION = "Oh my god, no way. What the. Oh no, oh no."
PLAIN = "We moved the desk to the other room and then we had lunch."


@pytest.fixture
def audience(monkeypatch):
    from clipfoundry.autopilot import brain as results
    from clipfoundry.autopilot import learner

    monkeypatch.setattr(learner, "destination_cohort", lambda platform, settings: COHORT)
    monkeypatch.setattr(results, "_group_version", lambda platform, settings: GROUP)


def test_results_become_a_lesson_the_brain_picks_by(audience):
    for source in range(3):
        _posted(REACTION, 3, 62.0, source)
        _posted(PLAIN, 3, 38.0, 10 + source)
    report = lessons.learn(db.get_settings())
    assert len(report["added"]) == 1 and report["lessons"] == 1
    text = report["added"][0]
    assert text.startswith("From your results: look for a big reaction.")
    assert "9 clips against 9" in text and "on TikTok" in text and "not proof" in text
    row = memories.list_("local", q="results")[0]
    assert row["source"] == "did" and lessons.TAG in row["tags"]
    st = steer.build("local")
    assert st["kinds"]["reaction"]["w"] == pytest.approx(steer.WEIGHT["results_strong"])
    assert "your results" in steer.judge(st, REACTION, {"emotion": 0.7})["why"][0]
    assert lessons.learn(db.get_settings())["added"] == []               # the same numbers change nothing
    # the owner forgets it: the same numbers do not bring it back
    memories.forget("local", row["id"])
    assert lessons.learn(db.get_settings()) == {"added": [], "changed": [], "dropped": [], "lessons": 0}
    assert steer.build("local")["kinds"] == {}


def test_too_little_or_unclear_evidence_teaches_nothing(audience):
    _posted(REACTION, 7, 62.0, 0)                                         # one video is not a pattern
    _posted(PLAIN, 9, 38.0, 1)
    assert lessons.learn(db.get_settings())["lessons"] == 0
    assert lessons.learn({**db.get_settings(), "brain_paused": True})["paused"]


def test_a_small_gap_between_kinds_is_not_a_lesson(audience):
    for source in range(3):
        _posted(REACTION, 3, 39.0, source)
        _posted(PLAIN, 3, 38.0, 10 + source)
    assert lessons.learn(db.get_settings()) == {"added": [], "changed": [], "dropped": [], "lessons": 0}


def test_saved_old_default_lengths_move_to_the_new_ones_once():
    assert (config.DEFAULT_SETTINGS["min_duration"], config.DEFAULT_SETTINGS["target_duration"],
            config.DEFAULT_SETTINGS["max_duration"]) == (25.0, 45.0, 90.0)
    db.save_settings(dict(db.OLD_CLIP_LENGTHS))
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.CLIP_LENGTHS_MIGRATION,))
    with db.connect() as conn:
        db._migrate_clip_lengths(conn)  # noqa: SLF001
    assert db.get_settings()["min_duration"] == 25.0 and db.get_settings()["max_duration"] == 90.0
    db.save_settings(dict(db.OLD_CLIP_LENGTHS))                           # chosen after the move: kept
    with db.connect() as conn:
        db._migrate_clip_lengths(conn)  # noqa: SLF001
    assert db.get_settings()["min_duration"] == 15.0
    db.execute("DELETE FROM autopilot_state WHERE key = ?", (db.CLIP_LENGTHS_MIGRATION,))
    db.save_settings({"min_duration": 15.0, "max_duration": 45.0, "target_duration": 30.0})  # one changed: theirs
    with db.connect() as conn:
        db._migrate_clip_lengths(conn)  # noqa: SLF001
    assert db.get_settings()["max_duration"] == 45.0 and db.get_settings()["min_duration"] == 15.0
