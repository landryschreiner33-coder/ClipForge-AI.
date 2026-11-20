/** The crew's pixel art: one atlas (public/space/crew.png) drawn from the three crew sheets, plus how each pose
 * maps to its frames. Shared by the ship, the portraits and the team page so every view shows the same robots.
 * design/space-studio/ holds the tools that built the art. */
import SPRITES from "../space/sprites.json";

export type Pose = "idle" | "work" | "walk" | "carry" | "review" | "approved" | "rework" | "error" | "retry" | "wait"
  | "paused" | "unavailable";
export type RobotPosture = "stand" | "desk" | "rest";
export type FrameName = "idle" | "blink" | "look_left" | "look_right" | "walk_left_a" | "walk_left_b" | "walk_right_a"
  | "walk_right_b" | "work_0" | "work_1" | "work_2" | "work_3";
export interface RobotArt {
  row: number; w: number; h: number; foot: number; cx: number;
  /** per work frame: light points [x, y, radius, colour] in sprite pixels, drawn as a soft glow */
  glows: [number, number, number, string][][];
}
export const CELL = { w: SPRITES.crew.cell[0], h: SPRITES.crew.cell[1] };
export const FRAME_NAMES = SPRITES.crew.frames as FrameName[];
export const ART = SPRITES.crew.robots as unknown as Record<string, RobotArt>;
export const CORE_ART = SPRITES.core;
export const CONSOLE_ART = { cell: SPRITES.consoles.cell, frames: SPRITES.consoles.frames, rows: SPRITES.consoles.rows };
export const EXHAUST_ART = { cell: SPRITES.exhaust.cell, count: SPRITES.exhaust.count };
export const frameIndex = (name: FrameName) => FRAME_NAMES.indexOf(name);

/** Frames and timing per pose, for the gallery's pose list. Work gestures run at 8 frames a second. */
export const FRAMES: Record<Pose, { n: number; ms: number }> = {
  idle: { n: 4, ms: 900 }, work: { n: 4, ms: 125 }, walk: { n: 2, ms: 170 }, carry: { n: 2, ms: 170 },
  review: { n: 2, ms: 700 }, approved: { n: 1, ms: 0 }, rework: { n: 2, ms: 500 }, error: { n: 2, ms: 600 },
  retry: { n: 4, ms: 250 }, wait: { n: 2, ms: 900 }, paused: { n: 1, ms: 0 }, unavailable: { n: 1, ms: 0 },
};
const POSE_FRAMES: Record<Pose, FrameName[]> = {
  idle: ["idle", "idle", "blink", "idle"], work: ["work_0", "work_1", "work_2", "work_3"],
  walk: ["walk_right_a", "walk_right_b"], carry: ["walk_right_a", "walk_right_b"],
  review: ["look_left", "look_right"], approved: ["work_3"], rework: ["look_left", "idle"],
  error: ["idle", "blink"], retry: ["work_0", "work_1", "work_2", "work_3"], wait: ["look_left", "look_right"],
  paused: ["idle"], unavailable: ["idle"],
};
/** The frame a pose shows at time t (ms). Still views always get the pose's first frame. */
export function poseFrame(pose: Pose, t: number, still: boolean, seed = 0): FrameName {
  const list = POSE_FRAMES[pose] || POSE_FRAMES.idle;
  if (still || list.length < 2) return list[0];
  return list[Math.floor((t + seed) / (FRAMES[pose]?.ms || 500)) % list.length];
}

const images = new Map<string, Promise<HTMLImageElement>>();
/** Loads a picture from public/space once and shares it. */
export function spaceImage(name: string): Promise<HTMLImageElement> {
  let p = images.get(name);
  if (!p) {
    p = new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => { images.delete(name); reject(new Error(`Could not load ${name}`)); };
      img.src = `/space/${name}`;
    });
    images.set(name, p);
  }
  return p;
}

/** Draws one robot frame with its feet at (x, y). */
export function drawRobot(ctx: CanvasRenderingContext2D, atlas: CanvasImageSource, id: string, frame: FrameName,
  x: number, y: number, alpha = 1) {
  const art = ART[id];
  if (!art) return;
  const col = frameIndex(frame);
  const sx = col * CELL.w, sy = art.row * CELL.h;
  const dx = Math.round(x - art.cx), dy = Math.round(y - art.foot);
  if (alpha < 1) ctx.globalAlpha = alpha;
  ctx.drawImage(atlas, sx, sy, art.w, art.h, dx, dy, art.w, art.h);
  if (alpha < 1) ctx.globalAlpha = 1;
}
