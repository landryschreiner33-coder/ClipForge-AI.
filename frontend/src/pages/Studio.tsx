import { KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { ap, ScheduledItem } from "../autopilot";
import { BlackHole } from "../components/BlackHole";
import { Banner, Icon, IconName, ProgressBar, toast } from "../components/ui";
import { DeleteProjectButton } from "../components/DeleteProject";
import { useAppearance } from "../prefs";
import { motionChoice, useMotion } from "../motion";
import { loadPost, timeLabel } from "../components/postShared";
import { useStatus } from "../status";
import { LibraryItem, studio } from "../studio";
import { LiveStream, submissions } from "../submissions";
import { BY_ID, CAST, ROOM_NAMES } from "../office/cast";
import { OfficeEvent, OwnerWork, RoleRow, Snapshot, staleHealth } from "../office/api";
import { OfficeFeed, useOffice } from "../office/useOffice";
import OfficeMap from "../office/OfficeMap";
import { ActivityList, ActivityPanel, POSE_OF, RobotPanel, RoomPanel } from "../office/panels";
import { ROOM_ACCENT } from "../office/world";
import Portrait from "../office/Portrait";
import { Sel, useOfficeSelection } from "./Office";
import "../office/studio.css";
import "./shorts.css";

const RUNNING = new Set(["queued", "processing", "importing", "uploading", "building", "rendering"]);
const STOPPED = new Set(["error", "failed", "needs_input"]);
// what a full video's status means while no step has said more
const VIDEO_WORDS: Record<string, string> = { building: "Building the rough cut", rendering: "Making the video",
  queued: "Waiting to start", importing: "Getting the video from your link" };
const KIND_WORD = (i: LibraryItem) => i.kind === "full_video" ? (i.mode === "animated_short" ? "Animated short" : "YouTube video")
  : i.mode === "full_stories" ? (i.story_split === "parts" ? "Clips · Story parts" : "Clips · Full stories")
  : "Clips · Highlights";
/** How long a finished clips project stays in "Now making" as "Your clips are ready". */
const READY_FOR = 6 * 3600;
const PLATFORM: Record<string, string> = { youtube: "YouTube", tiktok: "TikTok" };

/**
 * Studio (the space studio, 2026-11-19): the ship with its crew over the real work and, beside it, the Studio panel.
 * Its Working on tab is what is being made now on a screen with its real step and measured progress, what the crew
 * just did, what waits next, Talk to ClipForge AI and, at the bottom, the next video to publish; its Make tab holds
 * the four big Make buttons (the owner, 2026-11-19 8:47 PM). Everything the ship shows has an ordinary button or list
 * entry here too, and nothing on this page estimates or invents work.
 */
export default function Studio() {
  const feed = useOffice();
  const { st } = useStatus();
  const { appearance, layout } = useAppearance();
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [problem, setProblem] = useState("");
  const [sel, setSel] = useOfficeSelection("studio");
  // the Studio panel opens on Working on each visit, so coming back after starting something shows it being made
  const [tab, setTab] = useState<PanelTab>("now");
  const review = useReviewQueue(st ? st.home.posts.review : null);
  const live = useLiveRecordings();

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

  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && sel && !document.querySelector(".modal-bg, .dialog")) setSel(null);
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [sel, setSel]);

  // while the feed is lost, health shows as Unknown, never as the last green readings
  const snap = useMemo(() => (feed.snap && feed.lost
    ? { ...feed.snap, health: staleHealth(feed.snap.health, feed.lastOk) } : feed.snap),
  [feed.snap, feed.lost, feed.lastOk]);
  const work = snap?.work || [];
  const jobsFor = (i: LibraryItem) => work.filter((w) => w.project_id === i.id || w.video_id === i.id);
  // the project something is really running for comes first, then the newest
  const running = (items || []).filter((i) => RUNNING.has(i.status))
    .map((i, n) => ({ i, n, live: jobsFor(i).some((w) => w.status === "running") }))
    .sort((a, b) => Number(b.live) - Number(a.live) || a.n - b.n).map((x) => x.i);
  const stopped = (items || []).filter((i) => STOPPED.has(i.status)).slice(0, 5);
  const recent = (items || []).filter((i) => !RUNNING.has(i.status)).slice(0, 6);
  const actions = (st?.home.needs_you || []).filter((n) => n.fix || n.link).slice(0, 5);
  const yourTurn = work.filter((w) => w.waiting_on === "you" && w.video_id).slice(0, 5);
  const current = running[0];
  const now = Date.now() / 1000;
  const justMade = !current ? (items || []).find((i) => i.kind === "clips" && i.status === "ready"
    && (i.clip_count || 0) > 0 && now - i.updated_at < READY_FOR) : undefined;
  const pinned = appearance.pinned.map((id) => (items || []).find((i) => i.id === id)).filter(Boolean) as LibraryItem[];
  const order = layout.screens.studio?.length ? layout.screens.studio : null;
  const shown = (id: string) => !order || order.some((p) => p.id === id && p.visible);
  const onRobot = (id: string) => setSel({ type: "robot", id, card: null });
  const needs = shown("needs_you") ? stopped.length + actions.length + yourTurn.length : 0;

  return (
    <div className={`page studio-page studio-space ship-${appearance.office_size}`}>
      <h1 className="sr-only" tabIndex={-1}>Studio</h1>
      {problem && <Banner tone="warn" title="Could not load your projects">{problem}</Banner>}
      <div className="studio-layout">
        <section className="studio-ship" aria-labelledby="studio-office">
          <div className="studio-sky" aria-hidden="true"><BlackHole size="large" /></div>
          {shown("office") ? (
            <StudioShip feed={feed} snap={snap} sel={sel} setSel={setSel} dockCue={review.cue} />
          ) : (
            <div className="ship-hidden">
              <h2 id="studio-office">Robot office</h2>
              <p className="muted">The robot office is hidden on this device. Settings → Appearance → Customize studio
                shows it again.</p>
            </div>
          )}
          <TodayStrip snap={snap} review={st ? st.home.posts.review : null} />
        </section>
        <aside className="studio-side" aria-label={sel ? "Details" : "Studio panel"}>
          {sel && snap ? (
            <ShipDetails sel={sel} setSel={setSel} snap={snap} feed={feed} />
          ) : (
            <StudioPanel tab={tab} setTab={setTab} busy={running.length + live.length}
              now={<>
                <NowMaking item={current} ready={justMade} jobs={current ? jobsFor(current) : []}
                  loading={items === null} roles={snap?.roles || []} paused={snap?.run.state === "paused"}
                  onRobot={onRobot} onMake={() => setTab("make")} />
                <GoingOn events={feed.events} skew={feed.skew} onRobot={onRobot}
                  onAll={() => setSel({ type: "activity" })} />
                <QueueList running={running.slice(1)} live={live} review={review.items} />
                {needs > 0 && <NeedsYouLink count={needs} />}
                <AskAI />
                <NextPost />
              </>}
              make={<>
                <MakeTiles />
                <AskAI make />
              </>} />
          )}
        </aside>
      </div>

      {(stopped.length > 0 || actions.length > 0 || yourTurn.length > 0) && shown("needs_you") && (
        <section className="studio-band needs-you" aria-labelledby="studio-needs">
          <h2 id="studio-needs" tabIndex={-1}>Needs you</h2>
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
      )}
      {pinned.length > 0 && shown("pinned") && (
        <section className="studio-band" aria-labelledby="studio-pinned">
          <h2 id="studio-pinned">Pinned</h2>
          <div className="lib-grid">{pinned.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
        </section>
      )}
      {shown("recent") && (
        <section className="studio-band" aria-labelledby="studio-recent">
          <div className="panel-head"><h2 id="studio-recent">Recent projects</h2>
            <a className="btn btn-small" href="#/projects"><Icon name="folder" />All projects</a></div>
          {items !== null && recent.length === 0 ? (
            <p className="muted small">Nothing finished yet. Projects you make appear here and under Projects.</p>
          ) : (
            <div className="lib-grid">{recent.map((i) => <LibraryCard key={i.id} item={i} />)}</div>
          )}
        </section>
      )}
    </div>
  );
}

