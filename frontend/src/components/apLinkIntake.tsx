import { FormEvent, useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { ap, AutopilotLink } from "../autopilot";
import { when } from "../format";
import { ConfirmDialog, Icon, Pill, ProgressBar, Skel, Tone, usePoll } from "./ui";

type LinkAction = "cancel" | "retry" | "prioritize" | "remove";

const POST_STATEMENT = "I made this video, or its creator lets me post clips of it.";

/** How posted clips go out, in one line (YouTube by itself only with automatic publishing on). */
const goesOut = (autoYouTube: boolean) => autoYouTube
  ? "YouTube posts go out by themselves; TikTok posts wait for your OK in Posts."
  : "They wait for your OK in Posts. To post to YouTube without being asked, turn on automatic publishing under "
    + "How posts go out.";

/**
 * One durable list: new links appear immediately, and duplicates lead back to the existing video. A video's clips
 * are posted only when you say you may post them ("Post the clips for me"), when adding it or later on its row.
 */
export default function LinkIntake({ enabled, stopped, timezone, refreshStatus, autoYouTube = false }: {
  enabled: boolean; stopped: boolean; timezone: string; refreshStatus: () => void; autoYouTube?: boolean;
}) {
  const { data, error, refresh, setData } = usePoll(() => ap.links(), [], 3000, () => true);
  const [url, setUrl] = useState("");
  const [post, setPost] = useState(false);
  const [adding, setAdding] = useState(false);
  const [acting, setActing] = useState("");
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [focusId, setFocusId] = useState("");
  const rows = useRef<Record<string, HTMLElement | null>>({});
  useEffect(() => {
    if (!focusId || !rows.current[focusId]) return;
    const row = rows.current[focusId];
    row?.focus({ preventScroll: true });
    row?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setFocusId("");
  }, [focusId, data]);

  const remember = (item: AutopilotLink, first = false) => {
    // Restart polling after a mutation so an older in-flight answer cannot replace the new status.
    setData(item.status === "removed" ? (data || []).filter((i) => i.id !== item.id)
      : first ? [item, ...(data || []).filter((i) => i.id !== item.id)]
      : data?.some((i) => i.id === item.id)
        ? data.map((i) => i.id === item.id ? item : i) : [item, ...(data || [])]);
    refresh();
    refreshStatus();
  };
  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (adding || acting || !url.trim()) return;
    setAdding(true);
    setNotice("");
    setProblem("");
    try {
      const result = await ap.addLink(url.trim(), post);
      remember(result.item);
      const posted = result.item.posting.on ? " Its clips will be posted." : "";
      setNotice(result.already_added ? `Already added.${posted}` : `Added. Autopilot will work on this when it can.${posted}`);
      setUrl("");
      setPost(false);  // your statement is about one video: say it again for the next one
      setFocusId(result.item.id);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setAdding(false);
    }
  };
  const act = async (item: AutopilotLink, action: LinkAction) => {
    if (acting) return;
    setActing(item.id);
    setProblem("");
    setNotice("");
    try {
      const result = await ap.linkAction(item.id, action);
      if (action === "remove") {
        setData((data || []).filter((i) => i.id !== item.id));
        refresh();
        refreshStatus();
      } else remember(result, action === "prioritize");
      const word = { cancel: "Canceled", retry: "Added for another try", prioritize: "Moved to the top",
        remove: "Removed from Added by you" }[action];
      setNotice(`${word}: ${item.title || "Video"}`);
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setActing("");
    }
  };
  const setPosting = async (item: AutopilotLink, on: boolean) => {
    const result = await ap.linkPosting(item.id, on);  // a refusal stays in the dialog, which says why
    remember(result);
    setNotice(`${on ? "Its clips will be posted" : "Its clips are no longer posted"}: ${item.title || "Video"}`);
  };
  return (
    <section className="panel ap-link-intake" aria-labelledby="ap-add-video">
      <h2 id="ap-add-video">Add a video or stream</h2>
      <form className="ap-link-form" onSubmit={add}>
        <label className="stack grow" htmlFor="ap-video-link">
          <span className="small">Paste a video or stream link</span>
          <input id="ap-video-link" type="url" inputMode="url" value={url} required
            placeholder="https://…" autoComplete="off" disabled={adding || !!acting}
            aria-describedby="ap-link-hint" onChange={(e) => setUrl(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={adding || !!acting || !url.trim()}>
          <Icon name={adding ? "refresh" : "plus"} />{adding ? "ADDING…" : "ADD"}
        </button>
      </form>
      <label className="row small top ap-link-post">
        <input type="checkbox" checked={post} disabled={adding || !!acting}
          onChange={(e) => setPost(e.target.checked)} />
        <span><b>Post the clips for me.</b> {POST_STATEMENT}</span>
      </label>
      <p id="ap-link-hint" className="tiny faint">Your links go first after the current safe step. Other work keeps
        going. Without the tick, clips stay in your Library. Ticked, they are planned over your posting hours.{" "}
        {goesOut(autoYouTube)}</p>
      {(!enabled || stopped) && <p className="small muted">Links are saved now and wait until you
        {stopped ? " resume jobs" : " start Autopilot"}.</p>}
      <p className="small" role="status" aria-live="polite">{notice}</p>
      {problem && <p className="small bad-text" role="alert">{problem}</p>}
      <hr className="divider" />
      <h3 id="ap-added-by-you">Added by you</h3>
      {error && <p className="small muted" role="status">Could not refresh your links. Any statuses below are from
        the last update. <button type="button" className="textlink" onClick={refresh}>Try again</button></p>}
      {data === null ? <Skel className="skel-block" /> : data.length ? (
        <div className="rows" aria-labelledby="ap-added-by-you">
          {data.map((item) => <LinkRow key={item.id} item={item} timezone={timezone} disabled={adding || !!acting}
            rowRef={(el) => { rows.current[item.id] = el; }} act={(action) => act(item, action)}
            setPosting={(on) => setPosting(item, on)} autoYouTube={autoYouTube} />)}
        </div>
      ) : <p className="small muted">Paste a link above whenever you have a video or stream in mind.</p>}
    </section>
  );
}

function LinkRow({ item, timezone, disabled, rowRef, act, setPosting, autoYouTube }: {
  item: AutopilotLink; timezone: string; disabled: boolean; rowRef: (el: HTMLElement | null) => void;
  act: (action: LinkAction) => void; setPosting: (on: boolean) => Promise<void>; autoYouTube: boolean;
}) {
  const [asking, setAsking] = useState<"on" | "off" | "">("");
  const title = item.title || "Video or stream";
  const p = item.posting;
  const live = item.status === "watching_live";
  const waiting = item.status === "waiting_stream";
  const tone: Tone = ["inaccessible", "failed"].includes(item.status) ? "warn"
    : ["ready", "finished"].includes(item.status) ? "good" : live ? "info" : "neutral";
  const progress = Math.max(0, Math.min(1, item.progress || 0));
  return (
    <article className="ap-link-row" ref={rowRef} tabIndex={-1} aria-labelledby={`ap-link-title-${item.id}`}>
      <div className="row wrap top">
        <div className="stack grow" style={{ gap: 6 }}>
          <div className="row wrap">
            {live && <Pill tone="info" icon="dot">LIVE</Pill>}
            <h4 className="post-title" id={`ap-link-title-${item.id}`}>
              {item.project_id ? <a href={`#/project/${item.project_id}`}>{title}</a> : title}
            </h4>
          </div>
          <span className="small">{live ? `Watching ${title}` : item.status_label}</span>
          {live && <span className="tiny muted">{item.detail || "Listening for good moments"}</span>}
          {!live && item.detail && <span className="tiny muted break">{item.detail}</span>}
          {waiting && item.scheduled_at && <span className="small">Starts {when(item.scheduled_at, timezone)}</span>}
          {progress > 0 && progress < 1 && <ProgressBar value={progress} label={`${title}: ${item.status_label}`} />}
        </div>
        <Pill tone={tone} icon={live ? "dot" : tone === "good" ? "check" : "clock"}>{item.status_label}</Pill>
      </div>
      {p && (
        <div className="row wrap ap-link-posting">
          <Pill tone={p.on ? "good" : "neutral"} icon={p.on ? "upload" : "library"}>{p.on ? "Posting" : "Not posted"}</Pill>
          <span className="tiny muted">{p.label}</span>
          {p.can_change && !p.on && <button type="button" className="btn btn-small" disabled={disabled}
            aria-label={`Post the clips: ${title}`} onClick={() => setAsking("on")}>Post the clips</button>}
          {p.can_change && p.on && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
            aria-label={`Stop posting: ${title}`} onClick={() => setAsking("off")}>Stop posting</button>}
        </div>
      )}
      {asking === "on" && (
        <ConfirmDialog title="Post the clips of this video?" confirmLabel="Yes, post the clips"
          onConfirm={() => setPosting(true)} onClose={() => setAsking("")}>
          <p>Only if <b>you made this video, or its creator lets you post clips of it</b> (for example a clipping
            program you joined). Being public or popular does not make a video yours to post: posting someone
            else's video can get your account a copyright strike.</p>
          <p className="small muted">ClipFoundry saves your answer with today's date. Its finished clips are then
            planned over your posting hours. {goesOut(autoYouTube)}</p>
        </ConfirmDialog>
      )}
      {asking === "off" && (
        <ConfirmDialog title="Stop posting this video's clips?" confirmLabel="Stop posting"
          onConfirm={() => setPosting(false)} onClose={() => setAsking("")}>
          <p>Planned posts from this video that have not started uploading are canceled. Its clips stay in your
            Library.</p>
        </ConfirmDialog>
      )}
      <div className="row wrap ap-link-actions">
        {item.can_prioritize && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
          aria-label={`Move to top: ${title}`} onClick={() => act("prioritize")}>Move to top</button>}
        {item.can_retry && <button type="button" className="btn btn-small" disabled={disabled}
          aria-label={`Retry: ${title}`} onClick={() => act("retry")}>Retry</button>}
        {item.can_cancel && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
          aria-label={`Cancel: ${title}`} onClick={() => act("cancel")}>Cancel</button>}
        {item.can_remove && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
          aria-label={`Remove: ${title}`} onClick={() => act("remove")}>Remove</button>}
      </div>
    </article>
  );
}
