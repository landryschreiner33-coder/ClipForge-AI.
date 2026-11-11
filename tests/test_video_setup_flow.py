"""Make a YouTube video by talking it through (docs/clipforge/VIDEO_SETUP.md): a draft from your files and your idea,
ClipForge AI's plan from the built-in rules or a model (a fake one here; nothing leaves the machine), questions or
"Just do it", hand edits that stay, the plan becoming the brief, the build job planning after listening, the plan
driving the edit (the opening, fit to length, ClipForge AI's prompt) and changing it after the build."""
from __future__ import annotations

import json
import threading
import time

import pytest

from test_studio_smart_edit import HIKE, _asset, _cut, _lines, _project, _words, env  # noqa: F401

WS = "local"
H = {"X-ClipFoundry": "1"}


class FakeModel:
    """Stands in for llm.complete and llm.converse: records every request, answers from a script."""

    def __init__(self, *answers):
        self.answers, self.calls, self.gate = list(answers), [], threading.Event()
        self.gate.set()

    def _next(self):
        self.gate.wait(10)
        answer = self.answers.pop(0) if self.answers else "{}"
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)

    def complete(self, settings, prompt, **kw):
        self.calls.append({"request": prompt, "history": [], **kw})
        return self._next()

    def converse(self, settings, messages, **kw):
        self.calls.append({"request": messages[-1]["content"], "history": messages[:-1], **kw})
        return self._next()


def _model(monkeypatch, *answers, **settings) -> FakeModel:
    from clipfoundry import db
    from clipfoundry.pipeline import llm

    fake = FakeModel(*answers)
    monkeypatch.setattr(llm, "complete", fake.complete)
    if hasattr(llm, "converse"):
        monkeypatch.setattr(llm, "converse", fake.converse)
    db.save_settings({"ai_provider": "ollama", "ollama_url": "http://localhost:11434", **settings})
    return fake


def _files(env) -> list[dict]:
    return [_asset(env, "dock_jump.mp4", "video", 190), _asset(env, "drive.mp4", "video", 760),
            _asset(env, "sunset.jpg", "image"), _asset(env, "summer song.mp3", "audio", 210)]


def _heard(asset: dict, words: list[dict]) -> None:
    """The transcript the listening job would have saved for this video."""
    from pathlib import Path

    (Path(asset["path"]).parent / "transcript.json").write_text(json.dumps({"segments": [{"words": words}]}))


def _settled(message_id: str, timeout: float = 5.0) -> dict:
    from clipfoundry import db

    end = time.time() + timeout
    while time.time() < end:
        row = db.fetch("brain_chat_messages", message_id)
        if row["status"] != "thinking":
            return row
        time.sleep(0.02)
    raise AssertionError("still thinking")


def _last_ai(view: dict) -> dict:
    return [m for m in view["messages"] if m["role"] == "ai"][-1]


class Lease:
    def __init__(self):
        self.reports = []

    def progress(self, frac, message=""):
        self.reports.append((frac, message))

    def canceled(self):
        return False


# ------------------------------------------------------------------ without a model: the built-in rules
def test_a_draft_from_files_and_an_idea_gets_a_plan_and_questions_from_the_rules(env):
    from clipfoundry import db
    from clipfoundry.studio import prefs, video_setup

    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask",
                          idea="A 10 minute travel vlog of our lake trip. Open with the dock jump, cut the gas "
                               "station, put summer song under it.")
    row = db.fetch("studio_projects", v["id"])
    assert row["status"] == "draft" and row["message"] == "Planning with ClipForge AI" and row["plan_revision"] == 0
    # every video is listened to from the start; nothing is built yet
    jobs = db.select("studio_jobs", "target_id = ?", (v["id"],))
    assert [j["kind"] for j in jobs] == ["video_media"]
    plan = v["plan"]
    assert plan["length_min"] == 10 and plan["video_type"] == "Travel vlog" and plan["opening"] == "the dock jump"
    assert plan["cold_open"] == "on" and plan["cut"] == ["gas station"]
    assert plan["music"] == "mine" and plan["music_file"] == files[3]["id"]
    assert [m["role"] for m in v["messages"]] == ["owner", "ai"]
    ai = _last_ai(v)
    assert ai["data"]["source"] == "rules" and ai["data"]["plan"] == plan
    assert "Settings → ClipForge AI" in ai["data"]["say"]  # how to get a smarter planner, once
    # it asks what matters and is still open: who it is for and the feel (the length was said)
    assert [q["id"] for q in v["open"]] == ["audience", "feel"] and v["rounds"] == 1
    assert "Length: about 10 minutes" in ai["text"] and "Who is it for?" in ai["text"]
    assert v["model"]["ready"] is False and v["href"] == f"#/create/video/{v['id']}"
    assert [f["state"] for f in v["files"]] == ["listening", "listening", "", ""]
    # the choice is remembered for next time
    assert prefs.get_appearance(WS, WS)["value"]["video_setup_mode"] == "ask"
    # Projects lists the draft; it opens on this page
    from clipfoundry.studio import routes

    entry = [x for x in routes.library() if x["id"] == v["id"]][0]
    assert entry["status"] == "draft" and entry["href"] == f"#/create/video/{v['id']}"


def test_talking_changes_the_plan_and_quick_answers_and_hand_edits_stay(env):
    from clipfoundry.studio import video_setup

    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask",
                          idea="Our lake trip, about 10 minutes")
    assert [q["id"] for q in v["open"]] == ["audience", "feel"]
    # a quick answer to a question (the page says which question it answers)
    out = video_setup.say(WS, v["id"], "Friends and family", "audience")
    assert out["owner"]["data"]["answers"] == "audience"
    v = out["setup"] if "setup" in out else video_setup.view(WS, v["id"])
    assert v["plan"]["audience"] == "Friends and family" and v["plan"]["length_min"] == 10
    # the other question asked with it stays open (no new round), and the answer says so
    assert v["rounds"] == 1 and [q["id"] for q in v["open"]] == ["feel"]
    assert out["ai"]["data"]["say"].endswith("One more question below, or press Just do it.")
    assert [q["id"] for q in out["ai"]["data"]["questions"]] == ["feel"]
    # moving on in your own words: no question stays to nag you, and the rules ask in the first round only
    out = video_setup.say(WS, v["id"], "make it 5 minutes and no music")
    v = video_setup.view(WS, v["id"])
    assert v["open"] == [] and v["rounds"] == 1
    assert v["plan"]["length_min"] == 5 and v["plan"]["music"] == "none"
    assert out["ai"]["data"]["say"].startswith("Got it.") and "about 5 minutes" in out["ai"]["data"]["say"]
    # what was said in an earlier message stands: later messages about other things keep it
    video_setup.say(WS, v["id"], "add captions")
    v = video_setup.view(WS, v["id"])
    assert (v["plan"]["length_min"], v["plan"]["music"], v["plan"]["captions"]) == (5, "none", "on")
    # a hand edit stays until a message talks about that part again
    v = video_setup.patch(WS, WS, v["id"], {"plan": {"feel": "calm", "keep": ["the sunset"]}})
    assert v["plan"]["feel"] == "calm" and v["locked"] == ["feel", "keep"]
    video_setup.say(WS, v["id"], "use vertical")
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["feel"] == "calm" and v["plan"]["aspect_ratio"] == "9:16" and v["plan"]["keep"] == ["the sunset"]
    video_setup.say(WS, v["id"], "actually make it energetic")
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["feel"] == "energetic" and v["locked"] == ["keep"]
    # nothing the rules understand: it says so and changes nothing
    out = video_setup.say(WS, v["id"], "hmm")
    assert out["ai"]["data"]["say"].startswith("I didn't find anything to change")
    with pytest.raises(video_setup.SetupError):
        video_setup.say(WS, v["id"], "   ")
    with pytest.raises(video_setup.SetupError):
        video_setup.say(WS, v["id"], "x" * 4001)
    with pytest.raises(video_setup.SetupError):
        video_setup.say("other", v["id"], "hello")  # another workspace's draft
    with pytest.raises(video_setup.SetupError):
        video_setup.patch(WS, WS, v["id"], {"plan": {"colour": "red"}})
    with pytest.raises(video_setup.SetupError):
        video_setup.patch(WS, WS, v["id"], {"mode": "sometimes"})


def test_typing_under_the_only_question_answers_it_only_with_an_answer(env):
    from clipfoundry.studio import video_setup

    files = _files(env)
    ids = [f["id"] for f in files]
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", idea="Our lake trip, about 10 minutes, calm")
    assert [q["id"] for q in v["open"]] == ["audience"]
    # typed instead of tapped, about something else: not who it is for
    video_setup.say(WS, v["id"], "the beach part is the best")
    assert video_setup.view(WS, v["id"])["plan"]["audience"] == ""
    # typed instead of tapped, naming people: it is
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", idea="Our lake trip, about 10 minutes, calm")
    out = video_setup.say(WS, v["id"], "my gaming friends")
    assert out["owner"]["data"]["answers"] == "audience"
    assert video_setup.view(WS, v["id"])["plan"]["audience"] == "my gaming friends"


