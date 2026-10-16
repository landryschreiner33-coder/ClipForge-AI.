import { ReactNode, useEffect, useState } from "react";
import { errorText } from "../api";
import { at } from "../format";
import {
  audienceApi, AudienceDestination, AudienceIntent, AudienceView, ConnectionCheck, DevLogEntry, INTENT_OF,
  IntegrationCard, integrations, NvidiaResult, NvidiaView, office, SearchCheck, SearchConnection,
} from "../office/api";
import { FieldCtx, NumInput, Seg, SecretField, SettingRow, SettingsPanel, Switch, TextInput } from "./settingsFields";
import { Banner, ConfirmDialog, Disclosure, Icon, Pill, toast, Tone } from "./ui";
import { PhoneMonitorPanel } from "./PhoneMonitor";

/**
 * Settings → Integrations: who watches (the explicit audience choice an upload needs), one card per connection
 * with what it can and cannot do here, and the optional NVIDIA AI. A card keeps three things apart: whether this
 * version implements a capability, whether an account or key is connected, and whether it is available now.
 */

const STATUS_TONE: Record<string, Tone> = {
  connected: "good", not_connected: "neutral", permission_required: "warn", rate_limited: "warn", error: "bad",
  unsupported: "neutral", requires_user_action: "warn", off: "neutral", not_implemented: "neutral",
};
const CAP_STATE: Record<string, { label: string; tone: Tone }> = {
  implemented: { label: "Built in", tone: "good" },
  local: { label: "On this PC", tone: "good" },
  approval_required: { label: "Needs approval", tone: "warn" },
  not_implemented: { label: "Not in this version", tone: "neutral" },
  unsupported: { label: "Not offered", tone: "neutral" },
};
const NAME = { youtube: "YouTube", tiktok: "TikTok" } as const;
const NVIDIA_KEYS = ["nvidia_enabled", "nvidia_api_key", "nvidia_model", "nvidia_mode", "nvidia_production_url",
  "nvidia_daily_requests", "nvidia_daily_tokens", "nvidia_max_input_tokens", "nvidia_max_output_tokens",
  "nvidia_timeout_s", "nvidia_price_per_mtok_usd", "nvidia_daily_spend_cap_usd"];

export function IntegrationsTab({ c, changed, reload }: { c: FieldCtx; changed: string[]; reload: () => void }) {
  const [cards, setCards] = useState<IntegrationCard[] | null>(null);
  const [aud, setAud] = useState<AudienceView | null>(null);
  const [error, setError] = useState("");
  const load = () => {
    integrations.list().then((r) => { setCards(r.cards); setError(""); }).catch((e) => setError(errorText(e)));
    audienceApi.view().then(setAud).catch((e) => setError(errorText(e)));
  };
  useEffect(load, []);
  const nvidiaDirty = changed.some((k) => NVIDIA_KEYS.includes(k));
  return (
    <>
      <p className="small muted">
        Set up the connections supported by this app. Each card shows its current setup and the next step, if one
        is needed. Platform posting permissions still apply. Nothing here posts a video.
      </p>
      {error && <Banner tone="bad" icon="alert" title="Integrations could not be loaded">{error}</Banner>}
      <SearchConnections c={c} changed={changed} />
      <PhoneMonitorPanel />
      {aud && <AudiencePanel view={aud} onSaved={(v) => { setAud(v); load(); }} />}
      <SettingsPanel id="int-cards" title="Connections"
        intro="Each card says what is connected, what is missing, and what each part can do in this version.">
        {cards ? (
          <div className="integration-cards">
            {cards.filter((x) => x.id !== "nvidia" && !["not_implemented", "unsupported"].includes(x.status))
              .map((x) => <ConnectionCard key={x.id} card={x} onChange={load} />)}
          </div>
        ) : !error && <p className="small muted">Reading the connections…</p>}
      </SettingsPanel>
      <NvidiaPanel c={c} dirty={nvidiaDirty} unsaved={changed.length > 0}
        card={cards?.find((x) => x.id === "nvidia")} onChange={load} reload={reload} />
    </>
  );
}

