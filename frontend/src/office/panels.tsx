import { Fragment, ReactNode, useEffect, useState } from "react";
import { errorText } from "../api";
import { NeedActions, needLook } from "../components/needsYou";
import { ConfirmDialog, Disclosure, Icon, IconName, Pill, ProgressBar, toast, Tone } from "../components/ui";
import { DEPARTMENTS, RobotPortrait, RobotSprite, roleById, RoleId } from "../robots";
import { useStatus } from "../status";
import { CsvImport } from "./TestFeedback";
import { membersOf, Placement, RoomDef, STATE_SHAPE, STATE_WORDS } from "./layout";
import {
  AudienceView, BrainView, clockTime, destinationWords, DevLog, HealthState, localWhen, office, OfficeEvent,
  OfficeRobot, OfficeSnapshot,
} from "./officeApi";

/**
 * The right-hand detail panel: an overview (needs you + recent activity) when nothing is selected, one robot, or one
 * room's live details. Everything comes from the snapshot or a read of its own endpoint; unknown stays unknown.
 */

// ------------------------------------------------------------------ shared bits
export const HEALTH_LOOK: Record<HealthState, [Tone, IconName, string]> = {
  Healthy: ["good", "check", "Healthy"],
  Degraded: ["warn", "alert", "Degraded"],
  Error: ["bad", "x", "Error"],
  Unknown: ["neutral", "question", "Unknown"],
};

export function HealthPill({ state, lost }: { state?: HealthState; lost: boolean }) {
  // A stale "Healthy" must never read as current: while disconnected the pill says so instead.
  if (lost || !state) return <Pill tone="neutral" icon="offline">Health unknown</Pill>;
  const [tone, icon, word] = HEALTH_LOOK[state] || HEALTH_LOOK.Unknown;
  return <Pill tone={tone} icon={icon}>{word}</Pill>;
}

const STATE_TONE: Record<OfficeRobot["state"], Tone> = {
  working: "info", waiting: "warn", error: "bad", idle: "neutral", lounge: "neutral", monitoring: "info",
};
export function StatePill({ state }: { state: OfficeRobot["state"] }) {
  return (
    <span className={`pill ${STATE_TONE[state]}`}>
      <span aria-hidden="true" className="state-shape">{STATE_SHAPE[state]}</span>{STATE_WORDS[state]}
    </span>
  );
}

/** Measured progress when the job reports it; otherwise an honest indeterminate bar. */
export function TaskProgress({ value, label }: { value: number | null | undefined; label: string }) {
  if (value === null || value === undefined) {
    return (
      <div className="bar indeterminate" role="progressbar" aria-label={`${label}: progress not reported`}
        aria-valuetext="Progress not reported">
        <span />
      </div>
    );
  }
  return <ProgressBar value={value} label={`${label}: ${Math.round(value * 100)}% of this step`} />;
}

/** Where a task's main action leads (the clip, the post, the source list, or the Queue's problems). */
export function taskLink(r: OfficeRobot): { href: string; label: string } {
  const t = r.task;
  if (r.state === "error") return { href: "#/queue/problems", label: "Open Queue → Problems" };
  if (t?.ref_type === "clip" && t.ref_id) return { href: `#/clip/${t.ref_id}`, label: "Open the clip" };
  if (t?.ref_type === "scheduled" && t.ref_id) return { href: `#/post/${t.ref_id}`, label: "Open the post" };
  if (t?.ref_type === "project" && t.ref_id) return { href: `#/project/${t.ref_id}`, label: "Open the source video" };
  if (t?.ref_type === "source") return { href: "#/missions/sources", label: "Open the sources" };
  return { href: "#/missions/activity", label: "Open Missions activity" };
}

// ------------------------------------------------------------------ activity feed
type Filter = "all" | "reports" | "decisions" | "problems";
const FILTERS: [Filter, string][] = [["all", "All"], ["reports", "Reports"], ["decisions", "Decisions"],
  ["problems", "Problems"]];
const DECISIONS = new Set(["office.manager_review", "office.boss_decision", "strategy_updated",
  "strategy_rolled_back", "brain_evaluated"]);
const PROBLEM_TYPES = new Set(["publish_failed", "emergency_stop", "brain_error"]);
export const isProblem = (e: OfficeEvent) => e.level === "error" || e.level === "warning"
  || PROBLEM_TYPES.has(e.type);
