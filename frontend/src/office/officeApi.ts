import { req } from "../api";

/**
 * Types and calls for the Office, the Brain, Integrations and the selected audience. They mirror the backend
 * (clipfoundry/office.py, brain_routes.py, integrations_routes.py, publish/routes.py); a value the backend does not
 * send stays undefined and is shown as unknown, never filled in here.
 */

export type RunState = "running" | "paused" | "stopped";
export type RobotLive = "working" | "waiting" | "error" | "idle" | "lounge" | "monitoring";
export type HealthState = "Healthy" | "Degraded" | "Error" | "Unknown";

export interface OfficeTask {
  job_id: string;
  stage: string;
  label: string;
  progress: number | null;
  message: string;
  ref_type: string;
  ref_id: string;
}

export interface OfficeRobot {
  role: string;
  department: string;
  manager: string;
  state: RobotLive;
  task: OfficeTask | null;
  queued: number;
  last: { at: number; message: string; level: string } | null;
}

export interface HealthCheck {
  id: string;
  label: string;
  state: HealthState;
  reason: string;
  action: string;
  checked_at: number;
}

export interface HealthSummary {
  state: HealthState;
  reason: string;
  action: string;
  checks: HealthCheck[];
  checked_at?: number;
}

export interface AudienceDestination {
  platform: string;
  intent: "LOCAL_ONLY" | "OWNER_ONLY" | "SELECTED_AUDIENCE";
  route: "api" | "manual" | "none";
  visibility: string;
  setup: string;
  policy_version: string;
  notes: string[];
  text: string;
  group: string;
  group_version: number;
}

export interface OfficeEvent {
  id: number;
  at: number;
  type: string;
  level: string;
  message: string;
  role: string;
  job_id: string;
  department: string;
  ref_type: string;
  ref_id: string;
  data: Record<string, any>;
}

export interface BrainCohort {
  cohort: string;
  eligible_clips: number;
  needed: number;
  strategy: Record<string, any> | null;
  status: string;
}

export interface OfficeSnapshot {
  cursor: number;
  server_time: number;
  run_state: RunState;
  publishing_paused: boolean;
  mission: { title: string; detail: string; job_id?: string; role?: string };
  robots: OfficeRobot[];
  health: HealthSummary;
  today: { clips_made: number; uploads: number };
  next_upload: { id: string; platform: string; planned_at: number; title: string; status: string } | null;
  needs_you: { key: string; title: string; fix: string; level: string }[];
  manual_handoffs: number;
  audience: Record<string, AudienceDestination>;
  brain: {
    state: string;
    observations: number;
    strategy: { target_duration: number; strategy_version: string; strategy_scope: string };
    cohorts: BrainCohort[];
  };
  recent: OfficeEvent[];
}

export interface EventsPage {
  events: OfficeEvent[];
  cursor: number;
  latest: number;
  gap: boolean;
  server_time: number;
}

export interface StrategyVersion {
  id: string;
  scope: string;
  parameter: string;
  old_value: number | null;
  new_value: number | null;
  reason: string;
  status: string;
  rollback_to: string;
  kind: string;
  created_at: number;
}

export interface BrainView {
  state: string;
  observations: number;
  by_provenance: Record<string, number>;
  cohorts: BrainCohort[];
  versions: StrategyVersion[];
  ranking: { target_duration: number; strategy_version: string; strategy_scope: string };
  guards: Record<string, number>;
  note: string;
}

export interface ClipFeedback {
  state: string;
  next: string;
  observations: number;
  by_provenance: Record<string, number>;
  items: { id: string; provenance: string; metric: string; value: number | null; observed_at: number; note?: string;
    platform?: string; tester_id?: string }[];
  labels: Record<string, string>;
}

export interface CsvPreview {
  rows: Record<string, any>[];
  problems: { line: number; problem: string }[];
  accepted: number;
  rejected: number;
  columns: string[];
}

export interface IntegrationCard {
  id: string;
  name: string;
  state: string;
  identity: string;
  capabilities: string[];
  missing: string[];
  next: string;
  audience?: AudienceDestination;
  detail?: NvidiaStatus;
  last_check: number | null;
  setup?: string;
}

