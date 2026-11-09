/** ClipForge studio API: uploads, Make clips, full videos, stories, styles, skills, accounts, preferences. */
import { req, responseError } from "./api";

export type Asset = { id: string; kind: "video" | "audio" | "image"; filename: string; sha256: string; size: number;
  duration?: number; width?: number; height?: number; fps?: number; has_audio?: boolean; has_thumbnail: boolean;
  /** The owner's own file used where it is on this computer (desktop), not a copy ClipForge keeps. */
  linked?: boolean;
  /** A small preview copy of a big video exists (previews read it; the final render never does). */
  proxy?: boolean };
/** A folder of this computer the owner may pick footage from (desktop only). */
export type LocalRoot = { label: string; path: string };
export type LocalListing = { path: string; parent: string; roots: LocalRoot[];
  folders: { name: string; path: string }[];
  files: { name: string; path: string; size: number; kind: "video" | "audio" | "image"; modified: number }[];
  truncated: boolean };
/** A script as ClipForge read it (what /api/studio/scripts/parse returns and a video keeps). */
export type ScriptLine = { n: number; text: string; kind: "line" | "heading" | "direction"; speaker: string; section: string };
export type Script = { filename: string; format: string; text?: string; lines: ScriptLine[];
  counts: { lines: number; headings: number; directions: number; words: number } };
/** How the plan matched each script line: the clip that plays it and the other takes behind it. */
export type ScriptMatch = { n: number; status: "matched" | "weak" | "missing" | "skipped" | "heading" | "direction";
  coverage: number; clip_id: string; takes: { clip_id: string; coverage: number; quality: number }[] };
export type Upload = { id: string; filename: string; kind: string; size: number; received: number; status: string;
  error: string; asset_id: string; chunk_size: number };

export type Decision = { field: string; value: unknown; text: string; from: Entry; also: Entry[];
  overridden: (Entry & { value: unknown; reason: string })[] };
export type Entry = { level: string; id: string; revision: number; name: string };
export type LinkProblem = { code: string; label: string; why: string; fix: string; temporary: boolean };
export type LinkCheck = { ok: boolean; url?: string; platform?: string; video_id?: string; problem?: LinkProblem };
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
  source: string; is_default: boolean; effects: string[]; reference_id?: string;
  provenance?: { analysis_revision?: number; title?: string; method?: string;
    corrections?: { field: string; measured: unknown; chosen: unknown }[]; reference_deleted_at?: number } };

export type Evidence = { start_ms: number; end_ms: number; label?: string };
export type Observation = { id: string; aspect: string; kind: "measured" | "estimate"; text: string; evidence: Evidence[];
  confidence?: number };
export type ApplyChoice = { field: string; value: unknown; aspect: string; why: string; selected: boolean; modes: string[];
  label: string; text: string };
export type ExampleVideo = { id: string; asset_id: string; title: string; likes: string[]; note: string;
  ranges: { start_ms: number; end_ms: number }[]; scope: "chosen" | "all" | "modes"; modes: string[];
  status: "queued" | "analyzing" | "ready" | "failed" | "canceled"; message: string; error: string;
  analysis_revision: number; avoid: boolean; project_only: boolean; enabled: boolean; media_url: string;
  progress: number | null; style: Style | null; duration_ms: number; updated_at: number;
  analysis?: { revision: number; analyzer: string; method: string; model_note: string; speech_note: string;
    reused_from: string; created_at: number; observations: Observation[]; applicable: ApplyChoice[];
    unsupported: { aspect: string; text: string }[];
    coverage: { ranges: { start_ms: number; end_ms: number }[]; seconds?: number; frames_compared: number;
      scan_fps?: number; stills: number; still_method?: string; audio_seconds?: number; speech?: string } } };
export type Field = { name: string; label: string; kind: "choice" | "bool" | "number" | "text"; modes: string[];
  choices: (string | number)[]; minimum: number | null; maximum: number | null; applies: string };
export type Skill = { id: string; skill_key: string; name: string; description: string; version: string; revision: number;
  modes: string[]; supported: Record<string, unknown>; unsupported: { text: string; why: string }[];
  blocked: { text: string; why: string }[]; enabled: boolean; effects: string[]; original_format: string };

/** The Brain map: every style, skill and example video, and the projects whose recorded guidance used them. */
export type BrainMapExample = { id: string; title: string; status: string; enabled: boolean; avoid: boolean;
  scope: "chosen" | "all" | "modes"; modes: string[]; likes: string[]; note: string; analysis_revision: number;
  style_id: string; updated_at: number };
