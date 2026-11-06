import { useCallback, useEffect, useRef, useState } from "react";
import { errorText, responseError, sendBytes } from "../api";
import { craft, CraftStatus, EditorSession, FilmCraftOpen, FilmCraftStatus, MadeWith, studio, Video } from "../studio";
import { Banner, Disclosure, Icon, Modal, Pill, ProgressBar, toast } from "./ui";

/** What FilmCraft, EffectCraft and the AI did in a rendered version, in a sentence or two. */
export function MadeWithLine({ m }: { m: MadeWith }) {
  const fc = m.filmcraft;
  if (m.fallback) return <span className="small">{m.fallback}</span>;
  if (m.engine !== "filmcraft" || !fc) return <span className="small muted">Made with the built-in editor.</span>;
  if (fc.hand_edited) return <span className="small">Finished by hand in FilmCraft&apos;s editor and rendered by FilmCraft.</span>;
  const shots = fc.shots.map((s) => `${s.what} (${s.app})`).join(", ");
  return (
    <span className="small">Edited and rendered in FilmCraft with {fc.steps} of its tools
      {fc.failed ? `, ${fc.failed} of them did not apply` : ""}{shots ? `. Effect shots: ${shots}` : ""}.
      {fc.ai?.used && <> The AI ({fc.ai.provider}) finished it: {fc.ai.summary || `${fc.ai.steps} more edits`}
        {fc.ai.refused ? ` (${fc.ai.refused} of its suggestions were not allowed)` : ""}.</>}
    </span>
  );
}

type Bridge = {
  importUrl: (url: string, name?: string) => Promise<unknown>;
  openProject: (file: File | string) => Promise<unknown>;
  readFile: (path: string) => Promise<Uint8Array>;
  execute?: (id: string, params?: unknown) => Promise<unknown>;
};
/** The editor's window (same address as ClipForge): its API, how its start went, its own anchor elements. */
type EditorWindow = Window & {
  filmcraft?: Bridge;
  filmcraftLoad?: { fatal?: string; error?: string; readyMs?: number };
  HTMLAnchorElement: typeof HTMLAnchorElement;
  File: typeof File;
};

async function digest(bytes: ArrayBuffer): Promise<string> {
  try {
    return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return `${bytes.byteLength}`;
  }
}

/** FilmCraft's own editor on one version, inside ClipForge: the AI's FilmCraft edit (or the person's earlier save)
 * opens with its files, and Save in FilmCraft makes a new version of the video (FilmCraft renders it). Exports made
 * in the editor are downloaded. Only this computer's files of this video are used. */
