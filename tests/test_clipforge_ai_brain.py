"""ClipForge AI's brain (docs/clipforge/CLIPFORGE_AI.md): memories in plain words with a kind, a source, a scope
and a meaning; twins merge; recall puts the rules first and finds a memory by meaning, within a budget; uses are
recorded so answers can explain themselves; guesses expire unless confirmed; the brain check, Rebuild, Tidy; a brain
file round-trips; the API. Everything here lives in a temporary test database and nothing leaves the computer."""
from __future__ import annotations

import json
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
    Memories saved with that old norm are told apart by their words too: the stored form is brought up to date the
    first time the memories are looked at after a start."""
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
    assert memories._norm("Keep my intro < 3 s") == "keep my intro < 3 s"  # noqa: SLF001
    assert memories._norm("🔥🔥") == "🔥🔥" and memories.twin(WS, "👍", "fact") is None  # noqa: SLF001
    with pytest.raises(brain.Invalid):  # an edit into another memory's words is refused, in any language
        brain.edit(WS, other["id"], text="Мой канал о велоспорте в горах")
    assert brain.edit(WS, other["id"], text="Мой канал о походах")["text"] == "Мой канал о походах"

    # saved before: every one of these had the norm ''
    for row in (channel, other, rule):
        db.execute("UPDATE brain_memories SET norm = '' WHERE id = ?", (row["id"],))
    memories._norms_current.clear()  # noqa: SLF001  (a new start of the app)
    assert memories.twin(WS, "Мой канал о походах", "fact")["id"] == other["id"]
    assert db.fetch("brain_memories", rule["id"])["norm"] == "никогда не используй красные субтитры"
    assert memories.twin(WS, "Мой канал о рыбалке", "fact") is None
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}  # nothing deleted: they say different things
    assert len(brain.list_(WS)) == 4
    assert db.fetch("brain_memories", channel["id"])["norm"] == "мой канал о велоспорте в горах"
    assert brain.import_(WS, brain.export("nobody") | {"memories": [
        {"kind": "fact", "text": "Мой канал о рыбалке"}, {"kind": "fact", "text": "Мой канал о походах"}]}) == \
        {"added": 1, "updated": 0, "skipped": 1, "invalid": 0}


def test_a_mark_of_a_letter_or_the_sign_of_a_number_makes_other_words(data):
    """Words are compared strictly: only what cannot change their meaning is left out (capitals, spacing, how a
    letter with an accent or a full-width character was typed, the kind of dash or apostrophe, and quotes, brackets
    and sentence marks around a word). A Thai tone mark, an Indic vowel sign, a sign, a symbol, an emoji, a hyphen
    inside a word and a point, comma, colon or slash inside a number all belong to the words, and so does whatever
    stands alone between spaces: a mark a rule names, a minus set apart, a dash, a smiley. Until Nov 12 2026 some
    were left out, so "-3 dB" and "+3 dB", then "亮度+10" and "亮度-10", "EV+1" and "EV-1" or "<3 s" and ">3 s", then
    "never end a caption with !" and "… with ?" or "Maßen" and "Massen" were twins: the second replaced the first,
    and forgetting one forgot both. Memories saved with an earlier form are told apart by their words too."""
    import re
    import unicodedata

    from clipfoundry import brain, db
    from clipfoundry.brain import memories

    pairs = [("ตัดคลิปข่าวออก", "ตัดคลิปข้าวออก"), ("संगीत तेज़ रखो", "संगीत ताज़ा रखो"),
             ("Voice at -3 dB", "Voice at +3 dB"), ("The cut at 0:42 stays", "The cut at 0.42 stays"),
             ("Fade in over .5 s", "Fade in over 5 s"), ("Music ±2 dB", "Music 2 dB"),
             ("亮度+10", "亮度-10"), ("Shoot at EV+1", "Shoot at EV-1"), ("Post at 18:00 UTC+2", "Post at 18:00 UTC-2"),
             ("Peaks within +/-3 dB", "Peaks within -3 dB"), ("Gain +.5 dB", "Gain -.5 dB"),
             ("音量を＋３ｄＢ", "音量を－３ｄＢ"), ("Intro <3 s", "Intro >3 s"), ("Clips ≤ 60 s", "Clips ≥ 60 s"),
             ("Captions at 50%", "Captions at 50"), ("Mute the music 🔇", "Mute the music 🔊"),
             ("Use b-roll", "Use b roll"), ("Tag it #1", "Tag it 1"), ("Credit @trailnotes", "Credit trailnotes"),
             ("Budget $5", "Budget €5"), ("Speed x2", "Speed ×2"), ("Colour C++ blue", "Colour C blue"),
             # what stands alone between spaces counts as it is, and so does every sign at the edge of a word
             ('Never use "!" in titles', 'Never use "?" in titles'), ("Never end a caption with !",
                                                                    "Never end a caption with …"),
             ("Never end a title with .", "Never end a title with ?"), ("No , before and", "No ; before and"),
             ("The voice sits at - 3 dB", "The voice sits at 3 dB"), ("The music sits at − 6 dB",
                                                                    "The music sits at + 6 dB"),
             ("Trink in Maßen", "Trink in Massen"), ("الشفافية ٥٠٪", "الشفافية ٥٠"), ("Opacity 50﹪", "Opacity 50"),
             ("Rate it 5*", "Rate it 5"), ("End titles with ‼️", "End titles with ⁉️"),
             ("Width != 30", "Width = 30"), ("End on :)", "End on :("), ("Music low - voice up", "Music low voice up"),
             ("- keep it low", "keep it low"), ("Garde la musique basse !", "Garde la musique basse")]
    kept = []
    for one, other in pairs:
        a, b = brain.remember(WS, one), brain.remember(WS, other)
        assert a["id"] != b["id"] and (a["revision"], b["revision"]) == (1, 1), (one, other)
        kept += [a, b]
    norm = memories._norm  # noqa: SLF001
    assert norm("cafe\u0301") == norm("caf\u00e9") == "caf\u00e9"  # an accent typed apart is the same letter
    assert norm("−3 dB") == norm("-3 dB") == norm("–3 dB") == "-3 db" and norm("2-3 s") == "2-3 s"
    assert norm("a-3") == "a-3" and norm("music low - voice up") == norm("music low — voice up") \
        == "music low - voice up"  # whichever dash it is, it counts
    assert norm("1,000 views at 16:9") == "1,000 views at 16:9" and norm("The end. 5 more") == "the end 5 more"
    assert norm("＋３ｄＢ　ＯＫ") == norm("+3dB ok") == "+3db ok" and norm("STRASSE") == norm("Strasse") == "strasse"
    assert norm("Straße") == norm("STRAßE") == "straße"  # capitals are left out, "ß" is not "ss"
    assert norm("Call it “Trail Notes”!") == norm("call it (trail notes)") == norm("call it 'Trail Notes'.") \
        == "call it trail notes"
    assert norm("keep\u200b the music\u00ad low\ufeff") == "keep the music low"  # what nobody sees is left out
    assert norm("\u202bאל תזיז\u202c") == "אל תזיז"
    # a joiner makes another emoji or word
    assert norm("👨\u200d👩\u200d👧") != norm("👨👩👧") and norm("می\u200cخواهم") != norm("میخواهم")
    assert norm("- keep it low") == norm("– keep it low") == "- keep it low"
    assert norm("• keep it low") == "• keep it low"
    assert norm("**Keep** it low…") == "**keep** it low" and norm("¿Por qué?") == norm("por qué") == "por qué"
    assert norm('Never use "!" in titles.') == 'never use "!" in titles'  # a mark alone is kept as it is, quotes too
    assert norm("(Keep it low),") == norm("“keep it low”!?") == norm("`keep` it low...") == "keep it low"
    assert norm("End on :)") == "end on :)" and norm("5' or 5\"") == "5 or 5"  # the one known limit
    assert norm("fade in over .5 s.") == "fade in over .5 s" and norm("it’s") == norm("it's") == "it's"
    assert norm("❤️") == norm("❤") and norm("...") == "..." and norm("  ") == ""
    # behind a word, the marks that end a sentence in other scripts are left out like . , ! ? (they were not: the
    # same words with and without the full stop of Armenian, Amharic, Khmer, Tibetan … were two memories)
    for word, stop in (("բարև", "։"), ("ሰላም", "።"), ("ሰላም", "፣"), ("សួស្តី", "។"), ("བཀྲ་ཤིས", "།"), ("မင်္ဂလာပါ", "။"),
                       ("ｺﾝﾆﾁﾊ", "｡"), ("καλημέρα", "·"), ("καλημέρα", "\u0387"), ("τι", "\u037e"), ("नमस्ते", "॥"),
                       ("مرحبا", "؟"), ("你好", "。"), ("wow", "‼"), ("ᠰᠠᠢᠨ", "᠃"), ("ꯍꯥꯏ", "꯫"), ("ok", "․")):
        assert norm(word + stop) == norm(f"“{word}”{stop}{stop}") == norm(word) != "", (word, stop)
    assert norm("ሰላም ። ዓለም") == "ሰላም ። ዓለም" and norm("։") == "։"  # standing alone, a mark counts as it is
    assert norm("col·lecció") == "col·lecció" and norm("a։b") == "a։b" and norm("։բարև") == "։բարև"  # only behind
    assert len(memories._STOPS) == 295  # noqa: SLF001  (Unicode's list, written out: the same in every Python)
    assert [m["text"] for m in memories.forget_words(WS, "voice at -3 dB")] == ["Voice at -3 dB"]
    assert [m["text"] for m in memories.forget_words(WS, "亮度+10")] == ["亮度+10"]
    assert [m["text"] for m in memories.forget_words(WS, "intro >3 s")] == ["Intro >3 s"]
    assert brain.remember(WS, "voice at +3 dB.")["id"] == kept[5]["id"]  # the same words: the same memory
    assert brain.remember(WS, "音量を+3dB")["id"] == kept[22]["id"]  # typed on a full-width keyboard or not
    gone = {kept[4]["id"], kept[12]["id"], kept[25]["id"]}

    # saved by an earlier build: on Nov 9-11 2026 with the form that left marks and signs out, before with only a-z
    def nov9(text: str) -> str:
        return " ".join(re.findall(r"(?:[^\W_]|')+", text.lower().replace("’", "'")))

    def released(text: str) -> str:
        return " ".join(re.findall(r"[a-z0-9']+", text.lower().replace("’", "'")))

    left = [m for m in kept if m["id"] not in gone]
    for i, m in enumerate(left):
        db.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", ((nov9, released)[i % 2](m["text"]), m["id"]))
    apart = brain.remember(WS, unicodedata.normalize("NFD", "Café music in the intro"))  # the accent typed apart
    db.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", (released(apart["text"]), apart["id"]))
    assert nov9(pairs[0][0]) == nov9(pairs[0][1]) and released(pairs[6][0]) == released(pairs[6][1]) == "10"
    assert released(apart["text"]) == "cafe music in the intro" != released("Café music in the intro")
    was = {m["id"]: brain.get(WS, m["id"]) for m in left}
    memories._norms_current.clear()  # noqa: SLF001  (a new start of the app)
    assert memories.twin(WS, "Café music in the intro", "fact")["id"] == apart["id"]  # found by either spelling
    for mid, m in was.items():  # only the stored form changed: the words, the revision and the dates are as they were
        now = brain.get(WS, mid)
        assert (now["text"], now["revision"], now["updated_at"]) == (m["text"], m["revision"], m["updated_at"])
        assert now["norm"] == norm(m["text"])
    assert memories.twin(WS, "ตัดคลิปข้าวออก", "fact")["id"] == kept[1]["id"]
    assert memories.twin(WS, "Fade in over 5 s", "fact")["id"] == kept[9]["id"]
    assert memories.twin(WS, "亮度-10", "fact")["id"] == kept[13]["id"] and memories.twin(WS, "亮度+10", "fact") is None
    assert [m["text"] for m in memories.forget_words(WS, "ตัดคลิปข่าวออก")] == ["ตัดคลิปข่าวออก"]
    assert [m["text"] for m in memories.forget_words(WS, "shoot at ev-1")] == ["Shoot at EV-1"]
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}  # nothing merged: they say different things
    still = [m for m in left if m["id"] not in (kept[0]["id"], kept[15]["id"])] + [apart]
    assert {m["id"] for m in brain.list_(WS)} == {m["id"] for m in still}
    assert all(db.fetch("brain_memories", m["id"])["norm"] == norm(m["text"]) for m in still)


def test_tidy_first_thing_after_a_start_goes_by_the_words_and_not_by_a_form_an_earlier_build_stored(data):
    """Tidy run before any memory was looked up since the start. Memories an earlier build stored with one form for
    different words ("-3 dB" and "+3 dB" were both "3 db") are not twins, so none of them is merged away; two that
    say the same words but were stored with different forms (an accent typed apart made other letters) are, and one
    stands for both. Every stored form is the current one afterwards."""
    from clipfoundry import brain, db
    from clipfoundry.brain import memories

    quiet, loud = brain.remember(WS, "Voice at -3 dB"), brain.remember(WS, "Voice at +3 dB")
    bang = brain.remember(WS, "Never end a caption with !", kind="rule")
    dots = brain.remember(WS, "Never end a caption with …", kind="rule")
    cafe, apart = brain.remember(WS, "Café music in the intro"), brain.remember(WS, "its twin, typed apart")
    db.execute("UPDATE brain_memories SET text = ?, norm = ? WHERE id = ?",
               ("Cafe\u0301 music in the intro", "cafe music in the intro", apart["id"]))
    for row, stored in ((quiet, "voice at 3 db"), (loud, "voice at 3 db"), (bang, "never end a caption with"),
                        (dots, "never end a caption with"), (cafe, "caf music in the intro")):
        db.execute("UPDATE brain_memories SET norm = ? WHERE id = ?", (stored, row["id"]))
    memories._norms_current.clear()  # noqa: SLF001  (a new start of the app: nothing was looked up yet)
    assert brain.tidy(WS) == {"expired": 0, "merged": 1}
    left = db.select("brain_memories", "workspace_id = ?", (WS,))
    assert {m["id"] for m in left} == {quiet["id"], loud["id"], bang["id"], dots["id"], cafe["id"]}
    assert all(m["norm"] == memories._norm(m["text"]) for m in left)  # noqa: SLF001
    assert {m["norm"] for m in left} == {"voice at -3 db", "voice at +3 db", "never end a caption with !",
                                         "never end a caption with …", "café music in the intro"}
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}


def test_memories_that_hold_the_words_named_are_found_by_their_words_in_any_script(data):
    """`holding` finds the memories whose words hold the words named, whole and in that order, whatever the script
    and however short (the search by meaning reads only longer Latin words): what "forget …" offers to pick from.
    In scripts written without spaces between words (Chinese, Japanese, Thai) and in Korean, whose words carry their
    endings, a part of the words is found wherever it stands; a Latin word or a number next to such a character is
    a whole word too. (Until Nov 12 2026 only words set apart by spaces were found.)"""
    from clipfoundry import brain, db
    from clipfoundry.brain import memories

    for text in ("-3 dB here", "The voice sits at -3 dB.", "+3 dB on the music", "3 dB of headroom",
                 "«Привет, друзья» в начале", "Garde la musique basse !"):
        brain.remember(WS, text)

    def held(words: str) -> list[str]:
        return sorted(m["text"] for m in memories.holding(WS, words))

    assert held("-3 dB") == ["-3 dB here", "The voice sits at -3 dB."]  # whole words: not "+3 dB", not "3 dB"
    assert held("3 db") == ["3 dB of headroom"] and held("3") == ["3 dB of headroom"]
    assert held("DB") == ["+3 dB on the music", "-3 dB here", "3 dB of headroom", "The voice sits at -3 dB."]
    assert held("друзья") == held("“Привет, друзья”") == ["«Привет, друзья» в начале"]
    assert held("garde la musique basse") == ["Garde la musique basse !"] and held("sits at") == held("-3 dB.")[1:]
    assert held("dB -3") == held("penguins") == held("  ") == held("") == []
    for text in ("字幕は黄色で", "不要背景音乐", "ไม่ใช้เพลงประกอบ", "자막은 노란색으로", "イントロは5秒", "字幕はYouTube用"):
        brain.remember(WS, text)
    assert held("字幕") == ["字幕はYouTube用", "字幕は黄色で"] and held("黄色") == held("黄色で") == ["字幕は黄色で"]
    assert held("背景音乐") == ["不要背景音乐"] and held("เพลง") == ["ไม่ใช้เพลงประกอบ"]
    assert held("자막") == held("노란색") == held("자막은 노란색") == ["자막은 노란색으로"]  # a word without its ending
    assert held("5秒") == held("5") == ["イントロは5秒"] and held("youtube") == ["字幕はYouTube用"]
    assert held("Tube") == held("You") == held("黄色は") == held("音乐背景") == []  # whole Latin words, and in order
    assert held("3") == ["3 dB of headroom"] and held("d") == []  # a letter inside a Latin word is still no word
    assert [m["text"] for m in memories.holding(WS, "dB", 2)] == ["3 dB of headroom", "+3 dB on the music"]  # newest
    db.execute("UPDATE brain_memories SET norm = '3 db here' WHERE text = '-3 dB here'")  # an earlier build's form
    memories._norms_current.clear()  # noqa: SLF001  (a new start of the app)
    assert held("-3 dB") == ["-3 dB here", "The voice sits at -3 dB."]


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

        def twin(ws, text, kind, scope=None):
            found = real(ws, text, kind, scope)
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
    from clipfoundry import brain
    from clipfoundry.brain import memories

    guess = brain.remember(WS, "You seem to like drone shots", source="guessed")
    other = brain.remember(WS, "Fade the music out at the end")
    real, forgotten = memories.get, set()

    def get(ws, memory_id):
        row = real(ws, memory_id)
        if memory_id in (guess["id"], other["id"]) and memory_id not in forgotten:
            forgotten.add(memory_id)
            brain.forget(WS, memory_id)  # read, then forgotten before the change is written
        return row

    monkeypatch.setattr(memories, "get", get)
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


def test_the_same_words_kept_for_two_videos_are_two_memories_everywhere(data):
    """Where a memory is kept is part of what it is, so the same words kept for two videos are two memories: what
    happened in one video is not taken from the other (an episode with the same words used to move to the video
    that wrote it last), a brain file brings both back, a memory may be edited to say what another video's memory
    says, and the brain check does not call them twins. The same words in one place, or beside a memory for every
    video, are still one memory or a twin."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    first = brain.episode(WS, "Asked \"remove the silences\" → proposed 3 cuts", project_id="p1")
    second = brain.episode(WS, "Asked \"remove the silences\" → proposed 3 cuts", project_id="p2")
    assert first["id"] != second["id"] and brain.get(WS, first["id"])["project_id"] == "p1"
    assert brain.episode(WS, "Asked \"remove the silences\" → proposed 3 cuts", project_id="p2")["id"] == second["id"]
    one = brain.remember(WS, "No captions here", kind="rule", project_id="p1")
    two = brain.remember(WS, "No captions here", kind="rule", project_id="p2")
    tik = brain.remember(WS, "No captions here", kind="rule", platform="tiktok")
    assert len({one["id"], two["id"], tik["id"]}) == 3
    assert [m["id"] for m in brain.recall("captions", WS, project_id="p1").memories] == [one["id"]]
    assert [m["id"] for m in brain.recall("captions", WS, project_id="p2").memories] == [two["id"]]
    assert brain.tidy(WS) == {"expired": 0, "merged": 0}
    assert [p for p in brain.check(WS)["problems"] if p["code"] == "duplicates"] == []  # each is its place's own
    # "forget" asked in a video's chat is about what applies there: that video's own and the one for a platform (it
    # is for more than one video), never another video's own; in the general chat, about all of them
    for asked_in, about in (("p1", [one, tik]), ("p2", [two, tik]), ("p9", [tik]), ("", [one, two, tik])):
        assert [m["id"] for m in memories.to_forget(WS, "no captions here", asked_in)] == [m["id"] for m in about]
    # a brain file brings each of them back (the second used to be skipped: "a memory says those words already")
    file = brain.export(WS)
    assert brain.import_("studio", file) == {"added": 5, "updated": 0, "skipped": 0, "invalid": 0}
    assert sorted(m["scope"] for m in brain.list_("studio", kind="rule")) == ["platform:tiktok", "project:p1",
                                                                             "project:p2"]
    assert brain.import_("studio", file) == {"added": 0, "updated": 0, "skipped": 5, "invalid": 0}  # nothing twice
    # an edit may say what another video's memory says; not what one in the same place or for every video says
    other = brain.remember(WS, "Keep the cuts slow", kind="rule", project_id="p3")
    assert brain.edit(WS, other["id"], text="no captions here!")["text"] == "no captions here!"  # as p1's and p2's
    with pytest.raises(brain.Invalid):
        brain.edit(WS, other["id"], scope="project:p1", text="no captions here")  # one in that place says it
    everywhere = brain.remember(WS, "Fade the music out at the end", kind="rule")
    with pytest.raises(brain.Invalid):
        brain.edit(WS, everywhere["id"], text="No captions here")  # for every video: the videos' own say it
    late = brain.remember(WS, "Captions in white", kind="rule", project_id="p4")
    with pytest.raises(brain.Invalid):
        brain.edit(WS, late["id"], text="fade the music out at the end")  # the one for every video says it


