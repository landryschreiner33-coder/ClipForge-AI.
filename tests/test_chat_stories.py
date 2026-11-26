"""Text-message stories (makers/chatstory.py and the "chat" kind of makers/textstory.py): a phone chat that appears a
bubble at a time over background video, each message read aloud in its sender's voice, the way they look on TikTok.
The script ("Name: message" lines) and its limits, whose phone it is, voices for everyone, the card's pages, the
timing, ClipForge AI writing and revising chats up to ten minutes (a part at a time), and the preview and export."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave

import numpy as np
import pytest

from clipfoundry.makers import chatstory as cs

needs_media = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("espeak-ng") is None,
                                 reason="needs FFmpeg and espeak-ng")

CHAT = ("Sienna: Be honest. Did you eat my leftovers?\n"
        "Me: Which leftovers\n"
        "Sienna: The pasta. With my NAME on it 😤\n"
        "Me: There was a name on it?")


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from fastapi.testclient import TestClient

    from clipfoundry import api, db
    from clipfoundry.jobs import worker
    from clipfoundry.makers import voice

    db.init()
    queued: list[str] = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: queued.append(job_id))
    voice.clear_cache()
    with TestClient(api.app, base_url="http://127.0.0.1:8765") as c:
        yield {"client": c, "queued": queued, "tmp": tmp_path}


def _run(env) -> list[dict]:
    from clipfoundry import db
    from clipfoundry.studio import jobs as studio_jobs

    done = []
    while env["queued"]:
        job_id = env["queued"].pop(0)
        if db.fetch("studio_jobs", job_id)["kind"].startswith("text_story"):
            studio_jobs.run(job_id)
            done.append(db.fetch("studio_jobs", job_id))
    return done


VOICES = [{"id": "x:ava", "name": "Ava", "lang": "en-US", "gender": "female", "about": "", "engine": "x"},
          {"id": "x:ben", "name": "Ben", "lang": "en-US", "gender": "male", "about": "", "engine": "x"},
          {"id": "x:cara", "name": "Cara", "lang": "en-GB", "gender": "female", "about": "", "engine": "x"},
          {"id": "x:ola", "name": "Ola", "lang": "nb-NO", "gender": "female", "about": "", "engine": "x"}]


# ------------------------------------------------------------------ the script
def test_one_message_a_line_with_the_senders_name_in_front():
    msgs = cs.parse("Sienna: hey\nthis line goes on Sienna's messages\n\nsienna: same person, written small\n"
                    "Me: 10:30 works?\n10:30 works for me too\n\\Note: not a name, the backslash says so\n"
                    "Me: see https://example.com: it is there\nBen 😤: hi\n")
    assert [(m["who"], m["text"]) for m in msgs] == [
        ("Sienna", "hey"), ("Sienna", "this line goes on Sienna's messages"),
        ("Sienna", "same person, written small"),       # a name is kept as it was first written
        ("Me", "10:30 works?"), ("Me", "10:30 works for me too"),   # a time is a message, not a name
        ("Me", "Note: not a name, the backslash says so"),
        ("Me", "see https://example.com: it is there"),
        ("Ben 😤", "hi"),                                   # a name may carry an emoji
    ]
    assert cs.parse("hello there")[0]["who"] == "Them"     # no name yet: the contact
    assert cs.people_in(msgs) == ["Sienna", "Me", "Ben 😤"] and cs.words_in(msgs[:2]) == 7


def test_the_script_is_tidied_and_too_much_for_one_video_is_refused():
    assert cs.clean_script("  Sienna:   hi   there \n\n\n\nMe:  yo  ") == "Sienna: hi there\n\nMe: yo"
    with pytest.raises(cs.ChatError, match="at most 400"):
        cs.clean_script("\n".join(f"A: {i}" for i in range(cs.MAX_MESSAGES + 1)))
    with pytest.raises(cs.ChatError, match="Split it"):
        cs.clean_script("A: " + "x" * (cs.MAX_MESSAGE_CHARS + 1))
    with pytest.raises(cs.ChatError, match="at most 8 people"):
        cs.clean_script("\n".join(f"P{chr(65 + i)}: hi" for i in range(cs.MAX_PEOPLE + 1)))
    with pytest.raises(cs.ChatError, match="ten minutes"):
        cs.clean_script("\n".join("A: " + " ".join(["word"] * 40) for _ in range(cs.MAX_WORDS // 40 + 1)))
    with pytest.raises(cs.ChatError):
        cs.clean_script(None)


def test_whose_phone_it_is_and_the_name_at_the_top():
    two = cs.resolve(CHAT, {})
    assert two["me"] == "Me" and two["contact"] == "Sienna" and not two["group"]
    assert [m["side"] for m in two["messages"]] == ["them", "me", "them", "me"]
    assert all(m["label"] == "" for m in two["messages"])   # two people: no names over the bubbles
    # nobody called Me: the second person to write holds the phone, unless another is chosen
    assert cs.resolve("Ana: a\nBo: b", {})["me"] == "Bo"
    assert cs.resolve("Ana: a\nBo: b", {"me": "Ana"})["me"] == "Ana"
    assert cs.resolve("Ana: a\nBo: b", {"me": "Nobody"})["me"] == "Bo"
    assert cs.resolve("Ana: a\nBo: b", {"contact": "Mom ❤️"})["contact"] == "Mom ❤️"
    group = cs.resolve("Ana: a\nAna: b\nBo: c\nMe: d\nAna: e", {})
    assert group["group"] and group["contact"] == "Ana, Bo"
    assert [m["label"] for m in group["messages"]] == ["Ana", "", "Bo", "", "Ana"]   # first of each run of theirs


def test_the_chat_choices_are_checked():
    c = cs.clean_chat({"theme": "light", "pace": "slow", "badge": 5000, "sounds": 0, "contact": "  Big   Sis  "})
    assert (c["theme"], c["pace"], c["badge"], c["sounds"], c["contact"]) == ("light", "slow", 999, False, "Big Sis")
    for bad in ({"theme": "neon"}, {"pace": "warp"}, {"badge": "lots"}, {"people": ["Sienna"]},
                {"people": {"Sienna": {"speed": "fast"}}}):
        with pytest.raises(cs.ChatError):
            cs.clean_chat(bad)
    with pytest.raises(cs.ChatError):
        cs.clean_chat("dark")
    have = cs.clean_chat({"people": {"Sienna": {"voice": "x:ava", "tone": 2}}})
    assert have["people"]["Sienna"]["tone"] == 2.0
    assert "Sienna" not in cs.clean_chat({"people": {"Sienna": None}}, have)["people"]


def test_everyone_gets_a_voice_and_the_two_sides_sound_different():
    from clipfoundry.makers import voice

    chat = cs.with_voices(CHAT, dict(cs.DEFAULT_CHAT), VOICES)
    people = chat["people"]
    assert set(people) == {"Sienna", "Me"} and people["Sienna"]["voice"] != people["Me"]["voice"]
    genders = {v["id"]: v["gender"] for v in VOICES}
    assert genders[people["Sienna"]["voice"]] != genders[people["Me"]["voice"]]   # a woman's next to a man's
    assert all(people[n]["voice"] != "x:ola" for n in people)   # English voices first
    # a chosen voice stays; someone who left the chat loses theirs; a newcomer gets a voice nobody has
    kept = cs.with_voices(CHAT + "\nBen: what pasta", {**chat, "people": {**people, "Old": {"voice": "x:ava"}}},
                          VOICES)
    assert kept["people"]["Sienna"] == people["Sienna"] and "Old" not in kept["people"]
    assert kept["people"]["Ben"]["voice"] not in {people["Sienna"]["voice"], people["Me"]["voice"]}
    # more people than voices: a voice comes back higher or lower
    crowd = "\n".join(f"P{chr(65 + i)}: hi" for i in range(6))
    many = cs.with_voices(crowd, {}, VOICES[:2])["people"]
    pairs = [(v["voice"], v["tone"]) for v in many.values()]
    assert len(set(pairs)) == len(pairs) == 6
    assert cs.with_voices(CHAT, {}, [])["people"]["Me"]["voice"] == "auto"   # no voices: the computer's own
    assert voice  # imported for the default voice the module asks for


def test_the_timing_follows_the_voices_and_the_pace():
    msgs = cs.resolve(CHAT, {})["messages"]
    times, total = cs.timeline(msgs, [1.0, 0.5, 1.2, 0.8], "normal")
    assert times[0]["show"] == 0.0 and times[0]["at"] == cs.LEAD_S   # the first bubble is there from the start
    assert all(a["end"] < b["show"] for a, b in zip(times, times[1:]))
    assert times[1]["show"] == pytest.approx(times[0]["end"] + cs.PAUSE_TURN_S)
    assert total == pytest.approx(times[-1]["end"] + cs.END_S)
    slow = cs.timeline(msgs, [1.0, 0.5, 1.2, 0.8], "slow")[1]
    quick = cs.timeline(msgs, [1.0, 0.5, 1.2, 0.8], "quick")[1]
    assert quick < total < slow
    # the estimate before recording is in the same range, and reading without voices takes as long as reading
    est = cs.estimate(CHAT, {})
    assert 5 < est < 20
    assert cs.estimate(CHAT, {"read_aloud": False}) == pytest.approx(
        sum(cs.LEAD_S + cs.reading_seconds(m["text"]) for m in msgs) + 3 * cs.PAUSE_TURN_S + cs.END_S, abs=0.2)
    assert cs.estimate("", {}) == 0.0


def test_the_card_starts_a_new_page_when_it_fills_and_every_bubble_fits():
    script = "\n".join(f"{'Sienna' if i % 3 else 'Me'}: message number {i} " + "and more words " * (i % 4)
                       for i in range(60))
    resolved = cs.resolve(script, {})
    card = cs.Card(1.0, "dark", resolved["contact"], 99)
    places = card.layout(resolved["messages"])
    pages = sorted({p["page"] for p in places})
    assert pages == list(range(len(pages))) and len(pages) >= 3
    for p in places:
        assert p["top"] + p["h"] <= card.max_h + 1
        assert 0 <= p["x"] and p["x"] + p["w"] <= card.w + 1
    first_on_page = [p for i, p in enumerate(places) if i and p["page"] != places[i - 1]["page"]]
    assert all(p["top"] < cs.HEAD_H for p in first_on_page)   # later pages have no header
    for p, m in zip(places, resolved["messages"]):   # theirs on the left, whose phone it is on the right
        assert (p["x"] + p["w"] == pytest.approx(card.w - cs.SIDE)) if m["side"] == "me" else p["x"] == cs.SIDE
    pic = card.state(resolved["messages"], places, 5)
    assert pic.size == (card.w, card.max_h) and pic.mode == "RGBA"
    assert pic.getpixel((0, 0))[3] == 0 and pic.getpixel((card.w // 2, 10))[3] == 255   # rounded corners


def test_emoji_and_other_letters_are_kept_apart_and_left_out_of_what_is_said():
    assert cs.plain("The pasta 😤 is mine 🍝") == "The pasta is mine"
    kinds = [k for k, _ in cs.runs("ok 👍🏽 fine")]
    assert "emoji" in kinds and kinds[0] == "text"
    lines = cs.said_lines(cs.resolve("Sienna: GIF it 😤", {}), {}, [{"word": "GIF", "say": "jif"}])
    assert lines[0]["said"] == "jif it"


# ------------------------------------------------------------------ the page's story
def test_a_text_message_story_is_made_and_changed_on_the_page(env):
    c = env["client"]
    opts = c.get("/api/studio/text-stories/options").json()
    assert {k["id"] for k in opts["kinds"]} == {"chat", "narrated"}
    assert [t["id"] for t in opts["chat"]["themes"]] == ["dark", "light", "green"]
    assert opts["chat"]["themes"][0]["me"] == "#0a84ff" and opts["chat"]["limits"]["max_seconds"] == 600
    assert [x["id"] for x in opts["chat"]["lengths"]] == ["short", "standard", "long", "longest"]
    assert any(x["id"] == "ten" for x in opts["lengths"])   # narrated stories reach ten minutes too
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "title": "ignored"}).json()
    assert story["kind"] == "chat" and story["title"] == "" and story["name"] == "New text-message story"
    url = f"/api/studio/text-stories/{story['id']}"
    got = c.patch(url, json={"script": CHAT}).json()
    chat = got["chat"]
    assert chat["names"] == ["Sienna", "Me"] and chat["whose_phone"] == "Me" and chat["shown_contact"] == "Sienna"
    assert set(chat["people"]) == {"Sienna", "Me"} and got["steps"]["voice"]
    assert got["words"] == cs.words_in(cs.parse(CHAT)) == 23
    assert got["name"].startswith("Sienna: Be honest") and len(chat["messages"]) == 4
    assert got["seconds"] > 5
    got = c.patch(url, json={"chat": {"theme": "green", "contact": "Sis 💅", "me": "Sienna", "badge": 3,
                                      "people": {"Me": {"speed": 1.2}}}}).json()
    assert got["chat"]["theme"] == "green" and got["chat"]["shown_contact"] == "Sis 💅"
    assert got["chat"]["whose_phone"] == "Sienna" and got["chat"]["messages"][0]["side"] == "me"
    assert got["chat"]["people"]["Me"]["speed"] == 1.2
    assert c.patch(url, json={"chat": {"theme": "neon"}}).status_code == 422
    assert c.patch(url, json={"script": "A: " + "x" * 400}).status_code == 422
    listed = c.get("/api/studio/text-stories").json()["stories"]
    assert listed[0]["kind"] == "chat" and listed[0]["messages"] == 4
    # a narrated story turned into a chat keeps its words, as one message from the contact per line
    other = c.post("/api/studio/text-stories", json={"script": "Line one.\n\nLine two."}).json()
    turned = c.patch(f"/api/studio/text-stories/{other['id']}", json={"kind": "chat"}).json()
    assert turned["kind"] == "chat" and [m["text"] for m in turned["chat"]["messages"]] == ["Line one.", "Line two."]
    assert c.post("/api/studio/text-stories", json={"kind": "poem"}).status_code == 422


def test_a_chat_too_long_for_ten_minutes_fails_and_says_why(env):
    c = env["client"]
    # without voices each message stays up as long as it takes to read: 120 long messages run over ten minutes
    script = "\n".join(f"{'Sienna' if i % 2 else 'Me'}: " + " ".join(["word"] * 14) for i in range(120))
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "script": script}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.patch(url, json={"chat": {"read_aloud": False}})
    c.post(f"{url}/backgrounds/auto")
    c.post(f"{url}/preview")
    assert [j["status"] for j in _run(env)] == ["failed"]
    got = c.get(url).json()
    assert got["status"] == "failed" and "longer than ten minutes" in got["error"] and not got["working"]


# ------------------------------------------------------------------ ClipForge AI writes chats
def _fake_writer(monkeypatch, outro: bool = True):
    from clipfoundry.makers import writer

    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    asks: list[str] = []

    def fake(system, schema, settings, prompt, cancel, beat, message):
        asks.append(prompt)
        if "Plan a long" in prompt:
            parts = schema["properties"]["beats"]["minItems"]
            return json.dumps({"title": "The pasta war", "contact": "Sienna 💅", "premise": "Sisters fight over food.",
                               "beats": [f"beat {k}" for k in range(parts)]})
        if "Revise" in prompt:
            now = prompt.split("now:\n<<<", 1)[1].split(">>>", 1)[0].split("\n")
            rows = [{"from": line.split(":", 1)[0], "text": line.split(":", 1)[1].strip().upper()} for line in now]
            return json.dumps({"messages": rows})
        hi = schema["properties"]["messages"]["maxItems"]
        lo = schema["properties"]["messages"]["minItems"]
        n = (lo + hi) // 2
        part = prompt.split("You are writing part ", 1)[1].split(" ", 1)[0] if "You are writing part" in prompt \
            else "1"
        rows = [{"from": "them" if j % 2 == 0 else "me", "text": f"part {part} message {j}"} for j in range(n)]
        last = "End the chat here" in prompt or "You are writing part" not in prompt
        if outro and last:
            rows.append({"from": "them", "text": "follow for part 2!"})
        return json.dumps({"title": "Leftovers", "contact": "Sienna 💅", "messages": rows})

    monkeypatch.setattr(writer, "_ask_with", fake)
    return asks


def test_clipforge_ai_writes_a_short_chat_in_one_go(env, monkeypatch):
    asks = _fake_writer(monkeypatch)
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat"}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.post(f"{url}/write", json={"topic": "my sister's leftovers", "tone": "comeback", "length": "short"})
    assert [j["status"] for j in _run(env)] == ["done"]
    got = c.get(url).json()
    lines = got["script"].split("\n")
    assert len(asks) == 1 and "<<<my sister's leftovers>>>" in asks[0] and "comeback" in asks[0].lower()
    assert lines[0].startswith("Sienna: part 1 message 0") and lines[1].startswith("Me: ")
    assert "follow for part" not in got["script"] and "closing message" in " ".join(got["writer"]["notes"])
    assert got["chat"]["shown_contact"] == "Sienna 💅" and got["chat"]["whose_phone"] == "Me"
    assert got["name"] == "Leftovers" and set(got["chat"]["people"]) == {"Sienna", "Me"}


def test_clipforge_ai_writes_a_ten_minute_chat_a_part_at_a_time_and_revises_it_in_parts(env, monkeypatch):
    from clipfoundry.makers import writer

    asks = _fake_writer(monkeypatch)
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat"}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.post(f"{url}/write", json={"topic": "a group project gone wrong", "length": "longest"})
    assert [j["status"] for j in _run(env)] == ["done"]
    got = c.get(url).json()
    parts = -(-writer.CHAT_LENGTHS["longest"] // writer.CHAT_PART)
    assert len(asks) == 1 + parts and "Plan a long text-message story" in asks[0]
    assert all(f"You are writing part {k + 1} of {parts}" in asks[k + 1] for k in range(parts))
    assert "The chat so far ends with" in asks[2] and "part 1 message" in asks[2]   # each part sees the one before
    msgs = got["chat"]["messages"]
    assert writer.CHAT_LENGTHS["longest"] * 0.8 <= len(msgs) <= cs.MAX_MESSAGES
    assert "follow for part" not in got["script"]
    assert 300 < got["seconds"] <= 700   # several minutes, up to about ten
    # a revision goes through the chat 40 messages at a time; every message comes back
    before = len(asks)
    c.post(f"{url}/write", json={"change": "shout everything"})
    assert [j["status"] for j in _run(env)] == ["done"]
    revised = c.get(url).json()
    assert len(asks) - before == -(-len(msgs) // writer.CHAT_REVISE_PART)
    assert len(revised["chat"]["messages"]) == len(msgs)
    assert revised["chat"]["messages"][0]["text"] == msgs[0]["text"].upper()
    assert revised["chat"]["whose_phone"] == "Me" and revised["chat"]["shown_contact"] == "Sienna 💅"


def test_clipforge_ai_plans_a_ten_minute_narrated_story_and_writes_it_in_parts(env, monkeypatch):
    from clipfoundry.makers import textstory, writer

    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    asks: list[str] = []

    def fake(system, schema, settings, prompt, cancel, beat, message):
        asks.append(prompt)
        if "Plan a long" in prompt:
            return json.dumps({"title": "The long night", "premise": "A storm, a stranger, a secret.",
                               "beats": [f"beat {k}" for k in range(schema["properties"]["beats"]["minItems"])]})
        return json.dumps({"text": " ".join(["word"] * writer.PART_WORDS)})

    monkeypatch.setattr(writer, "_ask_with", fake)
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    c.post(f"{url}/write", json={"topic": "a storm", "length": "ten"})
    assert [j["status"] for j in _run(env)] == ["done"]
    got = c.get(url).json()
    lo, hi = writer.STORY_LENGTHS["ten"]
    parts = -(-((lo + hi) // 2) // writer.PART_WORDS)
    # the parts came back longer than asked: the last one was asked for again, shorter, then cut to what fits
    assert len(asks) == 2 + parts and "write this last part again in at most" in asks[-1]
    assert got["title"] == "The long night" and "last sentences were left out" in " ".join(got["writer"]["notes"])
    assert lo * 0.8 <= got["words"] <= textstory.MAX_WORDS and got["seconds"] > 480


def test_the_assistant_can_start_a_text_message_story():
    from clipfoundry.brain import operations

    assert operations._story_choices({"kind": "chat", "tone": "comeback", "length": "longest"}) == (
        "chat", "comeback", "longest")
    assert operations._story_choices({"kind": "chat", "length": "ten"}) == ("chat", "drama", "standard")
    assert operations._story_choices({"length": "ten"}) == ("narrated", "drama", "ten")
    shown = operations._story_preview(None, {"idea": "a fake text from my landlord", "kind": "chat"})
    assert "text-message story" in shown["detail"][0] and shown["args"]["kind"] == "chat"


# ------------------------------------------------------------------ the video
def _frame(path, at: float, out) -> np.ndarray:
    from PIL import Image

    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at}", "-i", str(path), "-frames:v", "1", str(out)],
                   check=True)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def _probe(path) -> dict:
    got = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(got.stdout)


def _espeak() -> str:
    from clipfoundry.makers import voice

    return next(v["id"] for v in voice.voices() if v["id"].startswith("espeak:"))


@needs_media
def test_the_chat_is_read_aloud_over_the_background_a_bubble_at_a_time(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "script": CHAT}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    espeak = _espeak()
    c.patch(url, json={"chat": {"people": {"Me": {"voice": espeak}, "Sienna": {"voice": espeak, "tone": 3}}}})
    c.post(f"{url}/backgrounds/auto")
    started = c.post(f"{url}/preview").json()
    assert started["working"]
    assert [j["status"] for j in _run(env)] == ["done"], [j["error"] for j in _run(env)]
    got = c.get(url).json()
    assert got["status"] == "ready" and got["made"]["preview"]["current"] and got["narration"]["ready"]
    assert got["narration"]["messages"] == 4
    row = db.fetch("text_stories", story["id"])
    narr = row["narration"]
    assert narr["timing"] == "chat" and len(narr["times"]) == 4
    folder = textstory.folder(story["id"])
    assert len(list((folder / "lines").glob("*.wav"))) == 4   # one recorded line a message, kept for next time
    assert not (folder / "preview-cards").exists()   # the chat's pictures go once the video is made
    video = textstory.file_for(row, "preview")
    info = _probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (360, 640)
    assert abs(float(info["format"]["duration"]) - textstory.total_seconds(row, narr)) < 0.15
    # the card sits where it should: its dark header over the colourful background, and only the first bubble at
    # the start, all four at the end
    x, y = cs.card_box((360, 640))
    start = _frame(video, 0.05, env["tmp"] / "a.png")
    end = _frame(video, narr["times"][-1]["end"] - 0.1, env["tmp"] / "b.png")
    head = start[y + 20, x + 60]   # the header between the unread number and the picture
    assert np.abs(head - np.array(cs.THEMES["dark"]["head"])).max() < 14
    assert np.abs(start[y - 30, x + 60] - head).max() > 20   # above the card: the background
    me_blue = np.array(cs.THEMES["dark"]["me"])
    below = y + round(cs.HEAD_H * 360 / 1080) + 4   # the messages, under the header (its icons are blue too)
    width = round(cs.CARD_W * 360 / 1080)
    blue_start = (np.abs(start[below:, x:x + width] - me_blue).max(axis=2) < 30).sum()
    blue_end = (np.abs(end[below:, x:x + width] - me_blue).max(axis=2) < 30).sum()
    assert blue_start < 50 < blue_end   # "Me" has not written yet at the start
    # the voices are heard while the bubbles are up
    wav = folder / narr["file"]
    with wave.open(str(wav)) as w:
        sound = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())
        rate = w.getframerate()
    t = narr["times"][0]
    said = sound[int(t["at"] * rate):int(t["end"] * rate)]
    assert np.abs(said).mean() > 300
    # pressing Preview again makes nothing new; a changed look draws the card again but keeps the voices
    assert c.post(f"{url}/preview").json()["status"] == "ready" and not env["queued"]
    looked = c.patch(url, json={"chat": {"theme": "light"}}).json()
    assert not looked["made"]["preview"]["current"] and looked["narration"]["ready"]
    # an emoji is said by nobody, but it is a changed bubble: the video is out of date
    c.patch(url, json={"chat": {"theme": "dark"}})
    assert c.get(url).json()["made"]["preview"]["current"]
    emoji = c.patch(url, json={"script": CHAT.replace("😤", "😡")}).json()
    assert not emoji["made"]["preview"]["current"]


@needs_media
@pytest.mark.slow
def test_the_exported_chat_is_full_size_with_the_card_in_the_middle(env):
    from clipfoundry import db
    from clipfoundry.makers import textstory

    c = env["client"]
    script = CHAT + "\nSienna: 😤😤😤\nMe: ...\nSienna: ??\nMe: ok fine I'll buy you more"   # some say nothing
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "script": script}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    espeak = _espeak()
    c.patch(url, json={"chat": {"theme": "light", "people": {"Me": {"voice": espeak}, "Sienna": {"voice": espeak}}}})
    c.post(f"{url}/backgrounds/auto")
    c.post(f"{url}/export")
    assert [j["status"] for j in _run(env)] == ["done"]
    row = db.fetch("text_stories", story["id"])
    video = textstory.file_for(row, "export")
    v = next(s for s in _probe(video)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    x, y = cs.card_box((1080, 1920))
    last = _frame(video, row["narration"]["times"][-1]["end"] - 0.1, env["tmp"] / "c.png")
    assert np.abs(last[y + 60, x + 180] - np.array(cs.THEMES["light"]["head"])).max() < 14
    assert np.abs(last[1700, 540] - np.array(cs.THEMES["light"]["card"])).max() > 20   # below the card: background
    r = c.get(f"{url}/file/export", params={"download": True})
    assert r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "")


# ------------------------------------------------------------------ review fixes (2026-11-26)
def test_symbols_and_other_scripts_are_drawn_never_dropped():
    # ★ ✓ ✗ ♪ are not in the colour emoji font: drawn as letters, never an empty bubble
    assert cs._measure("★★★★★", 35) > 100   # noqa: SLF001
    assert cs._measure("rate it ✓ or ✗ ♪", 35) > cs._measure("rate it  or", 35) + 40   # noqa: SLF001
    card = cs.Card(1.0, "dark", "Sienna", 0)
    pic, bw, bh, room = card.bubble("★★★★★", "them", True)
    ink = np.asarray(pic.convert("RGB")).astype(int)[:, room:room + bw]
    text = np.array(cs.THEMES["dark"]["them_text"])
    assert (np.abs(ink - text).max(axis=2) < 40).sum() > 200   # the stars' letters are there
    # each letter is drawn with a font of this computer that has it, not the first font found
    dejavu = next((p for p in cs._other_paths() if p.endswith("DejaVuSans.ttf")), "")   # noqa: SLF001
    if dejavu:
        assert cs._has_glyph(dejavu, "★") and not cs._has_glyph(dejavu, "中")   # noqa: SLF001
    cjk = cs._path_for("中")   # noqa: SLF001
    if cjk:
        assert cs._has_glyph(cjk, "中") and cjk != dejavu   # noqa: SLF001
        assert [part for _, part in cs._segments("ok 中文", 35)] == ["ok ", "中文"]   # noqa: SLF001


def test_a_group_senders_emoji_name_is_drawn_as_an_emoji():
    if cs._emoji_font() is None:   # noqa: SLF001
        pytest.skip("no colour emoji font on this computer")
    resolved = cs.resolve("👻: boo\nJake: who\nMe: stop", {})
    card = cs.Card(1.0, "dark", resolved["contact"], 0)
    places = card.layout(resolved["messages"])
    assert places[0]["label"] == "👻"
    pic = np.asarray(card.state(resolved["messages"], places, 0).convert("RGB")).astype(int)
    y = int(places[0]["label_y"])
    label = pic[y:y + cs.SENDER_H, cs.SIDE:cs.SIDE + 80]
    # a colour picture (the ghost is white and grey with black eyes, so look for its light pixels on the dark card)
    assert (label.min(axis=2) > 150).sum() > 30


def test_the_preview_breaks_lines_and_pages_where_the_video_does():
    script = "\n".join(f"{'Sienna' if i % 3 else 'Me'}: " + "words " * (i % 17 + 1) + "😤 end" for i in range(80))
    msgs = cs.resolve(script, {})["messages"]
    full, third = cs.Card(1.0, "dark", "Sienna", 3), cs.Card(1 / 3, "dark", "Sienna", 3)
    a, b = full.layout(msgs), third.layout(msgs)
    assert [p["page"] for p in a] == [p["page"] for p in b] and len({p["page"] for p in a}) >= 3
    assert all(abs(x["top"] - y["top"] * 3) < 0.01 for x, y in zip(a, b))
    for p in b:
        assert p["top"] + p["h"] <= third.max_h + 1


def test_a_very_long_message_fits_its_page_and_ends_with_dots():
    lines, _ = cs.bubble_lines("😤" * 300)
    assert len(lines) == cs.MAX_LINES and lines[-1].endswith("…")
    for first in ("😤" * 300, "W" * 320, "word " * 64):
        msgs = cs.resolve(f"Sienna: {first}\nMe: ok\nSienna: and?", {})["messages"]
        card = cs.Card(1.0, "dark", "Sienna", 0)
        places = card.layout(msgs)
        for p in places:
            assert p["top"] + p["h"] + cs.BOTTOM_PAD <= card.max_h + 1, first[:5]
    # the first bubble stays under the header (the video opens on whose chat it is), cut to the lines that fit there
    msgs = cs.resolve("Sienna: " + "😤" * 170, {})["messages"]
    assert len(cs.bubble_lines(msgs[0]["text"])[0]) > cs.first_lines(False) == 16
    card = cs.Card(1.0, "dark", "Sienna", 0)
    places = card.layout(msgs)
    assert places[0]["page"] == 0 and places[0]["top"] + places[0]["h"] + cs.BOTTOM_PAD <= card.max_h + 1
    pic = card.state(msgs, places, 0)
    assert np.abs(np.asarray(pic.convert("RGB"))[40, 60].astype(int) - np.array(cs.THEMES["dark"]["head"])).max() < 14


def test_preview_bubbles_fit_their_words_without_raqm(monkeypatch):
    # Windows' Pillow usually has no raqm: letters go on whole pixels and a small size comes out wider than a third
    from PIL import ImageFont

    real = cs._truetype   # noqa: SLF001

    def basic(path, size):
        try:
            return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)
        except TypeError:
            return real(path, size)

    caches = (cs._font, cs._font_at, cs.bubble_lines, cs._has_glyph, cs._missing_shape)   # noqa: SLF001
    for c in caches:
        c.cache_clear()
    monkeypatch.setattr(cs, "_truetype", basic)
    try:
        card = cs.Card(1 / 3, "dark", "Sienna", 0)
        for text in ("believe little did believe believe little did believe believe",
                     "little did I know that she believed every single word of it",
                     "Does it embarrass you that my friend's boyfriend makes seven times your salary?"):
            pic, bw, bh, room = card.bubble(text, "them", True)
            lines, _ = cs.bubble_lines(text)
            assert all(cs._measure(line, card.text) + cs.PAD_X * card.s <= bw for line in lines)   # noqa: SLF001
    finally:
        for c in caches:
            c.cache_clear()


def _fake_voice(monkeypatch, fail: set[str] | None = None, rules: dict | None = None):
    """voice.speak writing a short tone (failing over to another voice for the said words in `fail`), and the tone
    shaper copying it."""
    from clipfoundry.makers import voice, voice_styles

    spoken: list[tuple[str, str]] = []

    def speak(said, path, voice="auto", speed=1.0, cancel=None):
        spoken.append((said, voice))
        n = int(cs.SR * 0.3)
        tone = (np.sin(np.arange(n) * 2 * np.pi * 220 / cs.SR) * 8000).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(cs.SR)
            w.writeframes(tone.tobytes())
        failed = said in (fail or set())
        return {"fallback": "The chosen voice did not answer, so another one read it." if failed else "",
                "voice_id": "x:other" if failed else voice, "rule": (rules or {}).get(voice, ""), "original": None}

    monkeypatch.setattr(voice, "speak", speak)
    monkeypatch.setattr(voice_styles, "shape", lambda src, dst, tone, cancel=None: shutil.copy(src, dst))
    return spoken


def test_a_line_read_by_another_voice_is_recorded_again_next_time(monkeypatch, tmp_path):
    chat = {"people": {"Sienna": {"voice": "x:ava"}, "Me": {"voice": "x:ben"}}}
    story = {"script": "Sienna: did you eat it\nMe: no", "chat": chat}
    spoken = _fake_voice(monkeypatch, fail={"did you eat it"})
    got = cs.make_voices(story, tmp_path)
    assert "another one read it" in got["fallback"] and got["fallback"].startswith("Sienna:")
    kept = sorted(p.name for p in (tmp_path / "lines").iterdir())
    assert len([k for k in kept if k.endswith(".wav")]) == 1   # only Me's line is kept
    assert not any(".once." in k or ".new." in k for k in kept)
    # the chosen voice works again: a new recording (another pace) asks for it again and the note goes
    _fake_voice(monkeypatch)
    again = cs.make_voices({**story, "chat": {**chat, "pace": "slow"}}, tmp_path)
    assert again["fallback"] == "" and len(list((tmp_path / "lines").glob("*.wav"))) == 2
    assert spoken == [("did you eat it", "x:ava"), ("no", "x:ben")]


def test_the_voices_licence_rules_come_from_every_line(monkeypatch, tmp_path):
    chat = {"people": {"Sienna": {"voice": "x:ava"}, "Me": {"voice": "x:ben"}}}
    story = {"script": "Sienna: did you eat it\nMe: no", "chat": chat}
    _fake_voice(monkeypatch, rules={"x:ava": "Say the voice is made by Ava Labs.", "x:ben": "Credit Ben Voices."})
    got = cs.make_voices(story, tmp_path)
    assert "Sienna: Say the voice is made by Ava Labs." in got["rule"] and "Me: Credit Ben Voices." in got["rule"]
    # Me's line changes: Sienna's comes from what was kept, and her voice's rule stays on the page
    spoken = _fake_voice(monkeypatch, rules={"x:ben": "Credit Ben Voices."})
    again = cs.make_voices({**story, "script": "Sienna: did you eat it\nMe: no way"}, tmp_path)
    assert spoken == [("no way", "x:ben")] and "Ava Labs" in again["rule"]
    # one voice for both: its rule once, as it is
    _fake_voice(monkeypatch, rules={"x:ava": "Say the voice is made by Ava Labs."})
    one = cs.make_voices({**story, "chat": {"people": {"Sienna": {"voice": "x:ava"}, "Me": {"voice": "x:ava"}}}},
                         tmp_path)
    assert one["rule"] == "Say the voice is made by Ava Labs."


def test_reading_without_voices_keeps_the_recorded_lines(monkeypatch, tmp_path):
    story = {"script": "Sienna: did you eat it\nMe: no", "chat": {}}
    _fake_voice(monkeypatch)
    cs.make_voices(story, tmp_path)
    assert len(list((tmp_path / "lines").glob("*.wav"))) == 2
    cs.make_voices({**story, "chat": {"read_aloud": False}}, tmp_path)
    assert len(list((tmp_path / "lines").glob("*.wav"))) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")
def test_every_card_picture_starts_on_its_own_frame(tmp_path):
    msgs = cs.resolve("Sienna: one\nMe: two\nSienna: three", {})["messages"]
    # bubbles that come in just before a 1/25 s step: FFmpeg's picture reader would round both rise pictures together
    times = [{"show": 0.0, "at": 0.1, "end": 1.0}, {"show": 3.182, "at": 3.282, "end": 4.0},
             {"show": 4.398, "at": 4.498, "end": 5.0}]
    listing = cs.make_cards({"script": "Sienna: one\nMe: two\nSienna: three", "chat": {}},
                            {"times": times, "total": 6.2}, (360, 640), tmp_path / "cards")
    text = listing.read_text(encoding="utf-8")
    assert text.count("option framerate 30") == text.count("file '")   # FFmpeg 5 or later takes it
    got = subprocess.run(["ffprobe", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                          "-show_entries", "frame=pts_time", "-of", "csv=p=0"], capture_output=True, text=True,
                         check=True).stdout.split()
    starts = [round(float(t) * 30) for t in got]
    # the first bubble, three pictures for each later one, and the last picture once more at the end
    assert len(starts) == 1 + 3 * (len(msgs) - 1) + 1 and len(set(starts)) == len(starts)
    assert starts[1:4] == [95, 96, 97] and starts[-1] == 186   # 3.182 s is frame 95; the end at 6.2 s


def test_a_script_line_reads_back_the_same():
    tricky = [{"who": "Me", "text": "//sigh"}, {"who": "Sienna", "text": "\\o/ yay"}, {"who": "Me", "text": "ok: fine"}]
    script = "\n".join(cs.write_line(m["who"], m["text"]) for m in tricky)
    assert cs.parse(cs.clean_script(script)) == tricky


def test_a_revision_never_loses_a_person_whose_name_lost_its_emoji(monkeypatch):
    from clipfoundry.makers import writer

    unknown: list[str] = []
    rows = writer._chat_rows([{"from": "Ben", "text": "hey"}, {"from": "Ben 😤", "text": "yo"},   # noqa: SLF001
                              {"from": "Carl", "text": "who"}], ["Ben 😤", "Me"], [], unknown)
    assert [r["from"] for r in rows] == ["Ben 😤", "Ben 😤"] and unknown == ["Carl"]
    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    asks: list[str] = []

    def fake(system, schema, settings, prompt, cancel, beat, message):
        asks.append(prompt)
        return json.dumps({"messages": [{"from": "Stranger", "text": "HI"}, {"from": "Me", "text": "HEY"}]})

    monkeypatch.setattr(writer, "_ask_with", fake)
    got = writer.write_chat("", tone="drama", length="short", settings={}, workspace_id="w",
                            current={"script": "Ben 😤: hi\nMe: hey"}, change="shout", remember=False)
    # asked again with what was wrong, then the chat was kept as it was
    assert len(asks) == 2 and "Stranger, who is not in the chat" in asks[1]
    assert got["script"] == "Ben 😤: hi\nMe: hey" and "kept as it was" in " ".join(got["notes"])


def test_a_long_story_part_answered_with_a_word_is_kept(monkeypatch):
    from clipfoundry.makers import writer

    asks: list[str] = []

    def fake(system, schema, settings, prompt, cancel, beat, message):
        asks.append(prompt)
        if "Part 1 now" in prompt:
            return json.dumps({"text": "Unchanged."})
        return json.dumps({"text": "the second part, now with a dog in it " * 30})

    monkeypatch.setattr(writer, "_ask_with", fake)
    one = " ".join(["first"] * (writer.PART_WORDS - 10))
    two = " ".join(["second"] * (writer.PART_WORDS - 10))
    notes: list[str] = []
    got = writer._revise_long_story("", {"title": "T", "script": f"{one}\n\n{two}"}, "add a dog", {},   # noqa: SLF001
                                    None, None, notes)
    assert got.startswith(one) and "dog" in got and "Unchanged" not in got
    assert len(asks) == 3 and "it had 1 words" in asks[1]
    assert notes == ["Part 1 was kept as it was: ClipForge AI's answer for it could not be used."]


def test_a_short_closing_part_and_a_cut_chat_are_revised(monkeypatch):
    from clipfoundry.makers import writer

    def fake(system, schema, settings, prompt, cancel, beat, message):
        if "Part 3 now" in prompt:
            return json.dumps({"text": "And she never called me again."})
        if "Part" in prompt and "now: <<<" in prompt:
            return json.dumps({"text": prompt.split("now: <<<", 1)[1].split(">>>", 1)[0]})
        msgs = [{"from": "Mom", "text": "dinner?"}, {"from": "Jake", "text": "yes"}]
        return json.dumps({"messages": msgs})

    monkeypatch.setattr(writer, "_ask_with", fake)
    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    script = "\n\n".join(" ".join(["word"] * 50) for _ in range(12)) + "\n\nAnd she never texted me again."
    notes: list[str] = []
    got = writer._revise_long_story("", {"title": "T", "script": script}, "she called, not texted", {},   # noqa: SLF001
                                    None, None, notes)
    assert got.endswith("And she never called me again.") and notes == []
    chat = "\n".join(f"{'Mom' if i % 2 else 'Jake'}: message {i}" for i in range(20))
    cut = writer.write_chat("", tone="drama", length="short", settings={}, workspace_id="w",
                            current={"script": chat}, change="Cut it down to the best two messages", remember=False)
    assert cut["script"] == "Mom: dinner?\nJake: yes" and not any("kept as it was" in n for n in cut["notes"])


def test_automatic_whose_phone_stays_with_the_same_person_after_a_revision(env, monkeypatch):
    from clipfoundry.makers import writer

    monkeypatch.setattr(writer, "_usable", lambda settings: True)
    # the revision makes Jake write first: Automatic would now pick Mom
    monkeypatch.setattr(writer, "_ask_with", lambda *a: json.dumps({"messages": [
        {"from": "Jake", "text": "sorry I'm late"}, {"from": "Mom", "text": "where are you"},
        {"from": "Jake", "text": "on my way"}, {"from": "Mom", "text": "ok"}]}))
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat",
                                                     "script": "Mom: where are you\nJake: on my way\nMom: ok"}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    assert c.get(url).json()["chat"]["whose_phone"] == "Jake"
    assert c.get(url).json()["chat"]["auto_phone"] == "Jake"
    c.post(f"{url}/write", json={"change": "Jake opens with an apology"})
    assert [j["status"] for j in _run(env)] == ["done"]
    got = c.get(url).json()
    assert got["chat"]["messages"][0]["who"] == "Jake" and got["chat"]["whose_phone"] == "Jake"
    assert got["chat"]["messages"][0]["side"] == "me" and got["chat"]["auto_phone"] == "Mom"
    # a chosen person who has left the chat (renamed in the text) is no help either: the phone stays put
    c.patch(url, json={"chat": {"me": "Jake"}})
    c.patch(url, json={"script": "Mom: where are you\nJacob: on my way\nMom: ok"})
    monkeypatch.setattr(writer, "_ask_with", lambda *a: json.dumps({"messages": [
        {"from": "Jacob", "text": "sorry"}, {"from": "Mom", "text": "where are you"}, {"from": "Jacob", "text": "omw"}]}))
    assert c.get(url).json()["chat"]["whose_phone"] == "Jacob"
    c.post(f"{url}/write", json={"change": "Jacob opens with an apology"})
    assert [j["status"] for j in _run(env)] == ["done"]
    assert c.get(url).json()["chat"]["whose_phone"] == "Jacob"


def test_switching_a_chat_to_narrated_and_back_keeps_its_messages(env):
    c = env["client"]
    story = c.post("/api/studio/text-stories", json={"kind": "chat", "script": CHAT}).json()
    url = f"/api/studio/text-stories/{story['id']}"
    narrated = c.patch(url, json={"kind": "narrated"}).json()
    assert narrated["kind"] == "narrated" and narrated["script"].count("\n\n") == 3
    back = c.patch(url, json={"kind": "chat"}).json()
    assert back["script"] == CHAT and [m["text"] for m in back["chat"]["messages"]] == [
        m["text"] for m in cs.parse(CHAT)]
