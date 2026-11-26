"""ClipForge AI does what the owner asks without an OK button (Landry, Nov 26: "no i want it to be able to do it on its
own you dont have to say ok"): its new commands (edit a post's text, approve and post a YouTube post, the owner's own
clip text, trim and edit a clip, clips from a link, a mission, a Text Story, Autopilot, posting rules), each through
the app's own action. Deleting still waits for the OK, a TikTok post still needs the owner's OK on its page, and with
Settings → ClipForge AI → "Ask me first" every change is a button again. Fake platforms only: nothing is posted."""
from __future__ import annotations

import os
import time

import pytest
from fake_model import WS, install, say, settled
from quality_stub import passed_report
from test_assistant_commands import clip, ctx, data, press, tool, two_posts  # noqa: F401 - shared fixtures
from test_multi_accounts import env  # noqa: F401 - fake Google/TikTok
from test_post_to_channels import add_channel


def _youtube_post(tmp, connection_id: str, title: str = "Bass on the first cast", status: str = "awaiting_approval",
                  platform: str = "youtube") -> dict:
    from clipfoundry import db

    video = tmp / f"alone-{time.time_ns()}.mp4"
    video.write_bytes(os.urandom(4096))
    project = db.create_project("Fishing trip", status="ready", origin="autopilot")
    clip_row = db.create_clip(project["id"], start=0, end=20, title=title, status="ready", output_path=str(video),
                              duration=20.0, caption_text="Bass on the first cast.", score=72.0)
    passed_report(clip_row)
    return db.insert("scheduled_publications", {
        "clip_id": clip_row["id"], "platform": platform, "title": title, "description": "Bass on the first cast.",
        "tags": ["fishing"], "privacy": "private" if platform == "youtube" else "SELF_ONLY",
        "options": {"made_for_kids": False}, "connection_id": connection_id, "planned_at": time.time() + 7200,
        "status": status, "final_score": 70})


# ------------------------------------------------------------------ the commands
def test_the_new_commands_run_at_once_but_deleting_never_does():
    from clipfoundry.brain import assistant, operations, tools

    new = {"edit_post", "approve_post", "set_clip_text", "edit_clip", "make_clips", "start_mission",
           "write_text_story", "autopilot"}
    assert new <= operations.COMMANDS
    for name in operations.COMMANDS:
        t = tools.get(name)
        assert t.risk != "delete" and (t.alone or t.risk != "change"), name
        assert not t.for_agents or t.risk == "look", name  # helpers never get them
    assert not [t.name for t in tools.all_tools() if t.alone and t.risk == "delete"]
    with pytest.raises(ValueError, match="only a change"):
        tools.Tool("x_delete", "x", {"type": "object"}, lambda c, a: None, "delete", alone=True)
    assert "approve_post" in assistant.rules({}) and "never publish" not in assistant.rules({})
    asking = assistant.rules({"ai_acts_alone": False})
    assert "never publish or approve a post" in asking and "only happens when they press OK" in asking
    assert tools.signature(tools.get("edit_post"), True).endswith("Done at once.")
    assert tools.signature(tools.get("edit_post"), False).endswith("Waits for the owner's OK.")


def test_edit_a_planned_posts_own_title_and_hashtags(data):
    from clipfoundry import db

    a, b = two_posts(data)
    card, done = press("edit_post", {"post": "lake swim", "title": "I jumped in the coldest lake",
                                     "hashtags": "#lake #ColdWater swim lake"})
    assert card["label"].startswith("Change “Lake swim” on YouTube: title “I jumped in the coldest lake”")
    row = db.fetch("scheduled_publications", b["id"])
    assert row["title"] == "I jumped in the coldest lake"
    assert row["tags"] == ["lake", "ColdWater", "swim"]  # YouTube tags: no #, one of each whatever the case
    assert row["audit"][-1]["event"] == "edited" and "coldest lake" in done.text


def test_approve_and_post_a_youtube_post_with_the_post_pages_checks(env):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.autopilot import queue
    from clipfoundry.brain.tools import ToolError

    google, _tik, tmp = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_min_gap_minutes": 0})
    chan = add_channel(google, "UCfish", "Fishing channel")
    item = _youtube_post(tmp, chan["id"])
    card, done = press("approve_post", {"post": "bass first cast"})
    assert card["label"] == "Approve “Bass on the first cast” on YouTube (Fishing channel)" and not card["blocked"]
    row = db.fetch("scheduled_publications", item["id"])
    assert row["status"] == "approved" and row["approval"]["by"] == "you"
    assert row["audit"][-1]["detail"] == "Approved by ClipForge AI"  # the post's history says who approved it
    card, done = press("approve_post", {"post": "bass first cast", "now": True})
    assert card["label"].startswith("Post “Bass on the first cast”") and "goes out now" in " ".join(card["detail"])
    assert db.fetch("scheduled_publications", item["id"])["status"] == "publishing"
    assert queue.get(db.fetch("worker_jobs", f"publish:{item['id']}", "idem_key")["id"])["kind"] == "publish"
    assert done.data["work"][0]["kind"] == "post"

    # what the post page would ask for first stops it, and says what to do
    other = _youtube_post(tmp, chan["id"], "Second cast")
    db.update("scheduled_publications", other["id"], options={"made_for_kids": None})
    card = tool("approve_post").preview(ctx(), {"post": "second cast"})
    assert "answer “made for kids” on its page" in card["blocked"]
    with pytest.raises(ToolError, match="made for kids"):
        tool("approve_post").run(ctx(), {"post": other["id"]})
    assert db.fetch("scheduled_publications", other["id"])["status"] == "awaiting_approval"


