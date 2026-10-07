import { ReactNode, useId, useState } from "react";
import { req } from "../api";
import { ap, ScheduledItem } from "../autopilot";
import { at, when } from "../format";
import { ConfirmDialog, Icon, IconName, PLATFORM_LABEL, TextPromptDialog, Tone, toast } from "./ui";

/**
 * Posts (one clip on one platform at one time): loading them, their exact status words, and the dialogs that change
 * them. Shared by Posts, Post review and Prepare post. Every dialog says what will happen before anything changes.
 */

// The list API returns a few more fields than ScheduledItem declares (autopilot/routes.py _public_item).
export type Post = Omit<ScheduledItem, "approval" | "clip" | "publication"> & {
  approval: ScheduledItem["approval"] & { scheme?: number; video_sha256?: string };
  clip: ScheduledItem["clip"] & { version_id?: string };
  publication: (NonNullable<ScheduledItem["publication"]> & { remote_id?: string }) | null;
};
type ListResponse = {
  items: Post[]; view: string; timezone: string; auto_publish: boolean; counts: Record<string, number>;
};
export type PostList = { items: Post[]; timezone: string; autoPublish: boolean; capped: boolean };

const LIMIT = 500;

/**
 * Every post: the active ones (ordered by time) and the finished ones (newest first). Together the two views cover
 * every status. Finished posts beyond the newest 500 are not loaded, and the page says so.
 */
export async function loadPosts(): Promise<PostList> {
  const [active, done] = await Promise.all([
    req<ListResponse>("GET", `/api/autopilot/scheduled?view=upcoming&limit=${LIMIT}`),
    req<ListResponse>("GET", `/api/autopilot/scheduled?view=history&limit=${LIMIT}`),
  ]);
  const seen = new Set<string>();
  const items = [...active.items, ...done.items].filter((p) => !seen.has(p.id) && !!seen.add(p.id));
  return { items, timezone: active.timezone, autoPublish: active.auto_publish, capped: done.items.length >= LIMIT };
}

/** One post (the post page), however old; the same shape as a list of one. A post that does not exist is a 404. */
export async function loadPost(id: string): Promise<PostList> {
  try {
    const r = await req<{ item: Post; timezone: string; auto_publish: boolean }>(
      "GET", `/api/autopilot/scheduled/${encodeURIComponent(id)}`);
    return { items: [r.item], timezone: r.timezone, autoPublish: r.auto_publish, capped: false };
  } catch (e) {
    // A post that no longer exists (removed with its clip) gets its own page, not a loading error.
    if ((e as Error).message !== "Scheduled post not found") throw e;
    return { items: [], timezone: "", autoPublish: false, capped: false };
  }
}

const nowS = () => Date.now() / 1000;

/** Uploaded early to YouTube, which publishes it at its time (even if this PC is off by then). */
export const onPlatform = (p: Post) => p.status === "published" && !!p.planned_at && p.planned_at > nowS();

/** A TikTok draft waiting in the TikTok app (not a missing account or a refused setting). */
export const inInbox = (p: Post) => p.status === "action_needed" && p.publication?.status === "action_needed";

/** An approved post whose OK no longer covers the file that would be uploaded (APPROVAL_SCHEME 2: the file's hash). */
export const okOutdated = (p: Post) => p.status === "approved" && !p.approval_valid;

/** Which Posts tab a post belongs to. */
export const VIEW_OF: Record<string, (p: Post) => boolean> = {
  review: (p) => p.status === "awaiting_approval" || okOutdated(p),
  scheduled: (p) => (p.status === "approved" && !okOutdated(p)) || p.status === "publishing" || onPlatform(p),
  published: (p) => p.status === "published" && !onPlatform(p),
  history: (p) => (p.status === "published" && !onPlatform(p)) || p.status === "canceled" || p.status === "replaced",
  problems: (p) => ["reconciling", "failed", "blocked", "action_needed"].includes(p.status),
  manual: (p) => p.status === "manual_handoff",
};
export const VIEW_NAME: Record<string, string> = {
  review: "Needs review", scheduled: "Scheduled", published: "Published", history: "Published", problems: "Problems",
  manual: "Post yourself",
};
export const viewOf = (p: Post) =>
  ["review", "problems", "manual", "scheduled", "published", "history"].find((v) => VIEW_OF[v](p)) || "review";

