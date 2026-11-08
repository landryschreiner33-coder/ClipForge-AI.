import { ReactNode, useEffect, useMemo, useState } from "react";
import { errorText } from "../api";
import { Banner, EmptyState, Icon, ProgressBar, toast } from "../components/ui";
import { useAppearance } from "../prefs";
import { timeLabel } from "../components/postShared";
import { useStatus } from "../status";
import { LibraryItem, studio } from "../studio";
import { BY_ID, DEPARTMENTS } from "../office/cast";
import { OwnerWork, RoleRow } from "../office/api";
import { useOffice } from "../office/useOffice";
import { POSE_OF } from "../office/panels";
import Portrait from "../office/Portrait";
import { OfficeView, useOfficeSelection } from "./Office";
import "../office/studio.css";
import "./shorts.css";

const RUNNING = new Set(["queued", "processing", "importing", "uploading", "building", "rendering"]);
const STOPPED = new Set(["error", "failed", "needs_input"]);
// what a full video's status means while no step has said more
const VIDEO_WORDS: Record<string, string> = { building: "Building the rough cut", rendering: "Rendering",
  queued: "Waiting to start", importing: "Getting the video from your link" };
const KIND_WORD = (i: LibraryItem) => i.kind === "full_video" ? (i.mode === "animated_short" ? "Animated short" : "YouTube video")
  : i.mode === "full_stories" ? "Clips · Full stories" : "Clips · Highlights";

/**
 * Studio: Home and the Office in one place (studio upgrade handoff, section 4). The three things ClipForge makes, what
 * needs you (only when there is something to do), the current project with its real stage, measured progress and
 * the team on it, the office itself, then recent projects and publishing. Nothing here estimates or invents work.
 */