export type BrainMapLink = { node: string; revision: number | null; name: string; fields: string[] };
export type BrainMapProject = { id: string; kind: "clips" | "full_video"; name: string; href: string; at: number;
  mode: string; links: BrainMapLink[] };
export type BrainMap = { styles: (Style & { updated_at?: number })[];
  skills: Omit<Skill, "unsupported" | "blocked">[]; examples: BrainMapExample[]; projects: BrainMapProject[];
  omitted_projects: number; applied: { node: string; at: number; project: string }[]; recent_seconds: number };

export type LibraryItem = { id: string; kind: "clips" | "full_video"; mode: string; name: string; status: string;
  message?: string; stage?: string; progress?: number; error?: string; clip_count?: number; updated_at: number;
  thumbnail: string; href: string };

export type PlanClip = { id: string; asset_id: string; kind: string; in_ms: number; out_ms: number; label: string;
  gain_db: number; include: boolean; must_keep?: string[]; mute?: boolean; fade_in_ms?: number; fade_out_ms?: number;
  layout?: string | null; join?: "cut"; zoom?: number;
  /** The cold open: the strongest line, playing first (it plays again where it was said). */
  hook?: boolean;
  /** Script mode: the lines this clip plays (with each line's bounds), or the line it is another take of,
   * or speech that is not in the script. */
  take_of?: { lines?: number[]; takes?: Record<string, { in_ms: number; out_ms: number; coverage?: number; quality?: number }>;
    line?: number; coverage?: number; quality?: number; off_script?: boolean } };
/** A picture (or muted video) shown over a clip while its sound goes on. */
export type Overlay = { id: string; asset_id: string; clip_id: string; offset_ms: number; length_ms: number;
  motion: "still" | "zoom"; fit?: "fill" | "fit"; label: string; auto?: boolean; why?: string };
export type SmartLevel = "off" | "smart" | "tight";
export type SmartReport = { level: SmartLevel; options: Record<string, unknown>;
  /** True when the cut follows the project's script (script_cut.py) rather than the smart edit's rules. */
  script?: boolean;
  stats: { pauses_cut: number; seconds_saved: number; trimmed_s: number; retakes: number; takes?: number; chatter?: number;
    stumbles?: number; ai_left_out: number; fit_left_out: number; fillers: number; overlays: number; effects: number;
    music: string; cold_open?: string; lines_found?: number; lines_missing?: number; alternatives?: number; off_script_s?: number };
  ai: { used: boolean; provider?: string; sent?: string; local?: boolean; problems?: string[]; problem?: string;
    windows?: number; read?: number; budget_s?: number; not_sent?: number; skipped_sentences?: number;
    hook?: { i: number; why: string } | null };
  picture_queries: { query: string; clip_id: string; offset_ms: number }[] };
export type AudioRole = "voiceover" | "music" | "effect";
export type AudioItem = { id: string; asset_id: string; role: AudioRole; label: string; start_ms: number; in_ms: number;
  out_ms: number | null; length_ms: number | null; gain_db: number; mute: boolean; fade_in_ms: number; fade_out_ms: number;
  duck: boolean; loop: boolean; anchor: { clip_id: string; offset_ms: number } | null; auto?: boolean };
export type TrackName = "source" | "voiceover" | "music" | "effects";
export type Plan = { schema: number; output: { aspect: string; fps: number }; layout: string; clean_sound?: string; clips: PlanClip[];
  transition: { type: string; ms: number }; title: { enabled: boolean; text: string; ms: number };
  captions: { enabled: boolean; style: string; position: string; size?: string };
  audio: AudioItem[]; tracks: Record<TrackName, { gain_db: number; mute: boolean }>; ducking?: { depth_db: number };
  word_fixes?: Record<string, Record<string, string>>;
  outline: { clip_id: string; label: string; summary: string; duration: number; keeps?: string[] }[]; notes: string[];
  overlays?: Overlay[]; chapters?: { clip_id: string; offset_ms?: number; title: string }[]; smart?: SmartReport;
  /** Script mode: how each script line was matched (the text lives in Video.script). */
  script?: { filename: string; stats: Record<string, number>; lines: ScriptMatch[] };
  /** Set on a version finished by hand in FilmCraft's editor (rendered by FilmCraft from that save). */
  filmcraft?: { project: string; saved_at: number; opened_on: number } };
