/** Canvas compatibility scene: the same workplaces, lounge activities and genuine document transfers. */
import { BY_ID, CAST } from "./cast";
import { Snapshot } from "./api";
import { drawRobot, ROOM_ACCENT, spriteCanvas } from "./draw";
import { BREAK_SPOTS, CORE_AT, ROBOT_SCALE, ROOM, ROOMS, STATION, WORLD } from "./world";
import { FRAMES, frameMs } from "./sprites";
import type { SceneActor } from "./StudioScene";
import type { DocumentPass } from "./OfficeMotion";

type Ctx = CanvasRenderingContext2D;
type Pair = readonly [number, number];
const BRAIN_LOBE: Pair[] = [
  [-2, -22], [-10, -22], [-10, -26], [-20, -26], [-20, -23], [-26, -23], [-26, -18],
  [-31, -18], [-31, -11], [-35, -11], [-35, 3], [-32, 3], [-32, 11], [-27, 11],
  [-27, 17], [-20, 17], [-20, 21], [-12, 21], [-12, 18], [-5, 18], [-5, 14], [-2, 14],
];
const LEFT_CIRCUITS: Pair[][] = [
  [[-27, -14], [-21, -14], [-21, -7], [-12, -7], [-12, -13], [-6, -13]],
  [[-30, -6], [-25, -6], [-25, 1], [-17, 1], [-17, -2], [-9, -2]],
  [[-29, 7], [-22, 7], [-22, 12], [-14, 12], [-14, 7], [-7, 7]],
];
const NEURAL_PATHS = [...LEFT_CIRCUITS, ...LEFT_CIRCUITS.map(points => points.map(([x, y]): Pair => [-x, y]))];
const pixel = (c: Ctx, x: number, y: number, w: number, h: number, color: string) => {
  c.fillStyle = color; c.fillRect(Math.round(x), Math.round(y), w, h);
};
function box(c: Ctx, x: number, y: number, w: number, h: number, color: string, edge = "#192737") {
  pixel(c, x, y, w, h, edge); pixel(c, x + 1, y + 1, w - 2, h - 2, color);
}
function plant(c: Ctx, x: number, y: number) {
  box(c, x - 5, y - 1, 12, 9, "#ad8260");
  pixel(c, x, y - 22, 2, 24, "#76916b");
  for (const [dx, dy, w, h] of [[-8, -21, 8, 7], [2, -25, 8, 8], [5, -15, 8, 6], [-6, -11, 7, 6]]) {
    box(c, x + dx, y + dy, w, h, "#638d69", "#314c44");
    pixel(c, x + dx + 1, y + dy + 1, w - 3, 1, "#a3bd80");
  }
}

export class LivingFallback {
  private floor = document.createElement("canvas");
  private skyline: HTMLImageElement | null = null;
  private image: HTMLImageElement | null = null;
  private destroyed = false;
  private brainPhase = 0;
  private brainBusy = false;
  private lastActualBrainBusy: boolean | undefined;
  private brainSuppressed = false;
  private lastDraw: number | undefined;

  constructor(private ctx: Ctx) {
    this.floor.width = WORLD.w; this.floor.height = WORLD.h;
    this.buildFloor();
    const image = new Image(); this.image = image;
    image.onload = () => {
      if (this.destroyed) return;
      this.skyline = image; this.buildFloor(); image.onload = null; image.onerror = null;
    };
    image.onerror = () => { image.onload = null; image.onerror = null; };
    image.src = "/office-art/skyline.png";
  }

  private window(c: Ctx, x: number, y: number, w: number, h = 19) {
    box(c, x - 2, y - 2, w + 4, h + 5, "#203344");
    pixel(c, x, y, w, h, "#557c87");
    pixel(c, x + 1, y + 1, w - 2, Math.max(4, Math.floor(h / 3)), "#9cbdb9");
    if (this.skyline) {
      const image = this.skyline;
      const sh = Math.min(image.height, image.width * h / w), sw = sh * w / h;
      const sx = x / WORLD.w * (image.width - sw), sy = (image.height - sh) * .3;
      c.drawImage(image, sx, sy, sw, sh, x, y, w, h);
    } else {
      for (let i = 0; i < Math.floor(w / 7); i++) {
        const hh = 4 + i * 7 % 9;
        pixel(c, x + i * 7, y + h - hh, 6, hh, i % 2 ? "#385966" : "#426774");
      }
    }
    pixel(c, x + Math.floor(w / 2), y, 2, h, "#84969a");
    pixel(c, x, y + Math.floor(h / 2), w, 1, "#84969a");
    pixel(c, x - 3, y + h, w + 6, 3, "#a2a59b");
  }

