import { useMemo, useState } from "react";
import { api, Clip, clipDownloadUrl, clipThumbUrl, clipVideoUrl, downloadZip, fmtPrecise, fmtTime, Project } from "../api";
import { Icon, Modal, ScoreBadge, Segmented, StatusBadge, toast, usePoll } from "../components/ui";
import { ESTIMATE_NOTE, QualitySummary, StructureChips, SubscoreLine, ViralPanel } from "../components/viral";
import { navigate } from "../App";

const STAGES = ["Prepare", "Transcribe", "Find moments", "Score & hooks", "Render 9:16"];
const STAGE_STEP: Record<string, number> = {
  queued: -1, download: 0, probe: 0, audio: 0, transcribe: 1, candidates: 2, scoring: 3, render: 4, done: 5,
};

function isBusy(p: Project | null) {
  return !!p && (p.status === "processing" || p.status === "queued" || p.status === "uploading" ||
    (p.clips || []).some((c) => c.status === "rendering" || c.status === "queued"));
}

export default function ProjectView({ id }: { id: string }) {
  const { data: p, error, refresh } = usePoll(() => api.project(id), [id], 1500, isBusy);
  const [preview, setPreview] = useState<Clip | null>(null);
  const [exporting, setExporting] = useState(false);
  const [regen, setRegen] = useState(false);

  const clips = p?.clips || [];
  const ready = clips.filter((c) => c.status === "ready");
  const selected = ready.filter((c) => c.selected);

  const toggleSel = async (c: Clip) => {
    await api.patchClip(c.id, { selected: !c.selected });
    refresh();
  };
  const selectAll = async (on: boolean) => {
    await Promise.all(ready.map((c) => api.patchClip(c.id, { selected: on })));
    refresh();
  };
  const exportZip = async (ids: string[] | null) => {
    setExporting(true);
    try {
      await downloadZip(id, ids);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setExporting(false);
    }
  };

  if (error && !p) return <div className="page"><div className="notice bad">{error}</div></div>;
  if (!p) return <div className="page"><div className="spinner" /></div>;

  const busy = p.status === "processing" || p.status === "queued";
  const stepIdx = STAGE_STEP[p.stage || "queued"] ?? -1;
  const info = p.info || {};

  return (
    <div className="page">
      <div className="crumbs"><a href="#/projects">Projects</a> / {p.name}</div>
      <div className="page-head">
        <div>
          <h1>{p.name}</h1>
          <p>
            {p.duration ? `${fmtTime(p.duration)} · ${p.width}×${p.height} · ${Math.round(p.fps)} fps` : p.source_filename}
            {info.transcription
              ? ` · transcribed on ${info.transcription.device === "cuda" ? "GPU" : "CPU"} (${info.transcription.model}, ${info.transcription.compute_type}, ${info.transcription.speed}x realtime)`
              : info.transcript_source ? ` · transcript: ${String(info.transcript_source).replace("faster-whisper:", "Whisper ")}` : ""}
          </p>
        </div>
        <div className="row">
          <StatusBadge status={p.status} />
          {busy ? (
            <button className="btn danger" onClick={() => api.cancelProject(id).then(refresh)}>Cancel</button>
          ) : (
            <button className="btn" onClick={() => setRegen(true)}><Icon name="refresh" size={16} /> Regenerate</button>
          )}
        </div>
      </div>

      {busy && (
        <div className="card">
          <div className="row between">
            <b>{p.message || "Working..."}</b>
            <span className="muted">{Math.round(p.progress * 100)}%</span>
          </div>
          <div className="steps">
            {STAGES.map((label, i) => {
              const cls = stepIdx > i ? "done" : stepIdx === i ? "active" : "";
              return (
                <div key={label} className={`step ${cls}`}>
                  {cls === "done" ? <Icon name="check" size={14} /> : <span className="dot" />} {label}
                </div>
              );
            })}
          </div>
          <div className="bar"><div style={{ width: `${Math.max(2, p.progress * 100)}%` }} /></div>
          <div className="small muted mt-s">
            First run downloads the Whisper model. Long videos take a while on CPU: you can leave this page open or come back later.
          </div>
        </div>
      )}

      {p.status === "error" && <div className="notice bad mt"><b>Processing failed.</b>&nbsp;{p.error}</div>}
      {info.transcription?.warning && (
        <div className="notice warn mt block">
          <b>Transcribed on {info.transcription.device === "cuda" ? "the GPU" : "the CPU"}.</b>&nbsp;{info.transcription.warning}
          {info.transcription.fix ? ` Fix: ${info.transcription.fix}` : ""}
        </div>
      )}
      {info.stage2?.warning && <div className="notice warn mt">{info.stage2.warning}</div>}

      {!busy && info.quality && <QualitySummary q={info.quality} clipCount={clips.length} />}

      {clips.length > 0 && (
        <>
          <div className="notice mt">
            <Icon name="spark" size={16} />
            <div>
              Clips are ranked by <b>Viral Potential</b> ({info.stage2?.provider || "local analysis"}): hook strength,
              curiosity, emotion, information density, payoff, standalone context, opening, pacing, uniqueness, speaker
              clarity and retention, with a bonus for a clear hook → context → payoff structure. {ESTIMATE_NOTE}
            </div>
          </div>
          <div className="toolbar">
            <div className="row wrap">
              <b>{clips.length} clip{clips.length === 1 ? "" : "s"}</b>
              {info.candidates_found ? <span className="muted small">from {info.candidates_found} candidates</span> : null}
              <button className="btn ghost sm" onClick={() => selectAll(selected.length !== ready.length)}>
                {selected.length === ready.length && ready.length ? "Clear selection" : "Select all"}
              </button>
            </div>
            <div className="row wrap">
              <button className="btn" disabled={!selected.length || exporting} onClick={() => exportZip(selected.map((c) => c.id))}>
                <Icon name="zip" size={16} /> Download selected ({selected.length})
              </button>
              <button className="btn primary" disabled={!ready.length || exporting} onClick={() => exportZip(null)}>
                <Icon name="download" size={16} /> {exporting ? "Preparing ZIP..." : "Download all (ZIP)"}
              </button>
            </div>
          </div>
          <div className="clip-grid">
            {clips.map((c) => (
              <ClipCard key={c.id} c={c} onPreview={() => setPreview(c)} onToggle={() => toggleSel(c)} />
            ))}
          </div>
        </>
      )}

      {!busy && p.status === "ready" && clips.length === 0 && (
        <div className="card empty mt">
          <Icon name="scissors" size={34} />
          <h3>No moment passed the quality bar</h3>
          <p>
            ClipFoundry does not pad the results with weak clips. Try a different clip length with Regenerate, or lower
            the minimum Viral Potential in Settings if you want to see weaker moments too.
          </p>
        </div>
      )}

      {preview && <PreviewModal c={preview} onClose={() => setPreview(null)} />}
      {regen && <RegenModal p={p} onClose={() => setRegen(false)} onDone={() => { setRegen(false); refresh(); }} />}
    </div>
  );
}

