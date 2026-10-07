/** Reusable head/torso/equipment builders shared by the role art modules. */
import { OUTLINE, type Color, type Mat, type Shape, darken, ellipse, lighten, mat, rr } from "../pixel";
import { type Box, type G, eye, visor } from "../rig";

export type ShapeFn = (w: number, h: number) => Shape;

export interface VisorSpec {
  /** Offset and size relative to the head box (front view). */
  dx: number;
  dy: number;
  w: number;
  h: number;
  shape?: ShapeFn;
  rim?: Color;
}

export interface HeadSpec {
  shape: ShapeFn;
  /** Shape used for the profile; defaults to `shape`. */
  sideShape?: ShapeFn;
  mat?: Mat;
  visor?: VisorSpec;
  /** Eyes inside the front visor box. Default: two pill eyes. */
  eyes?: (g: G, v: Box) => void;
  /** Eye(s) inside the side visor box. Default: one pill eye near the front. */
  sideEyes?: (g: G, v: Box) => void;
  ears?: { w: number; h: number; dy?: number; mat?: Mat; shape?: ShapeFn; inset?: number; front?: boolean };
  /** Back-of-head panel (default true). */
  backPanel?: boolean;
  glint?: boolean;
}

/** Default two-eye layout inside a visor. */
export function twoEyes(ew: number, eh: number, kind: Parameters<typeof eye>[5] = "pill", spread = 0.27) {
  return (g: G, v: Box) => {
    const y = v.y + Math.floor((v.h - eh) / 2);
    const lx = v.x + Math.round(v.w * spread) - Math.floor(ew / 2);
    const rx = v.x + v.w - 1 - Math.round(v.w * spread) - Math.ceil(ew / 2) + 1;
    eye(g, lx, y, ew, eh, kind);
    eye(g, rx, y, ew, eh, kind);
  };
}
export function oneEye(ew: number, eh: number, kind: Parameters<typeof eye>[5] = "pill") {
  return (g: G, v: Box) => eye(g, v.x + v.w - ew - 2, v.y + Math.floor((v.h - eh) / 2), ew, eh, kind);
}

/**
 * For visors that show icons instead of eyes (charts, play buttons...). Handles the shared
 * eye modes (blink/closed/off/x/happy) uniformly and returns the icon colour, or null when the
 * mode was already drawn and the caller should skip its icons.
 */
export function displayMode(g: G, v: Box): Color | null {
  const { p, k, c } = g;
  const col = p.eyeColor ?? k.eye;
  const y = v.y + Math.floor(v.h / 2);
  switch (p.eyes) {
    case "off":
      c.hline(v.x + 2, y, v.w - 4, darken(k.face.mid, 0.3));
      return null;
    case "blink":
      c.hline(v.x + 2, y, v.w - 4, col);
      return null;
    case "closed":
      c.hline(v.x + 2, y, v.w - 4, k.eyeDim);
      return null;
    case "x":
      twoEyes(3, 3)(g, v);
      return null;
    case "happy":
      twoEyes(4, 3)(g, v);
      return null;
    default:
      return col;
  }
}

/** Draws ears, head shell, visor and eyes for the current view. Returns the head box. */
export function head(g: G, s: HeadSpec): Box {
  const { c, k, v } = g;
  const b = g.head;
  const m = s.mat ?? k.shell;
  const ears = s.ears;
  const earMat = ears?.mat ?? k.trim;
  const earShape = ears?.shape ?? ((w: number, h: number) => rr(w, h, Math.min(2, Math.floor(w / 2))));
  const ey = b.y + (ears?.dy ?? Math.floor((b.h - (ears?.h ?? 0)) / 2));
  const inset = ears?.inset ?? 2;
  if (ears && v !== "side" && !ears.front) {
    c.shape(b.x - ears.w + inset, ey, earShape(ears.w, ears.h), earMat);
    c.shape(b.x + b.w - inset, ey, earShape(ears.w, ears.h), earMat);
  }
  const shape = v === "side" ? (s.sideShape ?? s.shape)(b.w, b.h) : s.shape(b.w, b.h);
  c.shape(b.x, b.y, shape, m, { glint: s.glint ?? true });
  if (ears && v !== "side" && ears.front) {
    c.shape(b.x - ears.w + inset, ey, earShape(ears.w, ears.h), earMat);
    c.shape(b.x + b.w - inset, ey, earShape(ears.w, ears.h), earMat);
  }
  if (v === "front" && s.visor) {
    const vs = s.visor;
    const vb = { x: b.x + vs.dx, y: b.y + vs.dy, w: vs.w, h: vs.h };
    visor(g, vb.x, vb.y, (vs.shape ?? ((w, h) => rr(w, h, 2)))(vb.w, vb.h), vs.rim);
    (s.eyes ?? twoEyes(3, 4))(g, vb);
  } else if (v === "side") {
    if (s.visor) {
      const vs = s.visor;
      const w = Math.max(5, Math.round(vs.w * 0.4));
      const vb = { x: b.x + b.w - w - 1, y: b.y + vs.dy, w, h: vs.h };
      visor(g, vb.x, vb.y, rr(vb.w, vb.h, 1), vs.rim);
      (s.sideEyes ?? oneEye(3, Math.min(4, vs.h - 2)))(g, vb);
    }
    if (ears) {
      // profile ear: a ring with a bolt so it never reads as a second eye
      const ew = Math.max(ears.w, 5),
        eh = Math.max(ears.h, 5);
      const ex = b.x + Math.floor(b.w * 0.26) - Math.floor(ew / 2);
      c.shape(ex, ey, earShape(ew, eh), earMat);
      c.fill(ex + 1, ey + 1, ew - 2, eh - 2, earMat.lo);
      c.fill(ex + Math.floor(ew / 2) - 1, ey + Math.floor(eh / 2) - 1, 2, 2, k.shell.mid);
    }
  } else if (v === "back" && (s.backPanel ?? true)) {
    const pw = Math.max(6, b.w - 10),
      ph = Math.max(4, b.h - 9);
    const px = b.x + Math.floor((b.w - pw) / 2),
      py = b.y + Math.floor((b.h - ph) / 2) + 1;
    c.shape(px, py, rr(pw, ph, 2), { hi: m.lo, mid: m.mid, lo: m.lo, dk: m.lo }, { outline: m.dk, shade: "soft" });
    for (let i = 0; i < 3; i++) c.hline(px + 2, py + 2 + i * 2, pw - 6, m.lo);
    c.fill(px + pw - 3, py + 2, 1, Math.min(5, ph - 3), k.trim.mid);
  }
  return b;
}

