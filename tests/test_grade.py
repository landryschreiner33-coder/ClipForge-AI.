"""Colour (pipeline/grade.py): phone HDR to normal video, automatic correction per recording (white balance, levels,
contrast, colour), matching recordings, looks, noise, the colour table and the filters that apply it, the choices'
checks in Settings, the editor and edit requests. The FFmpeg checks use small synthetic pictures with a known cast.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from clipfoundry.pipeline import grade as G

W, H = 320, 180


def _linear(x):
    return np.clip(x, 0, 1) ** 2.4


def _display(x):
    return np.clip(x, 0, 1) ** (1 / 2.4)


def _scene(cast=(1.0, 1.0, 1.0)) -> np.ndarray:
    """A picture of grey blocks (left) and muted colour patches (right), with a white balance `cast` applied in
    linear light (gains per channel), as display R'G'B' 0-1."""
    img = np.zeros((H, W, 3))
    for k, v in enumerate(np.linspace(0.12, 0.9, 8)):
        img[:, k * 20:(k + 1) * 20] = v
    colours = [(0.6, 0.35, 0.3), (0.35, 0.55, 0.35), (0.3, 0.4, 0.6), (0.65, 0.6, 0.35), (0.5, 0.5, 0.5)]
    for k, c in enumerate(colours):
        img[k * 36:(k + 1) * 36, 160:] = c
    return _display(_linear(img) * np.asarray(cast))


def _grey_cast(rgb: np.ndarray) -> float:
    """How far the grey blocks (left half) are from neutral: mean |Cb| + |Cr| of display values."""
    left = rgb[:, :150].reshape(-1, 3)
    _, cb, cr = G._ycc(left)
    return float(np.abs(cb).mean() + np.abs(cr).mean())


def _encode(frame: np.ndarray, path: Path, seconds: float = 1.0) -> Path:
    raw = (np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()
    n = int(seconds * 10)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "10",
                    "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264",
                    "-crf", "10", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    str(path)], input=raw * n, check=True)
    return path


def _hlg_clip(path: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=10:d=1",
                    "-vf", "format=yuv420p10le", "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-crf", "8",
                    "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
                    str(path)], check=True)
    return path


def _frame(path: Path, vf: str, cwd: Path, fmt: str = "rgb48le") -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-vf", vf, "-f", "rawvideo",
                          "-pix_fmt", fmt, "-"], check=True, capture_output=True, cwd=cwd).stdout
    if fmt == "rgb48le":
        return np.frombuffer(out, "<u2").reshape(H, W, 3) / 65535.0
    return np.frombuffer(out, np.uint8).reshape(H, W, 3) / 255.0


# ---------------------------------------------------------------- HDR
def test_phone_hdr_becomes_normal_video_with_reference_white_bright_and_order_kept():
    ramp = np.stack([np.linspace(0, 1, 41)] * 3, axis=1)
    for kind in ("hlg", "pq"):
        sdr = G.to_sdr(ramp, kind)[:, 0]
        assert sdr[0] == 0 and np.all(np.diff(sdr) >= 0) and sdr.max() <= 1.0  # black stays black, no reversals
    # BT.2408 reference white (HLG 75 %, PQ 203 nits) lands as a bright, not clipped, white
    assert 0.8 < G.to_sdr(np.array([[0.75] * 3]), "hlg")[0, 0] < 0.9
    assert 0.8 < G.to_sdr(np.array([[0.5806] * 3]), "pq")[0, 0] < 0.9
    # a saturated BT.2020 green outside BT.709 comes back inside, still green
    green = G.apply(np.array([[0.2, 0.8, 0.2]]), G.Grade(hdr="hlg"))[0]
    assert green[1] > green[0] + 0.3 and green[1] > green[2] + 0.3 and np.all((green >= 0) & (green <= 1))


def test_reading_a_file_s_colour_tags():
    assert G.hdr_kind({"transfer": "arib-std-b67"}) == "hlg"
    assert G.hdr_kind({"transfer": "smpte2084"}) == "pq"
    assert G.hdr_kind({"transfer": "bt709"}) is None and G.hdr_kind({}) is None
    # untagged HD video is BT.709 (FFmpeg alone would read it as BT.601); small untagged video stays BT.601
    assert G.input_matrix({}, 1080) == "bt709" and G.input_matrix({}, 480) == "bt601"
    assert G.input_matrix({"matrix": "bt2020nc"}) == "bt2020"
    assert G.input_range({"range": "pc"}) == "pc" and G.input_range({}) == "tv"


