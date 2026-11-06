"""Effects shots made in EffectCraft and placed in the FilmCraft edit.

A shot is an EffectCraft composition built by an After Effects-style script (EffectCraft's scripting sandbox: a script
reads only its own folder, writes no files and has no network), rendered by `effectcraft-cli render` to ProRes
(4444 with transparency for shots laid over the video), then imported into the FilmCraft project.

* `title_shot`: the opening title card, animated: the title fades and settles in over the card's dark background.
* `script_shot`: a shot the AI wrote (ai.py), laid over the video with its transparency.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .runner import CraftError, EffectCraft

MAX_SCRIPT = 24_000
BG = (11 / 255, 13 / 255, 20 / 255)  # the title card's colour in the FFmpeg engine (0x0B0D14)


def _js(value) -> str:
    """A JavaScript literal (JSON is valid JavaScript; line and paragraph separators are escaped too)."""
    return json.dumps(value, ensure_ascii=True)


def prelude(name: str, width: int, height: int, fps: int, seconds: float, background: tuple | None) -> str:
    lines = [f"var W = {int(width)}, H = {int(height)}, FPS = {int(fps)}, DUR = {seconds:.4f};",
             f"var comp = app.project.items.addComp({_js(name)}, W, H, 1, DUR, FPS);"]
    if background:
        r, g, b = background
        lines += [f"comp.bgColor = [{r:.5f}, {g:.5f}, {b:.5f}];",
                  f"comp.layers.addSolid([{r:.5f}, {g:.5f}, {b:.5f}], \"Background\", W, H, 1, DUR);"]
    return "\n".join(lines) + "\n"


TITLE_BODY = """
var t = comp.layers.addText(TITLE);
var src = t.property("Source Text");
var doc = src.value;
doc.fontSize = Math.round(H * 0.07);
doc.fillColor = [1, 1, 1];
doc.applyFill = true;
doc.justification = ParagraphJustification.CENTER_JUSTIFY;
src.setValue(doc);
var tr = t.property("Transform");
tr.property("Position").setValue([W / 2, H / 2 + doc.fontSize * 0.35]);
var op = tr.property("Opacity");
op.setValueAtTime(0, 0);
op.setValueAtTime(0.7, 100);
var sc = tr.property("Scale");
sc.setValueAtTime(0, [90, 90]);
sc.setValueAtTime(1.2, [100, 100]);
var bar = comp.layers.addSolid([0.36, 0.88, 0.90], "Accent", Math.round(W * 0.28), Math.max(4, Math.round(H * 0.004)), 1, DUR);
var btr = bar.property("Transform");
btr.property("Position").setValue([W / 2, H / 2 + doc.fontSize * 0.9]);
var bsc = btr.property("Scale");
bsc.setValueAtTime(0.3, [0, 100]);
bsc.setValueAtTime(1.1, [100, 100]);
"""


def _render(effect: EffectCraft, folder: Path, script: str, comp: str, alpha: bool) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(script.encode()).hexdigest()[:12]
    js = folder / f"{comp.lower()}-{digest}.jsx"
    js.write_text(script, encoding="utf-8")
    project = folder / f"{comp.lower()}-{digest}.ecproj"
    out = folder / f"{comp.lower()}-{digest}.mov"
    out.unlink(missing_ok=True)
    effect.script(js, project)
    effect.render(project, comp, out, alpha=alpha)
    return out


def title_shot(effect: EffectCraft, folder: Path, text: str, width: int, height: int, fps: int,
               frames: int) -> dict:
    """The opening title card as an animated shot, a second longer than the title's place in the edit (its
    dissolve reaches into that extra time)."""
    seconds = (frames + fps) / fps
    script = prelude("Title", width, height, fps, seconds, BG) + f"var TITLE = {_js(text[:120])};\n" + TITLE_BODY
    out = _render(effect, folder, script, "Title", alpha=False)
    return {"path": out, "seconds": seconds, "app": "EffectCraft", "what": "Animated title"}


def script_shot(effect: EffectCraft, folder: Path, name: str, body: str, width: int, height: int, fps: int,
                seconds: float) -> dict:
    """A shot the AI scripted: its body adds layers to `comp` (already W x H at FPS, DUR seconds, transparent)."""
    if not body.strip() or len(body) > MAX_SCRIPT:
        raise CraftError("The effect's script is empty or too long.")
    if any(bad in body for bad in ("system.callSystem", "new File", "new Folder", "Socket", "$.evalFile",
                                    "#include", "app.project.save", "renderQueue")):
        raise CraftError("The effect's script uses something shots may not (files, programs, the network, renders).")
    script = prelude("Shot", width, height, fps, max(0.5, min(20.0, seconds)), None) + body + "\n"
    out = _render(effect, folder, script, "Shot", alpha=True)
    return {"path": out, "seconds": seconds, "app": "EffectCraft", "what": name[:80]}
