"""Packaging AI: platform packages in several styles, packaging score, grounding validation and regeneration."""
from __future__ import annotations

import json

import pytest

from clipfoundry.pipeline import postpack, transcribe
from test_core import SCRIPT, _srt

CLIP = SCRIPT[:7]  # "Here's the biggest mistake most people make when they start a business." ... "Talk to customers..."
TEXT = " ".join(CLIP)


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return tmp_path


def test_validation_catches_fabrication_repetition_and_duplicates():
    from clipfoundry.autopilot import packaging

    ok = {"title": "The biggest mistake most people make when they start a business",
          "caption": "They spend months building a product nobody asked for.",
          "description": "They spend months building a product nobody asked for.\n\n" + postpack.CTA_DEFAULT
                         + "\n\n#business #customers", "hashtags": ["#business", "#customers"], "tags": ["business"]}
    assert packaging.validate(ok, TEXT) == []
    bad = dict(ok, title="Elon Musk lost 5 million dollars on this")
    problems = packaging.validate(bad, TEXT)
    assert any("5" in p for p in problems) and any("Musk" in p or "Elon" in p for p in problems)
    quote = dict(ok, caption="He said “customers are always right” and it changed everything.")
    assert any("quote" in p for p in packaging.validate(quote, TEXT))
    rep = dict(ok, caption="Customers customers customers: talk to customers first.")
    assert any("repeats" in p for p in packaging.validate(rep, TEXT))
    tags = dict(ok, hashtags=["#crypto"])
    assert any("#crypto" in p for p in packaging.validate(tags, TEXT))
    dup = packaging.validate(ok, TEXT, prior_titles=["The biggest mistake most people make when they start a business!"])
    assert any("earlier title" in p for p in dup)
    cc = dict(ok, description=ok["description"] + "\n\nSource: “Talk” by Someone (https://x), licensed under CC BY.")
    assert packaging.validate(cc, TEXT) == []  # the attribution line is a fixed template


def test_extracted_candidates_cover_styles_and_platforms():
    from clipfoundry.autopilot import packaging

    clip = {"hook": CLIP[0], "post": {"cta": "Save this for later."}}
    yt = packaging.extracted_candidates("youtube", CLIP, clip, "", ["business", "customers"], ["#business",
                                                                                              "#customers"])
    styles = [c["style"] for c in yt]
    assert len(yt) >= 3 and len(set(c["title"] for c in yt)) == len(yt) and "context" in styles
    for c in yt:
        assert packaging.validate(c, TEXT) == [], (c["style"], packaging.validate(c, TEXT))
        assert "Save this for later." in c["description"] or c["style"] == "debate"
        assert c["tags"] and len(c["title"]) <= 100
    tt = packaging.extracted_candidates("tiktok", CLIP, clip, "Source: “x” by y (z), licensed under CC BY.",
                                        ["business"], ["#business"])
    assert all("#business" in c["caption"] and "CC BY" in c["caption"] for c in tt)


def test_scores_reward_grounded_searchable_unique_packages():
    from clipfoundry.autopilot import packaging

    meta = {"title": "Here's the biggest mistake most people make when they start a business",
            "caption": "", "hashtags": ["#business"], "tags": ["business"]}
    base = packaging.score(meta, "youtube", TEXT, ["business", "customers"], [], [], [])
    assert base["score"] > 30 and base["grounded"]
    trend = packaging.score(meta, "youtube", TEXT, ["business"], ["business", "mistake"], [], [])
    assert trend["components"]["searchability"] > base["components"]["searchability"]
    dup = packaging.score(meta, "youtube", TEXT, ["business"], [], [meta["title"]], [])
    assert dup["components"]["uniqueness"] == 0 and dup["score"] < base["score"]
    assert packaging.score(meta, "youtube", TEXT, [], [], [], ["title: invented"])["score"] == 0


def test_ai_suggestions_are_regenerated_until_grounded(monkeypatch):
    from clipfoundry.autopilot import packaging
    from clipfoundry.pipeline import llm

    prompts: list[str] = []
    answers = [{"suggestions": [{"style": "curiosity", "text": "Why 97% of founders fail in 2 years"}]},
               {"suggestions": [{"style": "curiosity", "text": "They spent a whole year building what nobody asked for"}]}]

    def fake(settings, prompt):
        prompts.append(prompt)
        return json.dumps(answers[min(len(prompts) - 1, len(answers) - 1)])

    monkeypatch.setattr(llm, "complete", fake)
    settings = {"ai_provider": "ollama"}
    out = packaging.ai_candidates(settings, "youtube", CLIP, {"post": {}}, "", ["business"], ["#business"], TEXT, [])
    assert len(prompts) == 2 and "rejected because" in prompts[1] and "97" in prompts[1]
    assert out and out[0]["origin"] == "ai" and out[0]["attempt"] == 2
    answers[:] = [{"suggestions": [{"style": "direct", "text": "Jeff Bezos explains 3 secrets"}]}]
    prompts.clear()
    assert packaging.ai_candidates(settings, "youtube", CLIP, {"post": {}}, "", [], [], TEXT, []) == []
    assert len(prompts) == packaging.MAX_ATTEMPTS  # gave up after three tries: the extracted text is used


def test_fallback_avoids_duplicate_titles():
    from clipfoundry.autopilot import packaging

    clip = {"title": "The biggest mistake most people make when they start a business", "post": {}}
    prior = [clip["title"], "They spend months building a product nobody asked for"]
    meta = packaging.fallback("youtube", CLIP, clip, "", ["business"], ["#business"], TEXT, prior)
    assert meta["origin"] == "fallback" and packaging.validate(meta, TEXT, prior) == []


def test_package_clip_job(data):
    from clipfoundry import db
    from clipfoundry.autopilot import host, queue
    from clipfoundry.pipeline.common import write_json

    folder = data / "p"
    folder.mkdir()
    (folder / "source.mp4").write_bytes(b"x")
    write_json(folder / "transcript.json", {"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    project = db.create_project("talk", source_path=str(folder / "source.mp4"), status="ready", origin="autopilot")
    words = transcribe.flatten_words({"segments": transcribe.parse_subtitles(_srt(SCRIPT))})
    end = next(w["end"] for w in words if w["w"] == "build.")
    (folder / "clip.mp4").write_bytes(b"placeholder")
    clip = db.create_clip(project["id"], start=0.3, end=end, title="t", hook=CLIP[0], status="ready",
                          caption_text=TEXT, hashtags=["#business", "#customers"], post={"cta": postpack.CTA_DEFAULT},
                          output_path=str(folder / "clip.mp4"))
    db.insert("clip_scores", {"clip_id": clip["id"], "clip": 70.0}, key="clip_id")
    db.save_settings({"autopilot_youtube": True, "autopilot_tiktok": True})
    host.WorkerHost(periodic=False)
    row = queue.enqueue("package_clip", {"clip_id": clip["id"]})
    out = host.HANDLERS["package_clip"](host.Job(queue.get(row["id"]), "t"))
    assert out["platforms"] == ["youtube", "tiktok"]
    for platform in ("youtube", "tiktok"):
        rows = db.select("metadata_candidates", "clip_id = ? AND platform = ?", (clip["id"], platform))
        chosen = [r for r in rows if r["selected"]]
        assert len(rows) >= 3 and len(chosen) == 1 and not chosen[0]["problems"] and chosen[0]["score"] > 0
        assert chosen[0]["score"] == max(r["score"] for r in rows if not r["problems"])
    assert db.fetch("clip_scores", clip["id"], "clip_id")["packaging"] > 0
    assert queue.jobs(worker="quality_gate")  # packaged clips go through the final quality gate first
