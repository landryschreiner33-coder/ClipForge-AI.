import { useEffect, useRef, useState } from "react";
import { errorText, req } from "../api";
import { plural } from "../format";
import { Post, timeLabel } from "./postShared";
import { ReuseBasis, ReuseKind, ReuseOption } from "./ReuseBasis";
import { Dialog, Icon, Pill, toast } from "./ui";

type PreviewRow = { id: string; eligible: boolean; reason: string; item: Post | null;
  needs_reuse_confirmation: boolean; needs_made_for_kids: boolean };
type Preview = { token: string; expires_at: number; items: PreviewRow[]; eligible_ids: string[];
  account: { id: string; display_name: string }; reuse_options: ReuseOption[]; timezone: string; auto_publish?: boolean };
type Result = { results: { id: string; status: "approved" | "skipped"; reason: string }[];
  approved: number; skipped: number };

/** The file, text and audience come from the server-bound preview, never from the live-polling Queue. */
export function BulkApproval({ ids, autoPublish, tz, onApproved, onClose }: {
  ids: string[]; autoPublish: boolean; tz?: string; onApproved: (ids: string[]) => void; onClose: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [remaining, setRemaining] = useState(ids);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [agree, setAgree] = useState(false);
  const [kind, setKind] = useState<ReuseKind>("");
  const [basis, setBasis] = useState("");
  const [kids, setKids] = useState<"" | "yes" | "no">("");
  const generation = useRef(0);
  const load = async (selected = remaining) => {
    const request = ++generation.current;
    setLoading(true); setError(""); setAgree(false); setResult(null); setPreview(null);
    try {
      const next = await req<Preview>("POST", "/api/autopilot/scheduled/bulk-preview", { ids: selected });
      if (request === generation.current) setPreview(next);
    } catch (e) {
      if (request === generation.current) setError(errorText(e));
    } finally {
      if (request === generation.current) setLoading(false);
    }
  };
  useEffect(() => {
    void load(ids);
    return () => { generation.current++; };
  }, []); // The selected IDs stay fixed for this review; new Queue arrivals are never added.

  const eligible = preview?.items.filter((row) => row.eligible) || [];
  const uploadsAtTime = preview?.auto_publish ?? autoPublish;
  const needsReuse = eligible.some((row) => row.needs_reuse_confirmation);
  const needsKids = eligible.some((row) => row.needs_made_for_kids);
  const missing = [!agree && "confirm your review", needsReuse && (!kind || (kind === "custom" && !basis.trim()))
    && "choose why you can reuse the clips", needsKids && !kids && "answer “made for kids”"]
    .filter(Boolean) as string[];
  const confirm = async () => {
    if (!preview || missing.length || busy || !eligible.length) return;
    setBusy(true); setError("");
    try {
      const out = await req<Result>("POST", "/api/autopilot/scheduled/bulk-approve", {
        token: preview.token, confirm: true, reuse_confirmed: agree,
        ...(needsReuse ? { reuse_kind: kind, ...(kind === "custom" ? { reuse_basis: basis.trim() } : {}) } : {}),
        ...(needsKids ? { made_for_kids: kids === "yes" } : {}),
      });
      const approved = out.results.filter((row) => row.status === "approved").map((row) => row.id);
      onApproved(approved);
      setRemaining((current) => current.filter((id) => !approved.includes(id)));
      setResult(out); setAgree(false);
      if (!out.skipped) {
        toast(`${plural(out.approved, "post")} approved. ${uploadsAtTime
          ? "Each can upload at its planned time; due posts can start on the next publishing check."
          : "Each waits for Publish now."}`);
        onClose();
      }
    } catch (e) {
      setError(errorText(e)); setAgree(false);
    } finally {
      setBusy(false);
    }
  };
  const timezone = preview?.timezone || tz;
  const close = () => { if (!busy) onClose(); };
  const selectedTitles = new Map(preview?.items.map((row) => [row.id,
    row.item?.title || row.item?.clip.title || "Unavailable post"]) || []);
  return (
    <Dialog title={`Review ${remaining.length} YouTube posts`} wide onClose={close} actions={<>
      <button type="button" className="btn" disabled={busy} onClick={close}>{result ? "Done" : "Cancel"}</button>
      {(error || result) && <button type="button" className="btn" disabled={busy || loading}
        onClick={() => void load() }><Icon name="refresh" />Refresh preview</button>}
      {!result && preview && <button type="button" className="btn btn-primary"
        disabled={busy || loading || !!error || !!missing.length || !eligible.length} onClick={() => void confirm()}>
        {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="check" />}
        Approve {eligible.length} posts
      </button>}
    </>}>
      <div className="bulk-review stack-4" aria-busy={loading || busy}>
        {loading && <p className="small muted" role="status">Checking the selected posts and their exact files…</p>}
        {error && <p className="error-text" role="alert">{error} Refresh the preview and confirm your review again.</p>}
        {result ? <section className="stack-3" aria-label="Approval results">
          <p role="status"><b>{plural(result.approved, "post")} approved.</b> {plural(result.skipped, "post")} skipped;
            they remain selected in Queue.</p>
          {result.results.filter((row) => row.status === "skipped").map((row) => <div key={row.id} className="bulk-skip">
            <a className="textlink" href={`#/post/${row.id}`} onClick={close}>{selectedTitles.get(row.id) || "Post"}</a>
            <p className="small muted">{row.reason}</p>
          </div>)}
          <p className="tiny muted">A skipped post has not received approval from this batch. Check its reason before trying again.</p>
        </section> : preview && <>
          <p className="small muted">One approval for these selected posts only. This does not approve future clips or enable automatic approval.
            {preview.account.display_name ? <> Destination: <b>{preview.account.display_name}</b>.</> : null}</p>
          <div className="bulk-review-list">
            {preview.items.map((row) => <BatchPost key={row.id} row={row} tz={timezone} />)}
          </div>
          <div className="consequence bulk-consequence">
            <b>{uploadsAtTime ? "What happens when you approve" : "Posting at the planned time is off"}</b>
            <span>{uploadsAtTime ? "Each approved post can upload at its own time without asking again. Past-due posts can start now, on the next publishing check."
              : "These approvals wait for you to press Publish now."} The audience and planned time shown above stay unchanged.</span>
          </div>
          {needsReuse && <ReuseBasis kind={kind} basis={basis} multiple options={preview.reuse_options}
            disabled={busy} onChange={(nextKind, nextBasis) => { setKind(nextKind); setBasis(nextBasis); setAgree(false); }} />}
          {needsKids && <fieldset className="bulk-kids" disabled={busy}>
            <legend className="small strong">Made for kids</legend>
            <p className="tiny muted">Apply to the selected posts with no answer yet. Existing answers stay unchanged.
              If they need different answers, approve those posts separately.</p>
            <div className="row wrap">
              <label className="choice"><input type="radio" name="bulk-kids" value="no" checked={kids === "no"}
                onChange={() => { setKids("no"); setAgree(false); }} /><span>No, not made for kids</span></label>
              <label className="choice"><input type="radio" name="bulk-kids" value="yes" checked={kids === "yes"}
                onChange={() => { setKids("yes"); setAgree(false); }} /><span>Yes, made for kids</span></label>
            </div>
          </fieldset>}
          {!!eligible.length && <label className="choice bulk-agree">
            <input type="checkbox" checked={agree} disabled={busy} onChange={(e) => setAgree(e.target.checked)} />
            <span className="small">I watched every selected video, read its text and authorize each audience shown above.
              {needsReuse ? " I checked I can reuse every clip needing confirmation on the common basis selected above." : ""}
              {eligible.some((row) => row.item?.privacy === "public") ? " Public means anyone can watch." : ""}</span>
          </label>}
          <p className="tiny muted" role="status">{!eligible.length ? "None of these posts can be approved in this batch. Open a skipped post to resolve its reason."
            : missing.length ? `To approve: ${missing.join(", ")}.` : `Ready to approve ${plural(eligible.length, "post")}.`}</p>
        </>}
      </div>
    </Dialog>
  );
}

function BatchPost({ row, tz }: { row: PreviewRow; tz?: string }) {
  const p = row.item;
  if (!p) return <article className="bulk-review-post"><b>Unavailable post</b><p className="small muted">{row.reason}</p></article>;
  const title = p.title || p.clip.title || "Untitled post";
  return <article className="bulk-review-post">
    <div className="row wrap spread"><h3>{title}</h3>
      {!row.eligible && <Pill tone="warn">Skipped</Pill>}</div>
    <div className="post-meta small">
      <b>{p.privacy === "public" ? "Public · anyone can watch" : p.audience_label || "Private"}</b>
      <span>{timeLabel(p.planned_at, tz)}</span>
      {!!p.planned_at && p.planned_at <= Date.now() / 1000 && <span className="bulk-due">Past due · can start now after approval</span>}
      <span>{p.options?.made_for_kids === true ? "Made for kids: Yes" : p.options?.made_for_kids === false
        ? "Made for kids: No" : "Made for kids: needs your answer"}</span>
    </div>
    {!row.eligible && <p className="small error-text">{row.reason}</p>}
    <PostInlinePreview p={p} />
    <a className="textlink tiny" href={`#/post/${p.id}`}>Edit this post separately</a>
  </article>;
}

/** Mount media only when asked, so a long Queue does not download every video. */
export function PostInlinePreview({ p }: { p: Post }) {
  const [open, setOpen] = useState(false);
  const title = p.title || p.clip.title || "Untitled post";
  const id = `post-preview-${p.id}`;
  const url = `${p.clip.video_url}${p.clip.video_url.includes("?") ? "&" : "?"}review=${encodeURIComponent(p.quality?.sha256 || p.clip.version_id || "current")}`;
  return <div className="post-inline-preview">
    <button type="button" className="btn btn-small btn-quiet" aria-label={`Preview video: ${title}`}
      aria-expanded={open} aria-controls={id} onClick={() => setOpen((current) => !current)}>
      <Icon name={open ? "x" : "play"} />{open ? "Hide preview" : "Preview"}
    </button>
    {open && <div id={id} className="post-preview-content">
      <video key={url} src={url} controls playsInline preload="metadata" aria-label={`Video of this post: ${title}`}
        poster={p.clip.has_thumbnail ? p.clip.thumbnail_url : undefined} />
      <div className="stack-3">
        <div><b className="small">Description</b><p className="small post-preview-text">{p.description || "No description."}</p></div>
        {!!p.tags?.length && <p className="tiny muted">Tags: {p.tags.join(", ")}</p>}
        <p className="tiny muted">Permission to use: {p.source?.rights_label || p.source?.rights_status || "unknown"}
          {p.reuse_review?.confirmed ? " · Reuse confirmed by you for this post" : ""}</p>
        {p.source?.url && <a className="textlink small" href={p.source.url} target="_blank" rel="noreferrer">Open source video <Icon name="external" className="sm" /></a>}
      </div>
    </div>}
  </div>;
}