export default function Studio() {
  const feed = useOffice();
  const { st } = useStatus();
  const { appearance, layout, setCustomizing } = useAppearance();
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState("");
  const [sel, setSel] = useOfficeSelection("studio");

  useEffect(() => {
    let alive = true;
    const load = () => studio.library().then((x) => alive && (setItems(x), setProblem("")))
      .catch((e) => alive && setProblem(errorText(e)));
    load();
    const t = window.setInterval(load, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const work = feed.snap?.work || [];
  const jobsFor = (i: LibraryItem) => work.filter((w) => w.project_id === i.id || w.video_id === i.id);
  // the project something is really running for comes first, then the newest
  const running = (items || []).filter((i) => RUNNING.has(i.status))
    .map((i, n) => ({ i, n, live: jobsFor(i).some((w) => w.status === "running") }))
    .sort((a, b) => Number(b.live) - Number(a.live) || a.n - b.n).map((x) => x.i);
  const stopped = (items || []).filter((i) => STOPPED.has(i.status)).slice(0, 5);
  const recent = (items || []).filter((i) => !RUNNING.has(i.status)).slice(0, 6);
  // Autopilot's own list, kept to items that say what to do, and your own work that waits for an answer from you
  const actions = (st?.home.needs_you || []).filter((n) => n.fix || n.link).slice(0, 5);
  const yourTurn = work.filter((w) => w.waiting_on === "you" && w.video_id).slice(0, 5);
  const current = running[0];
  const pinned = appearance.pinned.map((id) => (items || []).find((i) => i.id === id)).filter(Boolean) as LibraryItem[];

  return (
    <div className="page studio-page">
      <section className="home-hero" aria-labelledby="studio-title">
        <h1 id="studio-title" tabIndex={-1}>What are you making today?</h1>
        <div className="make-choices three">
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
          <a className="make-choice" href="#/create/short">
            <div className="frame-shape vertical" aria-hidden="true"><span className="pic" /><span className="cap" /></div>
            <div>
              <h2>Make an animated short</h2>
              <p>A voice-over short of moving pictures from your script, or one ClipForge AI writes.</p>
              <span className="btn btn-primary go"><Icon name="spark" />Make an animated short</span>
            </div>
          </a>
        </div>
        <p className="studio-link-action"><a className="btn" href="#/create/link"><Icon name="external" />Make clips from a video link</a>
          <span className="small muted">YouTube watch, Shorts and live links work the same way as a file.</span></p>
      </section>

      {problem && <Banner tone="warn" title="Could not load your projects">{problem}</Banner>}

      <StudioPanels order={layout.screens.studio} panels={{
        needs_you: (stopped.length > 0 || actions.length > 0 || yourTurn.length > 0) && (
          <section className="panel needs-you" aria-labelledby="studio-needs">
            <h2 id="studio-needs">Needs you</h2>
            <ul className="file-list">
              {stopped.map((i) => (
                <li key={i.id} className="file-row">
                  <Icon name="alert" />
                  <div className="break"><b>{i.name}</b>
                    <span className="block small muted">{i.error || i.message || "It stopped before it finished."}</span></div>
                  <a className="btn btn-small" href={i.href}>{i.status === "needs_input" ? "Answer" : "Open and retry"}</a>
                </li>
              ))}
              {yourTurn.map((w) => (
                <li key={w.id} className="file-row">
                  <Icon name="question" />
                  <div className="break"><b>{w.title || "Your video"}</b><span className="block small muted">{w.message}</span></div>
                  <a className="btn btn-small" href={`#/video/${w.video_id}`}>Open the editor</a>
                </li>
              ))}
              {actions.map((n) => (
                <li key={n.key} className="file-row">
                  <Icon name="alert" />
                  <div className="break"><b>{n.title}</b><span className="block small muted">{n.detail}</span></div>
                  {n.link ? <a className="btn btn-small" href={n.link}>{n.fix || "Fix it"}</a>
                    : <span className="small">{n.fix}</span>}
                </li>
              ))}
            </ul>
          </section>
        ),
        pinned: pinned.length > 0 && (
          <section className="panel" aria-labelledby="studio-pinned">
            <h2 id="studio-pinned">Pinned</h2>
            <div className="lib-grid">{pinned.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
          </section>
        ),
        current: (
          <section className="panel" aria-labelledby="studio-current">
            <h2 id="studio-current">Current project</h2>
            {items === null ? <p className="muted">Loading…</p> : current ? (
              <>
                <CurrentProject item={current} jobs={jobsFor(current)} roles={feed.snap?.roles || []}
                  onRobot={(id) => setSel({ type: "robot", id, card: null })} />
                {running.length > 1 && (
                  <ul className="file-list studio-more">
                    {running.slice(1, 5).map((i) => (
                      <li key={i.id} className="file-row">
                        <Icon name={i.kind === "full_video" ? "create" : "film"} />
                        <div className="break"><b>{i.name}</b><span className="block small muted">{stageWords(i)}</span></div>
                        <a className="btn btn-small" href={i.href}>Open</a>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <EmptyState icon="film" title="Ready for your next video" level={3}>
                <span className="row wrap studio-empty-actions">
                  <a className="btn btn-primary btn-small" href="#/create/clips"><Icon name="film" />Make clips</a>
                  <a className="btn btn-small" href="#/create/link"><Icon name="external" />Paste a video link</a>
                  <a className="btn btn-small" href="#/create/video"><Icon name="create" />Make a YouTube video</a>
                </span>
              </EmptyState>
            )}
          </section>
        ),
        office: (
          <section className={`office-page office-studio office-embedded office-size-${appearance.office_size}`}
            aria-labelledby="studio-office">
            <h2 id="studio-office" className="studio-title">Your robot office</h2>
            <OfficeView feed={feed} sel={sel} setSel={setSel} embedded compact={appearance.office_size === "compact"} />
          </section>
        ),
        recent: (
          <section className="panel" aria-labelledby="studio-recent">
            <div className="panel-head"><h2 id="studio-recent">Recent projects</h2><a className="btn btn-small" href="#/projects">All projects</a></div>
            {items !== null && recent.length === 0 ? (
              <p className="muted small">Nothing finished yet.</p>
            ) : (
              <div className="lib-grid">{recent.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
            )}
          </section>
        ),
        publishing: (
          <section className="panel" aria-labelledby="studio-publishing">
            <div className="panel-head"><h2 id="studio-publishing">Publishing</h2><a className="btn btn-small" href="#/publishing/review">Open</a></div>
            <PublishingStatus />
          </section>
        ),
      }} />
      <p className="studio-customize small muted">
        <button type="button" className="link-btn" onClick={() => setCustomizing(true)}><Icon name="sliders" size={14} />Customize studio</button>
        {" "}to choose which panels show here, their order, the office size and the colours.
      </p>
    </div>
  );
}

/** The Studio's panels in the order and visibility saved for this device (Customize studio). Recent projects and
 * Publishing share a row when they are next to each other; a panel with nothing to show is left out. */
function StudioPanels({ order, panels }: { order: { id: string; visible: boolean }[] | undefined;
  panels: Record<string, ReactNode> }) {
  const ids = (order?.length ? order : Object.keys(panels).map((id) => ({ id, visible: true })))
    .filter((p) => p.visible && panels[p.id]).map((p) => p.id);
  const out: ReactNode[] = [];
  for (let n = 0; n < ids.length; n++) {
    const pair = ["recent", "publishing"];
    if (pair.includes(ids[n]) && pair.includes(ids[n + 1] || "")) {
      out.push(<div key={ids[n]} className="studio-bottom">{panels[ids[n]]}{panels[ids[n + 1]]}</div>);
      n++;
    } else out.push(<div key={ids[n]} className="studio-panel-slot">{panels[ids[n]]}</div>);
  }
  return <>{out}</>;
}

function stageWords(i: LibraryItem): string {
  if (i.status === "queued") return i.message || "Waiting to start";
  return i.message || (i.kind === "full_video" ? VIDEO_WORDS[i.status] : i.stage) || i.status;
}

/** The current project: its picture, the step it is really at (queued or running, from the recorded work), progress
 * only when measured, the robots responsible for it and what to do next. */
function CurrentProject({ item, jobs, roles, onRobot }: {
  item: LibraryItem; jobs: OwnerWork[]; roles: RoleRow[]; onRobot: (id: string) => void;
}) {
  const [broken, setBroken] = useState(false);
  const live = jobs.filter((w) => w.status === "running");
  const step = live[0] || jobs.find((w) => w.waiting_on === "you") || jobs[0];
  const yours = jobs.filter((w) => w.waiting_on === "you");
  const state = live.length ? "Working" : yours.length ? "Waiting for you"
    : jobs.length || item.status === "queued" ? "Queued" : "In progress";
  const progress = live.map((w) => w.progress).find((p) => typeof p === "number") ?? null;
  const team = useMemo(() => [...new Set(jobs.map((w) => w.role))].filter((id) => BY_ID[id]), [jobs]);
  const rows = Object.fromEntries(roles.map((r) => [r.id, r]));
  const depts = [...new Set(team.map((id) => BY_ID[id].dept))]
    .map((d) => (DEPARTMENTS as Record<string, { name: string }>)[d]?.name).filter(Boolean);
  return (
    <article className="current-project">
      {item.thumbnail && !broken ? <img className="thumb" src={item.thumbnail} alt="" onError={() => setBroken(true)} />
        : <div className="thumb" aria-hidden="true" />}
      <div className="stack-2 grow">
        <div><b className="clamp-1">{item.name}</b><span className="small muted block">{KIND_WORD(item)}</span></div>
        <p className="small"><span className={`pill${state === "Working" ? " info" : ""}`}>{state}</span>{" "}
          {step?.message || stageWords(item)}</p>
        {typeof progress === "number" ? <ProgressBar value={progress} label={`${item.name} progress`} />
          : <p className="tiny muted"><Icon name="clock" size={12} /> Progress is not measured for this step.</p>}
        {team.length > 0 && (
          <div className="current-team">
            <span className="tiny muted">Team: {depts.join(" · ")}</span>
            <div className="row wrap">
              {team.map((id) => (
                <button key={id} type="button" className="op-chip" onClick={() => onRobot(id)}
                  aria-label={`${BY_ID[id].name}, ${BY_ID[id].title}. Show in the office`}>
                  <Portrait id={id} scale={1} pose={POSE_OF[rows[id]?.state || "idle"]} animate={false} crop />
                  {BY_ID[id].name}<span className="muted tiny">{BY_ID[id].title}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <a className="btn btn-primary" href={item.href}>{item.kind === "full_video" ? "Open the editor" : "Open project"}</a>
    </article>
  );
}

function PublishingStatus() {
  const { st } = useStatus();
  const posts = st?.home.posts;
  const next = st?.home.upcoming?.[0];
  if (!st) return <p className="muted small">Loading…</p>;
  const nothing = !posts?.review && !posts?.fix && !next;
  return (
    <ul className="studio-facts small">
      {!!posts?.review && <li><a href="#/publishing/review">{posts.review} waiting for your OK</a></li>}
      {!!posts?.fix && <li><a href="#/publishing/problems">{posts.fix} need you to settle something</a></li>}
      {next && <li>Next post: {timeLabel(next.planned_at, st.timezone)}{next.platform ? `, ${next.platform === "youtube" ? "YouTube" : "TikTok"}` : ""}</li>}
      {nothing && <li className="muted">Nothing waiting. Posts go only to the accounts and audience you choose.</li>}
    </ul>
  );
}

export function LibraryCard({ item }: { item: LibraryItem }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="lib-card-wrap">
      <a className="lib-card" href={item.href}>
        {item.thumbnail && !broken ? <img className="thumb" src={item.thumbnail} alt="" loading="lazy" onError={() => setBroken(true)} />
          : <div className="thumb" aria-hidden="true" />}
        <div className="body">
          <b className="clamp-1">{item.name}</b>
          <span className="small muted">{KIND_WORD(item)}</span>
          <span className="small">{statusWords(item)}</span>
        </div>
      </a>
      <PinButton id={item.id} name={item.name} />
    </div>
  );
}

const PIN_MAX = 12;  // clipfoundry/studio/prefs.py PIN_MAX

/** Pin a project to the top of the Studio page (saved with your appearance, per workspace). */
export function PinButton({ id, name }: { id: string; name: string }) {
  const { saved, set } = useAppearance();
  const on = saved.pinned.includes(id);
  const toggle = () => {
    if (!on && saved.pinned.length >= PIN_MAX) {
      toast(`You can pin up to ${PIN_MAX} projects. Unpin one first.`, true);
      return;
    }
    set({ pinned: on ? saved.pinned.filter((x) => x !== id) : [...saved.pinned, id] });
    toast(on ? `${name} is no longer pinned` : `${name} is pinned to the Studio page`);
  };
  return (
    <button type="button" className={`pin-btn${on ? " on" : ""}`} aria-pressed={on} onClick={toggle}
      aria-label={on ? `Unpin ${name}` : `Pin ${name} to the Studio page`} title={on ? "Unpin" : "Pin to Studio"}>
      <Icon name="spark" size={14} />{on ? "Pinned" : "Pin"}
    </button>
  );
}

export function statusWords(i: LibraryItem): string {
  if (i.status === "ready") return i.kind === "clips" ? `${i.clip_count || 0} clip${i.clip_count === 1 ? "" : "s"} ready` : "Ready";
  if (i.status === "error" || i.status === "failed") return "Stopped: open it to see why";
  if (RUNNING.has(i.status)) return i.message || "Working";
  return i.message || i.status;
}