def test_files_order_name_and_removing_a_file_before_the_build(env):
    from clipfoundry.studio import video_setup

    files = _files(env)
    ids = [f["id"] for f in files]
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", idea="Call it Lake Days. Put summer song under it.")
    assert v["name"] == "Lake Days" and v["plan"]["title"] == "Lake Days"
    v = video_setup.patch(WS, WS, v["id"], {"name": "Summer 2026"})
    assert v["name"] == "Summer 2026"
    video_setup.say(WS, v["id"], "call it Something Else")
    assert video_setup.view(WS, v["id"])["name"] == "Summer 2026"  # a name you gave stays
    # taking the music file out takes it out of the plan too
    v = video_setup.patch(WS, WS, v["id"], {"asset_ids": [ids[1], ids[0], ids[2]]})
    assert [f["id"] for f in v["files"]] == [ids[1], ids[0], ids[2]]
    assert v["plan"]["music_file"] == "" and v["plan"]["music"] == ""
    with pytest.raises(video_setup.SetupError):
        video_setup.patch(WS, WS, v["id"], {"asset_ids": [ids[2]]})  # no video left
    with pytest.raises(video_setup.SetupError):
        video_setup.patch(WS, WS, v["id"], {"asset_ids": ["as-someone-else"]})
    with pytest.raises(video_setup.SetupError):
        video_setup.start(WS, WS, asset_ids=[ids[2]], idea="pictures only")
    with pytest.raises(video_setup.SetupError):
        video_setup.start(WS, WS, asset_ids=[], idea="nothing")


# ------------------------------------------------------------------ building
def test_build_my_video_turns_the_plan_into_the_brief(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    ids = [f["id"] for f in files]
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", style_id="settings", remember={"enabled": False},
                          idea="A 10 minute vlog for my family. Open with the dock jump, keep the sunset, no music.")
    video_setup.patch(WS, WS, v["id"], {"plan": {"order": [ids[2], ids[1], ids[0]], "zooms": "on",
                                                  "summary": "Our lake trip"}})
    out = video_setup.build(WS, WS, v["id"])
    assert out["href"] == f"#/video/{v['id']}"
    row = db.fetch("studio_projects", v["id"])
    assert row["status"] == "building" and not row["setup"]["pending"]
    b = row["brief"]
    assert b["target_duration_s"] == 600 and b["audience"] == "Family" and b["open_with"] == "the dock jump"
    assert b["must_keep"] == "sunset" and b["music"] == "none" and b["punch_in"] is True
    assert b["smart_edit"] == "smart" and b["ai_edit"] is True and b["cold_open"] is True
    assert b["plan"] == {"summary": "Our lake trip", "opening": "the dock jump"}
    assert row["guidance"]["values"]["target_duration_s"] == 600  # the same guidance as the one-step create
    assert row["asset_ids"] == [ids[2], ids[1], ids[0], ids[3]]  # the plan's order, the sound after
    assert [j["kind"] for j in db.select("studio_jobs", "target_id = ?", (v["id"],), "created_at ASC")] == \
        ["video_media", "video_build"]
    # once building, the draft's chat and changes are closed; the editor page takes over
    with pytest.raises(video_setup.SetupError) as e:
        video_setup.build(WS, WS, v["id"])
    assert e.value.status == 409
    with pytest.raises(video_setup.SetupError):
        video_setup.say(WS, v["id"], "make it shorter")
    view = video_flow.view(row)
    assert view["setup"]["plan"]["length_min"] == 10 and "Opens with: the dock jump" in view["setup"]["lines"]


def test_just_do_it_without_a_model_builds_at_once_with_the_rules_plan(env):
    from clipfoundry import db
    from clipfoundry.studio import prefs, video_setup

    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="auto", style_id="settings",
                          remember={"enabled": False}, idea="Fast-paced 3 minute recap, vertical")
    row = db.fetch("studio_projects", v["id"])
    assert row["status"] == "building" and not row["setup"]["pending"]
    assert row["brief"]["target_duration_s"] == 180 and row["brief"]["aspect_ratio"] == "9:16"
    assert row["brief"]["smart_edit"] == "tight"
    ai = _last_ai(v)
    assert ai["data"]["building"] and "built-in rules" in ai["data"]["say"] and v["open"] == []
    assert prefs.get_appearance(WS, WS)["value"]["video_setup_mode"] == "auto"
    # the next new video starts in the mode chosen last time
    v2 = video_setup.start(WS, WS, asset_ids=[files[0]["id"]], style_id="settings", remember={"enabled": False})
    assert db.fetch("studio_projects", v2["id"])["status"] == "building"


# ------------------------------------------------------------------ with a model (a fake one)
PLAN = {"title": "Lake Days", "summary": "Our summer trip to the lake.", "video_type": "Travel vlog",
        "audience": "Friends and family", "goal": "", "length_min": 8, "aspect_ratio": "16:9", "feel": "energetic",
        "edit": "smart", "opening": "the jump off the dock", "story": ["the drive up", "swimming", "sunset"],
        "keep": ["sunset"], "cut": ["gas station"], "music": "mine", "music_file": 4, "voiceover_files": [],
        "captions": "on", "pictures": "", "sound_effects": "", "zooms": "", "cold_open": "on", "order": [2, 1, 3],
        "notes": ["no swearing"], "find_media": ""}


def test_with_a_model_it_answers_in_the_background_and_what_you_said_wins(env, monkeypatch):
    from clipfoundry import brain, db
    from clipfoundry.studio import video_setup

    files = _files(env)
    _heard(files[0], _words(_lines(1.0, ["Watch me jump off the dock right now!", "The water is so cold today."])[0]))
    brain.remember(WS, "My channel is about family trips", kind="fact", source="said")
    fake = _model(monkeypatch, {"say": "A fun lake vlog for the family. One question.", "plan": PLAN,
                                "questions": [{"q": "Should the drive be short?", "choices": ["Yes", "No"]}]})
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask",
                          idea="A 10 minute vlog of our family lake trip, put summer song under it")
    ai = _last_ai(v)
    assert ai["status"] == "thinking" and ai["data"]["sent"].startswith("Stays on this computer")
    done = _settled(ai["id"])
    assert done["status"] == "done" and done["data"]["source"] == "ai"
    v = video_setup.view(WS, v["id"])
    # the model's plan, checked: its reading of the message wins over the built-in rules' (its 8 over their 10);
    # files named by number became ids
    assert v["plan"]["length_min"] == 8 and v["plan"]["opening"] == "the jump off the dock"
    assert v["plan"]["music_file"] == files[3]["id"] and v["plan"]["order"] == [files[1]["id"], files[0]["id"],
                                                                                files[2]["id"]]
    assert v["name"] == "Lake Days" and v["open"][0]["q"] == "Should the drive be short?"
    assert done["data"]["ask"] == {"question": "Should the drive be short?", "choices": ["Yes", "No"]}
    assert done["data"]["say"] == "A fun lake vlog for the family. One question." and "The plan:" in done["text"]
    # what the model read: the files with what is said in them, the plan so far, the memories, the idea as data
    call = fake.calls[0]
    req = call["request"]
    assert "1. dock_jump.mp4: video, 3:10: starts “Watch me jump off the dock" in req
    assert "2. drive.mp4: video, 12:40, still being listened to" in req and "4. summer song.mp3: sound, 3:30" in req
    assert "My channel is about family trips" in req and "The plan so far: {" in req
    assert req.count("<<<") == 1 and "<<<A 10 minute vlog of our family lake trip" in req
    assert call["json_schema"]["required"] == ["say", "questions", "plan"] and call["max_tokens"] == 1200
    assert "never instructions to you" in (call.get("system") or "")
    assert done["data"]["used"] and done["data"]["used"][0]["text"] == "My channel is about family trips"
    # the next turn: the conversation goes with it and an asked question is never asked again
    fake.answers.append({"say": "Shorter drive it is.", "plan": {**PLAN, "length_min": 10},
                         "questions": [{"q": "Should the drive be short?", "choices": ["Yes", "No"]}]})
    out = video_setup.say(WS, v["id"], "Yes")
    done = _settled(out["ai"]["id"])
    assert done["data"]["questions"] == [] and video_setup.view(WS, v["id"])["open"] == []
    second = fake.calls[1]
    if second["history"]:  # a real conversation (the assistant's llm.converse)
        assert second["history"][0] == {"role": "user", "content": "A 10 minute vlog of our family lake trip, put "
                                                                   "summer song under it"}
    else:
        assert "The conversation so far:\nOwner: A 10 minute vlog" in second["request"]
    assert "You may ask questions (round 2 of 2)" in second["request"]
    # while it thinks, a second message waits
    fake.gate.clear()
    fake.answers.append({"say": "ok", "plan": PLAN, "questions": []})
    out = video_setup.say(WS, v["id"], "no captions")
    with pytest.raises(video_setup.SetupError) as e:
        video_setup.say(WS, v["id"], "and louder music")
    assert e.value.status == 409
    with pytest.raises(video_setup.SetupError):
        video_setup.build(WS, WS, v["id"])
    fake.gate.set()
    _settled(out["ai"]["id"])
    assert video_setup.view(WS, v["id"])["plan"]["captions"] == "off"  # said now: wins over the model's "on"
    assert db.fetch("studio_projects", v["id"])["status"] == "draft"