export type Segment = { clip_id: string; asset_id: string; kind: string; src_in_ms: number; src_out_ms: number;
  out_start_ms: number; out_end_ms: number };
export type Placed = { audio_id: string; asset_id: string; role: AudioRole; track: TrackName; out_start_ms: number;
  out_end_ms: number; src_in_ms: number; loop: boolean; cut_ms: number };
export type Video = { id: string; name: string; status: string; message: string; asset_ids: string[];
  brief: Record<string, unknown>; plan_revision: number; rendered_revision: number; guidance: Snapshot; plan: Plan | null;
  duration: number; assets: Asset[]; bin: string[]; timeline: Segment[]; audio_timeline: Placed[];
  artifacts: ({ id: string; revision: number; kind: string; sha256: string; duration: number; audio_ok: boolean } &
    MadeWith)[];
  preview: { revision: number; stale: boolean } | null;
  jobs: { id: string; kind: string; revision: number; status: string; progress: number; message: string; error: string }[];
  revisions: { revision: number; note: string; name: string; action: string; created_at: number }[];
  can_undo: boolean; can_redo: boolean;
  capabilities: { tracks: Record<TrackName, string>; caption_sizes: string[]; caption_positions: string[]; fps: number[];
    duck_depth_db: { default: number; range: [number, number] }; limits: string };
  sources?: Record<string, AssetSource[]>; credits?: Credit[]; media_rules?: MediaRules;
  overlay_timeline?: { overlay_id: string; asset_id: string; clip_id: string; out_start_ms: number; out_end_ms: number }[];
  chapters?: { title: string; ms: number }[]; smart?: SmartReport | null;
  /** The script this video follows (null for none). */
  script?: Script | null;
  /** The plan made with ClipForge AI before the build (null for a video made without one). */
  setup?: { mode: SetupMode; plan: PlanFields; lines: string[]; source: string; pending: boolean } | null;
  /** Still being planned with ClipForge AI: its page is the setup page (#/create/video/<id>). */
  planning?: boolean;
  ai_helper?: { configured: boolean; label: string; local: boolean } };

// ------------------------------------------------------------------ planning a video with ClipForge AI
export type SetupMode = "ask" | "auto";
/** "" leaves a choice to your style and Brain. */
export type Tri = "" | "on" | "off";
export type PlanFields = { title: string; summary: string; video_type: string; audience: string; goal: string;
  length_min: number; aspect_ratio: "" | "16:9" | "9:16" | "1:1" | "4:5"; feel: "" | "calm" | "balanced" | "energetic";
  edit: SmartLevel; opening: string; story: string[]; keep: string[]; cut: string[];
  music: "" | "auto" | "library" | "mine" | "find" | "none"; music_file: string; voiceover_files: string[];
  captions: Tri; pictures: Tri; sound_effects: Tri; zooms: Tri; cold_open: Tri; order: string[]; notes: string[];
  find_media: "" | "suggest" | "auto" };
export type SetupQuestion = { id: string; q: string; choices: string[] };
export type SetupMessage = { id: string; chat_id?: string; role: "owner" | "ai" | "agent"; text: string;
  status: "done" | "thinking" | "failed"; created_at: number; updated_at?: number;
  data: { tool?: string; say?: string; plan?: PlanFields; lines?: string[]; questions?: SetupQuestion[];
    ask?: { question: string; choices: string[] }; source?: "ai" | "rules"; sent?: string; remote?: boolean; provider?: string;
    used?: { kind: string; text: string }[];
    knowhow?: { title: string }[]; answers?: string; building?: boolean;
    helpers?: { agent: { id: string; name: string; icon: string }; text: string; ok: boolean }[] } };
export type SetupFile = { id: string; kind: "video" | "image" | "audio"; filename: string; duration: number;
  /** For a video: being listened to, waiting its turn, nothing said in it, or heard. */
  state: "" | "listening" | "waiting" | "silent" | "heard"; words: number; thumbnail: boolean };
export type VideoSetup = { id: string; name: string; status: string; message: string; mode: SetupMode; plan: PlanFields;
  lines: string[]; locked: string[]; source: string; planned: boolean; rounds: number; open: SetupQuestion[];
  files: SetupFile[]; chat_id: string; messages: SetupMessage[]; thinking: boolean; listening: boolean;
  style_id: string; reference_id: string; remember: { enabled?: boolean; name?: string }; script: Script | null;
  model: { ready: boolean; label: string; local: boolean };
  /** Still being planned here; false once it is being made (or for a video never planned here). */
  planning: boolean; href: string };

