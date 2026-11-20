import { useEffect, useMemo, useState } from "react";
import type { Connection } from "../studio";
import { channelRows, SubmissionOptions, SubmissionSetup } from "../submissions";
import { accountName, ChannelPicker, nameList } from "./channelPicker";
import { Banner, Icon, Skel } from "./ui";
import { YouTubeComments } from "./YouTubeComments";

/**
 * "What happens next" for a video or live stream you add: make clips only, or make and upload them under one
 * per-input request (the YouTube channels, visibility, the made-for-kids answer and why you may use it). The same
 * request covers each added video or stream on its own; nothing here approves older clips or other inputs.
 */
export function useUploadChoice(setup: SubmissionSetup | null) {
  const [autoUpload, setAutoUpload] = useState(true);
  const [kids, setKids] = useState("");
  const [basis, setBasis] = useState<SubmissionOptions["reuse_basis"]>("");
  const [statement, setStatement] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [channelIds, setChannelIds] = useState<string[]>([]);
  const [share, setShare] = useState<"each" | "turns">("each");
  const rows = useMemo(() => channelRows(setup), [setup]);
  // The chosen channels in the order they were ticked; one that left the list is never sent.
  const chosen = channelIds.map((cid) => rows.find((r) => r.id === cid)).filter((r): r is Connection => !!r);

  useEffect(() => {
    setAgreed(false);
    setKids("");
  }, [setup?.account_id, setup?.privacy, setup?.audience.group_version]);

  /** A different set of channels is a different request: it needs a fresh confirmation. */
  const setChannels = (ids: string[]) => {
    setChannelIds(ids);
    setAgreed(false);
  };
  /** Taking turns only means something with two or more channels; it changes what is agreed to. */
  const turns = autoUpload && chosen.length > 1 && share === "turns";
  const setSplit = (value: "each" | "turns") => {
    setShare(value);
    setAgreed(false);
  };
  const complete = !autoUpload || (!!setup?.can_upload && chosen.length > 0 && !!kids && !!basis &&
    (basis !== "legal_exception" || !!statement.trim()) && agreed);
  const options = (): SubmissionOptions => {
    const connections = autoUpload ? chosen.map((c) => ({ id: c.id, account_id: c.account_id })) : [];
    return {
      auto_upload: autoUpload, account_id: connections[0]?.account_id || "", connections,
      privacy: setup?.privacy || "private", made_for_kids: autoUpload ? kids === "yes" : null,
      audience_version: setup?.audience.group_version || 0, reuse_basis: autoUpload ? basis : "",
      reuse_statement: autoUpload ? statement.trim() : "", agreed: autoUpload && agreed,
      ...(turns ? { split: "turns" as const } : {}),
    };
  };
  const reset = () => {
    setAgreed(false);
    setBasis("");
    setStatement("");
    setKids("");
  };
  return { autoUpload, setAutoUpload, kids, setKids, basis, setBasis, statement, setStatement, agreed, setAgreed,
    rows, channelIds, chosen, setChannels, share, setSplit, turns, complete, options, reset };
}

export type UploadChoiceState = ReturnType<typeof useUploadChoice>;

const WORDS = {
  video: {
    upload: "Upload passing clips from this video to the YouTube channels you tick below.",
    local: "Keep the clips on this PC. You can edit, export or review them later.",
    why: "Why can you use this video and its audio?",
    details: "Permission details for this video",
    stays: "This answer stays with this submitted video and its upload authorization. It is not saved in Brain "
      + "knowledge, and it does not authorize old clips or other videos.",
  },
  stream: {
    upload: "Upload passing clips while the stream is live, and from the full recording after it ends, to the "
      + "YouTube channels you tick below.",
    local: "Keep the clips on this computer. You can edit, export or review them later.",
    why: "Why can you use these streams and their audio?",
    details: "Permission details for these streams",
    stays: "This answer is saved with each stream you add here and its upload authorization. It is not saved in "
      + "Brain knowledge, and it does not authorize old clips, other videos or the channel's later streams.",
  },
};

/** The statement the owner agrees to: with several channels ticked it says the permission covers each of them. */
function basisText(setup: SubmissionSetup | null, basis: string, channels: number): string {
  const option = setup?.reuse_bases.find((o) => o.id === basis);
  return (channels > 1 && option?.text_many) || option?.text || "";
}

export function UploadChoice({ choice, setup, id, what, count = 1 }: {
  choice: UploadChoiceState; setup: SubmissionSetup | null; id: string; what: "video" | "stream"; count?: number;
}) {
  const { autoUpload, setAutoUpload, kids, setKids, basis, setBasis, statement, setStatement, agreed, setAgreed,
    rows, channelIds, chosen, setChannels, share, setSplit, turns } = choice;
  const words = WORDS[what];
  const account = <>{<b>{nameList(chosen.map(accountName)) || "the YouTube channels you tick above"}</b>}
    {turns && " (each clip to one of them, taking turns)"}</>;
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
        <ChannelPicker platforms={["youtube"]} rows={rows} value={channelIds} idPrefix={`${id}-channels`}
          legend="YouTube channels to upload to" onChange={(ids) => setChannels(ids)} />
        {rows.length > 0 && !chosen.length && <p className="small warn-text">Tick at least one YouTube channel.</p>}
        {chosen.length > 1 && <fieldset className="stack" role="group" aria-labelledby={`${id}-share`}>
          <legend className="small strong" id={`${id}-share`}>How the clips are shared between these channels</legend>
          <label className="choice"><input type="radio" name={`${id}-share`} checked={share === "each"}
            onChange={() => setSplit("each")} />
            <span><b>Every channel gets every clip</b>
              <span className="hint block">Each clip is uploaded to all {chosen.length} channels.</span></span></label>
          <label className="choice"><input type="radio" name={`${id}-share`} checked={share === "turns"}
            onChange={() => setSplit("turns")} />
            <span><b>Split the clips between the channels</b>
              <span className="hint block">Each clip is uploaded to one channel only. The channels take turns, so
                they end up with about the same number of clips, and no clip appears on two of them.</span>
            </span></label>
        </fieldset>}
        <div className="submitted-destination">
          <div className="stack"><span className="small muted">Visibility for these clips</span>
            <b>{setup.privacy === "public" ? "Public · anyone can watch" : `Private · ${setup.audience.label}`}</b>
          </div>
          <div className="row wrap">
            <a className="textlink small" href="#/settings/integrations">Change audience
              <Icon name="chev" className="sm" /></a>
            <a className="textlink small" href="#/accounts">Manage channels<Icon name="chev" className="sm" /></a>
          </div>
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
        {basis && <p className="hint">{basisText(setup, basis, chosen.length)}</p>}
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
