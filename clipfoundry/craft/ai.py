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

A model on this computer (the built-in model, Ollama, LM Studio) reads about 8,000 tokens at a time, so its request is
made shorter until it fits (shorter tool descriptions and quotes, fewer effect and look names, then fewer clips), it is
asked for at most 10 steps, and its answer is capped at LOCAL_ANSWER_TOKENS. An answer cut off there still gives the
steps it finished; a step repeated word for word runs once.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import re

from ..studio import engine
from ..studio.jobs import Canceled
from . import shots
from .runner import CraftError

log = logging.getLogger("clipfoundry.craft.ai")

MAX_STEPS = 40
MAX_SHOTS = 2
MEMORY_CHARS = 800  # what the owner told ClipForge AI (brain/memories.py), inside the request's limit
KNOWHOW_CHARS = 1500  # the built-in playbooks for finishing (brain/knowhow.py: colour, effects, sound), inside the limit
LOCAL_CONTEXT = 8192  # tokens: the built-in model's context (builtin_ai.CONTEXT), also asked of Ollama
LOCAL_PROMPT_CHARS = 14_000  # about 4,000 tokens, leaving the rest of LOCAL_CONTEXT for the answer
REMOTE_PROMPT_CHARS = 40_000
LOCAL_TIMEOUT_S = 600.0  # a model on this computer without a graphics card can take minutes
LOCAL_ANSWER_TOKENS = 1200  # a small model can repeat itself until the time-out; this ends its answer
LOCAL_STEPS = 10
SHORT = f"Keep the answer short: at most {LOCAL_STEPS} steps and one shot, each step once."
# How the request is shortened, step by step: (characters of each tool's parameters, of what is said in a clip,
# effect names, look names, clips)
SHORTER = [(600, 160, 120, 60, 120), (240, 100, 60, 30, 80), (120, 60, 30, 20, 60), (0, 40, 20, 12, 40)]
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="filmcraft-ai")
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
_PATHISH = re.compile(r"^(?:/|~|\\|[A-Za-z]:[\\/]|file:|[a-z][a-z0-9+.-]*://)", re.I)  # \ too: \/server/share

SYSTEM = """You finish video edits in FilmCraft, a professional video editor, by choosing its tools. The cut (which
clips, in which order, how long) is final; you only improve how it looks and sounds: colour, effects with keyframes,
transitions, speed ramps, titles and shapes, caption style, sound clean-up. You can also ask EffectCraft (motion
graphics) for up to two effects shots, which are laid over the video. Correct before you grade, pick the look by
the mood, keep only effects that serve the story and give each its sound, and keep the voice first in the mix.
Answer with one JSON object and nothing else."""

ANSWER = """Answer format:
{"summary": "one sentence for the person: what you did",
 "steps": [{"id": "<tool id>", "params": {...}, "why": "short reason"}],
 "shots": [{"name": "Lower third", "at_s": 3.0, "seconds": 4.0, "script": "<After Effects ExtendScript body>"}]}
Steps look like these (clip ids from the sequence, names from the lists above):
{"id": "lumetri.applyPreset", "params": {"name": "<a colour look>", "clips": [12]}, "why": "warmer skin"}
{"id": "effects.apply", "params": {"clips": [12], "effect": "<a video effect>"}, "why": "soft glow"}
{"id": "effects.setParam", "params": {"clip": 12, "effect": "motion", "param": "scale", "value": 108, "frame": 90,
 "keyframe": true}, "why": "slow push-in"}
{"id": "sequence.applyVideoTransition", "params": {"clip": 12, "effect": "Cross Dissolve", "frames": 15, "edge": "in"},
 "why": "softer cut"}
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


def local_model(settings: dict) -> bool:
    """The AI runs on this computer (the built-in model, or Ollama / LM Studio at a local address)."""
    from ..pipeline import llm

    provider = settings.get("ai_provider", "heuristic")
    return provider in llm.LOCAL_PROVIDERS and llm.is_local(settings, provider)


def prompt_limit(settings: dict) -> int:
    """How long the request may be: a model on this computer reads about 8,000 tokens at a time."""
    return LOCAL_PROMPT_CHARS if local_model(settings) else REMOTE_PROMPT_CHARS


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[:max(0, n - 1)].rstrip() + "…"


def _fewer(rows: list[dict], n: int) -> list[dict]:
    """At most n clips, in their order: the main video's clips first, then pictures over it, then sound."""
    if len(rows) <= n:
        return rows

    def rank(r: dict) -> int:
        return 0 if r["track"] == "Video 1" else 2 if r["what"] == "sound" or "Sound" in r["track"] or \
            r["track"] in ("Voiceover", "Music") else 1

    keep = set(sorted(range(len(rows)), key=lambda i: (rank(rows[i]), i))[:n])
    return [r for i, r in enumerate(rows) if i in keep]


