/**
 * Pixel robots, drawn from the parts in cast.ts onto a transparent 48×64 cell (feet at y 61, centered at x 24).
 * Pure functions: a sprite is a list of rectangles, memoized per role, direction, pose and frame, so the office
 * renderer and the gallery draw exactly the same art. Bodies are sized by rank (worker, manager ≈1.15×, Director
 * ≈1.35×) in whole pixels, so nothing is scaled blurry.
 *
 * Left and right are drawn, not mirrored: gear held in the right hand stays in the right hand (behind the body when
 * that hand is the far side).
 */
import { BY_ID, Character, Dir, Palette } from "./cast";

export type Pose = "idle" | "work" | "walk" | "carry" | "review" | "approved" | "rework" | "error" | "retry" | "wait"
  | "paused" | "unavailable";
export type Rect = [number, number, number, number, string, number?];

export const CELL = { w: 48, h: 64 };
const INK = "#0b1020";
const WHITE = "#f3f4f7";
const GOOD = "#57eea0";
const AMBER = "#ffab45";
const BAD = "#ff5d73";
const CROWN = "#ffc94a";

/** Frames per pose and the time each frame shows (ms). Unknown combinations fall back to idle. */
export const FRAMES: Record<Pose, { n: number; ms: number }> = {
  idle: { n: 2, ms: 900 }, work: { n: 4, ms: 0 }, walk: { n: 4, ms: 140 }, carry: { n: 4, ms: 150 },
  review: { n: 2, ms: 700 }, approved: { n: 1, ms: 0 }, rework: { n: 1, ms: 0 }, error: { n: 2, ms: 500 },
  retry: { n: 4, ms: 250 }, wait: { n: 2, ms: 800 }, paused: { n: 1, ms: 0 }, unavailable: { n: 1, ms: 0 },
};
export const frameMs = (c: Character, pose: Pose) => pose === "work" ? c.workMs || 400 : FRAMES[pose].ms;

const SIZE = {
  worker: { hw: 18, hh: 14, bw: 16, bh: 13, lh: 6 },
  manager: { hw: 20, hh: 16, bw: 19, bh: 15, lh: 7 },
  director: { hw: 24, hh: 18, bw: 22, bh: 18, lh: 8 },
};

class Pix {
  r: Rect[] = [];
  px(x: number, y: number, w: number, h: number, c: string, a?: number) {
    if (w > 0 && h > 0) this.r.push(a === undefined ? [x, y, w, h, c] : [x, y, w, h, c, a]);
  }
  /** A filled shape from per-row insets, with a 1px ink outline and a shaded right edge. */
  shape(x: number, y: number, w: number, h: number, inset: (row: number) => number, fill: string, shade: string,
    alpha?: number) {
    for (let row = 0; row < h; row++) {
      const i = Math.max(0, Math.min(Math.floor(w / 2) - 1, inset(row)));
      const x0 = x + i, x1 = x + w - i;
      const edge = row === 0 || row === h - 1 || inset(row - 1) > i + 1 || inset(row + 1) > i + 1;
      if (edge) {
        this.px(x0, y + row, x1 - x0, 1, INK);
        const prev = Math.max(0, inset(row - 1)), next = Math.max(0, inset(row + 1));
        const inner0 = Math.max(x0 + 1, x + Math.min(prev, next) + 1);
        if (row !== 0 && row !== h - 1) this.px(inner0, y + row, Math.max(0, x1 - 1 - inner0 - (inner0 - x0) + 1),
          1, fill, alpha);
        continue;
      }
      this.px(x0, y + row, 1, 1, INK);
      this.px(x1 - 1, y + row, 1, 1, INK);
      this.px(x0 + 1, y + row, x1 - x0 - 2, 1, fill, alpha);
      this.px(x1 - 3, y + row, 2, 1, shade, alpha);
    }
  }
  box(x: number, y: number, w: number, h: number, fill: string, outline = INK) {
    this.px(x, y, w, h, outline);
    this.px(x + 1, y + 1, w - 2, h - 2, fill);
  }
}

// ------------------------------------------------------------------ head silhouettes (row insets)
const ellipse = (w: number, h: number) => (r: number) => {
  const t = (r + 0.5 - h / 2) / (h / 2);
  return Math.round(w / 2 - (w / 2) * Math.sqrt(Math.max(0, 1 - t * t)));
};
function headInset(c: Character, w: number, h: number): (r: number) => number {
  const last = h - 1;
  const round2 = (r: number) => (r === 0 || r === last ? 2 : r === 1 || r === last - 1 ? 1 : 0);
  switch (c.head) {
    case "oval": case "round": case "clock-ring": case "fin-round": return ellipse(w, h);
    case "dome": case "cap": return (r) => (r < h * 0.6 ? ellipse(w, h * 1.2)(r) : r === last ? 1 : 0);
    case "trapezoid": return (r) => Math.floor((r * 4) / h) + (r === 0 || r === last ? 1 : 0);
    case "slim-trapezoid": return (r) => Math.floor(((last - r) * 4) / h) + (r === last ? 1 : 0);
    case "angular": return (r) => Math.round(Math.abs(r - h * 0.35) * 0.55) + 1;
    case "hex": return (r) => Math.max(0, 4 - r, r - (last - 4));
    case "steel-hex": return (r) => Math.max(0, 5 - r, r - (last - 5)) + 1;
    case "keycap": return (r) => (r === 0 ? 3 : r < 3 ? 2 : r === last ? 1 : 0);
    case "swept": return (r) => (r < 3 ? 3 - r + 1 : r === last ? 1 : 0);
    case "jaw": return (r) => (r < h - 6 ? (r === 0 ? 3 : 2) : r === last ? 1 : 0);  // a heavy jaw wider than the brow
    case "box": case "book": case "wide": return (r) => (r === 0 || r === last ? 0 : 0);
    case "square": case "director-helmet": case "cargo": return (r) => (r === 0 || r === last ? 1 : 0);
    case "beacon": return (r) => (r === 0 || r === last ? 2 : r === 1 ? 1 : 0);
    default: return round2; // rounded-square, radar-arch, soft-rect, monitor
  }
}
function headSize(c: Character): { w: number; h: number } {
  const s = SIZE[c.rank];
  const adj: Partial<Record<Character["head"], [number, number]>> = {
    oval: [-4, 2], angular: [-4, 2], "slim-trapezoid": [-4, 1], wide: [6, -3], keycap: [-2, 3], round: [0, 2],
    "fin-round": [0, 2], beacon: [4, -3], "steel-hex": [0, 1], cargo: [4, -1], book: [0, 1], cap: [0, 1],
    box: [2, -2], jaw: [0, 1], swept: [0, 0],
  };
  const [dw, dh] = adj[c.head] || [0, 0];
  return { w: s.hw + dw, h: s.hh + dh };
}

