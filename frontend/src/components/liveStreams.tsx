import { FormEvent, useEffect, useId, useState } from "react";
import { errorText } from "../api";
import { ap } from "../autopilot";
import { plural, when } from "../format";
import {
  channelNames, LIVE_FRAMINGS, LIVE_PICKS, LiveFraming, LivePick, LiveStream, submissions,
} from "../submissions";
import { nameList } from "./channelPicker";
import { Box, FaceCamBox, START } from "./faceCam";
import { Banner, ConfirmDialog, Icon, IconName, Pill, Skel, toast, Tone, usePoll } from "./ui";
import { UploadChoice, useUploadChoice } from "./uploadChoice";

const MAX_LINKS = 10;
const isLink = (value: string) => /^https?:\/\/\S+$/i.test(value.trim());
const linesOf = (text: string) => text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);

type StreamAction = "cancel" | "retry" | "finish" | "stop_clipping";
const oneOf = <T extends string>(value: string, all: { value: T }[], fallback: T): T =>
  all.some(o => o.value === value) ? value as T : fallback;

/**
 * Live streams (#/missions/live): add one or several stream links, each recorded and clipped while it is live, with
 * the same per-input "Make & upload" request as a video. Every stream keeps its own recording, clips and uploads,
 * and its own choices: how picky it is (few strong clips, or every good moment) and whether its clips get a split
 * view (face cam on top, the rest of the picture below).
 *
 * Two ways to stop: "Stop recording" finishes what was recorded and still checks the full recording for missed
 * moments (which may swap a live clip nobody approved for a clearly better cut). "Stop clipping" stops the recording
 * and makes nothing more; the clips already made keep their checks and uploads.
 */
