import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Field, Skill, Style, studio } from "../studio";
import { Banner, ConfirmDialog, Dialog, EmptyState, Icon, Pill, toast } from "./ui";

/** Brain → Styles: saved editing choices. Each change saves a new revision; older projects keep theirs. */
export function StylesTab() {
  const [rows, setRows] = useState<Style[] | null>(null);
  const [del, setDel] = useState<Style | null>(null);
  const [saving, setSaving] = useState(false);
  const load = useCallback(() => studio.styles().then(setRows).catch(() => setRows([])), []);
  useEffect(() => {
    void load();
  }, [load]);
  if (rows === null) return <p className="muted">Loading styles…</p>;
  return (
    <div className="stack-3">
      <p className="muted">A style remembers editing choices, such as caption placement, pace and shape. Changing it affects new projects only.</p>
      <div className="row-actions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className="btn" onClick={() => setSaving(true)}><Icon name="plus" />Save a style</button>
      </div>
      {rows.length === 0 && <EmptyState icon="spark" title="No saved styles yet" level={3}>Tick “Remember this style” when you make a YouTube video, or save one here.</EmptyState>}
      <div className="acct-grid">{rows.map((s) => (
        <article key={s.id} className="acct">
          <div className="panel-head"><b>{s.name}</b>{s.is_default && <Pill tone="accent">My saved style</Pill>}</div>
          <span className="small muted">Revision {s.revision} · {s.modes.map((m) => ({ highlights: "Highlights", full_stories: "Full stories", full_video: "Full videos" } as Record<string, string>)[m] || m).join(", ")}</span>
          <ul className="small">{s.effects.map((e) => <li key={e}>{e}</li>)}</ul>
          <div className="row-actions" style={{ justifyContent: "flex-start" }}>
            {!s.is_default && <button type="button" className="btn btn-small" onClick={async () => { await studio.defaultStyle(s.id); await load(); }}>Use as my saved style</button>}
            <button type="button" className="btn btn-small btn-danger" onClick={() => setDel(s)}>Delete</button>
          </div>
        </article>))}</div>
      {saving && <SaveStyleDialog onClose={() => setSaving(false)} onSaved={() => { setSaving(false); void load(); }} />}
      {del && <ConfirmDialog title={`Delete “${del.name}”?`} danger confirmLabel="Delete style" onClose={() => setDel(null)}
        onConfirm={async () => { await studio.deleteStyle(del.id); setDel(null); await load(); }}>
        <p>Projects that already used it keep the choices they were made with.</p></ConfirmDialog>}
    </div>
  );
}

const MODE_WORDS: Record<string, string> = { highlights: "Highlights", full_stories: "Full stories",
  full_video: "Full videos" };
const word = (v: unknown) => String(v).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Save a style by hand: a name, the project types it is for and the editing choices it remembers (only the
 * choices ClipForge applies; the server checks them again). Changing a style later saves a new revision. */