// ------------------------------------------------------------------ the parts
function drawTop(p: Pix, c: Character, hx: number, hy: number, hw: number, dir: Dir, f: number, lit: boolean) {
  const P = c.palette, cx = hx + Math.floor(hw / 2);
  const side = dir === "left" ? -1 : dir === "right" ? 1 : 0;
  switch (c.top) {
    case "crest":  // gold three-fin crest
      for (const [dx, h] of [[-5, 4], [-1, 6], [3, 4]] as const) {
        p.px(cx + dx + side * 2 - 1, hy - h, 4, h + 1, INK);
        p.px(cx + dx + side * 2, hy - h + 1, 2, h, P.trim);
      }
      break;
    case "radar-arch":  // a tall arch over the head with a small dish
      p.px(hx + 2, hy - 7, 2, 8, INK); p.px(hx + hw - 4, hy - 7, 2, 8, INK);
      p.px(hx + 2, hy - 8, hw - 4, 2, INK); p.px(hx + 3, hy - 7, hw - 6, 1, P.trim);
      p.px(cx - 2 + side, hy - 11, 5, 3, INK); p.px(cx - 1 + side, hy - 10, 3, 1, P.eye);
      break;
    case "bar-antennae":
      p.px(cx - 6 + side, hy - 4, 3, 5, INK); p.px(cx - 5 + side, hy - 3, 1, 3, P.trim);
      p.px(cx + 3 + side, hy - 4, 3, 5, INK); p.px(cx + 4 + side, hy - 3, 1, 3, P.trim);
      break;
    case "brim":  // director-style helmet brim
      p.px(hx - 2, hy + 1, hw + 4, 3, INK); p.px(hx - 1, hy + 2, hw + 2, 1, P.trim);
      if (side) p.px(side > 0 ? hx + hw : hx - 4, hy + 1, 4, 3, INK);
      break;
    case "side-dial":
      if (side >= 0) { p.box(hx + hw - 2, hy + 4, 5, 5, P.trim); p.px(hx + hw, hy + 6, 1, 1, INK); }
      if (side <= 0 && dir !== "up") { /* the dial is on the right side of the head */ }
      if (dir === "up") { p.box(hx + 2, hy + 4, 5, 5, P.trim); }
      break;
    case "mast":  // single uplink mast with a blinking tip
      p.px(cx + side * 3, hy - 9, 2, 10, INK); p.px(cx + side * 3, hy - 8, 1, 8, P.shade);
      p.px(cx - 1 + side * 3, hy - 11, 4, 3, INK);
      p.px(cx + side * 3, hy - 10, 2, 1, lit && f % 2 ? WHITE : P.trim);
      break;
    case "crown3":
      for (const dx of [-5, 0, 5]) {
        p.px(cx + dx + side, hy - 4, 1, 4, INK);
        p.box(cx + dx - 1 + side, hy - 7, 3, 3, lit && (f + dx) % 3 === 0 ? WHITE : P.trim);
      }
      p.px(cx - 5 + side, hy - 6, 10, 1, P.trimDark);
      break;
    case "long-antenna":
      p.px(cx + 3 + side * 2, hy - 12, 1, 12, INK);
      p.box(cx + 2 + side * 2, hy - 15, 3, 3, lit ? P.eye : P.trim);
      break;
    case "zigzag": {
      const pts = [[0, 0], [2, -2], [0, -4], [2, -6], [0, -8]];
      for (const [dx, dy] of pts) p.px(cx + dx + side * 2, hy - 2 + dy, 2, 2, INK);
      p.px(cx + side * 2, hy - 11, 3, 2, lit ? P.eye : P.trim);
      break;
    }
    case "star":
      p.px(cx + side * 2, hy - 6, 1, 6, INK);
      p.px(cx - 1 + side * 2, hy - 10, 3, 3, INK); p.px(cx - 2 + side * 2, hy - 9, 5, 1, INK);
      p.px(cx + side * 2, hy - 11, 1, 5, INK);
      p.px(cx + side * 2, hy - 9, 1, 1, lit && f % 2 ? WHITE : P.trim);
      p.px(cx - 1 + side * 2, hy - 9, 1, 1, P.trim); p.px(cx + 1 + side * 2, hy - 9, 1, 1, P.trim);
      break;
    case "spine":  // book-spine ridge along one side of the head
      if (dir !== "right") { p.px(hx - 2, hy + 2, 3, 10, INK); p.px(hx - 1, hy + 3, 1, 8, P.trim); }
      if (dir === "right" || dir === "up") { p.px(hx + hw - 1, hy + 2, 3, 10, INK); p.px(hx + hw, hy + 3, 1, 8, P.trim); }
      break;
    case "fins":  // short side fins swept back
      if (dir !== "right") { p.px(hx - 3, hy + 4, 4, 3, INK); p.px(hx - 4, hy + 3, 3, 2, INK); p.px(hx - 2, hy + 5, 2, 1, P.trim); }
      if (dir !== "left") { p.px(hx + hw - 1, hy + 4, 4, 3, INK); p.px(hx + hw + 1, hy + 3, 3, 2, INK); p.px(hx + hw, hy + 5, 2, 1, P.trim); }
      break;
    case "ear-cups":  // oversized orange ear cups and band
      p.px(hx + 1, hy - 2, hw - 2, 2, INK); p.px(hx + 2, hy - 1, hw - 4, 1, P.gearDark);
      if (dir !== "right") { p.box(hx - 4, hy + 3, 6, 8, P.gear); p.px(hx - 3, hy + 4, 1, 6, WHITE, 0.4); }
      if (dir !== "left") { p.box(hx + hw - 2, hy + 3, 6, 8, P.gear); }
      break;
    case "key-tabs":
      if (dir !== "right") { p.box(hx - 3, hy + 5, 4, 4, P.trim); p.px(hx - 2, hy + 6, 1, 1, INK); }
      if (dir !== "left") { p.box(hx + hw - 1, hy + 5, 4, 4, P.trim); p.px(hx + hw, hy + 6, 1, 1, INK); }
      break;
    case "pencil":  // pencil-shaped antenna
      p.px(cx + 2 + side * 2, hy - 9, 3, 9, INK); p.px(cx + 3 + side * 2, hy - 8, 1, 6, P.trim);
      p.px(cx + 3 + side * 2, hy - 10, 1, 1, INK); p.px(cx + 3 + side * 2, hy - 2, 1, 1, P.gear);
      break;
    case "uplink":  // small dish
      p.px(cx + side * 2, hy - 5, 1, 5, INK);
      p.px(cx - 4 + side * 2, hy - 8, 9, 2, INK); p.px(cx - 3 + side * 2, hy - 9, 7, 1, INK);
      p.px(cx - 3 + side * 2, hy - 8, 7, 1, P.shell);
      p.px(cx + side * 2, hy - 11, 1, 2, lit && f % 2 ? GOOD : P.trim);
      break;
    case "bar-fins":  // three unequal bar fins
      for (const [dx, h] of [[-5, 3], [-1, 6], [3, 4]] as const) {
        p.px(cx + dx + side, hy - h, 3, h + 1, INK); p.px(cx + dx + 1 + side, hy - h + 1, 1, h, P.trim);
      }
      break;
    case "forked":
      p.px(cx + side, hy - 5, 1, 5, INK);
      p.px(cx - 3 + side, hy - 6, 7, 1, INK); p.px(cx - 3 + side, hy - 9, 1, 3, INK); p.px(cx + 3 + side, hy - 9, 1, 3, INK);
      p.box(cx - 4 + side, hy - 11, 3, 3, lit && f % 2 ? WHITE : P.trim);
      p.box(cx + 2 + side, hy - 11, 3, 3, lit && f % 2 === 0 ? WHITE : P.trim);
      break;
    case "beacon": {  // rotating beacon cap: lit only for a real incident (the error pose)
      p.px(cx - 4, hy - 4, 9, 5, INK);
      p.px(cx - 3, hy - 3, 7, 3, lit ? AMBER : P.trimDark);  // an orange lamp, dark until something is wrong
      if (lit) p.px(cx - 3 + ((f * 2) % 7), hy - 3, 2, 3, "#fff1b8");
      break;
    }
    default:
      break;
  }
}

