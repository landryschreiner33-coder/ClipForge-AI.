/**
 * Shared skeleton for every robot: rig proportions, poses per animation state, and the
 * common parts (legs, arms, eyes, visor, task card, status markers).
 *
 * Role art (art/*.ts) only describes what makes a role unique: head, torso, equipment.
 * The builder in `drawRobot` decides draw order per view so packs, held items and cards
 * sit correctly in front of or behind the body.
 */
import type { AnimState, RobotRole } from "./registry";
import {
  OUTLINE,
  Painter,
  type Color,
  type Mat,
  type Shape,
  darken,
  ellipse,
  lighten,
  mat,
  mix,
  rr,
  shapeFrom,
} from "./pixel";

export type View = "front" | "back" | "side";

// ------------------------------------------------------------------ kit (role colours)

export interface Kit {
  shell: Mat;
  trim: Mat;
  acc: Mat;
  face: Mat;
  joint: Mat;
  gold: Mat;
  paper: Mat;
  eye: Color;
  eyeHi: Color;
  eyeGlow: Color;
  eyeDim: Color;
  ink: Color;
}

export function makeKit(role: RobotRole): Kit {
  const p = role.palette;
  return {
    shell: mat(p.shell, 0.9),
    trim: mat(p.trim),
    acc: mat(p.accent),
    face: mat(p.face, 0.6),
    joint: mat("#56607A"),
    gold: mat("#F5C542"),
    paper: mat("#EEF2F8", 0.7),
    eye: p.eye,
    eyeHi: lighten(p.eye, 0.7),
    eyeGlow: mix(p.face, p.eye, 0.35),
    eyeDim: mix(p.face, p.eye, 0.3),
    ink: OUTLINE,
  };
}

// ------------------------------------------------------------------ rig

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface RigOpts {
  headW: number;
  headH: number;
  torsoW: number;
  torsoH: number;
  legH: number;
  /** Extra vertical gap/overlap between head and torso (positive raises head). */
  neck: number;
  legGap: number;
}

export interface Rig {
  s: number;
  cx: number;
  footY: number;
  head: Box;
  torso: Box;
  legTop: number;
  legGap: number;
  legH: number;
}

export function makeRig(scale: number, o: Partial<RigOpts> = {}): Rig {
  const base: RigOpts =
    scale >= 1.3
      ? { headW: 28, headH: 21, torsoW: 22, torsoH: 14, legH: 8, neck: 0, legGap: 4 }
      : scale >= 1.1
        ? { headW: 25, headH: 19, torsoW: 18, torsoH: 13, legH: 7, neck: 0, legGap: 4 }
        : { headW: 22, headH: 17, torsoW: 16, torsoH: 11, legH: 6, neck: 0, legGap: 3 };
  const r = { ...base, ...o };
  const cx = 24;
  const footY = 59;
  const legTop = footY - r.legH + 1;
  const ty = legTop - r.torsoH + 1;
  const hy = ty + 2 - r.headH - r.neck;
  return {
    s: scale,
    cx,
    footY,
    legTop,
    legGap: r.legGap,
    legH: r.legH,
    torso: { x: cx - Math.floor(r.torsoW / 2), y: ty, w: r.torsoW, h: r.torsoH },
    head: { x: cx - Math.floor(r.headW / 2), y: hy, w: r.headW, h: r.headH },
  };
}

// ------------------------------------------------------------------ pose

export type ArmPose = "rest" | "item" | "hold" | "cheer" | "offer" | "slump" | "work";
export type EyeMode = "open" | "blink" | "closed" | "dim" | "happy" | "x" | "down" | "off";
export type MarkerKind = "dots" | "check" | "bang" | "retry" | "return" | "pause";

export interface Pose {
  state: AnimState;
  frame: number;
  bob: number;
  /** Walk phase 0..3 or -1 when standing. */
  step: number;
  eyes: EyeMode;
  lookX: number;
  work: number | null;
  arms: ArmPose;
  card: null | "carry" | "review" | "revise";
  marker: null | { kind: MarkerKind; f: number };
  slump: number;
  grey: boolean;
  /** Override eye colour (error = red). */
  eyeColor?: Color;
}

/**
 * Pose for a state/frame. Fallback rule: an unknown state renders as idle; any role that
 * has no special drawing for a state still shows its full body (identity is never dropped),
 * with the shared marker/card/eye changes doing the talking.
 */
