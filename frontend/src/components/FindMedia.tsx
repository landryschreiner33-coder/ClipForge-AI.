import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { Banner, Dialog, Disclosure, Icon, Pill, ProgressBar, toast } from "./ui";
import {
  Credit, MediaImport, MediaKind, MediaResult, MediaRules, MediaSearchResult, studio, Suggestions, Video,
} from "../studio";

const KINDS: [MediaKind, string][] = [["image", "Images"], ["footage", "Footage"], ["music", "Music"], ["effect", "Sound effects"]];
const fmtDur = (s: number | null) => s == null ? "" : s < 60 ? `${s.toFixed(s < 10 ? 1 : 0)} s` : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

/** One result: preview, what it is, who made it, its license and whether it fits this project's rules. */
function ResultCard({ r, state, onAdd }: { r: MediaResult; state?: MediaImport; onAdd: (r: MediaResult) => void }) {
  const size = r.width && r.height ? `${r.width}×${r.height}` : "";
  const busy = state && (state.status === "queued" || state.status === "importing");
  const [broken, setBroken] = useState(false);  // a source that no longer serves its preview
  return (
    <li className="media-card">
      <div className="media-preview">
        {r.preview.video ? <video src={r.preview.video} poster={r.preview.image} controls muted preload="none" aria-label={`Preview of ${r.title}`} />
          : r.preview.image && !broken ? <img src={r.preview.image} alt="" loading="lazy" onError={() => setBroken(true)} />
            : <span className="media-noimg" aria-hidden="true"><Icon name="film" /></span>}
        {r.preview.audio && <audio src={r.preview.audio} controls preload="none" aria-label={`Listen to ${r.title}`} />}
      </div>
      <div className="stack-1 break">
        <b className="clamp-2">{r.title || "Untitled"}</b>
        <span className="small muted">{[r.creator && `by ${r.creator}`, r.origin ? `${r.origin} via ${r.provider_name}` : r.provider_name].filter(Boolean).join(" · ")}</span>
        <span className="small">{[size, fmtDur(r.duration_s), r.filetype.toUpperCase()].filter(Boolean).join(" · ")}</span>
        <span className="small">
          {r.license_url ? <a href={r.license_url} target="_blank" rel="noreferrer noopener">{r.license_name}</a> : r.license_name}
          {r.fits.credit_required ? " · credit required" : " · no credit required"}
          {r.page_url && <> · <a href={r.page_url} target="_blank" rel="noreferrer noopener">Source page</a></>}
        </span>
        {r.restrictions && <span className="small muted">Restrictions: {r.restrictions}</span>}
        {r.fits.eligible ? <Pill tone="good">Fits this project's license rules</Pill>
          : <span className="small warn-text"><Icon name="alert" className="sm" /> {r.fits.reasons.join(" ")}</span>}
      </div>
      <div className="row-actions">
        {state?.status === "ready" ? <Pill tone="good" icon="check">In your media</Pill>
          : busy ? <ProgressBar value={state!.progress || 0} label={state!.job_message || "Downloading"} />
            : <button type="button" className="btn btn-small" onClick={() => onAdd(r)}><Icon name="plus" />Add to media</button>}
        {state?.status === "failed" && <span className="small error-text" role="alert">{state.error}</span>}
      </div>
    </li>
  );
}

/** Find media: search the media sources, audition, and add a result to this project's media bin. Adding is not
 * placing: the file waits in Your media until you insert it or put it on a track. */
