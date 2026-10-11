import { useRef, useState } from "react";
import { api, errorText } from "../api";
import { ap } from "../autopilot";
import { ConnectAction, connectedOk, OpenVideosFolder, PLATFORMS } from "../components/apShared";
import { DEFAULT_TOPICS, splitTopics, TopicChoice } from "../components/topics";
import { Banner, Disclosure, Icon, LoadingPage, PageHead, PlatformName, Pill, toast } from "../components/ui";
import { plural } from "../format";
import { navigate } from "../router";
import { useStatus } from "../status";

/**
 * First-time setup in three steps (#/setup/videos, /mode, /posting): add your videos, choose how to work, and set up
 * posting when you're ready. Finish either starts Autopilot or goes Home. Nothing here posts anything: connecting an
 * account never allows a post by itself.
 */
const STEPS = [
  { id: "videos", label: "Add your videos" },
  { id: "mode", label: "Choose how to work" },
  { id: "posting", label: "Set up posting" },
];
type How = "" | "manual" | "autopilot";

// The choices live outside the page so they survive a trip to Add video and back (setup keeps no draft on disk).
const draft: { how: How; topics: string | null } = { how: "", topics: null };

/** Kept with the settings, so Home knows you chose to make clips yourself (and skips its welcome). */
const remember = (how: How) => api.saveSettings({ setup_mode: how === "manual" ? "manual" : "" });

