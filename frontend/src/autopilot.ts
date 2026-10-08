import { req, PlatformAccount } from "./api";

/** A metric as a platform reported it (observed), derived by ClipFoundry (estimated), or not reported. */
export interface Metric {
  value: number | null;
  status: "observed" | "estimated" | "unavailable";
  note?: string;
  at?: number | null;
  /** Who reported it (YouTube Data API, Tavily web search, Wikimedia Commons...). */
  source?: string;
}

export interface ScoreComponent {
  value: number;
  weight?: number;
  status?: string;
  note?: string;
}

export interface TrendSignal {
  id: string;
  provider: string;
  platform: string;
  external_id: string;
  kind: "video" | "live" | "topic";
  title: string;
  url: string;
  channel_title: string;
  topic: string;
  category: string;
  keywords: string[];
  query: string;
  published_at: number | null;
  platform_rank: number | null;
  metrics: Record<string, Metric>;
  score: number | null;
  score_mode: "momentum" | "platform_order" | "";
  components: Record<string, ScoreComponent>;
  notes: string[];
  first_seen: number;
  last_checked: number;
}

export type RightsStatus = "OWNED" | "LICENSED" | "CREATIVE_COMMONS" | "PUBLIC_DOMAIN" | "ALLOWLISTED" | "MANUAL_CONFIRMATION_REQUIRED" | "BLOCKED";

export interface Source {
  id: string;
  platform: string;
  external_id: string;
  kind: "recorded" | "live";
  live_status: string;
  url: string;
  local_path: string;
  title: string;
  channel_title: string;
  duration: number | null;
  topic: string;
  category: string;
  rights_status: RightsStatus;
  rights_label: string;
  rights_explain: string;
  rights_basis: string;
  source_score: number | null;
  expected_clips: number | null;
  components: Record<string, ScoreComponent>;
  status: string;
  status_note: string;
  project_id: string;
  candidates_found: number;
  clips_selected: number;
  selected_day: string;
  updated_at: number;
}

export interface RightsRule {
  id: string;
  scope: "source" | "channel" | "folder" | "url_prefix";
  platform: string;
  value: string;
  label: string;
  status: RightsStatus;
  basis: string;
  evidence_url: string;
  created_at: number;
}

export interface Feed {
  id: string;
  kind: "watch_folder" | "youtube_channel" | "stream_url" | "signal_feed";
  name: string;
  config: Record<string, any>;
  rights_status: string;
  enabled: number;
  last_checked: number | null;
  last_error: string;
}

export interface WorkerRow {
  /** Current active job; stale or terminal progress is never displayed. */
  job_kind?: string;
  progress?: number | null;
  name: string;
  label: string;
  status: "idle" | "working" | "waiting" | "completed" | "failed";
  message: string;
  stage: string;
  job_id: string;
  ref_type: string;
  ref_id: string;
  heartbeat: number;
  last_error: string;
  stale: boolean;
  queue: Record<string, number>;
}

export interface Job {
  id: string;
  kind: string;
  worker: string;
  status: "queued" | "running" | "waiting" | "retrying" | "completed" | "failed" | "canceled";
  priority: number;
  attempts: number;
  max_attempts: number;
  progress: number;
  stage: string;
  message: string;
  error: string;
  fix: string;
  wait_reason: string;
  ref_type: string;
  ref_id: string;
  run_after: number;
  created_at: number;
  updated_at: number;
}

export interface ActionItem {
  id: string;
  key: string;
  kind: string;
  level: "action" | "warning" | "error";
  title: string;
  detail: string;
  fix: string;
  ref_type: string;
  ref_id: string;
  created_at: number;
}

export interface EventRow {
  id: number;
  at: number;
  kind: string;
  level: string;
  message: string;
  ref_type: string;
  ref_id: string;
}

export interface QuotaBucket {
  label: string;
  budget: number;
  used: number;
  remaining: number;
  projected: number;
  exhausted: boolean;
  discovery_used?: number;
  discovery_allowance?: number;
  reserve?: number;
  by_method?: Record<string, number>;
}

export interface GpuStatus {
  available: boolean;
  name: string;
  vram_mb: number;
  memory: { used_mb: number; total_mb: number; free_mb: number; utilization: number } | null;
  libs_ok: boolean | null;
  problem: string;
  fix: string;
  mode: "gpu" | "cpu";
  whisper: { model: string; device: string; compute_type: string; reason: string };
  busy: boolean;
  holder: { kind: string; label: string; pid: number; since: number } | null;
  waiting: { kind: string; label: string; since: number }[];
  last_transcription: { device: string; requested_device: string; compute_type: string; model: string; speed: number; warning: string; fix: string; at: number; label: string } | null;
  last_error: { kind: string; error: string; at: number } | null;
  min_free_mb: number;
}