export function SaveStyleDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (s: Style) => void }) {
  const [fields, setFields] = useState<Field[] | null>(null);
  const [name, setName] = useState("");
  const [modes, setModes] = useState<string[]>(["highlights", "full_stories", "full_video"]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    studio.capabilities().then((c) => setFields(c.fields.filter((f) => f.kind !== "text"))).catch((e) => setProblem(errorText(e)));
  }, []);
  const shown = (fields || []).filter((f) => f.modes.some((m) => modes.includes(m)));
  const chosen = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== "" && v !== undefined
    && shown.some((f) => f.name === k)));
  const save = async () => {
    setBusy(true);
    setProblem("");
    try {
      const s = await studio.createStyle({ name, values: chosen, modes });
      toast(`Saved “${s.name}”. New projects can use it.`);
      onSaved(s);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog title="Save a style" wide onClose={onClose} actions={<>
      <button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary" disabled={busy || !name.trim() || !modes.length
        || !Object.keys(chosen).length} onClick={() => void save()}>Save style</button>
    </>}>
      <p className="small muted">A style remembers editing choices. Only the ones you set here are saved; everything else
        still comes from the project, other Brain items and Settings.</p>
      <label className="field"><span>Name</span>
        <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="For example: Calm interviews" /></label>
      <fieldset className="field"><legend>Use it for</legend>
        <div className="row wrap">{Object.entries(MODE_WORDS).map(([m, label]) => (
          <label key={m}><input type="checkbox" checked={modes.includes(m)}
            onChange={(e) => setModes((ms) => (e.target.checked ? [...ms, m] : ms.filter((x) => x !== m)))} /> {label}</label>
        ))}</div>
      </fieldset>
      {fields === null && !problem && <p className="muted small">Loading the editing choices…</p>}
      <div className="style-fields">
        {shown.map((f) => (
          <label key={f.name} className="field"><span>{f.label}</span>
            {f.kind === "number" ? (
              <input type="number" inputMode="decimal" min={f.minimum ?? undefined} max={f.maximum ?? undefined}
                value={values[f.name] === undefined ? "" : String(values[f.name])}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value === "" ? undefined : Number(e.target.value) }))}
                placeholder="Not set" />
            ) : (
              <select value={values[f.name] === undefined ? "" : String(values[f.name])}
                onChange={(e) => {
                  const raw = e.target.value;
                  const v = raw === "" ? undefined : f.kind === "bool" ? raw === "true"
                    : f.choices.find((c) => String(c) === raw);
                  setValues((old) => ({ ...old, [f.name]: v }));
                }}>
                <option value="">Not set</option>
                {f.kind === "bool"
                  ? <><option value="true">On</option><option value="false">Off</option></>
                  : f.choices.map((c) => <option key={String(c)} value={String(c)}>{word(c)}</option>)}
              </select>
            )}
            <span className="tiny muted">{f.modes.map((m) => MODE_WORDS[m] || m).join(", ")}</span>
          </label>
        ))}
      </div>
      {problem && <p className="error-text" role="alert"><Icon name="alert" />{problem}</p>}
    </Dialog>
  );
}

/** The lines of a skill that ClipForge AI reads as advice (the importer's own words for them, studio/skills.py). */
const ADVICE = "not an editing choice ClipForge applies yet";

/** What a skill does: the editing choices it sets, the advice ClipForge AI reads, and what is neither. */
function SkillLines({ s }: { s: Skill }) {
  const advice = s.unsupported.filter((u) => u.why === ADVICE);
  const rest = s.unsupported.filter((u) => u.why !== ADVICE);
  return (
    <div className="grid-2">
      <div><b className="small">Sets for new projects</b><ul className="small">{s.effects.length ? s.effects.map((e) => <li key={e}>{e}</li>) : <li>No editing choice: advice only</li>}</ul>
        {rest.length > 0 && <><b className="small">Not used</b><ul className="small">{rest.slice(0, 4).map((u, i) => <li key={i}>{u.text} <span className="muted">({u.why})</span></li>)}</ul></>}</div>
      <div><b className="small">ClipForge AI reads {advice.length === 1 ? "1 line" : `${advice.length} lines`} of advice</b>
        <ul className="small">{advice.slice(0, 4).map((u, i) => <li key={i}>{u.text}</li>)}
          {advice.length > 4 && <li className="muted">and {advice.length - 4} more</li>}
          {advice.length === 0 && <li>None</li>}</ul></div>
    </div>
  );
}

/**
 * Brain → Skills: imported editing guides. Nothing in a skill runs. A switched-on skill sets the editing choices
 * ClipForge supports for new projects, and ClipForge AI reads its advice when it picks clips, writes titles and
 * post text, and answers in the chat.
 */
