import { DragEvent, useEffect, useRef, useState } from "react";
import { Connection, ExampleVideo, fmtBytes, Snapshot, Style, studio, uploadFile, UploadProgress, Asset } from "../studio";
import { Icon } from "./ui";

export type Picked = { key: string; file: File; progress: UploadProgress | null; asset: Asset | null; error: string;
  /** Resume this file's upload where the server says it stopped. */
  retry?: () => void;
  /** Stop this file's upload (or take it out of the waiting line); it can be resumed later. */
  cancel?: () => void };

/** Uploads that run at the same time; the rest wait their turn (each one reads its file in chunks). */
const PARALLEL = 3;

/** File drop + picker. Any number of files, in as many batches as you like: each uploads in resumable chunks, a few
 * at a time, and each row shows bytes received (never a guess), with cancel and resume. */
export function FileDrop({ accept, multiple, label, onAssets }: { accept: string; multiple?: boolean; label: string;
  onAssets: (rows: Picked[]) => void }) {
  const [rows, setRows] = useState<Picked[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const files = useRef(new Map<string, File>());
  const waiting = useRef<string[]>([]);
  const running = useRef(new Map<string, AbortController>());

  const update = (key: string, patch: Partial<Picked>) => {
    setRows((rs) => {
      const next = rs.map((r) => (r.key === key ? { ...r, ...patch } : r));
      onAssets(next);
      return next;
    });
  };
  const pump = () => {
    while (running.current.size < PARALLEL && waiting.current.length) {
      const key = waiting.current.shift()!;
      const file = files.current.get(key);
      if (!file || running.current.has(key)) continue;
      const ctl = new AbortController();
      running.current.set(key, ctl);
      update(key, { error: "" });
      uploadFile(file, (p) => update(key, { progress: p }), ctl.signal)
        .then((asset) => update(key, { asset }))
        .catch((e) => update(key, { error: ctl.signal.aborted ? "Stopped. Resume upload to continue where it left off."
          : (e as Error).message }))
        .finally(() => { running.current.delete(key); pump(); });
    }
  };
  const start = (key: string) => {
    if (!waiting.current.includes(key) && !running.current.has(key)) waiting.current.push(key);
    update(key, { error: "" });
    pump();
  };
  const stop = (key: string) => {
    waiting.current = waiting.current.filter((k) => k !== key);
    const ctl = running.current.get(key);
    if (ctl) ctl.abort();
    else update(key, { error: "Not started. Resume upload when you want it." });
  };
  const add = (list: FileList | null) => {
    if (!list?.length) return;
    const fresh: Picked[] = Array.from(multiple ? list : [list[0]]).map((file) => {
      const key = `${file.name}|${file.size}|${file.lastModified}`;
      return { key, file, progress: null, asset: null, error: "", retry: () => start(key), cancel: () => stop(key) };
    });
    fresh.forEach((r) => files.current.set(r.key, r.file));
    setRows((rs) => {
      const next = multiple ? [...rs, ...fresh.filter((f) => !rs.some((r) => r.key === f.key))] : fresh;
      onAssets(next);
      return next;
    });
    fresh.forEach((r) => start(r.key));
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    add(e.dataTransfer.files);
  };
  useEffect(() => () => running.current.forEach((c) => c.abort()), []);
  const done = rows.filter((r) => r.asset).length;
  return (
    <div className="stack-3">
      <div className={`drop ${over ? "over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)} onDrop={drop}>
        <Icon name="upload" size={28} />
        <span>{label}</span>
        <button type="button" className="btn" onClick={() => input.current?.click()}>Choose {multiple ? "files" : "a file"}</button>
        <input ref={input} type="file" accept={accept} multiple={multiple} hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>
      {rows.length > 0 && !multiple && rows.map((r) => <UploadRow key={r.key} row={r} onRetry={() => start(r.key)} />)}
      {multiple && rows.length > 0 && <p className="small muted" aria-live="polite">
        {done} of {rows.length} uploaded{rows.length - done > PARALLEL ? ` · ${PARALLEL} at a time, the rest wait their turn` : ""}</p>}
      {multiple && rows.map((r) => r.error && <UploadRow key={r.key} row={r} onRetry={() => start(r.key)} />)}
    </div>
  );
}

export function UploadRow({ row, onRetry, extra }: { row: Picked; onRetry?: () => void; extra?: React.ReactNode }) {
  const p = row.progress;
  const retry = onRetry || row.retry;
  const sending = !row.asset && !row.error && p && p.state !== "done";
  const words = row.error ? row.error : row.asset ? `Uploaded · ${fmtBytes(row.file.size)}${row.asset.duration ? ` · ${Math.round(row.asset.duration)} s` : ""}`
    : !p ? "Waiting its turn" : p.state === "hashing" ? "Preparing the file" : p.state === "checking" ? "Checking the file"
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
      <div className="row-actions">
        {row.error && retry && <button type="button" className="btn btn-small" onClick={retry}>Resume upload</button>}
        {!row.asset && !row.error && row.cancel && <button type="button" className="btn btn-small"
          aria-label={`Stop uploading ${row.file.name}`} onClick={row.cancel}>{sending ? "Stop" : "Skip"}</button>}
        {extra}
      </div>
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

const LEVEL_WORDS: Record<string, string> = { project: "This project", reference: "Example chosen for this project",
  style: "Style", skill: "Skill", example: "Example video", brain: "Brain note", settings: "Settings" };

/** "Use an example": an analyzed example video whose saved choices this project should follow. */
export function ExampleSelect({ value, onChange, mode }: { value: string; onChange: (v: string) => void; mode: string }) {
  const [rows, setRows] = useState<ExampleVideo[] | null>(null);
  useEffect(() => {
    studio.examples(true).then(setRows).catch(() => setRows([]));
  }, []);
  const usable = (rows || []).filter((r) => r.style && r.enabled && !r.avoid && r.status !== "queued");
  const chosen = usable.find((r) => r.id === value);
  const fields = chosen?.style ? Object.keys(chosen.style.values) : [];
  return (
    <div className="stack-2">
      <label className="field">
        <span>Use an example</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} disabled={rows === null}>
          <option value="">No example</option>
          {usable.map((r) => <option key={r.id} value={r.id}>{r.title}{r.project_only ? " (this project only)" : ""}</option>)}
        </select>
      </label>
      {chosen && <p className="small muted">Follows {fields.length} saved choice{fields.length === 1 ? "" : "s"} learned from “{chosen.title}”
        {mode === "full_video" ? "" : " that apply to clips"}. Choices you make below still win. The example's own footage and sound are never used.</p>}
      {rows !== null && !usable.length && <p className="small muted">No example videos yet. <a className="textlink" href="#/brain/example-videos">Add one in Brain</a>: ClipForge measures its cuts, captions, framing and sound, and you choose what to reuse.</p>}
    </div>
  );
}

/** "Used from your Brain": each decided choice with the entry (and revision) that decided it, and what it beat. */
export function UsedFromBrain({ snapshot, compact }: { snapshot: Snapshot | null; compact?: boolean }) {
  if (!snapshot) return <p className="muted small">Working out what your style and Brain decide…</p>;
  // a video made before ClipForge recorded its guidance has an empty record
  if (!Array.isArray(snapshot.decisions)) return <p className="muted small">This video was made before ClipForge recorded which saved choices decided it.</p>;
  const shown = snapshot.decisions.filter((d) => d.text && (!compact || d.from.level !== "settings"));
  return (
    <div className="stack-3">
      {!!snapshot.problems?.length && <p className="error-text small">{snapshot.problems.join(" ")}</p>}
      <ul className="used-list">
        {shown.map((d) => (
          <li key={d.field} className={d.from.level === "settings" ? "settings" : ""}>
            <span>{d.text}</span>
            <span className="src">from {d.from.level === "reference" || d.from.level === "example"
              ? `${d.from.name}${d.from.level === "reference" ? ", chosen for this project" : ""}${d.from.revision ? ` (style revision ${d.from.revision})` : ""}`
              : <>{LEVEL_WORDS[d.from.level] || d.from.level}{d.from.name && d.from.level !== "settings" && d.from.level !== "project"
                ? `: ${d.from.name}${d.from.revision ? ` (revision ${d.from.revision})` : ""}` : ""}</>}
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
