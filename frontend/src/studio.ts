/** ClipForge studio API: uploads, Make clips, full videos, stories, styles, skills, accounts, preferences. */
import { req } from "./api";

export type Asset = { id: string; kind: "video" | "audio" | "image"; filename: string; sha256: string; size: number;
  duration?: number; width?: number; height?: number; fps?: number; has_audio?: boolean; has_thumbnail: boolean };
export type Upload = { id: string; filename: string; kind: string; size: number; received: number; status: string;
  error: string; asset_id: string; chunk_size: number };

export type Decision = { field: string; value: unknown; text: string; from: Entry; also: Entry[];
  overridden: (Entry & { value: unknown; reason: string })[] };
export type Entry = { level: string; id: string; revision: number; name: string };
export type Snapshot = { mode: string; values: Record<string, unknown>; decisions: Decision[]; problems: string[];
  conflicts: { field: string; label: string; level: string; entries: (Entry & { value: unknown })[]; resolution: string }[];
  used: (Entry & { fields: string[] })[] };

export type Connection = { id: string; platform: "youtube" | "tiktok"; label: string; account_id: string; display_name: string;
  nickname: string; avatar: string; scopes: string[]; is_default: boolean; status: string;
  health: { state: string; text: string; action: string }; connected_at: number; active_uploads: number };

export type Eligibility = { connection_id: string; platform: string; account: string; state: string; eligible: boolean;
  label: string; text: string; alternatives?: string[] };
export type Story = { id: string; position: number; kind: "story" | "gap"; title: string; opening: string; closing: string;
  completeness: "complete" | "uncertain" | "incomplete"; reason: string; method: string; boundary_revision: number;
  clip_id: string; clip_status: string; start: number; end: number; duration: number; confidence: number;
  included: boolean; eligibility: Eligibility[] };

export type Style = { id: string; name: string; revision: number; modes: string[]; values: Record<string, unknown>;
  source: string; is_default: boolean; effects: string[] };
export type Skill = { id: string; skill_key: string; name: string; description: string; version: string; revision: number;
  modes: string[]; supported: Record<string, unknown>; unsupported: { text: string; why: string }[];
  blocked: { text: string; why: string }[]; enabled: boolean; effects: string[]; original_format: string };

export type LibraryItem = { id: string; kind: "clips" | "full_video"; mode: string; name: string; status: string;
  message?: string; stage?: string; progress?: number; error?: string; clip_count?: number; updated_at: number;
  thumbnail: string; href: string };

export type PlanClip = { id: string; asset_id: string; kind: string; in_ms: number; out_ms: number; label: string;
  gain_db: number; include: boolean; must_keep?: string[] };
export type Plan = { schema: number; output: { aspect: string; fps: number }; layout: string; clips: PlanClip[];
  transition: { type: string; ms: number }; title: { enabled: boolean; text: string; ms: number };
  captions: { enabled: boolean; style: string; position: string }; music: { asset_id: string; level_db: number } | null;
  outline: { clip_id: string; label: string; summary: string; duration: number; keeps?: string[] }[]; notes: string[] };
export type Video = { id: string; name: string; status: string; message: string; asset_ids: string[];
  brief: Record<string, unknown>; plan_revision: number; rendered_revision: number; guidance: Snapshot; plan: Plan | null;
  duration: number; assets: Asset[];
  artifacts: { id: string; revision: number; kind: string; sha256: string; duration: number; audio_ok: boolean }[];
  jobs: { id: string; kind: string; revision: number; status: string; progress: number; message: string; error: string }[];
  revisions: { revision: number; note: string; created_at: number }[] };

