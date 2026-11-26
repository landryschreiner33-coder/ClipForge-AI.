import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon, IconName } from "../components/ui";
import { useMotion } from "../motion";
import { BY_ID, CAST, CORE, RoomId, ROOM_NAMES, ROOM_SHORT } from "./cast";
import { OfficeEvent, RoleState, Snapshot } from "./api";
import { ROOM_ACCENT, ROOMS, roomOf, VIEW } from "./world";
import { Listener, LIVE_SECONDS } from "./useOffice";
import { OfficeMotion, placements, WorkCard } from "./OfficeMotion";
import SHIP from "../space/ship-world.json";
import { ZAP_MS } from "./taser";
import { HeldTaser, TaserBursts, TaserDock, useTaser } from "./TaserItem";
import type { StudioScene } from "./StudioScene";

export type Card = WorkCard;
export { placements } from "./OfficeMotion";
const NEXT_ROOM: Record<string, Partial<Record<string, RoomId>>> = {
  source: { approved: "editing", rejected: "intake", held: "story", rework: "story" },
  clip: { approved: "sound", rejected: "editing", rework: "editing", held: "editing" },
  qc: { approved: "publishing", rework: "editing", rejected: "editing", held: "quality" },
  upload: { approved: "publishing", held: "publishing", rejected: "publishing", rework: "publishing" },
};
const STATE_ICON: Record<RoleState, IconName> = {
  idle: "dot", working: "play", queued: "clock", waiting: "clock", retrying: "refresh", error: "alert",
  reviewing: "check", paused: "pause", unavailable: "x",
};
const DECISION_POSE = { approved: "approved", rework: "rework", rejected: "error", held: "wait" } as const;
const BREAK_WORDS: Record<string, string> = {
  arcade: "Playing an arcade game", boardgame: "Playing a tabletop game", snack: "Having a snack",
  drink: "Having a drink", read: "Reading", rest: "Relaxing",
};
const DUTY_WORDS = {
  work: "At work", supervising: "Supervising the department", support: "Ready in the department",
  break: "Off duty", quiet: "Present and inactive",
};
/** How long DOCK's beacon turns after a clip arrives for review. */
export const DOCK_CUE_MS = 4200;
const CORE_BOX = { x: SHIP.core.x - 47, y: SHIP.core.y - 43, w: 94, h: 86 };
const pct = (value: number, total: number) => `${value / total * 100}%`;

/** The ship is drawn on a canvas for looks; the robot, room and CORE buttons over it carry the real states, so a
 * keyboard or screen reader reaches everything the picture shows. `dockCue` is the time (performance.now) a clip was
 * seen arriving for review: DOCK acknowledges it once with its amber beacon. */