/**
 * Why a post needs your OK again, from what the API reports: an approved post with `approval_valid: false` (the video
 * or its text no longer match the approval's hash), or a post the scheduler or publisher sent back to review with the
 * note "Needs a new approval: <reason>" and the audit event "approval_invalidated" (which keeps the approved file's
 * SHA-256). When the approved file's SHA-256 differs from the file the final check last saw, the video changed.
 */
export function newOkReason(p: Post): { word: string; detail: string } | null {
  const current = p.quality?.sha256 || "";
  if (okOutdated(p)) {
    if (p.approval?.scheme !== 2) return OLD_SCHEME;
    return changed(p.approval?.video_sha256 || "", current);
  }
  if (p.status !== "awaiting_approval") return null;
  const last = [...(p.audit || [])].reverse()
    .find((a) => ["approved", "approval_invalidated", "edited"].includes(a.event)) as
    (Post["audit"][number] & { approved_sha256?: string }) | undefined;
  const why = last?.event === "approval_invalidated" ? `${last.detail} ${p.status_note}` : p.status_note || "";
  if (last?.event === "edited" && /approve it again/i.test(p.status_note || "")) {
    return {
      word: "Needs your OK again: you edited it",
      detail: "You changed the text after approving it, so it needs your OK again.",
    };
  }
  if (/changed after approval/i.test(why)) return changed(last?.approved_sha256 || "", current);
  if (/missing or cannot be read/i.test(why)) {
    return {
      word: "Needs a new OK: the video file can't be read",
      detail: "The video file was missing or couldn't be read when it was due, so your OK no longer covers it. Open " +
        "the clip, render it again if needed, then approve the post again.",
    };
  }
  if (/before ClipFoundry checked the exact video file/i.test(why)) return OLD_SCHEME;
  if (/automatic.publishing/i.test(why)) {
    return {
      word: "Needs your OK: automatic publishing changed",
      detail: "Your automatic-publishing permission approved it, but that permission was turned off or changed. It " +
        "needs your own OK now.",
    };
  }
  return null;
}
function changed(approvedSha: string, currentSha: string): { word: string; detail: string } {
  if (approvedSha && currentSha && approvedSha !== currentSha) {
    return {
      word: "Needs a new OK: the video changed",
      detail: "The video changed after you approved it (the clip was made again), so it needs your OK again. Your " +
        "earlier OK covered the old file only.",
    };
  }
  return {
    word: "Needs a new OK: it changed after your OK",
    detail: "The video or its text changed after you approved it, or the video file can't be read right now. Your " +
      "earlier OK covered what you saw then only, so it needs your OK again.",
  };
}
const OLD_SCHEME = {
  word: "Needs a new OK: approved before exact-file checks",
  detail: "You approved it with an older version of ClipFoundry, which didn't record the exact video file. Approve " +
    "it again so your OK covers this exact file.",
};

export type StatusWord = { tone: Tone; word: string; icon: IconName };

