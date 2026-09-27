"""Viral Potential scoring: factors, sub-scores, structure, avoidance flags and the quality gate."""
from __future__ import annotations

import sqlite3

import pytest

from clipfoundry import config
from clipfoundry.pipeline import candidates, llm, scoring, transcribe, virality
from clipfoundry.pipeline.common import JobContext
from clipfoundry.pipeline.text_utils import build_sentences
from test_core import _srt, flat_loudness

PODCAST = [
    "Hey guys, welcome back to the channel.",
    "So today I want to talk about a few things that happened this month.",
    "Before we start, make sure you hit the bell so you don't miss anything.",
    "Okay so, the first thing is the new studio.",
    "We moved everything last week and it took forever.",
    "Here's the thing nobody tells you about quitting your job.",
    "Everyone thinks the hard part is the money.",
    "It's not. The hard part is the silence.",
    "For ten years my calendar told me what to do every single hour.",
    "Then one Monday I woke up and nobody needed me for anything.",
    "I was terrified. I sat in my car for an hour because I didn't know where to go.",
    "What I learned is that freedom without a plan feels exactly like being lost.",
    "So now I plan my week every Sunday night, and that one habit changed everything.",
    "Anyway, let's move on to the questions from the comments.",
    "Somebody asked about the camera we use.",
    "It's a pretty normal camera, nothing special.",
    "We use it with the lens that came with it.",
    "And the lighting is just two lamps from the hardware store.",
    "It's really, really important to be consistent. It's really important, you know, to be consistent.",
    "Consistency is really important, it's really, really important.",
    "Why do most people give up on running after three weeks?",
    "Because they start way too fast.",
    "Your body needs about six weeks to adapt to the impact.",
    "If you run slowly enough to hold a conversation, you recover faster and you keep going.",
    "That's why the slowest runners in my club are the ones who are still running a year later.",
    "So what do you think happened when we tried that with the beginners group?",
    "Almost all of them finished the race, and most of them are still running today.",
    "Exactly. And that's what he told me too.",
    "He said the same thing about the other one.",
    "We should probably talk about the schedule for next week.",
    "The meeting is on Tuesday, bring your notes, and that's all for today.",
]


def _setup(lines: list[str]):
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(lines))})
    sentences = build_sentences(words)
    loud = flat_loudness(words[-1]["end"])
    return words, sentences, loud, candidates.sentence_features(sentences, words)


def _find(sentences: list[dict], prefix: str) -> int:
    return next(k for k, s in enumerate(sentences) if s["text"].startswith(prefix))


def _analyze(lines: list[str], first: str, last: str) -> dict:
    words, sentences, loud, feats = _setup(lines)
    return virality.analyze(_find(sentences, first), _find(sentences, last), sentences, feats, words, loud,
                            dict(config.DEFAULT_SETTINGS))


@pytest.fixture(scope="module")
def podcast():
    words, sentences, loud, _ = _setup(PODCAST)
    opts = dict(config.DEFAULT_SETTINGS)
    cands = candidates.find_candidates(words, sentences, loud, opts, pool_size=12)
    results, _ = scoring.evaluate(cands, sentences, opts, JobContext(), "podcast", 0, 1, words=words, loud=loud)
    return sentences, results


def test_quality_over_quantity_only_strong_clips_no_filler(podcast):
    sentences, results = podcast
    chosen = scoring.select(results, 10, 50)
    firsts = sorted(sentences[c["s0"]]["text"] for c in chosen)
    assert firsts == ["Here's the thing nobody tells you about quitting your job.",
                      "Why do most people give up on running after three weeks?"]  # 10 requested, 2 good ones exist
    assert all(c["score"] >= 70 for c in chosen)
    report = scoring.quality_report(results, chosen, 10, 50)
    assert report["shown"] == 2 and report["requested"] == 10 and report["rejected"]
    assert all(r["reasons"] for r in report["rejected"])
    assert "Not a guarantee" in report["note"]


def test_nothing_passes_means_no_clips():
    words, sentences, loud, _ = _setup(PODCAST[13:20])  # camera questions + repetition only
    opts = dict(config.DEFAULT_SETTINGS)
    cands = candidates.find_candidates(words, sentences, loud, opts, pool_size=8)
    results, _ = scoring.evaluate(cands, sentences, opts, JobContext(), "x", 0, 1, words=words, loud=loud)
    assert results and scoring.select(results, 5, 50) == []


def test_ranking_and_subscores(podcast):
    sentences, results = podcast
    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    assert [r["score"] for r in ranked] == sorted((r["score"] for r in results), reverse=True)
    best = virality.summary(ranked[0]["analysis"])
    assert set(best["factors"]) == set(virality.FACTORS) and len(best["factors"]) == 11
    assert all(0 <= v <= 10 for v in best["factors"].values())
    assert set(best["subscores"]) == {"hook", "retention", "context", "engagement"}
    assert all(0 <= v <= 100 for v in best["subscores"].values())
    assert "Not a guarantee" in best["note"]


def test_hook_context_payoff_structure_detected(podcast):
    sentences, results = podcast
    run = next(r for r in results if sentences[r["s0"]]["text"].startswith("Why do most people"))
    assert run["analysis"]["structure"]["complete"]
    assert run["analysis"]["structure"]["label"] == "Hook → Context → Payoff"


def test_opening_is_moved_back_to_the_hook_and_warm_up_is_dropped(podcast):
    sentences, results = podcast
    quit_clip = next(r for r in results if "quitting your job" in r["caption_text"])
    assert sentences[quit_clip["s0"]]["text"].startswith("Here's the thing nobody tells you")
    assert "welcome back" not in quit_clip["caption_text"]
    assert sentences[quit_clip["s1"]]["text"].endswith("that one habit changed everything.")


