import { useEffect, useId, useState } from "react";
import { api, errorText, PlatformAccount, Settings } from "../api";
import { Disclosure, Icon, toast } from "./ui";
import "./TikTokSetup.css";

type Mode = "inbox" | "direct" | "both";
interface Draft {
  website: string; terms: string; privacy: string; completed: string[]; mode: Mode; read_stats: boolean;
}
interface Packet {
  name: string; category: string; description: string; platform: string; redirect_uri: string;
  mode: Mode; read_stats: boolean; preferences: Settings; products: string[]; scopes: string[];
  scope_notes: Record<string, string>; urls: Record<string, string>; url_errors: Record<string, string>;
  url_check: string; review_explanation: string; completed_count: number; portal_status: string;
  checklist: { id: string; label: string; completed: boolean }[]; limits: string[];
  sources: Record<string, string>; demo_steps: string[]; icon: { dark_url: string; light_url: string };
}
// Settings remounts its account cards after saving. Keep the user's non-secret draft in this tab through that
// remount, without persisting it to the app database or browser storage. Reloading or closing clears it.
let tabDraft: Draft | null = null;

async function buildDraft(draft: Draft, signal?: AbortSignal): Promise<Packet> {
  const response = await fetch("/api/publish/tiktok/setup", { method: "POST", signal,
    headers: { "Content-Type": "application/json", "X-ClipFoundry": "1" }, body: JSON.stringify(draft) });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "The form could not be prepared.");
  return body;
}

function CopyField({ label, value, multiline = false }: { label: string; value: string; multiline?: boolean }) {
  const id = useId();
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); toast(`${label} copied`); }
    catch { toast("Select the text and copy it; your browser did not allow copying.", true); }
  };
  return <div className="field tk-copy-field">
    <div className="row tk-field-head"><label htmlFor={id}>{label}</label>
      <button type="button" className="btn btn-small" onClick={copy} aria-label={`Copy ${label}`}>
        <Icon name="copy" />Copy
      </button>
    </div>
    {multiline ? <textarea id={id} readOnly value={value} rows={4} /> : <input id={id} readOnly value={value} />}
  </div>;
}

