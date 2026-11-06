"""The AI finishing the edit with FilmCraft's tools and EffectCraft shots (only with an AI service set up).

The AI service is sent the sequence (FilmCraft's clip ids, where each clip sits, what is said in it), the video's
size and title, and the FilmCraft tools it may use with their parameters; never the video, the sound or file paths.
It answers with steps (FilmCraft commands) and at most two effects shots (After Effects-style scripts EffectCraft
runs in its sandbox). Every step is checked before it runs:

* only finishing tools: effects and keyframes, colour presets, transitions, speed, titles and shapes, caption style,
  Essential Sound, markers. Cuts, trims and moves stay with ClipForge's editor, so captions, chapters and the
  video's length stay right; the person can still do anything by hand in FilmCraft's editor;
* clip ids must be clips of this sequence; no parameter may name a file, folder or address;
* at most 40 steps and 2 shots; a step FilmCraft refuses is reported and the rest still run.
"""
from __future__ import annotations

import json
import re

from ..studio import engine
from ..studio.jobs import Canceled
from . import shots
from .runner import CraftError

MAX_STEPS = 40
MAX_SHOTS = 2
ALLOWED = {
    "effects.apply", "effects.setParam", "effects.addKeyframe", "effects.setInterpolation", "effects.remove",
    "effects.toggleEnabled", "effects.resetParam", "effects.reset",
    "lumetri.applyPreset",
    "sequence.applyVideoTransition", "sequence.applyAudioTransition", "sequence.setTransition",
    "sequence.removeTransition",
    "clip.speedDuration", "clip.audioGain",
    "graphics.newText", "graphics.set", "graphics.setText", "graphics.newRectangle", "graphics.newEllipse",
    "graphics.newPolygon", "graphics.newShape", "graphics.align",
    "captions.setStyle",
    "essentialSound.setType", "essentialSound.set", "essentialSound.applyPreset", "essentialSound.generateDucking",
    "essentialSound.autoMatch",
    "markers.add",
}
FILE_KEYS = {"path", "paths", "file", "files", "folder", "dir", "lut", "output", "destination", "url", "src"}
_PATHISH = re.compile(r"^(?:/|~|\\\\|[A-Za-z]:[\\/]|file:|[a-z][a-z0-9+.-]*://)", re.I)

SYSTEM = """You finish video edits in FilmCraft, a professional video editor, by choosing its tools. The cut (which
clips, in which order, how long) is final; you only improve how it looks and sounds: colour, effects with keyframes,
transitions, speed ramps, titles and shapes, caption style, sound clean-up. You can also ask EffectCraft (motion
graphics) for up to two effects shots, which are laid over the video. Answer with one JSON object and nothing else."""

ANSWER = """Answer format:
{"summary": "one sentence for the person: what you did",
 "steps": [{"id": "<tool id>", "params": {...}, "why": "short reason"}],
 "shots": [{"name": "Lower third", "at_s": 3.0, "seconds": 4.0, "script": "<After Effects ExtendScript body>"}]}
Rules: use only the tools listed, with clip ids from the sequence; times for keyframes as "frame" (sequence frame) or
"seconds"; at most 40 steps; no file paths. Leave steps empty when the edit is already good. A shot's script runs in
After Effects' scripting model with `comp` already made (W x H, FPS, DUR seconds, transparent background): add text,
shape and solid layers, effects and keyframes to `comp`; do not save, render or touch files. For a layer's Source Text,
Position, Scale, Opacity, Rotation and Anchor Point use these helpers (EffectCraft does not know every After Effects
shortcut): cfProp(layer, name) gives the property, cfSet(layer, name, value), cfKeys(layer, name, [[seconds, value],
...]), cfStyle(textLayer, sizePx, [r, g, b]) sets the text's size and colour. Keep shots short and readable; they
play at "at_s" seconds over the video."""


def _catalog(film, project) -> list[dict]:
    try:
        cmds = film.commands()
    except CraftError:
        return [{"id": c, "params": ""} for c in sorted(ALLOWED)]
    out = []
    for c in cmds:
        cid = c.get("id") if isinstance(c, dict) else None
        if cid in ALLOWED:
            out.append({"id": cid, "label": c.get("label", ""), "params": str(c.get("params") or "")[:600]})
    return out


