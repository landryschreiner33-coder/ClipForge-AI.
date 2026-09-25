import { api, fmtTime, Project, projectThumbUrl, timeAgo } from "../api";
import { Icon, StatusBadge, toast, usePoll } from "../components/ui";
import { navigate } from "../App";

export function ProjectCard({ p, onDelete }: { p: Project; onDelete?: (p: Project) => void }) {
  const busy = p.status === "processing" || p.status === "queued";
  return (
    <div className="proj-card" onClick={() => navigate(`/project/${p.id}`)}>
      <div className="proj-thumb" style={p.has_thumbnail ? { backgroundImage: `url(${projectThumbUrl(p)})` } : undefined}>
        <StatusBadge status={p.status} />
        {p.duration > 0 && <span className="dur">{fmtTime(p.duration)}</span>}
      </div>
      <div className="proj-body">
        <div className="name" title={p.name}>{p.name}</div>
        {busy ? (
          <>
            <div className="bar"><div style={{ width: `${Math.round(p.progress * 100)}%` }} /></div>
            <div className="small muted">{p.message || "Working..."}</div>
          </>
        ) : (
          <div className="row between small muted">
            <span>
              {p.clip_count ?? 0} clip{p.clip_count === 1 ? "" : "s"}
              {p.best_score ? ` · best ${Math.round(p.best_score)}` : ""}
            </span>
            <span>{timeAgo(p.created_at)}</span>
          </div>
        )}
        {onDelete && (
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn ghost sm danger" disabled={busy}
              onClick={(e) => { e.stopPropagation(); onDelete(p); }}>
              <Icon name="trash" size={14} /> Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Projects() {
  const { data, refresh } = usePoll(() => api.projects(), [], 2500,
    (ps) => !!ps && ps.some((p) => p.status === "processing" || p.status === "queued"));

  const remove = async (p: Project) => {
    if (!confirm(`Delete "${p.name}" and all its clips? This cannot be undone.`)) return;
    try {
      await api.deleteProject(p.id);
      toast("Project deleted");
      refresh();
    } catch (e) {
      toast((e as Error).message, true);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Projects</h1>
          <p>Every source video, transcript and clip is stored locally in your data folder.</p>
        </div>
        <button className="btn primary" onClick={() => navigate("/create")}>
          <Icon name="spark" size={16} /> Create clips
        </button>
      </div>
      {data && data.length === 0 && (
        <div className="card empty">
          <Icon name="projects" size={34} />
          <h3>Your library is empty</h3>
          <p>Projects appear here after you upload a video.</p>
        </div>
      )}
      <div className="proj-grid">
        {data?.map((p) => <ProjectCard key={p.id} p={p} onDelete={remove} />)}
      </div>
    </div>
  );
}
