/** Worker bot art (16 roles). Each entry only describes what is unique to that role. */
import {
  OUTLINE,
  type Mat,
  ascii,
  darken,
  ellipse,
  hexPointy,
  lighten,
  mat,
  mix,
  octo,
  rect,
  rr,
  shapeFrom,
  trap,
} from "../pixel";
import { type Box, type G, type RobotDef, drawLimb, eye } from "../rig";
import { antenna, atHand, ball, displayMode, gripHand, head, reel, tablet, torso, twoEyes } from "./common";

const darkPanel = (g: G) => mat(darken(g.k.face.mid, 0.05), 0.3);

/** A small slate/tablet held in the near hand; narrow in profile. */
function slate(
  g: G,
  w: number,
  h: number,
  frame: Mat,
  screen: string,
  icon?: (x: number, y: number, w: number, h: number) => void,
) {
  const side = g.v === "side";
  const tw = side ? 4 : w;
  const { x, y } = atHand(g, tw, h, side ? 1 : 2, 3);
  tablet(g, x, y, tw, h, frame, screen, side ? undefined : icon);
  gripHand(g);
}

// ------------------------------------------------------------------ RADAR (Scout)

function radarDish(g: G, x: number, y: number, size: number, frame: number) {
  const { c, k } = g;
  c.shape(x, y, ellipse(size, size), k.trim);
  const inner = size - 4;
  c.shape(x + 2, y + 2, ellipse(inner, inner), mat("#0F3A22", 0.5), { outline: false, shade: "flat" });
  const cx = x + Math.floor(size / 2),
    cy = y + Math.floor(size / 2);
  const rad = Math.floor(inner / 2) - 1;
  for (let a = 0; a < 32; a++) {
    const t = (a / 32) * Math.PI * 2;
    c.px(Math.round(cx + Math.cos(t) * (rad * 0.55)), Math.round(cy + Math.sin(t) * (rad * 0.55)), "#1F6B3A");
  }
  c.hline(cx - rad, cy, rad * 2 + 1, "#1F6B3A");
  c.vline(cx, cy - rad, rad * 2 + 1, "#1F6B3A");
  const ang = (-90 + frame * 90 + 35) * (Math.PI / 180);
  c.line(cx, cy, Math.round(cx + Math.cos(ang) * rad), Math.round(cy + Math.sin(ang) * rad), k.trim.hi);
  const a2 = ang - 0.45;
  c.line(cx, cy, Math.round(cx + Math.cos(a2) * rad), Math.round(cy + Math.sin(a2) * rad), "#3FA95A");
  c.px(cx + Math.round(rad * 0.4), cy - Math.round(rad * 0.5), k.trim.hi);
  c.px(cx, cy, "#E9FFD0");
}

const radar: RobotDef = {
  rig: { headW: 18, headH: 17 },
  pack: (g) => {
    const f = g.p.work ?? 0;
    if (g.v === "front") radarDish(g, g.head.x - 8, g.torso.y - 13, 15, f);
    else if (g.v === "back") radarDish(g, g.r.cx - 8, g.torso.y - 9, 17, f);
    else radarDish(g, g.torso.x - 10, g.torso.y - 9, 15, f);
  },
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.shape(b.x + 4, b.y + 3, rr(b.w - 8, 5, 1), darkPanel(g), { shade: "flat" });
        g.c.fill(b.x + 6, b.y + 5, 2, 1, g.k.trim.hi);
        g.c.fill(b.x + 9, b.y + 5, 1, 1, g.k.trim.mid);
      },
    }),
  shoulders: (g) => {
    const { c, k, torso: t, v } = g;
    if (v === "side") {
      c.shape(t.x + 2, t.y, rr(6, 4, 2), k.trim);
      return;
    }
    c.shape(t.x - 4, t.y - 1, rr(7, 5, 2), k.trim);
    c.shape(t.x + t.w - 3, t.y - 1, rr(7, 5, 2), k.trim);
  },
  head: (g) => {
    const b = g.head;
    const ax = g.v === "side" ? b.x + 3 : g.v === "back" ? b.x + b.w - 5 : b.x + 4;
    antenna(g, ax, b.y - 11, b.y + 1, (x, y) => ball(g, x, y, 6, g.k.trim));
    head(g, { shape: (w, h) => ellipse(w, h), ears: { w: 4, h: 6, mat: g.k.joint } });
    const { c, k, v } = g;
    const lens = mat("#2A3346", 0.6);
    if (v === "front") {
      const y = b.y + 6;
      for (const x of [b.x + 1, b.x + b.w - 9]) {
        c.shape(x, y, rr(8, 8, 3), lens);
        c.shape(x + 1, y + 1, ellipse(6, 6), mat("#0D1420", 0.4), { outline: k.trim.lo, shade: "flat" });
        eye(g, x + 2, y + 2, 3, 3, "round");
      }
      c.fill(b.x + 9, y + 3, b.w - 18, 2, lens.dk);
    } else if (v === "side") {
      const y = b.y + 6;
      c.shape(b.x + b.w - 4, y, rr(8, 8, 2), lens);
      c.fill(b.x + b.w + 3, y + 1, 1, 6, k.trim.mid);
      eye(g, b.x + b.w + 1, y + 2, 2, 3, "pill");
    }
  },
  item: (g) => {
    const { c } = g;
    const w = g.v === "side" ? 4 : 9,
      h = 9;
    const { x, y } = atHand(g, w, h, 2, 3);
    c.shape(x, y, rr(w, h, 1), mat("#3DDC6B"));
    for (let i = 2; i < w - 1; i += 2) c.vline(x + i, y + 1, h - 2, "#1E8A45");
    for (let j = 2; j < h - 1; j += 3) c.hline(x + 1, y + j, w - 2, "#1E8A45");
    c.px(x + Math.floor(w / 2), y + 3, "#FFFFFF");
    gripHand(g);
  },
};

// ------------------------------------------------------------------ ARCHIVE (Researcher)

function satchel(g: G, x: number, y: number, w: number) {
  const bag = mat("#9A6034");
  g.c.shape(x, y, rr(w, 7, 1), bag);
  g.c.shape(x, y, rr(w, 3, 1), mat("#7A4626"));
  g.c.px(x + Math.floor(w / 2), y + 3, "#FFD15C");
}

