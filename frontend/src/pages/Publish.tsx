import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Accounts, api, Clip, ClipVersion, clipThumbUrl, downloadZip, errorText, fmtTime, Platform, PlatformAccount, Project,
  Publication, TikTokCreator, versionDownloadUrl, versionThumbUrl, versionVideoUrl,
} from "../api";
import { useLeaveGuard } from "../router";
import { useStatus } from "../status";
import { audienceApi, AudienceDestination, AudienceView } from "../office/api";
import { AccountBadge, ConnectButton } from "../components/accounts";
import { accountName, ChannelPicker, defaultTicks, isPostable, nameList } from "../components/channelPicker";
import { Connection, studio } from "../studio";
import { loadPosts, Post, postStatus, privacyLabel, TIKTOK_PRIVACY, timeLabel } from "../components/postShared";
import { PublicationStats } from "../components/stats";
import { YouTubeComments, YouTubeCommentsResult } from "../components/YouTubeComments";
import "./posts.css";
import {
  Banner, ConfirmDialog, Disclosure, EmptyState, Icon, IconName, LoadingPage, PageHead, Pill, PlatformName, ProgressBar,
  ScoreBadge, Tone, toast, usePoll,
} from "../components/ui";

const ACTIVE = ["queued", "uploading", "processing"];
// TikTok's own pages its posting rules ask apps to link (the UX guidelines of the Content Posting API).
const BC_POLICY = "https://www.tiktok.com/legal/page/global/bc-policy/en";
const MUSIC_POLICY = "https://www.tiktok.com/legal/page/global/music-usage-confirmation/en";
const STUDIO_UPLOAD = "https://www.tiktok.com/tiktokstudio/upload";
const tagList = (s: string) => s.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));

type Meta = { title: string; caption: string; hashtags: string };
const metaOf = (c: Clip): Meta => ({
  title: c.post?.title || c.title, caption: c.post?.caption || "", hashtags: (c.post?.hashtags || c.hashtags).join(" "),
});

/**
 * Prepare post: post one clip yourself, now. Preview the exact file (the clip's posting version), its text, and a
 * panel per platform with every option the platform asks for and the accounts it goes to (one upload per ticked
 * account). Nothing is uploaded until you press a platform's button and confirm in a dialog that says what happens.
 * Posts Autopilot planned for this clip are listed and open their own page; changing the posting version happens in
 * the editor.
 */
