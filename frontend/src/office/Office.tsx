import { CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { ConfirmDialog, Icon, Toggle, toast } from "../components/ui";
import { useMotion } from "../motion";
import { AnimState, CoreActivity, Direction, RobotSprite, RoleId, roleById } from "../robots";
import { useStatus } from "../status";
import {
  LOUNGE_SHOWN, membersOf, place, Placement, RoomDef, RoomId, roomById, ROOMS, STATE_SHAPE, STATE_WORDS,
} from "./layout";
import { clockTime, destinationWords, localWhen, office, OfficeEvent, OfficeSnapshot } from "./officeApi";
import {
  HealthPill, OverviewPanel, RobotPanel, RoomPanel, StatePill, TaskProgress,
} from "./panels";
import { Room } from "./rooms";
import { useOfficeFeed } from "./useOfficeFeed";
import "./office.css";

/**
 * The Office: the robot crew at work in their rooms (reference image A), a detail panel on the right, and the
 * control bar. Robots stand where the snapshot says; the only motion added here is a short, cosmetic walk when a
 * worker report arrives live. That walk never blocks or decides anything and is skipped when reports come fast.
 */
type Selection = { kind: "robot"; role: RoleId } | { kind: "room"; id: RoomId } | null;
const LIST_KEY = "clipfoundry.officeList";

function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "true";
  } catch {
    return false;
  }
}
function writeFlag(key: string, value: boolean) {
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    /* private window or blocked storage: the choice lasts for this visit only */
  }
}

// ------------------------------------------------------------------ cosmetic movement
type Move = { x: number; y: number; ms: number; sprite: AnimState; dir: Direction; card: boolean };
const STEP_MS = 420;

function useMovement(reduced: boolean, stations: React.MutableRefObject<Map<RoleId, HTMLElement>>) {
  const [moves, setMoves] = useState<Partial<Record<RoleId, Move>>>({});
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const busy = useRef(new Set<RoleId>());
  const clearAll = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    busy.current.clear();
    setMoves({});
  }, []);
  useEffect(() => clearAll, [clearAll]);
  useEffect(() => {
    if (reduced) clearAll();
  }, [reduced, clearAll]);

  const onEvents = useCallback((batch: OfficeEvent[]) => {
    if (reduced || document.hidden) return;
    const reports = batch.filter((e) => e.type === "office.worker_report");
    // A burst means the office is behind: skip the walks and show the current state straight away.
    if (reports.length > 3) {
      clearAll();
      return;
    }
    for (const rep of reports) {
      const worker = roleById(rep.role);
      const manager = worker?.managerId ? roleById(worker.managerId) : undefined;
      if (!worker || !manager || worker.rank !== "worker") continue;
      const w = stations.current.get(worker.id);
      const m = stations.current.get(manager.id);
      if (!w || !m || busy.current.has(worker.id) || busy.current.has(manager.id)) continue;
      if (w.closest(".room") !== m.closest(".room")) continue; // only within one room: no long walks
      const a = w.getBoundingClientRect();
      const b = m.getBoundingClientRect();
      const toLeft = b.left < a.left;
      const dx = b.left - a.left + (toLeft ? 36 : -36);
      const dy = b.top - a.top;
      const review = batch.find((e) => e.type === "office.manager_review" && e.data?.worker === worker.id
        && e.job_id === rep.job_id);
      const verdict = String(review?.data?.review || "");
      const sendBack = verdict === "rework" || verdict === "escalated";
      const out: Direction = toLeft ? "left" : "right";
      const back: Direction = toLeft ? "right" : "left";
      busy.current.add(worker.id);
      busy.current.add(manager.id);
      const set = (role: RoleId, mv: Move | null) => setMoves((all) => {
        const next = { ...all };
        if (mv) next[role] = mv;
        else delete next[role];
        return next;
      });
      // Fixed waypoints: step into the aisle, walk along it, step up to the manager; then the way back.
      const plan: [number, () => void][] = [
        [0, () => set(worker.id, { x: 0, y: 10, ms: STEP_MS, sprite: "carry", dir: "down", card: true })],
        [STEP_MS, () => set(worker.id, { x: dx, y: 10, ms: STEP_MS * 2, sprite: "carry", dir: out, card: true })],
        [STEP_MS * 3, () => set(worker.id, { x: dx, y: dy, ms: STEP_MS, sprite: "carry", dir: "up", card: true })],
        [STEP_MS * 4, () => set(manager.id, { x: 0, y: 0, ms: 0, sprite: "review", dir: "down", card: true })],
        [STEP_MS * 6, () => {
          set(manager.id, { x: 0, y: 0, ms: 0, sprite: !verdict ? "idle" : sendBack ? "revise" : "approved",
            dir: "down", card: !sendBack });
          set(worker.id, { x: dx, y: 10, ms: STEP_MS, sprite: sendBack ? "carry" : "walk", dir: back, card: sendBack });
        }],
        [STEP_MS * 7, () => set(worker.id, { x: 0, y: 10, ms: STEP_MS * 2, sprite: sendBack ? "carry" : "walk",
          dir: back, card: sendBack })],
        [STEP_MS * 9, () => set(worker.id, { x: 0, y: 0, ms: STEP_MS, sprite: "walk", dir: "up", card: false })],
        [STEP_MS * 10, () => {
          set(worker.id, null);
          set(manager.id, null);
          busy.current.delete(worker.id);
          busy.current.delete(manager.id);
        }],
      ];
      for (const [delay, fn] of plan) timers.current.push(setTimeout(fn, delay));
    }
  }, [reduced, clearAll, stations]);
  return { moves, onEvents };
}