function drawVisor(p: Pix, c: Character, hx: number, hy: number, hw: number, hh: number, dir: Dir, f: number,
  eyesOn: boolean, pose: Pose) {
  const P = c.palette;
  const eye = !eyesOn ? "#3b4560" : P.eye;
  const blink = pose === "idle" && f === 1 && c.visor !== "cyclops";
  if (dir === "up") {  // the back of the head: a vent plate, no face
    p.px(hx + 4, hy + Math.floor(hh / 2) - 1, hw - 8, 3, P.shade);
    p.px(hx + 5, hy + Math.floor(hh / 2), hw - 10, 1, INK, 0.35);
    return;
  }
  const side = dir === "left" ? -1 : dir === "right" ? 1 : 0;
  const vy = hy + Math.round(hh * 0.35);
  if (side) {  // profile: a smaller face plate on the facing side and one eye
    const fw = Math.max(5, Math.floor(hw * 0.45));
    const fx = side > 0 ? hx + hw - fw - 1 : hx + 1;
    p.px(fx, vy, fw, 5, P.visor);
    const ex = side > 0 ? fx + fw - 3 : fx + 1;
    p.px(ex, vy + 2, 2, blink ? 1 : 2, eye);
    if (c.visor === "cyclops") p.box(ex - 1, vy, 4, 5, P.trim);
    if (c.visor === "goggles" || c.visor === "binocular" || c.visor === "lenses" || c.visor === "round-lenses")
      p.px(side > 0 ? fx + fw - 1 : fx - 1, vy + 1, 2, 3, P.gearDark);
    return;
  }
  const cx = hx + Math.floor(hw / 2);
  const two = (gap: number, ew: number, eh: number, y = vy + 1) => {
    p.px(cx - gap - ew, y, ew, blink ? 1 : eh, eye);
    p.px(cx + gap, y, ew, blink ? 1 : eh, eye);
  };
  switch (c.visor) {
    case "wide-cyan": p.box(hx + 3, vy - 1, hw - 6, 7, P.visor); two(3, 4, 2, vy + 2); break;
    case "binocular":
      p.box(cx - 8, vy - 1, 7, 7, P.gearDark); p.box(cx + 1, vy - 1, 7, 7, P.gearDark);
      p.px(cx - 6, vy + 1, 3, 3, P.visor); p.px(cx + 3, vy + 1, 3, 3, P.visor);
      p.px(cx - 5, vy + 2, 1, 1, eye); p.px(cx + 4, vy + 2, 1, 1, eye); break;
    case "split":
      p.box(hx + 3, vy - 1, hw - 6, 6, P.visor); p.px(cx, vy, 1, 4, P.trim); two(3, 3, 2, vy + 1); break;
    case "horizontal": p.box(hx + 2, vy, hw - 4, 4, P.visor); p.px(hx + 4, vy + 1, hw - 8, 1, eye); break;
    case "bracket":
      p.box(hx + 3, vy - 1, hw - 6, 7, P.visor);
      for (const s of [-1, 1]) {
        const bx = s < 0 ? cx - 7 : cx + 6;
        p.px(bx, vy, 1, 5, P.trim); p.px(s < 0 ? bx : bx - 1, vy, 2, 1, P.trim); p.px(s < 0 ? bx : bx - 1, vy + 4, 2, 1, P.trim);
      }
      two(2, 3, 2, vy + 2); break;
    case "dial":
      p.box(cx - 6, vy - 1, 12, 7, P.visor); two(2, 2, 2, vy + 1);
      p.px(cx - 1, vy + 4, 2, 1, P.trim); break;
    case "slit": p.box(hx + 3, vy + 1, hw - 6, 3, P.visor); p.px(hx + 5, vy + 2, hw - 10, 1, eye); break;
    case "lenses":
      for (const s of [-1, 1]) {
        const lx = s < 0 ? cx - 8 : cx + 2;
        p.box(lx, vy - 1, 6, 6, P.trim); p.px(lx + 1, vy, 4, 4, P.visor); p.px(lx + 2, vy + 1, 2, 2, eye);
      }
      break;
    case "linked-dots":
      p.box(hx + 3, vy - 1, hw - 6, 6, P.visor);
      p.px(cx - 5, vy + 2, 10, 1, P.trimDark);
      for (const dx of [-6, -1, 4]) p.px(cx + dx, vy + 1, 2, blink ? 1 : 3, eye);
      break;
    case "round-lenses":
      p.box(hx + 2, vy - 1, hw - 4, 7, P.visor);
      for (const s of [-1, 1]) {
        const lx = s < 0 ? cx - 7 : cx + 2;
        p.px(lx, vy, 5, 5, P.gear); p.px(lx + 1, vy + 1, 3, 3, P.visor); p.px(lx + 2, vy + 2, 1, 1, eye);
      }
      p.px(cx - 2, vy + 2, 4, 1, P.gear); break;
    case "equalizer": {
      p.box(hx + 2, vy - 1, hw - 4, 7, P.visor);
      const bars = [2, 4, 3, 5, 2, 3];
      bars.forEach((h, k) => {
        const hh2 = pose === "work" ? ((h + f + k) % 5) + 1 : h;
        p.px(hx + 4 + k * 2, vy + 5 - hh2, 1, hh2, eye);
      });
      break;
    }
    case "level":
      p.box(hx + 2, vy + 1, hw - 4, 4, P.visor); p.px(hx + 4, vy + 2, hw - 8, 1, P.trimDark);
      p.px(cx - 1 + (pose === "work" ? (f % 3) - 1 : 0), vy + 2, 2, 1, eye); break;
    case "cyclops":
      p.box(cx - 4, vy - 2, 9, 9, P.trim); p.px(cx - 3, vy - 1, 7, 7, P.visor);
      p.px(cx - 1, vy + 1, 3, 3, eye); p.px(cx - 1, vy + 1, 1, 1, WHITE); break;
    case "panels":
      p.box(cx - 7, vy - 1, 6, 6, P.visor); p.box(cx + 1, vy - 1, 6, 6, P.visor);
      p.px(cx - 5, vy + 1, 2, blink ? 1 : 2, eye); p.px(cx + 3, vy + 1, 2, blink ? 1 : 2, eye); break;
    case "angled":
      p.box(hx + 3, vy - 1, hw - 6, 6, P.visor);
      p.px(cx - 6, vy + 2, 2, 1, eye); p.px(cx - 4, vy + 1, 2, 1, eye);
      p.px(cx + 2, vy + 1, 2, 1, eye); p.px(cx + 4, vy + 2, 2, 1, eye); break;
    case "visor-band":
      p.px(hx, vy, hw, 5, INK); p.px(hx + 1, vy + 1, hw - 2, 3, P.visor); two(3, 2, 1, vy + 2); break;
    case "monitor-face": {
      p.box(hx + 2, hy + 2, hw - 4, hh - 5, P.visor);
      const blinkCursor = pose === "work" ? f % 2 : 1;
      p.px(cx - 4, vy + 1, 2, 2, eye); p.px(cx + 2, vy + 1, 2, 2, eye);
      if (blinkCursor) p.px(cx - 1, vy + 5, 3, 1, P.trim);
      break;
    }
    case "narrow": p.box(hx + 3, vy, hw - 6, 5, P.visor); two(2, 3, 1, vy + 2); break;
    case "inspection":
      p.box(cx - 6, vy - 1, 12, 8, P.visor); p.px(cx - 4, vy + 3, 8, 1, P.trimDark); p.px(cx, vy, 1, 6, P.trimDark);
      p.px(cx - 3, vy + 1, 2, 2, eye); p.px(cx + 2, vy + 1, 2, 2, eye); break;
    case "lock":  // lock-shaped face surround: an arch over a face plate
      p.px(cx - 4, vy - 4, 9, 2, INK); p.px(cx - 5, vy - 3, 2, 4, INK); p.px(cx + 4, vy - 3, 2, 4, INK);
      p.px(cx - 3, vy - 3, 7, 1, P.trim);
      p.box(cx - 6, vy, 13, 7, P.visor); two(2, 2, 2, vy + 2); p.px(cx, vy + 4, 1, 2, P.trim); break;
    case "square-eyes": p.box(hx + 3, vy - 1, hw - 6, 7, P.visor); two(2, 3, 3, vy + 1); break;
    case "display":
      p.shape(cx - 6, vy - 2, 12, 9, ellipse(12, 9), P.visor, P.visor);
      p.px(cx - 3, vy + 1, 2, 2, eye); p.px(cx + 1, vy + 1, 2, 2, eye);
      p.px(cx - 3, vy + 4, 1, 1, P.trim); p.px(cx - 1, vy + 3, 1, 2, P.trim); p.px(cx + 1, vy + 4, 1, 1, P.trim); break;
    case "soft":
      p.box(hx + 3, vy, hw - 6, 6, P.visor);
      p.px(cx - 4, vy + 2, 3, blink ? 1 : 2, eye); p.px(cx + 1, vy + 2, 3, blink ? 1 : 2, eye); break;
    case "goggles":
      p.px(hx, vy + 1, hw, 2, P.gearDark);
      p.box(cx - 7, vy - 1, 6, 6, P.gearDark); p.box(cx + 1, vy - 1, 6, 6, P.gearDark);
      p.px(cx - 6, vy, 4, 4, P.visor); p.px(cx + 2, vy, 4, 4, P.visor);
      p.px(cx - 5, vy + 1, 2, blink ? 1 : 2, eye); p.px(cx + 3, vy + 1, 2, blink ? 1 : 2, eye); break;
  }
}

