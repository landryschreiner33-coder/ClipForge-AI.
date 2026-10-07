/**
 * Manager art (8 roles, 1.15x a worker). Every manager shares the rank kit: crown badge on the
 * chest, shoulder tabs in their trim and a command tablet in hand. Everything else is unique.
 */
import {
  OUTLINE,
  type Color,
  ascii,
  darken,
  ellipse,
  lighten,
  mat,
  mix,
  octo,
  rect,
  rr,
  shapeFrom,
  subtract,
  trap,
} from "../pixel";
import type { Mat } from "../pixel";
import { type Box, type G, type RobotDef, crownBadge, eye, shoulderTabs } from "../rig";
import { antenna, atHand, ball, displayMode, gripHand, head, reel, tablet, torso, twoEyes } from "./common";

/** Shared manager torso: crown badge (viewer-left) + role symbol (viewer-right). */
function mgrTorso(g: G, symbol: (x: number, y: number, b: Box) => void, m = g.k.shell, back?: (g: G, b: Box) => void) {
  torso(g, {
    mat: m,
    front: (g, b) => {
      crownBadge(g, b.x + 1, b.y + 3);
      symbol(b.x + b.w - 8, b.y + 3, b);
      g.c.hline(b.x + 2, b.y + b.h - 3, b.w - 4, g.k.trim.lo);
    },
    back:
      back ??
      ((g, b) => {
        g.c.hline(b.x + 3, b.y + 4, b.w - 6, m.lo);
        g.c.hline(b.x + 3, b.y + 6, b.w - 6, m.lo);
        g.c.hline(b.x + 2, b.y + b.h - 3, b.w - 4, g.k.trim.lo);
      }),
    side: (g, b) => {
      g.c.hline(b.x + 1, b.y + b.h - 3, b.w - 2, g.k.trim.lo);
      g.c.fill(b.x + b.w - 3, b.y + 3, 2, 3, g.k.gold.mid);
    },
  });
}

/** Held command tablet in the near hand. Side view shows it edge-on (narrow). */
function mgrTablet(
  g: G,
  w: number,
  h: number,
  frame: Mat,
  screen: Color,
  icon: (x: number, y: number, w: number, h: number) => void,
) {
  const side = g.v === "side";
  const tw = side ? 4 : w;
  const { x, y } = atHand(g, tw, h, side ? 1 : 3, 4);
  tablet(g, x, y, tw, h, frame, screen, side ? undefined : icon);
  gripHand(g);
}

function tabletBack(g: G, m: Mat) {
  g.c.shape(g.torso.x - 5, g.torso.y + 2, rr(3, 11, 1), m);
}

const sym = (g: G, x: number, y: number) =>
  g.c.shape(x, y, rr(7, 7, 1), mat(darken(g.k.face.mid, 0.05), 0.3), { shade: "flat" });

// ------------------------------------------------------------------ TRACKER

