import { req } from "./api";

export type KnowledgeKind = "reference" | "instruction" | "example";
export type Preferences = Partial<{ caption_style: string; caption_position: string; pacing: string; caption_emphasis: boolean }>;
export type KnowledgeInput = { kind: KnowledgeKind; title: string; content: string; tags: string[];
  features: Record<string, string>; preferences: Preferences; example_label: string; enabled: boolean };
export type Knowledge = KnowledgeInput & { id: string; revision: number; approved: boolean; approved_at: number | null;
  effective_preferences?: Preferences; priorities?: string[]; use_note?: string; example_duration?: number | null;
  state: "active" | "disabled" | "reference" | "saved_example" | "approved" | "needs_approval";
  filename: string; has_asset: boolean;
  asset_sha256: string; media: { duration_s?: number; width?: number; height?: number; has_audio?: boolean; provenance?: string };
  created_at: number; updated_at: number };
export type Influence = { id: string; clip_id: string; clip_title: string; knowledge_id: string; revision: number;
  snapshot: { title: string; kind: KnowledgeKind; example_label: string; features: Record<string, string> };
  decisions: Record<string, { before: unknown; after: unknown }>; knowledge_exists: boolean; created_at: number };
export type Workspace = { counts: { total: number; active?: number; approved: number; examples: number };
  guidance?: { paused: boolean; enabled: number; label: string; note: string };
  brain: { label: string; message: string; min_clips: number; max_step: number; observations: Record<string, number> };
  observations: { id: string; clip_id: string; clip_title: string; platform: string; cohort: string; provenance: string;
    observed_at: number; metrics: Record<string, number | null>; note: string }[];
  history: { id: string; platform: string; cohort: string; version: number; status: string; reason: string; created_at: number }[];
  influences: Influence[] };
export type DecisionPreview = {
  before: Record<string, unknown>; after: Record<string, unknown>; consulted?: number;
  influences: Pick<Influence, "knowledge_id" | "revision" | "snapshot" | "decisions">[]; note: string;
};
const base = "/api/brain/knowledge";
export const knowledgeApi = {
  list: (q = "", kind = "") => req<Knowledge[]>("GET", `${base}?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`),
  workspace: () => req<Workspace>("GET", `${base}/workspace`),
  create: (body: KnowledgeInput) => req<Knowledge>("POST", base, body),
  edit: (id: string, body: Partial<KnowledgeInput>, expectedRevision?: number) =>
    req<Knowledge>("PATCH", `${base}/${id}`, { ...body,
      ...(expectedRevision === undefined ? {} : { expected_revision: expectedRevision }) }),
  approve: (item: Knowledge) => req<Knowledge>("POST", `${base}/${item.id}/approve`, { revision: item.revision }),
  delete: (id: string) => req<{ deleted: boolean }>("DELETE", `${base}/${id}`),
  preview: (text: string) => req<DecisionPreview>("POST", `${base}/preview`, { text }),
  upload: async (file: File, metadata: KnowledgeInput): Promise<Knowledge> => {
    const form = new FormData();
    form.append("file", file);
    form.append("metadata", JSON.stringify(metadata));
    const res = await fetch(`${base}/upload`, { method: "POST", headers: { "X-ClipFoundry": "1" }, body: form });
    if (!res.ok) {
      const result = await res.json().catch(() => ({}));
      throw new Error(typeof result.detail === "string" ? result.detail : "Could not save this upload");
    }
    return res.json();
  },
  asset: (id: string, download = false) => `${base}/${id}/asset${download ? "?download=true" : ""}`,
  export: `${base}/export`,
};

// ------------------------------------------------------------------ ClipForge AI: memories and the chat
export type MemoryKind = "rule" | "fact" | "episode" | "asset" | "answer";
export type MemorySource = "said" | "did" | "guessed" | "imported";
export type Memory = { id: string; kind: MemoryKind; text: string; source: MemorySource; confidence: number; scope: string;
  project_id: string; platform: string; tags: string[]; data: Record<string, unknown>; enabled: boolean;
  expires_at: number | null; used_count: number; last_used_at: number | null; revision: number; created_at: number;
  updated_at: number; expired: boolean; has_meaning: boolean; score?: number };
