import { useEffect, useState } from "react";
import { errorText } from "../api";
import { DestinationPicker, FileDrop, Picked, StyleSelect, UsedFromBrain } from "../components/studioParts";
import { Banner, CAPTION_STYLES, Disclosure, Icon, PageHead, TRACKING } from "../components/ui";
import { useAppearance } from "../prefs";
import { navigate } from "../router";
import { Connection, Snapshot, studio } from "../studio";

const MODES = [
  { id: "highlights", name: "Highlights", text: "Pick the strongest short moments" },
  { id: "full_stories", name: "Full stories", text: "Make one complete clip for each story" },
] as const;

/** Make clips: one video in, vertical clips out. The full-video questionnaire is never asked here. */
export default function MakeClips() {
  const { appearance, set } = useAppearance();
  const [mode, setMode] = useState<string>(appearance.clips_mode);
  const [file, setFile] = useState<Picked | null>(null);
  const [style, setStyle] = useState("saved");
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
    studio.preview({ mode, style_id: style, choices, title: file?.file.name || "" })
      .then((s) => alive && setSnapshot(s)).catch(() => alive && setSnapshot(null));
    return () => {
      alive = false;
    };
  }, [mode, style, choices, file?.file.name]);

  const youtube = accounts.filter((a) => a.platform === "youtube");
  const tiktok = accounts.filter((a) => a.platform === "tiktok");
  const ready = !!file?.asset && (!upload || (dest.length > 0 && (!youtube.length || (kids && basis && agreed))));

  const submit = async () => {
    if (!file?.asset) return;
    setBusy(true);
    setProblem("");
    try {
      const body: Record<string, unknown> = { asset_id: file.asset.id, mode, style_id: style, choices };
      if (upload) {
        body.upload = { intent: "make_and_upload", destinations: dest, privacy, made_for_kids: kids === "yes",
          reuse_basis: basis, agreed };
      }
      const project = await studio.makeClips(body);
      if (mode !== appearance.clips_mode) set({ clips_mode: mode as "highlights" | "full_stories" });
      navigate(`project/${project.id}`);
    } catch (e) {
      setProblem(errorText(e));
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
            {mode === "full_stories" && <p className="small muted">Each story keeps its setup and ending, however long it is.
              Stories ClipForge is not sure about wait for you to check them; nothing is cut short to fit a platform.</p>}
          </section>
          <section className="panel" aria-labelledby="mc-file">
            <h2 id="mc-file">Your video</h2>
            <FileDrop accept="video/*,.mkv,.m4v" label="Drop a video here" onAssets={(rows) => setFile(rows[0] || null)} />
            <p className="small muted">Have a link to the video, or its own transcript file? <a className="textlink" href="#/create/link">Add it from a link instead</a>.</p>
          </section>
          <section className="panel" aria-labelledby="mc-style">
            <h2 id="mc-style">Style</h2>
            <StyleSelect value={style} onChange={setStyle} mode={mode} />
            <Disclosure summary="Customize captions and framing">
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
          {!file?.asset && <p className="small muted">Upload a video first.</p>}
        </div>
      </div>
    </div>
  );
}
