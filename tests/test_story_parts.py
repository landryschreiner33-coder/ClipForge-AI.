"""Story clips cut into parts (pipeline/story_parts.py): Full story splits a story only past five minutes, Story parts
splits it at its best places, and no story clip is ever longer than five minutes. Checked on labelled transcripts."""
from __future__ import annotations

import itertools
import random

import pytest

from story_fixtures import REDDIT_VOCAB, TEMPLATES, read_aloud


def _body(topic: str, n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    cycle = itertools.cycle(TEMPLATES)
    out = []
    for _ in range(n):
        a, b, c = rng.sample(REDDIT_VOCAB[topic], 3)
        out.append(next(cycle).format(a=a, b=b, c=c) + ".")
    return out


def _story(sentences: list[str], pause: float = 0.45, pauses: dict[str, float] | None = None):
    from clipfoundry.pipeline import transcribe
    from clipfoundry.pipeline.text_utils import build_sentences

    transcript, labels = read_aloud([("story", sentences)], pause=pause, pauses=pauses)
    words = transcribe.flatten_words(transcript)
    _kind, start, end = labels["parts"][0]
    return build_sentences(words), words, start, end


CLIFF = "And that's when I saw the text on her phone."
REVEAL = "Turns out the reservation had been under her name the whole time."
NEXT_DAY = "The next morning my husband would not even look at me."
UPDATE = "Update: we talked to a therapist and things are a little better."


def _seven_minutes():
    """A seven-minute post: a cliffhanger line, a reveal and a jump in time in the story, and the poster's update."""
    body = _body("inlaws", 72, 3)
    sentences = (body[:14] + [CLIFF] + body[14:26] + [REVEAL] + body[26:36] + [NEXT_DAY] + body[36:50] + [UPDATE]
                 + body[50:])
    return _story(sentences)


def _starts_with(parts, sents, text):
    return [p for p in parts if next(s for s in sents if s["end"] > p["start"])["text"] == text]


def test_how_many_parts_a_story_becomes():
    from clipfoundry.pipeline import story_parts as sp

    # a story of five minutes or less is never split in Full story (4:58 included)
    assert [sp.part_count(d, "whole") for d in (60, 295, 298, 299.9, 300, 300.5, 590, 1500)] == [1, 1, 1, 1, 1, 2, 2, 6]
    assert [sp.part_count(d, "parts") for d in (60, 120, 160, 200, 420, 1500)] == [1, 1, 1, 2, 4, 14]
    for d in range(30, 3600, 7):
        for mode in ("whole", "parts"):
            n = sp.part_count(float(d), mode)
            assert d / n <= (sp.MAX_CLIP_S if n == 1 else sp.CAP_PLAN_S)  # never over the cap
            if mode == "parts" and n > 1:
                assert d / n >= sp.PART_MIN_S - 1e-6  # Story parts are always over a minute


def test_full_story_keeps_a_story_whole_until_five_minutes_then_cuts_at_the_best_place():
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, end = _seven_minutes()
    assert 400 < end - start < 440
    parts = sp.split(sents, words, start, end, "whole")
    assert len(parts) == 2 and parts[0]["start"] == start and parts[-1]["end"] == end
    assert parts[0]["end"] == parts[1]["start"]  # nothing lost between the parts
    assert all(p["end"] - p["start"] <= sp.MAX_CLIP_S for p in parts)
    assert _starts_with(parts[1:], sents, NEXT_DAY)  # the jump in time near the middle, not any sentence
    assert "a jump in time" in parts[1]["why"]
    # the poster's update is the best place when both parts it makes fit under five minutes
    body = _body("car", 62, 6)
    sents, words, start, end = _story(body[:36] + [UPDATE] + body[36:])
    assert 300 < end - start < 400
    parts = sp.split(sents, words, start, end, "whole")
    assert len(parts) == 2 and _starts_with(parts[1:], sents, UPDATE)
    assert "the poster's update starts" in parts[1]["why"]
    short = _story(_body("car", 30, 5))
    assert len(sp.split(*short, "whole")) == 1  # under five minutes: one clip, never split


def test_story_parts_end_each_part_on_a_cliffhanger_reveal_or_jump_in_time():
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, end = _seven_minutes()
    parts = sp.split(sents, words, start, end, "parts")
    assert len(parts) == 4
    for p in parts:
        assert sp.PART_MIN_S <= p["end"] - p["start"] <= sp.PART_MAX_S, p
    firsts = [next(s for s in sents if s["end"] > p["start"])["text"] for p in parts[1:]]
    assert REVEAL in firsts or NEXT_DAY in firsts  # a reveal or the next morning opens a part
    lasts = [[s for s in sents if s["end"] <= p["end"] + 0.01][-1]["text"] for p in parts[:-1]]
    assert CLIFF in lasts or any(t in firsts for t in (REVEAL, NEXT_DAY, UPDATE))
    for p in parts[1:]:
        assert p["why"]  # every cut says why it is there
        first = next(s for s in sents if s["end"] > p["start"])
        assert 0 < first["start"] - p["start"] <= sp.LEAD_S + 0.3  # a part starts just before its first word


def test_no_story_clip_is_ever_longer_than_five_minutes():
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, end = _story(_body("wedding", 250, 11))  # a 24-minute post
    assert end - start > 1400
    for mode in ("whole", "parts"):
        parts = sp.split(sents, words, start, end, mode)
        assert parts[0]["start"] == start and parts[-1]["end"] == end
        assert all(a["end"] == b["start"] for a, b in zip(parts, parts[1:]))
        assert max(p["end"] - p["start"] for p in parts) <= sp.MAX_CLIP_S
    assert len(sp.split(sents, words, start, end, "whole")) == sp.part_count(end - start, "whole") == 5


def test_minutes_of_gameplay_without_talking_are_cut_at_the_limit():
    from clipfoundry.pipeline import story_parts as sp

    parts = sp.split([], [], 0.0, 660.0, "whole")
    assert len(parts) == 3 and all(abs(p["end"] - p["start"] - 220) <= 2 for p in parts)
    assert "without talking" in parts[1]["why"][0]


def test_a_story_just_under_ten_minutes_is_cut_between_two_sentences_never_in_one():
    """Parts may be as long as the cap itself (less a little rounding room), so the cut of a 9:50 story lands at a
    sentence boundary near the middle, not between two words where the only room under a stricter limit is."""
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, _end = _story(_body("inlaws", 140, 3))
    for d in (585.0, 588.0, 590.0, 591.5):
        parts = sp.split(sents, words, start, start + d, "whole")
        cut = parts[1]["start"]
        assert len(parts) == 2 and max(p["end"] - p["start"] for p in parts) <= sp.MAX_CLIP_S
        assert not [x for x in sents if x["start"] < cut < x["end"]], d  # not inside a sentence
        assert not any("between two words" in w for w in parts[1]["why"])


def test_minutes_of_silent_gameplay_after_a_post_never_make_a_short_part_or_a_cut_word():
    """A post read for about two and a half minutes, then minutes of gameplay without talking before the next post.
    Story parts never makes a part shorter than a minute out of it, no cut falls inside a word, and a cut inside
    the gameplay says so."""
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, end = _story(_body("inlaws", 26, 3))
    for silent in (130, 170, 250, 300, 330):
        for mode in ("parts", "whole"):
            parts = sp.split(sents, words, start, end + silent, mode)
            assert parts[0]["start"] == start and parts[-1]["end"] == end + silent
            assert max(p["end"] - p["start"] for p in parts) <= sp.MAX_CLIP_S
            if mode == "parts":
                assert min(p["end"] - p["start"] for p in parts) >= sp.PART_MIN_S, (silent, parts)
            for p in parts[1:]:
                assert not [w for w in words if w["start"] < p["start"] < w["end"]]
                if p["start"] > end:
                    assert "without talking" in p["why"][0]


def test_an_hour_long_story_is_split_in_moments_and_never_inside_a_word():
    import random
    import time

    from clipfoundry.pipeline import story_parts as sp

    rng = random.Random(5)
    words, sents, t = [], [], 0.5
    while t < 3548:  # an hour of quick talk: short sentences, short pauses
        said = []
        for _ in range(rng.randint(6, 18)):
            d = rng.uniform(0.15, 0.35)
            said.append({"w": "word", "start": round(t, 3), "end": round(t + d, 3)})
            t += d + rng.uniform(0.02, 0.15)
        said[-1]["w"] = "word."
        words += said
        sents.append({"start": said[0]["start"], "end": said[-1]["end"], "text": " ".join(w["w"] for w in said)})
        t += rng.uniform(0.2, 1.2)
    endless = [{"start": round(0.5 + k * 0.4, 3), "end": round(0.8 + k * 0.4, 3), "w": "word"} for k in range(4500)]
    one = [{"start": 0.5, "end": endless[-1]["end"], "text": " ".join("word" for _ in endless)}]
    for ws, ss, mode in ((words, sents, "whole"), (words, sents, "parts"), (endless, one, "whole")):
        began = time.monotonic()
        parts = sp.split(ss, ws, 0.0, ws[-1]["end"] + 1.0, mode)
        assert time.monotonic() - began < 10.0  # an O(n * m^2) programme took minutes here
        assert max(p["end"] - p["start"] for p in parts) <= sp.MAX_CLIP_S
        assert not [w for p in parts[1:] for w in ws if w["start"] < p["start"] < w["end"]]


def test_one_endless_sentence_is_cut_at_the_longest_pause_between_words():
    from clipfoundry.pipeline import story_parts as sp

    words, t = [], 0.0
    for k in range(1000):  # 400 s of words with no sentence end, and one 1.5 s pause near the middle
        t += 1.5 if k == 520 else 0.05
        words.append({"start": round(t, 3), "end": round(t + 0.35, 3), "w": "word"})
        t += 0.35
    sents = [{"start": words[0]["start"], "end": words[-1]["end"], "text": " ".join(w["w"] for w in words)}]
    parts = sp.split(sents, words, 0.0, words[-1]["end"] + 0.5, "whole")
    assert len(parts) == 2 and all(p["end"] - p["start"] <= sp.MAX_CLIP_S for p in parts)
    assert words[519]["end"] < parts[0]["end"] < words[520]["start"]  # in the pause, not in a word
    assert "between two words" in parts[1]["why"][0]


def test_a_gamer_who_stops_talking_every_few_seconds_is_not_cut_at_every_pause():
    from clipfoundry.pipeline import story_parts as sp

    body = _body("roommate", 52, 8)
    rng = random.Random(2)
    pauses = {s: round(rng.uniform(1.5, 4.0), 2) for s in body}  # the narrator plays between sentences
    pauses[body[30]] = 9.0  # one real break: nine seconds of only gameplay
    sents, words, start, end = _story(body, pauses=pauses)
    rh = sp.rhythm(sents)
    assert rh["median"] > 1.5
    assert sp.pause_weight(3.5, rh) < 1.0 and sp.pause_weight(9.0, rh) == 1.0
    assert sp.pause_weight(2.0, rh) == 0.0  # a usual pause for this narrator is no break at all
    cands = sp.candidates(sents, start, end, rh)
    brk = next(c for c in cands if c["next_text"] == body[31])
    assert brk["quality"] == max(c["quality"] for c in cands) and "a 9.0 s pause" in brk["why"]
    assert sum(1 for c in cands if any("pause" in w for w in c["why"])) <= 3
    parts = sp.split(sents, words, start, end, "parts", rh=rh)
    assert len(parts) == sp.part_count(end - start, "parts")  # the length decides how many, never the pauses


def test_a_cut_before_and_or_because_or_after_an_unfinished_sentence_is_avoided():
    from clipfoundry.pipeline import story_parts as sp

    rh = {"median": 0.45, "p90": 0.45, "p97": 0.45}
    sents = [{"start": 0.0, "end": 20.0, "text": "We drove to the venue."},
             {"start": 20.5, "end": 40.0, "text": "And the caterer was gone."},
             {"start": 40.5, "end": 60.0, "text": "My sister cried."},
             {"start": 60.5, "end": 80.0, "text": "The photographer left"},
             {"start": 80.5, "end": 100.0, "text": "We went home."}]
    q = {c["after"]: c["quality"] for c in sp.candidates(sents, 0.0, 100.0, rh)}
    # before "And" and after "left" (unfinished) cost; after "cried." does not
    assert q[0] < 0 and q[3] < 0 and q[2] >= 0


def test_clipforge_ai_may_choose_among_the_best_places_but_never_breaks_a_rule():
    from clipfoundry.pipeline import story_parts as sp

    sents, words, start, end = _seven_minutes()
    plain = sp.split(sents, words, start, end, "whole")
    offered = []

    def pick_second(k, n, options):
        offered.append(options)
        return 1

    picked = sp.split(sents, words, start, end, "whole", chooser=pick_second)
    assert offered and 2 <= len(offered[0]) <= sp.CHOICES
    assert all(p["end"] - p["start"] <= sp.MAX_CLIP_S for p in picked)
    if picked[1]["start"] != plain[1]["start"]:
        assert "ClipForge AI picked this place" in picked[1]["why"]

    def too_early(k, n, options):  # a pick that would leave a part over five minutes is refused
        return 0 if options[0]["time"] - start < 60 else None

    assert sp.split(sents, words, start, end, "whole", chooser=too_early) == plain

    def broken(k, n, options):
        raise RuntimeError("model down")

    assert sp.split(sents, words, start, end, "whole", chooser=broken) == plain


@pytest.mark.parametrize("duration", [301.0, 450.0, 899.0])
def test_the_parts_cover_the_whole_story_exactly(duration):
    from clipfoundry.pipeline import story_parts as sp

    n = int(duration / 6)
    sents = [{"start": k * 6.0, "end": k * 6.0 + 5.5, "text": f"Sentence number {k} is here."} for k in range(n)]
    words = [{"start": s["start"], "end": s["end"], "w": "word"} for s in sents]
    for mode in ("whole", "parts"):
        parts = sp.split(sents, words, 0.0, duration, mode)
        assert parts[0]["start"] == 0.0 and parts[-1]["end"] == duration
        assert all(a["end"] == b["start"] and a["end"] > a["start"] for a, b in zip(parts, parts[1:]))
        assert max(p["end"] - p["start"] for p in parts) <= sp.MAX_CLIP_S
