import { useEffect, useId, useRef, useState } from "react";
import { AutopilotStatus, NeedsYouItem, WorkerRow } from "../autopilot";
import { useStatus } from "../status";
import { Desk, OfficeBackdrop, RobotArt } from "./RobotArt";
import { Icon, ProgressBar } from "./ui";

export type StationKind = "finder" | "editor" | "checker" | "scheduler";
export type StationState = "working" | "waiting" | "paused" | "attention" | "completed" | "disconnected" | "stopped";
const STATIONS: { kind: StationKind; label: string; task: string }[] = [
  { kind: "finder", label: "Finder", task: "Finding videos" },
  { kind: "editor", label: "Editor", task: "Making clips" },
  { kind: "checker", label: "Checker", task: "Checking clips" },
  { kind: "scheduler", label: "Scheduler", task: "Planning posts" },
];
const JOB_STATION: Record<string, StationKind> = {
  trend_scan: "finder", source_scout: "finder", feed_scan: "finder", identify_link: "finder", live_watch: "finder",
  hunt_source: "editor", analyze_source: "editor", regenerate_clip: "editor", live_capture: "editor", post_live: "editor",
  package_clip: "editor", rights_check: "checker", quality_check: "checker", maintenance: "checker", selftest: "checker",
  schedule_tick: "scheduler", publish: "scheduler", learn: "scheduler",
};
const WORKER_STATION: Record<string, StationKind> = {
  trend_scout: "finder", source_scout: "finder", rights_gate: "checker", live_monitor: "editor",
  clip_hunter: "editor", analyzer: "editor", packager: "editor", quality_gate: "checker",
  scheduler: "scheduler", publisher: "scheduler", learner: "scheduler", maintenance: "checker",
};
const NOTICE_STATION: Record<string, StationKind> = {
  account: "scheduler", publish: "scheduler", approve: "scheduler", rights: "checker", file: "finder",
  videos: "finder", gpu: "editor", sleep: "editor", stopped: "editor", other: "checker",
};
export const stationForWorker = (w: WorkerRow): StationKind =>
  JOB_STATION[w.job_kind || ""] || WORKER_STATION[w.name] || "checker";

type Station = { state: StationState; message: string; workers: WorkerRow[]; notice?: NeedsYouItem };
/** A station rests unless the current response confirms an active, fresh job. Failures remain in Activity. */
export function stationStatus(kind: StationKind, st: AutopilotStatus | null, lost: boolean): Station {
  const workers = (st?.workers.workers || []).filter((w) => stationForWorker(w) === kind);
  if (!st || lost) return { state: "disconnected", message: "Connection lost. Activity cannot be confirmed.", workers };
  if (st.paused) return { state: "stopped", message: "All jobs stopped. Resume jobs to continue.", workers };
  if (!st.enabled) return { state: "paused", message: st.home.setup.started
    ? "Autopilot paused. Nothing new starts automatically." : "Ready when you set up Autopilot.", workers };
  if (!st.workers.host.alive) return { state: "stopped", message: "Background work is not running. See Needs you.", workers };
  const working = workers.filter((w) => w.status === "working" && !w.stale);
  if (working.length) return { state: "working", message: working.map((w) => w.message || w.stage
    || STATIONS.find((s) => s.kind === kind)!.task).join(" · "), workers };
  const notice = st.home.needs_you.find((n) => NOTICE_STATION[n.type] === kind);
  if (notice) return { state: "attention", message: notice.title, notice, workers };
  const waiting = workers.find((w) => w.status === "waiting" && !w.stale);
  const nextSearch = st.home.discovery.next_scan || st.home.next_look;
  const discoveryWait = nextSearch && nextSearch * 1000 > Date.now()
    ? `Next search ${clock(nextSearch, st.timezone)}.` : "Waiting for the next search.";
  return { state: "waiting", message: waiting?.message || (kind === "finder"
    ? discoveryWait : kind === "editor" ? "Waiting for a video to work on."
      : kind === "checker" ? "Waiting for the next clip to check." : "Waiting for a post to plan or send."), workers };
}
const STATE_WORD: Record<StationState, string> = {
  working: "Working", waiting: "Waiting", paused: "Paused", attention: "Needs you", completed: "Completed",
  disconnected: "Disconnected", stopped: "Stopped",
};
const clock = (at: number | null | undefined, tz: string) => at
  ? new Date(at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: tz }) : "Not yet";