export function FindMedia({ v, onChanged }: { v: Video; onChanged: () => void }) {
  const [kind, setKind] = useState<MediaKind>("image");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({ license: "fits" });
  const [res, setRes] = useState<MediaSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [imports, setImports] = useState<Record<string, MediaImport>>({});
  const [basisFor, setBasisFor] = useState<MediaResult | null>(null);
  const [basis, setBasis] = useState("");
  const timer = useRef<number>();

  const poll = useCallback(async () => {
    const open = Object.values(imports).filter((i) => i.status === "queued" || i.status === "importing");
    if (!open.length) return;
    const next = await Promise.all(open.map((i) => studio.mediaImport(i.id).catch(() => i)));
    setImports((cur) => ({ ...cur, ...Object.fromEntries(next.map((i) => [i.result_id, i])) }));
    if (next.some((i) => i.status === "ready")) onChanged();
    next.filter((i) => i.status === "failed").forEach((i) => toast(i.error || "Not added", true));
  }, [imports, onChanged]);
  useEffect(() => {
    timer.current = window.setInterval(() => void poll(), 1500);
    return () => window.clearInterval(timer.current);
  }, [poll]);

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      const clean = Object.fromEntries(Object.entries(filters).filter(([, x]) => x));
      setRes(await studio.searchMedia({ kind, query, filters: clean, project_id: v.id }));
    } catch (err) {
      toast(errorText(err), true);
    }
    setBusy(false);
  };
  const add = async (r: MediaResult, why = "") => {
    if (!r.fits.eligible && !why) { setBasisFor(r); setBasis(""); return; }
    try {
      const row = await studio.importMedia({ result_id: r.id, project_id: v.id, basis: why });
      setImports((cur) => ({ ...cur, [r.id]: row }));
      if (row.status === "ready") { toast(row.message || "Added to your media"); onChanged(); }
    } catch (err) {
      toast(errorText(err), true);
    }
  };
  const notices = (res?.providers || []).filter((p) => p.state === "ok" && p.count > 0).map((p) => p.notice);
  const trouble = (res?.providers || []).filter((p) => !["ok", "off"].includes(p.state));
  const durations = kind !== "image";

  return (
    <section className="panel" aria-labelledby="vr-find">
      <div className="panel-head"><h2 id="vr-find">Find media</h2><a className="small" href="#/settings/media">Media sources</a></div>
      <div className="seg" role="tablist" aria-label="What to find">
        {KINDS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={kind === k} className={kind === k ? "on" : ""}
          onClick={() => { setKind(k); setRes(null); }}>{label}</button>)}
      </div>
      <form className="row-actions wrap" onSubmit={search}>
        <label className="field grow"><span>Search {KINDS.find(([k]) => k === kind)![1].toLowerCase()}</span>
          <input value={query} maxLength={100} onChange={(e) => setQuery(e.target.value)}
            placeholder={kind === "effect" ? "For example: rain" : kind === "music" ? "For example: calm acoustic" : "For example: mountain valley"} /></label>
        {kind !== "music" && kind !== "effect" && <label className="field"><span>Shape</span>
          <select value={filters.orientation || ""} onChange={(e) => setFilters({ ...filters, orientation: e.target.value })}>
            <option value="">Any</option><option value="landscape">Landscape</option><option value="portrait">Portrait</option><option value="square">Square</option></select></label>}
        {durations && <label className="field"><span>Length</span>
          <select value={filters.duration || ""} onChange={(e) => setFilters({ ...filters, duration: e.target.value })}>
            <option value="">Any</option><option value="short">Short</option><option value="long">Long</option></select></label>}
        <label className="field"><span>License</span>
          <select value={filters.license || ""} onChange={(e) => setFilters({ ...filters, license: e.target.value })}>
            <option value="fits">Fits this project</option><option value="no_credit">Fits, no credit needed</option><option value="">Show everything</option></select></label>
        <button type="submit" className="btn" disabled={busy || query.trim().length < 2}>{busy ? "Searching…" : "Search"}</button>
      </form>
      {trouble.map((p) => <p key={p.id} className="small warn-text" role="status"><Icon name="alert" className="sm" /> {p.message}</p>)}
      {res && (res.results.length ? (
        <ul className="media-grid" aria-label="Results">
          {res.results.map((r) => <ResultCard key={r.id} r={r} state={imports[r.id]} onAdd={(x) => void add(x)} />)}
        </ul>) : <p className="muted">Nothing found{filters.license ? " that fits this project's license rules" : ""}. Try other words{filters.license ? " or show everything" : ""}.</p>)}
      {notices.length > 0 && <p className="small muted">{notices.join(" ")} A listing that says “free” is not proof of reuse rights: check the source page when in doubt. No source guarantees freedom from Content ID claims.</p>}
      {basisFor && (
        <Dialog title="Use it on your own basis?" onClose={() => setBasisFor(null)}
          actions={<>
            <button type="button" className="btn" onClick={() => setBasisFor(null)}>Choose another result</button>
            <button type="button" className="btn btn-primary" disabled={basis.trim().length < 10}
              onClick={() => { const r = basisFor; setBasisFor(null); void add(r, basis.trim()); }}>Add with my basis</button>
          </>}>
          <p>{basisFor.fits.reasons.join(" ")}</p>
          <label className="field"><span>What gives you the right to use “{basisFor.title}” here?</span>
            <textarea value={basis} maxLength={500} rows={3} onChange={(e) => setBasis(e.target.value)} placeholder="For example: the creator gave me written permission on 2 May" /></label>
          <p className="small muted">Your answer is saved with the file. Videos using it are never posted automatically; they wait for your review.</p>
        </Dialog>
      )}
      <SupportingMedia v={v} onChanged={onChanged} onAdd={(r) => void add(r)} imports={imports} />
    </section>
  );
}