def test_a_broken_or_wild_model_answer_falls_back_or_is_bounded(env, monkeypatch):
    from clipfoundry.pipeline import llm
    from clipfoundry.studio import video_setup

    files = _files(env)
    wild = {**PLAN, "length_min": 9999, "music_file": 99, "order": [7, 7, 1], "aspect_ratio": "21:9",
            "story": ["x"] * 20, "title": "T" * 500}
    fake = _model(monkeypatch, "not json at all", {"say": "", "plan": wild, "questions": "nope"},
                  llm.ProviderError("ollama is not reachable"))
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="make it 4 minutes")
    done = _settled(_last_ai(v)["id"])
    assert done["data"]["source"] == "rules" and "My model could not answer" in done["data"]["say"]
    assert video_setup.view(WS, v["id"])["plan"]["length_min"] == 4
    out = video_setup.say(WS, v["id"], "something new")
    done = _settled(out["ai"]["id"])
    p = video_setup.view(WS, v["id"])["plan"]
    assert p["length_min"] == 4  # said before and never taken back: stands over the model's 9999
    assert p["music_file"] == files[3]["id"]  # number 99 does not exist: "mine" falls back to the song by its name
    assert p["order"] == [files[0]["id"], files[1]["id"], files[2]["id"]] and p["aspect_ratio"] == ""
    assert len(p["story"]) == 8 and len(p["title"]) == 120
    out = video_setup.say(WS, v["id"], "again")
    done = _settled(out["ai"]["id"])
    assert done["data"]["source"] == "rules" and "ollama is not reachable" in done["data"]["say"]
    assert len(fake.calls) == 3


def test_an_online_model_has_a_daily_limit_and_says_what_is_sent(env, monkeypatch):
    from clipfoundry.studio import video_setup

    files = _files(env)
    _model(monkeypatch, {"say": "ok", "plan": PLAN, "questions": []}, ai_provider="openai_compatible",
           openai_url="https://api.example.com/v1", ai_edit_requests_per_day=1)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a vlog")
    done = _settled(_last_ai(v)["id"])
    assert done["data"]["sent"].startswith("Sent over the internet to") and "Never the video" in done["data"]["sent"]
    out = video_setup.say(WS, v["id"], "10 minutes")
    assert out["ai"]["status"] == "done" and "today's limit of 1" in out["ai"]["data"]["say"]
    assert video_setup.view(WS, v["id"])["plan"]["length_min"] == 10  # the rules still read it


def test_brain_notes_never_go_to_nvidia_and_the_rules_and_plan_are_named(env, monkeypatch):
    from clipfoundry import brain
    from clipfoundry.studio import video_setup

    files = _files(env)
    brain.remember(WS, "Never show my daughter's school", kind="rule", source="said")
    brain.remember(WS, "My channel is about family lake trips", kind="fact", source="said")
    fake = _model(monkeypatch, {"say": "ok", "plan": PLAN, "questions": []}, ai_provider="nvidia")
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="our lake trip, 10 minutes")
    done = _settled(_last_ai(v)["id"])
    assert done["data"]["source"] == "ai" and done["data"]["used"] == []
    req = fake.calls[0]["request"]
    assert "daughter's school" not in req and "family lake trips" not in req and "our lake trip" in req
    assert "never your Brain notes" in done["data"]["sent"] and "Brain rules" not in done["data"]["sent"]
    assert video_setup.model_view()["brain"] is False
    # any other model reads the rules and the memories that fit, and the line says so
    fake = _model(monkeypatch, {"say": "ok", "plan": PLAN, "questions": []})
    out = video_setup.say(WS, v["id"], "make it calm")
    done = _settled(out["ai"]["id"])
    assert "daughter's school" in fake.calls[0]["request"] and video_setup.model_view()["brain"] is True
    assert "your Brain rules" in done["data"]["sent"] and "the plan so far" in done["data"]["sent"]


def test_answering_one_question_keeps_the_others_it_asked_with_it(env, monkeypatch):
    from clipfoundry.studio import video_setup

    files = _files(env)
    asks = [{"q": "Who is it for?", "choices": ["Family", "Everyone"]},
            {"q": "Which moment opens it?", "choices": ["The jump", "The sunset"]}]
    fake = _model(monkeypatch, {"say": "Two questions.", "plan": PLAN, "questions": asks},
                  {"say": "Family it is.", "plan": PLAN, "questions": []},
                  {"say": "Shorter then.", "plan": PLAN, "questions": []})
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="our lake trip")
    _settled(_last_ai(v)["id"])
    v = video_setup.view(WS, v["id"])
    first, second = v["open"]
    # a quick answer to the first: the second stays on screen (no new round), and the model is told so
    out = video_setup.say(WS, v["id"], "Family", first["id"])
    done = _settled(out["ai"]["id"])
    v = video_setup.view(WS, v["id"])
    assert [q["id"] for q in v["open"]] == [second["id"]] and v["rounds"] == 1
    assert [q["id"] for q in done["data"]["questions"]] == [second["id"]]
    assert "Your questions still on screen with quick answers (don't ask them again): Who is it for? / Which " \
           "moment opens it?" in fake.calls[1]["request"]
    # moving on in your own words: the question goes, nobody nags
    out = video_setup.say(WS, v["id"], "make it shorter")
    _settled(out["ai"]["id"])
    assert video_setup.view(WS, v["id"])["open"] == []


def test_just_do_it_that_cannot_start_keeps_the_draft_and_says_why(env, monkeypatch):
    from clipfoundry.studio import video_setup

    files = _files(env)

    def refuse(*_a, **_k):
        raise video_setup.SetupError("Choose a length between 15 seconds and 4 hours.")

    monkeypatch.setattr(video_setup, "start_build", refuse)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="auto", idea="a vlog")
    assert v["status"] == "draft" and v["href"] == f"#/create/video/{v['id']}"
    assert _last_ai(v)["data"]["say"].startswith("I couldn't start the edit yet: Choose a length")


def test_just_do_it_with_a_model_plans_in_the_build_job_after_listening(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    fake = _model(monkeypatch, {"say": "Planned: a lake vlog.", "plan": {**PLAN, "length_min": 6, "captions": "off",
                                                                          "zooms": ""},
                                "questions": [{"q": "?", "choices": []}]})
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="auto", style_id="settings",
                          remember={"enabled": False}, idea="our lake trip, 6 minutes, no captions, no zooms")
    row = db.fetch("studio_projects", v["id"])
    assert row["status"] == "building" and row["setup"]["pending"] is True
    assert row["brief"]["target_duration_s"] == 360 and fake.calls == []  # the rules' plan until the job plans
    assert "listening to your files" in _last_ai(v)["data"]["say"]
    words = {files[0]["id"]: _words(_lines(1.0, ["Watch me jump off the dock right now!"])[0])}
    lease = Lease()
    got = video_setup.plan_in_build(row, video_flow._assets(row), words, db.get_settings(), lease)
    assert any(m == "ClipForge AI is planning your video" for _f, m in lease.reports)
    assert got["setup"]["pending"] is False and got["setup"]["source"] == "ai"
    b = got["brief"]
    assert b["target_duration_s"] == 360 and b["captions"] is False  # the model's plan, made after listening
    assert b["punch_in"] is False  # what the rules read fills what the model left open
    assert b["open_with"] == "the jump off the dock" and b["music"] == "supplied"
    assert b["music_asset_id"] == files[3]["id"] and got["name"] == "Lake Days"
    assert got["asset_ids"][:3] == [files[1]["id"], files[0]["id"], files[2]["id"]]
    assert got["guidance"]["values"]["target_duration_s"] == 360
    req = fake.calls[0]["request"]
    assert "starts “Watch me jump off the dock" in req and "No questions now" in req
    ai = _last_ai(video_setup.view(WS, v["id"]))
    assert ai["data"]["questions"] == [] and ai["data"]["say"].startswith("Planned: a lake vlog.")
    # a model that cannot answer leaves the rules' plan; the build goes on
    row2 = db.fetch("studio_projects", video_setup.start(WS, WS, asset_ids=[files[0]["id"]], mode="auto",
                                                         style_id="settings", remember={"enabled": False},
                                                         idea="8 minutes")["id"])
    fake.answers.append("garbage")
    got = video_setup.plan_in_build(row2, video_flow._assets(row2), {}, db.get_settings(), Lease())
    assert got["setup"]["source"] == "rules" and got["brief"]["target_duration_s"] == 480