function FilmCraftEditor({ v, revision, onClose, onSaved }: {
  v: Video; revision: number; onClose: () => void; onSaved: (v: Video) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [s, setS] = useState<EditorSession | null>(null);
  const [phase, setPhase] = useState<"loading" | "making" | "starting" | "opening" | "open" | "failed">("loading");
  const [note, setNote] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const base = useRef(v.plan_revision);
  const session = useRef<EditorSession | null>(null);
  const opened = useRef(false);
  const poll = useRef<number>(0);
  const last = useRef<{ digest: string; at: number }>({ digest: "", at: 0 });
  const saveRef = useRef<(name: string, bytes: ArrayBuffer) => Promise<void>>(async () => undefined);

  const load = useCallback(async (prepare: boolean) => {
    try {
      let got = await craft.editor(v.id, revision);
      if (!got.ready && prepare && !(got.job && ["queued", "running"].includes(got.job.status)))
        got = await craft.prepare(v.id, revision);
      session.current = got;
      setS(got);
      if (got.ready) setPhase((p) => (p === "loading" || p === "making" ? "starting" : p));
      else if (got.job?.status === "failed") { setPhase("failed"); setNote(got.job.error || "FilmCraft could not make the edit."); }
      else setPhase("making");
      return got;
    } catch (e) {
      setPhase("failed");
      setNote(errorText(e));
      return null;
    }
  }, [v.id, revision]);

  useEffect(() => { void load(true); }, [load]);
  useEffect(() => {  // follow the job that makes the AI's FilmCraft edit
    if (phase !== "making") return;
    const t = window.setInterval(() => { void load(false); }, 2000);
    return () => window.clearInterval(t);
  }, [phase, load]);

  const bridge = () => (frame.current?.contentWindow as unknown as { filmcraft?: Bridge } | null)?.filmcraft;

  const open = useCallback(async () => {
    const got = session.current;
    const fc = bridge();
    if (!got?.ready || !fc || !got.project || opened.current) return;
    opened.current = true;
    setPhase("opening");
    try {
      for (const m of got.media || []) {
        setNote(`Handing FilmCraft ${m.name}`);
        await fc.importUrl(m.url + (got.media_query || ""), m.name);
      }
      const res = await fetch(got.project, { headers: { "X-ClipFoundry": "1" } });
      if (!res.ok) throw await responseError(res);
      // a File made by the editor's own window: FilmCraft does not take one from another window
      const Made = (frame.current?.contentWindow as EditorWindow | null)?.File || File;
      await fc.openProject(new Made([await res.arrayBuffer()], got.project_name || "edit.fcproj"));
      setNote("");
      setPhase("open");
    } catch (e) {
      setPhase("failed");
      setNote(`FilmCraft could not open this version: ${errorText(e)}`);
    }
  }, []);
  const openRef = useRef(open);
  openRef.current = open;

  const save = useCallback(async (name: string, bytes: ArrayBuffer) => {
    if (!name.toLowerCase().endsWith(".fcproj")) {  // an export, captions, a frame: the person's download
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([bytes]));
      a.download = name;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      toast(`Saved ${name} to your downloads.`);
      return;
    }
    const d = await digest(bytes);
    if (d === last.current.digest && Date.now() - last.current.at < 15000) return;  // the same save, delivered twice
    last.current = { digest: d, at: Date.now() };
    setSaving(true);
    try {
      const url = `/api/studio/videos/${v.id}/filmcraft/save?revision=${revision}&base=${base.current}`;
      let res = await sendBytes(url, bytes);
      if (res.status === 409) {
        const j = await res.clone().json().catch(() => ({}));
        if (Array.isArray(j.need)) {  // files the person added in the editor: send them, then save again
          const fc = bridge();
          for (const n of j.need as string[]) {
            if (!fc) throw new Error("FilmCraft's editor closed.");
            const up = await sendBytes(`/api/studio/videos/${v.id}/filmcraft/files/${encodeURIComponent(n)}?revision=${revision}`,
              await fc.readFile(`/files/${n}`));
            if (!up.ok) throw await responseError(up);
          }
          res = await sendBytes(url, bytes);
        }
      }
      if (!res.ok) throw await responseError(res);
      const made = await res.json() as { revision: number; unchanged?: boolean; view: Video };
      setDirty(false);
      base.current = made.view.plan_revision;
      onSaved(made.view);
      toast(made.unchanged ? "Saved; nothing changed since this version." :
        `Saved as version ${made.revision}. FilmCraft is rendering its preview.`);
    } catch (e) {
      toast(`The FilmCraft save did not reach ClipForge: ${errorText(e)}`, true);
    }
    setSaving(false);
  }, [v.id, revision, onSaved]);
  saveRef.current = save;

  /** The editor's page loaded (again, when it restarts itself on WebGL2): take its project saves, then open the
   * version once FilmCraft has started. FilmCraft 0.17 offers a saved project as a browser download; ClipForge takes
   * those instead (exports still download). A FilmCraft with its own hand-over sends the messages below. */
  const onFrameLoad = useCallback(() => {
    const w = frame.current?.contentWindow as EditorWindow | null;
    window.clearInterval(poll.current);
    if (!w) return;
    try {
      const proto = w.HTMLAnchorElement.prototype;
      const click = proto.click;
      proto.click = function (this: HTMLAnchorElement) {
        if (/\.fcproj$/i.test(this.download || "") && this.href.startsWith("blob:")) {
          const name = this.download;
          void fetch(this.href).then((r) => r.arrayBuffer()).then((b) => saveRef.current(name, b))
            .catch((e) => toast(`The FilmCraft save did not reach ClipForge: ${errorText(e)}`, true));
          return;
        }
        click.call(this);
      };
    } catch { /* not this address: only the messages below */ }
    let errors = 0;
    let waited = 0;
    poll.current = window.setInterval(() => {
      waited += 1;
      const load = w.filmcraftLoad;
      errors = load?.error && !load.readyMs ? errors + 1 : 0;
      const failed = load?.fatal || (errors > 10 ? load?.error : "") ||
        (waited > 240 ? "FilmCraft's editor did not start in this window. It needs WebGPU or WebGL2." : "");
      if (failed) {
        window.clearInterval(poll.current);
        setPhase("failed");
        setNote(String(failed).split("\n\nStack:")[0].slice(0, 400));
      } else if (w.filmcraft && session.current?.ready) {
        window.clearInterval(poll.current);
        void openRef.current();
      }
    }, 500);
  }, []);
  useEffect(() => () => window.clearInterval(poll.current), []);

  /** ClipForge's own Save: FilmCraft saves the project under a ClipForge name, and that save comes back (above). */
  const saveNow = async () => {
    const fc = bridge();
    if (!fc?.execute) return;
    const path = `/projects/clipforge-version-${revision}.fcproj`;
    const before = last.current.at;
    try {
      await fc.execute("file.saveAs", { path });
      window.setTimeout(() => {  // nothing came back (a FilmCraft that keeps saves to itself): read it
        if (last.current.at !== before) return;
        fc.readFile(path).then((b) => saveRef.current(path.split("/").pop()!, b.slice().buffer as ArrayBuffer))
          .catch((e) => toast(`The FilmCraft save did not reach ClipForge: ${errorText(e)}`, true));
      }, 4000);
    } catch (e) {
      toast(`FilmCraft could not save: ${errorText(e)}`, true);
    }
  };

  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.source !== frame.current?.contentWindow) return;
      const d = (e.data || {}) as { type?: string; dirty?: boolean; error?: string; name?: string; bytes?: ArrayBuffer };
      if (d.type === "filmcraft:ready") void open();  // a FilmCraft with its own hand-over
      else if (d.type === "filmcraft:dirty") setDirty(!!d.dirty);
      else if (d.type === "filmcraft:failed") { setPhase("failed"); setNote(d.error || "FilmCraft's editor could not start."); }
      else if (d.type === "filmcraft:save" && d.bytes) void save(d.name || "edit.fcproj", d.bytes);
    };
    window.addEventListener("message", on);
    return () => window.removeEventListener("message", on);
  }, [open, save]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const close = () => {
    if (dirty && !window.confirm("FilmCraft has changes you have not saved. Close the editor anyway?")) return;
    onClose();
  };
  const showFrame = s?.ready && s.editor_ready && phase !== "failed";
  return (
    <Modal onClose={close} label={`FilmCraft editor, version ${revision}`} className="craft-editor" wide>
      <div className="craft-bar">
        <b>FilmCraft</b><span className="small muted">Version {revision}{s?.hand ? " (your FilmCraft save)" : ""}</span>
        {dirty && <Pill tone="warn">Unsaved changes</Pill>}
        {saving && <Pill>Saving…</Pill>}
        <span className="small muted craft-tip">Saving in FilmCraft (Ctrl or Cmd+S) makes a new version here.</span>
        <button type="button" className="btn btn-small btn-primary" disabled={phase !== "open" || saving}
          onClick={() => void saveNow()}><Icon name="check" />Save to ClipForge</button>
        <button type="button" className="btn btn-small" onClick={close}><Icon name="x" />Close</button>
      </div>
      {phase === "making" && <div className="craft-wait"><p>FilmCraft is editing version {revision}…</p>
        <ProgressBar value={s?.job?.progress || 0} label="Making the FilmCraft edit" />
        <p className="small muted">{s?.job?.message || "Waiting for a worker"}</p></div>}
      {phase === "failed" && <Banner tone="bad" title="FilmCraft's editor did not open">{note}</Banner>}
      {s && !s.editor_ready && <Banner tone="warn" title="FilmCraft's editor is not set up yet">Set it up in Settings,
        Editing apps.</Banner>}
      {(phase === "starting" || phase === "opening") && <p className="small muted craft-note">{note || "Starting FilmCraft…"}</p>}
      {showFrame && <iframe ref={frame} className="craft-frame" title="FilmCraft editor" src={s!.editor}
        onLoad={onFrameLoad} allow="fullscreen; clipboard-read; clipboard-write" />}
    </Modal>
  );
}

