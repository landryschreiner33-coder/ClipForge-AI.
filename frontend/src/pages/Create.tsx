import { useEffect, useRef, useState } from "react";
import { api, uploadVideo } from "../api";
import { Icon, Segmented, StylePicker, Toggle, TRACKING, toast } from "../components/ui";
import { navigate } from "../App";

const ACCEPT = [".mp4", ".mov", ".mkv", ".webm", ".m4v"];
const LENGTHS = [
  { value: "short", label: "15-30s", min: 15, max: 30, target: 22 },
  { value: "standard", label: "15-60s", min: 15, max: 60, target: 30 },
  { value: "long", label: "30-90s", min: 30, max: 90, target: 50 },
];

function fmtSize(b: number) {
  return b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`;
}

export default function Create() {
  const [file, setFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [mode, setMode] = useState<"file" | "url">("file");
  const [url, setUrl] = useState("");
  const [count, setCount] = useState(5);
  const [length, setLength] = useState("standard");
  const [style, setStyle] = useState("bold");
  const [tracking, setTracking] = useState("auto");
  const [layout, setLayout] = useState("fill");
  const [silence, setSilence] = useState("light");
  const [zoom, setZoom] = useState(true);
  const [hookOverlay, setHookOverlay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const tInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.settings().then((s) => {
      if ([3, 5, 10].includes(s.clip_count)) setCount(s.clip_count);
      setStyle(s.caption_style);
      setTracking(s.tracking);
      setLayout(s.layout);
      setSilence(s.silence);
      setZoom(!!s.auto_zoom);
      setHookOverlay(!!s.hook_overlay);
    }).catch(() => undefined);
  }, []);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
    if (!ACCEPT.includes(ext)) {
      toast(`Unsupported file type ${ext}. Use ${ACCEPT.join(", ")}`, true);
      return;
    }
    setFile(f);
  };

  const options = () => {
    const L = LENGTHS.find((l) => l.value === length)!;
    return {
      clip_count: count, min_duration: L.min, max_duration: L.max, target_duration: L.target,
      caption_style: style, tracking, layout, silence, auto_zoom: zoom, hook_overlay: hookOverlay,
    };
  };

  const submit = async () => {
    setBusy(true);
    try {
      let project;
      if (mode === "url") {
        project = await api.importUrl(url.trim(), options());
      } else {
        if (!file) return;
        project = await uploadVideo(file, options(), transcript, setProgress);
      }
      navigate(`/project/${project.id}`);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };

  const ready = mode === "file" ? !!file : /^https?:\/\//i.test(url.trim());

  return (
    <div className="page" style={{ maxWidth: 980 }}>
      <div className="page-head">
        <div>
          <h1>Create clips</h1>
          <p>Upload a long video. ClipFoundry finds the best moments and renders captioned 9:16 shorts.</p>
        </div>
        <Segmented value={mode} onChange={setMode}
          options={[{ value: "file", label: "Upload file" }, { value: "url", label: "From URL" }]} />
      </div>

      {mode === "file" ? (
        !file ? (
          <div className={`dropzone ${drag ? "drag" : ""}`} onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}>
            <Icon name="upload" size={38} />
            <h3>Drag & drop your video here</h3>
            <div className="muted">or click to browse. Podcasts, streams, interviews, lectures, vlogs...</div>
            <div className="formats">
              {ACCEPT.map((a) => <span key={a} className="badge">{a.slice(1).toUpperCase()}</span>)}
            </div>
            <input ref={input} type="file" accept={ACCEPT.join(",")} hidden onChange={(e) => pick(e.target.files?.[0])} />
          </div>
        ) : (
          <div className="file-chip">
            <Icon name="film" size={28} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{file.name}</div>
              <div className="small muted">{fmtSize(file.size)}</div>
              {busy && <div className="bar mt-s"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>}
            </div>
            {!busy && <button className="btn ghost sm" onClick={() => setFile(null)}><Icon name="x" size={14} /> Change</button>}
          </div>
        )
      ) : (
        <div className="card">
          <label className="field">
            Video URL
            <input type="url" placeholder="https://..." value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <div className="field-hint mt-s">
            Optional, uses yt-dlp. Only for publicly accessible videos you have the rights to use. ClipFoundry does not
            bypass DRM, paywalls, logins or other access controls.
          </div>
        </div>
      )}

      <div className="card mt">
        <div className="opt-row">
          <div className="lbl">Clips<small>Maximum; weak moments are skipped</small></div>
          <Segmented big value={count} onChange={setCount} options={[3, 5, 10].map((n) => ({ value: n, label: n }))} />
        </div>
        <div className="opt-row">
          <div className="lbl">Clip length</div>
          <Segmented value={length} onChange={setLength} options={LENGTHS.map((l) => ({ value: l.value, label: l.label }))} />
        </div>
        <div className="opt-row" style={{ alignItems: "start" }}>
          <div className="lbl">Caption style</div>
          <StylePicker value={style} onChange={setStyle} />
        </div>
        <div className="opt-row">
          <div className="lbl">Framing<small>How the 9:16 crop follows the action</small></div>
          <div className="row wrap">
            <select value={tracking} onChange={(e) => setTracking(e.target.value)} style={{ width: 200 }}>
              {TRACKING.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <Segmented value={layout} onChange={setLayout}
              options={[{ value: "fill", label: "Fill (crop)" }, { value: "fit", label: "Fit (blurred bg)" }]} />
          </div>
        </div>
        <div className="opt-row">
          <div className="lbl">Silence cleanup</div>
          <Segmented value={silence} onChange={setSilence}
            options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" }, { value: "aggressive", label: "Aggressive" }]} />
        </div>
        <div className="opt-row">
          <div className="lbl">Extras</div>
          <div className="row wrap" style={{ gap: 24 }}>
            <Toggle on={zoom} onChange={setZoom} label="Subtle auto-zoom" />
            <Toggle on={hookOverlay} onChange={setHookOverlay} label="On-screen hook (first seconds)" />
          </div>
        </div>
        {mode === "file" && (
          <div className="opt-row">
            <div className="lbl">Transcript<small>Optional .srt / .vtt; skips Whisper</small></div>
            <div className="row">
              <button className="btn sm" onClick={() => tInput.current?.click()}>
                {transcript ? transcript.name : "Attach transcript"}
              </button>
              {transcript && <button className="btn ghost sm" onClick={() => setTranscript(null)}>Remove</button>}
              <input ref={tInput} type="file" accept=".srt,.vtt,.json" hidden
                onChange={(e) => setTranscript(e.target.files?.[0] || null)} />
            </div>
          </div>
        )}
      </div>

      <div className="row mt" style={{ justifyContent: "flex-end" }}>
        <button className="btn primary xl" disabled={!ready || busy} onClick={submit}>
          {busy ? <><div className="spinner" style={{ width: 18, height: 18 }} /> {mode === "file" ? `Uploading ${Math.round(progress * 100)}%` : "Starting"}</>
            : <><Icon name="spark" /> CREATE CLIPS</>}
        </button>
      </div>
    </div>
  );
}
