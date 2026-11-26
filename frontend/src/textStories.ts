/**
 * Text Stories (clipfoundry/makers/textstory.py): a story read aloud over background video with big captions, and the
 * voice previews and favourite voices every maker can use (makers/voice_styles.py). Every change answers with the
 * whole story, so the page shows it at once.
 */
import { req, responseError } from "./api";

export type StoryVoice = { voice: string; style: string; speed: number; tone: number };
export type VoiceStyle = { id: string; name: string; about: string; speed: number; tone: number };
export type VoiceChoice = { id: string; name: string; lang: string; gender: string; about: string; engine: string };
export type Pronunciation = { word: string; say: string };
export type StoryCaptions = { style: string; position: string; size: string };
export type Background = {
  id: string; asset_id?: string; builtin?: string; in_s: number; out_s: number; loop: boolean; focus_x: number;
  focus_y: number; why: string;
  /** shown only: */
  filename?: string; name?: string; missing?: boolean; duration?: number; width?: number; height?: number;
  has_thumbnail?: boolean;
};
export type Made = { ready: boolean; current: boolean; duration?: number; at?: number; size?: number; url: string };
export type StoryStatus = "draft" | "writing" | "voicing" | "rendering" | "ready" | "failed";
export type Story = {
  id: string; name: string; own_name: string; title: string; script: string; words: number; seconds: number;
  voice: StoryVoice; pronunciations: Pronunciation[]; captions: StoryCaptions; backgrounds: Background[];
  status: StoryStatus; stage: "" | "write" | "preview" | "export"; message: string; error: string; working: boolean;
  job: { progress: number; message: string } | null;
  narration: { ready: boolean; voice?: string; fallback?: string; timing?: string; rule?: string; duration?: number };
  made: { preview: Made; export: Made };
  writer: { notes: string[] | null; model: string | null; local: boolean | null };
  project_id: string; updated_at: number;
  steps: { script: boolean; voice: boolean; background: boolean; preview: boolean; export: boolean };
};
export type StoryListItem = { id: string; name: string; status: StoryStatus; words: number; exported: boolean;
  updated_at: number };
export type Favourite = { voice: string; speed: number; tone: number; style: string };
export type StoryOptions = {
  voices: VoiceChoice[]; default_voice: string; styles: VoiceStyle[]; tone_range: [number, number];
  speed_range: [number, number];
  captions: { styles: { id: string; label: string }[]; positions: { id: string; label: string }[];
    sizes: { id: string; label: string }[] };
  builtins: { id: string; name: string; colors: string[] }[];
  writer: { configured: boolean; label: string; local: boolean };
  tones: { id: string; label: string }[]; lengths: { id: string; label: string }[];
  favourites: Record<string, Favourite>;
  limits: { max_words: number; max_title: number; wpm: number; max_backgrounds: number };
  links: { ai: string; makers: string };
};
export type BackgroundChoice = { asset_id: string; filename: string; duration: number; width: number; height: number;
  score: number; why: string };
export type StoryPatch = Partial<{ name: string; title: string; script: string; voice: Partial<StoryVoice>;
  pronunciations: Pronunciation[]; captions: Partial<StoryCaptions>; backgrounds: Partial<Background>[] }>;

const BASE = "/api/studio/text-stories";
const one = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export const textStories = {
  options: () => req<StoryOptions>("GET", `${BASE}/options`),
  list: () => req<{ stories: StoryListItem[] }>("GET", BASE),
  create: (body: { name?: string; title?: string; script?: string } = {}) => req<Story>("POST", BASE, body),
  get: (id: string) => req<Story>("GET", one(id)),
  change: (id: string, body: StoryPatch) => req<Story>("PATCH", one(id), body),
  remove: (id: string) => req<{ deleted: boolean }>("DELETE", one(id)),
  pickBackgrounds: (id: string) => req<Story>("POST", `${one(id)}/backgrounds/auto`),
  backgroundChoices: (id: string) =>
    req<{ videos: BackgroundChoice[] }>("GET", `${BASE}/backgrounds?text_story_id=${encodeURIComponent(id)}`),
  write: (id: string, body: { topic?: string; tone?: string; length?: string; change?: string }) =>
    req<Story>("POST", `${one(id)}/write`, body),
  preview: (id: string) => req<Story>("POST", `${one(id)}/preview`),
  export: (id: string) => req<Story>("POST", `${one(id)}/export`),
  stop: (id: string) => req<Story>("POST", `${one(id)}/stop`),
  openInEditor: (id: string) => req<{ video_id: string }>("POST", `${one(id)}/open-in-editor`),
  setFavourite: (scope: string, voice: Partial<StoryVoice> | null) =>
    req<{ favourites: Record<string, Favourite> }>("PUT", "/api/studio/voices/favourites", { scope, voice }),
  /** A few seconds of a voice at this speed and tone, as WAV, and what to tell the owner when another voice read it. */
  hear: async (v: { voice: string; speed: number; tone: number; text?: string }):
    Promise<{ blob: Blob; note: string }> => {
    const res = await fetch("/api/studio/voices/preview", {
      method: "POST", headers: { "Content-Type": "application/json", "X-ClipFoundry": "1" }, body: JSON.stringify(v),
    });
    if (!res.ok) throw await responseError(res);
    let note = "";
    try {
      note = decodeURIComponent(res.headers.get("X-ClipForge-Note") || "");
    } catch {
      note = "Another voice read this preview.";
    }
    return { blob: await res.blob(), note };
  },
};

/** "0:42", "1:05". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