def test_a_brain_file_adds_a_memory_for_every_video_beside_one_kept_for_one_video(data):
    """A brain file's memory for every video is added when the only memory that says its words here is kept for one
    video or one platform: skipped (as it was), the rule from the other computer would hold in that one video only.
    One kept in the same place or for every video says it already, so then the file's is skipped. A file never
    changes or widens a memory with another id."""
    from clipfoundry import brain

    mine = brain.remember(WS, "Never use red captions", kind="rule", project_id="p1")
    tik = brain.remember(WS, "Vertical only", kind="rule", platform="tiktok")
    file = {"format": brain.FORMAT, "memories": [
        {"id": "other-computer-1", "kind": "rule", "text": "never use red captions", "scope": "all", "source": "said"},
        {"id": "other-computer-2", "kind": "rule", "text": "vertical only", "scope": "all", "source": "said"},
        {"id": "other-computer-3", "kind": "rule", "text": "Never use red captions!", "scope": "project:p1"},
        {"id": "other-computer-4", "kind": "rule", "text": "vertical only", "scope": "platform:tiktok"},
        {"id": "other-computer-5", "kind": "rule", "text": "never use red captions", "scope": "project:p2"}]}
    # the two for every video are added; p1's and TikTok's are said already in their own place; p2's is added too:
    # the file's own memory for every video says nothing about what this brain kept before the file
    assert brain.import_(WS, file) == {"added": 3, "updated": 0, "skipped": 2, "invalid": 0}
    assert sorted((m["text"], m["scope"]) for m in brain.list_(WS, kind="rule")) == [
        ("Never use red captions", "project:p1"), ("Vertical only", "platform:tiktok"),
        ("never use red captions", "all"), ("never use red captions", "project:p2"), ("vertical only", "all")]
    assert [(brain.get(WS, m["id"])["scope"], brain.get(WS, m["id"])["revision"]) for m in (mine, tik)] == [
        ("project:p1", 1), ("platform:tiktok", 1)]  # as they were
    elsewhere = [m["id"] for m in brain.recall("red captions", WS, project_id="p2").memories]
    assert "other-computer-1" in elsewhere and mine["id"] not in elsewhere  # the rule holds in another video now
    assert brain.import_(WS, file) == {"added": 0, "updated": 0, "skipped": 5, "invalid": 0}  # nothing twice
    # one for every video beside one video's (or one platform's) own: the brain check calls them twins to review,
    # as the one for every video says it all; Tidy leaves them, since they apply in different places
    assert sorted(sorted(pair) for pair in brain.check(WS)["duplicates"]) == sorted(
        [sorted(["other-computer-1", mine["id"]]), sorted(["other-computer-1", "other-computer-5"]),
         sorted(["other-computer-2", tik["id"]])])
    assert brain.tidy(WS) == {"expired": 0, "merged": 0} and len(brain.list_(WS, kind="rule")) == 5


