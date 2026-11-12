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


def test_forget_offers_the_memories_that_say_or_hold_the_words_named_whatever_they_start_with(env):
    """Without a model. Words that start with a sign, a bracket or other quote marks never forget at once (what
    follows “forget” there may set something aside), and the search by meaning reads only longer Latin words, so
    “forget -3 dB here”, “forget -6 dB” or the words of a memory in Russian were answered “I have nothing like that
    in my memory”. Now the memories that say exactly the words named, then the ones that hold them as a part of
    theirs, are offered to pick from (the one that says them first, also when one that holds them is newer);
    nothing goes before the pick, and the button forgets exactly its words. The words may name the memory the way
    the help does (“forget the rule about -3 dB”, “the one that says …”) or ask nicely behind it (“…, please”, “…
    too”, which found nothing or an unrelated memory). A mark in quotes is a memory's exact words like any other."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c, video = chat.open_chat(WS), chat.open_chat(WS, _project(env)["id"])
    assert _say(video["id"], "remember: -3 dB here")["data"]["memory"]["scope"].startswith("project:")
    for words in ("+3 dB on the voice", "-6 dB", "-6 dB on the music", "-3 дБ на голос", "«Привет, друзья» в начале"):
        assert _say(c["id"], f"remember: {words}")["data"]["memory"]["text"] == words
    brain.remember(WS, "!")  # taught on the Memory page: a mark alone
    both = ["-6 dB", "-6 dB on the music"]  # the one that says the words, then the (newer) one that holds them
    for said, offered in (("forget -3 dB here", ["-3 dB here"]), ("forget -3 dB", ["-3 dB here"]),
                          ("forget -6 dB", both), ("Forget: -6 dB.", both), ("forget that -6 dB", both),
                          ("forget (-6 dB)", both), ("forget the -6 dB on the music", ["-6 dB on the music"]),
                          ("forget -3 дБ на голос", ["-3 дБ на голос"]), ("forget на голос", ["-3 дБ на голос"]),
                          ("forget «Привет, друзья» в начале", ["«Привет, друзья» в начале"]),
                          ("forget друзья", ["«Привет, друзья» в начале"]), ("forget !", ["!"]),
                          ("forget dB on the", ["-6 dB on the music", "+3 dB on the voice"]),
                          ("forget -3 dB here, please", ["-3 dB here"]), ("forget -3 dB here too", ["-3 dB here"]),
                          ("forget -3 dB, thanks", ["-3 dB here"]), ("forget -3 dB please", ["-3 dB here"]),
                          ("forget the rule about -3 dB", ["-3 dB here"]),
                          ("forget the rule -3 dB here", ["-3 dB here"]),
                          ("forget the one about -3 dB, please", ["-3 dB here"]),
                          ("forget the one that says -6 dB on the music", ["-6 dB on the music"]),
                          ("forget the rule about -6 dB, ok?", both),
                          ("forget the note on на голос", ["-3 дБ на голос"])):
        for where, quick in ((c, False), (video, False), (c, True)):  # pressed as a quick reply: the same list
            m = _say(where["id"], said, choice=quick)
            assert m["text"].startswith("Which one? I will forget the one you pick:"), said
            assert [x["text"] for x in m["data"]["candidates"]] == offered, said
            assert len(brain.list_(WS)) == 7, said  # nothing went
    for said in ("forget -9 dB", "forget that", "forget 3 dB", "forget it, please", "forget about penguins"):
        m = _say(c["id"], said)
        assert m["text"] == "I have nothing like that in my memory." and m["data"]["candidates"] == [], said
    m = _say(c["id"], "forget ?")
    assert m["status"] == "failed" and m["text"].startswith("Say what to forget, for example: ")
    assert _say(c["id"], "forget “-6 dB”", forget="-6 dB")["text"] == "Forgotten: “-6 dB”."  # its button
    assert _say(c["id"], "forget “!”", forget="!")["text"] == "Forgotten: “!”."
    brain.remember(WS, "?")
    assert _say(c["id"], 'forget "?"')["text"] == "Forgotten: “?”."  # typed in quotes: exactly these words, at once
    assert sorted(x["text"] for x in brain.list_(WS)) == ["+3 dB on the voice", "-3 dB here", "-3 дБ на голос",
                                                          "-6 dB on the music", "«Привет, друзья» в начале"]


def test_forget_with_only_words_it_skips_lists_no_memory_that_merely_holds_such_a_word(env):
    """“forget that”, “forget it, please”, “forget the one about” or “forget about” name no memory. Memories hold
    these little words (“I like that song”, “keep it short”), and the list of memories that hold the words named must
    not offer them all: without a model the answer is that nothing is like that."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    kept = ("I like that song", "keep it short", "the channel is about hiking", "my intro is 3 seconds",
            "the one rule: no stock music", "note the memory card")
    for words in kept:
        brain.remember(WS, words)
    for said in ("forget that", "forget it", "forget about", "forget the", "forget my", "forget that one",
                 "forget it, please", "forget that, thanks", "forget the one about", "forget that too",
                 "forget about that", "forget my one"):
        for quick in (False, True):
            m = _say(c["id"], said, choice=quick)
            assert m["text"] == "I have nothing like that in my memory." and m["data"]["candidates"] == [], said
    m = _say(c["id"], "forget that song")  # words that name something: the memory that holds them comes first
    assert m["data"]["candidates"][0]["text"] == "I like that song"
    m = _say(c["id"], "forget the one rule")
    assert m["data"]["candidates"][0]["text"] == "the one rule: no stock music"
    assert sorted(x["text"] for x in brain.list_(WS)) == sorted(kept)