export interface TorsoSpec {
  shape?: ShapeFn;
  mat?: Mat;
  front?: (g: G, b: Box) => void;
  back?: (g: G, b: Box) => void;
  side?: (g: G, b: Box) => void;
}

export function torso(g: G, s: TorsoSpec = {}): Box {
  const b = g.torso;
  const m = s.mat ?? g.k.shell;
  g.c.shape(b.x, b.y, (s.shape ?? ((w, h) => rr(w, h, 3, 2)))(b.w, b.h), m);
  if (g.v === "front") s.front?.(g, b);
  else if (g.v === "back") {
    if (s.back) s.back(g, b);
    else {
      g.c.hline(b.x + 3, b.y + 4, b.w - 6, m.lo);
      g.c.hline(b.x + 3, b.y + 6, b.w - 6, m.lo);
    }
  } else s.side?.(g, b);
  return b;
}

/** Simple belly panel (dark inset with a glowing pip). */
export function bellyPanel(g: G, b: Box, w: number, h: number, color: Color, dy = 3) {
  const x = b.x + Math.floor((b.w - w) / 2),
    y = b.y + dy;
  g.c.shape(x, y, rr(w, h, 1), mat(darken(g.k.face.mid, 0.05), 0.4), { shade: "flat" });
  return { x, y, w, h, color };
}

/** Straight antenna with a custom tip. */
export function antenna(g: G, x: number, yTop: number, yBottom: number, tip: (x: number, y: number) => void, m?: Mat) {
  const mm = m ?? g.k.joint;
  g.c.fill(x - 1, yTop, 3, yBottom - yTop + 1, OUTLINE);
  g.c.fill(x, yTop + 1, 1, yBottom - yTop, mm.hi);
  tip(x, yTop);
}

export function ball(g: G, x: number, y: number, size: number, m: Mat) {
  g.c.shape(x - Math.floor(size / 2), y - Math.floor(size / 2), ellipse(size, size), m, { glint: false });
  g.c.px(x - Math.floor(size / 2) + 1, y - Math.floor(size / 2) + 1, lighten(m.hi, 0.6));
}

/** Tablet/slate with an outlined frame and a screen; `icon` draws inside the screen. */
export function tablet(
  g: G,
  x: number,
  y: number,
  w: number,
  h: number,
  frame: Mat,
  screen: Color,
  icon?: (x: number, y: number, w: number, h: number) => void,
) {
  g.c.shape(x, y, rr(w, h, 1), frame);
  g.c.fill(x + 1, y + 1, w - 2, h - 2, screen);
  g.c.hline(x + 1, y + 1, w - 2, lighten(screen, 0.15));
  icon?.(x + 1, y + 1, w - 2, h - 2);
}

/** Film reel disc with rotating holes. */
export function reel(g: G, x: number, y: number, size: number, m: Mat, frame = 0) {
  const { c } = g;
  c.shape(x, y, ellipse(size, size), m);
  const cx = x + Math.floor(size / 2),
    cy = y + Math.floor(size / 2);
  const rad = Math.max(2, Math.floor(size / 2) - 2);
  const n = 4;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + (frame % 4) * (Math.PI / 8);
    const hx = Math.round(cx + Math.cos(a) * (rad - 1)),
      hy = Math.round(cy + Math.sin(a) * (rad - 1));
    c.fill(hx - (size > 9 ? 1 : 0), hy - (size > 9 ? 1 : 0), size > 9 ? 2 : 1, size > 9 ? 2 : 1, darken(m.dk, 0.35));
  }
  c.px(cx, cy, OUTLINE);
}

/** Small held item anchored so the hand overlaps its lower-left corner. */
export function atHand(g: G, _w: number, h: number, ax = 2, ay = 2) {
  return { x: g.hand.x - ax, y: g.hand.y - h + ay };
}

/** Draws the near hand again on top of a held item. */
export function gripHand(g: G, m?: Mat) {
  const hs = Math.max(4, Math.round(4 * g.r.s));
  g.c.shape(g.hand.x - Math.floor(hs / 2), g.hand.y - Math.floor(hs / 2), ellipse(hs, hs), m ?? g.k.shell, {
    shade: "soft",
  });
}
