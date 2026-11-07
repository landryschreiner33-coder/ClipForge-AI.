"""ClipForge AI's built-in craft know-how (docs/clipforge/CLIPFORGE_AI.md, "Know-how"): playbooks distilled from the
research the owner gave it, picked by words and by job inside a budget, read by the chat, change requests, smart-edit
advice and the FilmCraft pass, answering editing questions without a model; and the editors that apply its numbers
(outro lines, loss-framing hooks, caption safe zones, the voice chain, BT.709 colour, delivery settings)."""
from __future__ import annotations

import json

import pytest

from test_studio_edit_requests import _plan, _project, env  # noqa: F401

WS = "local"


def test_the_playbooks_are_short_plain_and_picked_by_words_and_by_job():
    from clipfoundry.brain import knowhow

    ids = [t.id for t in knowhow.TOPICS]
    assert len(ids) == len(set(ids)) == 12
    for t in knowhow.TOPICS:
        assert 3 <= len(t.lines) <= 5 and all(len(line) <= 260 for line in t.lines) and len(t.text) <= 800
        assert t.tasks and set(t.tasks) <= set(knowhow.TASKS)
    for task, defaults in knowhow.DEFAULTS.items():
        assert task in knowhow.TASKS and all(d in knowhow.BY_ID for d in defaults)
    # a question finds its playbook by words, rarer words counting more; nonsense finds nothing
    assert knowhow.answer("how loud should my video be?")["id"] == "sound"
    assert knowhow.answer("where do I put captions so TikTok doesn't cover them")["id"] == "captions"
    assert knowhow.answer("what music fits a sad scene")["id"] == "music"
    assert knowhow.answer("how do I make the first seconds grab people")["id"] == "hooks"
    assert knowhow.answer("make the colours warmer")["id"] == "colour"
    assert knowhow.answer("which export settings for YouTube Shorts")["id"] == "platforms"
    assert knowhow.answer("why did people leave halfway through")["id"] == "retention"
    assert knowhow.answer("what about penguins flying") is None and knowhow.answer("") is None
    # a job gets its defaults when the words pick nothing, inside the budget, the best match first
    finish = knowhow.select("", "finish", limit=3, budget_chars=1500)
    assert finish.ids == ["colour", "effects"] and len(finish.prompt()) <= 1500
    assert finish.prompt().startswith(knowhow.HEADER) and "Colour by mood:" in finish.prompt()
    assert knowhow.select("", "finish", limit=3, budget_chars=10 ** 6).ids == ["colour", "effects", "sound"]
    assert knowhow.select("make the captions bigger", "change", limit=2, budget_chars=900).ids == ["captions"]
    assert knowhow.select("", "change", limit=2, budget_chars=900).ids == ["pacing"]
    assert knowhow.select("", "chat").empty and knowhow.select("", "chat").prompt() == ""
    assert knowhow.select("penguins", "finish", fill=False).empty
    assert knowhow.select("the voice is too quiet", "finish", limit=1, budget_chars=2000).ids == ["sound"]
    assert knowhow.select("x", "nonsense-task", limit=1).empty
    picked = knowhow.select("how loud", "chat", limit=1)
    assert picked.snapshot() == [{"id": "sound", "title": "Voice and sound mix", "score": picked.topics[0]["score"]}]
    assert "remember: …" in knowhow.answer_text(knowhow.answer("how loud should my video be?"))
    assert all(knowhow.principles(t) for t in ("clips", "change", "smart_edit", "finish", "post"))
    assert knowhow.principles("chat") == ""
    assert [t["id"] for t in knowhow.topics()] == ids