def test_a_tiktok_post_always_waits_for_the_owners_ok_on_its_page(env):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    _g, _t, tmp = env
    item = _youtube_post(tmp, "", "Tiny trout", platform="tiktok")
    card = tool("approve_post").preview(ctx(), {"post": "tiny trout"})
    assert "TikTok's rules for apps need your own OK on every post" in card["blocked"]
    with pytest.raises(ToolError, match="TikTok's rules"):
        tool("approve_post").run(ctx(), {"post": item["id"]})
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"


def test_the_owners_own_clip_text_and_a_trim_go_through_the_clip_editor(clip):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    card, done = press("set_clip_text", {"project": "running podcast", "clip": "1", "title": "Why I run at 5am",
                                         "hashtags": "running #Morning"})
    fresh = db.get_clip(clip["id"])
    assert fresh["title"] == "Why I run at 5am" and fresh["hashtags"] == ["#running", "#Morning"]
    length = clip["end"] - clip["start"]
    card, done = press("edit_clip", {"project": "running podcast", "clip": "1", "cut_start": 1.5, "cut_end": 1,
                                     "captions": False, "volume_db": 3})
    fresh = db.get_clip(clip["id"])
    assert fresh["edit"]["start"] == round(clip["start"] + 1.5, 2) and fresh["edit"]["end"] == round(clip["end"] - 1, 2)
    assert fresh["edit"]["captions_enabled"] is False and fresh["edit"]["gain_db"] == 3.0
    assert fresh["status"] == "queued" and done.data["work"][0]["id"] == clip["id"]
    assert f"was {length:.1f}" in card["label"]
    with pytest.raises(ToolError, match="a clip needs at least 3"):
        tool("edit_clip").preview(ctx(), {"project": "running podcast", "clip": "1", "cut_end": length})
    card, done = press("edit_clip", {"project": "running podcast", "clip": "1", "keep": False})
    assert db.get_clip(clip["id"])["selected"] == 0 and not done.data["work"]  # no render for a pick


def test_clips_from_a_link_a_mission_and_autopilot(data, monkeypatch):
    from clipfoundry import api, db
    from clipfoundry.brain.tools import ToolError

    pytest.importorskip("yt_dlp")
    card, done = press("make_clips", {"link": "please clip https://example.com/watch?v=abc."})
    assert card["args"]["link"] == "https://example.com/watch?v=abc"
    project = db.get_project(done.data["work"][0]["id"])
    assert project["source_url"] == "https://example.com/watch?v=abc" and project["status"] == "queued"
    assert any(key == project["id"] for _kind, key, _x in list(api.worker.q.queue))
    with pytest.raises(ToolError, match="Give the video's link"):
        tool("make_clips").preview(ctx(), {"link": "my last stream"})

    db.save_settings({"autopilot_enabled": False})
    card, done = press("autopilot", {"action": "on"})
    assert db.get_settings()["autopilot_enabled"] is True and done.text == "Autopilot is on."
    with pytest.raises(ToolError, match="already on"):
        tool("autopilot").preview(ctx(), {"action": "on"})
    card, done = press("autopilot", {"action": "stop_all"})
    from clipfoundry.autopilot import state

    assert state.get("emergency_stop") is True and "Nothing new starts until resume" in done.text
    press("autopilot", {"action": "resume"})
    assert state.get("emergency_stop") is False


def test_posting_rules_are_settings_it_can_change(data):
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    card, done = press("change_setting", {"setting": "minutes between posts", "value": "90"})
    assert db.get_settings()["autopilot_min_gap_minutes"] == 90 and "posts already planned keep" in card["detail"][0]
    assert done.data["links"][0]["href"] == "#/settings/advanced"
    press("change_setting", {"setting": "latest posting hour", "value": "22"})
    assert db.get_settings()["autopilot_active_end"] == 22
    with pytest.raises(ToolError, match="changed by the owner on their own pages"):
        tool("change_setting").preview(ctx(), {"setting": "autopilot_auto_publish", "value": "true"})


