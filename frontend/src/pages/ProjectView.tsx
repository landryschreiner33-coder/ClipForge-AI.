import { useEffect, useId, useRef, useState } from "react";
import {
  api, Clip, clipDownloadUrl, clipThumbUrl, clipVideoUrl, downloadZip, errorText, fmtPrecise, fmtTime, Project,
  projectThumbUrl,
} from "../api";
import type { ScheduledItem } from "../autopilot";
import { plural } from "../format";
import {
  addedLine, byAutopilot, cancelProcessing, DeleteProjectDialog, ExportDialog, isWorking, LibProject, PLATFORM,
  postWord, projectMenu, ProjectStatus, RemakeDialog, useClipPosts,
} from "../components/libParts";
import {
  Banner, Disclosure, EmptyState, Icon, LoadingPage, Modal, MoreMenu, PageHead, ProgressBar, ScoreBadge, Thumb, toast,
  usePoll,
} from "../components/ui";
import { ESTIMATE_NOTE, QualitySummary, ViralPanel } from "../components/viral";
import { navigate } from "../router";
import "./library.css";

// The five real steps of making clips, and the backend stage names that belong to each.
const STAGES = ["Prepare", "Transcribe", "Find moments", "Score & hooks", "Render 9:16"];
const STAGE_STEP: Record<string, number> = {
  queued: -1, download: 0, probe: 0, audio: 0, transcribe: 1, candidates: 2, scoring: 3, render: 4, done: 5,
};

const clipBusy = (c: Clip) => c.status === "rendering" || c.status === "queued";
const pollWhile = (p: Project | null) => !!p && (isWorking(p) || (p.clips || []).some(clipBusy));

/** "Transcribed on the GPU (large-v3, float16, 17× real time)": only what the backend recorded. */
function transcriptLine(info: Record<string, any>): string {
  const t = info.transcription;
  if (t && t.device) {
    const where = t.device === "cuda" ? "the GPU" : "the CPU";
    const speed = typeof t.speed === "number" && Number.isFinite(t.speed) ? `${t.speed}× real time` : "";
    const bits = [t.model, t.compute_type, speed].filter(Boolean).join(", ");
    return `Transcribed on ${where}${bits ? ` (${bits})` : ""}`;
  }
  const s = String(info.transcript_source || "");
  if (s.startsWith("import:")) return `Imported from your ${s.slice(7).toUpperCase()} file`;
  if (s === "none") return "None: the video has no sound";
  if (s.startsWith("faster-whisper:")) return `Transcribed with Whisper (${s.split(":")[1]})`;
  return "";
}

function languageName(code: string): string {
  if (!code) return "";
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) || code;
  } catch {
    return code;
  }
}