def test_the_chat_answers_editing_questions_from_the_know_how_without_a_model(env):
    from clipfoundry import db
    from clipfoundry.brain import chat

    db.save_settings({"ai_provider": "heuristic"})
    c = chat.open_chat(WS)
    m = chat.send(WS, c["id"], "How loud should my video be?")["ai"]
    assert m["status"] == "done" and m["data"]["tool"] == "answer" and m["data"]["used"] == []
    assert m["data"]["knowhow"][0]["id"] == "sound" and m["text"].startswith("From my built-in know-how, voice and sound mix:")
    assert "-14 LUFS" in m["text"] and "Settings → ClipForge AI" in m["text"]
    m = chat.send(WS, c["id"], "what about penguins flying?")["ai"]
    assert m["data"]["tool"] == "answer" and m["data"]["knowhow"] == [] and "built-in know-how" in m["text"]
    assert "know-how" in chat.HELP


def test_the_model_reads_the_memories_first_and_the_know_how_second(env, monkeypatch):
    from clipfoundry import brain, db
    from clipfoundry.brain import chat, knowhow, memories
    from clipfoundry.pipeline import llm
    from test_clipforge_ai_chat import _settled

    calls = []
    monkeypatch.setattr(llm, "complete", lambda settings, prompt, **kw: calls.append(prompt) or json.dumps({"say": "ok"}))
    db.save_settings({"ai_provider": "ollama", "ollama_url": "http://localhost:11434"})
    brain.remember(WS, "Keep my music quiet", kind="rule")
    c = chat.open_chat(WS)
    first = chat.send(WS, c["id"], "how loud should the music be under my voice?")["ai"]
    assert first["status"] == "thinking" and first["data"]["knowhow"][0]["id"] == "sound"
    assert "built-in know-how" in first["data"]["sent"]
    assert _settled(c["id"], first["id"])["text"] == "ok"
    prompt = calls[0]
    assert prompt.index(memories.HEADER) < prompt.index(knowhow.HEADER) < prompt.index("The owner asks")
    assert "Voice and sound mix:" in prompt and "- [rule] Keep my music quiet" in prompt


def test_change_requests_carry_the_know_how_that_fits_inside_the_budget(env, monkeypatch):
    from clipfoundry.brain import knowhow
    from clipfoundry.studio import edit_requests as er
    from test_studio_edit_requests import _ai, _wait

    fake = _ai(monkeypatch, json.dumps({"summary": "Bigger captions", "operations": []}))
    pid = _project(env)["id"]
    r = er.ask(pid, WS, "Make the captions easier to read on a phone")
    assert [k["id"] for k in r["knowhow"]] == ["captions"] and "built-in know-how" in r["sent"]
    r = _wait(r["id"])
    prompt = fake.prompts[0][0]
    assert knowhow.HEADER in prompt and "Captions and safe zones:" in prompt and len(prompt) <= er.CONTEXT_CHARS
    assert knowhow.principles("change") in prompt
    assert prompt.index(knowhow.HEADER) < prompt.index("Clips in order")
    assert [k["id"] for k in er.view(r["id"], WS)["knowhow"]] == ["captions"]
    # a request the rules understand reads no know-how; the block is cut to its budget
    assert er.ask(pid, WS, "remove clip 3")["knowhow"] == []
    plan = _plan(pid)
    rows = er.clip_rows(plan, {})
    long = knowhow.HEADER + "\n" + "x" * 5000
    text = er.build_prompt("hello", plan, rows, {}, "", long)
    assert len(text) <= er.CONTEXT_CHARS and "x" * (er.KNOWHOW_CHARS + 1) not in text


def test_smart_edit_advice_and_the_filmcraft_pass_read_the_know_how():
    from clipfoundry.brain import knowhow
    from clipfoundry.studio import ai_editor, video_flow

    window = [{"i": 0, "file": 1, "start": 0.0, "dur": 2.0, "text": "Hello there."}]
    plain = ai_editor.build_prompt(window, {}, 1, 1)
    with_know = ai_editor.build_prompt(window, {}, 1, 1, "", knowhow.select("", "smart_edit", limit=2).prompt())
    assert knowhow.HEADER not in plain and with_know.startswith(knowhow.HEADER) and "Talking-head edits:" in with_know
    assert with_know.endswith(plain)
    both = ai_editor.build_prompt(window, {}, 1, 1, "MEMORIES", "KNOW")
    assert both.startswith("MEMORIES\nKNOW\n\n")
    assert "Talking-head edits:" in video_flow._smart_knowhow({"video_type": "vlog", "goal": "keep people watching"})
    assert "outro lines" in ai_editor.SYSTEM
    from clipfoundry.craft import ai as craft_ai

    assert "Correct before you grade" in craft_ai.SYSTEM
    assert craft_ai._knowhow({"title": {"text": "A sunny hike"}}).ids == ["colour", "effects"]
    assert craft_ai._knowhow({"title": {"text": "Make the voice clearer and the music quieter"}}).ids[0] == "sound"


