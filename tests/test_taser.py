"""The robot office's Taser (Landry, 2026-11-26: "make it an actual item you can grab with animations and make sure
when you taze them its animated and stuff and they should have multipal animations when you taze them the same thing
shouldent happen all the time").

The reaction logic (frontend/src/office/taser.ts) runs under Node when Node can strip TypeScript types; the rest
checks the source: the Taser is a thing you pick up from its charger, a click on a robot while holding it zaps
instead of opening, and the ship draws the reaction."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OFFICE = ROOT / "frontend" / "src" / "office"
TASER = (OFFICE / "taser.ts").read_text(encoding="utf-8")
ITEM = (OFFICE / "TaserItem.tsx").read_text(encoding="utf-8")
MAP = (OFFICE / "OfficeMap.tsx").read_text(encoding="utf-8")
SCENE = (OFFICE / "StudioScene.ts").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "src" / "space.css").read_text(encoding="utf-8")

CHECK = r"""
const t = await import(process.argv[2]);
const out = {};
const p = new t.ZapPicker();
const seq = [];
for (let i = 0; i < 900; i++) seq.push(p.next());
out.repeats = seq.filter((k, i) => i && k === seq[i - 1]).length;
out.fullBags = 0;
for (let r = 0; r < 100; r++) if (new Set(seq.slice(r * 9, r * 9 + 9)).size === t.ZAP_KINDS.length) out.fullBags++;
out.sameLine = 0;
for (const k of [...t.ZAP_KINDS, "fizzle"]) {
  let prev = null;
  for (let i = 0; i < 12; i++) { const l = p.line(k); if (!l || l === prev) out.sameLine++; prev = l; }
}
out.bad = 0; out.moving = {}; out.particles = {};
for (const k of [...t.ZAP_KINDS, "fizzle"]) {
  let moved = 0, parts = 0;
  for (let ms = 0; ms < t.ZAP_MS[k]; ms += 5) {
    const q = t.zapPose(k, ms);
    for (const v of [q.dx, q.dy, q.rot, q.sx, q.sy]) if (!Number.isFinite(v)) out.bad++;
    if (Math.abs(q.sx) < 0.15 || q.sy < 0.5) out.bad++;
    if (q.dx || q.dy || q.rot || q.sx !== 1 || q.sy !== 1 || q.flip || q.tint || q.xray || q.frame) moved++;
    for (const part of t.zapParticles(k, ms, 42, 4242)) {
      parts++;
      for (const v of Object.values(part)) if (typeof v === "number" && !Number.isFinite(v)) out.bad++;
    }
  }
  out.moving[k] = moved; out.particles[k] = parts;
}
const end = t.zapPose("topple", 999999);
out.restAfterEnd = !end.dx && !end.dy && !end.rot && end.sx === 1 && end.sy === 1 && !end.tint && !end.frame;
out.kinds = t.ZAP_KINDS;
console.log(JSON.stringify(out));
"""


def _node_with_types():
    node = shutil.which("node")
    if not node:
        return None
    probe = subprocess.run([node, "--experimental-strip-types", "-e", "1"], capture_output=True, text=True)
    return node if probe.returncode == 0 else None


def test_reactions_take_turns_and_every_one_animates(tmp_path):
    node = _node_with_types()
    if not node:
        pytest.skip("needs Node 22.6 or newer to run the Taser's TypeScript")
    source = tmp_path / "taser.mts"
    source.write_text(TASER, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(CHECK, encoding="utf-8")
    run = subprocess.run([node, "--experimental-strip-types", "--no-warnings", str(script), source.as_uri()],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert len(out["kinds"]) == 9
    assert out["repeats"] == 0, "the same reaction twice in a row"
    assert out["fullBags"] == 100, "every reaction comes up once before any comes back"
    assert out["sameLine"] == 0, "a robot says the same line twice in a row"
    assert out["bad"] == 0
    for kind, frames in out["moving"].items():
        assert frames > 0, f"{kind} does not change how the robot looks"
    for kind in out["kinds"]:
        assert out["particles"][kind] > 0, f"{kind} has nothing flying around the robot"
    assert out["restAfterEnd"]


def test_the_taser_is_an_item_on_a_charger():
    # it lies on its charger in the Control room, inside the room and clear of COMMAND
    ship = json.loads((ROOT / "frontend" / "src" / "space" / "ship-world.json").read_text(encoding="utf-8"))
    room, command = ship["rooms"]["control"], ship["stations"]["command"]
    dock = {k: int(v) for k, v in re.search(
        r"TASER_DOCK = \{ x: (?P<x>\d+), y: (?P<y>\d+), w: (?P<w>\d+), h: (?P<h>\d+) \}", ITEM).groupdict().items()}
    assert room["x"] < dock["x"] and dock["x"] + dock["w"] < room["x"] + room["w"]
    assert room["y"] < dock["y"] and dock["y"] + dock["h"] < room["y"] + room["h"]
    assert dock["x"] + dock["w"] < command["x"] - 20
    # picked up from the charger or the button under the ship; Escape, the charger or the button puts it back
    assert "taser.pickUp(" in ITEM and "taser.putBack()" in ITEM
    assert 'event.key !== "Escape"' in ITEM
    assert "zapper.held ? zapper.putBack() : zapper.pickUp()" in MAP
    assert "{taser && <TaserDock taser={zapper} />}" in MAP
    # held, it follows the pointer, drawn above the page
    assert "createPortal(" in ITEM and "onPointerMove={zapper.track}" in MAP
    assert '.taser-held.in-hand[data-shown="true"] { visibility: visible; }' in CSS
    assert '.office-map[data-taser="held"] .office-world' in CSS


def test_holding_it_a_click_zaps_instead_of_opening():
    assert "zapper.held ? zapper.zap(c.id, event.detail === 0)" in MAP
    assert "zapper.held ? zapper.miss(event) : onRoom(r.id)" in MAP
    assert "if (zapper.held) { event.preventDefault(); zapper.miss(event); }" in MAP
    # a zap before the Taser has recharged only fizzles
    assert 'const kind: ZapReaction = weak ? "fizzle" : picker.current!.next();' in ITEM
    # the old click-to-arm toggle is gone
    assert "setArmed" not in MAP and "reaction()" not in MAP


def test_the_ship_draws_the_reaction():
    assert "zap: zapOf(a.id, now)" in MAP
    # smooth while a zap plays, and never under Reduced motion
    assert "zapping ? 33 : still ? 250 : 83" in MAP
    assert "if (state.reduce || now - z.start >= ZAP_MS[z.kind]) zaps.delete(id)" in MAP
    assert "const zap = a.zap ? zapPose(a.zap.kind, a.zap.ms) : null;" in SCENE
    assert 't.globalCompositeOperation = "source-atop";' in SCENE
    assert "this.zapped(a.zap, zap, x, y, art.h)" in SCENE
    # sounds only when Sound effects is on
    assert "if (sounds) zapSound(kind);" in ITEM
