import { ReactElement, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  alignWords, api, Clip, ClipEdit, ClipVersion, errorText, fmtPrecise, Project, Settings, versionVideoUrl, Word,
} from "../api";
import { at, plural } from "../format";
import { editHash, TimeField, Timeline } from "../components/editorParts";
import { ExportDialog, useClipPosts } from "../components/libParts";
import { hasPostText, PostDraft, postPatch, PostTextFields, RewritePostDialog } from "../components/postpack";
import {
  announce, Banner, ConfirmDialog, EmptyState, Icon, LoadingPage, PageHead, Pill, ProgressBar, Segmented, StylePicker,
  TabPanel, Tabs, Toggle, toast, TRACKING,
} from "../components/ui";
import { VersionsCard } from "../components/versions";
import { useLeaveGuard } from "../router";
import "./editor.css";

type Group = "trim" | "captions" | "layout" | "audio" | "post";
type Key = Exclude<keyof ClipEdit, "caption_words">;
type Words = Awaited<ReturnType<typeof api.clipWords>>;

const GROUPS: { id: Group; label: string; what: string }[] = [
  { id: "trim", label: "Trim", what: "the trim" },
  { id: "captions", label: "Captions", what: "the captions or hook" },
  { id: "layout", label: "Layout", what: "the layout" },
  { id: "audio", label: "Audio", what: "the audio" },
  { id: "post", label: "Post text", what: "the post text" },
];
const KEYS: Record<Exclude<Group, "post">, Key[]> = {
  trim: ["start", "end"],
  captions: ["captions_enabled", "caption_style", "caption_position", "caption_size", "caption_emphasis",
    "highlight_words", "highlight_color", "hook", "hook_overlay", "hook_seconds"],
  layout: ["tracking", "crop_x", "layout", "zoom", "auto_zoom"],
  audio: ["gain_db", "normalize_audio", "silence", "remove_fillers", "speed"],
};
const ALL_KEYS = Object.values(KEYS).flat();
// What the renderer uses when neither the clip, the video's options nor Settings say otherwise.
const FALLBACK: Partial<Record<Key, unknown>> = {
  tracking: "auto", crop_x: 0.5, layout: "fill", zoom: 1, auto_zoom: true,
  captions_enabled: true, caption_style: "bold", caption_position: "bottom", caption_size: 1, caption_emphasis: false,
  highlight_words: true, highlight_color: "", hook_overlay: true, hook_seconds: 3,
  gain_db: 0, normalize_audio: true, silence: "light", remove_fillers: true, speed: 1,
};
const TITLE_MAX = 100;
const CAPTION_MAX = 2200;

const isBusy = (c: Clip) => c.status === "queued" || c.status === "rendering";
const same = (a: unknown, b: unknown) =>
  typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-6 : a === b;