export function poseFor(state: AnimState, frame: number): Pose {
  const p: Pose = {
    state,
    frame,
    bob: 0,
    step: -1,
    eyes: "open",
    lookX: 0,
    work: null,
    arms: "item",
    card: null,
    marker: null,
    slump: 0,
    grey: false,
  };
  switch (state) {
    case "idle":
      if (frame === 1) {
        p.eyes = "blink";
        p.bob = 1;
      }
      break;
    case "walk":
      p.step = frame % 4;
      p.bob = frame % 2 === 1 ? 1 : 0;
      break;
    case "work":
      p.work = frame;
      p.arms = "work";
      break;
    case "carry":
      p.step = frame % 4;
      p.bob = frame % 2 === 1 ? 1 : 0;
      p.arms = "hold";
      p.card = "carry";
      break;
    case "review":
      p.arms = "hold";
      p.card = "review";
      p.eyes = "down";
      p.lookX = frame === 0 ? -1 : 1;
      break;
    case "waiting":
      p.marker = { kind: "dots", f: frame };
      p.arms = "rest";
      break;
    case "approved":
      p.arms = "cheer";
      p.eyes = "happy";
      p.marker = { kind: "check", f: frame };
      p.bob = frame === 1 ? -1 : 0;
      break;
    case "revise":
      p.arms = "offer";
      p.card = "revise";
      p.marker = { kind: "return", f: frame };
      break;
    case "error":
      p.arms = "slump";
      p.slump = 2;
      p.bob = 1;
      p.eyes = "x";
      p.eyeColor = "#FF4D5E";
      p.marker = { kind: "bang", f: frame };
      break;
    case "retrying":
      p.marker = { kind: "retry", f: frame };
      p.arms = "rest";
      p.eyes = frame === 3 ? "blink" : "open";
      break;
    case "paused":
      p.eyes = "closed";
      p.arms = "rest";
      p.marker = { kind: "pause", f: 0 };
      break;
    case "unavailable":
      p.eyes = "off";
      p.arms = "rest";
      p.grey = true;
      p.slump = 1;
      break;
  }
  return p;
}

// ------------------------------------------------------------------ drawing context

export interface G {
  c: Painter;
  k: Kit;
  r: Rig;
  p: Pose;
  v: View;
  role: RobotRole;
  /** Near/held hand centre after arms are drawn (front: viewer's right). */
  hand: { x: number; y: number };
  /** Other hand (front: viewer's left). */
  hand2: { x: number; y: number };
  /** Head box after bob/slump offsets have been applied. */
  head: Box;
  torso: Box;
}

/** Round-capped thick line as a mask positioned at its own bounding box. */
export function limbShape(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  th: number,
): { s: Shape; x: number; y: number } {
  const pad = Math.ceil(th / 2) + 1;
  const bx = Math.min(x0, x1) - pad,
    by = Math.min(y0, y1) - pad;
  const w = Math.abs(x1 - x0) + pad * 2 + 1,
    h = Math.abs(y1 - y0) + pad * 2 + 1;
  const ax = x0 - bx,
    ay = y0 - by,
    cx = x1 - bx,
    cy = y1 - by;
  const r2 = (th / 2) * (th / 2);
  const s = shapeFrom(w, h, (x, y) => {
    const dx = cx - ax,
      dy = cy - ay;
    const len = dx * dx + dy * dy;
    let t = len === 0 ? 0 : ((x - ax) * dx + (y - ay) * dy) / len;
    t = Math.max(0, Math.min(1, t));
    const px = ax + t * dx - x,
      py = ay + t * dy - y;
    return px * px + py * py <= r2 + 0.25;
  });
  return { s, x: bx, y: by };
}

export function drawLimb(g: G, x0: number, y0: number, x1: number, y1: number, th: number, m: Mat) {
  const l = limbShape(x0, y0, x1, y1, th);
  g.c.shape(l.x, l.y, l.s, m, { shade: "soft" });
}

// ------------------------------------------------------------------ eyes & visor

export type EyeKind = "pill" | "round" | "square" | "arc" | "narrow" | "wide";

