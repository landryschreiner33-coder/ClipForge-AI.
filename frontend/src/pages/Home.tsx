import { ReactNode, useEffect, useRef, useState } from "react";
import { api, Clip, clipThumbUrl, Project, projectThumbUrl, timeAgo } from "../api";
import { NeedsYouItem } from "../autopilot";
import { UpcomingRow } from "../components/apShared";
import { NeedActions, needLook, NeedTone } from "../components/needsYou";
import { Icon, IconName, PageHead, Pill, Skel, Thumb } from "../components/ui";
import { plural, zoneLine } from "../format";
import { autopilotState, useStatus } from "../status";

/**
 * Home: the one next step, then recent videos and clips and the next few posts. It links to Autopilot and Posts
 * instead of repeating them: no stats, no specs. Everything comes from the shared Autopilot status and the library.
 */

type RecentProject = Project & { origin?: string };
const BUSY = ["uploading", "queued", "processing", "created"];

/** The newest videos, and the clips of the ones on the page (read again only when a video changed). */
function useRecent() {
  const [projects, setProjects] = useState<RecentProject[] | null>(null);
  const [clips, setClips] = useState<Record<string, Clip[]>>({});
  const seen = useRef<Record<string, { stamp: string; clips: Clip[] }>>({});
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const run = async () => {
      let busy = false;
      try {
        const s = await api.stats();
        if (!alive) return;
        setProjects(s.recent);
        busy = s.processing > 0 || s.recent.some((p) => BUSY.includes(p.status));
        for (const p of s.recent.slice(0, 4)) {
          const stamp = `${p.updated_at}:${p.clip_count}`;
          if (!p.clip_count || seen.current[p.id]?.stamp === stamp) continue;
          const full = await api.project(p.id);
          seen.current[p.id] = { stamp, clips: full.clips || [] };
        }
        if (alive) setClips(Object.fromEntries(Object.entries(seen.current).map(([k, v]) => [k, v.clips])));
      } catch {
        /* the connection banner says when ClipFoundry is not answering; keep what was shown */
      }
      if (alive) timer = setTimeout(run, busy ? 4000 : 15000);
    };
    run();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);
  return { projects, clips };
}

const ORIGIN: Record<string, string> = { autopilot: "Made by Autopilot", live: "Live stream (Autopilot)" };
const origin = (p: RecentProject) => ORIGIN[p.origin || ""] || "Added by you";

/** A source video's state in words: the real stage while it works, the clip count when it is done. */
function ProjectStatus({ p }: { p: RecentProject }) {
  const n = p.clip_count || 0;
  switch (p.status) {
    case "uploading": return <Pill tone="info" icon="upload">Copying into ClipFoundry</Pill>;
    case "created": return <Pill tone="neutral" icon="clock">Waiting to start</Pill>;
    case "queued":
    case "processing":
      return /^waiting/i.test(p.message || "") ? <Pill tone="warn" icon="clock">{p.message}</Pill>
        : <Pill tone="info" icon="refresh">{p.message || "Making clips"}</Pill>;
    case "error": return <Pill tone="bad" icon="alert">Couldn't make clips</Pill>;
    case "cancelled": return <Pill tone="neutral" icon="x">Canceled</Pill>;
    default:
      return n ? <Pill tone="good" icon="check">Ready · {plural(n, "clip")}</Pill>
        : <Pill tone="neutral" icon="info">Ready · no clip passed the quality bar</Pill>;
  }
}

type Lead = { tone: NeedTone | "good" | ""; kicker: ReactNode; sentence: ReactNode; detail?: ReactNode; fix?: string;
  actions?: ReactNode };
type Also = { key: string; tone: NeedTone; icon: IconName; title: string; action: ReactNode };
const ALSO_WORD: Record<NeedTone, string> = { bad: "Problem", warn: "Waiting", info: "Info" };
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

