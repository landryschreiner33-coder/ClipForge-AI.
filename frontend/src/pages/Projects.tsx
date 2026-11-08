import { useEffect, useState } from "react";
import { errorText } from "../api";
import { Banner, EmptyState, PageHead, Segmented } from "../components/ui";
import { LibraryItem, studio } from "../studio";
import { LibraryCard } from "./Studio";

/** One library: clips projects (Highlights and Full stories), full videos and animated shorts, with filters and search. */
export default function Projects() {
  const [kind, setKind] = useState<"" | "clips" | "full_video" | "short">("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => studio.library(kind, q).then((x) => alive && setItems(x))
      .catch((e) => alive && setProblem(errorText(e))), 150);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [kind, q]);
  return (
    <div className="page">
      <PageHead kind="Library" title="Projects" sub="Everything you made, newest first."
        actions={<><a className="btn" href="#/create/clips">Make clips</a><a className="btn btn-primary" href="#/create/video">Make a YouTube video</a></>} />
      <div className="lib-filters">
        <Segmented label="Show" value={kind} onChange={(v) => setKind(v as typeof kind)}
          options={[{ value: "", label: "All" }, { value: "clips", label: "Clips" }, { value: "full_video", label: "Full videos" },
            { value: "short", label: "Animated shorts" }]} />
        <label className="field grow"><span className="sr-only">Search projects</span>
          <input type="search" placeholder="Search by name" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <a className="small" href="#/projects/feedback">Test feedback</a>
      </div>
      {problem && <Banner tone="warn" title="Could not load projects">{problem}</Banner>}
      {items && items.length === 0 ? (
        <EmptyState icon="film" title={q ? "Nothing matches that search" : kind === "short" ? "No animated shorts yet" : "No projects yet"}
          actions={!q && kind === "short" ? <a className="btn btn-primary" href="#/create/short">Make an animated short</a> : undefined}>
          {q ? "Try another word." : kind === "short" ? "Paste a script, or let ClipForge AI write one from a topic."
            : "Make clips, a YouTube video or an animated short to start."}
        </EmptyState>
      ) : <div className="lib-grid">{(items || []).map((i) => <LibraryCard key={i.id} item={i} />)}</div>}
    </div>
  );
}