export type MediaKind = "image" | "footage" | "music" | "effect";
export type MediaTerms = { known: boolean; commercial: boolean; modify: boolean; attribution: boolean; share_alike: boolean };
export type MediaResult = { id: string; provider: string; provider_name: string; kind: MediaKind; external_id: string;
  title: string; creator: string; creator_url: string; page_url: string; origin: string; license: string;
  license_version: string; license_name: string; license_url: string; terms: MediaTerms; restrictions: string;
  width: number | null; height: number | null; duration_s: number | null; filetype: string; credit: string;
  preview: { image?: string; audio?: string; video?: string };
  fits: { eligible: boolean; reasons: string[]; credit_required: boolean } };
export type ProviderStatus = { id: string; name: string; state: string; message: string; count: number; cached: boolean;
  retry_after: number | null; notice: string };
export type MediaSearchResult = { kind: MediaKind; query: string; page: number; results: MediaResult[]; providers: ProviderStatus[] };
export type MediaProvider = { id: string; name: string; kinds: MediaKind[]; supplies: string; key_required: boolean;
  key_saved: boolean; key_help: string; limits: string; terms_url: string; docs_url: string; notice: string;
  enabled: boolean; state: string; message: string };
export type MediaImport = { id: string; result_id: string; project_id: string; provider: string; kind: MediaKind; title: string;
  status: "queued" | "importing" | "ready" | "failed" | "canceled"; message: string; error: string; asset_id: string;
  progress: number; job_message: string };
export type AssetSource = { provider: string; provider_name: string; kind: MediaKind; title: string; creator: string;
  page_url: string; origin: string; license_name: string; license_url: string; terms: MediaTerms; credit: string;
  credit_required: boolean; restrictions: string; user_basis: string; retrieved_at: number };
export type Credit = { key: string; asset_id: string; provider_name: string; title: string; creator: string; required: boolean;
  generated: string; text: string; edited: boolean; license_name: string; license_url: string; page_url: string; user_basis: string };
export type MediaRules = { mode: "suggest" | "auto"; commercial: boolean; share_alike: boolean };
export type Suggestions = { rules: MediaRules; latest: null | { round: number; mode: string; status: string; message: string;
  queries: { kind: MediaKind; query: string; why: string }[];
  items: { kind: MediaKind; query: string; why: string; results: MediaResult[] }[];
  added: { asset_id: string; kind: MediaKind; title: string; query: string }[]; problems: string[] } };

export type ChangeRequest = { id: string; project_id: string; base_revision: number; text: string;
  status: "thinking" | "ready" | "question" | "unsupported" | "invalid" | "failed" | "canceled" | "applied" | "stale";
  source: "rules" | "ai"; provider: string; sent: string; message: string; applied_revision: number; created_at: number;
  memories?: { id: string; kind: string; text: string; score?: number }[]; knowhow?: { id: string; title: string; score?: number }[];
  proposal: { format?: string; summary?: string; operations?: Record<string, unknown>[]; changes?: string[]; notes?: string[];
    question?: string; choices?: { label: string; request: string }[]; duration_ms?: [number, number] } };

/** Which editor made a rendered version, and what FilmCraft, EffectCraft and the AI did in it. */
export type MadeWith = { engine?: string; fallback?: string; filmcraft?: { hand_edited: boolean; steps: number;
  failed: number; shots: { what: string; app: string; use: string }[]; notes: string[];
  ai: { used: boolean; summary: string; provider: string; steps: number; refused: number } | null } };

/** FilmCraft and EffectCraft inside ClipForge (Settings, Editing apps). */
export type CraftApp = { key: string; label: string; what: string; version: string; page: string;
  cli: { ready: boolean; source: string; version: string; bytes: number }; web: { ready: boolean; bytes: number } | null };
export type CraftStatus = { platform: string; supported: boolean; online: boolean; can_install: boolean; apps: CraftApp[];
  ready: boolean; missing_bytes: number; engine: "auto" | "filmcraft" | "ffmpeg"; ai_finish: boolean; auto_install: boolean;
  ai_disclosure: string; editor: boolean;
  task: { state: string; app: string; part: string; done: number; total: number; error: string } };
