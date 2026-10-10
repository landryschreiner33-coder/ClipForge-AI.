/** A decorative neural sculpture. Its brighter activity is driven by genuine Brain work, not timers. */
import { Container, Graphics } from "pixi.js";

export type BrainMode = "standby" | "active" | "paused" | "offline";
export const BRAIN_CORE_BOUNDS = { x: -62, y: -124, width: 124, height: 126 } as const;

type Point = readonly [number, number];
type Orbit = { rx: number; ry: number; tilt: number; color: string; phase: number };
const CYAN = "#9ce8df", VIOLET = "#cbb4f3", GOLD = "#e5c591", INK = "#22283f";
const ORBITS: Orbit[] = [
  { rx: 57, ry: 13, tilt: -0.48, color: CYAN, phase: 0.35 },
  { rx: 55, ry: 16, tilt: 0.48, color: VIOLET, phase: 2.8 },
  { rx: 59, ry: 10, tilt: 0, color: GOLD, phase: 4.25 },
];
const HEMISPHERE: Point[] = [
  [-2, -22], [-10, -22], [-10, -26], [-20, -26], [-20, -23], [-26, -23], [-26, -18],
  [-31, -18], [-31, -11], [-35, -11], [-35, 3], [-32, 3], [-32, 11], [-27, 11],
  [-27, 17], [-20, 17], [-20, 21], [-12, 21], [-12, 18], [-5, 18], [-5, 14], [-2, 14],
];
const CIRCUITS: Point[][] = [
  [[-7, -17], [-14, -17], [-14, -21], [-20, -21]],
  [[-27, -14], [-21, -14], [-21, -7], [-12, -7], [-12, -13], [-6, -13]],
  [[-30, -6], [-25, -6], [-25, 1], [-17, 1], [-17, -2], [-9, -2]],
  [[-29, 7], [-22, 7], [-22, 12], [-14, 12], [-14, 7], [-7, 7]],
  [[-18, 16], [-10, 16], [-10, 11], [-5, 11]],
  [[7, -17], [14, -17], [14, -21], [21, -21]],
  [[28, -14], [21, -14], [21, -8], [13, -8], [13, -13], [6, -13]],
  [[30, -5], [25, -5], [25, 1], [17, 1], [17, -2], [9, -2]],
  [[29, 7], [22, 7], [22, 12], [14, 12], [14, 7], [7, 7]],
  [[18, 16], [10, 16], [10, 11], [5, 11]],
];
const NEURONS: Point[] = [
  [-20, -21], [-27, -14], [-12, -7], [-30, -6], [-17, 1], [-29, 7], [-14, 12], [-10, 16],
  [21, -21], [28, -14], [13, -8], [30, -5], [17, 1], [29, 7], [14, 12], [10, 16],
];

const rect = (g: Graphics, x: number, y: number, w: number, h: number, color: string, alpha = 1) =>
  g.rect(Math.round(x), Math.round(y), w, h).fill({ color, alpha });
const polygon = (g: Graphics, points: Point[], color: string, alpha = 1) =>
  g.poly(points.flatMap(([x, y]) => [x, y])).fill({ color, alpha });
