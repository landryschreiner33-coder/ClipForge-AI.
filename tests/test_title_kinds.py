"""Three kinds of title per clip (Searchable, Curiosity, The moment), each destination's pick with a reason, and the
platform field checks shown before posting (pipeline/postpack.py)."""
from __future__ import annotations

from clipfoundry.pipeline import postpack

SENTS = ["Why do most new streamers quit after a month?", "They stream to an empty chat for hours.",
         "The fix is boring.", "Stream the same game at the same time three days a week.",
         "That's why my channel grew to two hundred viewers in six weeks."]


def test_a_package_offers_one_title_of_each_kind_from_the_clips_own_words():
    pkg = postpack.generate(SENTS, SENTS[0], [], "education", {}, use_ai=False)
    kinds = [o["kind"] for o in pkg["guide"]["options"]]
    assert sorted(kinds) == ["curiosity", "moment", "search"], pkg["guide"]["options"]
    clip_words = set(" ".join(SENTS).lower().replace("?", " ").replace(".", " ").split())
    for o in pkg["guide"]["options"]:
        assert not postpack.grounding_problems(o["text"], " ".join(SENTS)), o
        assert set(o["text"].lower().replace(":", " ").replace("?", " ").split()) <= clip_words | {""}
    yt, tt = pkg["guide"]["youtube"], pkg["guide"]["tiktok"]
    assert pkg["guide"]["options"][yt["recommended"]]["text"] == pkg["title"] and yt["why"]
    assert pkg["guide"]["options"][tt["recommended"]]["kind"] == "curiosity" and "watch time" in tt["why"]
    assert pkg["limits"] == {"youtube": [], "tiktok": []}


def test_title_kinds_are_read_from_the_title():
    kws = ["streamers", "chat"]
    assert postpack.title_kind("Why do streamers quit?", kws) == "curiosity"
    assert postpack.title_kind("Here's why nobody watches", kws) == "curiosity"
    assert postpack.title_kind("Streamers: stream at the same time", kws) == "search"
    assert postpack.title_kind("My channel grew to two hundred viewers", kws) == "moment"


def test_a_models_titles_and_the_recommended_title_are_never_replaced():
    pkg = {"titles": ["Why do most new streamers quit after a month?", "Why chat stays empty?", "Why bother?"],
           "recommended_title": 0}
    out = postpack.ensure_kinds(dict(pkg), SENTS, ["streamers"], frozenset({"Why chat stays empty?"}))
    assert out["titles"][0] == pkg["titles"][0] and "Why chat stays empty?" in out["titles"]
    assert out["titles"][2] != "Why bother?"  # the spare question became another kind


def test_platform_field_checks_before_posting():
    pkg = {"title": "x" * 101, "description": "a < b", "caption": "y" * 2195, "hashtags": ["#one two", "#a", "#A"]}
    p = postpack.field_problems(pkg)
    assert any("101 characters" in x for x in p["youtube"]) and any("< or >" in x for x in p["youtube"])
    assert any("spaces" in x for x in p["youtube"]) and any("Repeated hashtags" in x for x in p["youtube"])
    assert any("TikTok allows 2200" in x for x in p["tiktok"])
    many = postpack.field_problems({"title": "ok", "hashtags": [f"#t{k}" for k in range(61)]})
    assert any("ignore all of them" in x for x in many["youtube"])


def test_an_edit_keeps_the_guide_and_checks_in_step():
    pkg = postpack.generate(SENTS, SENTS[0], [], "education", {}, use_ai=False)
    edited = postpack.apply_edit(pkg, {"title": "z" * 120})
    assert edited["limits"]["youtube"] == [] or "characters" in " ".join(edited["limits"]["youtube"])
    assert edited["guide"]["options"] == pkg["guide"]["options"]