export interface ProviderStatus {
  name: string;
  status: "ok" | "unavailable" | "not_configured" | "error" | "quota";
  detail: string;
  count: number;
  fix: string;
  at: number;
}

/** The one place to put your own videos: Autopilot watches it and clips what you put there. */
export interface MyVideos {
  path: string;
  watching: boolean;
  videos: number;
  opened?: boolean;
}

/** A video or stream added directly to Autopilot, with the backend's current plain-language status. */
export interface AutopilotLink {
  id: string;
  title: string;
  url: string;
  platform: string;
  kind: string;
  live_status: string;
  status: string;
  status_label: string;
  detail: string;
  progress: number;
  project_id: string;
  added_at: number;
  scheduled_at: number | null;
  can_remove: boolean;
  can_cancel: boolean;
  can_retry: boolean;
  can_prioritize: boolean;
}

/** Something that really needs you, in plain words (the simple Autopilot page). */
export interface NeedsYouItem {
  key: string;
  type: "account" | "rights" | "file" | "approve" | "publish" | "gpu" | "sleep" | "videos" | "stopped" | "other";
  folder?: MyVideos;
  title: string;
  detail: string;
  fix?: string;
  link?: string;
  question?: string;
  platform?: "youtube" | "tiktok";
  source?: { id: string; title: string; channel: string; url: string; platform: string; kind: string; score: number | null };
}

export interface Opportunity {
  id: string;
  title: string;
  url: string;
  channel: string;
  kind: string;
  topic: string;
  score: number;
  stage: string;
  source_id: string;
}

export interface AutoPublishState {
  enabled: boolean;
  supported: boolean;
  note: string;
  since: string;
  settings: { visibility?: string; made_for_kids?: boolean; daily_limit?: number; start_hour?: number; end_hour?: number };
}

export interface UpcomingPost {
  id: string;
  platform: "youtube" | "tiktok";
  title: string;
  planned_at: number | null;
  status: string;
  /** Approved by your automatic-publishing permission (not reviewed by you). */
  auto: boolean;
  /** Already uploaded: the platform publishes it at its time, even if this PC is off. */
  on_platform: boolean;
}

/** The video Autopilot works on now. `progress` is the job's own report (0 to 1), or null: never an estimate. */
export interface WorkingOn {
  title: string;
  project_id: string;
  has_thumbnail: boolean;
  step: string;
  progress: number | null;
  message?: string;
}

export interface HomeView {
  setup: {
    started: boolean; connected: ("youtube" | "tiktok")[]; can_discover: boolean; topics: string;
    /** The choice made in first-time setup ("manual": you make clips yourself). */
    mode?: "" | "manual" | "autopilot";
  };
  currently: string;
  next?: string;
  next_look: number | null;
  /** The last online search, what was found so far by where it stands, and searches that did not work (plain words). */
  discovery: {
    last_scan: number | null; next_scan: number | null; found: number; counts: Record<string, number>;
    problems: { name: string; detail: string; fix: string }[];
  };
  working: WorkingOn | null;
  /** Posts waiting for your OK, and posts you need to settle (upload not confirmed, finish in the TikTok app). */
  posts: { review: number; fix: number; ready?: number; scheduled?: number };
  needs_you: NeedsYouItem[];
  opportunities: Opportunity[];
  upcoming: UpcomingPost[];
  empty: string;
  auto_publish: { youtube: AutoPublishState; tiktok: AutoPublishState };
  pc_note: string;
  /** Whether Windows really keeps the PC awake now ("failed": it refused; Needs you says what to do). */
  keep_awake: "on" | "pending" | "failed" | "off" | "unsupported";
  skipped_today: number;
  my_videos: MyVideos;
}

/** One found video in the activity log: used, or skipped with the reason. */
export interface ActivityItem {
  id: string;
  title: string;
  channel: string;
  url: string;
  platform: string;
  kind: string;
  score: number | null;
  status: string;
  used: boolean;
  stage: string;
  why: string;
  rights: string;
  access: string;
  at: number;
  posting: string;
  can_add_file: boolean;
}