function headDecor(p: Pix, c: Character, hx: number, hy: number, hw: number, hh: number, dir: Dir) {
  const P = c.palette;
  if (c.head === "clock-ring" && dir !== "up") {  // tick marks around the round head
    const cx = hx + Math.floor(hw / 2), cy = hy + Math.floor(hh / 2);
    for (const [dx, dy] of [[0, -hh / 2 + 1], [hw / 2 - 2, 0], [0, hh / 2 - 2], [-hw / 2 + 1, 0]])
      p.px(cx + Math.round(dx), cy + Math.round(dy), 1, 1, P.trimDark);
  }
  if (c.head === "book") {  // the spine and page edges
    if (dir !== "right") { p.px(hx, hy + 1, 3, hh - 2, P.trim); p.px(hx + 1, hy + 3, 1, 1, INK); }
    if (dir === "down" || dir === "left") for (let y = hy + 2; y < hy + hh - 2; y += 2) p.px(hx + hw - 2, y, 1, 1, P.shade);
  }
  if (c.head === "jaw" && dir !== "up") p.px(hx + 2, hy + hh - 4, hw - 4, 2, P.gearDark);
  if (c.head === "cargo") { p.px(hx - 2, hy + 3, hw + 4, 2, INK); p.px(hx - 1, hy + 3, hw + 2, 1, P.trim); }
  if (c.head === "keycap" && dir !== "up") p.px(hx + 3, hy + 2, hw - 6, 1, P.shade);
  if (c.head === "cap") p.px(hx + 3, hy + 1, hw - 6, 4, "#ffffff", 0.35);  // translucent rounded cap
  if (c.head === "monitor") p.px(hx + Math.floor(hw / 2) - 2, hy + hh - 1, 4, 2, INK);
  if (c.head === "wide" && dir !== "up") p.px(hx + 1, hy + 1, hw - 2, 1, P.trim);
  if (c.head === "steel-hex" || c.head === "hex") p.px(hx + 4, hy + 1, hw - 8, 1, P.trim);
  if (c.head === "radar-arch" || c.head === "rounded-square") p.px(hx + 3, hy + 1, hw - 6, 1, P.trim);
  if (c.head === "swept") p.px(hx + 2, hy + 2, hw - 4, 1, P.trim);
}

// ------------------------------------------------------------------ body, limbs and gear
function bodyShape(c: Character, bw: number, bh: number): { w: number; h: number; inset: (r: number) => number } {
  const last = bh - 1;
  switch (c.body) {
    case "jacket": return { w: bw + 4, h: bh, inset: (r) => (r === 0 ? 3 : r === 1 ? 1 : r === last ? 1 : 0) };
    case "shield": return { w: bw + 2, h: bh, inset: (r) => (r < bh - 5 ? 0 : (r - (bh - 5)) + 1) + (r === 0 ? 1 : 0) };
    case "round": return { w: bw, h: bh, inset: ellipse(bw, bh) };
    case "pear": return { w: bw + 2, h: bh + 1, inset: (r) => Math.max(0, Math.round((bh * 0.55 - r) / 2)) + (r === bh ? 1 : 0) };
    case "stocky": return { w: bw + 5, h: bh - 1, inset: (r) => (r === 0 || r === last - 1 ? 1 : 0) };
    case "cart": return { w: bw + 4, h: bh + 2, inset: () => 0 };
    case "slim": return { w: bw - 2, h: bh, inset: (r) => (r === 0 || r === last ? 1 : 0) };
    default: return { w: bw, h: bh, inset: (r) => (r === 0 || r === last ? 1 : 0) };
  }
}

