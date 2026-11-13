/**
 * Animated shorts (docs/clipforge/ANIMATED_SHORTS.md): the types the Make page and the editor's Scenes panel read, and
 * the /api/studio/shorts calls. Every change answers with the whole video, the same object as GET
 * /api/studio/videos/{id}, so the page updates at once.
 */
import { req, responseError } from "./api";
import type { Video } from "./studio";

/** What one local maker can do right now ("why" says what is missing when it is not ready). */
export type EngineStatus = { ready: boolean; engine: string; why: string; available: boolean };
export type ShortEngines = { available: boolean; image: EngineStatus; video: EngineStatus; voice: EngineStatus };
/** A look: how every picture is drawn. top, bottom and accent are hex colours for a swatch. */
export type ShortLook = { id: string; name: string; about: string; top: string; bottom: string; accent: string };
export type ShortVoice = { id: string; name: string; lang: string; gender: string; about: string; engine: string };
export type ShortLength = "short" | "standard" | "long";
/** "" follows the look's own caption style. */
export type ShortCaptions = "" | "bold" | "high_energy" | "clean" | "off";
export type ShortMusic = "calm" | "balanced" | "energetic" | "none";
export type ShortMotion = "camera" | "animate";
export type ShortMode = "paste" | "write";
/** Whether ClipForge AI can write, under which name, and whether it runs on this computer. */
export type ShortWriter = { configured: boolean; label: string; local: boolean };

export type ShortOptions = {
  looks: ShortLook[];
  /** "auto" is first. */
  voices: ShortVoice[];
  default_voice: string;
  tones: { id: string; label: string }[];
  lengths: { id: ShortLength; label: string; min: number; max: number; target: number }[];
  captions: { id: ShortCaptions; label: string }[];
  music: { id: ShortMusic; label: string }[];
  speeds: { value: number; label: string }[];
  engines: ShortEngines;
  writer: ShortWriter;
  /** "listened": a speech model times the words exactly; "estimated": they are timed from the sound. */
  timing: "listened" | "estimated";
  limits: { max_words: number; max_scenes: number; wpm: number };
  /** "#/settings/makers" and "#/settings/ai". */
  links: { makers: string; ai: string };
};

export type SceneStatus = "waiting" | "voice" | "picture" | "motion" | "ready" | "failed";
export type ShortScene = {
  id: string; n: number; narration: string; picture_prompt: string; picture_source: "auto" | "upload";
  /** "" until the picture is made; its thumbnail is /api/assets/{id}/thumbnail. */
  picture_asset_id: string;
  clip_asset_id: string;
  /** "auto" or one of zoom_in zoom_out pan_left pan_right pan_up pan_down still. */
  move: string;
  status: SceneStatus; message: string; error: string;
  /** Seconds. */
  duration: number;
  picture: { source: "engine" | "card" | "upload" | ""; engine: string; why: string };
  /** fallback: why another voice read this scene ("" when the chosen voice did); Try again asks the chosen one. */
  voice: { engine: string; voice: string; timing: "engine" | "listened" | "estimated" | ""; fallback?: string };
  /** Earlier pictures of this scene, newest first. */
  earlier: { asset_id: string; prompt: string; source: string }[];
  /** The scene has a clip in the current plan (clip id == scene id). */
  in_plan: boolean;
  /** Its clip is switched on in the sequence. */
  included: boolean;
  /** Where its picture idea came from: "script" ([Visual: …] lines), "ai", "words" (its own words) or "owner". */
  picture_from?: string;
  /** Its clip was taken out of the sequence in the editor (a scene made again comes back). */
  replaced?: boolean;
};
/** "stopped": the owner pressed Stop; Make the short goes on. */
export type ShortStage = "writing" | "review" | "making" | "ready" | "failed" | "stopped";
export type ShortView = {
  stage: ShortStage; message: string; mode: ShortMode; topic: string; tone: string; length: string; audience: string;
  look: string; voice: string; speed: number; music: string; captions: string; motion: ShortMotion; review: boolean;
  title: string; character: string; scenes: ShortScene[]; progress: { done: number; total: number }; seconds: number;
  engines: ShortEngines;
  /** Designed cards the picture maker (ready now) would swap for real pictures: Draw real pictures does it. */
  cards_to_swap?: number;
  writer: ShortWriter & { used: { model: string; memories: number; knowhow: string[] } | null };
  /** What the licence of the voice that spoke it asks of what it makes ("" for none); shown next to Download. */
  voice_rule?: string;
  notes: string[];
};