export interface Agreement {
  id: string;
  creator: string;
  evidence: string;
  evidence_url: string;
  expires_at: number | null;
  created_at: number;
  channels: string[];
  rules: string[];
  conditions: { attribution: string; commercial: boolean; platforms: string[]; third_party: boolean; media_folder: string; media_url_prefix: string };
}

export interface AgreementIn {
  creator: string;
  channels: string[];
  evidence: string;
  evidence_url: string;
  attribution: string;
  commercial: boolean;
  platforms: string[];
  third_party: boolean;
  expires: string;
  media_folder: string;
  media_url_prefix: string;
}

export interface AutoPublishView {
  youtube: { supported: boolean; note: string; enabled: boolean; consent: { id: string; settings: AutoPublishState["settings"]; text: string; created_at: number } | null };
  tiktok: { supported: boolean; note: string; enabled: boolean; consent: null };
  verified_project: boolean;
  channel: string;
  timezone: string;
  defaults: { daily_limit: number; start_hour: number; end_hour: number };
}

export interface AutopilotStatus {
  enabled: boolean;
  paused: boolean;
  day: string;
  timezone: string;
  /** published/scheduled: unique clips today; *_posts: platform posts (one clip on YouTube and TikTok = 2 posts) */
  target: {
    daily: number; published: number; scheduled: number; processed: number; note: string;
    published_posts: number; scheduled_posts: number;
    posts_by_platform: Record<string, { published: number; scheduled: number }>;
  };
  sources_today: { selected: number; counted: number; clips: number; busy: number };
  sources_per_day: number;
  next: (ScheduledItemRow & { local: string }) | null;
  queue: { size: number; by_worker: Record<string, Record<string, number>> };
  workers: { workers: WorkerRow[]; host: { mode: string; alive: boolean; pid: number | null; process_running: boolean }; paused: boolean };
  gpu: GpuStatus;
  platforms: { youtube: PlatformAccount; tiktok: PlatformAccount };
  rights: Record<string, number>;
  quota: { warnings: string[]; buckets: Record<string, QuotaBucket>; resets_at: number; discovery_paused: boolean };
  actions: ActionItem[];
  events: EventRow[];
  trends: TrendSignal[];
  providers: Record<string, ProviderStatus>;
  web_search: { used: number; free: number; allowed: number; budget_usd: number; cost_usd: number; month: string };
  settings: Record<string, any>;
  home: HomeView;
}

export interface ScheduledItemRow {
  id: string;
  clip_id: string;
  platform: "youtube" | "tiktok";
  title: string;
  description: string;
  tags: string[];
  privacy: string;
  options: Record<string, any>;
  planned_at: number | null;
  status: "awaiting_approval" | "approved" | "publishing" | "reconciling" | "published" | "failed" | "canceled" | "replaced" | "blocked" | "action_needed";
  status_note: string;
  final_score: number | null;
  scores: Record<string, any>;
  slot: { quality?: number; note?: string; local?: string };
  approval: { at?: number; hash?: string; by?: string; consent_id?: string };
  replaces: string;
  replaced_by: string;
  last_error: string;
  fix: string;
  audit: { at: number; event: string; detail: string }[];
  /** Delivery, kept apart from the upload status (publish/audience.py): uploaded is not "watched". */
  delivery_state?: string;
  delivery_label?: string;
  /** What results the Brain has for it, never a guess. */
  analytics_state?: string;
  analytics_label?: string;
  /** Who it is for, in your words ("Invited viewers", "Only you (staging)"). */
  audience_label?: string;
  /** The audience stamp it was planned with (publish/audience.py). */
  audience?: { intent?: string; visibility?: string; group?: string };
}

export interface MetadataOption {
  id: string;
  style: string;
  title: string;
  description: string;
  caption: string;
  tags: string[];
  hashtags: string[];
  score: number;
  problems: string[];
  origin: string;
  selected: number;
}

export interface QualityCheck {
  name: string;
  label: string;
  kind: "deterministic" | "heuristic";
  status: "pass" | "warn" | "fail" | "skipped";
  detail: string;
}

/** The final quality gate's report on the exact file (and this platform's text) that would be published. */
export interface QualitySummary {
  status: "passed" | "failed";
  blockers: string[];
  warnings: string[];
  text_status: "passed" | "failed" | "missing" | null;
  text_problems: string[];
  checked_at: number;
  sha256: string;
  coverage: { note?: string; skipped?: string[] };
  checks: QualityCheck[];
}

