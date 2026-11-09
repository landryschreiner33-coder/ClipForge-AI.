import { useEffect, useRef, useState } from "react";
import { errorText } from "../api";
import { PlanFields, SmartLevel, studio, Tri, Video } from "../studio";
import { Icon, toast } from "./ui";
import "../videoSetup.css";

/** The plan of a YouTube video made with ClipForge AI (docs/clipforge/VIDEO_SETUP.md): read as a slate, changed by hand. */
type FileLike = { id: string; kind: string; filename: string };
export type PlanRow = { key: keyof PlanFields; label: string; value: string; list?: string[] };

const SHAPES: Record<string, string> = { "16:9": "16:9 widescreen", "9:16": "9:16 vertical", "1:1": "1:1 square", "4:5": "4:5 portrait" };
const FEELS: Record<string, string> = { calm: "Calm", balanced: "Balanced", energetic: "Energetic" };
const EDITS: Record<SmartLevel, string> = { smart: "Edit it for me", tight: "Fast-paced", off: "Keep my clips as they are" };
const MUSIC: Record<string, string> = { auto: "Pick for me", library: "Free music made by ClipForge", find: "Find music for me", none: "No music" };
const TRI_WORDS: Record<string, string> = { on: "On", off: "Off" };

export function minutes(m: number): string {
  if (m < 1) return `${Math.round(m * 60)} seconds`;
  const v = Math.round(m * 100) / 100;
  return v === 1 ? "1 minute" : `${v} minutes`;
}

/** The decided parts of a plan in plain words, in the order a person reads a video plan (nothing for what is left
 * to your style). */
export function planRows(p: PlanFields, files: FileLike[]): PlanRow[] {
  const name = (id: string) => files.find((f) => f.id === id)?.filename || "a file";
  const rows: PlanRow[] = [];
  const add = (key: keyof PlanFields, label: string, value: string, list?: string[]) => {
    if (value || (list && list.length)) rows.push({ key, label, value, list });
  };
  add("summary", "What it is", p.summary);
  add("video_type", "Kind", p.video_type);
  add("audience", "For", p.audience);
  add("goal", "Goal", p.goal);
  add("length_min", "Length", p.length_min ? `About ${minutes(p.length_min)}` : "");
  add("aspect_ratio", "Shape", p.aspect_ratio ? SHAPES[p.aspect_ratio] : "");
  add("feel", "Feel", p.feel ? FEELS[p.feel] : "");
  add("edit", "Editing", EDITS[p.edit] || EDITS.smart);
  add("opening", "Opens with", p.opening || (p.cold_open === "on" ? "Its strongest line" : p.cold_open === "off" ? "The beginning" : ""));
  add("story", "Story", "", p.story);
  add("keep", "Keep", p.keep.join(", "));
  add("cut", "Cut", p.cut.join(", "));
  add("music", "Music", p.music === "mine" ? (p.music_file ? `Your ${name(p.music_file)}` : "") : p.music ? MUSIC[p.music] : "");
  add("voiceover_files", "Voiceover", p.voiceover_files.map(name).join(", "));
  add("captions", "Captions", TRI_WORDS[p.captions] || "");
  add("pictures", "Your pictures over the video", TRI_WORDS[p.pictures] || "");
  add("sound_effects", "Sound effects", TRI_WORDS[p.sound_effects] || "");
  add("zooms", "Zooms", TRI_WORDS[p.zooms] || "");
  add("order", "Order", "", p.order.map(name));
  add("find_media", "Supporting media", p.find_media === "suggest" ? "Suggest pictures for my review"
    : p.find_media === "auto" ? "Add eligible pictures as a version I can undo" : "");
  add("notes", "Also", "", p.notes);
  return rows;
}

/** The plan's fields that changed since the plan before (shown for a moment, so you see what your words did). */
export function useChanged(plan: PlanFields | null | undefined): Set<string> {
  const before = useRef<PlanFields | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  // By what it says, not by the object: the page polls while ClipForge AI listens, and the same plan read again must
  // not cancel the moment the highlight goes out.
  const said = plan ? JSON.stringify(plan) : "";
  useEffect(() => {
    if (!plan) return;
    const prev = before.current;
    before.current = plan;
    if (!prev) return;
    const keys = (Object.keys(plan) as (keyof PlanFields)[]).filter((k) => JSON.stringify(plan[k]) !== JSON.stringify(prev[k]));
    if (!keys.length) return;
    setChanged(new Set(keys.map((k) => (k === "music_file" ? "music" : k === "cold_open" ? "opening" : k))));
    const t = window.setTimeout(() => setChanged(new Set()), 2600);
    return () => window.clearTimeout(t);
  }, [said]);  // eslint-disable-line react-hooks/exhaustive-deps -- `plan` is what `said` says
  return changed;
}

