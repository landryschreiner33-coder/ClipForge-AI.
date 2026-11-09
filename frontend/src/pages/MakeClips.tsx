import { useEffect, useState } from "react";
import { errorText } from "../api";
import { DestinationPicker, ExampleSelect, FileDrop, Picked, StyleSelect, UsedFromBrain } from "../components/studioParts";
import { Banner, CAPTION_STYLES, Disclosure, Icon, PageHead, TRACKING } from "../components/ui";
import { Appearance, useAppearance } from "../prefs";
import { navigate } from "../router";
import { Connection, LinkCheck, Snapshot, studio } from "../studio";

const MODES = [
  { id: "highlights", name: "Highlights", text: "Pick the strongest short moments" },
  { id: "full_stories", name: "Full story", text: "Each story whole, in one clip" },
  { id: "story_parts", name: "Story parts", text: "Each story cut at its best moments into Part 1, Part 2…" },
] as const;
// Story parts are Full stories cut into parts: the same styles and example videos apply to both
const guidanceMode = (mode: string) => (mode === "story_parts" ? "full_stories" : mode);
const STORY_MODES = new Set(["full_stories", "story_parts"]);

const newRequestId = () => (crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`).replace(/[^A-Za-z0-9_-]/g, "");

/** Make clips: one video in (a file or a link), vertical clips out. The full-video questionnaire is never asked here. */
export default function MakeClips({ initialInput = "file" }: { initialInput?: "file" | "link" }) {
  const { appearance, set } = useAppearance();
  const [mode, setMode] = useState<string>(appearance.clips_mode);
  const [input, setInput] = useState<"file" | "link">(initialInput);
  const [file, setFile] = useState<Picked | null>(null);
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
  const ready = haveInput && (!upload || (dest.length > 0 && (!youtube.length || (kids && basis && agreed))));

  const submit = async () => {
    if (!haveInput) return;
    setBusy(true);
    setProblem("");
    try {
      const source = input === "file" ? { asset_id: file!.asset!.id } : { url: link.trim(), request_id: requestId };
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
    <div className="page">
      <PageHead kind="Make" title="Make clips" crumbs={[{ label: "Home", href: "#/" }, { label: "Make clips" }]}
        sub="Make vertical 1080×1920 clips with captions. Keep ClipForge running while it processes your video." />
      <div className="studio-grid">
        <div className="stack-5">
          <section className="panel" aria-labelledby="mc-mode">
            <h2 id="mc-mode">What kind of clips?</h2>
            <div className="mode-pick" role="radiogroup" aria-labelledby="mc-mode">
              {MODES.map((m) => (
                <label key={m.id}>
                  <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
                  <b>{m.name}</b><span>{m.text}</span>
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
          <section className="panel" aria-labelledby="mc-file">
            <h2 id="mc-file">Your video</h2>
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
              <FileDrop accept="video/*,.mkv,.m4v" label="Drop a video here" onAssets={(rows) => setFile(rows[0] || null)} />
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
          <section className="panel" aria-labelledby="mc-style">
            <h2 id="mc-style">Style</h2>
            <StyleSelect value={style} onChange={setStyle} mode={guidanceMode(mode)} />
            <ExampleSelect value={example} onChange={setExample} mode={guidanceMode(mode)} />
            <Disclosure summary="Customize captions and framing">
              {STORY_MODES.has(mode) && <p className="small muted">Story clips show the whole picture, still and centred, with the
                captions above it. Choose a framing or caption position here only to change that for this video.</p>}
              <div className="grid-2">
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
            </Disclosure>
          </section>
        </div>
        <div className="stack-5">
          <section className="panel" aria-labelledby="mc-brain">
            <h2 id="mc-brain">Used from your Brain</h2>
            <UsedFromBrain snapshot={snapshot} />
          </section>
          <section className="panel" aria-labelledby="mc-after">
            <h2 id="mc-after">When the clips are ready</h2>
            <div className="mode-pick" role="radiogroup" aria-labelledby="mc-after">
              <label><input type="radio" name="after" checked={!upload} onChange={() => setUpload(false)} />
                <b>Make clips only</b><span>Review and download; publish later.</span></label>
              <label><input type="radio" name="after" checked={upload} onChange={() => setUpload(true)} />
                <b>Make &amp; upload clips</b><span>Checked clips upload to the accounts you choose.</span></label>
            </div>
            {upload && (
              <div className="stack-3">
                <DestinationPicker value={dest} onChange={(ids, accs) => { setDest(ids); setAccounts(accs); }} />
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
                {tiktok.length > 0 && <p className="small">TikTok asks for your OK on every post: those clips wait for you in Publishing.</p>}
              </div>
            )}
          </section>
          {problem && <Banner tone="bad" title="Not started">{problem}</Banner>}
          <button type="button" className="btn btn-primary btn-large" disabled={!ready || busy} onClick={submit}>
            <Icon name="film" />{busy ? "Starting…" : upload ? "Make & upload clips" : "Make clips"}
          </button>
          {!haveInput && <p className="small muted">{input === "file" ? "Upload a video first." : "Paste a link to one video first."}</p>}
        </div>
      </div>
    </div>
  );
}