# ------------------------------------------------------------------ after the build
def test_changing_the_plan_after_the_build_edits_again(env):
    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files[:2]], mode="ask", style_id="settings",
                          remember={"enabled": False}, idea="10 minutes, 16:9")
    video_setup.build(WS, WS, v["id"])
    row = db.fetch("studio_projects", v["id"])
    plan = video_flow.rough_cut(row, video_flow._assets(row), {})
    video_flow.save_revision(v["id"], plan, "Rough cut from your brief", None, {"action": "build", "prev": None,
                                                                                "redo": None})
    with pytest.raises(video_setup.SetupError) as e:
        video_setup.change_plan(WS, WS, v["id"], 0, {"length_min": 5})
    assert e.value.status == 409
    out = video_setup.change_plan(WS, WS, v["id"], 1, {"length_min": 5, "aspect_ratio": "9:16", "captions": "off"})
    row = db.fetch("studio_projects", v["id"])
    assert row["brief"]["target_duration_s"] == 300 and row["guidance"]["values"]["target_duration_s"] == 300
    assert row["setup"]["look"] == {"aspect": "9:16", "captions": False}
    job = db.fetch("studio_jobs", out["job"])
    assert job["kind"] == "video_smart" and job["revision"] == 1
    video_setup.look_used(v["id"])
    assert db.fetch("studio_projects", v["id"])["setup"]["look"] == {}
    with pytest.raises(video_setup.SetupError):
        video_setup.change_plan(WS, WS, v["id"], 1, {"colour": "red"})


# ------------------------------------------------------------------ the plan drives the edit
def test_the_opening_you_asked_for_opens_the_video(env):
    v = _asset(env, "hike.mp4", "video", 400)
    script, _end = _lines(1.0, HIKE, gap=1.0, step=0.4)
    words = {v["id"]: _words(script)}
    asked = _cut(_project([v], {"smart_edit": "smart", "music": "none", "sound_effects": False,
                                "open_with": "the ravens watching us"}), words)
    hook = asked["clips"][0]
    assert hook["id"] == "hook" and asked["outline"][0]["summary"].startswith("Cold open: “A pair of ravens")
    assert any(n.startswith("Opened with “A pair of ravens") and "the opening you asked for" in n
               for n in asked["notes"])
    # an opening that is already the start of the video needs no cold open
    start = _cut(_project([v], {"smart_edit": "smart", "music": "none", "open_with": "welcome back to the channel"},
                          "Start"), words)
    assert not any(c.get("hook") for c in start["clips"])
    # nothing matches: the usual strongest line
    other = _cut(_project([v], {"smart_edit": "smart", "music": "none", "open_with": "the drone shot of the castle"},
                          "Other"), words)
    assert other["outline"][0]["summary"].startswith("Cold open: “Why did nobody tell me")
    # a shorter video opens with what you asked for too (30 s or more)
    short_words = {v["id"]: _words(_lines(1.0, HIKE[:10], gap=1.0, step=0.4)[0])}
    short = _cut(_project([v], {"smart_edit": "smart", "music": "none", "open_with": "the hut keeper"}, "Short"),
                 short_words)
    assert short["clips"][0]["id"] == "hook" and "hut keeper" in short["outline"][0]["summary"]


def test_fit_to_length_keeps_what_the_plan_is_about(env):
    from clipfoundry.studio import smart_edit

    about = smart_edit.plan_words({"plan": {"summary": "Ravens and the hut", "story": ["the ridge"]},
                                   "must_keep": "soup"})
    assert about == {"ravens", "hut", "ridge", "soup"}
    assert smart_edit.plan_bonus("A pair of ravens watched us near the hut.", about) == pytest.approx(0.1)
    assert smart_edit.plan_bonus("ravens hut ridge soup", about) == pytest.approx(0.15)  # at most PLAN_BONUS
    assert smart_edit.plan_bonus("anything", set()) == 0.0


def test_clipforge_ai_reads_the_plan_in_every_part_of_the_edit():
    from clipfoundry.studio import ai_editor

    brief = {"open_with": "the dock jump", "plan": {"summary": "Our lake trip.", "story": ["drive", "swim"],
                                                    "notes": ["no swearing"]}, "audience": "Family"}
    block = ai_editor.plan_block(brief)
    assert block.startswith("The owner's plan for this video (follow it")
    assert "What it is: Our lake trip." in block and "Open with: the dock jump" in block
    assert "The story in order: 1. drive; 2. swim" in block and "Also: no swearing" in block
    prompt = ai_editor.build_prompt([{"i": 0, "file": 1, "start": 1.0, "dur": 2.0, "text": "Hello there."}],
                                    brief, 1, 1)
    assert block in prompt and prompt.index(block) < prompt.index("For: Family")
    assert ai_editor.plan_block({}) == "" and len(ai_editor.plan_block({"plan": {"summary": "x" * 900}})) <= 700