/** FilmCraft's editor on one version: its project and the files it uses, or the job making the AI's edit. */
export type EditorSession = { revision: number; editor: string; editor_ready: boolean; cli_ready: boolean; ready: boolean;
  hand: boolean; job: { id: string; status: string; progress: number; message: string; error: string } | null;
  media?: { name: string; url: string; bytes: number }[]; media_query?: string; project?: string; project_name?: string;
  steps?: number; failed?: string[]; notes?: string[]; shots?: { what: string; app: string; use: string }[];
  ai?: { used?: boolean; summary?: string; provider?: string; steps?: number; refused?: string[]; why?: string } };

export const craft = {
  status: () => req<CraftStatus>("GET", "/api/craft"),
  install: () => req<CraftStatus>("POST", "/api/craft/install", { parts: ["cli", "web"] }),
  editor: (id: string, revision: number) =>
    req<EditorSession>("GET", `/api/studio/videos/${id}/filmcraft/editor?revision=${revision}`),
  prepare: (id: string, revision: number) =>
    req<EditorSession>("POST", `/api/studio/videos/${id}/filmcraft/prepare`, { revision }),
};

/** FilmCraft (the free open-source editor from the ArtCraft team) on this computer. */
export type FilmCraftStatus = { available: boolean; installed: boolean; app?: boolean; cli?: boolean; version?: string;
  page: string; releases?: string; reason?: string; message?: string };
export type FilmCraftOpen = { installed: boolean; opened: boolean; how: "" | "project" | "timeline"; project?: string;
  revealed?: boolean; warnings: string[]; revision: number; folder: string; timeline: string; captions: string;
  counts: Record<string, number | boolean>; not_carried: string[]; page: string };

