import { useEffect, useState } from "react";
import { errorText } from "../api";
import { ChannelPicker } from "../components/channelPicker";
import {
  ExampleSelect, FileDrop, Picked, StyleSelect, UsedFromBrain, useUploadsByFile,
} from "../components/studioParts";
import { Banner, CAPTION_STYLES, Icon, PageHead, TRACKING } from "../components/ui";
import { Appearance, useAppearance } from "../prefs";
import { navigate } from "../router";
import { Connection, LinkCheck, Snapshot, studio } from "../studio";
import "./MakeClips.css";

/** What to make, in the owner's words (the space studio, 2026-11-19): Highlights picks the best moments, Full story
 * keeps each story from start to finish, Story parts splits each story into numbered parts. */
const MODES = [
  { id: "highlights", name: "Highlights", say: "Pick the best moments", more: "Short clips of the strongest parts" },
  { id: "full_stories", name: "Full story", say: "Keep each story from start to finish", more: "One clip for each story" },
  { id: "story_parts", name: "Story parts", say: "Split each story into Part 1, Part 2…",
    more: "Each story cut where it is most gripping" },
] as const;
// Story parts are Full stories cut into parts: the same styles and example videos apply to both
const guidanceMode = (mode: string) => (mode === "story_parts" ? "full_stories" : mode);
const STORY_MODES = new Set(["full_stories", "story_parts"]);

const newRequestId = () => (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9_-]/g, "");

/**
 * Make clips: one video in (a file or a link), vertical clips out. The full-video questionnaire is never asked here.
 *
 * The first-clip path (the space studio, 2026-11-19): 1 Choose a video, 2 Pick what to make, 3 Make clips. Everything
 * else starts from working defaults (your saved style, no example, captions and framing from the style, clips kept for
 * you to review) and sits under More options. Step 3 says what happens next, in the words the project page shows.
 */
