/** The ship's floor plan (frontend/src/space/ship-world.json). One world unit is half a pixel of the ship art, so
 * the crew sprites (drawn at twice the ship's detail) sit on it one to one. Routes follow the halls, doorways and
 * lounge walkways, never through a wall. */
import { CAST, Dir, RoomId } from "./cast";
import SHIP from "../space/ship-world.json";

export const WORLD = { w: SHIP.world.w, h: SHIP.world.h };
/** The drawn area: a margin left of the hull leaves room for the engine flames. */
export const VIEW = { x: SHIP.view.x, y: SHIP.view.y, w: SHIP.view.w, h: SHIP.view.h };
export const ROBOT_SCALE = 1;
export type Pt = { x: number; y: number };
export interface Room {
  id: RoomId; x: number; y: number; w: number; h: number;
  door: Pt; corridor: Pt; lane: number; accent: string;
}

type ShipRoom = { x: number; y: number; w: number; h: number; doors: number[][]; accent: string };
const HALL_Y = SHIP.halls.main.y, LOWER_Y = SHIP.halls.lower.y;
// Where robots walk inside each room: behind the desks in the two lower rows, in front of them upstairs.
const LANE: Record<RoomId, number> = {
  lounge: 254, brain: 300, control: 296, intake: 466, research: 466, story: 466, editing: 466,
  sound: 600, quality: 600, publishing: 600,
};
const LOWER_ROW = new Set<RoomId>(["sound", "quality", "publishing"]);

export const ROOMS: Room[] = (Object.entries(SHIP.rooms) as [RoomId, ShipRoom][]).map(([id, r]) => {
  const [dx, dy] = r.doors[0];
  return { id, x: r.x, y: r.y, w: r.w, h: r.h, accent: r.accent, lane: LANE[id], door: { x: dx, y: dy },
    corridor: { x: dx, y: LOWER_ROW.has(id) ? LOWER_Y : HALL_Y } };
});
export const ROOM: Record<string, Room> = Object.fromEntries(ROOMS.map(r => [r.id, r]));
export const ROOM_ACCENT: Record<string, string> = Object.fromEntries(ROOMS.map(r => [r.id, r.accent]));

type Station = { x: number; y: number; console: number[] | null };
const STATIONS = SHIP.stations as Record<string, Station>;
/** Each robot's own place on the ship (feet position). Every role keeps its station and its identity. */
export const STATION: Record<string, Pt> = Object.fromEntries(CAST.map(c => [c.id,
  { x: STATIONS[c.id].x, y: STATIONS[c.id].y }]));
/** The console beside each station. COMMAND uses the bridge desk and DOCK the launch hatch instead. */
export const CONSOLE: Record<string, Pt | null> = Object.fromEntries(CAST.map(c => {
  const at = STATIONS[c.id].console;
  return [c.id, at ? { x: at[0], y: at[1] } : null];
}));
/** Managers oversee their teams from the room's walkway, behind the desks. */
export const SUPERVISE: Record<string, Pt> = Object.fromEntries(CAST.filter(c => c.rank === "manager").map(c => {
  const r = ROOM[c.room], mates = CAST.filter(m => m.room === c.room && m.id !== c.id).map(m => STATION[m.id].x);
  const middle = mates.length ? mates.reduce((a, b) => a + b, 0) / mates.length : r.x + r.w / 2;
  return [c.id, { x: Math.round(middle + (STATION[c.id].x > middle ? 22 : -22)), y: r.lane }];
}));
/** Bottom centre of CORE, the holographic brain hovering in its chamber. */
export const CORE_AT: Pt = { x: SHIP.core.x, y: SHIP.core.y + 42 };
export const ENGINES: Pt[] = SHIP.engines.map(([x, y]) => ({ x, y }));
export const HATCH: Pt = { x: SHIP.hatch.x, y: SHIP.hatch.y };

export type BreakActivity = "arcade" | "boardgame" | "snack" | "drink" | "read" | "rest";
export interface BreakSpot { id: string; at: Pt; activity: BreakActivity; posture: "stand" | "rest"; dir: Dir }
const SEATED = new Set<BreakActivity>(["boardgame", "read", "rest"]);
/** The first 25 spots are stable homes in CAST order; the rest make room for visits. */
export const BREAK_SPOTS: BreakSpot[] = (SHIP.lounge as { x: number; y: number; activity: BreakActivity }[])
  .map((s, i) => ({ id: `${s.activity}-${i + 1}`, at: { x: s.x, y: s.y }, activity: s.activity,
    posture: SEATED.has(s.activity) ? "rest" : "stand", dir: "down" }));
