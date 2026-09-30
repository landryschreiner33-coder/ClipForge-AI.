import { ReactNode, useState } from "react";
import { Accounts, api, errorText, Platform, PlatformAccount, timeAgo } from "../api";
import {
  ActionItem, ActivityItem, Agreement, AgreementIn, ap, AutopilotStatus, Feed, ITEM_STATUS, Job, Metric, MyVideos,
  NeedsYouItem, ProviderStatus, RIGHTS_BADGE, RIGHTS_LABEL, RightsRule, Source, TrendSignal, WORKER_BADGE,
} from "../autopilot";
import { ConnectButton, PLATFORM_NAME, SetupAndConnect } from "../components/accounts";
import { AutoPublishLine } from "../components/autoPublish";
import { Icon, Modal, Segmented, toast, Toggle, usePoll } from "../components/ui";

/** The technical pages, for advanced users. Normal use needs none of them. */
const ADVANCED = [
  { value: "system", label: "System details" },
  { value: "sources", label: "Sources & rights" },
  { value: "jobs", label: "Jobs" },
  { value: "learning", label: "Learning" },
];
const OLD_SLUGS: Record<string, string> = { overview: "system" };
const PLATFORMS: Platform[] = ["youtube", "tiktok"];

/**
 * Autopilot. First time: connect YouTube, connect TikTok, choose topics, START AUTOPILOT. After that: a simple page with
 * START / PAUSE, what it is doing, today's clips, the next posts, the accounts and what needs you. Workers, sources,
 * rights rules, agreements, jobs and STOP ALL JOBS live under Advanced.
 */