  private buildFloor() {
    const c = this.floor.getContext("2d")!;
    c.imageSmoothingEnabled = false; c.clearRect(0, 0, WORLD.w, WORLD.h);
    pixel(c, 0, 0, WORLD.w, WORLD.h, "#243348");
    for (let y = 0; y < WORLD.h; y += 16) for (let x = 0; x < WORLD.w; x += 24)
      pixel(c, x + 1, y + 1, 23, 15, "#29384b");
    for (const room of ROOMS) {
      box(c, room.x, room.y, room.w, room.h, room.id === "lounge" ? "#384543" : "#354151", "#172335");
      pixel(c, room.x + 1, room.y + 1, room.w - 2, 7, "#536074");
      pixel(c, room.x + 2, room.y + 2, room.w - 4, 1, "#869099");
      pixel(c, room.x + 4, room.y + 11, room.w - 8, 2, ROOM_ACCENT[room.id]);
      for (let y = room.y + 30; y < room.y + room.h - 4; y += 16) {
        pixel(c, room.x + 4, y, room.w - 8, 1, "#293646");
        for (let x = room.x + 14 + (y % 32 ? 16 : 0); x < room.x + room.w - 4; x += 40)
          pixel(c, x, y - 14, 1, 14, "#2e3c49");
      }
      if (room.id !== "lounge") this.window(c, room.x + room.w - 66, room.y + 21, 47);
    }
    this.loungeFloor(c);
    for (const character of CAST) {
      const desk = STATION[character.id];
      box(c, desk.x - 13, desk.y - 32, 26, 34, "#394f61");
      pixel(c, desk.x - 11, desk.y - 30, 22, 17, "#647c8b");
      pixel(c, desk.x - 7, desk.y - 30, 1, 15, "#7c939e");
      box(c, desk.x - 29, desk.y - 25, 58, 10, "#b69c7d");
      pixel(c, desk.x - 27, desk.y - 24, 54, 2, "#dfc49b");
      pixel(c, desk.x - 26, desk.y - 15, 3, 10, "#3c3d45");
      pixel(c, desk.x + 23, desk.y - 15, 3, 10, "#3c3d45");
      box(c, desk.x - 13, desk.y - 47, 26, 19, "#19283b");
      pixel(c, desk.x - 12, desk.y - 46, 24, 1, "#8298aa");
      pixel(c, desk.x - 10, desk.y - 43, 20, 12, "#294657");
      pixel(c, desk.x - 1, desk.y - 28, 3, 4, "#516777");
      pixel(c, desk.x - 8, desk.y - 25, 18, 2, "#738491");
      pixel(c, desk.x + 17, desk.y - 23, 6, 4, "#ddd1b9");
    }
    for (const room of ROOMS.filter(r => r.id !== "lounge")) plant(c, room.x + 19, room.y + 58);
  }

