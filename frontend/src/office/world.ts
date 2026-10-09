/** Living studio floor plan. Routes follow clear aisles and doorways, never the furniture. */
import { CAST, RoomId } from "./cast";

export const WORLD = { w: 960, h: 640 };
export const ROBOT_SCALE = 0.8;
export type Pt = { x: number; y: number };
export interface Room {
  id: RoomId; x: number; y: number; w: number; h: number;
  door: Pt; corridor: Pt; lane: number;
}

const room = (id: RoomId, x: number, y: number, w: number, h: number,
  side: "left" | "right" | "bottom", corridor: Pt): Room => {
  const lane = y + h - 20;
  return { id, x, y, w, h, lane, corridor,
    door: side === "bottom" ? { x: x + w / 2, y: y + h }
      : { x: side === "left" ? x : x + w, y: lane } };
};

export const ROOMS: Room[] = [
  room("lounge", 8, 8, 416, 264, "right", { x: 440, y: 252 }),
  room("boss", 456, 8, 192, 128, "bottom", { x: 552, y: 148 }),
  room("workspace", 456, 160, 192, 112, "bottom", { x: 552, y: 284 }),
  room("brain", 680, 8, 272, 264, "left", { x: 664, y: 252 }),
  room("discover", 8, 296, 288, 140, "right", { x: 316, y: 416 }),
  room("analyze", 336, 296, 288, 140, "left", { x: 316, y: 416 }),
  room("studio", 664, 296, 288, 140, "left", { x: 644, y: 416 }),
  room("system", 8, 464, 208, 168, "right", { x: 232, y: 612 }),
  room("caption", 248, 464, 208, 168, "left", { x: 232, y: 612 }),
  room("schedule", 488, 464, 208, 168, "left", { x: 472, y: 612 }),
  room("dock", 728, 464, 208, 168, "left", { x: 712, y: 612 }),
];
export const ROOM: Record<string, Room> = Object.fromEntries(ROOMS.map(r => [r.id, r]));
// A small entry threshold in the main hall; it is scenery, not a standing station.
export const ENTRANCE = { x: 436, y: 440, w: 48, h: 20 };

const at = (id: RoomId, x: number, y: number): Pt => ({ x: ROOM[id].x + x, y: ROOM[id].y + y });
/** Desk foot anchors. Every role retains its own workplace and its stable identity. */
export const STATION: Record<string, Pt> = {
  command: at("boss", 96, 106),
  tracker: at("discover", 44, 106), radar: at("discover", 144, 106), archive: at("discover", 244, 106),
  pulse: at("analyze", 44, 106), gavel: at("analyze", 108, 106), boost: at("analyze", 176, 106), vector: at("analyze", 244, 106),
  frame: at("studio", 44, 106), spark: at("studio", 112, 106), story: at("studio", 180, 106), splice: at("studio", 244, 106),
  switch: at("system", 44, 118), check: at("system", 108, 118), patch: at("system", 172, 118),
  glyph: at("caption", 44, 118), quill: at("caption", 108, 118), script: at("caption", 172, 118),
  clock: at("schedule", 104, 118),
  lock: at("dock", 44, 118), dock: at("dock", 108, 118), harbor: at("dock", 172, 118),
  metric: at("brain", 40, 236), synapse: at("brain", 120, 236), curator: at("brain", 208, 236),
};
export const CORE_AT: Pt = { x: 812, y: 146 };

/** One stable, visible lounge seat per robot. A changing feed never reorders the seats. */
export const REST_SEAT: Record<string, Pt> = Object.fromEntries(CAST.map((c, i) => [c.id,
  at("lounge", 32 + (i % 7) * 54, 76 + Math.floor(i / 7) * 56)]));
export const LOUNGE: Pt[] = CAST.map(c => REST_SEAT[c.id]);

const key = (p: Pt) => `${p.x},${p.y}`;
const nodes = new Map<string, Pt>();
const edges = new Map<string, Set<string>>();
function link(a: Pt, b: Pt) {
  for (const p of [a, b]) {
    nodes.set(key(p), p);
    if (!edges.has(key(p))) edges.set(key(p), new Set());
  }
  edges.get(key(a))!.add(key(b)); edges.get(key(b))!.add(key(a));
}
function horizontal(y: number, xs: number[]) {
  for (let i = 1; i < xs.length; i++) link({ x: xs[i - 1], y }, { x: xs[i], y });
}
function vertical(x: number, ys: number[]) {
  for (let i = 1; i < ys.length; i++) link({ x, y: ys[i - 1] }, { x, y: ys[i] });
}
// The 32–40px vertical aisles join two broad horizontal halls. The smaller upper hall only spans the boss area.
horizontal(148, [440, 552, 664]);
for (const x of [440, 664]) vertical(x, [148, 252, 284]);
horizontal(284, [16, 232, 316, 440, 552, 644, 664, 712, 944]);
for (const x of [316, 644]) vertical(x, [284, 416, 450]);
horizontal(450, [16, 232, 316, 472, 644, 712, 944]);
for (const x of [232, 472, 712]) vertical(x, [450, 612]);

