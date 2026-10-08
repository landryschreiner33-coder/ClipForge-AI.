import { ReactNode, useEffect, useId, useState } from "react";
import { api, errorText, Settings } from "../api";
import { Banner, ConfirmDialog, Icon, Pill, Segmented, Toggle, Tone, toast } from "../components/ui";
import { AudienceView, IntegrationCard, NvidiaStatus, office } from "./officeApi";

/**
 * Settings → Integrations: one honest card per connection (state, account, what it can do, what is missing, the next
 * step), the optional NVIDIA AI settings, and who may see uploaded clips. Nothing here uploads or calls a paid API
 * by itself: the NVIDIA test runs only when you press its button.
 */
const STATE_TONE: Record<string, [Tone, "check" | "alert" | "x" | "info" | "clock"]> = {
  Connected: ["good", "check"], "Not connected": ["neutral", "info"], "Permission required": ["warn", "alert"],
  "Rate limited": ["warn", "clock"], Error: ["bad", "x"], Unsupported: ["neutral", "x"],
  "Requires user action": ["warn", "alert"],
};
const MASK = "********";

export function IntegrationsTab() {
  const [cards, setCards] = useState<IntegrationCard[] | null>(null);
  const [error, setError] = useState("");
  const load = () => office.integrations().then((r) => { setCards(r.cards); setError(""); })
    .catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  return (
    <div className="stack-4">
      {error && <Banner tone="bad" title="Integrations could not be loaded">{error}</Banner>}
      {!cards && !error && <p className="muted">Loading integrations…</p>}
      {cards?.map((c) => (
        <IntegrationPanel key={c.id} card={c}>
          {c.id === "nvidia" && <NvidiaSettings status={c.detail} onChanged={load} />}
          {(c.id === "youtube" || c.id === "tiktok") && (
            <p className="small"><a className="textlink" href="#/settings">Connect or reconnect in Settings →
              Accounts</a></p>
          )}
        </IntegrationPanel>
      ))}
      <AudienceSettings onSaved={load} />
    </div>
  );
}

function IntegrationPanel({ card, children }: { card: IntegrationCard; children?: ReactNode }) {
  const [tone, icon] = STATE_TONE[card.state] || ["neutral", "info"];
  const id = useId();
  return (
    <section className="panel integration" aria-labelledby={id}>
      <div className="row wrap">
        <h2 id={id} className="grow" style={{ fontSize: "var(--fs-h3)" }}>{card.name}</h2>
        <Pill tone={tone} icon={icon}>{card.state}</Pill>
      </div>
      <dl className="kv">
        <dt>Account or model</dt><dd>{card.identity || "—"}</dd>
        <dt>Can do</dt><dd>{card.capabilities.length ? card.capabilities.join(" · ") : "—"}</dd>
        {card.missing.length > 0 && <><dt>Missing</dt><dd>{card.missing.join(" · ")}</dd></>}
        <dt>Next step</dt><dd>{card.next || "Nothing to do."}</dd>
        {card.audience && <><dt>Clips go to</dt><dd>{card.audience.intent === "LOCAL_ONLY" ? "Nobody: kept on this PC"
          : card.audience.intent === "OWNER_ONLY" ? "Only you (private staging)"
            : "Your selected audience"}{card.audience.route === "manual" ? " (you post it yourself)" : ""}</dd></>}
      </dl>
      {children}
    </section>
  );
}

// ------------------------------------------------------------------ NVIDIA AI (optional)
const NV_KEYS = ["nvidia_enabled", "nvidia_cloud_optin", "nvidia_model", "nvidia_mode", "nvidia_production_url",
  "nvidia_production_terms_confirmed", "nvidia_price_input_per_mtok", "nvidia_price_output_per_mtok",
  "nvidia_spend_cap_usd", "nvidia_daily_requests", "nvidia_daily_tokens", "nvidia_terms_checked"];

