/**
 * The black hole in the studio's sky, painted from code so it stays sharp at any size and on any screen (the owner
 * asked for a better one on 2026-11-19, and on 2026-11-20 for it to move). A black shadow with a thin photon ring;
 * the far side of the hot disk bent up over the top by gravity into a wide arch, with a faint thin image underneath;
 * and the near side of the disk crossing in front.
 *
 * Where the browser has WebGL (blackHoleGl.ts), every streak is drawn again each frame on the graphics chip and the
 * disk turns, the inner streaks faster, as in a real disk; this file gives it the streaks (streakMesh) and the still
 * parts (paintUnder, paintShadow). Without WebGL the canvas below paints the same picture once per size and a few
 * brighter patches of light travel round the disk. It is scenery and says nothing about work.
 */

type Seg = { start: number; len: number; gain: number };
type Streak = { a: number; width: number; rgb: string; alpha: number; segs: Seg[] };
type Pulse = { a: number; phase: number; len: number; speed: number; gain: number };

/** How flat the disk looks from here, and how far it is turned (it rises to the right). */
export const FLAT = 0.22, TILT = -0.075;
export const INNER = 1.16, OUTER = 3.9;
/** The innermost material goes round in about 2π / SPIN seconds; further out it is slower (Kepler). */
export const SPIN = 0.32;

let streaks: Streak[] | null = null;
let pulses: Pulse[] | null = null;

function rnd(seed: { v: number }) {
  seed.v = (seed.v * 16807) % 2147483647;
  return seed.v / 2147483647;
}

function diskRgb(a: number, warm: number): [number, number, number] {
  // white hot at the inner edge, then gold, orange and a dull red outside; `warm` shifts a streak a little
  const stops: [number, [number, number, number]][] = [
    [1.1, [255, 238, 206]], [1.45, [255, 208, 142]], [2.0, [250, 166, 86]], [2.8, [226, 120, 58]], [4.5, [140, 62, 42]],
  ];
  const x = Math.min(4.5, Math.max(1.1, a + warm));
  for (let i = 1; i < stops.length; i++) {
    const [a1, c1] = stops[i];
    if (x <= a1) {
      const [a0, c0] = stops[i - 1], t = (x - a0) / (a1 - a0);
      return [0, 1, 2].map(k => Math.round(c0[k] + (c1[k] - c0[k]) * t)) as [number, number, number];
    }
  }
  return stops[stops.length - 1][1];
}

/** Brightness across the disk: a sharp rise at the inner edge and a long fade outwards. */
const level = (a: number) => Math.min(1, (a - INNER + 0.04) / 0.14) * Math.min(1, Math.exp(-(a - 1.35) / 0.95));

function makeArt() {
  const seed = { v: 19771119 };
  const list: Streak[] = [];
  const N = 360;
  for (let i = 0; i < N; i++) {
    const u = (i + rnd(seed)) / N;
    const a = INNER + (OUTER - INNER) * Math.pow(u, 1.3);
    const segs: Seg[] = [];
    const n = 2 + Math.floor(rnd(seed) * 3);
    for (let k = 0; k < n; k++) segs.push({ start: rnd(seed) * Math.PI * 2, len: 1.2 + rnd(seed) * 3.6, gain: 0.35 + rnd(seed) });
    const [r, g, b] = diskRgb(a, (rnd(seed) - 0.5) * 0.5);
    list.push({ a, width: 0.45 + rnd(seed) * 1.25, rgb: `${r}, ${g}, ${b}`, alpha: (0.07 + rnd(seed) * 0.24) * level(a), segs });
  }
  const moving: Pulse[] = [];
  for (let i = 0; i < 9; i++) {
    const a = INNER + 0.05 + rnd(seed) * 1.5;
    moving.push({ a, phase: rnd(seed) * Math.PI * 2, len: 0.35 + rnd(seed) * 0.5, speed: 0.34 * Math.pow(INNER / a, 1.5),
      gain: 0.5 + rnd(seed) * 0.5 });
  }
  streaks = list;
  pulses = moving;
}

export type HoleGeometry = { cx: number; cy: number; R: number; scale: number };

