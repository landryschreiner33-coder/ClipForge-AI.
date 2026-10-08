import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BY_ID, CAST, Dir, RoomId, ROOM_NAMES } from "./cast";
import { OfficeEvent, RoleRow, RoleState, Snapshot } from "./api";
import { FRAMES, frameMs, Pose } from "./sprites";
import { drawBackdrop, drawClock, drawCore, drawRackLights, drawRobot, drawScreens, highlightRoom, ROOM_ACCENT }
  from "./draw";
import { besideManager, LOUNGE, Pt, ROOM, ROOMS, roomOf, route, STATION, WORLD } from "./world";
import { Listener, LIVE_SECONDS } from "./useOffice";

/**
 * The office map: a small canvas renderer with an accessible HTML layer on top (a button per room and per visible
 * robot). Robots stand where the snapshot says their work is: at their station while a job runs, waits or failed,
 * in the Lounge while idle or paused. Walks are started only by real transitions (a role's state changing, a
 * manager's report, a recorded decision); they never delay, create or finish work, and a backlog is never replayed.
 */
export interface Card { job_id: string; kind: string; ref_type: string; ref_id: string; state: string; summary: string }

interface Step { walk?: Pt; carry?: Card; pose?: Pose; dir?: Dir; ms?: number; then?: () => void }
interface Actor {
  id: string;
  x: number;
  y: number;
  dir: Dir;
  path: Pt[];
  steps: Step[];
  carry: Card | null;
  hold: { pose: Pose; until: number; dir?: Dir } | null;
  react: { pose: Pose; until: number } | null;
  visible: boolean;
  offset: number;
}

const SPEED = 70;            // world px per second
const REVIEW_MS = 2400;
const REACT_MS = 2200;
const POSE: Record<RoleState, Pose> = {
  idle: "idle", working: "work", waiting: "wait", retrying: "retry", error: "error", reviewing: "review",
  paused: "paused", unavailable: "unavailable",
};
const NEXT_ROOM: Record<string, Partial<Record<string, RoomId>>> = {
  source: { approved: "studio", rejected: "discover", held: "analyze", rework: "analyze" },
  clip: { approved: "caption", rejected: "studio", rework: "studio", held: "studio" },
  qc: { approved: "schedule", rework: "studio", rejected: "studio", held: "system" },
  upload: { approved: "dock", held: "dock", rejected: "dock", rework: "schedule" },
};
const DECISION_POSE: Record<string, Pose> = { approved: "approved", rework: "rework", rejected: "error", held: "wait" };
const AT_STATION: RoleState[] = ["working", "waiting", "retrying", "error", "reviewing"];

/** Where each role belongs right now, from the snapshot alone. Managers and COMMAND keep their stations. */
export function placements(rows: RoleRow[]): Record<string, { at: Pt | null; lounge: boolean }> {
  const out: Record<string, { at: Pt | null; lounge: boolean }> = {};
  const resting: RoleRow[] = [];
  for (const r of rows) {
    const c = BY_ID[r.id];
    if (!c) continue;
    if (c.rank !== "worker" || AT_STATION.includes(r.state) || r.state === "unavailable") {
      out[r.id] = { at: STATION[r.id], lounge: false };
    } else {
      resting.push(r);
    }
  }
  // the most recently active resting workers get the Lounge places; the others are counted, not drawn
  resting.sort((a, b) => (b.last?.at || 0) - (a.last?.at || 0));
  resting.forEach((r, i) => {
    out[r.id] = { at: i < LOUNGE.length ? LOUNGE[i] : null, lounge: true };
  });
  return out;
}

const dirTo = (a: Pt, b: Pt): Dir =>
  Math.abs(b.x - a.x) > Math.abs(b.y - a.y) ? (b.x > a.x ? "right" : "left") : b.y > a.y ? "down" : "up";

