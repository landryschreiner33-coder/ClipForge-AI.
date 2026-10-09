/** Living studio floor plan. Routes follow clear aisles and doorways, never the furniture. */
import { CAST, Dir, RoomId } from "./cast";

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
  pulse: at("analyze", 44, 106), gavel: at("analyze", 108, 106),
  boost: at("analyze", 176, 106), vector: at("analyze", 244, 106),
  frame: at("studio", 44, 106), spark: at("studio", 112, 106),
  story: at("studio", 180, 106), splice: at("studio", 244, 106),
  switch: at("system", 44, 118), check: at("system", 108, 118), patch: at("system", 172, 118),
  glyph: at("caption", 44, 118), quill: at("caption", 108, 118), script: at("caption", 172, 118),
  clock: at("schedule", 104, 118),
  lock: at("dock", 44, 118), dock: at("dock", 108, 118), harbor: at("dock", 172, 118),
  metric: at("brain", 40, 236), synapse: at("brain", 120, 236), curator: at("brain", 208, 236),
};
export const CORE_AT: Pt = { x: 812, y: 146 };

export type BreakActivity = "arcade" | "boardgame" | "snack" | "drink" | "read" | "rest";
export interface BreakSpot { id: string; at: Pt; activity: BreakActivity; posture: "stand" | "rest"; dir: Dir }
const breakSpot = (id: string, x: number, y: number, activity: BreakActivity,
  posture: "stand" | "rest" = "rest", dir: Dir = "down"): BreakSpot =>
  ({ id, at: at("lounge", x, y), activity, posture, dir });
/** First 25 spots are stable homes in CAST order. Four extra destinations make leisure visits possible. */
export const BREAK_SPOTS: BreakSpot[] = [
  ...[31, 75, 119, 163, 207].map((x, i) => breakSpot(`arcade-${i + 1}`, x, 76, "arcade", "stand", "up")),
  breakSpot("cafe-drink-1", 252, 76, "drink", "stand"), breakSpot("cafe-snack-1", 296, 76, "snack", "stand"),
  breakSpot("cafe-drink-2", 340, 76, "drink", "stand"), breakSpot("cafe-snack-2", 384, 76, "snack", "stand"),
  breakSpot("game-a-back-1", 54, 130, "boardgame"), breakSpot("game-a-back-2", 116, 130, "boardgame"),
  breakSpot("game-a-front-1", 54, 186, "boardgame", "rest", "up"),
  breakSpot("game-a-front-2", 116, 186, "boardgame", "rest", "up"),
  breakSpot("game-b-back-1", 210, 130, "boardgame"), breakSpot("game-b-back-2", 272, 130, "boardgame"),
  breakSpot("game-b-front-1", 210, 186, "boardgame", "rest", "up"),
  breakSpot("game-b-front-2", 272, 186, "boardgame", "rest", "up"),
  breakSpot("sofa-read-1", 31, 244, "read"), breakSpot("sofa-read-2", 78, 244, "read"),
  breakSpot("sofa-read-3", 125, 244, "read"), breakSpot("sofa-read-4", 172, 244, "read"),
  breakSpot("sofa-drink", 219, 244, "drink"), breakSpot("sofa-read-5", 266, 244, "read"),
  breakSpot("sofa-rest", 313, 244, "rest"), breakSpot("sofa-snack", 360, 244, "snack"),
  breakSpot("game-a-guest", 20, 158, "boardgame", "stand", "right"),
  breakSpot("game-b-guest", 166, 158, "boardgame", "stand", "right"),
  breakSpot("cafe-guest-drink", 328, 144, "drink", "stand"), breakSpot("cafe-guest-snack", 384, 144, "snack", "stand"),
];
export const REST_SEAT: Record<string, Pt> = Object.fromEntries(CAST.map((c, i) => [c.id, BREAK_SPOTS[i].at]));
export const LOUNGE: Pt[] = CAST.map(c => REST_SEAT[c.id]);

export interface LoungeObstacle { id: string; x: number; y: number; w: number; h: number }
const obstacle = (id: string, x: number, y: number, w: number, h: number): LoungeObstacle =>
  ({ id, x: ROOM.lounge.x + x, y: ROOM.lounge.y + y, w, h });
