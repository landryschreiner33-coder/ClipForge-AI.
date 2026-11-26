/**
 * The robot office's Taser (the owner, 2026-11-25: "clicking it on a robot plays a brief cartoon spark and a funny
 * reaction"; 2026-11-26: "make it an actual item you can grab with animations ... they should have multipal animations
 * when you taze them the same thing shouldent happen all the time", then "improve the getting taxed animations").
 * Purely for fun: nothing is sent anywhere and the robot's job carries on.
 *
 * The Taser lies on its charger in the Control room; you pick it up, carry it over the ship and click a robot. Every
 * zap opens with the shock itself (SHOCK_MS: the robot rattles, its skeleton flashes, arcs crackle round it), then
 * plays one of twelve reactions (ZAP_KINDS), drawn on the ship by StudioScene from zapPose and zapParticles below. A
 * bag deals them, so every reaction comes up once before any comes back, and never the same one twice in a row.
 * Zapping again while the Taser recharges only fizzles. Under Reduced motion the robot stays still and a still spark
 * shows. The sounds play only when Settings → Appearance → Sound effects is on.
 */
import type { FrameName } from "./crew";

export type ZapKind = "jolt" | "xray" | "hop" | "spin" | "topple" | "scorch" | "float" | "boogie" | "overcharge"
  | "glitch" | "reboot" | "rocket";
export type ZapReaction = ZapKind | "fizzle";
export const ZAP_KINDS: ZapKind[] = ["jolt", "xray", "hop", "spin", "topple", "scorch", "float", "boogie", "overcharge",
  "glitch", "reboot", "rocket"];
/** The shock every real zap opens with, before the robot's own reaction. */
export const SHOCK_MS = 360;
/** How long each reaction plays after the shock (ms). */
const TAIL_MS: Record<ZapReaction, number> = {
  jolt: 1300, xray: 1100, hop: 1150, spin: 1350, topple: 2100, scorch: 2000, float: 1800, boogie: 1900,
  overcharge: 1600, glitch: 1400, reboot: 2200, rocket: 1900, fizzle: 900,
};
/** How long each reaction plays on the ship in all (ms). A fizzle has no shock. */
export const ZAP_MS = Object.fromEntries(Object.entries(TAIL_MS)
  .map(([k, v]) => [k, k === "fizzle" ? v : SHOCK_MS + v])) as Record<ZapReaction, number>;
/** The Taser needs this long to recharge after a zap; zapping sooner only fizzles. */
export const RECHARGE_MS = 650;
/** The reactions big enough to jolt the whole ship for a moment. */
export const BIG_ZAPS: ZapKind[] = ["topple", "overcharge", "reboot", "rocket"];

const LINES: Record<ZapReaction, string[]> = {
  jolt: ["Bzzt! My circuits!", "Ow, my bolts!", "That tickles!", "My antenna is buzzing!"],
  xray: ["I can see my own wiring!", "Was that an X-ray?", "My bones are made of cables?", "Don't look at my firmware!"],
  hop: ["Whoa! Who turned on gravity?", "Boing!", "I nearly hit the ceiling!", "My springs went sproing!"],
  spin: ["The room is spinning…", "Wheee… ugh.", "Which way is the console?", "Dizzy. Very dizzy."],
  topple: ["Taking a short reboot…", "I'll just lie here a sec.", "Rebooting my dignity…", "Floor feels nice."],
  scorch: ["Smells like burnt toast.", "*cough* Totally fine.", "I'll put that in my report.", "Static cling! Static cling!"],
  float: ["I'm floating! Put me down!", "Static is holding me up!", "Look, no thrusters!", "Hovering is not in my job!"],
  boogie: ["I can't stop dancing!", "Electric boogie!", "My legs have a mind of their own!", "Is this a dance break?"],
  overcharge: ["FULLY CHARGED!", "I feel 200% powered!", "Was that a firmware update?", "Power level: maximum!"],
  glitch: ["S-s-system err-err-error!", "Who put a bug in me?", "I'm b-b-buffering…", "01001000 01101001!"],
  reboot: ["Rebooting… please wait.", "Turning it off and on again.", "Installing update 1 of 37…",
    "Have you tried restarting me?"],
  rocket: ["We have liftoff!", "I didn't know I had rockets!", "To the stars!", "Coming in hot!"],
  fizzle: ["Was that it?", "Battery low, huh?", "That barely tickled.", "Fizz… nope."],
};
/** The cartoon sound written over the robot. */
const SOUND_WORDS = ["BZZZT!", "ZAP!", "KRZZT!", "FZZAP!", "ZZZAP!", "BZZAP!", "KZZZT!"];

