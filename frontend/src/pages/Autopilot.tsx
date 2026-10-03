import RobotOffice from "../components/RobotOffice";
import { useState } from "react";
import { api, errorText, Platform, Project, projectThumbUrl, timeAgo } from "../api";
import { ActivityItem, ap, AutopilotStatus } from "../autopilot";
import { PLATFORM_NAME } from "../components/accounts";
import AdvancedView from "../components/apAdvanced";
import LinkIntake from "../components/apLinkIntake";
import { ConnectAction, OpenVideosFolder, PLATFORMS, UpcomingRow } from "../components/apShared";
import SourcesView from "../components/apSources";
import { AutoPublishLine } from "../components/autoPublish";
import { needLook, NeedsYouList } from "../components/needsYou";
import {
  Banner, ConfirmDialog, Disclosure, Fact, Icon, IconName, LinkTabs, LoadingPage, PageHead, PlatformName, Pill,
  ProgressBar, Skel, TextPromptDialog, Thumb, toast, Tone, usePoll,
} from "../components/ui";
import { plural, zoneLine } from "../format";
import { useStatus } from "../status";

/**
 * Autopilot, the control room: the switch, the truthful state, what needs you, the current work, your videos folder,
 * upcoming posts and how posts go out (#/autopilot). Activity, Permissions & sources and Advanced (System, Jobs,
 * Learning) are one tab away. Before Autopilot was ever started, the overview points to Setup instead.
 */
const ADVANCED = ["system", "jobs", "learning"];
/** Your videos folder is checked by a fixed timer in the backend (feed_scan every 180 s), not a setting. */
const FOLDER_CHECK = "every 3 minutes";

export default function AutopilotPage({ tab }: { tab?: string }) {
  const { st, lost, lastOk, refresh, setData } = useStatus();
  if (!st) return <LoadingPage label="Loading Autopilot" />;
  const slug = tab || "";
  const advanced = ADVANCED.includes(slug);
  const since = lastOk ? new Date(lastOk).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  return (
    <div className="page">
      <PageHead title="Autopilot" sub="Finds videos you may use, makes clips, checks them and plans posts. Nothing is
        posted without your OK, or the permission you gave for YouTube." />
      {st.paused && <StoppedBanner refresh={refresh} />}
      <LinkTabs label="Autopilot sections" current={advanced ? "system" : slug || "overview"} tabs={[
        { id: "overview", href: "#/autopilot", label: "Overview" },
        { id: "activity", href: "#/autopilot/activity", label: "Activity" },
        { id: "sources", href: "#/autopilot/sources", label: "Permissions & sources" },
        { id: "system", href: "#/autopilot/system", label: "Advanced" },
      ]} />
      {advanced ? <AdvancedView which={slug} st={st} refresh={refresh} />
        : slug === "activity" ? <ActivityView st={st} refresh={refresh} />
          : slug === "sources" ? <SourcesView st={st} refreshStatus={refresh} />
            : <Overview st={st} lost={lost} since={since} refresh={refresh} setData={setData} />}
    </div>
  );
}

function StoppedBanner({ refresh }: { refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Banner tone="bad" icon="stop" title="All jobs are stopped." actions={
      <button type="button" className="btn btn-primary" disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          await ap.resume();
          toast("Jobs can run again");
        } catch (e) {
          toast(errorText(e), true);
        }
        setBusy(false);
        refresh();
      }}><Icon name="play" />Resume jobs</button>
    }>
      Nothing runs or posts until you resume. Work that was queued was canceled; running jobs stopped at a safe point.
    </Banner>
  );
}

// ------------------------------------------------------------------ the four facts
type FactValue = [Tone, IconName, string, string];

/** This PC: the real keep-awake state (PR #6), never the setting alone. "Kept awake" only when Windows agreed. */
const noAnswer = (since: string) => since ? `No answer from ClipFoundry since ${since}.`
  : "No answer from ClipFoundry.";

