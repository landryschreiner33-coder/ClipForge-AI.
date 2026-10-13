import { Influence, Knowledge, KnowledgeKind, Workspace } from "../brain";

export type GraphCategory = "all" | KnowledgeKind | "topic" | "evidence";
export type BrainNode = {
  id: string;
  title: string;
  label: string;
  kind: "brain" | "collection" | "topic" | "knowledge" | "decision" | "result";
  category: GraphCategory;
  color: string;
  x: number;
  y: number;
  radius: number;
  searchable: string;
  knowledge?: Knowledge;
  influence?: Influence;
  observation?: Workspace["observations"][number];
};
export type BrainEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
  kind: "collection" | "topic" | "evidence";
};
export type BrainGraphModel = { nodes: BrainNode[]; edges: BrainEdge[]; omitted: number };

const colors = {
  reference: "#41d9ca",
  instruction: "#aa89ff",
  example: "#f0c16a",
  evidence: "#5daeff",
  topic: "#79c8de",
};
const centers = { reference: [-210, -125], instruction: [205, -135], example: [-190, 170], evidence: [210, 165] };
const labels = {
  reference: "Notes & documents",
  instruction: "Clip preferences",
  example: "Your examples",
  evidence: "Recorded evidence",
};
const shorten = (title: string) => (title.length > 24 ? `${title.slice(0, 22)}…` : title);
const searchable = (values: unknown[]) => values.join(" ").toLocaleLowerCase();

