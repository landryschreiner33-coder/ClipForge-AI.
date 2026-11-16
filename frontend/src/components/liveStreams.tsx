import { FormEvent, useId, useState } from "react";
import { errorText } from "../api";
import { ap } from "../autopilot";
import { plural, when } from "../format";
import { LiveStream, submissions } from "../submissions";
import { Banner, ConfirmDialog, Icon, IconName, Pill, Skel, toast, Tone, usePoll } from "./ui";
import { UploadChoice, useUploadChoice } from "./uploadChoice";

const MAX_LINKS = 10;
const isLink = (value: string) => /^https?:\/\/\S+$/i.test(value.trim());
const linesOf = (text: string) => text.split(/\r?\n/).map(line => line.trim()).filter(Boolean);

/**
 * Live streams (#/missions/live): add one or several stream links, each recorded and clipped while it is live, with
 * the same per-input "Make & upload" request as a video. Every stream keeps its own recording, clips and uploads;
 * "Stop recording" finishes what was recorded and keeps everything made so far.
 */
export default function LiveStreams({ timezone, stopped, enabled, gapMinutes, refreshStatus }: {
  timezone: string; stopped: boolean; enabled: boolean; gapMinutes: number; refreshStatus: () => void;
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
    const options = choice.options();
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

  const act = async (item: LiveStream, action: "cancel" | "retry" | "finish") => {
    if (acting) return;
    setActing(item.id);
    try {
      await ap.linkAction(item.id, action);
      toast(action === "finish" ? "Stopping the recording. ClipForge finishes the clips from what was recorded."
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
            when it starts (ClipForge waits up to a day). Login-only and protected streams cannot be recorded.</span>
          {bad.length > 0 && <span className="error-text">Use links starting with https:// or http://
            ({plural(bad.length, "line needs", "lines need")} fixing).</span>}
          {tooMany && <span className="error-text">Add at most {MAX_LINKS} streams at a time.</span>}
        </label>
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
        timezone={timezone} disabled={!!acting} act={action => action === "finish" ? setConfirmStop(item) : act(item, action)} />)}</div>}
    {confirmStop && <ConfirmDialog title="Stop recording this stream?" confirmLabel="Stop recording"
      onClose={() => setConfirmStop(null)} onConfirm={() => act(confirmStop, "finish")}>
      <p>ClipForge stops recording “{confirmStop.title || "this stream"}”, then checks the full recording for
        moments it missed. The clips made so far{confirmStop.submission.auto_upload ? " and their uploads" : ""} stay.
        This cannot be resumed: add the link again to record more.</p>
    </ConfirmDialog>}
  </section>;
}

function streamState(item: LiveStream): [Tone, IconName, string] {
  const live = item.live;
  if (item.status === "canceled" || item.status === "removed") return ["neutral", "x", "Canceled"];
  if (["failed", "inaccessible"].includes(item.status) || item.submission.status === "needs_attention")
    return ["warn", "alert", "Needs attention"];
  if (live.finishing) return ["info", "clock", "Stopping the recording"];
  if (live.recording) return ["info", "dot", "Recording live"];
  if (item.status === "waiting_stream") return ["neutral", "clock", "Waiting for the stream to start"];
  if (item.status === "finding_clips" || item.status === "making_clips" || item.status === "final_check")
    return ["info", "clock", live.ended ? "Checking the full recording" : "Making clips"];
  if (live.ended && ["ready", "finished"].includes(item.status)) return ["good", "check", live.stopped ? "Stopped" : "Ended"];
  if (item.status === "watching_live" || item.status === "waiting") return ["neutral", "clock", "Waiting for its turn"];
  return ["neutral", "clock", item.status_label];
}

function StreamRow({ item, timezone, disabled, act }: {
  item: LiveStream; timezone: string; disabled: boolean; act: (action: "cancel" | "retry" | "finish") => void;
}) {
  const [tone, icon, word] = streamState(item);
  const p = item.submission.progress;
  const title = item.title || "Live stream";
  const ended = item.live.ended && ["ready", "finished"].includes(item.status);
  return <article className="ap-link-row" aria-label={title}>
    <div className="row wrap top">
      <div className="stack grow">
        <h4 className="post-title">{item.project_id ? <a href={`#/project/${item.project_id}`}>{title}</a> : title}</h4>
        {item.detail && <span className="small muted break">{item.detail}</span>}
        {item.submission.hold_reason && <span className="small bad-text">{item.submission.hold_reason}</span>}
        <p className="small">{item.live.minutes > 0 ? `${plural(Math.round(item.live.minutes), "minute")} recorded`
          : "Nothing recorded yet"} · {plural(item.live.live_clips, "live clip")}
          {p && p.clips_ready > item.live.live_clips && ` · ${plural(p.clips_ready, "clip")} in all`}
          {item.submission.auto_upload && p && <> · {p.posts_uploaded} uploaded · {p.posts_waiting + p.posts_uploading} waiting
            {p.posts_failed > 0 && ` · ${p.posts_failed} need attention`}</>}</p>
        <p className="tiny faint">Added {when(item.submission.created_at || item.added_at, timezone)}
          {item.submission.auto_upload ? ` · YouTube ${item.submission.privacy === "public" ? "Public" : "Private"}`
            : " · Clips stay on this computer"}{ended && " · Add the link again for the channel's next stream"}</p>
      </div>
      <Pill tone={tone} icon={icon} className={item.live.recording ? "pulse" : ""}>{word}</Pill>
    </div>
    <div className="row wrap">
      {item.project_id && <a className="btn btn-small" href={`#/project/${item.project_id}`}>View clips</a>}
      {item.submission.auto_upload && p?.posts_failed > 0 && <a className="btn btn-small" href="#/publishing/problems">Review upload issue</a>}
      {item.can_finish && <button type="button" className="btn btn-small" disabled={disabled}
        onClick={() => act("finish")}><Icon name="stop" />Stop recording</button>}
      {item.can_retry && <button type="button" className="btn btn-small" disabled={disabled} onClick={() => act("retry")}>Try again</button>}
      {item.can_cancel && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
        onClick={() => act("cancel")}>Cancel stream</button>}
    </div>
  </article>;
}
