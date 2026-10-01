import { useEffect, useState } from "react";
import { api, errorText, Health, timeAgo } from "../api";
import { ActionItem, ap, AutopilotStatus, Job, Metric, TrendSignal, WORKER_BADGE } from "../autopilot";
import { at, num, plural } from "../format";
import { PLATFORMS } from "./apShared";
import { PLATFORM_NAME } from "./accounts";
import {
  ConfirmDialog, Dialog, Icon, IconName, LinkTabs, PlatformName, Pill, ProgressBar, Skel, toast, Tone, usePoll,
} from "./ui";

/**
 * Autopilot → Advanced: the technical views for troubleshooting (System, Jobs, Learning). Normal use never needs
 * them; the words worker, job, queue and quota are allowed here and only here.
 */
export default function AdvancedView({ which, st, refresh }: {
  which: string; st: AutopilotStatus; refresh: () => void;
}) {
  return (
    <>
      <LinkTabs label="Advanced" current={which} tabs={[
        { id: "system", href: "#/autopilot/system", label: "System" },
        { id: "jobs", href: "#/autopilot/jobs", label: "Jobs" },
        { id: "learning", href: "#/autopilot/learning", label: "Learning" },
      ]} />
      <p className="small muted">For troubleshooting. Normal use never needs these pages.</p>
      {which === "jobs" ? <JobsView />
        : which === "learning" ? <LearningView /> : <SystemView st={st} refresh={refresh} />}
    </>
  );
}

/** Panels side by side are as tall as the taller one: keep each panel's content at its top. */
const TOP = { alignContent: "start" } as const;

// ------------------------------------------------------------------ system
const WORKER_LOOK: Record<string, [Tone, IconName]> = {
  idle: ["neutral", "dot"], working: ["info", "refresh"], waiting: ["warn", "clock"], completed: ["good", "check"],
  failed: ["bad", "alert"],
};
const PROVIDER: Record<string, [Tone, string]> = {
  ok: ["good", "Working"], unavailable: ["neutral", "Unavailable"], not_configured: ["warn", "Not set up"],
  error: ["bad", "Error"], quota: ["warn", "Quota used up"],
};
const ACTION_LINK: Record<string, string> = {
  approve: "#/posts/review", publish: "#/posts/problems", rights: "#/autopilot/sources",
  source_file: "#/autopilot/sources", youtube: "#/settings", quota: "#/settings/advanced",
  gpu: "#/settings/advanced", workers: "#/autopilot/jobs",
};
const ACTION_LOOK: Record<string, [Tone, IconName]> = {
  error: ["bad", "alert"], warning: ["warn", "alert"], action: ["warn", "clock"],
};

