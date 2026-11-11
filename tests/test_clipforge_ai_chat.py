"""ClipForge AI's chat (docs/clipforge/CLIPFORGE_AI.md, "The chat"): teaching, forgetting, listing and explaining
work without a model; a video's chat makes checked proposals; with a model, ClipForge AI the assistant answers every
message with the conversation so far and the memories it recalled, proposes changes with its tools, and every
answer records what it used. Fake models stand in (tests/fake_model.py for the conversation, FakeHelper for the
editor's AI helper that works a change out); nothing leaves the machine."""
from __future__ import annotations

import json
import threading

import pytest

from fake_model import answers_finish, install, say, settled, wait_for  # noqa: F401
from test_studio_edit_requests import _order, _plan, _project, env  # noqa: F401

H = {"X-ClipFoundry": "1"}
WS = "local"


class FakeHelper:
    """Stands in for llm.complete (the editor's AI helper): records every call, answers from a script, can block
    until released."""

    def __init__(self, *answers):
        self.answers, self.calls, self.gate = list(answers), [], threading.Event()
        self.gate.set()

    def __call__(self, settings, prompt, **kw):
        self.calls.append((prompt, kw))
        self.gate.wait(10)
        answer = self.answers.pop(0) if self.answers else "{}"
        if isinstance(answer, Exception):
            raise answer
        return answer


def _say(chat_id: str, text: str, **kw) -> dict:
    from clipfoundry.brain import chat

    return chat.send(WS, chat_id, text, **kw)["ai"]


def test_teaching_forgetting_listing_and_help_need_no_model(env):
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    assert c["title"] == "ClipForge AI" and c["project_id"] == ""
    assert chat.open_chat(WS)["id"] == c["id"]  # one general chat

    m = _say(c["id"], "Remember: my intro is 3 seconds.")
    assert m["text"].startswith("Remembered: “my intro is 3 seconds”") and "every video" in m["text"]
    assert m["data"]["tool"] == "remember" and m["data"]["memory"]["kind"] == "fact"
    m = _say(c["id"], "never zoom in on faces")
    assert m["data"]["memory"]["kind"] == "rule" and m["data"]["memory"]["source"] == "said"
    m = _say(c["id"], "I like warm colours")
    assert m["data"]["memory"]["kind"] == "fact"
    assert {x["kind"] for x in brain.list_(WS)} == {"rule", "fact"} and len(brain.list_(WS)) == 3

    m = _say(c["id"], "What do you know?")
    assert m["data"]["tool"] == "list" and len(m["data"]["memories"]) == 3
    assert "[rule] never zoom in on faces" in m["text"] and "Brain → Memory" in m["text"]
    m = _say(c["id"], "what do you know about zooms?")
    assert [x["text"] for x in m["data"]["memories"]] == ["never zoom in on faces"]

    m = _say(c["id"], "forget the rule about zooming")  # close, not exact: it asks which one
    assert m["data"]["tool"] == "forget" and [x["text"] for x in m["data"]["candidates"]] == ["never zoom in on faces"]
    assert "Which one?" in m["text"] and len(brain.list_(WS)) == 3
    m = _say(c["id"], "forget never zoom in on faces")  # exact words: gone
    assert m["text"] == "Forgotten: “never zoom in on faces”." and len(brain.list_(WS)) == 2
    m = _say(c["id"], "forget about penguins")
    assert m["text"] == "I have nothing like that in my memory." and m["data"]["candidates"] == []

    assert _say(c["id"], "help")["text"] == chat.HELP and _say(c["id"], "Help?")["text"] == chat.HELP
    assert _say(c["id"], "why?")["data"]["tool"] == "explain"
    m = _say(c["id"], "how long should my intros be?")  # a question, with no model set up
    assert m["data"]["tool"] == "answer" and m["status"] == "done" and "Settings → ClipForge AI" in m["text"]
    with pytest.raises(chat.ChatError):
        chat.send(WS, c["id"], "   ")
    with pytest.raises(chat.ChatError):
        chat.send(WS, c["id"], "x" * 4001)
    with pytest.raises(chat.ChatError):
        chat.send("other", c["id"], "hello")  # another workspace's chat
    with pytest.raises(chat.ChatError):
        chat.open_chat(WS, "no-such-video")

    msgs = chat.messages(WS, c["id"])
    assert [m["role"] for m in msgs][:2] == ["owner", "ai"] and msgs[0]["text"] == "Remember: my intro is 3 seconds."
    assert chat.messages(WS, c["id"], after=msgs[-3]["id"]) == msgs[-2:]
    assert chat.clear(WS, c["id"]) == len(msgs) and chat.messages(WS, c["id"]) == []


