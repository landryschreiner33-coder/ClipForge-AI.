import { useEffect, useState } from "react";
import { Icon } from "./ui";
import { Camera, CameraGroup, CameraShot, CameraSwitching, CornerPlace, fmtEdit, PlanClip, Video } from "../studio";

/* Several cameras of one recording (engine multicam, docs/clipforge/MULTICAM.md): line them up by their sound,
 * switch automatically or by hand, one camera small in a corner. The sound always comes from the recording itself. */

type EditFn = (change: Record<string, unknown>) => Promise<void>;

export const SHOTS: Record<CameraShot, string> = { wide: "Wide shot", close: "One person", other: "Screen or other" };
export const CORNERS: Record<CornerPlace, string> = { top_left: "Top left", top_right: "Top right",
  bottom_left: "Bottom left", bottom_right: "Bottom right" };
const SWITCHING: Record<CameraSwitching, string> = { speaker: "To whoever is speaking", angles: "Another angle at pauses",
  hand: "By hand (your choices)", off: "Off: this camera only" };
const SIZES: [string, string][] = [["", "Usual size"], ["0.2", "Small (20%)"], ["0.3", "Medium (30%)"], ["0.4", "Large (40%)"]];

/** A camera's colour on the timeline: its place in the recording's camera list. */
function camClass(g: CameraGroup | undefined, cam: string): string {
  const k = g ? g.cams.findIndex((c) => c.id === cam) : 0;
  return `cam-${Math.max(0, k) % 6}`;
}

function lineUp(c: Camera, fps: number): string {
  if (c.id === "main") return "the recording itself (its sound is the video's sound)";
  const s = ((c.offset_ms || 0) / 1000).toFixed(2);
  const sure = c.match == null ? "lined up by hand" : `sound match ${Math.round(c.match * 100)}%`;
  const drift = Math.abs(c.drift_ppm) > 0 ? `, runs ${Math.abs(c.drift_ppm).toFixed(0)} ppm ${c.drift_ppm > 0 ? "fast" : "slow"}` : "";
  return `${(c.offset_ms || 0) >= 0 ? "+" : ""}${s} s (${sure}${drift}) · 1 frame = ${(1000 / fps).toFixed(0)} ms`;
}

/** A camera's name, saved when you leave the field. */
function CameraName({ c, of, edit, busy }: { c: Camera; of: string; edit: EditFn; busy: boolean }) {
  const [text, setText] = useState(c.label);
  useEffect(() => setText(c.label), [c.label]);
  const commit = () => { if (text.trim() && text.trim() !== c.label) void edit({ op: "camera_edit", of, cam: c.id, field: "label", value: text.trim() }); else setText(c.label); };
  return <input value={text} maxLength={40} aria-label={`Name of ${c.label}`} disabled={busy} onChange={(e) => setText(e.target.value)}
    onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />;
}

function Group({ g, v, edit, busy }: { g: CameraGroup; v: Video; edit: EditFn; busy: boolean }) {
  const fps = v.plan?.output.fps || 30;
  const frame = 1000 / fps;
  // one frame earlier or later: the measured clock drift stays
  const nudge = (c: Camera, by: number) => edit({ op: "camera_edit", of: g.of, cam: c.id, field: "nudge_ms", value: Math.round(by * 10) / 10 });
  const corner = g.corner;
  const sized = corner?.size ? String(corner.size) : "";
  const sizes = sized && !SIZES.some(([s]) => s === sized) ? [...SIZES, [sized, `${Math.round(Number(sized) * 100)}%`] as [string, string]] : SIZES;
  const unused = v.bin.filter((aid) => aid !== g.of && !g.cams.some((c) => c.asset_id === aid) && v.assets.find((a) => a.id === aid)?.kind === "video");
  return (
    <div className="stack-3">
      <p className="small"><b>{g.filename}</b>: {g.cams.length} cameras · {g.changes} camera {g.changes === 1 ? "change" : "changes"}</p>
      <div className="row wrap top">
        <label className="field"><span>Switch cameras</span>
          <select value={g.switching} disabled={busy} onChange={(e) => edit({ op: "cameras_auto", of: g.of, mode: e.target.value })}>
            {(["speaker", "angles", "off"] as CameraSwitching[]).map((k) => <option key={k} value={k}>{SWITCHING[k]}</option>)}
            {g.switching === "hand" && <option value="hand" disabled>{SWITCHING.hand}</option>}
          </select>
          <span className="small muted">{g.switching === "speaker" ? "Cuts in the gap between people, holds each shot at least 2 s, the wide shot at the start, the end and in long pauses."
            : g.switching === "angles" ? "Holds each angle 3.5 to 12 s and changes it in a pause."
              : g.switching === "hand" ? "Choose a camera for a clip, or change camera at a moment, in the clip's details." : "Only the recording's own camera is shown."}</span></label>
        <label className="field"><span>In a corner</span>
          <select value={corner?.cam || ""} disabled={busy} onChange={(e) => edit({ op: "camera_corner", of: g.of, cam: e.target.value || null })}>
            <option value="">No camera in a corner</option>
            {g.cams.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
          <span className="small muted">Hidden while that camera is the full picture.</span></label>
        {corner && <label className="field"><span>Corner</span>
          <select value={corner.place || ""} disabled={busy} onChange={(e) => edit({ op: "camera_corner", of: g.of, cam: corner.cam, place: e.target.value })}>
            {!corner.place && <option value="">Usual corner</option>}
            {Object.entries(CORNERS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select></label>}
        {corner && <label className="field"><span>Size</span>
          <select value={sized} disabled={busy} onChange={(e) => e.target.value && edit({ op: "camera_corner", of: g.of, cam: corner.cam, size: Number(e.target.value) })}>
            {sizes.map(([s, t]) => <option key={s} value={s} disabled={!s && !!sized}>{t}</option>)}
          </select></label>}
      </div>
      <ul className="seq audio-list">{g.cams.map((c) => (
        <li key={c.id}>
          <div className="break">
            <div className="cam-name"><span className={`cam-dot ${camClass(g, c.id)}`} aria-hidden="true" />
              <CameraName c={c} of={g.of} edit={edit} busy={busy} /></div>
            <span className="block small muted">{c.filename} · {lineUp(c, fps)}</span>
          </div>
          <div className="row-actions wrap">
            <select value={c.shot} aria-label={`What ${c.label} shows`} disabled={busy} onChange={(e) => edit({ op: "camera_edit", of: g.of, cam: c.id, field: "shot", value: e.target.value })}>
              {Object.entries(SHOTS).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
            {c.id !== "main" && <>
              <button type="button" className="btn btn-small" disabled={busy} title="Show this camera one frame earlier" onClick={() => nudge(c, -frame)}>−1 frame</button>
              <button type="button" className="btn btn-small" disabled={busy} title="Show this camera one frame later" onClick={() => nudge(c, frame)}>+1 frame</button>
            </>}
          </div>
        </li>))}
      </ul>
      <div className="row-actions wrap">
        {unused.length > 0 && <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "cameras_add", of: g.of })}><Icon name="plus" />Line up the other recordings</button>}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "cameras_remove", of: g.of })}>Back to one camera</button>
      </div>
    </div>
  );
}

