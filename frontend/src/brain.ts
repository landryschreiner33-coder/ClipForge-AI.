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
};

export type ChatTool = "remember" | "forget" | "list" | "explain" | "change" | "answer" | "help";
export type UsedMemory = { id: string; kind: MemoryKind; text: string; score?: number };
export type ChatData = { tool?: ChatTool; used?: UsedMemory[]; memory?: Memory; forgotten?: Memory;
  candidates?: { id: string; kind: MemoryKind; text: string }[]; memories?: { id: string; kind: MemoryKind; text: string; source: MemorySource }[];
  request_id?: string; request?: import("./studio").ChangeRequest; provider?: string; sent?: string };
export type ChatMessage = { id: string; chat_id: string; role: "owner" | "ai"; text: string; status: "done" | "thinking" | "failed";
  data: ChatData; created_at: number; updated_at: number };
export type Chat = { id: string; workspace_id: string; project_id: string; title: string; messages: ChatMessage[] };
const chats = "/api/brain/chats";
export const chatApi = {
  open: (projectId = "") => req<Chat>("POST", chats, { project_id: projectId }),
  messages: (chatId: string, after = "") => req<ChatMessage[]>("GET", `${chats}/${chatId}/messages?after=${encodeURIComponent(after)}`),
  say: (chatId: string, text: string, baseRevision?: number) =>
    req<{ owner: ChatMessage; ai: ChatMessage }>("POST", `${chats}/${chatId}/messages`, { text, base_revision: baseRevision ?? null }),
  clear: (chatId: string) => req<{ cleared: number }>("DELETE", `${chats}/${chatId}/messages`),
  apply: (chatId: string, messageId: string) => req<ChatMessage>("POST", `${chats}/${chatId}/messages/${messageId}/apply`),
  discard: (chatId: string, messageId: string) => req<ChatMessage>("POST", `${chats}/${chatId}/messages/${messageId}/discard`),
};