export default function Home() {
  const { st, lost, lastOk, refresh } = useStatus();
  const { projects, clips } = useRecent();
  const state = autopilotState(st, lost);
  const h = st?.home;
  const since = lastOk ? new Date(lastOk).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";

  // Automatic failures stay in Recent videos; only genuine exceptions from Autopilot ask for attention.
  const items: NeedsYouItem[] = lost ? [] : h?.needs_you || [];
  const failed = (projects || []).filter((p) => p.status === "error"
    && !["autopilot", "live"].includes(p.origin || ""));
  const firstUse = !!st && !lost && !st.home.setup.started && projects !== null && projects.length === 0
    && st.home.setup.mode !== "manual";
  const busyProject = (projects || []).find((p) => BUSY.includes(p.status));
  const readyProject = (projects || []).find((p) => p.status === "ready" && (p.clip_count || 0) > 0);

  let lead: Lead | null = null;
  if (lost) {
    lead = {
      tone: "warn", kicker: <Pill tone="neutral" icon="offline">Status unknown</Pill>,
      sentence: "ClipFoundry isn't answering, so this page can't say what it's doing.",
      detail: <p className="muted">{since ? `The last update was at ${since}. ` : ""}Check that the black ClipFoundry
        window is still open.</p>,
      actions: (
        <button type="button" className="btn btn-primary" onClick={refresh}><Icon name="refresh" />Try again</button>
      ),
    };
  } else if (!st || projects === null) {
    lead = null; // still loading: skeleton
  } else if (firstUse) {
    lead = {
      tone: "", kicker: <Pill tone="accent" icon="spark">Welcome</Pill>,
      sentence: "Start by adding a video you made. ClipFoundry finds its best moments and turns them into short "
        + "vertical clips.",
      detail: <p className="muted">Everything runs on this computer. Posting to YouTube or TikTok is optional and can
        wait.</p>,
      actions: <>
        <a className="btn btn-primary" href="#/setup/videos">Get started</a>
        <a className="btn" href="#/create">Add a video now</a>
      </>,
    };
  } else if (items.length) {
    const it = items[0];
    const [tone, icon] = needLook(it);
    lead = {
      tone, kicker: <Pill tone={tone} icon={icon}>Needs you</Pill>, sentence: it.title, fix: it.fix,
      detail: <>
        {it.source && it.type === "rights" && (
          <p>“{it.source.title}”{it.source.channel ? ` · ${it.source.channel}` : ""}</p>
        )}
        {it.question && <p className="strong">{it.question}</p>}
        {it.detail && <p className="muted">{it.detail}</p>}
      </>,
      actions: <NeedActions item={it} platforms={st.platforms} refresh={refresh} primary />,
    };
  } else if (failed.length) {
    const p = failed[0];
    lead = {
      tone: "bad", kicker: <Pill tone="bad" icon="alert">Needs you</Pill>,
      sentence: `“${p.name}” could not be made into clips`,
      detail: p.error ? <p className="muted">{p.error}</p> : null,
      actions: <a className="btn btn-primary" href={`#/project/${p.id}`}>Open video</a>,
    };
  } else if (h?.working && st.enabled && !st.paused) {
    const w = h.working;
    lead = {
      tone: "info", kicker: <Pill tone="info" icon="refresh">Working</Pill>,
      sentence: `Autopilot is ${lower(w.step)}${w.title ? ` in “${w.title}”` : ""}.`,
      detail: <p className="muted">Nothing needs you. New clips show up in your Library, and posts that need your OK
        show up in Posts.</p>,
      actions: <a className="btn btn-primary" href="#/autopilot">See what it's doing</a>,
    };
  } else if (busyProject) {
    lead = {
      tone: "info", kicker: <Pill tone="info" icon="refresh">Working</Pill>,
      sentence: `“${busyProject.name}” is being turned into clips`
        + `${busyProject.message ? `: ${lower(busyProject.message)}` : ""}.`,
      detail: <p className="muted">You can leave this page. The clips appear in your Library when they're ready.</p>,
      actions: <a className="btn btn-primary" href={`#/project/${busyProject.id}`}>Open video</a>,
    };
  } else if (readyProject) {
    lead = {
      tone: "good", kicker: <Pill tone="good" icon="check">All caught up</Pill>,
      sentence: `Nothing needs you. Your newest clips are from “${readyProject.name}”.`,
      detail: <p className="muted">{st.paused ? "All jobs are stopped, so nothing new starts until you resume."
        : st.enabled ? "Autopilot keeps looking for videos it may use."
          : st.home.setup.started ? "Autopilot is paused, so nothing new starts by itself."
            : "Add another video whenever you like."}</p>,
      actions: <>
        <a className="btn btn-primary" href={`#/project/${readyProject.id}`}>See the clips</a>
        <a className="btn" href="#/create">Add a video</a>
      </>,
    };
  } else {
    lead = {
      tone: "", kicker: <Pill tone="neutral" icon="check">All caught up</Pill>,
      sentence: "Nothing needs you. Add a video to make clips.",
      actions: <a className="btn btn-primary" href="#/create">Add a video</a>,
    };
  }

  // The rest of what needs you, each with one small action.
  const also: Also[] = [];
  if (st && !lost && !firstUse) {
    for (const it of items.slice(1)) {
      const [tone, icon] = needLook(it);
      also.push({ key: it.key, tone, icon, title: it.title,
        action: <NeedActions item={it} platforms={st.platforms} refresh={refresh} first /> });
    }
    for (const p of failed.slice(items.length ? 0 : 1)) {
      also.push({ key: `project:${p.id}`, tone: "bad", icon: "alert",
        title: `“${p.name}” could not be made into clips`,
        action: <a className="btn btn-small" href={`#/project/${p.id}`}>Open video</a> });
    }
  }

  const detail = state.word === "On" ? h?.currently
    : state.word === "Paused" ? "Nothing new is found, clipped or posted"
      : state.word === "Stopped" ? "All jobs are on hold until you resume them"
        : state.word === "Off" ? "Not set up yet" : lost && since ? `No answer since ${since}` : "";
  const recent = (projects || []).slice(0, 4);
  const upcoming = (h?.upcoming || []).slice(0, 4);

  return (
    <div className="page">
      <PageHead title="Summary"
        sub={<span className="small"><a className="textlink" href="#/autopilot">Autopilot: {state.word}</a>
          {detail ? ` · ${detail}` : ""}</span>}
        actions={<a className="btn" href="#/create"><Icon name="plus" />Add video</a>} />

      {lead ? (
        <section className={`lead ${lead.tone}`} aria-labelledby="lead-title">
          <div className="lead-top">
            <div className="grow">
              <div>{lead.kicker}</div>
              <h2 className="lead-sentence" id="lead-title">{lead.sentence}</h2>
              {lead.detail}
              {lead.fix && <p className="small"><b>What to do:</b> {lead.fix}</p>}
            </div>
          </div>
          {lead.actions && <div className="lead-actions">{lead.actions}</div>}
          {also.length > 0 && (
            <>
              <hr className="divider" />
              <div className="also">
                <h3 className="small muted">Also needs you ({also.length})</h3>
                {also.map((a) => (
                  <div key={a.key} className="also-item">
                    <Pill tone={a.tone} icon={a.icon}>{ALSO_WORD[a.tone]}</Pill>
                    <span className="also-title">{a.title}</span>
                    {a.action}
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      ) : (
        <section className="lead" aria-busy="true" aria-label="Loading what needs you">
          <Skel className="skel-line" style={{ width: 120 }} />
          <Skel className="skel-title" />
          <Skel className="skel-line" style={{ width: "60%" }} />
        </section>
      )}

      <div className="cols-main">
        <section className="panel" aria-labelledby="recent-title">
          <div className="panel-head">
            <h2 id="recent-title">Recent videos and clips</h2>
            <a className="btn btn-quiet btn-small" href="#/library">Open Library</a>
          </div>
          {projects === null ? (
            <div className="stack-3" aria-hidden="true">
              <Skel className="skel-block" style={{ height: 90 }} />
              <Skel className="skel-block" style={{ height: 90 }} />
            </div>
          ) : recent.length ? (
            <div className="rows">{recent.map((p) => <RecentRow key={p.id} p={p} clips={clips[p.id] || []} />)}</div>
          ) : (
            <div className="empty">
              <Icon name="film" className="lg" />
              <p className="muted">No videos yet. Clips you make show up here.</p>
            </div>
          )}
        </section>
        <section className="panel" aria-labelledby="up-title">
          <div className="panel-head">
            <h2 id="up-title">Coming up</h2>
            <a className="btn btn-quiet btn-small" href="#/posts/scheduled">All posts</a>
          </div>
          {!st ? <Skel className="skel-block" style={{ height: 120 }} /> : upcoming.length ? (
            <>
              <div className="rows">{upcoming.map((u) => <UpcomingRow key={u.id} u={u} tz={st.timezone} />)}</div>
              <p className="tiny faint">{zoneLine(st.timezone)}</p>
            </>
          ) : (
            <p className="muted small">No posts planned. {st.home.setup.started
              ? "When clips are ready, planned posts show up here."
              : "Posting is optional: you can export clips and post them yourself."}</p>
          )}
        </section>
      </div>
    </div>
  );
}

function RecentRow({ p, clips }: { p: RecentProject; clips: Clip[] }) {
  const shown = clips.slice(0, 5);
  return (
    <div className="stack-3 recent-row" style={{ padding: "12px 0" }}>
      <div className="row top">
        <a href={`#/project/${p.id}`} style={{ width: "min(132px, 34%)", flex: "none" }} aria-hidden="true"
          tabIndex={-1}>
          <Thumb src={p.has_thumbnail ? projectThumbUrl(p) : null} duration={p.duration} />
        </a>
        <div className="stack grow">
          <a className="post-title clamp-2" href={`#/project/${p.id}`}>{p.name}</a>
          <span><ProjectStatus p={p} /></span>
          <span className="tiny faint">{origin(p)} · {timeAgo(p.created_at)}</span>
        </div>
      </div>
      {shown.length > 0 && (
        <ul className="mini-clips" aria-label={`Clips from ${p.name}`}>
          {shown.map((c) => (
            <li key={c.id}>
              <a className="mini" href={`#/clip/${c.id}`} aria-label={`Edit clip: ${c.title}`}>
                <Thumb vertical src={c.has_thumbnail ? clipThumbUrl(c) : null}
                  duration={c.duration || c.end - c.start} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