export default function OfficeMap({ snap, subscribe, selected, room, onRobot, onRoom, reduce, stale, dockCue = 0,
  tagsAlways = false, tools, simple = false }: {
  snap: Snapshot; subscribe: (fn: Listener) => () => void; skew: number; selected: string | null;
  room: RoomId | null; onRobot: (id: string, card: Card | null) => void; onRoom: (id: RoomId) => void;
  reduce: boolean; stale: boolean; dockCue?: number;
  /** show every robot's name (the expanded office); otherwise names show on hover, focus or selection */
  tagsAlways?: boolean;
  /** more controls for the row beneath the ship (the Studio page's Activity and Reduce motion) */
  tools?: ReactNode;
  /** the Studio page's quiet row: Whole ship and the caller's tools, without the robot count and state key */
  simple?: boolean;
}) {
  const wrap = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const { pageHidden, officeActivity, taser, sounds } = useMotion();
  // drawing stops while the ship is scrolled out of view
  const onScreen = useRef(true);
  const choreography = useRef<OfficeMotion | null>(null);
  if (!choreography.current) choreography.current = new OfficeMotion(snap);
  const motion = choreography.current;
  const buttons = useRef(new Map<string, HTMLButtonElement>()), world = useRef<HTMLDivElement>(null);
  // the Taser (an easter egg): pick it up from its charger, and a click on a robot zaps it instead of opening it
  const zapper = useTaser({ enabled: taser, sounds, robots: buttons, world, name: id => BY_ID[id]?.name || "The robot" });
  const zaps = zapper.fx.current;
  const brainLink = useRef<HTMLAnchorElement>(null), transferNote = useRef<HTMLSpanElement>(null);
  const pulses = useRef(new Map<RoomId, number>()), core = useRef(0), dockUntil = useRef(0);
  const coreConsulted = useRef<"consulting" | "consulted" | null>(null);
  const latest = useRef({ snap, selected, reduce, stale, pageHidden, officeActivity });
  latest.current = { snap, selected, reduce, stale, pageHidden, officeActivity };
  const cutoff = useRef(snap.cursor), suspendedSnapshot = useRef<Snapshot | null>(null);
  const [scale, setScale] = useState(1);
  const [renderer, setRenderer] = useState<"ship" | "plain">("ship");
  const [focus, setFocus] = useState<RoomId | "">("");
  const focused = focus ? ROOMS.find(r => r.id === focus) : null;
  const zoom = focused ? Math.min(VIEW.w / focused.w, VIEW.h / focused.h) * 0.84 : 1;
  const pan = focused ? `translate(${(VIEW.w / 2 - (focused.x - VIEW.x) - focused.w / 2) * scale * zoom}px, ${
    (VIEW.h / 2 - (focused.y - VIEW.y) - focused.h / 2) * scale * zoom}px)` : undefined;
  const rows = useMemo(() => Object.fromEntries(snap.roles.map(r => [r.id, r])), [snap.roles]);
  const resting = Object.values(placements(snap.roles)).filter(p => p.lounge).length;
  const ratio = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;

  useLayoutEffect(() => {
    const el = wrap.current!;
    const fit = () => {
      const w = el.clientWidth, h = el.clientHeight || w * VIEW.h / VIEW.w;
      const best = Math.max(0.2, Math.min(w / VIEW.w, h / VIEW.h));
      setScale(best >= 2 ? Math.floor(best) : best);
    };
    fit(); const observer = new ResizeObserver(fit); observer.observe(el);
    const seen = typeof IntersectionObserver === "function"
      ? new IntersectionObserver(([entry]) => { onScreen.current = entry.isIntersecting; }) : null;
    seen?.observe(el);
    return () => { observer.disconnect(); seen?.disconnect(); };
  }, []);

  useEffect(() => {
    cutoff.current = Math.max(cutoff.current, snap.cursor);
    const paused = ["paused", "pausing"].includes(snap.run.state);
    if (stale || pageHidden || paused) {
      suspendedSnapshot.current = snap;
      motion.clearTransfers();
      core.current = 0; coreConsulted.current = null; pulses.current.clear();
      if (paused && !stale && !pageHidden) motion.reconcile(snap, true);
      return;
    }
    if (suspendedSnapshot.current) {
      // Visibility/connection can recover before a fresh API snapshot arrives.
      if (snap === suspendedSnapshot.current) return;
      motion.resync(snap); cutoff.current = snap.cursor; suspendedSnapshot.current = null;
    }
    if (reduce || paused) { motion.clearTransfers(); core.current = 0; coreConsulted.current = null; }
    motion.reconcile(snap, reduce || paused);
  }, [snap, reduce, stale, pageHidden, motion]);

  // DOCK acknowledges a clip that arrived for review once: the beacon turns and DOCK shows its signal.
  useEffect(() => {
    if (!dockCue) return;
    const now = performance.now();
    if (now - dockCue > DOCK_CUE_MS) return;
    dockUntil.current = dockCue + DOCK_CUE_MS;
    if (!latest.current.stale) motion.react("dock", "approved", now);
  }, [dockCue, motion]);

  useEffect(() => subscribe((events: OfficeEvent[], serverTime: number) => {
    const current = latest.current;
    if (current.stale || current.pageHidden || suspendedSnapshot.current) return;
    const now = performance.now();
    const paused = ["paused", "pausing"].includes(current.snap.run.state);
    if (paused) return;
    motion.events(events, serverTime, now, current.reduce);
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
        coreConsulted.current = null;
        core.current = now + (event.type === "brain_lookup" ? 1800 : 3500);
      } else if (["brain_consultation_started", "brain_consultation_done"].includes(event.type)) {
        coreConsulted.current = event.type === "brain_consultation_started" ? "consulting" : "consulted";
        if (!current.reduce) core.current = now + 3500;
      } else if (event.type === "brain_consultation_failed") {
        core.current = 0; coreConsulted.current = null;
      }
    }
  }), [subscribe, motion]);

  useEffect(() => {
    const cv = canvas.current;
    let scene: StudioScene | null = null;
    let cancelled = false, raf = 0, wait = 0, last = performance.now(), drawn = 0;
    const frame = (now: number) => {
      if (!onScreen.current) {  // nothing to show: look again shortly, without drawing or animating
        last = now; wait = window.setTimeout(() => { raf = requestAnimationFrame(frame); }, 400); return;
      }
      const state = latest.current, dt = Math.min(0.1, (now - last) / 1000); last = now;
      const frozen = state.stale || state.pageHidden || suspendedSnapshot.current !== null
        || ["paused", "pausing"].includes(state.snap.run.state);
      const lowPower = state.officeActivity === "low_power";
      const still = state.reduce || frozen || lowPower;
      motion.tick(dt, now, state.reduce || lowPower, frozen, state.officeActivity === "full");
      // pixel crew step at about 12 frames a second; a still picture only needs to follow real changes. A Taser zap
      // plays smoothly, at 30 frames a second, even on a still ship (it is the person's own click).
      for (const [id, z] of zaps) if (state.reduce || now - z.start >= ZAP_MS[z.kind]) zaps.delete(id);
      const zapping = zaps.size > 0;
      if (drawn && now - drawn < (zapping ? 33 : still ? 250 : 83)) { raf = requestAnimationFrame(frame); return; }
      drawn = now;
      for (const [id, until] of pulses.current) if (until < now) pulses.current.delete(id);
      const actors = [...motion.actors.values()].sort((a, b) => a.y - b.y);
      const painted = actors.map(a => ({ id: a.id, x: a.x, y: a.y, dir: a.dir, pose: motion.pose(a),
        posture: motion.posture(a), duty: motion.duty(a), selected: state.selected === a.id,
        breakActivity: motion.breakActivity(a), breakPhase: motion.breakPhase(a), zap: zapOf(a.id, now) }));
      const consulting = state.snap.brain?.activity?.state === "working";
      const consulted = core.current > now && coreConsulted.current;
      const busy = core.current > now || consulting || state.snap.brain?.state === "evaluating"
        || state.snap.roles.some(r => BY_ID[r.id]?.room === "brain" && r.state === "working");
      const passes = motion.passes(now);
      scene?.draw(state.snap, painted, now, still, pulses.current, busy, state.stale, passes,
        { dockUntil: dockUntil.current });
      for (const a of actors) {
        const button = buttons.current.get(a.id); if (!button) continue;
        const posture = motion.posture(a), activity = motion.breakActivity(a);
        const height = posture === "rest" && activity ? 44 : 52;
        button.style.left = pct(a.x - 20 - VIEW.x, VIEW.w);
        button.style.top = pct(a.y - height - VIEW.y, VIEW.h);
        button.style.height = pct(height + 4, VIEW.h);
        button.dataset.pose = motion.pose(a); button.dataset.posture = posture;
        button.dataset.duty = motion.duty(a);
        button.dataset.room = roomOf(a)?.id || "corridor";
        button.dataset.carrying = a.card ? "true" : "false";
        button.dataset.offering = motion.isSender(a) ? "true" : "false";
        button.dataset.breakActivity = activity || "";
        button.dataset.breakPhase = motion.breakPhase(a).toFixed(3);
        button.dataset.breakSpot = motion.breakSpot(a) || "";
        button.title = `${BY_ID[a.id].name} · ${activity ? `${BREAK_WORDS[activity]} (lounge animation)`
          : DUTY_WORDS[motion.duty(a)]}`;
      }
      const brainMode = state.stale ? "offline" : frozen || state.snap.brain?.state === "paused"
        ? "paused" : busy ? "active" : "standby";
      if (brainLink.current) {
        brainLink.current.dataset.mode = brainMode;
        const word = brainMode === "active" && (consulting || consulted)
          ? consulting || coreConsulted.current === "consulting" ? "Consulting guidance" : "Consulted guidance"
          : { offline: "Offline", paused: "Paused", active: "Processing", standby: "Standby" }[brainMode];
        brainLink.current.setAttribute("aria-label", `${CORE.name}, Brain Core: ${word}. Open Brain workspace`);
        const label = brainLink.current.querySelector("span");
        if (label && label.textContent !== `${CORE.name} · ${word}`) label.textContent = `${CORE.name} · ${word}`;
      }
      const transfer = motion.activeTransfer(), note = transferNote.current;
      if (note) {
        note.dataset.phase = transfer?.phase || "idle";
        note.dataset.from = transfer?.from || ""; note.dataset.to = transfer?.to || "";
        note.dataset.job = transfer?.card.job_id || "";
        const label = transfer ? `${BY_ID[transfer.from].name} → ${BY_ID[transfer.to].name} · ${
          transfer.phase === "approach" ? "Bringing work" : transfer.phase === "pass"
            ? "Passing document" : "Received"}` : "";
        if (note.textContent !== label) note.textContent = label;
      }
      if (lowPower && !zapping) { wait = window.setTimeout(() => { raf = requestAnimationFrame(frame); }, 1000); return; }
      raf = requestAnimationFrame(frame);
    };
    const zapOf = (id: string, now: number) => {
      const z = zaps.get(id);
      return z ? { kind: z.kind, ms: now - z.start, seed: z.seed } : undefined;
    };
    const init = async () => {
      await Promise.resolve(); if (cancelled) return;
      if (renderer === "ship" && cv) {
        try {
          const module = await import("./StudioScene"); if (cancelled) return;
          scene = await module.StudioScene.create(cv);
          if (cancelled) { scene.destroy(); return; }
        } catch { if (!cancelled) setRenderer("plain"); return; }
      }
      raf = requestAnimationFrame(frame);
    };
    void init();
    return () => { cancelled = true; cancelAnimationFrame(raf); window.clearTimeout(wait); scene?.destroy(); };
  }, [renderer, motion, zaps]);

  const label = (id: string) => {
    const c = BY_ID[id], r = rows[id], task = r?.task?.message ? `: ${r.task.message}` : "";
    return `${c.name}, ${c.title}, ${stale ? "last known: " : ""}${STATE_WORDS[r?.state || "unavailable"]}${task}`;
  };
  const effective = scale * zoom * ratio;
  // A ship drawn about phone size: its rooms are too small for their full names (see space.css)
  const narrow = scale * zoom < 0.36;
  // On a bigger ship a name that can't fit its room on one line takes its one-word form too: a two-line sign reached
  // up over the robots' desks and down under the badges of the room below. A sign is Courier Prime (0.6 em a letter)
  // at max(11px, 14px × s), with 7px of padding and a 1px border on each side, in its room less 14 units (space.css).
  const signFont = Math.max(11, 14 * scale * zoom);
  const signText = (r: (typeof ROOMS)[number]) => narrow
    || ROOM_NAMES[r.id].length * 0.6 * signFont + 16 > (r.w - 14) * scale * zoom ? ROOM_SHORT[r.id] : ROOM_NAMES[r.id];
  return <div className="office-map-frame">
    <div className={`office-map${stale ? " stale" : ""}`} ref={wrap} data-narrow={narrow ? "true" : undefined}
      data-renderer={renderer} data-camera={focus || "office"} data-tags={tagsAlways || focus ? "all" : "chosen"}
      data-taser={zapper.held ? "held" : undefined} onPointerMove={zapper.track} onPointerDown={zapper.track}
      onPointerLeave={zapper.leave}>
      <div className="office-world" ref={world} data-smooth={effective < 1 ? "true" : "false"}
        style={{ width: VIEW.w * scale * zoom, height: VIEW.h * scale * zoom,
          transform: pan, ["--s" as string]: scale * zoom } as React.CSSProperties}>
        {renderer === "ship" && <canvas key={renderer} ref={canvas} width={VIEW.w} height={VIEW.h}
          aria-hidden="true" />}
        {ROOMS.map(r => <button key={r.id} type="button" className={`room-hit${room === r.id ? " on" : ""}`}
          style={{ left: pct(r.x - VIEW.x, VIEW.w), top: pct(r.y - VIEW.y, VIEW.h), width: pct(r.w, VIEW.w),
            height: pct(r.h, VIEW.h), ["--accent" as string]: ROOM_ACCENT[r.id] } as React.CSSProperties}
          aria-label={`${ROOM_NAMES[r.id]}${r.id === "lounge" ? `: ${resting} off duty` : ""}. Open details`}
          aria-pressed={room === r.id} onClick={event => (zapper.held ? zapper.miss(event) : onRoom(r.id))}>
          <span className="room-sign" aria-hidden="true">{signText(r)}</span>
        </button>)}
        <a ref={brainLink} href="#/brain" className="brain-core-hit" data-mode="standby"
          onClick={event => { if (zapper.held) { event.preventDefault(); zapper.miss(event); } }}
          aria-label={`${CORE.name}, Brain Core: Standby. Open Brain workspace`}
          style={{ left: pct(CORE_BOX.x - VIEW.x, VIEW.w), top: pct(CORE_BOX.y - VIEW.y, VIEW.h),
            width: pct(CORE_BOX.w, VIEW.w), height: pct(CORE_BOX.h, VIEW.h) }}>
          <span aria-hidden="true">{CORE.name} · Standby</span>
        </a>
        {CAST.map(c => <button key={c.id} type="button" className={`robot-hit${selected === c.id ? " on" : ""}`}
          ref={el => { if (el) buttons.current.set(c.id, el); else buttons.current.delete(c.id); }}
          style={{ width: pct(40, VIEW.w), height: pct(56, VIEW.h) }}
          aria-label={label(c.id)} aria-pressed={selected === c.id} data-id={c.id}
          data-state={rows[c.id]?.state || "unavailable"}
          onClick={event => (zapper.held ? zapper.zap(c.id, event.detail === 0)
            : onRobot(c.id, motion.actors.get(c.id)?.card || null))}>
          <span className={`robot-state state-${rows[c.id]?.state || "unavailable"}`} aria-hidden="true"
            title={stale ? "Last known state" : STATE_WORDS[rows[c.id]?.state || "unavailable"]}>
            <Icon name={STATE_ICON[rows[c.id]?.state || "unavailable"]} size={12} />
          </span>
          <span className="robot-tag" aria-hidden="true">{c.name}</span>
        </button>)}
        {taser && <TaserDock taser={zapper} />}
        <TaserBursts taser={zapper} />
      </div>
      {taser && <HeldTaser taser={zapper} width={Math.round(Math.max(60, Math.min(104, 76 * scale * zoom)))} />}
      {renderer === "plain" && <p className="ship-missing small">The ship pictures could not load. The rooms and
        robots below still work, and every robot is listed under Activity.</p>}
    </div>
    <div className={`office-map-legend${simple ? " simple" : ""}`} aria-label="Ship view and robot states">
      {!simple && <span>{CAST.length} robots · {stale ? "Last known states" : "Live job states"}</span>}
      <label className="office-camera"><span className="sr-only">Ship view</span><select aria-label="Ship view"
        value={focus} onChange={event => setFocus(event.target.value as RoomId | "")}>
        <option value="">Whole ship</option>
        {ROOMS.map(r => <option key={r.id} value={r.id}>{ROOM_NAMES[r.id]}</option>)}
      </select></label>
      {tools}
      {taser && <button type="button" className={`btn btn-ghost taser-btn${zapper.held ? " on" : ""}`}
        aria-pressed={zapper.held} onClick={() => (zapper.held ? zapper.putBack() : zapper.pickUp())}
        title={zapper.held ? "Click a robot to zap it. Escape or this button puts the Taser back on its charger."
          : "An easter egg: the Taser lies on its charger in the Control room. Pick it up and click a robot. Work "
          + "carries on."}>
        <Icon name="spark" size={14} />{zapper.held ? "Put the Taser back" : "Pick up the Taser"}</button>}
      <span className="sr-only" role="status" aria-live="polite">{zapper.said}</span>
      <span ref={transferNote} className="handoff-note" data-phase="idle" role="status" aria-live="polite" />
      {!simple && (["working", "queued", "waiting", "idle", "paused", "error"] as RoleState[]).map(state =>
        <span key={state} className="legend-state"><Icon name={STATE_ICON[state]} size={13} />
          {state[0].toUpperCase() + state.slice(1)}</span>)}
      <span className="lounge-life-caption"
        title="Games, snacks and drinks are off-duty animations. Job icons show the actual status.">
        Lounge life · decorative</span>
    </div>
  </div>;
}
export const STATE_WORDS: Record<RoleState, string> = {
  idle: "idle", working: "working", queued: "queued", waiting: "waiting", retrying: "retrying",
  error: "stopped by an error", reviewing: "reviewing", paused: "paused", unavailable: "unavailable",
};
