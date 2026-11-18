import { useEffect, useId, useState } from "react";
import { api, Clip, errorText, Publication } from "../api";
import { audienceApi, AudienceView } from "../office/api";
import { Connection, studio } from "../studio";
import { accountName, ChannelPicker, nameList } from "./channelPicker";
import { Dialog, Icon, Pill, toast } from "./ui";
import { YouTubeComments } from "./YouTubeComments";

const tagList = (s: string) => s.split(/[\s,]+/).filter(Boolean).map((t) => (t.startsWith("#") ? t : `#${t}`));

/** The clip's saved post text, exactly as Prepare post would send it to YouTube (without the optional #Shorts). */
function postOf(c: Clip) {
  const title = (c.post?.title || c.title || "").trim();
  const tags = tagList((c.post?.hashtags || c.hashtags || []).join(" "));
  const description = [(c.post?.caption || "").trim(), tags.join(" ")].filter(Boolean).join("\n\n");
  return { title, tags, description };
}

type Outcome = { key: string; clip: string; channel: string; ok: boolean; text: string };

// An upload that is on the channel, on its way there, or whose outcome YouTube never confirmed.
const HELD = ["done", "queued", "uploading", "processing", "action_needed"];
const onChannel = (p: Publication) => HELD.includes(p.status) || !!p.info?.outcome_unknown
  || p.info?.code === "outcome_unknown";

/**
 * Post several clips at once, to YouTube only: each selected clip goes to each ticked channel as its own upload, one
 * after another, with the clip's saved post text and your confirmed audience. A clip a channel already has is left out
 * unless you ask for it again. TikTok asks for a check of every post, so it stays on Prepare post.
 */