  private loungeFloor(c: Ctx) {
    const { x, y } = ROOM.lounge;
    box(c, x + 15, y + 99, 286, 101, "#4c615b", "#2b3737");
    pixel(c, x + 19, y + 103, 278, 1, "#849286");
    box(c, x + 12, y + 212, 372, 41, "#485c60", "#293840");
    for (const spot of BREAK_SPOTS.filter(s => s.activity === "arcade")) {
      const xx = spot.at.x;
      box(c, xx - 19, y + 20, 38, 47, "#455168");
      pixel(c, xx - 17, y + 21, 34, 5, "#bcaa79");
      pixel(c, xx - 15, y + 23, 30, 1, "#e8d6a5");
      box(c, xx - 15, y + 28, 30, 23, "#11263b");
      pixel(c, xx - 10, y + 34, 4, 3, "#89bda5");
      pixel(c, xx + 5, y + 34, 4, 3, "#c39dcc");
      pixel(c, xx - 3, y + 43, 7, 2, "#dcc987");
      box(c, xx - 19, y + 53, 38, 8, "#697b86");
      pixel(c, xx - 9, y + 53, 3, 4, "#d2bd83");
      pixel(c, xx + 6, y + 55, 3, 2, "#a0bc9a");
      pixel(c, xx - 5, y + 63, 10, 2, "#24384a");
    }
    // A café and shared games replace a grid of unrelated armchairs.
    this.window(c, x + 248, y + 20, 146, 20);
    box(c, x + 238, y + 44, 168, 23, "#806b5d");
    pixel(c, x + 240, y + 45, 164, 4, "#c7b28d");
    for (const xx of [246, 286, 326, 366]) {
      box(c, x + xx, y + 52, 32, 12, "#927d65");
      pixel(c, x + xx + 13, y + 55, 6, 1, "#d1bd93");
    }
    box(c, x + 245, y + 24, 20, 20, "#465666");
    pixel(c, x + 248, y + 26, 14, 4, "#90acb0");
    pixel(c, x + 250, y + 33, 3, 4, "#172b3a");
    box(c, x + 251, y + 38, 6, 5, "#e8dfc5");
    box(c, x + 284, y + 36, 19, 8, "#9a927c");
    pixel(c, x + 287, y + 36, 13, 2, "#ead2a0");
    box(c, x + 329, y + 39, 17, 4, "#d0cab0");
    pixel(c, x + 332, y + 37, 5, 3, "#bda675");
    plant(c, x + 386, y + 39);
    for (const spot of BREAK_SPOTS.filter(s => s.activity === "boardgame" && s.posture === "rest")) {
      box(c, spot.at.x - 17, spot.at.y - 30, 34, 30, "#49616a");
      pixel(c, spot.at.x - 15, spot.at.y - 28, 30, 12, "#789194");
      pixel(c, spot.at.x - 15, spot.at.y - 8, 30, 7, "#617b80");
    }
    for (const xx of [30, 186]) {
      box(c, x + xx, y + 108, 110, 41, "#b69f7e");
      pixel(c, x + xx + 2, y + 110, 106, 2, "#e1caa1");
      pixel(c, x + xx, y + 149, 110, 15, "#806851");
      pixel(c, x + xx + 6, y + 164, 5, 4, "#2b343d");
      pixel(c, x + xx + 98, y + 164, 5, 4, "#2b343d");
      box(c, x + xx + 24, y + 117, 34, 25, "#e0cfab");
      for (let row = 0; row < 4; row++) for (let col = 0; col < 5; col++)
        pixel(c, x + xx + 26 + col * 6, y + 119 + row * 5, 6, 5,
          (row + col) % 2 ? "#667d73" : "#c9bc97");
      for (const [dx, dy] of [[28, 122], [43, 132], [50, 123]]) box(c, x + xx + dx, y + dy, 4, 4, "#eedcba");
      box(c, x + xx + 71, y + 120, 12, 16, "#847698");
      box(c, x + xx + 79, y + 123, 12, 16, "#e1c6a6");
      pixel(c, x + xx + 83, y + 128, 4, 6, "#917c9c");
    }
    for (const xx of [13, 107, 201, 295]) {
      box(c, x + xx, y + 211, 85, 36, "#536e69");
      pixel(c, x + xx + 3, y + 212, 79, 3, "#8ea693");
      for (const dx of [7, 45]) {
        box(c, x + xx + dx, y + 216, 33, 15, "#6b8980");
        box(c, x + xx + dx, y + 232, 33, 11, "#78958a");
        pixel(c, x + xx + dx + 2, y + 233, 29, 1, "#a4b59d");
      }
      box(c, x + xx, y + 222, 6, 24, "#415d59");
      box(c, x + xx + 79, y + 222, 6, 24, "#415d59");
    }
  }