def test_hlg_file_through_ffmpeg_matches_the_colour_math(tmp_path):
    src = _hlg_clip(tmp_path / "hlg.mp4")
    colour = G.source_colour(src)
    assert G.hdr_kind(colour) == "hlg"
    g, _ = G.for_footage(str(src), [(0, 1)], {"auto_color": False, "clean_picture": False})
    assert g.hdr == "hlg" and "HDR phone video (HLG)" in g.notes[0]
    # what the renderer does (decode -> correct matrix -> 16-bit RGB -> colour table) against numpy on the same pixels
    made = _frame(src, G.rgb_filters(colour, g, "", tmp_path, H) + ",format=rgb48le", tmp_path)
    # (decoded the same way, to 16-bit planar RGB: swscale's packed-RGB path upsamples colour edges differently)
    plain = _frame(src, f"scale={G.to_rgb_chain(colour, H)},format=gbrp16le,format=rgb48le", tmp_path)
    want = G.apply(plain.reshape(-1, 3), g).reshape(H, W, 3)
    assert np.abs(made - want).mean() * 255 < 0.5 and np.percentile(np.abs(made - want), 99) * 255 < 2
    # the full-video path leaves tagged BT.709 4:2:0 with the same average colour
    out = tmp_path / "sdr.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", G.yuv_filters(colour, g, "", tmp_path, H),
                    "-c:v", "libx264", "-crf", "10", str(out)], check=True, cwd=tmp_path)
    tags = G.source_colour(out)
    assert (tags["transfer"], tags["primaries"], tags["matrix"]) == ("bt709", "bt709", "bt709")
    back = _frame(out, "scale=in_color_matrix=bt709:in_range=tv,format=rgb48le", tmp_path)
    assert np.abs(back.mean(axis=(0, 1)) - want.mean(axis=(0, 1))).max() * 255 < 2.0


# ---------------------------------------------------------------- automatic correction
def _stats(rgb: np.ndarray, noise: float | None = None) -> dict:
    crops = [np.full((360, 640), 128.0)] if noise is None else None
    st = G.measure([rgb], crops)
    if noise is not None:
        st["noise"] = noise
    return st


def test_a_colour_cast_is_reduced_and_a_neutral_picture_left_alone():
    blue = _scene((0.85, 1.0, 1.2))
    g = G.correction(_stats(blue))
    assert g.wb[2] < 1 < g.wb[0] and any("White balance" in n for n in g.notes)
    assert all(G.WB_CLAMP[0] <= v <= G.WB_CLAMP[1] for v in g.wb)
    fixed = G.apply(blue.reshape(-1, 3), g).reshape(blue.shape)
    assert _grey_cast(fixed) < 0.6 * _grey_cast(blue)
    neutral = G.correction(_stats(_scene()))
    assert neutral.wb == (1.0, 1.0, 1.0) and not any("White balance" in n for n in neutral.notes)


def test_deliberate_colours_and_screen_recordings_keep_their_colour():
    st = {"usable": 0.5, "skin": 0.0, "p005": 0.02, "p05": 0.06, "p50": 0.4, "p95": 0.9, "p995": 0.97, "chroma": 0.1}
    sunset = {**st, "grey": [0.5, 0.3, 0.1], "cast": 30.0, "cast_agree": 2.0}
    g = G.correction(sunset)
    assert g.wb == (1.0, 1.0, 1.0) and any("left alone" in n for n in g.notes)
    disagree = {**st, "grey": [0.42, 0.4, 0.3], "cast": 6.0, "cast_agree": 12.0}  # greys and highlights disagree
    assert G.correction(disagree).wb == (1.0, 1.0, 1.0)
    invisible = {**st, "grey": [0.401, 0.4, 0.398], "cast": 0.4, "cast_agree": 1.0}
    assert G.correction(invisible).wb == (1.0, 1.0, 1.0) and not G.correction(invisible).notes
    mild = {**st, "grey": [0.42, 0.4, 0.34], "cast": 5.0, "cast_agree": 1.0}
    person, screen = G.correction(mild), G.correction(mild, screen=True)
    assert person.wb[2] > 1 > person.wb[0]  # a warm cast: less red, more blue
    assert abs(screen.wb[2] - 1) < abs(person.wb[2] - 1)  # a game's colours are only half corrected