export const studio = {
  filmcraft: () => req<FilmCraftStatus>("GET", "/api/studio/filmcraft"),
  /** Write this version as a timeline with captions and open it in FilmCraft (`reveal`: show the folder instead). */
  openInFilmCraft: (id: string, revision: number, reveal = false) =>
    req<FilmCraftOpen>("POST", `/api/studio/videos/${id}/filmcraft`, { revision, reveal }),
  askForChange: (id: string, text: string, base_revision: number) =>
    req<ChangeRequest>("POST", `/api/studio/videos/${id}/requests`, { text, base_revision }),
  changeRequest: (rid: string) => req<ChangeRequest>("GET", `/api/studio/requests/${rid}`),
  applyChange: (rid: string) => req<ChangeRequest>("POST", `/api/studio/requests/${rid}/apply`),
  cancelChange: (rid: string) => req<ChangeRequest>("POST", `/api/studio/requests/${rid}/cancel`),
  mediaProviders: () => req<MediaProvider[]>("GET", "/api/studio/media/providers"),
  setMediaProvider: (id: string, body: { enabled?: boolean; key?: string }) => req<MediaProvider[]>("PUT", `/api/studio/media/providers/${id}`, body),
  testMediaProvider: (id: string) => req<{ ok: boolean; state: string; message: string }>("POST", `/api/studio/media/providers/${id}/test`),
  searchMedia: (body: { kind: MediaKind; query: string; filters?: Record<string, string>; page?: number; project_id?: string; providers?: string[] }) =>
    req<MediaSearchResult>("POST", "/api/studio/media/search", body),
  importMedia: (body: { result_id: string; project_id?: string; basis?: string }) => req<MediaImport>("POST", "/api/studio/media/imports", body),
  mediaImport: (id: string) => req<MediaImport>("GET", `/api/studio/media/imports/${id}`),
  cancelMediaImport: (id: string) => req<MediaImport>("POST", `/api/studio/media/imports/${id}/cancel`),
  setMediaRules: (id: string, body: Partial<MediaRules>) => req<Video>("PUT", `/api/studio/videos/${id}/media-rules`, body),
  findSupportingMedia: (id: string) => req<Suggestions>("POST", `/api/studio/videos/${id}/supporting-media`),
  supportingMedia: (id: string) => req<Suggestions>("GET", `/api/studio/videos/${id}/supporting-media`),
  editCredit: (id: string, key: string, text: string) => req<Video>("PUT", `/api/studio/videos/${id}/credits`, { key, text }),
  library: (kind = "", q = "") => req<LibraryItem[]>("GET", `/api/studio/projects?kind=${kind}&q=${encodeURIComponent(q)}`),
  // A plain read (GET): showing the preview never changes anything.
  preview: (body: { mode: string; style_id?: string; choices?: Record<string, unknown>; title?: string; reference_id?: string }) =>
    req<Snapshot>("GET", `/api/studio/guidance/preview?${new URLSearchParams({ mode: body.mode,
      style_id: body.style_id || "saved", choices: JSON.stringify(body.choices || {}), title: body.title || "",
      reference_id: body.reference_id || "" })}`),
  capabilities: () => req<{ modes: string[]; fields: Field[] }>("GET", "/api/studio/capabilities"),
  examples: (all = false) => req<ExampleVideo[]>("GET", `/api/studio/references${all ? "?all=1" : ""}`),
  example: (id: string) => req<ExampleVideo>("GET", `/api/studio/references/${id}`),
  addExample: (body: Record<string, unknown>) => req<ExampleVideo>("POST", "/api/studio/references", body),
  patchExample: (id: string, body: Record<string, unknown>) => req<ExampleVideo>("PATCH", `/api/studio/references/${id}`, body),
  analyzeExample: (id: string, ranges?: { start_ms: number; end_ms: number }[] | null) =>
    req<ExampleVideo>("POST", `/api/studio/references/${id}/analyze`, { ranges: ranges ?? null }),
  cancelExample: (id: string) => req<ExampleVideo>("POST", `/api/studio/references/${id}/cancel`),
  saveExampleStyle: (id: string, body: { values: Record<string, unknown>; analysis_revision: number; name?: string; style_revision?: number }) =>
    req<ExampleVideo>("PUT", `/api/studio/references/${id}/style`, body),
  deleteExample: (id: string, keepStyle: boolean, deleteFile: boolean) =>
    req<{ deleted: string; notes: string[] }>("DELETE", `/api/studio/references/${id}?keep_style=${keepStyle ? 1 : 0}&delete_file=${deleteFile ? 1 : 0}`),
  makeClips: (body: Record<string, unknown>) => req<{ id: string }>("POST", "/api/studio/clips", body),
  /** Is this a usable video link? Checked without fetching anything. */
  linkCheck: (url: string) => req<LinkCheck>("GET", `/api/studio/link-check?${new URLSearchParams({ url })}`),
  projectGuidance: (id: string) => req<{ snapshot: Snapshot; frozen: boolean; note: string }>("GET", `/api/projects/${id}/guidance`),
  stories: (id: string) => req<{ mode: string; stories: Story[]; summary: Record<string, unknown> }>("GET", `/api/projects/${id}/stories`),
  patchStory: (id: string, body: Record<string, unknown>) => req<Story>("PATCH", `/api/stories/${id}`, body),
  splitStory: (pid: string, story_id: string, at: number) => req("POST", `/api/projects/${pid}/stories/split`, { story_id, at }),
  mergeStories: (pid: string, ids: string[]) => req("POST", `/api/projects/${pid}/stories/merge`, { ids }),
  createStoryClips: (pid: string, ids: string[] | null) => req<{ created: string[] }>("POST", `/api/projects/${pid}/stories/create`, { ids }),
  makeVideo: (body: Record<string, unknown>) => req<Video>("POST", "/api/studio/videos", body),
  /** A draft video from your files and your idea; ClipForge AI answers with a plan (or builds it: mode "auto"). */
  startVideoSetup: (body: { asset_ids: string[]; idea: string; mode: SetupMode; name?: string; style_id?: string;
    reference_id?: string; script?: Script | null; remember?: { enabled: boolean; name?: string } }) =>
    req<VideoSetup>("POST", "/api/studio/videos/setup", body),
  videoSetup: (id: string) => req<VideoSetup>("GET", `/api/studio/videos/${id}/setup`),
  /** Whether ClipForge AI has a model to plan with (else its built-in rules read what you say). */
  setupModel: () => req<VideoSetup["model"]>("GET", "/api/studio/video-setup/model"),
  sayToSetup: (id: string, text: string, question_id = "") =>
    req<{ owner: SetupMessage; ai: SetupMessage; setup: VideoSetup }>("POST", `/api/studio/videos/${id}/setup/say`, { text, question_id }),
  changeSetup: (id: string, changes: Record<string, unknown>) => req<VideoSetup>("PATCH", `/api/studio/videos/${id}/setup`, changes),
  stopSetup: (id: string) => req<VideoSetup>("POST", `/api/studio/videos/${id}/setup/stop`),
  buildSetup: (id: string, mode: SetupMode | "" = "") =>
    req<Video & { href: string }>("POST", `/api/studio/videos/${id}/setup/build`, { mode }),
  /** After the build: change the plan and edit the video again with it (a new version Undo takes back). */
  changePlan: (id: string, base_revision: number, plan: Partial<PlanFields>) =>
    req<Video & { job: string }>("PUT", `/api/studio/videos/${id}/plan`, { base_revision, plan }),
  video: (id: string) => req<Video>("GET", `/api/studio/videos/${id}`),
  editVideo: (id: string, base_revision: number, edit: Record<string, unknown>) =>
    req<Video & { note: string }>("POST", `/api/studio/videos/${id}/edits`, { base_revision, edit }),
  renderVideo: (id: string, revision: number) => req<Video>("POST", `/api/studio/videos/${id}/render`, { revision }),
  cancelVideo: (id: string) => req<Video>("POST", `/api/studio/videos/${id}/cancel`),
  restoreVideo: (id: string, revision: number) => req<Video>("POST", `/api/studio/videos/${id}/restore`, { revision }),
  undoVideo: (id: string, base_revision: number) => req<Video & { note: string }>("POST", `/api/studio/videos/${id}/undo`, { base_revision }),
  redoVideo: (id: string, base_revision: number) => req<Video & { note: string }>("POST", `/api/studio/videos/${id}/redo`, { base_revision }),
  nameRevision: (id: string, revision: number, name: string) => req<Video>("PUT", `/api/studio/videos/${id}/revisions/${revision}/name`, { name }),
  /** Edit it for me (again): a new version made in the background with these choices. */
  smartVideo: (id: string, base_revision: number, choices: Record<string, unknown>) =>
    req<{ job: string }>("POST", `/api/studio/videos/${id}/smart`, { base_revision, choices }),
  /** Read a script file or pasted text into numbered lines (nothing is stored). */
  parseScript: async (source: File | { text: string; filename?: string }): Promise<Script> => {
    const form = new FormData();
    if (source instanceof File) form.append("file", source);
    else { form.append("text", source.text); form.append("filename", source.filename || "script.txt"); }
    const res = await fetch("/api/studio/scripts/parse", { method: "POST", body: form, headers: { "X-ClipFoundry": "1" } });
    if (!res.ok) throw await responseError(res);
    return res.json() as Promise<Script>;
  },
  /** Give the video a script (or take it away with null) and cut it again to follow it, as a new version. */
  setVideoScript: (id: string, base_revision: number, script: Script | null) =>
    req<Video & { job: string; script: boolean }>("PUT", `/api/studio/videos/${id}/script`, { base_revision, script }),
  /** This computer's folders (desktop only; the cloud answers 403). An empty path lists the top folders. */
  localBrowse: (path = "") => req<LocalListing>("GET", `/api/local/browse?${new URLSearchParams({ path })}`),
  /** Use files where they are on this computer: no copy, no upload. */
  linkLocal: (paths: string[]) => req<{ assets: Asset[]; problems: { path: string; detail: string }[] }>("POST", "/api/uploads/link", { paths }),
  /** Prepare a file in the background (its sound, transcript and preview copy), so the build starts faster. */
  prepareAsset: (id: string) => req<{ job: string; status: string }>("POST", `/api/assets/${id}/prepare`),
  addVideoMedia: (id: string, asset_ids: string[]) => req<Video & { added: string[] }>("POST", `/api/studio/videos/${id}/media`, { asset_ids }),
  styles: () => req<Style[]>("GET", "/api/studio/styles"),
  brainMap: () => req<BrainMap>("GET", "/api/studio/brain/map"),
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
  /** Every robot back to its original name; the screen confirms first. */
  resetAllRobots: () => req<Record<string, { display_name: string }>>("POST", "/api/robots/names/reset", { confirm: true }),
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
  // Small enough files are fingerprinted in the browser so the server can reject damaged transfers; for larger files
  // the server's own hash is the record (the browser has no streaming hash, and several uploads run at once).
  if (file.size > 64 * 1024 * 1024 || !crypto?.subtle) return "";
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

/** Seconds with tenths, for edit points (m:ss.t). */
export const fmtEdit = (ms: number) => {
  const m = Math.floor(ms / 60000);
  const sec = (ms % 60000) / 1000;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
};

export const fmtTime = (s: number) => {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};
export const fmtBytes = (n: number) => (n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