/** Ground footprints, distinct from a prop's projected height. Seat anchors have an explicit safe exit portal. */
export const LOUNGE_OBSTACLES: LoungeObstacle[] = [
  ...[31, 75, 119, 163, 207].map((x, i) => obstacle(`arcade-${i + 1}`, x - 19, 20, 38, 47)),
  obstacle("cafe-counter", 238, 18, 168, 49),
  obstacle("game-table-a", 30, 136, 110, 32), obstacle("game-table-b", 186, 136, 110, 32),
  ...BREAK_SPOTS.filter(s => s.posture === "rest" && s.activity === "boardgame")
    .map(s => obstacle(`chair-${s.id}`, s.at.x - ROOM.lounge.x - 17, s.at.y - ROOM.lounge.y - 8, 34, 11)),
  ...[13, 107, 201, 295].map((x, i) => obstacle(`sofa-${i + 1}`, x, 232, 85, 15)),
  obstacle("reading-library", 391, 161, 19, 53),
];

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
const LOUNGE_MARGIN = 3;
const inObstacle = (p: Pt, o: LoungeObstacle, margin = LOUNGE_MARGIN) => p.x >= o.x - margin
  && p.x <= o.x + o.w + margin && p.y >= o.y - margin && p.y <= o.y + o.h + margin;
const clearLoungePoint = (p: Pt) => !LOUNGE_OBSTACLES.some(o => inObstacle(p, o));
function clearLoungeSegment(a: Pt, b: Pt) {
  return !LOUNGE_OBSTACLES.some(o => a.x === b.x
    ? a.x >= o.x - LOUNGE_MARGIN && a.x <= o.x + o.w + LOUNGE_MARGIN
      && Math.max(a.y, b.y) >= o.y - LOUNGE_MARGIN && Math.min(a.y, b.y) <= o.y + o.h + LOUNGE_MARGIN
    : a.y >= o.y - LOUNGE_MARGIN && a.y <= o.y + o.h + LOUNGE_MARGIN
      && Math.max(a.x, b.x) >= o.x - LOUNGE_MARGIN && Math.min(a.x, b.x) <= o.x + o.w + LOUNGE_MARGIN);
}
/** Seat feet are within their own upholstery footprint; the short portal is their deliberate entry/exit. */
function loungePortal(p: Pt): Pt[] {
  const r = ROOM.lounge;
  const inside = { x: Math.max(r.x + 7, Math.min(r.x + r.w - 8, p.x)),
    y: Math.max(r.y + 12, Math.min(r.y + r.h - 5, p.y)) };
  if (clearLoungePoint(inside)) return dedupe([p, inside]);
  const obstacleAt = LOUNGE_OBSTACLES.find(o => inObstacle(inside, o))!;
  const nearby = BREAK_SPOTS.filter(s => s.posture === "rest" && inObstacle(s.at, obstacleAt))
    .sort((a, b) => Math.abs(a.at.x - p.x) + Math.abs(a.at.y - p.y)
      - Math.abs(b.at.x - p.x) - Math.abs(b.at.y - p.y))[0];
  if (nearby) {
    const y = nearby.at.y + (nearby.id.includes("-back-") ? -14 : 14);
    const portal = { x: inside.x, y };
    if (clearLoungePoint(portal)) return dedupe([p, inside, portal]);
  }
  const candidates = [
    { x: obstacleAt.x - LOUNGE_MARGIN - 1, y: inside.y },
    { x: obstacleAt.x + obstacleAt.w + LOUNGE_MARGIN + 1, y: inside.y },
    { x: inside.x, y: obstacleAt.y - LOUNGE_MARGIN - 1 },
    { x: inside.x, y: obstacleAt.y + obstacleAt.h + LOUNGE_MARGIN + 1 },
  ].filter(q => q.x >= r.x + 7 && q.x <= r.x + r.w - 8 && q.y >= r.y + 12 && q.y <= r.y + r.h - 5
    && clearLoungePoint(q)).sort((a, b) => Math.abs(a.x - p.x) + Math.abs(a.y - p.y)
      - Math.abs(b.x - p.x) - Math.abs(b.y - p.y));
  if (!candidates.length) throw new Error("The lounge point has no clear furniture exit");
  return dedupe([p, inside, candidates[0]]);
}

