/**
 * The Brain map's lightning (the owner, 2026-11-19 8:49 PM: "make the brain lines and balls look like lighting and
 * make sure its animated"). A canvas under the map's dots draws every real link as a jagged bolt of light in its
 * collection's colour, every dot as a glowing ball, and CORE as a globe of light with filaments. While motion is
 * allowed the bolts strike again about twelve times a second, in steps, each link at its own pace; the brightness
 * only varies a little, so nothing flashes.
 *
 * It is decoration: the links and dots are the Brain's real records, but the flicker shows no work and no learning.
 * BrainGraph draws one still frame of the same bolts under Reduced motion, Low power, a hidden or off-screen page and
 * while ClipForge is not answering. What a project really used keeps its own rings and words.
 */

export type BoltNode = { id: string; x: number; y: number; r: number; color: string; kind: string; applied: boolean;
  lit: boolean };
export type BoltEdge = { id: string; from: string; to: string; kind: string; color: string;
  /** CORE's branches bend a little, through this point (graph units) */
  bend: { x: number; y: number } | null;
  /** linked to the chosen dot or on its path from CORE */
  lit: boolean };
export type BoltScene = { nodes: BoltNode[]; edges: BoltEdge[];
  /** graph units to CSS pixels: x * scale + ox */
  scale: number; ox: number; oy: number; width: number; height: number; dpr: number };

/** Frames a second while the lightning moves: stepped, like the ship. */
export const BOLT_FPS = 12;

type RGB = [number, number, number];
const parsed = new Map<string, RGB>();
function rgbOf(color: string): RGB {
  let c = parsed.get(color);
  if (!c) {
    const m = /^#([0-9a-f]{6})$/i.exec(color.trim());
    const n = m ? parseInt(m[1], 16) : 0xb4c8ff;
    c = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    parsed.set(color, c);
  }
  return c;
}
const rgba = ([r, g, b]: RGB, a: number) => `rgba(${r}, ${g}, ${b}, ${a})`;
/** towards white: the hot middle of a bolt */
const hot = ([r, g, b]: RGB, k: number): RGB => [r + (255 - r) * k, g + (255 - g) * k, b + (255 - b) * k].map(Math.round) as RGB;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
/** a small seeded random (mulberry32): the same seed always gives the same bolt */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A soft round glow in one colour, painted once and reused for every ball of that colour. */
const glows = new Map<string, HTMLCanvasElement>();
function glow(color: string): HTMLCanvasElement | null {
  let g = glows.get(color);
  if (g) return g;
  g = document.createElement("canvas");
  g.width = g.height = 64;
  const x = g.getContext("2d");
  if (!x) return null;
  const c = rgbOf(color);
  const s = x.createRadialGradient(32, 32, 0, 32, 32, 32);
  s.addColorStop(0, rgba(hot(c, 0.6), 0.9));
  s.addColorStop(0.22, rgba(c, 0.55));
  s.addColorStop(0.55, rgba(c, 0.16));
  s.addColorStop(1, rgba(c, 0));
  x.fillStyle = s;
  x.fillRect(0, 0, 64, 64);
  glows.set(color, g);
  return g;
}

/** A jagged line from a to b (CSS pixels), through `bend` when given: midpoint displacement across the line. */
function bolt(ax: number, ay: number, bx: number, by: number, bend: { x: number; y: number } | null, rnd: () => number,
  rough: number): number[] {
  const len = Math.hypot(bx - ax, by - ay);
  const n = len > 260 ? 32 : len > 100 ? 16 : len > 30 ? 8 : 4;
  const off = new Float32Array(n + 1);
  const amp = Math.min(len * 0.075, 10) * rough;
  for (let step = n; step > 1; step >>= 1) {
    const half = step >> 1, spread = amp * (step / n) * 1.5;
    for (let i = half; i < n; i += step) off[i] = (off[i - half] + off[i + half]) / 2 + (rnd() * 2 - 1) * spread;
  }
  const pts: number[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    let x: number, y: number, tx: number, ty: number;
    if (bend) {
      x = u * u * ax + 2 * u * t * bend.x + t * t * bx;
      y = u * u * ay + 2 * u * t * bend.y + t * t * by;
      tx = 2 * u * (bend.x - ax) + 2 * t * (bx - bend.x);
      ty = 2 * u * (bend.y - ay) + 2 * t * (by - bend.y);
    } else {
      x = ax + (bx - ax) * t;
      y = ay + (by - ay) * t;
      tx = bx - ax;
      ty = by - ay;
    }
    const tl = Math.hypot(tx, ty) || 1;
    pts.push(x - (ty / tl) * off[i], y + (tx / tl) * off[i]);
  }
  return pts;
}

