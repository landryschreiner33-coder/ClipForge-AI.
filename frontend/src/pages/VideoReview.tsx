import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { LayoutFlow } from "../components/AppearanceSettings";
import { ClipForgeAI } from "../components/ClipForgeAI";
import { FilmCraftPanel, MadeWithLine } from "../components/FilmCraft";
import { Credits, FindMedia, MediaBanner, SourceLine } from "../components/FindMedia";
import { FileDrop, Picked, UsedFromBrain } from "../components/studioParts";
import { Banner, Disclosure, Icon, LoadingPage, PageHead, ProgressBar, toast } from "../components/ui";
import { AudioItem, AudioRole, fmtEdit, fmtTime, Overlay, Plan, PlanClip, SmartLevel, SmartReport, studio, TrackName, Video } from "../studio";

const PAGE = 60;  // sequence rows drawn at a time (the list stays light however long the project is)
const ROLE_WORDS: Record<AudioRole, string> = { voiceover: "Voiceover", music: "Music", effect: "Sound effect" };
const ROLE_TRACK: Record<AudioRole, TrackName> = { voiceover: "voiceover", music: "music", effect: "effects" };
const POSITIONS: [string, string][] = [["bottom", "Lower third"], ["raised", "Above player controls"], ["middle", "Centre"], ["top", "Top"]];

type EditFn = (change: Record<string, unknown>) => Promise<void>;

/** Seconds typed by hand, committed on Enter or when leaving the field (one edit, not one per keystroke). */
function TimeField({ label, ms, onCommit, disabled }: { label: string; ms: number; onCommit: (ms: number) => void; disabled?: boolean }) {
  const [text, setText] = useState((ms / 1000).toFixed(1));
  useEffect(() => setText((ms / 1000).toFixed(1)), [ms]);
  const commit = () => {
    const v = Math.round(parseFloat(text.replace(",", ".")) * 1000);
    if (Number.isFinite(v) && v !== ms) onCommit(v);
    else setText((ms / 1000).toFixed(1));
  };
  return (
    <label className="field time-field"><span>{label}</span>
      <input inputMode="decimal" value={text} disabled={disabled} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} /></label>
  );
}

