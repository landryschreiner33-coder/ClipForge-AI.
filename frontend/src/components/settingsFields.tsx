import { ReactNode, useState } from "react";
import { Settings } from "../api";
import { Icon, Segmented, Toggle } from "./ui";

/**
 * Building blocks of the Settings page: one row per setting (label, one-line hint, control, field error), the field
 * table (label and tab of every key, used by the save bar and to point at an invalid field) and validation.
 */

export type SettingsTab = "accounts" | "defaults" | "integrations" | "advanced";
export type FieldCtx = {
  s: Settings; set: (patch: Settings) => void; errors?: Record<string, string>; saved?: Settings;
};

/** Every key the page edits: its short name (for "Unsaved changes: …") and where it lives. */
export const FIELDS: Record<string, { label: string; tab: SettingsTab }> = {};
const add = (tab: SettingsTab, entries: Record<string, string>) => {
  for (const [k, label] of Object.entries(entries)) FIELDS[k] = { label, tab };
};
add("accounts", {
  youtube_client_id: "YouTube client ID", youtube_client_secret: "YouTube client secret",
  youtube_project_verified: "YouTube audit", tiktok_client_key: "TikTok client key",
  tiktok_client_secret: "TikTok client secret", tiktok_direct_post: "TikTok Direct Post permission",
  tiktok_read_stats: "TikTok statistics permission", tiktok_app_audited: "TikTok audit",
});
add("defaults", {
  clip_count: "Clips per video", min_duration: "Shortest clip", max_duration: "Longest clip",
  target_duration: "Ideal clip length", caption_style: "Caption style", caption_position: "Caption position",
  highlight_words: "Word highlight", tracking: "Framing", layout: "Layout", silence: "Silence cleanup",
  auto_zoom: "Auto-zoom", remove_fillers: "Cut filler words", caption_emphasis: "Emphasize key words",
  hook_overlay: "Hook on screen", normalize_audio: "Normalize loudness", autopilot_daily_target: "Daily target",
  autopilot_active_start: "Posting hours (from)", autopilot_active_end: "Posting hours (to)", trend_topics: "Topics",
});
add("advanced", {
  whisper_model: "Whisper model", whisper_device: "Transcription device", whisper_compute_type: "Compute type",
  whisper_beam_size: "Beam size", language: "Language", autopilot_allow_cpu_fallback: "CPU transcription in Autopilot",
  gpu_min_free_vram_mb: "Free GPU memory needed", gpu_wait_minutes: "Wait for the GPU",
  autopilot_timezone: "Time zone", autopilot_keep_awake: "Keep the PC awake",
  autopilot_sources_per_day: "Sources per day", autopilot_clips_per_source: "Clips per source",
  autopilot_min_quality: "Minimum clip quality", autopilot_youtube: "Post to YouTube",
  autopilot_tiktok: "Post to TikTok",
  autopilot_auto_schedule: "Automatic scheduling", autopilot_dynamic_replacement: "Replace weaker planned posts",
  autopilot_replacement_threshold: "Replacement margin", autopilot_replacement_cooldown_hours: "Replacement cooldown",
  autopilot_live_monitoring: "Live monitoring", autopilot_learning: "Learning", autopilot_process: "Worker process",
  autopilot_max_source_gb: "Largest source (GB)", autopilot_max_source_minutes: "Largest source (minutes)",
  autopilot_min_gap_minutes: "Minimum gap", autopilot_youtube_daily_limit: "YouTube posts a day",
  autopilot_tiktok_daily_limit: "TikTok posts a day", autopilot_youtube_privacy: "Suggested YouTube visibility",
  autopilot_upload_lead_minutes: "Upload YouTube posts early",
  autopilot_auto_publish: "Publish approved posts at their time",
  autopilot_allow_republish: "Allow republishing", youtube_category_id: "YouTube category",
  trend_region: "Region", trend_language: "Language for discovery", trend_poll_minutes: "Check trends every",
  trend_max_age_hours: "Video age", youtube_api_key: "YouTube Data API key",
  discovery_require_topic_match: "Require a topic match", discovery_excluded_topics: "Topics to skip",
  discovery_audience_terms: "Audience context clues", discovery_min_source_score: "Minimum discovery estimate",
  discovery_require_complete_clips: "Require a complete story",
  youtube_derived_metrics_approved: "Derived metrics approval", tavily_api_key: "Web search key",
  tavily_free_credits: "Web search credits", discovery_monthly_budget_usd: "Monthly cost limit",
  library_discovery: "Free-license library", rights_auto_licensed: "Licensed sources",
  rights_auto_allowlisted: "Allowlisted sources", rights_auto_creative_commons: "Creative Commons sources",
  rights_auto_public_domain: "Public domain sources", autopilot_commercial_use: "My posts are commercial",
  rights_ask_per_video: "Ask about uncovered videos", rights_allow_remote_download: "Download authorized sources",
  youtube_quota_default: "Quota: units", youtube_quota_uploads: "Quota: uploads",
  youtube_quota_search: "Quota: searches",
  youtube_discovery_share: "Discovery share of units", youtube_search_discovery_share: "Discovery share of searches",
  encoder: "Video encoder", crf: "Quality (CRF)", x264_preset: "x264 preset", max_fps: "Frame rate",
  ffmpeg_path: "FFmpeg location", min_score: "Minimum Viral Potential", hook_seconds: "Hook length",
  ai_provider: "AI scoring", ai_max_candidates: "Max candidates", ollama_url: "Ollama address",
  ollama_model: "Ollama model", openai_url: "Server address", openai_model: "Server model",
  openai_api_key: "Server API key", anthropic_api_key: "Claude API key", anthropic_model: "Claude model",
  brain_min_clips: "Brain: clips before a change", brain_max_step: "Brain: largest step",
  brain_min_views: "Brain: views per reading", brain_min_testers: "Brain: testers per clip",
});