/** The exact status words (design/ui-redesign/prototype/app.js postStatus): never softened. */
export function postStatus(p: Post): StatusWord {
  const again = newOkReason(p);
  switch (p.status) {
    case "awaiting_approval":
      return again ? { tone: "warn", word: again.word, icon: "alert" }
        : { tone: "warn", word: "Needs your OK", icon: "clock" };
    case "approved":
      if (again) return { tone: "warn", word: again.word, icon: "alert" };
      return p.approval?.by === "automatic" ? { tone: "good", word: "Approved automatically", icon: "shield" }
        : { tone: "good", word: "Approved by you", icon: "check" };
    case "publishing": return { tone: "info", word: "Uploading now", icon: "upload" };
    case "published": {
      // An upload is not the same as reaching the chosen viewers: say which audience step it is at.
      const setup = p.publication?.info?.audience?.setup;
      if (setup === "awaiting_invitations") return { tone: "warn", word: "Awaiting viewer invitations", icon: "user" };
      if (setup === "owner_only_staging") return { tone: "info", word: "Uploaded for you only", icon: "shield" };
      return onPlatform(p) ? { tone: "info", word: "Uploaded, waiting for its time", icon: "clock" }
        : { tone: "good", word: "Published", icon: "check" };
    }
    case "reconciling": return { tone: "warn", word: "Upload not confirmed", icon: "question" };
    case "failed": return { tone: "bad", word: "Failed", icon: "alert" };
    case "blocked":
      return blockedByCheck(p) ? { tone: "bad", word: "Blocked by the final check", icon: "shield" }
        : { tone: "bad", word: "Blocked", icon: "shield" };
    case "action_needed":
      return inInbox(p) ? { tone: "info", word: "Finish in the TikTok app", icon: "info" }
        : { tone: "bad", word: "Action needed", icon: "alert" };
    case "canceled": return { tone: "neutral", word: "Canceled", icon: "x" };
    case "replaced": return { tone: "neutral", word: "Replaced by a stronger clip", icon: "refresh" };
    case "manual_handoff": return { tone: "info", word: "Manual posting package", icon: "upload" };
    default: return { tone: "neutral", word: p.status, icon: "info" };
  }
}

/** Blocked by the final quality check of the file (audit event "quality"), not by the rights check. */
export const blockedByCheck = (p: Post) =>
  [...(p.audit || [])].reverse().find((a) => a.event === "quality" || a.event === "blocked")?.event === "quality";

/** The one main action of a row (it opens the post's page). */
export function mainAction(p: Post): string {
  if (p.status === "awaiting_approval" || okOutdated(p)) return "Review";
  if (p.status === "reconciling") return "Resolve";
  if (p.status === "failed") return "See what to do";
  if (p.status === "blocked") return "See why";
  if (inInbox(p)) return "Link the post";
  if (p.status === "action_needed") return "See what to do";
  return "Open";
}

/** "CDT": the zone's short name at that moment (daylight saving changes it). */
export function zoneAbbr(ts: number | null | undefined, tz?: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", { timeZone: tz || undefined, timeZoneName: "short" })
      .formatToParts(ts ? new Date(ts * 1000) : new Date()).find((x) => x.type === "timeZoneName")?.value || "";
  } catch {
    return "";
  }
}
/** "Today, 5:25 PM CDT", or why there is no time yet. */
export const timeLabel = (ts: number | null | undefined, tz?: string) =>
  ts ? `${when(ts, tz)} ${zoneAbbr(ts, tz)}`.trim() : "Time not chosen yet";
/** "today at 5:25 PM CDT", for a sentence. */
export const atLabel = (ts: number | null | undefined, tz?: string) =>
  ts ? `${at(ts, tz)} ${zoneAbbr(ts, tz)}`.trim() : "at the next free time";

export const TIKTOK_PRIVACY: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers",
  SELF_ONLY: "Only me",
};
export function privacyLabel(platform: string, privacy: string): string {
  if (!privacy) return platform === "tiktok" ? "Chosen in the TikTok app" : "Not chosen yet";
  if (platform === "tiktok") return TIKTOK_PRIVACY[privacy] || privacy;
  return privacy[0].toUpperCase() + privacy.slice(1);
}

