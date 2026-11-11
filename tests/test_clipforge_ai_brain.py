"""ClipForge AI's brain (docs/clipforge/CLIPFORGE_AI.md): memories in plain words with a kind, a source, a scope
and a meaning; twins merge; recall puts the rules first and finds a memory by meaning, within a budget; uses are
recorded so answers can explain themselves; guesses expire unless confirmed; the brain check, Rebuild, Tidy; a brain
file round-trips; the API. Everything here lives in a temporary test database and nothing leaves the computer."""
from __future__ import annotations

import time

import pytest

H = {"X-ClipFoundry": "1"}
WS = "local"


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


@pytest.fixture()
def client(data):
    from fastapi.testclient import TestClient
    from clipfoundry.api import app

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def test_a_memory_said_twice_is_one_memory_with_the_stronger_source(data):
    from clipfoundry import brain

    a = brain.remember(WS, "Never zoom in on faces", kind="rule", source="guessed")
    assert a["confidence"] == 0.5 and a["expires_at"] and a["scope"] == "all" and a["revision"] == 1
    assert a["meaning_model"] == "hash-v1" and len(a["meaning"]) == 256 * 4
    b = brain.remember(WS, "  never zoom in on faces.", kind="rule", source="said", tags=["framing"])
    assert b["id"] == a["id"] and b["revision"] == 2 and b["source"] == "said" and b["confidence"] == 1.0
    assert b["expires_at"] is None and b["tags"] == ["framing"]
    assert len(brain.list_(WS)) == 1
    with pytest.raises(brain.Invalid):
        brain.remember(WS, "", kind="rule")
    with pytest.raises(brain.Invalid):
        brain.remember(WS, "x" * 601)
    with pytest.raises(brain.Invalid):
        brain.remember(WS, "a thing", kind="wish")
    with pytest.raises(brain.Invalid):
        brain.remember(WS, "a thing", scope="galaxy:far")
    # the view never carries the vector
    v = brain.view(b)
    assert "meaning" not in v and "norm" not in v and v["has_meaning"] and not v["expired"]


def test_memories_in_any_language_are_twins_only_when_they_say_the_same_words(data):
    """Words of every script count (before Nov 9 2026 only a-z and 0-9 did, so all memories in Russian, Chinese or
    Arabic had the same norm: a second one merged into the first and replaced its words, and Tidy deleted all but one).
    Memories saved with that old norm are told apart by their words too."""
    from clipfoundry import brain, db
    from clipfoundry.brain import memories

    channel = brain.remember(WS, "Мой канал о велоспорте в горах")
    rule = brain.remember(WS, "Никогда не используй красные субтитры", kind="rule")
    other = brain.remember(WS, "Мой канал о готовке")
    assert len({channel["id"], other["id"]}) == 2 and brain.get(WS, channel["id"])["text"].endswith("в горах")
    again = brain.remember(WS, "мой канал о велоспорте  в горах.")  # the same words: one memory
    assert again["id"] == channel["id"] and again["revision"] == 2
    assert memories.twin(WS, "Мой канал о велоспорте в горах", ("rule", "fact"))["id"] == channel["id"]
    assert memories.twin(WS, "Никогда не используй синие субтитры", ("rule", "fact")) is None
    assert memories.twin(WS, "我的频道是关于山地车的", ("rule", "fact")) is None
    assert brain.remember(WS, "我的频道是关于山地车的")["id"] not in (channel["id"], other["id"], rule["id"])
    assert memories._norm("Café au lait, s'il vous plaît!") == "café au lait s'il vous plaît"  # noqa: SLF001
    assert memories._norm("Keep my intro < 3 s") == memories._legacy_norm("Keep my intro < 3 s")  # noqa: SLF001
    assert memories._norm("🔥🔥") == "🔥🔥" and memories.twin(WS, "👍", "fact") is None  # noqa: SLF001
    with pytest.raises(brain.Invalid):  # an edit into another memory's words is refused, in any language
        brain.edit(WS, other["id"], text="Мой канал о велоспорте в горах")
    assert brain.edit(WS, other["id"], text="Мой канал о походах")["text"] == "Мой канал о походах"

    # saved before: every one of these had the norm ''
    for row in (channel, other, rule):
        db.execute("UPDATE brain_memories SET norm = '' WHERE id = ?", (row["id"],))
    assert memories.twin(WS, "Мой канал о походах", "fact")["id"] == other["id"]
    assert memories.twin(WS, "Мой канал о рыбалке", "fact") is None
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}  # nothing deleted: they say different things
    assert len(brain.list_(WS)) == 4
    assert db.fetch("brain_memories", channel["id"])["norm"] == "мой канал о велоспорте в горах"
    assert brain.import_(WS, brain.export("nobody") | {"memories": [
        {"kind": "fact", "text": "Мой канал о рыбалке"}, {"kind": "fact", "text": "Мой канал о походах"}]}) == \
        {"added": 1, "updated": 0, "skipped": 1, "invalid": 0}


