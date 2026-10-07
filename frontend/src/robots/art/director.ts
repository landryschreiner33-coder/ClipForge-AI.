/** COMMAND, the boss. Largest body (1.35x), gold crest, jacket and tie, orange command tablet. */
import { mat, rr, trap } from "../pixel";
import { type G, type RobotDef, crownBadge } from "../rig";
import { atHand, gripHand, head, tablet, torso, twoEyes } from "./common";

function crest(g: G) {
  const { c, k, v, head: b } = g;
  const fin = (x: number, w: number, h: number, m = k.gold) => c.shape(x, b.y - h + 2, trap(w, h, 1, 0, 1), m);
  if (v === "side") {
    const x = b.x + Math.floor(b.w / 2) - 4;
    fin(x - 4, 4, 7, { ...k.gold, mid: k.gold.lo, hi: k.gold.mid });
    fin(x + 4, 4, 7);
    fin(x, 5, 10);
    return;
  }
  const cx = g.r.cx;
  fin(cx - 9, 4, 7);
  fin(cx + 5, 4, 7);
  fin(cx - 2, 5, 10);
}

function tails(g: G) {
  const { c, k, torso: t, v } = g;
  const y = t.y + t.h - 6;
  if (v === "side") {
    c.shape(t.x - 3, y, trap(6, 9, 0, 1), k.gold);
    return;
  }
  c.shape(t.x - 3, y, trap(7, 9, 0, 1), k.gold);
  c.shape(t.x + t.w - 4, y, trap(7, 9, 0, 1), k.gold);
}

const command: RobotDef = {
  rig: { torsoH: 16, headH: 20 },
  legs: "legs",
  footMat: (k) => k.gold,
  arms: (g) => {
    const t = g.torso;
    if (g.p.work === null) return {};
    const f = g.p.work;
    if (f === 2 || f === 3) return { leftTo: { x: t.x - 5, y: t.y - 7 + (f === 3 ? 1 : 0) } };
    return { leftTo: { x: t.x + t.w + 1, y: t.y + 3 + f } };
  },
  torso: (g) => {
    tails(g);
    const jacket = g.k.gold;
    torso(g, {
      mat: jacket,
      shape: (w, h) => rr(w, h, 4, 2),
      front: (g, b) => {
        const { c, k } = g;
        const cx = g.r.cx;
        // dark shirt panel, open jacket
        for (let j = 0; j < b.h - 2; j++) {
          const half = j < 2 ? 4 : j < 5 ? 3 : 2;
          c.fill(cx - half, b.y + j, half * 2, 1, "#16203A");
          c.px(cx - half - 1, b.y + j, k.gold.dk);
          c.px(cx + half, b.y + j, k.gold.dk);
        }
        // white collar points
        c.map(cx - 4, b.y, ["##....##", ".#....#."], { "#": "#F3F4F7" });
        // tie
        c.fill(cx - 1, b.y + 1, 2, 2, k.gold.hi);
        c.fill(cx - 1, b.y + 3, 2, 7, k.gold.mid);
        c.px(cx - 1, b.y + 3, k.gold.hi);
        c.fill(cx - 1, b.y + 10, 2, 1, k.gold.lo);
        // buttons
        c.px(cx - 4, b.y + 9, "#F3F4F7");
        c.px(cx + 3, b.y + 9, "#F3F4F7");
        crownBadge(g, b.x + 2, b.y + 4);
      },
      back: (g, b) => {
        const { c, k } = g;
        c.vline(g.r.cx, b.y + 5, b.h - 5, k.gold.dk);
        c.hline(b.x + 3, b.y + 1, b.w - 6, "#F3F4F7");
      },
      side: (g, b) => {
        const { c, k } = g;
        c.fill(b.x + b.w - 3, b.y + 1, 2, b.h - 4, "#16203A");
        c.vline(b.x + b.w - 4, b.y + 1, b.h - 4, k.gold.dk);
        c.px(b.x + b.w - 2, b.y + 2, k.gold.hi);
      },
    });
  },
  shoulders: (g) => {
    const { c, k, torso: t, v } = g;
    const pad = (x: number) => {
      c.shape(x, t.y - 1, rr(9, 6, 2), k.shell);
      c.hline(x + 1, t.y + 3, 7, k.gold.mid);
    };
    if (v === "side") {
      pad(t.x + 1);
      return;
    }
    pad(t.x - 6);
    pad(t.x + t.w - 3);
  },
  head: (g) => {
    crest(g);
    head(g, {
      shape: (w, h) => rr(w, h, 6, 4),
      ears: { w: 5, h: 9, mat: g.k.gold, front: true },
      visor: { dx: 3, dy: 5, w: 22, h: 11, shape: (w, h) => rr(w, h, 3) },
      eyes: twoEyes(4, 6, "pill", 0.27),
    });
    if (g.v !== "back") g.c.hline(g.head.x + 6, g.head.y + g.head.h - 3, g.head.w - 12, g.k.shell.lo);
  },
  item: (g) => {
    const side = g.v === "side";
    const w = side ? 5 : 14,
      h = 10;
    const { x, y } = atHand(g, w, h, side ? 2 : 3, 4);
    const k = g.k;
    const f = g.p.work ?? -1;
    tablet(g, x, y, w, h, k.acc, "#FFB05C", (sx, sy, sw) => {
      if (side) return;
      for (let i = 0; i < 3; i++)
        g.c.hline(sx + 2, sy + 1 + i * 2, sw - 4 - i * 2, i === f % 3 ? "#FFFFFF" : "#8A3F0A");
      g.c.fill(sx + sw - 4, sy + 6, 3, 1, "#8A3F0A");
    });
    gripHand(g);
  },
  itemBack: (g) => {
    // tablet edge peeking out at the right of the body in back view
    g.c.shape(g.torso.x - 5, g.torso.y + 2, rr(3, 10, 1), mat("#FF8A2A"));
  },
};

export const DIRECTOR_ART = { command } satisfies Record<string, RobotDef>;
