/**
 * Tiny pixel engine for the robot sprites.
 *
 * Art is drawn into 48x64 layers with outlined, auto-shaded shapes (light from top-left),
 * then emitted as one SVG path per colour. Colours starting with "@" are tokens resolved
 * at render time (used for the tintable task card).
 */

export const W = 48;
export const H = 64;

export type Color = string;

export const OUTLINE = "#0A0D18";

// ---------------------------------------------------------------- colour helpers

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h.slice(0, 6),
    16,
  );
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex(r: number, g: number, b: number): string {
  const c = (v: number) =>
    Math.max(0, Math.min(255, Math.round(v)))
      .toString(16)
      .padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}
export function mix(a: Color, b: Color, t: number): Color {
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  return rgbToHex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t);
}
export const lighten = (c: Color, t: number) => mix(c, "#FFFFFF", t);
export const darken = (c: Color, t: number) => mix(c, "#0A0D20", t);

/** Desaturated, flattened version of a colour (for the "unavailable" state). */
export function grey(c: Color): Color {
  if (c.startsWith("@")) return c;
  const alpha = c.length === 9 ? c.slice(7) : "";
  const [r, g, b] = hexToRgb(c);
  const l = 0.3 * r + 0.59 * g + 0.11 * b;
  const v = 52 + l * 0.5;
  return rgbToHex(v * 0.97, v, v * 1.06) + alpha;
}

/** A material: four tones of one colour, light from the top-left. */
export interface Mat {
  hi: Color;
  mid: Color;
  lo: Color;
  dk: Color;
}

export function mat(base: Color, contrast = 1): Mat {
  return {
    hi: lighten(base, 0.5 * contrast),
    mid: base,
    lo: darken(base, 0.2 * contrast),
    dk: darken(base, 0.4 * contrast),
  };
}
export function flat(c: Color): Mat {
  return { hi: c, mid: c, lo: c, dk: c };
}

// ---------------------------------------------------------------- shapes

/** A boolean mask of size w x h. */
export interface Shape {
  w: number;
  h: number;
  m: Uint8Array;
}

export function shapeFrom(w: number, h: number, f: (x: number, y: number) => boolean): Shape {
  const m = new Uint8Array(Math.max(0, w * h));
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (f(x, y)) m[y * w + x] = 1;
  return { w, h, m };
}
export const inShape = (s: Shape, x: number, y: number) =>
  x >= 0 && y >= 0 && x < s.w && y < s.h && s.m[y * s.w + x] === 1;

export const rect = (w: number, h: number) => shapeFrom(w, h, () => true);

/** Rounded rectangle. r may differ for top and bottom corners. */
export function rr(w: number, h: number, r: number, rb = r): Shape {
  return shapeFrom(w, h, (x, y) => {
    const rad = y < h / 2 ? r : rb;
    if (rad <= 0) return true;
    const cx = x < rad ? rad - 0.5 : x >= w - rad ? w - rad - 0.5 : x;
    const cy = y < rad && y < h / 2 ? rad - 0.5 : y >= h - rad && y >= h / 2 ? h - rad - 0.5 : y;
    if (cx === x || cy === y) return true;
    const dx = x - cx,
      dy = y - cy;
    return dx * dx + dy * dy <= rad * rad * 0.98;
  });
}

export function ellipse(w: number, h: number): Shape {
  return shapeFrom(w, h, (x, y) => {
    const dx = (x + 0.5 - w / 2) / (w / 2);
    const dy = (y + 0.5 - h / 2) / (h / 2);
    return dx * dx + dy * dy <= 1.02;
  });
}

/** Trapezoid: `top` and `bottom` are horizontal insets on each side. */
export function trap(w: number, h: number, top: number, bottom: number, r = 0): Shape {
  const base = r > 0 ? rr(w, h, r) : rect(w, h);
  return shapeFrom(w, h, (x, y) => {
    const t = h <= 1 ? 0 : y / (h - 1);
    const inset = Math.round(top + (bottom - top) * t);
    return x >= inset && x < w - inset && inShape(base, x, y);
  });
}

/** Hexagon-ish: corners cut at 45 degrees by `cut` pixels (top and bottom). */
export function octo(w: number, h: number, cut: number, cutB = cut): Shape {
  return shapeFrom(w, h, (x, y) => {
    const c = y < h / 2 ? cut - y : cutB - (h - 1 - y);
    return x >= c && x < w - Math.max(0, c);
  });
}

