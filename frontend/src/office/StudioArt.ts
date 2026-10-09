/**
 * The studio's authored pixel robot family. All geometry and pose offsets use whole world pixels;
 * the scene renderer must use nearest-neighbour sampling when it scales this 48×64-ish artwork.
 * Equipment markings are identity motifs, never invented progress, charts or app results.
 */
import { Container, Graphics } from "pixi.js";
import type { Character, Dir } from "./cast";
import type { Pose } from "./sprites";

const INK = "#101725";
const JOINT = "#364354";
const LIGHT = "#f8faf2";
const EDGE = "#7f94a5";

function px(g: Graphics, x: number, y: number, w: number, h: number, color: string, alpha = 1) {
  if (w > 0 && h > 0) g.rect(x, y, w, h).fill({ color, alpha });
}

function box(g: Graphics, x: number, y: number, w: number, h: number, color: string,
  dark = INK, highlight = LIGHT) {
  px(g, x, y, w, h, dark);
  px(g, x + 1, y + 1, w - 2, h - 2, color);
  px(g, x + 1, y + 1, w - 3, 1, highlight, 0.55);
  px(g, x + w - 2, y + 2, 1, h - 3, INK, 0.24);
  px(g, x + 2, y + h - 2, w - 3, 1, INK, 0.2);
}

/** A stepped metal silhouette, with a cut-in shadow, rim light and a quiet reflected lower edge. */
function shell(g: Graphics, x: number, y: number, w: number, h: number, inset: (r: number) => number,
  color: string, shade: string) {
  for (let r = 0; r < h; r++) {
    const cut = Math.min(Math.floor(w / 2) - 1, Math.max(0, Math.floor(inset(r))));
    const left = x + cut, width = w - cut * 2;
    px(g, left, y + r, width, 1, INK);
    if (r === 0 || r === h - 1) continue;
    const before = inset(r - 1), after = inset(r + 1);
    const edge = Math.max(cut + 1, Math.min(before, after));
    const fillWidth = w - edge * 2;
    if (fillWidth <= 0) continue;
    px(g, x + edge, y + r, fillWidth, 1, color);
    px(g, x + w - edge - Math.min(3, fillWidth), y + r, Math.min(3, fillWidth), 1, shade);
    if (r < h - 4) px(g, x + edge, y + r, 1, 1, LIGHT, 0.62);
    if (r < 3) px(g, x + edge + 1, y + r, Math.max(0, fillWidth - 4), 1, LIGHT, 0.42);
    if (r === h - 3) px(g, x + edge + 2, y + r, Math.max(0, fillWidth - 6), 1, LIGHT, 0.18);
  }
}

const chamfer = (h: number, corner = 3) => (r: number) => Math.max(0, corner - r, r - (h - 1 - corner));
const oval = (w: number, h: number) => (r: number) => {
  const v = (r + 0.5 - h / 2) / (h / 2);
  return Math.round(w / 2 * (1 - Math.sqrt(Math.max(0, 1 - v * v))));
};

function headProfile(c: Character, w: number, h: number): (r: number) => number {
  switch (c.head) {
    case "oval": case "round": case "clock-ring": case "fin-round": return oval(w, h);
    case "dome": case "cap": return (r) => r < 5 ? 5 - r : r > h - 3 ? r - (h - 3) : 0;
    case "trapezoid": return (r) => Math.floor(r / 5) + (r === 0 ? 1 : 0);
    case "slim-trapezoid": return (r) => Math.floor((h - 1 - r) / 4) + (r === h - 1 ? 1 : 0);
    case "angular": return (r) => Math.floor(Math.abs(r - 6) / 3) + 1;
    case "hex": return chamfer(h, 5);
    case "steel-hex": return chamfer(h, 6);
    case "keycap": return (r) => r < 3 ? 3 - r : r === h - 1 ? 1 : 0;
    case "swept": return (r) => r < 4 ? 4 - r : r === h - 1 ? 1 : 0;
    case "jaw": return (r) => r < h - 5 ? (r === 0 ? 4 : 2) : r === h - 1 ? 1 : 0;
    case "book": return (r) => r === 0 || r === h - 1 ? 1 : 0;
    case "box": case "wide": return () => 0;
    case "square": case "cargo": case "director-helmet": return chamfer(h, 1);
    case "beacon": return chamfer(h, 2);
    default: return chamfer(h, 3);
  }
}