function trace(g: CanvasRenderingContext2D, pts: number[]) {
  g.beginPath();
  g.moveTo(pts[0], pts[1]);
  for (let i = 2; i < pts.length; i += 2) g.lineTo(pts[i], pts[i + 1]);
}

/** One bolt in up to three strokes: a wide faint glow (the costly one, kept for CORE's branches, the chosen dot's
 * links and sparks), the coloured body and a thin white-hot core. */
function strike(g: CanvasRenderingContext2D, pts: number[], c: RGB, width: number, bright: number, dashed: boolean,
  halo = true) {
  trace(g, pts);
  g.setLineDash([]);
  if (halo) {
    g.lineWidth = width * 5;
    g.strokeStyle = rgba(c, 0.12 * bright);
    g.stroke();
  }
  if (dashed) g.setLineDash([5, 4]);
  g.lineWidth = width * 2;
  g.strokeStyle = rgba(c, 0.5 * bright);
  g.stroke();
  g.lineWidth = Math.max(0.8, width * 0.7);
  g.strokeStyle = rgba(hot(c, 0.7), Math.min(1, 0.95 * bright));
  g.stroke();
}

const WIDTH: Record<string, number> = { branch: 1.8, collection: 1, topic: 0.6, evidence: 0.75, use: 0.85,
  provenance: 0.85 };
const LEVEL: Record<string, number> = { branch: 1, collection: 0.78, topic: 0.42, evidence: 0.62, use: 0.7,
  provenance: 0.72 };

/**
 * Draws frame `frame` of the lightning. Frame 0 is the still picture. A link keeps its shape for 2 to 5 frames before
 * it strikes again, so the map never flickers all at once.
 */