/** Pointed-side hexagon: points on left and right at mid-height. */
export function hexPointy(w: number, h: number, cut: number): Shape {
  return shapeFrom(w, h, (x, y) => {
    const mid = (h - 1) / 2;
    const c = Math.round((Math.abs(y - mid) / mid) * cut);
    return x >= c && x < w - c;
  });
}

/** Shape from ASCII rows: any non-space, non-'.' char is filled. */
export function ascii(rows: string[]): Shape {
  const w = Math.max(...rows.map((r) => r.length));
  return shapeFrom(w, rows.length, (x, y) => {
    const ch = rows[y][x];
    return ch !== undefined && ch !== " " && ch !== ".";
  });
}

export function union(a: Shape, b: Shape, bx = 0, by = 0): Shape {
  const w = Math.max(a.w, b.w + bx),
    h = Math.max(a.h, b.h + by);
  return shapeFrom(w, h, (x, y) => inShape(a, x, y) || inShape(b, x - bx, y - by));
}
export function subtract(a: Shape, b: Shape, bx = 0, by = 0): Shape {
  return shapeFrom(a.w, a.h, (x, y) => inShape(a, x, y) && !inShape(b, x - bx, y - by));
}
export function flipX(s: Shape): Shape {
  return shapeFrom(s.w, s.h, (x, y) => inShape(s, s.w - 1 - x, y));
}

// ---------------------------------------------------------------- layers

export class Layer {
  px: (Color | null)[] = new Array(W * H).fill(null);
  get(x: number, y: number): Color | null {
    if (x < 0 || y < 0 || x >= W || y >= H) return null;
    return this.px[y * W + x];
  }
  set(x: number, y: number, c: Color | null) {
    x = Math.round(x);
    y = Math.round(y);
    if (x < 0 || y < 0 || x >= W || y >= H) return;
    this.px[y * W + x] = c;
  }
  mirror() {
    const out: (Color | null)[] = new Array(W * H).fill(null);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) out[y * W + (W - 1 - x)] = this.px[y * W + x];
    this.px = out;
  }
  map(f: (c: Color) => Color) {
    this.px = this.px.map((c) => (c ? f(c) : c));
  }
  isEmpty() {
    return this.px.every((c) => c === null);
  }
}

export interface ShapeOpts {
  /** Draw a 1px dark outline around the shape (default true). */
  outline?: boolean | Color;
  /** "auto" = top-left highlight, bottom/right shade; "flat" = mid only; "soft" = only bottom shade. */
  shade?: "auto" | "flat" | "soft" | "vertical";
  /** Add a 2px white glint near the top-left. */
  glint?: boolean;
}

export type LayerName = "back" | "base" | "card" | "over";

/** A painter draws onto named layers. All coordinates are integers in the 48x64 cell. */
export class Painter {
  layers: Record<LayerName, Layer> = { back: new Layer(), base: new Layer(), card: new Layer(), over: new Layer() };
  target: LayerName = "base";
  /** Text decals: stamped after mirroring so lettering is never drawn backwards. */
  decals: { x: number; y: number; text: string; color: Color; layer: LayerName }[] = [];
  /** Global offset applied to every draw (used for bobbing). */
  ox = 0;
  oy = 0;

  to(layer: LayerName) {
    this.target = layer;
    return this;
  }
  get L() {
    return this.layers[this.target];
  }