function sleepFact(st: AutopilotStatus, lost: boolean, since: string): FactValue {
  if (lost) return ["neutral", "offline", "Unknown", noAnswer(since)];
  if (!st.enabled || st.paused) return ["neutral", "moon", "Not kept awake", "Only while Autopilot is on."];
  switch (st.home.keep_awake) {
    case "on":
      return ["good", "check", "Kept awake", "Windows agreed to keep this PC from sleeping while Autopilot is on. "
        + "A laptop still sleeps if you close its lid."];
    case "pending":
      return ["neutral", "clock", "Asking Windows", "ClipFoundry is asking Windows to keep this PC awake. This is not "
        + "confirmed yet."];
    case "failed":
      return ["bad", "alert", "Windows said no", "Windows did not let ClipFoundry keep this PC awake. Turn off sleep "
        + "yourself: see Needs you."];
    case "unsupported":
      return ["neutral", "moon", "Not available on this computer", "Turn off sleep in the PC's power settings, or "
        + "Autopilot stops when the PC sleeps."];
    default:
      return ["neutral", "moon", "Not kept awake", "“Keep the PC awake” is off in Settings. Turn off sleep in the "
        + "PC's power settings, or Autopilot stops when the PC sleeps."];
  }
}

const every = (minutes: number) => minutes % 60 === 0 ? `every ${plural(minutes / 60, "hour")}`
  : `every ${minutes} minutes`;