function SystemView({ st, refresh }: { st: AutopilotStatus; refresh: () => void }) {
  const t = st.target;
  const host = st.workers.host;
  return (
    <>
      <section className="panel" style={TOP} aria-labelledby="sys-today">
        <div className="panel-head">
          <h2 id="sys-today">Today's numbers</h2>
          <a className="btn btn-quiet btn-small" href="#/posts/scheduled">Open Posts</a>
        </div>
        <dl className="kv daily">
          <dt>Daily target</dt>
          <dd><b className="tnum">{t.published}</b> of {t.daily} unique clips posted today. {t.note}</dd>
          <dt>Platform posts today</dt>
          <dd>{t.published_posts} published, {t.scheduled_posts} scheduled ({PLATFORMS.map((p) => {
            const c = t.posts_by_platform?.[p];
            return `${PLATFORM_NAME[p]} ${c?.published ?? 0} published, ${c?.scheduled ?? 0} scheduled`;
          }).join("; ")})</dd>
          <dt>Clips</dt>
          <dd>{t.processed} processed · {t.scheduled} scheduled today</dd>
          <dt>Source videos today</dt>
          <dd>{st.sources_today.counted} of {st.sources_per_day} chosen</dd>
          <dt>Jobs in the queue</dt>
          <dd>{st.queue.size}</dd>
          <dt>Next post</dt>
          <dd>{st.next ? <>
            {at(st.next.planned_at, st.timezone)} · {PLATFORM_NAME[st.next.platform]}
            {" "}· “{st.next.title.slice(0, 80)}” ({st.next.status.replace(/_/g, " ")})
          </> : "Nothing scheduled yet"}</dd>
        </dl>
      </section>

      {st.actions.length > 0 && (
        <section className="panel" style={TOP} aria-labelledby="sys-actions">
          <h2 id="sys-actions">All action items ({st.actions.length})</h2>
          <div className="rows">{st.actions.map((a) => <ActionRow key={a.id} a={a} onDone={refresh} />)}</div>
        </section>
      )}

      <div className="cols-2">
        <section className="panel" style={TOP} aria-labelledby="sys-workers">
          <div className="panel-head">
            <h2 id="sys-workers">Workers ({st.workers.workers.length})</h2>
            <Pill tone={host.alive ? "good" : "bad"} icon={host.alive ? "check" : "alert"}>
              {host.alive ? `Running ${host.mode === "separate" ? "in their own process" : "in the app"}`
                : "Not running"}
            </Pill>
          </div>
          <div className="rows workers">
            {st.workers.workers.map((w) => {
              const [tone, icon] = WORKER_LOOK[w.status] || ["neutral", "dot"];
              const queued = (w.queue.queued || 0) + (w.queue.retrying || 0) + (w.queue.waiting || 0);
              return (
                <div key={w.name} className="row wrap worker" style={{ padding: "8px 0" }}>
                  <Pill tone={tone} icon={icon}>{(WORKER_BADGE[w.status] || [w.status])[0]}</Pill>
                  <b className="small" style={{ minWidth: 120 }}>{w.label}</b>
                  <span className="tiny faint grow break" title={w.last_error || w.message}>
                    {w.stage ? `${w.stage} · ` : ""}{w.message}{w.stale ? ` (last heard ${timeAgo(w.heartbeat)})` : ""}
                  </span>
                  {queued > 0 && <span className="tiny faint">{queued} queued</span>}
                </div>
              );
            })}
          </div>
        </section>
        <GpuPanel st={st} />
      </div>

      <div className="cols-2">
        <ComputerPanel />
        <PlatformsPanel st={st} />
      </div>

      <div className="cols-2">
        <QuotaPanel st={st} />
        <section className="panel" style={TOP} aria-labelledby="sys-events">
          <h2 id="sys-events">Recent events</h2>
          {st.events.length ? (
            <div className="rows">
              {st.events.slice(0, 12).map((e) => (
                <div key={e.id} className="row top event" style={{ padding: "8px 0" }}>
                  <span className="tiny faint nowrap" style={{ width: 80, flex: "none" }}>{timeAgo(e.at)}</span>
                  <span className={`small break ${levelText(e.level)}`}>{e.message}</span>
                </div>
              ))}
            </div>
          ) : <p className="small muted">Nothing yet.</p>}
        </section>
      </div>

      <TrendsPanel trends={st.trends} providers={st.providers} />
    </>
  );
}

const levelText = (level: string) => level === "error" ? "bad-text" : level === "warning" ? "warn-text" : "";

function ActionRow({ a, onDone }: { a: ActionItem; onDone: () => void }) {
  const link = ACTION_LINK[a.kind] || "";
  const [tone, icon] = ACTION_LOOK[a.level] || ["warn", "alert"];
  return (
    <div className={`need ${tone}`}>
      <Icon name={icon} />
      <div className="need-body">
        <span className="need-title">{a.title}</span>
        {a.detail && <span className="small muted">{a.detail}</span>}
        {a.fix && <span className="small"><b>What to do:</b> {a.fix}</span>}
      </div>
      <div className="need-actions">
        {link && <a className="btn btn-small" href={link}>Open</a>}
        <button type="button" className="btn btn-small btn-quiet" onClick={async () => {
          try {
            await ap.dismiss(a.key);
          } catch (e) {
            toast(errorText(e), true);
          }
          onDone();
        }}>Dismiss</button>
      </div>
    </div>
  );
}