export default function ProjectView({ id }: { id: string }) {
  const { data: p, error, refresh, setData } =
    usePoll(() => api.project(id) as Promise<LibProject>, [id], 1500, pollWhile);
  const posts = useClipPosts([id]);
  const [preview, setPreview] = useState<Clip | null>(null);
  const [exporting, setExporting] = useState<Clip | null>(null);
  const [dialog, setDialog] = useState<"remake" | "delete" | null>(null);
  const [zipping, setZipping] = useState(false);

  // Say when the work this page shows has finished (once, not on every poll).
  const was = useRef("");
  useEffect(() => {
    if (!p) return;
    const before = was.current;
    was.current = p.status;
    if (!before || before === p.status || !["created", "uploading", "queued", "processing"].includes(before)) return;
    const n = p.clips?.length || 0;
    if (p.status === "ready") {
      toast(n ? `${plural(n, "clip")} ${n === 1 ? "is" : "are"} ready from “${p.name}”`
        : `No moment of “${p.name}” passed the quality bar`);
    }
    if (p.status === "error") toast(`ClipFoundry couldn't make clips from “${p.name}”`, true);
  }, [p]);

  if (!p) {
    if (!error) return <LoadingPage label="Loading the video" />;
    return (
      <div className="page">
        <PageHead crumbs={[{ label: "Clips", href: "#/clips" }, { label: "Video" }]} kind="Source video"
          title="This video isn't in your library" />
        <EmptyState icon="film" title="Nothing to show" actions={<>
          <a className="btn" href="#/clips"><Icon name="library" />Open the Library</a>
          <button type="button" className="btn" onClick={refresh}><Icon name="refresh" />Try again</button>
        </>}>
          <p>ClipFoundry answered: {error}. It may have been deleted.</p>
        </EmptyState>
      </div>
    );
  }

  const clips = p.clips || [];
  const ready = clips.filter((c) => c.status === "ready" && c.has_video);
  const selected = ready.filter((c) => c.selected);
  const busy = isWorking(p);
  const info = (p.info || {}) as Record<string, any>;
  const transcript = transcriptLine(info);
  const language = languageName(info.language || "");
  const facts = p.duration
    ? `${fmtTime(p.duration)} · ${p.width}×${p.height} · ${Math.round(p.fps)} fps · ${addedLine(p)}`
    : `${p.source_filename || p.source_url || ""}${p.source_filename || p.source_url ? " · " : ""}${addedLine(p)}`;

  const setSelected = async (list: Clip[], on: boolean) => {
    const ids = new Set(list.map((c) => c.id));
    setData({ ...p, clips: clips.map((c) => (ids.has(c.id) ? { ...c, selected: on ? 1 : 0 } : c)) });
    try {
      await Promise.all(list.map((c) => api.patchClip(c.id, { selected: on })));
    } catch (e) {
      toast(errorText(e), true);
    }
    refresh();
  };
  const zip = async (ids: string[] | null) => {
    setZipping(true);
    try {
      await downloadZip(id, ids);
      toast("Download started");
    } catch (e) {
      toast(errorText(e), true);
    }
    setZipping(false);
  };
  const menu = projectMenu(p, {
    cancel: () => cancelProcessing(p, refresh),
    remake: () => setDialog("remake"),
    remove: () => setDialog("delete"),
  });

  return (
    <div className="page source-video-page">
      <PageHead crumbs={[{ label: "Clips", href: "#/clips" }, { label: p.name }]} kind="Source video" title={p.name}
        sub={facts}
        actions={<>
          <ProjectStatus p={p} clipCount={clips.length} />
          {busy && !byAutopilot(p) && (
            <button type="button" className="btn" onClick={() => cancelProcessing(p, refresh)}>
              <Icon name="stop" />Cancel processing
            </button>
          )}
          <MoreMenu label="More for this video" items={menu} />
        </>} />

      {p.status === "error" && (
        <Banner tone="bad" title="ClipFoundry couldn't make clips from this video." actions={<>
          <button type="button" className="btn btn-small" onClick={() => setDialog("remake")}>
            <Icon name="refresh" />Try again…
          </button>
          <a className="btn btn-small" href="#/create">Add a different video</a>
        </>}>
          <span className="break">{p.error || "No reason was recorded."}</span>
          <br /><b>What to do:</b> press Try again. A transcript that was already made is reused.
        </Banner>
      )}
      {p.status === "cancelled" && (
        <Banner tone="neutral" icon="stop" title="Making clips was canceled" actions={
          <button type="button" className="btn btn-small" onClick={() => setDialog("remake")}>
            <Icon name="refresh" />Make clips again…
          </button>}>
          Nothing more happens with this video until you start it again.
        </Banner>
      )}
      {info.transcription?.warning && (
        <Banner tone="warn" title={`Transcribed on ${info.transcription.device === "cuda" ? "the GPU" : "the CPU"}`}>
          {info.transcription.warning}
          {info.transcription.fix ? <><br /><b>What to do:</b> {info.transcription.fix}</> : null}
        </Banner>
      )}
      {info.stage2?.warning && <Banner tone="warn" title="About the ranking">{info.stage2.warning}</Banner>}

      <section className="panel" aria-labelledby="src-h">
        <div className="src-top">
          <div className="src-pic">
            <Thumb src={p.has_thumbnail ? projectThumbUrl(p) : null} duration={p.duration} />
          </div>
          <div className="src-facts">
            <span className="kind-label">Original video</span>
            <h2 id="src-h">About this video</h2>
            {busy && <Working p={p} />}
            {(transcript || language) && (
              <dl className="kv">
                {transcript && <><dt>Transcript</dt><dd>{transcript}</dd></>}
                {language && <><dt>Language</dt><dd>{language}</dd></>}
              </dl>
            )}
            {p.status === "ready" && (info.quality ? <QualitySummary q={info.quality} clipCount={clips.length} /> : (
              <p className="small">
                {plural(clips.length, "clip")}
                {info.candidates_found ? ` from ${plural(info.candidates_found, "moment")} found` : ""}.
                Weak moments are never added to reach the count.
              </p>
            ))}
            {p.status === "ready" && (
              <Disclosure plain summary="How clips are ranked">
                <p className="small muted">
                  Clips are ranked by Viral Potential ({info.stage2?.provider || "local analysis"}): hook strength,
                  curiosity, emotion, information density, payoff, standalone context, opening, pacing, uniqueness,
                  speaker clarity and retention, with a bonus for a clear hook, context and payoff. {ESTIMATE_NOTE}
                </p>
              </Disclosure>
            )}
          </div>
        </div>
      </section>

      {clips.length > 0 && (
        <section className="stack-4" aria-labelledby="clips-h">
          <div className="panel-head">
            <div className="section-title">
              <h2 id="clips-h">Clips made from it ({clips.length})</h2>
              <span className="small muted">Each clip is its own 9:16 video. Posts are made from clips.</span>
            </div>
            <div className="row wrap">
              <span className="small muted">{selected.length} selected</span>
              <button type="button" className="btn btn-small btn-quiet" disabled={!ready.length}
                onClick={() => setSelected(ready, selected.length !== ready.length)}>
                {selected.length === ready.length && ready.length ? "Clear selection" : "Select all"}
              </button>
              <button type="button" className="btn btn-small" disabled={!selected.length || zipping}
                onClick={() => zip(selected.map((c) => c.id))}>
                <Icon name="zip" />Download selected (ZIP)
              </button>
              <button type="button" className="btn btn-small" disabled={!ready.length || zipping}
                onClick={() => zip(null)}>
                <Icon name="download" />{zipping ? "Preparing the ZIP…" : "Download all (ZIP)"}
              </button>
            </div>
          </div>
          <div className="clip-grid">
            {clips.map((c) => (
              <ClipCard key={c.id} c={c} posts={posts ? posts.get(c.id) || [] : null}
                onPreview={() => setPreview(c)} onToggle={() => setSelected([c], !c.selected)}
                onExport={() => setExporting(c)} />
            ))}
          </div>
        </section>
      )}

      {p.status === "ready" && clips.length === 0 && (
        <EmptyState icon="scissors" title="No moment passed the quality bar" actions={
          <button type="button" className="btn" onClick={() => setDialog("remake")}>
            <Icon name="refresh" />Make clips again…
          </button>}>
          <p>
            ClipFoundry doesn't pad the results with weak clips. Try a different clip length with “Make clips again”, or
            lower the minimum Viral Potential in <a className="textlink" href="#/settings/advanced">Settings</a> to
            see weaker moments too.
          </p>
        </EmptyState>
      )}

      {preview && <PreviewDialog c={preview} onClose={() => setPreview(null)} />}
      {exporting && <ExportDialog clip={exporting} onClose={() => setExporting(null)} />}
      {dialog === "remake" && (
        <RemakeDialog p={p} clipCount={clips.length} onClose={() => setDialog(null)} onDone={refresh} />
      )}
      {dialog === "delete" && (
        <DeleteProjectDialog p={p} clipCount={clips.length} onClose={() => setDialog(null)}
          onDeleted={() => navigate("clips")} />
      )}
    </div>
  );
}

