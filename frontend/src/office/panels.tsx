import { ReactNode, useEffect, useMemo, useState } from "react";
import { errorText } from "../api";
import { ConfirmDialog, Icon, IconName, toast } from "../components/ui";
import { timeLabel } from "../components/postShared";
import { useStatus } from "../status";
import { BY_ID, CAST, DEPARTMENTS, Dept, RoomId, ROOM_NAMES } from "./cast";
import { brainApi, BrainSummary, Health, HealthStatus, office, OfficeDecision, OfficeEvent, RoleRow, RoomDetails,
  Snapshot, staleHealth } from "./api";
import Portrait from "./Portrait";
import { Card, STATE_WORDS } from "./OfficeMap";
import { Pose } from "./sprites";

// ------------------------------------------------------------------ small shared pieces
export const time = (ts: number | null | undefined, seconds = false) => ts
  ? new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", ...(seconds ? { second: "2-digit" } : {}) })
  : "—";
export const when = (ts: number | null | undefined) => {
  if (!ts) return "—";
  const d = new Date(ts * 1000), today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay ? `today ${time(ts)}` : d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};
const ago = (ts: number, skew: number) => {
  const s = Math.max(0, Date.now() / 1000 + skew - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
};

const STATE_TONE: Record<string, string> = {
  working: "info", reviewing: "accent", waiting: "warn", retrying: "warn", error: "bad", idle: "", paused: "",
  unavailable: "",
};
const STATE_ICON: Record<string, IconName> = {
  working: "play", reviewing: "check", waiting: "clock", retrying: "refresh", error: "alert", idle: "dot",
  paused: "pause", unavailable: "x",
};
export function StateBadge({ state }: { state: string }) {
  return (
    <span className={`pill ${STATE_TONE[state] || ""}`}>
      <Icon name={STATE_ICON[state] || "dot"} />{(STATE_WORDS as Record<string, string>)[state] || state}
    </span>
  );
}
const HEALTH_TONE: Record<HealthStatus, string> = { healthy: "good", degraded: "warn", error: "bad", unknown: "" };
const HEALTH_ICON: Record<HealthStatus, IconName> = { healthy: "check", degraded: "alert", error: "x", unknown: "question" };
export function HealthBadge({ status, label }: { status: HealthStatus; label: string }) {
  return <span className={`pill ${HEALTH_TONE[status]}`}><Icon name={HEALTH_ICON[status]} />{label}</span>;
}

export const POSE_OF: Record<string, Pose> = {
  idle: "idle", working: "work", waiting: "wait", retrying: "retry", error: "error", reviewing: "review",
  paused: "paused", unavailable: "unavailable",
};
const NEXT_STAGE: Record<Dept, string> = {
  boss: "—", discover: "Analyze", analyze: "Clip Studio", studio: "Caption", caption: "Quality check",
  system: "Schedule", schedule: "Upload Dock", dock: "Results in the Brain Room", brain: "Discover",
};
const POINT_LABEL: Record<string, string> = { source: "Video", clip: "Clip", qc: "Quality check", upload: "Upload" };
const ACTION_LABEL: Record<string, [string, string]> = {
  approved: ["Go", "good"], rework: ["Do again", "warn"], rejected: ["No", "bad"], held: ["Held", "warn"],
};

/** Where a job's subject can be opened. */
export function subjectLink(type: string, id: string): { href: string; label: string } | null {
  if (!id) return null;
  if (type === "clip") return { href: `#/clip/${id}`, label: "Open editor" };
  if (type === "scheduled") return { href: `#/post/${id}`, label: "Open post" };
  if (type === "source") return { href: "#/missions/sources", label: "Open videos found" };
  if (type === "project") return { href: `#/project/${id}`, label: "Open source video" };
  return null;
}

function Section({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="op-section">
      <div className="op-section-head"><h3>{title}</h3>{action}</div>
      {children}
    </section>
  );
}

function Progress({ value, label }: { value: number | null; label: string }) {
  if (value === null) {
    return <div className="op-progress indeterminate" role="progressbar" aria-label={`${label}: progress not measured`}><span /></div>;
  }
  const pct = Math.round(value * 100);
  return (
    <div className="op-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
      <span style={{ width: `${pct}%` }} /><b>{pct}%</b>
    </div>
  );
}

export function DecisionList({ items, empty = "No decisions recorded yet." }: { items: OfficeDecision[]; empty?: string }) {
  if (!items.length) return <p className="muted small">{empty}</p>;
  return (
    <ul className="op-list">
      {items.map((d) => {
        const [word, tone] = ACTION_LABEL[d.action] || [d.action, ""];
        const link = subjectLink(d.subject_type, d.subject_id);
        return (
          <li key={d.id}>
            <span className={`pill ${tone}`}>{POINT_LABEL[d.point] || d.point}: {word}</span>
            <span className="grow">{d.reason}</span>
            <span className="muted tiny nowrap">{time(d.created_at)}</span>
            {link && <a className="tiny" href={link.href}>{link.label}</a>}
          </li>
        );
      })}
    </ul>
  );
}

// ------------------------------------------------------------------ the default panel
export function OverviewPanel({ snap, skew, events, onRobot, onRoom, setupNeeded }: {
  snap: Snapshot; skew: number; events: OfficeEvent[]; onRobot: (id: string) => void; onRoom: (id: RoomId) => void;
  setupNeeded: boolean;
}) {
  const { st } = useStatus();
  const needs = st?.home.needs_you || [];
  const busy = snap.roles.filter((r) => r.state === "working" && r.task)
    .sort((a, b) => (BY_ID[a.id]?.rank === "worker" ? -1 : 1) - (BY_ID[b.id]?.rank === "worker" ? -1 : 1));
  const lead = busy[0];
  const brain = snap.brain as BrainSummary;
  return (
    <div className="op-body">
      {setupNeeded && (
        <div className="op-callout">
          <b>Finish setting up</b>
          <p className="small">Choose where your videos come from and how posts go out.</p>
          <a className="btn btn-primary btn-small" href="#/setup/videos">Set up ClipFoundry</a>
        </div>
      )}
      {needs.length > 0 && (
        // the same list, in the same order, as Missions → Needs you (autopilot/home.py)
        <a className="op-needs" href={needs.length === 1 && needs[0].link ? needs[0].link : "#/missions"}>
          <Icon name="alert" />
          <span className="grow"><b>Needs your action</b><span className="small">{needs[0].title}</span></span>
          {needs.length > 1 && <span className="count">{needs.length}</span>}
          <Icon name="chev" />
        </a>
      )}
      <Section title="Current mission">
        {lead && lead.task ? (
          <button type="button" className="op-mission" onClick={() => onRobot(lead.id)}>
            <Portrait id={lead.id} pose="work" scale={1} crop />
            <span className="grow">
              <b>{BY_ID[lead.id].name}</b> <span className="muted small">{BY_ID[lead.id].title}</span>
              <span className="small block">{lead.task.message || "Working"}</span>
              <Progress value={lead.task.progress} label={`${BY_ID[lead.id].name} progress`} />
            </span>
          </button>
        ) : (
          <p className="muted small">{snap.run.state === "running" ? "Nothing is running right now. Autopilot checks for new videos on its schedule."
            : snap.run.state === "paused" ? "Autopilot is paused. Running steps finish; nothing new starts."
              : "Autopilot is stopped. Press Start to let it find and clip videos."}</p>
        )}
        {busy.length > 1 && <p className="muted tiny">{busy.length - 1} more step{busy.length > 2 ? "s" : ""} running.</p>}
      </Section>
      <Section title="Today">
        <dl className="op-facts">
          <div><dt>Clips made</dt><dd>{snap.today.clips}</dd></div>
          <div><dt>Passed the check</dt><dd>{snap.today.passed_check}</dd></div>
          <div><dt>Uploaded</dt><dd>{snap.today.uploads}</dd></div>
        </dl>
        <p className="small">
          <Icon name="calendar" className="sm" /> Next upload: {snap.next_upload
            ? <a href={`#/post/${snap.next_upload.id}`}>{timeLabel(snap.next_upload.planned_at, st?.timezone)}, {snap.next_upload.platform === "youtube" ? "YouTube" : "TikTok"}</a>
            : <span className="muted">none planned</span>}
          {snap.run.publishing_paused && <span className="pill warn"><Icon name="pause" />Publishing paused</span>}
        </p>
      </Section>
      <Section title="Health" action={<button type="button" className="link-btn small" onClick={() => onRoom("system")}>Details</button>}>
        <p className="small"><HealthBadge status={snap.health.status} label={snap.health.label} /> {snap.health.headline}</p>
        {snap.health.action && <p className="small muted">{snap.health.action}</p>}
      </Section>
      {brain && brain.label && (
        <Section title="Brain" action={<button type="button" className="link-btn small" onClick={() => onRoom("brain")}>Details</button>}>
          <p className="small"><span className="pill">{brain.label}</span> {brain.message}</p>
        </Section>
      )}
      <Section title="Recent activity">
        <ActivityList events={events} skew={skew} limit={5} onRobot={onRobot} />
      </Section>
    </div>
  );
}

// ------------------------------------------------------------------ activity
const FILTERS: { id: string; label: string; test: (e: OfficeEvent) => boolean }[] = [
  { id: "all", label: "All", test: () => true },
  { id: "reports", label: "Reports", test: (e) => e.type === "report" },
  { id: "decisions", label: "Decisions", test: (e) => e.type === "decision" },
  { id: "problems", label: "Problems", test: (e) => ["job_failed", "job_retry"].includes(e.type) ||
    (e.type === "decision" && ["rejected", "held", "rework"].includes(e.data?.action)) },
  { id: "uploads", label: "Uploads", test: (e) => ["dock", "lock", "harbor", "clock"].includes(e.role) },
  { id: "brain", label: "Brain", test: (e) => e.type.startsWith("brain") || e.type.startsWith("strategy") },
];
const TYPE_WORD: Record<string, string> = {
  job_started: "Started", job_done: "Finished", job_failed: "Failed", job_retry: "Will try again",
  job_waiting: "Waiting", job_canceled: "Canceled", job_stage: "Next step", report: "Report", decision: "Decision",
  control: "Control", brain_observation: "Result saved", brain_lookup: "Memory lookup", brain_evaluation: "Comparing",
  brain_evaluated: "Evaluated", strategy_changed: "Strategy changed", strategy_rolled_back: "Rolled back",
};

export function ActivityList({ events, skew, limit, onRobot, filter = "all" }: {
  events: OfficeEvent[]; skew: number; limit?: number; onRobot: (id: string) => void; filter?: string;
}) {
  const test = FILTERS.find((f) => f.id === filter)?.test || (() => true);
  const rows = events.filter((e) => !(e.data?.routine && e.type !== "job_failed") && test(e)).slice().reverse()
    .slice(0, limit || 100);
  if (!rows.length) return <p className="muted small">No activity yet.</p>;
  return (
    <ul className="op-activity">
      {rows.map((e) => {
        const c = BY_ID[e.role];
        const bad = e.type === "job_failed" || (e.type === "decision" && e.data?.action === "rejected");
        return (
          <li key={e.id} className={bad ? "bad" : ""}>
            <span className="dot" aria-hidden="true" style={{ background: c ? c.palette.trim : "#7d8494" }} />
            {c ? <button type="button" className="link-btn" onClick={() => onRobot(e.role)}>{c.name}</button>
              : <b>{e.role === "core" ? "CORE" : "System"}</b>}
            <span className="grow">{TYPE_WORD[e.type] || e.type}{e.message ? `: ${e.message}` : ""}</span>
            <time className="muted tiny nowrap" dateTime={new Date(e.at * 1000).toISOString()} title={new Date(e.at * 1000).toLocaleString()}>{ago(e.at, skew)}</time>
          </li>
        );
      })}
    </ul>
  );
}

export function ActivityPanel({ events, skew, onRobot }: { events: OfficeEvent[]; skew: number; onRobot: (id: string) => void }) {
  const [filter, setFilter] = useState("all");
  return (
    <div className="op-body">
      <div className="chips" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className={`chip${filter === f.id ? " on" : ""}`} aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}>{f.label}</button>
        ))}
      </div>
      <ActivityList events={events} skew={skew} onRobot={onRobot} filter={filter} />
      <p className="muted tiny">Times are when each step really happened. Routine checks that changed nothing are left out.</p>
    </div>
  );
}

