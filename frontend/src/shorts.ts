/**
 * Animated shorts (docs/clipforge/ANIMATED_SHORTS.md): the types the Make page and the editor's Scenes panel read, and
 * the /api/studio/shorts calls. Every change answers with the whole video, the same object as GET
 * /api/studio/videos/{id}, so the page updates at once.
 */
import { req, responseError } from "./api";
import type { Video } from "./studio";

/** What one local maker can do right now ("why" says what is missing when it is not ready). */
export type EngineStatus = { ready: boolean; engine: string; why: string; available: boolean; remote?: boolean;
  /** The picture model keeps a character's look from reference pictures (FLUX.2 klein); else from the words only. */
  references?: boolean };
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
  transitions: { id: ShortTransition; label: string }[];
  /** How long a scene may stay after its words, in ms (the owner's timing). */
  holds_ms: number[];
  cast: CastOptions;
};

export type ShortTransition = "cut" | "dissolve" | "fade";
export type CastKind = "character" | "place";
export type CastField = "appearance" | "clothing" | "colors" | "props";
export type CastOptions = {
  kinds: { id: CastKind; label: string }[]; fields: Record<CastKind, CastField[]>;
  labels: Record<CastKind, Partial<Record<CastField, string>>>; lockable: (CastField | "references")[];
  max_cast: number; max_refs: number; max_field: number; max_name: number; max_change: number;
};
/** A character or place: in the library (id = library_id) or a short's own copy (id "cm-…"). */
export type CastMember = {
  id: string; library_id: string; kind: CastKind; name: string; appearance: string; clothing: string; colors: string;
  props: string; locked: (CastField | "references")[]; refs: { asset_id: string; ok: boolean }[];
  /** The words the picture maker reads. */
  described: string;
  /** A short's copy only: "same" as its library entry, "differs", or "none" (not in the library). */
  library?: "same" | "differs" | "none";
};
export type CastFields = Partial<Pick<CastMember, "kind" | "name" | CastField | "locked">> & { refs?: string[] };
export type CastProposal = { changes: Partial<Record<CastField, string>>; kept: CastField[]; note: string;
  model: string };
export type DriftFlag = { member: string; name: string; detail: string; why: string };
export type SceneStatus = "waiting" | "voice" | "picture" | "motion" | "ready" | "failed";
export type ShortScene = {
  id: string; n: number; narration: string; picture_prompt: string; picture_source: "auto" | "upload";
  /** "" until the picture is made; its thumbnail is /api/assets/{id}/thumbnail. */
  picture_asset_id: string;
  clip_asset_id: string;
  /** "auto" or one of zoom_in zoom_out pan_left pan_right pan_up pan_down push_left push_right still. */
  move: string;
  status: SceneStatus; message: string; error: string;
  /** Seconds. */
  duration: number;
  picture: { source: "engine" | "card" | "upload" | ""; engine: string; why: string;
    /** Reference pictures the maker drew with, and how many it was given (a words-only model uses none). */
    references?: number; asked_references?: number;
    /** A short without characters: the scene whose picture this one was drawn with, so the main character looks the
     * same (0: none). */
    kept_from?: number };
  /** The cast members in this shot (all of the short's unless the owner picked: cast_chosen). */
  cast?: string[]; cast_chosen?: boolean;
  /** Changes for this shot only, by member id. */
  overrides?: Record<string, Partial<Record<CastField, string>>>;
  /** How long it stays after its words, in ms. */
  hold_ms?: number;
  /** What the look check found in the current picture (null: not checked, or the owner's own picture). */
  drift?: { flags: DriftFlag[]; how: "colours" | "looked" | ""; ok: boolean } | null;
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
  transition?: ShortTransition; cast?: CastMember[];
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
  hold_ms?: number;
  /** Who is in the shot; all_cast puts everyone back. */
  cast?: string[]; all_cast?: boolean;
  /** The owner looked at a flagged picture and it is right. */
  drift_ok?: boolean;
};
/** The picture maker's own examples of the looks (makers/look_examples.py), and the job that draws them. */
export type LookExamples = {
  examples: Record<string, { url: string; engine: string; at: number }>;
  job: { status: string; progress: number; message: string; error: string } | null;
  can_make: boolean; why: string;
};
export type ShortOptionsPatch = Partial<{ voice: string; speed: number; look: string; music: string; captions: string;
  motion: ShortMotion; transition: ShortTransition }>;

const scenes = (videoId: string) => `/api/studio/shorts/${encodeURIComponent(videoId)}/scenes`;
const cast = (videoId: string) => `/api/studio/shorts/${encodeURIComponent(videoId)}/cast`;
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
  // ---- the picture maker's examples of the looks
  lookExamples: () => req<LookExamples>("GET", "/api/studio/shorts/look-examples"),
  makeLookExamples: () => req<LookExamples>("POST", "/api/studio/shorts/look-examples"),
  stopLookExamples: () => req<LookExamples>("POST", "/api/studio/shorts/look-examples/stop"),
  // ---- characters and places (makers/cast.py)
  library: () => req<{ library: CastMember[] }>("GET", "/api/studio/cast"),
  libraryAdd: (body: CastFields) => req<CastMember>("POST", "/api/studio/cast", body),
  libraryChange: (id: string, body: CastFields) => req<CastMember>("PATCH", `/api/studio/cast/${encodeURIComponent(id)}`, body),
  libraryDelete: (id: string) => req<{ deleted: boolean }>("DELETE", `/api/studio/cast/${encodeURIComponent(id)}`),
  castAdd: (videoId: string, body: CastFields & { library_id?: string; save?: boolean }) =>
    req<Video>("POST", cast(videoId), body),
  castChange: (videoId: string, memberId: string, body: CastFields) =>
    req<Video>("PATCH", `${cast(videoId)}/${encodeURIComponent(memberId)}`, body),
  castRemove: (videoId: string, memberId: string) => req<Video>("DELETE", `${cast(videoId)}/${encodeURIComponent(memberId)}`),
  castToLibrary: (videoId: string, memberId: string) =>
    req<Video>("POST", `${cast(videoId)}/${encodeURIComponent(memberId)}/library`),
  /** A reference picture: an upload of the owner's (asset_id with the page's upload_ids) or a scene's picture. */
  castReference: (videoId: string, memberId: string, body: { asset_id?: string; upload_ids?: string[]; scene_id?: string }) =>
    req<Video>("POST", `${cast(videoId)}/${encodeURIComponent(memberId)}/reference`, body),
  /** What ClipForge AI would change for the owner's words; nothing is saved. */
  castPropose: (videoId: string, memberId: string, words: string, sceneId?: string) =>
    req<CastProposal>("POST", `${cast(videoId)}/${encodeURIComponent(memberId)}/propose`, { words, scene_id: sceneId }),
  /** Changes for every shot (no sceneId) or for one shot. */
  castApply: (videoId: string, memberId: string, changes: Partial<Record<CastField, string>>, sceneId?: string) =>
    req<Video & { applied: { changed: CastField[]; kept: CastField[] } }>("POST",
      `${cast(videoId)}/${encodeURIComponent(memberId)}/apply`, { changes, scene_id: sceneId }),
  clearOverride: (videoId: string, sceneId: string, memberId: string) =>
    req<Video>("DELETE", `${scenes(videoId)}/${encodeURIComponent(sceneId)}/overrides/${encodeURIComponent(memberId)}`),
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