/** The real steps and the progress the backend reports; never a time estimate. */
function Working({ p }: { p: Project }) {
  const step = p.status === "processing" ? STAGE_STEP[p.stage || "queued"] ?? -1 : -1;
  const pct = Math.round((p.progress || 0) * 100);
  const label = p.status === "uploading" ? "Copying into ClipFoundry"
    : p.status === "processing" ? p.message || "Making clips" : p.message || "Waiting to start";
  return (
    <div className="stack">
      <b>{label}</b>
      <ol className="stages" aria-label="Steps">
        {STAGES.map((s, i) => (
          <li key={s} className={i < step ? "done" : i === step ? "now" : ""}
            aria-current={i === step ? "step" : undefined}>
            <Icon name={i < step ? "check" : i === step ? "refresh" : "dot"} />{s}
            {i < step && <span className="sr-only"> (done)</span>}
          </li>
        ))}
      </ol>
      {p.status === "processing" && pct > 0 ? (
        <>
          <ProgressBar value={p.progress} label="Progress of this video" />
          <span className="tiny faint">
            {pct}% of all steps, as ClipFoundry reports it. No time estimate is available.
          </span>
        </>
      ) : (
        <span className="tiny faint">
          {p.status === "processing" ? "Starting." : "It starts when the work before it is done."}
        </span>
      )}
      <span className="tiny faint">You can leave this page; the clips appear here when they're ready.</span>
    </div>
  );
}