// ------------------------------------------------------------------ overview
function Overview({ st, lost, since, refresh, setData }: {
  st: AutopilotStatus; lost: boolean; since: string; refresh: () => void; setData: (s: AutopilotStatus) => void;
}) {
  const h = st.home;
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const autoYouTube = !!h.auto_publish?.youtube?.enabled;
  if (!st.enabled && !h.setup.started) {
    return (
      <>
        <section className="panel" aria-labelledby="ap-off">
          <h2 id="ap-off">Autopilot is not set up</h2>
          <p className="muted">Autopilot finds videos it may use and makes local clips from links you add. It keeps
            looking and working by itself. Posting needs your OK or the permission you give for YouTube.</p>
          <div className="row wrap">
            <a className="btn btn-primary" href="#/setup/mode">Set up Autopilot</a>
            <a className="btn" href="#/create">Make clips yourself instead</a>
          </div>
        </section>
        <div className="ap-control-room">
          <RobotOffice />
          <LinkIntake enabled={st.enabled} stopped={st.paused} timezone={st.timezone} refreshStatus={refresh}
            autoYouTube={autoYouTube} />
        </div>
      </>
    );
  }

  const toggle = async (on: boolean) => {
    setBusy(true);
    try {
      setData(await ap.enable(on));
      toast(on ? "Autopilot is on" : "Autopilot is paused. Nothing new is found, clipped or posted.");
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };

  const on = st.enabled && !st.paused && !lost;
  const blocking = h.needs_you.filter((i) => needLook(i)[0] === "bad").length;
  const headline = lost ? "Autopilot's state is unknown" : st.paused ? "Autopilot is stopped"
    : !st.enabled ? "Autopilot is paused"
      : blocking ? `Autopilot is on, but ${plural(blocking, "problem needs", "problems need")} you`
        : "Autopilot is on";
  const dot = lost ? "" : st.paused ? "bad" : !st.enabled ? "warn" : blocking ? "warn" : "on pulse";
  const w = h.working;
  const line = lost ? noAnswer(since)
    : st.paused ? "All jobs are on hold until you resume them."
      : !st.enabled ? "Nothing new is found, clipped or posted. Things you start yourself still run."
        : `${h.currently}${w?.title ? ` in “${w.title}”` : ""}`;
  const [t1, i1, v1, d1] = sleepFact(st, lost, since);
  const searchEvery = every(Number(st.settings.trend_poll_minutes) || 180);
  const folder = h.my_videos;
  const progress = lost ? "Unknown" : !on ? "Waiting" : w?.message || (w?.progress != null
    ? `${Math.round(w.progress * 100)}% of this step` : w ? w.step : "No video being processed right now");
  const next = lost ? "Unknown" : !on ? "Waiting until Autopilot resumes"
    : h.next || "Checking for more videos";

  return (
    <>
      <section className="panel" aria-labelledby="ap-state">
        <div className="ap-status">
          <div className="grow stack">
            <h2 className="big" id="ap-state"><span className={`dot ${dot}`} aria-hidden="true" />{headline}</h2>
            <p className="muted">{line}</p>
          </div>
          {!st.paused && !lost && (st.enabled ? (
            <button type="button" className="btn" disabled={busy} onClick={() => toggle(false)}>
              <Icon name="pause" />Pause Autopilot</button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => toggle(true)}>
              <Icon name="play" />Start Autopilot</button>
          ))}
        </div>
      </section>

      <div className="ap-control-room">
        <RobotOffice />
        <LinkIntake enabled={st.enabled} stopped={st.paused} timezone={st.timezone} refreshStatus={refresh}
          autoYouTube={autoYouTube} />
      </div>

      <section className="panel ap-facts-panel" aria-label="Autopilot progress">
        <div className="facts ap-summary">
          <Fact label="Now" tone="neutral" icon="film" value={line} />
          <Fact label="Progress" tone="neutral" icon="refresh" value={progress} />
          <Fact label="Next" tone="neutral" icon="clock" value={next} />
          <Fact label="Posts" tone="neutral" icon="posts"
            value={lost ? "Unknown" : `${h.posts.ready ?? 0} ready · ${h.posts.scheduled
              ?? st.target.scheduled_posts} scheduled · ${h.posts.review} need your OK`} />
        </div>
        {on && h.discovery.problems.length > 0 && (
          <div className="note search-problems" role="status">
            <Icon name="alert" />
            <div className="stack">
              <span>Some online searches did not work last time. The others keep going, and what was already found
                is kept.</span>
              {h.discovery.problems.map((p, i) => (
                <span key={`${p.name}:${i}`} className="small"><b>{p.name}:</b> {p.detail} {p.fix}</span>
              ))}
            </div>
          </div>
        )}
        <Fact label="This PC" tone={t1} icon={i1} value={v1} desc={d1} />
        <p className="note pc-note"><Icon name="info" /><span>{h.pc_note}</span></p>
      </section>

      <section className="panel needs-you" aria-labelledby="ap-needs">
        <div className="panel-head">
          <h2 id="ap-needs">Needs you{!lost && h.needs_you.length ? ` (${h.needs_you.length})` : ""}</h2>
        </div>
        {lost ? <p className="muted">Unknown: ClipFoundry hasn't answered{since ? ` since ${since}` : ""}.</p>
          : <NeedsYouList items={h.needs_you} platforms={st.platforms} refresh={refresh} />}
      </section>

      <div className="cols-2">
        {/* align-content: start keeps the two parts together when the column next to it is taller */}
        <section className="panel" aria-labelledby="ap-now" style={{ alignContent: "start" }}>
          <h2 id="ap-now">Working on</h2>
          {lost ? <p className="muted">Unknown: ClipFoundry hasn't answered{since ? ` since ${since}` : ""}.</p>
            : <WorkingOn st={st} searchEvery={searchEvery} />}
          <hr className="divider" />
          <div className="stack my-videos">
            <h3>Your videos</h3>
            <p className="small muted">Put videos you made here. Autopilot turns them into clips by itself.</p>
            <div className="row wrap">
              <OpenVideosFolder onDone={refresh} />
              <span className="small row wrap">
                {plural(folder.videos, "video")}
                {folder.watching ? <Pill tone="good" icon="check">Watched</Pill>
                  : <Pill tone="warn" icon="alert">Not watched (turned off under Permissions & sources)</Pill>}
              </span>
            </div>
            <Disclosure plain summary="Show folder location">
              <code className="break my-videos-path">{folder.path}</code>
            </Disclosure>
          </div>
        </section>
        <section className="panel" aria-labelledby="ap-up">
          <div className="panel-head">
            <h2 id="ap-up">Coming up</h2>
            <a className="btn btn-quiet btn-small" href="#/posts/scheduled">All posts</a>
          </div>
          {h.upcoming.length ? (
            <>
              <div className="rows">{h.upcoming.map((u) => <UpcomingRow key={u.id} u={u} tz={st.timezone} />)}</div>
              <p className="tiny faint">{zoneLine(st.timezone)}</p>
            </>
          ) : <p className="muted small">No posts planned yet. Finished clips show up here with their posting time.</p>}
          <hr className="divider" />
          <h3>How posts go out</h3>
          <AutoPublishLine onChange={refresh} />
          <Accounts st={st} refresh={refresh} />
          <p className="tiny faint">Connecting an account never lets ClipFoundry post by itself. Automatic publishing is
            a separate permission that you turn on here, for YouTube only.</p>
        </section>
      </div>

      <p className="small muted">
        {h.skipped_today ? `${plural(h.skipped_today, "video")} skipped in the last 24 hours (not covered, no `
          + "allowed way to get the file, too short or a repeat). " : ""}
        <a className="textlink" href="#/autopilot/activity">See Activity</a> for what it did with each video it found.
      </p>

      <section className="panel tight" aria-labelledby="ap-stop">
        <h2 id="ap-stop" style={{ fontSize: "var(--fs-h3)" }}>Pause or stop everything</h2>
        <div className="estop">
          <div className="grow stack small muted">
            <span><b>Pause Autopilot</b> (at the top) stops new work: nothing new is found, clipped or posted, and
              what's queued waits. Posts already uploaded to YouTube with a publish time still go public then, because
              YouTube does that itself.</span>
            <span><b>Stop all jobs</b> is the emergency stop: queued work is canceled and running jobs stop at their
              next safe point, including videos and uploads you started yourself. Nothing starts again until you press
              Resume jobs.</span>
          </div>
          {st.paused ? <span className="small muted">Stopped. Use Resume jobs at the top.</span> : (
            <button type="button" className="btn btn-danger" disabled={lost} onClick={() => setStopping(true)}>
              <Icon name="stop" />Stop all jobs…</button>
          )}
        </div>
      </section>
      {stopping && (
        <ConfirmDialog title="Stop all jobs?" confirmLabel="Stop all jobs" danger cancelLabel="Keep running"
          onClose={() => setStopping(false)} onConfirm={async () => {
            const r = await ap.stopAll();
            toast(`All jobs stopped: ${plural(r.canceled, "queued job")} canceled, ${r.stopping + r.manual} stopping.`);
            refresh();
          }}>
          <p className="muted">This is the emergency stop. Queued work is canceled and running jobs stop at their next
            safe point. Nothing runs or posts until you press Resume jobs.</p>
          <p className="small">To only stop new work for a while, use <b>Pause Autopilot</b> instead: it keeps what's
            queued.</p>
        </ConfirmDialog>
      )}
    </>
  );
}