def test_half_an_emoji_in_a_message_or_a_memory_is_left_out(env):
    """A message cut in the middle of an emoji ends with half of one, which cannot be saved: the chat's request and
    the Memory page's failed (a server error). The half is left out, like the one a model writes."""
    from fastapi.testclient import TestClient

    from clipfoundry import brain
    from clipfoundry.api import app
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    m = _say(c["id"], "remember: the outro song is \ud83d upbeat")
    assert m["text"].startswith("Remembered: “the outro song is upbeat”. It applies to every video.")
    assert chat.messages(WS, c["id"])[-2]["text"] == "remember: the outro song is upbeat"
    assert brain.remember(WS, "half \ude00 emoji")["text"] == "half emoji"
    assert _say(c["id"], "forget “half emoji”", forget="half \ud83d emoji")["text"] == "Forgotten: “half emoji”."
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        head = {**H, "Content-Type": "application/json"}
        r = client.post(f"/api/brain/chats/{c['id']}/messages", headers=head,
                        content=b'{"text": "remember: the intro is \\ud83d short"}')
        assert r.status_code == 200 and r.json()["ai"]["data"]["memory"]["text"] == "the intro is short"
        r = client.post("/api/brain/memories", headers=head, content=b'{"text": "cut on the \\ud83d beat"}')
        assert r.status_code == 200 and r.json()["text"] == "cut on the beat"
        r = client.post(f"/api/brain/chats/{c['id']}/messages", headers=head,
                        content=b'{"text": "remember: whole \\ud83d\\ude00 emoji"}')  # both halves: the emoji
        assert r.status_code == 200 and r.json()["ai"]["data"]["memory"]["text"] == "whole 😀 emoji"


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
    """The memory that already says the words, as a rule or as a fact, is switched on and kept for every video, and
    the answer says what it was before (switched off, only a guess, kept for one platform, other symbols) with no
    Undo chip: Undo forgets the memory, and that one was there before the answer. New words get their chip; words
    that differ in a sign, a symbol, a colon between digits, a mark of a letter, an emoji or a mark that stands alone
    (“end every caption with !”, “… with .”, kept with its full stop) are new words."""
    from clipfoundry.brain import chat, memories

    c = chat.open_chat(WS)
    old = _twin("The outro is 2 seconds", scope="platform:tiktok", platform="tiktok", enabled=0)
    m = _say(c["id"], "Remember that. The outro is 2 seconds")
    assert m["text"] == ("I already remember “The outro is 2 seconds” (switched on again; before, only for tiktok). "
                         "It applies to every video. Say “forget …” to remove it.")
    assert "memory" not in m["data"] and m["data"]["kept"]["id"] == old["id"]
    row = memories.get(WS, old["id"])
    assert (row["enabled"], row["scope"]) == (1, "all")
    m = _say(c["id"], "remember: the outro is 2 seconds")  # said again
    assert m["text"] == ("I already remember “the outro is 2 seconds”. It applies to every video. Say “forget …” to "
                         "remove it.")
    assert "memory" not in m["data"] and [x["id"] for x in memories.list_(WS)] == [old["id"]]
    m = _say(c["id"], "remember: the intro is 3 seconds")
    assert m["data"]["memory"]["text"] == "the intro is 3 seconds" and m["data"]["memory"]["id"] != old["id"]

    rule = _twin("“Keep the music low!”", kind="rule", source="guessed", confidence=0.5, enabled=0)
    m = _say(c["id"], "remember: keep the music low")  # no rule words, so a fact: the rule says them already
    assert m["text"] == ("I already had ““Keep the music low!”” (switched on again; no longer only a guess); it now "
                         "says “keep the music low”. It applies to every video. Say “forget …” to remove it.")
    assert "memory" not in m["data"] and m["data"]["kept"]["id"] == rule["id"]
    row = memories.get(WS, rule["id"])
    assert (row["kind"], row["text"], row["source"], row["enabled"]) == ("rule", "keep the music low", "said", 1)
    _twin("Don't zoom in on faces", kind="rule")
    m = _say(c["id"], "Remember: Don’t zoom in on faces")  # only the apostrophe differs
    assert m["text"].startswith("I already remember “Don’t zoom in on faces”. It applies to every video.")
    tiktok = _twin("Voice at +3 dB", scope="platform:tiktok", platform="tiktok")
    new = ("voice at -3 dB", "the cut at 0:42 stays", "the cut at 0.42 stays", "ตัดคลิปข่าวออก", "ตัดคลิปข้าวออก",
           "亮度+10", "亮度-10", "Shoot at EV+1", "shoot at EV-1", "post at 18:00 UTC+2", "post at 18:00 UTC-2",
           "keep peaks within +/-3 dB", "keep peaks within -3 dB", "raise the voice by +.5 dB",
           "raise the voice by -.5 dB", "raise the voice by .5 dB", "音量を＋３ｄＢにする", "音量を－３ｄＢにする",
           "keep the intro <3 s", "keep the intro >3 s", "clips ≤ 60 s", "clips ≥ 60 s", "captions at 50%",
           "captions at 50", "mute the music 🔇", "mute the music 🔊", "use b-roll", "use b roll",
           "end every caption with !", "end every caption with …", "end every caption with .",
           'use "!" in titles', 'use "?" in titles', "the voice sits at - 3 dB", "the voice sits at 3 dB",
           "trink in Maßen", "trink in Massen", "garde la musique basse !", "garde la musique basse")
    for said in new:
        m = _say(c["id"], f"remember: {said}")
        assert m["text"].startswith("Remembered: “") and m["data"]["memory"]["revision"] == 1, said
    assert memories.get(WS, tiktok["id"])["text"] == "Voice at +3 dB" and len(memories.list_(WS)) == 5 + len(new)
    # forgetting one of a pair leaves the other: only the words named go
    for said, other in (("亮度+10", "亮度-10"), ("shoot at EV+1", "shoot at EV-1"), ("keep the intro <3 s",
                        "keep the intro >3 s"), ("keep peaks within -3 dB", "keep peaks within +/-3 dB"),
                        ("end every caption with !", "end every caption with …"),
                        ("end every caption with .", "end every caption with …"),
                        ("the voice sits at 3 dB", "the voice sits at - 3 dB"), ("trink in Massen", "trink in Maßen"),
                        ("garde la musique basse", "garde la musique basse !")):
        assert _say(c["id"], f"forget {said}")["text"].lower() == f"forgotten: “{said}”.".lower(), said
        assert memories.twin(WS, other, ("fact", "rule")) and not memories.twin(WS, said, ("fact", "rule")), said
    # the same words typed with a full-width keyboard, or with the accent typed apart, are the same words
    m = _say(c["id"], "remember: 音量を+3dBにする")
    assert m["text"].startswith("I already had “音量を＋３ｄＢにする”; it now says “音量を+3dBにする”."), m["text"]


