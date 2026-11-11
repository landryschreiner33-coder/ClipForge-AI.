import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { errorText } from "../api";
import {
  SceneStatus, ScenePatch, ShortLook, ShortOptions, ShortOptionsPatch, ShortScene, ShortView, shorts,
} from "../shorts";
import { PlanClip, studio, Video } from "../studio";
import { FileDrop, Picked, useUploadsByFile } from "./studioParts";
import { announce, Banner, ConfirmDialog, Disclosure, Icon, IconName, Pill, ProgressBar, Tone, toast } from "./ui";
import "../pages/shorts.css";

/** A plan clip made from a scene (its id is the scene's id; a part split off in the editor names its scene). */
type SceneClip = PlanClip & { scene_id?: string };
/** Where a scene's clip can move to in the plan: just before the scene before it, just after the scene after it. */
type Moves = { clip: string; earlier: number | null; later: number | null };

/** Sends one change and hands the video it answers with to the page; `said` is told to screen readers. */
type Send = (call: () => Promise<Video>, said?: string) => Promise<Video>;
/** The same, but a problem is shown as a message and the answer is null. */
type Run = (call: () => Promise<Video>, said?: string) => Promise<Video | null>;

export const MOVES: [string, string][] = [["auto", "Automatic"], ["zoom_in", "Push in"], ["zoom_out", "Pull out"],
  ["pan_left", "Pan left"], ["pan_right", "Pan right"], ["pan_up", "Pan up"], ["pan_down", "Pan down"], ["still", "Still"]];
const WORKING = new Set<SceneStatus>(["voice", "picture", "motion"]);
const SCENE_WORDS: Record<SceneStatus, string> = { waiting: "Waiting its turn", voice: "Making the voice",
  picture: "Making the picture", motion: "Adding the motion", ready: "Ready", failed: "This scene could not be made." };
const THUMB_WORDS: Record<SceneStatus, string> = { waiting: "Waiting", voice: "Voice", picture: "Picture",
  motion: "Motion", ready: "Ready", failed: "Failed" };
const PICTURE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const isPicture = (f: File) => (f.type ? PICTURE_TYPES.has(f.type) : /\.(png|jpe?g|webp)$/i.test(f.name));

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const lowerFirst = (t: string) => (/^[A-Z][a-z]/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);
const lengthWords = (sec: number) => {
  const s = Math.max(1, Math.round(sec));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}`;
};
const listWords = (parts: string[]) => (parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`
  : parts[0] || "");

/** Where a scene's picture came from, in a few words (its Picture line; the reason for a card is shown inside). */
export function pictureWords(p: ShortScene["picture"]): string {
  if (p.source === "engine") return `Made by ${p.engine || "the picture maker"}`;
  if (p.source === "card") return "Designed card";
  if (p.source === "upload") return "Your picture";
  return "";
}

/** The short's stage as a word and an icon. */
function stageWords(s: ShortView): [string, Tone, IconName] {
  const { done, total } = s.progress;
  switch (s.stage) {
    case "writing": return ["Writing the script", "info", "spark"];
    case "review": return ["Check the script", "info", "edit"];
    case "making": {
      const left = total - done;
      return [left > 0 ? `${plural(left, "scene")} to make` : "Putting it together", "info", "clock"];
    }
    case "ready": return ["Ready", "good", "check"];
    case "failed": return ["Failed", "bad", "alert"];
    case "stopped": return ["Stopped", "warn", "stop"];
    default: return [s.message || "Working", "info", "clock"];
  }
}

/** Text the person is typing stays while the page refreshes; a new value from ClipForge replaces it only when the
 * person has not changed it. `settle` takes the saved value as the new starting point. */
function useDraft(value: string) {
  const [draft, setDraft] = useState(value);
  const base = useRef(value);
  useEffect(() => {
    if (value === base.current) return;
    const old = base.current;
    base.current = value;
    setDraft((d) => (d === old ? value : d));
  }, [value]);
  const settle = useCallback((v: string) => {
    base.current = v;
    setDraft(v);
  }, []);
  return [draft, setDraft, settle] as const;
}

