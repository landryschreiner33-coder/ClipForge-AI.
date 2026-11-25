import { useEffect, useRef, useState } from "react";
import { usePageCovered } from "../covered";
import { useMotion } from "../motion";
import { paintFrame, paintStill } from "./blackHoleArt";
import { HoleRenderer, makeHoleRenderer } from "./blackHoleGl";
import { makeOrbitRenderer, orbitPose } from "./blackHoleOrbit";
import { onPixelRatioChange } from "./pixelRatio";
import { paintShip } from "./shipArt";

/**
 * One clock for every black hole: how far the disk has turned, in seconds of turning. It moves on only while a hole
 * turns, so a hole that held still (or the one on the next page) carries on from the picture last shown. A frame's
 * time is when the frame was due, which can be a moment before the turning started: it counts as no turning yet, so
 * the disk never steps back.
 */
let spun = 0, turning = 0, turnedFrom = 0;
const diskTime = (now: number) => spun + (turning ? Math.max(0, now - turnedFrom) / 1000 : 0);
const startTurning = (now: number) => {
  if (!turning++) turnedFrom = now;
};
const stopTurning = (now: number) => {
  if (turning && !--turning) spun += (now - turnedFrom) / 1000;
};
/** The disk turns slowly: thirty frames a second are plenty. */
const FRAME = 1000 / 30;

/**
 * Whether this computer has just shown that it draws the turning disk too slowly (as one without a graphics chip
 * does): frames more than SLOW_GAP apart, on the middle frame, through two stretches of STRETCH in a row. A gap longer
 * than STALL is the page or the window held up, not slow drawing, and is left out. Every black hole then holds still
 * for a while, so the app itself stays quick, and tries again after 2 minutes, then 4, 8 and so on up to an hour each
 * time it is too slow again: a computer that was only busy for a moment gets the turning disk back.
 */
const SLOW_GAP = 45, STRETCH = 2500, STALL = 1000;
let tooSlow = false, slowTrips = 0, slowTimer = 0;
const slowWatchers = new Set<(slow: boolean) => void>();
function setTooSlow(on: boolean) {
  tooSlow = on;
  for (const tell of slowWatchers) tell(on);
}
function tooSlowNow() {
  slowTrips++;
  setTooSlow(true);
  window.clearTimeout(slowTimer);
  slowTimer = window.setTimeout(() => setTooSlow(false), Math.min(64, 2 ** slowTrips) * 60_000);
}

/**
 * Times the graphics chip's drawing was lost (a driver update or reset, the chip's process restarting): each time the
 * hole starts again on a fresh canvas. After a few, holes keep to the canvas painter for the rest of the visit.
 */
let losses = 0;
const MAX_LOSSES = 3;

/**
 * The orbiting view (blackHoleOrbit.ts) traces every pixel's light and costs the graphics chip far more than the
 * lighter hole. When this computer cannot draw it smoothly (frames SLOW_GAP apart through two STRETCHes), or has no
 * WebGL for it, the big hole is the lighter one for the rest of the visit.
 */
let orbitTooSlow = false;
const orbitWatchers = new Set<(slow: boolean) => void>();
function giveUpOrbit() {
  orbitTooSlow = true;
  for (const tell of orbitWatchers) tell(true);
}

/**
 * The black hole in the studio's sky. The big one is seen from the ship as it orbits the hole (blackHoleOrbit.ts),
 * unless Settings → Appearance asks for the lighter look or the computer cannot draw it smoothly; then, and for the
 * slim one in the masthead, it is the lighter hole: where the browser has WebGL its disk turns (blackHoleGl.ts),
 * otherwise the canvas painter shows the same picture with a few patches of light travelling round the disk
 * (blackHoleArt.ts). It moves only while motion is allowed, Low power is off, the window is shown, the hole is on
 * screen and the computer keeps up; otherwise it is one still picture. It is decoration and says nothing about work.
 */
export function BlackHole({ size = "small", className = "" }: { size?: "small" | "large"; className?: string }) {
  const { spaceLook } = useMotion();
  const [gaveUp, setGaveUp] = useState(orbitTooSlow);
  useEffect(() => {
    orbitWatchers.add(setGaveUp);
    setGaveUp(orbitTooSlow);
    return () => {
      orbitWatchers.delete(setGaveUp);
    };
  }, []);
  if (size === "large" && spaceLook === "orbit" && !gaveUp) return <OrbitingHole className={className} />;
  return <TurningHole size={size} className={className} />;
}

