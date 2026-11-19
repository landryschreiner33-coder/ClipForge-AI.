"""The owner's rules for titles, post text and hashtags (brain/poststyle.py) are read from the Brain and followed by
the post text writers, without ever adding a word that is not in the clip."""
from __future__ import annotations

import json

import pytest

from clipfoundry import db
from clipfoundry.brain import memories, poststyle
from clipfoundry.pipeline import llm, postpack
from test_core import SCRIPT

CLIP = SCRIPT[:7]
TEXT = " ".join(CLIP)


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path))
    db.init()


def _say(text: str, **kw) -> dict:
    return memories.remember("local", text, kind=kw.pop("kind", "rule"), source=kw.pop("source", "said"), **kw)


@pytest.mark.parametrize("said, choices", [
    ("titles in lower case, no emoji", {"title_case": "lower", "emoji": False}),
    ("Remember: no emoji, titles in lower case.", {"title_case": "lower", "emoji": False}),
    ("Titles in ALL CAPS.", {"title_case": "upper"}),
    ("No all caps titles.", {"title_case": "sentence"}),
    ("No capitals in titles.", {"title_case": "lower"}),
    ("For titles, use title case.", {"title_case": "title"}),
    ("Post text in lower case too.", {"text_case": "lower"}),
    ("No hashtags, emoji or links in my posts.", {"tags": 0, "emoji": False}),
    ("Never use hashtags", {"tags": 0}),
    ("Use at most 3 hashtags.", {"tags": 3}),
    ("No more than 4 hashtags", {"tags": 4}),
    ("Only use two hashtags", {"tags": 2}),
    ("Use 3 to 5 hashtags and keep titles short.", {"tags": 5, "title_max": poststyle.TITLE_SHORT}),
    ("Fewer hashtags.", {"tags": poststyle.FEWER_TAGS}),
    ("Titles under 45 characters.", {"title_max": 45}),
    ("Titles: no more than 6 words", {"title_words": 6}),
    ("Titles should be questions.", {"question": 1}),
    ("No question titles.", {"question": -1}),
    ("Don't ask people to follow me.", {"cta": False}),
    ("Stop asking viewers to subscribe", {"cta": False}),
    ("No call to action.", {"cta": False}),
    # not a rule this writer can keep, or not about the post text at all
    ("At least 5 hashtags please", {}),          # the clip may not talk about five things
    ("Captions in all caps.", {}),               # the words on the video have their own settings
    ("I love emoji in thumbnails", {}),
    ("Keep the description short.", {}),
    ("Pick funny moments, not small talk.", {}),
    ("Titles under 900 characters.", {}),        # a slip of the pen, not a wish
    # a "no" before a "no" asks for the thing; a rule about which hashtags is not one about how many
    ("Don't forget the hashtags.", {}),
    ("Don't forget to add a call to action.", {}),
    ("Never forget emojis in the post.", {}),
    ("No generic hashtags like #fyp or #viral.", {}),
    ("Don't put hashtags in the title.", {}),
    ("Don't use the same hashtags on every clip.", {}),
    # each part of a sentence is about what it names
    ("Thumbnail text in capitals, title in lower case.", {"title_case": "lower"}),
    ("Captions on screen in all caps, titles normal.", {}),
    ("Keep the description in lower case, titles normal.", {"text_case": "lower"}),
    ("Short clips, longer titles.", {}),
    ("Keep the on-screen captions under 6 words, titles can be long.", {}),
    ("In titles, use lower case", {"title_case": "lower"}),
    # what the owner allows is not banned by the list before it
    ("No emoji in titles, hashtags welcome.", {"emoji": False}),
    ("No call to action, hashtags are good.", {"cta": False}),
    ("No hashtags, emoji are fine.", {"tags": 0}),
    # "capitals" alone asks for all capitals only when refused
    ("Proper names in titles should keep their capitals.", {}),
    ("Titles can have capital letters again.", {}),
    ("Titles should use capital letters at the start of each word.", {"title_case": "title"}),
])
def test_what_the_owner_says_about_post_text_is_read_into_choices(said, choices):
    assert poststyle.read(said) == choices


