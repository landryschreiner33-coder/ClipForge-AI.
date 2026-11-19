import { useEffect, useRef } from "react";
import { useMotion } from "../motion";
import { paintFrame, paintStill } from "./blackHoleArt";

/** One clock for every black hole, so the disk does not jump when a page opens again. */
const BORN = performance.now();

/** The black hole in the studio's sky, painted by blackHoleArt.ts. Its disk turns twelve steps a second only while
 * motion is allowed, the window is shown and the hole is on screen; otherwise it is one still picture. It is
 * decoration and says nothing about work. */
export function BlackHole({ size = "small", className = "" }: { size?: "small" | "large"; className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const { reduceMotion, pageHidden } = useMotion();
  useEffect(() => {
    const el = box.current, cv = canvas.current, g = cv?.getContext("2d");
    if (!el || !cv || !g) return;
    const under = document.createElement("canvas"), over = document.createElement("canvas");
    const still = reduceMotion || pageHidden;
    let w = 0, h = 0, raf = 0, last = 0, onScreen = true;
    const draw = (now: number) => { if (w && h) paintFrame(g, under, over, w, h, still ? null : (now - BORN) / 1000); };
    const fit = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const nw = Math.round(el.clientWidth * dpr), nh = Math.round(el.clientHeight * dpr);
      if (!nw || !nh || (nw === w && nh === h)) return;
      w = nw; h = nh;
      for (const c of [cv, under, over]) { c.width = w; c.height = h; }
      const gu = under.getContext("2d"), go = over.getContext("2d");
      if (gu && go) paintStill(gu, go, w, h);
      draw(performance.now());
    };
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (!onScreen || now - last < 1000 / 12) return;
      last = now;
      draw(now);
    };
    const resize = new ResizeObserver(fit);
    resize.observe(el);
    const seen = typeof IntersectionObserver === "function"
      ? new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; }) : null;
    seen?.observe(el);
    fit();
    if (!still) raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); resize.disconnect(); seen?.disconnect(); };
  }, [reduceMotion, pageHidden]);
  return (
    <div ref={box} className={`black-hole ${size}${className ? ` ${className}` : ""}`} aria-hidden="true"
      data-still={reduceMotion || pageHidden ? "true" : "false"}>
      <canvas ref={canvas} />
    </div>
  );
}