export default function OfficeMap({ snap, subscribe, skew, selected, room, onRobot, onRoom, reduce, stale }: {
  snap: Snapshot;
  subscribe: (fn: Listener) => () => void;
  skew: number;
  selected: string | null;
  room: RoomId | null;
  onRobot: (id: string, card: Card | null) => void;
  onRoom: (id: RoomId) => void;
  reduce: boolean;
  stale: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const actors = useRef(new Map<string, Actor>());
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const pulses = useRef(new Map<RoomId, number>());
  const core = useRef(0);
  const snapRef = useRef(snap);
  const selRef = useRef(selected);
  const reduceRef = useRef(reduce);
  const [scale, setScale] = useState(1);
  const [shown, setShown] = useState<string[]>([]);
  snapRef.current = snap;
  selRef.current = selected;
  reduceRef.current = reduce;

  const rows = useMemo(() => Object.fromEntries(snap.roles.map((r) => [r.id, r])), [snap.roles]);
  const place = useMemo(() => placements(snap.roles), [snap.roles]);
  const resting = snap.roles.filter((r) => place[r.id]?.lounge).length;
  const hiddenResting = snap.roles.filter((r) => place[r.id]?.lounge && !place[r.id]?.at).length;

  // ---- fit the map into its box (whole world pixels inside, CSS scaling with nearest-neighbor sampling)
  useLayoutEffect(() => {
    const el = wrap.current!;
    const fit = () => {
      const w = el.clientWidth, h = el.clientHeight || w * (WORLD.h / WORLD.w);
      const best = Math.max(0.5, Math.min(w / WORLD.w, h / WORLD.h));
      // whole multiples when there is room for them, so every pixel has the same size
      setScale(best >= 2 ? Math.floor(best) : best);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---- follow the snapshot: every role moves to where its real state puts it
  useEffect(() => {
    for (const c of CAST) {
      const p = place[c.id];
      let a = actors.current.get(c.id);
      const target = p?.at || null;
      if (!a) {
        const start = target || STATION[c.id];
        a = { id: c.id, x: start.x, y: start.y, dir: "down", path: [], steps: [], carry: null, hold: null, react: null,
          visible: !!target, offset: Math.floor(Math.random() * 1000) };
        actors.current.set(c.id, a);
        continue;
      }
      if (!target) {
        if (!a.steps.length) a.visible = false;
        continue;
      }
      if (!a.visible) {  // coming back into view: appear at the Lounge door rather than from nowhere
        const from = ROOM.lounge.door;
        a.x = from.x - 6;
        a.y = from.y;
        a.visible = true;
      }
      if (a.steps.length) continue;  // a scripted walk ends at the snapshot's place anyway
      const last = a.path.length ? a.path[a.path.length - 1] : { x: a.x, y: a.y };
      if (last.x === target.x && last.y === target.y) continue;
      if (reduceRef.current) {
        a.x = target.x;
        a.y = target.y;
        a.path = [];
      } else {
        a.path = route({ x: a.x, y: a.y }, target).slice(1);
      }
      a.hold = null;
    }
    setShown(CAST.filter((c) => actors.current.get(c.id)?.visible).map((c) => c.id));
  }, [place]);

  // ---- real events: reports are carried to the manager, decisions get COMMAND's reaction
  useEffect(() => subscribe((events: OfficeEvent[], serverTime: number) => {
    const t = performance.now();
    for (const e of events) {
      if (serverTime - e.at > LIVE_SECONDS) continue;  // history is listed, not replayed
      if (e.type === "report" && e.data?.worker && BY_ID[e.data.worker] && BY_ID[e.role]) {
        carry(e);
      } else if (e.type === "decision") {
        react("command", DECISION_POSE[e.data?.action] || "review", t);
        const next = NEXT_ROOM[e.data?.point]?.[e.data?.action];
        if (next) pulses.current.set(next, t + 1800);
      } else if (e.type === "control") {
        react("command", "review", t);
      } else if (e.type === "strategy_changed") {
        react("curator", "approved", t);
        core.current = Math.max(core.current, t + 3000);
      } else if (e.type === "strategy_rolled_back") {
        react("curator", "rework", t);
      } else if (e.type === "brain_evaluated" || e.type === "brain_evaluation") {
        core.current = Math.max(core.current, t + 3000);
      } else if (e.type === "brain_lookup") {
        core.current = Math.max(core.current, t + 1500);
      }
    }
  }), [subscribe]);

  const react = (id: string, pose: Pose, t: number) => {
    const a = actors.current.get(id);
    if (a) a.react = { pose, until: t + REACT_MS };
  };

  const carry = (e: OfficeEvent) => {
    const w = actors.current.get(e.data.worker);
    const m = actors.current.get(e.role);
    const card: Card = { job_id: e.job_id, kind: e.kind, ref_type: e.ref_type, ref_id: e.ref_id,
      state: e.data?.state || "", summary: e.message };
    const review = () => {
      if (m) m.hold = { pose: "review", until: performance.now() + REVIEW_MS };
    };
    if (!w || !w.visible || reduceRef.current || e.data.worker === e.role) {
      review();
      return;
    }
    const spot = besideManager(e.role);
    const face: Dir = spot.x < STATION[e.role].x ? "right" : "left";
    // Coalesce: a newer report replaces a walk that has not started yet.
    w.steps = [
      ...(card.state === "failed" ? [{ pose: "error" as Pose, ms: 900 }] : []),
      { walk: spot, carry: card },
      { pose: "idle", dir: face, ms: 700, carry: card, then: review },
      { pose: "idle", dir: face, ms: REVIEW_MS - 700 },
    ];
    w.path = [];
    w.hold = null;
  };

  // ---- the frame loop
  useEffect(() => {
    const cv = canvas.current!;
    const ctx = cv.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    let raf = 0, last = performance.now(), drawn = 0;
    const step = (t: number) => {
      const dt = Math.min(0.1, (t - last) / 1000);
      last = t;
      const still = reduceRef.current;
      for (const a of actors.current.values()) advance(a, dt, t, still);
      if (still && t - drawn < 500 && drawn) {
        raf = requestAnimationFrame(step);
        return;
      }
      if (!still && t - drawn < 45) {  // about 20 frames a second is plenty for pixel art
        raf = requestAnimationFrame(step);
        return;
      }
      drawn = t;
      render(ctx, t, still);
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const advance = (a: Actor, dt: number, t: number, still: boolean) => {
    if (a.react && a.react.until < t) a.react = null;
    if (a.hold && a.hold.until < t) a.hold = null;
    if (!a.path.length && a.steps.length && !a.hold) {
      const s = a.steps[0];
      if (s.walk) {
        a.path = still ? [s.walk] : route({ x: a.x, y: a.y }, s.walk).slice(1);
        a.carry = s.carry || null;
        a.steps[0] = { ...s, walk: undefined };
        if (!s.pose) a.steps.shift();
      } else {
        a.steps.shift();
        a.carry = s.carry || null;
        if (s.pose) a.hold = { pose: s.pose, until: t + (s.ms || 600), dir: s.dir };
        s.then?.();
        if (!a.steps.length) {
          // the script is over: go where the snapshot puts this role now
          const p = placements(snapRef.current.roles)[a.id];
          a.carry = null;
          if (p?.at) a.path = still ? [p.at] : route({ x: a.x, y: a.y }, p.at).slice(1);
          else a.visible = false;
        }
      }
    }
    if (a.path.length) {
      const target = a.path[0];
      if (still) {
        a.x = a.path[a.path.length - 1].x;
        a.y = a.path[a.path.length - 1].y;
        a.path = [];
      } else {
        const dx = target.x - a.x, dy = target.y - a.y;
        const dist = Math.abs(dx) + Math.abs(dy);
        const move = SPEED * dt;
        a.dir = dirTo({ x: a.x, y: a.y }, target);
        if (dist <= move) {
          a.x = target.x;
          a.y = target.y;
          a.path.shift();
        } else if (Math.abs(dx) > 0) a.x += Math.sign(dx) * Math.min(move, Math.abs(dx));
        else a.y += Math.sign(dy) * Math.min(move, Math.abs(dy));
      }
      if (!a.path.length && !a.steps.length) {
        a.dir = "down";
        if (!placements(snapRef.current.roles)[a.id]?.at) a.visible = false;
      }
    }
  };

  const poseOf = (a: Actor): Pose => {
    if (a.path.length) return a.carry ? "carry" : "walk";
    if (a.react) return a.react.pose;
    if (a.hold) return a.hold.pose;
    const row = snapRef.current.roles.find((r) => r.id === a.id);
    return row ? POSE[row.state] : "idle";
  };

  const render = (ctx: CanvasRenderingContext2D, t: number, still: boolean) => {
    const s = snapRef.current;
    ctx.drawImage(drawBackdrop(), 0, 0);
    const working = new Set<RoomId>();
    for (const r of s.roles) if (r.state === "working" && BY_ID[r.id]) working.add(BY_ID[r.id].room);
    drawScreens(ctx, working, t, still);
    drawClock(ctx, new Date(Date.now() + skew * 1000));
    const brainBusy = s.brain && "state" in s.brain && s.brain.state === "evaluating";
    drawCore(ctx, core.current > t || brainBusy ? 1 : 0.2, t, still);
    const colors: Record<string, string> = { healthy: "#57eea0", degraded: "#ffab45", error: "#ff5d73", unknown: "#7d8494" };
    drawRackLights(ctx, s.health.checks.map((c) => colors[c.status] || colors.unknown));
    for (const [id, until] of pulses.current) {
      if (until < t) pulses.current.delete(id);
      else highlightRoom(ctx, id, Math.min(1, (until - t) / 600));
    }
    for (const [id, b] of buttons.current) b.hidden = !actors.current.get(id)?.visible;
    const list = [...actors.current.values()].filter((a) => a.visible).sort((a, b) => a.y - b.y);
    for (const a of list) {
      const c = BY_ID[a.id];
      const pose = poseOf(a);
      const n = FRAMES[pose].n;
      const ms = frameMs(c, pose) || 400;
      const frame = still || n === 1 ? 0 : Math.floor((t + a.offset) / ms) % n;
      const dir = a.path.length ? a.dir : a.hold?.dir || "down";
      drawRobot(ctx, a.id, a.x, a.y, dir, pose, frame, selRef.current === a.id);
      const b = buttons.current.get(a.id);
      if (b) {
        b.style.left = `${((a.x - 14) / WORLD.w) * 100}%`;
        b.style.top = `${((a.y - 44) / WORLD.h) * 100}%`;
        b.dataset.pose = pose;
        b.dataset.room = roomOf(a)?.id || "corridor";  // where it stands now (the browser tests read it)
      }
    }
  };

  const label = (id: string) => {
    const c = BY_ID[id], r = rows[id];
    const st = r ? STATE_WORDS[r.state] : "unknown";
    const task = r?.task?.message ? `: ${r.task.message}` : "";
    return `${c.name}, ${c.title}, ${st}${task}`;
  };

  return (
    <div className={`office-map${stale ? " stale" : ""}`} ref={wrap}>
      <div className="office-world" style={{ width: WORLD.w * scale, height: WORLD.h * scale,
        ["--s" as string]: scale } as React.CSSProperties}>
        <canvas ref={canvas} width={WORLD.w} height={WORLD.h} aria-hidden="true"
          style={{ imageRendering: scale >= 1 ? "pixelated" : "auto" }} />
        {ROOMS.map((r) => {
          const people = snap.roles.filter((x) => BY_ID[x.id]?.room === r.id);
          const busy = people.filter((x) => x.state === "working").length;
          const extra = r.id === "lounge" && hiddenResting ? ` +${hiddenResting}` : "";
          return (
            <button key={r.id} type="button" className={`room-hit${room === r.id ? " on" : ""}`}
              style={{ left: `${(r.x / WORLD.w) * 100}%`, top: `${(r.y / WORLD.h) * 100}%`,
                width: `${(r.w / WORLD.w) * 100}%`, height: `${(r.h / WORLD.h) * 100}%`,
                ["--accent" as string]: ROOM_ACCENT[r.id] } as React.CSSProperties}
              aria-label={`${ROOM_NAMES[r.id]}${r.id === "lounge" ? `: ${resting} resting` :
                busy ? `: ${busy} working` : ""}. Open details`}
              aria-pressed={room === r.id}
              onClick={() => onRoom(r.id)}>
              <span className="room-sign" aria-hidden="true">{ROOM_NAMES[r.id]}{extra}</span>
            </button>
          );
        })}
        {shown.map((id) => (
          <button key={id} type="button" className={`robot-hit${selected === id ? " on" : ""}`}
            ref={(el) => {
              if (el) buttons.current.set(id, el);
              else buttons.current.delete(id);
            }}
            style={{ left: `${((actors.current.get(id)!.x - 14) / WORLD.w) * 100}%`,
              top: `${((actors.current.get(id)!.y - 44) / WORLD.h) * 100}%`,
              width: `${(28 / WORLD.w) * 100}%`, height: `${(46 / WORLD.h) * 100}%` }}
            aria-label={label(id)} aria-pressed={selected === id} data-id={id} data-state={rows[id]?.state}
            onClick={() => onRobot(id, actors.current.get(id)?.carry || null)}>
            {selected === id && <span className="robot-tag" aria-hidden="true">{BY_ID[id].name}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

export const STATE_WORDS: Record<RoleState, string> = {
  idle: "idle", working: "working", waiting: "waiting", retrying: "retrying", error: "stopped by an error",
  reviewing: "reviewing", paused: "paused", unavailable: "unavailable",
};
