/**
 * The moving sky behind every page (the owner, 2026-11-20: "give the background animation like the stars and black
 * hole", then "make the backround animated like we are moving"). The ship flies on to the right, so the sky streams
 * past to the left, the nearer things faster: the two tiles of small stars (space.css) slide slowly, brighter stars
 * twinkle as they go by, specks of dust rush past, and now and then a shooting star crosses. The nebula holds still,
 * far away. It is scenery and says nothing about work.
 *
 * The tiles are moved by the browser's compositor (addDrift), which costs the page nothing. The rest is one clock and
 * one list for the whole window, drawn on canvases that each show their own piece (the window, and the masthead, which
 * paints its own copy of the sky to hide what scrolls under it). Each frame only the small squares round what moved are
 * cleared and drawn again, about 30 times a second (60 while a shooting star crosses). The clock runs only while
 * motion is allowed; held still, the sky is one picture and nothing is drawn.
 */

type Star = {
  u: number; v: number; layer: 0 | 1 | 2; size: number; base: number; amp: number; freq: number; phase: number;
  tint: number; spikes: boolean;
};
type Meteor = { at: number; x: number; y: number; dx: number; dy: number; speed: number; dur: number; tail: number };
type Sky = {
  canvas: HTMLCanvasElement; g: CanvasRenderingContext2D; dpr: number;
  /** Where the canvas is in the window, CSS pixels. */
  x: number; y: number; w: number; h: number;
  /** What was drawn last frame (device pixels: x, y, w, h, ...), cleared before the next. */
  drawn: number[]; whole: boolean;
};

/** Drift to the left, in CSS pixels a second, for the far, middle and near bright stars (the tiles of small stars,
 * further away, go slower: TILES). */
const DRIFT = [10, 18, 30];
const TINTS = ["255, 255, 255", "206, 222, 255", "255, 228, 196", "176, 236, 255"];
const POOL = 420;
const FRAME = 1000 / 30, FAST = 1000 / 60;

function random(seed: number) {
  let v = seed;
  return () => {
    v = (v * 16807) % 2147483647;
    return v / 2147483647;
  };
}

let stars: Star[] | null = null;
function makeStars(): Star[] {
  const r = random(20261120), list: Star[] = [];
  for (let i = 0; i < POOL; i++) {
    const layer = (r() < 0.5 ? 0 : r() < 0.62 ? 1 : 2) as 0 | 1 | 2;
    const deep = r() < 0.35;
    const t = r();
    list.push({
      u: r(), v: r(), layer,
      size: [0.55, 0.85, 1.15][layer] + r() * [0.35, 0.45, 0.65][layer],
      base: [0.45, 0.62, 0.8][layer] + r() * 0.2,
      amp: deep ? 0.55 + r() * 0.35 : 0.15 + r() * 0.3,
      freq: 0.08 + r() * 0.4, phase: r() * Math.PI * 2,
      tint: t < 0.58 ? 0 : t < 0.8 ? 1 : t < 0.94 ? 2 : 3,
      spikes: layer === 2 && r() < 0.16,
    });
  }
  return list;
}

/** Specks of dust close by, rushing past much faster than any star: what most makes the ship feel on its way. */
type Dust = { u: number; v: number; speed: number; alpha: number };
const DUST_POOL = 40;
let dust: Dust[] | null = null;
function makeDust(): Dust[] {
  const r = random(90210), list: Dust[] = [];
  for (let i = 0; i < DUST_POOL; i++) list.push({ u: r(), v: r(), speed: 160 + r() * 100, alpha: 0.3 + r() * 0.4 });
  return list;
}

/** Shooting stars, in the order they come: one every 7 to 16 seconds of sky time. Only the next few are kept. */
const meteors: Meteor[] = [];
const nextMeteor = random(7121);
function meteorsUpTo(t: number) {
  while (!meteors.length || meteors[meteors.length - 1].at < t + 20) {
    const r = nextMeteor, prev = meteors.length ? meteors[meteors.length - 1].at : -2;
    const angle = (12 + r() * 20) * (Math.PI / 180);
    meteors.push({
      at: prev + 7 + r() * 9, x: 0.35 + r() * 0.65, y: 0.03 + r() * 0.42,
      dx: -Math.cos(angle), dy: Math.sin(angle), speed: 620 + r() * 380, dur: 0.75 + r() * 0.4, tail: 140 + r() * 130,
    });
  }
  // the ones that have crossed are gone for good (the last stays: the next is timed from it)
  while (meteors.length > 1 && meteors[0].at + meteors[0].dur < t) meteors.shift();
}

