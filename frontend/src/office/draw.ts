/**
 * Canvas drawing for the office: the static floor plan (rooms, corridors, furniture) is drawn once into an offscreen
 * canvas; screens, lamps and the robots are drawn each frame on top. Everything is whole world pixels; the page scales
 * the canvas with nearest-neighbor sampling, so the pixel art stays crisp.
 *
 * In-world screens show only real state: lit while their room has running work, dark otherwise. No sample numbers,
 * graphs or thumbnails are painted on them.
 */
import { BY_ID, Dir, RoomId } from "./cast";
import { Pose, Rect, sprite, CELL } from "./sprites";
import { CORE_AT, ENTRANCE, ROOM, ROOMS, WORLD } from "./world";

const INK = "#0b1020";
export const ROOM_ACCENT: Record<RoomId, string> = {
  lounge: "#ff8f6b", boss: "#ffc94a", brain: "#c4a8ff", discover: "#a6e94b", workspace: "#28d9ff",
  analyze: "#4f7dff", studio: "#ff3dad", system: "#ffc23d", caption: "#9a6bff", schedule: "#ffab45",
  dock: "#57eea0",
};
const FLOOR: Record<RoomId, [string, string]> = {
  lounge: ["#3a2f3a", "#40343f"], boss: ["#33304a", "#38344f"], brain: ["#2c2a4a", "#312e51"],
  discover: ["#2b3a37", "#2f3f3b"], workspace: ["#2a3a4c", "#2e3f52"], analyze: ["#28344f", "#2c3855"],
  studio: ["#3a2a40", "#3f2e46"], system: ["#33352f", "#383a33"], caption: ["#30294a", "#352d50"],
  schedule: ["#3d3127", "#43362b"], dock: ["#283b33", "#2c4038"],
};
const CORRIDOR = ["#2a3550", "#2e3a57"];
const WALL = "#151c2e";
const WOOD = ["#c9a27a", "#a87f57", "#7d5b3b"];

type Ctx = CanvasRenderingContext2D;
const box = (c: Ctx, x: number, y: number, w: number, h: number, fill: string, line = INK) => {
  c.fillStyle = line;
  c.fillRect(x, y, w, h);
  c.fillStyle = fill;
  c.fillRect(x + 1, y + 1, w - 2, h - 2);
};
const px = (c: Ctx, x: number, y: number, w: number, h: number, fill: string) => {
  c.fillStyle = fill;
  c.fillRect(x, y, w, h);
};

// ------------------------------------------------------------------ furniture
function desk(c: Ctx, x: number, y: number, w: number) {
  box(c, x, y, w, 10, WOOD[0]);
  px(c, x + 1, y + 8, w - 2, 1, WOOD[1]);
  box(c, x + 1, y + 9, w - 2, 7, WOOD[1]);
  px(c, x + 3, y + 16, 2, 3, WOOD[2]);
  px(c, x + w - 5, y + 16, 2, 3, WOOD[2]);
}
function plant(c: Ctx, x: number, y: number) {
  box(c, x, y + 8, 8, 7, "#9c6a3e");
  px(c, x + 1, y + 9, 6, 1, "#b8824f");
  for (const [dx, dy, w, h] of [[1, 2, 6, 6], [-1, 4, 4, 4], [5, 3, 4, 4], [2, 0, 4, 4]])
    box(c, x + dx, y + dy, w, h, "#3fa34d", "#1f5a2b");
  px(c, x + 3, y + 3, 1, 1, "#7fd88a");
}
function shelf(c: Ctx, x: number, y: number, w = 22, h = 30) {
  box(c, x, y, w, h, "#5a4330");
  const books = ["#ff7a6b", "#4f7dff", "#ffc94a", "#57eea0", "#9a6bff", "#d9c58f"];
  for (let row = 0; row < 3; row++) {
    const yy = y + 2 + row * 9;
    px(c, x + 1, yy + 7, w - 2, 1, "#3a2b1f");
    for (let k = 0; k < Math.floor((w - 4) / 3); k++) px(c, x + 2 + k * 3, yy + 1 + ((k + row) % 2), 2, 6 - ((k + row) % 2), books[(k + row * 2) % books.length]);
  }
}
function lamp(c: Ctx, x: number, y: number) {
  px(c, x + 2, y + 4, 1, 14, "#3a3f4b");
  box(c, x, y, 6, 5, "#ffe9b0");
  px(c, x - 1, y + 18, 8, 2, "#3a3f4b");
}
function rug(c: Ctx, x: number, y: number, w: number, h: number, fill: string, edge: string) {
  px(c, x, y, w, h, edge);
  px(c, x + 2, y + 2, w - 4, h - 4, fill);
}
function chair(c: Ctx, x: number, y: number, fill = "#2b3247") {
  box(c, x, y, 10, 8, fill);
  px(c, x + 2, y + 8, 2, 3, INK);
  px(c, x + 6, y + 8, 2, 3, INK);
}
function crate(c: Ctx, x: number, y: number, s = 12) {
  box(c, x, y, s, s, "#c08a52");
  px(c, x + 1, y + Math.floor(s / 2), s - 2, 1, "#7d5530");
  px(c, x + Math.floor(s / 2), y + 1, 1, s - 2, "#7d5530");
}
function rack(c: Ctx, x: number, y: number) {
  box(c, x, y, 18, 34, "#2b3040");
  for (let k = 0; k < 5; k++) px(c, x + 2, y + 3 + k * 6, 14, 4, "#1c2130");
}

