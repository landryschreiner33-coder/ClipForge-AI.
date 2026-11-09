"""Story clips and their two settings (studio/story_review.py): Full story makes one clip per story, Story parts makes
Part 1, Part 2... of every story, no story clip is ever longer than five minutes whatever the owner does, and a story
clip keeps the whole picture still and centred with the captions above it (pipeline/captions.py "above").

Stories come from labelled recordings (story_fixtures.py); the database is real (a temporary data folder) and the
render check renders a real video.
"""
from __future__ import annotations

import itertools
import subprocess

import numpy as np
import pytest

from story_fixtures import three_stories
from synthetic_media import make_video, needs_ffmpeg
from test_story_parts import _seven_minutes

H = {"X-ClipFoundry": "1"}
STEADY_EDIT = {"silence": "off", "remove_fillers": False, "hook_overlay": False, "layout": "fit", "tracking": "center",
               "zoom": 1.0, "auto_zoom": False, "caption_position": "above"}


def _plan(transcript, duration: float, split: str):
    from clipfoundry.pipeline import stories, transcribe
    from clipfoundry.pipeline.text_utils import build_sentences
    from clipfoundry.studio import story_review

    words = transcribe.flatten_words(transcript)
    sents = build_sentences(words)
    result = stories.propose(words, sents, duration)
    return {**result, "items": story_review.plan_parts(result["items"], sents, words, split)}, words


@pytest.fixture()
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db

    db.init()
    return db


def _project(db, split: str):
    from clipfoundry.studio import story_review

    transcript, fx = three_stories()
    result, words = _plan(transcript, 720.0, split)
    p = db.create_project("stories", status="ready", clip_mode="full_stories", duration=720.0,
                          options={"story_split": split})
    story_review.save(p, result)
    return db.get_project(p["id"]), words, fx


def _stories(project_id: str) -> list[dict]:
    from clipfoundry.studio import story_review

    return [s for s in story_review.list_for(project_id) if s["kind"] == "story"]


# ------------------------------------------------------------------ the two settings
def test_full_story_makes_one_clip_per_story_with_the_whole_picture_still_and_centred(data):
    from clipfoundry.studio import story_review

    p, words, fx = _project(data, "whole")
    assert story_review.split_of(p) == "whole"
    rows = _stories(p["id"])
    assert len(rows) == 3 and all(s["part"] == 0 and s["parts"] == 0 and s["story_key"] == "" for s in rows)
    made = story_review.auto_clips(p, words, {})
    assert len(made) == 3
    for clip, row in zip(made, rows):
        assert (clip["start"], clip["end"]) == (pytest.approx(row["start"]), pytest.approx(row["end"]))
        assert clip["edit"] == STEADY_EDIT  # no camera moves, no zoom, nothing cropped, captions above the picture
        assert clip["hook"] == "" and "(Part" not in clip["title"]
        assert clip["analysis"]["story"]["parts"] == 0


def test_story_parts_cuts_every_story_into_numbered_parts_that_keep_its_name(data):
    from clipfoundry.studio import story_review

    p, words, fx = _project(data, "parts")
    assert story_review.split_of(p) == "parts"
    rows = _stories(p["id"])
    groups = [list(g) for _, g in itertools.groupby(rows, key=lambda s: s["story_key"])]
    # three stories of three to four and a half minutes: two parts each, every part over a minute
    assert len(groups) == 3 and all(len(g) == 2 for g in groups)
    assert len({g[0]["story_key"] for g in groups}) == 3 and all(g[0]["story_key"] for g in groups)
    for g, key in zip(groups, "ABC"):
        assert abs(g[0]["start"] - fx["labels"][key][0]) <= 1.0  # the story starts where it really starts
        assert [s["part"] for s in g] == [1, 2] and all(s["parts"] == 2 for s in g)
        assert g[0]["end"] == g[1]["start"]  # nothing is lost between the parts
        assert g[0]["opening"] == fx["openings"][key]
        base = g[0]["title"].removesuffix(" (Part 1)")
        assert base != g[0]["title"] and g[1]["title"] == base + " (Part 2)"
        assert g[1]["reason"].startswith("Part 2 of 2: starts ")
        assert all(60 <= s["duration"] <= 180 for s in g)
    made = story_review.auto_clips(p, words, {})
    assert len(made) == 6
    for clip, row in zip(made, rows):
        part = row["part"]
        assert clip["hook"] == f"Part {part}" and clip["title"].endswith(f"(Part {part})")
        assert clip["edit"]["hook_overlay"] is True and clip["edit"]["hook_seconds"] > clip["duration"]  # all along
        assert clip["edit"]["layout"] == "fit" and clip["edit"]["tracking"] == "center"
        assert clip["analysis"]["story"]["part"] == part and clip["analysis"]["story"]["parts"] == 2


