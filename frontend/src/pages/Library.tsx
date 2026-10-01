import { useEffect, useState } from "react";
import { api, errorText, Project, projectThumbUrl } from "../api";
import { ap } from "../autopilot";
import {
  addedLine, cancelProcessing, DeleteProjectDialog, isWorking, LibProject, projectMenu, ProjectStatus,
} from "../components/libParts";
import { Banner, EmptyState, Icon, MoreMenu, PageHead, Skel, Thumb, toast, usePoll } from "../components/ui";
import { useStatus } from "../status";
import "./library.css";

type Filter = "all" | "working" | "ready" | "problems";
const FILTERS: [Filter, string][] = [
  ["all", "All"], ["working", "Working"], ["ready", "Ready"], ["problems", "Problems"],
];
const MATCH: Record<Filter, (p: Project) => boolean> = {
  all: () => true,
  working: isWorking,
  ready: (p) => p.status === "ready",
  problems: (p) => p.status === "error",
};

/** Your source videos. The name filter and the chips work on the loaded list (the backend has no search). */
export default function Library() {
  // Fast while something is being worked on; slower otherwise, so videos Autopilot adds still appear.
  const [fast, setFast] = useState(true);
  const every = fast ? 2500 : 10000;
  const { data, error, refresh } = usePoll(() => api.projects() as Promise<LibProject[]>, [every], every, () => true);
  useEffect(() => {
    if (data) setFast(data.some(isWorking));
  }, [data]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [deleting, setDeleting] = useState<LibProject | null>(null);

  const head = (
    <PageHead title="Library"
      sub="Your source videos and the clips made from them. Everything is stored on this computer."
      actions={<a className="btn btn-primary" href="#/create"><Icon name="plus" />Add video</a>} />
  );

  if (!data) {
    return (
      <div className="page">
        {head}
        {error ? (
          <Banner tone="bad" title="The library didn't load"
            actions={<button type="button" className="btn btn-small" onClick={refresh}>
              <Icon name="refresh" />Try again
            </button>}>
            {error}. Check that the black ClipFoundry window is still open.
          </Banner>
        ) : (
          <div className="grid-cards" aria-busy="true">
            <span className="sr-only" role="status">Loading your library…</span>
            {[0, 1, 2].map((i) => (
              <div key={i} className="stack"><Skel className="skel-block" /><Skel className="skel-line" /></div>
            ))}
          </div>
        )}
      </div>
    );
  }

  const q = query.trim().toLowerCase();
  const list = data.filter((p) => MATCH[filter](p) && (!q || p.name.toLowerCase().includes(q)));
  return (
    <div className="page">
      {head}
      {data.length === 0 ? <EmptyLibrary /> : (
        <>
          <div className="row wrap lib-filters">
            <div className="field lib-search">
              <label htmlFor="lib-q" className="sr-only">Find a video by name</label>
              <input id="lib-q" type="search" placeholder="Find a video by name" value={query}
                onChange={(e) => setQuery(e.target.value)} />
            </div>
            <div className="chips" role="group" aria-label="Show">
              {FILTERS.map(([k, label]) => (
                <button key={k} type="button" className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {label} ({data.filter(MATCH[k]).length})
                </button>
              ))}
            </div>
          </div>
          {list.length ? (
            <div className="grid-cards">
              {list.map((p) => <LibraryCard key={p.id} p={p} onChanged={refresh} onDelete={() => setDeleting(p)} />)}
            </div>
          ) : (
            <p className="muted">
              No video matches.{" "}
              <button type="button" className="linkish" onClick={() => { setQuery(""); setFilter("all"); }}>
                Show all videos
              </button>
            </p>
          )}
        </>
      )}
      {deleting && (
        <DeleteProjectDialog p={deleting} clipCount={deleting.clip_count ?? 0} onClose={() => setDeleting(null)}
          onDeleted={refresh} />
      )}
    </div>
  );
}

function LibraryCard({ p, onChanged, onDelete }: { p: LibProject; onChanged: () => void; onDelete: () => void }) {
  const busy = isWorking(p);
  return (
    <article className="pcard" aria-labelledby={`pc-${p.id}`}>
      <Thumb src={p.has_thumbnail ? projectThumbUrl(p) : null} duration={p.duration}>
        {busy && (
          <span className="overlay">
            <Icon name={p.status === "uploading" ? "upload" : "refresh"} />
            <span>{p.status === "uploading" ? "Copying into ClipFoundry" : p.message || "Waiting to start"}</span>
          </span>
        )}
      </Thumb>
      <div className="stack">
        <a className="title-link clamp-2" id={`pc-${p.id}`} href={`#/project/${p.id}`}>{p.name}</a>
        <div className="pcard-meta"><ProjectStatus p={p} /></div>
        <div className="pcard-foot">
          <span className="tiny faint">{addedLine(p)}</span>
          <MoreMenu label={`More for ${p.name}`}
            items={projectMenu(p, { cancel: () => cancelProcessing(p, onChanged), remove: onDelete })} />
        </div>
      </div>
    </article>
  );
}

/** First use: why it is empty, and the two ways to fill it. */
function EmptyLibrary() {
  const { st } = useStatus();
  const folder = st?.home.my_videos?.path;
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      const r = await ap.openMyVideos();
      toast(r.opened ? "Your videos folder is open in File Explorer" : `Your videos folder is ${r.path}`);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  return (
    <EmptyState icon="library" title="Your library is empty" actions={<>
      <a className="btn" href="#/create"><Icon name="plus" />Add video</a>
      <button type="button" className="btn" disabled={busy} onClick={open}>
        <Icon name="folder" />Open videos folder
      </button>
    </>}>
      <p>
        Add a video to make clips yourself, or put videos you made in your videos folder
        ({folder ? <span className="mono break">{folder}</span> : <>Videos\ClipFoundry in your user folder</>}).
        While Autopilot is on, it makes clips from what you put there.
      </p>
    </EmptyState>
  );
}