/** Monitors and screens: positions are kept so their light can follow real state each frame. */
export interface Screen { room: RoomId; x: number; y: number; w: number; h: number }
export const SCREENS: Screen[] = [];
function screen(c: Ctx, room: RoomId, x: number, y: number, w: number, h: number) {
  box(c, x, y, w, h, "#2b3247");
  px(c, x + 2, y + 2, w - 4, h - 4, "#0f1626");
  SCREENS.push({ room, x: x + 2, y: y + 2, w: w - 4, h: h - 4 });
}
function monitorOnDesk(c: Ctx, room: RoomId, x: number, y: number) {
  screen(c, room, x, y, 16, 11);
  px(c, x + 7, y + 11, 2, 3, "#2b3247");
}

// ------------------------------------------------------------------ the floor plan
let backdrop: HTMLCanvasElement | null = null;

export function drawBackdrop(): HTMLCanvasElement {
  if (backdrop) return backdrop;
  const cv = document.createElement("canvas");
  cv.width = WORLD.w;
  cv.height = WORLD.h;
  const c = cv.getContext("2d")!;
  SCREENS.length = 0;
  px(c, 0, 0, WORLD.w, WORLD.h, "#0b1020");
  // corridors: everything between the rooms, in quiet slate tiles
  px(c, 4, 4, WORLD.w - 8, WORLD.h - 8, CORRIDOR[0]);
  for (let y = 4; y < WORLD.h - 4; y += 12)
    for (let x = 4 + ((y / 12) % 2) * 12; x < WORLD.w - 4; x += 24) px(c, x, y, 12, 12, CORRIDOR[1]);
  // entrance: a door and a mat at the bottom of the center hall
  const e = ENTRANCE;
  px(c, e.x + e.w / 2 - 26, e.y + e.h - 6, 52, 6, WALL);
  box(c, e.x + e.w / 2 - 22, e.y + e.h - 30, 44, 26, "#3b6f9e");
  px(c, e.x + e.w / 2 - 1, e.y + e.h - 29, 2, 24, INK);
  px(c, e.x + e.w / 2 - 18, e.y + e.h - 26, 6, 18, "#9fd2ff");
  px(c, e.x + e.w / 2 + 4, e.y + e.h - 26, 6, 18, "#9fd2ff");
  rug(c, e.x + e.w / 2 - 20, e.y + e.h - 46, 40, 14, "#b0284f", "#7a1a37");
  plant(c, e.x + 14, e.y + 50);
  plant(c, e.x + e.w - 24, e.y + 50);

  for (const r of ROOMS) {
    const [f0, f1] = FLOOR[r.id];
    px(c, r.x, r.y, r.w, r.h, WALL);
    px(c, r.x + 3, r.y + 3, r.w - 6, r.h - 6, f0);
    for (let y = r.y + 16; y < r.y + r.h - 3; y += 8)
      for (let x = r.x + 3 + (((y - r.y) / 8) % 2) * 8; x < r.x + r.w - 3; x += 16) px(c, x, y, 8, 8, f1);
    // back wall with the department's trim
    px(c, r.x + 3, r.y + 3, r.w - 6, 13, "#1d2640");
    px(c, r.x + 3, r.y + 15, r.w - 6, 1, ROOM_ACCENT[r.id]);
    // the door gap
    if (r.door.y === r.y + r.h) px(c, r.door.x - 12, r.y + r.h - 3, 24, 3, f0);
    else px(c, r.door.x === r.x ? r.x : r.x + r.w - 3, r.door.y - 12, 3, 24, f0);
    furnish(c, r.id, r.x, r.y, r.w);
  }
  backdrop = cv;
  return cv;
}