const tracker: RobotDef = {
  rig: { headW: 24, headH: 17 },
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      sym(g, x, y);
      const c = g.c,
        k = g.k;
      c.map(x + 1, y + 1, ["..#..", ".#.#.", "#.o.#", ".#.#.", "..#.."], { "#": k.trim.mid, o: "#FFFFFF" });
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    // radar arch over the head
    if (v === "side") {
      const x = b.x + Math.floor(b.w / 2) - 2;
      c.shape(x, b.y - 6, rr(4, 12, 1), k.trim);
      c.shape(x - 1, b.y - 10, ellipse(6, 6), k.trim);
      c.px(x + 2, b.y - 8, "#FFFFFF");
    } else {
      const aw = b.w + 6,
        ah = 15;
      const arch = subtract(rr(aw, ah, 7, 0), rr(aw - 6, ah, 5, 0), 3, 3);
      c.shape(b.x - 3, b.y - 6, arch, k.trim);
      // apex compass disc
      c.shape(g.r.cx - 4, b.y - 11, ellipse(8, 8), k.trim);
      c.shape(g.r.cx - 2, b.y - 9, ellipse(4, 4), mat("#0F2A14", 0.3), { outline: false, shade: "flat" });
      c.px(g.r.cx - 1, b.y - 8, v === "back" ? k.trim.lo : "#FFFFFF");
      if (f === 1 || f === 2) {
        const r = f === 1 ? 6 : 8;
        for (let a = 0; a < 20; a++) {
          const t = Math.PI + (a / 19) * Math.PI;
          c.px(Math.round(g.r.cx + Math.cos(t) * r), Math.round(b.y - 7 + Math.sin(t) * r), k.trim.hi);
        }
      }
    }
    head(g, {
      shape: (w, h) => rr(w, h, 5, 3),
      ears: { w: 5, h: 9, mat: k.trim, front: true },
      visor: { dx: 2, dy: 5, w: b.w - 4, h: 9, shape: (w, h) => rr(w, h, 4) },
      eyes: twoEyes(5, 5, "round", 0.24),
      sideEyes: (g, vb) => eye(g, vb.x + vb.w - 6, vb.y + 2, 4, 5, "round"),
    });
  },
  item: (g) =>
    mgrTablet(g, 12, 13, mat("#1E9E50"), "#2FBF5A", (x, y, w, h) => {
      const c = g.c;
      c.line(x + 1, y + h - 2, x + 4, y + 5, "#C8FFB0");
      c.line(x + 4, y + 5, x + 8, y + 7, "#C8FFB0");
      c.line(x + 8, y + 7, x + w - 1, y + 2, "#C8FFB0");
      const blink = (g.p.work ?? 0) === 1;
      c.map(x + 5, y + 1, [".###.", "##.##", ".###.", "..#.."], { "#": blink ? "#FFFFFF" : "#FF5A5A" });
    }),
  itemBack: (g) => tabletBack(g, mat("#1E9E50")),
};

// ------------------------------------------------------------------ VECTOR

function vectorDisplay(g: G, vb: Box, sideOnly = false) {
  const col = displayMode(g, vb);
  if (!col) return;
  const { c } = g;
  const f = g.p.work ?? 0;
  const mid = vb.x + Math.floor(vb.w / 2);
  const bars = [
    [3, 5, 7],
    [5, 7, 4],
    [7, 4, 6],
    [4, 6, 7],
  ][f % 4];
  const baseY = vb.y + vb.h - 2;
  const bx = sideOnly ? vb.x + 1 : vb.x + 3;
  bars.forEach((h, i) => c.fill(bx + i * 3, baseY - h + 1, 2, h, i === 2 ? lighten(col, 0.4) : col));
  if (sideOnly) return;
  c.vline(mid, vb.y + 1, vb.h - 2, g.k.shell.lo);
  // pie
  const px = mid + 3,
    py = vb.y + 1,
    s = 7;
  c.blot(px, py, ellipse(s, s), col);
  const wedge = f % 4;
  const q = [
    [1, 0],
    [1, 1],
    [0, 1],
    [0, 0],
  ][wedge];
  for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) c.px(px + q[0] * 4 + i, py + q[1] * 4 + j, g.k.face.mid);
  c.px(px + 3, py + 3, g.k.face.mid);
}

