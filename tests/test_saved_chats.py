"""Saved chats: as many general chats as you like, each named after the first thing said in it (or the name you give
it), kept across restarts with the actions taken in it; switching, renaming and deleting through the API."""
from __future__ import annotations

from test_clipforge_ai_chat import H, WS, _say
from test_studio_edit_requests import env  # noqa: F401


def test_chats_are_created_switched_renamed_and_deleted(env):
    from clipfoundry import db
    from clipfoundry.brain import chat

    first = chat.open_chat(WS)
    _say(first["id"], "Remember: my intro is 3 seconds.")
    assert chat.get_chat(WS, first["id"])["title"] == "Remember: my intro is 3 seconds."
    second = chat.new_chat(WS)
    assert second["id"] != first["id"] and second["title"] == "ClipForge AI"
    _say(second["id"], "never zoom in on faces")
    listed = chat.list_chats(WS)
    assert [c["id"] for c in listed] == [second["id"], first["id"]]       # the one used last first
    assert listed[0]["messages"] == 2 and listed[0]["last"]
    assert chat.open_chat(WS)["id"] == second["id"]                     # opening without an id: the one used last
    assert chat.open_chat(WS, chat_id=first["id"])["id"] == first["id"]  # switching
    assert [m["role"] for m in chat.messages(WS, first["id"])] == ["owner", "ai"]
    # a name you give stays; later messages do not rename it
    chat.rename(WS, first["id"], "  Intro\nrules  ")
    _say(first["id"], "I like warm colours")
    named = chat.get_chat(WS, first["id"])
    assert named["named"] == 1 and named["title"] == "Intro rules"
    # deleting removes the conversation only: what was done in it stays (the memories it saved)
    from clipfoundry import brain

    kept = len(brain.list_(WS))
    gone = chat.delete_chat(WS, first["id"])
    assert gone["messages"] == 4 and db.fetch("brain_chats", first["id"]) is None
    assert not db.select("brain_chat_messages", "chat_id = ?", (first["id"],))
    assert len(brain.list_(WS)) == kept
    assert [c["id"] for c in chat.list_chats(WS)] == [second["id"]]


def test_a_video_chat_is_not_a_saved_chat_and_another_workspace_sees_nothing(env):
    import pytest

    from clipfoundry.brain import chat

    mine = chat.new_chat(WS)
    with pytest.raises(chat.ChatError):
        chat.open_chat("other", chat_id=mine["id"])
    with pytest.raises(chat.ChatError):
        chat.rename("other", mine["id"], "x")
    with pytest.raises(chat.ChatError):
        chat.delete_chat("other", mine["id"])
    assert chat.list_chats("other") == []
    with pytest.raises(chat.ChatError):
        chat.rename(WS, mine["id"], "   ")


def test_the_chat_routes(env):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    c = TestClient(app)
    a = c.post("/api/brain/chats", json={}, headers=H).json()
    b = c.post("/api/brain/chats/new", headers=H).json()
    c.post(f"/api/brain/chats/{a['id']}/messages", json={"text": "Remember: I post at 6 pm."}, headers=H)
    listed = c.get("/api/brain/chats", headers=H).json()
    assert {x["id"] for x in listed} == {a["id"], b["id"]} and listed[0]["id"] == a["id"]
    opened = c.post("/api/brain/chats", json={"chat_id": b["id"]}, headers=H).json()
    assert opened["id"] == b["id"] and opened["messages"] == []
    r = c.patch(f"/api/brain/chats/{b['id']}", json={"title": "Thumbnails"}, headers=H)
    assert r.status_code == 200 and r.json()["title"] == "Thumbnails"
    assert c.delete(f"/api/brain/chats/{b['id']}", headers=H).json()["deleted"] == b["id"]
    assert c.post("/api/brain/chats", json={"chat_id": b["id"]}, headers=H).status_code == 404
    assert c.patch("/api/brain/chats/nope", json={"title": "x"}, headers=H).status_code == 404