// ------------------------------------------------------------------ one robot
export function RobotPanel({ id, row, card, onRobot }: {
  id: string; row: RoleRow | undefined; card: Card | null; onRobot: (id: string) => void;
}) {
  const c = BY_ID[id];
  const [decisions, setDecisions] = useState<OfficeDecision[] | null>(null);
  const subject = card ? [card.ref_type, card.ref_id] : row?.task ? [row.task.ref_type, row.task.ref_id] : ["", ""];
  useEffect(() => {
    setDecisions(null);
    if (!subject[0] || !subject[1]) return;
    let alive = true;
    office.decisions(subject[0], subject[1]).then((d) => alive && setDecisions(d)).catch(() => alive && setDecisions([]));
    return () => {
      alive = false;
    };
  }, [subject[0], subject[1]]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!c) return null;
  const state = row?.state || "idle";
  const manager = c.manager ? BY_ID[c.manager] : null;
  const link = subjectLink(subject[0], subject[1]);
  const team = CAST.filter((x) => x.manager === id);
  return (
    <div className="op-body">
      <div className="op-portrait">
        <Portrait id={id} pose={POSE_OF[state]} scale={3} label={`${c.name}, ${c.title}`} />
        <div className="op-name">
          <b>{c.name}</b>
          <span>{c.title}</span>
          <StateBadge state={state} />
        </div>
      </div>
      <dl className="op-pair">
        <div>
          <dt>Manager</dt>
          <dd>{manager ? <button type="button" className="op-chip" onClick={() => onRobot(manager.id)}>
            <Portrait id={manager.id} scale={1} crop />{manager.name}</button> : <span className="muted">Reports to you</span>}</dd>
        </div>
        <div><dt>Next</dt><dd>{NEXT_STAGE[c.dept]}</dd></div>
      </dl>
      <p className="small">{c.job}</p>
      {row?.task && (
        <Section title="Current task">
          <p className="small">{row.task.message || row.task.kind}</p>
          {row.task.status === "running" && <Progress value={row.task.progress} label={`${c.name} progress`} />}
          {row.tasks > 1 && <p className="muted tiny">{row.tasks - 1} more job{row.tasks > 2 ? "s" : ""} waiting for {c.name}.</p>}
        </Section>
      )}
      {card && (
        <Section title="Carrying a report">
          <p className="small">{card.summary || card.kind} <span className="muted">({card.state === "failed" ? "failed" : "finished"})</span></p>
          <p className="muted tiny">Job {card.job_id.slice(0, 8)}</p>
        </Section>
      )}
      {state === "error" && row?.error && (
        <div className="op-callout bad">
          <b>Latest error</b>
          <p className="small">{row.error}</p>
          <a className="small" href="#/missions/jobs">See the job and try again</a>
        </div>
      )}
      {row?.last && (
        <Section title="Recent result">
          <p className="small">{row.last.summary} <span className="muted tiny">{when(row.last.at)}</span></p>
        </Section>
      )}
      {decisions && decisions.length > 0 && (
        <Section title="Recorded decisions">
          <DecisionList items={decisions.slice(0, 5)} />
        </Section>
      )}
      {team.length > 0 && (
        <Section title="Team">
          <div className="op-team">
            {team.map((w) => (
              <button key={w.id} type="button" className="op-chip" onClick={() => onRobot(w.id)}>
                <Portrait id={w.id} scale={1} crop />{w.name}
              </button>
            ))}
          </div>
        </Section>
      )}
      {link ? <a className="btn btn-primary op-main" href={link.href}><Icon name="external" />{link.label}</a>
        : <a className="btn op-main" href="#/missions/jobs"><Icon name="dashboard" />See all jobs</a>}
    </div>
  );
}