/** "Find supporting media for this project": one project-level choice (suggest or add automatically) and the license
 * rules, instead of a question per clip. */
function SupportingMedia({ v, onChanged, onAdd, imports }: { v: Video; onChanged: () => void; onAdd: (r: MediaResult) => void;
  imports: Record<string, MediaImport> }) {
  const [s, setS] = useState<Suggestions | null>(null);
  const rules: MediaRules = s?.rules || v.media_rules || { mode: "suggest", commercial: true, share_alike: false };
  const load = useCallback(() => studio.supportingMedia(v.id).then(setS).catch(() => undefined), [v.id]);
  useEffect(() => { void load(); }, [load]);
  const running = s?.latest && (s.latest.status === "queued" || s.latest.status === "searching");
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => void load().then(() => onChanged()), 1500);
    return () => window.clearInterval(t);
  }, [running, load, onChanged]);
  const set = async (patch: Partial<MediaRules>) => {
    try { await studio.setMediaRules(v.id, patch); await load(); onChanged(); } catch (e) { toast(errorText(e), true); }
  };
  const latest = s?.latest;
  return (
    <Disclosure summary="Find supporting media for this project" open={!!latest}>
      <div className="stack-3">
        <fieldset className="stack-1"><legend className="label">When media is found</legend>
          <label><input type="radio" name="media-mode" checked={rules.mode === "suggest"} onChange={() => void set({ mode: "suggest" })} /> Suggest it for my review</label>
          <label><input type="radio" name="media-mode" checked={rules.mode === "auto"} onChange={() => void set({ mode: "auto" })} /> Add eligible media automatically (as a new version you can undo)</label>
        </fieldset>
        <fieldset className="stack-1"><legend className="label">License rules for this project</legend>
          <label><input type="checkbox" checked={rules.commercial} onChange={(e) => void set({ commercial: e.target.checked })} /> This video is commercial (monetized, sponsored or promoting a business): no non-commercial licenses</label>
          <label><input type="checkbox" checked={rules.share_alike} onChange={(e) => void set({ share_alike: e.target.checked })} /> Allow share-alike licenses (my video will use the same license)</label>
          <span className="small muted">No-derivatives licenses and unknown terms are never added automatically.</span>
        </fieldset>
        <div className="row-actions">
          <button type="button" className="btn" disabled={!!running || !v.plan}
            onClick={async () => { try { setS(await studio.findSupportingMedia(v.id)); } catch (e) { toast(errorText(e), true); } }}>
            <Icon name="spark" />{running ? "Looking…" : "Find supporting media now"}</button>
          <span className="small muted">Searches a few words you say most often{v.brief?.music === "find" ? " and music for the feel you chose" : ""}; nothing runs in the background.</span>
        </div>
        {latest && <div className="stack-2" aria-live="polite">
          <b>{latest.message}</b>
          {latest.added.length > 0 && <ul className="small">{latest.added.map((a) => <li key={a.asset_id}>Added {a.kind === "image" ? "image" : "music"} “{a.title}” for “{a.query}”</li>)}</ul>}
          {latest.problems.map((p) => <p key={p} className="small warn-text">{p}</p>)}
          {latest.items.map((it) => (
            <div key={`${it.kind}-${it.query}`} className="stack-1">
              <b className="small">{it.kind === "music" ? "Music" : "Images"} for “{it.query}”</b><span className="small muted">{it.why}</span>
              {it.results.length ? <ul className="media-grid compact">{it.results.map((r) => <ResultCard key={r.id} r={r} state={imports[r.id]} onAdd={onAdd} />)}</ul>
                : <span className="small muted">Nothing that fits this project's rules.</span>}
            </div>))}
        </div>}
      </div>
    </Disclosure>
  );
}