def test_make_clips_offers_story_parts_as_a_full_stories_project(data, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.studio import clips_flow, story_review

    parts = clips_flow.prepare("local", mode="story_parts")
    assert (parts["mode"], parts["request_mode"], parts["options"]["story_split"]) == \
        ("full_stories", "story_parts", "parts")  # the same styles, skills and examples as Full stories
    assert clips_flow.prepare("local", mode="full_stories")["options"]["story_split"] == "whole"
    assert "story_split" not in clips_flow.prepare("local", mode="highlights")["options"]
    with pytest.raises(clips_flow.FlowError, match="Story parts"):
        clips_flow.prepare("local", mode="chapters")
    assert story_review.split_of({"options": {"story_split": "sideways"}}) == "whole"
    assert story_review.split_of({}) == "whole"  # projects made before the setting existed
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        preview = api.get("/api/studio/guidance/preview", params={"mode": "story_parts"})
        assert preview.status_code == 200, preview.text
        remembered = api.put("/api/preferences/appearance", headers=H, json={"value": {"clips_mode": "story_parts"}})
        assert remembered.status_code == 200 and remembered.json()["value"]["clips_mode"] == "story_parts"
        p, _words, _fx = _project(data, "parts")
        assert api.get(f"/api/projects/{p['id']}/stories").json()["split"] == "parts"
        listed = next(x for x in api.get("/api/studio/projects").json() if x["id"] == p["id"])
        assert (listed["mode"], listed["story_split"]) == ("full_stories", "parts")


# ------------------------------------------------------------------ never longer than five minutes
def test_a_story_longer_than_five_minutes_is_cut_at_its_best_point_in_both_settings():
    from clipfoundry.studio import story_review

    sents, words, start, end = _seven_minutes()
    item = {"kind": "story", "start": start, "end": end, "title": "My in-laws took over the reunion",
            "opening": sents[0]["text"], "closing": sents[-1]["text"], "reason": "Starts with the post's title",
            "completeness": "complete", "confidence": 0.9}
    whole = story_review.plan_parts([item], sents, words, "whole")
    assert [w["title"] for w in whole] == ["My in-laws took over the reunion (Part 1)",
                                          "My in-laws took over the reunion (Part 2)"]
    assert whole[0]["start"] == start and whole[-1]["end"] == end and whole[0]["end"] == whole[1]["start"]
    assert all(w["end"] - w["start"] <= 300 for w in whole)
    assert "longer than five minutes" in whole[0]["reason"] and whole[1]["reason"].startswith("Part 2 of 2")
    assert whole[0]["opening"] == item["opening"] and whole[1]["closing"] == item["closing"]
    assert len(story_review.plan_parts([item], sents, words, "parts")) == 4
    short = {**item, "end": start + 200}
    assert story_review.plan_parts([short], sents, words, "whole") == [{**short, "story": 0}]


def test_a_story_stored_longer_than_five_minutes_becomes_parts_when_its_clips_are_made(data):
    from clipfoundry.studio import story_review

    p, words, fx = _project(data, "whole")
    a, b, c = _stories(p["id"])
    # stored before the limit existed: B and C as one story of over eight minutes
    data.update("story_proposals", b["id"], end_ms=int(round(c["end"] * 1000)))
    data.execute("DELETE FROM story_proposals WHERE id = ?", (c["id"],))
    renamed = story_review.patch(b["id"], title="The cake and the highway")  # other changes still work on it
    assert renamed["title"] == "The cake and the highway"
    made = story_review.auto_clips(data.get_project(p["id"]), words, {})
    assert len(made) == 3 and all(m["duration"] <= 300 for m in made)
    assert made[1]["start"] == pytest.approx(b["start"]) and made[2]["end"] == pytest.approx(c["end"])
    assert made[1]["end"] == pytest.approx(made[2]["start"])  # nothing lost at the cut
    assert [m["hook"] for m in made] == ["", "Part 1", "Part 2"]
    assert [m["title"] for m in made[1:]] == ["The cake and the highway (Part 1)", "The cake and the highway (Part 2)"]
    rows = story_review.list_for(p["id"])
    assert [(r["kind"], r["part"]) for r in rows] == [("gap", 0), ("story", 0), ("gap", 0), ("story", 1),
                                                      ("story", 2), ("gap", 0)]
    assert [r["position"] for r in rows] == sorted({r["position"] for r in rows})  # one place each, in order
    assert rows[3]["story_key"] == rows[4]["story_key"] != ""


def test_moving_or_merging_a_story_by_hand_never_makes_it_longer_than_five_minutes(data):
    from clipfoundry.studio import story_review

    p, words, fx = _project(data, "whole")
    a, b, c = _stories(p["id"])
    with pytest.raises(story_review.StoryError, match="at most 5 minutes.*would make it 11:25"):
        story_review.patch(c["id"], start_ms=int(a["start"] * 1000))
    with pytest.raises(story_review.StoryError, match="Keep them as parts"):
        story_review.merge([b["id"], c["id"]])
    assert story_review.patch(c["id"], start_ms=int(c["start"] * 1000) - 20_000)["start_ms"] < c["start"] * 1000


def test_splitting_and_merging_by_hand_keeps_the_parts_numbered(data):
    from clipfoundry.studio import story_review

    p, words, fx = _project(data, "whole")
    a = _stories(p["id"])[0]
    first, second = story_review.split(a["id"], int((a["start"] + 80) * 1000))
    assert (first["part"], second["part"], first["parts"], second["parts"]) == (1, 2, 2, 2)
    assert first["story_key"] == second["story_key"] != ""
    assert first["title"].endswith(" (Part 1)") and second["title"].endswith(" (Part 2)")
    story_review.split(second["id"], int((a["start"] + 130) * 1000))
    parts = [s for s in story_review.list_for(p["id"]) if s["story_key"] == first["story_key"]]
    assert [s["part"] for s in parts] == [1, 2, 3] and {s["parts"] for s in parts} == {3}
    assert [s["title"][-8:] for s in parts] == ["(Part 1)", "(Part 2)", "(Part 3)"]
    story_review.merge([parts[1]["id"], parts[2]["id"]])
    parts = [s for s in story_review.list_for(p["id"]) if s["story_key"] == first["story_key"]]
    assert [(s["part"], s["parts"]) for s in parts] == [(1, 2), (2, 2)] and parts[1]["title"].endswith("(Part 2)")
    whole = story_review.merge([parts[0]["id"], parts[1]["id"]])
    assert (whole["part"], whole["parts"], whole["story_key"]) == (0, 0, "") and "(Part" not in whole["title"]
    assert (whole["start_ms"], whole["end_ms"]) == (int(round(a["start"] * 1000)), int(round(a["end"] * 1000)))


def test_part_n_still_shows_for_the_whole_part_after_a_trim(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app
    from clipfoundry.studio import story_review

    p = data.create_project("stories", status="ready", clip_mode="full_stories", duration=900.0)
    edit = story_review.story_edit({}, {"start_ms": 100_000, "end_ms": 220_000, "parts": 2})
    part = data.create_clip(p["id"], rank=0, start=100.0, end=220.0, title="A story (Part 1)", hook="Part 1",
                            category="story", status="ready", duration=120.0, edit=edit)
    own = data.create_clip(p["id"], rank=1, start=220.0, end=330.0, title="A story (Part 2)", hook="Part 2",
                           category="story", status="ready", duration=110.0,
                           edit={**edit, "hook_seconds": 4.0})
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        # lengthened: "Part 1" still shows to the new end
        assert api.patch(f"/api/clips/{part['id']}", headers=H, json={"edit": {"end": 260.0}}).status_code == 200
        assert data.get_clip(part["id"])["edit"]["hook_seconds"] == 161.0
        # shortened, and the trim taken back: still the whole part
        assert api.patch(f"/api/clips/{part['id']}", headers=H, json={"edit": {"start": 130.0}}).status_code == 200
        assert data.get_clip(part["id"])["edit"]["hook_seconds"] == 131.0
        r = api.patch(f"/api/clips/{part['id']}", headers=H, json={"edit": {"start": None, "end": None}})
        assert r.status_code == 200 and data.get_clip(part["id"])["edit"]["hook_seconds"] == 121.0
        # a time the owner set for the label is kept, and so is one set in the same change as the trim
        assert api.patch(f"/api/clips/{own['id']}", headers=H, json={"edit": {"end": 340.0}}).status_code == 200
        assert data.get_clip(own["id"])["edit"]["hook_seconds"] == 4.0
        r = api.patch(f"/api/clips/{part['id']}", headers=H, json={"edit": {"end": 250.0, "hook_seconds": 6.0}})
        assert r.status_code == 200 and data.get_clip(part["id"])["edit"]["hook_seconds"] == 6.0


def test_trimming_a_story_clip_past_five_minutes_is_refused_and_other_edits_still_work(data):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    p = data.create_project("stories", status="ready", clip_mode="full_stories", duration=900.0)

    def clip(start, end, category="story"):
        return data.create_clip(p["id"], rank=0, start=start, end=end, title="A story", hook="", category=category,
                                status="ready", duration=end - start, edit={})

    story, older, highlight = clip(100.0, 380.0), clip(0.0, 420.0), clip(0.0, 400.0, "highlight")
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.patch(f"/api/clips/{story['id']}", headers=H, json={"edit": {"end": 420.0}})
        assert r.status_code == 400 and "at most 5 minutes" in r.json()["detail"] and "5:20" in r.json()["detail"]
        assert data.get_clip(story["id"])["edit"] == {}  # nothing changed
        assert api.patch(f"/api/clips/{story['id']}", headers=H, json={"edit": {"end": 395.0}}).status_code == 200
        # a story clip made before the limit can still be changed in other ways, and a highlight has no limit here
        assert api.patch(f"/api/clips/{older['id']}", headers=H,
                         json={"edit": {"caption_position": "bottom"}}).status_code == 200
        assert api.patch(f"/api/clips/{highlight['id']}", headers=H, json={"edit": {"end": 410.0}}).status_code == 200
        # a trim is a time in seconds: "NaN" (or infinity) would render the clip to the end of the recording
        for bad in ("NaN", "inf", "soon"):
            r = api.patch(f"/api/clips/{story['id']}", headers=H, json={"edit": {"end": bad}})
            assert r.status_code == 400 and "time in seconds" in r.json()["detail"], bad
        r = api.patch(f"/api/clips/{story['id']}", content='{"edit": {"start": NaN}}',
                      headers={**H, "content-type": "application/json"})
        assert r.status_code in (400, 422)  # a bare NaN in the body is refused one way or the other
        assert data.get_clip(story["id"])["edit"] == {"end": 395.0}


# ------------------------------------------------------------------ the picture
def test_only_a_framing_chosen_for_the_project_changes_the_still_picture():
    from clipfoundry.studio import story_review

    def project(*decisions):
        return {"guidance": {"decisions": [{"field": f, "value": v, "from": {"level": level}}
                                           for f, v, level in decisions]}}

    row = {"start_ms": 0, "end_ms": 120_000, "parts": 0}
    assert story_review.story_edit({}, row) == STEADY_EDIT
    # the app's settings and a saved style do not move the camera of a story clip
    got = story_review.story_edit(project(("layout", "fill", "settings"), ("tracking", "face", "style"),
                                          ("caption_position", "bottom", "settings")), row)
    assert got == STEADY_EDIT
    # a framing chosen for this project in Make clips wins, and so does a caption position chosen anywhere
    got = story_review.story_edit(project(("layout", "fill", "project"), ("caption_position", "bottom", "style")),
                                  row)
    assert "layout" not in got and "caption_position" not in got
    assert (got["tracking"], got["zoom"], got["auto_zoom"]) == ("center", 1.0, False)  # still, centred, not zoomed
    got = story_review.story_edit({}, {"start_ms": 0, "end_ms": 95_500, "parts": 3})
    assert got["hook_overlay"] is True and got["hook_seconds"] == 97  # "Part N" for the whole part
    # a subject to follow chosen for this project needs the vertical frame, or the choice would change nothing
    got = story_review.story_edit(project(("tracking", "face", "project")), row)
    assert got["layout"] == "fill" and "tracking" not in got and (got["zoom"], got["auto_zoom"]) == (1.0, False)
    # following the centre keeps the whole picture, and a framing chosen with the subject is used as chosen
    assert story_review.story_edit(project(("tracking", "center", "project")), row)["layout"] == "fit"
    got = story_review.story_edit(project(("tracking", "face", "project"), ("layout", "fit", "project")), row)
    assert "layout" not in got and "tracking" not in got
    # a subject chosen by a style or the settings does not move the camera
    assert story_review.story_edit(project(("tracking", "face", "style")), row) == STEADY_EDIT


def test_used_from_your_brain_shows_the_framing_story_clips_really_use(data):
    from clipfoundry.studio import clips_flow, story_review, styles

    def decided(snapshot):
        return {d["field"]: (d["value"], d["from"]["level"]) for d in snapshot["decisions"]
                if d["field"] in ("layout", "tracking", "caption_position")}

    snap = clips_flow.prepare("local", mode="story_parts", style_id="settings")["guidance"]
    assert decided(snap) == {"layout": ("fit", "story"), "tracking": ("center", "story"),
                             "caption_position": ("above", "story")}
    by = {d["field"]: d for d in snap["decisions"]}
    assert by["layout"]["text"] == "Framing: fit with blurred background"
    assert by["caption_position"]["text"] == "Caption position: above the picture"
    assert by["layout"]["overridden"][0]["name"] == "Settings" and by["layout"]["overridden"][0]["value"] == "fill"
    assert story_review.story_edit({"guidance": snap}, {"start_ms": 0, "end_ms": 60_000}) == STEADY_EDIT
    # a saved style does not move the camera of a story clip, but its caption position is used
    gaming = styles.create("local", "Gaming", {"layout": "fill", "tracking": "face", "caption_position": "bottom"},
                           ["highlights", "full_stories"])
    snap = clips_flow.prepare("local", mode="full_stories", style_id=gaming["id"])["guidance"]
    assert decided(snap) == {"layout": ("fit", "story"), "tracking": ("center", "story"),
                             "caption_position": ("bottom", "style")}
    assert {d["field"]: d for d in snap["decisions"]}["tracking"]["overridden"][0]["name"] == "Gaming"
    edit = story_review.story_edit({"guidance": snap}, {"start_ms": 0, "end_ms": 60_000})
    assert edit["layout"] == "fit" and "caption_position" not in edit  # the style's lower third is rendered
    # a framing chosen for this project wins; Highlights are not story clips
    own = clips_flow.prepare("local", mode="full_stories", style_id=gaming["id"],
                             choices={"layout": "fill", "tracking": "screen"})["guidance"]
    assert decided(own)["layout"] == ("fill", "project") and decided(own)["tracking"] == ("screen", "project")
    assert "layout" not in story_review.story_edit({"guidance": own}, {"start_ms": 0, "end_ms": 60_000})
    # a subject to follow chosen for this project: the vertical frame, so the choice does something
    face = clips_flow.prepare("local", mode="story_parts", style_id="settings", choices={"tracking": "face"})
    snap = face["guidance"]
    assert decided(snap)["tracking"] == ("face", "project") and decided(snap)["layout"][0] == "fill"
    assert face["options"]["layout"] == "fill" and face["options"]["tracking"] == "face"
    edit = story_review.story_edit({"guidance": snap}, {"start_ms": 0, "end_ms": 60_000})
    assert edit["layout"] == "fill" and "tracking" not in edit
    styled = clips_flow.prepare("local", mode="full_stories", style_id=gaming["id"], choices={"tracking": "face"})
    assert decided(styled["guidance"])["layout"] == ("fill", "style")  # the style's framing already follows it
    fit = styles.create("local", "Wide", {"layout": "fit"}, ["full_stories"])
    snap = clips_flow.prepare("local", mode="full_stories", style_id=fit["id"],
                              choices={"tracking": "face"})["guidance"]
    layout = {d["field"]: d for d in snap["decisions"]}["layout"]
    assert (layout["value"], layout["from"]["level"]) == ("fill", "story")
    assert layout["overridden"][0]["name"] == "Wide" and "vertical frame" in layout["overridden"][0]["reason"]
    assert decided(clips_flow.prepare("local", mode="highlights", style_id=gaming["id"])["guidance"]) == \
        {"layout": ("fill", "style"), "tracking": ("face", "style"), "caption_position": ("bottom", "style")}


def _caption_style(opts: dict, hook: str = "") -> tuple[int, int, int]:
    from clipfoundry.pipeline import captions

    words = [{"w": "My", "start": 0.2, "end": 0.4}, {"w": "sister", "start": 0.45, "end": 0.8},
             {"w": "laughed.", "start": 0.85, "end": 1.3}]
    ass = captions.build_ass(words, {"caption_style": "bold", **opts}, 3.0, hook)
    fields = next(x for x in ass.splitlines() if x.startswith("Style: Caption,")).split(",")
    return int(fields[2]), int(fields[18]), int(fields[21])  # size, alignment, MarginV


def test_captions_sit_right_above_a_fitted_picture_and_otherwise_in_the_lower_third():
    from clipfoundry.pipeline import captions

    lower_third = (92, 2, int(1920 * captions.POSITIONS["bottom"][1]))
    wide = (1920 - 607.5) / 2  # a 16:9 game fitted into the 9:16 frame: 607.5 px tall, starting 656 px down
    size, align, margin = _caption_style({"caption_position": "above", "picture_top": wide})
    assert (size, align) == (92, 2) and margin == int(1920 - wide + captions.ABOVE_GAP)  # just above the picture
    assert 1920 * captions.POSITIONS["top"][1] < 1920 - margin - 2 * size  # two lines fit under the apps' top bar
    # "Part 2" at the top still leaves room for two lines above a 16:9 game; above a 16:10 one the words get a
    # little smaller so they still fit between it and the picture
    size, align, margin = _caption_style({"caption_position": "above", "picture_top": wide, "hook_overlay": True},
                                         "Part 2")
    assert size == 92 and align == 2 and margin == int(1920 - wide + captions.ABOVE_GAP)
    tall = (1920 - 675) / 2  # 16:10
    size, align, margin = _caption_style({"caption_position": "above", "picture_top": tall, "hook_overlay": True},
                                         "Part 2")
    assert size == 82 and align == 2 and margin == int(1920 - tall + captions.ABOVE_GAP)
    assert captions.hook_bottom("Part 2") + captions.HOOK_GAP <= tall - captions.ABOVE_GAP - 2 * 82
    # no room above the picture (4:3 under a headline, a square picture) or no fitted picture: the lower third
    four_three = (1920 - 810) / 2
    assert _caption_style({"caption_position": "above", "picture_top": four_three, "hook_overlay": True},
                          "Part 2") == lower_third
    assert _caption_style({"caption_position": "above", "picture_top": (1920 - 1080) / 2}) == lower_third
    assert _caption_style({"caption_position": "above", "picture_top": None}) == lower_third
    assert _caption_style({"caption_position": "bottom", "picture_top": wide}) == lower_third


def test_captions_at_the_top_go_under_the_part_label_while_it_shows():
    from clipfoundry.pipeline import captions

    words = [{"w": w, "start": 0.2 + 0.4 * k, "end": 0.5 + 0.4 * k}
             for k, w in enumerate("My sister laughed at me again and again.".split())]

    def margins(opts, hook="Part 2"):
        ass = captions.build_ass(words, {"caption_style": "bold", "caption_position": "top", **opts}, 3.5, hook)
        return [int(x.split(",")[7]) for x in ass.splitlines() if x.startswith("Dialogue: 1,")]

    below = int(captions.hook_bottom("Part 2") + captions.HOOK_GAP)
    assert below > 1920 * captions.POSITIONS["top"][1]  # the top captions' usual place is inside the label's box
    # a story part: "Part 2" shows for the whole clip, so every caption sits under it
    assert set(margins({"hook_overlay": True, "hook_seconds": 4.5})) == {below}
    # a headline for the first second: the captions shown with it go under it, the later ones back to the top
    first = margins({"hook_overlay": True, "hook_seconds": 1.0})
    assert first[0] == below and first[-1] == 0
    # no headline, or the captions somewhere else: nothing moves
    assert set(margins({"hook_overlay": False})) == {0}
    assert set(margins({"hook_overlay": True, "hook_seconds": 4.5, "caption_position": "bottom"})) == {0}
    assert set(margins({"hook_overlay": True, "hook_seconds": 4.5}, hook="")) == {0}
    # a long headline wraps, and the captions go under all of its lines
    long_hook = "I told my whole family the truth at dinner and nobody believed me at all"
    assert captions.hook_bottom(long_hook) > captions.hook_bottom("Part 2") + 20


@needs_ffmpeg
@pytest.mark.slow
def test_libass_draws_story_captions_clear_of_the_part_label_and_of_the_game(tmp_path):
    """The measured sizes hold in libass itself: in every caption style, captions above a fitted 16:9 or 16:10 game
    stay between the "Part N" box and the picture, two wrapped lines stay under the apps' top bar, and captions at
    the top never touch the box."""
    from clipfoundry import config
    from clipfoundry.pipeline import captions

    def ink(ass: str, keep: str, t: float):
        """(first row, last row) where the `keep` events draw on a grey frame at time t."""
        path = tmp_path / "x.ass"
        path.write_text("\n".join(x for x in ass.splitlines() if not x.startswith("Dialogue:") or f",{keep}," in x)
                        + "\n", encoding="utf-8")
        raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x808080:s=1080x1920:d=4:r=10",
                              "-vf", f"ass={path.name}:fontsdir={config.FONTS_DIR}", "-ss", f"{t:.2f}",
                              "-frames:v", "1", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
                             cwd=tmp_path, capture_output=True, check=True).stdout
        rows = np.nonzero((np.abs(np.frombuffer(raw, np.uint8).reshape(1920, 1080).astype(int) - 128) > 10)
                          .any(axis=1))[0]
        return (int(rows.min()), int(rows.max())) if len(rows) else None

    texts = {"bold": "SHE LAUGHED AGAIN", "high_energy": "ABSOLUTELY NOT", "clean": "and then my sister laughed",
             "minimal": "and then my sister laughed at the"}
    lower_third = int(1920 * captions.POSITIONS["bottom"][1])
    for style, text in texts.items():
        words = [{"w": w, "start": 0.1 + 0.35 * k, "end": 0.4 + 0.35 * k, "em": len(w) > 6}
                 for k, w in enumerate(text.split())]
        times = [0.3 + 0.35 * k for k in range(len(words))]  # each word highlighted (and grown) in turn
        for top in ((1920 - 607.5) / 2, (1920 - 675) / 2):  # 16:9 and 16:10 games, fitted
            opts = {"caption_style": style, "caption_position": "above", "picture_top": top, "hook_overlay": True,
                    "hook_seconds": 4.0, "caption_emphasis": True}
            ass = captions.build_ass(words, opts, 3.0, "Part 2")
            if int(next(x for x in ass.splitlines() if x.startswith("Style: Caption,")).split(",")[21]) == lower_third:
                # the one combination without room for two lines between "Part 2" and the picture, even at four
                # fifths of the size: the captions go to the lower third as usual
                assert (style, top) == ("high_energy", (1920 - 675) / 2)
                continue
            box = ink(ass, "Hook", 1.0)
            for t in times:
                got = ink(ass, "Caption", t)
                assert got and got[0] > box[1] and got[1] < top, (style, top, t, box, got)
        # captions at the top under "Part 2"
        ass = captions.build_ass(words, {"caption_style": style, "caption_position": "top", "hook_overlay": True,
                                         "hook_seconds": 4.0}, 3.0, "Part 2")
        box = ink(ass, "Hook", 1.0)
        assert all(ink(ass, "Caption", t)[0] > box[1] for t in times), style
    # the biggest captions wrap to two lines above a 16:9 game and still stay under the apps' top bar
    words = [{"w": w, "start": 0.1 + 0.35 * k, "end": 0.4 + 0.35 * k}
             for k, w in enumerate("and then my sister laughed at the".split())]
    top = (1920 - 607.5) / 2
    ass = captions.build_ass(words, {"caption_style": "minimal", "caption_position": "above", "picture_top": top,
                                     "caption_size": 1.8, "hook_overlay": False}, 3.0, "")
    got = ink(ass, "Caption", 0.3)
    size = int(next(x for x in ass.splitlines() if x.startswith("Style: Caption,")).split(",")[2])
    assert got[1] - got[0] > 1.5 * size  # two lines
    assert 1920 * captions.POSITIONS["top"][1] < got[0] and got[1] < top, got


def _frame(path, t: float, scale: str = "") -> np.ndarray:
    vf = (scale + "," if scale else "") + "format=gray"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-vf", vf,
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).astype(float)


