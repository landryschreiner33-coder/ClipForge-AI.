/**
 * Settings → Processing and the project page's Full Cloud card (docs/clipforge/FULL_CLOUD.md): where Make clips runs
 * (Local, Hybrid or Full Cloud), the owner's worker, worker time and its monthly limit, and the private test job.
 */
import { req } from "./api";

export type ProcessingMode = "local" | "hybrid" | "full_cloud";
export type WorkerStage = "ingest" | "transcribe" | "analyze" | "framing" | "captions" | "render";
export const STAGE_NAMES: Record<WorkerStage, string> = {
  ingest: "Getting the video", transcribe: "Transcription", analyze: "Finding the moments", framing: "Framing",
  captions: "Captions", render: "Rendering",
};
export type WorkerCheck = { ok: true; version?: string; whisper: { model?: string; device?: string };
  ai: string; busy?: boolean; jobs: { waiting?: number; finished?: number }; keep_hours?: number;
  max_upload_gb?: number } | { ok: false; why: string };
export type CloudRun = { id: string; kind: "project" | "test"; project_id: string; worker: string; status: string;
  started_at: number; ended_at: number | null; seconds: number; uploaded_bytes: number; cost: number | null };
export type WorkerTest = {
  id: string; status: string; worker: string; started_at: number; ended_at: number | null; seconds: number;
  ok?: boolean; problem?: string; note?: string; transcription_tried?: boolean; ran?: Partial<Record<WorkerStage, boolean>>;
  how?: Record<string, string>; upload_seconds?: number; upload_mbps?: number; uploaded_bytes?: number;
  worker_seconds?: number; round_trip_seconds?: number; cost?: number;
  clip?: { seconds: number; width: number; height: number; plays: boolean; bytes: number };
  worker_info?: { version?: string; whisper?: { model?: string; device?: string }; ai?: string };
  job: { status: string; progress: number; message: string; error: string } | null;
};
export type Processing = {
  mode: ProcessingMode;
  modes: { id: ProcessingMode; name: string; about: string; ready: boolean; why: string }[];
  pictures_on: string;
  worker: { url: string; host: string; key_set: boolean; check: WorkerCheck | null };
  price_per_hour: number | null; month_hours: number;
  usage: { used_seconds: number; limit_hours: number; price_per_hour: number | null; cost: number | null;
    resets_at: number; runs: CloudRun[] };
  stages: WorkerStage[]; unsupported: string[]; test: WorkerTest | null; note?: string;
};
/** The project page's Full Cloud card (GET /api/projects/{id} → cloud). */
export type ProjectCloud = {
  phase: "waiting" | "upload" | "running" | "fetching" | "done" | "failed" | "canceled" | "gone";
  worker: string; uploaded: { what?: string; name: string; link: string; bytes: number }[];
  estimate: { seconds: number | null; cost: number | null; price: number | null; known: boolean } | null;
  seconds: number | null; cost: number | null; ran: Partial<Record<WorkerStage, boolean>>; how: Record<string, string>;
  log: { at: number; text: string }[]; worker_info: { version?: string; whisper?: { model?: string; device?: string };
    ai?: string }; unsupported: string[]; clips?: number | null;
};

export const processing = {
  get: (check = false) => req<Processing>("GET", `/api/processing${check ? "?check=true" : ""}`),
  set: (body: { mode?: ProcessingMode; price_per_hour?: number; month_hours?: number }) =>
    req<Processing>("PUT", "/api/processing", body),
  worker: (url: string, key?: string) => req<Processing>("POST", "/api/processing/worker",
    key === undefined ? { url } : { url, key }),
  test: () => req<{ test: WorkerTest }>("POST", "/api/processing/test"),
  stopTest: () => req<{ test: WorkerTest | null }>("POST", "/api/processing/test/stop"),
};

export function fmtSpan(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  return m < 120 ? `${m} min` : `${(s / 3600).toFixed(1)} h`;
}

export function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  return n < 0.01 && n > 0 ? "under $0.01" : `$${n.toFixed(2)}`;
}

export function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return n < 1024 ** 3 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024 ** 3).toFixed(2)} GB`;
}