function furnish(c: Ctx, id: RoomId, x: number, y: number, w: number) {
  // rooms are 100 px tall: back wall to y+16, desks around y+36..52, robots stand in front, the lane at y+80
  switch (id) {
    case "lounge":
      rug(c, x + 30, y + 44, 150, 38, "#2f6f6a", "#245a56");
      box(c, x + 58, y + 20, 70, 13, "#b23a48");  // sofa
      box(c, x + 54, y + 24, 8, 14, "#9a2f3d");
      box(c, x + 124, y + 24, 8, 14, "#9a2f3d");
      box(c, x + 80, y + 50, 34, 10, WOOD[0]);  // coffee table
      lamp(c, x + 18, y + 18);
      shelf(c, x + w - 30, y + 18, 22, 28);
      plant(c, x + 8, y + 78);
      break;
    case "boss":
      screen(c, "boss", x + 48, y + 18, 96, 22);  // the big wall screen
      desk(c, x + 56, y + 46, 80);
      monitorOnDesk(c, "boss", x + 64, y + 34);
      monitorOnDesk(c, "boss", x + 112, y + 34);
      shelf(c, x + 8, y + 18);
      shelf(c, x + w - 30, y + 18);
      plant(c, x + 12, y + 76);
      plant(c, x + w - 20, y + 76);
      break;
    case "brain":
      shelf(c, x + 8, y + 18, 18, 30);
      screen(c, "brain", x + 160, y + 18, 30, 16);
      desk(c, x + 26, y + 36, 70);
      monitorOnDesk(c, "brain", x + 36, y + 24);
      plant(c, x + w - 18, y + 76);
      // the CORE pedestal (its glow is drawn each frame)
      box(c, CORE_AT.x - 18, CORE_AT.y + 4, 36, 10, "#2b3247");
      px(c, CORE_AT.x - 16, CORE_AT.y + 6, 32, 2, "#3d4560");
      break;
    case "discover":
      screen(c, "discover", x + 72, y + 18, 70, 16);
      desk(c, x + 92, y + 36, 110);
      monitorOnDesk(c, "discover", x + 110, y + 24);
      monitorOnDesk(c, "discover", x + 170, y + 24);
      shelf(c, x + 8, y + 18);
      plant(c, x + w - 18, y + 76);
      break;
    case "analyze":
      screen(c, "analyze", x + 30, y + 18, 60, 16);
      screen(c, "analyze", x + 100, y + 18, 40, 16);
      desk(c, x + 20, y + 36, 140);
      monitorOnDesk(c, "analyze", x + 40, y + 24);
      monitorOnDesk(c, "analyze", x + 88, y + 24);
      monitorOnDesk(c, "analyze", x + 132, y + 24);
      shelf(c, x + w - 30, y + 18);
      plant(c, x + 8, y + 76);
      break;
    case "studio":
      screen(c, "studio", x + 90, y + 18, 60, 16);
      desk(c, x + 80, y + 36, 136);
      monitorOnDesk(c, "studio", x + 96, y + 24);
      monitorOnDesk(c, "studio", x + 140, y + 24);
      monitorOnDesk(c, "studio", x + 186, y + 24);
      shelf(c, x + 8, y + 18);
      // a film reel on the wall
      box(c, x + 40, y + 18, 18, 18, "#3a3f4b");
      for (const [dx, dy] of [[4, 4], [10, 4], [4, 10], [10, 10]]) px(c, x + 40 + dx, y + 18 + dy, 4, 4, "#1c2130");
      plant(c, x + 8, y + 76);
      break;
    case "caption":
      screen(c, "caption", x + 40, y + 18, 50, 16);
      desk(c, x + 30, y + 36, 120);
      monitorOnDesk(c, "caption", x + 50, y + 24);
      monitorOnDesk(c, "caption", x + 110, y + 24);
      shelf(c, x + w - 30, y + 18);
      plant(c, x + 8, y + 76);
      break;
    case "workspace":
      rug(c, x + 24, y + 40, w - 48, 44, "#2b4a63", "#24405a");
      box(c, x + 50, y + 54, w - 100, 14, WOOD[0]);
      px(c, x + 51, y + 66, w - 102, 2, WOOD[1]);
      for (const dx of [58, 92, 126]) chair(c, x + dx, y + 43);
      for (const dx of [58, 92, 126]) chair(c, x + dx, y + 71);
      box(c, x + 70, y + 18, 52, 20, "#c9a27a");  // the handoff board
      px(c, x + 72, y + 20, 48, 16, "#d9c58f");
      plant(c, x + 10, y + 18);
      plant(c, x + w - 18, y + 18);
      break;
    case "system":
      rack(c, x + 10, y + 18);
      rack(c, x + 30, y + 18);
      screen(c, "system", x + 120, y + 18, 34, 18);  // the Dev Log terminal
      desk(c, x + 110, y + 38, 60);
      monitorOnDesk(c, "system", x + 70, y + 26);
      desk(c, x + 60, y + 38, 40);
      plant(c, x + w - 18, y + 76);
      break;
    case "schedule":
      box(c, x + 60, y + 18, 70, 20, "#e9e2cf");  // the calendar board
      for (let k = 0; k < 7; k++) for (let r = 0; r < 2; r++) px(c, x + 63 + k * 9, y + 21 + r * 8, 7, 6, "#d4ccb6");
      desk(c, x + 60, y + 42, 80);
      monitorOnDesk(c, "schedule", x + 104, y + 30);
      shelf(c, x + 8, y + 18);
      plant(c, x + w - 18, y + 76);
      break;
    case "dock":
      for (const [dx, dy] of [[150, 22], [164, 22], [157, 10], [180, 26]]) crate(c, x + dx, y + dy);
      px(c, x + 20, y + 46, w - 40, 6, "#3a3f4b");  // the loading conveyor
      for (let k = 0; k < (w - 40) / 6; k++) px(c, x + 20 + k * 6, y + 47, 3, 1, "#ffc94a");
      screen(c, "dock", x + 30, y + 18, 40, 16);
      monitorOnDesk(c, "dock", x + 90, y + 24);
      plant(c, x + 8, y + 76);
      break;
  }
}