export type ShortCreate = {
  name: string; mode: ShortMode; script?: string; topic?: string; tone?: string; length?: ShortLength; audience?: string;
  look: string; voice: string; speed: number; music: string; captions: string; motion: ShortMotion; review: boolean;
};
export type ScenePatch = {
  narration?: string; picture_prompt?: string; move?: string;
  /** The owner's uploaded image, or one of the scene's earlier pictures. */
  picture_asset_id?: string;
  /** The page's uploads of that image, also one dropped again after a change failed (none for an earlier picture
   * chosen again). */
  upload_ids?: string[];
  new_picture?: boolean; again?: boolean;
};
export type ShortOptionsPatch = Partial<{ voice: string; speed: number; look: string; music: string; captions: string;
  motion: ShortMotion }>;

const scenes = (videoId: string) => `/api/studio/shorts/${encodeURIComponent(videoId)}/scenes`;
let optionsCall: Promise<ShortOptions> | null = null;

export const shorts = {
  /** The choices for a short. Kept for this page visit; `fresh` asks again (engines may have been set up since). */
  options: (fresh = false): Promise<ShortOptions> => {
    if (fresh || !optionsCall) {
      const call = req<ShortOptions>("GET", "/api/studio/shorts/options");
      optionsCall = call;
      call.catch(() => {
        if (optionsCall === call) optionsCall = null;  // a failed load is asked again next time
      });
    }
    return optionsCall;
  },
  create: (body: ShortCreate) => req<Video>("POST", "/api/studio/shorts", body),
  /** A few seconds of a voice, as WAV, and what to tell the owner when another voice had to read it ("" if none). */
  voiceSample: async (voice: string, speed: number): Promise<{ blob: Blob; note: string }> => {
    const res = await fetch("/api/studio/shorts/voice-sample", {
      method: "POST", headers: { "Content-Type": "application/json", "X-ClipFoundry": "1" },
      body: JSON.stringify({ voice, speed }),
    });
    if (!res.ok) throw await responseError(res);
    let note = "";
    try {
      note = decodeURIComponent(res.headers.get("X-ClipForge-Note") || "");
    } catch {
      note = "Another voice read this sample.";
    }
    return { blob: await res.blob(), note };
  },
  patchScene: (videoId: string, sceneId: string, body: ScenePatch) =>
    req<Video>("PATCH", `${scenes(videoId)}/${encodeURIComponent(sceneId)}`, body),
  /** A new scene after `after` (a scene id; null puts it at the start). */
  addScene: (videoId: string, body: { after: string | null; narration: string; picture_prompt?: string }) =>
    req<Video>("POST", scenes(videoId), body),
  deleteScene: (videoId: string, sceneId: string) =>
    req<Video>("DELETE", `${scenes(videoId)}/${encodeURIComponent(sceneId)}`),
  /** Go on after the script was checked, or make every scene that needs it. */
  make: (videoId: string) => req<Video>("POST", `/api/studio/shorts/${encodeURIComponent(videoId)}/make`),
  setOptions: (videoId: string, body: ShortOptionsPatch) =>
    req<Video>("PUT", `/api/studio/shorts/${encodeURIComponent(videoId)}/options`, body),
};

// Lines that say what a picture shows, not what the voice says: [Visual: ...], (b-roll ...), "Show: ...", "Scene 3".
const DIRECTION = new RegExp(
  "^\\s*(?:\\[[^\\]]*\\]|\\((?:b-?roll|visual|show|picture|image|shot|scene|cut to|on screen)\\b[^)]*\\)"
  + "|(?:visual|show|picture|image|b-?roll|shot|on screen)\\s*:.*|(?:scene|part)\\s+\\d+\\s*[:.)-]?)\\s*$", "i");

/** About how many words the voice says in a pasted script: direction lines and [bracketed] notes are not spoken. */
export function spokenWords(text: string): number {
  let n = 0;
  for (const line of text.split(/\r?\n/)) {
    if (DIRECTION.test(line)) continue;
    n += line.replace(/\[[^\]]*\]/g, " ").split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
  }
  return n;
}

/** How long the words take to say: words × 60 / (words a minute × speed), in seconds. */
export const speakingSeconds = (words: number, wpm: number, speed: number) =>
  words > 0 ? (words * 60) / (Math.max(1, wpm) * Math.max(0.1, speed)) : 0;

/** "About 42 s", "About 1 min 25 s". */
export function aboutLength(seconds: number): string {
  const s = Math.max(1, Math.round(seconds));
  if (s < 60) return `About ${s} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `About ${m} min${r ? ` ${r} s` : ""}`;
}
