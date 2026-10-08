import { ReactNode, useEffect, useState } from "react";
import { errorText } from "../api";
import {
  audienceApi, AudienceDestination, AudienceIntent, AudienceView, DevLogEntry, INTENT_OF, IntegrationCard,
  integrations, NvidiaResult, NvidiaView, office,
} from "../office/api";
import { FieldCtx, NumInput, Seg, SecretField, SettingRow, SettingsPanel, Switch, TextInput } from "./settingsFields";
import { Banner, ConfirmDialog, Disclosure, Icon, Pill, toast, Tone } from "./ui";

/**
 * Settings → Integrations: who watches (the selected-audience choice an upload needs), one card per connection
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
        What each connection can do on this PC. A connected account does not unlock everything: some parts need the
        platform's own approval, and some are not offered at all. Nothing here posts anything.
      </p>
      {error && <Banner tone="bad" icon="alert" title="Integrations could not be loaded">{error}</Banner>}
      {aud && <AudiencePanel view={aud} onSaved={(v) => { setAud(v); load(); }} />}
      <SettingsPanel id="int-cards" title="Connections"
        intro="Each card says what is connected, what is missing, and what each part can do in this version.">
        {cards ? (
          <div className="integration-cards">
            {cards.filter((x) => x.id !== "nvidia").map((x) => <ConnectionCard key={x.id} card={x} />)}
          </div>
        ) : !error && <p className="small muted">Reading the connections…</p>}
      </SettingsPanel>
      <NvidiaPanel c={c} dirty={nvidiaDirty} unsaved={changed.length > 0}
        card={cards?.find((x) => x.id === "nvidia")} onChange={load} reload={reload} />
    </>
  );
}

// ------------------------------------------------------------------ who watches
function AudiencePanel({ view, onSaved }: { view: AudienceView; onSaved: (v: AudienceView) => void }) {
  return (
    <SettingsPanel id="int-audience" title="Who watches"
      intro={<>ClipFoundry uploads only for viewers you pick, never publicly. Nothing uploads to a platform until
        you confirm how its audience works. {view.limits}</>}>
      <div className="stack-4">
        <AudienceRow p="youtube" d={view.youtube} steps={view.youtube_steps} onSaved={onSaved} />
        <AudienceRow p="tiktok" d={view.tiktok} steps={view.tiktok_steps} onSaved={onSaved} />
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
  const promise = intent === "owner_only"
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
        <Radio name={id} value="selected" on={intent} set={setIntent}
          label={selectedLabel} hint={p === "youtube" ? "Private, shared in YouTube Studio with the people you pick"
            : "Followers-only posts on your private account"} />
        {p === "tiktok" && intent === "selected" && (
          <div className="row wrap" style={{ paddingLeft: 28 }} role="group" aria-label="Which TikTok group">
            {(["followers", "friends"] as const).map((g) => (
              <label key={g} className="choice small">
                <input type="radio" name={`${id}-group`} checked={group === g} onChange={() => setGroup(g)} />
                <span>{g === "followers" ? "Followers" : "Friends (followers you follow back)"}</span>
              </label>
            ))}
          </div>
        )}
        <Radio name={id} value="owner_only" on={intent} set={setIntent} label="Only me (staging)"
          hint="Nobody else can watch; not a test with viewers" />
        <Radio name={id} value="local_only" on={intent} set={setIntent} label="Keep clips on this PC"
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
function ConnectionCard({ card }: { card: IntegrationCard }) {
  const link = actionLink(card);
  return (
    <article className="integration" aria-labelledby={`card-${card.id}`}>
      <h3 id={`card-${card.id}`}>
        <span>{card.name}</span>
        <Pill tone={STATUS_TONE[card.status] || "neutral"}>{card.status_label}</Pill>
      </h3>
      {card.identity && <p className="small" style={{ margin: 0 }}>Signed in as <b>{card.identity}</b></p>}
      <p className="small muted" style={{ margin: 0 }}>{card.detail}</p>
      {card.missing.length > 0 && (
        <p className="small" style={{ margin: 0 }}><b>Missing:</b> {card.missing.join("; ")}</p>
      )}
      {card.action && (link
        ? <a className="btn btn-small" href={link} style={{ justifySelf: "start" }}>{card.action}</a>
        : <p className="small" style={{ margin: 0 }}><b>What to do:</b> {card.action}</p>)}
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