function drawLegs(p: Pix, c: Character, cx: number, top: number, lh: number, dir: Dir, pose: Pose, f: number) {
  const P = c.palette;
  if (c.base === "wheels") {  // DOCK rolls on a compact wheel base
    p.px(cx - 9, top, 18, 3, INK); p.px(cx - 8, top, 16, 2, P.gearDark);
    const spin = (pose === "walk" || pose === "carry") && f % 2 ? 1 : 0;
    for (const dx of dir === "left" || dir === "right" ? [-6, 3] : [-8, 5]) {
      p.box(cx + dx, top + 2, 4, 4, "#3b4252"); p.px(cx + dx + 1 + spin, top + 3, 1, 1, P.shell);
    }
    return;
  }
  const moving = pose === "walk" || pose === "carry";
  const step = moving ? [0, 1, 0, -1][f % 4] : 0;
  if (dir === "left" || dir === "right") {
    const s = dir === "right" ? 1 : -1;
    const a = cx - 2 + step * 2 * s, b = cx - 2 - step * 2 * s;
    p.box(b, top, 4, lh, P.shade); p.box(a, top, 4, lh, P.shell);
    p.px(a + (s > 0 ? 1 : -1), top + lh - 2, 5, 2, INK); p.px(b + (s > 0 ? 1 : -1), top + lh - 2, 5, 2, INK);
    return;
  }
  const lift = (k: number) => (moving && ((k === 0 && step > 0) || (k === 1 && step < 0)) ? 1 : 0);
  for (const [k, dx] of [[0, -5], [1, 1]] as const) {
    p.box(cx + dx, top - lift(k), 4, lh, P.shell);
    p.px(cx + dx - 1, top + lh - 2 - lift(k), 6, 2, INK);
    p.px(cx + dx, top + lh - 2 - lift(k), 4, 1, P.trimDark);
  }
}

function drawArms(p: Pix, c: Character, bx: number, by: number, bw: number, dir: Dir, pose: Pose, f: number) {
  const P = c.palette;
  const swing = pose === "walk" ? [0, 1, 0, -1][f % 4] : 0;
  if (dir === "left" || dir === "right") {
    const s = dir === "right" ? 1 : -1;
    const ax = bx + Math.floor(bw / 2) - 1 + swing * s;
    p.box(ax, by + 2, 3, 8, P.shade);
    return;
  }
  const raised = pose === "review" || pose === "approved" || pose === "carry";
  p.box(bx - 3, by + 1 + (raised ? -1 : swing), 4, raised ? 6 : 9, P.shade);
  p.box(bx + bw - 1, by + 1 + (raised ? -1 : -swing), 4, raised ? 6 : 9, P.shade);
  p.px(bx - 3, by + (raised ? 5 : 9 + swing), 4, 2, P.trimDark);
  p.px(bx + bw - 1, by + (raised ? 5 : 9 - swing), 4, 2, P.trimDark);
}