// ------------------------------------------------------------------ the page
export default function OfficePage() {
  const feed = useOfficeFeed();
  const { snap, events, lost, lastOk } = feed;
  const { reduceMotion, setReduceMotion, preferredReduceMotion, systemReducedMotion } = useMotion();
  const [list, setList] = useState(() => readFlag(LIST_KEY));
  const [sel, setSel] = useState<Selection>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const stations = useRef(new Map<RoleId, HTMLElement>());
  const panelRef = useRef<HTMLElement>(null);
  const { moves, onEvents } = useMovement(reduceMotion, stations);
  const { setLiveListener } = feed;
  useEffect(() => {
    setLiveListener(onEvents);
    return () => setLiveListener(null);
  }, [setLiveListener, onEvents]);

  const placements = useMemo(() => (snap ? snap.robots.map((r) => place(r, snap.run_state))
    .filter((p): p is Placement => !!p) : []), [snap]);
  const byRole = useMemo(() => new Map(placements.map((p) => [p.role, p])), [placements]);

  const select = (s: Selection) => {
    setSel(s);
    setPanelOpen(true);
    // On a narrow screen the panel sits below the cards: bring it into view.
    if (s && window.innerWidth < 900) setTimeout(() => panelRef.current?.scrollIntoView({ block: "start" }), 0);
  };
  const openRobot = (role: RoleId) => select({ kind: "robot", role });
  const openRoom = (id: RoomId) => select(sel?.kind === "room" && sel.id === id ? null : { kind: "room", id });

  const selectedPlacement = sel?.kind === "robot" ? byRole.get(sel.role) : undefined;
  const selectedRoom = sel?.kind === "room" ? roomById(sel.id) : undefined;
  const since = lastOk ? clockTime(lastOk / 1000) : "";

  return (
    <div className={`office-page ${panelOpen ? "" : "panel-closed"} ${list ? "is-list" : ""} ${lost ? "is-lost" : ""}`}>
      <div className="office-toolbar">
        <h1 tabIndex={-1} className="office-title">Office</h1>
        {lost ? (
          <span className="stale-note" role="status"><Icon name="offline" />
            Connection lost, data may be stale{since ? ` (last update ${since})` : ""}.
            <button type="button" className="textlink" onClick={feed.reload}>Try again</button></span>
        ) : !snap ? <span className="small muted" role="status">Loading the office…</span> : null}
        <span className="grow" />
        <a className="btn btn-small btn-quiet" href="#/team"><Icon name="user" />Team</a>
        <Toggle on={list} onChange={(v) => { setList(v); writeFlag(LIST_KEY, v); }} label="List view" />
        <Toggle on={preferredReduceMotion || systemReducedMotion} disabled={systemReducedMotion}
          onChange={setReduceMotion} label="Reduce animations" />
        {!panelOpen && (
          <button type="button" className="btn btn-small" onClick={() => setPanelOpen(true)}>Show details</button>
        )}
      </div>

      <div className={`office-stage ${lost ? "is-stale" : ""}`}>
        {!snap ? (
          <div className="office-loading" aria-busy="true">{feed.error && lost ? `ClipFoundry is not answering: `
            + feed.error : "Waiting for data."}</div>
        ) : (
          <>
            <OfficeMap snap={snap} placements={placements} sel={sel} moves={moves} reduced={reduceMotion}
              lost={lost} stations={stations} openRobot={openRobot} openRoom={openRoom} />
            <OfficeList snap={snap} placements={placements} lost={lost} reduced={reduceMotion}
              openRobot={openRobot} openRoom={openRoom} />
          </>
        )}
      </div>

      <aside ref={panelRef} className="office-panel" aria-label="Details" hidden={!panelOpen}>
        <div className="dp-head">
          <h2 className="dp-title">{selectedPlacement ? "Robot" : selectedRoom ? selectedRoom.label : "Studio"}</h2>
          {sel && <button type="button" className="btn btn-small btn-quiet" onClick={() => setSel(null)}>
            <Icon name="back" />Overview</button>}
          <button type="button" className="btn btn-small btn-quiet btn-icon" aria-label="Hide details"
            onClick={() => setPanelOpen(false)}><Icon name="x" /></button>
        </div>
        <div className="dp-body">
          {snap && selectedPlacement ? (
            <RobotPanel p={selectedPlacement} snap={snap} lost={lost} events={events} reduced={reduceMotion}
              onRobot={openRobot} />
          ) : snap && selectedRoom ? (
            <RoomPanel room={selectedRoom} snap={snap} placements={placements} events={events} lost={lost}
              reduced={reduceMotion} onRobot={openRobot} refresh={feed.reload} />
          ) : (
            <OverviewPanel snap={snap} events={events} lost={lost} onRobot={openRobot} />
          )}
        </div>
      </aside>

      <ControlBar snap={snap} lost={lost} reload={feed.reload} />
    </div>
  );
}

