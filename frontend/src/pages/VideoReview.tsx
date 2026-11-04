import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { LayoutFlow } from "../components/AppearanceSettings";
import { UsedFromBrain } from "../components/studioParts";
import { Banner, Icon, LoadingPage, PageHead, ProgressBar, toast } from "../components/ui";
import { fmtTime, studio, Video } from "../studio";

/** Review a full video: preview, outline, sequence, simple edits, versions, render and download. */
export default function VideoReview({ id }: { id: string }) {
  const [v, setV] = useState<Video | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [request, setRequest] = useState("");

  const load = useCallback(() => studio.video(id).then(setV).catch((e) => setProblem(errorText(e))), [id]);
  useEffect(() => {
    void load();
    const t = window.setInterval(load, 2500);
    return () => window.clearInterval(t);
  }, [load]);
  if (!v) return problem ? <Banner tone="bad" title="This video cannot be opened">{problem}</Banner> : <LoadingPage label="Loading video" />;

  const plan = v.plan;
  const working = v.jobs.find((j) => j.status === "running" || j.status === "queued");
  const preview = v.artifacts.find((a) => a.kind === "preview" && a.revision === v.plan_revision)
    || v.artifacts.find((a) => a.kind === "preview");
  const finals = v.artifacts.filter((a) => a.kind === "final");
  const failed = v.jobs.find((j) => j.status === "failed" && j.revision >= v.plan_revision);
  const edit = async (change: Record<string, unknown>) => {
    setBusy(true);
    try {
      const r = await studio.editVideo(v.id, v.plan_revision, change);
      setV(r);
      toast(r.note || "Saved as a new version");
    } catch (e) {
      toast(errorText(e), true);  // the earlier version stays as it was
    }
    setBusy(false);
  };
  const vertical = plan?.output.aspect === "9:16" || plan?.output.aspect === "4:5";

  return (
    <div className="page">
      <PageHead kind="Full video" title={v.name} crumbs={[{ label: "Projects", href: "#/projects" }, { label: v.name }]}
        sub={plan ? `Version ${v.plan_revision} · ${fmtTime(v.duration)} · ${plan.output.aspect}` : v.message}
        actions={plan && <>
          <button type="button" className="btn btn-primary" disabled={busy || !!working && working.kind === "video_render"}
            onClick={async () => { try { setV(await studio.renderVideo(v.id, v.plan_revision)); toast("Rendering on the server"); } catch (e) { toast(errorText(e), true); } }}>
            <Icon name="play" />Render version {v.plan_revision}</button>
          {working && <button type="button" className="btn" onClick={async () => setV(await studio.cancelVideo(v.id))}><Icon name="stop" />Cancel</button>}
        </>} />
      {failed && <Banner tone="bad" title="That did not finish">{failed.error}</Banner>}
      {working && <div className="panel"><b>{working.message || "Waiting for a worker"}</b><ProgressBar value={working.progress} label="Progress" /></div>}
      <LayoutFlow screen="review" sections={{
        preview: (
          <section className="panel" aria-labelledby="vr-preview">
            <div className="panel-head"><h2 id="vr-preview">Preview</h2>
              {preview && preview.revision !== v.plan_revision && <span className="small muted">Showing version {preview.revision} while version {v.plan_revision} is prepared</span>}</div>
            {preview ? <video key={preview.id} className={`preview-video ${vertical ? "vertical" : ""}`} controls preload="metadata"
              src={`/api/studio/videos/${v.id}/media?kind=preview&revision=${preview.revision}`} />
              : <p className="muted">The preview appears here when the rough cut is ready.</p>}
            <p className="small muted">The preview is a small, fast copy of the same plan. The final render uses your full original files.</p>
          </section>),
        outputs: plan && (
            <section className="panel" aria-labelledby="vr-seq">
              <div className="panel-head"><h2 id="vr-seq">Sequence</h2>
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "shorten_intro", seconds: 5 })}>Shorten the introduction</button></div>
              <ol className="seq">
                {plan.clips.map((c, i) => {
                  const o = plan.outline.find((x) => x.clip_id === c.id);
                  return (
                    <li key={c.id} className={c.include ? "" : "off"}>
                      <span className="idx">{i + 1}</span>
                      <div className="break">
                        <b className="clamp-1">{c.label}</b>
                        <span className="block small muted">{fmtTime(c.in_ms / 1000)}–{fmtTime(c.out_ms / 1000)} · {((c.out_ms - c.in_ms) / 1000).toFixed(1)} s{o?.summary ? ` · “${o.summary}”` : ""}</span>
                        {c.must_keep?.length ? <span className="block small">Keeps: {c.must_keep.join(", ")}</span> : null}
                      </div>
                      <div className="row-actions">
                        <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${c.label} earlier`} disabled={busy || i === 0} onClick={() => edit({ op: "move", clip_id: c.id, to: i - 1 })}><Icon name="chev" className="rot-up" /></button>
                        <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${c.label} later`} disabled={busy || i === plan.clips.length - 1} onClick={() => edit({ op: "move", clip_id: c.id, to: i + 1 })}><Icon name="chev" /></button>
                        {c.include ? <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "remove", clip_id: c.id })}>Remove this clip</button>
                          : <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "include", clip_id: c.id })}>Put back</button>}
                      </div>
                    </li>
                  );
                })}
              </ol>
              <form className="robot-name-form" onSubmit={(e) => { e.preventDefault(); if (request.trim()) void edit({ op: "request", text: request }); }}>
                <label className="field grow"><span>Ask for a change</span><input value={request} onChange={(e) => setRequest(e.target.value)} placeholder="For example: shorten the intro by 3 seconds" /></label>
                <button type="submit" className="btn" disabled={busy || !request.trim()}>Apply</button>
              </form>
              {plan.notes.length > 0 && <ul className="small">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            </section>),
        guidance: <section className="panel" aria-labelledby="vr-brain"><h2 id="vr-brain">Used from your Brain</h2><UsedFromBrain snapshot={v.guidance} compact /></section>,
        transcript: (<div className="stack-5">{plan && (
            <section className="panel" aria-labelledby="vr-look"><h2 id="vr-look">Look and sound</h2>
              <label><input type="checkbox" checked={plan.captions.enabled} disabled={busy} onChange={(e) => edit({ op: "set", field: "captions", value: e.target.checked })} /> Captions</label>
              <label className="field"><span>Joins between clips</span>
                <select value={plan.transition.type} disabled={busy} onChange={(e) => edit({ op: "set", field: "transition", value: e.target.value })}>
                  <option value="cut">Straight cuts</option><option value="dissolve">Dissolves</option><option value="fade">Fade through black</option>
                </select></label>
              {plan.music && <label className="field"><span>Music level ({plan.music.level_db} dB)</span>
                <input type="range" min={-36} max={-6} step={1} defaultValue={plan.music.level_db} disabled={busy}
                  onMouseUp={(e) => edit({ op: "set", field: "music_level_db", value: Number((e.target as HTMLInputElement).value) })}
                  onKeyUp={(e) => edit({ op: "set", field: "music_level_db", value: Number((e.target as HTMLInputElement).value) })} /></label>}
            </section>
          )}
          <section className="panel" aria-labelledby="vr-versions"><h2 id="vr-versions">Versions</h2>
            {finals.length > 0 && <ul className="file-list">{finals.map((a) => (
              <li key={a.id} className="file-row"><Icon name="check" /><div><b>Version {a.revision}</b><span className="block small muted">{fmtTime(a.duration)} · checked{a.audio_ok ? ", audio timing valid" : ""}</span></div>
                <a className="btn btn-small" href={`/api/studio/videos/${v.id}/media?kind=final&revision=${a.revision}&download=1`}><Icon name="download" />Download</a></li>
            ))}</ul>}
            <ul className="small">{v.revisions.slice(0, 8).map((r) => (
              <li key={r.revision}>{r.revision}. {r.note}{r.revision !== v.plan_revision && <> <button type="button" className="link-btn" onClick={async () => setV(await studio.restoreVideo(v.id, r.revision))}>Go back to this</button></>}</li>
            ))}</ul>
            <a className="small" href={`/api/studio/videos/${v.id}/export`}>Download the edit plan (JSON)</a>
          </section></div>),
      }} />
    </div>
  );
}