def test_ending_stops_at_the_payoff_not_in_the_chatter_after_it(podcast):
    sentences, results = podcast
    run = next(r for r in results if sentences[r["s0"]]["text"].startswith("Why do most people"))
    assert "Exactly." not in run["caption_text"] and "told me too" not in run["caption_text"]


def test_ending_includes_the_point_after_a_setup_line():
    from test_core import SCRIPT

    words, sentences, loud, _ = _setup(SCRIPT)
    opts = dict(config.DEFAULT_SETTINGS)
    cands = candidates.find_candidates(words, sentences, loud, opts, pool_size=8)
    results, _ = scoring.evaluate(cands, sentences, opts, JobContext(), "x", 0, 1, words=words, loud=loud)
    biz = next(r for r in results if "biggest mistake" in r["caption_text"])
    assert sentences[biz["s1"]]["text"] == "Talk to customers first, then build."


def test_misleading_cut_before_the_point_is_blocked():
    r = _analyze(PODCAST, "We moved everything", "It's not.")
    assert any(f["id"] == "misleading_cut" and f["severity"] == "block" for f in r["flags"]) and r["blocked"]


def test_cut_before_an_answer_is_blocked():
    r = _analyze(PODCAST, "Why do most people", "So what do you think happened")
    assert any(f["id"] == "misleading_cut" and "answer" in f["detail"] for f in r["flags"])


def test_slow_opening_and_excessive_setup():
    r = _analyze(PODCAST, "Hey guys", "It's not.")
    ids = {f["id"] for f in r["flags"]}
    assert "slow_opening" in ids and "excessive_setup" in ids
    assert r["factors"]["opening"] < 0.5


def test_repetitive_segment_is_flagged():
    r = _analyze(PODCAST, "And the lighting", "Consistency is really important")
    assert any(f["id"] == "repetitive" for f in r["flags"])
    assert r["factors"]["uniqueness"] < 0.8


def test_reply_start_and_topic_change_need_context():
    r = _analyze(PODCAST, "Exactly.", "The meeting is on Tuesday")
    ids = {f["id"] for f in r["flags"]}
    assert {"weak_context", "topic_change"} <= ids and r["blocked"]
    assert r["factors"]["standalone"] < 0.4


def test_weak_ending_mid_sentence_blocks():
    words, sentences, loud, feats = _setup(PODCAST)
    k = _find(sentences, "Why do most people")
    feats = [dict(f) for f in feats]
    feats[k + 3]["complete"] = False  # e.g. Whisper cut the sentence off
    r = virality.analyze(k, k + 3, sentences, feats, words, loud, dict(config.DEFAULT_SETTINGS))
    assert any(f["id"] == "weak_ending" and f["severity"] == "block" for f in r["flags"])


def test_speaker_clarity_uses_whisper_confidence_but_not_placeholders():
    words, sentences, loud, feats = _setup(PODCAST)
    k = _find(sentences, "Why do most people")
    opts = dict(config.DEFAULT_SETTINGS)

    def clarity(p):
        ws = [dict(w, **({"p": p} if p is not None else {})) for w in words]
        return virality.analyze(k, k + 4, sentences, feats, ws, loud, opts)["factors"]["clarity"]

    assert clarity(0.95) > clarity(0.45)
    assert clarity(1.0) == clarity(None)  # 1.0 everywhere = subtitles imported by old versions, not a measurement


def test_pool_uniqueness_lowers_similar_candidates():
    words, sentences, loud, feats = _setup(PODCAST)
    opts = dict(config.DEFAULT_SETTINGS)
    k = _find(sentences, "Why do most people")
    a = virality.analyze(k, k + 4, sentences, feats, words, loud, opts)
    b = virality.analyze(k, k + 5, sentences, feats, words, loud, opts)
    c = virality.analyze(_find(sentences, "Somebody asked"), _find(sentences, "And the lighting"), sentences, feats,
                         words, loud, opts)
    virality.set_uniqueness([a, b, c])
    assert a["factors"]["uniqueness"] < c["factors"]["uniqueness"]


def test_ai_factors_are_blended_and_legacy_answers_still_work():
    raw = '{"hook": 9, "opening": 8, "curiosity": 10, "emotion": 7, "payoff": 9, "standalone": 9, "pacing": 8,' \
          ' "density": 6, "retention": 9, "category": "Story", "title": "t"}'
    out = llm.parse_response(raw, 3)
    assert out["factors"]["curiosity"] == 10.0 and "clarity" not in out["factors"]
    r = _analyze(PODCAST, "Somebody asked", "And the lighting")
    before = r["factors"]["curiosity"]
    virality.blend_ai(r, out["factors"])
    assert r["factors"]["curiosity"] == pytest.approx(0.6 + 0.4 * before)
    legacy = llm.parse_response('{"hook": 8, "engagement": 7, "context": 6, "payoff": 5, "standalone": 9}', 3)
    assert legacy["factors"] == {"hook": 8.0, "payoff": 5.0, "standalone": 9.0}
    assert legacy["scores"]["engagement"] == 7.0


def test_existing_database_gets_the_new_column(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "clipfoundry.db")
    conn.execute("CREATE TABLE clips (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, start REAL NOT NULL, "
                 "end REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    conn.execute("INSERT INTO clips VALUES ('old', 'p', 0, 1, 0, 0)")
    conn.commit()
    conn.close()
    from clipfoundry import db

    with db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(clips)")}
        row = c.execute("SELECT analysis FROM clips WHERE id = 'old'").fetchone()
    assert "analysis" in cols and row[0] == "{}"
