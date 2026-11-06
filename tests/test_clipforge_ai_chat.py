"""ClipForge AI's chat (docs/clipforge/CLIPFORGE_AI.md, "The chat"): teaching, forgetting, listing and explaining
work without a model; a video's chat makes checked proposals; the general chat asks the model with the memories
it recalled, and every answer records what it used. A fake model stands in; nothing leaves the machine."""
from __future__ import annotations

import json
import threading
import time

import pytest

from test_studio_edit_requests import _plan, _project, env  # noqa: F401

H = {"X-ClipFoundry": "1"}
WS = "local"


class FakeHelper:
    """Stands in for llm.complete: records every call, answers from a script, can block until released."""

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


def _helper(monkeypatch, *answers, **settings) -> FakeHelper:
    from clipfoundry import db
    from clipfoundry.pipeline import llm

    fake = FakeHelper(*answers)
    monkeypatch.setattr(llm, "complete", fake)
    db.save_settings({"ai_provider": "ollama", "ollama_url": "http://localhost:11434", **settings})
    return fake


def _say(chat_id: str, text: str, **kw) -> dict:
    from clipfoundry.brain import chat

    return chat.send(WS, chat_id, text, **kw)["ai"]


def _settled(chat_id: str, message_id: str, timeout: float = 5.0) -> dict:
    from clipfoundry.brain import chat

    end = time.time() + timeout
    while time.time() < end:
        m = [m for m in chat.messages(WS, chat_id) if m["id"] == message_id][0]
        if m["status"] != "thinking":
            return m
        time.sleep(0.02)
    raise AssertionError("still thinking")


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

    m = _say(c["id"], "what do you know")
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

    assert _say(c["id"], "help")["text"] == chat.HELP
    assert _say(c["id"], "why?")["data"]["tool"] == "explain"
    m = _say(c["id"], "how long should my intros be?")  # a question, with no model set up
    assert m["data"]["tool"] == "answer" and m["status"] == "done" and "Settings → ClipForge AI" in m["text"]
    with pytest.raises(chat.ChatError):
        chat.send(WS, c["id"], "   ")
    with pytest.raises(chat.ChatError):
        chat.send(WS, c["id"], "x" * 501)
    with pytest.raises(chat.ChatError):
        chat.send("other", c["id"], "hello")  # another workspace's chat
    with pytest.raises(chat.ChatError):
        chat.open_chat(WS, "no-such-video")

    msgs = chat.messages(WS, c["id"])
    assert [m["role"] for m in msgs][:2] == ["owner", "ai"] and msgs[0]["text"] == "Remember: my intro is 3 seconds."
    assert chat.messages(WS, c["id"], after=msgs[-3]["id"]) == msgs[-2:]
    assert chat.clear(WS, c["id"]) == len(msgs) and chat.messages(WS, c["id"]) == []


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
    from clipfoundry import brain, db
    from clipfoundry.brain import chat

    fake = _helper(monkeypatch, json.dumps({"summary": "Keep the lunch story together.",
                                            "operations": [{"op": "move", "clip_id": "c4", "after": "c2"}]}))
    brain.remember(WS, "Never move the summit part", kind="rule")
    p = _project(env)
    c = chat.open_chat(WS, p["id"])
    fake.gate.clear()
    m = _say(c["id"], "Keep the second story together")
    assert m["status"] == "thinking" and m["text"].startswith("Asking the AI service")
    assert [x["text"] for x in m["data"]["used"]] == ["Never move the summit part"]
    assert m["data"]["request"]["status"] == "thinking"
    fake.gate.set()
    m = _settled(c["id"], m["id"])
    assert m["status"] == "done" and m["data"]["request"]["status"] == "ready"
    assert m["text"].startswith("Keep the lunch story together.") and "New order: 1, 2, 4, 3" in m["text"]
    assert db.fetch("brain_chat_messages", m["id"])["status"] == "done"  # the finished state is kept
    prompt, kw = fake.calls[0]
    assert kw["task"] == "edit_proposal" and "- [rule] Never move the summit part" in prompt
    m = _say(c["id"], "what did you use?")
    assert "answered by Ollama" in m["text"] and "[rule] Never move the summit part" in m["text"]
    assert "What I proposed: Keep the lunch story together." in m["text"]


def test_the_general_chat_asks_the_ai_helper_with_its_memories_and_checks_the_answer(env, monkeypatch):
    from clipfoundry import brain, db
    from clipfoundry.brain import chat
    from clipfoundry.pipeline import llm

    fake = _helper(monkeypatch, json.dumps({"say": "About 3 seconds, as you told me."}), "not json at all",
                   llm.ProviderError("the helper is down"), json.dumps({"say": "x" * 5000}),
                   ai_edit_requests_per_day=4)
    brain.remember(WS, "my intro is 3 seconds")
    brain.remember(WS, "Never zoom in on faces", kind="rule")
    c = chat.open_chat(WS)
    m = _say(c["id"], "how long should my intro be?")
    assert m["status"] == "thinking" and m["text"] == "Thinking…" and m["data"]["tool"] == "answer"
    assert m["data"]["provider"].startswith("Ollama") and m["data"]["sent"].startswith("Stays on this computer")
    assert "Never your videos" in m["data"]["sent"]
    assert [x["text"] for x in m["data"]["used"]] == ["Never zoom in on faces", "my intro is 3 seconds"]
    m = _settled(c["id"], m["id"])
    assert m["status"] == "done" and m["text"] == "About 3 seconds, as you told me."
    prompt, kw = fake.calls[0]
    assert kw["system"] == chat.SYSTEM and kw["task"] == "chat" and kw["json_object"] is True
    assert kw["num_ctx"] == 8192 and kw["max_tokens"] == 600 and kw["timeout"] >= 60
    assert prompt.startswith(brain.memories.HEADER) and "- [fact] my intro is 3 seconds" in prompt
    assert prompt.endswith("<<<how long should my intro be?>>>")
    assert [u["where_used"] for u in db.select("brain_memory_uses", "ref_id = ?", (m["id"],))] == ["chat", "chat"]

    m = _settled(c["id"], _say(c["id"], "and the outro?")["id"])
    assert m["status"] == "failed" and m["text"].startswith("My model did not answer with JSON.")
    m = _settled(c["id"], _say(c["id"], "and the music?")["id"])
    assert m["status"] == "failed" and "could not answer: the helper is down" in m["text"]
    m = _settled(c["id"], _say(c["id"], "and the captions?")["id"])
    assert m["status"] == "done" and len(m["text"]) == chat.ANSWER_CHARS  # a long answer is cut, never refused
    m = _say(c["id"], "one more?")
    assert m["status"] == "failed" and "Today's limit of 4 AI requests" in m["text"] and len(fake.calls) == 4

    # a restart while an answer was waiting: reported, never asked again
    db.insert("brain_chat_messages", {"chat_id": c["id"], "workspace_id": WS, "role": "ai", "text": "Thinking…",
                                      "data": {"tool": "answer"}, "status": "thinking"})
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