/** The big hole seen from the orbiting ship: the hole traced on the chip, the ship and dust painted over it. */
function OrbitingHole({ className }: { className: string }) {
  const box = useRef<HTMLDivElement>(null);
  const { reduceMotion, pageHidden, officeActivity } = useMotion();
  const covered = usePageCovered();  // behind FilmCraft's editor (covered.ts)
  const [onScreen, setOnScreen] = useState(true);
  const still = reduceMotion || pageHidden || officeActivity === "low_power" || covered;
  const moving = !still && onScreen;
  const run = useRef<{ start: () => void; stop: () => void } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const cv = el.appendChild(document.createElement("canvas"));
    const gl = makeOrbitRenderer(cv);
    if (!gl) {
      cv.remove();
      giveUpOrbit();
      return;
    }
    const front = el.appendChild(document.createElement("canvas"));
    const g2 = front.getContext("2d");
    const lost = () => giveUpOrbit();
    cv.addEventListener("webglcontextlost", lost);
    let w = 0, h = 0, raf = 0, last = 0, going = false;
    let prev = 0, since = 0, slowStretches = 0, gaps: number[] = [];
    const draw = (now: number) => {
      if (!w || !h) return;
      const t = diskTime(now);
      gl.draw(t, t);
      if (g2) paintShip(g2, w, h, orbitPose(t), going ? t : null);
    };
    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const nw = Math.round(el.clientWidth * dpr), nh = Math.round(el.clientHeight * dpr);
      if (!nw || !nh || (nw === w && nh === h)) return;
      w = nw;
      h = nh;
      gl.resize(w, h);
      front.width = w;
      front.height = h;
      draw(performance.now());
    };
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (prev && now - prev < STALL) gaps.push(now - prev);
      prev = now;
      since ||= now;
      if (now - since >= STRETCH) {
        gaps.sort((a, b) => a - b);
        slowStretches = gaps.length >= 3 && gaps[gaps.length >> 1] > SLOW_GAP ? slowStretches + 1 : 0;
        gaps = [];
        since = now;
        if (slowStretches >= 2) {
          giveUpOrbit();
          return;
        }
      }
      if (now - last < FRAME - 2) return;
      last = now;
      draw(now);
    };
    const halt = () => {
      if (going) stopTurning(performance.now());
      going = false;
      cancelAnimationFrame(raf);
    };
    run.current = {
      start: () => {
        if (going) return;
        going = true;
        startTurning(performance.now());
        prev = since = slowStretches = 0;
        gaps = [];
        raf = requestAnimationFrame(tick);
      },
      stop: () => {
        halt();
        draw(performance.now());
      },
    };
    const resize = new ResizeObserver(fit);
    resize.observe(el);
    const unwatchRatio = onPixelRatioChange(fit);
    const seen = typeof IntersectionObserver === "function"
      ? new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting)) : null;
    seen?.observe(el);
    fit();
    return () => {
      run.current = null;
      halt();
      resize.disconnect();
      unwatchRatio();
      seen?.disconnect();
      cv.removeEventListener("webglcontextlost", lost);
      gl.dispose();
      cv.remove();
      front.remove();
    };
  }, []);

  useEffect(() => {
    if (moving) run.current?.start();
    else run.current?.stop();
  }, [moving]);

  return (
    <div ref={box} className={`black-hole large orbit${className ? ` ${className}` : ""}`} aria-hidden="true"
      data-still={moving ? "false" : "true"} data-look="orbit" />
  );
}

