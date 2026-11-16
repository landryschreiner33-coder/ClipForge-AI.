import { useEffect, useState } from "react";
import { SubmissionOptions, SubmissionSetup } from "../submissions";
import { Banner, Icon, Skel } from "./ui";
import { YouTubeComments } from "./YouTubeComments";

/**
 * "What happens next" for a video or live stream you add: make clips only, or make and upload them under one
 * per-input request (account, visibility, the made-for-kids answer and why you may use it). The same request covers
 * each added video or stream on its own; nothing here approves older clips or other inputs.
 */
export function useUploadChoice(setup: SubmissionSetup | null) {
  const [autoUpload, setAutoUpload] = useState(true);
  const [kids, setKids] = useState("");
  const [basis, setBasis] = useState<SubmissionOptions["reuse_basis"]>("");
  const [statement, setStatement] = useState("");
  const [agreed, setAgreed] = useState(false);

  useEffect(() => {
    setAgreed(false);
    setKids("");
  }, [setup?.account_id, setup?.privacy, setup?.audience.group_version]);

  const complete = !autoUpload || (!!setup?.can_upload && !!kids && !!basis &&
    (basis !== "legal_exception" || !!statement.trim()) && agreed);
  const options = (): SubmissionOptions => ({
    auto_upload: autoUpload, account_id: autoUpload && setup ? setup.account_id : "",
    privacy: setup?.privacy || "private", made_for_kids: autoUpload ? kids === "yes" : null,
    audience_version: setup?.audience.group_version || 0, reuse_basis: autoUpload ? basis : "",
    reuse_statement: autoUpload ? statement.trim() : "", agreed: autoUpload && agreed,
  });
  const reset = () => {
    setAgreed(false);
    setBasis("");
    setStatement("");
    setKids("");
  };
  return { autoUpload, setAutoUpload, kids, setKids, basis, setBasis, statement, setStatement, agreed, setAgreed,
    complete, options, reset };
}

export type UploadChoiceState = ReturnType<typeof useUploadChoice>;

const WORDS = {
  video: {
    upload: "Upload passing clips from this video to the YouTube account shown below.",
    local: "Keep the clips on this PC. You can edit, export or review them later.",
    why: "Why can you use this video and its audio?",
    details: "Permission details for this video",
    stays: "This answer stays with this submitted video and its upload authorization. It is not saved in Brain "
      + "knowledge, and it does not authorize old clips or other videos.",
  },
  stream: {
    upload: "Upload passing clips while the stream is live, and from the full recording after it ends, to the "
      + "YouTube account shown below.",
    local: "Keep the clips on this computer. You can edit, export or review them later.",
    why: "Why can you use these streams and their audio?",
    details: "Permission details for these streams",
    stays: "This answer is saved with each stream you add here and its upload authorization. It is not saved in "
      + "Brain knowledge, and it does not authorize old clips, other videos or the channel's later streams.",
  },
};

export function UploadChoice({ choice, setup, id, what, count = 1 }: {
  choice: UploadChoiceState; setup: SubmissionSetup | null; id: string; what: "video" | "stream"; count?: number;
}) {
  const { autoUpload, setAutoUpload, kids, setKids, basis, setBasis, statement, setStatement, agreed, setAgreed } = choice;
  const words = WORDS[what];
  const account = <b>{setup?.account_name || "the YouTube account above"}</b>;
  const visibility = <b>{setup?.privacy === "public" ? "Public" : "Private"}</b>;
  const these = what === "video" ? "this video" : count > 1 ? "these streams" : "this stream";
  return <>
    <fieldset className="submitted-mode">
      <legend className="small strong">What happens next</legend>
      <label className="choice"><input type="radio" name={`${id}-mode`} checked={autoUpload}
        onChange={() => { setAutoUpload(true); setAgreed(false); }} />
        <span><b>Make & upload clips</b><span className="hint block">{words.upload}</span></span></label>
      <label className="choice"><input type="radio" name={`${id}-mode`} checked={!autoUpload}
        onChange={() => { setAutoUpload(false); setAgreed(false); }} />
        <span><b>Make clips only</b><span className="hint block">{words.local}</span></span></label>
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
          {setup.blocker || "Connect YouTube and confirm who may watch new uploads in Settings."}{" "}
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
        <legend className="small strong">{words.why}</legend>
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
              : words.details}</span>
            <textarea id={`${id}-statement`} rows={2} maxLength={4000} value={statement}
              required={basis === "legal_exception"}
              onChange={event => { setStatement(event.target.value); setAgreed(false); }} />
          </label>
        </details>
        <p className="hint">{words.stays}</p>
      </fieldset>
      <label className="choice submitted-agreement"><input type="checkbox" checked={agreed}
        onChange={event => setAgreed(event.target.checked)} />
        {what === "video" ? <span>I checked that I can use this video, its music and other material on the basis
          above. Make clips from this video and automatically upload those that pass the final checks to
          {" "}{account} as {visibility}, using my kids answer. No separate approval is needed for each new clip
          from this video.</span>
          : <span>I checked that I can use {these}, {count > 1 ? "their" : "its"} music and other material on the
            basis above. Record {count > 1 ? "each stream" : "it"} while it is live, make clips, and automatically
            upload those that pass the final checks to {account} as {visibility}, using my kids answer: during the
            stream and from the full recording after it ends. No separate approval is needed for each new clip
            from {these}.</span>}</label>
    </div>}
  </>;
}