def test_a_well_exposed_colourful_picture_is_left_almost_alone():
    # a blue sky over green grass and a yellow robot (the lighthouse picture): colourful, not cast, well exposed
    pic = Path(__file__).resolve().parents[1] / "frontend" / "public" / "looks" / "cartoon3d.jpg"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(pic), "-vf", "scale=256:456,format=rgb48le", "-f",
                          "rawvideo", "-"], check=True, capture_output=True).stdout
    img = np.frombuffer(raw, "<u2").reshape(-1, 3) / 65535.0
    g = G.correction(G.measure([img.reshape(456, 256, 3)]))
    assert g.wb == (1.0, 1.0, 1.0)  # a blue sky is not a blue cast
    assert np.abs(G.apply(img, g) - img).mean() * 255 < 5


def test_washed_out_flat_and_dark_pictures_get_levels_contrast_and_at_most_half_a_stop():
    flat = {"usable": 0.5, "skin": 0.0, "p005": 0.14, "p05": 0.2, "p50": 0.42, "p95": 0.6, "p995": 0.72,
            "chroma": 0.02}
    g = G.correction(flat)
    assert g.black > 0 and g.gain > 1 and g.s_curve > 0 and g.vibrance > 0
    assert g.black <= G.BLACK_MAX and g.gain <= G.WHITE_GAIN_MAX
    # a lifted black comes off each channel (the inverse of haze); gain and contrast then change brightness, not
    # colourfulness: a stretched colour keeps the saturation it has without the haze
    orange = np.array([[0.6, 0.4, 0.25]])
    out = G.apply(orange, G.Grade(black=0.05, gain=1.2, s_curve=0.15))[0]
    assert abs(out[0] / out[2] - 0.55 / 0.20) < 0.05 * 0.55 / 0.20
    # a deep blue (little brightness) is not crushed by the black offset
    blue = G.apply(np.array([[0.05, 0.05, 0.95]]), G.Grade(black=0.05, gain=1.0556))[0]
    assert blue[2] > 0.9 and blue[0] < 0.02
    good = {"usable": 0.5, "skin": 0.0, "p005": 0.03, "p05": 0.08, "p50": 0.45, "p95": 0.85, "p995": 0.95,
            "chroma": 0.1}
    assert not G.correction(good).corrects() and not G.correction(good).notes  # nothing to fix: nothing changes
    dark = {"usable": 0.5, "skin": 0.0, "p005": 0.0, "p05": 0.01, "p50": 0.12, "p95": 0.8, "p995": 0.95,
            "chroma": 0.1}
    d = G.correction(dark)
    after = (0.12 * d.gain) ** d.gamma
    assert d.gamma < 1 and np.log2(after ** 2.4 / 0.12 ** 2.4) <= G.MAX_STOPS + 1e-6


def test_skin_tones_keep_their_colour_when_colour_is_brought_back():
    skin = np.array([[0.78, 0.57, 0.47]])
    dull_blue = np.array([[0.42, 0.46, 0.55]])
    g = G.Grade(vibrance=0.2)
    assert np.abs(G.apply(skin, g) - skin).max() < 0.02
    out = G.apply(dull_blue, g)
    assert (out[0, 2] - out[0, 0]) > (dull_blue[0, 2] - dull_blue[0, 0]) + 0.01


