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
    rows = db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE memory_id = ?", (said["id"],))
    assert rows >= 2 and brain.get(WS, said["id"])["used_count"] == rows  # its own and its twin's, all counted


def _did_twin(text: str, **fields) -> dict:
    """A twin of a memory: the same words and kind, saved apart (two answers at the same moment, or a brain file)."""
    from clipfoundry import db
    from clipfoundry.brain import memories

    return db.insert("brain_memories", {"workspace_id": WS, "kind": "fact", "text": text,
                                        "norm": memories._norm(text), "source": "did",  # noqa: SLF001
                                        "confidence": 0.8, "scope": "all", "tags": [], "data": {}, "meaning": None,
                                        "meaning_model": "", "enabled": 1, "revision": 1, "used_count": 0, **fields})


def test_a_twin_merged_into_a_memory_forgotten_meanwhile_leaves_no_use_behind(data, monkeypatch):
    """Tidy merges a twin into the stronger memory of the two. When that one is forgotten before Tidy merges them,
    the twin stays with the record of its own uses and nothing is merged; forgotten after (here: after any of Tidy's
    steps), it goes with every use, its twin's too. None is ever moved to a memory that is gone."""
    from contextlib import contextmanager

    from clipfoundry import brain, db

    real = db.connect
    for step in range(0, 9):
        for m in db.select("brain_memories", "workspace_id = ?", (WS,)):
            brain.forget(WS, m["id"])
        said = brain.remember(WS, "Captions in yellow")
        twin = _did_twin("captions in yellow")
        brain.record_use(WS, [said["id"], twin["id"]], "chat", "msg-1")
        brain.record_use(WS, [twin["id"]], "chat", "msg-2")
        done, forgot = [0], [False]
        if step == 0:  # forgotten before Tidy starts
            brain.forget(WS, said["id"])
            forgot[0] = True

        @contextmanager
        def connect():
            with real() as conn:
                yield conn
            done[0] += 1
            if done[0] == step:  # the stronger one is forgotten right after this step of Tidy
                brain.forget(WS, said["id"])
                forgot[0] = True

        monkeypatch.setattr(db, "connect", connect)
        result = brain.tidy(WS)
        monkeypatch.setattr(db, "connect", real)
        assert db.scalar("SELECT COUNT(*) FROM brain_memory_uses u WHERE NOT EXISTS (SELECT 1 FROM brain_memories m "
                         "WHERE m.id = u.memory_id)") == 0, step
        left = [(m["id"], m["used_count"], db.scalar("SELECT COUNT(*) FROM brain_memory_uses WHERE memory_id = ?",
                                                     (m["id"],))) for m in db.select("brain_memories",
                                                                                     "workspace_id = ?", (WS,))]
        if not forgot[0]:  # merged: one memory with every use
            assert result == {"expired": 0, "merged": 1} and left == [(said["id"], 3, 3)], step
        elif db.fetch("brain_memories", twin["id"]):  # forgotten before the merge: the twin stays as it was
            assert result == {"expired": 0, "merged": 0} and left == [(twin["id"], 2, 2)], step
        else:  # forgotten after the merge: with every use, its twin's too
            assert result == {"expired": 0, "merged": 1} and left == [], step


@pytest.mark.parametrize("what", ["confirm", "edit", "remember"])
def test_what_the_owner_does_while_tidy_runs_waits_for_it_and_is_never_lost(data, monkeypatch, what):
    """Tidy deletes expired guesses and merges twins in one locked step. A guess confirmed, a twin given other words
    or the same words said again (another page, an answer) while Tidy looks at the memories waits until Tidy is done:
    it is never done on what Tidy read before and then undone by it. Then it applies to the memory that is there now
    (the same words said again keep what Tidy merged: every tag and use), or the owner is told the memory is gone."""
    import threading

    from clipfoundry import brain, db
    from clipfoundry.brain import memories

    guess = brain.remember(WS, "You seem to like drone shots", source="guessed")
    _did_twin("you seem to like drone shots", tags=["drone"])  # did: Tidy keeps it, the guess goes
    said = brain.remember(WS, "Captions in yellow", tags=["style"])
    twin = _did_twin("captions in yellow", tags=["look"], used_count=2)  # merged into `said`
    act = {"confirm": lambda: brain.confirm(WS, guess["id"]),
           "edit": lambda: brain.edit(WS, twin["id"], text="Captions in white"),
           "remember": lambda: brain.remember(WS, "Captions in yellow", tags=["new"])}[what]
    real, owner, outcome = memories._norm, [], {}  # noqa: SLF001

    def do():
        try:
            outcome["row"] = act()
        except brain.Invalid as exc:
            outcome["gone"] = exc

    def norm(text):  # Tidy reads the words of each memory inside its step: the owner acts right then
        if not owner and threading.current_thread() is threading.main_thread():
            owner.append(threading.Thread(target=do))
            owner[0].start()
            owner[0].join(1.0)
            assert owner[0].is_alive(), "the owner's change did not wait for Tidy"
        return real(text)

    monkeypatch.setattr(memories, "_norm", norm)
    assert brain.tidy(WS) == {"expired": 0, "merged": 2}
    owner[0].join(30)
    assert not owner[0].is_alive()
    monkeypatch.setattr(memories, "_norm", real)
    kept = brain.get(WS, said["id"])
    if what == "remember":
        assert outcome["row"]["id"] == said["id"] and outcome["row"]["tags"] == ["style", "look", "new"]
        assert kept["tags"] == ["style", "look", "new"] and kept["used_count"] == 2 and kept["source"] == "said"
    else:  # confirmed or edited after Tidy merged it away: the owner is told it is gone, and nothing was lost
        assert outcome["gone"].status == 404 and str(outcome["gone"]) == "Memory not found."
        assert kept["tags"] == ["style", "look"] and kept["used_count"] == 2
        assert not db.select("brain_memories", "text = ?", ("Captions in white",))
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}


