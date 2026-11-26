"""Titles and hashtags that help a clip be found (Landry's research, Nov 26): the video's subject from its name,
hashtags in the order subject -> topic -> community with no generic or repeated tags, titles that name something,
The moment without the ending, where the clip backs a title, the owner's own hashtags, typed text kept on a rewrite,
a trim that cuts out a title's line, and the same rules for Autopilot and live clips."""
from __future__ import annotations

import pytest

from clipfoundry.pipeline import postpack, transcribe
from test_core import SCRIPT, _srt

BOSS = ["Watch this.", "Forty attempts on this boss last night.", "Every attempt she healed off my hits.",
        "Why does nobody talk about the heal?", "The trick is to stop attacking after two hits."]


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def test_the_videos_subject_comes_from_names_in_its_name_not_from_file_name_filler():
    assert postpack.subjects("Elden Ring: I finally beat Malenia", "she hits so hard") == ["Elden Ring", "Malenia"]
    # a name the clip says goes first
    assert postpack.subjects("Elden Ring: I finally beat Malenia", "Malenia hits so hard")[0] == "Malenia"
    # Title Case can't tell a name from an ordinary word: only words the clip also says are taken
    assert postpack.subjects("How I Beat The Hardest Boss Ever", "the boss heals") == ["boss"]
    # a file's name: filler and numbers are left out
    assert postpack.subjects("elden_ring_final_v2.mp4", "this ring is cursed") == ["ring"]
    assert postpack.subjects("IMG_2034.mov", "anything") == []
    assert postpack.subjects_for(["my stream", "Valorant ranked grind"], "") == ["Valorant"]


def test_hashtags_go_owner_subject_topic_without_generic_or_repeated_tags():
    text = " ".join(BOSS) + " The heal is the boss's whole trick. Viral fyp."
    tags = postpack.hashtags_for(text, prefer="Forty attempts on this boss", subject=["Elden Ring"],
                                 owner=["#MyShow", "#myshow"])
    assert tags[:2] == ["#MyShow", "#EldenRing"], tags
    assert len(tags) <= postpack.HASHTAG_LIMIT and len({t.lower() for t in tags}) == len(tags)
    assert not {t.lower() for t in tags} & {"#viral", "#fyp", "#trending", "#foryou"}
    assert "#boss" in tags  # the clip's own topic, the title's subject first
    assert postpack.tag_of("Elden Ring") == "#EldenRing" and postpack.tag_of("valorant") == "#valorant"
    assert postpack.dedupe_tags(["#Aim", "#aim", "#AIM", "#crosshair"]) == ["#Aim", "#crosshair"]


def test_a_package_uses_the_subject_in_a_searchable_title_and_hashtag_and_checks_pass():
    pkg = postpack.generate(BOSS, BOSS[1], [], "Gaming", {}, use_ai=False, name="Elden Ring boss fight")
    assert pkg["subject"] == ["Elden Ring", "boss"]
    assert pkg["hashtags"][0] == "#EldenRing"
    assert any(t.startswith("Elden Ring: ") for t in pkg["titles"]), pkg["titles"]
    assert "search" in [o["kind"] for o in pkg["guide"]["options"]]
    assert pkg["checks"] == {}  # the subject's words count as known; nothing else was added
    assert postpack.grounding_problems("Elden Ring: invented Margit fight", " ".join(BOSS),
                                       postpack.subject_words(pkg["subject"]))  # other names still are not


def test_vague_titles_name_nothing_and_go_last():
    assert postpack.vague("Watch this") and postpack.vague("It was crazy") and postpack.vague("Oh my god")
    assert not postpack.vague("Forty attempts on this boss")
    assert not postpack.vague("Malenia heals off every hit")      # a name
    assert not postpack.vague("Watch the heal", ["heal"])          # a topic word
    pkg = postpack.generate(BOSS, BOSS[0], [], "Gaming", {}, use_ai=False)
    assert "Watch this" not in pkg["titles"][:1] and pkg["title"] != "Watch this", pkg["titles"]


def test_the_moment_carries_a_concrete_detail_before_the_ending():
    title = postpack._make_kind("moment", BOSS, ["attacking"], [])  # noqa: SLF001
    assert title == "Forty attempts on this boss last night", title   # not "The trick is to stop attacking..."


def test_the_guide_says_where_the_clip_backs_the_recommended_title():
    pkg = postpack.generate(BOSS, BOSS[1], [], "Gaming", {}, use_ai=False, starts=[0.0, 1.2, 4.0, 7.5, 10.0])
    rec = pkg["titles"][pkg["recommended_title"]]
    assert rec in pkg["said_at"]
    when = pkg["said_at"][rec]
    assert f"The clip says it at 0:{int(when):02d}." in pkg["guide"]["youtube"]["why"]
    assert "first 4 hashtags" in pkg["guide"]["tiktok"]["note"]