const vector: RobotDef = {
  rig: { headW: 27, headH: 17 },
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      sym(g, x, y);
      g.c.fill(x + 1, y + 4, 1, 2, g.k.acc.mid);
      g.c.fill(x + 3, y + 2, 1, 4, g.k.acc.mid);
      g.c.fill(x + 5, y + 1, 1, 5, g.k.trim.hi);
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    // two short bar antennae
    const xs = v === "side" ? [b.x + Math.floor(b.w / 2)] : [b.x + 5, b.x + b.w - 6];
    for (const x of xs) {
      c.fill(x - 1, b.y - 5, 3, 6, OUTLINE);
      c.vline(x, b.y - 4, 5, k.joint.hi);
      c.shape(x - 1, b.y - 6, rr(3, 2, 0), k.trim);
    }
    head(g, {
      shape: (w, h) => trap(w, h, 0, 3, 3),
      sideShape: (w, h) => trap(w, h, 0, 1, 3),
      ears: { w: 4, h: 7, mat: k.trim, dy: 5 },
      visor: { dx: 2, dy: 3, w: b.w - 4, h: 10, shape: (w, h) => trap(w, h, 0, 1, 2) },
      eyes: (g, vb) => vectorDisplay(g, vb),
      sideEyes: (g, vb) => vectorDisplay(g, vb, true),
    });
  },
  item: (g) =>
    mgrTablet(g, 12, 12, mat("#2F6BFF"), "#123A9C", (x, y, w, h) => {
      const f = g.p.work ?? 0;
      [3, 5, 4, 7].forEach((bh, i) =>
        g.c.fill(
          x + 1 + i * 3,
          y + h - Math.min(h - 1, bh + (i === f % 4 ? 1 : 0)),
          2,
          Math.min(h - 1, bh + (i === f % 4 ? 1 : 0)),
          "#28D9FF",
        ),
      );
      g.c.line(x + 1, y + 3, x + w - 2, y + 1, "#FFFFFF");
    }),
  itemBack: (g) => tabletBack(g, mat("#2F6BFF")),
};

// ------------------------------------------------------------------ FRAME

function clapper(g: G, x: number, y: number, open: boolean) {
  const { c } = g;
  const board = mat("#7B2FD0");
  c.shape(x, y + 3, rr(13, 10, 1), board);
  c.fill(x + 1, y + 4, 11, 8, "#2A0F4A");
  c.map(x + 5, y + 6, ["#..", "##.", "###", "##.", "#.."], { "#": "#FF7AD9" });
  // striped clapper top
  const top = shapeFrom(13, 3, () => true);
  const ty = open ? y - 1 : y + 1;
  c.shape(x, ty, top, mat("#F3F4F7", 0.5));
  for (let i = 0; i < 13; i += 4) {
    c.fill(x + i, ty, 2, 3, OUTLINE);
  }
  if (open) c.line(x, y + 2, x, ty + 2, OUTLINE);
}

const frame: RobotDef = {
  rig: { headW: 24, headH: 19 },
  footMat: (k) => k.trim,
  torso: (g) =>
    mgrTorso(
      g,
      (x, y) => {
        sym(g, x, y);
        reel(g, x + 1, y + 1, 5, mat("#FF7AD9"));
      },
      mat("#E64BB0", 0.9),
    ),
  shoulders: (g) => shoulderTabs(g, mat("#F3F4F7", 0.7)),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    // top antenna nub
    if (v !== "side") {
      c.shape(g.r.cx - 1, b.y - 4, rect(2, 5), k.joint);
      c.shape(g.r.cx - 2, b.y - 5, rr(4, 2, 0), k.trim);
    }
    const reelAt = () => {
      if (v === "front") reel(g, b.x - 6, b.y - 3, 12, k.trim, f);
      else if (v === "back") reel(g, b.x + b.w - 6, b.y - 3, 12, k.trim, f);
      else reel(g, b.x - 5, b.y - 2, 12, k.trim, f);
    };
    if (v === "side") reelAt();
    head(g, {
      shape: (w, h) => rr(w, h, 2),
      ears: { w: 4, h: 8, mat: k.trim },
      visor: { dx: 3, dy: 7, w: b.w - 6, h: 7, shape: (w, h) => rr(w, h, 1) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        g.c.map(vb.x + 2, vb.y + 1, ["#...", "##..", "###.", "##..", "#..."], { "#": col });
        for (let i = 0; i < 3; i++)
          g.c.fill(
            vb.x + 8 + i * 3,
            vb.y + 2,
            2,
            2,
            i === f % 3 && g.p.work !== null ? "#FFFFFF" : mix(col, "#FFFFFF", 0.2),
          );
      },
    });
    // helmet cap band
    c.fill(b.x + 1, b.y + 1, b.w - 2, 4, k.trim.mid);
    c.hline(b.x + 1, b.y + 1, b.w - 2, k.trim.hi);
    c.hline(b.x + 1, b.y + 5, b.w - 2, OUTLINE);
    if (v !== "side") reelAt();
  },
  item: (g) => {
    if (g.v === "side") {
      mgrTablet(g, 4, 12, mat("#7B2FD0"), "#2A0F4A", () => {});
      return;
    }
    const { x, y } = atHand(g, 13, 13, 3, 4);
    clapper(g, x, y, (g.p.work ?? 1) === 0);
    gripHand(g);
  },
  itemBack: (g) => tabletBack(g, mat("#7B2FD0")),
};

