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
              "Let me ask the Script writer.",
              # the real Basic model as the Script writer, in the fourth check (Nov 26)
              "Got it: I'm ready to write a two-line hook about mountain biking.", "Got it, I'll write a title."):
        assert intents.promise(s), s
    for s in ("Let me know if you want more.", "Can I look at it?", "I can't find that project.",
              "You have 3 projects. " + "x" * 300, "I'll be honest: the hook is too slow.",
              # the review's answers that are answers (Nov 26)
              "Try “Ridge Rider”, “Downhill Dreams” or “Wheels Up”. Let me know if you want me to find more.",
              "Let's get you a title: “Ride the Ridge”.", "I'll be honest: the hook is weak, see if you can open on it",
              "Got it — from now on I will ask you before anything is posted.", "Let me look. You have 3 projects.",
              "Let me check: you have “Hike day” and “Lake swim”.",
              "Got it: your channel is about mountain biking. I'll keep this in mind.", "Got it: “Ride the ridge”.",
              "Sure: here is the hook: “I almost fell.”"):
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


# ------------------------------------------------------------------ the second review's findings (Nov 26)
def test_words_that_go_on_after_let_me_look_are_the_answer():
    from clipfoundry.brain import intents

    for words in ("Let me see, your best clip is “Rage quit” with 2,500 views.",
                  "Let me look — you have “Hike day” and “Lake swim”.", "I'll check — nothing is running right now.",
                  "Let me see; “Trail build” is nearly done, so finish that one first."):
        assert not intents.promise(words), words


def test_only_a_whole_plain_request_is_read_without_the_model(data):
    from clipfoundry import db
    from clipfoundry.brain import intents

    db.create_project("Hike day", workspace_id=WS, status="ready")
    every = {"find_projects", "rename_project", "missions", "work", "posts"}
    assert intents.guess("which videos do I have to finish first?", every, WS) is None
    assert intents.guess("what projects do I have right now?", every, WS)["tool"] == "find_projects"
    assert intents.guess("show me my posts please", every, WS)["tool"] == "posts"
    for said in ("rename Hike day to Summit push please", "rename Hike day to a catchy title",
                 "rename Hike day to whatever you think works", "rename Hike day to a new name",
                 "rename Hike day to something better"):
        assert intents.guess(said, every, WS) is None, said
    assert intents.guess("rename Hike day to “Summit push please”", every, WS)["args"]["name"] == \
        "Summit push please"
    assert intents.guess("rename Hike day to Summit push", every, WS)["args"] == {"project": "Hike day",
                                                                               "name": "Summit push"}


def test_a_question_or_a_dont_about_a_helper_is_no_job_for_it(data):
    from clipfoundry.brain import agents, intents

    critic = agents.add(WS, template="critic")
    for said in ("Have the Critic's notes been fixed yet?", "Let the Critic rest today, I will review it myself",
                 "tell the Critic not to bother", "Get the Critic's review out of my way"):
        assert intents.handoff(WS, said) is None, said
    assert intents.handoff(WS, "can you get my Critic to review this hook?")[0]["id"] == critic["id"]


def test_a_helper_that_repeats_its_job_or_the_owners_words_is_asked_once_more(data, monkeypatch):
    from clipfoundry.brain import agents, assistant

    agents.add(WS, template="script_writer")
    said = "Ask the script writer for a title for my biking video"
    fake = install(monkeypatch, say(said), say("Title: “Ridge run at dawn”."),
                   say("The Script writer suggests “Ridge run at dawn”."))
    m, _c = _ask(said)
    assert fake.last_user(1) == assistant.NUDGE_ECHO  # the helper's second round
    assert m["data"]["helpers"][0]["text"] == "Title: “Ridge run at dawn”."


def test_a_bracket_is_removed_only_when_it_names_a_helper(data, monkeypatch):
    install(monkeypatch, say("[0:42–1:10] The jump is your best moment: start the clip there."))
    out = _think([], "where should my clip start?")
    assert out.text == "[0:42–1:10] The jump is your best moment: start the clip there."
    install(monkeypatch, say("[Critic] Cut the first two seconds."))
    assert _think([], "what would you cut?").text == "Cut the first two seconds."  # a ready-made helper's name