/** The final check of the exact file, in a few words, for a row. */
export function checkSummary(p: Post): string {
  const q = p.quality;
  if (!q) return "not done yet";
  if (q.status === "failed") return "failed";
  if (q.text_status === "failed") return "the text needs a fix";
  const n = q.warnings.length;
  return n ? `passed, ${n} ${n === 1 ? "warning" : "warnings"}` : "passed";
}

// ------------------------------------------------------------------ dialogs that change a post
export type PostAction = "cancel" | "retry" | "publish-now" | "resolve-yes" | "resolve-no" | "link" | "reschedule";

/**
 * One dialog per action. Each says exactly what will happen, then calls the API; an error keeps the dialog open
 * with the reason. `onDone` receives the post as the API returns it.
 */
export function PostActionDialog({ action, post: p, tz, account, onClose, onDone }: {
  action: PostAction; post: Post; tz?: string; account?: string; onClose: () => void; onDone: (p: Post) => void;
}) {
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const done = (msg: string) => (out: ScheduledItem) => {
    toast(msg);
    onDone(out as Post);
  };
  if (action === "cancel") {
    return (
      <ConfirmDialog title={`Cancel this ${name} post?`} confirmLabel="Cancel post" cancelLabel="Keep the post" danger
        onClose={onClose}
        onConfirm={() => ap.cancel(p.id).then(done("Post canceled. Nothing was posted."))}>
        <p className="muted">It won't be posted. The clip stays in your Library, and you can plan it again later.</p>
      </ConfirmDialog>
    );
  }
  if (action === "publish-now") {
    return (
      <ConfirmDialog title={`Publish to ${name} now?`} confirmLabel="Publish now" cancelLabel="Wait for its time"
        onClose={onClose}
        onConfirm={() => ap.publishNow(p.id).then(done(`Uploading to ${name} now`))}>
        <dl className="kv">
          <dt>Account</dt><dd>{account || name}</dd>
          <dt>Who can see it</dt><dd>{privacyLabel(p.platform, p.privacy)}</dd>
          <dt>When</dt><dd>Right away, instead of {atLabel(p.planned_at, tz)}</dd>
        </dl>
        <div className="consequence">
          <span>
            The upload starts as soon as you confirm. ClipFoundry can't take it back afterwards; you would remove it on
            {" "}{name}.
          </span>
        </div>
      </ConfirmDialog>
    );
  }
  if (action === "retry") return <RetryDialog p={p} name={name} onClose={onClose} done={done} />;
  if (action === "resolve-yes") {
    return (
      <TextPromptDialog title={`Where is the video on ${name}?`} label="Link of the video"
        confirmLabel="Mark as published"
        placeholder={p.platform === "youtube" ? "https://youtube.com/shorts/…"
          : "https://www.tiktok.com/@…/video/…"}
        onClose={onClose}
        onSubmit={(url) => ap.resolve(p.id, true, url).then(done("Marked as published. It won't be uploaded again."))}>
        <p className="small muted">
          ClipFoundry marks it as published, reads its real numbers from {name}, and never uploads it again.
        </p>
      </TextPromptDialog>
    );
  }
  if (action === "resolve-no") {
    return (
      <ConfirmDialog title="Upload it again?" confirmLabel="I checked: upload again" danger onClose={onClose}
        onConfirm={() => ap.resolve(p.id, false).then(done("It gets a new time. Nothing was uploaded now."))}>
        <p className="muted">
          Only do this if you checked {p.platform === "youtube" ? "YouTube Studio" : "your TikTok profile"} and the
          video is <b>not</b> there. Otherwise it would be posted twice.
        </p>
        <p className="small muted">
          It gets a new time. If your OK still covers this exact video and text, it's uploaded then; otherwise it waits
          for your OK.
        </p>
      </ConfirmDialog>
    );
  }
  if (action === "link") {
    return (
      <TextPromptDialog title="Link the post you made in TikTok" label="Link of the post" confirmLabel="Save link"
        placeholder="https://www.tiktok.com/@…/video/…" onClose={onClose}
        onSubmit={(url) => ap.link(p.id, url).then(done("Linked. Its real numbers are read from TikTok."))}>
        <p className="small muted">
          Paste the link of the post you finished in the TikTok app. ClipFoundry marks it as published and reads its
          real numbers from TikTok.
        </p>
      </TextPromptDialog>
    );
  }
  return <RescheduleDialog p={p} tz={tz} onClose={onClose} done={done} />;
}