def test_undo_forgets_a_memory_only_while_it_is_as_its_answer_added_it(env):
    """A chip's Undo sends its words, and the memory goes only while it is as that answer added it (revision 1, the
    same words). Said again over it, edited, switched off, or written over by the answer of an earlier build (whose
    chip pointed at it), it stays, and Undo says it changed since; one already forgotten answers 404."""
    from fastapi.testclient import TestClient
    from clipfoundry import brain
    from clipfoundry.api import app
    from clipfoundry.brain import chat, memories

    c = chat.open_chat(WS)
    said = [_say(c["id"], f"remember: {w}")["data"]["memory"]
            for w in ("music at -6 dB", "my intro is 3 seconds", "captions in yellow", "the outro is 2 seconds")]
    assert [m["revision"] for m in said] == [1, 1, 1, 1]
    loud, intro, captions, outro = said
    assert _say(c["id"], "remember: Music at -6 dB!")["data"]["kept"]["id"] == loud["id"]  # said again
    brain.edit(WS, intro["id"], text="my intro is 4 seconds")
    brain.edit(WS, captions["id"], enabled=False)
    older = _twin("Keep the music low", enabled=0)
    over = memories.view(memories.remember(WS, "keep the music low", source="said"))  # what an earlier build showed
    assert over["id"] == older["id"] and over["revision"] == 2
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        def undo(mem: dict, words: str = ""):
            return client.post(f"/api/brain/memories/{mem['id']}/undo", json={"words": words or mem["text"]},
                               headers=H)

        for mem in (loud, intro, captions, over):
            r = undo(mem)
            assert (r.status_code, r.json()["detail"]) == (409, memories.CHANGED_SINCE), mem["text"]
        assert undo(outro, "the outro is 5 seconds").status_code == 409  # not the words its chip shows
        assert client.post(f"/api/brain/memories/{outro['id']}/undo", json={"words": outro["text"]}).status_code == 403
        r = undo(outro)
        assert r.status_code == 200 and r.json()["forgotten"]["id"] == outro["id"]
        assert undo(outro).status_code == 404
    assert sorted(m["text"] for m in brain.list_(WS)) == ["Music at -6 dB!", "captions in yellow",
                                                          "keep the music low", "my intro is 4 seconds"]