const MATCH: Record<Filter, (e: OfficeEvent) => boolean> = {
  all: () => true,
  reports: (e) => e.type === "office.worker_report",
  decisions: (e) => DECISIONS.has(e.type),
  problems: isProblem,
};

export function ActivityFeed({ events, lost, limit = 40, initial = "all", onRobot }: {
  events: OfficeEvent[]; lost: boolean; limit?: number; initial?: Filter; onRobot?: (r: RoleId) => void;
}) {
  const [filter, setFilter] = useState<Filter>(initial);
  const shown = events.filter(MATCH[filter]).slice(-limit).reverse();
  return (
    <div className={`feed ${lost ? "is-stale" : ""}`}>
      <div className="feed-filters" role="group" aria-label="Show activity">
        {FILTERS.map(([id, label]) => (
          <button key={id} type="button" className="chip" aria-pressed={filter === id}
            onClick={() => setFilter(id)}>{label}</button>
        ))}
      </div>
      {shown.length ? (
        <ol className="feed-list">
          {shown.map((e) => {
            const role = roleById(e.role);
            return (
              <li key={e.id} className={`feed-item ${isProblem(e) ? "is-problem" : ""}`}>
                <span className="feed-mark" aria-hidden="true">{isProblem(e) ? "!" : DECISIONS.has(e.type) ? "◆"
                  : "•"}</span>
                <span className="feed-msg">
                  {role && onRobot ? (
                    <button type="button" className="textlink feed-who" onClick={() => onRobot(role.id)}>
                      {role.name}
                    </button>
                  ) : null}
                  {" "}{role ? e.message.replace(new RegExp(`^${role.name}:?\\s*`), "") : e.message}
                </span>
                <time className="feed-time tnum" dateTime={new Date(e.at * 1000).toISOString()}>
                  {clockTime(e.at)}
                </time>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="small muted">{events.length ? "Nothing of this kind yet." : "Waiting for data."}</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ overview (nothing selected)
export function OverviewPanel({ snap, events, lost, onRobot }: {
  snap: OfficeSnapshot | null; events: OfficeEvent[]; lost: boolean; onRobot: (r: RoleId) => void;
}) {
  const { st, refresh } = useStatus();
  // The Home page's working Needs-you actions (rights, files, accounts...), folded into the Office.
  const items = lost ? [] : st?.home.needs_you || [];
  const firstUse = !!st && !lost && !st.home.setup.started && st.home.setup.mode !== "manual";
  const fallback = !st && snap ? snap.needs_you : [];
  return (
    <>
      <section className="dp-section" aria-labelledby="dp-needs">
        <h3 id="dp-needs" className="dp-h"><Icon name="alert" />Needs your action</h3>
        {lost ? <p className="small muted">Unknown while ClipFoundry is not answering.</p>
          : firstUse ? (
            <div className="stack">
              <p className="small">Start by adding a video you made, or set up Autopilot.</p>
              <div className="row wrap">
                <a className="btn btn-primary btn-small" href="#/setup/videos">Get started</a>
                <a className="btn btn-small" href="#/create">Add a video</a>
              </div>
            </div>
          ) : items.length ? (
            <ul className="dp-needs">
              {items.slice(0, 4).map((it) => {
                const [tone, icon] = needLook(it);
                return (
                  <li key={it.key} className="dp-need">
                    <Pill tone={tone} icon={icon}>{tone === "bad" ? "Problem" : tone === "warn" ? "Waiting" : "Info"}
                    </Pill>
                    <span className="small strong">{it.title}</span>
                    {it.fix && <span className="tiny muted">{it.fix}</span>}
                    {st && <div className="row wrap"><NeedActions item={it} platforms={st.platforms}
                      refresh={refresh} first /></div>}
                  </li>
                );
              })}
              {items.length > 4 && <li className="tiny muted">and {items.length - 4} more on the Missions page.</li>}
            </ul>
          ) : fallback.length ? (
            <ul className="dp-needs">
              {fallback.map((n) => <li key={n.key} className="dp-need"><span className="small strong">{n.title}</span>
                {n.fix && <span className="tiny muted">{n.fix}</span>}</li>)}
            </ul>
          ) : <p className="small muted">{st || snap ? "Nothing needs you." : "Waiting for data."}</p>}
      </section>
      <section className="dp-section" aria-labelledby="dp-recent">
        <h3 id="dp-recent" className="dp-h"><Icon name="clock" />Recent activity</h3>
        <ActivityFeed events={events} lost={lost} limit={25} onRobot={onRobot} />
      </section>
    </>
  );
}

// ------------------------------------------------------------------ one robot
export function RobotPanel({ p, snap, lost, events, reduced, onRobot }: {
  p: Placement; snap: OfficeSnapshot; lost: boolean; events: OfficeEvent[]; reduced: boolean;
  onRobot: (r: RoleId) => void;
}) {
  const role = roleById(p.role)!;
  const r = p.robot;
  const manager = roleById(r.manager !== r.role ? r.manager : role.managerId || "");
  const dept = DEPARTMENTS.find((d) => d.id === role.department);
  const task = r.task && r.task.job_id ? r.task : null;
  const link = taskLink(r);
  const mine = events.filter((e) => e.role === role.id || e.data?.worker === role.id);
  const lastError = [...mine].reverse().find((e) => e.level === "error");
  return (
    <div className="dp-robot">
      <div className="dp-portrait">
        <RobotPortrait role={role.id} scale={2} state={lost ? "unavailable" : p.sprite} reducedMotion={reduced}
          title={`${role.name}, ${role.job}`} />
      </div>
      <div className="dp-name">
        <h3 className="pixel-name" style={{ color: role.palette.trim }}>{role.name}</h3>
        <span>{role.job}</span>
        <span className="tiny muted">{role.duty}</span>
      </div>
      <dl className="dp-kv">
        <dt>Manager</dt>
        <dd>{manager ? <button type="button" className="textlink" onClick={() => onRobot(manager.id)}>
          {manager.name} · {manager.job}</button> : "Runs the whole studio"}</dd>
        <dt>Room</dt><dd>{dept?.label || "—"}</dd>
        <dt>State</dt><dd>{lost ? <Pill tone="neutral" icon="offline">Unknown (connection lost)</Pill>
          : <StatePill state={r.state} />}</dd>
        {r.queued > 1 && <><dt>Tasks</dt><dd>{r.queued} jobs assigned (one shown)</dd></>}
      </dl>
      <section className="dp-section" aria-label="Current task">
        <h4 className="dp-h">Current task</h4>
        {task ? (
          <div className="dp-task">
            <span className="strong">{task.label || task.stage}</span>
            {task.message && <span className="small muted">{task.message}</span>}
            {r.state === "working" && <TaskProgress value={task.progress} label={task.label || "This task"} />}
            <span className="tiny faint">Job {task.job_id.slice(0, 8)}</span>
          </div>
        ) : <p className="small muted">No task right now.</p>}
      </section>
      <section className="dp-section" aria-label="Last report">
        <h4 className="dp-h">Last report</h4>
        {r.last ? (
          <p className={`small ${r.last.level === "error" ? "bad-text" : ""}`}>
            {r.last.message} <span className="tiny faint">· {localWhen(r.last.at)}</span>
          </p>
        ) : <p className="small muted">None recorded yet.</p>}
        {lastError && lastError.message !== r.last?.message && (
          <p className="small bad-text">Latest error: {lastError.message}
            <span className="tiny faint"> · {localWhen(lastError.at)}</span></p>
        )}
      </section>
      <a className="btn btn-primary dp-main" href={link.href}>{link.label}<Icon name="chev" /></a>
      {snap.run_state !== "running" && r.state === "lounge" && (
        <p className="tiny muted">Autopilot is {snap.run_state}, so this robot rests until work starts again.</p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ rooms
export function RoomPanel({ room, snap, placements, events, lost, reduced, onRobot, refresh }: {
  room: RoomDef; snap: OfficeSnapshot; placements: Placement[]; events: OfficeEvent[]; lost: boolean;
  reduced: boolean; onRobot: (r: RoleId) => void; refresh: () => void;
}) {
  const here = placements.filter((p) => p.room === room.id);
  const crew = room.id === "lounge" ? here : membersOf(room.id)
    .map((id) => placements.find((p) => p.role === id)).filter((p): p is Placement => !!p);
  let body: ReactNode = null;
  switch (room.id) {
    case "boss_hub": body = <BossHub snap={snap} events={events} lost={lost} onRobot={onRobot} />; break;
    case "brain": body = <BrainRoom lost={lost} snap={snap} refresh={refresh} />; break;
    case "upload_dock": body = <UploadDock snap={snap} lost={lost} />; break;
    case "system": body = <SystemRoom snap={snap} lost={lost} />; break;
    case "devlog": body = <DevLogRoom />; break;
    case "team": body = <TeamRoom events={events} lost={lost} onRobot={onRobot} />; break;
    case "lounge": body = (
      <p className="small muted">{here.length ? "Robots rest here only while Autopilot is paused or stopped. "
        + "Nothing in the Lounge is working." : "Nobody is resting: Autopilot is running, so every robot is at "
        + "its own desk."}</p>
    ); break;
    default: break;
  }
  return (
    <div className="dp-room">
      {body}
      {crew.length > 0 && (
        <section className="dp-section" aria-label={`${room.label} robots`}>
          <h4 className="dp-h">{room.id === "lounge" ? "Resting here" : "Robots and their jobs"}</h4>
          <ul className="dp-crew">
            {crew.map((p) => {
              const role = roleById(p.role)!;
              const t = p.robot.task && p.robot.task.job_id ? p.robot.task : null;
              return (
                <li key={p.role}>
                  <button type="button" className="dp-crew-row" onClick={() => onRobot(p.role)}>
                    <RobotSprite role={p.role} scale={1} state={lost ? "unavailable" : p.sprite} card={false}
                      reducedMotion={reduced} />
                    <span className="stack">
                      <span className="strong">{role.name} <span className="muted small">· {role.job}</span></span>
                      <span className="small">{lost ? "State unknown" : STATE_WORDS[p.robot.state]}
                        {t ? `: ${t.label || t.stage}` : ""}</span>
                      {t?.message && <span className="tiny muted clamp-2">{t.message}</span>}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {crew.length === 0 && !["boss_hub", "brain", "upload_dock", "system", "devlog", "team", "lounge"]
        .includes(room.id) && <p className="small muted">No robots here right now.</p>}
    </div>
  );
}

function BossHub({ snap, events, lost, onRobot }: {
  snap: OfficeSnapshot; events: OfficeEvent[]; lost: boolean; onRobot: (r: RoleId) => void;
}) {
  return (
    <>
      <section className="dp-section" aria-label="Current mission">
        <h4 className="dp-h">Current mission</h4>
        <p className="strong">{lost ? "Unknown (connection lost)" : snap.mission.title}</p>
        {!lost && snap.mission.detail && <p className="small muted">{snap.mission.detail}</p>}
      </section>
      <section className="dp-section" aria-label="Needs you">
        <h4 className="dp-h">Needs you ({lost ? "?" : snap.needs_you.length})</h4>
        {lost ? <p className="small muted">Unknown.</p> : snap.needs_you.length ? (
          <ul className="dp-needs">{snap.needs_you.map((n) => (
            <li key={n.key} className="dp-need"><span className="small strong">{n.title}</span>
              {n.fix && <span className="tiny muted">{n.fix}</span>}</li>
          ))}</ul>
        ) : <p className="small muted">Nothing needs you.</p>}
      </section>
      <section className="dp-section" aria-label="Reports and decisions">
        <h4 className="dp-h">Reports and decisions</h4>
        <p className="tiny muted">Reviews and decisions are recorded rules over each job's outcome; nothing here
          approves a post.</p>
        <ActivityFeed events={events} lost={lost} initial="decisions" limit={20} onRobot={onRobot} />
      </section>
    </>
  );
}

function TeamRoom({ events, lost, onRobot }: { events: OfficeEvent[]; lost: boolean; onRobot: (r: RoleId) => void }) {
  const handoffs = events.filter((e) => e.type === "office.worker_report" || e.type === "office.manager_review");
  return (
    <section className="dp-section" aria-label="Handoffs">
      <h4 className="dp-h">Handoffs between robots</h4>
      <p className="tiny muted">Recorded reports and reviews only. There is no chat to show.</p>
      <ActivityFeed events={handoffs} lost={lost} limit={20} onRobot={onRobot} />
    </section>
  );
}

function BrainRoom({ lost, snap, refresh }: { lost: boolean; snap: OfficeSnapshot; refresh: () => void }) {
  const [view, setView] = useState<BrainView | null>(null);
  const [error, setError] = useState("");
  const [rolling, setRolling] = useState<string | null>(null);
  const load = () => office.brain().then((v) => { setView(v); setError(""); })
    .catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);
  const v = view;
  const active = (v?.versions || []).filter((s) => s.status === "active");
  return (
    <>
      <section className="dp-section" aria-label="Brain state">
        <h4 className="dp-h">What the Brain knows</h4>
        {error && <p className="small bad-text">Could not read the Brain: {error}</p>}
        {!v ? <p className="small muted">{error ? "Unavailable" : "Waiting for data."}</p> : (
          <dl className="dp-kv">
            <dt>State</dt><dd>{v.state}</dd>
            <dt>Observations</dt><dd>{v.observations}</dd>
            {Object.entries(v.by_provenance).map(([k, n]) => (
              <Fragment key={k}><dt className="sub">{PROV_LABEL[k] || k}</dt><dd>{n}</dd></Fragment>
            ))}
            <dt>Strategy</dt>
            <dd>{v.ranking.strategy_version === "baseline" ? "Baseline (your settings)" : `Version ${v.ranking
              .strategy_version.slice(0, 8)}`} · target {Math.round(v.ranking.target_duration)} s</dd>
          </dl>
        )}
        {v && !v.cohorts.length && <p className="small"><b>Not enough evidence yet.</b> Results from your selected
          viewers appear here once you add test feedback.</p>}
        {v?.cohorts.map((c) => (
          <div key={c.cohort} className="dp-cohort">
            <span className="small strong">{c.cohort.replace(/^selected:/, "Selected audience: ")}</span>
            <span className="small">{c.eligible_clips} of {c.needed} eligible clips · {c.status}</span>
            <TaskProgress value={Math.min(1, c.needed ? c.eligible_clips / c.needed : 0)} label="Eligible clips" />
          </div>
        ))}
        {v?.note && <p className="tiny muted">{v.note}</p>}
      </section>
      {active.length > 0 && (
        <section className="dp-section" aria-label="Active strategy">
          <h4 className="dp-h">Active strategy changes</h4>
          {active.map((s) => (
            <div key={s.id} className="dp-cohort">
              <span className="small">{s.parameter}: {s.old_value ?? "—"} → {s.new_value ?? "—"}
                <span className="tiny faint"> · {localWhen(s.created_at)}</span></span>
              {s.reason && <span className="tiny muted">{s.reason}</span>}
              <button type="button" className="btn btn-small" disabled={lost} onClick={() => setRolling(s.id)}>
                <Icon name="back" />Roll back</button>
            </div>
          ))}
        </section>
      )}
      <section className="dp-section" aria-label="Test feedback">
        <h4 className="dp-h">Test feedback</h4>
        <p className="small">Add what your viewers told you, or numbers you read on the platform, from a clip's page:
          {" "}<a className="textlink" href="#/clips">Clips</a> → a clip → Prepare post → Test feedback.</p>
        <Disclosure summary="Import numbers from a CSV file">
          <CsvImport onDone={() => { load(); refresh(); }} />
        </Disclosure>
      </section>
      {rolling && (
        <ConfirmDialog title="Roll back this strategy change?" confirmLabel="Roll back" onClose={() => setRolling(null)}
          onConfirm={async () => {
            await office.rollback(rolling);
            toast("Strategy rolled back");
            load();
            refresh();
          }}>
          <p className="muted">New clips go back to the previous version ({snap.brain.strategy.strategy_version ===
            "baseline" ? "your settings" : "or the baseline"}). The change stays in the history.</p>
        </ConfirmDialog>
      )}
    </>
  );
}
const PROV_LABEL: Record<string, string> = {
  platform_api: "Platform API", owner_import: "Your import", tester_feedback: "Tester feedback (self-reported)",
};

function UploadDock({ snap, lost }: { snap: OfficeSnapshot; lost: boolean }) {
  const [aud, setAud] = useState<AudienceView | null>(null);
  useEffect(() => {
    office.audience().then(setAud).catch(() => undefined);
  }, []);
  const yt = snap.audience.youtube;
  return (
    <>
      <section className="dp-section" aria-label="Selected audience">
        <h4 className="dp-h">Who sees the clips</h4>
        <ul className="dp-plain">
          {(["youtube", "tiktok"] as const).map((p) => (
            <li key={p}><span className="strong small">{destinationWords(p, snap.audience[p])}</span>
              <span className="tiny muted">{snap.audience[p]?.text}</span>
              {snap.audience[p]?.notes?.map((n, i) => <span key={i} className="tiny muted">{n}</span>)}</li>
          ))}
        </ul>
        <a className="textlink small" href="#/settings/integrations">Change in Settings → Integrations</a>
        {snap.publishing_paused && <p className="small"><b>Publishing is paused.</b> Clips are still made and kept
          on this PC.</p>}
      </section>
      <section className="dp-section" aria-label="Manual posting">
        <h4 className="dp-h">Manual posting packages</h4>
        <p className="small">{lost ? "Unknown" : snap.manual_handoffs ? `${snap.manual_handoffs} waiting for you to `
          + "post on TikTok yourself." : "None waiting."}</p>
        {!lost && snap.manual_handoffs > 0 && <a className="btn btn-small" href="#/queue/manual">Open the packages</a>}
      </section>
      {yt?.intent === "SELECTED_AUDIENCE" && (
        <section className="dp-section" aria-label="Invited viewers">
          <h4 className="dp-h">Inviting YouTube viewers</h4>
          <p className="small">{aud?.youtube_share_steps || "Open YouTube Studio, keep the video Private and share it "
            + "with the people you chose."}</p>
          <p className="tiny muted">After you invite them, press “I've invited my viewers” on the post in the Queue.
            Until then the video counts as uploaded for you only.</p>
          <a className="btn btn-small" href="#/queue/published">Open uploaded posts</a>
        </section>
      )}
    </>
  );
}

function SystemRoom({ snap, lost }: { snap: OfficeSnapshot; lost: boolean }) {
  const h = snap.health;
  return (
    <section className="dp-section" aria-label="Health checks">
      <h4 className="dp-h">Health</h4>
      {lost && <p className="small"><b>Connection lost.</b> These checks are from before the connection dropped and
        may be out of date.</p>}
      <div className="row wrap"><HealthPill state={h.state} lost={lost} />
        {!lost && <span className="small">{h.reason}</span>}</div>
      {!lost && h.action && <p className="small"><b>What to do:</b> {h.action}</p>}
      <ul className="dp-checks">
        {h.checks.map((c) => {
          const [tone, icon, word] = HEALTH_LOOK[c.state] || HEALTH_LOOK.Unknown;
          return (
            <li key={c.id} className={lost ? "is-stale" : ""}>
              <span className="row"><Pill tone={lost ? "neutral" : tone} icon={icon}>{word}</Pill>
                <span className="small strong">{c.label}</span></span>
              <span className="small">{c.reason}</span>
              {c.action && <span className="tiny"><b>What to do:</b> {c.action}</span>}
              <span className="tiny faint">Checked {clockTime(c.checked_at)}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function DevLogRoom() {
  const [log, setLog] = useState<DevLog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    office.devlog().then(setLog).catch((e) => setError(errorText(e)));
  }, []);
  return (
    <section className="dp-section" aria-label="Development log">
      <h4 className="dp-h">Development history (read-only)</h4>
      {error ? <p className="small bad-text">{error}</p> : !log ? <p className="small muted">Waiting for data.</p>
        : !log.available ? <p className="small muted">Unavailable: this copy of ClipFoundry has no development log
          (it ships only with a source checkout).</p> : (
          <>
            {log.entries.length > 0 && (
              <ol className="dp-plain">
                {log.entries.slice(0, 30).map((e, i) => (
                  <li key={i}><span className="small">{String(e.summary || e.message || e.title || "")
                    || JSON.stringify(e).slice(0, 160)}</span>
                  {e.at || e.date ? <span className="tiny faint">{String(e.date || (typeof e.at === "number"
                    ? localWhen(e.at) : e.at))}</span> : null}</li>
                ))}
              </ol>
            )}
            {log.changelog && <pre className="dp-log">{log.changelog.slice(0, 20000)}</pre>}
          </>
        )}
    </section>
  );
}
