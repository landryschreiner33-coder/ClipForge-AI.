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
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="ask", idea="Our lake trip, about 10 minutes")
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
    # the model's plan, checked; the owner's explicit "10 minute" wins over its 8; files named by number became ids
    assert v["plan"]["length_min"] == 10 and v["plan"]["opening"] == "the jump off the dock"
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
    fake = _model(monkeypatch, {"say": "Planned: a lake vlog.", "plan": PLAN, "questions": [{"q": "?", "choices": []}]})
    v = video_setup.start(WS, WS, asset_ids=[f["id"] for f in files], mode="auto", style_id="settings",
                          remember={"enabled": False}, idea="our lake trip, 6 minutes, no captions")
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
    assert b["target_duration_s"] == 360 and b["captions"] is False  # what was said wins
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
                                                                               "local": True}
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
    db.insert("studio_projects", {"id": "vid-short", "workspace_id": WS, "name": "My short", "workflow": "animated_short",
                                  "status": "draft", "created_at": now, "updated_at": now})
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
