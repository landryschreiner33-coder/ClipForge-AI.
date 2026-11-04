import { useEffect, useState } from "react";
import { errorText } from "../api";
import RobotTeam from "../components/RobotTeam";
import { Banner, EmptyState, Icon, ProgressBar } from "../components/ui";
import { LibraryItem, studio } from "../studio";

const RUNNING = new Set(["queued", "processing", "uploading", "building", "rendering"]);

/** Home: the two things ClipForge makes, then what is going on. Running work shows only measured progress. */
export default function Home() {
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () => studio.library().then((x) => alive && (setItems(x), setProblem(""))).catch((e) => alive && setProblem(errorText(e)));
    load();
    const t = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const running = (items || []).filter((i) => RUNNING.has(i.status));
  const failed = (items || []).filter((i) => i.status === "error" || i.status === "failed");
  const recent = (items || []).filter((i) => !RUNNING.has(i.status)).slice(0, 6);

  return (
    <div className="page">
      <section className="home-hero" aria-labelledby="home-title">
        <h1 id="home-title" tabIndex={-1}>What are you making today?</h1>
        <div className="make-choices">
          <a className="make-choice" href="#/create/clips">
            <div className="frame-shape vertical" aria-hidden="true"><span className="cap" /></div>
            <div>
              <h2>Make clips</h2>
              <p>Vertical clips for TikTok and YouTube, with captions, from one long video.</p>
              <div className="mode-names" aria-label="Two ways">
                <span>Highlights: the strongest short moments</span>
                <span>Full stories: one complete clip per story</span>
              </div>
              <span className="btn btn-primary go"><Icon name="film" />Make clips</span>
            </div>
          </a>
          <a className="make-choice" href="#/create/video">
            <div className="frame-shape wide" aria-hidden="true"><span className="strip"><i /><i /><i /><i /></span><span className="cap" /></div>
            <div>
              <h2>Make a YouTube video</h2>
              <p>Upload your clips, answer four short questions, and get an edited video you can still change.</p>
              <span className="btn btn-primary go"><Icon name="create" />Make a YouTube video</span>
            </div>
          </a>
        </div>
      </section>

      {problem && <Banner tone="warn" title="Could not load your projects">{problem}</Banner>}

      <RobotTeam />

      {failed.length > 0 && (
        <section className="panel" aria-labelledby="home-problems">
          <h2 id="home-problems">Needs you</h2>
          <ul className="file-list">
            {failed.slice(0, 5).map((i) => (
              <li key={i.id} className="file-row">
                <Icon name="alert" />
                <div className="break"><b>{i.name}</b><span className="block small muted">{i.error || i.message || "It stopped."}</span></div>
                <a className="btn btn-small" href={i.href}>Open</a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel" aria-labelledby="home-running">
        <h2 id="home-running">Working now</h2>
        {items === null ? <p className="muted">Loading…</p> : running.length === 0 ? (
          <p className="muted">Nothing is being made right now.</p>
        ) : (
          <ul className="file-list">
            {running.map((i) => (
              <li key={i.id} className="file-row">
                <Icon name={i.kind === "full_video" ? "create" : "film"} />
                <div className="break">
                  <b>{i.name}</b>
                  <span className="block small muted">{i.message || i.status}</span>
                  {typeof i.progress === "number" && i.progress > 0 && <ProgressBar value={i.progress} label={`${i.name} progress`} />}
                </div>
                <a className="btn btn-small" href={i.href}>Open</a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel" aria-labelledby="home-recent">
        <div className="panel-head"><h2 id="home-recent">Recent projects</h2><a className="btn btn-small" href="#/projects">All projects</a></div>
        {items !== null && recent.length === 0 ? (
          <EmptyState icon="film" title="No projects yet" level={3}>Make clips or a YouTube video to start.</EmptyState>
        ) : (
          <div className="lib-grid">{recent.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
        )}
      </section>
    </div>
  );
}

export function LibraryCard({ item }: { item: LibraryItem }) {
  const [broken, setBroken] = useState(false);
  const kind = item.kind === "full_video" ? "Full video" : item.mode === "full_stories" ? "Clips · Full stories" : "Clips · Highlights";
  return (
    <a className="lib-card" href={item.href}>
      {item.thumbnail && !broken ? <img className="thumb" src={item.thumbnail} alt="" loading="lazy" onError={() => setBroken(true)} />
        : <div className="thumb" aria-hidden="true" />}
      <div className="body">
        <b className="clamp-1">{item.name}</b>
        <span className="small muted">{kind}</span>
        <span className="small">{statusWords(item)}</span>
      </div>
    </a>
  );
}

export function statusWords(i: LibraryItem): string {
  if (i.status === "ready") return i.kind === "clips" ? `${i.clip_count || 0} clip${i.clip_count === 1 ? "" : "s"} ready` : "Ready";
  if (i.status === "error" || i.status === "failed") return "Stopped: open it to see why";
  if (RUNNING.has(i.status)) return i.message || "Working";
  return i.message || i.status;
}
