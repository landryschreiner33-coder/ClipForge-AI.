export type Status = "created" | "uploading" | "queued" | "processing" | "ready" | "error" | "cancelled";

export interface Project {
  id: string;
  name: string;
  created_at: number;
  updated_at: number;
  source_filename: string;
  source_url?: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  status: Status;
  stage: string;
  progress: number;
  message: string;
  error: string;
  options: Record<string, unknown>;
  info: Record<string, any>;
  clip_count?: number;
  best_score?: number | null;
  has_thumbnail: boolean;
  clips?: Clip[];
}

export interface Word {
  start: number;
  end: number;
  w: string;
}

export interface ClipEdit {
  start?: number;
  end?: number;
  tracking?: string;
  layout?: string;
  crop_x?: number;
  zoom?: number;
  caption_style?: string;
  caption_position?: string;
  caption_size?: number;
  highlight_color?: string;
  highlight_words?: boolean;
  captions_enabled?: boolean;
  caption_words?: Word[] | null;
  hook?: string;
  hook_overlay?: boolean;
  hook_seconds?: number;
  silence?: string;
  auto_zoom?: boolean;
  gain_db?: number;
  normalize_audio?: boolean;
}

export interface Clip {
  id: string;
  project_id: string;
  rank: number;
  start: number;
  end: number;
  title: string;
  hook: string;
  hooks_alt: string[];
  caption_text: string;
  hashtags: string[];
  category: string;
  score: number;
  scores: Record<string, number>;
  score_source: string;
  reason: string;
  edit: ClipEdit;
  status: "queued" | "rendering" | "ready" | "error";
  progress: number;
  error: string;
  duration: number;
  selected: number;
  render_info: Record<string, any>;
  has_video: boolean;
  has_thumbnail: boolean;
  version: number;
}

export type Settings = Record<string, any>;

export interface Health {
  version: string;
  platform: string;
  ffmpeg: string | null;
  ffprobe: string | null;
  nvenc: boolean;
  cuda: boolean;
  whisper_installed: boolean;
  whisper: { model: string; device: string; compute_type: string; cached: boolean };
  ai_provider: string;
  data_dir: string;
  busy: boolean;
  queue: number;
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("GET", "/api/health"),
  stats: () => req<{ projects: number; clips: number; processing: number; recent: Project[] }>("GET", "/api/stats"),
  settings: () => req<Settings>("GET", "/api/settings"),
  saveSettings: (s: Settings) => req<Settings>("PUT", "/api/settings", s),
  checkAi: () => req<{ ok: boolean; detail: string; models?: string[] }>("POST", "/api/ai/check"),
  projects: () => req<Project[]>("GET", "/api/projects"),
  project: (id: string) => req<Project>("GET", `/api/projects/${id}`),
  renameProject: (id: string, name: string) => req<Project>("PATCH", `/api/projects/${id}`, { name }),
  deleteProject: (id: string) => req<{ ok: boolean }>("DELETE", `/api/projects/${id}`),
  cancelProject: (id: string) => req<{ ok: boolean }>("POST", `/api/projects/${id}/cancel`),
  reprocess: (id: string, options: Record<string, unknown>) =>
    req<Project>("POST", `/api/projects/${id}/process`, { options }),
  importUrl: (url: string, options: Record<string, unknown>) =>
    req<Project>("POST", "/api/projects/url", { url, options }),
  clip: (id: string) => req<Clip>("GET", `/api/clips/${id}`),
  patchClip: (id: string, patch: Record<string, unknown>) =>
    req<Clip>("PATCH", `/api/clips/${id}`, patch),
  renderClip: (id: string) => req<Clip>("POST", `/api/clips/${id}/render`),
  clipWords: (id: string) =>
    req<{ start: number; end: number; original_start: number; original_end: number; duration: number; words: Word[]; caption_words: Word[] | null }>(
      "GET",
      `/api/clips/${id}/words`,
    ),
};

export const clipVideoUrl = (c: Clip) => `/api/clips/${c.id}/video?v=${c.version}`;
export const clipDownloadUrl = (c: Clip) => `/api/clips/${c.id}/video?download=1`;
export const clipThumbUrl = (c: Clip) => `/api/clips/${c.id}/thumbnail?v=${c.version}`;
export const projectThumbUrl = (p: Project) => `/api/projects/${p.id}/thumbnail`;

export function uploadVideo(
  file: File,
  options: Record<string, unknown>,
  transcript: File | null,
  onProgress: (fraction: number) => void,
): Promise<Project> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("options", JSON.stringify(options));
    if (transcript) form.append("transcript", transcript);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300) resolve(data);
        else reject(new Error(data.detail || "Upload failed"));
      } catch {
        reject(new Error("Upload failed"));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed: server not reachable"));
    xhr.send(form);
  });
}

export async function downloadZip(projectId: string, clipIds: string[] | null): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clip_ids: clipIds }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(j.detail || "Export failed");
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : "clips.zip";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

export function fmtTime(sec: number): string {
  if (!isFinite(sec)) return "0:00";
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

export function fmtPrecise(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export function timeAgo(ts: number): string {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

/** Map edited caption text back onto timed words (token-level LCS alignment). */
export function alignWords(original: Word[], edited: string): Word[] {
  const tokens = edited.split(/\s+/).filter(Boolean);
  const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}']/gu, "");
  const a = original.map((w) => norm(w.w));
  const b = tokens.map(norm);
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] && a[i] !== "" ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: Word[] = [];
  let i = 0;
  let j = 0;
  let pendingNew: string[] = [];
  let pendingOld: Word[] = [];
  const flush = (nextStart: number) => {
    if (!pendingNew.length) {
      pendingOld = [];
      return;
    }
    let s: number;
    let e: number;
    if (pendingOld.length) {
      s = pendingOld[0].start;
      e = pendingOld[pendingOld.length - 1].end;
    } else {
      s = out.length ? out[out.length - 1].end : original[0]?.start ?? 0;
      e = Math.max(s + 0.2 * pendingNew.length, Math.min(nextStart, s + 0.3 * pendingNew.length));
    }
    const step = (e - s) / pendingNew.length;
    pendingNew.forEach((t, k) => out.push({ start: s + k * step, end: s + (k + 1) * step, w: t }));
    pendingNew = [];
    pendingOld = [];
  };
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j] && a[i] !== "") {
      flush(original[i].start);
      out.push({ ...original[i], w: tokens[j] });
      i++;
      j++;
    } else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) {
      pendingNew.push(tokens[j]);
      j++;
    } else {
      pendingOld.push(original[i]);
      i++;
    }
  }
  flush(Infinity);
  return out;
}
