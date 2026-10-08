import { useEffect, useState } from "react";
import { errorText } from "../api";
import { Banner, ConfirmDialog, Icon, toast } from "../components/ui";
import { useMotion } from "../motion";
import { useStatus } from "../status";
import { BY_ID, RoomId, ROOM_NAMES } from "../office/cast";
import { Control, office, Snapshot } from "../office/api";
import { useOffice } from "../office/useOffice";
import OfficeMap, { Card } from "../office/OfficeMap";
import { ActivityPanel, DepartmentCards, HealthBadge, OverviewPanel, RobotPanel, RoomPanel } from "../office/panels";
import { ROOM_ACCENT } from "../office/draw";

/**
 * Office: the robot office (layout of reference image A) over the real job system. The map shows where work is,
 * the right panel explains a selected robot or room, and the bottom bar has the controls that fit the current state.
 */
type Sel = { type: "robot"; id: string; card: Card | null } | { type: "room"; id: RoomId } | { type: "activity" } | null;
const VIEW_KEY = "clipfoundry.officeView";

function storedView(): "map" | "list" {
  try {
    const v = window.localStorage.getItem(VIEW_KEY);
    if (v === "map" || v === "list") return v;
  } catch {
    /* no storage: the default below */
  }
  return window.matchMedia?.("(max-width: 760px)").matches ? "list" : "map";
}