/** The editor page's FilmCraft panel: how final videos are made, what FilmCraft did in the newest one, and
 * FilmCraft's own editor on the current version. */
export function FilmCraftPanel({ v, onSaved }: { v: Video; onSaved: (v: Video) => void }) {
  const [st, setSt] = useState<CraftStatus | null>(null);
  const [editing, setEditing] = useState(false);
  useEffect(() => { craft.status().then(setSt).catch(() => setSt(null)); }, []);
  const rev = v.plan_revision;
  const latest = v.artifacts.find((a) => a.kind === "final");
  const film = st?.apps.find((a) => a.key === "filmcraft");
  const filmReady = !!film?.cli.ready;
  const hand = !!v.plan?.filmcraft;
  const engineText = !st ? "" : hand ? "This version was finished by hand in FilmCraft, so FilmCraft renders it." :
    st.engine === "ffmpeg" ? "Final videos are made with the built-in editor (Settings, Editing apps)." :
    filmReady ? "Final videos are edited and rendered in FilmCraft: ClipForge's cut, with its look and sound made " +
      "with FilmCraft's tools and an animated title from EffectCraft" +
      (st.ai_finish ? ", and the AI's finishing when an AI helper is set up." : ".") :
    st.task.state === "running" ? "FilmCraft is being set up; until then final videos are made with the built-in editor." :
    "FilmCraft is not set up yet, so final videos are made with the built-in editor.";
  return (
    <section className="panel" aria-labelledby="vr-filmcraft"><h2 id="vr-filmcraft">FilmCraft</h2>
      <p className="small">{engineText}{st && !filmReady && !st.online && <> <a className="textlink" href="#/settings/apps">
        Editing apps settings</a></>}</p>
      {latest && <p className="small"><b>Version {latest.revision}:</b> <MadeWithLine m={latest} /></p>}
      {st?.editor && <div className="row-actions wrap">
        <button type="button" className="btn" disabled={!rev || !filmReady} onClick={() => setEditing(true)}>
          <Icon name="edit" />Edit version {rev || "…"} in FilmCraft</button></div>}
      {st && !st.editor && !st.online && <p className="small muted">FilmCraft&apos;s editor appears here once it is set up
        (Settings, Editing apps).</p>}
      {hand && <p className="small muted">Editing this version in ClipForge starts again from ClipForge&apos;s own cut;
        your FilmCraft version stays in Versions.</p>}
      <Disclosure summary="Other ways to finish it in FilmCraft"><FinishInFilmCraft v={v} /></Disclosure>
      {editing && <FilmCraftEditor v={v} revision={rev} onClose={() => setEditing(false)} onSaved={onSaved} />}
    </section>
  );
}

