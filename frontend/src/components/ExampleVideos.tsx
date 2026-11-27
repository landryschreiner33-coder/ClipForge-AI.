import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { ApplyChoice, ExampleVideo, Field, fmtEdit, studio } from "../studio";
import { FileDrop, Picked, UploadRow, useUploadsByFile } from "./studioParts";
import { Banner, ConfirmDialog, Dialog, EmptyState, Icon, Pill, ProgressBar, toast } from "./ui";

const LIKES: [string, string][] = [["overall", "Overall style"], ["pacing", "Pacing and cuts"], ["captions", "Captions"],
  ["framing", "Framing"], ["sound", "Sound and music"]];
const MODES: [string, string][] = [["highlights", "Highlights"], ["full_stories", "Full stories"], ["full_video", "Full videos"]];
const STATUS: Record<string, [string, "neutral" | "accent" | "good" | "warn" | "bad"]> = {
  queued: ["Waiting", "neutral"], analyzing: ["Analyzing", "accent"], ready: ["Analyzed", "good"],
  failed: ["Not analyzed", "bad"], canceled: ["Canceled", "warn"] };

const clock = (ms: number) => fmtEdit(ms);
const parseClock = (v: string): number | null => {
  const t = v.trim();
  if (!t) return null;
  const parts = t.split(":").map((x) => Number(x));
  if (parts.some((x) => !Number.isFinite(x) || x < 0)) return NaN;
  return Math.round(parts.reduce((acc, x) => acc * 60 + x, 0) * 1000);
};
const scopeText = (r: ExampleVideo) => r.avoid ? "Example to avoid: never applied"
  : r.project_only ? "Added for one project"
    : r.scope === "all" ? "Used for every new project"
      : r.scope === "modes" ? `Used for ${r.modes.map((m) => MODES.find(([k]) => k === m)?.[1] || m).join(", ")}`
        : "Used when you choose it for a project";

/** Brain → Example videos: upload a video you like; ClipForge measures it and you choose what new projects reuse. */
export function ExampleVideosTab() {
  const [rows, setRows] = useState<ExampleVideo[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [all, setAll] = useState(false);
  const load = useCallback(() => studio.examples(all).then((r) => { setRows(r); return r; }).catch(() => { setRows([]); return []; }), [all]);
  useEffect(() => {
    void load();
  }, [load]);
  const busy = (rows || []).some((r) => r.status === "queued" || r.status === "analyzing");
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(t);
  }, [busy, load]);
  if (rows === null) return <p className="muted">Loading example videos…</p>;
  const current = rows.find((r) => r.id === open) || null;
  return (
    <div className="stack-3">
      <p className="muted">Upload a video whose editing you like. ClipForge measures its cuts, captions, framing and sound on this computer,
        shows what it noticed with the moments to check, and you choose what new projects should reuse. The example's own footage and sound never go into your videos.</p>
      <div className="row-actions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}><Icon name="plus" />Add example video</button>
        <label className="small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Also show examples added for one project</label>
      </div>
      {rows.length === 0 && <EmptyState icon="film" title="No example videos yet" level={3}>
        Add a short video you like. Measuring takes about a second per minute of video on a typical computer.</EmptyState>}
      <ul className="ex-list" aria-label="Example videos">
        {rows.map((r) => {
          const [label, tone] = STATUS[r.status] || [r.status, "neutral"];
          return (
            <li key={r.id}>
              <button type="button" className={`ex-row ${open === r.id ? "on" : ""}`} aria-expanded={open === r.id}
                onClick={() => setOpen(open === r.id ? null : r.id)}>
                <Icon name="film" />
                <span className="ex-row-main">
                  <b>{r.title}</b>
                  <span className="small muted">{scopeText(r)}{r.style ? ` · saved as “${r.style.name}” (revision ${r.style.revision})` : ""}{!r.enabled ? " · disabled" : ""}</span>
                </span>
                <Pill tone={tone}>{r.status === "analyzing" && r.progress != null ? `${label} ${Math.round(r.progress * 100)}%` : label}</Pill>
              </button>
              {open === r.id && current && <ExampleDetail row={current} onChange={load} onDeleted={() => { setOpen(null); void load(); }} />}
            </li>
          );
        })}
      </ul>
      {adding && <AddExample onClose={() => setAdding(false)} onAdded={(r) => { setAdding(false); setOpen(r.id); void load(); }} />}
    </div>
  );
}