def _prompt(brief: dict, rows: list[dict], catalog: list[dict], effects: list[str], looks: list[str], short: bool,
            params_n: int, said_n: int, effects_n: int, looks_n: int, rows_n: int, memories: str = "",
            knowhow: str = "") -> str:
    rows = [{**r, "said": _cut(r["said"], said_n)} if r.get("said") else r for r in _fewer(rows, rows_n)]
    tools = [{"id": c["id"], **({"label": c["label"]} if c.get("label") else {}),
              **({"params": _cut(c["params"], params_n)} if params_n and c.get("params") else {})} for c in catalog]
    return "\n".join([
        "The video: " + json.dumps(brief, ensure_ascii=False),
        *([memories] if memories else []),
        *([knowhow] if knowhow else []),
        "The sequence (FilmCraft clip ids):", json.dumps(rows, ensure_ascii=False),
        "Tools you may use (id, parameters):", json.dumps(tools, ensure_ascii=False),
        # JSON lists: FilmCraft's names have commas in them ("Teal Shadows, Warm Skin")
        "Video effects (for effects.apply): " + json.dumps(effects[:effects_n], ensure_ascii=False),
        "Colour looks (for lumetri.applyPreset name): " + json.dumps(looks[:looks_n], ensure_ascii=False),
        ANSWER + ("\n" + SHORT if short else "")])


