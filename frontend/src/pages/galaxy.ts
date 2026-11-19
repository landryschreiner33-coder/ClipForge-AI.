/**
 * The spiral galaxy behind the Brain's knowledge map (the space studio, 2026-11-19). It is painted once, face on, from
 * a fixed seed, so every visit shows the same galaxy; the page tilts it and turns it very slowly. It is decoration:
 * the dots, lines and labels drawn over it are the Brain's real records.
 */
let painted: HTMLCanvasElement | null = null;

export const GALAXY_SIZE = 1200;

export function galaxyCanvas(): HTMLCanvasElement {
  if (painted) return painted;
  const size = GALAXY_SIZE, c = size / 2;
  const cv = document.createElement("canvas");
  cv.width = cv.height = size;
  const g = cv.getContext("2d");
  if (!g) return (painted = cv);
  let seed = 20261119;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const gauss = () => (rnd() + rnd() + rnd() - 1.5) / 1.5;

  // the faint halo of the whole disk
  const halo = g.createRadialGradient(c, c, 0, c, c, c);
  halo.addColorStop(0, "rgba(120, 90, 200, 0.30)");
  halo.addColorStop(0.45, "rgba(70, 60, 160, 0.14)");
  halo.addColorStop(1, "rgba(20, 20, 60, 0)");
  g.fillStyle = halo;
  g.fillRect(0, 0, size, size);

  g.globalCompositeOperation = "lighter";
  const ARMS = 2, PITCH = 3.1, INNER = 0.07;
  const along = (arm: number, t: number) => {
    const r = (INNER + t * (0.93 - INNER)) * c;
    const theta = arm * Math.PI + Math.log(r / (INNER * c)) * PITCH / Math.PI * 1.9;
    return { r, theta };
  };
  // nebula clouds along the arms: violet, magenta and blue
  const clouds = ["150, 90, 255", "220, 90, 210", "90, 120, 255", "170, 120, 255"];
  for (let i = 0; i < 260; i++) {
    const arm = i % ARMS, t = Math.pow(rnd(), 0.8);
    const { r, theta } = along(arm, t);
    const a = theta + gauss() * 0.22;
    const x = c + Math.cos(a) * r, y = c + Math.sin(a) * r;
    const rad = (0.035 + rnd() * 0.06) * c * (0.5 + t);
    const cloud = g.createRadialGradient(x, y, 0, x, y, rad);
    cloud.addColorStop(0, `rgba(${clouds[i % clouds.length]}, ${0.10 + rnd() * 0.08})`);
    cloud.addColorStop(1, `rgba(${clouds[i % clouds.length]}, 0)`);
    g.fillStyle = cloud;
    g.fillRect(x - rad, y - rad, rad * 2, rad * 2);
  }
  // stars along the arms, warmer near the centre and bluer outside
  for (let i = 0; i < 14000; i++) {
    const arm = i % ARMS, t = Math.pow(rnd(), 0.7);
    const { r, theta } = along(arm, t);
    const spread = 0.12 + t * 0.32;
    const a = theta + gauss() * spread;
    const rr = r * (1 + gauss() * 0.05);
    const x = c + Math.cos(a) * rr, y = c + Math.sin(a) * rr;
    const warm = t < 0.25 && rnd() < 0.7;
    const pick = rnd();
    const color = warm ? "255, 214, 160" : pick < 0.35 ? "200, 170, 255" : pick < 0.6 ? "255, 150, 230"
      : pick < 0.85 ? "150, 185, 255" : "255, 255, 255";
    const big = rnd() < 0.03;
    g.fillStyle = `rgba(${color}, ${(big ? 0.75 : 0.25 + rnd() * 0.45) * (1 - t * 0.35)})`;
    const s = big ? 2.2 : 0.7 + rnd() * 1.1;
    g.fillRect(x - s / 2, y - s / 2, s, s);
  }
  // scattered stars between the arms
  for (let i = 0; i < 2600; i++) {
    const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd()) * c * 0.92;
    g.fillStyle = `rgba(210, 200, 255, ${0.12 + rnd() * 0.25})`;
    const s = 0.6 + rnd() * 0.9;
    g.fillRect(c + Math.cos(a) * r, c + Math.sin(a) * r, s, s);
  }
  // the bright, warm centre
  const core = g.createRadialGradient(c, c, 0, c, c, c * 0.24);
  core.addColorStop(0, "rgba(255, 240, 215, 0.95)");
  core.addColorStop(0.18, "rgba(255, 200, 140, 0.55)");
  core.addColorStop(0.5, "rgba(230, 130, 150, 0.18)");
  core.addColorStop(1, "rgba(140, 80, 200, 0)");
  g.fillStyle = core;
  g.fillRect(0, 0, size, size);
  return (painted = cv);
}