/** Draw one glowing eye of size w x h at x,y honoring the pose's eye mode. */
export function eye(g: G, x: number, y: number, w: number, h: number, kind: EyeKind = "pill") {
  const { c, k, p } = g;
  const col = p.eyeColor ?? k.eye;
  const hi = p.eyeColor ? lighten(p.eyeColor, 0.6) : k.eyeHi;
  const dim = p.eyeColor ? mix("#1A0A10", p.eyeColor, 0.4) : k.eyeDim;
  x += p.lookX;
  if (p.eyes === "down") y += 1;
  const mode = p.eyes;
  const cy = y + Math.floor(h / 2);
  if (mode === "off") {
    c.fill(x, cy, w, 1, darken(k.face.mid, 0.3));
    return;
  }
  if (mode === "blink" || mode === "closed") {
    c.fill(x, cy, w, 1, mode === "closed" ? dim : col);
    return;
  }
  if (mode === "x") {
    const n = Math.min(w, h);
    for (let i = 0; i < n; i++) {
      c.px(x + i, y + i, col);
      c.px(x + n - 1 - i, y + i, col);
    }
    return;
  }
  if (mode === "happy") {
    // ^ arc
    c.fill(x, y + 1, 1, Math.max(1, h - 1), col);
    c.fill(x + w - 1, y + 1, 1, Math.max(1, h - 1), col);
    c.fill(x + 1, y, Math.max(1, w - 2), 1, col);
    return;
  }
  const fillCol = mode === "dim" ? dim : col;
  // glow halo
  if (mode !== "dim") {
    for (let i = -1; i <= w; i++) {
      c.px(x + i, y - 1, k.eyeGlow);
      c.px(x + i, y + h, k.eyeGlow);
    }
    for (let j = 0; j < h; j++) {
      c.px(x - 1, y + j, k.eyeGlow);
      c.px(x + w, y + j, k.eyeGlow);
    }
  }
  if (kind === "round" || kind === "pill") {
    const s = kind === "round" ? ellipse(w, h) : rr(w, h, Math.min(1, Math.floor(w / 2)));
    g.c.blot(x, y, s, fillCol);
  } else if (kind === "arc") {
    c.fill(x, y + 1, 1, h - 1, fillCol);
    c.fill(x + w - 1, y + 1, 1, h - 1, fillCol);
    c.fill(x + 1, y, w - 2, 1, fillCol);
    return;
  } else {
    c.fill(x, y, w, h, fillCol);
  }
  if (mode !== "dim" && w >= 2 && h >= 2) c.px(x, y, hi);
}

/** Dark face panel with a 1px inner rim and a glass reflection. */
export function visor(g: G, x: number, y: number, s: Shape, rim?: Color) {
  const { c, k } = g;
  c.shape(
    x,
    y,
    s,
    { hi: k.face.mid, mid: k.face.mid, lo: k.face.mid, dk: darken(k.face.mid, 0.3) },
    { outline: rim ?? OUTLINE, shade: "soft" },
  );
  // reflection streak
  c.px(x + 2, y + 1, lighten(k.face.mid, 0.25));
  c.px(x + 3, y + 1, lighten(k.face.mid, 0.18));
}

// ------------------------------------------------------------------ legs

export type LegStyle = "legs" | "stubby" | "wheels" | "none";

export function drawLegs(g: G, style: LegStyle, footMat?: Mat) {
  const { c, k, r, p, v } = g;
  if (style === "none") return;
  const foot = footMat ?? k.trim;
  const gap = r.legGap;
  const legW = Math.max(3, Math.round(3 * r.s));
  const footW = Math.max(6, Math.round(6 * r.s));
  const lh = r.legH;
  if (style === "wheels") return; // wheel bases are drawn by the role
  if (v === "side") {
    const off = p.step < 0 ? [0, 0] : p.step === 0 ? [3, -3] : p.step === 2 ? [-3, 3] : [0, 0];
    const lift = p.step === 1 ? [0, 1] : p.step === 3 ? [1, 0] : [0, 0];
    // far leg first (darker)
    for (const i of [1, 0]) {
      const lx = r.cx - 2 + off[i];
      const m = i === 1 ? { ...k.joint, hi: k.joint.lo, mid: k.joint.lo } : k.joint;
      const fm = i === 1 ? { hi: foot.lo, mid: foot.lo, lo: foot.dk, dk: foot.dk } : foot;
      c.shape(lx, r.legTop, rr(legW, lh - 2, 1), m, { shade: "soft" });
      c.shape(lx - 1, r.footY - 2 - lift[i], rr(footW, 3, 1), fm);
    }
    return;
  }
  const lift = p.step === 0 ? [1, 0] : p.step === 2 ? [0, 1] : [0, 0];
  const xs = [r.cx - gap - legW + 1, r.cx + gap - 1];
  xs.forEach((lx, i) => {
    const hgt = lh - 2 - lift[i];
    c.shape(lx, r.legTop, rr(legW, Math.max(2, hgt), 1), k.joint, { shade: "soft" });
    const fx = i === 0 ? lx - (footW - legW) + 1 : lx - 1;
    c.shape(fx, r.footY - 2 - lift[i], rr(footW, 3, 1, 0), foot);
    if (style === "stubby") c.hline(fx + 1, r.footY - 2 - lift[i], footW - 2, foot.hi);
  });
}

