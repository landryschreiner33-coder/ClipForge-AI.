import { OrbitPose } from "./blackHoleOrbit";

/**
 * The ship in front of the camera as it orbits the black hole (blackHoleOrbit.ts): chunky pixel art like the app's
 * gold robot icon, flying the way the orbit goes, banking with it, lit on the side facing the hole's disk, with dust
 * streaming past. Drawn on its own canvas over the hole. Still when motion is off: the same picture, no movement.
 */

// . nothing  H hull shade  h hull  l hull lit edge  g gold  w window  W window shine  e engine  f fin
const SHIP = [
  "........ff..............",
  ".......fffg.............",
  ".....lllllllllll........",
  "e..lHhhhhhhhhhhhhl......",
  "eelhhhhhhgggggghhhwww...",
  "eeHhhhhhhhhhhhhhhhwWwww.",
  "eeHHhhhhhhhhhhhhhhhhhhhl",
  "e..HHHHHHHHHHHHHHHHHHH..",
  ".....HHHHgggHHHHHH......",
  "........ff..............",
  ".......fff..............",
];
const COLOURS: Record<string, string> = {
  H: "#3c4f78", h: "#8fa6cf", l: "#d9e6ff", g: "#f2c14e", w: "#5fd3ff", W: "#e8fbff", e: "#56627d", f: "#c99a2e",
};

let sprite: HTMLCanvasElement | null = null;
function shipSprite(): HTMLCanvasElement {
  if (sprite) return sprite;
  const c = document.createElement("canvas");
  c.width = SHIP[0].length;
  c.height = SHIP.length;
  const g = c.getContext("2d");
  if (g) {
    SHIP.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === ".") return;
      g.fillStyle = COLOURS[ch];
      g.fillRect(x, y, 1, 1);
    }));
  }
  return (sprite = c);
}

/** Dust in front of the ship: fixed points that the orbit carries past. */
const DUST = Array.from({ length: 18 }, (_, i) => {
  const r = (n: number) => ((Math.sin(i * 12.9898 + n * 78.233) * 43758.5453) % 1 + 1) % 1;
  return { x: r(1), y: 0.15 + r(2) * 0.8, depth: 0.3 + r(3) * 0.7, size: r(4) };
});

/**
 * One picture of the ship and dust on `g` (w × h canvas pixels) for the orbit pose, `t` seconds of flying (for the
 * engine's flicker and the gentle bob; pass null for a still picture).
 */
export function paintShip(g: CanvasRenderingContext2D, w: number, h: number, pose: OrbitPose, t: number | null) {
  g.clearRect(0, 0, w, h);
  const s = Math.max(2, Math.round(h / 62));
  const along = pose.phi / (Math.PI * 2);
  // dust: drifts left as the ship flies right, the nearer specks faster and bigger
  for (const d of DUST) {
    const x = ((d.x - along * (1.5 + d.depth * 3)) % 1 + 1) % 1;
    const size = Math.max(1, Math.round(s * (0.25 + d.depth * 0.45 + d.size * 0.2)));
    g.fillStyle = `rgba(200, 225, 255, ${(0.18 + d.depth * 0.35).toFixed(2)})`;
    g.fillRect(Math.round(x * w), Math.round(d.y * h), size, size);
  }
  const art = shipSprite();
  const sw = art.width * s, sh = art.height * s;
  const bob = t === null ? 0 : Math.sin(t * 0.9) * h * 0.012;
  const cx = w * 0.19, cy = h * 0.74 + bob;
  g.save();
  g.translate(cx, cy);
  // banks with the orbit, and dips its nose a little as the camera climbs
  g.rotate(-pose.roll * 1.6 + (pose.incl - 0.13) * 0.3);
  g.imageSmoothingEnabled = false;
  // the engine: a flame of square pixels that flickers
  const flick = t === null ? 0.6 : 0.55 + 0.45 * Math.abs(Math.sin(t * 13.0) * Math.sin(t * 7.3));
  const flame = Math.round((3 + flick * 4) * s);
  for (let k = 0; k < flame; k += s) {
    const fade = 1 - k / flame;
    const [r, gr] = [Math.round(150 + 105 * fade), Math.round(205 + 50 * fade)];
    g.fillStyle = `rgba(${r}, ${gr}, 255, ${(0.85 * fade).toFixed(2)})`;
    const half = Math.max(1, Math.round((1 + fade * 1.2) * s));
    g.fillRect(-sw / 2 - s - k, -sh / 2 + 5 * s - half / 2 + s / 2, s, half);
  }
  g.drawImage(art, -sw / 2, -sh / 2, sw, sh);
  // the side facing the hole is lit by the disk: brighter when its bright side is towards the ship
  const warm = 0.18 + 0.14 * Math.cos(pose.phi);
  g.globalCompositeOperation = "source-atop";
  const grad = g.createLinearGradient(sw / 2, -sh / 2, -sw / 2, sh / 2);
  grad.addColorStop(0, `rgba(255, 200, 120, ${warm.toFixed(2)})`);
  grad.addColorStop(1, "rgba(255, 200, 120, 0)");
  g.fillStyle = grad;
  g.fillRect(-sw / 2, -sh / 2, sw, sh);
  g.restore();
}