/** Gear held in front (front view), at the hand (side view) or on the back (back view). */
function drawGear(p: Pix, c: Character, bx: number, by: number, bw: number, bh: number, dir: Dir, pose: Pose,
  f: number, front: boolean) {
  const P = c.palette, cx = bx + Math.floor(bw / 2);
  const working = pose === "work";
  const backpack = ["radar-pack", "reel-pack", "wrench"].includes(c.gear) || c.id === "clock";
  // back items are drawn behind the body in the front view and on top in the back view
  if (backpack && !front) {
    if (dir === "down") {
      if (c.gear === "radar-pack") { p.box(bx - 5, by - 3, 6, 6, P.gear); p.box(bx + bw - 1, by - 3, 6, 6, P.gear); }
      if (c.gear === "reel-pack") { p.box(bx - 4, by - 2, 5, 5, P.gearDark); p.box(bx + bw - 1, by - 2, 5, 5, P.gearDark); }
      if (c.id === "clock") p.box(bx + bw - 2, by + 1, 5, 9, P.gear);
      if (c.gear === "wrench") p.box(bx + bw - 1, by, 4, 8, "#3d424e");
    } else if (dir === "left" || dir === "right") {
      const s = dir === "right" ? -1 : 1;  // the pack is behind: opposite to the facing side
      const px = s > 0 ? bx + bw - 2 : bx - 6;
      if (c.gear === "radar-pack") {
        p.shape(px - 1, by - 4, 9, 9, ellipse(9, 9), P.gear, P.gearDark);
        const a = working ? f % 4 : 0;
        p.px(px + 3, by, [3, 1, 3, 1][a], 1, INK); p.px(px + 3, by - 2 + a, 1, 1, P.eye);
      }
      if (c.gear === "reel-pack") { p.shape(px, by - 2, 8, 8, ellipse(8, 8), P.gearDark, INK); p.px(px + 3, by + 1, 2, 2, P.gear); }
      if (c.id === "clock") p.box(px + 1, by + 1, 6, 10, P.gear);
      if (c.gear === "wrench") p.box(px + 1, by, 6, 9, "#3d424e");
    }
    return;
  }
  if (backpack && front && dir === "up") {
    if (c.gear === "radar-pack") {
      p.shape(cx - 6, by - 3, 13, 13, ellipse(13, 13), P.gear, P.gearDark);
      p.px(cx - 1, by + 2, 3, 3, INK);
      const a = working ? f % 4 : 0;
      p.px(cx + [0, 2, 0, -2][a], by + [-1, 3, 7, 3][a], 1, 1, P.eye);  // the sweep turns only while searching
    }
    if (c.gear === "reel-pack") {
      p.shape(cx - 6, by - 2, 12, 12, ellipse(12, 12), P.gearDark, INK);
      for (const [dx, dy] of [[-2, 1], [2, 1], [0, 5]]) p.px(cx + dx - 1, by + dy + 1, 2, 2, P.gear);
    }
    if (c.id === "clock") { p.box(cx - 5, by + 1, 11, 10, P.gear); p.px(cx - 4, by + 3, 9, 1, INK); p.px(cx - 4, by + 6, 9, 1, P.trimDark); }
    if (c.gear === "wrench") { p.box(cx - 5, by + 1, 11, 9, "#3d424e"); p.px(cx - 3, by + 3, 2, 2, AMBER); p.px(cx + 1, by + 3, 3, 1, GOOD); }
    return;
  }
  if (!front || dir === "up") return;
  const side = dir === "left" ? -1 : dir === "right" ? 1 : 0;
  // which hand holds it in a profile: the far hand's gear is hidden behind the body
  if (side && c.hand !== "both") {
    const near = (c.hand === "right" && side > 0) || (c.hand === "left" && side < 0);
    if (!near) return;
  }
  const gx = side ? (side > 0 ? bx + bw - 3 : bx - 6) : cx - 6;
  const gy = by + 4;
  const tablet = (w: number, h: number, fill: string, lines: string) => {
    const x = side ? gx : cx - Math.floor(w / 2);
    p.box(x, gy, w, h, fill);
    for (let y = gy + 2; y < gy + h - 1; y += 2) p.px(x + 2, y, w - 4, 1, lines);
    return x;
  };
  switch (c.gear) {
    case "command-tablet": {  // a wide orange command tablet
      const x = side ? gx - 2 : cx - 9;
      p.box(x, gy, side ? 9 : 18, 7, P.gear);
      p.px(x + 2, gy + 2, side ? 5 : 14, 1, P.gearDark);
      p.px(x + 2, gy + 4, side ? 3 : (working || pose === "review" ? 6 + f * 2 : 9), 1, WHITE);
      break;
    }
    case "map-tablet": {
      const x = tablet(side ? 7 : 12, 8, P.gear, P.gearDark);
      p.px(x + 2, gy + 5, 2, 1, P.trimDark); p.px(x + 4, gy + 4, 2, 1, P.trimDark);
      if (working) p.px(x + 2 + (f % 3) * 2, gy + 3, 1, 1, BAD);
      break;
    }
    case "graph-badge": {
      p.box(cx - 3 + side * 3, by + 2, 6, 5, P.gear); p.px(cx - 2 + side * 3, by + 4, 1, 2, WHITE);
      p.px(cx + side * 3, by + 3, 1, 3, WHITE);
      const x = tablet(side ? 6 : 10, 6, "#22304f", P.trim);
      if (working) p.px(x + 2 + (f % 2) * 3, gy + 1, 2, 1, WHITE);
      break;
    }
    case "clapper": {
      const x = side ? gx : cx - 6;
      p.box(x, gy, side ? 7 : 12, 8, "#2b2f3d");
      for (let k = 0; k < (side ? 3 : 5); k++) p.px(x + 1 + k * 2, gy + 1, 1, 2, WHITE);
      p.px(x + 1, gy + 4, side ? 5 : 10, 1, P.trim);
      if (working) p.px(x + 2 + (f % 4) * 2, gy + 6, 1, 1, P.trim);
      break;
    }
    case "proof-tablet": {
      const x = tablet(side ? 7 : 11, 9, P.gear, P.shade);
      if (working || pose === "rework") p.px(x + 6, gy + 3 + (f % 2) * 2, 2, 1, BAD);
      break;
    }
    case "ticket-tablet": {
      const x = side ? gx : cx - 6;
      p.box(x, gy, side ? 7 : 12, 6, P.gear);
      for (let k = 1; k < (side ? 6 : 11); k += 2) p.px(x + k, gy + 3, 1, 1, P.gearDark);
      if (working) p.px(x + 1 + (f % 4) * 2, gy + 1, 2, 1, WHITE);
      break;
    }
    case "checklist": {
      const x = tablet(side ? 7 : 11, 9, P.gear, P.shade);
      p.px(x + 2, gy + 2, 1, 1, P.trimDark); p.px(x + 2, gy + 4, 1, 1, P.trimDark);
      if (working) p.px(x + 2, gy + 6, 1, 1, f % 2 ? P.trimDark : P.shade);
      break;
    }
    case "tool-belt":
      p.px(bx, by + bh - 4, bw, 2, "#3a3f4b");
      for (const dx of [2, 6, bw - 5]) p.px(bx + dx, by + bh - 3, 2, 3, AMBER);
      tablet(side ? 6 : 9, 6, "#2b2f3d", P.trim);
      break;
    case "cartridge": {
      const x = tablet(side ? 7 : 11, 8, P.gearDark, P.trim);
      p.px(x + 2, gy + 1, side ? 3 : 7, 2, WHITE, working && f % 2 ? 0.9 : 0.5);
      break;
    }
    case "radar-pack":  // the map card in its hand
      p.box(side ? gx : bx + bw - 1, gy + 1, 5, 6, "#d9c58f");
      p.px((side ? gx : bx + bw - 1) + 1, gy + 3, 3, 1, P.trimDark);
      break;
    case "satchel": {
      p.px(bx + 1, by + 1, 1, bh - 4, "#6b4f2f"); p.box(bx + bw - 6, by + bh - 6, 7, 6, P.gear);
      const mx = side ? gx : bx - 5;
      p.box(mx, gy - 1, 5, 5, "#9fb6c9"); p.px(mx + 4, gy + 3, 2, 2, INK);  // magnifier
      if (working) p.px(mx + 1, gy, 1, 1, WHITE);
      break;
    }
    case "graph-slate": {
      const x = tablet(side ? 7 : 11, 8, P.gear, P.gear);
      const pts = [5, 4, 5, 3, 2, 3, 1];
      for (let k = 0; k < (side ? 5 : 9); k++) p.px(x + 1 + k, gy + pts[(k + (working ? f : 0)) % pts.length], 1, 1, P.trim);
      break;
    }
    case "stamp": {
      const sx = side ? gx : bx + bw;
      const up = working && f % 2 ? 2 : 0;  // the stamp comes down on a decision, up between
      p.box(sx, gy - 2 - up, 4, 4, P.gear); p.px(sx - 1, gy + 2 - up, 6, 2, P.gearDark);
      if (!side) { p.box(bx - 4, gy + 1, 6, 7, WHITE); p.px(bx - 3, gy + 3, 4, 1, P.shade); }
      break;
    }
    case "waveform": {
      const x = side ? gx : cx - 6;
      p.box(x, gy, side ? 7 : 12, 6, "#22304f");
      const wave = [2, 1, 3, 0, 2, 1, 3, 2, 1, 2];
      for (let k = 0; k < (side ? 5 : 10); k++) p.px(x + 1 + k, gy + 1 + wave[k], 1, 2, P.trim);
      if (working) p.px(x + 1 + (f * 3) % (side ? 5 : 10), gy, 1, 6, BAD);
      break;
    }
    case "storyboard":
      for (let k = 0; k < (side ? 1 : 3); k++) {
        const lift = working && k === f % 3 ? 1 : 0;
        p.box((side ? gx : cx - 8) + k * 5, gy - lift, 5, 6, P.gear);
        p.px((side ? gx : cx - 8) + k * 5 + 1, gy + 2 - lift, 3, 1, [P.trim, "#ffab45", GOOD][k]);
      }
      break;
    case "curve-tablet": {
      const x = tablet(side ? 7 : 11, 8, P.gear, P.gear);
      for (let k = 0; k < (side ? 5 : 9); k++) p.px(x + 1 + k, gy + 6 - Math.floor((k * k) / 14), 1, 1, P.trim);
      if (working) p.px(x + 1 + (f * 2) % (side ? 5 : 9), gy + 1, 1, 1, WHITE);
      break;
    }
    case "reel-pack": {  // the editing control pad in front
      const x = side ? gx : cx - 6;
      p.box(x, gy + 1, side ? 7 : 12, 5, "#2b2f3d");
      p.px(x + 2, gy + 3, 2, 1, working && f % 2 ? WHITE : P.trim);
      p.px(x + (side ? 4 : 7), gy + 2, 2, 2, working && f % 2 === 0 ? WHITE : P.gear);
      break;
    }
    case "keyboard": {
      const x = side ? gx : cx - 7;
      p.box(x, gy + 2, side ? 8 : 14, 5, P.gear);
      for (let k = 0; k < (side ? 3 : 6); k++) p.px(x + 1 + k * 2, gy + 3, 1, 1, working && k === f % 6 ? WHITE : P.trim);
      p.box(cx - 2 + side * 3, by + 2, 5, 4, "#2b2f3d"); p.px(cx - 1 + side * 3, by + 3, 3, 1, WHITE);  // CC tile
      break;
    }
    case "printer": {
      const x = side ? gx : cx - 5;
      p.box(x, gy, side ? 7 : 10, 5, P.gearDark);
      p.px(x + 2, gy + 1, side ? 3 : 6, 1, "#3a3f4b");
      const out = working ? 1 + (f % 3) : 1;
      p.px(x + 2, gy + 5, side ? 3 : 6, out, WHITE);
      break;
    }
    case "scanner": {
      const sx = side ? gx : bx + bw;
      p.box(sx, gy, 4, 6, P.gearDark); p.px(sx + 1, gy + 1, 2, 2, P.trim);
      if (working && f % 2) p.px(sx + (side < 0 ? -6 : 4), gy + 2, 6, 1, P.trim, 0.8);  // the beam only while checking
      if (!side) { p.box(bx - 4, gy, 5, 8, P.gear); p.px(bx - 3, gy + 2, 3, 1, WHITE); }
      break;
    }
    case "id-reader": {
      const x = side ? gx : cx - 4;
      p.box(x, gy + 1, side ? 6 : 8, 7, P.gearDark);
      p.px(x + 1, gy + 2, side ? 4 : 6, 2, "#9fd2ff");
      p.px(x + (side ? 2 : 3), gy + 5, 2, 1, working ? (f % 2 ? GOOD : AMBER) : P.trim);
      break;
    }
    case "parcel": {  // the parcel carrier on the cart
      const lift = pose === "carry" && f % 2 ? 1 : 0;
      p.box(cx - 5, by - 5 - lift, 10, 7, P.gear);
      p.px(cx - 1, by - 5 - lift, 2, 7, P.gearDark);
      if (working) p.px(cx - 4 + (f % 3) * 3, by - 3, 2, 1, WHITE);
      break;
    }
    case "notebook": {
      const x = tablet(side ? 6 : 9, 8, P.gear, P.shade);
      p.px(x, gy, 1, 8, P.trimDark);
      if (working) p.px(x + 2 + (f % 2) * 2, gy + 6, 2, 1, P.trim);
      break;
    }
    case "node-pattern":
      for (const [dx, dy] of [[1, 2], [4, 1], [bw - 6, 1], [bw - 3, 2]]) p.px(bx + dx, by + dy, 2, 2, P.trim);
      p.px(bx + 2, by + 2, 3, 1, P.trimDark); p.px(bx + bw - 5, by + 2, 3, 1, P.trimDark);
      if (working) p.px(cx - 1, by + 5, 3, 3, f % 2 ? WHITE : P.trim);
      break;
    case "wrench": {
      const wx = side ? gx : bx + bw;
      const turn = working ? f % 2 : 0;
      p.px(wx + 1, gy - turn, 2, 7, "#9aa3b5"); p.px(wx, gy - 2 - turn, 4, 3, INK); p.px(wx + 1, gy - 1 - turn, 2, 1, "#9aa3b5");
      break;
    }
  }
}