def test_only_the_owners_own_words_count_and_the_closest_note_wins():
    project = db.create_project("stream")
    _say("Titles in all caps.")
    _say("For this video: titles in lower case.", scope=f"project:{project['id']}")
    _say("Use at most 4 hashtags.", kind="fact")
    memories.remember("local", "Great titles have no hashtags and are in lower case.", kind="fact", source="imported")
    memories.remember("local", "The owner seems to want no emoji in titles.", kind="fact", source="guessed")
    off = _say("No call to action.")
    memories.edit("local", off["id"], enabled=False)

    general = poststyle.build("local")
    assert general["title_case"] == "upper" and general["tags"] == 4
    assert "emoji" not in general and "cta" not in general           # a guess and a switched-off note change nothing
    assert general["lines"] == ["titles in capitals", "at most 4 hashtags"] and len(general["ids"]) == 2
    here = poststyle.build("local", project["id"])
    assert here["title_case"] == "lower" and here["tags"] == 4     # this video's note wins, the general one fills in
    assert poststyle.build("local", "another video")["title_case"] == "upper"
    assert poststyle.build("nobody") == {}


def test_the_text_is_dressed_without_a_new_word():
    style = {"title_case": "lower", "emoji": False, "tags": 2, "cta": False}
    assert poststyle.title(style, "He Forgot He Was LIVE 😂🔥 again ❤️!") == "he forgot he was live again!"
    assert poststyle.title({"title_case": "title"}, "he didn't even try") == "He Didn't Even Try"
    assert poststyle.title({"title_case": "sentence"}, "HE FORGOT HE WAS LIVE") == "He forgot he was live"
    assert poststyle.title({"title_case": "sentence"}, "He forgot he was LIVE") == "He forgot he was LIVE"
    assert poststyle.text(style, "Talk To Customers First 👍") == "Talk To Customers First"  # only titles change case
    assert poststyle.tags(style, ["#a", "#b", "#c"]) == ["#a", "#b"] and poststyle.tags({"tags": 0}, ["#a"]) == []
    assert poststyle.title({}, "As Written 😀") == "As Written 😀"
    # a joiner between letters stays (some languages write with it); a keycap and a flag go
    assert poststyle.title({"emoji": False}, "می‌خواهم 1️⃣ 🇺🇸 done") == "می‌خواهم done"

    titles = ["A very long title that goes on and on and never ends", "Short one here", "Why did he do it?"]
    assert poststyle.prefer({"title_max": 30}, titles, 0) == 1      # the writer's pick breaks the rule
    assert poststyle.prefer({"title_max": 30}, titles, 2) == 2      # ... and is kept when it fits as well
    assert poststyle.prefer({"question": 1}, titles, 0) == 2 and poststyle.prefer({"question": -1}, titles, 2) == 0
    assert poststyle.prefer({"title_max": 10}, titles, 0) == 1      # nothing fits: the nearest
    assert poststyle.prefer({}, titles, 2) == 2 and poststyle.prefer({"title_max": 30}, [], 0) == 0


def test_the_writer_follows_the_owners_rules_and_stays_grounded():
    plain = postpack.generate(CLIP, CLIP[0], [], "Business", {})
    assert plain["source"] == "Extracted from the clip's transcript" and "brain" not in plain and plain["cta"]
    assert any(t != t.lower() for t in plain["titles"]) and len(plain["hashtags"]) > 2

    rule = _say("Titles in lower case, no emoji. Use at most 2 hashtags and don't ask people to follow.")
    p = postpack.generate(CLIP, CLIP[0], [], "Business", {})
    assert p["titles"] == [t.lower() for t in plain["titles"]] and p["title"] == p["titles"][p["recommended_title"]]
    assert p["hashtags"] == plain["hashtags"][:2] and p["cta"] == ""
    assert p["captions"] == plain["captions"]                       # the rule names titles, not the post text
    assert p["checks"] == {}                                        # still nothing the clip does not say
    assert p["source"] == ("Extracted from the clip's transcript · your Brain: titles in lower case, no emoji, "
                           "at most 2 hashtags, no call to action")
    assert p["brain"] == {"rules": ["titles in lower case", "no emoji", "at most 2 hashtags", "no call to action"],
                          "memories": [rule["id"]]}
    # what the owner types on the post afterwards is theirs and stays as typed
    edited = postpack.apply_edit(p, {"title": "My OWN Title 😀", "hashtags": ["#one", "#two", "#three"]})
    assert edited["title"] == "My OWN Title 😀" and len(edited["hashtags"]) == 3


