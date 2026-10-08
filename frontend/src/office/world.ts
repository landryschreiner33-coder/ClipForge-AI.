/**
 * The office floor plan in world pixels (layout of reference image A): rooms, corridors, the walkable waypoint graph
 * and each role's station. Robots only move along these routes, so they never cross desks or walls.
 *
 *   Lounge     | Boss Hub        | Brain Room
 *   Discover   | Team Workspace  | Analyze
 *   Clip Studio| System          | Caption
 *   Schedule   | (entrance)      | Upload Dock
 */
import { RoomId } from "./cast";

// sized so the whole office fits a 1280×720 window at 1:1 or larger (whole pixels, nothing shrunk)
export const WORLD = { w: 704, h: 464 };
const COL = [8, 256, 464];
const COLW = [232, 192, 232];
const ROW = [8, 124, 240, 356];
const ROWH = 100;
const LANE = 20;          // the walking lane runs this far above a room's bottom wall
const VX = [248, 456];    // the two vertical corridors
const HY = [116, 232, 348];
const MID = COL[1] + COLW[1] / 2;

export interface Room { id: RoomId; x: number; y: number; w: number; h: number; door: Pt; corridor: Pt }
export type Pt = { x: number; y: number };

const GRID: [RoomId, number, number][] = [
  ["lounge", 0, 0], ["boss", 1, 0], ["brain", 2, 0],
  ["discover", 0, 1], ["workspace", 1, 1], ["analyze", 2, 1],
  ["studio", 0, 2], ["system", 1, 2], ["caption", 2, 2],
  ["schedule", 0, 3], ["dock", 2, 3],
];

export const ROOMS: Room[] = GRID.map(([id, c, r]) => {
  const x = COL[c], y = ROW[r], w = COLW[c], h = ROWH;
  const lane = y + h - LANE;
  // side rooms open onto the vertical corridor next to them; center rooms open downwards
  const door = c === 0 ? { x: x + w, y: lane } : c === 2 ? { x, y: lane } : { x: x + w / 2, y: y + h };
  const corridor = c === 0 ? { x: VX[0], y: lane } : c === 2 ? { x: VX[1], y: lane } : { x: x + w / 2, y: y + h + 8 };
  return { id, x, y, w, h, door, corridor };
});
export const ROOM: Record<string, Room> = Object.fromEntries(ROOMS.map((r) => [r.id, r]));
export const ENTRANCE = { x: COL[1], y: ROW[3], w: COLW[1], h: ROWH };

// ------------------------------------------------------------------ waypoint graph
const key = (p: Pt) => `${p.x},${p.y}`;
const nodes = new Map<string, Pt>();
const edges = new Map<string, Set<string>>();
function link(a: Pt, b: Pt) {
  for (const p of [a, b]) {
    nodes.set(key(p), p);
    if (!edges.has(key(p))) edges.set(key(p), new Set());
  }
  edges.get(key(a))!.add(key(b));
  edges.get(key(b))!.add(key(a));
}
// each vertical corridor: a chain through every point that touches it, top to bottom
for (const vx of VX) {
  const ys = new Set<number>(HY);
  for (const r of ROOMS) if (r.corridor.x === vx) ys.add(r.corridor.y);
  const sorted = [...ys].sort((a, b) => a - b);
  for (let i = 1; i < sorted.length; i++) link({ x: vx, y: sorted[i - 1] }, { x: vx, y: sorted[i] });
}
// each horizontal corridor joins the two vertical ones through the point below the center room's door
for (const hy of HY) {
  link({ x: VX[0], y: hy }, { x: MID, y: hy });
  link({ x: MID, y: hy }, { x: VX[1], y: hy });
}
// the entrance hall connects to the corridor above it
link({ x: MID, y: HY[2] }, { x: MID, y: ROW[3] + 50 });

function nearestNode(p: Pt): string {
  let best = "", d = Infinity;
  for (const [k, n] of nodes) {
    const dd = Math.abs(n.x - p.x) + Math.abs(n.y - p.y);
    if (dd < d) [best, d] = [k, dd];
  }
  return best;
}

