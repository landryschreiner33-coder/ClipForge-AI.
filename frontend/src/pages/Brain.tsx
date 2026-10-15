import { FormEvent, useEffect, useMemo, useState } from "react";
import { errorText } from "../api";
import {
  DecisionPreview,
  Influence,
  Knowledge,
  KnowledgeInput,
  KnowledgeKind,
  knowledgeApi,
  Preferences,
  Workspace,
} from "../brain";
import { Banner, Dialog, EmptyState, Icon, LinkTabs, PageHead, toast } from "../components/ui";
import { brainApi } from "../office/api";
import BrainGraph from "./BrainGraph";
import { BrainNode, buildBrainGraph, filterBrainGraph, GraphCategory } from "./brainGraphModel";
import "./Brain.css";

const stateLabel = {
  active: "Used automatically",
  reference: "Searchable reference",
  saved_example: "Saved example",
  approved: "Approved for new clips",
  needs_approval: "Needs approval",
  disabled: "Disabled",
};
const lessonLabel = (item: Knowledge, paused = false) =>
  paused && item.state === "active" ? "Ready when Brain resumes" : stateLabel[item.state];
const pretty = (key: string) => key.replace(/_/g, " ");
const valueLabel = (value: unknown) =>
  typeof value === "boolean" ? (value ? "on" : "off") : value == null ? "default" : pretty(String(value));
const date = (at: number) => new Date(at * 1000).toLocaleDateString();
const empty = (kind: KnowledgeKind): KnowledgeInput => ({
  kind,
  title: "",
  content: "",
  tags: [],
  features: {},
  preferences: {},
  example_label: kind === "example" ? "good" : "",
  enabled: true,
});
const inputOf = (item: Knowledge): KnowledgeInput => ({
  kind: item.kind,
  title: item.title,
  content: item.content,
  tags: item.tags,
  features: item.features,
  preferences: item.preferences,
  example_label: item.example_label,
  enabled: item.enabled,
});
const parsedTags = (tags: string) => tags.split(",").map((tag) => tag.trim()).filter(Boolean);
const draftKey = (data: KnowledgeInput) => JSON.stringify({
  ...data,
  features: Object.entries(data.features).sort(),
  preferences: Object.entries(data.preferences).sort(),
});
const savedView = (tab: string) => {
  try {
    return JSON.parse(sessionStorage.getItem(`clipfoundry.brainView.${tab}`) || "null") as {
      mode: string;
      selected: string | null;
    } | null;
  } catch {
    return null;
  }
};

