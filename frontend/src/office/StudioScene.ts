/** PixiJS scene for the refined pixel office. Every animated work cue comes from the live feed. */
import { Application, Container, Graphics } from "pixi.js";
import { CAST, BY_ID, Dir, RoomId } from "./cast";
import { ROOM_ACCENT } from "./draw";
import { Snapshot } from "./api";
import { CORE_AT, ENTRANCE, ROOM, ROOMS, STATION, WORLD } from "./world";
import { Pose } from "./sprites";
import { createRobot } from "./StudioArt";

export interface SceneActor { id: string; x: number; y: number; pose: Pose; dir: Dir; selected: boolean }
type RobotArt = ReturnType<typeof createRobot>;
const INK = "#101925", WOOD = "#bb9672", WOOD_EDGE = "#886b52";
const FLOOR: Record<RoomId, string> = {
  lounge: "#3d383d", boss: "#303a4b", brain: "#353449", discover: "#30433f", workspace: "#35414a",
  analyze: "#344157", studio: "#433543", system: "#3d403c", caption: "#38364d", schedule: "#494038", dock: "#30433e",
};

const px = (g: Graphics, x: number, y: number, w: number, h: number, color: string, alpha = 1) => {
  g.rect(Math.round(x), Math.round(y), w, h).fill({ color, alpha });
};
const box = (g: Graphics, x: number, y: number, w: number, h: number, color: string, edge = INK) => {
  px(g, x, y, w, h, edge); px(g, x + 1, y + 1, w - 2, h - 2, color);
};
function plant(g: Graphics, x: number, y: number, tall = false) {
  px(g, x - 5, y + 7, 16, 3, "#07101b", 0.3);
  box(g, x - 1, y, 11, 9, "#b77d59"); px(g, x, y + 1, 9, 2, "#dfb18e");
  px(g, x + 3, y - (tall ? 20 : 12), 2, tall ? 22 : 14, "#77995e");
  const crown = tall ? [[-7, -22, 9, 7], [3, -27, 8, 8], [7, -15, 9, 6], [-6, -12, 9, 6]]
    : [[-4, -10, 7, 6], [3, -15, 7, 7], [6, -8, 7, 5]];
  for (const [dx, dy, w, h] of crown) {
    box(g, x + dx, y + dy, w, h, "#537a58", "#233e38");
    px(g, x + dx + 1, y + dy + 1, w - 3, 2, "#91b47a");
  }
}
function desk(g: Graphics, x: number, y: number, w: number, accent: string) {
  px(g, x + 3, y + 12, w + 2, 6, "#07101b", 0.28);
  box(g, x, y + 3, w, 13, WOOD_EDGE);
  px(g, x + 2, y + 4, w - 4, 2, "#e1ba90");
  box(g, x - 2, y - 1, w + 4, 9, WOOD);
  px(g, x, y, w, 2, "#e3c09b");
  px(g, x + 3, y + 3, w - 8, 1, "#b18b67");
  px(g, x + 4, y + 15, 3, 5, "#252b35"); px(g, x + w - 7, y + 15, 3, 5, "#252b35");
  px(g, x + w - 10, y + 9, 4, 2, accent, 0.65);
}
function monitor(g: Graphics, lights: Graphics, x: number, y: number, accent: string, w = 21) {
  px(g, x + 3, y + 15, w - 1, 3, "#0d1827", 0.25);
  box(g, x, y, w, 15, "#38465a"); px(g, x + 2, y + 2, w - 4, 10, "#112338");
  px(g, x + 1, y + 1, w - 2, 1, "#728294");
  px(g, x + Math.floor(w / 2) - 1, y + 15, 3, 3, "#273343");
  px(g, x + Math.floor(w / 2) - 5, y + 18, 11, 2, "#556070");
  px(lights, x + 3, y + 3, w - 6, 7, accent, 0.19);
  // A powered screen is a room-activity cue, never an invented chart or progress meter.
  px(lights, x + 4, y + 5, 3, 2, accent, 0.75);
  px(lights, x + w - 4, y + 12, 1, 1, accent);
}
function shelf(g: Graphics, x: number, y: number, w = 20) {
  box(g, x, y, w, 26, "#70605c");
  const books = ["#c77c72", "#b9a075", "#709db2", "#779c82", "#a190b4"];
  for (let row = 0; row < 2; row++) {
    px(g, x + 1, y + 12 + row * 12, w - 2, 2, "#433b41");
    for (let j = 0; j < 4; j++) {
      const yy = y + 3 + row * 12 + j % 2;
      px(g, x + 3 + j * 4, yy, 3, 9 - j % 2, books[(j + row) % books.length]);
      px(g, x + 3 + j * 4, yy + 2, 1, 1, "#e4d5b0");
    }
  }
}
function rug(g: Graphics, x: number, y: number, w: number, h: number, color: string) {
  box(g, x, y, w, h, color, "#232a36");
  px(g, x + 3, y + 3, w - 6, 1, "#ede1c0", 0.18);
  px(g, x + 3, y + h - 4, w - 6, 1, "#ede1c0", 0.18);
}