def build_prompt(plan: dict, edit, rows: list[dict], catalog: list[dict], effects: list[str],
                 looks: list[str], limit: int | None = None, short: bool = False, memories: str = "",
                 knowhow: str = "") -> str:
    """The request; with `limit`, made shorter step by step (SHORTER, then fewer clips) until it fits. `short` asks a
    model on this computer for a short answer; `memories` is the brain's block (brain.Recall.prompt) and `knowhow`
    the built-in playbooks for finishing (brain.knowhow.Picked.prompt)."""
    tl = edit.timeline
    brief = {"title": (plan.get("title") or {}).get("text", ""), "width": tl.width, "height": tl.height,
             "fps": tl.fps, "seconds": round(tl.frames / tl.fps, 2), "captions": bool(tl.counts.get("captions"))}
    text = ""
    for step in SHORTER:
        text = _prompt(brief, rows, catalog, effects, looks, short, *step, memories=memories, knowhow=knowhow)
        if limit is None or len(text) <= limit:
            return text
    n = SHORTER[-1][-1]
    while len(text) > limit and n > 8:  # a long video: the first clips that fit
        n = max(8, n * 2 // 3)
        text = _prompt(brief, rows, catalog, effects, looks, short, *SHORTER[-1][:-1], n, memories=memories,
                       knowhow=knowhow)
    return text


def _knowhow(plan: dict):
    """The built-in playbooks for finishing this video (brain/knowhow.py): colour, effects and sound by default,
    or what the title's words pick. Never fails the pass."""
    from ..brain import knowhow

    try:
        title = str((plan.get("title") or {}).get("text") or "")
        return knowhow.select(title, "finish", limit=2, budget_chars=KNOWHOW_CHARS)
    except Exception:  # noqa: BLE001
        log.exception("know-how failed")
        return knowhow.Picked()


def _recall(plan: dict, context: dict | None):
    """The owner's rules and facts that apply to finishing this video (docs/clipforge/CLIPFORGE_AI.md)."""
    from .. import brain

    if not context or not context.get("workspace_id"):
        return brain.Recall()
    title = str((plan.get("title") or {}).get("text") or "")
    try:
        return brain.recall(f"{title} finishing the look and sound: colour, effects, transitions, titles, captions, "
                            "music".strip(), context["workspace_id"], project_id=context.get("project_id", ""),
                            mode="video", kinds=("rule", "fact"), limit=5, budget_chars=MEMORY_CHARS)
    except Exception:  # noqa: BLE001 - the brain is optional for the pass
        log.exception("recall failed")
        return brain.Recall()


def _remember(context: dict | None, rec, steps: list[dict], results: list[dict], summary: str) -> None:
    """Record which memories the pass used, and what it did, as an episode of this video."""
    from .. import brain

    if not context or not context.get("workspace_id"):
        return
    try:
        if rec.ids:
            brain.record_use(context["workspace_id"], rec.ids, "filmcraft", context.get("project_id", ""))
        landed = sum(1 for r in results if r.get("ok"))
        if landed:
            brain.episode(context["workspace_id"], f"ClipForge AI finished the edit in FilmCraft: {landed} of "
                          f"{len(steps)} steps landed" + (f" ({summary[:160]})" if summary else ""),
                          project_id=context.get("project_id", ""), data={"steps": len(steps), "landed": landed})
    except Exception:  # noqa: BLE001
        log.exception("the FilmCraft pass was not remembered")


def ask(settings: dict, prompt: str, cancelled=None) -> str:
    """The AI service's answer; a model on this computer may take minutes, and the job can still be cancelled."""
    from ..pipeline import llm

    call = _pool.submit(llm.complete, settings, prompt, system=SYSTEM, task="filmcraft_finish",
                        num_ctx=LOCAL_CONTEXT, timeout=LOCAL_TIMEOUT_S, json_object=True,
                        max_tokens=LOCAL_ANSWER_TOKENS if local_model(settings) else None)
    while True:
        try:
            return call.result(timeout=1.0)
        except concurrent.futures.TimeoutError:
            if cancelled and cancelled():
                call.cancel()
                raise Canceled() from None


def parse(raw: str) -> dict:
    """The answer's object; an answer cut off at its length limit gives the summary and the steps it finished
    (`cut_off`), and the shots are left out."""
    text = (raw or "").strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0:
        raise ValueError("The AI's answer had no JSON object.")
    if b > a:
        try:
            got = json.loads(text[a:b + 1])
        except ValueError:
            got = None
        if got is not None:
            if not isinstance(got, dict):
                raise ValueError("The AI's answer was not an object.")
            return got
    got = _finished_part(text[a:])
    if not got["steps"]:
        raise ValueError("The AI's answer was cut off before its first step.")
    return got


def _finished_part(text: str) -> dict:
    dec = json.JSONDecoder()
    out: dict = {"steps": [], "cut_off": True}
    m = re.search(r'"summary"\s*:\s*', text)
    if m:
        try:
            out["summary"] = dec.raw_decode(text, m.end())[0]
        except ValueError:
            pass
    m = re.search(r'"steps"\s*:\s*\[', text)
    i = m.end() if m else len(text)
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] == "]":
            break
        try:
            step, i = dec.raw_decode(text, i)
        except ValueError:
            break
        out["steps"].append(step)
    return out


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
    ok, refused, seen = [], [], set()
    if not isinstance(steps, list):
        return [], ["the steps were not a list"]
    for n, s in enumerate(steps[:MAX_STEPS], 1):
        if not isinstance(s, dict) or not isinstance(s.get("id"), str):
            refused.append(f"step {n}: not a tool call")
            continue
        params = s.get("params") or {}
        same = json.dumps([s["id"], params], sort_keys=True, default=str)
        if same in seen:
            refused.append(f"step {n}: the same as an earlier step")
            continue
        seen.add(same)
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


_NO_PARAM = re.compile(r"has no param `([^`]+)`")
_NEEDED = {"clip", "clips", "effect", "name", "param", "value", "item", "text"}


