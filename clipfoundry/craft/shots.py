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


# Helpers every shot script gets. EffectCraft releases differ in which After Effects shortcuts they know (0.9 has no
# `layer.property("Source Text")`), so properties are looked up by their match names first, then by display names.
# Anything a script could not set is listed in CF.missing, which the script's result reports.
HELPERS = r"""
var CF = {missing: []};
var CF_MATCH = {"Source Text": ["ADBE Text Properties", "ADBE Text Document", "Text"],
  "Position": ["ADBE Transform Group", "ADBE Position", "Transform"],
  "Scale": ["ADBE Transform Group", "ADBE Scale", "Transform"],
  "Opacity": ["ADBE Transform Group", "ADBE Opacity", "Transform"],
  "Rotation": ["ADBE Transform Group", "ADBE Rotate Z", "Transform"],
  "Anchor Point": ["ADBE Transform Group", "ADBE Anchor Point", "Transform"]};
function cfProp(layer, name) {
  var m = CF_MATCH[name] || [null, null, null];
  var ways = [function () { return layer.property(m[0]).property(m[1]); },
              function () { return layer.property(m[2]).property(name); },
              function () { return layer.property(name); }];
  if (name === "Source Text") ways.push(function () { return layer.text.sourceText; });
  for (var i = 0; i < ways.length; i++) {
    try { var p = ways[i](); if (p) return p; } catch (e) {}
  }
  CF.missing.push(name);
  return null;
}
function cfSet(layer, name, value) {
  var p = cfProp(layer, name);
  if (p) { try { p.setValue(value); } catch (e) { CF.missing.push(name + ": " + e.message); } }
  return p;
}
function cfKeys(layer, name, keys) {
  var p = cfProp(layer, name);
  for (var i = 0; p && i < keys.length; i++) {
    try { p.setValueAtTime(keys[i][0], keys[i][1]); } catch (e) { CF.missing.push(name + " key: " + e.message); }
  }
  return p;
}
function cfStyle(layer, size, color) {
  var p = cfProp(layer, "Source Text");
  if (!p) return false;
  try {
    var doc = p.value;
    doc.fontSize = size;
    doc.fillColor = color;
    doc.applyFill = true;
    try { doc.justification = ParagraphJustification.CENTER_JUSTIFY; } catch (e) {}
    p.setValue(doc);
    return true;
  } catch (e) {
    CF.missing.push("text style: " + e.message);
    return false;
  }
}
"""

# The script's last value, which EffectCraft reports back: "ok", or what could not be set.
RESULT = 'CF.missing.length ? "missing: " + CF.missing.join("; ") : "ok";\n'


def prelude(name: str, width: int, height: int, fps: int, seconds: float, background: tuple | None) -> str:
    lines = [f"var W = {int(width)}, H = {int(height)}, FPS = {int(fps)}, DUR = {seconds:.4f};",
             f"var comp = app.project.items.addComp({_js(name)}, W, H, 1, DUR, FPS);"]
    if background:
        r, g, b = background
        lines += [f"comp.bgColor = [{r:.5f}, {g:.5f}, {b:.5f}];",
                  f"comp.layers.addSolid([{r:.5f}, {g:.5f}, {b:.5f}], \"Background\", W, H, 1, DUR);"]
    return HELPERS + "\n".join(lines) + "\n"


TITLE_BODY = """
var FS = Math.round(H * 0.07);
var t = comp.layers.addText(TITLE);
cfStyle(t, FS, [1, 1, 1]);
cfSet(t, "Position", [W / 2, H / 2 + FS * 0.35]);
cfKeys(t, "Opacity", [[0, 0], [0.7, 100]]);
cfKeys(t, "Scale", [[0, [90, 90]], [1.2, [100, 100]]]);
var bar = comp.layers.addSolid([0.36, 0.88, 0.90], "Accent", Math.round(W * 0.28), Math.max(4, Math.round(H * 0.004)), 1, DUR);
cfSet(bar, "Position", [W / 2, H / 2 + FS * 0.9]);
cfKeys(bar, "Scale", [[0.3, [0, 100]], [1.1, [100, 100]]]);
"""

TITLE_COMP, SHOT_COMP = "ClipForge Title", "ClipForge Shot"


def _render(effect: EffectCraft, folder: Path, script: str, comp: str, alpha: bool) -> tuple[Path, str]:
    """Build and render one shot: (the file, the script's own report: "ok" or what it could not set)."""
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(script.encode()).hexdigest()[:12]
    stem = f"{comp.lower().replace(' ', '-')}-{digest}"
    js = folder / f"{stem}.jsx"
    js.write_text(script + RESULT, encoding="utf-8")
    project = folder / f"{stem}.ecproj"
    out = folder / f"{stem}.mov"
    out.unlink(missing_ok=True)
    got = effect.script(js, project)
    effect.render(project, comp, out, alpha=alpha)
    return out, str(got.get("result") if got.get("result") is not None else "")[:300]


def title_shot(effect: EffectCraft, folder: Path, text: str, width: int, height: int, fps: int,
               frames: int) -> dict:
    """The opening title card as an animated shot, a second longer than the title's place in the edit (its
    dissolve reaches into that extra time)."""
    seconds = (frames + fps) / fps
    script = prelude(TITLE_COMP, width, height, fps, seconds, BG) + f"var TITLE = {_js(text[:120])};\n" + TITLE_BODY
    out, checks = _render(effect, folder, script, TITLE_COMP, alpha=False)
    return {"path": out, "seconds": seconds, "app": "EffectCraft", "what": "Animated title", "checks": checks}


def script_shot(effect: EffectCraft, folder: Path, name: str, body: str, width: int, height: int, fps: int,
                seconds: float) -> dict:
    """A shot the AI scripted: its body adds layers to `comp` (already W x H at FPS, DUR seconds, transparent)."""
    if not body.strip() or len(body) > MAX_SCRIPT:
        raise CraftError("The effect's script is empty or too long.")
    if any(bad in body for bad in ("system.callSystem", "new File", "new Folder", "Socket", "$.evalFile",
                                    "#include", "app.project.save", "renderQueue")):
        raise CraftError("The effect's script uses something shots may not (files, programs, the network, renders).")
    script = prelude(SHOT_COMP, width, height, fps, max(0.5, min(20.0, seconds)), None) + body + "\n"
    out, checks = _render(effect, folder, script, SHOT_COMP, alpha=True)
    return {"path": out, "seconds": seconds, "app": "EffectCraft", "what": name[:80], "checks": checks}