function trace(g: Graphics, points: Point[], color: string, width: number, alpha: number) {
  g.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) g.lineTo(points[i][0], points[i][1]);
  g.stroke({ color, width, alpha, cap: "square", join: "miter" });
}
const CIRCUIT_ROUTES = CIRCUITS.map(points => {
  const lengths = points.slice(1).map(([x, y], i) => Math.abs(x - points[i][0]) + Math.abs(y - points[i][1]));
  return { points, lengths, length: lengths.reduce((sum, n) => sum + n, 0) };
});
function circuitPoint(route: typeof CIRCUIT_ROUTES[number], phase: number): Point {
  let distance = ((phase % 1 + 1) % 1) * route.length;
  for (let i = 0; i < route.lengths.length; i++) {
    const length = route.lengths[i];
    if (distance <= length) {
      const [sx, sy] = route.points[i], [ex, ey] = route.points[i + 1];
      return [Math.round(sx + (ex - sx) * distance / length), Math.round(sy + (ey - sy) * distance / length)];
    }
    distance -= length;
  }
  return route.points[route.points.length - 1];
}
function orbitPoint(orbit: Orbit, angle: number): Point {
  const x = Math.cos(angle) * orbit.rx, y = Math.sin(angle) * orbit.ry;
  return [Math.round(x * Math.cos(orbit.tilt) - y * Math.sin(orbit.tilt)),
    Math.round(x * Math.sin(orbit.tilt) + y * Math.cos(orbit.tilt))];
}
function orbitArc(g: Graphics, orbit: Orbit, front: boolean) {
  const points: Point[] = [];
  const start = front ? 0 : Math.PI;
  for (let i = 0; i <= 48; i++) points.push(orbitPoint(orbit, start + i * Math.PI / 48));
  trace(g, points, orbit.color, 3, front ? 0.065 : 0.035);
  trace(g, points, orbit.color, 1, front ? 0.42 : 0.23);
}

