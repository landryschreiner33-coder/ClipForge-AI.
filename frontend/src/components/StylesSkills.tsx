import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Skill, Style, studio } from "../studio";
import { Banner, ConfirmDialog, EmptyState, Icon, Pill, toast } from "./ui";

/** Brain → Styles: saved editing choices. Each change saves a new revision; older projects keep theirs. */
export function StylesTab() {
  const [rows, setRows] = useState<Style[] | null>(null);
  const [del, setDel] = useState<Style | null>(null);
  const load = useCallback(() => studio.styles().then(setRows).catch(() => setRows([])), []);
  useEffect(() => {
    void load();
  }, [load]);
  if (rows === null) return <p className="muted">Loading styles…</p>;
  return (
    <div className="stack-3">
      <p className="muted">A style remembers editing choices, such as caption placement, pace and shape. Changing it affects new projects only.</p>
      {rows.length === 0 && <EmptyState icon="spark" title="No saved styles yet" level={3}>Tick “Remember this style” when you make a YouTube video, or save one below.</EmptyState>}
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
      {del && <ConfirmDialog title={`Delete “${del.name}”?`} danger confirmLabel="Delete style" onClose={() => setDel(null)}
        onConfirm={async () => { await studio.deleteStyle(del.id); setDel(null); await load(); }}>
        <p>Projects that already used it keep the choices they were made with.</p></ConfirmDialog>}
    </div>
  );
}

/** Brain → Skills: imported editing instructions. Nothing in a skill runs; only supported editing choices apply. */
export function SkillsTab() {
  const [rows, setRows] = useState<Skill[] | null>(null);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const load = useCallback(() => studio.skills().then(setRows).catch(() => setRows([])), []);
  useEffect(() => {
    void load();
  }, [load]);
  const add = async (file: File) => {
    setProblem("");
    try {
      const s = await studio.importSkill(file);
      toast(`Imported “${s.name}”. Check what it would change, then switch it on.`);
      await load();
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  return (
    <div className="stack-3">
      <p className="muted">Import a Markdown, text or ClipForge JSON skill. ClipForge reads the editing choices it supports and shows the rest; it never runs commands, scripts or links from a skill.</p>
      <div className="row-actions" style={{ justifyContent: "flex-start" }}>
        <button type="button" className="btn" onClick={() => input.current?.click()}><Icon name="upload" />Import a skill</button>
        <button type="button" className="btn" onClick={async () => { const ex = await studio.exampleSkill(); await add(new File([ex.text], ex.filename, { type: "text/markdown" })); }}>
          Add the example skill</button>
        <input ref={input} type="file" accept=".md,.markdown,.txt,.json" hidden onChange={(e) => e.target.files?.[0] && void add(e.target.files[0])} />
      </div>
      {problem && <Banner tone="bad" title="Not imported">{problem}</Banner>}
      {rows && rows.length === 0 && <EmptyState icon="spark" title="No skills yet" level={3}>Try the example skill to see how it works.</EmptyState>}
      {(rows || []).map((s) => (
        <article key={s.id} className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>{s.name}</h3>
            <label><input type="checkbox" checked={s.enabled} onChange={async (e) => { await studio.patchSkill(s.id, { enabled: e.target.checked }); await load(); }} /> {s.enabled ? "On for new projects" : "Off"}</label></div>
          {s.description && <p className="small muted">{s.description}</p>}
          <div className="grid-2">
            <div><b className="small">Will change</b><ul className="small">{s.effects.length ? s.effects.map((e) => <li key={e}>{e}</li>) : <li>Nothing ClipForge supports yet</li>}</ul></div>
            <div><b className="small">Not applied</b><ul className="small">{s.unsupported.slice(0, 6).map((u, i) => <li key={i}>{u.text} <span className="muted">({u.why})</span></li>)}
              {s.unsupported.length === 0 && <li>Nothing</li>}</ul></div>
          </div>
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