/** A volume slider that saves once you let go (pointer, keyboard or leaving it). */
function Gain({ label, value, min, max, onCommit, disabled }: { label: string; value: number; min: number; max: number;
  onCommit: (v: number) => void; disabled?: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const commit = () => { if (v !== value) onCommit(v); };
  return (
    <label className="field"><span>{label} ({v > 0 ? "+" : ""}{v} dB)</span>
      <input type="range" min={min} max={max} step={1} value={v} disabled={disabled} onChange={(e) => setV(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onBlur={commit} /></label>
  );
}

/** The whole project at a glance: the picture sequence and each audio track, to scale. */
function Timeline({ v, selected, onSelect }: { v: Video; selected: string; onSelect: (id: string) => void }) {
  const total = Math.max(1, v.duration * 1000);
  const pct = (ms: number) => `${(100 * ms / total).toFixed(3)}%`;
  const rows: [TrackName, string][] = [["voiceover", "Voiceover"], ["music", "Music"], ["effects", "Effects"]];
  return (
    <div className="tl" aria-label="Timeline">
      <div className="tl-row"><span className="tl-name">Picture</span><div className="tl-lane">
        {v.timeline.map((s, i) => (
          <button key={s.clip_id} type="button" className={`tl-seg ${s.kind} ${selected === s.clip_id ? "on" : ""}`}
            style={{ left: pct(s.out_start_ms), width: pct(s.out_end_ms - s.out_start_ms) }}
            aria-label={`Clip ${i + 1}, ${fmtEdit(s.out_start_ms)} to ${fmtEdit(s.out_end_ms)}`} onClick={() => onSelect(s.clip_id)} />
        ))}</div></div>
      {(v.overlay_timeline?.length ?? 0) > 0 && <div className="tl-row"><span className="tl-name">Pictures</span><div className="tl-lane">
        {v.overlay_timeline!.map((o) => <span key={o.overlay_id} className="tl-seg image"
          style={{ left: pct(o.out_start_ms), width: pct(o.out_end_ms - o.out_start_ms) }} />)}</div></div>}
      {rows.map(([track, name]) => {
        const items = v.audio_timeline.filter((a) => a.track === track);
        const muted = v.plan?.tracks?.[track]?.mute;
        return (
          <div key={track} className={`tl-row ${muted ? "muted" : ""}`}><span className="tl-name">{name}</span><div className="tl-lane">
            {items.map((a) => <span key={a.audio_id} className={`tl-seg audio ${track}`} title={a.loop ? "Loops" : ""}
              style={{ left: pct(a.out_start_ms), width: pct(a.out_end_ms - a.out_start_ms) }} />)}
          </div></div>
        );
      })}
      <div className="tl-scale small muted"><span>0:00</span><span>{fmtTime(v.duration)}</span></div>
    </div>
  );
}

function ClipInspector({ c, plan, v, edit, busy }: { c: PlanClip; plan: Plan; v: Video; edit: EditFn; busy: boolean }) {
  const [splitAt, setSplitAt] = useState(Math.round((c.in_ms + c.out_ms) / 2));
  const asset = v.assets.find((a) => a.id === c.asset_id);
  const swaps = v.assets.filter((a) => a.id !== c.asset_id && a.kind !== "audio");
  const [swap, setSwap] = useState("");
  return (
    <div className="inspector stack-3">
      <div className="grid-3">
        <TimeField label="Starts at (s in the file)" ms={c.in_ms} disabled={busy} onCommit={(ms) => edit({ op: "trim", clip_id: c.id, in_ms: ms, out_ms: c.out_ms })} />
        <TimeField label="Ends at (s)" ms={c.out_ms} disabled={busy} onCommit={(ms) => edit({ op: "trim", clip_id: c.id, in_ms: c.in_ms, out_ms: ms })} />
        <div className="field"><span>Split</span><div className="row-actions">
          <TimeField label="At (s)" ms={splitAt} onCommit={setSplitAt} />
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "split", clip_id: c.id, at_ms: splitAt })}><Icon name="scissors" />Split</button>
        </div></div>
      </div>
      {c.kind === "video" && asset?.has_audio !== false && <div className="grid-3">
        <Gain label="Sound" value={c.gain_db} min={-12} max={12} disabled={busy} onCommit={(x) => edit({ op: "set", clip_id: c.id, field: "gain_db", value: x })} />
        <TimeField label="Fade in (s)" ms={c.fade_in_ms || 0} disabled={busy} onCommit={(ms) => edit({ op: "set", clip_id: c.id, field: "fade_in_ms", value: ms })} />
        <TimeField label="Fade out (s)" ms={c.fade_out_ms || 0} disabled={busy} onCommit={(ms) => edit({ op: "set", clip_id: c.id, field: "fade_out_ms", value: ms })} />
        <label><input type="checkbox" checked={!!c.mute} disabled={busy} onChange={(e) => edit({ op: "set", clip_id: c.id, field: "mute", value: e.target.checked })} /> Mute this clip's sound</label>
      </div>}
      {c.kind === "video" && <div className="grid-2">
        <label className="field"><span>Zoom</span>
          <select value={String(c.zoom || 1)} disabled={busy} onChange={(e) => edit({ op: "set", clip_id: c.id, field: "zoom", value: Number(e.target.value) })}>
            {[["1", "None"], ["1.1", "A little (110%)"], ["1.2", "More (120%)"], ["1.3", "Close (130%)"], ["1.5", "Very close (150%)"]].map(([z, t]) => <option key={z} value={z}>{t}</option>)}
            {c.zoom && ![1, 1.1, 1.2, 1.3, 1.5].includes(c.zoom) && <option value={String(c.zoom)}>{Math.round(c.zoom * 100)}%</option>}
          </select></label>
        {plan.clips[0]?.id !== c.id && <label className="field"><span>Join with the clip before</span>
          <select value={c.join || ""} disabled={busy} onChange={(e) => edit({ op: "set", clip_id: c.id, field: "join", value: e.target.value || null })}>
            <option value="">Like the rest of the video ({plan.transition.type === "cut" ? "straight cut" : plan.transition.type})</option>
            <option value="cut">Straight cut (jump cut)</option>
          </select></label>}
      </div>}
      <div className="grid-2">
        <label className="field"><span>Framing</span>
          <select value={c.layout || ""} disabled={busy} onChange={(e) => edit({ op: "set", clip_id: c.id, field: "layout", value: e.target.value || null })}>
            <option value="">Like the rest of the video ({plan.layout === "fill" ? "fill" : "fit"})</option>
            <option value="fit">Fit (blurred background)</option><option value="fill">Fill the frame</option>
          </select></label>
        {swaps.length > 0 && <div className="field"><span>Replace with</span><div className="row-actions">
          <select value={swap} aria-label="File to put in this clip's place" onChange={(e) => setSwap(e.target.value)}>
            <option value="">Choose a file</option>{swaps.map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}
          </select>
          <button type="button" className="btn btn-small" disabled={busy || !swap} onClick={() => edit({ op: "replace", clip_id: c.id, asset_id: swap })}>Replace</button>
        </div></div>}
      </div>
    </div>
  );
}