export function SkillsTab() {
  const [rows, setRows] = useState<Skill[] | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const load = useCallback(() => studio.skills().then(setRows).catch(() => setRows([])), []);
  useEffect(() => {
    void load();
  }, [load]);
  /** One file or many at once (a folder of skills is imported in one go). Each file is checked on its own. */
  const add = async (files: File[]) => {
    setProblem("");
    setBusy(true);
    const done: string[] = [];
    const failed: string[] = [];
    for (const file of files) {
      try {
        done.push((await studio.importSkill(file)).name);
      } catch (e) {
        failed.push(`${file.name}: ${errorText(e)}`);
      }
    }
    await load();
    setBusy(false);
    if (done.length === 1) toast(`Imported “${done[0]}”. Check what it would change, then switch it on.`);
    else if (done.length > 1) toast(`Imported ${done.length} skills. Switch them on for ClipForge AI to read them.`);
    if (failed.length) setProblem(failed.slice(0, 5).join(" ") + (failed.length > 5 ? ` And ${failed.length - 5} more.` : ""));
  };
  const switchAll = async (on: boolean) => {
    setBusy(true);
    setProblem("");
    try {
      for (const s of rows || []) if (s.enabled !== on) await studio.patchSkill(s.id, { enabled: on });
      toast(on ? "Every skill is on" : "Every skill is off");
    } catch (e) {
      setProblem(errorText(e));
    }
    await load();
    setBusy(false);
  };
  const on = (rows || []).filter((s) => s.enabled).length;
  return (
    <div className="stack-3">
      <p className="muted">Import Markdown, text or ClipForge JSON skills, one or many at once. A switched-on skill sets the editing choices ClipForge supports for new projects, and ClipForge AI reads its advice when it picks clips, writes titles and post text, and answers you. ClipForge never runs commands, scripts or links from a skill.</p>
      <div className="row-actions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className="btn" disabled={busy} onClick={() => input.current?.click()}><Icon name="upload" />Import skills</button>
        <button type="button" className="btn" disabled={busy} onClick={async () => { const ex = await studio.exampleSkill(); await add([new File([ex.text], ex.filename, { type: "text/markdown" })]); }}>
          Add the example skill</button>
        {rows && rows.length > 1 && on < rows.length && <button type="button" className="btn" disabled={busy} onClick={() => void switchAll(true)}>Switch all on</button>}
        {rows && rows.length > 1 && on > 0 && <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => void switchAll(false)}>Switch all off</button>}
        <input ref={input} type="file" accept=".md,.markdown,.txt,.json" multiple hidden
          onChange={(e) => { const files = Array.from(e.target.files || []); e.target.value = ""; if (files.length) void add(files); }} />
      </div>
      {rows && rows.length > 0 && <p className="small muted" role="status">{on} of {rows.length} switched on.</p>}
      {problem && <Banner tone="bad" title="Not imported">{problem}</Banner>}
      {rows && rows.length === 0 && <EmptyState icon="spark" title="No skills yet" level={3}>Try the example skill to see how it works.</EmptyState>}
      {(rows || []).map((s) => (
        <article key={s.id} className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>{s.name}</h3>
            <label><input type="checkbox" checked={s.enabled} disabled={busy} onChange={async (e) => { await studio.patchSkill(s.id, { enabled: e.target.checked }); await load(); }} /> {s.enabled ? "On: used and read" : "Off"}</label></div>
          {s.description && <p className="small muted">{s.description}</p>}
          <SkillLines s={s} />
          {s.blocked.length > 0 && <Banner tone="warn" title={`${s.blocked.length} instruction${s.blocked.length > 1 ? "s" : ""} refused`}>
            <ul className="small">{s.blocked.slice(0, 6).map((b, i) => <li key={i}>{b.text} <span className="muted">({b.why})</span></li>)}</ul>
            Skills can only change editing choices. They never run code, use secrets, change accounts or publish.</Banner>}
          <div className="row-actions" style={{ justifyContent: "flex-start" }}>
            <a className="btn btn-small" href={`/api/studio/skills/${s.id}/export`}><Icon name="download" />Export</a>
            <button type="button" className="btn btn-small btn-danger" onClick={async () => { await studio.deleteSkill(s.id); await load(); }}>Delete</button>
          </div>
        </article>
      ))}
    </div>
  );
}