def test_recordings_are_matched_toward_the_main_one_within_limits():
    warm = _stats(_scene((1.12, 1.0, 0.88)))
    neutral = _stats(_scene())
    g = G.Grade()
    mine, ref = G.corrected_stats(warm, g), G.corrected_stats(neutral, G.Grade())
    G.match(g, mine, ref)
    assert g.match_cb > 0 and g.match_cr < 0  # bluer and less red: toward the neutral recording
    assert abs(g.match_cb) <= G.MATCH_CHROMA_MAX and abs(g.match_cr) <= G.MATCH_CHROMA_MAX
    assert G.MATCH_GAMMA[0] <= g.match_gamma <= G.MATCH_GAMMA[1] and "Matched" in g.notes[-1]
    again = G.Grade()
    G.match(again, ref, ref)
    assert not again.corrects() and not again.notes  # the same colours: nothing changes


# ---------------------------------------------------------------- looks and the table
def test_looks_their_strength_and_the_untouched_default():
    rng = np.random.default_rng(3)
    px = rng.uniform(0.05, 0.95, (3000, 3))
    assert np.abs(G.apply(px, G.Grade()) - px).max() < 1e-9 and not G.Grade().active()
    mono = G.apply(px, G.Grade(look="mono"))
    assert np.abs(mono[:, 0] - mono[:, 1]).max() < 1e-6 and np.abs(mono[:, 1] - mono[:, 2]).max() < 1e-6
    assert np.abs(G.apply(px, G.Grade(look="film", strength=0.0)) - px).max() < 1e-9
    full = np.abs(G.apply(px, G.Grade(look="warm")) - px).mean()
    half = np.abs(G.apply(px, G.Grade(look="warm", strength=0.5)) - px).mean()
    assert 0.35 * full < half < 0.65 * full
    warm = G.apply(np.array([[0.5, 0.5, 0.5]]), G.Grade(look="warm"))[0]
    cool = G.apply(np.array([[0.5, 0.5, 0.5]]), G.Grade(look="cool"))[0]
    assert warm[0] > warm[2] and cool[2] > cool[0]
    for name in G.LOOKS:
        out = G.apply(px, G.Grade(look=name))
        assert np.all((out >= 0) & (out <= 1)) and set(G.LOOKS) == set(G.LOOK_WORDS)


def test_colour_table_is_made_once_per_grade_and_named_by_it(tmp_path):
    g = G.Grade(look="film", strength=0.6)
    text = G.cube_text(g, size=5)
    rows = [r for r in text.splitlines() if r and r[0].isdigit()]
    assert "LUT_3D_SIZE 5" in text and len(rows) == 125
    assert [float(v) for v in rows[0].split()] == pytest.approx(list(G.apply(np.zeros((1, 3)), g)[0]), abs=1e-6)
    a = G.lut_file(g)
    mtime = a.stat().st_mtime_ns
    assert G.lut_file(G.Grade(look="film", strength=0.6)) == a and a.stat().st_mtime_ns == mtime
    assert G.lut_file(G.Grade(look="film", strength=0.7)) != a
    assert G.Grade(look="film", notes=["x"]).key() == G.Grade(look="film").key()  # notes never change the table
    assert G.lut_filter(G.Grade(), tmp_path) == ""
    assert G.lut_filter(g, tmp_path).startswith("lut3d=file=") and "interp=tetrahedral" in G.lut_filter(g, tmp_path)
    plain = G.yuv_filters({}, G.Grade(), "", tmp_path, 1080)
    assert "lut3d" not in plain and "in_color_matrix=bt709" in plain and "colorspace=bt709" in plain
    assert G.Grade.from_json(g.to_json()).key() == g.key()