export default function Setup({ step }: { step?: string }) {
  const { st, setData, refresh } = useStatus();
  const [, redraw] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const firstChoice = useRef<HTMLInputElement>(null);
  if (!st) return <LoadingPage label="Loading setup" />;

  const idx = Math.max(0, STEPS.findIndex((s) => s.id === step));
  const started = st.home.setup.started;
  const how: How = draft.how || (started ? "autopilot" : "");
  const topics = draft.topics ?? (st.home.setup.topics || DEFAULT_TOPICS);
  const setHow = (v: How) => {
    draft.how = v;
    setError("");
    redraw((x) => x + 1);
  };
  const setTopics = (t: string) => {
    draft.topics = t;
    setError("");
    redraw((x) => x + 1);
  };
  const folder = st.home.my_videos;

  const toPosting = () => {
    if (!how) {
      setError("Choose one way to work first.");
      firstChoice.current?.focus();
      return;
    }
    if (how === "autopilot" && !splitTopics(topics).length) {
      setError("Choose at least one topic, or type your own.");
      return;
    }
    navigate("setup/posting");
  };

  const finish = async () => {
    setBusy(true);
    try {
      if (how === "autopilot" && !st.enabled) {
        setData(await ap.start(topics));
        toast("Autopilot is on. Connecting an account did not allow any post by itself.");
      } else if (how === "autopilot") {
        if (topics !== st.home.setup.topics) await api.saveSettings({ trend_topics: topics });
        refresh();
        toast("Setup saved");
      } else {
        toast("Setup finished. Add a video whenever you like.");
      }
      await remember(how);
      navigate("");
    } catch (e) {
      toast(errorText(e), true);
      setBusy(false);
    }
  };

  let body;
  if (idx === 0) {
    body = (
      <section className="panel" aria-labelledby="st1">
        <h2 id="st1">Where are your videos?</h2>
        <p className="muted">Use videos you made, or videos you have permission to use. ClipFoundry never posts other
          people's videos without an agreement or a free license.</p>
        <div className="cols-2">
          <div className="choice-card stack-3" style={{ display: "grid", alignContent: "start", cursor: "auto" }}>
            <b>Choose one video now</b>
            <span className="small muted">Pick a long video and see its clips in a few minutes.</span>
            <a className="btn" href="#/create" style={{ justifySelf: "start" }}><Icon name="plus" />Choose a video</a>
          </div>
          <div className="choice-card stack-3" style={{ display: "grid", alignContent: "start", cursor: "auto" }}>
            <b>Use your videos folder</b>
            <span className="small muted">Anything you put in it is clipped by Autopilot, once it's on. Only put videos
              there that you made or may use.</span>
            <span style={{ justifySelf: "start" }}><OpenVideosFolder onDone={refresh} /></span>
            <span className="tiny faint">{folder.watching ? `${plural(folder.videos, "video")} in it now.`
              : "Not watched yet. Opening it creates the folder if needed and watches it."}</span>
            <Disclosure plain summary="Show folder location"><code className="break">{folder.path}</code></Disclosure>
          </div>
        </div>
        <div className="row wrap">
          <span className="grow small muted">You can do both, and add more later.</span>
          <a className="btn btn-primary" href="#/setup/mode">Continue</a>
        </div>
      </section>
    );
  } else if (idx === 1) {
    body = (
      <section className="panel" aria-labelledby="st2">
        <fieldset>
          <legend><h2 id="st2">How do you want to work?</h2></legend>
          <label className="choice-card">
            <input ref={firstChoice} type="radio" name="how" value="manual" checked={how === "manual"}
              onChange={() => setHow("manual")} />
            <span className="stack" style={{ gap: 2 }}>
              <b>I'll pick videos and make clips myself</b>
              <span className="small muted">You add a video, choose the clips you like, edit and export them. Nothing
                runs in the background.</span>
            </span>
          </label>
          <label className="choice-card">
            <input type="radio" name="how" value="autopilot" checked={how === "autopilot"}
              onChange={() => setHow("autopilot")} />
            <span className="stack" style={{ gap: 2 }}>
              <b>Let Autopilot do it</b>
              <span className="small muted">It clips your videos folder and public videos about your topics, writes
                titles and plans posting times. Clips of other people's videos stay on this PC: only videos you may
                reuse are planned for posting. Nothing is posted without your OK, or a permission you give
                separately.</span>
            </span>
          </label>
        </fieldset>
        {how === "autopilot" && <TopicChoice topics={topics} setTopics={setTopics} />}
        {error && <p className="error-text" role="alert"><Icon name="alert" className="sm" />{error}</p>}
        <div className="row wrap">
          <a className="btn btn-quiet" href="#/setup/videos">Back</a>
          <span className="grow small muted">You can switch any time.</span>
          <button type="button" className="btn btn-primary" onClick={toPosting}>Continue</button>
        </div>
      </section>
    );
  } else {
    body = (
      <section className="panel" aria-labelledby="st3">
        <h2 id="st3">Post to YouTube and TikTok when you're ready</h2>
        <p className="muted">Optional. Without accounts you can still make clips and export them. Connecting an account
          does <b>not</b> let ClipFoundry post by itself: every post needs your OK, and YouTube can post automatically
          only if you turn that on separately. TikTok always asks.</p>
        <div className="rows">
          {PLATFORMS.map((p) => {
            const acc = st.platforms[p];
            return (
              <div key={p} className="row wrap" style={{ padding: "12px 0" }}>
                <PlatformName platform={p} />
                <span className="grow small muted">{p === "youtube"
                  ? "Posts Shorts to your channel and finds videos you may use."
                  : "Posts to your TikTok account, with your OK on each post."}</span>
                {connectedOk(acc) ? <Pill tone="good" icon="check">Connected: {acc.name || acc.account_id}</Pill> : (
                  <span className="row wrap">
                    {acc.needs_reconnect && <Pill tone="bad" icon="alert">Sign-in expired</Pill>}
                    <ConnectAction platform={p} account={acc} onChange={refresh} />
                  </span>
                )}
              </div>
            );
          })}
        </div>
        <p className="small muted">The first time, each platform asks for the two codes of your own free developer app
          (about 10 minutes, steps included).</p>
        {how === "autopilot" && (
          <p className="small muted">Autopilot uses the accounts you connected. To let YouTube posts go out without
            your review, turn on automatic publishing later on the Autopilot page: it asks exactly what you allow.</p>
        )}
        {!how && (
          <Banner tone="info" title="You haven't chosen how to work yet"
            actions={<a className="btn btn-small" href="#/setup/mode">Choose how to work</a>} />
        )}
        <div className="row wrap">
          <a className="btn btn-quiet" href="#/setup/mode">Back</a>
          <span className="grow" />
          {how === "autopilot" && !st.enabled && (
            <a className="btn" href="#/" onClick={() => void remember("").catch(() => {})}>Finish without starting</a>
          )}
          {!how && <a className="btn" href="#/">Skip for now</a>}
          {how && (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={finish}>
              {how === "autopilot" && !st.enabled ? <><Icon name="play" />Start Autopilot</> : "Finish"}
            </button>
          )}
        </div>
      </section>
    );
  }

  return (
    <div className="page narrow">
      <PageHead title="Set up ClipFoundry" sub="Three short steps. You can skip anything and come back later." />
      {started && (
        <Banner tone="info" title={`Autopilot is already set up${st.enabled ? " and on" : ""}`}>
          You can change these choices any time; Autopilot keeps working the way it is until you finish.
        </Banner>
      )}
      <ol className="setup-steps" aria-label="Setup steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className={i < idx ? "done" : ""} aria-current={i === idx ? "step" : undefined}>
            <span className="n">{i < idx ? <Icon name="check" className="sm" /> : i + 1}</span>
            {s.label}
            {i < idx && <span className="sr-only"> (done)</span>}
          </li>
        ))}
      </ol>
      {body}
    </div>
  );
}
