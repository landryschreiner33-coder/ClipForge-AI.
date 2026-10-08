import { MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { Accounts, api, errorText, Health, Platform, PlatformAccount, Settings } from "../api";
import { navigate, useLeaveGuard } from "../router";
import { useStatus } from "../status";
import { useMotion } from "../motion";
import {
  AccountBadge, ConnectButton, PLATFORM_NAME, TikTokSetupSteps, YouTubeSetupSteps,
} from "../components/accounts";
import { AutopilotSettings, Errors } from "../components/autopilotSettings";
import { AutoPublishLine } from "../components/autoPublish";
import { DevLogPanel, IntegrationsTab } from "../components/integrations";
import {
  Check, FieldCtx, fieldId, FIELDS, NumInput, Seg, SecretField, Select, SettingRow, SettingsPanel, SettingsTab, Switch,
  TextInput, validate,
} from "../components/settingsFields";
import {
  Banner, Disclosure, EmptyState, Icon, LinkTabs, LoadingPage, PageHead, Pill, StylePicker, toast, Toggle, TRACKING,
} from "../components/ui";

const WHISPER_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"];
const TAB_NAME: Record<SettingsTab, string> = {
  accounts: "Accounts", defaults: "Defaults", integrations: "Integrations", advanced: "Advanced",
};
const TAB_HREF: Record<SettingsTab, string> = {
  accounts: "#/settings", defaults: "#/settings/defaults", integrations: "#/settings/integrations",
  advanced: "#/settings/advanced",
};
const ACCOUNT_KEYS: Record<Platform, string[]> = {
  youtube: ["youtube_client_id", "youtube_client_secret", "youtube_project_verified"],
  tiktok: ["tiktok_client_key", "tiktok_client_secret", "tiktok_direct_post", "tiktok_read_stats",
    "tiktok_app_audited"],
};
const SECRETS = new Set(["openai_api_key", "anthropic_api_key", "youtube_client_secret", "tiktok_client_secret",
  "youtube_api_key", "tavily_api_key", "nvidia_api_key"]);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Settings: Accounts (connect, app codes, how posts get approved), Defaults (new clips, the daily target, posting
 * hours, topics), Integrations (who watches, what each connection can do, the optional NVIDIA AI) and Advanced
 * (everything else, and the read-only Dev Log). One sticky save bar for all four: it names the unsaved changes,
 * and a field error blocks saving and points at the field. Secrets are never sent to the page: they show as
 * "•••••••• (saved)" with Replace.
 */
export default function SettingsPage({ tab }: { tab?: string }) {
  const t: SettingsTab = tab === "defaults" || tab === "integrations" || tab === "advanced" ? tab : "accounts";
  const { st } = useStatus();
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [loadError, setLoadError] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [form, setForm] = useState(0); // remount key: resets the secret boxes after a save or discard
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const [saveError, setSaveError] = useState("");
  const [focusKey, setFocusKey] = useState("");
  const [goingTo, setGoingTo] = useState(""); // a tab being opened (see switchTab)

  const load = () => {
    api.settings()
      .then((s) => { setSaved(s); setDraft(s); setLoadError(""); })
      .catch((e) => setLoadError(errorText(e)));
    api.health().then(setHealth).catch(() => undefined);
    api.accounts().then(setAccounts).catch(() => undefined);
  };
  useEffect(load, []);

  const changed = draft && saved ? Object.keys(FIELDS).filter((k) => k in draft && !same(draft[k], saved[k])) : [];
  const errors = useMemo(() => (draft ? validate(draft) : {}), [draft]);
  const errorKeys = Object.keys(FIELDS).filter((k) => errors[k]);
  const set = (patch: Settings) => {
    setDraft((d) => d && { ...d, ...patch });
    setJustSaved(false);
    setSaveError("");
  };

  // After moving to the tab of an invalid field, put the focus on it.
  useEffect(() => {
    if (!focusKey) return;
    const el = document.getElementById(fieldId(focusKey));
    if (el) {
      el.scrollIntoView({ block: "center" });
      el.focus();
      setFocusKey("");
    }
  });
  const goToField = (k: string) => {
    const where = FIELDS[k]?.tab || t;
    setFocusKey(k);
    if (where !== t) switchTab(TAB_HREF[where]);
  };

  /** Save the changed settings only. Resolves false when nothing was saved (the page then stays). */
  const save = async (keys = changed): Promise<boolean> => {
    if (!draft || !saved) return false;
    if (!keys.length) return true;
    if (errorKeys.length) {
      goToField(errorKeys[0]);
      return false;
    }
    const patch = Object.fromEntries(keys.map((k) => [k, draft[k]]));
    setSaving(true);
    setSaveError("");
    try {
      const out = await api.saveSettings(patch);
      // The server keeps a value it can't use (a range or an unknown name): say so instead of pretending it saved.
      const kept = keys.filter((k) => !SECRETS.has(k) && !same(out[k], patch[k]))
        .map((k) => `${FIELDS[k].label} was saved as ${String(out[k])}.`);
      const fresh = { ...out };
      setSaved(fresh);
      setDraft((d) => (d ? { ...d, ...Object.fromEntries(keys.map((k) => [k, fresh[k]])) } : fresh));
      setForm((f) => f + 1);
      setNotes(kept);
      setJustSaved(true);
      toast(keys.length === changed.length ? "Settings saved" : "Saved");
      api.health().then(setHealth).catch(() => undefined);
      api.accounts().then(setAccounts).catch(() => undefined);
      return true;
    } catch (e) {
      setSaveError(errorText(e));
      return false;
    } finally {
      setSaving(false);
    }
  };
  const saveRef = useRef(save);
  saveRef.current = save;
  const discard = () => {
    setDraft(saved);
    setForm((f) => f + 1);
    setSaveError("");
  };

  const labels = changed.map((k) => FIELDS[k].label);
  const what = labels.length > 4 ? `${labels.slice(0, 4).join(", ")} and ${labels.length - 4} more` : labels.join(", ");
  // Leaving Settings with unsaved changes asks first. Switching tabs doesn't: the three tabs are one page with one
  // draft. For that one move the guard is lifted (goingTo), and it comes back once the new tab shows. (Not
  // router.leaveTo: after a held-back Back and "Stay" it repeats that Back instead of opening the tab.)
  const guard = useMemo(() => (changed.length && !goingTo ? {
    what, save: () => saveRef.current(), discard: () => { setDraft(saved); setForm((f) => f + 1); },
  } : null), [what, t, saved, goingTo]); // eslint-disable-line react-hooks/exhaustive-deps
  useLeaveGuard(guard);
  useEffect(() => setGoingTo(""), [t]);
  useEffect(() => {
    if (goingTo) navigate(goingTo);
  }, [goingTo]);
  function switchTab(href: string) {
    if (href !== TAB_HREF[t]) setGoingTo(href);
  }
  const tabClick = (e: MouseEvent) => {
    const a = (e.target as HTMLElement).closest("a");
    if (!a || !changed.length) return;
    e.preventDefault();
    switchTab(a.getAttribute("href") || "#/settings");
  };

  if (loadError) {
    return (
      <div className="page narrow">
        <PageHead title="Settings" />
        <EmptyState icon="alert" title="Settings could not be loaded"
          actions={<button type="button" className="btn" onClick={load}><Icon name="refresh" />Try again</button>}>
          {loadError}
        </EmptyState>
      </div>
    );
  }
  if (!draft || !saved) return <LoadingPage label="Loading settings" />;

  const c: FieldCtx = { s: draft, set, errors, saved };
  const expired = (["youtube", "tiktok"] as const).filter((p) => accounts?.[p]?.needs_reconnect);
  const gpuProblem = st?.gpu?.problem || health?.whisper.problem || "";
  const gpuFix = st?.gpu?.fix || health?.whisper.fix || "";
  const firstError = errorKeys[0];
  return (
    <div className="page narrow">
      <PageHead title="Settings"
        sub={<>
          Stored on this computer, in ClipFoundry's data folder
          {health?.data_dir ? <>: <code className="break">{health.data_dir}</code></> : ""}.
        </>} />
      {expired.length > 0 && t !== "accounts" && (
        <Banner tone="bad" icon="link"
          title={`${expired.map((p) => PLATFORM_NAME[p]).join(" and ")} ${expired.length > 1 ? "need" : "needs"} you `
            + "to sign in again."}
          actions={<a className="btn btn-small" href="#/settings" onClick={tabClick}>Open Accounts</a>}>
          Planned posts there wait until you connect again.
        </Banner>
      )}
      {gpuProblem && t !== "advanced" && (
        <Banner tone="bad" icon="cpu" title="GPU transcription is not working."
          actions={<a className="btn btn-small" href="#/settings/advanced" onClick={tabClick}>Open GPU settings</a>}>
          {gpuProblem}{gpuFix ? <> <b>What to do:</b> {gpuFix}</> : null}
        </Banner>
      )}
      <div onClickCapture={tabClick}>
        <LinkTabs label="Settings sections" current={t} tabs={[
          { id: "accounts", href: "#/settings", label: "Accounts" },
          { id: "defaults", href: "#/settings/defaults", label: "Defaults" },
          { id: "integrations", href: "#/settings/integrations", label: "Integrations" },
          { id: "advanced", href: "#/settings/advanced", label: "Advanced" },
        ]} />
      </div>
      {notes.length > 0 && (
        <Banner tone="warn" title="Some values were adjusted when saving">
          {notes.join(" ")}
        </Banner>
      )}

      <div key={form} className="stack-4">
        {t === "accounts" && (
          <AccountsTab c={c} accounts={accounts} setAccounts={setAccounts} changed={changed}
            saveKeys={(keys) => saveRef.current(keys)} />
        )}
        {t === "defaults" && (
          <>
            <DefaultsTab c={c} autopilotOn={st?.enabled ?? !!saved.autopilot_enabled}
              tz={String(saved.autopilot_timezone || "")} />
            <AppearancePanel />
          </>
        )}
        {t === "integrations" && <IntegrationsTab c={c} changed={changed} reload={load} />}
        {t === "advanced" && (
          <>
            <AdvancedTab c={c} health={health} st={st} />
            <DevLogPanel />
          </>
        )}
      </div>

      <section className="savebar" aria-label="Save settings">
        <div className="grow">
          <b className="small">{changed.length ? `Unsaved changes: ${what}` : justSaved ? "Saved" : "No changes"}</b>
          {changed.length > 0 && firstError && (
            <span className="error-text" role="alert">
              <Icon name="alert" className="sm" />
              <span>
                Fix the field marked{" "}
                {FIELDS[firstError].tab === t ? "below" : `on ${TAB_NAME[FIELDS[firstError].tab]}`} before saving:{" "}
                {FIELDS[firstError].label}.{" "}
                <button type="button" className="textlink" onClick={() => goToField(firstError)}>Go to it</button>
              </span>
            </span>
          )}
          {saveError && (
            <span className="error-text" role="alert"><Icon name="alert" className="sm" />{saveError}</span>
          )}
        </div>
        <button type="button" className="btn btn-quiet" disabled={!changed.length || saving} onClick={discard}>
          Discard
        </button>
        <button type="button" className="btn btn-primary" disabled={!changed.length || saving} onClick={() => save()}>
          {saving && <span className="inline-spinner" aria-hidden="true" />}Save settings
        </button>
      </section>
    </div>
  );
}

function AppearancePanel() {
  const { preferredReduceMotion, systemReducedMotion, persistent, setReduceMotion } = useMotion();
  return (
    <SettingsPanel id="appearance" title="Appearance" intro="Visual preferences apply immediately in this browser.">
      <SettingRow k="reduce_motion" label="Reduce motion"
        hint="Keep the robots and decorative movement still. Video previews play normally.">
        <Toggle id={fieldId("reduce_motion")} ariaLabel="Reduce motion" on={preferredReduceMotion}
          onChange={setReduceMotion} showState />
      </SettingRow>
      {systemReducedMotion && <p className="small muted">Your operating system also requests reduced motion, so
        animations stay still even with this switch off.</p>}
      <p className="tiny muted" role="status">{persistent
        ? "Saved for this browser. No need to press Save settings."
        : "Applied for this tab. Your browser prevented saving this preference."}</p>
    </SettingsPanel>
  );
}

// ------------------------------------------------------------------ Accounts
function AccountsTab({ c, accounts, setAccounts, changed, saveKeys }: {
  c: FieldCtx; accounts: Accounts | null; setAccounts: (a: Accounts) => void; changed: string[];
  saveKeys: (keys: string[]) => Promise<boolean>;
}) {
  return (
    <>
      <p className="small muted">
        Connect the platforms you want to post to. You sign in on Google's or TikTok's own page; ClipFoundry never sees
        your password. <b>Connecting an account doesn't let ClipFoundry post by itself.</b>
      </p>
      {(["youtube", "tiktok"] as const).map((p) => (
        <AccountPanel key={p} platform={p} c={c} account={accounts?.[p]} setAccounts={setAccounts}
          changed={changed.filter((k) => ACCOUNT_KEYS[p].includes(k))} saveKeys={saveKeys} />
      ))}
      {accounts?.protection && <p className="tiny faint">Sign-ins and app secrets are {accounts.protection}.</p>}
    </>
  );
}

function AccountPanel({ platform, c, account, setAccounts, changed, saveKeys }: {
  platform: Platform; c: FieldCtx; account?: PlatformAccount; setAccounts: (a: Accounts) => void; changed: string[];
  saveKeys: (keys: string[]) => Promise<boolean>;
}) {
  const yt = platform === "youtube";
  const name = PLATFORM_NAME[platform];
  const s = c.s;
  const idKey = yt ? "youtube_client_id" : "tiktok_client_key";
  const secretKey = yt ? "youtube_client_secret" : "tiktok_client_secret";
  const hasCodes = !!String(s[idKey] || "").trim() && !!String(s[secretKey] || "");
  const connected = !!account?.connected && !account.needs_reconnect;
  // Connecting uses the saved codes: save this account's changed fields first.
  const beforeConnect = hasCodes ? async () => {
    if (changed.length && !(await saveKeys(changed))) {
      throw new Error(`Save your ${name} app codes first: fix the field marked below.`);
    }
  } : undefined;
  const redirect = account?.redirect_uri || `${window.location.origin}/api/oauth/tiktok/callback`;
  const copy = () => {
    if (!navigator.clipboard) {
      toast("Copying is not available in this browser. Select the address and copy it.", true);
      return;
    }
    navigator.clipboard.writeText(redirect).then(() => toast("Redirect address copied"),
      () => toast("The address could not be copied. Select it and copy it.", true));
  };
  return (
    <section className="panel" aria-labelledby={`acc-${platform}`}>
      <div className="panel-head">
        <h2 id={`acc-${platform}`}>{name}</h2>
        <div className="row wrap">
          <AccountBadge platform={platform} account={account} />
          {account && (
            <ConnectButton platform={platform} account={account} onChange={setAccounts} beforeConnect={beforeConnect} />
          )}
        </div>
      </div>
      {account?.needs_reconnect && (
        <p className="small">
          {name} stopped accepting ClipFoundry's sign-in. Sign in again to keep posting. Planned posts wait until then.
        </p>
      )}
      {account?.restriction && account.configured && (
        <p className="small break"><Pill tone="warn" icon="alert">Note</Pill> {account.restriction}</p>
      )}
      {yt ? (
        <div className="stack">
          <span className="small strong">How posts get approved</span>
          <AutoPublishLine platform="youtube" />
        </div>
      ) : (
        <p className="small">
          How posts get approved: <b>your OK on each post</b>. TikTok's rules require a preview and your consent for
          every upload.
          {connected && account && <> Permissions: {account.can_direct_post ? "Direct Post" : "no Direct Post"} ·{" "}
            {account.can_inbox ? "send to inbox" : "no inbox"} ·{" "}
            {account.can_read_stats ? "video statistics" : "no video statistics"}.</>}
        </p>
      )}
      <Disclosure plain open={!!account && !account.configured}
        summary={`Your ${name} app codes${account?.configured ? "" : " (needed once)"}`}>
        <div className="stack-3">
          <p className="small muted">
            {name} only lets apps like ClipFoundry post through your own free developer app. Paste its two codes once.
          </p>
          <div className="field">
            <label htmlFor={fieldId(idKey)}>{yt ? "OAuth client ID" : "Client key"}</label>
            <TextInput k={idKey} c={c} placeholder={yt ? "1234567890-abc.apps.googleusercontent.com" : ""} />
          </div>
          <div className="field">
            <label htmlFor={fieldId(secretKey)}>
              Client secret <span className="hint">never shown again after saving</span>
            </label>
            <SecretField k={secretKey} c={c} />
          </div>
          {!yt && (
            <>
              <div className="field">
                <span className="label">Redirect address to register in your TikTok app</span>
                <div className="row wrap">
                  <code className="uri break grow">{redirect}</code>
                  <button type="button" className="btn btn-small" onClick={copy}><Icon name="copy" />Copy</button>
                </div>
              </div>
              <fieldset>
                <legend className="label">
                  Permissions to ask TikTok for <span className="hint">(used the next time you connect)</span>
                </legend>
                <Check k="tiktok_direct_post" c={c}>Direct Post (video.publish)</Check>
                <Check k="tiktok_read_stats" c={c}>Video statistics (video.list)</Check>
              </fieldset>
            </>
          )}
          <Check k={yt ? "youtube_project_verified" : "tiktok_app_audited"} c={c}>
            {yt ? "My Google Cloud project passed YouTube's API audit (tick only after Google approved it)"
              : "My TikTok app passed TikTok's Content Posting audit (tick only after TikTok approved it)"}
          </Check>
          {changed.length > 0 && (
            <p className="tiny muted">Not saved yet. Save with the bar below, or press Connect: it saves them first.</p>
          )}
          <Disclosure plain summary="How to get these codes (free, about 10 minutes)">
            {yt ? <YouTubeSetupSteps testingNote={account?.testing_note} /> : <TikTokSetupSteps />}
          </Disclosure>
        </div>
      </Disclosure>
    </section>
  );
}

// ------------------------------------------------------------------ Defaults
function DefaultsTab({ c, autopilotOn, tz }: { c: FieldCtx; autopilotOn: boolean; tz: string }) {
  const { s, set, errors } = c;
  // A count saved from elsewhere (Add video, More options) stays choosable instead of showing nothing selected.
  const counts = [3, 5, 10].includes(Number(s.clip_count)) ? [3, 5, 10]
    : [3, 5, 10, Number(s.clip_count)].sort((a, b) => a - b);
  return (
    <>
      <SettingsPanel id="def-clips" title="New clips"
        intro="Used for every new video. You can change them per video under Add video, More options.">
        <SettingRow k="clip_count" label="Clips per video" hint="At most; weak moments are skipped" group
          errors={errors}>
          <Seg k="clip_count" c={c} options={counts.map((n) => ({ value: n, label: String(n) }))} />
        </SettingRow>
        <SettingRow label="Clip length" hint="Seconds: the shortest, the longest, and the length to aim for" group>
          <div className="inline-fields small">
            <NumInput k="min_duration" c={c} label="Shortest clip in seconds" width={90} />
            <span>to</span>
            <NumInput k="max_duration" c={c} label="Longest clip in seconds" width={90} />
            <span>seconds, ideally</span>
            <NumInput k="target_duration" c={c} label="Ideal clip length in seconds" width={90} />
          </div>
          <Errors keys={["min_duration", "max_duration", "target_duration"]} errors={errors} />
        </SettingRow>
        <SettingRow label="Caption style" group>
          <StylePicker value={String(s.caption_style)} onChange={(v) => set({ caption_style: v })} />
        </SettingRow>
        <SettingRow k="caption_position" label="Caption position" group>
          <Seg k="caption_position" c={c}
            options={[{ value: "top", label: "Top" }, { value: "middle", label: "Middle" },
              { value: "bottom", label: "Bottom" }]} />
        </SettingRow>
        <SettingRow k="tracking" label="Framing" hint="How the 9:16 crop follows the action">
          <Select k="tracking" c={c} options={TRACKING.map((x) => ({ value: x.value, label: x.label }))} />
        </SettingRow>
        <SettingRow k="layout" label="Layout" group>
          <Seg k="layout" c={c}
            options={[{ value: "fill", label: "Fill (crop)" }, { value: "fit", label: "Fit (blurred background)" }]} />
        </SettingRow>
        <SettingRow k="silence" label="Silence cleanup" hint="Removes long pauses" group>
          <Seg k="silence" c={c}
            options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" },
              { value: "aggressive", label: "Strong" }]} />
        </SettingRow>
        <SettingRow label="Extras" group>
          <div className="stack" style={{ gap: 0 }}>
            <Check k="highlight_words" c={c}>Highlight each word as it's spoken</Check>
            <Check k="auto_zoom" c={c}>Auto-zoom on emphasized sentences</Check>
            <Check k="remove_fillers" c={c}>Cut filler words (with silence cleanup)</Check>
            <Check k="caption_emphasis" c={c}>Emphasize key words in their own color</Check>
            <Check k="hook_overlay" c={c}>Hook on screen at the start</Check>
            <Check k="normalize_audio" c={c}>Normalize loudness</Check>
          </div>
        </SettingRow>
      </SettingsPanel>

      <SettingsPanel id="def-ap" title="Autopilot">
        <SettingRow label="Autopilot" hint="Turned on and off on the Autopilot page" group>
          <span className="small">
            <Pill tone={autopilotOn ? "good" : "neutral"} icon={autopilotOn ? "check" : "dot"}>
              {autopilotOn ? "On" : "Off"}
            </Pill>{" "}
            <a className="textlink" href="#/missions">Open Autopilot</a>
          </span>
        </SettingRow>
        <SettingRow k="autopilot_daily_target" label="Daily target"
          hint="Clips a day to aim for. A target, not a quota: quality and your rights come first" errors={errors}>
          <NumInput k="autopilot_daily_target" c={c} />
        </SettingRow>
        <SettingRow label="Posting hours" hint={`Posts only between these hours${tz ? ` (${tz})` : ""}`} group>
          <div className="inline-fields small">
            <NumInput k="autopilot_active_start" c={c} label="Posting hours from (0 to 23)" width={90} />
            <span>to</span>
            <NumInput k="autopilot_active_end" c={c} label="Posting hours to (1 to 24)" width={90} />
            <span>o'clock</span>
          </div>
          <Errors keys={["autopilot_active_start", "autopilot_active_end"]} errors={errors} />
        </SettingRow>
        <SettingRow k="trend_topics" label="Topics to look for online"
          hint="Broad on purpose; a few are searched at a time (separate them with commas)">
          <textarea id={fieldId("trend_topics")} rows={3} value={String(s.trend_topics ?? "")}
            onChange={(e) => set({ trend_topics: e.target.value })} />
        </SettingRow>
        <p className="small muted">
          Everything else has a sensible default. It's under Advanced, but you don't need to change it.
        </p>
      </SettingsPanel>
    </>
  );
}