/** A soft round star (or rays, or a streak of dust), drawn once per tint, then stamped at each one's size. */
const sprites = new Map<string, HTMLCanvasElement>();
function sprite(kind: "dot" | "spikes" | "streak", tint: number) {
  const key = `${kind}${tint}`;
  let c = sprites.get(key);
  if (c) return c;
  c = document.createElement("canvas");
  const S = kind === "dot" ? 32 : kind === "spikes" ? 96 : 64;
  c.width = S;
  c.height = kind === "streak" ? 8 : S;
  const g = c.getContext("2d")!, m = S / 2, col = TINTS[tint];
  if (kind === "streak") {
    // bright at the front (the left: it rushes left), fading out behind, soft at the edges
    const along = g.createLinearGradient(0, 0, S, 0);
    along.addColorStop(0, `rgba(255, 255, 255, 1)`);
    along.addColorStop(0.2, `rgba(${col}, 0.75)`);
    along.addColorStop(1, `rgba(${col}, 0)`);
    g.fillStyle = along;
    g.fillRect(0, 2, S, 4);
    g.globalAlpha = 0.35;
    g.fillRect(0, 1, S, 6);
  } else if (kind === "dot") {
    const gr = g.createRadialGradient(m, m, 0, m, m, m);
    gr.addColorStop(0, `rgba(255, 255, 255, 1)`);
    gr.addColorStop(0.16, `rgba(${col}, 0.95)`);
    gr.addColorStop(0.34, `rgba(${col}, 0.28)`);
    gr.addColorStop(1, `rgba(${col}, 0)`);
    g.fillStyle = gr;
    g.fillRect(0, 0, S, S);
  } else {
    // four thin rays, brightest at the middle
    for (const [x0, y0, x1, y1] of [[0, m, S, m], [m, 0, m, S]]) {
      const gr = g.createLinearGradient(x0, y0, x1, y1);
      gr.addColorStop(0, `rgba(${col}, 0)`);
      gr.addColorStop(0.5, `rgba(${col}, 0.9)`);
      gr.addColorStop(1, `rgba(${col}, 0)`);
      g.fillStyle = gr;
      if (y0 === y1) g.fillRect(0, m - 0.75, S, 1.5);
      else g.fillRect(m - 0.75, 0, 1.5, S);
    }
  }
  c.addEventListener("contextrestored", restored);
  sprites.set(key, c);
  return c;
}

/**
 * Where the browser paints canvases on the graphics chip (Windows), a reset of the chip gives them back empty: the
 * star pictures are drawn again and every sky is painted again, once for however many canvases come back.
 */
let restoring = 0;
function restored() {
  sprites.clear();
  cancelAnimationFrame(restoring);
  restoring = requestAnimationFrame(redrawAll);
}

const skies = new Set<Sky>();
let skyTime = 0, last = 0, raf = 0, moving = false;
let view = { w: 1, h: 1 };

const wrap = (x: number, span: number) => ((x % span) + span) % span;