export const REST_SEAT: Record<string, Pt> = Object.fromEntries(CAST.map((c, i) => [c.id, BREAK_SPOTS[i].at]));
export const LOUNGE: Pt[] = CAST.map(c => REST_SEAT[c.id]);

export function roomOf(p: Pt): Room | undefined {
  return ROOMS.find(r => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h);
}
/** Visitors meet a manager beside its desk, on the room's walkway. */
export function besideManager(manager: string): Pt {
  const p = STATION[manager], r = roomOf(p)!;
  return { x: Math.round(p.x + (p.x - r.x > r.w / 2 ? -40 : 40)), y: r.lane };
}
/** Where a handoff happens: the receiver waits on its walkway, the sender offers the work from beside it. */
export function handoffSpots(to: string): { meet: Pt; offer: Pt } {
  const station = STATION[to], r = roomOf(station)!;
  const side = station.x - r.x > r.w / 2 ? -1 : 1;
  return { meet: { x: station.x, y: r.lane }, offer: { x: Math.round(station.x + side * 44), y: r.lane } };
}

// ---- The walking graph: halls, links between them, doorways, room walkways and the lounge walkways ----
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
const uniq = (xs: number[]) => [...new Set(xs.map(Math.round))].sort((a, b) => a - b);
function horizontal(y: number, xs: number[]) {
  const all = uniq(xs);
  for (let i = 1; i < all.length; i++) link({ x: all[i - 1], y }, { x: all[i], y });
}
function vertical(x: number, ys: number[]) {
  const all = uniq(ys);
  for (let i = 1; i < all.length; i++) link({ x, y: all[i - 1] }, { x, y: all[i] });
}
const LINKS = SHIP.halls.links;
horizontal(HALL_Y, [SHIP.halls.main.x0, SHIP.halls.main.x1, ...LINKS,
  ...ROOMS.filter(r => !LOWER_ROW.has(r.id)).map(r => r.corridor.x)]);
horizontal(LOWER_Y, [SHIP.halls.lower.x0, SHIP.halls.lower.x1, ...LINKS,
  ...ROOMS.filter(r => LOWER_ROW.has(r.id)).map(r => r.corridor.x)]);
for (const x of LINKS) vertical(x, [HALL_Y, LOWER_Y]);
for (const r of ROOMS) {
  if (r.id === "lounge") continue;
  const mine = CAST.filter(c => c.room === r.id);
  const xs = [r.door.x, ...mine.map(c => STATION[c.id].x), ...mine.map(c => handoffSpots(c.id).offer.x),
    ...mine.filter(c => SUPERVISE[c.id]).flatMap(c => [SUPERVISE[c.id].x, besideManager(c.id).x])];
  horizontal(r.lane, xs);
  vertical(r.door.x, [r.corridor.y, r.door.y, r.lane]);
  for (const c of mine) vertical(STATION[c.id].x, [r.lane, STATION[c.id].y]);
}
// The lounge: three walkways (in front of the machines, past the sofa and tables, along the front) and three
// aisles between the furniture. Every break spot steps straight onto its walkway.
const LOUNGE_WALKS = [210, 254, 298], LOUNGE_AISLES = [430, 594, 725];
const walkOf = (y: number) => y < 230 ? LOUNGE_WALKS[0] : y < 276 ? LOUNGE_WALKS[1] : LOUNGE_WALKS[2];
for (const walk of LOUNGE_WALKS) horizontal(walk, [...LOUNGE_AISLES, ...(walk === LOUNGE_WALKS[2]
  ? [ROOM.lounge.door.x] : []), ...BREAK_SPOTS.filter(s => walkOf(s.at.y) === walk).map(s => s.at.x)]);
for (const x of LOUNGE_AISLES) vertical(x, LOUNGE_WALKS);
vertical(ROOM.lounge.door.x, [LOUNGE_WALKS[2], ROOM.lounge.door.y, ROOM.lounge.corridor.y]);
for (const s of BREAK_SPOTS) if (walkOf(s.at.y) !== s.at.y) vertical(s.at.x, [walkOf(s.at.y), s.at.y]);

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

/** A walking route along the halls and walkways: every leg goes straight across or straight up and down. */
export function route(from: Pt, to: Pt): Pt[] {
  return dedupe([from, ...shortest(nearestNode(from), nearestNode(to)), to]);
}
/** The lounge is part of the one walking graph; kept for callers that walk inside it. */
export const loungeRoute = route;
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