def test_a_brain_file_brings_back_what_is_not_in_force_here_yet_in_either_order(data):
    """What a brain file adds is weighed against the brain as it was before the file. A memory of the file is known
    already only when a memory in that very place says its words (what the owner did with that one stands), or one
    that is in force for every video (switched on, not a guess, not expired): adding it would change nothing. So a
    backup comes back whole, in either order of the file: the same words kept for every video (switched off, only a
    guess, or in force) and for one video are both restored. Skipped behind the one for every video (as it was), a
    rule that held in one video held nowhere after the restore, and nothing said which memory was left out."""
    from clipfoundry import brain

    def entry(mid: str, scope: str, **more) -> dict:
        return {"id": mid, "kind": "rule", "text": "Never use red captions", "scope": scope, "source": "said", **more}

    def held() -> list[tuple]:
        return sorted((m["id"], m["scope"], bool(m["enabled"]), m["source"]) for m in brain.list_(WS, kind="rule"))

    def in_force(project_id: str) -> list[str]:
        return [m["id"] for m in brain.recall("red captions", WS, project_id=project_id).memories]

    def empty() -> None:
        for m in brain.list_(WS):
            brain.forget(WS, m["id"])

    note = entry("p1-1", "project:p1")
    generals = {"off": entry("all-1", "all", enabled=0),
                "guess": entry("all-1", "all", source="guessed", expires_at=time.time() + 3600),
                "on": entry("all-1", "all")}
    for state, general in generals.items():
        for memories in ([general, note], [note, general]):  # export writes the oldest first: either can be it
            file = {"format": brain.FORMAT, "memories": memories}
            assert brain.import_(WS, file) == {"added": 2, "updated": 0, "skipped": 0, "invalid": 0}, state
            assert held() == [("all-1", "all", state != "off", "guessed" if state == "guess" else "said"),
                              ("p1-1", "project:p1", True, "said")], state
            if state == "off":  # the rule holds in the one video, as on the computer the file came from
                assert in_force("p1") == ["p1-1"] and in_force("p2") == []
            assert brain.import_(WS, file) == {"added": 0, "updated": 0, "skipped": 2, "invalid": 0}  # nothing twice
            empty()
    one = {"format": brain.FORMAT, "memories": [note]}
    # beside a memory of this computer for every video that is not in force, the video's note is added
    from clipfoundry import db

    for state in ("off", "guess", "expired"):
        mine = brain.remember(WS, "never use red captions", kind="rule",
                              source="guessed" if state == "guess" else "said")
        if state == "off":
            brain.edit(WS, mine["id"], enabled=False)
        if state == "expired":  # said, switched on, but its time is over (a hand-made file can bring one)
            db.update("brain_memories", mine["id"], expires_at=time.time() - 60)
        assert brain.import_(WS, one) == {"added": 1, "updated": 0, "skipped": 0, "invalid": 0}, state
        assert in_force("p1") == (["p1-1"] if state != "guess" else in_force("p1")) and "p1-1" in [m[0] for m in held()]
        assert brain.get(WS, mine["id"])["revision"] == (2 if state == "off" else 1)  # as the owner left it
        empty()
    # one in force for every video says it already; so does one in the same place, switched off or not
    mine = brain.remember(WS, "never use red captions", kind="rule")
    assert brain.import_(WS, one) == {"added": 0, "updated": 0, "skipped": 1, "invalid": 0}
    assert [m[0] for m in held()] == [mine["id"]]
    empty()
    mine = brain.remember(WS, "never use red captions", kind="rule", project_id="p1")
    brain.edit(WS, mine["id"], enabled=False)
    assert brain.import_(WS, one) == {"added": 0, "updated": 0, "skipped": 1, "invalid": 0}
    assert held() == [(mine["id"], "project:p1", False, "said")] and in_force("p1") == []  # the owner's switch stands