function AddExample({ onClose, onAdded, projectOnly = false }: { onClose: () => void; onAdded: (r: ExampleVideo) => void; projectOnly?: boolean }) {
  const [file, setFile] = useState<Picked | null>(null);
  const [title, setTitle] = useState("");
  const [likes, setLikes] = useState<string[]>(["overall"]);
  const [note, setNote] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [avoid, setAvoid] = useState(false);
  const [scope, setScope] = useState<"chosen" | "all" | "modes">("chosen");
  const [modes, setModes] = useState<string[]>([]);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const uploaded = useUploadsByFile();  // the page's uploads of the file become the example's own
  const a = parseClock(from);
  const b = parseClock(to);
  const rangeBad = (a !== null || b !== null) && (a === null || b === null || Number.isNaN(a) || Number.isNaN(b) || b - a < 1000);
  const ok = !!file?.asset && !rangeBad && (scope !== "modes" || modes.length > 0) && !busy;
  const submit = async () => {
    setBusy(true);
    setProblem("");
    try {
      const r = await studio.addExample({ asset_id: file!.asset!.id, upload_ids: uploaded.of([file!.asset!.id]),
        title: title.trim(), likes, note, avoid,
        scope: avoid ? "chosen" : scope, modes: scope === "modes" ? modes : [], project_only: projectOnly,
        ranges: a !== null && b !== null ? [{ start_ms: a, end_ms: b }] : [] });
      toast(`Measuring “${r.title}”. You can keep working; it shows here when it is ready.`);
      onAdded(r);
    } catch (e) {
      setProblem(errorText(e));
      setBusy(false);
    }
  };
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <Dialog title="Add an example video" wide onClose={onClose} actions={<>
      <button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary" disabled={!ok} onClick={submit}>{busy && <span className="inline-spinner" aria-hidden="true" />}Add and analyze</button>
    </>}>
      <div className="stack-3">
        {!file?.asset ? <FileDrop accept="video/*,.mkv,.m4v" label="Drop the example video here" onAssets={(rows) => setFile(rows[0] || null)}
          onUploaded={uploaded.add} />
          : <UploadRow row={file} />}
        <label className="field"><span>Name</span><input value={title} maxLength={120} placeholder={file?.file.name.replace(/\.[^.]+$/, "") || "My favourite vlog"} onChange={(e) => setTitle(e.target.value)} /></label>
        <fieldset className="stack-2"><legend className="label">What do you like about this example?</legend>
          <div className="chip-row">{LIKES.map(([v, t]) => (
            <label key={v} className="chip-check"><input type="checkbox" checked={likes.includes(v)} onChange={() => setLikes(toggle(likes, v))} />{t}</label>
          ))}</div>
          <label className="field"><span>In your words (optional)</span><textarea rows={2} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: the quick cuts and the captions low on the screen" /></label>
        </fieldset>
        <fieldset className="stack-2"><legend className="label">Only part of it? (optional)</legend>
          <div className="grid-2">
            <label className="field"><span>From (m:ss)</span><input inputMode="decimal" value={from} placeholder="0:00" onChange={(e) => setFrom(e.target.value)} /></label>
            <label className="field"><span>To (m:ss)</span><input inputMode="decimal" value={to} placeholder="the end" onChange={(e) => setTo(e.target.value)} /></label>
          </div>
          {rangeBad && <p className="small error-text">Give both times, at least one second apart, like 0:12 and 1:05.</p>}
        </fieldset>
        <label><input type="checkbox" checked={avoid} onChange={(e) => setAvoid(e.target.checked)} /> This is an example to avoid (shown for comparison, never applied)</label>
        {!avoid && !projectOnly && <fieldset className="stack-2"><legend className="label">When should new projects use it?</legend>
          <label><input type="radio" name="ex-scope" checked={scope === "chosen"} onChange={() => setScope("chosen")} /> Only when I choose it for a project</label>
          <label><input type="radio" name="ex-scope" checked={scope === "all"} onChange={() => setScope("all")} /> For every new project</label>
          <label><input type="radio" name="ex-scope" checked={scope === "modes"} onChange={() => setScope("modes")} /> For some kinds of project</label>
          {scope === "modes" && <div className="chip-row">{MODES.map(([v, t]) => (
            <label key={v} className="chip-check"><input type="checkbox" checked={modes.includes(v)} onChange={() => setModes(toggle(modes, v))} />{t}</label>))}</div>}
          <p className="small muted">Choices you make in a project always win over an example.</p>
        </fieldset>}
        <p className="small muted">The video stays private on this computer. It is measured here; it is not sent to any AI service.</p>
        {problem && <Banner tone="bad" title="Not added">{problem}</Banner>}
      </div>
    </Dialog>
  );
}