def test_recall_puts_the_rules_first_finds_by_meaning_and_keeps_to_the_scope_and_budget(data):
    from clipfoundry import brain

    rule = brain.remember(WS, "Never zoom in on faces", kind="rule")
    channel = brain.remember(WS, "The channel is about hiking in Norway")
    done = brain.episode(WS, "Asked \"shorten the intro\" and applied it as version 3", project_id="p1")
    wedding = brain.remember(WS, "This video is a wedding, keep it gentle", project_id="p2")
    other_ws = brain.remember("other", "Zoom on every face", kind="rule")
    r = brain.recall("add a zoom on the face at the start", WS, project_id="p1")
    assert r.ids[0] == rule["id"], r.memories
    assert wedding["id"] not in r.ids and other_ws["id"] not in r.ids
    assert r.prompt().startswith("What the owner has told ClipForge AI")
    assert "- [rule] Never zoom in on faces" in r.prompt()
    assert r.memories[0]["words"] > 0 and r.memories[0]["meaning"] > 0.3
    # a question about the channel finds the fact by its words, the episode stays out of an unrelated question
    r2 = brain.recall("what is my channel about?", WS)
    assert channel["id"] in r2.ids and done["id"] not in r2.ids
    # the episode comes back for its own project and a related question
    r3 = brain.recall("shorten the intro again", WS, project_id="p1")
    assert done["id"] in r3.ids
    # the wedding fact applies only to its video
    assert wedding["id"] in brain.recall("keep it gentle", WS, project_id="p2").ids
    assert wedding["id"] not in brain.recall("keep it gentle", WS).ids
    # the budget cuts facts before rules
    tiny = brain.recall("zoom on the face of the hiker in norway", WS, budget_chars=40)
    assert tiny.ids == [rule["id"]]
    assert brain.recall("anything", "empty-workspace").empty
    # the snapshot an answer keeps
    snap = r.snapshot()
    assert snap[0]["id"] == rule["id"] and snap[0]["text"] == "Never zoom in on faces" and "score" in snap[0]


def test_uses_are_recorded_and_counted(data):
    from clipfoundry import brain, db

    m = brain.remember(WS, "Captions always on")
    assert brain.record_use(WS, [m["id"], m["id"], ""], "change_request", "req-1") == 1
    assert brain.record_use(WS, [m["id"]], "chat", "msg-1") == 1
    row = brain.get(WS, m["id"])
    assert row["used_count"] == 2 and row["last_used_at"]
    where = [u["where_used"] for u in brain.uses(WS, m["id"])]
    assert where == ["chat", "change_request"]
    with pytest.raises(brain.Invalid):
        brain.record_use(WS, [m["id"]], "dreams")
    assert brain.record_use(WS, [m["id"]], "chat") == 1
    assert brain.record_use("other", [m["id"]], "chat") == 0  # another workspace's memory is never touched
    assert len(brain.uses(WS, m["id"])) == 3  # nor given a record
    # a memory deleted while the answer was written (with its project, or forgotten) is not given one either
    assert brain.record_use(WS, ["gone", m["id"]], "chat", "msg-2") == 1
    assert db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE memory_id = 'gone'") == 0
    assert len(brain.uses(WS, m["id"])) == 4