  private leisure(c: Ctx, a: SceneActor) {
    const activity = a.breakActivity;
    if (!activity || a.posture === "desk"
      || ["work", "review", "walk", "carry", "unavailable"].includes(a.pose)) return;
    const p = Math.max(0, Math.min(1, a.breakPhase || 0));
    const metal = BY_ID[a.id].palette;
    const side = a.dir === "left" ? -1 : 1;
    const seated = a.posture === "rest", cy = seated ? a.dir === "up" ? -29 : -18 : -28;
    const raise = Math.max(0, Math.sin((p - .13) * Math.PI * 2));
    if (activity === "drink") {
      const yy = cy - Math.round(raise * 12), xx = side * 10;
      box(c, xx - 4, yy - 4, 9, 9, "#e5dcc4");
      pixel(c, xx - 3, yy - 4, 7, 2, "#6c5447");
      box(c, xx + side * 5 - 1, yy - 2, 3, 5, "#c2b79d");
      pixel(c, xx - 5, yy + 3, 3, 4, metal.shade);
      pixel(c, xx - 4, yy - 9 - Math.round(p * 3), 1, 3, "#a7bcb5");
      pixel(c, xx + 1, yy - 11 + Math.round(p * 3), 1, 3, "#a7bcb5");
    } else if (activity === "snack") {
      const yy = cy - Math.round(raise * 10), xx = side * 8;
      box(c, -9, cy + 6, 18, 3, "#c9c3af");
      pixel(c, xx - 6, yy - 3, 13, 3, "#d2b480");
      pixel(c, xx - 5, yy, 11, 2, "#7e9c65");
      pixel(c, xx - 5, yy + 2, 11, 2, "#be7c65");
      pixel(c, xx - 6, yy + 4, 13, 3, "#ecd2a1");
      if (p > .34 && p < .7) pixel(c, xx + 4, yy - 3, 3, 3, metal.visor);
      pixel(c, xx - 7, yy + 3, 3, 4, metal.shade);
    } else if (activity === "read") {
      box(c, -11, cy - 6, 22, 15, "#a88574");
      pixel(c, -9, cy - 5, 8, 12, "#e4d8b7"); pixel(c, 1, cy - 5, 8, 12, "#d2c6a7");
      for (const dy of [-2, 1, 4]) {
        pixel(c, -7, cy + dy, 5, 1, "#a3a58e"); pixel(c, 2, cy + dy, 5, 1, "#a3a58e");
      }
      const page = p > .44 && p < .64;
      pixel(c, page ? Math.round((p - .44) * 32) - 3 : -1, cy - 5, page ? 3 : 2, 12, "#fbefd0");
      pixel(c, -13, cy + 3, 3, 4, metal.shade); pixel(c, 10, cy + 3, 3, 4, metal.shade);
    } else if (activity === "arcade") {
      const tap = p > .25 && p < .65 ? -2 : 0;
      box(c, -12, cy - 1, 24, 7, "#485b6d");
      pixel(c, -7, cy - 4 + tap, 2, 6, "#e0c58a");
      pixel(c, -9, cy - 5 + tap, 6, 2, "#bdad87");
      pixel(c, 4, cy + 1 + (tap ? 1 : 0), 3, 2, "#a7c69f");
      pixel(c, -14, cy + 1, 4, 4, metal.shade); pixel(c, 10, cy + tap, 4, 4, metal.shade);
    } else if (activity === "boardgame") {
      const reach = Math.round(Math.sin(p * Math.PI * 2) * 5);
      const xx = a.dir === "up" ? reach : side * (7 + reach);
      pixel(c, xx - 4, cy + 1, 5, 4, metal.shade);
      box(c, xx, cy - 3, 5, 5, "#eee5c9");
      pixel(c, xx + 1, cy - 2, 1, 1, "#6d7184"); pixel(c, xx + 3, cy, 1, 1, "#6d7184");
    } else if (activity === "rest") {
      pixel(c, -15, cy + 5, 7, 3, metal.shade); pixel(c, 8, cy + 5, 7, 3, metal.shade);
    }
  }