// ------------------------------------------------------------------ arms

export interface ArmOpts {
  mat?: Mat;
  handMat?: Mat;
  thick?: number;
  /** Override the right/near hand target (e.g. custom work motions). */
  rightTo?: { x: number; y: number };
  leftTo?: { x: number; y: number };
  shoulderMat?: Mat;
}

/** Hand targets for the current pose. Returns [left(viewer), right(viewer)]. */
export function handTargets(g: G): [{ x: number; y: number }, { x: number; y: number }] {
  const { p, torso: t } = g;
  const L = t.x - 2,
    R = t.x + t.w + 1;
  const low = t.y + t.h - 3;
  switch (p.arms) {
    case "hold":
      return [
        { x: g.r.cx - 6, y: t.y + 5 },
        { x: g.r.cx + 6, y: t.y + 5 },
      ];
    case "cheer":
      return [
        { x: L - 2, y: t.y - 6 },
        { x: R + 2, y: t.y + 5 },
      ];
    case "offer":
      return [
        { x: L - 1, y: low },
        { x: R + 4, y: t.y + 3 },
      ];
    case "slump":
      return [
        { x: L, y: low + 2 },
        { x: R, y: low + 2 },
      ];
    case "rest":
      return [
        { x: L - 1, y: low },
        { x: R + 1, y: low },
      ];
    case "work":
    case "item":
    default:
      return [
        { x: L - 1, y: low },
        { x: R + 2, y: t.y + 5 },
      ];
  }
}

/** Front/back arms. Shoulders at torso top corners. */
export function drawArms(g: G, o: ArmOpts = {}) {
  const { c, k, torso: t, v } = g;
  const m = o.mat ?? k.shell;
  const hm = o.handMat ?? k.shell;
  const th = o.thick ?? Math.max(3, Math.round(3 * g.r.s));
  let [hl, hr] = handTargets(g);
  if (o.rightTo) hr = o.rightTo;
  if (o.leftTo) hl = o.leftTo;
  if (v === "back")
    [hl, hr] = [
      { x: 48 - 1 - hr.x, y: hr.y },
      { x: 48 - 1 - hl.x, y: hl.y },
    ];
  const sy = t.y + 3;
  const sl = { x: t.x, y: sy },
    sr = { x: t.x + t.w - 1, y: sy };
  drawLimb(g, sl.x, sl.y, hl.x, hl.y, th, m);
  drawLimb(g, sr.x, sr.y, hr.x, hr.y, th, m);
  const hs = Math.max(4, Math.round(4 * g.r.s));
  for (const h of [hl, hr])
    c.shape(h.x - Math.floor(hs / 2), h.y - Math.floor(hs / 2), ellipse(hs, hs), hm, { shade: "soft" });
  const sm = o.shoulderMat ?? k.joint;
  for (const s of [sl, sr]) c.shape(s.x - 2, s.y - 2, ellipse(4, 4), sm, { shade: "soft" });
  if (v === "back") {
    g.hand = hl;
    g.hand2 = hr;
  } else {
    g.hand = hr;
    g.hand2 = hl;
  }
}