def test_a_which_one_button_forgets_exactly_the_words_it_shows_whatever_quotes_they_hold(env):
    """The button sends its memory's words apart from the message, so German, Polish or Swedish quotation marks or an
    inch mark in them change nothing: every memory that says exactly those words goes, never one with fewer or more
    words, and pressed again it says nothing says them any more."""
    from fastapi.testclient import TestClient
    from clipfoundry import brain
    from clipfoundry.api import app
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    words = ["Die Serie heißt „Bergtouren“", "Serien heter ”Fjällturer”", "I edit on a 27” screen",
             "Seria nazywa się „Górskie wędrówki”"]
    for w in words:
        brain.remember(WS, w)
    longer = brain.remember(WS, "Die Serie heißt „Bergtouren“ und läuft sonntags")
    for w in words:
        m = _say(c["id"], f"forget “{w}”", forget=w)
        assert m["text"] == f"Forgotten: “{w}”.", w
        m = _say(c["id"], f"forget “{w}”", forget=w)  # pressed again
        assert m["text"] == f"Nothing I remember says “{w}”, so nothing was forgotten.", w
    assert [x["id"] for x in brain.list_(WS)] == [longer["id"]]
    m = _say(c["id"], "forget “Die Serie heißt”", forget="Die Serie heißt")  # fewer words than the memory says
    assert m["text"].startswith("Nothing I remember says “Die Serie heißt”") and len(brain.list_(WS)) == 1
    _twin("Keep the music low", kind="rule")
    _twin("keep the music low", scope="platform:tiktok", platform="tiktok")
    m = _say(c["id"], "forget “Keep the music low”", forget="Keep the music low")
    assert m["text"] == "Forgotten: “Keep the music low” (I had it 2 times; both are gone)."
    m = _say(c["id"], "forget “”", forget="  ")
    assert m["status"] == "failed" and m["text"].startswith("Say what to forget")
    most = brain.remember(WS, "word " * 119 + "words")  # 600 characters: the most a memory holds
    m = _say(c["id"], "forget “…”", forget=most["text"] + " and more")  # never cut down to a memory's words
    assert m["text"].startswith("Nothing I remember says “word word") and len(brain.list_(WS)) == 2
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        said = len(chat.messages(WS, c["id"]))
        r = client.post(f"/api/brain/chats/{c['id']}/messages", headers=H,  # sent as a quick reply: it never forgets
                        json={"text": "forget “…”", "forget": longer["text"], "choice": True})
        assert r.status_code == 422 and "quick reply cannot forget" in r.json()["detail"]
        assert len(brain.list_(WS)) == 2 and len(chat.messages(WS, c["id"])) == said
        r = client.post(f"/api/brain/chats/{c['id']}/messages", json={"text": "forget “…”", "forget": longer["text"]},
                        headers=H)
        assert r.status_code == 200 and r.json()["ai"]["text"] == f"Forgotten: “{longer['text']}”."
    assert [x["id"] for x in brain.list_(WS)] == [most["id"]]


