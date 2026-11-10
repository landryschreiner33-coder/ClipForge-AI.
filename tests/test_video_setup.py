"""Make a YouTube video's new setup (docs/clipforge/VIDEO_SETUP.md): the plan, the built-in rules that read the
owner's words, the questions, the checked model answer and how a new plan is merged. Pure functions only; the
draft, the chat and the build are in test_video_setup_flow.py."""
from __future__ import annotations

import pytest

from clipfoundry.studio import video_setup as vs

FILES = [  # the media bin as the planner sees it, in order
    {"id": "v1", "kind": "video", "filename": "dock_jump.mp4", "duration": 190.0},
    {"id": "v2", "kind": "video", "filename": "drive.mp4", "duration": 760.0},
    {"id": "i1", "kind": "image", "filename": "sunset.jpg", "duration": 0.0},
    {"id": "a1", "kind": "audio", "filename": "summer song.mp3", "duration": 210.0},
    {"id": "a2", "kind": "audio", "filename": "narration.m4a", "duration": 95.0},
]


def read(text: str) -> dict:
    return vs.rules_read(text, FILES)[0]


# ------------------------------------------------------------------ the built-in rules
def test_lengths_are_read_from_plain_words():
    assert read("make it about 10 minutes")["length_min"] == 10
    assert read("8-10 minutes long")["length_min"] == 9
    assert read("under 5 minutes please")["length_min"] == 4.5
    assert read("half an hour")["length_min"] == 30
    assert read("an hour and a half")["length_min"] == 90
    assert read("90 seconds")["length_min"] == 1.5
    assert read("a two minute video")["length_min"] == 2
    assert read("1.5 hours")["length_min"] == 90
    assert "length_min" not in read("the jump happens 3 minutes in")
    assert "length_min" not in read("at 2 minutes he falls in")
    plan, said = vs.rules_read("As long as it needs", FILES)
    assert plan["length_min"] == vs.NO_LENGTH and "length_min" in said


def test_shape_feel_and_how_much_to_edit():
    assert read("a vertical video for TikTok")["aspect_ratio"] == "9:16"
    assert read("for YouTube Shorts")["aspect_ratio"] == "9:16"
    assert read("square please")["aspect_ratio"] == "1:1"
    assert read("widescreen 16:9")["aspect_ratio"] == "16:9"
    assert read("4:5 for instagram")["aspect_ratio"] == "4:5"
    assert "aspect_ratio" not in read("a normal youtube video")
    assert read("calm and cinematic")["feel"] == "calm"
    assert read("fun and high energy")["feel"] == "energetic"
    assert read("chill at first but mostly hype")["feel"] == "energetic"  # the last one said wins
    assert read("Balanced")["feel"] == "balanced"
    assert read("fast-paced with jump cuts")["edit"] == "tight"
    assert read("don't cut anything, keep my clips as they are")["edit"] == "off"
    assert read("just edit it for me")["edit"] == "smart"
    assert "edit" not in read("don't cut the jump")


def test_music_files_captions_and_switches():
    assert read("no music")["music"] == "none"
    p = read("use my song as the music")
    assert p["music"] == "mine" and p["music_file"] == "a1"
    p = read("put summer song under it")
    assert p["music"] == "mine" and p["music_file"] == "a1"
    assert read("free music made by clipforge")["music"] == "library"
    assert read("find music for me")["music"] == "find"
    assert read("narration.m4a is the voiceover")["voiceover_files"] == ["a2"]
    p = read("put summer song under it, narration.m4a is the voiceover")  # one clause each
    assert p["music_file"] == "a1" and p["voiceover_files"] == ["a2"]
    assert "music_file" not in read("don't put summer song under it")
    assert read("no captions")["captions"] == "off"
    assert read("add subtitles")["captions"] == "on"
    p = read("no sound effects and no zooms")
    assert p["sound_effects"] == "off" and p["zooms"] == "off"
    assert read("show my photos over the talking")["pictures"] == "on"
    assert read("no pictures")["pictures"] == "off"
    assert read("zoom in on the funny bits")["zooms"] == "on"