def test_a_brain_file_changes_the_memories_it_knows_before_it_adds_the_rest(data):
    """A brain file's newer revisions of memories this brain has are applied first, and what the file adds is weighed
    against the brain as they leave it. Read in the file's own order (the oldest first), one video's note was skipped
    because this brain's rule for every video still said its words, and then a later entry of the same file reworded
    that rule or switched it off: the note was nowhere, and importing the same file a second time added it."""
    from clipfoundry import brain

    def sync(change: dict) -> tuple[dict, dict]:
        for m in brain.list_(WS):
            brain.forget(WS, m["id"])
        mine = brain.remember(WS, "Never use red captions", kind="rule")
        theirs = next(m for m in brain.export(WS)["memories"] if m["id"] == mine["id"])
        note = {"id": "p1-1", "kind": "rule", "text": "Never use red captions", "scope": "project:p1",
                "source": "said", "created_at": theirs["created_at"] - 60}  # the older of the two: it comes first
        return mine, {"format": brain.FORMAT, "memories": [note, {**theirs, **change, "revision": 2}]}

    mine, reworded = sync({"text": "Never use red captions on shorts"})
    assert brain.import_(WS, reworded) == {"added": 1, "updated": 1, "skipped": 0, "invalid": 0}
    assert sorted((m["id"], m["text"], m["scope"]) for m in brain.list_(WS, kind="rule")) == sorted([
        ("p1-1", "Never use red captions", "project:p1"), (mine["id"], "Never use red captions on shorts", "all")])
    assert brain.import_(WS, reworded) == {"added": 0, "updated": 0, "skipped": 2, "invalid": 0}  # nothing twice
    mine, off = sync({"enabled": 0})
    assert brain.import_(WS, off) == {"added": 1, "updated": 1, "skipped": 0, "invalid": 0}
    assert sorted((m["id"], m["scope"], bool(m["enabled"])) for m in brain.list_(WS, kind="rule")) == sorted([
        ("p1-1", "project:p1", True), (mine["id"], "all", False)])
    assert [m["id"] for m in brain.recall("red captions", WS, project_id="p1").memories] == ["p1-1"]
    assert brain.recall("red captions", WS, project_id="p2").memories == []
    assert brain.import_(WS, off) == {"added": 0, "updated": 0, "skipped": 2, "invalid": 0}


