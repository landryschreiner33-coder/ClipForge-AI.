"""Clip selection rules found by the clip quality benchmark (scripts/clip_quality_benchmark.py): ad reads, talking to
chat, goodbyes, a "he" the clip never introduces, a clip that cuts off its own introduction, "where was I", lines
that repeat one point, and titles that only make sense next to the clip."""
from __future__ import annotations

from clipfoundry import config
from clipfoundry.pipeline import candidates, postpack, trims, virality
from clipfoundry.pipeline.text_utils import AD_PHRASES, CHAT_CHORES, ONE_THING, count_words, repeat_run
from test_trims import words_of
from test_virality import _analyze, _setup

STORY = ["Welcome back to the show, everybody.", "We have a lot to get through today.",
         "My grandfather ran a bakery for forty years and he never once took a day off.",
         "People in town thought he was crazy.", "One winter night the oven caught fire at three in the morning.",
         "Do you know what he did?", "He kept baking in the neighbor's kitchen.",
         "By six o'clock every single order was on the counter.",
         "And that loaf is still framed on the wall of the bakery today."]


def flags(r: dict) -> dict:
    return {f["id"]: f for f in r["flags"]}


def test_whole_word_phrases():
    assert count_words("use code show for twenty percent off your first bag.", AD_PHRASES) == 2
    assert count_words("because code is fun", AD_PHRASES) == 0
    assert count_words("thanks for the subway ride", CHAT_CHORES) == 0
    assert count_words("thank you for the five gifted subs!", CHAT_CHORES) == 1
    assert ONE_THING.search("your exports are slow because of one checkbox.")
    assert not ONE_THING.search("one of my friends came over")


def test_an_ad_read_is_never_a_clip():
    lines = ["Here is why my bread always rises.", "This episode is brought to you by Northwind Coffee.",
             "Use code SHOW for twenty percent off your first bag.", "Go to the link in the description.",
             "Thanks to Northwind for supporting the show.", "Anyway, the bread rises because the dough is warm."]
    r = virality.finalize(_analyze(lines, "Here is why", "Anyway"))
    assert flags(r)["ad_read"]["severity"] == "block" and r["blocked"]
    one = virality.finalize(_analyze(lines[:1] + ["Use code SHOW at checkout, by the way."] + STORY[4:],
                                     "Here is why", "And that loaf"))
    assert flags(one)["ad_read"]["severity"] == "warn"


def test_talking_to_chat_and_goodbyes():
    lines = ["I have forty health and only a pistol.", "He peeks, and he misses.", "Headshot, we won the round.",
             "That is the cleanest clutch I have ever hit.", "Okay, let me read chat.", "Thanks for the follow.",
             "Thank you for the five gifted subs.", "Okay, that is the stream for today.", "Bye chat."]
    r = virality.finalize(_analyze(lines, "I have forty", "Thank you for the five"))
    f = flags(r)
    assert f["chat_chores"]["severity"] == "block" and "3 lines" in f["chat_chores"]["detail"]
    assert f["topic_change"]  # "let me read chat" moves on from the clutch
    r = virality.finalize(_analyze(lines, "I have forty", "Bye chat"))
    assert flags(r)["outro"]["severity"] == "block"   # two goodbye lines at the end
    reasons = virality.reasons(virality.summary(r))
    assert any(x["area"] == "Context" and "Talks to chat" in x["text"] for x in reasons)
    # the editor offers to end on the point
    ws = words_of(" ".join(lines[:4] + lines[5:7]))
    s = trims.suggest(ws, 0.0, ws[-1]["end"] + 0.2)
    cut = next(x for x in s["suggestions"] if x["id"] == "outro")
    point = next(w["end"] for w in ws if w["w"] == "hit.")
    assert point < cut["edit"]["end"] <= point + 0.4 and "Thanks for the follow" in cut["why"]


def test_a_he_nobody_introduced_and_a_cut_off_introduction():
    assert candidates.unnamed_person("People in town thought he was crazy.") == "he"
    assert candidates.unnamed_person("My grandfather said he was tired.") == ""
    assert candidates.unnamed_person("The third one is behind the box, I know he is.") == ""
    assert candidates.unnamed_person("Mark said he would come.", {"mark"}) == ""
    assert candidates.names_someone("Then Sarah told me.") and not candidates.names_someone("Rent is due.")
    # starts one line after the grandfather is named: blocked, the clip cut off its own introduction
    r = virality.finalize(_analyze(STORY, "People in town", "And that loaf"))
    f = flags(r)["weak_context"]
    assert f["severity"] == "block" and "“he”" in f["detail"] and "just before" in f["detail"]
    # a later "he" before anyone is named counts too ("Do you know what he did?")
    r = virality.finalize(_analyze(STORY, "One winter night", "And that loaf"))
    assert flags(r)["weak_context"]["severity"] == "block"
    # starting where he is introduced: no context problem
    r = virality.finalize(_analyze(STORY, "My grandfather", "And that loaf"))
    assert "weak_context" not in flags(r)