def _twin(text: str, **fields) -> dict:
    """The same words kept apart from the memory that says them (for one video, switched off, as another kind): a
    brain file, an edit, or two answers at the same moment."""
    from clipfoundry import db
    from clipfoundry.brain import memories

    return db.insert("brain_memories", {"workspace_id": WS, "kind": "fact", "text": text,
                                        "norm": memories._norm(text), "source": "said",  # noqa: SLF001
                                        "confidence": 1.0, "scope": "all", "tags": [], "data": {}, "meaning": None,
                                        "meaning_model": "", "enabled": 1, "revision": 1, "used_count": 0, **fields})


def test_forget_with_the_exact_words_forgets_every_memory_that_says_them(env):
    """Its twins go with it (kept for one video, switched off, or as a rule), so nothing still follows words the owner
    asked to forget, also when they start with a word the pattern skips ("forget my …"); other words stay."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    brain.remember(WS, "my intro is 3 seconds")
    _twin("My intro is 3 seconds", scope="project:p1", project_id="p1")
    _twin("my intro is 3 seconds.", enabled=0)
    _twin("my intro is 3 seconds", kind="rule")
    brain.remember(WS, "my outro is 5 seconds")
    m = _say(c["id"], "forget my intro is 3 seconds")
    assert m["text"] == "Forgotten: “my intro is 3 seconds” (I had it 4 times; all 4 are gone)."
    assert m["data"]["tool"] == "forget" and m["data"]["forgotten"]["text"] == "my intro is 3 seconds"
    assert [x["text"] for x in brain.list_(WS)] == ["my outro is 5 seconds"]
    _twin("My outro is 5 seconds", enabled=0)
    m = _say(c["id"], "forget: my outro is 5 seconds")
    assert m["text"] == "Forgotten: “my outro is 5 seconds” (I had it 2 times; both are gone)."
    assert brain.list_(WS) == []


def test_forget_takes_only_the_words_the_owner_named_and_only_as_a_whole_word(env):
    """“forget my intro is 3 seconds” forgets the memory that says “my intro is 3 seconds”, never also another that
    says “intro is 3 seconds”; the words after a leading “my”, “that” or “the” count only when no memory says them
    all. A sentence that starts with “Forgetting …” or a word that starts with “note” is not a request to forget or
    to remember anything."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    for words in ("intro is 3 seconds", "my intro is 3 seconds", "intro is 3 seconds for shorts"):
        brain.remember(WS, words)
    m = _say(c["id"], "forget my intro")  # close, not exact: which one?
    assert sorted(x["text"] for x in m["data"]["candidates"]) == ["intro is 3 seconds", "intro is 3 seconds for shorts",
                                                                   "my intro is 3 seconds"]
    m = _say(c["id"], "forget my intro is 3 seconds")  # typed
    assert m["text"] == "Forgotten: “my intro is 3 seconds”."
    assert m["data"]["forgotten"]["text"] == "my intro is 3 seconds"
    assert sorted(x["text"] for x in brain.list_(WS)) == ["intro is 3 seconds", "intro is 3 seconds for shorts"]
    m = _say(c["id"], "forget that my intro is 3 seconds")  # no memory says it all: the words after “that my”
    assert m["text"] == "Forgotten: “intro is 3 seconds”."
    assert [x["text"] for x in brain.list_(WS)] == ["intro is 3 seconds for shorts"]

    brain.remember(WS, "Forgetting captions loses viewers")
    brain.remember(WS, "mystery music works")
    m = _say(c["id"], "Forgetting captions loses viewers")  # said again: not “forget ting captions …”
    assert m["data"]["tool"] != "forget"
    m = _say(c["id"], "forget mystery music")  # not “forget my” + “stery music”
    assert [x["text"] for x in m["data"]["candidates"]] == ["mystery music works"]
    m = _say(c["id"], "Notes from the shoot are in the folder")  # not “note” + “s from the shoot …”
    assert m["data"]["tool"] != "remember"
    assert sorted(x["text"] for x in brain.list_(WS)) == ["Forgetting captions loses viewers",
                                                          "intro is 3 seconds for shorts", "mystery music works"]


