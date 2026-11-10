import { ChangeEvent, useCallback, useEffect, useState } from "react";
import { api, errorText, Taste } from "../api";
import { KnowHow, Memory, memoryApi, MemoryCheck, MemoryKind, MemoryUse } from "../brain";
import { ConfirmDialog, EmptyState, Icon, Pill, toast } from "./ui";

const KIND_WORD: Record<MemoryKind, string> = { rule: "Rule", fact: "Fact", episode: "What it did", asset: "Asset", answer: "Answer" };
const SOURCE_WORD: Record<Memory["source"], string> = { said: "You said it", did: "From what it did", guessed: "Its guess", imported: "Imported" };
const WHERE_WORD: Record<string, string> = { change_request: "a change you asked for", filmcraft: "the FilmCraft finishing pass",
  smart_edit: "a smart edit", chat: "the chat", guidance: "guidance", short_script: "writing a short" };
const scopeWord = (m: Memory) => m.scope === "all" ? "Every video" : m.scope.startsWith("project:") ? "One video"
  : m.scope.startsWith("platform:") ? m.scope.slice(9) : m.scope.replace(":", " ");
const date = (at: number) => new Date(at * 1000).toLocaleDateString();
const mb = (bytes: number) => bytes < 1e6 ? `${Math.round(bytes / 1e3)} KB` : `${(bytes / 1e6).toFixed(1)} MB`;

/**
 * Brain → Memory: what ClipForge AI remembers (rules it follows, facts about you and your channel, and what it did),
 * where each memory was used, and the brain's health. Everything here stays on this computer unless you export it.
 */