def test_a_tease_at_the_end_and_a_he_a_team_role_introduced():
    lines = ["First map they beat us thirteen to two.", "But then our captain calls a timeout and says one thing.",
             "He says Marcus always pushes left when he is ahead.", "So we put three people on the left side.",
             "We win that map thirteen to four."]
    assert virality.finalize(_analyze(lines, "First map", "We win"))["flags"] == []  # "our captain" is the "he"
    # ending on "says one thing" when the one thing comes right after the cut
    r = virality.finalize(_analyze(lines, "First map", "But then"))
    assert flags(r)["misleading_cut"]["severity"] == "block"


def test_no_way_is_a_reaction_not_a_reply():
    lines = ["I have forty health and only a pistol.", "The third one peeks, and he misses.", "Headshot.", "No way.",
             "No way!", "We won the round with forty health.", "That is the cleanest clutch I have ever hit."]
    r = virality.finalize(_analyze(lines, "I have forty", "That is the cleanest"))
    assert "weak_ending" not in flags(r)
    _, _, _, feats = _setup(["Do you think it works?", "No, it never did."])
    assert feats[1]["response"]                    # a real answer to someone still counts


def test_a_clause_waiting_for_its_other_half_is_not_a_title():
    assert not postpack.stands_alone("Even if you recorded in ten eighty")
    assert not postpack.stands_alone("Just because it is free")
    assert postpack.stands_alone("Even pros miss this setting") and postpack.stands_alone("Just export in 4K")


def test_a_number_is_not_a_searchable_topic():
    assert "eighty" not in postpack.topics("If you upload in ten eighty, YouTube compresses ten eighty twice. "
                                           "Even if you recorded in ten eighty, upload it in four K.")


def test_a_he_with_nobody_named_nearby_is_a_warning():
    lines = ["Let me tell you about the worst landlord ever.", "Rent is due on the first.", "Anyway.",
             "People said he was the worst landlord in the city.", "He once charged us for the rain.",
             "He said the water came through our window, so it was our water.",
             "We paid it, because what else could we do."]
    r = virality.finalize(_analyze(lines, "People said", "We paid it"))
    assert flags(r)["weak_context"]["severity"] == "warn"


def test_lines_that_repeat_one_point():
    tail = ["The thing is, consistency really matters.", "Consistency is the most important thing.",
            "If you are not consistent, nothing works.", "You have to be consistent every single day."]
    assert repeat_run(["So stop throwing away your starter."] + tail) == 4
    assert repeat_run(["The dog ran to the park.", "The dog barked at a squirrel.", "My dog chased it up a tree."]) == 0
    lines = ["Here is something most people get wrong about sourdough.", "You can keep a starter in the fridge.",
             "Feed it twice when you take it out.", "So stop throwing away your starter."] + tail
    r = virality.finalize(_analyze(lines, "Here is something", "You have to be"))
    assert "saying the same thing 4 times" in flags(r)["weak_ending"]["detail"]
    ws = words_of(" ".join(lines))
    s = trims.suggest(ws, 0.0, ws[-1]["end"] + 0.2)
    cut = next(x for x in s["suggestions"] if x["id"] == "repeats")
    assert "starter" in cut["why"] and cut["seconds"] > 3


def test_one_thing_opens_a_loop():
    words, sentences, loud, feats = _setup(["Your exports are slow because of one checkbox.",
                                            "Your exports are slow because of the settings."])
    assert feats[0]["hookw"] > feats[1]["hookw"]


def test_titles_stand_alone():
    assert not postpack.stands_alone("That's the setting")
    assert not postpack.stands_alone("If you upload in ten eighty")
    assert postpack.stands_alone("Do you know what he did?")
    pkg = postpack.extract(["Your exports are slow because of one checkbox.", "Turn on hardware encoding.",
                            "It went from twenty two minutes to four.", "So that's the setting."], "", [],
                           "education")
    assert "So that's the setting" not in pkg["titles"] and "That's the setting" not in pkg["titles"]


def test_the_benchmark_scripts_are_there():
    from pathlib import Path

    folder = Path(__file__).resolve().parents[1] / "scripts" / "clip_benchmark"
    assert {p.stem for p in folder.glob("*.txt")} == {"podcast_story", "gaming_stream", "tutorial"}
    assert dict(config.DEFAULT_SETTINGS)["silence"] == "light"


def _stream(lines: list[str], loud_after: str | None = None, delay: float = 1.0, length: float = 1.5):
    """A stream transcript with 3 s pauses between lines and, optionally, a loud stretch without words (a shout, the
    crowd) `delay` seconds after the line that starts with `loud_after`."""
    from test_core import _srt
    from test_virality import _find
    from clipfoundry.pipeline import transcribe
    from clipfoundry.pipeline.audio import Loudness
    from clipfoundry.pipeline.text_utils import build_sentences

    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(lines, gap=3.0))})
    sentences = build_sentences(words)
    db = [-20.0] * int(words[-1]["end"] * 10 + 60)
    if loud_after:
        t = sentences[_find(sentences, loud_after)]["end"] + delay
        db[int(t * 10):int((t + length) * 10)] = [-6.0] * (int((t + length) * 10) - int(t * 10))
    return words, sentences, Loudness({"hop": 0.1, "db": db}), candidates.sentence_features(sentences, words)