function top(g: Graphics, c: Character, y: number, w: number) {
  const p = c.palette, left = -w / 2;
  const mast = (x: number, high: number) => {
    px(g, x, y - high, 2, high + 1, INK);
    px(g, x, y - high + 1, 1, high - 1, EDGE);
    box(g, x - 1, y - high - 2, 4, 3, p.trim);
  };
  switch (c.top) {
    case "crest":
      for (const [x, high] of [[-6, 4], [-1, 7], [4, 4]]) {
        px(g, x - 1, y - high, 4, high + 1, INK);
        px(g, x, y - high + 1, 2, high, p.trim);
        px(g, x, y - high + 1, 1, high - 1, LIGHT, 0.5);
      }
      break;
    case "radar-arch":
      px(g, left + 2, y - 5, 2, 6, INK);
      px(g, -left - 4, y - 5, 2, 6, INK);
      box(g, left + 2, y - 7, w - 4, 3, p.trim);
      box(g, -3, y - 11, 6, 4, p.trim);
      px(g, -1, y - 10, 2, 1, p.eye);
      break;
    case "bar-antennae": mast(-7, 5); mast(5, 5); break;
    case "brim":
      box(g, left - 3, y + 2, w + 6, 4, p.trim);
      px(g, left + 2, y - 2, w - 4, 2, p.trimDark);
      break;
    case "side-dial":
      box(g, -left - 1, y + 5, 5, 8, p.trim);
      px(g, -left + 1, y + 8, 1, 2, INK);
      break;
    case "mast": mast(0, 9); break;
    case "crown3":
      px(g, -6, y - 4, 13, 1, p.trimDark);
      for (const x of [-6, 0, 6]) mast(x, x === 0 ? 8 : 5);
      break;
    case "long-antenna": mast(4, 11); break;
    case "zigzag":
      for (const [x, yy] of [[0, -2], [2, -4], [0, -6], [2, -8]]) px(g, x, y + yy, 2, 3, EDGE);
      box(g, 0, y - 11, 5, 3, p.trim);
      break;
    case "star":
      px(g, 0, y - 6, 1, 7, JOINT);
      px(g, -1, y - 10, 3, 5, INK);
      px(g, -3, y - 8, 7, 1, INK);
      px(g, 0, y - 9, 1, 3, p.trim);
      px(g, -2, y - 8, 5, 1, p.trim);
      break;
    case "spine": box(g, left - 3, y + 2, 4, 14, p.trim); break;
    case "fins":
      for (const side of [-1, 1]) {
        box(g, side < 0 ? left - 5 : -left + 1, y + 3, 4, 3, p.trim);
        box(g, side < 0 ? left - 3 : -left - 1, y + 6, 4, 3, p.trim);
      }
      break;
    case "ear-cups":
      box(g, left + 2, y - 3, w - 4, 3, p.gearDark);
      box(g, left - 4, y + 4, 6, 10, p.gear);
      box(g, -left - 2, y + 4, 6, 10, p.gear);
      px(g, left - 3, y + 5, 2, 6, LIGHT, 0.45);
      break;
    case "key-tabs":
      box(g, left - 3, y + 6, 4, 6, p.trim);
      box(g, -left - 1, y + 6, 4, 6, p.trim);
      break;
    case "pencil":
      px(g, 3, y - 10, 3, 11, INK);
      px(g, 4, y - 9, 1, 7, p.trim);
      px(g, 4, y - 11, 1, 1, p.gearDark);
      px(g, 4, y - 2, 1, 2, p.gear);
      break;
    case "uplink":
      px(g, 0, y - 5, 2, 6, JOINT);
      box(g, -5, y - 8, 12, 3, p.shade);
      px(g, -3, y - 9, 8, 1, INK);
      px(g, 0, y - 12, 1, 3, p.trim);
      break;
    case "bar-fins":
      for (const [x, high] of [[-6, 4], [-1, 7], [4, 5]]) {
        box(g, x, y - high, 3, high + 1, p.trim);
      }
      break;
    case "forked":
      px(g, 0, y - 5, 1, 6, JOINT);
      px(g, -5, y - 6, 11, 2, JOINT);
      for (const x of [-5, 5]) mast(x, 8);
      break;
    case "beacon":
      box(g, -5, y - 5, 11, 5, p.trimDark);
      px(g, -4, y - 4, 2, 2, p.trim);
      px(g, -7, y - 1, 15, 2, JOINT);
      break;
    case "none": break;
  }
}