def test_a_use_recorded_while_a_memory_is_forgotten_or_tidied_away_is_never_left_behind(data, monkeypatch):
    """Forget and Tidy delete a memory with the record of its uses, and Tidy moves a twin's uses to the memory it
    keeps, each in one step: an answer that records a use at any moment in between (here: after every step they
    take) has it go with the memory, or it is not recorded. None is left over for a memory that is gone."""
    from contextlib import contextmanager

    from clipfoundry import brain, db

    said = brain.remember(WS, "Captions in yellow")
    twin = db.insert("brain_memories", {"workspace_id": WS, "kind": "fact", "text": "captions in yellow",
                                        "norm": "captions in yellow", "source": "did", "confidence": 0.8,
                                        "scope": "all", "tags": [], "data": {}, "meaning": None,
                                        "meaning_model": "", "enabled": 1, "revision": 1, "used_count": 0})
    gone = brain.remember(WS, "A guess that ran out", source="guessed")
    db.update("brain_memories", gone["id"], expires_at=time.time() - 5)
    forgotten = brain.remember(WS, "Never use red captions", kind="rule")
    every = [said["id"], twin["id"], gone["id"], forgotten["id"]]
    real, inside = db.connect, [False]

    @contextmanager
    def connect():
        with real() as conn:
            yield conn
        if not inside[0]:  # an answer that used them all records it right after each step
            inside[0] = True
            try:
                brain.record_use(WS, every, "chat", "msg-1")
            finally:
                inside[0] = False

    monkeypatch.setattr(db, "connect", connect)
    brain.forget(WS, forgotten["id"])
    assert brain.tidy(WS) == {"expired": 1, "merged": 1}
    monkeypatch.setattr(db, "connect", real)
    assert db.scalar("SELECT COUNT(*) FROM brain_memory_uses u WHERE NOT EXISTS (SELECT 1 FROM brain_memories m "
                     "WHERE m.id = u.memory_id)") == 0
    assert {m["id"] for m in db.select("brain_memories", "workspace_id = ?", (WS,))} == {said["id"]}
    assert len(brain.uses(WS, said["id"])) >= 2  # its own and its twin's moved to it


def test_guesses_expire_unless_confirmed_and_forget_removes_a_memory_with_its_uses(data):
    from clipfoundry import brain, db

    g = brain.remember(WS, "You seem to like fast cuts", source="guessed")
    assert g["id"] in brain.recall("fast cuts", WS).ids
    db.update("brain_memories", g["id"], expires_at=time.time() - 1)
    assert g["id"] not in brain.recall("fast cuts", WS).ids
    assert brain.view(brain.get(WS, g["id"]))["expired"]
    c = brain.confirm(WS, g["id"])
    assert c["source"] == "said" and c["confidence"] == 1.0 and c["expires_at"] is None and c["revision"] == 2
    assert g["id"] in brain.recall("fast cuts", WS).ids
    brain.record_use(WS, [g["id"]], "chat", "m1")
    gone = brain.forget(WS, g["id"])
    assert gone["id"] == g["id"]
    with pytest.raises(brain.Invalid):
        brain.get(WS, g["id"])
    assert db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE memory_id = ?", (g["id"],)) == 0
    with pytest.raises(brain.Invalid):
        brain.forget("other", c["id"])


def test_edit_changes_the_words_scope_and_kind_and_refuses_a_twin(data):
    from clipfoundry import brain

    a = brain.remember(WS, "Use dissolves between parts")
    b = brain.remember(WS, "Music under speech at -18 dB")
    e = brain.edit(WS, a["id"], text="Use dissolves between every part", kind="rule", scope="platform:tiktok",
                   tags=["look"])
    assert e["text"] == "Use dissolves between every part" and e["kind"] == "rule" and e["platform"] == "tiktok"
    assert e["scope"] == "platform:tiktok" and e["revision"] == 2 and e["tags"] == ["look"]
    assert e["id"] in brain.recall("dissolves", WS, platform="tiktok").ids
    assert e["id"] not in brain.recall("dissolves", WS, platform="youtube").ids
    c = brain.remember(WS, "Fade the music out at the end")
    with pytest.raises(brain.Invalid):
        brain.edit(WS, c["id"], text="music under speech at -18 db")  # b says that already
    with pytest.raises(brain.Invalid):
        brain.edit(WS, c["id"], kind="rule", text="use dissolves between every part")  # a (now a rule) does
    off = brain.edit(WS, b["id"], enabled=False)
    assert off["enabled"] == 0 and b["id"] not in brain.recall("music under speech", WS).ids
    assert brain.edit(WS, b["id"])["revision"] == off["revision"]  # nothing to change