/** Side-view arm (near arm only; far arm is mostly hidden). */
export function drawSideArm(g: G, far: boolean, o: ArmOpts = {}) {
  const { c, k, torso: t, p } = g;
  const m = far ? { ...(o.mat ?? k.shell), hi: (o.mat ?? k.shell).lo, mid: (o.mat ?? k.shell).lo } : (o.mat ?? k.shell);
  const th = o.thick ?? Math.max(3, Math.round(3 * g.r.s));
  const sx = t.x + Math.floor(t.w / 2) - (far ? 2 : 0),
    sy = t.y + 3;
  let to: { x: number; y: number };
  const swing = p.step < 0 ? 0 : p.step === 0 ? 2 : p.step === 2 ? -2 : 0;
  switch (p.arms) {
    case "hold":
      to = { x: t.x + t.w + 3, y: t.y + 5 };
      break;
    case "cheer":
      to = { x: sx + 3, y: t.y - 6 };
      break;
    case "offer":
      to = { x: t.x + t.w + 5, y: t.y + 3 };
      break;
    case "slump":
      to = { x: sx + 1, y: t.y + t.h };
      break;
    case "rest":
      to = { x: sx + (far ? -swing : swing), y: t.y + t.h - 2 };
      break;
    default:
      to = far ? { x: sx - swing, y: t.y + t.h - 2 } : { x: t.x + t.w + 2, y: t.y + 6 };
  }
  if (!far && o.rightTo) to = o.rightTo;
  drawLimb(g, sx, sy, to.x, to.y, th, m);
  const hs = Math.max(4, Math.round(4 * g.r.s));
  c.shape(
    to.x - Math.floor(hs / 2),
    to.y - Math.floor(hs / 2),
    ellipse(hs, hs),
    far ? { ...k.shell, mid: k.shell.lo, hi: k.shell.lo } : (o.handMat ?? k.shell),
    { shade: "soft" },
  );
  if (!far) {
    c.shape(sx - 2, sy - 1, ellipse(4, 4), o.mat ?? k.shell, { shade: "soft" });
    c.px(sx - 1, sy, k.joint.mid);
    g.hand = to;
  } else g.hand2 = to;
}

// ------------------------------------------------------------------ rank insignia

/** Small crown badge (5x4 inside a 7x6 plate). */
export function crownBadge(g: G, x: number, y: number, plate?: Mat) {
  const { c, k } = g;
  c.shape(x, y, rr(7, 6, 1), plate ?? { ...k.face, mid: darken(k.face.mid, 0.1) }, { shade: "flat" });
  c.map(x + 1, y + 1, ["#.#.#", "#####", ".###."], { "#": k.gold.mid });
  c.px(x + 2, y + 2, k.gold.hi);
}

/** Shoulder tabs (epaulettes) in role trim, drawn on top of shoulders. */
export function shoulderTabs(g: G, m?: Mat) {
  const { c, k, torso: t, v } = g;
  const tm = m ?? k.trim;
  if (v === "side") {
    c.shape(t.x + Math.floor(t.w / 2) - 3, t.y - 1, rr(6, 3, 1), tm);
    return;
  }
  c.shape(t.x - 3, t.y, rr(6, 3, 1), tm);
  c.shape(t.x + t.w - 3, t.y, rr(6, 3, 1), tm);
}

// ------------------------------------------------------------------ task card overlay

/** Card tokens resolved by the renderer against the caller's tint. */
export const CARD = { fill: "@c", hi: "@h", lo: "@l", ink: "@i", line: "@o" } as const;

