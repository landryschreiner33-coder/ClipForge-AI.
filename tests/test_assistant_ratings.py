"""👍 and 👎 on ClipForge AI's answers (brain/ratings.py): a rating lives in its answer and goes with its chat; the
next answers read the liked answer to a question like theirs, the reasons given for 👎 and a disliked answer to a
very similar question; a helper's ratings teach that helper only. A fake model answers; nothing leaves the
computer."""
from __future__ import annotations

import pytest
from fake_model import WS, answers_finish, install, say, settled  # noqa: F401

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def _answer(chat_id: str, said: str) -> dict:
    from clipfoundry.brain import chat

    return settled(chat_id, chat.send(WS, chat_id, said)["ai"]["id"])


def _system(text: str, agent: dict | None = None) -> str:
    from clipfoundry import db
    from clipfoundry.brain import assistant, chat

    c = chat.open_chat(WS)
    return assistant.system_prompt(WS, c, text, [], db.get_settings(), agent=agent)[0]


def test_a_rating_is_kept_in_its_answer_and_can_be_taken_back(data, monkeypatch):
    from clipfoundry.brain import chat, ratings

    install(monkeypatch, say("Open on the crash, then explain."))
    c = chat.open_chat(WS)
    m = _answer(c["id"], "How should I start my biking video?")
    rated = ratings.rate(WS, c["id"], m["id"], True)
    assert rated["data"]["rating"]["good"] is True and rated["data"]["rating"]["why"] == ""
    assert rated["data"]["rating"]["question"] == "How should I start my biking video?"
    bad = ratings.rate(WS, c["id"], m["id"], False, "  too   short ")
    assert bad["data"]["rating"]["why"] == "too short" and bad["data"]["rating"]["good"] is False
    assert "rating" not in ratings.rate(WS, c["id"], m["id"], None)["data"]
    owner = chat.messages(WS, c["id"])[0]
    with pytest.raises(ratings.RatingError, match="Only ClipForge AI's answers"):
        ratings.rate(WS, c["id"], owner["id"], True)
    with pytest.raises(ratings.RatingError, match="not there any more"):
        ratings.rate(WS, chat.new_chat(WS)["id"], m["id"], True)  # another chat's answer
    with pytest.raises(chat.ChatError, match="Chat not found"):
        ratings.rate("someone-else", c["id"], m["id"], True)
    chat.clear(WS, c["id"])
    assert ratings.rated(WS) == []  # it went with its chat


def test_the_page_rates_an_answer(data, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.brain import chat

    install(monkeypatch, say("Post at 6 pm."))
    c = chat.open_chat(WS)
    m = _answer(c["id"], "When should I post?")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        r = client.post(f"/api/brain/chats/{c['id']}/messages/{m['id']}/rating", json={"good": False,
                                                                                      "why": "say why 6 pm"},
                        headers=H)
        assert r.status_code == 200 and r.json()["data"]["rating"]["why"] == "say why 6 pm"
        r = client.post(f"/api/brain/chats/{c['id']}/messages/nope/rating", json={"good": True}, headers=H)
        assert r.status_code == 404


def test_the_next_answers_read_what_the_owner_liked_and_disliked(data, monkeypatch):
    from clipfoundry.brain import chat, ratings

    install(monkeypatch, say("Open on the biggest jump, then the trail map."),
            say("Here are 12 ideas, in no order, for intros of every kind."))
    c = chat.open_chat(WS)
    liked = _answer(c["id"], "How should I start my mountain biking video?")
    ratings.rate(WS, c["id"], liked["id"], True)
    disliked = _answer(c["id"], "Give me intro ideas for my skate video")
    ratings.rate(WS, c["id"], disliked["id"], False, "too long, give me three")
    system = _system("how should I start my next mountain biking video")
    assert "An answer the owner liked (👍)" in system and "Open on the biggest jump" in system
    assert "- “too long, give me three” (about “Give me intro ideas for my skate video”)" in system
    assert "Your answer to a question very like this one" not in system
    again = _system("give me intro ideas for my skate video please")
    assert "Here are 12 ideas" in again and "Answer differently: too long, give me three." in again
    other = _system("what is the weather like")  # nothing alike: only the reasons, which always apply
    assert "An answer the owner liked" not in other and "too long, give me three" in other


def test_a_helpers_ratings_teach_that_helper_only(data, monkeypatch):
    from clipfoundry.brain import agents, chat, ratings

    writer = agents.add(WS, template="script_writer")
    install(monkeypatch, say("Hook: “I almost didn't make it down.”"))
    c = chat.open_chat(WS)
    m = _answer(c["id"], "@Script writer write a hook for my mountain biking video")
    assert m["role"] == "agent"
    ratings.rate(WS, c["id"], m["id"], True)
    assert "almost didn't make it down" in _system("write a hook for my mountain biking video", writer)
    assert "almost didn't make it down" not in _system("write a hook for my mountain biking video")
    assert ratings.rated(WS) == [] and len(ratings.rated(WS, writer["id"])) == 1