def test_opening_story_keep_and_cut():
    p = read("Start with the dock jump, then the drive up, then swimming, and finally dinner. "
             "Cut the boring traffic part and skip the gas station. Keep the sunset.")
    assert p["opening"] == "the dock jump" and p["cold_open"] == "on"
    assert p["story"] == ["the dock jump", "the drive up", "swimming", "dinner"]
    assert p["cut"] == ["boring traffic part", "gas station"]
    assert p["keep"] == ["sunset"]
    p = read("start from the beginning")
    assert p["cold_open"] == "off" and p.get("opening", "") == ""
    p = read("open with the best moment")
    assert p["cold_open"] == "on" and "opening" not in p
    assert read("don't cut the part where we fall")["keep"] == ["part where we fall"]
    assert "keep" not in read("keep it short and fun")
    assert "cut" not in read("cut it down to 5 minutes")
    # a part of the story ends where another instruction starts; a story's own "and …" stays
    assert read("Start with the jump, then the drive up, and use my song as the music.")["story"] == \
        ["the jump", "the drive up"]
    assert read("first the drive, then swimming, then make it 8 minutes")["story"] == ["the drive", "swimming"]
    assert read("first we drive up and play in the water, then we make a fire, finally the sunset")["story"] == \
        ["we drive up and play in the water", "we make a fire", "the sunset"]


def test_audience_type_and_title():
    p = read("A fun travel vlog of our lake trip for friends and family. Call it Lake Days.")
    assert p["video_type"] == "Travel vlog"
    assert p["audience"] == "Friends and family"
    assert p["title"] == "Lake Days"
    assert read("a tutorial for beginners")["video_type"] == "Tutorial"
    assert read("a tutorial for beginners")["audience"] == "Beginners"
    assert read("a podcast episode")["video_type"] == "Podcast"
    assert "audience" not in read("for 10 minutes")


def test_keep_and_cut_read_negatives_and_only_requests():
    # a "don't" / "never" / "can't" in front of a cut verb keeps the part; a negated keep cuts it
    for text in ("Please don't ever cut the sunset.", "never cut the sunset", "we can't lose the sunset",
                 "I do not want you to remove the sunset", "make sure you don't cut the sunset"):
        p = read(text)
        assert p.get("keep") == ["sunset"] and "cut" not in p, text
    for text in ("don't include the gas station", "please don't keep the gas station"):
        p = read(text)
        assert p.get("cut") == ["gas station"] and "keep" not in p, text
    # "you don't have to keep it" lets it go without cutting it
    p = read("you don't have to keep the sunset")
    assert "keep" not in p and "cut" not in p
    # what happens in the story is not an instruction
    for text in ("my dad tries to remove the fish hook", "then we cut the cake", "he drops the phone in the lake",
                 "she skips the line"):
        p = read(text)
        assert "keep" not in p and "cut" not in p, text
    # requests in other words still count
    assert read("can you cut the gas station")["cut"] == ["gas station"]
    assert read("I want you to keep the dock jump")["keep"] == ["dock jump"]
    assert read("we need to cut the traffic part")["cut"] == ["traffic part"]


def test_the_length_is_the_one_asked_for():
    for text, minutes in (("My footage is 2 hours long, I want a 15 minute video", 15),
                          ("The interview is 45 minutes, make it 10", 10),
                          ("Turn my 30 minute talk into a 5 minute video", 5),
                          ("not 12 minutes, 8 minutes", 8),
                          ("make it 10 minutes. actually make it 8 minutes", 8),
                          ("10 minutes, vertical, no music, upbeat, for my friends and family", 10),
                          ("It should be 10 minutes and the drive took 2 hours", 10)):
        assert read(text).get("length_min") == minutes, text
    for text in ("We drove 6 hours", "I have 20 minutes of footage", "hold on a sec", "wait a minute",
                 "my footage is about 40 minutes", "the drive was 2 hours and the lake was cold",
                 "each picture for 3 seconds each"):
        assert "length_min" not in read(text), text