// Discovery keys are separate from the account authorization needed to upload a video.
function SearchConnections({ c, changed }: { c: FieldCtx; changed: string[] }) {
  return (
    <SettingsPanel id="int-search" title="Search connections"
      intro={<>Add an optional search key to find more relevant video links. Your folders and the free-license
        library work without a key. Save changes below; saving a key does not test it or upload anything.</>}>
      <SettingRow k="youtube_api_key" label="YouTube Data API key"
        hint="Optional for public-video discovery. A connected YouTube account already supports search.">
        <SecretField k="youtube_api_key" c={c} removable placeholder="AIza…" />
        <span className="small muted">A key uses its Google project's allowance; it does not remove YouTube's
          daily limits or authorize uploads. The default allowance includes 100 searches a day.</span>
        <Disclosure summary="Get a YouTube search key">
          <ol className="small">
            <li>Choose your project in <a className="textlink"
              href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank"
              rel="noreferrer">Google Cloud and enable YouTube Data API v3</a>.</li>
            <li>Open <a className="textlink" href="https://console.cloud.google.com/apis/credentials"
              target="_blank" rel="noreferrer">Credentials</a>, create an API key, and restrict its API access to
              YouTube Data API v3.</li>
            <li>Paste the key here, then save your changes. Keep your YouTube account connected for uploading.</li>
            <li>This is a desktop app. A key restricted to browser websites/referrers cannot authorize its requests.
              Keep the API restriction set to YouTube Data API v3 and use application restrictions suited to your PC.</li>
          </ol>
          <a className="textlink small" href="https://developers.google.com/youtube/v3/getting-started"
            target="_blank" rel="noreferrer">Official setup and current quota details</a>
        </Disclosure>
        <p className="tiny muted">If this optional key fails, Remove it and save to search with your connected
          YouTube account instead. An API key is different from an OAuth client ID or client secret.</p>
        <SearchConnectionCheck provider="youtube" dirty={changed.some((key) =>
          ["youtube_api_key", "youtube_client_id", "youtube_client_secret"].includes(key))} />
      </SettingRow>
      <SettingRow k="tavily_api_key" label="Tavily web search key"
        hint="Adds topic-based web search for public video links and the originals behind clips.">
        <SecretField k="tavily_api_key" c={c} removable placeholder="tvly-…" />
        <span className="small muted">The free plan includes 1,000 credits each month with no credit card.
          This app uses basic searches, at one credit per request. Search results give links, not TikTok viewing
          statistics or reuse permission.</span>
        <ol className="small" style={{ margin: 0, paddingLeft: 20 }}>
          <li><a className="textlink" href="https://app.tavily.com" target="_blank" rel="noreferrer">
            Open Tavily and create a free account</a>.</li>
          <li>Copy the API key from your dashboard, paste it here, then save your changes.</li>
        </ol>
        <a className="textlink small" href="https://docs.tavily.com/documentation/api-credits" target="_blank"
          rel="noreferrer">Current Tavily free allowance and credit costs</a>
        <SearchConnectionCheck provider="tavily" dirty={changed.includes("tavily_api_key")} />
      </SettingRow>
      <SettingRow k="tavily_free_credits" label="Included Tavily credits each month" errors={c.errors}
        hint="Match your provider plan. The free plan includes 1,000; usage in other apps also counts there.">
        <NumInput k="tavily_free_credits" c={c} />
      </SettingRow>
      <SettingRow k="discovery_monthly_budget_usd" label="Paid web-search limit each month" errors={c.errors}
        hint="US dollars beyond the included credits. Keep this at 0 for free-only use in this app.">
        <NumInput k="discovery_monthly_budget_usd" c={c} step={1} />
        <button type="button" className="btn btn-small" style={{ justifySelf: "start" }}
          onClick={() => c.set({ tavily_free_credits: 1000, discovery_monthly_budget_usd: 0 })}>
          Use free Tavily plan limits
        </button>
        <span className="tiny muted">This is an app allowance, not a live provider balance. Check Tavily's dashboard
          before enabling paid usage or sharing a key with another app.</span>
      </SettingRow>
      <SettingRow k="library_discovery" label="Free-license library"
        hint="Search Wikimedia Commons for videos with recorded free licenses. No API key is needed.">
        <Switch k="library_discovery" c={c} />
      </SettingRow>
      <p className="small muted" style={{ margin: 0 }}>Keys are stored sealed on this PC and saved keys stay hidden.
        Enter keys here, never in chat. The next search uses your saved setup; Missions shows search waits and
        problems. Your shortlist quality, review and publishing checks still apply.</p>
      <a className="textlink small" href="#/missions/sources">Open discovery choices and recent search results</a>
    </SettingsPanel>
  );
}