def test_a_brain_file_entry_with_a_value_that_is_no_number_is_left_out_and_the_rest_is_read(client):
    """A hand-made or converted brain file can hold text where a number belongs (a date for "last_used_at", "high"
    for "confidence"). Such an entry is counted as invalid and the rest of the file is read. Stored as it was, a
    date in "last_used_at" made every later search, recall and answer fail until that memory was forgotten, and the
    other fields gave a server error with the file half imported."""
    from clipfoundry import brain

    def file(**bad) -> dict:
        return {"format": brain.FORMAT, "memories": [
            {"id": "m-1", "kind": "rule", "text": "captions in yellow"},
            {"id": "m-2", "kind": "rule", "text": "music under the voice", **bad},
            {"id": "m-3", "kind": "fact", "text": "the channel is about hiking"}]}

    for field, value in (("last_used_at", "2026-11-01T10:00:00"), ("confidence", "high"), ("revision", "two"),
                         ("expires_at", "never"), ("created_at", "2026-11-01"), ("used_count", "many"),
                         ("revision", float("inf")), ("created_at", float("nan")), ("used_count", [3]),
                         ("last_used_at", {"at": 1}), ("revision", 10 ** 400)):
        body = json.dumps({"data": file(**{field: value})})  # as a file holds it: Infinity and NaN are in there
        r = client.post("/api/brain/memories/import", content=body, headers={**H, "Content-Type": "application/json"})
        assert r.status_code == 200 and r.json() == {"added": 2, "updated": 0, "skipped": 0, "invalid": 1}, (
            field, r.text)
        assert sorted(m["id"] for m in brain.list_(WS)) == ["m-1", "m-3"], field
        assert client.get("/api/brain/memories?q=captions").status_code == 200, field
        r = client.post("/api/brain/memories/recall", json={"query": "captions"})
        assert r.status_code == 200 and [m["id"] for m in r.json()["memories"]] == ["m-1"], field
        for m in brain.list_(WS):
            brain.forget(WS, m["id"])
    # numbers written as numbers or as text that is a number are read as before, and a count stays in bounds
    good = file(last_used_at="1762000000", confidence="0.4", revision=3.0, used_count=10 ** 30, created_at=1762000000,
                expires_at=None)
    assert client.post("/api/brain/memories/import", json={"data": good}, headers=H).json() == {
        "added": 3, "updated": 0, "skipped": 0, "invalid": 0}
    kept = brain.get(WS, "m-2")
    assert (kept["last_used_at"], kept["confidence"], kept["revision"], kept["created_at"]) == (
        1762000000.0, 0.4, 3, 1762000000.0) and kept["used_count"] == 10 ** 9 and kept["expires_at"] is None
    big = {"format": brain.FORMAT, "memories": [
        {"id": "m-2", "kind": "rule", "text": "music under the voice", "revision": 10 ** 30},
        {"id": "m-8", "kind": "fact", "text": "the mic is a lavalier", "revision": 10 ** 30, "used_count": -4}]}
    assert client.post("/api/brain/memories/import", json={"data": big}, headers=H).json() == {
        "added": 1, "updated": 1, "skipped": 0, "invalid": 0}
    assert brain.get(WS, "m-2")["revision"] == 10 ** 9 and brain.get(WS, "m-2")["used_count"] == 10 ** 9
    assert brain.get(WS, "m-8")["revision"] == 10 ** 9 and brain.get(WS, "m-8")["used_count"] == 0
    assert client.get("/api/brain/memories?q=music").status_code == 200