function StationView({ kind, label, task, status, selected, onSelect, panelId }: {
  kind: StationKind; label: string; task: string; status: Station; selected: boolean; onSelect: () => void;
  panelId: string;
}) {
  const [success, setSuccess] = useState(false);
  const previous = useRef<Record<string, { status: string; job: string }>>({});
  useEffect(() => {
    const completed = status.workers.some((w) => w.status === "completed" && previous.current[w.name]?.status === "working"
      && previous.current[w.name]?.job === w.job_id);
    previous.current = Object.fromEntries(status.workers.map((w) => [w.name, { status: w.status, job: w.job_id }]));
    if (!completed || status.state !== "waiting") { setSuccess(false); return; }
    setSuccess(true);
    const timer = setTimeout(() => setSuccess(false), 1400);
    return () => clearTimeout(timer);
  }, [status.workers.map((w) => `${w.name}:${w.status}:${w.job_id}`).join("|"), status.state]);
  const state = success ? "completed" : status.state;
  return (
    <button type="button" className={`robot-station station-${kind}`} data-state={state}
      aria-expanded={selected} aria-controls={panelId} onClick={onSelect}>
      <div className="station-art" aria-hidden="true">
        <RobotArt kind={kind} state={state} />
        <Desk kind={kind} />
        {state === "attention" && <span className="station-notice"><Icon name="alert" /></span>}
        {state === "completed" && <span className="station-notice"><Icon name="check" /></span>}
      </div>
      <span className="station-name">{label}</span>
      <span className="station-task">{task}</span>
      <span className="station-state"><span className="station-dot" aria-hidden="true" />{STATE_WORD[state]}</span>
      <span className="station-message">{status.message}</span>
    </button>
  );
}

export default function RobotOffice({ compact = false }: { compact?: boolean }) {
  const { st, lost } = useStatus();
  const [selected, setSelected] = useState<StationKind | null>(null);
  const id = useId();
  const statuses = Object.fromEntries(STATIONS.map((s) => [s.kind, stationStatus(s.kind, st, lost)])) as Record<StationKind, Station>;
  const current = selected ? statuses[selected] : null;
  return (
    <section className={`robot-office ${compact ? "compact" : ""}`} aria-label="Robot studio">
      <div className="office-heading">
        <div><span className="office-kicker">CLIPFOUNDRY STUDIO</span>
          <h2>{compact ? "Your studio, at a glance" : "A little studio. Real work."}</h2></div>
        <span className="office-status">{lost || !st ? "Waiting for connection" : st.paused ? "Jobs stopped"
          : !st.enabled ? "Autopilot resting" : !st.workers.host.alive ? "Background work stopped" : "Connected to this PC"}</span>
      </div>
      <div className="office-room">
        <OfficeBackdrop />
        <div className="office-stations">
          {STATIONS.map((s) => <StationView key={s.kind} {...s} status={statuses[s.kind]} selected={selected === s.kind}
            panelId={id} onSelect={() => setSelected(selected === s.kind ? null : s.kind)} />)}
        </div>
      </div>
      <div id={id} className="office-activity" hidden={!selected}>
        {selected && current && <>
          <div className="row wrap"><h3>{STATIONS.find((s) => s.kind === selected)!.label} activity</h3>
            <span className="grow" /><a className="textlink small" href="#/autopilot/activity">Open Activity</a>
            <button type="button" className="btn btn-small btn-quiet" onClick={() => setSelected(null)}>Close</button></div>
          <p>{current.message}</p>
          {current.state === "working" && current.workers.filter((w) => w.status === "working" && !w.stale).map((w) => (
            <div className="stack small" key={w.name}>
              <span>{w.message || w.stage}{w.progress != null ? ` · ${Math.round(w.progress * 100)}% of this step` : ""}</span>
              {w.progress != null && <ProgressBar value={w.progress} label={`${Math.round(w.progress * 100)}% of this step`} />}
            </div>
          ))}
          {current.notice?.fix && <p className="small muted">{current.notice.fix}</p>}
          {current.notice?.link && <a className="textlink" href={current.notice.link}>Open recovery steps</a>}
        </>}
      </div>
      {!compact && st && <dl className="office-summary">
        <div><dt>Last search</dt><dd>{lost ? "Unknown" : clock(st.home.discovery.last_scan, st.timezone)}</dd></div>
        <div><dt>Next search</dt><dd>{lost ? "Unknown" : !st.enabled || st.paused ? "When Autopilot resumes"
          : clock(st.home.discovery.next_scan || st.home.next_look, st.timezone)}</dd></div>
        <div><dt>Clips made today</dt><dd>{lost ? "—" : st.sources_today.clips}</dd></div>
        <div><dt>Next post</dt><dd>{lost ? "Unknown" : st.next ? clock(st.next.planned_at, st.timezone) : "None planned"}</dd></div>
      </dl>}
    </section>
  );
}
