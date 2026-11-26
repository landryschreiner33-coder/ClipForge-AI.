/** The viral predictor (clipfoundry/predictor/): a clip's prediction, Check a video, and how well it matched results. */
import { req } from "./api";

export type PredictorReason = { area: string; good: boolean | null; text: string; t?: number };
export type PredictorFix = {
  id: string; label: string; why: string; at: number | null;
  gain: { score: number; avg_view: number; rate: number; hook: number } | null;
  /** A one-press change to the clip's edit (null: advice). */
  edit: Record<string, unknown> | null; kind: "edit" | "advice";
};
export type Prediction = {
  model: number; score: number; band: string; duration: number; note: string; at?: number; version_id?: string;
  hook: { score: number; parts: { picture: number | null; sound: number | null; words: number | null };
    first_word_s: number | null; notes: string[] };
  peak: { t: number; value: number; in_hook: boolean; hook_vs_peak: number };
  hold: { rate: number; avg_view: number; avg_view_calibrated?: number; calibrated_on?: number; stay_after_swipe: number;
    /** The share still watching at 0 s, 1 s, ... (0-1). */
    curve: number[]; drops: { t: number; per_second: number; why: string }[]; open_loop: boolean };
  /** Per second, 0-1: what the modelled viewer gets from each channel. */
  channels: Record<"vision" | "sound" | "language" | "attention" | "memory", number[]>;
  measured: { picture: boolean; sound: boolean; words: boolean; speech: string };
  memory: { value: number; moments: number[] };
  components: Record<string, number | null>;
  reasons: PredictorReason[]; fixes: PredictorFix[]; words_note?: string;
};
export type ClipPrediction = { enabled: boolean; prediction: Prediction | null; rendered: boolean };
export type ViralCheck = {
  id: string; title: string; status: "queued" | "checking" | "ready" | "failed" | "canceled"; message: string;
  error: string; created_at: number; updated_at: number; media_url: string;
  summary: { score: number; band: string; hook: number | null; avg_view: number | null; rate: number | null; fixes: number } | null;
  result?: Prediction | null;
};
export type PlatformAccuracy = {
  posts: number; median_views: number; spearman: number | null; top_third_hit: number | null;
  bands: { band: string; posts: number; median_views: number; vs_median: number | null }[];
  avg_view_error: number | null; avg_view_posts: number;
};
export type PredictorAccuracy = {
  posts: number; platforms: Record<string, PlatformAccuracy>; min_posts: number; min_calibration: number;
  min_weights: number; designed_weights: Record<string, number>; at?: number; note: string;
  /** The Brain is paused: nothing learned is used (learned is null). */
  paused?: boolean;
  calibration?: { slope: number; intercept: number; n: number; shrink: number } | null;
  weights?: Record<string, number> | null;
  learned: { weights?: Record<string, number>; hold?: { n: number }; n?: number } | null;
};

export const predictor = {
  /** versionId: "" is the clip's own file, a version's id that version; left out, whichever file is posted. */
  ofClip: (clipId: string, versionId?: string) =>
    req<ClipPrediction>("GET", `/api/clips/${clipId}/prediction${versionId !== undefined
      ? `?version_id=${encodeURIComponent(versionId)}` : ""}`),
  predictClip: (clipId: string, versionId = "") =>
    req<{ prediction: Prediction }>("POST", `/api/clips/${clipId}/prediction`, { version_id: versionId }),
  accuracy: () => req<PredictorAccuracy>("GET", "/api/predictor/accuracy"),
  checks: () => req<ViralCheck[]>("GET", "/api/predictor/checks"),
  check: (id: string) => req<ViralCheck>("GET", `/api/predictor/checks/${id}`),
  addCheck: (body: { asset_id: string; title?: string; upload_ids?: string[] }) =>
    req<ViralCheck>("POST", "/api/predictor/checks", body),
  checkAgain: (id: string) => req<ViralCheck>("POST", `/api/predictor/checks/${id}/again`),
  cancelCheck: (id: string) => req<ViralCheck>("POST", `/api/predictor/checks/${id}/cancel`),
  deleteCheck: (id: string) => req<{ deleted: string; notes: string[] }>("DELETE", `/api/predictor/checks/${id}`),
};

export const PREDICTOR_NOTE =
  "A prediction from the clip's own picture, sound and words, to compare clips and find what to fix. Not a promise of views.";

export const CHANNEL_LABELS: [keyof Prediction["channels"], string, string][] = [
  ["vision", "Vision", "Movement, cuts, faces and text on screen"],
  ["sound", "Sound", "Loudness, sudden sounds, emphasis and reactions"],
  ["language", "Language", "Words per second, hook words, questions and payoffs"],
  ["attention", "Attention", "Something new to notice: it fades when nothing changes"],
  ["memory", "Memory", "Moments likely to stick or be shared"],
];

/** "0:07" / "1:02" from seconds. */
export function clock(t: number): string {
  const s = Math.max(0, Math.round(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The share of viewers that stay to the end, and the average watched, as written for people. */
export function watchedWords(p: Prediction): string {
  const avg = p.hold.avg_view_calibrated ?? p.hold.avg_view;
  return `about ${avg}% watched on average, ${p.hold.rate}% to the end`;
}