// ------------------------------------------------------------------ live layers
/** Screens light up only while their room has running work. */
export function drawScreens(c: Ctx, active: Set<RoomId>, t: number, still: boolean) {
  for (const s of SCREENS) {
    const on = active.has(s.room);
    if (!on) continue;
    const accent = ROOM_ACCENT[s.room];
    c.globalAlpha = 0.25;
    px(c, s.x, s.y, s.w, s.h, accent);
    c.globalAlpha = 1;
    // a calm scan line shows the screen is live; it carries no data
    const yy = still ? s.y + Math.floor(s.h / 2) : s.y + (Math.floor(t / 180) % s.h);
    c.globalAlpha = 0.6;
    px(c, s.x, yy, s.w, 1, accent);
    c.globalAlpha = 1;
  }
}

/** The wall clock in Schedule shows this PC's real time. */
export function drawClock(c: Ctx, now: Date) {
  const r = ROOM.schedule;
  const cx = r.x + 160, cy = r.y + 28, R = 9;
  c.fillStyle = INK;
  c.beginPath();
  c.arc(cx, cy, R + 1, 0, Math.PI * 2);
  c.fill();
  c.fillStyle = "#f3eedf";
  c.beginPath();
  c.arc(cx, cy, R, 0, Math.PI * 2);
  c.fill();
  const hand = (frac: number, len: number, color: string) => {
    const a = frac * Math.PI * 2 - Math.PI / 2;
    const steps = Math.round(len);
    for (let k = 0; k <= steps; k++) px(c, Math.round(cx + Math.cos(a) * k), Math.round(cy + Math.sin(a) * k), 1, 1, color);
  };
  hand(((now.getHours() % 12) + now.getMinutes() / 60) / 12, 4, INK);
  hand(now.getMinutes() / 60, 7, "#b8651a");
}

