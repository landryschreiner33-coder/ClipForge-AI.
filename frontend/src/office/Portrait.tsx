import { useLayoutEffect, useRef } from "react";
import { Dir } from "./cast";
import { paint } from "./draw";
import { CELL, FRAMES, frameMs, Pose, sprite, spriteTop } from "./sprites";
import { BY_ID } from "./cast";
import { useMotion } from "../motion";

/**
 * One robot drawn large (whole-pixel scale), for the detail panel, the Team roster and the gallery. It animates its
 * pose only when animations are allowed; with Reduce animations it shows the first frame.
 */
export default function Portrait({ id, pose = "idle", dir = "down", scale = 3, label, animate = true, crop }: {
  id: string; pose?: Pose; dir?: Dir; scale?: number; label?: string; animate?: boolean;
  /** a small head-and-shoulders view (chips, lists) */
  crop?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { reduceMotion, pageHidden } = useMotion();
  useLayoutEffect(() => {
    const cv = ref.current!;
    const ctx = cv.getContext("2d")!;
    const c = BY_ID[id];
    const n = FRAMES[pose].n;
    const ms = c ? frameMs(c, pose) || 500 : 500;
    let frame = 0;
    const draw = () => {
      ctx.clearRect(0, 0, CELL.w, CELL.h);
      paint(ctx, sprite(id, dir, pose, frame));
    };
    draw();
    if (!animate || reduceMotion || pageHidden || n < 2) return;
    const timer = setInterval(() => {
      frame = (frame + 1) % n;
      draw();
    }, ms);
    return () => clearInterval(timer);
  }, [id, pose, dir, animate, reduceMotion, pageHidden]);
  const canvas = (
    <canvas ref={ref} className="portrait" width={CELL.w} height={CELL.h}
      style={{ width: CELL.w * scale, height: CELL.h * scale }}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />
  );
  return crop ? <span className="mini" style={{ ["--top" as string]: `${-Math.max(0, spriteTop(id) - 2) * scale}px` } as React.CSSProperties}>{canvas}</span> : canvas;
}