export function drawCard(g: G) {
  const { c, p, v, torso: t } = g;
  if (!p.card) return;
  const revise = p.card === "revise";
  const fill = revise ? "#FFAB45" : CARD.fill,
    hi = revise ? "#FFD08F" : CARD.hi,
    lo = revise ? "#C9771F" : CARD.lo,
    ink = revise ? "#5A2E05" : CARD.ink;
  const cm: Mat = { hi, mid: fill, lo, dk: lo };
  if (revise) {
    // held out to the side in the right hand
    c.to("card");
    const hx = g.hand.x,
      hy = g.hand.y;
    const x = v === "side" ? hx - 1 : hx - 1,
      y = hy - 9;
    c.shape(x, y, rr(8, 10, 1), cm);
    c.hline(x + 2, y + 3, 4, ink);
    c.hline(x + 2, y + 5, 3, ink);
    c.to("over");
    c.shape(hx - 2, hy - 2, ellipse(4, 4), g.k.shell, { shade: "soft" });
    c.to("base");
    return;
  }
  if (v === "back") {
    c.to("back");
    const w = t.w + 4;
    c.shape(g.r.cx - Math.floor(w / 2), t.y + 1, rr(w, 8, 1), cm);
    c.to("base");
    return;
  }
  c.to("card");
  if (v === "side") {
    const x = t.x + t.w + 1,
      y = t.y - 1;
    if (p.card === "review") {
      c.shape(x, y - 2, rr(5, 12, 1), cm);
      c.vline(x + 2, y, 8, ink);
    } else {
      c.shape(x, y, rr(4, 11, 1), cm);
      c.vline(x + 1, y + 2, 6, hi);
    }
  } else if (p.card === "review") {
    const w = Math.max(18, t.w + 2),
      h = 11;
    const x = g.r.cx - Math.floor(w / 2),
      y = t.y + 1;
    c.shape(x, y, rr(w, h, 1), cm);
    c.vline(g.r.cx, y + 1, h - 2, lo);
    for (let i = 0; i < 3; i++) {
      c.hline(x + 2, y + 2 + i * 3, Math.floor(w / 2) - 4 - (i === 2 ? 2 : 0), ink);
      c.hline(g.r.cx + 2, y + 2 + i * 3, Math.floor(w / 2) - 4 - (i === 1 ? 3 : 0), ink);
    }
  } else {
    const w = 12,
      h = 10;
    const x = g.r.cx - Math.floor(w / 2),
      y = t.y;
    c.shape(x, y, rr(w, h, 1), cm);
    c.hline(x + 2, y + 2, 8, ink);
    c.hline(x + 2, y + 4, 6, ink);
    c.hline(x + 2, y + 6, 7, ink);
    c.px(x + 1, y + 1, hi);
  }
  // hands over the card
  c.to("over");
  const hs = Math.max(4, Math.round(4 * g.r.s));
  if (v === "side") {
    const hx = t.x + t.w + 1,
      hy = t.y + 5;
    c.shape(hx - 1, hy, ellipse(hs, hs), g.k.shell, { shade: "soft" });
  } else {
    for (const h of [g.hand, g.hand2])
      c.shape(h.x - Math.floor(hs / 2), h.y, ellipse(hs, hs), g.k.shell, { shade: "soft" });
  }
  c.to("base");
}

// ------------------------------------------------------------------ status markers

export function drawMarker(g: G) {
  const { c, p, head } = g;
  if (!p.marker) return;
  const { kind, f } = p.marker;
  c.to("over");
  const saveY = c.oy;
  c.oy = 0;
  const x = Math.min(47 - 11, head.x + head.w - 3);
  const y = Math.max(1, head.y - 10);
  const W = "#FFFFFF";
  if (kind === "dots") {
    c.shape(x, y, rr(11, 7, 2), mat("#F3F4F7", 0.4));
    c.px(x + 2, y + 7, "#F3F4F7");
    c.px(x + 1, y + 8, OUTLINE);
    c.px(x + 2, y + 8, OUTLINE);
    c.px(x + 3, y + 7, OUTLINE);
    for (let i = 0; i <= f && i < 3; i++) c.fill(x + 2 + i * 3, y + 3, 2, 2, "#141D31");
  } else if (kind === "check") {
    c.shape(x + 1, y, ellipse(10, 10), mat("#2FCB6B"));
    c.map(x + 3, y + 3, [".....#", "....##", "#..##.", "####..", ".##..."], { "#": W });
    if (f === 1) {
      c.px(x - 1, y + 1, "#B6FFC8");
      c.px(x + 12, y + 2, "#B6FFC8");
      c.px(x + 12, y + 9, "#B6FFC8");
    }
  } else if (kind === "bang") {
    const red = f === 0 ? "#FF4D5E" : "#FF7A86";
    c.shape(x + 2, y, rr(7, 10, 2), mat(red));
    c.fill(x + 5, y + 2, 2, 4, W);
    c.fill(x + 5, y + 7, 2, 1, W);
  } else if (kind === "retry") {
    const ring = [
      [3, 0],
      [4, 0],
      [5, 0],
      [6, 0],
      [7, 1],
      [8, 2],
      [9, 3],
      [9, 4],
      [9, 5],
      [9, 6],
      [8, 7],
      [7, 8],
      [6, 9],
      [5, 9],
      [4, 9],
      [3, 9],
      [2, 8],
      [1, 7],
      [0, 6],
      [0, 5],
      [0, 4],
      [0, 3],
      [1, 2],
      [2, 1],
    ];
    const n = ring.length;
    const gapAt = (f * 6) % n;
    c.shape(x, y, ellipse(10, 10), flat("#141D31"), { shade: "flat" });
    ring.forEach(([dx, dy], i) => {
      const rel = (i - gapAt + n) % n;
      if (rel < 4) return;
      c.px(x + dx, y + dy, rel > n - 3 ? "#BFF4FF" : "#28D9FF");
    });
    const [ax, ay] = ring[(gapAt + n - 1) % n];
    c.px(x + ax, y + ay, W);
  } else if (kind === "return") {
    c.shape(x, y, rr(11, 8, 2), mat("#FFAB45"));
    c.map(x + 2, y + 1, ["..#....", ".##....", "#######", ".##...#", "..#...#", "......#"], { "#": "#3A1E02" });
    void f;
  } else if (kind === "pause") {
    c.shape(x + 2, y + 1, rr(8, 8, 2), mat("#8892A8", 0.5));
    c.fill(x + 4, y + 3, 1, 4, "#141D31");
    c.fill(x + 7, y + 3, 1, 4, "#141D31");
  }
  c.oy = saveY;
  c.to("base");
}