  private supervise(c: Ctx, a: SceneActor, frame: number) {
    if (!(a.duty === "supervising" || a.supervising) || BY_ID[a.id].rank !== "manager"
      || a.breakActivity || a.posture !== "stand"
      || !["idle", "wait", "retry"].includes(a.pose)) return;
    const metal = BY_ID[a.id].palette, side = a.dir === "left" ? -1 : 1;
    const x = side * 9, y = -28 - frame % 2;
    box(c, x - 5, y, 11, 15, "#e3d2b1");
    pixel(c, x - 3, y - 1, 7, 2, "#bca474");
    for (const dy of [4, 7, 10]) pixel(c, x - 2, y + dy, dy === 10 ? 4 : 6, 1, "#8b9290");
    pixel(c, x - 7, y + 8, 3, 4, metal.shade);
    pixel(c, -side * 12 - 2, -20, 5, 3, metal.shade);
  }

  draw(snap: Snapshot, actors: SceneActor[], time: number, still: boolean, busy: boolean,
    passes: DocumentPass[], offline = false) {
    if (this.destroyed) return;
    const delta = this.lastDraw === undefined ? 0 : Math.max(0, Math.min(time - this.lastDraw, 100));
    this.lastDraw = time;
    const paused = ["paused", "pausing"].includes(snap.run.state) || snap.brain?.state === "paused";
    const actualBrainBusy = snap.brain?.state === "evaluating"
      || snap.roles.some(r => BY_ID[r.id]?.room === "brain" && r.state === "working");
    if (paused || offline) this.brainBusy = false;
    else if (!still || this.lastActualBrainBusy === undefined || this.brainSuppressed) {
      this.brainBusy = busy || actualBrainBusy;
    } else if (actualBrainBusy !== this.lastActualBrainBusy) this.brainBusy = actualBrainBusy;
    this.lastActualBrainBusy = actualBrainBusy;
    this.brainSuppressed = paused || offline;
    // A cue expiring must not change a frozen sculpture's phase, geometry or color. Reduced may still
    // reflect a genuine job-state change; paused/offline artwork ignores transient cues entirely.
    if (!still && !paused && !offline) this.brainPhase += delta / (this.brainBusy ? 812.5 : 10666);
    const c = this.ctx; c.imageSmoothingEnabled = false; c.drawImage(this.floor, 0, 0);
    for (const a of actors) {
      const character = BY_ID[a.id], count = FRAMES[a.pose].n;
      const frame = still ? 0 : Math.floor(time / (frameMs(character, a.pose) || 400)) % count;
      c.save(); c.translate(Math.round(a.x), Math.round(a.y)); c.scale(ROBOT_SCALE, ROBOT_SCALE);
      if (a.posture === "stand" || !a.posture) drawRobot(c, a.id, 0, 0, a.dir, a.pose, frame, a.selected);
      else {
        // Retain each original identity's upper sprite, with bent legs under the seated torso.
        const upperHeight = character.rank === "director" ? 54 : character.rank === "manager" ? 55 : 56;
        c.drawImage(spriteCanvas(a.id, a.dir, a.pose, frame), 0, 0, 48, upperHeight,
          -24, -upperHeight - 13, 48, upperHeight);
        pixel(c, -11, -13, 9, 8, character.palette.shade); pixel(c, 3, -13, 9, 8, character.palette.shade);
        pixel(c, -13, -5, 12, 4, character.palette.trimDark); pixel(c, 2, -5, 12, 4, character.palette.trimDark);
      }
      // The controller owns every leisure phase. Wall time never advances a mug, page, bite or game piece.
      this.leisure(c, a); this.supervise(c, a, frame); c.restore();
    }
    for (const a of actors) if (a.posture === "desk") {
      pixel(c, a.x - 29, a.y - 21, 58, 7, "#c6ac88");
      pixel(c, a.x - 29, a.y - 14, 58, 5, "#8a7057");
      pixel(c, a.x - 11, a.y - 20, 22, 3, "#596c79");
    }
    this.brain(c, this.brainBusy, offline);
    for (const pass of passes) {
      const xx = Math.round(pass.from.x + (pass.to.x - pass.from.x) * pass.progress);
      const yy = Math.round(pass.from.y + (pass.to.y - pass.from.y) * pass.progress - 22);
      box(c, xx - 7, yy - 7, 14, 13, "#f0e3c4", "#1a2637");
      pixel(c, xx - 3, yy - 3, 7, 2, "#6d9fab");
    }
  }