export class StudioScene {
  private app: Application;
  private robots = new Map<string, RobotArt>();
  private lights = new Map<RoomId, Graphics>();
  private roomHighlights = new Map<RoomId, Graphics>();
  private selector = new Graphics();
  private racks = new Graphics();
  private core = new Container();
  private actors = new Container();
  private destroyed = false;

  private constructor(app: Application) { this.app = app; }

  static async create(canvas: HTMLCanvasElement): Promise<StudioScene> {
    const app = new Application();
    try {
      await app.init({ canvas, width: WORLD.w, height: WORLD.h, resolution: 1, antialias: false,
        autoStart: false, preference: "webgl", preserveDrawingBuffer: true, backgroundAlpha: 0,
        powerPreference: "low-power" });
      const scene = new StudioScene(app);
      scene.build();
      return scene;
    } catch (error) {
      // Context creation can fail on a browser/driver; the caller restores the existing Canvas renderer.
      try { app.destroy(false, { children: true }); } catch { /* init may not have completed */ }
      throw error;
    }
  }

  private build() {
    const g = new Graphics();
    this.app.stage.addChild(g);
    px(g, 0, 0, WORLD.w, WORLD.h, "#1b2738");
    // Quiet stone corridor, with small inset lighting and no high-contrast checkerboard.
    for (let y = 0; y < WORLD.h; y += 16) for (let x = 0; x < WORLD.w; x += 24) {
      px(g, x + 1, y + 1, 23, 15, "#263449");
      if ((x / 24 + y / 16) % 4 === 0) px(g, x + 3, y + 3, 4, 1, "#465264", 0.18);
    }
    for (const r of ROOMS) {
      const a = ROOM_ACCENT[r.id], x = r.x, y = r.y;
      px(g, x + 4, y + 6, r.w, r.h, "#090f1a", 0.35);
      box(g, x, y, r.w, r.h, FLOOR[r.id], "#172234");
      // Floor planks and a bevel give each room depth, with the names remaining readable above.
      for (let yy = y + 20; yy < y + r.h - 1; yy += 12) {
        px(g, x + 3, yy, r.w - 6, 1, "#132333", 0.18);
        for (let xx = x + 18 + ((yy - y) % 24 ? 0 : 20); xx < x + r.w - 3; xx += 40)
          px(g, xx, yy - 10, 1, 10, "#182536", 0.12);
      }
      px(g, x + 1, y + 1, r.w - 2, 7, "#43516a");
      px(g, x + 1, y + 1, r.w - 2, 1, "#788397", 0.6);
      px(g, x + 1, y + 7, r.w - 2, 3, "#19283b");
      px(g, x + 1, y + 10, 3, r.h - 11, "#4d5a70");
      px(g, x + r.w - 4, y + 10, 3, r.h - 11, "#23344a");
      px(g, x + 4, y + r.h - 3, r.w - 8, 2, "#1c2b3e");
      px(g, x + 6, y + 10, r.w - 12, 1, a, 0.28);
      const glow = new Graphics();
      px(glow, x + 6, y + 11, r.w - 12, 3, a, 0.12);
      px(glow, x + 6, y + 11, r.w - 12, 1, a, 0.45);
      this.lights.set(r.id, glow);
      this.app.stage.addChild(glow);
      const pulse = new Graphics();
      pulse.rect(x + 2, y + 2, r.w - 4, r.h - 4).stroke({ color: a, width: 1, alpha: 0.7 });
      pulse.visible = false;
      this.roomHighlights.set(r.id, pulse);
      this.app.stage.addChild(pulse);
      // Rooms have curated role-specific furniture, rather than a shelf in every corner.
      const ids = CAST.filter(c => c.room === r.id);
      for (const c of ids) {
        const at = STATION[c.id];
        desk(g, at.x - 19, y + 42, 38, a);
        monitor(g, glow, at.x - 11, y + 22, a);
        // Small keyboard and a cast-colored desk mat.
        box(g, at.x - 10, y + 39, 19, 4, "#657180");
        for (let j = 0; j < 5; j++) px(g, at.x - 8 + j * 3, y + 40, 2, 1, "#bcc3c9");
      }
      switch (r.id) {
        case "lounge": {
          rug(g, x + 30, y + 47, 164, 32, "#49605e");
          px(g, x + 44, y + 30, 132, 14, "#152132", 0.3);
          box(g, x + 40, y + 26, 128, 18, "#ac6d68");
          px(g, x + 44, y + 27, 120, 3, "#d29b88");
          for (let j = 0; j < 3; j++) box(g, x + 48 + j * 36, y + 35, 32, 12, "#c18175");
          box(g, x + 39, y + 32, 8, 20, "#945e61"); box(g, x + 164, y + 32, 8, 20, "#945e61");
          desk(g, x + 92, y + 62, 46, "#cba878");
          box(g, x + 103, y + 59, 6, 5, "#e1cab2");
          plant(g, x + 16, y + 81, true); shelf(g, x + r.w - 27, y + 28);
          px(g, x + 21, y + 30, 2, 27, "#987c61"); box(g, x + 14, y + 25, 15, 9, "#ddbd88");
          break;
        }
        case "boss": {
          box(g, x + 30, y + 21, 18, 23, "#252d42");
          px(g, x + 34, y + 25, 10, 3, "#b39a67"); px(g, x + 38, y + 28, 2, 11, "#b39a67");
          plant(g, x + r.w - 20, y + 79, true);
          shelf(g, x + 9, y + 23, 20);
          break;
        }
        case "brain": {
          const crystal = new Graphics();
          box(g, CORE_AT.x - 17, CORE_AT.y + 2, 34, 10, "#404259");
          px(g, CORE_AT.x - 15, CORE_AT.y + 4, 30, 2, "#76708e");
          px(crystal, -9, -29, 18, 30, "#c4a8ff", 0.1);
          box(crystal, -8, -23, 16, 25, "#8870b5", "#3d355d");
          px(crystal, -5, -20, 5, 18, "#cbb9ec"); px(crystal, 1, -17, 4, 15, "#ad8de0");
          px(crystal, -5, -22, 10, 2, "#ece1ff");
          this.core.addChild(crystal); this.core.position.set(CORE_AT.x, CORE_AT.y);
          shelf(g, x + 5, y + 24, 18); plant(g, x + r.w - 13, y + 79);
          break;
        }
        case "workspace": {
          rug(g, x + 19, y + 30, r.w - 38, 61, "#405b64");
          desk(g, x + 45, y + 57, r.w - 90, "#6d9da0");
          for (let j = 0; j < 3; j++) {
            box(g, x + 54 + j * 31, y + 38, 15, 14, "#68828b");
            box(g, x + 54 + j * 31, y + 74, 15, 12, "#526c77");
          }
          box(g, x + 64, y + 23, 64, 13, "#907b65"); px(g, x + 67, y + 25, 58, 8, "#d6c29b");
          plant(g, x + 14, y + 33); plant(g, x + r.w - 20, y + 33);
          box(g, x + 73, y + 54, 12, 6, "#ddd4c4");
          break;
        }
        case "system": {
          for (const dx of [184, 205]) {
            box(g, x + dx, y + 23, 16, 39, "#3b4759");
            for (let j = 0; j < 4; j++) { box(g, x + dx + 2, y + 26 + j * 8, 12, 6, "#202e42"); }
          }
          break;
        }
        case "schedule": {
          box(g, x + 146, y + 26, 55, 35, "#cab692");
          px(g, x + 148, y + 28, 51, 5, "#8e7160");
          for (let row = 0; row < 3; row++) for (let col = 0; col < 7; col++)
            px(g, x + 150 + col * 7, y + 36 + row * 7, 5, 5, "#ead9b8");
          plant(g, x + 16, y + 77, true);
          break;
        }
        case "dock": {
          for (const [dx, dy] of [[16, 29], [29, 36], [15, 46]]) {
            box(g, x + dx, y + dy, 11, 10, "#b08c66"); px(g, x + dx + 5, y + dy + 1, 2, 8, "#dbc293");
          }
          px(g, x + 7, y + 60, 218, 2, "#8bac8a", 0.3);
          break;
        }
        case "discover": plant(g, x + 16, y + 76, true); break;
        case "caption": shelf(g, x + 7, y + 28, 21); break;
        case "studio": {
          box(g, x + 10, y + 28, 15, 20, "#4c435b");
          for (let j = 0; j < 4; j++) px(g, x + 11, y + 30 + j * 4, 2, 2, "#c0a0b4");
          break;
        }
        default: break;
      }
    }
    const e = ENTRANCE;
    rug(g, e.x + 28, e.y + 42, e.w - 56, 46, "#374353");
    box(g, e.x + 74, e.y + 22, 44, 48, "#455a72");
    box(g, e.x + 79, e.y + 27, 34, 42, "#23364b");
    px(g, e.x + 83, e.y + 31, 10, 30, "#7aadb8", 0.58);
    px(g, e.x + 97, e.y + 31, 10, 30, "#7aadb8", 0.58);
    box(g, e.x + 77, e.y + 18, 38, 7, "#b09771");
    plant(g, e.x + 35, e.y + 52, true); plant(g, e.x + e.w - 42, e.y + 52, true);
    // The furnished floor never changes. Render it once instead of replaying every plank/desk at each frame.
    g.cacheAsTexture({ resolution: 1, antialias: false });
    this.app.stage.addChild(this.core, this.racks, this.selector, this.actors);
    this.actors.sortableChildren = true;
    for (const c of CAST) {
      const robot = createRobot(c);
      this.robots.set(c.id, robot);
      this.actors.addChild(robot.container);
    }
  }

