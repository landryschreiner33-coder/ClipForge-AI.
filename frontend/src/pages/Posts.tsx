import { useState } from "react";
import { plural, zoneLine } from "../format";
import { useStatus } from "../status";
import {
  checkSummary, inInbox, loadPosts, mainAction, okOutdated, Post, PostAction, PostActionDialog, postStatus, timeLabel,
  VIEW_OF,
} from "../components/postShared";
import { PostResults } from "../components/postResults";
import { AudienceFacts, ManualPackage, ViewersInvitedButton } from "../components/queueAudience";
import {
  EmptyState, Icon, LinkTabs, MenuItem, MoreMenu, PageHead, Pill, PLATFORM_LABEL, PlatformName, Skel, Thumb, usePoll,
} from "../components/ui";
import "./posts.css";

const VIEWS = ["review", "scheduled", "published", "history", "problems", "manual", "results"];

const INTRO: Record<string, string> = {
  review: "Nothing is posted until it's approved. TikTok needs your OK on every post; YouTube does too unless you " +
    "turned on automatic publishing.",
  published: "Posts that are live on YouTube or TikTok.",
  history: "Published, canceled and replaced posts.",
  problems: "Posts that could not go out, or where ClipFoundry needs you to check something. Nothing here is tried " +
    "again behind your back.",
  manual: "TikTok can't post these to your chosen followers from this app, so each one is a manual posting package: " +
    "the checked video, its caption and the steps. Post it on your phone, then press I posted it.",
};
const EMPTY: Record<string, [string, string]> = {
  review: ["Nothing waits for your OK", "When Autopilot plans a post, it shows up here for your OK."],
  scheduled: ["Nothing is scheduled", "Approved posts wait here for their time."],
  published: ["Nothing published yet", "Posts appear here once they are live."],
  history: ["No history yet", "Published, canceled and replaced posts appear here."],
  problems: ["No problems", "Every post went out, or is waiting for its time or your OK."],
  manual: ["Nothing to post yourself", "Manual posting packages appear here when TikTok can't reach your followers "
    + "through the app."],
};
const VIEW_TITLE: Record<string, string> = {
  review: "Ready for your review", scheduled: "Your posting agenda", published: "Out in the world",
  history: "Posting history", problems: "Let's get these moving", results: "How your posts performed",
  manual: "Manual posting packages",
};

// Problems, grouped by what you do about them (one section each).
const GROUPS: { id: string; label: string; test: (p: Post) => boolean }[] = [
  { id: "reconciling", label: "Upload not confirmed", test: (p) => p.status === "reconciling" },
  { id: "failed", label: "Failed", test: (p) => p.status === "failed" },
  { id: "blocked", label: "Blocked", test: (p) => p.status === "blocked" },
  { id: "inbox", label: "Finish in the TikTok app", test: (p) => inInbox(p) },
  { id: "action", label: "Action needed", test: (p) => p.status === "action_needed" && !inInbox(p) },
];

/**
 * Posts: every planned and published post (one clip on one platform). Needs review, Scheduled, Published (with the
 * canceled and replaced ones as History), Problems and Results. Each row has one action, which opens the post's page,
 * and a More menu. There is no bulk approval: each post gets its own look.
 */