def test_a_correction_never_forgets_and_a_longer_word_is_never_cut(env):
    """“Forget that, keep the music low” sets something aside and says the rule again: it never forgets that rule at
    once (without a model it asks which one, so nothing goes before a press). “forget”, and each word it skips,
    counts only with a space after it (or a colon after “forget”) and then a word or an opening “ or ": never with a
    comma, a full stop, a dash, a new line, an emoji, a smiley, a bracket or an arrow, and a quote counts only when it
    holds all the words (“Forget the “🔇”, keep the music low” is a correction too). A longer word is never cut:
    “Remember that's …” keeps “that's …”, and “Note-taking …”, “Forget-me-nots …” and “Keep in mind-blowing …” are not
    requests; a minus is not a dash (“Note -14 LUFS …”). Words that name nothing on their own (“Remember that.”,
    “Remember that one”, “Remember this 😅”, “Remember that :D”) keep nothing."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    brain.remember(WS, "Keep the music low", kind="rule")
    _twin("keep the music low", scope="platform:tiktok", platform="tiktok")
    for said in ("Forget that, keep the music low.", "Forget that. Keep the music low", "Forget, keep the music low",
                 "Forget about that - keep the music low!", "Forget. Keep the music low",
                 "Forget that\nKeep the music low", "forget that: keep the music low",
                 "Forget that 😅 keep the music low", "Forget 😅 keep the music low",
                 "Forget about that 😂 keep the music low", "Forget :) keep the music low",
                 "Forget that (keep the music low)", "Forget that » keep the music low",
                 "Forget that → keep the music low", "Forget that 🙈\nKeep the music low",
                 "Forget 😅\nKeep the music low", "Forget that 😅, keep the music low",
                 "Forget the “🔇”, keep the music low", "Forget “🎵🔊” — keep the music low!",
                 "Forget that “…” keep the music low", "Forget about that “🙈”\nKeep the music low",
                 'Forget that "..." keep the music low', "Forget that “:)” keep the music low",
                 "Forget that “” keep the music low", "Forget «keep the music low»"):
        m = _say(c["id"], said)
        assert m["data"]["tool"] == "forget" and m["text"].startswith("Which one?"), said  # nothing went
        assert len(brain.list_(WS)) == 2, said
    m = _say(c["id"], "forget that keep the music low")  # “that” and a space: the words after it, both times
    assert m["text"] == "Forgotten: “Keep the music low” (I had it 2 times; both are gone)."

    m = _say(c["id"], "Remember that's my sister in the intro")
    assert m["data"]["memory"]["text"] == "that's my sister in the intro"
    m = _say(c["id"], "Remember thatch roofs look great on drone shots")
    assert m["data"]["memory"]["text"] == "thatch roofs look great on drone shots"
    m = _say(c["id"], "remember that my intro is 3 seconds")
    assert m["data"]["memory"]["text"] == "my intro is 3 seconds"
    m = _say(c["id"], "note - the drone shots are in the B folder")
    assert m["data"]["memory"]["text"] == "the drone shots are in the B folder"
    m = _say(c["id"], "Remember that. The outro is 2 seconds")  # “that.” points back; the next sentence is kept
    assert m["data"]["memory"]["text"] == "The outro is 2 seconds"
    m = _say(c["id"], "Note -14 LUFS for YouTube")  # a minus, not a dash
    assert m["data"]["memory"]["text"] == "-14 LUFS for YouTube"
    m = _say(c["id"], "Remember that -3 dB is right for music")
    assert m["data"]["memory"]["text"] == "-3 dB is right for music"
    m = _say(c["id"], "Remember that; the cut at 0:42 stays")  # “that” is left out only before a space or , : . ! ? …
    assert m["data"]["memory"]["text"] == "that; the cut at 0:42 stays"
    kept = sorted(x["text"] for x in brain.list_(WS))
    for said in ("Note-taking during the shoot saves time in the edit", "Keep in mind-blowing transitions for the end",
                 "Forget-me-nots in spring footage look great"):
        m = _say(c["id"], said)
        assert m["data"]["tool"] not in ("remember", "forget"), said
    for said in ("Remember that.", "Note that.", "Keep in mind that.", "Remember that!", "Remember that?",
                 "Remember that", "remember this.", "Please remember that 😅", "remember: it", "Remember that one",
                 "Note that one.", "Keep in mind that one!", "Remember this…", "Please remember this 😅",
                 "Remember it 👍", "Remember this :)", "Remember: that…", "Remember that :D", "Remember :D",
                 "Remember that, please.", "Remember these 👇", "Remember that here."):
        m = _say(c["id"], said)
        assert m["status"] == "failed" and m["text"].startswith("Say what to remember, for example: "), said
    assert sorted(x["text"] for x in brain.list_(WS)) == kept


def test_remembering_words_a_memory_already_says_offers_no_undo(env):
    """The memory that already says the words is switched on and kept for every video, and the answer says so with
    no Undo chip: Undo forgets the memory, and that one was there before the answer. New words get their chip."""
    from clipfoundry.brain import chat, memories

    c = chat.open_chat(WS)
    old = _twin("The outro is 2 seconds", scope="platform:tiktok", platform="tiktok", enabled=0)
    m = _say(c["id"], "Remember that. The outro is 2 seconds")
    assert m["text"] == ("I already remember “The outro is 2 seconds” (switched on again). It applies to every video. "
                         "Say “forget …” to remove it.")
    assert "memory" not in m["data"] and m["data"]["kept"]["id"] == old["id"]
    row = memories.get(WS, old["id"])
    assert (row["enabled"], row["scope"]) == (1, "all")
    m = _say(c["id"], "remember: the outro is 2 seconds")  # said again
    assert m["text"] == ("I already remember “the outro is 2 seconds”. It applies to every video. Say “forget …” to "
                         "remove it.")
    assert "memory" not in m["data"] and [x["id"] for x in memories.list_(WS)] == [old["id"]]
    m = _say(c["id"], "remember: the intro is 3 seconds")
    assert m["data"]["memory"]["text"] == "the intro is 3 seconds" and m["data"]["memory"]["id"] != old["id"]


def test_which_one_lists_each_set_of_words_once_and_its_button_forgets_only_those_words(env):
    """“Which one?” lists words kept more than once (a rule and a fact, one for a single platform …) once, and says
    that picking them forgets each. Its button sends the memory's words in quotes: quoted words are forgotten exactly,
    never shorter ones, so a button pressed again, or after its memory was forgotten or changed elsewhere, forgets
    nothing else and says so; also when the memory's words have quotes of their own (“Trail Notes”, "hello"). Two
    quoted parts typed in one message are not one quote."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    brain.remember(WS, "Music fades out at the end")
    brain.remember(WS, "Keep the music low", kind="rule")
    _twin("keep the music low", scope="platform:tiktok", platform="tiktok")
    m = _say(c["id"], "forget the music thing")
    assert m["text"].startswith("Which one? I will forget the one you pick:\n")
    assert m["text"].lower().count("keep the music low") == 1
    assert "\n- [rule, fact] Keep the music low (2 times: picking it forgets both)" in m["text"]
    assert "\n- [fact] Music fades out at the end" in m["text"]
    assert sorted(x["text"] for x in m["data"]["candidates"]) == ["Keep the music low", "Music fades out at the end"]
    m = _say(c["id"], "forget “Keep the music low”")  # its button
    assert m["text"] == "Forgotten: “Keep the music low” (I had it 2 times; both are gone)."
    assert [x["text"] for x in brain.list_(WS)] == ["Music fades out at the end"]

    brain.remember(WS, "the intro is 3 seconds")
    brain.remember(WS, "intro is 3 seconds")
    m = _say(c["id"], "forget “the intro is 3 seconds”")
    assert m["text"] == "Forgotten: “the intro is 3 seconds”."
    m = _say(c["id"], "forget “the intro is 3 seconds”")  # pressed again: the shorter words stay
    assert m["text"] == "Nothing I remember says “the intro is 3 seconds”, so nothing was forgotten."
    assert m["data"]["tool"] == "forget" and not m["data"].get("candidates")
    assert sorted(x["text"] for x in brain.list_(WS)) == ["Music fades out at the end", "intro is 3 seconds"]
    m = _say(c["id"], 'forget "intro is 3 seconds".')  # typed in straight quotes, with a full stop
    assert m["text"] == "Forgotten: “intro is 3 seconds”."

    for words, near in (("my “intro” is 3 seconds", "intro is 3 seconds"),
                        ('Say "hello" at the start', "Say hello at the end"),
                        ("Call the series “Trail Notes”", "Call the series Trail Notes Daily")):
        brain.remember(WS, words)
        brain.remember(WS, near)
        m = _say(c["id"], f"forget “{words}”")  # its button
        assert m["text"] == f"Forgotten: “{words}”.", words
        m = _say(c["id"], f"forget “{words}”")  # pressed again: nothing else, and it says so
        assert m["text"] == f"Nothing I remember says “{words}”, so nothing was forgotten.", words
        assert near in [x["text"] for x in brain.list_(WS)], words
    m = _say(c["id"], "forget “Say hello at the end” and “Music fades out at the end”")  # two quotes, typed
    assert m["data"]["tool"] == "forget" and m["text"].startswith("Which one?")
    assert sorted(x["text"] for x in brain.list_(WS)) == ["Call the series Trail Notes Daily",
                                                           "Music fades out at the end", "Say hello at the end",
                                                           "intro is 3 seconds"]


