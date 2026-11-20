/**
 * The spiral galaxy behind the Brain's knowledge map (the space studio, 2026-11-19). It is painted once, face on, from
 * a fixed seed, so every visit shows the same galaxy; the page tilts it and turns it very slowly. It is decoration:
 * the dots, lines and labels drawn over it are the Brain's real records.
 *
 * Layers, back to front: the disk's glow, a haze of disk stars, gas clouds along two main arms and two fainter ones,
 * the arms' stars, dark dust along each main arm's inner edge, pink and orange star-forming knots, the warm bulge and
 * a few bright stars. About 45 000 small rectangles and 900 soft spots, painted once per visit.
 */
let painted: HTMLCanvasElement | null = null;

export const GALAXY_SIZE = 1400;

export function galaxyCanvas(): HTMLCanvasElement {
  if (painted) return painted;
  const size = GALAXY_SIZE, c = size / 2;
  const cv = document.createElement("canvas");
  cv.width = cv.height = size;
  const g = cv.getContext("2d");
  if (!g) return (painted = cv);
  let seed = 20261119;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const gauss = () => (rnd() + rnd() + rnd() + rnd() - 2) / 1.15;
  const spot = (x: number, y: number, r: number, rgb: string, a: number) => {
    const s = g.createRadialGradient(x, y, 0, x, y, r);
    s.addColorStop(0, `rgba(${rgb}, ${a})`);
    s.addColorStop(1, `rgba(${rgb}, 0)`);
    g.fillStyle = s;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  };
  const dot = (x: number, y: number, s: number, rgb: string, a: number) => {
    g.fillStyle = `rgba(${rgb}, ${a})`;
    g.fillRect(x - s / 2, y - s / 2, s, s);
  };

  // a logarithmic spiral: arms 0 and 1 are the main arms, 0.5 and 1.5 the fainter ones between them
  const INNER = 0.06, WIND = 2.55;
  const along = (arm: number, t: number) => {
    const r = (INNER + t * (0.96 - INNER)) * c;
    return { r, theta: arm * Math.PI + WIND * Math.log(r / (INNER * c)) };
  };
  const at = (r: number, a: number) => ({ x: c + Math.cos(a) * r, y: c + Math.sin(a) * r });

  // the disk's glow
  const halo = g.createRadialGradient(c, c, 0, c, c, c);
  halo.addColorStop(0, "rgba(150, 110, 230, 0.34)");
  halo.addColorStop(0.3, "rgba(105, 80, 200, 0.20)");
  halo.addColorStop(0.65, "rgba(60, 50, 150, 0.08)");
  halo.addColorStop(1, "rgba(20, 20, 60, 0)");
  g.fillStyle = halo;
  g.fillRect(0, 0, size, size);

  g.globalCompositeOperation = "lighter";
  // a haze of stars over the whole disk, thicker towards the middle
  for (let i = 0; i < 9000; i++) {
    const r = Math.min(0.97, -Math.log(1 - rnd() * 0.97) * 0.27) * c, a = rnd() * Math.PI * 2;
    const p = at(r, a);
    dot(p.x, p.y, 0.6 + rnd() * 0.9, rnd() < 0.5 ? "205, 190, 255" : "175, 190, 255", 0.10 + rnd() * 0.22);
  }
  // gas along the arms: violet, magenta and blue
  const gas = ["150, 90, 255", "215, 95, 220", "95, 125, 255", "175, 125, 255", "120, 100, 240"];
  for (let i = 0; i < 520; i++) {
    const main = i % 4 < 3, arm = main ? i % 2 : 0.5 + (i % 2);
    const t = Math.pow(rnd(), 0.85) * (main ? 1 : 0.8);
    const { r, theta } = along(arm, t);
    const p = at(r * (1 + gauss() * 0.04), theta + gauss() * (0.1 + t * 0.12));
    spot(p.x, p.y, (0.03 + rnd() * 0.05) * c * (0.55 + t), gas[i % gas.length], (main ? 0.09 : 0.05) + rnd() * 0.07);
  }
  // the arms' stars, warmer near the middle and bluer outside
  for (let i = 0; i < 28000; i++) {
    const main = i % 5 < 4, arm = main ? i % 2 : 0.5 + (i % 2);
    const t = Math.pow(rnd(), 0.75) * (main ? 1 : 0.85);
    const { r, theta } = along(arm, t);
    const p = at(r * (1 + gauss() * 0.035), theta + gauss() * (0.07 + t * 0.2));
    const warm = t < 0.22 && rnd() < 0.75, pick = rnd();
    const rgb = warm ? "255, 216, 168" : pick < 0.34 ? "205, 175, 255" : pick < 0.55 ? "255, 160, 230"
      : pick < 0.86 ? "160, 190, 255" : "255, 255, 255";
    const big = rnd() < 0.025;
    dot(p.x, p.y, big ? 2.3 : 0.7 + rnd() * 1.1, rgb, (big ? 0.8 : 0.28 + rnd() * 0.5) * (main ? 1 : 0.7) * (1 - t * 0.3));
  }
  // dark dust along the inner edge of each main arm
  g.globalCompositeOperation = "source-over";
  for (let i = 0; i < 360; i++) {
    const arm = i % 2, t = 0.08 + rnd() * 0.72;
    const { r, theta } = along(arm, t);
    const p = at(r * (0.975 + gauss() * 0.012), theta - 0.16 - t * 0.05 + gauss() * 0.03);
    spot(p.x, p.y, (0.012 + rnd() * 0.022) * c * (0.6 + t), "10, 6, 26", 0.22 + rnd() * 0.18);
  }
  g.globalCompositeOperation = "lighter";
  // star-forming knots: pink and orange
  for (let i = 0; i < 110; i++) {
    const arm = i % 2, t = 0.15 + rnd() * 0.75;
    const { r, theta } = along(arm, t);
    const p = at(r * (1 + gauss() * 0.03), theta + gauss() * 0.12);
    const rgb = rnd() < 0.55 ? "255, 120, 205" : "255, 175, 95";
    spot(p.x, p.y, 4 + rnd() * 9, rgb, 0.35 + rnd() * 0.3);
    dot(p.x, p.y, 1.6, "255, 245, 235", 0.85);
  }
  // the warm bulge: a crowd of old stars and a bright middle
  for (let i = 0; i < 4200; i++) {
    const r = Math.abs(gauss()) * 0.085 * c, a = rnd() * Math.PI * 2;
    const p = at(r, a);
    dot(p.x, p.y, 0.7 + rnd() * 1.2, rnd() < 0.7 ? "255, 214, 160" : "255, 238, 214", 0.25 + rnd() * 0.45);
  }
  const core = g.createRadialGradient(c, c, 0, c, c, c * 0.3);
  core.addColorStop(0, "rgba(255, 246, 225, 1)");
  core.addColorStop(0.12, "rgba(255, 222, 165, 0.8)");
  core.addColorStop(0.35, "rgba(250, 165, 120, 0.32)");
  core.addColorStop(0.7, "rgba(200, 110, 170, 0.1)");
  core.addColorStop(1, "rgba(140, 80, 200, 0)");
  g.fillStyle = core;
  g.fillRect(0, 0, size, size);
  // a few bright stars with short spikes
  for (let i = 0; i < 36; i++) {
    const r = Math.sqrt(rnd()) * c * 0.9, a = rnd() * Math.PI * 2;
    const p = at(r, a), len = 4 + rnd() * 6, rgb = rnd() < 0.5 ? "255, 240, 220" : "210, 225, 255";
    spot(p.x, p.y, len, rgb, 0.5);
    dot(p.x, p.y, 2, "255, 255, 255", 0.95);
    g.fillStyle = `rgba(${rgb}, 0.55)`;
    g.fillRect(p.x - len, p.y - 0.5, len * 2, 1);
    g.fillRect(p.x - 0.5, p.y - len, 1, len * 2);
  }
  return (painted = cv);
}