/** The ship with the quiet row beneath it: Whole ship, Activity and Reduce motion (the same setting as Settings →
 * Appearance → Motion). */
function StudioShip({ feed, snap, sel, setSel, dockCue }: {
  feed: OfficeFeed; snap: Snapshot | null; sel: Sel; setSel: (s: Sel) => void; dockCue: number;
}) {
  const { reduceMotion, systemReducedMotion, setAnimationMode, officeActivity } = useMotion();
  const connected = !!feed.snap && !feed.lost && !feed.error && feed.lastOk !== null;
  const toggleMotion = () => setAnimationMode(motionChoice(reduceMotion, systemReducedMotion));
  return (
    <>
      <div className="ship-head">
        <h2 id="studio-office">Robot office</h2>
        <span className="ship-count">{CAST.length} robots</span>
        <span className={`ship-live${connected ? " on" : ""}`}>
          <span className="state-dot" aria-hidden="true" />
          {connected ? "Showing live work" : feed.lost ? "Not updating: last known states" : "Connecting"}
        </span>
        <span className="spacer" />
        <a className="btn btn-small btn-quiet" href="#/office"><Icon name="external" />Bigger view</a>
      </div>
      {snap ? (
        <OfficeMap snap={snap} subscribe={feed.subscribe} skew={feed.skew} simple dockCue={dockCue}
          reduce={reduceMotion || officeActivity === "low_power"} stale={feed.lost}
          selected={sel?.type === "robot" ? sel.id : null} room={sel?.type === "room" ? sel.id : null}
          onRobot={(id, card) => setSel({ type: "robot", id, card })} onRoom={(id) => setSel({ type: "room", id })}
          tools={<>
            <button type="button" className="ship-tool" aria-pressed={sel?.type === "activity"}
              onClick={() => setSel(sel?.type === "activity" ? null : { type: "activity" })}>
              <Icon name="bars" />Activity</button>
            <button type="button" role="switch" aria-checked={reduceMotion} className="ship-tool switch"
              onClick={toggleMotion}>
              <Icon name="settings" />Reduce motion<span className="track" aria-hidden="true" /></button>
          </>} />
      ) : feed.error ? (
        <Banner tone="warn" title="The robot office could not load"
          actions={<button type="button" className="btn btn-small" onClick={() => feed.reload().catch(() => {})}>
            <Icon name="refresh" />Try again</button>}>
          {feed.error} Your projects below still work.
        </Banner>
      ) : <p className="muted ship-loading">Opening the robot office…</p>}
    </>
  );
}