export function MemoryTab() {
  const [rows, setRows] = useState<Memory[] | null>(null);
  const [check, setCheck] = useState<MemoryCheck | null>(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [add, setAdd] = useState({ text: "", kind: "fact" as MemoryKind });
  const [edit, setEdit] = useState<{ id: string; text: string } | null>(null);
  const [del, setDel] = useState<Memory | null>(null);
  const [uses, setUses] = useState<Record<string, MemoryUse[]>>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [knowhow, setKnowhow] = useState<KnowHow | null>(null);
  const [open, setOpen] = useState<string>("");
  const [taste, setTaste] = useState<Taste | null>(null);
  const [forgetTaste, setForgetTaste] = useState(false);
  useEffect(() => {
    memoryApi.knowhow().then(setKnowhow).catch(() => setKnowhow({ topics: [], source: "", tasks: [] }));
    api.taste().then(setTaste).catch(() => setTaste(null));
  }, []);

  const load = useCallback(async () => {
    try {
      const [list, health] = await Promise.all([memoryApi.list(q, kind), memoryApi.check()]);
      setRows(list);
      setCheck(health);
      setProblem("");
    } catch (e) {
      setProblem(errorText(e));
      setRows((r) => r || []);
    }
  }, [q, kind]);
  useEffect(() => {
    const t = window.setTimeout(() => void load(), q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [load, q]);

  const run = async (fn: () => Promise<unknown>, done?: (r: never) => string) => {
    setBusy(true);
    try {
      const r = await fn();
      if (done) toast(done(r as never));
      await load();
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  const importFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    let data: unknown;
    try { data = JSON.parse(await file.text()); } catch { toast("That file is not a ClipForge AI brain file.", true); return; }
    await run(() => memoryApi.import(data), (r: { added: number; updated: number; skipped: number; invalid: number }) =>
      `Imported: ${r.added} added, ${r.updated} updated, ${r.skipped} already known${r.invalid ? `, ${r.invalid} invalid` : ""}.`);
  };
  const showUses = async (m: Memory) => {
    if (uses[m.id]) { setUses(({ [m.id]: _gone, ...rest }) => rest); return; }
    try { setUses({ ...uses, [m.id]: await memoryApi.uses(m.id) }); } catch (e) { toast(errorText(e), true); }
  };

  if (rows === null) return <p className="muted">Loading ClipForge AI's memory…</p>;
  const counts = check?.counts || {};
  return (
    <div className="stack-3">
      <p className="muted">What ClipForge AI remembers: rules it always follows, facts about you and your channel, and what it did.
        Teach it here or in any chat (“remember: …”, “always …”, “never …”). It stays on this computer unless you export it.</p>
      {problem && <p className="error-text"><Icon name="alert" />{problem}</p>}

      <section className="panel tight" aria-labelledby="mem-health">
        <div className="panel-head"><h3 id="mem-health">The brain</h3>
          {check && <Pill tone={check.ok ? "good" : "warn"}>{check.ok ? "Healthy" : `${check.problems.length} thing${check.problems.length === 1 ? "" : "s"} to tidy`}</Pill>}</div>
        {check && <div className="mem-meta">
          <span>{check.total} memor{check.total === 1 ? "y" : "ies"} ({check.enabled} on)</span>
          {(["rule", "fact", "episode"] as MemoryKind[]).map((k) => <span key={k}>{counts[k] || 0} {KIND_WORD[k].toLowerCase()}{k === "episode" ? "" : "s"}</span>)}
          <span>used {check.uses} time{check.uses === 1 ? "" : "s"}</span>
          <span>{mb(check.size_bytes)}</span>
        </div>}
        {check && check.problems.length > 0 && <ul className="small">{check.problems.map((p) => <li key={p.code}>{p.text}</li>)}</ul>}
        <div className="row wrap">
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void run(memoryApi.tidy, (r: { expired: number; merged: number }) => `Tidied: ${r.expired} expired removed, ${r.merged} twins merged.`)}><Icon name="refresh" />Tidy</button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => void run(memoryApi.rebuild, (r: { rebuilt: number }) => `Rebuilt the meaning of ${r.rebuilt} memor${r.rebuilt === 1 ? "y" : "ies"}.`)}><Icon name="cpu" />Rebuild</button>
          <a className="btn btn-small" href={memoryApi.exportUrl} download="clipforge-ai-brain.json"><Icon name="download" />Export</a>
          <label className="btn btn-small"><Icon name="upload" />Import<input type="file" accept="application/json,.json" hidden onChange={(e) => void importFile(e)} /></label>
        </div>
      </section>

      <section className="panel tight" aria-labelledby="mem-taste">
        <div className="panel-head"><h3 id="mem-taste">What it learned from your choices</h3>
          {taste && <Pill tone={taste.ready ? "good" : "info"}>{taste.ready ? "Learning your taste" : `${taste.events} lesson${taste.events === 1 ? "" : "s"}`}</Pill>}</div>
        <p className="small muted">Every clip you leave out, put back, export or publish teaches ClipForge AI your taste. Once it has 12 lessons with at
          least 4 kept and 4 left out, each new clip's score moves by up to {taste?.weight ?? 6} points your way, and the clip says why. It stays on this computer.</p>
        {taste && taste.ready && taste.preferences.length > 0 && <p className="small">So far you tend to keep clips with {taste.preferences.join(", ")}.</p>}
        {taste && !taste.ready && <p className="small">{taste.events} lesson{taste.events === 1 ? "" : "s"} so far ({taste.kept} kept, {taste.left_out} left out).
          {taste.needed.events > 0 || taste.needed.kept > 0 || taste.needed.left_out > 0
            ? ` It needs ${Math.max(taste.needed.events, taste.needed.kept + taste.needed.left_out)} more${taste.needed.kept > 0 ? `, ${taste.needed.kept} kept` : ""}${taste.needed.left_out > 0 ? `, ${taste.needed.left_out} left out` : ""}.`
            : ""}</p>}
        {taste && taste.events > 0 && <div className="row wrap">
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setForgetTaste(true)}><Icon name="x" />Forget my choices</button></div>}
      </section>

      <form className="panel tight mem-add" aria-labelledby="mem-teach" onSubmit={(e) => { e.preventDefault();
        void run(() => memoryApi.create({ text: add.text.trim(), kind: add.kind }), () => "Remembered.").then(() => setAdd({ ...add, text: "" })); }}>
        <h3 id="mem-teach">Teach it something</h3>
        <div className="cfai-row">
          <label className="field grow"><span>{add.kind === "rule" ? "A rule it always follows" : "A fact about you or your channel"}</span>
            <input value={add.text} maxLength={600} onChange={(e) => setAdd({ ...add, text: e.target.value })}
              placeholder={add.kind === "rule" ? "For example: never zoom in on faces" : "For example: my videos are about hiking in Colorado"} /></label>
          <label className="field"><span>Kind</span>
            <select value={add.kind} onChange={(e) => setAdd({ ...add, kind: e.target.value as MemoryKind })}><option value="fact">Fact</option><option value="rule">Rule</option></select></label>
          <button type="submit" className="btn btn-primary" disabled={busy || !add.text.trim()}><Icon name="plus" />Remember</button>
        </div>
      </form>

      <div className="cfai-row" role="search">
        <label className="field grow"><span>Search its memory</span><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Words or a question; the closest memories come first" /></label>
        <label className="field"><span>Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All</option>
            {(Object.keys(KIND_WORD) as MemoryKind[]).map((k) => <option key={k} value={k}>{KIND_WORD[k]}</option>)}</select></label>
      </div>
      {rows.length === 0 && <EmptyState icon="spark" title={q ? "Nothing like that in its memory" : "It remembers nothing yet"} level={3}>
        {q ? "Try other words." : "Teach it above, or talk to it on a video or on the Talk tab."}</EmptyState>}
      <div className="mem-list">{rows.map((m) => (
        <article key={m.id} className={`mem-row${m.enabled && !m.expired ? "" : " off"}`}>
          <div className="row wrap">
            <Pill tone={m.kind === "rule" ? "accent" : m.kind === "episode" ? "neutral" : "info"} icon={m.kind === "rule" ? "shield" : m.kind === "episode" ? "clock" : "info"}>{KIND_WORD[m.kind]}</Pill>
            {!m.enabled && <Pill tone="neutral">Off</Pill>}
            {m.expired && <Pill tone="warn">Expired</Pill>}
            {m.source === "guessed" && <Pill tone="warn">Its guess: confirm or forget it</Pill>}
          </div>
          {edit?.id === m.id
            ? <textarea value={edit.text} maxLength={600} aria-label="Memory words" onChange={(e) => setEdit({ id: m.id, text: e.target.value })} />
            : <p className="break">{m.text}</p>}
          <div className="mem-meta">
            <span>{SOURCE_WORD[m.source]}</span><span>{scopeWord(m)}</span>
            <span>Used {m.used_count} time{m.used_count === 1 ? "" : "s"}</span><span>{date(m.created_at)}</span>
            {typeof m.score === "number" && q && <span>Match {Math.round(m.score * 100)}%</span>}
          </div>
          <div className="row-actions wrap" style={{ justifyContent: "flex-start" }}>
            {edit?.id === m.id ? <>
              <button type="button" className="btn btn-small btn-primary" disabled={busy || !edit.text.trim()} onClick={() => void run(() => memoryApi.edit(m.id, { text: edit.text.trim() })).then(() => setEdit(null))}>Save</button>
              <button type="button" className="btn btn-small" onClick={() => setEdit(null)}>Cancel</button>
            </> : <>
              {m.source !== "said" && <button type="button" className="btn btn-small" disabled={busy} onClick={() => void run(() => memoryApi.confirm(m.id), () => "Confirmed: it now counts as something you said.")}><Icon name="check" />Confirm</button>}
              {m.kind !== "episode" && <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEdit({ id: m.id, text: m.text })}><Icon name="edit" />Edit</button>}
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => void run(() => memoryApi.edit(m.id, { enabled: !m.enabled }))}>{m.enabled ? "Turn off" : "Turn on"}</button>
              <button type="button" className="btn btn-small" aria-expanded={!!uses[m.id]} onClick={() => void showUses(m)}>Where it was used</button>
              <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => setDel(m)}><Icon name="trash" />Forget</button>
            </>}
          </div>
          {uses[m.id] && (uses[m.id].length
            ? <ul className="small">{uses[m.id].map((u) => <li key={u.id}>{date(u.created_at)}: {WHERE_WORD[u.where_used] || u.where_used}</li>)}</ul>
            : <p className="small muted">Not used yet.</p>)}
        </article>))}</div>
      <section className="panel tight" aria-labelledby="mem-knowhow">
        <div className="panel-head"><h3 id="mem-knowhow">What it knows about editing (built in)</h3>
          {knowhow && knowhow.topics.length > 0 && <Pill tone="info">{knowhow.topics.length} playbooks</Pill>}</div>
        <p className="small muted">{knowhow?.source || "ClipForge AI's built-in craft know-how."} Every answer, change request, smart edit
          and FilmCraft pass reads the playbooks that fit it; what you teach it above always wins over them.</p>
        {knowhow && knowhow.topics.length === 0 && <p className="small muted">Could not load the know-how.</p>}
        {knowhow && knowhow.topics.length > 0 && <ul className="small knowhow-list">{knowhow.topics.map((t) => (
          <li key={t.id}>
            <button type="button" className="link-btn" aria-expanded={open === t.id} onClick={() => setOpen(open === t.id ? "" : t.id)}>
              <strong>{t.title}</strong>: {t.summary}</button>
            {open === t.id && <ul>{t.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
          </li>))}</ul>}
      </section>
      {forgetTaste && <ConfirmDialog title="Forget what it learned from your choices?" danger confirmLabel="Forget" onClose={() => setForgetTaste(false)}
        onConfirm={async () => { try { setTaste(await api.tasteForget()); toast("Forgotten. It learns again from your next choices."); } catch (e) { toast(errorText(e), true); } setForgetTaste(false); }}>
        <p>Every lesson from clips you left out, put back, exported or published is removed. Clips already scored keep their scores.</p></ConfirmDialog>}
      {del && <ConfirmDialog title={`Forget “${del.text.slice(0, 80)}${del.text.length > 80 ? "…" : ""}”?`} danger confirmLabel="Forget" onClose={() => setDel(null)}
        onConfirm={async () => { await memoryApi.forget(del.id); setDel(null); await load(); }}>
        <p>ClipForge AI will not use it again. Versions it already helped make keep their edits.</p></ConfirmDialog>}
    </div>
  );
}
