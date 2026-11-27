"""Batch 5b, the picture (docs/clipforge/QC.md): flat cartoons and graphics are left as drawn by automatic colour,
dim whites are judged by the brightest channel, and every grade is tried on the recording's own pixels before a
render (the predicted check): a correction that would lose detail is eased step by step or left out, and a look
only as far as 30% of the owner's choice, with a note that says why.
"""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import numpy as np

from clipfoundry.pipeline import grade as G
from test_grade import H, W, _encode


def _disk(img: np.ndarray, cx: int, cy: int, r: int, colour) -> None:
    yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
    img[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = np.asarray(colour) / 255.0


def _cartoon(bg=(11, 16, 48), scale: float = 1.0) -> np.ndarray:
    """A flat cartoon frame like the animated shorts: a navy background, an orange and a teal character with black
    outlines and white eyes, a red title bar (display R'G'B' 0-1)."""
    img = np.zeros((H, W, 3))
    img[:] = np.asarray(bg) / 255.0
    for cx, col in ((105, (255, 122, 26)), (215, (31, 181, 168))):
        r = int(42 * scale)
        _disk(img, cx, 100, r + 2, (5, 5, 10))
        _disk(img, cx, 100, r, col)
        for ex in (-1, 1):
            _disk(img, cx + ex * int(14 * scale), 90, max(2, int(7 * scale)), (245, 245, 245))
            _disk(img, cx + ex * int(14 * scale), 90, max(1, int(3 * scale)), (10, 10, 20))
    img[10:10 + int(18 * scale), 15:15 + int(125 * scale)] = np.array((232, 48, 58)) / 255.0
    return img


def _real(img: np.ndarray) -> dict:
    """Statistics as for_footage measures them: the averaged frame, and its real pixels for the check."""
    return G.measure([img], None, img.reshape(-1, 3))


def _dim_photo() -> np.ndarray:
    """A dim, natural-looking picture: smooth gradients, a skin-ish patch and a little sensor noise."""
    y = np.linspace(0, 1, H)[:, None, None]
    x = np.linspace(0, 1, W)[None, :, None]
    img = (0.08 + 0.3 * y * np.array([0.9, 1.0, 1.1]) + 0.1 * x) * np.ones((H, W, 3))
    img[60:120, 140:200] = (0.42, 0.3, 0.24)
    return np.clip(img + np.random.default_rng(5).normal(0, 0.01, img.shape), 0, 1)


def _st(px: np.ndarray) -> dict:
    """Statistics holding only the predicted check's pixel sample, `px` (N x 3, 0-1)."""
    return {"check_px": base64.b64encode(np.round(np.clip(px, 0, 1) * 255).astype(np.uint8).tobytes()).decode()}


def _mix(top: np.ndarray, n: int = 16384) -> np.ndarray:
    """Half the pixels `top` (near white), half ordinary mid-tone colours."""
    mid = np.random.default_rng(2).uniform(0.2, 0.6, (n - len(top), 3))
    return np.vstack([top, mid])


def _ramp(lo: float, hi: float, n: int = 8192) -> np.ndarray:
    """A smooth near-white gradient (a sky, a lit wall): grey levels from `lo` to `hi`."""
    return np.random.default_rng(1).uniform(lo, hi, (n, 1)) * np.ones((1, 3))


# ---------------------------------------------------------------- flat cartoons and the white lift
def test_flat_cartoons_are_left_as_drawn_and_natural_pictures_still_corrected():
    for bg, scale in (((11, 16, 48), 1.0), ((11, 16, 48), 0.4), ((13, 18, 38), 0.4)):
        st = _real(_cartoon(bg, scale))
        assert st["graphic"] and st["top8"] >= G.GRAPHIC_TOP8
        g = G.correction(st)
        # before: the dark background read as underexposure and every drawn colour was lifted (up to 27 codes)
        assert not g.corrects() and g.notes == ["Flat colours (a cartoon or graphics): left as drawn"]
    rng = np.random.default_rng(8)
    dim = _real(_dim_photo())
    # a dark night shot and a talking head against a plain wall: few colours once averaged, but a camera's noise
    # spreads the real pixels (the first version of this test, on averaged frames, took both for drawings)
    y = np.linspace(0, 1, H)[:, None, None]
    night = np.clip(0.04 + 0.05 * y + rng.normal(0, 2 / 255, (H, W, 3)), 0, 1)
    wall = np.clip(np.full((H, W, 3), (0.62, 0.58, 0.52)) * (0.9 + 0.1 * y) + rng.normal(0, 2 / 255, (H, W, 3)), 0, 1)
    wall[50:150, 120:200] = (0.75, 0.55, 0.45)
    for st in (dim, _real(night), _real(wall)):
        assert not st["graphic"] and st["top8"] < 0.5
    g = G.correction(dim)
    assert g.corrects() and (g.gain > 1 or g.gamma < 1)  # real dim footage keeps its brightening
    assert G.correction(_real(night)).corrects()
    assert not G.measure([_cartoon()])["graphic"]  # without its real pixels nothing is taken for a drawing


def test_dim_whites_are_judged_by_the_brightest_channel():
    st = {"usable": 0.5, "skin": 0.0, "p005": 0.02, "p05": 0.05, "p50": 0.4, "p95": 0.55, "p995": 0.6,
          "chroma": 0.1}
    # saturated colours: dim in brightness, but one channel is already at full scale; lifting would clip them
    vivid = G.correction({**st, "p995_max": 0.98})
    assert vivid.gain == 1.0 and not any(n.startswith("Brightest parts lifted") for n in vivid.notes)
    dull = G.correction({**st, "p995_max": 0.62})
    assert dull.gain == min(G.WHITE_GAIN_MAX, G.WHITE_TO / 0.62) and "Brightest parts lifted toward white" in dull.notes
    # deepening washed-out blacks keeps the brightest channel where it was, too
    hazy = G.correction({**st, "p005": 0.16, "p995": 0.7, "p995_max": 0.97})
    assert hazy.black > 0 and (0.97 - hazy.black) * hazy.gain <= 0.97 + 1e-9


# ---------------------------------------------------------------- the predicted check
def test_the_pixel_sample_is_kept_with_the_statistics_and_read_back():
    frame = _dim_photo()
    px = frame.reshape(-1, 3)
    st = G.measure([frame], None, px)
    back = G.check_pixels(st)
    assert back is not None and len(back) == min(len(px), G.CHECK_PIXELS)
    assert np.abs(back - px[::max(1, len(px) // G.CHECK_PIXELS)][:len(back)]).max() <= 0.5 / 255 + 1e-9
    assert len(st["check_px"]) < 90_000  # about 64 KB as text, kept in the measurement's cache
    assert G.check_pixels(None) is None and G.check_pixels({"check_px": "not base64!"}) is None
    g = G.Grade(gain=1.4, notes=["Brightest parts lifted toward white"])
    assert G.guard(g, {"p50": 0.4}) is g  # measured before the sample existed: unchanged


def test_a_correction_that_would_clip_is_eased_or_left_out_and_says_why(monkeypatch):
    st = _st(_mix(_ramp(0.8, 0.96)))
    notes = ["Brightest parts lifted toward white", "A little contrast added (the picture was flat)"]
    g = G.Grade(gain=1.3, s_curve=0.15, notes=notes)
    assert G.check_grade(G.check_pixels(st), g)["clip"] > G.CHECK_CLIP[1]
    eased = G.guard(g, st)
    assert g.gain == 1.3 and len(g.notes) == 2  # the grade given is not changed
    assert 1.0 <= eased.gain < 1.3 and G.check_grade(G.check_pixels(st), eased)["clip"] <= G.CHECK_CLIP[1]
    assert eased.notes[-1] == "Colour correction eased: it would have lost detail in the brightest parts"
    assert any(n.startswith("Brightest parts lifted") for n in eased.notes) == (eased.gain > 1.0)
    # nothing left to ease: no correction at all, and its step notes go with it
    monkeypatch.setattr(G, "CHECK_TRIES", 0)
    out = G.guard(g, st)
    assert not out.corrects()
    assert out.notes == ["Colour correction left out: it would have lost detail in the brightest parts"]
    # an ordinary correction on an ordinary picture is left exactly as it is
    fine = G.Grade(gain=1.05, notes=["Brightest parts lifted toward white"])
    kept = G.guard(fine, _st(np.random.default_rng(4).uniform(0.05, 0.85, (16384, 3))))
    assert kept.gain == 1.05 and kept.notes == fine.notes


def test_easing_everything_half_way_keeps_the_white_balance_note_true():
    g = G.Grade(wb=(1.18, 0.97, 0.85), notes=["White balance: a blue cast reduced (70% of the measured cast)"])
    G._ease(g, "clip")  # nothing else to ease: every setting half way
    assert np.allclose(g.wb, (1.09, 0.985, 0.925))
    assert g.notes == ["White balance: a blue cast reduced (35% of the measured cast)"]


def test_darker_or_brighter_colours_are_not_washed_out():
    rng = np.random.default_rng(6)
    hues = np.array([[0.9, 0.2, 0.1], [0.1, 0.7, 0.2], [0.15, 0.25, 0.9], [0.85, 0.8, 0.1]])
    px = hues[rng.integers(0, 4, 16384)] * rng.uniform(0.5, 1.0, (16384, 1))
    # mid-tones darkened or brightened change brightness, not colourfulness (the old measure counted them)
    for g in (G.Grade(gamma=1.2), G.Grade(gamma=0.85), G.Grade(black=0.04, gain=1.04)):
        assert G.check_grade(px, g)["sat"] < G.CHECK_SAT[0]


def test_a_look_is_eased_only_where_it_would_lose_detail(monkeypatch):
    gradient = _st(_mix(_ramp(0.8, 0.97)))
    flat_white = _st(_mix(np.full((8192, 3), 0.95)))
    look = G.Grade(look="teal_orange", strength=1.0)
    eased = G.guard(look, gradient)
    assert eased.strength in (0.6, 0.3) and look.strength == 1.0
    assert eased.notes == [f"The Teal and orange look eased to {int(eased.strength * 100)}%: at 100% it would have "
                           "lost detail in the brightest parts"]
    # a flat white area (a cartoon's sky, a slide) is made all one level: no detail is lost there
    assert G.guard(look, flat_white).strength == 1.0
    # looks that change nothing harmful here are untouched
    for name in ("film", "moody", "vintage", "mono"):
        assert G.guard(G.Grade(look=name), gradient).strength == 1.0
    # never below 30% of what the owner chose, however much it would still lose
    dark = {"clip": 0, "crush": 0.5, "sat": 0, "slope": 0}
    monkeypatch.setattr(G, "check_grade", lambda px, g, part="correction": dark)
    floor = G.guard(G.Grade(look="moody", strength=0.5), gradient)
    assert abs(floor.strength - 0.15) < 1e-9
    assert floor.notes == ["The Moody look eased to 15%: at 50% it would have lost detail in the darkest parts"]


def test_a_cartoon_recording_is_measured_and_rendered_as_drawn(tmp_path):
    src = _encode(_cartoon(), tmp_path / "cartoon.mp4")
    g, st = G.for_footage(str(src), [(0, 1)], {}, cache=tmp_path / "grade.json")
    assert st["graphic"] and st.get("check_px") and not g.corrects() and not g.active()
    assert g.notes == ["Flat colours (a cartoon or graphics): left as drawn"]
    colour = G.source_colour(src)
    vf_plain = f"scale={G.to_rgb_chain(colour, H)},format=rgb24"
    vf_graded = G.rgb_filters(colour, g, "", tmp_path, H) + ",format=rgb24"

    def frame(vf):
        out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-frames:v", "1", "-vf", vf, "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, cwd=tmp_path).stdout
        return np.frombuffer(out, np.uint8).reshape(H, W, 3).astype(float)

    assert np.abs(frame(vf_graded) - frame(vf_plain)).max() <= 1
    # with a look chosen, the look still applies (it is the owner's choice) and is checked on the same pixels
    warm, _ = G.for_footage(str(src), [(0, 1)], {"look": "warm"}, cache=tmp_path / "grade.json")
    assert warm.active() and warm.look == "warm" and warm.strength == 1.0


def test_the_full_video_engine_checks_corrections_before_matching_and_everything_after(monkeypatch, tmp_path):
    from clipfoundry.studio import engine

    calls = []
    skin = {"a": {"skin": 0.1, "px": [0.51, 0.4, 0.3]}, "b": {"skin": 0.1, "px": [0.52, 0.4, 0.3]},
            "slide": {"skin": 1.0, "graphic": True, "px": [0.9, 0.7, 0.55]}}

    def fake_for_footage(path, spans, opts, **kw):
        calls.append(("measure", kw.get("guarded")))
        return G.Grade(), skin[Path(path).stem]

    def fake_match(g, mine, ref):
        calls.append(("match", mine["id"]))
        return g

    monkeypatch.setattr(G, "for_footage", fake_for_footage)
    monkeypatch.setattr(G, "corrected_stats", lambda st, g: {"p50": 0.4, "cb": 0.0, "cr": 0.0, "id": st["px"][0]})
    monkeypatch.setattr(G, "match", fake_match)
    monkeypatch.setattr(G, "guard", lambda g, st, look=True: calls.append(("guard", look)) or g)
    ids = ("a", "b", "slide")
    clips = [{"id": f"c{i}", "asset_id": a, "kind": "video", "in_ms": 0, "out_ms": 1000 * (i + 1), "include": True}
             for i, a in enumerate(ids)]  # the slide plays longest: it would be the reference
    plan = {"clips": clips, "color": {**engine.default_color({}), "match": True}}
    assets = {a: {"id": a, "kind": "video", "path": str(tmp_path / f"{a}.mp4"), "probe": {}} for a in ids}
    out = engine.grades(plan, assets, tmp_path)
    assert set(out) == set(ids)
    assert [c for c in calls if c[0] == "measure"] == [("measure", False)] * 3  # not checked inside the measuring
    kinds = [c[0] for c in calls]
    first, last = kinds.index("match"), len(kinds) - 1 - kinds[::-1].index("match")
    assert calls[3:6] == [("guard", False)] * 3 and kinds[:first].count("guard") == 3  # corrections first...
    assert [c for c in calls[last + 1:]] == [("guard", True)] * 3  # ...then everything, matching included
    # a cartoon or a slide is neither matched nor the reference, whatever its colours look like to the skin finder
    assert [c[1] for c in calls if c[0] == "match"] == [0.51]  # only "a", matched to "b" (now the reference)


def test_a_look_alone_is_checked_and_a_failed_sample_is_not_kept(monkeypatch, tmp_path):
    src = _encode(_dim_photo(), tmp_path / "dim.mp4")
    off = {"auto_color": False, "clean_picture": False, "look": "warm"}
    g, st = G.for_footage(str(src), [(0, 1)], off)
    assert st is not None and G.check_pixels(st) is not None  # measured for the look alone
    assert not G.for_footage(str(src), [(0, 1)], {"auto_color": False, "clean_picture": False})[1]  # nothing to do
    cache = tmp_path / "grade.json"
    monkeypatch.setattr(G, "check_sample", lambda *a, **k: None)  # a read that failed or timed out
    g, st = G.for_footage(str(src), [(0, 1)], {}, cache=cache)
    assert st and not st.get("check_px") and not cache.exists()  # used for this render, not kept
    monkeypatch.undo()
    g, st = G.for_footage(str(src), [(0, 1)], {}, cache=cache)
    assert st.get("check_px") and cache.exists()  # measured again next time, with its sample