def test_a_videos_chat_proposes_checked_changes_that_apply_as_versions_and_explains_them(env, monkeypatch):
    from clipfoundry import brain, db
    from clipfoundry.brain import chat
    from clipfoundry.pipeline import llm

    calls: list = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: calls.append(a) or "{}")
    p = _project(env)
    pid = p["id"]
    c = chat.open_chat(WS, pid)
    assert c["title"] == "Hike" and c["project_id"] == pid
    assert chat.open_chat(WS, pid)["id"] == c["id"] and chat.open_chat(WS)["id"] != c["id"]

    m = _say(c["id"], "why did you do that?")
    assert "not changed this video yet" in m["text"]
    m = _say(c["id"], "Remove the long silence at the beginning.")
    assert m["status"] == "done" and m["data"]["tool"] == "change" and m["data"]["used"] == []
    req = m["data"]["request"]
    assert req["status"] == "ready" and req["source"] == "rules"
    assert "Clip 1 “morning.mp4” starts 2.1 s later" in m["text"] and "Apply it as a new version" in m["text"]
    assert _plan(pid)["clips"][0]["in_ms"] == 0 and calls == []  # nothing changes until Apply; no model asked

    done = chat.apply(WS, c["id"], m["id"])
    assert done["data"]["request"]["status"] == "applied" and done["text"].startswith("Applied as version 2.")
    assert db.fetch("studio_projects", pid)["plan_revision"] == 2 and _plan(pid)["clips"][0]["in_ms"] == 2150
    with pytest.raises(chat.ChatError) as e:
        chat.apply(WS, c["id"], m["id"])  # not twice
    assert e.value.status == 409
    with pytest.raises(chat.ChatError) as e:
        chat.apply(WS, c["id"], done["id"] + "x")
    assert e.value.status == 404

    m = _say(c["id"], "why?")
    assert m["data"]["tool"] == "explain" and m["data"]["request_id"] == req["id"]
    assert "“Remove the long silence at the beginning.” → applied, understood on my own, without a model" in m["text"]
    assert "From your brain I used: nothing" in m["text"]

    m = _say(c["id"], "remember for this video: the lunch part is the best bit")
    assert "this video" in m["text"] and m["data"]["memory"]["project_id"] == pid
    assert m["data"]["memory"]["scope"] == f"project:{pid}"
    assert m["data"]["memory"]["text"] == "the lunch part is the best bit"
    m = _say(c["id"], "always keep the summit part")
    assert m["data"]["memory"]["scope"] == "all"
    assert [x["text"] for x in brain.recall("the summit and the lunch part", WS, project_id=pid).memories] == [
        "always keep the summit part", "the lunch part is the best bit"]
    assert [x["text"] for x in brain.recall("the summit and the lunch part", WS, project_id="other").memories] == [
        "always keep the summit part"]

    m = _say(c["id"], "move clip 4 before clip 2")
    assert m["data"]["request"]["status"] == "ready"
    m = chat.discard(WS, c["id"], m["id"])
    assert m["data"]["request"]["status"] == "canceled" and m["text"] == "Canceled; nothing was changed."
    m = _say(c["id"], "remove clip 9")
    assert m["status"] == "done" and m["data"]["request"]["status"] in ("question", "unsupported", "invalid")
    m = _say(c["id"], "paint the sky green")  # the rules do not understand it and there is no model
    assert m["data"]["request"]["status"] == "unsupported" and "none is set up" in m["text"]
    m = _say(c["id"], "remove clip 3", base_revision=1)
    assert m["status"] == "failed" and "This video changed (now version 2)" in m["text"]


