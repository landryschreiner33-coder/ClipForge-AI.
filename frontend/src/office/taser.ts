/**
 * The robot office's Taser (the owner, 2026-11-25: "clicking it on a robot plays a brief cartoon spark and a funny
 * reaction"; 2026-11-26: "make it an actual item you can grab with animations ... they should have multipal animations
 * when you taze them the same thing shouldent happen all the time"). Purely for fun: nothing is sent anywhere and the
 * robot's job carries on.
 *
 * The Taser lies on its charger in the Control room; you pick it up, carry it over the ship and click a robot. Each zap
 * plays one of nine reactions (ZAP_KINDS), drawn on the ship by StudioScene from zapPose and zapParticles below. A bag
 * deals them, so every reaction comes up once before any comes back, and never the same one twice in a row. Zapping
 * again while the Taser recharges only fizzles. Under Reduced motion the robot stays still and a still spark shows.
 * The sounds play only when Settings → Appearance → Sound effects is on.
 */
import type { FrameName } from "./crew";

export type ZapKind = "jolt" | "xray" | "hop" | "spin" | "topple" | "scorch" | "float" | "boogie" | "overcharge";
export type ZapReaction = ZapKind | "fizzle";
export const ZAP_KINDS: ZapKind[] = ["jolt", "xray", "hop", "spin", "topple", "scorch", "float", "boogie", "overcharge"];
/** How long each reaction plays on the ship (ms). */
export const ZAP_MS: Record<ZapReaction, number> = {
  jolt: 1500, xray: 1300, hop: 1150, spin: 1500, topple: 2300, scorch: 2300, float: 1900, boogie: 2000,
  overcharge: 1800, fizzle: 900,
};
/** The Taser needs this long to recharge after a zap; zapping sooner only fizzles. */
export const RECHARGE_MS = 650;

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
  fizzle: ["Was that it?", "Battery low, huh?", "That barely tickled.", "Fizz… nope."],
};

/** Deals the reactions from a shuffled bag: all nine before any repeats, and never the same one twice in a row. Each
 * reaction's lines take turns too. */
export class ZapPicker {
  private bag: ZapKind[] = [];
  private last: ZapKind | null = null;
  private lines = new Map<ZapReaction, number>();
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
}

/** How a zapped robot is drawn at `ms` into its reaction: an offset (world units), a turn, a flip, a squash, a tint,
 * the X-ray look and the frame to show instead of its own. */
export interface ZapPose {
  dx: number; dy: number; rot: number; flip: boolean; sx: number; sy: number;
  tint: { color: string; alpha: number } | null;
  xray: boolean;
  frame: FrameName | null;
}
const REST: ZapPose = { dx: 0, dy: 0, rot: 0, flip: false, sx: 1, sy: 1, tint: null, xray: false, frame: null };
const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const ease = (v: number) => 1 - (1 - clamp01(v)) ** 3;

