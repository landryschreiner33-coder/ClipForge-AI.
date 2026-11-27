"""The editor's camera edits (multicam and the corner camera), applied to a plan copy by video_flow.apply_edit.

    {"op": "cameras_add", "of"?, "asset_ids"?}          line up other recordings of the same moments by their sound
    {"op": "cameras_auto", "of"?, "mode": "speaker" | "angles" | "off", "asset_ids"?}
                                                        switch cameras automatically (lining them up first if needed)
    {"op": "camera_set", "clip_id", "cam"}               show one camera for a whole clip
    {"op": "camera_cut", "clip_id", "offset_ms", "cam"}  from this moment of a clip on (file time from its in point)
    {"op": "camera_edit", "of"?, "cam", "field": "shot" | "label" | "offset_ms", "value"}
    {"op": "camera_corner", "of"?, "cam": id | None, "place"?, "size"?}
    {"op": "cameras_remove", "of"?}                     back to the recording's own camera only

`of` is the main recording (the one the clips are cut from); without it, the recording that already has cameras,
else the one most of the video plays. Every change says what it did in plain words; anything that cannot work raises
multicam.MulticamError with a sentence for the owner.
"""
from __future__ import annotations

import logging

from . import multicam, retime
from .multicam import MAIN, MulticamError

log = logging.getLogger(__name__)

OPS = ("cameras_add", "cameras_auto", "camera_set", "camera_cut", "camera_edit", "camera_corner", "cameras_remove")
FACE_SAMPLE_S = 4.0     # seconds of picture looked at to tell a wide shot from a close-up


def _length(a: dict) -> int:
    return int(float((a.get("probe") or {}).get("duration") or 0) * 1000)


def main_recording(p: dict, edit: dict, assets: dict[str, dict]) -> str:
    """The recording the camera edit is about."""
    of = edit.get("of")
    if of not in (None, ""):
        if not isinstance(of, str) or of not in assets or assets[of].get("kind") != "video":
            raise MulticamError("That recording is not in this video.")
        return of
    if edit.get("clip_id"):
        c = next((c for c in p.get("clips") or [] if c.get("id") == edit["clip_id"]), None)
        if c is None:
            raise MulticamError("That clip is not in this video.")
        return c["asset_id"]
    have = [aid for aid in multicam.groups(p) if aid in assets]
    if len(have) == 1:
        return have[0]
    plays: dict[str, int] = {}
    for c in p.get("clips") or []:
        a = assets.get(c.get("asset_id"))
        if c.get("include", True) and a and a.get("kind") == "video" and not retime.is_freeze(c):
            plays[c["asset_id"]] = plays.get(c["asset_id"], 0) + int(c["out_ms"]) - int(c["in_ms"])
    if have:
        return max(have, key=lambda aid: plays.get(aid, 0))
    if not plays:
        raise MulticamError("This video has no recording to add cameras to.")
    return max(plays, key=plays.get)


def _group(p: dict, main_id: str) -> dict:
    g = multicam.group_of(p, main_id)
    if g is None:
        raise MulticamError("This recording has no other cameras yet. Line them up first.")
    return g


def _ranges(p: dict, main_id: str) -> list[tuple[float, float]]:
    """The parts of the main recording the video plays, in the video's order."""
    return [(float(c["in_ms"]), float(c["out_ms"])) for c in p.get("clips") or []
            if c.get("include", True) and c.get("asset_id") == main_id and not retime.is_freeze(c)]


