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
