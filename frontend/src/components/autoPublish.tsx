import { useEffect, useId, useState } from "react";
import { errorText } from "../api";
import { ap, AutoPublishView } from "../autopilot";
import { audienceApi, AudienceView } from "../office/api";
import { Banner, ConfirmDialog, Dialog, Disclosure, Pill, toast } from "./ui";

const hourWord = (h?: number) => (h === undefined ? "?" : h === 0 || h === 24 ? "midnight" : h === 12 ? "noon"
  : h < 12 ? `${h} a.m.` : `${h - 12} p.m.`);

/**
 * "Turn on automatic publishing": says exactly what will happen (account, what is posted, how many, when) and only
 * turns it on when you gave the made-for-kids answer yourself and ticked that you understand. The permission names
 * the confirmed audience and connected channel. TikTok is not offered: its rules require your OK on each post.
 */
export function AutoPublishDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [view, setView] = useState<AutoPublishView | null>(null);
  const [audience, setAudience] = useState<AudienceView | null>(null);
  const [loadError, setLoadError] = useState("");
  const [kids, setKids] = useState<boolean | null>(null);
  const [limit, setLimit] = useState(3);
  const [start, setStart] = useState(9);
  const [end, setEnd] = useState(21);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  useEffect(() => {
    Promise.all([ap.autoPublish(), audienceApi.view()]).then(([v, a]) => {
      setView(v);
      setAudience(a);
      setAgreed(false);
      setLimit(v.defaults.daily_limit);
      setStart(v.defaults.start_hour);
      setEnd(v.defaults.end_hour);
    }).catch((e) => setLoadError(errorText(e)));
  }, []);
  const publicPosts = audience?.youtube.intent === "PUBLIC";
  const visibility = publicPosts ? "public" : "private";
  const audienceReady = !!audience?.youtube.confirmed && audience.youtube.intent !== "LOCAL_ONLY";
  const blocker = view?.youtube.blocker || (!audienceReady ? "confirm who watches in Settings → Integrations"
    : "");
  const missing = [
    (!view || !audience || loadError) && "wait for the current account and audience to load",
    (view?.youtube.can_enable === false || !audienceReady) && blocker,
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
        agreed, expected_account_id: view?.youtube.account_id,
        expected_audience_version: audience?.youtube.group_version,
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
      onChange={(e) => { set(Math.max(min, Math.min(max, +e.target.value || 0))); setAgreed(false); }} />
  );
  return (
    <Dialog title="Turn on automatic publishing for YouTube" wide onClose={onClose} actions={<>
      <button type="button" className="btn" onClick={onClose}>Cancel</button>
      <button type="button" className="btn btn-primary"
        disabled={busy || missing.length > 0 || view?.youtube.can_enable === false}
        aria-describedby={`${id}-why`} onClick={() => !busy && save()}>
        {busy && <span className="inline-spinner" aria-hidden="true" />}Turn on automatic publishing
      </button>
    </>}>
      <p className="small">
        ClipFoundry will upload eligible finished clips to YouTube as <b>{publicPosts ? "Public" : "Private"}</b>
        {" "}videos without asking about each one. {publicPosts ? "Anyone may watch, share or find new public posts."
          : "You share private videos with invited viewers in YouTube Studio yourself."}
        {" "}Existing posts and previously planned private uploads keep their audience.
      </p>
      {blocker && <Banner tone="warn" title="Automatic publishing needs setup">
        {blocker}. <a className="textlink" href="#/settings/integrations">Open publishing setup</a>
      </Banner>}
      {loadError && <Banner tone="bad" title="The current setting could not be read">{loadError}</Banner>}
      <dl className="kv">
        <dt>Account</dt>
        <dd>YouTube{view?.channel ? `: ${view.channel}` : ""}</dd>
        <dt>What gets posted</dt>
        <dd>
          Only clips that passed every automatic check (file, sound, captions, framing, text), from videos you own or
          that an agreement or license covers. Clips that do not pass stay in your Library and are not posted.
        </dd>
        <dt>Who can see them</dt>
        <dd>
          {publicPosts ? "Public: anyone can watch, including people who do not follow your channel."
            : audience?.youtube.intent === "OWNER_ONLY" ? "Private: only you (staging)."
              : "Private: only the people you invite in YouTube Studio (Content → the video → Visibility → "
                + "Private → Share privately). ClipFoundry cannot invite viewers."}
        </dd>
        <dt id={`${id}-kids`}>Made for kids</dt>
        <dd>
          <div role="radiogroup" aria-labelledby={`${id}-kids`} className="row wrap">
            <label className="choice">
              <input type="radio" name={`${id}-kids`} checked={kids === false}
                onChange={() => { setKids(false); setAgreed(false); }} />
              <span>No</span>
            </label>
            <label className="choice">
              <input type="radio" name={`${id}-kids`} checked={kids === true}
                onChange={() => { setKids(true); setAgreed(false); }} />
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
      <p className="small">
        <b>TikTok</b> is not included: {view?.tiktok.note || "TikTok requires your OK on each post."}
      </p>
      <label className="autopub-agree">
        <input type="checkbox" checked={agreed} disabled={!view || !audience || !!loadError}
          onChange={(e) => setAgreed(e.target.checked)} />
        <span>
          I authorize ClipFoundry to upload eligible clips to {view?.channel || "this connected YouTube channel"}
          {" "}as {publicPosts ? "Public videos that anyone can watch" : "Private videos"} within these limits,
          without asking me each time. {publicPosts ? "Previously planned private uploads keep their audience. "
            : audience?.youtube.intent === "SELECTED_AUDIENCE" ? "I share private videos myself. " : ""}
          I can cancel upcoming uploads or pause publishing at any time.
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
              <Pill tone="good" icon="check">
                Automatic {cfg.visibility === "public" ? "public " : ""}publishing on
              </Pill>
              <span className="small muted">
                {cfg.visibility ? `${String(cfg.visibility)[0].toUpperCase()}${String(cfg.visibility).slice(1)}` : ""},
                {" "}up to{" "}
                {cfg.daily_limit} a day, {hourWord(cfg.start_hour)} to {hourWord(cfg.end_hour)}
              </span>
              {view.channel && <span className="small muted">· {view.channel}</span>}
              <button type="button" className="btn btn-small" onClick={() => setAsking(true)}>Turn off…</button>
            </>
          ) : (
            <>
              <Pill tone="neutral">Off: each post waits for your OK</Pill>
              {yt.blocker && <span className="small muted">{yt.blocker}</span>}
              <button type="button" className="btn btn-small" onClick={() => setOpen(true)}>
                Turn on automatic publishing…
              </button>
            </>
          )}
        </div>
      )}
      {platform !== "tiktok" && yt.enabled && yt.consent && (
        <Disclosure plain summary="Recorded automatic publishing permission">
          <p className="small muted">{yt.consent.text}</p>
        </Disclosure>
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
            Upcoming YouTube posts it approved go back to Queue, Needs review, and wait for your OK. Nothing already
            published changes. You can turn it on again at any time.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