// ------------------------------------------------------------------ Advanced
function AdvancedTab({ c, health, st }: {
  c: FieldCtx; health: Health | null; st: ReturnType<typeof useStatus>["st"];
}) {
  const { s, set, errors } = c;
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const g = st?.gpu;
  const provider = String(s.ai_provider);
  const aiDirty = ["ai_provider", "ollama_url", "ollama_model", "openai_url", "openai_model", "openai_api_key",
    "anthropic_api_key", "anthropic_model"].some((k) => !same(s[k], c.saved?.[k]));
  const testAi = async () => {
    setChecking(true);
    try {
      setCheck(await api.checkAi());
    } catch (e) {
      setCheck({ ok: false, detail: errorText(e) });
    } finally {
      setChecking(false);
    }
  };
  const problem = g?.problem || health?.whisper.problem;
  const fix = g?.fix || health?.whisper.fix;
  const vram = g?.vram_mb ? ` · ${Math.round(g.vram_mb / 1024)} GB` : "";
  return (
    <>
      <SettingsPanel id="adv-gpu" title="Transcription and GPU">
        <div id="gpu" className="stack-3">
          {problem && (
            <Banner tone="bad" icon="cpu" title="GPU transcription is not working">
              {problem}{fix ? <> <b>What to do:</b> {fix}</> : null}
            </Banner>
          )}
          <dl className="kv">
            <dt>GPU</dt>
            <dd>{g ? (g.available ? `${g.name}${vram}` : "No NVIDIA GPU found")
              : health ? (health.cuda ? health.gpu.name : "No NVIDIA GPU found") : "Checking…"}</dd>
            <dt>Transcription now</dt>
            <dd>{health ? (health.whisper.mode === "gpu"
              ? `On the GPU (${health.whisper.model}, ${health.whisper.compute_type})`
              : `On the CPU: ${health.whisper.reason}`) : "Checking…"}</dd>
            {g?.last_transcription && (
              <><dt>Last transcription</dt><dd>{g.last_transcription.device.toUpperCase()}, {g.last_transcription.model}
                {g.last_transcription.warning ? ` · ${g.last_transcription.warning}` : ""}</dd></>
            )}
          </dl>
        </div>
        <SettingRow k="whisper_model" label="Whisper model" hint="auto = large-v3-turbo on the GPU, small on the CPU">
          <Select k="whisper_model" c={c} options={WHISPER_MODELS} />
        </SettingRow>
        <SettingRow k="whisper_device" label="Device" group>
          <Seg k="whisper_device" c={c}
            options={[{ value: "auto", label: "Auto" }, { value: "cuda", label: "GPU (CUDA)" },
              { value: "cpu", label: "CPU" }]} />
        </SettingRow>
        <SettingRow k="whisper_compute_type" label="Compute type">
          <Select k="whisper_compute_type" c={c} options={["auto", "float16", "int8_float16", "int8", "float32"]} />
        </SettingRow>
        <SettingRow k="whisper_beam_size" label="Beam size"
          hint="0 = automatic (5 on the GPU, 1 on the CPU). Higher is slower and slightly more accurate" errors={errors}
        >
          <NumInput k="whisper_beam_size" c={c} />
        </SettingRow>
        <SettingRow k="language" label="Language" hint="Leave empty to detect it">
          <TextInput k="language" c={c} placeholder="For example en, es, de" width={200} />
        </SettingRow>
        <SettingRow k="autopilot_allow_cpu_fallback" label="Allow CPU transcription in Autopilot"
          hint={"Off: if the GPU fails, Autopilot pauses and tells you why. Videos you add yourself always fall back "
            + "to the CPU, and say so"}>
          <Switch k="autopilot_allow_cpu_fallback" c={c} />
        </SettingRow>
        <SettingRow k="gpu_min_free_vram_mb" label="Free GPU memory needed"
          hint="Autopilot waits for this much free VRAM before transcribing (MB)" errors={errors}>
          <NumInput k="gpu_min_free_vram_mb" c={c} />
        </SettingRow>
        <SettingRow k="gpu_wait_minutes" label="Wait for the GPU up to"
          hint="Minutes; then the job waits and tries later" errors={errors}>
          <NumInput k="gpu_wait_minutes" c={c} />
        </SettingRow>
      </SettingsPanel>

      <AutopilotSettings s={s} set={set} errors={errors} saved={c.saved} />

      <SettingsPanel id="adv-brain" title="Brain (learning)"
        intro={<>How carefully ClipFoundry learns from your viewers' results. These are lower limits: it never learns
          from fewer than 30 clips or changes a value by more than 10% at once. Pause, reset and roll back are in the
          Office's <a className="textlink" href="#/">Brain Room</a>.</>}>
        <SettingRow k="brain_min_clips" label="Clips before any change" errors={errors}
          hint="Mature clips in one comparable audience before a strategy may change (30 to 1,000)">
          <NumInput k="brain_min_clips" c={c} />
        </SettingRow>
        <SettingRow k="brain_max_step" label="Largest step" errors={errors}
          hint="The most one update may change a value, as a fraction (0.01 to 0.10, that is 1% to 10%)">
          <NumInput k="brain_max_step" c={c} step={0.01} />
        </SettingRow>
        <SettingRow k="brain_min_views" label="Views for a reading" errors={errors}
          hint="A platform reading counts once a clip has this many views">
          <NumInput k="brain_min_views" c={c} />
        </SettingRow>
        <SettingRow k="brain_min_testers" label="Testers for a reading" errors={errors}
          hint="...or once this many different testers rated it">
          <NumInput k="brain_min_testers" c={c} />
        </SettingRow>
      </SettingsPanel>

      <SettingsPanel id="adv-render" title="Rendering, AI scoring and system">
        <SettingRow k="encoder" label="Video encoder"
          hint={health ? (health.nvenc ? "NVENC is available" : "NVENC is not available on this PC") : undefined} group>
          <Seg k="encoder" c={c}
            options={[{ value: "auto", label: "Auto" }, { value: "nvenc", label: "NVIDIA NVENC" },
              { value: "x264", label: "x264 (CPU)" }]} />
        </SettingRow>
        <SettingRow k="crf" label="Quality (CRF)" hint="Lower = better quality and bigger files (10 to 35)"
          errors={errors}>
          <NumInput k="crf" c={c} />
        </SettingRow>
        <SettingRow k="x264_preset" label="x264 preset">
          <Select k="x264_preset" c={c}
            options={["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"]} />
        </SettingRow>
        <SettingRow k="max_fps" label="Max frame rate" group>
          <Seg k="max_fps" c={c} options={[{ value: 30, label: "30" }, { value: 60, label: "60" }]} />
        </SettingRow>
        <SettingRow k="ffmpeg_path" label="FFmpeg location" hint="Optional: the folder or path of ffmpeg.exe">
          <TextInput k="ffmpeg_path" c={c}
            placeholder={health?.ffmpeg || "Found automatically (PATH or tools/ffmpeg/bin)"} />
        </SettingRow>
        <SettingRow k="min_score" label="Minimum Viral Potential" errors={errors}
          hint={"Only clips at or above this estimate (0 to 100), and without blocking problems such as a misleading "
            + "cut, are shown. No filler is added"}>
          <NumInput k="min_score" c={c} />
        </SettingRow>
        <SettingRow k="hook_seconds" label="Hook length" hint="Seconds the hook stays on screen at the start (0 to 10)"
          errors={errors}>
          <NumInput k="hook_seconds" c={c} step={0.5} />
        </SettingRow>
        <SettingRow k="ai_provider" label="AI scoring"
          hint={"Stage 1 always runs locally. Stage 2 re-scores only the strongest candidates. Ollama and LM Studio "
            + "are free; the Claude API is paid per use"}>
          <Select k="ai_provider" c={c} options={[
            { value: "heuristic", label: "Local heuristic (offline, free)" },
            { value: "ollama", label: "Ollama (local AI, free)" },
            { value: "openai_compatible", label: "LM Studio or another OpenAI-compatible local server" },
            { value: "anthropic", label: "Claude API (optional, paid)" },
            { value: "nvidia", label: "NVIDIA AI (optional; set it up under Integrations)" },
          ]} />
        </SettingRow>
        {provider === "nvidia" && (
          <p className="small muted">
            NVIDIA AI is set up, agreed to and tested under{" "}
            <a className="textlink" href="#/settings/integrations">Settings → Integrations</a>. Without that
            agreement nothing is sent and the local analysis is used.
          </p>
        )}
        {provider === "ollama" && (
          <>
            <SettingRow k="ollama_url" label="Ollama address"><TextInput k="ollama_url" c={c} /></SettingRow>
            <SettingRow k="ollama_model" label="Ollama model" hint="For example llama3.1:8b or qwen2.5:7b">
              <TextInput k="ollama_model" c={c} />
            </SettingRow>
          </>
        )}
        {provider === "openai_compatible" && (
          <>
            <SettingRow k="openai_url" label="Server address"><TextInput k="openai_url" c={c} /></SettingRow>
            <SettingRow k="openai_model" label="Server model"><TextInput k="openai_model" c={c} /></SettingRow>
            <SettingRow k="openai_api_key" label="Server API key" hint="Usually not needed for local servers">
              <SecretField k="openai_api_key" c={c} removable />
            </SettingRow>
          </>
        )}
        {provider === "anthropic" && (
          <>
            <SettingRow k="anthropic_api_key" label="Claude API key" hint="Paid per use; stored on this PC only">
              <SecretField k="anthropic_api_key" c={c} removable placeholder="sk-ant-…" />
            </SettingRow>
            <SettingRow k="anthropic_model" label="Claude model"
              hint="For example claude-opus-5, claude-sonnet-5, or claude-haiku-4-5 (cheapest)">
              <TextInput k="anthropic_model" c={c} />
            </SettingRow>
          </>
        )}
        <SettingRow k="ai_max_candidates" label="Max candidates"
          hint="How many candidates per video stage 2 re-scores; caps paid calls (1 to 30)" errors={errors}>
          <NumInput k="ai_max_candidates" c={c} />
        </SettingRow>
        <div className="row wrap" style={{ paddingBottom: 8 }}>
          <button type="button" className="btn" aria-disabled={aiDirty || checking || undefined}
            onClick={() => (aiDirty ? toast("Save the AI scoring settings first: the test uses the saved ones.", true)
              : !checking && testAi())}>
            {checking ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="refresh" />}Test connection
          </button>
          {aiDirty && <span className="tiny muted">Save first: the test uses the saved settings.</span>}
          {check && <Pill tone={check.ok ? "good" : "bad"} icon={check.ok ? "check" : "alert"}>{check.detail}</Pill>}
        </div>
        <h3 style={{ fontSize: "var(--fs-h3)", paddingTop: 8 }}>System</h3>
        {health ? (
          <dl className="kv">
            <dt>Version</dt><dd>{health.version}</dd>
            <dt>FFmpeg</dt><dd>{health.ffmpeg || "Not found"}</dd>
            <dt>Whisper</dt>
            <dd>{health.whisper.model} · {health.whisper.device} · {health.whisper.compute_type}{" "}
              {health.whisper.cached ? "(downloaded)" : "(downloads on first use)"}</dd>
            <dt>Data folder</dt><dd><code className="break">{health.data_dir}</code></dd>
          </dl>
        ) : <p className="small muted">Reading the system details…</p>}
      </SettingsPanel>
    </>
  );
}