  draw(snap: Snapshot, actors: SceneActor[], t: number, still: boolean, pulseUntil: Map<RoomId, number>, coreBusy: boolean) {
    if (this.destroyed) return;
    const busy = new Set(snap.roles.filter(r => r.state === "working" && BY_ID[r.id]).map(r => BY_ID[r.id].room));
    for (const [id, lights] of this.lights) lights.alpha = busy.has(id) ? 0.9 : 0.24;
    for (const [id, highlight] of this.roomHighlights) {
      const until = pulseUntil.get(id) || 0;
      highlight.visible = until > t;
      highlight.alpha = still ? 0.5 : Math.min(0.7, Math.max(0, (until - t) / 900));
    }
    this.core.alpha = coreBusy ? 1 : 0.75;
    this.core.y = CORE_AT.y + (coreBusy && !still ? Math.round(Math.sin(t / 400)) : 0);
    this.racks.clear();
    const sy = ROOM.system;
    const colors: Record<string, string> = { healthy: "#8bbc96", degraded: "#dcc080", error: "#e08788", unknown: "#71849c" };
    for (let j = 0; j < Math.min(8, snap.health.checks.length); j++)
      px(this.racks, sy.x + (j < 4 ? 194 : 215), sy.y + 28 + (j % 4) * 8, 2, 2,
        colors[snap.health.checks[j].status] || colors.unknown);
    this.selector.clear();
    const present = new Set(actors.map(a => a.id));
    for (const [id, art] of this.robots) art.container.visible = present.has(id);
    for (const actor of actors) {
      const art = this.robots.get(actor.id);
      if (!art) continue;
      art.container.position.set(Math.round(actor.x), Math.round(actor.y));
      art.container.zIndex = actor.y;
      art.animate(actor.pose, t, still, actor.dir);
      if (actor.selected) {
        const x = Math.round(actor.x), y = Math.round(actor.y);
        this.selector.poly([x - 21, y - 4, x, y - 10, x + 21, y - 4, x, y + 3]).fill({ color: "#c9b98c", alpha: 0.13 })
          .stroke({ color: "#e5cf96", width: 1 });
      }
    }
    this.app.renderer.render(this.app.stage);
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.app.destroy(false, { children: true });
  }
}