/** A robot, room or the activity feed, opened from the ship or its row; Back (or Escape) goes back to the Studio
 * panel's tab. */
function ShipDetails({ sel, setSel, snap, feed }: { sel: NonNullable<Sel>; setSel: (s: Sel) => void; snap: Snapshot;
  feed: OfficeFeed }) {
  const title = sel.type === "robot" ? BY_ID[sel.id]?.name : sel.type === "room" ? ROOM_NAMES[sel.id] : "Activity";
  const eyebrow = sel.type === "robot" ? BY_ID[sel.id]?.title : sel.type === "room" ? "Room on the ship" : "What the crew did";
  const accent = sel.type === "room" ? ROOM_ACCENT[sel.id] : sel.type === "robot" ? BY_ID[sel.id]?.palette.trim : undefined;
  const onRobot = (id: string) => setSel({ type: "robot", id, card: null });
  return (
    <div className="ship-details office-studio" style={accent ? { ["--accent" as string]: accent } as React.CSSProperties : undefined}>
      <div className="op-head">
        <div className="studio-panel-title">
          <span className="studio-eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <span className="spacer" />
        <button type="button" className="btn btn-small" onClick={() => setSel(null)}><Icon name="back" />Back</button>
      </div>
      {sel.type === "robot" ? (
        <RobotPanel key={sel.id} id={sel.id} row={snap.roles.find((r) => r.id === sel.id)} card={sel.card} onRobot={onRobot}
          events={feed.events} skew={feed.skew} />
      ) : sel.type === "room" ? (
        <RoomPanel key={sel.id} id={sel.id} snap={snap} onRobot={onRobot} stale={feed.lost} />
      ) : (
        <ActivityPanel events={feed.events} skew={feed.skew} onRobot={onRobot} />
      )}
    </div>
  );
}