def test_a_brain_file_nested_deeper_than_anything_real_is_refused_before_anything_is_stored(client):
    """A memory's extra data nested a few hundred levels deep could be read and stored, but not sent back: from then
    on the Memory page, the search and recall answered with a server error, until that memory was removed by hand.
    A request nested deeper than anything ClipForge writes (`routes.MAX_DEPTH`) is refused in plain words before
    anything is stored; a real file's few levels are read as before."""
    from clipfoundry import brain
    from clipfoundry.brain import routes

    def nested(levels: int, as_list: bool = False) -> object:
        out: object = "leaf"
        for _ in range(levels):
            out = [out] if as_list else {"a": out}
        return out

    def file(extra: object) -> dict:
        return {"format": brain.FORMAT, "memories": [
            {"id": "m-1", "kind": "rule", "text": "captions in yellow"},
            {"id": "m-2", "kind": "asset", "text": "the summit photo", "data": {"extra": extra}}]}

    for levels in (300, 254, routes.MAX_DEPTH - 4):
        for as_list in (False, True):
            r = client.post("/api/brain/memories/import", json={"data": file(nested(levels, as_list))}, headers=H)
            assert (r.status_code, r.json()["detail"]) == (422, "That is nested too deeply to read."), levels
            assert brain.list_(WS) == [] and client.get("/api/brain/memories").status_code == 200
    # the request itself is five levels around the extra data: what fits is read, kept and sent back whole
    fits = nested(routes.MAX_DEPTH - 5)
    r = client.post("/api/brain/memories/import", json={"data": file(fits)}, headers=H)
    assert r.status_code == 200 and r.json() == {"added": 2, "updated": 0, "skipped": 0, "invalid": 0}
    assert brain.get(WS, "m-2")["data"] == {"extra": fits}
    assert client.get("/api/brain/memories").status_code == 200
    assert client.get("/api/brain/memories?q=summit").status_code == 200
    r = client.post("/api/brain/memories/recall", json={"query": "summit photo"})
    assert r.status_code == 200 and [m["id"] for m in r.json()["memories"]] == ["m-1", "m-2"]  # the rule first
    back = client.get("/api/brain/memories/export").json()
    assert [m["data"] for m in back["memories"] if m["id"] == "m-2"] == [{"extra": fits}]


