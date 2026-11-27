import { OrbitPose, TILT } from "./blackHoleOrbit";

/**
 * The ship in front of the camera as it orbits the black hole (blackHoleOrbit.ts): Landry's pixel-art ship (2026-11-27:
 * "use this as the tiny ship in the backround"), cut out of its picture by design/space-studio/tools/flyer.py into
 * public/space/flyer-384.png and a half-size copy for small or 1x screens. It flies the way the orbit goes, banks with
 * it, is lit on the side facing the hole's disk, and its engine flame flickers. Drawn on its own canvas over the hole.
 * Still when motion is off: the same picture, no movement.
 */

/** Where the engines start, as a share of the picture's width from the left: left of it is the exhaust flame. */
const FLAME = 0.22;
/** The ship's width, flame included, as a share of the box's height. */
const SIZE = 0.62;
/** From this many canvas pixels wide the full-size copy is drawn; below it the half-size one, which shrinks cleaner. */
const BIG_FROM = 260;

let big: HTMLImageElement | null = null, small: HTMLImageElement | null = null;
let loading: Promise<void> | null = null;

function picture(name: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Could not load ${name}`));
    img.src = `/space/${name}`;
  });
}

/** Loads the ship's two pictures once (again after a failed try); resolves when they can be drawn. */
export function loadShip(): Promise<void> {
  loading ||= Promise.all([picture("flyer-384.png"), picture("flyer-192.png")]).then(([b, s]) => {
    big = b;
    small = s;
  }, () => {
    loading = null;
  });
  return loading;
}

/**
 * One picture of the ship on `g` (w × h canvas pixels) for the orbit pose, `t` seconds of flying (for the engine's
 * flicker and the gentle bob; pass null for a still picture). Draws nothing until loadShip() has finished.
 */
export function paintShip(g: CanvasRenderingContext2D, w: number, h: number, pose: OrbitPose, t: number | null) {
  g.clearRect(0, 0, w, h);
  const width = h * SIZE;
  const art = (width >= BIG_FROM ? big : small) || big || small;
  if (!art) return;
  const sw = width, sh = width * art.naturalHeight / art.naturalWidth;
  const split = Math.round(art.naturalWidth * FLAME);
  const engines = -sw / 2 + sw * split / art.naturalWidth;
  const bob = t === null ? 0 : Math.sin(t * 0.9) * h * 0.012;
  g.save();
  g.translate(w * 0.2, h * 0.76 + bob);
  // banks with the orbit, and dips its nose a little as the camera climbs
  g.rotate(-pose.roll * 1.6 + (pose.incl - TILT) * 0.3);
  // the picture is drawn smaller than it is: smoothing keeps its hard pixel edges even instead of dropping pixels
  g.imageSmoothingEnabled = true;
  g.imageSmoothingQuality = "high";
  // the flame, stretched back from the engines: longer and shorter as it flickers, exactly as painted when still
  const flick = t === null ? 0.5 : 0.25 + 0.75 * Math.abs(Math.sin(t * 13.0) * Math.sin(t * 7.3));
  const flame = (engines + sw / 2) * (0.88 + 0.24 * flick);
  g.globalAlpha = t === null ? 1 : 0.8 + 0.2 * flick;
  // reaching one pixel under the hull, so no hairline shows between them
  g.drawImage(art, 0, 0, split, art.naturalHeight, engines - flame + 1, -sh / 2, flame, sh);
  g.globalAlpha = 1;
  g.drawImage(art, split, 0, art.naturalWidth - split, art.naturalHeight, engines, -sh / 2, sw / 2 - engines, sh);
  // the hull's side facing the hole is lit by the disk: brighter when its bright side is towards the ship
  const warm = 0.16 + 0.12 * Math.cos(pose.phi);
  g.globalCompositeOperation = "source-atop";
  const grad = g.createLinearGradient(sw / 2, -sh / 2, engines, sh / 2);
  grad.addColorStop(0, `rgba(255, 200, 120, ${warm.toFixed(2)})`);
  grad.addColorStop(1, "rgba(255, 200, 120, 0)");
  g.fillStyle = grad;
  g.fillRect(engines, -sh / 2, sw / 2 - engines, sh);
  g.restore();
}