function face(g: Graphics, eyes: Graphics, c: Character, y: number, w: number) {
  const p = c.palette;
  const fw = w - 6, left = -Math.floor(fw / 2), fy = y + 5;
  box(g, left, fy, fw, 9, p.visor, INK, EDGE);
  px(g, left + 1, fy + 1, fw - 3, 1, p.trim, 0.18);
  px(g, left + 2, fy + 6, fw - 5, 1, "#53748b", 0.2);
  eyes.position.y = fy + 4;
  const pair = (ew = 3, eh = 3, gap = 3) => {
    px(eyes, -gap - ew, -1, ew, eh, p.eye);
    px(eyes, gap, -1, ew, eh, p.eye);
    if (eh > 1) {
      px(eyes, -gap - ew, -1, Math.max(1, ew - 1), 1, LIGHT, 0.58);
      px(eyes, gap, -1, Math.max(1, ew - 1), 1, LIGHT, 0.58);
    }
  };
  switch (c.visor) {
    case "cyclops":
      box(g, -5, fy - 1, 10, 10, p.trimDark);
      px(eyes, -3, -2, 6, 5, p.eye);
      px(eyes, -2, -2, 3, 1, LIGHT);
      px(eyes, 0, -1, 2, 3, "#effdff");
      break;
    case "goggles": case "round-lenses": case "binocular": case "lenses":
      for (const x of [-8, 2]) {
        shell(g, x, fy, 7, 7, chamfer(7, 2), p.trimDark, JOINT);
        px(g, x + 2, fy + 2, 3, 3, p.visor);
      }
      px(g, -1, fy + 3, 3, 1, p.trimDark);
      pair(2, 2, 4);
      break;
    case "horizontal": case "slit": case "visor-band":
      px(eyes, left + 3, 0, fw - 6, 2, p.eye);
      px(eyes, left + 3, 0, 3, 1, LIGHT, 0.5);
      if (c.visor === "visor-band") px(g, -1, fy + 1, 2, 6, p.trimDark);
      break;
    case "bracket":
      for (const x of [-8, 7]) {
        px(g, x, fy + 2, 1, 4, p.trim);
        px(g, x === -8 ? x : x - 1, fy + 1, 2, 1, p.trim);
        px(g, x === -8 ? x : x - 1, fy + 6, 2, 1, p.trim);
      }
      pair(2, 2, 2);
      break;
    case "equalizer":
      for (const [x, high] of [[-6, 2], [-3, 4], [1, 3], [4, 2]]) px(eyes, x, 2 - high, 2, high, p.eye);
      break;
    case "angled":
      px(eyes, -7, -2, 3, 2, p.eye); px(eyes, -4, -1, 2, 2, p.eye);
      px(eyes, 4, -2, 3, 2, p.eye); px(eyes, 2, -1, 2, 2, p.eye);
      break;
    case "linked-dots": case "soft":
      pair(3, 3, 3);
      if (c.visor === "linked-dots") px(g, -3, fy + 4, 6, 1, p.trimDark);
      else px(g, -2, fy + 7, 4, 1, p.eye, 0.7);
      break;
    case "panels": case "square-eyes": case "monitor-face":
      pair(4, 3, 2);
      if (c.visor === "monitor-face") px(g, -2, fy + 7, 4, 1, p.trim);
      break;
    case "lock":
      pair(2, 2, 4);
      px(g, -1, fy + 5, 2, 3, p.trim);
      break;
    case "inspection":
      pair(3, 2, 3);
      px(g, 6, fy + 1, 2, 6, p.trimDark);
      break;
    case "split":
      pair(); px(g, -1, fy + 1, 2, 6, p.trimDark); break;
    case "narrow": pair(3, 1, 2); break;
    case "level": pair(4, 1, 2); break;
    case "dial":
      pair(2, 2, 3);
      px(g, -3, fy + 7, 6, 1, p.trim);
      break;
    case "display":
      pair(3, 2, 3); px(g, -1, fy + 1, 1, 1, p.trim); break;
    case "wide-cyan": pair(4, 2, 3); break;
  }
}