add("integrations", {
  nvidia_enabled: "Use NVIDIA AI", nvidia_api_key: "NVIDIA API key", nvidia_model: "NVIDIA model",
  nvidia_mode: "NVIDIA mode", nvidia_production_url: "NVIDIA endpoint", nvidia_daily_requests: "NVIDIA requests a day",
  nvidia_daily_tokens: "NVIDIA tokens a day", nvidia_max_input_tokens: "NVIDIA text per request",
  nvidia_max_output_tokens: "NVIDIA longest answer", nvidia_timeout_s: "NVIDIA timeout",
  nvidia_price_per_mtok_usd: "NVIDIA price", nvidia_daily_spend_cap_usd: "NVIDIA spending cap",
});

// The server's ranges (config.py _RANGES and validate_settings), so a value is never silently clamped on save.
const RANGES: Record<string, [number, number]> = {
  clip_count: [1, 20], min_duration: [5, 180], max_duration: [5, 180], target_duration: [5, 180], crf: [10, 35],
  max_fps: [15, 60], min_score: [0, 100], ai_max_candidates: [1, 30], whisper_beam_size: [0, 10], hook_seconds: [0, 10],
  autopilot_daily_target: [1, 100], autopilot_sources_per_day: [1, 30], autopilot_clips_per_source: [1, 10],
  autopilot_min_quality: [0, 100], autopilot_replacement_threshold: [0, 500],
  autopilot_replacement_cooldown_hours: [0, 168], autopilot_active_start: [0, 23], autopilot_active_end: [1, 24],
  autopilot_min_gap_minutes: [0, 1440], autopilot_youtube_daily_limit: [0, 100], autopilot_tiktok_daily_limit: [0, 100],
  autopilot_upload_lead_minutes: [5, 720], autopilot_max_source_gb: [0.5, 200], autopilot_max_source_minutes: [5, 1440],
  trend_poll_minutes: [15, 1440], trend_max_age_hours: [6, 720], youtube_quota_default: [0, 10_000_000],
  discovery_min_source_score: [0, 100],
  youtube_quota_uploads: [0, 100_000], youtube_quota_search: [0, 100_000], youtube_discovery_share: [0, 90],
  youtube_search_discovery_share: [0, 100], gpu_min_free_vram_mb: [0, 48_000], gpu_wait_minutes: [1, 720],
  tavily_free_credits: [0, 1_000_000], discovery_monthly_budget_usd: [0, 1000],
  nvidia_daily_requests: [0, 5000], nvidia_daily_tokens: [0, 5_000_000], nvidia_max_input_tokens: [500, 32000],
  nvidia_max_output_tokens: [100, 4000], nvidia_timeout_s: [5, 300], nvidia_price_per_mtok_usd: [-1, 1000],
  nvidia_daily_spend_cap_usd: [0, 1000],
  brain_min_clips: [30, 1000], brain_max_step: [0.01, 0.1], brain_min_views: [1, 100_000], brain_min_testers: [2, 100],
};
const INTEGER = new Set([
  "clip_count", "crf", "max_fps", "ai_max_candidates", "whisper_beam_size", "autopilot_daily_target",
  "autopilot_sources_per_day", "autopilot_clips_per_source", "autopilot_active_start", "autopilot_active_end",
  "autopilot_min_gap_minutes", "autopilot_youtube_daily_limit", "autopilot_tiktok_daily_limit",
  "autopilot_upload_lead_minutes", "autopilot_max_source_minutes", "trend_poll_minutes", "trend_max_age_hours",
  "youtube_quota_default", "youtube_quota_uploads", "youtube_quota_search", "youtube_discovery_share",
  "youtube_search_discovery_share", "gpu_min_free_vram_mb", "gpu_wait_minutes", "tavily_free_credits",
  "nvidia_daily_requests", "nvidia_daily_tokens", "nvidia_max_input_tokens", "nvidia_max_output_tokens",
  "brain_min_clips", "brain_min_views", "brain_min_testers",
]);

