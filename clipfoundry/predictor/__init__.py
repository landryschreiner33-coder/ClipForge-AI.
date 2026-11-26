"""ClipForge's viral predictor: for one short video, a viral score, the hook, how long people stay (a hold curve),
when the strongest moment comes, a per-second heatmap of five channels (vision, sound, language, attention, memory),
reasons tied to moments, and fixes that were tried on a model of the clip before they are offered.

It is built from public research on what predicts short-video performance (docs/clipforge/VIRAL_PREDICTOR.md), not
from any other product's code. Every number is an estimate from the clip's own picture, sound and words; once your
own posts have real results, learn.py checks the estimates against them and calibrates them.

Where it runs:
- after every render (pipeline/render.py), so each clip and version carries its prediction (render_info);
- while clips are picked, from the recording's words and sound only (pipeline/deep.py, a bounded adjustment);
- on any video file the owner uploads (Check a video, checks.py);
- when the posting plan weighs a clip's expected retention (autopilot/scheduler.py).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from . import content, fixes, model, signals

log = logging.getLogger(__name__)
SETTING = "viral_predictor"
STATE_LEARNED = "predictor:learned"
STATE_ACCURACY = "predictor:accuracy"


def enabled(settings: dict | None = None) -> bool:
    if settings is None:
        from .. import db

        settings = db.get_settings()
    return bool(settings.get(SETTING, True))


def learned(settings: dict | None = None) -> dict | None:
    """What learn.py learned from the owner's results (None while learning is paused or nothing was learned)."""
    from .. import db
    from ..autopilot import state

    settings = settings if settings is not None else db.get_settings()
    if settings.get("brain_paused"):
        return None
    data = state.get(STATE_LEARNED)
    return data if isinstance(data, dict) and data.get("model") == model.MODEL_VERSION else None


def to_source(segments: list[dict] | None, offset: float = 0.0) -> Callable[[float], float] | None:
    """Maps a time in a rendered clip to the time in its recording, from the render's edit decision list. `offset`:
    where the rendered file's source starts in the recording (a live clip renders from a window of the stream)."""
    segs = sorted((s for s in segments or [] if s.get("out_end", 0) > s.get("out_start", 0)),
                  key=lambda s: float(s["out_start"]))
    if not segs:
        return None

    def f(t: float) -> float:
        for s in segs:
            if float(s["out_start"]) - 1e-6 <= t <= float(s["out_end"]) + 1e-6:
                return offset + float(s["src_start"]) + (t - float(s["out_start"])) * float(s.get("speed") or 1.0)
        return offset + (float(segs[-1]["src_end"]) if t > float(segs[-1]["out_end"]) else float(segs[0]["src_start"]))

    return f


def run(path: str | Path, words: list[dict] | None, settings: dict, *, edit: dict | None = None,
        to_src: Callable[[float], float] | None = None, cancelled: Callable[[], bool] | None = None,
        progress: Callable[[float, str], None] | None = None, probe: dict | None = None,
        learned_values: dict | None | bool = False) -> dict:
    """Measure a video file and predict it. `words`: the words heard in it, in its own time (None: speech is estimated
    from the sound). `edit`: the clip's effective edit options when ClipForge can change the clip (fixes become
    one-press changes), else None (fixes are advice). Raises signals.MeasureError for a file it cannot measure."""
    sig = signals.measure_file(path, words, cancelled=cancelled, progress=progress, probe=probe)
    con = content.analyze(sig, settings)
    lrn = learned(settings) if learned_values is False else learned_values
    pred = model.predict(sig, con, lrn or None)
    out = model.public(pred)
    out["fixes"] = fixes.suggest(sig, pred, settings, lrn or None, edit, to_src)
    out["at"] = round(time.time(), 3)
    return out


MOMENT_MAX = 5.0  # clip picking: the predictor moves a moment's Clip Score by at most this many points


def moment(start: float, end: float, words: list[dict], loud, content: dict | None = None,
           emphasis: list[float] | None = None, learned_values: dict | None | bool = False) -> dict:
    """While clips are picked: the hook and how long people stay for the moment [start, end) of a recording, from its
    words and sound (the picture is measured once the clip is rendered). `content`: its 11-factor analysis. The
    adjustment leaves out what it says (Viral Potential is already the Clip Score's base) and is bounded."""
    sig = signals.from_source(start, end, words, loud, emphasis)
    lrn = learned() if learned_values is False else learned_values
    pred = model.predict(sig, content, lrn or None)
    hook_v = pred["hook"]["score"] / 100.0
    watch_v = (pred["components"].get("watch") or 0) / 100.0
    adjust = max(-MOMENT_MAX, min(MOMENT_MAX, 10.0 * ((hook_v + watch_v) / 2.0 - 0.5)))
    return {"model": model.MODEL_VERSION, "score": pred["score"], "hook": pred["hook"]["score"],
            "avg_view": pred["hold"]["avg_view"], "rate": pred["hold"]["rate"], "peak": pred["peak"]["t"],
            "adjust": round(adjust, 1)}


def _read(path: str | None) -> dict | None:
    from ..pipeline.common import read_json

    if not path:
        return None
    data = read_json(Path(path), None)
    return data if isinstance(data, dict) else None


def _edit_for(clip: dict, opts: dict) -> dict:
    """The clip's effective options, with the hook text the overlay would show."""
    return {**opts, "hook": opts.get("hook") if opts.get("hook") is not None else clip.get("hook", "")}


