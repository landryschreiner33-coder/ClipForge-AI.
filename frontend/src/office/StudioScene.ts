/** Furnished PixiJS living studio. Real feed states drive work, reports and handoffs. */
import { Application, Assets, Container, Graphics, Texture } from "pixi.js";
import { CAST, BY_ID, Dir, RoomId } from "./cast";
import { ROOM_ACCENT } from "./draw";
import { Snapshot } from "./api";
import { BreakActivity, CORE_AT, Pt, ROBOT_SCALE, ROOMS, STATION, WORLD } from "./world";
import { Pose } from "./sprites";
import { createRobot } from "./StudioArt";
import { createBrainCore } from "./BrainCore";
import { cachedLightPool, createLoungeDecor, skylineWindow } from "./LoungeDecor";

export interface SceneActor {
  id: string; x: number; y: number; pose: Pose; dir: Dir; selected: boolean;
  posture?: "stand" | "desk" | "rest";
  breakActivity?: BreakActivity | null;
  breakPhase?: number;
}
export interface SceneHandoff { id: number; from: Pt; to: Pt; progress: number }
type RobotArt = ReturnType<typeof createRobot>;
const INK = "#101925", WOOD = "#b89570", WOOD_EDGE = "#80644d";
const FLOOR: Record<RoomId, string> = {
  lounge: "#343e42", boss: "#343b49", brain: "#353448", discover: "#30423e", workspace: "#35424a",
  analyze: "#354256", studio: "#423644", system: "#3a403f", caption: "#3c394e", schedule: "#464039", dock: "#34433f",
};
const px = (g: Graphics, x: number, y: number, w: number, h: number, color: string, alpha = 1) => {
  g.rect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)).fill({ color, alpha });
};
const box = (g: Graphics, x: number, y: number, w: number, h: number, color: string, edge = INK) => {
  px(g, x, y, w, h, edge); px(g, x + 1, y + 1, w - 2, h - 2, color);
};
function plant(g: Graphics, x: number, y: number, tall = false) {
  px(g, x - 6, y + 7, 17, 3, "#07101b", .3);
  box(g, x - 2, y, 12, 10, "#b77d59"); px(g, x - 1, y + 1, 10, 2, "#dfb18e");
  px(g, x + 3, y - (tall ? 23 : 12), 2, tall ? 25 : 14, "#77995e");
  for (const [dx, dy, w, h] of tall ? [[-8, -24, 10, 8], [3, -29, 9, 9], [7, -17, 10, 7], [-7, -13, 10, 7]]
    : [[-5, -10, 8, 6], [3, -16, 8, 8], [6, -8, 8, 6]]) {
    box(g, x + dx, y + dy, w, h, "#537a58", "#233e38");
    px(g, x + dx + 1, y + dy + 1, w - 3, 2, "#91b47a");
  }
}
function rug(g: Graphics, x: number, y: number, w: number, h: number, color: string) {
  box(g, x, y, w, h, color, "#232b36");
  px(g, x + 3, y + 3, w - 6, 1, "#ede1c0", .18);
  px(g, x + 3, y + h - 4, w - 6, 1, "#ede1c0", .18);
  for (let xx = x + 8; xx < x + w - 5; xx += 8) px(g, xx, y + 5, 1, h - 10, "#13232a", .08);
}
function shelf(g: Graphics, x: number, y: number, w = 28, h = 32) {
  box(g, x, y, w, h, "#76645b");
  const books = ["#b88377", "#c2ab7c", "#729cae", "#779e84", "#ac91bd"];
  for (let row = 0; row < 2; row++) {
    const sy = y + 3 + row * Math.floor(h / 2);
    px(g, x + 1, sy + 10, w - 2, 2, "#433b41");
    for (let j = 0; j < Math.floor((w - 5) / 4); j++) {
      box(g, x + 3 + j * 4, sy + j % 2, 3, 10 - j % 2, books[(j + row) % books.length]);
      px(g, x + 3 + j * 4, sy + 2, 1, 1, "#e4d5b0");
    }
  }
}
function windowPanel(g: Graphics, x: number, y: number, w = 36) {
  box(g, x - 2, y - 2, w + 4, 23, "#172638", "#131e2b");
  box(g, x, y, w, 18, "#41606a", "#819293");
  px(g, x + 2, y + 2, w - 4, 5, "#a8c5bf", .36);
  px(g, x + Math.floor(w / 2), y + 1, 2, 16, "#8b9391");
  px(g, x + 1, y + 9, w - 2, 1, "#707e83");
  px(g, x - 3, y + 18, w + 6, 3, "#a5a493");
  g.poly([x + 2, y + 21, x + w - 2, y + 21, x + w + 14, y + 57, x + 18, y + 57])
    .fill({ color: "#cce4d8", alpha: .045 });
}
function chairBack(g: Graphics, p: Pt, color: string, rest = false) {
  const w = rest ? 34 : 30;
  px(g, p.x - w / 2 + 2, p.y - 3, w + 1, 6, "#09131f", .24);
  box(g, p.x - w / 2, p.y - 34, w, 22, color, "#1a2530");
  px(g, p.x - w / 2 + 2, p.y - 32, w - 4, 3, "#ccddd0", .22);
  px(g, p.x - w / 2 + 2, p.y - 29, 2, 14, "#18232b", .23);
  box(g, p.x - w / 2 + 1, p.y - 17, w - 2, 12, color, "#24303a");
  px(g, p.x - w / 2 + 3, p.y - 16, w - 6, 2, "#d8d2b3", .14);
  px(g, p.x - 9, p.y - 4, 2, 7, "#253142"); px(g, p.x + 7, p.y - 4, 2, 7, "#253142");
}
function deskBack(g: Graphics, p: Pt, w: number) {
  px(g, p.x - w / 2 + 2, p.y - 11, w + 2, 17, "#091421", .25);
  px(g, p.x - w / 2 + 4, p.y - 16, 4, 18, "#253140");
  px(g, p.x + w / 2 - 8, p.y - 16, 4, 18, "#253140");
  box(g, p.x - w / 2 + 2, p.y - 20, w - 4, 12, WOOD_EDGE);
}
function deskFront(g: Graphics, p: Pt, w: number, accent: string) {
  box(g, p.x - w / 2 - 1, p.y - 22, w + 2, 12, WOOD);
  px(g, p.x - w / 2 + 1, p.y - 21, w - 2, 2, "#e0bf96");
  px(g, p.x - w / 2 + 2, p.y - 12, w - 4, 4, WOOD_EDGE);
  px(g, p.x - w / 2 + 4, p.y - 10, w - 8, 1, "#c6a681", .5);
  box(g, p.x - 10, p.y - 21, 20, 4, "#5d6872");
  for (let j = 0; j < 6; j++) px(g, p.x - 8 + j * 3, p.y - 20, 2, 1, "#b4bbc0");
  box(g, p.x + w / 2 - 11, p.y - 23, 6, 5, "#d3c6ae");
  px(g, p.x + w / 2 - 9, p.y - 22, 2, 2, accent, .7);
}
function monitor(g: Graphics, lights: Graphics, p: Pt, accent: string) {
  const x = p.x - 20, y = p.y - 57, w = 26;
  box(g, x, y, w, 18, "#435267");
  px(g, x + 2, y + 2, w - 4, 12, "#12283b");
  px(g, x + 1, y + 1, w - 2, 1, "#81909c");
  px(g, x + 12, y + 18, 3, 5, "#263243");
  box(g, x + 6, y + 22, 15, 3, "#636f7c");
  px(lights, x + 3, y + 3, w - 6, 10, accent, .24);
  px(lights, x + 4, y + 5, 4, 3, accent, .7);
  px(lights, x + w - 5, y + 15, 2, 1, accent, .85);
}