def test_as_long_as_it_needs_is_a_decision():
    assert read("As long as it needs")["length_min"] == vs.NO_LENGTH
    p = vs.clean_plan({"length_min": vs.NO_LENGTH}, FILES)
    assert p["length_min"] == vs.NO_LENGTH
    assert "Length: as long as it needs" in vs.plan_lines(p, FILES)
    assert vs.plan_to_brief(p)["target_duration_s"] == 0  # no fit, and your style's length does not apply
    assert vs.rules_questions(p, set(), set()) == [q for q in vs.rules_questions(p, set(), set())
                                                   if q["id"] != "length"]
    assert "target_duration_s" not in vs.plan_to_brief(vs.clean_plan({}, FILES))  # undecided: your style decides


def test_editing_off_needs_the_whole_video():
    for text in ("Keep everything light and fun", "keep it all upbeat", "leave the drive as is",
                 "the drive, don't cut it too short", "don't edit it too much", "the uncut part of the drive"):
        assert read(text).get("edit") != "off", text
    for text in ("keep everything", "keep my clips as they are", "don't edit anything", "leave it as is",
                 "don't cut anything, keep my clips as they are", "post it unedited"):
        assert read(text).get("edit") == "off", text


def test_switches_music_and_shape_hear_no():
    for text in ("I don't want captions", "skip the captions", "turn off captions", "no need for captions",
                 "no captions please"):
        assert read(text).get("captions") == "off", text
    assert read("no zooms and add captions")["captions"] == "on"
    assert read("I don't want zooms")["zooms"] == "off"
    assert read("please avoid sound effects")["sound_effects"] == "off"
    assert "zooms" not in read("we had a zoom call")
    for text in ("without background music", "I don't want background music", "no music", "I don't want any music",
                 "lose the background music"):
        assert read(text).get("music") == "none", text
    assert "cut" not in read("lose the background music")
    assert read("add some background music")["music"] == "auto"
    # a no that is no no, and a "not sure" that says neither
    for text in ("Don't forget the captions", "I don't mind captions", "I don't want music but don't forget subtitles"):
        assert read(text).get("captions") == "on", text
    assert read("no worries, add some background music")["music"] == "auto"
    assert read("Don't forget to add music")["music"] == "auto"
    assert read("not too many zooms")["zooms"] == "on"
    for text in ("not sure about captions", "I don't care about captions"):
        assert "captions" not in read(text), text
    assert read("don't forget to keep the sunset")["keep"] == ["sunset"]
    for text in ("not a TikTok", "I don't want it vertical", "the old town square", "my new fishing reels",
                 "The landscape up there was unreal", "we wore shorts all day"):
        assert "aspect_ratio" not in read(text), text
    for text, shape in (("make it square", "1:1"), ("square please", "1:1"), ("in landscape", "16:9"),
                        ("a vertical video", "9:16"), ("for instagram reels", "9:16"), ("make it vertical", "9:16")):
        assert read(text).get("aspect_ratio") == shape, text


def test_story_title_and_opening_edge_cases():
    assert "story" not in read("Make the first part shorter, then speed up the end")
    assert "story" not in read("I want it shorter, then I'll upload it")
    assert read("first the drive, then swimming, then dinner")["story"] == ["the drive", "swimming", "dinner"]
    assert "title" not in read("after the sunset we call it a day")
    assert "title" not in read("let's call it a night")
    assert read("call it lake days")["title"] == "lake days"
    p = read("Actually, start from the beginning instead")
    assert p["cold_open"] == "off" and p["opening"] == ""
    assert "cold_open" not in read("I want to cut the boring parts in order to make it shorter")
    # an opening only stays while the video opens with it
    p = vs.clean_plan({"opening": "the dock jump", "cold_open": "off"}, FILES)
    assert p["opening"] == "" and p["cold_open"] == "off"


def test_mentions_say_which_parts_of_the_plan_a_message_touches():
    assert vs.mentions("make it a bit shorter") >= {"length_min"}
    assert "feel" in vs.mentions("more chill please")
    assert "music" in vs.mentions("change the song")
    assert {"keep", "cut"} <= vs.mentions("you don't have to keep the sunset")
    assert vs.mentions("thanks!") == set()


