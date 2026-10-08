import { req } from "../api";

/** What the office API returns (clipfoundry/office). Every value comes from the job system; nothing is invented. */
export type RoleState = "idle" | "working" | "waiting" | "retrying" | "error" | "reviewing" | "paused" | "unavailable";

export interface OfficeTask {
  job_id: string;
  kind: string;
  stage: string;
  status: string;
  message: string;
  /** measured progress 0-1 while running, null when the job does not measure it */
  progress: number | null;
  ref_type: string;
  ref_id: string;
  updated_at: number | null;
}

export interface RoleRow {
  id: string;
  state: RoleState;
  task: OfficeTask | null;
  tasks: number;
  queued: number;
  error: string;
  last: { summary: string; state: string; at: number } | null;
}

export interface OfficeReport {
  id: string;
  job_id: string;
  kind: string;
  department: string;
  manager: string;
  worker: string;
  ref_type: string;
  ref_id: string;
  state: string;
  summary: string;
  warnings: string[];
  recommendation: string;
  confidence: number | null;
  resources: { elapsed_s: number | null; attempts: number | null; worker: string | null };
  created_at: number;
}

export interface OfficeDecision {
  id: string;
  point: "source" | "clip" | "qc" | "upload";
  action: "approved" | "rework" | "rejected" | "held";
  subject_type: string;
  subject_id: string;
  job_id: string;
  decided_by: string;
  reported_by: string;
  reason: string;
  evidence: Record<string, unknown>;
  rule_version: string;
  created_at: number;
}

export interface OfficeEvent {
  id: number;
  at: number;
  type: string;
  role: string;
  job_id: string;
  kind: string;
  ref_type: string;
  ref_id: string;
  message: string;
  data: Record<string, any>;
}

export type HealthStatus = "healthy" | "degraded" | "error" | "unknown";
export interface HealthCheck {
  id: string;
  label: string;
  status: HealthStatus;
  status_label: string;
  reason: string;
  action: string;
  checked_at: number;
  [k: string]: unknown;
}
export interface Health {
  status: HealthStatus;
  label: string;
  checked_at: number;
  headline: string;
  action: string;
  checks: HealthCheck[];
}

export const NOT_UPDATING = "Unknown — not updating";
/**
 * Health as a page that stopped hearing from ClipFoundry must show it: every reading Unknown, never the last green,
 * with the last known reading kept in words (System Guardian rule: no stale green shown as current).
 */
export function staleHealth(h: Health, since: number | null): Health {
  const at = since ? new Date(since).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  return {
    ...h,
    status: "unknown",
    label: NOT_UPDATING,
    headline: `ClipFoundry is not answering, so these readings may be out of date${at ? ` (last answer ${at})` : ""}.`,
    action: "Check that the black ClipFoundry window is still open. The page catches up when it answers again.",
    checks: h.checks.map((c) => ({
      ...c, status: "unknown", status_label: NOT_UPDATING,
      reason: `Last known: ${c.status_label}. ${c.reason}`,
    })),
  };
}

export interface Destination {
  platform: string;
  label: string;
  confirmed: boolean;
  [k: string]: unknown;
}

export interface BrainSummary {
  state: "cold_start" | "collecting" | "evaluating" | "updated" | "paused" | "error";
  label: string;
  message: string;
  observations: Record<string, number>;
  groups: { platform: string; cohort: string; state: string; message: string; mature?: number; sources?: number;
    [k: string]: unknown }[];
  last_evaluated: number | null;
  strategies: { id: string; name: string; platform: string; cohort: string; version: number;
    params: Record<string, any>; reason: string; created_at: number }[];
  baseline_target: number;
  min_clips: number;
  max_step: number;
}

export interface RunState {
  state: "running" | "paused" | "stopped";
  actions: ("start" | "pause" | "resume" | "stop")[];
  publishing_paused: boolean;
  label: string;
}

export interface Snapshot {
  cursor: number;
  server_time: number;
  run: RunState;
  roles: RoleRow[];
  reports: OfficeReport[];
  decisions: OfficeDecision[];
  health: Health;
  audience: { footer: string; destinations: Record<string, Destination>; uploadable: string[];
    halted: Record<string, unknown> };
  next_upload: { id: string; platform: string; title: string; planned_at: number } | null;
  today: { clips: number; passed_check: number; uploads: number };
  needs_you: { key: string; kind: string; level: string; title: string; detail: string; fix: string }[];
  brain: BrainSummary | Record<string, never>;
}