def test_the_brain_check_rebuild_and_tidy(data):
    from clipfoundry import brain, db

    a = brain.remember(WS, "The channel is about hiking in Norway")
    b = brain.remember(WS, "The channel is all about hiking in Norway")   # a near twin
    old = brain.remember(WS, "Captions in yellow")
    db.update("brain_memories", old["id"], meaning_model="hash-v0")
    stale = brain.remember(WS, "Maybe you like drone shots", source="guessed")
    db.update("brain_memories", stale["id"], created_at=time.time() - 100 * 86400, expires_at=time.time() + 10)
    gone = brain.remember(WS, "A guess that ran out", source="guessed")
    db.update("brain_memories", gone["id"], expires_at=time.time() - 5)
    twin = db.insert("brain_memories", {"workspace_id": WS, "kind": "fact", "text": "captions in yellow",
                                        "norm": "captions in yellow", "source": "did", "confidence": 0.8,
                                        "scope": "all", "tags": ["x"], "data": {}, "meaning": None,
                                        "meaning_model": "", "enabled": 1, "revision": 1, "used_count": 3})
    c = brain.check(WS)
    assert not c["ok"] and c["total"] == 6 and c["counts"]["fact"] == 6 and c["sources"]["guessed"] == 2
    codes = {p["code"]: p for p in c["problems"]}
    assert set(codes) == {"missing_meaning", "old_meaning", "duplicates", "stale_guesses", "expired"}
    assert codes["old_meaning"]["ids"] == [old["id"]] and codes["missing_meaning"]["ids"] == [twin["id"]]
    assert sorted(c["duplicates"][0]) == sorted([a["id"], b["id"]])
    assert codes["stale_guesses"]["ids"] == [stale["id"]] and codes["expired"]["ids"] == [gone["id"]]
    assert c["size_bytes"] > 0 and c["meaning_model"] == "hash-v1"
    assert brain.rebuild(WS) == 2
    assert brain.get(WS, old["id"])["meaning_model"] == "hash-v1"
    assert brain.tidy(WS) == {"expired": 1, "merged": 1}
    kept = brain.get(WS, old["id"])
    assert kept["used_count"] == 3 and "x" in kept["tags"] and kept["source"] == "said"
    with pytest.raises(brain.Invalid):
        brain.get(WS, gone["id"])
    after = brain.check(WS)
    assert {p["code"] for p in after["problems"]} == {"duplicates", "stale_guesses"}


def test_a_brain_file_round_trips_and_merges_by_revision(data):
    from clipfoundry import brain

    a = brain.remember(WS, "Never zoom in on faces", kind="rule")
    brain.remember(WS, "The channel is about hiking in Norway", tags=["channel"])
    brain.record_use(WS, [a["id"]], "chat")
    file = brain.export(WS)
    assert file["format"] == brain.FORMAT and file["count"] == 2
    assert all("meaning" not in m and "norm" not in m for m in file["memories"])
    # into another workspace: the ids are taken, so the memories get fresh ids
    got = brain.import_("studio", file)
    assert got == {"added": 2, "updated": 0, "skipped": 0, "invalid": 0}
    mine = brain.list_("studio")
    assert {m["text"] for m in mine} == {"Never zoom in on faces", "The channel is about hiking in Norway"}
    assert {m["id"] for m in mine}.isdisjoint({m["id"] for m in file["memories"]})
    assert a["id"] in brain.recall("zoom", WS).ids and brain.recall("zoom", "studio").memories
    # back into the same workspace: nothing newer, nothing changes
    assert brain.import_(WS, file) == {"added": 0, "updated": 0, "skipped": 2, "invalid": 0}
    # a newer revision in the file updates the memory
    newer = {**file, "memories": [{**file["memories"][0], "text": "Never zoom in on faces or hands", "revision": 5},
                                  {"kind": "wish", "text": "x"}, {"kind": "fact", "text": ""}]}
    assert brain.import_(WS, newer) == {"added": 0, "updated": 1, "skipped": 0, "invalid": 2}
    assert brain.get(WS, a["id"])["text"] == "Never zoom in on faces or hands"
    with pytest.raises(brain.Invalid):
        brain.import_(WS, {"format": "something else"})


