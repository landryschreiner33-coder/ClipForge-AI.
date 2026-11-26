import { KeyboardEvent, PointerEvent, useEffect, useRef, useState } from "react";
import { announce, Icon, ProgressBar, Segmented, toast } from "./ui";
import { api, CamCheck, Clip, errorText, FaceCamState, Project, uploadCamera, UploadCanceled } from "../api";

/** A box drawn over a video's picture, in shares of it: [x0, y0, x1, y1]. */
export type Box = number[];
const MIN = 0.05;                          // the server refuses a box narrower than 0.04 of the picture
const START: Box = [0.02, 0.6, 0.28, 0.95]; // where a face cam usually is: bottom left
const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const round = (b: Box) => b.map((v) => Math.round(v * 1000) / 1000);
const pct = (v: number) => `${Math.round(v * 100)}%`;

/** The picture of a video at `time`, with a box to move (drag it, or arrow keys), resize (the corner, or Shift +
 * arrow keys) or draw again (drag anywhere else). */
export function FaceCamBox({ src, time, aspect, box, onChange, label }: {
  src: string; time: number; aspect: number; box: Box; onChange: (b: Box) => void; label: string;
}) {
  const area = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const drag = useRef<{ mode: "move" | "resize" | "draw"; x: number; y: number; from: Box } | null>(null);

  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const seek = () => { v.currentTime = Math.max(0, time); };
    if (v.readyState >= 1) seek();
    else v.addEventListener("loadedmetadata", seek, { once: true });
  }, [src, time]);

  const point = (e: PointerEvent) => {
    const r = area.current!.getBoundingClientRect();
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  };
  const down = (e: PointerEvent<HTMLDivElement>) => {
    const [x, y] = point(e);
    const handle = (e.target as HTMLElement).dataset.handle;
    const inside = x > box[0] && x < box[2] && y > box[1] && y < box[3];
    drag.current = { mode: handle ? "resize" : inside ? "move" : "draw", x, y, from: box };
    area.current!.setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const [x, y] = point(e);
    const [x0, y0, x1, y1] = d.from;
    if (d.mode === "move") {
      const dx = clamp(x - d.x, -x0, 1 - x1), dy = clamp(y - d.y, -y0, 1 - y1);
      onChange(round([x0 + dx, y0 + dy, x1 + dx, y1 + dy]));
    } else if (d.mode === "resize") {
      onChange(round([x0, y0, Math.max(x0 + MIN, x), Math.max(y0 + MIN, y)]));
    } else if (Math.abs(x - d.x) >= MIN && Math.abs(y - d.y) >= MIN) {
      onChange(round([Math.min(x, d.x), Math.min(y, d.y), Math.max(x, d.x), Math.max(y, d.y)]));
    }
  };
  const up = () => { drag.current = null; };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01] }[e.key];
    if (!step) return;
    e.preventDefault();
    const [x0, y0, x1, y1] = box;
    if (e.shiftKey) {
      onChange(round([x0, y0, clamp(x1 + step[0], x0 + MIN), clamp(y1 + step[1], y0 + MIN)]));
    } else {
      const dx = clamp(step[0], -x0, 1 - x1), dy = clamp(step[1], -y0, 1 - y1);
      onChange(round([x0 + dx, y0 + dy, x1 + dx, y1 + dy]));
    }
  };
  return (
    <div className="cam-editor" ref={area} style={{ aspectRatio: String(aspect) }} onPointerDown={down}
      onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
      <video ref={video} src={src} muted playsInline preload="auto" aria-hidden="true" />
      <div className="cam-box" tabIndex={0} role="group" onKeyDown={key}
        aria-label={`${label}: ${pct(box[0])} from the left, ${pct(box[1])} from the top, ${pct(box[2] - box[0])} `
          + `wide, ${pct(box[3] - box[1])} high. Arrow keys move it; Shift and arrow keys change its size.`}
        style={{ left: pct(box[0]), top: pct(box[1]), width: pct(box[2] - box[0]), height: pct(box[3] - box[1]) }}>
        <span className="cam-box-handle" data-handle="resize" aria-hidden="true" />
      </div>
    </div>
  );
}

