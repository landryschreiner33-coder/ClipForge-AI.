import { DragEvent, useEffect, useRef, useState } from "react";
import { Connection, fmtBytes, Snapshot, Style, studio, uploadFile, UploadProgress, Asset } from "../studio";
import { Icon } from "./ui";

export type Picked = { key: string; file: File; progress: UploadProgress | null; asset: Asset | null; error: string };

/** File drop + picker. Each file uploads in resumable chunks; the row shows bytes received, never a guess. */
export function FileDrop({ accept, multiple, label, onAssets }: { accept: string; multiple?: boolean; label: string;
  onAssets: (rows: Picked[]) => void }) {
  const [rows, setRows] = useState<Picked[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const rowsRef = useRef<Picked[]>([]);
  rowsRef.current = rows;

  const update = (key: string, patch: Partial<Picked>) => {
    setRows((rs) => {
      const next = rs.map((r) => (r.key === key ? { ...r, ...patch } : r));
      onAssets(next);
      return next;
    });
  };
  const send = async (row: Picked) => {
    update(row.key, { error: "" });
    try {
      const asset = await uploadFile(row.file, (p) => update(row.key, { progress: p }));
      update(row.key, { asset });
    } catch (e) {
      update(row.key, { error: (e as Error).message });
    }
  };
  const add = (files: FileList | null) => {
    if (!files?.length) return;
    const fresh = Array.from(multiple ? files : [files[0]]).map((file) => ({
      key: `${file.name}|${file.size}|${file.lastModified}`, file, progress: null, asset: null, error: "" }));
    setRows((rs) => {
      const next = multiple ? [...rs, ...fresh.filter((f) => !rs.some((r) => r.key === f.key))] : fresh;
      onAssets(next);
      return next;
    });
    fresh.forEach((r) => void send(r));
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    add(e.dataTransfer.files);
  };
  return (
    <div className="stack-3">
      <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)} onDrop={drop}>
        <Icon name="upload" size={28} />
        <span>{label}</span>
        <button type="button" className="btn" onClick={() => input.current?.click()}>Choose {multiple ? "files" : "a file"}</button>
        <input ref={input} type="file" accept={accept} multiple={multiple} hidden onChange={(e) => add(e.target.files)} />
      </div>
      {rows.length > 0 && !multiple && rows.map((r) => <UploadRow key={r.key} row={r} onRetry={() => void send(r)} />)}
      {multiple && rows.length > 0 && <p className="small muted" aria-live="polite">
        {rows.filter((r) => r.asset).length} of {rows.length} uploaded</p>}
      {multiple && rows.map((r) => r.error && <UploadRow key={r.key} row={r} onRetry={() => void send(r)} />)}
    </div>
  );
}

export function UploadRow({ row, onRetry, extra }: { row: Picked; onRetry: () => void; extra?: React.ReactNode }) {
  const p = row.progress;
  const words = row.error ? row.error : row.asset ? `Uploaded · ${fmtBytes(row.file.size)}${row.asset.duration ? ` · ${Math.round(row.asset.duration)} s` : ""}`
    : !p ? "Waiting" : p.state === "hashing" ? "Preparing the file" : p.state === "checking" ? "Checking the file"
      : `${fmtBytes(p.received)} of ${fmtBytes(p.size)} received`;
  return (
    <div className="file-row" aria-live="polite">
      {row.asset?.has_thumbnail ? <img className="thumb-mini" src={`/api/assets/${row.asset.id}/thumbnail`} alt="" />
        : <span className="thumb-mini" aria-hidden="true" />}
      <div className="break">
        <b className="clamp-1">{row.file.name}</b>
        <span className={`block small ${row.error ? "error-text" : "muted"}`}>{words}</span>
        {p && !row.asset && !row.error && <progress max={p.size} value={p.received} aria-label={`${row.file.name} upload`} />}
      </div>
      <div className="row-actions">{row.error && <button type="button" className="btn btn-small" onClick={onRetry}>Resume upload</button>}{extra}</div>
    </div>
  );
}