export interface ScheduledItem extends ScheduledItemRow {
  local_time: string;
  approval_valid: boolean;
  clip: { id: string; title: string; duration: number; score: number; category: string; status: string; has_thumbnail: boolean; video_url: string; thumbnail_url: string; caption_text: string };
  source: { id?: string; title: string; url?: string; platform?: string; channel?: string; rights_status: string; rights_label: string };
  trend: { topic: string; score: number; mode: string } | null;
  clip_scores: Record<string, any> | null;
  metadata_options: MetadataOption[];
  quality: QualitySummary | null;
  publication: { id: string; status: string; url: string; privacy: string; requested_privacy: string; message: string; error: string; fix: string; info: Record<string, any> } | null;
  warnings?: string[];
}

export interface QuotaStatus {
  day: string;
  resets_at: number;
  buckets: Record<string, QuotaBucket>;
  warnings: string[];
  cache: Record<string, number>;
  discovery_slowdown: number | null;
  discovery_paused: boolean;
  planned_uploads: number;
  note: string;
}

export interface LearningStatus {
  status: { samples: number; needed: number; excluded_youtube?: number; note?: string; message?: string; findings?: string[]; at?: number };
  metrics: { dimension: string; key: string; platform: string; n: number; lift: number }[];
  weights: { key: string; lift: number; n: number; data: { rho: number } }[];
  labels: Record<string, string>;
  min_samples: number;
}