// ------------------------------------------------------------------ one room
export function RoomPanel({ id, snap, onRobot, stale = false }: {
  id: RoomId; snap: Snapshot; onRobot: (id: string) => void; stale?: boolean;
}) {
  const [d, setD] = useState<RoomDetails | null>(null);
  const [err, setErr] = useState("");
  const [lastOk, setLastOk] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    setD(null);
    const load = () => office.room(id).then((x) => {
      if (alive) {
        setD(x);
        setErr("");
        setLastOk(Date.now());
      }
    }).catch((e) => alive && setErr(errorText(e)));
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [id]);
  const people = useMemo(() => {
    if (id === "lounge") return snap.roles.filter((r) => BY_ID[r.id]?.rank === "worker" && ["idle", "paused"].includes(r.state));
    return snap.roles.filter((r) => BY_ID[r.id]?.room === id);
  }, [id, snap.roles]);
  return (
    <div className="op-body">
      {people.length > 0 && (
        <div className="op-team">
          {people.map((r) => (
            <button key={r.id} type="button" className="op-chip" onClick={() => onRobot(r.id)}
              aria-label={`${BY_ID[r.id].name}, ${STATE_WORDS[r.state]}`}>
              <Portrait id={r.id} scale={1} pose={POSE_OF[r.state]} animate={false} crop />{BY_ID[r.id].name}
              <span className="muted tiny">{STATE_WORDS[r.state]}</span>
            </button>
          ))}
        </div>
      )}
      {id === "lounge" && <p className="muted small">Robots rest here while they have no work or Autopilot is paused. Nothing in this room is processing.</p>}
      {id === "workspace" && <p className="muted small">Handoffs between departments: each card is a real report a manager received.</p>}
      {err && <p className="error-text small">{err}</p>}
      {!d && !err && <p className="muted small">Loading…</p>}
      {d && <RoomBody d={d} snap={snap} stale={stale || !!err} lastOk={lastOk} />}
    </div>
  );
}