# ---------------------------------------------------------------- noise
def test_noise_is_measured_on_flat_areas_and_cleaned_only_when_visible():
    rng = np.random.default_rng(7)
    ramp = np.tile(np.linspace(30, 220, 640), (360, 1))
    texture = ramp + 40 * (((np.arange(640) // 8) % 2)[None, :] * ((np.arange(360) // 8) % 2)[:, None])
    texture[:, :320] = ramp[:, :320]  # half the picture is flat, so the flattest tiles see only the noise
    assert G.noise_sigma(texture) < 1.0
    noisy = texture + rng.normal(0, 4.0, texture.shape)
    assert 3.0 < G.noise_sigma(noisy) < 5.0
    assert G.denoise_filter(1.0) == "" and G.denoise_filter(None) == ""
    assert G.denoise_filter(2.5).startswith("atadenoise")
    assert G.denoise_filter(30).startswith("fftdnoiz=sigma=10.0")  # capped
    assert G.denoise_for({"noise": 6}, {"clean_picture": False}) == ""
    assert G.denoise_for({"noise": 6}, {}).startswith("fftdnoiz")


# ---------------------------------------------------------------- a real recording, measured and corrected
def test_a_recording_with_a_cast_is_measured_once_and_corrected_through_ffmpeg(tmp_path):
    src = _encode(_scene((0.85, 1.0, 1.2)), tmp_path / "blue.mp4")
    cache = tmp_path / "grade.json"
    g, stats = G.for_footage(str(src), [(0, 1)], {}, cache=cache)
    assert cache.is_file() and stats["pixels"] > 0 and g.wb[2] < 1
    calls = []
    real = G.sample
    G.sample = lambda *a, **k: calls.append(1) or real(*a, **k)
    try:
        again, _ = G.for_footage(str(src), [(0, 1)], {}, cache=cache)
    finally:
        G.sample = real
    assert not calls and again.key() == g.key()  # the measurement is reused
    colour = G.source_colour(src)
    before = _frame(src, f"scale={G.to_rgb_chain(colour, H)},format=rgb48le", tmp_path)
    after = _frame(src, G.rgb_filters(colour, g, "", tmp_path, H) + ",format=rgb48le", tmp_path)
    assert _grey_cast(after) < 0.6 * _grey_cast(before)
    off, _ = G.for_footage(str(src), [(0, 1)], {"auto_color": False, "look": "mono"}, cache=cache)
    assert not off.corrects() and off.look == "mono" and off.active()


# ---------------------------------------------------------------- the choices
def test_settings_editor_and_engine_check_the_colour_choices():
    from clipfoundry import config
    from clipfoundry.studio import engine, video_flow

    s = config.validate_settings({"look": "laser", "look_strength": 180, "auto_color": False})
    assert "look" not in s and s["look_strength"] == 100 and s["auto_color"] is False
    assert config.DEFAULT_SETTINGS["auto_color"] is True and config.DEFAULT_SETTINGS["look"] == "natural"
    from clipfoundry.fullcloud import worker_api  # a Full Cloud job carries the owner's colour choices
    assert {"auto_color", "look", "look_strength", "clean_picture"} <= set(worker_api.SETTING_KEYS)
    assert engine.default_color({"look": "film", "look_strength": 40, "clean_picture": False}) == {
        "auto": True, "match": True, "look": "film", "strength": 40, "clean": False, "steady": True}
    old = engine.color_options({})  # a plan made before colour existed: only phone HDR is converted
    assert old["auto_color"] is False and old["clean_picture"] is False and old["look"] == "natural"
    bad = engine.validate({"color": {"look": "laser", "strength": 400, "auto": "yes"}}, {})
    assert "Unknown look." in bad and any("strength" in p for p in bad) and any("on or off" in p for p in bad)
    p = {"color": engine.default_color({})}
    assert video_flow._set_color(p, "look", "teal_orange") == "Look: Teal and orange"
    assert video_flow._set_color(p, "look_strength", 55) == "Look strength 55 %"
    assert video_flow._set_color(p, "clean_picture", False).endswith("off")
    assert p["color"] == {"auto": True, "match": True, "look": "teal_orange", "strength": 55, "clean": False,
                          "steady": True}
    with pytest.raises(video_flow.VideoError, match="Unknown look"):
        video_flow._set_color(p, "look", "laser")
    legacy = {}
    video_flow._set_color(legacy, "look", "mono")  # only the choice made changes an old plan
    assert legacy["color"] == {"auto": False, "match": False, "look": "mono", "strength": 100, "clean": False}


def test_edit_requests_understand_colour_in_plain_words():
    from clipfoundry.studio import edit_requests as er

    plan = {"color": {"auto": True, "match": True, "look": "natural", "strength": 100, "clean": True},
            "clips": [], "captions": {}}

    def ops(text, p=plan):
        return er.by_rules(text, p, [])

    assert ops("make it black and white")["operations"] == [{"op": "set", "field": "look", "value": "mono"}]
    assert ops("give it a cinematic look")["operations"][0]["value"] == "film"
    assert ops("make it warmer")["operations"][0]["value"] == "warm"
    assert ops("keep the original colours")["operations"] == [{"op": "set", "field": "auto_color", "value": False}]
    assert "already on" in ops("fix the colours")["explain"]
    assert "no look" in ops("make the look subtler")["explain"]
    film = {**plan, "color": {**plan["color"], "look": "film"}}
    assert ops("tone down the look", film)["operations"] == [{"op": "set", "field": "look_strength", "value": 75}]
    assert ops("make the music warmer") is None  # sound, not picture
    assert ops("use dissolves")["operations"][0]["field"] == "transition"
    old, new = {"color": plan["color"]}, {"color": {**plan["color"], "look": "mono", "auto": False}}
    assert er.changes(old, new) == ["Look: Natural → Black and white", "Automatic colour off"]


# ---------------------------------------------------------------- review fixes (2026-11-26)
TRUTH = {"grey": (31, 31, 31), "red": (190, 45, 31)}


def _full_range(path: Path, ten_bit: bool, size: tuple[int, int] = (640, 360)) -> Path:
    """A full-range recording (what many Android phones, OBS and drones write): grey on the left, red on the
    right, BT.709, tagged pc."""
    w, h = size
    img = np.zeros((h, w, 3), np.uint8)
    img[:, : w // 2] = TRUTH["grey"]
    img[:, w // 2:] = TRUTH["red"]
    fmt = "yuv420p10le" if ten_bit else "yuvj420p"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", "10",
                    "-i", "-", "-vf", f"scale=out_color_matrix=bt709:out_range=pc,format={fmt}", "-c:v", "libx264",
                    "-crf", "4", "-pix_fmt", fmt, "-color_range", "pc", "-color_primaries", "bt709", "-color_trc",
                    "bt709", "-colorspace", "bt709", str(path)], input=img.tobytes() * 10, check=True)
    return path


def _patches(raw: bytes, w: int, h: int) -> dict:
    px = np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(float)
    return {"grey": px[h // 3: 2 * h // 3, w // 8: w // 3].reshape(-1, 3).mean(axis=0),
            "red": px[h // 3: 2 * h // 3, 2 * w // 3: 7 * w // 8].reshape(-1, 3).mean(axis=0)}


def _engine_frame(src: Path, colour: dict, layout: str, size: tuple[int, int], tmp: Path) -> dict:
    from clipfoundry.studio import engine

    w, h = size
    e = {"kind": "video", "path": str(src), "src_in_ms": 0, "clip": {"layout": layout}, "colour": colour,
         "grade": {"grade": G.Grade(), "denoise": ""}}
    args, lines = engine._video_input(e, 0, 5, 10, w, h, 0, "[v0]", layout, tmp)
    lines = [*lines, "[v0]scale=in_color_matrix=bt709:in_range=tv,format=rgb24[v]"]
    out = subprocess.run(["ffmpeg", "-v", "error", *args, "-filter_complex", ";".join(lines), "-map", "[v]",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True, cwd=tmp).stdout
    return _patches(out, w, h)


@pytest.mark.parametrize("ten_bit", [False, True])
def test_full_range_video_keeps_its_blacks_in_both_renderers_and_in_previews(tmp_path, ten_bit):
    src = _full_range(tmp_path / "full.mp4", ten_bit)
    colour = G.source_colour(src)
    assert G.input_range(colour) == "pc"
    # the full-video engine, both layouts, final size and preview size
    for layout in ("fill", "fit"):
        for size in ((1280, 720), (640, 360)):
            got = _engine_frame(src, colour, layout, size, tmp_path)
            for name, want in TRUTH.items():
                assert np.abs(got[name] - want).max() < 5, (layout, size, name, got[name])
    # the clip renderer's decoder chain: resize, then the colour step
    vf = f"fps=10,scale=320:180:flags=bicubic,{G.rgb_filters(colour, G.Grade(), '', tmp_path, 360)}"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-frames:v", "1", "-vf", vf, "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, cwd=tmp_path).stdout
    got = _patches(raw, 320, 180)
    for name, want in TRUTH.items():
        assert np.abs(got[name] - want).max() < 5, (name, got[name])


def test_a_preview_proxy_of_a_full_range_recording_reads_right(tmp_path):
    """A proxy is limited range whatever its original was; it is read with the original's matrix and its own
    range."""
    src = _full_range(tmp_path / "full.mp4", False)
    proxy = tmp_path / "proxy.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=640:-2", "-c:v", "libx264", "-crf",
                    "10", "-pix_fmt", "yuv420p", str(proxy)], check=True)  # what studio/proxies.make_proxy runs
    got = _engine_frame(proxy, G.source_colour(src), "fill", (640, 360), tmp_path)
    for name, want in TRUTH.items():
        assert np.abs(got[name] - want).max() < 5, (name, got[name])


def test_the_measurement_reads_untagged_hd_like_the_render(tmp_path):
    colour = {"matrix": "", "primaries": "", "transfer": "", "range": "", "width": 1920, "height": 1080}
    cmd = " ".join(G._frame_cmd("x.mp4", 1.0, colour, 256, 144))
    assert "in_color_matrix=bt709" in cmd and G.to_rgb_chain(colour, 1080) == "in_color_matrix=bt709"
    sd = {**colour, "width": 640, "height": 480}
    assert "in_color_matrix=bt601" in " ".join(G._frame_cmd("x.mp4", 1.0, sd, 256, 192))


def test_a_cancelled_measurement_is_never_kept(tmp_path):
    from clipfoundry.pipeline.common import Cancelled

    src = _encode(_scene((0.85, 1.0, 1.2)), tmp_path / "blue.mp4")
    cache = tmp_path / "grade.json"
    asked = []

    def cancelled() -> bool:
        asked.append(1)
        return len(asked) > 4
    with pytest.raises(Cancelled):
        G.for_footage(str(src), [(0, 1)], {}, cache=cache, cancelled=cancelled)
    assert not cache.exists()
    g, stats = G.for_footage(str(src), [(0, 1)], {}, cache=cache)
    assert cache.is_file() and stats["pixels"] > 0


def test_a_failed_probe_is_not_remembered_and_hdr10_peaks_are_read_from_the_first_frame(tmp_path, monkeypatch):
    pq = tmp_path / "pq.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate=10:d=0.5",
                    "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params",
                    "log-level=error:hdr10=1:max-cll=4000,400:master-display=G(13250,34500)B(7500,3000)"
                    "R(34000,16000)WP(15635,16450)L(40000000,50):colorprim=bt2020:transfer=smpte2084:"
                    "colormatrix=bt2020nc", "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                    "-colorspace", "bt2020nc", "-tag:v", "hvc1", str(pq)], check=True)
    real = G.run_process
    calls = []

    def failing(*a, **k):
        calls.append(1)
        raise G.FFmpegError("busy") if hasattr(G, "FFmpegError") else RuntimeError("busy")
    monkeypatch.setattr(G, "run_process", failing)
    assert G.source_colour(pq)["transfer"] == ""
    monkeypatch.setattr(G, "run_process", real)
    colour = G.source_colour(pq)
    assert colour["transfer"] == "smpte2084" and colour["max_cll"] == 4000.0


def test_grain_is_cleaned_for_the_size_the_picture_is_shown_at():
    from clipfoundry.studio import engine

    stats = {"noise": 3.0}
    assert G.denoise_for(stats, {}).startswith("atadenoise")
    assert G.denoise_for(stats, {}, 1 / 3) == ""  # a 360p preview of a 1080p recording: the grain is mostly gone
    heavy = {"noise": 6.0}
    look = {"grade": G.Grade(), "stats": heavy, "denoise": G.denoise_for(heavy, {})}
    assert "sigma=6.0" in look["denoise"]
    shown = engine._shown_at(look, {"width": 1920, "height": 1080}, 640, 360)
    assert shown["denoise"].startswith("atadenoise") and look["denoise"].startswith("fftdnoiz")
    assert engine._shown_at(look, {"width": 1920, "height": 1080}, 1920, 1080) == look


def test_filmcraft_keeps_finals_whose_colour_step_does_something_on_the_built_in_engine(tmp_path):
    from clipfoundry.studio import engine

    sdr = _encode(_scene(), tmp_path / "a.mp4")
    assets = {"a": {"kind": "video", "path": str(sdr)}}
    plan = {"clips": [{"asset_id": "a", "include": True}], "color": engine.default_color({})}
    assert engine.colour_in_use(plan, assets)
    assert not engine.colour_in_use({"clips": plan["clips"]}, assets)  # an old plan of normal video: nothing to do
    assert engine.colour_in_use({"clips": plan["clips"], "color": {"auto": False, "clean": False, "look": "mono",
                                                                   "strength": 60}}, assets)
    # measured as the render would: a clean picture with only grain cleanup on has nothing to do
    plan2 = {"clips": [{"asset_id": "a", "include": True, "in_ms": 0, "out_ms": 1000}],
             "color": {"auto": False, "match": False, "look": "natural", "strength": 100, "clean": True}}
    assert engine.colour_in_use(plan2, assets) and not engine.colour_in_use(plan2, assets, tmp_path / "pieces")
    plan2["color"]["auto"] = True  # this test picture is washed out: the correction is real
    assert engine.colour_in_use(plan2, assets, tmp_path / "pieces")
    hlg = _hlg_clip(tmp_path / "h.mp4")
    assert engine.colour_in_use({"clips": [{"asset_id": "h", "include": True}]},
                                {"h": {"kind": "video", "path": str(hlg)}})  # phone HDR is always converted


def test_a_full_range_photo_shown_whole_keeps_its_blacks(tmp_path):
    """JPEG photos are full range too; the "fit" layout (blurred copy behind) used to lift their blacks."""
    from clipfoundry.studio import engine

    src = _full_range(tmp_path / "full.mp4", False)
    photo = tmp_path / "photo.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-frames:v", "1", "-q:v", "1", str(photo)],
                   check=True)
    for size in ((1280, 720), (640, 360)):
        e = {"kind": "image", "path": str(photo), "clip": {"layout": "fit"}}
        args, lines = engine._video_input(e, 0, 5, 10, *size, 0, "[v0]", "fit", tmp_path)
        lines = [*lines, "[v0]scale=in_color_matrix=bt709:in_range=tv,format=rgb24[v]"]
        raw = subprocess.run(["ffmpeg", "-v", "error", *args, "-filter_complex", ";".join(lines), "-map", "[v]",
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             check=True, capture_output=True, cwd=tmp_path).stdout
        got = _patches(raw, *size)
        assert np.abs(got["grey"] - TRUTH["grey"]).max() < 5, (size, got)


def test_colour_words_inside_other_requests_are_not_taken_for_colour():
    from clipfoundry.studio import edit_requests as er

    plan = {"color": {"auto": True, "match": True, "look": "vintage", "strength": 100, "clean": True},
            "clips": [], "captions": {}}
    rows = [{"n": k + 1, "id": f"c{k + 1}", "kind": "video", "label": label, "included": True, "in_ms": 0,
             "out_ms": 3000, "out": [k * 3000, k * 3000 + 3000], "summary": "", "words": []}
            for k, label in enumerate(("Black and white intro", "Vintage car", "Interview"))]

    def ops(text):
        return er.by_rules(text, plan, rows)

    removed = ops("remove the black and white intro")["operations"]
    assert removed and all(o.get("clip_id") == "c1" for o in removed) and removed[0]["op"] != "set"
    moved = ops("move the vintage car to the end")["operations"]
    assert moved and moved[0].get("clip_id") == "c2" and moved[0]["op"] != "set"
    assert ops("make the ending cooler") is None              # a part of the video: the AI, not the whole look
    for sound in ("remove the background noise", "clean up the hiss", "less noise in the audio"):
        r = ops(sound)
        assert r is None or all(o.get("field") != "clean_picture" for o in r.get("operations") or []), sound
    assert ops("remove the look")["operations"] == [{"op": "set", "field": "look", "value": "natural"}]
    assert ops("remove the vintage look")["operations"] == [{"op": "set", "field": "look", "value": "natural"}]
    assert ops("don't clean up the grain")["operations"] == [{"op": "set", "field": "clean_picture", "value": False}]
    assert ops("don't match the clips' colours")["operations"] == [{"op": "set", "field": "match_color",
                                                                    "value": False}]
