/**
 * Canvas helpers for the office: the room accents, and the robot sprites drawn as cached canvases (the canvas
 * fallback, portraits and the Team view use them). The floor plan itself is drawn by StudioScene.ts (and its plain
 * fallback LivingFallback.ts); there is one layout, in world.ts.
 */
import { BY_ID, Dir, RoomId } from "./cast";
import { Pose, Rect, sprite, CELL } from "./sprites";

type Ctx = CanvasRenderingContext2D;
export const ROOM_ACCENT: Record<RoomId, string> = {
  lounge: "#ff8f6b", control: "#ffc94a", brain: "#c4a8ff", intake: "#a6e94b", research: "#ffab45",
  story: "#4f7dff", editing: "#ff3dad", quality: "#ffc23d", sound: "#9a6bff", publishing: "#57eea0",
};

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