def test_clip_scoring_and_post_packages_tell_the_model_the_principles():
    from clipfoundry.brain import knowhow
    from clipfoundry.pipeline import llm

    prompt = llm.build_prompt("v", ["Stop doing this.", "It costs you."], "", 12.0)
    assert knowhow.principles("clips") in prompt and prompt.index("Judge like") < prompt.index("Source video")
    assert "never #fyp" in knowhow.principles("post")


def test_an_outro_is_a_weak_ending_and_the_point_before_it_scores_higher():
    from clipfoundry import config
    from clipfoundry.pipeline import candidates, transcribe, virality
    from clipfoundry.pipeline.text_utils import build_sentences
    from test_core import _srt, flat_loudness

    lines = ["Why do most people give up on running after three weeks?",
             "Because they start way too fast.",
             "Your body needs about six weeks to adapt to the impact.",
             "If you run slowly enough to hold a conversation, you recover faster and you keep going.",
             "That's why the slowest runners in my club are the ones who are still running a year later.",
             "So to recap, start slow and keep going.",
             "Thanks for watching, and don't forget to subscribe."]
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(lines))})
    sentences = build_sentences(words)
    feats = candidates.sentence_features(sentences, words)
    assert [f["outro"] for f in feats] == [False] * 5 + [True, True]
    loud = flat_loudness(words[-1]["end"])
    opts = dict(config.DEFAULT_SETTINGS)
    point = virality.analyze(0, 4, sentences, feats, words, loud, opts)
    recap = virality.analyze(0, 5, sentences, feats, words, loud, opts)
    outro = virality.analyze(0, 6, sentences, feats, words, loud, opts)
    assert not any(f["id"] == "outro" for f in point["flags"]) and point["signals"]["outro"] is False
    for r in (recap, outro):
        assert any(f["id"] == "outro" and f["severity"] == "warn" for f in r["flags"]) and r["signals"]["outro"]
        assert not r["structure"]["payoff"]
    assert point["viral_potential"] > recap["viral_potential"] > outro["viral_potential"]
    assert point["factors"]["payoff"] > outro["factors"]["payoff"]
    # an outro line makes a poor opener, a loss or a warning a good one
    assert feats[6]["opener"] < 0.2 < feats[0]["opener"]
    loss = candidates.sentence_features(build_sentences(transcribe.flatten_words(
        {"segments": transcribe.parse_subtitles(_srt(["Stop making this mistake with your money."]))})), words)
    plain = candidates.sentence_features(build_sentences(transcribe.flatten_words(
        {"segments": transcribe.parse_subtitles(_srt(["Here is a way to handle your money."]))})), words)
    assert loss[0]["loss"] >= 2 and plain[0]["loss"] == 0 and loss[0]["opener"] > plain[0]["opener"]


def test_hooks_prefer_loss_framing_plain_words_and_a_headline_that_fits():
    from clipfoundry.pipeline import hooks

    assert hooks._hookiness("Stop making this mistake with your money", 0.0) > \
        hooks._hookiness("Here is a way to handle your money", 0.0)
    assert hooks._hookiness("Why most diets fail after two weeks", 0.0) > \
        hooks._hookiness("Why most diets fail after fourteen days of unsustainable overcommitment", 0.0)
    hook, alts = hooks.heuristic_hooks(["So today I wanted to share something that I have been thinking about for a "
                                        "long while now, which is about running.",
                                        "Stop doing this when you start running.",
                                        "It is the mistake that ruins most beginners."])
    assert hook == "Stop doing this when you start running."
    assert len(alts) == 3 and all(len(a.split()) >= 3 for a in alts)


