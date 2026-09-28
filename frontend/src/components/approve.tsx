import { useEffect, useMemo, useState } from "react";
import { api, errorText, fmtTime, TikTokCreator } from "../api";
import { ap, ScheduledItem } from "../autopilot";
import { Icon, Modal, toast } from "./ui";

const TIKTOK_PRIVACY: Record<string, string> = {
  PUBLIC_TO_EVERYONE: "Everyone", MUTUAL_FOLLOW_FRIENDS: "Friends", FOLLOWER_OF_CREATOR: "Followers", SELF_ONLY: "Only me",
};
const tagList = (s: string) => s.split(/[\s,]+/).filter(Boolean).map((t) => t.replace(/^#/, ""));

/**
 * Approving one scheduled post. YouTube and TikTok require that you control what is published: you see the video,
 * the exact text and the visibility, and nothing is uploaded until you approve. After approval ClipFoundry publishes
 * it at its time without asking again (unless the clip or its text changes).
 */
export function ApproveDialog({ item, restriction, audited, onDone, onClose }: {
  item: ScheduledItem; restriction: string; audited: boolean; onDone: (i: ScheduledItem) => void; onClose: () => void;
}) {
  const yt = item.platform === "youtube";
  const [title, setTitle] = useState(item.title);
  const [text, setText] = useState(item.description);
  const [tags, setTags] = useState((item.tags || []).join(" "));
  const [privacy, setPrivacy] = useState(yt ? item.privacy || "private" : "");
  const [kids, setKids] = useState<"" | "no" | "yes">(item.options?.made_for_kids === false ? "no" : item.options?.made_for_kids ? "yes" : "");
  const [mode, setMode] = useState<"direct" | "inbox">(item.options?.mode === "inbox" ? "inbox" : "direct");
  const [allow, setAllow] = useState({ comment: false, duet: false, stitch: false });
  const [disclose, setDisclose] = useState(false);
  const [brandOrganic, setBrandOrganic] = useState(false);
  const [brandContent, setBrandContent] = useState(false);
  const [creator, setCreator] = useState<TikTokCreator | null>(null);
  const [creatorError, setCreatorError] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (yt) return;
    api.tiktokCreator().then(setCreator).catch((e) => setCreatorError(errorText(e)));
  }, [yt]);

  const direct = !yt && mode === "direct";
  const branded = direct && disclose && brandContent;
  const problems = useMemo(() => [
    yt && !title.trim() && "enter a title",
    yt && title.length > 100 && "shorten the title to 100 characters",
    yt && !kids && "answer “made for kids”",
    !yt && text.length > 2200 && "shorten the caption",
    direct && !privacy && "choose who can see it",
    direct && !audited && privacy && privacy !== "SELF_ONLY" && "unaudited apps can only post “Only me”",
    direct && disclose && !brandOrganic && !brandContent && "choose what the commercial content is",
    branded && privacy === "SELF_ONLY" && "branded content can't be “Only me”",
    direct && creator && creator.max_duration > 0 && item.clip.duration > creator.max_duration && `trim the clip to ${creator.max_duration}s`,
    !agree && "confirm below",
  ].filter(Boolean) as string[], [yt, title, kids, text, direct, privacy, audited, disclose, brandOrganic, brandContent, branded, creator, item.clip.duration, agree]);

  const approve = async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { title: yt ? title.trim() : item.title, description: text.trim() };
      if (yt) Object.assign(body, { tags: tagList(tags), privacy, made_for_kids: kids === "yes" });
      else Object.assign(body, {
        mode, privacy: direct ? privacy : "", allow_comment: allow.comment, allow_duet: allow.duet, allow_stitch: allow.stitch,
        disclose, brand_organic: brandOrganic, brand_content: brandContent,
      });
      const out = await ap.approve(item.id, body);
      if (out.warnings?.length) toast(`Approved. Note: ${out.warnings[0]}`);
      else toast("Approved: it will be published at its time");
      onDone(out);
      onClose();
    } catch (e) {
      toast(errorText(e), true);
    } finally {
      setBusy(false);
    }
  };

  const useOption = (o: ScheduledItem["metadata_options"][number]) => {
    setTitle(o.title);
    setText(yt ? o.description : o.caption);
    setTags((yt ? o.tags : o.hashtags).join(" "));
  };

  return (
    <Modal onClose={onClose}>
      <div className="approve">
        <video src={item.clip.video_url} controls playsInline poster={item.clip.thumbnail_url} />
        <div className="approve-side">
          <div className="row between">
            <h3 style={{ margin: 0 }}>Approve for {yt ? "YouTube Shorts" : "TikTok"}</h3>
            <button className="btn ghost icon-btn" onClick={onClose}><Icon name="x" /></button>
          </div>
          <div className="small muted">
            Planned for <b>{item.local_time || "the next free slot"}</b> · {fmtTime(item.clip.duration)} · Final Opportunity {Math.round(item.final_score ?? 0)}
          </div>
          {item.metadata_options.length > 1 && (
            <div>
              <div className="pp-label">Text options <span className="small muted">written from the clip's own words</span></div>
              <div className="options">
                {item.metadata_options.filter((o) => !o.problems.length).slice(0, 6).map((o) => (
                  <button key={o.id} className="opt" title={`${o.style} · Packaging Score ${Math.round(o.score)}`} onClick={() => useOption(o)}>
                    <span className="rec">{Math.round(o.score)}</span>{o.style}: {o.title.slice(0, 60)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {yt ? (
            <>
              <label className="field"><span className="row between">Title <span className={`small ${title.length > 100 ? "bad-text" : "muted"}`}>{title.length}/100</span></span>
                <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
              </label>
              <label className="field">Description<textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} /></label>
              <label className="field">Tags<input type="text" value={tags} onChange={(e) => setTags(e.target.value)} /></label>
              <div className="field">Visibility
                <div className="segmented">
                  {(["public", "unlisted", "private"] as const).map((p) => (
                    <button key={p} type="button" className={privacy === p ? "on" : ""} onClick={() => setPrivacy(p)}>{p[0].toUpperCase() + p.slice(1)}</button>
                  ))}
                </div>
              </div>
              {privacy === "public" && <div className="small muted">Uploaded early as Private with a scheduled time: YouTube itself makes it public at {item.local_time || "its time"}.</div>}
              {privacy !== "private" && restriction && <div className="notice warn small block">{restriction}</div>}
              <div className="field">Made for kids <span className="small muted">(required by YouTube)</span>
                <div className="row">
                  <label className="row small"><input type="radio" checked={kids === "no"} onChange={() => setKids("no")} /> No, it's not made for kids</label>
                  <label className="row small"><input type="radio" checked={kids === "yes"} onChange={() => setKids("yes")} /> Yes</label>
                </div>
              </div>
            </>
          ) : (
            <>
              {creator && (
                <div className="row small">
                  {creator.avatar && <img className="avatar" src={creator.avatar} alt="" referrerPolicy="no-referrer" />}
                  Posting as <b>{creator.nickname}</b>{creator.username ? <span className="muted">@{creator.username}</span> : null}
                </div>
              )}
              {creatorError && <div className="notice bad small block">{creatorError}</div>}
              <label className="field"><span className="row between">Caption <span className="small muted">{text.length}/2200</span></span>
                <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} />
              </label>
              <div className="field">How to post
                <div className="segmented">
                  <button type="button" className={direct ? "on" : ""} onClick={() => setMode("direct")}>Post directly</button>
                  <button type="button" className={!direct ? "on" : ""} onClick={() => setMode("inbox")}>Send to TikTok inbox</button>
                </div>
              </div>
              {!direct && <div className="small muted">The video arrives as a draft in the TikTok app; you finish and post it there. Works without TikTok's app audit.</div>}
              {direct && !audited && <div className="notice warn small block">{restriction || "Until TikTok audits your app, Direct Post only works for private accounts and “Only me”."}</div>}
              {direct && (
                <>
                  <label className="field">Who can see this
                    <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
                      <option value="" disabled>Choose privacy</option>
                      {(creator?.privacy_options || []).map((o) => (
                        <option key={o} value={o} disabled={(!audited && o !== "SELF_ONLY") || (branded && o === "SELF_ONLY")}>{TIKTOK_PRIVACY[o] || o}</option>
                      ))}
                    </select>
                  </label>
                  <div className="field">Allow viewers to
                    <div className="row wrap" style={{ gap: 16 }}>
                      {(["comment", "duet", "stitch"] as const).map((k) => {
                        const off = !!creator?.[`${k}_disabled` as const];
                        return (
                          <label key={k} className="row small" style={off ? { opacity: 0.45 } : undefined}>
                            <input type="checkbox" disabled={off} checked={allow[k] && !off} onChange={(e) => setAllow({ ...allow, [k]: e.target.checked })} />
                            {k[0].toUpperCase() + k.slice(1)}
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <label className="row small"><input type="checkbox" checked={disclose} onChange={(e) => { setDisclose(e.target.checked); if (!e.target.checked) { setBrandOrganic(false); setBrandContent(false); } }} /> This video is commercial content</label>
                  {disclose && (
                    <div className="grid" style={{ gap: 6, paddingLeft: 22 }}>
                      <label className="row small"><input type="checkbox" checked={brandOrganic} onChange={(e) => setBrandOrganic(e.target.checked)} /> <b>Your brand</b></label>
                      <label className="row small"><input type="checkbox" checked={brandContent} onChange={(e) => setBrandContent(e.target.checked)} /> <b>Branded content</b> (paid partnership)</label>
                    </div>
                  )}
                </>
              )}
              <div className="small muted">
                By posting, you agree to TikTok's{" "}
                {branded && <><a href="https://www.tiktok.com/legal/page/global/bc-policy/en" target="_blank" rel="noreferrer">Branded Content Policy</a> and </>}
                <a href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank" rel="noreferrer">Music Usage Confirmation</a>.
                It may take a few minutes for the video to appear on your profile.
              </div>
            </>
          )}
          <label className="row small agree">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            I reviewed this video and its text, and I approve publishing it {item.local_time ? `at ${item.local_time}` : "at its scheduled time"}.
          </label>
          <div className="row between">
            <span className="small muted">{problems.length ? `To approve: ${problems.join(", ")}.` : "Nothing is uploaded before its time."}</span>
            <button className="btn primary" disabled={problems.length > 0 || busy} onClick={approve}><Icon name="check" size={16} /> {busy ? "Approving..." : "Approve"}</button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