def test_a_videos_chat_waits_for_the_ai_helper_and_remembers_what_it_used(env, monkeypatch):
    """With a model, ClipForge AI talks in the video's chat: it reads the memories that fit the message and records
    them as used, proposes the change with its propose_change tool (the editor's AI helper works it out and the
    editor checks it), and the video changes only when the owner presses Apply, as a new version."""
    from clipfoundry import brain, db
    from clipfoundry.brain import assistant, chat
    from clipfoundry.pipeline import llm
    from clipfoundry.studio import edit_requests as er

    fake = install(monkeypatch, ['{"say": "I will keep the lunch story together', ': check my proposal below.", '
                                 '"do": [{"tool": "propose_change", "args": {"request": "keep the second story '
                                 'together"}}]}'])
    helper = FakeHelper(json.dumps({"summary": "Keep the lunch story together.",
                                    "operations": [{"op": "move", "clip_id": "c4", "after": "c2"}]}))
    monkeypatch.setattr(llm, "complete", helper)
    monkeypatch.setattr(assistant, "WRITE_EVERY_S", 0.0)
    brain.remember(WS, "Never move the summit part", kind="rule")
    p = _project(env)
    c = chat.open_chat(WS, p["id"])
    fake.ready.clear()
    fake.flowing.clear()
    helper.gate.clear()
    try:
        m = _say(c["id"], "Keep the second story together")
        assert m["status"] == "thinking" and m["role"] == "ai" and m["text"] == "" and m["data"]["tool"] == "talk"
        assert m["data"]["provider"].startswith("Ollama") and m["data"]["sent"].startswith("Stays on this computer")
        assert m["data"]["remote"] is False
        fake.ready.set()
        assert fake.started.wait(10)
        # the answer shows while it is written
        row = db.fetch("brain_chat_messages", m["id"])
        assert row["status"] == "thinking" and row["text"] == "I will keep the lunch story together"
        assert [x["text"] for x in row["data"]["used"]] == ["Never move the summit part"]
        fake.flowing.set()
        m = settled(c["id"], m["id"])
        assert m["status"] == "done"
        assert m["text"] == "I will keep the lunch story together: check my proposal below."
        assert m["data"]["steps"] == [{"tool": "propose_change", "label": "Started working out the change",
                                       "ok": True}]
        assert m["data"]["request"]["status"] == "thinking"  # the editor's AI helper is still working it out
        assert len(fake.calls) == 1  # a proposal on its way needs no second round
    finally:
        fake.ready.set()
        fake.flowing.set()
        helper.gate.set()
    req = wait_for(lambda: next((x["data"]["request"] for x in chat.messages(WS, c["id"]) if x["id"] == m["id"]
                                 and x["data"]["request"]["status"] != "thinking"), None), what="the proposal")
    assert req["status"] == "ready" and "New order: 1, 2, 4, 3" in req["proposal"]["changes"]
    assert req["proposal"]["summary"] == "Keep the lunch story together."
    assert db.fetch("brain_chat_messages", m["id"])["status"] == "done"  # the finished state is kept

    # what it read and used: the rule went to the model and to the AI helper, and both uses are recorded
    call = fake.calls[0]
    assert call["task"] == "chat" and call["streamed"] and "- [rule] Never move the summit part" in call["system"]
    assert "This chat belongs to the YouTube video “Hike”" in call["system"]
    assert call["messages"] == [{"role": "user", "content": "Keep the second story together"}]
    assert "propose_change" in fake.tools_offered(0)
    prompt, kw = helper.calls[0]
    assert kw["task"] == "edit_proposal" and "- [rule] Never move the summit part" in prompt
    assert [x["text"] for x in m["data"]["used"]] == ["Never move the summit part"]
    assert [u["where_used"] for u in db.select("brain_memory_uses", "ref_id = ?", (m["id"],))] == ["chat"]
    assert [u["where_used"] for u in db.select("brain_memory_uses", "ref_id = ?", (req["id"],))] == \
        ["change_request"]
    assert er.view(req["id"], WS)["memories"][0]["text"] == "Never move the summit part"

    # nothing changed until Apply; Apply makes version 2 with the new order
    assert _order(p["id"]) == ["c1", "c2", "c3", "c4"] and db.fetch("studio_projects", p["id"])["plan_revision"] == 1
    done = chat.apply(WS, c["id"], m["id"])
    assert done["data"]["request"]["status"] == "applied"
    assert db.fetch("studio_projects", p["id"])["plan_revision"] == 2 and _order(p["id"]) == ["c1", "c2", "c4", "c3"]
    with pytest.raises(chat.ChatError) as again:
        chat.apply(WS, c["id"], m["id"])  # not twice
    assert again.value.status == 409