export default function PublishPage({ id }: { id: string }) {
  const { st } = useStatus();
  const [clip, setClip] = useState<Clip | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState("");
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [conns, setConns] = useState<Connection[] | null>(null);
  const [ticks, setTicks] = useState<Ticks | null>(null);
  const [audience, setAudience] = useState<AudienceView | null>(null);
  const [pubs, setPubs] = useState<Publication[]>([]);
  const [version, setVersion] = useState<ClipVersion | undefined>();
  const [saved, setSaved] = useState<Meta>({ title: "", caption: "", hashtags: "" });
  const [meta, setMeta] = useState<Meta>(saved);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        let c = await api.clip(id);
        if (!c.post?.title && !c.post?.titles?.length) c = await api.regeneratePost(id); // clips from older versions
        setClip(c);
        setSaved(metaOf(c));
        setMeta(metaOf(c));
        setProject(await api.project(c.project_id));
        const v = await api.versions(id);
        setVersion(v.versions.find((x) => x.id === v.active));
      } catch (e) {
        setLoadError(errorText(e));
      }
    })();
    api.accounts().then(setAccounts).catch((e) => toast(errorText(e), true));
    audienceApi.view().then(setAudience).catch((e) => toast(errorText(e), true));
  }, [id]);

  // Every connected account; read again when you come back from signing in to one in another tab.
  const loadConns = useCallback((quiet: boolean) => studio.connections().then((r) => setConns(r.connections))
    .catch((e) => {
      setConns((c) => c ?? []);
      if (!quiet) toast(errorText(e), true);
    }), []);
  useEffect(() => {
    void loadConns(false);
    const back = () => document.visibilityState === "visible" && void loadConns(true);
    document.addEventListener("visibilitychange", back);
    window.addEventListener("focus", back);
    return () => {
      document.removeEventListener("visibilitychange", back);
      window.removeEventListener("focus", back);
    };
  }, [loadConns]);
  const changeAccounts = (a: Accounts) => {
    setAccounts(a);
    void loadConns(true);
  };
  // Ticked at first: the accounts this clip's project was made to upload to, else the accounts ticked for new posts.
  useEffect(() => {
    if (!conns || !project || ticks) return;
    const fromProject = projectConnections(project);
    const start = (platform: Platform) => {
      const usable = new Set(conns.filter((c) => c.platform === platform && isPostable(c)).map((c) => c.id));
      const chosen = fromProject.filter((cid) => usable.has(cid));
      return chosen.length ? chosen : defaultTicks(conns, [platform]);
    };
    setTicks({ youtube: start("youtube"), tiktok: start("tiktok") });
  }, [conns, project, ticks]);

  const loadPubs = useCallback(() => api.publications(id).then(setPubs).catch(() => undefined), [id]);
  useEffect(() => {
    loadPubs();
  }, [loadPubs]);
  const uploading = pubs.some((p) => ACTIVE.includes(p.status));
  useEffect(() => {
    if (!uploading) return;
    const t = setTimeout(loadPubs, 1500);
    return () => clearTimeout(t);
  }, [uploading, pubs, loadPubs]);

  // Posts Autopilot planned for this clip (they are approved and published on their own page).
  const planned = usePoll(loadPosts, [id], 15000, () => true);
  const posts = (planned.data?.items || []).filter((p) => p.clip_id === id);

  const dirtyKeys = (Object.keys(meta) as (keyof Meta)[]).filter((k) => meta[k] !== saved[k]);
  /** Keep the clip's post text in step with what is actually published or exported. */
  const saveMeta = async () => {
    if (!clip || !dirtyKeys.length) return;
    const c = await api.patchClip(clip.id, {
      post: { title: meta.title, caption: meta.caption, hashtags: tagList(meta.hashtags) },
    });
    setClip(c);
    setSaved(meta);
  };
  const guard = useMemo(() => (dirtyKeys.length ? {
    what: `Post text (${dirtyKeys.join(", ")})`,
    save: saveMeta, discard: () => setMeta(saved),
  } : null), [dirtyKeys.join(), meta, saved]); // eslint-disable-line react-hooks/exhaustive-deps
  useLeaveGuard(guard);

  /** One upload per chosen account, one after another. One that is refused never stops the others. */
  const publish = async (platform: Platform, chosen: Connection[], body: Record<string, unknown>) => {
    await saveMeta();
    const started: string[] = [];
    const failed: string[] = [];
    let only: unknown = null;
    for (const c of chosen) {
      try {
        const p = await api.publish(id, platform, { ...body, confirm: true, connection_id: c.id,
          expected_account_id: c.account_id });
        setPubs((list) => [p, ...list]);
        started.push(accountName(c));
      } catch (e) {
        only = e;
        failed.push(`${accountName(c)}: ${errorText(e)}`);
      }
    }
    if (!started.length) throw chosen.length === 1 ? only : new Error(failed.join(" "));
    const names = nameList(started);
    const one = started.length === 1;
    const lead = platform === "youtube" ? `Started ${one ? "the YouTube upload" : "YouTube uploads"} to ${names}.`
      : body.mode === "inbox"
        ? `Sending ${one ? "the draft to the TikTok inbox" : "drafts to the TikTok inboxes"} of ${names}.`
        : `Started ${one ? "the TikTok post" : "TikTok posts"} to ${names}.`;
    toast([lead, ...failed].join(" "), failed.length > 0);
  };

  const exportClip = async () => {
    if (!clip) return;
    setExporting(true);
    try {
      await saveMeta();
      await downloadZip(clip.project_id, [clip.id]);
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setExporting(false);
    }
  };

  if (loadError) {
    return (
      <div className="page">
        <PageHead title="Prepare post" crumbs={[{ label: "Projects", href: "#/projects" }, { label: "Prepare post" }]} />
        <EmptyState icon="alert" title="This clip could not be opened"
          actions={<a className="btn" href="#/projects">Open Projects</a>}>{loadError}</EmptyState>
      </div>
    );
  }
  if (!clip || !project) return <LoadingPage label="Loading the clip" />;
  const ready = clip.status === "ready" && clip.has_video
    && (!version || (version.status === "ready" && version.has_video));
  const post = clip.post || {};
  const duration = version?.duration ?? clip.duration;
  const videoUrl = version ? versionVideoUrl(clip, version) : `/api/clips/${clip.id}/video?v=${clip.version}`;
  const thumbUrl = version ? versionThumbUrl(clip, version) : clipThumbUrl(clip);
  const downloadUrl = versionDownloadUrl(clip, version);
  const acc = (p: Platform) => accounts?.[p];
  // An old upload has no account of its own: it went to the platform's default account.
  const pubConnection = (p: Publication) =>
    p.connection_id || conns?.find((c) => c.platform === p.platform && c.is_default)?.id || "";
  const pubAccount = (p: Publication) => {
    const c = conns?.find((x) => x.id === pubConnection(p));
    return c ? accountName(c) : "";
  };
  const channels = (platform: Platform): ChannelProps => ({
    rows: conns, ticked: ticks?.[platform] ?? null, pubs, pubConnection,
    onTick: (ids) => setTicks((t) => t && { ...t, [platform]: ids }),
  });
  const setM = (patch: Partial<Meta>) => setMeta((m) => ({ ...m, ...patch }));

  return (
    <div className="page">
      <PageHead title="Prepare post"
        crumbs={[
          { label: "Projects", href: "#/projects" },
          { label: <span className="clamp-1 crumb-title">{project.name}</span>, href: `#/project/${project.id}` },
          { label: <span className="clamp-1 crumb-title">{clip.title}</span>, href: `#/clip/${clip.id}` },
          { label: "Prepare post" },
        ]}
        sub={<>Post this clip yourself, now. Nothing goes out until you press a platform's button and confirm. Posts
          Autopilot planned are in <a className="textlink" href="#/publishing/review">Publishing</a>.</>}
        actions={<>
          <a className="btn" href={`#/clip/${clip.id}`}><Icon name="edit" />Edit clip</a>
          <button type="button" className="btn" disabled={!ready || exporting} onClick={exportClip}>
            {exporting ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="download" />}
            {exporting ? "Preparing the download…" : "Save to computer"}
          </button>
        </>} />

      <div className="review">
        <div className="stack-3">
          <div className="player-wrap">
            <div className="player">
              {ready ? (
                <video key={videoUrl} src={videoUrl} poster={clip.has_thumbnail ? thumbUrl : undefined} controls
                  playsInline preload="metadata" aria-label={`Video: ${clip.title}`} />
              ) : (
                <span className="missing">
                  <Icon name="film" />Not rendered yet. {clip.error || "Render the clip in the editor first."}
                </span>
              )}
            </div>
          </div>
          <p className="small muted">
            Posting version: <b>{version?.id ? version.label : "Original"}</b> · {fmtTime(duration)} · 1080×1920.{" "}
            <a className="textlink" href={`#/clip/${clip.id}`}>Change it in the editor</a>
          </p>
          <div className="row wrap">
            <ScoreBadge score={clip.score} />
            <a className="btn btn-small btn-quiet" href={ready ? downloadUrl : undefined}
              aria-disabled={!ready || undefined} download={ready || undefined}>
              <Icon name="download" />Download MP4
            </a>
          </div>
        </div>

        <div className="stack-4">
          {posts.length > 0 && <PlannedPosts posts={posts} tz={planned.data?.timezone || st?.timezone} />}

          <section className="panel" aria-labelledby="pp-text">
            <div className="stack" style={{ gap: 2 }}>
              <h2 id="pp-text">Post text</h2>
              <p className="tiny faint">Used for both platforms · written from the clip's own words · edit anything</p>
            </div>
            <div className="field">
              <label htmlFor="pp-title">
                Title{" "}
                <span className={`hint tnum ${meta.title.length > 100 ? "bad-text" : ""}`}>
                  {meta.title.length}/100
                </span>
              </label>
              <input id="pp-title" type="text" value={meta.title} onChange={(e) => setM({ title: e.target.value })}
                aria-invalid={meta.title.length > 100 || undefined} />
            </div>
            <Suggestions label="Title suggestions" items={post.titles || []} current={meta.title}
              recommended={post.recommended_title} onPick={(t) => setM({ title: t })} />
            <div className="field">
              <label htmlFor="pp-cap">
                Description or caption <span className="hint tnum">{meta.caption.length} characters</span>
              </label>
              <textarea id="pp-cap" rows={4} value={meta.caption} onChange={(e) => setM({ caption: e.target.value })} />
            </div>
            <Suggestions label="Caption suggestions" items={post.captions || []} current={meta.caption}
              onPick={(t) => setM({ caption: t })} />
            {post.cta && !meta.caption.includes(post.cta) && (
              <div className="row wrap">
                <button type="button" className="btn btn-small btn-quiet"
                  onClick={() => setM({ caption: `${meta.caption.trim()} ${post.cta}`.trim() })}>
                  Add the call to action: “{post.cta}”
                </button>
              </div>
            )}
            <div className="field">
              <label htmlFor="pp-tags">Hashtags</label>
              <input id="pp-tags" type="text" value={meta.hashtags} onChange={(e) => setM({ hashtags: e.target.value })}
              />
            </div>
            <p className="tiny faint">
              Your edits are saved with the clip when you publish or export{dirtyKeys.length ? " (not saved yet)" : ""}.
            </p>
          </section>

          <YouTubePanel audience={audience?.youtube} account={acc("youtube")} setAccounts={changeAccounts}
            meta={meta} duration={duration} ready={ready} onPublish={publish} {...channels("youtube")} />
          <TikTokPanel audience={audience?.tiktok} account={acc("tiktok")} setAccounts={changeAccounts}
            meta={meta} duration={duration} ready={ready} onPublish={publish} {...channels("tiktok")}
            onExport={exportClip} downloadUrl={downloadUrl} />

          <section className="panel tight" aria-labelledby="pp-status">
            <h2 id="pp-status" style={{ fontSize: "var(--fs-h3)" }}>Uploads you started here</h2>
            {pubs.length ? (
              <div className="pubs">
                {pubs.map((p) => (
                  <PubRow key={p.id} p={p} account={pubAccount(p)}
                    onChange={(np) => setPubs((l) => l.map((x) => (x.id === np.id ? np : x)))} />
                ))}
              </div>
            ) : <p className="small muted">None yet.</p>}
          </section>
        </div>
      </div>
    </div>
  );
}