export function zapPose(kind: ZapReaction, ms: number): ZapPose {
  const p: ZapPose = { ...REST };
  if (ms < 0 || ms >= ZAP_MS[kind]) return p;
  const flash = (period: number) => Math.floor(ms / period) % 2 === 0;
  switch (kind) {
    case "jolt":
      if (ms < 650) {
        p.dx = flash(40) ? 2 : -2;
        p.dy = flash(70) ? -1 : 0;
        p.tint = flash(60) ? { color: "#9ff3ff", alpha: .85 } : null;
        p.frame = flash(120) ? "work_3" : "blink";
      } else p.frame = Math.floor(ms / 300) % 2 ? "look_left" : "look_right";
      break;
    case "xray":
      if (ms < 950) {
        p.xray = flash(90);
        p.dx = flash(45) ? 1 : -1;
      } else {
        p.tint = { color: "#1a1424", alpha: .55 * (1 - (ms - 950) / 350) };
        p.frame = "blink";
      }
      break;
    case "hop": {
      if (ms < 90) { p.sx = 1.18; p.sy = .8; break; }
      if (ms < 760) {
        const t = (ms - 90) / 670;
        p.dy = -Math.sin(Math.PI * t) * 30;
        p.sx = .9; p.sy = 1.12;
        p.rot = Math.sin(Math.PI * t) * .18;
        p.frame = "work_3";
        p.tint = ms < 260 && flash(50) ? { color: "#9ff3ff", alpha: .7 } : null;
        break;
      }
      const t = (ms - 760) / 390;
      p.sx = 1 + .2 * (1 - t); p.sy = 1 - .2 * (1 - t);
      p.frame = "blink";
      break;
    }
    case "spin":
      if (ms < 950) {
        p.sx = Math.cos(ease(ms / 950) * 4 * Math.PI * 2);  // four turns, fast at first, then slowing down
        if (Math.abs(p.sx) < .18) p.sx = p.sx < 0 ? -.18 : .18;
        p.dy = -Math.sin(Math.PI * ms / 950) * 8;
        p.tint = ms < 200 && flash(50) ? { color: "#9ff3ff", alpha: .7 } : null;
      } else {
        p.rot = Math.sin((ms - 950) / 90) * .09;
        p.frame = Math.floor(ms / 250) % 2 ? "look_left" : "look_right";
      }
      break;
    case "topple":
      if (ms < 300) {
        p.rot = -Math.PI / 2 * ease(ms / 300);
        p.tint = flash(50) ? { color: "#9ff3ff", alpha: .7 } : null;
      } else if (ms < 1800) {
        p.rot = -Math.PI / 2;
        p.frame = "blink";
        if (ms > 1000 && ms < 1150) p.dx = flash(40) ? 1 : -1;  // a twitch
      } else if (ms < 2100) {
        const t = (ms - 1800) / 300;
        p.rot = -Math.PI / 2 * (1 - ease(t));
        p.dy = -Math.sin(Math.PI * t) * 12;
      } else {
        const t = (ms - 2100) / 200;
        p.sx = 1 + .12 * (1 - t); p.sy = 1 - .12 * (1 - t);
      }
      break;
    case "scorch":
      if (ms < 180) p.tint = { color: "#ffffff", alpha: .95 };
      else {
        const fade = ms > 1800 ? 1 - (ms - 1800) / 500 : 1;
        p.tint = { color: "#15100c", alpha: .78 * fade };
        p.frame = Math.floor(ms / 700) % 3 === 2 ? "blink" : "idle";
        if (ms > 1500 && ms < 1800) p.dx = flash(35) ? 2 : -2;  // shakes the soot off
      }
      break;
    case "float":
      if (ms < 1300) {
        const rise = ease(ms / 900);
        p.dy = -rise * 20 + Math.sin(ms / 160) * 2;
        p.rot = Math.sin(ms / 220) * .1;
        p.tint = flash(110) ? { color: "#9ff3ff", alpha: .45 } : null;
        p.frame = "work_3";
      } else if (ms < 1520) {
        p.dy = -20 + Math.sin(ms / 160) * 2;
        p.frame = "look_left";
      } else if (ms < 1660) {
        p.dy = -20 * (1 - (ms - 1520) / 140);
        p.frame = "blink";
      } else {
        const t = (ms - 1660) / 240;
        p.sx = 1 + .2 * (1 - t); p.sy = 1 - .2 * (1 - t);
      }
      break;
    case "boogie": {
      const beat = Math.floor(ms / 250);
      p.dy = -Math.abs(Math.sin(ms / 250 * Math.PI)) * 7;
      p.flip = beat % 2 === 1;
      p.rot = (beat % 2 ? -1 : 1) * .12;
      p.frame = beat % 4 < 2 ? "work_3" : "work_1";
      p.tint = ms < 200 && flash(50) ? { color: "#9ff3ff", alpha: .7 } : null;
      break;
    }
    case "overcharge": {
      const glow = .35 + .3 * Math.sin(ms / 90);
      p.tint = { color: "#ffd23f", alpha: glow * (ms > 1400 ? 1 - (ms - 1400) / 400 : 1) };
      const grow = Math.sin(Math.PI * clamp01(ms / 1200)) * .1;
      p.sx = 1 + grow; p.sy = 1 + grow;
      p.frame = "work_3";
      break;
    }
    case "fizzle":
      p.frame = ms < 450 ? "look_left" : "look_right";
      p.tint = ms < 120 ? { color: "#9ff3ff", alpha: .35 } : null;
      break;
  }
  return p;
}