export default function AutopilotPage({ tab: wanted }: { tab?: string }) {
  const slug = OLD_SLUGS[wanted || ""] || wanted || "";
  const advanced = ADVANCED.some((x) => x.value === slug) ? slug : "";
  const setTab = (v: string) => { window.location.hash = `#/autopilot/${v}`; };
  const { data: st, refresh, setData } = usePoll(() => ap.status(), [], 3000, () => true);
  const [adding, setAdding] = useState(false);

  const toggle = async (on: boolean) => {
    try {
      setData(await ap.enable(on));
      toast(on ? "Autopilot is on" : "Autopilot is paused: queued work waits");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const stopAll = async () => {
    if (!window.confirm("STOP ALL JOBS? Queued work is canceled and running jobs stop at their next safe point. Nothing starts again until you resume.")) return;
    try {
      const r = await ap.stopAll();
      toast(`Stopped: ${r.canceled} queued job(s) canceled, ${r.stopping + r.manual} stopping`);
      refresh();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const resume = async () => {
    await ap.resume();
    toast("Jobs allowed again");
    refresh();
  };

  if (!st) return <div className="page"><div className="spinner" /></div>;
  const firstRun = !advanced && !st.enabled && !st.home.setup.started;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Autopilot</h1>
          <p>{advanced ? "System details for advanced users. Normal use never needs these." : "Connect your accounts, turn it on, and ClipFoundry does the work."}</p>
        </div>
        <div className="row wrap">
          {!firstRun && !st.paused && (
            <>
              <span className={`badge ap-state ${st.enabled ? "good" : ""}`}>AUTOPILOT {st.enabled ? "ON" : "PAUSED"}</span>
              {st.enabled
                ? <button className="btn ap-toggle" aria-pressed="true" onClick={() => toggle(false)}><Icon name="stop" size={12} fill /> PAUSE AUTOPILOT</button>
                : <button className="btn primary ap-toggle" aria-pressed="false" onClick={() => toggle(true)}><Icon name="play" size={14} /> START AUTOPILOT</button>}
            </>
          )}
          {st.paused ? (
            <button className="btn primary" onClick={resume}><Icon name="play" size={14} /> Resume jobs</button>
          ) : advanced ? (
            <button className="btn stop" onClick={stopAll}><Icon name="stop" size={14} fill /> STOP ALL JOBS</button>
          ) : null}
        </div>
      </div>

      {st.paused && <div className="notice bad"><Icon name="x" size={16} /><div><b>All jobs are stopped.</b> Nothing runs or publishes until you press Resume jobs.</div></div>}
      {!st.enabled && !st.paused && !firstRun && <div className="notice"><Icon name="cpu" size={16} /><div>Autopilot is paused. Nothing new is found, clipped or posted until you press START AUTOPILOT; things you start by hand still run.</div></div>}

      {advanced ? (
        <>
          <a className="btn sm ghost adv-back" href="#/autopilot"><Icon name="back" size={14} /> Back to Autopilot</a>
          <div className="segmented" style={{ marginBottom: 18 }}>
            {ADVANCED.map((x) => <button key={x.value} className={advanced === x.value ? "on" : ""} onClick={() => setTab(x.value)}>{x.label}</button>)}
          </div>
          {advanced === "system" && <SystemDetails st={st} refresh={refresh} />}
          {advanced === "sources" && <SourcesTab />}
          {advanced === "jobs" && <JobsTab />}
          {advanced === "learning" && <LearningTab />}
        </>
      ) : firstRun ? (
        <Onboarding st={st} refresh={refresh} onStarted={setData} onAddContent={() => setAdding(true)} />
      ) : (
        <Home st={st} refresh={refresh} onAddContent={() => setAdding(true)} />
      )}
      {adding && <AddContentDialog onClose={() => setAdding(false)} onDone={refresh} />}
    </div>
  );
}

// ------------------------------------------------------------------ connecting an account
/** CONNECT: signs in right away when the platform is set up; otherwise asks for your app's two codes first. */
function ConnectAction({ platform, account, onChange, big }: { platform: Platform; account: PlatformAccount; onChange: (a?: Accounts) => void; big?: boolean }) {
  const [setup, setSetup] = useState(false);
  if (account.configured) return <ConnectButton platform={platform} account={account} onChange={onChange} big={big} />;
  return (
    <>
      <button className={`btn primary ${big ? "lg" : ""}`} onClick={() => setSetup(true)}><Icon name="link" size={16} /> CONNECT {PLATFORM_NAME[platform].toUpperCase()}</button>
      {setup && (
        <Modal onClose={() => setSetup(false)}>
          <div className="confirm" style={{ width: "min(620px, 94vw)" }}>
            <h3 style={{ marginTop: 0 }}>Connect {PLATFORM_NAME[platform]}</h3>
            <SetupAndConnect platform={platform} account={account} onChange={(a) => { setSetup(false); onChange(a); }} />
          </div>
        </Modal>
      )}
    </>
  );
}

const connectedOk = (a?: PlatformAccount) => !!a?.connected && !a.needs_reconnect;

// ------------------------------------------------------------------ first run
const TOPIC_CHOICES = ["podcasts", "interviews", "comedy", "sports", "gaming", "science", "business", "education", "news", "technology"];
const splitTopics = (t: string) => t.split(",").map((x) => x.trim()).filter(Boolean);

/** The one topic choice: a suggested list you can change by clicking or typing. */
function TopicChoice({ topics, setTopics }: { topics: string; setTopics: (t: string) => void }) {
  const list = splitTopics(topics);
  const has = (t: string) => list.some((x) => x.toLowerCase() === t);
  const flip = (t: string) => setTopics((has(t) ? list.filter((x) => x.toLowerCase() !== t) : [...list, t]).join(", "));
  return (
    <div className="topic-choice">
      <div className="row wrap">
        {TOPIC_CHOICES.map((t) => <button key={t} type="button" className={`chip ${has(t) ? "on" : ""}`} aria-pressed={has(t)} onClick={() => flip(t)}>{t}</button>)}
      </div>
      <input type="text" className="mt-s" aria-label="Topics" value={topics} onChange={(e) => setTopics(e.target.value)} placeholder="podcasts, interviews, comedy" />
    </div>
  );
}

function Onboarding({ st, refresh, onStarted, onAddContent }: { st: AutopilotStatus; refresh: () => void; onStarted: (s: AutopilotStatus) => void; onAddContent: () => void }) {
  const [busy, setBusy] = useState(false);
  const [topics, setTopics] = useState(st.home.setup.topics || "podcasts, interviews, comedy");
  const start = async () => {
    setBusy(true);
    try {
      onStarted(await ap.start(topics));
      toast("Autopilot is on");
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };
  const any = st.home.setup.connected.length > 0;
  const why: Record<Platform, string> = {
    youtube: "Posts your YouTube Shorts and looks for videos you may use.",
    tiktok: "Posts to TikTok. Optional: you can use one platform without the other.",
  };
  return (
    <div className="card onboard">
      <div className="kicker">CLIPFOUNDRY AUTOPILOT</div>
      <h2>A few steps. Then ClipFoundry does the work.</h2>
      <p className="muted">It makes short clips from videos you are allowed to use: videos you made (put them in your videos folder) and free-to-use videos it finds online. Videos from other people's channels are skipped. Then it writes titles and captions and picks posting times. YouTube can post by itself once you allow it; TikTok asks for your OK on each post (its rules).</p>
      <div className="ob-steps">
        {PLATFORMS.map((p, k) => (
          <div key={p} className="ob-step">
            <span className={`ob-n ${connectedOk(st.platforms[p]) ? "done" : ""}`}>{connectedOk(st.platforms[p]) ? <Icon name="check" size={16} /> : k + 1}</span>
            <div className="ob-body">
              <span className="small muted">Step {k + 1}</span>
              <b>Connect {PLATFORM_NAME[p]}</b>
              <div className="small muted">{connectedOk(st.platforms[p]) ? `Connected: ${st.platforms[p].name || st.platforms[p].account_id}` : why[p]}</div>
            </div>
            {connectedOk(st.platforms[p]) ? <span className="badge good">Connected</span> : <ConnectAction platform={p} account={st.platforms[p]} onChange={refresh} big />}
          </div>
        ))}
        <div className="ob-step ob-topics">
          <span className="ob-n">3</span>
          <div className="ob-body">
            <span className="small muted">Step 3</span>
            <b>Choose topics</b>
            <div className="small muted">What should it look for? A suggestion is filled in; change it if you like.</div>
            <TopicChoice topics={topics} setTopics={setTopics} />
          </div>
        </div>
        <div className="ob-step">
          <span className="ob-n">4</span>
          <div className="ob-body">
            <span className="small muted">Step 4</span>
            <b>Add your videos</b>
            <div className="small muted">Put videos you made in your videos folder. Autopilot turns them into clips by itself. You can add more any time.</div>
          </div>
          <MyVideosButton onDone={refresh} />
        </div>
        <div className="ob-step">
          <span className="ob-n">5</span>
          <div className="ob-body">
            <span className="small muted">Step 5</span>
            <b>Start Autopilot</b>
            <div className="small muted">{any
              ? "It uses the accounts you connected. To let YouTube posts go out without your review, turn on automatic publishing afterwards (it asks what you allow)."
              : "Connect YouTube or TikTok so Autopilot can post. You can also start now and connect later."}</div>
          </div>
          <button className="btn primary xl" disabled={busy || !splitTopics(topics).length} onClick={start}>START AUTOPILOT</button>
        </div>
      </div>
      <div className="row wrap mt">
        <button className="btn sm ghost" onClick={onAddContent}>+ Add content manually</button>
        <a className="btn sm ghost" href="#/autopilot/system">Advanced</a>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the simple page
/** "4:20 PM", "Tomorrow 9:05 AM" or "Fri 9:05 AM", in Autopilot's time zone. */
function postTime(ts: number | null, tz: string): string {
  if (!ts) return "Time not chosen yet";
  const zone = (() => {
    try {
      new Intl.DateTimeFormat([], { timeZone: tz });
      return tz;
    } catch {
      return undefined;
    }
  })();
  const d = new Date(ts * 1000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: zone });
  const day = (x: Date) => x.toLocaleDateString("en-CA", { timeZone: zone });
  if (day(d) === day(new Date())) return time;
  if (day(d) === day(new Date(Date.now() + 86_400_000))) return `Tomorrow ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short", timeZone: zone })} ${time}`;
}

function PlatformLine({ platform, st, refresh }: { platform: Platform; st: AutopilotStatus; refresh: () => void }) {
  const acc = st.platforms[platform];
  const used = !!st.settings[`autopilot_${platform}`];
  const use = async () => {
    try {
      await api.saveSettings({ [`autopilot_${platform}`]: true });
    } catch (e) {
      toast(errorText(e), true);
    }
    refresh();
  };
  let state: ReactNode;
  if (acc.connected && acc.needs_reconnect) state = <><span className="badge bad">Reconnect needed</span><ConnectButton platform={platform} account={acc} onChange={refresh} /></>;
  else if (acc.connected) state = used ? <span className="badge good">Connected</span>
    : <><span className="badge">Connected, not used</span><button className="btn sm" onClick={use}>Use it</button></>;
  else state = <><span className="badge">Not connected</span><ConnectAction platform={platform} account={acc} onChange={use} /></>;
  return <div className="home-platform"><b>{PLATFORM_NAME[platform]}</b>{state}</div>;
}

const STAGE_BADGE = (stage: string) => /needs/i.test(stage) ? "warn" : /made|done/i.test(stage) ? "good"
  : /next|up next|getting|finding/i.test(stage) ? "info" : /skipped|could not|no strong/i.test(stage) ? "" : "";

function Home({ st, refresh, onAddContent }: { st: AutopilotStatus; refresh: () => void; onAddContent: () => void }) {
  const h = st.home;
  const t = st.target;
  const on = st.enabled && !st.paused;
  return (
    <>
      <div className="card ap-home">
        <div className="home-grid">
          <div className="home-cell">
            <span className="home-k">Today</span>
            <div className="home-today"><b>{t.processed}</b> / {t.daily} <span>clips</span></div>
            <div className="small muted today-posts">
              Posted: {count(t.published, "clip")} · {count(t.published_posts, "platform post")}
            </div>
            <div className="small muted today-posts">
              Scheduled: {count(t.scheduled, "clip")} · {count(t.scheduled_posts, "platform post")}
            </div>
          </div>
          <div className="home-cell">
            <span className="home-k">Currently</span>
            <div className="home-now">{on && <span className="pulse" />}{h.currently}</div>
            {on && h.next_look && <div className="small muted next-look">Next look for new videos: {postTime(h.next_look, st.timezone)}</div>}
          </div>
          <div className="home-cell">
            <span className="home-k">Next post</span>
            <div className="home-now">{st.next ? postTime(st.next.planned_at, st.timezone) : "Nothing planned yet"}</div>
            {st.next && <div className="small muted">{PLATFORM_NAME[st.next.platform]} · “{st.next.title.length > 50 ? `${st.next.title.slice(0, 48).trim()}…` : st.next.title}”</div>}
          </div>
          <div className="home-cell">
            {PLATFORMS.map((p) => <PlatformLine key={p} platform={p} st={st} refresh={refresh} />)}
          </div>
        </div>
      </div>

      <NeedsYou items={h.needs_you} platforms={st.platforms} refresh={refresh} />

      <MyVideosCard folder={h.my_videos} refresh={refresh} />

      <div className="grid grid-2 mt">
        <div className="card">
          <h3>Top opportunities</h3>
          <div className="small muted home-estimate">Scores are ClipFoundry's estimates, not platform numbers.</div>
          {h.opportunities.length ? (
            <div className="trends">
              {h.opportunities.map((o) => (
                <div key={o.id} className="trend">
                  <span className={`score ${o.score >= 75 ? "hi" : o.score >= 50 ? "mid" : "lo"}`} title="How strong the opportunity looks (ClipFoundry's estimate)">{o.score}</span>
                  <div className="trend-body">
                    <a href={o.url || undefined} target="_blank" rel="noreferrer"><b>{o.title}</b></a>
                    <div className="small muted">{o.channel}{o.kind === "live" ? " · LIVE" : ""}{o.topic ? ` · ${o.topic}` : ""}</div>
                  </div>
                  <span className={`badge ${STAGE_BADGE(o.stage)}`}>{o.stage}</span>
                </div>
              ))}
            </div>
          ) : <p className="muted empty-msg">{h.empty}</p>}
        </div>
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Upcoming posts</h3><a className="btn sm" href="#/publish-center">Open Publish Center</a></div>
          <div className="upcoming mt-s">
            {h.upcoming.map((u) => {
              const [label, cls] = u.on_platform ? [`Uploaded: ${PLATFORM_NAME[u.platform]} posts it`, "good"]
                : u.auto && u.status === "approved" ? ["Approved automatically", "good"] : ITEM_STATUS[u.status] || [u.status, ""];
              return (
                <div key={u.id} className="up-row" data-auto={u.auto ? "1" : "0"}>
                  <span className="up-time">{postTime(u.planned_at, st.timezone)}</span>
                  <span className="badge">{PLATFORM_NAME[u.platform]}</span>
                  <span className="up-title">{u.title}</span>
                  <span className={`badge ${cls}`}>{label}</span>
                </div>
              );
            })}
            {!h.upcoming.length && <p className="muted">No posts planned yet. Finished clips show up here with their posting time.</p>}
          </div>
          <div className="home-publish mt">
            <span className="home-k">How posts go out</span>
            <AutoPublishLine onChange={refresh} />
          </div>
        </div>
      </div>

      <ActivityLog skipped={h.skipped_today} refresh={refresh} />

      <div className="notice small mt pc-note"><Icon name="cpu" size={14} /><div>{h.pc_note}</div></div>

      <div className="row wrap mt">
        <button className="btn" onClick={onAddContent}>+ Add content manually</button>
        <a className="btn ghost" href="#/autopilot/system"><Icon name="cpu" size={14} /> Advanced</a>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ your videos folder
/** OPEN MY VIDEOS FOLDER: creates the folder if needed and shows it in File Explorer. */
function MyVideosButton({ onDone, primary }: { onDone: () => void; primary?: boolean }) {
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      const f: MyVideos = await ap.openMyVideos();
      toast(f.opened ? "Your videos folder is open: put videos in it" : `Your videos folder: ${f.path}`);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
    onDone();
  };
  return <button className={`btn ${primary ? "primary" : ""}`} disabled={busy} onClick={open}><Icon name="projects" size={14} /> OPEN MY VIDEOS FOLDER</button>;
}

function MyVideosCard({ folder, refresh }: { folder: MyVideos; refresh: () => void }) {
  return (
    <div className="card mt my-videos">
      <div className="row between wrap">
        <div>
          <h3 style={{ margin: 0 }}>Your videos</h3>
          <div className="small muted">Put videos you made in this folder. Autopilot turns them into clips by itself.</div>
          <div className="small my-videos-path">{folder.path} · {count(folder.videos, "video")}{folder.watching ? "" : " · not watched (turned off under Advanced)"}</div>
        </div>
        <MyVideosButton onDone={refresh} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ the activity log (optional reading)
function ActivityLog({ skipped, refresh }: { skipped: number; refresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ActivityItem[] | null>(null);
  const load = async () => {
    try {
      setItems((await ap.activity()).items);
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const show = () => {
    setOpen(!open);
    if (!open) load();
  };
  const addFile = async (a: ActivityItem) => {
    const path = window.prompt("Full path of the video file on this computer (for example C:\\Users\\you\\Videos\\talk.mp4):");
    if (!path) return;
    try {
      await ap.attachFile(a.id, path.trim().replace(/^"|"$/g, ""));
      toast("File added: Autopilot will clip it");
      load();
      refresh();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (
    <div className="card mt activity-log">
      <div className="row between wrap">
        <div>
          <h3 style={{ margin: 0 }}>Activity</h3>
          <div className="small muted">{skipped
            ? `${skipped} video${skipped !== 1 ? "s" : ""} skipped in the last 24 hours (not covered, no allowed way to get the file, too short or a repeat). Autopilot keeps looking.`
            : "What Autopilot did with the videos it found, and why it skipped any."}</div>
        </div>
        <button className="btn sm" aria-expanded={open} onClick={show}>{open ? "Hide activity" : "Show activity"}</button>
      </div>
      {open && (
        <div className="activity mt">
          {items === null && <div className="spinner" />}
          {items?.map((a) => (
            <div key={a.id} className={`activity-row ${a.used ? "used" : "skipped"}`}>
              <span className={`badge ${a.used ? "good" : ""}`}>{a.used ? a.stage : "Skipped"}</span>
              <div className="activity-body">
                <a href={a.url || undefined} target="_blank" rel="noreferrer"><b>{a.title}</b></a>
                <div className="small muted">{[a.channel, a.rights, a.access].filter(Boolean).join(" · ")}</div>
                {!a.used && <div className="small">{a.why}</div>}
              </div>
              <span className="small muted">{timeAgo(a.at)}</span>
              {a.can_add_file && <button className="btn sm" onClick={() => addFile(a)}>Add the file</button>}
            </div>
          ))}
          {items && !items.length && <div className="muted small">Nothing yet.</div>}
          <div className="small muted mt-s">Videos from creators you have an agreement with are used without asking: record agreements under <a href="#/autopilot/sources">Advanced → Sources & rights</a>.</div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ needs you
function NeedsYou({ items, platforms, refresh }: { items: NeedsYouItem[]; platforms: AutopilotStatus["platforms"]; refresh: () => void }) {
  return (
    <div className="card mt needs-you">
      <h3>Needs you {items.length > 0 && <span className="badge warn">{items.length}</span>}</h3>
      {items.length ? <div className="actions">{items.map((i) => <NeedsYouRow key={i.key} item={i} platforms={platforms} refresh={refresh} />)}</div>
        : <div className="muted">Nothing right now. ClipFoundry asks here only when it really needs you.</div>}
    </div>
  );
}

function NeedsYouRow({ item, platforms, refresh }: { item: NeedsYouItem; platforms: AutopilotStatus["platforms"]; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast(msg);
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
    refresh();
  };
  const src = item.source;
  const view = src?.url ? <a className="btn sm ghost" href={src.url} target="_blank" rel="noreferrer">VIEW SOURCE</a> : null;
  const dismiss = <button className="btn sm ghost" disabled={busy} onClick={() => act(() => ap.dismiss(item.key), "Hidden for now")}>Not now</button>;
  let buttons: ReactNode;
  if (item.type === "rights" && src) {
    buttons = (
      <>
        <button className="btn sm primary" disabled={busy} onClick={() => act(() => ap.permission(src.id, true), "Thanks: Autopilot will use it")}>YES, I HAVE PERMISSION</button>
        <button className="btn sm" disabled={busy} onClick={() => act(() => ap.permission(src.id, false), "Got it: it will not be used")}>NO</button>
        {view}
      </>
    );
  } else if (item.type === "file" && src) {
    buttons = (
      <>
        <button className="btn sm primary" disabled={busy} onClick={() => {
          const path = window.prompt("Full path of the video file on this computer (for example C:\\Users\\you\\Videos\\talk.mp4):");
          if (path) act(() => ap.attachFile(src.id, path.trim().replace(/^"|"$/g, "")), "File added: Autopilot will clip it");
        }}>ADD THE VIDEO FILE</button>
        <button className="btn sm" disabled={busy} onClick={() => act(() => ap.skipSource(src.id), "Skipped")}>SKIP THIS VIDEO</button>
        {view}
      </>
    );
  } else if (item.type === "videos") {
    buttons = <MyVideosButton onDone={refresh} primary />;
  } else if (item.type === "account" && item.platform) {
    const again = item.title.startsWith("Reconnect");
    buttons = <ConnectAction platform={item.platform} account={{ ...platforms[item.platform], connected: false, needs_reconnect: again }} onChange={refresh} />;
  } else {
    buttons = <>{item.link && <a className="btn sm" href={item.link}>{item.type === "approve" ? "REVIEW POSTS" : "OPEN"}</a>}{dismiss}</>;
  }
  return (
    <div className={`action ${item.type === "gpu" || item.type === "account" ? "error" : "action"}`} data-type={item.type}>
      <div>
        <b>{item.title}</b>
        {src && item.type === "rights" && <div className="needs-src">“{src.title}”{src.channel ? <span className="muted"> · {src.channel}</span> : null}</div>}
        {item.question && <div className="needs-q">{item.question}</div>}
        {item.detail && <div className="small">{item.detail}</div>}
        {item.fix && <div className="small muted">What to do: {item.fix}</div>}
      </div>
      <div className="row wrap needs-buttons">{buttons}</div>
    </div>
  );
}

// ------------------------------------------------------------------ adding content by hand (optional)
const CAN_USE = [
  { value: "OWNED", label: "Yes, it's my own content" },
  { value: "ALLOWLISTED", label: "Yes, I have permission from the creator" },
  { value: "", label: "Not sure: ask me later" },
];

function AddContentDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [mode, setMode] = useState("link");
  const [where, setWhere] = useState("");
  const [title, setTitle] = useState("");
  const [canUse, setCanUse] = useState<string | null>(null);
  const basis = canUse === "OWNED" ? "My own content (added by hand)" : "You said you have permission from the creator (added by hand)";
  const save = async () => {
    if (mode === "upload") {
      window.location.hash = "#/create";
      return;
    }
    if (!where.trim()) throw new Error(mode === "link" ? "Paste the link first" : mode === "folder" ? "Enter the folder first" : "Enter the file's path first");
    if (canUse === null) throw new Error("Say whether ClipFoundry may use it");
    const path = where.trim().replace(/^"|"$/g, "");
    if (mode === "folder") {
      await ap.addFeed({ kind: "watch_folder", name: title || "My videos", config: { path }, rights_status: canUse, rights_basis: canUse ? basis : "" });
    } else {
      await ap.addSource({ [mode === "link" ? "url" : "path"]: path, title, rights_status: canUse, basis: canUse ? basis : "" });
    }
    toast(canUse ? "Added: Autopilot will pick it up" : "Added: Autopilot will ask you before using it");
    onDone();
  };
  return (
    <Dialog title="Add content manually" label={mode === "upload" ? "Open Create" : "Add"} onClose={onClose} onSave={save}>
      <p className="small muted">Optional: Autopilot finds content by itself. Use this for your own videos or links you may use.</p>
      <Segmented value={mode} onChange={setMode} options={[
        { value: "link", label: "Paste a link" }, { value: "file", label: "A video on this computer" },
        { value: "folder", label: "Watch a folder" }, { value: "upload", label: "Upload a video" },
      ]} />
      {mode === "upload" ? (
        <p className="small mt">Upload a video on the Create page and make clips from it yourself.</p>
      ) : (
        <>
          <label className="field mt">{mode === "link" ? "Link to the video" : mode === "folder" ? "Folder on this computer (new videos in it are clipped)" : "Full path of the video file"}
            <input type="text" value={where} onChange={(e) => setWhere(e.target.value)} placeholder={mode === "link" ? "https://..." : mode === "folder" ? "C:\\Users\\you\\Videos\\Recordings" : "C:\\Users\\you\\Videos\\talk.mp4"} />
          </label>
          <label className="field mt-s">Name <span className="small muted">optional</span><input type="text" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <div className="radio-block mt">Can ClipFoundry use it?
            <div className="radio-list">
              {CAN_USE.map((c) => (
                <label key={c.value} className="row small"><input type="radio" name="canuse" checked={canUse === c.value} onChange={() => setCanUse(c.value)} /> {c.label}</label>
              ))}
            </div>
          </div>
        </>
      )}
    </Dialog>
  );
}

// ------------------------------------------------------------------ advanced: system details
function SystemDetails({ st, refresh }: { st: AutopilotStatus; refresh: () => void }) {
  const t = st.target;
  const pct = Math.min(100, (100 * t.published) / Math.max(1, t.daily));
  const nxt = st.next;
  return (
    <>
      <div className="card target">
        <div className="row between wrap">
          <div>
            <div className="target-big"><b>{t.published}</b> / {t.daily} <span>DAILY TARGET</span></div>
            <div className="small muted">Unique clips posted today. {t.note}</div>
            <div className="small muted platform-posts">
              Platform posts today: {t.published_posts} published, {t.scheduled_posts} scheduled ({perPlatform(t)})
            </div>
          </div>
          <div className="grid grid-4 target-stats">
            <Stat n={`${st.sources_today.counted} / ${st.sources_per_day}`} label="Sources today" />
            <Stat n={t.processed} label="Clips processed" />
            <Stat n={`${t.scheduled} · ${t.scheduled_posts}`} label="Scheduled today: clips · platform posts" />
            <Stat n={st.queue.size} label="Jobs in queue" />
          </div>
        </div>
        <div className="bar mt"><div style={{ width: `${pct}%` }} /></div>
        <div className="row between wrap mt-s small">
          <span>{nxt ? <>Next: <b>{nxt.local}</b> · {nxt.platform === "youtube" ? "YouTube" : "TikTok"} · “{nxt.title.slice(0, 60)}” <span className="badge">{nxt.status.replace("_", " ")}</span></> : <span className="muted">Nothing scheduled yet</span>}</span>
          <a className="btn sm" href="#/publish-center">Open Publish Center</a>
        </div>
      </div>

      {st.actions.length > 0 && (
        <div className="card">
          <h3>All action items ({st.actions.length})</h3>
          <div className="actions">{st.actions.map((a) => <ActionRow key={a.id} a={a} onDone={refresh} />)}</div>
        </div>
      )}

      <div className="grid grid-2 mt">
        <div className="card">
          <h3>Workers <span className="small muted" style={{ fontWeight: 400 }}>{st.workers.host.alive ? `running (${st.workers.host.mode === "separate" ? "own process" : "in the app"})` : "not running"}</span></h3>
          <div className="workers">
            {st.workers.workers.map((w) => {
              const [label, cls] = WORKER_BADGE[w.status] || [w.status, ""];
              const queued = (w.queue.queued || 0) + (w.queue.retrying || 0) + (w.queue.waiting || 0);
              return (
                <div key={w.name} className="worker">
                  <span className={`badge ${cls}`}><span className="dot" /> {label}</span>
                  <b>{w.label}</b>
                  <span className="small muted wmsg" title={w.last_error || w.message}>{w.stage ? `${w.stage} · ` : ""}{w.message}</span>
                  {queued > 0 && <span className="small muted">{queued} queued</span>}
                </div>
              );
            })}
          </div>
        </div>
        <GpuCard st={st} />
      </div>

      <div className="grid grid-2 mt">
        <PlatformsCard st={st} />
        <QuotaCard st={st} />
      </div>

      <div className="grid grid-2 mt">
        <div className="card">
          <h3>Rights of known sources</h3>
          <div className="row wrap">
            {Object.entries(st.rights).map(([k, n]) => <span key={k} className={`badge ${RIGHTS_BADGE[k] || ""}`}>{RIGHTS_LABEL[k] || k}: {n}</span>)}
            {!Object.keys(st.rights).length && <span className="muted small">No sources yet.</span>}
          </div>
          <p className="small muted">Discovery is not authorization: only Owned, Licensed and Allowlisted sources (and Creative Commons if you allow it) are clipped automatically. Everything else waits for your decision.</p>
        </div>
        <div className="card">
          <h3>Recent activity</h3>
          <div className="events">
            {st.events.slice(0, 12).map((e) => (
              <div key={e.id} className={`event ${e.level}`}><span className="muted">{timeAgo(e.at)}</span> {e.message}</div>
            ))}
            {!st.events.length && <span className="muted small">Nothing yet.</span>}
          </div>
        </div>
      </div>

      <TrendsCard trends={st.trends} providers={st.providers} />
    </>
  );
}

/** "1 clip", "2 platform posts" */
const count = (n: number, what: string) => `${n} ${what}${n === 1 ? "" : "s"}`;

/** "YouTube 1 published, 0 scheduled; TikTok 0 published, 1 scheduled" */
function perPlatform(t: AutopilotStatus["target"]) {
  return PLATFORMS.map((p) => {
    const c = t.posts_by_platform?.[p];
    return `${PLATFORM_NAME[p]} ${c?.published ?? 0} published, ${c?.scheduled ?? 0} scheduled`;
  }).join("; ");
}

function Stat({ n, label }: { n: ReactNode; label: string }) {
  return <div className="stat"><b>{n}</b><span>{label}</span></div>;
}

function ActionRow({ a, onDone }: { a: ActionItem; onDone: () => void }) {
  const link = ({
    approve: "#/publish-center", publish: "#/publish-center/problems", rights: "#/autopilot/sources", source_file: "#/autopilot/sources",
    youtube: "#/settings", quota: "#/settings", gpu: "#/settings", workers: "#/autopilot/jobs",
  } as Record<string, string>)[a.kind] || "";
  return (
    <div className={`action ${a.level}`}>
      <div>
        <b>{a.title}</b>
        {a.detail && <div className="small">{a.detail}</div>}
        {a.fix && <div className="small muted">What to do: {a.fix}</div>}
      </div>
      <div className="row">
        {link && <a className="btn sm" href={link}>Open</a>}
        <button className="btn sm ghost" onClick={async () => { await ap.dismiss(a.key); onDone(); }}>Dismiss</button>
      </div>
    </div>
  );
}

function GpuCard({ st }: { st: AutopilotStatus }) {
  const g = st.gpu;
  const mem = g.memory;
  const last = g.last_transcription;
  const fell = last && last.requested_device === "cuda" && last.device !== "cuda";
  return (
    <div className="card">
      <h3>GPU <span className="small muted" style={{ fontWeight: 400 }}>one heavy GPU job at a time</span></h3>
      <div className="sys-list">
        <div className="sys-item"><span className="k">Device</span><span>{g.available ? <span className="badge good">{g.name || "NVIDIA GPU"}</span> : <span className="badge warn">No CUDA GPU detected</span>}</span></div>
        <div className="sys-item"><span className="k">Transcription</span><span>{g.mode === "gpu" ? `GPU · ${g.whisper.model} · ${g.whisper.compute_type}` : `CPU · ${g.whisper.reason}`}</span></div>
        {mem && (
          <div>
            <div className="sys-item"><span className="k">Memory</span><span>{(mem.used_mb / 1024).toFixed(1)} / {(mem.total_mb / 1024).toFixed(1)} GB used · {mem.utilization}% busy</span></div>
            <div className="bar mt-s"><div style={{ width: `${(100 * mem.used_mb) / Math.max(1, mem.total_mb)}%` }} /></div>
          </div>
        )}
        <div className="sys-item"><span className="k">Now</span><span>{g.holder ? <><span className="badge warn">{g.holder.kind}</span> {g.holder.label.slice(0, 40)}</> : <span className="muted">free</span>}</span></div>
        {g.waiting.length > 0 && <div className="sys-item"><span className="k">Waiting</span><span>{g.waiting.map((w) => w.kind).join(", ")}</span></div>}
        {last && (
          <div className="sys-item"><span className="k">Last transcription</span>
            <span>{fell ? <span className="badge bad">fell back to CPU</span> : <span className="badge good">{last.device.toUpperCase()}</span>} {last.speed ? `${last.speed}x realtime` : ""}</span>
          </div>
        )}
        {(g.problem || fell) && <div className="notice warn small block">{fell ? last?.warning : g.problem} {g.fix || last?.fix ? <b>Fix: {g.fix || last?.fix}</b> : null}</div>}
      </div>
    </div>
  );
}

function PlatformsCard({ st }: { st: AutopilotStatus }) {
  const s = st.settings;
  const row = (name: string, acc: AutopilotStatus["platforms"]["youtube"], enabled: boolean) => (
    <div className="platform-row">
      <div className="row between">
        <b>{name}</b>
        <span className="row">
          {!enabled && <span className="badge">not used by Autopilot</span>}
          {acc.connected ? <span className={`badge ${acc.needs_reconnect ? "bad" : "good"}`}>{acc.needs_reconnect ? "reconnect needed" : `connected: ${acc.name}`}</span>
            : <span className="badge warn">{acc.configured ? "not connected" : "not set up"}</span>}
        </span>
      </div>
      {acc.restriction && <div className="small muted">{acc.restriction}</div>}
    </div>
  );
  return (
    <div className="card">
      <h3>Platforms</h3>
      {row("YouTube Shorts", st.platforms.youtube, !!s.autopilot_youtube)}
      {row("TikTok", st.platforms.tiktok, !!s.autopilot_tiktok)}
      <div className="small muted mt-s">Every post needs your approval in the Publish Center (the platforms' rules). {s.autopilot_auto_publish ? "Approved posts are published at their time automatically." : "Automatic publishing is off: approved posts wait for Publish now."}</div>
      <a className="btn sm mt-s" href="#/settings">Connect accounts</a>
    </div>
  );
}

function QuotaCard({ st }: { st: AutopilotStatus }) {
  const q = st.quota;
  return (
    <div className="card">
      <h3>YouTube API quota <span className="small muted" style={{ fontWeight: 400 }}>resets {new Date(q.resets_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></h3>
      {Object.entries(q.buckets).map(([k, b]) => (
        <div key={k} className="quota">
          <div className="row between small"><span>{b.label}</span><span>{b.used} / {b.budget}{b.exhausted ? " · used up" : ""} · projected {b.projected}</span></div>
          <div className={`bar ${b.exhausted ? "bad" : ""}`}><div style={{ width: `${Math.min(100, (100 * b.used) / Math.max(1, b.budget))}%` }} /></div>
        </div>
      ))}
      {q.warnings.map((w, i) => <div key={i} className="notice warn small block mt-s">{w}</div>)}
      <div className="small muted mt-s">Counted by ClipFoundry. Discovery uses only its share and never the quota kept for publishing and statistics.</div>
    </div>
  );
}

const PROV: Record<string, string> = { ok: "good", unavailable: "", not_configured: "warn", error: "bad", quota: "warn" };

function MetricCell({ m, label }: { m?: Metric; label: string }) {
  if (!m) return null;
  const v = m.value;
  const text = v == null ? "—" : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(v);
  return <span className={`metric ${m.status}`} title={`${label}: ${m.status}${m.note ? ` (${m.note})` : ""}`}>{text} <small>{label}</small></span>;
}

export function TrendsCard({ trends, providers }: { trends: TrendSignal[]; providers: Record<string, ProviderStatus> }) {
  return (
    <div className="card mt">
      <div className="row between wrap">
        <h3 style={{ margin: 0 }}>Trend opportunities</h3>
        <button className="btn sm" onClick={async () => { await ap.scan(); toast("Trend scan started"); }}><Icon name="refresh" size={13} /> Scan now</button>
      </div>
      <div className="row wrap mt-s" style={{ gap: 6 }}>
        {Object.entries(providers).map(([k, p]) => (
          <span key={k} className={`badge ${PROV[p.status] || ""}`} title={`${p.detail}${p.fix ? ` · ${p.fix}` : ""}`}>{p.name}: {p.status.replace("_", " ")}</span>
        ))}
      </div>
      <div className="trends mt">
        {trends.map((s) => (
          <div key={s.id} className="trend">
            <span className={`score ${(s.score ?? 0) >= 75 ? "hi" : (s.score ?? 0) >= 50 ? "mid" : "lo"}`} title={s.notes.join(" ")}>{Math.round(s.score ?? 0)}</span>
            <div className="trend-body">
              <a href={s.url} target="_blank" rel="noreferrer"><b>{s.title}</b></a>
              <div className="small muted">{s.channel_title} · {s.kind === "live" ? "LIVE · " : ""}{s.topic || s.category}{s.score_mode === "platform_order" ? " · YouTube's order" : ""}</div>
            </div>
            <div className="row wrap metrics">
              <MetricCell m={s.metrics.views} label="views" />
              <MetricCell m={s.metrics.live_viewers?.value != null ? s.metrics.live_viewers : undefined} label="watching" />
              <MetricCell m={s.metrics.likes} label="likes" />
            </div>
          </div>
        ))}
        {!trends.length && <div className="muted small">Nothing found yet. Connect YouTube (Settings → General → Accounts) or add a YouTube API key (Settings → Advanced → Discovery).</div>}
      </div>
      <div className="small muted mt-s">Observed = as the platform reported it · estimated = calculated by ClipFoundry · — = not reported. Scores are ClipFoundry's own, not platform metrics.</div>
    </div>
  );
}

// ------------------------------------------------------------------ sources & rights
const STATUSES = ["OWNED", "LICENSED", "ALLOWLISTED", "CREATIVE_COMMONS", "BLOCKED"];
const SOURCE_FILTERS = ["", "eligible", "needs_rights", "needs_file", "queued", "ingesting", "analyzing", "analyzed", "weak", "failed", "skipped", "blocked"];

function SourcesTab() {
  const [filter, setFilter] = useState("");
  const { data: sources, refresh } = usePoll(() => ap.sources(filter), [filter], 5000, () => true);
  const { data: rights, refresh: refreshRights } = usePoll(() => ap.rights(), [], 30000, () => false);
  const { data: feeds, refresh: refreshFeeds } = usePoll(() => ap.feeds(), [], 15000, () => true);
  const { data: agreements, refresh: refreshAgreements } = usePoll(() => ap.agreements(), [], 30000, () => false);
  const [confirming, setConfirming] = useState<Source | null>(null);
  const [adding, setAdding] = useState<"" | "feed" | "rule" | "source" | "agreement">("");
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      toast(msg);
      refresh();
      refreshRights();
      refreshFeeds();
      refreshAgreements();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (
    <>
      <div className="card agreements">
        <div className="row between"><h3 style={{ margin: 0 }}>Creator agreements</h3><button className="btn sm primary" onClick={() => setAdding("agreement")}>+ Record an agreement</button></div>
        <p className="small muted">A creator who allows you to clip their videos (an agreement, or a clipping program you joined): record it once, with what shows it and its conditions, and every video it covers is used without asking. It covers the creator's own material only, unless you say it also covers other people's music or footage.</p>
        {(agreements || []).map((a: Agreement) => (
          <div key={a.id} className="feed">
            <div>
              <b>{a.creator}</b> <span className="small muted">{[...a.channels, a.conditions.media_folder && "shared folder", a.conditions.media_url_prefix && "file link"].filter(Boolean).join(" · ")}</span>
              <div className="small muted">
                {a.conditions.commercial ? "Commercial use allowed" : "No commercial use"}
                {a.conditions.platforms?.length ? ` · only on ${a.conditions.platforms.map((p) => PLATFORM_NAME[p as Platform] || p).join(", ")}` : ""}
                {a.conditions.attribution ? ` · credit: “${a.conditions.attribution}”` : ""}
                {a.conditions.third_party ? " · also covers other people's material" : ""}
                {a.expires_at ? ` · ends ${new Date(a.expires_at * 1000 - 1000).toLocaleDateString()}` : ""}
              </div>
              <div className="small muted">Evidence: {a.evidence || a.evidence_url}</div>
            </div>
            <button className="btn sm ghost danger" onClick={() => window.confirm("Remove this agreement? Videos it covers are no longer used automatically.") && act(() => ap.removeAgreement(a.id), "Agreement removed")}><Icon name="trash" size={12} /></button>
          </div>
        ))}
        {!agreements?.length && <div className="small muted">None yet. Without agreements, Autopilot uses your own videos and videos with a free license (public domain, CC0, CC BY).</div>}
      </div>

      <div className="grid grid-2 mt">
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Where sources come from</h3><button className="btn sm" onClick={() => setAdding("feed")}>+ Add</button></div>
          <p className="small muted">Watch folders (your recordings; a file that is still growing is a live recording), YouTube channels you follow, stream URLs you may use, and signal feeds you are authorized to use.</p>
          {(feeds || []).map((f: Feed) => (
            <div key={f.id} className="feed">
              <div><b>{f.name}</b> <span className="small muted">{f.kind.replace("_", " ")} · {f.config.path || f.config.url || f.config.channel_id}</span>
                {f.last_error && <div className="small bad-text">{f.last_error}</div>}</div>
              <div className="row">
                <Toggle on={!!f.enabled} onChange={(v) => act(() => ap.setFeed(f.id, v), v ? "Enabled" : "Disabled")} />
                <button className="btn sm ghost danger" onClick={() => window.confirm("Remove this feed?") && act(() => ap.deleteFeed(f.id), "Removed")}><Icon name="trash" size={12} /></button>
              </div>
            </div>
          ))}
          {!feeds?.length && <div className="small muted">None yet.</div>}
        </div>
        <div className="card">
          <div className="row between"><h3 style={{ margin: 0 }}>Rights rules</h3><button className="btn sm" onClick={() => setAdding("rule")}>+ Add rule</button></div>
          <p className="small muted">Record what you may use, and why: a channel whose clipping program you joined, a folder of your own recordings, a licensed feed. Blocked always wins.</p>
          {(rights?.rules || []).map((r: RightsRule) => (
            <div key={r.id} className="feed">
              <div><span className={`badge ${RIGHTS_BADGE[r.status]}`}>{RIGHTS_LABEL[r.status]}</span> <b>{r.label || r.value}</b> <span className="small muted">{r.scope.replace("_", " ")}</span>
                <div className="small muted">{r.basis}</div></div>
              <button className="btn sm ghost danger" onClick={() => window.confirm("Remove this rule?") && act(() => ap.deleteRule(r.id), "Rule removed")}><Icon name="trash" size={12} /></button>
            </div>
          ))}
          {!rights?.rules.length && <div className="small muted">No rules yet: videos nothing covers are skipped.</div>}
        </div>
      </div>

      <div className="card mt">
        <div className="row between wrap">
          <h3 style={{ margin: 0 }}>Sources</h3>
          <div className="row">
            <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 180 }}>
              {SOURCE_FILTERS.map((f) => <option key={f} value={f}>{f ? f.replace("_", " ") : "All sources"}</option>)}
            </select>
            <button className="btn sm" onClick={() => setAdding("source")}>+ Add a source</button>
          </div>
        </div>
        <div className="sources mt">
          {(sources || []).map((s) => (
            <div key={s.id} className="source">
              <div className="source-main">
                <div className="row wrap" style={{ gap: 6 }}>
                  <span className={`badge ${RIGHTS_BADGE[s.rights_status] || ""}`} title={s.rights_explain}>{s.rights_label}</span>
                  <span className="badge">{s.status.replace("_", " ")}</span>
                  {s.kind === "live" && <span className="badge bad">LIVE</span>}
                  <span className="small muted">{s.platform}{s.channel_title ? ` · ${s.channel_title}` : ""}</span>
                </div>
                <a href={s.url || undefined} target="_blank" rel="noreferrer"><b>{s.title || s.external_id}</b></a>
                <div className="small muted">{s.rights_basis}{s.status_note ? ` · ${s.status_note}` : ""}</div>
              </div>
              <div className="source-scores small" title={Object.entries(s.components || {}).map(([k, c]) => `${k}: ${c.note || c.value}`).join("\n")}>
                <div>Source Score <b>{s.source_score != null ? Math.round(s.source_score) : "—"}</b></div>
                <div className="muted">≈ {s.expected_clips ?? "?"} strong clips</div>
                {s.clips_selected > 0 && <div className="muted">{s.clips_selected} clip(s) made</div>}
              </div>
              <div className="row wrap source-actions">
                <button className="btn sm" onClick={() => setConfirming(s)}>Rights</button>
                {s.status === "needs_file" && <button className="btn sm" onClick={() => {
                  const path = window.prompt("Full path of the video file on this computer:");
                  if (path) act(() => ap.attachFile(s.id, path), "File added");
                }}>Add file</button>}
                {["eligible", "weak", "failed", "skipped"].includes(s.status) && <button className="btn sm" onClick={() => act(() => ap.huntSource(s.id), "Sent to the Clip Hunter")}>Clip now</button>}
                {s.project_id && <a className="btn sm ghost" href={`#/project/${s.project_id}`}>Clips</a>}
                {!["ingesting", "analyzing", "skipped"].includes(s.status) && <button className="btn sm ghost" onClick={() => act(() => ap.skipSource(s.id), "Skipped")}>Skip</button>}
              </div>
            </div>
          ))}
          {!sources?.length && <div className="small muted">No sources{filter ? " with this status" : " yet"}.</div>}
        </div>
      </div>
      {confirming && <RightsDialog source={confirming} onClose={() => setConfirming(null)} onDone={() => { refresh(); refreshRights(); }} />}
      {adding === "feed" && <AddFeedDialog onClose={() => setAdding("")} onDone={() => { refreshFeeds(); refreshRights(); }} />}
      {adding === "rule" && <AddRuleDialog onClose={() => setAdding("")} onDone={refreshRights} />}
      {adding === "source" && <AddSourceDialog onClose={() => setAdding("")} onDone={refresh} />}
      {adding === "agreement" && <AgreementDialog onClose={() => setAdding("")} onDone={() => { refreshAgreements(); refreshRights(); refreshFeeds(); refresh(); }} />}
    </>
  );
}

function AgreementDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [a, setA] = useState<AgreementIn>({
    creator: "", channels: [], evidence: "", evidence_url: "", attribution: "", commercial: true, platforms: ["youtube", "tiktok"],
    third_party: false, expires: "", media_folder: "", media_url_prefix: "",
  });
  const [channels, setChannels] = useState("");
  const set = (p: Partial<AgreementIn>) => setA({ ...a, ...p });
  const plat = (p: string, on: boolean) => set({ platforms: on ? [...a.platforms.filter((x) => x !== p), p] : a.platforms.filter((x) => x !== p) });
  return (
    <Dialog title="Record an agreement with a creator" label="Save agreement" onClose={onClose} onSave={async () => {
      if (!a.platforms.length) throw new Error("Choose at least one platform it allows");
      await ap.addAgreement({ ...a, channels: channels.split(/[\s,]+/).filter(Boolean) });
      toast("Agreement saved: videos it covers are used without asking");
      onDone();
    }}>
      <label className="field">Creator<input type="text" value={a.creator} onChange={(e) => set({ creator: e.target.value })} placeholder="Their name or channel name" /></label>
      <label className="field mt-s">YouTube channel IDs and TikTok handles <span className="small muted">UC... or @name, separated by commas</span>
        <input type="text" value={channels} onChange={(e) => setChannels(e.target.value)} placeholder="UCxxxxxxxxxxxxxxxxxxxxxx, @theirname" /></label>
      <label className="field mt-s">What shows the agreement <span className="small muted">required: where and when they agreed, or the program's terms</span>
        <textarea rows={2} value={a.evidence} onChange={(e) => set({ evidence: e.target.value })} placeholder="Email from them on 2026-09-01: “You may clip and post my podcast episodes”" /></label>
      <label className="field mt-s">Link to it <span className="small muted">optional</span><input type="text" value={a.evidence_url} onChange={(e) => set({ evidence_url: e.target.value })} placeholder="https://..." /></label>
      <label className="field mt-s">Credit line they want <span className="small muted">optional, added to every post</span><input type="text" value={a.attribution} onChange={(e) => set({ attribution: e.target.value })} placeholder="Clip from @theirname's podcast" /></label>
      <div className="row wrap mt-s" style={{ gap: 18 }}>
        <label className="row small"><input type="checkbox" checked={a.commercial} onChange={(e) => set({ commercial: e.target.checked })} /> Allows commercial use</label>
        <label className="row small"><input type="checkbox" checked={a.platforms.includes("youtube")} onChange={(e) => plat("youtube", e.target.checked)} /> YouTube</label>
        <label className="row small"><input type="checkbox" checked={a.platforms.includes("tiktok")} onChange={(e) => plat("tiktok", e.target.checked)} /> TikTok</label>
      </div>
      <label className="field mt-s">Ends on <span className="small muted">optional</span><input type="date" value={a.expires} onChange={(e) => set({ expires: e.target.value })} /></label>
      <label className="field mt-s">Folder with their files on this computer <span className="small muted">optional, e.g. a Dropbox or Google Drive folder they share</span>
        <input type="text" value={a.media_folder} onChange={(e) => set({ media_folder: e.target.value })} placeholder="C:\\Users\\you\\Dropbox\\Their raw videos" /></label>
      <label className="field mt-s">Address of their file links <span className="small muted">optional: direct file links they give you start with this</span>
        <input type="text" value={a.media_url_prefix} onChange={(e) => set({ media_url_prefix: e.target.value })} placeholder="https://files.example.com/raw/" /></label>
      <label className="row small mt-s"><input type="checkbox" checked={a.third_party} onChange={(e) => set({ third_party: e.target.checked })} /> It also covers other people's music or footage in their videos <span className="muted">(only if the agreement says so)</span></label>
      <p className="small muted mt-s">Without a shared folder or file link, their YouTube videos are still skipped: YouTube does not allow downloading its videos without its permission.</p>
    </Dialog>
  );
}

function RightsFields({ status, setStatus, basis, setBasis, empty = "Choose..." }: {
  status: string; setStatus: (s: string) => void; basis: string; setBasis: (s: string) => void; empty?: string;
}) {
  return (
    <>
      <label className="field">Rights status
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="" disabled={empty === "Choose..."}>{empty}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{RIGHTS_LABEL[s]}</option>)}
        </select>
      </label>
      <label className="field mt-s">Basis <span className="small muted">what gives you the right (required for Licensed and Allowlisted)</span>
        <input type="text" value={basis} placeholder="e.g. My own recordings / Official clipping program, joined 2026-09-01 / License #123" onChange={(e) => setBasis(e.target.value)} />
      </label>
    </>
  );
}

function Dialog({ title, children, onSave, onClose, label = "Save" }: { title: string; children: ReactNode; onSave: () => Promise<void>; onClose: () => void; label?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal onClose={onClose}>
      <div className="confirm" style={{ width: "min(560px, 94vw)" }}>
        <h3 style={{ marginTop: 0 }}>{title}</h3>
        {children}
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              await onSave();
              onClose();
            } catch (e) {
              toast(errorText(e), true);
              setBusy(false);
            }
          }}>{label}</button>
        </div>
      </div>
    </Modal>
  );
}

function RightsDialog({ source, onClose, onDone }: { source: Source; onClose: () => void; onDone: () => void }) {
  const [status, setStatus] = useState<string>(source.rights_status === "MANUAL_CONFIRMATION_REQUIRED" ? "" : source.rights_status);
  const [basis, setBasis] = useState(source.rights_basis || "");
  return (
    <Dialog title={`Rights for “${source.title.slice(0, 60)}”`} onClose={onClose} onSave={async () => {
      if (!status) throw new Error("Choose a rights status");
      await ap.confirmRights(source.id, status, basis);
      toast("Saved");
      onDone();
    }}>
      <p className="small muted">{source.rights_explain}</p>
      <p className="small">Only confirm rights you actually have. Being public, trending or downloadable does not make a video reusable.</p>
      <RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} />
    </Dialog>
  );
}

function AddFeedDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [kind, setKind] = useState("watch_folder");
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [status, setStatus] = useState("");
  const [basis, setBasis] = useState("");
  const key = kind === "watch_folder" ? "path" : kind === "youtube_channel" ? "channel_id" : kind === "stream_url" ? "url" : value.startsWith("http") ? "url" : "path";
  const withRights = kind !== "signal_feed";
  return (
    <Dialog title="Add a source feed" label="Add" onClose={onClose} onSave={async () => {
      await ap.addFeed({ kind, name, config: { [key]: value }, rights_status: withRights ? status : "", rights_basis: withRights ? basis : "" });
      toast("Added");
      onDone();
    }}>
      <label className="field">Kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="watch_folder">Watch folder (your recordings)</option>
          <option value="youtube_channel">YouTube channel (new uploads)</option>
          <option value="stream_url">Stream URL (HLS/RTMP/SRT you may use)</option>
          <option value="signal_feed">Signal feed (JSON/CSV file or URL)</option>
        </select>
      </label>
      <label className="field mt-s">Name<input type="text" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="field mt-s">{kind === "watch_folder" ? "Folder on this computer" : kind === "youtube_channel" ? "Channel ID (starts with UC)" : kind === "stream_url" ? "Stream URL" : "File path or URL"}
        <input type="text" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      {withRights && <div className="mt-s"><RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} empty="Ask me for each video" /></div>}
      {kind === "youtube_channel" && <p className="small muted">Following a channel finds its new uploads. Downloading them still needs a passing rights status and, for YouTube, either the original file or the download setting in Settings → Autopilot → Rights.</p>}
    </Dialog>
  );
}

function AddRuleDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [scope, setScope] = useState("channel");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState("ALLOWLISTED");
  const [basis, setBasis] = useState("");
  const [evidence, setEvidence] = useState("");
  return (
    <Dialog title="Add a rights rule" label="Add rule" onClose={onClose} onSave={async () => {
      await ap.addRule({ scope: scope as RightsRule["scope"], value, label, status: status as RightsRule["status"], basis, evidence_url: evidence, platform: scope === "channel" ? "youtube" : "" });
      toast("Rule added");
      onDone();
    }}>
      <label className="field">Applies to
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="channel">A YouTube channel (channel ID)</option>
          <option value="folder">A folder on this computer</option>
          <option value="url_prefix">URLs starting with...</option>
        </select>
      </label>
      <label className="field mt-s">Value<input type="text" value={value} onChange={(e) => setValue(e.target.value)} /></label>
      <label className="field mt-s">Label<input type="text" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. the creator's name" /></label>
      <div className="mt-s"><RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} /></div>
      <label className="field mt-s">Evidence link <span className="small muted">optional</span><input type="text" value={evidence} onChange={(e) => setEvidence(e.target.value)} /></label>
    </Dialog>
  );
}

function AddSourceDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [where, setWhere] = useState("");
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState("");
  const [basis, setBasis] = useState("");
  return (
    <Dialog title="Add a source" label="Add" onClose={onClose} onSave={async () => {
      const isUrl = /^(https?|rtmps?|srt):\/\//i.test(where.trim());
      await ap.addSource({ [isUrl ? "url" : "path"]: where.trim(), title, rights_status: status, basis });
      toast("Added");
      onDone();
    }}>
      <label className="field">Video file path or URL<input type="text" value={where} onChange={(e) => setWhere(e.target.value)} /></label>
      <label className="field mt-s">Title<input type="text" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <div className="mt-s"><RightsFields status={status} setStatus={setStatus} basis={basis} setBasis={setBasis} empty="Decide later (not clipped until then)" /></div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ jobs
const JOB_BADGE: Record<string, string> = { queued: "", running: "warn", waiting: "info", retrying: "info", completed: "good", failed: "bad", canceled: "" };

function JobsTab() {
  const [status, setStatus] = useState("queued,running,waiting,retrying,failed");
  const { data: jobs, refresh } = usePoll(() => ap.jobs(status), [status], 3000, () => true);
  const [logs, setLogs] = useState<{ job: Job; lines: { at: number; level: string; event: string; message: string }[] } | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      refresh();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (
    <div className="card">
      <div className="row between wrap">
        <h3 style={{ margin: 0 }}>Jobs</h3>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 240 }}>
          <option value="queued,running,waiting,retrying,failed">Active and failed</option>
          <option value="">All (latest 150)</option>
          <option value="completed">Completed</option>
          <option value="canceled">Canceled</option>
        </select>
      </div>
      <div className="jobs mt">
        {(jobs || []).map((j) => (
          <div key={j.id} className="job">
            <span className={`badge ${JOB_BADGE[j.status]}`}>{j.status}</span>
            <div className="job-main">
              <b>{j.kind.replace("_", " ")}</b> <span className="small muted">{j.worker.replace("_", " ")} · attempt {j.attempts}/{j.max_attempts}{j.priority >= 100 ? " · started by you" : ""}</span>
              <div className="small">{j.message}{j.wait_reason ? ` (${j.wait_reason})` : ""}</div>
              {j.error && <div className="small bad-text">{j.error}{j.fix ? <> <b>What to do:</b> {j.fix}</> : null}</div>}
              {j.status === "running" && <div className="bar mt-s"><div style={{ width: `${Math.max(2, j.progress * 100)}%` }} /></div>}
            </div>
            <div className="row">
              <button className="btn sm ghost" onClick={async () => setLogs({ job: j, lines: await ap.jobLogs(j.id) })}>Log</button>
              {["queued", "running", "waiting", "retrying"].includes(j.status) && <button className="btn sm ghost danger" onClick={() => act(() => ap.cancelJob(j.id))}>Cancel</button>}
              {["failed", "canceled"].includes(j.status) && <button className="btn sm" onClick={() => act(() => ap.retryJob(j.id))}>Retry</button>}
            </div>
          </div>
        ))}
        {!jobs?.length && <div className="small muted">No jobs.</div>}
      </div>
      {logs && (
        <Modal onClose={() => setLogs(null)}>
          <div className="confirm" style={{ width: "min(760px, 94vw)" }}>
            <h3 style={{ marginTop: 0 }}>{logs.job.kind} · log</h3>
            <div className="logs">
              {logs.lines.map((l, i) => <div key={i} className={`log ${l.level}`}><span className="muted">{new Date(l.at * 1000).toLocaleTimeString()}</span> <b>{l.event}</b> {l.message}</div>)}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ learning
function LearningTab() {
  const { data } = usePoll(() => ap.learning(), [], 15000, () => true);
  if (!data) return <div className="spinner" />;
  const s = data.status;
  return (
    <div className="grid grid-2">
      <div className="card">
        <div className="row between"><h3 style={{ margin: 0 }}>What your results show</h3><button className="btn sm" onClick={async () => { await ap.learn(); toast("Learning started"); }}>Learn now</button></div>
        <p className="small">{s.message || "Nothing learned yet."}</p>
        <div className="small muted">Posts with real numbers: {s.samples} (needs {data.min_samples}).</div>
        {s.note && <div className="notice warn small block mt-s">{s.note}</div>}
        <ul className="flags mt-s">{(s.findings || []).map((f, i) => <li key={i}>{f}</li>)}</ul>
        {!s.findings?.length && <p className="small muted">No conclusions are drawn until there is enough data from your own posts. Posting times are spread evenly until then.</p>}
      </div>
      <div className="card">
        <h3>How the scores are weighted</h3>
        {data.weights.length ? data.weights.map((w) => (
          <div key={w.key} className="sys-item small"><span className="k">{w.key}</span><span>weight {w.lift.toFixed(3)} · rank agreement with your results {w.data.rho.toFixed(2)} over {w.n} posts</span></div>
        )) : <p className="small muted">Default weights (not enough results to adjust them).</p>}
        <div className="hr" />
        <h3>Reliable groups ({data.metrics.length})</h3>
        <div className="small">
          {data.metrics.slice(0, 20).map((m, i) => (
            <div key={i} className="sys-item"><span className="k">{m.platform} · {data.labels[m.dimension] || m.dimension} {m.key}</span><span>{m.lift.toFixed(2)}x · {m.n} posts</span></div>
          ))}
        </div>
      </div>
    </div>
  );
}