export function validTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return !!tz.trim();
  } catch {
    return false;
  }
}

/** Field errors that block saving, in plain words, keyed by setting. */
export function validate(s: Settings): Record<string, string> {
  const e: Record<string, string> = {};
  for (const [k, [lo, hi]] of Object.entries(RANGES)) {
    if (!(k in s)) continue;
    const v = s[k];
    if (v === "" || v === null || typeof v !== "number" || !Number.isFinite(v)) e[k] = "Enter a number.";
    else if (INTEGER.has(k) && !Number.isInteger(v)) e[k] = "Enter a whole number.";
    else if (v < lo || v > hi) {
      e[k] = `Enter a number from ${lo.toLocaleString("en-US")} to ${hi.toLocaleString("en-US")}.`;
    }
  }
  const n = (k: string) => (typeof s[k] === "number" ? (s[k] as number) : NaN);
  if (!e.min_duration && !e.max_duration && n("min_duration") >= n("max_duration")) {
    e.max_duration = "The longest clip must be longer than the shortest.";
  }
  if (!e.target_duration && (n("target_duration") < n("min_duration") || n("target_duration") > n("max_duration"))) {
    e.target_duration = "The ideal length must be between the shortest and the longest clip.";
  }
  if (!e.autopilot_active_start && !e.autopilot_active_end
    && n("autopilot_active_start") >= n("autopilot_active_end")) {
    e.autopilot_active_end = "The end hour must be later than the start hour.";
  }
  if ("autopilot_timezone" in s && !validTimeZone(String(s.autopilot_timezone || ""))) {
    e.autopilot_timezone = "Unknown time zone. Use a name such as America/Chicago or Europe/Berlin.";
  }
  if ("trend_region" in s && !/^[A-Za-z]{2}$/.test(String(s.trend_region || ""))) {
    e.trend_region = "Use a two-letter country code, such as US.";
  }
  if ("youtube_category_id" in s && !/^\d+$/.test(String(s.youtube_category_id || ""))) {
    e.youtube_category_id = "Use YouTube's category number, such as 22.";
  }
  return e;
}

export const fieldId = (k: string) => `set-${k}`;

/** One setting: its name and one-line hint on the left, the control and any field error on the right. */
export function SettingRow({ k, label, hint, group, children, errors }: {
  k?: string; label: ReactNode; hint?: ReactNode; group?: boolean; children: ReactNode; errors?: Record<string, string>;
}) {
  const id = k ? fieldId(k) : undefined;
  const err = k && errors?.[k];
  return (
    <div className="setting">
      <div className="stack" style={{ gap: 2 }}>
        {group || !id ? <span className="label" id={id ? `${id}-label` : undefined}>{label}</span>
          : <label className="label" htmlFor={id}>{label}</label>}
        {hint && <span className="hint" id={id ? `${id}-hint` : undefined}>{hint}</span>}
      </div>
      <div className="stack" style={{ gap: 6 }}>
        {children}
        {err && <span className="error-text" id={`${id}-err`}><Icon name="alert" className="sm" />{err}</span>}
      </div>
    </div>
  );
}

// Only the error is linked: a row's hint is next to its label, and a reference to a missing id would be invalid.
const describe = (k: string, errors?: Record<string, string>) => (errors?.[k] ? `${fieldId(k)}-err` : undefined);

/** A number box. While typing, an empty box stays empty (and blocks saving) instead of jumping to 0. */
export function NumInput({ k, c, label, step, width = 120 }: {
  k: string; c: FieldCtx; label?: string; step?: number; width?: number;
}) {
  const v = c.s[k];
  return (
    <input type="number" id={fieldId(k)} aria-label={label} step={step ?? (INTEGER.has(k) ? 1 : "any")}
      min={RANGES[k]?.[0]} max={RANGES[k]?.[1]} value={v === null || v === undefined ? "" : v}
      style={{ maxWidth: width }}
      aria-invalid={!!c.errors?.[k] || undefined} aria-describedby={describe(k, c.errors)}
      onChange={(e) => c.set({ [k]: e.target.value === "" ? "" : Number(e.target.value) })} />
  );
}

