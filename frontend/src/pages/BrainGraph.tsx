import { KeyboardEvent, PointerEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useConnection } from "../components/ui";
import { useMotion } from "../motion";
import { BrainGraphModel, BrainNode } from "./brainGraphModel";
import "./BrainGraph.css";

type View = { x: number; y: number; width: number; height: number };
function nodeName(node: BrainNode) {
  const kind =
    node.kind === "knowledge"
      ? node.category === "reference"
        ? "Note"
        : node.category === "instruction"
          ? "Preference"
          : "Example"
      : node.kind;
  return `${kind}: ${node.title}`;
}
function bounds(model: BrainGraphModel): View {
  const xs = model.nodes.map((node) => node.x),
    ys = model.nodes.map((node) => node.y);
  const width = Math.max(460, Math.max(...xs) - Math.min(...xs) + 120);
  const height = Math.max(400, Math.max(...ys) - Math.min(...ys) + 130);
  return {
    x: (Math.max(...xs) + Math.min(...xs) - width) / 2,
    y: (Math.max(...ys) + Math.min(...ys) - height) / 2,
    width,
    height,
  };
}

export default function BrainGraph({
  model,
  selected,
  empty,
  onSelect,
}: {
  model: BrainGraphModel;
  selected: string;
  empty: boolean;
  onSelect: (id: string) => void;
}) {
  const { reduceMotion, pageHidden } = useMotion();
  const { lost } = useConnection();
  const gradient = useId().replace(/:/g, "");
  const home = useMemo(() => bounds(model), [model]);
  const [view, setView] = useState(home);
  const [quiet, setQuiet] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; view: View } | null>(null);
  const points = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model]);
  const connected = new Set(
    model.edges
      .filter((edge) => edge.from === selected || edge.to === selected)
      .flatMap((edge) => [edge.from, edge.to]),
  );
  const frozen = reduceMotion || pageHidden || lost || quiet;
  useEffect(() => {
    setView(home);
  }, [home]);
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
      className={`brain-graph ${frozen ? "is-still" : ""}`}
      aria-label="Knowledge graph"
      data-animation={frozen ? "still" : "decorative-glow"}
    >
      <div className="brain-graph-heading">
        <span>
          <i />
          LOCAL KNOWLEDGE MAP
        </span>
        <button className="brain-graph-motion" aria-pressed={quiet} onClick={() => setQuiet(!quiet)}>
          {quiet ? "Resume glow" : "Pause glow"}
        </button>
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
            <stop offset="0" stopColor="#d9fcff" />
            <stop offset=".35" stopColor="#68eff5" />
            <stop offset="1" stopColor="#118399" />
          </radialGradient>
        </defs>
        <g className="brain-graph-edges" aria-hidden="true">
          {model.edges.map((edge) => {
            const from = points.get(edge.from),
              to = points.get(edge.to);
            if (!from || !to) return null;
            return (
              <line
                key={edge.id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className={`edge-${edge.kind}`}
                data-highlighted={edge.from === selected || edge.to === selected}
                style={{ stroke: from.color }}
              >
                <title>{edge.label}</title>
              </line>
            );
          })}
        </g>
        {model.nodes.map((node) => (
          <g
            key={node.id}
            role="button"
            tabIndex={0}
            data-brain-node={node.id}
            aria-label={nodeName(node)}
            aria-pressed={selected === node.id}
            className={`brain-graph-node node-${node.kind}`}
            data-connected={connected.has(node.id)}
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
            {(node.kind === "brain" || node.kind === "collection") && (
              <circle className="brain-node-aura" r={node.radius + 11} />
            )}
            <circle className="brain-node-ring" r={node.radius + 4} />
            <circle
              className="brain-node-core"
              r={node.radius}
              fill={node.kind === "brain" ? `url(#${gradient}-core)` : node.color}
            />
            {node.knowledge?.state === "disabled" && <path d="M-6 6L6-6" className="brain-node-disabled" />}
            <text y={node.radius + 19} textAnchor="middle" className="brain-node-label">
              {node.label}
            </text>
          </g>
        ))}
      </svg>
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
        <p id={`${gradient}-help`}>Drag to explore · Tab selects nodes · Arrow keys pan · + / − zoom</p>
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
      </div>
    </section>
  );
}