def without_unknown(step: dict, error: str) -> dict | None:
    """The step without the parameter FilmCraft says it does not have (a small model often adds one, such as a
    transition's "duration"), or None when that would not leave a step worth trying again. FilmCraft checks
    parameters before it changes anything, so the failed try left nothing behind."""
    m = _NO_PARAM.search(error or "")
    if not m:
        return None
    k, p = m.group(1), dict(step.get("params") or {})
    inner = p.get("params")
    if isinstance(inner, dict) and k in inner:
        p["params"] = {a: b for a, b in inner.items() if a != k}
        if not p["params"]:
            p.pop("params")
    elif k in p and k not in _NEEDED:
        p.pop(k)
    else:
        return None
    return {**step, "params": p, "for": f"{step.get('for', '')} (without `{k}`)".strip()}


def run_checked(film, project, steps: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run the steps; a step that failed only on a parameter FilmCraft does not have runs once more without it.
    The steps as they ran, and their results."""
    steps = list(steps)
    results = film.run_steps(project, steps) if steps else []
    again = [(i, fixed) for i, (s, r) in enumerate(zip(steps, results))
             if not r.get("ok") and (fixed := without_unknown(s, r.get("error", "")))]
    if again:
        for (i, fixed), r in zip(again, film.run_steps(project, [f for _, f in again])):
            if r.get("ok"):
                steps[i], results[i] = fixed, r
    return steps, results


def usable(settings: dict) -> bool:
    """An AI service is set up (the built-in model counts once its engine and a level are downloaded)."""
    from ..pipeline import llm

    provider = settings.get("ai_provider", "heuristic")
    if provider not in llm.PROVIDERS:
        return False
    if provider == "builtin":
        from .. import builtin_ai

        return builtin_ai.ready(settings)
    return True


def finish(film, effect, edit, plan: dict, words_by_asset: dict, settings: dict, context: dict | None = None) -> dict:
    """Ask the AI service for finishing steps and shots, check them and run them on the project. `context` names
    the workspace and project: the owner's memories are read for the request and what happened is remembered."""
    from ..pipeline import llm

    provider = settings.get("ai_provider", "heuristic")
    if not settings.get("craft_ai_finish", True):
        return {"used": False, "why": "turned off"}
    if not usable(settings):
        return {"used": False, "why": "the built-in model is not downloaded yet" if provider == "builtin" else
                "no AI service is set up"}
    rec = _recall(plan, context)
    know = _knowhow(plan)
    try:
        rows = sequence_rows(film, edit, words_by_asset, plan)
        catalog = _catalog(film, edit.project)
        effects = _names(film, edit.project, "effects.list", {"kind": "Video"})
        looks = _names(film, edit.project, "lumetri.presets", {})
        prompt = build_prompt(plan, edit, rows, catalog, effects, looks, prompt_limit(settings),
                              short=local_model(settings), memories=rec.prompt(), knowhow=know.prompt())
        answer = parse(ask(settings, prompt, getattr(film, "cancelled", None)))
    except Canceled:
        raise
    except Exception as exc:  # noqa: BLE001 - the AI's finishing is optional: the FilmCraft edit stands without it
        return {"used": False, "why": (str(exc) or type(exc).__name__)[:300]}
    steps, refused = check_steps(answer.get("steps"), {r["clip"] for r in rows})
    if answer.get("cut_off"):
        refused.append("the answer was cut off at its length limit: the steps it finished were used, no shots")
    steps, results = run_checked(film, edit.project, steps)
    edit.steps += steps
    edit.results += results
    _remember(context, rec, steps, results, str(answer.get("summary") or ""))
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
    return {"used": True, "provider": llm.provider_label(settings), "prompt_chars": len(prompt),
            "summary": str(answer.get("summary") or "")[:300],
            "steps": len(steps), "failed": [r["error"] for r in results if not r["ok"]][:20], "refused": refused,
            "shots": len(made), "memories": rec.snapshot(), "knowhow": know.snapshot()}


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