# ------------------------------------------------------------------ the routes and the chat
def test_the_setup_routes(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    files = _files(env)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.post("/api/studio/videos/setup", headers=H,
                     json={"asset_ids": [f["id"] for f in files], "idea": "10 minutes, for my family", "mode": "ask",
                           "style_id": "settings", "remember": {"enabled": False}})
        assert r.status_code == 200, r.text
        vid = r.json()["id"]
        assert r.json()["plan"]["length_min"] == 10
        r = api.post(f"/api/studio/videos/{vid}/setup/say", headers=H, json={"text": "no music"})
        assert r.status_code == 200 and r.json()["setup"]["plan"]["music"] == "none"
        r = api.patch(f"/api/studio/videos/{vid}/setup", headers=H, json={"plan": {"feel": "calm"}})
        assert r.status_code == 200 and r.json()["locked"] == ["feel"]
        r = api.patch(f"/api/studio/videos/{vid}/setup", headers=H, json={"plan": {"feel": "loud"}})
        assert r.status_code == 200 and r.json()["plan"]["feel"] == ""  # not a choice: left to your style
        r = api.patch(f"/api/studio/videos/{vid}/setup", headers=H, json={"wrong": 1})
        assert r.status_code == 422
        assert api.get(f"/api/studio/videos/{vid}/setup", headers=H).json()["status"] == "draft"
        assert api.get(f"/api/studio/videos/{vid}", headers=H).json()["status"] == "draft"
        # more files join a draft (Add files) and the setup lists them
        extra = _asset(env, "beach.mp4", "video", 30)
        r = api.post(f"/api/studio/videos/{vid}/media", headers=H, json={"asset_ids": [extra["id"]]})
        assert r.status_code == 200, r.text
        shown = api.get(f"/api/studio/videos/{vid}/setup", headers=H).json()["files"]
        assert [f["id"] for f in shown][-1] == extra["id"] and shown[-1]["kind"] == "video"
        # the start page asks whether ClipForge AI has a model before anything is sent
        assert api.get("/api/studio/video-setup/model", headers=H).json() == {"ready": False, "label": "",
                                                                               "local": True, "brain": True}
        r = api.post(f"/api/studio/videos/{vid}/setup/build", headers=H, json={})
        assert r.status_code == 200 and r.json()["href"] == f"#/video/{vid}" and r.json()["status"] == "building"
        assert api.post(f"/api/studio/videos/{vid}/setup/build", headers=H, json={}).status_code == 409
        assert api.get("/api/studio/videos/vid-nope/setup", headers=H).status_code == 404
        assert api.post("/api/studio/videos/setup", headers=H, json={"asset_ids": []}).status_code == 422


def test_a_message_to_a_drafts_chat_from_anywhere_plans_it(env):
    from clipfoundry.brain import chat
    from clipfoundry.studio import video_setup

    if not hasattr(chat, "route"):
        pytest.skip("the assistant's chat routes come with the ClipForge AI assistant")
    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a vlog")
    first = v["open"][0]
    # a quick answer pressed in the ClipForge AI panel counts as the answer to that question, like on this page
    out = chat.send(WS, v["chat_id"], first["choices"][0])
    assert out["owner"]["data"]["answers"] == first["id"] and out["ai"]["data"]["tool"] == "plan"
    # in the chat's own shape, so the panel shows it like its own answers (the next quick answers from `ask`)
    assert out["owner"]["chat_id"] == out["ai"]["chat_id"] == v["chat_id"] and out["ai"]["updated_at"]
    left = video_setup.view(WS, v["id"])["open"]
    assert left and out["ai"]["data"]["ask"] == {"question": left[0]["q"], "choices": left[0]["choices"]}
    out = chat.send(WS, v["chat_id"], "make it 7 minutes")
    assert out["ai"]["data"]["tool"] == "plan" and video_setup.view(WS, v["id"])["plan"]["length_min"] == 7


def test_a_video_waiting_as_a_draft_that_was_not_planned_here_stays_its_own(env):
    """An animated short stopped before its first version waits with status "draft" too: its page, its chat and its
    Projects link are not taken over by the planning page."""
    from clipfoundry import db
    from clipfoundry.studio import routes, video_flow, video_setup

    now = time.time()
    db.insert("studio_projects", {"id": "vid-short", "workspace_id": WS, "name": "My short",
                                  "workflow": "animated_short", "status": "draft", "created_at": now,
                                  "updated_at": now})
    short = db.fetch("studio_projects", "vid-short")
    assert not video_setup.is_draft(short) and not video_setup._draft_chat({}, short)  # noqa: SLF001
    entry = [x for x in routes.library() if x["id"] == "vid-short"][0]
    assert entry["href"] == "#/video/vid-short"
    assert video_setup.view(WS, "vid-short")["planning"] is False
    assert video_flow.view(short)["planning"] is False
    with pytest.raises(video_setup.SetupError) as no:
        video_setup.say(WS, "vid-short", "make it 7 minutes")
    assert no.value.status == 409
    video_setup.stop(WS, "vid-short")  # nothing of its own to stop
    # a draft made here is one, and stops being one when it is built
    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a vlog")
    row = db.fetch("studio_projects", v["id"])
    assert video_setup.is_draft(row) and video_flow.view(row)["planning"] is True and v["planning"] is True
    video_setup.build(WS, WS, v["id"])
    row = db.fetch("studio_projects", v["id"])
    assert not video_setup.is_draft(row) and video_flow.view(row)["planning"] is False
    assert video_setup.view(WS, v["id"])["planning"] is False


# ------------------------------------------------------------------ stop, hand edits while it thinks, odd inputs
def _spy_answers(monkeypatch) -> threading.Event:
    """Set once a model's answer has been taken in (or turned away)."""
    from clipfoundry.studio import video_setup

    done = threading.Event()
    real = video_setup._apply

    def spy(*a, **k):
        try:
            return real(*a, **k)
        finally:
            if k.get("message_id"):
                done.set()

    monkeypatch.setattr(video_setup, "_apply", spy)
    return done


def _asked(fake: FakeModel, n: int = 1) -> None:
    end = time.time() + 5
    while len(fake.calls) < n and time.time() < end:
        time.sleep(0.01)
    assert len(fake.calls) >= n, "the model was never asked"


def test_stop_means_stop_even_when_the_answer_comes_late(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_setup

    files = _files(env)
    done = _spy_answers(monkeypatch)
    fake = _model(monkeypatch, {"say": "Here's a plan.", "plan": PLAN, "questions": []})
    fake.gate.clear()
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a 6 minute lake vlog")
    ai = _last_ai(v)
    _asked(fake)
    video_setup.stop(WS, v["id"])
    fake.gate.set()  # the model answers anyway, after Stop
    assert done.wait(5)
    row = db.fetch("brain_chat_messages", ai["id"])
    assert row["status"] == "done" and row["text"] == "(Stopped.)"
    v = video_setup.view(WS, v["id"])
    assert v["plan"] == video_setup.empty_plan() and v["name"] == "My video" and not v["planned"]
    video_setup.patch(WS, WS, v["id"], {"plan": {"feel": "calm"}})
    # Build after a stopped first answer: the built-in rules read what was said, the build job plans after listening
    out = video_setup.build(WS, WS, v["id"])
    row = db.fetch("studio_projects", v["id"])
    assert out["href"] == f"#/video/{v['id']}" and row["status"] == "building" and row["setup"]["pending"] is True
    assert row["brief"]["target_duration_s"] == 360 and row["brief"]["feel"] == "calm"
    # a part set by hand after the message stays, even when the message talked about it
    fake.gate.clear()
    done.clear()
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a 6 minute lake vlog")
    _asked(fake, 2)
    video_setup.stop(WS, v["id"])
    fake.gate.set()
    assert done.wait(5)
    v = video_setup.patch(WS, WS, v["id"], {"plan": {"length_min": 9}})
    assert not v["planned"]
    video_setup.build(WS, WS, v["id"])
    assert db.fetch("studio_projects", v["id"])["brief"]["target_duration_s"] == 540
    assert "listening to your files" in [m for m in video_setup.view(WS, v["id"])["messages"]
                                         if m["role"] == "ai"][-1]["text"]


def test_a_hand_edit_made_while_it_thinks_stays(env, monkeypatch):
    from clipfoundry.studio import video_setup

    files = _files(env)
    done = _spy_answers(monkeypatch)
    fake = _model(monkeypatch, {"say": "More energy!", "plan": PLAN, "questions": []})  # feel: energetic
    fake.gate.clear()
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a lake vlog, more energy")
    _asked(fake)
    v = video_setup.patch(WS, WS, v["id"], {"plan": {"feel": "calm", "length_min": 7}})  # after the message
    fake.gate.set()
    assert done.wait(5)
    _settled(_last_ai(v)["id"])
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["feel"] == "calm" and v["plan"]["length_min"] == 7 and {"feel", "length_min"} <= set(v["locked"])
    assert v["plan"]["title"] == "Lake Days"  # the rest of the answer is taken in


def test_what_a_stopped_message_said_counts_with_the_next_one(env, monkeypatch):
    from clipfoundry.studio import video_setup

    files = _files(env)
    done = _spy_answers(monkeypatch)
    fake = _model(monkeypatch, {"say": "A plan.", "plan": PLAN, "questions": []})  # feel: energetic
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a lake vlog")
    _settled(_last_ai(v)["id"])
    assert video_setup.view(WS, v["id"])["plan"]["feel"] == "energetic"
    fake.gate.clear()
    done.clear()
    fake.answers.append({"say": "Calmer.", "plan": {**PLAN, "feel": "calm"}, "questions": []})
    video_setup.say(WS, v["id"], "make it calm and slow")
    _asked(fake, 2)
    video_setup.stop(WS, v["id"])
    fake.gate.set()
    assert done.wait(5)
    assert video_setup.view(WS, v["id"])["plan"]["feel"] == "energetic"  # stopped: nothing changed
    # the next message is read with the stopped one: the model's answer (it saw both) and the rules' reading of both
    # count, though only the stopped one talked about the feel
    fake.answers.append({"say": "Calm and vertical.", "plan": {**PLAN, "feel": "calm", "aspect_ratio": "9:16"},
                         "questions": []})
    out = video_setup.say(WS, v["id"], "and make it vertical")
    _settled(out["ai"]["id"])
    p = video_setup.view(WS, v["id"])["plan"]
    assert p["feel"] == "calm" and p["aspect_ratio"] == "9:16"
    # with the rules alone too: a stopped message's words count when the next answer comes
    fake.gate.clear()
    done.clear()
    fake.answers.append({"say": "x", "plan": PLAN, "questions": []})
    video_setup.say(WS, v["id"], "no captions please")
    _asked(fake, 4)
    video_setup.stop(WS, v["id"])
    fake.gate.set()
    assert done.wait(5)
    monkeypatch.setattr(video_setup, "model_ready", lambda _settings: False)
    out = video_setup.say(WS, v["id"], "use some free music")
    p = video_setup.view(WS, v["id"])["plan"]
    assert out["ai"]["data"]["source"] == "rules" and p["captions"] == "off" and p["music"] == "library"


def test_hand_edits_stay_when_build_reads_stopped_messages(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    done = _spy_answers(monkeypatch)
    fake = _model(monkeypatch)
    fake.gate.clear()
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a calm lake vlog")
    _asked(fake)
    video_setup.stop(WS, v["id"])
    fake.gate.set()
    assert done.wait(5)
    video_setup.patch(WS, WS, v["id"], {"plan": {"feel": "energetic"}})  # after the message about the feel
    fake.gate.clear()
    done.clear()
    video_setup.say(WS, v["id"], "make it 6 minutes")  # a later message, not about the feel
    _asked(fake, 2)
    video_setup.stop(WS, v["id"])
    fake.gate.set()
    assert done.wait(5)
    video_setup.build(WS, WS, v["id"])
    row = db.fetch("studio_projects", v["id"])
    assert row["brief"]["feel"] == "energetic" and row["brief"]["target_duration_s"] == 360
    # the build job's plan keeps it too, though the model says calm
    fake.answers.append({"say": "Planned.", "plan": {**PLAN, "feel": "calm", "length_min": 6}, "questions": []})
    got = video_setup.plan_in_build(row, video_flow._assets(row), {}, db.get_settings(), Lease())
    assert got["setup"]["source"] == "ai" and got["brief"]["feel"] == "energetic"
    assert got["brief"]["target_duration_s"] == 360 and got["name"] == "Lake Days"


def test_a_quick_answer_lets_the_model_change_what_its_question_asked(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_setup

    files = _files(env)
    _model(monkeypatch, {"say": "A plan.", "plan": PLAN,
                         "questions": [{"q": "Should it open with the sunset instead?", "choices": ["Yes", "No"]}]},
           {"say": "Sunset first.", "plan": {**PLAN, "opening": "the sunset"}, "questions": []})
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask",
                          idea="a lake vlog, open with the dock jump")
    _settled(_last_ai(v)["id"])
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["opening"] == "the jump off the dock"
    out = video_setup.say(WS, v["id"], "Yes", v["open"][0]["id"])
    assert db.fetch("brain_chat_messages", out["owner"]["id"])["data"]["about"] == ["cold_open", "opening"]
    _settled(out["ai"]["id"])
    assert video_setup.view(WS, v["id"])["plan"]["opening"] == "the sunset"


def test_files_put_in_order_while_it_thinks_keep_that_order(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_setup

    files = _files(env)
    ids = [f["id"] for f in files]
    done = _spy_answers(monkeypatch)
    fake = _model(monkeypatch, {"say": "A plan.", "plan": PLAN, "questions": []})  # order: drive, dock jump, sunset
    fake.gate.clear()
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", idea="a lake vlog")
    _asked(fake)
    video_setup.patch(WS, WS, v["id"], {"asset_ids": [ids[2], ids[0], ids[1], ids[3]]})
    fake.gate.set()
    assert done.wait(5)
    _settled(_last_ai(v)["id"])
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["order"] == [] and "order" in v["locked"]
    # talking about the order later lets the model set it (by the files' numbers now: sunset, dock jump, drive), and
    # the plan's order is the order again
    fake.answers.append({"say": "Drive first.", "plan": {**PLAN, "order": [3, 2, 1]}, "questions": []})
    out = video_setup.say(WS, v["id"], "put the drive first, then the dock jump")
    _settled(out["ai"]["id"])
    v = video_setup.view(WS, v["id"])
    assert v["plan"]["order"] == [ids[1], ids[0], ids[2]]
    video_setup.build(WS, WS, v["id"])
    assert db.fetch("studio_projects", v["id"])["asset_ids"][:3] == [ids[1], ids[0], ids[2]]


def test_a_stopped_answer_is_never_sent(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.pipeline import llm
    from clipfoundry.studio import video_setup

    fake = _model(monkeypatch)
    monkeypatch.delattr(llm, "converse", raising=False)
    with pytest.raises(video_setup._Stop):
        video_setup.ask_model(db.get_settings(), "system", [], "plan this", [], timeout=5, cancel=lambda: True)
    assert fake.calls == []


def test_a_canceled_build_sends_nothing_more_and_counts_what_it_sent(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import jobs, video_flow, video_setup

    files = _files(env)
    fake = _model(monkeypatch, {"say": "Planned.", "plan": PLAN, "questions": []}, ollama_url="http://192.0.2.1:11434",
                  ai_edit_requests_per_day=1)

    class Gone(Lease):
        def __init__(self, gone=True):
            super().__init__()
            self.gone = gone

        def canceled(self):
            return self.gone

        def progress(self, frac, message=""):
            super().progress(frac, message)
            if self.gone:
                raise jobs.Canceled()

    def draft() -> dict:
        v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="auto", style_id="settings",
                              remember={"enabled": False}, idea="our lake trip, 6 minutes")
        return db.fetch("studio_projects", v["id"])

    # canceled before the request went out (it waited behind other answers): nothing is sent
    row = draft()
    lease = Gone()
    lease.progress = lambda *_a, **_k: None  # the job was canceled while this was queued
    with pytest.raises(jobs.Canceled):
        video_setup.plan_in_build(row, video_flow._assets(row), {}, db.get_settings(), lease)
    assert fake.calls == []
    # canceled while the request is out: it counts toward today's online limit
    row = draft()
    lease = Gone(gone=False)
    fake.gate.clear()
    raised = []

    def run():
        try:
            video_setup.plan_in_build(row, video_flow._assets(row), {}, db.get_settings(), lease)
        except jobs.Canceled as exc:
            raised.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    _asked(fake)
    lease.gone = True
    worker.join(10)
    fake.gate.set()
    assert raised and not worker.is_alive()
    stopped = [m for m in video_setup.view(WS, row["id"])["messages"] if m["text"] == "(Stopped.)"]
    assert stopped and stopped[0]["data"]["remote"] is True
    assert video_setup.limit_reached(WS, db.get_settings())


def test_odd_inputs_are_refused_not_errors(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    ids = [f["id"] for f in files]
    for bad in ({"enabled": "yes"}, {"name": 5}, {"other": 1}, ["x"]):
        with pytest.raises(video_setup.SetupError):
            video_setup.start(WS, WS, asset_ids=ids, mode="ask", idea="a vlog", remember=bad)
    for bad in ("v1", [1, 2], None):
        with pytest.raises(video_setup.SetupError):
            video_setup.start(WS, WS, asset_ids=bad, mode="ask")
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", remember={"enabled": True, "name": " Lake " * 30})
    assert len(db.fetch("studio_projects", v["id"])["setup"]["remember"]["name"]) <= 60
    for change in ({"asset_ids": "abc"}, {"asset_ids": [1]}, {"remember": {"name": ["x"]}}):
        with pytest.raises(video_setup.SetupError):
            video_setup.patch(WS, WS, v["id"], change)
    assert video_setup.clean_plan({"order": ["²", "9" * 40], "music": "mine", "music_file": "٣"}, [
        {"id": "x", "kind": "video", "filename": "a.mp4"}])["order"] == []
    # a file taken out and another added: the new set is listened to
    video_setup.patch(WS, WS, v["id"], {"asset_ids": [ids[0], ids[2], ids[3]]})
    extra = _asset(env, "extra.mp4", "video", 30)
    video_flow.add_media(v["id"], [extra["id"]])
    assert len(db.select("studio_jobs", "target_id = ? AND kind = 'video_media'", (v["id"],))) == 2


def test_a_failed_online_request_still_counts_toward_the_daily_limit(env, monkeypatch):
    from clipfoundry.pipeline import llm
    from clipfoundry.studio import video_setup

    files = _files(env)
    fake = _model(monkeypatch, llm.ProviderError("the server is down"), ollama_url="http://192.0.2.1:11434",
                  ai_edit_requests_per_day=1)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="a lake vlog")
    done = _settled(_last_ai(v)["id"])
    assert done["data"]["source"] == "rules" and done["data"]["remote"] is True and len(fake.calls) == 1
    out = video_setup.say(WS, v["id"], "make it 5 minutes")
    assert out["ai"]["status"] == "done" and "today's limit" in out["ai"]["data"]["say"] and len(fake.calls) == 1


def test_after_the_build_a_plan_change_keeps_your_choices_and_undo_brings_the_plan_back(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    files = _files(env)
    voice = _asset(env, "narration.m4a", "audio", 20)
    for f in files[:2]:
        _heard(f, _words(_lines(1.0, ["Here we are at the lake with the whole family today."])[0]))
    ids = [files[0]["id"], files[1]["id"], files[3]["id"], voice["id"]]
    v = video_setup.start(WS, WS, asset_ids=ids, mode="ask", style_id="settings", remember={"enabled": False},
                          idea="10 minutes, put summer song under it, narration.m4a is the voiceover")
    queued = []

    def fake_enqueue(ws, kind, target, rev=0, **_k):
        queued.append((kind, rev))
        return {"id": f"job-{kind}-{rev}"}

    monkeypatch.setattr(video_setup, "enqueue", fake_enqueue)
    monkeypatch.setattr(video_flow, "enqueue", fake_enqueue)
    video_setup.build(WS, WS, v["id"])
    row = db.fetch("studio_projects", v["id"])
    assert row["brief"]["music"] == "supplied" and row["brief"]["voiceover_asset_ids"] == [voice["id"]]
    plan = video_flow.rough_cut(row, video_flow._assets(row), {})
    assert {i["role"] for i in plan["audio"] if i.get("brief")} == {"music", "voiceover"}
    video_flow.save_revision(v["id"], plan, "Rough cut from your brief", None, {"action": "build", "prev": None,
                                                                                "redo": None})
    video_setup.edited(v["id"], 1)
    # on the editor page the owner turned ClipForge AI's reading off and chose a calm feel
    db.update("studio_projects", v["id"], brief={**row["brief"], "ai_edit": False, "feel": "calm"})
    with pytest.raises(video_setup.SetupError):  # looked for when the video is built
        video_setup.change_plan(WS, WS, v["id"], 1, {"find_media": "auto"})
    video_setup.change_plan(WS, WS, v["id"], 1, {"music": "none", "voiceover_files": [], "length_min": 5,
                                                 "order": [files[1]["id"], files[0]["id"]]})
    row = db.fetch("studio_projects", v["id"])
    b = row["brief"]
    assert b["ai_edit"] is False and b["feel"] == "calm"  # your choices on the editor page stay
    assert b["music"] == "none" and "music_asset_id" not in b and "voiceover_asset_ids" not in b
    assert b["target_duration_s"] == 300 and row["asset_ids"][:2] == [files[1]["id"], files[0]["id"]]
    video_flow.smart_job({"target_id": v["id"], "revision": 1}, _Lease())
    new = video_flow.plan_at(v["id"], 2)
    assert not any(i["role"] in ("music", "voiceover") for i in new["audio"])  # the plan's sounds went with it
    assert [c["asset_id"] for c in new["clips"] if c["kind"] == "video"][0] == files[1]["id"]
    # Undo brings the plan back, with the brief it set; your editor choices still stay
    video_flow.undo(v["id"], 2)
    row = db.fetch("studio_projects", v["id"])
    assert row["setup"]["plan"]["music"] == "mine" and row["setup"]["plan"]["length_min"] == 10
    assert row["brief"]["music"] == "supplied" and row["brief"]["target_duration_s"] == 600
    assert row["brief"]["ai_edit"] is False and row["brief"]["feel"] == "calm"
    # a plan change whose edit fails goes back, look and all
    rev = row["plan_revision"]
    video_setup.change_plan(WS, WS, v["id"], rev, {"captions": "off", "aspect_ratio": "9:16"})
    assert db.fetch("studio_projects", v["id"])["setup"]["look"] == {"aspect": "9:16", "captions": False}

    def broken(*_a, **_k):
        raise video_flow.VideoError("the edit broke")

    monkeypatch.setattr(video_flow, "rough_cut", broken)
    with pytest.raises(video_flow.VideoError):
        video_flow.smart_job({"target_id": v["id"], "revision": rev}, _Lease())
    row = db.fetch("studio_projects", v["id"])
    assert row["setup"]["plan"]["captions"] == "" and row["setup"]["plan"]["aspect_ratio"] == ""
    assert row["setup"]["look"] == {} and "captions" not in row["brief"] and row["setup"]["change"] == {}


def _speech(asset: dict, parts: int = 12) -> None:
    lines = [f"Here is part {k} of our day at the lake with the whole family." for k in range(parts)]
    _heard(asset, _words(_lines(1.0, lines, gap=1.2)[0]))


def _built(env, monkeypatch, idea: str, *files: dict, jobs: bool = False) -> str:
    """A video planned from `idea` with these files (videos with made-up speech) and made by the build job. Jobs it
    starts are only noted, unless `jobs` (then they are real rows the test runs or cancels)."""
    from test_studio_smart_edit import _Lease

    from clipfoundry import db
    from clipfoundry.studio import library, video_flow, video_setup

    made: dict = {}

    def library_asset(_ws, key):  # ClipForge's own music and sound effects, without making them
        if key not in made:
            made[key] = _asset(env, library.filename(key), "audio", 0.9 if key in library.EFFECTS else 50)
        return made[key]

    monkeypatch.setattr(library, "asset", library_asset)
    if not jobs:
        def noted(_ws, kind, _target, rev=0, **_k):
            return {"id": f"job-{kind}-{rev}"}

        monkeypatch.setattr(video_setup, "enqueue", noted)
        monkeypatch.setattr(video_flow, "enqueue", noted)
    for f in files:
        if f["kind"] == "video":
            _speech(f)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", style_id="settings",
                          remember={"enabled": False}, idea=idea)
    video_setup.build(WS, WS, v["id"])
    video_flow.build({"target_id": v["id"], "revision": 0}, _Lease())
    assert db.fetch("studio_projects", v["id"])["plan_revision"] == 1
    return v["id"]


def test_undo_and_a_failed_plan_change_bring_back_what_the_next_edit_uses(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    clips = [_asset(env, "clip0.mp4", "video", 120), _asset(env, "clip1.mp4", "video", 120)]
    vid = _built(env, monkeypatch, "A 10 minute lake vlog, no sound effects", *clips)

    def row():
        return db.fetch("studio_projects", vid)

    def used():  # the length and feel the next edit fits to
        return row()["guidance"]["values"]

    assert used()["target_duration_s"] == 600
    video_flow.smart_again(vid, 1, {"music": "none"})  # a choice on the editor page (v2)...
    video_flow.smart_job({"target_id": vid, "revision": 1}, _Lease())
    video_setup.change_plan(WS, WS, vid, 2, {"length_min": 5, "music": "library"})  # ...a plan change over it (v3)
    video_flow.smart_job({"target_id": vid, "revision": 2}, _Lease())
    assert used()["target_duration_s"] == 300 and row()["brief"]["music"] == "library"
    video_flow.undo(vid, 3)  # v4 is v2 again: its plan, the brief values it was made with, and what the edits use
    assert row()["setup"]["plan"]["length_min"] == 10 and row()["brief"]["target_duration_s"] == 600
    assert row()["brief"]["music"] == "none" and used()["target_duration_s"] == 600
    video_flow.redo(vid, 4)  # v5 is v3 again
    assert row()["setup"]["plan"]["length_min"] == 5 and used()["target_duration_s"] == 300
    video_flow.undo(vid, 5)
    # a plan change whose edit fails puts back the guidance too, not only the plan and the brief
    before = used()
    video_setup.change_plan(WS, WS, vid, 6, {"length_min": 5, "feel": "energetic"})
    assert used()["target_duration_s"] == 300

    def broken(*_a, **_k):
        raise video_flow.VideoError("the edit broke")

    monkeypatch.setattr(video_flow, "rough_cut", broken)
    with pytest.raises(video_flow.VideoError):
        video_flow.smart_job({"target_id": vid, "revision": 6}, _Lease())
    assert used() == before and row()["setup"]["plan"]["feel"] == "" and "feel" not in row()["brief"]


def test_undo_while_a_plan_change_waits_keeps_the_version_you_went_back_to(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    clips = [_asset(env, "clip0.mp4", "video", 120), _asset(env, "clip1.mp4", "video", 120)]
    vid = _built(env, monkeypatch, "A 10 minute lake vlog, no music, no sound effects", *clips)
    video_setup.change_plan(WS, WS, vid, 1, {"length_min": 5})
    video_flow.smart_job({"target_id": vid, "revision": 1}, _Lease())  # v2: 5 minutes
    video_setup.change_plan(WS, WS, vid, 2, {"length_min": 3})  # its edit waits its turn...
    video_flow.undo(vid, 2)  # ...while you undo to the 10 minute version (v3)
    with pytest.raises(video_flow.VideoError):  # the video changed: that edit changes nothing
        video_flow.smart_job({"target_id": vid, "revision": 2}, _Lease())
    row = db.fetch("studio_projects", vid)
    assert row["plan_revision"] == 3 and row["setup"]["plan"]["length_min"] == 10
    assert row["brief"]["target_duration_s"] == 600 and row["guidance"]["values"]["target_duration_s"] == 600
    assert row["setup"]["change"] == {}


def test_a_plan_change_canceled_before_its_edit_runs_goes_back(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import jobs as studio_jobs, video_flow, video_setup

    clips = [_asset(env, "clip0.mp4", "video", 120), _asset(env, "clip1.mp4", "video", 120)]
    vid = _built(env, monkeypatch, "A 10 minute lake vlog, no music, no sound effects", *clips, jobs=True)

    def plan():
        row = db.fetch("studio_projects", vid)
        return row["setup"]["plan"]["length_min"], row["brief"]["target_duration_s"], \
            row["guidance"]["values"]["target_duration_s"]

    out = video_setup.change_plan(WS, WS, vid, 1, {"length_min": 5})
    assert plan() == (5, 300, 300)
    assert studio_jobs.cancel(out["job"])  # Cancel on the editor page, before the edit started
    studio_jobs.run(out["job"])  # the worker reaches it: nothing runs
    assert plan() == (10, 600, 600) and db.fetch("studio_projects", vid)["plan_revision"] == 1
    # canceled while it runs: the edit puts the plan back itself as it stops
    out = video_setup.change_plan(WS, WS, vid, 1, {"length_min": 5})
    lease = studio_jobs.claim(out["job"])
    assert lease is not None and studio_jobs.cancel(out["job"])
    assert plan() == (5, 300, 300)
    with pytest.raises(studio_jobs.Canceled):
        video_flow.smart_job(db.fetch("studio_jobs", out["job"]), lease)
    assert plan() == (10, 600, 600) and db.fetch("studio_projects", vid)["setup"]["change"] == {}


def test_undo_and_a_failed_edit_bring_back_the_order_of_the_files(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry import db
    from clipfoundry.studio import video_flow, video_setup

    a, b = _asset(env, "clip0.mp4", "video", 120), _asset(env, "clip1.mp4", "video", 120)
    vid = _built(env, monkeypatch, "A lake vlog, no music, no sound effects", a, b)

    def first(rev):
        return next(c["asset_id"] for c in video_flow.plan_at(vid, rev)["clips"] if c.get("include", True))

    def bin_order():
        return db.fetch("studio_projects", vid)["asset_ids"]

    assert first(1) == a["id"]
    video_setup.change_plan(WS, WS, vid, 1, {"order": [b["id"], a["id"]]})
    video_flow.smart_job({"target_id": vid, "revision": 1}, _Lease())
    assert first(2) == b["id"]
    video_flow.undo(vid, 2)
    assert db.fetch("studio_projects", vid)["setup"]["plan"]["order"] == [] and bin_order() == [a["id"], b["id"]]
    video_flow.smart_again(vid, 3, {"smart_edit": "smart"})  # the next edit plays them in that order again
    video_flow.smart_job({"target_id": vid, "revision": 3}, _Lease())
    assert first(4) == a["id"]
    # a plan change whose edit added ClipForge's sound effects to the files, then failed: the order goes back
    video_setup.change_plan(WS, WS, vid, 4, {"order": [b["id"], a["id"]], "sound_effects": "on"})
    real = video_flow.prepare_smart

    def then_a_hand_edit(*args, **kw):
        out = real(*args, **kw)
        video_flow.edit(vid, 4, {"op": "set", "field": "caption_size", "value": "large"})
        return out

    monkeypatch.setattr(video_flow, "prepare_smart", then_a_hand_edit)
    with pytest.raises(video_flow.VideoError):
        video_flow.smart_job({"target_id": vid, "revision": 4}, _Lease())
    assert bin_order()[:2] == [a["id"], b["id"]] and len(bin_order()) > 2  # the effects stay, after your files


def test_sounds_you_changed_by_hand_are_not_doubled_dropped_or_set_back(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry.studio import video_flow

    clip = _asset(env, "clip0.mp4", "video", 120)
    voice, song = _asset(env, "narration.m4a", "audio", 20), _asset(env, "summer song.mp3", "audio", 210)
    outro = _asset(env, "outro tune.mp3", "audio", 30)
    vid = _built(env, monkeypatch, "A lake vlog. Put summer song under it, narration.m4a is the voiceover, no sound "
                 "effects", clip, voice, song, outro)

    def sounds(rev):
        return sorted((i["label"], i["role"], i["gain_db"]) for i in video_flow.plan_at(vid, rev)["audio"])

    level = next(i["gain_db"] for i in video_flow.plan_at(vid, 1)["audio"] if i["role"] == "music")
    assert sounds(1) == [("narration.m4a", "voiceover", 0.0), ("summer song.mp3", "music", level)]
    narration = next(i["id"] for i in video_flow.plan_at(vid, 1)["audio"] if i["role"] == "voiceover")
    # the voiceover moved to the effects track, and a second song on the music track, both by hand
    video_flow.edit(vid, 1, {"op": "audio_set", "audio_id": narration, "field": "role", "value": "effect"})
    video_flow.edit(vid, 2, {"op": "add_audio", "asset_id": outro["id"], "role": "music", "start_ms": 0})
    video_flow.smart_again(vid, 3, {"smart_edit": "tight"})
    video_flow.smart_job({"target_id": vid, "revision": 3}, _Lease())
    hand = next(i["gain_db"] for i in video_flow.plan_at(vid, 4)["audio"] if i["label"] == "outro tune.mp3")
    assert sounds(4) == sorted([("narration.m4a", "effect", 0.0), ("outro tune.mp3", "music", hand),
                                ("summer song.mp3", "music", level)])  # once each; the plan's song stays
    # "make the music quieter": the level you set stays through the next edit
    video_flow.edit(vid, 4, {"op": "set", "field": "music_level_db", "value": -24})
    video_flow.smart_again(vid, 5, {"smart_edit": "smart"})
    video_flow.smart_job({"target_id": vid, "revision": 5}, _Lease())
    assert sounds(6) == sorted([("narration.m4a", "effect", 0.0), ("outro tune.mp3", "music", -24.0),
                                ("summer song.mp3", "music", -24.0)])


def test_a_video_made_without_a_plan_keeps_its_sounds_as_you_left_them(env, monkeypatch):
    from test_studio_smart_edit import _Lease

    from clipfoundry.studio import video_flow

    clip, voice = _asset(env, "clip0.mp4", "video", 120), _asset(env, "narration.m4a", "audio", 20)
    _speech(clip)

    def noted(_ws, kind, _target, rev=0, **_k):
        return {"id": f"job-{kind}-{rev}"}

    monkeypatch.setattr(video_flow, "enqueue", noted)
    p = video_flow.create(WS, WS, name="Lake day", asset_ids=[clip["id"], voice["id"]],
                          brief={"smart_edit": "smart", "music": "none", "sound_effects": False,
                                 "voiceover_asset_ids": [voice["id"]]}, style_id="settings",
                          remember={"enabled": False})
    video_flow.build({"target_id": p["id"], "revision": 0}, _Lease())
    placed = video_flow.plan_at(p["id"], 1)["audio"]
    assert [i["role"] for i in placed] == ["voiceover"] and not placed[0].get("brief")
    video_flow.edit(p["id"], 1, {"op": "audio_remove", "audio_id": placed[0]["id"]})
    video_flow.smart_again(p["id"], 2, {"smart_edit": "tight"})
    video_flow.smart_job({"target_id": p["id"], "revision": 2}, _Lease())
    assert video_flow.plan_at(p["id"], 3)["audio"] == []  # taken out by hand, it stays out


def test_going_back_finds_the_plan_past_any_number_of_hand_edits(monkeypatch):
    from clipfoundry.studio import video_flow, video_setup

    rows = {r: {"prev": r - 1} for r in range(2, 300)}  # 298 hand edits after the version the plan made
    monkeypatch.setattr(video_flow, "_revision_row", lambda _project, r: rows[r])
    monkeypatch.setattr(video_flow, "_meta", lambda row: row)
    plan = {"length_min": 10}
    assert video_setup._plan_of("p", 299, {"1": plan}) == ("1", plan)
    rows[150] = {"prev": 150}  # a loop in the history ends the walk
    assert video_setup._plan_of("p", 299, {"1": plan}) is None


def test_plan_words_are_only_for_videos_with_a_plan():
    from clipfoundry.studio import smart_edit

    assert smart_edit.plan_words({"must_keep": "soup"}) == set()  # made the old way: ranks as it always did
    assert smart_edit.plan_words({"open_with": "the ravens", "must_keep": "soup"}) == {"ravens", "soup"}


def test_a_video_deleted_while_its_answer_is_written_gets_no_new_chat(env, monkeypatch):
    """Deleting a video being planned removes its planning chat. If the delete lands while an answer is being
    written, between reading the video and reading its chat, the answer stops: it never makes a new, empty chat for
    the deleted video."""
    from clipfoundry import db
    from clipfoundry.brain import chat as chat_mod
    from clipfoundry.studio import video_setup

    files = _files(env)
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask")
    chat = video_setup._chat(WS, v["id"])
    owner = video_setup._add(chat, "owner", "make it calm")
    ai = video_setup._add(chat, "ai", "", status="thinking")
    real_select, armed = db.select, [True]

    def deleted_meanwhile(table, *a, **k):
        if table == "brain_chats" and armed:
            armed.clear()
            with db.connect() as conn:  # what deleting the video does, in one step
                conn.execute("DELETE FROM brain_chat_messages WHERE chat_id = ?", (chat["id"],))
                conn.execute("DELETE FROM brain_chats WHERE project_id = ?", (v["id"],))
                conn.execute("DELETE FROM studio_projects WHERE id = ?", (v["id"],))
        return real_select(table, *a, **k)

    monkeypatch.setattr(chat_mod.db, "select", deleted_meanwhile)
    video_setup._think(v["id"], ai["id"], owner["id"], False)
    assert not armed  # the delete landed where the answer read the chat
    assert not real_select("brain_chats", "project_id = ?", (v["id"],))
    with pytest.raises(chat_mod.ChatError):  # also a page that opens the chat of a video deleted meanwhile
        armed.append(True)
        chat_mod.open_chat(WS, v["id"])
