"""Post packages: grounded titles, captions, hashtags, description, CTA and hook; editing; AI checks; API; export."""
from __future__ import annotations

import json
import zipfile

import pytest

from clipfoundry import config
from clipfoundry.pipeline import candidates, llm, postpack, scoring, transcribe
from clipfoundry.pipeline.common import JobContext, write_json
from test_core import SCRIPT, _srt
from test_virality import PODCAST, _setup


def _packages(lines: list[str]) -> list[tuple[str, dict]]:
    words, sentences, loud, _ = _setup(lines)
    opts = dict(config.DEFAULT_SETTINGS)
    cands = candidates.find_candidates(words, sentences, loud, opts, pool_size=12)
    results, _ = scoring.evaluate(cands, sentences, opts, JobContext(), "x", 0, 1, words=words, loud=loud)
    df = scoring.document_frequencies(sentences)
    out = []
    for r in scoring.select(results, 10, 50):
        sents = [sentences[k]["text"] for k in range(r["s0"], r["s1"] + 1)]
        out.append((" ".join(sents), postpack.generate(sents, r["hook"], r["hooks_alt"], r["category"], {}, df,
                                                       len(sentences))))
    return out


@pytest.fixture(scope="module")
def packages():
    return _packages(PODCAST) + _packages(SCRIPT)


def test_package_has_every_component(packages):
    assert len(packages) == 4
    for _, p in packages:
        assert len(p["titles"]) == 3 and len(set(p["titles"])) == 3
        assert 0 <= p["recommended_title"] < 3 and p["title"] == p["titles"][p["recommended_title"]]
        assert len(p["captions"]) == 3 and len(set(p["captions"])) == 3 and p["caption"] == p["captions"][0]
        assert 2 <= len(p["hashtags"]) <= postpack.HASHTAG_LIMIT and all(t.startswith("#") for t in p["hashtags"])
        assert p["description"] and len(p["description"]) <= postpack.DESCRIPTION_MAX
        assert p["cta"] and p["hook"]
        assert all(len(t) <= postpack.TITLE_MAX and "<" not in t and not t.endswith("...") for t in p["titles"])
        assert not any("#" in c for c in p["captions"])


def test_everything_is_grounded_in_the_clip(packages):
    for clip_text, p in packages:
        assert p["checks"] == {}
        for text in [*p["titles"], *p["captions"], p["description"], p["hook"]]:
            assert postpack.grounding_problems(text, clip_text) == [], text
        for tag in p["hashtags"]:
            assert tag[1:].lower() in clip_text.lower(), tag  # hashtags are words the speaker actually says
        # the call to action is a fixed template: it asks for an action and states nothing about the clip
        assert p["cta"] in [*postpack.CTAS.values(), postpack.CTA_DEFAULT]
        assert postpack.grounding_problems(p["cta"], clip_text, postpack.CTA_WORDS) == []


def test_recommended_title_is_the_hook_line(packages):
    titles = {p["title"] for _, p in packages}
    assert "Why do most people give up on running after three weeks?" in titles
    assert "Here's the thing nobody tells you about quitting your job" in titles


def test_conclusion_quote_keeps_the_line_that_delivers_it(packages):
    biz = next(p for text, p in packages if "biggest mistake" in text)
    assert "“The lesson is simple. Talk to customers first, then build.”" in biz["captions"]


CLIP = "I lost ten thousand dollars in my first startup. The lesson is simple: talk to customers first."


@pytest.mark.parametrize("text, problem", [
    ("I lost 50,000 dollars in my first startup", "number 50,000"),
    ("How Elon Musk lost everything in his startup", "name “Elon”"),
    ("The shocking lesson from my first startup", "“shocking” makes a claim"),
    ("Scientists agree: talk to customers first", "“scientists”"),
    ("Why crypto traders and investors lose money fast", "not in the clip"),
    ("I lost twenty thousand dollars", "“twenty” is not in the clip"),
])
def test_grounding_check_catches_invented_content(text, problem):
    problems = postpack.grounding_problems(text, CLIP)
    assert any(problem in p for p in problems), problems


def test_grounding_check_accepts_the_clips_own_words():
    for text in ["I lost ten thousand dollars in my first startup", "The lesson is simple: talk to customers first",
                 "Talk to customers first", "Losing ten thousand dollars in a first startup"]:
        assert postpack.grounding_problems(text, CLIP) == [], text
    assert postpack.hashtag_problems("#customers", CLIP) == []
    assert postpack.hashtag_problems("#TalkToCustomers", CLIP) == []
    assert postpack.hashtag_problems("#fyp", CLIP) and postpack.hashtag_problems("#crypto", CLIP)