def _names(film, project, command: str, params: dict, field: str = "name", limit: int = 120) -> list[str]:
    try:
        got = film.exec(project, command, params)
    except CraftError:
        return []
    rows = got if isinstance(got, list) else (got.get("effects") or got.get("presets") or got.get("items") or []) \
        if isinstance(got, dict) else []
    names = []
    for r in rows:
        if isinstance(r, str):
            names.append(r)
        elif isinstance(r, dict) and (r.get("id") or r.get(field)):
            names.append(str(r.get("id") or r.get(field)))
    return names[:limit]


def sequence_rows(film, edit, words_by_asset: dict, plan: dict) -> list[dict]:
    """The clips the AI may edit: FilmCraft id, track, seconds on the timeline, and what is said."""
    from . import finish

    fps = edit.timeline.fps
    segs = {s["clip_id"]: s for s in engine.render_timeline(plan, fps)}
    words = engine.output_words(plan, words_by_asset, list(segs.values()))
    rows = []
    for c in finish.match(edit.timeline.otio, film.inspect(edit.project)):
        if c["id"] is None:
            continue
        a, b = c["start"] / fps, (c["start"] + c["frames"]) / fps
        said = " ".join(w["w"] for w in words if a <= w["start"] < b)[:160]
        m = c["meta"]
        what = m.get("kind") or m.get("role") or ("picture over the video" if m.get("overlay_id") else
                                                   "sound" if c["kind"] == "Audio" else "clip")
        rows.append({"clip": c["id"], "track": c["track"], "what": what, "from_s": round(a, 2), "to_s": round(b, 2),
                     **({"said": said} if said and c["track"] == "Video 1" else {})})
    return rows


def build_prompt(plan: dict, edit, rows: list[dict], catalog: list[dict], effects: list[str],
                 looks: list[str]) -> str:
    tl = edit.timeline
    brief = {"title": (plan.get("title") or {}).get("text", ""), "width": tl.width, "height": tl.height,
             "fps": tl.fps, "seconds": round(tl.frames / tl.fps, 2), "captions": bool(tl.counts.get("captions"))}
    return "\n".join([
        "The video: " + json.dumps(brief, ensure_ascii=False),
        "The sequence (FilmCraft clip ids):", json.dumps(rows[:120], ensure_ascii=False),
        "Tools you may use (id, parameters):", json.dumps(catalog, ensure_ascii=False),
        "Video effects (for effects.apply): " + ", ".join(effects[:120]),
        "Colour looks (for lumetri.applyPreset): " + ", ".join(looks[:60]),
        ANSWER])


def parse(raw: str) -> dict:
    text = (raw or "").strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("The AI's answer had no JSON object.")
    got = json.loads(text[a:b + 1])
    if not isinstance(got, dict):
        raise ValueError("The AI's answer was not an object.")
    return got


def _safe(value, key: str = "") -> bool:
    if isinstance(value, dict):
        return all(k not in FILE_KEYS and _safe(v, k) for k, v in value.items())
    if isinstance(value, list):
        return all(_safe(v, key) for v in value)
    if isinstance(value, str):
        return not _PATHISH.search(value.strip()) and ".." not in value and len(value) <= 2000
    return isinstance(value, (int, float, bool)) or value is None


def check_steps(steps: object, clip_ids: set) -> tuple[list[dict], list[str]]:
    """The steps that may run, and why the others may not."""
    ok, refused = [], []
    if not isinstance(steps, list):
        return [], ["the steps were not a list"]
    for n, s in enumerate(steps[:MAX_STEPS], 1):
        if not isinstance(s, dict) or not isinstance(s.get("id"), str):
            refused.append(f"step {n}: not a tool call")
            continue
        params = s.get("params") or {}
        if s["id"] not in ALLOWED:
            refused.append(f"step {n}: {s['id']} is not a finishing tool")
            continue
        if not isinstance(params, dict) or not _safe(params):
            refused.append(f"step {n}: {s['id']} names a file or address")
            continue
        ids = ([params["clip"]] if "clip" in params else []) + list(params.get("clips") or [])
        if any(i not in clip_ids for i in ids):
            refused.append(f"step {n}: {s['id']} names a clip that is not in this sequence")
            continue
        ok.append({"id": s["id"], "params": params, "for": f"AI: {str(s.get('why') or '')[:120]}"})
    if isinstance(steps, list) and len(steps) > MAX_STEPS:
        refused.append(f"{len(steps) - MAX_STEPS} steps over the limit of {MAX_STEPS}")
    return ok, refused