/** Where the hole sits in a canvas of this size. The art is 2.7 times as wide as it is tall. */
export function holeGeometry(w: number, h: number): HoleGeometry {
  const R = Math.min(h * 0.29, w * 0.107);
  return { cx: w / 2, cy: h * 0.5, R, scale: R / 64 };
}

/** The lensed image of a disk ring over the top of the shadow: an arch that widens for outer rings. */
function arch(a: number) {
  const ry = 1.045 + 0.25 * (a - INNER);
  return { rx: ry * (1 + 0.17 * (a - INNER)), ry };
}

const beamAt = (angle: number, amount: number) => 1 + amount * -Math.cos(angle);

/** Disk streaks between angles lo and hi (0..π is the near side, π..2π the far side). */
function diskStreaks(g: CanvasRenderingContext2D, geo: HoleGeometry, lo: number, hi: number, soft: boolean) {
  const { cx, cy, R } = geo;
  for (const s of streaks!) {
    g.lineWidth = Math.max(0.5, s.width * geo.scale * (soft ? 5 : 1));
    for (const seg of s.segs) {
      for (const shift of [0, Math.PI * 2]) {
        const a0 = Math.max(seg.start - shift, lo), a1 = Math.min(seg.start + seg.len - shift, hi);
        if (a1 <= a0) continue;
        const al = s.alpha * seg.gain * beamAt((a0 + a1) / 2, 0.35) * (soft ? 0.05 : 1);
        g.strokeStyle = `rgba(${s.rgb}, ${Math.min(1, al)})`;
        g.beginPath();
        g.ellipse(cx, cy, s.a * R, s.a * R * FLAT, TILT, a0, a1);
        g.stroke();
      }
    }
  }
}

/** The arch over the top, made of the same streaks bent round the shadow. */
function archStreaks(g: CanvasRenderingContext2D, geo: HoleGeometry, soft: boolean) {
  const { cx, cy, R } = geo;
  for (const s of streaks!) {
    if (s.a > 3.3) continue;
    const { rx, ry } = arch(s.a);
    g.lineWidth = Math.max(0.5, s.width * geo.scale * (soft ? 6 : 1.15));
    const fade = Math.max(0, 1 - (s.a - INNER) / 2.6);
    for (const seg of s.segs) {
      const from = Math.PI + (seg.start % Math.PI), to = Math.min(Math.PI * 2, from + seg.len * 0.75);
      // drawn in short pieces so the arch fades out where its ends meet the disk beside the shadow
      for (let p0 = from; p0 < to; p0 += 0.16) {
        const p1 = Math.min(to, p0 + 0.17), mid = (p0 + p1) / 2;
        const ends = Math.min(1, Math.sin(mid - Math.PI) / 0.5);
        const al = s.alpha * seg.gain * (0.55 + 0.75 * fade) * beamAt(mid, 0.3) * ends * (soft ? 0.05 : 1);
        if (al < 0.004) continue;
        g.strokeStyle = `rgba(${s.rgb}, ${Math.min(1, al)})`;
        g.beginPath();
        g.ellipse(cx, cy, rx * R, ry * R, TILT, p0, p1);
        g.stroke();
      }
    }
  }
}

function begin(gs: CanvasRenderingContext2D[], w: number, h: number) {
  for (const g of gs) {
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = "source-over";
    g.clearRect(0, 0, w, h);
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
  }
}

/** A wide, warm glow along the plane of the disk and round the arch. */
function glow(u: CanvasRenderingContext2D, { cx, cy, R }: HoleGeometry) {
  u.save();
  u.translate(cx, cy); u.rotate(TILT); u.scale(1, 0.42);
  const gr = u.createRadialGradient(0, 0, R, 0, 0, R * 4.6);
  gr.addColorStop(0, "rgba(255, 186, 120, 0.2)");
  gr.addColorStop(0.3, "rgba(255, 150, 86, 0.10)");
  gr.addColorStop(1, "rgba(150, 70, 60, 0)");
  u.fillStyle = gr;
  u.fillRect(-R * 4.8, -R * 4.8, R * 9.6, R * 9.6);
  u.restore();
}