# ------------------------------------------------------------------ the questions
def test_rules_ask_only_for_what_is_missing_and_never_twice():
    assert [q["id"] for q in vs.rules_questions(vs.empty_plan(), set(), set())] == ["audience", "length", "feel"]
    plan = {**vs.empty_plan(), "audience": "Friends", "feel": "calm"}
    assert [q["id"] for q in vs.rules_questions(plan, set(), set())] == ["length"]
    assert vs.rules_questions(plan, set(), {"length_min"}) == []  # "as long as it needs" was said
    assert [q["id"] for q in vs.rules_questions(vs.empty_plan(), {"audience", "length"}, set())] == ["feel"]
    for q in vs.rules_questions(vs.empty_plan(), set(), set()):
        assert 2 <= len(q["choices"]) <= 4 and q["q"].endswith("?")


def test_quick_answers_fill_the_plan():
    assert vs.answer_fields("length", "About 10 minutes", FILES) == {"length_min": 10}
    assert vs.answer_fields("length", "As long as it needs", FILES) == {"length_min": vs.NO_LENGTH}
    assert vs.answer_fields("length", "Under 5 minutes", FILES) == {"length_min": 4.5}
    assert vs.answer_fields("audience", "My subscribers", FILES) == {"audience": "My subscribers"}
    assert vs.answer_fields("audience", "people who love fishing", FILES) == {"audience": "people who love fishing"}
    assert vs.answer_fields("feel", "Energetic", FILES) == {"feel": "energetic"}
    assert vs.answer_fields("feel", "whatever you think", FILES) == {}


def test_words_typed_under_who_is_it_for_count_only_when_they_name_people():
    # the only question on screen is "Who is it for?" and the owner types instead of tapping
    for typed, who in (("my gaming friends", "my gaming friends"), ("it's for my mom", "my mom"),
                       ("It’s for my Mom!", "my Mom"),
                       ("kids who want to learn guitar", "kids who want to learn guitar"),
                       ("travel lovers", "travel lovers")):
        assert vs.answer_fields("audience", typed, FILES) == {"audience": who}, typed
    # a message about another part of the video is not taken as who it is for
    for typed in ("the beach part is the best", "more drone shots", "the sunset at the end", "use the drone shots",
                  "make it 5 minutes and no music", "first the drive then the lake", "add captions", "no idea"):
        assert vs.answer_fields("audience", typed, FILES) == {}, typed


# ------------------------------------------------------------------ the plan, checked
def test_clean_plan_keeps_only_checked_values():
    raw = {"title": "  Lake   days ", "summary": "x" * 500, "length_min": "12", "aspect_ratio": "21:9",
           "feel": "CALM", "edit": "nonsense", "story": ["a", "", 5, "b" * 300] + ["c"] * 10, "keep": "sunset",
           "cut": [None, "drive", "Drive"], "music": "mine", "music_file": 4, "voiceover_files": [5, 9, 1],
           "captions": True, "pictures": "off", "order": [2, 1], "evil": "x", "zooms": "maybe",
           "find_media": "auto"}
    p = vs.clean_plan(raw, FILES)
    assert p["title"] == "Lake days" and len(p["summary"]) == 300
    assert p["length_min"] == 12 and p["aspect_ratio"] == "" and p["feel"] == "calm" and p["edit"] == "smart"
    assert p["story"][:2] == ["a", "b" * 160] and len(p["story"]) == 8
    assert p["keep"] == ["sunset"] and p["cut"] == ["drive"]  # one string is one item; twins are one
    assert p["music"] == "mine" and p["music_file"] == "a1"  # file 4 is the song
    assert p["voiceover_files"] == ["a2"]  # 9 does not exist, 1 is a video
    assert p["captions"] == "on" and p["pictures"] == "off" and p["zooms"] == ""
    assert p["order"] == ["v2", "v1", "i1"]  # the rest follows in its current order
    assert p["find_media"] == "auto" and "evil" not in p
    assert set(p) == set(vs.empty_plan())
    # ids work as well as numbers; out-of-range lengths are bounded; "mine" without a file picks your longest sound
    p = vs.clean_plan({"music": "mine", "order": ["i1", "a1", "v1"], "length_min": 999, "voiceover_files": ["a2"]},
                      FILES)
    assert p["music_file"] == "a1" and p["order"] == ["i1", "v1", "v2"] and p["length_min"] == 240
    assert p["voiceover_files"] == ["a2"]
    assert vs.clean_plan({"length_min": -3}, FILES)["length_min"] == 0
    assert vs.clean_plan({"music": "mine"}, FILES[:3])["music"] == ""  # no sound to use: from your style


