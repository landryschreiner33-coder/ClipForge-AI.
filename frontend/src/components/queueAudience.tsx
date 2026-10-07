import { FormEvent, useId, useState } from "react";
import { errorText } from "../api";
import { office } from "../office/officeApi";
import { Post } from "./postShared";
import { Icon, toast } from "./ui";

/**
 * Who can actually watch an upload, kept apart from whether the bytes arrived. Transfer, visibility, audience setup
 * and analytics are four separate facts (audience.py); a finished upload is never shown as "viewers can watch" until
 * the platform's API or the user confirmed the audience.
 */
export const SETUP_LABEL: Record<string, string> = {
  owner_only_staging: "Uploaded for you only (staging)",
  awaiting_invitations: "Awaiting viewer invitations",
  user_confirmed: "Audience setup confirmed by you",
  api_requested: "Restricted visibility requested",
  api_verified: "Restricted visibility confirmed by the platform",
  manual_handoff: "Ready for manual posting",
};
const TRANSFER: Record<string, string> = {
  queued: "Waiting to upload", uploading: "Uploading", processing: "Processing on the platform", done: "Uploaded",
  action_needed: "Finish in the app", failed: "Failed", cancelled: "Canceled",
};
const VISIBILITY: Record<string, string> = {
  private: "Private", SELF_ONLY: "Only you", FOLLOWER_OF_CREATOR: "Followers", MUTUAL_FOLLOW_FRIENDS: "Friends",
};

export const awaitingInvites = (p: Post) =>
  p.status === "published" && p.publication?.info?.audience?.setup === "awaiting_invitations";

function analyticsWord(setup: string, intent: string): string {
  if (intent === "OWNER_ONLY" || setup === "owner_only_staging") return "Not a viewer test (only you can watch)";
  if (setup === "user_confirmed" || setup === "api_verified") return "Awaiting observations (see the clip's Test "
    + "feedback)";
  return "Awaiting viewer access";
}

/** The four facts of one upload, each in its own words. Shown only once there is an upload record. */
export function AudienceFacts({ p }: { p: Post }) {
  const pub = p.publication;
  if (!pub) return null;
  const a = (pub.info?.audience || {}) as Record<string, string>;
  const returned = pub.privacy || a.returned || "";
  return (
    <dl className="aud-facts">
      <div><dt>Transfer</dt><dd>{TRANSFER[pub.status] || pub.status || "—"}</dd></div>
      <div><dt>Visibility</dt><dd>{returned ? (VISIBILITY[returned] || returned) : "Not reported"}</dd></div>
      <div><dt>Audience</dt><dd>{a.setup ? (SETUP_LABEL[a.setup] || a.setup) : "Not recorded"}</dd></div>
      <div>
        <dt>Analytics</dt>
        <dd>{pub.status === "done" ? analyticsWord(a.setup || "", a.intent || "") : "—"}</dd>
      </div>
    </dl>
  );
}

/** "I've invited my viewers": the user's own confirmation for a private YouTube upload, recorded as such. */
export function ViewersInvitedButton({ p, onDone }: { p: Post; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  if (!awaitingInvites(p) || !p.publication) return null;
  return (
    <button type="button" className="btn btn-small" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        await office.viewersInvited(p.publication!.id);
        toast("Recorded: you invited your viewers");
        onDone();
      } catch (e) {
        toast(errorText(e), true);
      }
      setBusy(false);
    }}><Icon name="check" />I've invited my viewers</button>
  );
}

/** A manual TikTok posting package: the exact checked video, its caption, the steps, then "I posted it". */
export function ManualPackage({ p, onDone }: { p: Post; onDone: () => void }) {
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  if (p.status !== "manual_handoff") return null;
  const caption = [p.description, (p.tags || []).map((t) => (t.startsWith("#") ? t : `#${t}`)).join(" ")]
    .filter(Boolean).join("\n\n");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const url = link.trim();
    if (url && !url.startsWith("https://")) {
      setError("Paste the https:// link of the post, or leave it empty.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await office.manualPosted(p.id, url, "");
      toast("Recorded as posted by you");
      onDone();
    } catch (err) {
      setError(errorText(err));
    }
    setBusy(false);
  };
  return (
    <div className="manual-package">
      <ol className="steps-list small">
        <li>
          <a className="textlink" href={`${p.clip.video_url}${p.clip.video_url.includes("?") ? "&" : "?"}download=1`}
            download>Download the checked video</a>
        </li>
        <li>
          <button type="button" className="btn btn-small btn-quiet" onClick={() => {
            if (!navigator.clipboard) {
              toast("Copying is not available here. Open the post and copy the caption from its text.", true);
              return;
            }
            navigator.clipboard.writeText(caption).then(() => toast("Caption copied"),
              () => toast("The caption could not be copied.", true));
          }}><Icon name="copy" />Copy caption</button>
        </li>
        <li>{p.fix || "Post it on TikTok yourself with Followers or Friends on your private account, never "
          + "Everyone."}</li>
      </ol>
      <form className="row wrap" onSubmit={submit}>
        <label className="small" htmlFor={`${id}-link`}>Link to your post <span className="hint">optional</span></label>
        <input id={`${id}-link`} type="url" inputMode="url" placeholder="https://www.tiktok.com/@you/video/…"
          value={link} onChange={(e) => setLink(e.target.value)} className="grow" />
        <button type="submit" className="btn btn-small btn-primary" disabled={busy}>I posted it</button>
      </form>
      {error && <p className="small bad-text" role="alert">{error}</p>}
    </div>
  );
}
