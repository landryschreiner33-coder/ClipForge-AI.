import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { api, ClipVersion, errorText, fmtTime, PlatformAccount, Publication, TikTokCreator } from "../api";
import { ap, ScheduledItem } from "../autopilot";
import { plural, when } from "../format";
import { useLeaveGuard } from "../router";
import { useStatus } from "../status";
import {
  atLabel, blockedByCheck, inInbox, loadPost, newOkReason, okOutdated, onPlatform, Post, PostAction,
  PostActionDialog, postStatus, privacyLabel, TIKTOK_PRIVACY, timeLabel, VIEW_NAME, viewOf,
} from "../components/postShared";
import { PublicationStats } from "../components/stats";
import "./posts.css";
import {
  Banner, ConfirmDialog, Disclosure, EmptyState, Icon, LoadingPage, PageHead, Pill, PLATFORM_LABEL, toast,
  usePoll,
} from "../components/ui";

type Kids = "" | "no" | "yes";
type Form = {
  title: string; text: string; tags: string; privacy: string; kids: Kids; mode: "direct" | "inbox" | "manual";
  comment: boolean; duet: boolean; stitch: boolean; disclose: boolean; brandOrganic: boolean; brandContent: boolean;
};
const LABELS: Record<keyof Form, string> = {
  title: "Title", text: "Text", tags: "Tags", privacy: "Who can see it", kids: "Made for kids", mode: "How to post",
  comment: "Comments", duet: "Duet", stitch: "Stitch", disclose: "Commercial content", brandOrganic: "Your brand",
  brandContent: "Branded content",
};
// The edit endpoint stores these; the others are part of the approval (they are saved when you approve).
const SAVED_BY_EDIT: (keyof Form)[] = ["title", "text", "tags", "privacy"];

