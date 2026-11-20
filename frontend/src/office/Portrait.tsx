import { useLayoutEffect, useRef } from "react";
import { Dir } from "./cast";
import { ART, CELL, drawRobot, FrameName, Pose, poseFrame, spaceImage } from "./crew";
import { useMotion } from "../motion";

/**
 * One robot drawn from the same crew art as the ship, at a whole-pixel size. `frame` shows one exact frame (the
 * robot gallery); otherwise the pose animates at the ship's pace unless motion is reduced or the page is hidden.
 */
export default function Portrait({ id, pose = "idle", dir, frame, scale = 3, label, animate = true, crop }: {
  id: string; pose?: Pose; dir?: Dir; frame?: FrameName; scale?: number; label?: string; animate?: boolean;
  /** a small head-and-shoulders view (chips, lists) */
  crop?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { reduceMotion, pageHidden } = useMotion();
  useLayoutEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    let active = true, timer: ReturnType<typeof setInterval> | null = null, repaint: (() => void) | null = null;
    const still = !animate || reduceMotion || pageHidden;
    const seed = id.length * 397;
    const walk = dir === "left" ? "walk_left" : "walk_right";
    void spaceImage("crew.png").then((atlas) => {
      if (!active) return;
      const paint = () => {
        let shown = frame || poseFrame(pose, performance.now(), still, seed);
        if (!frame && (pose === "walk" || pose === "carry")) {
          shown = (shown.endsWith("_b") ? `${walk}_b` : `${walk}_a`) as FrameName;
        }
        ctx.imageSmoothingEnabled = false;
        ctx.clearRect(0, 0, CELL.w, CELL.h);
        drawRobot(ctx, atlas, id, shown, CELL.w / 2, CELL.h - 1, pose === "unavailable" ? .5 : 1);
        cv.dataset.art = "studio";
      };
      paint();
      if (!still && !frame) timer = setInterval(paint, 125);
      // a reset of the graphics chip (Windows paints canvases on it) gives a still portrait back empty
      repaint = paint;
      cv.addEventListener("contextrestored", paint);
    }).catch(() => { if (active) cv.dataset.art = "missing"; });
    return () => {
      active = false;
      if (timer !== null) clearInterval(timer);
      if (repaint) cv.removeEventListener("contextrestored", repaint);
    };
  }, [id, pose, dir, frame, animate, reduceMotion, pageHidden]);
  const canvas = (
    <canvas ref={ref} className="portrait" width={CELL.w} height={CELL.h}
      style={{ width: CELL.w * scale, height: CELL.h * scale }}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />
  );
  // The crop shows the head: the top of the sprite sits a pixel below the window's top edge.
  const art = ART[id];
  const top = art ? CELL.h - 1 - art.foot - 1 : 2;
  return crop ? <span className="portrait-crop" style={{ ["--top" as string]: `${-Math.max(0, top) * scale}px` } as React.CSSProperties}>
    {canvas}</span> : canvas;
}
