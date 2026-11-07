"""Example videos the Brain measures (CF2-25 to CF2-27, plan side): the analyzer's cut, dissolve, fade, framing and
caption readings on synthetic frames, the honest method label, the durable job with its cache, the Example style with
the owner's corrections, precedence when it is used (project choice, chosen example, style, skills, examples that
always apply), avoid examples, project-only examples, reanalysis that never changes saved work, deletion, workspace
isolation and the routes. Real decoding of a real example is in test_studio_reference_render.py (slow).
"""
from __future__ import annotations

import numpy as np
import pytest

H = {"X-ClipFoundry": "1"}


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import jobs as studio_jobs

    db.init()
    ran: list[str] = []

    def submit(job_id: str) -> None:  # reference jobs run at once; other studio work is not needed here
        job = db.fetch("studio_jobs", job_id)
        if job and job["kind"] == "reference_analysis":
            ran.append(job_id)
            studio_jobs.run(job_id)

    monkeypatch.setattr(worker, "submit_studio", submit)
    return tmp_path


MEASURED = {
    "ranges": [{"start_ms": 0, "end_ms": 21000}], "seconds": 21.0,
    "shots": {"count": 14, "median_s": 1.5, "shortest_s": 1.45, "longest_s": 1.55, "first_s": 1.45},
    "joins": {"count": 13, "cut": 13, "dissolve": 0, "fade": 0, "times": [1.45 + 1.5 * k for k in range(13)]},
    "starts_black": False,
    "framing": {"width": 540, "height": 960, "ratio": 0.5625, "aspect": "9:16", "stills": 14, "letterbox": 0,
                "pillarbox": 0, "blurred": 0, "fit_share": 0.0, "evidence": []},
    "captions": {"stills": 14, "found": 11, "share": 0.79, "position": "bottom", "position_share": 1.0,
                 "center": 0.9, "height": 0.016, "scale": 0.028, "changing": True, "speech_share": 1.0,
                 "evidence": [0.7, 2.2]},
    "speech": {"source": "transcript", "segments": 6, "seconds": 15.5, "first_s": 0.6, "words_per_minute": 160,
               "median_pause_s": 0.7, "pauses": 5, "note": "", "spans": [(0.6, 2.8), (3.5, 6.1)]},
    "sound": {"seconds": 21.0, "level_db": -28.7, "peak_db": -19.0, "silences": [], "background_gap_db": -34.8,
              "gap_frames": 29, "under_speech": {"low": {"gap_db": -12.4, "speech_db": -24.2, "drop_db": 11.8}},
              "onsets": []},
    "brightness": 0.4,
}


def _fake_analysis(monkeypatch, calls: list | None = None, measured: dict | None = None):
    from clipfoundry.studio import reference_analysis as ra

    def analyze(path, probe, ranges, words=None, *, transcript_note="", cancelled=None, progress=None):
        if calls is not None:
            calls.append({"ranges": ranges, "words": words})
        m = measured or MEASURED
        return {"analyzer": ra.ANALYZER, "method": ra.METHOD, "measured": m,
                "coverage": {"ranges": m["ranges"], "frames_compared": 210, "stills": 14},
                "observations": ra.observations(m, [{"t": t, "kind": "cut"} for t in m["joins"]["times"]], [])}

    monkeypatch.setattr(ra, "analyze", analyze)
    from clipfoundry.studio import video_flow

    monkeypatch.setattr(video_flow, "transcript_words", lambda asset, settings, lease=None, cached_only=False:
                        [{"start": 0.6, "end": 0.9, "w": "we"}, {"start": 1.0, "end": 1.4, "w": "climbed."}])


def _video(tmp_path, n: int, workspace: str = "local", seconds: float = 21.0, sha: str = "") -> dict:
    from clipfoundry import db

    folder = tmp_path / f"assets-{workspace}-{n}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "original.mp4"
    path.write_bytes(b"x")
    return db.insert("assets", {"id": f"as-{workspace}-{n}", "workspace_id": workspace, "kind": "video",
                                "filename": f"example{n}.mp4", "sha256": sha or f"sha-{workspace}-{n}", "size": 1,
                                "path": str(path), "probe": {"duration": seconds, "has_audio": True,
                                                             "width": 540, "height": 960}})