function bodyDecor(p: Pix, c: Character, bx: number, by: number, bw: number, bh: number, dir: Dir) {
  const P = c.palette, cx = bx + Math.floor(bw / 2);
  if (dir === "up") {
    p.px(bx + 3, by + 3, bw - 6, 2, P.shade);
    return;
  }
  const side = dir === "left" || dir === "right";
  if (c.rank === "manager") p.px(bx + bw - 4, by + 1, 4, 2, P.trim);  // a shoulder tab in the department's color
  if (c.body === "jacket") {
    p.px(cx - 4, by + 1, 2, bh - 3, P.trim); p.px(cx + 3, by + 1, 2, bh - 3, P.trim);
    if (!side) { p.px(cx - 1, by + 1, 3, 2, P.gear); p.px(cx, by + 3, 1, 6, P.gear); }
  }
  if (c.body === "shield" && !side) {
    p.px(cx - 2, by + 3, 5, 5, P.trim);
    if (c.id === "lock") { p.px(cx - 1, by + 3, 3, 1, INK); p.px(cx, by + 5, 1, 2, INK); }
    else p.px(cx - 1, by + 5, 1, 1, INK);
  }
  if (c.body === "stocky") for (let k = 0; k < bw - 2; k += 4) p.px(bx + 1 + k, by + bh - 3, 2, 2, P.trim);
  if (c.body === "cart") { p.px(bx + 1, by + 3, bw - 2, 1, P.shade); p.px(bx + 2, by + bh - 3, bw - 4, 1, INK, 0.4); }
  if (c.body === "torso" || c.body === "slim") p.px(cx - 1, by + 3, 3, 2, P.trim);
  if (c.body === "pear") p.px(cx - 2, by + bh - 4, 5, 1, P.trimDark);
  if (c.body === "round") p.px(cx - 1, by + 3, 3, 1, P.trim);
}

/** The gold crown badge COMMAND and every manager wear on the left shoulder (the reference sheet). */
function rankBadge(p: Pix, c: Character, bx: number, by: number, bw: number, dir: Dir) {
  if (c.rank === "worker" || dir === "up" || dir === "right") return;
  const x = dir === "left" ? bx + Math.floor(bw / 2) - 3 : bx - 2, y = by;
  p.box(x, y, 7, 6, "#1b2340");
  for (const dx of [1, 3, 5]) p.px(x + dx, y + 1, 1, 2, CROWN);
  p.px(x + 1, y + 3, 5, 2, CROWN);
}

