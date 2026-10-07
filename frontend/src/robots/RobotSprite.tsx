/**
 * React components for the robot crew: RobotSprite (office scale), RobotPortrait (detail
 * panel) and CoreChamber (the brain core). All render crisp pixel SVG.
 *
 * Animation: when `frame` is omitted the sprite animates from one shared clock (<= 8 fps).
 * The clock stops while the document is hidden or when nobody is subscribed. Reduced motion
 * (prop, or the OS setting when the prop is not given) shows frame 0 of the state, static.
 */
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { renderCore } from "./core";
import { darken, lighten, mix, type PathRun } from "./pixel";
import {
  CORE,
  type AnimState,
  type CoreActivity,
  type Direction,
  type RoleId,
  roleById,
  resolveState,
} from "./registry";
import { renderFrame } from "./sprite";

// ------------------------------------------------------------------ shared clock

const TICK_MS = 125; // 8 fps ceiling
let now = 0;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function hidden() {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}
function startClock() {
  if (timer || hidden() || listeners.size === 0) return;
  timer = setInterval(() => {
    now += TICK_MS;
    listeners.forEach((l) => l());
  }, TICK_MS);
}
function stopClock() {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => (hidden() ? stopClock() : startClock()));
}
function subscribe(cb: () => void) {
  listeners.add(cb);
  startClock();
  return () => {
    listeners.delete(cb);
    if (listeners.size === 0) stopClock();
  };
}
const noopSubscribe = () => () => {};
const getNow = () => now;

/** Milliseconds from the shared clock; static 0 when `active` is false. */
export function useRobotClock(active: boolean): number {
  return useSyncExternalStore(active ? subscribe : noopSubscribe, active ? getNow : () => 0, () => 0);
}

/** OS-level reduced-motion preference (live). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

/** Stable per-id phase so robots don't blink in lockstep (deterministic, not random). */
function phaseOf(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 1777;
}

/**
 * Current frame index for a timing table, re-rendering only when the frame changes
 * (not on every clock tick). Returns 0 when inactive.
 */
export function useAnimFrame(ms: readonly number[], phase: number, active: boolean): number {
  const key = ms.join(",");
  const snap = useCallback(() => (active ? frameAt(ms, now + phase) : 0), [key, phase, active]);
  return useSyncExternalStore(active ? subscribe : noopSubscribe, snap, () => 0);
}

function frameAt(ms: readonly number[], t: number): number {
  const total = ms.reduce((a, b) => a + b, 0);
  if (total <= 0) return 0;
  let r = t % total;
  for (let i = 0; i < ms.length; i++) {
    if (r < ms[i]) return i;
    r -= ms[i];
  }
  return 0;
}

// ------------------------------------------------------------------ path rendering

function Paths({ runs, tint }: { runs: PathRun[]; tint?: (c: string) => string }) {
  return (
    <>
      {runs.map((r, i) => (
        <path key={i} d={r.d} fill={tint && r.fill.startsWith("@") ? tint(r.fill) : r.fill} fillOpacity={r.opacity} />
      ))}
    </>
  );
}

function cardResolver(tint: string, greyed: boolean) {
  const base = greyed ? mix(tint, "#8A8F9C", 0.85) : tint;
  return (tok: string) => {
    switch (tok) {
      case "@c":
        return base;
      case "@h":
        return lighten(base, 0.55);
      case "@l":
        return darken(base, 0.22);
      case "@i":
        return darken(base, 0.7);
      default:
        return "#0A0D18";
    }
  };
}

// ------------------------------------------------------------------ RobotSprite

/** Default task-card colour: warm paper, so it reads against the pale shells. */
export const DEFAULT_CARD = "#FFE7A8";

export interface RobotSpriteProps {
  role: RoleId;
  dir?: Direction;
  state?: AnimState;
  /** Fixed frame. When omitted the sprite animates itself. */
  frame?: number;
  /** Integer pixel scale (1 = 48x64 px). */
  scale?: number;
  /** Task-card tint (any hex colour). `false` hides the card overlay. Default warm paper (DEFAULT_CARD). */
  card?: string | false;
  /** Accessible name; when absent the sprite is aria-hidden. */
  title?: string;
  className?: string;
  /** Freeze on frame 0. Defaults to the OS reduced-motion setting. */
  reducedMotion?: boolean;
}