function GpuPanel({ st }: { st: AutopilotStatus }) {
  const g = st.gpu;
  const mem = g.memory;
  const last = g.last_transcription;
  const fell = !!last && last.requested_device === "cuda" && last.device !== "cuda";
  return (
    <section className="panel" style={TOP} aria-labelledby="sys-gpu">
      <div className="panel-head">
        <h2 id="sys-gpu">GPU</h2>
        <span className="small muted">One heavy GPU job at a time</span>
      </div>
      <dl className="kv">
        <dt>Device</dt>
        <dd>{g.available ? <Pill tone="neutral" icon="cpu">{g.name || "NVIDIA GPU"}</Pill>
          : <Pill tone="warn" icon="alert">No CUDA GPU detected</Pill>}</dd>
        <dt>Transcription plan</dt>
        <dd>{g.mode === "gpu" ? `GPU · ${g.whisper.model} · ${g.whisper.compute_type}`
          : `CPU · ${g.whisper.reason}`}</dd>
        {mem && <>
          <dt>Memory</dt>
          <dd className="stack">
            <span>
              {(mem.used_mb / 1024).toFixed(1)} of {(mem.total_mb / 1024).toFixed(1)} GB used · {mem.utilization}% busy
            </span>
            <ProgressBar value={mem.used_mb / Math.max(1, mem.total_mb)} label="GPU memory used" />
          </dd>
        </>}
        <dt>Now</dt>
        <dd>{g.holder ? <>
          <Pill tone="info" icon="refresh">{g.holder.kind}</Pill> {g.holder.label.slice(0, 60)}
        </> : "Free"}</dd>
        {g.waiting.length > 0 && <><dt>Waiting</dt><dd>{g.waiting.map((w) => w.kind).join(", ")}</dd></>}
        <dt>Last transcription</dt>
        <dd>{last ? <>
          {fell ? <Pill tone="warn" icon="cpu">Ran on the CPU instead of the GPU</Pill>
            : <Pill tone="good" icon="check">Ran on the {last.device === "cuda" ? "GPU" : "CPU"}</Pill>}
          {typeof last.speed === "number" && last.speed > 0 ? ` · ${last.speed}× real time` : ""}
          {last.at ? ` · ${timeAgo(last.at)}` : ""}
        </> : "None yet"}</dd>
        <dt>CPU fallback in Autopilot</dt>
        <dd>{st.settings.autopilot_allow_cpu_fallback ? "Allowed (Settings → Advanced)"
          : "Off: Autopilot pauses instead (Settings → Advanced)"}</dd>
      </dl>
      {(g.problem || fell) && (
        <div className="banner warn">
          <Icon name="alert" />
          <div className="grow small">
            <span>{fell ? last?.warning || "The last transcription ran on the CPU." : g.problem}</span>
            {(g.fix || last?.fix) && <span><b>What to do:</b> {fell ? last?.fix || g.fix : g.fix}</span>}
          </div>
        </div>
      )}
      {g.last_error && (
        <p className="small muted">Last GPU error ({timeAgo(g.last_error.at)}): {g.last_error.error}</p>
      )}
    </section>
  );
}

/** What the old Dashboard's System card showed: the tools ClipFoundry found on this computer. */
function ComputerPanel() {
  const [h, setH] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    api.health().then(setH).catch(() => setFailed(true));
  }, []);
  return (
    <section className="panel" style={TOP} aria-labelledby="sys-pc">
      <h2 id="sys-pc">This computer</h2>
      {!h ? (failed ? <p className="small muted">Unknown: ClipFoundry did not answer.</p>
        : <Skel className="skel-block" style={{ height: 100 }} />) : (
        <>
          <dl className="kv">
            <dt>FFmpeg</dt>
            <dd>{h.ffmpeg ? <Pill tone="good" icon="check">Found</Pill>
              : <Pill tone="bad" icon="alert">Missing</Pill>}</dd>
            <dt>Video encoder</dt>
            <dd>{h.nvenc ? "GPU (NVENC)" : "CPU (x264)"}</dd>
            <dt>Transcription</dt>
            <dd>{h.whisper.mode === "gpu" ? "GPU" : "CPU"} · {h.whisper.model} · {h.whisper.compute_type}</dd>
            <dt>Whisper model</dt>
            <dd>{h.whisper.cached ? "Downloaded" : "Downloads the first time it is needed"}</dd>
            <dt>Clip scoring</dt>
            <dd>{h.ai_provider}</dd>
            <dt>Data folder</dt>
            <dd><code className="break">{h.data_dir}</code></dd>
          </dl>
          {!h.ffmpeg && (
            <p className="small bad-text">FFmpeg is required. Install it with <code>winget install Gyan.FFmpeg</code>
              {" "}and restart, or set its path in Settings → Advanced.</p>
          )}
          {h.whisper.fix && <p className="small"><b>What to do:</b> {h.whisper.problem} {h.whisper.fix}</p>}
        </>
      )}
    </section>
  );
}

