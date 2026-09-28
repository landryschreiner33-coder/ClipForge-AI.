import { useState } from "react";
import { Accounts, api, errorText, fmtTime } from "../api";
import { ap, ITEM_STATUS, localInput, RIGHTS_BADGE, ScheduledItem } from "../autopilot";
import { ApproveDialog } from "../components/approve";
import { Icon, Modal, toast, usePoll } from "../components/ui";

const VIEWS = [
  { value: "upcoming", label: "Upcoming" },
  { value: "problems", label: "Needs attention" },
  { value: "published", label: "Published" },
  { value: "history", label: "History" },
];

/**
 * Publish Center: every scheduled post in one queue. Approve (required by YouTube and TikTok), edit, reschedule,
 * cancel, retry, publish now, open the source or the published post.
 */
export default function PublishCenter({ view: wanted }: { view?: string }) {
  const view = VIEWS.some((x) => x.value === wanted) ? wanted! : "upcoming";
  const setView = (v: string) => { window.location.hash = `#/publish-center/${v}`; };
  const { data, refresh, setData } = usePoll(() => ap.scheduled(view), [view], 4000, () => true);
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [approving, setApproving] = useState<ScheduledItem | null>(null);
  const [editing, setEditing] = useState<ScheduledItem | null>(null);
  const [preview, setPreview] = useState<ScheduledItem | null>(null);

  const replace = (item: ScheduledItem) => setData((d) => d && ({ ...d, items: d.items.map((i) => (i.id === item.id ? item : i)) }));
  const act = async (fn: () => Promise<ScheduledItem>, done?: string) => {
    try {
      replace(await fn());
      if (done) toast(done);
      refresh();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const openApprove = async (item: ScheduledItem) => {
    try {
      setAccounts(accounts || (await api.accounts()));
      setApproving(item);
    } catch (e) {
      toast(errorText(e), true);
    }
  };

  const items = data?.items || [];
  const counts = data?.counts || {};
  const waiting = counts.awaiting_approval || 0;
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Publish Center</h1>
          <p>
            Every scheduled post, in order. YouTube and TikTok require that you approve what is published; approved posts go
            out at their time {data?.auto_publish ? "automatically" : "when you press Publish now (automatic publishing is off)"}.
            Times are in {data?.timezone || "your time zone"}.
          </p>
        </div>
        <div className="segmented">
          {VIEWS.map((v) => (
            <button key={v.value} className={view === v.value ? "on" : ""} onClick={() => setView(v.value)}>
              {v.label}{v.value === "upcoming" && waiting ? ` · ${waiting} to approve` : ""}
            </button>
          ))}
        </div>
      </div>

      {data && browserTz && data.timezone && browserTz !== data.timezone && (
        <div className="notice small">This browser uses {browserTz}; planned times are shown in {data.timezone}. When you reschedule, you pick the time in {browserTz}.</div>
      )}

      {!items.length && (
        <div className="empty card">
          <Icon name="film" size={40} />
          <h3>{view === "upcoming" ? "Nothing scheduled yet" : "Nothing here"}</h3>
          <p>Turn on Autopilot and add sources; packaged clips are scheduled here for your approval.</p>
          <a className="btn" href="#/autopilot">Open Autopilot</a>
        </div>
      )}

      <div className="queue">
        {items.map((it) => {
          const [label, cls] = ITEM_STATUS[it.status] || [it.status, ""];
          const can = (s: string[]) => s.includes(it.status);
          return (
            <div key={it.id} className={`qitem ${it.status}`} data-id={it.id}>
              <div className="qthumb" style={{ backgroundImage: `url(${it.clip.thumbnail_url})` }} onClick={() => setPreview(it)} title="Preview">
                <span className="dur">{fmtTime(it.clip.duration)}</span>
                <div className="play"><Icon name="play" size={18} fill /></div>
              </div>
              <div className="qbody">
                <div className="row wrap" style={{ gap: 6 }}>
                  <span className={`badge ${it.platform === "youtube" ? "bad" : "info"}`}>{it.platform === "youtube" ? "YouTube Shorts" : "TikTok"}</span>
                  <span className={`badge ${cls}`}><span className="dot" /> {label}</span>
                  <span className={`badge ${RIGHTS_BADGE[it.source.rights_status] || ""}`} title="Rights status of the source">{it.source.rights_label || it.source.rights_status}</span>
                  {it.privacy && <span className="badge">{it.platform === "tiktok" ? ({ SELF_ONLY: "Only me", PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers" } as Record<string, string>)[it.privacy] || it.privacy : it.privacy[0].toUpperCase() + it.privacy.slice(1)}</span>}
                  {it.replaces && <span className="badge warn" title="A stronger opportunity for the slot of another post">Replacement</span>}
                </div>
                <div className="qtitle">{it.title}</div>
                <div className="small muted qcaption">{it.description.split("\n")[0]}</div>
                <div className="qmeta small">
                  <span><Icon name="calendar" size={12} /> {it.local_time || "time to be chosen"}</span>
                  <span title={(it.scores?.explanation || []).join("\n")}>Final Opportunity <b>{Math.round(it.final_score ?? 0)}</b></span>
                  <span>Clip Score <b>{Math.round(it.clip_scores?.clip ?? it.clip.score)}</b></span>
                  <span className="muted" title={it.source.url}>Source: {it.source.title?.slice(0, 50)}{it.trend ? ` · trend “${it.trend.topic}”` : ""}</span>
                </div>
                {it.status_note && <div className={`small ${["failed", "blocked", "action_needed"].includes(it.status) ? "bad-text" : "muted"}`}>{it.status_note}</div>}
                {it.publication?.message && it.status !== "awaiting_approval" && <div className="small">{it.publication.message}</div>}
                {it.fix && <div className="small"><b>What to do:</b> {it.fix}</div>}
                <details className="small">
                  <summary>Why this slot and score</summary>
                  <ul className="flags">
                    {(it.scores?.explanation || []).map((w: string, k: number) => <li key={k}>{w}</li>)}
                    {it.slot?.note && <li>Time: {it.slot.note}</li>}
                  </ul>
                  <div className="muted">Audit trail</div>
                  <ul className="flags">
                    {(it.audit || []).map((a, k) => <li key={k}>{new Date(a.at * 1000).toLocaleString()}: {a.detail}</li>)}
                  </ul>
                </details>
              </div>
              <div className="qactions">
                {can(["awaiting_approval", "approved", "action_needed"]) && (
                  <button className={`btn sm ${it.status === "awaiting_approval" ? "primary" : ""}`} onClick={() => openApprove(it)}>
                    <Icon name="check" size={13} /> {it.status === "approved" ? "Review" : "Approve"}
                  </button>
                )}
                {can(["awaiting_approval", "approved", "failed"]) && <button className="btn sm" onClick={() => setEditing(it)}><Icon name="edit" size={13} /> Edit</button>}
                {can(["approved"]) && <button className="btn sm" onClick={() => window.confirm("Publish this post now?") && act(() => ap.publishNow(it.id), "Publishing now")}><Icon name="upload" size={13} /> Publish now</button>}
                {can(["failed", "blocked", "action_needed", "canceled"]) && <button className="btn sm" onClick={() => act(() => ap.retry(it.id), "It will be tried again")}><Icon name="refresh" size={13} /> Retry</button>}
                {can(["awaiting_approval", "approved", "failed", "action_needed"]) && (
                  <button className="btn sm ghost danger" onClick={() => window.confirm("Cancel this post?") && act(() => ap.cancel(it.id), "Canceled")}><Icon name="x" size={13} /> Cancel</button>
                )}
                {it.source.url && <a className="btn sm ghost" href={it.source.url} target="_blank" rel="noreferrer"><Icon name="link" size={13} /> Open source</a>}
                {it.publication?.url && <a className="btn sm ghost" href={it.publication.url} target="_blank" rel="noreferrer"><Icon name="play" size={13} /> Open post</a>}
                {it.platform === "tiktok" && it.status === "action_needed" && it.publication && (
                  <button className="btn sm ghost" onClick={() => {
                    const url = window.prompt("Paste the link of the post you made in the TikTok app:");
                    if (url) act(() => ap.link(it.id, url), "Linked");
                  }}>Link TikTok post</button>
                )}
                <a className="btn sm ghost" href={`#/clip/${it.clip.id}`}><Icon name="scissors" size={13} /> Clip</a>
              </div>
            </div>
          );
        })}
      </div>

      {approving && accounts && (
        <ApproveDialog item={approving} onClose={() => setApproving(null)} onDone={(i) => { replace(i); refresh(); }}
          restriction={(approving.platform === "youtube" ? accounts.youtube.restriction : accounts.tiktok?.restriction) || ""}
          audited={approving.platform === "youtube" ? true : !!accounts.tiktok?.audited} />
      )}
      {editing && <EditDialog item={editing} onClose={() => setEditing(null)} onDone={(i) => { replace(i); refresh(); }} />}
      {preview && (
        <Modal onClose={() => setPreview(null)}>
          <div className="preview-modal">
            <video src={preview.clip.video_url} controls autoPlay playsInline />
            <div className="preview-side">
              <b>{preview.title}</b>
              <pre className="desc-preview">{preview.description}</pre>
              <div className="small muted">{preview.clip.caption_text?.slice(0, 400)}</div>
            </div>
          </div>
        </Modal>
      )}
      <div className="small muted mt">Refreshes every few seconds.</div>
    </div>
  );
}

function EditDialog({ item, onClose, onDone }: { item: ScheduledItem; onClose: () => void; onDone: (i: ScheduledItem) => void }) {
  const yt = item.platform === "youtube";
  const [title, setTitle] = useState(item.title);
  const [text, setText] = useState(item.description);
  const [tags, setTags] = useState((item.tags || []).join(" "));
  const [when, setWhen] = useState(localInput(item.planned_at));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      let out = await ap.edit(item.id, { title, description: text, tags: tags.split(/[\s,]+/).filter(Boolean).map((t) => (yt ? t.replace(/^#/, "") : t.startsWith("#") ? t : `#${t}`)) });
      const ts = when ? new Date(when).getTime() / 1000 : 0;
      if (ts && Math.abs(ts - (item.planned_at || 0)) > 59) out = await ap.reschedule(item.id, ts);
      if (out.warnings?.length) toast(`Saved. Check: ${out.warnings[0]}`);
      else toast(item.status === "approved" ? "Saved: approve it again to publish" : "Saved");
      onDone(out);
      onClose();
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal onClose={onClose}>
      <div className="confirm" style={{ width: "min(640px, 94vw)" }}>
        <h3 style={{ marginTop: 0 }}>Edit {yt ? "YouTube" : "TikTok"} post</h3>
        {item.metadata_options.length > 1 && (
          <div className="options" style={{ marginBottom: 10 }}>
            {item.metadata_options.filter((o) => !o.problems.length).slice(0, 6).map((o) => (
              <button key={o.id} className="opt" onClick={() => { setTitle(o.title); setText(yt ? o.description : o.caption); setTags((yt ? o.tags : o.hashtags).join(" ")); }}>
                <span className="rec">{Math.round(o.score)}</span>{o.style}: {o.title.slice(0, 50)}
              </button>
            ))}
          </div>
        )}
        {yt && <label className="field">Title<input type="text" value={title} onChange={(e) => setTitle(e.target.value)} /></label>}
        <label className="field mt-s">{yt ? "Description" : "Caption"}<textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label className="field mt-s">{yt ? "Tags" : "Hashtags"}<input type="text" value={tags} onChange={(e) => setTags(e.target.value)} /></label>
        <label className="field mt-s">Planned time<input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
        <div className="small muted mt-s">Text is checked against the clip's transcript; anything that is not in it is pointed out. {item.status === "approved" ? "Changing the text needs a new approval." : ""}</div>
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}