function AudioRow({ item, v, edit, busy }: { item: AudioItem; v: Video; edit: EditFn; busy: boolean }) {
  const placed = v.audio_timeline.find((a) => a.audio_id === item.id);
  const anchor = item.anchor && v.plan?.clips.find((c) => c.id === item.anchor?.clip_id);
  const set = (field: string, value: unknown) => edit({ op: "audio_set", audio_id: item.id, field, value });
  return (
    <li className={item.mute ? "off" : ""}>
      <div className="break">
        <b className="clamp-1">{item.label}</b>
        <span className="block small muted">{placed ? `${fmtEdit(placed.out_start_ms)}–${fmtEdit(placed.out_end_ms)}` : "Not heard"}
          {anchor ? ` · moves with “${anchor.label}”` : ""}{item.loop ? " · loops" : ""}
          {placed && placed.cut_ms > 0 ? ` · the last ${(placed.cut_ms / 1000).toFixed(1)} s is after the end of the video` : ""}</span>
      </div>
      <Disclosure summary="Change">
        <div className="stack-3">
          <div className="grid-3">
            {item.anchor ? <TimeField label="Starts after its clip (s)" ms={item.anchor.offset_ms} disabled={busy}
              onCommit={(ms) => edit({ op: "audio_move", audio_id: item.id, clip_id: item.anchor!.clip_id, offset_ms: ms })} />
              : <TimeField label="Starts at (s)" ms={item.start_ms} disabled={busy} onCommit={(ms) => edit({ op: "audio_move", audio_id: item.id, start_ms: ms })} />}
            {item.loop ? <TimeField label="Plays for (s, 0 = to the end)" ms={item.length_ms || 0} disabled={busy}
              onCommit={(ms) => edit({ op: "audio_trim", audio_id: item.id, length_ms: ms || null })} />
              : <><TimeField label="From (s in the file)" ms={item.in_ms} disabled={busy} onCommit={(ms) => edit({ op: "audio_trim", audio_id: item.id, in_ms: ms, out_ms: item.out_ms })} />
                <TimeField label="To (s)" ms={item.out_ms || 0} disabled={busy} onCommit={(ms) => edit({ op: "audio_trim", audio_id: item.id, in_ms: item.in_ms, out_ms: ms })} /></>}
          </div>
          <div className="grid-3">
            <Gain label="Volume" value={item.gain_db} min={-36} max={12} disabled={busy} onCommit={(x) => set("gain_db", x)} />
            <TimeField label="Fade in (s)" ms={item.fade_in_ms} disabled={busy} onCommit={(ms) => set("fade_in_ms", ms)} />
            <TimeField label="Fade out (s)" ms={item.fade_out_ms} disabled={busy} onCommit={(ms) => set("fade_out_ms", ms)} />
          </div>
          <div className="row-actions wrap">
            <label><input type="checkbox" checked={item.mute} disabled={busy} onChange={(e) => set("mute", e.target.checked)} /> Mute</label>
            {item.role !== "voiceover" && <label><input type="checkbox" checked={item.duck} disabled={busy} onChange={(e) => set("duck", e.target.checked)} /> Dips while people speak</label>}
            <label><input type="checkbox" checked={item.loop} disabled={busy} onChange={(e) => set("loop", e.target.checked)} /> Loop</label>
            {item.anchor ? <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "audio_move", audio_id: item.id, start_ms: placed?.out_start_ms ?? 0 })}>Stop following the clip</button> : null}
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "audio_remove", audio_id: item.id })}><Icon name="trash" />Remove from the track</button>
          </div>
        </div>
      </Disclosure>
    </li>
  );
}

const LEVELS: [SmartLevel, string, string][] = [
  ["smart", "Edit it for me", "Cut pauses, repeated takes and weak parts; pictures, music and sound effects"],
  ["tight", "Fast-paced", "Shorter pauses and a small zoom on every other cut"],
  ["off", "Keep my clips as they are", "Only the silence at the start and end is trimmed"]];
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** What the last smart edit did, in a sentence. */
function smartDone(r: SmartReport): string {
  const s = r.stats;
  const parts: string[] = [];
  if (s.pauses_cut) parts.push(`cut ${plural(s.pauses_cut, "pause")} (${Math.round(s.seconds_saved)} s)`);
  if (s.retakes) parts.push(`left out ${plural(s.retakes, "repeated take")}`);
  if (s.stumbles) parts.push(`cut ${plural(s.stumbles, "stumbled word")}`);
  if (s.ai_left_out) parts.push(`left out ${plural(s.ai_left_out, "weak part")} ClipForge AI found`);
  if (s.fit_left_out) parts.push(`left out ${plural(s.fit_left_out, "weaker sentence")} to fit your length`);
  if (s.overlays) parts.push(`showed ${plural(s.overlays, "picture")}`);
  if (s.music) parts.push("added music");
  if (s.effects) parts.push(`added ${plural(s.effects, "sound effect")}`);
  if (!parts.length) return "Nothing needed cutting.";
  const text = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  return text.charAt(0).toUpperCase() + text.slice(1) + ".";
}