def guess_shot(asset: dict, at_s: float) -> str:
    """"wide", "close" or "other" from a few seconds of picture: two faces or more (or one small one) is a wide
    shot, one big face a close-up, no face on a flat, still picture a screen; "close" when the picture cannot be read
    (the owner can change it)."""
    try:
        from ..pipeline import reframe

        probe = asset.get("probe") or {}
        a = reframe.analyze(asset["path"], max(0.0, at_s), max(0.0, at_s) + FACE_SAMPLE_S, int(probe["width"]),
                            int(probe["height"]))
    except Exception as exc:  # noqa: BLE001 - a guess: the owner can set it
        log.info("could not look at %s: %s", asset.get("filename"), exc)
        return "close"
    n = max(1, a["n"])
    per = [sum(1 for t in a["tracks"] if i in t.boxes) for i in range(n)]
    if sum(1 for k in per if k) / n < 0.3:
        return "other" if a["edge"] > 0.07 and a["sat"] < 70 and a["motion"] < 6 else "wide"
    if sum(1 for k in per if k >= 2) / n >= 0.3:
        return "wide"
    return "close" if max(t.mean_area() for t in a["tracks"]) >= 0.015 else "wide"


def _profile(asset: dict) -> "multicam.np.ndarray":
    try:
        return multicam.sound_profile(asset)
    except OSError as exc:
        raise MulticamError(f"ClipForge could not read the sound of “{asset['filename']}”.") from exc


def add_cameras(p: dict, main_id: str, asset_ids, assets: dict[str, dict]) -> str:
    """Line up `asset_ids` (default: every other video in the media) with the main recording by their sound and add
    the ones that match; say which did not."""
    if asset_ids is not None and (not isinstance(asset_ids, list) or not all(isinstance(a, str) for a in asset_ids)):
        raise MulticamError("Choose the recordings to line up.")
    main = assets[main_id]
    g = p.setdefault("multicam", {}).setdefault(main_id, {"main": {"label": "Camera 1"}, "cams": [], "cuts": [],
                                                          "switching": "off"})
    if not isinstance(g.get("main"), dict):
        g["main"] = {"label": "Camera 1"}
    have = {c["asset_id"] for c in g["cams"]}
    pool = [aid for aid in (asset_ids or [a for a in assets if assets[a].get("kind") == "video"])
            if aid != main_id and aid not in have and assets.get(aid, {}).get("kind") == "video"]
    if asset_ids and any(aid not in assets for aid in asset_ids):
        raise MulticamError("That recording is not in this video's media.")
    if not pool:
        if not g["cams"]:
            p["multicam"].pop(main_id, None)
            if not p["multicam"]:
                p.pop("multicam")
            raise MulticamError("Add the other cameras' recordings to the media first.")
        return "Every camera is already lined up"
    ranges = _ranges(p, main_id)
    at = (ranges[0][0] / 1000 + 1.0) if ranges else 1.0
    if "shot" not in g["main"]:
        g["main"]["shot"] = guess_shot(main, at)
    ref = _profile(main)
    added, missed, fresh = [], [], []
    for aid in pool:
        if len(g["cams"]) + 1 >= multicam.MAX_CAMS:
            missed.append(f"{assets[aid]['filename']} (at most {multicam.MAX_CAMS} cameras)")
            continue
        found = multicam.line_up(ref, _profile(assets[aid]))
        if not found:
            missed.append(assets[aid]["filename"])
            continue
        cid = next(f"c{k}" for k in range(2, 99) if f"c{k}" not in multicam.cam_ids(g))
        cam = {"id": cid, "asset_id": aid, "label": f"Camera {len(g['cams']) + 2}", **found}
        cam["shot"] = guess_shot(assets[aid], multicam.to_cam_ms(cam, at * 1000) / 1000)
        cam["shot_guessed"] = True  # until the owner chooses it
        g["cams"].append(cam)
        fresh.append(cam)
        added.append(f"{cam['label']} ({assets[aid]['filename']}, {multicam.SHOT_NAMES[cam['shot']].lower()})")
    if not g["cams"]:
        p["multicam"].pop(main_id, None)
        if not p["multicam"]:
            p.pop("multicam")
        raise MulticamError("None of the other recordings has the same sound as this one, so they could not be lined "
                            "up: " + ", ".join(missed) + ".")
    note = ("Lined up " + ", ".join(added)) if added else "No new camera lined up"
    if missed:
        note += ". Not the same sound, left out: " + ", ".join(missed)
    moved = _to_main(p, main_id, g, fresh, assets)
    if moved:
        note += f". {moved} {'part' if moved == 1 else 'parts'} cut from another camera's file now " + \
            f"{'plays' if moved == 1 else 'play'} from {assets[main_id]['filename']} with that camera shown"
    return note


