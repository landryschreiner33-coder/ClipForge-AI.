"""The robot office's Taser (Landry, 2026-11-26: "make it an actual item you can grab with animations and make sure
when you taze them its animated and stuff and they should have multipal animations when you taze them the same thing
shouldent happen all the time"; later the same day, with two pictures: "Use this as the tazer design and the other as
the missions logo and improve the getting taxed animations").

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
const n = t.ZAP_KINDS.length;
for (let i = 0; i < 100 * n; i++) seq.push(p.next());
out.repeats = seq.filter((k, i) => i && k === seq[i - 1]).length;
out.fullBags = 0;
for (let r = 0; r < 100; r++) if (new Set(seq.slice(r * n, r * n + n)).size === n) out.fullBags++;
const words = [];
for (let i = 0; i < 300; i++) words.push(p.sound(t.ZAP_KINDS[i % n]));
out.wordRepeats = words.filter((w, i) => i && w === words[i - 1]).length;
out.words = [...new Set(words)];
out.fizzleWord = p.sound("fizzle");
const bolt = t.boltPoints({ x: 3, y: 4 }, { x: 60, y: -20 }, 6, 8).split(" ").map(pt => pt.split(",").map(Number));
out.bolt = { count: bolt.length, first: bolt[0], last: bolt[bolt.length - 1],
  finite: bolt.every(pt => pt.length === 2 && pt.every(Number.isFinite)) };
out.shock = {};
for (const k of t.ZAP_KINDS) {
  let rattle = 0, skeleton = 0, flash = 0;
  for (let ms = 0; ms < t.SHOCK_MS; ms += 5) {
    const q = t.zapPose(k, ms);
    if (q.dx) rattle++;
    if (q.xray) skeleton++;
    if (q.tint) flash++;
  }
  out.shock[k] = { rattle, skeleton, flash, sparks: t.zapParticles(k, 40, 42, 7).length };
}
out.fizzleShock = t.zapPose("fizzle", 30).xray;
out.particleKinds = {};
for (const k of ["glitch", "reboot", "rocket"]) {
  const seen = new Set();
  for (let ms = t.SHOCK_MS; ms < t.ZAP_MS[k]; ms += 10) {
    for (const part of t.zapParticles(k, ms, 42, 99)) seen.add(part.kind);
  }
  out.particleKinds[k] = [...seen];
}
out.glitchBands = 0;
for (let ms = t.SHOCK_MS; ms < t.ZAP_MS.glitch; ms += 10) if (t.zapPose("glitch", ms).bands) out.glitchBands++;
out.big = t.BIG_ZAPS;
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
    if (q.dx || q.dy || q.rot || q.sx !== 1 || q.sy !== 1 || q.flip || q.tint || q.xray || q.glitch || q.frame) moved++;
    for (const part of t.zapParticles(k, ms, 42, 4242)) {
      parts++;
      for (const v of Object.values(part)) if (typeof v === "number" && !Number.isFinite(v)) out.bad++;
    }
  }
  out.moving[k] = moved; out.particles[k] = parts;
}
const end = t.zapPose("topple", 999999);
out.restAfterEnd = !end.dx && !end.dy && !end.rot && end.sx === 1 && end.sy === 1 && !end.tint && !end.frame
  && !end.glitch && !end.bands;
out.kinds = t.ZAP_KINDS;
console.log(JSON.stringify(out));
"""


def _node_with_types():
    node = shutil.which("node")
    if not node:
        return None
    probe = subprocess.run([node, "--experimental-strip-types", "-e", "1"], capture_output=True, text=True)
    return node if probe.returncode == 0 else None