/** What flies around a zapped robot, in world units from its feet: sparks, dizzy stars, smoke, dust, music notes,
 * golden rings and crackling arcs. Pure, so the ship can draw it and a test can check it. */
export type ZapParticle =
  | { kind: "spark"; x: number; y: number; dx: number; dy: number; color: string; alpha: number }
  | { kind: "star" | "note" | "smoke" | "dust"; x: number; y: number; size: number; alpha: number }
  | { kind: "ring"; x: number; y: number; rx: number; ry: number; alpha: number }
  | { kind: "arc"; points: number[]; alpha: number };

export function zapParticles(kind: ZapReaction, ms: number, height: number, seed: number): ZapParticle[] {
  const out: ZapParticle[] = [];
  if (ms < 0 || ms >= ZAP_MS[kind]) return out;
  const head = -height * .78;
  const rand = (k: number) => {  // a fixed number per particle, so a particle keeps its path
    const v = Math.sin((seed % 997) * 12.9898 + k * 78.233) * 43758.5453;
    return v - Math.floor(v);
  };
  // the hit: sparks fly out from the middle of the robot
  const burst = kind === "fizzle" ? 140 : 380;
  if (ms < burst) {
    const n = kind === "fizzle" ? 4 : 10, t = ms / burst;
    for (let i = 0; i < n; i++) {
      const a = rand(i) * Math.PI * 2, reach = (kind === "fizzle" ? 8 : 18 + rand(i + 20) * 14) * ease(t);
      out.push({ kind: "spark", x: Math.cos(a) * reach, y: -height * .5 + Math.sin(a) * reach, dx: Math.cos(a) * 5,
        dy: Math.sin(a) * 5, color: i % 3 ? "#9ff3ff" : "#fff3a0", alpha: 1 - t });
    }
  }
  const stars = (from: number, to: number) => {
    if (ms < from || ms >= to) return;
    const t = (ms - from) / 1000, fade = Math.min(1, (to - ms) / 250);
    for (let i = 0; i < 3; i++) {
      const a = t * Math.PI * 4 + i * Math.PI * 2 / 3;
      out.push({ kind: "star", x: Math.cos(a) * 13, y: head - 8 + Math.sin(a) * 4, size: 3, alpha: fade });
    }
  };
  const arcs = (from: number, to: number, count: number) => {
    if (ms < from || ms >= to) return;
    const step = Math.floor(ms / 70);  // the arcs jump about, like real ones
    for (let i = 0; i < count; i++) {
      const a = rand(step * 7 + i) * Math.PI * 2, r1 = 12 + rand(step + i) * 6, r2 = r1 + 6;
      const x0 = Math.cos(a) * r1, y0 = -height * .5 + Math.sin(a) * r1 * 1.3;
      const x2 = Math.cos(a + .5) * r2, y2 = -height * .5 + Math.sin(a + .5) * r2 * 1.3;
      out.push({ kind: "arc", points: [x0, y0, (x0 + x2) / 2 + (rand(step + i + 3) - .5) * 8,
        (y0 + y2) / 2 + (rand(step + i + 5) - .5) * 8, x2, y2], alpha: .9 });
    }
  };
  const puffs = (kindName: "smoke" | "dust", from: number, to: number, count: number, x0: number, y0: number,
    rise: number, spread: number) => {
    for (let i = 0; i < count; i++) {
      const start = from + (to - from) * i / count, life = 700;
      if (ms < start || ms >= start + life) continue;
      const t = (ms - start) / life;
      out.push({ kind: kindName, x: x0 + (rand(i + 40) - .5) * 6 + (rand(i + 50) - .5) * spread * t,
        y: y0 - rise * t, size: 2 + t * 5, alpha: (1 - t) * .8 });
    }
  };
  switch (kind) {
    case "jolt": arcs(0, 650, 3); stars(650, ZAP_MS.jolt); break;
    case "xray": arcs(0, 950, 2); puffs("smoke", 950, 1250, 2, 0, head, 16, 6); break;
    case "hop": puffs("dust", 760, 900, 4, 0, 0, 3, 26); break;
    case "spin": stars(950, ZAP_MS.spin); break;
    case "topple": stars(300, 1800); break;
    case "scorch": puffs("smoke", 200, 1900, 7, 0, head, 26, 10); break;
    case "float": arcs(0, 1300, 2); puffs("dust", 1660, 1800, 3, 0, 0, 3, 22); break;
    case "boogie":
      for (let i = 0; i < 4; i++) {
        const start = i * 450, life = 900;
        if (ms < start || ms >= start + life) continue;
        const t = (ms - start) / life;
        out.push({ kind: "note", x: (i % 2 ? 10 : -10) + Math.sin(t * 6) * 3, y: head - 4 - t * 22, size: 3,
          alpha: 1 - t });
      }
      break;
    case "overcharge":
      for (let i = 0; i < 3; i++) {
        const start = i * 500, life = 700;
        if (ms < start || ms >= start + life) continue;
        const t = (ms - start) / life;
        out.push({ kind: "ring", x: 0, y: -height * .5, rx: 10 + t * 24, ry: 6 + t * 14, alpha: 1 - t });
      }
      for (let i = 0; i < 5; i++) {
        const a = rand(i + 60) * Math.PI * 2 + ms / 400, r = 14 + rand(i + 70) * 8;
        if (Math.floor(ms / 120 + i) % 3 === 0) {
          out.push({ kind: "spark", x: Math.cos(a) * r, y: -height * .5 + Math.sin(a) * r, dx: 1.5, dy: 1.5,
            color: "#fff3a0", alpha: .9 });
        }
      }
      break;
    case "fizzle": puffs("smoke", 60, 200, 1, 0, head, 10, 4); break;
  }
  return out;
}

