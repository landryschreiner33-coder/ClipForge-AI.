/** The living ship, drawn with Canvas 2D from the pixel art in public/space (design/space-studio holds the tools that
 * made it). Real office states light the rooms, wake the consoles and move the crew; the engines, CORE's idle rings,
 * idle fidgets and lounge life are decoration. Everything holds one still picture when motion is reduced, the page is
 * hidden, or the feed is paused or lost (AGENTS.md rule 14): the caller passes `still` and draws less often. */
import { BY_ID, Dir, RoomId } from "./cast";
import { RoleState, Snapshot } from "./api";
import { BreakActivity, CONSOLE, HATCH, Pt, ROOM, ROOMS, STATION, VIEW, WORLD } from "./world";
import { ART, CELL, CONSOLE_ART, EXHAUST_ART, FrameName, frameIndex, Pose, spaceImage } from "./crew";
import type { OfficeDuty } from "./DepartmentDuty";
import { ZapPose, ZapReaction, zapParticles, zapPose } from "./taser";
import SHIP from "../space/ship-world.json";

export interface SceneActor {
  id: string; x: number; y: number; pose: Pose; dir: Dir; selected: boolean;
  posture?: "stand" | "desk" | "rest";
  breakActivity?: BreakActivity | null;
  breakPhase?: number;
  supervising?: boolean;
  duty?: OfficeDuty;
  /** a Taser zap playing on this robot (TaserItem.tsx): which reaction and how far into it */
  zap?: { kind: ZapReaction; ms: number; seed: number };
}
export interface SceneHandoff { id: number; from: Pt; to: Pt; progress: number }
/** Short-lived cues the page saw happen: DOCK's beacon when a clip arrives for review. */
export interface SceneCues { dockUntil?: number }
export type CoreMode = "offline" | "paused" | "active" | "standby";

const OX = -VIEW.x, OY = -VIEW.y;
/** Characters step at ten frames a second, like hand-drawn pixel animation. */
const STEP = 100;
const BUSY: RoleState[] = ["working", "retrying", "reviewing"];
const ENGINE_MS = [96, 121, 147];
const CORE_TOP = 47, CORE_SPLIT = 44;

function hash(text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}
function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
  return c;
}
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("The ship pictures took too long to load")), ms);
    promise.then(v => { clearTimeout(timer); resolve(v); }, e => { clearTimeout(timer); reject(e); });
  });
}
type Art = { ship: HTMLImageElement; lights: HTMLImageElement; crew: HTMLImageElement; consoles: HTMLImageElement;
  exhaust: HTMLImageElement; core: HTMLImageElement };

export class StudioScene {
  private ctx: CanvasRenderingContext2D;
  private base: HTMLCanvasElement;
  private bloom: HTMLCanvasElement;
  private glows = new Map<string, HTMLCanvasElement>();
  private side = new Map<string, "left" | "right">();
  private destroyed = false;
  private brainBusy = false;
  private lastActualBrainBusy: boolean | undefined;
  private brainSuppressed = false;
  /** a scratch canvas for a zapped robot's flash, soot, X-ray or golden glow */
  private tint: HTMLCanvasElement | null = null;

  private constructor(cv: HTMLCanvasElement, private art: Art) {
    const ctx = cv.getContext("2d");
    if (!ctx) throw new Error("Canvas drawing is unavailable");
    this.ctx = ctx;
    cv.width = VIEW.w; cv.height = VIEW.h;
    // The hull, rooms and furniture never change: draw them once.
    this.base = canvas(VIEW.w, VIEW.h);
    this.bloom = canvas(VIEW.w, VIEW.h);
    this.paintBase();
    // Where the browser paints canvases on the graphics chip (Windows), a reset of the chip gives these back empty:
    // either one coming back paints both again and drops the glows (draw() paints the ship's canvas itself anyway).
    const again = () => {
      if (this.destroyed) return;
      this.glows.clear();
      this.paintBase();
    };
    this.base.addEventListener("contextrestored", again);
    this.bloom.addEventListener("contextrestored", again);
  }

