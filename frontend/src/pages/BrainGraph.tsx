import { KeyboardEvent, PointerEvent, ReactNode, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useConnection } from "../components/ui";
import { useMotion } from "../motion";
import { BrainGraphModel, BrainNode, branchControl } from "./brainGraphModel";
import { galaxyCanvas } from "./galaxy";
import "./BrainGraph.css";

type View = { x: number; y: number; width: number; height: number };
const RECORD: Partial<Record<BrainNode["kind"], string>> = { style: "Style", skill: "Skill", video: "Example video",
  project: "Project" };
function nodeName(node: BrainNode) {
  const kind = RECORD[node.kind] ? `${RECORD[node.kind]}${node.applied ? ", just used" : ""}` :
    node.kind === "knowledge"
      ? node.category === "reference"
        ? "Note"
        : node.category === "instruction"
          ? "Preference"
          : "Example"
      : node.kind;
  return `${kind}: ${node.title}`;
}
/** The graph's real path from CORE to a node (fewest links), for the light that travels it when you select it. */
function pathTo(model: BrainGraphModel, target: string): string[] {
  if (target === "brain") return [];
  const next = new Map<string, string[]>();
  for (const edge of model.edges) {
    next.set(edge.from, [...(next.get(edge.from) || []), edge.to]);
    next.set(edge.to, [...(next.get(edge.to) || []), edge.from]);
  }
  const from = new Map<string, string>([["brain", ""]]);
  const queue = ["brain"];
  while (queue.length) {
    const at = queue.shift()!;
    if (at === target) break;
    for (const id of next.get(at) || []) if (!from.has(id)) { from.set(id, at); queue.push(id); }
  }
  if (!from.has(target)) return [];
  const path = [target];
  while (path[0] !== "brain") path.unshift(from.get(path[0])!);
  return path;
}
/** A link's drawn path: CORE's branches bend a little, like an arm of the galaxy; every other link is straight. */
function linkPath(from: BrainNode, to: BrainNode): string {
  if (from.kind !== "brain" || to.kind !== "collection") return `M${from.x} ${from.y}L${to.x} ${to.y}`;
  const bend = branchControl(to.x, to.y);  // CORE sits at (0, 0)
  return `M${from.x} ${from.y}Q${bend.x} ${bend.y} ${to.x} ${to.y}`;
}
/** A dot's name, on the side away from its collection (the way its branch points), so it never covers the
 * collection's own name. */
function LeafName({ node, parent }: { node: BrainNode; parent?: BrainNode }) {
  const dx = node.x - (parent?.x ?? 0), dy = node.y - (parent?.y ?? 0);
  const gap = node.radius + 7;
  const side = Math.abs(dx) >= Math.abs(dy) * 0.6;
  return side ? (
    <text x={dx >= 0 ? gap : -gap} y={4} textAnchor={dx >= 0 ? "start" : "end"} className="brain-node-label">{node.label}</text>
  ) : (
    <text y={dy >= 0 ? gap + 9 : -gap} textAnchor="middle" className="brain-node-label">{node.label}</text>
  );
}
/** How far the galaxy reaches from CORE, in graph units (the branches sit within about 480). */
const GALAXY_REACH = 560;
function bounds(model: BrainGraphModel): View {
  const xs = model.nodes.map((node) => node.x),
    ys = model.nodes.map((node) => node.y);
  // room round the dots for their names, and a little more at the top, under the map's own heading
  const width = Math.max(460, Math.max(...xs) - Math.min(...xs) + 190);
  const height = Math.max(400, Math.max(...ys) - Math.min(...ys) + 210);
  return {
    x: (Math.max(...xs) + Math.min(...xs) - width) / 2,
    y: (Math.max(...ys) + Math.min(...ys) - height) / 2 - 18,
    width,
    height,
  };
}