// ------------------------------------------------------------------ the map
function OfficeMap({ snap, placements, sel, moves, reduced, lost, stations, openRobot, openRoom }: {
  snap: OfficeSnapshot; placements: Placement[]; sel: Selection; moves: Partial<Record<RoleId, Move>>;
  reduced: boolean; lost: boolean; stations: React.MutableRefObject<Map<RoleId, HTMLElement>>;
  openRobot: (r: RoleId) => void; openRoom: (r: RoomId) => void;
}) {
  const byRole = new Map(placements.map((p) => [p.role, p]));
  const lounge = placements.filter((p) => p.room === "lounge");
  const brainBusy = ["curator", "metric", "synapse"].some((r) => byRole.get(r as RoleId)?.robot.state === "working");
  const core: CoreActivity = snap.brain.state === "Evaluating" ? "evaluating" : brainBusy ? "lookup" : "idle";
  const station = (p: Placement) => (
    <Station key={p.role} p={p} move={moves[p.role]} selected={sel?.kind === "robot" && sel.role === p.role}
      reduced={reduced} lost={lost} onOpen={() => openRobot(p.role)}
      refFn={(el) => (el ? stations.current.set(p.role, el) : stations.current.delete(p.role))} />
  );
  const roomOf = (room: RoomDef) => {
    if (room.id === "lounge") {
      const shown = lounge.slice(0, LOUNGE_SHOWN);
      const more = lounge.length - shown.length;
      return (
        <Room key={room.id} room={room} selected={sel?.kind === "room" && sel.id === room.id} reduced={reduced}
          dim={lost} onOpen={() => openRoom(room.id)}
          count={lounge.length && !lost ? `${lounge.length} resting` : undefined}>
          {shown.map(station)}
          {more > 0 && (
            <button type="button" className="more-chip" onClick={() => openRoom("lounge")}
              aria-label={`${more} more robots resting: show the list`}>+{more}</button>
          )}
        </Room>
      );
    }
    const members = membersOf(room.id);
    const here = members.map((r) => byRole.get(r)).filter((p): p is Placement => !!p && p.room === room.id);
    const working = here.filter((p) => p.robot.state === "working").length;
    return (
      <Room key={room.id} room={room} selected={sel?.kind === "room" && sel.id === room.id} reduced={reduced}
        dim={lost} onOpen={() => openRoom(room.id)} core={room.id === "brain" ? core : undefined}
        count={working && !lost ? `${working} working` : undefined}>
        {members.map((r) => {
          const p = byRole.get(r);
          // A robot resting in the Lounge leaves its desk empty, so the room keeps its shape.
          return p && p.room === room.id ? station(p) : (
            <div key={r} className={`station rank-${roleById(r)?.rank} is-empty`} aria-hidden="true">
              <span className="desk" />
            </div>
          );
        })}
        {room.id === "team" && <span className="room-note">Handoffs</span>}
        {room.id === "devlog" && <span className="room-note">Read-only history</span>}
      </Room>
    );
  };
  return (
    <div className="office-map" role="group" aria-label="Office map: rooms and robots">
      {ROOMS.map(roomOf)}
    </div>
  );
}