function shortest(from: string, to: string): Pt[] {
  const dist = new Map<string, number>([[from, 0]]);
  const prev = new Map<string, string>();
  const todo = new Set<string>([from]);
  while (todo.size) {
    let cur = "", best = Infinity;
    for (const k of todo) if ((dist.get(k) ?? Infinity) < best) [cur, best] = [k, dist.get(k)!];
    todo.delete(cur);
    if (cur === to) break;
    const a = nodes.get(cur)!;
    for (const nb of edges.get(cur) || []) {
      const b = nodes.get(nb)!;
      const nd = best + Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
      if (nd < (dist.get(nb) ?? Infinity)) {
        dist.set(nb, nd);
        prev.set(nb, cur);
        todo.add(nb);
      }
    }
  }
  const out: Pt[] = [];
  for (let k: string | undefined = to; k; k = prev.get(k)) {
    out.unshift(nodes.get(k)!);
    if (k === from) break;
  }
  return out;
}

export function roomOf(p: Pt): Room | undefined {
  return ROOMS.find((r) => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h);
}

/** A route from one standing point to another: down to the room's walking lane, out of the door, along the
 * corridors and in through the other door. Axis-aligned segments only. */
export function route(from: Pt, to: Pt): Pt[] {
  const a = roomOf(from), b = roomOf(to);
  if (a && b && a.id === b.id) {
    const lane = a.y + a.h - LANE;
    return dedupe([from, { x: from.x, y: lane }, { x: to.x, y: lane }, to]);
  }
  const out: Pt[] = [from];
  if (a) {
    const lane = a.y + a.h - LANE;
    out.push({ x: from.x, y: lane }, { x: a.door.x, y: a.door.y === a.y + a.h ? lane : a.door.y }, a.door, a.corridor);
  }
  const start = a ? key(a.corridor) : nearestNode(from);
  const goal = b ? key(b.corridor) : nearestNode(to);
  if (!nodes.has(start)) nodes.set(start, a!.corridor);
  out.push(...shortest(start, goal));
  if (b) {
    const lane = b.y + b.h - LANE;
    out.push(b.corridor, b.door, { x: b.door.x, y: b.door.y === b.y + b.h ? lane : b.door.y }, { x: to.x, y: lane });
  }
  out.push(to);
  return dedupe(out);
}

function dedupe(pts: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of pts) {
    const last = out[out.length - 1];
    if (!last || last.x !== p.x || last.y !== p.y) {
      // keep every segment axis-aligned: insert a corner when both coordinates change
      if (last && last.x !== p.x && last.y !== p.y) out.push({ x: p.x, y: last.y });
      out.push(p);
    }
  }
  return out;
}

// ------------------------------------------------------------------ stations (feet positions)
const at = (room: RoomId, dx: number, dy: number): Pt => ({ x: ROOM[room].x + dx, y: ROOM[room].y + dy });

/** Where each role stands while on duty. Managers stand at the front of their room. */
export const STATION: Record<string, Pt> = {
  command: at("boss", 96, 66),
  tracker: at("discover", 52, 70), radar: at("discover", 120, 62), archive: at("discover", 182, 62),
  vector: at("analyze", 186, 70), pulse: at("analyze", 46, 62), gavel: at("analyze", 96, 62),
  boost: at("analyze", 140, 62),
  frame: at("studio", 52, 70), spark: at("studio", 104, 62), story: at("studio", 148, 62),
  splice: at("studio", 194, 62),
  script: at("caption", 186, 70), glyph: at("caption", 60, 62), quill: at("caption", 120, 62),
  clock: at("schedule", 96, 66),
  harbor: at("dock", 186, 70), lock: at("dock", 64, 62), dock: at("dock", 126, 64),
  switch: at("system", 40, 70), check: at("system", 96, 62), patch: at("system", 152, 62),
  curator: at("brain", 186, 70), metric: at("brain", 36, 64), synapse: at("brain", 76, 64),
};
export const CORE_AT: Pt = at("brain", 132, 56);

/** Lounge places for idle and paused workers (the rest are counted, not drawn). */
export const LOUNGE: Pt[] = [
  at("lounge", 36, 60), at("lounge", 150, 58), at("lounge", 96, 76), at("lounge", 204, 74), at("lounge", 40, 84),
  at("lounge", 160, 84),
];

/** Where a worker stands to hand a card to its manager (beside the manager, facing it). */
export function besideManager(manager: string): Pt {
  const m = STATION[manager];
  const r = roomOf(m)!;
  const left = m.x - r.x > r.w / 2;
  return { x: m.x + (left ? -22 : 22), y: m.y };
}