export function TextInput({ k, c, placeholder, width, label }: {
  k: string; c: FieldCtx; placeholder?: string; width?: number; label?: string;
}) {
  return (
    <input type="text" id={fieldId(k)} aria-label={label} value={c.s[k] ?? ""} placeholder={placeholder}
      spellCheck={false} autoComplete="off" style={width ? { maxWidth: width } : undefined}
      aria-invalid={!!c.errors?.[k] || undefined} aria-describedby={describe(k, c.errors)}
      onChange={(e) => c.set({ [k]: e.target.value })} />
  );
}

/** An on/off setting as a switch with its state word; the row's label names it. */
export function Switch({ k, c }: { k: string; c: FieldCtx }) {
  return (
    <Toggle id={fieldId(k)} on={!!c.s[k]} onChange={(v) => c.set({ [k]: v })} showState ariaLabel={FIELDS[k]?.label} />
  );
}

/** A checkbox with its own words (for lists of options under one row). */
export function Check({ k, c, children }: { k: string; c: FieldCtx; children: ReactNode }) {
  return (
    <label className="choice">
      <input type="checkbox" id={fieldId(k)} checked={!!c.s[k]} onChange={(e) => c.set({ [k]: e.target.checked })} />
      <span>{children}</span>
    </label>
  );
}

export function Seg<T extends string | number>({ k, c, options }: {
  k: string; c: FieldCtx; options: { value: T; label: ReactNode }[];
}) {
  return (
    <Segmented labelledBy={`${fieldId(k)}-label`} value={c.s[k] as T} onChange={(v) => c.set({ [k]: v })}
      options={options} />
  );
}

export function Select({ k, c, options }: {
  k: string; c: FieldCtx; options: (string | { value: string; label: string })[];
}) {
  const opts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const v = String(c.s[k] ?? "");
  return (
    <select id={fieldId(k)} value={v} aria-describedby={describe(k, c.errors)} style={{ maxWidth: 360 }}
      onChange={(e) => c.set({ [k]: e.target.value })}>
      {!opts.some((o) => o.value === v) && <option value={v}>{v || "(not set)"}</option>}
      {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

const MASK = "********";

/**
 * A secret (API key or client secret). The page never receives a saved secret: the server sends "********". It is
 * shown as "•••••••• (saved)" with Replace…; a new one is typed into an empty password box and sent only on
 * save.
 * Replace with nothing typed keeps the saved one. Optional keys can also be removed (sent as empty on save).
 */
export function SecretField({ k, c, removable, placeholder }: {
  k: string; c: FieldCtx; removable?: boolean; placeholder?: string;
}) {
  const savedHas = (c.saved ?? c.s)[k] === MASK;
  const v = String(c.s[k] ?? "");
  const [replacing, setReplacing] = useState(false);
  const id = fieldId(k);
  if (savedHas && v === "") {
    return (
      <div className="row wrap">
        <input type="text" id={id} readOnly value="Removed when you save" aria-describedby={describe(k, c.errors)}
          style={{ maxWidth: 320 }} />
        <button type="button" className="btn btn-small" onClick={() => c.set({ [k]: MASK })}>Undo</button>
      </div>
    );
  }
  if (savedHas && !replacing && v === MASK) {
    return (
      <div className="row wrap">
        <input type="text" id={id} readOnly value="•••••••• (saved)" aria-describedby={describe(k, c.errors)}
          style={{ maxWidth: 320 }} />
        <button type="button" className="btn btn-small" onClick={() => setReplacing(true)}>Replace…</button>
        {removable && (
          <button type="button" className="btn btn-small btn-quiet" onClick={() => c.set({ [k]: "" })}>Remove</button>
        )}
      </div>
    );
  }
  return (
    <div className="row wrap">
      <input type="password" id={id} autoComplete="new-password" spellCheck={false} autoFocus={replacing}
        value={v === MASK ? "" : v} placeholder={savedHas ? "Paste the new one" : placeholder} style={{ maxWidth: 320 }}
        aria-describedby={describe(k, c.errors)}
        onChange={(e) => c.set({ [k]: e.target.value || (savedHas ? MASK : "") })} />
      {savedHas && (
        <button type="button" className="btn btn-small btn-quiet"
          onClick={() => { setReplacing(false); c.set({ [k]: MASK }); }}>
          Keep the saved one
        </button>
      )}
    </div>
  );
}

/** A panel of settings with its heading (h2) and an optional intro line. */
export function SettingsPanel({ id, title, intro, children }: {
  id: string; title: string; intro?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="panel" aria-labelledby={id} id={`${id}-panel`}>
      <div className="stack" style={{ gap: 4 }}>
        <h2 id={id}>{title}</h2>
        {intro && <p className="small muted">{intro}</p>}
      </div>
      <div>{children}</div>
    </section>
  );
}