def _to_main(p: dict, main_id: str, g: dict, cams: list[dict], assets: dict[str, dict]) -> int:
    """Clips cut from a camera's own file, at moments the main recording also has, now play from the main recording
    (its sound and words) with that camera shown: the cameras switch there like everywhere else, and "Edit it for
    me" never uses the same moment twice. Returns how many clips moved."""
    main_len = _length(assets[main_id])
    moved = 0
    for c in p.get("clips") or []:
        cam = next((x for x in cams if x["asset_id"] == c.get("asset_id")), None)
        if cam is None or c.get("kind", "video") not in ("video", "freeze"):
            continue
        rate = 1 + float(cam.get("drift_ppm") or 0) / 1e6
        a, b = ((float(c[k]) - float(cam.get("offset_ms") or 0)) / rate for k in ("in_ms", "out_ms"))
        if a < 0 or b > main_len:
            continue  # the main recording does not have these moments
        c.update(asset_id=main_id, in_ms=int(round(a)), out_ms=int(round(b)))
        end = float(c["in_ms"]) + 1 if retime.is_freeze(c) else float(c["out_ms"])
        after = multicam.camera_at(g, end)
        g["cuts"] = _tidy([x for x in g.get("cuts") or [] if not c["in_ms"] <= float(x[0]) <= end] +
                          [[c["in_ms"], cam["id"]], [end, after]])
        moved += 1
    if moved:
        g["switching"] = "hand"
    return moved


def auto(p: dict, main_id: str, mode: str, words: dict[str, list[dict]], assets: dict[str, dict],
         asset_ids=None) -> str:
    """Switch cameras automatically: "speaker" (to whoever is speaking), "angles" (one person: another angle at a
    pause every few seconds) or "off" (the recording's own camera only)."""
    if mode not in ("speaker", "angles", "off"):
        raise MulticamError("Choose to switch to whoever speaks, to change angles, or to stop switching.")
    if multicam.group_of(p, main_id) is None or asset_ids:
        if mode == "off":
            raise MulticamError("This recording has no other cameras to switch between.")
        setup = add_cameras(p, main_id, asset_ids, assets)
    else:
        setup = ""
    g = _group(p, main_id)
    if mode == "off":
        g.update(cuts=[], switching="off")
        return f"Stopped switching cameras: {multicam.label_of(g, MAIN)} only"
    ranges = _ranges(p, main_id)
    if not ranges:
        raise MulticamError("No clip of this recording is in the video.")
    said = words.get(main_id) or []
    shots = {cam: multicam.shot_of(g, cam) for cam in multicam.cam_ids(g)}
    lengths = {c["id"]: _length(assets[c["asset_id"]]) for c in g["cams"] if c["asset_id"] in assets}

    def avail(cam: str, t0: float, t1: float) -> bool:
        if cam == MAIN:
            return True
        lo, hi = multicam.coverage(multicam.cam_entry(g, cam) or {}, lengths.get(cam, 0))
        return lo <= t0 and t1 <= hi

    why, who, used, found = "", None, mode, ""
    if mode == "speaker":
        # every camera that films people listens: a camera whose microphone hears one person loudest shows that
        # person (a wide shot with its microphone between everybody hears nobody loudest, so it shows nobody's turn)
        listen = [cam for cam in multicam.cam_ids(g) if shots[cam] != "other"]
        if not said:
            why = "this recording has no words yet, so nobody can be heard speaking"
        elif len(listen) < 2:
            why = "only one camera films the people"
        else:
            ref = _profile(assets[main_id])
            levels = {}
            for cam in listen:  # each camera's sound on the main recording's frames
                own = ref if cam == MAIN else _profile(assets[multicam.asset_of(g, main_id, cam)])
                levels[cam] = multicam.aligned(own, None if cam == MAIN else multicam.cam_entry(g, cam), len(ref))
            who, info = multicam.who_speaks(said, levels)
            if not info["separable"]:
                why, who = info["why"], None
            else:
                found = _close_by_sound(g, set(info["seconds"]))
        if who is None:
            used = "angles"
    shots = {cam: multicam.shot_of(g, cam) for cam in multicam.cam_ids(g)}  # a camera found by its sound is close
    cuts = multicam.plan_cuts(ranges, said, who, shots, used, avail, seed=main_id)
    g.update(cuts=cuts, switching=used)
    changes = sum(1 for c in cuts if any(a <= c[0] < b for a, b in ranges))
    if used == "speaker":
        note = f"Cameras switch to whoever is speaking ({changes} changes"
        note += ", the wide shot at the start, the end and in long pauses)" if "wide" in shots.values() else ")"
        if found:
            note += f". {found}"
    else:
        note = f"Cameras change angle at pauses every few seconds ({changes} changes)"
        if why:
            note += f". They could not follow the speaker: {why}"
    return f"{setup}. {note}" if setup else note