// ------------------------------------------------------------------ SCRIPT

const script: RobotDef = {
  rig: { headW: 22, headH: 21 },
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      g.c.shape(x - 2, y, rr(9, 7, 1), mat(darken(g.k.face.mid, 0.05), 0.3), { shade: "flat" });
      g.c.text(x - 1, y + 1, "CC", g.k.trim.hi);
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    head(g, {
      shape: (w, h) => trap(w, h, 2, 0, 4),
      ears: { w: 4, h: 9, mat: k.trim, dy: 7 },
      visor: { dx: 4, dy: 7, w: b.w - 8, h: 10, shape: (w, h) => rr(w, h, 2) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const y = vb.y + 2 + (g.p.eyes === "down" ? 1 : 0),
          h = 6;
        const lx = vb.x + 3 + g.p.lookX,
          rx = vb.x + vb.w - 5 + g.p.lookX;
        c.vline(lx, y, h, col);
        c.hline(lx, y, 2, col);
        c.hline(lx, y + h - 1, 2, col);
        c.vline(rx + 1, y, h, col);
        c.hline(rx, y, 2, col);
        c.hline(rx, y + h - 1, 2, col);
        if (g.p.work === 0) c.vline(vb.x + Math.floor(vb.w / 2), y + 1, h - 2, "#FFFFFF");
      },
      sideEyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const x = vb.x + vb.w - 3,
          y = vb.y + 2;
        c.vline(x + 1, y, 6, col);
        c.hline(x, y, 2, col);
        c.hline(x, y + 5, 2, col);
      },
    });
    if (v !== "back") {
      // keycap top face
      const tw = v === "side" ? b.w - 6 : b.w - 8;
      c.shape(
        b.x + (v === "side" ? 2 : 4),
        b.y + 2,
        rr(tw, 3, 1),
        { ...k.shell, mid: k.shell.hi },
        { outline: k.shell.lo, shade: "flat" },
      );
    } else {
      c.shape(
        b.x + 4,
        b.y + 2,
        rr(b.w - 8, 3, 1),
        { ...k.shell, mid: k.shell.hi },
        { outline: k.shell.lo, shade: "flat" },
      );
    }
  },
  item: (g) =>
    mgrTablet(g, 11, 13, mat("#7B3DFF"), "#3A1C8C", (x, y, w, h) => {
      for (let i = 0; i < 4; i++) g.c.hline(x + 1, y + 1 + i * 2, w - 3 - (i % 2) * 2, "#C9B5FF");
      g.c.map(x + w - 5, y + h - 4, ["...#", "#.#.", ".#.."], { "#": g.p.work === 1 ? "#FFFFFF" : "#57EEA0" });
    }),
  itemBack: (g) => tabletBack(g, mat("#7B3DFF")),
};

// ------------------------------------------------------------------ CLOCK

function calendarPack(g: G, x: number, y: number, w: number, h: number, grid: boolean) {
  const { c, k } = g;
  c.shape(x, y, rr(w, h, 2), k.trim);
  if (!grid) return;
  c.fill(x + 2, y + 2, w - 4, h - 4, "#FFF3E2");
  c.fill(x + 2, y + 2, w - 4, 2, k.acc.mid);
  for (let j = 0; j < 3; j++)
    for (let i = 0; i < 3; i++)
      c.fill(x + 3 + i * Math.floor((w - 5) / 3), y + 5 + j * 3, 2, 2, j === 1 && i === 1 ? k.acc.mid : "#C9B9A4");
}