export default function BrainGraph({
  model,
  selected,
  empty,
  onSelect,
  actions,
}: {
  model: BrainGraphModel;
  selected: string;
  empty: boolean;
  onSelect: (id: string) => void;
  /** buttons for the map's lower right corner (Teach preference) */
  actions?: ReactNode;
}) {
  const { reduceMotion, pageHidden } = useMotion();
  const { lost } = useConnection();
  const gradient = useId().replace(/:/g, "");
  const home = useMemo(() => bounds(model), [model]);
  const [view, setView] = useState(home);
  const [offscreen, setOffscreen] = useState(false);
  const section = useRef<HTMLElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; view: View } | null>(null);
  const points = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model]);
  const connected = new Set(
    model.edges
      .filter((edge) => edge.from === selected || edge.to === selected)
      .flatMap((edge) => [edge.from, edge.to]),
  );
  // The map is still unless a project really applied something in the last few minutes; that pulse stops in a hidden
  // tab, off screen, with reduced motion and while ClipForge is not answering.
  const frozen = reduceMotion || pageHidden || lost || offscreen;
  const applied = model.nodes.filter((node) => node.applied).length;
  const zoomLevel = home.width / view.width;
  // dots' names show once zoomed in; until then the chosen item, its links and every collection keep theirs
  const allLabels = zoomLevel >= 1.5;
  useEffect(() => {
    setView(home);
  }, [home]);
  // the galaxy follows the map's pan and zoom and otherwise holds still (decoration: the map moves only when used)
  const galaxy = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = svg.current;
    if (!el) return;
    const measure = () => setBox({ width: el.clientWidth, height: el.clientHeight });
    measure();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(el);
    return () => observer?.disconnect();
  }, []);
  useEffect(() => {
    const host = galaxy.current?.querySelector(".brain-galaxy-art");
    if (host && !host.firstChild) {
      try {
        const art = galaxyCanvas();
        const copy = document.createElement("canvas");
        copy.width = art.width; copy.height = art.height;
        copy.getContext("2d")?.drawImage(art, 0, 0);
        host.appendChild(copy);
      } catch {
        /* no canvas: the map works on the plain sky */
      }
    }
  }, []);
  const fit = box.width ? Math.min(box.width / view.width, box.height / view.height) : 0;
  const centre = { x: box.width / 2 - (view.x + view.width / 2) * fit, y: box.height / 2 - (view.y + view.height / 2) * fit };
  const path = useMemo(() => pathTo(model, selected).map((id) => points.get(id)).filter(Boolean) as BrainNode[],
    [model, selected, points]);
  const pathIds = new Set(path.map((node) => node.id));
  // the same bends as the links it follows, joined into one line from CORE
  const tracePath = path.slice(1).map((node, i) => linkPath(path[i], node).replace(/^M[^LQ]+/, i ? "" : "$&"))
    .join("");
  const selectedNode = points.get(selected);
  useEffect(() => {
    if (typeof IntersectionObserver !== "function" || !section.current) return;
    const seen = new IntersectionObserver(([entry]) => setOffscreen(!entry.isIntersecting));
    seen.observe(section.current);
    return () => seen.disconnect();
  }, []);
  const zoom = (factor: number) =>
    setView((current) => {
      const width = Math.max(home.width * 0.28, Math.min(home.width * 2.5, current.width * factor));
      const ratio = width / current.width;
      const height = current.height * ratio;
      return {
        x: current.x + (current.width - width) / 2,
        y: current.y + (current.height - height) / 2,
        width,
        height,
      };
    });
  const start = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-brain-node]")) return;
    if (event.button !== 0) return;
    svg.current?.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, view };
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    if (!drag.current || !svg.current) return;
    const rect = svg.current.getBoundingClientRect();
    const scale = Math.max(drag.current.view.width / rect.width, drag.current.view.height / rect.height);
    setView({
      ...drag.current.view,
      x: drag.current.view.x - (event.clientX - drag.current.x) * scale,
      y: drag.current.view.y - (event.clientY - drag.current.y) * scale,
    });
  };
  const keyboard = (event: KeyboardEvent<SVGSVGElement>) => {
    if (event.target !== event.currentTarget) return;
    const directions: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    if (directions[event.key]) {
      event.preventDefault();
      const [dx, dy] = directions[event.key];
      setView((current) => ({
        ...current,
        x: current.x + dx * current.width * 0.08,
        y: current.y + dy * current.height * 0.08,
      }));
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoom(0.8);
    } else if (event.key === "-") {
      event.preventDefault();
      zoom(1.25);
    } else if (event.key === "0") {
      event.preventDefault();
      setView(home);
    }
  };

  return (
    <section
      ref={section}
      className={`brain-graph ${frozen ? "is-still" : ""}`}
      aria-label="Knowledge graph"
      data-animation={frozen || !applied ? "still" : "applied"}
      data-names={allLabels ? "all" : "chosen"}
    >
      <div className="brain-graph-heading">
        <span>
          <i />
          Local knowledge map
        </span>
        <span className="brain-graph-motion" role="status">
          {applied ? `${applied} used in the last 15 minutes` : "Still: nothing applied just now"}
        </span>
      </div>
      <div className="brain-graph-stage">
      <div ref={galaxy} className="brain-galaxy" aria-hidden="true" style={fit ? {
        left: centre.x - GALAXY_REACH * fit, top: centre.y - GALAXY_REACH * fit,
        width: GALAXY_REACH * 2 * fit, height: GALAXY_REACH * 2 * fit } : { display: "none" }}>
        <div className="brain-galaxy-tilt"><div className="brain-galaxy-art" /></div>
      </div>
      <svg
        ref={svg}
        className="brain-graph-canvas"
        viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
        role="group"
        aria-label="Interactive Brain graph"
        aria-describedby={`${gradient}-help`}
        tabIndex={0}
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
        onKeyDown={keyboard}
      >
        <defs>
          <radialGradient id={`${gradient}-core`}>
            <stop offset="0" stopColor="#140a1f" />
            <stop offset=".72" stopColor="#1d0f2c" />
            <stop offset="1" stopColor="#4a2a3a" />
          </radialGradient>
        </defs>
        <g className="brain-graph-edges" aria-hidden="true">
          {model.edges.map((edge) => {
            const from = points.get(edge.from),
              to = points.get(edge.to);
            if (!from || !to) return null;
            return (
              <path
                key={edge.id}
                d={linkPath(from, to)}
                className={`edge-${edge.kind}${from.kind === "brain" ? " edge-branch" : ""}`}
                strokeDasharray={edge.kind === "provenance" ? "4 3" : undefined}
                data-highlighted={edge.from === selected || edge.to === selected}
                style={{ stroke: from.kind === "brain" ? to.color : from.color,
                  color: from.kind === "brain" ? to.color : from.color }}
              >
                <title>{edge.label}</title>
              </path>
            );
          })}
        </g>
        {path.length > 1 && selectedNode && (
          <g className="brain-path" aria-hidden="true" style={{ color: selectedNode.color }}>
            <path className="brain-path-line" d={tracePath} />
            <path key={selected} className="brain-path-trace" pathLength={100} d={tracePath} />
          </g>
        )}
        {model.nodes.map((node) => (
          <g
            key={node.id}
            role="button"
            tabIndex={0}
            data-brain-node={node.id}
            aria-label={nodeName(node)}
            aria-pressed={selected === node.id}
            className={`brain-graph-node node-${node.kind}${node.applied ? " is-applied" : ""}`}
            data-connected={connected.has(node.id)}
            data-on-path={pathIds.has(node.id)}
            style={{ color: node.color }}
            transform={`translate(${node.x} ${node.y})`}
            onClick={() => onSelect(node.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(node.id);
              }
            }}
          >
            <title>
              {node.title}
              {node.knowledge ? ` · ${node.knowledge.state.replace(/_/g, " ")}` : ""}
            </title>
            <circle className="brain-node-hit" r={Math.max(14, node.radius + 10)} />
            {node.applied && <circle className="brain-node-applied" r={node.radius + 9} />}
            {(node.kind === "brain" || node.kind === "collection") && (
              <circle className="brain-node-aura" r={node.radius + 11} />
            )}
            <circle className="brain-node-ring" r={node.radius + 4} />
            {selected === node.id && node.kind !== "brain" && (
              <circle key={selected} className="brain-node-settle" r={node.radius + 7} />
            )}
            <circle
              className="brain-node-core"
              r={node.radius}
              fill={node.kind === "brain" ? `url(#${gradient}-core)` : node.color}
            />
            {node.knowledge?.state === "disabled" && <path d="M-6 6L6-6" className="brain-node-disabled" />}
            {node.kind === "brain" ? (
              <text y={5} textAnchor="middle" className="brain-node-label brain-core-word">{node.label}</text>
            ) : node.kind === "collection" ? (
              <text x={node.labelAt?.x ?? node.radius + 10} y={node.labelAt?.y ?? 4} className="brain-node-label">
                {node.label}
              </text>
            ) : (
              // every dot has its name; the map shows it when the dot is chosen, linked to the chosen one, pointed at,
              // just used or zoomed in on (BrainGraph.css), so a full map stays readable
              <LeafName node={node} parent={points.get(`group:${node.category}`)} />
            )}
          </g>
        ))}
      </svg>
      </div>
      {model.nodes.length === 1 && (
        <div className="brain-graph-empty">
          <strong>{empty ? "A space for your ideas" : "No connections match"}</strong>
          <span>
            {empty
              ? "Add your first note. Its real connections will appear here."
              : "Try another search or choose All connections."}
          </span>
        </div>
      )}
      <div className="brain-graph-bottom">
        <div className="brain-graph-controls">
          <button aria-label="Zoom out" onClick={() => zoom(1.25)}>
            −
          </button>
          <span aria-label="Graph zoom">{Math.round((home.width / view.width) * 100)}%</span>
          <button aria-label="Zoom in" onClick={() => zoom(0.8)}>
            +
          </button>
          <button onClick={() => setView(home)}>Fit graph</button>
        </div>
        <p id={`${gradient}-help`}>Drag to explore · Tab selects items · Arrow keys pan · + / − zoom · 0 fits
          {Object.values(model.hidden).some(Boolean) ? " · large collections are listed in full under Saved items" : ""}</p>
        {actions && <div className="brain-graph-actions">{actions}</div>}
      </div>
    </section>
  );
}