function Suggestions({ label, items, current, recommended, onPick }: {
  label: string; items: string[]; current: string; recommended?: number; onPick: (t: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="chips" role="group" aria-label={label}>
      {items.map((t, i) => (
        <button key={i} type="button" className="chip" aria-pressed={t === current} onClick={() => onPick(t)} title={t}>
          {i === recommended && <span aria-label="Recommended">★ </span>}{t.length > 80 ? `${t.slice(0, 80)}…` : t}
        </button>
      ))}
    </div>
  );
}

function PlannedPosts({ posts, tz }: { posts: Post[]; tz?: string }) {
  return (
    <section className="panel tight" aria-labelledby="pp-posts">
      <h2 id="pp-posts" style={{ fontSize: "var(--fs-h3)" }}>Posts of this clip</h2>
      <p className="tiny faint">Planned by Autopilot. Each one is approved, changed or canceled on its own page.</p>
      <div className="rows">
        {posts.map((p) => {
          const s = postStatus(p);
          return (
            <div key={p.id} className="row wrap" style={{ padding: "8px 0" }}>
              <PlatformName platform={p.platform} />
              <span className="small faint tnum">{timeLabel(p.planned_at, tz)}</span>
              <span className="grow" />
              <Pill tone={s.tone} icon={s.icon}>{s.word}</Pill>
              <a className="btn btn-small" href={`#/post/${p.id}`}
                aria-label={`Open the ${p.platform === "youtube" ? "YouTube" : "TikTok"} post: ${s.word}`}>Open</a>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ one panel per platform
type Ticks = Record<Platform, string[]>;

/** The project's own upload request ("Make & upload clips"): the accounts it chose, if any. */
function projectConnections(p: Project): string[] {
  const d = (p as Project & { destinations?: unknown }).destinations;
  const ids = d && typeof d === "object" && !Array.isArray(d) ? (d as { connections?: unknown }).connections : null;
  return Array.isArray(ids) ? ids.filter((x): x is string => typeof x === "string") : [];
}

const outcomeUnknown = (p: Publication) => !!p.info?.outcome_unknown || p.info?.code === "outcome_unknown";
const canDirectPost = (c: Connection) => c.can_direct_post ?? (c.scopes || []).includes("video.publish");
const canInbox = (c: Connection) => c.can_inbox ?? (c.scopes || []).includes("video.upload");

/** Which accounts of a platform are ticked, and what this clip's uploads to each of them are doing. */
type ChannelProps = {
  rows: Connection[] | null; ticked: string[] | null; onTick: (ids: string[]) => void;
  pubs: Publication[]; pubConnection: (p: Publication) => string;
};
function channelsOf(platform: Platform, { rows, ticked, pubs, pubConnection }: ChannelProps) {
  const list = rows ? rows.filter((r) => r.platform === platform) : null;
  const chosen = list && ticked
    ? ticked.map((cid) => list.find((r) => r.id === cid)).filter((r): r is Connection => !!r && isPostable(r)) : [];
  const has = (c: Connection, test: (p: Publication) => boolean) =>
    pubs.some((p) => p.platform === platform && pubConnection(p) === c.id && test(p));
  return {
    loading: !list || !ticked,
    connected: !!list?.some(isPostable),
    chosen,
    names: chosen.map(accountName),
    /** Still uploading to it: another upload of this clip to the same account waits. */
    active: chosen.filter((c) => has(c, (p) => ACTIVE.includes(p.status) && !outcomeUnknown(p))),
    /** Its last upload's outcome is unknown: find out before uploading again. */
    unknown: chosen.filter((c) => has(c, outcomeUnknown)),
    /** This clip is already on it. */
    posted: chosen.filter((c) => has(c, (p) => p.status === "done")),
    /** This clip already waits in its TikTok inbox as a draft. */
    drafted: chosen.filter((c) => has(c, (p) => p.status === "action_needed")),
  };
}

type PanelProps = ChannelProps & {
  audience?: AudienceDestination; account?: PlatformAccount; setAccounts: (a: Accounts) => void;
  meta: Meta; duration: number; ready: boolean;
  onPublish: (platform: Platform, chosen: Connection[], body: Record<string, unknown>) => Promise<void>;
};

function PlatformPanel({ id, name, account, platform, setAccounts, connected, children }: {
  id: string; name: string; account?: PlatformAccount; platform: Platform;
  setAccounts: (a: Accounts) => void; connected: boolean | null; children: ReactNode;
}) {
  return (
    <section className="panel" aria-labelledby={id}>
      <div className="panel-head">
        <h2 id={id}>{name}</h2>
        {connected === false && (
          <div className="row wrap">
            <AccountBadge platform={platform} account={account} />
            <ConnectButton platform={platform} account={account} onChange={setAccounts} />
          </div>
        )}
      </div>
      {account && !account.configured && (
        <p className="small muted">
          Set up {platform === "youtube" ? "YouTube" : "TikTok"} once in{" "}
          <a className="textlink" href="#/settings">Settings, Accounts</a> (your own free developer app), then connect.
        </p>
      )}
      {children}
    </section>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="small break"><Pill tone="warn" icon="alert">Note</Pill> {children}</p>;
}

/** The accounts of one platform this post goes to (loaded with the page, ticked as Accounts says). */
function PanelChannels({ platform, rows, ticked, onTick }: ChannelProps & { platform: Platform }) {
  if (!rows || !ticked) return <p className="muted small">Loading accounts…</p>;
  return <ChannelPicker platforms={[platform]} rows={rows} value={ticked} onChange={(ids) => onTick(ids)}
    idPrefix={`pp-${platform}-to`} legend={platform === "youtube" ? "YouTube channels to publish to"
      : "TikTok accounts to post to"} />;
}

/** "Already posted to A; this posts it there again." for each chosen account that has this clip already. */
function AgainNotes({ posted, drafted = [] }: { posted: Connection[]; drafted?: Connection[] }) {
  return <>
    {posted.map((c) => (
      <Note key={c.id}>Already posted to {accountName(c)}; this posts it there again.</Note>
    ))}
    {drafted.filter((c) => !posted.includes(c)).map((c) => (
      <Note key={c.id}>Already sent to {accountName(c)}'s TikTok inbox as a draft; this sends it there again.</Note>
    ))}
  </>;
}

function YouTubePanel(props: PanelProps) {
  const { audience, account, setAccounts, meta, duration, ready, onPublish } = props;
  const ch = channelsOf("youtube", props);
  const n = ch.chosen.length;
  const privacy = audience?.intent === "PUBLIC" ? "public" : "private";
  const [kids, setKids] = useState<"" | "no" | "yes">("");
  const [shortsTag, setShortsTag] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const tags = tagList(meta.hashtags);
  const description = useMemo(() => {
    const t = shortsTag && !tags.some((x) => x.toLowerCase() === "#shorts") ? [...tags, "#Shorts"] : tags;
    return [meta.caption.trim(), t.join(" ")].filter(Boolean).join("\n\n");
  }, [meta.caption, meta.hashtags, shortsTag]); // eslint-disable-line react-hooks/exhaustive-deps
  const busy = ch.active.length > 0;
  const unknown = ch.unknown.length > 0;
  const missing = [
    !ready && "render the clip first",
    ch.loading && "wait for your accounts to load",
    !ch.loading && !ch.connected && "connect YouTube",
    ch.connected && !n && "choose at least one channel",
    ...ch.active.map((c) => `wait for the upload to ${accountName(c)} to finish`),
    ...ch.unknown.map((c) => `check the outcome of the upload to ${accountName(c)} below`),
    (!audience?.confirmed || audience.intent === "LOCAL_ONLY") && "confirm who watches in Settings → Integrations",
    !!audience?.halted && "resolve the audience warning in Settings → Integrations",
    !meta.title.trim() && "enter a title",
    meta.title.length > 100 && "shorten the title to 100 characters",
    new TextEncoder().encode(description).length > 5000 && "shorten the description",
    !kids && "answer “made for kids”",
  ].filter(Boolean) as string[];
  const privacyWord = privacy === "public" ? "Public" : "Private";

  return (
    <PlatformPanel id="pp-youtube" name="YouTube Shorts" platform="youtube" account={account} setAccounts={setAccounts}
      connected={ch.loading ? null : ch.connected}>
      <PanelChannels platform="youtube" {...props} />
      <div className="field">
        <span className="label">Who can see it</span>
        <span>{privacy === "public" ? "Public: anyone can watch" : audience?.label || "Private"}</span>
        <span className="hint">
          {privacy === "public" ? "Your confirmed audience is Public. The upload record shows the visibility "
            + "YouTube actually returned; it reports a restriction if Public is not confirmed."
            : audience?.intent === "OWNER_ONLY" ? "Private staging: nobody else can watch."
              : "Private: share it with invited viewers in YouTube Studio → Content → this video → Visibility "
                + "→ Private → Share privately."}
          {" "}<a className="textlink" href="#/settings/integrations">Change the audience for new posts</a>
        </span>
      </div>
      <fieldset>
        <legend className="label">Made for kids <span className="hint">(YouTube requires an answer)</span></legend>
        <label className="choice">
          <input type="radio" name="pp-kids" checked={kids === "no"} onChange={() => setKids("no")} />
          <span>No, it's not made for kids</span>
        </label>
        <label className="choice">
          <input type="radio" name="pp-kids" checked={kids === "yes"} onChange={() => setKids("yes")} />
          <span>Yes, it's made for kids</span>
        </label>
        <YouTubeComments privacy={privacy} kids={kids === "yes" ? true : kids === "no" ? false : null} />
      </fieldset>
      <label className="choice">
        <input type="checkbox" checked={shortsTag} onChange={(e) => setShortsTag(e.target.checked)} />
        <span>Add #Shorts to the description (optional; vertical videos up to 3 minutes are Shorts anyway)</span>
      </label>
      {duration > 180 && (
        <Note>This clip is longer than 3 minutes, so YouTube publishes it as a regular video, not a Short.</Note>
      )}
      <Disclosure plain summary="Description as it will appear on YouTube">
        <pre className="desc-preview">{description || "(empty)"}</pre>
      </Disclosure>
      <div className="row wrap">
        <span className="small muted grow">
          {missing.length ? `To publish: ${missing.join(", ")}.`
            : `Uploads to ${nameList(ch.names)} as ${privacyWord}.`}
        </span>
        <button type="button" className="btn btn-primary" aria-disabled={missing.length > 0 || undefined}
          onClick={() => (missing.length ? toast(`To publish: ${missing.join(", ")}.`, true) : setConfirming(true))}>
          {busy && !unknown ? <span className="inline-spinner" aria-hidden="true" />
            : <Icon name={unknown ? "question" : "upload"} />}
          {unknown ? "Check upload outcome below" : busy ? "Uploading…"
            : n > 1 ? `Publish to ${n} YouTube channels now…` : "Publish to YouTube now…"}
        </button>
      </div>
      {confirming && (
        <ConfirmDialog title={n > 1 ? `Publish to ${n} YouTube channels now?` : "Publish to YouTube now?"}
          confirmLabel="Publish now" cancelLabel="Not now" wide onClose={() => setConfirming(false)}
          onConfirm={() => onPublish("youtube", ch.chosen, {
            title: meta.title.trim(), description, tags, privacy, made_for_kids: kids === "yes",
          })}>
          <dl className="kv">
            <dt>{n > 1 ? "Channels" : "Channel"}</dt><dd>{nameList(ch.names)}</dd>
            <dt>Title</dt><dd>{meta.title}</dd>
            <dt>Who can see it</dt><dd>{privacyWord}</dd>
            <dt>Made for kids</dt><dd>{kids === "yes" ? "Yes" : "No"}</dd>
            <dt>Tags</dt><dd>{tags.join(" ") || "None"}</dd>
            <dt>When</dt><dd>Right away</dd>
          </dl>
          <AgainNotes posted={ch.posted} />
          <div className="consequence">
            <span>
              {n > 1 ? `This starts ${n} separate uploads, one to each channel. ` : ""}
              {privacy === "public" ? "This requests a Public upload now: anyone may watch or share it if YouTube "
                + "allows public API uploads for your project." : "This uploads it as Private; you choose any viewers "
                  + "in YouTube Studio yourself."}
              {" "}ClipForge cannot take an upload back; you would delete it in YouTube Studio.
              {n > 1 ? " Each upload uses" : " It uses"} part of your project's daily YouTube upload allowance.
            </span>
          </div>
        </ConfirmDialog>
      )}
    </PlatformPanel>
  );
}

function TikTokPanel(props: PanelProps & { onExport: () => void; downloadUrl: string }) {
  const { audience, account, setAccounts, meta, duration, ready, onPublish, onExport, downloadUrl } = props;
  const ch = channelsOf("tiktok", props);
  const n = ch.chosen.length;
  const [creators, setCreators] = useState<Record<string, TikTokCreator>>({});
  const [creatorErrors, setCreatorErrors] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<"direct" | "inbox">("direct");
  // True while "inbox" was chosen for the owner (a ticked account has no Direct Post), not by the owner.
  const forcedInbox = useRef(false);
  const pickMode = (m: "direct" | "inbox") => {
    forcedInbox.current = false;
    setMode(m);
  };
  const [privacy, setPrivacy] = useState("");
  const [allow, setAllow] = useState({ comment: false, duet: false, stitch: false });
  const [disclose, setDisclose] = useState(false);
  const [brandOrganic, setBrandOrganic] = useState(false);
  const [brandContent, setBrandContent] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // Direct Post (or an inbox draft) only when every chosen account allows it.
  const directOk = n > 0 && ch.chosen.every(canDirectPost);
  const inboxOk = n > 0 && ch.chosen.every(canInbox);

  // TikTok's sharing guidelines: read each chosen account's options fresh before posting.
  const chosenKey = ch.chosen.map((c) => `${c.id}:${c.connected_at}:${canDirectPost(c) ? 1 : 0}`).join("|");
  useEffect(() => {
    setPrivacy("");
    setCreators({});
    setCreatorErrors({});
    if (!n) return;
    if (!directOk) {
      if (mode === "direct") forcedInbox.current = true;
      setMode("inbox");
      return;
    }
    if (forcedInbox.current) {  // every ticked account has Direct Post again: back to what the owner had chosen
      forcedInbox.current = false;
      setMode("direct");
    }
    let alive = true;
    for (const c of ch.chosen) {
      api.tiktokCreator(c.id)
        .then((info) => alive && setCreators((m) => ({ ...m, [c.id]: info })))
        .catch((e) => alive && setCreatorErrors((m) => ({ ...m, [c.id]: errorText(e) })));
    }
    return () => {
      alive = false;
    };
  }, [chosenKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const caption = [meta.caption.trim(), tagList(meta.hashtags).join(" ")].filter(Boolean).join(" ");
  const audited = !!account?.audited;
  const publicPosts = audience?.intent === "PUBLIC";
  const who = publicPosts ? "Everyone (Public)" : audience?.intent === "OWNER_ONLY" ? "Only me"
    : audience?.group === "friends" ? "Friends" : "Followers";
  const expected = publicPosts ? "PUBLIC_TO_EVERYONE" : audience?.intent === "OWNER_ONLY" ? "SELF_ONLY"
    : audience?.group === "friends" ? "MUTUAL_FOLLOW_FRIENDS" : "FOLLOWER_OF_CREATOR";
  const direct = mode === "direct";
  const branded = direct && disclose && brandContent;
  const label = disclose ? (brandContent ? "Paid partnership" : brandOrganic ? "Promotional content" : "") : "";
  // What every chosen account allows right now: the strictest of their current TikTok options.
  const infos = ch.chosen.map((c) => creators[c.id]).filter((x): x is TikTokCreator => !!x);
  const readAll = n > 0 && infos.length === n;
  const lacking = ch.chosen.filter((c) => creators[c.id] && !creators[c.id].privacy_options.includes(expected));
  const offered = readAll && !lacking.length ? [expected] : [];
  const off = (k: "comment" | "duet" | "stitch") => infos.some((info) => info[`${k}_disabled`]);
  const limits = infos.map((info) => info.max_duration).filter((s) => s > 0);
  const maxDuration = limits.length ? Math.min(...limits) : 0;
  const allowed = (["comment", "duet", "stitch"] as const).filter((k) => allow[k] && !off(k)).join(", ");
  const postingNames = ch.chosen.map((c) => creators[c.id]?.nickname || accountName(c));
  const busy = ch.active.length > 0;
  const missing = [
    !ready && "render the clip first",
    ch.loading && "wait for your accounts to load",
    !ch.loading && !ch.connected && "connect TikTok",
    ch.connected && !n && "choose at least one account",
    ...ch.active.map((c) => `wait for the upload to ${accountName(c)} to finish`),
    ...ch.unknown.map((c) => `check the outcome of the upload to ${accountName(c)} below`),
    (!audience?.confirmed || audience.intent === "LOCAL_ONLY") && "confirm who watches in Settings → Integrations",
    !!audience?.halted && "resolve the audience warning in Settings → Integrations",
    !direct && n > 0 && !inboxOk && "get TikTok approval for inbox uploads, or download and post it yourself",
    direct && n > 0 && !readAll && "read TikTok’s current posting options",
    caption.length > 2200 && "shorten the caption to 2,200 characters",
    direct && !privacy && "choose who can see it",
    direct && disclose && !brandOrganic && !brandContent && "choose what the commercial content is",
    branded && privacy && !["MUTUAL_FOLLOW_FRIENDS", "PUBLIC_TO_EVERYONE"].includes(privacy)
      && "branded content needs Friends or Everyone",
    direct && !audited && privacy && privacy !== "SELF_ONLY" && "choose “Only me” (your TikTok app is not audited)",
    direct && maxDuration > 0 && duration > maxDuration && `trim the clip to ${maxDuration} seconds`,
  ].filter(Boolean) as string[];
  const copyCaption = () => {
    if (!navigator.clipboard) {
      toast("Copying is not available in this browser. Select the caption in the text box and copy it.", true);
      return;
    }
    navigator.clipboard.writeText(caption)
      .then(() => toast("Caption copied"), () => toast("The caption could not be copied.", true));
  };

  return (
    <PlatformPanel id="pp-tiktok" name="TikTok" platform="tiktok" account={account} setAccounts={setAccounts}
      connected={ch.loading ? null : ch.connected}>
      <PanelChannels platform="tiktok" {...props} />
      {infos.length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          {ch.chosen.map((c) => {
            const info = creators[c.id];
            if (!info) return null;
            return (
              <p key={c.id} className="small row" style={{ gap: 8 }}>
                {info.avatar && (
                  <img className="avatar" src={info.avatar} alt="" referrerPolicy="no-referrer"
                    onError={(e) => { e.currentTarget.style.display = "none"; }} />
                )}
                <span>
                  Posting as <b>{info.nickname}</b>
                  {info.username ? <span className="muted"> @{info.username}</span> : null}{" "}
                  <span className="faint">(read from TikTok just now)</span>
                </span>
              </p>
            );
          })}
        </div>
      )}
      {ch.chosen.filter((c) => creatorErrors[c.id]).map((c) => (
        <Banner key={c.id} tone="bad" title="TikTok's account details could not be read">
          {n > 1 ? `${accountName(c)}: ` : ""}{creatorErrors[c.id]}
        </Banner>
      ))}
      <fieldset>
        <legend className="label">How to post</legend>
        <label className="choice">
          <input type="radio" name="pp-tt-mode" checked={direct} disabled={n > 0 && !directOk}
            onChange={() => pickMode("direct")} />
          <span>
            <b>Post directly</b> to your profile
            {n > 0 && !directOk ? (n > 1 ? " (not every chosen account has Direct Post permission)"
              : " (your TikTok app has no Direct Post permission)") : ""}
          </span>
        </label>
        <label className="choice">
          <input type="radio" name="pp-tt-mode" checked={!direct} disabled={n > 0 && !inboxOk}
            onChange={() => pickMode("inbox")} />
          <span>
            <b>Send to TikTok inbox</b> as a draft: finish and post it in the TikTok app for {who}. TikTok must
            approve your app for inbox uploads; at most 5 drafts can wait at a time. This is a manual posting step.
          </span>
        </label>
      </fieldset>
      {direct && (
        <>
          <div className="field">
            <label htmlFor="pp-tt-priv">Who can see it</label>
            <select id="pp-tt-priv" value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
              <option value="" disabled>Choose…</option>
              {offered.map((o) => (
                <option key={o} value={o}
                  disabled={(!audited && o !== "SELF_ONLY")
                    || (branded && !["MUTUAL_FOLLOW_FRIENDS", "PUBLIC_TO_EVERYONE"].includes(o))}>
                  {TIKTOK_PRIVACY[o] || o}{!audited && o !== "SELF_ONLY" ? " (needs TikTok's app audit)" : ""}
                  {branded && !["MUTUAL_FOLLOW_FRIENDS", "PUBLIC_TO_EVERYONE"].includes(o)
                    ? " (branded content: Friends or Everyone)" : ""}
                </option>
              ))}
            </select>
            {lacking.length > 0 && (
              <span className="hint warn-text">
                TikTok does not offer {who} for {nameList(lacking.map(accountName))} right now. Untick{" "}
                {lacking.length > 1 ? "those accounts" : "that account"} or check {lacking.length > 1 ? "their" : "its"}
                {" "}privacy settings in TikTok.
              </span>
            )}
          </div>
          <Note>
            Choose {who} explicitly; TikTok offers no preset privacy choice. {!audited ? "Public or selected-viewer "
              + "Direct Post needs TikTok’s audit; an unaudited app can only stage “Only me”. " : ""}
            TikTok requires consent to each post, so unattended TikTok publishing is unavailable.
            {" "}<a className="textlink" href="#/settings/integrations">Change new-post audience</a>.
          </Note>
          <fieldset>
            <legend className="label">Allow viewers to</legend>
            <div className="row wrap" style={{ gap: 16 }}>
              {(["comment", "duet", "stitch"] as const).map((k) => {
                const isOff = off(k);
                return (
                  <label key={k} className="choice" title={isOff ? "Turned off in your TikTok settings" : undefined}>
                    <input type="checkbox" disabled={isOff} checked={allow[k] && !isOff}
                      onChange={(e) => setAllow({ ...allow, [k]: e.target.checked })} />
                    <span>{k[0].toUpperCase() + k.slice(1)}
                      {isOff ? ` (off in TikTok${n > 1 ? " for a chosen account" : ""})` : ""}</span>
                  </label>
                );
              })}
            </div>
          </fieldset>
          <label className="choice">
            <input type="checkbox" checked={disclose} onChange={(e) => {
              setDisclose(e.target.checked);
              if (!e.target.checked) { setBrandOrganic(false); setBrandContent(false); }
            }} />
            <span>This video promotes a brand, product or service (disclose commercial content)</span>
          </label>
          {disclose && (
            <div className="stack" style={{ paddingLeft: 32 }}>
              <label className="choice">
                <input type="checkbox" checked={brandOrganic} onChange={(e) => setBrandOrganic(e.target.checked)} />
                <span><b>Your brand</b>: you promote yourself or your own business</span>
              </label>
              <label className="choice">
                <input type="checkbox" checked={brandContent} onChange={(e) => setBrandContent(e.target.checked)} />
                <span><b>Branded content</b>: you promote another brand or a third party</span>
              </label>
              {label && <span className="small muted">Your video will be labeled “{label}”.</span>}
            </div>
          )}
        </>
      )}
      <p className="tiny faint">
        By posting, you agree to TikTok's{" "}
        {branded && <><a className="textlink" href={BC_POLICY} target="_blank" rel="noreferrer">Branded Content
          Policy</a> and </>}
        <a className="textlink" href={MUSIC_POLICY} target="_blank" rel="noreferrer">Music Usage Confirmation</a>.
      </p>
      <Disclosure plain summary={`Caption as it will appear on TikTok (${caption.length}/2200)`}>
        <pre className="desc-preview">{caption || "(empty)"}</pre>
      </Disclosure>
      <div className="row wrap">
        <span className="small muted grow">
          {missing.length ? `To publish: ${missing.join(", ")}.` : direct
            ? `Posts to ${nameList(postingNames)} (${TIKTOK_PRIVACY[privacy]}).`
            : `Sends a draft to the TikTok inbox of ${nameList(postingNames)}.`}
        </span>
        <button type="button" className="btn btn-primary" aria-disabled={missing.length > 0 || undefined}
          onClick={() => (missing.length ? toast(`To publish: ${missing.join(", ")}.`, true) : setConfirming(true))}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="upload" />}
          {busy ? "Uploading…" : direct ? (n > 1 ? `Post to ${n} TikTok accounts now…` : "Post to TikTok now…")
            : n > 1 ? `Send to ${n} TikTok inboxes…` : "Send to TikTok inbox…"}
        </button>
      </div>
      {(!ch.connected || !audited || (n > 0 && !directOk)) && (
        <Banner tone="warn"
          title={publicPosts ? "TikTok public posting needs a manual step" : "TikTok posting needs setup"}>
          {publicPosts ? "Public Direct Post needs an audited app and Everyone among your account’s current options. "
            : "Direct Post for viewers needs an audited app. "}
          TikTok’s guidelines exclude personal upload utilities and reposting from other platforms; approval may be
          unavailable. Download this clip and post it yourself, or finish an approved inbox draft in TikTok.
          Neither route is automatic public publishing.
        </Banner>
      )}
      <Disclosure plain summary="Download and post it yourself">
        <ol className="steps-list">
          <li>
            <button type="button" className="btn btn-small" onClick={onExport}><Icon name="download" />Save to
              computer</button>
            {" "}or <a className="textlink" href={downloadUrl} download>download the MP4</a>.
          </li>
          <li>
            <button type="button" className="btn btn-small" onClick={copyCaption}>
              <Icon name="copy" />Copy caption
            </button>
            {" "}(text and hashtags).
          </li>
          <li>
            Open <a className="textlink" href={STUDIO_UPLOAD} target="_blank" rel="noreferrer">TikTok Studio,
            Upload</a> (official), choose the MP4, paste the caption, choose <b>{who}</b> and post.
            {publicPosts ? " Your TikTok account must permit public posts." : ""}
          </li>
        </ol>
      </Disclosure>
      {confirming && (
        <ConfirmDialog wide cancelLabel="Not now"
          title={direct ? (n > 1 ? `Post to ${n} TikTok accounts now?` : "Post to TikTok now?")
            : n > 1 ? `Send to ${n} TikTok inboxes?` : "Send to your TikTok inbox?"}
          confirmLabel={direct ? "Post now" : n > 1 ? "Send the drafts" : "Send the draft"}
          onClose={() => setConfirming(false)}
          onConfirm={() => onPublish("tiktok", ch.chosen, {
            description: caption, mode, privacy: direct ? privacy : "", allow_comment: allow.comment && !off("comment"),
            allow_duet: allow.duet && !off("duet"), allow_stitch: allow.stitch && !off("stitch"), disclose,
            brand_organic: brandOrganic, brand_content: brandContent,
          })}>
          <dl className="kv">
            <dt>{n > 1 ? "Accounts" : "Account"}</dt><dd>{nameList(postingNames)}</dd>
            <dt>Caption</dt><dd>{caption || "(empty)"}</dd>
            {direct && <><dt>Who can see it</dt><dd>{TIKTOK_PRIVACY[privacy]}</dd></>}
            {direct && <><dt>Viewers can</dt><dd>{allowed || "Not comment, duet or stitch"}</dd></>}
            {label && <><dt>Label</dt><dd>{label}</dd></>}
            <dt>When</dt><dd>Right away</dd>
          </dl>
          <AgainNotes posted={ch.posted} drafted={ch.drafted} />
          <div className="consequence">
            <span>
              {n > 1 ? `This sends it to ${n} accounts, one after another. ` : ""}
              {direct ? `This posts the video on your TikTok ${n > 1 ? "profiles" : "profile"} now. ClipForge can't `
                + "take it back; you would delete it in the TikTok app. It may take a few minutes to appear."
                : `This sends the video to your TikTok ${n > 1 ? "inboxes" : "inbox"} as a draft now. Nobody else can `
                  + `see it until you post it in the TikTok app for ${who}. This is a manual step, not automatic `
                  + "publishing."}
            </span>
            <span>
              By posting, you agree to TikTok's {branded ? "Branded Content Policy and " : ""}Music Usage Confirmation.
            </span>
          </div>
        </ConfirmDialog>
      )}
    </PlatformPanel>
  );
}

// ------------------------------------------------------------------ uploads started on this page
const STATUS: Record<Publication["status"], [string, Tone, IconName]> = {
  queued: ["Waiting to upload", "info", "clock"], uploading: ["Uploading", "info", "upload"],
  processing: ["Processing on the platform", "info", "clock"], done: ["Done", "good", "check"],
  action_needed: ["Finish in the TikTok app", "info", "info"], failed: ["Failed", "bad", "alert"],
  cancelled: ["Canceled", "neutral", "x"],
};

function PubRow({ p, account, onChange }: { p: Publication; account: string; onChange: (p: Publication) => void }) {
  const [baseWord, baseTone, baseIcon] = STATUS[p.status];
  const setup = p.delivery?.audience_setup || "";
  const delivery: Record<string, [string, Tone, IconName]> = {
    public_api_verified: ["Public (platform confirmed)", "good", "check"],
    public_requested: ["Posted; Public requested", "warn", "question"],
    public_restricted: ["Uploaded; Public not confirmed", "warn", "alert"],
    awaiting_invitations: ["Uploaded; share privately in YouTube Studio", "warn", "user"],
    owner_only: ["Uploaded for you only", "info", "shield"],
  };
  const retryAt = Number(p.info?.retry_at || 0);
  const outcomeUnknown = !!p.info?.outcome_unknown || p.info?.code === "outcome_unknown";
  const [word, tone, icon] = outcomeUnknown ? ["Upload outcome unknown", "warn" as Tone, "question" as IconName]
    : p.status === "done" && delivery[setup] ? delivery[setup]
    : p.status === "queued" && retryAt > Date.now() / 1000
      ? ["Waiting for platform retry time", "warn" as Tone, "clock" as IconName] : [baseWord, baseTone, baseIcon];
  const [canceling, setCanceling] = useState(false);
  const privacy = p.privacy || p.requested_privacy;
  const act = async (fn: () => Promise<Publication>) => {
    try {
      onChange(await fn());
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const name = p.platform === "youtube" ? "YouTube" : p.mode === "inbox" ? "TikTok inbox" : "TikTok";
  return (
    <div className="pub">
      <div className="row wrap">
        <PlatformName platform={p.platform}
          extra={[p.mode === "inbox" ? "inbox" : "", account ? `· ${account}` : ""].filter(Boolean).join(" ")
            || undefined} />
        <Pill tone={tone} icon={icon}>{word}{p.status === "uploading" ? ` ${Math.round(p.progress * 100)}%` : ""}</Pill>
        {privacy && p.status === "done" && <span className="tag">{privacyLabel(p.platform, privacy)}</span>}
        <span className="tiny faint">{new Date(p.created_at * 1000).toLocaleString()}</span>
      </div>
      {(p.status === "uploading" || p.status === "queued") && (
        <ProgressBar value={p.progress} label={`${name} upload`} />
      )}
      {p.status === "queued" && retryAt > Date.now() / 1000 && (
        <span className="small muted">The platform asked to wait until {timeLabel(retryAt)}.
          The same upload resumes then; it is not uploaded twice.</span>
      )}
      {setup === "public_restricted" && <span className="small">YouTube has not confirmed Public.
        Check the video’s visibility and any restrictions in YouTube Studio.</span>}
      {setup === "public_requested" && <span className="small muted">TikTok did not report the post’s actual
        visibility; Everyone was requested.</span>}
      {p.message && <span className="small">{p.message}</span>}
      {p.platform === "youtube" && <YouTubeCommentsResult info={p.info} />}
      {p.error && <span className="small bad-text">{p.error}{p.fix ? <> <b>What to do:</b> {p.fix}</> : null}</span>}
      <span className="tiny faint">“{p.title || p.description.slice(0, 80)}”</span>
      <div className="row wrap">
        {p.url && (
          <a className="btn btn-small" href={p.url} target="_blank" rel="noreferrer">
            <Icon name="external" />Open on {p.platform === "youtube" ? "YouTube" : "TikTok"}
          </a>
        )}
        {p.info?.studio_url && (
          <a className="btn btn-small btn-quiet" href={p.info.studio_url} target="_blank" rel="noreferrer">
            YouTube Studio
          </a>
        )}
        {((p.status === "done" || p.status === "processing" || p.status === "action_needed") && p.remote_id
          || outcomeUnknown) && (
          <button type="button" className="btn btn-small btn-quiet"
            onClick={() => act(() => api.refreshPublication(p.id))}>
            <Icon name="refresh" />Refresh status
          </button>
        )}
        {(p.status === "queued" || p.status === "uploading") && (
          <button type="button" className="btn btn-small btn-danger" onClick={() => setCanceling(true)}>
            Cancel upload…
          </button>
        )}
      </div>
      <PublicationStats p={p} onChange={onChange} />
      {canceling && (
        <ConfirmDialog title={`Cancel the ${name} upload?`} confirmLabel="Cancel the upload"
          cancelLabel="Keep uploading" danger onClose={() => setCanceling(false)}
          onConfirm={async () => onChange(await api.cancelPublication(p.id))}>
          <p className="muted">
            The upload stops. If {p.platform === "youtube" ? "YouTube" : "TikTok"} already received every byte, the
            video may still appear there; check before you upload again.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
