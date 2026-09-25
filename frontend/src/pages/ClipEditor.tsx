import { useEffect, useMemo, useRef, useState } from "react";
import { alignWords, api, Clip, clipDownloadUrl, clipVideoUrl, ClipEdit, fmtPrecise, Project, Settings, Word } from "../api";
import { Icon, ScoreBadge, Segmented, StylePicker, Toggle, TRACKING, toast } from "../components/ui";
import { navigate } from "../App";

type Tab = "trim" | "framing" | "captions" | "hook" | "audio";

export default function ClipEditor({ id }: { id: string }) {
  const [clip, setClip] = useState<Clip | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [words, setWords] = useState<Word[]>([]);
  const [draft, setDraft] = useState<ClipEdit>({});
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [captionText, setCaptionText] = useState("");
  const [captionDirty, setCaptionDirty] = useState(false);
  const [customHook, setCustomHook] = useState("");
  const [tab, setTab] = useState<Tab>("trim");
  const [clickMode, setClickMode] = useState<"start" | "end">("start");
  const [view, setView] = useState<"clip" | "source">("clip");
  const [saving, setSaving] = useState(false);
  const srcVideo = useRef<HTMLVideoElement>(null);

  // initial load
  useEffect(() => {
    (async () => {
      try {
        const c = await api.clip(id);
        const [p, s, w] = await Promise.all([api.project(c.project_id), api.settings(), api.clipWords(id)]);
        setClip(c);
        setProject(p);
        setSettings(s);
        setWords(w.words);
        setDraft({ ...(c.edit || {}) });
        setTitle(c.title);
        setTags(c.hashtags.join(" "));
        const inRange = w.caption_words || w.words.filter((x) => x.end > w.start && x.start < w.end);
        setCaptionText(inRange.map((x) => x.w).join(" "));
      } catch (e) {
        toast((e as Error).message, true);
      }
    })();
  }, [id]);

  // poll while rendering
  useEffect(() => {
    if (!clip || (clip.status !== "rendering" && clip.status !== "queued")) return;
    const t = setTimeout(async () => setClip(await api.clip(id)), 1200);
    return () => clearTimeout(t);
  }, [clip, id]);

  const opts = (project?.options || {}) as Record<string, any>;
  const eff = <K extends keyof ClipEdit>(k: K, fallback: ClipEdit[K]): NonNullable<ClipEdit[K]> =>
    (draft[k] ?? opts[k as string] ?? settings?.[k as string] ?? fallback) as NonNullable<ClipEdit[K]>;
  const set = (patch: Partial<ClipEdit>) => setDraft((d) => ({ ...d, ...patch }));

  const start = draft.start ?? clip?.start ?? 0;
  const end = draft.end ?? clip?.end ?? 0;
  const hooks = useMemo(() => (clip ? [clip.hook, ...clip.hooks_alt].filter(Boolean) : []), [clip]);
  const currentHook = draft.hook ?? clip?.hook ?? "";
  const trimChanged = !!clip && (Math.abs(start - clip.start) > 0.01 || Math.abs(end - clip.end) > 0.01 ||
    draft.start !== clip.edit?.start || draft.end !== clip.edit?.end);

  // keep source preview inside the trim range
  useEffect(() => {
    const v = srcVideo.current;
    if (!v) return;
    const onTime = () => {
      if (v.currentTime >= end) v.pause();
    };
    v.addEventListener("timeupdate", onTime);
    return () => v.removeEventListener("timeupdate", onTime);
  }, [end, view]);

  if (!clip || !project || !settings) return <div className="page"><div className="spinner" /></div>;

  const setTrim = (s: number, e: number) => {
    const dur = project.duration || e;
    s = Math.max(0, Math.min(s, dur - 1));
    e = Math.max(s + 1, Math.min(e, dur));
    set({ start: +s.toFixed(2), end: +e.toFixed(2) });
    if (srcVideo.current) srcVideo.current.currentTime = s;
  };

  const onWordClick = (w: Word) => {
    if (clickMode === "start") setTrim(Math.max(0, w.start - 0.12), Math.max(end, w.start + 1.5));
    else setTrim(Math.min(start, w.end - 1.5), w.end + 0.3);
  };

  const save = async (render: boolean) => {
    setSaving(true);
    try {
      const edit: Record<string, unknown> = { ...draft };
      // keys removed in the editor (e.g. "Reset to AI cut") must be sent as null to clear them
      for (const k of Object.keys(clip.edit || {})) if (!(k in draft) || (draft as any)[k] === undefined) edit[k] = null;
      delete edit.caption_words;
      const rangeWords = words.filter((x) => x.end > start && x.start < end);
      const original = rangeWords.map((x) => x.w).join(" ");
      if (captionDirty) {
        edit.caption_words = captionText.trim() !== original.trim() ? alignWords(rangeWords, captionText) : null;
      } else if (trimChanged) {
        edit.caption_words = null;
      }
      const hashtags = tags.split(/[\s,]+/).filter(Boolean);
      await api.patchClip(id, { title, hashtags, caption_text: captionText, edit });
      if (render) {
        const c = await api.renderClip(id);
        setClip(c);
        setView("clip");
        toast("Re-rendering clip...");
      } else {
        setClip(await api.clip(id));
        toast("Saved");
      }
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setSaving(false);
    }
  };

  const resetTrim = () => {
    set({ start: undefined, end: undefined });
    setDraft((d) => {
      const n = { ...d };
      delete n.start;
      delete n.end;
      return n;
    });
  };

  const rendering = clip.status === "rendering" || clip.status === "queued";

  return (
    <div className="page">
      <div className="crumbs">
        <a href="#/projects">Projects</a> / <a href={`#/project/${project.id}`}>{project.name}</a> / Edit clip
      </div>
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: 22 }}>{clip.title}</h1>
          <p>Simple edits, then re-render. Source {fmtPrecise(start)} - {fmtPrecise(end)} ({(end - start).toFixed(1)}s)</p>
        </div>
        <div className="row">
          <ScoreBadge score={clip.score} />
          <button className="btn ghost" onClick={() => navigate(`/project/${project.id}`)}><Icon name="back" size={16} /> Back</button>
        </div>
      </div>

      <div className="editor">
        <div className="player">
          <div className="row" style={{ marginBottom: 10 }}>
            <Segmented value={view} onChange={setView}
              options={[{ value: "clip", label: "Rendered clip" }, { value: "source", label: "Source range" }]} />
          </div>
          {view === "source" ? (
            <video ref={srcVideo} src={`/api/projects/${project.id}/source#t=${start}`} controls playsInline
              style={{ aspectRatio: "16 / 9", objectFit: "contain" }}
              onLoadedMetadata={(e) => (e.currentTarget.currentTime = start)} />
          ) : rendering ? (
            <div className="rendering">
              <div className="spinner" />
              <b>{clip.status === "queued" ? "Queued" : `Rendering ${Math.round(clip.progress * 100)}%`}</b>
              <div className="bar" style={{ width: "80%" }}><div style={{ width: `${clip.progress * 100}%` }} /></div>
            </div>
          ) : clip.has_video ? (
            <video key={clip.version} src={clipVideoUrl(clip)} controls playsInline />
          ) : (
            <div className="rendering">
              <span className="badge bad">Not rendered</span>
              <div className="small muted">{clip.error}</div>
            </div>
          )}
          <div className="row mt" style={{ justifyContent: "center" }}>
            <a className="btn sm" href={clip.has_video ? clipDownloadUrl(clip) : undefined}
              style={clip.has_video ? undefined : { opacity: 0.45, pointerEvents: "none" }}>
              <Icon name="download" size={14} /> Download MP4
            </a>
          </div>
        </div>

        <div>
          <div className="tabs">
            {([["trim", "Trim"], ["framing", "Framing"], ["captions", "Captions"], ["hook", "Hook & text"], ["audio", "Audio"]] as [Tab, string][]).map(([k, l]) => (
              <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>

          {tab === "trim" && (
            <div className="card">
              <div className="grid grid-2">
                <TimeField label="Start" value={start} onChange={(v) => setTrim(v, end)} />
                <TimeField label="End" value={end} onChange={(v) => setTrim(start, v)} />
              </div>
              <div className="row between mt">
                <div className="row">
                  <span className="small muted">Click a word to set the</span>
                  <Segmented value={clickMode} onChange={setClickMode}
                    options={[{ value: "start", label: "start" }, { value: "end", label: "end" }]} />
                </div>
                <button className="btn ghost sm" onClick={resetTrim}>Reset to AI cut</button>
              </div>
              <div className="words mt-s">
                {words.map((w, i) => {
                  const inside = w.end > start && w.start < end;
                  const edge = inside && (i === 0 || !(words[i - 1].end > start && words[i - 1].start < end) ||
                    i === words.length - 1 || !(words[i + 1].end > start && words[i + 1].start < end));
                  return (
                    <span key={i} className={edge ? "edge" : inside ? "in" : ""} title={fmtPrecise(w.start)} onClick={() => onWordClick(w)}>
                      {w.w}
                    </span>
                  );
                })}
                {!words.length && <span className="muted">No transcript words near this clip.</span>}
              </div>
              <div className="field-hint mt-s">Cuts snap into the pauses around the words you pick. Use "Source range" above to check the cut before re-rendering.</div>
            </div>
          )}

          {tab === "framing" && (
            <div className="card">
              <div className="opt-row"><div className="lbl">Tracking</div>
                <select value={eff("tracking", "auto")} onChange={(e) => set({ tracking: e.target.value })}>
                  {[...TRACKING, { value: "manual", label: "Manual position" }].map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select></div>
              {eff("tracking", "auto") === "manual" && (
                <div className="opt-row"><div className="lbl">Horizontal position</div>
                  <input type="range" min={0} max={1} step={0.01} value={eff("crop_x", 0.5)} onChange={(e) => set({ crop_x: +e.target.value })} /></div>
              )}
              <div className="opt-row"><div className="lbl">Layout</div>
                <Segmented value={eff("layout", "fill")} onChange={(v) => set({ layout: v })}
                  options={[{ value: "fill", label: "Fill (crop)" }, { value: "fit", label: "Fit (blurred bg)" }]} /></div>
              <div className="opt-row"><div className="lbl">Zoom<small>{eff("zoom", 1).toFixed(2)}×</small></div>
                <input type="range" min={1} max={2} step={0.05} value={eff("zoom", 1)} onChange={(e) => set({ zoom: +e.target.value })} /></div>
              <div className="opt-row"><div className="lbl">Auto-zoom</div>
                <Toggle on={!!eff("auto_zoom", true)} onChange={(v) => set({ auto_zoom: v })} label="Subtle zoom changes between sentences" /></div>
              {clip.render_info?.mode && <div className="field-hint mt-s">Last render used <b>{clip.render_info.mode}</b> framing
                {clip.render_info.faces ? `, ${clip.render_info.faces} face track(s)` : ""}{clip.render_info.cuts ? `, ${clip.render_info.cuts} scene cut(s)` : ""}.</div>}
            </div>
          )}

          {tab === "captions" && (
            <div className="card">
              <div className="opt-row"><div className="lbl">Captions</div>
                <Toggle on={eff("captions_enabled", true)} onChange={(v) => set({ captions_enabled: v })} label="Burn captions into the video" /></div>
              <div className="opt-row" style={{ alignItems: "start" }}><div className="lbl">Style</div>
                <StylePicker value={eff("caption_style", "bold")} onChange={(v) => set({ caption_style: v })} /></div>
              <div className="opt-row"><div className="lbl">Position</div>
                <Segmented value={eff("caption_position", "bottom")} onChange={(v) => set({ caption_position: v })}
                  options={[{ value: "top", label: "Top" }, { value: "middle", label: "Middle" }, { value: "bottom", label: "Bottom" }]} /></div>
              <div className="opt-row"><div className="lbl">Size<small>{Math.round(eff("caption_size", 1) * 100)}%</small></div>
                <input type="range" min={0.6} max={1.6} step={0.05} value={eff("caption_size", 1)} onChange={(e) => set({ caption_size: +e.target.value })} /></div>
              <div className="opt-row"><div className="lbl">Word highlight</div>
                <div className="row">
                  <Toggle on={eff("highlight_words", true)} onChange={(v) => set({ highlight_words: v })} />
                  <input type="color" value={draft.highlight_color || "#FFE500"} onChange={(e) => set({ highlight_color: e.target.value })} />
                  {draft.highlight_color && <button className="btn ghost sm" onClick={() => set({ highlight_color: undefined })}>Style default</button>}
                </div></div>
              <label className="field mt">
                Caption text (fix misheard words; timing is kept)
                <textarea rows={7} value={captionText} onChange={(e) => { setCaptionText(e.target.value); setCaptionDirty(true); }} />
              </label>
            </div>
          )}

          {tab === "hook" && (
            <div className="card">
              <h3>On-screen hook</h3>
              <div className="grid" style={{ gap: 8 }}>
                {hooks.map((h, i) => (
                  <label key={i} className={`hook-opt ${currentHook === h ? "on" : ""}`}>
                    <input type="radio" checked={currentHook === h} onChange={() => set({ hook: h })} />
                    <span>{h}{i === 0 && <span className="badge good" style={{ marginLeft: 8 }}>Recommended</span>}</span>
                  </label>
                ))}
                <div className="row">
                  <input type="text" placeholder="Write your own hook..." value={customHook} onChange={(e) => setCustomHook(e.target.value)} />
                  <button className="btn" disabled={!customHook.trim()} onClick={() => set({ hook: customHook.trim() })}>Use</button>
                </div>
              </div>
              <div className="row wrap mt" style={{ gap: 20 }}>
                <Toggle on={eff("hook_overlay", true)} onChange={(v) => set({ hook_overlay: v })} label="Show hook on screen" />
                <label className="row small muted">for
                  <input type="number" min={1} max={15} step={0.5} style={{ width: 70 }} value={eff("hook_seconds", 3)}
                    onChange={(e) => set({ hook_seconds: +e.target.value })} /> seconds</label>
              </div>
              <div className="hr" />
              <label className="field">Title<input type="text" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
              <label className="field mt">Hashtags<input type="text" value={tags} onChange={(e) => setTags(e.target.value)} /></label>
              <div className="field-hint mt-s">Hooks are suggested from the clip's own words; they never add facts that aren't in the clip.</div>
            </div>
          )}

          {tab === "audio" && (
            <div className="card">
              <div className="opt-row"><div className="lbl">Volume<small>{eff("gain_db", 0) > 0 ? "+" : ""}{eff("gain_db", 0)} dB</small></div>
                <input type="range" min={-12} max={12} step={0.5} value={eff("gain_db", 0)} onChange={(e) => set({ gain_db: +e.target.value })} /></div>
              <div className="opt-row"><div className="lbl">Normalize loudness</div>
                <Toggle on={eff("normalize_audio", true)} onChange={(v) => set({ normalize_audio: v })} label="-14 LUFS (social media standard)" /></div>
              <div className="opt-row"><div className="lbl">Silence cleanup</div>
                <Segmented value={eff("silence", "light")} onChange={(v) => set({ silence: v })}
                  options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" }, { value: "aggressive", label: "Aggressive" }]} /></div>
              {clip.render_info?.removed_s > 0.1 && <div className="field-hint">Last render removed {clip.render_info.removed_s}s of pauses.</div>}
            </div>
          )}

          <div className="save-bar">
            {trimChanged && captionDirty && <span className="small muted">Trim changed: caption edits apply to words inside the new range.</span>}
            <button className="btn" disabled={saving} onClick={() => save(false)}>Save</button>
            <button className="btn primary" disabled={saving || rendering} onClick={() => save(true)}>
              <Icon name="refresh" size={16} /> Save & re-render
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TimeField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="field">
      {label} <span className="muted small">{fmtPrecise(value)}</span>
      <div className="row">
        <button className="btn sm" type="button" onClick={() => onChange(value - 0.5)}>-0.5s</button>
        <input type="number" step={0.1} value={value.toFixed(2)} onChange={(e) => onChange(+e.target.value)} />
        <button className="btn sm" type="button" onClick={() => onChange(value + 0.5)}>+0.5s</button>
      </div>
    </label>
  );
}