const SYNCED: Record<string, string> = {
  sound: "Lined up by the sound both recorded.",
  you: "Lined up by the offset you typed.",
  none: "Not lined up: no sound both recorded was found. Type the offset below.",
};

/** The face cam part of the clip editor's Layout tab: how sure the last render's face cam is, drawing or locking
 * its box, the Picture-in-picture corner, and a separate camera recording. */
export function FaceCamPanel({ project, clip, layout, box, setBox, pipCorner, setPipCorner, renderNow, busy }: {
  project: Project; clip: Clip; layout: string; box: Box | null; setBox: (b: Box | null) => void;
  pipCorner: "left" | "right"; setPipCorner: (c: "left" | "right") => void; renderNow: () => void; busy: boolean;
}) {
  const [fc, setFc] = useState<FaceCamState | null>(null);
  const [open, setOpen] = useState(false);
  const [work, setWork] = useState<Box | null>(null);
  const [offset, setOffset] = useState("");
  const [upload, setUpload] = useState<number | null>(null);
  const sending = useRef<AbortController | null>(null);   // the recording being sent, for Cancel upload
  const [changedHere, setChangedHere] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    api.facecam(project.id).then((s) => live && setFc(s)).catch(() => undefined);
    return () => { live = false; };
  }, [project.id]);
  const savedOffset = fc?.camera ? String(fc.camera.offset) : "";
  useEffect(() => { setOffset(savedOffset); }, [savedOffset]);

  const check: CamCheck | null | undefined = clip.cam_check;
  const camera = fc?.camera || null;
  const rendered = (clip.render_info?.framing_evidence?.split?.cam as Box | undefined) || null;
  const current: Box = (camera ? camera.box : box || fc?.found?.box || (rendered && !camera ? rendered : null))
    || (camera ? [0, 0, 1, 1] : START);
  const shown = work || current;
  const aspect = camera ? camera.width / Math.max(1, camera.height)
    : (project.width || 16) / Math.max(1, project.height || 9);
  const src = camera ? `/api/projects/${project.id}/camera/video` : `/api/projects/${project.id}/source`;
  const at = Number(clip.edit?.start ?? clip.start) + 1 + (camera ? camera.offset : 0);

  const done = (s: FaceCamState, words: string) => {
    setFc(s);
    setChangedHere(true);
    toast(words);
  };
  const act = async (run: () => Promise<FaceCamState>, words: string) => {
    try {
      done(await run(), words);
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const addCamera = async (file: File) => {
    setUpload(0);
    const ctl = new AbortController();
    sending.current = ctl;
    try {
      done(await uploadCamera(project.id, file, "", setUpload, ctl.signal),
        "Camera recording added. Render the clip to see it.");
      setWork(null);
    } catch (e) {
      toast(e instanceof UploadCanceled ? e.message : errorText(e), !(e instanceof UploadCanceled));
    } finally {
      sending.current = null;
      setUpload(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="field facecam">
      <span className="label">Face cam</span>
      {check && (
        <p className={`cam-check ${check.state}`} role="status">
          <Icon name={check.state === "unsure" || check.state === "none" ? "alert" : "check"} />
          {check.text}
        </p>
      )}
      {fc?.found?.locked && !camera && (
        <p className="hint">
          A box is locked for every clip of this video.{" "}
          <button type="button" className="textlink" onClick={() => act(() => api.lockFacecam(project.id, null),
            "Unlocked. Clips look for the face cam again when they are rendered.")}>Unlock</button>
        </p>
      )}
      {box && !camera && <p className="hint">This clip uses the box you drew.{" "}
        <button type="button" className="textlink" onClick={() => {
          setBox(null);
          announce("This clip's own box removed: not saved yet");
        }}>Find it automatically</button></p>}
      {layout === "pip" && (
        <div className="row wrap">
          <span className="small" id={`pip-corner-${clip.id}`}>The face cam's box sits in the top</span>
          <Segmented labelledBy={`pip-corner-${clip.id}`} value={pipCorner} onChange={(c) => setPipCorner(c)}
            options={[{ value: "left", label: "Left corner" }, { value: "right", label: "Right corner" }]} />
        </div>
      )}
      {!open && (
        <button type="button" className="btn btn-small" onClick={() => { setWork(current); setOpen(true); }}>
          <Icon name="edit" />{camera ? "Choose the part of the camera to show" : "Draw the face cam yourself"}
        </button>
      )}
      {open && (
        <div className="cam-draw">
          <p className="hint">{camera
            ? "Drag the box over the part of your camera's picture to show."
            : "Drag the box over the face cam in the video's picture, or drag anywhere to draw it again."}</p>
          <FaceCamBox src={src} time={at} aspect={aspect} box={shown} onChange={setWork}
            label={camera ? "The part of the camera to show" : "The face cam's box"} />
          <div className="row wrap">
            {camera ? (<>
              <button type="button" className="btn btn-small btn-primary" onClick={() => act(
                () => api.patchCamera(project.id, { box: shown }), "Saved. Render the clip to see it.")}>
                Show this part</button>
              <button type="button" className="btn btn-small" onClick={() => act(
                () => api.patchCamera(project.id, { whole: true }), "The whole camera picture is shown again.")}>
                Show all of it</button>
            </>) : (<>
              <button type="button" className="btn btn-small btn-primary" onClick={() => {
                setBox(shown);
                announce("Face cam box set for this clip: not saved yet");
              }}>Use for this clip</button>
              <button type="button" className="btn btn-small" onClick={() => act(
                () => api.lockFacecam(project.id, shown),
                "Locked. Every clip of this video uses this box when it is rendered.")}>
                <Icon name="lock" />Lock for every clip of this video</button>
            </>)}
            <button type="button" className="btn btn-small btn-quiet"
              onClick={() => { setOpen(false); setWork(null); }}>
              Close</button>
          </div>
        </div>
      )}
      <div className="cam-recording">
        {camera ? (<>
          <p className="small"><Icon name="video" /> Separate camera recording: <b>{camera.name}</b></p>
          <p className="hint">{SYNCED[camera.synced] || ""} Every clip of this video that uses a face cam shows
            this recording.</p>
          <div className="row wrap">
            <label className="small" htmlFor={`cam-off-${project.id}`}>Camera clock ahead of the video by</label>
            <input id={`cam-off-${project.id}`} className="cam-offset tnum" type="number" step={0.05} value={offset}
              onChange={(e) => setOffset(e.target.value)} aria-describedby={`cam-off-hint-${project.id}`} />
            <span className="small">s</span>
            <button type="button" className="btn btn-small"
              disabled={!offset.trim() || !Number.isFinite(Number(offset)) || Number(offset) === camera.offset}
              onClick={() => act(() => api.patchCamera(project.id, { offset: Number(offset) }),
                "Offset saved. Render the clip to see it.")}>Save offset</button>
            <button type="button" className="btn btn-small btn-quiet" onClick={() => act(
              () => api.deleteCamera(project.id),
              "Camera recording removed. Clips look for a face cam in the video again.")}>Remove</button>
          </div>
          <p className="hint" id={`cam-off-hint-${project.id}`}>A camera started 2 seconds after the video is −2.</p>
        </>) : (<>
          <p className="hint">Recorded your camera separately? Add that file and it becomes the face cam, lined up
            with the video by the sound both recorded.</p>
          <input ref={fileRef} type="file" accept="video/*" className="sr-only" id={`cam-file-${project.id}`}
            onChange={(e) => e.target.files?.[0] && addCamera(e.target.files[0])} />
          {upload === null
            ? <label className="btn btn-small" htmlFor={`cam-file-${project.id}`}><Icon name="upload" />
              Add a camera recording</label>
            : <div className="row wrap">
              <ProgressBar value={upload} label={upload < 1 ? "Copying the camera recording" : "Lining it up"} />
              {upload < 1 && <button type="button" className="btn btn-small" onClick={() => sending.current?.abort()}>
                <Icon name="x" />Cancel upload</button>}
            </div>}
        </>)}
      </div>
      {changedHere && (
        <p className="hint">The change is used when the clip is rendered.{" "}
          <button type="button" className="textlink" disabled={busy} onClick={() => {
            setChangedHere(false);
            renderNow();
          }}>Render this clip again</button></p>
      )}
    </div>
  );
}
