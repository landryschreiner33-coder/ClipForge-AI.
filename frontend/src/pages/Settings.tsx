import { ReactNode, useEffect, useState } from "react";
import { Accounts, api, Health, Settings } from "../api";
import { Icon, Segmented, StylePicker, Toggle, TRACKING, toast } from "../components/ui";
import { AccountBadge, ConnectButton } from "../components/accounts";

const WHISPER_MODELS = ["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"];

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="opt-row">
      <div className="lbl">{label}{hint && <small>{hint}</small>}</div>
      <div>{children}</div>
    </div>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState<Settings | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [dirty, setDirty] = useState(false);
  const [check, setCheck] = useState<{ ok: boolean; detail: string } | null>(null);
  const [accounts, setAccounts] = useState<Accounts | null>(null);

  useEffect(() => {
    api.settings().then(setS);
    api.health().then(setHealth).catch(() => undefined);
    api.accounts().then(setAccounts).catch(() => undefined);
  }, []);
  if (!s) return <div className="page"><div className="spinner" /></div>;

  const set = (patch: Settings) => {
    setS({ ...s, ...patch });
    setDirty(true);
  };
  const save = async (quiet = false) => {
    try {
      setS(await api.saveSettings(s));
      setDirty(false);
      setHealth(await api.health());
      setAccounts(await api.accounts());
      if (!quiet) toast("Settings saved");
    } catch (e) {
      toast((e as Error).message, true);
    }
  };
  const testAi = async () => {
    if (dirty) await save();
    setCheck(await api.checkAi());
  };

  const provider = s.ai_provider as string;

  return (
    <div className="page" style={{ maxWidth: 980 }}>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Defaults for new projects. Everything is stored locally in <code>{health?.data_dir || "data/"}</code>.</p>
        </div>
        <button className="btn primary" disabled={!dirty} onClick={() => save()}><Icon name="check" size={16} /> Save settings</button>
      </div>

      <div className="card">
        <h3>Transcription (faster-whisper, local)</h3>
        <Row label="Model" hint="auto = large-v3-turbo on GPU, small on CPU">
          <select value={s.whisper_model} onChange={(e) => set({ whisper_model: e.target.value })}>
            {WHISPER_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </Row>
        <Row label="Device" hint={health ? (health.whisper.mode === "gpu"
          ? `GPU mode: ${health.gpu.name} (CUDA, ${health.whisper.compute_type})`
          : `CPU mode: ${health.whisper.reason}`) : ""}>
          <Segmented value={s.whisper_device} onChange={(v) => set({ whisper_device: v })}
            options={[{ value: "auto", label: "Auto" }, { value: "cuda", label: "GPU (CUDA)" }, { value: "cpu", label: "CPU" }]} />
        </Row>
        <Row label="Compute type">
          <select value={s.whisper_compute_type} onChange={(e) => set({ whisper_compute_type: e.target.value })}>
            {["auto", "float16", "int8_float16", "int8", "float32"].map((m) => <option key={m}>{m}</option>)}
          </select>
        </Row>
        <Row label="Language" hint="Leave empty to auto-detect">
          <input type="text" placeholder="e.g. en, es, de" value={s.language} onChange={(e) => set({ language: e.target.value })} />
        </Row>
      </div>

      <div className="card">
        <h3>Clip discovery</h3>
        <Row label="Clips per video" hint="Maximum; weaker moments are dropped">
          <Segmented value={s.clip_count} onChange={(v) => set({ clip_count: v })} options={[3, 5, 10].map((n) => ({ value: n, label: n }))} />
        </Row>
        <Row label="Clip length (seconds)">
          <div className="row">
            <input type="number" value={s.min_duration} onChange={(e) => set({ min_duration: +e.target.value })} />
            <span className="muted">to</span>
            <input type="number" value={s.max_duration} onChange={(e) => set({ max_duration: +e.target.value })} />
            <span className="muted">target</span>
            <input type="number" value={s.target_duration} onChange={(e) => set({ target_duration: +e.target.value })} />
          </div>
        </Row>
        <Row label="Minimum Viral Potential" hint="Only clips at or above this (and without blocking problems such as a misleading cut) are shown. No filler is added.">
          <div className="row"><input type="range" min={0} max={90} step={5} value={s.min_score} onChange={(e) => set({ min_score: +e.target.value })} /><b style={{ width: 30 }}>{s.min_score}</b></div>
        </Row>
      </div>

      <div className="card">
        <h3>AI scoring (Stage 2)</h3>
        <div className="notice">
          <Icon name="cpu" size={16} />
          <div>
            Stage 1 always runs locally. Stage 2 re-scores only the strongest candidates. <b>Local heuristic</b> is free and
            offline; <b>Ollama</b> / <b>LM Studio</b> run a local LLM for free; <b>Claude API</b> is optional and paid per use.
          </div>
        </div>
        <Row label="Provider">
          <select value={provider} onChange={(e) => { set({ ai_provider: e.target.value }); setCheck(null); }}>
            <option value="heuristic">Local heuristic (offline, free)</option>
            <option value="ollama">Ollama (local LLM, free)</option>
            <option value="openai_compatible">LM Studio / OpenAI-compatible local server</option>
            <option value="anthropic">Claude API (optional, paid)</option>
          </select>
        </Row>
        {provider === "ollama" && (
          <>
            <Row label="Ollama URL"><input type="text" value={s.ollama_url} onChange={(e) => set({ ollama_url: e.target.value })} /></Row>
            <Row label="Model" hint="e.g. llama3.1:8b, qwen2.5:7b"><input type="text" value={s.ollama_model} onChange={(e) => set({ ollama_model: e.target.value })} /></Row>
          </>
        )}
        {provider === "openai_compatible" && (
          <>
            <Row label="Server URL"><input type="text" value={s.openai_url} onChange={(e) => set({ openai_url: e.target.value })} /></Row>
            <Row label="Model"><input type="text" value={s.openai_model} onChange={(e) => set({ openai_model: e.target.value })} /></Row>
            <Row label="API key" hint="Usually not needed for local servers"><input type="password" value={s.openai_api_key} onChange={(e) => set({ openai_api_key: e.target.value })} /></Row>
          </>
        )}
        {provider === "anthropic" && (
          <>
            <Row label="API key" hint="Stored locally in your SQLite database"><input type="password" value={s.anthropic_api_key} onChange={(e) => set({ anthropic_api_key: e.target.value })} /></Row>
            <Row label="Model" hint="e.g. claude-opus-5, claude-sonnet-5, claude-haiku-4-5 (cheapest)"><input type="text" value={s.anthropic_model} onChange={(e) => set({ anthropic_model: e.target.value })} /></Row>
            <Row label="Max candidates" hint="Caps paid calls per video"><input type="number" min={1} max={30} value={s.ai_max_candidates} onChange={(e) => set({ ai_max_candidates: +e.target.value })} /></Row>
          </>
        )}
        <div className="row mt">
          <button className="btn" onClick={testAi}><Icon name="refresh" size={14} /> Test connection</button>
          {check && <span className={`badge ${check.ok ? "good" : "bad"}`}>{check.detail}</span>}
        </div>
      </div>

      <div className="card" id="publishing">
        <h3>Publishing (YouTube Shorts and TikTok)</h3>
        <div className="notice">
          <Icon name="link" size={16} />
          <div>
            ClipFoundry publishes only through the official YouTube Data API and TikTok Content Posting API, with your own
            free developer apps. You sign in on Google's or TikTok's own page: ClipFoundry never sees or stores your
            password. The access tokens it receives are {accounts?.protection || "stored locally"}. Nothing is posted
            until you press a Publish button and confirm.
          </div>
        </div>

        <div className="platform-head">
          <b>YouTube Shorts</b>
          <AccountBadge platform="youtube" account={accounts?.youtube} />
          <span style={{ flex: 1 }} />
          <ConnectButton platform="youtube" account={accounts?.youtube} onChange={setAccounts}
            beforeConnect={s.youtube_client_id && s.youtube_client_secret ? (dirty ? () => save(true) : async () => undefined) : undefined} />
        </div>
        <Row label="OAuth client ID" hint="Google Cloud → Credentials → OAuth client (Desktop app)">
          <input type="text" placeholder="1234567890-abc.apps.googleusercontent.com" value={s.youtube_client_id} onChange={(e) => set({ youtube_client_id: e.target.value })} />
        </Row>
        <Row label="OAuth client secret" hint="Stored encrypted on Windows">
          <input type="password" value={s.youtube_client_secret} onChange={(e) => set({ youtube_client_secret: e.target.value })} />
        </Row>
        <Row label="API audit" hint="Only tick this after Google approved your project">
          <Toggle on={!!s.youtube_project_verified} onChange={(v) => set({ youtube_project_verified: v })}
            label="My Google Cloud project passed YouTube's API audit (public uploads allowed)" />
        </Row>
        {accounts?.youtube.restriction && <div className="notice warn small block">{accounts.youtube.restriction}</div>}
        <details className="setup">
          <summary>How to set up YouTube publishing (free, about 10 minutes)</summary>
          <ol>
            <li>Open <b>console.cloud.google.com</b> and create a project (any name).</li>
            <li><b>APIs &amp; Services → Library</b>: enable <b>YouTube Data API v3</b>. Optional: also enable <b>YouTube Analytics API</b> so ClipFoundry can read watch time and retention of your videos.</li>
            <li><b>OAuth consent screen</b>: choose <i>External</i>, fill in the app name and your e-mail, and add your Google account under <i>Test users</i>.</li>
            <li><b>Credentials → Create credentials → OAuth client ID</b>, application type <b>Desktop app</b>. Copy the client ID and client secret into the fields above and save.</li>
            <li>Click <b>CONNECT YOUTUBE</b>, sign in with Google and allow access. Google may show “Google hasn't verified this app”: that is your own app, choose <i>Continue</i>.</li>
          </ol>
          <p className="small muted">{accounts?.youtube.testing_note}</p>
          <p className="small muted">
            Until Google audits your project, YouTube keeps every upload from it Private. Private uploads are fine for
            testing. Uploads count against your project's daily YouTube API quota.
          </p>
        </details>

        <div className="platform-head">
          <b>TikTok</b>
          <AccountBadge platform="tiktok" account={accounts?.tiktok} />
          <span style={{ flex: 1 }} />
          <ConnectButton platform="tiktok" account={accounts?.tiktok} onChange={setAccounts}
            beforeConnect={s.tiktok_client_key && s.tiktok_client_secret ? (dirty ? () => save(true) : async () => undefined) : undefined} />
        </div>
        {accounts?.tiktok?.connected && (
          <div className="small muted" style={{ marginBottom: 6 }}>
            Permissions: {accounts.tiktok.can_direct_post ? "Direct Post" : "no Direct Post"} ·{" "}
            {accounts.tiktok.can_inbox ? "upload to inbox" : "no inbox upload"} ·{" "}
            {accounts.tiktok.can_read_stats ? "video statistics" : "no statistics"}
          </div>
        )}
        <Row label="Client key" hint="developers.tiktok.com → your app">
          <input type="text" value={s.tiktok_client_key} onChange={(e) => set({ tiktok_client_key: e.target.value })} />
        </Row>
        <Row label="Client secret" hint="Stored encrypted on Windows">
          <input type="password" value={s.tiktok_client_secret} onChange={(e) => set({ tiktok_client_secret: e.target.value })} />
        </Row>
        <Row label="Redirect URI" hint="Register exactly this in your TikTok app (Login Kit → Desktop)">
          <div className="row">
            <code className="uri">{accounts?.tiktok?.redirect_uri || "http://127.0.0.1:8765/api/oauth/tiktok/callback"}</code>
            <button className="btn sm" type="button" onClick={() => {
              navigator.clipboard?.writeText(accounts?.tiktok?.redirect_uri || "").then(() => toast("Redirect URI copied"));
            }}>Copy</button>
          </div>
        </Row>
        <Row label="Permissions to request" hint="Each must be enabled for your TikTok app">
          <div className="row wrap" style={{ gap: 18 }}>
            <Toggle on={!!s.tiktok_direct_post} onChange={(v) => set({ tiktok_direct_post: v })} label="Direct Post (video.publish)" />
            <Toggle on={!!s.tiktok_read_stats} onChange={(v) => set({ tiktok_read_stats: v })} label="Video statistics (video.list)" />
          </div>
        </Row>
        <Row label="App audit" hint="Only tick this after TikTok approved your app">
          <Toggle on={!!s.tiktok_app_audited} onChange={(v) => set({ tiktok_app_audited: v })}
            label="My TikTok app passed TikTok's Content Posting audit" />
        </Row>
        {accounts?.tiktok?.restriction && <div className="notice warn small block">{accounts.tiktok.restriction}</div>}
        <details className="setup">
          <summary>How to set up TikTok publishing (free)</summary>
          <ol>
            <li>Sign in at <b>developers.tiktok.com</b> and create an app (any name, category "Video").</li>
            <li>Add the products <b>Login Kit</b> (platform <i>Desktop</i>) and <b>Content Posting API</b>. In Content Posting API, turn on <b>Direct Post</b> if you want to post directly.</li>
            <li>Add the scopes <code>user.info.basic</code>, <code>video.upload</code>, <code>video.publish</code> (Direct Post) and <code>video.list</code> (statistics).</li>
            <li>In Login Kit, register the redirect URI shown above. If you start ClipFoundry on another port, register that port too.</li>
            <li>Add your TikTok account as a <b>target user</b> (sandbox) while the app is not reviewed, paste the client key and secret above and save.</li>
            <li>Click <b>CONNECT TIKTOK</b>, sign in on TikTok's page and allow access.</li>
          </ol>
          <p className="small muted">
            Until TikTok audits your app, Direct Post only works when your TikTok account is private, every post is
            “Only me”, and at most 5 users can post per day. <b>Send to TikTok inbox</b> works without the audit: the
            video arrives as a draft in the TikTok app and you post it from there. You can also export the clip and
            upload it on tiktok.com/tiktokstudio/upload.
          </p>
        </details>
      </div>

      <div className="card">
        <h3>Rendering defaults</h3>
        <Row label="Caption style"><StylePicker value={s.caption_style} onChange={(v) => set({ caption_style: v })} /></Row>
        <Row label="Caption position">
          <Segmented value={s.caption_position} onChange={(v) => set({ caption_position: v })}
            options={[{ value: "top", label: "Top" }, { value: "middle", label: "Middle" }, { value: "bottom", label: "Bottom" }]} />
        </Row>
        <Row label="Word highlight"><Toggle on={s.highlight_words} onChange={(v) => set({ highlight_words: v })} /></Row>
        <Row label="Tracking">
          <select value={s.tracking} onChange={(e) => set({ tracking: e.target.value })}>
            {TRACKING.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </Row>
        <Row label="Layout">
          <Segmented value={s.layout} onChange={(v) => set({ layout: v })}
            options={[{ value: "fill", label: "Fill (crop)" }, { value: "fit", label: "Fit (blurred bg)" }]} />
        </Row>
        <Row label="Silence cleanup">
          <Segmented value={s.silence} onChange={(v) => set({ silence: v })}
            options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" }, { value: "aggressive", label: "Aggressive" }]} />
        </Row>
        <Row label="Extras">
          <div className="row wrap" style={{ gap: 20 }}>
            <Toggle on={s.auto_zoom} onChange={(v) => set({ auto_zoom: v })} label="Auto-zoom" />
            <Toggle on={s.remove_fillers} onChange={(v) => set({ remove_fillers: v })} label="Cut filler words" />
            <Toggle on={s.caption_emphasis} onChange={(v) => set({ caption_emphasis: v })} label="Emphasize key words" />
            <Toggle on={s.hook_overlay} onChange={(v) => set({ hook_overlay: v })} label="Hook overlay" />
            <Toggle on={s.normalize_audio} onChange={(v) => set({ normalize_audio: v })} label="Normalize audio" />
          </div>
        </Row>
        <Row label="Video encoder" hint={health ? (health.nvenc ? "NVENC available" : "NVENC not available") : ""}>
          <Segmented value={s.encoder} onChange={(v) => set({ encoder: v })}
            options={[{ value: "auto", label: "Auto" }, { value: "nvenc", label: "NVIDIA NVENC" }, { value: "x264", label: "x264 (CPU)" }]} />
        </Row>
        <Row label="Quality (CRF)" hint="Lower = better quality, bigger files">
          <div className="row"><input type="range" min={14} max={30} value={s.crf} onChange={(e) => set({ crf: +e.target.value })} /><b style={{ width: 30 }}>{s.crf}</b></div>
        </Row>
        <Row label="x264 preset">
          <select value={s.x264_preset} onChange={(e) => set({ x264_preset: e.target.value })}>
            {["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"].map((p) => <option key={p}>{p}</option>)}
          </select>
        </Row>
        <Row label="Max frame rate"><Segmented value={s.max_fps} onChange={(v) => set({ max_fps: v })} options={[{ value: 30, label: "30" }, { value: 60, label: "60" }]} /></Row>
        <Row label="FFmpeg location" hint="Optional: folder or path of ffmpeg.exe">
          <input type="text" placeholder={health?.ffmpeg || "auto-detect (PATH or tools/ffmpeg/bin)"} value={s.ffmpeg_path} onChange={(e) => set({ ffmpeg_path: e.target.value })} />
        </Row>
      </div>

      {health && (
        <div className="card">
          <h3>System</h3>
          <div className="kv">
            <span className="k">Version</span><span>{health.version}</span>
            <span className="k">FFmpeg</span><span>{health.ffmpeg || "not found"}</span>
            <span className="k">Whisper</span><span>{health.whisper.model} · {health.whisper.device} · {health.whisper.compute_type} {health.whisper.cached ? "(downloaded)" : "(downloads on first use)"}</span>
            <span className="k">Data folder</span><span>{health.data_dir}</span>
          </div>
        </div>
      )}
    </div>
  );
}