def _add_skill(name: str, lines: list[str], topics: list[str]) -> None:
    from clipfoundry.studio import skills

    raw = json.dumps({"schema": "clipforge.skill/v1", "id": name.lower().replace(" ", "-"), "name": name,
                      "version": "1", "description": f"About {name.lower()}.", "modes": ["highlights"],
                      "topics": topics, "preferences": {},
                      "instructions": "# Rules\n" + "\n".join(f"- {x}" for x in lines)}).encode()
    row = skills.save("local", f"{name.lower().replace(' ', '-')}.json", raw)
    db.update("skills", row["id"], enabled=1)


def test_a_models_text_is_dressed_too_and_it_reads_the_rules_not_the_notes(monkeypatch):
    _say("My cousin Bartholomew says: titles in lower case, no emoji, at most 3 hashtags.")
    _add_skill("Titles that travel", ["A title names the stakes in the first four words.",
                                      "Hashtags name the niche, never the platform."], ["titles", "hashtags"])
    _add_skill("Colour grading", ["Lift the shadows before you add contrast."], ["colour", "grade"])
    fake = {"titles": ["Talk To Customers First 🔥", "My first startup cost ten thousand dollars 😱"],
            "recommended": 0, "captions": ["The lesson is simple: talk to customers first. 🚀"],
            "hook": "Talk to customers first 🔥", "hashtags": ["startup", "customers", "viral", "product", "savings"]}
    prompts: list[str] = []

    def answer(settings, prompt):
        prompts.append(prompt)
        return json.dumps(fake)

    monkeypatch.setattr(llm, "complete", answer)
    sents = TEXT.replace(": ", ". ").split(". ")
    p = postpack.generate(sents, sents[0], [], "Business", {"ai_provider": "ollama", "ollama_model": "m"})
    assert "talk to customers first" in p["titles"] and all(t == t.lower() for t in p["titles"])
    everything = " ".join([*p["titles"], *p["captions"], p["hook"], *p["hashtags"]])
    assert not poststyle._EMOJI.search(everything)  # noqa: SLF001
    assert len(p["hashtags"]) == 3 and "#viral" not in p["hashtags"] and p["checks"] == {}
    assert "checked against the transcript · your Brain: titles in lower case" in p["source"]
    # the model is told the choices in ClipForge's words; the owner's note itself is not sent
    assert "titles in lower case; no emoji; at most 3 hashtags" in prompts[0] and "Bartholomew" not in prompts[0]
    # ... with the one-line craft and what the owner's switched-on skill about titles says, not the other skill
    assert "never #fyp" in prompts[0] and "holds back the outcome" in prompts[0]
    assert "A title names the stakes in the first four words." in prompts[0] and "shadows" not in prompts[0]


def test_hashtags_say_what_the_clip_is_about():
    sents = ["This video went viral on TikTok last week.", "Everybody asked how the sourdough starter works.",
             "You feed the sourdough flour and water every single morning.",
             "After a week the starter doubles and your bread rises."]
    tags = postpack.hashtags_for(" ".join(sents))
    assert "#sourdough" in tags and "#starter" in tags
    assert not {"#viral", "#tiktok", "#video"} & set(tags) and len(tags) <= postpack.HASHTAG_LIMIT == 5
    # a clip about the platforms keeps them: its title says that is its subject
    about = "YouTube Shorts or TikTok? I post clips on YouTube and TikTok every day."
    tags = postpack.hashtags_for(about, prefer="YouTube Shorts or TikTok?")
    assert {"#youtube", "#tiktok"} <= set(tags) and "#viral" not in tags
    assert postpack.generic_tag("#fyp", {"fyp"}) and not postpack.generic_tag("#tiktok", {"tiktok"})


def test_story_clips_follow_the_rules_kept_for_their_video():
    from story_fixtures import three_stories
    from test_story_clips import _plan

    from clipfoundry.studio import story_review

    transcript, _ = three_stories()
    result, words = _plan(transcript, 720.0, "whole")
    p = db.create_project("stories", status="ready", clip_mode="full_stories", duration=720.0,
                          options={"story_split": "whole"})
    story_review.save(p, result)
    _say("Titles in lower case. No hashtags.", scope=f"project:{p['id']}")
    project = db.get_project(p["id"])
    first = db.select("story_proposals", "project_id = ? AND kind = 'story'", (p["id"],), "position")[0]
    one = story_review.create_clip(project, first, words, {})          # made again from Review, on its own
    made = [one] + story_review.auto_clips(project, words, db.get_settings())
    assert len(made) == 3 and all(c["title"] == c["title"].lower() and c["hashtags"] == [] for c in made)