export interface NvidiaStatus {
  state: string;
  blocker: string;
  enabled: boolean;
  key_saved: boolean;
  key_source: string;
  key_hint: string;
  mode: string;
  model: string;
  endpoint: string;
  usage_today: Record<string, number | null>;
  limits: { requests: number; tokens: number; spend_usd: number };
  terms_checked: string;
  authentication: string;
  sharing: string;
}

export interface AudienceView {
  destinations: Record<string, AudienceDestination>;
  scope: string;
  setup_labels: Record<string, string>;
  publish_paused: boolean;
  tiktok_private_confirmed: boolean;
  tiktok_followers_reviewed: boolean;
  youtube_viewers_label: string;
  migrated_from: string;
  youtube_share_steps: string;
}

export interface DevLog {
  entries: Record<string, any>[];
  changelog: string;
  available: boolean;
}

export const office = {
  snapshot: () => req<OfficeSnapshot>("GET", "/api/office"),
  events: (after: number) => req<EventsPage>("GET", `/api/office/events?after=${after}`),
  control: (action: string) =>
    req<{ run_state: RunState; publishing_paused: boolean }>("POST", "/api/office/control", { action }),
  health: () => req<HealthSummary>("GET", "/api/system/health"),
  devlog: () => req<DevLog>("GET", "/api/devlog"),
  brain: () => req<BrainView>("GET", "/api/brain"),
  rollback: (id: string) => req<StrategyVersion>("POST", `/api/brain/strategy/${encodeURIComponent(id)}/rollback`),
  clipFeedback: (clipId: string) => req<ClipFeedback>("GET", `/api/brain/clips/${encodeURIComponent(clipId)}`),
  feedback: (body: Record<string, unknown>) =>
    req<{ stored: number; duplicates: number }>("POST", "/api/brain/feedback", body),
  importPreview: (text: string, filename: string) =>
    req<CsvPreview>("POST", "/api/brain/import/preview", { text, filename }),
  importCommit: (text: string, filename: string) =>
    req<{ import_id: string; stored: number; duplicates: number }>("POST", "/api/brain/import/commit",
      { text, filename }),
  integrations: () =>
    req<{ cards: IntegrationCard[]; states: string[]; audience: Record<string, AudienceDestination> }>(
      "GET", "/api/integrations"),
  nvidiaTest: () => req<Record<string, any>>("POST", "/api/integrations/nvidia/test"),
  nvidiaDisconnect: () => req<NvidiaStatus>("POST", "/api/integrations/nvidia/disconnect"),
  audience: () => req<AudienceView>("GET", "/api/audience"),
  saveAudience: (body: Record<string, unknown>) => req<AudienceView>("POST", "/api/audience", body),
  viewersInvited: (pubId: string) =>
    req<Record<string, any>>("POST", `/api/publications/${encodeURIComponent(pubId)}/viewers-invited`),
  manualPosted: (itemId: string, link: string, note: string) =>
    req<Record<string, any>>("POST", `/api/autopilot/scheduled/${encodeURIComponent(itemId)}/manual-posted`,
      { link, note }),
};

/** The destination in a few words for the footer: never a blanket "Private uploads". */
export function destinationWords(platform: string, d?: AudienceDestination): string {
  const name = platform === "youtube" ? "YouTube" : "TikTok";
  if (!d) return `${name}: unknown`;
  if (d.intent === "LOCAL_ONLY") return `${name}: kept on this PC`;
  if (d.intent === "OWNER_ONLY") return `${name}: private staging (only you)`;
  if (platform === "youtube") return "YouTube invited viewers";
  const group = d.group === "FRIENDS" ? "TikTok friends" : "TikTok approved followers";
  return d.route === "manual" ? `${group} (you post it)` : group;
}

/** Local clock time "3:04:05 PM" from seconds since 1970. */
export const clockTime = (s: number) =>
  new Date(s * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

/** Local date and time "Oct 7, 3:04 PM". */
export const localWhen = (s: number) =>
  new Date(s * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
