import { useEffect, useState } from "react";
import { errorText } from "../api";
import { ap, AutoPublishView } from "../autopilot";
import { Icon, Modal, toast } from "./ui";

const VISIBILITY = [
  { value: "public", label: "Public: anyone can see them" },
  { value: "unlisted", label: "Unlisted: only people with the link" },
  { value: "private", label: "Private: only you" },
];

/**
 * "Enable automatic publishing": says exactly what will happen (account, what is posted, visibility, how many, when) and
 * only turns it on when you chose the visibility and the made-for-kids answer yourself and confirmed it. TikTok is not
 * offered: its rules require your OK on each post.
 */
export function AutoPublishDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [view, setView] = useState<AutoPublishView | null>(null);
  const [visibility, setVisibility] = useState("");
  const [kids, setKids] = useState<boolean | null>(null);
  const [limit, setLimit] = useState(3);
  const [start, setStart] = useState(9);
  const [end, setEnd] = useState(21);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    ap.autoPublish().then((v) => {
      setView(v);
      setLimit(v.defaults.daily_limit);
      setStart(v.defaults.start_hour);
      setEnd(v.defaults.end_hour);
    }).catch((e) => toast(errorText(e), true));
  }, []);
  const ready = !!visibility && kids !== null && agreed && limit >= 1 && start < end;
  const save = async () => {
    setBusy(true);
    try {
      await ap.enableAutoPublish({ platform: "youtube", visibility, made_for_kids: kids, daily_limit: limit, start_hour: start, end_hour: end, agreed });
      toast("Automatic publishing is on for YouTube");
      onDone();
      onClose();
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };
  const hour = (v: number, set: (n: number) => void, min: number, max: number) => (
    <input type="number" min={min} max={max} value={v} style={{ width: 70 }} onChange={(e) => set(Math.max(min, Math.min(max, +e.target.value || 0)))} />
  );
  return (
    <Modal onClose={onClose}>
      <div className="confirm autopub" style={{ width: "min(660px, 94vw)" }}>
        <h3 style={{ marginTop: 0 }}>Enable automatic publishing</h3>
        <p className="small">ClipFoundry will publish finished clips to YouTube by itself, without asking you about each one.</p>
        <div className="autopub-facts">
          <span className="k">Account</span>
          <span>YouTube{view?.channel ? `: ${view.channel}` : ""}</span>
          <span className="k">What gets posted</span>
          <span>Only clips that passed every automatic check (file, sound, captions, framing, text), from videos you own or that an agreement or license covers. A clip with a possible problem is held for you instead.</span>
          <span className="k">Who can see them</span>
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)} aria-label="Who can see them">
            <option value="" disabled>Choose...</option>
            {VISIBILITY.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
          </select>
          <span className="k">Made for kids</span>
          <span className="row" role="radiogroup" aria-label="Made for kids">
            <label className="row small"><input type="radio" name="kids" checked={kids === false} onChange={() => setKids(false)} /> No</label>
            <label className="row small"><input type="radio" name="kids" checked={kids === true} onChange={() => setKids(true)} /> Yes</label>
          </span>
          <span className="k">How many</span>
          <span className="row small">At most {hour(limit, setLimit, 1, 15)} a day</span>
          <span className="k">When</span>
          <span className="row small wrap">Between {hour(start, setStart, 0, 23)} and {hour(end, setEnd, 1, 24)} o'clock ({view?.timezone || "America/Chicago"}), spread over the day</span>
        </div>
        {view && !view.verified_project && (
          <div className="notice warn small mt"><Icon name="shield" size={14} /><div>Until Google audits your YouTube API project, YouTube keeps these uploads <b>private</b> whatever you choose here. The audit is requested in Google's YouTube API Services form.</div></div>
        )}
        <div className="notice small mt"><Icon name="shield" size={14} /><div><b>TikTok</b> is not included: {view?.tiktok.note || "TikTok requires your OK on each post."}</div></div>
        <label className="row small mt autopub-agree">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
          <span>I understand: ClipFoundry uploads these clips to my channel without asking me each time. I can cancel any upcoming post, and turn this off at any time.</span>
        </label>
        <div className="row mt" style={{ justifyContent: "flex-end" }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !ready} onClick={save}>Enable automatic publishing</button>
        </div>
      </div>
    </Modal>
  );
}

/** One line per platform: publishes by itself, or waits for your OK (and why), with the button to change it. */
export function AutoPublishLine({ onChange }: { onChange?: () => void }) {
  const [view, setView] = useState<AutoPublishView | null>(null);
  const [open, setOpen] = useState(false);
  const load = () => ap.autoPublish().then(setView).catch(() => setView(null));
  useEffect(() => { load(); }, []);
  const off = async () => {
    if (!window.confirm("Turn off automatic publishing for YouTube? Upcoming posts it approved will wait for your approval.")) return;
    try {
      const r = await ap.disableAutoPublish("youtube");
      toast(`Automatic publishing is off${r.returned_to_review ? `: ${r.returned_to_review} post(s) wait for your approval` : ""}`);
      setView(r);
      onChange?.();
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  if (!view) return <span className="muted small">...</span>;
  const yt = view.youtube;
  const cfg = yt.consent?.settings || {};
  return (
    <div className="autopub-line">
      <div className="row wrap">
        <b>YouTube</b>
        {yt.enabled ? (
          <>
            <span className="badge good">On</span>
            <span className="small muted">{cfg.visibility}, up to {cfg.daily_limit} a day, {cfg.start_hour}:00 to {cfg.end_hour}:00</span>
            <button className="btn sm ghost" onClick={off}>Turn off</button>
          </>
        ) : (
          <>
            <span className="badge">Off: each post waits for your OK</span>
            <button className="btn sm primary" onClick={() => setOpen(true)}>Enable automatic publishing</button>
          </>
        )}
      </div>
      <div className="row wrap small mt-s">
        <b>TikTok</b><span className="badge">Your OK on each post</span><span className="muted">{view.tiktok.note}</span>
      </div>
      {open && <AutoPublishDialog onClose={() => setOpen(false)} onDone={() => { load(); onChange?.(); }} />}
    </div>
  );
}