def test_autopilots_packages_follow_the_rules_too(monkeypatch):
    from clipfoundry.autopilot import packaging

    owner = {"title_case": "lower", "emoji": False, "tags": 1, "cta": False, "lines": ["titles in lower case"]}
    yt = packaging.build("youtube", "direct", "Talk To Customers First", "The lesson is simple.",
                         ["#business", "#customers"], postpack.CTA_DEFAULT, "", ["business"], owner)
    assert yt["title"] == "talk to customers first" and yt["hashtags"] == ["#business"]
    assert postpack.CTA_DEFAULT not in yt["description"] and packaging.validate(yt, TEXT) == []
    same = packaging.build("youtube", "direct", "Talk To Customers First", "The lesson is simple.",
                           ["#business", "#customers"], postpack.CTA_DEFAULT, "", ["business"])
    assert same["title"] == "Talk To Customers First" and postpack.CTA_DEFAULT in same["description"]

    for meta in packaging.extracted_candidates("tiktok", CLIP, {"hook": CLIP[0], "post": {}}, "", ["business"],
                                               ["#business", "#customers"], owner):
        assert meta["title"] == meta["title"].lower() and meta["hashtags"] == ["#business"]
        assert packaging.validate(meta, TEXT) == []

    prompts: list[str] = []

    def answer(settings, prompt, **kw):
        prompts.append(prompt)
        return json.dumps({"suggestions": [{"style": "direct", "text": "Talk to customers first, then build"}]})

    monkeypatch.setattr(llm, "complete", answer)
    out = packaging.ai_candidates({"ai_provider": "ollama"}, "youtube", CLIP, {"post": {}}, "", ["business"],
                                  ["#business"], TEXT, [], owner)
    assert out and out[0]["title"] == "talk to customers first, then build"
    assert "The owner's rules for this text" in prompts[0] and "titles in lower case" in prompts[0]


def test_a_title_that_keeps_the_owners_length_goes_first(tmp_path):
    from clipfoundry.autopilot import packaging
    from clipfoundry.pipeline import transcribe
    from clipfoundry.pipeline.common import write_json
    from test_core import _srt

    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"x")
    write_json(folder / "transcript.json", {"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    project = db.create_project("talk", source_path=str(folder / "source.mp4"), status="ready")
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    end = next(w["end"] for w in words if w["w"] == "build.")
    clip = db.create_clip(project["id"], start=0.3, end=end, title="t", hook=CLIP[0], status="ready",
                          caption_text=TEXT, hashtags=["#business", "#customers"], post={"cta": postpack.CTA_DEFAULT})
    settings = db.get_settings()
    before = packaging.package(clip, None, "youtube", settings)
    assert len(before["title"]) > 30
    _say("Titles under 30 characters, in lower case.")
    after = packaging.package(clip, None, "youtube", settings)
    assert len(after["title"]) <= 30 and after["title"] == after["title"].lower() and not after["problems"]
    rows = db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube' AND selected = 1", (clip["id"],))
    assert [r["title"] for r in rows] == [after["title"]]


def test_a_run_reads_the_style_once_and_counts_the_use():
    from clipfoundry.pipeline import process

    rule = _say("Titles in lower case.")
    project = db.create_project("talk")
    opts = process._options(project, db.get_settings())  # noqa: SLF001
    assert opts["post_style"]["title_case"] == "lower" and opts["post_style"]["ids"] == [rule["id"]]
    p = postpack.generate(CLIP, CLIP[0], [], "Business", opts)
    assert all(t == t.lower() for t in p["titles"])
    # a clip written again from the clip page reads the Brain for its own video
    clip = db.create_clip(project["id"], start=0.0, end=20.0, title="t", hook=CLIP[0], caption_text=TEXT)
    again = postpack.for_clip(clip, [], db.get_settings(), use_ai=False)
    assert again["titles"] and all(t == t.lower() for t in again["titles"])
