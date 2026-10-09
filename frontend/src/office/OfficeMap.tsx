import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon, IconName } from "../components/ui";
import { useMotion } from "../motion";
import { BY_ID, CAST, RoomId, ROOM_NAMES } from "./cast";
import { OfficeEvent, RoleState, Snapshot } from "./api";
import { ROOM_ACCENT } from "./draw";
import { CORE_AT, ROOMS, roomOf, WORLD } from "./world";
import { Listener, LIVE_SECONDS } from "./useOffice";
import { OfficeMotion, placements, WorkCard } from "./OfficeMotion";
import { LivingFallback } from "./LivingFallback";
import type { StudioScene } from "./StudioScene";

export type Card = WorkCard;
export { placements } from "./OfficeMotion";
const NEXT_ROOM: Record<string, Partial<Record<string, RoomId>>> = {
  source: { approved: "studio", rejected: "discover", held: "analyze", rework: "analyze" },
  clip: { approved: "caption", rejected: "studio", rework: "studio", held: "studio" },
  qc: { approved: "schedule", rework: "studio", rejected: "studio", held: "system" },
  upload: { approved: "dock", held: "dock", rejected: "dock", rework: "schedule" },
};
const STATE_ICON: Record<RoleState, IconName> = {
  idle: "dot", working: "play", waiting: "clock", retrying: "refresh", error: "alert", reviewing: "check",
  paused: "pause", unavailable: "x",
};
const DECISION_POSE = { approved: "approved", rework: "rework", rejected: "error", held: "wait" } as const;
const BREAK_WORDS: Record<string, string> = {
  arcade: "Playing an arcade game", boardgame: "Playing a tabletop game", snack: "Having a snack",
  drink: "Having a drink", read: "Reading", rest: "Relaxing",
};
// Alternate names along the dense arcade/cafe and sofa edges so the whole-office camera stays readable.
const LOWER_LOUNGE_LABELS = new Set([
  "arcade-2", "arcade-4", "cafe-drink-1", "cafe-drink-2",
  "sofa-read-2", "sofa-read-4", "sofa-read-5", "sofa-snack",
]);