function RoomBody({ d, snap, stale, lastOk }: {
  d: RoomDetails; snap: Snapshot; stale: boolean; lastOk: number | null;
}) {
  const tz = useStatus().st?.timezone;
  switch (d.id) {
    case "boss":
      return (<>
        <Section title="Work in the queue">
          <p className="small">{["running", "queued", "waiting", "retrying"].map((k) => `${d.queue?.[k] || 0} ${k}`).join(" · ")}</p>
        </Section>
        <Section title="Recorded decisions" action={<span className="muted tiny">rules {d.decisions?.[0]?.rule_version || "v1"}</span>}>
          <DecisionList items={(d.decisions || []).slice(0, 8)} />
        </Section>
        <Section title="Managers' reports"><ReportList items={(d.reports || []).slice(0, 6)} /></Section>
      </>);
    case "discover": {
      const s = d.discovery || {};
      return (<>
        <Section title="Searches">
          <p className="small">Last search: {when(s.last_scan)} · Next: {when(s.next_scan)}</p>
          {(s.problems || []).map((p: { name: string; detail: string; fix: string }, i: number) => (
            <p key={i} className="small"><span className="pill warn">{p.name}</span> {p.detail} {p.fix}</p>
          ))}
        </Section>
        <Section title="Videos found">
          {(d.found || []).length ? (
            <ul className="op-list">
              {d.found.slice(0, 8).map((s2: any) => (
                <li key={s2.id}><span className="grow">{s2.title || s2.url}</span><span className="muted tiny">{s2.platform} · {s2.status}</span></li>
              ))}
            </ul>
          ) : <p className="muted small">Nothing found yet.</p>}
          <a className="small" href="#/missions/sources">All videos found</a>
        </Section>
      </>);
    }
    case "analyze":
      return (<>
        <Section title="Trends being watched">
          {(d.trends || []).length ? (
            <ul className="op-list">{d.trends.map((t: any) => (
              <li key={t.id}><span className="grow">{t.topic || t.title}</span><span className="muted tiny">score {Math.round(t.score)} (estimate)</span></li>
            ))}</ul>
          ) : <p className="muted small">No active trends yet.</p>}
        </Section>
        <Section title="Which videos to use"><DecisionList items={(d.decisions || []).slice(0, 6)} /></Section>
      </>);
    case "studio":
    case "caption":
      return (<>
        <Section title="Latest clips">
          {(d.clips || []).length ? (
            <ul className="op-list">{d.clips.map((c: any) => (
              <li key={c.id}>
                <span className="grow">{c.title || "Untitled clip"}
                  {d.id === "caption" && c.caption_text && <span className="block muted tiny">“{String(c.caption_text).slice(0, 90)}”</span>}
                </span>
                <span className="muted tiny nowrap">{c.duration ? `${Math.round(c.duration)} s · ` : ""}{c.status}</span>
                <a className="tiny" href={`#/clip/${c.id}`}>Open</a>
              </li>
            ))}</ul>
          ) : <p className="muted small">No clips yet.</p>}
        </Section>
        <Section title="Clip and quality decisions"><DecisionList items={(d.decisions || []).slice(0, 6)} /></Section>
      </>);
    case "schedule":
      return (<>
        {d.publishing_paused && <p className="small"><span className="pill warn"><Icon name="pause" />Publishing paused</span> Clips are still made and checked.</p>}
        <Section title={`Planned posts (${d.timezone || "local time"})`}>
          {(d.upcoming || []).length ? (
            <ul className="op-list">{d.upcoming.map((p: any) => (
              <li key={p.id}><span className="grow">{p.title || "Clip"}</span>
                <span className="muted tiny nowrap">{timeLabel(p.planned_at, tz)} · {p.platform === "youtube" ? "YouTube" : "TikTok"}</span>
                <a className="tiny" href={`#/post/${p.id}`}>Open</a></li>
            ))}</ul>
          ) : <p className="muted small">Nothing is planned.</p>}
          <a className="small" href="#/queue/review">Open the queue</a>
        </Section>
      </>);
    case "dock": {
      const a = d.audience || {};
      return (<>
        <Section title="Who can watch">
          <p className="small">{a.summary}</p>
          {["youtube", "tiktok"].map((p) => a[p] && (
            <p key={p} className="small"><b>{p === "youtube" ? "YouTube" : "TikTok"}:</b> {a[p].label}
              {a[p].confirmed ? <span className="pill good"><Icon name="check" />You confirmed</span>
                : <span className="pill warn"><Icon name="alert" />Not confirmed</span>}</p>
          ))}
          <p className="muted tiny">{a.limits}</p>
          <a className="small" href="#/settings/integrations">Integrations and audience</a>
        </Section>
        <Section title="Recent uploads">
          {(d.recent || []).length ? (
            <ul className="op-list">{d.recent.map((p: any) => (
              <li key={p.id}><span className="grow">{p.title || "Clip"}</span><span className="pill">{p.delivery_label || p.status}</span>
                <a className="tiny" href={`#/post/${p.id}`}>Open</a></li>
            ))}</ul>
          ) : <p className="muted small">Nothing uploaded yet.</p>}
        </Section>
        <Section title="Upload decisions"><DecisionList items={(d.decisions || []).slice(0, 6)} /></Section>
      </>);
    }
    case "system":
      return (<>
        {/* the last readings this panel received; while it cannot read new ones they are shown as Unknown */}
        <HealthList health={d.health && stale ? staleHealth(d.health as Health, lastOk) : d.health as Health} />
        <Section title="Dev Log (read-only)">
          {(d.devlog || []).length ? (
            <ul className="op-list">{d.devlog.slice(0, 8).map((x: any, i: number) => (
              <li key={i}><span className="grow">{x.summary || x.checkpoint}</span><span className="muted tiny nowrap">{x.at ? String(x.at).slice(0, 10) : ""}</span></li>
            ))}</ul>
          ) : <p className="muted small">No development history in this copy.</p>}
          <a className="small" href="#/settings/advanced">Full Dev Log</a>
        </Section>
      </>);
    case "brain":
      return <BrainBody summary={(d.brain || snap.brain) as BrainSummary} />;
    case "workspace":
    case "lounge":
      return d.id === "workspace" ? <Section title="Latest handoffs"><ReportList items={(d.reports || []).slice(0, 8)} /></Section> : null;
    default:
      return null;
  }
}

