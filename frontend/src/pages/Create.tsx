import { ReactNode, useEffect, useId, useRef, useState } from "react";
import { api, errorText, Settings, uploadVideo } from "../api";
import { Banner, Icon, PageHead, ProgressBar, Segmented, StylePicker, TRACKING, toast } from "../components/ui";
import { navigate } from "../router";
import "./library.css";

const ACCEPT = [".mp4", ".mov", ".mkv", ".webm", ".m4v"];
const LENGTHS = [
  { value: "short", label: "15–30 s", min: 15, max: 30, target: 22 },
  { value: "standard", label: "15–60 s", min: 15, max: 60, target: 30 },
  { value: "long", label: "30–90 s", min: 30, max: 90, target: 50 },
];
const COUNTS = [3, 5, 10];

function fmtSize(b: number) {
  return b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`;
}
const isLink = (s: string) => /^https?:\/\/\S+$/i.test(s.trim());

/** One labeled row of the options: the label and its hint on the left, the control on the right. */
function Setting({ label, hint, id, children }: { label: string; hint?: string; id?: string; children: ReactNode }) {
  return (
    <div className="setting">
      <div className="stack" style={{ gap: 2 }}>
        {id ? <label className="label" htmlFor={id}>{label}</label> : <span className="label">{label}</span>}
        {hint && <span className="hint">{hint}</span>}
      </div>
      <div style={{ minWidth: 0 }}>{children}</div>
    </div>
  );
}

/**
 * Add video: a file from this computer (or a link), copied into ClipFoundry with real upload progress. The options
 * start from the saved defaults and only apply to this video; Settings stay as they are.
 */
export default function Create() {
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [url, setUrl] = useState("");
  const [defaults, setDefaults] = useState<Settings | null>(null);
  const [count, setCount] = useState(5);
  const [length, setLength] = useState("standard");
  const [style, setStyle] = useState("bold");
  const [tracking, setTracking] = useState("auto");
  const [layout, setLayout] = useState("fill");
  const [silence, setSilence] = useState("light");
  const [zoom, setZoom] = useState(true);
  const [hookOverlay, setHookOverlay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const tInput = useRef<HTMLInputElement>(null);
  const ids = useId();

  useEffect(() => {
    api.settings().then((s) => {
      setDefaults(s);
      if (typeof s.clip_count === "number") setCount(s.clip_count);
      const preset = LENGTHS.find((l) => l.min === s.min_duration && l.max === s.max_duration);
      setLength(preset ? preset.value : "saved");
      if (s.caption_style) setStyle(s.caption_style);
      if (s.tracking) setTracking(s.tracking);
      if (s.layout) setLayout(s.layout);
      if (s.silence) setSilence(s.silence);
      setZoom(!!s.auto_zoom);
      setHookOverlay(!!s.hook_overlay);
    }).catch(() => undefined);
  }, []);

  // Closing the window stops the copy; moving to another page in the app does not.
  useEffect(() => {
    if (!busy) return;
    const stay = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", stay);
    return () => window.removeEventListener("beforeunload", stay);
  }, [busy]);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    const ext = `.${(f.name.split(".").pop() || "").toLowerCase()}`;
    if (!ACCEPT.includes(ext)) {
      toast(`“${f.name}” isn't a video ClipFoundry can use. Use MP4, MOV, MKV, WEBM or M4V.`, true);
      return;
    }
    setProblem("");
    setFile(f);
  };

  const lengths = [...LENGTHS];
  if (defaults && length === "saved") {
    lengths.push({ value: "saved", label: `${defaults.min_duration}–${defaults.max_duration} s (your default)`,
      min: defaults.min_duration, max: defaults.max_duration, target: defaults.target_duration });
  }
  const saved = defaults && typeof defaults.clip_count === "number" ? [defaults.clip_count] : [];
  const counts = [...new Set([...COUNTS, ...saved])].sort((a, b) => a - b);

  const options = () => {
    const L = lengths.find((l) => l.value === length) || LENGTHS[1];
    return {
      clip_count: count, min_duration: L.min, max_duration: L.max, target_duration: L.target,
      caption_style: style, tracking, layout, silence, auto_zoom: zoom, hook_overlay: hookOverlay,
    };
  };

  const fromLink = !file && isLink(url);
  const ready = !!file || fromLink;
  const submit = async () => {
    if (!ready) return;
    setBusy(true);
    setProblem("");
    try {
      let project;
      if (file) {
        setProgress(0);
        project = await uploadVideo(file, options(), transcript, setProgress);
        toast("Video copied. ClipFoundry is making clips.");
      } else {
        project = await api.importUrl(url.trim(), options());
        toast("ClipFoundry is getting the video from the link.");
      }
      navigate(`project/${project.id}`);
    } catch (e) {
      setProblem(errorText(e));
      setProgress(null);
      setBusy(false);
    }
  };

  const pct = progress === null ? 0 : Math.round(progress * 100);
  return (
    <div className="page narrow">
      <PageHead crumbs={[{ label: "Library", href: "#/library" }, { label: "Add video" }]} title="Add video"
        sub={"Choose a long video on this computer. ClipFoundry copies it into its data folder, finds the best "
          + "moments and makes captioned vertical clips."} />

      {problem && (
        <Banner tone="bad" title={file ? "The video wasn't added" : "The link wasn't imported"}>
          {problem} You can try again.
        </Banner>
      )}

      {file ? (
        <section className="file-chip" aria-label="Chosen video">
          <Icon name="film" className="lg" />
          <div className="grow stack">
            <b className="break">{file.name}</b>
            <span className="small muted">{fmtSize(file.size)}</span>
            {progress !== null && (
              <>
                <ProgressBar value={progress} label="Copying the video into ClipFoundry" />
                <span className="small">
                  {pct < 100 ? `Copying into ClipFoundry: ${pct}%` : "Copied. ClipFoundry is finishing up…"}
                </span>
              </>
            )}
          </div>
          {!busy && (
            <button type="button" className="btn btn-quiet" onClick={() => { setFile(null); setTranscript(null); }}>
              Choose another
            </button>
          )}
        </section>
      ) : (
        <div className={`drop ${drag ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}>
          <Icon name="upload" className="lg" />
          <h2>Drop a video here</h2>
          <p className="muted small">MP4, MOV, MKV, WEBM or M4V. Only videos you made or may use.</p>
          <div className="drop-actions">
            <button type="button" className="btn btn-primary" onClick={() => input.current?.click()}>
              Choose a video
            </button>
          </div>
          <input ref={input} type="file" accept={ACCEPT.join(",")} className="sr-only" tabIndex={-1} aria-hidden="true"
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </div>
      )}

      <details className="more">
        <summary><Icon name="chev" className="chev" />Import from a link instead</summary>
        <div className="more-body">
          <div className="field">
            <label htmlFor={`${ids}-url`}>Video link</label>
            <input id={`${ids}-url`} type="url" placeholder="https://…" value={url} disabled={busy}
              aria-invalid={url.trim() !== "" && !isLink(url) ? true : undefined} aria-describedby={`${ids}-url-hint`}
              onChange={(e) => setUrl(e.target.value)} />
          </div>
          {url.trim() !== "" && !isLink(url) && (
            <p className="error-text">
              <Icon name="alert" className="sm" />Use a link that starts with http:// or https://
            </p>
          )}
          {file && isLink(url) && (
            <p className="small">
              <Icon name="info" className="sm" /> A video file is chosen above, so this link isn't used.
            </p>
          )}
          <p className="hint" id={`${ids}-url-hint`}>
            For publicly reachable videos you have the rights to use (it uses yt-dlp). ClipFoundry doesn't get around
            DRM, paywalls, logins or other access controls, and some sites don't allow downloads at all.
          </p>
        </div>
      </details>

      <details className="more">
        <summary>
          <Icon name="chev" className="chev" />More options{" "}
          <span className="tiny faint">clips, length, captions, framing</span>
        </summary>
        <div className="more-body">
          <p className="hint">These start from your defaults in Settings and apply only to this video.</p>
          <Setting label="Clips" hint="At most; weak moments are skipped">
            <Segmented label="Clips at most" value={count} onChange={setCount}
              options={counts.map((n) => ({ value: n, label: String(n) }))} />
          </Setting>
          <Setting label="Clip length">
            <Segmented label="Clip length" value={length} onChange={setLength}
              options={lengths.map((l) => ({ value: l.value, label: l.label }))} />
          </Setting>
          <Setting label="Caption style">
            <StylePicker value={style} onChange={setStyle} />
          </Setting>
          <Setting label="Framing" hint="How the 9:16 crop follows the action" id={`${ids}-track`}>
            <div className="stack">
              <select id={`${ids}-track`} value={tracking} onChange={(e) => setTracking(e.target.value)}>
                {TRACKING.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                {!TRACKING.some((t) => t.value === tracking) && <option value={tracking}>{tracking}</option>}
              </select>
              <Segmented label="Layout" value={layout} onChange={setLayout}
                options={[{ value: "fill", label: "Fill (crop)" },
                  { value: "fit", label: "Fit (blurred background)" }]} />
            </div>
          </Setting>
          <Setting label="Silence cleanup">
            <Segmented label="Silence cleanup" value={silence} onChange={setSilence}
              options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" },
                { value: "aggressive", label: "Strong" }]} />
          </Setting>
          <Setting label="Extras">
            <div className="stack" style={{ gap: 0 }}>
              <label className="choice">
                <input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} />
                <span>Subtle auto-zoom</span>
              </label>
              <label className="choice">
                <input type="checkbox" checked={hookOverlay} onChange={(e) => setHookOverlay(e.target.checked)} />
                <span>On-screen hook in the first seconds</span>
              </label>
            </div>
          </Setting>
          <Setting label="Transcript"
            hint="Optional .srt, .vtt or .json; skips the transcription. Only with a video file.">
            <div className="row wrap">
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => tInput.current?.click()}>
                <Icon name="upload" />{transcript ? "Choose another transcript…" : "Attach a transcript…"}
              </button>
              {transcript && (
                <>
                  <span className="small break">{transcript.name}</span>
                  <button type="button" className="btn btn-small btn-quiet" disabled={busy}
                    onClick={() => setTranscript(null)}>
                    Remove
                  </button>
                </>
              )}
              <input ref={tInput} type="file" accept=".srt,.vtt,.json" className="sr-only" tabIndex={-1}
                aria-hidden="true"
                onChange={(e) => { setTranscript(e.target.files?.[0] || null); e.target.value = ""; }} />
            </div>
          </Setting>
        </div>
      </details>

      <div className="row wrap" style={{ justifyContent: "flex-end" }}>
        <span className="small muted next-line">
          {file ? "Next: ClipFoundry copies the video, transcribes it on this computer and shows the clips on the "
            + "video's page."
            : fromLink ? "Next: ClipFoundry downloads the video from the link and shows its progress on the "
              + "video's page."
              : "Choose a video, or open “Import from a link instead”."}
        </span>
        <button type="button" className="btn btn-primary" disabled={!ready || busy} onClick={submit}>
          {busy ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name="scissors" />}
          {busy ? (file ? "Copying…" : "Starting…") : "Make clips"}
        </button>
      </div>
    </div>
  );
}