/** "Hear it": a few seconds of the voice at this speed, made on this computer. Pressing it again while it plays stops it. */
export function HearButton({ voice, speed, disabled, small }: { voice: string; speed: number; disabled?: boolean;
  small?: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const sample = useRef<{ key: string; url: string } | null>(null);
  const latest = useRef("");
  const key = `${voice}|${speed}`;
  latest.current = key;
  const stop = useCallback(() => {
    const a = audio.current;
    audio.current = null;
    if (a) {
      a.onended = null;
      a.onerror = null;
      a.pause();
    }
    setState("idle");
  }, []);
  useEffect(() => stop, [key, stop]);  // another voice or speed, or leaving the page, stops the sound
  useEffect(() => () => {
    if (sample.current) URL.revokeObjectURL(sample.current.url);
    sample.current = null;
    latest.current = "";
  }, []);
  const click = async () => {
    if (state === "playing") {
      stop();
      return;
    }
    if (state === "loading") return;
    const asked = key;
    try {
      if (sample.current?.key !== asked) {
        setState("loading");
        const { blob, note } = await shorts.voiceSample(voice, speed);
        if (latest.current !== asked) return;  // the voice changed while the sample was made
        if (sample.current) URL.revokeObjectURL(sample.current.url);
        // a sample another voice read is played once and asked for again next time
        sample.current = { key: note ? "" : asked, url: URL.createObjectURL(blob) };
        if (note) toast(note);
      }
      const a = new Audio(sample.current.url);
      audio.current = a;
      a.onended = () => audio.current === a && stop();
      a.onerror = () => {
        if (audio.current !== a) return;
        stop();
        toast("That voice sample could not be played. Try another voice.", true);
      };
      await a.play();
      if (audio.current === a) setState("playing");
    } catch (e) {
      stop();
      if ((e as Error).name === "NotAllowedError") toast("The voice sample is ready. Press Hear it again to listen.");
      else toast(errorText(e), true);
    }
  };
  return (
    <button type="button" className={`btn hear-btn${small ? " btn-small" : ""}`} disabled={disabled || !voice}
      aria-busy={state === "loading" || undefined} onClick={() => void click()}>
      {state === "loading" ? <span className="inline-spinner" aria-hidden="true" /> : <Icon name={state === "playing" ? "stop" : "play"} />}
      {state === "playing" ? "Stop" : "Hear it"}
    </button>
  );
}

/** A scene's picture as a 9:16 thumbnail; while it is made, a placeholder that says what is happening. */
function SceneThumb({ scene, early }: { scene: ShortScene; early: boolean }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [scene.picture_asset_id]);
  const shown = !!scene.picture_asset_id && !broken;
  const working = WORKING.has(scene.status);
  const state = early ? "Not made yet" : THUMB_WORDS[scene.status];
  return (
    <span className="scene-thumb" aria-hidden="true">
      {shown && <img src={`/api/assets/${encodeURIComponent(scene.picture_asset_id)}/thumbnail`} alt="" loading="lazy"
        onError={() => setBroken(true)} />}
      {(!shown || working || scene.status === "failed") && (
        <span className={`scene-thumb-state${shown ? " over" : ""}`}>
          {working ? <span className="inline-spinner" /> : <Icon name={scene.status === "failed" ? "alert" : "film"} />}
          <span>{state}</span>
        </span>
      )}
    </span>
  );
}

/** A small form for a new scene: what the voice says in it. */
function AddScene({ label, off, onAdd, onClose }: { label: string; off: boolean; onAdd: (text: string) => Promise<boolean>;
  onClose: () => void }) {
  const [text, setText] = useState("");
  const id = useId();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || off) return;
    if (await onAdd(t)) onClose();
  };
  return (
    <form className="scene-add" onSubmit={(e) => void submit(e)}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } }}>
      <label className="label small" htmlFor={id}>{label}</label>
      <textarea id={id} rows={3} value={text} autoFocus placeholder="What the voice says in the new scene"
        onChange={(e) => setText(e.target.value)} />
      <div className="scene-actions">
        <button type="submit" className="btn btn-small" disabled={off || !text.trim()}><Icon name="plus" />Add</button>
        <button type="button" className="btn btn-small btn-quiet" onClick={onClose}>Cancel</button>
      </div>
    </form>
  );
}

