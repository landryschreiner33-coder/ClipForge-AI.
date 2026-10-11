/**
 * One lazy offscreen renderer for the entire roster. Cards receive ordinary cached Canvas2D images,
 * so opening Team or the developer gallery never creates a WebGL context for each portrait.
 */
import type { Application } from "pixi.js";
import { BY_ID } from "./cast";
import type { Dir } from "./cast";
import type { Pose } from "./sprites";
import type { StudioRobot } from "./StudioArt";

export const PORTRAIT_SIZE = { w: 48, h: 68 };
const LIMIT = 512;
const frames = new Map<string, HTMLCanvasElement>();
interface Painter {
  app: Application;
  canvas: HTMLCanvasElement;
  robots: Map<string, StudioRobot>;
  previous: StudioRobot | null;
}
let painter: Promise<Painter | null> | null = null;

function sharedPainter(): Promise<Painter | null> {
  if (painter) return painter;
  painter = (async () => {
    const [{ Application }, { createRobot }] = await Promise.all([import("pixi.js"), import("./StudioArt")]);
    const app = new Application();
    const canvas = document.createElement("canvas");
    try {
      await app.init({ canvas, width: PORTRAIT_SIZE.w, height: PORTRAIT_SIZE.h, resolution: 1,
        antialias: false, backgroundAlpha: 0, autoStart: false, preference: "webgl",
        preserveDrawingBuffer: true, powerPreference: "low-power" });
      const robots = new Map<string, StudioRobot>();
      for (const c of Object.values(BY_ID)) {
        const robot = createRobot(c);
        robot.container.position.set(24, 64);
        robot.container.visible = false;
        robots.set(c.id, robot);
        app.stage.addChild(robot.container);
      }
      return { app, canvas, robots, previous: null };
    } catch {
      try { app.destroy(false, { children: true }); } catch { /* Incomplete context initialization. */ }
      return null;
    }
  })().catch(() => null);
  return painter;
}

/** Render only the requested authored frame; repeated requests share a bounded image cache. */
export async function studioPortrait(id: string, pose: Pose, dir: Dir, timeMs: number,
  reduce: boolean): Promise<HTMLCanvasElement | null> {
  const c = BY_ID[id];
  if (!c) return null;
  const still = reduce || pose === "paused" || pose === "unavailable";
  const offset = Array.from(id).reduce((sum, letter) => sum + letter.charCodeAt(0), 0) * 29;
  const t = Math.max(0, timeMs + offset);
  let frame = 0, sample = 0;
  if (!still) {
    if (pose === "walk" || pose === "carry") {
      frame = Math.floor(t / 110) % 8;
      sample = frame * 110;
    } else if (pose === "work" || pose === "review" || pose === "retry") {
      const ms = Math.max(120, c.workMs || 350);
      frame = Math.floor(t / ms) % 4;
      sample = frame * ms;
    } else if (pose === "error") {
      frame = Math.floor(t / 650) % 2;
      sample = frame * 650;
    } else {
      frame = t % 5300 > 5140 ? 1 : 0;
      sample = frame ? 5200 : 0;
    }
  }
  const key = `${id}|${pose}|${dir}|${still ? "still" : frame}`;
  const cached = frames.get(key);
  if (cached) {
    // LRU: changing gallery poses cannot retain an unbounded number of canvases.
    frames.delete(key);
    frames.set(key, cached);
    return cached;
  }
  const shared = await sharedPainter();
  if (!shared) return null;
  // Another caller may have rendered this frame while renderer initialization was pending.
  const ready = frames.get(key);
  if (ready) return ready;
  const art = shared.robots.get(id);
  if (!art) return null;
  const image = document.createElement("canvas");
  image.width = PORTRAIT_SIZE.w;
  image.height = PORTRAIT_SIZE.h;
  const ctx = image.getContext("2d");
  if (!ctx) return null;
  if (shared.previous) shared.previous.container.visible = false;
  art.container.visible = true;
  shared.previous = art;
  art.animate(pose, sample - offset, still, dir);
  shared.app.renderer.render(shared.app.stage);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(shared.canvas, 0, 0);
  frames.set(key, image);
  if (frames.size > LIMIT) frames.delete(frames.keys().next().value!);
  return image;
}