function SearchConnectionCheck({ provider, dirty }: { provider: "youtube" | "tavily"; dirty: boolean }) {
  const [connection, setConnection] = useState<SearchConnection | null>(null);
  const [result, setResult] = useState<SearchCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let live = true;
    integrations.searchStatus().then((data) => {
      if (live) { setConnection(data[provider]); setResult(data[provider].last_check); }
    }).catch((e) => { if (live) setProblem(errorText(e)); });
    return () => { live = false; };
  }, [provider]);
  const test = async () => {
    setBusy(true);
    setProblem("");
    try { setResult(await integrations.testSearch(provider)); }
    catch (e) { setProblem(errorText(e)); }
    finally { setBusy(false); }
  };
  const name = provider === "youtube" ? "YouTube" : "Tavily";
  const stale = dirty || result?.current === false;
  return <div className="stack" style={{ gap: 8 }}>
    <div className="row wrap">
      <button type="button" className="btn btn-small" disabled={busy || dirty || !connection?.configured}
        onClick={() => void test()}>{busy ? "Checking…" : `Test saved ${name} connection`}</button>
      <span className="tiny muted">{dirty ? "Save changes first; this checks the saved connection."
        : provider === "youtube" ? "One general-quota read, with one retry if sign-in expires. No search or upload."
          : "Checks the saved key through account usage, without running a search."}</span>
    </div>
    {connection?.configured && <p className="tiny muted">{provider === "youtube"
      ? `Saved search method: ${connection.auth_mode === "api_key" ? "YouTube API key" : "connected YouTube account"}.`
      : "Saved search method: Tavily API key."}</p>}
    {!dirty && connection && !connection.configured && <p className="tiny muted">{provider === "youtube"
      ? "Save a search API key or connect your YouTube account first." : "Save your Tavily API key first."}</p>}
    {result && <Banner tone={stale ? "neutral" : result.ok ? "info" : result.status === "waiting" ? "warn" : "bad"}
      title={stale ? "Previous connection result" : result.ok ? `${name} connection accepted` : `${name} needs attention`}>
      {stale && <p>The saved connection has changed. Save and test again to check the new setup.</p>}
      <p>{result.detail}</p>
      {result.fix && <p>{result.fix}</p>}
      {result.until && result.until * 1000 > Date.now() && <p>Try again after {at(result.until)}.</p>}
    </Banner>}
    {problem && <Banner tone="bad" title="Connection check could not finish">{problem}</Banner>}
  </div>;
}

// ------------------------------------------------------------------ who watches
export function AudiencePanel({ view, onSaved, platforms = ["youtube", "tiktok"] }: {
  view: AudienceView; onSaved: (v: AudienceView) => void; platforms?: ("youtube" | "tiktok")[];
}) {
  return (
    <SettingsPanel id="int-audience" title="Who watches"
      intro={<>Choose the audience for new posts, then set up automatic YouTube publishing in Accounts. Public posts
        may be watched by anyone. Existing posts and previously planned private uploads keep their audience.
        Accessible videos still need reuse permission and a passing final check before posting. {view.limits}</>}>
      <div className="stack-4">
        {platforms.map((p) => <AudienceRow key={p} p={p} d={view[p]} steps={view[`${p}_steps`]} onSaved={onSaved} />)}
      </div>
    </SettingsPanel>
  );
}