export default function LiveStreams({ timezone, stopped, enabled, gapMinutes, maxGb, maxMinutes, livePick, liveFraming,
  refreshStatus }: {
  timezone: string; stopped: boolean; enabled: boolean; gapMinutes: number; maxGb: number; maxMinutes: number;
  /** What a new stream starts with (Settings); each stream keeps the choice it was added with. */
  livePick: string; liveFraming: string;
  refreshStatus: () => void;
}) {
  const { data: setup, error: setupError, refresh: reloadSetup } = usePoll(submissions.setup, [], 30000, () => true);
  const { data, error, refresh } = usePoll(submissions.live, [], 3000, () => true);
  const [text, setText] = useState("");
  const choice = useUploadChoice(setup);
  const [busy, setBusy] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [acting, setActing] = useState("");
  const [confirmStop, setConfirmStop] = useState<LiveStream | null>(null);
  const [confirmNoClips, setConfirmNoClips] = useState<LiveStream | null>(null);
  const [pick, setPick] = useState<LivePick>(oneOf(livePick, LIVE_PICKS, "best"));
  const [framing, setFraming] = useState<LiveFraming>(oneOf(liveFraming, LIVE_FRAMINGS, "auto"));
  const id = useId();

  const links = linesOf(text);
  const bad = links.filter(line => !isLink(line));
  const tooMany = links.length > MAX_LINKS;
  const ready = links.length > 0 && !bad.length && !tooMany && !!setup && !setupError && !stopped && choice.complete;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setProblems([]);
    setNotice("");
    const options = { ...choice.options(), live_pick: pick, live_framing: framing };
    const failed: string[] = [];
    const kept: string[] = [];
    let added = 0;
    // One request per link: each stream gets its own recording and its own saved upload request.
    for (const link of links) {
      try {
        await submissions.link(link, options, true);
        added += 1;
      } catch (e) {
        failed.push(`${link}: ${errorText(e)}`);
        kept.push(link);
      }
    }
    if (added) {
      setNotice(`Added ${plural(added, "stream")}. ClipForge records each one while it is live`
        + (options.auto_upload ? " and uploads clips that pass the final checks." : " and keeps the clips on this computer."));
      if (!kept.length) choice.reset();
    }
    setProblems(failed);
    setText(kept.join("\n"));
    if (failed.length) reloadSetup();
    refresh();
    refreshStatus();
    setBusy(false);
  };

  const act = async (item: LiveStream, action: StreamAction) => {
    if (acting) return;
    setActing(item.id);
    try {
      await ap.linkAction(item.id, action);
      toast(action === "finish" ? "Stopping the recording. ClipForge finishes the clips from what was recorded."
        : action === "stop_clipping" ? (item.submission.auto_upload
          ? "Clipping stopped. The clips already made still upload." : "Clipping stopped. The clips already made are kept.")
        : action === "cancel" ? "Stream canceled" : "Stream queued for another try");
      refresh();
      refreshStatus();
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setActing("");
    }
  };

  const recording = (data || []).filter(item => item.live.recording).length;
  return <section className="panel submitted-videos live-streams" aria-labelledby={`${id}-heading`}>
    <div className="panel-head wrap">
      <div className="stack">
        <span className="kind-label">Live stream → clips while it is live</span>
        <h2 id={`${id}-heading`}>Clip live streams</h2>
      </div>
      {recording > 0 && <Pill tone="info" icon="dot">{plural(recording, "stream")} recording</Pill>}
    </div>
    <p className="muted small">Paste one or more stream links. ClipForge records each stream on this computer,
      listens for strong moments while it is live, makes vertical clips as they happen and, if you choose it below,
      uploads the ones that pass the final checks during the stream. When a stream ends, ClipForge checks the full
      recording for moments it missed.</p>
    <form className="stack-4" onSubmit={submit}>
      <fieldset className="submitted-form stack-4" disabled={busy}>
        <legend className="sr-only">Streams and upload choices</legend>
        <label className="stack small" htmlFor={`${id}-links`}>
          <span className="strong" id={`${id}-links-label`}>Stream links, one per line</span>
          <textarea id={`${id}-links`} rows={3} value={text} placeholder={"https://www.twitch.tv/…\nhttps://www.youtube.com/@…/live"}
            autoComplete="off" spellCheck={false} aria-labelledby={`${id}-links-label`}
            aria-invalid={bad.length || tooMany ? true : undefined} aria-describedby={`${id}-links-help`}
            onChange={event => { setText(event.target.value); choice.setAgreed(false); }} />
          <span className="hint" id={`${id}-links-help`}>A Twitch or Kick channel, a YouTube live video or a channel's
            live page (youtube.com/@name/live), or a public .m3u8 stream. A channel that is not live yet is recorded
            when it starts (ClipForge waits up to a day). Login-only and protected streams cannot be recorded.
            Each stream is recorded for at most {maxMinutes % 60 === 0 ? plural(maxMinutes / 60, "hour")
              : plural(maxMinutes, "minute")} or {maxGb} GB, whichever comes first (Largest source in <a
              className="textlink" href="#/settings/advanced">Settings → Advanced</a>); then ClipForge stops recording,
            even if the stream is still live, and finishes the clips from what was recorded.</span>
          {bad.length > 0 && <span className="error-text">Use links starting with https:// or http://
            ({plural(bad.length, "line needs", "lines need")} fixing).</span>}
          {tooMany && <span className="error-text">Add at most {MAX_LINKS} streams at a time.</span>}
        </label>
        <fieldset className="stack live-choices">
          <legend className="small strong">How {links.length > 1 ? "these streams are" : "this stream is"} clipped</legend>
          <div className="row wrap top live-choice-row">
            <label className="stack small grow" htmlFor={`${id}-pick`}>
              <span>How picky</span>
              <select id={`${id}-pick`} value={pick} aria-describedby={`${id}-pick-hint`}
                onChange={event => setPick(event.target.value as LivePick)}>
                {LIVE_PICKS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="hint" id={`${id}-pick-hint`}>{LIVE_PICKS.find(o => o.value === pick)?.hint}</span>
            </label>
            <label className="stack small grow" htmlFor={`${id}-framing`}>
              <span>Split view</span>
              <select id={`${id}-framing`} value={framing} aria-describedby={`${id}-framing-hint`}
                onChange={event => setFraming(event.target.value as LiveFraming)}>
                {LIVE_FRAMINGS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <span className="hint" id={`${id}-framing-hint`}>{LIVE_FRAMINGS.find(o => o.value === framing)?.hint}</span>
            </label>
          </div>
        </fieldset>
        <UploadChoice choice={choice} setup={setup} id={id} what="stream" count={Math.max(1, links.length)} />
      </fieldset>
      {setupError && <Banner tone="warn" title="Upload setup could not refresh">{setupError}
        <button type="button" className="textlink" onClick={reloadSetup}>Try again</button></Banner>}
      {stopped && <Banner tone="warn" title="Jobs are stopped">Resume jobs before adding a stream.</Banner>}
      {!stopped && !enabled && <Banner tone="warn" title="Autopilot is paused">Adding a stream turns Autopilot on.
        Pausing Autopilot later also pauses every recording.</Banner>}
      <div className="row wrap submitted-actions">
        <span className="hint grow">Keep ClipForge open and the computer awake while streams are recording.
          {choice.autoUpload && <> Clips upload as they pass the final checks, at most one
            {gapMinutes > 0 ? ` every ${plural(gapMinutes, "minute")}` : " at a time"} per YouTube account,
            shared by all streams (Minimum gap in <a className="textlink" href="#/settings/advanced">Settings → Advanced</a>).</>}</span>
        <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name={choice.autoUpload ? "upload" : "scissors"} />}
          {busy ? "Adding…" : links.length > 1 ? `Clip ${links.length} streams` : "Clip this stream"}
        </button>
      </div>
      {notice && <p className="small" role="status">{notice}</p>}
      {problems.length > 0 && <div className="small bad-text" role="alert">
        {problems.length === 1 ? problems[0] : <ul>{problems.map(line => <li key={line}>{line}</li>)}</ul>}
        {problems.length > 0 && <p>Links that could not be added stay in the box above.</p>}
      </div>}
    </form>
    <hr className="divider" />
    <div className="panel-head"><h3 id={`${id}-streams`}>Your streams</h3>
      <a className="textlink small" href="#/publishing/scheduled">See uploads<Icon name="chev" className="sm" /></a></div>
    {error && <p className="small muted" role="status">Could not refresh the streams. Last known results are shown.
      <button type="button" className="textlink" onClick={refresh}>Try again</button></p>}
    {data === null ? <Skel className="skel-block" /> : !data.length ? <p className="small muted">
      Streams you add appear here with what was recorded, the clips made so far and their uploads.</p>
      : <div className="rows" aria-labelledby={`${id}-streams`}>{data.map(item => <StreamRow key={item.id} item={item}
        timezone={timezone} disabled={!!acting} act={action => action === "finish" ? setConfirmStop(item)
          : action === "stop_clipping" ? setConfirmNoClips(item) : act(item, action)} />)}</div>}
    {confirmStop && <ConfirmDialog title="Stop recording this stream?" confirmLabel="Stop recording"
      onClose={() => setConfirmStop(null)} onConfirm={() => act(confirmStop, "finish")}>
      <p>ClipForge stops recording “{confirmStop.title || "this stream"}”, then checks the full recording for
        moments it missed. The clips made so far{confirmStop.submission.auto_upload ? " and their uploads" : ""} stay,
        except that the check of the full recording may swap a live clip that is not approved, uploading or uploaded
        for a clearly better cut of the same moment. {canAddAgain(confirmStop)
          ? "This cannot be resumed: once it has stopped, add the link again to record from then on."
          : "This cannot be resumed, and this video link cannot be added again."}</p>
    </ConfirmDialog>}
    {confirmNoClips && <ConfirmDialog title="Stop clipping this stream?" confirmLabel="Stop clipping"
      onClose={() => setConfirmNoClips(null)} onConfirm={() => act(confirmNoClips, "stop_clipping")}>
      <p>ClipForge stops recording “{confirmNoClips.title || "this stream"}” and makes no more clips from it,
        neither now nor from the full recording. {made(confirmNoClips)} {canAddAgain(confirmNoClips)
          ? "This cannot be undone for this stream: add the link again to clip it from then on."
          : "This cannot be undone, and this video link cannot be added again."}</p>
    </ConfirmDialog>}
  </section>;
}