/** The plan read as a slate: the video's name on top, then each decided part. */
export function PlanSheet({ name, plan, files, changed, empty }: {
  name: string; plan: PlanFields; files: FileLike[]; changed?: Set<string>; empty?: string;
}) {
  const rows = planRows(plan, files);
  return (
    <div className="vs-slate">
      <p className={`vs-slate-name${changed?.has("title") ? " is-new" : ""}`}>{plan.title || name}</p>
      {rows.length > 1 || plan.edit !== "smart" ? (
        <dl className="vs-plan">
          {rows.map((r) => (
            <div key={r.key} className={changed?.has(r.key) ? "is-new" : undefined}>
              <dt>{r.label}</dt>
              <dd>{r.list ? (r.key === "story" || r.key === "order"
                ? <ol>{r.list.map((x, i) => <li key={i}>{x}</li>)}</ol>
                : <ul>{r.list.map((x, i) => <li key={i}>{x}</li>)}</ul>) : r.value}</dd>
            </div>
          ))}
        </dl>
      ) : <p className="muted small">{empty || "Nothing decided yet: tell ClipForge AI your idea."}</p>}
    </div>
  );
}

const lines = (text: string, count: number) => text.split("\n").map((x) => x.trim()).filter(Boolean).slice(0, count);
const items = (text: string, count: number) => text.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean).slice(0, count);

/** The plan as a form: every part can be set by hand ("From your style" leaves it to your style and Brain). Only what
 * you changed is saved, and stays as you set it until you talk about it again. */