const norm = (s: string) => s.split(/\s+/).filter(Boolean).join(" ");
const andList = (xs: string[]) =>
  (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const captionOf = (w: Words) =>
  (w.caption_words || w.words.filter((x) => x.end > w.start && x.start < w.end)).map((x) => x.w).join(" ");
/** When a render was made, from its artifact record (older renders don't have one). */
const renderedAt = (info?: Record<string, any>): number | null =>
  typeof info?.artifact?.created_at === "number" ? info.artifact.created_at : null;

function Check({ label, on, onChange, disabled }: {
  label: string; on: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <label className="choice">
      <input type="checkbox" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="small">{label}</span>
    </label>
  );
}

export default function ClipEditor({ id }: { id: string }) {
  const [clip, setClip] = useState<Clip | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [settings, setSettings] = useState<Settings>({});
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [words, setWords] = useState<Word[]>([]);
  const [wordsOk, setWordsOk] = useState(false);
  // The unsaved state: the edit, the caption text and the post text.
  const [draft, setDraft] = useState<ClipEdit>({});
  const [captionBase, setCaptionBase] = useState("");
  const [captionText, setCaptionText] = useState("");
  const [postDraft, setPostDraft] = useState<PostDraft>({});
  const [postKey, setPostKey] = useState(0);
  const [customHook, setCustomHook] = useState("");

  const [tab, setTab] = useState<Group>("trim");
  const [view, setView] = useState<"clip" | "source">("clip");
  const [shown, setShown] = useState<ClipVersion | null>(null); // a version in the player; null is the clip itself
  const [activeVersion, setActiveVersion] = useState<ClipVersion | undefined>();
  const [clickMode, setClickMode] = useState<"start" | "end">("start");
  const [t, setT] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  // Why the player can't play: "format" when this browser can't decode the file, "load" when it couldn't be fetched.
  const [videoFailed, setVideoFailed] = useState<"" | "format" | "load">("");

  const [saving, setSaving] = useState(false);
  const [hashState, setHashState] = useState<"same" | "differs" | "unknown">("unknown");
  const [savedHere, setSavedHere] = useState(false);
  const [justRendered, setJustRendered] = useState(false);
  const [dialog, setDialog] = useState<"" | "discard" | "again" | "rewrite" | "export">("");
  const [pollTick, setPollTick] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const uid = useId();
  const posts = useClipPosts([id]);

  useEffect(() => {
    let alive = true;
    setLoadError("");
    (async () => {
      try {
        const c = await api.clip(id);
        const [p, s, w] = await Promise.all([
          api.project(c.project_id), api.settings().catch(() => ({} as Settings)), api.clipWords(id).catch(() => null),
        ]);
        if (!alive) return;
        setClip(c);
        setProject(p);
        setSettings(s);
        setDraft({ ...(c.edit || {}) });
        setPostDraft(c.post || {});
        setView(c.has_video || isBusy(c) ? "clip" : "source");
        setWordsOk(!!w);
        if (w) {
          setWords(w.words);
          setCaptionBase(captionOf(w));
          setCaptionText(captionOf(w));
        }
      } catch (e) {
        if (alive) setLoadError(errorText(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [id, attempt]);

  // While the clip renders, follow its real progress.
  const busy = !!clip && isBusy(clip);
  useEffect(() => {
    if (!busy) return;
    const timer = setTimeout(() => {
      api.clip(id).then(setClip).catch(() => setPollTick((n) => n + 1));
    }, 1200);
    return () => clearTimeout(timer);
  }, [busy, clip, id, pollTick]);

  const lastStatus = useRef("");
  useEffect(() => {
    if (!clip) return;
    const was = lastStatus.current;
    lastStatus.current = clip.status;
    if (was !== "queued" && was !== "rendering") return;
    if (clip.status === "ready") {
      setJustRendered(true);
      setSavedHere(false);
      setShown(null);
      toast("Rendered. The new video gets its own final check before it is posted.");
    } else if (clip.status === "error") {
      announce("The render didn't finish. The reason is at the top of the page.");
    }
  }, [clip?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Is the saved edit in the video? Compared with the fingerprint the renderer stored, never guessed.
  const renderedHash: string | undefined = clip?.render_info?.edit_hash;
  const savedJson = JSON.stringify(clip?.edit || {});
  useEffect(() => {
    if (!clip || !renderedHash) {
      setHashState("unknown");
      return;
    }
    let alive = true;
    editHash((clip.edit || {}) as Record<string, unknown>).then((h) => {
      if (alive) setHashState(h === null ? "unknown" : h === renderedHash ? "same" : "differs");
    });
    return () => {
      alive = false;
    };
  }, [savedJson, renderedHash]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------ effective values and what changed
  const opts = (project?.options || {}) as Record<string, unknown>;
  const saved = (clip?.edit || {}) as Record<string, unknown>;
  const d = draft as Record<string, unknown>;
  const base = (k: Key): unknown =>
    k === "start" ? clip?.start : k === "end" ? clip?.end : k === "hook" ? clip?.hook
      : opts[k] ?? settings[k] ?? FALLBACK[k];
  const eff = (k: Key) => d[k] ?? base(k);
  const num = (k: Key) => Number(eff(k) ?? 0);
  const bool = (k: Key) => !!eff(k);
  const str = (k: Key) => String(eff(k) ?? "");
  // A change counts only when the value the renderer would use differs, so setting a default again isn't a change.
  const changed = (k: Key) => !same(eff(k), saved[k] ?? base(k));

  const captionDirty = wordsOk && norm(captionText) !== norm(captionBase);
  const postDirty = !!clip && JSON.stringify(postPatch(postDraft)) !== JSON.stringify(postPatch(clip.post || {}));
  const dirty = GROUPS.filter((g) =>
    g.id === "post" ? postDirty : KEYS[g.id].some(changed) || (g.id === "captions" && captionDirty));
  const dirtyIds = new Set(dirty.map((g) => g.id));
  const videoDirty = dirty.some((g) => g.id !== "post");
  const what = andList(dirty.map((g) => g.what));

  // Leaving with unsaved changes (a link, Back, closing the window) asks first; the router shows the question.
  const saveRef = useRef<(render: boolean) => Promise<boolean>>(async () => false);
  const discardRef = useRef<() => void>(() => undefined);
  const guard = useMemo(
    () => (what ? { what, save: () => saveRef.current(false), discard: () => discardRef.current() } : null),
    [what],
  );
  useLeaveGuard(guard);

  // The clip's own file is keyed by its render time, so saving (which changes clip.version) doesn't reload it.
  const src = !clip || !project ? "" : view === "source" ? `/api/projects/${project.id}/source`
    : shown ? versionVideoUrl(clip, shown)
      : `/api/clips/${clip.id}/video?v=${renderedAt(clip.render_info) ?? clip.version}`;
  useEffect(() => {
    setVideoFailed("");
    setPlaying(false);
    setT(null);
  }, [src]);

  if (loadError) {
    return (
      <div className="page">
        <PageHead crumbs={[{ label: "Library", href: "#/library" }, { label: "Edit clip" }]} kind="Clip"
          title="This clip isn't in your library" />
        <EmptyState icon="film" title="Nothing to edit" actions={<>
          <a className="btn" href="#/library"><Icon name="library" />Open the Library</a>
          <button type="button" className="btn" onClick={() => setAttempt((n) => n + 1)}>
            <Icon name="refresh" />Try again
          </button>
        </>}>
          <p>ClipFoundry answered: {loadError}. The clip may have been deleted, or its video's clips made again.</p>
        </EmptyState>
      </div>
    );
  }
  if (!clip || !project) return <LoadingPage label="Loading the clip" />;

  // ------------------------------------------------------------ trim
  const start = num("start");
  const end = num("end");
  const savedStart = Number(saved.start ?? clip.start);
  const savedEnd = Number(saved.end ?? clip.end);
  const dur = project.duration > 0 ? project.duration : Number.MAX_SAFE_INTEGER;
  const lo = Math.max(0, Math.min(savedStart - 10, start));
  const hi = Math.min(dur, Math.max(savedEnd + 10, end));
  const trimChanged = changed("start") || changed("end");
  const canReset = !same(start, clip.start) || !same(end, clip.end);

  const set = (patch: Partial<ClipEdit>) => setDraft((x) => ({ ...x, ...patch }));
  const setTrim = (s: number, e: number) => {
    s = Math.max(0, Math.min(s, dur - 1));
    e = Math.max(s + 1, Math.min(e, dur));
    set({ start: +s.toFixed(2), end: +e.toFixed(2) });
    if (view === "source" && videoRef.current) videoRef.current.currentTime = s;
  };
  const onWord = (w: Word) => {
    if (clickMode === "start") setTrim(Math.max(0, w.start - 0.12), Math.max(end, w.start + 1.5));
    else setTrim(Math.min(start, w.end - 1.5), w.end + 0.3);
    announce(`${clickMode === "start" ? "Start" : "End"} set at “${w.w}”`);
  };
  const resetTrim = () => setDraft((x) => {
    const n = { ...x };
    delete n.start;
    delete n.end;
    return n;
  });

  // ------------------------------------------------------------ save, render, discard
  /** Saves what changed, and renders only when asked. Throws with a reason, so a dialog can stay open and say it. */
  const persist = async (render: boolean) => {
    if (busy) throw new Error("Wait until the render finishes, then save.");
    if (postDirty && (postDraft.title || "").length > TITLE_MAX) {
      setTab("post");
      throw new Error(`The title is longer than ${TITLE_MAX} characters. Shorten it, then save.`);
    }
    if (postDirty && (postDraft.caption || "").length > CAPTION_MAX) {
      setTab("post");
      throw new Error("The caption is longer than 2,200 characters. Shorten it, then save.");
    }
    const edit: Record<string, unknown> = {};
    for (const k of ALL_KEYS) if (changed(k)) edit[k] = d[k] === undefined ? null : d[k]; // null removes a key
    if (captionDirty) {
      const inRange = words.filter((w) => w.end > start && w.start < end);
      const plain = inRange.map((w) => w.w).join(" ");
      edit.caption_words = norm(captionText) !== norm(plain) ? alignWords(inRange, captionText) : null;
    } else if (trimChanged && saved.caption_words) {
      edit.caption_words = null; // the fixes were timed to the old range
    }
    const body: Record<string, unknown> = {};
    if (Object.keys(edit).length) body.edit = edit;
    if (captionDirty) body.caption_text = captionText;
    if (postDirty) body.post = postPatch(postDraft);

    setSaving(true);
    try {
      if (Object.keys(body).length) {
        const c = await api.patchClip(clip.id, body);
        setClip(c);
        setDraft({ ...(c.edit || {}) });
        setPostDraft(c.post || {});
        setPostKey((n) => n + 1);
        if (body.edit) {
          setSavedHere(true);
          setJustRendered(false);
          // The caption text follows the saved range, so the words are read again.
          const w = await api.clipWords(clip.id).catch(() => null);
          if (w) {
            setWords(w.words);
            setCaptionBase(captionOf(w));
            setCaptionText(captionOf(w));
          } else {
            setCaptionBase(captionText);
          }
        }
      }
      if (render) {
        const c = await api.renderClip(clip.id);
        setClip(c);
        setShown(null);
        setView("clip");
        setJustRendered(false);
        toast(body.edit || body.post ? "Saved. Rendering the clip…" : "Rendering the clip…");
      } else if (body.edit) {
        toast("Saved. The video doesn't change until you render.");
      } else if (body.post) {
        toast("Post text saved");
      }
    } finally {
      setSaving(false);
    }
  };
  const save = async (render: boolean) => {
    try {
      await persist(render);
      return true;
    } catch (e) {
      toast(errorText(e), true);
      return false;
    }
  };
  const discard = () => {
    setDraft({ ...(clip.edit || {}) });
    setCaptionText(captionBase);
    setPostDraft(clip.post || {});
    setPostKey((n) => n + 1);
    setCustomHook("");
  };
  saveRef.current = save;
  discardRef.current = discard;

  const renderOnly = async () => {
    try {
      setClip(await api.renderClip(clip.id));
      setShown(null);
      setView("clip");
      toast("Rendering the clip…");
    } catch (e) {
      toast(errorText(e), true);
    }
  };
  const takeHook = (h: string) => {
    set({ hook: h, hook_overlay: true });
    setTab("captions");
    toast("Hook set. Save and render to put it in the video.");
  };
  const useOwnHook = () => {
    if (!customHook.trim()) return;
    set({ hook: customHook.trim() });
    setCustomHook("");
  };

  // ------------------------------------------------------------ what the save bar says
  const clipAt = renderedAt(clip.render_info);
  const lastRender = clipAt ? `the render from ${at(clipAt)}` : "the earlier render";
  const savedNotRendered = !busy && clip.has_video
    && (hashState === "differs" || (hashState === "unknown" && savedHere));
  const needsRender = !busy && (clip.status === "error" || !clip.has_video || savedNotRendered);
  const pct = Math.round((clip.progress || 0) * 100);
  const renderWord = clip.status === "queued" ? "Waiting to render…" : `Rendering… ${pct}%`;
  const changes = `Unsaved changes: ${dirty.map((g) => g.label).join(", ")}`;
  const status = busy ? (dirty.length ? `${renderWord} ${changes}` : renderWord)
    : dirty.length ? changes
      : clip.status === "error" ? "The last render didn't finish. Your saved edits are kept."
        : !clip.has_video ? "Saved. Not rendered yet."
          : savedNotRendered ? `Saved, not rendered yet. The video is still ${lastRender}.`
            : justRendered ? "Rendered just now. It gets a new final check before it is posted."
              : clipAt ? `No changes. The video is the render from ${at(clipAt)}.` : "No changes.";
  const approved = (posts?.get(clip.id) || []).filter((x) => x.status === "approved" && x.approval_valid).length;
  const approvalLine = `Approved posts that use the new video then need your OK again${
    approved ? ` (this clip has ${plural(approved, "approved post")})` : ""}.`;
  const note = `${!videoDirty && postDirty ? "Post text isn't part of the video, so it doesn't need a render. " : ""}`
    + "Saving keeps your edits and doesn't render. Rendering makes a new video file, which gets a new final check. "
    + approvalLine;
  const renderDirect = videoDirty || needsRender;
  const renderLabel = renderDirect ? (dirty.length ? "Save and render" : "Render")
    : dirty.length ? "Save and render…" : "Render again…";

  // ------------------------------------------------------------ the player
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (!v.paused) {
      v.pause();
      return;
    }
    if (view === "source" && (v.currentTime < start - 0.05 || v.currentTime >= end - 0.05)) v.currentTime = start;
    v.play().catch(() => toast("This video can't be played here.", true));
  };
  const shownLabel = shown ? shown.label : "Original";
  const shownAt = shown ? renderedAt(shown.render_info) : clipAt;
  const badge = view === "source" ? "Source" : `${shownLabel}${shownAt ? ` · rendered ${at(shownAt)}` : ""}`;
  const usedElsewhere = activeVersion && activeVersion.id && activeVersion.id !== (shown?.id ?? "")
    ? ` Export and posts use “${activeVersion.label}”.` : "";
  const playerNote = view === "source"
    ? "Shows the source with your current start and end. Captions and layout appear after rendering."
    : busy ? "The new video shows here when the render finishes."
      : (videoDirty || savedNotRendered) && !shown
        ? `Shows the last render. Your changes appear after you render.${usedElsewhere}`
        : `Shows ${shown ? `the “${shown.label}” version` : "the clip as last rendered"}.${usedElsewhere}`;
  const timeText = view === "source"
    ? `${fmtPrecise(Math.max(0, (t ?? start) - start))} / ${fmtPrecise(end - start)}`
    : `${fmtPrecise(t ?? 0)} / ${fmtPrecise(shown?.duration || clip.duration || 0)}`;
  const showVideo = !videoFailed && (view === "source" || !!shown || (!busy && clip.has_video));
  const nowWord = view === "source" && t !== null ? words.findIndex((w) => t >= w.start && t < w.end) : -1;

  // ------------------------------------------------------------ the groups
  const hookList = [...new Set([clip.hook, ...(clip.hooks_alt || [])].filter(Boolean))];
  const currentHook = str("hook");
  const hookOptions = currentHook && !hookList.includes(currentHook) ? [...hookList, currentHook] : hookList;
  const ri = clip.render_info || {};
  const sizePct = Math.round(num("caption_size") * 100);
  const gain = num("gain_db");

  const panels: Record<Group, ReactElement> = {
    trim: (
      <>
        <p className="small muted">Change where the clip starts and ends on the timeline, or type exact times.</p>
        <div className="row wrap top">
          <TimeField label="Start" value={start} onChange={(v) => setTrim(v, end)} />
          <TimeField label="End" value={end} onChange={(v) => setTrim(start, v)} />
        </div>
        <p className="small tnum">
          Length: <b>{(end - start).toFixed(1)} s</b>
          {trimChanged && <span className="faint"> (saved: {(savedEnd - savedStart).toFixed(1)} s)</span>}
        </p>
        <p className="hint">
          ClipFoundry suggested {fmtPrecise(clip.start)} to {fmtPrecise(clip.end)}. Silence cleanup, filler cuts and
          pacing (in Audio) can make the video shorter than this.
        </p>
      </>
    ),
    captions: (
      <>
        <Toggle on={bool("captions_enabled")} onChange={(v) => set({ captions_enabled: v })}
          label="Burn captions into the video" />
        <div className="field">
          <span className="label">Caption style</span>
          <StylePicker value={str("caption_style")} onChange={(v) => set({ caption_style: v })} />
        </div>
        <div className="field">
          <span className="label" id={`${uid}-pos`}>Position</span>
          <Segmented labelledBy={`${uid}-pos`} value={str("caption_position")}
            onChange={(v) => set({ caption_position: v })}
            options={[{ value: "top", label: "Top" }, { value: "middle", label: "Middle" },
              { value: "bottom", label: "Bottom" }]} />
        </div>
        <div className="field">
          <label htmlFor={`${uid}-size`}>Size <span className="faint tnum">{sizePct}%</span></label>
          <input id={`${uid}-size`} type="range" min={0.6} max={1.6} step={0.05} value={num("caption_size")}
            aria-valuetext={`${sizePct}%`} onChange={(e) => set({ caption_size: +e.target.value })} />
        </div>
        <Check label="Key words (numbers, strong words, the clip's keywords) in their own color"
          on={bool("caption_emphasis")} onChange={(v) => set({ caption_emphasis: v })} />
        <Check label="Highlight each word as it is spoken" on={bool("highlight_words")}
          onChange={(v) => set({ highlight_words: v })} />
        <div className="field">
          <label htmlFor={`${uid}-hl`}>Highlight color</label>
          <div className="row wrap color-row">
            <input id={`${uid}-hl`} type="color" value={(str("highlight_color") || "#ffe500").toLowerCase()}
              onChange={(e) => set({ highlight_color: e.target.value })} />
            <span className="small muted">
              {str("highlight_color") ? str("highlight_color").toUpperCase() : "The caption style's own color"}
            </span>
            {d.highlight_color !== undefined && (
              <button type="button" className="btn btn-small btn-quiet"
                onClick={() => set({ highlight_color: undefined })}>
                Use the style's color
              </button>
            )}
          </div>
        </div>
        <div className="field">
          <label htmlFor={`${uid}-ct`}>
            Caption text <span className="hint">fix misheard words; the timing is kept</span>
          </label>
          <textarea id={`${uid}-ct`} rows={5} value={captionText} disabled={!wordsOk}
            onChange={(e) => setCaptionText(e.target.value)} />
          {!wordsOk && (
            <p className="hint">The transcript couldn't be loaded, so the caption text can't be changed now.</p>
          )}
          {trimChanged && captionDirty && (
            <p className="hint">
              You changed the start or end too. Your text is matched to the words inside the new range.
            </p>
          )}
          {trimChanged && !captionDirty && !!saved.caption_words && (
            <p className="hint warn-text">
              Saving the new start or end resets your caption text fixes to the transcript.
            </p>
          )}
        </div>
        <hr className="divider" />
        <h3 style={{ fontSize: "var(--fs-body)" }}>On-screen hook</h3>
        <fieldset className="stack">
          <legend className="sr-only">Hook shown at the start of the video</legend>
          {hookOptions.map((h, i) => (
            <label key={h} className="hook-opt">
              <input type="radio" name={`${uid}-hook`} checked={currentHook === h} onChange={() => set({ hook: h })} />
              <span className="small">
                {h}
                {i === 0 && <> <Pill tone="accent" icon="spark">Suggested</Pill></>}
                {i >= hookList.length && <> <Pill tone="neutral" icon="edit">Yours</Pill></>}
              </span>
            </label>
          ))}
        </fieldset>
        <div className="field">
          <label htmlFor={`${uid}-own`}>Write your own hook</label>
          <div className="row wrap">
            <input id={`${uid}-own`} type="text" maxLength={160} style={{ flex: "1 1 200px", width: "auto" }}
              value={customHook} onChange={(e) => setCustomHook(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && useOwnHook()} />
            <button type="button" className="btn btn-small" disabled={!customHook.trim()} onClick={useOwnHook}>
              Use this hook
            </button>
          </div>
        </div>
        <div className="row wrap hook-row">
          <Check label="Show the hook on screen for" on={bool("hook_overlay")}
            onChange={(v) => set({ hook_overlay: v })} />
          <input type="number" min={1} max={15} step={0.5} aria-label="Seconds the hook shows"
            value={num("hook_seconds")} disabled={!bool("hook_overlay")} onChange={(e) => {
              const n = Number(e.target.value);
              if (e.target.value !== "" && Number.isFinite(n)) set({ hook_seconds: Math.min(15, Math.max(1, n)) });
            }} />
          <span className="small">seconds</span>
        </div>
        <p className="hint">
          Suggested hooks come from the clip's own words and never add facts that aren't in the clip. A hook you
          write is used as you wrote it.
        </p>
      </>
    ),
    layout: (
      <>
        <div className="field">
          <label htmlFor={`${uid}-tr`}>Framing follows</label>
          <select id={`${uid}-tr`} value={str("tracking")} onChange={(e) => set({ tracking: e.target.value })}>
            {[...TRACKING, { value: "manual", label: "A position you choose" }].map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        {str("tracking") === "manual" && (
          <div className="field">
            <label htmlFor={`${uid}-cx`}>
              Horizontal position <span className="faint tnum">{Math.round(num("crop_x") * 100)}% from the left</span>
            </label>
            <input id={`${uid}-cx`} type="range" min={0} max={1} step={0.01} value={num("crop_x")}
              aria-valuetext={`${Math.round(num("crop_x") * 100)}% from the left`}
              onChange={(e) => set({ crop_x: +e.target.value })} />
          </div>
        )}
        <div className="field">
          <span className="label" id={`${uid}-lay`}>Layout</span>
          <Segmented labelledBy={`${uid}-lay`} value={str("layout")} onChange={(v) => set({ layout: v })}
            options={[{ value: "fill", label: "Fill (crop)" }, { value: "fit", label: "Fit (blurred background)" }]} />
        </div>
        <div className="field">
          <label htmlFor={`${uid}-zoom`}>Zoom <span className="faint tnum">{num("zoom").toFixed(2)}×</span></label>
          <input id={`${uid}-zoom`} type="range" min={1} max={2} step={0.05} value={num("zoom")}
            aria-valuetext={`${num("zoom").toFixed(2)} times`} onChange={(e) => set({ zoom: +e.target.value })} />
        </div>
        <Check label="Subtle push-in on sentences with an emphasized word" on={bool("auto_zoom")}
          onChange={(v) => set({ auto_zoom: v })} />
        {ri.mode && (
          <p className="hint">
            Last render: {String(ri.mode)} framing
            {ri.faces ? `, ${plural(Number(ri.faces), "face track")}` : ""}
            {ri.cuts ? `, ${plural(Number(ri.cuts), "scene cut")}` : ", no scene cuts"}.
          </p>
        )}
      </>
    ),
    audio: (
      <>
        <div className="field">
          <label htmlFor={`${uid}-gain`}>
            Volume <span className="faint tnum">{gain > 0 ? "+" : ""}{gain} dB</span>
          </label>
          <input id={`${uid}-gain`} type="range" min={-12} max={12} step={0.5} value={gain}
            aria-valuetext={`${gain > 0 ? "plus " : gain < 0 ? "minus " : ""}${Math.abs(gain)} decibels`}
            onChange={(e) => set({ gain_db: +e.target.value })} />
        </div>
        <Check label="Normalize loudness to −14 LUFS (the social media standard)" on={bool("normalize_audio")}
          onChange={(v) => set({ normalize_audio: v })} />
        <div className="field">
          <span className="label" id={`${uid}-sil`}>Silence cleanup</span>
          <Segmented labelledBy={`${uid}-sil`} value={str("silence")} onChange={(v) => set({ silence: v })}
            options={[{ value: "off", label: "Off" }, { value: "light", label: "Light" },
              { value: "aggressive", label: "Strong" }]} />
        </div>
        <Check label="Cut “um” and “uh” with the pause around them" on={bool("remove_fillers")}
          onChange={(v) => set({ remove_fillers: v })} />
        <div className="field">
          <label htmlFor={`${uid}-speed`}>
            Pacing <span className="faint tnum">{num("speed").toFixed(2)}× (voice pitch unchanged)</span>
          </label>
          <input id={`${uid}-speed`} type="range" min={1} max={1.15} step={0.01} value={num("speed")}
            aria-valuetext={`${num("speed").toFixed(2)} times`} onChange={(e) => set({ speed: +e.target.value })} />
        </div>
        {Number(ri.removed_s) > 0.1 && (
          <p className="hint">
            Last render removed {Number(ri.removed_s)} s of pauses
            {ri.fillers_removed ? ` and ${plural(Number(ri.fillers_removed), "filler word")}` : ""}.
          </p>
        )}
      </>
    ),
    post: (
      <>
        <p className="small muted">
          The title, caption and hashtags used when you post this clip. They aren't part of the video, so changing them
          doesn't need a render.
        </p>
        {hasPostText(postDraft) ? (
          <PostTextFields key={postKey} pkg={postDraft} onUseHook={takeHook}
            onChange={(patch) => setPostDraft((x) => ({ ...x, ...patch }))} />
        ) : (
          <p className="muted small">
            No post text yet. ClipFoundry can write a title, caption, hashtags, a short description, a call to action
            and hook text from this clip's own words.
          </p>
        )}
        <div className="row wrap">
          <button type="button" className="btn btn-small" disabled={saving} onClick={() => setDialog("rewrite")}>
            <Icon name="refresh" />{hasPostText(postDraft) ? "Write new suggestions…" : "Write post text…"}
          </button>
          {postDraft.source && (
            <span className="tiny faint">{postDraft.source}{postDraft.edited ? " · edited" : ""}</span>
          )}
        </div>
      </>
    ),
  };

  return (
    <div className="page clip-editor">
      <PageHead
        crumbs={[
          { label: "Library", href: "#/library" }, { label: project.name, href: `#/project/${project.id}` },
          { label: "Edit clip" },
        ]}
        kind="Clip" title={clip.title}
        sub={<span className="small tnum">
          {(end - start).toFixed(1)} s · from {fmtPrecise(start)} to {fmtPrecise(end)} of the source video ·{" "}
          <span title="An estimate used to rank clips. Not a promise of views.">
            Viral Potential {Math.round(clip.score)} (estimate)
          </span>
        </span>}
        actions={<>
          <button type="button" className="btn" disabled={!clip.has_video} onClick={() => setDialog("export")}>
            <Icon name="download" />Export
          </button>
          <a className="btn" href={`#/publish/${clip.id}`}><Icon name="upload" />Prepare post</a>
        </>}
      />

      {clip.status === "error" && (
        <Banner tone="bad"
          title={clip.error === "Cancelled" ? "The last render was canceled" : "The last render didn't finish"}
          actions={<button type="button" className="btn btn-small" disabled={saving} onClick={renderOnly}>
            <Icon name="refresh" />Try again
          </button>}>
          {clip.error && clip.error !== "Cancelled" && <p className="break">ClipFoundry reported: {clip.error}</p>}
          {clip.has_video && <p>The video below is the last render that worked.</p>}
        </Banner>
      )}

      <div className="editor">
        <div className="stage-area">
          <div className="player-wrap">
            <Segmented label="Preview" value={view} onChange={(v) => setView(v)}
              options={[{ value: "clip", label: "Rendered clip" }, { value: "source", label: "Source range" }]} />
            <div className={`player ${view === "source" ? "wide" : ""}`}>
              {showVideo ? (
                <video key={src} ref={videoRef} src={src} controls playsInline preload="metadata"
                  aria-label={view === "source" ? "Source video" : `Clip preview: ${shownLabel}`}
                  onLoadedMetadata={(e) => {
                    if (view === "source") e.currentTarget.currentTime = start;
                    setT(e.currentTarget.currentTime);
                  }}
                  onTimeUpdate={(e) => {
                    const v = e.currentTarget;
                    setT(v.currentTime);
                    if (view === "source" && !v.paused && v.currentTime >= end) v.pause();
                  }}
                  onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
                  onError={(e) => setVideoFailed(e.currentTarget.error?.code === 4 ? "format" : "load")} />
              ) : view === "clip" && busy ? (
                <div className="player-msg">
                  <Icon name="refresh" />
                  <b>{renderWord}</b>
                  <ProgressBar value={clip.progress || 0} label="Rendering progress" />
                </div>
              ) : videoFailed ? (
                <div className="player-msg">
                  <Icon name="alert" />
                  <b>
                    {videoFailed === "format" ? "This browser can't play this video file."
                      : "The video couldn't be loaded."}
                  </b>
                  <span>
                    {videoFailed === "format"
                      ? (view === "source" ? "The cut can still be set with the timeline and words."
                        : "Use Export to download it and watch it in another player.")
                      : view === "source" ? "The source file may have been moved or deleted."
                        : "The file may have been moved or deleted. Rendering the clip makes it again."}
                  </span>
                </div>
              ) : (
                <div className="player-msg">
                  <Icon name="film" />
                  <b>Not rendered yet</b>
                  <span>Check the cut with “Source range”, then Save and render.</span>
                </div>
              )}
              <span className="badge-version">{badge}</span>
            </div>
            <div className="player-controls">
              <button type="button" className="btn btn-small" disabled={!showVideo} onClick={togglePlay}>
                <Icon name={playing ? "pause" : "play"} />
                {playing ? "Pause" : view === "source" ? "Play the range" : "Play"}
              </button>
              <span className="small tnum">{timeText}</span>
              <span className="tiny faint grow">{playerNote}</span>
            </div>
          </div>

          <Timeline lo={lo} hi={hi} start={start} end={end} words={words} playhead={view === "source" ? t : null}
            nowWord={nowWord} clickMode={clickMode} onClickMode={setClickMode} onTrim={setTrim} onWord={onWord}
            onReset={resetTrim} canReset={canReset} />

          <VersionsCard clip={clip} playing={view === "clip" ? shown?.id ?? "" : undefined}
            onPlay={(v) => {
              setShown(v.id ? v : null);
              setView("clip");
            }}
            onChange={(active, all) => {
              setActiveVersion(active);
              // Keep a shown version only while it still exists with a video (it may be deleted or rendering).
              setShown((s) => (s && all.find((v) => v.id === s.id && v.status === "ready" && v.has_video)) || null);
            }} />
        </div>

        <section className="edit-panel" aria-label="Edit">
          <Tabs label="Edit groups" idPrefix="ed" current={tab} onChange={setTab}
            tabs={GROUPS.map((g) => ({
              id: g.id,
              label: <>{g.label}{dirtyIds.has(g.id) && <>
                <span className="sr-only"> (changed)</span><span className="changed-mark" aria-hidden="true">•</span>
              </>}</>,
            }))} />
          <TabPanel idPrefix="ed" id={tab}>{panels[tab]}</TabPanel>
        </section>
      </div>

      <div className="savebar" role="region" aria-label="Save and render">
        <div className="grow">
          <b className="small">{status}</b>
          <span className="tiny faint">{note}</span>
          <span className="hint savebar-short">Save doesn't render.</span>
        </div>
        <button type="button" className="btn btn-quiet" disabled={!dirty.length || saving}
          onClick={() => setDialog("discard")}>
          Discard changes…
        </button>
        <button type="button" className="btn" disabled={!dirty.length || saving || busy} onClick={() => save(false)}>
          Save
        </button>
        <button type="button" className="btn btn-primary" disabled={saving || busy}
          onClick={() => (renderDirect ? save(true) : setDialog("again"))}>
          <Icon name="refresh" />{renderLabel}
        </button>
      </div>

      {dialog === "discard" && (
        <ConfirmDialog title="Discard your changes?" confirmLabel="Discard changes" danger onClose={() => setDialog("")}
          onConfirm={discard}>
          <p className="muted">
            Your unsaved changes to {what} are lost. The saved clip and its video stay as they are.
          </p>
        </ConfirmDialog>
      )}
      {dialog === "again" && (
        <ConfirmDialog title="Render this clip again?" confirmLabel={dirty.length ? "Save and render" : "Render again"}
          onClose={() => setDialog("")} onConfirm={() => persist(true)}>
          <p className="muted">
            Nothing in the video changed since the last render
            {dirty.length ? " (post text isn't part of the video)" : ""}.
            Rendering again makes a new video file, which gets a new final check.
          </p>
          <p className="small">{approvalLine}</p>
        </ConfirmDialog>
      )}
      {dialog === "rewrite" && (
        <RewritePostDialog clip={clip} edited={!!postDraft.edited || postDirty} onClose={() => setDialog("")}
          onDone={(c) => {
            setClip(c);
            setPostDraft(c.post || {});
            setPostKey((n) => n + 1);
          }} />
      )}
      {dialog === "export" && <ExportDialog clip={clip} onClose={() => setDialog("")} />}
    </div>
  );
}