def test_a_listing_found_before_a_later_round_failed_is_still_shown(data, monkeypatch):
    import pytest

    from clipfoundry import db
    from clipfoundry.brain import assistant, intents

    db.create_project("Hike day", workspace_id=WS, status="ready")
    said = "what projects do I have?"
    install(monkeypatch, say("Let me look."), RuntimeError("the engine fell over"))
    out = assistant.Outcome()
    with pytest.raises(Exception):
        _think(_tools("find_projects"), said, fallback=intents.guess(said, {"find_projects"}), out=out)
    assert "“Hike day”" in out.text and "Let me look" not in out.text


def test_a_cards_note_the_model_copies_is_never_the_answer(data, monkeypatch):
    """The real Basic model, as the Script writer, answered only "[Waiting for the owner's OK: Delete the clips
    project “Old gear review”]", the note the conversation holds for the card before (check on Nov 26 2026)."""
    from clipfoundry.brain import agents, assistant

    agents.add(WS, template="script_writer")
    note = "[Waiting for the owner's OK: Delete the clips project “Old gear review”]"
    fake = install(monkeypatch, say(note), say("“I almost didn't make it down.” / “Here's why.”"))
    m, _c = _ask("@Script writer write a two-line hook about mountain biking")
    assert m["role"] == "agent" and m["text"] == "“I almost didn't make it down.” / “Here's why.”"
    assert fake.last_user(1) == assistant.NUDGE_EMPTY and m["data"]["guards"] == ["empty"]
    install(monkeypatch, say(note + " You have 2 projects. [The owner said no to: Rename “Hike day”]"))
    assert _think([], "how many projects do I have?").text == "You have 2 projects."


def test_when_a_helper_only_promises_even_when_asked_again_clipforge_ai_writes_it(data, monkeypatch):
    """As the real Basic model's Script writer did: "Got it. I'll write a two-line hook for your biking video." twice;
    ClipForge AI is told so and writes the title itself, never "I'll now give you the result"."""
    from clipfoundry.brain import agents

    agents.add(WS, template="script_writer")
    promise = "Got it. I'll write a title for your biking video."
    fake = install(monkeypatch, say(promise), say(promise), say("Try “Ridge run at dawn”."))
    m, _c = _ask("Ask the script writer for a title for my biking video")
    assert m["text"] == "Try “Ridge run at dawn”." and m["data"]["helpers"][0]["text"] == promise
    assert "Script writer only said what it would do" in fake.last_user(2) and "Write it yourself now" in \
        fake.last_user(2)


def test_a_helper_that_writes_nothing_even_asked_again_is_asked_with_its_job_alone(data, monkeypatch):
    """The real Basic model, as the Script writer after a delete card, answered only the card's note twice (check on
    Nov 26 2026); the planner's same kind of job, without the conversation, it wrote."""
    from clipfoundry.brain import agents, assistant, chat

    writer = agents.add(WS, template="script_writer")
    c = chat.open_chat(WS)
    install(monkeypatch, say("Sure."))
    settled(c["id"], chat.send(WS, c["id"], "hi")["ai"]["id"])
    note = "[Waiting for the owner's OK: Delete the clips project “Old gear review”]"
    fake = install(monkeypatch, say(note), say(note), say("“I almost didn't make it down.” / “Here's why.”"))
    said = "@Script writer write a two-line hook about mountain biking"
    m = settled(c["id"], chat.send(WS, c["id"], said)["ai"]["id"])
    assert m["status"] == "done" and m["text"] == "“I almost didn't make it down.” / “Here's why.”"
    assert m["data"]["guards"] == ["empty", "empty", "alone"]
    assert fake.calls[1]["messages"][-1]["content"] == assistant.NUDGE_EMPTY
    assert [x["content"] for x in fake.calls[2]["messages"]] == [said.removeprefix("@Script writer ")]  # alone
    # a job ClipForge AI hands over: the same, with the job's own words
    fake = install(monkeypatch, say(""), say(""), say("Title: “Ridge run at dawn”."))
    out = agents.run(WS, writer["id"], "Write a title for my biking video", chat=c)
    assert out["ok"] and out["text"] == "Title: “Ridge run at dawn”."
    assert len(fake.calls[2]["messages"]) == 1 and fake.calls[2]["messages"][0]["content"].startswith(
        assistant.JOB_LEAD)
    # one that wrote, or read the conversation alone already, is never asked again
    fake = install(monkeypatch, say(""), say(""))
    out = agents.run(WS, writer["id"], "Write a title for my biking video")
    assert not out["ok"] and len(fake.calls) == 2