function Station({ p, move, selected, reduced, lost, onOpen, refFn }: {
  p: Placement; move?: Move; selected: boolean; reduced: boolean; lost: boolean; onOpen: () => void;
  refFn: (el: HTMLElement | null) => void;
}) {
  const role = roleById(p.role)!;
  const r = p.robot;
  const task = r.task && r.task.job_id ? r.task : null; // a card only for a real job
  const sprite: AnimState = lost ? "unavailable" : move?.sprite || p.sprite;
  const card = move ? move.card : !!task;
  const style: CSSProperties | undefined = move ? {
    transform: `translate(${move.x}px, ${move.y}px)`, transition: `transform ${move.ms}ms linear`, zIndex: 5,
  } : undefined;
  const words = lost ? "state unknown (connection lost)" : `${STATE_WORDS[r.state]}${task ? `: ${task.label
    || task.stage}` : ""}`;
  return (
    <div className={`station rank-${role.rank} ${p.room === "lounge" ? "in-lounge" : ""}`} ref={refFn}>
      {p.room !== "lounge" && <span className="desk" aria-hidden="true" />}
      <button type="button" className={`bot state-${r.state} ${selected ? "is-selected" : ""}`} style={style}
        aria-pressed={selected} onClick={onOpen} aria-label={`${role.name}, ${role.job}: ${words}`}
        title={`${role.name} · ${role.job}\n${words}`}>
        <RobotSprite role={p.role} scale={1} state={sprite} dir={move?.dir || "down"} card={card ? undefined : false}
          reducedMotion={reduced} />
        <span className="bot-tag" aria-hidden="true">{role.name}</span>
        {!lost && r.state !== "idle" && r.state !== "lounge" && (
          <span className={`bot-mark mark-${r.state}`} aria-hidden="true">{STATE_SHAPE[r.state]}</span>
        )}
        {r.queued > 1 && <span className="bot-count" aria-hidden="true">×{r.queued}</span>}
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ list view / narrow screens
function OfficeList({ snap, placements, lost, reduced, openRobot, openRoom }: {
  snap: OfficeSnapshot; placements: Placement[]; lost: boolean; reduced: boolean;
  openRobot: (r: RoleId) => void; openRoom: (r: RoomId) => void;
}) {
  const byRole = new Map(placements.map((p) => [p.role, p]));
  const lounge = placements.filter((p) => p.room === "lounge");
  const rooms = ROOMS.filter((r) => membersOf(r.id).length || r.id === "lounge" || r.id === "devlog"
    || r.id === "team");
  return (
    <div className="office-list" aria-label="Office as a list">
      {rooms.map((room) => {
        const crew = room.id === "lounge" ? lounge : membersOf(room.id).map((r) => byRole.get(r))
          .filter((p): p is Placement => !!p);
        if (room.id === "lounge" && !crew.length) return null;
        return (
          <section key={room.id} className="dept-card" style={{ "--accent": room.color } as CSSProperties}
            aria-labelledby={`dc-${room.id}`}>
            <h2 id={`dc-${room.id}`} className="dept-card-h">
              <button type="button" className="room-sign" onClick={() => openRoom(room.id)}>{room.label}</button>
            </h2>
            {crew.length ? (
              <ul className="dept-crew">
                {crew.map((p) => {
                  const role = roleById(p.role)!;
                  const t = p.robot.task && p.robot.task.job_id ? p.robot.task : null;
                  return (
                    <li key={p.role}>
                      <button type="button" className="dept-row" onClick={() => openRobot(p.role)}>
                        <RobotSprite role={p.role} scale={1} card={t ? undefined : false} reducedMotion={reduced}
                          state={lost ? "unavailable" : p.sprite} />
                        <span className="stack grow">
                          <span><b>{role.name}</b> <span className="muted small">· {role.job}</span></span>
                          {lost ? <span className="small muted">State unknown</span>
                            : <StatePill state={p.robot.state} />}
                          {t && <span className="small">{t.label || t.stage}
                            {t.message ? ` · ${t.message}` : ""}</span>}
                          {t && p.robot.state === "working" && <TaskProgress value={t.progress} label={t.label} />}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="small muted">{room.id === "devlog" ? "Development history (read-only)."
                : room.id === "team" ? "Handoffs between robots show in the activity list."
                  : room.id === "lounge" ? "" : "Everyone here is resting in the Lounge."}</p>
            )}
            {room.id !== "lounge" && crew.length > 0 && crew.every((p) => p.room === "lounge") && (
              <p className="tiny muted">Resting in the Lounge while Autopilot is {snap.run_state}.</p>
            )}
          </section>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ control bar
function ControlBar({ snap, lost, reload }: { snap: OfficeSnapshot | null; lost: boolean; reload: () => void }) {
  const { refresh, st } = useStatus();
  const [busy, setBusy] = useState("");
  const [stopping, setStopping] = useState(false);
  const act = async (action: string, done: string) => {
    setBusy(action);
    try {
      await office.control(action);
      toast(done);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy("");
    reload();
    refresh();
  };
  const run = snap?.run_state;
  const known = !!snap && !lost;
  const needs = lost ? null : st ? st.home.needs_you.length : snap ? snap.needs_you.length : null;
  const RUN_WORD = { running: "Running", paused: "Paused", stopped: "Stopped" } as const;
  const RUN_SHAPE = { running: "▶", paused: "⏸", stopped: "■" } as const;
  return (
    <section className="control-bar" aria-label="Autopilot controls and today's summary">
      <div className="cb-group">
        <span className="cb-label">Autopilot</span>
        {known && run ? (
          <span className={`pill ${run === "running" ? "good" : run === "paused" ? "warn" : "neutral"}`}>
            <span aria-hidden="true" className="state-shape">{RUN_SHAPE[run]}</span>{RUN_WORD[run]}</span>
        ) : <span className="pill neutral"><Icon name="question" />Unknown</span>}
        {known && run === "stopped" && (
          <button type="button" className="btn btn-small btn-primary" disabled={!!busy}
            onClick={() => act("start", "Autopilot started")}><Icon name="play" />Start</button>
        )}
        {known && run === "running" && (
          <button type="button" className="btn btn-small" disabled={!!busy}
            onClick={() => act("pause", "Autopilot paused: no new work starts")}><Icon name="pause" />Pause</button>
        )}
        {known && run === "paused" && (
          <button type="button" className="btn btn-small btn-primary" disabled={!!busy}
            onClick={() => act("resume", "Autopilot resumed")}><Icon name="play" />Resume</button>
        )}
        {known && run !== "stopped" && (
          <button type="button" className="btn btn-small btn-danger" disabled={!!busy}
            onClick={() => setStopping(true)}><Icon name="stop" />Stop</button>
        )}
        {known && (
          <button type="button" className="btn btn-small btn-quiet" disabled={!!busy}
            onClick={() => act(snap!.publishing_paused ? "resume_publishing" : "pause_publishing",
              snap!.publishing_paused ? "Publishing resumed" : "Publishing paused: clips are still made")}>
            <Icon name={snap!.publishing_paused ? "upload" : "pause"} />
            {snap!.publishing_paused ? "Resume publishing" : "Pause publishing"}
          </button>
        )}
      </div>
      <div className="cb-group cb-mission">
        <span className="cb-label">Current mission</span>
        <span className="cb-value clamp-1"
          title={known ? `${snap!.mission.title}. ${snap!.mission.detail}` : undefined}>
          {known ? snap!.mission.title : "Unknown"}</span>
      </div>
      <div className="cb-group">
        <span className="cb-label">Health</span>
        <HealthPill state={snap?.health.state} lost={lost} />
      </div>
      <div className="cb-group">
        <span className="cb-label">Today</span>
        <span className="cb-value tnum">{known ? `${snap!.today.clips_made} clips · ${snap!.today.uploads} uploads`
          : "—"}</span>
      </div>
      <div className="cb-group">
        <span className="cb-label">Next eligible upload</span>
        <span className="cb-value tnum">{!known ? "—" : snap!.next_upload ? localWhen(snap!.next_upload.planned_at)
          : "None planned"}</span>
      </div>
      <div className="cb-group">
        <span className="cb-label">Needs you</span>
        {needs === null ? <span className="cb-value">—</span> : needs ? (
          <span className="pill warn"><Icon name="alert" />{needs}</span>
        ) : <span className="cb-value">0</span>}
      </div>
      <div className="cb-group cb-audience">
        <span className="cb-label"><Icon name="shield" className="sm" />Selected audience</span>
        <span className="cb-value small">{snap ? `${destinationWords("youtube", snap.audience.youtube)} · `
          + destinationWords("tiktok", snap.audience.tiktok) : "—"}</span>
      </div>
      {stopping && (
        <ConfirmDialog title="Stop Autopilot?" danger confirmLabel="Stop" cancelLabel="Keep running"
          onClose={() => setStopping(false)} onConfirm={() => act("stop", "Autopilot stopped")}>
          <p className="muted">All background jobs are put on hold and Autopilot turns off. Nothing is deleted; the
            held work continues after you press Start.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