def test_forget_that_with_the_rule_on_the_next_line_forgets_nothing_whatever_the_line_break(env):
    """A line or paragraph separator, a page break or a vertical tab from a pasted text is a new line too, so “Forget
    that” with the rule on the next line sets something aside and forgets nothing at once."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    brain.remember(WS, "Keep the music low", kind="rule")
    for br in ("\n", "\r", "\r\n", "\u2028", "\u2029", "\x85", "\x0b", "\x0c"):
        m = _say(c["id"], f"Forget that{br}Keep the music low")
        assert m["text"].startswith("Which one?") and len(brain.list_(WS)) == 1, repr(br)
        assert chat.messages(WS, c["id"])[-2]["text"] == "Forget that\nKeep the music low", repr(br)


def test_words_that_name_nothing_keep_nothing_and_never_mind_is_no_rule(env):
    """Without a model, words that only point back, ask nicely or say when or where (“Remember this, please”,
    “Remember that for later”, “Remember that from now on”, “I like that”, “Always.”, “Always for this video”,
    “Always keep that in mind”, “Never do that again”, a quote mark alone) keep nothing and ask what to remember, in
    the general chat and in a video's; “Never mind” is not a rule, and its answer says only what is true of that
    message. Words that name something are kept, with such words around them too, and so is a fact or a rule made
    of everyday words (“I am not in the videos”, “I'm in the US”, “one video at a time”, “one video for every
    project”, “just me”): only turns of speech that point, ask or say when or where name nothing."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    nothing = ("Remember this, please.", "Remember that for later", "Remember that too", "Remember that, ok?",
               "remember: that, please", "remember: this please", "Remember that for next time, thanks!",
               "I like that", "I love this 😍", "Always.", "Never again", "From now on, that.",
               "Remember that from now on", "Remember that always", "Always remember that", "Never forget that",
               "Remember it forever", "Remember that for the next video", "Remember that for the future",
               "Remember that, will you?", "remember: that from now on", "remember: it for the next video",
               "Always for this video.", "Never for this video", "From now on, for this video",
               "I like that for this video", "I want that in this video", "I prefer it for this project",
               "remember: that for this video", "Remember that for this video", "Remember for this video: that",
               "Remember here: 👍", "remember: '", "remember: '👍'", "Remember that ’", "remember: “that”",
               "Always keep that in mind", "remember: keep it in mind, please", "Always bear this in mind",
               "Remember that at all times", "remember: that one for all my videos, ok?", "Never do that again",
               "Always do it for all of my next videos", "Remember this video", "I like this video",
               "Remember everything", "remember: all of them", "Remember that one thing", "Remember that for me",
               "remember: the same thing for the next one, thank you", "Remember that for tomorrow",
               "remember: THAT ONE, PLEASE")
    c, video = chat.open_chat(WS), chat.open_chat(WS, _project(env)["id"])
    for said in nothing:
        for where in (c, video):
            m = _say(where["id"], said)
            assert m["status"] == "failed" and m["text"].startswith("Say what to remember, for example: "), said
    assert _say(c["id"], "Remember: my intro is 3 seconds")["data"]["memory"]["text"] == "my intro is 3 seconds"
    for said in ("Never mind", "never mind.", "Nevermind!"):
        m = _say(c["id"], said)  # said right after a memory was kept: it takes nothing back, and says so
        assert (m["status"], m["text"]) == ("done", chat.NEVER_MIND), said
        assert "did nothing" in m["text"] and "stays as it is" in m["text"] and "Undo" in m["text"]
    assert [x["text"] for x in brain.list_(WS)] == ["my intro is 3 seconds"]
    assert _say(c["id"], "forget my intro is 3 seconds")["text"] == "Forgotten: “my intro is 3 seconds”."
    assert _say(c["id"], "Never mind the shaky shots in the intro")["data"]["tool"] != "remember"
    assert brain.list_(WS) == []
    assert _say(c["id"], "Never zoom in on faces")["data"]["memory"]["kind"] == "rule"
    m = _say(c["id"], "remember: thanks to the drone, the summit shots look great")
    assert m["data"]["memory"]["text"] == "thanks to the drone, the summit shots look great"
    # everyday words that say something: each is kept, whole, in either chat
    everyday = (("remember: I am not in the videos", "I am not in the videos"),
                ("Remember that I am not in my videos", "I am not in my videos"),
                ("I never want to be in the video", "I never want to be in the video"),
                ("I don't want to be in my videos", "I don't want to be in my videos"),
                ("remember: I'm in the US", "I'm in the US"),
                ("remember: my videos are for the US", "my videos are for the US"),
                ("remember: one video at a time", "one video at a time"), ("Always be on time", "Always be on time"),
                ("remember: I'm never in my videos", "I'm never in my videos"),
                ("remember: no one but me is in the videos", "no one but me is in the videos"),
                ("remember: my videos are about me", "my videos are about me"),
                ("remember: my videos are about IT", "my videos are about IT"),
                ("remember: each video is about one thing", "each video is about one thing"),
                ("remember: she/her", "she/her"), ("I hate being in videos", "I hate being in videos"),
                ("I prefer to do one video at a time", "I prefer to do one video at a time"),
                ("Never have me in the video", "Never have me in the video"),
                ("Keep in mind that we are in the UK", "we are in the UK"),
                ("remember: keep all my videos", "keep all my videos"),
                ("remember: it's my last video", "it's my last video"),
                ("Always keep the drone in mind", "Always keep the drone in mind"),
                ("remember: one video for every project", "one video for every project"),
                ("remember: all in one video", "all in one video"), ("remember: just me", "just me"),
                ("remember: just one video", "just one video"),
                ("I want me in every video", "I want me in every video"),
                ("remember: one thing at a time", "one thing at a time"), ("remember: not that one", "not that one"),
                ("remember: every video on time", "every video on time"), ("Never in the US", "Never in the US"))
    for where in (c, video):
        for said, words in everyday:
            m = _say(where["id"], said)
            assert m["status"] == "done" and m["data"]["tool"] == "remember", said
            assert (m["data"].get("memory") or m["data"]["kept"])["text"] == words, said
            assert ("memory" in m["data"]) == (where is c), said  # said again in the video's chat: the same memory
    assert sorted(x["text"] for x in brain.list_(WS)) == sorted(
        [w for _said, w in everyday] + ["Never zoom in on faces", "thanks to the drone, the summit shots look great"])
    assert all(x["scope"] == "all" for x in brain.list_(WS))