/** Finish a version by hand in the FilmCraft desktop app, the free open-source editor from the ArtCraft team (colour,
 * keyframes, titles, mixing). ClipForge writes the cut as an OpenTimelineIO timeline with SRT captions next to the
 * video and FilmCraft opens it; the files stay where they are. The online studio offers the timeline as a download. */
export function FinishInFilmCraft({ v }: { v: Video }) {
  const [st, setSt] = useState<FilmCraftStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<FilmCraftOpen | null>(null);
  const rev = v.plan_revision;

  useEffect(() => { studio.filmcraft().then(setSt).catch(() => setSt(null)); }, []);

  const open = async (reveal: boolean) => {
    setBusy(true);
    try {
      const r = await studio.openInFilmCraft(v.id, rev, reveal);
      setLast(r);
      if (reveal) toast(r.revealed ? "Showing the timeline files." : `The timeline files are in ${r.folder}`);
      else if (r.opened) toast(r.how === "project" ? `Opening version ${r.revision} in FilmCraft as a project.` :
        `Opening version ${r.revision} in FilmCraft. It imports the timeline and captions.`);
      else if (!r.installed) toast("The FilmCraft desktop app is not installed on this computer. The timeline is saved.", true);
      else toast(`The FilmCraft project is ready: ${r.project}`);
      if (r.warnings.length) toast(r.warnings[0], true);
      setSt(await studio.filmcraft());
    } catch (e) {
      toast(errorText(e), true);
    }
    setBusy(false);
  };

  const local = st?.available !== false;
  return (
    <div>
      <p className="small muted">Open version {rev || "…"} in the FilmCraft desktop app, or take the timeline to any editor
        that reads OpenTimelineIO. Nothing is uploaded.</p>
      {!local && st?.message && <p className="small">{st.message}</p>}
      <div className="row-actions wrap">
        {local && st?.installed && <button type="button" className="btn btn-small" disabled={busy || !rev}
          onClick={() => void open(false)}><Icon name="external" />Open in the FilmCraft app</button>}
        {local && <button type="button" className="btn btn-small" disabled={busy || !rev} onClick={() => void open(true)}>
          <Icon name="folder" />Show the timeline files</button>}
        <a className="btn btn-small" href={`/api/studio/videos/${v.id}/timeline.zip?revision=${rev}`}>
          <Icon name="zip" />Timeline with media (.zip)</a>
      </div>
      {st?.installed && <p className="small muted">Found the FilmCraft app{st.version ? ` ${st.version}` : ""}.</p>}
      {last && last.not_carried.length > 0 && <Disclosure summary="What to redo by hand in FilmCraft">
        <ul className="small">{last.not_carried.map((x) => <li key={x}>{x}</li>)}</ul></Disclosure>}
    </div>
  );
}
