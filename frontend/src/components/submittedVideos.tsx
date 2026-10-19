import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import { ap } from "../autopilot";
import { plural, when } from "../format";
import { useLeaveGuard } from "../router";
import { SubmissionOptions, SubmittedVideo, submissions } from "../submissions";
import { Banner, Icon, Pill, ProgressBar, Segmented, Skel, toast, Tone, usePoll } from "./ui";
import { YouTubeComments } from "./YouTubeComments";

const ACCEPT = [".mp4", ".mov", ".mkv", ".webm", ".m4v"];
const isLink = (value: string) => /^https?:\/\/\S+$/i.test(value.trim());
const size = (bytes: number) => bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;

/** A source-scoped command. Nothing here changes the approval mode or grants access to earlier clips. */
export default function SubmittedVideos({ timezone, stopped, refreshStatus }: {
  timezone: string; stopped: boolean; refreshStatus: () => void;
}) {
  const { data: setup, error: setupError, refresh: reloadSetup } = usePoll(submissions.setup, [], 30000, () => true);
  const { data, error, refresh, setData } = usePoll(submissions.list, [], 3000, () => true);
  const [inputMode, setInputMode] = useState("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [autoUpload, setAutoUpload] = useState(true);
  const [kids, setKids] = useState("");
  const [basis, setBasis] = useState<SubmissionOptions["reuse_basis"]>("");
  const [statement, setStatement] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  const [notice, setNotice] = useState("");
  const [acting, setActing] = useState("");
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  useLeaveGuard(busy ? { what: "a video still being copied into ClipFoundry" } : null);

  useEffect(() => {
    setAgreed(false);
    setKids("");
  }, [setup?.account_id, setup?.privacy, setup?.audience.group_version]);

  const pick = (chosen?: File) => {
    if (!chosen || busy) return;
    const ext = `.${(chosen.name.split(".").pop() || "").toLowerCase()}`;
    if (!ACCEPT.includes(ext)) {
      setProblem("Choose an MP4, MOV, MKV, WEBM or M4V video.");
      return;
    }
    if (chosen.size > 8 * 1024 ** 3) {
      setProblem("Choose a video smaller than 8 GB.");
      return;
    }
    setFile(chosen);
    setAgreed(false);
    setProblem("");
  };
  const hasInput = inputMode === "file" ? !!file : isLink(url);
  const ready = hasInput && !!setup && !setupError && !stopped && (!autoUpload || (
    setup.can_upload && !!kids && !!basis && (basis !== "legal_exception" || !!statement.trim()) && agreed));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready || !setup || busy) return;
    setBusy(true);
    setProblem("");
    setNotice("");
    const options: SubmissionOptions = {
      auto_upload: autoUpload, account_id: autoUpload ? setup.account_id : "",
      privacy: setup.privacy, made_for_kids: autoUpload ? kids === "yes" : null,
      audience_version: setup.audience.group_version, reuse_basis: autoUpload ? basis : "",
      reuse_statement: autoUpload ? statement.trim() : "", agreed: autoUpload && agreed,
    };
    try {
      if (inputMode === "file") setProgress(0);
      const result = inputMode === "file" && file ? await submissions.file(file, options, setProgress)
        : await submissions.link(url.trim(), options);
      const item = { ...result.item, submission: result.item.submission || result.submission };
      setData([item, ...(data || []).filter(row => row.id !== item.id)]);
      setNotice(result.already_added ? "This video was already added. Its existing progress is shown below."
        : autoUpload ? "Added. ClipFoundry will make clips and upload those that pass the final checks."
          : "Added. ClipFoundry will make clips on this PC without uploading them.");
      if (!result.already_added) {
        setUrl("");
        setFile(null);
        setAgreed(false);
        setBasis("");
        setStatement("");
        setKids("");
      }
      refresh();
      refreshStatus();
    } catch (e) {
      setProblem(errorText(e));
      reloadSetup();
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  const act = async (item: SubmittedVideo, action: "cancel" | "retry") => {
    if (acting || busy) return;
    setActing(item.id);
    try {
      await ap.linkAction(item.id, action);
      toast(action === "cancel" ? "Video processing canceled" : "Video queued for another try");
      refresh();
      refreshStatus();
    } catch (e) {
      setProblem(errorText(e));
    } finally {
      setActing("");
    }
  };

  return <section className="panel submitted-videos" aria-labelledby={`${id}-heading`}>
    <div className="panel-head wrap">
      <div className="stack">
        <span className="kind-label">Your video → finished clips</span>
        <h2 id={`${id}-heading`}>Add a video</h2>
      </div>
      <a className="textlink small" href="#/brain"><Icon name="spark" />Edit Brain guidance</a>
    </div>
    <p className="muted small">Paste one video link or choose a file. ClipFoundry finds strong moments, uses relevant
      supported Brain notes and example preferences, makes vertical clips, checks the finished audio and video, then uploads to YouTube
      when you choose it below. Settings fill any gaps in Brain guidance. No search API key is needed.</p>
    <form className="stack-4" onSubmit={submit}>
      <fieldset className="submitted-form stack-4" disabled={busy}>
        <legend className="sr-only">Video and upload choices</legend>
        <Segmented label="Video input" value={inputMode} onChange={value => { setInputMode(value); setAgreed(false); }}
          options={[{ value: "link", label: "Video link" }, { value: "file", label: "Video file" }]} />
        {inputMode === "link" ? <label className="stack small" htmlFor={`${id}-url`}>
          <span className="strong" id={`${id}-url-label`}>Video link</span>
          <input id={`${id}-url`} type="url" inputMode="url" value={url} placeholder="https://…" autoComplete="off"
            aria-labelledby={`${id}-url-label`}
            aria-invalid={url.trim() !== "" && !isLink(url) ? true : undefined}
            aria-describedby={`${id}-link-help`} onChange={event => { setUrl(event.target.value); setAgreed(false); }} />
          <span className="hint" id={`${id}-link-help`}>A publicly accessible recorded video. Login-only, protected or
            unavailable videos cannot be downloaded.</span>
          {url.trim() !== "" && !isLink(url) && <span className="error-text">Use a link starting with https:// or http://.</span>}
        </label> : <div className={`submitted-drop${drag ? " over" : ""}`}
          onDragOver={event => { event.preventDefault(); if (!busy) setDrag(true); }}
          onDragLeave={() => setDrag(false)} onDrop={event => {
            event.preventDefault(); setDrag(false); pick(event.dataTransfer.files?.[0]);
          }}>
          <Icon name="film" className="lg" />
          <div className="stack grow">
            <b className="break">{file ? file.name : "Drop a video here"}</b>
            <span className="small muted">{file ? size(file.size) : "MP4, MOV, MKV, WEBM or M4V · up to 8 GB"}</span>
          </div>
          <button type="button" className="btn" onClick={() => input.current?.click()}>
            <Icon name="folder" />{file ? "Choose another video" : "Choose a video"}</button>
          <input ref={input} type="file" accept={ACCEPT.join(",")} className="sr-only" tabIndex={-1}
            aria-label="Video file" onChange={event => { pick(event.target.files?.[0]); event.target.value = ""; }} />
        </div>}

        <fieldset className="submitted-mode">
          <legend className="small strong">What happens next</legend>
          <label className="choice"><input type="radio" name={`${id}-mode`} checked={autoUpload}
            onChange={() => { setAutoUpload(true); setAgreed(false); }} />
            <span><b>Make & upload clips</b><span className="hint block">Upload passing clips from this video to the
              YouTube account shown below.</span></span></label>
          <label className="choice"><input type="radio" name={`${id}-mode`} checked={!autoUpload}
            onChange={() => { setAutoUpload(false); setAgreed(false); }} />
            <span><b>Make clips only</b><span className="hint block">Keep the clips on this PC. You can edit, export or
              review them later.</span></span></label>
        </fieldset>

        {autoUpload && <div className="stack-4 submitted-consent">
          {setup === null ? <Skel className="skel-line" /> : <>
            <div className="submitted-destination">
              <div className="stack"><span className="small muted">YouTube account</span>
                <b>{setup.account_name || (setup.connected ? setup.account_id : "Not connected")}</b></div>
              <div className="stack"><span className="small muted">Visibility for these clips</span>
                <b>{setup.privacy === "public" ? "Public · anyone can watch" : `Private · ${setup.audience.label}`}</b>
              </div>
              <a className="textlink small" href="#/settings">Change account or audience<Icon name="chev" className="sm" /></a>
            </div>
            {!setup.can_upload && <Banner tone="warn" title="Finish YouTube setup first">
              {setup.blocker || "Connect YouTube and confirm who may watch new uploads in Settings."}
              <a className="textlink" href="#/settings">Open account settings</a>
            </Banner>}
          </>}
          <fieldset className="stack" role="group" aria-labelledby={`${id}-kids`}>
            <legend className="small strong" id={`${id}-kids`}>Are these clips made for kids?</legend>
            <div className="row wrap">
              <label className="choice"><input type="radio" name={`${id}-kids`} checked={kids === "yes"}
                onChange={() => { setKids("yes"); setAgreed(false); }} />Yes, made for kids</label>
              <label className="choice"><input type="radio" name={`${id}-kids`} checked={kids === "no"}
                onChange={() => { setKids("no"); setAgreed(false); }} />No, not made for kids</label>
            </div>
            <YouTubeComments privacy={setup?.privacy} kids={kids ? kids === "yes" : null} />
          </fieldset>
          <fieldset className="stack">
            <legend className="small strong">Why can you use this video and its audio?</legend>
            <div className="reuse-choices">{setup?.reuse_bases.map(option => <label key={option.id}
              className={`reuse-option${basis === option.id ? " selected" : ""}`}>
              <input type="radio" name={`${id}-basis`} checked={basis === option.id}
                onChange={() => { setBasis(option.id); setAgreed(false); }} />
              <span>{option.label}</span>
            </label>)}</div>
            {basis && <p className="hint">{setup?.reuse_bases.find(option => option.id === basis)?.text}</p>}
            <details className="more" open={basis === "legal_exception" ? true : undefined}>
              <summary><Icon name="chev" className="chev" />{basis === "legal_exception"
                ? "Explain your legal basis (required)" : "Add permission details (optional)"}</summary>
              <label className="stack small more-body" htmlFor={`${id}-statement`}>
                <span>{basis === "legal_exception" ? "Legal basis covering footage, sound, edits and YouTube upload"
                  : "Permission details for this video"}</span>
                <textarea id={`${id}-statement`} rows={2} maxLength={4000} value={statement}
                  required={basis === "legal_exception"}
                  onChange={event => { setStatement(event.target.value); setAgreed(false); }} />
              </label>
            </details>
            <p className="hint">This answer stays with this submitted video and its upload authorization. It is not
              saved in Brain knowledge, and it does not authorize old clips or other videos.</p>
          </fieldset>
          <label className="choice submitted-agreement"><input type="checkbox" checked={agreed}
            onChange={event => setAgreed(event.target.checked)} />
            <span>I checked that I can use this video, its music and other material on the basis above. Make clips from
              this video and automatically upload those that pass the final checks to
              {" "}<b>{setup?.account_name || "the YouTube account above"}</b> as
              {" "}<b>{setup?.privacy === "public" ? "Public" : "Private"}</b>, using my kids answer. No separate approval
              is needed for each new clip from this video.</span></label>
        </div>}
      </fieldset>
      {setupError && <Banner tone="warn" title="Upload setup could not refresh">{setupError}
        <button type="button" className="textlink" onClick={reloadSetup}>Try again</button></Banner>}
      {stopped && <Banner tone="warn" title="Jobs are stopped">Resume jobs above before adding a video.</Banner>}
      {progress !== null && <div className="stack" role="status">
        <ProgressBar value={progress} label="Copying video into ClipFoundry" />
        <span className="small muted">{progress < 1 ? `Copying video: ${Math.round(progress * 100)}%`
          : "Copied. Preparing the video…"}</span>
      </div>}
      <div className="row wrap submitted-actions">
        <span className="hint grow">Adding a video starts processing. Keep ClipFoundry open and the PC awake while it works. Weak or failed clips stay
          off YouTube. <a className="textlink" href="#/create">Open the manual editor workflow</a></span>
        <button type="submit" className="btn btn-primary" disabled={!ready || busy}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name={autoUpload ? "upload" : "scissors"} />}
          {busy ? "Adding video…" : autoUpload ? "Make & upload clips" : "Make clips on this PC"}
        </button>
      </div>
      {notice && <p className="small" role="status">{notice}</p>}
      {problem && <p className="small bad-text" role="alert">{problem}</p>}
    </form>
    <hr className="divider" />
    <div className="panel-head"><h3 id={`${id}-videos`}>Submitted videos</h3>
      <a className="textlink small" href="#/queue/scheduled">See uploads<Icon name="chev" className="sm" /></a></div>
    {error && <p className="small muted" role="status">Could not refresh progress. Last known results are shown.
      <button type="button" className="textlink" onClick={refresh}>Try again</button></p>}
    {data === null ? <Skel className="skel-block" /> : !data.length ? <p className="small muted">
      Your videos and their real creation and upload progress will appear here.</p>
      : <div className="rows" aria-labelledby={`${id}-videos`}>{data.map(item => <SubmittedRow key={item.id}
        item={item} timezone={timezone} disabled={busy || !!acting} act={action => act(item, action)} />)}</div>}
  </section>;
}

function SubmittedRow({ item, timezone, disabled, act }: {
  item: SubmittedVideo; timezone: string; disabled: boolean; act: (action: "cancel" | "retry") => void;
}) {
  const source = item.submission;
  const p = source.progress;
  const labels = { creating: "Making clips", local_ready: "Local clips ready", waiting: "Waiting to upload",
    uploading: "Uploading", uploaded: "Uploaded", needs_attention: "Needs attention" };
  const label = labels[source.status] || item.status_label;
  const tone: Tone = source.status === "needs_attention" ? "warn"
    : ["uploaded", "local_ready"].includes(source.status) ? "good" : source.status === "uploading" ? "info" : "neutral";
  const title = item.title || "Submitted video";
  return <article className="ap-link-row" aria-label={title}>
    <div className="row wrap top">
      <div className="stack grow">
        <h4 className="post-title">{item.project_id ? <a href={`#/project/${item.project_id}`}>{title}</a> : title}</h4>
        <span className="small">{item.status_label}</span>
        {item.detail && <span className="small muted break">{item.detail}</span>}
        {source.hold_reason && <span className="small bad-text">{source.hold_reason}</span>}
        {item.progress > 0 && item.progress < 1 && <ProgressBar value={item.progress}
          label={`${title}: ${item.status_label}`} />}
        {p && <p className="small muted">{plural(p.clips_ready, "clip")} ready
          {source.auto_upload && <> · {p.posts_waiting} waiting · {p.posts_uploading} uploading
            · {p.posts_uploaded} uploaded{p.posts_failed > 0 && ` · ${p.posts_failed} need attention`}</>}</p>}
        <p className="tiny faint">Added {when(source.created_at || item.added_at, timezone)}
          {source.auto_upload ? ` · YouTube ${source.privacy === "public" ? "Public" : "Private"}` : " · Stays on this PC"}</p>
      </div>
      <Pill tone={tone}>{label}</Pill>
    </div>
    <div className="row wrap">
      {item.project_id && <a className="btn btn-small" href={`#/project/${item.project_id}`}>View clips</a>}
      {source.auto_upload && p?.posts_failed > 0 && <a className="btn btn-small" href="#/queue/problems">Review upload issue</a>}
      {item.can_retry && <button type="button" className="btn btn-small" disabled={disabled} onClick={() => act("retry")}>Retry video</button>}
      {item.can_cancel && <button type="button" className="btn btn-small btn-quiet" disabled={disabled}
        onClick={() => act("cancel")}>Cancel video</button>}
    </div>
  </article>;
}