function PlatformsPanel({ st }: { st: AutopilotStatus }) {
  const s = st.settings;
  return (
    <section className="panel" style={TOP} aria-labelledby="sys-platforms">
      <div className="panel-head">
        <h2 id="sys-platforms">Platforms</h2>
        <a className="btn btn-quiet btn-small" href="#/settings">Accounts</a>
      </div>
      <div className="rows">
        {PLATFORMS.map((p) => {
          const acc = st.platforms[p];
          return (
            <div key={p} className="stack" style={{ padding: "10px 0" }}>
              <div className="row wrap">
                <PlatformName platform={p} />
                {!s[`autopilot_${p}`] && <Pill tone="neutral" icon="info">Not used by Autopilot</Pill>}
                {acc.connected ? (acc.needs_reconnect ? <Pill tone="bad" icon="alert">Reconnect needed</Pill>
                  : <Pill tone="good" icon="check">Connected: {acc.name || acc.account_id}</Pill>)
                  : <Pill tone="warn" icon="alert">{acc.configured ? "Not connected" : "Not set up"}</Pill>}
              </div>
              {acc.restriction && <span className="small muted break">{acc.restriction}</span>}
            </div>
          );
        })}
      </div>
      <p className="small muted">Every post needs your OK, or for YouTube the automatic-publishing permission.
        {s.autopilot_auto_publish ? " Approved posts are published at their time by themselves."
          : " Approved posts wait until you press Publish now."}</p>
    </section>
  );
}