function ClipCard({ c, posts, onPreview, onToggle, onExport }: {
  c: Clip; posts: ScheduledItem[] | null; onPreview: () => void; onToggle: () => void; onExport: () => void;
}) {
  const ready = c.status === "ready" && c.has_video;
  const warnings = (c.analysis?.flags || []).filter((f) => f.severity === "warn");
  return (
    <article className="ccard" aria-labelledby={`cc-${c.id}`}>
      <div style={{ position: "relative" }}>
        <button type="button" className="thumb-button" disabled={!ready} onClick={onPreview}
          aria-label={`Preview “${c.title}”`}>
          <Thumb vertical src={c.has_thumbnail ? clipThumbUrl(c) : null} duration={c.duration}>
            {clipBusy(c) && (
              <span className="overlay"><Icon name="refresh" />
                <span>
                  {c.status === "queued" ? "Waiting to render" : `Rendering ${Math.round((c.progress || 0) * 100)}%`}
                </span>
              </span>
            )}
            {c.status === "error" && <span className="overlay"><Icon name="alert" /><span>Render failed</span></span>}
            {ready && <span className="play-hint" aria-hidden="true"><Icon name="play" fill /></span>}
          </Thumb>
        </button>
        {ready && (
          <label className="sel">
            <input type="checkbox" checked={!!c.selected} onChange={onToggle} aria-label={`Select “${c.title}”`} />
            Select
          </label>
        )}
      </div>
      <div className="ccard-body">
        <span className="kind-label">Generated clip · 9:16</span>
        <h3 className="clamp-2" id={`cc-${c.id}`} style={{ fontSize: "var(--fs-body)" }}>{c.title}</h3>
        <span className="score" title={ESTIMATE_NOTE}><b>{Math.round(c.score)}</b>Viral Potential (estimate)</span>
        <span className="tiny faint">
          {c.category || "Highlight"} · from {fmtTime(c.edit?.start ?? c.start)} in the source
        </span>
        {warnings.length > 0 && (
          <span className="tiny warn-text" title={warnings.map((f) => `${f.label}: ${f.detail}`).join("\n")}>
            <Icon name="alert" className="xs" /> Watch out: {warnings.map((f) => f.label).join(", ")}
          </span>
        )}
        {c.status === "error" && (
          <span className="tiny bad-line clamp-2" title={c.error}>{c.error || "The render didn't work."}</span>
        )}
        {posts && (posts.length ? (
          <span className="tiny posts-line">
            {posts.slice(0, 2).map((x) => (
              <a key={x.id} className="textlink" href={`#/post/${x.id}`}>
                {PLATFORM[x.platform] || x.platform}: {postWord(x)}
              </a>
            ))}
            {posts.length > 2 && <a className="textlink" href="#/queue/review">{posts.length - 2} more</a>}
          </span>
        ) : <span className="tiny faint">No posts yet</span>)}
        <div className="ccard-actions">
          <a className="btn btn-small" href={`#/clip/${c.id}`}><Icon name="edit" />Edit clip</a>
          <button type="button" className="btn btn-small" disabled={!ready} onClick={onExport}>
            <Icon name="download" />Export
          </button>
          {ready ? (
            <a className="btn btn-small btn-primary" href={`#/publish/${c.id}`}><Icon name="upload" />Prepare post</a>
          ) : (
            <button type="button" className="btn btn-small btn-primary" disabled>
              <Icon name="upload" />Prepare post
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

/** The rendered clip with everything ClipFoundry knows about it (scores are estimates). */
function PreviewDialog({ c, onClose }: { c: Clip; onClose: () => void }) {
  const hid = useId();
  const start = c.edit?.start ?? c.start;
  const end = c.edit?.end ?? c.end;
  return (
    <Modal onClose={onClose} labelledBy={hid} className="preview-dialog">
      <div className="preview">
        <video src={clipVideoUrl(c)} controls autoPlay playsInline />
        <div className="preview-side">
          <div className="row top">
            <h2 id={hid} className="grow break">{c.title}</h2>
            <button type="button" className="btn btn-small btn-icon" aria-label="Close preview" onClick={onClose}>
              <Icon name="x" />
            </button>
          </div>
          <ScoreBadge score={c.score} />
          <dl className="kv">
            <dt>Hook</dt><dd>{c.edit?.hook ?? c.hook}</dd>
            <dt>Category</dt><dd>{c.category || "Highlight"}</dd>
            <dt>From the source</dt><dd className="tnum">{fmtPrecise(start)} – {fmtPrecise(end)}</dd>
            <dt>Length</dt><dd className="tnum">{c.duration.toFixed(1)} s</dd>
            <dt>Scored by</dt><dd>{c.score_source}</dd>
            {c.render_info?.mode && <><dt>Framing</dt><dd>{c.render_info.mode}</dd></>}
          </dl>
          {c.active_version && (
            <p className="tiny faint">
              This is the original render. Exports and posts use the version chosen in the editor.
            </p>
          )}
          <ViralPanel c={c} />
          {c.reason && <p className="small muted">{c.reason}</p>}
          {c.hashtags.length > 0 && (
            <div className="row wrap" style={{ gap: 6 }}>
              {c.hashtags.map((t) => <span className="tag" key={t}>{t}</span>)}
            </div>
          )}
          <div className="row wrap">
            <a className="btn btn-primary" href={`#/publish/${c.id}`}><Icon name="upload" />Prepare post</a>
            <a className="btn" href={`#/clip/${c.id}`}><Icon name="edit" />Edit clip</a>
            <a className="btn" href={clipDownloadUrl(c)} download><Icon name="download" />Download this video</a>
          </div>
        </div>
      </div>
    </Modal>
  );
}
