import { Influence, Knowledge, KnowledgeKind, Workspace } from "../brain";
import type { BrainMap, BrainMapExample, BrainMapProject, Skill, Style } from "../studio";

export type RecordKind = "style" | "skill" | "video" | "project";
export type GraphCategory = "all" | KnowledgeKind | "topic" | "evidence" | RecordKind;
export type BrainNode = {
  id: string;
  title: string;
  label: string;
  kind: "brain" | "collection" | "topic" | "knowledge" | "decision" | "result" | RecordKind;
  category: GraphCategory;
  color: string;
  x: number;
  y: number;
  radius: number;
  searchable: string;
  knowledge?: Knowledge;
  influence?: Influence;
  observation?: Workspace["observations"][number];
  style?: Style;
  skill?: Omit<Skill, "unsupported" | "blocked">;
  video?: BrainMapExample;
  project?: BrainMapProject;
  /** a project's recorded guidance applied this in the last few minutes (the only reason the map animates) */
  applied?: { at: number; project: string };
  /** a collection's name: where it starts (left end, baseline), from the node's centre */
  labelAt?: { x: number; y: number };
};
export type BrainEdge = {
  id: string;
  from: string;
  to: string;
  label: string;
  kind: "collection" | "topic" | "evidence" | "use" | "provenance";
};
export type BrainGraphModel = { nodes: BrainNode[]; edges: BrainEdge[]; omitted: number;
  /** leaves per collection that are in the list but not drawn (large collections are clustered) */
  hidden: Partial<Record<GraphCategory, number>> };

type Cluster = KnowledgeKind | "evidence" | RecordKind;
// the space studio's branches (2026-11-19): amber example videos, teal skills, ice-blue recorded evidence
const colors: Record<Cluster | "topic", string> = {
  reference: "#c9b8ff",
  instruction: "#b48cff",
  example: "#ff9fc8",
  evidence: "#9ad8ff",
  topic: "#7fc8e0",
  style: "#e09bff",
  skill: "#2ee6c5",
  video: "#ffb347",
  project: "#8fb4ff",
};
// eight places round CORE, clockwise from the upper left: skills up and to the right, recorded evidence down and to the
// right and example videos on the left, as in the space studio's picture
const ORDER: Cluster[] = ["reference", "instruction", "skill", "style", "evidence", "project", "example", "video"];
const centers = Object.fromEntries(ORDER.map((c, i) => {
  const angle = -Math.PI * 0.75 + i * (Math.PI / 4);
  return [c, [Math.round(Math.cos(angle) * 330), Math.round(Math.sin(angle) * 245)]];
})) as Record<Cluster, [number, number]>;
const labels: Record<Cluster, string> = {
  reference: "Notes & documents",
  instruction: "Clip preferences",
  example: "Example notes",
  evidence: "Recorded evidence",
  style: "Styles",
  skill: "Skills",
  video: "Example videos",
  project: "Projects that used them",
};
/** More leaves than this in one collection are listed but not drawn, so a large Brain stays readable. */
export const DRAWN_PER_COLLECTION = 36;
const shorten = (title: string) => (title.length > 24 ? `${title.slice(0, 22)}…` : title);
const searchable = (values: unknown[]) => values.join(" ").toLocaleLowerCase();


/** The bend of the branch from CORE (0, 0) to a collection at (x, y): the control point of its curve. */
export function branchControl(x: number, y: number): { x: number; y: number } {
  return { x: x / 2 - y * 0.22, y: y / 2 + x * 0.22 };
}

/** The server names a note "note:<id>" and an example video "example:<id>"; the map calls them knowledge and video. */
export function nodeFor(serverNode: string): string {
  const [kind, ...rest] = serverNode.split(":");
  const id = rest.join(":");
  return kind === "note" ? `knowledge:${id}` : kind === "example" ? `video:${id}` : `${kind}:${id}`;
}