/** The canvas is decorative; accessible robot/room controls continue to expose actual backend states. */
export default function OfficeMap({ snap, subscribe, selected, room, onRobot, onRoom, reduce, stale }: {
  snap: Snapshot; subscribe: (fn: Listener) => () => void; skew: number; selected: string | null;
  room: RoomId | null; onRobot: (id: string, card: Card | null) => void; onRoom: (id: RoomId) => void;
  reduce: boolean; stale: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const { pageHidden } = useMotion();
  const choreography = useRef<OfficeMotion | null>(null);
  if (!choreography.current) choreography.current = new OfficeMotion(snap);
  const motion = choreography.current;
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const brainLink = useRef<HTMLAnchorElement>(null), transferNote = useRef<HTMLSpanElement>(null);
  const pulses = useRef(new Map<RoomId, number>()), core = useRef(0);
  const latest = useRef({ snap, selected, reduce, stale, pageHidden });
  latest.current = { snap, selected, reduce, stale, pageHidden };
  const cutoff = useRef(snap.cursor), suspendedSnapshot = useRef<Snapshot | null>(null);
  const [scale, setScale] = useState(1);
  const [renderer, setRenderer] = useState<"pixi" | "canvas">("pixi");
  const [focus, setFocus] = useState<RoomId | "">("");
  const focused = focus ? ROOMS.find(r => r.id === focus) : null;
  const zoom = focused ? Math.min(WORLD.w / focused.w, WORLD.h / focused.h) * 0.84 : 1;
  const pan = focused ? `translate(${(WORLD.w / 2 - focused.x - focused.w / 2) * scale * zoom}px, ${
    (WORLD.h / 2 - focused.y - focused.h / 2) * scale * zoom}px)` : undefined;
  const rows = useMemo(() => Object.fromEntries(snap.roles.map(r => [r.id, r])), [snap.roles]);
  const resting = Object.values(placements(snap.roles)).filter(p => p.lounge).length;

  useLayoutEffect(() => {
    const el = wrap.current!;
    const fit = () => {
      const w = el.clientWidth, h = el.clientHeight || w * WORLD.h / WORLD.w;
      const best = Math.max(0.2, Math.min(w / WORLD.w, h / WORLD.h));
      setScale(best >= 2 ? Math.floor(best) : best);
    };
    fit(); const observer = new ResizeObserver(fit); observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    cutoff.current = Math.max(cutoff.current, snap.cursor);
    const paused = ["paused", "pausing"].includes(snap.run.state);
    if (stale || pageHidden || paused) {
      suspendedSnapshot.current = snap;
      motion.clearTransfers();
      if (paused && !stale && !pageHidden) motion.reconcile(snap, true);
      return;
    }
    if (suspendedSnapshot.current) {
      // Visibility/connection can recover before a fresh API snapshot arrives.
      if (snap === suspendedSnapshot.current) return;
      motion.resync(snap); cutoff.current = snap.cursor; suspendedSnapshot.current = null;
    }
    if (reduce || paused) motion.clearTransfers();
    motion.reconcile(snap, reduce || paused);
  }, [snap, reduce, stale, pageHidden, motion]);

  useEffect(() => subscribe((events: OfficeEvent[], serverTime: number) => {
    const current = latest.current;
    if (current.stale || current.pageHidden || suspendedSnapshot.current) return;
    const now = performance.now();
    const paused = ["paused", "pausing"].includes(current.snap.run.state);
    if (!paused) motion.events(events, serverTime, now, current.reduce);
    for (const event of events) {
      if (event.id <= cutoff.current || serverTime - event.at > LIVE_SECONDS || event.at > serverTime + 5) continue;
      if (event.type === "decision") {
        motion.react("command", DECISION_POSE[event.data?.action as keyof typeof DECISION_POSE] || "review", now);
        const next = NEXT_ROOM[event.data?.point]?.[event.data?.action];
        if (next) pulses.current.set(next, now + 1800);
      } else if (event.type === "strategy_changed") {
        motion.react("curator", "approved", now); core.current = now + 3500;
      } else if (event.type === "strategy_rolled_back") {
        motion.react("curator", "rework", now);
      } else if (["brain_evaluated", "brain_evaluation", "brain_lookup"].includes(event.type)) {
        core.current = now + (event.type === "brain_lookup" ? 1800 : 3500);
      }
    }
  }), [subscribe, motion]);

  useEffect(() => {
    const cv = canvas.current!;
    let scene: StudioScene | null = null, fallback: LivingFallback | null = null;
    let cancelled = false, raf = 0, last = performance.now(), drawn = 0;
    const frame = (now: number) => {
      const state = latest.current, dt = Math.min(0.1, (now - last) / 1000); last = now;
      const frozen = state.stale || state.pageHidden || suspendedSnapshot.current !== null
        || ["paused", "pausing"].includes(state.snap.run.state);
      const still = state.reduce || frozen;
      motion.tick(dt, now, state.reduce, frozen);
      if (drawn && now - drawn < (still ? 250 : 45)) { raf = requestAnimationFrame(frame); return; }
      drawn = now;
      for (const [id, until] of pulses.current) if (until < now) pulses.current.delete(id);
      const actors = [...motion.actors.values()].sort((a, b) => a.y - b.y);
      const painted = actors.map(a => ({ id: a.id, x: a.x, y: a.y, dir: a.dir, pose: motion.pose(a),
        posture: motion.posture(a), selected: state.selected === a.id,
        breakActivity: motion.breakActivity(a), breakPhase: motion.breakPhase(a) }));
      const busy = core.current > now || state.snap.brain?.state === "evaluating"
        || state.snap.roles.some(r => BY_ID[r.id]?.room === "brain" && r.state === "working");
      const passes = motion.passes(now);
      scene?.draw(state.snap, painted, now, still, pulses.current, busy, state.stale, passes);
      fallback?.draw(state.snap, painted, now, still, busy, passes, state.stale);
      for (const a of actors) {
        const button = buttons.current.get(a.id); if (!button) continue;
        const posture = motion.posture(a), height = posture === "rest" ? 48 : 65;
        button.style.left = `${(a.x - 19) / WORLD.w * 100}%`;
        button.style.top = `${(a.y - height) / WORLD.h * 100}%`;
        button.style.height = `${height / WORLD.h * 100}%`;
        button.dataset.pose = motion.pose(a); button.dataset.posture = posture;
        button.dataset.room = roomOf(a)?.id || "corridor";
        button.dataset.carrying = a.card ? "true" : "false";
        button.dataset.offering = motion.isSender(a) ? "true" : "false";
        const activity = motion.breakActivity(a);
        button.dataset.breakActivity = activity || "";
        button.dataset.breakPhase = motion.breakPhase(a).toFixed(3);
        button.dataset.breakSpot = motion.breakSpot(a) || "";
        button.dataset.labelRow = LOWER_LOUNGE_LABELS.has(button.dataset.breakSpot) ? "lower" : "base";
        button.title = activity ? `${BY_ID[a.id].name} · ${BREAK_WORDS[activity]} (lounge animation)` : "";
      }
      const brainMode = state.stale ? "offline" : frozen || state.snap.brain?.state === "paused" ? "paused" : busy ? "active" : "standby";
      if (brainLink.current) {
        brainLink.current.dataset.mode = brainMode;
        const word = { offline: "Offline", paused: "Paused", active: "Processing", standby: "Standby" }[brainMode];
        brainLink.current.setAttribute("aria-label", `Brain Core: ${word}. Open Brain workspace`);
        const label = brainLink.current.querySelector("span");
        if (label && label.textContent !== `CORE · ${word}`) label.textContent = `CORE · ${word}`;
      }
      const transfer = motion.activeTransfer(), note = transferNote.current;
      if (note) {
        note.dataset.phase = transfer?.phase || "idle";
        note.dataset.from = transfer?.from || ""; note.dataset.to = transfer?.to || "";
        const label = transfer ? `${BY_ID[transfer.from].name} → ${BY_ID[transfer.to].name} · ${
          transfer.phase === "approach" ? "Bringing work" : transfer.phase === "pass" ? "Passing document" : "Received"}` : "";
        if (note.textContent !== label) note.textContent = label;
      }
      raf = requestAnimationFrame(frame);
    };
    const init = async () => {
      await Promise.resolve(); if (cancelled) return;
      if (renderer === "pixi") {
        try {
          const module = await import("./StudioScene"); if (cancelled) return;
          scene = await module.StudioScene.create(cv);
          if (cancelled) { scene.destroy(); return; }
        } catch { if (!cancelled) setRenderer("canvas"); return; }
      } else {
        const ctx = cv.getContext("2d"); if (!ctx) return;
        fallback = new LivingFallback(ctx);
      }
      raf = requestAnimationFrame(frame);
    };
    void init();
    return () => { cancelled = true; cancelAnimationFrame(raf); scene?.destroy(); fallback?.destroy(); };
  }, [renderer, motion]);

  const label = (id: string) => {
    const c = BY_ID[id], r = rows[id], task = r?.task?.message ? `: ${r.task.message}` : "";
    return `${c.name}, ${c.title}, ${stale ? "last known: " : ""}${STATE_WORDS[r?.state || "unavailable"]}${task}`;
  };
  return <div className="office-map-frame">
    <div className={`office-map${stale ? " stale" : ""}`} ref={wrap} data-renderer={renderer} data-camera={focus || "office"}>
      <div className="office-world" style={{ width: WORLD.w * scale * zoom, height: WORLD.h * scale * zoom,
        transform: pan, ["--s" as string]: scale * zoom } as React.CSSProperties}>
        <canvas key={renderer} ref={canvas} width={WORLD.w} height={WORLD.h} aria-hidden="true" />
        {ROOMS.map(r => <button key={r.id} type="button" className={`room-hit${room === r.id ? " on" : ""}`}
          style={{ left: `${r.x / WORLD.w * 100}%`, top: `${r.y / WORLD.h * 100}%`, width: `${r.w / WORLD.w * 100}%`,
            height: `${r.h / WORLD.h * 100}%`, ["--accent" as string]: ROOM_ACCENT[r.id] } as React.CSSProperties}
          aria-label={`${ROOM_NAMES[r.id]}${r.id === "lounge" ? `: ${resting} off duty` : ""}. Open details`}
          aria-pressed={room === r.id} onClick={() => onRoom(r.id)}>
          <span className="room-sign" aria-hidden="true">{ROOM_NAMES[r.id]}</span>
        </button>)}
        <a ref={brainLink} href="#/brain" className="brain-core-hit" data-mode="standby"
          aria-label="Brain Core: Standby. Open Brain workspace" style={{ left: `${(CORE_AT.x - 66) / WORLD.w * 100}%`,
            top: `${(CORE_AT.y - 130) / WORLD.h * 100}%`, width: `${132 / WORLD.w * 100}%`, height: `${132 / WORLD.h * 100}%` }}>
          <span aria-hidden="true">CORE · Standby</span>
        </a>
        {CAST.map(c => <button key={c.id} type="button" className={`robot-hit${selected === c.id ? " on" : ""}`}
          ref={el => { if (el) buttons.current.set(c.id, el); else buttons.current.delete(c.id); }}
          style={{ width: `${38 / WORLD.w * 100}%`, height: `${65 / WORLD.h * 100}%` }}
          aria-label={label(c.id)} aria-pressed={selected === c.id} data-id={c.id} data-state={rows[c.id]?.state || "unavailable"}
          onClick={() => onRobot(c.id, motion.actors.get(c.id)?.card || null)}>
          <span className={`robot-state state-${rows[c.id]?.state || "unavailable"}`} aria-hidden="true"
            title={stale ? "Last known state" : STATE_WORDS[rows[c.id]?.state || "unavailable"]}>
            <Icon name={STATE_ICON[rows[c.id]?.state || "unavailable"]} size={12} />
          </span>
          <span className="robot-tag" aria-hidden="true">{c.name}</span>
        </button>)}
      </div>
    </div>
    <div className="office-map-legend" aria-label="Robot states">
      <span>{CAST.length} robots · {stale ? "Last known states" : "Live job states"}</span>
      <label className="office-camera">Camera <select aria-label="Office camera" value={focus}
        onChange={event => setFocus(event.target.value as RoomId | "")}>
        <option value="">Whole office</option>
        {ROOMS.map(r => <option key={r.id} value={r.id}>{ROOM_NAMES[r.id]}</option>)}
      </select></label>
      <span ref={transferNote} className="handoff-note" data-phase="idle" role="status" aria-live="polite" />
      {renderer === "canvas" && <span>Original artwork · new graphics unavailable in this browser</span>}
      {(["working", "waiting", "idle", "paused", "error"] as RoleState[]).map(state =>
        <span key={state}><Icon name={STATE_ICON[state]} size={13} />{state[0].toUpperCase() + state.slice(1)}</span>)}
    </div>
    <span className="lounge-life-caption"
      title="Games, snacks and coffee are off-duty animations. Job icons show the actual status.">Lounge life · decorative</span>
  </div>;
}
export const STATE_WORDS: Record<RoleState, string> = {
  idle: "idle", working: "working", waiting: "waiting", retrying: "retrying", error: "stopped by an error",
  reviewing: "reviewing", paused: "paused", unavailable: "unavailable",
};