def test_the_memory_api(client):
    r = client.post("/api/brain/memories", json={"text": "Never zoom in on faces", "kind": "rule"}, headers=H)
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["source"] == "said" and "meaning" not in rule
    assert client.post("/api/brain/memories", json={"text": "x", "kind": "wish"}, headers=H).status_code == 422
    r = client.post("/api/brain/memories", json={"text": "This video is a wedding", "project_id": "p2"}, headers=H)
    assert r.json()["scope"] == "project:p2"
    assert len(client.get("/api/brain/memories").json()) == 2
    found = client.get("/api/brain/memories?q=zoom").json()
    assert [m["id"] for m in found] == [rule["id"]] and found[0]["score"] > 0
    r = client.post("/api/brain/memories/recall", json={"query": "zoom on the face", "project_id": "p2"})
    assert r.status_code == 200 and r.json()["memories"][0]["id"] == rule["id"]
    assert r.json()["prompt"].startswith("What the owner")
    assert client.get("/api/brain/memories/check").json()["ok"]
    r = client.patch(f"/api/brain/memories/{rule['id']}", json={"text": "Never zoom in on faces, ever"}, headers=H)
    assert r.json()["revision"] == 2
    assert client.post(f"/api/brain/memories/{rule['id']}/confirm", headers=H).json()["source"] == "said"
    assert client.get(f"/api/brain/memories/{rule['id']}/uses").json() == []
    assert client.get("/api/brain/memories/export").json()["count"] == 2
    assert client.get("/api/brain/memories/export").headers["content-disposition"].endswith('brain.json"')
    file = client.get("/api/brain/memories/export").json()
    assert client.post("/api/brain/memories/import", json={"data": file}, headers=H).json()["skipped"] == 2
    assert client.post("/api/brain/memories/import", json={"data": {"format": "x"}}, headers=H).status_code == 422
    assert client.post("/api/brain/memories/rebuild", headers=H).json() == {"rebuilt": 0}
    assert client.post("/api/brain/memories/tidy", headers=H).json() == {"expired": 0, "merged": 0}
    assert client.delete(f"/api/brain/memories/{rule['id']}", headers=H).json()["forgotten"]["id"] == rule["id"]
    assert client.delete(f"/api/brain/memories/{rule['id']}", headers=H).status_code == 404
    # writes need the app's own header
    assert client.post("/api/brain/memories", json={"text": "No header"}).status_code == 403


def test_smart_edit_advice_reads_the_owners_rules(data):
    from clipfoundry import brain
    from clipfoundry.studio import ai_editor, video_flow

    window = [{"i": 0, "file": "a.mp4", "start": 0.0, "dur": 3.0, "text": "Hello there"}]
    assert ai_editor.build_prompt(window, {}, 1, 1).startswith("Transcript part 1 of 1")
    block = "What the owner has told ClipForge AI:\n- [rule] Keep every joke"
    p = ai_editor.build_prompt(window, {"goal": "fun"}, 1, 1, block)
    assert p.startswith(block + "\nGoal: fun\n\nTranscript part 1 of 1")
    rule = brain.remember(WS, "Keep every joke, even the bad ones", kind="rule")
    brain.remember(WS, "This one is a wedding", project_id="other-video")
    got = video_flow._smart_memories({"workspace_id": WS, "id": "p9"}, {"goal": "a funny hiking film"})
    assert "- [rule] Keep every joke, even the bad ones" in got and "wedding" not in got
    assert brain.uses(WS, rule["id"])[0]["where_used"] == "smart_edit"
    assert brain.uses(WS, rule["id"])[0]["ref_id"] == "p9"
    assert video_flow._smart_memories({"workspace_id": "nobody", "id": "p9"}, {}) == ""
    # a fake answer through advise carries the block in every window
    seen = []

    def fake(settings, prompt, **kw):
        seen.append(prompt)
        return '{"leave_out": [], "pictures": [], "chapters": [], "music": "calm"}'

    ai_editor.advise(window, {}, {"ai_provider": "ollama"}, complete=fake, memories=block)
    assert seen and seen[0].startswith(block)