/** The steps a found video goes through, in the backend's own words for the running job (autopilot/home.py DOING). */
const FLOW: [string, string][] = [
  ["Getting a video ready", "Get the video"], ["Finding the best moments", "Find the best moments"],
  ["Writing titles and captions", "Write titles and captions"], ["Checking a finished clip", "Final check"],
  ["Publishing a post", "Post"],
];

/** What autopilot/home.py `currently` says when nothing is being worked on. */
const IDLE = ["Looking for opportunities", "Starting", "Waiting for the next search", "No usable video files yet",
  "No covered videos found yet", "Some searches did not work"];

function WorkingOn({ st, searchEvery }: { st: AutopilotStatus; searchEvery: string }) {
  const h = st.home;
  const w = h.working;
  const on = st.enabled && !st.paused;
  if (!on) return <p className="muted">Nothing: Autopilot is {st.paused ? "stopped" : "paused"}.</p>;
  if (!w) {
    // Nothing runs: the line at the top already says why (no usable files, nothing covered, a search that failed).
    const idle = IDLE.includes(h.currently);
    if (h.currently === "Waiting for the GPU") return <p><Pill tone="warn" icon="clock">Waiting for the GPU</Pill></p>;
    if (h.currently === "Background work has stopped") {
      return <p className="muted">Nothing: Autopilot's background work has stopped. See Needs you.</p>;
    }
    return idle
      ? <p className="muted">Nothing right now. It checks your videos folder {FOLDER_CHECK} and looks online
        {" "}{searchEvery}.</p>
      : <p className="small">Now: <b>{h.currently}</b></p>;
  }
  const step = FLOW.findIndex(([words]) => words === w.step);
  return (
    <div className="stack-3 working">
      <div className="row top wrap">
        <div style={{ width: 168, flex: "none" }}>
          <Thumb src={w.has_thumbnail && w.project_id ? projectThumbUrl({ id: w.project_id } as Project) : null} />
        </div>
        <div className="stack grow" style={{ flexBasis: 200 }}>
          {w.project_id ? <a className="post-title clamp-2" href={`#/project/${w.project_id}`}>{w.title}</a>
            : <b className="clamp-2">{w.title}</b>}
          <span className="small">Now: <b>{w.step}</b></span>
          {w.progress != null ? (
            <>
              <ProgressBar value={w.progress} label={`${w.step}: progress as the job reports it`} />
              <span className="tiny faint">{Math.round(w.progress * 100)}% of this step, as the job reports it. No time
                estimate is available.</span>
            </>
          ) : <span className="tiny faint">This step doesn't report progress.</span>}
        </div>
      </div>
      {step >= 0 && (
        <ol className="stages" aria-label="Steps for this video">
          {FLOW.map(([, label], i) => (
            <li key={label} className={i < step ? "done" : i === step ? "now" : ""}
              aria-current={i === step ? "step" : undefined}>
              <Icon name={i < step ? "check" : i === step ? "refresh" : "dot"} />{label}
              {i < step && <span className="sr-only"> (done)</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Which accounts Autopilot posts to, with the one action each needs (connect, reconnect, or use it). */
function Accounts({ st, refresh }: { st: AutopilotStatus; refresh: () => void }) {
  const use = async (p: Platform) => {
    try {
      await api.saveSettings({ [`autopilot_${p}`]: true });
      toast(`Autopilot now posts to ${PLATFORM_NAME[p]} too`);
    } catch (e) {
      toast(errorText(e), true);
    }
    refresh();
  };
  return (
    <div className="stack accounts-line" role="group" aria-label="Accounts">
      {PLATFORMS.map((p) => {
        const acc = st.platforms[p];
        const used = !!st.settings[`autopilot_${p}`];
        return (
          <div key={p} className="row wrap">
            <PlatformName platform={p} extra={acc.connected ? acc.name || acc.account_id : undefined} />
            {acc.connected && acc.needs_reconnect ? <>
              <Pill tone="bad" icon="alert">Sign-in expired</Pill>
              <ConnectAction platform={p} account={acc} reconnect onChange={refresh} />
            </> : acc.connected ? (used ? <Pill tone="good" icon="check">Connected, used by Autopilot</Pill> : <>
              <Pill tone="neutral" icon="info">Connected, not used by Autopilot</Pill>
              <button type="button" className="btn btn-small" onClick={() => use(p)}>Use it</button>
            </>) : <>
              <Pill tone="neutral" icon="link">Not connected</Pill>
              <ConnectAction platform={p} account={acc} onChange={() => (used ? refresh() : use(p))} />
            </>}
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ activity
const STAGE_LOOK = (stage: string): [Tone, IconName] => /made|done/i.test(stage) ? ["good", "check"]
  : /skipped|could not|no strong|not covered/i.test(stage) ? ["neutral", "x"] : ["info", "refresh"];

function ActivityView({ st, refresh }: { st: AutopilotStatus; refresh: () => void }) {
  const h = st.home;
  const { data, refresh: reload } = usePoll(() => ap.activity(), [], 10000, () => true);
  const [adding, setAdding] = useState<ActivityItem | null>(null);
  return (
    <>
      <section className="panel" aria-labelledby="found">
        <div className="panel-head">
          <h2 id="found">What Autopilot found</h2>
          <span className="tiny faint">Scores are ClipFoundry's estimates, not platform numbers.</span>
        </div>
        {h.opportunities.length ? (
          <div className="rows">
            {h.opportunities.map((o) => {
              const [tone, icon] = STAGE_LOOK(o.stage);
              return (
                <div key={o.id} className="row wrap opportunity" style={{ padding: "12px 0" }}>
                  <span className="score" title="How strong the opportunity looks: ClipFoundry's estimate">
                    <b>{o.score}</b>estimate</span>
                  <span className="grow stack" style={{ gap: 0, flexBasis: 220 }}>
                    {o.url ? <a className="post-title break" href={o.url} target="_blank" rel="noreferrer">{o.title}
                      <span className="sr-only"> (opens a new tab)</span></a> : <b className="break">{o.title}</b>}
                    <span className="tiny faint">
                      {[o.channel, o.kind === "live" ? "Live" : "", o.topic].filter(Boolean).join(" · ")}</span>
                  </span>
                  <Pill tone={tone} icon={icon}>{o.stage}</Pill>
                </div>
              );
            })}
          </div>
        ) : <p className="muted small">{h.empty || "Nothing it may use yet."}</p>}
      </section>

      <section className="panel activity-log" aria-labelledby="act">
        <div className="panel-head">
          <h2 id="act">Activity</h2>
          <span className="small muted">What it did with each video it found, newest first</span>
        </div>
        {h.skipped_today > 0 && (
          <p className="small">{plural(h.skipped_today, "video")} skipped in the last 24 hours (not covered, no
            allowed way to get the file, too short or a repeat). Autopilot keeps looking.</p>
        )}
        {data === null ? <Skel className="skel-block" /> : data.items.length ? (
          <div className="rows">
            {data.items.map((a) => (
              <div key={a.id} className={`row top wrap activity-row ${a.used ? "used" : "skipped"}`}
                style={{ padding: "12px 0" }}>
                {a.used ? <Pill tone={STAGE_LOOK(a.stage)[0]} icon={STAGE_LOOK(a.stage)[1]}>{a.stage}</Pill>
                  : <Pill tone="neutral" icon="x">Skipped</Pill>}
                <span className="grow stack" style={{ gap: 2, flexBasis: 240 }}>
                  {a.url ? <a className="post-title break" href={a.url} target="_blank" rel="noreferrer">{a.title}
                    <span className="sr-only"> (opens a new tab)</span></a> : <b className="break">{a.title}</b>}
                  <span className="tiny faint">{[a.channel, a.rights, a.access].filter(Boolean).join(" · ")}</span>
                  {!a.used && a.why && <span className="small">{a.why}</span>}
                </span>
                <span className="tiny faint nowrap">{a.at ? timeAgo(a.at) : ""}</span>
                {a.can_add_file && (
                  <button type="button" className="btn btn-small" onClick={() => setAdding(a)}>Add the file…</button>
                )}
              </div>
            ))}
          </div>
        ) : <p className="muted small">Nothing yet.</p>}
        <p className="small muted">Videos from creators you have an agreement with are used without asking. Record
          agreements under <a className="textlink" href="#/autopilot/sources">Permissions &amp; sources</a>.</p>
      </section>
      {adding && (
        <TextPromptDialog title="Add the video file" label="Full path of the video file on this computer"
          hint="For example C:\Users\you\Videos\talk.mp4" confirmLabel="Add file" onClose={() => setAdding(null)}
          onSubmit={async (path) => {
            await ap.attachFile(adding.id, path);
            toast("File added: Autopilot will clip it");
            reload();
            refresh();
          }}>
          <p className="small muted">“{adding.title}”. ClipFoundry does not download videos from YouTube or other
            platforms by itself (their terms). Choose the original file on this computer; for your own videos, YouTube
            Studio → Download gives you one.</p>
        </TextPromptDialog>
      )}
    </>
  );
}