/** The lighter hole: the disk seen from one place, turning (blackHoleGl.ts), or painted (blackHoleArt.ts). */
function TurningHole({ size, className }: { size: "small" | "large"; className: string }) {
  const box = useRef<HTMLDivElement>(null);
  const { reduceMotion, pageHidden, officeActivity } = useMotion();
  const covered = usePageCovered();  // behind FilmCraft's editor (covered.ts)
  const [onScreen, setOnScreen] = useState(true);
  const [slow, setSlow] = useState(tooSlow);
  // a new drawing after the graphics chip lost the old one
  const [drawing, setDrawing] = useState(0);
  const still = reduceMotion || pageHidden || officeActivity === "low_power" || slow || covered;
  const moving = !still && onScreen;
  // the drawing set up once per hole; `moving` only starts and stops its clock
  const run = useRef<{ start: () => void; stop: () => void } | null>(null);

  useEffect(() => {
    slowWatchers.add(setSlow);
    setSlow(tooSlow);
    return () => {
      slowWatchers.delete(setSlow);
    };
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    // a canvas of our own each time: one that was offered WebGL can never draw 2D, and a lost one is never reused
    const fresh = () => el.appendChild(document.createElement("canvas"));
    let cv = fresh();
    const gl: HoleRenderer | null = losses < MAX_LOSSES ? makeHoleRenderer(cv) : null;
    let g2: CanvasRenderingContext2D | null = null;
    if (!gl) {
      cv.remove();
      cv = fresh();
      g2 = cv.getContext("2d");
    }
    const under = document.createElement("canvas"), over = document.createElement("canvas");
    // the chip let the drawing go: start again on a fresh canvas (a lost one shows as a blank or broken box)
    const lost = () => {
      losses++;
      setDrawing((n) => n + 1);
    };
    if (gl) cv.addEventListener("webglcontextlost", lost);
    let w = 0, h = 0, raf = 0, last = 0, going = false;
    // how far apart the frames come, to tell whether the computer keeps up
    let prev = 0, since = 0, slowStretches = 0, gaps: number[] = [];
    const draw = (now: number) => {
      if (!w || !h) return;
      const t = diskTime(now);
      if (gl) gl.draw(t);
      else if (g2) paintFrame(g2, under, over, w, h, going ? t : null);
    };
    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const nw = Math.round(el.clientWidth * dpr), nh = Math.round(el.clientHeight * dpr);
      if (!nw || !nh || (nw === w && nh === h)) return;
      w = nw;
      h = nh;
      if (gl) gl.resize(w, h);
      else {
        for (const c of [cv, under, over]) { c.width = w; c.height = h; }
        const gu = under.getContext("2d"), go = over.getContext("2d");
        if (gu && go) paintStill(gu, go, w, h);
      }
      draw(performance.now());
    };
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (prev && now - prev < STALL) gaps.push(now - prev);
      prev = now;
      since ||= now;
      if (now - since >= STRETCH) {
        gaps.sort((a, b) => a - b);
        slowStretches = gaps.length >= 3 && gaps[gaps.length >> 1] > SLOW_GAP ? slowStretches + 1 : 0;
        gaps = [];
        since = now;
        if (slowStretches >= 2) {
          tooSlowNow();
          return;
        }
      }
      if (now - last < FRAME - 2) return;
      last = now;
      draw(now);
    };
    const halt = () => {
      if (going) stopTurning(performance.now());
      going = false;
      cancelAnimationFrame(raf);
    };
    run.current = {
      start: () => {
        if (going || tooSlow) return;
        going = true;
        startTurning(performance.now());
        prev = since = slowStretches = 0;
        gaps = [];
        raf = requestAnimationFrame(tick);
      },
      stop: () => {
        halt();
        draw(performance.now());
      },
    };
    // where the browser paints canvases on the chip (Windows), a reset of the chip gives the painter's canvases back
    // empty: paint them again, once for all three. Not a WebGL loss, so it does not count towards giving WebGL up.
    let restoring = 0;
    const restored = () => {
      cancelAnimationFrame(restoring);
      restoring = requestAnimationFrame(() => {
        w = h = 0;
        fit();
      });
    };
    const painted = gl ? [] : [cv, under, over];
    for (const c of painted) c.addEventListener("contextrestored", restored);
    const resize = new ResizeObserver(fit);
    resize.observe(el);
    const unwatchRatio = onPixelRatioChange(fit);
    const seen = typeof IntersectionObserver === "function"
      ? new IntersectionObserver(([entry]) => setOnScreen(entry.isIntersecting)) : null;
    seen?.observe(el);
    fit();
    return () => {
      run.current = null;
      halt();
      resize.disconnect();
      unwatchRatio();
      seen?.disconnect();
      cancelAnimationFrame(restoring);
      for (const c of painted) c.removeEventListener("contextrestored", restored);
      // before letting the drawing go, which itself sends "lost"
      cv.removeEventListener("webglcontextlost", lost);
      gl?.dispose();
      cv.remove();
    };
  }, [drawing]);

  useEffect(() => {
    if (moving) run.current?.start();
    else run.current?.stop();
  }, [moving, drawing]);

  return (
    <div ref={box} className={`black-hole ${size}${className ? ` ${className}` : ""}`} aria-hidden="true"
      data-still={moving ? "false" : "true"} data-look="lighter" />
  );
}