/** The thin image under the shadow. */
function thinImage(u: CanvasRenderingContext2D, geo: HoleGeometry) {
  const { cx, cy, R } = geo;
  for (let i = 0; i < 26; i++) {
    const r = 1.012 + i * 0.006, al = 0.34 * Math.exp(-i / 6);
    u.lineWidth = Math.max(0.5, 0.9 * geo.scale);
    u.strokeStyle = `rgba(255, ${226 - i * 3}, ${180 - i * 4}, ${al})`;
    u.beginPath();
    u.ellipse(cx, cy, r * R, r * R, TILT, 0.08, Math.PI - 0.08);
    u.stroke();
  }
}

/** The shadow, then the photon ring round it. */
function shadow(u: CanvasRenderingContext2D, geo: HoleGeometry) {
  const { cx, cy, R } = geo;
  u.globalCompositeOperation = "source-over";
  u.fillStyle = "#000";
  u.beginPath();
  u.arc(cx, cy, R, 0, Math.PI * 2);
  u.fill();
  u.globalCompositeOperation = "lighter";
  for (const [wd, al] of [[5, 0.07], [2.4, 0.16], [1.1, 0.5], [0.55, 0.9]] as const) {
    u.lineWidth = Math.max(0.6, wd * geo.scale * 1.5);
    u.strokeStyle = `rgba(255, 238, 212, ${al})`;
    u.beginPath();
    u.arc(cx, cy, R * 1.008, 0, Math.PI * 2);
    u.stroke();
  }
}

/** Everything that stays put, painted once per size: `under` holds the glow, the far side of the disk, the arch, the
 * shadow and the photon ring; `over` holds the near side of the disk, which crosses in front of the shadow. */
export function paintStill(under: CanvasRenderingContext2D, over: CanvasRenderingContext2D, w: number, h: number) {
  if (!streaks) makeArt();
  const geo = holeGeometry(w, h);
  begin([under, over], w, h);
  glow(under, geo);
  // the far side of the disk, then the arch: soft light first, then the fine streaks
  diskStreaks(under, geo, Math.PI, Math.PI * 2, true);
  diskStreaks(under, geo, Math.PI, Math.PI * 2, false);
  archStreaks(under, geo, true);
  archStreaks(under, geo, false);
  thinImage(under, geo);
  shadow(under, geo);
  // the near side of the disk, in front of everything
  diskStreaks(over, geo, 0, Math.PI, true);
  diskStreaks(over, geo, 0, Math.PI, false);
  for (const g of [under, over]) g.globalCompositeOperation = "source-over";
}

/** For the turning disk (blackHoleGl.ts): the glow and the thin image, which lie under the streaks... */
export function paintUnder(g: CanvasRenderingContext2D, w: number, h: number) {
  const geo = holeGeometry(w, h);
  begin([g], w, h);
  glow(g, geo);
  thinImage(g, geo);
  g.globalCompositeOperation = "source-over";
}

/** ...and the shadow with its photon ring, laid over the far side and the arch and under the near side. */
export function paintShadow(g: CanvasRenderingContext2D, w: number, h: number) {
  const geo = holeGeometry(w, h);
  begin([g], w, h);
  shadow(g, geo);
  g.globalCompositeOperation = "source-over";
}

/**
 * The streaks as strips of triangles for the graphics chip: each streak piece is a line of points round its ellipse,
 * every point twice (one each side of the line). Per point: radius, angle, signed width (the sign says which side),
 * strength, then the colour as three bytes. The arch carries each piece twice, half a turn apart, so whatever half is
 * on top at any moment shows every streak once, as the still picture does.
 */
export const MESH_STRIDE = 20;
/** The disk's or the arch's strip, with a point every `step` radians: a bigger hole needs smaller steps, so that a
 * curve never shows corners, and a small one draws fewer points. */