export default function Posts({ view }: { view?: string }) {
  const v = VIEWS.includes(view || "") ? view! : "review";
  const { st } = useStatus();
  const { data, error, refresh, setData } = usePoll(loadPosts, [], 5000, () => true);
  const [dialog, setDialog] = useState<{ action: PostAction; post: Post } | null>(null);
  const items = data?.items || [];
  const tz = data?.timezone || st?.timezone;
  const count = (k: string) => items.filter(VIEW_OF[k]).length;
  const faint = (n: number) => (n ? <span className="faint tiny">{n}</span> : null);
  const tabs = [
    { id: "review", href: "#/queue/review", label: "Needs review", count: count("review"), countTone: "warn" as const },
    { id: "scheduled", href: "#/queue/scheduled", label: <>Scheduled {faint(count("scheduled"))}</> },
    { id: "published", href: "#/queue/published", label: <>Published {faint(count("published"))}</> },
    {
      id: "problems", href: "#/queue/problems", label: "Problems", count: count("problems"), countTone: "bad" as const,
    },
    ...(count("manual") ? [{ id: "manual", href: "#/queue/manual", label: "Post yourself", count: count("manual"),
      countTone: "warn" as const }] : []),
    { id: "results", href: "#/queue/results", label: "Results" },
  ];
  const replace = (p: Post) => {
    setData((d) => d && { ...d, items: d.items.map((x) => (x.id === p.id ? p : x)) });
    refresh();
  };

  return (
    <div className="page posts-page">
      <PageHead title="Queue"
        sub={<>
          Every planned and published post. One clip can have a YouTube post and a TikTok post. {zoneLine(tz)}
        </>} />
      <LinkTabs label="Queue" tabs={tabs} current={v === "history" ? "published" : v} />
      <div className="post-ledger-heading">
        <div className="stack">
          <span className="kind-label">Posting desk</span>
          <h2>{VIEW_TITLE[v]}</h2>
        </div>
        {data && v !== "results" && <span className="small muted">{plural(count(v), "post")}</span>}
      </div>
      {v === "results" ? <PostResults posts={items} /> : !data ? (
        error ? (
          <EmptyState icon="alert" title="Posts could not be loaded"
            actions={<button type="button" className="btn" onClick={refresh}><Icon name="refresh" />Try again</button>}>
            {error}
          </EmptyState>
        ) : (
          <div className="panel tight" aria-busy="true">
            <span className="sr-only" role="status">Loading posts…</span>
            {[0, 1, 2].map((i) => <Skel key={i} className="skel-line" style={{ height: 56 }} />)}
          </div>
        )
      ) : (
        <PostList view={v} items={items.filter(VIEW_OF[v])} autoPublish={data.autoPublish} capped={data.capped}
          setupStarted={st?.home.setup.started ?? true} tz={tz} refresh={refresh}
          onAction={(action, post) => setDialog({ action, post })} />
      )}
      {dialog && (
        <PostActionDialog action={dialog.action} post={dialog.post} tz={tz}
          account={st?.platforms?.[dialog.post.platform]?.name} onClose={() => setDialog(null)} onDone={replace} />
      )}
    </div>
  );
}

function PostList({ view, items, autoPublish, capped, setupStarted, tz, onAction, refresh }: {
  view: string; items: Post[]; autoPublish: boolean; capped: boolean; setupStarted: boolean; tz?: string;
  onAction: (a: PostAction, p: Post) => void; refresh: () => void;
}) {
  const history = view === "history";
  const intro = view === "scheduled"
    ? autoPublish ? "Approved posts go out at their time by themselves. You can still change or cancel them until then."
      : "Approved posts wait for you at their time: posting at the planned time is turned off (Settings, Advanced), " +
        "so each one needs Publish now."
    : INTRO[view];
  const [emptyTitle, emptyText] = EMPTY[view];
  const row = (p: Post) => <PostRow key={p.id} p={p} tz={tz} onAction={onAction} refresh={refresh} />;
  return (
    <>
      <p className="small muted post-list-intro">{intro}</p>
      {(view === "published" || history) && (
        <label className="choice">
          <input type="checkbox" checked={history} onChange={(e) => {
            window.location.hash = e.target.checked ? "#/queue/history" : "#/queue/published";
          }} />
          <span className="small">Also show canceled and replaced posts</span>
        </label>
      )}
      {!items.length ? (
        <EmptyState icon="posts" title={emptyTitle}
          actions={view === "review" && !setupStarted
            ? <a className="btn" href="#/setup">Set up Autopilot</a> : undefined}>
          {emptyText}
        </EmptyState>
      ) : view === "problems" ? (
        GROUPS.map((g) => {
          const list = items.filter(g.test);
          if (!list.length) return null;
          return (
            <section key={g.id} className="panel tight post-problem-group" aria-labelledby={`grp-${g.id}`}>
              <h2 id={`grp-${g.id}`} style={{ fontSize: "var(--fs-h3)" }}>{g.label} ({list.length})</h2>
              <div className="rows">{list.map(row)}</div>
            </section>
          );
        })
      ) : (
        <div className="post-agenda" aria-label="Posts grouped by local day">
          {agendaDays(items, tz, history || view === "published").map((day) => (
            <section key={day.key} className="panel post-agenda-day" aria-labelledby={`post-day-${day.key}`}>
              <div className="panel-head post-day-heading">
                <h2 id={`post-day-${day.key}`}>{day.label}</h2>
                <span className="tiny muted">{plural(day.items.length, "post")}</span>
              </div>
              <div className="rows">{day.items.map(row)}</div>
            </section>
          ))}
        </div>
      )}
      {capped && (view === "published" || history) && (
        <p className="tiny faint">Showing the newest 500 finished posts. Older ones are kept but not listed here.</p>
      )}
    </>
  );
}