function RetryDialog({ p, name, onClose, done }: {
  p: Post; name: string; onClose: () => void; done: (msg: string) => (out: ScheduledItem) => void;
}) {
  const later = "It gets a new time within your posting hours. If your OK still covers this exact video and text, " +
    "it's uploaded then without asking again; otherwise it waits for your OK.";
  let title = "Try again?";
  let label = "Try again";
  let body: ReactNode = <p className="muted">{later}</p>;
  if (p.status === "canceled") {
    title = "Plan this post again?";
    label = "Plan it again";
  } else if (p.status === "blocked") {
    body = (
      <>
        <p className="muted">Do this after you fixed the clip (for example, trimmed it and rendered it again).</p>
        <p className="small muted">The file is checked again before it can go out. {later}</p>
      </>
    );
  } else if (inInbox(p)) {
    title = "Send a new draft to TikTok?";
    label = "Send a new draft";
    body = (
      <>
        <p className="muted">
          Only do this if you did <b>not</b> post the draft that is already in your TikTok inbox. If you posted it, link
          it instead; otherwise the video could be posted twice.
        </p>
        <p className="small muted">{later}</p>
      </>
    );
  } else if (p.status === "action_needed") {
    body = (
      <>
        <p className="muted">
          Do this after you fixed what is described on the post (for example, connected {name} again).
        </p>
        <p className="small muted">{later}</p>
      </>
    );
  }
  return (
    <ConfirmDialog title={title} confirmLabel={label} danger={inInbox(p)} onClose={onClose}
      onConfirm={() => ap.retry(p.id).then(done("It will get a new time. Nothing was uploaded now."))}>
      {body}
    </ConfirmDialog>
  );
}

const pad = (n: number) => String(n).padStart(2, "0");
const localValue = (ts: number) => {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

function RescheduleDialog({ p, tz, onClose, done }: {
  p: Post; tz?: string; onClose: () => void; done: (msg: string) => (out: ScheduledItem) => void;
}) {
  const id = useId();
  const [value, setValue] = useState(p.planned_at ? localValue(p.planned_at) : "");
  const here = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const ts = value ? new Date(value).getTime() / 1000 : 0;
  const tooSoon = !!ts && ts < nowS() + 120;
  return (
    <ConfirmDialog title="Change the time" confirmLabel="Save the new time" disabled={!ts || tooSoon} onClose={onClose}
      onConfirm={() => ap.reschedule(p.id, ts).then(done(`Moved to ${timeLabel(ts, tz)}`))}>
      <div className="field">
        <label htmlFor={id}>New time</label>
        <input id={id} type="datetime-local" value={value} data-autofocus onChange={(e) => setValue(e.target.value)}
          aria-invalid={tooSoon || undefined} aria-describedby={`${id}-hint`} />
        <span className="hint" id={`${id}-hint`}>
          {here && tz && here !== tz ? `You pick the time in this computer's time zone (${here}). ` : ""}
          {ts ? `That is ${timeLabel(ts, tz)}.` : ""}
        </span>
        {tooSoon && (
          <span className="error-text">
            <Icon name="alert" className="sm" />Choose a time at least two minutes from now.
          </span>
        )}
      </div>
      <p className="small muted">
        {p.status === "approved" ? "Your OK is kept: only the time changes. " : ""}
        Posts on the same platform need some time between them, so a time too close to another post is refused.
      </p>
    </ConfirmDialog>
  );
}