const A = "/api/autopilot";
export const ap = {
  links: () => req<AutopilotLink[]>("GET", `${A}/links`),
  addLink: (url: string) => req<{ item: AutopilotLink; already_added: boolean }>("POST", `${A}/links`, { url }),
  linkAction: (id: string, action: "cancel" | "retry" | "prioritize" | "remove") =>
    req<AutopilotLink>("POST", `${A}/links/${id}/${action}`),
  status: () => req<AutopilotStatus>("GET", `${A}/status`),
  enable: (enabled: boolean) => req<AutopilotStatus>("POST", `${A}/enable`, { enabled }),
  start: (topics?: string) => req<AutopilotStatus>("POST", `${A}/start`, topics === undefined ? undefined : { topics }),
  openMyVideos: () => req<MyVideos>("POST", `${A}/my-videos/open`),
  permission: (id: string, allowed: boolean) => req<Source>("POST", `${A}/sources/${id}/permission`, { allowed }),
  stopAll: () => req<{ canceled: number; stopping: number; manual: number }>("POST", `${A}/stop-all`),
  resume: () => req<{ paused: boolean }>("POST", `${A}/resume`),
  scan: () => req<Job>("POST", `${A}/scan`),
  learn: () => req<Job>("POST", `${A}/learn`),
  trends: () => req<{ signals: TrendSignal[]; providers: Record<string, ProviderStatus>; last_scan: { at: number; signals: number; active: number } | null; derived_metrics_approved: boolean }>("GET", `${A}/trends`),
  sources: (status = "") => req<Source[]>("GET", `${A}/sources${status ? `?status=${status}` : ""}`),
  addSource: (body: { url?: string; path?: string; title?: string; rights_status?: string; basis?: string }) => req<Source>("POST", `${A}/sources`, body),
  confirmRights: (id: string, status: string, basis: string) => req<Source>("POST", `${A}/sources/${id}/rights`, { status, basis }),
  attachFile: (id: string, path: string) => req<Source>("POST", `${A}/sources/${id}/file`, { path }),
  skipSource: (id: string) => req<Source>("POST", `${A}/sources/${id}/skip`),
  huntSource: (id: string) => req<Job>("POST", `${A}/sources/${id}/hunt`),
  rights: () => req<{ rules: RightsRule[]; statuses: { id: RightsStatus; label: string; explain: string; auto: boolean }[] }>("GET", `${A}/rights`),
  addRule: (body: Partial<RightsRule>) => req<RightsRule>("POST", `${A}/rights`, body),
  deleteRule: (id: string) => req<{ ok: boolean }>("DELETE", `${A}/rights/${id}`),
  feeds: () => req<Feed[]>("GET", `${A}/feeds`),
  addFeed: (body: { kind: string; name: string; config: Record<string, any>; rights_status?: string; rights_basis?: string }) => req<Feed>("POST", `${A}/feeds`, body),
  setFeed: (id: string, enabled: boolean) => req<Feed>("PATCH", `${A}/feeds/${id}`, { enabled }),
  deleteFeed: (id: string) => req<{ ok: boolean }>("DELETE", `${A}/feeds/${id}`),
  quota: () => req<QuotaStatus>("GET", `${A}/quota`),
  jobs: (status = "", worker = "") => req<Job[]>("GET", `${A}/jobs?status=${status}&worker=${worker}&limit=150`),
  jobLogs: (id: string) => req<{ at: number; level: string; event: string; message: string; data: Record<string, any> }[]>("GET", `${A}/jobs/${id}/logs`),
  cancelJob: (id: string) => req<Job>("POST", `${A}/jobs/${id}/cancel`),
  retryJob: (id: string) => req<Job>("POST", `${A}/jobs/${id}/retry`),
  dismiss: (key: string) => req<{ ok: boolean }>("POST", `${A}/actions/${encodeURIComponent(key)}/dismiss`),
  scheduled: (view: string) => req<{ items: ScheduledItem[]; view: string; timezone: string; auto_publish: boolean; counts: Record<string, number> }>("GET", `${A}/scheduled?view=${view}`),
  approve: (id: string, body: Record<string, unknown>) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/approve`, { ...body, confirm: true }),
  edit: (id: string, body: Record<string, unknown>) => req<ScheduledItem>("PATCH", `${A}/scheduled/${id}`, body),
  reschedule: (id: string, planned_at: number) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/reschedule`, { planned_at }),
  cancel: (id: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/cancel`),
  retry: (id: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/retry`),
  publishNow: (id: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/publish-now`),
  link: (id: string, url: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/link`, { url }),
  /** You posted a ready-to-post package in the TikTok app and have no link for it (your word). */
  postedByYou: (id: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/posted`),
  /** You shared this Private YouTube video with your viewers in YouTube Studio (your word). */
  audienceConfirmed: (id: string) => req<ScheduledItem>("POST", `${A}/scheduled/${id}/audience-confirmed`),
  /** Plan posts held as public (planned before this version) for your selected viewers; each needs your OK. */
  retarget: (ids: string[]) => req<{ retargeted: number }>("POST", `${A}/scheduled/retarget`, { ids }),
  resolve: (id: string, published: boolean, url = "") => req<ScheduledItem>("POST", `${A}/scheduled/${id}/resolve`, { published, url }),
  learning: () => req<LearningStatus>("GET", `${A}/learning`),
  activity: () => req<{ items: ActivityItem[]; events: EventRow[] }>("GET", `${A}/activity`),
  agreements: () => req<Agreement[]>("GET", `${A}/agreements`),
  addAgreement: (body: AgreementIn) => req<Agreement>("POST", `${A}/agreements`, body),
  removeAgreement: (id: string) => req<{ ok: boolean }>("DELETE", `${A}/agreements/${id}`),
  autoPublish: () => req<AutoPublishView>("GET", `${A}/auto-publish`),
  enableAutoPublish: (body: { platform: string; visibility: string; made_for_kids: boolean | null; daily_limit: number; start_hour: number; end_hour: number; agreed: boolean }) =>
    req<AutoPublishView>("POST", `${A}/auto-publish`, body),
  disableAutoPublish: (platform: string) => req<AutoPublishView & { returned_to_review: number }>("DELETE", `${A}/auto-publish/${platform}`),
};

export const RIGHTS_BADGE: Record<string, string> = {
  OWNED: "good", LICENSED: "good", ALLOWLISTED: "good", CREATIVE_COMMONS: "info", PUBLIC_DOMAIN: "info",
  MANUAL_CONFIRMATION_REQUIRED: "warn", BLOCKED: "bad",
};
export const RIGHTS_LABEL: Record<string, string> = {
  OWNED: "Owned", LICENSED: "Licensed", CREATIVE_COMMONS: "Creative Commons", PUBLIC_DOMAIN: "Public domain",
  ALLOWLISTED: "Allowlisted", MANUAL_CONFIRMATION_REQUIRED: "Not covered", BLOCKED: "Blocked",
};
export const WORKER_BADGE: Record<string, [string, string]> = {
  idle: ["Idle", ""], working: ["Working", "warn"], waiting: ["Waiting", "info"], completed: ["Completed", "good"],
  failed: ["Failed", "bad"],
};
export const ITEM_STATUS: Record<string, [string, string]> = {
  awaiting_approval: ["Needs approval", "warn"], approved: ["Approved", "good"], publishing: ["Publishing", "info"],
  published: ["Published", "good"], failed: ["Failed", "bad"], canceled: ["Canceled", ""], replaced: ["Replaced", ""],
  blocked: ["Blocked", "bad"], action_needed: ["Action needed", "bad"],
  reconciling: ["Upload not confirmed", "warn"],
};

export function localInput(ts: number | null): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
