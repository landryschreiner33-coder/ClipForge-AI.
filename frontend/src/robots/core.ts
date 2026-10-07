/**
 * CORE (Brain Core): a stationary glass chamber with a pixel brain/neural pattern on a base.
 * Not a robot. Four activities share the same body; only lights and particles change.
 */
import { OUTLINE, Painter, ascii, ellipse, layerToPaths, mat, mix, rr, type PathRun } from "./pixel";
import { CORE, type CoreActivity } from "./registry";

const cache = new Map<string, PathRun[]>();

const BRAIN = [
  "......######......",
  "...############...",
  "..##############..",
  ".################.",
  "##################",
  "##################",
  "##################",
  ".################.",
  "..######..######..",
  "...####....####...",
  "........##........",
  "........##........",
];

export function renderCore(activity: CoreActivity, frameIn: number): PathRun[] {
  const f = ((Math.floor(frameIn) % CORE.anim.frames) + CORE.anim.frames) % CORE.anim.frames;
  const key = `${activity}|${f}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const c = new Painter();
  const glass = CORE.palette.glass,
    glow = CORE.palette.glow;
  const pulse = activity === "idle" ? [0, 1, 2, 1][f] : 2;
  const amber = "#FFAB45";

  // shadow
  c.to("back").blot(9, 58, ellipse(30, 5), "#00000055");
  c.to("base");
  // base pedestal
  const base = mat(CORE.palette.base, 0.9);
  c.shape(8, 49, rr(32, 10, 2, 1), base);
  c.shape(11, 46, rr(26, 5, 1), mat("#3A4568", 0.8));
  // base lights (activity readout)
  const lights = activity === "updating" ? 4 : activity === "evaluating" ? 3 : activity === "lookup" ? 2 : 1;
  for (let i = 0; i < 5; i++) {
    const on = activity === "updating" ? i <= f + 1 : i < lights;
    c.fill(13 + i * 5, 53, 3, 2, on ? (activity === "evaluating" ? amber : glow) : "#1B2238");
  }
  // glass chamber
  const chamberW = 26,
    chamberH = 36;
  const cx = 11,
    cy = 11;
  const glassMat = {
    hi: mix(glass, "#FFFFFF", 0.35),
    mid: mix(glass, "#0B1020", 0.55),
    lo: mix(glass, "#0B1020", 0.68),
    dk: mix(glass, "#0B1020", 0.78),
  };
  c.shape(cx, cy, rr(chamberW, chamberH, 11, 2), glassMat, { shade: "flat" });
  // inner glow rim
  const rimCol = pulse === 0 ? mix(glow, "#0B1020", 0.5) : pulse === 1 ? mix(glow, "#0B1020", 0.25) : glow;
  const inner = rr(chamberW - 2, chamberH - 2, 10, 1);
  for (let y = 0; y < inner.h; y++)
    for (let x = 0; x < inner.w; x++) {
      const inside = inner.m[y * inner.w + x] === 1;
      if (!inside) continue;
      const edge = [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ].some(([dx, dy]) => {
        const nx = x + dx,
          ny = y + dy;
        return nx < 0 || ny < 0 || nx >= inner.w || ny >= inner.h || inner.m[ny * inner.w + nx] !== 1;
      });
      if (edge) c.px(cx + 1 + x, cy + 1 + y, rimCol);
    }
  // brain glow + brain
  c.blot(13, 16, ellipse(22, 17), mix(glow, glassMat.mid, pulse === 0 ? 0.85 : pulse === 1 ? 0.75 : 0.65));
  const brain = ascii(BRAIN);
  const bx = 15,
    by = 18;
  const brainCol = CORE.palette.brain;
  c.shape(bx, by, brain, mat(brainCol, 0.7));
  c.map(
    bx + 1,
    by + 2,
    ["..#...#....#...#.", ".#...#...#....#..", "...#...#....#....", ".#...#....#...#..", "...#....#....#..."],
    { "#": mix(brainCol, glass, 0.6) },
  );
  c.vline(bx + 9, by + 1, 7, mix(brainCol, glass, 0.7));
  c.px(bx + 4, by + 2, "#FFFFFF");
  c.px(bx + 5, by + 2, "#FFFFFF");
  // neural nodes + links
  const nodes: [number, number][] = [
    [14, 15],
    [33, 15],
    [14, 37],
    [33, 37],
    [24, 13],
    [24, 36],
  ];
  const lit =
    activity === "lookup"
      ? [f % nodes.length]
      : activity === "evaluating"
        ? [f % 2, 2 + (f % 2), 4]
        : activity === "updating"
          ? nodes.map((_, i) => i)
          : [];
  nodes.forEach(([nx, ny], i) => {
    c.line(nx, ny, bx + 9, by + 5, mix(glow, "#0B1020", 0.45));
    const on = lit.includes(i);
    const col = on ? (activity === "evaluating" ? amber : "#E8FBFF") : glow;
    c.fill(nx - 1, ny - 1, 3, 3, OUTLINE);
    c.px(nx, ny, col);
  });
  // activity effects
  if (activity === "lookup") {
    const sy = cy + 4 + f * 7;
    c.hline(cx + 3, sy, chamberW - 6, "#BFF4FF");
    c.hline(cx + 4, sy + 1, chamberW - 8, mix(glow, "#0B1020", 0.3));
  } else if (activity === "updating") {
    const ys = [40, 34, 28, 22];
    [
      [15, 0],
      [30, 2],
      [21, 1],
      [27, 3],
    ].forEach(([x, o]) => {
      const y = ys[(f + o) % 4];
      c.px(x, y, "#E8FBFF");
      c.px(x, y + 1, glow);
    });
  } else if (activity === "evaluating") {
    c.shape(20, 41, rr(8, 4, 1), mat("#141D31", 0.4), { shade: "flat" });
    c.fill(21, 42, 1 + (f % 4) * 2, 2, amber);
  }
  // glass shine
  c.vline(cx + 4, cy + 7, 10, "#FFFFFF");
  c.vline(cx + 5, cy + 5, 3, mix(glass, "#FFFFFF", 0.6));
  c.px(cx + 4, cy + 19, mix(glass, "#FFFFFF", 0.6));
  // top cap
  c.shape(cx + 8, cy - 3, rr(10, 4, 1), base);
  c.fill(cx + 11, cy - 2, 4, 1, rimCol);

  const out = [...layerToPaths(c.layers.back), ...layerToPaths(c.layers.base)];
  cache.set(key, out);
  return out;
}