  /** The still ship and its bloom; cleared first, as the two can come back a moment apart and each paints both. */
  private paintBase() {
    const art = this.art, b = this.base.getContext("2d")!, bl = this.bloom.getContext("2d")!;
    b.clearRect(0, 0, VIEW.w, VIEW.h);
    bl.clearRect(0, 0, VIEW.w, VIEW.h);
    b.imageSmoothingEnabled = false;
    b.drawImage(art.ship, OX, OY, WORLD.w, WORLD.h);
    // A soft bloom made from the lit pixels: shrink, then grow back smoothly (works in every browser).
    const small = canvas(VIEW.w / 6, VIEW.h / 6), s = small.getContext("2d")!;
    s.imageSmoothingEnabled = true;
    s.drawImage(art.lights, OX / 6, OY / 6, WORLD.w / 6, WORLD.h / 6);
    bl.globalAlpha = 1; bl.imageSmoothingEnabled = true; bl.imageSmoothingQuality = "high";
    bl.drawImage(small, 0, 0, VIEW.w, VIEW.h);
    bl.globalAlpha = .55; bl.imageSmoothingEnabled = false;
    bl.drawImage(art.lights, OX, OY, WORLD.w, WORLD.h);
    bl.globalAlpha = 1;
    // Every light on the ship glows a little all the time; working rooms glow more (see draw).
    b.globalCompositeOperation = "lighter"; b.globalAlpha = .22;
    b.drawImage(this.bloom, 0, 0);
    b.globalCompositeOperation = "source-over"; b.globalAlpha = 1;
  }

  static async create(cv: HTMLCanvasElement): Promise<StudioScene> {
    const names = ["ship.png", "ship-lights.png", "crew.png", "consoles.png", "exhaust.png", "core.png"];
    const [ship, lights, crew, consoles, exhaust, core] = await withTimeout(Promise.all(names.map(spaceImage)), 12000);
    return new StudioScene(cv, { ship, lights, crew, consoles, exhaust, core });
  }

  /** A soft round light, made once per colour and size. */
  private glow(color: string, radius: number) {
    const key = `${color}:${radius}`;
    let g = this.glows.get(key);
    if (!g) {
      g = canvas(radius * 2, radius * 2);
      const c = g.getContext("2d")!, grad = c.createRadialGradient(radius, radius, 0, radius, radius, radius);
      grad.addColorStop(0, color); grad.addColorStop(.35, `${color}88`); grad.addColorStop(1, `${color}00`);
      c.fillStyle = grad; c.fillRect(0, 0, radius * 2, radius * 2);
      this.glows.set(key, g);
    }
    return g;
  }
  private light(x: number, y: number, radius: number, color: string, alpha: number) {
    if (alpha <= 0.01) return;
    const ctx = this.ctx, r = Math.round(radius), g = this.glow(color, r);
    ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = Math.min(1, alpha);
    ctx.drawImage(g, Math.round(x + OX - r), Math.round(y + OY - r));
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1;
  }

  draw(snap: Snapshot, actors: SceneActor[], t: number, still: boolean, pulseUntil: Map<RoomId, number>,
    coreBusy: boolean, offline = false, handoffs: SceneHandoff[] = [], cues: SceneCues = {}) {
    if (this.destroyed) return;
    const ctx = this.ctx;
    const step = Math.floor(t / STEP) * STEP;
    const states = new Map(snap.roles.map(r => [r.id, r.state]));
    const busyRooms = new Set<RoomId>();
    for (const r of snap.roles) if (BUSY.includes(r.state) && BY_ID[r.id]) busyRooms.add(BY_ID[r.id].room);
    const runPaused = ["paused", "pausing"].includes(snap.run.state);
    const paused = runPaused || snap.brain?.state === "paused";
    const actualBrainBusy = snap.brain?.state === "evaluating" || snap.brain?.activity?.state === "working"
      || busyRooms.has("brain");
    // A still picture keeps a short cue at its frozen phase, while a real change of state still shows.
    if (paused || offline) this.brainBusy = false;
    else if (!still || this.lastActualBrainBusy === undefined || this.brainSuppressed) {
      this.brainBusy = coreBusy || actualBrainBusy;
    } else if (actualBrainBusy !== this.lastActualBrainBusy) this.brainBusy = actualBrainBusy;
    this.lastActualBrainBusy = actualBrainBusy;
    this.brainSuppressed = paused || offline;
    const coreMode: CoreMode = offline ? "offline" : paused ? "paused" : this.brainBusy ? "active" : "standby";

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, VIEW.w, VIEW.h);
    ctx.imageSmoothingEnabled = false;
    this.engines(step, still, offline);
    ctx.drawImage(this.base, 0, 0);