const archive: RobotDef = {
  rig: { headW: 22, headH: 16 },
  arms: (g) =>
    g.p.work === null
      ? {}
      : {
          rightTo: {
            x: g.torso.x + g.torso.w + 2 - [0, 2, 3, 1][g.p.work],
            y: g.torso.y + 3 + [0, 1, 0, -1][g.p.work],
          },
        },
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        const { c } = g;
        // strap across the chest
        c.line(b.x + b.w - 3, b.y, b.x + 2, b.y + b.h - 3, "#7A4626");
        c.line(b.x + b.w - 2, b.y, b.x + 3, b.y + b.h - 3, "#9A6034");
        c.shape(b.x + 5, b.y + 3, rr(5, 4, 1), g.k.trim, { shade: "flat" });
      },
      back: (g, b) => {
        g.c.line(b.x + 2, b.y, b.x + b.w - 3, b.y + b.h - 3, "#9A6034");
      },
      side: (g, b) => {
        g.c.vline(b.x + Math.floor(b.w / 2), b.y, b.h - 2, "#9A6034");
      },
    }),
  after: (g) => {
    const t = g.torso;
    if (g.v === "front") satchel(g, t.x - 5, t.y + t.h - 6, 8);
    else if (g.v === "side") satchel(g, t.x - 3, t.y + t.h - 6, 7);
  },
  pack: (g) => {
    if (g.v === "back") satchel(g, g.torso.x + g.torso.w - 3, g.torso.y + g.torso.h - 6, 8);
  },
  head: (g) => {
    const { c, k, v, head: b } = g;
    head(g, { shape: (w, h) => rr(w, h, 1), ears: undefined, glint: false });
    // pages along the top edge
    const pageX = v === "side" ? b.x + 1 : b.x + 5;
    const pw = v === "side" ? b.w - 2 : b.w - 6;
    c.fill(pageX, b.y + 1, pw, 2, "#FFFDF5");
    for (let i = 1; i < pw; i += 2) c.px(pageX + i, b.y + 1, "#C7C2B4");
    // book spine
    if (v !== "side") {
      const sx = v === "front" ? b.x + 1 : b.x + b.w - 5;
      c.fill(sx, b.y + 1, 4, b.h - 2, k.trim.mid);
      c.vline(sx, b.y + 1, b.h - 2, k.trim.hi);
      for (let j = 3; j < b.h - 2; j += 4) c.hline(sx, b.y + j, 4, k.trim.dk);
    } else {
      c.fill(b.x + 1, b.y + 3, b.w - 2, 2, k.trim.mid);
    }
    if (v === "front") {
      c.shape(b.x + 6, b.y + 5, rr(14, 8, 2), darkPanel(g), { shade: "flat" });
      for (const x of [b.x + 5, b.x + 13]) {
        c.shape(x, b.y + 5, ellipse(8, 8), k.trim, { glint: false });
        c.blot(x + 1, b.y + 6, ellipse(6, 6), mix(k.face.mid, "#7FF4FF", 0.15));
        eye(g, x + 3, b.y + 7, 2, 3, "pill");
        c.px(x + 1, b.y + 7, "#E9FFFF");
      }
    } else if (v === "side") {
      c.shape(b.x + b.w - 6, b.y + 6, rr(5, 7, 1), darkPanel(g), { shade: "flat" });
      c.shape(b.x + b.w - 5, b.y + 5, ellipse(6, 8), k.trim, { glint: false });
      c.blot(b.x + b.w - 4, b.y + 6, ellipse(4, 6), mix(k.face.mid, "#7FF4FF", 0.15));
      eye(g, b.x + b.w - 3, b.y + 7, 2, 3, "pill");
      c.hline(b.x + 5, b.y + 8, b.w - 10, k.trim.lo);
    } else {
      c.hline(b.x + 2, b.y + 8, b.w - 7, k.trim.lo);
    }
  },
  item: (g) => {
    const { c } = g;
    const { x, y } = atHand(g, 8, 11, 0, 2);
    c.shape(x + 1, y + 6, rect(2, 5), mat("#7A4626"));
    c.shape(x, y, ellipse(8, 8), g.k.trim, { glint: false });
    c.blot(x + 2, y + 2, ellipse(4, 4), "#BFF6FF");
    c.px(x + 2, y + 2, "#FFFFFF");
    gripHand(g);
  },
};

// ------------------------------------------------------------------ PULSE (Trend Analyst)