/** What "Stop clipping" keeps, in the dialog's words. */
function made(item: LiveStream): string {
  const clips = item.submission.progress?.clips_ready || item.live.live_clips;
  if (!clips) return "No clip has been made yet, so none will be.";
  const these = clips === 1 ? "The clip already made stays" : `The ${clips} clips already made stay`;
  return item.submission.auto_upload
    ? `${these}: ${clips === 1 ? "it still goes" : "they still go"} through the final checks and `
      + `${clips === 1 ? "uploads at its planned time" : "upload at their planned times"}.`
    : `${these} on this computer.`;
}

/** Only a channel page or a stream address can be added again for a later broadcast (submissions._finished_broadcast);
 * a YouTube video link names one broadcast and is refused as already added. */
const canAddAgain = (item: LiveStream) => item.platform === "url" || item.platform === "stream";

function streamState(item: LiveStream): [Tone, IconName, string] {
  const live = item.live;
  if (item.status === "canceled" || item.status === "removed") return ["neutral", "x", "Canceled"];
  if (["failed", "inaccessible"].includes(item.status) || item.submission.status === "needs_attention")
    return ["warn", "alert", "Needs attention"];
  if (live.finishing) return ["info", "clock", live.clipping_stopped ? "Stopping" : "Stopping the recording"];
  if (live.recording) return ["info", "dot", "Recording live"];
  if (item.status === "waiting_stream") return ["neutral", "clock", "Waiting for the stream to start"];
  if (item.status === "finding_clips" || item.status === "making_clips" || item.status === "final_check")
    return ["info", "clock", live.ended ? "Checking the full recording" : "Making clips"];
  if (live.ended && ["ready", "finished"].includes(item.status))
    return ["good", "check", live.clipping_stopped ? "Clipping stopped" : live.stopped ? "Stopped" : "Ended"];
  if (item.status === "watching_live" || item.status === "waiting") return ["neutral", "clock", "Waiting for its turn"];
  return ["neutral", "clock", item.status_label];
}