export const studio = {
  library: (kind = "", q = "") => req<LibraryItem[]>("GET", `/api/studio/projects?kind=${kind}&q=${encodeURIComponent(q)}`),
  // A plain read (GET): showing the preview never changes anything.
  preview: (body: { mode: string; style_id?: string; choices?: Record<string, unknown>; title?: string }) =>
    req<Snapshot>("GET", `/api/studio/guidance/preview?${new URLSearchParams({ mode: body.mode,
      style_id: body.style_id || "saved", choices: JSON.stringify(body.choices || {}), title: body.title || "" })}`),
  makeClips: (body: Record<string, unknown>) => req<{ id: string }>("POST", "/api/studio/clips", body),
  projectGuidance: (id: string) => req<{ snapshot: Snapshot; frozen: boolean; note: string }>("GET", `/api/projects/${id}/guidance`),
  stories: (id: string) => req<{ mode: string; stories: Story[]; summary: Record<string, unknown> }>("GET", `/api/projects/${id}/stories`),
  patchStory: (id: string, body: Record<string, unknown>) => req<Story>("PATCH", `/api/stories/${id}`, body),
  splitStory: (pid: string, story_id: string, at: number) => req("POST", `/api/projects/${pid}/stories/split`, { story_id, at }),
  mergeStories: (pid: string, ids: string[]) => req("POST", `/api/projects/${pid}/stories/merge`, { ids }),
  createStoryClips: (pid: string, ids: string[] | null) => req<{ created: string[] }>("POST", `/api/projects/${pid}/stories/create`, { ids }),
  makeVideo: (body: Record<string, unknown>) => req<Video>("POST", "/api/studio/videos", body),
  video: (id: string) => req<Video>("GET", `/api/studio/videos/${id}`),
  editVideo: (id: string, base_revision: number, edit: Record<string, unknown>) =>
    req<Video & { note: string }>("POST", `/api/studio/videos/${id}/edits`, { base_revision, edit }),
  renderVideo: (id: string, revision: number) => req<Video>("POST", `/api/studio/videos/${id}/render`, { revision }),
  cancelVideo: (id: string) => req<Video>("POST", `/api/studio/videos/${id}/cancel`),
  restoreVideo: (id: string, revision: number) => req<Video>("POST", `/api/studio/videos/${id}/restore`, { revision }),
  styles: () => req<Style[]>("GET", "/api/studio/styles"),
  createStyle: (body: Record<string, unknown>) => req<Style>("POST", "/api/studio/styles", body),
  updateStyle: (id: string, body: Record<string, unknown>) => req<Style>("PATCH", `/api/studio/styles/${id}`, body),
  defaultStyle: (id: string) => req<Style>("POST", `/api/studio/styles/${id}/default`),
  deleteStyle: (id: string) => req("DELETE", `/api/studio/styles/${id}`),
  skills: () => req<Skill[]>("GET", "/api/studio/skills"),
  exampleSkill: () => req<{ filename: string; text: string }>("GET", "/api/studio/skills/example"),
  importSkill: async (file: File): Promise<Skill> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/studio/skills", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "The skill could not be imported.");
    return body;
  },
  patchSkill: (id: string, body: Record<string, unknown>) => req<Skill>("PATCH", `/api/studio/skills/${id}`, body),
  deleteSkill: (id: string) => req("DELETE", `/api/studio/skills/${id}`),
  connections: () => req<{ connections: Connection[]; protection: string }>("GET", "/api/connections"),
  addConnection: (platform: string) => req<{ auth_url: string }>("POST", `/api/connections/${platform}/add`),
  reconnect: (id: string) => req<{ auth_url: string }>("POST", `/api/connections/${id}/reconnect`),
  disconnect: (id: string) => req<Connection>("POST", `/api/connections/${id}/disconnect`),
  patchConnection: (id: string, body: Record<string, unknown>) => req<Connection>("PATCH", `/api/connections/${id}`, body),
  appearance: () => req<{ value: Record<string, unknown>; revision: number }>("GET", "/api/preferences/appearance"),
  saveAppearance: (value: Record<string, unknown>, revision?: number) =>
    req<{ value: Record<string, unknown>; revision: number }>("PUT", "/api/preferences/appearance", { value, revision }),
  layout: (device: string) => req<{ value: { screens: Record<string, { id: string; visible: boolean; size?: number }[]> }; revision: number; default?: boolean }>("GET", `/api/preferences/layout/${device}`),
  saveLayout: (device: string, value: unknown, revision?: number) => req("PUT", `/api/preferences/layout/${device}`, { value, revision }),
  resetLayout: (device: string) => req("DELETE", `/api/preferences/layout/${device}`),
  robotNames: () => req<Record<string, { role_id: string; default_name: string; role: string; display_name: string; custom: boolean }>>("GET", "/api/robots/names"),
  renameRobot: (id: string, name: string) => req<{ display_name: string }>("PUT", `/api/robots/names/${id}`, { name }),
  resetRobot: (id: string) => req<{ display_name: string }>("DELETE", `/api/robots/names/${id}`),
};

// ------------------------------------------------------------------ resumable upload
const KEY = "clipforge.uploads";
function remembered(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}
function remember(fp: string, id: string | null) {
  try {
    const all = remembered();
    if (id) all[fp] = id;
    else delete all[fp];
    localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* private window: resuming still works within this page */
  }
}

async function sha256(file: File): Promise<string> {
  // Small enough files are fingerprinted in the browser so the server can reject damaged transfers; for very large
  // files the server's own hash is the record (reading gigabytes into memory would stall a phone).
  if (file.size > 256 * 1024 * 1024 || !crypto?.subtle) return "";
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export type UploadProgress = { received: number; size: number; state: "hashing" | "sending" | "checking" | "done" | "interrupted" };

/** Send a file in chunks, resuming the same upload after an interruption (also after reloading the page). */
export async function uploadFile(file: File, onProgress: (p: UploadProgress) => void, signal?: AbortSignal): Promise<Asset> {
  const fp = `${file.name}|${file.size}|${file.lastModified}`;
  onProgress({ received: 0, size: file.size, state: "hashing" });
  const hash = await sha256(file);
  let up = await req<Upload>("POST", "/api/uploads", { filename: file.name, size: file.size, sha256: hash, fingerprint: fp });
  remember(fp, up.id);
  const chunk = up.chunk_size || 8 * 1024 * 1024;
  while (up.received < file.size) {
    if (signal?.aborted) throw new Error("Upload paused. Resume upload.");
    onProgress({ received: up.received, size: file.size, state: "sending" });
    const res = await fetch(`/api/uploads/${up.id}?offset=${up.received}`, {
      method: "PUT", body: file.slice(up.received, up.received + chunk), signal,
      headers: { "Content-Type": "application/octet-stream" },
    }).catch(() => null);
    if (!res) {
      onProgress({ received: up.received, size: file.size, state: "interrupted" });
      throw new Error("Upload interrupted. Resume upload.");
    }
    const body = await res.json();
    if (res.status === 409 && typeof body.received === "number") {
      up = { ...up, received: body.received };  // the server says where it really is: continue from there
      continue;
    }
    if (!res.ok) throw new Error(body.detail || "Upload failed.");
    up = body;
  }
  onProgress({ received: file.size, size: file.size, state: "checking" });
  const asset = await req<Asset>("POST", `/api/uploads/${up.id}/complete`);
  remember(fp, null);
  onProgress({ received: file.size, size: file.size, state: "done" });
  return asset;
}

export const fmtTime = (s: number) => {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};
export const fmtBytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