// ------------------------------------------------------------------ pose overlays (above the head)
function bubble(p: Pix, x: number, y: number, kind: Pose, f: number) {
  const box = (fill: string) => { p.box(x, y, 9, 8, fill); p.px(x + 3, y + 8, 2, 1, INK); };
  switch (kind) {
    case "approved": box(GOOD); p.px(x + 2, y + 4, 1, 1, INK); p.px(x + 3, y + 5, 1, 1, INK); p.px(x + 4, y + 4, 1, 1, INK);
      p.px(x + 5, y + 3, 1, 1, INK); p.px(x + 6, y + 2, 1, 1, INK); break;
    case "rework": box(AMBER); p.px(x + 3, y + 2, 3, 1, INK); p.px(x + 2, y + 3, 1, 2, INK); p.px(x + 3, y + 5, 4, 1, INK);
      p.px(x + 2, y + 2, 1, 1, INK); break;
    case "error": box(f % 2 ? BAD : "#ff8a98"); p.px(x + 4, y + 2, 1, 3, INK); p.px(x + 4, y + 6, 1, 1, INK); break;
    case "retry": box("#9fd2ff"); p.px(x + 3, y + 2, 3, 1, INK); p.px(x + 6, y + 3, 1, 2, INK); p.px(x + 2, y + 3, 1, 2, INK);
      p.px(x + 3, y + 5, 3, 1, INK); p.px(x + 2 + [0, 4, 4, 0][f % 4], y + [2, 2, 5, 5][f % 4], 1, 1, "#ffffff"); break;
    case "wait": box(WHITE); p.px(x + 2, y + 2, 5, 1, INK); p.px(x + 3, y + 3, 3, 1, f % 2 ? INK : AMBER);
      p.px(x + 4, y + 4, 1, 1, INK); p.px(x + 3, y + 5, 3, 1, f % 2 ? AMBER : INK); p.px(x + 2, y + 6, 5, 1, INK); break;
    case "review": box(WHITE); for (let k = 0; k < 3; k++) p.px(x + 2 + k * 2, y + 4, 1, 1, k <= f % 3 ? INK : "#a6b0c2"); break;
    case "paused": box("#a6b0c2"); p.px(x + 2, y + 2, 4, 1, INK); p.px(x + 5, y + 3, 1, 1, INK); p.px(x + 4, y + 4, 1, 1, INK);
      p.px(x + 3, y + 5, 1, 1, INK); p.px(x + 3, y + 6, 4, 1, INK); break;
    default: break;
  }
}

function carriedCard(p: Pix, c: Character, cx: number, y: number, f: number) {
  const accent = c.palette.trim;
  const bob = f % 2;
  p.box(cx - 5, y - bob, 11, 8, WHITE);
  p.px(cx - 3, y + 2 - bob, 7, 1, accent);
  p.px(cx - 3, y + 4 - bob, 5, 1, "#a6b0c2");
}

// ------------------------------------------------------------------ the sprite
const cache = new Map<string, Rect[]>();

export function sprite(role: string, dir: Dir = "down", pose: Pose = "idle", frame = 0): Rect[] {
  const c = BY_ID[role];
  if (!c) return [];
  const f = frame % Math.max(1, FRAMES[pose]?.n || 1);
  const key = `${role}|${dir}|${pose}|${f}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const p = new Pix();
  const s = SIZE[c.rank];
  const cx = 24;
  const moving = pose === "walk" || pose === "carry";
  const bob = moving ? [0, -1, 0, -1][f] : pose === "idle" && f === 1 ? 1 : 0;
  const lh = c.base === "wheels" ? 5 : s.lh;
  const legTop = 62 - lh;
  const body = bodyShape(c, s.bw, s.bh);
  const by = legTop - body.h + 1 + Math.max(0, bob);
  const bw = dir === "left" || dir === "right" ? Math.max(10, body.w - 4) : body.w;
  const bx = cx - Math.floor(bw / 2);
  const hd = headSize(c);
  const hw = dir === "left" || dir === "right" ? Math.max(11, hd.w - 4) : hd.w;
  const hx = cx - Math.floor(hw / 2) + (dir === "right" ? 1 : dir === "left" ? -1 : 0);
  const hy = by - hd.h - 1 + (bob < 0 ? bob : 0);  // a short neck keeps head and body apart
  const lit = pose === "work" || pose === "error" || pose === "review";
  const eyesOn = pose !== "paused" && pose !== "unavailable";
  // shadow
  p.px(cx - 10, 61, 20, 2, INK, 0.35);
  drawGear(p, c, bx, by, bw, body.h, dir, pose, f, false);
  drawLegs(p, c, cx, legTop, lh, dir, pose, f);
  p.px(cx - 3, hy + hd.h - 1, 6, by - hy - hd.h + 2, INK);
  p.px(cx - 2, hy + hd.h - 1, 4, by - hy - hd.h + 2, c.palette.shade);
  if (dir !== "down") drawArms(p, c, bx, by, bw, dir, pose, f);
  p.shape(bx, by, bw, body.h, body.inset, c.body === "cart" ? c.palette.shell : c.palette.shell, c.palette.shade);
  bodyDecor(p, c, bx, by, bw, body.h, dir);
  if (dir === "down") drawArms(p, c, bx, by, bw, dir, pose, f);
  if (c.top === "ear-cups" || c.top === "fins" || c.top === "key-tabs" || c.top === "spine" || c.top === "side-dial") {
    p.shape(hx, hy, hw, hd.h, headInset(c, hw, hd.h), c.palette.shell, c.palette.shade);
    headDecor(p, c, hx, hy, hw, hd.h, dir);
    drawVisor(p, c, hx, hy, hw, hd.h, dir, f, eyesOn, pose);
    drawTop(p, c, hx, hy, hw, dir, f, lit);
  } else {
    drawTop(p, c, hx, hy, hw, dir, f, lit && (c.top !== "beacon" || pose === "error"));
    p.shape(hx, hy, hw, hd.h, headInset(c, hw, hd.h), c.palette.shell, c.palette.shade);
    headDecor(p, c, hx, hy, hw, hd.h, dir);
    drawVisor(p, c, hx, hy, hw, hd.h, dir, f, eyesOn, pose);
  }
  if (c.top === "beacon" && pose === "error") drawTop(p, c, hx, hy, hw, dir, f, true);
  drawGear(p, c, bx, by, bw, body.h, dir, pose, f, true);
  rankBadge(p, c, bx, by, bw, dir);
  if (pose === "carry") carriedCard(p, c, cx, by + 2, f);
  const above = Math.max(0, hy - 14);
  // paused robots only dim their eyes: a bubble on every resting robot would read as activity
  if (["approved", "rework", "error", "retry", "wait", "review"].includes(pose)) bubble(p, cx + 4, above, pose, f);
  if (pose === "unavailable") for (const r of p.r) r[5] = (r[5] ?? 1) * 0.45;
  cache.set(key, p.r);
  return p.r;
}

/** Pixel height of the robot above its feet (for name labels and cards). */
export function spriteTop(role: string): number {
  const c = BY_ID[role];
  if (!c) return 30;
  const s = SIZE[c.rank];
  const hd = headSize(c);
  return 62 - s.lh - s.bh - hd.h - 9;
}

export const paletteOf = (role: string): Palette | undefined => BY_ID[role]?.palette;