/** CORE: steady while idle; brighter while the Brain evaluates or answers a lookup. */
export function drawCore(c: Ctx, level: number, t: number, still: boolean) {
  const { x, y } = CORE_AT;
  box(c, x - 12, y - 30, 24, 36, "#1c2440");
  c.globalAlpha = 0.35 + 0.4 * level + (still ? 0 : 0.08 * Math.sin(t / 400) * level);
  px(c, x - 10, y - 28, 20, 32, "#9a6bff");  // glass tube
  c.globalAlpha = 1;
  // the brain shape
  const P = level > 0.5 ? "#ffd1f3" : "#e0b8ff";
  for (const [dx, dy, w, h] of [[-6, -20, 12, 10], [-7, -16, 14, 8], [-5, -10, 10, 3]]) px(c, x + dx, y + dy, w, h, P);
  px(c, x - 1, y - 20, 1, 13, "#9a6bff");
  px(c, x - 12, y - 31, 24, 2, "#3d4560");
  px(c, x - 12, y + 5, 24, 2, "#3d4560");
}

/** Server rack lights follow the health readings (green healthy, amber degraded, red error, grey unknown). */
export function drawRackLights(c: Ctx, colors: string[]) {
  const r = ROOM.system;
  colors.slice(0, 10).forEach((col, k) => {
    const rx = r.x + 10 + (k >= 5 ? 20 : 0);
    const ry = r.y + 18 + 4 + (k % 5) * 6;
    px(c, rx + 3, ry, 2, 2, col);
    px(c, rx + 7, ry, 6, 1, "#3d4560");
  });
}

export function highlightRoom(c: Ctx, id: RoomId, strength: number) {
  const r = ROOM[id];
  c.globalAlpha = 0.5 * strength;
  c.strokeStyle = ROOM_ACCENT[id];
  c.lineWidth = 2;
  c.strokeRect(r.x + 2, r.y + 2, r.w - 4, r.h - 4);
  c.globalAlpha = 1;
}

// ------------------------------------------------------------------ robots
const frames = new Map<string, HTMLCanvasElement>();

/** One sprite frame as a small canvas (cached), drawn from the same rectangles as the gallery. */
export function spriteCanvas(role: string, dir: Dir, pose: Pose, frame: number): HTMLCanvasElement {
  const k = `${role}|${dir}|${pose}|${frame}`;
  let cv = frames.get(k);
  if (cv) return cv;
  cv = document.createElement("canvas");
  cv.width = CELL.w;
  cv.height = CELL.h;
  paint(cv.getContext("2d")!, sprite(role, dir, pose, frame));
  frames.set(k, cv);
  return cv;
}

export function paint(c: Ctx, rects: Rect[], ox = 0, oy = 0) {
  for (const [x, y, w, h, fill, a] of rects) {
    c.globalAlpha = a ?? 1;
    c.fillStyle = fill;
    c.fillRect(ox + x, oy + y, w, h);
  }
  c.globalAlpha = 1;
}

export function drawRobot(c: Ctx, role: string, x: number, y: number, dir: Dir, pose: Pose, frame: number,
  selected: boolean) {
  if (!BY_ID[role]) return;
  const ox = Math.round(x - 24), oy = Math.round(y - 61);
  if (selected) {
    c.globalAlpha = 0.55;
    c.fillStyle = "#28d9ff";
    c.fillRect(Math.round(x) - 13, Math.round(y) - 1, 26, 3);
    c.globalAlpha = 1;
  }
  c.drawImage(spriteCanvas(role, dir, pose, frame), ox, oy);
}