  private brain(c: Ctx, busy: boolean, offline: boolean) {
    const phase = this.brainPhase;
    c.save(); c.globalAlpha = offline ? .55 : 1;
    const x = CORE_AT.x, y = CORE_AT.y - 82 + Math.round(Math.sin(phase * .5) * 2);
    box(c, x - 30, CORE_AT.y - 11, 60, 11, "#536379");
    box(c, x - 24, CORE_AT.y - 18, 48, 9, "#6c7c8d");
    box(c, x - 18, CORE_AT.y - 29, 36, 12, "#3e4e65");
    pixel(c, x - 16, CORE_AT.y - 28, 32, 2, "#b0b3c3");
    const lobes = () => {
      c.beginPath();
      for (const side of [-1, 1]) {
        c.moveTo(x + BRAIN_LOBE[0][0] * side, y + BRAIN_LOBE[0][1]);
        for (const [xx, yy] of BRAIN_LOBE.slice(1)) c.lineTo(x + xx * side, y + yy);
        c.closePath();
      }
    };
    const orbit = (i: number, front: boolean) => {
      const color = ["#e8d394", "#aaacf0", "#80c8cb"][i];
      c.save(); c.globalAlpha *= front ? .75 : .4; c.strokeStyle = color; c.lineWidth = 1;
      c.beginPath(); c.ellipse(x, y, 57, 12, (i - 1) * .45,
        front ? 0 : Math.PI, front ? Math.PI : Math.PI * 2); c.stroke(); c.restore();
      const angle = phase + i * Math.PI * 2 / 3;
      const normalized = (angle % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
      if ((normalized < Math.PI) !== front) return;
      const xx = Math.cos(angle) * 57, yy = Math.sin(angle) * 12, tilt = (i - 1) * .45;
      pixel(c, x + xx * Math.cos(tilt) - yy * Math.sin(tilt) - 1,
        y + xx * Math.sin(tilt) + yy * Math.cos(tilt) - 1, 3, 3, color);
    };
    for (let i = 0; i < 3; i++) orbit(i, false);
    lobes(); c.fillStyle = busy ? "#b5a6df" : "#9695bd"; c.fill();
    c.strokeStyle = "#484967"; c.lineWidth = 2; c.stroke();
    pixel(c, x - 20, y - 25, 10, 2, "#dbcbf2"); pixel(c, x + 10, y - 25, 10, 2, "#d9e0ee");
    pixel(c, x - 1, y - 20, 2, 34, "#535371");
    pixel(c, x, y - 18, 1, 29, "#dcd3ed");
    for (let i = 0; i < NEURAL_PATHS.length; i++) {
      const path = NEURAL_PATHS[i];
      c.beginPath(); c.moveTo(x + path[0][0], y + path[0][1]);
      for (const [xx, yy] of path.slice(1)) c.lineTo(x + xx, y + yy);
      c.strokeStyle = "#5c6e88"; c.lineWidth = 3; c.stroke();
      c.strokeStyle = busy ? "#adeadb" : "#a0c6ce"; c.lineWidth = 1; c.stroke();
      if (busy) {
        const segment = (phase * 1.5 + i * .3) % (path.length - 1);
        const index = Math.floor(segment), mix = segment - index;
        const [sx, sy] = path[index], [ex, ey] = path[index + 1];
        pixel(c, x + sx + (ex - sx) * mix, y + sy + (ey - sy) * mix, 2, 2, "#f1fff5");
      }
    }
    if (busy) {
      c.save(); lobes(); c.clip(); c.globalAlpha *= .16;
      const scan = -26 + (phase * 12) % 48;
      pixel(c, x - 36, y + scan - 4, 72, 4, "#a5ece0");
      c.globalAlpha *= 3; pixel(c, x - 36, y + scan, 72, 1, "#defff3"); c.restore();
      for (let i = 0; i < 3; i++) {
        const height = (phase * 14 + i * 8) % 24;
        pixel(c, x + (i - 1) * 9, CORE_AT.y - 32 - height, 1, 2, "#9ed9d4");
      }
    }
    for (let i = 0; i < 3; i++) orbit(i, true);
    c.restore();
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.image) { this.image.onload = null; this.image.onerror = null; this.image.src = ""; }
    this.skyline = null; this.image = null; this.floor.width = 0; this.floor.height = 0;
  }
}