def test_plan_to_brief_maps_every_field():
    p = vs.clean_plan({"video_type": "Travel vlog", "audience": "Family", "goal": "Share the trip", "length_min": 10,
                       "aspect_ratio": "9:16", "feel": "energetic", "edit": "tight", "opening": "the dock jump",
                       "story": ["jump", "drive"], "keep": ["sunset", "dinner"], "cut": ["traffic"],
                       "music": "mine", "music_file": 4, "voiceover_files": [5], "captions": "off",
                       "pictures": "on", "sound_effects": "off", "zooms": "on", "cold_open": "on",
                       "summary": "Our lake trip", "notes": ["no swearing"], "find_media": "suggest"}, FILES)
    assert vs.plan_to_brief(p) == {
        "video_type": "Travel vlog", "audience": "Family", "goal": "Share the trip", "target_duration_s": 600.0,
        "aspect_ratio": "9:16", "feel": "energetic", "smart_edit": "tight", "ai_edit": True,
        "open_with": "the dock jump", "must_keep": "sunset, dinner", "avoid": "traffic", "music": "supplied",
        "music_asset_id": "a1", "voiceover_asset_ids": ["a2"], "captions": False, "broll_images": True,
        "sound_effects": False, "punch_in": True, "cold_open": True, "find_media": "suggest",
        "plan": {"summary": "Our lake trip", "opening": "the dock jump", "story": ["jump", "drive"],
                 "notes": ["no swearing"]}}
    # an empty plan leaves everything to your style and Brain, with "Edit it for me" like the old page
    assert vs.plan_to_brief(vs.clean_plan({}, FILES)) == {"smart_edit": "smart", "ai_edit": True}
    assert vs.plan_to_brief(vs.clean_plan({"music": "find"}, FILES))["find_media"] == "suggest"
    from clipfoundry.studio import video_flow
    assert set(vs.plan_to_brief(p)) <= video_flow.BRIEF_FIELDS


def test_plan_lines_read_like_a_person_wrote_them():
    p = vs.clean_plan({"summary": "Our lake trip", "audience": "Family", "length_min": 10, "feel": "calm",
                       "opening": "the dock jump", "story": ["jump", "drive"], "cut": ["traffic"],
                       "music": "none", "captions": "on"}, FILES)
    lines = vs.plan_lines(p, FILES)
    assert "What it is: Our lake trip" in lines and "For: Family" in lines and "Length: about 10 minutes" in lines
    assert "Opens with: the dock jump" in lines and "Story: 1. jump 2. drive" in lines
    assert "Cut: traffic" in lines and "Music: none" in lines and "Captions: on" in lines
    assert vs.plan_lines(vs.clean_plan({}, FILES), FILES) == []