/** Origin is the pedestal base. Keep its bounds clear of room labels and the robots' desks. */
export function createBrainCore() {
  const container = new Container();
  container.label = "Brain neural sculpture";
  container.eventMode = "none";
  const pedestal = new Graphics();
  const emitter = new Graphics();
  const shadow = new Graphics();
  const orbitBack = new Container();
  const neural = new Container();
  const orbitFront = new Container();
  const halo = new Graphics();
  const body = new Graphics();
  const neuralLight = new Graphics();
  const energy = new Graphics();
  const scan = new Graphics();
  const scanMask = new Graphics();
  const nodes = new Graphics();
  const backLights = new Graphics(), frontLights = new Graphics();
  const ringBack = new Graphics(), ringFront = new Graphics();
  const orbital = new Container();

  // Layered bevels and inset light strips give the brain a physical stand, rather than a floating UI icon.
  rect(shadow, -33, -3, 66, 5, "#101c2c", 0.24);
  rect(shadow, -26, -5, 52, 4, "#101c2c", 0.25);
  rect(pedestal, -30, -11, 60, 11, INK);
  rect(pedestal, -28, -9, 56, 7, "#5b6379");
  rect(pedestal, -24, -18, 48, 10, "#303b51");
  rect(pedestal, -22, -17, 44, 4, "#707d92");
  rect(pedestal, -18, -28, 36, 13, "#36445c");
  rect(pedestal, -16, -27, 32, 3, "#9b9ab2");
  rect(pedestal, -15, -24, 4, 8, "#55657f");
  rect(pedestal, 11, -24, 4, 8, "#27344b");
  rect(pedestal, -22, -29, 44, 4, "#243149");
  rect(pedestal, -20, -29, 40, 2, "#b0b4c4");
  rect(pedestal, -10, -11, 20, 4, "#202e43");
  rect(pedestal, -7, -10, 14, 1, GOLD, 0.72);
  for (const x of [-23, 20]) {
    rect(pedestal, x, -7, 3, 2, "#8a97ad");
    rect(pedestal, x, -3, 3, 1, "#3c475e");
  }

  // Three overlapping, translucent stepped shapes create a soft glow without expensive blur filters.
  for (const scale of [1.38, 1.21, 1.09]) {
    const left: Point[] = HEMISPHERE.map(([x, y]) => [Math.round(x * scale), Math.round(y * scale)]);
    polygon(halo, left, VIOLET, 0.035);
    polygon(halo, left.map(([x, y]) => [-x, y]), CYAN, 0.03);
  }
  polygon(body, HEMISPHERE, "#3b4265");
  polygon(body, HEMISPHERE.map(([x, y]) => [-x, y]), "#3b4265");
  const inset = HEMISPHERE.map(([x, y]): Point => [x < -4 ? x + 2 : x, y > 0 ? y - 2 : y + 2]);
  polygon(body, inset, "#9f88ca");
  polygon(body, inset.map(([x, y]) => [-x, y]), "#a6a6cd");
  // The top planes are cool and bright; lower steps receive a darker reflected lavender.
  rect(body, -20, -24, 10, 2, "#e2cff9", 0.86);
  rect(body, -26, -21, 6, 2, "#d9c4f1", 0.82);
  rect(body, -31, -16, 5, 2, "#d8c6ed", 0.75);
  rect(body, 10, -24, 10, 2, "#e4e7f9", 0.9);
  rect(body, 20, -21, 6, 2, "#d1dfed", 0.82);
  rect(body, 26, -16, 5, 2, "#d0dded", 0.75);
  rect(body, -26, 14, 7, 2, "#6c5e98", 0.8);
  rect(body, -19, 18, 7, 1, "#6c5e98", 0.8);
  rect(body, 19, 14, 7, 2, "#7378a5", 0.8);
  rect(body, 12, 18, 7, 1, "#7378a5", 0.8);
  rect(body, -2, -20, 4, 33, "#40415f");
  rect(body, 0, -18, 1, 29, "#eee4fb", 0.75);
  for (const points of CIRCUITS) {
    trace(body, points, "#545477", 3, 0.87);
    trace(neuralLight, points, CYAN, 1, 0.54);
  }
  polygon(scanMask, HEMISPHERE, "#ffffff");
  polygon(scanMask, HEMISPHERE.map(([x, y]) => [-x, y]), "#ffffff");
  scan.mask = scanMask;
  neural.addChild(halo, body, neuralLight, scan, energy, nodes, scanMask);
  for (const orbit of ORBITS) {
    orbitArc(ringBack, orbit, false);
    orbitArc(ringFront, orbit, true);
  }
  orbitBack.addChild(ringBack, backLights);
  orbitFront.addChild(ringFront, frontLights);
  orbital.addChild(orbitBack, neural, orbitFront);
  orbital.position.y = -82;
  container.addChild(shadow, emitter, pedestal, orbital);

  let lastTime: number | undefined;
  let clock = 0;
  let lastFrame = -1;
  let lastMode: BrainMode | undefined;
  let lastStill = false;
  let destroyed = false;

  const update = (timeMs: number, still: boolean, mode: BrainMode) => {
    if (destroyed) return;
    const delta = lastTime === undefined ? 0 : Math.max(0, Math.min(timeMs - lastTime, 80));
    lastTime = timeMs;
    const frozen = still || mode === "paused" || mode === "offline";
    if (!frozen) clock += delta;
    // Thirty visual frames per second suit pixel art and avoid rebuilding geometry on every RAF.
    const frame = Math.floor(clock / 33.333);
    if (frame === lastFrame && mode === lastMode && still === lastStill) return;
    lastFrame = frame; lastMode = mode; lastStill = still;
    const t = frame / 30;
    const active = mode === "active", offline = mode === "offline";
    const pulse = 0.5 + Math.sin(t * (active ? 2.4 : 0.55)) * 0.5;
    const breath = active ? 0.72 + pulse * 0.28 : 0.4 + pulse * 0.1;
    orbital.position.y = -82 + Math.round(Math.sin(t * 0.65) * 1.5);
    body.alpha = offline ? 0.48 : 1;
    halo.alpha = offline ? 0.12 : active ? 1.6 + pulse * 0.4 : 0.7 + pulse * 0.22;
    neuralLight.alpha = offline ? 0.25 : active ? 0.8 + pulse * 0.2 : 0.65;
    ringBack.alpha = offline ? 0.3 : 1;
    ringFront.alpha = offline ? 0.3 : 1;

    emitter.clear();
    // A contained light cone connects the levitating sculpture to the physical emitter below it.
    polygon(emitter, [[-18, -30], [-26, -56], [26, -56], [18, -30]], CYAN,
      offline ? 0.015 : 0.028 + breath * 0.025);
    polygon(emitter, [[-10, -30], [-14, -55], [14, -55], [10, -30]], VIOLET,
      offline ? 0.015 : 0.035 + breath * 0.03);
    rect(emitter, -18, -30, 36, 1, CYAN, offline ? 0.1 : 0.34 + breath * 0.2);
    rect(emitter, -12, -32, 24, 1, VIOLET, offline ? 0.05 : 0.22 + breath * 0.15);
    if (active) for (let i = 0; i < 3; i++) {
      const height = (t * 14 + i * 8) % 24;
      const x = (i - 1) * 9;
      rect(emitter, x - 1, -32 - height, 3, 4, CYAN, .08);
      rect(emitter, x, -32 - height, 1, 2, i === 1 ? GOLD : CYAN, .55);
    }

    scan.clear(); energy.clear();
    if (active) {
      // The scan is confined to the sculpture, and denotes processing rather than measured progress.
      const scanY = -26 + (t * 12) % 48;
      rect(scan, -36, scanY - 6, 72, 7, CYAN, .045);
      rect(scan, -36, scanY - 3, 72, 3, CYAN, .12);
      rect(scan, -36, scanY, 72, 1, "#d8fff4", .6);
      for (let i = 0; i < CIRCUIT_ROUTES.length; i++) {
        const route = CIRCUIT_ROUTES[i], phase = t * .38 + i * .173;
        if ((Math.floor(t * 2) + i) % 5 === 0) trace(energy, route.points, CYAN, 1, .35);
        for (let tail = 3; tail >= 0; tail--) {
          const [x, y] = circuitPoint(route, phase - tail * .055);
          rect(energy, x - 1, y - 1, 3, 3, i % 3 === 0 ? VIOLET : CYAN, .1 - tail * .02);
          rect(energy, x, y, tail ? 1 : 2, tail ? 1 : 2, tail ? CYAN : "#effff6", .8 - tail * .19);
        }
      }
      const bridgeY = -18 + (t * 9) % 30;
      rect(energy, -1, bridgeY - 2, 3, 6, VIOLET, .16);
      rect(energy, 0, bridgeY, 1, 2, "#fff1d4", .9);
    }

    nodes.clear();
    for (let i = 0; i < NEURONS.length; i++) {
      const [x, y] = NEURONS[i];
      const strength = offline ? 0.14 : active ? 0.48 + (Math.sin(t * 2.8 + i * 0.77) + 1) * 0.24
        : 0.3 + (Math.sin(t * 0.5 + i * 0.77) + 1) * 0.08;
      rect(nodes, x - 2, y - 2, 5, 5, CYAN, strength * 0.12);
      rect(nodes, x - 1, y - 1, 3, 3, i % 4 === 0 ? GOLD : CYAN, strength);
      rect(nodes, x, y, 1, 1, "#f3efff", strength);
    }
    backLights.clear(); frontLights.clear();
    for (let i = 0; i < ORBITS.length; i++) {
      const orbit = ORBITS[i];
      const speed = active ? 0.47 : 0.11;
      const count = active ? 3 : 2;
      for (let j = 0; j < count; j++) {
        const angle = (orbit.phase + t * speed * (i === 1 ? -1 : 1) + j * Math.PI * 2 / count)
          % (Math.PI * 2);
        const normalized = angle < 0 ? angle + Math.PI * 2 : angle;
        const [x, y] = orbitPoint(orbit, normalized);
        const layer = normalized < Math.PI ? frontLights : backLights;
        const alpha = offline ? 0.12 : active ? 0.88 : 0.58;
        rect(layer, x - 3, y - 3, 6, 6, orbit.color, alpha * 0.075);
        rect(layer, x - 1, y - 1, 3, 3, orbit.color, alpha);
        rect(layer, x, y, 1, 1, "#f5eddb", alpha);
        if (active) {
          const trail: Point[] = [];
          for (let k = 1; k <= 10; k++) trail.push(orbitPoint(orbit, normalized - k * 0.025));
          trace(layer, trail, orbit.color, 2, 0.065);
          trace(layer, trail, orbit.color, 1, 0.36);
        }
      }
    }
  };
  update(0, false, "standby");
  return { container, update, destroy: () => {
    if (destroyed) return;
    destroyed = true;
    container.destroy({ children: true });
  } };
}