def test_the_general_chat_asks_the_ai_helper_with_its_memories_and_checks_the_answer(env, monkeypatch):
    """The general chat: the conversation engine answers with the memories it recalled (recorded as used), the
    conversation so far and ClipForge's reply shape; plain words are read as the answer, a failing model is said
    plainly, a long answer is cut, and the daily limit is for online models only."""
    from clipfoundry import brain, db
    from clipfoundry.brain import assistant, chat, tools
    from clipfoundry.pipeline import llm

    fake = install(monkeypatch, say("About 3 seconds, as you told me."), "not json at all",
                   llm.ProviderError("the helper is down"), say("x" * 7000), say("Online answer one."),
                   say("Online answer two."))
    brain.remember(WS, "my intro is 3 seconds")
    brain.remember(WS, "Never zoom in on faces", kind="rule")
    c = chat.open_chat(WS)
    fake.ready.clear()
    try:
        m = _say(c["id"], "how long should my intro be?")
        assert m["status"] == "thinking" and m["text"] == "" and m["data"]["tool"] == "talk"
        assert m["data"]["provider"].startswith("Ollama") and m["data"]["sent"].startswith("Stays on this computer")
    finally:
        fake.ready.set()
    m = settled(c["id"], m["id"])
    assert m["status"] == "done" and m["text"] == "About 3 seconds, as you told me."
    assert [x["text"] for x in m["data"]["used"]] == ["Never zoom in on faces", "my intro is 3 seconds"]
    assert m["data"]["steps"] == [] and m["data"]["pending"] == []
    call = fake.calls[0]
    settings = db.get_settings()
    assert call["task"] == "chat" and call["streamed"] and callable(call["cancel"])
    assert call["max_tokens"] == assistant.budgets(settings)["max_tokens"] and call["timeout"] > 60
    assert call["system"].startswith(assistant.persona()) and brain.memories.HEADER in call["system"]
    assert "- [fact] my intro is 3 seconds" in call["system"] and "- [rule] Never zoom in on faces" in call["system"]
    assert call["json_schema"] == tools.reply_schema(tools.available("general"))
    assert call["messages"] == [{"role": "user", "content": "how long should my intro be?"}]
    assert [u["where_used"] for u in db.select("brain_memory_uses", "ref_id = ?", (m["id"],))] == ["chat", "chat"]

    m = settled(c["id"], _say(c["id"], "and the outro?")["id"])
    assert m["status"] == "done" and m["text"] == "not json at all"  # plain words are read as what it says
    assert fake.calls[1]["messages"] == [
        {"role": "user", "content": "how long should my intro be?"},
        {"role": "assistant", "content": '{"say":"About 3 seconds, as you told me.","do":[]}'},
        {"role": "user", "content": "and the outro?"}]  # the conversation so far goes with every message
    m = settled(c["id"], _say(c["id"], "and the music?")["id"])
    assert m["status"] == "failed" and m["text"] == "My model could not answer: the helper is down"
    m = settled(c["id"], _say(c["id"], "and the captions?")["id"])
    assert m["status"] == "done" and m["text"] == "x" * assistant.SAY_CHARS  # a long answer is cut, never refused
    assert [t["content"] for t in fake.calls[3]["messages"]][-2:] == ["and the music?", "and the captions?"]

    # a model on this computer has no daily limit; an online one does (one answer counts once)
    db.save_settings({"ai_provider": "anthropic", "anthropic_model": "claude-opus-5", "ai_edit_requests_per_day": 2})
    m = settled(c["id"], _say(c["id"], "and the title?")["id"])
    assert m["status"] == "done" and m["data"]["remote"] is True
    assert m["data"]["sent"].startswith("Sent over the internet to Claude claude-opus-5")
    assert m["data"]["sent"].endswith("Never your files or their sound.")
    assert settled(c["id"], _say(c["id"], "and the hashtags?")["id"])["status"] == "done"
    m = _say(c["id"], "one more?")
    assert m["status"] == "failed" and "Today's limit of 2 requests to your online AI is reached" in m["text"]
    assert len(fake.calls) == 6

    # a restart while an answer was waiting: reported, never asked again
    db.insert("brain_chat_messages", {"chat_id": c["id"], "workspace_id": WS, "role": "ai", "text": "",
                                      "data": {"tool": "talk"}, "status": "thinking"})
    assert chat.recover() == 1 and chat.recover() == 0
    assert chat.messages(WS, c["id"])[-1]["text"].startswith("ClipForge restarted while this was waiting")


