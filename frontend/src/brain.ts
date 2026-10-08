import { req } from "./api";

export type KnowledgeKind = "reference" | "instruction" | "example";
export type Preferences = Partial<{ caption_style: string; caption_position: string; pacing: string; caption_emphasis: boolean }>;
export type KnowledgeInput = { kind: KnowledgeKind; title: string; content: string; tags: string[];
  features: Record<string, string>; preferences: Preferences; example_label: string; enabled: boolean };
export type Knowledge = KnowledgeInput & { id: string; revision: number; approved: boolean; approved_at: number | null;
  state: "disabled" | "reference" | "approved" | "needs_approval"; filename: string; has_asset: boolean;
  asset_sha256: string; media: { duration_s?: number; width?: number; height?: number; has_audio?: boolean; provenance?: string };
  created_at: number; updated_at: number };
export type Influence = { id: string; clip_id: string; clip_title: string; knowledge_id: string; revision: number;
  snapshot: { title: string; kind: KnowledgeKind; example_label: string; features: Record<string, string> };
  decisions: Record<string, { before: unknown; after: unknown }>; knowledge_exists: boolean; created_at: number };
export type Workspace = { counts: { total: number; approved: number; examples: number };
  brain: { label: string; message: string; min_clips: number; max_step: number; observations: Record<string, number> };
  observations: { id: string; clip_id: string; clip_title: string; platform: string; cohort: string; provenance: string;
    observed_at: number; metrics: Record<string, number | null>; note: string }[];
  history: { id: string; platform: string; cohort: string; version: number; status: string; reason: string; created_at: number }[];
  influences: Influence[] };
export type DecisionPreview = { before: Preferences; after: Preferences; influences: Pick<Influence, "knowledge_id" | "revision" | "snapshot" | "decisions">[]; note: string };
const base = "/api/brain/knowledge";
export const knowledgeApi = {
  list: (q = "", kind = "") => req<Knowledge[]>("GET", `${base}?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`),
  workspace: () => req<Workspace>("GET", `${base}/workspace`),
  create: (body: KnowledgeInput) => req<Knowledge>("POST", base, body),
  edit: (id: string, body: Partial<KnowledgeInput>) => req<Knowledge>("PATCH", `${base}/${id}`, body),
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