/** Edit it for me (again): the smart edit with your choices, as a new version you can undo. */
function SmartPanel({ v, plan, busy, onStarted }: { v: Video; plan: Plan; busy: boolean; onStarted: () => void }) {
  const report = plan.smart;
  const brief = v.brief as Record<string, unknown>;
  const opts = (report?.options || {}) as Record<string, unknown>;
  const [level, setLevel] = useState<SmartLevel>(report && report.level !== "off" ? report.level : "smart");
  const [broll, setBroll] = useState(opts.broll !== undefined ? !!opts.broll : brief.broll_images !== false);
  const [fx, setFx] = useState(opts.sound_effects !== undefined ? !!opts.sound_effects : brief.sound_effects !== false);
  const [punch, setPunch] = useState<boolean | null>(typeof brief.punch_in === "boolean" ? brief.punch_in : null);
  const current = String(brief.music || "none");
  const [music, setMusic] = useState(current === "none" && !report ? "auto" : current);
  const [ai, setAi] = useState(brief.ai_edit !== false);
  const [minutes, setMinutes] = useState(brief.target_duration_s ? String(Math.round(Number(brief.target_duration_s) / 6) / 10) : "");
  const [starting, setStarting] = useState(false);
  const running = v.jobs.some((j) => j.kind === "video_smart" && (j.status === "running" || j.status === "queued"));
  const helper = v.ai_helper;
  const chapters = v.chapters || [];
  const start = async () => {
    setStarting(true);
    const m = parseFloat(minutes.replace(",", "."));
    try {
      await studio.smartVideo(v.id, v.plan_revision, { smart_edit: level, broll_images: broll, sound_effects: fx, music,
        ai_edit: ai, target_duration_s: Number.isFinite(m) && m > 0 ? Math.round(m * 60) : 0,
        ...(punch === null ? {} : { punch_in: punch }) });
      toast("Editing it for you. The new version appears here when it is ready; Undo goes back to this one.");
      onStarted();
    } catch (e) {
      toast(errorText(e), true);
    }
    setStarting(false);
  };
  const copyChapters = async () => {
    const text = chapters.map((c) => `${fmtTime(c.ms / 1000)} ${c.title}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast("Chapters copied. Paste them into your YouTube description.");
    } catch {
      toast(text);
    }
  };
  return (
    <section className="panel" aria-labelledby="vr-smart">
      <div className="panel-head"><h2 id="vr-smart">Edit it for me</h2>
        {report && report.level !== "off" && <span className="pill">{report.level === "tight" ? "Fast-paced" : "Smart edit"}</span>}</div>
      {report && report.level !== "off" ? <p>{smartDone(report)}</p>
        : <p className="muted">ClipForge can cut the pauses, repeated takes and weak parts, fit your length, and add your pictures, music and soft sound effects. It makes a new version you can undo.</p>}
      {report?.ai?.used ? <p className="small muted">{report.ai.sent}{report.ai.problems?.length ? ` Some parts were decided without it: ${report.ai.problems[0]}` : ""}</p>
        : report?.ai?.problem ? <p className="small muted">ClipForge AI was not used ({report.ai.problem}). <a href="#/settings/ai">ClipForge AI settings</a></p> : null}
      <Disclosure summary={report && report.level !== "off" ? "Edit it again with other choices" : "Choose how"}>
        <div className="stack-3">
          <div className="mode-pick">
            {LEVELS.map(([lv, t, d]) => (
              <label key={lv}><input type="radio" name="vr-smart-level" checked={level === lv} onChange={() => setLevel(lv)} /><b>{t}</b><span>{d}</span></label>
            ))}
          </div>
          <div className="grid-2">
            <label className="field"><span>Length in minutes</span><input inputMode="decimal" value={minutes} placeholder="Keep everything good" onChange={(e) => setMinutes(e.target.value)} /></label>
            <label className="field"><span>Music</span><select value={music} onChange={(e) => setMusic(e.target.value)}>
              <option value="auto">Pick for me (your music file, or free ClipForge music)</option>
              <option value="library">Free music made by ClipForge</option>
              {!!brief.music_asset_id && <option value="supplied">My own music file</option>}
              {current === "find" && <option value="find">Music found in Media sources</option>}
              <option value="none">No added music</option></select></label>
          </div>
          {level !== "off" && <div className="stack-2">
            <label><input type="checkbox" checked={broll} onChange={(e) => setBroll(e.target.checked)} /> Show my images over the video while people talk</label>
            <label><input type="checkbox" checked={fx} onChange={(e) => setFx(e.target.checked)} /> Soft sound effects at scene changes and pictures</label>
            <label><input type="checkbox" checked={punch ?? level === "tight"} onChange={(e) => setPunch(e.target.checked)} /> Zoom in a little on every other cut</label>
            <label><input type="checkbox" checked={ai && !!helper?.configured} disabled={!helper?.configured} onChange={(e) => setAi(e.target.checked)} /> Let ClipForge AI help{helper?.configured ? ` (${helper.label}${helper.local ? ", on this computer" : ", online"})` : ""}</label>
            {!helper?.configured && <p className="small muted">ClipForge AI has no model yet; the built-in editor works without one. <a href="#/settings/ai">Set up a free model</a></p>}
          </div>}
          <p className="small muted">Your look, captions, word fixes and the sounds and pictures you placed yourself stay. What it cuts stays in the sequence, switched off.</p>
          <button type="button" className="btn btn-primary" disabled={busy || starting || running} onClick={start}>
            <Icon name="create" />{running ? "Editing…" : report && report.level !== "off" ? "Edit it again" : "Edit it for me"}</button>
        </div>
      </Disclosure>
      {chapters.length > 0 && <Disclosure summary={`Chapters for YouTube (${chapters.length})`}>
        <ul className="small">{chapters.map((c) => <li key={`${c.ms}-${c.title}`}>{fmtTime(c.ms / 1000)} {c.title}</li>)}</ul>
        <button type="button" className="btn btn-small" onClick={copyChapters}>Copy for the description</button>
      </Disclosure>}
    </section>
  );
}

/** Pictures shown over the video while its sound goes on (B-roll). */
function Pictures({ v, plan, edit, busy }: { v: Video; plan: Plan; edit: EditFn; busy: boolean }) {
  const images = v.bin.map((aid) => v.assets.find((a) => a.id === aid)).filter((a) => a && (a.kind === "image" || a.kind === "video"));
  const clips = plan.clips.filter((c) => c.include && c.kind === "video");
  const [add, setAdd] = useState({ asset: "", clip: "" });
  const overlays = plan.overlays || [];
  if (!overlays.length && !images.some((a) => a!.kind === "image")) return null;
  const placed = (o: Overlay) => v.overlay_timeline?.find((x) => x.overlay_id === o.id);
  return (
    <section className="panel" aria-labelledby="vr-pictures">
      <h2 id="vr-pictures">Pictures over the video ({overlays.length})</h2>
      {overlays.length ? <ul className="seq audio-list">{overlays.map((o) => {
        const at = placed(o);
        const clip = plan.clips.find((c) => c.id === o.clip_id);
        return (
          <li key={o.id}>
            <div className="break">
              <b className="clamp-1">{o.label}</b>
              <span className="block small muted">{at ? `${fmtEdit(at.out_start_ms)}–${fmtEdit(at.out_end_ms)}` : "Not shown (its clip is switched off or too short)"}
                {clip ? ` · over “${clip.label}”` : ""}{o.why ? ` · ${o.why}` : ""}</span>
            </div>
            <div className="row-actions wrap">
              <select value={o.motion} aria-label={`Motion of ${o.label}`} disabled={busy} onChange={(e) => edit({ op: "overlay_set", overlay_id: o.id, field: "motion", value: e.target.value })}>
                <option value="zoom">Slow push in</option><option value="still">Still</option></select>
              <TimeField label="Shown for (s)" ms={o.length_ms} disabled={busy} onCommit={(ms) => edit({ op: "overlay_set", overlay_id: o.id, field: "length_ms", value: ms })} />
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "overlay_remove", overlay_id: o.id })}><Icon name="trash" />Remove</button>
            </div>
          </li>
        );
      })}</ul> : <p className="small muted">Show an image over a clip while its sound goes on, instead of between clips.</p>}
      {images.length > 0 && clips.length > 0 && <div className="row-actions wrap" role="group" aria-label="Show a picture over the video">
        <select value={add.asset} aria-label="Picture to show" onChange={(e) => setAdd({ ...add, asset: e.target.value })}>
          <option value="">Show a picture…</option>{images.map((a) => <option key={a!.id} value={a!.id}>{a!.filename}</option>)}</select>
        <select value={add.clip} aria-label="Over which clip" onChange={(e) => setAdd({ ...add, clip: e.target.value })}>
          <option value="">Over clip…</option>{clips.map((c) => <option key={c.id} value={c.id}>Clip {plan.clips.indexOf(c) + 1} ({c.label}, {((c.out_ms - c.in_ms) / 1000).toFixed(1)} s)</option>)}</select>
        <button type="button" className="btn btn-small" disabled={busy || !add.asset || !add.clip}
          onClick={() => edit({ op: "overlay_add", asset_id: add.asset, clip_id: add.clip, offset_ms: 0, length_ms: 3500 })}><Icon name="plus" />Show</button>
      </div>}
    </section>
  );
}

/** The full-video editor: preview, timeline, sequence, media, audio tracks, look and sound, versions. Every change is
 * saved at once as a new version; undo, redo and going back are new versions too, so nothing is ever overwritten. */
export default function VideoReview({ id }: { id: string }) {
  const [v, setV] = useState<Video | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState("");
  const [shown, setShown] = useState(PAGE);
  const [insert, setInsert] = useState({ asset: "", at: -1 });
  const [place, setPlace] = useState<{ asset: string; role: AudioRole; at: string }>({ asset: "", role: "effect", at: "" });
  const [naming, setNaming] = useState<{ rev: number; name: string } | null>(null);
  const sent = useRef(new Set<string>());

  const load = useCallback(() => studio.video(id).then(setV).catch((e) => setProblem(errorText(e))), [id]);
  useEffect(() => {
    void load();
    const t = window.setInterval(load, 2500);
    return () => window.clearInterval(t);
  }, [load]);

  const act = useCallback(async (call: () => Promise<Video & { note?: string }>) => {
    setBusy(true);
    try {
      const r = await call();
      setV(r);
      if (r.note) toast(r.note);
    } catch (e) {
      toast(errorText(e), true);  // the earlier version stays as it was
    }
    setBusy(false);
  }, []);
  const revision = v?.plan_revision ?? 0;
  const edit: EditFn = useCallback((change) => act(() => studio.editVideo(id, revision, change)), [act, id, revision]);
  const canUndo = !!v?.can_undo;
  const canRedo = !!v?.can_redo;
  const undo = useCallback(async () => { if (canUndo) await act(() => studio.undoVideo(id, revision)); }, [act, id, revision, canUndo]);
  const redo = useCallback(async () => { if (canRedo) await act(() => studio.redoVideo(id, revision)); }, [act, id, revision, canRedo]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (busy || !(e.ctrlKey || e.metaKey) || t.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); void undo(); }
      else if ((e.key.toLowerCase() === "z" && e.shiftKey) || e.key.toLowerCase() === "y") { e.preventDefault(); void redo(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [busy, undo, redo]);

  const media = useMemo(() => Object.fromEntries((v?.assets || []).map((a) => [a.id, a])), [v?.assets]);
  if (!v) return problem ? <Banner tone="bad" title="This video cannot be opened">{problem}</Banner> : <LoadingPage label="Loading video" />;

  const plan = v.plan;
  const working = v.jobs.find((j) => j.status === "running" || j.status === "queued");
  const preview = v.preview ? v.artifacts.find((a) => a.kind === "preview" && a.revision === v.preview!.revision) : undefined;
  const finals = v.artifacts.filter((a) => a.kind === "final");
  const failed = v.jobs.find((j) => j.status === "failed" && j.revision >= v.plan_revision);
  const vertical = plan?.output.aspect === "9:16" || plan?.output.aspect === "4:5";
  const bin = v.bin.map((aid) => media[aid]).filter(Boolean);
  const pictures = bin.filter((a) => a.kind !== "audio");
  const sounds = bin.filter((a) => a.kind === "audio");
  const tracks = v.capabilities?.tracks || { source: "Sound from your videos", voiceover: "Voiceover", music: "Music", effects: "Sound effects" };
  const addFiles = (rows: Picked[]) => {
    const fresh = rows.filter((r) => r.asset && !sent.current.has(r.asset.id)).map((r) => r.asset!.id);
    if (!fresh.length) return;
    fresh.forEach((a) => sent.current.add(a));
    void act(() => studio.addVideoMedia(v.id, fresh).then((r) => ({ ...r, note: `Added ${r.added.length} file${r.added.length === 1 ? "" : "s"} to your media` })));
  };

  return (
    <div className="page">
      <PageHead kind="Full video" title={v.name} crumbs={[{ label: "Projects", href: "#/projects" }, { label: v.name }]}
        sub={plan ? <span aria-live="polite">{busy ? "Saving…" : `Saved · version ${v.plan_revision}`} · {fmtTime(v.duration)} · {plan.output.aspect} · {plan.output.fps} fps</span> : v.message}
        actions={plan && <>
          <button type="button" className="btn" disabled={busy || !v.can_undo} onClick={() => void undo()} title="Undo (Ctrl+Z)"><Icon name="back" />Undo</button>
          <button type="button" className="btn" disabled={busy || !v.can_redo} onClick={() => void redo()} title="Redo (Ctrl+Shift+Z)"><Icon name="back" className="flip-x" />Redo</button>
          <button type="button" className="btn btn-primary" disabled={busy || !!working && working.kind === "video_render"}
            onClick={async () => { try { setV(await studio.renderVideo(v.id, v.plan_revision)); toast("Render queued. Keep ClipForge running until it finishes."); } catch (e) { toast(errorText(e), true); } }}>
            <Icon name="play" />Render version {v.plan_revision}</button>
          {working && <button type="button" className="btn" onClick={async () => setV(await studio.cancelVideo(v.id))}><Icon name="stop" />Cancel</button>}
        </>} />
      {failed && <Banner tone="bad" title="That did not finish">{failed.error}</Banner>}
      <MediaBanner v={v} />
      {working && <div className="panel"><b>{working.message || "Waiting for a worker"}{working.kind === "video_render" ? ` (version ${working.revision}; later edits do not change it)` : ""}</b><ProgressBar value={working.progress} label="Progress" /></div>}
      <LayoutFlow screen="review" sections={{
        preview: (
          <section className="panel" aria-labelledby="vr-preview">
            <div className="panel-head"><h2 id="vr-preview">Preview</h2>
              {v.preview?.stale && <span className="pill warn">Older: shows version {v.preview.revision}; version {v.plan_revision} is being prepared</span>}</div>
            {preview ? <video key={preview.id} className={`preview-video ${vertical ? "vertical" : ""}`} controls preload="metadata"
              src={`/api/studio/videos/${v.id}/media?kind=preview&revision=${preview.revision}`} />
              : <p className="muted">The preview appears here when the rough cut is ready.</p>}
            {plan && <Timeline v={v} selected={selected} onSelect={(cid) => { setSelected(cid); document.getElementById(`clip-${cid}`)?.scrollIntoView({ block: "nearest" }); }} />}
            <p className="small muted">The preview is a small, fast copy of the same plan. The final render uses your full original files.</p>
          </section>),
        outputs: plan && (
          <div className="stack-5">
            <SmartPanel key={v.plan_revision} v={v} plan={plan} busy={busy} onStarted={() => void load()} />
            <section className="panel" aria-labelledby="vr-seq">
              <div className="panel-head"><h2 id="vr-seq">Sequence ({plan.clips.length})</h2>
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "shorten_intro", seconds: 5 })}>Shorten the introduction</button></div>
              <ol className="seq edit-seq">
                {plan.clips.slice(0, shown).map((c, i) => {
                  const o = plan.outline.find((x) => x.clip_id === c.id);
                  return (
                    <li key={c.id} id={`clip-${c.id}`} className={`${c.include ? "" : "off"} ${selected === c.id ? "on" : ""}`}>
                      <span className="idx">{i + 1}</span>
                      <div className="break">
                        <b className="clamp-1">{c.label}</b>
                        <span className="block small muted">{fmtEdit(c.in_ms)}–{fmtEdit(c.out_ms)} · {((c.out_ms - c.in_ms) / 1000).toFixed(1)} s{c.mute ? " · muted" : ""}{o?.summary ? ` · “${o.summary}”` : ""}</span>
                        {c.must_keep?.length ? <span className="block small">Keeps: {c.must_keep.join(", ")}</span> : null}
                      </div>
                      <div className="row-actions">
                        <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${c.label} earlier`} disabled={busy || i === 0} onClick={() => edit({ op: "move", clip_id: c.id, to: i - 1 })}><Icon name="chev" className="rot-up" /></button>
                        <button type="button" className="btn btn-small btn-icon" aria-label={`Move ${c.label} later`} disabled={busy || i === plan.clips.length - 1} onClick={() => edit({ op: "move", clip_id: c.id, to: i + 1 })}><Icon name="chev" /></button>
                        {c.include ? <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "remove", clip_id: c.id })}>Remove</button>
                          : <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "include", clip_id: c.id })}>Put back</button>}
                        <button type="button" className="btn btn-small" aria-expanded={selected === c.id} onClick={() => setSelected(selected === c.id ? "" : c.id)}>{selected === c.id ? "Close" : "Edit"}</button>
                      </div>
                      {selected === c.id && <ClipInspector c={c} plan={plan} v={v} edit={edit} busy={busy} />}
                    </li>
                  );
                })}
              </ol>
              {plan.clips.length > shown && <button type="button" className="btn btn-small" onClick={() => setShown((n) => n + PAGE)}>Show {Math.min(PAGE, plan.clips.length - shown)} more of {plan.clips.length}</button>}
              {pictures.length > 0 && <div className="row-actions wrap" role="group" aria-label="Insert a file">
                <select value={insert.asset} aria-label="File to insert" onChange={(e) => setInsert({ ...insert, asset: e.target.value })}>
                  <option value="">Insert a video or image…</option>{pictures.map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}</select>
                <select value={insert.at} aria-label="Where to insert it" onChange={(e) => setInsert({ ...insert, at: Number(e.target.value) })}>
                  <option value={-1}>At the end</option><option value={0}>At the start</option>
                  {plan.clips.slice(0, -1).map((c, i) => <option key={c.id} value={i + 1}>After clip {i + 1} ({c.label})</option>)}</select>
                <button type="button" className="btn btn-small" disabled={busy || !insert.asset} onClick={() => edit({ op: "insert", asset_id: insert.asset, at: insert.at < 0 ? plan.clips.length : insert.at })}><Icon name="plus" />Insert</button>
              </div>}
              <ClipForgeAI projectId={v.id} v={v} busy={busy} onApplied={() => void load()} />
              {plan.notes.length > 0 && <ul className="small">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            </section>
            <Pictures v={v} plan={plan} edit={edit} busy={busy} />
            <section className="panel" aria-labelledby="vr-audio">
              <h2 id="vr-audio">Sound</h2>
              <div className="track-grid">
                {(Object.keys(tracks) as TrackName[]).map((t) => (
                  <div key={t} className="track-ctl">
                    <Gain label={tracks[t]} value={plan.tracks?.[t]?.gain_db ?? 0} min={-36} max={12} disabled={busy} onCommit={(x) => edit({ op: "track_set", track: t, field: "gain_db", value: x })} />
                    <label><input type="checkbox" checked={!!plan.tracks?.[t]?.mute} disabled={busy} onChange={(e) => edit({ op: "track_set", track: t, field: "mute", value: e.target.checked })} /> Mute</label>
                  </div>))}
              </div>
              <label className="field"><span>Clean up the sound from your videos</span>
                <select value={plan.clean_sound ?? ""} disabled={busy} onChange={(e) => e.target.value && edit({ op: "set", field: "clean_sound", value: e.target.value })}>
                  {!plan.clean_sound && <option value="">As in Settings</option>}
                  <option value="off">Off</option><option value="auto">Auto (leaves music alone)</option>
                  <option value="gentle">Gentle</option><option value="strong">Strong</option></select>
                <span className="small muted">Background noise, hum, breaths, uneven levels and voice polish. The preview plays the result; choose Off to hear the original.</span></label>
              {(["voiceover", "music", "effect"] as AudioRole[]).map((role) => {
                const items = plan.audio.filter((i) => i.role === role);
                return items.length > 0 && (
                  <div key={role} className="stack-3"><h3 className="label">{tracks[ROLE_TRACK[role]]}</h3>
                    <ul className="seq audio-list">{items.map((i) => <AudioRow key={i.id} item={i} v={v} edit={edit} busy={busy} />)}</ul></div>
                );
              })}
              {sounds.length > 0 ? <div className="row-actions wrap" role="group" aria-label="Add a sound to a track">
                <select value={place.asset} aria-label="Sound to add" onChange={(e) => setPlace({ ...place, asset: e.target.value })}>
                  <option value="">Add a sound…</option>{sounds.map((a) => <option key={a.id} value={a.id}>{a.filename}</option>)}</select>
                <select value={place.role} aria-label="Track" onChange={(e) => setPlace({ ...place, role: e.target.value as AudioRole })}>
                  {(Object.keys(ROLE_WORDS) as AudioRole[]).map((r) => <option key={r} value={r}>{ROLE_WORDS[r]}</option>)}</select>
                <select value={place.at} aria-label="Where it starts" onChange={(e) => setPlace({ ...place, at: e.target.value })}>
                  <option value="">At the start of the video</option>
                  {plan.clips.filter((c) => c.include).map((c, i) => <option key={c.id} value={c.id}>With clip {i + 1} ({c.label}), moving with it</option>)}</select>
                <button type="button" className="btn btn-small" disabled={busy || !place.asset}
                  onClick={() => edit({ op: "add_audio", asset_id: place.asset, role: place.role, ...(place.at ? { clip_id: place.at } : { start_ms: 0 }) })}><Icon name="plus" />Add</button>
              </div> : <p className="small muted">Add voiceovers, music or sound effects under Your media, then place them here.</p>}
              {plan.audio.some((i) => i.duck) && <Gain label="Music and effects dip under speech by" value={-(plan.ducking?.depth_db ?? 12)} min={-30} max={0} disabled={busy}
                onCommit={(x) => edit({ op: "set", field: "duck_depth_db", value: -x })} />}
            </section>
            <section className="panel" aria-labelledby="vr-media">
              <h2 id="vr-media">Your media ({bin.length})</h2>
              <FileDrop accept="video/*,image/png,image/jpeg,image/webp,audio/*,.mkv,.m4v,.flac,.opus,.ogg" multiple label="Add more videos, images or sounds" onAssets={addFiles} />
              <p className="small muted">New files wait here until you insert them or add them to a track. Nothing is cut or deleted from your originals.</p>
              <Disclosure summary={`Files in this project (${bin.length})`}>
                <ul className="file-list">{bin.map((a) => (
                  <li key={a.id} className="file-row">
                    {a.has_thumbnail ? <img className="thumb-mini" src={`/api/assets/${a.id}/thumbnail`} alt="" /> : <span className="thumb-mini" aria-hidden="true" />}
                    <div className="break"><b className="clamp-1">{a.filename}</b><span className="block small muted">{a.kind === "audio" ? "Sound" : a.kind === "image" ? "Image" : "Video"}{a.duration ? ` · ${fmtTime(a.duration)}` : ""}</span><SourceLine v={v} assetId={a.id} /></div>
                  </li>))}</ul>
              </Disclosure>
            </section>
            <FindMedia v={v} onChanged={() => void load()} />
          </div>),
        guidance: <section className="panel" aria-labelledby="vr-brain"><h2 id="vr-brain">Used from your Brain</h2><UsedFromBrain snapshot={v.guidance} compact /></section>,
        transcript: (<div className="stack-5">{plan && (
            <section className="panel" aria-labelledby="vr-look"><h2 id="vr-look">Look</h2>
              <label><input type="checkbox" checked={plan.captions.enabled} disabled={busy} onChange={(e) => edit({ op: "set", field: "captions", value: e.target.checked })} /> Captions</label>
              {plan.captions.enabled && <div className="grid-2">
                <label className="field"><span>Caption size</span><select value={plan.captions.size || "medium"} disabled={busy} onChange={(e) => edit({ op: "set", field: "caption_size", value: e.target.value })}>
                  <option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></select></label>
                <label className="field"><span>Caption position</span><select value={plan.captions.position} disabled={busy} onChange={(e) => edit({ op: "set", field: "caption_position", value: e.target.value })}>
                  {POSITIONS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
              </div>}
              <label className="field"><span>Joins between clips</span>
                <select value={plan.transition.type} disabled={busy} onChange={(e) => edit({ op: "set", field: "transition", value: e.target.value })}>
                  <option value="cut">Straight cuts</option><option value="dissolve">Dissolves</option><option value="fade">Fade through black</option>
                </select></label>
              <div className="grid-2">
                <label className="field"><span>Framing</span><select value={plan.layout} disabled={busy} onChange={(e) => edit({ op: "set", field: "layout", value: e.target.value })}>
                  <option value="fit">Fit (blurred background)</option><option value="fill">Fill the frame</option></select></label>
                <label className="field"><span>Frame rate</span><select value={plan.output.fps} disabled={busy} onChange={(e) => edit({ op: "set", field: "fps", value: Number(e.target.value) })}>
                  {(v.capabilities?.fps || [24, 25, 30, 50, 60]).map((f) => <option key={f} value={f}>{f} fps</option>)}</select></label>
              </div>
              <label><input type="checkbox" checked={plan.title.enabled} disabled={busy} onChange={(e) => edit({ op: "set", field: "title_card", value: e.target.checked })} /> Opening title “{plan.title.text}”</label>
            </section>
          )}
          <section className="panel" aria-labelledby="vr-versions"><h2 id="vr-versions">Versions</h2>
            {finals.length > 0 && <ul className="file-list">{finals.map((a) => (
              <li key={a.id} className="file-row"><Icon name="check" /><div><b>Version {a.revision}</b><span className="block small muted">{fmtTime(a.duration)} · checked{a.audio_ok ? ", audio timing valid" : ""}{a.engine === "filmcraft" ? " · made in FilmCraft" : ""}</span>{a.fallback && <span className="block"><MadeWithLine m={a} /></span>}</div>
                <a className="btn btn-small" href={`/api/studio/videos/${v.id}/media?kind=final&revision=${a.revision}&download=1`}><Icon name="download" />Download</a></li>
            ))}</ul>}
            <ul className="small version-list">{v.revisions.slice(0, 12).map((r) => (
              <li key={r.revision}>
                {naming?.rev === r.revision ? <form className="row-actions" onSubmit={async (e) => { e.preventDefault(); await act(() => studio.nameRevision(v.id, r.revision, naming.name)); setNaming(null); }}>
                  <input value={naming.name} maxLength={60} aria-label={`Name for version ${r.revision}`} autoFocus onChange={(e) => setNaming({ rev: r.revision, name: e.target.value })} />
                  <button type="submit" className="btn btn-small">Save</button><button type="button" className="btn btn-small" onClick={() => setNaming(null)}>Cancel</button></form>
                  : <>{r.revision}. {r.name ? <b>{r.name} · </b> : null}{r.note}
                    {" "}<button type="button" className="link-btn" onClick={() => setNaming({ rev: r.revision, name: r.name })}>{r.name ? "Rename" : "Name"}</button>
                    {r.revision !== v.plan_revision && <> · <button type="button" className="link-btn" disabled={busy} onClick={() => act(() => studio.restoreVideo(v.id, r.revision))}>Go back to this</button></>}</>}
              </li>
            ))}</ul>
            <a className="small" href={`/api/studio/videos/${v.id}/export`}>Download the edit plan (JSON)</a>
          </section>
          <FilmCraftPanel v={v} onSaved={setV} />
          <Credits v={v} onSaved={setV} /></div>),
      }} />
    </div>
  );
}