export interface EventsPage {
  events: OfficeEvent[];
  cursor: number;
  latest: number;
  more: boolean;
  reset: boolean;
  server_time: number;
}

export interface RoomDetails {
  id: string;
  name: string;
  roles: string[];
  events: OfficeEvent[];
  [k: string]: any;
}

export interface DevLogEntry {
  at?: string;
  checkpoint?: string;
  summary?: string;
  files?: string[];
  tests?: string;
  verified?: string[];
  not_verified?: string[];
  [k: string]: unknown;
}

export type Control = "start" | "pause" | "resume" | "stop" | "pause_publishing" | "resume_publishing";

const O = "/api/office";
export const office = {
  snapshot: () => req<Snapshot>("GET", `${O}/snapshot`),
  events: (after: number, limit = 200) => req<EventsPage>("GET", `${O}/events?after=${after}&limit=${limit}`),
  room: (id: string) => req<RoomDetails>("GET", `${O}/rooms/${encodeURIComponent(id)}`),
  decisions: (subjectType: string, subjectId: string) =>
    req<OfficeDecision[]>("GET", `${O}/decisions?subject_type=${encodeURIComponent(subjectType)}&subject_id=${encodeURIComponent(subjectId)}`),
  reports: (manager = "") => req<OfficeReport[]>("GET", `${O}/reports${manager ? `?manager=${manager}` : ""}`),
  health: () => req<Health>("GET", `${O}/health`),
  devlog: (limit = 50) => req<DevLogEntry[]>("GET", `${O}/devlog?limit=${limit}`),
  control: (action: Control) => req<Snapshot>("POST", `${O}/control`, { action }),
};

// ------------------------------------------------------------------ Brain and test feedback
export type Provenance = "platform_api" | "owner_import" | "tester_feedback";
export interface Observation {
  id: string;
  clip_id: string;
  platform: string;
  provenance: Provenance;
  observed_at: number;
  metrics: Record<string, number | null>;
  tester: string;
  note: string;
  cohort: string;
  revision: number;
  created_at: number;
  [k: string]: unknown;
}
export interface Strategy {
  id: string;
  name: string;
  platform: string;
  cohort: string;
  version: number;
  status: string;
  params: Record<string, any>;
  reason: string;
  created_at: number;
  [k: string]: unknown;
}
export interface BrainView extends BrainSummary {
  history: Strategy[];
  fields: {
    metrics: Record<string, { label: string; unit: string }>;
    ratings: Record<string, string>;
    provenance: Record<Provenance, string>;
    cohorts: Record<string, string>;
  };
}
export interface ImportRow {
  line: number;
  status: "new" | "correction" | "duplicate" | "error" | "skipped" | string;
  message?: string;
  clip_id?: string;
  clip_title?: string;
  platform?: string;
  observed_at?: number;
  tester?: string;
  values?: Record<string, number | null>;
  cohort_label?: string;
}
export interface ImportResult {
  rows: ImportRow[];
  counts: Record<string, number>;
  columns?: { recognized: string[]; ignored: string[] };
}
export interface FeedbackClip {
  clip_id: string;
  title: string;
  platform: string;
  posted_at: number | null;
  cohort: string;
  cohort_label: string;
}
export interface ImportIn {
  text: string;
  provenance: "owner_import" | "tester_feedback";
  platform: string;
  observed_at: number | null;
  filename: string;
}

const B = "/api/brain";
export const brainApi = {
  view: () => req<BrainView>("GET", B),
  feedbackClips: () => req<FeedbackClip[]>("GET", `${B}/feedback-clips`),
  clip: (id: string) => req<{ observations: Observation[]; testers: number; has: Record<Provenance, boolean> }>(
    "GET", `${B}/clips/${encodeURIComponent(id)}`),
  add: (body: { clip_id: string; platform: string; provenance: "owner_import" | "tester_feedback";
    values: Record<string, unknown>; observed_at: number | null; tester: string; note: string }) =>
    req<{ status: string; observation: Observation }>("POST", `${B}/observations`, body),
  preview: (body: ImportIn) => req<ImportResult>("POST", `${B}/import/preview`, body),
  importCsv: (body: ImportIn) => req<ImportResult>("POST", `${B}/import`, body),
  rollback: (id: string) => req<{ rolled_back: string; active: string; message: string }>("POST",
    `${B}/strategies/${encodeURIComponent(id)}/rollback`),
  reset: (platform = "") => req<{ reset: number }>("POST", `${B}/reset`, { platform }),
  pause: (paused: boolean) => req<BrainSummary>("POST", `${B}/pause`, { paused }),
};