def for_render(out_path: str | Path, art: dict, opts: dict, clip: dict, settings: dict, cancelled=None,
               editable: bool = True, source_offset: float = 0.0) -> dict | None:
    """The prediction of a clip just rendered (render.render_clip): never stops a render (None when it fails).
    `source_offset`: where the render's source starts in the clip's recording (render_info["source_offset"])."""
    from ..pipeline.common import Cancelled

    if not enabled(settings):
        return None
    try:
        words = (_read(art.get("transcript")) or {}).get("words")
        edl = (_read(art.get("edl")) or {}).get("segments")
        pred = run(out_path, words if isinstance(words, list) else None, settings,
                   edit=_edit_for(clip, opts) if editable else None,
                   to_src=to_source(edl, source_offset) if editable else None, cancelled=cancelled)
        pred["file_sha256"] = art.get("sha256", "")
        return pred
    except Cancelled:
        raise
    except signals.ra.Canceled:
        raise Cancelled() from None
    except Exception:  # noqa: BLE001 - a prediction is extra: the clip is made either way
        log.exception("viral prediction failed for %s", out_path)
        return None


def _target(clip: dict, version_id: str = "") -> tuple[str, dict, dict | None]:
    """(file, render_info, version row) of the clip itself or one of its versions."""
    from .. import db

    if version_id:
        v = db.get_version(version_id)
        if not v or v.get("clip_id") != clip["id"]:
            raise LookupError("Version not found.")
        return v.get("output_path") or "", v.get("render_info") or {}, v
    return clip.get("output_path") or "", clip.get("render_info") or {}, None


def stored(clip: dict, version_id: str | None = None) -> dict | None:
    """The prediction kept with what would be published for this clip (or the given version), when it belongs to
    the file as it is now and to this model."""
    from ..pipeline import artifact

    if version_id is None:
        _, version_id, info = artifact.active(clip)
    else:
        try:
            _, info, _ = _target(clip, version_id)
        except LookupError:
            return None
    pred = (info or {}).get("prediction")
    if not isinstance(pred, dict) or pred.get("model") != model.MODEL_VERSION:
        return None
    art = artifact.of(info)
    if art and pred.get("file_sha256") and pred["file_sha256"] != art["sha256"]:
        return None
    return {**pred, "version_id": version_id or ""}


def predict_clip(clip_id: str, version_id: str = "", cancelled=None) -> dict:
    """Predict a clip (or one version) that is already rendered, and keep the result with it. Used for clips
    rendered before the predictor existed and when the owner asks again."""
    from .. import db
    from ..pipeline import artifact, render

    clip = db.get_clip(clip_id)
    if not clip:
        raise LookupError("Clip not found.")
    path, info, version = _target(clip, version_id)
    if not path or not Path(path).is_file():
        raise FileNotFoundError("This clip is not rendered yet.")
    settings = db.get_settings()
    art = artifact.of(info)
    words = ((artifact.final_transcript(info) or {}).get("words")) if art else None
    edl = (_read(art.get("edl")) or {}).get("segments") if art else None
    project = db.get_project(clip["project_id"]) or {}
    edit = {**(clip.get("edit") or {}), **((version or {}).get("edit") or {})}
    opts = render.effective_options(settings, project.get("options") or {}, edit)
    editable = version is None and bool(art)
    pred = run(path, words, settings, edit=_edit_for(clip, opts) if editable else None,
               to_src=to_source(edl, float(info.get("source_offset") or 0.0)) if editable else None,
               cancelled=cancelled)
    pred["file_sha256"] = (art or {}).get("sha256", "")
    # keep it only when the clip still has the file that was measured (a render may have finished meanwhile)
    fresh = db.get_clip(clip_id) or {}
    try:
        now_path, now_info, _ = _target(fresh, version_id)
    except LookupError:
        return pred
    if now_path == path and (artifact.of(now_info) or {}).get("sha256") == (art or {}).get("sha256"):
        if version_id:
            db.update_version(version_id, render_info={**now_info, "prediction": pred})
        else:
            db.update_clip(clip_id, render_info={**now_info, "prediction": pred})
    return {**pred, "version_id": version_id}


def watched(clip: dict) -> float | None:
    """The predicted average share of the clip watched, in percent (calibrated on your results when learned)."""
    pred = stored(clip)
    if not pred:
        return None
    hold = pred.get("hold") or {}
    v = hold.get("avg_view_calibrated", hold.get("avg_view"))
    return None if v is None else float(v)


def snapshot(clip: dict) -> dict | None:
    """What the predictor said about a clip when it was published (stored with the post, checked by learn.py)."""
    pred = stored(clip)
    if not pred:
        return None
    hold = pred.get("hold") or {}
    return {"model": pred["model"], "score": pred["score"], "band": pred["band"],
            "hook": (pred.get("hook") or {}).get("score"), "avg_view": hold.get("avg_view"),
            "avg_view_calibrated": hold.get("avg_view_calibrated"), "rate": hold.get("rate"),
            "components": pred.get("components") or {}, "peak": (pred.get("peak") or {}).get("t"),
            "at": pred.get("at")}


def summary(pred: dict | None) -> dict | None:
    """The few numbers a clip card shows."""
    if not pred:
        return None
    hold = pred.get("hold") or {}
    return {"score": pred["score"], "band": pred["band"], "hook": (pred.get("hook") or {}).get("score"),
            "avg_view": hold.get("avg_view_calibrated", hold.get("avg_view")), "rate": hold.get("rate"),
            "fixes": len(pred.get("fixes") or [])}