export default function MakeClips({ initialInput = "file" }: { initialInput?: "file" | "link" }) {
  const { appearance, set } = useAppearance();
  const [mode, setMode] = useState<string>(appearance.clips_mode);
  const [input, setInput] = useState<"file" | "link">(initialInput);
  const [file, setFile] = useState<Picked | null>(null);
  const uploaded = useUploadsByFile();
  const [link, setLink] = useState("");
  const [checked, setChecked] = useState<LinkCheck | null>(null);
  const [requestId, setRequestId] = useState(newRequestId);
  const [style, setStyle] = useState("saved");
  const [example, setExample] = useState("");
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [upload, setUpload] = useState(false);
  const [dest, setDest] = useState<string[]>([]);
  const [accounts, setAccounts] = useState<Connection[]>([]);
  const [privacy, setPrivacy] = useState("private");
  const [kids, setKids] = useState<"" | "yes" | "no">("");
  const [basis, setBasis] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [more, setMore] = useState(false);

  useEffect(() => setMode(appearance.clips_mode), [appearance.clips_mode]);
  useEffect(() => {
    let alive = true;
    setSnapshot(null);
    studio.preview({ mode, style_id: style, choices, title: input === "file" ? file?.file.name || "" : "", reference_id: example })
      .then((s) => alive && setSnapshot(s)).catch(() => alive && setSnapshot(null));
    return () => {
      alive = false;
    };
  }, [mode, style, choices, file?.file.name, input, example]);
  // The link is checked as it is typed, without fetching anything; the download starts only on Make clips.
  useEffect(() => {
    const value = link.trim();
    setChecked(null);
    if (!value) return;
    let alive = true;
    const t = window.setTimeout(() => {
      studio.linkCheck(value).then((r) => alive && setChecked(r)).catch(() => alive && setChecked(null));
    }, 300);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [link]);

  const youtube = accounts.filter((a) => a.platform === "youtube");
  const tiktok = accounts.filter((a) => a.platform === "tiktok");
  const haveInput = input === "file" ? !!file?.asset : !!checked?.ok;
  const uploadAnswered = !upload || (dest.length > 0 && (!youtube.length || (kids && basis && agreed)));
  const ready = haveInput && uploadAnswered;
  // what More options holds that differs from the working defaults, so a closed More options still says so
  const changed = (style !== "saved" ? 1 : 0) + (example ? 1 : 0) + Object.keys(choices).length + (upload ? 1 : 0);
  const modeRow = MODES.find((m) => m.id === mode) || MODES[0];
  const videoName = input === "file" ? file?.file.name || "" : checked?.ok ? link.trim() : "";

  const submit = async () => {
    if (!haveInput) return;
    setBusy(true);
    setProblem("");
    try {
      const source = input === "file" ? { asset_id: file!.asset!.id, upload_ids: uploaded.of([file!.asset!.id]) }
        : { url: link.trim(), request_id: requestId };
      const body: Record<string, unknown> = { ...source, mode, style_id: style, choices, reference_id: example };
      if (upload) {
        body.upload = { intent: "make_and_upload", destinations: dest, privacy, made_for_kids: kids === "yes",
          reuse_basis: basis, agreed };
      }
      const project = await studio.makeClips(body);
      if (mode !== appearance.clips_mode) set({ clips_mode: mode as Appearance["clips_mode"] });
      navigate(`project/${project.id}`);
    } catch (e) {
      setProblem(errorText(e));
      setRequestId(newRequestId());  // a corrected request is a new one
      setBusy(false);
    }
  };

  const choose = (k: string, v: string) => setChoices((c) => {
    const next = { ...c };
    if (v) next[k] = v;
    else delete next[k];
    return next;
  });

  return (
    <div className="page mc-space">
      <PageHead kind="Make" title="Make clips" crumbs={[{ label: "Studio", href: "#/" }, { label: "Make clips" }]}
        sub="Choose a video, pick what to make, then press Make clips. Each clip is a vertical video with captions." />
      <div className="mc-layout">
        <section className="mc-step mc-file" aria-labelledby="mc-file">
          <h2 id="mc-file"><span className="mc-num" aria-hidden="true">1</span>Choose a video</h2>
          <div className="seg" role="radiogroup" aria-label="Where the video comes from">
            <label className={input === "file" ? "on" : ""}>
              <input type="radio" name="input" value="file" checked={input === "file"} onChange={() => setInput("file")} />
              <Icon name="upload" />Video file
            </label>
            <label className={input === "link" ? "on" : ""}>
              <input type="radio" name="input" value="link" checked={input === "link"} onChange={() => setInput("link")} />
              <Icon name="link" />Video link
            </label>
          </div>
          {input === "file" ? (
            <FileDrop accept="video/*,.mkv,.m4v" label="Drop a video here" button="Choose a video"
              onAssets={(rows) => setFile(rows[0] || null)} onUploaded={uploaded.add} />
          ) : (
            <div className="stack-3">
              <label className="field"><span>Link to one video</span>
                <input type="url" inputMode="url" autoComplete="off" spellCheck={false} value={link}
                  placeholder="https://www.youtube.com/watch?v=…" aria-describedby="mc-link-help"
                  aria-invalid={checked ? !checked.ok : undefined} onChange={(e) => setLink(e.target.value)} /></label>
              <p id="mc-link-help" className="small muted" aria-live="polite">
                {checked?.ok ? (checked.platform === "youtube"
                  ? `YouTube video ${checked.video_id}. Only this video is downloaded, even if the link names a playlist.`
                  : "ClipForge downloads this one video when you press Make clips.")
                  : checked?.problem ? <><b>{checked.problem.label}.</b> {checked.problem.why} {checked.problem.fix}</>
                  : "YouTube watch, Shorts and youtu.be links work, and other public video pages ClipForge can read. No search key is needed."}
              </p>
              <p className="tiny faint">ClipForge never signs in or uses your browser's cookies. For a private or members-only video, use Video file with your own copy.</p>
            </div>
          )}
          <p className="small muted">Have the video's own transcript file? <a className="textlink" href="#/create/transcript">Add the video with its transcript</a>.</p>
        </section>

        <section className="mc-step mc-what" aria-labelledby="mc-mode">
          <h2 id="mc-mode"><span className="mc-num" aria-hidden="true">2</span>Pick what to make</h2>
          <div className="mode-pick mc-modes" role="radiogroup" aria-labelledby="mc-mode">
            {MODES.map((m) => (
              <label key={m.id}>
                <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
                <b>{m.say}</b><span className="mc-mode-name">{m.name}</span><span>{m.more}</span>
              </label>
            ))}
          </div>
          {mode === "full_stories" && <p className="small muted">ClipForge finds where each story starts and makes one clip per story,
            running until the next one starts. A story is never split, except one longer than 5 minutes: that one is split at its
            best point into Part 1, Part 2… so no clip is longer than 5 minutes.</p>}
          {mode === "story_parts" && <p className="small muted">ClipForge finds each story and cuts it where it is most gripping to
            stop (a cliffhanger, a reveal, a jump in time) into parts of about one to three minutes. Every part is its own clip with
            the story's title and “Part 1”, “Part 2”… at the top. No part is longer than 5 minutes.</p>}
          {STORY_MODES.has(mode) && <p className="small muted">The picture stays still: the whole video, centred, never cropped,
            zoomed or stretched, with the captions just above it. Every clip is made right away; you can still move a story's start
            or end afterwards.</p>}
        </section>

        <aside className="mc-go" aria-labelledby="mc-go">
          <h2 id="mc-go"><span className="mc-num" aria-hidden="true">3</span>Make clips</h2>
          <dl className="mc-sum">
            <div><dt>Video</dt><dd className="break">{videoName || <span className="muted">Not chosen yet</span>}</dd></div>
            <div><dt>Making</dt><dd>{modeRow.say} <span className="muted">({modeRow.name})</span></dd></div>
            <div><dt>When ready</dt><dd>{upload ? "Checked clips upload to the accounts you chose"
              : "You review them first"}</dd></div>
          </dl>
          {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}
          <button type="button" className="btn btn-primary btn-large mc-make" disabled={!ready || busy} onClick={submit}>
            <Icon name="film" />{busy ? "Starting…" : upload ? "Make & upload clips" : "Make clips"}
          </button>
          {!haveInput && <p className="small muted">{input === "file" ? "Upload a video first." : "Paste a link to one video first."}</p>}
          {haveInput && !uploadAnswered && (
            <p className="small muted">Choose the accounts{youtube.length ? " and answer the YouTube questions" : ""} under
              {" "}<button type="button" className="textlink" onClick={() => setMore(true)}>More options</button>.</p>
          )}
          <div className="mc-next">
            <h3>What happens next</h3>
            <ol>
              <li><b>{STORY_MODES.has(mode) ? "Finding the stories" : "Finding the best moments"}</b>
                <span>ClipForge listens to the video and {STORY_MODES.has(mode) ? "marks where each story starts and ends"
                  : "picks the moments worth a clip"}.</span></li>
              <li><b>Making the clips</b><span>One at a time, with captions. The project page counts them as they are
                made.</span></li>
              <li><b>Your clips are ready</b><span>Press Review clips to watch them, change their captions, save them or
                post them.</span></li>
            </ol>
            <p className="tiny faint">You can leave this page; Studio shows the progress too. Keep ClipForge running while it
              works.</p>
          </div>
        </aside>

        <div className="mc-more">
          <button type="button" className="mc-more-toggle" aria-expanded={more} aria-controls="mc-more-body"
            aria-label="More options" aria-describedby="mc-more-what mc-more-changed" onClick={() => setMore((o) => !o)}>
            <Icon name="chev" className="chev" />
            <span className="mc-more-words"><b>More options</b>
              <span id="mc-more-what">Style, example video, captions and framing, uploading</span></span>
            {changed > 0 && <span id="mc-more-changed" className="pill">{changed} changed</span>}
          </button>
          <div id="mc-more-body" className="mc-more-body" hidden={!more}>
            <div className="mc-group">
              <h3>Style</h3>
              <StyleSelect value={style} onChange={setStyle} mode={guidanceMode(mode)} />
              <ExampleSelect value={example} onChange={setExample} mode={guidanceMode(mode)} />
            </div>
            <div className="mc-group">
              <h3>Captions and framing</h3>
              {STORY_MODES.has(mode) && <p className="small muted">Story clips show the whole picture, still and centred, with the
                captions above it. Choose a framing or caption position here only to change that for this video.</p>}
              <div className="grid grid-2">
                <label className="field"><span>Caption position</span>
                  <select value={choices.caption_position || ""} onChange={(e) => choose("caption_position", e.target.value)}>
                    <option value="">From the style</option><option value="bottom">Lower third</option>
                    <option value="middle">Centre</option><option value="top">Top</option>
                  </select></label>
                <label className="field"><span>Caption look</span>
                  <select value={choices.caption_style || ""} onChange={(e) => choose("caption_style", e.target.value)}>
                    <option value="">From the style</option>
                    {CAPTION_STYLES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select></label>
                <label className="field"><span>Framing</span>
                  <select value={choices.layout || ""} onChange={(e) => choose("layout", e.target.value)}>
                    <option value="">From the style</option><option value="fill">Fill the frame</option>
                    <option value="fit">Fit with blurred background</option>
                  </select></label>
                <label className="field"><span>Follow</span>
                  <select value={choices.tracking || ""} onChange={(e) => choose("tracking", e.target.value)}>
                    <option value="">From the style</option>
                    {TRACKING.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select></label>
              </div>
            </div>
            <div className="mc-group" role="group" aria-labelledby="mc-after">
              <h3 id="mc-after">When the clips are ready</h3>
              <div className="mode-pick" role="radiogroup" aria-labelledby="mc-after">
                <label><input type="radio" name="after" checked={!upload} onChange={() => setUpload(false)} />
                  <b>Make clips only</b><span>Review and download; publish later.</span></label>
                <label><input type="radio" name="after" checked={upload} onChange={() => setUpload(true)} />
                  <b>Make &amp; upload clips</b><span>Checked clips upload to the accounts you choose.</span></label>
              </div>
              {upload && (
                <div className="stack-3">
                  <ChannelPicker platforms={["youtube", "tiktok"]} idPrefix="mc-dest" legend="Accounts to upload to"
                    value={dest} onChange={(ids, accs) => { setDest(ids); setAccounts(accs); }} />
                  {youtube.length > 0 && (
                    <>
                      <label className="field"><span>Who can watch on YouTube</span>
                        <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
                          <option value="private">Only me (Private)</option><option value="unlisted">Anyone with the link</option>
                          <option value="public">Public</option>
                        </select></label>
                      <fieldset className="field"><legend>Made for kids? (YouTube requires an answer)</legend>
                        <label><input type="radio" name="kids" checked={kids === "no"} onChange={() => setKids("no")} /> No</label>{" "}
                        <label><input type="radio" name="kids" checked={kids === "yes"} onChange={() => setKids("yes")} /> Yes</label>
                      </fieldset>
                      <fieldset className="field"><legend>May these clips be uploaded?</legend>
                        <label className="block"><input type="radio" name="basis" checked={basis === "owned"} onChange={() => setBasis("owned")} /> It is my own video</label>
                        <label className="block"><input type="radio" name="basis" checked={basis === "permission"} onChange={() => setBasis("permission")} /> I have permission or a license</label>
                        <label className="block"><input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} /> I confirm this for this video, once for all its clips</label>
                      </fieldset>
                      <p className="small muted">Each clip uploads once to each chosen channel after it passes the final check. A clip longer than 3 minutes uploads as a regular video, not a Short.</p>
                    </>
                  )}
                  {tiktok.length > 0 && <p className="small">TikTok asks for your OK on every post. Open a clip's Prepare
                    post to send it; the TikTok accounts you chose here are ticked for you there.</p>}
                </div>
              )}
            </div>
            <div className="mc-group">
              <h3 id="mc-brain">Used from your Brain</h3>
              <p className="small muted">Your Brain remembers your editing preferences. These are the ones this video will
                use.</p>
              <UsedFromBrain snapshot={snapshot} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