def _close_by_sound(g: dict, owners: set[str]) -> str:
    """Cameras whose microphone hears one person loudest film that person: a camera ClipForge guessed to be a wide
    shot (its picture showed no face it could read) becomes a close-up. The recording's own camera keeps its shot, and
    so does any camera whose shot the owner chose. Returns what changed, in words ("" for nothing)."""
    changed = []
    for cam in sorted(owners - {MAIN}):
        rec = multicam.cam_entry(g, cam) or {}
        if rec.get("shot_guessed") and rec.get("shot") == "wide":
            rec["shot"] = "close"
            changed.append(multicam.label_of(g, cam))
    if not changed:
        return ""
    names = " and ".join(changed) if len(changed) < 3 else ", ".join(changed[:-1]) + " and " + changed[-1]
    return f"{names} {'hears' if len(changed) == 1 else 'each hear'} one person loudest, so " + \
        ("it is used as a close-up" if len(changed) == 1 else "they are used as close-ups")


def _tidy(cuts: list[list]) -> list[list]:
    out: list[list] = []
    for t, cam in sorted(([int(round(float(t))), cam] for t, cam in cuts), key=lambda x: x[0]):
        if out and out[-1][0] == t:
            out[-1][1] = cam
            if len(out) > 1 and out[-2][1] == cam:
                out.pop()
        elif not out or out[-1][1] != cam:
            out.append([t, cam])
    return out[1:] if out and out[0][1] == MAIN else out


def _cam(g: dict, cam) -> str:
    if cam in (None, "", "main"):
        return MAIN
    if cam not in multicam.cam_ids(g):
        raise MulticamError("That camera is not one of this recording's cameras.")
    return cam


