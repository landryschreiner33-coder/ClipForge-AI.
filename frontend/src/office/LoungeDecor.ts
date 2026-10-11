/** Original pixel lounge furnishings. Games and cafe ambience are leisure, never processing progress. */
import { BlurFilter, Container, Graphics, Rectangle, Sprite, Texture } from "pixi.js";
import { BREAK_SPOTS, ROOM } from "./world";
const px = (g: Graphics, x: number, y: number, w: number, h: number, color: string, alpha = 1) =>
  g.rect(Math.round(x), Math.round(y), w, h).fill({ color, alpha });
const box = (g: Graphics, x: number, y: number, w: number, h: number, color: string, edge = "#172431") => {
  px(g, x, y, w, h, edge); px(g, x + 1, y + 1, w - 2, h - 2, color);
};

/** A cropped image sits within procedural frames. Missing art leaves the original glass underneath. */
export function skylineWindow(g: Graphics, texture: Texture | null,
  x: number, y: number, w: number, h: number, section = 0) {
  if (!texture) return null;
  const sourceW = texture.source.width, sourceH = texture.source.height;
  const cropW = Math.floor(Math.min(sourceW, sourceH * w / h)), cropH = Math.floor(Math.min(sourceH, cropW * h / w));
  const startX = Math.floor(Math.min(sourceW - cropW, Math.max(0, (sourceW - cropW) * section)));
  const startY = Math.floor((sourceH - cropH) * .8);
  const cropped = new Texture({ source: texture.source, frame: new Rectangle(startX, startY, cropW, cropH) });
  const sprite = new Sprite({ texture: cropped });
  sprite.position.set(x, y); sprite.width = w; sprite.height = h; sprite.alpha = .8;
  g.addChild(sprite);
  const frame = new Graphics();
  px(frame, x + Math.floor(w / 2), y, 2, h, "#818c91");
  px(frame, x, y + h - 2, w, 2, "#d5aa80", .14);
  g.addChild(frame);
  return cropped;
}
export function cachedLightPool(g: Graphics, x: number, y: number, rx: number, ry: number, color: string, alpha = .06) {
  const pool = new Graphics();
  pool.ellipse(x, y, rx, ry).fill({ color, alpha });
  pool.filters = [new BlurFilter({ strength: 6, quality: 2 })];
  g.addChild(pool);
}