function ClipCard({ c, onPreview, onToggle }: { c: Clip; onPreview: () => void; onToggle: () => void }) {
  const ready = c.status === "ready";
  return (
    <div className={`clip-card ${c.selected && ready ? "sel" : ""}`}>
      <div className="clip-thumb" style={c.has_thumbnail ? { backgroundImage: `url(${clipThumbUrl(c)})` } : undefined}
        onClick={() => ready && onPreview()}>
        {ready && <div className="play"><div><Icon name="play" fill size={24} /></div></div>}
        <div className="tl"><ScoreBadge score={c.score} /></div>
        {ready && (
          <div className="tr" onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            <div className={`check ${c.selected ? "on" : ""}`}>{c.selected ? <Icon name="check" size={14} /> : null}</div>
          </div>
        )}
        <div className="bl">{fmtTime(c.duration)}</div>
        {!ready && (
          <div className="overlay">
            {c.status === "error" ? (
              <>
                <span className="badge bad">Render failed</span>
                <div className="small muted" style={{ maxHeight: 120, overflow: "auto" }}>{c.error}</div>
              </>
            ) : (
              <>
                <div className="spinner" />
                <div className="small">{c.status === "queued" ? "Queued" : `Rendering ${Math.round(c.progress * 100)}%`}</div>
              </>
            )}
          </div>
        )}
      </div>
      <div className="clip-body">
        <div className="row between">
          <span className="badge">{c.category || "Highlight"}</span>
          <span className="small muted">@ {fmtTime(c.edit?.start ?? c.start)}</span>
        </div>
        <div className="clip-title">{c.title}</div>
        <SubscoreLine c={c} />
        <StructureChips c={c} />
        {(c.analysis?.flags || []).some((f) => f.severity === "warn") && (
          <div className="small warn-text" title={(c.analysis?.flags || []).map((f) => `${f.label}: ${f.detail}`).join("\n")}>
            ⚠ {(c.analysis?.flags || []).map((f) => f.label).join(", ")}
          </div>
        )}
        {(() => {
          const hook = c.edit?.hook ?? c.hook;
          const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
          return hook && norm(hook) !== norm(c.title) ? <div className="clip-hook">“{hook}”</div> : null;
        })()}
        <div className="tags">{c.hashtags.slice(0, 5).map((t) => <span className="tag" key={t}>{t}</span>)}</div>
      </div>
      <div className="clip-actions">
        <button className="btn sm" disabled={!ready} onClick={onPreview}><Icon name="play" size={13} /> Preview</button>
        <button className="btn sm" onClick={() => navigate(`/clip/${c.id}`)}><Icon name="edit" size={13} /> Edit</button>
        <a className={`btn sm ${ready ? "" : "disabled"}`} href={ready ? clipDownloadUrl(c) : undefined}
          style={ready ? undefined : { opacity: 0.45, pointerEvents: "none" }}>
          <Icon name="download" size={13} /> MP4
        </a>
        <button className="btn sm primary span3" disabled={!ready} onClick={() => navigate(`/publish/${c.id}`)}>
          <Icon name="upload" size={13} /> Publish
        </button>
      </div>
    </div>
  );
}