@pytest.fixture(scope="module")
def reactions(tmp_path_factory):
    node = _node_with_types()
    if not node:
        pytest.skip("needs Node 22.6 or newer to run the Taser's TypeScript")
    folder = tmp_path_factory.mktemp("taser")
    source = folder / "taser.mts"
    source.write_text(TASER, encoding="utf-8")
    script = folder / "check.mjs"
    script.write_text(CHECK, encoding="utf-8")
    run = subprocess.run([node, "--experimental-strip-types", "--no-warnings", str(script), source.as_uri()],
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_reactions_take_turns_and_every_one_animates(reactions):
    out = reactions
    assert len(out["kinds"]) == 12
    assert {"glitch", "reboot", "rocket"} <= set(out["kinds"])
    assert out["repeats"] == 0, "the same reaction twice in a row"
    assert out["fullBags"] == 100, "every reaction comes up once before any comes back"
    assert out["sameLine"] == 0, "a robot says the same line twice in a row"
    assert out["bad"] == 0
    for kind, frames in out["moving"].items():
        assert frames > 0, f"{kind} does not change how the robot looks"
    for kind in out["kinds"]:
        assert out["particles"][kind] > 0, f"{kind} has nothing flying around the robot"
    assert out["restAfterEnd"]


def test_every_zap_opens_with_a_shock(reactions):
    # the robot rattles, its skeleton and a flash take turns, and sparks fly, whatever the reaction after it
    for kind, shock in reactions["shock"].items():
        assert shock["rattle"] > 0 and shock["skeleton"] > 0 and shock["flash"] > 0, kind
        assert shock["sparks"] > 0, kind
    assert not reactions["fizzleShock"], "a fizzle is too weak for the shock"
    # the new reactions bring their own pieces: glitch pixels, a reboot's loading bar, a rocket's flame
    assert "pixel" in reactions["particleKinds"]["glitch"] and reactions["glitchBands"] > 0
    assert "bar" in reactions["particleKinds"]["reboot"]
    assert "flame" in reactions["particleKinds"]["rocket"]
    assert set(reactions["big"]) <= set(reactions["kinds"]) and len(reactions["big"]) < len(reactions["kinds"])


def test_the_sound_is_written_over_the_robot(reactions):
    assert reactions["wordRepeats"] == 0, "the same sound word twice in a row"
    assert len(reactions["words"]) >= 5 and all(w.endswith("!") for w in reactions["words"])
    assert reactions["fizzleWord"] == "fzz…"
    bolt = reactions["bolt"]
    assert bolt["count"] == 7 and bolt["first"] == [3, 4] and bolt["last"] == [60, -20] and bolt["finite"]
    assert "sfx = picker.current!.sound(kind)" in ITEM
    assert '{b.sfx && <span className="taser-sfx">{b.sfx}</span>}' in ITEM
    # lightning and the ship's jolt are motion: none under Reduced motion
    assert "const bolts = weak || reduce ? [] : lightning(robot, at, x, y);" in ITEM
    assert "if (!ship || reduce) return;" in ITEM
    assert "if (BIG_ZAPS.includes(kind as ZapKind)) jolt();" in ITEM
    assert "useTaser({ enabled: taser, sounds, reduce," in MAP
    assert ".office-world.ship-jolt { animation: ship-jolt" in CSS


def test_the_taser_is_the_owners_picture():
    space = ROOT / "frontend" / "public" / "space"
    for name in ("taser.png", "taser-sparks.png"):
        data = (space / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        assert int.from_bytes(data[16:20], "big") == 400 and int.from_bytes(data[20:24], "big") == 350, name
        assert f'src="/space/{name}"' in ITEM
    # the built app carries them too
    dist = ROOT / "frontend" / "dist" / "space"
    for name in ("taser.png", "taser-sparks.png"):
        assert (dist / name).read_bytes() == (space / name).read_bytes(), name
    # the old drawn Taser is gone
    assert "<polygon" not in ITEM and 'viewBox="-6 -2 32 18"' not in ITEM


def test_missions_has_the_owners_logo():
    ui = (ROOT / "frontend" / "src" / "components" / "ui.tsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert 'missions: "M15.76 4.87A10.11 6.06 -33.56 1 0 20.8 10.17"' in ui
    assert '{SOLID[name] && <path className="icon-solid" d={SOLID[name]} />}' in ui
    assert '<NavLink href="#/missions" icon="missions" label="Missions"' in app


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