    // Room lights: a working room is lit; the rest keep their resting glow.
    for (const r of ROOMS) {
      if (r.id === "lounge") continue;
      const lit = busyRooms.has(r.id) && !offline;
      let alpha = lit ? .62 : 0;
      if (lit && !still) alpha += .08 * Math.sin((t + hash(r.id) % 900) / 650);
      if (r.id === "brain" && coreMode === "active") alpha = Math.max(alpha, .5);
      if (alpha > 0) {
        ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = alpha;
        ctx.drawImage(this.bloom, r.x + OX, r.y + OY, r.w, r.h, r.x + OX, r.y + OY, r.w, r.h);
      }
    }
    ctx.globalCompositeOperation = "source-over"; ctx.globalAlpha = 1;
    this.core(step, t, still, coreMode);
    this.dockBeacon(t, still, (cues.dockUntil || 0) > t && !offline, states.get("dock"));

    // Consoles and robots, nearest last.
    const items: { y: number; draw: () => void }[] = [];
    const where = new Map(actors.map(a => [a.id, a]));
    for (const [id, at] of Object.entries(CONSOLE)) {
      if (!at) continue;
      const room = BY_ID[id]?.room, row = CONSOLE_ART.rows.indexOf(room);
      if (row < 0) continue;
      const a = where.get(id), state = states.get(id) || "unavailable", home = STATION[id], r = ROOM[room];
      const inRoom = !!a && a.x >= r.x && a.x <= r.x + r.w && a.y >= r.y && a.y <= r.y + r.h;
      const atDesk = !!a && Math.abs(a.x - home.x) + Math.abs(a.y - home.y) < 6;
      const working = atDesk && (state === "working" || state === "retrying") && !offline;
      let col = !inRoom || state === "unavailable" || offline ? 0 : 1;
      if (working) col = 2 + (still ? 1 : Math.floor((step + hash(id) % 400) / 125) % 4);
      items.push({ y: at.y - .5, draw: () => {
        const [cw, ch] = CONSOLE_ART.cell;
        ctx.drawImage(this.art.consoles, col * cw, row * ch, cw, ch,
          Math.round(at.x - cw / 2 + OX), Math.round(at.y - ch + 1 + OY), cw, ch);
        if (working) this.light(at.x, at.y - 14, 16, r.accent, .55);
      } });
    }
    for (const a of actors) items.push({ y: a.y, draw: () => this.robot(a, states.get(a.id) || "unavailable", step,
      still, offline) });
    items.sort((p, q) => p.y - q.y);
    for (const item of items) item.draw();