function AudienceRow({ p, d, steps, onSaved }: {
  p: "youtube" | "tiktok"; d: AudienceDestination; steps: string; onSaved: (v: AudienceView) => void;
}) {
  const name = NAME[p];
  const [intent, setIntent] = useState<AudienceIntent>(INTENT_OF[d.intent]);
  const [group, setGroup] = useState(d.group === "friends" ? "friends" : "followers");
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [askChanged, setAskChanged] = useState(false);
  useEffect(() => {
    setIntent(INTENT_OF[d.intent]);
    setGroup(d.group === "friends" ? "friends" : "followers");
    setUnderstood(false);
  }, [d.intent, d.group, d.confirmed_at]);
  const selectIntent = (v: AudienceIntent) => { setIntent(v); setUnderstood(false); };
  const dirty = intent !== INTENT_OF[d.intent] || (p === "tiktok" && intent === "selected" && group !== d.group);
  const needsWord = intent !== "local_only";
  const save = async (groupChanged = false) => {
    setBusy(true);
    try {
      const v = await audienceApi.set(p, { intent, group: p === "tiktok" ? group : "", confirm: needsWord,
        group_changed: groupChanged });
      toast(groupChanged ? `${name}: older approvals will ask for your OK again` : `${name}: who watches saved`);
      onSaved(v);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
      setAskChanged(false);
    }
  };
  const selectedLabel = p === "youtube" ? "My invited viewers" : "My approved followers";
  const promise = intent === "public"
    ? `New ${name} posts are public: anyone may watch, share or find them. This does not make existing posts or `
      + "previously scheduled private uploads public. Public discovery alone does not grant reuse permission."
    : intent === "owner_only"
    ? `Only I can see these ${name} uploads. Nobody else watches them, so they teach the Brain nothing.`
    : p === "youtube"
      ? "ClipFoundry uploads as Private and cannot invite anyone. I share each video with my viewers in YouTube "
        + "Studio myself."
      : `ClipFoundry posts for ${group === "friends" ? "my friends (followers I follow back)" : "my followers"}. My `
        + "TikTok account is private, so only people I approved follow me.";
  const id = `aud-${p}`;
  return (
    <section className="audience-row" aria-labelledby={`${id}-h`}>
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        <h3 id={`${id}-h`} style={{ margin: 0, fontSize: "var(--fs-h3)" }}>{name}</h3>
        {d.confirmed ? <Pill tone="good" icon="check">{d.label} · confirmed</Pill>
          : d.intent === "LOCAL_ONLY" ? <Pill icon="dot">Kept on this PC</Pill>
            : <Pill tone="warn" icon="alert">Not confirmed: nothing uploads to {name}</Pill>}
      </div>
      {d.halted && (
        <Banner tone="bad" icon="alert" title={`Uploads to ${name} are stopped`}
          actions={<button type="button" className="btn btn-small" disabled={busy}
            onClick={async () => {
              setBusy(true);
              try { onSaved(await audienceApi.checked(p)); toast(`${name}: uploads may continue`); }
              catch (e) { toast(errorText(e), true); }
              finally { setBusy(false); }
            }}>I checked it</button>}>
          {d.halted.detail} Open the video in {name}, set it back to the audience you chose, then press I checked it.
        </Banner>
      )}
      <p className="small muted" style={{ margin: 0 }}>{d.detail}</p>
      <fieldset className="stack" style={{ gap: 4, border: 0, padding: 0, margin: 0 }}>
        <legend className="label">Who may watch {name} uploads</legend>
        <Radio name={id} value="public" on={intent} set={selectIntent} label="Public audience"
          hint={p === "youtube" ? "Anyone can watch; automatic publishing needs separate permission"
            : "Everyone; TikTok approval and an explicit choice on each post are required"} />
        <Radio name={id} value="selected" on={intent} set={selectIntent}
          label={selectedLabel} hint={p === "youtube" ? "Private, shared in YouTube Studio with the people you pick"
            : "Followers-only posts on your private account"} />
        {p === "tiktok" && intent === "selected" && (
          <div className="row wrap" style={{ paddingLeft: 28 }} role="group" aria-label="Which TikTok group">
            {(["followers", "friends"] as const).map((g) => (
              <label key={g} className="choice small">
                <input type="radio" name={`${id}-group`} checked={group === g}
                  onChange={() => { setGroup(g); setUnderstood(false); }} />
                <span>{g === "followers" ? "Followers" : "Friends (followers you follow back)"}</span>
              </label>
            ))}
          </div>
        )}
        <Radio name={id} value="owner_only" on={intent} set={selectIntent} label="Only me (staging)"
          hint="Nobody else can watch; not a test with viewers" />
        <Radio name={id} value="local_only" on={intent} set={selectIntent} label="Keep clips on this PC"
          hint={`Nothing is uploaded to ${name}`} />
      </fieldset>
      {needsWord && (dirty || !d.confirmed) && (
        <label className="choice small">
          <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
          <span>I understand: {promise}</span>
        </label>
      )}
      <div className="row wrap">
        {(dirty || !d.confirmed) && (
          <button type="button" className="btn btn-primary btn-small" disabled={busy || (needsWord && !understood)}
            onClick={() => save()}>
            {needsWord ? "Confirm who watches" : "Keep clips on this PC"}
          </button>
        )}
        {d.confirmed && !dirty && d.intent === "SELECTED_AUDIENCE" && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => setAskChanged(true)}>
            My viewers changed
          </button>
        )}
      </div>
      <Disclosure summary={`How to set this up on ${name}`}><p className="small">{steps}</p></Disclosure>
      {askChanged && (
        <ConfirmDialog title={`Did the people who watch on ${name} change?`} confirmLabel="Yes, they changed"
          onConfirm={() => save(true)} onClose={() => setAskChanged(false)}>
          Posts you approved before were approved for the earlier group, so each one asks for your OK again. Nothing
          already uploaded changes.
        </ConfirmDialog>
      )}
    </section>
  );
}