/** A rectilinear visibility grid follows actual furniture edges, including when a job interrupts a leisure walk. */
function loungeAisle(from: Pt, to: Pt): Pt[] {
  const r = ROOM.lounge;
  const xs = [...new Set([r.x + 7, r.x + r.w - 8, from.x, to.x,
    ...LOUNGE_OBSTACLES.flatMap(o => [o.x - LOUNGE_MARGIN - 1, o.x + o.w + LOUNGE_MARGIN + 1])])]
    .filter(x => x >= r.x + 7 && x <= r.x + r.w - 8).sort((a, b) => a - b);
  const ys = [...new Set([r.y + 12, r.y + r.h - 5, from.y, to.y,
    ...LOUNGE_OBSTACLES.flatMap(o => [o.y - LOUNGE_MARGIN - 1, o.y + o.h + LOUNGE_MARGIN + 1])])]
    .filter(y => y >= r.y + 12 && y <= r.y + r.h - 5).sort((a, b) => a - b);
  const grid = ys.map(() => new Int32Array(xs.length).fill(-1));
  const points: (Pt & { ix: number; iy: number })[] = [];
  for (let iy = 0; iy < ys.length; iy++) for (let ix = 0; ix < xs.length; ix++) {
    const p = { x: xs[ix], y: ys[iy], ix, iy };
    if (clearLoungePoint(p)) { grid[iy][ix] = points.length; points.push(p); }
  }
  const start = points.findIndex(p => p.x === from.x && p.y === from.y);
  const goal = points.findIndex(p => p.x === to.x && p.y === to.y);
  if (start < 0 || goal < 0) throw new Error("The lounge route must start and end in a clear aisle");
  const distances = new Float64Array(points.length).fill(Infinity), previous = new Int32Array(points.length).fill(-1);
  const closed = new Uint8Array(points.length), todo = new Set([start]);
  distances[start] = 0;
  while (todo.size) {
    let current = -1, best = Infinity;
    for (const id of todo) {
      const score = distances[id] + Math.abs(points[id].x - to.x) + Math.abs(points[id].y - to.y);
      if (score < best) [current, best] = [id, score];
    }
    todo.delete(current);
    if (current === goal) break;
    closed[current] = 1;
    const a = points[current];
    for (const [ix, iy] of [[a.ix - 1, a.iy], [a.ix + 1, a.iy], [a.ix, a.iy - 1], [a.ix, a.iy + 1]]) {
      if (ix < 0 || iy < 0 || ix >= xs.length || iy >= ys.length) continue;
      const id = grid[iy][ix];
      if (id < 0 || closed[id] || !clearLoungeSegment(a, points[id])) continue;
      const distance = distances[current] + Math.abs(a.x - points[id].x) + Math.abs(a.y - points[id].y);
      if (distance < distances[id]) { distances[id] = distance; previous[id] = current; todo.add(id); }
    }
  }
  if (!Number.isFinite(distances[goal])) throw new Error("The lounge route has no clear furniture aisle");
  const out: Pt[] = [];
  for (let id = goal; id >= 0; id = previous[id]) out.unshift({ x: points[id].x, y: points[id].y });
  // Keep genuine corners while omitting straight-line grid subdivisions.
  return out.filter((p, i) => i === 0 || i === out.length - 1
    || !((out[i - 1].x === p.x && out[i + 1].x === p.x) || (out[i - 1].y === p.y && out[i + 1].y === p.y)));
}
export function loungeRoute(from: Pt, to: Pt): Pt[] {
  const a = loungePortal(from), b = loungePortal(to);
  return dedupe([...a, ...loungeAisle(a[a.length - 1], b[b.length - 1]), ...b.reverse()]);
}
function exitRoom(p: Pt, r: Room): Pt[] {
  if (r.id === "lounge") return loungeRoute(p, r.door);
  return [p, { x: p.x, y: r.lane }, { x: r.door.x, y: r.lane }, r.door];
}
export function route(from: Pt, to: Pt): Pt[] {
  const a = roomOf(from), b = roomOf(to);
  if (a?.id === "lounge" && b?.id === "lounge") return loungeRoute(from, to);
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