# ------------------------------------------------------------------ in the chat: at once, or a button
def test_in_the_chat_a_change_happens_at_once_and_a_delete_still_waits(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.brain import chat

    a, b = two_posts(data)
    fake = install(monkeypatch,
                   say("Moving it.", ("cancel_post", {"post": "lake swim"})),
                   say("Done: Lake swim is off the schedule."),
                   say("Deleting it needs your OK.", ("delete_project", {"project": "lake swim"})))
    c = chat.open_chat(WS)
    m = settled(c["id"], chat.send(WS, c["id"], "don't post the lake swim")["ai"]["id"])
    act = m["data"]["pending"][0]
    assert act["state"] == "done" and act["alone"] is True and act["tool"] == "cancel_post"
    assert db.fetch("scheduled_publications", b["id"])["status"] == "canceled"
    assert "done (you did it yourself, no OK needed)" in fake.last_user(1)  # the model reads what it did
    assert m["text"].endswith("Done: Lake swim is off the schedule.")
    m = settled(c["id"], chat.send(WS, c["id"], "and delete that project")["ai"]["id"])
    assert all(p["state"] in ("waiting", "blocked") and not p.get("alone") for p in m["data"]["pending"])


def test_ask_me_first_turns_every_change_back_into_a_button(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.brain import chat

    a, b = two_posts(data)
    install(monkeypatch, say("Shall I?", ("cancel_post", {"post": "lake swim"})), ai_acts_alone=False)
    c = chat.open_chat(WS)
    m = settled(c["id"], chat.send(WS, c["id"], "don't post the lake swim")["ai"]["id"])
    assert m["data"]["pending"][0]["state"] == "waiting" and not m["data"]["pending"][0].get("alone")
    assert db.fetch("scheduled_publications", b["id"])["status"] != "canceled"
    out = chat.decide(WS, c["id"], m["id"], "a1", True)
    assert out["data"]["pending"][0]["state"] == "done"


def test_everyday_words_bring_the_commands_and_a_bigger_model_always_has_them():
    from clipfoundry.brain import operations, tools

    every = tools.available("general")
    for words in ("push the fishing clip to Saturday at 6", "kill the ranked stream project",
                  "trim 2 seconds off the start", "make it louder", "turn autopilot off",
                  "approve the bass video", "clip https://youtu.be/x", "write a scary story"):
        assert {t.name for t in operations.offered(every, words)} >= {"edit_clip", "approve_post"}, words
    assert not {t.name for t in operations.offered(every, "how long should my intro be?")} & operations.COMMANDS
    big = operations.offered(every, "hello", {"ai_provider": "anthropic"})
    assert {t.name for t in big} >= operations.COMMANDS


def test_the_main_ai_reviews_a_helpers_work_before_it_answers(data, monkeypatch):
    from clipfoundry.brain import agents, chat

    agents.add(WS, name="Critic", role="Reviews hooks")
    fake = install(monkeypatch,
                   say("Let me ask the Critic.", ("ask_agent", {"agent": "Critic", "task": "Rate my hook"})),
                   say("The hook is weak: it gives the ending away."),        # the Critic's work
                   say("The Critic is right about the ending; I would open on the fall instead."))
    c = chat.open_chat(WS)
    m = settled(c["id"], chat.send(WS, c["id"], "ask the critic about my hook")["ai"]["id"])
    assert len(fake.calls) == 3  # asked again after the helper's work, although it had already spoken
    assert m["text"].endswith("I would open on the fall instead.")
    assert "you are its reviewer" in fake.calls[0]["system"]


def test_a_long_chat_keeps_its_start(data):
    from clipfoundry import db
    from clipfoundry.brain import chat

    c = chat.open_chat(WS)
    first = chat._add(c, "user", "the very first thing I said")  # noqa: SLF001
    for n in range(260):  # more than the 200 an older version kept
        chat._add(c, "user", f"message {n}")  # noqa: SLF001
    assert db.fetch("brain_chat_messages", first["id"]) is not None
    assert len(chat.messages(WS, c["id"])) == 261 and chat.KEEP >= 5000


# ------------------------------------------------------------------ review fixes (Nov 26)
def test_an_approved_tiktok_post_is_never_posted_by_clipforge_ai(env):  # noqa: F811
    """The owner approved it on its page for later; "post it now" still leaves it to the post page."""
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    _g, _t, tmp = env
    item = _youtube_post(tmp, "", "Tiny trout", status="approved", platform="tiktok")
    card = tool("approve_post").preview(ctx(), {"post": "tiny trout", "now": True})
    assert "TikTok's rules for apps need your own OK on every post" in card["blocked"]
    with pytest.raises(ToolError, match="TikTok's rules"):
        tool("approve_post").run(ctx(), {"post": item["id"], "now": True})
    assert db.fetch("scheduled_publications", item["id"])["status"] == "approved"
    assert not db.fetch("worker_jobs", f"publish:{item['id']}", "idem_key")


def test_an_ok_checks_the_account_its_card_showed(env):  # noqa: F811
    """Ask me first: the card says Fishing channel; another channel is the one it would go to when OK is pressed."""
    from clipfoundry import db
    from clipfoundry.brain import tools
    from clipfoundry.brain.tools import ToolError

    google, _tik, tmp = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_min_gap_minutes": 0})
    fish = add_channel(google, "UCfish", "Fishing channel")
    other = add_channel(google, "UCother", "Other channel")
    item = _youtube_post(tmp, fish["id"])
    t = tool("approve_post")
    card = t.preview(ctx(), tools.check_args(t, {"post": "bass first cast"}))
    assert card["args"]["account"] == "UCfish" and "(Fishing channel)" in card["label"]
    db.update("scheduled_publications", item["id"], connection_id=other["id"])
    with pytest.raises(ToolError, match="Another account is connected now"):
        t.run(ctx(), tools.check_args(t, card["args"], button=True))
    assert db.fetch("scheduled_publications", item["id"])["status"] == "awaiting_approval"
    # the model cannot choose the account itself: it is the card's own
    assert "account" not in tools.check_args(t, {"post": item["id"], "account": "UCother"})


def test_ok_on_a_post_that_was_approved_meanwhile_says_so(env):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.brain import tools

    google, _tik, tmp = env
    db.save_settings({"autopilot_enabled": True, "autopilot_youtube": True, "autopilot_min_gap_minutes": 0})
    chan = add_channel(google, "UCfish", "Fishing channel")
    item = _youtube_post(tmp, chan["id"])
    t = tool("approve_post")
    card = t.preview(ctx(), tools.check_args(t, {"post": "bass first cast"}))
    t.run(ctx(), tools.check_args(t, card["args"], button=True))   # approved on its page, say
    done = t.run(ctx(), tools.check_args(t, card["args"], button=True))   # then the card's OK
    assert "is approved" in done.text and db.fetch("scheduled_publications", item["id"])["status"] == "approved"


def test_a_tiktok_posts_hashtags_go_into_the_caption_it_posts(env):  # noqa: F811
    from clipfoundry import db
    from clipfoundry.brain.tools import ToolError

    _g, _t, tmp = env
    item = _youtube_post(tmp, "", "Tiny trout", platform="tiktok")
    db.update("scheduled_publications", item["id"], description="Tiny trout on a fly rod #fishing #old")
    card, done = press("edit_post", {"post": "tiny trout", "hashtags": "#trout #FlyFishing"})
    row = db.fetch("scheduled_publications", item["id"])
    assert row["description"] == "Tiny trout on a fly rod #trout #FlyFishing"   # TikTok posts this
    assert row["tags"] == ["#trout", "#FlyFishing"]
    with pytest.raises(ToolError, match="TikTok post has no title"):
        tool("edit_post").preview(ctx(), {"post": "tiny trout", "title": "A new title"})


def test_starting_a_project_with_clips_again_waits_for_the_ok(data, monkeypatch):
    """Making the clips again from the start replaces the clips it has (a delete), so it is always a button."""
    from clipfoundry import db
    from clipfoundry.brain import chat

    source = data / "fish.mp4"
    source.write_bytes(b"video")
    p = db.create_project("Fishing stream", status="error", error="stopped", source_path=str(source))
    db.create_clip(p["id"], start=0, end=20, title="Bass", status="ready", score=70.0)
    card = tool("restart_work").preview(ctx(), {"project": "fishing stream"})
    assert card["ask"] is True and "The 1 clip it has now are replaced" in " ".join(card["detail"])
    install(monkeypatch, say("Starting it again.", ("restart_work", {"project": "fishing stream"})),
            say("It waits for your OK."))
    c = chat.open_chat(WS)
    m = settled(c["id"], chat.send(WS, c["id"], "start the fishing stream again")["ai"]["id"])
    act = m["data"]["pending"][0]
    assert act["tool"] == "restart_work" and act["state"] == "waiting" and not act.get("alone")
    assert len(db.list_clips(p["id"])) == 1 and db.get_project(p["id"])["status"] == "error"


def test_settings_say_it_acts_on_its_own_with_a_switch_to_ask_first():
    """Settings → ClipForge AI: the switch, and an intro that no longer says it only proposes changes."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "frontend/src/components/AiHelperSettings.tsx").read_text()
    assert '"Do it without asking"' in page and '"Ask me first (OK button)"' in page
    assert "api.saveSettings({ ai_acts_alone: v === \"alone\" })" in page
    assert "proposes the changes you" not in page and "makes the changes you" in page