function ReportList({ items }: { items: RoomDetails["reports"] }) {
  if (!items?.length) return <p className="muted small">No reports yet.</p>;
  return (
    <ul className="op-list">
      {items.map((r: any) => (
        <li key={r.id}>
          <span className="op-mini" aria-hidden="true" style={{ background: BY_ID[r.worker]?.palette.trim }} />
          <span className="grow"><b>{BY_ID[r.worker]?.name || r.worker}</b> → {BY_ID[r.manager]?.name || r.manager}: {r.summary}</span>
          <span className="muted tiny nowrap">{time(r.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

export function HealthList({ health }: { health: Health | undefined }) {
  if (!health) return null;
  return (
    <Section title="Health">
      <ul className="op-list">
        {health.checks.map((c) => (
          <li key={c.id}>
            <HealthBadge status={c.status} label={c.status_label} />
            <span className="grow"><b>{c.label}</b>: {c.reason}{c.action && <span className="block muted tiny">{c.action}</span>}</span>
            <span className="muted tiny nowrap" title="When this was checked">{time(c.checked_at)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function BrainBody({ summary }: { summary: BrainSummary | undefined }) {
  const [confirm, setConfirm] = useState<null | "reset" | { rollback: string }>(null);
  const [s, setS] = useState(summary);
  useEffect(() => setS(summary), [summary]);
  if (!s || !s.label) return <p className="muted small">The Brain has not reported yet.</p>;
  const obs = s.observations || {};
  const pause = async () => {
    try {
      setS(await brainApi.pause(s.state !== "paused"));
      toast(s.state === "paused" ? "Learning resumed" : "Learning paused");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (<>
    <Section title="State">
      <p className="small"><span className="pill">{s.label}</span> {s.message}</p>
      <p className="small">Results stored: {obs.platform_api || 0} from the platforms, {obs.owner_import || 0} you imported, {obs.tester_feedback || 0} from testers.</p>
      <p className="muted tiny">A change needs {s.min_clips} mature clips from your selected viewers and moves at most {Math.round(s.max_step * 100)}% at a time. Your own setting: {s.baseline_target} s.</p>
    </Section>
    {(s.groups || []).length > 0 && (
      <Section title="By platform and audience">
        <ul className="op-list">{s.groups.map((g, i) => (
          <li key={i}><span className="grow">{g.platform} · {g.cohort}</span><span className="muted tiny">{g.message}</span></li>
        ))}</ul>
      </Section>
    )}
    <Section title="Strategies in use">
      {s.strategies.length ? (
        <ul className="op-list">{s.strategies.map((x) => (
          <li key={x.id}><span className="grow">{x.platform}: clip length {x.params?.target_duration ?? "—"} s (version {x.version})
            <span className="block muted tiny">{x.reason}</span></span>
            <button type="button" className="btn btn-small" onClick={() => setConfirm({ rollback: x.id })}>Roll back</button></li>
        ))}</ul>
      ) : <p className="muted small">None. Autopilot uses your own settings.</p>}
    </Section>
    <div className="row wrap">
      <a className="btn btn-small" href="#/clips/feedback"><Icon name="plus" />Add test feedback</a>
      <button type="button" className="btn btn-small" onClick={pause}><Icon name={s.state === "paused" ? "play" : "pause"} />{s.state === "paused" ? "Resume learning" : "Pause learning"}</button>
      <button type="button" className="btn btn-small btn-quiet" onClick={() => setConfirm("reset")}>Reset learning</button>
    </div>
    {confirm === "reset" && (
      <ConfirmDialog title="Reset what the Brain learned?" confirmLabel="Reset learning" danger
        onConfirm={async () => {
          await brainApi.reset();
          toast("Learning reset. Your own settings are used again.");
        }} onClose={() => setConfirm(null)}>
        <p>Every learned strategy stops being used and Autopilot goes back to your own settings. The stored results stay, so learning can start again.</p>
      </ConfirmDialog>
    )}
    {confirm && typeof confirm === "object" && (
      <ConfirmDialog title="Roll back this strategy?" confirmLabel="Roll back"
        onConfirm={async () => {
          const r = await brainApi.rollback(confirm.rollback);
          toast(r.message);
        }} onClose={() => setConfirm(null)}>
        <p>The previous version (or your own setting) is used again for the next videos. Clips already made stay as they are.</p>
      </ConfirmDialog>
    )}
  </>);
}

// ------------------------------------------------------------------ the department cards (list view)
export function DepartmentCards({ snap, onRobot, onRoom }: { snap: Snapshot; onRobot: (id: string) => void; onRoom: (id: RoomId) => void }) {
  const rows = Object.fromEntries(snap.roles.map((r) => [r.id, r]));
  const groups: { id: RoomId; name: string; ids: string[] }[] = [
    { id: "boss", name: ROOM_NAMES.boss, ids: ["command"] },
    ...Object.entries(DEPARTMENTS).map(([dept, v]) => ({ id: dept as RoomId, name: v.name,
      ids: CAST.filter((c) => c.dept === dept).sort((a, b) => (a.rank === "manager" ? -1 : 1) - (b.rank === "manager" ? -1 : 1)).map((c) => c.id) })),
  ];
  return (
    <div className="dept-cards">
      {groups.map((g) => (
        <section key={g.id} className="dept-card" style={{ ["--accent" as string]: (DEPARTMENTS as Record<string, { accent: string }>)[g.id]?.accent || "#ffc94a" } as React.CSSProperties}>
          <h3><button type="button" className="link-btn" onClick={() => onRoom(g.id)}>{g.name}</button></h3>
          <ul>
            {g.ids.map((id) => {
              const r = rows[id];
              return (
                <li key={id}>
                  <button type="button" className="dept-robot" onClick={() => onRobot(id)}>
                    <Portrait id={id} scale={1} pose={POSE_OF[r?.state || "idle"]} animate={false} crop />
                    <span className="grow"><b>{BY_ID[id].name}</b> <span className="muted tiny">{BY_ID[id].title}</span>
                      <span className="block small">{r?.task?.message || (r?.state === "error" ? r.error : "")}</span></span>
                    <StateBadge state={r?.state || "idle"} />
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