CLUTCH = ["I have forty health and only a pistol.", "He peeks, and he misses.", "Headshot, we won the round.",
          "Okay, that was close.", "Anyway, the next round is on the other site."]


def test_a_late_reaction_stays_in_the_clip():
    from test_virality import _find
    from clipfoundry.pipeline import deep

    opts = dict(config.DEFAULT_SETTINGS)
    for loud_after, kept in (("Headshot", True), (None, False)):
        words, sentences, loud, feats = _stream(CLUTCH, loud_after, delay=1.2, length=1.5)
        i, j = _find(sentences, "I have forty"), _find(sentences, "Headshot")
        last = sentences[j]["end"]
        b = deep.optimize_bounds({"s0": i, "s1": j}, sentences, loud, sentences[-1]["end"] + 1)
        start, end = candidates.refine_bounds({"s0": i, "s1": j}, sentences, sentences[-1]["end"] + 1, loud)
        r = virality.finalize(virality.analyze(i, j, sentences, feats, words, loud, opts))
        reasons = virality.reasons(virality.summary(r))
        if kept:
            # the shout starts 1.2 s after "round." and lasts 1.5 s: both cuts end after it, before the next words
            # (loudness comes in 0.1 s steps, so the times are within a step)
            assert last + 2.6 <= b["end"] <= last + 3.1 and "keeps the reaction 1.1 s" in b["notes"][0]
            assert last + 2.6 <= end < sentences[j + 1]["start"]
            assert r["signals"]["reaction_after"]
            assert any(x["area"] == "Payoff" and "reaction" in x["text"] for x in reasons)
        else:
            assert b["end"] <= last + 0.6 and end <= last + 0.5
            assert not any("reaction" in x["text"] for x in reasons)
    # a long stretch of loud sound (music) is not kept whole
    words, sentences, loud, _ = _stream(CLUTCH, "Headshot", delay=0.5, length=2.8)
    j = _find(sentences, "Headshot")
    got = virality.reaction_after(sentences, j, loud)
    assert got and got[1] - got[0] <= virality.REACTION_KEEP


def test_a_clip_that_opens_right_after_a_reaction_starts_too_late():
    from test_virality import _find

    opts = dict(config.DEFAULT_SETTINGS)
    words, sentences, loud, feats = _stream(CLUTCH, "He peeks", delay=1.4, length=1.4)
    # the shout ends 0.2 s before "Headshot": a clip starting there missed what caused it
    r = virality.finalize(virality.analyze(_find(sentences, "Headshot"), _find(sentences, "Okay, that"), sentences,
                                           feats, words, loud, opts))
    assert flags(r)["starts_on_reaction"]["severity"] == "warn"
    assert any(x["area"] == "Context" and "reaction" in x["text"] for x in virality.reasons(virality.summary(r)))
    r2 = virality.finalize(virality.analyze(_find(sentences, "I have forty"), _find(sentences, "Okay, that"),
                                            sentences, feats, words, loud, opts))
    assert "starts_on_reaction" not in flags(r2)


def test_remove_pauses_keeps_a_reaction_without_words():
    from clipfoundry.pipeline import render

    ws = words_of("We won the round with forty health and a pistol.")
    last = ws[-1]["end"]
    ws += [{"w": "Okay.", "start": last + 4.0, "end": last + 4.4, "p": 0.9}]
    shout = (last + 0.9, last + 2.7)
    cut = render.keep_segments(ws, 0.0, last + 4.6, "light", 30.0)
    kept = render.keep_segments(ws, 0.0, last + 4.6, "light", 30.0, loud=[shout])
    heard = lambda segs: sum(max(0.0, min(b, shout[1]) - max(a, shout[0])) for a, b in segs)  # noqa: E731
    assert heard(cut) < 0.5 and heard(kept) >= shout[1] - shout[0] - 0.05
    # the dead air suggestion counts only the real silence
    plain = trims.suggest(ws, 0.0, last + 4.6, silence="off")
    aware = trims.suggest(ws, 0.0, last + 4.6, silence="off", loud=[shout])
    secs = {name: next((x["seconds"] for x in t["suggestions"] if x["id"] == "dead_air"), 0.0)
            for name, t in (("plain", plain), ("aware", aware))}
    assert secs["aware"] < secs["plain"] - 1.5


def test_reactions_are_read_from_the_loudness_measured_at_analysis(tmp_path):
    import json

    from clipfoundry.pipeline import render

    db = [-20.0] * 100
    db[40:60] = [-6.0] * 20                                  # 4.0 to 6.0 s: loud, and nobody speaks
    (tmp_path / "loudness.json").write_text(json.dumps({"hop": 0.1, "db": db}))
    words = [{"w": "Go.", "start": 1.0, "end": 1.4}, {"w": "Yes!", "start": 7.0, "end": 7.4}]
    assert render.heard(tmp_path, words, 0.0, 10.0) == [(4.0, 6.0)]
    assert render.heard(tmp_path / "none", words, 0.0, 10.0) == []