export function RobotSprite({
  role,
  dir = "down",
  state = "idle",
  frame,
  scale = 2,
  card = DEFAULT_CARD,
  title,
  className,
  reducedMotion,
}: RobotSpriteProps) {
  const osReduced = usePrefersReducedMotion();
  const reduced = reducedMotion ?? osReduced;
  const def = roleById(role);
  const st = resolveState(state);
  const timing = def?.anim[st];
  const animate = frame === undefined && !reduced && !!timing && timing.frames > 1;
  const auto = useAnimFrame(timing?.ms ?? [1], phaseOf(role), animate);
  const f = frame ?? auto;
  const data = useMemo(() => renderFrame(role, dir, st, f), [role, dir, st, f]);
  if (!data) return null;
  const s = Math.max(1, Math.round(scale));
  const tint = cardResolver(card || DEFAULT_CARD, data.grey);
  return (
    <svg
      viewBox="0 0 48 64"
      width={48 * s}
      height={64 * s}
      shapeRendering="crispEdges"
      className={["robot-sprite", `robot-${role}`, `is-${st}`, className].filter(Boolean).join(" ")}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
      style={{ imageRendering: "pixelated", display: "block" }}
      data-role={role}
      data-dir={dir}
      data-state={st}
      data-frame={f}
    >
      {title && <title>{title}</title>}
      <g className="robot-layer-back">
        <Paths runs={data.layers.back} tint={tint} />
      </g>
      <g className="robot-layer-base">
        <Paths runs={data.layers.base} tint={tint} />
      </g>
      {card !== false && (
        <g className="robot-layer-card">
          <Paths runs={data.layers.card} tint={tint} />
        </g>
      )}
      <g className="robot-layer-over">
        <Paths runs={data.layers.over} tint={tint} />
      </g>
    </svg>
  );
}

// ------------------------------------------------------------------ RobotPortrait

export interface RobotPortraitProps {
  role: RoleId;
  /** Integer scale; default 4 (192x256). */
  scale?: number;
  state?: AnimState;
  /** Show a framed backdrop in the department colour. */
  framed?: boolean;
  title?: string;
  className?: string;
  reducedMotion?: boolean;
}

/** Large front view for the detail panel. Same design as the sprite, idle (blinking) by default. */
export function RobotPortrait({
  role,
  scale = 4,
  state = "idle",
  framed = true,
  title,
  className,
  reducedMotion,
}: RobotPortraitProps) {
  const def = roleById(role);
  if (!def) return null;
  const s = Math.max(1, Math.round(scale));
  const sprite = (
    <RobotSprite role={role} dir="down" state={state} scale={s} title={title} reducedMotion={reducedMotion} />
  );
  if (!framed) return <div className={className}>{sprite}</div>;
  return (
    <div
      className={["robot-portrait", className].filter(Boolean).join(" ")}
      style={{
        display: "inline-block",
        padding: s * 2,
        borderRadius: s * 3,
        lineHeight: 0,
        background: `radial-gradient(circle at 50% 60%, ${mix(def.palette.trim, "#0B1020", 0.72)} 0%, #0B1020 70%)`,
        boxShadow: `inset 0 0 0 ${Math.max(1, s / 2)}px ${mix(def.palette.trim, "#0B1020", 0.4)}`,
      }}
    >
      {sprite}
    </div>
  );
}

// ------------------------------------------------------------------ CoreChamber

const CORE_MS: number[] = Array.from({ length: CORE.anim.frames }, () => CORE.anim.ms);

export interface CoreChamberProps {
  /** Integer scale; default 2 (96x128). */
  scale?: number;
  activity?: CoreActivity;
  /** Glow pulse animation (default true). */
  pulse?: boolean;
  frame?: number;
  title?: string;
  className?: string;
  reducedMotion?: boolean;
}

export function CoreChamber({
  scale = 2,
  activity = "idle",
  pulse = true,
  frame,
  title,
  className,
  reducedMotion,
}: CoreChamberProps) {
  const osReduced = usePrefersReducedMotion();
  const reduced = reducedMotion ?? osReduced;
  const animate = frame === undefined && pulse && !reduced;
  const auto = useAnimFrame(CORE_MS, 0, animate);
  const f = frame ?? auto;
  const act: CoreActivity = (CORE.activities as readonly string[]).includes(activity) ? activity : "idle";
  const layers = useMemo(() => renderCore(act, f), [act, f]);
  const s = Math.max(1, Math.round(scale));
  return (
    <svg
      viewBox="0 0 48 64"
      width={48 * s}
      height={64 * s}
      shapeRendering="crispEdges"
      className={["core-chamber", `is-${act}`, className].filter(Boolean).join(" ")}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
      style={{ imageRendering: "pixelated", display: "block" }}
      data-activity={act}
      data-frame={f}
    >
      {title && <title>{title}</title>}
      <Paths runs={layers} />
    </svg>
  );
}