function PreviewModal({ c, onClose }: { c: Clip; onClose: () => void }) {
  const start = c.edit?.start ?? c.start;
  const end = c.edit?.end ?? c.end;
  return (
    <Modal onClose={onClose}>
      <div className="preview-modal">
        <video src={clipVideoUrl(c)} controls autoPlay playsInline />
        <div className="preview-side">
          <div className="row between">
            <ScoreBadge score={c.score} />
            <button className="btn ghost icon-btn" onClick={onClose}><Icon name="x" /></button>
          </div>
          <h3 style={{ margin: 0 }}>{c.title}</h3>
          <div className="kv">
            <span className="k">Hook</span><span>{c.edit?.hook ?? c.hook}</span>
            <span className="k">Category</span><span>{c.category}</span>
            <span className="k">Source</span><span>{fmtPrecise(start)} - {fmtPrecise(end)}</span>
            <span className="k">Duration</span><span>{c.duration.toFixed(1)}s</span>
            <span className="k">Scored by</span><span>{c.score_source}</span>
            {c.render_info?.mode && <><span className="k">Framing</span><span>{c.render_info.mode}</span></>}
          </div>
          <ViralPanel c={c} />
          {c.reason && <div className="small muted">{c.reason}</div>}
          <div className="tags">{c.hashtags.map((t) => <span className="tag" key={t}>{t}</span>)}</div>
          <div className="row" style={{ marginTop: "auto" }}>
            <button className="btn primary" onClick={() => navigate(`/publish/${c.id}`)}><Icon name="upload" size={16} /> Publish</button>
            <a className="btn" href={clipDownloadUrl(c)}><Icon name="download" size={16} /> Download</a>
            <button className="btn" onClick={() => navigate(`/clip/${c.id}`)}><Icon name="edit" size={16} /> Edit</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function RegenModal({ p, onClose, onDone }: { p: Project; onClose: () => void; onDone: () => void }) {
  const opts = (p.options || {}) as Record<string, any>;
  const [count, setCount] = useState<number>([3, 5, 10].includes(opts.clip_count) ? opts.clip_count : 5);
  const [minD, setMinD] = useState<number>(opts.min_duration ?? 15);
  const [maxD, setMaxD] = useState<number>(opts.max_duration ?? 60);
  const [busy, setBusy] = useState(false);
  const note = useMemo(() => "The transcript is reused, so this is much faster than the first run. Manual edits on current clips are discarded.", []);
  const go = async () => {
    setBusy(true);
    try {
      await api.reprocess(p.id, { clip_count: count, min_duration: minD, max_duration: Math.max(maxD, minD + 5), target_duration: (minD + maxD) / 2 });
      onDone();
    } catch (e) {
      toast((e as Error).message, true);
      setBusy(false);
    }
  };
  return (
    <Modal onClose={onClose}>
      <div style={{ padding: 24, width: 440 }}>
        <h3 style={{ marginTop: 0 }}>Regenerate clips</h3>
        <p className="muted small">{note}</p>
        <div className="opt-row"><div className="lbl">Clips</div>
          <Segmented value={count} onChange={setCount} options={[3, 5, 10].map((n) => ({ value: n, label: n }))} /></div>
        <div className="opt-row"><div className="lbl">Min length (s)</div>
          <input type="number" min={5} max={170} value={minD} onChange={(e) => setMinD(+e.target.value)} /></div>
        <div className="opt-row"><div className="lbl">Max length (s)</div>
          <input type="number" min={10} max={180} value={maxD} onChange={(e) => setMaxD(+e.target.value)} /></div>
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={go}><Icon name="refresh" size={16} /> Regenerate</button>
        </div>
      </div>
    </Modal>
  );
}