  px(x: number, y: number, c: Color) {
    this.L.set(x + this.ox, y + this.oy, c);
  }
  fill(x: number, y: number, w: number, h: number, c: Color) {
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) this.px(x + i, y + j, c);
  }
  hline(x: number, y: number, w: number, c: Color) {
    this.fill(x, y, w, 1, c);
  }
  vline(x: number, y: number, h: number, c: Color) {
    this.fill(x, y, 1, h, c);
  }
  /** Plot pixels from ASCII rows with a colour key; '.' and ' ' are transparent. */
  map(x: number, y: number, rows: string[], key: Record<string, Color>) {
    rows.forEach((row, j) => {
      for (let i = 0; i < row.length; i++) {
        const c = key[row[i]];
        if (c) this.px(x + i, y + j, c);
      }
    });
  }
  /** Pixel line (Bresenham). */
  line(x0: number, y0: number, x1: number, y1: number, c: Color) {
    const dx = Math.abs(x1 - x0),
      dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1,
      sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (;;) {
      this.px(x0, y0, c);
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) {
        err += dy;
        x0 += sx;
      }
      if (e2 <= dx) {
        err += dx;
        y0 += sy;
      }
    }
  }

  /** Draw an outlined, shaded shape at (x, y). */
  shape(x: number, y: number, s: Shape, m: Mat, o: ShapeOpts = {}) {
    const outline = o.outline === undefined ? OUTLINE : o.outline;
    if (outline) {
      const oc = typeof outline === "string" ? outline : OUTLINE;
      for (let j = -1; j <= s.h; j++)
        for (let i = -1; i <= s.w; i++) {
          if (inShape(s, i, j)) continue;
          if (inShape(s, i - 1, j) || inShape(s, i + 1, j) || inShape(s, i, j - 1) || inShape(s, i, j + 1))
            this.px(x + i, y + j, oc);
        }
    }
    const mode = o.shade ?? "auto";
    for (let j = 0; j < s.h; j++)
      for (let i = 0; i < s.w; i++) {
        if (!inShape(s, i, j)) continue;
        let c = m.mid;
        if (mode === "auto") {
          const top = !inShape(s, i, j - 1),
            left = !inShape(s, i - 1, j);
          const bottom = !inShape(s, i, j + 1),
            right = !inShape(s, i + 1, j);
          const bottom2 = !inShape(s, i, j + 2);
          if (bottom) c = m.dk;
          else if (right || bottom2) c = m.lo;
          else if (top || left) c = m.hi;
        } else if (mode === "soft") {
          if (!inShape(s, i, j + 1)) c = m.lo;
        } else if (mode === "vertical") {
          const t = j / Math.max(1, s.h - 1);
          c = t < 0.25 ? m.hi : t > 0.75 ? m.lo : m.mid;
        }
        this.px(x + i, y + j, c);
      }
    if (o.glint) {
      // find first filled pixels near top-left
      for (let j = 1; j < s.h; j++) {
        let first = -1;
        for (let i = 0; i < s.w; i++)
          if (inShape(s, i, j)) {
            first = i;
            break;
          }
        if (first >= 0) {
          this.px(x + first + 2, y + j + 1, "#FFFFFF");
          this.px(x + first + 3, y + j + 1, "#FFFFFF");
          this.px(x + first + 2, y + j + 2, "#FFFFFF");
          break;
        }
      }
    }
  }

  /** Flat-filled shape with no outline (details, glass). */
  blot(x: number, y: number, s: Shape, c: Color) {
    for (let j = 0; j < s.h; j++) for (let i = 0; i < s.w; i++) if (inShape(s, i, j)) this.px(x + i, y + j, c);
  }

  text(x: number, y: number, text: string, color: Color) {
    this.decals.push({ x: x + this.ox, y: y + this.oy, text, color, layer: this.target });
  }
}

// ---------------------------------------------------------------- tiny font (3x5, a few glyphs)

const FONT: Record<string, string[]> = {
  C: ["###", "#..", "#..", "#..", "###"],
  A: [".#.", "#.#", "###", "#.#", "#.#"],
  a: ["...", "##.", "..#", "###", "###"],
  "!": ["#", "#", "#", ".", "#"],
};

export function textWidth(text: string) {
  return text.split("").reduce((w, ch) => w + (FONT[ch]?.[0].length ?? 3) + 1, -1);
}

export function stampText(layer: Layer, x: number, y: number, text: string, color: Color) {
  let cx = x;
  for (const ch of text) {
    const g = FONT[ch];
    if (g)
      g.forEach((row, j) => {
        for (let i = 0; i < row.length; i++) if (row[i] === "#") layer.set(cx + i, y + j, color);
      });
    cx += (g?.[0].length ?? 3) + 1;
  }
}

// ---------------------------------------------------------------- SVG output

export interface PathRun {
  fill: string;
  d: string;
  opacity?: number;
}

/** Group a layer into one path per colour, emitting horizontal runs. */
export function layerToPaths(layer: Layer): PathRun[] {
  const runs = new Map<string, string[]>();
  for (let y = 0; y < H; y++) {
    let x = 0;
    while (x < W) {
      const c = layer.px[y * W + x];
      if (!c) {
        x++;
        continue;
      }
      let e = x + 1;
      while (e < W && layer.px[y * W + e] === c) e++;
      const list = runs.get(c) ?? [];
      list.push(`M${x} ${y}h${e - x}v1h-${e - x}z`);
      runs.set(c, list);
      x = e;
    }
  }
  return [...runs.entries()].map(([c, parts]) => {
    if (c.length === 9 && c.startsWith("#")) {
      return { fill: c.slice(0, 7), opacity: parseInt(c.slice(7), 16) / 255, d: parts.join("") };
    }
    return { fill: c, d: parts.join("") };
  });
}