    // Work passed from one robot to the next: a real handoff only, drawn while the controller passes it.
    for (const h of handoffs) {
      const p = Math.max(0, Math.min(1, h.progress));
      const x = h.from.x + (h.to.x - h.from.x) * p, y = h.from.y + (h.to.y - h.from.y) * p - 24
        - Math.sin(Math.PI * p) * 6;
      this.paper(x, y);
    }
    // A room that just received a decision outlines itself briefly.
    for (const r of ROOMS) {
      const until = pulseUntil.get(r.id) || 0;
      if (until <= t) continue;
      ctx.globalAlpha = still ? .7 : Math.min(.85, Math.max(0, (until - t) / 900));
      ctx.strokeStyle = r.accent; ctx.lineWidth = 3;
      ctx.strokeRect(r.x + OX + 3, r.y + OY + 3, r.w - 6, r.h - 6);
      ctx.globalAlpha = 1;
    }
    if (offline) {
      ctx.fillStyle = "rgba(6, 10, 24, .38)";
      ctx.fillRect(0, 0, VIEW.w, VIEW.h);
    }
  }

  private engines(step: number, still: boolean, offline: boolean) {
    const ctx = this.ctx, [w, h] = EXHAUST_ART.cell;
    SHIP.engines.forEach(([x, y], i) => {
      const k = still ? (i * 2) % EXHAUST_ART.count : Math.floor((step + i * 377) / ENGINE_MS[i]) % EXHAUST_ART.count;
      const flicker = still ? 1 : .86 + .14 * (((k * 7 + i * 3) % 5) / 4);
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = (offline ? .45 : 1) * flicker;
      ctx.drawImage(this.art.exhaust, 0, k * h, w, h, x - w + OX, y - h / 2 + OY, w, h);
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
      this.light(x - 6, y, 34, "#7fdcff", (offline ? .2 : .45) * flicker);
    });
  }

  private core(step: number, t: number, still: boolean, mode: CoreMode) {
    const ctx = this.ctx, img = this.art.core;
    const cx = SHIP.core.x, cy = SHIP.core.y, left = Math.round(cx - img.width / 2 + OX);
    const top = Math.round(cy - img.height / 2 + OY);
    const strength = { active: .75, standby: .38, paused: .2, offline: .08 }[mode];
    this.light(cx, cy - 16, 64, "#b46cff", strength);
    const bob = still || mode === "paused" || mode === "offline" ? 0
      : Math.round(Math.sin(step / (mode === "active" ? 420 : 900)) * 1.6);
    ctx.globalAlpha = mode === "offline" ? .55 : 1;
    // The projector stays put; the brain floats above it.
    ctx.drawImage(img, 0, CORE_SPLIT, img.width, img.height - CORE_SPLIT, left, top + CORE_SPLIT, img.width,
      img.height - CORE_SPLIT);
    ctx.drawImage(img, 0, 0, img.width, CORE_TOP, left, top + bob, img.width, CORE_TOP);
    ctx.globalAlpha = 1;
    if (mode === "offline") return;
    // Orbiting rings around the brain, and rings the projector sends up while CORE works.
    const brainY = cy - 22 + bob + OY, x = cx + OX;
    // a paused Brain holds its rings still, like its float, while the rest of the ship keeps moving
    const turn = still || mode === "paused" ? .6 : t / (mode === "active" ? 2200 : 7000) * Math.PI * 2;
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 1.5;
    for (const [rx, ry, tilt, offset] of [[46, 10, -.16, 0], [40, 13, .22, Math.PI * .8]]) {
      ctx.strokeStyle = "#a678ff"; ctx.globalAlpha = .28 + strength * .25;
      ctx.beginPath(); ctx.ellipse(x, brainY, rx, ry, tilt, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = "#e7d2ff"; ctx.globalAlpha = .45 + strength * .4;
      const a = turn + offset;
      ctx.beginPath(); ctx.ellipse(x, brainY, rx, ry, tilt, a, a + .9); ctx.stroke();
    }
    if (mode === "active") {
      const baseY = cy + 8 + OY;
      for (let i = 0; i < 3; i++) {
        const p = still ? (i + 1) / 4 : ((t / 1500) + i / 3) % 1;
        ctx.strokeStyle = "#c79bff"; ctx.globalAlpha = (1 - p) * .7;
        ctx.beginPath(); ctx.ellipse(x, baseY - p * 34, 14 + p * 24, 3 + p * 5, 0, 0, Math.PI * 2); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
  }

  private dockBeacon(t: number, still: boolean, acknowledging: boolean, state: RoleState | undefined) {
    const x = HATCH.x, y = HATCH.y - 30, ctx = this.ctx;
    const uploading = state === "working" || state === "retrying";
    let alpha = uploading ? .35 : .12;
    if (acknowledging) alpha = still ? .9 : .45 + .5 * Math.max(0, Math.sin(t / 110));
    else if (uploading && !still) alpha += .15 * Math.sin(t / 500);
    this.light(x, y, 26, "#ffb347", alpha);
    ctx.fillStyle = acknowledging || uploading ? "#ffd27a" : "#8a6a3a";
    ctx.fillRect(Math.round(x - 3 + OX), Math.round(y - 2 + OY), 6, 4);
    if (acknowledging && !still) {
      // a turning beam, like a lighthouse
      const a = (t / 420) % (Math.PI * 2);
      ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = .35; ctx.fillStyle = "#ffb347";
      ctx.beginPath(); ctx.moveTo(x + OX, y + OY);
      ctx.arc(x + OX, y + OY, 42, a, a + .45); ctx.closePath(); ctx.fill();
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = "source-over";
    }
  }

  private frame(a: SceneActor, state: RoleState, t: number, still: boolean): { frame: FrameName; dx: number } {
    const seed = hash(a.id);
    const toward: FrameName = (CONSOLE[a.id]?.x ?? STATION[a.id].x + 1) < STATION[a.id].x ? "look_left" : "look_right";
    if (a.pose === "walk" || a.pose === "carry") {
      if (a.dir === "left" || a.dir === "right") this.side.set(a.id, a.dir);
      const side = this.side.get(a.id) || "right";
      if (still) return { frame: side === "left" ? "look_left" : "look_right", dx: 0 };
      return { frame: `walk_${side}_${Math.floor(t / 170) % 2 ? "b" : "a"}` as FrameName, dx: 0 };
    }
    if (a.pose === "work" || a.pose === "retry" || a.pose === "approved") {
      if (still) return { frame: "work_2", dx: 0 };
      const ms = a.pose === "retry" ? 90 : 125;
      const cycle: FrameName[] = a.pose === "approved" ? ["work_1", "work_2", "work_3", "work_3", "work_3", "work_2"]
        : ["work_0", "work_1", "work_2", "work_3", "work_3", "work_3", "work_2", "work_1", "work_0", "work_0", toward,
          toward];
      return { frame: cycle[Math.floor((t + seed % 1500) / ms) % cycle.length], dx: 0 };
    }
    if (still) return { frame: "idle", dx: 0 };
    if (a.pose === "review" || a.pose === "wait") {
      const cycle: FrameName[] = ["idle", "look_left", "look_left", "idle", "look_right", "look_right"];
      return { frame: cycle[Math.floor((t + seed % 2000) / 450) % cycle.length], dx: 0 };
    }
    if (a.pose === "rework") return { frame: Math.floor(t / 500) % 2 ? "look_left" : "idle", dx: 0 };
    if (a.pose === "error") return { frame: Math.floor(t / 600) % 2 ? "blink" : "idle", dx: 0 };
    if (a.pose === "paused" || a.pose === "unavailable" || state === "unavailable") return { frame: "idle", dx: 0 };
    if (a.breakActivity) return this.breakFrame(a, t, seed);
    // Idle crew blink, look around and shift their weight, each on its own clock.
    const period = 4800 + seed % 3200, u = (t + seed) % period, round = Math.floor((t + seed) / period);
    if (u < 130) return { frame: "blink", dx: 0 };
    if (round % 3 === 1) {
      if (u >= 1800 && u < 2500) return { frame: "look_left", dx: 0 };
      if (u >= 2500 && u < 3100) return { frame: "look_right", dx: 0 };
    }
    if (round % 3 === 2 && u >= 2000 && u < 3400) return { frame: "idle", dx: seed & 1 ? 1 : -1 };
    return { frame: "idle", dx: 0 };
  }

  private breakFrame(a: SceneActor, t: number, seed: number): { frame: FrameName; dx: number } {
    const phase = a.breakPhase || 0;
    switch (a.breakActivity) {
      case "rest": return { frame: phase > .45 && phase < .8 ? "blink" : "idle", dx: 0 };
      case "read": return { frame: Math.floor((t + seed) / 900) % 2 ? "look_left" : "look_right", dx: 0 };
      case "arcade": {
        const cycle: FrameName[] = ["look_left", "look_left", "idle", "look_right", "idle", "look_left"];
        return { frame: cycle[Math.floor((t + seed) / 260) % cycle.length], dx: 0 };
      }
      case "boardgame": {
        const k = Math.floor((t + seed) / 1300) % 3;
        return { frame: k === 0 ? "look_right" : k === 1 ? "look_left" : "idle", dx: 0 };
      }
      default: return { frame: (t + seed) % 3600 < 140 ? "blink" : "idle", dx: 0 };
    }
  }

  private robot(a: SceneActor, state: RoleState, step: number, still: boolean, offline: boolean) {
    const art = ART[a.id];
    if (!art) return;
    const ctx = this.ctx;
    let { frame, dx } = this.frame(a, state, step, still);
    // a Taser zap takes over the robot's look for a moment (taser.ts)
    const zap = a.zap ? zapPose(a.zap.kind, a.zap.ms) : null;
    if (zap?.frame) { frame = zap.frame; dx = 0; }
    const seated = a.posture === "rest" && !!a.breakActivity;
    const x = Math.round(a.x + dx), y = Math.round(a.y);
    if (a.selected) this.marker(x, y, step, still);
    // a soft shadow grounds the robot on the floor; it shrinks while the robot is up in the air and widens lying down
    const up = zap ? Math.max(0, -zap.dy) : 0, lying = zap ? Math.abs(Math.sin(zap.rot)) : 0;
    ctx.fillStyle = "rgba(6, 8, 20, .35)";
    ctx.beginPath();
    ctx.ellipse(x + OX + (zap ? zap.dx - lying * art.h * .45 : 0), y + OY,
      Math.max(4, art.w * .36 * (1 - Math.min(.6, up / 50)) + lying * art.h * .2), 3, 0, 0, Math.PI * 2);
    ctx.fill();
    const dim = offline ? .7 : state === "unavailable" || a.pose === "unavailable" ? .5 : a.pose === "paused" ? .78 : 1;
    const sx = frameIndex(frame) * CELL.w, sy = art.row * CELL.h;
    // seated robots tuck their feet behind the sofa or table
    const cut = seated ? 6 : 0;
    ctx.globalAlpha = dim;
    if (zap) {
      ctx.save();
      ctx.translate(x + OX + zap.dx, y + OY + zap.dy + (seated ? 4 : 0));
      if (zap.rot) ctx.rotate(zap.rot);
      ctx.scale(zap.sx * (zap.flip ? -1 : 1), zap.sy);
      const look = zap.tint || zap.xray ? this.tinted(sx, sy, art.w, art.h - cut, art.cx, zap) : null;
      if (look) ctx.drawImage(look, 0, 0, art.w, art.h - cut, -art.cx, -art.foot, art.w, art.h - cut);
      else ctx.drawImage(this.art.crew, sx, sy, art.w, art.h - cut, -art.cx, -art.foot, art.w, art.h - cut);
      ctx.restore();
    } else {
      ctx.drawImage(this.art.crew, sx, sy, art.w, art.h - cut, Math.round(x - art.cx + OX),
        Math.round(y - art.foot + OY + (seated ? 4 : 0)), art.w, art.h - cut);
    }
    ctx.globalAlpha = 1;
    if (a.zap && zap) {
      this.zapped(a.zap, zap, x, y, art.h);
    } else {
      if (frame.startsWith("work_") && !offline) {
        const k = Number(frame.slice(5));
        for (const [gx, gy, r, color] of art.glows[k] || []) {
          this.light(x - art.cx + gx, y - art.foot + gy, Math.max(4, r * 2.2), color, .75);
        }
      }
      if (a.pose === "carry") this.paper(x + 10, y - 18);
      if (a.breakActivity && (!still || a.breakActivity === "read")) this.prop(a, x, y, art.h);
    }
    if (state === "error" && !offline) {
      if (still || Math.floor(step / 400) % 2 === 0) this.light(x, y - art.h - 5, 8, "#ff5d6c", .9);
      ctx.fillStyle = "#ff5d6c";
      ctx.fillRect(x - 2 + OX, y - art.h - 7 + OY, 4, 4);
    }
  }

  /** The robot's sprite recoloured for a zap: a flash, soot or a golden glow over it, or the X-ray look (a cyan
   * silhouette with its wiring skeleton showing). Only the robot's own pixels change. */
  private tinted(sx: number, sy: number, w: number, h: number, cx: number, zap: ZapPose) {
    const c = this.tint ||= canvas(CELL.w, CELL.h);
    const t = c.getContext("2d")!;
    t.setTransform(1, 0, 0, 1, 0, 0);
    t.globalCompositeOperation = "source-over"; t.globalAlpha = 1; t.imageSmoothingEnabled = false;
    t.clearRect(0, 0, c.width, c.height);
    t.drawImage(this.art.crew, sx, sy, w, h, 0, 0, w, h);
    t.globalCompositeOperation = "source-atop";
    if (zap.xray) {
      t.fillStyle = "#2ad8ff"; t.globalAlpha = .94; t.fillRect(0, 0, w, h);
      t.globalAlpha = 1;
      const m = Math.round(cx), bone = (bx: number, by: number, bw: number, bh: number) =>
        t.fillRect(m + bx, Math.round(by), bw, Math.max(1, Math.round(bh)));
      t.fillStyle = "#f4fbff";
      bone(-5, h * .1, 10, 7);                                   // skull
      bone(-1, h * .1 + 7, 2, h * .5);                           // spine
      for (let i = 0; i < 3; i++) bone(-6, h * .38 + i * 4, 12, 1);  // ribs
      bone(-5, h * .72, 10, 2);                                  // hips
      bone(-4, h * .72, 2, h * .26); bone(2, h * .72, 2, h * .26);   // legs
      bone(-10, h * .38, 2, h * .28); bone(8, h * .38, 2, h * .28);  // arms
      t.fillStyle = "#0b3a52";
      bone(-3, h * .1 + 2, 2, 2); bone(1, h * .1 + 2, 2, 2);      // eye sockets
      t.fillStyle = "#ffe14d";
      bone(-1, h * .44, 2, 2);                                   // a glowing bolt where its heart would be
    } else if (zap.tint) {
      t.fillStyle = zap.tint.color; t.globalAlpha = Math.min(1, zap.tint.alpha); t.fillRect(0, 0, w, h);
    }
    t.globalCompositeOperation = "source-over"; t.globalAlpha = 1;
    return c;
  }

  /** What flies around a zapped robot: sparks, arcs, dizzy stars, smoke, dust, music notes and golden rings. They
   * move with the robot (and turn with it when it falls over); dust stays on the floor. */
  private zapped(z: NonNullable<SceneActor["zap"]>, pose: ZapPose, x: number, y: number, height: number) {
    const ctx = this.ctx, cos = Math.cos(pose.rot), sin = Math.sin(pose.rot);
    const at = (px: number, py: number, ground = false) => ground
      ? [x + OX + pose.dx + px, y + OY + py]
      : [x + OX + pose.dx + px * cos - py * sin, y + OY + pose.dy + px * sin + py * cos];
    if (z.kind === "overcharge") this.light(x, y - height * .5, 30, "#ffd23f", .55 * (1 - z.ms / 1800));
    else if (pose.tint && (pose.tint.color === "#9ff3ff" || pose.tint.color === "#ffffff")) {
      this.light(x + pose.dx, y + pose.dy - height * .5, 26, "#59e8ff", pose.tint.alpha * .6);
    }
    if (pose.xray) this.light(x + pose.dx, y - height * .5, 28, "#2ad8ff", .5);
    for (const p of zapParticles(z.kind, z.ms, height, z.seed)) {
      ctx.globalAlpha = Math.max(0, Math.min(1, p.alpha));
      switch (p.kind) {
        case "spark": {
          const [px, py] = at(p.x, p.y), [tx, ty] = at(p.x - p.dx, p.y - p.dy);
          ctx.strokeStyle = p.color; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(tx, ty); ctx.stroke();
          ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(px - 1), Math.round(py - 1), 2, 2);
          break;
        }
        case "arc": {
          const pts = [0, 2, 4].map(i => at(p.points[i], p.points[i + 1]));
          for (const [color, width] of [["#2ad8ff", 3], ["#e9fdff", 1.2]] as const) {
            ctx.strokeStyle = color; ctx.lineWidth = width;
            ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
            for (const [px, py] of pts.slice(1)) ctx.lineTo(px, py);
            ctx.stroke();
          }
          break;
        }
        case "star": {
          const [px, py] = at(p.x, p.y), s = p.size;
          ctx.fillStyle = "#ffe14d";
          ctx.fillRect(Math.round(px - 1), Math.round(py - s), 2, s * 2);
          ctx.fillRect(Math.round(px - s), Math.round(py - 1), s * 2, 2);
          ctx.fillStyle = "#ffffff"; ctx.fillRect(Math.round(px - 1), Math.round(py - 1), 2, 2);
          break;
        }
        case "note": {
          const [px, py] = at(p.x, p.y), left = Math.round(px), top = Math.round(py);
          ctx.fillStyle = "#ff9bd2";
          ctx.fillRect(left, top, 3, 2); ctx.fillRect(left + 2, top - 6, 1, 7); ctx.fillRect(left + 3, top - 6, 2, 1);
          break;
        }
        case "smoke": case "dust": {
          const [px, py] = at(p.x, p.y, p.kind === "dust");
          ctx.fillStyle = p.kind === "smoke" ? "#3b3744" : "#c9c2d9";
          ctx.beginPath(); ctx.arc(px, py, p.size * (p.kind === "dust" ? .6 : 1), 0, Math.PI * 2); ctx.fill();
          break;
        }
        case "ring": {
          const [px, py] = at(p.x, p.y);
          ctx.strokeStyle = "#ffd23f"; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.ellipse(px, py, p.rx, p.ry, 0, 0, Math.PI * 2); ctx.stroke();
          break;
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  /** Small things robots hold on a break: a cup, a snack, a book or a game piece. */
  private prop(a: SceneActor, x: number, y: number, height: number) {
    const ctx = this.ctx, phase = a.breakPhase || 0, chest = y - height * .42;
    const px = (dx: number, dy: number, w: number, h: number, color: string) => {
      ctx.fillStyle = color; ctx.fillRect(Math.round(x + dx + OX), Math.round(dy + OY), w, h);
    };
    switch (a.breakActivity) {
      case "drink": {
        const lift = phase > .3 && phase < .55 ? 6 : 0;
        px(9, chest - lift, 4, 5, "#eef3ff"); px(9, chest - lift, 4, 1, "#7a4a2a"); px(13, chest - lift + 1, 1, 2, "#eef3ff");
        break;
      }
      case "snack": {
        const lift = phase > .35 && phase < .55 ? 6 : 0;
        px(9, chest - lift, 4, 3, "#ffcf5a"); px(10, chest - lift - 1, 2, 1, "#ffe9a8");
        break;
      }
      case "read":
        px(-6, chest + 1, 5, 6, "#5b8cff"); px(1, chest + 1, 5, 6, "#5b8cff");
        px(-5, chest + 2, 4, 4, "#f2f5ff"); px(1, chest + 2, 4, 4, "#f2f5ff");
        break;
      case "boardgame":
        px(-7 + Math.floor(phase * 4) * 3, y - 8, 3, 3, phase > .5 ? "#ff6fae" : "#7fe3ff");
        break;
      case "arcade":
        this.light(x, y - height - 2, 10, phase > .5 ? "#7fe3ff" : "#ff6fae", .35);
        break;
      default: break;
    }
  }

  private paper(x: number, y: number) {
    const ctx = this.ctx, left = Math.round(x - 4 + OX), top = Math.round(y - 5 + OY);
    ctx.fillStyle = "#1a2040"; ctx.fillRect(left - 1, top - 1, 10, 12);
    ctx.fillStyle = "#f4f1e6"; ctx.fillRect(left, top, 8, 10);
    ctx.fillStyle = "#9a7cff"; ctx.fillRect(left + 1, top + 1, 6, 2);
    ctx.fillStyle = "#8d96ab"; ctx.fillRect(left + 1, top + 5, 5, 1); ctx.fillRect(left + 1, top + 7, 4, 1);
  }

  private marker(x: number, y: number, step: number, still: boolean) {
    const ctx = this.ctx, bob = still ? 0 : Math.floor(step / 300) % 2;
    ctx.fillStyle = "rgba(108, 207, 246, .2)"; ctx.strokeStyle = "#6ccff6"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.ellipse(x + OX, y + OY + 1, 17, 5, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    // a pointer over the head so the chosen robot is easy to find at whole-ship size
    const top = y - 58 - bob + OY;
    ctx.fillStyle = "#081226";
    ctx.beginPath(); ctx.moveTo(x - 7 + OX, top - 1); ctx.lineTo(x + 7 + OX, top - 1); ctx.lineTo(x + OX, top + 9);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#6ccff6";
    ctx.beginPath(); ctx.moveTo(x - 5 + OX, top); ctx.lineTo(x + 5 + OX, top); ctx.lineTo(x + OX, top + 7);
    ctx.closePath(); ctx.fill();
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.glows.clear();
    this.base.width = this.base.height = 0;
    this.bloom.width = this.bloom.height = 0;
    if (this.tint) this.tint.width = this.tint.height = 0;
  }
}