const clock: RobotDef = {
  rig: { headW: 23, headH: 22 },
  pack: (g) => {
    const { v, torso: t, head: b } = g;
    if (v === "front") calendarPack(g, t.x - 7, t.y - 5, 10, 16, false);
    else if (v === "back") calendarPack(g, g.r.cx - 8, t.y - 3, 16, 16, true);
    else calendarPack(g, t.x - 8, t.y - 4, 10, 15, false);
    void b;
  },
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      sym(g, x, y);
      g.c.fill(x + 1, y + 1, 5, 1, g.k.trim.mid);
      g.c.fill(x + 3, y + 3, 1, 2, "#FFFFFF");
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? 0;
    // alarm button on top
    c.shape(g.r.cx - 2 + (v === "side" ? 1 : 0), b.y - 3, rr(4, 4, 1), k.trim);
    head(g, { shape: (w, h) => ellipse(w, h), backPanel: false });
    if (v === "back") {
      c.shape(b.x + 3, b.y + 3, ellipse(b.w - 6, b.h - 6), k.trim, { glint: false });
      c.shape(b.x + 6, b.y + 6, ellipse(b.w - 12, b.h - 12), k.shell, { glint: false });
      c.shape(b.x - 2, b.y + 8, ellipse(6, 6), mat("#F3F4F7", 0.5)); // dial on the far side
      return;
    }
    if (v === "side") {
      c.shape(b.x + b.w - 6, b.y + 2, rr(6, b.h - 4, 3), k.trim, { glint: false });
      c.shape(b.x + b.w - 4, b.y + 4, rr(3, b.h - 8, 1), k.face, { outline: false, shade: "flat" });
      eye(g, b.x + b.w - 3, b.y + 8, 2, 3, "pill");
      // side dial
      c.shape(b.x + 2, b.y + 8, ellipse(7, 7), mat("#F3F4F7", 0.5));
      c.vline(b.x + 5, b.y + 9, 3, OUTLINE);
      c.hline(b.x + 5, b.y + 11, 2, OUTLINE);
      return;
    }
    // ring + face
    c.shape(b.x + 2, b.y + 2, ellipse(b.w - 4, b.h - 4), k.trim, { glint: false });
    const fw = b.w - 9,
      fh = b.h - 9;
    const fx = b.x + 4 + 1,
      fy = b.y + 4 + 1;
    c.shape(
      fx - 1,
      fy - 1,
      ellipse(fw + 2, fh + 2),
      { hi: k.face.mid, mid: k.face.mid, lo: k.face.mid, dk: k.face.mid },
      { shade: "flat" },
    );
    // hour ticks
    const cx = fx + Math.floor(fw / 2),
      cy = fy + Math.floor(fh / 2);
    c.fill(cx, fy, 1, 2, k.trim.hi);
    c.fill(cx, fy + fh - 2, 1, 2, k.trim.lo);
    c.fill(fx, cy, 2, 1, k.trim.lo);
    c.fill(fx + fw - 2, cy, 2, 1, k.trim.lo);
    // clock hand (rotates while working)
    const ang = (-90 + f * 90) * (Math.PI / 180);
    c.line(cx, cy + 3, Math.round(cx + Math.cos(ang) * 3), Math.round(cy + 3 + Math.sin(ang) * 3), k.trim.hi);
    // arc eyes
    const ev = { x: fx + 1, y: cy - 3, w: fw - 2, h: 4 };
    if (g.p.eyes === "open" || g.p.eyes === "down") twoEyes(4, 3, "arc", 0.22)(g, ev);
    else twoEyes(4, 3, "pill", 0.22)(g, ev);
    // side dial (viewer-left)
    c.shape(b.x - 4, b.y + 8, ellipse(7, 7), mat("#F3F4F7", 0.5));
    c.shape(b.x - 3, b.y + 9, ellipse(5, 5), mat("#FFF3E2", 0.3), { outline: k.trim.mid, shade: "flat" });
    c.vline(b.x - 1, b.y + 10, 2, OUTLINE);
    c.px(b.x, b.y + 11, OUTLINE);
  },
  item: (g) =>
    mgrTablet(g, 11, 13, mat("#FF7A1A"), "#FFE0B8", (x, y, w, h) => {
      for (let i = 0; i < 4; i++)
        g.c.hline(x + 1, y + 2 + i * 2, w - 3 - (i === 3 ? 3 : 0), i === (g.p.work ?? -1) ? "#FF7A1A" : "#B07A44");
      g.c.px(x - 1, y + Math.floor(h / 2), OUTLINE);
      g.c.px(x + w, y + Math.floor(h / 2), OUTLINE);
    }),
  itemBack: (g) => tabletBack(g, mat("#FF7A1A")),
};

