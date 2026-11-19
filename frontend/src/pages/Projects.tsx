import { useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { DeleteProjectConfirm } from "../components/DeleteProject";
import { Banner, EmptyState, Icon, PageHead, Segmented } from "../components/ui";
import { LibraryItem, studio } from "../studio";
import { LiveStream } from "../submissions";
import { LibraryCard, useLiveRecordings } from "./Studio";

type Order = "new" | "old" | "name";

/** One library: clips projects (Highlights, Full stories and Story parts), full videos and animated shorts, with filters,
 * search and order, beside the live streams being recorded right now. Each card can be deleted after a confirmation that
 * says what goes and what stays. */
export default function Projects() {
  const [kind, setKind] = useState<"" | "clips" | "full_video" | "short">("");
  const [q, setQ] = useState("");
  const [order, setOrder] = useState<Order>("new");
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState("");
  const [deleting, setDeleting] = useState<LibraryItem | null>(null);
  const live = useLiveRecordings();
  const grid = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const focusAt = useRef<number | null>(null);  // where the deleted card was, so focus lands on its neighbour
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => studio.library(kind, q).then((x) => alive && setItems(x))
      .catch((e) => alive && setProblem(errorText(e))), 150);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [kind, q]);
  useEffect(() => {
    // after the window closes: the card it was opened from is gone, so focus moves to the next card (or the search)
    if (focusAt.current === null || deleting) return;
    const cards = grid.current?.querySelectorAll<HTMLElement>(".lib-card");
    (cards?.length ? cards[Math.min(focusAt.current, cards.length - 1)] : search.current)?.focus();
    focusAt.current = null;
  }, [items, deleting]);
  const shown = useMemo(() => {
    const list = [...(items || [])];  // the server sends newest first
    if (order === "old") list.reverse();
    if (order === "name") list.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    return list;
  }, [items, order]);
  return (
    <div className="page projects-space">
      <PageHead title="Projects" />
      <div className="lib-filters projects-toolbar">
        <Segmented label="Show" value={kind} onChange={(v) => setKind(v as typeof kind)}
          options={[{ value: "", label: "All" }, { value: "clips", label: "Clips" }, { value: "full_video", label: "Full videos" },
            { value: "short", label: "Animated shorts" }]} />
        <label className="projects-search"><Icon name="search" /><span className="sr-only">Search projects</span>
          <input ref={search} type="search" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <label className="projects-order"><span className="sr-only">Order</span>
          <select value={order} onChange={(e) => setOrder(e.target.value as Order)}>
            <option value="new">Newest first</option>
            <option value="old">Oldest first</option>
            <option value="name">Name, A to Z</option>
          </select></label>
      </div>
      {problem && <Banner tone="warn" title="Could not load projects">{problem}</Banner>}
      <div className="projects-layout">
        <section className="projects-recent" aria-labelledby="projects-recent">
          <h2 id="projects-recent">{order === "name" ? "Your projects" : order === "old" ? "Oldest projects" : "Recent projects"}</h2>
          {items && items.length === 0 ? (
            <EmptyState icon="film" title={q ? "Nothing matches that search" : kind === "short" ? "No animated shorts yet" : "No projects yet"}
              actions={!q && kind === "short" ? <a className="btn btn-primary" href="#/create/short">Make an animated short</a>
                : !q ? <a className="btn btn-primary" href="#/create/clips">Make clips</a> : undefined}>
              {q ? "Try another word." : kind === "short" ? "Paste a script, or let ClipForge AI write one from a topic."
                : "Make clips, a YouTube video or an animated short to start. + Make at the top has every choice."}
            </EmptyState>
          ) : <div className="lib-grid" ref={grid}>{shown.map((i) => <LibraryCard key={i.id} item={i} onDelete={() => setDeleting(i)} />)}</div>}
          <p className="projects-foot small"><a href="#/projects/feedback">Test feedback</a> holds what testers said about
            your clips.</p>
        </section>
        <LiveTable rows={live} />
      </div>
      {deleting && (
        <DeleteProjectConfirm kind={deleting.kind} id={deleting.id} name={deleting.name} onClose={() => setDeleting(null)}
          onDeleted={(id) => {
            focusAt.current = Math.max(0, (items || []).findIndex((x) => x.id === id));
            setItems((list) => list && list.filter((x) => x.id !== id));
          }} />
      )}
    </div>
  );
}

/** The live streams being recorded right now, with the minutes recorded and the clips found so far. */
function LiveTable({ rows }: { rows: LiveStream[] }) {
  return (
    <aside className="projects-live" aria-labelledby="projects-live">
      <h2 id="projects-live">Live recordings</h2>
      {rows.length ? (
        <table className="live-table">
          <thead><tr><th scope="col">Channel</th><th scope="col">Recorded</th><th scope="col">Clips</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <th scope="row"><a href="#/missions/live"><span className="live-pill"><i aria-hidden="true" />LIVE</span>
                  <span className="live-name">{r.channel || r.title || r.url}
                    {r.channel && r.title && <small className="clamp-1">{r.title}</small>}</span></a></th>
                <td>{Math.round(r.live.minutes)} min</td>
                <td>{r.live.live_clips}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="live-empty">
          <p className="muted">No live stream is being recorded right now.</p>
          <a className="btn" href="#/missions/live"><Icon name="live" />Clip a live stream</a>
        </div>
      )}
    </aside>
  );
}