function nearestNode(p: Pt): string {
  let best = "", distance = Infinity;
  for (const [k, n] of nodes) {
    const d = Math.abs(n.x - p.x) + Math.abs(n.y - p.y);
    if (d < distance) [best, distance] = [k, d];
  }
  return best;
}
function shortest(from: string, to: string): Pt[] {
  const distances = new Map<string, number>([[from, 0]]), previous = new Map<string, string>();
  const todo = new Set([from]);
  while (todo.size) {
    let current = "", best = Infinity;
    for (const k of todo) if ((distances.get(k) ?? Infinity) < best) [current, best] = [k, distances.get(k)!];
    todo.delete(current);
    if (current === to) break;
    const a = nodes.get(current)!;
    for (const next of edges.get(current) || []) {
      const b = nodes.get(next)!;
      const d = best + Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      if (d < (distances.get(next) ?? Infinity)) {
        distances.set(next, d); previous.set(next, current); todo.add(next);
      }
    }
  }
  const out: Pt[] = [];
  for (let k: string | undefined = to; k; k = previous.get(k)) {
    out.unshift(nodes.get(k)!);
    if (k === from) break;
  }
  return out;
}

export function roomOf(p: Pt): Room | undefined {
  return ROOMS.find(r => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h);
}
/** Leave the chair forwards, turn into the gap between seat columns, then follow the clear bottom aisle. */
function exitRoom(p: Pt, r: Room): Pt[] {
  if (r.id === "lounge") {
    const aisleX = r.x + r.w - 24;
    if (p.x >= aisleX - 4) return [p, { x: aisleX, y: p.y }, { x: aisleX, y: r.lane }, r.door];
    const bottomAisleY = Math.max(r.lane, r.y + 244 + 9);
    const gaps = Array.from({ length: 7 }, (_, col) => r.x + 32 + col * 54 + 27);
    const existingGap = gaps.find(x => Math.abs(x - p.x) < 2);
    if (existingGap !== undefined) return [p, { x: existingGap, y: p.y }, { x: existingGap, y: bottomAisleY },
      { x: aisleX, y: bottomAisleY }, { x: aisleX, y: r.lane }, r.door];
    const nearestRow = Math.max(0, Math.min(3, Math.round((p.y - r.y - 76) / 56)));
    const nearestColumn = Math.max(0, Math.min(6, Math.round((p.x - r.x - 32) / 54)));
    const aisleY = r.y + 85 + nearestRow * 56, gapX = gaps[nearestColumn];
    return [p, { x: p.x, y: aisleY }, { x: gapX, y: aisleY }, { x: gapX, y: bottomAisleY },
      { x: aisleX, y: bottomAisleY }, { x: aisleX, y: r.lane }, r.door];
  }
  return [p, { x: p.x, y: r.lane }, { x: r.door.x, y: r.lane }, r.door];
}
export function route(from: Pt, to: Pt): Pt[] {
  const a = roomOf(from), b = roomOf(to);
  if (a && b && a.id === b.id) return dedupe([...exitRoom(from, a), ...exitRoom(to, b).reverse()]);
  const out: Pt[] = a ? [...exitRoom(from, a), a.corridor] : [from];
  out.push(...shortest(a ? key(a.corridor) : nearestNode(from), b ? key(b.corridor) : nearestNode(to)));
  if (b) out.push(b.corridor, ...exitRoom(to, b).reverse());
  else out.push(to);
  return dedupe(out);
}
function dedupe(points: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of points) {
    const previous = out[out.length - 1];
    if (!previous || previous.x !== p.x || previous.y !== p.y) {
      if (previous && previous.x !== p.x && previous.y !== p.y) out.push({ x: p.x, y: previous.y });
      out.push(p);
    }
  }
  return out;
}
/** Visitors meet the manager beside the desk, with their feet in the unobstructed room aisle. */
export function besideManager(manager: string): Pt {
  const p = STATION[manager], r = roomOf(p)!;
  return { x: p.x + (p.x - r.x > r.w / 2 ? -36 : 36), y: r.lane };
}