# ------------------------------------------------------------------ the analyzer on synthetic frames
def _scan(dpix: list[float], luma: list[float] | None = None, hists=None) -> dict:
    n = len(dpix)
    hist = np.zeros((n, 48), dtype=np.float32)
    for i in range(n):  # a different colour histogram per "shot" so cuts and dissolves add up
        hist[i, (i // 15) % 48] = 1.0
    return {"times": np.arange(n) / 10.0, "luma": np.array(luma or [0.5] * n), "dpix": np.array(dpix),
            "dhist": np.array([0.0] + [0.5 if d > 0.09 else 0.05 for d in dpix[1:]]),
            "hists": hists if hists is not None else hist}


def test_cuts_dissolves_and_fades_are_told_apart_from_frame_changes():
    from clipfoundry.studio import reference_analysis as ra

    d = [0.0] + [0.01] * 59
    d[15] = 0.4  # a hard cut
    d[30:35] = [0.05, 0.05, 0.06, 0.05, 0.05]  # a dissolve over half a second
    luma = [0.5] * 60
    luma[44:47] = [0.01, 0.01, 0.01]  # a dip to black
    hists = np.zeros((60, 48), dtype=np.float32)
    hists[:30, 1] = 1.0
    hists[30:35, 1] = np.linspace(0.8, 0.2, 5)
    hists[30:35, 9] = np.linspace(0.2, 0.8, 5)
    hists[35:, 9] = 1.0
    joins = ra.find_joins(_scan(d, luma, hists))
    assert [j["kind"] for j in joins] == ["cut", "dissolve", "fade"]
    assert abs(joins[0]["t"] - 1.45) < 0.06 and abs(joins[2]["t"] - 4.5) < 0.15
    shots = ra.shots(joins, [(0.0, 6.0)])
    assert len(shots) == 4 and shots[0]["partial"] and shots[-1]["partial"]
    # camera movement alone (steady moderate change) is not a cut
    assert ra.find_joins(_scan([0.0] + [0.03 + 0.005 * (i % 3) for i in range(59)])) == []


def test_stills_cover_every_shot_and_long_shots_without_exceeding_the_bound():
    from clipfoundry.studio import reference_analysis as ra

    shots = [{"start": 0.0, "end": 1.5, "partial": True}, {"start": 1.5, "end": 40.0, "partial": False}]
    times = ra.pick_stills(shots)
    assert times[0] == pytest.approx(0.75) and len([t for t in times if t > 1.5]) == 5
    many = [{"start": k * 1.0, "end": k * 1.0 + 1.0, "partial": False} for k in range(1000)]
    assert len(ra.pick_stills(many)) == ra.MAX_STILLS


def test_framing_and_caption_lines_are_read_from_stills():
    from clipfoundry.studio import reference_analysis as ra

    rng = np.random.default_rng(3)
    base = np.clip(110 + rng.normal(0, 3, (568, 320)), 0, 255).astype(np.uint8)
    captioned = []
    for k in range(6):
        img = base.copy()
        y = 500
        for x in range(40 + 7 * k, 280, 9):  # light glyph strokes with dark outlines: a line of text
            img[y:y + 12, x:x + 2] = 250
            img[y:y + 12, x + 2:x + 4] = 10
        captioned.append((float(k), img))
    probe = {"width": 540, "height": 960}
    c = ra.captions(captioned, [(0.0, 10.0)], probe)
    assert c["position"] == "bottom" and c["share"] == 1.0 and c["changing"]
    assert 0.015 < c["height"] < 0.03
    static = [(float(k), captioned[0][1]) for k in range(6)]  # the same text every time: a logo, not captions
    assert ra.captions(static, [], probe)["changing"] is False
    assert ra.captions([(0.0, base)], [], probe)["found"] == 0
    barred = base.copy()
    barred[:80] = 0
    barred[-80:] = 0
    f = ra.framing([(0.0, barred), (1.0, barred)], probe)
    assert f["aspect"] == "9:16" and f["fit_share"] == 1.0
    assert ra.framing([(0.0, base)], {"width": 1000, "height": 1000})["aspect"] == "1:1"
    assert ra.caption_size(0.025) == "small" and ra.caption_size(0.028) == "medium" and \
        ra.caption_size(0.037) == "large"


def test_what_can_be_applied_follows_the_measurements_and_what_was_liked():
    from clipfoundry.studio import reference_analysis as ra

    apply, unsupported = ra.applicable(MEASURED, ["captions"])
    values = {a["field"]: a["value"] for a in apply}
    assert values["shot_length_s"] == 1.5 and values["pacing"] == "safe_cuts" and values["transition"] == "cut"
    assert values["caption_position"] == "bottom" and values["caption_size"] == "medium" and values["captions"]
    assert values["duck_music"] is True and values["duck_depth_db"] == 12 and values["aspect_ratio"] == "9:16"
    assert {a["field"] for a in apply if a["selected"]} == {"captions", "caption_position", "caption_size"}
    assert any("font" in u["text"] for u in unsupported) and any("pace" in u["text"] for u in unsupported)
    quiet = {**MEASURED, "sound": {**MEASURED["sound"], "background_gap_db": -70.0}}
    assert "duck_music" not in {a["field"] for a in ra.applicable(quiet, [])[0]}
    level = {**MEASURED, "sound": {**MEASURED["sound"], "under_speech": {"low": {"gap_db": -12, "speech_db": -12.5,
                                                                                  "drop_db": 0.5}}}}
    assert {a["field"]: a["value"] for a in ra.applicable(level, [])[0]}["duck_music"] is False


def test_observations_separate_measured_facts_from_estimates_with_playable_evidence():
    from clipfoundry.studio import reference_analysis as ra

    obs = {o["id"]: o for o in ra.observations(MEASURED, [{"t": t, "kind": "cut"} for t in
                                                          MEASURED["joins"]["times"]], [])}
    assert obs["shots"]["kind"] == "measured" and obs["shots"]["evidence"][0]["end_ms"] > 0
    assert obs["captions"]["kind"] == "estimate" and "no model read it" in obs["captions"]["text"]
    assert 0 < obs["captions"]["confidence"] <= 0.9
    assert obs["music"]["kind"] == "estimate" and "12 dB" in obs["music"]["text"]
    assert "No AI model" in ra.METHOD


def test_ranges_are_validated_and_bounded():
    from clipfoundry.studio import reference_analysis as ra

    assert ra.clean_ranges(None, 30) == [(0.0, 30)]
    assert ra.clean_ranges([{"start_ms": 5000, "end_ms": 9000}, {"start_ms": 0, "end_ms": 2000}], 30) == \
        [(0.0, 2.0), (5.0, 9.0)]
    for bad in ([{"start_ms": 0, "end_ms": 500}], [{"start_ms": 0, "end_ms": 40000}],
                [{"start_ms": 0, "end_ms": 5000}, {"start_ms": 4000, "end_ms": 8000}], [{"start": 1}]):
        with pytest.raises(ra.AnalysisError):
            ra.clean_ranges(bad, 30)
    with pytest.raises(ra.AnalysisError, match="Choose up to"):
        ra.clean_ranges(None, ra.MAX_ANALYZE_S + 60)


# ------------------------------------------------------------------ examples, styles and guidance
def test_an_example_is_analyzed_once_per_content_and_saved_as_a_style_with_corrections(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import reference, styles

    calls: list = []
    _fake_analysis(monkeypatch, calls)
    a = _video(env, 1)
    ref = reference.create("local", a["id"], {"likes": ["captions", "sound"], "note": "Love the captions"})
    assert ref["status"] == "queued"
    ref = reference.view(reference.get(ref["id"], "local"))
    assert ref["status"] == "ready" and ref["analysis_revision"] == 1 and len(calls) == 1
    an = ref["analysis"]
    assert "No AI model" in an["method"] and "No AI service is set up" in an["model_note"]
    assert calls[0]["words"]  # the transcript was used for speech timing
    chosen = {x["field"] for x in an["applicable"] if x["selected"]}
    assert chosen == {"captions", "caption_position", "caption_size", "duck_music", "duck_depth_db"}
    # the same file added again as another example (same content, same ranges) reuses the analysis
    again = reference.create("local", a["id"], {"title": "Again"})
    assert len(calls) == 1 and db.fetch("reference_analyses", again["id"], "reference_id")["reused_from"]
    # save the selection with one correction: smaller captions than measured
    values = {x["field"]: x["value"] for x in an["applicable"] if x["selected"]}
    values["caption_size"] = "small"
    saved = reference.save_style(ref["id"], "local", values=values, analysis_revision=1)
    style = saved["style"]
    assert style["source"] == "example" and style["reference_id"] == ref["id"] and style["revision"] == 1
    assert style["provenance"]["corrections"] == [{"field": "caption_size", "measured": "medium",
                                                   "chosen": "small"}]
    assert style["provenance"]["analysis_revision"] == 1 and "No AI model" in style["provenance"]["method"]
    assert styles.at_revision(style["id"], 1)["provenance"]["analysis_revision"] == 1
    assert not style["is_default"]  # an example never silently becomes the default style


def test_reanalysis_is_a_new_revision_and_never_changes_the_saved_style_or_a_made_project(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import clips_flow, reference

    _fake_analysis(monkeypatch)
    a = _video(env, 1)
    ref = reference.create("local", a["id"], {})
    reference.save_style(ref["id"], "local", values={"caption_position": "bottom"}, analysis_revision=1)
    made = clips_flow.prepare("local", mode="highlights", style_id="settings", reference_id=ref["id"])
    assert made["guidance"]["values"]["caption_position"] == "bottom"
    top = {**MEASURED, "captions": {**MEASURED["captions"], "position": "top"}}
    _fake_analysis(monkeypatch, measured=top)
    again = reference.reanalyze(ref["id"], "local", [{"start_ms": 1000, "end_ms": 9000}])
    assert again["analysis_revision"] == 2 and again["ranges"] == [{"start_ms": 1000, "end_ms": 9000}]
    assert {x["field"]: x["value"] for x in again["analysis"]["applicable"]}["caption_position"] == "top"
    assert again["style"]["values"] == {"caption_position": "bottom"} and again["style"]["revision"] == 1
    assert made["guidance"]["values"]["caption_position"] == "bottom"  # the frozen snapshot is unchanged
    with pytest.raises(reference.Conflict):  # saving from the older analysis the owner reviewed
        reference.save_style(ref["id"], "local", values={"caption_position": "top"}, analysis_revision=1)
    saved = reference.save_style(ref["id"], "local", values={"caption_position": "top"}, analysis_revision=2)
    assert saved["style"]["revision"] == 2
    assert db.fetch("styles", saved["style"]["id"])["provenance"]["analysis_revision"] == 2


def test_precedence_project_then_chosen_example_then_style_then_skills_then_examples_that_apply(env, monkeypatch):
    from clipfoundry.studio import clips_flow, reference, styles, video_flow

    _fake_analysis(monkeypatch)
    one, two = _video(env, 1), _video(env, 2, sha="other")
    chosen = reference.create("local", one["id"], {"title": "Trail vlog"})
    reference.save_style(chosen["id"], "local", values={"caption_position": "bottom", "layout": "fit",
                                                       "shot_length_s": 1.5, "duck_depth_db": 9.0},
                         analysis_revision=1)
    always = reference.create("local", two["id"], {"title": "House style", "scope": "all"})
    reference.save_style(always["id"], "local", values={"caption_position": "top", "caption_emphasis": True,
                                                       "tracking": "face"}, analysis_revision=1)
    saved = styles.create("local", "Mine", {"layout": "fill", "tracking": "center"}, ["highlights"])
    snap = clips_flow.prepare("local", mode="highlights", style_id=saved["id"], reference_id=chosen["id"],
                              choices={"caption_position": "middle"})["guidance"]
    by = {d["field"]: d for d in snap["decisions"]}
    assert by["caption_position"]["value"] == "middle" and by["caption_position"]["from"]["level"] == "project"
    assert [o["name"] for o in by["caption_position"]["overridden"]] == ["Example “Trail vlog”",
                                                                        "Example “House style”"]
    assert by["layout"]["value"] == "fit" and by["layout"]["from"]["level"] == "reference"
    assert by["layout"]["from"]["id"] == chosen["id"] and by["layout"]["from"]["analysis_revision"] == 1
    assert by["tracking"]["value"] == "center" and by["tracking"]["from"]["level"] == "style"
    assert by["caption_emphasis"]["from"]["level"] == "example"
    used = {(u["level"], u["id"]) for u in snap["used"]}
    assert ("reference", chosen["id"]) in used and ("example", always["id"]) in used
    # without choosing it, the house style applies to every project; the trail vlog only when chosen
    plain = clips_flow.prepare("local", mode="highlights", style_id="settings")["guidance"]
    assert {d["field"]: d["value"] for d in plain["decisions"]}["caption_position"] == "top"
    # restricted to Full stories, the house style stops applying to Highlights
    reference.update(always["id"], "local", {"scope": "modes", "modes": ["full_stories"]})
    plain = clips_flow.prepare("local", mode="highlights", style_id="settings")["guidance"]
    assert "caption_position" not in {d["field"] for d in plain["decisions"] if d["from"]["level"] != "settings"}
    # the full-video project uses the example's shot length and music dip in the actual rough cut
    v = _video(env, 3, seconds=12.0)
    project = video_flow.create("local", "local", name="Hike", asset_ids=[v["id"]], brief={}, style_id="settings",
                                remember={"enabled": False}, reference_id=chosen["id"])
    words = [{"start": s + k * 0.3, "end": s + k * 0.3 + 0.25, "w": w} for s, text in
             ((0.5, "we climbed early."), (2.6, "the ridge was icy."), (5.0, "then we ate lunch."),
              (8.4, "and walked down."))
             for k, w in enumerate(text.split())]
    plan = video_flow.rough_cut(project, video_flow._assets(project), {v["id"]: words})  # noqa: SLF001
    lengths = [(c["out_ms"] - c["in_ms"]) / 1000 for c in plan["clips"]]
    assert len(lengths) == 4 and max(lengths) < 2.0 and plan["ducking"]["depth_db"] == 9.0
    assert any("shots of about 1.5 s" in n for n in plan["notes"])
    assert {d["field"]: d["from"]["level"] for d in project["guidance"]["decisions"]}["shot_length_s"] == \
        "reference"
    # a project choice overrides the example's shot length (0 = keep each file whole)
    own = video_flow.create("local", "local", name="Hike 2", asset_ids=[v["id"]], brief={"shot_length_s": 0},
                            style_id="settings", remember={"enabled": False}, reference_id=chosen["id"])
    plan = video_flow.rough_cut(own, video_flow._assets(own), {v["id"]: words})  # noqa: SLF001
    assert len(plan["clips"]) == 1


def test_avoid_disabled_and_project_only_examples_are_never_applied_silently(env, monkeypatch):
    from clipfoundry.studio import clips_flow, reference

    _fake_analysis(monkeypatch)
    bad = reference.create("local", _video(env, 1)["id"], {"avoid": True, "scope": "all"})
    assert all(not x["selected"] for x in bad["analysis"]["applicable"]) if bad.get("analysis") else True
    with pytest.raises(reference.ReferenceError, match="avoid"):
        reference.save_style(bad["id"], "local", values={"layout": "fit"}, analysis_revision=1)
    with pytest.raises(clips_flow.FlowError, match="avoid"):
        clips_flow.prepare("local", mode="highlights", style_id="settings", reference_id=bad["id"])
    once = reference.create("local", _video(env, 2, sha="b")["id"], {"project_only": True, "scope": "all"})
    reference.save_style(once["id"], "local", values={"layout": "fit"}, analysis_revision=1)
    assert [r["id"] for r in reference.list_for("local")] == [bad["id"]]  # not listed in the Brain until kept
    plain = clips_flow.prepare("local", mode="highlights", style_id="settings")["guidance"]
    assert all(d["from"]["level"] == "settings" for d in plain["decisions"])
    chosen = clips_flow.prepare("local", mode="highlights", style_id="settings", reference_id=once["id"])
    assert chosen["guidance"]["values"]["layout"] == "fit"  # it works for the project it was added for
    kept = reference.update(once["id"], "local", {"project_only": False})
    assert kept["project_only"] is False
    plain = clips_flow.prepare("local", mode="highlights", style_id="settings")["guidance"]
    assert plain["values"]["layout"] == "fit"  # remembered, and set to apply to every project
    with pytest.raises(reference.ReferenceError):
        reference.update(once["id"], "local", {"project_only": True})
    reference.update(once["id"], "local", {"enabled": False})
    with pytest.raises(clips_flow.FlowError, match="disabled"):
        clips_flow.prepare("local", mode="highlights", style_id="settings", reference_id=once["id"])
    unsaved = reference.create("local", _video(env, 3, sha="c")["id"], {})
    with pytest.raises(clips_flow.FlowError, match="Save what you want"):
        clips_flow.prepare("local", mode="highlights", style_id="settings", reference_id=unsaved["id"])


def test_without_a_transcript_speech_is_estimated_and_said_so(env, monkeypatch):
    from clipfoundry.studio import reference, reference_analysis as ra, video_flow

    seen: list = []
    _fake_analysis(monkeypatch, seen)

    def no_model(asset, settings, lease=None, cached_only=False):
        raise RuntimeError("speech model not downloaded")

    monkeypatch.setattr(video_flow, "transcript_words", no_model)
    ref = reference.create("local", _video(env, 1)["id"], {})
    assert reference.get(ref["id"], "local")["status"] == "ready" and seen[0]["words"] is None
    # the cache key keeps measured-from-transcript and estimated analyses apart
    assert reference.cache_key("s", [(0, 1)], "transcript") != reference.cache_key("s", [(0, 1)], "estimate")
    from clipfoundry import db

    settings = {**db.get_settings(), "ai_provider": "anthropic", "anthropic_model": "some-model"}
    note = reference.view(reference.get(ref["id"], "local"), settings)["analysis"]["model_note"]
    assert "only sent text" in note and "did not watch or hear" in note
    assert ra.METHOD.startswith("Measured on this computer")


def test_cancel_failure_and_an_interrupted_analysis_resume(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.jobs import worker
    from clipfoundry.studio import jobs as studio_jobs, reference, reference_analysis as ra

    _fake_analysis(monkeypatch)
    waiting: list[str] = []
    monkeypatch.setattr(worker, "submit_studio", lambda job_id: waiting.append(job_id))  # "the app stops"
    ref = reference.create("local", _video(env, 1)["id"], {})
    assert reference.get(ref["id"], "local")["status"] == "queued"
    assert studio_jobs.recover() == 1  # after a restart the queued analysis is picked up again
    studio_jobs.run(waiting[-1])
    assert reference.get(ref["id"], "local")["status"] == "ready"
    again = reference.reanalyze(ref["id"], "local")
    out = reference.cancel(again["id"], "local")
    assert out["status"] == "canceled" and "previous analysis is still shown" in out["message"]
    assert out["analysis"]["revision"] == 1

    def broken(*a, **k):
        raise ra.AnalysisError("This file has no readable picture.")

    monkeypatch.setattr(ra, "analyze", broken)
    # the same file, ranges and analyzer reuse the finished analysis; a new range has to be measured
    same = reference.reanalyze(ref["id"], "local")
    studio_jobs.run(waiting[-1])
    assert reference.get(same["id"], "local")["analysis_revision"] == 2
    third = reference.reanalyze(ref["id"], "local", [{"start_ms": 0, "end_ms": 5000}])
    studio_jobs.run(waiting[-1])
    row = reference.get(third["id"], "local")
    assert row["status"] == "failed" and "no readable picture" in row["error"] and row["analysis_revision"] == 2
    assert db.fetch("studio_jobs", waiting[-1])["status"] == "failed"


def test_delete_keeps_or_removes_the_style_and_explains_the_effect(env, monkeypatch):
    from clipfoundry import db
    from clipfoundry.studio import reference

    _fake_analysis(monkeypatch)
    a = _video(env, 1)
    ref = reference.create("local", a["id"], {})
    style = reference.save_style(ref["id"], "local", values={"layout": "fit"}, analysis_revision=1)["style"]
    out = reference.delete(ref["id"], "local", keep_style=True)
    assert any("stays" in n for n in out["notes"]) and any("keep the choices" in n for n in out["notes"])
    assert db.fetch("styles", style["id"])["provenance"]["reference_deleted_at"]
    assert db.fetch("assets", a["id"])  # the file stays unless asked
    b = _video(env, 2, sha="b")
    ref = reference.create("local", b["id"], {})
    style = reference.save_style(ref["id"], "local", values={"layout": "fit"}, analysis_revision=1)["style"]
    out = reference.delete(ref["id"], "local", keep_style=False, delete_file=True)
    assert db.fetch("styles", style["id"]) is None and db.fetch("assets", b["id"]) is None
    assert not db.select("reference_analyses", "reference_id = ?", (ref["id"],))
    assert "file was deleted" in " ".join(out["notes"])


def test_examples_stay_inside_their_workspace(env, monkeypatch):
    from clipfoundry.cloud import middleware
    from clipfoundry.studio import reference

    _fake_analysis(monkeypatch)
    mine = reference.create("local", _video(env, 1)["id"], {"scope": "all"})
    reference.save_style(mine["id"], "local", values={"layout": "fit"}, analysis_revision=1)
    other = _video(env, 2, workspace="ws-other")
    with pytest.raises(reference.NotFound):
        reference.create("local", other["id"], {})
    with pytest.raises(reference.NotFound):
        reference.get(mine["id"], "ws-other")
    assert reference.applying("ws-other", "highlights") == []
    assert reference.list_for("ws-other") == []
    # the same content in another workspace is analyzed there, never copied across
    assert middleware.SECONDARY_BLOCKED.search("/api/studio/references")
    assert middleware.SECONDARY_BLOCKED.search(f"/api/studio/references/{mine['id']}/style")


def test_example_routes(env, monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry.api import app

    _fake_analysis(monkeypatch)
    a = _video(env, 1)
    with TestClient(app, base_url="http://127.0.0.1:8765") as api:
        r = api.post("/api/studio/references", json={"asset_id": a["id"], "likes": ["pacing"], "title": "Vlog"},
                     headers=H)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        got = api.get(f"/api/studio/references/{rid}").json()
        assert got["status"] == "ready" and got["media_url"] == f"/api/assets/{a['id']}/media"
        assert {x["field"] for x in got["analysis"]["applicable"] if x["selected"]} == \
            {"shot_length_s", "pacing", "transition"}
        bad = api.put(f"/api/studio/references/{rid}/style", json={"values": {"pacing": "wild"},
                                                                    "analysis_revision": 1}, headers=H)
        assert bad.status_code == 422
        ok = api.put(f"/api/studio/references/{rid}/style", json={"values": {"shot_length_s": 2.0},
                                                                   "analysis_revision": 1}, headers=H)
        assert ok.status_code == 200 and ok.json()["style"]["values"] == {"shot_length_s": 2.0}
        stale = api.put(f"/api/studio/references/{rid}/style", json={"values": {"shot_length_s": 3.0},
                                                                      "analysis_revision": 1,
                                                                      "style_revision": 0}, headers=H)
        assert stale.status_code == 409
        prev = api.get("/api/studio/guidance/preview", params={"mode": "full_video", "style_id": "settings",
                                                               "reference_id": rid}).json()
        assert {d["field"]: d["from"]["level"] for d in prev["decisions"]}["shot_length_s"] == "reference"
        assert api.patch(f"/api/studio/references/{rid}", json={"scope": "modes", "modes": []},
                         headers=H).status_code == 422
        assert api.get("/api/studio/references").json()[0]["id"] == rid
        gone = api.delete(f"/api/studio/references/{rid}", params={"keep_style": 0}, headers=H)
        assert gone.status_code == 200 and api.get(f"/api/studio/references/{rid}").status_code == 404