export class StudioScene {
  private app: Application;
  private robots = new Map<string, RobotArt>();
  private lights = new Map<RoomId, Graphics>();
  private roomHighlights = new Map<RoomId, Graphics>();
  private selector = new Graphics();
  private racks = new Graphics();
  private rackLamps: Pt[] = [];
  private core = createBrainCore();
  private actors = new Container();
  private transfers = new Graphics();
  private skyline: Texture | null;
  private croppedTextures: Texture[] = [];
  private lounge: ReturnType<typeof createLoungeDecor> | null = null;
  private destroyed = false;

  private constructor(app: Application, skyline: Texture | null) { this.app = app; this.skyline = skyline; }
  static async create(canvas: HTMLCanvasElement): Promise<StudioScene> {
    const app = new Application();
    let scene: StudioScene | undefined;
    try {
      await app.init({ canvas, width: WORLD.w, height: WORLD.h, resolution: 1, antialias: false,
        autoStart: false, preference: "webgl", preserveDrawingBuffer: true, backgroundAlpha: 0,
        powerPreference: "low-power" });
      // This optional decoration cannot hold the first office frame indefinitely. Assets owns the shared texture;
      // a request finishing after the deadline only populates its cache, with no late scene mutation or ticker.
      let timer: ReturnType<typeof setTimeout> | undefined;
      const requestedSkyline = Assets.load<Texture>("/office-art/skyline.png").catch(() => null);
      const skyline = await Promise.race([requestedSkyline, new Promise<null>(resolve => {
        timer = setTimeout(() => resolve(null), 1500);
      })]);
      if (timer !== undefined) clearTimeout(timer);
      if (skyline) skyline.source.scaleMode = "nearest";
      scene = new StudioScene(app, skyline);
      scene.build();
      return scene;
    } catch (error) {
      try {
        if (scene) scene.destroy();
        else app.destroy(false, { children: true });
      } catch { /* init may not have completed */ }
      throw error;
    }
  }
  private foreground(g: Graphics, feet: number) {
    g.zIndex = feet + 1;
    this.actors.addChild(g);
  }
  private window(g: Graphics, x: number, y: number, w = 36, section = .5) {
    windowPanel(g, x, y, w);
    const cropped = skylineWindow(g, this.skyline, x + 2, y + 2, w - 4, 12, section);
    if (cropped) this.croppedTextures.push(cropped);
  }
  private build() {
    const g = new Graphics();
    this.app.stage.addChild(g);
    px(g, 0, 0, WORLD.w, WORLD.h, "#1c293a");
    for (let y = 0; y < WORLD.h; y += 16) for (let x = 0; x < WORLD.w; x += 24) {
      px(g, x + 1, y + 1, 23, 15, "#28374a");
      if ((x / 24 + y / 16) % 4 === 0) px(g, x + 3, y + 3, 5, 1, "#71829a", .12);
    }
    // Inset hall light strips mark the real clear circulation space, without drawing fake job paths.
    for (const [y, x1, x2] of [[280, 8, 952], [446, 8, 952], [144, 440, 664]]) {
      px(g, x1, y, x2 - x1, 1, "#94a9bd", .14);
      px(g, x1, y + 1, x2 - x1, 3, "#9dbfbe", .035);
    }
    this.actors.sortableChildren = true;
    for (const r of ROOMS) {
      const accent = ROOM_ACCENT[r.id], x = r.x, y = r.y;
      px(g, x + 4, y + 6, r.w, r.h, "#08101b", .3);
      box(g, x, y, r.w, r.h, FLOOR[r.id], "#142234");
      for (let yy = y + 20; yy < y + r.h - 1; yy += 12) {
        px(g, x + 3, yy, r.w - 6, 1, "#152333", .17);
        for (let xx = x + 16 + ((yy - y) % 24 ? 0 : 22); xx < x + r.w - 3; xx += 44)
          px(g, xx, yy - 10, 1, 10, "#142435", .12);
      }
      // Layered ambient light is decorative and static. Work lights below remain tied to real roles.
      for (let layer = 0; layer < 5; layer++)
        px(g, x + 10 + layer * 9, y + 18 + layer * 5, r.w - 20 - layer * 18, r.h - 28 - layer * 10,
          r.id === "lounge" ? "#d1c394" : "#d5dded", .012);
      px(g, x + 1, y + 1, r.w - 2, 8, "#47556a");
      px(g, x + 1, y + 1, r.w - 2, 1, "#8291a2", .55);
      px(g, x + 1, y + 8, r.w - 2, 3, "#1b2b3b");
      px(g, x + 1, y + 10, 3, r.h - 11, "#536074");
      px(g, x + r.w - 4, y + 10, 3, r.h - 11, "#23354b");
      px(g, x + 4, y + r.h - 3, r.w - 8, 2, "#1d2c3c");
      px(g, x + 6, y + 10, r.w - 12, 1, accent, .24);
      const d = r.door;
      if (d.y === y + r.h) {
        px(g, d.x - 17, d.y - 4, 34, 8, "#344153");
        px(g, d.x - 17, d.y - 3, 2, 7, "#809094"); px(g, d.x + 15, d.y - 3, 2, 7, "#809094");
      } else {
        px(g, d.x - 4, d.y - 56, 8, 64, "#2b3b4e");
        px(g, d.x - 4, d.y - 57, 8, 2, "#849296"); px(g, d.x - 4, d.y + 7, 8, 2, "#6c797f");
        px(g, d.x - 2, d.y - 55, 4, 61, "#2b3b4e");
      }
      const glow = new Graphics();
      px(glow, x + 6, y + 11, r.w - 12, 2, accent, .3);
      this.lights.set(r.id, glow); this.app.stage.addChild(glow);
      const pulse = new Graphics();
      pulse.rect(x + 2, y + 2, r.w - 4, r.h - 4).stroke({ color: accent, width: 1, alpha: .7 });
      pulse.visible = false; this.roomHighlights.set(r.id, pulse); this.app.stage.addChild(pulse);

      if (r.id === "boss") rug(g, x + 43, y + 65, 108, 52, "#525040");

      if (r.id === "lounge") {
        this.lounge = createLoungeDecor(g, this.actors, this.skyline, chairBack);
      } else {
        for (const c of CAST.filter(character => character.room === r.id)) {
          const p = STATION[c.id], width = c.id === "command" ? 74 : 56;
          chairBack(g, p, c.rank === "director" ? "#766047" : "#526772");
          deskBack(g, p, width); monitor(g, glow, p, accent);
          const front = new Graphics(); deskFront(front, p, width, accent);
          this.foreground(front, p.y);
        }
      }
      if (r.id !== "lounge") cachedLightPool(g, x + r.w / 2, y + r.h * .55,
        r.w * .36, r.h * .2, r.id === "brain" ? "#b6a0da" : "#e6d3ac", .04);
      switch (r.id) {
        case "boss":
          this.window(g, x + 55, y + 19, 78);
          shelf(g, x + 10, y + 23, 25, 35); plant(g, x + 165, y + 61, true);
          box(g, x + 152, y + 21, 22, 21, "#66594d");
          px(g, x + 155, y + 24, 16, 15, "#cfb685"); px(g, x + 162, y + 27, 2, 10, "#695c49");
          break;
        case "brain":
          rug(g, x + 45, y + 54, 175, 112, "#424759");
          this.window(g, x + 18, y + 21, 29); this.window(g, x + r.w - 48, y + 21, 29);
          shelf(g, x + 9, y + 59, 30, 46); shelf(g, x + r.w - 40, y + 61, 29, 45);
          plant(g, x + 21, y + 142, true); plant(g, x + r.w - 27, y + 143, true);
          // Archive cabinets flank the pedestal and never masquerade as performance data.
          for (const dx of [43, 206]) {
            box(g, x + dx, y + 127, 23, 28, "#54536a");
            for (let row = 0; row < 3; row++) { box(g, x + dx + 2, y + 130 + row * 7, 19, 5, "#373e53"); px(g, x + dx + 10, y + 132 + row * 7, 4, 1, "#aea3ba"); }
          }
          this.core.container.position.set(CORE_AT.x, CORE_AT.y);
          break;
        case "workspace": {
          rug(g, x + 24, y + 26, r.w - 48, 62, "#43616a");
          for (const dy of [42, 76]) for (const dx of [58, 90, 122]) {
            box(g, x + dx, y + dy, 16, 11, "#63838b"); px(g, x + dx + 2, y + dy + 1, 12, 2, "#95b0b3", .4);
          }
          box(g, x + 43, y + 51, 105, 22, WOOD); px(g, x + 45, y + 52, 101, 2, "#e0bd95");
          box(g, x + 68, y + 57, 12, 7, "#d8d3c3"); box(g, x + 112, y + 59, 5, 5, "#ddd4bb");
          this.window(g, x + 51, y + 16, 91); plant(g, x + 13, y + 44); plant(g, x + r.w - 20, y + 43);
          break;
        }
        case "system":
          for (const dx of [14, 65]) {
            box(g, x + dx, y + 23, 42, 39, "#465261");
            px(g, x + dx + 2, y + 25, 38, 2, "#91a0a8", .5);
            for (let j = 0; j < 4; j++) {
              box(g, x + dx + 4, y + 29 + j * 7, 34, 5, "#263549");
              this.rackLamps.push({ x: x + dx + 7, y: y + 31 + j * 7 });
              px(g, x + dx + 13, y + 31 + j * 7, 18, 1, "#718395", .6);
            }
          }
          shelf(g, x + 146, y + 22, 43, 34); break;
        case "schedule":
          box(g, x + 32, y + 26, 144, 36, "#beaf8e"); px(g, x + 35, y + 29, 138, 5, "#877464");
          for (let row = 0; row < 2; row++) for (let col = 0; col < 9; col++)
            box(g, x + 39 + col * 14, y + 39 + row * 10, 10, 7, "#e0d2b4", "#a49880");
          plant(g, x + 21, y + 88, true); plant(g, x + r.w - 31, y + 91, true); break;
        case "dock":
          for (const [dx, dy, w] of [[13, 28, 21], [40, 36, 24], [17, 48, 23]]) {
            box(g, x + dx, y + dy, w, 18, "#ae8e69"); px(g, x + dx + Math.floor(w / 2), y + dy + 1, 2, 15, "#dac396");
            box(g, x + dx + 3, y + dy + 4, 6, 5, "#d6cfb5");
          }
          this.window(g, x + 86, y + 26, 79); break;
        case "discover":
          this.window(g, x + 67, y + 22, 65); this.window(g, x + 170, y + 22, 65);
          plant(g, x + 16, y + 59, true); shelf(g, x + r.w - 36, y + 22, 25, 30); break;
        case "analyze":
          for (let j = 0; j < 3; j++) {
            box(g, x + 38 + j * 73, y + 23, 51, 20, "#738491");
            px(g, x + 41 + j * 73, y + 26, 45, 14, "#273d51");
            px(g, x + 47 + j * 73, y + 30, 10, 6, "#9ebdc2", .45);
            px(g, x + 62 + j * 73, y + 30, 18, 1, "#a3b5bc", .45);
          }
          break;
        case "studio":
          shelf(g, x + 11, y + 20, 35, 30);
          for (let j = 0; j < 3; j++) {
            box(g, x + 82 + j * 62, y + 23, 43, 21, "#666077");
            box(g, x + 85 + j * 62, y + 26, 37, 15, "#253748");
            for (const dx of [0, 5, 10]) px(g, x + 88 + j * 62 + dx, y + 28, 3, 2, "#bc94b0", .65);
          }
          break;
        case "caption":
          shelf(g, x + 16, y + 23, 40, 34); shelf(g, x + 152, y + 23, 40, 34);
          box(g, x + 78, y + 24, 48, 26, "#88758a"); px(g, x + 81, y + 27, 42, 20, "#dbd0bd");
          for (const dy of [32, 38, 43]) px(g, x + 87, y + dy, dy === 43 ? 22 : 30, 1, "#726579");
          break;
        default: break;
      }
    }
    // Cache all static floor, furniture backs and ambient lighting once.
    g.cacheAsTexture({ resolution: 1, antialias: false });
    if (this.lounge) this.app.stage.addChild(this.lounge.container);
    this.app.stage.addChild(this.core.container, this.racks, this.selector, this.actors, this.transfers);
    for (const c of CAST) {
      const art = createRobot(c); art.container.scale.set(ROBOT_SCALE);
      this.robots.set(c.id, art); this.actors.addChild(art.container);
    }
  }