/** An individually authored piece of kit for every cast member. */
function equipment(g: Graphics, c: Character) {
  const p = c.palette;
  const panel = (w = 16, h = 11, fill = p.gear) => {
    box(g, -Math.floor(w / 2), -Math.floor(h / 2), w, h, fill, INK);
  };
  const paper = (x: number, y: number, w = 7, h = 7) => {
    box(g, x, y, w, h, "#efe7ce");
    px(g, x + 2, y + 2, w - 4, 1, p.trimDark);
    if (h > 6) px(g, x + 2, y + 4, Math.max(1, w - 5), 1, EDGE);
  };
  switch (c.gear) {
    case "command-tablet":
      panel(18, 12, "#36485c");
      px(g, -6, -3, 11, 6, "#152938");
      box(g, -3, -2, 5, 4, p.trim, p.trimDark);
      px(g, 5, 3, 2, 1, p.eye);
      break;
    case "map-tablet":
      panel(18, 12, "#425536");
      px(g, -6, -3, 12, 6, "#b8cf9e");
      px(g, -4, -3, 1, 6, "#708852"); px(g, -6, -1, 12, 1, "#708852");
      px(g, 2, -2, 2, 2, p.trimDark);
      break;
    case "graph-badge":
      panel(12, 11); px(g, -3, -3, 6, 6, "#233358");
      px(g, -2, -1, 4, 2, p.eye); px(g, -1, -2, 2, 4, p.eye);
      break;
    case "clapper":
      panel(18, 11, "#323942");
      px(g, -9, -6, 18, 3, INK);
      for (const x of [-7, -1, 5]) px(g, x, -5, 3, 2, LIGHT);
      px(g, -5, -1, 10, 1, p.trim); px(g, -5, 2, 6, 1, EDGE);
      break;
    case "proof-tablet":
      panel(16, 12, p.trimDark); paper(-6, -4, 12, 8);
      px(g, 3, 0, 1, 2, p.trimDark); px(g, 4, -1, 2, 1, p.trimDark);
      break;
    case "ticket-tablet":
      panel(17, 11); paper(-6, -4, 12, 8);
      px(g, 2, -2, 1, 5, p.trimDark); px(g, 5, -2, 1, 5, p.trimDark);
      break;
    case "checklist":
      panel(14, 13, "#50645a"); paper(-5, -4, 10, 9);
      px(g, -3, -2, 2, 2, p.trimDark); px(g, -3, 1, 2, 2, p.trimDark);
      break;
    case "tool-belt":
      panel(22, 7, "#453c2e");
      for (const x of [-8, -2, 4]) box(g, x, -3, 5, 7, p.gearDark);
      px(g, -6, -6, 1, 8, p.trim); px(g, 6, -5, 2, 7, EDGE);
      break;
    case "cartridge":
      panel(16, 13, p.trimDark); box(g, -6, -4, 12, 7, p.gear);
      for (const x of [-4, -1, 2]) px(g, x, 3, 1, 2, LIGHT);
      px(g, -3, -2, 6, 1, p.eye);
      break;
    case "radar-pack":
      panel(12, 14, "#435737");
      shell(g, -4, -5, 8, 8, chamfer(8, 2), p.trimDark, "#34482a");
      px(g, -1, -4, 1, 5, p.eye); px(g, -3, -2, 5, 1, p.eye);
      px(g, 1, -10, 1, 5, EDGE); px(g, 0, -11, 3, 2, p.trim);
      break;
    case "satchel":
      px(g, -4, -8, 9, 3, p.gearDark); panel(15, 12);
      box(g, -6, -5, 12, 5, p.gearDark); box(g, -2, -1, 4, 4, "#cfb578");
      px(g, -5, 3, 10, 1, p.gearDark);
      break;
    case "graph-slate":
      panel(15, 13, p.gear); box(g, -5, -4, 10, 8, p.gearDark);
      px(g, -3, -2, 2, 4, p.eye); px(g, 1, -2, 2, 4, p.eye);
      px(g, -1, -1, 2, 2, p.eye);
      break;
    case "stamp":
      box(g, -3, -7, 6, 5, p.gear); box(g, -1, -3, 2, 5, p.gearDark);
      box(g, -6, 1, 12, 5, p.gear); px(g, -5, 5, 10, 1, INK);
      break;
    case "waveform":
      panel(14, 10, p.gearDark);
      for (const [x, high] of [[-4, 2], [-1, 6], [2, 4]]) px(g, x, -Math.floor(high / 2), 2, high, p.trim);
      break;
    case "storyboard":
      panel(20, 11, "#dbc9a7");
      for (const x of [-8, -2, 4]) {
        box(g, x, -3, 5, 6, "#faf0d7", p.gearDark);
        px(g, x + 1, 0, 3, 2, p.trim);
      }
      break;
    case "curve-tablet":
      panel(15, 12, p.gear); px(g, -4, -3, 8, 6, "#112f34");
      px(g, -2, -2, 2, 4, p.trim); px(g, 0, -2, 2, 1, p.trim); px(g, 0, 1, 2, 1, p.trim);
      break;
    case "reel-pack":
      panel(18, 10, p.gearDark);
      for (const x of [-7, 1]) {
        shell(g, x, -3, 7, 7, chamfer(7, 2), EDGE, JOINT);
        px(g, x + 3, -1, 1, 3, INK); px(g, x + 2, 0, 3, 1, INK);
      }
      break;
    case "keyboard":
      panel(20, 8, p.gear);
      for (let x = -8; x <= 6; x += 3) {
        px(g, x, -2, 2, 1, p.trim); px(g, x, 0, 2, 1, EDGE);
      }
      px(g, -4, 2, 8, 1, p.trimDark);
      break;
    case "printer":
      panel(14, 10, p.gear); paper(-4, -8, 8, 7);
      px(g, -5, -1, 10, 2, p.gearDark); px(g, 4, 2, 1, 1, p.trim);
      break;
    case "scanner":
      panel(12, 10, p.gearDark); box(g, -4, -3, 8, 4, "#183831");
      px(g, -3, -1, 6, 1, p.eye); px(g, -2, 3, 4, 1, EDGE);
      break;
    case "id-reader":
      panel(11, 14, p.gearDark); paper(-3, -5, 6, 8);
      px(g, -1, -3, 2, 2, p.trim); px(g, -2, 4, 4, 1, p.eye);
      break;
    case "parcel":
      panel(20, 14, p.gear); px(g, -2, -6, 4, 12, "#d5b981");
      px(g, -9, -3, 18, 1, p.gearDark); paper(3, 0, 5, 5);
      break;
    case "notebook":
      panel(13, 15, "#efe6cf"); px(g, -5, -6, 2, 12, p.trim);
      for (const y of [-4, -1, 2]) px(g, -1, y, 5, 1, EDGE);
      break;
    case "node-pattern":
      panel(15, 11, p.gearDark);
      px(g, -4, -1, 9, 1, p.gear); px(g, 0, -3, 1, 6, p.gear);
      for (const [x, y] of [[-5, -2], [-1, -4], [3, -2], [-1, 2]]) box(g, x, y, 3, 3, p.eye, p.gear);
      break;
    case "wrench":
      px(g, -1, -4, 3, 11, INK); px(g, 0, -3, 1, 9, EDGE);
      px(g, -4, -8, 3, 5, INK); px(g, 2, -8, 3, 5, INK); px(g, -3, -4, 7, 3, INK);
      px(g, -3, -7, 1, 4, LIGHT); px(g, 3, -7, 1, 4, EDGE); px(g, -2, -3, 5, 1, EDGE);
      break;
  }
}

