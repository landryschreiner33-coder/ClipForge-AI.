import { useEffect, useState } from "react";
import { errorText } from "../api";
import { Icon, LoadingPage, Pill, toast, Toggle } from "./ui";
import { MediaProvider, studio } from "../studio";

const KIND_WORDS: Record<string, string> = { image: "images", footage: "footage", music: "music", effect: "sound effects" };
const STATE: Record<string, [string, "good" | "warn" | "bad" | "neutral"]> = {
  ready: ["Ready", "good"], off: ["Off", "neutral"], missing_key: ["Needs a key", "warn"], busy: ["Waiting", "warn"],
};

/** One media source: what it supplies, whether a key is needed and how to get one, its limits, on/off, and a
 * connection test that never shows the key. */
function ProviderCard({ p, onList }: { p: MediaProvider; onList: (rows: MediaProvider[]) => void }) {
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [label, tone] = STATE[p.state] || [p.state, "neutral"];
  const run = async (fn: () => Promise<MediaProvider[]>, done?: string) => {
    setBusy(true);
    try { onList(await fn()); if (done) toast(done); } catch (e) { toast(errorText(e), true); }
    setBusy(false);
  };
  return (
    <section className="panel stack-3" aria-labelledby={`ms-${p.id}`}>
      <div className="panel-head">
        <h2 id={`ms-${p.id}`}>{p.name}</h2>
        <div className="row-actions"><Pill tone={tone}>{label}</Pill>
          <Toggle on={p.enabled} ariaLabel={`Use ${p.name}`} showState disabled={busy} onChange={(on) => void run(() => studio.setMediaProvider(p.id, { enabled: on }), on ? `${p.name} is on` : `${p.name} is off`)} /></div>
      </div>
      <p>{p.supplies}</p>
      <p className="small">Supplies {p.kinds.map((k) => KIND_WORDS[k]).join(", ")}. {p.limits}</p>
      {p.key_required ? (
        <div className="stack-2">
          <p className="small"><b>A key is required.</b> {p.key_help}</p>
          {p.key_saved && !replacing ? (
            <div className="row wrap"><input type="text" readOnly value="•••••••• (saved)" aria-label={`${p.name} API key`} style={{ maxWidth: 260 }} />
              <button type="button" className="btn btn-small" onClick={() => setReplacing(true)}>Replace…</button>
              <button type="button" className="btn btn-small btn-quiet" disabled={busy} onClick={() => void run(() => studio.setMediaProvider(p.id, { key: "" }), "Key removed")}>Remove</button></div>
          ) : (
            <form className="row wrap" onSubmit={(e) => { e.preventDefault(); void run(() => studio.setMediaProvider(p.id, { key }), "Key saved").then(() => { setKey(""); setReplacing(false); setTest(null); }); }}>
              <input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} aria-label={`${p.name} API key`} placeholder="Paste the API key" style={{ maxWidth: 320 }} />
              <button type="submit" className="btn btn-small" disabled={busy || !key.trim()}>Save key</button>
              {replacing && <button type="button" className="btn btn-small" onClick={() => setReplacing(false)}>Cancel</button>}
            </form>
          )}
        </div>
      ) : <p className="small"><b>No key needed.</b></p>}
      {p.message && p.state !== "ready" && <p className="small muted">{p.message}</p>}
      <div className="row wrap">
        <button type="button" className="btn btn-small" disabled={busy || !p.enabled || (p.key_required && !p.key_saved)}
          onClick={async () => { setBusy(true); try { setTest(await studio.testMediaProvider(p.id)); } catch (e) { setTest({ ok: false, message: errorText(e) }); } setBusy(false); }}>
          Test connection</button>
        {test && <span className={`small ${test.ok ? "" : "error-text"}`} role="status"><Icon name={test.ok ? "check" : "alert"} className="sm" /> {test.message}</span>}
      </div>
      <p className="small"><a href={p.terms_url} target="_blank" rel="noreferrer noopener">Terms and licenses</a> · <a href={p.docs_url} target="_blank" rel="noreferrer noopener">API documentation</a></p>
    </section>
  );
}

/** Settings → Media sources: where Find media searches. Separate from social connections and from the retired
 * source-discovery keys. Nothing here searches in the background. */
export default function MediaSourcesSettings() {
  const [rows, setRows] = useState<MediaProvider[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { studio.mediaProviders().then(setRows).catch((e) => setErr(errorText(e))); }, []);
  if (!rows) return err ? <p className="error-text" role="alert">{err}</p> : <LoadingPage label="Loading media sources" />;
  return (
    <div className="stack-4">
      <p className="muted">Find media in the video editor searches these sources when you search, or when you ask for supporting media for one project. Files you add are copied into your media with their source, creator and license, so finished projects keep working if a source is switched off or removes an item.</p>
      {rows.map((p) => <ProviderCard key={p.id} p={p} onList={setRows} />)}
      <p className="small muted">Licenses are reported by each source and are not verified by ClipForge. Keys are stored encrypted and never shown again after saving. No source here guarantees freedom from Content ID claims.</p>
    </div>
  );
}