  draw(snap: Snapshot, actors: SceneActor[], t: number, still: boolean, pulseUntil: Map<RoomId, number>,
    coreBusy: boolean, offline = false, handoffs: SceneHandoff[] = []) {
    if (this.destroyed) return;
    const busy = new Set(snap.roles.filter(r => r.state === "working" && BY_ID[r.id]).map(r => BY_ID[r.id].room));
    for (const [id, lights] of this.lights) lights.alpha = busy.has(id) && !offline ? .9 : .22;
    for (const [id, highlight] of this.roomHighlights) {
      const until = pulseUntil.get(id) || 0;
      highlight.visible = until > t;
      highlight.alpha = still ? .5 : Math.min(.7, Math.max(0, (until - t) / 900));
    }
    const mode = offline ? "offline" : ["paused", "pausing"].includes(snap.run.state) || snap.brain?.state === "paused" ? "paused"
      : coreBusy || busy.has("brain") ? "active" : "standby";
    this.core.update(t, still, mode);
    this.lounge?.update(t, still || offline || ["paused", "pausing"].includes(snap.run.state));
    this.racks.clear();
    const colors: Record<string, string> = { healthy: "#8bbc96", degraded: "#dcc080", error: "#e08788", unknown: "#71849c" };
    for (let j = 0; j < Math.min(this.rackLamps.length, snap.health.checks.length); j++) {
      const p = this.rackLamps[j];
      px(this.racks, p.x, p.y, 3, 2, offline ? colors.unknown : colors[snap.health.checks[j].status] || colors.unknown);
    }
    this.selector.clear();
    const present = new Set(actors.map(a => a.id));
    for (const [id, art] of this.robots) art.container.visible = present.has(id);
    for (const actor of actors) {
      const art = this.robots.get(actor.id);
      if (!art) continue;
      art.container.position.set(Math.round(actor.x), Math.round(actor.y));
      art.container.zIndex = actor.y;
      art.animate(actor.pose, t, still, actor.dir, actor.posture || "stand", actor.breakActivity, actor.breakPhase || 0);
      if (actor.selected) {
        const x = Math.round(actor.x), y = Math.round(actor.y);
        this.selector.poly([x - 19, y - 4, x, y - 8, x + 19, y - 4, x, y + 3])
          .fill({ color: "#c9b98c", alpha: .14 }).stroke({ color: "#e5cf96", width: 1 });
      }
    }
    // The single card exists only during the controller's genuine pass phase; it never invents a handoff.
    this.transfers.clear();
    for (const handoff of handoffs) {
      const p = Math.max(0, Math.min(1, handoff.progress));
      const x = Math.round(handoff.from.x + (handoff.to.x - handoff.from.x) * p);
      const y = Math.round(handoff.from.y + (handoff.to.y - handoff.from.y) * p - 22 - Math.sin(Math.PI * p) * 3);
      if (!still && p > .1 && p < .9) {
        const dx = Math.sign(handoff.to.x - handoff.from.x);
        px(this.transfers, x - dx * 10 - 2, y, 4, 1, "#d8cbb0", .3);
        px(this.transfers, x - dx * 7 - 1, y - 2, 3, 1, "#d8cbb0", .5);
      }
      box(this.transfers, x - 5, y - 5, 10, 10, "#efe4c9", "#263142");
      px(this.transfers, x - 3, y - 3, 6, 2, "#ad89c3");
      px(this.transfers, x - 3, y + 1, 5, 1, "#74818a");
    }
    this.app.renderer.render(this.app.stage);
  }
  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.core.destroy();
    this.app.destroy(false, { children: true });
    for (const texture of this.croppedTextures) texture.destroy(false);
    this.lounge?.destroy();
  }
}