function QuotaPanel({ st }: { st: AutopilotStatus }) {
  const q = st.quota;
  return (
    <section className="panel" style={TOP} aria-labelledby="sys-quota">
      <div className="panel-head">
        <h2 id="sys-quota">YouTube API quota</h2>
        <span className="small muted">
          Resets {new Date(q.resets_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
        </span>
      </div>
      {Object.entries(q.buckets).map(([k, b]) => (
        <div key={k} className="stack quota">
          <span className="row small"><span className="grow">{b.label}</span>
            <span className="tnum">
              {b.used} of {b.budget}{b.exhausted ? " · used up" : ""} · projected {b.projected}
            </span>
          </span>
          <ProgressBar value={b.used / Math.max(1, b.budget)} label={`${b.label}: quota used`} />
        </div>
      ))}
      {q.warnings.map((w, i) => <p key={i} className="small warn-text">{w}</p>)}
      <p className="tiny faint">Counted by ClipFoundry. Discovery uses only its share and never the quota kept for
        publishing and statistics.</p>
    </section>
  );
}

function MetricCell({ m, label }: { m?: Metric; label: string }) {
  if (!m) return null;
  const v = m.value;
  const text = v == null ? "—" : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
    : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : num(v);
  const why = `${label}: ${m.status === "observed" ? "as the platform reported it" : m.status === "estimated"
    ? "calculated by ClipFoundry" : "not reported"}${m.note ? ` (${m.note})` : ""}`;
  return (
    <span className={`small ${v == null ? "metric-missing" : ""}`} title={why}>
      {text} <span className="faint">{label}</span>
    </span>
  );
}

function TrendsPanel({ trends, providers }: { trends: TrendSignal[]; providers: AutopilotStatus["providers"] }) {
  const [busy, setBusy] = useState(false);
  return (
    <section className="panel" style={TOP} aria-labelledby="sys-trends">
      <div className="panel-head">
        <h2 id="sys-trends">Trend opportunities</h2>
        <button type="button" className="btn btn-small" disabled={busy} onClick={async () => {
          setBusy(true);
          try {
            await ap.scan();
            toast("Trend scan started");
          } catch (e) {
            toast(errorText(e), true);
          }
          setBusy(false);
        }}><Icon name="refresh" />Scan now</button>
      </div>
      <div className="row wrap" role="group" aria-label="Where trends come from">
        {Object.entries(providers).map(([k, p]) => {
          const [tone, word] = PROVIDER[p.status] || ["neutral", p.status];
          return (
            <Pill key={k} tone={tone} title={`${p.detail}${p.fix ? ` · ${p.fix}` : ""}`}>{p.name}: {word}</Pill>
          );
        })}
      </div>
      {trends.length ? (
        <div className="rows">
          {trends.map((s) => (
            <div key={s.id} className="row wrap trend" style={{ padding: "10px 0" }}>
              <span className="score" title={s.notes.join(" ")}>
                <b>{s.score == null ? "—" : Math.round(s.score)}</b>estimate</span>
              <span className="grow stack" style={{ gap: 0, flexBasis: 240 }}>
                <a className="post-title break" href={s.url} target="_blank" rel="noreferrer">{s.title}
                  <span className="sr-only"> (opens a new tab)</span></a>
                <span className="tiny faint">{[s.channel_title, s.kind === "live" ? "Live" : "", s.topic || s.category,
                  s.score_mode === "platform_order" ? "YouTube's order" : ""].filter(Boolean).join(" · ")}</span>
              </span>
              <span className="row wrap">
                <MetricCell m={s.metrics.views} label="views" />
                <MetricCell m={s.metrics.live_viewers?.value != null ? s.metrics.live_viewers : undefined}
                  label="watching" />
                <MetricCell m={s.metrics.likes} label="likes" />
              </span>
            </div>
          ))}
        </div>
      ) : <p className="small muted">Nothing found yet. Connect YouTube (Settings → Accounts) or add a YouTube API key
        (Settings → Advanced).</p>}
      <p className="tiny faint">Numbers are as the platform reported them; “—” means not reported. Scores are
        ClipFoundry's own estimates, not platform numbers.</p>
    </section>
  );
}

// ------------------------------------------------------------------ jobs
const JOB_LOOK: Record<Job["status"], [Tone, IconName, string]> = {
  queued: ["neutral", "clock", "Queued"], running: ["info", "refresh", "Running"],
  waiting: ["warn", "clock", "Waiting"], retrying: ["info", "refresh", "Retrying"],
  completed: ["good", "check", "Completed"], failed: ["bad", "alert", "Failed"], canceled: ["neutral", "x", "Canceled"],
};
const ACTIVE = ["queued", "running", "waiting", "retrying"];
type LogLine = { at: number; level: string; event: string; message: string };

function JobsView() {
  const [status, setStatus] = useState("queued,running,waiting,retrying,failed");
  const { data: jobs, refresh } = usePoll(() => ap.jobs(status), [status], 3000, () => true);
  const [logs, setLogs] = useState<{ job: Job; lines: LogLine[] } | null>(null);
  const [canceling, setCanceling] = useState<Job | null>(null);
  const showLog = async (j: Job) => {
    try {
      setLogs({ job: j, lines: await ap.jobLogs(j.id) });
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const retry = async (j: Job) => {
    try {
      await ap.retryJob(j.id);
      toast("Queued again");
      refresh();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (
    <section className="panel" style={TOP} aria-labelledby="jobs-h">
      <div className="panel-head">
        <h2 id="jobs-h">Jobs</h2>
        <span className="row">
          <label className="sr-only" htmlFor="job-filter">Show</label>
          <select id="job-filter" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
            <option value="queued,running,waiting,retrying,failed">Active and failed</option>
            <option value="">All (latest 150)</option>
            <option value="completed">Completed</option>
            <option value="canceled">Canceled</option>
          </select>
        </span>
      </div>
      {jobs === null ? <Skel className="skel-block" /> : jobs.length ? (
        <div className="rows jobs">
          {jobs.map((j) => {
            const [tone, icon, word] = JOB_LOOK[j.status] || ["neutral", "info", j.status];
            return (
              <div key={j.id} className="row top wrap job" style={{ padding: "12px 0" }}>
                <Pill tone={tone} icon={icon}>{word}</Pill>
                <span className="grow stack" style={{ gap: 2, flexBasis: 260 }}>
                  <b>{j.kind.replace(/_/g, " ")}</b>
                  <span className="tiny faint">{j.worker.replace(/_/g, " ")} · attempt {j.attempts} of {j.max_attempts}
                    {j.priority >= 100 ? " · started by you" : ""} · {timeAgo(j.updated_at)}</span>
                  {(j.message || j.wait_reason) && (
                    <span className="small break">{j.message}{j.wait_reason ? ` (${j.wait_reason})` : ""}</span>
                  )}
                  {j.error && <span className="small bad-text break">{j.error}</span>}
                  {j.fix && <span className="small"><b>What to do:</b> {j.fix}</span>}
                  {j.status === "running" && j.progress > 0 && (
                    <ProgressBar value={j.progress}
                      label={`Progress of ${j.kind.replace(/_/g, " ")}, as the job reports it`} />
                  )}
                </span>
                <span className="row">
                  <button type="button" className="btn btn-small btn-quiet" onClick={() => showLog(j)}>Log</button>
                  {ACTIVE.includes(j.status) && (
                    <button type="button" className="btn btn-small btn-danger" onClick={() => setCanceling(j)}>
                      Cancel…</button>
                  )}
                  {["failed", "canceled"].includes(j.status) && (
                    <button type="button" className="btn btn-small" onClick={() => retry(j)}>Retry</button>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ) : <p className="small muted">No jobs.</p>}
      {logs && (
        <Dialog title={`Log: ${logs.job.kind.replace(/_/g, " ")}`} wide onClose={() => setLogs(null)}
          actions={<button type="button" className="btn" onClick={() => setLogs(null)}>Close</button>}>
          {logs.lines.length ? (
            <div className="rows logs">
              {logs.lines.map((l, i) => (
                <div key={i} className="row top small" style={{ padding: "6px 0" }}>
                  <span className="tiny faint nowrap">{new Date(l.at * 1000).toLocaleTimeString()}</span>
                  <span className={`break ${levelText(l.level)}`}><b>{l.event}</b> {l.message}</span>
                </div>
              ))}
            </div>
          ) : <p className="small muted">This job has no log lines.</p>}
        </Dialog>
      )}
      {canceling && (
        <ConfirmDialog title={`Cancel “${canceling.kind.replace(/_/g, " ")}”?`} confirmLabel="Cancel job"
          cancelLabel="Keep it" danger onClose={() => setCanceling(null)} onConfirm={async () => {
            await ap.cancelJob(canceling.id);
            toast("Canceled: it stops at its next safe point");
            refresh();
          }}>
          <p className="muted">A running job stops at its next safe point; a queued one never starts. You can retry it
            afterwards.</p>
        </ConfirmDialog>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ learning
function LearningView() {
  const { data } = usePoll(() => ap.learning(), [], 15000, () => true);
  const [busy, setBusy] = useState(false);
  if (!data) return <Skel className="skel-block" />;
  const s = data.status;
  return (
    <div className="cols-2">
      <section className="panel" style={TOP} aria-labelledby="learn-h">
        <div className="panel-head">
          <h2 id="learn-h">What your results show</h2>
          <button type="button" className="btn btn-small" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              await ap.learn();
              toast("Learning started");
            } catch (e) {
              toast(errorText(e), true);
            }
            setBusy(false);
          }}>Learn now</button>
        </div>
        <p className="small">{s.message || "Nothing learned yet."}</p>
        <p className="small muted">Posts with real numbers: {s.samples} (needs {data.min_samples}).</p>
        {s.note && <p className="small warn-text">{s.note}</p>}
        {s.findings?.length ? <ul className="flags">{s.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
          : <p className="small muted">No conclusions are drawn until there is enough data from your own posts. Posting
            times are spread evenly until then.</p>}
      </section>
      <section className="panel" style={TOP} aria-labelledby="weights-h">
        <h2 id="weights-h">How the scores are weighted</h2>
        {data.weights.length ? (
          <dl className="kv">
            {data.weights.map((w) => (
              <div key={w.key} style={{ display: "contents" }}>
                <dt>{w.key}</dt>
                <dd>
                  weight {w.lift.toFixed(3)} · rank agreement with your results {w.data.rho.toFixed(2)}
                  {" "}over {plural(w.n, "post")}
                </dd>
              </div>
            ))}
          </dl>
        ) : <p className="small muted">Default weights (not enough results to adjust them).</p>}
        <h3>Reliable groups ({data.metrics.length})</h3>
        {data.metrics.length ? (
          <dl className="kv">
            {data.metrics.slice(0, 20).map((m, i) => (
              <div key={i} style={{ display: "contents" }}>
                <dt>{m.platform} · {data.labels[m.dimension] || m.dimension} {m.key}</dt>
                <dd>{m.lift.toFixed(2)}× · {plural(m.n, "post")}</dd>
              </div>
            ))}
          </dl>
        ) : <p className="small muted">None yet.</p>}
      </section>
    </div>
  );
}