function ChoiceControl({ field, value, onChange, label }: { field?: Field; value: unknown; onChange: (v: unknown) => void; label: string }) {
  if (!field) return null;
  if (field.kind === "bool") {
    return <select aria-label={label} value={value ? "on" : "off"} onChange={(e) => onChange(e.target.value === "on")}>
      <option value="on">On</option><option value="off">Off</option></select>;
  }
  if (field.kind === "choice") {
    return <select aria-label={label} value={String(value)} onChange={(e) => onChange(typeof field.choices[0] === "number" ? Number(e.target.value) : e.target.value)}>
      {field.choices.map((c) => <option key={String(c)} value={String(c)}>{String(c).replace(/_/g, " ")}</option>)}</select>;
  }
  return <input aria-label={label} type="number" step={field.name === "shot_length_s" ? 0.5 : 1} min={field.minimum ?? undefined}
    max={field.maximum ?? undefined} value={Number(value)} onChange={(e) => onChange(Number(e.target.value))} />;
}

function ExampleDetail({ row, onChange, onDeleted }: { row: ExampleVideo; onChange: () => Promise<unknown>; onDeleted: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [fields, setFields] = useState<Record<string, Field>>({});
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [name, setName] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState(false);
  const [keepStyle, setKeepStyle] = useState(true);
  const [dropFile, setDropFile] = useState(false);
  const an = row.analysis;
  useEffect(() => {
    studio.capabilities().then((c) => setFields(Object.fromEntries(c.fields.map((f) => [f.name, f])))).catch(() => undefined);
  }, []);
  // Start from the saved style when there is one (its values, including your corrections), otherwise from what was measured.
  useEffect(() => {
    if (!an) return;
    const saved = row.style && row.style.provenance?.analysis_revision === an.revision ? row.style.values : null;
    setPicked(Object.fromEntries(an.applicable.map((x) => [x.field, saved ? x.field in saved : x.selected])));
    setValues(Object.fromEntries(an.applicable.map((x) => [x.field, saved && x.field in saved ? saved[x.field] : x.value])));
    setName(row.style?.name || "");
  }, [an?.revision, row.style?.revision]); // eslint-disable-line react-hooks/exhaustive-deps
  const seek = (ms: number) => {
    const v = video.current;
    if (!v) return;
    v.currentTime = ms / 1000;
    void v.play().catch(() => undefined);
  };
  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    setProblem("");
    try {
      await fn();
      if (done) toast(done);
      await onChange();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const chosen = useMemo(() => Object.fromEntries(Object.entries(values).filter(([k]) => picked[k])), [values, picked]);
  const groups = useMemo(() => {
    const out: Record<string, ApplyChoice[]> = {};
    for (const x of an?.applicable || []) (out[x.aspect] ||= []).push(x);
    return out;
  }, [an]);
  const cov = an?.coverage;
  return (
    <div className="ex-detail stack-3">
      <div className="ex-top">
        <video ref={video} src={row.media_url} controls preload="metadata" className="ex-video" aria-label={`Example video: ${row.title}`} />
        <div className="stack-2">
          {(row.status === "queued" || row.status === "analyzing") && <>
            <ProgressBar value={row.progress || 0} label={row.message || "Analyzing"} />
            <p className="small muted">{row.message || "Analyzing"}</p>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.cancelExample(row.id))}>Cancel analysis</button>
          </>}
          {row.status === "failed" && <Banner tone="bad" title="Not analyzed" actions={
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.analyzeExample(row.id))}>Analyze again</button>}>
            {row.error || "Something went wrong."}</Banner>}
          {row.status === "canceled" && <Banner tone="warn" title="Canceled" actions={
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.analyzeExample(row.id))}>Analyze again</button>}>{row.message}</Banner>}
          {row.note && <p className="small"><b>You said:</b> {row.note}</p>}
          {an && <div className="small muted stack-1">
            <span><b>How it was analyzed:</b> {an.method}</span>
            <span>{an.model_note}</span>
            {cov && <span>Compared {cov.frames_compared.toLocaleString()} frames ({cov.scan_fps || 10} per second) over {Math.round(cov.seconds || 0)} s and looked closely at {cov.stills} stills ({cov.still_method}). {an.speech_note}</span>}
            <span>Analysis revision {an.revision}{an.reused_from ? " (the same file was measured before; that result was reused)" : ""}.</span>
          </div>}
          <div className="row-actions" style={{ justifyContent: "flex-start" }}>
            <label className="small"><input type="checkbox" checked={row.enabled} disabled={busy} onChange={(e) => act(() => studio.patchExample(row.id, { enabled: e.target.checked }),
              e.target.checked ? "Enabled." : "Disabled. New projects stop using it; finished ones keep their choices.")} /> Enabled</label>
            {row.project_only && <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.patchExample(row.id, { project_only: false }), "Remembered in your Brain.")}>Remember for future projects</button>}
            {row.status !== "queued" && row.status !== "analyzing" && <button type="button" className="btn btn-small" disabled={busy} onClick={() => act(() => studio.analyzeExample(row.id), "Analyzing again. Your saved style stays as it is until you save again.")}>Reanalyze</button>}
            <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => setDel(true)}>Delete</button>
          </div>
          {!row.avoid && !row.project_only && <label className="field"><span>When new projects use it</span>
            <select value={row.scope} disabled={busy} onChange={(e) => act(() => studio.patchExample(row.id, { scope: e.target.value, modes: e.target.value === "modes" ? (row.modes.length ? row.modes : ["full_video"]) : row.modes }))}>
              <option value="chosen">Only when I choose it for a project</option>
              <option value="all">Every new project</option>
              <option value="modes">Some kinds of project</option>
            </select></label>}
          {row.scope === "modes" && !row.avoid && <div className="chip-row">{MODES.map(([v, t]) => (
            <label key={v} className="chip-check"><input type="checkbox" checked={row.modes.includes(v)} disabled={busy || (row.modes.length === 1 && row.modes.includes(v))}
              onChange={() => act(() => studio.patchExample(row.id, { modes: row.modes.includes(v) ? row.modes.filter((m) => m !== v) : [...row.modes, v] }))} />{t}</label>))}</div>}
        </div>
      </div>
      {problem && <Banner tone="bad" title="Not saved">{problem}</Banner>}
      {an && <section aria-labelledby={`ex-n-${row.id}`} className="stack-2">
        <h3 id={`ex-n-${row.id}`}>What I noticed</h3>
        <ul className="ex-notes">
          {an.observations.map((o) => (
            <li key={o.id}>
              <Pill tone={o.kind === "measured" ? "good" : "warn"} title={o.kind === "measured" ? "Measured directly" : "An estimate from a measurement; it can be wrong"}>
                {o.kind === "measured" ? "Measured" : `Estimate${o.confidence != null ? ` · ${Math.round(o.confidence * 100)}% sure` : ""}`}</Pill>
              <span>{o.text}</span>
              {o.evidence.length > 0 && <span className="ex-ev">{o.evidence.map((e, i) => (
                <button key={i} type="button" className="btn btn-small" onClick={() => seek(e.start_ms)} aria-label={`Play ${e.label || "moment"} at ${clock(e.start_ms)}`}>
                  <Icon name="play" />{clock(e.start_ms)}</button>))}</span>}
            </li>
          ))}
        </ul>
      </section>}
      {an && <section aria-labelledby={`ex-a-${row.id}`} className="stack-2">
        <h3 id={`ex-a-${row.id}`}>What I can apply</h3>
        {row.avoid ? <p className="small muted">This is an example to avoid. These readings are shown for comparison and are never applied.</p>
          : <p className="small muted">Tick what new projects should reuse and change any value. Saving creates a new revision of the example style; projects already made keep theirs.</p>}
        {an.applicable.length === 0 && <p className="small">Nothing measured here is something this editor can reproduce.</p>}
        {Object.entries(groups).map(([aspect, list]) => (
          <fieldset key={aspect} className="ex-apply" disabled={row.avoid || busy}>
            <legend className="label">{LIKES.find(([k]) => k === aspect)?.[1] || aspect}</legend>
            {list.map((x) => {
              const changed = picked[x.field] && JSON.stringify(values[x.field]) !== JSON.stringify(x.value);
              return (
                <div key={x.field} className="ex-apply-row">
                  <label><input type="checkbox" checked={!!picked[x.field]} onChange={(e) => setPicked({ ...picked, [x.field]: e.target.checked })} /> {x.label}</label>
                  <ChoiceControl field={fields[x.field]} label={x.label} value={values[x.field]} onChange={(v) => { setValues({ ...values, [x.field]: v }); setPicked({ ...picked, [x.field]: true }); }} />
                  <span className="small muted">{changed ? `Your correction (measured: ${String(x.value)})` : x.text}{x.modes.length < 3 ? ` · ${x.modes.map((m) => MODES.find(([k]) => k === m)?.[1]).join(", ")}` : ""}</span>
                </div>
              );
            })}
          </fieldset>
        ))}
        {!row.avoid && an.applicable.length > 0 && <div className="row-actions" style={{ justifyContent: "flex-start" }}>
          <label className="field" style={{ minWidth: 220 }}><span>Style name</span><input value={name} maxLength={60} placeholder={`${row.title} style`} onChange={(e) => setName(e.target.value)} /></label>
          <button type="button" className="btn btn-primary" disabled={busy || !Object.keys(chosen).length}
            onClick={() => act(() => studio.saveExampleStyle(row.id, { values: chosen, analysis_revision: an.revision, name: name.trim(),
              style_revision: row.style?.revision }), row.style ? "Saved a new revision of the example style." : "Saved. Choose this example when you make a project.")}>
            {row.style ? "Save changes" : "Save as example style"}</button>
        </div>}
        {row.style && <p className="small muted">Saved as “{row.style.name}”, revision {row.style.revision}, from analysis revision {row.style.provenance?.analysis_revision}.
          {(row.style.provenance?.corrections || []).length > 0 && ` Your corrections: ${row.style.provenance!.corrections!.map((c) => `${c.field.replace(/_/g, " ")} ${String(c.chosen)}`).join(", ")}.`}
          {row.style.provenance?.analysis_revision !== an.revision && " A newer analysis is shown above; save again to use it."}</p>}
        {an.unsupported.length > 0 && <details><summary className="small">Noticed but not reproduced by this editor</summary>
          <ul className="small">{an.unsupported.map((u, i) => <li key={i}>{u.text}</li>)}</ul></details>}
      </section>}
      {del && <ConfirmDialog title={`Delete “${row.title}”?`} danger confirmLabel="Delete example" onClose={() => setDel(false)}
        onConfirm={async () => { const r = await studio.deleteExample(row.id, keepStyle, dropFile); toast(r.notes.join(" ")); onDeleted(); }}>
        <p>Its analyses are deleted. Projects already made keep the choices they used, so they still explain and reproduce their plan.</p>
        {row.style && <label><input type="checkbox" checked={keepStyle} onChange={(e) => setKeepStyle(e.target.checked)} /> Keep the style “{row.style.name}” as a normal style</label>}
        <label><input type="checkbox" checked={dropFile} onChange={(e) => setDropFile(e.target.checked)} /> Also delete the video file (only if no project uses it)</label>
      </ConfirmDialog>}
    </div>
  );
}