/** The helper writes a truthful local draft. Checking a step cannot change platform approval or upload permissions. */
export function TikTokSetup({ account, preferences, onPreferences }: {
  account?: PlatformAccount; preferences?: Settings; onPreferences?: (patch: Settings) => void;
}) {
  const uid = useId();
  const [draft, setDraft] = useState<Draft>(() => {
    if (tabDraft) return tabDraft;
    const direct = !!account?.configured && preferences?.tiktok_direct_post !== false;
    const inbox = preferences?.tiktok_inbox_upload !== false;
    return { website: "", terms: "", privacy: "", completed: [], mode: direct ? (inbox ? "both" : "direct") : "inbox",
      read_stats: !!account?.configured && !!preferences?.tiktok_read_stats };
  });
  const [packet, setPacket] = useState<Packet | null>(null);
  const [opened, setOpened] = useState(false);
  const [error, setError] = useState("");
  const [updating, setUpdating] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const invalidUrls = !!packet && (["website", "terms", "privacy"] as const)
    .some(key => !!draft[key].trim() && !!packet.url_errors[key]);
  useEffect(() => {
    tabDraft = draft;
    // Opening Settings is read-only. Prepare a form only after the owner opens this helper.
    if (!opened) return;
    const abort = new AbortController();
    setUpdating(true);
    const timer = setTimeout(() => {
      buildDraft(draft, abort.signal).then(p => { setPacket(p); setError(""); })
        .catch(e => { if (!abort.signal.aborted) setError(errorText(e)); })
        .finally(() => { if (!abort.signal.aborted) setUpdating(false); });
    }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [draft, opened]);
  const change = (patch: Partial<Draft>) => setDraft(d => ({ ...d, ...patch }));
  const download = async () => {
    setDownloading(true);
    try {
      const response = await fetch("/api/publish/tiktok/setup/export", { method: "POST",
        headers: { "Content-Type": "application/json", "X-ClipFoundry": "1" }, body: JSON.stringify(draft) });
      if (!response.ok) {
        const result = await response.json();
        throw new Error(typeof result.detail === "string" ? result.detail : "The form pack could not be downloaded.");
      }
      const url = URL.createObjectURL(await response.blob()), a = document.createElement("a");
      a.href = url; a.download = "ClipFoundry-TikTok-form.zip"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast("Form pack downloaded. Review it before using TikTok's portal.");
    } catch (e) { toast(errorText(e), true); }
    finally { setDownloading(false); }
  };
  const apply = async () => {
    if (!packet || updating) return;
    if (onPreferences) {
      onPreferences(packet.preferences);
      toast("Permission choices added to Settings. Save them before connecting.");
    } else {
      try { await api.saveSettings(packet.preferences); toast("Permissions saved. Connect TikTok with these scopes."); }
      catch (e) { toast(errorText(e), true); }
    }
  };
  return <details className="plain" onToggle={event => setOpened(event.currentTarget.open)}>
    <summary><Icon name="chev" className="chev sm" />Help me fill out the TikTok app form</summary>
    <div className="more-body">
    <div className="tk-setup stack-3" data-testid="tiktok-form-helper">
      <div className="tk-setup-intro">
        <span className="eyebrow">YOUR APP · YOUR ACCOUNT</span>
        <h3>A clear starting point for TikTok setup</h3>
        <p>Copy the fields below into TikTok's developer portal. Start with a Sandbox for your own test account.</p>
        <a className="btn btn-small" href="https://developers.tiktok.com/apps/" target="_blank" rel="noreferrer">
          <Icon name="external" />Open TikTok developer portal
        </a>
      </div>
      <div className="tk-eligibility" role="note">
        <Icon name="alert" /><div><b>Approval is TikTok's decision.</b>
          <p>TikTok's production rules reject personal or private utility tools. ClipFoundry is a personal desktop
            app, so this form cannot guarantee a connection or Public posting. You can always export clips and
            post them yourself.</p>
        </div>
      </div>
      <fieldset className="tk-mode-picker">
        <legend>1. Choose what your connection should do</legend>
        {([ ["inbox", "Send to my TikTok inbox", "Fewest posting permissions. Finish the post in TikTok."],
          ["direct", "Direct Post only", "Needs an eligible app. Approve each post in ClipFoundry."],
          ["both", "Direct Post and inbox", "Request both only if you will demonstrate and use both."] ] as const)
          .map(([mode, title, detail]) => <label key={mode} className={draft.mode === mode ? "selected" : ""}>
            <input type="radio" name={`${uid}-mode`} checked={draft.mode === mode}
              onChange={() => change({ mode })} /><span><b>{title}</b><small>{detail}</small></span>
          </label>)}
        <label className="tk-stats-choice"><input type="checkbox" checked={draft.read_stats}
          onChange={e => change({ read_stats: e.target.checked })} />
          Also read my posted-video statistics <span className="hint">optional; adds Display API</span>
        </label>
      </fieldset>
      {error && <p role="alert" className="form-error">{error}</p>}
      {!packet && !error && <p role="status" className="small muted">Preparing your form fields…</p>}
      {packet && <>
        <div className="tk-scope-card" aria-live="polite">
          <span className="small strong">Add these products: {packet.products.join(" · ")}</span>
          <code className="break">{packet.scopes.join(", ")}</code>
          <button type="button" className="btn btn-small" disabled={updating} onClick={apply}>
            Use these permissions in ClipFoundry
          </button>
          <p className="tiny muted">These are form choices. Save them and reconnect to request them; a previous
            TikTok connection keeps its existing granted permissions until you reconnect.</p>
        </div>
        <h4>2. Copy the app details</h4>
        <div className="tk-form-grid">
          <CopyField label="App name" value={packet.name} />
          <CopyField label="Platform" value={packet.platform} />
        </div>
        <p className="small muted">Category: {packet.category}</p>
        <CopyField label="Description" value={packet.description} multiline />
        <CopyField label="Login Kit Desktop redirect address" value={packet.redirect_uri} />
        <p className="tiny muted">This HTTP address is correct for Desktop sign-in on this computer. It includes
          your current port. Register it exactly in Login Kit Desktop; it is separate from the public website.</p>
        <div className="tk-icons">
          <img src={packet.icon.dark_url} alt="ClipFoundry robot app icon on a dark background" />
          <div><span className="small strong">Your app icon · 1024 × 1024 PNG</span>
            <div className="row wrap">
              <a className="btn btn-small" href={packet.icon.dark_url} download>Download dark</a>
              <a className="btn btn-small" href={packet.icon.light_url} download>Download light</a></div>
            <p className="tiny muted">Use the ClipFoundry name and icon consistently. Both files are below 5 MB.</p>
          </div>
        </div>
        <Disclosure plain summary="Public website, Terms and Privacy fields">
          <div className="stack-3">
            <p className="small">TikTok asks Desktop apps for a real public website with visible active policy
              links and verified URL ownership. Local previews and GitHub source links are not a published site.
              The download includes draft pages you can review before publishing.</p>
            {([ ["website", "Website URL"], ["terms", "Terms of Service URL"],
              ["privacy", "Privacy Policy URL"] ] as const).map(([key, label]) => <div className="field" key={key}>
              <label htmlFor={`${uid}-${key}`}>{label}</label>
              <input id={`${uid}-${key}`} type="url" value={draft[key]} placeholder="Your published HTTPS page"
                aria-describedby={`${uid}-${key}-hint`} onChange={e => change({ [key]: e.target.value })} />
              <span id={`${uid}-${key}-hint`} className="tiny muted">
                {packet.url_errors[key] || "Format looks right. Website availability and ownership are unverified."}
              </span>
            </div>)}
            <div className="row wrap small"><a href="/legal/" target="_blank" rel="noreferrer">Preview local website</a>
              <a href="/legal/terms.html" target="_blank" rel="noreferrer">Preview local Terms</a>
              <a href="/legal/privacy.html" target="_blank" rel="noreferrer">Preview local Privacy</a></div>
            <p className="tiny muted">These fields stay in this app tab until reload or close, and in your download.
              The helper
              does not fetch, deploy or verify the addresses, and it never uploads your form to TikTok.</p>
          </div>
        </Disclosure>
        <Disclosure plain summary="Review explanation and demo recording guide">
          <div className="stack-3"><CopyField label="Product and permission explanation"
            value={packet.review_explanation} multiline />
            <ol className="tk-demo-list">{packet.demo_steps.map(s => <li key={s}>{s}</li>)}</ol>
            <p className="small muted">Record a real integration with your own account; this app cannot create or
              certify the demo for you.</p>
          </div>
        </Disclosure>
        <Disclosure plain summary={`3. My setup checklist (${packet.completed_count}/${packet.checklist.length})`}>
          <div className="stack-3">
            <p className="small muted">For your reference only. Checking a step never marks the app approved or
              audited, and never connects your account.</p>
            {packet.checklist.map(row => <label key={row.id} className="tk-check-row">
              <input type="checkbox" checked={draft.completed.includes(row.id)} onChange={e => change({
                completed: e.target.checked ? [...draft.completed, row.id] : draft.completed.filter(x => x !== row.id),
              })} /><span>{row.label}</span>
            </label>)}
            <p className="tiny muted">Connection: {account?.connected ? "Connected to TikTok" : "Not connected"}.
              {" "}{packet.portal_status}</p>
          </div>
        </Disclosure>
        <div className="tk-export-row">
          <button type="button" className="btn" disabled={downloading || updating || invalidUrls} onClick={download}>
            <Icon name="zip" />{downloading ? "Preparing download…" : "Download TikTok form pack"}
          </button>
          <span className="tiny muted">Form text, icons and draft website pages.
            App codes and tokens are excluded.</span>
        </div>
        {invalidUrls && <p className="tiny muted">Fix the entered public website addresses before downloading.
          Leave them blank if your pages are not published yet.</p>}
        <Disclosure plain summary="TikTok limits and official guides">
          <ul className="small tk-limit-list">{packet.limits.map(s => <li key={s}>{s}</li>)}</ul>
          <div className="row wrap small">{Object.entries(packet.sources).map(([name, url]) =>
            <a key={name} href={url} target="_blank" rel="noreferrer">{name}<Icon name="external" size={12} /></a>)}
          </div>
        </Disclosure>
      </>}
    </div>
    </div>
  </details>;
}