def test_the_chat_api_keeps_chats_inside_their_workspace(env, monkeypatch):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    p = _project(env)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/brain/chats", json={}).status_code == 403  # the app's header is needed to write
        r = client.post("/api/brain/chats", json={}, headers=H)
        assert r.status_code == 200 and r.json()["title"] == "ClipForge AI" and r.json()["messages"] == []
        general = r.json()["id"]
        r = client.post("/api/brain/chats", json={"project_id": p["id"]}, headers=H)
        assert r.status_code == 200 and r.json()["title"] == "Hike"
        video = r.json()["id"]
        assert client.post("/api/brain/chats", json={"project_id": "nope"}, headers=H).status_code == 404

        r = client.post(f"/api/brain/chats/{general}/messages", json={"text": "always use dissolves"}, headers=H)
        assert r.status_code == 200 and r.json()["ai"]["data"]["memory"]["kind"] == "rule"
        r = client.post(f"/api/brain/chats/{video}/messages", json={"text": "remove clip 3"}, headers=H)
        assert r.status_code == 200 and r.json()["ai"]["data"]["request"]["status"] == "ready"
        mid = r.json()["ai"]["id"]
        r = client.post(f"/api/brain/chats/{video}/messages/{mid}/discard", headers=H)
        assert r.status_code == 200 and r.json()["data"]["request"]["status"] == "canceled"
        assert client.post(f"/api/brain/chats/{video}/messages/{mid}/apply", headers=H).status_code == 409
        assert client.post(f"/api/brain/chats/{general}/messages/{mid}/apply", headers=H).status_code == 404
        r = client.get(f"/api/brain/chats/{video}/messages")
        assert r.status_code == 200 and [m["role"] for m in r.json()] == ["owner", "ai"]
        assert client.get(f"/api/brain/chats/{video}/messages", params={"after": r.json()[0]["id"]}).json() == \
            r.json()[1:]
        assert client.post(f"/api/brain/chats/{video}/messages", json={"text": ""}, headers=H).status_code == 422
        assert client.delete(f"/api/brain/chats/{video}/messages", headers=H).json() == {"cleared": 2}
        assert client.get("/api/brain/chats/not-a-chat/messages").status_code == 404