// ------------------------------------------------------------------ integrations
export interface CapabilityRow { id: string; label: string; state: string; detail: string }
/** The last Test connection of a platform (office/capabilities.test_connection): one read, nothing uploaded. */
export interface ConnectionCheck {
  ok: boolean;
  at: number;
  status: string;
  status_label: string;
  detail: string;
  fix: string;
  code: string;
  /** a rate limit's end (seconds since 1970), when the platform named one */
  until: number | null;
  last_ok_at: number | null;
  identity?: string;
  /** false once you connected again: it tested the earlier sign-in */
  current?: boolean;
}
export interface IntegrationCard {
  id: string;
  name: string;
  status: string;
  status_label: string;
  detail: string;
  identity: string;
  missing: string[];
  action: string;
  capabilities: CapabilityRow[];
  /** the last successful Test connection (YouTube, TikTok); null when none worked yet */
  checked_at: number | null;
  last_check?: ConnectionCheck | null;
  can_test?: boolean;
  /** a wait the platform set (Retry-After, posting cap, YouTube quota), while it lasts */
  limit?: { until: number; detail: string } | null;
  [k: string]: any;
}
export interface NvidiaView {
  enabled: boolean;
  selected: boolean;
  has_key: boolean;
  key_from_env: boolean;
  model: string;
  mode: "development" | "production";
  opted_in: boolean;
  endpoint: string;
  problems: string[];
  usage: { day: string; requests: number; tokens: number; cost_usd: number | null; cost_known: boolean };
  circuit: { open: boolean; reason?: string; until?: number; fails?: number };
  limits: Record<string, number | null>;
  data_note: string;
  development_note: string;
}
export interface NvidiaResult { ok: boolean; detail?: string; key_verified?: boolean; models?: string[]; code?: string }

const I = "/api/integrations";
export const integrations = {
  list: () => req<{ cards: IntegrationCard[]; registry: { capabilities: Record<string, string>;
    platforms: Record<string, Record<string, { state: string; detail: string }>> } }>("GET", I),
  nvidia: () => req<NvidiaView>("GET", `${I}/nvidia`),
  optIn: (agree: boolean) => req<NvidiaView>("POST", `${I}/nvidia/opt-in`, { agree }),
  check: () => req<NvidiaResult>("POST", `${I}/nvidia/check`),
  test: () => req<NvidiaResult>("POST", `${I}/nvidia/test`),
  disconnect: () => req<{ disconnected: boolean }>("POST", `${I}/nvidia/disconnect`),
  testConnection: (platform: "youtube" | "tiktok") => req<ConnectionCheck>("POST", `${I}/${platform}/test`),
};

// ------------------------------------------------------------------ who watches (publish/audience.py)
export type AudienceIntent = "selected" | "owner_only" | "local_only";
export interface AudienceDestination {
  platform: "youtube" | "tiktok";
  intent: "SELECTED_AUDIENCE" | "OWNER_ONLY" | "LOCAL_ONLY";
  group: string;
  label: string;
  detail: string;
  confirmed: boolean;
  confirmed_at: number | null;
  group_version: number;
  halted: { at: number; detail: string; remote_id?: string } | null;
}
export interface AudienceView {
  policy_version: number;
  youtube: AudienceDestination;
  tiktok: AudienceDestination;
  summary: string;
  youtube_steps: string;
  tiktok_steps: string;
  limits: string;
}
export const INTENT_OF: Record<AudienceDestination["intent"], AudienceIntent> = {
  SELECTED_AUDIENCE: "selected", OWNER_ONLY: "owner_only", LOCAL_ONLY: "local_only",
};
export const audienceApi = {
  view: () => req<AudienceView>("GET", "/api/audience"),
  set: (platform: string, body: { intent: AudienceIntent; group?: string; confirm: boolean; group_changed?: boolean }) =>
    req<AudienceView>("POST", `/api/audience/${platform}`, body),
  checked: (platform: string) => req<AudienceView>("POST", `/api/audience/${platform}/checked`),
};