/** One scene: its picture, its words, where it is, its picture's details, and moving, deleting and adding after it. */
function SceneRow({ scene, v, s, moves, off, run, adding, onAdding, onDelete }: {
  scene: ShortScene; v: Video; s: ShortView; moves: Moves | null; off: boolean; run: Run; adding: boolean;
  onAdding: (on: boolean) => void; onDelete: () => void;
}) {
  const id = useId();
  const [words, setWords, settleWords] = useDraft(scene.narration);
  const [idea, setIdea, settleIdea] = useDraft(scene.picture_prompt);
  const [typing, setTyping] = useState<"" | "words" | "idea">("");
  const [uploading, setUploading] = useState(false);
  const [drop, setDrop] = useState(0);  // a new number is a new, empty drop area
  const seen = useRef(new Set<string>());
  const uploaded = useUploadsByFile();  // every upload of a picture, also one dropped again after a change failed
  const addButton = useRef<HTMLButtonElement>(null);
  const early = s.stage === "review" || s.stage === "writing";
  const writing = s.stage === "writing";
  const working = WORKING.has(scene.status);
  const patch = (body: ScenePatch, said: string) => run(() => shorts.patchScene(v.id, scene.id, body), said);
  const fresh = (nv: Video | null) => nv?.short?.scenes.find((x) => x.id === scene.id);

  const saveWords = async () => {
    setTyping("");
    const text = words.trim();
    if (text === scene.narration.trim()) {
      if (words !== scene.narration) settleWords(scene.narration);
      return;
    }
    if (!text) {
      toast("A scene needs some words. To take a scene out, use Delete.", true);
      settleWords(scene.narration);
      return;
    }
    const got = fresh(await patch({ narration: text },
      early ? `Scene ${scene.n} saved.` : `Scene ${scene.n} saved. ClipForge makes its voice again.`));
    if (got) settleWords(got.narration);
  };
  const saveIdea = async () => {
    setTyping("");
    const text = idea.trim();
    if (text === scene.picture_prompt.trim()) {
      if (idea !== scene.picture_prompt) settleIdea(scene.picture_prompt);
      return;
    }
    const got = fresh(await patch({ picture_prompt: text }, `The picture idea of scene ${scene.n} is saved.`));
    if (got) settleIdea(got.picture_prompt);
  };
  // FileDrop reports its rows while it updates itself, so each upload is dealt with a moment later, and only once
  // (a picture dropped again is a new upload, so a change that failed is tried again with it).
  const picked = (rows: Picked[]) => {
    for (const r of rows) {
      const k = `${drop}|${r.key}|${r.asset?.upload_id || ""}`;
      const wrong = !isPicture(r.file) || (!!r.asset && r.asset.kind !== "image");
      if (seen.current.has(k) || (!wrong && !r.asset)) continue;
      seen.current.add(k);
      const assetId = r.asset?.id || "";
      window.setTimeout(() => {
        if (wrong) {
          setDrop((n) => n + 1);  // the old drop area goes, and its upload stops
          toast("That file is not a picture. Use a PNG, JPEG or WebP picture.", true);
        } else {
          void patch({ picture_asset_id: assetId, upload_ids: uploaded.of([assetId]) }, `Scene ${scene.n} uses your picture now.`)
            .then((nv) => nv && setUploading(false));
        }
      }, 0);
      return;
    }
  };
  const move = (clip: string, to: number, way: string) => run(() => studio.editVideo(v.id, v.plan_revision,
    { op: "move", clip_id: clip, to }), `Scene ${scene.n} moved ${way}.`);
  const closeAdd = () => {
    onAdding(false);
    window.requestAnimationFrame(() => addButton.current?.focus());
  };
  const pw = pictureWords(scene.picture);
  const tone = scene.status === "ready" ? "good" : scene.status === "failed" ? "bad" : working ? "info" : "";
  const said = scene.status === "failed" ? scene.error || scene.message || SCENE_WORDS.failed
    : scene.message || SCENE_WORDS[scene.status];
  const wordsUnsaved = typing !== "words" && words.trim() !== scene.narration.trim();
  const ideaUnsaved = typing !== "idea" && idea.trim() !== scene.picture_prompt.trim();

  return (
    <li className={`short-scene ${scene.status}${scene.in_plan && !scene.included ? " off" : ""}`} id={`scene-${scene.id}`}>
      <SceneThumb scene={scene} early={early} />
      <div className="scene-main">
        <div className="scene-top">
          <h3 className="scene-title">Scene {scene.n}
            {scene.duration > 0 && <span className="small muted tnum"> · {scene.duration.toFixed(1)} s</span>}</h3>
          <div className="scene-move">
            <button type="button" className="btn btn-small btn-icon" aria-label={`Move scene ${scene.n} earlier`}
              title="Move earlier" disabled={off || !scene.in_plan || moves?.earlier == null}
              onClick={() => moves && moves.earlier != null && void move(moves.clip, moves.earlier, "earlier")}>
              <Icon name="chev" className="rot-up" /></button>
            <button type="button" className="btn btn-small btn-icon" aria-label={`Move scene ${scene.n} later`}
              title="Move later" disabled={off || !scene.in_plan || moves?.later == null}
              onClick={() => moves && moves.later != null && void move(moves.clip, moves.later, "later")}>
              <Icon name="chev" /></button>
          </div>
        </div>
        <label className="sr-only" htmlFor={`${id}-words`}>Words of scene {scene.n}</label>
        <textarea id={`${id}-words`} rows={3} value={words} readOnly={writing} aria-describedby={early ? undefined : `${id}-state`}
          onChange={(e) => setWords(e.target.value)} onFocus={() => setTyping("words")} onBlur={() => void saveWords()} />
        {wordsUnsaved && (
          <p className="scene-unsaved"><Icon name="alert" className="sm" /><span>These words are not saved yet.</span>
            <button type="button" className="btn btn-small" disabled={off} onClick={() => void saveWords()}>Save the words</button>
            <button type="button" className="btn btn-small btn-quiet" onClick={() => settleWords(scene.narration)}>Put back the saved words</button>
          </p>
        )}
        {!early && (
          <p className={`scene-status ${tone}`} id={`${id}-state`}>
            {working ? <span className="inline-spinner" aria-hidden="true" />
              : <Icon name={scene.status === "ready" ? "check" : scene.status === "failed" ? "alert" : "clock"} className="sm" />}
            <span>{said}</span>
            {scene.status === "failed" && (
              <button type="button" className="btn btn-small" disabled={off}
                onClick={() => void patch({ again: true }, `ClipForge is trying scene ${scene.n} again.`)}>
                <Icon name="refresh" />Try again</button>
            )}
          </p>
        )}
        {!early && scene.status === "ready" && !!scene.voice.fallback && (
          <p className="scene-status warn">
            <Icon name="alert" className="sm" />
            <span>{scene.voice.fallback}</span>
            <button type="button" className="btn btn-small" disabled={off}
              onClick={() => void patch({ again: true }, `ClipForge is asking the chosen voice to read scene ${scene.n} again.`)}>
              <Icon name="refresh" />Try again</button>
          </p>
        )}
        {scene.in_plan && !scene.included && (
          <p className="small muted">Switched off in the sequence, so it is not in the video.{" "}
            <button type="button" className="link-btn" disabled={off}
              onClick={() => void run(() => studio.editVideo(v.id, v.plan_revision, { op: "include", clip_id: scene.id }),
                `Scene ${scene.n} is back in the video.`)}>Put it back</button></p>
        )}
        <Disclosure plain summary={<>Picture{pw && <span className="muted small"> · {pw}</span>}</>}>
          <div className="scene-picture">
            {scene.picture.source === "card" && (
              <p className="small muted">A designed card with the scene's key words{scene.picture.why
                ? `, because ${lowerFirst(scene.picture.why).replace(/\.$/, "")}.` : "."}</p>
            )}
            <div className="field">
              <label htmlFor={`${id}-idea`}>Picture idea</label>
              <input id={`${id}-idea`} type="text" value={idea} maxLength={400} readOnly={writing}
                placeholder="What the picture shows" aria-describedby={`${id}-idea-hint`}
                onChange={(e) => setIdea(e.target.value)} onFocus={() => setTyping("idea")} onBlur={() => void saveIdea()} />
              <span className="hint" id={`${id}-idea-hint`}>Saved when you leave the box.</span>
            </div>
            {ideaUnsaved && (
              <p className="scene-unsaved"><Icon name="alert" className="sm" /><span>This picture idea is not saved yet.</span>
                <button type="button" className="btn btn-small" disabled={off} onClick={() => void saveIdea()}>Save it</button>
                <button type="button" className="btn btn-small btn-quiet" onClick={() => settleIdea(scene.picture_prompt)}>Put back the saved idea</button>
              </p>
            )}
            {!writing && (
              <div className="scene-actions">
                {scene.picture_asset_id && (
                  <button type="button" className="btn btn-small" disabled={off}
                    onClick={() => void patch({ new_picture: true }, `ClipForge is making a new picture for scene ${scene.n}.`)}>
                    <Icon name="refresh" />New picture</button>
                )}
                <button type="button" className="btn btn-small" aria-expanded={uploading}
                  onClick={() => { setDrop((n) => n + 1); setUploading((u) => !u); }}>
                  <Icon name="upload" />Use my picture…</button>
              </div>
            )}
            {uploading && !writing && (
              <div className="scene-upload">
                <FileDrop key={drop} accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  label={`Drop a PNG, JPEG or WebP picture for scene ${scene.n}`} onAssets={picked} onUploaded={uploaded.add} />
              </div>
            )}
            {scene.earlier.length > 0 && (
              <div className="stack-2">
                <span className="label small" id={`${id}-earlier`}>Earlier pictures</span>
                <ul className="scene-earlier" aria-labelledby={`${id}-earlier`}>
                  {scene.earlier.slice(0, 8).map((e, k) => (
                    <li key={e.asset_id}>
                      <button type="button" className="scene-earlier-btn" disabled={off} title={e.prompt || undefined}
                        aria-label={`Use earlier picture ${k + 1}${e.prompt ? `: ${e.prompt}` : ""}`}
                        onClick={() => void patch({ picture_asset_id: e.asset_id }, `Scene ${scene.n} uses an earlier picture again.`)}>
                        <img src={`/api/assets/${encodeURIComponent(e.asset_id)}/thumbnail`} alt="" loading="lazy" />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <label className="field">
              <span>Camera move</span>
              <select value={MOVES.some(([m]) => m === scene.move) ? scene.move : "auto"} disabled={off || writing}
                onChange={(e) => void patch({ move: e.target.value }, `Scene ${scene.n} gets the new camera move.`)}>
                {MOVES.map(([m, t]) => <option key={m} value={m}>{t}</option>)}
              </select>
              {s.motion === "animate" && <span className="hint">With Animate the pictures, the video maker moves the picture instead.</span>}
            </label>
          </div>
        </Disclosure>
        {!writing && (
          <div className="scene-actions">
            <button ref={addButton} type="button" className="btn btn-small" aria-expanded={adding} onClick={() => onAdding(!adding)}>
              <Icon name="plus" />Add a scene after</button>
            <button type="button" className="btn btn-small btn-quiet" disabled={off} onClick={onDelete}>
              <Icon name="trash" />Delete</button>
          </div>
        )}
        {adding && (
          <AddScene label={`Words of the new scene after scene ${scene.n}`} off={off} onClose={closeAdd}
            onAdd={async (narration) => !!(await run(() => shorts.addScene(v.id, { after: scene.id, narration }),
              `A new scene was added after scene ${scene.n}.`))} />
        )}
      </div>
    </li>
  );
}

/** Voice, look and music for the whole short: each change makes again only what it touches. */
function ShortChoices({ v, s, opts, problem, onRetry, off, run, send }: {
  v: Video; s: ShortView; opts: ShortOptions | null; problem: string; onRetry: () => void; off: boolean; run: Run; send: Send;
}) {
  const [look, setLook] = useState<ShortLook | null>(null);
  const ids = useId();
  if (!opts) {
    return problem ? (
      <div className="stack-2">
        <p className="error-text"><Icon name="alert" className="sm" />The choices could not be loaded. {problem}</p>
        <button type="button" className="btn btn-small" onClick={onRetry}><Icon name="refresh" />Try again</button>
      </div>
    ) : <p className="small muted">Loading the choices…</p>;
  }
  const put = (body: ShortOptionsPatch) => run(() => shorts.setOptions(v.id, body), "Saved. ClipForge makes again what this changes.");
  const video = opts.engines.video;
  return (
    <div className="short-choices">
      <div className="field short-voice-field">
        <label htmlFor={`${ids}-voice`}>Voice</label>
        <div className="short-voice-row">
          <select id={`${ids}-voice`} value={s.voice} disabled={off} onChange={(e) => void put({ voice: e.target.value })}>
            {!opts.voices.some((x) => x.id === s.voice) && <option value={s.voice}>The voice chosen before</option>}
            {opts.voices.map((x) => <option key={x.id} value={x.id}>{x.about ? `${x.name} · ${x.about}` : x.name}</option>)}
          </select>
          <HearButton voice={s.voice} speed={s.speed} small />
        </div>
      </div>
      <label className="field"><span>Speed</span>
        <select value={String(s.speed)} disabled={off} onChange={(e) => void put({ speed: Number(e.target.value) })}>
          {!opts.speeds.some((x) => x.value === s.speed) && <option value={String(s.speed)}>{s.speed}×</option>}
          {opts.speeds.map((x) => <option key={x.value} value={String(x.value)}>{x.label}</option>)}
        </select></label>
      <label className="field"><span>Look</span>
        <select value={s.look} disabled={off} onChange={(e) => setLook(opts.looks.find((l) => l.id === e.target.value) || null)}>
          {!opts.looks.some((l) => l.id === s.look) && <option value={s.look}>The look chosen before</option>}
          {opts.looks.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select></label>
      <label className="field"><span>Music</span>
        <select value={s.music} disabled={off} onChange={(e) => void put({ music: e.target.value })}>
          {!opts.music.some((m) => m.id === s.music) && <option value={s.music}>{s.music}</option>}
          {opts.music.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select></label>
      <label className="field"><span>Captions</span>
        <select value={s.captions} disabled={off} onChange={(e) => void put({ captions: e.target.value })}>
          {!opts.captions.some((c) => c.id === s.captions) && <option value={s.captions}>{s.captions || "The look's own style"}</option>}
          {opts.captions.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
        </select></label>
      <label className="field"><span>Motion</span>
        <select value={s.motion} disabled={off} onChange={(e) => void put({ motion: e.target.value === "animate" ? "animate" : "camera" })}>
          <option value="camera">Gentle camera moves (quick)</option>
          <option value="animate" disabled={!video.ready && s.motion !== "animate"}>Animate the pictures with the video maker (slow)</option>
        </select>
        {!video.ready && video.why && <span className="hint">{video.why}</span>}</label>
      {look && (
        <ConfirmDialog title={`Use the ${look.name} look?`} confirmLabel="Change the look" onClose={() => setLook(null)}
          onConfirm={() => send(() => shorts.setOptions(v.id, { look: look.id }), `The look is now ${look.name}. ClipForge is making new pictures.`)}>
          <p className="muted">New pictures for every scene; your own pictures stay.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

/** How this short was made: who wrote it, what it read, which makers drew, spoke and moved it, and ClipForge's notes. */
function MadeHow({ s, scenes, opts }: { s: ShortView; scenes: ShortScene[]; opts: ShortOptions | null }) {
  const used = s.writer.used;
  const count = (src: string) => scenes.filter((x) => x.picture.source === src).length;
  const drawn = scenes.find((x) => x.picture.source === "engine")?.picture.engine || s.engines.image.engine || "the picture maker";
  const pictureParts = [
    count("engine") ? `${count("engine")} made by ${drawn}` : "",
    count("card") ? `${plural(count("card"), "designed card")} with the key words` : "",
    count("upload") ? `${count("upload")} of your own` : "",
  ].filter(Boolean);
  const pictures = pictureParts.length ? listWords(pictureParts)
    : s.engines.image.ready ? `${s.engines.image.engine || "The picture maker"} on this computer`
      : "Designed cards with the key words (no picture maker is set up)";
  const spoken = scenes.filter((x) => x.voice.engine);
  const names = [...new Set(spoken.map((x) => x.voice.voice).filter(Boolean))].slice(0, 3);
  // the voices that spoke the scenes; before any scene is made, the voice the short asks for
  const byEngine = spoken.length ? spoken.some((x) => x.voice.engine === "engine")
    : s.engines.voice.ready && (s.voice === "auto" || s.voice.startsWith("engine:"));
  const voice = `${byEngine ? s.engines.voice.engine || "The voice maker on this computer" : "This computer's own voice"}${
    names.length ? `: ${names.join(", ")}` : ""}`;
  const exact = scenes.filter((x) => x.voice.timing === "engine" || x.voice.timing === "listened").length;
  const guessed = scenes.filter((x) => x.voice.timing === "estimated").length;
  const timing = !exact && !guessed ? "" : !guessed ? "Exact" : !exact ? "Estimated from the sound"
    : `Exact in ${plural(exact, "scene")}, estimated from the sound in ${guessed}`;
  const motion = s.motion === "camera" ? "Gentle camera moves"
    : s.engines.video.ready ? `Animated by ${s.engines.video.engine || "the video maker"}`
      : `Gentle camera moves${s.engines.video.why ? `. ${s.engines.video.why}` : ""}`;
  const tone = opts?.tones.find((t) => t.id === s.tone)?.label;
  const length = opts?.lengths.find((l) => l.id === s.length)?.label;
  const script = s.mode === "write"
    ? `Written by ClipForge AI${used?.model ? ` (${used.model})` : ""}${s.topic ? ` from the topic “${s.topic}”` : ""}`
    : `Your own script. ${used ? `ClipForge AI${used.model ? ` (${used.model})` : ""} wrote the picture ideas`
      : "Each picture idea comes from the scene's own words or your [Visual: …] lines"}`;
  return (
    <div className="stack-3">
      <dl className="kv short-made">
        <dt>Script</dt><dd>{script}.</dd>
        {s.mode === "write" && (tone || length || s.audience) && <>
          <dt>Asked for</dt><dd>{[tone && `${tone} tone`, length, s.audience && `for ${s.audience}`].filter(Boolean).join(" · ")}</dd>
        </>}
        {s.title && <><dt>Title</dt><dd>{s.title}</dd></>}
        {s.character && <><dt>In every picture</dt><dd>{s.character}</dd></>}
        {used && used.memories > 0 && <>
          <dt>Your memories</dt><dd>{plural(used.memories, "memory", "memories")} used. <a className="textlink" href="#/brain/memory">See them in Brain</a></dd>
        </>}
        {used && used.knowhow.length > 0 && <><dt>Know-how</dt><dd>{used.knowhow.join(", ")}</dd></>}
        <dt>Pictures</dt><dd>{pictures}</dd>
        <dt>Voice</dt><dd>{voice}</dd>
        <dt>Motion</dt><dd>{motion}</dd>
        {timing && <><dt>Word timing</dt><dd>{timing}</dd></>}
      </dl>
      {count("card") > 0 && !s.engines.image.ready && s.engines.available && opts && (
        <p className="small muted">Designed cards are placeholders, not illustrations. <a className="textlink" href={opts.links.makers}>Set up a picture maker</a> to draw real pictures.</p>
      )}
      {s.notes.length > 0 && <ul className="small short-notes">{s.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
    </div>
  );
}

/**
 * The Scenes panel of an animated short on the editor page (docs/clipforge/ANIMATED_SHORTS.md): each scene's words and
 * picture and where it is, changes to any scene, the short's voice, look and music, and how it was made. It sends its
 * own changes and hands the video each one answers with to the page.
 */
export function ShortScenes({ v, busy, onVideo }: { v: Video; busy: boolean; onVideo: (v: Video) => void }) {
  const s = v.short;
  const [opts, setOpts] = useState<ShortOptions | null>(null);
  const [optsProblem, setOptsProblem] = useState("");
  const [pending, setPending] = useState(0);
  const [adding, setAdding] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ShortScene | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const head = useRef<HTMLHeadingElement>(null);
  const refocus = useRef(false);
  const headId = useId();
  const loadOptions = useCallback(() => {
    setOptsProblem("");
    shorts.options().then(setOpts).catch((e) => setOptsProblem(errorText(e)));
  }, []);
  useEffect(() => loadOptions(), [loadOptions]);
  useEffect(() => {
    // after a scene is deleted (its Delete button is gone), the panel's heading takes the focus
    if (deleting || !refocus.current) return;
    refocus.current = false;
    head.current?.focus();
  }, [deleting]);
  // One change at a time, in the order they were made (words saved when leaving a box can follow each other).
  const send = useCallback<Send>((call, said) => {
    setPending((n) => n + 1);
    const done = queue.current.then(call).then((nv) => {
      onVideo(nv);
      const note = (nv as Video & { note?: string }).note;
      if (note) toast(note);
      else if (said) announce(said);
      return nv;
    }).finally(() => setPending((n) => n - 1));
    queue.current = done.catch(() => undefined);
    return done;
  }, [onVideo]);
  const run = useCallback<Run>((call, said) => send(call, said).catch((e) => {
    toast(errorText(e), true);
    return null;
  }), [send]);
  if (!s) return null;

  const off = busy || pending > 0 || s.stage === "writing";
  const scenes = [...s.scenes].sort((a, b) => a.n - b.n);
  const planClips = (v.plan?.clips || []) as SceneClip[];
  const partsOf = (id: string) => planClips.flatMap((c, i) => (c.id === id || c.scene_id === id ? [i] : []));
  const placed = scenes.map((sc) => ({ id: sc.id, parts: partsOf(sc.id) })).filter((x) => x.parts.length);
  const movesOf = (id: string): Moves | null => {
    const k = placed.findIndex((x) => x.id === id);
    if (k < 0) return null;
    const own = planClips.findIndex((c) => c.id === id);
    const at = own >= 0 ? own : placed[k].parts[0];
    const before = placed[k - 1]?.parts[0];
    const next = placed[k + 1]?.parts;
    const after = next ? next[next.length - 1] : undefined;
    return { clip: planClips[at].id, earlier: before !== undefined && before < at ? before : null,
      later: after !== undefined && after > at ? after : null };
  };
  const early = s.stage === "review" || s.stage === "writing";
  const failed = scenes.filter((x) => x.status === "failed").length;
  const [word, tone, icon] = stageWords(s);
  const last = scenes[scenes.length - 1];
  const makeIt = () => void run(() => shorts.make(v.id), "ClipForge is making the short.");

  return (
    <section className="panel short-scenes" aria-labelledby={headId}>
      <div className="panel-head">
        <h2 id={headId} ref={head} tabIndex={-1}>Scenes ({scenes.length})</h2>
        <div className="short-state">
          <Pill tone={tone} icon={icon}>{word}</Pill>
          {failed > 0 && s.stage !== "failed" && <Pill tone="warn">{plural(failed, "scene")} did not work</Pill>}
          {s.seconds > 0 && <span className="small muted tnum">{lengthWords(s.seconds)}</span>}
        </div>
      </div>
      {s.stage === "writing" && (
        <p className="short-writing" role="status"><span className="inline-spinner" aria-hidden="true" />ClipForge AI is writing the script…</p>
      )}
      {s.stage === "review" && (
        <Banner tone="info" icon="edit" title="Check the script"
          actions={<button type="button" className="btn btn-primary" disabled={off} onClick={makeIt}><Icon name="spark" />Make the short</button>}>
          Change any words, then press Make the short.
        </Banner>
      )}
      {s.stage === "failed" && (
        <Banner tone="bad" title="The short was not made"
          actions={<button type="button" className="btn btn-small" disabled={off} onClick={makeIt}><Icon name="refresh" />Try again</button>}>
          {s.message || "Something stopped it before it finished."}
        </Banner>
      )}
      {s.stage === "stopped" && (
        <Banner tone="warn" title="Stopped"
          actions={<button type="button" className="btn btn-small" disabled={off} onClick={makeIt}><Icon name="play" />Make the short</button>}>
          Press Make the short to go on where it stopped.
        </Banner>
      )}
      {s.stage === "making" && s.progress.total > 0 && (
        <ProgressBar value={s.progress.done / s.progress.total} label={`${s.progress.done} of ${s.progress.total} scenes made`} />
      )}
      {s.stage === "ready" && (s.cards_to_swap ?? 0) > 0 && (
        <Banner tone="info" title="A picture maker is ready"
          actions={<button type="button" className="btn btn-small" disabled={off} onClick={() => void run(() => shorts.make(v.id),
            "ClipForge is drawing real pictures for the cards.")}><Icon name="spark" />Draw real pictures</button>}>
          {plural(s.cards_to_swap ?? 0, "scene")} {s.cards_to_swap === 1 ? "shows" : "show"} a designed card. Draw real pictures swaps {s.cards_to_swap === 1 ? "it" : "them"} for pictures made on this computer.
        </Banner>
      )}
      {s.message && (s.stage === "making" || s.stage === "ready") && <p className="small muted">{s.message}</p>}
      {scenes.length > 0 && s.stage !== "writing" && (
        <p className="small muted">{early ? "Changes to the words are saved when you leave the box."
          : "Changes are saved when you leave the box, and ClipForge makes that scene again."}</p>
      )}
      {scenes.length > 0 && (
        <ol className="scene-list">
          {scenes.map((sc) => (
            <SceneRow key={sc.id} scene={sc} v={v} s={s} moves={movesOf(sc.id)} off={off} run={run}
              adding={adding === sc.id} onAdding={(on) => setAdding(on ? sc.id : null)} onDelete={() => setDeleting(sc)} />
          ))}
        </ol>
      )}
      {scenes.length === 0 && s.stage !== "writing" && <p className="small muted">No scenes yet. Add the first one.</p>}
      {s.stage !== "writing" && (
        <div className="scene-actions">
          <button type="button" className="btn btn-small" aria-expanded={adding === "end"}
            onClick={() => setAdding(adding === "end" ? null : "end")}><Icon name="plus" />Add a scene</button>
        </div>
      )}
      {adding === "end" && (
        <AddScene label={last ? `Words of the new scene at the end` : "Words of the first scene"} off={off}
          onClose={() => setAdding(null)}
          onAdd={async (narration) => !!(await run(() => shorts.addScene(v.id, { after: last?.id ?? null, narration }),
            "A new scene was added at the end."))} />
      )}
      <Disclosure summary="Voice, look and music">
        <ShortChoices v={v} s={s} opts={opts} problem={optsProblem} onRetry={loadOptions} off={off} run={run} send={send} />
      </Disclosure>
      <Disclosure summary="How this short was made">
        <MadeHow s={s} scenes={scenes} opts={opts} />
      </Disclosure>
      {deleting && (
        <ConfirmDialog title={`Delete scene ${deleting.n}?`} confirmLabel="Delete the scene" danger onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await send(() => shorts.deleteScene(v.id, deleting.id), `Scene ${deleting.n} was deleted.`);
            refocus.current = true;
          }}>
          <p className="muted">Its words, voice and picture are taken out of the short.</p>
          {deleting.narration && <blockquote className="scene-quote">“{deleting.narration.length > 160
            ? `${deleting.narration.slice(0, 157)}…` : deleting.narration}”</blockquote>}
        </ConfirmDialog>
      )}
    </section>
  );
}