export function PostSelected({ clips, onClose }: { clips: Clip[]; onClose: () => void }) {
  const hid = useId();
  const [audience, setAudience] = useState<AudienceView | null>(null);
  const [audienceError, setAudienceError] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [chosen, setChosen] = useState<Connection[]>([]);
  const [kids, setKids] = useState<"" | "no" | "yes">("");
  const [running, setRunning] = useState<{ done: number; total: number } | null>(null);
  const [results, setResults] = useState<Outcome[] | null>(null);
  const [rows, setRows] = useState<Connection[] | null>(null);
  const [history, setHistory] = useState<Record<string, Publication[]> | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [again, setAgain] = useState(false);
  const clipIds = clips.map((c) => c.id).join("|");
  useEffect(() => {
    audienceApi.view().then(setAudience).catch((e) => setAudienceError(errorText(e)));
    studio.connections().then((r) => setRows(r.connections)).catch(() => setRows([]));
  }, []);
  // What each clip was already uploaded to, so one press never posts a clip to the same channel twice by accident.
  useEffect(() => {
    let alive = true;
    Promise.all(clips.map((c) => api.publications(c.id).then((list) => [c.id, list] as const)))
      .then((pairs) => alive && setHistory(Object.fromEntries(pairs)))
      .catch((e) => alive && setHistoryError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [clipIds]); // eslint-disable-line react-hooks/exhaustive-deps

  const yt = audience?.youtube;
  const privacy = yt?.intent === "PUBLIC" ? "public" : "private";
  // An old upload names no account: it went to the platform's default account.
  const fallback = rows?.find((r) => r.platform === "youtube" && r.is_default)?.id || "";
  const has = (clipId: string, c: Connection) => !!history?.[clipId]?.some(
    (p) => p.platform === "youtube" && (p.connection_id || fallback) === c.id && onChannel(p));
  const posts = clips.map((c) => {
    const there = chosen.filter((ch) => has(c.id, ch));
    return { clip: c, ...postOf(c), there, to: again ? chosen : chosen.filter((ch) => !there.includes(ch)) };
  });
  const longTitles = posts.filter((p) => p.title.length > 100).length;
  const total = posts.reduce((n, p) => n + p.to.length, 0);
  const repeats = posts.reduce((n, p) => n + p.there.length, 0);
  const missing = [
    !audience && !audienceError && "wait for your audience settings to load",
    !!audienceError && "reload the audience settings",
    yt && (!yt.confirmed || yt.intent === "LOCAL_ONLY") && "confirm who watches in Settings → Integrations",
    !!yt?.halted && "resolve the audience warning in Settings → Integrations",
    !history && !historyError && "wait while ClipForge reads where these clips were already posted",
    !!historyError && "close this and try again (the clips' earlier uploads could not be read)",
    !chosen.length && "choose at least one channel",
    chosen.length > 0 && !!history && !total && "tick another channel, or tick “Post them there again”",
    !kids && "answer “made for kids”",
    posts.some((p) => !p.title) && "give every clip a title in Prepare post",
    longTitles > 0 && "shorten the titles marked below to 100 characters in Prepare post",
    posts.some((p) => new TextEncoder().encode(p.description).length > 5000)
      && "shorten the descriptions marked below in Prepare post",
  ].filter(Boolean) as string[];

  const start = async () => {
    if (running) return;
    if (missing.length) {
      toast(`To post: ${missing.join(", ")}.`, true);
      return;
    }
    const out: Outcome[] = [];
    let done = 0;
    setRunning({ done, total });
    // One at a time, in order: each is its own upload request, and one refusal never stops the others.
    for (const p of posts) {
      for (const c of p.to) {
        setRunning({ done, total });
        const row = { key: `${p.clip.id}|${c.id}`, clip: p.title, channel: accountName(c) };
        try {
          await api.publish(p.clip.id, "youtube", {
            title: p.title, description: p.description, tags: p.tags, privacy, made_for_kids: kids === "yes",
            confirm: true, connection_id: c.id, expected_account_id: c.account_id,
          });
          out.push({ ...row, ok: true, text: "Started" });
        } catch (e) {
          out.push({ ...row, ok: false, text: errorText(e) });
        }
        done += 1;
      }
    }
    setRunning(null);
    setResults(out);
  };

  const close = () => { if (!running) onClose(); };
  const started = results?.filter((r) => r.ok).length || 0;
  return (
    <Dialog title={`Post ${clips.length === 1 ? "1 clip" : `${clips.length} clips`} to YouTube`} wide onClose={close}
      actions={results ? <button type="button" className="btn btn-primary" onClick={onClose}>Done</button> : <>
        <button type="button" className="btn" disabled={!!running} onClick={close}>Cancel</button>
        <button type="button" className="btn btn-primary" aria-disabled={missing.length > 0 || !!running || undefined}
          aria-describedby={`${hid}-why`} onClick={() => void start()}>
          {running ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="upload" />}
          {running ? `Starting ${Math.min(running.done + 1, running.total)} of ${running.total}…`
            : total > 1 ? `Start ${total} uploads` : "Start the upload"}
        </button>
      </>}>
      {results ? (
        <div className="stack-3" aria-live="polite">
          <p role="status"><b>{started} of {results.length} uploads started.</b>{" "}
            {started ? "Follow them on each clip's Prepare post page." : ""}</p>
          <ul className="post-selected-list">
            {results.map((r) => (
              <li key={r.key}>
                <span className="break"><b>{r.clip}</b> <span className="muted">to {r.channel}</span></span>
                {r.ok ? <Pill tone="good" icon="check">Started</Pill>
                  : <span className="small bad-text break">{r.text}</span>}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <fieldset className="stack-4" disabled={!!running}>
          <legend className="sr-only">Where and how these clips are posted</legend>
          <p className="small muted">TikTok asks you to check each post, so use Prepare post for TikTok.</p>
          {rows ? <ChannelPicker platforms={["youtube"]} rows={rows} value={ids} idPrefix={`${hid}-to`}
            legend="YouTube channels to post to" onChange={(next, accounts) => { setIds(next); setChosen(accounts); }} />
            : <p className="muted small">Loading accounts…</p>}
          <div className="field">
            <span className="label">Who can see it</span>
            {audienceError ? <span className="error-text">{audienceError}</span>
              : <span>{!yt ? "Loading…" : privacy === "public" ? "Public: anyone can watch"
                : yt.label || "Private"}</span>}
            <span className="hint">Your confirmed audience for new YouTube posts.{" "}
              <a className="textlink" href="#/settings/integrations">Change it in Settings → Integrations</a></span>
          </div>
          <fieldset>
            <legend className="label">Made for kids <span className="hint">(YouTube requires an answer)</span></legend>
            <label className="choice">
              <input type="radio" name={`${hid}-kids`} checked={kids === "no"} onChange={() => setKids("no")} />
              <span>No, they're not made for kids</span>
            </label>
            <label className="choice">
              <input type="radio" name={`${hid}-kids`} checked={kids === "yes"} onChange={() => setKids("yes")} />
              <span>Yes, they're made for kids</span>
            </label>
            <YouTubeComments privacy={privacy} kids={kids === "yes" ? true : kids === "no" ? false : null} />
          </fieldset>
          <div className="stack-2">
            <span className="label">Clips and their titles</span>
            <ul className="post-selected-list">
              {posts.map((p) => {
                const long = p.title.length > 100;
                const big = new TextEncoder().encode(p.description).length > 5000;
                return (
                  <li key={p.clip.id}>
                    <span className="break">{p.title || <span className="muted">(no title)</span>}
                      {p.there.length > 0 && <span className="block small muted">
                        Already on {nameList(p.there.map(accountName))}:{" "}
                        {again ? "posted there again" : "left out there"}</span>}
                    </span>
                    {(long || big || !p.title) && (
                      <a className="textlink small" href={`#/publish/${p.clip.id}`}>
                        {!p.title ? "Add a title" : long ? `Title is ${p.title.length}/100: shorten it`
                          : "Description too long: shorten it"}
                      </a>
                    )}
                  </li>
                );
              })}
            </ul>
            <p className="tiny faint">Each clip uses its saved post text (title, caption and hashtags). Edit it in the
              clip's Prepare post.</p>
            {repeats > 0 && (
              <label className="choice">
                <input type="checkbox" checked={again} onChange={(e) => setAgain(e.target.checked)} />
                <span>Post them there again <span className="hint block">
                  {repeats === 1 ? "1 upload is" : `${repeats} uploads are`} left out because the channel already has
                  that clip, or an upload of it is still under way. Tick this to upload {repeats === 1 ? "it" : "them"}
                  {" "}again anyway.</span></span>
              </label>
            )}
          </div>
          <div className="consequence">
            <span>
              {total > 0 ? `This starts ${total === 1 ? "1 upload" : `${total} uploads`}`
                + (repeats > 0 && !again ? " (clips a channel already has are left out)" : ": each clip")
                + ` to ${nameList(chosen.map(accountName))}, as ${privacy === "public" ? "Public" : "Private"}, `
                + "right away. "
                : ""}
              Every upload uses part of your project's daily YouTube upload allowance. ClipForge can't take an upload
              back; you would delete it in YouTube Studio.
            </span>
          </div>
          <p className="tiny muted" id={`${hid}-why`} role="status">
            {running ? `Starting ${Math.min(running.done + 1, running.total)} of ${running.total}…`
              : missing.length ? `To post: ${missing.join(", ")}.` : "Ready to start."}
          </p>
        </fieldset>
      )}
    </Dialog>
  );
}
