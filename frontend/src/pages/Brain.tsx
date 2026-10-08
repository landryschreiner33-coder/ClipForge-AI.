import { FormEvent, useEffect, useState } from "react";
import { errorText } from "../api";
import { DecisionPreview, Influence, Knowledge, KnowledgeInput, KnowledgeKind, knowledgeApi, Preferences, Workspace } from "../brain";
import { Banner, Dialog, EmptyState, Icon, LinkTabs, PageHead, toast } from "../components/ui";
import "./Brain.css";

const stateLabel = { reference: "Searchable reference", approved: "Approved for new clips", needs_approval: "Needs approval", disabled: "Disabled" };
const pretty = (key: string) => key.replace(/_/g, " ");
const valueLabel = (value: unknown) => typeof value === "boolean" ? value ? "on" : "off" : value == null ? "default" : pretty(String(value));
const date = (at: number) => new Date(at * 1000).toLocaleDateString();
const empty = (kind: KnowledgeKind): KnowledgeInput => ({ kind, title: "", content: "", tags: [], features: {}, preferences: {},
  example_label: kind === "example" ? "good" : "", enabled: true });

export default function Brain({ tab = "knowledge" }: { tab?: string }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [rows, setRows] = useState<Knowledge[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState("");
  const [approval, setApproval] = useState<Knowledge | null>(null);
  const [removing, setRemoving] = useState<Knowledge | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const examples = tab === "examples";
  const active = ["knowledge", "examples", "decisions", "results"].includes(tab) ? tab : "knowledge";

  const refresh = async () => {
    try {
      const [all, ws] = await Promise.all([knowledgeApi.list(), knowledgeApi.workspace()]);
      setRows(all);
      setWorkspace(ws);
      setProblem("");
    } catch (error) { setProblem(errorText(error)); }
  };
  useEffect(() => { void refresh(); }, []);
  useEffect(() => { setAdding(false); setSelected(null); setQuery(""); }, [tab]);
  const filtered = rows.filter((row) => (examples ? row.kind === "example" : row.kind !== "example") &&
    (!query || [row.title, row.content, ...row.tags, ...Object.values(row.features)].join(" ").toLowerCase().includes(query.toLowerCase())));
  const chosen = adding ? null : filtered.find((row) => row.id === selected) || filtered[0] || null;
  const save = async (data: KnowledgeInput, file: File | null) => {
    const saved = chosen && !adding ? await knowledgeApi.edit(chosen.id, data) : file ? await knowledgeApi.upload(file, data) : await knowledgeApi.create(data);
    setAdding(false);
    setSelected(saved.id);
    await refresh();
    toast(saved.kind === "reference" ? "Reference saved" : "Saved. Review and approve its clip preferences to use them.");
  };
  const action = async (run: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try { await run(); await refresh(); toast(message); }
    catch (error) { setProblem(errorText(error)); }
    finally { setBusy(false); }
  };

  return <div className="page brain-page">
    <PageHead kind="CORE / Local memory" title="Brain" sub="Teach your clip preferences. Inspect what changed and the real results behind it."
      actions={<a className="btn btn-small" href={knowledgeApi.export} download><Icon name="download" />Export knowledge</a>} />
    <LinkTabs label="Brain sections" current={active} tabs={[
      { id: "knowledge", href: "#/brain", label: "Knowledge" }, { id: "examples", href: "#/brain/examples", label: "Examples" },
      { id: "decisions", href: "#/brain/decisions", label: "Decisions" }, { id: "results", href: "#/brain/results", label: "Performance history" },
    ]} />
    {problem && <Banner tone="bad" title="Could not complete this action">{problem}</Banner>}
    {workspace && <div className="brain-summary" aria-label="Brain memory overview">
      <div><strong>{workspace.counts.total}</strong><span>saved references & examples</span></div>
      <div><strong>{workspace.counts.approved}</strong><span>approved clip preferences</span></div>
      <div><strong>{Object.values(workspace.brain.observations).reduce((a, b) => a + b, 0)}</strong><span>separate result readings</span></div>
    </div>}
    {(active === "knowledge" || active === "examples") && <>
      <div className="brain-toolbar">
        <p className="brain-note">{examples ? "Good and bad examples record your judgment. Add specific preferences to repeat what works or correct what does not."
          : "Documents stay searchable. Only the clip preferences you separately approve change new Autopilot plans."}</p>
        <div className="brain-actions"><button className="btn btn-small" onClick={() => setPreviewing(true)}><Icon name="spark" />Try a decision</button>
          <button className="btn btn-primary btn-small" onClick={() => { setAdding(true); setSelected(null); }}><Icon name="plus" />{examples ? "Add example" : "Add knowledge"}</button></div>
      </div>
      <div className="brain-grid">
        <aside className="brain-list" aria-label="Saved knowledge">
          <label className="field"><span>Search {examples ? "examples" : "knowledge"}</span><input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Title, topic, notes, or feature" /></label>
          {filtered.map((item) => <button key={item.id} aria-pressed={chosen?.id === item.id && !adding} onClick={() => { setSelected(item.id); setAdding(false); }}>
            <div className="brain-tags"><span className={`brain-pill ${item.state}`}>{stateLabel[item.state]}</span>
              <span className="brain-pill">{item.kind === "example" ? `${item.example_label} example` : item.kind}</span></div>
            <strong>{item.title}</strong>
            <small>{item.filename || "Written here"} · revision {item.revision} · {date(item.updated_at)}</small>
            {item.tags.length > 0 && <div className="brain-tags">{item.tags.map((tag) => <span className="brain-pill" key={tag}>{tag}</span>)}</div>}
          </button>)}
          {!filtered.length && <p className="brain-note">{query ? "No saved knowledge matches this search." : "Your memory starts here. Add a guide or example to teach your preferences."}</p>}
        </aside>
        <KnowledgeEditor key={`${chosen?.id || "new"}:${chosen?.revision || 0}:${examples}`} item={chosen} kind={examples ? "example" : "reference"}
          onSave={save} onApprove={setApproval} onDelete={setRemoving}
          onToggle={(item) => void action(() => knowledgeApi.edit(item.id, { enabled: !item.enabled }), item.enabled ? "Disabled for future clips" : "Knowledge enabled")} />
      </div>
      <p className="brain-note">Files stay on this computer. Uploading does not fine-tune a model. Prose and uploaded code are never executed or sent to an AI service. Approved preferences affect new clips; existing projects keep their saved plans.</p>
    </>}
    {active === "decisions" && <DecisionHistory rows={workspace?.influences || []} onTry={() => setPreviewing(true)} />}
    {active === "results" && workspace && <PerformanceHistory workspace={workspace} />}
    {!workspace && !problem && <p className="muted">Loading local memory…</p>}
    {approval && <Dialog title="Approve these clip preferences?" onClose={() => setApproval(null)} actions={<>
      <button className="btn" disabled={busy} onClick={() => setApproval(null)}>Cancel</button>
      <button className="btn btn-primary" disabled={busy} onClick={() => void action(async () => { await knowledgeApi.approve(approval); setApproval(null); }, "Preferences approved for new clips")}><Icon name="check" />Approve preferences</button>
    </>}><p><b>{approval.title}</b> · revision {approval.revision}</p>
      <ul className="op-list">{Object.entries(approval.preferences).map(([key, value]) => <li key={key}>{pretty(key)}: <b>{valueLabel(value)}</b></li>)}</ul>
      <p className="brain-note">{approval.tags.length ? `Applies when a clip contains a topic tag: ${approval.tags.join(", ")}.` : "Applies to all new Autopilot clips."} Instructions take priority over examples; the newest approval wins within each kind. Uploaded prose remains a reference.</p>
    </Dialog>}
    {removing && <Dialog title="Delete saved knowledge?" onClose={() => setRemoving(null)} actions={<>
      <button className="btn" disabled={busy} onClick={() => setRemoving(null)}>Keep it</button>
      <button className="btn btn-danger" disabled={busy} onClick={() => void action(async () => { await knowledgeApi.delete(removing.id); setRemoving(null); }, "Knowledge and its uploaded file deleted")}><Icon name="trash" />Delete knowledge</button>
    </>}><p>This deletes <b>{removing.title}</b> and its uploaded file. Existing clips keep the revision snapshot explaining their decision.</p></Dialog>}
    {previewing && <DecisionTry onClose={() => setPreviewing(false)} />}
  </div>;
}

function KnowledgeEditor({ item, kind, onSave, onApprove, onToggle, onDelete }: {
  item: Knowledge | null; kind: KnowledgeKind; onSave: (data: KnowledgeInput, file: File | null) => Promise<void>;
  onApprove: (item: Knowledge) => void; onToggle: (item: Knowledge) => void; onDelete: (item: Knowledge) => void;
}) {
  const [data, setData] = useState<KnowledgeInput>(item ? { kind: item.kind, title: item.title, content: item.content, tags: item.tags,
    features: item.features, preferences: item.preferences, example_label: item.example_label, enabled: item.enabled } : empty(kind));
  const [tags, setTags] = useState(data.tags.join(", "));
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const isExample = data.kind === "example";
  const preference = (key: keyof Preferences, value: string) => {
    const next = { ...data.preferences };
    if (!value) delete next[key];
    else if (key === "caption_emphasis") next.caption_emphasis = value === "true";
    else next[key] = value;
    setData({ ...data, preferences: next });
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setProblem("");
    try { await onSave({ ...data, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }, file); }
    catch (error) { setProblem(errorText(error)); }
    finally { setBusy(false); }
  };
  return <form className="card brain-editor" onSubmit={submit}>
    <div className="brain-toolbar"><h2>{item ? "Saved knowledge" : isExample ? "New example" : "New knowledge"}</h2>
      {item && <span className={`brain-pill ${item.state}`}>{stateLabel[item.state]}</span>}</div>
    {item?.has_asset && isExample && <video controls preload="metadata" src={knowledgeApi.asset(item.id)} aria-label={item.title} />}
    {item?.media.duration_s != null && <p className="brain-note">Measured locally: {item.media.duration_s.toFixed(1)} seconds · {item.media.width} × {item.media.height} · {item.media.has_audio ? "audio present" : "no audio"}</p>}
    <label><span>Title</span><input required maxLength={160} value={data.title} onChange={(e) => setData({ ...data, title: e.target.value })} placeholder={isExample ? "A hook worth repeating" : "My clip style guide"} /></label>
    {!isExample && <label><span>Use as</span><select value={data.kind} onChange={(e) => setData({ ...data, kind: e.target.value as KnowledgeKind,
      preferences: e.target.value === "reference" ? {} : data.preferences })}>
      <option value="reference">Searchable reference</option><option value="instruction">Instruction / skill guide</option>
    </select></label>}
    {!item && <label><span>{isExample ? "Example clip (optional)" : "Upload a document (optional)"}</span>
      <input type="file" accept={isExample ? ".mp4,.mov,.webm" : ".txt,.md,.csv,.json,.docx"} onChange={(e) => {
        const chosen = e.target.files?.[0] || null;
        if (chosen && chosen.size > (isExample ? 64 : 2) * 1024 * 1024) { setProblem(`Choose a file smaller than ${isExample ? 64 : 2} MB.`); e.target.value = ""; setFile(null); }
        else { setFile(chosen); setProblem(""); }
      }} /><small className="brain-note">{isExample ? "MP4, MOV, WebM · up to 64 MB and 10 minutes. Feature labels come from you." : "TXT, Markdown, CSV, JSON, DOCX · up to 2 MB. Text becomes searchable; no macros or code run."}</small></label>}
    {isExample && <>
      <label><span>Example judgment</span><select value={data.example_label} onChange={(e) => setData({ ...data, example_label: e.target.value })}>
        <option value="good">Good — useful to repeat</option><option value="bad">Bad — useful to learn from</option>
      </select></label>
      <fieldset><legend>Useful features</legend><div className="brain-field-grid">{["hook", "pacing", "captions", "storytelling"].map((feature) =>
        <label key={feature}><span>{feature.charAt(0).toUpperCase() + feature.slice(1)}</span><textarea maxLength={2000} value={data.features[feature] || ""}
          onChange={(e) => setData({ ...data, features: { ...data.features, [feature]: e.target.value } })} placeholder={`What ${data.example_label === "bad" ? "fails" : "works"} here?`} /></label>)}</div></fieldset>
    </>}
    <label><span>{item?.filename && !isExample ? "Searchable document text & notes" : "Notes / instructions"}</span><textarea maxLength={100000} value={data.content} onChange={(e) => setData({ ...data, content: e.target.value })}
      placeholder="Describe the lesson in your own words. These notes are saved as reference text." /></label>
    <label><span>Topic tags (optional, separated by commas)</span><input value={tags} onChange={(e) => setTags(e.target.value)} maxLength={1000} placeholder="science, basketball, cooking" />
      <small className="brain-note">With tags, preferences apply only when the clip's text or category contains one. Without tags, they apply to every new Autopilot clip.</small></label>
    {data.kind !== "reference" && <fieldset><legend>{data.example_label === "bad" ? "Corrective preferences for future clips" : "Preferences for future clips"}</legend>
      <p className="brain-note">Only these supported choices affect clip plans. Save, then review and approve them separately.</p>
      <div className="brain-field-grid">
        <label><span>Caption style</span><select value={data.preferences.caption_style || ""} onChange={(e) => preference("caption_style", e.target.value)}>
          <option value="">Keep the app default</option>{["clean", "bold", "high_energy", "minimal"].map((style) => <option key={style} value={style}>{pretty(style)}</option>)}
        </select></label>
        <label><span>Caption position</span><select value={data.preferences.caption_position || ""} onChange={(e) => preference("caption_position", e.target.value)}>
          <option value="">Keep the app default</option>{["bottom", "middle", "top"].map((position) => <option key={position}>{position}</option>)}
        </select></label>
        <label><span>Pacing</span><select value={data.preferences.pacing || ""} onChange={(e) => preference("pacing", e.target.value)}>
          <option value="">Keep the app default</option><option value="safe_cuts">Remove weak middle sentences when safe</option><option value="continuous">Keep the story continuous</option>
        </select></label>
        <label><span>Caption emphasis</span><select value={data.preferences.caption_emphasis === undefined ? "" : String(data.preferences.caption_emphasis)} onChange={(e) => preference("caption_emphasis", e.target.value)}>
          <option value="">Keep the app default</option><option value="true">On</option><option value="false">Off</option>
        </select></label>
      </div>
    </fieldset>}
    {problem && <p className="error-text" role="alert">{problem}</p>}
    <div className="brain-actions"><button type="submit" className="btn btn-primary" disabled={busy}><Icon name="check" />{busy ? "Saving…" : item ? "Save changes" : "Save knowledge"}</button>
      {item && <>
        {item.kind !== "reference" && !item.approved && item.enabled && Object.keys(item.preferences).length > 0 && <button type="button" className="btn" onClick={() => onApprove(item)}>Review & approve</button>}
        <button type="button" className="btn btn-quiet" onClick={() => onToggle(item)}>{item.enabled ? "Disable" : "Enable"}</button>
        {item.has_asset && <a className="btn btn-quiet" href={knowledgeApi.asset(item.id, true)} download><Icon name="download" />Original</a>}
        <button type="button" className="btn btn-quiet brain-delete" aria-label="Delete this knowledge" onClick={() => onDelete(item)}><Icon name="trash" /></button>
      </>}
    </div>
    {item?.approved && <p className="brain-note">Approved revision {item.revision}. Editing the lesson or preferences requires a new approval.</p>}
  </form>;
}

function DecisionHistory({ rows, onTry }: { rows: Influence[]; onTry: () => void }) {
  return <div className="brain-decision-list">
    <Banner title="An explanation you can inspect">Each entry records a saved instruction or example that changed a new clip's blueprint, including the exact revision and before / after choice. Disabling a lesson affects future plans.</Banner>
    {!rows.length ? <EmptyState icon="spark" title="No saved preferences have changed a clip yet"
      actions={<button className="btn btn-primary" onClick={onTry}>Try a decision</button>}>Approve an instruction or example, then let Autopilot make a new clip. A preview can show which preferences would apply.</EmptyState>
      : rows.map((row) => <article className="card" key={row.id}>
        <div className="brain-toolbar"><h2><a href={`#/clip/${row.clip_id}`}>{row.clip_title}</a></h2><span className="muted tiny">{date(row.created_at)}</span></div>
        <p className="brain-note">{row.snapshot.title} · {row.snapshot.kind}{row.snapshot.example_label ? ` (${row.snapshot.example_label})` : ""} · revision {row.revision}{!row.knowledge_exists ? " · original knowledge deleted; snapshot retained" : ""}</p>
        <ul>{Object.entries(row.decisions).map(([key, choice]) => <li key={key}><b>{pretty(key)}</b>: {valueLabel(choice.before)} → {valueLabel(choice.after)}</li>)}</ul>
      </article>)}
  </div>;
}

function PerformanceHistory({ workspace }: { workspace: Workspace }) {
  const provenance: Record<string, string> = { platform_api: "Official platform reading", owner_import: "Owner import", tester_feedback: "Tester feedback" };
  return <>
    <Banner title={workspace.brain.label}>{workspace.brain.message} Strategy changes require at least {workspace.brain.min_clips} mature clips from five source videos; each update is limited to {Math.round(workspace.brain.max_step * 100)}%.</Banner>
    <div className="brain-history"><section className="card brain-history-list"><div className="brain-toolbar"><h2>Real results</h2><a className="btn btn-small" href="#/clips/feedback">Add feedback / import</a></div>
      <p className="brain-note">Examples and teaching documents never count as views or posting results. Audiences and platforms stay separate; missing numbers stay missing.</p>
      {!workspace.observations.length && <p className="muted">No result readings yet.</p>}
      {workspace.observations.map((row) => <article key={row.id}><h3><a href={`#/clip/${row.clip_id}`}>{row.clip_title}</a></h3>
        <p className="brain-note">{provenance[row.provenance] || row.provenance} · {row.platform || "direct testers"} · {pretty(row.cohort)} · {date(row.observed_at)}</p>
        <p>{Object.entries(row.metrics).filter(([, value]) => value !== null).map(([key, value]) => `${pretty(key)}: ${value}`).join(" · ")}</p>
        {row.note && <p className="brain-note">{row.note}</p>}
      </article>)}
    </section><section className="card brain-history-list"><h2>Strategy history</h2>
      {!workspace.history.length && <p className="muted">No automatic strategy changes yet. Your own preferences remain in use.</p>}
      {workspace.history.map((row) => <article key={row.id}><h3>{row.platform} · {pretty(row.cohort)} · v{row.version}</h3>
        <p className="brain-note">{pretty(row.status)} · {date(row.created_at)}</p><p>{row.reason}</p>
      </article>)}
    </section></div>
  </>;
}

function DecisionTry({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<DecisionPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const run = async () => {
    setBusy(true); setProblem("");
    try { setResult(await knowledgeApi.preview(text)); }
    catch (error) { setProblem(errorText(error)); }
    finally { setBusy(false); }
  };
  return <Dialog title="Try a later clip decision" onClose={onClose} actions={<>
    <button className="btn" onClick={onClose}>Close</button>
    <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => void run()}><Icon name="spark" />{busy ? "Checking…" : "Apply approved preferences"}</button>
  </>}>
    <div className="brain-preview"><p className="brain-note">Paste a clip topic or sample transcript. This uses the same approved-preference lookup as a new Autopilot plan.</p>
      <label className="field"><span>Clip context</span><textarea value={text} maxLength={10000} onChange={(e) => { setText(e.target.value); setResult(null); }} placeholder="A clip about the science of sleep…" /></label>
      {problem && <p className="error-text" role="alert">{problem}</p>}
      {result && <div className="brain-preview-result" aria-live="polite">
        {result.influences.length ? result.influences.map((row) => <div key={row.knowledge_id}><b>{row.snapshot.title}</b><p className="brain-note">Revision {row.revision}</p>
          {Object.entries(row.decisions).map(([key, change]) => <p key={key}>{pretty(key)}: {valueLabel(change.before)} → <b>{valueLabel(change.after)}</b></p>)}
        </div>) : <p>No approved lesson changes these defaults. Check its approval, topic tags, and preferences.</p>}
        <p className="brain-note">{result.note}</p>
      </div>}
    </div>
  </Dialog>;
}