function StreamRow({ item, timezone, disabled, act }: {
  item: LiveStream; timezone: string; disabled: boolean; act: (action: StreamAction) => void;
}) {
  const [tone, icon, word] = streamState(item);
  const p = item.submission.progress;
  const title = item.title || "Live stream";
  const ended = item.live.ended && ["ready", "finished"].includes(item.status);
  const [drawing, setDrawing] = useState(false);
  const canDraw = Boolean(item.project_id) && item.live.recording && item.live.framing !== "off";
  return <article className="ap-link-row" aria-label={title}>
    <div className="row wrap top">
      <div className="stack grow">
        <h4 className="post-title">{item.project_id ? <a href={`#/project/${item.project_id}`}>{title}</a> : title}</h4>
        {item.detail && <span className="small muted break">{item.detail}</span>}
        {item.live.note && !item.live.finishing && <span className="small muted">{item.live.note}</span>}
        {item.submission.hold_reason && <span className="small bad-text">{item.submission.hold_reason}</span>}
        <p className="small">{item.live.minutes > 0 ? `${plural(Math.round(item.live.minutes), "minute")} recorded`
          : "Nothing recorded yet"} · {plural(item.live.live_clips, "live clip")}
          {p && p.clips_ready > item.live.live_clips && ` · ${plural(p.clips_ready, "clip")} in all`}
          {item.submission.auto_upload && p && <> · {p.posts_uploaded} uploaded · {p.posts_waiting + p.posts_uploading} waiting
            {p.posts_failed > 0 && ` · ${p.posts_failed} need attention`}</>}</p>
        <p className="tiny faint">Added {when(item.submission.created_at || item.added_at, timezone)}
          {item.submission.auto_upload ? ` · YouTube ${item.submission.privacy === "public" ? "Public" : "Private"}`
            : " · Clips stay on this computer"}
          {item.submission.auto_upload && channelNames(item.submission).length > 0
            && ` to ${nameList(channelNames(item.submission))}`}
          {item.submission.split === "turns" && ", taking turns"}
          {[item.live.pick_label, item.live.framing_label].filter(Boolean).map((label) => ` · ${label}`).join("")}
          {ended && canAddAgain(item) && " · Add the link again to record its next stream"}</p>
      </div>
      <Pill tone={tone} icon={icon} className={item.live.recording ? "pulse" : ""}>{word}</Pill>
    </div>
    <div className="row wrap">
      {item.project_id && <a className="btn btn-small" href={`#/project/${item.project_id}`}>View clips</a>}
      {item.submission.auto_upload && p?.posts_failed > 0 && <a className="btn btn-small" href="#/publishing/problems">Review upload issue</a>}
      {item.can_finish && <button type="button" className="btn btn-small" disabled={disabled}
        onClick={() => act("finish")}><Icon name="stop" />Stop recording</button>}
      {item.can_stop_clipping && <button type="button" className="btn btn-small" disabled={disabled}
        onClick={() => act("stop_clipping")}><Icon name="scissors" />Stop clipping</button>}
      {canDraw && !drawing && <button type="button" className="btn btn-small" onClick={() => setDrawing(true)}>
        <Icon name="screen" />Draw the face cam</button>}
      {item.can_retry && <button type="button" className="btn btn-small" disabled={disabled} onClick={() => act("retry")}>Try again</button>}
      {item.can_cancel && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
        onClick={() => act("cancel")}>Cancel stream</button>}
    </div>
    {canDraw && drawing && <LiveFaceCam projectId={item.project_id!} title={title} close={() => setDrawing(false)} />}
  </article>;
}

