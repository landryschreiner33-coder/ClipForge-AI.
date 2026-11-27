import { KeyboardEvent, PointerEvent, ReactNode, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useConnection } from "../components/ui";
import { useMotion } from "../motion";
import { BrainGraphModel, BrainNode, branchControl } from "./brainGraphModel";
import { BOLT_FPS, BoltScene, drawLightning } from "./brainLightning";
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
 * collection's own name. A name that would run past the map's edge there goes under the dot instead. */
function LeafName({ node, parent, home }: { node: BrainNode; parent?: BrainNode; home: View }) {
  const dx = node.x - (parent?.x ?? 0), dy = node.y - (parent?.y ?? 0);
  const gap = node.radius + 7;
  const reach = gap + node.label.length * 7.6;  // Courier at 12.5px: about 0.6 em a letter
  const fits = dx >= 0 ? node.x + reach <= home.x + home.width : node.x - reach >= home.x;
  const side = Math.abs(dx) >= Math.abs(dy) * 0.6 && fits;
  return side ? (
    <text x={dx >= 0 ? gap : -gap} y={4} textAnchor={dx >= 0 ? "start" : "end"} className="brain-node-label">{node.label}</text>
  ) : (
    <text y={dy >= 0 ? gap + 9 : -gap} textAnchor="middle" className="brain-node-label">{node.label}</text>
  );
}
/** How far the galaxy reaches from CORE, in graph units (the branches sit within about 480). */
const GALAXY_REACH = 560;
/** How long a zoom, a fit or an arrow-key pan of the map takes, ms. */
const VIEW_GLIDE_MS = 260;
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
  const { reduceMotion, pageHidden, officeActivity } = useMotion();
  const { lost } = useConnection();
  const gradient = useId().replace(/:/g, "");
  const home = useMemo(() => bounds(model), [model]);
  const [view, setView] = useState(home);
  const [offscreen, setOffscreen] = useState(false);
  const section = useRef<HTMLElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; view: View } | null>(null);
  const points = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model]);
  // one glowing ball fill per colour on the map
  const colours = useMemo(() => [...new Set(model.nodes.map((node) => node.color))]
    .filter((c) => /^#[0-9a-f]{6}$/i.test(c)), [model]);
  const connected = new Set(
    model.edges
      .filter((edge) => edge.from === selected || edge.to === selected)
      .flatMap((edge) => [edge.from, edge.to]),
  );
  // What a project really applied in the last few minutes pulses; that pulse stops in a hidden tab, off screen, with
  // reduced motion and while ClipForge is not answering. The lightning (brainLightning.ts) is decoration and also
  // holds still in Low power.
  const frozen = reduceMotion || pageHidden || lost || offscreen;
  const boltsStill = frozen || officeActivity === "low_power";
  const bolts = useRef<HTMLCanvasElement>(null);
  const [lit, setLit] = useState(false);
  const applied = model.nodes.filter((node) => node.applied).length;
  const zoomLevel = home.width / view.width;
  // dots' names show once zoomed in; until then the chosen item, its links and every collection keep theirs
  const allLabels = zoomLevel >= 1.5;
  // + and −, Fit graph, 0 and the arrow keys glide to the new view in about a quarter of a second, and a press during a
  // glide goes on from where the last one was heading; a drag follows the pointer directly. At once under Reduced
  // motion or in a hidden tab.
  const shown = useRef(view);
  shown.current = view;
  // the view as last asked for: a glide's step or a drag can be a frame ahead of what React has drawn, and a drag or a
  // new glide must go on from there (or the map would jump back a step)
  const show = (next: View) => {
    shown.current = next;
    setView(next);
  };
  const glide = useRef<{ frame: number; to: View | null }>({ frame: 0, to: null });
  const stopGlide = () => {
    cancelAnimationFrame(glide.current.frame);
    glide.current = { frame: 0, to: null };
  };
  const glideTo = (next: View) => {
    stopGlide();
    if (reduceMotion || pageHidden || typeof requestAnimationFrame !== "function") {
      show(next);
      return;
    }
    const from = shown.current, began = performance.now();
    const step = (now: number) => {
      // a frame's time can be a little before the press (it is when the frame began): never step backwards
      const u = Math.max(0, Math.min(1, (now - began) / VIEW_GLIDE_MS)), k = 1 - (1 - u) ** 3;
      show(u >= 1 ? next : { x: from.x + (next.x - from.x) * k, y: from.y + (next.y - from.y) * k,
        width: from.width + (next.width - from.width) * k, height: from.height + (next.height - from.height) * k });
      if (u < 1) glide.current.frame = requestAnimationFrame(step);
      else glide.current = { frame: 0, to: null };
    };
    glide.current = { frame: requestAnimationFrame(step), to: next };
  };
  /** Where the map is heading: the end of a glide, else where it is. */
  const aim = () => glide.current.to || shown.current;
  useEffect(() => () => cancelAnimationFrame(glide.current.frame), []);
  useEffect(() => {
    stopGlide();
    show(home);
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
        const copy = document.createElement("canvas");
        const paint = () => {
          const art = galaxyCanvas();
          copy.width = art.width; copy.height = art.height;
          copy.getContext("2d")?.drawImage(art, 0, 0);
        };
        paint();
        // a reset of the graphics chip (Windows paints canvases on it) gives the copy back empty
        copy.addEventListener("contextrestored", paint);
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
  // the lightning under the dots: one still frame, or twelve stepped frames a second while motion is allowed
  useEffect(() => {
    const cv = bolts.current, g = cv?.getContext("2d");
    if (!cv || !g || !fit) return;
    // soft light needs no more than 1.5 canvas pixels a screen pixel, which keeps each frame cheap on a laptop
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const w = Math.round(box.width * dpr), h = Math.round(box.height * dpr);
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
    }
    const near = new Set(model.edges.filter((e) => e.from === selected || e.to === selected)
      .flatMap((e) => [e.from, e.to]));
    const onPath = new Set(pathTo(model, selected));
    const scene: BoltScene = {
      nodes: model.nodes.map((n) => ({ id: n.id, x: n.x, y: n.y, r: n.radius, color: n.color, kind: n.kind,
        applied: !!n.applied, lit: n.id === selected || near.has(n.id) })),
      edges: model.edges.flatMap((e) => {
        const a = points.get(e.from), b = points.get(e.to);
        if (!a || !b) return [];
        const branch = a.kind === "brain" && b.kind === "collection";
        return [{ id: e.id, from: e.from, to: e.to, kind: e.kind, color: a.kind === "brain" ? b.color : a.color,
          bend: branch ? branchControl(b.x, b.y) : null,
          lit: e.from === selected || e.to === selected || (onPath.has(e.from) && onPath.has(e.to)) }];
      }),
      scale: fit, ox: centre.x, oy: centre.y, width: box.width, height: box.height, dpr,
    };
    setLit(true);
    if (boltsStill) {
      drawLightning(g, scene, 0);
      // a reset of the graphics chip (Windows paints canvases on it) gives the still frame back empty
      const again = () => drawLightning(g, scene, 0);
      cv.addEventListener("contextrestored", again);
      return () => cv.removeEventListener("contextrestored", again);
    }
    // twelve frames a second; a computer that needs long for a frame gets fewer, so the map never slows the app
    let raf = 0, last = -Infinity, frame = 1, cost = 0;
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick);
      if (t - last < Math.max(1000 / BOLT_FPS, cost * 8) - 4) return;
      last = t;
      const begun = performance.now();
      drawLightning(g, scene, frame++);
      cost = cost * 0.8 + (performance.now() - begun) * 0.2;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [model, points, selected, fit, centre.x, centre.y, box.width, box.height, boltsStill]);
  useEffect(() => {
    if (typeof IntersectionObserver !== "function" || !section.current) return;
    const seen = new IntersectionObserver(([entry]) => setOffscreen(!entry.isIntersecting));
    seen.observe(section.current);
    return () => seen.disconnect();
  }, []);
  const zoom = (factor: number) => {
    const current = aim();
    const width = Math.max(home.width * 0.28, Math.min(home.width * 2.5, current.width * factor));
    const ratio = width / current.width;
    const height = current.height * ratio;
    glideTo({
      x: current.x + (current.width - width) / 2,
      y: current.y + (current.height - height) / 2,
      width,
      height,
    });
  };
  const start = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-brain-node]")) return;
    if (event.button !== 0) return;
    stopGlide();
    svg.current?.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, view: shown.current };
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    if (!drag.current || !svg.current) return;
    const rect = svg.current.getBoundingClientRect();
    const scale = Math.max(drag.current.view.width / rect.width, drag.current.view.height / rect.height);
    show({
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
      const current = aim();
      glideTo({
        ...current,
        x: current.x + dx * current.width * 0.08,
        y: current.y + dy * current.height * 0.08,
      });
    } else if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoom(0.8);
    } else if (event.key === "-") {
      event.preventDefault();
      zoom(1.25);
    } else if (event.key === "0") {
      event.preventDefault();
      glideTo(home);
    }
  };

  return (
    <section
      ref={section}
      className={`brain-graph ${frozen ? "is-still" : ""}${lit ? " has-lightning" : ""}`}
      aria-label="Knowledge graph"
      data-animation={frozen || !applied ? "still" : "applied"}
      data-lightning={lit ? (boltsStill ? "still" : "moving") : "off"}
      data-names={allLabels ? "all" : "chosen"}
    >
      <div className="brain-graph-heading">
        <span>
          <i />
          Local knowledge map
        </span>
        <span className="brain-graph-motion" role="status">
          {applied ? `${applied} used in the last 15 minutes` : "Nothing used in the last 15 minutes"}
        </span>
      </div>
      <div className="brain-graph-stage">
      <div ref={galaxy} className="brain-galaxy" aria-hidden="true" style={fit ? {
        left: centre.x - GALAXY_REACH * fit, top: centre.y - GALAXY_REACH * fit,
        width: GALAXY_REACH * 2 * fit, height: GALAXY_REACH * 2 * fit } : { display: "none" }}>
        <div className="brain-galaxy-tilt"><div className="brain-galaxy-art" /></div>
      </div>
      <canvas ref={bolts} className="brain-bolts" aria-hidden="true"
        style={{ width: box.width || undefined, height: box.height || undefined }} />
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
          {/* CORE is a dark glass globe: the lightning's filaments show through its middle */}
          <radialGradient id={`${gradient}-core`}>
            <stop offset="0" stopColor="#140a1f" stopOpacity={lit ? 0.2 : 1} />
            <stop offset=".72" stopColor="#1d0f2c" stopOpacity={lit ? 0.55 : 1} />
            <stop offset="1" stopColor="#4a2a3a" stopOpacity={lit ? 0.9 : 1} />
          </radialGradient>
          {colours.map((c) => (
            <radialGradient key={c} id={`${gradient}-orb-${c.slice(1)}`} cx=".4" cy=".36" r=".7">
              <stop offset="0" stopColor="#ffffff" />
              <stop offset=".42" stopColor={c} />
              <stop offset="1" stopColor={c} stopOpacity=".8" />
            </radialGradient>
          ))}
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
              fill={node.kind === "brain" ? `url(#${gradient}-core)`
                : /^#[0-9a-f]{6}$/i.test(node.color) ? `url(#${gradient}-orb-${node.color.slice(1)})` : node.color}
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
              <LeafName node={node} parent={points.get(`group:${node.category}`)} home={home} />
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
          <button onClick={() => glideTo(home)}>Fit graph</button>
        </div>
        <p id={`${gradient}-help`}>Drag to explore · Tab selects items · Arrow keys pan · + / − zoom · 0 fits
          {Object.values(model.hidden).some(Boolean) ? " · large collections are listed in full under Saved items" : ""}</p>
        {actions && <div className="brain-graph-actions">{actions}</div>}
      </div>
    </section>
  );
}