/** Deals the reactions from a shuffled bag: all twelve before any repeats, and never the same one twice in a row.
 * Each reaction's lines take turns too, and so do the sound words. */
export class ZapPicker {
  private bag: ZapKind[] = [];
  private last: ZapKind | null = null;
  private lines = new Map<ZapReaction, number>();
  private word = -1;
  private random: () => number;
  constructor(random: () => number = Math.random) { this.random = random; }

  next(): ZapKind {
    if (!this.bag.length) {
      const bag = [...ZAP_KINDS];
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(this.random() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      // the last of the old bag never opens the new one
      if (bag[bag.length - 1] === this.last) [bag[0], bag[bag.length - 1]] = [bag[bag.length - 1], bag[0]];
      this.bag = bag;
    }
    const kind = this.bag.pop()!;
    this.last = kind;
    return kind;
  }

  line(kind: ZapReaction): string {
    const list = LINES[kind];
    const start = this.lines.has(kind) ? this.lines.get(kind)! + 1 : Math.floor(this.random() * list.length);
    const k = start % list.length;
    this.lines.set(kind, k);
    return list[k];
  }

  /** "BZZZT!", "ZAP!" and the rest, never the same twice in a row. */
  sound(kind: ZapReaction): string {
    if (kind === "fizzle") return "fzz…";
    const step = 1 + Math.floor(this.random() * (SOUND_WORDS.length - 1));
    this.word = this.word < 0 ? Math.floor(this.random() * SOUND_WORDS.length)
      : (this.word + step) % SOUND_WORDS.length;
    return SOUND_WORDS[this.word];
  }
}

/** A jagged lightning line from a to b as SVG points: `steps` pieces, each corner pushed sideways by up to `jag`. */
export function boltPoints(a: { x: number; y: number }, b: { x: number; y: number }, steps: number, jag: number,
  random: () => number = Math.random): string {
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len;
  const points = [a];
  for (let i = 1; i < steps; i++) {
    const t = i / steps, push = (random() * 2 - 1) * jag;
    points.push({ x: a.x + dx * t + nx * push, y: a.y + dy * t + ny * push });
  }
  points.push(b);
  return points.map(p => `${Math.round(p.x)},${Math.round(p.y)}`).join(" ");
}

/** How a zapped robot is drawn at `ms` into its reaction: an offset (world units), a turn, a flip, a squash, a tint,
 * the X-ray look, a glitch (0 to 1, with the sideways shift of each band of the sprite) and the frame to show instead
 * of its own. */
export interface ZapPose {
  dx: number; dy: number; rot: number; flip: boolean; sx: number; sy: number;
  tint: { color: string; alpha: number } | null;
  xray: boolean;
  glitch: number;
  bands: number[] | null;
  frame: FrameName | null;
}
const REST: ZapPose = { dx: 0, dy: 0, rot: 0, flip: false, sx: 1, sy: 1, tint: null, xray: false, glitch: 0,
  bands: null, frame: null };
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const ease = (v: number) => 1 - (1 - clamp01(v)) ** 3;
const easeIn = (v: number) => clamp01(v) ** 2;
const CYAN = "#9ff3ff";
/** a fixed number from 0 to 1 for a moment and a slot, so a jitter holds still within its moment */
const noise = (a: number, b: number) => {
  const v = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return v - Math.floor(v);
};

export function zapPose(kind: ZapReaction, ms: number): ZapPose {
  const p: ZapPose = { ...REST };
  if (ms < 0 || ms >= ZAP_MS[kind]) return p;
  if (kind !== "fizzle" && ms < SHOCK_MS) {
    // the shock: the robot rattles hard, its skeleton and a white flash take turns, its arms fly up
    const k = Math.floor(ms / 30);
    p.dx = (k % 2 ? 3 : -3) * (1 - ms / SHOCK_MS * .4);
    p.dy = k % 3 === 0 ? -2 : 0;
    p.rot = (k % 2 ? 1 : -1) * .05;
    p.sx = 1 + (k % 2 ? .05 : -.03); p.sy = 1 + (k % 2 ? -.04 : .05);
    const phase = Math.floor(ms / 60) % 3;
    p.xray = phase === 0;
    p.tint = phase === 1 ? { color: "#ffffff", alpha: .9 } : phase === 2 ? { color: CYAN, alpha: .7 } : null;
    p.frame = k % 2 ? "work_3" : "work_1";
    return p;
  }
  const t = kind === "fizzle" ? ms : ms - SHOCK_MS;
  const flash = (period: number) => Math.floor(t / period) % 2 === 0;
  switch (kind) {
    case "jolt":
      if (t < 520) {
        // aftershocks, getting smaller
        const fade = 1 - t / 520;
        p.dx = (flash(40) ? 2.5 : -2.5) * fade;
        p.dy = flash(70) ? -1.5 * fade : 0;
        p.tint = flash(80) ? { color: CYAN, alpha: .7 * fade } : null;
        p.frame = flash(120) ? "work_3" : "blink";
      } else p.frame = Math.floor(t / 300) % 2 ? "look_left" : "look_right";
      break;
    case "xray":
      if (t < 700) {
        p.xray = flash(110);
        p.dx = flash(55) ? 1 : -1;
      } else {
        p.tint = { color: "#1a1424", alpha: .55 * (1 - (t - 700) / 400) };
        p.frame = "blink";
      }
      break;
    case "hop": {
      if (t < 90) { p.sx = 1.22; p.sy = .76; break; }
      if (t < 780) {
        const u = (t - 90) / 690;
        p.dy = -Math.sin(Math.PI * u) * 42;
        p.sx = .88; p.sy = 1.16;
        p.rot = Math.sin(Math.PI * u) * .25;
        p.frame = "work_3";
        break;
      }
      const u = (t - 780) / 370;
      p.sx = 1 + .24 * (1 - u); p.sy = 1 - .24 * (1 - u);
      p.frame = "blink";
      break;
    }
    case "spin":
      if (t < 950) {
        p.sx = Math.cos(ease(t / 950) * 5 * Math.PI * 2);  // five turns, fast at first, then slowing down
        if (Math.abs(p.sx) < .18) p.sx = p.sx < 0 ? -.18 : .18;
        p.dy = -Math.sin(Math.PI * t / 950) * 12;
      } else {
        p.rot = Math.sin((t - 950) / 80) * .12;
        p.frame = Math.floor(t / 200) % 2 ? "look_left" : "look_right";
      }
      break;
    case "topple":
      if (t < 280) {
        p.rot = -Math.PI / 2 * easeIn(t / 280);
        p.dx = -4 * easeIn(t / 280);
      } else if (t < 1750) {
        p.rot = -Math.PI / 2; p.dx = -4;
        if (t < 400) p.dy = -Math.sin(Math.PI * (t - 280) / 120) * 3;  // a little bounce on landing
        p.frame = "blink";
        if (t > 900 && t < 1080) p.dx = -4 + (flash(40) ? 1.5 : -1.5);  // a twitch
      } else if (t < 2000) {
        const u = (t - 1750) / 250;
        p.rot = -Math.PI / 2 * (1 - ease(u)); p.dx = -4 * (1 - u);
        p.dy = -Math.sin(Math.PI * u) * 14;
      } else {
        const u = (t - 2000) / 100;
        p.sx = 1 + .14 * (1 - u); p.sy = 1 - .14 * (1 - u);
      }
      break;
    case "scorch": {
      const fade = t > 1550 ? 1 - (t - 1550) / 450 : 1;
      p.tint = { color: "#15100c", alpha: .82 * fade };
      p.frame = Math.floor(t / 650) % 3 === 2 ? "blink" : "idle";
      if (t > 1200 && t < 1550) p.dx = flash(35) ? 2.5 : -2.5;  // shakes the soot off
      break;
    }
    case "float":
      if (t < 1150) {
        const rise = ease(t / 800);
        p.dy = -rise * 28 + Math.sin(t / 150) * 3;
        p.rot = Math.sin(t / 200) * .14;
        p.tint = flash(110) ? { color: CYAN, alpha: .45 } : null;
        p.frame = "work_3";
      } else if (t < 1400) {
        p.dy = -28 + Math.sin(t / 150) * 3;
        p.frame = "look_left";
      } else if (t < 1550) {
        p.dy = -28 * (1 - easeIn((t - 1400) / 150));
        p.frame = "blink";
      } else {
        const u = (t - 1550) / 250;
        p.sx = 1 + .22 * (1 - u); p.sy = 1 - .22 * (1 - u);
      }
      break;
    case "boogie": {
      const beat = Math.floor(t / 230);
      p.dy = -Math.abs(Math.sin(t / 230 * Math.PI)) * 9;
      p.flip = beat % 2 === 1;
      p.rot = (beat % 2 ? -1 : 1) * .16;
      p.dx = (beat % 4 < 2 ? 1 : -1) * 3;
      p.frame = beat % 4 < 2 ? "work_3" : "work_1";
      break;
    }
    case "overcharge": {
      const glow = .4 + .3 * Math.sin(t / 80);
      p.tint = { color: "#ffd23f", alpha: glow * (t > 1250 ? 1 - (t - 1250) / 350 : 1) };
      const grow = Math.sin(Math.PI * clamp01(t / 1100)) * .16;
      p.sx = 1 + grow; p.sy = 1 + grow;
      p.dx = Math.floor(t / 40) % 2 ? .8 : -.8;
      p.frame = "work_3";
      break;
    }
    case "glitch": {
      const g = t < 950 ? 1 : 1 - (t - 950) / 450;
      const moment = Math.floor(t / 70);
      p.glitch = Math.max(0, g) * (noise(moment, 1) > .25 ? 1 : .3);
      p.bands = [0, 1, 2, 3, 4].map(i => (noise(moment, i + 2) - .5) * 10 * p.glitch);
      p.dx = (noise(moment, 9) - .5) * 4 * p.glitch;
      p.frame = noise(moment, 11) > .5 ? "blink" : "work_2";
      break;
    }
    case "reboot":
      if (t < 260) {
        // powers off: slumps and goes dark
        const u = ease(t / 260);
        p.sy = 1 - .16 * u; p.sx = 1 + .06 * u;
        p.rot = .12 * u;
        p.tint = { color: "#05060c", alpha: .6 * u };
        p.frame = "blink";
      } else if (t < 1600) {
        p.sy = .84; p.sx = 1.06; p.rot = .12;
        p.tint = { color: "#05060c", alpha: .6 };
        p.frame = "blink";
      } else if (t < 1760) {
        // powers on with a flash
        p.tint = { color: CYAN, alpha: .85 };
        p.frame = "work_3";
      } else if (t < 2000) {
        const u = (t - 1760) / 240;
        p.dy = -Math.sin(Math.PI * u) * 12;
        p.sy = 1.1 - .1 * u; p.sx = .94 + .06 * u;
        p.frame = "work_3";
      } else p.frame = Math.floor(t / 150) % 2 ? "look_left" : "look_right";
      break;
    case "rocket":
      if (t < 160) {
        p.sx = 1.18; p.sy = .78;  // crouches
        p.frame = "blink";
      } else if (t < 760) {
        const u = ease((t - 160) / 600);
        p.dy = -78 * u;
        p.sx = .86; p.sy = 1.2;
        p.rot = Math.sin(t / 60) * .06;
        p.frame = "work_3";
      } else if (t < 1180) {
        const u = easeIn((t - 760) / 420);
        p.dy = -78 * (1 - u);
        p.rot = u * .5;
        p.frame = "blink";
      } else if (t < 1380) {
        const u = (t - 1180) / 200;
        p.sx = 1 + .3 * (1 - u); p.sy = 1 - .3 * (1 - u);
        p.rot = .5 * (1 - u);
      } else p.frame = Math.floor(t / 180) % 2 ? "look_left" : "look_right";
      break;
    case "fizzle":
      p.frame = t < 450 ? "look_left" : "look_right";
      p.tint = t < 120 ? { color: CYAN, alpha: .35 } : null;
      break;
  }
  return p;
}

/** What flies around a zapped robot, in world units from its feet: sparks, dizzy stars, smoke, dust, music notes,
 * golden rings, crackling arcs, glitch pixels, flames and a loading bar. Pure, so the ship can draw it and a test can
 * check it. */
export type ZapParticle =
  | { kind: "spark"; x: number; y: number; dx: number; dy: number; color: string; alpha: number }
  | { kind: "star" | "note" | "smoke" | "dust" | "flame"; x: number; y: number; size: number; alpha: number }
  | { kind: "pixel"; x: number; y: number; size: number; color: string; alpha: number }
  | { kind: "ring"; x: number; y: number; rx: number; ry: number; alpha: number }
  | { kind: "arc"; points: number[]; alpha: number }
  | { kind: "bar"; x: number; y: number; w: number; progress: number; alpha: number };

export function zapParticles(kind: ZapReaction, ms: number, height: number, seed: number): ZapParticle[] {
  const out: ZapParticle[] = [];
  if (ms < 0 || ms >= ZAP_MS[kind]) return out;
  const head = -height * .78, middle = -height * .5;
  const rand = (k: number) => noise((seed % 997) + .5, k);  // a fixed number per particle, so it keeps its path
  const arcs = (count: number, reach: number, from = 0) => {
    const step = Math.floor(ms / 50);  // the arcs jump about, like real ones
    for (let i = 0; i < count; i++) {
      const a = rand(step * 7 + i + from) * Math.PI * 2, r1 = reach + rand(step + i) * 6, r2 = r1 + 7;
      const x0 = Math.cos(a) * r1, y0 = middle + Math.sin(a) * r1 * 1.4;
      const x2 = Math.cos(a + .6) * r2, y2 = middle + Math.sin(a + .6) * r2 * 1.4;
      out.push({ kind: "arc", points: [x0, y0, (x0 + x2) / 2 + (rand(step + i + 3) - .5) * 10,
        (y0 + y2) / 2 + (rand(step + i + 5) - .5) * 10, x2, y2], alpha: .95 });
    }
  };
  if (kind === "fizzle") {
    if (ms < 140) {
      const t = ms / 140;
      for (let i = 0; i < 4; i++) {
        const a = rand(i) * Math.PI * 2, reach = 8 * ease(t);
        out.push({ kind: "spark", x: Math.cos(a) * reach, y: middle + Math.sin(a) * reach, dx: Math.cos(a) * 4,
          dy: Math.sin(a) * 4, color: "#9ff3ff", alpha: 1 - t });
      }
    }
    if (ms >= 60 && ms < 760) {
      const t = (ms - 60) / 700;
      out.push({ kind: "smoke", x: 0, y: head - 10 * t, size: 2 + t * 4, alpha: (1 - t) * .7 });
    }
    return out;
  }
  if (ms < SHOCK_MS) {
    // the shock: a big burst of sparks, arcs all round the robot and sparks jumping off its antenna
    const t = ms / SHOCK_MS;
    for (let i = 0; i < 14; i++) {
      const a = rand(i) * Math.PI * 2, reach = (16 + rand(i + 20) * 22) * ease(t * 1.6);
      out.push({ kind: "spark", x: Math.cos(a) * reach, y: middle + Math.sin(a) * reach * 1.2, dx: Math.cos(a) * 7,
        dy: Math.sin(a) * 7, color: i % 3 ? "#9ff3ff" : "#fff3a0", alpha: 1 - t * .8 });
    }
    arcs(4, 13);
    const k = Math.floor(ms / 45);
    for (let i = 0; i < 2; i++) {
      const side = i ? 1 : -1, x0 = side * 3, y0 = -height - 1;
      out.push({ kind: "arc", points: [x0, y0, x0 + side * (4 + rand(k + i) * 4), y0 - 4 - rand(k + i + 9) * 4,
        x0 + side * (2 + rand(k + i + 4) * 6), y0 - 10 - rand(k + i + 7) * 4], alpha: 1 });
    }
    return out;
  }
  const t = ms - SHOCK_MS;
  const stars = (from: number, to: number) => {
    if (t < from || t >= to) return;
    const u = (t - from) / 1000, fade = Math.min(1, (to - t) / 250);
    for (let i = 0; i < 3; i++) {
      const a = u * Math.PI * 4 + i * Math.PI * 2 / 3;
      out.push({ kind: "star", x: Math.cos(a) * 14, y: head - 8 + Math.sin(a) * 4.5, size: 3, alpha: fade });
    }
  };
  const puffs = (kindName: "smoke" | "dust", from: number, to: number, count: number, x0: number, y0: number,
    rise: number, spread: number) => {
    for (let i = 0; i < count; i++) {
      const start = from + (to - from) * i / count, life = 700;
      if (t < start || t >= start + life) continue;
      const u = (t - start) / life;
      out.push({ kind: kindName, x: x0 + (rand(i + 40) - .5) * 6 + (rand(i + 50) - .5) * spread * u,
        y: y0 - rise * u, size: 2 + u * 5, alpha: (1 - u) * .8 });
    }
  };
  const during = (from: number, to: number) => t >= from && t < to;
  switch (kind) {
    case "jolt":
      if (during(0, 520)) arcs(2, 12);
      stars(520, TAIL_MS.jolt);
      break;
    case "xray": if (during(0, 700)) arcs(2, 12); puffs("smoke", 700, 1000, 3, 0, head, 16, 6); break;
    case "hop": puffs("dust", 780, 920, 5, 0, 0, 3, 30); break;
    case "spin": stars(950, TAIL_MS.spin); break;
    case "topple": puffs("dust", 260, 360, 4, -height * .5, 0, 2, 30); stars(380, 1750); break;
    case "scorch": puffs("smoke", 0, 1700, 8, 0, head, 28, 12); break;
    case "float": if (during(0, 1150)) arcs(2, 12); puffs("dust", 1550, 1700, 3, 0, 0, 3, 24); break;
    case "boogie":
      for (let i = 0; i < 5; i++) {
        const start = i * 380, life = 900;
        if (t < start || t >= start + life) continue;
        const u = (t - start) / life;
        out.push({ kind: "note", x: (i % 2 ? 11 : -11) + Math.sin(u * 6) * 3, y: head - 4 - u * 24, size: 3,
          alpha: 1 - u });
      }
      break;
    case "overcharge":
      for (let i = 0; i < 3; i++) {
        const start = i * 420, life = 700;
        if (t < start || t >= start + life) continue;
        const u = (t - start) / life;
        out.push({ kind: "ring", x: 0, y: middle, rx: 10 + u * 28, ry: 6 + u * 16, alpha: 1 - u });
      }
      for (let i = 0; i < 6; i++) {
        const a = rand(i + 60) * Math.PI * 2 + t / 350, r = 15 + rand(i + 70) * 9;
        if (Math.floor(t / 110 + i) % 3 === 0) {
          out.push({ kind: "spark", x: Math.cos(a) * r, y: middle + Math.sin(a) * r, dx: 1.5, dy: 1.5,
            color: "#fff3a0", alpha: .9 });
        }
      }
      break;
    case "glitch":
      if (t < 1150) {
        const moment = Math.floor(t / 70);
        for (let i = 0; i < 7; i++) {
          if (noise(moment, i + 30) < .35) continue;
          out.push({ kind: "pixel", x: (noise(moment, i + 40) - .5) * 34, y: middle + (noise(moment, i + 50) - .5) * 44,
            size: 2 + Math.floor(noise(moment, i + 60) * 3),
            color: ["#ff3df2", "#3dfcff", "#7dff6b", "#ffffff"][i % 4], alpha: .9 });
        }
      }
      break;
    case "reboot":
      if (during(0, 600)) puffs("smoke", 0, 300, 2, 0, head, 12, 6);
      if (during(260, 1600)) {
        out.push({ kind: "bar", x: 0, y: head - 16, w: 24, progress: ease((t - 260) / 1340), alpha: 1 });
      }
      if (during(1600, 1800)) arcs(3, 12);
      break;
    case "rocket":
      if (during(160, 820)) {
        // flames under its feet, a little apart, each one burning out as it falls behind
        for (let i = 0; i < 6; i++) {
          const u = ((t - 160 + i * 43) % 260) / 260;
          out.push({ kind: "flame", x: (rand(i + 80) - .5) * 8, y: 4 + u * 14, size: 4 - u * 2.5, alpha: 1 - u });
        }
      }
      puffs("dust", 160, 420, 5, 0, 0, 4, 34);  // the launch cloud stays on the floor
      puffs("dust", 1180, 1300, 5, 0, 0, 3, 36);
      stars(1380, TAIL_MS.rocket);
      break;
  }
  return out;
}

let audio: AudioContext | null = null;

/** A short cartoon sound for a reaction: crackling noise and a buzz; hops and rockets boing, fizzles only fizz. */
export function zapSound(kind: ZapReaction = "jolt") {
  try {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
    if (!Ctor) return;
    audio ||= new Ctor();
    const ctx = audio, now = ctx.currentTime;
    const weak = kind === "fizzle";
    const length = weak ? 0.16 : 0.34;
    const out = ctx.createGain();
    out.gain.setValueAtTime(0.0001, now);
    out.gain.exponentialRampToValueAtTime(weak ? 0.06 : 0.16, now + 0.01);
    out.gain.exponentialRampToValueAtTime(0.0001, now + length);
    out.connect(ctx.destination);
    // the crackle: noise through a band-pass filter
    const noiseBuffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * length), ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (Math.random() < 0.3 ? 1 : 0.2);
    const crackle = ctx.createBufferSource();
    crackle.buffer = noiseBuffer;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = weak ? 3800 : 2400;
    band.Q.value = 0.8;
    crackle.connect(band).connect(out);
    crackle.start(now);
    crackle.stop(now + length);
    if (weak) return;
    // the buzz: a sawtooth falling in pitch; each reaction its own pitch
    const top = { jolt: 880, xray: 1200, hop: 660, spin: 990, topple: 520, scorch: 440, float: 1320, boogie: 740,
      overcharge: 1560, glitch: 1800, reboot: 330, rocket: 600 }[kind];
    const buzz = ctx.createOscillator();
    buzz.type = kind === "glitch" ? "square" : "sawtooth";
    buzz.frequency.setValueAtTime(top, now);
    buzz.frequency.exponentialRampToValueAtTime(110, now + length);
    const quiet = ctx.createGain();
    quiet.gain.value = 0.35;
    buzz.connect(quiet).connect(out);
    buzz.start(now);
    buzz.stop(now + length);
    if (kind === "hop" || kind === "float" || kind === "rocket") {
      // a cartoon boing (a rocket's goes up and keeps going)
      const boing = ctx.createOscillator(), level = ctx.createGain();
      boing.type = "sine";
      boing.frequency.setValueAtTime(220, now + 0.05);
      const rocket = kind === "rocket";
      boing.frequency.exponentialRampToValueAtTime(rocket ? 1400 : 520, now + (rocket ? 0.6 : 0.2));
      if (!rocket) boing.frequency.exponentialRampToValueAtTime(260, now + 0.4);
      level.gain.setValueAtTime(0.0001, now);
      level.gain.exponentialRampToValueAtTime(0.12, now + 0.06);
      level.gain.exponentialRampToValueAtTime(0.0001, now + (rocket ? 0.7 : 0.45));
      boing.connect(level).connect(ctx.destination);
      boing.start(now + 0.04);
      boing.stop(now + (rocket ? 0.72 : 0.46));
    }
  } catch {
    /* no sound: the spark still shows */
  }
}