/** Draw where the streamer's face cam is on a picture from the newest recorded minute. Live clips made from now on
 * put that part of the picture in their split view's cam spot (the stream's own folder, cam.json). */
function LiveFaceCam({ projectId, title, close }: { projectId: string; title: string; close: () => void }) {
  const [src, setSrc] = useState("");
  const [aspect, setAspect] = useState(16 / 9);
  const [box, setBox] = useState<Box>(START);
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setError("");
    const url = submissions.liveFrame(projectId);
    const picture = new Image();
    picture.onload = () => { setAspect(picture.naturalWidth / Math.max(1, picture.naturalHeight)); setSrc(url); };
    picture.onerror = () => setError("No picture from the stream yet. Wait a minute while it records, then press "
      + "New picture.");
    picture.src = url;
  };
  useEffect(() => {
    load();
    submissions.liveFacecam(projectId).then((cam) => {
      if (cam.box) setBox(cam.box);
      setLocked(cam.locked);
    }).catch(() => undefined);
  }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (next: Box | null) => {
    setBusy(true);
    try {
      const cam = await submissions.lockLiveFacecam(projectId, next);
      setLocked(cam.locked);
      if (cam.box) setBox(cam.box);
      toast(next ? "Face cam saved. Clips made from now on put this part of the picture in the cam spot."
        : "ClipForge looks for the face cam by itself again.");
      if (next) close();
    } catch (err) {
      toast(errorText(err), true);
    } finally {
      setBusy(false);
    }
  };

  return <section className="stack" aria-label={`Face cam for ${title}`}>
    <p className="small">Drag a box around the streamer's face cam. Live clips with a split view use it from now on.</p>
    {error ? <Banner tone="info">{error}</Banner>
      : src ? <FaceCamBox image src={src} time={0} aspect={aspect} box={box} onChange={setBox} label="Face cam box" />
        : <Skel style={{ height: 180, maxWidth: 520 }} />}
    <div className="row wrap">
      <button type="button" className="btn btn-small btn-primary" disabled={busy || !src} onClick={() => save(box)}>
        <Icon name="check" />Use this box</button>
      <button type="button" className="btn btn-small" disabled={busy} onClick={load}><Icon name="refresh" />New picture</button>
      {locked && <button type="button" className="btn btn-small btn-quiet" disabled={busy} onClick={() => save(null)}>
        Let ClipForge find it</button>}
      <button type="button" className="btn btn-small btn-quiet" onClick={close}>Close</button>
    </div>
  </section>;
}