export default function Office() {
  const feed = useOffice();
  const { st } = useStatus();
  const { reduceMotion, setReduceMotion, systemReducedMotion } = useMotion();
  const [sel, setSel] = useState<Sel>(null);
  const [view, setViewState] = useState<"map" | "list">(storedView);
  const setView = (v: "map" | "list") => {
    setViewState(v);
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* the choice lasts for this visit */
    }
  };
  const snap = feed.snap;
  const onRobot = (id: string, card: Card | null = null) => setSel({ type: "robot", id, card });
  const onRoom = (id: RoomId) => setSel({ type: "room", id });

  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && sel && !document.querySelector(".modal-bg, .dialog")) setSel(null);
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [sel]);

  if (!snap) {
    return (
      <div className="office-page">
        <h1 className="sr-only" tabIndex={-1}>Office</h1>
        {feed.error ? (
          <Banner tone="warn" title="The office could not load" actions={<button type="button" className="btn btn-small" onClick={() => feed.reload().catch(() => {})}><Icon name="refresh" />Try again</button>}>
            {feed.error}
          </Banner>
        ) : <p className="muted">Opening the office…</p>}
      </div>
    );
  }

  const title = sel?.type === "robot" ? BY_ID[sel.id]?.name : sel?.type === "room" ? ROOM_NAMES[sel.id]
    : sel?.type === "activity" ? "Activity" : "Today";
  const accent = sel?.type === "room" ? ROOM_ACCENT[sel.id] : sel?.type === "robot" ? BY_ID[sel.id]?.palette.trim : undefined;
  const setupNeeded = !!st && !st.home.setup.started && snap.run.state === "stopped";

  return (
    <div className="office-page">
      <h1 className="sr-only" tabIndex={-1}>Office</h1>
      {feed.lost && (
        <Banner tone="warn" icon="offline" title="The office is not updating">
          What you see is the last known state{feed.lastOk ? `, from ${new Date(feed.lastOk).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}. It catches up as soon as ClipFoundry answers again.
        </Banner>
      )}
      <div className={`office-body${sel ? "" : " overview"}`}>
        <section className="office-stage" aria-label="The office">
          <div className="office-tools">
            <div className="seg" role="group" aria-label="Show the office as">
              <button type="button" className={view === "map" ? "on" : ""} aria-pressed={view === "map"} onClick={() => setView("map")}><Icon name="dashboard" />Map</button>
              <button type="button" className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => setView("list")}><Icon name="menu" />List</button>
            </div>
            <label className="check-inline small">
              <input type="checkbox" checked={reduceMotion} disabled={systemReducedMotion}
                onChange={(e) => setReduceMotion(e.target.checked)} />
              Reduce animations{systemReducedMotion ? " (set by Windows)" : ""}
            </label>
            <span className="spacer" />
            <button type="button" className="btn btn-small btn-quiet" aria-pressed={sel?.type === "activity"} onClick={() => setSel(sel?.type === "activity" ? null : { type: "activity" })}><Icon name="clock" />Activity</button>
            <a className="btn btn-small btn-quiet" href="#/office/team"><Icon name="user" />Team</a>
          </div>
          {view === "map" ? (
            <OfficeMap snap={snap} subscribe={feed.subscribe} skew={feed.skew} reduce={reduceMotion}
              selected={sel?.type === "robot" ? sel.id : null} room={sel?.type === "room" ? sel.id : null}
              onRobot={onRobot} onRoom={onRoom} stale={feed.lost} />
          ) : (
            <DepartmentCards snap={snap} onRobot={(id) => onRobot(id)} onRoom={onRoom} />
          )}
        </section>
        <aside className="office-panel" aria-label="Details" style={accent ? { ["--accent" as string]: accent } as React.CSSProperties : undefined}>
          <div className="op-head">
            <h2>{title}</h2>
            {sel?.type === "robot" && snap.roles.find((r) => r.id === sel.id)?.state === "working" && <span className="pill info"><Icon name="play" />Working</span>}
            <span className="spacer" />
            {sel && <button type="button" className="btn btn-small btn-icon btn-quiet" aria-label="Close details" onClick={() => setSel(null)}><Icon name="x" /></button>}
          </div>
          {sel?.type === "robot" ? (
            <RobotPanel key={sel.id} id={sel.id} row={snap.roles.find((r) => r.id === sel.id)} card={sel.card} onRobot={(id) => onRobot(id)} />
          ) : sel?.type === "room" ? (
            <RoomPanel key={sel.id} id={sel.id} snap={snap} onRobot={(id) => onRobot(id)} />
          ) : sel?.type === "activity" ? (
            <ActivityPanel events={feed.events} skew={feed.skew} onRobot={(id) => onRobot(id)} />
          ) : (
            <OverviewPanel snap={snap} skew={feed.skew} events={feed.events} onRobot={(id) => onRobot(id)} onRoom={onRoom} setupNeeded={setupNeeded} />
          )}
        </aside>
      </div>
      <ControlBar snap={snap} onSnap={feed.setSnap} onRoom={onRoom} />
    </div>
  );
}

// ------------------------------------------------------------------ the bottom bar
const RUN_TONE = { running: "good", paused: "warn", stopped: "bad" } as const;
const RUN_ICON = { running: "play", paused: "pause", stopped: "stop" } as const;

export function ControlBar({ snap, onSnap, onRoom }: { snap: Snapshot; onSnap: (s: Snapshot) => void; onRoom: (id: RoomId) => void }) {
  const [busy, setBusy] = useState(false);
  const [askStop, setAskStop] = useState(false);
  const run = snap.run;
  const act = async (a: Control) => {
    setBusy(true);
    try {
      onSnap(await office.control(a));
      toast({ start: "Autopilot started", resume: "Autopilot resumed", pause: "Autopilot paused", stop: "Everything is stopped",
        pause_publishing: "Publishing paused", resume_publishing: "Publishing resumed" }[a]);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const working = snap.roles.filter((r) => r.state === "working" && r.task && BY_ID[r.id]?.rank === "worker");
  const mission = working[0];
  const gpu = snap.health.checks.find((c) => c.id === "gpu");
  return (
    <div className="control-bar" role="region" aria-label="Autopilot controls">
      <div className="cb-group">
        <b className="cb-title">Autopilot</b>
        <span className={`pill ${RUN_TONE[run.state]}`} id="office-run-state"><Icon name={RUN_ICON[run.state]} />{run.label}</span>
        {run.actions.includes("start") && <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => act("start")}><Icon name="play" />Start</button>}
        {run.actions.includes("resume") && <button type="button" className="btn btn-primary btn-small" disabled={busy} onClick={() => act("resume")}><Icon name="play" />Resume</button>}
        {run.actions.includes("pause") && <button type="button" className="btn btn-small" disabled={busy} onClick={() => act("pause")}><Icon name="pause" />Pause</button>}
        {run.actions.includes("stop") && <button type="button" className="btn btn-danger btn-small" disabled={busy} onClick={() => setAskStop(true)}><Icon name="stop" />Stop all</button>}
      </div>
      <div className="cb-group cb-mission">
        <Icon name="spark" />
        <span className="grow"><span className="tiny muted block">Current mission</span>
          <span className="small">{mission ? `${BY_ID[mission.id].name}: ${mission.task!.message || "working"}` : "Nothing running"}</span></span>
      </div>
      <div className="cb-group">
        <button type="button" className="link-btn small" onClick={() => onRoom("system")} title={gpu?.reason}>
          <Icon name="cpu" /> GPU: {gpu ? <HealthBadge status={gpu.status} label={gpu.status === "healthy" ? "Ready" : gpu.status_label} /> : "—"}
        </button>
        <button type="button" className="btn btn-small btn-quiet" disabled={busy}
          aria-pressed={run.publishing_paused} onClick={() => act(run.publishing_paused ? "resume_publishing" : "pause_publishing")}>
          <Icon name={run.publishing_paused ? "play" : "pause"} />{run.publishing_paused ? "Resume publishing" : "Pause publishing"}
        </button>
      </div>
      <div className="cb-group cb-audience">
        <Icon name="shield" /><span className="small">{snap.audience.footer}</span>
      </div>
      {askStop && (
        <ConfirmDialog title="Stop all work?" confirmLabel="Stop all" danger onConfirm={() => act("stop")} onClose={() => setAskStop(false)}>
          <p>Queued work is canceled and held, and running steps stop at their next safe point. Nothing is uploaded until you start again. Your clips and posts stay.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