def test_the_owners_hashtags_come_first_and_are_never_flagged():
    from clipfoundry import config

    assert config.validate_settings({"post_always_hashtags": "valorant, #MyShow #valorant"}) == {
        "post_always_hashtags": "#valorant #MyShow"}
    assert config.validate_settings({"post_always_hashtags": "#good #bad-tag"}) == {}
    pkg = postpack.generate(BOSS, BOSS[1], [], "Gaming", {"post_always_hashtags": "#MyShow #valorant"},
                            use_ai=False)
    assert pkg["hashtags"][:2] == ["#MyShow", "#valorant"] and "hashtags" not in pkg["checks"]


def test_a_rewrite_keeps_what_the_owner_typed_but_not_a_picked_suggestion():
    pkg = postpack.generate(BOSS, BOSS[1], [], "Gaming", {}, use_ai=False)
    typed = postpack.apply_edit(pkg, {"title": "My forty tries at this boss", "hashtags": ["#mine"]})
    assert typed["mine"] == ["title", "hashtags"]
    again = postpack.keep_mine(typed, postpack.generate(BOSS, BOSS[1], [], "Gaming", {}, use_ai=False))
    assert again["title"] == "My forty tries at this boss" and again["hashtags"] == ["#mine"]
    assert again["titles"] == pkg["titles"] and "your own text kept" in again["source"]
    picked = postpack.apply_edit(typed, {"title": pkg["titles"][-1]})   # picking a suggestion is not typing
    assert picked["mine"] == ["hashtags"]
    assert postpack.keep_mine({}, pkg) is pkg