// ------------------------------------------------------------------ HARBOR

function cargoPack(g: G, x: number, y: number, w: number, h: number, arrow: boolean) {
  const { c, k } = g;
  c.shape(x, y, rr(w, h, 2), k.trim);
  c.hline(x + 1, y + Math.floor(h / 2), w - 2, k.trim.dk);
  c.vline(x + 3, y + 1, h - 2, k.trim.lo);
  c.vline(x + w - 4, y + 1, h - 2, k.trim.lo);
  if (arrow) {
    const ax = x + Math.floor(w / 2) - 3,
      ay = y + 3;
    c.shape(ax, ay, rr(7, 9, 1), mat("#0F3D24", 0.3), { outline: false, shade: "flat" });
    c.map(ax + 1, ay + 1, ["..#..", ".###.", "#####", ".###.", ".###.", ".###.", ".###."], { "#": "#E9FFF1" });
  }
}

const harbor: RobotDef = {
  rig: { headW: 27, headH: 17, torsoW: 19 },
  pack: (g) => {
    const { v, torso: t } = g;
    if (v === "front") cargoPack(g, g.r.cx - 17, t.y - 6, 34, 16, false);
    else if (v === "back") cargoPack(g, g.r.cx - 13, t.y - 7, 26, 18, true);
    else cargoPack(g, t.x - 10, t.y - 6, 13, 17, false);
  },
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      g.c.shape(x, y, ascii(["#######", "#######", "#######", ".#####.", "..###..", "...#..."]), g.k.trim);
      g.c.vline(x + 3, y + 1, 4, g.k.trim.hi);
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? -1;
    // uplink mast + dish
    const mx = v === "side" ? b.x + 4 : v === "back" ? b.x + 6 : b.x + b.w - 7;
    antenna(g, mx, b.y - 7, b.y + 1, (x, y) => {
      c.shape(x - 3, y - 3, ellipse(7, 4), k.trim);
      c.px(x, y - 2, f === 1 || f === 2 ? "#FFFFFF" : k.trim.hi);
      if (f === 2) {
        c.px(x + 4, y - 5, k.trim.hi);
        c.px(x + 5, y - 4, k.trim.hi);
        c.px(x + 5, y - 6, k.trim.hi);
      }
    });
    head(g, {
      shape: (w, h) => rr(w, h, 3),
      ears: { w: 4, h: 8, mat: k.trim, dy: 6 },
      visor: { dx: 3, dy: 6, w: b.w - 6, h: 8, shape: (w, h) => rr(w, h, 2) },
      eyes: twoEyes(4, 4, "pill", 0.27),
    });
    // cargo helmet brim band with rivets
    c.fill(b.x + 1, b.y + 1, b.w - 2, 3, k.trim.mid);
    c.hline(b.x + 1, b.y + 1, b.w - 2, k.trim.hi);
    c.hline(b.x, b.y + 4, b.w, OUTLINE);
    for (let i = 3; i < b.w - 2; i += 5) c.px(b.x + i, b.y + 2, k.trim.dk);
  },
  item: (g) =>
    mgrTablet(g, 11, 13, mat("#1E9E50"), "#E8FFF0", (x, y, w) => {
      for (let i = 0; i < 4; i++) {
        g.c.fill(x + 1, y + 1 + i * 3, 2, 2, "#1E9E50");
        if (i <= (g.p.work ?? 3)) g.c.px(x + 1, y + 1 + i * 3, "#FFFFFF");
        g.c.hline(x + 4, y + 2 + i * 3, w - 5, "#7FA08B");
      }
    }),
  itemBack: (g) => tabletBack(g, mat("#1E9E50")),
};