function Radio({ name, value, on, set, label, hint }: {
  name: string; value: AudienceIntent; on: AudienceIntent; set: (v: AudienceIntent) => void; label: string;
  hint: string;
}) {
  return (
    <label className="choice">
      <input type="radio" name={name} checked={on === value} onChange={() => set(value)} />
      <span>{label} <span className="muted small">· {hint}</span></span>
    </label>
  );
}

// ------------------------------------------------------------------ connection cards
function ConnectionCard({ card, onChange }: { card: IntegrationCard; onChange: () => void }) {
  const link = actionLink(card);
  const [busy, setBusy] = useState(false);
  const chk = card.last_check;
  const test = async () => {
    setBusy(true);
    try {
      const r: ConnectionCheck = await integrations.testConnection(card.id as "youtube" | "tiktok");
      toast(r.ok ? `${card.name}: the connection works` : `${card.name}: ${r.status_label}. ${r.detail}`, !r.ok);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
      onChange();
    }
  };
  return (
    <article className="integration" aria-labelledby={`card-${card.id}`}>
      <h3 id={`card-${card.id}`}>
        <span>{card.name}</span>
        <Pill tone={STATUS_TONE[card.status] || "neutral"}>{card.status_label}</Pill>
      </h3>
      {card.identity && <p className="small" style={{ margin: 0 }}>Signed in as <b>{card.identity}</b></p>}
      <p className="small muted" style={{ margin: 0 }}>{card.detail}</p>
      {card.limit && <p className="small" style={{ margin: 0 }}><b>Waiting until:</b> {at(card.limit.until)}</p>}
      {card.missing.length > 0 && (
        <p className="small" style={{ margin: 0 }}><b>Missing:</b> {card.missing.join("; ")}</p>
      )}
      {card.action && (link
        ? <a className="btn btn-small" href={link} style={{ justifySelf: "start" }}>{card.action}</a>
        : <p className="small" style={{ margin: 0 }}><b>What to do:</b> {card.action}</p>)}
      {card.can_test && (
        <div className="stack" style={{ gap: 4 }}>
          <p className="small" style={{ margin: 0 }}>
            <b>Last successful check:</b> {card.checked_at ? at(card.checked_at) : "none yet"}
          </p>
          {chk && !chk.ok && chk.current !== false && (
            <p className="small" style={{ margin: 0 }}>
              <Pill tone={STATUS_TONE[chk.status] || "bad"} icon="alert">{chk.status_label}</Pill>
              {" "}Last check, {at(chk.at)}: {chk.detail}{chk.fix ? ` ${chk.fix}` : ""}
            </p>
          )}
          <button type="button" className="btn btn-small" style={{ justifySelf: "start" }} disabled={busy}
            onClick={test} aria-label={`Test connection to ${card.name}`}>
            {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="refresh" />}
            Test connection
          </button>
          <p className="tiny muted" style={{ margin: 0 }}>
            {card.id === "youtube" ? "Reads your channel's name from YouTube (1 unit of the daily API quota)."
              : "Asks TikTok about your account and the audiences you can post to."} Nothing is uploaded or changed, and
            it costs no money.
          </p>
        </div>
      )}
      {card.capabilities.length > 0 && (
        <details>
          <summary>What it can do ({card.capabilities.length})</summary>
          <ul className="caps">
            {card.capabilities.map((cap) => (
              <li key={cap.id}>
                <b>{cap.label}</b> <Pill tone={CAP_STATE[cap.state]?.tone || "neutral"}>
                  {CAP_STATE[cap.state]?.label || cap.state}</Pill>
                <div className="muted">{cap.detail}</div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

function actionLink(card: IntegrationCard): string {
  const a = card.action.toLowerCase();
  if (a.startsWith("confirm the audience")) return "#/settings/integrations";
  if (a.startsWith("connect")) return "#/settings";
  if (a.includes("settings → integrations")) return "#/settings/integrations";
  if (a.includes("settings → advanced")) return "#/settings/advanced";
  return "";
}

// ------------------------------------------------------------------ NVIDIA AI (optional)
function NvidiaPanel({ c, dirty, unsaved, card, onChange, reload }: {
  c: FieldCtx; dirty: boolean; unsaved: boolean; card?: IntegrationCard; onChange: () => void; reload: () => void;
}) {
  const { s, errors } = c;
  const [v, setV] = useState<NvidiaView | null>(null);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<NvidiaResult | null>(null);
  const [askDisconnect, setAskDisconnect] = useState(false);
  const refresh = () => integrations.nvidia().then(setV).catch(() => undefined);
  useEffect(() => { refresh(); }, [c.saved]);
  const run = async (what: string, fn: () => Promise<NvidiaResult>) => {
    setBusy(what);
    setResult(null);
    try {
      setResult(await fn());
    } catch (e) {
      setResult({ ok: false, detail: errorText(e) });
    } finally {
      setBusy("");
      refresh();
      onChange();
    }
  };
  const optIn = async (yes: boolean) => {
    setBusy("optin");
    try {
      setV(await integrations.optIn(yes));
      setAgree(false);
      toast(yes ? "Agreement saved" : "Agreement withdrawn: nothing more is sent to NVIDIA");
      onChange();
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy("");
    }
  };
  const production = s.nvidia_mode === "production";
  const lim = v?.limits || {};
  const cost = v ? (v.usage.cost_known ? `$${(v.usage.cost_usd ?? 0).toFixed(4)}` : "unknown (no price set)") : "";
  return (
    <SettingsPanel id="int-nvidia" title="NVIDIA AI (optional)"
      intro={<>Off by default and never required: ClipFoundry's own analysis on this PC always works. When on, it can
        re-score the strongest clip candidates for work you start yourself. {card &&
          <Pill tone={STATUS_TONE[card.status] || "neutral"}>{card.status_label}</Pill>}</>}>
      {v?.circuit.open && (
        <Banner tone="warn" icon="clock" title="NVIDIA AI is paused">
          {v.circuit.reason || "Paused after failed requests."} Local analysis is used meanwhile.
        </Banner>
      )}
      <SettingRow k="nvidia_enabled" label="Use NVIDIA AI" hint="Off: nothing is ever sent to NVIDIA">
        <Switch k="nvidia_enabled" c={c} />
      </SettingRow>
      <SettingRow k="nvidia_api_key" label="NVIDIA API key"
        hint={v?.key_from_env ? "Using NVIDIA_API_KEY set on this PC" : "Stored sealed on this PC. Never paste it into "
          + "a chat or a message"}>
        <SecretField k="nvidia_api_key" c={c} removable placeholder="nvapi-…" />
      </SettingRow>
      <SettingRow k="nvidia_model" label="Model" hint="The model name exactly as NVIDIA lists it">
        <TextInput k="nvidia_model" c={c} />
      </SettingRow>
      <SettingRow k="nvidia_mode" label="Mode" group
        hint={production ? "Your own endpoint, with a price and a daily spending cap"
          : "NVIDIA's hosted catalog, for development and trying it out"}>
        <Seg k="nvidia_mode" c={c} options={[{ value: "development", label: "Development" },
          { value: "production", label: "Production" }]} />
      </SettingRow>
      {production && (
        <>
          <SettingRow k="nvidia_production_url" label="Endpoint" hint="Your own https address whose terms allow this">
            <TextInput k="nvidia_production_url" c={c} placeholder="https://…" />
          </SettingRow>
          <SettingRow k="nvidia_price_per_mtok_usd" label="Price per million tokens (USD)" errors={errors}
            hint="-1 means unknown; production needs the real price (unknown is never treated as free)">
            <NumInput k="nvidia_price_per_mtok_usd" c={c} step={0.01} />
          </SettingRow>
          <SettingRow k="nvidia_daily_spend_cap_usd" label="Daily spending cap (USD)" errors={errors}
            hint="Requests stop for the day at this amount; 0 allows no paid use">
            <NumInput k="nvidia_daily_spend_cap_usd" c={c} step={0.5} />
          </SettingRow>
        </>
      )}
      <Disclosure summary="Daily limits and timeouts">
        <SettingRow k="nvidia_daily_requests" label="Requests a day" errors={errors}>
          <NumInput k="nvidia_daily_requests" c={c} />
        </SettingRow>
        <SettingRow k="nvidia_daily_tokens" label="Tokens a day" errors={errors}>
          <NumInput k="nvidia_daily_tokens" c={c} />
        </SettingRow>
        <SettingRow k="nvidia_max_input_tokens" label="Most text sent per request (tokens)" errors={errors}>
          <NumInput k="nvidia_max_input_tokens" c={c} />
        </SettingRow>
        <SettingRow k="nvidia_max_output_tokens" label="Longest answer (tokens)" errors={errors}>
          <NumInput k="nvidia_max_output_tokens" c={c} />
        </SettingRow>
        <SettingRow k="nvidia_timeout_s" label="Give up after (seconds)" errors={errors}>
          <NumInput k="nvidia_timeout_s" c={c} />
        </SettingRow>
      </Disclosure>

      {v && (
        <div className="stack-3" style={{ paddingTop: 8 }}>
          <h3 style={{ fontSize: "var(--fs-h3)", margin: 0 }}>What is sent</h3>
          <p className="small">{v.data_note}</p>
          {!production && <p className="small muted">{v.development_note}</p>}
          {v.opted_in ? (
            <div className="row wrap">
              <Pill tone="good" icon="check">You agreed</Pill>
              <button type="button" className="btn btn-small" disabled={!!busy} onClick={() => optIn(false)}>
                Withdraw my agreement
              </button>
            </div>
          ) : (
            <div className="row wrap">
              <label className="choice small">
                <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
                <span>I agree that, while NVIDIA AI is on, the excerpts described above are sent to NVIDIA.</span>
              </label>
              <button type="button" className="btn btn-small" disabled={!agree || !!busy} onClick={() => optIn(true)}>
                Save my agreement
              </button>
            </div>
          )}
          <dl className="kv">
            <dt>Today</dt>
            <dd>{v.usage.requests} of {lim.nvidia_daily_requests ?? "?"} requests · {v.usage.tokens.toLocaleString("en-US")}
              {" "}of {(lim.nvidia_daily_tokens ?? 0).toLocaleString("en-US")} tokens · cost {cost}</dd>
            <dt>Endpoint</dt><dd><code className="break">{v.endpoint || "not set"}</code></dd>
            <dt>Used for scoring</dt>
            <dd>{v.selected ? "Yes" : <>No. Choose it under <a className="textlink" href="#/settings/advanced">
              Advanced → AI scoring</a> to use it.</>}</dd>
          </dl>
          {v.problems.length > 0 && (
            <ul className="small" style={{ margin: 0, paddingLeft: 20 }}>{v.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          )}
          <div className="row wrap">
            <button type="button" className="btn btn-small" disabled={!!busy || dirty}
              onClick={() => run("check", integrations.check)}>
              {busy === "check" ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="refresh" />}
              Check the setup
            </button>
            <button type="button" className="btn btn-small" disabled={!!busy || dirty || !v.selected}
              onClick={() => run("test", integrations.test)}>
              {busy === "test" ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="spark" />}
              Run a small AI test
            </button>
            <button type="button" className="btn btn-small btn-quiet"
              disabled={!!busy || unsaved || (!v.has_key && !v.enabled && !v.opted_in)}
              onClick={() => setAskDisconnect(true)}>Disconnect</button>
          </div>
          <p className="tiny muted">
            {dirty ? "Save first: the check and the test use the saved settings. " : ""}
            The check reads NVIDIA's model list and uses nothing. The small test sends one short made-up text (no clip
            content) and counts against today's limits.{unsaved ? " Disconnect needs your other changes saved or "
              + "discarded first." : ""}
          </p>
          {result && <Pill tone={result.ok ? "good" : "bad"} icon={result.ok ? "check" : "alert"}>
            {result.detail || (result.ok ? "OK" : "Did not work")}</Pill>}
        </div>
      )}
      {askDisconnect && (
        <ConfirmDialog title="Disconnect NVIDIA AI?" confirmLabel="Disconnect" danger
          onConfirm={async () => {
            setAskDisconnect(false);
            setBusy("disconnect");
            try {
              await integrations.disconnect();
              toast("NVIDIA AI disconnected");
              reload();  // the saved key, switch and AI provider changed on the server
              onChange();
            } catch (e) {
              toast(errorText(e), true);
            } finally {
              setBusy("");
            }
          }}
          onClose={() => setAskDisconnect(false)}>
          The saved key is forgotten, NVIDIA AI turns off and your agreement is withdrawn. If AI scoring used NVIDIA,
          it goes back to the local analysis. Clips and earlier results stay.
        </ConfirmDialog>
      )}
    </SettingsPanel>
  );
}

// ------------------------------------------------------------------ Dev Log (Settings → Advanced)
export function DevLogPanel() {
  const [rows, setRows] = useState<DevLogEntry[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { office.devlog(100).then(setRows).catch((e) => setError(errorText(e))); }, []);
  return (
    <SettingsPanel id="adv-devlog" title="Dev Log"
      intro={<>Read-only history of changes made by AI assistants to this copy of ClipFoundry, from
        <code> .clipfoundry/ai-change-log.jsonl</code>. The longer notes are in AI_CHANGELOG.md and AI_HANDOFF.md in
        the app folder.</>}>
      {error && <p className="small error-text">{error}</p>}
      {rows === null && !error && <p className="small muted">Reading the log…</p>}
      {rows && !rows.length && <p className="small muted">No development history in this copy.</p>}
      {rows && rows.length > 0 && (
        <ol className="devlog">
          {rows.map((r, i) => (
            <li key={i}>
              <div className="row wrap" style={{ justifyContent: "space-between" }}>
                <b>{r.checkpoint || "Change"}</b>
                <span className="tiny muted nowrap">{r.at ? String(r.at).replace("T", " ").slice(0, 16) : ""}</span>
              </div>
              {r.summary && <p className="small" style={{ margin: "4px 0" }}>{r.summary}</p>}
              <DevLogDetails r={r} />
            </li>
          ))}
        </ol>
      )}
    </SettingsPanel>
  );
}

function DevLogDetails({ r }: { r: DevLogEntry }) {
  const parts: ReactNode[] = [];
  if (r.tests) parts.push(<p key="t" className="small"><b>Tests:</b> {String(r.tests)}</p>);
  if (r.verified?.length) parts.push(<p key="v" className="small"><b>Verified:</b> {r.verified.join("; ")}</p>);
  if (r.not_verified?.length) {
    parts.push(<p key="n" className="small"><b>Not verified:</b> {r.not_verified.join("; ")}</p>);
  }
  if (r.files?.length) parts.push(<p key="f" className="tiny muted">Files: {r.files.join(", ")}</p>);
  return parts.length ? <Disclosure summary="Details">{parts}</Disclosure> : null;
}