export function createLoungeDecor(floor: Graphics, depth: Container, skyline: Texture | null,
  chairBack: (g: Graphics, p: { x: number; y: number }, color: string, rest?: boolean) => void) {
  const r = ROOM.lounge, ox = r.x, oy = r.y;
  const g = floor, ambient = new Container();
  const croppedTextures: Texture[] = [];
  let destroyed = false;
  const arcades: { x: number; y: number; color: string }[] = [];
  const screens = new Graphics(), steam = new Graphics(), tokens = new Graphics();
  ambient.addChild(screens, steam);
  tokens.zIndex = oy + 132; depth.addChild(tokens);
  const at = (x: number, y: number) => ({ x: ox + x, y: oy + y });
  const foreground = (art: Graphics, y: number) => { art.zIndex = y + 1; depth.addChild(art); };
  const carpet = (x: number, y: number, w: number, h: number, color: string) => {
    box(g, ox + x, oy + y, w, h, color, "#27383c");
    px(g, ox + x + 3, oy + y + 3, w - 6, 1, "#d5c79b", .22);
    px(g, ox + x + 3, oy + y + h - 4, w - 6, 1, "#d5c79b", .16);
  };
  carpet(9, 17, 222, 82, "#354b53"); carpet(235, 17, 174, 80, "#51493f");
  carpet(18, 101, 134, 109, "#575849"); carpet(172, 101, 138, 109, "#40575a");
  carpet(11, 216, 375, 45, "#53564c");

  const cabinetColors = ["#725f83", "#597c70", "#92655e", "#96815d", "#507382"];
  for (let i = 0; i < 5; i++) {
    const p = BREAK_SPOTS[i].at, x = p.x - 19, y = oy + 20, color = cabinetColors[i];
    px(g, x + 3, y + 45, 36, 6, "#0d1824", .32);
    box(g, x, y, 38, 47, color);
    px(g, x + 1, y + 1, 3, 43, "#c7b7b4", .22);
    box(g, x + 2, y - 4, 34, 10, color, "#20333e");
    px(g, x + 6, y - 2, 26, 2, "#e5c990", .65);
    for (let j = 0; j < 4; j++) px(g, x + 10 + j * 5, y + 1, 3, 1, "#e8dbb5");
    box(g, x + 3, y + 8, 32, 24, "#152536");
    px(g, x + 5, y + 10, 28, 20, "#15283a");
    box(g, x + 2, y + 33, 34, 8, "#53606b");
    px(g, x + 9, y + 32, 2, 5, "#bfc4ba"); box(g, x + 7, y + 30, 6, 4, "#d78977");
    px(g, x + 23, y + 35, 3, 2, "#e2c18b"); px(g, x + 29, y + 35, 2, 2, "#85b39c");
    box(g, x + 12, y + 43, 13, 3, "#354450");
    arcades.push({ x: x + 6, y: y + 11, color: ["#bfb4e0", "#a5d2b5", "#e4a5a0", "#e3cc96", "#9bd0d1"][i] });
    // Compact stools support quiet/paused avatars without turning the room into rows of chairs.
    box(g, p.x - 10, p.y - 12, 20, 5, "#5b6870");
    px(g, p.x - 7, p.y - 7, 2, 8, "#293746");
    px(g, p.x + 5, p.y - 7, 2, 8, "#293746");
  }

  // A dusk panorama and warm cafe counter form one shared hospitality area.
  box(g, ox + 240, oy + 13, 165, 25, "#6d7b86");
  px(g, ox + 243, oy + 16, 159, 19, "#446069");
  const cafeWindow = skylineWindow(g, skyline, ox + 244, oy + 16, 157, 18, .7);
  if (cafeWindow) croppedTextures.push(cafeWindow);
  box(g, ox + 238, oy + 40, 168, 27, "#927658");
  px(g, ox + 240, oy + 41, 164, 3, "#d9b68c");
  px(g, ox + 241, oy + 49, 162, 1, "#4f4b46");
  for (let j = 0; j < 4; j++) box(g, ox + 245 + j * 40, oy + 52, 34, 12, "#75684f");
  box(g, ox + 355, oy + 35, 34, 16, "#2e414a");
  px(g, ox + 358, oy + 37, 28, 4, "#a3bcb5");
  box(g, ox + 362, oy + 43, 8, 7, "#cdbda3"); box(g, ox + 376, oy + 43, 8, 7, "#cdbda3");
  box(g, ox + 290, oy + 34, 45, 10, "#423c39");
  for (let j = 0; j < 5; j++) {
    box(g, ox + 293 + j * 8, oy + 36, 6, 5, "#d6a975");
    px(g, ox + 295 + j * 8, oy + 37, 2, 1, "#efd5a8");
  }
  box(g, ox + 251, oy + 36, 23, 7, "#bfc4ad");
  for (const x of [252, 296, 340, 384]) {
    const p = at(x, 76);
    box(g, p.x - 10, p.y - 12, 20, 5, "#816c56");
    px(g, p.x - 7, p.y - 7, 2, 8, "#2d3b43");
    px(g, p.x + 5, p.y - 7, 2, 8, "#2d3b43");
  }

  for (const group of ["a", "b"] as const) {
    const sx = group === "a" ? 30 : 186, color = group === "a" ? "#b49770" : "#a59173";
    const seats = BREAK_SPOTS.filter(s => s.id.startsWith(`game-${group}-`) && s.posture === "rest");
    for (const s of seats) chairBack(g, s.at, group === "a" ? "#64735f" : "#647e7b", true);
    px(g, ox + sx + 3, oy + 163, 109, 9, "#14222b", .28);
    const table = new Graphics();
    table.poly([ox + sx + 3, oy + 108, ox + sx + 107, oy + 108, ox + sx + 115, oy + 164, ox + sx - 5, oy + 164])
      .fill({ color: "#263342" });
    table.poly([ox + sx + 5, oy + 110, ox + sx + 105, oy + 110, ox + sx + 112, oy + 159, ox + sx - 2, oy + 159])
      .fill({ color });
    px(table, ox + sx + 5, oy + 111, 100, 2, "#dec5a0");
    px(table, ox + sx - 2, oy + 159, 114, 5, "#78644e");
    px(table, ox + sx + 6, oy + 165, 4, 5, "#283543"); px(table, ox + sx + 100, oy + 165, 4, 5, "#283543");
    const bx = ox + sx + 35, by = oy + 119;
    if (group === "a") {
      box(table, bx - 2, by - 2, 40, 40, "#826650");
      for (let row = 0; row < 8; row++) for (let col = 0; col < 8; col++)
        px(table, bx + col * 4, by + row * 4, 4, 4, (row + col) % 2 ? "#496461" : "#ddd0a7");
      for (const [col, row, light] of [[1, 1, 1], [4, 2, 0], [6, 5, 1], [2, 6, 0]]) {
        box(table, bx + col * 4, by + row * 4 - 2, 3, 5, light ? "#d8d7b6" : "#283c49");
      }
    } else {
      box(table, bx - 2, by - 2, 41, 39, "#d7c7a3");
      for (const [dx, dy, color] of [
        [0, 0, "#ac746d"], [24, 0, "#6b8ea5"], [0, 24, "#88a57b"], [24, 24, "#c6ae72"],
      ] as const) {
        box(table, bx + dx, by + dy, 12, 12, color); px(table, bx + dx + 4, by + dy + 3, 4, 5, "#ece0bd");
      }
      for (let j = 0; j < 7; j++) {
        px(table, bx + 15, by + j * 5, 5, 3, "#93a4a0");
        px(table, bx + j * 5, by + 15, 3, 5, "#93a4a0");
      }
      box(table, ox + sx + 88, oy + 126, 8, 8, "#ede2c6"); px(table, ox + sx + 91, oy + 128, 2, 2, "#625e60");
    }
    foreground(table, oy + 130);
  }

  const sofaColors = ["#6b8882", "#8b756a", "#6d788e", "#8e8270"];
  for (let i = 0; i < 4; i++) {
    const x = ox + 13 + i * 94, y = oy + 208, color = sofaColors[i];
    px(g, x + 3, y + 38, 84, 5, "#14232a", .3);
    box(g, x, y, 85, 37, color);
    px(g, x + 2, y + 2, 81, 3, "#d4d6c4", .24);
    px(g, x + 5, y + 8, 75, 2, "#364b50", .25);
    for (let j = 0; j < 2; j++) {
      box(g, x + 7 + j * 39, y + 23, 33, 15, color, "#405357");
      px(g, x + 10 + j * 39, y + 24, 27, 2, "#e1d4b2", .15);
    }
    const arms = new Graphics();
    for (const dx of [0, 79]) {
      box(arms, x + dx - 2, y + 15, 9, 24, color, "#2b3d46");
      px(arms, x + dx, y + 16, 5, 3, "#c4c3ae", .4);
    }
    px(arms, x + 5, y + 36, 76, 3, "#394b53"); foreground(arms, oy + 244);
  }
  // Tall, narrow bookcase leaves the door and the main aisle open.
  box(g, ox + 391, oy + 161, 19, 53, "#766955");
  for (let row = 0; row < 4; row++) {
    px(g, ox + 393, oy + 171 + row * 12, 15, 2, "#443f3b");
    for (let col = 0; col < 4; col++)
      box(g, ox + 394 + col * 3, oy + 164 + row * 12, 2, 7,
        ["#b78276", "#bba476", "#769d9f", "#a18db7"][col]);
  }
  cachedLightPool(g, ox + 126, oy + 62, 108, 23, "#9bbcd7", .06);
  cachedLightPool(g, ox + 327, oy + 64, 75, 24, "#e9ba87", .07);
  cachedLightPool(g, ox + 189, oy + 223, 168, 25, "#e1d2a2", .045);

  return {
    container: ambient,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      for (const texture of croppedTextures) texture.destroy(false);
    },
    update(timeMs: number, still: boolean) {
      if (destroyed) return;
      const t = still ? 0 : timeMs;
      screens.clear(); steam.clear(); tokens.clear();
      for (let i = 0; i < arcades.length; i++) {
        const a = arcades[i], step = Math.floor(t / (600 + i * 83)) % 4;
        px(screens, a.x, a.y, 26, 18, "#152839");
        for (let row = 0; row < 2; row++) for (let col = 0; col < 3; col++) {
          const xx = a.x + 2 + col * 8 + (still ? 0 : step % 2), yy = a.y + 2 + row * 5;
          px(screens, xx + 1, yy, 3, 2, a.color); px(screens, xx, yy + 2, 5, 1, a.color);
          px(screens, xx, yy + 3, 1, 1, a.color); px(screens, xx + 4, yy + 3, 1, 1, a.color);
        }
        const shipX = a.x + 4 + (still ? 8 : Math.round((Math.sin(t / 1300 + i) + 1) * 7));
        px(screens, shipX, a.y + 15, 5, 2, "#e5d8b0"); px(screens, shipX + 2, a.y + 14, 1, 1, "#e5d8b0");
        if (step % 2) px(screens, shipX + 2, a.y + 11, 1, 2, "#e5d8b0", .7);
      }
      const phase = still ? 0 : Math.floor(t / 400) % 4;
      for (const x of [ox + 367, ox + 380]) {
        px(steam, x + phase % 2, oy + 32 - phase, 1, 3, "#ddd8c3", .38);
        px(steam, x + 2 - phase % 2, oy + 29 - phase, 1, 2, "#ddd8c3", .22);
      }
      const move = still ? 0 : Math.floor(t / 4500) % 3;
      box(tokens, ox + 73 + move * 4, oy + 139 - move * 4, 3, 5, "#d8d7b6");
      box(tokens, ox + 237, oy + 136 + move * 5, 4, 4, "#b66f6a");
    },
  };
}