// ------------------------------------------------------------------ SWITCH

function hazard(g: G, x: number, y: number, w: number, h: number) {
  for (let j = 0; j < h; j++)
    for (let i = 0; i < w; i++) g.c.px(x + i, y + j, ((i + j) >> 1) % 2 === 0 ? g.k.trim.mid : "#1A1A1F");
}

const switchBot: RobotDef = {
  rig: { headW: 25, headH: 19 },
  arms: { mat: mat("#8A93A6", 0.9) },
  footMat: (k) => k.trim,
  torso: (g) => {
    mgrTorso(g, (x, y) => {
      hazard(g, x, y + 1, 7, 4);
      g.c.shape(x, y + 1, rect(7, 4), mat("#000000"), { outline: OUTLINE, shade: "flat" });
      hazard(g, x, y + 1, 7, 4);
    });
    // tool belt
    const { c, torso: b, v } = g;
    const by = b.y + b.h - 4;
    c.fill(b.x, by, b.w, 3, "#6B4A2A");
    c.hline(b.x, by, b.w, "#8C6A44");
    if (v === "front") {
      c.shape(b.x + 2, by, rr(4, 4, 1), mat("#8C6A44"));
      c.shape(b.x + b.w - 6, by, rr(4, 4, 1), mat("#8C6A44"));
      c.fill(g.r.cx - 1, by, 3, 3, g.k.trim.mid);
    }
  },
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { k, v, head: b } = g;
    const f = g.p.work ?? 0;
    const xs = v === "side" ? [b.x + Math.floor(b.w / 2)] : [b.x + 7, b.x + b.w - 8];
    for (const x of xs) antenna(g, x, b.y - 5, b.y + 1, (x, y) => ball(g, x, y, 3, k.trim));
    head(g, {
      shape: (w, h) => octo(w, h, 6, 4),
      ears: { w: 4, h: 10, mat: k.trim, dy: 4, shape: (w, h) => rr(w, h, 1) },
      visor: { dx: 3, dy: 4, w: b.w - 6, h: 10, shape: (w, h) => octo(w, h, 2, 2) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const s = 7;
        const y = vb.y + Math.floor((vb.h - s) / 2) + (g.p.eyes === "down" ? 1 : 0);
        for (const x of [vb.x + 2, vb.x + vb.w - s - 2]) {
          g.c.blot(x + g.p.lookX, y, ellipse(s, s), col);
          const inner = f % 2 === 1 ? 5 : 3;
          g.c.blot(
            x + g.p.lookX + Math.floor((s - inner) / 2),
            y + Math.floor((s - inner) / 2),
            ellipse(inner, inner),
            k.face.mid,
          );
          g.c.px(x + g.p.lookX + 1, y + 1, lighten(col, 0.6));
        }
      },
      sideEyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        g.c.blot(vb.x + vb.w - 6, vb.y + 2, ellipse(5, 6), col);
        g.c.blot(vb.x + vb.w - 4, vb.y + 4, ellipse(2, 2), k.face.mid);
      },
    });
    if (v !== "back") hazard(g, v === "side" ? b.x + b.w - 9 : g.r.cx - 6, b.y + b.h - 4, v === "side" ? 7 : 12, 2);
    else hazard(g, g.r.cx - 6, b.y + 2, 12, 2);
  },
  item: (g) =>
    mgrTablet(g, 12, 12, mat("#FF7A1A"), "#3A1A05", (x, y, w) => {
      const f = g.p.work ?? 0;
      const gear =
        f % 2 === 0 ? [".#.#.", "#####", "##.##", "#####", ".#.#."] : ["#.#.#", ".###.", "##.##", ".###.", "#.#.#"];
      g.c.map(x + 1, y + 3, gear, { "#": "#FFB020" });
      g.c.map(x + w - 5, y + 1, ["..#..", ".#.#.", "#.#.#", "#####"], { "#": "#FFB020" });
    }),
  itemBack: (g) => tabletBack(g, mat("#FF7A1A")),
};

// ------------------------------------------------------------------ CURATOR

