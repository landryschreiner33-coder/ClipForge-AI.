"""Guards for a small model (docs/clipforge/CLIPFORGE_AI.md, "Guards for a small model"; brain/intents.py): what the
real Basic model did on GitHub's machines on Nov 26 2026 never reaches the owner as the answer: repeating the owner's
message, "Let me look." without looking, "Here are your projects:" with none of them, "[Script writer] …" instead of
asking the Script writer. A fake model replays those slips; nothing leaves the computer."""
from __future__ import annotations

import time

import pytest
from fake_model import WS, FakeModel, answers_finish, install, say, settled  # noqa: F401


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _think(tool_list: list, text: str, **kw):
    from clipfoundry import db
    from clipfoundry.brain import assistant
    from clipfoundry.brain.tools import Ctx

    ctx = kw.pop("ctx", None) or Ctx(ws=WS, deadline=time.monotonic() + 60)
    return assistant.think(db.get_settings(), "SYSTEM", [{"role": "user", "content": text}], tool_list, ctx,
                           said=text, **kw)


def _tools(*names: str) -> list:
    from clipfoundry.brain import tools

    return [tools.get(n) for n in names]


def _ask(text: str, *answers) -> tuple[dict, FakeModel]:
    """`text` sent in a new general chat, answered by a fake model from `answers`; the finished message."""
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    m = chat.send(WS, c["id"], text)["ai"]
    return settled(c["id"], m["id"]), c


# ------------------------------------------------------------------ reading the owner's words
def test_echo_promise_and_an_answer_that_stops_at_a_colon():
    from clipfoundry.brain import intents

    assert intents.echo("Hi! How are you today?", "Hi! How are you today?")
    assert intents.echo("@Script writer, write a hook for my video", "@Script writer write a hook for my video.")
    assert intents.echo("ok", "OK!") and not intents.echo("Thanks!", "thanks a lot")
    assert not intents.echo("I'm well, thanks! How can I help with your videos?", "Hi! How are you today?")
    for s in ("Let me look.", "I'll check for the project “Old gear review”.", "One moment, I'll look that up",
              "Let me ask the Script writer."):
        assert intents.promise(s), s
    for s in ("Let me know if you want more.", "Can I look at it?", "I can't find that project.",
              "You have 3 projects. " + "x" * 300, "I'll be honest: the hook is too slow.",
              # the review's answers that are answers (Nov 26)
              "Try “Ridge Rider”, “Downhill Dreams” or “Wheels Up”. Let me know if you want me to find more.",
              "Let's get you a title: “Ride the Ridge”.", "I'll be honest: the hook is weak, see if you can open on it",
              "Got it — from now on I will ask you before anything is posted.", "Let me look. You have 3 projects.",
              "Let me check: you have “Hike day” and “Lake swim”."):
        assert not intents.promise(s), s
    assert intents.stops_short("Here are your projects:") and not intents.stops_short("You have 2 projects.")


def test_a_helper_asked_by_name_is_found_only_when_it_is_switched_on(data):
    from clipfoundry.brain import agents, intents

    writer = agents.add(WS, template="script_writer")
    agents.add(WS, template="critic", enabled=False)
    found = intents.handoff(WS, "Ask the script writer for a title for my biking video")
    assert found and found[0]["id"] == writer["id"]
    assert found[1] == "The owner asked: “Ask the script writer for a title for my biking video”. Do that job now, " \
                       "completely."
    assert intents.handoff(WS, "can you get my Script Writer to write a hook?")[0]["id"] == writer["id"]
    assert intents.handoff(WS, "Ask the critic to review my hook") is None  # switched off
    assert intents.handoff(WS, "Ask the script writers union about rates") is None  # not the helper's name
    assert intents.handoff(WS, "What would the script writer say?") is None