/** Every leaf represents a saved item, an actual tag, or a recorded reading/decision. Positions are decoration. */
export function buildBrainGraph(rows: Knowledge[], workspace: Workspace | null): BrainGraphModel {
  const nodes: BrainNode[] = [
    {
      id: "brain",
      title: "Your Brain",
      label: "YOUR BRAIN",
      kind: "brain",
      category: "all",
      color: "#65e7f4",
      x: 0,
      y: 0,
      radius: 24,
      searchable: "your brain local memory",
    },
  ];
  const edges: BrainEdge[] = [];
  const included = rows.slice(0, 160);
  const influences = (workspace?.influences || []).slice(0, 24);
  const observations = (workspace?.observations || []).slice(0, 24);
  const collection = (category: KnowledgeKind | "evidence", count: number) => {
    if (!count) return;
    const [x, y] = centers[category];
    nodes.push({
      id: `group:${category}`,
      title: labels[category],
      label: labels[category],
      kind: "collection",
      category,
      color: colors[category],
      x,
      y,
      radius: 13,
      searchable: labels[category].toLowerCase(),
    });
    edges.push({
      id: `root:${category}`,
      from: "brain",
      to: `group:${category}`,
      label: "Saved in this workspace",
      kind: "collection",
    });
  };
  const radial = (category: KnowledgeKind | "evidence", index: number, count: number) => {
    const [cx, cy] = centers[category];
    const ring = Math.floor(index / 14);
    const angle = (index % 14) * ((Math.PI * 2) / Math.min(14, count - ring * 14)) + ring * 0.43;
    const distance = 58 + ring * 32;
    return { x: cx + Math.cos(angle) * distance, y: cy + Math.sin(angle) * distance };
  };
  const knowledgeGroups: KnowledgeKind[] = ["reference", "instruction", "example"];
  for (const category of knowledgeGroups) {
    const items = included.filter((row) => row.kind === category);
    collection(category, items.length);
    items.forEach((item, index) => {
      const id = `knowledge:${item.id}`;
      nodes.push({
        id,
        title: item.title,
        label: shorten(item.title),
        kind: "knowledge",
        category,
        color: colors[category],
        ...radial(category, index, items.length),
        radius: item.state === "active" ? 6 : 4.5,
        knowledge: item,
        searchable: searchable([item.title, item.content, ...item.tags, ...Object.values(item.features)]),
      });
      edges.push({
        id: `member:${item.id}`,
        from: `group:${category}`,
        to: id,
        label: `Saved ${item.kind}`,
        kind: "collection",
      });
    });
  }
  const allTags = [...new Set(included.flatMap((row) => row.tags))].sort();
  const tags = allTags.slice(0, 32);
  tags.forEach((tag, index) => {
    const angle = (index / Math.max(tags.length, 1)) * Math.PI * 2 + 0.2;
    const id = `topic:${tag}`;
    nodes.push({
      id,
      title: tag,
      label: shorten(tag),
      kind: "topic",
      category: "topic",
      color: colors.topic,
      x: Math.cos(angle) * 112,
      y: Math.sin(angle) * 95,
      radius: 5,
      searchable: tag.toLocaleLowerCase(),
    });
    included
      .filter((item) => item.tags.includes(tag))
      .forEach((item) =>
        edges.push({
          id: `tag:${tag}:${item.id}`,
          from: id,
          to: `knowledge:${item.id}`,
          label: `Shared topic: ${tag}`,
          kind: "topic",
        }),
      );
  });
  const evidenceCount = influences.length + observations.length;
  collection("evidence", evidenceCount);
  influences.forEach((item, index) => {
    const id = `decision:${item.id}`;
    nodes.push({
      id,
      title: item.clip_title,
      label: shorten(item.clip_title),
      kind: "decision",
      category: "evidence",
      color: colors.evidence,
      ...radial("evidence", index, evidenceCount),
      radius: 4.5,
      influence: item,
      searchable: searchable([item.clip_title, item.snapshot.title, ...Object.keys(item.decisions)]),
    });
    edges.push({
      id: `decision:${item.id}`,
      from: `group:evidence`,
      to: id,
      label: "Recorded clip decision",
      kind: "evidence",
    });
    if (included.some((row) => row.id === item.knowledge_id))
      edges.push({
        id: `influence:${item.id}`,
        from: `knowledge:${item.knowledge_id}`,
        to: id,
        label: `Applied revision ${item.revision}`,
        kind: "evidence",
      });
  });
  observations.forEach((item, index) => {
    const id = `result:${item.id}`;
    nodes.push({
      id,
      title: item.clip_title,
      label: shorten(item.clip_title),
      kind: "result",
      category: "evidence",
      color: colors.evidence,
      ...radial("evidence", influences.length + index, evidenceCount),
      radius: 4.5,
      observation: item,
      searchable: searchable([item.clip_title, item.provenance, item.platform, item.cohort, item.note]),
    });
    edges.push({
      id: `reading:${item.id}`,
      from: `group:evidence`,
      to: id,
      label: "Recorded result reading",
      kind: "evidence",
    });
  });
  return {
    nodes,
    edges,
    omitted:
      Math.max(0, rows.length - included.length) +
      Math.max(0, (workspace?.influences.length || 0) - influences.length) +
      Math.max(0, (workspace?.observations.length || 0) - observations.length) +
      Math.max(0, new Set(rows.flatMap((row) => row.tags)).size - tags.length),
  };
}

/** Filtering keeps matching leaves and their direct neighbours so visible connections retain their meaning. */
export function filterBrainGraph(model: BrainGraphModel, query: string, category: GraphCategory): BrainGraphModel {
  const term = query.trim().toLocaleLowerCase();
  if (!term && category === "all") return model;
  const matches = new Set(
    model.nodes
      .filter(
        (node) =>
          node.kind !== "brain" &&
          node.kind !== "collection" &&
          (!term || node.searchable.includes(term)) &&
          (category === "all" || node.category === category),
      )
      .map((node) => node.id),
  );
  const visible = new Set(["brain", ...matches]);
  for (const edge of model.edges) {
    if (matches.has(edge.from) || matches.has(edge.to)) {
      visible.add(edge.from);
      visible.add(edge.to);
    }
  }
  return {
    ...model,
    nodes: model.nodes.filter((node) => visible.has(node.id)),
    edges: model.edges.filter((edge) => visible.has(edge.from) && visible.has(edge.to)),
  };
}