def test_ai_suggestions_are_used_only_when_grounded(monkeypatch):
    sents = CLIP.replace(": ", ". ").split(". ")
    fake = {"titles": ["Elon Musk's 10 million dollar mistake", "My first startup cost ten thousand dollars",
                       "Talk to customers first"],
            "recommended": 0,
            "captions": ["This shocking secret will change your life", "The lesson is simple: talk to customers first.",
                         "I lost ten thousand dollars in my first startup #startup"],
            "description": "Scientists say most startups fail.", "hook": "Talk to customers first",
            "hashtags": ["startup", "fyp", "viral", "customers"]}
    monkeypatch.setattr(llm, "complete", lambda settings, prompt: "Sure: " + json.dumps(fake))
    p = postpack.generate(sents, sents[0], [], "Business", {"ai_provider": "ollama", "ollama_model": "m"})
    all_text = " ".join([*p["titles"], *p["captions"], p["description"], *p["hashtags"]])
    for invented in ("Elon", "10 million", "shocking", "Scientists", "#fyp", "#viral"):
        assert invented not in all_text
    assert "My first startup cost ten thousand dollars" in p["titles"]
    assert p["title"] != "Elon Musk's 10 million dollar mistake"  # the AI's pick was invented, so not recommended
    assert "#startup" in p["hashtags"] and "#customers" in p["hashtags"]
    assert "checked against the transcript" in p["source"] and p["checks"] == {}


def test_ai_failure_falls_back_to_extraction(monkeypatch):
    def boom(settings, prompt):
        raise llm.ProviderError("offline")

    monkeypatch.setattr(llm, "complete", boom)
    p = postpack.generate(["Why do most diets fail?", "Because willpower is a terrible strategy."], "", [], "",
                          {"ai_provider": "ollama"})
    assert p["source"] == "Extracted from the clip's transcript" and p["titles"]


def test_user_edits_are_kept_and_checked_for_information_only():
    p = postpack.generate(CLIP.split(". "), "", [], "Business", {})
    edited = postpack.apply_edit(p, {"title": "My <b>50k</b> mistake", "hashtags": ["startup", "#Money Tips", ""],
                                     "captions": ["one", "two", "three", "four"], "cta": "Follow me!",
                                     "clip_text": "ignored", "source": "ignored"})
    assert edited["title"] == "My b50k/b mistake" and edited["edited"]
    assert edited["hashtags"] == ["#startup", "#MoneyTips"] and edited["captions"] == ["one", "two", "three"]
    assert edited["cta"] == "Follow me!" and edited["source"] == p["source"] and edited["clip_text"] == p["clip_text"]
    assert any("50" in note for note in edited["checks"]["title"])  # shown as a hint, never blocks the user


def test_short_clip_does_not_crash():
    p = postpack.generate(["Okay."], "", [], "", {})
    assert isinstance(p["titles"], list) and p["cta"]


@pytest.fixture()
def api_clip(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    segs = transcribe.parse_subtitles(_srt(PODCAST))
    pdir = config.projects_dir() / "p1"
    pdir.mkdir(parents=True)
    write_json(pdir / "transcript.json", {"segments": segs})
    words = transcribe.flatten_words({"segments": segs})
    start = next(w["start"] for w in words if w["w"] == "Why")
    end = next(w["end"] for w in words if w["w"] == "later.")
    project = db.create_project("pod", source_path=str(pdir / "source.mp4"), status="ready")
    clip = db.create_clip(project["id"], start=start, end=end, title="old title", hook="Why do most people give up?",
                          hashtags=["#old"], category="Educational", caption_text="")
    return clip


def test_api_regenerate_edit_and_export(api_clip, tmp_path):
    from fastapi.testclient import TestClient

    from clipfoundry import db
    from clipfoundry.api import app

    with TestClient(app) as client:
        c = client.post(f"/api/clips/{api_clip['id']}/post-package", json={"use_ai": False}).json()
        post = c["post"]
        assert len(post["titles"]) == 3 and c["title"] == post["title"] and c["hashtags"] == post["hashtags"]
        assert "#running" in post["hashtags"]

        c = client.patch(f"/api/clips/{api_clip['id']}", json={"post": {
            "title": "My own title", "caption": "My own caption", "hashtags": ["running", "#tips"]}}).json()
        assert c["title"] == "My own title" and c["hashtags"] == ["#running", "#tips"]
        assert c["post"]["caption"] == "My own caption" and c["post"]["edited"]

        c = client.patch(f"/api/clips/{api_clip['id']}", json={"title": "Edited in the clip editor"}).json()
        assert c["post"]["title"] == "Edited in the clip editor"  # both editors stay in step

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    db.update_clip(api_clip["id"], output_path=str(video))
    from clipfoundry.pipeline import export

    z = export.build_zip({"name": "pod"}, [db.get_clip(api_clip["id"])], tmp_path / "out")
    with zipfile.ZipFile(z) as zf:
        txt = next(zf.read(n).decode() for n in zf.namelist() if n.endswith(".txt"))
        meta = json.loads(zf.read("metadata.json"))
    assert "POST PACKAGE" in txt and "Chosen title: Edited in the clip editor" in txt
    assert meta["clips"][0]["post_package"]["caption"] == "My own caption"
    assert "clip_text" not in meta["clips"][0]["post_package"]