const pulse: RobotDef = {
  rig: { headW: 20, headH: 14 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      shape: (w, h) => trap(w, h, 0, 2, 2),
      front: (g, b) => {
        g.c.fill(b.x + 3, b.y + 3, b.w - 6, 2, g.k.trim.mid);
        g.c.hline(b.x + 3, b.y + 3, b.w - 6, g.k.trim.hi);
      },
      side: (g, b) => g.c.fill(b.x + 1, b.y + 3, b.w - 2, 2, g.k.trim.mid),
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    // zigzag antenna
    const ax = v === "side" ? b.x + Math.floor(b.w / 2) - 1 : g.r.cx - 4;
    const zig = ["......#.", ".....#.#", "#...#...", ".#.#....", "..#.....", "..#....."];
    c.map(
      ax - 1,
      b.y - 7,
      zig.map((r) => r.replace(/#/g, "o")),
      { o: OUTLINE },
    );
    c.map(
      ax + 1,
      b.y - 7,
      zig.map((r) => r.replace(/#/g, "o")),
      { o: OUTLINE },
    );
    c.map(
      ax,
      b.y - 8,
      zig.map((r) => r.replace(/#/g, "o")),
      { o: OUTLINE },
    );
    c.map(
      ax,
      b.y - 6,
      zig.map((r) => r.replace(/#/g, "o")),
      { o: OUTLINE },
    );
    c.map(ax, b.y - 7, zig, { "#": f % 2 === 1 ? "#FFFFFF" : k.acc.mid });
    head(g, {
      shape: (w, h) => octo(w, h, 4, 2),
      sideShape: (w, h) => octo(w, h, 3, 1),
      ears: { w: 3, h: 6, mat: k.trim, dy: 4 },
      visor: { dx: 2, dy: 3, w: b.w - 4, h: 8, shape: (w, h) => octo(w, h, 1, 1) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const n = 5;
        const heights = [
          [2, 4, 6, 3, 5],
          [4, 6, 3, 5, 2],
          [6, 3, 5, 2, 4],
          [3, 5, 2, 4, 6],
        ][f % 4];
        for (let i = 0; i < n; i++) {
          const h = g.p.work === null ? [3, 5, 6, 4, 3][i] : heights[i];
          g.c.fill(vb.x + 2 + i * 3, vb.y + vb.h - 1 - h, 2, h, i === 2 ? lighten(col, 0.4) : col);
        }
      },
      sideEyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        [3, 5, 4].forEach((h, i) => g.c.fill(vb.x + 1 + i * 2, vb.y + vb.h - 1 - h, 1, h, col));
      },
    });
  },
  item: (g) =>
    slate(g, 10, 11, mat("#2A3A66"), "#0E1838", (x, y, w, h) => {
      const f = g.p.work ?? 0;
      g.c.line(x, y + h - 2, x + 3, y + h - 4, "#28D9FF");
      g.c.line(x + 3, y + h - 4, x + 5, y + h - 3, "#28D9FF");
      g.c.line(x + 5, y + h - 3, x + w - 1, y + 1 + (f % 2), "#28D9FF");
      g.c.hline(x, y + h - 1, w, "#3A6BFF");
    }),
};

// ------------------------------------------------------------------ GAVEL (Source Judge)

function stamp(g: G, x: number, y: number, impact: boolean) {
  const { c } = g;
  c.shape(x + 1, y - 1, ellipse(6, 5), mat("#E8423B"));
  c.shape(x + 2, y + 3, rect(4, 3), mat("#8A2A24"));
  c.shape(x, y + 6, rr(8, 3, 1), mat("#B9BCC6"));
  if (impact) {
    c.px(x + 9, y + 7, "#FFD15C");
    c.px(x + 10, y + 5, "#FFD15C");
    c.px(x - 2, y + 7, "#FFD15C");
    c.px(x - 3, y + 5, "#FFD15C");
  }
}

const gavel: RobotDef = {
  rig: { headW: 24, headH: 17 },
  footMat: (k) => k.trim,
  arms: (g) =>
    g.p.work === null ? {} : { rightTo: { x: g.torso.x + g.torso.w + 3, y: g.torso.y + [1, 6, 7][g.p.work] } },
  torso: (g) =>
    torso(g, {
      shape: (w, h) => rr(w, h, 1),
      front: (g, b) => {
        const { c, k } = g;
        c.shape(b.x + 3, b.y + 2, rr(b.w - 6, 7, 1), k.trim);
        c.shape(g.r.cx - 2, b.y + 4, ellipse(4, 4), mat("#8A5A10"), { outline: false });
      },
      side: (g, b) => g.c.shape(b.x + b.w - 4, b.y + 2, rr(4, 7, 1), g.k.trim),
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    // heavy squared jaw: top inset, bottom full width
    const shape = (w: number, h: number) =>
      shapeFrom(w, h, (x, y) => {
        if (y < h - 6) return x >= 1 && x < w - 1 && !(y === 0 && (x < 2 || x > w - 3));
        return true;
      });
    head(g, {
      shape,
      ears: { w: 4, h: 7, mat: k.trim, dy: 3, shape: (w, h) => rr(w, h, 1) },
      visor: { dx: 4, dy: 4, w: b.w - 8, h: 5, shape: (w, h) => rect(w, h) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const y = vb.y + 2;
        g.c.hline(vb.x + 2, y, vb.w - 4, col);
        g.c.fill(vb.x + Math.floor(vb.w / 2) - 1 + g.p.lookX * 2, y - 1, 3, 3, lighten(col, 0.5));
      },
      sideEyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (col) g.c.hline(vb.x + 1, vb.y + 2, vb.w - 2, col);
      },
    });
    if (v !== "back") {
      // jaw seam + bolts
      const jy = b.y + b.h - 6;
      c.hline(b.x + 1, jy, b.w - 2, k.shell.lo);
      if (v === "front") {
        c.px(b.x + 2, jy + 2, k.shell.dk);
        c.px(b.x + b.w - 3, jy + 2, k.shell.dk);
      }
      for (let i = 0; i < 4; i++)
        c.vline(g.v === "side" ? b.x + b.w - 8 + i * 2 : g.r.cx - 4 + i * 2, jy + 2, 2, k.shell.lo);
    }
  },
  item: (g) => {
    const w = g.p.work;
    const { x, y } = atHand(g, 7, 10, 3, 4);
    stamp(g, x, y - 2, w === 2);
    if (w === 2 && g.v === "front") g.c.fill(x + 1, y + 9, 5, 1, "#E8423B");
    gripHand(g);
  },
  after: (g) => {
    // checklist clipboard in the off hand
    if (g.v !== "front" || g.p.card) return;
    const h = g.hand2;
    const x = h.x - 4,
      y = h.y - 9;
    g.c.shape(x, y, rr(7, 9, 1), mat("#C98A44"));
    g.c.fill(x + 1, y + 2, 5, 6, "#FFF6E3");
    g.c.fill(x + 2, y - 1, 3, 2, "#6B7385");
    for (let i = 0; i < 3; i++) {
      g.c.px(x + 2, y + 3 + i * 2, "#2FBF5A");
      g.c.hline(x + 3, y + 3 + i * 2, 2, "#B07A44");
    }
    g.c.shape(h.x - 2, h.y - 2, ellipse(4, 4), g.k.shell, { shade: "soft" });
  },
};

// ------------------------------------------------------------------ SPARK (Moment Finder)

const STAR = ["..#..", ".###.", "#####", ".###.", ".#.#."];

const spark: RobotDef = {
  rig: { headW: 21, headH: 19, torsoW: 14, torsoH: 9, legH: 5 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      shape: (w, h) => ellipse(w, h),
      front: (g, b) => g.c.fill(g.r.cx - 2, b.y + 4, 4, 2, g.k.trim.mid),
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    const ax = v === "side" ? b.x + Math.floor(b.w / 2) - 1 : g.r.cx;
    antenna(g, ax, b.y - 6, b.y + 1, (x, y) => {
      c.map(
        x - 3,
        y - 4,
        STAR.map((r) => r.replace(/#/g, "o")),
        { o: OUTLINE },
      );
      c.map(
        x - 1,
        y - 4,
        STAR.map((r) => r.replace(/#/g, "o")),
        { o: OUTLINE },
      );
      c.map(
        x - 2,
        y - 5,
        STAR.map((r) => r.replace(/#/g, "o")),
        { o: OUTLINE },
      );
      c.map(
        x - 2,
        y - 3,
        STAR.map((r) => r.replace(/#/g, "o")),
        { o: OUTLINE },
      );
      c.map(x - 2, y - 4, STAR, { "#": g.p.work === 1 ? "#FFFFFF" : k.trim.mid });
      c.px(x - 1, y - 3, "#FFFFFF");
    });
    head(g, {
      shape: (w, h) => ellipse(w, h),
      ears: { w: 5, h: 6, mat: k.trim, dy: 7, shape: (w, h) => ellipse(w, h) },
    });
    if (v === "back") return;
    // the big lens
    const s = v === "side" ? 9 : 13;
    const lx = v === "side" ? b.x + b.w - 7 : g.r.cx - Math.floor(s / 2),
      ly = b.y + 3;
    c.shape(lx, ly, ellipse(s, s), mat("#2A3346", 0.5), { glint: false });
    const iris = s - 4;
    const col = g.p.eyeColor ?? k.eye;
    const ix = lx + 2 + (v === "front" ? g.p.lookX : 0),
      iy = ly + 2 + (g.p.eyes === "down" ? 1 : 0);
    if (g.p.eyes === "blink" || g.p.eyes === "closed" || g.p.eyes === "off") {
      c.blot(lx + 1, ly + 1, ellipse(s - 2, s - 2), k.face.mid);
      c.hline(lx + 2, ly + Math.floor(s / 2), s - 4, g.p.eyes === "blink" ? col : k.eyeDim);
    } else if (g.p.eyes === "happy") {
      c.blot(lx + 1, ly + 1, ellipse(s - 2, s - 2), k.face.mid);
      eye(g, lx + 3, ly + 4, s - 6, 3, "arc");
    } else if (g.p.eyes === "x") {
      c.blot(lx + 1, ly + 1, ellipse(s - 2, s - 2), k.face.mid);
      eye(g, lx + 3, ly + 3, s - 6, s - 6);
    } else {
      c.blot(ix, iy, ellipse(iris, iris), col);
      c.blot(ix + 1, iy + 1, ellipse(iris - 2, iris - 2), darken(col, 0.25));
      const pupil = g.p.work === 1 ? 2 : Math.max(2, iris - 6);
      const po = Math.floor((iris - pupil) / 2);
      c.blot(ix + po, iy + po, ellipse(pupil, pupil), "#0A1430");
      c.fill(ix + 1, iy + 1, 2, 2, "#FFFFFF");
    }
    void f;
  },
  item: (g) => {
    const { c, k } = g;
    const side = g.v === "side";
    const { x, y } = atHand(g, 9, 13, side ? 1 : 3, 4);
    c.shape(x + 3, y + 8, rect(2, 5), k.joint);
    if (side) {
      c.shape(x + 1, y, rr(4, 9, 1), k.trim);
      gripHand(g);
      return;
    }
    c.shape(x, y, ellipse(9, 9), k.trim, { glint: false });
    c.blot(x + 2, y + 2, ellipse(5, 5), "#1A1A2E");
    c.map(x + 2, y + 3, [".....", "..#..", "#.#.#", "...#."], { "#": k.trim.hi });
    if (g.p.work === 1) {
      c.vline(x + 4, y - 4, 2, k.trim.hi);
      c.px(x + 9, y - 1, k.trim.hi);
      c.px(x + 10, y - 2, k.trim.hi);
      c.px(x - 1, y - 1, k.trim.hi);
      c.px(x - 2, y - 2, k.trim.hi);
      c.hline(x + 10, y + 4, 2, k.trim.hi);
    }
    gripHand(g);
  },
};

// ------------------------------------------------------------------ STORY (Story Editor)

function storyboard(g: G, x: number, y: number, f: number) {
  const { c } = g;
  const icons = [
    (cx: number, cy: number) => {
      c.fill(cx, cy, 4, 3, "#4FA8FF");
      c.px(cx + 1, cy + 1, "#FFFFFF");
      c.hline(cx, cy + 2, 4, "#2FBF5A");
    },
    (cx: number, cy: number) => {
      c.fill(cx, cy, 4, 3, "#FF5C8A");
      c.vline(cx + 1, cy, 3, "#FFFFFF");
      c.px(cx + 2, cy + 1, "#FFFFFF");
    },
    (cx: number, cy: number) => {
      c.hline(cx, cy, 4, "#4FA8FF");
      c.hline(cx, cy + 1, 3, "#4FA8FF");
      c.hline(cx, cy + 2, 4, "#4FA8FF");
    },
  ];
  for (let i = 0; i < 3; i++) {
    const lift = f >= 0 && i === f % 3 ? -2 : 0;
    const cx = x + i * 7,
      cy = y + lift;
    c.shape(cx, cy, rr(7, 7, 1), mat("#F7F3EE", 0.5), { outline: OUTLINE });
    c.fill(cx + 1, cy + 1, 5, 5, mat("#FF6F61").mid);
    c.fill(cx + 1, cy + 1, 5, 1, mat("#FF6F61").hi);
    c.fill(cx + 1, cy + 2, 5, 4, "#FFFFFF");
    icons[i](cx + 2, cy + 2);
  }
}

const story: RobotDef = {
  rig: { headW: 25, headH: 15 },
  footMat: (k) => k.trim,
  arms: (g) =>
    g.p.card ? {} : { leftTo: { x: g.r.cx - 11, y: g.torso.y + 5 }, rightTo: { x: g.r.cx + 11, y: g.torso.y + 5 } },
  torso: (g) => torso(g, { front: (g, b) => g.c.hline(b.x + 2, b.y + b.h - 3, b.w - 4, g.k.trim.mid) }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    // antenna knob (top-left)
    const ax = v === "side" ? b.x + 5 : v === "back" ? b.x + b.w - 6 : b.x + 5;
    antenna(g, ax, b.y - 4, b.y + 1, (x, y) => ball(g, x, y, 4, k.trim));
    head(g, { shape: (w, h) => rr(w, h, 4), ears: undefined, glint: true });
    // book-spine ridge on one side
    const ridge = (x: number) => {
      c.shape(x, b.y + 1, rr(4, b.h - 2, 1), k.trim);
      for (let j = 3; j < b.h - 2; j += 3) c.hline(x + 1, b.y + j, 2, k.trim.dk);
    };
    if (v === "front") ridge(b.x - 2);
    else if (v === "back") ridge(b.x + b.w - 2);
    else ridge(b.x + 1);
    if (v === "front") {
      for (const x of [b.x + 4, b.x + b.w - 11]) {
        c.shape(x, b.y + 4, rr(7, 7, 1), mat(k.face.mid, 0.2), { shade: "flat" });
        eye(g, x + 2, b.y + 6, 3, 3, g.p.eyes === "open" ? "arc" : "pill");
      }
    } else if (v === "side") {
      c.shape(b.x + b.w - 6, b.y + 4, rr(5, 7, 1), mat(k.face.mid, 0.2), { shade: "flat" });
      eye(g, b.x + b.w - 4, b.y + 6, 2, 3, g.p.eyes === "open" ? "arc" : "pill");
    }
  },
  item: (g) => {
    if (g.v === "side") {
      const x = g.torso.x + g.torso.w,
        y = g.torso.y;
      g.c.shape(x, y, rr(3, 9, 1), mat("#F7F3EE", 0.5));
      g.c.vline(x + 1, y + 1, 7, "#FF6F61");
      gripHand(g);
      return;
    }
    storyboard(g, g.r.cx - 10, g.torso.y + 1, g.p.work ?? -1);
    g.c.shape(g.hand.x - 2, g.hand.y - 2, ellipse(4, 4), g.k.shell, { shade: "soft" });
    g.c.shape(g.hand2.x - 2, g.hand2.y - 2, ellipse(4, 4), g.k.shell, { shade: "soft" });
  },
  itemBack: (g) => {
    g.c.shape(g.r.cx - 11, g.torso.y + 1, rr(22, 7, 1), mat("#F7F3EE", 0.5));
  },
};

// ------------------------------------------------------------------ BOOST (Viral Analyst)

const FIN = ["#...", "##..", "###.", "####", ".###", "..##"];

const boost: RobotDef = {
  rig: { headW: 21, headH: 16 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.shape(g.r.cx - 3, b.y + 2, rr(6, 5, 1), g.k.trim);
        g.c.map(g.r.cx - 2, b.y + 3, ["...#", "..#.", "##.."], { "#": "#FFFFFF" });
      },
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const fin = ascii(FIN);
    const finR = ascii(FIN.map((r) => r.split("").reverse().join("")));
    if (v === "side") {
      // swept-back fin trailing off the back of the helmet
      c.shape(b.x - 5, b.y - 3, ascii(["###.....", ".####...", "..#####.", "...#####", "....####"]), k.trim);
    } else {
      c.shape(b.x - 3, b.y - 3, fin, k.trim);
      c.shape(b.x + b.w - 1, b.y - 3, finR, k.trim);
    }
    head(g, {
      shape: (w, h) => rr(w, h, 6, 3),
      sideShape: (w, h) => shapeFrom(w, h, (x, y) => inRR(w, h, 6, x, y) && !(y < 3 && x < 3 - y)),
      ears: { w: 4, h: 6, mat: k.trim, dy: 7 },
      visor: {
        dx: 3,
        dy: 5,
        w: b.w - 6,
        h: 7,
        shape: (w, h) =>
          shapeFrom(w, h, (x, y) => {
            // frame angled upward toward the outer corners
            const mid = (w - 1) / 2;
            const lift = Math.floor(Math.abs(x - mid) / 4);
            return y >= 2 - Math.min(2, lift) && y < h - Math.min(2, lift);
          }),
      },
      eyes: (g, vb) => {
        if (g.p.eyes === "open") {
          // upturned arcs
          eye(g, vb.x + 3, vb.y + 2, 4, 3, "arc");
          eye(g, vb.x + vb.w - 7, vb.y + 2, 4, 3, "arc");
        } else twoEyes(4, 3, "pill", 0.28)(g, vb);
      },
    });
    if (v === "back") c.vline(g.r.cx, b.y + 1, b.h - 4, k.trim.mid);
  },
  item: (g) =>
    slate(g, 11, 11, mat("#1F6F66"), "#0B2422", (x, y, w, h) => {
      const f = g.p.work ?? 3;
      const pts = [
        [0, h - 2],
        [3, h - 3],
        [5, h - 5],
        [w - 1, 1],
      ];
      for (let i = 0; i < Math.min(3, f + 1); i++)
        g.c.line(x + pts[i][0], y + pts[i][1], x + pts[i + 1][0], y + pts[i + 1][1], "#2EE6C8");
      g.c.px(x + w - 2, y + 1, "#FFFFFF");
      g.c.px(x + w - 3, y + 1, "#2EE6C8");
      g.c.px(x + w - 2, y + 2, "#2EE6C8");
    }),
};

function inRR(w: number, h: number, r: number, x: number, y: number) {
  const s = rr(w, h, r, 3);
  return s.m[y * w + x] === 1;
}

// ------------------------------------------------------------------ SPLICE (Video Editor)

const splice: RobotDef = {
  rig: { headW: 26, headH: 14 },
  footMat: (k) => k.trim,
  arms: (g) =>
    g.p.work === null ? {} : { rightTo: { x: g.torso.x + g.torso.w + 1 - [0, 2, 4, 2][g.p.work], y: g.torso.y + 6 } },
  pack: (g) => {
    const f = g.p.work ?? (g.p.step >= 0 ? g.p.step : 0);
    const { v, torso: t } = g;
    if (v === "front") reel(g, t.x - 9, t.y - 2, 13, mat("#7D8496"), f);
    else if (v === "back") reel(g, g.r.cx - 7, t.y - 3, 14, mat("#7D8496"), f);
    else reel(g, t.x - 9, t.y - 3, 13, mat("#7D8496"), f);
  },
  torso: (g) =>
    torso(g, {
      mat: g.k.trim,
      front: (g, b) => {
        g.c.shape(g.r.cx - 3, b.y + 2, rr(6, 5, 1), mat("#FF8FCF"), { shade: "flat" });
        g.c.map(g.r.cx - 1, b.y + 3, ["#..", "##.", "#.."], { "#": "#FFFFFF" });
      },
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    head(g, {
      shape: (w, h) => rr(w, h, 2),
      ears: { w: 7, h: 12, mat: k.acc, dy: 1, front: true, shape: (w, h) => rr(w, h, 3), inset: 3 },
      visor: { dx: 4, dy: 3, w: b.w - 8, h: 8, shape: (w, h) => rr(w, h, 1) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const f = g.p.work ?? 0;
        const bars = [
          [2, 4, 3],
          [4, 2, 4],
          [3, 4, 2],
          [4, 3, 4],
        ][f % 4];
        bars.forEach((h, i) => {
          c.fill(vb.x + 1 + i * 2, vb.y + vb.h - 1 - h, 1, h, col);
          c.fill(vb.x + vb.w - 2 - i * 2, vb.y + vb.h - 1 - h, 1, h, col);
        });
        c.map(vb.x + Math.floor(vb.w / 2) - 1, vb.y + 1, ["#..", "##.", "###", "##.", "#.."], { "#": "#FF5CB8" });
      },
    });
    if (v !== "front") {
      // cups still read from behind
    }
    if (v === "front") for (const x of [b.x - 3, b.x + b.w - 4]) c.fill(x + 2, b.y + 4, 3, 6, k.acc.dk);
    if (v === "back") c.fill(b.x + 3, b.y + b.h - 4, b.w - 6, 2, k.trim.mid);
  },
  item: (g) => {
    const { c } = g;
    const side = g.v === "side";
    const w = side ? 4 : 10,
      h = 7;
    const { x, y } = atHand(g, w, h, side ? 1 : 2, 2);
    c.shape(x, y, rr(w, h, 1), mat("#2A2F45"));
    if (!side) {
      c.fill(x + 1, y + 1, w - 2, 2, "#3FA9FF");
      c.px(x + 1 + (((g.p.work ?? 0) * 2) % (w - 2)), y + 1, "#FFFFFF");
      c.px(x + 2, y + 4, "#FF3DAD");
      c.px(x + 4, y + 4, "#FFAB45");
      c.px(x + 6, y + 4, "#57EEA0");
      c.px(x + 8, y + 4, "#9A6BFF");
    }
    gripHand(g);
  },
};

// ------------------------------------------------------------------ GLYPH (Caption Agent)

function keyboard(g: G, x: number, y: number, f: number) {
  const { c, k } = g;
  c.shape(x, y, rr(16, 5, 1), k.trim);
  for (let r = 0; r < 2; r++)
    for (let i = 0; i < 6; i++) {
      const lit = f >= 0 && (i + r * 3) % 6 === f % 6;
      c.fill(x + 1 + i * 2 + r, y + 1 + r * 2, 1, 1, lit ? "#FFFFFF" : k.trim.hi);
    }
}

const glyph: RobotDef = {
  rig: { headW: 22, headH: 17 },
  footMat: (k) => k.trim,
  arms: (g) => {
    if (g.p.card || g.p.arms === "cheer" || g.p.arms === "offer") return {};
    const f = g.p.work;
    const t = g.torso;
    const lift = (i: number) => (f === null ? 0 : (f + i) % 2);
    return {
      leftTo: { x: g.r.cx - 5, y: t.y + t.h - 3 - lift(0) },
      rightTo: { x: g.r.cx + 5, y: t.y + t.h - 3 - lift(1) },
    };
  },
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.shape(g.r.cx - 5, b.y + 1, rr(10, 7, 1), darkPanel(g), { outline: g.k.trim.mid, shade: "flat" });
        g.c.text(g.r.cx - 4, b.y + 2, "CC", g.k.trim.hi);
      },
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    // monitor neck
    c.shape(g.r.cx - 3, b.y + b.h - 1, rect(6, 3), k.joint);
    head(g, {
      shape: (w, h) => rr(w, h, 4),
      visor: { dx: 2, dy: 2, w: b.w - 4, h: b.h - 5, shape: (w, h) => rr(w, h, 3), rim: k.trim.lo },
      eyes: (g, vb) => {
        if (g.p.eyes === "open") twoEyes(4, 3, "arc", 0.3)(g, { ...vb, y: vb.y + 1 });
        else twoEyes(4, 3, "pill", 0.3)(g, vb);
      },
    });
    // CC key tabs on both sides
    const tab = (x: number, text: boolean) => {
      c.shape(x, b.y + 3, rr(9, 7, 1), mat("#F6F3FF", 0.5), { outline: OUTLINE });
      c.hline(x, b.y + 9, 9, k.trim.mid);
      if (text) c.text(x + 1, b.y + 4, "CC", k.trim.lo);
    };
    if (v === "side") tab(b.x + 1, true);
    else {
      tab(b.x - 7, v === "front");
      tab(b.x + b.w - 2, v === "front");
    }
  },
  item: (g) => {
    if (g.v === "side") {
      g.c.shape(g.torso.x + g.torso.w - 1, g.torso.y + g.torso.h - 4, rr(6, 3, 1), g.k.trim);
      gripHand(g);
      return;
    }
    keyboard(g, g.r.cx - 8, g.torso.y + g.torso.h - 4, g.p.work ?? -1);
    g.c.shape(g.hand.x - 2, g.hand.y - 3, ellipse(4, 4), g.k.shell, { shade: "soft" });
    g.c.shape(g.hand2.x - 2, g.hand2.y - 3, ellipse(4, 4), g.k.shell, { shade: "soft" });
  },
};

// ------------------------------------------------------------------ QUILL (Title Agent)

const quill: RobotDef = {
  rig: { headW: 20, headH: 15 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.fill(b.x + 3, b.y + 3, 3, 3, g.k.trim.mid);
        g.c.hline(b.x + 7, b.y + 4, 5, g.k.shell.lo);
      },
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    // pencil antenna
    const px = v === "side" ? b.x + 6 : v === "back" ? b.x + b.w - 6 : b.x + 5;
    const dir = v === "back" ? 1 : -1;
    const pencil = (x: number, y: number) => {
      const len = 13;
      const at = (i: number) => x + Math.round(dir * i * 0.35);
      for (let i = -1; i <= len; i++) {
        const ow = i >= 12 ? 3 : 5;
        c.fill(at(i) - 1 + (5 - ow) / 2, y - i, ow, 1, OUTLINE);
      }
      for (let i = 0; i < len; i++) {
        const xx = at(i),
          yy = y - i;
        if (i < 2) c.fill(xx, yy, 3, 1, i === 0 ? "#E06A8E" : "#FF8FB0");
        else if (i === 2) c.fill(xx, yy, 3, 1, "#B9BCC6");
        else if (i < 10) {
          c.fill(xx, yy, 3, 1, "#FFD43B");
          c.px(xx, yy, "#FFE98A");
          c.px(xx + 2, yy, "#D9A21F");
        } else if (i < 12) c.fill(xx + (i === 11 ? 1 : 0), yy, i === 11 ? 1 : 3, 1, "#E8C9A0");
        else c.px(xx + 1, yy, "#1A1A2E");
      }
    };
    pencil(px, b.y + 1);
    head(g, {
      shape: (w, h) => trap(w, h, 0, 3, 2),
      sideShape: (w, h) => trap(w, h, 0, 1, 2),
      ears: { w: 4, h: 5, mat: k.trim, dy: 5, shape: (w, h) => ellipse(w, h) },
      visor: { dx: 3, dy: 4, w: b.w - 6, h: 7, shape: (w, h) => trap(w, h, 0, 1, 1) },
      eyes: twoEyes(2, 5, "pill", 0.3),
      sideEyes: (g, vb) => eye(g, vb.x + vb.w - 3, vb.y + 1, 2, 5, "pill"),
    });
  },
  item: (g) => {
    const { c } = g;
    const side = g.v === "side";
    const f = g.p.work ?? 2;
    const { x, y } = atHand(g, 10, 7, 2, 3);
    if (!side) {
      // label strip with "Aa" coming out of the top of the printer
      const lh = [3, 6, 8][f % 3];
      c.to("base");
      c.shape(x + 1, y - lh + 1, rect(9, lh + 1), mat("#FFFFFF", 0.4));
      if (lh >= 6) c.text(x + 2, y - lh + 2, "Aa", "#1A1A2E");
    }
    c.shape(x, y, rr(side ? 5 : 11, 7, 1), mat("#9AA2B4"));
    c.fill(x + 1, y + 1, side ? 3 : 9, 1, "#3A4152");
    if (!side) c.px(x + 8, y + 4, "#FF5C8A");
    gripHand(g);
  },
};

// ------------------------------------------------------------------ CHECK (Quality Control)

const shieldShape = (w: number, h: number) =>
  shapeFrom(w, h, (x, y) => {
    const start = h - 6;
    if (y < 1 && (x < 1 || x > w - 2)) return false;
    if (y < start) return true;
    const inset = Math.round(((y - start + 1) / 6) * (w / 2 - 2));
    return x >= inset && x < w - inset;
  });

const check: RobotDef = {
  rig: { headW: 22, headH: 16, torsoW: 20, torsoH: 13 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      shape: shieldShape,
      front: (g, b) => {
        g.c.shape(g.r.cx - 3, b.y + 3, shieldShape(7, 8), g.k.trim);
        g.c.map(g.r.cx - 2, b.y + 5, ["....#", "#..#.", ".##.."], { "#": "#FFFFFF" });
      },
      back: (g, b) => g.c.vline(g.r.cx, b.y + 2, b.h - 4, g.k.trim.mid),
    }),
  head: (g) => {
    const { k } = g;
    head(g, {
      shape: (w, h) => rr(w, h, 3),
      ears: { w: 4, h: 8, mat: k.trim, shape: (w, h) => rr(w, h, 1) },
      visor: { dx: 4, dy: 3, w: 14, h: 10, shape: (w, h) => rr(w, h, 1), rim: k.trim.lo },
      eyes: twoEyes(4, 4, "square", 0.28),
      sideEyes: (g, vb) => eye(g, vb.x + vb.w - 5, vb.y + 3, 3, 4, "square"),
    });
  },
  after: (g) => {
    // scanner on the off hand
    if (g.v !== "front" || g.p.card) return;
    const h = g.hand2,
      f = g.p.work ?? -1;
    g.c.shape(h.x - 4, h.y - 6, rr(6, 6, 1), mat("#3A4152"));
    g.c.fill(h.x - 3, h.y - 5, 4, 2, f === 0 || f === 1 ? "#B6FFD6" : "#57EEA0");
    if (f === 0 || f === 1) {
      g.c.vline(h.x - 3 + f * 2, h.y - 9, 3, "#57EEA0");
    }
    g.c.shape(h.x - 2, h.y - 2, ellipse(4, 4), g.k.shell, { shade: "soft" });
  },
  item: (g) => {
    const { c } = g;
    const f = g.p.work ?? 2;
    const { x, y } = atHand(g, 9, 14, 4, 4);
    c.shape(x + 4, y + 8, rect(2, 6), mat("#9AA2B4"));
    const edge = g.v === "side" || f === 1;
    if (edge) c.shape(x + 3, y, rr(3, 9, 1), mat("#2FCB6B"));
    else {
      c.shape(x, y, ellipse(10, 10), mat("#2FCB6B"));
      if (f >= 2 || g.p.work === null)
        c.map(x + 2, y + 3, [".....#", "....##", "#..##.", "####..", ".##..."], { "#": "#FFFFFF" });
    }
    gripHand(g);
  },
};

// ------------------------------------------------------------------ LOCK (Audience Verification)

const lock: RobotDef = {
  rig: { headW: 22, headH: 17 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.shape(g.r.cx - 4, b.y + 2, shieldShape(8, 8), g.k.trim);
        g.c.fill(g.r.cx - 1, b.y + 4, 2, 3, "#E5F0FF");
      },
      back: (g, b) => g.c.shape(g.r.cx - 3, b.y + 2, shieldShape(6, 6), g.k.trim, { shade: "flat" }),
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 1;
    head(g, {
      shape: (w, h) => hexPointy(w, h, 4),
      sideShape: (w, h) => octo(w, h, 3, 3),
      ears: { w: 3, h: 6, mat: k.trim },
    });
    if (v === "back") {
      c.shape(g.r.cx - 4, b.y + 3, rr(8, 6, 3, 0), k.shell, { outline: k.trim.mid });
      return;
    }
    // lock-shaped face surround: shackle + body
    const lw = v === "side" ? 7 : 14;
    const lx = v === "side" ? b.x + b.w - lw - 1 : g.r.cx - 7;
    const sw = v === "side" ? 5 : 8;
    const sx = lx + Math.floor((lw - sw) / 2) + (f === 0 && v === "front" ? 2 : 0);
    const sy = b.y + 1 - (f === 0 ? 1 : 0);
    const shackle = shapeFrom(sw, 6, (x, y) => {
      const inner = x >= 2 && x < sw - 2 && y >= 2;
      return !inner && !(y === 0 && (x === 0 || x === sw - 1));
    });
    c.shape(sx, sy, shackle, k.trim);
    c.shape(lx, b.y + 5, rr(lw, 10, 2), { ...k.face, hi: k.face.mid }, { outline: k.trim.mid, shade: "soft" });
    if (v === "front") {
      twoEyes(3, 3, "pill", 0.25)(g, { x: lx, y: b.y + 6, w: lw, h: 5 });
      c.fill(g.r.cx - 1, b.y + 11, 2, 1, k.trim.hi);
      c.px(g.r.cx - 1, b.y + 12, k.trim.hi);
    } else eye(g, lx + lw - 4, b.y + 7, 2, 3);
  },
  item: (g) => {
    const { c } = g;
    const side = g.v === "side";
    const w = side ? 3 : 8,
      h = 10;
    const { x, y } = atHand(g, w, h, 2, 3);
    c.shape(x, y, rr(w, h, 1), mat("#F3F6FF", 0.5));
    if (!side) {
      c.fill(x + 1, y + 1, w - 2, 2, g.k.trim.mid);
      c.fill(x + 3, y + 4, 2, 2, "#3E8BFF");
      c.fill(x + 2, y + 6, 4, 2, "#3E8BFF");
      if (g.p.work === 1) c.hline(x - 1, y + 5, w + 2, "#9FE8FF");
    }
    gripHand(g);
  },
};

// ------------------------------------------------------------------ DOCK (Publisher)

function wheel(g: G, x: number, y: number, s: number, spin: number) {
  g.c.shape(x, y, ellipse(s, s), mat("#2A2F3E", 0.6));
  const cx = x + Math.floor(s / 2),
    cy = y + Math.floor(s / 2);
  g.c.fill(cx - 1, cy - 1, 2, 2, "#9AA2B4");
  const spokes = [
    [0, -2],
    [2, 0],
    [0, 1],
    [-2, 0],
  ];
  const [dx, dy] = spokes[spin % 4];
  g.c.px(cx + dx, cy + dy, "#C9CFDB");
}

const dock: RobotDef = {
  rig: { headW: 24, headH: 12, torsoW: 24, torsoH: 12, legH: 7 },
  legs: "none",
  arms: { thick: 3 },
  base: (g) => {
    const { c, r, v, p } = g;
    const spin = p.work ?? (p.step >= 0 ? p.step : 0);
    const y = r.footY - 6;
    if (v === "side") {
      c.shape(r.cx - 12, y - 2, rr(25, 4, 1), mat("#3A4152"));
      for (const x of [r.cx - 12, r.cx - 4, r.cx + 4]) wheel(g, x, y, 8, spin);
      return;
    }
    c.shape(r.cx - 13, y - 2, rr(26, 4, 1), mat("#3A4152"));
    for (const x of [r.cx - 13, r.cx + 6]) wheel(g, x, y, 7, spin);
    c.shape(r.cx - 4, y + 1, rr(8, 5, 1), mat("#2A2F3E", 0.6));
    // conveyor rollers between wheels
    for (let i = 0; i < 3; i++) c.px(r.cx - 3 + i * 3 + (spin % 3 === 0 ? 0 : 1), y + 2, "#9AA2B4");
  },
  torso: (g) => {
    const { c, k, v, head: hb, torso: t } = g;
    const top = hb.y,
      bottom = t.y + t.h;
    const w = v === "side" ? Math.round(t.w * 0.9) : t.w;
    const x = g.r.cx - Math.floor(w / 2);
    c.shape(x, top, rr(w, bottom - top, 2), k.shell);
    // panel seams and cargo hatch
    c.hline(x + 1, t.y + 2, w - 2, k.shell.lo);
    if (v === "back") {
      c.shape(x + 4, t.y + 3, rr(w - 8, 6, 1), k.shell, { outline: k.shell.dk });
      c.hline(x + 6, t.y + 5, w - 12, k.shell.lo);
    } else if (v === "front") {
      c.fill(x + 2, t.y + 4, 3, 2, k.shell.lo);
      c.fill(x + w - 5, t.y + 4, 3, 2, k.shell.lo);
    }
  },
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? -1;
    // uplink antenna with signal arcs
    const ax = v === "side" ? b.x + 4 : v === "back" ? b.x + b.w - 5 : b.x + 4;
    antenna(g, ax, b.y - 7, b.y + 1, (x, y) => ball(g, x, y, 4, mat("#FFAB45")));
    if (v !== "back") {
      const wx = v === "side" ? b.x + 8 : b.x + b.w - 7;
      const on = f < 0 || f % 2 === 0;
      c.map(wx, b.y - 7, [".###.", "#...#", "..#..", ".#.#."], { "#": on ? "#FFD43B" : "#7A5A10" });
    }
    if (v === "front") {
      c.shape(b.x + 4, b.y + 2, rr(b.w - 8, 9, 1), mat(k.face.mid, 0.2), { shade: "flat" });
      twoEyes(3, 3, "square", 0.3)(g, { x: b.x + 4, y: b.y + 3, w: b.w - 8, h: 7 });
    } else if (v === "side") {
      c.shape(b.x + b.w - 5, b.y + 2, rr(4, 9, 1), mat(k.face.mid, 0.2), { shade: "flat" });
      eye(g, b.x + b.w - 4, b.y + 5, 2, 3, "square");
    }
  },
  item: (g) => {
    const { c } = g;
    const f = g.p.work ?? 0;
    const side = g.v === "side";
    const w = side ? 7 : 10,
      h = 9;
    const { x, y } = atHand(g, w, h, 1 + (g.p.work === null ? 0 : f), 3);
    c.shape(x, y, rr(w, h, 1), mat("#C98A44"));
    c.vline(x + Math.floor(w / 2), y + 1, h - 2, "#E8B878");
    if (!side) c.map(x + 3, y + 3, ["#..", "##.", "#.."], { "#": "#FFFFFF" });
    gripHand(g);
  },
};

// ------------------------------------------------------------------ METRIC (Analytics Agent)

const metric: RobotDef = {
  rig: { headW: 21, headH: 19 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      front: (g, b) => {
        g.c.shape(g.r.cx - 3, b.y + 2, ellipse(6, 6), g.k.trim);
        g.c.blot(g.r.cx - 1, b.y + 4, ellipse(2, 2), "#FFFFFF");
      },
    }),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? -1;
    // three unequal bar fins
    const hs = [5, 9, 6];
    const xs = v === "side" ? [b.x + 3, b.x + 7, b.x + 11] : [g.r.cx - 6, g.r.cx - 1, g.r.cx + 4];
    xs.forEach((x, i) => c.shape(x, b.y - hs[i] + 3, rect(3, hs[i]), i === f % 3 ? mat("#BFF8FF") : k.trim));
    head(g, {
      shape: (w, h) => ellipse(w, h),
      ears: { w: 4, h: 7, mat: k.trim, dy: 7 },
      visor: { dx: 3, dy: 4, w: b.w - 6, h: 12, shape: (w, h) => ellipse(w, h), rim: k.trim.lo },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const base = vb.y + vb.h - 3;
        const bars =
          f < 0
            ? [3, 5, 7]
            : [
                [2, 4, 6],
                [3, 6, 4],
                [5, 3, 7],
                [4, 7, 5],
              ][f % 4];
        bars.forEach((h, i) => c.fill(vb.x + 4 + i * 3, base - h + 1, 2, h, i === 2 ? lighten(col, 0.3) : col));
      },
      sideEyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (col) [3, 5].forEach((h, i) => g.c.fill(vb.x + 1 + i * 2, vb.y + vb.h - 2 - h, 1, h, col));
      },
    });
  },
  item: (g) => {
    const { c } = g;
    const side = g.v === "side";
    const w = side ? 3 : 8,
      h = 10;
    const { x, y } = atHand(g, w, h, 2, 3);
    c.shape(x, y, rr(w, h, 1), mat("#8A6034"));
    if (!side) {
      c.fill(x + 1, y + 1, w - 2, h - 2, "#F3F6FF");
      [2, 4, 3].forEach((bh, i) => c.fill(x + 2 + i * 2, y + h - 2 - bh, 1, bh, "#0EA5C6"));
      // pen
      const py = g.p.work !== null && g.p.work % 2 === 1 ? 1 : 0;
      c.line(x + w + 1, y - 3 + py, x + w - 2, y + 2 + py, "#3A4152");
      c.px(x + w + 1, y - 3 + py, "#22D3EE");
    }
    gripHand(g);
  },
};

// ------------------------------------------------------------------ SYNAPSE (Learning Agent)

const synapse: RobotDef = {
  rig: { headW: 21, headH: 17, torsoW: 16, torsoH: 12 },
  footMat: (k) => k.trim,
  torso: (g) =>
    torso(g, {
      shape: (w, h) =>
        shapeFrom(w, h, (x, y) => {
          // pear: narrow shoulders, round wide belly
          const t = y / (h - 1);
          const inset = t < 0.45 ? Math.round(3 - t * 4) : Math.round(Math.max(0, (t - 0.85) * 12));
          return x >= inset && x < w - inset;
        }),
      front: (g, b) => {
        g.c.shape(g.r.cx - 2, b.y + 5, ellipse(5, 5), g.k.acc);
        g.c.px(g.r.cx - 1, b.y + 6, "#FFFFFF");
      },
    }),
  shoulders: (g) => {
    const { c, k, torso: t, v } = g;
    const nodes = (x: number) => {
      c.line(x, t.y + 2, x + 3, t.y, k.trim.lo);
      c.line(x + 3, t.y, x + 5, t.y + 3, k.trim.lo);
      for (const [dx, dy] of [
        [0, 2],
        [3, 0],
        [5, 3],
      ]) {
        c.fill(x + dx - 1, t.y + dy - 1, 3, 3, OUTLINE);
        c.px(x + dx, t.y + dy, k.trim.hi);
      }
    };
    if (v === "side") {
      nodes(t.x + 1);
      return;
    }
    nodes(t.x - 3);
    nodes(t.x + t.w - 3);
  },
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? -1;
    // forked node antenna
    const ax = v === "side" ? b.x + Math.floor(b.w / 2) : g.r.cx;
    c.fill(ax - 1, b.y - 4, 3, 5, OUTLINE);
    c.vline(ax, b.y - 3, 4, k.joint.hi);
    c.line(ax, b.y - 4, ax - 3, b.y - 7, OUTLINE);
    c.line(ax, b.y - 4, ax + 3, b.y - 7, OUTLINE);
    ball(g, ax - 3, b.y - 8, 4, f === 0 ? mat("#FFFFFF", 0.3) : k.trim);
    ball(g, ax + 3, b.y - 8, 4, f === 1 ? mat("#FFFFFF", 0.3) : k.trim);
    head(g, {
      shape: (w, h) => rr(w, h, 8, 4),
      ears: { w: 4, h: 6, mat: k.trim, dy: 9, shape: (w, h) => ellipse(w, h) },
      visor: { dx: 3, dy: 9, w: b.w - 6, h: 6, shape: (w, h) => rr(w, h, 2) },
      eyes: twoEyes(3, 3, "round", 0.27),
      sideEyes: (g, vb) => eye(g, vb.x + vb.w - 4, vb.y + 1, 3, 3, "round"),
    });
    // translucent cap with nodes
    const gw = b.w - 4,
      gh = 8;
    const glass = "#B7C4FF";
    c.shape(
      b.x + 2,
      b.y + 1,
      rr(gw, gh, 7, 1),
      { hi: "#EEF1FF", mid: glass, lo: mix(glass, "#9A6BFF", 0.4), dk: mix(glass, "#9A6BFF", 0.6) },
      { outline: k.trim.lo, glint: true },
    );
    const pts: [number, number][] = [
      [4, 5],
      [8, 3],
      [12, 5],
      [15, 3],
    ].filter(([dx]) => dx < gw - 1) as [number, number][];
    for (let i = 0; i < pts.length - 1; i++)
      c.line(b.x + 2 + pts[i][0], b.y + pts[i][1], b.x + 2 + pts[i + 1][0], b.y + pts[i + 1][1], "#8E7BFF");
    pts.forEach(([dx, dy], i) => c.px(b.x + 2 + dx, b.y + dy, f >= 0 && i <= f ? "#FFFFFF" : "#6B4BEF"));
  },
  item: (g) =>
    slate(g, 9, 10, mat("#9A6BFF"), "#3A1C8C", (x, y) => {
      g.c.map(
        x + 1,
        y + 1,
        [".###.#", "#.#.##", "######", "#.#.##", ".###.#"].map((r) => r.slice(0, 6)),
        { "#": g.p.work !== null ? "#FFFFFF" : "#E2C8FF" },
      );
    }),
};

// ------------------------------------------------------------------ PATCH (System Guardian)

function hazardStrip(g: G, x: number, y: number, w: number, h: number) {
  for (let j = 0; j < h; j++)
    for (let i = 0; i < w; i++) g.c.px(x + i, y + j, ((i + j) >> 1) % 2 === 0 ? g.k.trim.mid : "#1A1A1F");
}

const patch: RobotDef = {
  rig: { headW: 22, headH: 15, torsoW: 20, torsoH: 13, legH: 6, legGap: 4 },
  legs: "stubby",
  footMat: (k) => k.trim,
  arms: (g) => ({
    thick: 4,
    mat: mat("#6B7385", 0.9),
    handMat: mat("#6B7385", 0.9),
    ...(g.p.work === null ? {} : { rightTo: { x: g.torso.x + g.torso.w + 2, y: g.torso.y + 5 + (g.p.work % 2) } }),
  }),
  pack: (g) => {
    const { c, k, v, torso: t } = g;
    const box = (x: number, y: number, w: number, h: number, plus: boolean) => {
      c.shape(x, y, rr(w, h, 1), mat("#5A6272"));
      c.hline(x + 1, y + 2, w - 2, k.trim.mid);
      if (plus) {
        c.fill(x + Math.floor(w / 2) - 1, y + 4, 2, 6, k.trim.hi);
        c.fill(x + Math.floor(w / 2) - 3, y + 6, 6, 2, k.trim.hi);
      }
    };
    if (v === "front") box(t.x - 6, t.y - 2, 8, 13, false);
    else if (v === "back") box(g.r.cx - 8, t.y - 3, 16, 14, true);
    else box(t.x - 7, t.y - 2, 9, 13, true);
  },
  torso: (g) =>
    torso(g, {
      shape: (w, h) => rr(w, h, 2),
      front: (g, b) => {
        hazardStrip(g, b.x + 2, b.y + b.h - 5, b.w - 4, 3);
        g.c.shape(g.r.cx - 3, b.y + 2, rr(6, 4, 1), mat("#2A2F3E", 0.4), { shade: "flat" });
        g.c.fill(g.r.cx - 2, b.y + 3, 1, 1, "#57EEA0");
        g.c.fill(g.r.cx, b.y + 3, 1, 1, g.k.acc.mid);
      },
      back: (g, b) => hazardStrip(g, b.x + 2, b.y + b.h - 5, b.w - 4, 3),
      side: (g, b) => hazardStrip(g, b.x + 1, b.y + b.h - 5, b.w - 2, 3),
    }),
  shoulders: (g) => {
    const { c, k, torso: t, v } = g;
    if (v === "side") {
      c.shape(t.x + 1, t.y - 1, rr(7, 4, 1), k.trim);
      return;
    }
    c.shape(t.x - 4, t.y - 1, rr(7, 4, 1), k.trim);
    c.shape(t.x + t.w - 3, t.y - 1, rr(7, 4, 1), k.trim);
  },
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    // rotating beacon cap
    const bx = v === "side" ? b.x + Math.floor(b.w / 2) - 4 : g.r.cx - 4;
    c.shape(bx - 1, b.y - 1, rr(10, 3, 1), mat("#3A4152"));
    c.shape(bx, b.y - 6, rr(8, 6, 3, 0), k.acc, { glint: false });
    const hx = bx + 1 + (f % 4) * 2;
    c.fill(Math.min(bx + 6, hx), b.y - 5, 2, 4, "#FFF3C4");
    if (g.p.work !== null) {
      const rays = [
        [-3, -4],
        [10, -4],
        [-2, -8],
        [9, -8],
      ];
      const [rx, ry] = rays[f % 4];
      c.fill(bx + rx, b.y + ry, 2, 1, "#FFD15C");
    }
    head(g, {
      shape: (w, h) => rr(w, h, 2),
      ears: { w: 4, h: 8, mat: mat("#3A4152"), shape: (w, h) => rect(w, h) },
      visor: { dx: 3, dy: 4, w: b.w - 6, h: 7, shape: (w, h) => rr(w, h, 1) },
      eyes: twoEyes(3, 4, "pill", 0.28),
    });
    if (v !== "back") c.fill(b.x + 2, b.y + b.h - 3, v === "side" ? b.w - 4 : 4, 1, k.trim.mid);
    if (v === "front") c.fill(b.x + b.w - 6, b.y + b.h - 3, 4, 1, k.trim.mid);
  },
  item: (g) => {
    const { c } = g;
    const f = g.p.work ?? 0;
    const h = g.hand;
    const tilt = g.p.work !== null && f % 2 === 1 ? 2 : 0;
    drawLimb(g, h.x, h.y, h.x + tilt, h.y - 9, 2, mat("#B9BCC6"));
    const jx = h.x + tilt - 3,
      jy = h.y - 14;
    c.shape(jx, jy, ascii(["##.##", "##.##", "#####", ".###."]), mat("#C9CFDB"));
    gripHand(g, mat("#6B7385", 0.9));
  },
};

export const WORKER_ART = {
  radar,
  archive,
  pulse,
  gavel,
  spark,
  story,
  boost,
  splice,
  glyph,
  quill,
  check,
  lock,
  dock,
  metric,
  synapse,
  patch,
} satisfies Record<string, RobotDef>;

export type { Box };