function NvidiaSettings({ status, onChanged }: { status?: NvidiaStatus; onChanged: () => void }) {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [key, setKey] = useState(""); // write-only: never filled from the server
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [testResult, setTestResult] = useState("");
  const id = useId();
  const load = () => api.settings().then((s) => {
    const pick = Object.fromEntries(NV_KEYS.map((k) => [k, s[k]]));
    setSaved(pick);
    setDraft(pick);
  }).catch((e) => setError(errorText(e)));
  useEffect(() => {
    load();
  }, []);
  if (!draft || !saved) return <p className="small muted">{error || "Loading NVIDIA settings…"}</p>;
  const set = (patch: Settings) => setDraft((d) => d && { ...d, ...patch });
  const changed = NV_KEYS.filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(saved[k]));
  const dirty = changed.length > 0 || key.trim() !== "";
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const patch: Settings = Object.fromEntries(changed.map((k) => [k, draft[k]]));
      if (key.trim()) patch.nvidia_api_key = key.trim();
      await api.saveSettings(patch);
      setKey("");
      toast("NVIDIA settings saved");
      await load();
      onChanged();
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };
  const field = (k: string, label: string, hint: string, input: ReactNode) => (
    <div className="field" key={k}>
      <label htmlFor={`${id}-${k}`}>{label}{hint && <span className="hint"> {hint}</span>}</label>
      {input}
    </div>
  );
  const text = (k: string, type = "text", extra: Record<string, unknown> = {}) => (
    <input id={`${id}-${k}`} type={type} value={draft[k] ?? ""} onChange={(e) => set({
      [k]: type === "number" && !k.startsWith("nvidia_price") ? (e.target.value === "" ? "" : Number(e.target.value))
        : e.target.value,
    })} {...extra} />
  );
  const production = draft.nvidia_mode === "production";
  return (
    <div className="stack-3 nvidia-settings">
      <p className="small muted">Optional. ClipFoundry works fully without it: local analysis is always the fallback.
        Off by default, and nothing is sent until you turn it on and opt in below.</p>
      <Toggle on={!!draft.nvidia_enabled} onChange={(v) => set({ nvidia_enabled: v })} label="Use NVIDIA AI"
        showState />
      <label className="choice">
        <input type="checkbox" checked={!!draft.nvidia_cloud_optin}
          onChange={(e) => set({ nvidia_cloud_optin: e.target.checked })} />
        <span className="small">Send approved text to NVIDIA's cloud. {status?.sharing || "When on, short transcript "
          + "excerpts, titles and descriptions of approved clips are sent to NVIDIA. Never sent: keys, account tokens, "
          + "media files or links, viewer names or emails."}</span>
      </label>
      {field("nvidia_api_key", "API key", status?.key_saved ? `(saved${status.key_hint ? ` ${status.key_hint}` : ""}${
        status.key_source === "environment" ? ", from the backend's environment" : ""}; type a new one to replace it)`
        : "(not saved)", (
        <input id={`${id}-nvidia_api_key`} type="password" autoComplete="off" value={key}
          placeholder={status?.key_saved ? MASK : ""} onChange={(e) => setKey(e.target.value)} />
      ))}
      {field("nvidia_model", "Model", "", text("nvidia_model"))}
      <div className="field">
        <span className="label" id={`${id}-mode`}>Mode</span>
        <Segmented<string> labelledBy={`${id}-mode`} value={String(draft.nvidia_mode || "experimental")}
          onChange={(v) => set({ nvidia_mode: v })} options={[
            { value: "experimental", label: "Experimental / development" },
            { value: "production", label: "Production" },
          ]} />
        <span className="tiny muted">{production ? "Production uses an endpoint you configured whose terms allow it, "
          + "with a known price and a spending cap." : "Experimental access is for trying it out; unattended Autopilot "
          + "work does not use it."}</span>
      </div>
      {production && (
        <>
          {field("nvidia_production_url", "Production endpoint", "(https)", text("nvidia_production_url", "url"))}
          <label className="choice">
            <input type="checkbox" checked={!!draft.nvidia_production_terms_confirmed}
              onChange={(e) => set({ nvidia_production_terms_confirmed: e.target.checked })} />
            <span className="small">I checked that this endpoint's terms allow this production use.</span>
          </label>
        </>
      )}
      <div className="fb-grid">
        {field("nvidia_daily_requests", "Requests per day", "", text("nvidia_daily_requests", "number", { min: 0 }))}
        {field("nvidia_daily_tokens", "Tokens per day", "", text("nvidia_daily_tokens", "number", { min: 0 }))}
        {field("nvidia_price_input_per_mtok", "Input price", "$ per million tokens; empty = unknown",
          text("nvidia_price_input_per_mtok", "number", { min: 0, step: "0.01" }))}
        {field("nvidia_price_output_per_mtok", "Output price", "$ per million tokens; empty = unknown",
          text("nvidia_price_output_per_mtok", "number", { min: 0, step: "0.01" }))}
        {field("nvidia_spend_cap_usd", "Spending cap", "$ per day", text("nvidia_spend_cap_usd", "number",
          { min: 0, step: "0.01" }))}
      </div>
      {field("nvidia_terms_checked", "What you checked about the terms", "(your note, with the date)",
        text("nvidia_terms_checked"))}
      {status && (
        <p className="tiny muted">Authentication: {status.authentication || "no key yet"} · Today:{" "}
          {Object.entries(status.usage_today || {}).map(([k, v]) => `${k} ${v ?? "—"}`).join(", ") || "—"}</p>
      )}
      {error && <p className="small bad-text" role="alert">{error}</p>}
      <div className="row wrap">
        <button type="button" className="btn btn-primary btn-small" disabled={!dirty || busy} onClick={save}>
          {busy && <span className="inline-spinner" aria-hidden="true" />}Save NVIDIA settings</button>
        <button type="button" className="btn btn-small" disabled={dirty || busy || !status?.key_saved}
          onClick={() => setTesting(true)}><Icon name="spark" />Run small AI test…</button>
        <button type="button" className="btn btn-small btn-quiet" disabled={busy || !status?.key_saved}
          onClick={() => setDisconnecting(true)}>Disconnect…</button>
      </div>
      {dirty && <p className="tiny muted">Save first to run the test with these settings.</p>}
      {testResult && <p className="small" role="status">{testResult}</p>}
      {testing && (
        <ConfirmDialog title="Run a small AI test?" confirmLabel="Run the test" onClose={() => setTesting(false)}
          onConfirm={async () => {
            try {
              const r = await office.nvidiaTest();
              setTestResult(`The test worked: ${r.model || "the model"} answered “${r.answer || ""}”.`);
            } catch (e) {
              setTestResult(`The test did not work: ${errorText(e)}`);
            }
            onChanged();
          }}>
          <p className="muted">This sends one tiny made-up message (no clip text) to NVIDIA. It uses a little of
            today's request and token budget, and costs money if your endpoint is paid.</p>
        </ConfirmDialog>
      )}
      {disconnecting && (
        <ConfirmDialog title="Disconnect NVIDIA AI?" danger confirmLabel="Disconnect"
          onClose={() => setDisconnecting(false)} onConfirm={async () => {
            await office.nvidiaDisconnect();
            toast("NVIDIA AI disconnected");
            await load();
            onChanged();
          }}>
          <p className="muted">The saved key is removed and NVIDIA AI turns off. Your clips and the usage history stay.
            A key set in the backend's environment is not removed.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ selected audience
type Intent = "LOCAL_ONLY" | "OWNER_ONLY" | "SELECTED_AUDIENCE";
const INTENT_OPTIONS = (platform: "youtube" | "tiktok") => [
  { value: "LOCAL_ONLY" as Intent, label: "Keep on this PC" },
  { value: "OWNER_ONLY" as Intent, label: "Only me (staging)" },
  { value: "SELECTED_AUDIENCE" as Intent, label: platform === "youtube" ? "Selected audience (invited viewers)"
    : "Selected audience (followers)" },
];

function AudienceSettings({ onSaved }: { onSaved: () => void }) {
  const [view, setView] = useState<AudienceView | null>(null);
  const [yt, setYt] = useState<Intent>("LOCAL_ONLY");
  const [tt, setTt] = useState<Intent>("LOCAL_ONLY");
  const [group, setGroup] = useState("FOLLOWERS");
  const [privateOk, setPrivateOk] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  const apply = (v: AudienceView) => {
    setView(v);
    setYt(v.destinations.youtube?.intent || "LOCAL_ONLY");
    setTt(v.destinations.tiktok?.intent || "LOCAL_ONLY");
    setGroup(v.destinations.tiktok?.group || "FOLLOWERS");
    setPrivateOk(v.tiktok_private_confirmed);
    setReviewed(v.tiktok_followers_reviewed);
    setLabel(v.youtube_viewers_label);
  };
  useEffect(() => {
    office.audience().then(apply).catch((e) => setError(errorText(e)));
  }, []);
  if (!view) return <section className="panel"><p className="small muted">{error || "Loading who sees clips…"}</p>
  </section>;
  const ttSelected = tt === "SELECTED_AUDIENCE";
  const blocked = ttSelected && (!privateOk || !reviewed);
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      apply(await office.saveAudience({
        youtube_intent: yt, tiktok_intent: tt, tiktok_group: group, tiktok_private_confirmed: privateOk,
        tiktok_followers_reviewed: reviewed, youtube_viewers_label: label,
      }));
      toast("Audience saved");
      onSaved();
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  };
  return (
    <section className="panel" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} style={{ fontSize: "var(--fs-h3)" }}>Who sees your clips</h2>
      <p className="small muted">{view.scope}</p>
      {view.migrated_from && <p className="small">Your earlier setting “{view.migrated_from}” was converted to the
        closest safe choice. Check it below.</p>}
      <div className="field">
        <span className="label" id={`${id}-yt`}>YouTube</span>
        <Segmented<Intent> labelledBy={`${id}-yt`} value={yt} onChange={setYt} options={INTENT_OPTIONS("youtube")} />
        {yt === "SELECTED_AUDIENCE" && (
          <>
            <span className="tiny muted">Uploads stay Private. You add viewers yourself in YouTube Studio; ClipFoundry
              never invites anyone.</span>
            <label className="small" htmlFor={`${id}-label`}>Who you invite <span className="hint">your own short
              note, e.g. “5 friends”; no addresses</span></label>
            <input id={`${id}-label`} type="text" maxLength={80} value={label}
              onChange={(e) => setLabel(e.target.value)} />
          </>
        )}
      </div>
      <div className="field">
        <span className="label" id={`${id}-tt`}>TikTok</span>
        <Segmented<Intent> labelledBy={`${id}-tt`} value={tt} onChange={setTt} options={INTENT_OPTIONS("tiktok")} />
        {ttSelected && (
          <div className="stack">
            <span className="label small" id={`${id}-grp`}>Which group</span>
            <Segmented<string> labelledBy={`${id}-grp`} value={group} onChange={setGroup} options={[
              { value: "FOLLOWERS", label: "Followers (all approved followers)" },
              { value: "FRIENDS", label: "Friends (people you follow back)" },
            ]} />
            <label className="choice">
              <input type="checkbox" checked={privateOk} onChange={(e) => setPrivateOk(e.target.checked)} />
              <span className="small">My TikTok account is private (Settings and privacy → Privacy → Private
                account). ClipFoundry never changes it.</span>
            </label>
            <label className="choice">
              <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
              <span className="small">I reviewed my approved followers in the TikTok app: “Followers” means all of
                them.</span>
            </label>
          </div>
        )}
      </div>
      {blocked && <p className="small">Confirm both boxes to use your selected audience on TikTok.</p>}
      {error && <p className="small bad-text" role="alert">{error}</p>}
      <div className="row wrap">
        <button type="button" className="btn btn-primary btn-small" disabled={busy || blocked} onClick={save}>
          {busy && <span className="inline-spinner" aria-hidden="true" />}Save audience</button>
      </div>
      <p className="tiny muted">Public and unlisted posts are not possible in this version.</p>
    </section>
  );
}