def test_the_closest_memory_in_a_videos_chat_applies_there_unless_another_videos_note_names_more(data, monkeypatch):
    """`closest` is the search's best match. Asked in a video's chat, a match that applies there comes before another
    video's own note when it holds a word named and at least as much of the words named as that note, or fits
    exactly as well; otherwise the best match stands, also when it is another video's note. The scores are set by
    hand here, so the rule is checked by itself: (score, share of the words named, closeness of meaning)."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    every = brain.remember(WS, "always add captions", kind="rule")
    mine = brain.remember(WS, "no captions in the intro", kind="rule", project_id="hike")
    theirs = brain.remember(WS, "no captions in the outro", kind="rule", project_id="beach")
    tiktok = brain.remember(WS, "captions sit higher", kind="rule", platform="tiktok")
    unrelated = brain.remember(WS, "the channel is about hiking")
    real = memories._scores

    def closest(project_id: str, **scores: tuple[float, float, float]) -> str:
        by_id = {m["id"]: scores.get(name, (0.0, 0.0, 0.0)) for name, m in (
            ("every", every), ("mine", mine), ("theirs", theirs), ("tiktok", tiktok), ("unrelated", unrelated))}
        monkeypatch.setattr(memories, "_scores", lambda q, rows, project_id="": [by_id[r["id"]] for r in rows])
        found = memories.closest(WS, "the caption rule", project_id)
        return next(name for name, m in (("every", every), ("mine", mine), ("theirs", theirs), ("tiktok", tiktok),
                                         ("unrelated", unrelated)) if found and m["id"] == found["id"])

    # as many of the words named: the one that applies here, however much closer the other video's note is otherwise
    assert closest("hike", theirs=(0.9, 0.2, 0.9), mine=(0.4, 0.2, 0.1)) == "mine"
    assert closest("hike", theirs=(0.9, 0.2, 0.9), every=(0.4, 0.3, 0.1)) == "every"
    assert closest("hike", theirs=(0.9, 0.2, 0.9), tiktok=(0.4, 0.2, 0.1)) == "tiktok"  # a platform's is not a video's
    assert closest("hike", theirs=(0.9, 0.2, 0.9), every=(0.3, 0.2, 0.1), mine=(0.4, 0.2, 0.1)) == "mine"  # the best
    # fewer of the words named: the other video's note is the one the owner named
    assert closest("hike", theirs=(0.9, 0.3, 0.9), mine=(0.8, 0.2, 0.9)) == "theirs"
    assert closest("hike", theirs=(0.9, 0.3, 0.9), every=(0.8, 0.2, 0.9), mine=(0.4, 0.3, 0.0)) == "mine"
    # no word named in either: only an exact tie goes to the one that applies here, never a weaker match
    assert closest("hike", theirs=(0.6, 0.0, 0.9), unrelated=(0.3, 0.0, 0.3)) == "theirs"
    assert closest("hike", theirs=(0.6, 0.0, 0.9), unrelated=(0.3, 0.2, 0.0)) == "unrelated"  # it names a word
    assert closest("hike", theirs=(0.6, 0.0, 0.9), mine=(0.6, 0.0, 0.9)) == "mine"
    assert closest("hike", theirs=(0.60004, 0.0, 0.9), mine=(0.59996, 0.0, 0.9)) == "mine"  # the same to four places
    # the best match applies here, or nothing that applies here matches, or the chat has no video: the best match
    assert closest("hike", mine=(0.9, 0.1, 0.9), every=(0.5, 0.3, 0.9), theirs=(0.6, 0.3, 0.9)) == "mine"
    assert closest("city", theirs=(0.5, 0.2, 0.5), mine=(0.4, 0.2, 0.5)) == "theirs"
    assert closest("", theirs=(0.5, 0.2, 0.5), mine=(0.4, 0.2, 0.5), every=(0.3, 0.2, 0.5)) == "theirs"
    assert closest("beach", theirs=(0.5, 0.2, 0.5), mine=(0.9, 0.2, 0.5), every=(0.3, 0.2, 0.5)) == "theirs"
    # nothing matches (no word, and not close enough in meaning), or nothing is asked: None
    monkeypatch.setattr(memories, "_scores", lambda q, rows, project_id="": [(0.2, 0.0, 0.0) for _ in rows])
    assert memories.closest(WS, "the caption rule", "hike") is None
    monkeypatch.setattr(memories, "_scores", lambda q, rows, project_id="": [(0.9, 0.0, 0.9) for _ in rows])
    assert memories.closest(WS, "  ", "hike") is None  # whatever a meaning model makes of no words at all
    monkeypatch.setattr(memories, "_scores", real)
    assert memories.closest(WS, "the intro", "hike")["id"] == mine["id"]


def test_a_memory_an_older_build_moved_is_listed_for_the_video_it_is_kept_for(data):
    """The builds released before this one moved a memory to the video that said its words last and left its
    project_id naming the first video. The scope says whom a memory is for (recall and a video's delete go by it),
    so the list for a video goes by it too: the moved memory is listed for the video it is kept for, not for the one
    it left."""
    from clipfoundry import brain, db

    moved = brain.remember(WS, "No captions on the intro", kind="rule", project_id="p2")
    db.update("brain_memories", moved["id"], project_id="p1")  # as an older build left a memory it had moved
    everywhere = brain.remember(WS, "Captions in yellow", kind="rule")
    assert [m["id"] for m in brain.list_(WS, project_id="p2")] == [everywhere["id"], moved["id"]]  # newest first
    assert [m["id"] for m in brain.list_(WS, project_id="p1")] == [everywhere["id"]]
    assert [m["id"] for m in brain.list_(WS, q="captions", project_id="p1")] == [everywhere["id"]]
    assert {m["id"] for m in brain.list_(WS, q="captions", project_id="p2")} == {everywhere["id"], moved["id"]}
    assert [m["id"] for m in brain.recall("captions", WS, project_id="p1").memories] == [everywhere["id"]]
    # a video's own memories come a little first in its searches: that goes by the scope too
    score = {pid: next(m["score"] for m in brain.list_(WS, q="captions", project_id=pid) if m["id"] == moved["id"])
             for pid in ("p2", "")}
    assert round(score["p2"] - score[""], 4) == 0.1


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


def test_a_brain_files_newer_revision_is_applied_beside_a_twin_and_a_memory_gone_meanwhile_gets_its_newer_words(
        data, monkeypatch):
    """A brain file's newer revision of a memory is applied, also when another memory says those words: switched off
    or retagged on the other computer, or given the words of a rule this computer has already. Skipping it kept the
    replaced words in force beside the new ones and counted the change as already known. The twins it leaves are read
    once, and Tidy merges those kept for the same videos and switched on or off alike. When the memory is forgotten or
    tidied away between ClipForge reading it and writing it, it is read again, and the file's newer words are added
    (not counted as updated and then found nowhere)."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    here = brain.remember(WS, "Captions in yellow", kind="rule", project_id="p1")
    _did_twin("captions in yellow", kind="rule")  # the same words for every video
    mine = next(m for m in brain.export(WS)["memories"] if m["id"] == here["id"])
    off = {"format": brain.FORMAT, "memories": [{**mine, "enabled": 0, "tags": ["look"], "revision": 2}]}
    assert brain.import_(WS, off) == {"added": 0, "updated": 1, "skipped": 0, "invalid": 0}
    row = brain.get(WS, here["id"])
    assert row["enabled"] == 0 and row["tags"] == ["look"] and row["revision"] == 2
    intro = brain.remember(WS, "Keep the intro under five seconds", kind="rule")
    brain.remember(WS, "keep the intro under three seconds", kind="rule")
    theirs = next(m for m in brain.export(WS)["memories"] if m["id"] == intro["id"])
    shorter = {"format": brain.FORMAT, "memories": [{**theirs, "text": "Keep the intro under three seconds",
                                                     "revision": 2}]}
    assert brain.import_(WS, shorter) == {"added": 0, "updated": 1, "skipped": 0, "invalid": 0}
    said = [m["text"].lower() for m in brain.recall("how long should the intro be", WS).memories]
    assert [t for t in said if "intro" in t] == ["keep the intro under three seconds"]
    assert brain.tidy(WS)["merged"] == 1
    assert [m["text"].lower() for m in brain.list_(WS) if "intro" in m["text"].lower()] == [
        "keep the intro under three seconds"]
    opening = brain.remember(WS, "Open with the best shot", kind="rule", project_id="p2")
    first = next(m for m in brain.export(WS)["memories"] if m["id"] == opening["id"])
    real = memories._write_over  # noqa: SLF001

    def write_over(old, fields):  # forgotten just before the file's words are written
        brain.forget(WS, old["id"])
        monkeypatch.setattr(memories, "_write_over", real)
        return real(old, fields)

    monkeypatch.setattr(memories, "_write_over", write_over)
    newer = {"format": brain.FORMAT, "memories": [{**first, "text": "Open with the loudest shot", "revision": 5}]}
    assert brain.import_(WS, newer) == {"added": 1, "updated": 0, "skipped": 0, "invalid": 0}
    row = brain.get(WS, opening["id"])
    assert row["text"] == "Open with the loudest shot" and row["scope"] == "project:p2" and row["revision"] == 5


@pytest.mark.parametrize("act", ["edit", "confirm"])
def test_an_edit_or_a_confirmation_writes_only_over_the_memory_as_it_read_it(data, monkeypatch, act):
    """Like `remember`, an edit or a confirmation writes only over the memory as it read it (`memories._write_over`).
    When an answer says the same words again in between, it reads the memory again and writes the next revision, so
    no two different memories share one: written blindly as its read + 1, another answer that had read the one said
    in between wrote over the edit (its old words back, beside the edit's stored form and meaning) or undid the
    confirmation."""
    from clipfoundry import brain
    from clipfoundry.brain import memories

    source = "guessed" if act == "confirm" else "said"
    m = brain.remember(WS, "Captions in yellow", source=source)
    real, said = memories.get, []

    def get(ws, memory_id):  # the owner's change has read it; an answer says the same words before it is written
        row = real(ws, memory_id)
        if not said:
            said.append(brain.remember(WS, "captions in yellow", source=source, tags=["look"]))
        return row

    monkeypatch.setattr(memories, "get", get)
    out = brain.edit(WS, m["id"], text="Captions in white") if act == "edit" else brain.confirm(WS, m["id"])
    monkeypatch.setattr(memories, "get", real)
    assert said[0]["revision"] == 2 and out["revision"] == 3
    row = brain.get(WS, m["id"])
    assert row["tags"] == ["look"] and row["revision"] == 3  # what was said in between stays
    if act == "edit":
        assert row["text"] == "Captions in white" and row["norm"] == "captions in white"
    else:
        assert row["source"] == "said" and row["confidence"] == 1.0 and row["expires_at"] is None
    # an answer that read it as it was said in between (revision 2) cannot write over the change now
    assert memories._write_over(said[0], {"text": "captions in yellow", "revision": 3}) is None  # noqa: SLF001
    assert brain.get(WS, m["id"])["revision"] == 3


def test_twins_are_read_once_from_those_that_fit_the_question(data, monkeypatch):
    """Twins kept apart (one for every video, one for this video) are read once: the best of those that fit the
    question. Picked before the relevance floor, the twin with the higher score (for this video, used yesterday, its
    meaning still from the embedder used before, until Rebuild) was kept and then fell under the floor, so the memory
    was not read at all, though its twin fits the question by meaning."""
    import numpy as np

    from clipfoundry import db, embedder
    from clipfoundry.brain import meaning, memories

    rng = np.random.default_rng(1)
    q = rng.normal(size=embedder.DIM).astype(np.float32)
    q /= np.linalg.norm(q)
    u = rng.normal(size=embedder.DIM).astype(np.float32)
    u -= q * float(np.dot(u, q))
    u /= np.linalg.norm(u)
    monkeypatch.setattr(meaning, "model", lambda settings=None: embedder.MODEL)  # the question's meaning is q
    monkeypatch.setattr(meaning, "embed", lambda text, which=None, settings=None:
                        q if (which or embedder.MODEL) == embedder.MODEL else meaning.hash_embed(text))
    now, sim = time.time(), 0.4
    fits = (sim * q + np.sqrt(1 - sim ** 2) * u).astype(np.float32)
    base = {"workspace_id": WS, "kind": "fact", "text": "Captions in yellow", "norm": "captions in yellow",
            "confidence": 1.0, "tags": [], "data": {}, "enabled": 1, "revision": 1, "used_count": 0}
    db.insert("brain_memories", {**base, "id": "every", "source": "did", "scope": "all", "created_at": now - 40 * 86400,
                                 "meaning": meaning.pack(fits), "meaning_model": embedder.MODEL})
    db.insert("brain_memories", {**base, "id": "this", "source": "said", "scope": "project:p1", "project_id": "p1",
                                 "meaning": meaning.pack(meaning.hash_embed("captions in yellow")),
                                 "meaning_model": meaning.HASH_MODEL, "created_at": now - 40 * 86400 + 1,
                                 "last_used_at": now - 86400})
    got = memories.recall("how should subtitles look", WS, project_id="p1").memories
    assert [m["id"] for m in got] == ["every"]
    assert memories.recall("captions in yellow", WS, project_id="p1").ids == ["this"]  # both fit: the best is read


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