# ------------------------------------------------------------------ the review of the last fixes (Nov 26)
def test_a_cards_note_with_brackets_in_a_name_is_removed_whole(data, monkeypatch):
    for note in ("[Waiting for the owner's OK: Delete the clips project “Trip to Iceland [4K]”]",
                 "[The owner pressed OK and it was done: Renamed “Vlog [part 2]” to “Vlog 2”]",
                 "[Could not delete Old talk, so nothing was done: That project is not there any more.]"):
        install(monkeypatch, say(note + " You have 2 projects."))
        assert _think([], "how many projects do I have?").text == "You have 2 projects.", note
    install(monkeypatch, say("[0:42–1:10] The jump is your best moment."))
    assert _think([], "where should my clip start?").text == "[0:42–1:10] The jump is your best moment."


def test_a_silent_helper_is_asked_once_more_alone_and_not_nudged_after_it(data, monkeypatch):
    from clipfoundry.brain import agents, chat

    writer = agents.add(WS, template="script_writer")
    c = chat.open_chat(WS)
    install(monkeypatch, say("Sure."))
    settled(c["id"], chat.send(WS, c["id"], "hi")["ai"]["id"])
    fake = install(monkeypatch, say(""), say(""), say(""), say("never asked"))
    out = agents.run(WS, writer["id"], "Write a title for my biking video", chat=c)
    assert not out["ok"] and len(fake.calls) == 3
    fake = install(monkeypatch, say(""), say(""), say(""), say("never asked"))
    m = settled(c["id"], chat.send(WS, c["id"], "@Script writer write a title")["ai"]["id"])
    assert m["status"] == "failed" and len(fake.calls) == 3 and m["data"]["guards"] == ["empty", "empty", "alone",
                                                                                          "empty"]


def test_a_helper_that_did_the_work_with_a_tool_is_not_told_off_for_its_words(data, monkeypatch):
    from clipfoundry.brain import agents, toolbox, tools

    writer = agents.add(WS, template="script_writer")
    for steps, told in (([{"tool": "remember", "label": "Kept a memory", "ok": True}], False),
                        ([{"tool": "recall", "label": "Looked in the memory", "ok": True}], True), ([], True)):
        ran = {"agent": agents.card(writer), "text": "I will write it down.", "steps": steps, "data": {}, "ok": True}
        monkeypatch.setattr(agents, "run", lambda *a, ran=ran, **k: ran)
        res = toolbox._ask_agent(tools.Ctx(ws=WS), {"agent": "Script writer", "task": "Keep my channel's topic"})
        assert ("only said what it would do" in res.text) is told, steps
        assert told or res.text == "Script writer answered:\nI will write it down."


def test_an_answer_with_long_notes_before_a_long_follow_up_is_kept_shortened(data):
    import json

    from clipfoundry import db
    from clipfoundry.brain import assistant, chat

    c = chat.open_chat(WS)

    def add(role, text, **extra):
        return db.insert("brain_chat_messages", {"chat_id": c["id"], "workspace_id": WS, "role": role, "text": text,
                                                 "data": extra, "status": "done"})

    add("owner", "plan my video")
    helpers = [{"agent": {"name": n}, "text": f"{n} notes. " * 80, "ok": True} for n in ("Researcher", "Critic")]
    add("ai", "Here is the plan: open on the summit, then the climb. " + "More. " * 300, helpers=helpers)
    add("owner", "Rewrite my draft using your plan. " + "word " * 760)
    for as_json in (False, True):
        h = assistant.history(c["id"], 5000, as_json=as_json)
        assert [t["role"] for t in h] == ["assistant", "user"], as_json
        assert sum(len(t["content"]) + 8 for t in h) <= 5000
    plan = json.loads(h[0]["content"])
    assert plan["say"].startswith("Here is the plan: open on the summit") and " … " in plan["say"]
    assert len(plan["notes"]) == 1 and plan["notes"][0].startswith("[Researcher wrote:")