function stageWords(i: LibraryItem): string {
  if (i.status === "queued") return i.message || "Waiting to start";
  return i.message || (i.kind === "full_video" ? VIDEO_WORDS[i.status] : i.stage) || i.status;
}

type PanelTab = "now" | "make";
const PANEL_TABS: { id: PanelTab; label: string; icon: IconName }[] = [
  { id: "now", label: "Working on", icon: "clapper" }, { id: "make", label: "Make", icon: "plus" }];

/** The Studio panel beside the ship (below it on a narrow window): Working on, then Make, as two tabs. Arrow keys,
 * Home and End move between the tabs, as in any tab list. */
function StudioPanel({ tab, setTab, busy, now, make }: { tab: PanelTab; setTab: (t: PanelTab) => void; busy: number;
  now: ReactNode; make: ReactNode }) {
  const tabs = useRef<Partial<Record<PanelTab, HTMLButtonElement | null>>>({});
  const onKey = (e: ReactKeyboardEvent) => {
    const at = PANEL_TABS.findIndex((t) => t.id === tab);
    const to = e.key === "ArrowRight" ? (at + 1) % PANEL_TABS.length
      : e.key === "ArrowLeft" ? (at + PANEL_TABS.length - 1) % PANEL_TABS.length
        : e.key === "Home" ? 0 : e.key === "End" ? PANEL_TABS.length - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    setTab(PANEL_TABS[to].id);
    tabs.current[PANEL_TABS[to].id]?.focus();
  };
  return (
    <>
      <div className="side-tabs" role="tablist" aria-label="Studio panel" onKeyDown={onKey}>
        {PANEL_TABS.map((t) => (
          <button key={t.id} ref={(el) => { tabs.current[t.id] = el; }} type="button" role="tab" id={`side-tab-${t.id}`}
            className="side-tab" aria-selected={tab === t.id} aria-controls={`side-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1} onClick={() => setTab(t.id)}>
            <Icon name={t.icon} />{t.label}
            {t.id === "now" && busy > 0 && <span className="tab-count"><span className="sr-only">, being made: </span>
              {busy}</span>}
          </button>
        ))}
      </div>
      <div className="side-panel" role="tabpanel" id="side-panel-now" aria-labelledby="side-tab-now"
        hidden={tab !== "now"}>{now}</div>
      <div className="side-panel" role="tabpanel" id="side-panel-make" aria-labelledby="side-tab-make"
        hidden={tab !== "make"}>{make}</div>
    </>
  );
}

/** What the crew did last, from the office feed of real job steps; See everything opens the whole feed here. */
function GoingOn({ events, skew, onRobot, onAll }: { events: OfficeEvent[]; skew: number;
  onRobot: (id: string) => void; onAll: () => void }) {
  return (
    <section className="studio-going" aria-labelledby="studio-going">
      <h2 id="studio-going">What's going on</h2>
      <ActivityList events={events} skew={skew} limit={3} onRobot={onRobot} />
      <button type="button" className="link-btn small" onClick={onAll}>See everything the crew did</button>
    </section>
  );
}

/** How many things wait for you, with a button down to them (the Needs you list under the ship). */
function NeedsYouLink({ count }: { count: number }) {
  const show = () => {
    const band = document.getElementById("studio-needs");
    band?.scrollIntoView({ block: "start" });
    band?.focus({ preventScroll: true });
  };
  return (
    <button type="button" className="needs-row" onClick={show}>
      <Icon name="alert" />
      <span><b>{count === 1 ? "1 thing needs you" : `${count} things need you`}</b>
        <span className="block muted">Show me what</span></span>
    </button>
  );
}

/** Talking to ClipForge AI, one press from the Studio (the owner: "make sure im still able to talk to the AI"). */
function AskAI({ make = false }: { make?: boolean }) {
  return (
    <a className="studio-ask" href="#/brain/talk">
      <span className="ask-icon"><Icon name="chat" /></span>
      <span><b>{make ? "Not sure what to make?" : "Talk to ClipForge AI"}</b>
        <span className="block muted">{make ? "Tell ClipForge AI your idea and ask what to make."
          : "Ask a question or get ideas for your next video."}</span></span>
    </a>
  );
}

/** Everything ClipForge makes, one press away (the owner, 2026-11-19: "make everything easily accessible"). The same
 * four choices as + Make at the top of every page. */
const MAKE_CHOICES: { href: string; icon: IconName; title: string; words: string }[] = [
  { href: "#/create/clips", icon: "scissors", title: "Make clips", words: "The best moments, or whole stories" },
  { href: "#/create/video", icon: "video", title: "Make a YouTube video", words: "Your files and your idea" },
  { href: "#/create/short", icon: "spark", title: "Make an animated short", words: "Moving pictures and a voice-over" },
  { href: "#/missions/live", icon: "live", title: "Clip a live stream", words: "Clips while it is still live" },
];

function MakeTiles() {
  return (
    <nav className="studio-make" aria-labelledby="studio-make">
      <h2 id="studio-make">Make something</h2>
      <ul>
        {MAKE_CHOICES.map((c, i) => (
          <li key={c.href}>
            <a className={`make-tile${i === 0 ? " first" : ""}`} href={c.href}>
              <span className="make-icon"><Icon name={c.icon} /></span>
              <b>{c.title}</b><span className="make-words">{c.words}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** What is being made now: the project on a screen, its real step, progress only when measured, the robots on it and
 * one button to open it. With nothing running, a clips project that just finished says so, or the crew rests and
 * Make something opens the Make tab. */
function NowMaking({ item, ready, jobs, roles, loading, paused, onRobot, onMake }: {
  item?: LibraryItem; ready?: LibraryItem; jobs: OwnerWork[]; roles: RoleRow[]; loading: boolean; paused: boolean;
  onRobot: (id: string) => void; onMake: () => void;
}) {
  const [broken, setBroken] = useState("");
  const shown = item || ready;
  if (loading) return <section className="now-making" aria-labelledby="now-making"><h2 id="now-making">Now making</h2>
    <p className="muted">Loading…</p></section>;
  if (!shown) {
    return (
      <section className="now-making idle" aria-labelledby="now-making">
        <h2 id="now-making">Now making</h2>
        <p className="now-empty"><b>Nothing is being made right now.</b>
          <span className="block muted">The crew is relaxing in the lounge until you pick something to make.</span></p>
        <button type="button" className="btn btn-primary btn-wide" onClick={onMake}><Icon name="plus" />
          Make something</button>
      </section>
    );
  }
  const live = jobs.filter((w) => w.status === "running");
  const yours = jobs.find((w) => w.waiting_on === "you");
  const step = live[0] || yours || jobs[0];
  const progress = item ? live.map((w) => w.progress).find((p) => typeof p === "number")
    ?? (typeof item.progress === "number" && live.length ? item.progress : null) : null;
  const words = !item ? `${ready!.clip_count || 0} clip${ready!.clip_count === 1 ? "" : "s"} ready to review`
    : yours ? `Waiting for you: ${yours.message || "an answer"}`
    : paused && !live.length ? "Paused" : step?.message || stageWords(item);
  const crew = item ? [...new Set([...jobs.map((w) => w.role), ...roles.filter((r) => r.task
    && (r.task.ref_id === item.id || r.task.shared?.project_id === item.id)).map((r) => r.id)])]
    .filter((id) => BY_ID[id]) : [];
  const rows = Object.fromEntries(roles.map((r) => [r.id, r]));
  const open = item ? (item.kind === "full_video" ? "Open the editor" : "Open project") : "Review clips";
  // the screen's light: what the project is doing, in a word or two (the line below the screen says it in full)
  const light = !item ? ["ready", "Ready"] : yours ? ["wait", "Your turn"] : live.length ? ["on", "Making"]
    : paused ? ["", "Paused"] : ["", "Waiting"];
  return (
    <section className={`now-making${ready ? " ready" : ""}`} aria-labelledby="now-making">
      <h2 id="now-making">{item ? "Now making" : "Your clips are ready"}</h2>
      <a className="now-screen" href={shown.href} tabIndex={-1} aria-hidden="true">
        <span className="now-thumb">
          {shown.thumbnail && broken !== shown.id ? <img src={shown.thumbnail} alt="" onError={() => setBroken(shown.id)} />
            : <span className="thumb-empty"><Icon name="film" /></span>}
        </span>
        <span className={`screen-light ${light[0]}`}><span className="state-dot" />{light[1]}</span>
        {typeof progress === "number" && <span className="screen-pct">{Math.round(progress * 100)}%</span>}
      </a>
      <div className="now-title">
        <h3 className="clamp-2">{shown.name}</h3>
        <span className="muted">{KIND_WORD(shown)}</span>
      </div>
      <p className="now-step" role="status" aria-live="polite">
        <span>{words}</span>
        {typeof progress === "number" && <b>{Math.round(progress * 100)}%</b>}
      </p>
      {typeof progress === "number" ? <ProgressBar value={progress} label={`${shown.name} progress`} />
        : item && <p className="tiny muted"><Icon name="clock" size={12} /> This step does not measure its progress.</p>}
      {crew.length > 0 && (
        <div className="now-crew">
          <span className="small muted">On the ship:</span>
          {crew.slice(0, 3).map((id) => (
            <button key={id} type="button" className="op-chip" onClick={() => onRobot(id)}
              aria-label={`${BY_ID[id].name}, ${BY_ID[id].title}. Show on the ship`}>
              <Portrait id={id} scale={1} pose={POSE_OF[rows[id]?.state || "idle"]} animate={false} crop />
              {BY_ID[id].name}
            </button>
          ))}
        </div>
      )}
      <a className={`btn btn-wide ${item ? "btn-outline" : "btn-primary"}`}
        href={item ? shown.href : `${shown.href}/clips`}>
        {item ? <Icon name="external" /> : <Icon name="play" />}{open}</a>
    </section>
  );
}

/** Next in line: other projects being made, live recordings and posts that wait for your OK. */
function QueueList({ running, live, review }: { running: LibraryItem[]; live: LiveStream[]; review: ScheduledItem[] }) {
  const rows: { key: string; href: string; thumb: string; name: string; words: string }[] = [
    ...live.map((l) => ({ key: `live-${l.id}`, href: "#/missions/live", thumb: l.project_id ? `/api/projects/${l.project_id}/thumbnail` : "",
      name: l.title || "Live stream", words: `Live · ${l.live.live_clips} clip${l.live.live_clips === 1 ? "" : "s"} found` })),
    ...running.map((i) => ({ key: i.id, href: i.href, thumb: i.thumbnail, name: i.name, words: stageWords(i) })),
    ...review.map((r) => ({ key: `post-${r.id}`, href: "#/publishing/review", thumb: r.clip?.thumbnail_url || "",
      name: r.clip?.title || r.title || "Clip", words: `Ready for review · ${PLATFORM[r.platform] || r.platform}` })),
  ];
  return (
    <section className="studio-queue" aria-labelledby="studio-queue">
      <h2 id="studio-queue">Queue</h2>
      {rows.length === 0 ? <p className="small muted">Nothing else is waiting.</p> : (
        <ul>
          {rows.slice(0, 3).map((r) => <QueueRow key={r.key} href={r.href} thumb={r.thumb} name={r.name} words={r.words} />)}
        </ul>
      )}
      {rows.length > 3 && <a className="small" href="#/projects">{rows.length - 3} more</a>}
    </section>
  );
}

function QueueRow({ href, thumb, name, words }: { href: string; thumb: string; name: string; words: string }) {
  const [broken, setBroken] = useState(false);
  return (
    <li>
      <a className="queue-row" href={href}>
        {thumb && !broken ? <img src={thumb} alt="" loading="lazy" onError={() => setBroken(true)} />
          : <span className="thumb-empty" aria-hidden="true"><Icon name="film" /></span>}
        <span className="break"><b className="clamp-1">{name}</b><span className="block muted">{words}</span></span>
      </a>
    </li>
  );
}

/** The next video to publish, at the bottom of Working on: a little screen of its clip, where and when it goes. */
function NextPost() {
  const { st } = useStatus();
  const next = st?.home.upcoming?.[0];
  const [thumb, setThumb] = useState<{ id: string; src: string } | null>(null);
  const [broken, setBroken] = useState("");
  useEffect(() => {
    if (!next?.id) return;
    let alive = true;
    // a plain read of that one post, for its clip's picture
    loadPost(next.id).then((r) => {
      const clip = r.items[0]?.clip;
      if (alive) setThumb(clip?.has_thumbnail && clip.thumbnail_url ? { id: next.id, src: clip.thumbnail_url } : null);
    }).catch(() => alive && setThumb(null));
    return () => {
      alive = false;
    };
  }, [next?.id]);
  const pic = next && thumb?.id === next.id && broken !== thumb.src ? thumb.src : "";
  return (
    <section className="studio-next" aria-labelledby="studio-next">
      <h2 id="studio-next">Next to publish</h2>
      {!st ? <p className="muted">Loading…</p> : next ? (
        <a className="next-row" href={`#/post/${next.id}`}>
          <span className="little-screen" aria-hidden="true">
            {pic ? <img src={pic} alt="" loading="lazy" onError={() => setBroken(pic)} />
              : <span className="thumb-empty"><Icon name="film" /></span>}
          </span>
          <span className="break"><b className="clamp-2">{next.title || "Your clip"}</b>
            <span className="block muted">{PLATFORM[next.platform] || next.platform}</span>
            <span className="block small"><Icon name="calendar" size={14} /> {timeLabel(next.planned_at, st.timezone)}</span>
          </span>
        </a>
      ) : <p className="muted">No posts scheduled yet.</p>}
      <a className="small" href="#/publishing/scheduled">View schedule</a>
    </section>
  );
}

/** Today's real counts and whether the computer can make video now. */
function TodayStrip({ snap, review }: { snap: Snapshot | null; review: number | null }) {
  const gpu = snap?.health.checks.find((c) => c.id === "gpu");
  const tone = !gpu ? "" : gpu.status === "healthy" ? "good" : gpu.status === "degraded" ? "warn"
    : gpu.status === "error" ? "bad" : "";
  const n = (v: number | undefined | null) => (v === undefined || v === null ? "–" : String(v));
  return (
    <div className="studio-today" role="group" aria-label="Today">
      <a href="#/projects"><b>{n(snap?.today.clips)}</b> clip{snap?.today.clips === 1 ? "" : "s"} made today</a>
      <a href="#/publishing/published"><b>{n(snap?.today.uploads)}</b> published today</a>
      <a href="#/publishing/review"><b>{n(review)}</b> need{review === 1 ? "s" : ""} review</a>
      <span className={`studio-compute ${tone}`} title={gpu?.reason}>
        <Icon name="cpu" /><span className="state-dot" aria-hidden="true" />
        {!gpu ? "Checking the computer" : gpu.status === "healthy" ? "GPU ready" : `GPU: ${gpu.status_label}`}
      </span>
    </div>
  );
}

// posts the Dock has seen arrive for review this visit, so each one is acknowledged once
let reviewSeen: Set<string> | null = null;

/** The posts waiting for your OK. When one arrives while the Studio is open, the Dock acknowledges it once. */
function useReviewQueue(count: number | null): { items: ScheduledItem[]; cue: number } {
  const [items, setItems] = useState<ScheduledItem[]>([]);
  const [cue, setCue] = useState(0);
  const first = useRef(true);
  useEffect(() => {
    if (count === null) return;
    let alive = true;
    const settle = (list: ScheduledItem[]) => {
      const ids = list.map((i) => i.id);
      if (first.current || reviewSeen === null) reviewSeen = new Set(ids);  // what was already there is not news
      else if (ids.some((id) => !reviewSeen!.has(id))) {
        ids.forEach((id) => reviewSeen!.add(id));
        setCue(performance.now());
      }
      first.current = false;
      setItems(list);
    };
    if (count === 0) settle([]);
    else ap.scheduled("review").then((r) => alive && settle(r.items)).catch(() => {});
    return () => {
      alive = false;
    };
  }, [count]);
  return { items, cue };
}

/** Live streams being recorded now (Missions → Live streams). */
export function useLiveRecordings(): LiveStream[] {
  const [rows, setRows] = useState<LiveStream[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => submissions.live().then((x) => alive && setRows(x.filter((l) => l.live.recording)))
      .catch(() => {});
    load();
    const t = window.setInterval(load, 10000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  return rows;
}

/** A project's card: its picture with the video's length, its name, what kind it is and where it stands. With
 * `onDelete` (the Projects page) it has a trash button that opens the confirmation. */
export function LibraryCard({ item, onDelete }: { item: LibraryItem; onDelete?: () => void }) {
  const [broken, setBroken] = useState(false);
  const length = item.duration ? clock(item.duration) : "";
  const running = RUNNING.has(item.status);
  return (
    <div className="lib-card-wrap">
      <a className="lib-card" href={item.href}>
        <span className="lib-thumb">
          {item.thumbnail && !broken ? <img className="thumb" src={item.thumbnail} alt="" loading="lazy" onError={() => setBroken(true)} />
            : <span className="thumb" aria-hidden="true" />}
          {length && <span className="lib-length"><Icon name="play" size={11} fill /><span className="sr-only">Length </span>{length}</span>}
        </span>
        <span className="body">
          <b className="clamp-2">{item.name}</b>
          <span className="lib-line"><Icon name={KIND_ICON(item)} size={16} />{KIND_WORD(item)}</span>
          <span className={`lib-line${running ? " running" : ""}`}><Icon name="layers" size={16} />
            {running && <i className="state-dot" aria-hidden="true" />}{statusWords(item)}</span>
        </span>
      </a>
      <span className="lib-card-tools">
        <PinButton id={item.id} name={item.name} />
        {onDelete && <DeleteProjectButton name={item.name} onClick={onDelete} />}
      </span>
    </div>
  );
}

const KIND_ICON = (i: LibraryItem): IconName => i.kind === "clips" ? "clapper" : i.mode === "animated_short" ? "spark" : "video";
/** 75 → "1:15", 3725 → "1:02:05". */
function clock(seconds: number): string {
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
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
      <Icon name="pin" size={15} /><span className="pin-word">{on ? "Pinned" : "Pin"}</span>
    </button>
  );
}

export function statusWords(i: LibraryItem): string {
  if (i.status === "ready") return i.kind === "clips" ? `${i.clip_count || 0} clip${i.clip_count === 1 ? "" : "s"} ready` : "Ready";
  if (i.status === "error" || i.status === "failed") return "Stopped: open it to see why";
  if (RUNNING.has(i.status)) return i.message || "Working";
  return i.message || i.status;
}