export function PlanForm({ plan, files, busy, saveLabel, onSave, onCancel, hide = [] }: {
  plan: PlanFields; files: FileLike[]; busy?: boolean; saveLabel: string; hide?: (keyof PlanFields)[];
  onSave: (changes: Partial<PlanFields>) => void | Promise<void>; onCancel: () => void;
}) {
  const [p, setP] = useState<PlanFields>(plan);
  const [story, setStory] = useState(plan.story.join("\n"));
  const [notes, setNotes] = useState(plan.notes.join("\n"));
  const [keep, setKeep] = useState(plan.keep.join(", "));
  const [cut, setCut] = useState(plan.cut.join(", "));
  const [length, setLength] = useState(plan.length_min ? String(plan.length_min) : "");
  const set = <K extends keyof PlanFields>(k: K, v: PlanFields[K]) => setP((x) => ({ ...x, [k]: v }));
  const sounds = files.filter((f) => f.kind === "audio");
  const voices = sounds.filter((f) => !(p.music === "mine" && f.id === p.music_file));
  const shown = (k: keyof PlanFields) => !hide.includes(k);
  const save = () => {
    const minutesSet = parseFloat(length.replace(",", "."));
    const next: PlanFields = { ...p, story: lines(story, 8), notes: lines(notes, 6), keep: items(keep, 12), cut: items(cut, 12),
      length_min: Number.isFinite(minutesSet) && minutesSet > 0 ? minutesSet : 0 };
    const changes = Object.fromEntries((Object.keys(next) as (keyof PlanFields)[])
      .filter((k) => JSON.stringify(next[k]) !== JSON.stringify(plan[k])).map((k) => [k, next[k]])) as Partial<PlanFields>;
    void onSave(changes);
  };
  const tri = (k: "captions" | "pictures" | "sound_effects" | "zooms", label: string) => (
    <label className="field"><span>{label}</span>
      <select value={p[k]} onChange={(e) => set(k, e.target.value as Tri)}>
        <option value="">From your style</option><option value="on">On</option><option value="off">Off</option></select></label>);
  return (
    <form className="stack-3 vs-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
      {shown("title") && <label className="field"><span>Name</span><input value={p.title} maxLength={120} onChange={(e) => set("title", e.target.value)} /></label>}
      <label className="field"><span>What it is</span><textarea rows={2} value={p.summary} maxLength={300} onChange={(e) => set("summary", e.target.value)} /></label>
      <div className="vs-pair">
        <label className="field"><span>Kind of video</span><input value={p.video_type} maxLength={80} placeholder="For example: travel vlog" onChange={(e) => set("video_type", e.target.value)} /></label>
        <label className="field"><span>Who it's for</span><input value={p.audience} maxLength={120} placeholder="For example: friends and family" onChange={(e) => set("audience", e.target.value)} /></label>
      </div>
      <label className="field"><span>Goal</span><input value={p.goal} maxLength={200} onChange={(e) => set("goal", e.target.value)} /></label>
      <div className="vs-pair">
        <label className="field"><span>Length in minutes</span><input inputMode="decimal" value={length} placeholder="As long as it needs" onChange={(e) => setLength(e.target.value)} /></label>
        <label className="field"><span>Shape</span><select value={p.aspect_ratio} onChange={(e) => set("aspect_ratio", e.target.value as PlanFields["aspect_ratio"])}>
          <option value="">From your style</option>{Object.entries(SHAPES).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        <label className="field"><span>Feel</span><select value={p.feel} onChange={(e) => set("feel", e.target.value as PlanFields["feel"])}>
          <option value="">From your style</option>{Object.entries(FEELS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        <label className="field"><span>Editing</span><select value={p.edit} onChange={(e) => set("edit", e.target.value as SmartLevel)}>
          {Object.entries(EDITS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
      </div>
      <div className="vs-pair">
        <label className="field"><span>Opens with</span><input value={p.opening} maxLength={200} placeholder="A moment or a line, in the words said in it" onChange={(e) => set("opening", e.target.value)} /></label>
        <label className="field"><span>How it starts</span><select value={p.cold_open} onChange={(e) => set("cold_open", e.target.value as Tri)}>
          <option value="">From your style</option><option value="on">With its strongest line, then from the start</option><option value="off">At the beginning</option></select></label>
      </div>
      <label className="field"><span>Story, one part per line, in order</span><textarea rows={4} value={story} onChange={(e) => setStory(e.target.value)} placeholder={"The drive up\nSwimming\nSunset"} /></label>
      <div className="vs-pair">
        <label className="field"><span>Keep (words or topics, comma separated)</span><input value={keep} onChange={(e) => setKeep(e.target.value)} /></label>
        <label className="field"><span>Cut (words or topics, comma separated)</span><input value={cut} onChange={(e) => setCut(e.target.value)} /></label>
      </div>
      <div className="vs-pair">
        <label className="field"><span>Music</span><select value={p.music} onChange={(e) => set("music", e.target.value as PlanFields["music"])}>
          <option value="">From your style</option><option value="auto">Pick for me</option><option value="library">Free music made by ClipForge</option>
          {sounds.length > 0 && <option value="mine">One of my sound files</option>}
          <option value="find">Find music for me</option><option value="none">No music</option></select></label>
        {p.music === "mine" && <label className="field"><span>Which file is the music</span><select value={p.music_file} onChange={(e) => set("music_file", e.target.value)}>
          <option value="">Choose for me</option>{sounds.map((f) => <option key={f.id} value={f.id}>{f.filename}</option>)}</select></label>}
      </div>
      {voices.length > 0 && <fieldset className="stack-2"><legend className="label">Voiceover</legend>
        {voices.map((f) => (
          <label key={f.id}><input type="checkbox" checked={p.voiceover_files.includes(f.id)}
            onChange={(e) => set("voiceover_files", e.target.checked ? [...p.voiceover_files, f.id] : p.voiceover_files.filter((x) => x !== f.id))} /> {f.filename}</label>))}
      </fieldset>}
      <div className="vs-pair">
        {tri("captions", "Captions")}
        {tri("pictures", "Your pictures over the video")}
        {tri("sound_effects", "Sound effects")}
        {tri("zooms", "Zooms")}
      </div>
      <label className="field"><span>Supporting media</span><select value={p.find_media} onChange={(e) => set("find_media", e.target.value as PlanFields["find_media"])}>
        <option value="">Don't look for pictures or music</option><option value="suggest">Suggest pictures for my review</option>
        <option value="auto">Add eligible pictures as a version I can undo</option></select></label>
      <label className="field"><span>Also keep in mind, one per line</span><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <div className="row wrap">
        <button type="submit" className="btn btn-primary" disabled={busy}><Icon name="check" />{saveLabel}</button>
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

/** The plan a video was made with, on its editor page: read it, or change it and edit the video again (a new
 * version that Undo takes back). */
export function PlanPanel({ v, onStarted }: { v: Video; onStarted: () => void }) {
  const setup = v.setup!;
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const changed = useChanged(setup.plan);
  const running = v.jobs.some((j) => j.kind === "video_smart" && (j.status === "running" || j.status === "queued"));
  const files = v.bin.map((id) => v.assets.find((a) => a.id === id)).filter((a): a is NonNullable<typeof a> => !!a)
    .map((a) => ({ id: a.id, kind: a.kind, filename: a.filename }));
  const save = async (changes: Partial<PlanFields>) => {
    if (!Object.keys(changes).length) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await studio.changePlan(v.id, v.plan_revision, changes);
      toast("Editing your video again with the new plan. It becomes a new version that Undo takes back.");
      setEditing(false);
      onStarted();
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };
  return (
    <section className="panel" aria-labelledby="vr-plan">
      <div className="panel-head"><h2 id="vr-plan">Your plan</h2>
        <span className="small muted">{setup.source === "ai" ? "Planned with ClipForge AI" : "Read by the built-in rules"}</span></div>
      {setup.pending && <p className="small muted">ClipForge AI plans once it has listened to your files; the plan below fills in then.</p>}
      {editing
        ? <PlanForm plan={setup.plan} files={files} busy={busy} saveLabel="Edit it again with this plan" onSave={save} onCancel={() => setEditing(false)} />
        : <PlanSheet name={v.name} plan={setup.plan} files={files} changed={changed} />}
      {!editing && v.plan && (
        <div className="vs-plan-actions">
          <button type="button" className="btn" disabled={running || busy} onClick={() => setEditing(true)}><Icon name="edit" />Change the plan</button>
          {running && <span className="small muted">Editing with your plan…</span>}
        </div>
      )}
      {!editing && v.plan && <p className="small muted">A changed plan edits the video again as a new version. Undo takes it back.</p>}
    </section>
  );
}