def test_a_plainly_phrased_request_has_one_tool_call(data):
    from clipfoundry import db
    from clipfoundry.brain import intents

    for name in ("Old gear review", "Lake swim", "Hike day", "Music festival vlog"):
        db.create_project(name, workspace_id=WS, status="ready")
    every = {"results", "find_projects", "posts", "work", "missions", "delete_project", "rename_project",
             "make_clips"}
    g = lambda t: intents.guess(t, every, WS)  # noqa: E731
    assert g("How are my clips doing?") == {"tool": "results", "args": {}}
    assert g("what projects do I have?") == {"tool": "find_projects", "args": {}}
    assert g("show me my upcoming posts") == {"tool": "posts", "args": {}}
    assert g("is anything stuck?") == {"tool": "work", "args": {}}
    assert g("list my missions") == {"tool": "missions", "args": {}}
    assert g("Delete the project Old gear review") == {"tool": "delete_project", "args": {"project": "Old gear review"}}
    assert g("delete video “Lake swim”.") == {"tool": "delete_project",
                                              "args": {"project": "Lake swim", "kind": "full_video"}}
    assert g("rename Hike day to Summit push") == {"tool": "rename_project",
                                                   "args": {"project": "Hike day", "name": "Summit push"}}
    assert g("make clips from https://youtu.be/abc123") == {"tool": "make_clips",
                                                            "args": {"link": "https://youtu.be/abc123"}}
    assert g("https://youtu.be/abc123") == {"tool": "make_clips", "args": {"link": "https://youtu.be/abc123"}}
    assert g("please clip this video: https://youtu.be/q") == {"tool": "make_clips",
                                                               "args": {"link": "https://youtu.be/q"}}
    for t in ("should I delete the project Old gear review?", "what is this? https://youtu.be/abc",
              "how do I make my hooks better", "delete the intro of my video please", "",
              # the review's misreads (Nov 26): never a guess
              "Don't make clips from https://youtu.be/abc123", "I already made clips from https://youtu.be/abc, great",
              "Here is my latest short https://youtube.com/shorts/xyz, tell me what you think.",
              "Remove the video background music", "remove my video from TikTok", "Delete the video intro",
              "Rename this video to something catchier", "rename Hike day to Summer hike, then post it to TikTok",
              "rename the second clip to Big jump", "my results are bad, help me write better hooks",
              "My views dropped, what should I change in my hooks?", "What's working for my channel?"):
        assert g(t) is None, t
    assert intents.guess("what projects do I have?", {"posts"}) is None  # only tools this chat offers
    assert intents.guess("Delete the project Old gear review", every) is None  # no workspace: no project to check


# ------------------------------------------------------------------ the rounds of one answer
def test_an_echo_is_never_the_answer_the_model_is_asked_once_more(data, monkeypatch):
    from clipfoundry.brain import assistant

    fake = install(monkeypatch, say("Hi! How are you today?"), say("I'm doing well! What are we making today?"))
    out = _think(_tools("find_projects"), "Hi! How are you today?")
    assert out.text == "I'm doing well! What are we making today?" and out.rounds == 2
    assert fake.last_user(1) == assistant.NUDGE_ECHO and out.slips == ["echo"]
    # asked once only: a second echo is not shown either, and nothing else is asked
    fake = install(monkeypatch, say("Hi! How are you today?"), say("Hi! How are you today?"), say("never asked"))
    out = _think(_tools("find_projects"), "Hi! How are you today?")
    assert len(fake.calls) == 2 and out.text == "Hi! How are you today?"  # its own words: the only answer it gave