function paint(sky: Sky, t: number) {
  const { g, dpr, canvas } = sky;
  if (!sky.w || !sky.h) return;
  if (sky.whole) g.clearRect(0, 0, canvas.width, canvas.height);
  else {
    const d = sky.drawn;
    for (let i = 0; i < d.length; i += 4) g.clearRect(d[i], d[i + 1], d[i + 2], d[i + 3]);
  }
  const drawn: number[] = [];
  let area = 0;
  // `img` centred on (cx, cy), `wide` by `high` CSS pixels
  const put = (img: HTMLCanvasElement, cx: number, cy: number, wide: number, high: number, alpha: number) => {
    const dw = wide * dpr, dh = high * dpr;
    const x = Math.floor((cx - sky.x) * dpr - dw / 2), y = Math.floor((cy - sky.y) * dpr - dh / 2);
    if (x > canvas.width || y > canvas.height || x + dw < 0 || y + dh < 0 || alpha <= 0.01) return;
    g.globalAlpha = Math.min(1, alpha);
    g.drawImage(img, x, y, dw, dh);
    const bw = Math.ceil(dw) + 2, bh = Math.ceil(dh) + 2;
    drawn.push(x - 1, y - 1, bw, bh);
    area += bw * bh;
  };
  const stamp = (img: HTMLCanvasElement, cx: number, cy: number, size: number, alpha: number) =>
    put(img, cx, cy, size, size, alpha);
  // as many stars as suit the window: about one for every 9,000 square pixels
  const list = (stars ??= makeStars()), n = Math.min(POOL, Math.max(60, Math.round((view.w * view.h) / 9000)));
  const spanX = view.w + 24;
  for (let i = 0; i < n; i++) {
    const s = list[i];
    const x = wrap(s.u * spanX - DRIFT[s.layer] * t, spanX) - 12, y = s.v * view.h;
    const glow = s.base * (1 - s.amp * (0.5 + 0.5 * Math.sin(t * s.freq * Math.PI * 2 + s.phase)));
    stamp(sprite("dot", s.tint), x, y, s.size * 7, glow);
    if (s.spikes) stamp(sprite("spikes", s.tint), x, y, s.size * 9 * (0.55 + glow * 0.6), glow * 0.8);
  }
  // dust and shooting stars, only while the sky moves (a still sky never holds them in mid-flight)
  if (moving) {
    const specks = (dust ??= makeDust()), nd = Math.min(DUST_POOL, Math.max(6, Math.round((view.w * view.h) / 75000)));
    for (let i = 0; i < nd; i++) {
      // x is the speck's front; it wraps round once its tail has left on the left
      const d = specks[i], len = d.speed * 0.1, span = view.w + len + 24;
      const x = wrap(d.u * span - d.speed * t, span) - len - 12, y = d.v * view.h;
      put(sprite("streak", 1), x + len / 2, y, len, 2.4, d.alpha);
    }
    meteorsUpTo(t);
    for (const m of meteors) {
      if (t < m.at || t > m.at + m.dur) continue;
      const age = t - m.at, run = m.speed * age;
      const fade = Math.min(1, age / 0.12) * Math.min(1, (m.at + m.dur - t) / (m.dur * 0.4));
      const hx = m.x * view.w + m.dx * run, hy = m.y * view.h + m.dy * run;
      const len = Math.min(m.tail, run), tx = hx - m.dx * len, ty = hy - m.dy * len;
      const ax = (Math.min(hx, tx) - sky.x) * dpr - 8, ay = (Math.min(hy, ty) - sky.y) * dpr - 8;
      const bw = Math.abs(hx - tx) * dpr + 16, bh = Math.abs(hy - ty) * dpr + 16;
      if (ax > canvas.width || ay > canvas.height || ax + bw < 0 || ay + bh < 0) continue;
      const gr = g.createLinearGradient((tx - sky.x) * dpr, (ty - sky.y) * dpr, (hx - sky.x) * dpr, (hy - sky.y) * dpr);
      gr.addColorStop(0, "rgba(206, 228, 255, 0)");
      gr.addColorStop(0.75, `rgba(220, 236, 255, ${0.45 * fade})`);
      gr.addColorStop(1, `rgba(255, 255, 255, ${0.95 * fade})`);
      g.globalAlpha = 1;
      g.strokeStyle = gr;
      g.lineWidth = 1.6 * dpr;
      g.lineCap = "round";
      g.beginPath();
      g.moveTo((tx - sky.x) * dpr, (ty - sky.y) * dpr);
      g.lineTo((hx - sky.x) * dpr, (hy - sky.y) * dpr);
      g.stroke();
      drawn.push(Math.floor(ax), Math.floor(ay), Math.ceil(bw) + 1, Math.ceil(bh) + 1);
      area += bw * bh;
      stamp(sprite("dot", 1), hx, hy, 9, fade);
    }
  }
  g.globalAlpha = 1;
  sky.drawn = drawn;
  // when most of the canvas changes anyway, one clear is cheaper than many
  sky.whole = area > canvas.width * canvas.height * 0.35;
}

function meteorShowing(t: number) {
  return meteors.some((m) => t >= m.at - 0.05 && t <= m.at + m.dur);
}

function frame(now: number) {
  raf = requestAnimationFrame(frame);
  const gap = now - last;
  if (gap < (meteorShowing(skyTime) ? FAST : FRAME) - 2) return;
  // the sky's own clock: it stops while the sky holds still, and never jumps more than a tenth of a second
  skyTime += Math.min(0.1, gap / 1000);
  last = now;
  for (const sky of skies) paint(sky, skyTime);
}