def test_a_trim_that_cuts_out_a_titles_line_gets_a_note_and_the_text_stays():
    words = [{"w": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(
        "Malenia healed off every hit. I stopped attacking after two hits.".split())]
    clip = {"start": 0.0, "end": 6.0, "edit": {}, "caption_text": ""}
    pkg = postpack.generate(postpack.clip_sentences(words, clip), "", [], "Gaming", {}, use_ai=False)
    pkg = postpack.apply_edit(pkg, {"title": "Malenia healed off every hit"})
    assert "title" not in pkg["checks"]
    trimmed = postpack.recheck(pkg, words, {**clip, "edit": {"start": 2.4}})
    assert trimmed["title"] == "Malenia healed off every hit" and trimmed["checks"].get("title")
    assert trimmed["clip_text"] == "I stopped attacking after two hits."


def test_trimming_a_clip_through_the_api_checks_its_post_text_again(data):
    from fastapi.testclient import TestClient

    from clipfoundry import api, db
    from clipfoundry.pipeline.common import write_json

    folder = data / "p"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"x")
    project = db.create_project("talk", source_path=str(folder / "source.mp4"), status="ready")
    from clipfoundry.pipeline.process import project_dir

    write_json(project_dir(project) / "transcript.json", {"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    first_end = next(w["end"] for w in words if w["w"].endswith("."))
    clip = db.create_clip(project["id"], start=0.0, end=words[-1]["end"], title="t", status="ready",
                          post=postpack.apply_edit(postpack.generate(SCRIPT, SCRIPT[0], [], "", {}, use_ai=False),
                                                   {"title": SCRIPT[0].rstrip(".")}))
    client = TestClient(api.app)
    out = client.patch(f"/api/clips/{clip['id']}", json={"edit": {"start": first_end + 0.05}}).json()
    assert out["post"]["title"] == SCRIPT[0].rstrip(".") and out["post"]["checks"].get("title")


def test_the_model_reads_the_research_and_the_subject(monkeypatch):
    from clipfoundry.autopilot import packaging
    from clipfoundry.pipeline import llm

    seen = []
    monkeypatch.setattr(llm, "complete", lambda settings, prompt, **kw: seen.append(prompt) or "{}")
    postpack.generate(BOSS, BOSS[1], [], "Gaming", {"ai_provider": "ollama"}, name="Elden Ring boss fight")
    assert "one clear promise" in seen[0] and "The whole video is about: Elden Ring" in seen[0]
    assert "#fyp" in seen[0] and "CamelCase" in seen[0]
    prompt = packaging._ai_prompt("youtube", BOSS, [], "", ["Elden Ring"])  # noqa: SLF001
    assert "one clear promise" in prompt and "Elden Ring" in prompt
    from clipfoundry.brain import knowhow

    assert knowhow.principles("post")[:40] in prompt


def test_autopilot_posts_get_the_subject_tag_four_tiktok_tags_and_pass_the_final_check(data, monkeypatch):
    from clipfoundry import db
    from clipfoundry.autopilot import gate, packaging
    from clipfoundry.brain import learned
    from clipfoundry.pipeline.common import write_json

    folder = data / "p"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"x")
    project = db.create_project("my talk at Startup School", source_path=str(folder / "source.mp4"), status="ready",
                                origin="autopilot")
    from clipfoundry.pipeline.process import project_dir

    write_json(project_dir(project) / "transcript.json", {"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    end = next(w["end"] for w in words if w["w"] == "build.")
    clip = db.create_clip(project["id"], start=0.3, end=end, title="t", hook=SCRIPT[0], status="ready",
                          caption_text=" ".join(SCRIPT[:7]), hashtags=["#business"], post={})
    settings = {"autopilot_youtube": True, "autopilot_tiktok": True, "post_always_hashtags": "#MyShow"}
    db.save_settings(settings)
    yt = packaging.package(clip, None, "youtube", db.get_settings())
    tt = packaging.package(clip, None, "tiktok", db.get_settings())
    assert yt["hashtags"][:2] == ["#MyShow", "#StartupSchool"], yt["hashtags"]
    assert "StartupSchool" in yt["tags"] and not yt["problems"]
    assert len(tt["hashtags"]) <= 4 and tt["caption"].count("#") <= 4 and not tt["problems"]
    report = gate.check_metadata(clip, "", db.get_settings())
    assert report["youtube"]["status"] == "passed", report
    # the kind of title you usually pick gets its bonus
    rows = {r["title"]: r["score"] for r in db.select("metadata_candidates", "clip_id = ? AND platform = 'youtube'",
                                                       (clip["id"],))}
    kws = postpack.topics(" ".join(packaging.clip_sentences(clip)[0]))
    want = next(postpack.title_kind(t, kws) for t, sc in rows.items() if sc)
    monkeypatch.setattr(learned, "defaults", lambda ws, s=None: {"title_kind": want})
    packaging.package(clip, None, "youtube", db.get_settings())
    after = {r["title"]: r["score"] for r in db.select("metadata_candidates",
                                                        "clip_id = ? AND platform = 'youtube'", (clip["id"],))}
    bumped = [t for t, sc in rows.items() if sc and postpack.title_kind(t, ["startup"] + kws) == want and sc < 90]
    assert bumped and all(after[t] == pytest.approx(rows[t] + packaging.LEARNED_KIND_BONUS) for t in bumped)


def test_extracted_autopilot_titles_stand_alone():
    from clipfoundry.autopilot import packaging

    sents = ["That's the setting.", "Turn off mouse acceleration before you play ranked.", "It does not help."]
    cands = packaging.extracted_candidates("youtube", sents, {"hook": ""}, "", ["mouse", "acceleration"], [])
    assert cands and all(postpack.stands_alone(c["title"]) for c in cands), [c["title"] for c in cands]


def test_live_clips_start_with_your_captions_and_pacing_but_keep_their_framing():
    from clipfoundry.autopilot import live

    taught = {"caption_style": "bold", "silence": "light", "layout": "fit", "crop_x": 0.3, "start_shift": 1.0,
              "title_kind": "curiosity"}
    look = live._learned_look(taught)  # noqa: SLF001
    assert look == {"caption_style": "bold", "silence": "light", "learned_keys": ["caption_style", "silence"]}
    assert live._learned_look({}) == {}  # noqa: SLF001


def _words(text: str, step: float = 0.4) -> list[dict]:
    return [{"w": w, "start": round(i * step, 2), "end": round(i * step + step - 0.05, 2)}
            for i, w in enumerate(text.split())]


TALK = ("So, um, okay. The boss heals off every hit you land on her. Stop attacking after two hits and wait. "
        "Then she drops her guard and you get a free window. That one change took me from forty tries to one. "
        "Thanks for watching and subscribe for more.")


def test_new_clips_start_on_the_first_real_word_and_stop_before_the_outro():
    from types import SimpleNamespace

    from clipfoundry.pipeline import process

    words = _words(TALK)
    p = SimpleNamespace(opts={"min_duration": 5}, words=words)
    edit = process.auto_trim(p, 0.0, words[-1]["end"], {})
    sides = {t["side"]: t for t in edit["auto_trims"]}
    assert set(sides) == {"start", "end"}, edit
    first_real = next(w for w in words if w["w"] == "The")
    assert edit["start"] == sides["start"]["to"] and abs(edit["start"] - first_real["start"]) < 0.5
    assert sides["start"]["was"] == 0.0 and edit["end"] < next(w for w in words if w["w"] == "Thanks")["start"] + 0.5
    # off in Settings, or a clip that would get too short: nothing moves
    assert process.auto_trim(SimpleNamespace(opts={"auto_trims": False}, words=words), 0.0, 40.0, {}) == {}
    assert process.auto_trim(SimpleNamespace(opts={"min_duration": 60}, words=words), 0.0, words[-1]["end"],
                             {}) == {}


def test_a_trim_made_for_you_is_not_learned_as_your_habit(data):
    from clipfoundry import db
    from clipfoundry.brain import learned

    project = db.create_project("p", status="ready")
    edit = {"start": 1.2, "auto_trims": [{"id": "lead_in", "label": "x", "why": "", "side": "start", "was": 0.0,
                                          "to": 1.2}]}
    before = db.create_clip(project["id"], start=0.0, end=30.0, title="t", status="ready", edit=edit)
    after = {**before, "edit": {**edit, "end": 28.0}}   # you only moved the end
    events = learned.observe(before, after, {"learn_from_edits": True})
    trim = [e for e in events if e["kind"] == "trim"]
    assert trim and trim[0]["data"] == {"start_shift": 0.0, "end_shift": -2.0}   # the start it moved is not yours