def finish(film, effect, edit, plan: dict, words_by_asset: dict, settings: dict) -> dict:
    """Ask the AI service for finishing steps and shots, check them and run them on the project."""
    from ..pipeline import llm

    provider = settings.get("ai_provider", "heuristic")
    if provider not in llm.PROVIDERS or not settings.get("craft_ai_finish", True):
        return {"used": False, "why": "no AI service is set up" if provider not in llm.PROVIDERS else "turned off"}
    try:
        rows = sequence_rows(film, edit, words_by_asset, plan)
        catalog = _catalog(film, edit.project)
        effects = _names(film, edit.project, "effects.list", {"kind": "Video"})
        looks = _names(film, edit.project, "lumetri.presets", {})
        prompt = build_prompt(plan, edit, rows, catalog, effects, looks)
        answer = parse(llm.complete(settings, prompt, system=SYSTEM, task="filmcraft_finish"))
    except Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - the AI's finishing is optional: the FilmCraft edit stands without it
        return {"used": False, "why": (str(exc) or type(exc).__name__)[:300]}
    steps, refused = check_steps(answer.get("steps"), {r["clip"] for r in rows})
    results = film.run_steps(edit.project, steps) if steps else []
    edit.steps += steps
    edit.results += results
    made = []
    tl = edit.timeline
    for n, shot in enumerate((answer.get("shots") or [])[:MAX_SHOTS] if effect else []):
        if not isinstance(shot, dict):
            continue
        try:
            at = max(0.0, min(tl.frames / tl.fps - 0.5, float(shot.get("at_s") or 0)))
            secs = max(0.5, min(float(shot.get("seconds") or 3), tl.frames / tl.fps - at))
            got = shots.script_shot(effect, edit.folder / "shots", str(shot.get("name") or f"Shot {n + 1}"),
                                    str(shot.get("script") or ""), tl.width, tl.height, tl.fps, secs)
            from .finish import place_shot

            item = place_shot(film, edit.project, got["path"])
            placed = film.run_steps(edit.project, [{"id": "timeline.place", "params": {
                "item": item, "track": "new", "frame": round(at * tl.fps), "audio": False}}])
            if not placed[0]["ok"]:
                raise CraftError(placed[0]["error"])
            made.append({**got, "path": str(got["path"]), "at_s": at, "use": "over the video"})
        except (CraftError, OSError, TypeError, ValueError) as exc:
            refused.append(f"shot {n + 1}: {str(exc)[:160]}")
    edit.shots += made
    return {"used": True, "provider": llm.provider_label(settings), "summary": str(answer.get("summary") or "")[:300],
            "steps": len(steps), "failed": [r["error"] for r in results if not r["ok"]][:20], "refused": refused,
            "shots": len(made)}


def disclosure(settings: dict) -> str:
    """What the AI finishing pass sends, and where (shown in Settings before it is used)."""
    from ..pipeline import llm
    from ..studio import edit_requests

    provider = settings.get("ai_provider", "heuristic")
    if provider not in llm.PROVIDERS or not settings.get("craft_ai_finish", True):
        return ""
    what = ("FilmCraft's clip list with times, the words said in each clip, the video's title, size and length, and "
            "FilmCraft's tool list. Never the video or the sound.")
    label = llm.provider_label(settings)
    if edit_requests._local(settings, provider):
        return f"Stays on this computer: {label} at a local address is sent {what}"
    return f"Sent over the internet to {label}: {what}"
