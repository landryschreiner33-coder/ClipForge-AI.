import { useEffect, useState } from "react";
import { api, errorText, Health, PerformanceOverview } from "../api";
import { Icon, toast, usePoll } from "../components/ui";
import { fmtNum } from "../components/stats";
import { navigate } from "../App";
import { ProjectCard } from "./Projects";

export default function Dashboard() {
  const { data: stats } = usePoll(() => api.stats(), [], 3000, (s) => !!s && s.processing > 0);
  const [health, setHealth] = useState<Health | null>(null);
  const [perf, setPerf] = useState<PerformanceOverview | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.performance().then(setPerf).catch(() => setPerf(null));
  }, []);

  return (
    <div className="page">
      <section className="hero">
        <h1>
          Turn long videos into
          <br />
          ready-to-post shorts.
        </h1>
        <p>
          Drop in a podcast, stream, lecture or vlog. ClipFoundry transcribes it locally, finds the strongest moments,
          reframes them to 9:16, adds captions and hooks, and exports MP4s. Everything runs on your machine.
        </p>
        <button className="btn primary xl" onClick={() => navigate("/create")}>
          <Icon name="spark" /> CREATE CLIPS
        </button>
        <div className="pipeline">
          {["VIDEO", "TRANSCRIPT", "BEST MOMENTS", "CLIPS", "9:16", "CAPTIONS", "HOOKS", "EXPORT"].map((s, i) => (
            <span key={s} style={{ display: "contents" }}>
              {i > 0 && <i>&rarr;</i>}
              <span>{s}</span>
            </span>
          ))}
        </div>
      </section>

      <div className="grid grid-4 mt">
        <div className="card stat">
          <b>{stats?.projects ?? "-"}</b>
          <span>Projects</span>
        </div>
        <div className="card stat">
          <b>{stats?.clips ?? "-"}</b>
          <span>Clips generated</span>
        </div>
        <div className="card stat">
          <b>{stats?.processing ?? "-"}</b>
          <span>Processing now</span>
        </div>
        <div className="card stat">
          <b>$0</b>
          <span>Runtime cost (local mode)</span>
        </div>
      </div>

      <div className="grid mt" style={{ gridTemplateColumns: "1fr 320px" }}>
        <div>
          <div className="row between" style={{ marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Recent projects</h3>
            <a className="btn ghost sm" href="#/projects">View all</a>
          </div>
          {stats && stats.recent.length === 0 ? (
            <div className="card empty">
              <Icon name="film" size={34} />
              <h3>No projects yet</h3>
              <p>Upload your first long video to generate clips.</p>
              <button className="btn primary" onClick={() => navigate("/create")}>Create clips</button>
            </div>
          ) : (
            <div className="proj-grid">
              {stats?.recent.map((p) => <ProjectCard key={p.id} p={p} />)}
            </div>
          )}
        </div>
        <div className="card">
          <h3>System</h3>
          {!health ? (
            <div className="muted">Checking...</div>
          ) : (
            <div className="sys-list">
              <SysRow k="FFmpeg" ok={!!health.ffmpeg} v={health.ffmpeg ? "Found" : "Missing"} />
              <SysRow k="GPU (CUDA)" ok={health.cuda && health.gpu.libs_ok !== false}
                v={health.gpu.name ? health.gpu.name.replace(/^NVIDIA (GeForce )?/, "") : "Not found"}
                neutral={!health.gpu.name} />
              <SysRow k="GPU encoder" ok={health.nvenc} v={health.nvenc ? "NVENC" : "x264 (CPU)"} neutral={!health.nvenc} />
              <SysRow k="Transcription" ok={health.whisper_installed} neutral={health.whisper.mode === "cpu"}
                v={`${health.whisper.mode === "gpu" ? "GPU" : "CPU"} mode · ${health.whisper.model} · ${health.whisper.compute_type}`} />
              <SysRow k="Whisper model" ok={health.whisper.cached} neutral={!health.whisper.cached}
                v={health.whisper.cached ? "Downloaded" : "Downloads on first run"} />
              <SysRow k="Clip scoring" ok v={health.ai_provider} />
              {health.whisper.fix && (
                <div className="notice warn small block">
                  <b>{health.whisper.mode === "gpu" ? "GPU transcription may fail." : "GPU not used for transcription."}</b>{" "}
                  {health.whisper.problem}
                  {health.whisper.mode === "gpu" ? " ClipFoundry still tries the GPU first and falls back to the CPU only if it fails." : ""}
                  {" "}Fix: {health.whisper.fix}
                </div>
              )}
              {health.whisper.last_run?.warning && (
                <div className="notice warn small block">
                  <b>Last transcription:</b> {health.whisper.last_run.warning}
                  {health.whisper.last_run.fix ? ` Fix: ${health.whisper.last_run.fix}` : ""}
                </div>
              )}
              {!health.ffmpeg && (
                <div className="notice bad small">
                  FFmpeg is required. Install it with <code>winget install Gyan.FFmpeg</code> and restart, or set its
                  path in Settings.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {perf && <PerformanceCard perf={perf} setPerf={setPerf} />}
    </div>
  );
}

function PerformanceCard({ perf, setPerf }: { perf: PerformanceOverview; setPerf: (p: PerformanceOverview) => void }) {
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try {
      const r = await api.refreshAllStats();
      setPerf(await api.performance());
      toast(r.failed.length ? `Updated ${r.refreshed}; ${r.failed.length} failed: ${r.failed[0].error}` : `Updated ${r.refreshed} upload(s)`, r.failed.length > 0);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const t = perf.totals;
  const tile = (key: string, label: string, unit = "") => (
    <div className="card stat" title={t[key]?.total === null ? "No platform reported this yet" : `From ${t[key]?.publications} of ${perf.published} uploads`}>
      <b>{t[key]?.total === null || t[key]?.total === undefined ? "—" : `${fmtNum(Math.round(t[key].total as number))}${unit}`}</b>
      <span>{label}{t[key]?.total !== null && t[key]?.publications < perf.published ? ` (${t[key].publications} of ${perf.published})` : ""}</span>
    </div>
  );
  const check = perf.check;
  return (
    <div className="card mt">
      <div className="row between wrap">
        <h3 style={{ margin: 0 }}>Performance of published clips</h3>
        <div className="row">
          {perf.last_refreshed && <span className="small muted">Updated {new Date(perf.last_refreshed * 1000).toLocaleString()}</span>}
          <button className="btn sm" disabled={busy || !perf.published} onClick={refresh}><Icon name="refresh" size={13} /> Refresh stats</button>
          <a className="btn sm ghost" href="/api/performance/dataset" title="Your clips' scores at publish time next to their real numbers, for analysis">
            <Icon name="download" size={13} /> Data (CSV)
          </a>
        </div>
      </div>
      <p className="small muted" style={{ marginTop: 6 }}>
        Real numbers read from YouTube and TikTok for your own uploads. Metrics a platform does not report are shown as “—”;
        nothing is estimated.
      </p>
      {perf.published === 0 ? (
        <div className="small muted">Nothing published yet.</div>
      ) : (
        <>
          <div className="grid grid-4 mt-s">
            {tile("views", "Views")}
            {tile("likes", "Likes")}
            {tile("comments", "Comments")}
            {tile("shares", "Shares")}
          </div>
          <div className="small muted mt-s">
            {check.spearman === null
              ? `Comparing Viral Potential with real views needs at least ${check.min_samples} uploads with view counts (now ${check.samples}).`
              : `Viral Potential vs. real views over ${check.samples} uploads: rank correlation ${check.spearman.toFixed(2)} (1 = perfect order, 0 = no relation).`}
          </div>
          <div className="perf-list">
            {perf.items.slice(0, 8).map((i) => (
              <div className="perf-item" key={i.id}>
                <span className="badge">{i.platform === "youtube" ? "YouTube" : "TikTok"}</span>
                <a className="t" href={`#/publish/${i.clip_id}`} title={i.title}>{i.title}</a>
                <span title="Views">{fmtNum(i.stats?.views)} views</span>
                <span title="Likes">{fmtNum(i.stats?.likes)} likes</span>
                <span className="muted" title="Viral Potential estimate at publish time">VP {i.viral_potential ?? "—"}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SysRow({ k, v, ok, neutral }: { k: string; v: string; ok: boolean; neutral?: boolean }) {
  return (
    <div className="sys-item">
      <span className="k">{k}</span>
      <span className={`badge ${neutral ? "" : ok ? "good" : "bad"}`}>{v}</span>
    </div>
  );
}