export type MemoryUse = { id: string; memory_id: string; where_used: string; ref_id: string; created_at: number };
export type MemoryCheck = { ok: boolean; total: number; enabled: number; counts: Record<string, number>;
  sources: Record<string, number>; meaning_model: string; problems: { code: string; count: number; text: string; ids: string[] }[];
  duplicates: unknown[]; duplicates_truncated: boolean; size_bytes: number; uses: number; checked_at: number };
export type Recalled = { memories: (Memory & { score: number })[]; prompt: string };
/** One playbook of ClipForge AI's built-in craft know-how (brain/knowhow.py). */
export type KnowHowTopic = { id: string; title: string; summary: string; lines: string[]; tasks: string[]; chars: number; score: number };
export type KnowHow = { topics: KnowHowTopic[]; source: string; tasks: string[] };
export type UsedKnowHow = { id: string; title: string; score?: number };
const mem = "/api/brain/memories";
export const memoryApi = {
  list: (q = "", kind = "", projectId = "") =>
    req<Memory[]>("GET", `${mem}?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}&project_id=${encodeURIComponent(projectId)}`),
  create: (body: { text: string; kind?: MemoryKind; scope?: string; project_id?: string; platform?: string; mode?: string; tags?: string[] }) =>
    req<Memory>("POST", mem, body),
  edit: (id: string, body: { text?: string; kind?: MemoryKind; scope?: string; tags?: string[]; enabled?: boolean }) =>
    req<Memory>("PATCH", `${mem}/${id}`, body),
  confirm: (id: string) => req<Memory>("POST", `${mem}/${id}/confirm`),
  forget: (id: string) => req<{ forgotten: Memory }>("DELETE", `${mem}/${id}`),
  uses: (id: string) => req<MemoryUse[]>("GET", `${mem}/${id}/uses`),
  recall: (query: string, projectId = "") => req<Recalled>("POST", `${mem}/recall`, { query, project_id: projectId }),
  check: () => req<MemoryCheck>("GET", `${mem}/check`),
  rebuild: () => req<{ rebuilt: number }>("POST", `${mem}/rebuild`),
  tidy: () => req<{ expired: number; merged: number }>("POST", `${mem}/tidy`),
  import: (data: unknown) => req<{ added: number; updated: number; skipped: number; invalid: number }>("POST", `${mem}/import`, { data }),
  exportUrl: `${mem}/export`,
  knowhow: () => req<KnowHow>("GET", `${mem}/knowhow`),
};

/** What answered a message: the rules alone (remember … explain, help), a change request ("change"), the assistant
 * ("talk") or the new-video planner ("plan"). */
export type ChatTool = "remember" | "forget" | "list" | "explain" | "change" | "answer" | "help" | "talk" | "plan";
export type UsedMemory = { id: string; kind: MemoryKind; text: string; score?: number };
/** A helper agent as a chat shows it. */
export type AgentCard = { id: string; name: string; icon: string };
/** A tool ClipForge AI used while answering ("Looked at your projects (3)"). */
export type ChatStep = { tool: string; label: string; ok: boolean; why?: string };
/** A button to a page or a project inside the app ("#/project/…"). */
export type ChatLink = { label: string; href: string };
export type ChatActionState = "waiting" | "done" | "failed" | "skipped" | "blocked";
/** A change or a delete ClipForge AI proposed: it happens only when you press OK. */
export type ChatAction = { id: string; tool: string; args: Record<string, unknown>; risk: "change" | "delete"; label: string;
  detail: string[]; blocked: string; state: ChatActionState; result: string };
/** A helper agent's work inside ClipForge AI's answer. */
export type HelperWork = { agent: AgentCard; task: string; text: string; ok: boolean; steps?: ChatStep[] };
export type ChatAsk = { question: string; choices: string[] };
export type ChatData = { tool?: ChatTool; used?: UsedMemory[]; knowhow?: UsedKnowHow[]; memory?: Memory; forgotten?: Memory;
  candidates?: { id: string; kind: MemoryKind; text: string }[]; memories?: { id: string; kind: MemoryKind; text: string; source: MemorySource }[];
  request_id?: string; request?: import("./studio").ChangeRequest; provider?: string; sent?: string; remote?: boolean;
  /** an @mention's answer: the agent that wrote it (role "agent") */
  agent?: AgentCard; steps?: ChatStep[]; pending?: ChatAction[]; links?: ChatLink[]; helpers?: HelperWork[];
  /** a helper agent's work while it is being written */
  helper_live?: { agent: AgentCard; task: string; text: string };
  /** what the assistant saved with its remember tool */
  remembered?: Memory[]; ask?: ChatAsk;
  /** answered without a model: it offers to set up the built-in model */
  setup?: boolean };
