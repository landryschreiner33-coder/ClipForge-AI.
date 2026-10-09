import { useLayoutEffect, useRef } from "react";
import { Dir } from "./cast";
import { paint } from "./draw";
import { CELL, FRAMES, frameMs, Pose, sprite, spriteTop } from "./sprites";
import { BY_ID } from "./cast";
import { useMotion } from "../motion";
import type { studioPortrait } from "./StudioPortraits";

const HEIGHT = 68;

/**
 * The same refined artwork as the office, delivered through one shared offscreen renderer and a frame cache.
 * Original art remains available for CORE and browsers that cannot initialize the new graphics.
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
    let active = true;
    let version = 0;
    let refined: typeof studioPortrait | null = null;
    ctx.imageSmoothingEnabled = false;
    const still = !animate || reduceMotion || pageHidden;
    const draw = () => {
      const request = ++version;
      if (refined) {
        void refined(id, pose, dir, performance.now(), still).then((image) => {
          if (!active || request !== version) return;
          if (image) {
            ctx.clearRect(0, 0, CELL.w, HEIGHT);
            ctx.drawImage(image, 0, 0);
            cv.dataset.art = "studio";
          } else {
            refined = null;
            ctx.clearRect(0, 0, CELL.w, HEIGHT);
            paint(ctx, sprite(id, dir, pose, frame), 0, 3);
            cv.dataset.art = "original";
          }
        }).catch(() => { if (active) refined = null; });
      } else {
        ctx.clearRect(0, 0, CELL.w, HEIGHT);
        paint(ctx, sprite(id, dir, pose, frame), 0, 3);
        cv.dataset.art = "original";
      }
    };
    draw();
    if (c) void import("./StudioPortraits").then((module) => {
      if (!active) return;
      refined = module.studioPortrait;
      draw();
    }).catch(() => { /* Keep the complete original-art fallback. */ });
    const timer = still || n < 2 ? null : setInterval(() => {
      frame = Math.floor(performance.now() / ms) % n;
      draw();
    }, Math.min(ms, 110));
    return () => {
      active = false;
      if (timer !== null) clearInterval(timer);
    };
  }, [id, pose, dir, animate, reduceMotion, pageHidden]);
  const canvas = (
    <canvas ref={ref} className="portrait" width={CELL.w} height={HEIGHT}
      style={{ width: CELL.w * scale, height: HEIGHT * scale }}
      role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />
  );
  const c = BY_ID[id];
  const top = c ? c.rank === "director" ? 3 : c.rank === "manager" ? 7 : 11 : spriteTop(id) + 1;
  return crop ? <span className="mini" style={{ ["--top" as string]: `${-Math.max(0, top) * scale}px` } as React.CSSProperties}>{canvas}</span> : canvas;
}