export type RobotPosture = "stand" | "desk" | "rest";

export interface StudioRobot {
  container: Container;
  animate: (pose: Pose, timeMs: number, reduce: boolean, dir?: Dir, posture?: RobotPosture) => void;
}

/** Feet are anchored at 0,0. Create once, then animate from the office's actual reported pose. */
export function createRobot(c: Character): StudioRobot {
  const p = c.palette;
  const container = new Container();
  container.label = `robot-${c.id}`;
  const shadow = new Graphics();
  px(shadow, -15, -1, 30, 4, INK, 0.2);
  px(shadow, -11, -2, 22, 6, INK, 0.14);
  px(shadow, -7, -3, 14, 7, INK, 0.08);
  container.addChild(shadow);
  const rig = new Container();
  container.addChild(rig);
  const large = c.rank === "director" ? 2 : c.rank === "manager" ? 1 : 0;
  const hw = (c.head === "wide" ? 30 : c.head === "oval" || c.head === "slim-trapezoid" ? 22 : 26) + large * 2;
  const hh = (c.head === "wide" || c.head === "beacon" ? 16 : 19) + large;
  const hy = -49 - large * 4;
  const by = -28 - large * 3;
  const bw = (c.body === "slim" ? 18 : c.body === "stocky" || c.body === "cart" ? 25 : 21) + large * 2;
  const bh = 17 + large * 3;
  const bx = -Math.floor(bw / 2);
  const seatedHeight = 12 + large;
  const seatedY = -9 - seatedHeight;
  const seatedHeadY = seatedY - 2 - hh;
  const head = new Container();
  const eyes = new Graphics();
  const legLeft = new Container(), legRight = new Container();
  const arms = [new Container(), new Container()];
  const standingLegs: Graphics[] = [], seatedLegs: Graphics[] = [];
  const standingArms: Graphics[] = [], deskArms: Graphics[] = [], restingArms: Graphics[] = [];
  const carryingArms: Graphics[] = [];
  for (const [i, leg] of [legLeft, legRight].entries()) {
    const g = new Graphics();
    const x = i === 0 ? -8 : 3;
    if (c.base === "wheels") {
      box(g, x - 1, -8, 8, 8, JOINT);
      px(g, x + 1, -7, 3, 5, INK);
      px(g, x + 2, -6, 1, 2, EDGE);
    } else {
      box(g, x + 1, -12, 5, 9, p.shade);
      px(g, x + 2, -10, 3, 2, JOINT);
      box(g, x - 1, -5, 9, 5, p.trimDark);
      px(g, x, -4, 5, 1, p.trim);
    }
    const bent = new Graphics();
    if (c.base === "wheels") {
      box(bent, x + 1, -16, 5, 9, p.shade);
      box(bent, x - 1, -8, 8, 8, JOINT);
      px(bent, x + 1, -7, 3, 5, INK);
      px(bent, x + 2, -6, 1, 2, EDGE);
    } else {
      // Horizontal thighs, visible knee joints and short shins give the feet a seated stance.
      box(bent, x + 1, -16, 5, 9, p.shade);
      box(bent, i === 0 ? -11 : 2, -10, 10, 5, p.shade);
      box(bent, i === 0 ? -13 : 8, -7, 6, 5, JOINT);
      px(bent, i === 0 ? -11 : 10, -6, 2, 2, EDGE);
      box(bent, i === 0 ? -13 : 8, -4, 5, 4, p.shade);
      box(bent, i === 0 ? -15 : 7, -3, 10, 3, p.trimDark);
      px(bent, i === 0 ? -14 : 8, -2, 6, 1, p.trim);
    }
    bent.visible = false;
    standingLegs.push(g);
    seatedLegs.push(bent);
    leg.addChild(g, bent);
    rig.addChild(leg);
  }
  for (let i = 0; i < 2; i++) {
    const g = new Graphics(), x = i === 0 ? bx - 5 : bx + bw - 1;
    box(g, x, by + 3, 6, 6, p.trimDark);
    box(g, x + (i === 0 ? 0 : 1), by + 8, 5, 8, p.shade);
    box(g, x - (i === 0 ? 1 : 0), by + 13, 6, 5, p.shell);
    px(g, x + (i === 0 ? 1 : 2), by + 5, 2, 1, p.trim);
    const deskHand = new Graphics();
    const sx = i === 0 ? bx - 4 : bx + bw - 1;
    box(deskHand, sx, seatedY - 5, 5, 5, p.trimDark);
    box(deskHand, sx, -24, 5, seatedY + 35, p.shade);
    // At the office's 0.8 scale these palms reach over the foreground desktop at feet -21.
    box(deskHand, i === 0 ? sx + 2 : 4, -27, Math.max(6, Math.abs(sx) - 2), 5, p.shade);
    box(deskHand, i === 0 ? -7 : 2, -29, 6, 5, p.shell);
    px(deskHand, i === 0 ? -6 : 3, -28, 3, 1, LIGHT, 0.65);
    const relaxed = new Graphics();
    box(relaxed, sx, seatedY + 3, 5, 5, p.trimDark);
    box(relaxed, sx, seatedY + 7, 5, 6, p.shade);
    box(relaxed, i === 0 ? sx + 2 : 3, -11, Math.max(6, Math.abs(sx) - 1), 4, p.shade);
    box(relaxed, i === 0 ? -7 : 2, -12, 6, 4, p.shell);
    const documentHand = new Graphics();
    box(documentHand, x, by + 3, 6, 6, p.trimDark);
    box(documentHand, x + (i === 0 ? 0 : 1), by + 8, 5, 5, p.shade);
    box(documentHand, i === 0 ? bx - 3 : 3, by + 11, Math.max(6, Math.abs(bx) - 1), 4, p.shade);
    box(documentHand, i === 0 ? -8 : 2, by + 10, 6, 5, p.shell);
    deskHand.visible = false;
    relaxed.visible = false;
    documentHand.visible = false;
    standingArms.push(g);
    deskArms.push(deskHand);
    restingArms.push(relaxed);
    carryingArms.push(documentHand);
    arms[i].addChild(g, deskHand, relaxed, documentHand);
    rig.addChild(arms[i]);
  }
  const drawBody = (g: Graphics, y: number, height: number) => {
    const profile = c.body === "shield" ? (r: number) => r < 4 ? Math.max(0, 2 - r) : Math.floor((r - 4) / 4)
      : c.body === "pear" ? (r: number) => r < 6 ? Math.max(0, 4 - r) : r > height - 3 ? r - (height - 3) : 0
        : c.body === "round" ? oval(bw, height) : chamfer(height, 2);
    shell(g, bx, y, bw, height, profile, p.shell, p.shade);
    px(g, bx + 3, y + 3, bw - 6, 3, p.trim);
    px(g, bx + 4, y + 3, bw - 10, 1, LIGHT, 0.4);
    const badgeY = y + Math.min(8, height - 5);
    box(g, -4, badgeY, 9, 4, p.trimDark);
    px(g, -2, badgeY + 1, 5, 1, p.trim);
    px(g, bx + 3, y + height - 4, 3, 1, JOINT, 0.6);
    px(g, bx + bw - 6, y + height - 4, 3, 1, JOINT, 0.6);
    if (c.rank !== "worker") {
      for (const x of [bx + 1, bx + bw - 5]) box(g, x, y + 1, 4, 3, p.trim);
      px(g, -1, y + 7, 2, 2, c.rank === "director" ? "#ffe295" : LIGHT);
    }
    if (c.body === "jacket") {
      px(g, -1, y + 5, 2, height - 8, p.trimDark);
      px(g, bx + 4, y + 7, 3, 2, p.trim);
      px(g, bx + bw - 7, y + 7, 3, 2, p.trim);
    }
  };
  const body = new Graphics(), seatedBody = new Graphics();
  drawBody(body, by, bh);
  drawBody(seatedBody, seatedY, seatedHeight);
  seatedBody.visible = false;
  rig.addChild(body, seatedBody);
  const neck = new Graphics();
  box(neck, -4, by - 5, 8, 6, JOINT);
  px(neck, -3, by - 4, 5, 1, EDGE);
  rig.addChild(neck);
  const skull = new Graphics();
  shell(skull, -hw / 2, hy, hw, hh, headProfile(c, hw, hh), p.shell, p.shade);
  px(skull, -hw / 2 + 5, hy + hh - 3, hw - 10, 1, p.trimDark);
  px(skull, -hw / 2 + 5, hy + hh - 4, 3, 1, p.trim);
  for (const x of [-hw / 2 + 2, hw / 2 - 3]) px(skull, x, hy + hh - 5, 1, 1, JOINT);
  top(skull, c, hy, hw);
  const visor = new Graphics();
  face(visor, eyes, c, hy, hw);
  const back = new Graphics();
  box(back, -6, hy + 6, 12, 8, p.shade);
  for (const x of [-3, 0, 3]) px(back, x, hy + 8, 1, 4, JOINT);
  back.visible = false;
  head.addChild(skull, visor, eyes, back);
  rig.addChild(head);
  const gear = new Container();
  const kit = new Graphics();
  equipment(kit, c);
  gear.addChild(kit);
  const gearX = c.hand === "left" ? -12 : c.hand === "right" ? 12 : 0;
  const gearY = by + 16;
  gear.position.set(gearX, gearY);
  rig.addChild(gear);
  const report = new Graphics();
  box(report, -7, -7, 14, 13, "#efe7cf");
  px(report, -4, -4, 8, 2, p.trim);
  px(report, -4, 0, 6, 1, EDGE);
  px(report, -4, 2, 8, 1, EDGE);
  report.position.y = gearY;
  report.visible = false;
  rig.addChild(report);
  // Palms sit over the document or keyboard rather than disappearing behind the torso.
  rig.addChild(arms[0], arms[1]);
  const incident = new Graphics();
  box(incident, -2, hy + hh - 1, 5, 3, "#ff687c");
  incident.visible = false;
  head.addChild(incident);
  // A recorded go decision gets a visible reaction even when motion is reduced.
  const approval = new Graphics();
  const ay = hy + hh - 3;
  box(approval, 7, ay, 12, 10, "#24553f", INK, "#80c797");
  px(approval, 9, ay + 9, 3, 3, INK);
  px(approval, 10, ay + 9, 1, 2, "#24553f");
  px(approval, 10, ay + 4, 2, 2, "#a8f5bc");
  px(approval, 12, ay + 5, 2, 2, "#a8f5bc");
  px(approval, 14, ay + 3, 2, 3, "#a8f5bc");
  px(approval, 16, ay + 2, 1, 2, "#a8f5bc");
  approval.visible = false;
  rig.addChild(approval);
  const eyesY = eyes.position.y;
  const phaseOffset = Array.from(c.id).reduce((sum, letter) => sum + letter.charCodeAt(0), 0) * 29;

  function animate(pose: Pose, timeMs: number, reduce: boolean, dir: Dir = "down",
    posture: RobotPosture = "stand") {
    const stopped = pose === "paused" || pose === "unavailable";
    const still = reduce || stopped;
    const time = still ? 0 : timeMs + phaseOffset;
    const walking = pose === "walk" || pose === "carry";
    const working = pose === "work" || pose === "review" || pose === "retry";
    const seated = posture !== "stand";
    const resting = posture === "rest";
    const holding = pose === "carry" || pose === "review";
    const walkMotion = walking && !still && !seated;
    const side = dir === "left" ? -1 : dir === "right" ? 1 : 0;
    const frame = Math.floor(time / 110) % 8;
    const step = [0, 1, 2, 1, 0, -1, -2, -1][frame];
    const beat = Math.floor(time / Math.max(120, c.workMs || 350)) % 4;
    body.visible = !seated;
    seatedBody.visible = seated;
    // Desk chairs support an upright torso; lounge seats let the same robot settle lower and relax.
    seatedBody.position.y = resting ? 1 : -7;
    neck.position.y = seated ? seatedY - by + (resting ? 1 : -7) : 0;
    for (let i = 0; i < 2; i++) {
      standingLegs[i].visible = !seated;
      seatedLegs[i].visible = seated;
      standingArms[i].visible = !seated && !holding;
      carryingArms[i].visible = !seated && holding;
      deskArms[i].visible = seated && !resting;
      restingArms[i].visible = resting;
    }
    rig.position.set(0, walkMotion ? [0, -1, -1, 0, 0, -1, -1, 0][frame] : 0);
    legLeft.position.set(walkMotion ? step : resting ? -1 : 0, walkMotion && step > 0 ? -1 : 0);
    legRight.position.set(walkMotion ? -step : resting ? 1 : 0, walkMotion && step < 0 ? -1 : 0);
    head.position.set(resting ? 1 : 0, (seated ? seatedHeadY - hy + (resting ? 1 : -9) : 0)
      + (working && !still && !resting && beat === 1 ? -1 : 0));
    arms[0].position.set(holding && !seated ? side * 3 : 0,
      resting ? 1 : walkMotion && !holding ? -Math.sign(step) : 0);
    arms[1].position.set(holding && !seated ? side * 3 : 0,
      resting ? 1 : walkMotion && !holding ? Math.sign(step) : 0);
    gear.position.set(gearX, gearY);
    gear.visible = !seated && !holding;
    report.visible = holding;
    report.position.set(holding && !seated ? side * 3 : 0, seated ? resting ? -11 : -25 : gearY - 4);
    if (working && !still && !resting) {
      const tapping = c.work === "type" || c.work === "proofread" || c.work === "draft" || c.work === "pages";
      const scanning = c.work === "sweep" || c.work === "scan" || c.work === "verify";
      const down = c.work === "weigh" || c.work === "repair";
      arms[0].position.y = tapping || seated ? (beat % 2 ? -1 : 0) : beat === 1 ? -1 : 0;
      arms[1].position.y = tapping || seated ? (beat % 2 ? 0 : -1) : beat === 2 ? -2 : 0;
      gear.position.x = gearX + (scanning ? [-1, 0, 1, 0][beat] : 0);
      gear.position.y = gearY + (down ? [0, -2, 1, 0][beat] : beat === 2 ? -1 : 0);
    }
    approval.visible = pose === "approved";
    approval.position.copyFrom(head.position);
    if (pose === "approved") {
      arms[1].position.y = -4;
      if (seated) arms[1].position.x = 8;
      if (c.hand === "right") gear.position.y = gearY - 4;
    }
    // A short eye blink is an expression, never a representation of completed work.
    const blinking = !still && pose !== "error" && time % 5300 > 5140;
    visor.visible = dir !== "up";
    eyes.visible = dir !== "up";
    back.visible = dir === "up";
    visor.position.x = side;
    eyes.position.x = side * 2;
    eyes.scale.y = blinking ? 0 : 1;
    eyes.position.y = eyesY + (posture === "desk" && working ? 1 : 0);
    eyes.alpha = pose === "unavailable" ? 0.25 : pose === "paused" ? 0.55 : 1;
    incident.visible = pose === "error" || pose === "rework";
    incident.alpha = pose === "error" && !still ? (Math.floor(time / 650) % 2 ? 0.6 : 1) : 1;
    rig.alpha = pose === "unavailable" ? 0.58 : 1;
    shadow.alpha = walkMotion && frame % 4 === 1 ? 0.8 : 1;
  }
  animate("idle", 0, true);
  return { container, animate };
}