def test_captions_keep_clear_of_the_apps_and_the_headline_fits_above_the_face():
    from clipfoundry.config import OUTPUT_H
    from clipfoundry.pipeline import captions

    assert captions.POSITIONS["bottom"] == (2, 0.36)  # above the bottom 35% the phone apps cover
    assert captions.POSITIONS["top"][1] >= captions.HOOK_TOP >= 0.15  # below the top bar
    words = [{"start": 0.0, "end": 0.4, "w": "Stop"}, {"start": 0.4, "end": 0.9, "w": "doing"},
             {"start": 0.9, "end": 1.3, "w": "this."}]
    short = captions.build_ass(words, {"caption_style": "bold", "hook_overlay": True}, 3.0, "Stop doing this")
    long = captions.build_ass(words, {"caption_style": "bold", "hook_overlay": True}, 3.0,
                              "Stop doing this one thing that ruins every single run you ever go on, honestly")
    assert f"Style: Hook,Poppins ExtraBold,68," in short and f",{int(OUTPUT_H * 0.15)},1" in short
    assert "Style: Hook,Poppins ExtraBold,50," in long
    assert captions.hook_size("Three words only") == 68 and captions.hook_size("x" * 50) == 58
    assert f",{int(OUTPUT_H * 0.36)},1" in captions.build_ass(words, {"caption_style": "bold"}, 3.0)


def test_the_voice_chain_follows_the_dialogue_numbers():
    from clipfoundry.pipeline import cleanup

    for p in cleanup.PROFILES.values():
        assert 80 <= p["highpass"] <= 100 and 2.0 <= p["presence_db"] <= 3.0 and 2.5 <= p["ratio"] <= 3.5
        assert -4.0 <= p["mud_db"] <= -2.0
    assert 2500 <= cleanup.PRESENCE_HZ <= 5000 and 200 <= cleanup.MUD_HZ <= 400
    assert 15 <= cleanup.COMP_ATTACK_MS <= 30 and 50 <= cleanup.COMP_RELEASE_MS <= 100
    chain = cleanup._polish_chain(cleanup.PROFILES["strong"], 48000)
    assert "ratio=3.5:attack=20:release=90" in chain and "equalizer=f=3500" in chain and "equalizer=f=300" in chain


def test_delivery_settings_and_bt709_colour():
    from clipfoundry.pipeline import ffmpeg_utils, render
    from clipfoundry.studio import engine
    import inspect

    args = ffmpeg_utils.delivery_args(30)
    assert args[:4] == ["-g", "15", "-flags", "+cgop"] and args[-1] == "bt709" and "-colorspace" in args
    assert ffmpeg_utils.delivery_args(59.94)[1] == "30" and ffmpeg_utils.delivery_args(24)[1] == "12"
    assert ffmpeg_utils.AUDIO_BITRATE == "256k"
    src = inspect.getsource(render.render_clip)
    assert "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p" in src and "delivery_args(fps)" in src
    assert "-g" in engine._encode_args(False, {}, 30) and engine._encode_args(False, {}, 60)[-3] == "30"


def test_the_know_how_api_lists_the_playbooks_and_what_a_question_would_read(env):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.get("/api/brain/memories/knowhow")
        assert r.status_code == 200 and len(r.json()["topics"]) == 12 and "November 2026" in r.json()["source"]
        assert r.json()["topics"][0]["id"] == "hooks" and r.json()["topics"][0]["lines"]
        r = api.post("/api/brain/memories/knowhow/select", json={"query": "how loud should my video be", "task": "chat"})
        assert r.status_code == 200 and r.json()["answer"]["id"] == "sound" and r.json()["topics"][0]["id"] == "sound"
        assert r.json()["prompt"].startswith("ClipForge AI's craft know-how")