def test_a_long_message_of_repeated_words_is_read_at_once(env):
    """What a message names, and where it applies, is read in a few short steps per word, however its words repeat:
    a pattern that tried every way to split “one one one …” into turns of speech would never finish. And “forget”
    with nothing but words it skips (“forget: my my my …”) is read a few ways, not once for every word: each way is
    looked up in the memory, which took seconds."""
    import time

    from clipfoundry.brain import chat, memories

    c, video = chat.open_chat(WS), chat.open_chat(WS, _project(env)["id"])
    units = ("one ", "the one ", "that ", "for all of my ", "all of that ", "do the same one thing ", "never ",
             "not only here ", "from here on ", "this video ", "every other ", "keep ", "' ", ":) ", "here: ", "my ",
             "the rule about ", "please ", ", ", "like this one ", "never again ", "too. ")
    start = time.monotonic()
    for unit in units:
        words = (unit * (chat.MAX_TEXT // len(unit)))[:chat.MAX_TEXT - 20]
        for said in (words, words + "zebra", "x " + words):
            chat._names_nothing(said), memories.points_here(said), chat._kept_words("p1", said)
            assert len(chat._named(said)) <= chat._FORMS, unit
            assert len(chat._said("forget " + said)[0]) <= chat._FORMS, unit
    took = time.monotonic() - start
    assert took < 10, took  # a fraction of a second, even on a slow machine
    start = time.monotonic()
    for said in ("remember: " + "one " * 900 + "z", "Always " + "the one " * 400, "forget " + "that " * 700 + "z",
                 "forget: " + "my " * 1300 + "x", "forget , " + "my " * 1300, "forget " + "the rule about " * 250):
        for where in (c, video):
            assert _say(where["id"], said)["status"] in ("done", "failed")
    took = time.monotonic() - start
    assert took < 15, took  # well under a second; read once for every word, the “forget” ones alone took 20 s


def test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole(env):
    """In a video's chat, words that point at this video keep the memory to it: “this video”, “this project” or “this
    one” (with or without “for”, “in” or “on”), a piece of it (“this clip”, “these shots”) and “here” as a word of
    its own, whatever follows (“here, please”, “here too”, a smiley, a bracket). Such words can only be read in this
    video's chat, so they stay with it also when they speak of other videos or of later, or liken something to it
    (“this video is private, never upload it again” was kept for every video, where “this video” is another one):
    then the answer says why, and how to say them for every video (with the video's name, or which clip). The
    words are kept as said: nothing is cut out of them (“never zoom in here” was kept as “never zoom”, “in this
    video's intro” as “'s intro”), and only a label in front, set apart by a colon, a comma or a spaced dash, is
    left out. “here's”, a title with a capital “Here”
    and other things said with “this” are other words, as are words that only bring on what follows (“this one
    thing: …”, “here is …”), and “not only this video”, “not just here” and “from here on” where it means from now
    on reach further: those are kept for every video."""
    from clipfoundry import brain
    from clipfoundry.brain import chat

    p = _project(env)
    c = chat.open_chat(WS, p["id"])
    whole = ("-3 dB here", "-2 dB on the voice for this video", "the music is too loud in here",
             "no captions here, please", "keep the music low here too", "no music here 🙂", "no music here, thanks",
             "no music here for now", "no captions here,", "no titles (here)", "the music here is too loud",
             "use the drone shot here instead", "never zoom in here", "no voice over here",
             "the logo goes top right here", "the caption sits on the right here", "the music should fade in here",
             "the music in this video's intro is too loud", "slow motion only for this one clip",
             "zoom in on this one shot", "the logo goes here!", "the banner goes here...",
             "no captions on this one, ever", "captions in yellow (for this video)",
             "keep the music low – for this video", "this video is for kids", "NO SUBTITLES HERE",
             "Here, There and Everywhere is the outro song", "keep this video under 60 s",
             "I want this video to be fun", "this project is due on Friday", "this video's title is Hike 2",
             "this video needs the intro again", "the next clip in this video is the summit",
             "all the clips of this video are vertical", "my office is here in Lyon", "this one is for kids",
             "keep this one under 60 s", "this clip is the best take", "these shots are out of focus",
             "this scene needs music", "from this shot on, the grade is warmer", "keep this project under a minute",
             "as for this video, keep it short", "this one time I want captions", "the plan is here in this chat")
    for words in whole:
        m = _say(c["id"], f"remember: {words}")
        assert m["text"] == f"Remembered: “{words}”. It applies to this video. Say “forget …” to remove it.", words
        assert m["data"]["memory"]["scope"] == f"project:{p['id']}"
    labelled = (("Note for this video: -14 LUFS", "-14 LUFS"),
                ("Remember for this video - keep the voice up", "keep the voice up"),
                ("Remember for this video – keep the b-roll short", "keep the b-roll short"),
                ("remember: only for this video: keep the cuts slow", "keep the cuts slow"),
                ("remember: for this video only - keep the titles small", "keep the titles small"),
                ("remember: on this one, the hero is my dog", "the hero is my dog"),
                ("Remember here: the drone shots go first", "the drone shots go first"),
                ("remember: for this video: never use that song again", "never use that song again"),
                ("Never pan in here", "Never pan in here"), ("Always fade in here.", "Always fade in here"),
                ("I want the logo top right here", "I want the logo top right here"),
                ("Never use captions here, please", "Never use captions here, please"))
    for said, words in labelled:
        m = _say(c["id"], said)
        assert m["text"] == f"Remembered: “{words}”. It applies to this video. Say “forget …” to remove it.", said
    # they also speak of other videos or of later, or liken something to this one: kept here, and the answer says why
    hinted = (("Never use the music from this video again", "this video"),
              ("use this video as the template for the next ones", "this video"),
              ("From now on, make every intro like this video's intro", "this video"),
              ("the next videos should be shorter than this video", "this video"),
              ("use more b-roll than in this video", "this video"),
              ("unlike here, the other intros stay under 5 s", "here"),
              ("next time, start like this video", "this video"), ("don't use this video's font again", "this video"),
              ("in future, grade like this project", "this project"),
              ("use this video's intro for all my other videos", "this video"),
              ("this video is the template for each new one", "this video"),
              ("for all my videos, keep the captions like in this video", "this video"),
              ("Always cut the intro like in this video", "this video"),
              ("this video is private, never upload it again", "this video"),
              ("unlike my other videos, this video has no intro", "this video"),
              ("Never touch this video again", "this video"),
              ("this project has five clips, keep every one under 10 s", "this project"),
              ("starting with this video, captions are yellow", "this video"),
              ("make them all like this one", "this one"), ("every video should open like THIS ONE", "THIS ONE"),
              ("Never use the music from here again", "here"), ("the same pace as in this video", "this video"),
              ("from this video on, captions are yellow", "this video"),
              ("from this one onwards, no stock music", "this one"),
              ("put the logo from this video on the thumbnail", "this video"),
              ("put the logo from here on the thumbnail", "here"),
              ("Never use this clip again", "this clip"), ("cut every scene like these shots", "these shots"),
              ("for this video: use this scene in the next ones too", "this scene"))
    for words, points in hinted:
        m = _say(c["id"], words if words.startswith(("Never ", "From now on", "Always ")) else f"remember: {words}")
        words = words.removeprefix("for this video: ")  # a label in front is left out
        piece = points.split()[-1] if points.endswith(("clip", "shots", "scene")) else ""
        instead = f"which {piece}" if piece else "the video's name (“Hike”)"
        assert m["text"] == (f"Remembered: “{words}”. It applies to this video only, because it says “{points}”. To "
                             f"keep it for every video, say {instead} instead. Say “forget …” to remove it."), words
        assert m["data"]["memory"]["scope"] == f"project:{p['id']}"
    m = _say(c["id"], "remember: use this video as the template for the next ones")  # said again: the same answer
    assert m["text"].startswith("I already remember “use this video as the template for the next ones”. It applies "
                                "to this video only, because it says “this video”. To keep it for every video, say")
    every = ("here's the plan: intro 3 s", "Here Comes the Sun is the outro song", "where the summit is",
             "Always keep the voice up in every video, not only this video",
             "this applies to all videos, not only this project: no stock music",
             "from here on, captions are always yellow", "From here on out, no stock music",
             "the titles are white from here on", "From here on the grade is warm", "no zooms from here onwards",
             "Always keep the voice up, not only in this video", "no stock music anywhere, not just here",
             "keep the voice up, not only this video", "not just this project: no stock music",
             "I like this channel's look", "use this font for the titles", "Never use the music from Hike again",
             "this video-game series is for teens", "as for the outro: 5 s",
             "this one thing: I want no red captions", "follow this one rule: no stock music",
             "here is how I like my intros: fast cuts", "here are my channel colours: teal and white")
    for words in every:
        m = _say(c["id"], words if words.startswith(("Never ", "From now on", "Always ")) else f"remember: {words}")
        assert m["text"] == f"Remembered: “{words}”. It applies to every video. Say “forget …” to remove it.", words
    g = chat.open_chat(WS)  # the general chat has no video to keep it to: the words stay whole there too
    m = _say(g["id"], "remember: for this video: keep the outro short")
    assert m["text"].startswith("Remembered: “for this video: keep the outro short”. It applies to every video.")
    m = _say(g["id"], "remember: this video is for my sister, never share it again")
    assert m["text"] == ("Remembered: “this video is for my sister, never share it again”. It applies to every video. "
                         "Say “forget …” to remove it.")
    assert len(brain.list_(WS)) == len(whole) + len(labelled) + len(hinted) + len(every) + 2
    assert sum(x["scope"] == "all" for x in brain.list_(WS)) == len(every) + 2


def test_the_same_words_said_in_two_videos_are_kept_for_each_of_them(env):
    """A note said for one video stays with it. The same words said in another video's chat are a memory of their
    own, with its own Undo (they used to take the first video's note away: “I already remember … (before, only for
    another video). It applies to this video.”). Said again in the same chat they are there already. “forget” and
    the words, typed or picked from “Which one?” in one video's chat, forgets that video's note and says that the
    other video's stays; when only the other video keeps the words, they name that note, and it goes. Said in the
    general chat the words are kept for every video (the oldest widens, and the answer says what it was before),
    and there “forget” forgets each memory that says them."""
    from clipfoundry import brain, db
    from clipfoundry.brain import chat, memories

    a = _project(env)
    b = db.insert("studio_projects", {"workspace_id": WS, "name": "Beach", "status": "ready"})
    ca, cb, g = chat.open_chat(WS, a["id"]), chat.open_chat(WS, b["id"]), chat.open_chat(WS)
    kept = {}
    for said, words in (("remember: no captions here", "no captions here"),
                        ("remember: this video is for kids", "this video is for kids"),
                        ("remember: for this video: keep the cuts slow", "keep the cuts slow"),
                        ("Never zoom in here", "Never zoom in here")):
        first, second = _say(ca["id"], said), _say(cb["id"], said)
        for m, p in ((first, a), (second, b)):
            assert m["text"] == f"Remembered: “{words}”. It applies to this video. Say “forget …” to remove it.", said
            assert m["data"]["memory"]["scope"] == f"project:{p['id']}" and m["data"]["memory"]["revision"] == 1
        kept[words] = (first["data"]["memory"], second["data"]["memory"])
        assert kept[words][0]["id"] != kept[words][1]["id"]
        again = _say(cb["id"], said)  # said again in the second video's chat: that video's own memory
        assert again["text"] == f"I already remember “{words}”. It applies to this video. Say “forget …” to remove it."
        assert again["data"]["kept"]["id"] == kept[words][1]["id"] and "memory" not in again["data"]
        mine = memories.get(WS, kept[words][0]["id"])  # the first video's note is as it was
        assert (mine["scope"], mine["revision"], mine["text"]) == (f"project:{a['id']}", 1, words)
    assert len(brain.list_(WS)) == 8
    for p, n in ((a, 0), (b, 1)):  # each video reads its own
        got = memories.recall("captions", WS, project_id=p["id"])
        assert [m["id"] for m in got.memories if m["text"] == "no captions here"] == [kept["no captions here"][n]["id"]]
    # Undo on the first video's answer forgets that video's note only (it is as its answer added it)
    gone = memories.undo(WS, kept["keep the cuts slow"][0]["id"], "keep the cuts slow")
    assert gone["id"] == kept["keep the cuts slow"][0]["id"]
    assert [m["scope"] for m in memories.saying(WS, "keep the cuts slow")] == [f"project:{b['id']}"]
    # "forget" and the words in one video's chat is about that video: the other video's note stays, and it says so
    m = _say(cb["id"], "forget this video is for kids")
    assert m["text"] == "Forgotten: “this video is for kids”. Another video keeps the same words: its note stays."
    assert m["data"]["forgotten"]["id"] == kept["this video is for kids"][1]["id"]
    assert [x["id"] for x in memories.saying(WS, "this video is for kids")] == [kept["this video is for kids"][0]["id"]]
    m = _say(cb["id"], "forget this video is for kids")  # now only the other video keeps them: they name its note
    assert m["text"] == "Forgotten: “this video is for kids”." and memories.saying(WS, "this video is for kids") == []
    # "Which one?" lists what a pick forgets, and its button forgets that: this video's note
    m = _say(ca["id"], "forget zoom")
    assert m["text"] == "Which one? I will forget the one you pick:\n- [rule] Never zoom in here"
    assert [x["id"] for x in m["data"]["candidates"]] == [kept["Never zoom in here"][0]["id"]]
    m = _say(ca["id"], "forget “Never zoom in here”", forget="Never zoom in here")
    assert m["text"] == "Forgotten: “Never zoom in here”. Another video keeps the same words: its note stays."
    assert [x["scope"] for x in memories.saying(WS, "Never zoom in here")] == [f"project:{b['id']}"]
    # in the general chat there is no video: kept for every video, the oldest widens and the answer says so
    m = _say(g["id"], "remember: no captions here")
    assert m["text"] == ("I already remember “no captions here” (before, only for another video). It applies to every "
                         "video. Say “forget …” to remove it.")
    assert m["data"]["kept"]["id"] == kept["no captions here"][0]["id"]
    assert sorted(x["scope"] for x in memories.saying(WS, "no captions here")) == ["all", f"project:{b['id']}"]
    m = _say(cb["id"], "remember: no captions here")  # the second video's own is still its own
    assert m["data"]["kept"]["id"] == kept["no captions here"][1]["id"]
    m = _say(ca["id"], "forget no captions here")  # the one for every video applies here; the other video's stays
    assert m["text"] == "Forgotten: “no captions here”. Another video keeps the same words: its note stays."
    _say(ca["id"], "remember: no captions here")
    m = _say(g["id"], "forget no captions here")  # the general chat: each memory that says the words
    assert m["text"] == "Forgotten: “no captions here” (I had it 2 times; both are gone)."
    assert sorted((x["text"], x["scope"]) for x in brain.list_(WS)) == [
        ("Never zoom in here", f"project:{b['id']}"), ("keep the cuts slow", f"project:{b['id']}")]


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