def test_the_same_words_said_again_while_their_memory_changes_or_goes_are_kept(data, monkeypatch):
    """Saying something ClipForge AI remembers already updates that memory. When it is forgotten, tidied into its
    twin or changed between ClipForge reading it and writing it, ClipForge reads it again: the words are kept
    (anew, in the twin Tidy kept, or with the change), and what the change wrote is never put back as it was."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    real = memories.twin
    for meanwhile in ("forget", "tidy", "edit"):
        for m in brain.list_(WS):
            brain.forget(WS, m["id"])
        first = brain.remember(WS, "Music under speech at -18 dB", tags=["sound"])
        other = _did_twin("music under speech at -18 db", tags=["mix"])
        brain.forget(WS, other["id"]) if meanwhile != "tidy" else None
        once = []

        def twin(ws, text, kind):
            found = real(ws, text, kind)
            if not once:
                once.append(1)
                if meanwhile == "forget":
                    brain.forget(WS, first["id"])
                elif meanwhile == "tidy":
                    brain.tidy(WS)  # the `said` one is kept, with the twin's tag
                else:
                    brain.edit(WS, first["id"], tags=["sound", "voice"])
            return found

        monkeypatch.setattr(memories, "twin", twin)
        row = brain.remember(WS, "Music under speech at -18 dB", tags=["music"])
        monkeypatch.setattr(memories, "twin", real)
        left = brain.list_(WS)
        assert [m["id"] for m in left] == [row["id"]] and row["text"] == "Music under speech at -18 dB", meanwhile
        assert row["tags"] == {"forget": ["music"], "tidy": ["sound", "mix", "music"],
                               "edit": ["sound", "voice", "music"]}[meanwhile], meanwhile


def test_a_confirmation_or_edit_of_a_memory_gone_meanwhile_says_it_is_gone(data, monkeypatch):
    """Tidy (or Forget) can delete a memory between a confirmation or an edit reading it and writing it: the owner is
    told it is not there any more, instead of an error."""
    from clipfoundry import brain, db

    guess = brain.remember(WS, "You seem to like drone shots", source="guessed")
    other = brain.remember(WS, "Fade the music out at the end")
    real = db.update

    def update(table, value, key="id", **fields):
        if table == "brain_memories" and value in (guess["id"], other["id"]):
            brain.forget(WS, value)  # just before the change is written
        return real(table, value, key, **fields)

    monkeypatch.setattr(db, "update", update)
    for do in (lambda: brain.confirm(WS, guess["id"]), lambda: brain.edit(WS, other["id"], text="Fade out slowly")):
        with pytest.raises(brain.Invalid) as gone:
            do()
        assert gone.value.status == 404 and str(gone.value) == "Memory not found."


def test_tidy_merges_only_twins_kept_for_the_same_videos_and_switched_on_or_off_alike(data):
    """Twins (the same words and kind) come from two answers saving at the same moment or from a brain file. Tidy
    merges those that apply in the same place and are switched on or off alike, and the one it keeps stands for all
    of them: every use, every tag, and it expires only when the last of them would. The others stay as they are, so a
    memory for every video never shrinks to one video (and goes when that video is deleted), and one that is
    switched on stays on."""
    from clipfoundry import brain, db

    here = brain.remember(WS, "Captions in yellow", project_id="p1")  # said, for one video
    everywhere = _did_twin("captions in yellow")  # for every video
    same = _did_twin("captions in yellow", scope="project:p1", project_id="p1", used_count=2, tags=["look"],
                     last_used_at=time.time() - 60)  # for the same video
    off = brain.remember(WS, "Music under speech at -18 dB")
    brain.edit(WS, off["id"], enabled=False)  # said, switched off
    on = _did_twin("music under speech at -18 db")  # switched on
    guess = brain.remember(WS, "You seem to like drone shots", source="guessed", project_id="p1")
    later = _did_twin("you seem to like drone shots", scope="project:p1", project_id="p1", source="guessed",
                      confidence=0.5, expires_at=guess["expires_at"] + 86400)  # guessed again, a day later
    assert brain.tidy(WS) == {"expired": 0, "merged": 2}  # `same` into `here`, `later` into `guess`
    assert db.fetch("brain_memories", same["id"]) is None and db.fetch("brain_memories", later["id"]) is None
    kept = brain.get(WS, here["id"])
    assert kept["used_count"] == 2 and kept["tags"] == ["look"] and kept["last_used_at"]
    assert kept["scope"] == "project:p1" and kept["source"] == "said"
    assert brain.get(WS, guess["id"])["expires_at"] == later["expires_at"]  # as long as the later guess would last
    assert everywhere["id"] in brain.recall("captions in yellow", WS, project_id="p2").ids  # still for every video
    assert on["id"] in brain.recall("music under speech", WS).ids  # still on
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}  # what stays apart stays apart


def test_the_same_words_kept_for_every_video_and_for_one_are_read_once_and_left_to_the_owner(data):
    """Twins Tidy keeps apart (one for every video, one for a video) both apply to that video: its prompt reads the
    words once, so they take one rule's room. The brain check still shows them to the owner, saying that Tidy merges
    only twins kept for the same videos."""
    from clipfoundry import brain
    from clipfoundry.brain import meaning

    everywhere = brain.remember(WS, "Never use red captions", kind="rule")
    vec, model = meaning.make("never use red captions")
    here = _did_twin("never use red captions", kind="rule", scope="project:p1", project_id="p1", meaning=vec,
                     meaning_model=model)
    brain.remember(WS, "Keep the intro under five seconds", kind="rule")
    got = brain.recall("captions", WS, project_id="p1")
    assert sorted(m["text"].lower() for m in got.memories) == ["keep the intro under five seconds",
                                                               "never use red captions"]
    assert len({everywhere["id"], here["id"]} & set(got.ids)) == 1
    assert everywhere["id"] in brain.recall("captions", WS, project_id="p2").ids
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}
    assert [p["text"] for p in brain.check(WS)["problems"] if p["code"] == "duplicates"] == [
        "1 memories look like twins (review them; Tidy merges exact twins kept for the same videos)"]


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


def test_a_brain_file_never_makes_twins_and_a_memory_gone_meanwhile_gets_its_newer_words(data, monkeypatch):
    """A brain file's newer revision of a memory is skipped when another memory says those words already (an edit
    refuses that too), so a file never makes twins. When the memory is forgotten or tidied away between ClipForge
    reading it and writing it, it is read again, and the file's newer words are added (not counted as updated and
    then found nowhere)."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    brain.remember(WS, "Never use red captions", kind="rule")
    intro = brain.remember(WS, "Keep the intro short", kind="rule", project_id="p1")
    mine = next(m for m in brain.export(WS)["memories"] if m["id"] == intro["id"])
    twin = {"format": brain.FORMAT, "memories": [{**mine, "text": "never use RED captions", "revision": 5}]}
    assert brain.import_(WS, twin) == {"added": 0, "updated": 0, "skipped": 1, "invalid": 0}
    assert brain.get(WS, intro["id"])["text"] == "Keep the intro short"
    real = memories._write_over  # noqa: SLF001

    def write_over(old, fields):  # forgotten just before the file's words are written
        brain.forget(WS, old["id"])
        monkeypatch.setattr(memories, "_write_over", real)
        return real(old, fields)

    monkeypatch.setattr(memories, "_write_over", write_over)
    newer = {"format": brain.FORMAT, "memories": [{**mine, "text": "Keep the intro under five seconds", "revision": 5}]}
    assert brain.import_(WS, newer) == {"added": 1, "updated": 0, "skipped": 0, "invalid": 0}
    row = brain.get(WS, intro["id"])
    assert row["text"] == "Keep the intro under five seconds" and row["scope"] == "project:p1" and row["revision"] == 5


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