const tagList = (s: string) => s.split(/[\s,]+/).filter(Boolean).map((t) => t.replace(/^#/, ""));
const CLEARED_RIGHTS = ["OWNED", "LICENSED", "ALLOWLISTED", "CREATIVE_COMMONS", "PUBLIC_DOMAIN"];
// TikTok's own pages its posting rules ask apps to link (the UX guidelines of the Content Posting API).
const BC_POLICY = "https://www.tiktok.com/legal/page/global/bc-policy/en";
const MUSIC_POLICY = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en";

function formOf(p: Post): Form {
  const o = p.options || {};
  const yt = p.platform === "youtube";
  return {
    title: p.title || "", text: p.description || "", tags: (p.tags || []).join(" "),
    privacy: yt ? "private" : p.privacy || "",  // YouTube: Private only (the selected-audience policy)
    kids: o.made_for_kids === false ? "no" : o.made_for_kids === true ? "yes" : "",
    mode: o.mode === "inbox" || o.mode === "manual" ? o.mode : "direct",
    comment: !!o.allow_comment, duet: !!o.allow_duet, stitch: !!o.allow_stitch,
    disclose: !!o.disclose, brandOrganic: !!o.brand_organic, brandContent: !!o.brand_content,
  };
}
const serverKey = (p: Post) =>
  JSON.stringify([p.status, p.title, p.description, p.tags, p.privacy, p.options, p.approval?.hash || ""]);

/**
 * One post, in full: the exact file that will be posted, its status (with the fix for a problem), what it needs
 * before it can go out (account, permission, the final check of this file), its text and visibility, and the actions.
 * Your OK is its own step with a checkbox; Publish now exists only on an approved post, and asks first.
 */
export default function PostReview({ id }: { id: string }) {
  const { st } = useStatus();
  const { data, error, refresh, setData } = usePoll(() => loadPost(id), [id], 6000, () => true);
  const post = data?.items.find((p) => p.id === id) || null;
  const update = (p: Post) => {
    setData((d) => d && { ...d, items: d.items.map((x) => (x.id === p.id ? p : x)) });
    refresh();
  };
  if (!data) {
    if (error) {
      return (
        <div className="page">
          <PageHead title="Post" crumbs={[{ label: "Queue", href: "#/queue/review" }, { label: "Post" }]} />
          <EmptyState icon="alert" title="This post could not be loaded"
            actions={<button type="button" className="btn" onClick={refresh}><Icon name="refresh" />Try again</button>}>
            {error}
          </EmptyState>
        </div>
      );
    }
    return <LoadingPage label="Loading the post" />;
  }
  if (!post) {
    return (
      <div className="page">
        <PageHead title="Post not found"
          crumbs={[{ label: "Queue", href: "#/queue/review" }, { label: "Post not found" }]} />
        <EmptyState icon="posts" title="There is no post at this address"
          actions={<a className="btn" href="#/queue/review">Open the Queue</a>}>
          It may have been removed with its clip.
        </EmptyState>
      </div>
    );
  }
  return (
    <Review key={post.id} p={post} tz={data.timezone || st?.timezone} autoPublish={data.autoPublish}
      account={st?.platforms?.[post.platform]} onChanged={update} />
  );
}

function Review({ p, tz, autoPublish, account, onChanged }: {
  p: Post; tz?: string; autoPublish: boolean; account?: PlatformAccount; onChanged: (p: Post) => void;
}) {
  const yt = p.platform === "youtube";
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const s = postStatus(p);
  const needsOk = p.status === "awaiting_approval" || okOutdated(p);
  const editable = ["awaiting_approval", "approved", "failed"].includes(p.status);
  const accountOk = !account || (account.connected && !account.needs_reconnect);

  // The form starts from the post and follows it while you have not changed anything.
  const [base, setBase] = useState<Form>(() => formOf(p));
  const [f, setF] = useState<Form>(base);
  const [agree, setAgree] = useState(false);
  const key = serverKey(p);
  const dirtyKeys = (Object.keys(LABELS) as (keyof Form)[]).filter((k) => f[k] !== base[k]);
  const dirty = editable && dirtyKeys.length > 0;
  const lastKey = useRef(key);
  useEffect(() => {
    if (lastKey.current === key) return;
    lastKey.current = key;
    const next = formOf(p);
    setBase(next);
    if (!dirty) setF(next);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (patch: Partial<Form>) => setF((x) => ({ ...x, ...patch }));

  const [dialog, setDialog] = useState<PostAction | null>(null);
  const [confirmSave, setConfirmSave] = useState(false);
  const [busy, setBusy] = useState(false);

  // TikTok's creator info is read fresh from TikTok before posting (its sharing guidelines).
  const [creator, setCreator] = useState<TikTokCreator | null>(null);
  const [creatorError, setCreatorError] = useState("");
  useEffect(() => {
    if (yt || !editable || !account?.connected) return;
    api.tiktokCreator().then(setCreator).catch((e) => setCreatorError(errorText(e)));
  }, [yt, editable, account?.connected]);

  // The file that would be posted: the clip's posting version (its label and a cache key for this render).
  const [version, setVersion] = useState<ClipVersion | null>(null);
  useEffect(() => {
    api.versions(p.clip_id)
      .then((v) => setVersion(v.versions.find((x) => x.id === v.active) || null))
      .catch(() => undefined);
  }, [p.clip_id, p.quality?.sha256]);
  const videoUrl = version ? (version.id ? `/api/versions/${version.id}/video?v=${version.version}`
    : `/api/clips/${p.clip_id}/video?v=${version.version}`) : p.clip.video_url;

  const saveText = async (): Promise<Post> => {
    const out = await ap.edit(p.id, {
      title: yt ? f.title.trim() : p.title, description: f.text.trim(),
      ...(yt ? { tags: tagList(f.tags), privacy: f.privacy } : { privacy: f.mode === "direct" ? f.privacy : "" }),
    });
    onChanged(out as Post);
    const left = dirtyKeys.filter((k) => !SAVED_BY_EDIT.includes(k));
    setBase((b) => ({ ...b, ...Object.fromEntries(SAVED_BY_EDIT.map((k) => [k, f[k]])) }));
    toast(p.status === "approved" ? "Saved. It needs your OK again before it can go out."
      : left.length ? `Text saved. ${left.map((k) => LABELS[k]).join(", ")} are kept only when you approve.`
        : "Text saved.");
    if (out.warnings?.length) toast(`Saved. Check: ${out.warnings[0]}`);
    return out as Post;
  };

  const guard = useMemo(() => (dirty ? {
    what: dirtyKeys.map((k) => LABELS[k]).join(", "),
    save: dirtyKeys.every((k) => SAVED_BY_EDIT.includes(k)) && p.status !== "approved"
      ? async () => { await saveText(); } : undefined,
    discard: () => setF(base),
  } : null), [dirty, dirtyKeys.join(), base, p.status]); // eslint-disable-line react-hooks/exhaustive-deps
  useLeaveGuard(guard);

  // What still stands between this post and your OK (the platform's rules and the final check).
  const direct = !yt && f.mode === "direct";
  const branded = direct && f.disclose && f.brandContent;
  const audited = yt || !!account?.audited;
  const tooLong = direct && creator && creator.max_duration > 0 && p.clip.duration > creator.max_duration;
  const missing = [
    !accountOk && `connect ${name} again`,
    yt && !f.title.trim() && "enter a title",
    yt && f.title.length > 100 && "shorten the title to 100 characters",
    yt && !f.kids && "answer “made for kids”",
    !yt && f.text.length > 2200 && "shorten the caption to 2,200 characters",
    direct && !f.privacy && "choose who can see it",
    direct && !audited && f.privacy && f.privacy !== "SELF_ONLY" && "choose “Only me” (your TikTok app is not audited)",
    direct && f.disclose && !f.brandOrganic && !f.brandContent && "choose what the commercial content is",
    branded && f.privacy && f.privacy !== "MUTUAL_FOLLOW_FRIENDS" && "TikTok allows branded content only for Friends",
    tooLong && `trim the clip to ${creator!.max_duration} seconds`,
    p.quality?.status === "failed" && "fix what the final check found",
    !agree && "tick that you watched the video and read its text",
  ].filter(Boolean) as string[];

  const approve = async () => {
    if (missing.length) {
      toast(`To approve: ${missing.join(", ")}.`, true);
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = { title: yt ? f.title.trim() : p.title, description: f.text.trim() };
      if (yt) Object.assign(body, { tags: tagList(f.tags), privacy: f.privacy, made_for_kids: f.kids === "yes" });
      else Object.assign(body, {
        mode: f.mode, privacy: direct ? f.privacy : "", allow_comment: f.comment, allow_duet: f.duet,
        allow_stitch: f.stitch, disclose: f.disclose, brand_organic: f.brandOrganic, brand_content: f.brandContent,
      });
      const out = (await ap.approve(p.id, body)) as Post & { warnings?: string[] };
      setAgree(false);
      onChanged(out);
      toast(out.warnings?.length ? `Approved. Note: ${out.warnings[0]}`
        : `Approved for ${name}. It goes out ${atLabel(out.planned_at, tz)}. Nothing was uploaded now.`);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };

  const view = viewOf(p);
  const title = p.title || p.clip.title || "Untitled post";
  const clipLink = p.clip.id
    ? <a className="textlink" href={`#/clip/${p.clip.id}`}>{p.clip.title || "the clip"}</a> : null;
  return (
    <div className="page">
      <PageHead kind={`${name} post`} title={needsOk ? `Review for ${name}` : title}
        crumbs={[
          { label: `Queue: ${VIEW_NAME[view]}`, href: `#/queue/${view}` },
          { label: <span className="clamp-1 crumb-title">{title}</span> },
        ]}
        sub={<span className="row wrap" style={{ gap: 8 }}><Pill tone={s.tone} icon={s.icon}>{s.word}</Pill>
          <span className="small muted tnum">Planned for {timeLabel(p.planned_at, tz)}</span></span>} />
      <div className="review">
        <div className="stack-3">
          <div className="player-wrap">
            <div className="player">
              {p.clip.status === "ready" || p.clip.status === undefined
                ? <video key={videoUrl} src={videoUrl} poster={p.clip.has_thumbnail ? p.clip.thumbnail_url : undefined}
                  controls playsInline preload="metadata" aria-label={`Video of this post: ${title}`} />
                : <span className="missing"><Icon name="film" />The clip is being made again ({p.clip.status}).</span>}
            </div>
            <div className="player-controls">
              <span className="tiny faint">
                The exact file that will be posted:{" "}
                {version ? (version.id ? version.label : "Original") : "the clip's posting version"}
                {p.clip.duration ? ` · ${fmtTime(p.clip.duration)}` : ""} · 1080×1920.
              </span>
            </div>
          </div>
          <p className="small">
            {clipLink}{p.source?.title ? <span className="faint"> · clip from “{p.source.title}”</span> : null}
          </p>
          <p className="tiny faint">
            Changing the clip makes a new file. A new file needs a new final check and a new OK before it can be posted.
          </p>
        </div>

        <div className="stack-4">
          <StatusBlock p={p} tz={tz} autoPublish={autoPublish} accountOk={accountOk} onAction={setDialog}
            onChanged={onChanged} videoUrl={videoUrl} />
          {p.replaces && p.status === "awaiting_approval" && (
            <p className="small">
              <Icon name="refresh" className="sm" /> If you approve it, it takes the time of a weaker{" "}
              <a className="textlink" href={`#/post/${p.replaces}`}>planned post</a>, which is then replaced.
            </p>
          )}
          <Checks p={p} account={account} />
          {editable ? (
            <TextPanel p={p} f={f} set={set} creator={creator} creatorError={creatorError} account={account} />
          ) : (
            <section className="panel" aria-labelledby="posted-h">
              <h2 id="posted-h" style={{ fontSize: "var(--fs-h3)" }}>Text and visibility</h2>
              <dl className="kv">
                {yt && <><dt>Title</dt><dd>{p.title || "—"}</dd></>}
                <dt>{yt ? "Description" : "Caption"}</dt>
                <dd style={{ whiteSpace: "pre-wrap" }}>{p.description || "—"}</dd>
                {yt && !!p.tags?.length && <><dt>Tags</dt><dd>{p.tags.join(", ")}</dd></>}
                <dt>Who can see it</dt>
                <dd>{privacyLabel(p.platform, p.publication?.privacy || p.privacy)}</dd>
                {p.audience_label && <><dt>Who it is for</dt><dd>{p.audience_label}</dd></>}
                {p.delivery_label && <><dt>Delivery</dt><dd>{p.delivery_label}</dd></>}
                {p.analytics_label && p.status === "published" && <><dt>Results</dt><dd>{p.analytics_label}</dd></>}
              </dl>
            </section>
          )}
          <div className="row wrap">
            {["awaiting_approval", "approved", "failed", "action_needed", "blocked"].includes(p.status) && (
              <button type="button" className="btn btn-danger" onClick={() => setDialog("cancel")}>
                <Icon name="x" />Cancel this post…
              </button>
            )}
            {editable && (
              <button type="button" className="btn btn-quiet" onClick={() => setDialog("reschedule")}>
                <Icon name="clock" />Change the time…
              </button>
            )}
          </div>
          <Details p={p} />
        </div>
      </div>

      {needsOk && (
        <section className="savebar approve-bar" aria-labelledby="ok-h">
          <div className="grow">
            <h2 id="ok-h" className="small strong">Your OK for {name}</h2>
            <span className="small muted">
              {!yt && f.mode === "inbox"
                ? `Approving sends this exact video with this text to your TikTok inbox ${atLabel(p.planned_at, tz)}, `
                  + "without asking again. You finish it in the TikTok app for your followers. Nothing is sent now."
                : !yt && f.mode === "manual"
                  ? `Approving makes this exact video and caption ready for you to post ${atLabel(p.planned_at, tz)}. `
                    + "Nothing is sent to TikTok: you post it in the TikTok app for your followers and paste the link."
                  : yt
                    ? `Approving uploads this exact video as Private ${atLabel(p.planned_at, tz)} to `
                      + `${account?.name || name}, without asking again. Then you share it in YouTube Studio with `
                      + "the people you picked. Nothing is uploaded now."
                    : `Approving posts this exact video with this text ${atLabel(p.planned_at, tz)} to `
                      + `${account?.name || name} for the audience you chose, without asking again. Nothing is `
                      + "posted now."}
              {" "}If the video or the text changes, it needs your OK again, and you can cancel it until it goes out.
              {!autoPublish
                ? " Posting at the planned time is turned off, so at its time it waits for you to press Publish now."
                : ""}
            </span>
            <label className="choice">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
              <span className="small">I watched this video and read its text.</span>
            </label>
          </div>
          <div className="stack approve-side">
            <button type="button" className="btn btn-primary" aria-disabled={missing.length > 0 || busy}
              aria-describedby="ok-why" onClick={() => !busy && approve()}>
              {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="check" />}Approve for {name}
            </button>
            <span className="tiny muted" id="ok-why">
              {missing.length ? `To approve: ${missing.join(", ")}.` : "Ready to approve."}
            </span>
            {dirty && dirtyKeys.some((k) => SAVED_BY_EDIT.includes(k)) && (
              <button type="button" className="btn btn-small btn-quiet" disabled={busy}
                onClick={() => saveText().catch((e) => toast(errorText(e), true))}>
                Save the text without approving
              </button>
            )}
          </div>
        </section>
      )}
      {!needsOk && dirty && (
        <section className="savebar" aria-label="Save changes">
          <div className="grow">
            <b className="small">Unsaved changes: {dirtyKeys.map((k) => LABELS[k]).join(", ")}</b>
            {p.status === "approved" && (
              <span className="tiny muted">Saving removes your OK: it needs your OK again before it can go out.</span>
            )}
          </div>
          <button type="button" className="btn btn-quiet" onClick={() => setF(base)}>Discard</button>
          <button type="button" className="btn btn-primary"
            onClick={() => (p.status === "approved" ? setConfirmSave(true)
              : saveText().catch((e) => toast(errorText(e), true)))}>Save changes</button>
        </section>
      )}

      {confirmSave && (
        <ConfirmDialog title="Save the changes?" confirmLabel="Save and remove my OK" cancelLabel="Keep it as approved"
          onClose={() => setConfirmSave(false)} onConfirm={async () => { await saveText(); }}>
          <p className="muted">
            You approved this {name} post as it was. Saving the changes removes your OK: it won't go out until you
            approve it again.
          </p>
        </ConfirmDialog>
      )}
      {dialog && (
        <PostActionDialog action={dialog} post={p} tz={tz} account={account?.name} onClose={() => setDialog(null)}
          onDone={(out) => onChanged(out)} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------ the status, with the fix for a problem
function StatusBlock({ p, tz, autoPublish, accountOk, onAction, onChanged, videoUrl }: {
  p: Post; tz?: string; autoPublish: boolean; accountOk: boolean; onAction: (a: PostAction) => void;
  onChanged: (p: Post) => void; videoUrl?: string;
}) {
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const fix = (text?: string) => (text ? <span><b>What to do:</b> {text}</span> : null);
  const reconnect = !accountOk
    && <a className="btn btn-small" href="#/settings"><Icon name="link" />Connect {name} again</a>;
  const retry = (label = "Try again…", quiet = false) => (
    <button type="button" className={`btn btn-small ${quiet ? "btn-quiet" : ""}`} onClick={() => onAction("retry")}>
      <Icon name="refresh" />{label}
    </button>
  );
  const again = newOkReason(p);
  if (again) {
    return (
      <Banner tone="warn" icon="alert" title={again.word}>
        <span>{again.detail}</span> <span>Watch the video, check its text, then approve it again below.</span>
      </Banner>
    );
  }
  switch (p.status) {
    case "awaiting_approval":
      return p.status_note ? <p className="small muted">{p.status_note}</p> : null;
    case "approved": {
      const auto = p.approval?.by === "automatic";
      // "approved today, 9:14" reads better mid-sentence than "approved Today, 9:14".
      const approvedAt = p.approval?.at
        ? when(p.approval.at, tz).replace(/^(Today|Tomorrow|Yesterday)/, (m) => m.toLowerCase()) : "";
      // The scheduler gives an approved post more than 15 minutes late a new time instead of posting it late
      // (scheduler.OVERDUE_MINUTES), so "it goes out yesterday" would be wrong.
      const overdue = !!p.planned_at && p.planned_at < Date.now() / 1000 - 15 * 60;
      return (
        <section className="panel" aria-labelledby="st-h">
          <h2 id="st-h" style={{ fontSize: "var(--fs-h3)" }}>{auto ? "Approved automatically" : "Approved by you"}</h2>
          <p className="small muted">
            {auto ? `Your automatic-publishing permission for ${name} approved it, because every check passed. `
              + "You did not review it."
              : `You approved this exact video and text${approvedAt ? ` ${approvedAt}` : ""}.`}{" "}
            {overdue ? `Its time, ${atLabel(p.planned_at, tz)}, passed while Autopilot wasn't running. It stays `
              + "approved and gets a new time the next time Autopilot runs."
              : autoPublish ? `It goes out ${atLabel(p.planned_at, tz)} by itself.`
              : "Posting at the planned time is turned off (Settings, Advanced), so at its time it waits for you to "
                + "press Publish now."}
          </p>
          <div className="consequence">
            <b>Publish now instead?</b>
            <span>
              “Publish now” uploads it right away instead of {atLabel(p.planned_at, tz)}. The upload can't be taken back
              from ClipFoundry; you would remove it on {name}.
            </span>
          </div>
          <div className="row wrap">
            <button type="button" className="btn" onClick={() => onAction("publish-now")}>
              <Icon name="upload" />Publish now…
            </button>
          </div>
        </section>
      );
    }
    case "publishing":
      return (
        <Banner tone="info" icon="upload" title="Uploading now">
          {p.publication?.message || p.status_note || "The upload has started."} It can't be canceled from ClipFoundry
          once it started; wait for it to finish.
        </Banner>
      );
    case "published":
      if (onPlatform(p)) {
        return (
          <Banner tone="info" icon="clock" title="Uploaded early as Private">
            It was uploaded ahead of its time ({atLabel(p.planned_at, tz)}) and stays Private: {name} never makes it
            public by itself. {p.status_note}
          </Banner>
        );
      }
      return <PublishedBlock p={p} onChanged={onChanged} />;
    case "reconciling":
      return (
        <Banner tone="warn" icon="question" title="Upload not confirmed"
          actions={<>
            <button type="button" className="btn btn-small" onClick={() => onAction("resolve-yes")}>
              <Icon name="check" />It's on {name}: add its link…
            </button>
            <button type="button" className="btn btn-small" onClick={() => onAction("resolve-no")}>
              <Icon name="refresh" />It's not there: upload again…
            </button>
          </>}>
          <span className="stack" style={{ gap: 4 }}>
            {p.status_note && <span>{p.status_note}</span>}
            <span>ClipFoundry won't upload it again by itself, so the video can never be posted twice.</span>
            {fix(p.fix || `Check ${p.platform === "youtube" ? "YouTube Studio" : "your TikTok profile"}, then tell `
              + "ClipFoundry what you found.")}
          </span>
        </Banner>
      );
    case "failed":
      return (
        <Banner tone="bad" icon="alert" title="It could not be posted" actions={<>{reconnect}{retry()}</>}>
          <span className="stack" style={{ gap: 4 }}>
            <span>{p.last_error || p.status_note}</span>
            {fix(p.fix)}
          </span>
        </Banner>
      );
    case "blocked":
      if (p.audience?.intent === "LEGACY_PUBLIC") return <HeldPublic p={p} onChanged={onChanged} />;
      return (
        <Banner tone="bad" icon="shield"
          title={blockedByCheck(p) ? "Blocked: this file did not pass the final check" : "Blocked"}
          actions={<>
            {p.clip.id && (
              <a className="btn btn-small" href={`#/clip/${p.clip.id}`}><Icon name="edit" />Open the clip</a>
            )}
            {retry("Try again…", true)}
          </>}>
          <span className="stack" style={{ gap: 4 }}>
            <span>{p.status_note || p.last_error}</span>
            {fix(p.fix)}
          </span>
        </Banner>
      );
    case "action_needed":
      if (inInbox(p)) {
        return (
          <Banner tone="info" title="Finish it in the TikTok app"
            actions={<>
              <button type="button" className="btn btn-small" onClick={() => onAction("link")}>
                <Icon name="link" />Link the post…
              </button>
              <button type="button" className="btn btn-small btn-quiet" onClick={() => onAction("retry")}>
                Send a new draft…
              </button>
            </>}>
            <span className="stack" style={{ gap: 4 }}>
              <span>{p.status_note || p.publication?.message}</span>
              <span>After you posted it, paste its link so ClipFoundry can read its real numbers.</span>
            </span>
          </Banner>
        );
      }
      if (p.delivery_state === "manual_handoff") {
        return <PostItYourself p={p} videoUrl={videoUrl} onAction={onAction} onChanged={onChanged} />;
      }
      return (
        <Banner tone="bad" icon="alert" title="Action needed" actions={<>{reconnect}{retry()}</>}>
          <span className="stack" style={{ gap: 4 }}>
            <span>{p.last_error || p.status_note}</span>
            {fix(p.fix)}
          </span>
        </Banner>
      );
    case "canceled":
      return (
        <section className="panel tight">
          <p className="small muted">{p.status_note || "Canceled."} Nothing was posted.</p>
          <div className="row wrap">
            <button type="button" className="btn btn-small" onClick={() => onAction("retry")}>Plan it again…</button>
          </div>
        </section>
      );
    case "replaced":
      return (
        <section className="panel tight">
          <p className="small muted">
            {p.status_note || "Replaced by a stronger clip."}{" "}
            {p.replaced_by && (
              <a className="textlink" href={`#/post/${p.replaced_by}`}>Open the post that took its time</a>
            )}
          </p>
        </section>
      );
    default:
      return null;
  }
}

/** TikTok has no route for your followers from this app (only audited apps may post for them), so the clip is a
 * ready-to-post package: the video, its caption and who to post it for. You post it in the TikTok app, then paste
 * its link (or say you posted it). Nothing is uploaded by ClipFoundry. */
function PostItYourself({ p, videoUrl, onAction, onChanged }: {
  p: Post; videoUrl?: string; onAction: (a: PostAction) => void; onChanged: (p: Post) => void;
}) {
  const who = (p.audience?.visibility || p.privacy) === "MUTUAL_FOLLOW_FRIENDS" ? "Friends" : "Followers";
  const [busy, setBusy] = useState(false);
  const caption = p.description || p.title;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(caption);
      toast("Caption copied");
    } catch {
      toast("Copying is blocked here: select the caption and copy it yourself", true);
    }
  };
  const posted = async () => {
    setBusy(true);
    try {
      onChanged(await ap.postedByYou(p.id) as Post);
      toast("Noted: you posted it in the TikTok app");
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  const file = `${(p.title || "clip").replace(/[^\w -]+/g, "").trim().slice(0, 60) || "clip"}.mp4`;
  return (
    <section className="panel stack-4 post-yourself" aria-labelledby="py-h">
      <h2 id="py-h" style={{ fontSize: "var(--fs-h3)" }}>Ready for you to post on TikTok</h2>
      <p className="small">
        TikTok lets only apps it has audited post for your followers, so ClipFoundry does not upload this clip. Post it
        yourself in the TikTok app; it takes a minute.
      </p>
      <ol className="small stack" style={{ gap: 6, paddingLeft: 20 }}>
        <li>
          Save the video:{" "}
          {videoUrl
            ? <a className="btn btn-small" href={videoUrl} download={file}><Icon name="download" />Download video</a>
            : <span className="muted">the video file is not ready</span>}
          {" "}Then put it on your phone (a cable or your cloud drive), or upload it at tiktok.com on this PC.
        </li>
        <li>
          Copy the caption:{" "}
          <button type="button" className="btn btn-small" onClick={copy}><Icon name="copy" />Copy caption</button>
          <textarea className="input" readOnly rows={3} value={caption} aria-label="Caption"
            onFocus={(e) => e.currentTarget.select()} style={{ marginTop: 6, width: "100%" }} />
        </li>
        <li>
          In TikTok: keep your account <b>private</b>, tap <b>+</b> → <b>Upload</b>, pick the video and paste the
          caption.
        </li>
        <li>
          Under <b>Who can watch this video</b> choose <b>{who}</b>. Never <b>Everyone</b>; <b>Only you</b> means nobody
          else sees it. Then post.
        </li>
        <li>Back here, paste the post's link (Share → Copy link) so ClipFoundry can read its numbers.</li>
      </ol>
      <div className="row wrap">
        <button type="button" className="btn btn-primary btn-small" onClick={() => onAction("link")}>
          <Icon name="link" />Link the post…
        </button>
        <button type="button" className="btn btn-small btn-quiet" disabled={busy} onClick={posted}>
          I posted it, no link
        </button>
      </div>
      <p className="tiny muted">
        Without a link ClipFoundry cannot read its numbers: add what your viewers said in Clips → Test feedback.
        Only post clips you may reuse.
      </p>
    </section>
  );
}

/** A post planned as public before this version. It never goes out as public; you can plan it for your selected
 * viewers instead (it then needs your OK like any other post), or cancel it. */
function HeldPublic({ p, onChanged }: { p: Post; onChanged: (p: Post) => void }) {
  const [busy, setBusy] = useState(false);
  const plan = async () => {
    setBusy(true);
    try {
      await ap.retarget([p.id]);
      onChanged((await loadPost(p.id)).items[0] || p);
      toast("Planned for your selected viewers. It needs your OK before it goes out.");
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Banner tone="warn" icon="shield" title="Held: it was planned as public"
      actions={<button type="button" className="btn btn-small" disabled={busy} onClick={plan}>
        <Icon name="user" />Send to my selected viewers</button>}>
      This version never posts publicly. Plan it for the viewers you chose instead (it then waits for your OK), or
      cancel it.
    </Banner>
  );
}

/** An uploaded post: links to it, the step only you can do (sharing a private video), and its real numbers (read
 * from the platform, never estimated). */
function PublishedBlock({ p, onChanged }: { p: Post; onChanged: (p: Post) => void }) {
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const [pub, setPub] = useState<Publication | null>(null);
  useEffect(() => {
    if (!p.publication?.id) return;
    api.publications(p.clip_id)
      .then((list) => setPub(list.find((x) => x.id === p.publication!.id) || null))
      .catch(() => undefined);
  }, [p.clip_id, p.publication?.id]);
  const studio = p.publication?.info?.studio_url as string | undefined;
  const [sharing, setSharing] = useState(false);
  const shared = async () => {
    setSharing(true);
    try {  // recorded on the post itself, which the Queue and the Brain read (your word, not checked by YouTube)
      onChanged(await ap.audienceConfirmed(p.id) as Post);
      toast("Noted: you shared it with your invited viewers");
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setSharing(false);
    }
  };
  return (
    <section className="panel" aria-labelledby="st-h">
      <h2 id="st-h" style={{ fontSize: "var(--fs-h3)" }}>{postStatus(p).word}</h2>
      {p.status_note && <p className="small muted">{p.status_note}</p>}
      {p.delivery_state === "awaiting_invitations" && (
        <Banner tone="warn" icon="user" title="Share it with your invited viewers"
          actions={<button type="button" className="btn btn-small" disabled={sharing} onClick={shared}>
            <Icon name="check" />I shared it</button>}>
          It is Private on YouTube, so nobody but you can watch it yet. In YouTube Studio choose Visibility → Private
          → Share privately, add your viewers' email addresses and save. ClipFoundry cannot check this; your word is
          recorded as yours.
        </Banner>
      )}
      {p.analytics_label && <p className="small"><b>Results:</b> {p.analytics_label}</p>}
      <div className="row wrap">
        {p.publication?.url && (
          <a className="btn btn-small" href={p.publication.url} target="_blank" rel="noreferrer">
            <Icon name="external" />Open on {name}
          </a>
        )}
        {studio && (
          <a className="btn btn-small btn-quiet" href={studio} target="_blank" rel="noreferrer">YouTube Studio</a>
        )}
      </div>
      {pub && <PublicationStats p={pub} onChange={setPub} />}
    </section>
  );
}

// ------------------------------------------------------------------ before it can go out
function Checks({ p, account }: { p: Post; account?: PlatformAccount }) {
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const q = p.quality;
  const CHECK: Record<string, [string, string, "check" | "x" | "alert"]> = {
    pass: ["good", "passed", "check"], warn: ["warn", "warning", "alert"], fail: ["bad", "failed", "x"],
    skipped: ["skip", "not checked", "alert"],
  };
  return (
    <section className="panel" aria-labelledby="checks-h">
      <h2 id="checks-h" style={{ fontSize: "var(--fs-h3)" }}>Before it can go out</h2>
      <dl className="kv">
        <dt>Account</dt>
        <dd>
          {!account ? <span className="muted">Unknown right now</span>
            : account.connected && !account.needs_reconnect ? <>{account.name || name}</>
              : <span className="row wrap" style={{ gap: 8 }}>
                <Pill tone="bad" icon="alert">{account.needs_reconnect ? "Sign-in expired" : "Not connected"}</Pill>
                <a className="textlink small" href="#/settings">Connect in Settings</a>
              </span>}
        </dd>
        <dt>Permission to use</dt>
        <dd>
          <Pill tone={CLEARED_RIGHTS.includes(p.source?.rights_status) ? "good" : "warn"} icon="shield">
            {p.source?.rights_label || p.source?.rights_status || "Unknown"}
          </Pill>
          {p.source?.title && (
            <span className="small muted"> {p.source.title}{p.source.channel ? ` · ${p.source.channel}` : ""}</span>
          )}
        </dd>
        <dt>Final check</dt>
        <dd>
          {!q ? <Pill tone="neutral" icon="clock">Not done yet</Pill>
            : q.status === "failed" ? <Pill tone="bad" icon="alert">Failed</Pill>
              : q.warnings.length
                ? <Pill tone="warn" icon="alert">Passed with {plural(q.warnings.length, "warning")}</Pill>
                : <Pill tone="good" icon="check">Passed</Pill>}
          {!q && (
            <div className="small muted">
              This file has not been checked yet. You can approve it now; it is posted only after the check passes.
            </div>
          )}
          {q?.blockers.map((w, i) => <div key={`b${i}`} className="small">{w}</div>)}
          {q?.warnings.map((w, i) => <div key={`w${i}`} className="small muted">{w}</div>)}
          {q?.text_status === "failed"
            && q.text_problems.map((t, i) => <div key={`t${i}`} className="small">Text: {t}</div>)}
        </dd>
      </dl>
      {!!q?.checks.length && (
        <Disclosure plain summary={`All ${q.checks.length} checks of this exact file`}>
          <ul className="check-list">
            {q.checks.map((c) => {
              const [cls, word, icon] = CHECK[c.status] || CHECK.skipped;
              return (
                <li key={c.name}>
                  <span className={cls}><Icon name={icon} className="sm" /></span>
                  <span>
                    {c.label}: {word}{c.detail ? ` (${c.detail})` : ""}{c.kind === "heuristic" ? " · estimate" : ""}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="tiny faint">
            {q.coverage?.note ? `${q.coverage.note} ` : ""}Checks marked “estimate” are heuristics. The report is tied
            to this file's fingerprint (SHA-256), checked {when(q.checked_at)}.
          </p>
        </Disclosure>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ text and visibility
function TextPanel({ p, f, set, creator, creatorError, account }: {
  p: Post; f: Form; set: (x: Partial<Form>) => void; creator: TikTokCreator | null; creatorError: string;
  account?: PlatformAccount;
}) {
  const yt = p.platform === "youtube";
  const direct = !yt && f.mode === "direct";
  const branded = direct && f.disclose && f.brandContent;
  const audited = !!account?.audited;
  const options = (p.metadata_options || []).filter((o) => !o.problems.length).slice(0, 6);
  const pick = (o: ScheduledItem["metadata_options"][number]) =>
    set({ title: o.title, text: yt ? o.description : o.caption, tags: (yt ? o.tags : o.hashtags).join(" ") });
  const label = f.disclose ? (f.brandContent ? "Paid partnership" : f.brandOrganic ? "Promotional content" : "") : "";
  return (
    <section className="panel" aria-labelledby="text-h">
      <h2 id="text-h" style={{ fontSize: "var(--fs-h3)" }}>Text and visibility</h2>
      {options.length > 1 && (
        <div className="field">
          <span className="label" id="sugg-l">
            Suggestions <span className="hint">written from the clip's own words</span>
          </span>
          <div className="chips" role="group" aria-labelledby="sugg-l">
            {options.map((o) => (
              <button key={o.id} type="button" className="chip" aria-pressed={f.title === o.title}
                onClick={() => pick(o)} title={`${o.style}: ${o.title}`}>
                {o.title.length > 70 ? `${o.title.slice(0, 70)}…` : o.title}
              </button>
            ))}
          </div>
        </div>
      )}
      {yt && (
        <Field id="rv-title" label="Title" count={`${f.title.length}/100`}
          invalid={!f.title.trim() || f.title.length > 100}>
          <input id="rv-title" type="text" value={f.title} onChange={(e) => set({ title: e.target.value })}
            aria-invalid={f.title.length > 100 || undefined} />
        </Field>
      )}
      <Field id="rv-text" label={yt ? "Description" : "Caption"} count={yt ? undefined : `${f.text.length}/2200`}
        invalid={!yt && f.text.length > 2200}>
        <textarea id="rv-text" rows={5} value={f.text} onChange={(e) => set({ text: e.target.value })}
          aria-invalid={(!yt && f.text.length > 2200) || undefined} />
      </Field>
      {yt ? (
        <>
          <Field id="rv-tags" label="Tags">
            <input id="rv-tags" type="text" value={f.tags} onChange={(e) => set({ tags: e.target.value })} />
          </Field>
          <div className="field">
            <span className="label">Who can see it</span>
            <span>Private, then shared with the people you invite</span>
            <span className="hint">
              ClipFoundry uploads it as Private and never makes it public or unlisted. Share it in YouTube Studio:
              Content → this video → Visibility → Private → Share privately.
            </span>
          </div>
          <fieldset>
            <legend className="label">Made for kids <span className="hint">(YouTube requires an answer)</span></legend>
            {([["no", "No, it's not made for kids"], ["yes", "Yes, it's made for kids"]] as const).map(([v, l]) => (
              <label key={v} className="choice">
                <input type="radio" name="rv-kids" value={v} checked={f.kids === v} onChange={() => set({ kids: v })} />
                <span>{l}</span>
              </label>
            ))}
          </fieldset>
        </>
      ) : (
        <>
          {creator && (
            <p className="small">
              Posting as <b>{creator.nickname}</b>
              {creator.username ? <span className="muted"> @{creator.username}</span> : null}{" "}
              <span className="faint">(read from TikTok just now)</span>
            </p>
          )}
          {creatorError && (
            <Banner tone="bad" title="TikTok's account details could not be read">{creatorError}</Banner>
          )}
          <fieldset>
            <legend className="label">How to post</legend>
            <label className="choice">
              <input type="radio" name="rv-mode" checked={direct} onChange={() => set({ mode: "direct" })}
                disabled={!!account?.connected && !account.can_direct_post} />
              <span>
                Post directly to your profile
                {account?.connected && !account.can_direct_post
                  ? " (your TikTok app has no Direct Post permission)" : ""}
              </span>
            </label>
            <label className="choice">
              <input type="radio" name="rv-mode" checked={f.mode === "inbox"} onChange={() => set({ mode: "inbox" })}
                disabled={!account?.connected || !account.can_inbox} />
              <span>
                Send to your TikTok inbox as a draft (you finish it in the TikTok app for your followers; no audit
                needed, but TikTok must have approved your app, and at most 5 drafts can wait at a time)
              </span>
            </label>
            <label className="choice">
              <input type="radio" name="rv-mode" checked={f.mode === "manual"} onChange={() => set({ mode: "manual" })} />
              <span>
                Ready to post yourself (download the video and caption, post it in the TikTok app for your followers,
                then paste the link)
              </span>
            </label>
          </fieldset>
          {direct && (
            <>
              <Field id="rv-tpriv" label="Who can see it">
                <select id="rv-tpriv" value={f.privacy} onChange={(e) => set({ privacy: e.target.value })}>
                  <option value="" disabled>Choose…</option>
                  {(creator?.privacy_options || []).filter((o) => o !== "PUBLIC_TO_EVERYONE").map((o) => (
                    <option key={o} value={o}
                      disabled={(!audited && o !== "SELF_ONLY") || (branded && o !== "MUTUAL_FOLLOW_FRIENDS")}>
                      {TIKTOK_PRIVACY[o] || o}{!audited && o !== "SELF_ONLY" ? " (needs TikTok's app audit)" : ""}
                      {branded && o !== "MUTUAL_FOLLOW_FRIENDS" ? " (branded content: Friends only)" : ""}
                    </option>
                  ))}
                </select>
              </Field>
              <Note>
                Posting to everyone is turned off: ClipFoundry posts only for your approved followers (keep your TikTok
                account private).{!audited ? " Until TikTok audits your app, Direct Post can only post “Only me”, so "
                  + "use the inbox draft or the ready-to-post package to reach your followers." : ""}
              </Note>
              <fieldset>
                <legend className="label">Allow viewers to</legend>
                <div className="row wrap" style={{ gap: 16 }}>
                  {(["comment", "duet", "stitch"] as const).map((k) => {
                    const off = !!creator?.[`${k}_disabled` as const];
                    return (
                      <label key={k} className="choice" title={off ? "Turned off in your TikTok settings" : undefined}>
                        <input type="checkbox" disabled={off} checked={f[k] && !off}
                          onChange={(e) => set({ [k]: e.target.checked })} />
                        <span>{LABELS[k] === "Comments" ? "Comment" : LABELS[k]}{off ? " (off in TikTok)" : ""}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
              <label className="choice">
                <input type="checkbox" checked={f.disclose}
                  onChange={(e) => set(e.target.checked ? { disclose: true }
                    : { disclose: false, brandOrganic: false, brandContent: false })} />
                <span>This video promotes a brand, product or service (disclose commercial content)</span>
              </label>
              {f.disclose && (
                <div className="stack" style={{ paddingLeft: 32 }}>
                  <label className="choice">
                    <input type="checkbox" checked={f.brandOrganic}
                      onChange={(e) => set({ brandOrganic: e.target.checked })} />
                    <span><b>Your brand</b>: you promote yourself or your own business</span>
                  </label>
                  <label className="choice">
                    <input type="checkbox" checked={f.brandContent}
                      onChange={(e) => set({ brandContent: e.target.checked })} />
                    <span><b>Branded content</b>: you promote another brand or a third party</span>
                  </label>
                  {label && <span className="small muted">Your video will be labeled “{label}”.</span>}
                </div>
              )}
              {creator && creator.max_duration > 0 && p.clip.duration > creator.max_duration && (
                <Note>
                  This clip is {Math.round(p.clip.duration)} seconds; your TikTok account allows up to{" "}
                  {creator.max_duration} seconds.
                </Note>
              )}
            </>
          )}
          <p className="tiny faint">
            By posting, you agree to TikTok's{" "}
            {branded && <><a className="textlink" href={BC_POLICY} target="_blank" rel="noreferrer">Branded Content
              Policy</a> and </>}
            <a className="textlink" href={MUSIC_POLICY} target="_blank" rel="noreferrer">Music Usage Confirmation</a>.
            It may take a few minutes for the video to appear on your profile.
          </p>
        </>
      )}
      <p className="tiny faint">
        Text is checked against the clip's transcript; anything that isn't said in the clip is pointed out.
      </p>
    </section>
  );
}

function Field({ id, label, count, invalid, children }: {
  id: string; label: string; count?: string; invalid?: boolean; children: ReactNode;
}) {
  return (
    <div className="field">
      <label htmlFor={id}>
        {label} {count && <span className={`hint tnum ${invalid ? "bad-text" : ""}`}>{count}</span>}
      </label>
      {children}
    </div>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="small break"><Pill tone="warn" icon="alert">Note</Pill> {children}</p>;
}

// ------------------------------------------------------------------ why this time, and the post's history
function Details({ p }: { p: Post }) {
  const explanation: string[] = Array.isArray(p.scores?.explanation) ? p.scores.explanation : [];
  return (
    <div className="stack">
      <Disclosure plain summary="Why this time and score (estimates)">
        <ul className="flags">
          {p.final_score != null && <li>Final Opportunity {Math.round(p.final_score)} (estimate)</li>}
          {p.clip_scores?.clip != null && <li>Clip Score {Math.round(p.clip_scores.clip)} (estimate)</li>}
          {explanation.map((w, i) => <li key={i}>{w}</li>)}
          {p.slot?.note && <li>Time: {p.slot.note}</li>}
          {p.trend && <li>Topic “{p.trend.topic}”</li>}
        </ul>
      </Disclosure>
      {!!p.audit?.length && (
        <Disclosure plain summary={`History of this post (${p.audit.length})`}>
          <ul className="flags">
            {[...p.audit].reverse().map((a, i) => (
              <li key={i}><span className="tnum">{when(a.at)}</span>: {a.detail}</li>
            ))}
          </ul>
        </Disclosure>
      )}
    </div>
  );
}