export function drawLightning(g: CanvasRenderingContext2D, scene: BoltScene, frame: number) {
  const { nodes, edges, scale, ox, oy, dpr } = scene;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, g.canvas.width, g.canvas.height);
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.globalCompositeOperation = "lighter";
  g.lineJoin = "round";
  g.lineCap = "round";
  const at = new Map(nodes.map((n) => [n.id, n]));
  const sx = (x: number) => x * scale + ox, sy = (y: number) => y * scale + oy;
  const zoom = Math.max(0.6, Math.min(1.6, scale));
  const chosen = edges.some((e) => e.lit);

  for (const e of edges) {
    const a = at.get(e.from), b = at.get(e.to);
    if (!a || !b) continue;
    const id = hash(e.id), pace = 2 + (id % 4);
    const turn = frame === 0 ? 0 : Math.floor((frame + (id % 7)) / pace);
    const rnd = seeded(id ^ Math.imul(turn + 1, 2654435761));
    const kind = a.kind === "brain" ? "branch" : e.kind;
    const pts = bolt(sx(a.x), sy(a.y), sx(b.x), sy(b.y), e.bend ? { x: sx(e.bend.x), y: sy(e.bend.y) } : null, rnd,
      kind === "branch" ? 1 : 0.8);
    // a gentle flicker, frame by frame; links of the chosen dot shine brighter and the rest step back a little
    const flick = frame === 0 ? 1 : 0.84 + 0.16 * seeded(id ^ Math.imul(frame, 40503))();
    const level = (LEVEL[kind] ?? 0.6) * (e.lit ? 1.35 : chosen ? 0.75 : 1) * flick;
    strike(g, pts, rgbOf(e.color), (WIDTH[kind] ?? 0.8) * zoom * (e.lit ? 1.5 : 1), level,
      kind === "evidence" || kind === "provenance", kind === "branch" || e.lit);
    // CORE's branches throw a short fork now and then
    if (kind === "branch" && rnd() < 0.55) {
      const i = 2 * (2 + Math.floor(rnd() * (pts.length / 2 - 4)));
      const ang = Math.atan2(pts[i + 3] - pts[i + 1], pts[i + 2] - pts[i]) + (rnd() < 0.5 ? -1 : 1) * (0.5 + rnd() * 0.5);
      const reach = (14 + rnd() * 22) * zoom;
      const fork = bolt(pts[i], pts[i + 1], pts[i] + Math.cos(ang) * reach, pts[i + 1] + Math.sin(ang) * reach, null, rnd,
        1);
      strike(g, fork, rgbOf(e.color), 0.8 * zoom, 0.55 * flick, false);
    }
  }
  g.setLineDash([]);

  for (const n of nodes) {
    const x = sx(n.x), y = sy(n.y), r = Math.max(2.5, n.r * scale);
    const id = hash(n.id);
    const flick = frame === 0 ? 1 : 0.82 + 0.18 * seeded(id ^ Math.imul(frame, 69069))();
    const sprite = glow(n.applied ? "#ffffff" : n.color);
    const big = n.kind === "brain" ? 4.2 : n.kind === "collection" ? 3.6 : n.applied || n.lit ? 3.6 : 3;
    if (sprite) {
      g.globalAlpha = (n.kind === "brain" ? 0.9 : 0.75) * flick;
      g.drawImage(sprite, x - r * big, y - r * big, r * big * 2, r * big * 2);
      g.globalAlpha = 1;
    }
    const c = rgbOf(n.color);
    const turn = frame === 0 ? 0 : Math.floor((frame + (id % 5)) / 2);
    const rnd = seeded(id ^ Math.imul(turn + 7, 2246822519));
    if (n.kind === "brain") {
      // a globe of light: filaments from the middle to the glass, as in a plasma ball
      const warm: RGB = [255, 214, 160];
      for (let i = 0; i < 8; i++) {
        const ang = (i / 8) * Math.PI * 2 + rnd() * 0.7;
        const f = bolt(x, y, x + Math.cos(ang) * r * 0.96, y + Math.sin(ang) * r * 0.96, null, rnd, 1.6);
        strike(g, f, i % 2 ? warm : [150, 210, 255], 0.9 * zoom, 0.8 * flick, false);
      }
    } else if (n.kind === "collection") {
      // a few sparks crackle off a collection's ball
      for (let i = 0; i < 3; i++) {
        const ang = rnd() * Math.PI * 2, reach = r * (0.7 + rnd() * 0.9);
        const px = x + Math.cos(ang) * r, py = y + Math.sin(ang) * r;
        const f = bolt(px, py, px + Math.cos(ang + rnd() - 0.5) * reach, py + Math.sin(ang + rnd() - 0.5) * reach, null,
          rnd, 1.4);
        strike(g, f, c, 0.7 * zoom, 0.7 * flick, false);
      }
    } else if (rnd() < (frame === 0 ? 0 : 0.12)) {
      // and now and then off a small one
      const ang = rnd() * Math.PI * 2, reach = r * (1.2 + rnd());
      const px = x + Math.cos(ang) * r, py = y + Math.sin(ang) * r;
      strike(g, bolt(px, py, px + Math.cos(ang) * reach, py + Math.sin(ang) * reach, null, rnd, 1.4), c, 0.6 * zoom,
        0.6 * flick, false);
    }
  }
  g.globalCompositeOperation = "source-over";
}