export function streakMesh(kind: "disk" | "arch", step: number): { data: ArrayBuffer; count: number } {
  if (!streaks) makeArt();
  const pieces: { a: number; from: number; len: number; width: number; alpha: number; rgb: number[] }[] = [];
  for (const s of streaks!) {
    if (kind === "arch" && s.a > 3.3) continue;
    const rgb = s.rgb.split(",").map(Number);
    const fade = Math.max(0, 1 - (s.a - INNER) / 2.6);
    for (const seg of s.segs) {
      if (kind === "disk") {
        pieces.push({ a: s.a, from: seg.start, len: seg.len, width: s.width, alpha: s.alpha * seg.gain, rgb });
      } else {
        // the still picture cut each piece where the arch ends, so on average a piece showed about this long
        const len = Math.min(Math.PI, seg.len * 0.5), alpha = s.alpha * seg.gain * (0.55 + 0.75 * fade);
        for (const turn of [0, Math.PI]) {
          pieces.push({ a: s.a, from: seg.start + turn, len, width: s.width, alpha, rgb });
        }
      }
    }
  }
  let count = 0;
  for (const p of pieces) count += 2 * (Math.ceil(p.len / step) + 1) + 2;
  const data = new ArrayBuffer(count * MESH_STRIDE), f = new Float32Array(data), b = new Uint8Array(data);
  let v = 0;
  const put = (a: number, angle: number, side: number, alpha: number, rgb: number[]) => {
    const o = v * MESH_STRIDE;
    f[o / 4] = a; f[o / 4 + 1] = angle; f[o / 4 + 2] = side; f[o / 4 + 3] = alpha;
    b[o + 16] = rgb[0]; b[o + 17] = rgb[1]; b[o + 18] = rgb[2];
    v++;
  };
  for (const p of pieces) {
    const n = Math.ceil(p.len / step);
    // a repeated first and last point join the pieces into one strip without drawing anything between them
    put(p.a, p.from, -p.width, p.alpha, p.rgb);
    for (let j = 0; j <= n; j++) {
      const angle = p.from + (p.len * j) / n;
      put(p.a, angle, -p.width, p.alpha, p.rgb);
      put(p.a, angle, p.width, p.alpha, p.rgb);
    }
    put(p.a, p.from + p.len, p.width, p.alpha, p.rgb);
  }
  return { data, count: v };
}

/** Brighter patches of light travelling round the disk at time `t` seconds, on the side between lo and hi. */
function paintPulses(g: CanvasRenderingContext2D, geo: HoleGeometry, t: number, lo: number, hi: number, lensed: boolean) {
  const { cx, cy, R } = geo;
  for (const p of pulses!) {
    const at = ((p.phase - t * p.speed) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2);
    for (const shift of [0, Math.PI * 2]) {
      const a0 = Math.max(at - shift, lo), a1 = Math.min(at + p.len - shift, hi);
      if (a1 <= a0) continue;
      const [r, gg, b] = diskRgb(p.a, -0.2);
      for (const [wd, al] of [[4, 0.1], [1.4, 0.45]] as const) {
        g.lineWidth = Math.max(0.6, wd * geo.scale);
        g.strokeStyle = `rgba(${r}, ${gg}, ${b}, ${al * p.gain * beamAt((a0 + a1) / 2, 0.35)})`;
        g.beginPath();
        if (lensed) {
          // the far side's patch also shows in the arch, at the matching place over the top
          const { rx, ry } = arch(p.a);
          g.ellipse(cx, cy, rx * R, ry * R, TILT, a0, a1);
        } else {
          g.ellipse(cx, cy, p.a * R, p.a * R * FLAT, TILT, a0, a1);
        }
        g.stroke();
      }
    }
  }
}

/** One frame: the still layers, with the travelling light behind and in front of the shadow. `t` null = no light. */
export function paintFrame(g: CanvasRenderingContext2D, under: HTMLCanvasElement, over: HTMLCanvasElement,
  w: number, h: number, t: number | null) {
  if (!streaks) makeArt();
  const geo = holeGeometry(w, h);
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.globalCompositeOperation = "source-over";
  g.clearRect(0, 0, w, h);
  g.drawImage(under, 0, 0);
  if (t !== null) {
    g.globalCompositeOperation = "lighter";
    g.lineCap = "round";
    // the far side never crosses the shadow
    g.save();
    g.beginPath();
    g.rect(0, 0, w, h);
    g.arc(geo.cx, geo.cy, geo.R * 1.004, 0, Math.PI * 2, true);
    g.clip("evenodd");
    paintPulses(g, geo, t, Math.PI, Math.PI * 2, false);
    paintPulses(g, geo, t, Math.PI, Math.PI * 2, true);
    g.restore();
  }
  g.globalCompositeOperation = "lighter";
  g.drawImage(over, 0, 0);
  if (t !== null) paintPulses(g, geo, t, 0, Math.PI, false);
  g.globalCompositeOperation = "source-over";
}