function redrawAll() {
  for (const sky of skies) {
    sky.whole = true;
    paint(sky, skyTime);
  }
}

/** The tiles of small stars (space.css --sky-far, --sky-near): how wide one tile is and how fast it slides left. */
const TILES = { far: { width: 797, speed: 6 }, near: { width: 512, speed: 11 } } as const;
/** Every tile layer showing, with which tile it is. */
const drifts = new Map<Animation, keyof typeof TILES>();

/**
 * Slide tile layers (each as wide as its box plus one tile) to the left forever: one tile along, the picture is the
 * same as at the start, so the loop never shows. The browser's compositor moves them; the page does no work per frame.
 * A new layer starts where the same tile already showing is, so the window's and the masthead's copies line up.
 */
export function addDrift(layers: HTMLElement[]) {
  const mine: Animation[] = [];
  for (const el of layers) {
    if (typeof el.animate !== "function") continue;
    const kind: keyof typeof TILES = el.classList.contains("far") ? "far" : "near";
    const { width, speed } = TILES[kind], loop = (width / speed) * 1000;
    const twin = [...drifts].find(([, k]) => k === kind)?.[0];
    const anim = el.animate([{ transform: "translateX(0)" }, { transform: `translateX(${-width}px)` }],
      { duration: loop, iterations: Infinity, easing: "linear" });
    const at = twin?.currentTime;
    anim.currentTime = typeof at === "number" ? at : (skyTime * 1000) % loop;
    if (!moving) anim.pause();
    drifts.set(anim, kind);
    mine.push(anim);
  }
  return () => mine.forEach((a) => {
    a.cancel();
    drifts.delete(a);
  });
}

/** Start or stop the sky (motion allowed, Low power off, window shown). */
export function setSkyMoving(on: boolean) {
  if (on === moving) return;
  moving = on;
  cancelAnimationFrame(raf);
  for (const a of drifts.keys()) {
    if (on) a.play();
    else a.pause();
  }
  if (on) {
    last = performance.now();
    raf = requestAnimationFrame(frame);
  } else redrawAll();
}

/** Show the sky on `canvas`; `place` says where the canvas is in the window. Returns a function that measures again
 * (after a resize or scroll) and one that lets the canvas go. */
export function addSky(canvas: HTMLCanvasElement, place: () => { x: number; y: number; w: number; h: number }) {
  const g = canvas.getContext("2d");
  if (!g) return { measure: () => undefined, remove: () => undefined };
  const sky: Sky = { canvas, g, dpr: 1, x: 0, y: 0, w: 0, h: 0, drawn: [], whole: true };
  const measure = () => {
    const p = place();
    // where the stars are depends on the window's size (the scrollbar's room included, so that it showing or going
    // moves nothing): when that changes, every sky is painted again, a still one too
    const next = { w: window.innerWidth || 1, h: window.innerHeight || 1 };
    const viewChanged = next.w !== view.w || next.h !== view.h;
    view = next;
    // sharp on high-density screens, but never more than about 4.5 million pixels for the whole window
    let dpr = Math.min(2, window.devicePixelRatio || 1);
    if (p.w * p.h * dpr * dpr > 4.5e6) dpr = Math.max(1, Math.sqrt(4.5e6 / Math.max(1, p.w * p.h)));
    const sized = Math.round(p.w) !== Math.round(sky.w) || Math.round(p.h) !== Math.round(sky.h) || dpr !== sky.dpr;
    const moved = p.x !== sky.x || p.y !== sky.y;
    if (!sized && !moved && !viewChanged) return;
    Object.assign(sky, p);
    if (sized) {
      sky.dpr = dpr;
      canvas.width = Math.max(1, Math.round(p.w * dpr));
      canvas.height = Math.max(1, Math.round(p.h * dpr));
    }
    if (viewChanged) redrawAll();
    else {
      sky.whole = true;
      paint(sky, skyTime);
    }
  };
  canvas.addEventListener("contextrestored", restored);
  skies.add(sky);
  measure();
  return {
    measure,
    remove: () => {
      canvas.removeEventListener("contextrestored", restored);
      skies.delete(sky);
    },
  };
}
