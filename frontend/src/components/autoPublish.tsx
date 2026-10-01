import { useEffect, useId, useState } from "react";
import { errorText } from "../api";
import { ap, AutoPublishView } from "../autopilot";
import { Banner, ConfirmDialog, Dialog, Pill, toast } from "./ui";

const VISIBILITY = [
  { value: "public", label: "Public: anyone can see them" },
  { value: "unlisted", label: "Unlisted: only people with the link" },
  { value: "private", label: "Private: only you" },
];
const hourWord = (h?: number) => (h === undefined ? "?" : h === 0 || h === 24 ? "midnight" : h === 12 ? "noon"
  : h < 12 ? `${h} a.m.` : `${h - 12} p.m.`);

/**
 * "Turn on automatic publishing": says exactly what will happen (account, what is posted, visibility, how many, when)
 * and only turns it on when you chose the visibility and the made-for-kids answer yourself and ticked that you
 * understand. TikTok is not offered: its rules require your OK on each post.
 */
export function AutoPublishDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [view, setView] = useState<AutoPublishView | null>(null);
  const [loadError, setLoadError] = useState("");
  const [visibility, setVisibility] = useState("");
  const [kids, setKids] = useState<boolean | null>(null);
  const [limit, setLimit] = useState(3);
  const [start, setStart] = useState(9);
  const [end, setEnd] = useState(21);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  useEffect(() => {
    ap.autoPublish().then((v) => {
      setView(v);
      setLimit(v.defaults.daily_limit);
      setStart(v.defaults.start_hour);
      setEnd(v.defaults.end_hour);
    }).catch((e) => setLoadError(errorText(e)));
  }, []);
  const missing = [
    !visibility && "choose who can see them",
    kids === null && "answer “made for kids”",
    !(limit >= 1) && "allow at least 1 a day",
    !(start < end) && "make the start hour earlier than the end hour",
    !agreed && "tick that you understand",
  ].filter(Boolean) as string[];
  const save = async () => {
    if (missing.length) return;
    setBusy(true);
    setError("");
    try {
      await ap.enableAutoPublish({
        platform: "youtube", visibility, made_for_kids: kids, daily_limit: limit, start_hour: start, end_hour: end,
        agreed,
      });
      toast("Automatic publishing is on for YouTube");
      onDone();
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  };
  const hour = (label: string, v: number, set: (n: number) => void, min: number, max: number) => (
    <input type="number" min={min} max={max} value={v} aria-label={label} style={{ width: 84 }}
      onChange={(e) => set(Math.max(min, Math.min(max, +e.target.value || 0)))} />
  );
  return (
    <Dialog title="Turn on automatic publishing for YouTube" wide onClose={onClose} actions={<>
      <button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary" aria-disabled={busy || missing.length > 0 || undefined}
        aria-describedby={`${id}-why`} onClick={() => !busy && save()}>
        {busy && <span className="inline-spinner" aria-hidden="true" />}Turn on automatic publishing
      </button>
    </>}>
      <p className="small">
        ClipFoundry will then publish finished clips to YouTube by itself, without asking you about each one.
      </p>
      {loadError && <Banner tone="bad" title="The current setting could not be read">{loadError}</Banner>}
      <dl className="kv">
        <dt>Account</dt>
        <dd>YouTube{view?.channel ? `: ${view.channel}` : ""}</dd>
        <dt>What gets posted</dt>
        <dd>
          Only clips that passed every automatic check (file, sound, captions, framing, text), from videos you own or
          that an agreement or license covers. A clip with a possible problem waits for you instead.
        </dd>
        <dt><label htmlFor={`${id}-vis`}>Who can see them</label></dt>
        <dd>
          <select id={`${id}-vis`} value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="" disabled>Choose…</option>
            {VISIBILITY.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
          </select>
        </dd>
        <dt id={`${id}-kids`}>Made for kids</dt>
        <dd>
          <div role="radiogroup" aria-labelledby={`${id}-kids`} className="row wrap">
            <label className="choice">
              <input type="radio" name={`${id}-kids`} checked={kids === false} onChange={() => setKids(false)} />
              <span>No</span>
            </label>
            <label className="choice">
              <input type="radio" name={`${id}-kids`} checked={kids === true} onChange={() => setKids(true)} />
              <span>Yes</span>
            </label>
          </div>
        </dd>
        <dt>How many</dt>
        <dd className="inline-fields">At most {hour("Posts a day at most", limit, setLimit, 1, 15)} a day</dd>
        <dt>When</dt>
        <dd className="inline-fields">
          Between {hour("From hour", start, setStart, 0, 23)} and {hour("To hour", end, setEnd, 1, 24)}
          <span className="tiny faint">
            ({hourWord(start)} to {hourWord(end)}, {view?.timezone || "America/Chicago"}), spread over the day
          </span>
        </dd>
      </dl>
      {view && !view.verified_project && (
        <Banner tone="warn" icon="shield" title="YouTube keeps these uploads private for now">
          Until Google audits your YouTube API project, YouTube keeps uploads from it <b>private</b> whatever you choose
          here. The audit is requested in Google's YouTube API Services form.
        </Banner>
      )}
      <p className="small">
        <b>TikTok</b> is not included: {view?.tiktok.note || "TikTok requires your OK on each post."}
      </p>
      <label className="autopub-agree">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span>
          I understand: ClipFoundry uploads these clips to my channel without asking me each time. I can cancel any
          upcoming post, and turn this off at any time.
        </span>
      </label>
      <span className="tiny muted" id={`${id}-why`}>
        {missing.length ? `To turn it on: ${missing.join(", ")}.` : "Ready."}
      </span>
      {error && <p className="error-text" role="alert">{error}</p>}
    </Dialog>
  );
}

/**
 * How each platform's posts get approved: YouTube by itself (with the permission's terms) or with your OK, and
 * TikTok always with your OK. `platform` shows one line only (Settings shows each under its own account).
 */
export function AutoPublishLine({ onChange, platform }: { onChange?: () => void; platform?: "youtube" | "tiktok" }) {
  const [view, setView] = useState<AutoPublishView | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const load = () => ap.autoPublish().then((v) => { setView(v); setFailed(false); }).catch(() => setFailed(true));
  useEffect(() => { load(); }, []);
  if (failed && !view) {
    return <span className="small muted">The publishing permission could not be read right now.</span>;
  }
  if (!view) return <span className="small muted" aria-busy="true">Loading…</span>;
  const yt = view.youtube;
  const cfg = yt.consent?.settings || ({} as Record<string, any>);
  return (
    <div className="autopub-line">
      {platform !== "tiktok" && (
        <div className="row wrap">
          {!platform && <b>YouTube</b>}
          {yt.enabled ? (
            <>
              <Pill tone="good" icon="check">Automatic publishing on</Pill>
              <span className="small muted">
                {cfg.visibility ? `${String(cfg.visibility)[0].toUpperCase()}${String(cfg.visibility).slice(1)}` : ""},
                {" "}up to{" "}
                {cfg.daily_limit} a day, {hourWord(cfg.start_hour)} to {hourWord(cfg.end_hour)}
              </span>
              <button type="button" className="btn btn-small" onClick={() => setAsking(true)}>Turn off…</button>
            </>
          ) : (
            <>
              <Pill tone="neutral">Off: each post waits for your OK</Pill>
              <button type="button" className="btn btn-small" onClick={() => setOpen(true)}>
                Turn on automatic publishing…
              </button>
            </>
          )}
        </div>
      )}
      {platform !== "youtube" && (
        <div className="row wrap small">
          {!platform && <b>TikTok</b>}
          <Pill tone="neutral">Your OK on each post</Pill>
          <span className="muted">{view.tiktok.note}</span>
        </div>
      )}
      {open && <AutoPublishDialog onClose={() => setOpen(false)} onDone={() => { load(); onChange?.(); }} />}
      {asking && (
        <ConfirmDialog title="Turn off automatic publishing for YouTube?" confirmLabel="Turn it off"
          cancelLabel="Keep it on"
          onClose={() => setAsking(false)}
          onConfirm={async () => {
            const r = await ap.disableAutoPublish("youtube");
            const n = r.returned_to_review;
            toast(`Automatic publishing is off${n ? `: ${n} post${n === 1 ? "" : "s"} now wait for your OK` : ""}`);
            setView(r);
            onChange?.();
          }}>
          <p className="muted">
            Upcoming YouTube posts it approved go back to Posts, Needs review, and wait for your OK. Nothing already
            published changes. You can turn it on again at any time.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