/** The exact accounts a project may upload to (names and pictures, never just a platform icon). */
export function DestinationPicker({ value, onChange, platforms = ["youtube", "tiktok"] }: { value: string[];
  onChange: (ids: string[], accounts: Connection[]) => void; platforms?: string[] }) {
  const [rows, setRows] = useState<Connection[] | null>(null);
  useEffect(() => {
    studio.connections().then((r) => setRows(r.connections)).catch(() => setRows([]));
  }, []);
  if (rows === null) return <p className="muted small">Loading accounts…</p>;
  const usable = rows.filter((r) => platforms.includes(r.platform));
  if (!usable.length) return <p className="small">No account connected yet. <a href="#/accounts">Connect YouTube or TikTok</a> to upload from here.</p>;
  return (
    <fieldset className="dest-list">
      <legend className="sr-only">Accounts to upload to</legend>
      {usable.map((r) => {
        const ok = r.health.state === "ok";
        const on = value.includes(r.id);
        return (
          <label key={r.id} className="dest">
            <input type="checkbox" checked={on} disabled={!ok} onChange={() => {
              const next = on ? value.filter((v) => v !== r.id) : [...value, r.id];
              onChange(next, rows.filter((x) => next.includes(x.id)));
            }} />
            {r.avatar ? <img src={r.avatar} alt="" className="avatar" referrerPolicy="no-referrer" onError={(e) => { e.currentTarget.removeAttribute("src"); }} /> : <span className="avatar" aria-hidden="true" />}
            <span>
              <span className="who-name">{r.nickname || r.display_name || r.account_id}</span>{" "}
              <span className="small muted">{r.label}{r.is_default ? " · default" : ""}</span>
              {!ok && <span className="block small error-text">{r.health.text}</span>}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function StyleSelect({ value, onChange, mode }: { value: string; onChange: (v: string) => void; mode: string }) {
  const [styles, setStyles] = useState<Style[]>([]);
  useEffect(() => {
    studio.styles().then(setStyles).catch(() => setStyles([]));
  }, []);
  const usable = styles.filter((s) => !s.modes.length || s.modes.includes(mode));
  return (
    <label className="field">
      <span>Style</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="saved">My saved style{usable.find((s) => s.is_default) ? ` (${usable.find((s) => s.is_default)!.name})` : ""}</option>
        {usable.filter((s) => !s.is_default).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        <option value="settings">Settings defaults</option>
      </select>
    </label>
  );
}

const LEVEL_WORDS: Record<string, string> = { project: "This project", style: "Style", skill: "Skill", brain: "Brain note", settings: "Settings" };

/** "Used from your Brain": each decided choice with the entry (and revision) that decided it, and what it beat. */
export function UsedFromBrain({ snapshot, compact }: { snapshot: Snapshot | null; compact?: boolean }) {
  if (!snapshot) return <p className="muted small">Working out what your style and Brain decide…</p>;
  const shown = snapshot.decisions.filter((d) => d.text && (!compact || d.from.level !== "settings"));
  return (
    <div className="stack-3">
      {snapshot.problems.length > 0 && <p className="error-text small">{snapshot.problems.join(" ")}</p>}
      <ul className="used-list">
        {shown.map((d) => (
          <li key={d.field} className={d.from.level === "settings" ? "settings" : ""}>
            <span>{d.text}</span>
            <span className="src">from {LEVEL_WORDS[d.from.level] || d.from.level}{d.from.name && d.from.level !== "settings" && d.from.level !== "project"
              ? `: ${d.from.name}${d.from.revision ? ` (revision ${d.from.revision})` : ""}` : ""}
              {d.overridden.length > 0 && ` · instead of ${d.overridden.map((o) => `${String(o.value)} from ${o.name}`).join(", ")}`}</span>
          </li>
        ))}
        {snapshot.conflicts.map((c) => (
          <li key={`c-${c.field}`} className="conflict">
            <span>{c.label}: {c.entries.map((e) => `${e.name} says ${String(e.value)}`).join("; ")}</span>
            <span className="src">{c.resolution}</span>
          </li>
        ))}
        {!shown.length && !snapshot.conflicts.length && <li className="settings"><span>Nothing saved applies; Settings decide.</span></li>}
      </ul>
    </div>
  );
}