# ------------------------------------------------------------------ merging a new plan
def test_merge_the_model_reads_first_and_hand_edits_win():
    base = vs.clean_plan({"length_min": 10, "feel": "calm", "keep": ["sunset"], "cut": ["drive"]}, FILES)
    model = vs.clean_plan({"length_min": 8, "feel": "energetic", "keep": ["sunset"], "cut": ["drive"],
                           "audience": "Family"}, FILES)
    # the rules read "12 minutes" in the newest message, but the model changed the length: its reading wins; the
    # owner set the feel by hand earlier
    out = vs.merge(base, model, explicit={"length_min": 12}, mentioned={"length_min"}, locked={"feel": "calm"})
    assert out["length_min"] == 8 and out["feel"] == "calm" and out["audience"] == "Family"
    # where the model left a part as it was (or empty), what the rules read fills it in
    lazy = vs.clean_plan({**base, "audience": "Family"}, FILES)
    out = vs.merge(base, lazy, explicit={"length_min": 12, "aspect_ratio": "9:16"}, mentioned={"length_min"},
                   locked={})
    assert out["length_min"] == 12 and out["aspect_ratio"] == "9:16"
    # keep and cut: the rules' reading only when the model changed neither list
    out = vs.merge(base, lazy, explicit={"keep": ["drive"]}, mentioned={"keep", "cut"}, locked={})
    assert out["keep"] == ["sunset", "drive"] and out["cut"] == []
    moved = vs.clean_plan({**base, "keep": ["sunset", "dock jump"]}, FILES)
    out = vs.merge(base, moved, explicit={"cut": ["sunset"]}, mentioned={"keep", "cut"}, locked={})
    assert out["keep"] == ["sunset", "dock jump"] and out["cut"] == ["drive"]
    # a newer message about the feel lets the model change it
    out = vs.merge(base, model, explicit={}, mentioned={"feel"}, locked={"feel": "calm"})
    assert out["feel"] == "energetic" and out["length_min"] == 8
    # a model that silently empties what was set keeps the old value
    blank = vs.clean_plan({"length_min": 0, "feel": "", "keep": [], "cut": []}, FILES)
    out = vs.merge(base, blank, explicit={}, mentioned=set(), locked={})
    assert out["length_min"] == 10 and out["feel"] == "calm" and out["keep"] == ["sunset"] and out["cut"] == ["drive"]
    # "don't cut the drive" moves it from cut to keep, without a model
    out = vs.merge(base, None, explicit={"keep": ["drive"]}, mentioned={"keep", "cut"}, locked={})
    assert out["keep"] == ["sunset", "drive"] and out["cut"] == []
    # a story said in the newest message replaces the old one
    out = vs.merge({**base, "story": ["a", "b"]}, None, explicit={"story": ["c", "d"]}, mentioned={"story"}, locked={})
    assert out["story"] == ["c", "d"]


# ------------------------------------------------------------------ the model's answer
def test_parse_answer_reads_only_the_checked_shape():
    raw = ('<think>hmm</think> Sure! {"say": "Here is my plan.", "questions": [{"q": "Who is it for?", '
           '"choices": ["Family", "Friends", "x", "y", "z"]}, {"q": ""}, "junk"], "plan": {"length_min": 6, '
           '"order": [3, 1]}, "extra": 1}')
    a = vs.parse_answer(raw, FILES)
    assert a["say"] == "Here is my plan."
    assert [(q["q"], q["choices"]) for q in a["questions"]] == [("Who is it for?", ["Family", "Friends", "x", "y"])]
    assert a["questions"][0]["id"]
    assert a["plan"]["length_min"] == 6 and a["plan"]["order"] == ["i1", "v1", "v2"]
    a = vs.parse_answer('{"say": "Only words"}', FILES)
    assert a["say"] == "Only words" and a["plan"] is None and a["questions"] == []
    for bad in ("no json here", "[1, 2]", '{"say": 5, "plan": 3}', '{"say": "x" '):
        with pytest.raises(vs.SetupError):
            vs.parse_answer(bad, FILES)
    long = vs.parse_answer('{"say": "' + "y" * 2000 + '", "questions": [{"q": "' + "z" * 400 + '", "choices": []}]}',
                           FILES)
    assert len(long["say"]) == vs.SAY_CHARS and len(long["questions"][0]["q"]) == vs.QUESTION_CHARS


def test_the_answer_schema_lists_every_plan_field():
    schema = vs.answer_schema(FILES)
    plan = schema["properties"]["plan"]
    assert set(plan["required"]) == set(vs.MODEL_FIELDS) == set(plan["properties"])
    assert schema["properties"]["questions"]["maxItems"] == vs.MAX_QUESTIONS