/** The Cameras panel: shown once the media holds two videos or more. */
export function CamerasPanel({ v, edit, busy }: { v: Video; edit: EditFn; busy: boolean }) {
  const groups = v.cameras || [];
  const videos = v.bin.filter((aid) => v.assets.find((a) => a.id === aid)?.kind === "video");
  if (!groups.length && videos.length < 2) return null;
  return (
    <section className="panel" aria-labelledby="vr-cameras">
      <h2 id="vr-cameras">Cameras</h2>
      {!groups.length ? <>
        <p className="small muted">Filmed the same moment with more than one camera? ClipForge lines the recordings up by
          their sound, then switches to whoever is speaking. The sound and captions always come from the main recording.</p>
        <div className="row-actions wrap">
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "cameras_auto", mode: "speaker" })}>Line up and switch to whoever speaks</button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "cameras_auto", mode: "angles" })}>Line up and change angles</button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => edit({ op: "cameras_add" })}>Only line them up</button>
        </div></> : groups.map((g) => <Group key={g.of} g={g} v={v} edit={edit} busy={busy} />)}
    </section>
  );
}

/** The timeline's Cameras row: which camera is on screen when (a dot marks a camera in the corner). */
export function CamerasRow({ v, pct }: { v: Video; pct: (ms: number) => string }) {
  const spans = v.camera_timeline || [];
  if (!spans.length) return null;
  const group = (aid: string) => v.cameras?.find((g) => g.of === aid);
  return (
    <div className="tl-row"><span className="tl-name">Cameras</span><div className="tl-lane">
      {spans.map((s) => {
        const g = group(s.asset_id);
        const corner = s.corner ? g?.cams.find((c) => c.id === s.corner)?.label : "";
        return <span key={`${s.clip_id}-${s.out_start_ms}`} className={`tl-seg cam ${camClass(g, s.cam)} ${corner ? "has-corner" : ""}`}
          title={`${s.label}${corner ? `, ${corner} in the corner` : ""} · ${fmtEdit(s.out_start_ms)}–${fmtEdit(s.out_end_ms)}`}
          style={{ left: pct(s.out_start_ms), width: pct(s.out_end_ms - s.out_start_ms) }} />;
      })}</div></div>
  );
}

/** In a clip's details: one camera for the whole clip, or another camera from the split point on. */
export function ClipCamera({ c, v, at, edit, busy }: { c: PlanClip; v: Video; at: number; edit: EditFn; busy: boolean }) {
  const g = v.cameras?.find((x) => x.of === c.asset_id);
  const shows = [...new Set((v.camera_timeline || []).filter((s) => s.clip_id === c.id).map((s) => s.cam))];
  const [cutCam, setCutCam] = useState("");
  if (!g) return null;
  const whole = shows.length === 1 ? shows[0] : "";
  const inside = at > c.in_ms && at < c.out_ms;
  const several = shows.map((id) => g.cams.find((x) => x.id === id)?.label || id).join(", ");
  return (
    <div className="stack-3">
      <div className="grid-2">
        <label className="field"><span>Camera</span>
          <select value={whole} disabled={busy} title={whole ? "" : several}
            onChange={(e) => e.target.value && edit({ op: "camera_set", clip_id: c.id, cam: e.target.value })}>
            {!whole && <option value="">{shows.length ? "Several cameras" : "No camera shown"}</option>}
            {g.cams.map((x) => <option key={x.id} value={x.id}>{x.label} · {SHOTS[x.shot].toLowerCase()}</option>)}
          </select></label>
        <div className="field"><span>From the split point</span><div className="row-actions start">
          <select value={cutCam} aria-label="Camera from the split point on" disabled={busy} onChange={(e) => setCutCam(e.target.value)}>
            <option value="">Camera…</option>{g.cams.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>
          <button type="button" className="btn btn-small" disabled={busy || !cutCam || !inside}
            title={inside ? "" : "Set the split point inside this clip first"}
            onClick={() => edit({ op: "camera_cut", clip_id: c.id, cam: cutCam, offset_ms: at - c.in_ms })}>Change here</button>
        </div></div>
      </div>
      <p className="small muted">{whole ? "" : `Shows ${several}. `}The sound always comes from {g.cams[0]?.label || "the main camera"}.</p>
    </div>
  );
}
