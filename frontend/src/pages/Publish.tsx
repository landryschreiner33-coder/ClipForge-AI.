import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  Accounts, api, Clip, ClipVersion, clipThumbUrl, downloadZip, errorText, fmtTime, Project,
  Publication, TikTokCreator, versionDownloadUrl, versionThumbUrl, versionVideoUrl,
} from "../api";
import { Icon, Modal, ScoreBadge, toast } from "../components/ui";
import { AccountBadge, ConnectButton } from "../components/accounts";
import { StructureChips, SubscoreLine } from "../components/viral";
import { VersionsCard } from "../components/versions";
import { PublicationStats } from "../components/stats";
import { navigate } from "../App";

const TIKTOK_PRIVACY: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers", SELF_ONLY: "Only me",
};
const ACTIVE = ["queued", "uploading", "processing"];

const tagList = (s: string) =>
  s.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));

interface Meta {
  title: string;
  caption: string;
  hashtags: string;
}

/**
 * One screen to publish a clip: preview, editable title / caption / hashtags, privacy per platform, and explicit
 * "Publish to YouTube", "Publish to TikTok" and "Export" buttons. Nothing is posted without pressing a button and
 * confirming.
 */
export default function PublishPage({ id }: { id: string }) {
  const [clip, setClip] = useState<Clip | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [pubs, setPubs] = useState<Publication[]>([]);
  const [meta, setMeta] = useState<Meta>({ title: "", caption: "", hashtags: "" });
  const [metaDirty, setMetaDirty] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [version, setVersion] = useState<ClipVersion | undefined>();
  const onVersions = useCallback((active: ClipVersion | undefined) => setVersion(active), []);

  useEffect(() => {
    (async () => {
      try {
        let c = await api.clip(id);
        if (!c.post?.title && !c.post?.titles?.length) c = await api.regeneratePost(id); // clips from older versions
        setClip(c);
        setMeta({ title: c.post?.title || c.title, caption: c.post?.caption || "", hashtags: (c.post?.hashtags || c.hashtags).join(" ") });
        setProject(await api.project(c.project_id));
      } catch (e) {
        toast(errorText(e), true);
      }
    })();
    api.accounts().then(setAccounts).catch((e) => toast(errorText(e), true));
  }, [id]);

  const loadPubs = useCallback(() => api.publications(id).then(setPubs).catch(() => undefined), [id]);
  useEffect(() => {
    loadPubs();
  }, [loadPubs]);
  const active = pubs.some((p) => ACTIVE.includes(p.status));
  useEffect(() => {
    if (!active) return;
    const t = setTimeout(loadPubs, 1200);
    return () => clearTimeout(t);
  }, [active, pubs, loadPubs]);

  const setM = (patch: Partial<Meta>) => {
    setMeta((m) => ({ ...m, ...patch }));
    setMetaDirty(true);
  };

  /** Keep the post package in step with what is actually published. */
  const saveMeta = async () => {
    if (!clip || !metaDirty) return;
    const c = await api.patchClip(clip.id, { post: { title: meta.title, caption: meta.caption, hashtags: tagList(meta.hashtags) } });
    setClip(c);
    setMetaDirty(false);
  };

  const publish = async (platform: "youtube" | "tiktok", body: Record<string, unknown>) => {
    await saveMeta();
    const p = await api.publish(id, platform, { ...body, confirm: true });
    setPubs((list) => [p, ...list]);
    toast(`${platform === "youtube" ? "YouTube" : "TikTok"} upload started`);
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

  if (!clip || !project) return <div className="page"><div className="spinner" /></div>;
  const ready = clip.status === "ready" && clip.has_video && (!version || (version.status === "ready" && version.has_video));
  const post = clip.post || {};
  const duration = version?.duration ?? clip.duration;
  const videoUrl = version ? versionVideoUrl(clip, version) : `/api/clips/${clip.id}/video?v=${clip.version}`;
  const thumbUrl = version ? versionThumbUrl(clip, version) : clipThumbUrl(clip);

  return (
    <div className="page">
      <div className="crumbs">
        <a href="#/projects">Projects</a> / <a href={`#/project/${project.id}`}>{project.name}</a> / Publish
      </div>
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: 22 }}>Publish clip</h1>
          <p>Review the clip and its text, choose privacy, then publish. Nothing is posted until you press a Publish button and confirm.</p>
        </div>
        <div className="row">
          <button className="btn ghost" onClick={() => navigate(`/clip/${clip.id}`)}><Icon name="edit" size={16} /> Edit clip</button>
          <button className="btn" disabled={!ready || exporting} onClick={exportClip}>
            <Icon name="zip" size={16} /> {exporting ? "Preparing..." : "Export"}
          </button>
        </div>
      </div>

      <div className="publish">
        <div className="player">
          {ready ? (
            <video key={videoUrl} src={videoUrl} poster={clip.has_thumbnail ? thumbUrl : undefined} controls playsInline />
          ) : (
            <div className="rendering"><span className="badge warn">Not rendered yet</span><div className="small muted">{clip.error || "Render the clip first."}</div></div>
          )}
          <div className="card mt-s" style={{ padding: 14 }}>
            <div className="row between"><ScoreBadge score={clip.score} /><span className="small muted">{version ? `${version.label} · ` : ""}{fmtTime(duration)} · 1080×1920</span></div>
            <SubscoreLine c={clip} />
            <StructureChips c={clip} />
            <a className="btn sm mt-s" href={ready ? versionDownloadUrl(clip, version) : undefined} style={ready ? undefined : { opacity: 0.45, pointerEvents: "none" }}>
              <Icon name="download" size={13} /> Download MP4
            </a>
          </div>
        </div>

        <div className="publish-side">
          <VersionsCard clip={clip} onChange={onVersions} />

          <div className="card">
            <h3>Post text <span className="muted small" style={{ fontWeight: 400 }}>used for both platforms · {post.source || "your text"}</span></h3>
            <label className="field">
              <span className="row between">Title <span className={`small ${meta.title.length > 100 ? "bad-text" : "muted"}`}>{meta.title.length}/100</span></span>
              <input type="text" value={meta.title} onChange={(e) => setM({ title: e.target.value })} />
            </label>
            <Options items={post.titles || []} current={meta.title} onPick={(t) => setM({ title: t })} recommended={post.recommended_title} />
            <label className="field mt">
              <span className="row between">Description / caption <span className="small muted">{meta.caption.length} characters</span></span>
              <textarea rows={4} value={meta.caption} onChange={(e) => setM({ caption: e.target.value })} />
            </label>
            <Options items={post.captions || []} current={meta.caption} onPick={(t) => setM({ caption: t })} />
            <div className="row wrap mt-s" style={{ gap: 6 }}>
              {post.cta && !meta.caption.includes(post.cta) && (
                <button className="btn sm ghost" onClick={() => setM({ caption: `${meta.caption.trim()} ${post.cta}`.trim() })}>+ Add call to action: “{post.cta}”</button>
              )}
            </div>
            <label className="field mt">Hashtags
              <input type="text" value={meta.hashtags} onChange={(e) => setM({ hashtags: e.target.value })} />
            </label>
            <div className="field-hint mt-s">
              Suggestions come only from this clip's own words. Edit anything; your edits are saved with the clip when you publish or export.
            </div>
          </div>

          <YouTubePanel clip={clip} duration={duration} accounts={accounts} setAccounts={setAccounts} meta={meta} ready={ready} busy={pubs.some((p) => p.platform === "youtube" && ACTIVE.includes(p.status))} onPublish={publish} />
          <TikTokPanel clip={clip} duration={duration} downloadUrl={versionDownloadUrl(clip, version)} accounts={accounts} setAccounts={setAccounts} meta={meta} ready={ready} busy={pubs.some((p) => p.platform === "tiktok" && ACTIVE.includes(p.status))} onPublish={publish} onExport={exportClip} />

          {pubs.length > 0 && (
            <div className="card">
              <h3>Publishing status</h3>
              <div className="pubs">
                {pubs.map((p) => <PubRow key={p.id} p={p} onChange={(np) => setPubs((l) => l.map((x) => (x.id === np.id ? np : x)))} />)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Options({ items, current, onPick, recommended }: { items: string[]; current: string; onPick: (t: string) => void; recommended?: number }) {
  if (!items.length) return null;
  return (
    <div className="options">
      {items.map((t, i) => (
        <button key={i} type="button" className={`opt ${t === current ? "on" : ""}`} onClick={() => onPick(t)} title={t}>
          {i === recommended && <span className="rec">★</span>}{t.length > 90 ? t.slice(0, 90) + "..." : t}
        </button>
      ))}
    </div>
  );
}

function PlatformCard({ name, head, children }: { name: string; head: ReactNode; children: ReactNode }) {
  return (
    <div className="card platform">
      <div className="row between wrap" style={{ marginBottom: 12, gap: 10 }}>
        <h3 style={{ margin: 0 }}>{name}</h3>
        <div className="row wrap">{head}</div>
      </div>
      {children}
    </div>
  );
}

function Confirm({ title, children, label, onConfirm, onClose }: { title: string; children: ReactNode; label: string; onConfirm: () => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal onClose={onClose}>
      <div className="confirm">
        <h3 style={{ marginTop: 0 }}>{title}</h3>
        {children}
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
              onClose();
            } catch (e) {
              toast(errorText(e), true);
              setBusy(false);
            }
          }}>{busy ? "Starting..." : label}</button>
        </div>
      </div>
    </Modal>
  );
}

type PanelProps = {
  clip: Clip;
  duration: number;
  accounts: Accounts | null;
  setAccounts: (a: Accounts) => void;
  meta: Meta;
  ready: boolean;
  busy: boolean;
  onPublish: (platform: "youtube" | "tiktok", body: Record<string, unknown>) => Promise<void>;
};

function YouTubePanel({ duration, accounts, setAccounts, meta, ready, busy, onPublish }: PanelProps) {
  const acc = accounts?.youtube;
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("private");
  const [kids, setKids] = useState<"" | "no" | "yes">("");
  const [shortsTag, setShortsTag] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const tags = tagList(meta.hashtags);
  const description = useMemo(() => {
    const t = shortsTag && !tags.some((x) => x.toLowerCase() === "#shorts") ? [...tags, "#Shorts"] : tags;
    return [meta.caption.trim(), t.join(" ")].filter(Boolean).join("\n\n");
  }, [meta.caption, meta.hashtags, shortsTag]); // eslint-disable-line react-hooks/exhaustive-deps
  const connected = !!acc?.connected && !acc.needs_reconnect;
  const problems = [
    !ready && "render the clip first",
    !connected && "connect YouTube",
    !meta.title.trim() && "enter a title",
    meta.title.length > 100 && "shorten the title to 100 characters",
    new TextEncoder().encode(description).length > 5000 && "shorten the description",
    !kids && "answer “made for kids”",
  ].filter(Boolean) as string[];

  return (
    <PlatformCard name="YouTube Shorts" head={<>
      <AccountBadge platform="youtube" account={acc} />
      <ConnectButton platform="youtube" account={acc} onChange={setAccounts} />
    </>}>
      {!acc?.configured && <div className="notice small block">Set up YouTube once in <a href="#/settings"><b>Settings → Accounts</b></a> (your own free Google Cloud app), then connect.</div>}
      <div className="opt-row"><div className="lbl">Privacy</div>
        <div className="segmented">
          {(["public", "unlisted", "private"] as const).map((p) => (
            <button key={p} type="button" className={privacy === p ? "on" : ""} onClick={() => setPrivacy(p)}>{p[0].toUpperCase() + p.slice(1)}</button>
          ))}
        </div>
      </div>
      {privacy !== "private" && acc?.restriction && <div className="notice warn small block">{acc.restriction}</div>}
      <div className="opt-row"><div className="lbl">Made for kids<small>Required by YouTube (COPPA)</small></div>
        <div className="row">
          <label className="row small"><input type="radio" checked={kids === "no"} onChange={() => setKids("no")} /> No, it's not made for kids</label>
          <label className="row small"><input type="radio" checked={kids === "yes"} onChange={() => setKids("yes")} /> Yes</label>
        </div>
      </div>
      <div className="opt-row"><div className="lbl">#Shorts tag<small>Optional; vertical videos up to 3 min are Shorts anyway</small></div>
        <label className="row small"><input type="checkbox" checked={shortsTag} onChange={(e) => setShortsTag(e.target.checked)} /> Add #Shorts to the description</label>
      </div>
      {duration > 180 && <div className="notice warn small block">This clip is longer than 3 minutes, so YouTube will publish it as a regular video, not a Short.</div>}
      <details className="small mt-s"><summary>Description as it will appear on YouTube</summary><pre className="desc-preview">{description || "(empty)"}</pre></details>
      <div className="row between mt">
        <span className="small muted">{problems.length ? `To publish: ${problems.join(", ")}.` : `Uploads to ${acc?.name} as ${privacy}.`}</span>
        <button className="btn primary" disabled={problems.length > 0 || busy} onClick={() => setConfirming(true)}>
          <Icon name="upload" size={16} /> {busy ? "Uploading..." : "Publish to YouTube"}
        </button>
      </div>
      {confirming && (
        <Confirm title="Publish to YouTube?" label="Publish now" onClose={() => setConfirming(false)}
          onConfirm={() => onPublish("youtube", { title: meta.title.trim(), description, tags, privacy, made_for_kids: kids === "yes" })}>
          <div className="kv">
            <span className="k">Channel</span><span>{acc?.name}</span>
            <span className="k">Title</span><span>{meta.title}</span>
            <span className="k">Privacy</span><span>{privacy[0].toUpperCase() + privacy.slice(1)}</span>
            <span className="k">Made for kids</span><span>{kids === "yes" ? "Yes" : "No"}</span>
            <span className="k">Tags</span><span>{tags.join(" ") || "none"}</span>
          </div>
          {privacy !== "private" && acc?.restriction && <div className="notice warn small block mt">{acc.restriction}</div>}
        </Confirm>
      )}
    </PlatformCard>
  );
}

function TikTokPanel({ duration, accounts, setAccounts, meta, ready, busy, onPublish, onExport, downloadUrl }: PanelProps & { onExport: () => void; downloadUrl: string }) {
  const acc = accounts?.tiktok;
  const connected = !!acc?.connected && !acc.needs_reconnect;
  const [creator, setCreator] = useState<TikTokCreator | null>(null);
  const [creatorError, setCreatorError] = useState("");
  const [mode, setMode] = useState<"direct" | "inbox">("direct");
  const [privacy, setPrivacy] = useState("");
  const [allow, setAllow] = useState({ comment: false, duet: false, stitch: false });
  const [disclose, setDisclose] = useState(false);
  const [brandOrganic, setBrandOrganic] = useState(false);
  const [brandContent, setBrandContent] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [manual, setManual] = useState(false);

  useEffect(() => {
    if (!connected) return;
    if (!acc?.can_direct_post) {
      setMode("inbox");
      return;
    }
    api.tiktokCreator().then((c) => { setCreator(c); setCreatorError(""); }).catch((e) => setCreatorError(errorText(e)));
  }, [connected, acc?.can_direct_post, acc?.connected_at]);

  const caption = [meta.caption.trim(), tagList(meta.hashtags).join(" ")].filter(Boolean).join(" ");
  const audited = !!acc?.audited;
  const direct = mode === "direct";
  const problems = [
    !ready && "render the clip first",
    !connected && "connect TikTok",
    caption.length > 2200 && "shorten the caption to 2200 characters",
    direct && !privacy && "choose who can see it",
    direct && disclose && !brandOrganic && !brandContent && "choose what the commercial content is",
    direct && brandContent && privacy === "SELF_ONLY" && "branded content can't be “Only me”",
    direct && !audited && privacy && privacy !== "SELF_ONLY" && "unaudited apps can only post “Only me”",
    direct && creator && creator.max_duration > 0 && duration > creator.max_duration && `trim to ${creator.max_duration}s`,
  ].filter(Boolean) as string[];
  const branded = direct && disclose && brandContent;
  const label = disclose ? (brandContent ? "Paid partnership" : brandOrganic ? "Promotional content" : "") : "";

  return (
    <PlatformCard name="TikTok" head={<>
      <AccountBadge platform="tiktok" account={acc} />
      <ConnectButton platform="tiktok" account={acc} onChange={setAccounts} />
    </>}>
      {!acc?.configured && <div className="notice small block">Set up TikTok once in <a href="#/settings"><b>Settings → Accounts</b></a> (your own free TikTok developer app), then connect.</div>}
      {connected && creator && (
        <div className="row small" style={{ marginBottom: 8 }}>
          {creator.avatar && <img className="avatar" src={creator.avatar} alt="" referrerPolicy="no-referrer" />}
          Posting as <b>{creator.nickname}</b>{creator.username ? <span className="muted">@{creator.username}</span> : null}
        </div>
      )}
      {creatorError && <div className="notice bad small block">{creatorError}</div>}
      <div className="opt-row"><div className="lbl">How to post</div>
        <div className="grid" style={{ gap: 6 }}>
          <label className={`hook-opt ${direct ? "on" : ""}`} style={!acc?.can_direct_post && connected ? { opacity: 0.5 } : undefined}>
            <input type="radio" checked={direct} disabled={connected && !acc?.can_direct_post} onChange={() => setMode("direct")} />
            <span><b>Post directly</b> to your profile{connected && !acc?.can_direct_post ? " (your app has no Direct Post permission)" : ""}</span>
          </label>
          <label className={`hook-opt ${!direct ? "on" : ""}`}>
            <input type="radio" checked={!direct} onChange={() => setMode("inbox")} />
            <span><b>Send to TikTok inbox</b> as a draft: finish and post it in the TikTok app. Works without TikTok's app audit.</span>
          </label>
        </div>
      </div>
      {direct && !audited && <div className="notice warn small block">{acc?.restriction || "Until TikTok audits your app, Direct Post only works for private accounts and “Only me”."}</div>}
      {direct && (
        <>
          <div className="opt-row"><div className="lbl">Who can see this</div>
            <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
              <option value="" disabled>Choose privacy</option>
              {(creator?.privacy_options || []).map((o) => (
                <option key={o} value={o} disabled={(!audited && o !== "SELF_ONLY") || (branded && o === "SELF_ONLY")}>
                  {TIKTOK_PRIVACY[o] || o}{branded && o === "SELF_ONLY" ? " (not for branded content)" : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="opt-row"><div className="lbl">Allow viewers to</div>
            <div className="row wrap" style={{ gap: 16 }}>
              {(["comment", "duet", "stitch"] as const).map((k) => {
                const off = !!creator?.[`${k}_disabled` as const];
                return (
                  <label key={k} className="row small" style={off ? { opacity: 0.45 } : undefined} title={off ? "Turned off in your TikTok settings" : ""}>
                    <input type="checkbox" disabled={off} checked={allow[k] && !off} onChange={(e) => setAllow({ ...allow, [k]: e.target.checked })} />
                    {k[0].toUpperCase() + k.slice(1)}
                  </label>
                );
              })}
            </div>
          </div>
          <div className="opt-row"><div className="lbl">Disclose commercial content<small>Promotes a brand, product or service</small></div>
            <div>
              <label className="row small"><input type="checkbox" checked={disclose} onChange={(e) => { setDisclose(e.target.checked); if (!e.target.checked) { setBrandOrganic(false); setBrandContent(false); } }} /> This video is commercial content</label>
              {disclose && (
                <div className="grid mt-s" style={{ gap: 6, paddingLeft: 22 }}>
                  <label className="row small"><input type="checkbox" checked={brandOrganic} onChange={(e) => setBrandOrganic(e.target.checked)} /> <span><b>Your brand</b>: you are promoting yourself or your own business</span></label>
                  <label className="row small"><input type="checkbox" checked={brandContent} onChange={(e) => setBrandContent(e.target.checked)} /> <span><b>Branded content</b>: you are promoting another brand or a third party</span></label>
                  {label && <div className="small muted">Your video will be labeled “{label}”.</div>}
                </div>
              )}
            </div>
          </div>
        </>
      )}
      <div className="small muted mt-s">
        By posting, you agree to TikTok's{" "}
        {branded && <><a href="https://www.tiktok.com/legal/page/global/bc-policy/en" target="_blank" rel="noreferrer">Branded Content Policy</a> and </>}
        <a href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank" rel="noreferrer">Music Usage Confirmation</a>.
      </div>
      <details className="small mt-s"><summary>Caption as it will appear on TikTok ({caption.length}/2200)</summary><pre className="desc-preview">{caption || "(empty)"}</pre></details>
      <div className="row between mt">
        <span className="small muted">{problems.length ? `To publish: ${problems.join(", ")}.` : direct ? `Posts to ${creator?.nickname || acc?.name} (${TIKTOK_PRIVACY[privacy]}).` : "Sends a draft to your TikTok inbox."}</span>
        <button className="btn primary" disabled={problems.length > 0 || busy} onClick={() => setConfirming(true)}>
          <Icon name="upload" size={16} /> {busy ? "Uploading..." : "Publish to TikTok"}
        </button>
      </div>
      <div className="mt-s">
        <button className="btn ghost sm" onClick={() => setManual(!manual)}>{manual ? "Hide" : "Can't post through the API?"} Upload it yourself in TikTok</button>
        {manual && (
          <ol className="manual small">
            <li><button className="btn sm" onClick={onExport}><Icon name="zip" size={13} /> Export</button> or <a href={downloadUrl}>download the MP4</a>.</li>
            <li><button className="btn sm" onClick={() => navigator.clipboard?.writeText(caption).then(() => toast("Caption copied"))}>Copy caption</button> (text and hashtags).</li>
            <li>Open <a href="https://www.tiktok.com/tiktokstudio/upload" target="_blank" rel="noreferrer">TikTok Studio → Upload</a> (official), select the MP4, paste the caption, choose privacy and post.</li>
          </ol>
        )}
      </div>
      {confirming && (
        <Confirm title={direct ? "Post to TikTok?" : "Send to your TikTok inbox?"} label={direct ? "Post now" : "Send draft"} onClose={() => setConfirming(false)}
          onConfirm={() => onPublish("tiktok", {
            description: caption, mode, privacy: direct ? privacy : "", allow_comment: allow.comment, allow_duet: allow.duet,
            allow_stitch: allow.stitch, disclose, brand_organic: brandOrganic, brand_content: brandContent,
          })}>
          <div className="kv">
            <span className="k">Account</span><span>{creator?.nickname || acc?.name}</span>
            <span className="k">Caption</span><span>{caption}</span>
            {direct && <><span className="k">Who can see it</span><span>{TIKTOK_PRIVACY[privacy]}</span></>}
            {direct && <><span className="k">Viewers can</span><span>{(["comment", "duet", "stitch"] as const).filter((k) => allow[k]).join(", ") || "not comment, duet or stitch"}</span></>}
            {label && <><span className="k">Label</span><span>{label}</span></>}
          </div>
          <p className="small muted">{direct ? "It may take a few minutes for the video to be processed and appear on your profile." : "You finish and post it in the TikTok app."}</p>
          <p className="small muted">By posting, you agree to TikTok's {branded ? "Branded Content Policy and " : ""}Music Usage Confirmation.</p>
        </Confirm>
      )}
    </PlatformCard>
  );
}

const STATUS: Record<Publication["status"], [string, string]> = {
  queued: ["Waiting", "info"], uploading: ["Uploading", "warn"], processing: ["Processing", "warn"], done: ["Done", "good"],
  action_needed: ["Finish in the app", "info"], failed: ["Failed", "bad"], cancelled: ["Cancelled", ""],
};

function PubRow({ p, onChange }: { p: Publication; onChange: (p: Publication) => void }) {
  const [label, cls] = STATUS[p.status];
  const privacy = p.platform === "tiktok" ? TIKTOK_PRIVACY[p.privacy || p.requested_privacy] : p.privacy || p.requested_privacy;
  const act = async (fn: () => Promise<Publication>) => {
    try {
      onChange(await fn());
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  return (
    <div className="pub">
      <div className="row between wrap">
        <div className="row">
          <b>{p.platform === "youtube" ? "YouTube" : p.mode === "inbox" ? "TikTok inbox" : "TikTok"}</b>
          <span className={`badge ${cls}`}>{label}{p.status === "uploading" ? ` ${Math.round(p.progress * 100)}%` : ""}</span>
          {privacy && p.status === "done" && <span className="badge">{privacy[0].toUpperCase() + privacy.slice(1)}</span>}
          <span className="small muted">{new Date(p.created_at * 1000).toLocaleString()}</span>
        </div>
        <div className="row">
          {p.url && <a className="btn sm" href={p.url} target="_blank" rel="noreferrer">Open</a>}
          {p.info?.studio_url && <a className="btn sm ghost" href={p.info.studio_url} target="_blank" rel="noreferrer">YouTube Studio</a>}
          {(p.status === "done" || p.status === "processing" || p.status === "action_needed") && p.remote_id && (
            <button className="btn sm ghost" onClick={() => act(() => api.refreshPublication(p.id))}><Icon name="refresh" size={12} /> Refresh status</button>
          )}
          {(p.status === "queued" || p.status === "uploading") && <button className="btn sm danger" onClick={() => act(() => api.cancelPublication(p.id))}>Cancel</button>}
        </div>
      </div>
      {(p.status === "uploading" || p.status === "queued") && <div className="bar mt-s"><div style={{ width: `${Math.max(2, p.progress * 100)}%` }} /></div>}
      {p.message && <div className="small mt-s">{p.message}</div>}
      {p.error && <div className="small bad-text mt-s">{p.error}{p.fix ? <> <b>What to do:</b> {p.fix}</> : null}</div>}
      <div className="small muted mt-s">“{p.title || p.description.slice(0, 80)}”</div>
      <PublicationStats p={p} onChange={onChange} />
    </div>
  );
}
