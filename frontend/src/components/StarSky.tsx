import { useEffect, useRef } from "react";
import { usePageCovered } from "../covered";
import { useMotion } from "../motion";
import { onPixelRatioChange } from "./pixelRatio";
import { addDrift, addSky, setSkyMoving } from "./starSky";

/**
 * The moving sky (starSky.ts): the tiles of small stars sliding past and, on a canvas over them, the brighter stars,
 * dust and shooting stars. Either the whole window behind every page, or, with `strip`, the masthead, which paints its
 * own copy of the sky over the page that scrolls under it (its tiles are shifted so they line up with the window's).
 * It moves only while motion is allowed, Low power is off and the window is shown; otherwise it holds still.
 * Decoration: hidden from screen readers.
 */
export function StarSky({ strip = false }: { strip?: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const tiles = useRef<HTMLDivElement>(null);
  const { reduceMotion, pageHidden, officeActivity } = useMotion();
  const covered = usePageCovered();  // behind FilmCraft's editor (covered.ts)
  const moving = !reduceMotion && !pageHidden && officeActivity !== "low_power" && !covered;

  useEffect(() => {
    const canvas = ref.current, box = tiles.current;
    if (!canvas || !box) return;
    const shift = strip ? box.querySelector<HTMLElement>(".sky-shift") : null;
    // each canvas is measured where it is: the window's leaves out a scrollbar that takes room, and draws the stars
    // at the same places as the masthead's copy, one canvas pixel to one screen pixel
    const place = () => {
      const r = canvas.getBoundingClientRect();
      if (shift) {
        // the copy covers the window from its top-left corner down to the masthead's bottom
        shift.style.width = `${window.innerWidth}px`;
        shift.style.height = `${Math.max(0, r.bottom)}px`;
        shift.style.transform = `translate(${-r.left}px, ${-r.top}px)`;
      }
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    };
    const sky = addSky(canvas, place);
    const stopDrift = addDrift(Array.from(box.querySelectorAll<HTMLElement>(".sky-tile")));
    const again = () => sky.measure();
    const watch = new ResizeObserver(again);
    watch.observe(canvas);
    window.addEventListener("resize", again);
    if (strip) window.addEventListener("scroll", again, { passive: true });
    const unwatchRatio = onPixelRatioChange(again);
    return () => {
      watch.disconnect();
      window.removeEventListener("resize", again);
      window.removeEventListener("scroll", again);
      unwatchRatio();
      stopDrift();
      sky.remove();
    };
  }, [strip]);

  useEffect(() => {
    if (strip) return;
    setSkyMoving(moving);
    // once the sky is gone (signed out), nothing is left to draw
    return () => setSkyMoving(false);
  }, [moving, strip]);

  const layers = <><div className="sky-tile far" /><div className="sky-tile near" /></>;
  return (
    <>
      <div ref={tiles} className={strip ? "sky-drift sky-back" : "sky-drift"} aria-hidden="true">
        {strip ? <div className="sky-shift">{layers}</div> : layers}
      </div>
      <canvas ref={ref} className={strip ? "sky-stars sky-back" : "sky-stars"} aria-hidden="true" />
    </>
  );
}