let audio: AudioContext | null = null;

/** A short cartoon sound for a reaction: crackling noise and a buzz; hops boing, fizzles only fizz. Quiet. */
export function zapSound(kind: ZapReaction = "jolt") {
  try {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
    if (!Ctor) return;
    audio ||= new Ctor();
    const ctx = audio, now = ctx.currentTime;
    const weak = kind === "fizzle";
    const length = weak ? 0.16 : 0.28;
    const out = ctx.createGain();
    out.gain.setValueAtTime(0.0001, now);
    out.gain.exponentialRampToValueAtTime(weak ? 0.06 : 0.16, now + 0.01);
    out.gain.exponentialRampToValueAtTime(0.0001, now + length);
    out.connect(ctx.destination);
    // the crackle: noise through a band-pass filter
    const noise = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * length), ctx.sampleRate);
    const data = noise.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (Math.random() < 0.3 ? 1 : 0.2);
    const crackle = ctx.createBufferSource();
    crackle.buffer = noise;
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
      overcharge: 1560 }[kind];
    const buzz = ctx.createOscillator();
    buzz.type = "sawtooth";
    buzz.frequency.setValueAtTime(top, now);
    buzz.frequency.exponentialRampToValueAtTime(110, now + length);
    const quiet = ctx.createGain();
    quiet.gain.value = 0.35;
    buzz.connect(quiet).connect(out);
    buzz.start(now);
    buzz.stop(now + length);
    if (kind === "hop" || kind === "float") {
      // a cartoon boing: a sine bending up then down
      const boing = ctx.createOscillator(), level = ctx.createGain();
      boing.type = "sine";
      boing.frequency.setValueAtTime(220, now + 0.05);
      boing.frequency.exponentialRampToValueAtTime(520, now + 0.2);
      boing.frequency.exponentialRampToValueAtTime(260, now + 0.4);
      level.gain.setValueAtTime(0.0001, now);
      level.gain.exponentialRampToValueAtTime(0.12, now + 0.06);
      level.gain.exponentialRampToValueAtTime(0.0001, now + 0.45);
      boing.connect(level).connect(ctx.destination);
      boing.start(now + 0.04);
      boing.stop(now + 0.46);
    }
  } catch {
    /* no sound: the spark still shows */
  }
}