/** Credits for media from Media sources that this version uses; editable, with required credits kept complete. */
export function Credits({ v, onSaved }: { v: Video; onSaved: (v: Video) => void }) {
  const [editing, setEditing] = useState<{ key: string; text: string } | null>(null);
  const [err, setErr] = useState("");
  const rows: Credit[] = v.credits || [];
  if (!rows.length) return null;
  const all = "Credits:\n" + rows.map((c) => `- ${c.text}`).join("\n");
  return (
    <section className="panel" aria-labelledby="vr-credits">
      <div className="panel-head"><h2 id="vr-credits">Credits ({rows.length})</h2>
        <div className="row-actions">
          <button type="button" className="btn btn-small" onClick={() => { void navigator.clipboard?.writeText(all); toast("Credits copied for your description"); }}><Icon name="copy" />Copy</button>
          <a className="btn btn-small" href={`/api/studio/videos/${v.id}/credits.txt`}><Icon name="download" />credits.txt</a>
        </div></div>
      <ul className="stack-2">{rows.map((c) => (
        <li key={c.key} className="stack-1">
          {editing?.key === c.key ? (
            <form className="stack-1" onSubmit={async (e) => {
              e.preventDefault();
              try { onSaved(await studio.editCredit(v.id, c.key, editing.text)); setEditing(null); setErr(""); } catch (x) { setErr(errorText(x)); }
            }}>
              <textarea value={editing.text} rows={2} maxLength={600} aria-label={`Credit for ${c.title}`} onChange={(e) => setEditing({ key: c.key, text: e.target.value })} />
              {err && <span className="small error-text" role="alert">{err}</span>}
              <div className="row-actions"><button type="submit" className="btn btn-small">Save</button>
                <button type="button" className="btn btn-small" onClick={() => { setEditing(null); setErr(""); }}>Cancel</button>
                {c.edited && <button type="button" className="btn btn-small" onClick={async () => onSaved(await studio.editCredit(v.id, c.key, ""))}>Use the generated credit</button>}</div>
            </form>
          ) : (
            <span className="break">{c.text} {c.required ? <Pill tone="warn">Required by the license</Pill> : <Pill>Courtesy</Pill>}
              {c.user_basis && <Pill tone="warn">On your stated basis</Pill>}
              {" "}<button type="button" className="link-btn" onClick={() => setEditing({ key: c.key, text: c.text })}>Edit</button></span>
          )}
        </li>))}</ul>
      <p className="small muted">Required credits go in your video's description when you post it. Every render includes this list.</p>
    </section>
  );
}

/** Where an imported file came from (shown in Your media). */
export function SourceLine({ v, assetId }: { v: Video; assetId: string }) {
  const src = v.sources?.[assetId]?.[0];
  if (!src) return null;
  return (
    <span className="block small muted">
      {src.provider_name}{src.origin ? ` (${src.origin})` : ""} · {src.license_url ? <a href={src.license_url} target="_blank" rel="noreferrer noopener">{src.license_name}</a> : src.license_name}
      {src.creator ? ` · ${src.creator}` : ""}{src.user_basis ? " · on your stated basis" : ""}
      {src.page_url && <> · <a href={src.page_url} target="_blank" rel="noreferrer noopener">Source</a></>}
    </span>
  );
}

export function MediaBanner({ v }: { v: Video }) {
  const basis = Object.values(v.sources || {}).flat().filter((s) => s.user_basis);
  if (!basis.length) return null;
  return <Banner tone="warn" title={`${basis.length} file${basis.length === 1 ? "" : "s"} added on your own stated basis`}>Their terms were unknown or did not fit this project. Check the credits before you post.</Banner>;
}