def _edges(a: np.ndarray) -> np.ndarray:
    return np.abs(np.diff(a, axis=1))[:-1, :] + np.abs(np.diff(a, axis=0))[:, :-1]


@needs_ffmpeg
@pytest.mark.slow
def test_a_story_clip_renders_the_whole_game_still_and_centred_with_the_captions_above_it(tmp_path, monkeypatch):
    """Real render of a 16:9 recording as a story clip: the picture in the 9:16 frame is the whole source frame,
    centred and unzoomed for the whole clip, and the captions are drawn above it, never over the gameplay."""
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import config
    from clipfoundry.pipeline import render
    from clipfoundry.pipeline.common import JobContext
    from clipfoundry.pipeline.ffmpeg_utils import probe
    from clipfoundry.studio import story_review

    src = make_video(tmp_path / "game.mp4", seconds=6.0, size="1280x720")
    meta = probe(src)
    words = [{"w": w, "start": 0.4 + 0.5 * k, "end": 0.8 + 0.5 * k}
             for k, w in enumerate("So my roommate keeps eating my food and I finally snapped.".split())]
    project = {"source_path": str(src), "dir": str(tmp_path / "proj"), "info": meta, "options": {}, **meta}
    edit = story_review.story_edit({}, {"start_ms": 0, "end_ms": 6000, "parts": 2})
    clip = {"id": "story-1", "start": 0.0, "end": 6.0, "hook": "Part 1", "edit": edit}
    settings = {**config.DEFAULT_SETTINGS, "encoder": "x264", "x264_preset": "ultrafast"}
    shown = render.render_clip(project, clip, words, settings, JobContext())
    bare = render.render_clip(project, {**clip, "hook": "", "edit": {**edit, "captions_enabled": False,
                                                                      "hook_overlay": False}},
                              words, settings, JobContext(), out_dir=tmp_path / "bare")
    assert shown["render_info"]["layout"] == "fit" and shown["render_info"]["mode"] == "center"
    top, height = 656, 607  # where the fitted 16:9 picture sits in the 1080x1920 frame
    for t in (0.6, 2.1, 3.6, 5.1):
        out = _frame(bare["output_path"], t).reshape(1920, 1080)
        sharp = np.nonzero(_edges(out).mean(axis=1) > 4)[0]  # the picture's rows: the fill around it is blurred
        assert abs(sharp.min() - top) <= 3 and abs(sharp.max() - (top + height)) <= 3, (t, sharp.min(), sharp.max())
        # the whole frame, not cropped, zoomed or moved: its edges line up with the source's, and a push-in of only
        # five percent would already lose them
        band = out[top + 6:top + height - 6]
        want = _frame(src, t, "scale=1080:607").reshape(607, 1080)[6:height - 6]
        pushed = _frame(src, t, "crop=iw/1.05:ih/1.05,scale=1080:607").reshape(607, 1080)[6:height - 6]
        same = np.corrcoef(_edges(band).ravel(), _edges(want).ravel())[0, 1]
        assert same > 0.7 and same > np.corrcoef(_edges(band).ravel(), _edges(pushed).ravel())[0, 1] + 0.2, t
        with_captions = _frame(shown["output_path"], t).reshape(1920, 1080)
        rows = np.nonzero((np.abs(with_captions - out) > 40).sum(axis=1) > 6)[0]
        assert len(rows) and rows.max() < top, (t, rows.min(), rows.max())  # captions above the gameplay
