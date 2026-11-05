import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { errorText } from "../api";
import { LayoutFlow } from "../components/AppearanceSettings";
import { FileDrop, Picked, UsedFromBrain } from "../components/studioParts";
import { Banner, Disclosure, Icon, LoadingPage, PageHead, ProgressBar, toast } from "../components/ui";
import { AudioItem, AudioRole, fmtEdit, fmtTime, Plan, PlanClip, studio, TrackName, Video } from "../studio";

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

/** The full-video editor: preview, timeline, sequence, media, audio tracks, look and sound, versions. Every change is
 * saved at once as a new version; undo, redo and going back are new versions too, so nothing is ever overwritten. */
export default function VideoReview({ id }: { id: string }) {
  const [v, setV] = useState<Video | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [request, setRequest] = useState("");
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
              <form className="robot-name-form" onSubmit={(e) => { e.preventDefault(); if (request.trim()) void edit({ op: "request", text: request }); }}>
                <label className="field grow"><span>Ask for a change</span><input value={request} onChange={(e) => setRequest(e.target.value)} placeholder="For example: shorten the intro by 3 seconds" /></label>
                <button type="submit" className="btn" disabled={busy || !request.trim()}>Apply</button>
              </form>
              {plan.notes.length > 0 && <ul className="small">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            </section>
            <section className="panel" aria-labelledby="vr-audio">
              <h2 id="vr-audio">Sound</h2>
              <div className="track-grid">
                {(Object.keys(tracks) as TrackName[]).map((t) => (
                  <div key={t} className="track-ctl">
                    <Gain label={tracks[t]} value={plan.tracks?.[t]?.gain_db ?? 0} min={-36} max={12} disabled={busy} onCommit={(x) => edit({ op: "track_set", track: t, field: "gain_db", value: x })} />
                    <label><input type="checkbox" checked={!!plan.tracks?.[t]?.mute} disabled={busy} onChange={(e) => edit({ op: "track_set", track: t, field: "mute", value: e.target.checked })} /> Mute</label>
                  </div>))}
              </div>
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
                    <div className="break"><b className="clamp-1">{a.filename}</b><span className="block small muted">{a.kind === "audio" ? "Sound" : a.kind === "image" ? "Image" : "Video"}{a.duration ? ` · ${fmtTime(a.duration)}` : ""}</span></div>
                  </li>))}</ul>
              </Disclosure>
            </section>
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
              <li key={a.id} className="file-row"><Icon name="check" /><div><b>Version {a.revision}</b><span className="block small muted">{fmtTime(a.duration)} · checked{a.audio_ok ? ", audio timing valid" : ""}</span></div>
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
          </section></div>),
      }} />
    </div>
  );
}