/** Use the configured calendar day, so late-evening posts stay with their actual local posting date. */
function agendaDays(items: Post[], tz?: string, newestFirst = false) {
  let timezone = tz;
  try {
    new Intl.DateTimeFormat([], { timeZone: timezone });
  } catch {
    timezone = undefined;
  }
  const calendar = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  });
  const label = new Intl.DateTimeFormat([], {
    timeZone: timezone, weekday: "long", month: "long", day: "numeric", year: "numeric",
  });
  const keyOf = (date: Date) => {
    const parts = calendar.formatToParts(date);
    return ["year", "month", "day"].map((kind) => parts.find((part) => part.type === kind)?.value || "")
      .join("-");
  };
  const today = keyOf(new Date());
  const groups = new Map<string, { key: string; label: string; items: Post[] }>();
  for (const post of items) {
    const date = post.planned_at ? new Date(post.planned_at * 1000) : null;
    const key = date ? keyOf(date) : "unplanned";
    if (!groups.has(key)) groups.set(key, { key,
      label: date ? `${key === today ? "Today · " : ""}${label.format(date)}` : "Time not chosen yet", items: [] });
    groups.get(key)!.items.push(post);
  }
  return [...groups.values()].sort((a, b) => {
    if (a.key === "unplanned") return 1;
    if (b.key === "unplanned") return -1;
    return newestFirst ? b.key.localeCompare(a.key) : a.key.localeCompare(b.key);
  });
}

function PostRow({ p, tz, onAction, refresh }: {
  p: Post; tz?: string; onAction: (a: PostAction, p: Post) => void; refresh: () => void;
}) {
  const { st } = useStatus();
  const s = postStatus(p);
  const name = PLATFORM_LABEL[p.platform] || p.platform;
  const account = st?.platforms?.[p.platform]?.name;
  const href = `#/post/${p.id}`;
  const title = p.title || p.clip.title || "Untitled post";
  const editable = ["awaiting_approval", "approved", "failed"].includes(p.status);
  const cancelable = ["awaiting_approval", "approved", "failed", "action_needed", "blocked"].includes(p.status);
  const items: MenuItem[] = [
    ...(editable ? [{ label: "Change text or time…", href, icon: "edit" as const }] : []),
    ...(p.clip.id ? [{ label: "Open the clip", href: `#/clip/${p.clip.id}`, icon: "scissors" as const }] : []),
    ...(p.publication?.url
      ? [{ label: `Open on ${name}`, href: p.publication.url, external: true, icon: "external" as const }] : []),
    ...(p.source?.url
      ? [{ label: "Open the source video", href: p.source.url, external: true, icon: "link" as const }] : []),
    ...(cancelable ? ["separator" as const,
      { label: "Cancel this post…", danger: true, icon: "x" as const, onSelect: () => onAction("cancel", p) }] : []),
  ];
  return (
    <div className="post-row" data-id={p.id}>
      <a href={href} tabIndex={-1} aria-hidden="true">
        <Thumb src={p.clip.has_thumbnail ? p.clip.thumbnail_url : null} vertical />
      </a>
      <div className="post-main">
        <a className="post-title clamp-2" href={href}>{title}</a>
        <div className="post-meta">
          <PlatformName platform={p.platform} extra={account ? `· ${account}` : undefined} />
          <span className="tnum">{timeLabel(p.planned_at, tz)}</span>
          {p.privacy && <span className="post-privacy">{privacyLabel(p.publication?.privacy || p.privacy)}</span>}
          <Pill tone={s.tone} icon={s.icon}>{s.word}</Pill>
          {p.replaces && p.status === "awaiting_approval" && <span className="tag">Replaces a weaker post</span>}
        </div>
        {/* An approved post's note ("Approved: it will be published…") is out of date once its OK no longer
            covers it. */}
        {okOutdated(p) ? <span className="small">You approved it, but it changed since: it needs your OK again.</span>
          : p.status_note && <span className={`small ${s.tone === "bad" ? "" : "muted"}`}>{p.status_note}</span>}
        <AudienceFacts p={p} />
        <ManualPackage p={p} onDone={refresh} />
        {(p.status === "awaiting_approval" || p.status === "approved") && (
          <span className="tiny faint">
            Permission to use: {p.source?.rights_label || p.source?.rights_status || "unknown"}
            {" "}· Final check: {checkSummary(p)}
          </span>
        )}
      </div>
      <div className="post-actions">
        <ViewersInvitedButton p={p} onDone={refresh} />
        <a className="btn btn-small" href={href}>{mainAction(p)}</a>
        <MoreMenu label={`More for this ${name} post: ${title}`} items={items} />
      </div>
    </div>
  );
}

function privacyLabel(privacy: string): string {
  const labels: Record<string, string> = {
    public: "Public", private: "Private", unlisted: "Unlisted", PUBLIC_TO_EVERYONE: "Public",
    SELF_ONLY: "Only you", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers",
  };
  return labels[privacy] || privacy;
}