export default function Brain({ tab = "knowledge" }: { tab?: string }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [rows, setRows] = useState<Knowledge[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(() => savedView(tab)?.selected || null);
  const [mode, setMode] = useState(() => (savedView(tab)?.mode === "editor" ? "editor" : "graph"));
  const [nodeId, setNodeId] = useState("brain");
  const [category, setCategory] = useState<GraphCategory>(tab === "examples" ? "example" : "all");
  const [newKind, setNewKind] = useState<KnowledgeKind>("reference");
  const [detailed, setDetailed] = useState(false);
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState("");
  const [removing, setRemoving] = useState<Knowledge | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const examples = tab === "examples";
  const active = ["knowledge", "examples", "decisions", "results"].includes(tab) ? tab : "knowledge";

  const refresh = async () => {
    try {
      const [all, ws] = await Promise.all([knowledgeApi.list(), knowledgeApi.workspace()]);
      setRows(all);
      setWorkspace(ws);
      setProblem("");
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    const stored = savedView(tab);
    setAdding(false);
    setSelected(stored?.selected || null);
    setMode(stored?.mode === "editor" ? "editor" : "graph");
    setQuery("");
    setCategory(tab === "examples" ? "example" : "all");
    setNodeId("brain");
  }, [tab]);
  const filtered = rows.filter(
    (row) =>
      (examples ? row.kind === "example" : row.kind !== "example") &&
      (!query ||
        [row.title, row.content, ...row.tags, ...Object.values(row.features)]
          .join(" ")
          .toLowerCase()
          .includes(query.toLowerCase())),
  );
  const chosen = adding ? null : rows.find((row) => row.id === selected) || filtered[0] || null;
  const model = useMemo(() => buildBrainGraph(rows, workspace), [rows, workspace]);
  const graph = useMemo(
    () => filterBrainGraph(model, query, examples ? "example" : category),
    [model, query, examples, category],
  );
  const inspected = model.nodes.find((node) => node.id === nodeId) || model.nodes[0];
  const remember = (nextMode: string, id: string | null) => {
    try {
      sessionStorage.setItem(`clipfoundry.brainView.${tab}`, JSON.stringify({ mode: nextMode, selected: id }));
    } catch {
      /* A blocked browser store does not prevent editing local knowledge. */
    }
  };
  const showGraph = () => {
    setMode("graph");
    setAdding(false);
    remember("graph", selected);
  };
  const edit = (id: string | null) => {
    setSelected(id);
    setAdding(false);
    setMode("editor");
    setDetailed(true);
    remember("editor", id);
  };
  const add = (kind: KnowledgeKind, advanced = false) => {
    setNewKind(kind);
    setDetailed(advanced);
    setAdding(true);
    setSelected(null);
    setMode("editor");
    remember("editor", null);
  };
  const selectNode = (id: string) => {
    const node = model.nodes.find((item) => item.id === id);
    if (!node && id.startsWith("knowledge:")) {
      edit(id.slice("knowledge:".length));
      return;
    }
    if (!node && id.startsWith("topic:")) {
      setQuery(id.slice("topic:".length));
      setCategory("all");
      setNodeId("brain");
      return;
    }
    if (!graph.nodes.some((item) => item.id === id)) {
      setCategory("all");
      setQuery("");
    }
    setNodeId(id);
    if (node?.knowledge) setSelected(node.knowledge.id);
    else if (node?.kind === "topic") setCategory("all");
  };
  const save = async (data: KnowledgeInput, file: File | null) => {
    const saved =
      chosen && !adding
        ? await knowledgeApi.edit(chosen.id, data, chosen.revision)
        : file
          ? await knowledgeApi.upload(file, data)
          : await knowledgeApi.create(data);
    setAdding(false);
    setSelected(saved.id);
    setNodeId(`knowledge:${saved.id}`);
    remember("editor", saved.id);
    await refresh();
    toast(!saved.enabled ? "Saved. This lesson is disabled for future clips."
      : workspace?.guidance?.paused ? "Saved. Resume Brain to use this lesson on new clips."
        : saved.state === "active" ? "Saved. Recognized guidance applies to matching new clips."
          : "Saved as a reference. Choose a supported preference to change new clips.");
    return saved;
  };
  const action = async (run: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await run();
      await refresh();
      toast(message);
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page brain-page">
      <PageHead
        kind="YOUR LOCAL KNOWLEDGE"
        title="Brain"
        sub="Collect ideas. Teach your style. See how it connects."
        actions={
          <a className="btn btn-small" href={knowledgeApi.export} download>
            <Icon name="download" />
            Export knowledge
          </a>
        }
      />
      <LinkTabs
        label="Brain sections"
        current={active}
        tabs={[
          { id: "knowledge", href: "#/brain", label: "Knowledge" },
          { id: "examples", href: "#/brain/examples", label: "Examples" },
          { id: "decisions", href: "#/brain/decisions", label: "Decisions" },
          { id: "results", href: "#/brain/results", label: "Performance history" },
        ]}
      />
      {problem && (
        <Banner tone="bad" title="Could not complete this action">
          {problem}
          <button className="btn btn-small" onClick={() => void refresh()}>
            Reload memory
          </button>
        </Banner>
      )}
      {workspace && (
        <div className="brain-summary" aria-label="Brain memory overview">
          <div>
            <strong>{workspace.counts.total}</strong>
            <span>saved references & examples</span>
          </div>
          <div>
            <strong>{workspace.counts.active ?? workspace.counts.approved}</strong>
            <span>enabled lessons</span>
          </div>
          <div>
            <strong>{Object.values(workspace.brain.observations).reduce((a, b) => a + b, 0)}</strong>
            <span>separate result readings</span>
          </div>
        </div>
      )}
      {workspace?.guidance?.paused && <Banner tone="warn" title="Brain is paused" actions={
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void action(
          () => brainApi.pause(false), "Brain resumed. Saved guidance applies to matching new clips.")}
        ><Icon name="play" />Resume Brain</button>
      }>
        {workspace.guidance.note || "Saved guidance and learning from results are paused. Your Settings still apply."}
      </Banner>}
      {(active === "knowledge" || active === "examples") && (
        <>
          <div className="brain-toolbar brain-main-toolbar">
            <div className="brain-view-buttons" aria-label="Knowledge view">
              <button className={mode === "graph" ? "active" : ""} aria-pressed={mode === "graph"} onClick={showGraph}>
                <Icon name="spark" />
                Graph view
              </button>
              <button
                className={mode === "editor" ? "active" : ""}
                aria-pressed={mode === "editor"}
                onClick={() => edit(selected)}
              >
                <Icon name="edit" />
                List & editor
              </button>
            </div>
            <div className="brain-actions">
              <button className="btn btn-small btn-primary" onClick={() => add("reference")}>
                <Icon name="plus" />
                Add note
              </button>
              <button className="btn btn-small" onClick={() => add("instruction")}>
                <Icon name="sliders" />
                Teach preference
              </button>
              <button className="btn btn-small" onClick={() => add("example")}>
                <Icon name="film" />
                Add example
              </button>
            </div>
          </div>
          {mode === "graph" ? (
            <div className="brain-vault">
              <aside className="brain-vault-sidebar" aria-label="Saved knowledge">
                <div className="brain-vault-name">
                  <Icon name="folder" />
                  <span>MY KNOWLEDGE</span>
                  <span>{rows.length}</span>
                </div>
                <label className="brain-vault-search">
                  <span className="sr-only">Search knowledge graph</span>
                  <input
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Find a note or topic…"
                  />
                </label>
                <nav className="brain-collections" aria-label="Knowledge collections">
                  {(
                    [
                      ["all", "All connections", "spark"],
                      ["reference", "Notes & documents", "library"],
                      ["instruction", "Clip preferences", "sliders"],
                      ["example", "Your examples", "film"],
                      ["topic", "Topics", "link"],
                      ["evidence", "Recorded evidence", "check"],
                    ] as const
                  ).map(([id, label, icon]) => (
                    <button
                      key={id}
                      aria-pressed={category === id}
                      disabled={examples && id !== "example"}
                      onClick={() => setCategory(id)}
                    >
                      <Icon name={icon} />
                      {label}
                    </button>
                  ))}
                </nav>
                <div className="brain-vault-divider">
                  <span>SAVED ITEMS</span>
                </div>
                <div className="brain-vault-notes">
                  {rows
                    .filter(
                      (item) =>
                        (!examples || item.kind === "example") &&
                        (category === "all" ||
                          category === "topic" ||
                          category === "evidence" ||
                          item.kind === category) &&
                        (!query ||
                          [item.title, item.content, ...item.tags]
                            .join(" ")
                            .toLowerCase()
                            .includes(query.toLowerCase())),
                    )
                    .map((item) => (
                      <button
                        key={item.id}
                        aria-pressed={nodeId === `knowledge:${item.id}`}
                        onClick={() => selectNode(`knowledge:${item.id}`)}
                      >
                        <i className={`brain-note-dot dot-${item.kind}`} />
                        <span>{item.title}</span>
                        {item.state === "active" && <Icon name="check" />}
                      </button>
                    ))}
                  {!rows.length && <p>Your notes will live here.</p>}
                </div>
                <button className="brain-advanced-add" onClick={() => add(examples ? "example" : "reference", true)}>
                  <Icon name="upload" />
                  Add knowledge
                </button>
              </aside>
              <BrainGraph
                model={graph}
                selected={nodeId}
                empty={!rows.length && !workspace?.influences.length && !workspace?.observations.length}
                onSelect={selectNode}
              />
              <GraphInspector
                node={inspected}
                paused={Boolean(workspace?.guidance?.paused)}
                model={model}
                onEdit={edit}
                onSelect={selectNode}
                onTry={() => setPreviewing(true)}
                onAdd={() => add("reference")}
                onTeach={() => add("instruction")}
              />
            </div>
          ) : (
            <>
              <div className="brain-teaching-steps" aria-label="How teaching works">
                <span>
                  <b>1</b> Save a note or preference
                </span>
                <span>
                  <b>2</b> Brain combines it with Settings
                </span>
                <span>
                  <b>3</b> Use automatically on new clips
                </span>
              </div>
              <div className="brain-grid">
                <aside className="brain-list" aria-label="Saved knowledge">
                  <label className="field">
                    <span>Search {examples ? "examples" : "knowledge"}</span>
                    <input
                      type="search"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Title, topic, notes, or feature"
                    />
                  </label>
                  {filtered.map((item) => (
                    <button
                      key={item.id}
                      aria-pressed={chosen?.id === item.id && !adding}
                      onClick={() => {
                        setSelected(item.id);
                        setAdding(false);
                      }}
                    >
                      <div className="brain-tags">
                        <span className={`brain-pill ${item.state}`}>{lessonLabel(item, Boolean(workspace?.guidance?.paused))}</span>
                        <span className="brain-pill">
                          {item.kind === "example" ? `${item.example_label} example` : item.kind}
                        </span>
                      </div>
                      <strong>{item.title}</strong>
                      <small>
                        {item.filename || "Written here"} · revision {item.revision} · {date(item.updated_at)}
                      </small>
                      {item.tags.length > 0 && (
                        <div className="brain-tags">
                          {item.tags.map((tag) => (
                            <span className="brain-pill" key={tag}>
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))}
                  {!filtered.length && (
                    <p className="brain-note">
                      {query
                        ? "No saved knowledge matches this search."
                        : "Your memory starts here. Add a guide or example to teach your preferences."}
                    </p>
                  )}
                </aside>
                <KnowledgeEditor
                  key={`${chosen?.id || "new"}:${chosen?.revision || 0}:${newKind}:${detailed}`}
                  item={chosen}
                  paused={Boolean(workspace?.guidance?.paused)}
                  kind={adding ? newKind : examples ? "example" : "reference"}
                  detailed={detailed}
                  onGraph={showGraph}
                  onReload={refresh}
                  onSave={save}
                  onDelete={setRemoving}
                  onToggle={(item) =>
                    void action(
                      () => knowledgeApi.edit(item.id, { enabled: !item.enabled }, item.revision),
                      item.enabled ? "Disabled for future clips" : "Knowledge enabled",
                    )
                  }
                />
              </div>
            </>
          )}
          <div className="brain-bottom-note">
            <p>
              Relevant enabled lessons guide new clips. Settings fill unspecified choices; changes you make in
              the clip editor take priority. Existing clips keep their edits.
            </p>
            {mode === "editor" && (
              <button onClick={() => setPreviewing(true)}>
                Try a decision <Icon name="chev" />
              </button>
            )}
          </div>
          {model.omitted > 0 && mode === "graph" && (
            <p className="brain-note">
              The graph shows up to 160 saved items, 32 topics and 48 recent evidence readings. {model.omitted} more
              items, topics or readings remain in the list and history tabs.
            </p>
          )}
        </>
      )}
      {active === "decisions" && (
        <DecisionHistory rows={workspace?.influences || []} onTry={() => setPreviewing(true)} />
      )}
      {active === "results" && workspace && <PerformanceHistory workspace={workspace} />}
      {!workspace && !problem && <p className="muted">Loading local memory…</p>}
      {removing && (
        <Dialog
          title="Delete saved knowledge?"
          onClose={() => setRemoving(null)}
          actions={
            <>
              <button className="btn" disabled={busy} onClick={() => setRemoving(null)}>
                Keep it
              </button>
              <button
                className="btn btn-danger"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await knowledgeApi.delete(removing.id);
                    setRemoving(null);
                  }, "Knowledge and its uploaded file deleted")
                }
              >
                <Icon name="trash" />
                Delete knowledge
              </button>
            </>
          }
        >
          <p>
            This deletes <b>{removing.title}</b> and its uploaded file. Existing clips keep the revision snapshot
            explaining their decision.
          </p>
        </Dialog>
      )}
      {previewing && <DecisionTry onClose={() => setPreviewing(false)} />}
    </div>
  );
}

function GraphInspector({
  node,
  paused,
  model,
  onEdit,
  onSelect,
  onTry,
  onAdd,
  onTeach,
}: {
  node: BrainNode;
  paused: boolean;
  model: ReturnType<typeof buildBrainGraph>;
  onEdit: (id: string | null) => void;
  onSelect: (id: string) => void;
  onTry: () => void;
  onAdd: () => void;
  onTeach: () => void;
}) {
  const item = node.knowledge;
  const related = model.edges
    .filter((edge) => edge.from === node.id || edge.to === node.id)
    .map((edge) => ({
      edge,
      node: model.nodes.find((candidate) => candidate.id === (edge.from === node.id ? edge.to : edge.from))!,
    }));
  return (
    <aside className="brain-inspector" aria-label="Selected connection">
      <div className="brain-inspector-eyebrow">
        <span style={{ background: node.color }} />
        {node.kind === "brain" ? "YOUR KNOWLEDGE" : node.kind === "knowledge" ? node.category : node.kind}
      </div>
      <h2>{node.title}</h2>
      {item ? (
        <>
          <span className={`brain-pill ${item.state}`}>{lessonLabel(item, paused)}</span>
          <p className="brain-inspector-content">{item.content || "No written notes yet."}</p>
          <div className="brain-tags">
            {item.tags.map((tag) => (
              <button key={tag} onClick={() => onSelect(`topic:${tag}`)}>
                {tag}
              </button>
            ))}
          </div>
          {Object.keys(item.effective_preferences || item.preferences).length > 0 && (
            <div className="brain-inspector-preferences">
              <h3>Clip preferences</h3>
              {Object.entries(item.effective_preferences || item.preferences).map(([key, value]) => (
                <p key={key}>
                  <span>{pretty(key)}</span>
                  <b>{valueLabel(value)}</b>
                </p>
              ))}
            </div>
          )}
          <LessonEffect item={item} paused={paused} compact />
          <p className="brain-note">
            Revision {item.revision} · {date(item.updated_at)}
            {item.filename ? ` · ${item.filename}` : ""}
          </p>
          <button className="btn btn-small" onClick={() => onEdit(item.id)}>
            <Icon name="edit" />
            Open & edit
          </button>
        </>
      ) : node.influence ? (
        <>
          <p className="brain-note">An actual preference decision, recorded for this clip.</p>
          <a href={`#/clip/${node.influence.clip_id}`}>
            Open clip <Icon name="external" />
          </a>
          <p className="brain-note">
            {node.influence.snapshot.title} · revision {node.influence.revision}
          </p>
          {Object.entries(node.influence.decisions).map(([key, value]) => (
            <p key={key}>
              {pretty(key)}: {valueLabel(value.before)} → {valueLabel(value.after)}
            </p>
          ))}
        </>
      ) : node.observation ? (
        <>
          <p className="brain-note">
            {pretty(node.observation.provenance)} · {node.observation.platform || "direct testers"} ·{" "}
            {pretty(node.observation.cohort)}
          </p>
          <a href={`#/clip/${node.observation.clip_id}`}>
            Open clip <Icon name="external" />
          </a>
          {Object.entries(node.observation.metrics).map(([key, value]) => (
            <p key={key}>
              {pretty(key)}: {value === null ? "Not measured" : value}
            </p>
          ))}
          <p className="brain-note">
            {date(node.observation.observed_at)}
            {node.observation.note ? ` · ${node.observation.note}` : ""}
          </p>
        </>
      ) : node.kind === "brain" ? (
        <>
          <p className="brain-note">
            A map of the knowledge you saved. Each dot opens its real note, topic or recorded evidence.
          </p>
          <div className="brain-inspector-guide">
            <h3>Teach it in three steps</h3>
            <p>
              <b>01</b> Save your idea or style preference.
            </p>
            <p>
              <b>02</b> Brain combines recognized guidance with Settings.
            </p>
            <p>
              <b>03</b> New clips use saved, enabled lessons automatically.
            </p>
          </div>
          <button className="btn btn-small btn-primary" onClick={onAdd}>
            <Icon name="plus" />
            Write a note
          </button>
          <button className="btn btn-small" onClick={onTeach}>
            <Icon name="sliders" />
            Teach your clip style
          </button>
          <p className="brain-note">
            The glow is decorative. Connections show saved categories, shared tags and recorded influence, not hidden AI
            thoughts.
          </p>
        </>
      ) : (
        <p className="brain-note">
          {node.kind === "topic"
            ? "These saved items share this topic tag. A shared tag is an organizational connection."
            : "A collection of actual saved items in your local Brain."}
        </p>
      )}
      {!!related.length && (
        <div className="brain-inspector-connections">
          <h3>
            Connections <span>{related.length}</span>
          </h3>
          {related.slice(0, 12).map(({ edge, node: linked }) => (
            <button key={edge.id} onClick={() => onSelect(linked.id)}>
              <i style={{ background: linked.color }} />
              <span>
                {linked.title}
                <small>{edge.label}</small>
              </span>
              <Icon name="chev" />
            </button>
          ))}
          {related.length > 12 && <p className="brain-note">{related.length - 12} more connections in the graph.</p>}
        </div>
      )}
      <button className="brain-inspector-try" onClick={onTry}>
        <Icon name="spark" />
        Try a decision
      </button>
    </aside>
  );
}

function KnowledgeEditor({
  item,
  paused,
  kind,
  detailed,
  onGraph,
  onReload,
  onSave,
  onToggle,
  onDelete,
}: {
  item: Knowledge | null;
  paused: boolean;
  kind: KnowledgeKind;
  onSave: (data: KnowledgeInput, file: File | null) => Promise<Knowledge>;
  detailed: boolean;
  onGraph: () => void;
  onReload: () => Promise<void>;
  onToggle: (item: Knowledge) => void;
  onDelete: (item: Knowledge) => void;
}) {
  const [data, setData] = useState<KnowledgeInput>(() => item ? inputOf(item) : empty(kind));
  const [tags, setTags] = useState(data.tags.join(", "));
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [advanced, setAdvanced] = useState(detailed || Boolean(item?.filename));
  const isExample = data.kind === "example";
  const dirty = Boolean(item && draftKey({ ...data, tags: parsedTags(tags) }) !== draftKey(inputOf(item)));
  const preference = (key: keyof Preferences, value: string) => {
    const next = { ...data.preferences };
    if (!value) delete next[key];
    else if (key === "caption_emphasis") next.caption_emphasis = value === "true";
    else next[key] = value;
    setData({ ...data, preferences: next });
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem("");
    const title =
      data.title.trim() ||
      data.content.trim().split(/\n/)[0].slice(0, 160) ||
      file?.name.replace(/\.[^.]+$/, "").slice(0, 160) ||
      "";
    if (!title) {
      setProblem("Give this note a title, some text, or a document first.");
      setBusy(false);
      return;
    }
    try {
      const saved = await onSave(
        {
          ...data,
          title,
          tags: parsedTags(tags),
        },
        file,
      );
      // A no-op save can retain its revision; still adopt the server's normalized saved values explicitly.
      setData(inputOf(saved));
      setTags(saved.tags.join(", "));
      setFile(null);
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="card brain-editor" onSubmit={submit}>
      <div className="brain-toolbar">
        <h2>
          {item
            ? "Saved knowledge"
            : isExample
              ? "New example"
              : data.kind === "instruction"
                ? "Teach a clip preference"
                : "New note"}
        </h2>
        {item && (
          <span className={`brain-pill ${dirty ? "unsaved" : item.state}`}>
            {dirty ? "Unsaved changes" : lessonLabel(item, paused)}
          </span>
        )}
      </div>
      {item?.has_asset && isExample && (
        <video controls preload="metadata" src={knowledgeApi.asset(item.id)} aria-label={item.title} />
      )}
      {item?.media.duration_s != null && (
        <p className="brain-note">
          Measured locally: {item.media.duration_s.toFixed(1)} seconds · {item.media.width} × {item.media.height} ·{" "}
          {item.media.has_audio ? "audio present" : "no audio"}
        </p>
      )}
      <p className="brain-note">
        Recognized editing guidance and ranking goals apply to matching new clips. Your Settings fill in missing
        choices; your clip editor changes take priority. Other prose stays as a searchable reference.
        {isExample ? " Good video examples can guide clip length. They do not copy the example's visual style." : ""}
      </p>
      {item && <LessonEffect item={item} paused={paused} dirty={dirty} />}
      <label>
        <span>Title</span>
        <input
          maxLength={160}
          value={data.title}
          onChange={(e) => setData({ ...data, title: e.target.value })}
          placeholder={isExample ? "A hook worth repeating" : "Optional — we can use the first line of your note"}
        />
      </label>
      <label>
        <span>{item?.filename && !isExample ? "Searchable document text & notes" : "Notes / instructions"}</span>
        <textarea
          maxLength={100000}
          value={data.content}
          onChange={(e) => setData({ ...data, content: e.target.value })}
          placeholder="What should the Brain remember?"
        />
      </label>
      <details
        className="brain-editor-details"
        open={advanced}
        onToggle={(event) => setAdvanced(event.currentTarget.open)}
      >
        <summary>Document, topic tags & detailed options</summary>
        {!isExample && (
          <label>
            <span>Use as</span>
            <select
              value={data.kind}
              onChange={(e) =>
                setData({
                  ...data,
                  kind: e.target.value as KnowledgeKind,
                  preferences: data.preferences,
                })
              }
            >
              <option value="reference">Note / document</option>
              <option value="instruction">Instruction / skill guide</option>
            </select>
          </label>
        )}
        {!item && (
          <label>
            <span>{isExample ? "Example clip (optional)" : "Upload a document (optional)"}</span>
            <input
              type="file"
              accept={isExample ? ".mp4,.mov,.webm" : ".txt,.md,.csv,.json,.docx"}
              onChange={(e) => {
                const chosen = e.target.files?.[0] || null;
                if (chosen && chosen.size > (isExample ? 64 : 2) * 1024 * 1024) {
                  setProblem(`Choose a file smaller than ${isExample ? 64 : 2} MB.`);
                  e.target.value = "";
                  setFile(null);
                } else {
                  setFile(chosen);
                  setProblem("");
                }
              }}
            />
            <small className="brain-note">
              {isExample
                ? "MP4, MOV, WebM · up to 64 MB and 10 minutes. Feature labels come from you."
                : "TXT, Markdown, CSV, JSON, DOCX · up to 2 MB. Text becomes searchable; no macros or code run."}
            </small>
          </label>
        )}
        {isExample && (
          <>
            <label>
              <span>Example judgment</span>
              <select value={data.example_label} onChange={(e) => setData({ ...data, example_label: e.target.value })}>
                <option value="good">Good — useful to repeat</option>
                <option value="bad">Bad — useful to learn from</option>
              </select>
            </label>
            <fieldset>
              <legend>Useful features</legend>
              <div className="brain-field-grid">
                {["hook", "pacing", "captions", "storytelling"].map((feature) => (
                  <label key={feature}>
                    <span>{feature.charAt(0).toUpperCase() + feature.slice(1)}</span>
                    <textarea
                      maxLength={2000}
                      value={data.features[feature] || ""}
                      onChange={(e) => setData({ ...data, features: { ...data.features, [feature]: e.target.value } })}
                      placeholder={`What ${data.example_label === "bad" ? "fails" : "works"} here?`}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
          </>
        )}
        <label>
          <span>Topic tags (optional, separated by commas)</span>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            maxLength={1000}
            placeholder="science, basketball, cooking"
          />
          <small className="brain-note">
            With tags, guidance applies when the source title, spoken words, clip text or category matches a tag.
            Without tags, it can guide every new clip.
          </small>
        </label>
      </details>
      {(
        <fieldset>
          <legend>
            {data.example_label === "bad" ? "Corrective preferences for future clips" : "Preferences for future clips"}
          </legend>
          <p className="brain-note">
            These explicit choices override interpretations of your note. Save to use them automatically.
            Keep the app default to use recognized note guidance and your Settings.
          </p>
          <div className="brain-field-grid">
            <label>
              <span>Caption style</span>
              <select
                value={data.preferences.caption_style || ""}
                onChange={(e) => preference("caption_style", e.target.value)}
              >
                <option value="">Keep the app default</option>
                {["clean", "bold", "high_energy", "minimal"].map((style) => (
                  <option key={style} value={style}>
                    {pretty(style)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Caption position</span>
              <select
                value={data.preferences.caption_position || ""}
                onChange={(e) => preference("caption_position", e.target.value)}
              >
                <option value="">Keep the app default</option>
                {["bottom", "middle", "top"].map((position) => (
                  <option key={position}>{position}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Pacing</span>
              <select value={data.preferences.pacing || ""} onChange={(e) => preference("pacing", e.target.value)}>
                <option value="">Keep the app default</option>
                <option value="safe_cuts">Remove weak middle sentences when safe</option>
                <option value="continuous">Keep the story continuous</option>
              </select>
            </label>
            <label>
              <span>Caption emphasis</span>
              <select
                value={data.preferences.caption_emphasis === undefined ? "" : String(data.preferences.caption_emphasis)}
                onChange={(e) => preference("caption_emphasis", e.target.value)}
              >
                <option value="">Keep the app default</option>
                <option value="true">On</option>
                <option value="false">Off</option>
              </select>
            </label>
          </div>
        </fieldset>
      )}
      {problem && (
        <div className="error-text" role="alert">
          {problem}
          {item && (
            <button className="btn btn-small" type="button" onClick={() => void onReload()}>
              Reload saved note (discard edits)
            </button>
          )}
        </div>
      )}
      <div className="brain-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          <Icon name="check" />
          {busy ? "Saving…" : item ? "Save changes" : "Save knowledge"}
        </button>
        <button type="button" className="btn btn-quiet" onClick={onGraph}>
          Back to graph
        </button>
        {item && (
          <>
            <button type="button" className="btn btn-quiet" disabled={busy || dirty} onClick={() => onToggle(item)}>
              {item.enabled ? "Disable" : "Enable"}
            </button>
            {item.has_asset && (
              <a className="btn btn-quiet" href={knowledgeApi.asset(item.id, true)} download>
                <Icon name="download" />
                Original
              </a>
            )}
            <button
              type="button"
              className="btn btn-quiet brain-delete"
              aria-label="Delete this knowledge"
              onClick={() => onDelete(item)}
            >
              <Icon name="trash" />
            </button>
          </>
        )}
      </div>
      {dirty && (
        <p className="brain-note" role="status">
          Your edits are not saved. Save changes before new clips use them.
        </p>
      )}

    </form>
  );
}

function DecisionHistory({ rows, onTry }: { rows: Influence[]; onTry: () => void }) {
  return (
    <div className="brain-decision-list">
      <Banner title="An explanation you can inspect">
        Each entry records a saved instruction or example that changed a new clip's blueprint, including the exact
        revision and before / after choice. Disabling a lesson affects future plans.
      </Banner>
      {!rows.length ? (
        <EmptyState
          icon="spark"
          title="No saved preferences have changed a clip yet"
          actions={
            <button className="btn btn-primary" onClick={onTry}>
              Try a decision
            </button>
          }
        >
          Save an enabled lesson, then let Autopilot make a new clip. A preview can show which preferences
          would apply.
        </EmptyState>
      ) : (
        rows.map((row) => (
          <article className="card" key={row.id}>
            <div className="brain-toolbar">
              <h2>
                <a href={`#/clip/${row.clip_id}`}>{row.clip_title}</a>
              </h2>
              <span className="muted tiny">{date(row.created_at)}</span>
            </div>
            <p className="brain-note">
              {row.snapshot.title} · {row.snapshot.kind}
              {row.snapshot.example_label ? ` (${row.snapshot.example_label})` : ""} · revision {row.revision}
              {!row.knowledge_exists ? " · original knowledge deleted; snapshot retained" : ""}
            </p>
            <ul>
              {Object.entries(row.decisions).map(([key, choice]) => (
                <li key={key}>
                  <b>{pretty(key)}</b>: {valueLabel(choice.before)} → {valueLabel(choice.after)}
                </li>
              ))}
            </ul>
          </article>
        ))
      )}
    </div>
  );
}

function PerformanceHistory({ workspace }: { workspace: Workspace }) {
  const provenance: Record<string, string> = {
    platform_api: "Official platform reading",
    owner_import: "Owner import",
    tester_feedback: "Tester feedback",
  };
  return (
    <>
      <Banner title={workspace.brain.label}>
        {workspace.brain.message} Strategy changes require at least {workspace.brain.min_clips} mature clips from five
        source videos; each update is limited to {Math.round(workspace.brain.max_step * 100)}%.
      </Banner>
      <div className="brain-history">
        <section className="card brain-history-list">
          <div className="brain-toolbar">
            <h2>Real results</h2>
            <a className="btn btn-small" href="#/clips/feedback">
              Add feedback / import
            </a>
          </div>
          <p className="brain-note">
            Examples and teaching documents never count as views or posting results. Audiences and platforms stay
            separate; missing numbers stay missing.
          </p>
          {!workspace.observations.length && <p className="muted">No result readings yet.</p>}
          {workspace.observations.map((row) => (
            <article key={row.id}>
              <h3>
                <a href={`#/clip/${row.clip_id}`}>{row.clip_title}</a>
              </h3>
              <p className="brain-note">
                {provenance[row.provenance] || row.provenance} · {row.platform || "direct testers"} ·{" "}
                {pretty(row.cohort)} · {date(row.observed_at)}
              </p>
              <p>
                {Object.entries(row.metrics)
                  .filter(([, value]) => value !== null)
                  .map(([key, value]) => `${pretty(key)}: ${value}`)
                  .join(" · ")}
              </p>
              {row.note && <p className="brain-note">{row.note}</p>}
            </article>
          ))}
        </section>
        <section className="card brain-history-list">
          <h2>Strategy history</h2>
          {!workspace.history.length && (
            <p className="muted">No automatic strategy changes yet. Your own preferences remain in use.</p>
          )}
          {workspace.history.map((row) => (
            <article key={row.id}>
              <h3>
                {row.platform} · {pretty(row.cohort)} · v{row.version}
              </h3>
              <p className="brain-note">
                {pretty(row.status)} · {date(row.created_at)}
              </p>
              <p>{row.reason}</p>
            </article>
          ))}
        </section>
      </div>
    </>
  );
}

function LessonEffect({ item, paused, dirty = false, compact = false }: {
  item: Knowledge; paused: boolean; dirty?: boolean; compact?: boolean;
}) {
  const choices = Object.entries(item.effective_preferences || item.preferences);
  const measuredLength = item.example_duration;
  return <section className="brain-note brain-use-note" aria-label="How Brain uses this lesson">
    <h3 className="small strong">Effect on new clips</h3>
    {dirty ? <p>Unsaved edits have not changed this saved lesson. Save to update its recognized guidance.</p>
      : paused && item.state === "active" ? <p>Brain is paused. Resume it to apply this lesson to new clips.</p>
        : item.use_note ? <p>{item.use_note}</p>
        : !choices.length && !item.priorities?.length && measuredLength == null
          ? <p>Saved reference. Choose a supported preference to change new clips.</p> : null}
    {!!choices.length && !compact && <p>Recognized choices: {choices.map(([key, value]) =>
      `${pretty(key)}: ${valueLabel(value)}`).join(" · ")}.</p>}
    {!!item.priorities?.length && <p>Ranking priorities: {item.priorities.map(pretty).join(", ")}.</p>}
    {measuredLength != null && <p>Measured length hint: <b>{measuredLength.toFixed(1)} seconds</b>.
      {" "}Blended with your target. Your minimum and maximum clip lengths still apply, so the target may stay the same.</p>}
  </section>;
}

function DecisionTry({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<DecisionPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const run = async () => {
    setBusy(true);
    setProblem("");
    try {
      setResult(await knowledgeApi.preview(text));
    } catch (error) {
      setProblem(errorText(error));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title="Try a later clip decision"
      onClose={onClose}
      actions={
        <>
          <button className="btn" onClick={onClose}>
            Close
          </button>
          <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => void run()}>
            <Icon name="spark" />
            {busy ? "Checking…" : "Check Brain guidance"}
          </button>
        </>
      }
    >
      <div className="brain-preview">
        <p className="brain-note">
          Paste a clip topic or sample transcript. This uses the same saved-guidance lookup as a new clip plan.
        </p>
        <label className="field">
          <span>Clip context</span>
          <textarea
            value={text}
            maxLength={10000}
            onChange={(e) => {
              setText(e.target.value);
              setResult(null);
            }}
            placeholder="A clip about the science of sleep…"
          />
        </label>
        {problem && (
          <p className="error-text" role="alert">
            {problem}
          </p>
        )}
        {result && (
          <div className="brain-preview-result" aria-live="polite">
            {result.influences.length ? (
              result.influences.map((row) => (
                <div key={row.knowledge_id}>
                  <b>{row.snapshot.title}</b>
                  <p className="brain-note">Revision {row.revision}</p>
                  {Object.entries(row.decisions).map(([key, change]) => (
                    <p key={key}>
                      {pretty(key)}: {valueLabel(change.before)} → <b>{valueLabel(change.after)}</b>
                    </p>
                  ))}
                </div>
              ))
            ) : (
              <p>
                Your Settings already match, or this topic has no recognized Brain preference.
                Check the lesson, its tags and enabled state.
              </p>
            )}
            <p className="brain-note">
              {result.consulted != null && `${result.consulted} matching enabled lessons consulted. `}{result.note}
            </p>
          </div>
        )}
      </div>
    </Dialog>
  );
}