def apply(p: dict, edit: dict, words: dict[str, list[dict]], assets: dict[str, dict]) -> str:
    """Apply one camera edit to plan `p` (changed in place); returns what changed, in plain words."""
    op = edit.get("op")
    main_id = main_recording(p, edit, assets)
    if op == "cameras_add":
        return add_cameras(p, main_id, edit.get("asset_ids"), assets)
    if op == "cameras_auto":
        return auto(p, main_id, edit.get("mode") or "speaker", words, assets, edit.get("asset_ids"))
    g = _group(p, main_id)
    if op in ("camera_set", "camera_cut"):
        c = next((c for c in p.get("clips") or [] if c.get("id") == edit.get("clip_id")), None)
        if c is None:
            raise MulticamError("That clip is not in this video.")
        cam = _cam(g, edit.get("cam"))
        a = float(c["in_ms"])
        b = a + 1 if retime.is_freeze(c) else float(c["out_ms"])
        if op == "camera_set":
            after = multicam.camera_at(g, b)
            g["cuts"] = _tidy([x for x in g.get("cuts") or [] if not a <= float(x[0]) <= b] + [[a, cam], [b, after]])
            g["switching"] = "hand"
            return f"{c['label']}: {multicam.label_of(g, cam)}"
        off = edit.get("offset_ms")
        if isinstance(off, bool) or not isinstance(off, (int, float)) or not 0 <= off < b - a:
            raise MulticamError("Choose a moment inside the clip.")
        t = a + float(off)
        g["cuts"] = _tidy([x for x in g.get("cuts") or [] if float(x[0]) != t] + [[t, cam]])
        g["switching"] = "hand"
        return f"{multicam.label_of(g, cam)} from {off / 1000:.1f} s into {c['label']}"
    if op == "camera_edit":
        cam = _cam(g, edit.get("cam"))
        if cam == MAIN and not isinstance(g.get("main"), dict):
            g["main"] = {}
        rec = g["main"] if cam == MAIN else multicam.cam_entry(g, cam)
        field, value = edit.get("field"), edit.get("value")
        if field == "shot" and value in multicam.SHOTS:
            rec["shot"] = value
            rec.pop("shot_guessed", None)
            return f"{multicam.label_of(g, cam)} is a {multicam.SHOT_NAMES[value].lower()}"
        if field == "label" and isinstance(value, str) and value.strip():
            rec["label"] = value.strip()[:40]
            return f"Renamed the camera to {rec['label']}"
        number = multicam._number(value, -multicam.OFFSET_MAX_MS, multicam.OFFSET_MAX_MS)  # noqa: SLF001
        if field == "nudge_ms" and cam != MAIN and number and abs(value) <= 1000:
            # a frame or so earlier or later: the measured clock drift and the sound match stay
            new = round(float(rec.get("offset_ms") or 0) + float(value), 1)
            if abs(new) > multicam.OFFSET_MAX_MS:
                raise MulticamError("A camera can be lined up at most a day away.")
            rec["offset_ms"] = new
            return f"{multicam.label_of(g, cam)} {abs(value):.0f} ms {'later' if value > 0 else 'earlier'} " \
                f"({new / 1000:+.2f} s)"
        if field == "offset_ms" and cam != MAIN and number:
            # lined up by hand: the clocks still run apart as measured (line up again to measure them again)
            rec.update(offset_ms=round(float(value), 1), match=None)
            return f"Lined up {multicam.label_of(g, cam)} by hand ({value / 1000:+.2f} s)"
        raise MulticamError(f"“{field}” cannot be set to that.")
    if op == "camera_corner":
        if edit.get("cam") in (None, ""):
            g.pop("corner", None)
            return "No camera in the corner"
        cam = _cam(g, edit.get("cam"))
        place, size = edit.get("place"), edit.get("size")
        if place is not None and place not in multicam.CORNERS:
            raise MulticamError("Choose a corner: top left, top right, bottom left or bottom right.")
        if size is not None and not multicam._number(size, *multicam.CORNER_SIZE):  # noqa: SLF001
            raise MulticamError(f"A corner picture is {multicam.CORNER_SIZE[0]:.0%} to "
                                f"{multicam.CORNER_SIZE[1]:.0%} of the frame's width.")
        old = g.get("corner") or {}
        g["corner"] = {"cam": cam, **({"place": place or old["place"]} if place or old.get("place") else {}),
                       **({"size": size if size is not None else old["size"]}
                          if size is not None or old.get("size") is not None else {})}
        where = multicam.CORNER_NAMES.get(g["corner"].get("place") or "", "its usual corner")
        return f"{multicam.label_of(g, cam)} in the {where}" if g["corner"].get("place") else \
            f"{multicam.label_of(g, cam)} in a corner"
    if op == "cameras_remove":
        p["multicam"].pop(main_id, None)
        if not p["multicam"]:
            p.pop("multicam")
        return "Back to one camera (the other recordings stay in your media)"
    raise MulticamError("Unknown edit.")