export type ChatMessage = { id: string; chat_id: string; role: "owner" | "ai" | "agent"; text: string;
  status: "done" | "thinking" | "failed"; data: ChatData; created_at: number; updated_at: number;
  /** after pressing OK: the action deleted this chat's own video (and the chat with it) */
  gone?: boolean };
/** ClipForge AI's model as the chat shows it, and the built-in model's setup when it is (or could be) the one. */
export type ChatAi = { ready: boolean; provider: string; label: string; local: boolean;
  builtin?: { supported: boolean; recommended: string; level: string; task: import("./api").BuiltinTask;
    levels: Pick<import("./api").BuiltinLevel, "id" | "name" | "model" | "installed" | "download_bytes" | "recommended" | "fits">[] };
  /** a level of the built-in model this computer runs well and that talks better than the one in use */
  better?: { level: string; name: string; model: string; installed: boolean; download_bytes: number } };
/** A switched-on helper agent you can talk to with "@Name …". */
export type ChatAgent = AgentCard & { role: string };
export type Chat = { id: string; workspace_id: string; project_id: string; title: string; messages: ChatMessage[];
  ai?: ChatAi; agents?: ChatAgent[] };
export const MAX_CHAT_TEXT = 4000;
const chats = "/api/brain/chats";
export const chatApi = {
  open: (projectId = "") => req<Chat>("POST", chats, { project_id: projectId }),
  messages: (chatId: string, after = "") => req<ChatMessage[]>("GET", `${chats}/${chatId}/messages?after=${encodeURIComponent(after)}`),
  say: (chatId: string, text: string, baseRevision?: number) =>
    req<{ owner: ChatMessage; ai: ChatMessage }>("POST", `${chats}/${chatId}/messages`, { text, base_revision: baseRevision ?? null }),
  clear: (chatId: string) => req<{ cleared: number }>("DELETE", `${chats}/${chatId}/messages`),
  apply: (chatId: string, messageId: string) => req<ChatMessage>("POST", `${chats}/${chatId}/messages/${messageId}/apply`),
  discard: (chatId: string, messageId: string) => req<ChatMessage>("POST", `${chats}/${chatId}/messages/${messageId}/discard`),
  /** Stop the answer being written; it keeps what it wrote so far. Returns the chat's messages. */
  stop: (chatId: string) => req<ChatMessage[]>("POST", `${chats}/${chatId}/stop`),
  /** Your OK (true) or no (false) for a change or delete ClipForge AI proposed. */
  decide: (chatId: string, messageId: string, actionId: string, doIt: boolean) =>
    req<ChatMessage>("POST", `${chats}/${chatId}/messages/${messageId}/actions/${actionId}`, { do: doIt }),
};

// ------------------------------------------------------------------ helper agents (Brain → Agents)
export type Agent = { id: string; template: string; name: string; icon: string; role: string; instructions: string;
  tools: string[]; helps_plans: boolean; enabled: boolean; position: number; runs: number; last_run_at: number | null;
  created_at: number; updated_at: number };
/** A ready-made helper; `added` when you already have it. */
export type AgentTemplate = { template: string; name: string; icon: string; role: string; instructions: string;
  tools: string[]; helps_plans: boolean; added: boolean };
/** A tool a helper may be given: only looking and making ones (a helper never changes or deletes anything). */
export type AgentTool = { name: string; risk: "look" | "make"; label: string; about: string; video_only: boolean };
export type AgentsView = { agents: Agent[]; templates: AgentTemplate[]; tools: AgentTool[]; icons: string[]; limit: number };
export type AgentInput = { name: string; icon: string; role: string; instructions: string; tools: string[];
  helps_plans: boolean; enabled: boolean };
const agentsBase = "/api/brain/agents";
export const agentsApi = {
  list: () => req<AgentsView>("GET", agentsBase),
  add: (body: Partial<AgentInput> & { template?: string }) => req<Agent>("POST", agentsBase, body),
  edit: (id: string, body: Partial<AgentInput> & { position?: number }) => req<Agent>("PATCH", `${agentsBase}/${id}`, body),
  remove: (id: string) => req<{ removed: Agent }>("DELETE", `${agentsBase}/${id}`),
};