def test_let_me_look_without_looking_uses_the_plain_reading_or_is_asked_to_look(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.brain import assistant, intents

    db.create_project("Hike day", workspace_id=WS, status="ready")
    db.create_project("Lake swim", workspace_id=WS, status="ready")
    said = "what projects do I have?"
    fake = install(monkeypatch, say("Let me look."), say("Here are your projects:"))
    out = _think(_tools("find_projects"), said, fallback=intents.guess(said, {"find_projects"}))
    assert [s["tool"] for s in out.steps] == ["find_projects"] and len(fake.calls) == 2
    assert out.text.startswith("Here are your projects:\n\n- “Lake swim” — clips project") and "“Hike day”" in out.text
    assert "Let me look" not in out.text and out.slips == ["act", "fallback:find_projects", "short",
                                                           "show:find_projects"]
    # without a plain reading it is asked to use its tool
    fake = install(monkeypatch, say("Let me check."), say("", ("find_projects", {})),
                   say("You have “Hike day” and “Lake swim”."))
    out = _think(_tools("find_projects"), "anything I should finish?")
    assert fake.last_user(1) == assistant.NUDGE_ACT and out.text == "You have “Hike day” and “Lake swim”."
    # a list that stops at its colon, without any tool: asked to write it on one line
    fake = install(monkeypatch, say("Your projects are:"), say("Hike day; Lake swim."))
    out = _think([], "name my projects in one go")
    assert fake.last_user(1) == assistant.NUDGE_SHORT and out.text == "Hike day; Lake swim."


def test_a_listing_the_answer_leaves_out_is_added_and_one_it_gives_is_not(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.brain import intents

    for name in ("Hike day", "Lake swim", "Trail build"):
        db.create_project(name, workspace_id=WS, status="ready")
    said = "list my projects"
    plain = intents.guess(said, {"find_projects"})
    install(monkeypatch, say("", ("find_projects", {})), say("You have 3 projects, mostly outdoors."))
    out = _think(_tools("find_projects"), said, fallback=plain)
    assert out.text.startswith("You have 3 projects, mostly outdoors.\n\nLooked at your projects (3):\n- “")
    assert all(f"“{n}”" in out.text for n in ("Hike day", "Lake swim", "Trail build"))
    install(monkeypatch, say("", ("find_projects", {})), say("“Hike day”, “Lake swim” and “Trail build”."))
    out = _think(_tools("find_projects"), said, fallback=plain)
    assert out.text == "“Hike day”, “Lake swim” and “Trail build”." and out.slips == []
    # a look the model used for its own answer (memories it read) is not listed
    install(monkeypatch, say("", ("find_projects", {})), say("Finish the trail one first: it is nearly done."))
    out = _think(_tools("find_projects"), "which one should I finish first?")
    assert out.text == "Finish the trail one first: it is nearly done."


def test_a_bracketed_helper_name_is_not_clipforge_ais_words(data, monkeypatch):
    install(monkeypatch, say("[Script writer] Ask for a title: “Biking the ridge”."))
    out = _think([], "a title for my biking video?")
    assert out.text == "Ask for a title: “Biking the ridge”."


# ------------------------------------------------------------------ whole turns in the chat
def test_how_are_my_clips_doing_reads_the_results_even_when_the_model_does_not(data, monkeypatch):
    from test_assistant_results import post

    post("tiktok", 2500, "Rage quit")
    fake = install(monkeypatch, say("Let me look."), say("Here is how they did:"))
    m, _c = _ask("How are my clips doing?")
    assert m["status"] == "done" and "“Rage quit”" in m["text"] and not m["text"].startswith("Let me look")
    assert [s["tool"] for s in m["data"]["steps"]] == ["results"]
    # the results are read before the model's first round: one round, and the app's own lines when it only promises
    assert m["data"]["guards"] == ["first:results", "act", "show:results"] and len(fake.calls) == 1
    assert "results: " in fake.last_user(0) and "Rage quit" in fake.last_user(0)


def test_a_look_the_model_asks_for_again_is_not_run_twice(data, monkeypatch):
    from clipfoundry import db

    db.create_project("Hike day", workspace_id=WS, status="ready")
    fake = install(monkeypatch, say("", ("find_projects", {})), say("You have one: “Hike day”."))
    m, _c = _ask("what projects do I have?")
    assert [s["tool"] for s in m["data"]["steps"]] == ["find_projects"] and m["text"] == "You have one: “Hike day”."
    assert m["data"]["guards"] == ["first:find_projects"] and len(fake.calls) == 2
    assert "find_projects: " in fake.last_user(1)  # the same result again, not a second run


def test_an_answer_of_sentences_that_only_say_what_it_will_do_is_a_promise():
    from clipfoundry.brain import intents

    for words in ("I'll delete the project 'Old gear review'. First, I'll check if it's ready for deletion. Let me "
                  "look at it.",
                  "I'll write a two-line hook about mountain biking. Let me think of a strong opening line that grabs "
                  "attention and leads into the topic.",
                  "I'm ready to help you with that. Let me ask the script writer for a title.",
                  "Sure! Let me look at your projects. Let me know if you need more."):
        assert intents.promise(words), words
    for words in ("Got it: your channel is about mountain biking. I'll save this rule for future reference.",
                  "I can see you have 3 projects.", "Got it! I'll make sure to never use red captions.",
                  "Your channel is about mountain biking. I remember that rule now.", "I'll write it: “Send it”",
                  "The script writer has been asked to create a title. I'll now provide the results.",
                  "Let me look. Here are your projects: Hike day, Lake swim.", "Which one should I delete?"):
        assert not intents.promise(words), words


def test_delete_the_project_shows_its_card_when_the_model_only_talks_about_it(data, monkeypatch):
    from clipfoundry import db

    p = db.create_project("Old gear review", workspace_id=WS, status="ready")
    # the real Basic model's answer (check run 45777094657): three sentences of what it will do, no tool
    install(monkeypatch, say("I'll delete the project 'Old gear review'. First, I'll check if it's ready for "
                             "deletion. Let me look at it."))
    m, _c = _ask("Delete the project Old gear review")
    assert [c["tool"] for c in m["data"]["pending"]] == ["delete_project"] and m["data"]["pending"][0]["state"] == \
        "waiting" and m["data"]["guards"] == ["act", "fallback:delete_project"]
    # one that claims it is done is no answer either: the card shows, and the claim does not
    install(monkeypatch, say("Done! I deleted “Old gear review”."))
    m, _c = _ask("Delete the project Old gear review")
    assert m["data"]["pending"][0]["state"] == "waiting" and "Done!" not in m["text"]
    assert m["data"]["guards"] == ["fallback:delete_project"] and db.get_project(p["id"]) is not None


def test_a_helper_that_only_says_what_it_will_write_is_asked_to_write_it(data, monkeypatch):
    from clipfoundry.brain import agents, assistant

    agents.add(WS, template="script_writer")
    fake = install(monkeypatch, say("I'll write a two-line hook about mountain biking. Let me think of a strong "
                                    "opening line."), say("“I almost didn't make it down.” / “Here's why.”"))
    m, _c = _ask("@Script writer write a two-line hook about mountain biking")
    assert m["role"] == "agent" and m["text"] == "“I almost didn't make it down.” / “Here's why.”"
    assert fake.last_user(1) == assistant.NUDGE_DO and m["data"]["guards"] == ["act"]
    # after looking something up, too: reading is not the job
    fake = install(monkeypatch, say("", ("recall", {"words": "mountain biking"})),
                   say("I'm ready to help you with that. Let me ask the script writer for a title."),
                   say("Title: “The ridge at dawn”."))
    m, _c = _ask("@Script writer a title for my biking video")
    assert m["text"] == "Title: “The ridge at dawn”." and fake.last_user(2) == assistant.NUDGE_DO


def test_delete_the_project_shows_its_card_when_the_model_only_says_it_will_look(data, monkeypatch):
    from clipfoundry import db

    p = db.create_project("Old gear review", workspace_id=WS, status="ready")
    install(monkeypatch, say("Let me look."))
    m, _c = _ask("Delete the project Old gear review")
    card = m["data"]["pending"]
    assert len(card) == 1 and card[0]["tool"] == "delete_project" and card[0]["state"] == "waiting"
    assert "Old gear review" in card[0]["label"] and m["data"]["guards"] == ["act", "fallback:delete_project"]
    assert db.get_project(p["id"]) is not None  # deleting always waits for the OK


def test_ask_the_script_writer_hands_the_job_over_and_reviews_its_work(data, monkeypatch):
    from clipfoundry.brain import agents, assistant

    agents.add(WS, template="script_writer")
    fake = install(monkeypatch, say("Title: “I rode the ridge at dawn”."),
                   say("The Script writer suggests “I rode the ridge at dawn”: short and visual."))
    m, _c = _ask("Ask the script writer for a title for my biking video")
    assert m["status"] == "done" and m["text"] == "The Script writer suggests “I rode the ridge at dawn”: short " \
                                                  "and visual."
    assert m["data"]["steps"][0] == {"tool": "ask_agent", "label": "Asked Script writer", "ok": True}
    assert m["data"]["helpers"][0]["text"] == "Title: “I rode the ridge at dawn”." and m["data"]["guards"] == \
        ["handoff"]
    assert "Ask the script writer for a title for my biking video" in fake.calls[0]["messages"][-1]["content"]
    assert "Script writer answered:" in fake.last_user(1) and fake.last_user(1).startswith(assistant.RESULTS)


def test_a_helper_that_repeats_its_job_is_asked_once_more(data, monkeypatch):
    from clipfoundry.brain import agents, assistant

    writer = agents.add(WS, template="script_writer")
    task = "Write a hook for my biking video"
    fake = install(monkeypatch, say(task), say("“I almost didn't make it down.”"))
    out = agents.run(WS, writer["id"], task)
    assert out["ok"] and out["text"] == "“I almost didn't make it down.”" and fake.last_user(1) == \
        assistant.NUDGE_ECHO


# ------------------------------------------------------------------ the review's findings (Nov 26)
def test_a_change_a_guard_reads_always_waits_for_the_ok(data, monkeypatch):
    from clipfoundry.brain import intents, tools

    ran: list = []
    make = tools.get("make_clips")
    monkeypatch.setattr(make, "run", lambda ctx, args: ran.append(args) or tools.Result("Started.", "Started"))
    monkeypatch.setattr(make, "preview", lambda ctx, args: {"label": f"Make clips from {args['link']}", "args": {}})
    said = "make clips from https://youtu.be/abc123"
    install(monkeypatch, say("Let me take a look."), ai_acts_alone=True)
    out = _think([make], said, fallback=intents.guess(said, {"make_clips"}))
    assert out.pending[0]["state"] == "waiting" and ran == []  # acting alone, yet a guessed change is a button
    # the model's own call still acts at once, as Settings say
    install(monkeypatch, say("Making clips.", ("make_clips", {"link": "https://youtu.be/abc123"})), ai_acts_alone=True)
    out = _think([make], said)
    assert out.pending[0]["state"] == "done" and len(ran) == 1


def test_an_answer_that_ends_with_let_me_know_is_kept(data, monkeypatch):
    good = "Try “Ridge Rider”, “Downhill Dreams” or “Wheels Up”. Let me know if you want me to find more."
    fake = install(monkeypatch, say(good), say("never asked"))
    out = _think(_tools("find_projects"), "title ideas for my biking video")
    assert out.text == good and len(fake.calls) == 1 and out.slips == []


def test_the_caught_words_stay_when_the_next_round_fails(data, monkeypatch):
    from clipfoundry.brain import assistant
    from clipfoundry.pipeline import llm

    install(monkeypatch, say("Let me check."), llm.ProviderError("the model went away"))
    out = assistant.Outcome()
    with pytest.raises(llm.ProviderError):
        _think(_tools("find_projects"), "anything I should finish", out=out)
    assert out.text == "Let me check."


def test_work_done_first_is_an_answer_even_when_the_time_is_up(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.brain.tools import Ctx

    db.create_project("Hike day", workspace_id=WS, status="ready")
    fake = install(monkeypatch)
    out = _think(_tools("find_projects"), "my projects", first=[{"tool": "find_projects", "args": {}}],
                 ctx=Ctx(ws=WS, deadline=time.monotonic() + 3))
    assert out.rounds == 0 and fake.calls == [] and "“Hike day”" in out.text  # not "No time left"