function flat(cc: Color): Mat {
  return { hi: cc, mid: cc, lo: cc, dk: cc };
}

// ------------------------------------------------------------------ the builder

export interface RobotDef {
  rig?: Partial<RigOpts>;
  legs?: LegStyle;
  footMat?: (k: Kit) => Mat;
  arms?: ArmOpts | ((g: G) => ArmOpts);
  /** Wheels / custom base drawn instead of legs. */
  base?: (g: G) => void;
  /** Backpack or rear equipment. Front: drawn behind body. Back: drawn over body. Side: behind. */
  pack?: (g: G) => void;
  torso: (g: G) => void;
  head: (g: G) => void;
  /** Held equipment (near hand). Hidden behind the body in back view unless `itemBack` is set. */
  item?: (g: G) => void;
  itemBack?: (g: G) => void;
  /** Drawn right after the arms (shoulder tabs, pads) so they sit over the shoulder joints. */
  shoulders?: (g: G) => void;
  /** Drawn last over everything. */
  after?: (g: G) => void;
  /** Hide the held item while carrying/reviewing (default true). */
  stowItemWhenBusy?: boolean;
}

export function busy(p: Pose) {
  return p.card === "carry" || p.card === "review";
}

export function drawRobot(c: Painter, def: RobotDef, role: RobotRole, kit: Kit, view: View, pose: Pose) {
  const r = makeRig(role.scale, def.rig);
  const g: G = {
    c,
    k: kit,
    r,
    p: pose,
    v: view,
    role,
    hand: { x: 0, y: 0 },
    hand2: { x: 0, y: 0 },
    head: { ...r.head, y: r.head.y + pose.bob + pose.slump },
    torso: { ...r.torso, y: r.torso.y + pose.bob },
  };
  if (view === "side") {
    // profiles are narrower than the front view
    g.head.w = Math.round(r.head.w * 0.84);
    g.head.x = r.cx - Math.floor(g.head.w / 2) + 1;
    g.torso.w = Math.round(r.torso.w * 0.72);
    g.torso.x = r.cx - Math.floor(g.torso.w / 2);
  }
  // shadow
  c.to("back");
  const sw = Math.round(22 * r.s) + 2;
  c.blot(r.cx - Math.floor(sw / 2), r.footY - 1, ellipse(sw, 4), "#00000055");
  c.to("base");

  const legStyle = def.legs ?? "legs";
  const armOpts = typeof def.arms === "function" ? def.arms(g) : (def.arms ?? {});
  const stow =
    ((def.stowItemWhenBusy ?? true) && (busy(pose) || pose.card === "revise")) ||
    (view === "side" && pose.arms === "cheer");
  if (view === "front") {
    def.pack?.(g);
    if (def.base) def.base(g);
    else drawLegs(g, legStyle, def.footMat?.(kit));
    def.torso(g);
    drawArms(g, armOpts);
    def.shoulders?.(g);
    def.head(g);
    if (!stow) def.item?.(g);
    def.after?.(g);
  } else if (view === "back") {
    if (!stow) def.itemBack?.(g);
    if (def.base) def.base(g);
    else drawLegs(g, legStyle, def.footMat?.(kit));
    drawArms(g, armOpts);
    def.torso(g);
    def.shoulders?.(g);
    def.head(g);
    def.pack?.(g);
    def.after?.(g);
  } else {
    drawSideArm(g, true, armOpts);
    def.pack?.(g);
    if (def.base) def.base(g);
    else drawLegs(g, legStyle, def.footMat?.(kit));
    def.torso(g);
    def.head(g);
    drawSideArm(g, false, armOpts);
    def.shoulders?.(g);
    if (!stow) def.item?.(g);
    def.after?.(g);
  }
  drawCard(g);
  drawMarker(g);
}