/** Every leaf represents a saved item, an actual tag, or a recorded reading/decision. Positions are decoration. */
export function buildBrainGraph(rows: Knowledge[], workspace: Workspace | null, map: BrainMap | null = null,
  drawnPer = DRAWN_PER_COLLECTION): BrainGraphModel {
  const nodes: BrainNode[] = [
    {
      id: "brain",
      title: "Your Brain",
      label: "CORE",
      kind: "brain",
      category: "all",
      color: "#ffe2b8",
      x: 0,
      y: 0,
      radius: 24,
      searchable: "core your brain local memory",
    },
  ];
  const edges: BrainEdge[] = [];
  const included = rows.slice(0, 160);
  const influences = (workspace?.influences || []).slice(0, 24);
  const observations = (workspace?.observations || []).slice(0, 24);
  const hidden: BrainGraphModel["hidden"] = {};
  const collection = (category: Cluster, count: number) => {
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
  // a collection's dots fan out on the side away from CORE, up to 14 to a ring
  const radial = (category: Cluster, index: number, count: number) => {
    const [cx, cy] = centers[category];
    const ring = Math.floor(index / 14), inRing = Math.min(14, count - ring * 14);
    const arc = Math.min(Math.PI * 1.3, Math.max(1, inRing) * 0.36 + 0.2);
    const angle = Math.atan2(cy, cx) - arc / 2 + (arc * ((index % 14) + 0.5)) / inRing + (ring % 2) * 0.13;
    const distance = 64 + ring * 34;
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
  if (map) {
    const applied = new Map(map.applied.map((a) => [nodeFor(a.node), { at: a.at, project: a.project }]));
    const ids = new Set(nodes.map((n) => n.id));
    // a record some project used (and above all one used just now) is drawn before the rest of a large collection
    const usedIds = new Set(map.projects.flatMap((pr) => pr.links.map((l) => nodeFor(l.node))));
    const records = <T,>(category: RecordKind, all: T[], make: (item: T) => Omit<BrainNode, "x" | "y" |
      "category" | "color" | "kind">) => {
      collection(category, all.length);
      const rank = (id: string) => (applied.has(id) ? 0 : usedIds.has(id) ? 1 : 2);
      const items = all.map((item) => ({ item, id: make(item).id }))
        .map((x, i) => ({ ...x, i })).sort((a, b) => rank(a.id) - rank(b.id) || a.i - b.i).map((x) => x.item);
      const drawn = items.slice(0, drawnPer);
      if (items.length > drawn.length) hidden[category] = items.length - drawn.length;
      drawn.forEach((item, index) => {
        const base = make(item);
        nodes.push({ ...base, kind: category, category, color: colors[category],
          ...radial(category, index, drawn.length), applied: applied.get(base.id) });
        ids.add(base.id);
        edges.push({ id: `member:${base.id}`, from: `group:${category}`, to: base.id, label: "In this collection",
          kind: "collection" });
      });
    };
    records("style", map.styles, (st) => ({ id: `style:${st.id}`, title: st.name, label: shorten(st.name),
      radius: st.is_default ? 6.5 : 5.5, style: st,
      searchable: searchable([st.name, ...st.effects, st.provenance?.title || ""]) }));
    records("skill", map.skills, (sk) => ({ id: `skill:${sk.id}`, title: sk.name, label: shorten(sk.name),
      radius: sk.enabled ? 6 : 4.5, skill: sk, searchable: searchable([sk.name, sk.description, ...sk.effects]) }));
    records("video", map.examples, (ex) => ({ id: `video:${ex.id}`, title: ex.title, label: shorten(ex.title),
      radius: ex.enabled && !ex.avoid ? 6 : 4.5, video: ex, searchable: searchable([ex.title, ex.note, ...ex.likes]) }));
    records("project", map.projects, (pr) => ({ id: `project:${pr.id}`, title: pr.name, label: shorten(pr.name),
      radius: 5, project: pr, searchable: searchable([pr.name, ...pr.links.map((l) => l.name)]) }));
    for (const st of map.styles) {  // an Example style was learned from its example video
      if (st.reference_id && ids.has(`video:${st.reference_id}`) && ids.has(`style:${st.id}`))
        edges.push({ id: `learned:${st.id}`, from: `video:${st.reference_id}`, to: `style:${st.id}`,
          label: "Style learned from this example", kind: "provenance" });
    }
    for (const pr of map.projects) {  // a project's snapshot recorded applying these
      if (!ids.has(`project:${pr.id}`)) continue;
      for (const link of pr.links) {
        const target = nodeFor(link.node);
        if (!ids.has(target)) continue;
        const fields = link.fields.length ? `: ${link.fields.join(", ")}` : "";
        edges.push({ id: `use:${pr.id}:${target}`, from: target, to: `project:${pr.id}`,
          label: `Used${link.revision ? ` (revision ${link.revision})` : ""}${fields}`, kind: "use" });
      }
    }
    for (const node of nodes) if (!node.applied && applied.has(node.id)) node.applied = applied.get(node.id);
  }
  placeCollectionNames(nodes);
  return {
    hidden,
    nodes,
    edges,
    omitted:
      Math.max(0, rows.length - included.length) +
      Math.max(0, (workspace?.influences.length || 0) - influences.length) +
      Math.max(0, (workspace?.observations.length || 0) - observations.length) +
      Math.max(0, new Set(rows.flatMap((row) => row.tags)).size - tags.length) +
      (map?.omitted_projects || 0),
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

/** Puts each collection's name where it covers none of its dots and not CORE's branch: the first of eight places
 * round the node with the fewest overlaps (the name's width is measured in the map's Courier letters). */
function placeCollectionNames(nodes: BrainNode[]) {
  const CHAR = 9.1, LINE = 17;  // 15px Courier Prime: each letter is 0.6 of the size
  for (const group of nodes.filter((n) => n.kind === "collection")) {
    const dots = nodes.filter((n) => n.category === group.category && n !== group)
      .map((n) => ({ x: n.x - group.x, y: n.y - group.y, r: n.radius + 5 }));
    const bend = branchControl(group.x, group.y);
    for (let t = 0.3; t < 1; t += 0.05) {  // the curved branch, in the node's own coordinates
      const u = 1 - t;
      dots.push({ x: 2 * u * t * bend.x + t * t * group.x - group.x, y: 2 * u * t * bend.y + t * t * group.y - group.y, r: 4 });
    }
    const w = group.label.length * CHAR, gap = group.radius + 9, d = gap * 0.75;
    const places: [number, number][] = [[gap, -LINE / 2], [d, -d - LINE], [d, d], [-w / 2, -gap - LINE], [-w / 2, gap],
      [-gap - w, -LINE / 2], [-d - w, -d - LINE], [-d - w, d]];
    const hits = ([x, y]: [number, number]) => dots.filter((p) => p.x + p.r > x && p.x - p.r < x + w &&
      p.y + p.r > y && p.y - p.r < y + LINE).length;
    const [x, y] = places.reduce((best, place) => (hits(place) < hits(best) ? place : best));
    group.labelAt = { x, y: y + LINE * 0.78 };
  }
}