const curator: RobotDef = {
  rig: { headW: 24, headH: 20 },
  footMat: (k) => k.trim,
  torso: (g) =>
    mgrTorso(g, (x, y) => {
      sym(g, x, y);
      g.c.blot(x + 2, y + 2, ellipse(3, 3), g.k.trim.hi);
    }),
  shoulders: (g) => shoulderTabs(g),
  head: (g) => {
    const { c, k, v, head: b } = g;
    const f = g.p.work ?? -1;
    // three-node crown
    const cx = v === "side" ? b.x + Math.floor(b.w / 2) : g.r.cx;
    const nodes: [number, number][] =
      v === "side"
        ? [[cx, b.y - 6]]
        : [
            [cx - 6, b.y - 2],
            [cx, b.y - 6],
            [cx + 6, b.y - 2],
          ];
    if (nodes.length === 3) {
      c.line(nodes[0][0], nodes[0][1], nodes[1][0], nodes[1][1], k.trim.lo);
      c.line(nodes[1][0], nodes[1][1], nodes[2][0], nodes[2][1], k.trim.lo);
    }
    c.vline(cx, b.y - 4, 4, k.trim.lo);
    nodes.forEach(([x, y], i) => ball(g, x, y, 5, i === f ? mat("#FFFFFF", 0.3) : k.trim));
    head(g, {
      shape: (w, h) => rr(w, h, 10, 4),
      ears: { w: 5, h: 8, mat: k.trim, dy: 9, shape: (w, h) => ellipse(w, h) },
      visor: { dx: 3, dy: 10, w: b.w - 6, h: 8, shape: (w, h) => rr(w, h, 3) },
      eyes: (g, vb) => {
        const col = displayMode(g, vb);
        if (!col) return;
        const y = vb.y + 2 + (g.p.eyes === "down" ? 1 : 0);
        const lx = vb.x + 3 + g.p.lookX,
          rx = vb.x + vb.w - 6 + g.p.lookX,
          mx = vb.x + Math.floor(vb.w / 2) + g.p.lookX;
        c.line(lx + 1, y + 1, mx, y + 3, mix(col, k.face.mid, 0.4));
        c.line(mx, y + 3, rx + 1, y + 1, mix(col, k.face.mid, 0.4));
        g.c.blot(lx, y, ellipse(3, 3), col);
        g.c.blot(rx, y, ellipse(3, 3), col);
        g.c.px(mx, y + 3, lighten(col, 0.5));
      },
    });
    // glass dome over the top half
    const gw = v === "side" ? b.w - 4 : b.w - 4,
      gh = 9;
    const glass = mix(k.trim.hi, "#FFFFFF", 0.35);
    c.shape(
      b.x + 2,
      b.y + 1,
      rr(gw, gh, 7, 1),
      { hi: "#FFFFFF", mid: glass, lo: mix(glass, k.trim.mid, 0.4), dk: mix(glass, k.trim.mid, 0.6) },
      { outline: k.trim.lo, glint: true },
    );
    const dots: [number, number][] = [
      [5, 4],
      [9, 6],
      [13, 3],
      [17, 6],
      [8, 3],
    ];
    dots.forEach(([dx, dy], i) => {
      if (dx < gw - 1) c.px(b.x + 2 + dx, b.y + dy, i === (f + 1) % 5 ? "#FFFFFF" : k.trim.mid);
    });
  },
  item: (g) =>
    mgrTablet(g, 11, 13, mat("#8F6BFF"), "#2C1A66", (x, y, w, h) => {
      const cx = x + Math.floor(w / 2) - 2;
      g.c.map(cx, y + 2, [".###.", "#...#", ".###.", "#...#", ".###.", "#...#", ".###."], {
        "#": g.p.work !== null ? "#FFFFFF" : "#C9A8FF",
      });
      void h;
    }),
  itemBack: (g) => tabletBack(g, mat("#8F6BFF")),
};

export const MANAGER_ART = {
  tracker,
  vector,
  frame,
  script,
  clock,
  harbor,
  switch: switchBot,
  curator,
} satisfies Record<string, RobotDef>;
